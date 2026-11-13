"""Reproduce the local comparison, including real containers and crash recovery."""
import argparse
import concurrent.futures
import datetime
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import threading
import time
import uuid

from .fixtures import ANALYSIS, dataset, expected_counts, expected_events, expected_reachable, fingerprint, key, record, scope
from .pipeline import Outbox
from .provenance import source_hashes, stamped
from .stores import STORES, Postgres

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(Path(__file__).with_name("compose.yaml"))]
IMAGES = {"postgres": "postgres:17.11-alpine", "neo4j": "neo4j:5.26.33-community",
          "elasticsearch": "docker.elastic.co/elasticsearch/elasticsearch:9.5.6",
          "clickhouse": "clickhouse/clickhouse-server:26.8.36.3"}


def command(args, check=True):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def compose(*args):
    return command(COMPOSE + list(args)).stdout.strip()


def ready(name):
    deadline = time.monotonic() + 120
    last_error = None
    while time.monotonic() < deadline:
        store = None
        try:
            store = STORES[name]()
            if name == "postgres":
                store.sql("SELECT 1")
            elif name == "neo4j":
                store.cypher("RETURN 1")
            elif name == "elasticsearch":
                store.http.request("GET", "/_cluster/health?wait_for_status=yellow&timeout=2s")
            else:
                store.http.request("POST", "/?database=default&query=CREATE%20DATABASE%20IF%20NOT%20EXISTS%20evidence_lab", parse_json=False)
                store.sql("SELECT 1 FORMAT JSONEachRow")
            return store
        except Exception as error:
            last_error = error
            if store:
                store.close()
            time.sleep(1)
    logs = command(COMPOSE + ["logs", "--tail=12", name], False).stdout
    raise RuntimeError("%s not ready: %s\n%s" % (name, last_error, logs))


