"""Real PostgreSQL tests. Each test cleans up only its own unique namespaces."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from .contracts import (EvidenceReader, GraphRequest, SnapshotConflict, SnapshotRef,
                        VersionMismatch)
from .test_contracts import method, reference, rehash, request, sample


@unittest.skipUnless(os.environ.get("JJAMTONG_EVIDENCE_DSN"), "Local PostgreSQL DSN not provided")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        from .postgres import PostgresEvidenceStore
        self.store = PostgresEvidenceStore(os.environ["JJAMTONG_EVIDENCE_DSN"])
        self.store.initialize()
        self.tenant = "test-" + uuid.uuid4().hex
        self.index = sample()
        self.ref = reference(self.index, self.tenant)
        self.addCleanup(self.clean)

    def clean(self):
        # Only this test's explicit namespaces; never truncate another client's data.
        with self.store._connect() as conn:
            for table in ("call", "method", "analysis"):
                conn.execute("DELETE FROM jjamtong_evidence_v1." + table + " WHERE tenant_id=ANY(%s)",
                             ([self.tenant, self.tenant + "-other"],))

    def walk(self, **budgets):
        req = request(self.index, **budgets)
        return self.store.walk(GraphRequest(self.ref, req.analyzer, req.root,
                                           req.max_depth, req.max_nodes, req.max_edges))

    def test_roundtrip_reopen_and_identical_retry(self):
        self.assertTrue(self.store.publish(self.tenant, self.index))
        self.assertFalse(self.store.publish(self.tenant, self.index))
        reopened = type(self.store)(self.store.dsn)
        self.assertEqual(self.index, reopened.load(self.ref))

    def test_conflicting_publish_is_immutable(self):
        self.store.publish(self.tenant, self.index)
        changed = sample(build="build-b")
        with self.assertRaises(SnapshotConflict):
            self.store.publish(self.tenant, changed)
        self.assertEqual(self.index, self.store.load(self.ref))

    def test_concurrent_conflicting_publish_has_one_winner(self):
        def publish(index):
            try:
                return self.store.publish(self.tenant, index)
            except SnapshotConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(publish, [self.index, sample(build="build-b")]))
        self.assertCountEqual([True, "conflict"], outcomes)

    def test_concurrent_identical_retry_is_idempotent(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: self.store.publish(self.tenant, self.index), range(2)))
        self.assertCountEqual([True, False], outcomes)

    def test_projection_failure_rolls_back_source_and_graph(self):
        base = type(self.store)
        class Failing(base):
            def _insert_projection(self, conn, ref, derived):
                super()._insert_projection(conn, ref, derived)
                raise RuntimeError("synthetic failure before commit")
        with self.assertRaises(RuntimeError):
            Failing(self.store.dsn).publish(self.tenant, self.index)
        self.assertIsNone(self.store.load(self.ref))
        with self.store._connect() as conn:
            for table in ("method", "call"):
                count = conn.execute("SELECT count(*) FROM jjamtong_evidence_v1." + table +
                                     " WHERE tenant_id=%s", (self.tenant,)).fetchone()[0]
                self.assertEqual(0, count)
        self.assertTrue(self.store.publish(self.tenant, self.index))

    def test_tenants_same_run_and_builds_do_not_mix(self):
        self.store.publish(self.tenant, self.index)
        changed = sample(build="build-b")
        other = self.tenant + "-other"
        self.store.publish(other, changed)
        self.assertEqual(changed, self.store.load(reference(changed, other)))
        self.assertEqual(self.index, self.store.load(self.ref))
        missing = SnapshotRef(self.tenant, "not-collected", self.ref.index_sha256)
        self.assertIsNone(self.store.load(missing))
        with self.assertRaises(VersionMismatch):
            self.store.load(reference(changed, self.tenant))

    def test_projection_stamp_mismatch_is_rejected(self):
        self.store.publish(self.tenant, self.index)
        with self.store._connect() as conn:
            conn.execute("UPDATE jjamtong_evidence_v1.analysis SET projection_sha256=%s WHERE tenant_id=%s",
                         ("f" * 64, self.tenant))
        with self.assertRaises(VersionMismatch):
            self.store.load(self.ref)
        with self.assertRaises(VersionMismatch):
            self.walk()

    def test_cycle_terminates_and_keeps_static_provenance(self):
        self.store.publish(self.tenant, self.index)
        result = self.walk()
        self.assertEqual("STATIC_CANDIDATES", result.status)
        self.assertEqual(3, len(result.methods))
        self.assertEqual(3, len(result.calls))
        self.assertEqual({"possible-call"}, {item["kind"] for item in result.calls})

    def test_depth_node_edge_limits_are_partial(self):
        self.store.publish(self.tenant, self.index)
        for kwargs, reason in (({"max_depth": 1}, "DEPTH_LIMIT"),
                               ({"max_nodes": 1}, "NODE_LIMIT"), ({"max_edges": 1}, "EDGE_LIMIT")):
            result = self.walk(**kwargs)
            self.assertEqual("PARTIAL", result.status)
            self.assertIn(reason, result.reasons)
            self.assertLessEqual(len(result.methods), kwargs.get("max_nodes", 200))
            self.assertLessEqual(len(result.calls), kwargs.get("max_edges", 500))

    def test_analyzers_and_unknown_targets_are_separate(self):
        index = copy.deepcopy(self.index)
        index["staticEvidence"]["javaparser"]["calls"] = []
        tool = index["staticEvidence"]["wala"]
        tool["unresolved"] = [{"reason": "reflection target not inferred"}]
        tool["excluded"] = [{"reason": "out of scope"}]
        tool["calls"].append({"caller": method("entry"), "target": method("unknown"), "kind": "possible-call"})
        self.index, self.ref = rehash(index), reference(rehash(index), self.tenant)
        self.store.publish(self.tenant, self.index)
        result = self.walk()
        self.assertEqual({"ANALYZER_UNRESOLVED", "ANALYZER_EXCLUDED", "DANGLING_STATIC_CALLS"}, set(result.reasons))
        self.assertEqual(3, len(result.methods))
        self.assertEqual(3, len(result.calls))
        jp = self.store.walk(GraphRequest(self.ref, "javaparser", request(index).root))
        self.assertEqual(1, len(jp.methods))
        self.assertFalse(jp.calls)

    def test_exact_missing_root_does_not_pick_overload(self):
        self.store.publish(self.tenant, self.index)
        result = self.store.walk(GraphRequest(self.ref, "wala", ("board", "fixture.Board", "entry", "(I)V")))
        self.assertEqual(["ROOT_NOT_IN_ANALYZER"], result.reasons)
        self.assertFalse(result.methods)

    def test_existing_trace_consumer_uses_exact_persisted_build(self):
        self.store.publish(self.tenant, self.index)
        reader = EvidenceReader(self.store, self.store)
        span = {"traceId": "1" * 32, "spanId": "2" * 16, "parentSpanId": None,
                "resource": dict(self.index["buildIdentity"], configSha256="c" * 64),
                "class": "fixture.Board", "method": "entry", "links": []}
        collection = {"spans": [span], "collectionReasons": []}
        self.assertEqual("OBSERVED", reader.trace(self.ref, collection, "1" * 32, "c" * 64)["status"])
        newer = sample("run-b", "build-b")
        self.store.publish(self.tenant, newer)
        self.assertEqual("MISMATCH", reader.trace(reference(newer, self.tenant), collection,
                                                "1" * 32, "c" * 64)["status"])
        self.assertEqual(3, len(reader.graph(GraphRequest(self.ref, "wala", request(self.index).root)).methods))

    def test_real_statement_timeout_returns_partial_at_traversal_boundary(self):
        self.store.publish(self.tenant, self.index)
        from .contracts import symbol_json
        class SlowConnection:
            def __init__(self, conn): self.conn = conn
            def execute(self, sql, params=None):
                if "SELECT target,evidence" in sql:
                    self.conn.execute("SET LOCAL statement_timeout='10ms'")
                    self.conn.execute("SELECT pg_sleep(0.1)")
                return self.conn.execute(sql, params)
            def rollback(self): self.conn.rollback()
        req = GraphRequest(self.ref, "wala", request(self.index).root)
        with self.store._connect() as conn:
            coverage = conn.execute("SELECT coverage FROM jjamtong_evidence_v1.analysis "
                                    "WHERE tenant_id=%s", (self.tenant,)).fetchone()[0]["wala"]
            result = self.store._walk(SlowConnection(conn), req, coverage, symbol_json(req.root))
        self.assertEqual("PARTIAL", result.status)
        self.assertEqual(["TIME_BUDGET"], result.reasons)
        self.assertEqual([list(req.root)], result.methods)

    def test_timeout_before_root_validation_is_unresolved(self):
        import psycopg
        with patch.object(self.store, "_read_graph", side_effect=psycopg.errors.QueryCanceled):
            result = self.walk()
        self.assertEqual("UNRESOLVED", result.status)
        self.assertEqual(["TIME_BUDGET"], result.reasons)

    def test_public_reader_normalizes_real_repository_preflight_timeout(self):
        self.store.publish(self.tenant, self.index)
        original = self.store._connect
        @contextmanager
        def slow_connect():
            with original() as conn:
                class SlowLookup:
                    def execute(self, sql, params=None):
                        if "projection_sha256,document" in sql:
                            conn.execute("SET LOCAL statement_timeout='10ms'")
                            conn.execute("SELECT pg_sleep(0.1)")
                        return conn.execute(sql, params)
                yield SlowLookup()
        req = GraphRequest(self.ref, "wala", request(self.index).root)
        with patch.object(self.store, "_connect", slow_connect):
            result = EvidenceReader(self.store, self.store).graph(req)
        self.assertEqual("UNRESOLVED", result.status)
        self.assertEqual(["TIME_BUDGET"], result.reasons)
        self.assertFalse(result.methods)

    def test_payload_extension_is_rejected_before_any_database_write(self):
        index = copy.deepcopy(self.index)
        index["staticEvidence"]["wala"]["calls"][0]["token"] = "SECRET-never-persist"
        with self.assertRaises(ValueError):
            self.store.publish(self.tenant, rehash(index))
        with self.store._connect() as conn:
            self.assertEqual(0, conn.execute("SELECT count(*) FROM jjamtong_evidence_v1.analysis "
                                            "WHERE tenant_id=%s", (self.tenant,)).fetchone()[0])

    def test_cli_invalid_input_has_no_traceback_or_payload_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            index = copy.deepcopy(self.index)
            index["token"] = "SECRET-never-print"
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(rehash(index)))
            result = subprocess.run([sys.executable, "-m", "tools.evidence_store", "publish",
                                     "--tenant", self.tenant, "--index", str(path)],
                                    text=True, capture_output=True)
        self.assertEqual(2, result.returncode)
        self.assertIn("Invalid evidence input", result.stderr)
        self.assertNotIn("SECRET", result.stderr + result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
