"""Versioned graph scale comparison; all inputs are synthetic, all errors retained."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import math
import platform
import statistics
import subprocess
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

from .fixtures import edges, fingerprint, metadata, nodes, oracle, questions, scope_id
from .provenance import ROOT, manifest, save, verify_manifest
from .stores import BudgetExceeded, Store

PROJECT = "jjamtong-graph-scale-lab"
COMPOSE = ROOT / "experiments/graph_scale_lab/compose.yaml"
SCALES = ((10000, 2), (10000, 6), (100000, 2), (100000, 6))
REPETITIONS = 20
WARMUPS = 2
DEFAULT_OUTPUT = ".local/graph-scale-lab/run.json"


class MeasurementFailure(RuntimeError):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(json.dumps(evidence, sort_keys=True))


def command(args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def compose(*args):
    return command(["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args])


def containers():
    return set(command(["docker", "ps", "-q"]).split())


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def result_hash(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def plan_operators(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("operatorType", "Node Type"):
                yield item
            yield from plan_operators(item)
    elif isinstance(value, list):
        for item in value:
            yield from plan_operators(item)


def check_plans(engine, plans, n):
    if [item["question"] for item in plans] != questions(n):
        raise ValueError("native plans missing or unexpected")
    for item in plans:
        operators = list(plan_operators(item["plan"]["plan"]))
        if not operators:
            raise ValueError("execution plan is empty")
        if engine == "neo4j" and item["question"]["depth"] > 1:
            if not any("VarLengthExpand(Pruning" in op for op in operators):
                raise ValueError("Neo4j native baseline did not use endpoint pruning")
        if engine == "postgres" and "Recursive Union" not in operators:
            raise ValueError("PostgreSQL native baseline did not use recursive union")


class Resources:
    """One-second Docker samples, separate from latency measurements."""
    def __init__(self, container):
        self.container = container
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.collect, daemon=True)

    def collect(self):
        while not self.stop.is_set():
            try:
                # Docker reports CPU %, memory usage and configured limit as strings.
                raw = command(["docker", "stats", "--no-stream", "--format", "{{json .}}", self.container])
                value = json.loads(raw)
                self.samples.append({"at_monotonic": time.monotonic(),
                                     "cpu_percent": float(value["CPUPerc"].strip("%")),
                                     "memory": value["MemUsage"]})
            except Exception as exc:
                self.samples.append({"error": repr(exc)})
            self.stop.wait(1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=10)


def expected_cases(n, density):
    inputs, checks = [], []
    for revision in ("old", "new"):
        meta = metadata(revision, size=n, density=density)
        rows = edges(n, density, revision)
        sid = scope_id(meta)
        inputs.append((sid, meta, nodes(n), rows))
        for question in questions(n):
            answer = oracle(rows, **{k: v for k, v in question.items() if k != "label"})
            checks.append({"revision": revision, "scope": sid, "question": question,
                           "expected": answer})
    # Other repository/config and another artifact of the SAME commit/build.
    for meta in (metadata(repo="synthetic/other", size=n, density=density),
                 metadata(config="partial", size=n, density=density),
                 metadata(artifact="synthetic-other-artifact", size=n, density=density)):
        rows = edges(64, 2)
        inputs.append((scope_id(meta), meta, nodes(64), rows))
        question = questions(64)[0]
        checks.append({"revision": "decoy", "scope": scope_id(meta), "question": question,
                       "expected": oracle(rows, 0, 1)})
    return inputs, checks


def measure(store, case, mode):
    started = time.perf_counter()
    try:
        ids, trips = store.traverse(case["scope"], case["question"], mode=mode)
    except BudgetExceeded as exc:
        return {"status": "budget_exceeded", "ms": (time.perf_counter() - started) * 1000,
                "code": getattr(exc, "code", type(exc).__name__), "error": str(exc)}
    except Exception as exc:
        raise MeasurementFailure({"engine": store.name, "scope": case["scope"],
                                  "question": case["question"], "mode": mode,
                                  "ms": (time.perf_counter() - started) * 1000,
                                  "code": getattr(exc, "code", getattr(exc, "sqlstate", type(exc).__name__)),
                                  "error": str(exc)}) from exc
    elapsed = (time.perf_counter() - started) * 1000
    if ids != case["expected"]:
        raise MeasurementFailure({"engine": store.name, "scope": case["scope"],
                                  "question": case["question"], "mode": mode,
                                  "ms": elapsed, "code": "wrong_reachability",
                                  "actual_count": len(ids), "actual_sha256": result_hash(ids),
                                  "expected_count": len(case["expected"]),
                                  "expected_sha256": result_hash(case["expected"])})
    return {"status": "correct", "ms": elapsed, "count": len(ids),
            "sha256": result_hash(ids), "round_trips": trips}


def summarize(samples):
    correct = [s["ms"] for s in samples if s["status"] == "correct"]
    return {"correct": len(correct), "budget_exceeded": len(samples) - len(correct),
            "p50_ms": statistics.median(correct) if correct else None,
            "p95_ms": percentile(correct, .95) if correct else None}


def sequential(store, cases, mode, results, checkpoint):
    for case in cases:
        item = {k: v for k, v in case.items() if k != "expected"}
        item.update({"mode": mode, "expected_count": len(case["expected"]),
                     "expected_sha256": result_hash(case["expected"])})
        results.append(item)
        if case["revision"] == "decoy":
            item["warmups"], item["samples"] = [], [measure(store, case, mode)]
        else:
            item["warmups"] = [measure(store, case, mode) for _ in range(WARMUPS)]
            # A native budget failure is evidence, not a cue to hammer it 20 times.
            count = 1 if any(s["status"] != "correct" for s in item["warmups"]) else REPETITIONS
            item["samples"] = [measure(store, case, mode) for _ in range(count)]
        item["summary"] = summarize(item["samples"])
        checkpoint()
        print(json.dumps({"query": store.name, "mode": mode, "revision": case["revision"],
                          "label": case["question"]["label"], **item["summary"]}), flush=True)
    return results


def concurrent_queries(kind, cases, clients, mode):
    # All connections established before releasing the barrier; six operations/client.
    selected = [c for c in cases if c["revision"] == "old"]
    released = []
    barrier = threading.Barrier(clients + 1, action=lambda: released.append(time.perf_counter()), timeout=60)

    def worker(index):
        with Store(kind) as store:
            barrier.wait()
            values = []
            for offset in range(6):
                case = selected[(index + offset) % len(selected)]
                values.append({"label": case["question"]["label"],
                               **measure(store, case, mode)})
            return values

    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as executor:
        futures = [executor.submit(worker, i) for i in range(clients)]
        barrier.wait()
        samples = [sample for future in futures for sample in future.result()]
        elapsed = time.perf_counter() - released[0]
    return {"clients": clients, "mode": mode, "operations_per_client": 6,
            "elapsed_seconds": elapsed, "completed_ops_per_second": len(samples) / elapsed,
            "samples": samples, "summary": summarize(samples)}


def execute_case(store, n, density, container, record, checkpoint):
    inputs, cases = expected_cases(n, density)
    record.update({"engine": store.name, "methods_per_build": n, "local_static_degree": density,
                   "input_sha256": fingerprint(n, density), "scopes": [], "status": "running",
                   "stage": "clear"})
    store.clear_data()
    with Resources(container) as usage:
        started = time.perf_counter()
        for sid, meta, node_rows, edge_rows in inputs:
            record["stage"] = "load:" + sid
            scope_started = time.perf_counter()
            store.load(sid, meta, node_rows, edge_rows)
            counts = store.counts(sid)
            if counts != {"nodes": len(node_rows), "edges": len(edge_rows)}:
                raise AssertionError("ingestion counts differ")
            record["scopes"].append({"id": sid, "metadata": meta, **counts,
                                     "load_seconds": time.perf_counter() - scope_started})
        record["load_seconds"] = time.perf_counter() - started
    record["ingestion_resources"] = usage.samples
    store.prepare_read()
    record["stage"] = "scope_checks"
    # New graphs are ready only after complete ingestion/count checks.
    unknown = {"scope": "unknown-immutable-scope", "question": questions(n)[0], "expected": []}
    for mode in ("native", "frontier"):
        if measure(store, unknown, mode)["status"] != "correct":
            raise AssertionError("unknown scope did not return empty")
        try:
            store.traverse("", questions(n)[0], mode=mode)
        except ValueError:
            pass
        else:
            raise AssertionError("unscoped graph query was accepted")
    record["scope_checks"] = {"unknown_empty": True, "missing_rejected": True}
    record["plans"] = [{"question": case["question"],
                        "plan": store.explain(case["scope"], case["question"])}
                       for case in cases if case["revision"] == "old"]
    check_plans(store.name, record["plans"], n)
    record["sequential"], record["concurrent"] = [], []
    with Resources(container) as usage:
        for mode in ("native", "frontier"):
            record["stage"] = "sequential:" + mode
            sequential(store, cases, mode, record["sequential"], checkpoint)
        for mode in ("native", "frontier"):
            for clients in (1, 4, 8):
                record["stage"] = "concurrent:%s:%s" % (mode, clients)
                record["concurrent"].append(concurrent_queries(store.name, cases, clients, mode))
                checkpoint()
    record["query_resources"] = usage.samples
    record["allocated_database_size_bytes_after_volume_reuse"] = store.size_bytes()
    directory = "/var/lib/postgresql/data" if store.name == "postgres" else "/data"
    record["allocated_data_directory_kib_after_volume_reuse"] = int(command(["docker", "exec", container, "du", "-sk", directory]).split()[0])
    record.update(status="complete", stage="complete")
    return record


def run(output):
    import psycopg  # Fail dependency checks before starting any containers.
    output = ROOT / output
    if output.exists():
        raise ValueError("choose a new output path; never overwrite a measured run")
    pinned = manifest()
    before = containers()
    if compose("ps", "-q"):
        raise ValueError("dedicated graph lab already running; inspect before resuming")
    record = {"schema": "graph-scale-run/v1", "run_id": uuid.uuid4().hex, **pinned,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "environment": {"host": platform.platform(), "python": platform.python_version(),
                              "docker": command(["docker", "version", "--format", "{{.Server.Version}}"]),
                              "docker_memory_bytes": int(command(["docker", "info", "--format", "{{.MemTotal}}"])),
                              "unrelated_container_ids": sorted(before)},
              "settings": {"warmups": WARMUPS, "repetitions": REPETITIONS, "native_budget_seconds": 10,
                           "cpus": 1, "memory_bytes": 1073741824, "load_order": ["postgres", "neo4j"],
                           "concurrency": [1, 4, 8], "cold_cache_controlled": False},
              "images": {}, "cases": [], "status": "running",
              "case_plan": [{"engine": kind, "methods_per_build": n, "local_static_degree": density,
                             "status": "pending"} for kind in ("postgres", "neo4j") for n, density in SCALES]}
    save(output, record)
    try:
        for kind in ("postgres", "neo4j"):
            compose("up", "-d", kind)
            container = compose("ps", "-q", kind)
            image = json.loads(command(["docker", "inspect", container]))[0]
            info = json.loads(command(["docker", "image", "inspect", image["Image"]]))[0]
            record["images"][kind] = {"id": image["Image"], "digests": info.get("RepoDigests"),
                                      "memory_limit": image["HostConfig"]["Memory"],
                                      "nano_cpus": image["HostConfig"]["NanoCpus"]}
            deadline = time.monotonic() + 120
            while True:
                try:
                    with Store(kind) as store:
                        if kind == "postgres":
                            store._execute("SELECT 1")
                        else:
                            store._cypher("RETURN 1")
                    break
                except (OSError, psycopg.OperationalError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            with Store(kind) as store:
                store.reset_schema()
                for n, density in SCALES:
                    active = next(item for item in record["case_plan"] if
                                  (item["engine"], item["methods_per_build"], item["local_static_degree"]) == (kind, n, density))
                    active["status"] = "running"
                    case = {}
                    record["cases"].append(case)
                    execute_case(store, n, density, container, case, lambda: save(output, record))
                    active["status"] = "complete"
                    save(output, record)
            compose("stop", kind)
        record["status"] = "complete"
    except BaseException as exc:
        record["status"] = "failed"
        record["error"] = repr(exc)
        if isinstance(exc, MeasurementFailure):
            record["failure"] = exc.evidence
        for item in record["case_plan"]:
            if item["status"] == "running":
                item["status"] = "failed"
        if record["cases"] and record["cases"][-1].get("status") == "running":
            record["cases"][-1]["status"] = "failed"
        raise
    finally:
        try:
            compose("down")  # Preserve named volumes; touch this project only.
            record["cleanup"] = {"lab_containers_removed": not bool(compose("ps", "-q")),
                                 "unrelated_still_running": before <= containers()}
        finally:
            record["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save(output, record)


def validate(record):
    verify_manifest(record)
    if record["schema"] != "graph-scale-run/v1" or record["status"] != "complete":
        raise ValueError("run incomplete")
    wanted = {(kind, n, density) for kind in ("postgres", "neo4j") for n, density in SCALES}
    keys = [(c["engine"], c["methods_per_build"], c["local_static_degree"]) for c in record["cases"]]
    if len(keys) != len(wanted) or set(keys) != wanted:
        raise ValueError("missing or duplicate engine/scale case")
    for case in record["cases"]:
        n, density = case["methods_per_build"], case["local_static_degree"]
        inputs, checks = expected_cases(n, density)
        if case["input_sha256"] != fingerprint(n, density):
            raise ValueError("input fingerprint mismatch")
        scopes = case["scopes"]
        if len(scopes) != len(inputs):
            raise ValueError("scope count mismatch")
        for scope, (sid, meta, node_rows, edge_rows) in zip(scopes, inputs):
            if (scope["id"], scope["metadata"], scope["nodes"], scope["edges"]) != (sid, meta, len(node_rows), len(edge_rows)):
                raise ValueError("scope ingestion evidence mismatch")
        if case["scope_checks"] != {"unknown_empty": True, "missing_rejected": True}:
            raise ValueError("scope checks incomplete")
        check_plans(case["engine"], case["plans"], n)
        expected_queries = {(mode, c["scope"], c["question"]["label"]): c for mode in ("native", "frontier") for c in checks}
        seen = set()
        for item in case["sequential"]:
            key = (item["mode"], item["scope"], item["question"]["label"])
            if key in seen or key not in expected_queries:
                raise ValueError("unexpected/duplicate query")
            seen.add(key)
            expected = expected_queries[key]
            if item["question"] != expected["question"] or item["expected_sha256"] != result_hash(expected["expected"]) or item["expected_count"] != len(expected["expected"]):
                raise ValueError("query oracle mismatch")
            required = 1 if item["revision"] == "decoy" or any(s["status"] != "correct" for s in item["warmups"]) else REPETITIONS
            if len(item["samples"]) != required or len(item["warmups"]) != (0 if item["revision"] == "decoy" else WARMUPS):
                raise ValueError("query repetitions incomplete")
            for sample in item["warmups"] + item["samples"]:
                check_sample(sample, len(expected["expected"]), result_hash(expected["expected"]))
            if item["summary"] != summarize(item["samples"]):
                raise ValueError("summary mismatch")
        if seen != set(expected_queries):
            raise ValueError("queries incomplete")
        old = {c["question"]["label"]: c["expected"] for c in checks if c["revision"] == "old"}
        if [(r["mode"], r["clients"]) for r in case["concurrent"]] != [(mode, c) for mode in ("native", "frontier") for c in (1, 4, 8)]:
            raise ValueError("concurrency cases incomplete")
        for result in case["concurrent"]:
            if result["operations_per_client"] != 6 or result["elapsed_seconds"] <= 0 or not math.isfinite(result["elapsed_seconds"]):
                raise ValueError("invalid concurrent measurement")
            if len(result["samples"]) != result["clients"] * 6:
                raise ValueError("concurrent samples incomplete")
            if not math.isclose(result["completed_ops_per_second"], len(result["samples"]) / result["elapsed_seconds"], rel_tol=1e-12):
                raise ValueError("concurrent rate mismatch")
            if Counter(s["label"] for s in result["samples"]) != Counter({label: result["clients"] for label in old}):
                raise ValueError("concurrent question distribution incomplete")
            for sample in result["samples"]:
                expected = old[sample["label"]]
                check_sample(sample, len(expected), result_hash(expected))
            if result["summary"] != summarize(result["samples"]):
                raise ValueError("concurrent summary mismatch")
    if not all(record["cleanup"].values()):
        raise ValueError("cleanup/isolation check failed")
    return {"status": "verified", "cases": len(keys), "run_id": record["run_id"]}


def check_sample(sample, count, digest):
    if sample["ms"] < 0 or not math.isfinite(sample["ms"]):
        raise ValueError("invalid timing")
    if sample["status"] == "correct":
        if sample["count"] != count or sample["sha256"] != digest or sample["round_trips"] < 1:
            raise ValueError("wrong query result")
    elif sample["status"] == "budget_exceeded":
        if sample["code"] not in ("57014", "Neo.ClientError.Transaction.TransactionTimedOut", "application.deadline"):
            raise ValueError("unexpected timeout classification")
    else:
        raise ValueError("unexpected sample status")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "validate"))
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.action == "run":
        run(args.output)
    else:
        print(json.dumps(validate(json.loads((ROOT / args.output).read_text()))))


if __name__ == "__main__":
    main()
