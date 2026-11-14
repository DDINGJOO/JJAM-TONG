"""Serve real local evidence at http://127.0.0.1:28740 without new dependencies."""
import argparse
import os
from pathlib import Path

from tools.evidence_store.postgres import PostgresEvidenceStore
from tools.method_evidence.evidence import HEX64, read_otlp, valid_id
from .server import WorkspaceServer
from .service import EvidenceWorkspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--port", type=int, default=28740)
    parser.add_argument("--trace-log", type=Path)
    parser.add_argument("--telemetry-config")
    parser.add_argument("--trace-id", help="Optionally expose only this captured trace")
    args = parser.parse_args()
    dsn = os.environ.get("JJAMTONG_EVIDENCE_DSN")
    if not dsn:
        parser.error("JJAMTONG_EVIDENCE_DSN is required")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be 1..65535")
    if bool(args.trace_log) != bool(args.telemetry_config) or (args.trace_id and not args.trace_log):
        parser.error("Trace capture requires --trace-log and --telemetry-config together")
    if args.telemetry_config and not HEX64.fullmatch(args.telemetry_config):
        parser.error("Expected exact telemetry configuration SHA-256")
    if args.trace_id and not valid_id(args.trace_id, 32):
        parser.error("Expected an exact 32-character trace ID")
    try:
        collection = read_otlp(args.trace_log) if args.trace_log else None
        if args.trace_id:
            collection["spans"] = [span for span in collection["spans"] if span["traceId"] == args.trace_id]
        workspace = EvidenceWorkspace(PostgresEvidenceStore(dsn), args.tenant, collection=collection,
                                      telemetry_config=args.telemetry_config)
        server = WorkspaceServer(workspace, args.port)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        parser.error("Could not initialize the local evidence workspace; check the capture and port")
    print("JJAM-TONG local read-only workspace: http://127.0.0.1:" + str(server.server_port), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
