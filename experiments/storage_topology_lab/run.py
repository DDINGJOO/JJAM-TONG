"""Run four single-engine and twelve directed authority/projection topologies."""
import argparse
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from experiments.storage_lab.fixtures import dataset, record
from experiments.storage_lab.provenance import source_hashes
from experiments.storage_lab.run import COMPOSE, IMAGES, ROOT, command, correctness, ready
from experiments.storage_lab.stores import HTTP, STORES
from .authority import Conflict, Journal, digest, load, publish, stage, view

ENGINES = tuple(STORES)
CASES = [(p, q) for p in ENGINES for q in ENGINES]
CHECKS = ("staged-without-catalog-is-missing", "empty-projection-is-partial",
          "partial-projection-is-partial", "complete-projection-is-ready",
          "same-catalog-retry-is-idempotent", "conflicting-catalog-rejected",
          "unknown-catalog-has-no-latest-fallback", "wrong-artifact-is-partial",
          "worker-exit-73-before-ack", "replay-after-lost-ack-is-idempotent",
          "authority-outage-is-unavailable", "authority-restart-retains-snapshot",
          "rebuild-from-authority-only", "tombstone-then-older-replay-stays-deleted")
PAIR_CHECKS = ("projection-outage-is-unavailable", "publish-while-projection-is-down",
               "projection-restart-catches-up-from-authority")
QUERY_CHECKS = ("static-forward-1", "static-forward-3", "static-forward-6",
                "higher-degree-dispatcher", "reverse-impact-with-cycle", "infra-vpc-rds-s3",
                "same-commit-different-artifact", "different-analysis-configuration",
                "unknown-build-is-empty", "fulltext-timeout", "late-record-known-time",
                "error-group-by-service", "tenant-filter-alpha-vs-beta",
                "actual-trace-stays-observed", "missing-query-scope-rejected")


class PerRequestHTTP(HTTP):
    """No idle keep-alive survives long restart scenarios; never retry writes."""
    def request(self, *args, **kwargs):
        try:
            return super().request(*args, **kwargs)
        finally:
            self.close()


def compose(*args):
    return command(COMPOSE + ["-p", "jjamtong-topology-lab"] + list(args)).stdout.strip()


def fresh(name):
    s = ready(name)
    if hasattr(s, "http"):
        port, auth = s.http.connection.port, s.http.auth
        s.http.close()
        s.http = PerRequestHTTP(port, auth)
    if name == "elasticsearch":
        s.index = "jjamtong-topology-evidence"
    return s


def reset_projection(store):
    if store.name != "neo4j":
        store.reset()
        return
    # The old engine lab reset deletes all labels. Preserve the authoritative
    # journal in this lab, including in the single-Neo4j configuration.
    while store.cypher("MATCH (n:Evidence) WITH n LIMIT 1000 DETACH DELETE n RETURN count(*)")[0][0]:
        pass
    store.cypher("CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE")
    store.cypher("CREATE INDEX evidence_scope IF NOT EXISTS FOR (n:Evidence) ON (n.tenant,n.build,n.analysis,n.kind)")
    store.cypher("CREATE FULLTEXT INDEX event_text IF NOT EXISTS FOR (n:Event) ON EACH [n.message]")
    store.cypher("CALL db.awaitIndexes(60)")


def project(primary, projection, catalog, crash=False):
    source, sink = fresh(primary), fresh(projection)
    try:
        rows = load(Journal(source), catalog)
        if rows is None:
            raise RuntimeError("unknown catalog")
        sink.put(rows)
        sink.flush()
        if crash:
            os._exit(73)  # Deliberately lose the process result after applying.
    finally:
        source.close()
        sink.close()


