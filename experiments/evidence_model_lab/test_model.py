from dataclasses import replace
from datetime import datetime, timedelta, timezone
import copy
import unittest
from unittest.mock import patch

from .model import (Claim, ClaimLog, EntityKind, EntityRef, EvidenceMode, EvidenceRef, QueryRequest,
                    RelationKind, import_v1, require_exact_bridge)
from tools.evidence_store.test_contracts import rehash, sample

UTC, NOW = timezone.utc, datetime(2026, 1, 1, tzinfo=timezone.utc)

def entity(kind, name, tenant="t", provider="provider", incarnation=""):
    return EntityRef(kind, tenant, provider, name, incarnation)

def evidence(tenant="t", source="source"):
    return EvidenceRef(tenant, "provider", source, "record")

def make_claim(cid, subject, relation, object, mode, known=NOW, valid_to=None, **changes):
    values = dict(claim_id=cid, tenant=subject.tenant, subject=subject, relation=relation, object=object,
                  mode=mode, evidence=evidence(subject.tenant), valid_from=NOW, known_at=known, valid_to=valid_to)
    values.update(changes)
    return Claim(**values)

def query(subject, relation, allowed, **changes):
    values = dict(tenant=subject.tenant, subject=subject, relation=relation, valid_at=NOW, known_at=NOW,
                  allowed_refs=frozenset(allowed), visibility_complete=True)
    values.update(changes)
    return QueryRequest(**values)