class Sampler:
    """Docker cgroup working-set samples, not a host or process RSS peak."""
    def __init__(self, name):
        self.container = compose("ps", "-q", name)
        self.samples = []
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.done.is_set():
            result = command(["docker", "stats", "--no-stream", "--format", "{{json .}}", self.container], False)
            if result.returncode == 0 and result.stdout.strip():
                sample = json.loads(result.stdout)
                self.samples.append({k: sample[k] for k in ("CPUPerc", "MemUsage", "NetIO", "BlockIO")})
            self.done.wait(1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.done.set()
        self.thread.join(timeout=5)


def timed(call):
    started = time.perf_counter()
    value = call()
    return value, (time.perf_counter() - started) * 1000


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError("%s: actual=%s expected=%s" % (label, str(actual)[:1000], str(expected)[:1000]))


def correctness(store, rows):
    checks = []
    def check(label, actual, expected):
        assert_equal(actual, expected, label)
        checks.append(label)
    selected = scope()
    start = key("alpha", "build-A", "method-0")
    for depth in (1, 3, 6):
        check("static-forward-%d" % depth, store.reachable(selected, start, depth), expected_reachable(rows, selected, start, depth))
    dispatcher = key("alpha", "build-A", "dispatcher")
    check("higher-degree-dispatcher", store.reachable(selected, dispatcher, 3), expected_reachable(rows, selected, dispatcher, 3))
    target = key("alpha", "build-A", "method-17")
    check("reverse-impact-with-cycle", store.reachable(selected, target, 6, reverse=True), expected_reachable(rows, selected, target, 6, reverse=True))
    check("infra-vpc-rds-s3", store.reachable(selected, start, 6, "INFRA"), expected_reachable(rows, selected, start, 6, "INFRA"))
    other = scope(build="build-B")
    check("same-commit-different-artifact", store.reachable(other, key("alpha", "build-B", "method-0"), 1), expected_reachable(rows, other, key("alpha", "build-B", "method-0"), 1))
    analysis = "analyzer-1.config-partial.schema-1"
    check("different-analysis-configuration", store.reachable(scope(analysis=analysis), key("alpha", "build-A", "method-0", analysis), 3), [key("alpha", "build-A", "method-24", analysis)])
    check("unknown-build-is-empty", store.reachable(scope(build="unknown"), key("alpha", "unknown", "method-0"), 3), [])
    check("fulltext-timeout", store.events(selected, "timeout"), expected_events(rows, selected, "timeout"))
    check("late-record-known-time", store.events(selected, known_before=1500), expected_events(rows, selected, known_before=1500))
    check("error-group-by-service", store.counts(selected), expected_counts(rows, selected))
    beta = scope(tenant="beta")
    check("tenant-filter-alpha-vs-beta", store.events(beta, "timeout"), expected_events(rows, beta, "timeout"))
    spans = store.select(selected, "span")
    check("actual-trace-stays-observed", sorted((r["logical"], r["relation"], r["trace_id"]) for r in spans), [("span-%d" % i, "OBSERVED", "trace-demo") for i in range(3)])
    for bad_scope in (("", "build-A", ANALYSIS), ("alpha", "", ANALYSIS), ("alpha", "build-A", "")):
        try:
            store.events(bad_scope)
        except ValueError:
            continue
        raise AssertionError("missing scope accepted")
    checks.append("missing-query-scope-rejected")
    return checks


def benchmark(store, rows, repetitions):
    selected = scope()
    start = key("alpha", "build-A", "method-0")
    target = key("alpha", "build-A", "method-17")
    queries = {
        "graph_forward_6": (lambda: store.reachable(selected, start, 6), expected_reachable(rows, selected, start, 6)),
        "graph_reverse_6": (lambda: store.reachable(selected, target, 6, reverse=True), expected_reachable(rows, selected, target, 6, reverse=True)),
        "graph_hub_3": (lambda: store.reachable(selected, key("alpha", "build-A", "dispatcher"), 3), expected_reachable(rows, selected, key("alpha", "build-A", "dispatcher"), 3)),
        "fulltext_timeout": (lambda: store.events(selected, "timeout"), expected_events(rows, selected, "timeout")),
        "error_aggregation": (lambda: store.counts(selected), expected_counts(rows, selected)),
    }
    results = {}
    for label, (query, expected) in queries.items():
        before = store.calls
        value, first_ms = timed(query)
        assert_equal(value, expected, label)
        for _ in range(3):
            assert_equal(query(), expected, label)
        samples = []
        for _ in range(repetitions):
            actual, elapsed = timed(query)
            assert_equal(actual, expected, label)
            samples.append(elapsed)
        ordered = sorted(samples)
        results[label] = dict(first_measured_ms=first_ms, samples_ms=samples,
                              p50_ms=statistics.median(samples), p95_ms=ordered[math.ceil(.95 * len(ordered)) - 1],
                              result_count=len(expected), database_calls=store.calls - before,
                              measured_and_warmup_invocations=repetitions + 4)
    return results


def concurrent_reads(name, rows):
    """Fixed 1/4/8-client probes. Not a sustainable-capacity measurement."""
    selected = scope()
    start = key("alpha", "build-A", "dispatcher")
    graph = expected_reachable(rows, selected, start, 3)
    events = expected_events(rows, selected, "timeout")
    counts = expected_counts(rows, selected)
    results = []
    for clients in (1, 4, 8):
        started = []
        # The action runs before any participant can leave the barrier.
        barrier = threading.Barrier(clients + 1, action=lambda: started.append(time.perf_counter()))
        def worker():
            adapter = STORES[name]()
            samples = []
            try:
                # Open the native transport before timing the concurrent interval.
                assert_equal(adapter.counts(selected), counts, "client readiness")
                barrier.wait(timeout=60)
                for i in range(12):
                    query, expected = ((lambda: adapter.reachable(selected, start, 3), graph),
                                       (lambda: adapter.events(selected, "timeout"), events),
                                       (lambda: adapter.counts(selected), counts))[i % 3]
                    actual, elapsed = timed(query)
                    assert_equal(actual, expected, "concurrent query correctness")
                    samples.append(elapsed)
                return samples
            finally:
                adapter.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
            futures = [pool.submit(worker) for _ in range(clients)]
            barrier.wait(timeout=60)
            samples = [sample for future in futures for sample in future.result()]
            elapsed = time.perf_counter() - started[0]
        ordered = sorted(samples)
        results.append(dict(clients=clients, operations=len(samples), elapsed_seconds=elapsed,
                            operations_per_second=len(samples) / elapsed, p50_ms=statistics.median(samples),
                            p95_ms=ordered[math.ceil(.95 * len(ordered)) - 1], samples_ms=samples, correctness="passed"))
    return results


def mutation_checks(store, rows):
    selected = scope()
    chosen = next(r for r in rows if r["kind"] == "event" and (r["tenant"], r["build"], r["analysis"]) == selected)
    original_ids = expected_events(rows, selected)
    store.put([chosen, chosen])
    store.flush()
    assert_equal(store.events(selected), original_ids, "idempotent replay")
    tombstone = dict(chosen, seq=2, deleted=1)
    store.put([tombstone])
    store.put([chosen])  # an old event arrives after the tombstone
    store.flush()
    remaining = [i for i in original_ids if i != chosen["id"]]
    assert_equal(store.events(selected), remaining, "out-of-order replay must not resurrect")
    restored = dict(chosen, seq=3)
    store.put([restored])
    store.flush()
    assert_equal(store.events(selected), original_ids, "newer revision restores explicitly")
    return ["idempotent-duplicate-delivery", "tombstone-and-older-replay", "explicit-newer-revision"], restored


def pipeline_checks(name, sink):
    primary = ready("postgres")
    stream = "test-" + name + "-" + uuid.uuid4().hex[:8]
    outbox = Outbox(primary, sink, stream, stream)
    row = record("pipeline", stream, "event", "pipeline-event", message="synthetic timeout", level="ERROR", service="board")
    selected = scope("pipeline", stream)
    checks, timings = [], {}
    restored_sink = rebuild_sink = None
    succeeded = False
    try:
        # Rollback proves the source and outbox obligation share a transaction.
        try:
            with primary.connection.transaction():
                outbox.publish(stream + "-rollback", row)
                raise RuntimeError("rollback-injection")
        except RuntimeError as error:
            if str(error) != "rollback-injection":
                raise
        assert_equal(primary.events(selected), [], "canonical rollback")
        assert_equal(outbox.watermark()["status"], "ready", "outbox rollback")
        checks.append("source-and-outbox-atomic-rollback")
        outbox.publish(stream + "-1", row)
        assert_equal(primary.events(selected), [row["id"]], "canonical commit")
        assert_equal(outbox.watermark()["status"], "stale", "projection pending")
        assert_equal(sink.events(selected), [], "paused projection has no result")
        checks.append("committed-source-with-pending-projection")
        proc = command([sys.executable, "-m", "experiments.storage_lab.pipeline", "--sink", name, "--stream", stream, "--consumer", stream, "--crash-after-apply"], False)
        assert_equal(proc.returncode, 73, "worker process really exits after apply before ACK: " + proc.stderr)
        assert_equal(sink.events(selected), [row["id"]], "applied before process loss")
        assert_equal(outbox.watermark()["status"], "stale", "crash left ACK pending")
        _, timings["replay_after_process_loss_ms"] = timed(outbox.drain)
        assert_equal(sink.events(selected), [row["id"]], "replay remains one visible record")
        assert_equal(outbox.watermark()["status"], "ready", "recovered watermark")
        checks.append("real-worker-exit-73-before-ack-and-idempotent-replay")
        outbox.publish(stream + "-2", dict(row, seq=2, deleted=1))
        outbox.drain()
        outbox.publish(stream + "-3", row)
        outbox.drain()
        assert_equal(sink.events(selected), [], "old replay cannot undo delete")
        checks.append("cross-store-delete-and-out-of-order-replay")
        try:
            outbox.publish(stream + "-1", dict(row, message="different payload"))
        except ValueError:
            checks.append("event-id-conflict-rejected")
        else:
            raise AssertionError("conflicting event identity accepted")
        # Real database outage: a new source commit stays durable and unacknowledged.
        sink.close()
        compose("stop", name)
        outbox.publish(stream + "-4", dict(row, seq=3))
        unavailable = STORES[name]()
        outbox.sink = unavailable
        try:
            outbox.drain()
        except Exception as error:
            timings["outage_exception_type"] = type(error).__name__
        else:
            raise AssertionError("stopped projection unexpectedly accepted a write")
        finally:
            unavailable.close()
        assert_equal(outbox.watermark()["status"], "stale", "outage remains unacknowledged")
        compose("start", name)
        restored_sink = ready(name)
        outbox.sink = restored_sink
        _, timings["drain_after_database_restart_ms"] = timed(outbox.drain)
        assert_equal(restored_sink.events(selected), [row["id"]], "recovered after DB outage")
        checks.append("real-database-stop-start-and-backlog-recovery")
        # Delete only this synthetic scope, then replay its retained original stream.
        outbox.invalidate()
        restored_sink.purge_scope(selected)
        assert_equal(restored_sink.events(selected), [], "projection really removed")
        assert_equal(outbox.watermark()["status"], "stale", "retired projection cannot remain ready")
        rebuild_sink = restored_sink
        if name == "elasticsearch":
            # delete_by_query advances internal versions. Rebuild in a fresh generation.
            rebuild_sink = STORES[name]()
            rebuild_sink.index += "-rebuild-" + uuid.uuid4().hex[:8]
            rebuild_sink.reset()
        rebuild = Outbox(primary, rebuild_sink, stream, stream + "-rebuild")
        replayed, timings["rebuild_from_retained_outbox_ms"] = timed(rebuild.drain)
        assert_equal(replayed, 4, "rebuild replays all four committed events")
        assert_equal(rebuild_sink.events(selected), [row["id"]], "rebuilt latest state")
        assert_equal(rebuild.watermark()["status"], "ready", "rebuilt projection has its own checkpoint")
        if rebuild_sink is not restored_sink:
            restored_sink.close()
            timings["rebuild_mode"] = "fresh-index-generation; atomic alias switch not implemented"
        else:
            timings["rebuild_mode"] = "purge isolated synthetic scope and replay original retained stream"
        checks.append("purged-projection-rebuilt-from-retained-outbox")
        succeeded = True
        return {"checks": checks, "timings": timings, "watermark": rebuild.watermark(),
                "retired_watermark": outbox.watermark(), "consumer": rebuild.consumer,
                "projection": getattr(rebuild_sink, "index", name)}, rebuild_sink
    finally:
        primary.close()
        if not succeeded:
            for adapter in (restored_sink, rebuild_sink):
                if adapter is not None:
                    adapter.close()


def run_engine(name, scales, repetitions, do_pipeline):
    print("START " + name, flush=True)
    store = None
    results = {"engine": name, "image": IMAGES[name], "scales": []}
    try:
        compose("up", "-d", name)
        store = ready(name)
        for label, methods, events in scales:
            rows = dataset(methods, events)
            store.reset()
            with Sampler(name) as resources:
                _, ingest_ms = timed(lambda: store.put(rows))
                _, visibility_ms = timed(store.flush)
                checks = correctness(store, rows)
                measurements = benchmark(store, rows, repetitions)
                concurrent = concurrent_reads(name, rows) if label == "medium" else []
                mutations, restored = mutation_checks(store, rows)
                checks += mutations
            result = dict(label=label, methods_per_tenant_build=methods, events_total=events,
                          total_records=len(rows), input_sha256=fingerprint(rows),
                          ingest_ms=ingest_ms, explicit_visibility_barrier_ms=visibility_ms,
                          records_per_second=len(rows) * 1000 / ingest_ms,
                          correctness_checks=checks, queries=measurements,
                          concurrent_reads=concurrent,
                          engine_reported_storage_bytes=store.storage_bytes(), resource_samples=resources.samples)
            results["scales"].append(result)
            print("PASS %s %s records=%d checks=%d ingest=%.0fms" % (name, label, len(rows), len(checks), ingest_ms), flush=True)
        # Preserve all but the intentionally revised event across actual restart.
        store.close()
        compose("stop", name)
        compose("start", name)
        store = ready(name)
        correctness(store, rows)
        results["restart_persistence"] = "passed"
        if name != "postgres" and do_pipeline:
            compose("up", "-d", "postgres")
            results["pipeline"], store = pipeline_checks(name, store)
            print("PASS %s pipeline checks=%d" % (name, len(results["pipeline"]["checks"])), flush=True)
        container = compose("ps", "-q", name)
        results["container_inspect"] = json.loads(command(["docker", "inspect", container, "--format", "{{json .State}}" ]).stdout)
        results["image_identity"] = json.loads(command(["docker", "image", "inspect", IMAGES[name], "--format", "{{json .RepoDigests}}" ]).stdout)
        results["store_files_du_kib"] = command(["docker", "exec", container, "du", "-sk", {"postgres": "/var/lib/postgresql/data", "neo4j": "/data", "elasticsearch": "/usr/share/elasticsearch/data", "clickhouse": "/var/lib/clickhouse"}[name]], False).stdout.strip()
        print("DONE " + name, flush=True)
        results["status"] = "passed"
        return results
    finally:
        try:
            if store is not None:
                try:
                    if name == "elasticsearch" and store.index != STORES[name].index:
                        store.http.request("DELETE", "/" + store.index, allowed=(200, 404))
                finally:
                    store.close()
        finally:
            try:
                compose("stop", name)
            finally:
                if name != "postgres":
                    compose("stop", "postgres")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", nargs="+", choices=sorted(STORES), default=list(STORES))
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--no-pipeline", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "results/storage-lab")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    if command(["git", "status", "--porcelain", "--", "experiments/storage_lab"]).stdout.strip():
        parser.error("commit storage-lab source changes before measuring a reproducible comparison")
    args.output.mkdir(parents=True, exist_ok=True)
    scales = [("small", 150, 1000)] if args.quick else [("small", 150, 1000), ("medium", 1500, 20000)]
    environment = dict(run_id=uuid.uuid4().hex, source_sha256=source_hashes(), source_tree_dirty=False,
                       engines=args.engines, pipeline_enabled=not args.no_pipeline,
                       timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       platform=platform.platform(), python=sys.version, machine=platform.machine(),
                       git_commit=command(["git", "rev-parse", "HEAD"]).stdout.strip(),
                       docker=json.loads(command(["docker", "info", "--format", "{{json .}}" ]).stdout),
                       existing_containers=command(["docker", "ps", "--format", "{{.Names}} {{.Image}}" ]).stdout.splitlines(),
                       repetitions=args.repetitions, scales=scales,
                       caveats=["single-node local shared host", "different native models and drivers", "same 1 CPU limit; memory limits differ",
                                "first measurement is not a cold disk test", "sequential single-client queries", "no HA, capacity or production authorization proof"])
    # Do not serialize the complete Docker info: it can contain registry/account settings.
    environment["docker"] = {k: environment["docker"].get(k) for k in ("ServerVersion", "Architecture", "MemTotal", "NCPU", "OperatingSystem")}
    (args.output / "environment.json").write_text(json.dumps(environment, indent=2))
    failed = False
    for name in args.engines:
        try:
            result = stamped(run_engine(name, scales, args.repetitions, not args.no_pipeline), environment)
        except Exception as error:
            failed = True
            result = {"engine": name, "status": "failed", "error": repr(error)}
            print("FAIL %s: %r" % (name, error), flush=True)
        (args.output / (name + ".json")).write_text(json.dumps(result, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
