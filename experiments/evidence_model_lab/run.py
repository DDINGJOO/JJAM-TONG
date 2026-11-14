"""Compare explicit synthetic expectations with typed evidence query results."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from tools.evidence_store.test_contracts import rehash, sample
from .model import (Claim, ClaimLog, EntityKind as K, EntityRef, EvidenceMode as M,
                    EvidenceRef, QueryRequest, RelationKind as R, import_v1,
                    require_exact_bridge)

T0 = datetime(2026, 11, 14, tzinfo=timezone.utc)


def ref(kind, native_id, provider="synthetic-installation", incarnation=""):
    return EntityRef(kind, "synthetic-tenant", provider, native_id, incarnation)


def claim(cid, subject, relation, target, mode=M.DECLARED, known=0, source="source-a", **changes):
    values = dict(claim_id=cid, tenant=subject.tenant, subject=subject, relation=relation,
                  object=target, mode=mode,
                  evidence=EvidenceRef(subject.tenant, "synthetic-collector", source, "record:" + cid),
                  valid_from=T0, known_at=T0 + timedelta(minutes=known))
    values.update(changes)
    return Claim(**values)


def lookup(log, subject, relation, allowed, known=10, **changes):
    values = dict(tenant=subject.tenant, subject=subject, relation=relation,
                  valid_at=T0, known_at=T0 + timedelta(minutes=known),
                  allowed_refs=frozenset(allowed), visibility_complete=True)
    values.update(changes)
    return log.query(QueryRequest(**values))


def view(result):
    return {"status": result.status, "claimIds": list(result.claim_ids),
            "targetIds": [item.native_id for item in result.object_refs],
            "reasons": sorted(result.reasons)}


def expected(status="MATCH", ids=(), targets=(), reasons=()):
    return {"status": status, "claimIds": list(ids), "targetIds": list(targets),
            "reasons": sorted(reasons)}


def rejected(operation):
    try:
        operation()
    except ValueError:
        return "REJECTED"
    return "ACCEPTED"


def scenarios():
    cases = []

    def record(number, name, wanted, actual):
        cases.append({"scenarioId": f"BDD-MDL-{number:03d}", "name": name,
                      "expected": wanted, "actual": actual,
                      "status": "PASS" if wanted == actual else "FAIL"})

    first = sample()
    rebuilt = sample(run="run-rebuilt")
    rebuilt["buildIdentity"]["artifactSha256"] = "b" * 64
    rehash(rebuilt)
    bridge = import_v1(first, "synthetic-tenant")
    other = import_v1(rebuilt, "synthetic-tenant")
    record(1, "same revision and label with different artifacts",
           {"buildIdentity": first["buildIdentity"], "artifactDigests": ["a" * 64, "b" * 64],
            "analysisRuns": ["run-a", "run-rebuilt"], "distinctBuildRefs": True},
           {"buildIdentity": dict(bridge.build_identity),
            "artifactDigests": [bridge.artifact.native_id.removeprefix("sha256:"), other.artifact.native_id.removeprefix("sha256:")],
            "analysisRuns": [bridge.analysis_run_id, other.analysis_run_id],
            "distinctBuildRefs": bridge.module_build != other.module_build})

    service, worker = ref(K.SERVICE, "board"), ref(K.SERVICE, "worker")
    module, common = ref(K.MODULE, "board-module"), ref(K.MODULE, "common-module")
    log = ClaimLog()
    for item in (claim("board-common", service, R.SERVICE_USES_MODULE, common),
                 claim("board-module", service, R.SERVICE_USES_MODULE, module),
                 claim("worker-common", worker, R.SERVICE_USES_MODULE, common)):
        log.append(item)
    allowed = (service, worker, module, common)
    record(2, "many modules and services",
           {"board": expected(ids=("board-common", "board-module"), targets=("common-module", "board-module")),
            "worker": expected(ids=("worker-common",), targets=("common-module",))},
           {"board": view(lookup(log, service, R.SERVICE_USES_MODULE, allowed)),
            "worker": view(lookup(log, worker, R.SERVICE_USES_MODULE, allowed))})

    old_dep, new_dep = ref(K.DEPLOYMENT, "release-old"), ref(K.DEPLOYMENT, "release-new")
    old_runtime, new_runtime = ref(K.RUNTIME, "container-old"), ref(K.RUNTIME, "container-new")
    log = ClaimLog()
    for item in (claim("deploy-new", service, R.DEPLOYS, new_dep), claim("deploy-old", service, R.DEPLOYS, old_dep),
                 claim("runtime-old", old_runtime, R.RUNTIME_PRIMARY_BUILD, bridge.module_build, M.OBSERVED),
                 claim("runtime-new", new_runtime, R.RUNTIME_PRIMARY_BUILD, other.module_build, M.OBSERVED)):
        log.append(item)
    record(3, "coexisting releases keep exact distinct builds",
           {"deployments": expected(ids=("deploy-new", "deploy-old"), targets=("release-new", "release-old")),
            "oldBuild": dict(first["buildIdentity"]), "newBuild": dict(rebuilt["buildIdentity"]), "separateRuntimeBindings": True},
           {"deployments": view(lookup(log, service, R.DEPLOYS, (service, old_dep, new_dep))),
            "oldBuild": dict(bridge.build_identity), "newBuild": dict(other.build_identity),
            "separateRuntimeBindings": lookup(log, old_runtime, R.RUNTIME_PRIMARY_BUILD, (old_runtime, bridge.module_build)).object_refs !=
                                      lookup(log, new_runtime, R.RUNTIME_PRIMARY_BUILD, (new_runtime, other.module_build)).object_refs})

    one = ref(K.RESOURCE, "shared-db", "aws:account-a:region-a")
    same_name = ref(K.RESOURCE, "shared-db", "aws:account-b:region-a")
    pod_old = ref(K.POD, "board", "k8s:cluster-a", "uid-old")
    pod_new = ref(K.POD, "board", "k8s:cluster-a", "uid-new")
    log = ClaimLog(); log.append(claim("equivalent", one, R.EQUIVALENT_TO, same_name))
    record(4, "native scope and incarnation survive equivalence claims",
           {"sameAccountIdentity": False, "sameWorkloadIdentity": False,
            "equivalence": expected(ids=("equivalent",), targets=("shared-db",)), "originalProviders": ["aws:account-a:region-a", "aws:account-b:region-a"]},
           {"sameAccountIdentity": one == same_name, "sameWorkloadIdentity": pod_old == pod_new,
            "equivalence": view(lookup(log, one, R.EQUIVALENT_TO, (one, same_name))),
            "originalProviders": [one.provider, same_name.provider]})

    second = ref(K.RESOURCE, "redis")
    log = ClaimLog()
    for item in (claim("board-db", service, R.CATALOG_MAPS, one), claim("board-redis", service, R.CATALOG_MAPS, second),
                 claim("worker-db", worker, R.CATALOG_MAPS, one)):
        log.append(item)
    record(5, "many-valued catalog and a genuinely shared resource",
           {"board": expected(ids=("board-db", "board-redis"), targets=("shared-db", "redis")),
            "worker": expected(ids=("worker-db",), targets=("shared-db",)),
            "observedOnly": expected("NO_MATCH_IN_KNOWN_EVIDENCE", reasons=("NO_MATCH_IN_KNOWN_EVIDENCE",))},
           {"board": view(lookup(log, service, R.CATALOG_MAPS, (service, one, second))),
            "worker": view(lookup(log, worker, R.CATALOG_MAPS, (worker, one))),
            "observedOnly": view(lookup(log, service, R.CATALOG_MAPS, (service, one, second), modes=frozenset({M.OBSERVED})))})

    log = ClaimLog(); log.append(claim("late", service, R.USES_RESOURCE, one, known=5))
    none = expected("NO_MATCH_IN_KNOWN_EVIDENCE", reasons=("NO_MATCH_IN_KNOWN_EVIDENCE",))
    record(6, "valid time differs from knowledge cutoff",
           {"before": none, "after": expected(ids=("late",), targets=("shared-db",)), "naiveTime": "REJECTED"},
           {"before": view(lookup(log, service, R.USES_RESOURCE, (service, one), known=3)),
            "after": view(lookup(log, service, R.USES_RESOURCE, (service, one), known=6)),
            "naiveTime": rejected(lambda: claim("naive", service, R.USES_RESOURCE, one, valid_from=datetime(2026, 11, 14)))})

    log = ClaimLog(); original = claim("original", service, R.USES_RESOURCE, one, known=1); log.append(original)
    corrected = claim("corrected", service, R.USES_RESOURCE, second, known=2,
                      valid_from=T0 + timedelta(minutes=1), supersedes="original")
    log.append(corrected)
    log.append(claim("withdrawn", service, R.USES_RESOURCE, second, known=3, retracts="corrected"))
    scope = (service, one, second)
    record(7, "new record references, corrected validity and retraction preserve history",
           {"earlierKnowledge": expected(ids=("original",), targets=("shared-db",)), "correctedOutsideInterval": none,
            "correctedInsideInterval": expected(ids=("corrected",), targets=("redis",)), "afterRetraction": none},
           {"earlierKnowledge": view(lookup(log, service, R.USES_RESOURCE, scope, known=1)),
            "correctedOutsideInterval": view(lookup(log, service, R.USES_RESOURCE, scope, known=2)),
            "correctedInsideInterval": view(lookup(log, service, R.USES_RESOURCE, scope, known=2, valid_at=T0 + timedelta(minutes=1))),
            "afterRetraction": view(lookup(log, service, R.USES_RESOURCE, scope, known=3, valid_at=T0 + timedelta(minutes=1)))})

    conflicts = ClaimLog()
    conflicts.append(claim("primary-a", old_runtime, R.RUNTIME_PRIMARY_BUILD, bridge.module_build, M.OBSERVED))
    conflicts.append(claim("primary-b", old_runtime, R.RUNTIME_PRIMARY_BUILD, other.module_build, M.OBSERVED, source="source-b"))
    result = lookup(conflicts, old_runtime, R.RUNTIME_PRIMARY_BUILD, (old_runtime, bridge.module_build, other.module_build))
    record(8, "conflicting primary builds retain both sources",
           {"status": "CONFLICT", "claimIds": ["primary-a", "primary-b"], "sourceRecords": ["record:primary-a", "record:primary-b"]},
           {"status": result.status, "claimIds": list(result.claim_ids), "sourceRecords": [c.evidence.original_ref for c in result.claims]})

    collision = ClaimLog(); collision.append(claim("same-id", service, R.USES_RESOURCE, one))
    mutable = sample(); immutable = import_v1(mutable, "synthetic-tenant"); mutable["buildIdentity"]["build"] = "mutated"
    record(9, "invalid types and immutable identity collisions are rejected",
           {"unknownKind": "REJECTED", "wrongEndpoints": "REJECTED", "collision": "REJECTED", "preservedBuild": "build-a"},
           {"unknownKind": rejected(lambda: EntityRef("SERVICE", "synthetic-tenant", "p", "s")),
            "wrongEndpoints": rejected(lambda: claim("bad", service, R.STATIC_CALL, one, M.STATIC_CANDIDATE)),
            "collision": rejected(lambda: collision.append(claim("same-id", service, R.USES_RESOURCE, second))),
            "preservedBuild": dict(immutable.build_identity)["build"]})

    method_a, method_b = ref(K.METHOD_VERSION, "artifact-a:method-a"), ref(K.METHOD_VERSION, "artifact-a:method-b")
    log = ClaimLog(); log.append(claim("static", method_a, R.STATIC_CALL, method_b, M.STATIC_CANDIDATE))
    log.append(claim("declared", service, R.USES_RESOURCE, one))
    log.append(claim("inferred", service, R.USES_RESOURCE, second, M.INFERRED))
    record(10, "candidate declaration and inference never become observed execution",
           {"staticObserved": none, "mappingObserved": none, "promotion": "REJECTED"},
           {"staticObserved": view(lookup(log, method_a, R.STATIC_CALL, (method_a, method_b), modes=frozenset({M.OBSERVED}))),
            "mappingObserved": view(lookup(log, service, R.USES_RESOURCE, (service, one, second), modes=frozenset({M.OBSERVED}))),
            "promotion": rejected(lambda: claim("promoted", method_a, R.STATIC_CALL, method_b, M.OBSERVED))})

    visible_only = ClaimLog(); visible_only.append(claim("visible", service, R.USES_RESOURCE, one))
    with_hidden = ClaimLog(); with_hidden.append(claim("visible", service, R.USES_RESOURCE, one))
    with_hidden.append(claim("hidden-secret", service, R.USES_RESOURCE, second))
    incomplete = expected("INCOMPLETE", reasons=("INCOMPLETE_VISIBILITY",))
    wanted_visible = expected(ids=("visible",), targets=("shared-db",))
    record(11, "hidden records do not change visible answers",
           {"withoutHidden": wanted_visible, "withHidden": wanted_visible, "incompleteScope": incomplete},
           {"withoutHidden": view(lookup(visible_only, service, R.USES_RESOURCE, (service, one))),
            "withHidden": view(lookup(with_hidden, service, R.USES_RESOURCE, (service, one))),
            "incompleteScope": view(lookup(with_hidden, service, R.USES_RESOURCE, (service, one), visibility_complete=False))})

    result = lookup(with_hidden, service, R.USES_RESOURCE, (service, one, second), limit=1)
    conflict_limit = lookup(conflicts, old_runtime, R.RUNTIME_PRIMARY_BUILD, (old_runtime, bridge.module_build, other.module_build), limit=1)
    record(12, "limits apply to ordinary and conflicting results",
           {"ordinary": expected("PARTIAL", ("hidden-secret",), ("redis",), ("QUERY_LIMIT",)),
            "conflictStatus": "PARTIAL", "conflictIds": ["primary-a"],
            "conflictReasons": sorted(["QUERY_LIMIT", "CONFLICTING_SINGLE_VALUE"]), "boolLimit": "REJECTED"},
           {"ordinary": view(result), "conflictStatus": conflict_limit.status,
            "conflictIds": list(conflict_limit.claim_ids), "conflictReasons": sorted(conflict_limit.reasons),
            "boolLimit": rejected(lambda: QueryRequest(service.tenant, service, R.USES_RESOURCE, T0, T0, frozenset({service}), limit=True))})

    rendered = bridge.to_dict()
    record(13, "strict metadata bridge keeps exact selection without domain invention",
           {"buildIdentity": first["buildIdentity"], "analysisRunId": "run-a", "indexSha256": first["indexSha256"],
            "configSha256": first["configSha256"], "refKinds": ["ANALYSIS_SNAPSHOT", "ARTIFACT", "MODULE", "MODULE_BUILD", "REPOSITORY", "SOURCE_REVISION"],
            "wrongIndex": "REJECTED", "wrongBuild": "REJECTED"},
           {"buildIdentity": rendered["buildIdentity"], "analysisRunId": rendered["analysisRunId"],
            "indexSha256": rendered["indexSha256"], "configSha256": rendered["configSha256"],
            "refKinds": sorted(item["kind"] for item in rendered["refs"].values()),
            "wrongIndex": rejected(lambda: require_exact_bridge(bridge, first["buildIdentity"], "f" * 64, bridge.config_sha256)),
            "wrongBuild": rejected(lambda: require_exact_bridge(bridge, rebuilt["buildIdentity"], bridge.index_sha256, bridge.config_sha256))})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases = scenarios()
    report = {"schema": "jjamtong.evidence-model-lab.v1", "syntheticInputOnly": True,
              "cases": cases, "passed": sum(item["status"] == "PASS" for item in cases), "total": len(cases),
              "limitations": ["Small in-memory identity/claim contract experiment; no capacity or auth proof.",
                              "No live collectors, full method graph migration or UI change.",
                              "BDD IDs trace selected contract assertions; Gherkin feature files are not executed."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "total": report["total"]}))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
