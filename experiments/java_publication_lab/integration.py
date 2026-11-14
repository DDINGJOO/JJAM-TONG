"""Run two synthetic Java builds through the real local index and PostgreSQL path.

Uses the existing Psycopg environment and an explicitly supplied local DSN.
Generated OTLP records are QA inputs, not captured application execution.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import time

from experiments.analysis_reuse.run import command, measure
from experiments.java_publication_lab.probe import ADAPTER, PRODUCER_COMMIT, runtime_dependencies
from tools.evidence_store.contracts import GraphRequest, SnapshotConflict, SnapshotRef, VersionMismatch, prepare
from tools.evidence_store.postgres import PostgresEvidenceStore
from tools.method_evidence.evidence import (RESOURCE_KEYS, create_index, digest, file_digest, load_index,
                                            method_key, save_index)

ROOT = Path(__file__).resolve().parents[2]


def producer_snapshot():
    runtime = runtime_dependencies()
    paths = [ADAPTER / "target/java-call-analysis-0.1.0.jar",
             ADAPTER / "target/dependency-sha256.json", ADAPTER / "dependency-provenance.json"]
    paths += sorted((ADAPTER / "src/main/java").rglob("*.java"))
    paths += [ADAPTER / "target/dependency" / name for name in runtime]
    return {path.relative_to(ROOT).as_posix(): file_digest(path) for path in paths}


def verify_baseline(path, record_path, index, analysis):
    record = json.loads(record_path.read_bytes())
    before = json.loads(path.read_bytes())
    if (record.get("schema") != "jjamtong.java-publication-comparison.v1"
            or record.get("producerBaseCommit") != PRODUCER_COMMIT
            or record["analysis"]["adapterVersion"] != "0.2.2-probe32"
            or before["provenance"]["adapterVersion"] != "0.2.2-probe32"
            or file_digest(path) != record["analysis"]["rawSha256"]
            or record["inputIdentity"]["buildIdentity"] != index["buildIdentity"]
            or record["inputIdentity"]["input"] != analysis["input"]
            or record["fixture"]["metadataSha256"] != analysis["input"]["metadataInputSha256"]):
        raise ValueError("baseline version, hash, producer commit or exact input differs from the comparison record")
    after = copy.deepcopy(analysis)
    after["provenance"]["adapterVersion"] = "0.2.2-probe32"
    if before != after:
        raise AssertionError("compact producer changed prior analysis semantics")
    return {"rawSha256": file_digest(path), "producerCommit": PRODUCER_COMMIT,
            "comparisonRecordSha256": file_digest(record_path), "adapterVersion": "0.2.2-probe32"}


def timed(action):
    start = time.monotonic()
    result = action()
    return result, time.monotonic() - start


def reject(action, error):
    try:
        action()
    except error:
        return "rejected"
    raise AssertionError("invalid input was accepted")


def synthetic_trace(index, trace_id, method):
    resource = dict(index["buildIdentity"], configSha256="c" * 64)
    attrs = [{"key": RESOURCE_KEYS[key], "value": {"stringValue": value}}
             for key, value in resource.items()]
    return {"resource": {"attributes": attrs}, "scopeSpans": [{"spans": [{
        "traceId": trace_id, "spanId": "2" * 16, "parentSpanId": "9" * 16,
        "startTimeUnixNano": "1794000000000000001", "endTimeUnixNano": "1794000000000001001",
        "attributes": [{"key": "code.namespace", "value": {"stringValue": "fixture.scale.Unit0000"}},
                       {"key": "code.function", "value": {"stringValue": method}}],
        "status": {"code": 0}, "links": []}]}]}


def run(old_fixture, new_fixture, java_home, output, tenant, dsn, baseline=None, baseline_record=None):
    if bool(baseline) != bool(baseline_record):
        raise ValueError("baseline and baseline-record are required together")
    producer = producer_snapshot()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    store = PostgresEvidenceStore(dsn)
    store.initialize()
    results, indices, analyses = {}, {}, {}
    for label, fixture in (("old", old_fixture), ("new", new_fixture)):
        metadata = json.loads((fixture / "metadata.json").read_bytes())
        raw = output / (label + "-methods.json")
        measurement = measure(command(fixture, java_home, metadata["module"], "fixture.scale", raw),
                              output / (label + "-java.log"), timeout=100)
        if not measurement["success"]:
            raise RuntimeError("Java analysis failed; inspect the private Java log")
        analysis = json.loads(raw.read_bytes())
        if analysis["provenance"]["adapterVersion"] != "0.2.3":
            raise AssertionError("expected compact producer 0.2.3")
        index, index_seconds = timed(lambda: create_index(analysis, metadata, fixture / "fixture.jar",
                                                          fixture / "sources", "scale-" + label))
        path, save_seconds = timed(lambda: save_index(index, output / "index"))
        loaded = load_index(output / "index", index["analysisRunId"])
        if loaded != index:
            raise AssertionError("persisted index changed")
        derived, prepare_seconds = timed(lambda: prepare(loaded))
        created, publish_seconds = timed(lambda: store.publish(tenant, loaded))
        ref = SnapshotRef(tenant, index["analysisRunId"], index["indexSha256"])
        stored, load_seconds = timed(lambda: store.load(ref))
        if stored != index or store.publish(tenant, loaded) is not False:
            raise AssertionError("DB identity or idempotent retry changed")
        graph_results = {}
        for analyzer in ("javaparser", "wala"):
            root = (metadata["module"], "fixture.scale.Main", "main", "([Ljava/lang/String;)V")
            graph = store.walk(GraphRequest(ref, analyzer, root, max_nodes=1))
            if graph.status != "PARTIAL" or "NODE_LIMIT" not in graph.reasons:
                raise AssertionError("graph display budget was ignored")
            expected = {json.dumps(call, sort_keys=True) for call in index["staticEvidence"][analyzer]["calls"]}
            if any(json.dumps(call, sort_keys=True) not in expected for call in graph.calls):
                raise AssertionError("graph invented a call")
            graph_results[analyzer] = {"status": graph.status, "reasons": graph.reasons,
                                       "methods": len(graph.methods), "calls": len(graph.calls)}
        results[label] = {"buildIdentity": index["buildIdentity"], "analysisRunId": index["analysisRunId"],
                          "indexSha256": index["indexSha256"], "configSha256": index["configSha256"],
                          "rawSha256": file_digest(raw), "rawBytes": raw.stat().st_size,
                          "indexFileSha256": file_digest(path), "indexBytes": path.stat().st_size,
                          "prepareBytes": len(json.dumps(index, ensure_ascii=False).encode()),
                          "methods": len(index["methods"]), "java": measurement,
                          "indexSeconds": index_seconds, "saveSeconds": save_seconds,
                          "prepareSeconds": prepare_seconds, "dbPublishSeconds": publish_seconds,
                          "dbLoadSeconds": load_seconds, "dbCreated": created,
                          "exactDbRoundtrip": True, "sameHashRetryCreated": False,
                          "coverage": {tool: data["coverage"] for tool, data in derived.items()},
                          "boundedGraph": graph_results}
        indices[label], analyses[label] = index, analysis

    old, new = indices["old"], indices["new"]
    old_ref = SnapshotRef(tenant, old["analysisRunId"], old["indexSha256"])
    old_names = {method_key(m) for m in old["methods"]}
    new_names = {method_key(m) for m in new["methods"]}
    removed, added = sorted(old_names - new_names), sorted(new_names - old_names)
    if not removed or not added or store.load(old_ref) != old:
        raise AssertionError("build change or previous history was lost")
    altered = copy.deepcopy(old)
    altered["limitations"].append("Synthetic same-run conflict counterexample")
    altered["indexSha256"] = digest({key: value for key, value in altered.items() if key != "indexSha256"})
    checks = {"differentContentSameRun": reject(lambda: store.publish(tenant, altered), SnapshotConflict),
              "wrongSnapshotHash": reject(lambda: store.load(SnapshotRef(tenant, old["analysisRunId"], "f" * 64)), VersionMismatch),
              "oldAnalysisWithNewInput": reject(lambda: create_index(analyses["old"],
                    json.loads((new_fixture / "metadata.json").read_bytes()), new_fixture / "fixture.jar",
                    new_fixture / "sources", "wrong-input"), ValueError),
              "oldHistoryAfterNewPublish": "exact"}
    baseline_evidence = None
    if baseline:
        baseline_evidence = verify_baseline(baseline, baseline_record, old, analyses["old"])
        checks["baselineExceptAdapterVersion"] = "exact full JSON including source positions"
    if producer_snapshot() != producer:
        raise ValueError("producer sources or JAR changed during verification")
    trace_log = output / "synthetic-otlp.log"
    trace_log.write_text("\n".join(json.dumps(synthetic_trace(indices[label], trace, name))
                         for label, trace, name in (("old", "1" * 32, "m19"),
                                                    ("new", "3" * 32, "m19Updated"))) + "\n")
    report = {"schema": "jjamtong.java-publication-integration.v1", "syntheticInputOnly": True,
              "syntheticTraceOnly": True, "tenant": tenant, "adapterVersion": "0.2.3",
              "results": results, "checks": checks, "methodChanges": {"removed": removed, "added": added},
              "producerSha256": producer, "baselineEvidence": baseline_evidence,
              "browserQa": "pending; real browser interaction is a separate gate"}
    (output / "integration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("old-fixture", "new-fixture", "java-home", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-record", type=Path)
    args = parser.parse_args()
    dsn = os.environ.get("JJAMTONG_EVIDENCE_DSN")
    if not dsn:
        parser.error("explicit local JJAMTONG_EVIDENCE_DSN is required")
    result = run(args.old_fixture, args.new_fixture, args.java_home, args.output, args.tenant, dsn,
                 args.baseline, args.baseline_record)
    print(json.dumps({"status": "passed", "checks": result["checks"], "browserQa": result["browserQa"]}))


if __name__ == "__main__":
    main()
