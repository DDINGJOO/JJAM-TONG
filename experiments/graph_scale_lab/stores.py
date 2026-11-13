"""Small PostgreSQL and Neo4j adapters for the synthetic graph-scale lab.

Each loaded scope is immutable.  A failed multi-batch load can leave partial
data behind, so it is deliberately not query-ready and must be cleared before
the case is retried.
"""
import base64
import http.client
import json
import time

from .fixtures import scope_id


RELATIONS = frozenset(("STATIC", "OBSERVED"))
POSTGRES_DSN = "host=127.0.0.1 port=29532 dbname=graphlab user=graphlab password=synthetic-local-only"
NEO4J_HOST = "127.0.0.1"
NEO4J_PORT = 29574
NEO4J_AUTH = "neo4j:synthetic-local-only"
REQUEST_TIMEOUT = 45
NATIVE_BUDGET_SECONDS = 10
NEO4J_TIMEOUT_CODES = frozenset((
    "Neo.ClientError.Transaction.TransactionTimedOut",
    "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
))
_BATCH_SIZE = 1000
_MAX_FRONTIER = 1000000


class ServerError(RuntimeError):
    """A database-reported failure, retaining the server code and payload."""

    def __init__(self, code, payload):
        self.code = code
        self.payload = payload
        RuntimeError.__init__(self, "%s: %s" % (code, payload))


class BudgetExceeded(ServerError):
    """Only a native database timeout or the explicit frontier deadline."""


def _batches(rows, size=_BATCH_SIZE):
    for offset in range(0, len(rows), size):
        yield rows[offset:offset + size]


def _required_scope(scope):
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("scope must be a non-blank string")
    return scope


def _question(question):
    if not isinstance(question, dict):
        raise ValueError("question must be a dictionary")
    depth = question.get("depth")
    start = question.get("start")
    relation = question.get("relation")
    reverse = question.get("reverse", False)
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= 12:
        raise ValueError("depth must be an integer from 1 to 12")
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        raise ValueError("start must be a non-negative integer")
    if relation not in RELATIONS:
        raise ValueError("relation must be STATIC or OBSERVED")
    if not isinstance(reverse, bool):
        raise ValueError("reverse must be a boolean")
    return depth, start, relation, reverse


def _load_rows(scope, meta, node_rows, edge_rows):
    _required_scope(scope)
    if scope != scope_id(meta):
        raise ValueError("scope must equal scope_id(meta)")
    nodes = list(node_rows)
    edges = list(edge_rows)
    node_ids = set()
    for row in nodes:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise ValueError("node rows must be (idx, module, logical)")
        idx, module, logical = row
        if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
            raise ValueError("node idx must be a non-negative integer")
        if not isinstance(module, str) or not module or not isinstance(logical, str) or not logical:
            raise ValueError("node module and logical must be non-blank strings")
        if idx in node_ids:
            raise ValueError("duplicate node idx")
        node_ids.add(idx)
    for row in edges:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise ValueError("edge rows must be (source, target, relation)")
        source, target, relation = row
        if source not in node_ids or target not in node_ids:
            raise ValueError("edge endpoint is absent from node rows")
        if relation not in RELATIONS:
            raise ValueError("edge relation must be STATIC or OBSERVED")
    return nodes, edges


