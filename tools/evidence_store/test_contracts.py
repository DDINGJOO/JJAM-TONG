"""Independent synthetic contract tests; these fixtures are not real executions."""
import copy
import unittest

from tools.method_evidence.evidence import digest
from .contracts import (EvidenceReader, GraphRequest, GraphResult, SnapshotRef,
                        VersionMismatch, prepare)


def method(name, descriptor="()V"):
    return {"module": "board", "class": "fixture.Board", "name": name, "descriptor": descriptor}


def rehash(index):
    index["indexSha256"] = digest({k: v for k, v in index.items() if k != "indexSha256"})
    return index


def sample(run="run-a", build="build-a"):
    methods = [method(name) for name in ("entry", "validate", "query")]
    calls = [{"caller": methods[a], "target": methods[b], "kind": "possible-call"}
             for a, b in ((0, 1), (1, 2), (2, 1))]
    config = {"schema": "jjamtong.methods.v1", "adapter": "synthetic-test", "tools": {}}
    return rehash({"schema": "jjamtong.method-index.v1", "analysisRunId": run,
                   "buildIdentity": {"repository": "local:synthetic", "revision": "rev-a", "build": build,
                                     "module": "board", "artifactSha256": "a" * 64},
                   "config": config, "configSha256": digest(config), "methods": methods,
                   "input": {}, "provenance": {"adapterVersion": "synthetic-test"},
                   "staticEvidence": {name: {"version": "synthetic-1", "methods": copy.deepcopy(methods),
                                             "calls": copy.deepcopy(calls), "unresolved": [], "excluded": []}
                                      for name in ("javaparser", "wala")},
                   "limitations": ["Synthetic storage contract fixture, not verified Java analysis."],
                   "identityAssurance": "synthetic test only"})


def reference(index, tenant="team-a"):
    return SnapshotRef(tenant, index["analysisRunId"], index["indexSha256"])


def request(index, analyzer="wala", **budgets):
    return GraphRequest(reference(index), analyzer, ("board", "fixture.Board", "entry", "()V"), **budgets)


class ContractsTests(unittest.TestCase):
    def test_exact_reference_and_budgets_are_mandatory(self):
        for tenant, run, sha in (("../a", "run-a", "a" * 64), ("a", "", "a" * 64), ("a", "r", "latest")):
            with self.assertRaises(ValueError):
                SnapshotRef(tenant, run, sha)
        for kwargs in ({"max_depth": 13}, {"max_nodes": 0}, {"max_edges": True}):
            with self.assertRaises(ValueError):
                request(sample(), **kwargs)
        with self.assertRaises(ValueError):
            request(sample(), "combined")

    def test_digest_mutation_and_inventory_mismatch_rejected(self):
        index = sample()
        index["buildIdentity"]["build"] = "changed"
        with self.assertRaises(ValueError):
            prepare(index)
        index = sample()
        index["methods"].append(method("invented"))
        with self.assertRaisesRegex(ValueError, "inventories"):
            prepare(rehash(index))

    def test_module_and_missing_analyzer_version_rejected(self):
        for field, value in (("version", ""), ("methods", [dict(method("entry"), module="wrong")])):
            index = sample()
            index["staticEvidence"]["wala"][field] = value
            with self.assertRaises(ValueError):
                prepare(rehash(index))

    def test_dangling_calls_counted_without_inventing_nodes(self):
        index = sample()
        index["staticEvidence"]["wala"]["calls"].append(
            {"caller": method("entry"), "target": method("generated-unknown"), "kind": "possible-call"})
        derived = prepare(rehash(index))
        self.assertEqual(1, derived["wala"]["coverage"]["danglingCalls"])
        self.assertEqual(3, len(derived["wala"]["nodes"]))
        self.assertEqual(3, len(derived["wala"]["edges"]))
        self.assertEqual(0, derived["javaparser"]["coverage"]["danglingCalls"])

    def test_unknown_payload_fields_are_rejected_at_every_import_level(self):
        for place in ("top", "call", "method", "input", "provenance", "unresolved"):
            index = sample()
            targets = {"top": index, "call": index["staticEvidence"]["wala"]["calls"][0],
                       "method": index["methods"][0], "input": index["input"],
                       "provenance": index["provenance"]}
            if place == "unresolved":
                index["staticEvidence"]["wala"]["unresolved"] = [{"reason": "reflection", "token": "SECRET"}]
            else:
                targets[place]["token"] = "SECRET"
            with self.subTest(place=place), self.assertRaises(ValueError):
                prepare(rehash(index))
        index = sample()
        index["staticEvidence"]["wala"]["calls"][0]["source"] = "class Board { token = SECRET; }"
        with self.assertRaises(ValueError):
            prepare(rehash(index))

    def test_malformed_containers_fail_with_validation_errors(self):
        for field, value in (("staticEvidence", None), ("methods", {}), ("config", []),
                             ("limitations", "wrong"), ("buildIdentity", "wrong")):
            index = sample()
            index[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare(rehash(index))
        index = sample()
        index["staticEvidence"]["wala"]["calls"] = "wrong"
        with self.assertRaises(ValueError):
            prepare(rehash(index))

    def test_missing_history_never_queries_another_graph(self):
        class Missing:
            def load(self, ref): return None
            def walk(self, query): raise AssertionError("Graph must not be called")
        reader = EvidenceReader(Missing(), Missing())
        self.assertEqual(["HISTORY_NOT_COLLECTED"], reader.graph(request(sample())).reasons)
        self.assertEqual("HISTORY_NOT_COLLECTED", reader.trace(reference(sample()),
                         {"spans": [], "collectionReasons": []}, "1" * 32, "c" * 64)["reason"])

    def test_replaceable_graph_port_checks_exact_projection_stamp(self):
        index = sample()
        class Source:
            def load(self, ref): return index
        class OtherEngine:
            def walk(self, query):
                stale = request(sample("run-b"))
                return GraphResult(stale, "STATIC_CANDIDATES", [], [], [], {})
        with self.assertRaises(VersionMismatch):
            EvidenceReader(Source(), OtherEngine()).graph(request(index))

    def test_consumer_rejects_wrong_repository_snapshot(self):
        class WrongSource:
            def load(self, ref): return sample("other")
        with self.assertRaises(VersionMismatch):
            EvidenceReader(WrongSource(), None).trace(reference(sample()), {}, "1" * 32, "c" * 64)


if __name__ == "__main__":
    unittest.main()
