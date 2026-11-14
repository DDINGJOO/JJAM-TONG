"""Read-only application queries; no app execution, publication or latest fallback."""
from dataclasses import asdict
import re

from tools.evidence_store.contracts import (ANALYZERS, EvidenceReader, GraphRequest,
                                            SnapshotRef, VersionMismatch, identifier, prepare)
from tools.evidence_store.postgres import PREFIX
from tools.method_evidence.evidence import HEX64, build_identity, valid_id

LIMITS = {"nodes": 200, "edges": 500, "depth": 12}


class MissingHistory(LookupError):
    pass


def bounded_int(value, default, ceiling, minimum=1):
    if value is None:
        return default
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}", value):
        raise ValueError("Invalid bounded integer")
    parsed = int(value)
    if not minimum <= parsed <= ceiling:
        raise ValueError("Query budget out of range")
    return parsed


def page(params, default=50, ceiling=100):
    return (bounded_int(params.get("limit"), default, ceiling),
            bounded_int(params.get("offset"), 0, 10000, minimum=0))


def metadata(ref, identity, schema, config, coverage):
    """Explicit response projection; never return the stored source document."""
    if schema != "jjamtong.method-index.v1" or not isinstance(config, str) or not HEX64.fullmatch(config):
        raise VersionMismatch("Stored metadata does not match the evidence contract")
    projected = {}
    for analyzer in sorted(ANALYZERS):
        source = coverage[analyzer]
        numbers = ("inventoryMethods", "inputCalls", "indexedCalls", "danglingCalls", "unresolved", "excluded")
        if any(type(source[key]) is not int or source[key] < 0 for key in numbers):
            raise VersionMismatch("Invalid analyzer coverage")
        if not isinstance(source["analyzerVersion"], str):
            raise VersionMismatch("Invalid analyzer version")
        projected[analyzer] = {key: source[key] for key in (*numbers, "analyzerVersion")}
    return {"ref": asdict(ref), "buildIdentity": build_identity(identity), "schema": schema,
            "analysisConfigSha256": config, "coverage": projected}


class PostgresCatalog:
    """Bounded discovery within the one configured local tenant, sorted by run ID."""

    def __init__(self, store):
        self.store = store

    def snapshots(self, tenant, limit, offset):
        with self.store._connect() as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            rows = conn.execute(
                "SELECT run_id,index_sha256,projection_sha256,document->'buildIdentity',"
                "document->>'schema',document->>'configSha256',coverage FROM " + PREFIX +
                "analysis WHERE tenant_id=%s ORDER BY run_id DESC LIMIT %s OFFSET %s",
                (tenant, limit + 1, offset)).fetchall()
        result = []
        for run, index_sha, projection_sha, identity, schema, config, coverage in rows[:limit]:
            ref = SnapshotRef(tenant, run, index_sha)
            if index_sha != projection_sha:
                raise VersionMismatch("Catalog projection differs from source")
            result.append(metadata(ref, identity, schema, config, coverage))
        return {"snapshots": result, "hasMore": len(rows) > limit, "offset": offset,
                "limit": limit, "order": "run-id-desc"}


