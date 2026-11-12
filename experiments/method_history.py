#!/usr/bin/env python3
"""Independent static/version/history controls over preserved real Java inputs."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.method_evidence.evidence import (digest, file_digest, load_index, method_key,
                                             query, read_otlp, save_index)


def symbol(name, descriptor, class_name="fixture.board.Service"):
    return {"module": "method-fixture", "class": class_name, "name": name, "descriptor": descriptor}


def has_edge(tool, caller, target):
    return any(method_key(edge["caller"]) == method_key(caller) and
               method_key(edge["target"]) == method_key(target) for edge in tool["calls"])


def verify_static(index, variant):
    tools = index["staticEvidence"]
    string = "(Ljava/lang/String;)Ljava/lang/String;"
    list_method = symbol("list", string)
    validation = symbol("validate" if variant == "A" else "validateV2", "(Ljava/lang/String;)V")
    declared = symbol("find", string, "fixture.board.Repository")
    assert has_edge(tools["javaparser"], list_method, validation)
    assert has_edge(tools["wala"], list_method, validation)
    assert has_edge(tools["javaparser"], list_method, declared)
    impls = [symbol("find", string, "fixture.board." + name) for name in ("JdbcRepository", "CachedRepository")]
    assert all(has_edge(tools["wala"], list_method, item) for item in impls)
    for tool in tools.values():
        keys = {method_key(item) for item in tool["methods"]}
        assert method_key(symbol("find", string, "fixture.board.JdbcRepository")) in keys
        assert method_key(symbol("find", "(Ljava/lang/String;I)Ljava/lang/String;", "fixture.board.JdbcRepository")) in keys
        assert any("reflection" in item["reason"] for item in tool["unresolved"])
        assert any("native" in item["reason"] for item in tool["unresolved"])
    return {"privateCall": True, "distinctOverloads": True, "jpInterfaceDeclaration": True,
            "walaImplementationCandidates": 2, "reflectionTarget": "UNRESOLVED", "nativeBody": "UNSUPPORTED"}


def controls(store, artifacts, runs, full_reference):
    a = load_index(store, "method-a1-jdk17")
    b = load_index(store, "method-b1-jdk17")
    a2 = load_index(store, "method-a2-jdk17")
    excluded = load_index(store, "method-a1-jdk17-exclude")
    directory = Path(runs) / "17-method-a1-selected-normal-function"
    case = json.loads((directory / "result.json").read_text())
    collection = read_otlp(directory / "telemetry.log")
    trace = collection["spans"][0]["traceId"]
    config = case["telemetryConfigSha256"]
    assert query(a, collection, trace, config)["status"] == "OBSERVED"
    assert query(a2, collection, trace, config)["status"] == "MISMATCH"
    assert query(b, collection, trace, config)["status"] == "MISMATCH"
    assert a["buildIdentity"]["revision"] == a2["buildIdentity"]["revision"] == b["buildIdentity"]["revision"]
    assert a["buildIdentity"]["artifactSha256"] != a2["buildIdentity"]["artifactSha256"]
    first = json.loads((Path(artifacts) / "method-a1/identity.json").read_text())
    second = json.loads((Path(artifacts) / "method-a2/identity.json").read_text())
    variant = json.loads((Path(artifacts) / "method-b1/identity.json").read_text())
    assert first["classFiles"] == second["classFiles"] and first["sourceFiles"] == second["sourceFiles"]
    assert first["sourceFiles"] != variant["sourceFiles"]
    assert a["configSha256"] != excluded["configSha256"] and a["indexSha256"] != excluded["indexSha256"]
    assert all(item["class"] != "fixture.board.CachedRepository" for item in excluded["methods"])
    before = file_digest(Path(store) / "method-a1-jdk17.json")
    overwrite_rejected = False
    try:
        save_index(b, store)
    except FileExistsError:
        overwrite_rejected = True
    assert overwrite_rejected and before == file_digest(Path(store) / "method-a1-jdk17.json")
    missing = query(load_index(store, "uncollected-middle-revision"), collection, trace, config)
    assert missing["reason"] == "HISTORY_NOT_COLLECTED"
    without_identity = copy.deepcopy(collection)
    for span in without_identity["spans"]:
        span["resource"].pop("artifactSha256", None)
    assert query(a, without_identity, trace, config)["status"] == "UNRESOLVED"
    lost = copy.deepcopy(collection)
    root = next(item for item in lost["spans"] if item["method"] == "list")
    lost["spans"] = [item for item in lost["spans"] if item["spanId"] != root["spanId"]]
    loss = query(a, lost, trace, config)
    assert loss["status"] == "PARTIAL" and "PARENT_EXTERNAL_OR_NOT_COLLECTED" in loss["collectionReasons"]
    capped = query(a, collection, trace, config, per_trace_limit=2)
    assert "PER_TRACE_RECORD_LIMIT" in capped["collectionReasons"]
    akeys, bkeys = {method_key(m) for m in a["methods"]}, {method_key(m) for m in b["methods"]}
    removed, added = akeys - bkeys, bkeys - akeys
    assert {key[2] for key in removed} == {"validate"} and {key[2] for key in added} == {"validateV2"}
    # Conservative refresh prototype: choose full analysis when no sound impact
    # closure is implemented. This is a fallback, not an incremental algorithm.
    refreshed = json.loads(Path(full_reference).read_text())
    full_equivalence = refreshed["tools"] == b["staticEvidence"]
    assert full_equivalence
    return {
        "static": {"A": verify_static(a, "A"), "B": verify_static(b, "B")},
        "C09": {"sameRevision": True, "sameSourceDifferentManifestBuildAndArtifact": True,
                "classBytesSameForA1A2": True, "wrongArtifactJoin": "MISMATCH",
                "scope": "A1/A2 differ in build manifest; dependency-change/annotation-processor fixture not run"},
        "C10": {"actualClassExclusion": True, "differentConfigAndIndexDigests": True,
                "runSelectionExplicit": True, "overwriteRejected": True,
                "oldIndexBytesUnchanged": True, "analyzerOrSchemaUpgrade": "not run"},
        "C11": {"sourceOverlayChanged": "fixture/board/Service.java", "removed": sorted(removed), "added": sorted(added),
                "oldExecutionStillQueriesOldIndex": True, "aliasInference": "none; deletion + addition only",
                "refresh": {"strategy": "full-fallback", "reason": "sound partial impact closure not implemented",
                            "selectedResultEqualsFull": full_equivalence,
                            "incrementalPerformanceComparison": "NOT_RUN; same full result is a fallback control, not independent partial analysis"}},
        "C12": {"uncollectedHistory": missing["reason"], "missingArtifactIdentity": "UNRESOLVED",
                "languageSupport": "Java17 plain JAR only; unsupported language must not be represented as an empty success graph"},
        "lossControls": {"removedCollectedParent": "PARTIAL", "perTraceCollectorCap": "PARTIAL",
                         "boundary": "post-capture controls; not real exporter/network-loss injection",
                         "missingRecordDoesNotProveNonExecution": True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("store", "artifacts", "runs", "full-reference", "output"):
        parser.add_argument("--" + arg, required=True, type=Path)
    args = parser.parse_args()
    result = controls(args.store, args.artifacts, args.runs, args.full_reference)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"static": "PASS", "buildHistoryControls": "PASS", "C03": "UNRESOLVED_CODE_SYMBOL",
                      "incremental": "full-fallback only"}))


if __name__ == "__main__":
    main()
