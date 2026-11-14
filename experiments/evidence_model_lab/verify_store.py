"""Read existing synthetic PostgreSQL analyses and verify the metadata bridge.

No schema initialization or publication is performed. All connections explicitly
start read-only transactions; this command requires the existing Psycopg setup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tools.evidence_store.contracts import SnapshotRef, VersionMismatch
from tools.evidence_store.postgres import PostgresEvidenceStore
from tools.method_evidence.evidence import file_digest
from .model import import_v1, require_exact_bridge


class ReadOnlyStore(PostgresEvidenceStore):
    def _connect(self):
        conn = super()._connect()
        try:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        except BaseException:
            conn.close()
            raise
        return conn


def verify(store, tenant, paths):
    with store._connect() as conn:
        read_only = conn.execute("SHOW transaction_read_only").fetchone()[0]
        version = conn.execute("SHOW server_version").fetchone()[0]
    if read_only != "on":
        raise AssertionError("Expected server-enforced read-only transaction")
    analyses = []
    for path in paths:
        expected = json.loads(path.read_text())
        selected = SnapshotRef(tenant, expected["analysisRunId"], expected["indexSha256"])
        stored = store.load(selected)
        if stored != expected:
            raise AssertionError("Stored original differs from the explicitly selected input")
        bridge = import_v1(stored, tenant)
        exact = require_exact_bridge(bridge, expected["buildIdentity"], expected["indexSha256"], expected["configSha256"])
        if dict(exact.build_identity) != expected["buildIdentity"]:
            raise AssertionError("Bridge changed a build identity field")
        invalid = {}
        for field in expected["buildIdentity"]:
            changed = dict(expected["buildIdentity"])
            changed[field] = (("0" if changed[field][0] != "0" else "1") + changed[field][1:]
                              if field == "artifactSha256" else changed[field] + "-wrong")
            try:
                require_exact_bridge(bridge, changed, bridge.index_sha256, bridge.config_sha256)
            except ValueError:
                invalid[field] = "REJECTED"
            else:
                raise AssertionError("Bridge accepted a different build field")
        wrong_hash = ("0" if selected.index_sha256[0] != "0" else "1") + selected.index_sha256[1:]
        try:
            store.load(SnapshotRef(tenant, selected.run_id, wrong_hash))
        except VersionMismatch:
            invalid["databaseIndexSha256"] = "REJECTED"
        else:
            raise AssertionError("Database accepted another analysis hash")
        for field in ("indexSha256", "configSha256"):
            hashes = {"indexSha256": bridge.index_sha256, "configSha256": bridge.config_sha256}
            hashes[field] = ("0" if hashes[field][0] != "0" else "1") + hashes[field][1:]
            try:
                require_exact_bridge(bridge, expected["buildIdentity"], hashes["indexSha256"], hashes["configSha256"])
            except ValueError:
                invalid[field] = "REJECTED"
            else:
                raise AssertionError("Bridge accepted another analysis/configuration hash")
        rendered = bridge.to_dict()
        wanted_kinds = {"REPOSITORY", "SOURCE_REVISION", "MODULE", "MODULE_BUILD", "ARTIFACT", "ANALYSIS_SNAPSHOT"}
        if {item["kind"] for item in rendered["refs"].values()} != wanted_kinds:
            raise AssertionError("Metadata bridge invented or omitted a domain")
        analyses.append({"input": {"name": path.name, "fileSha256": file_digest(path)},
                         "originalDocumentExact": True, "bridge": rendered,
                         "negativeChecks": invalid, "status": "PASS"})
    if len(analyses) != 2 or analyses[0]["bridge"]["buildIdentity"] == analyses[1]["bridge"]["buildIdentity"]:
        raise AssertionError("Expected exactly two distinct synthetic builds")
    return {"schema": "jjamtong.evidence-model-store-verification.v1", "syntheticInputOnly": True,
            "serverVersion": version, "transactionReadOnly": read_only, "tenant": tenant,
            "analyses": analyses, "passed": len(analyses), "total": len(analyses),
            "negativeChecksPassed": sum(len(item["negativeChecks"]) for item in analyses),
            "sources": {p.name: file_digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
            "limitations": ["Reads preserved synthetic Java analyses; no fresh Java analysis or application request.",
                            "Metadata only; no full graph migration, runtime ingestion, cloud or security collection.",
                            "No database publication, schema change, capacity or authentication claim."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--index", type=Path, nargs=2, required=True, metavar=("OLD", "NEW"))
    parser.add_argument("--dsn-env", default="JJAMTONG_EVIDENCE_DSN")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        parser.error("Set the named environment variable to the existing local database DSN")
    report = verify(ReadOnlyStore(dsn), args.tenant, args.index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"analyses": report["passed"], "negativeChecks": report["negativeChecksPassed"],
                      "transactionReadOnly": report["transactionReadOnly"]}))


if __name__ == "__main__":
    main()
