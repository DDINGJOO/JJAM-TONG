import argparse
import json
from pathlib import Path
from .evidence import create_index, load_index, query, read_otlp, save_index


def main():
    parser = argparse.ArgumentParser(description="Experimental exact-version method evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index")
    for key in ("analysis", "manifest", "artifact", "sources", "store", "run-id"):
        index.add_argument("--" + key, required=True)
    lookup = commands.add_parser("query")
    for key in ("store", "run-id", "log", "trace-id"):
        lookup.add_argument("--" + key, required=True)
    lookup.add_argument("--telemetry-config", required=True)
    args = parser.parse_args()
    if args.command == "index":
        value = create_index(json.loads(Path(args.analysis).read_text()), json.loads(Path(args.manifest).read_text()),
                             Path(args.artifact), Path(args.sources), args.run_id)
        destination = save_index(value, args.store)
        print(json.dumps({"analysisRunId": value["analysisRunId"], "indexSha256": value["indexSha256"],
                          "stored": destination.name}))
    else:
        print(json.dumps(query(load_index(args.store, args.run_id), read_otlp(args.log),
                               args.trace_id, args.telemetry_config), indent=2))


if __name__ == "__main__":
    main()
