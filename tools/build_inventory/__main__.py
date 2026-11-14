"""Inspect declared build inputs and compare explicitly pinned local snapshots."""
import argparse
import json
from pathlib import Path
import sys

from .baseline import compare
from .discovery import discover
from .inventory import SafeReader, _json_no_duplicates, link_analysis, load_manifest, load_snapshot, save_snapshot

MAX_JSON = 10 * 1024 * 1024


def _read_index(path):
    path = Path(path).absolute()
    with SafeReader(path.parent) as reader:
        data = reader.read_bytes(path.name, max_bytes=MAX_JSON)
    return _json_no_duplicates(data)


def _emit(document, output=None):
    data = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_JSON:
        raise ValueError("report exceeds 10 MiB")
    if output:
        with Path(output).open("xb") as stream:
            stream.write(data)
    else:
        sys.stdout.write(data.decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("discover", help="Read descriptors without running a build")
    find.add_argument("--root", required=True)
    find.add_argument("--adapter", choices=("maven", "gradle"))
    find.add_argument("--entry")
    find.add_argument("--output")
    capture = commands.add_parser("capture", help="Verify an explicitly supplied portable manifest")
    capture.add_argument("--root", required=True)
    capture.add_argument("--manifest", required=True)
    capture.add_argument("--tenant", required=True)
    capture.add_argument("--output", required=True)
    inspect = commands.add_parser("inspect", help="Validate a saved record without rereading old files")
    inspect.add_argument("--snapshot", required=True)
    inspect.add_argument("--output")
    diff = commands.add_parser("compare", help="Compare declared inputs, with exact manifest SHA pins")
    diff.add_argument("--baseline", required=True)
    diff.add_argument("--current", required=True)
    diff.add_argument("--baseline-sha256", required=True)
    diff.add_argument("--current-sha256", required=True)
    diff.add_argument("--limit", type=int, default=100)
    diff.add_argument("--output")
    link = commands.add_parser("link", help="Validate the existing v1 metadata bridge")
    link.add_argument("--snapshot", required=True)
    link.add_argument("--index", required=True)
    link.add_argument("--module", required=True)
    link.add_argument("--artifact", required=True)
    link.add_argument("--index-sha256", required=True)
    link.add_argument("--config-sha256", required=True)
    link.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            result = discover(args.root, adapter=args.adapter, entry=args.entry)
        elif args.command == "capture":
            snapshot = load_manifest(args.manifest, args.root, args.tenant)
            save_snapshot(snapshot, args.output)
            result = {"status": "SAVED", "manifestSha256": snapshot.manifest_sha256,
                      "verificationSha256": snapshot.verification_sha256}
            return _emit(result) or 0
        elif args.command == "inspect":
            result = load_snapshot(args.snapshot).to_dict()
        elif args.command == "compare":
            result = compare(load_snapshot(args.baseline), load_snapshot(args.current),
                             args.baseline_sha256, args.current_sha256, limit=args.limit)
        else:
            result = link_analysis(load_snapshot(args.snapshot), _read_index(args.index),
                                   args.module, args.artifact, args.index_sha256,
                                   args.config_sha256).to_dict()
        _emit(result, args.output)
        return 0
    except (ValueError, OSError, UnicodeError, NotImplementedError) as error:
        print(json.dumps({"status": "ERROR", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
