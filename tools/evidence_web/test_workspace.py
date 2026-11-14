"""Behavioral tests for immutable selection, safe HTTP boundaries and real SQL reads."""
import copy
import http.client
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

import psycopg

from tools.evidence_store.contracts import GraphResult, VersionMismatch
from tools.evidence_store.postgres import PostgresEvidenceStore
from tools.evidence_store.test_contracts import method, reference, rehash, sample
from .server import WorkspaceServer
from .service import EvidenceWorkspace, PostgresCatalog, bounded_int


def params(index):
    return {"run_id": index["analysisRunId"], "index_sha256": index["indexSha256"]}


def captured(index):
    identity = dict(index["buildIdentity"], configSha256="c" * 64)
    return {"collectionReasons": [], "spans": [
        {"traceId": "1" * 32, "spanId": "2" * 16, "parentSpanId": "9" * 16,
         "resource": identity, "class": "fixture.Board", "method": "entry", "links": [],
         "startTimeUnixNano": 1794000000000000001, "endTimeUnixNano": "1794000000000000011", "error": False},
        {"traceId": "1" * 32, "spanId": "3" * 16, "parentSpanId": "2" * 16,
         "resource": identity, "class": "fixture.Board", "method": "validate", "links": [],
         "startTimeUnixNano": "bad", "endTimeUnixNano": True, "error": True}]}


class MemoryStore:
    def __init__(self, *indices):
        self.indices = {index["analysisRunId"]: index for index in indices}
        self.requests = []

    def load(self, ref):
        self.requests.append(ref)
        index = self.indices.get(ref.run_id)
        if index is not None and index["indexSha256"] != ref.index_sha256:
            raise VersionMismatch("Wrong hash must not choose another version")
        return copy.deepcopy(index)

    def walk(self, request):
        return GraphResult(request, "PARTIAL", [list(request.root)], [], ["NODE_LIMIT"], {})