class _BaseStore(object):
    name = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def _frontier(self, scope, question):
        depth, start, relation, reverse = _question(question)
        deadline = time.monotonic() + NATIVE_BUDGET_SECONDS
        if not self._root_exists(scope, start):
            return [], 1
        if time.monotonic() >= deadline:
            raise BudgetExceeded("application.deadline", {"stage": "after-root-query"})
        seen = set((start,))
        frontier = set((start,))
        round_trips = 1
        for unused_level in range(depth):
            if not frontier:
                break
            if time.monotonic() >= deadline:
                raise BudgetExceeded("application.deadline", {"stage": "before-query"})
            destinations = self._one_hop(scope, sorted(frontier), relation, reverse)
            round_trips += 1
            if time.monotonic() >= deadline:
                raise BudgetExceeded("application.deadline", {"stage": "after-query"})
            frontier = set(destinations).difference(seen)
            if len(frontier) > _MAX_FRONTIER:
                raise RuntimeError("frontier exceeds bounded query result")
            seen.update(frontier)
        return sorted(seen.difference((start,))), round_trips

    def traverse(self, scope, question, mode="native"):
        _required_scope(scope)
        depth, start, relation, reverse = _question(question)
        if mode not in ("native", "frontier"):
            raise ValueError("mode must be native or frontier")
        if mode == "frontier":
            return self._frontier(scope, question)
        return self._native(scope, depth, start, relation, reverse)


class PostgresStore(_BaseStore):
    name = "postgres"

    def __init__(self):
        import psycopg
        self.kind = self.name
        self.connection = psycopg.connect(POSTGRES_DSN, autocommit=True)
        self._execute("SET statement_timeout = 10000")

    def _execute(self, query, params=None):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall() if cursor.description else []
        except Exception as error:
            if getattr(error, "sqlstate", None) == "57014":
                raise BudgetExceeded("57014", {"message": str(error)}) from error
            raise

    def reset_schema(self):
        self._execute("DROP TABLE IF EXISTS calls CASCADE")
        self._execute("DROP TABLE IF EXISTS methods CASCADE")
        self._execute("DROP TABLE IF EXISTS scopes CASCADE")
        self._execute("CREATE TABLE scopes (scope text PRIMARY KEY, metadata jsonb NOT NULL)")
        self._execute("CREATE TABLE methods (scope text NOT NULL REFERENCES scopes(scope), idx integer NOT NULL, module text NOT NULL, logical text NOT NULL, PRIMARY KEY (scope, idx))")
        self._execute("CREATE TABLE calls (scope text NOT NULL, source integer NOT NULL, target integer NOT NULL, relation text NOT NULL CHECK (relation IN ('STATIC','OBSERVED')), PRIMARY KEY (scope, source, target, relation), FOREIGN KEY (scope, source) REFERENCES methods(scope, idx), FOREIGN KEY (scope, target) REFERENCES methods(scope, idx))")
        self._execute("CREATE INDEX calls_forward ON calls(scope, relation, source, target)")
        self._execute("CREATE INDEX calls_reverse ON calls(scope, relation, target, source)")

    def clear_data(self):
        self._execute("TRUNCATE calls, methods, scopes")

    def load(self, scope, meta, node_rows, edge_rows):
        nodes, edges = _load_rows(scope, meta, node_rows, edge_rows)
        if self._execute("SELECT 1 FROM scopes WHERE scope=%s", (scope,)):
            raise ValueError("scope already exists and is immutable")
        try:
            with self.connection.transaction():
                with self.connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = 0")
                    cursor.execute("INSERT INTO scopes(scope, metadata) VALUES (%s, %s::jsonb)", (scope, json.dumps(meta, sort_keys=True)))
                    with cursor.copy("COPY methods (scope, idx, module, logical) FROM STDIN") as copy:
                        for idx, module, logical in nodes:
                            copy.write_row((scope, idx, module, logical))
                    with cursor.copy("COPY calls (scope, source, target, relation) FROM STDIN") as copy:
                        for source, target, relation in edges:
                            copy.write_row((scope, source, target, relation))
        except Exception as error:
            if getattr(error, "sqlstate", None) == "57014":
                raise BudgetExceeded("57014", {"message": str(error)}) from error
            raise

    def counts(self, scope):
        _required_scope(scope)
        rows = self._execute("SELECT (SELECT count(*) FROM methods WHERE scope=%s), (SELECT count(*) FROM calls WHERE scope=%s)", (scope, scope))
        return {"nodes": int(rows[0][0]), "edges": int(rows[0][1])}

    def _root_exists(self, scope, start):
        return bool(self._execute("SELECT 1 FROM methods WHERE scope=%s AND idx=%s", (scope, start)))

    def _one_hop(self, scope, frontier, relation, reverse):
        source, target = ("target", "source") if reverse else ("source", "target")
        rows = self._execute("SELECT DISTINCT %s FROM calls WHERE scope=%%s AND relation=%%s AND %s = ANY(%%s)" % (target, source), (scope, relation, frontier))
        return [row[0] for row in rows]

    def _native_query(self, reverse):
        source, target = ("target", "source") if reverse else ("source", "target")
        return """WITH RECURSIVE walk(depth, idx) AS (
            SELECT 0, idx FROM methods WHERE scope=%s AND idx=%s
            UNION
            SELECT walk.depth + 1, calls.%s
            FROM walk JOIN calls ON calls.scope=%s AND calls.relation=%s AND calls.%s=walk.idx
            WHERE walk.depth < %s
        ) SELECT DISTINCT idx FROM walk WHERE depth > 0 AND idx <> %s ORDER BY idx""" % ("%s", "%s", target, "%s", "%s", source, "%s", "%s")

    def _native(self, scope, depth, start, relation, reverse):
        rows = self._execute(self._native_query(reverse), (scope, start, scope, relation, depth, start))
        return [row[0] for row in rows], 1

    def explain(self, scope, question):
        _required_scope(scope)
        depth, start, relation, reverse = _question(question)
        query = self._native_query(reverse)
        rows = self._execute("EXPLAIN (FORMAT JSON) " + query, (scope, start, scope, relation, depth, start))
        return {"store": self.name, "query": query, "plan": rows[0][0] if rows else None}

    def prepare_read(self):
        self._execute("ANALYZE methods")
        self._execute("ANALYZE calls")

    def size_bytes(self):
        return int(self._execute("SELECT pg_database_size(current_database())")[0][0])

    def close(self):
        self.connection.close()