class EvidenceWorkspace:
    def __init__(self, store, tenant, catalog=None, collection=None, telemetry_config=None):
        self.store, self.tenant = store, identifier(tenant)
        self.catalog = catalog if catalog is not None else PostgresCatalog(store)
        self.reader = EvidenceReader(store, store)
        if collection is not None and (not isinstance(telemetry_config, str) or
                                       not HEX64.fullmatch(telemetry_config)):
            raise ValueError("Explicit telemetry configuration required for a trace capture")
        self.collection, self.telemetry_config = collection, telemetry_config

    def context(self, params):
        self._only(params, set())
        return {"tenant": self.tenant, "mode": "local-read-only", "limits": LIMITS,
                "traceSource": "startup-file-capture" if self.collection is not None else "not-configured",
                "traceCollectionReasons": self.collection["collectionReasons"] if self.collection else []}

    @staticmethod
    def _only(params, allowed):
        if set(params) - allowed:
            raise ValueError("Unknown query fields")

    def _ref(self, params):
        return SnapshotRef(self.tenant, params["run_id"], params["index_sha256"])

    def _index(self, ref):
        index = self.store.load(ref)
        if index is None:
            raise MissingHistory("History not collected")
        return index

    @staticmethod
    def _analyzer(params):
        analyzer = params["analyzer"]
        if analyzer not in ANALYZERS:
            raise ValueError("Explicit supported analyzer required")
        return analyzer

    def snapshots(self, params):
        self._only(params, {"limit", "offset"})
        return self.catalog.snapshots(self.tenant, *page(params))

    def snapshot(self, params):
        self._only(params, {"run_id", "index_sha256"})
        ref = self._ref(params)
        index = self._index(ref)
        derived = prepare(index)
        result = metadata(ref, index["buildIdentity"], index["schema"], index["configSha256"],
                          {key: value["coverage"] for key, value in derived.items()})
        # Stored diagnostic prose is not a browser-facing contract: it may have
        # been supplied by an importer. Project controlled explanations only.
        result.update(limitations=["정적 호출 후보는 실제 실행의 증거가 아닙니다.",
                                   "분석기 전체의 미해결·제외 집계는 선택한 경로의 집계와 다릅니다."],
                      sourceLimitationCount=len(index["limitations"]),
                      identityAssurance="저장된 분석 해시를 대조했습니다. 빌드의 출처를 인증한 결과는 아닙니다.")
        return result

    def methods(self, params):
        self._only(params, {"run_id", "index_sha256", "analyzer", "q", "limit", "offset"})
        ref, analyzer = self._ref(params), self._analyzer(params)
        limit, offset = page(params, default=80, ceiling=200)
        query = params.get("q", "")
        if len(query) > 200:
            raise ValueError("Search query too long")
        index = self._index(ref)
        symbols = sorted({tuple(item[key] for key in ("module", "class", "name", "descriptor"))
                          for item in index["staticEvidence"][analyzer]["methods"]})
        selected = [key for key in symbols if query.casefold() in " ".join(key).casefold()]
        return {"methods": selected[offset:offset + limit], "total": len(selected),
                "hasMore": len(selected) > offset + limit, "offset": offset, "limit": limit,
                "ref": asdict(ref), "analyzer": analyzer}

    def graph(self, params):
        self._only(params, {"run_id", "index_sha256", "analyzer", "module", "class", "name",
                            "descriptor", "depth", "nodes", "edges"})
        request = GraphRequest(self._ref(params), self._analyzer(params),
                               tuple(params[key] for key in ("module", "class", "name", "descriptor")),
                               bounded_int(params.get("depth"), 4, LIMITS["depth"]),
                               bounded_int(params.get("nodes"), 80, LIMITS["nodes"]),
                               bounded_int(params.get("edges"), 200, LIMITS["edges"]))
        return asdict(self.reader.graph(request))

    def traces(self, params):
        self._only(params, {"limit", "offset"})
        limit, offset = page(params)
        counts = {}
        for item in self.collection["spans"] if self.collection else []:
            trace = item["traceId"]
            counts[trace] = counts.get(trace, 0) + 1
        ids = sorted(counts)
        return {"traces": [{"traceId": value, "spanRecords": counts[value]}
                           for value in ids[offset:offset + limit]],
                "hasMore": len(ids) > offset + limit, "offset": offset, "limit": limit,
                "source": "startup-file-capture" if self.collection is not None else "not-configured",
                "collectionReasons": self.collection["collectionReasons"] if self.collection else []}

    def trace(self, params):
        self._only(params, {"run_id", "index_sha256", "trace_id"})
        ref, trace_id = self._ref(params), params["trace_id"]
        if not valid_id(trace_id, 32):
            raise ValueError("Invalid trace ID")
        if self.collection is None:
            return {"status": "UNRESOLVED", "reason": "TRACE_CAPTURE_NOT_CONFIGURED", "traceId": trace_id}
        result = self.reader.trace(ref, self.collection, trace_id, self.telemetry_config)
        # Preserve nanosecond precision across JSON/JavaScript without exposing raw payloads.
        result = dict(result)
        if "spans" in result:
            result["spans"] = [dict(span) for span in result["spans"]]
            invalid_time = False
            for span in result["spans"]:
                for field in ("startTimeUnixNano", "endTimeUnixNano"):
                    value = span.get(field)
                    span[field] = str(value) if (type(value) is int and 0 <= value < 2**64) or (
                        isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value)
                        and int(value) < 2**64) else None
                start, end = span["startTimeUnixNano"], span["endTimeUnixNano"]
                if start is None or end is None or int(end) < int(start):
                    span["startTimeUnixNano"] = span["endTimeUnixNano"] = None
                    invalid_time = True
            if invalid_time:
                result["collectionReasons"] = sorted(set(result["collectionReasons"]) | {"INVALID_SPAN_TIMESTAMP"})
                if result["status"] == "OBSERVED":
                    result["status"] = "PARTIAL"
        return result