class EvidenceModelTests(unittest.TestCase):
    def test_bridge_preserves_five_fields_and_rejects_wrong_hashes(self):
        index = sample(); bridge = import_v1(index, "t")
        self.assertEqual(tuple(dict(bridge.build_identity)), ("repository", "revision", "build", "module", "artifactSha256"))
        self.assertEqual(bridge.analysis_snapshot.incarnation, index["indexSha256"])
        with self.assertRaisesRegex(ValueError, "exact"):
            require_exact_bridge(bridge, index["buildIdentity"], "b" * 64, bridge.config_sha256)
        changed = sample(build="changed")
        self.assertNotEqual(bridge.module_build, import_v1(changed, "t").module_build)

    def test_bridge_scopes_revision_and_module_and_hashes_full_identity(self):
        first = sample()
        second = sample()
        second["buildIdentity"]["repository"] = "local:other"
        rehash(second)
        different_artifact = sample()
        different_artifact["buildIdentity"]["artifactSha256"] = "b" * 64
        rehash(different_artifact)
        one, two, artifact_changed = (import_v1(index, "t") for index in (first, second, different_artifact))
        self.assertNotEqual(one.source_revision, two.source_revision)
        self.assertNotEqual(one.module, two.module)
        self.assertNotEqual(one.module_build, artifact_changed.module_build)
        self.assertLessEqual(len(one.module_build.native_id), 512)
        self.assertTrue(one.module_build.native_id.startswith("sha256:"))

    def test_bridge_is_metadata_only_and_input_mutation_does_not_change_it(self):
        index = sample(); bridge = import_v1(index, "t"); index["buildIdentity"]["build"] = "other"
        rendered = bridge.to_dict()
        self.assertEqual(dict(bridge.build_identity)["build"], "build-a")
        self.assertIn("no method inventory imported", rendered["limitations"])
        self.assertNotIn("service", rendered["refs"])

    def test_bridge_copies_payload_before_strict_validation(self):
        index = sample()
        from tools.evidence_store import contracts
        original_prepare = contracts.prepare

        def validate_copy(payload):
            self.assertIsNot(payload, index)
            index["buildIdentity"]["build"] = "caller-mutated"
            return original_prepare(payload)

        with patch("tools.evidence_store.contracts.prepare", side_effect=validate_copy):
            bridge = import_v1(index, "t")
        self.assertEqual(dict(bridge.build_identity)["build"], "build-a")

    def test_entity_scope_and_incarnation_are_identity_not_display_name(self):
        self.assertNotEqual(entity(EntityKind.RESOURCE, "db", "a"), entity(EntityKind.RESOURCE, "db", "b"))
        self.assertNotEqual(entity(EntityKind.POD, "orders", incarnation="uid-1"), entity(EntityKind.POD, "orders", incarnation="uid-2"))
        self.assertNotEqual(entity(EntityKind.RESOURCE, "db", incarnation="one"), entity(EntityKind.RESOURCE, "db", incarnation="two"))
        with self.assertRaisesRegex(ValueError, "incarnation"):
            entity(EntityKind.POD, "pod", incarnation=" ")

    def test_closed_relations_and_modes_reject_invalid_combinations(self):
        method, resource = entity(EntityKind.METHOD_VERSION, "m"), entity(EntityKind.RESOURCE, "db")
        with self.assertRaisesRegex(ValueError, "mode"):
            make_claim("x", method, RelationKind.STATIC_CALL, entity(EntityKind.METHOD_VERSION, "n"), EvidenceMode.OBSERVED)
        with self.assertRaisesRegex(ValueError, "endpoint"):
            make_claim("y", method, RelationKind.STATIC_CALL, resource, EvidenceMode.STATIC_CANDIDATE)
        with self.assertRaisesRegex(ValueError, "mode"):
            make_claim("z", entity(EntityKind.SERVICE, "s"), RelationKind.CATALOG_MAPS, resource, EvidenceMode.OBSERVED)

    def test_invalid_kind_cross_tenant_missing_evidence_and_id_collision_fail(self):
        with self.assertRaises(ValueError):
            EntityRef("SERVICE", "t", "provider", "s")
        service, resource = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "r")
        with self.assertRaisesRegex(ValueError, "cross-tenant"):
            make_claim("cross", service, RelationKind.USES_RESOURCE, entity(EntityKind.RESOURCE, "r", "other"), EvidenceMode.DECLARED)
        with self.assertRaisesRegex(ValueError, "typed"):
            Claim("missing", "t", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED, None, NOW, NOW)
        log = ClaimLog(); log.append(make_claim("same", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED))
        with self.assertRaisesRegex(ValueError, "collision"):
            log.append(make_claim("same", service, RelationKind.USES_RESOURCE, entity(EntityKind.RESOURCE, "other"), EvidenceMode.DECLARED))

    def test_equivalence_is_a_claim_not_an_identity_merge(self):
        first = entity(EntityKind.RESOURCE, "db", provider="aws")
        second = entity(EntityKind.RESOURCE, "db", provider="cmdb")
        self.assertNotEqual(first, second)
        log = ClaimLog(); log.append(make_claim("equivalent", first, RelationKind.EQUIVALENT_TO, second, EvidenceMode.DECLARED))
        self.assertEqual(log.query(query(first, RelationKind.EQUIVALENT_TO, (first, second))).object_refs, (second,))

    def test_valid_time_is_utc_half_open(self):
        service, resource = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "r")
        with self.assertRaises(ValueError):
            make_claim("bad", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED, valid_to=NOW)
        with self.assertRaises(ValueError):
            make_claim("naive", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED, known=datetime(2026, 1, 1))
        log = ClaimLog(); log.append(make_claim("edge", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED, valid_to=NOW + timedelta(hours=1)))
        self.assertEqual(log.query(query(service, RelationKind.USES_RESOURCE, (service, resource), valid_at=NOW + timedelta(hours=1))).status, "NO_MATCH_IN_KNOWN_EVIDENCE")

    def test_late_knowledge_and_correction_preserve_past_query(self):
        service, old, new = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "old"), entity(EntityKind.RESOURCE, "new")
        log = ClaimLog(); log.append(make_claim("old", service, RelationKind.USES_RESOURCE, old, EvidenceMode.DECLARED, known=NOW + timedelta(hours=1)))
        log.append(make_claim("new", service, RelationKind.USES_RESOURCE, new, EvidenceMode.DECLARED,
                              known=NOW + timedelta(hours=2), supersedes="old",
                              evidence=EvidenceRef("t", "provider", "source", "corrected-record")))
        self.assertEqual(log.query(query(service, RelationKind.USES_RESOURCE, (service, old, new), known_at=NOW + timedelta(hours=1))).claim_ids, ("old",))
        self.assertEqual(log.query(query(service, RelationKind.USES_RESOURCE, (service, old, new), known_at=NOW + timedelta(hours=2))).claim_ids, ("new",))

    def test_supersession_retraction_and_replays_are_constrained(self):
        service, one, two = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "one"), entity(EntityKind.RESOURCE, "two")
        log = ClaimLog(); original = make_claim("one", service, RelationKind.USES_RESOURCE, one, EvidenceMode.DECLARED); log.append(original)
        with self.assertRaisesRegex(ValueError, "replay"): log.append(original)
        with self.assertRaisesRegex(ValueError, "mode"): log.append(make_claim("bad", service, RelationKind.USES_RESOURCE, two, EvidenceMode.OBSERVED, supersedes="one"))
        with self.assertRaisesRegex(ValueError, "not known"): log.append(make_claim("future", service, RelationKind.USES_RESOURCE, two, EvidenceMode.DECLARED, retracts="absent"))
        with self.assertRaisesRegex(ValueError, "both"):
            make_claim("both", service, RelationKind.USES_RESOURCE, one, EvidenceMode.DECLARED, supersedes="one", retracts="one")
        with self.assertRaisesRegex(ValueError, "object"):
            log.append(make_claim("wrong-object", service, RelationKind.USES_RESOURCE, two, EvidenceMode.DECLARED, retracts="one"))
        log.append(make_claim("retract", service, RelationKind.USES_RESOURCE, one, EvidenceMode.DECLARED,
                              retracts="one", evidence=EvidenceRef("t", "provider", "source", "new-record")))
        self.assertEqual(log.query(query(service, RelationKind.USES_RESOURCE, (service, one))).status, "NO_MATCH_IN_KNOWN_EVIDENCE")

    def test_correction_removes_original_before_valid_time_filtering(self):
        service, old, new = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "old"), entity(EntityKind.RESOURCE, "new")
        log = ClaimLog()
        log.append(make_claim("old", service, RelationKind.USES_RESOURCE, old, EvidenceMode.DECLARED,
                              valid_to=NOW + timedelta(hours=2)))
        log.append(make_claim("corrected", service, RelationKind.USES_RESOURCE, new, EvidenceMode.DECLARED,
                              known=NOW + timedelta(hours=1), valid_to=NOW + timedelta(hours=1), supersedes="old"))
        result = log.query(query(service, RelationKind.USES_RESOURCE, (service, old, new),
                                 valid_at=NOW + timedelta(minutes=90), known_at=NOW + timedelta(hours=1)))
        self.assertEqual(result.status, "NO_MATCH_IN_KNOWN_EVIDENCE")

    def test_many_valued_catalog_and_service_module_relations(self):
        service, one, two = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "one"), entity(EntityKind.RESOURCE, "two")
        module = entity(EntityKind.MODULE, "module")
        log = ClaimLog()
        log.append(make_claim("catalog-a", service, RelationKind.CATALOG_MAPS, one, EvidenceMode.DECLARED))
        log.append(make_claim("catalog-b", service, RelationKind.CATALOG_MAPS, two, EvidenceMode.DECLARED, evidence=evidence(source="second")))
        log.append(make_claim("uses-module", service, RelationKind.SERVICE_USES_MODULE, module, EvidenceMode.DECLARED))
        self.assertEqual(log.query(query(service, RelationKind.CATALOG_MAPS, (service, one, two))).status, "MATCH")
        self.assertEqual(log.query(query(service, RelationKind.SERVICE_USES_MODULE, (service, module))).status, "MATCH")

    def test_primary_runtime_build_conflict_is_bounded(self):
        runtime = entity(EntityKind.RUNTIME, "runtime")
        one, two = entity(EntityKind.MODULE_BUILD, "one"), entity(EntityKind.MODULE_BUILD, "two")
        log = ClaimLog()
        log.append(make_claim("b", runtime, RelationKind.RUNTIME_PRIMARY_BUILD, one, EvidenceMode.OBSERVED))
        log.append(make_claim("a", runtime, RelationKind.RUNTIME_PRIMARY_BUILD, two, EvidenceMode.DECLARED,
                              evidence=evidence(source="second")))
        result = log.query(query(runtime, RelationKind.RUNTIME_PRIMARY_BUILD, (runtime, one, two), limit=1))
        self.assertEqual((result.status, result.claim_ids, result.reasons),
                         ("PARTIAL", ("a",), ("QUERY_LIMIT", "CONFLICTING_SINGLE_VALUE")))
        self.assertEqual(tuple(claim.claim_id for claim in result.claims), ("a",))

    def test_query_returns_full_visible_claim_provenance(self):
        service, resource = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "r")
        claim = make_claim("claim", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED)
        log = ClaimLog(); log.append(claim)
        result = log.query(query(service, RelationKind.USES_RESOURCE, (service, resource)))
        self.assertEqual(result.claims, (claim,))
        self.assertEqual(result.to_dict()["claims"][0]["evidence"]["originalRef"], "record")

    def test_visible_correction_does_not_expose_hidden_history_ids(self):
        service = entity(EntityKind.SERVICE, "service")
        hidden, visible = entity(EntityKind.RESOURCE, "hidden"), entity(EntityKind.RESOURCE, "visible")
        original = make_claim("hidden-claim-id", service, RelationKind.USES_RESOURCE, hidden, EvidenceMode.DECLARED)
        correction = make_claim("visible-correction", service, RelationKind.USES_RESOURCE, visible,
                                EvidenceMode.DECLARED, known=NOW + timedelta(seconds=1), supersedes=original.claim_id)
        log = ClaimLog(); log.append(original); log.append(correction)
        request = query(service, RelationKind.USES_RESOURCE, (service, visible), known_at=NOW + timedelta(seconds=2))
        result = log.query(request)
        baseline = ClaimLog(); baseline.append(replace(correction, supersedes=None))
        self.assertEqual(result, baseline.query(request))
        self.assertIsNone(result.claims[0].supersedes)
        self.assertNotIn(original.claim_id, str(result.to_dict()))
        # The immutable input retains its original linkage for ledger history.
        self.assertEqual(correction.supersedes, original.claim_id)

    def test_rolling_release_scenario_rejects_corrupted_bridge_identity(self):
        from . import run as lab
        original_import = lab.import_v1

        def corrupt_identity(*args, **kwargs):
            bridge = original_import(*args, **kwargs)
            fields = tuple((key, "corrupted" if key == "build" else value)
                           for key, value in bridge.build_identity)
            return replace(bridge, build_identity=fields)

        with patch.object(lab, "import_v1", side_effect=corrupt_identity):
            result = next(case for case in lab.scenarios() if case["scenarioId"] == "BDD-MDL-003")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["expected"]["oldBuild"]["build"], "build-a")
        self.assertEqual(result["actual"]["oldBuild"]["build"], "corrupted")

    def test_visibility_is_caller_declared_and_noninterfering(self):
        service, visible, hidden = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "visible"), entity(EntityKind.RESOURCE, "hidden")
        baseline = ClaimLog(); baseline.append(make_claim("visible", service, RelationKind.USES_RESOURCE, visible, EvidenceMode.DECLARED))
        with_hidden = ClaimLog(); with_hidden.append(make_claim("visible", service, RelationKind.USES_RESOURCE, visible, EvidenceMode.DECLARED))
        with_hidden.append(make_claim("hidden-correction", service, RelationKind.USES_RESOURCE, hidden, EvidenceMode.DECLARED,
                                      supersedes="visible", evidence=EvidenceRef("t", "provider", "source", "hidden-record")))
        visible_request = query(service, RelationKind.USES_RESOURCE, (service, visible))
        self.assertEqual(baseline.query(visible_request), with_hidden.query(visible_request))
        incomplete = with_hidden.query(query(service, RelationKind.USES_RESOURCE, (service, visible), visibility_complete=False))
        self.assertEqual(incomplete.to_dict(), {"status":"INCOMPLETE", "claimIds":[], "objectRefs":[], "claims":[], "reasons":["INCOMPLETE_VISIBILITY"]})
        self.assertEqual(with_hidden.query(query(service, RelationKind.USES_RESOURCE, (visible,))).status, "INCOMPLETE")

    def test_query_budget_and_observed_filter_are_explicit(self):
        service, resource = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "r")
        with self.assertRaises(ValueError): query(service, RelationKind.USES_RESOURCE, (service,), limit=True)
        log = ClaimLog(); log.append(make_claim("declared", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED))
        result = log.query(query(service, RelationKind.USES_RESOURCE, (service, resource), modes=frozenset({EvidenceMode.OBSERVED})))
        self.assertEqual(result.status, "NO_MATCH_IN_KNOWN_EVIDENCE")

    def test_query_rejects_untyped_or_cross_tenant_refs_before_dereference(self):
        service, resource = entity(EntityKind.SERVICE, "s"), entity(EntityKind.RESOURCE, "r")
        with self.assertRaisesRegex(ValueError, "typed"):
            QueryRequest("t", "not-a-ref", RelationKind.USES_RESOURCE, NOW, NOW, frozenset())
        with self.assertRaisesRegex(ValueError, "tenant"):
            query(service, RelationKind.USES_RESOURCE, (service, entity(EntityKind.RESOURCE, "other", tenant="other")))
        with self.assertRaisesRegex(ValueError, "typed"):
            Claim("bad", "t", service, RelationKind.USES_RESOURCE, resource, EvidenceMode.DECLARED,
                  "not-evidence", NOW, NOW)

    def test_pod_can_host_multiple_runtime_builds(self):
        pod = entity(EntityKind.POD, "pod", incarnation="uid")
        runtime_a, runtime_b = entity(EntityKind.RUNTIME, "container-a"), entity(EntityKind.RUNTIME, "container-b")
        log = ClaimLog(); log.append(make_claim("a", pod, RelationKind.HOSTS_RUNTIME, runtime_a, EvidenceMode.OBSERVED)); log.append(make_claim("b", pod, RelationKind.HOSTS_RUNTIME, runtime_b, EvidenceMode.OBSERVED))
        self.assertEqual(log.query(query(pod, RelationKind.HOSTS_RUNTIME, (pod, runtime_a, runtime_b))).status, "MATCH")
