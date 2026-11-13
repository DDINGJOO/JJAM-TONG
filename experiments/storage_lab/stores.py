"""Four real database adapters with an intentionally small common query contract."""
import base64
import http.client
import json
import urllib.parse

from .fixtures import FIELDS, NUMBERS, STRINGS, scope

MAX_ROWS = 100000


def batches(rows, size=500):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def quote(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


class HTTP:
    def __init__(self, port, auth=None):
        self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        self.auth = auth
        self.calls = 0

    def request(self, method, path, data=None, raw=None, content_type="application/json", allowed=(200, 201), parse_json=True):
        body = raw if raw is not None else (json.dumps(data) if data is not None else None)
        headers = {"Content-Type": content_type}
        if self.auth:
            headers["Authorization"] = "Basic " + base64.b64encode(self.auth.encode()).decode()
        self.calls += 1
        self.connection.request(method, path, body=body, headers=headers)
        response = self.connection.getresponse()
        payload = response.read().decode()
        if response.status not in allowed:
            raise RuntimeError("HTTP %d %s: %s" % (response.status, path, payload[:1200]))
        return json.loads(payload) if parse_json and payload.strip().startswith(("{", "[")) else payload

    def close(self):
        self.connection.close()


class Store:
    calls = 0

    def reachable(self, selected, start, depth, relation="STATIC", reverse=False):
        """Document/columnar fallback: bounded client-side BFS, one query per level."""
        if not 1 <= depth <= 8:
            raise ValueError("depth must be 1..8")
        seen, frontier = {start}, {start}
        for _ in range(depth):
            if not frontier:
                break
            edges = self.edges_from(selected, sorted(frontier), relation, reverse)
            frontier = {r["source"] if reverse else r["target"] for r in edges} - seen
            seen |= frontier
        return sorted(seen - {start})

    def events(self, selected, token=None, known_before=None):
        return sorted(r["id"] for r in self.select(selected, "event", token=token, known_before=known_before))

    def close(self):
        pass


class Postgres(Store):
    name = "postgres"

    def __init__(self):
        import psycopg
        from psycopg.rows import dict_row
        self.connection = psycopg.connect("host=127.0.0.1 port=29432 dbname=evidence_lab user=lab password=synthetic-local-only", autocommit=True, row_factory=dict_row)
        self.calls = 0

    def sql(self, query, params=None):
        self.calls += 1
        cursor = self.connection.execute(query, params)
        return cursor.fetchall() if cursor.description else []

    def reset(self):
        self.sql("DROP TABLE IF EXISTS evidence CASCADE")
        fields = [f + " TEXT NOT NULL" for f in STRINGS] + [f + " BIGINT NOT NULL" for f in NUMBERS]
        self.sql("CREATE TABLE evidence (" + ",".join(fields) + ", PRIMARY KEY(id))")
        self.sql("CREATE INDEX edge_forward ON evidence(tenant,build,analysis,kind,relation,source) WHERE deleted=0")
        self.sql("CREATE INDEX edge_reverse ON evidence(tenant,build,analysis,kind,relation,target) WHERE deleted=0")
        self.sql("CREATE INDEX event_scope ON evidence(tenant,build,analysis,kind,level,service) WHERE deleted=0")
        self.sql("CREATE INDEX event_text ON evidence USING GIN(to_tsvector('simple',message)) WHERE deleted=0")

    def put(self, rows):
        if not rows:
            return
        query = "INSERT INTO evidence (" + ",".join(FIELDS) + ") VALUES (" + ",".join(["%s"] * len(FIELDS)) + ") ON CONFLICT(id) DO UPDATE SET "
        query += ",".join(f + "=EXCLUDED." + f for f in FIELDS if f != "id")
        query += " WHERE evidence.seq <= EXCLUDED.seq"
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                self.calls += 1
                cursor.executemany(query, [tuple(r[f] for f in FIELDS) for r in rows])

    def select(self, selected, kind, token=None, known_before=None):
        tenant, build, analysis = scope(*selected)
        query = "SELECT * FROM evidence WHERE tenant=%s AND build=%s AND analysis=%s AND kind=%s AND deleted=0"
        params = [tenant, build, analysis, kind]
        if token is not None:
            query += " AND to_tsvector('simple',message) @@ plainto_tsquery('simple',%s)"
            params.append(token)
        if known_before is not None:
            query += " AND known<=%s"
            params.append(known_before)
        rows = self.sql(query + " LIMIT %d" % (MAX_ROWS + 1), params)
        if len(rows) > MAX_ROWS:
            raise RuntimeError("result budget exceeded")
        return rows

    def reachable(self, selected, start, depth, relation="STATIC", reverse=False):
        tenant, build, analysis = scope(*selected)
        if not 1 <= depth <= 8:
            raise ValueError("depth must be 1..8")
        source, target = ("target", "source") if reverse else ("source", "target")
        query = """WITH RECURSIVE walk(id,depth,path) AS (
          SELECT %s::text, 0, ARRAY[%s::text]
          UNION ALL SELECT e.TARGET,w.depth+1,w.path||e.TARGET FROM walk w
          JOIN evidence e ON e.SOURCE=w.id
          WHERE e.tenant=%s AND e.build=%s AND e.analysis=%s AND e.kind='edge'
          AND e.relation=%s AND e.deleted=0 AND w.depth<%s AND NOT e.TARGET=ANY(w.path))
          SELECT DISTINCT id FROM walk WHERE depth>0 AND id<>%s ORDER BY id"""
        query = query.replace("SOURCE", source).replace("TARGET", target)
        return [r["id"] for r in self.sql(query, (start, start, tenant, build, analysis, relation, depth, start))]

    def counts(self, selected):
        return {r["service"]: r["n"] for r in self.sql("SELECT service,count(*) AS n FROM evidence WHERE tenant=%s AND build=%s AND analysis=%s AND kind='event' AND level='ERROR' AND deleted=0 GROUP BY service", scope(*selected))}

    def flush(self):
        self.sql("ANALYZE evidence")

    def storage_bytes(self):
        return self.sql("SELECT pg_total_relation_size('evidence') AS n")[0]["n"]

    def purge_scope(self, selected):
        self.sql("DELETE FROM evidence WHERE tenant=%s AND build=%s AND analysis=%s", scope(*selected))

    def close(self):
        self.connection.close()


class Neo4j(Store):
    name = "neo4j"

    def __init__(self):
        self.http = HTTP(29474)

    @property
    def calls(self):
        return self.http.calls

    def cypher(self, query, params=None):
        result = self.http.request("POST", "/db/neo4j/tx/commit", {"statements": [{"statement": query, "parameters": params or {}}]})
        if result["errors"]:
            raise RuntimeError(str(result["errors"]))
        return [r["row"] for r in result["results"][0]["data"]]

    def reset(self):
        # A previous medium fixture exceeds the 256 MiB heap in one delete tx.
        while self.cypher("MATCH (n) WITH n LIMIT $limit DETACH DELETE n RETURN count(*)", {"limit": 1000})[0][0]:
            pass
        self.cypher("CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE")
        self.cypher("CREATE INDEX evidence_scope IF NOT EXISTS FOR (n:Evidence) ON (n.tenant,n.build,n.analysis,n.kind)")
        self.cypher("CREATE FULLTEXT INDEX event_text IF NOT EXISTS FOR (n:Event) ON EACH [n.message]")
        self.cypher("CALL db.awaitIndexes(60)")

    def put(self, rows):
        nodes = [r for r in rows if r["kind"] != "edge"]
        edges = [r for r in rows if r["kind"] == "edge"]
        for group in batches(nodes):
            self.cypher("UNWIND $rows AS row MERGE (n:Evidence {id:row.id}) FOREACH (_ IN CASE WHEN n.seq IS NULL OR n.seq<=row.seq THEN [1] ELSE [] END | SET n += row) FOREACH (_ IN CASE WHEN row.kind='node' THEN [1] ELSE [] END | SET n:Entity) FOREACH (_ IN CASE WHEN row.kind='event' THEN [1] ELSE [] END | SET n:Event)", {"rows": group})
        for group in batches(edges):
            result = self.cypher("UNWIND $rows AS row MATCH (a:Entity {id:row.source}),(b:Entity {id:row.target}) MERGE (a)-[r:LINK {id:row.id}]->(b) FOREACH (_ IN CASE WHEN r.seq IS NULL OR r.seq<=row.seq THEN [1] ELSE [] END | SET r += row) RETURN count(r)", {"rows": group})
            if result[0][0] != len(group):
                raise RuntimeError("missing graph endpoints: projection must retry after nodes arrive")

    def select(self, selected, kind, token=None, known_before=None):
        tenant, build, analysis = scope(*selected)
        params = dict(tenant=tenant, build=build, analysis=analysis, kind=kind)
        var = "r" if kind == "edge" else "n"
        query = "MATCH ()-[r:LINK]->()" if kind == "edge" else "MATCH (n:Evidence)"
        if token is not None:
            query = "CALL db.index.fulltext.queryNodes('event_text',$token) YIELD node AS n, score"
            params["token"] = token
        query += " WHERE " + " AND ".join(var + "." + f + "=$" + f for f in ("tenant", "build", "analysis", "kind"))
        query += " AND " + var + ".deleted=0"
        if known_before is not None:
            query += " AND " + var + ".known<=$known"
            params["known"] = known_before
        result = self.cypher(query + " RETURN properties(" + var + ") LIMIT %d" % (MAX_ROWS + 1), params)
        if len(result) > MAX_ROWS:
            raise RuntimeError("result budget exceeded")
        return [r[0] for r in result]

    def reachable(self, selected, start, depth, relation="STATIC", reverse=False):
        tenant, build, analysis = scope(*selected)
        if not 1 <= depth <= 8:
            raise ValueError("depth must be 1..8")
        path = "(s:Entity {id:$start})<-[rs:LINK*1..%d]-(t:Entity)" if reverse else "(s:Entity {id:$start})-[rs:LINK*1..%d]->(t:Entity)"
        query = "MATCH " + path % depth
        query += " WHERE s.deleted=0 AND t.deleted=0 AND t.id<>$start AND all(r IN rs WHERE r.tenant=$tenant AND r.build=$build AND r.analysis=$analysis AND r.relation=$relation AND r.deleted=0) RETURN DISTINCT t.id ORDER BY t.id"
        return [r[0] for r in self.cypher(query, dict(start=start, tenant=tenant, build=build, analysis=analysis, relation=relation))]

    def counts(self, selected):
        return {r[0]: r[1] for r in self.cypher("MATCH (n:Event) WHERE n.tenant=$tenant AND n.build=$build AND n.analysis=$analysis AND n.deleted=0 AND n.level='ERROR' RETURN n.service,count(*)", dict(zip(("tenant", "build", "analysis"), scope(*selected))))}

    def flush(self):
        self.cypher("CALL db.index.fulltext.awaitEventuallyConsistentIndexRefresh()")

    def storage_bytes(self):
        return None  # store-file size is measured separately with docker exec du

    def purge_scope(self, selected):
        self.cypher("MATCH (n:Evidence) WHERE n.tenant=$tenant AND n.build=$build AND n.analysis=$analysis DETACH DELETE n", dict(zip(("tenant", "build", "analysis"), scope(*selected))))

    def close(self):
        self.http.close()


class Elasticsearch(Store):
    name = "elasticsearch"
    index = "jjamtong-evidence-lab"

    def __init__(self):
        self.http = HTTP(29420)

    @property
    def calls(self):
        return self.http.calls

    def reset(self):
        self.http.request("DELETE", "/" + self.index, allowed=(200, 404))
        properties = {f: {"type": "keyword"} for f in STRINGS}
        properties.update({f: {"type": "long"} for f in NUMBERS})
        properties["message"] = {"type": "text", "analyzer": "whitespace"}
        self.http.request("PUT", "/" + self.index, {"settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"}, "mappings": {"dynamic": "strict", "properties": properties}})

    def put(self, rows):
        for group in batches(rows):
            lines = []
            for row in group:
                lines.extend((json.dumps({"index": {"_index": self.index, "_id": row["id"], "version": row["seq"], "version_type": "external_gte"}}), json.dumps(row)))
            result = self.http.request("POST", "/_bulk", raw="\n".join(lines) + "\n", content_type="application/x-ndjson")
            bad = [item for item in result["items"] if item["index"].get("error") and item["index"]["status"] != 409]
            if bad:
                raise RuntimeError(str(bad[:2]))
            for row, item in zip(group, result["items"]):
                if item["index"]["status"] == 409:
                    path = "/" + self.index + "/_doc/" + urllib.parse.quote(row["id"], safe="")
                    current = self.http.request("GET", path, allowed=(200, 404))
                    if not current.get("found") or current["_source"]["seq"] < row["seq"]:
                        raise RuntimeError("version conflict without newer retained evidence; rebuild into a fresh index")

    def filters(self, selected, kind):
        return [{"term": {f: v}} for f, v in zip(("tenant", "build", "analysis", "kind", "deleted"), scope(*selected) + (kind, 0))]

    def search(self, filters, size=MAX_ROWS, aggregations=None):
        data = {"query": {"bool": {"filter": filters}}, "size": min(size, 5000), "track_total_hits": True}
        if aggregations:
            data["aggs"] = aggregations
        if size == 0:
            return self.http.request("POST", "/" + self.index + "/_search", data)
        # search_after plus PIT keeps multi-page results tied to one snapshot.
        pit = self.http.request("POST", "/" + self.index + "/_pit?keep_alive=1m")["id"]
        rows = []
        try:
            data.update(pit={"id": pit, "keep_alive": "1m"}, sort=["_shard_doc"])
            while True:
                result = self.http.request("POST", "/_search", data)
                pit = result.get("pit_id", pit)
                if result.get("timed_out") or result["_shards"]["failed"]:
                    raise RuntimeError("partial Elasticsearch result")
                hits = result["hits"]["hits"]
                rows.extend(hit["_source"] for hit in hits)
                if len(rows) > MAX_ROWS:
                    raise RuntimeError("result budget exceeded")
                if not hits or len(rows) >= result["hits"]["total"]["value"]:
                    return rows
                data["search_after"] = hits[-1]["sort"]
        finally:
            self.http.request("DELETE", "/_pit", {"id": pit})

    def select(self, selected, kind, token=None, known_before=None):
        filters = self.filters(selected, kind)
        if token is not None:
            filters.append({"match": {"message": token}})
        if known_before is not None:
            filters.append({"range": {"known": {"lte": known_before}}})
        return self.search(filters)

    def edges_from(self, selected, frontier, relation, reverse=False):
        return self.search(self.filters(selected, "edge") + [{"term": {"relation": relation}}, {"terms": {"target" if reverse else "source": frontier}}])

    def counts(self, selected):
        result = self.search(self.filters(selected, "event") + [{"term": {"level": "ERROR"}}], 0, {"services": {"terms": {"field": "service", "size": 100}}})
        agg = result["aggregations"]["services"]
        if agg["sum_other_doc_count"] or result.get("timed_out") or result["_shards"]["failed"]:
            raise RuntimeError("partial Elasticsearch aggregation")
        return {b["key"]: b["doc_count"] for b in agg["buckets"]}

    def flush(self):
        self.http.request("POST", "/" + self.index + "/_refresh")

    def storage_bytes(self):
        return self.http.request("GET", "/" + self.index + "/_stats/store")["_all"]["primaries"]["store"]["size_in_bytes"]

    def purge_scope(self, selected):
        filters = [{"term": {f: v}} for f, v in zip(("tenant", "build", "analysis"), scope(*selected))]
        result = self.http.request("POST", "/" + self.index + "/_delete_by_query?refresh=true", {"query": {"bool": {"filter": filters}}})
        if result.get("failures"):
            raise RuntimeError(str(result["failures"]))

    def close(self):
        self.http.close()


