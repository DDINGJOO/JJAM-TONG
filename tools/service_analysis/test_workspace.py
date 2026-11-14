"""Consumer scenarios for API-first exploration, privacy filters and graph bounds."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from tools.evidence_web.server import WorkspaceServer
from .workspace import SourceWorkspace


def fixture():
    def method(mid, name, visibility="public", kind="method", noise=()):
        return {"id": mid, "module": "web", "className": "sample.Board", "name": name,
                "signature": name + "()", "path": "web/src/main/java/sample/Board.java", "line": 2,
                "kind": kind, "visibility": visibility, "abstract": False, "static": False,
                "noiseReasons": list(noise)}
    return {"schema": "jjamtong.service-source.v1",
            "service": {"name": "Synthetic board", "revision": "a" * 40, "dirty": False,
                        "sourceSha256": "b" * 64, "capturedAt": "2026-11-14T00:00:00Z",
                        "scope": "SOURCE_DECLARATIONS", "runtime": "not-collected", "artifact": "not-linked"},
            "metrics": {"sourceFiles": 1, "parsedFiles": 1, "failedFiles": 0, "methodCount": 6,
                        "routeCount": 2, "edgeCount": 3, "unresolvedCallCount": 0, "abstractDeclarations": 0,
                        "analysisSeconds": 0.1, "maxRssBytes": 1000},
            "modules": [{"id": "web", "name": "web", "sourceFiles": 1, "methods": 6, "routes": 2}],
            "limitations": [],
            "methods": [method("handler", "create"), method("private", "validate", "private"),
                        method("repo", "save"), method("init", "<init>", kind="constructor"),
                        method("single", "health"), method("island", "helper")],
            "endpoints": [{"id": "route", "module": "web", "httpMethod": "POST", "path": "/posts",
                           "controller": "sample.Board", "handlerId": "handler", "resolution": "literal",
                           "source": {"path": "web/src/main/java/sample/Board.java", "line": 2}, "notes": []},
                          {"id": "health", "module": "web", "httpMethod": "GET", "path": "/health",
                           "controller": "sample.Board", "handlerId": "single", "resolution": "literal",
                           "source": {"path": "web/src/main/java/sample/Board.java", "line": 2}, "notes": []}],
            "edges": [{"source": "handler", "target": "private", "kind": "source-resolved",
                       "sites": [{"line": 7, "conditions": [{"kind": "if", "expression": "allowed", "branch": "then"}]}]},
                      {"source": "private", "target": "repo", "kind": "source-resolved", "sites": []},
                      {"source": "repo", "target": "private", "kind": "source-resolved", "sites": []}],
            "diagnostics": {}}


class SourceWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "snapshot.json"
        self.path.write_text(json.dumps(fixture()))
        self.workspace = SourceWorkspace(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_api_entry_points_include_singleton_and_server_search(self):
        result = self.workspace.endpoints({"q": "/HEALTH"})
        self.assertEqual([r["handlerId"] for r in result["items"]], ["single"])
        graph = self.workspace.graph({"method_id": "single"})
        self.assertEqual(graph["edges"], [])
        self.assertEqual([m["id"] for m in graph["methods"]], ["single"])

    def test_private_filter_is_reversible_and_never_changes_edges(self):
        visible = self.workspace.methods({"include_private": "false"})
        self.assertNotIn("private", [m["id"] for m in visible["items"]])
        all_methods = self.workspace.methods({"focus": "all", "include_private": "true"})
        self.assertEqual(all_methods["total"], 6)
        graph = self.workspace.graph({"method_id": "handler"})
        self.assertEqual({(e["source"], e["target"]) for e in graph["edges"]},
                         {("handler", "private"), ("private", "repo"), ("repo", "private")})
        self.assertEqual(graph["edges"][0]["sites"][0]["conditions"][0]["expression"], "allowed")

    def test_default_focus_suppresses_noise_but_not_singleton_routes(self):
        result = self.workspace.methods({})
        ids = {m["id"] for m in result["items"]}
        self.assertTrue({"handler", "private", "repo", "single"} <= ids)
        self.assertFalse({"init", "island"} & ids)
        self.assertEqual(result["hiddenCount"], 2)

    def test_bounds_cycles_paging_and_no_silent_unknown_identity(self):
        graph = self.workspace.graph({"method_id": "handler", "nodes": "2"})
        self.assertEqual(graph["counts"]["nodes"], 2)
        self.assertEqual(graph["reasons"][0]["code"], "DISPLAY_LIMIT")
        self.assertEqual(self.workspace.endpoints({"limit": "1"})["hasMore"], True)
        with self.assertRaises(KeyError):
            self.workspace.graph({"method_id": "missing"})
        for params in ({"depth": "-1"}, {"nodes": "201"}, {"edges": "0"}, {"depth": "１２"}):
            with self.assertRaises(ValueError):
                self.workspace.graph(dict(params, method_id="handler"))

    def test_snapshot_rejects_duplicate_or_dangling_identity(self):
        for invalid in ("duplicate", "dangling"):
            data = fixture()
            if invalid == "duplicate":
                data["methods"].append(data["methods"][0])
            else:
                data["edges"][0]["target"] = "absent"
            self.path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                SourceWorkspace(self.path)

    def test_http_scope_origin_assets_readonly_and_invalid_query(self):
        with WorkspaceServer(self.workspace, 0,
                             assets={"/service-analysis": ("service.html", "text/html; charset=utf-8")},
                             routes={"/api/service/summary": "summary", "/api/service/methods": "methods"},
                             inline_styles=("/service-analysis",)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, method="GET", headers=None):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request(method, path, headers=headers or {})
                    response = connection.getresponse()
                    body, status, result_headers = response.read(), response.status, dict(response.getheaders())
                    connection.close()
                    return status, body, result_headers
                status, body, headers = request("/service-analysis")
                self.assertEqual(status, 200)
                self.assertIn(b"service.js", body)
                self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
                self.assertIn("'unsafe-inline'", headers["Content-Security-Policy"])
                self.assertEqual(request("/api/service/summary")[0], 200)
                self.assertEqual(request("/api/service/summary", headers={"Host": "attacker.invalid"})[0], 403)
                self.assertEqual(request("/api/service/summary", headers={"Origin": "https://attacker.invalid"})[0], 403)
                self.assertEqual(request("/api/service/methods?limit=1&limit=2")[0], 400)
                self.assertEqual(request("/../../secret")[0], 404)
                self.assertEqual(request("/api/service/summary", "POST")[0], 405)
            finally:
                server.shutdown()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
