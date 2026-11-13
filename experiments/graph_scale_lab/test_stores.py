import json
import unittest
from unittest.mock import patch

from experiments.graph_scale_lab import fixtures, stores


class FakeGraph(stores._BaseStore):
    name = "fake"

    def __init__(self, adjacency, roots=None):
        self.adjacency = adjacency
        self.roots = roots if roots is not None else set(adjacency)
        self.calls = []

    def _root_exists(self, scope, start):
        self.calls.append(("root", scope, start))
        return start in self.roots

    def _one_hop(self, scope, frontier, relation, reverse):
        self.calls.append(("hop", tuple(frontier), relation, reverse))
        return [target for node in frontier for target in self.adjacency.get((node, relation, reverse), ())]

    def _native(self, scope, depth, start, relation, reverse):
        return self._frontier(scope, {"depth": depth, "start": start, "relation": relation, "reverse": reverse})


class StoreContractTest(unittest.TestCase):
    def test_frontier_bfs_deduplicates_cycles_and_supports_reverse(self):
        graph = FakeGraph({
            (0, "STATIC", False): (1, 2), (1, "STATIC", False): (2,),
            (2, "STATIC", False): (0, 3), (3, "STATIC", False): (),
            (3, "STATIC", True): (2,), (2, "STATIC", True): (0, 1),
        }, roots={0, 3})
        self.assertEqual(([1, 2, 3], 4), graph.traverse("scope", {"start": 0, "depth": 12, "relation": "STATIC", "reverse": False}, "frontier"))
        self.assertEqual(([0, 1, 2], 4), graph.traverse("scope", {"start": 3, "depth": 12, "relation": "STATIC", "reverse": True}, "frontier"))
        self.assertEqual(([], 1), graph.traverse("scope", {"start": 9, "depth": 1, "relation": "STATIC"}, "frontier"))

    def test_question_validation_rejects_unsafe_query_parts(self):
        graph = FakeGraph({})
        for question in ({"start": -1, "depth": 1, "relation": "STATIC"}, {"start": 1, "depth": 13, "relation": "STATIC"}, {"start": 1, "depth": 1, "relation": "DROP"}, {"start": 1, "depth": 1, "relation": "STATIC", "reverse": 1}):
            with self.assertRaises(ValueError):
                graph.traverse("scope", question)
        with self.assertRaises(ValueError):
            graph.traverse("scope", {"start": 1, "depth": 1, "relation": "STATIC"}, "sql")

    def test_loader_validation_happens_before_database_write(self):
        meta = fixtures.metadata()
        scope = fixtures.scope_id(meta)
        store = object.__new__(stores.PostgresStore)
        store._execute = unittest.mock.Mock()
        with self.assertRaises(ValueError):
            store.load("wrong", meta, [(0, "m", "a")], [])
        with self.assertRaises(ValueError):
            store.load(scope, meta, [(0, "m", "a")], [(0, 1, "STATIC")])
        self.assertFalse(store._execute.called)

    def test_neo4j_classifies_only_exact_native_timeout_and_never_retries(self):
        responses = [
            (200, {"results": [], "errors": [{"code": "Neo.ClientError.Transaction.TransactionTimedOut", "message": "late"}]}),
        ]
        class Response(object):
            def __init__(self, status, body): self.status, self.body = status, body
            def read(self): return json.dumps(self.body).encode("utf-8")
        class Connection(object):
            calls = 0
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): Connection.calls += 1
            def getresponse(self): return Response(*responses.pop(0))
            def close(self): pass
        with patch("experiments.graph_scale_lab.stores.http.client.HTTPConnection", Connection):
            with self.assertRaises(stores.BudgetExceeded) as caught:
                stores.Neo4jStore()._cypher("RETURN 1")
        self.assertEqual("Neo.ClientError.Transaction.TransactionTimedOut", caught.exception.code)
        self.assertEqual(1, Connection.calls)

    def test_neo4j_preserves_non_timeout_server_error_code(self):
        class Response(object):
            status = 200
            def read(self): return b'{"results":[],"errors":[{"code":"Neo.ClientError.Statement.SyntaxError","message":"bad"}]}'
        class Connection(object):
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch("experiments.graph_scale_lab.stores.http.client.HTTPConnection", Connection):
            with self.assertRaises(stores.ServerError) as caught:
                stores.Neo4jStore()._cypher("bad")
        self.assertEqual("Neo.ClientError.Statement.SyntaxError", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