class ClickHouse(Store):
    name = "clickhouse"

    def __init__(self):
        self.http = HTTP(29423, "lab:synthetic-local-only")

    @property
    def calls(self):
        return self.http.calls

    def sql(self, query, raw=None):
        path = "/?" + urllib.parse.urlencode({"database": "evidence_lab", "query": query, "max_execution_time": 30})
        result = self.http.request("POST", path, raw=raw, content_type="text/plain", parse_json=False)
        return [json.loads(line) for line in result.splitlines() if line.strip()] if isinstance(result, str) else [result]

    def reset(self):
        self.sql("DROP TABLE IF EXISTS evidence")
        fields = [f + " String" for f in STRINGS] + [f + " UInt64" for f in NUMBERS]
        self.sql("CREATE TABLE evidence (" + ",".join(fields) + ") ENGINE=ReplacingMergeTree(seq) ORDER BY (tenant,build,analysis,kind,id)")

    def put(self, rows):
        for group in batches(rows, 5000):
            self.sql("INSERT INTO evidence FORMAT JSONEachRow", "\n".join(json.dumps(row) for row in group) + "\n")

    def where(self, selected, kind):
        return " AND ".join(f + "=" + quote(v) for f, v in zip(("tenant", "build", "analysis", "kind"), scope(*selected) + (kind,))) + " AND deleted=0"

    def select(self, selected, kind, token=None, known_before=None):
        query = "SELECT * FROM evidence FINAL WHERE " + self.where(selected, kind)
        if token is not None:
            query += " AND hasToken(message," + quote(token) + ")"
        if known_before is not None:
            query += " AND known<=" + str(int(known_before))
        rows = self.sql(query + " LIMIT %d FORMAT JSONEachRow" % (MAX_ROWS + 1))
        if len(rows) > MAX_ROWS:
            raise RuntimeError("result budget exceeded")
        return [{f: int(r[f]) if f in NUMBERS else r[f] for f in FIELDS} for r in rows]

    def edges_from(self, selected, frontier, relation, reverse=False):
        query = "SELECT source,target FROM evidence FINAL WHERE " + self.where(selected, "edge")
        query += " AND relation=" + quote(relation) + " AND " + ("target" if reverse else "source") + " IN (" + ",".join(quote(x) for x in frontier) + ") FORMAT JSONEachRow"
        return self.sql(query)

    def counts(self, selected):
        return {r["service"]: int(r["n"]) for r in self.sql("SELECT service,count() AS n FROM evidence FINAL WHERE " + self.where(selected, "event") + " AND level='ERROR' GROUP BY service FORMAT JSONEachRow")}

    def flush(self):
        pass  # synchronous inserts; FINAL is required for version/dedup correctness

    def storage_bytes(self):
        return int(self.sql("SELECT sum(bytes_on_disk) AS n FROM system.parts WHERE database='evidence_lab' AND table='evidence' AND active FORMAT JSONEachRow")[0]["n"])

    def purge_scope(self, selected):
        condition = " AND ".join(f + "=" + quote(v) for f, v in zip(("tenant", "build", "analysis"), scope(*selected)))
        self.sql("ALTER TABLE evidence DELETE WHERE " + condition + " SETTINGS mutations_sync=2")

    def close(self):
        self.http.close()


STORES = {cls.name: cls for cls in (Postgres, Neo4j, Elasticsearch, ClickHouse)}
