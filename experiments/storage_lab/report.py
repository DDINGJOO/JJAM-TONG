"""Package measured raw results without publishing environment credentials."""
import argparse
import hashlib
import json
from pathlib import Path

from .run import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "results/storage-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/experiments/storage-engine-run.json")
    args = parser.parse_args()
    names = ("postgres", "neo4j", "elasticsearch", "clickhouse")
    environment = json.loads((args.input / "environment.json").read_text())
    engines = {name: json.loads((args.input / (name + ".json")).read_text()) for name in names}
    for name, result in engines.items():
        if result.get("status") == "failed" or len(result.get("scales", [])) != 2:
            raise SystemExit("incomplete engine result: " + name)
    federation = json.loads((args.input / "federation.json").read_text())
    files = ["fixtures.py", "stores.py", "pipeline.py", "run.py", "compose.yaml", "clickhouse.xml", "requirements.txt"]
    sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files}
    output = dict(environment=environment, engines=engines, federation=federation,
                  packaged_source_sha256=sources,
                  counts={"fixture_assertions": sum(len(s["correctness_checks"]) for e in engines.values() for s in e["scales"]),
                          "latency_samples": sum(len(q["samples_ms"]) for e in engines.values() for s in e["scales"] for q in s["queries"].values()),
                          "concurrent_read_operations": sum(c["operations"] for e in engines.values() for s in e["scales"] for c in s["concurrent_reads"]),
                          "pipeline_checks": sum(len(e.get("pipeline", {}).get("checks", [])) for e in engines.values()),
                          "federation_checks": len(federation["checks"])})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["counts"]))
    print(str(args.output))


if __name__ == "__main__":
    main()
