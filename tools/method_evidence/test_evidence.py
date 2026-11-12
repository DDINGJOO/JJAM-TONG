"""Independent boundary tests: incorrect identity must never become execution evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from .evidence import (build_identity, create_index, digest, file_digest, load_index,
                       query as actual_query, read_otlp, save_index, source_digest)


def query(index, collection, trace_id, config="c" * 64, **kwargs):
    return actual_query(index, collection, trace_id, config, **kwargs)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        (self.sources / "Board.java").write_text("class Board { void find() {} }\n")
        self.artifact = self.root / "board.jar"
        self.artifact.write_bytes(b"synthetic build bytes, not a JVM execution fixture")
        self.identity = {"repository": "local:test", "revision": "rev-A", "build": "build-A", "module": "board",
                         "artifactSha256": file_digest(self.artifact)}
        self.manifest = dict(self.identity, sourceState="clean", sourceFiles=[
            {"path": "Board.java", "sha256": file_digest(self.sources / "Board.java")}])
        self.method = {"module": "board", "class": "fixture.Board", "name": "find", "descriptor": "()V"}
        self.analysis = {"schema": "jjamtong.methods.v1", "module": "board", "metadata": self.identity,
                         "input": {"artifactSha256": self.identity["artifactSha256"],
                                   "sourceTreeSha256": source_digest(self.sources)},
                         "scope": {"includePackage": "fixture"}, "provenance": {"adapterVersion": "test-1"},
                         "tools": {"javaparser": {"version": "test-1", "methods": [self.method], "calls": []},
                                   "wala": {"version": "test-2", "methods": [self.method], "calls": []}}, "limitations": []}
        self.index = create_index(self.analysis, self.manifest, self.artifact, self.sources, "run-A")
        self.trace = "1" * 32
        self.span = {"traceId": self.trace, "spanId": "2" * 16, "parentSpanId": None,
                     "resource": dict(self.identity, configSha256="c" * 64), "class": "fixture.Board", "method": "find", "links": [],
                     "startTimeUnixNano": "1", "endTimeUnixNano": "2", "error": False}

    def collection(self, *spans):
        return {"spans": list(spans), "collectionReasons": []}

    def test_exact_identity_unique_descriptor_is_derived(self):
        result = query(self.index, self.collection(self.span), self.trace)
        self.assertEqual("OBSERVED", result["status"])
        self.assertEqual("unique-name-resolved", result["spans"][0]["symbolStatus"])
        self.assertIn("derived", result["spans"][0]["symbolReason"])

    def test_each_build_field_rejects_a_false_join(self):
        for field in self.identity:
            span = copy.deepcopy(self.span)
            span["resource"][field] = "f" * 64 if field == "artifactSha256" else "wrong"
            result = query(self.index, self.collection(span), self.trace)
            self.assertEqual("MISMATCH", result["status"], field)
            self.assertFalse(result["spans"])

    def test_missing_build_or_config_stays_unresolved(self):
        span = copy.deepcopy(self.span)
        del span["resource"]["revision"]
        self.assertEqual("UNRESOLVED", query(self.index, self.collection(span), self.trace)["status"])
        self.assertEqual("UNRESOLVED", query(self.index, self.collection(self.span), self.trace, "d" * 64)["status"])
        self.assertEqual("MISSING_TELEMETRY_CONFIG", actual_query(self.index, self.collection(self.span), self.trace)["reason"])

    def test_overload_does_not_pick_a_descriptor(self):
        self.analysis["tools"]["javaparser"]["methods"].append(dict(self.method, descriptor="(I)V"))
        index = create_index(self.analysis, self.manifest, self.artifact, self.sources, "run-overload")
        record = query(index, self.collection(self.span), self.trace)["spans"][0]
        self.assertEqual("UNRESOLVED_CODE_SYMBOL", record["symbolStatus"])
        self.assertEqual(2, len(record["symbolCandidates"]))

    def test_history_is_immutable_and_explicit(self):
        save_index(self.index, self.root / "history")
        with self.assertRaises(FileExistsError):
            save_index(self.index, self.root / "history")
        self.assertEqual(self.index, load_index(self.root / "history", "run-A"))
        self.assertEqual("HISTORY_NOT_COLLECTED", query(load_index(self.root, "missing"),
                                                      self.collection(self.span), self.trace)["reason"])
        with self.assertRaises(ValueError):
            load_index(self.root, "../run-A")

    def test_actual_bytes_and_source_must_match(self):
        self.artifact.write_bytes(b"different artifact")
        with self.assertRaisesRegex(ValueError, "Artifact"):
            create_index(self.analysis, self.manifest, self.artifact, self.sources, "bad")
        self.artifact.write_bytes(b"synthetic build bytes, not a JVM execution fixture")
        (self.sources / "Board.java").write_text("changed source")
        with self.assertRaisesRegex(ValueError, "source"):
            create_index(self.analysis, self.manifest, self.artifact, self.sources, "bad")

    def test_empty_and_mutated_index_fail(self):
        self.analysis["tools"]["javaparser"]["methods"] = []
        self.analysis["tools"]["wala"]["methods"] = []
        with self.assertRaisesRegex(ValueError, "Empty"):
            create_index(self.analysis, self.manifest, self.artifact, self.sources, "empty")
        changed = copy.deepcopy(self.index)
        changed["buildIdentity"]["build"] = "new"
        with self.assertRaises(ValueError):
            query(changed, self.collection(self.span), self.trace)

    def test_parent_missing_is_partial_context_not_invented_call(self):
        span = dict(self.span, parentSpanId="3" * 16)
        result = query(self.index, self.collection(span), self.trace)
        self.assertEqual("external-or-not-collected", result["edges"][0]["parentState"])
        self.assertEqual("observed-span-parent", result["edges"][0]["relation"])
        self.assertEqual("PARTIAL", result["status"])

    def test_recursion_distinct_instances_and_collection_cap(self):
        child = dict(self.span, spanId="3" * 16, parentSpanId=self.span["spanId"])
        full = query(self.index, self.collection(self.span, child), self.trace)
        self.assertEqual(2, len(full["spans"]))
        capped = query(self.index, self.collection(self.span, child), self.trace, per_trace_limit=1)
        self.assertEqual("PARTIAL", capped["status"])
        self.assertIn("PER_TRACE_RECORD_LIMIT", capped["collectionReasons"])

    def test_conflicting_replay_is_not_silently_overwritten(self):
        self.assertEqual(1, len(query(self.index, self.collection(self.span, self.span), self.trace)["spans"]))
        with self.assertRaisesRegex(ValueError, "replay"):
            query(self.index, self.collection(self.span, dict(self.span, method="other")), self.trace)

    def test_otlp_logging_shape_and_payload_allowlist(self):
        attrs = [{"key": "jjamtong." + ("artifact.sha256" if k == "artifactSha256" else k),
                  "value": {"stringValue": v}} for k, v in self.identity.items()]
        attrs.append({"key": "jjamtong.config.sha256", "value": {"stringValue": "c" * 64}})
        raw_span = {"traceId": self.trace, "spanId": self.span["spanId"], "name": "secret span name",
                    "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in
                                   (("code.namespace", "fixture.Board"), ("code.function", "find"),
                                    ("db.query.text", "SECRET SQL"), ("url.full", "SECRET URL"))],
                    "events": [{"name": "SECRET exception body"}], "status": {"code": 2, "message": "SECRET"}}
        log = self.root / "raw.log"
        log.write_text('not JSON\n{"kind":"BUSINESS_OUTCOME"}\nINFO: ' + json.dumps({
            "resource": {"attributes": attrs}, "scopeSpans": [{"spans": [raw_span]}]}) + "\n")
        collection = read_otlp(log)
        self.assertEqual(1, len(collection["spans"]))
        self.assertTrue(collection["spans"][0]["error"])
        self.assertNotIn("SECRET", json.dumps(collection))
        self.assertEqual("OBSERVED", query(self.index, collection, self.trace)["status"])

    def test_no_spans_is_not_a_successful_execution_or_nonexecution_proof(self):
        result = query(self.index, self.collection(), self.trace)
        self.assertEqual("UNRESOLVED", result["status"])
        self.assertIn("NO_MATCHING_SPANS", result["collectionReasons"])
        self.assertEqual(build_identity(dict(self.identity, artifactSha256=self.identity["artifactSha256"].upper())),
                         self.identity)


if __name__ == "__main__":
    unittest.main()