class Neo4jStore(_BaseStore):
    name = "neo4j"

    def __init__(self):
        self.kind = self.name
        self.closed = False

    def _cypher(self, statement, parameters=None, include_stats=False):
        connection = http.client.HTTPConnection(NEO4J_HOST, NEO4J_PORT, timeout=REQUEST_TIMEOUT)
        payload = {"statements": [{"statement": statement, "parameters": parameters or {}, "includeStats": include_stats, "resultDataContents": ["row"]}]}
        headers = {"Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(NEO4J_AUTH.encode("utf-8")).decode("ascii")}
        try:
            connection.request("POST", "/db/neo4j/tx/commit", json.dumps(payload), headers)
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
        finally:
            connection.close()
        try:
            result = json.loads(raw)
        except ValueError:
            raise RuntimeError("Neo4j HTTP %s: %s" % (response.status, raw[:1200]))
        errors = result.get("errors", [])
        if errors:
            error = errors[0]
            code = error.get("code", "Neo4j.Unknown")
            if code in NEO4J_TIMEOUT_CODES:
                raise BudgetExceeded(code, error)
            raise ServerError(code, error)
        if response.status not in (200, 201):
            raise RuntimeError("Neo4j HTTP %s: %s" % (response.status, result))
        return result

    @staticmethod
    def _rows(result):
        results = result.get("results", [])
        return [item["row"] for item in results[0].get("data", [])] if results else []

    def reset_schema(self):
        while self._rows(self._cypher("MATCH (n) WITH n LIMIT 1000 DETACH DELETE n RETURN count(n)"))[0][0]:
            pass
        self._cypher("CREATE CONSTRAINT analysis_scope IF NOT EXISTS FOR (a:Analysis) REQUIRE a.scope IS UNIQUE")
        self._cypher("CREATE CONSTRAINT method_scope_idx IF NOT EXISTS FOR (m:Method) REQUIRE (m.scope, m.idx) IS UNIQUE")

    def clear_data(self):
        while self._rows(self._cypher("MATCH (n) WITH n LIMIT 1000 DETACH DELETE n RETURN count(n)"))[0][0]:
            pass

    def load(self, scope, meta, node_rows, edge_rows):
        nodes, edges = _load_rows(scope, meta, node_rows, edge_rows)
        if self._rows(self._cypher("MATCH (a:Analysis {scope:$scope}) RETURN a.scope", {"scope": scope})):
            raise ValueError("scope already exists and is immutable")
        self._cypher("CREATE (:Analysis {scope:$scope, metadata:$metadata})", {"scope": scope, "metadata": json.dumps(meta, sort_keys=True)})
        for batch in _batches(nodes):
            self._cypher("UNWIND $rows AS row CREATE (:Method {scope:$scope, idx:row[0], module:row[1], logical:row[2]})", {"scope": scope, "rows": batch})
        for relation in RELATIONS:
            relation_edges = [[source, target] for source, target, edge_relation in edges if edge_relation == relation]
            for batch in _batches(relation_edges):
                self._cypher("UNWIND $rows AS row MATCH (a:Method {scope:$scope, idx:row[0]}), (b:Method {scope:$scope, idx:row[1]}) CREATE (a)-[:%s]->(b)" % relation, {"scope": scope, "rows": batch})

    def counts(self, scope):
        _required_scope(scope)
        nodes = self._rows(self._cypher("MATCH (m:Method {scope:$scope}) RETURN count(m)", {"scope": scope}))[0][0]
        edges = self._rows(self._cypher("MATCH (:Method {scope:$scope})-[r]->(:Method {scope:$scope}) RETURN count(r)", {"scope": scope}))[0][0]
        return {"nodes": int(nodes), "edges": int(edges)}

    def _root_exists(self, scope, start):
        return bool(self._rows(self._cypher("MATCH (m:Method {scope:$scope, idx:$start}) RETURN 1", {"scope": scope, "start": start})))

    def _one_hop(self, scope, frontier, relation, reverse):
        arrow = "<-[r:%s]-" % relation if reverse else "-[r:%s]->" % relation
        statement = "UNWIND $frontier AS idx MATCH (m:Method {scope:$scope, idx:idx})%s(n:Method {scope:$scope}) RETURN DISTINCT n.idx" % arrow
        return [row[0] for row in self._rows(self._cypher(statement, {"scope": scope, "frontier": frontier}))]

    def _native_query(self, depth, relation, reverse):
        arrow = "<-[:%s*1..%d]-" % (relation, depth) if reverse else "-[:%s*1..%d]->" % (relation, depth)
        return "MATCH (root:Method {scope:$scope, idx:$start})%s(endpoint:Method) WITH DISTINCT endpoint RETURN endpoint.idx ORDER BY endpoint.idx" % arrow

    def _native(self, scope, depth, start, relation, reverse):
        statement = self._native_query(depth, relation, reverse)
        rows = self._rows(self._cypher(statement, {"scope": scope, "start": start}))
        return [row[0] for row in rows if row[0] != start], 1

    def explain(self, scope, question):
        _required_scope(scope)
        depth, start, relation, reverse = _question(question)
        query = "EXPLAIN " + self._native_query(depth, relation, reverse)
        result = self._cypher(query, {"scope": scope, "start": start}, include_stats=True)
        return {"store": self.name, "query": query, "plan": result.get("results", [{}])[0].get("plan"), "response": result}

    def size_bytes(self):
        return None

    def prepare_read(self):
        self._cypher("CALL db.awaitIndexes(60)")

    def close(self):
        self.closed = True


class Store(object):
    """Create an independent adapter instance for the requested lab store."""

    def __new__(cls, kind):
        if kind == "postgres":
            return PostgresStore()
        if kind == "neo4j":
            return Neo4jStore()
        raise ValueError("kind must be postgres or neo4j")
