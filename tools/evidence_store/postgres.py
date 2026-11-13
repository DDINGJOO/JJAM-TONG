"""One local adapter implements two independent ports, with atomic publication."""
import json
from pathlib import Path
import time

import psycopg
from psycopg.types.json import Jsonb

from .contracts import (EvidenceTimeout, GraphResult, SnapshotConflict, SnapshotRef, VersionMismatch,
                        identifier, prepare, symbol_json)
from tools.method_evidence.evidence import validate_index

PREFIX = "jjamtong_evidence_v1."


class PostgresEvidenceStore:
    def __init__(self, dsn):
        self.dsn = dsn

    def _connect(self):
        return psycopg.connect(self.dsn, connect_timeout=3,
                               options="-c statement_timeout=5000 -c lock_timeout=3000")

    def initialize(self):
        with self._connect() as conn:
            conn.execute(Path(__file__).with_name("schema.sql").read_text())

    def publish(self, tenant, index):
        identifier(tenant)
        # Copy through JSON before validation: caller mutation cannot change the
        # verified document after graph derivation or during publication.
        index = json.loads(json.dumps(index, ensure_ascii=False))
        derived = prepare(index)
        ref = SnapshotRef(tenant, index["analysisRunId"], index["indexSha256"])
        coverage = {name: value["coverage"] for name, value in derived.items()}
        with self._connect() as conn:
            created = conn.execute(
                "INSERT INTO " + PREFIX + "analysis VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id,run_id) DO NOTHING RETURNING run_id",
                (tenant, ref.run_id, ref.index_sha256, ref.index_sha256, Jsonb(index), Jsonb(coverage))
            ).fetchone()
            if created is None:
                prior = conn.execute("SELECT index_sha256 FROM " + PREFIX +
                                     "analysis WHERE tenant_id=%s AND run_id=%s",
                                     (tenant, ref.run_id)).fetchone()
                if prior is None:
                    raise RuntimeError("Published run disappeared during conflict resolution; retry")
                if prior[0] != ref.index_sha256:
                    raise SnapshotConflict("Run already published with different content")
                return False
            self._insert_projection(conn, ref, derived)
        return True

    def _insert_projection(self, conn, ref, derived):
        for analyzer, rows in derived.items():
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO " + PREFIX + "method VALUES (%s,%s,%s,%s)",
                                [(ref.tenant, ref.run_id, analyzer, node) for node in rows["nodes"]])
                cur.executemany("INSERT INTO " + PREFIX + "call VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                [(ref.tenant, ref.run_id, analyzer, ordinal, caller, target, Jsonb(call))
                                 for ordinal, caller, target, call in rows["edges"]])

    @staticmethod
    def _stamp(row, ref):
        if row[0] != ref.index_sha256 or row[1] != ref.index_sha256:
            raise VersionMismatch("Stored source/projection differs from the requested index")

    def load(self, ref):
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT index_sha256,projection_sha256,document FROM " + PREFIX +
                                   "analysis WHERE tenant_id=%s AND run_id=%s",
                                   (ref.tenant, ref.run_id)).fetchone()
        except psycopg.errors.QueryCanceled:
            raise EvidenceTimeout("Evidence snapshot query time budget exceeded") from None
        if row is None:
            return None
        self._stamp(row, ref)
        index = validate_index(row[2])
        if index["indexSha256"] != ref.index_sha256 or index["analysisRunId"] != ref.run_id:
            raise VersionMismatch("Stored document differs from requested analysis")
        return index

    def walk(self, request):
        try:
            return self._read_graph(request)
        except psycopg.errors.QueryCanceled:
            # Timeout before traversal/root validation: do not imply missing history.
            return GraphResult(request, "UNRESOLVED", [], [], ["TIME_BUDGET"], {})

    def _read_graph(self, request):
        ref, analyzer = request.ref, request.analyzer
        with self._connect() as conn:
            # One stable view even if another writer publishes unrelated builds.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            row = conn.execute("SELECT index_sha256,projection_sha256,coverage FROM " + PREFIX +
                               "analysis WHERE tenant_id=%s AND run_id=%s",
                               (ref.tenant, ref.run_id)).fetchone()
            if row is None:
                return GraphResult(request, "UNRESOLVED", [], [], ["HISTORY_NOT_COLLECTED"], {})
            self._stamp(row, ref)
            coverage = row[2][analyzer]
            root = symbol_json(request.root)
            exists = conn.execute("SELECT 1 FROM " + PREFIX + "method WHERE tenant_id=%s "
                                  "AND run_id=%s AND analyzer=%s AND symbol=%s",
                                  (ref.tenant, ref.run_id, analyzer, root)).fetchone()
            if not exists:
                return GraphResult(request, "UNRESOLVED", [], [], ["ROOT_NOT_IN_ANALYZER"], coverage)
            return self._walk(conn, request, coverage, root)

    @staticmethod
    def _walk(conn, request, coverage, root):
        visited, frontier, calls, reasons = {root}, [root], [], set()
        ref = request.ref
        deadline = time.monotonic() + 5
        for depth in range(request.max_depth + 1):
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                reasons.add("TIME_BUDGET")
                break
            try:
                conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(remaining_ms) + "ms",))
                if depth == request.max_depth:
                    beyond = conn.execute(
                        "SELECT 1 FROM " + PREFIX + "call WHERE tenant_id=%s AND run_id=%s "
                        "AND analyzer=%s AND caller=ANY(%s) AND NOT (target=ANY(%s)) LIMIT 1",
                        (ref.tenant, ref.run_id, request.analyzer, frontier, sorted(visited))).fetchone()
                    if beyond:
                        reasons.add("DEPTH_LIMIT")
                    break
                rows = conn.execute(
                    "SELECT target,evidence FROM " + PREFIX + "call WHERE tenant_id=%s AND run_id=%s "
                    "AND analyzer=%s AND caller=ANY(%s) ORDER BY caller,target,ordinal LIMIT %s",
                    (ref.tenant, ref.run_id, request.analyzer, frontier,
                     request.max_edges - len(calls) + 1)).fetchall()
            except psycopg.errors.QueryCanceled:
                conn.rollback()
                reasons.add("TIME_BUDGET")
                break
            next_frontier = []
            for target, evidence in rows:
                if len(calls) >= request.max_edges:
                    reasons.add("EDGE_LIMIT")
                    break
                if target not in visited:
                    if len(visited) >= request.max_nodes:
                        reasons.add("NODE_LIMIT")
                        break
                    visited.add(target)
                    next_frontier.append(target)
                calls.append(evidence)
            if reasons or not next_frontier:
                break
            frontier = next_frontier
        if time.monotonic() >= deadline:
            reasons.add("TIME_BUDGET")
        for field, reason in (("unresolved", "ANALYZER_UNRESOLVED"),
                              ("excluded", "ANALYZER_EXCLUDED"), ("danglingCalls", "DANGLING_STATIC_CALLS")):
            if coverage[field]:
                reasons.add(reason)
        return GraphResult(request, "PARTIAL" if reasons else "STATIC_CANDIDATES",
                           [json.loads(node) for node in sorted(visited)], calls,
                           sorted(reasons), coverage)
