"""Package measured raw results without publishing environment credentials."""
import argparse
import json
from pathlib import Path

from .run import ROOT
from .fixtures import dataset, fingerprint
from .provenance import load_environment


NAMES = ("postgres", "neo4j", "elasticsearch", "clickhouse")
QUERIES = {"graph_forward_6", "graph_reverse_6", "graph_hub_3", "fulltext_timeout", "error_aggregation"}
SCALES = [("small", 150, 1000), ("medium", 1500, 20000)]
CORRECTNESS = {"static-forward-1", "static-forward-3", "static-forward-6", "higher-degree-dispatcher",
               "reverse-impact-with-cycle", "infra-vpc-rds-s3", "same-commit-different-artifact",
               "different-analysis-configuration", "unknown-build-is-empty", "fulltext-timeout",
               "late-record-known-time", "error-group-by-service", "tenant-filter-alpha-vs-beta",
               "actual-trace-stays-observed", "missing-query-scope-rejected", "idempotent-duplicate-delivery",
               "tombstone-and-older-replay", "explicit-newer-revision"}
PIPELINE = {"source-and-outbox-atomic-rollback", "committed-source-with-pending-projection",
            "real-worker-exit-73-before-ack-and-idempotent-replay", "cross-store-delete-and-out-of-order-replay",
            "event-id-conflict-rejected", "real-database-stop-start-and-backlog-recovery",
            "purged-projection-rebuilt-from-retained-outbox"}
FEDERATION = {"one-projection-behind-is-partial", "fixture-build-assumed-artifact-join",
              "requested-artifact-mismatch-with-source-rejected", "unknown-build-has-no-latest-fallback",
              "new-write-invalidates-previous-ready-watermark", "catch-up-restores-joined-view"}


def validate(environment, engines, federation):
    if set(environment.get("engines", [])) != set(NAMES) or not environment.get("pipeline_enabled"):
        raise ValueError("full comparison requires all four engines and pipeline checks")
    if environment.get("scales") != [list(scale) for scale in SCALES]:
        raise ValueError("full comparison requires small and medium inputs")
    repetitions = environment["repetitions"]
    if not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError("latency repetitions must be positive")
    for name, result in list(engines.items()) + [("federation", federation)]:
        if (result.get("run_id") != environment["run_id"] or result.get("git_commit") != environment["git_commit"] or
                result.get("source_sha256") != environment["source_sha256"]):
            raise ValueError("mixed run or source identity: " + name)
        if result.get("status") != "passed":
            raise ValueError("incomplete result: " + name)
    for name, result in engines.items():
        if result.get("engine") != name or result.get("restart_persistence") != "passed" or len(result.get("scales", [])) != 2:
            raise ValueError("incomplete engine result: " + name)
        for measured, (label, methods, events) in zip(result["scales"], SCALES):
            expected = dataset(methods, events)
            if (measured.get("label") != label or measured.get("input_sha256") != fingerprint(expected) or
                    measured.get("total_records") != len(expected)):
                raise ValueError("different input: " + name + "/" + label)
            if (len(measured.get("correctness_checks", [])) != len(CORRECTNESS) or
                    set(measured["correctness_checks"]) != CORRECTNESS or set(measured.get("queries", {})) != QUERIES):
                raise ValueError("incomplete correctness or queries: " + name)
            if any(len(query["samples_ms"]) != repetitions for query in measured["queries"].values()):
                raise ValueError("incomplete latency samples: " + name)
            probes = measured["concurrent_reads"]
            if label == "medium" and ([probe["clients"] for probe in probes] != [1, 4, 8] or any(
                    probe.get("correctness") != "passed" or probe["operations"] != 12 * probe["clients"] or
                    len(probe["samples_ms"]) != probe["operations"] for probe in probes)):
                raise ValueError("incomplete concurrent reads: " + name)
        if name != "postgres":
            pipeline = result.get("pipeline", {})
            if (len(pipeline.get("checks", [])) != len(PIPELINE) or set(pipeline["checks"]) != PIPELINE or
                    pipeline.get("watermark", {}).get("status") != "ready" or
                    pipeline.get("retired_watermark", {}).get("status") != "stale"):
                raise ValueError("incomplete pipeline: " + name)
    if (len(federation.get("checks", [])) != len(FEDERATION) or set(federation["checks"]) != FEDERATION or
            federation.get("partial_example", {}).get("status") != "partial" or
            federation.get("ready_example", {}).get("status") != "ready"):
        raise ValueError("incomplete federation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "results/storage-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/experiments/storage-engine-run.json")
    args = parser.parse_args()
    environment = load_environment(args.input)
    engines = {name: json.loads((args.input / (name + ".json")).read_text()) for name in NAMES}
    federation = json.loads((args.input / "federation.json").read_text())
    validate(environment, engines, federation)
    output = dict(environment=environment, engines=engines, federation=federation,
                  measured_source_sha256=environment["source_sha256"],
                  counts={"fixture_assertions": sum(len(s["correctness_checks"]) for e in engines.values() for s in e["scales"]),
                          "latency_samples": sum(len(q["samples_ms"]) for e in engines.values() for s in e["scales"] for q in s["queries"].values()),
                          "concurrent_read_operations": sum(c["operations"] for e in engines.values() for s in e["scales"] for c in s["concurrent_reads"]),
                          "pipeline_checks": sum(len(e.get("pipeline", {}).get("checks", [])) for e in engines.values()),
                          "federation_checks": len(federation["checks"])})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["counts"]))
    print(str(args.output))


if __name__ == "__main__":
    main()
