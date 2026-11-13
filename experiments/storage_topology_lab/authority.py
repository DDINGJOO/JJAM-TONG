"""Native immutable journals. No engine depends on a PostgreSQL coordinator."""
import hashlib
import json
import urllib.parse
from psycopg import Error as PostgresError

from experiments.storage_lab.stores import quote

IDENTITY = ("tenant", "repo", "commit", "build", "artifact", "module", "analysis")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Conflict(RuntimeError):
    pass


class Journal:
    """One native table/index/label, isolated from replaceable evidence models."""
    index = "jjamtong-topology-authority"

    def __init__(self, store):
        self.store = store
        self.name = store.name

    def reset(self):
        s = self.store
        if self.name == "postgres":
            s.sql("DROP TABLE IF EXISTS topology_authority")
            s.sql("CREATE TABLE topology_authority (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        elif self.name == "neo4j":
            s.cypher("MATCH (n:TopologyAuthority) DETACH DELETE n")
            s.cypher("CREATE CONSTRAINT topology_authority_id IF NOT EXISTS FOR (n:TopologyAuthority) REQUIRE n.id IS UNIQUE")
        elif self.name == "elasticsearch":
            s.http.request("DELETE", "/" + self.index, allowed=(200, 404))
            s.http.request("PUT", "/" + self.index, {"settings": {"number_of_shards": 1, "number_of_replicas": 0}, "mappings": {"dynamic": "strict", "properties": {"payload": {"type": "keyword", "index": False, "doc_values": False}}}})
        else:
            s.sql("DROP TABLE IF EXISTS topology_authority")
            s.sql("CREATE TABLE topology_authority (id String, payload String) ENGINE=MergeTree ORDER BY id")

    def get(self, identity):
        s = self.store
        if self.name == "postgres":
            values = [r["payload"] for r in s.sql("SELECT payload FROM topology_authority WHERE id=%s", (identity,))]
        elif self.name == "neo4j":
            values = [r[0] for r in s.cypher("MATCH (n:TopologyAuthority {id:$id}) RETURN n.payload", {"id": identity})]
        elif self.name == "elasticsearch":
            result = s.http.request("GET", "/%s/_doc/%s" % (self.index, urllib.parse.quote(identity, safe="")), allowed=(200, 404))
            values = [result["_source"]["payload"]] if result.get("found") else []
        else:
            values = [r["payload"] for r in s.sql("SELECT DISTINCT payload FROM topology_authority WHERE id=" + quote(identity) + " LIMIT 2 FORMAT JSONEachRow")]
        if len(set(values)) > 1:
            raise Conflict("conflicting immutable journal identity: " + identity)
        return json.loads(values[0]) if values else None

    def append_clickhouse(self, identity, value):
        """Deliberately unconditional; used to expose the missing uniqueness gate."""
        self.store.sql("INSERT INTO topology_authority FORMAT JSONEachRow", canonical({"id": identity, "payload": canonical(value)}) + "\n")

    def claim(self, identity, value):
        """Native create-only for three engines; single-publisher CH protocol only."""
        s, payload = self.store, canonical(value)
        if self.name == "postgres":
            s.sql("INSERT INTO topology_authority(id,payload) VALUES (%s,%s) ON CONFLICT(id) DO NOTHING", (identity, payload))
        elif self.name == "neo4j":
            s.cypher("MERGE (n:TopologyAuthority {id:$id}) ON CREATE SET n.payload=$payload RETURN n.payload", {"id": identity, "payload": payload})
        elif self.name == "elasticsearch":
            result = s.http.request("PUT", "/%s/_create/%s" % (self.index, urllib.parse.quote(identity, safe="")), {"payload": payload}, allowed=(201, 409))
            if result.get("error") and result.get("status") != 409:
                raise RuntimeError(str(result))
        else:
            # This read/insert is explicitly NOT atomic. The capability probe
            # records UNSUPPORTED; a Python mutex would conceal the limitation.
            previous = self.get(identity)
            if previous is None:
                self.append_clickhouse(identity, value)
        if self.get(identity) != value:
            raise Conflict("immutable identity already holds different content: " + identity)


def manifest_for(rows):
    ordered = sorted(rows, key=lambda r: r["id"])
    if not ordered or len({r["id"] for r in ordered}) != len(ordered):
        raise ValueError("nonempty snapshot with unique evidence IDs required")
    identities = sorted({tuple(r[f] for f in IDENTITY) for r in ordered})
    if any(not all(identity) for identity in identities):
        raise ValueError("complete immutable evidence identity required")
    chunks = [ordered[i:i + 100] for i in range(0, len(ordered), 100)]
    manifest = {"schema": 1, "rows": len(ordered), "sha256": digest(ordered),
                "identities": [list(i) for i in identities], "chunks": [digest(c) for c in chunks]}
    return manifest, chunks


def stage(journal, rows):
    manifest, chunks = manifest_for(rows)
    for chunk_id, chunk in zip(manifest["chunks"], chunks):
        journal.claim("chunk:" + chunk_id, chunk)
    return manifest


def load(journal, catalog):
    manifest = journal.get("catalog:" + catalog)
    if manifest is None:
        return None
    rows = []
    for chunk_id in manifest["chunks"]:
        chunk = journal.get("chunk:" + chunk_id)
        if chunk is None or digest(chunk) != chunk_id:
            raise Conflict("missing or corrupt content-addressed chunk")
        rows.extend(chunk)
    actual, _ = manifest_for(rows)
    if actual != manifest:
        raise Conflict("manifest does not describe retained evidence")
    return rows


def publish(journal, catalog, rows):
    manifest = stage(journal, rows)
    journal.claim("catalog:" + catalog, manifest)
    if load(journal, catalog) != sorted(rows, key=lambda r: r["id"]):
        raise Conflict("published snapshot failed read-back verification")


def projection_rows(store, rows):
    selected = sorted({(r["tenant"], r["build"], r["analysis"]) for r in rows})
    kinds = sorted({r["kind"] for r in rows})
    return sorted((r for s in selected for k in kinds for r in store.select(s, k)), key=lambda r: r["id"])


def view(journal, store, catalog):
    """Fresh authority validation is required; no cached-complete fallback."""
    try:
        rows = load(journal, catalog)
        if rows is None:
            return "missing"
        expected = sorted((r for r in rows if not r["deleted"]), key=lambda r: r["id"])
        return "ready" if projection_rows(store, rows) == expected else "partial"
    except Conflict:
        return "conflict"
    except (OSError, RuntimeError, PostgresError):
        return "unavailable"
