"""Local CLI; credentials come only from JJAMTONG_EVIDENCE_DSN."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import psycopg

from tools.method_evidence.evidence import MAX_BYTES, read_otlp
from .contracts import (EvidenceReader, EvidenceTimeout, GraphRequest, SnapshotConflict,
                        SnapshotRef, VersionMismatch)
from .postgres import PostgresEvidenceStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    publish = commands.add_parser("publish")
    publish.add_argument("--tenant", required=True)
    publish.add_argument("--index", type=Path, required=True)
    for name in ("graph", "trace"):
        sub = commands.add_parser(name)
        sub.add_argument("--tenant", required=True)
        sub.add_argument("--run-id", required=True)
        sub.add_argument("--index-sha256", required=True)
        if name == "graph":
            sub.add_argument("--analyzer", choices=("javaparser", "wala"), required=True)
            sub.add_argument("--root", nargs=4, metavar=("MODULE", "CLASS", "METHOD", "DESCRIPTOR"), required=True)
            sub.add_argument("--depth", type=int, default=4)
            sub.add_argument("--nodes", type=int, default=200)
            sub.add_argument("--edges", type=int, default=500)
        else:
            sub.add_argument("--log", type=Path, required=True)
            sub.add_argument("--trace-id", required=True)
            sub.add_argument("--telemetry-config", required=True)
    args = parser.parse_args()
    dsn = os.environ.get("JJAMTONG_EVIDENCE_DSN")
    if not dsn:
        parser.error("JJAMTONG_EVIDENCE_DSN is required")
    try:
        result = execute(args, dsn)
    except (SnapshotConflict, VersionMismatch) as exc:
        parser.error(str(exc))
    except EvidenceTimeout:
        parser.error("Evidence snapshot query time budget exceeded")
    except (ValueError, TypeError, KeyError, AttributeError):
        parser.error("Invalid evidence input or unsupported index fields")
    except psycopg.Error as exc:
        parser.error("Database operation failed: " + type(exc).__name__)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def execute(args, dsn):
    store = PostgresEvidenceStore(dsn)
    if args.command == "init":
        store.initialize()
        result = {"schema": "jjamtong_evidence_v1", "initialized": True}
    elif args.command == "publish":
        with args.index.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Index exceeds 10 MiB")
        index = json.loads(raw)
        result = {"created": store.publish(args.tenant, index), "analysisRunId": index["analysisRunId"],
                  "indexSha256": index["indexSha256"]}
    else:
        ref = SnapshotRef(args.tenant, args.run_id, args.index_sha256)
        reader = EvidenceReader(store, store)
        if args.command == "graph":
            result = asdict(reader.graph(GraphRequest(ref, args.analyzer, tuple(args.root),
                                                     args.depth, args.nodes, args.edges)))
        else:
            result = reader.trace(ref, read_otlp(args.log), args.trace_id, args.telemetry_config)
    return result


if __name__ == "__main__":
    main()
