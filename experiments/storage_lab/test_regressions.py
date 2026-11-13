"""Regression cases for failures observed while running real databases."""
import unittest

from .fixtures import record
from .stores import Elasticsearch, Neo4j


class ConflictHTTP:
    def __init__(self, current):
        self.current = current

    def request(self, method, path, *args, **kwargs):
        if path == "/_bulk":
            return {"items": [{"index": {"status": 409, "error": {"type": "version_conflict_engine_exception"}}}]}
        return self.current


class ProjectionRegressions(unittest.TestCase):
    def test_search_conflict_without_retained_evidence_is_not_success(self):
        adapter = Elasticsearch()
        adapter.http.close()
        adapter.http = ConflictHTTP({"found": False})
        with self.assertRaisesRegex(RuntimeError, "fresh index"):
            adapter.put([record("alpha", "A", "event", "e")])

    def test_old_event_can_be_ignored_only_when_newer_evidence_exists(self):
        adapter = Elasticsearch()
        adapter.http.close()
        adapter.http = ConflictHTTP({"found": True, "_source": {"seq": 2, "deleted": 1}})
        adapter.put([record("alpha", "A", "event", "e")])

    def test_missing_graph_endpoint_cannot_be_acknowledged(self):
        adapter = Neo4j()
        adapter.http.close()
        adapter.cypher = lambda *args: [[0]]
        with self.assertRaisesRegex(RuntimeError, "missing graph endpoints"):
            adapter.put([record("alpha", "A", "edge", "e", source="missing-a", target="missing-b")])


if __name__ == "__main__":
    unittest.main()