class EmptyCatalog:
    def snapshots(self, tenant, limit, offset):
        return {"snapshots": [], "limit": limit, "offset": offset, "hasMore": False, "order": "run-id-desc"}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.index = sample()
        extra = method("validate", "(I)V")
        self.index["methods"].append(extra)
        for tool in self.index["staticEvidence"].values():
            tool["methods"].append(extra)
        self.index = rehash(self.index)
        self.other = sample("run-b", "build-b")
        self.store = MemoryStore(self.index, self.other)
        self.workspace = EvidenceWorkspace(self.store, "one-team", EmptyCatalog(), captured(self.index), "c" * 64)

    def test_snapshot_exposes_identity_and_limits_without_source_payload(self):
        result = self.workspace.snapshot(params(self.index))
        self.assertEqual("build-a", result["buildIdentity"]["build"])
        self.assertEqual(4, result["coverage"]["wala"]["inventoryMethods"])
        self.assertEqual({"ref", "buildIdentity", "schema", "analysisConfigSha256", "coverage", "sourceLimitationCount",
                          "limitations", "identityAssurance"}, set(result))

    def test_imported_diagnostic_prose_is_not_projected_to_browser(self):
        index = copy.deepcopy(self.index)
        index["limitations"] = ["analyzer diagnostic password=SECRET"]
        index["identityAssurance"] = "importer token=SECRET"
        rehash(index)
        self.store.indices[index["analysisRunId"]] = index
        result = self.workspace.snapshot(params(index))
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(1, result["sourceLimitationCount"])

    def test_exact_ref_is_required_and_never_replaced(self):
        with self.assertRaises(KeyError):
            self.workspace.snapshot({"run_id": "latest"})
        with self.assertRaises(VersionMismatch):
            self.workspace.snapshot(dict(params(self.index), index_sha256="f" * 64))
        missing = dict(params(self.index), run_id="not-collected")
        self.assertEqual("HISTORY_NOT_COLLECTED", self.workspace.graph(dict(
            missing, analyzer="wala", module="board", **{"class": "fixture.Board"}, name="entry", descriptor="()V"))["reasons"][0])
        self.assertTrue(all(ref.tenant == "one-team" for ref in self.store.requests))

    def test_search_keeps_overloads_and_analyzers_separate_with_paging(self):
        result = self.workspace.methods(dict(params(self.index), analyzer="wala", q="VALIDATE", limit="1"))
        self.assertEqual(2, result["total"])
        self.assertTrue(result["hasMore"])
        page2 = self.workspace.methods(dict(params(self.index), analyzer="wala", q="validate", limit="1", offset="1"))
        self.assertNotEqual(result["methods"][0][3], page2["methods"][0][3])
        no_result = self.workspace.methods(dict(params(self.index), analyzer="javaparser", q="' OR 1=1 --"))
        self.assertEqual([], no_result["methods"])
        with self.assertRaises(ValueError):
            self.workspace.methods(dict(params(self.index), analyzer="combined"))

    def test_graph_budget_and_partial_reason_survive_adapter(self):
        query = dict(params(self.index), analyzer="wala", module="board", **{"class": "fixture.Board"},
                     name="entry", descriptor="()V", nodes="1")
        result = self.workspace.graph(query)
        self.assertEqual(["NODE_LIMIT"], result["reasons"])
        self.assertEqual(1, result["request"]["max_nodes"])
        for field, value in (("nodes", "201"), ("edges", "501"), ("depth", "13")):
            with self.assertRaises(ValueError):
                self.workspace.graph(dict(query, **{field: value}))

    def test_trace_preserves_precision_unresolved_and_uncollected_parent(self):
        result = self.workspace.trace(dict(params(self.index), trace_id="1" * 32))
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual("1794000000000000001", result["spans"][0]["startTimeUnixNano"])
        unresolved = result["spans"][1]
        self.assertEqual("UNRESOLVED_CODE_SYMBOL", unresolved["symbolStatus"])
        self.assertEqual(2, len(unresolved["symbolCandidates"]))
        self.assertIsNone(unresolved["startTimeUnixNano"])
        self.assertIsNone(unresolved["endTimeUnixNano"])
        self.assertIn("INVALID_SPAN_TIMESTAMP", result["collectionReasons"])
        self.assertIn("PARENT_EXTERNAL_OR_NOT_COLLECTED", result["collectionReasons"])
        self.assertEqual(2, self.workspace.traces({})["traces"][0]["spanRecords"])

    def test_reversed_or_missing_time_cannot_claim_valid_observation(self):
        for start, end in ((2, 1), (None, 2), (True, 2)):
            collection = captured(self.index)
            collection["spans"] = collection["spans"][:1]
            collection["spans"][0].update(parentSpanId=None, startTimeUnixNano=start, endTimeUnixNano=end)
            workspace = EvidenceWorkspace(self.store, "one-team", EmptyCatalog(), collection, "c" * 64)
            result = workspace.trace(dict(params(self.index), trace_id="1" * 32))
            self.assertEqual("PARTIAL", result["status"])
            self.assertEqual(["INVALID_SPAN_TIMESTAMP"], result["collectionReasons"])
            self.assertIsNone(result["spans"][0]["startTimeUnixNano"])
            self.assertIsNone(result["spans"][0]["endTimeUnixNano"])

    def test_wrong_build_does_not_link_or_guess_a_method(self):
        result = self.workspace.trace(dict(params(self.other), trace_id="1" * 32))
        self.assertEqual("MISMATCH", result["status"])
        self.assertEqual([], result["spans"])
        self.assertEqual(2, len(result["rejected"]))

    def test_no_capture_and_unknown_fields_are_explicit(self):
        blank = EvidenceWorkspace(self.store, "one-team", EmptyCatalog())
        self.assertEqual("not-configured", blank.traces({})["source"])
        self.assertEqual("TRACE_CAPTURE_NOT_CONFIGURED", blank.trace(dict(params(self.index), trace_id="1" * 32))["reason"])
        for query in ({"tenant": "other-team"}, {"path": "/private/file"}):
            with self.assertRaises(ValueError):
                self.workspace.traces(query)
        for value in ("-1", "0", "1.5", "00000001", "999999"):
            with self.assertRaises(ValueError):
                bounded_int(value, 1, 200)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = sample()
        cls.workspace = EvidenceWorkspace(MemoryStore(cls.index), "one-team", EmptyCatalog())
        cls.server = WorkspaceServer(cls.workspace, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_real_http_read_projection_and_security_headers(self):
        status, headers, body = self.request("/api/snapshot?" + urlencode(params(self.index)))
        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual("nosniff", headers["X-Content-Type-Options"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual("build-a", json.loads(body)["buildIdentity"]["build"])

    def test_platform_and_preserved_demo_keep_data_and_csp_separate(self):
        status, headers, body = self.request("/")
        self.assertEqual(200, status)
        self.assertIn(b'/prototype.css', body)
        self.assertIn(b'/app.js', body)
        self.assertNotIn(b'/prototype.js', body)
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        status, headers, body = self.request("/demo")
        self.assertEqual(200, status)
        self.assertIn(b'/prototype.js', body)
        self.assertNotIn(b'src="/app.js"', body)
        self.assertIn("connect-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("style-src 'self' 'unsafe-inline'", headers["Content-Security-Policy"])
        for path in ("/prototype.css", "/prototype.js", "/platform.js", "/demo-entry.js"):
            self.assertEqual(200, self.request(path)[0])

    def test_rebinding_cross_origin_and_cross_site_fetch_are_blocked(self):
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://attacker.invalid"},
                        {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(403, self.request("/api/context", headers=headers)[0])

    def test_no_http_write_or_filesystem_endpoint(self):
        for method_name in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(405, self.request("/api/snapshot", method_name)[0])
        for path in ("/../.local/private.log", "/static/../../AGENTS.md", "/api/publish", "/api/initialize"):
            self.assertEqual(404, self.request(path)[0])

    def test_duplicate_tenant_extra_and_oversized_queries_are_rejected(self):
        for path in ("/api/snapshots?limit=1&limit=2", "/api/snapshots?tenant=other",
                     "/api/snapshots?offset=10001", "/api/graph?run_id=latest",
                     "/api/methods?q=" + "a" * 8200):
            self.assertEqual(400, self.request(path)[0])

    def test_hash_conflict_and_missing_history_remain_distinct(self):
        bad = dict(params(self.index), index_sha256="f" * 64)
        self.assertEqual(409, self.request("/api/snapshot?" + urlencode(bad))[0])
        missing = dict(params(self.index), run_id="no-such-run")
        self.assertEqual(404, self.request("/api/snapshot?" + urlencode(missing))[0])

    def test_database_failure_is_safe_and_does_not_leak_credentials(self):
        with patch.object(self.workspace.store, "load", side_effect=psycopg.OperationalError("SECRET_DSN_PASSWORD")):
            status, _, body = self.request("/api/snapshot?" + urlencode(params(self.index)))
        self.assertEqual(503, status)
        self.assertNotIn(b"SECRET", body)
        self.assertEqual("DATABASE_UNAVAILABLE", json.loads(body)["error"])

    def test_http_capacity_limit_rejects_excess_and_recovers(self):
        acquired = 0
        try:
            for _ in range(8):
                self.assertTrue(self.server.slots.acquire(timeout=1))
                acquired += 1
            self.assertEqual(503, self.request("/api/context")[0])
        finally:
            for _ in range(acquired):
                self.server.slots.release()
        self.assertEqual(200, self.request("/api/context")[0])


@unittest.skipUnless(os.environ.get("JJAMTONG_EVIDENCE_DSN"), "Explicit local DB DSN required")
class PostgresWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresEvidenceStore(os.environ["JJAMTONG_EVIDENCE_DSN"])
        self.tenant = "web-test-" + uuid4().hex
        self.first, self.second = sample(), sample("run-b", "build-b")
        self.store.publish(self.tenant, self.first)
        self.store.publish(self.tenant, self.second)
        self.workspace = EvidenceWorkspace(self.store, self.tenant, collection=captured(self.first), telemetry_config="c" * 64)

    def tearDown(self):
        with self.store._connect() as conn:
            for table in ("call", "method", "analysis"):
                conn.execute("DELETE FROM jjamtong_evidence_v1." + table + " WHERE tenant_id=%s", (self.tenant,))

    def test_catalog_is_scoped_bounded_and_explicitly_lexical(self):
        first = self.workspace.snapshots({"limit": "1"})
        self.assertEqual("run-b", first["snapshots"][0]["ref"]["run_id"])
        self.assertEqual(self.tenant, first["snapshots"][0]["ref"]["tenant"])
        self.assertTrue(first["hasMore"])
        self.assertEqual("run-id-desc", first["order"])
        second = self.workspace.snapshots({"limit": "1", "offset": "1"})
        self.assertEqual("run-a", second["snapshots"][0]["ref"]["run_id"])
        self.assertFalse(second["hasMore"])
        self.assertEqual([], self.workspace.snapshots({"offset": "2"})["snapshots"])

    def test_real_graph_trace_and_old_version_survive_reading_new_build(self):
        graph = dict(params(self.first), analyzer="wala", module="board", **{"class": "fixture.Board"},
                     name="entry", descriptor="()V")
        self.assertEqual(3, len(self.workspace.graph(graph)["methods"]))
        self.assertEqual("build-b", self.workspace.snapshot(params(self.second))["buildIdentity"]["build"])
        old = self.workspace.trace(dict(params(self.first), trace_id="1" * 32))
        wrong = self.workspace.trace(dict(params(self.second), trace_id="1" * 32))
        self.assertEqual("PARTIAL", old["status"])
        self.assertEqual("MISMATCH", wrong["status"])
        self.assertEqual([], wrong["spans"])
        self.assertEqual(3, len(self.workspace.graph(graph)["methods"]))
        self.assertEqual(self.first, self.store.load(reference(self.first, self.tenant)))

    def test_corrupt_projection_is_rejected_even_in_catalog(self):
        with self.store._connect() as conn:
            conn.execute("UPDATE jjamtong_evidence_v1.analysis SET projection_sha256=%s "
                         "WHERE tenant_id=%s AND run_id=%s", ("f" * 64, self.tenant, "run-a"))
        with self.assertRaises(VersionMismatch):
            PostgresCatalog(self.store).snapshots(self.tenant, 50, 0)


if __name__ == "__main__":
    unittest.main()