def race_probe(name):
    """Separate connections and a barrier; no application serialization."""
    def race(values, raw=False):
        barrier = threading.Barrier(2)
        def attempt(value):
            store = fresh(name)
            try:
                journal = Journal(store)
                barrier.wait(timeout=20)
                if raw:
                    journal.append_clickhouse("probe-raw", value)
                else:
                    journal.claim("probe-" + ("same" if values[0] == values[1] else "different"), value)
                return "accepted"
            except Conflict:
                return "conflict"
            finally:
                store.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, values))
    if name == "clickhouse":
        outcomes = race([{"value": "A"}, {"value": "B"}], raw=True)
        store = fresh(name)
        try:
            retained = store.sql("SELECT count(DISTINCT payload) AS n FROM topology_authority WHERE id='probe-raw' FORMAT JSONEachRow")[0]["n"]
            if int(retained) != 2 or outcomes != ["accepted", "accepted"]:
                raise AssertionError("ClickHouse uniqueness counterexample did not reproduce")
            try:
                Journal(store).get("probe-raw")
            except Conflict:
                return {"status": "unsupported", "reason": "plain MergeTree has no native create-only identity gate in this adapter", "retained_conflicting_payloads": 2}
            raise AssertionError("conflicting CH identities were silently accepted on read")
        finally:
            store.close()
    same = race([{"value": "A"}, {"value": "A"}])
    different = race([{"value": "A"}, {"value": "B"}])
    if same != ["accepted", "accepted"] or sorted(different) != ["accepted", "conflict"]:
        raise AssertionError((name, same, different))
    return {"status": "passed", "same_content": same, "different_content": sorted(different)}


def scenario(primary, projection, repetitions):
    names = sorted({primary, projection})
    source = sink = None
    checks, metrics = [], {}
    def check(label, actual, expected):
        if actual != expected:
            raise AssertionError((label, actual, expected))
        checks.append(label)
    def measure(label, action):
        start = time.perf_counter()
        result = action()
        metrics[label] = (time.perf_counter() - start) * 1000
        return result
    try:
        compose("up", "-d", *names)
        if sorted(compose("ps", "--services", "--status", "running").splitlines()) != names:
            raise RuntimeError("unexpected engine in dedicated topology project")
        source, sink = fresh(primary), fresh(projection)
        reset_projection(sink)
        journal = Journal(source)
        journal.reset()
        rows = dataset(25, 20)
        base_digest = digest(rows)
        capability = race_probe(primary)
        stage(journal, rows[:100])
        check(CHECKS[0], view(journal, sink, "import-1"), "missing")
        measure("publish_snapshot_ms", lambda: publish(journal, "import-1", rows))
        check(CHECKS[1], view(journal, sink, "import-1"), "partial")
        sink.put([r for r in rows if r["kind"] == "node"])
        sink.flush()
        check(CHECKS[2], view(journal, sink, "import-1"), "partial")
        measure("initial_projection_ms", lambda: (sink.put(rows), sink.flush()))
        check(CHECKS[3], view(journal, sink, "import-1"), "ready")
        query_checks = correctness(sink, rows)
        publish(journal, "import-1", rows)
        check(CHECKS[4], view(journal, sink, "import-1"), "ready")
        try:
            publish(journal, "import-1", rows + [record("alpha", "build-A", "event", "conflict")])
        except Conflict:
            checks.append(CHECKS[5])
        else:
            raise AssertionError("catalog overwrite succeeded")
        check(CHECKS[6], view(journal, sink, "unknown"), "missing")
        wrong = dict(next(r for r in rows if r["kind"] == "event"), artifact="sha256:wrong", seq=2)
        sink.put([wrong]); sink.flush()
        check(CHECKS[7], view(journal, sink, "import-1"), "partial")
        reset_projection(sink)
        worker = command([sys.executable, "-m", "experiments.storage_topology_lab.run", "worker", "--primary", primary, "--projection", projection, "--catalog", "import-1"], check=False)
        check(CHECKS[8], worker.returncode, 73)
        project(primary, projection, "import-1")
        check(CHECKS[9], view(journal, sink, "import-1"), "ready")
        catalog = "import-1"
        if primary != projection:
            sink.close(); sink = None
            compose("stop", projection)
            unavailable = fresh_unconnected(projection)
            try:
                check(PAIR_CHECKS[0], view(journal, unavailable, catalog), "unavailable")
            finally:
                unavailable.close()
            rows = sorted(rows + [record("alpha", "build-A", "event", "during-outage", message="synthetic outage backlog", level="ERROR", service="board")], key=lambda r: r["id"])
            catalog = "import-2"
            publish(journal, catalog, rows)
            check(PAIR_CHECKS[1], load(journal, catalog), rows)
            compose("start", projection)
            sink = fresh(projection)
            project(primary, projection, catalog)
            check(PAIR_CHECKS[2], view(journal, sink, catalog), "ready")
        source.close(); source = None
        if primary == projection:
            sink.close(); sink = None
        compose("stop", primary)
        unavailable_source = fresh_unconnected(primary)
        try:
            check(CHECKS[10], view(Journal(unavailable_source), sink, catalog), "unavailable")
        finally:
            unavailable_source.close()
        compose("start", primary)
        source = fresh(primary); journal = Journal(source)
        if primary == projection:
            sink = fresh(projection)
        check(CHECKS[11], load(journal, catalog), rows)
        # Destroy the derived model. Rebuild uses only DB-retained input;
        # neither the original fixture nor an external PostgreSQL is consulted.
        reset_projection(sink)
        measure("rebuild_projection_ms", lambda: project(primary, projection, catalog))
        check(CHECKS[12], view(journal, sink, catalog), "ready")
        old = next(r for r in rows if r["kind"] == "event")
        rows = [dict(r, seq=2, deleted=1) if r["id"] == old["id"] else r for r in rows]
        publish(journal, "import-deleted", rows)
        project(primary, projection, "import-deleted")
        sink.put([old]); sink.flush()
        check(CHECKS[13], view(journal, sink, "import-deleted"), "ready")
        samples = []
        for _ in range(repetitions):
            start = time.perf_counter()
            if view(journal, sink, "import-deleted") != "ready":
                raise AssertionError("final snapshot is incomplete")
            samples.append((time.perf_counter() - start) * 1000)
        metrics["validated_view_samples_ms"] = samples
        expected = set(CHECKS + (PAIR_CHECKS if primary != projection else ()))
        if set(checks) != expected or len(checks) != len(expected):
            raise AssertionError("scenario checklist drift")
        return {"authority": primary, "projection": projection, "status": "passed", "checks": checks, "query_checks": query_checks,
                "capability": capability, "fixture_sha256": base_digest, "fixture_rows": len(dataset(25, 20)), "metrics": metrics}
    finally:
        if source:
            source.close()
        if sink:
            sink.close()
        compose("stop", *names)


