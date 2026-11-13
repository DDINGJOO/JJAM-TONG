"""Command line entry point for one explicit GitHub Actions source."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from .collector import Collector, GitHubTransport, ImportError, SourceConfig
from .contract import CONTRACT


def _write_receipts(directory, receipts):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for receipt in receipts:
        destination = target / ("run-" + receipt.run_id + "-attempt-" + receipt.attempt + ".json")
        data = json.dumps(receipt.json(), sort_keys=True, separators=(",", ":")) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=target)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _single(args, continue_on_error=False):
    token, dsn = os.environ.get("JJAMTONG_GITHUB_TOKEN"), os.environ.get("JJAMTONG_EVIDENCE_DSN")
    if not token or not dsn:
        raise ValueError("JJAMTONG_GITHUB_TOKEN and JJAMTONG_EVIDENCE_DSN are required")
    # Keep --help and injected/offline collection usable without the optional
    # PostgreSQL driver's environment; a real pull still uses the existing store.
    from tools.evidence_store.postgres import PostgresEvidenceStore
    source = SourceConfig(args.repository, args.workflow, args.branch, args.tenant, args.pages)
    collector = Collector(source, GitHubTransport(token), PostgresEvidenceStore(dsn), CONTRACT)
    receipts = collector.collect(args.run_id, continue_on_error, lambda exc: print(
        "github evidence sync failed: " + str(exc), file=sys.stderr))
    if args.receipts:
        try:
            _write_receipts(args.receipts, receipts)
        except OSError:
            raise ValueError("RECEIPT_WRITE_FAILED") from None
    for receipt in receipts:
        print(json.dumps(receipt.json(), sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m tools.github_evidence_sync")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pull", "watch"):
        command = commands.add_parser(name)
        command.add_argument("--repository", required=True)
        command.add_argument("--workflow", required=True, help="workflow filename (for example ci.yml)")
        command.add_argument("--branch", default="main")
        command.add_argument("--tenant", required=True)
        command.add_argument("--run-id")
        command.add_argument("--pages", type=int, default=3)
        command.add_argument("--receipts")
        if name == "watch":
            command.add_argument("--interval", type=int, default=30)
    args = parser.parse_args(argv)
    if args.command == "watch" and args.interval < 10:
        parser.error("--interval must be at least 10 seconds")
    if args.command == "pull":
        try:
            _single(args)
        except (ImportError, ValueError) as exc:
            print("github evidence sync failed: " + str(exc), file=sys.stderr)
            return 1
        return 0
    while True:
        try:
            _single(args, continue_on_error=True)
        except (ImportError, ValueError) as exc:
            # Per-run and transient failures remain sanitized; the next poll retries.
            print("github evidence sync failed: " + str(exc), file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