def fresh_unconnected(name):
    # PostgreSQL connects eagerly. Represent a failed connection with the same
    # read failure the caller would observe; other engines fail on HTTP read.
    try:
        return STORES[name]()
    except Exception as error:
        from psycopg import OperationalError
        if not isinstance(error, OperationalError):
            raise
        class Disconnected:
            name = "postgres"
            def sql(self, *args):
                raise OperationalError("authority database is stopped")
            def select(self, *args):
                raise OperationalError("projection database is stopped")
            def close(self):
                pass
        return Disconnected()


def hashes():
    import hashlib
    result = {"experiments/storage_lab/" + name: value for name, value in source_hashes().items()}
    for path in sorted((ROOT / "experiments/storage_topology_lab").glob("*.py")):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate(report):
    import hashlib
    import re
    if report["schema"] != 1 or report["status"] != "passed":
        raise ValueError("incomplete report")
    if report["source_sha256"] != hashes():
        raise ValueError("measurement sources changed")
    if (not re.fullmatch(r"[0-9a-f]{32}", report["run_id"]) or
            not re.fullmatch(r"[0-9a-f]{40}", report["git_commit"]) or
            report["source_tree_dirty"] is not False or report["repetitions"] < 1):
        raise ValueError("missing execution identity")
    for path, expected_hash in report["source_sha256"].items():
        blob = command(["git", "show", report["git_commit"] + ":" + path]).stdout
        if hashlib.sha256(blob.encode()).hexdigest() != expected_hash:
            raise ValueError("source does not match measurement commit: " + path)
    results = report["results"]
    if set(report["images"]) != set(ENGINES) or any(not v.get("id") or not v.get("digests") or v.get("tag") != IMAGES[k] for k, v in report["images"].items()):
        raise ValueError("missing image identity")
    if len(results) != 16 or {(r["authority"], r["projection"]) for r in results} != set(CASES):
        raise ValueError("all four singles and twelve directed pairs required")
    for r in results:
        if r["run_id"] != report["run_id"] or r["git_commit"] != report["git_commit"]:
            raise ValueError("mixed execution results")
        expected = set(CHECKS + (PAIR_CHECKS if r["authority"] != r["projection"] else ()))
        if r["status"] != "passed" or set(r["checks"]) != expected or len(r["checks"]) != len(expected):
            raise ValueError("missing topology checks")
        if r["fixture_sha256"] != digest(dataset(25, 20)) or r["fixture_rows"] != len(dataset(25, 20)):
            raise ValueError("fixture mismatch")
        if set(r["query_checks"]) != set(QUERY_CHECKS) or len(r["query_checks"]) != len(QUERY_CHECKS):
            raise ValueError("missing query checks")
        required = "unsupported" if r["authority"] == "clickhouse" else "passed"
        if r["capability"]["status"] != required:
            raise ValueError("capability classification mismatch")
        if required == "unsupported":
            if r["capability"]["retained_conflicting_payloads"] != 2:
                raise ValueError("missing uniqueness counterexample")
        elif (r["capability"]["same_content"] != ["accepted", "accepted"] or
              r["capability"]["different_content"] != ["accepted", "conflict"]):
            raise ValueError("native uniqueness probe failed")
        samples = r["metrics"]["validated_view_samples_ms"]
        if len(samples) != report["repetitions"] or any(not isinstance(n, (int, float)) or not 0 <= n < 1e9 for n in samples):
            raise ValueError("invalid latency samples")
    return {"topologies": 16, "single": 4, "directed_pairs": 12,
            "workflow_checks": sum(len(r["checks"]) for r in results), "query_checks": sum(len(r["query_checks"]) for r in results),
            "native_uniqueness_passed": 12, "native_uniqueness_unsupported": 4}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "worker", "validate"))
    parser.add_argument("--primary", choices=ENGINES)
    parser.add_argument("--projection", choices=ENGINES)
    parser.add_argument("--catalog")
    parser.add_argument("--output", default="results/storage-topology-lab/run.json")
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.mode == "worker":
        project(args.primary, args.projection, args.catalog, crash=True)
        return
    path = ROOT / args.output
    if args.mode == "validate":
        print(json.dumps(validate(json.loads(path.read_text())), indent=2))
        return
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    if command(["git", "status", "--porcelain", "--", "experiments/storage_lab", "experiments/storage_topology_lab"]).stdout.strip():
        raise RuntimeError("commit measurement sources before running")
    if path.exists():
        raise RuntimeError("choose a new output path; do not overwrite run evidence")
    report = {"schema": 1, "status": "running", "run_id": uuid.uuid4().hex, "git_commit": command(["git", "rev-parse", "HEAD"]).stdout.strip(),
              "source_sha256": hashes(), "source_tree_dirty": False, "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "repetitions": args.repetitions, "images": {}, "results": []}
    for name, image in IMAGES.items():
        image_info = json.loads(command(["docker", "image", "inspect", image]).stdout)[0]
        report["images"][name] = {"tag": image, "id": image_info["Id"], "digests": image_info["RepoDigests"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(path)
    try:
        save()
        for primary, projection in CASES:
            print("running %s -> %s" % (primary, projection), flush=True)
            result = scenario(primary, projection, args.repetitions)
            result.update(run_id=report["run_id"], git_commit=report["git_commit"])
            report["results"].append(result)
            save()
            print("passed %s -> %s" % (primary, projection), flush=True)
        if hashes() != report["source_sha256"]:
            raise RuntimeError("sources changed during measurement")
        report["status"] = "passed"
        report["summary"] = validate(report)
        report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
        print(json.dumps(report["summary"], indent=2), flush=True)
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        save()
        raise
    finally:
        compose("down")  # Dedicated project; keep named volumes for inspection.


if __name__ == "__main__":
    main()
