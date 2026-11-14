"""Compare an earlier trusted adapter revision with current synthetic scale outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from experiments.analysis_reuse.run import ROOT, measure, semantic

SOURCE_PREFIX = "tools/java-call-analysis/src/main/java/"


def compile_reference(revision, java_home, output):
    """Compile only this repository's analyzer, never the target application's build."""
    revision = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"], cwd=ROOT, text=True).strip()
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision, "--", SOURCE_PREFIX],
                                    cwd=ROOT, text=True).splitlines()
    if not paths or any(not p.startswith(SOURCE_PREFIX) or not p.endswith(".java") for p in paths):
        raise ValueError("baseline must contain only the expected Java analyzer sources")
    sources, classes = output / "reference-sources", output / "reference-classes"
    sources.mkdir(); classes.mkdir()
    evidence = {}
    for name in paths:
        path = sources / Path(name).relative_to(SOURCE_PREFIX)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT)
        path.write_bytes(body)
        evidence[name] = hashlib.sha256(body).hexdigest()
    dependencies = ROOT / "tools/java-call-analysis/target/dependency"
    subprocess.run([str(java_home / "bin/javac"), "--release", "17", "-cp", str(dependencies / "*"),
                    "-d", str(classes), *map(str, sorted(sources.rglob("*.java")))],
                   check=True, capture_output=True, timeout=60)
    return revision, str(classes) + ":" + str(dependencies / "*"), evidence


def compare(java_home, classpath, fixture, output, size, heap, current):
    if output.exists():
        raise FileExistsError(output)
    command = [str(java_home / "bin/java"), "-Xmx" + heap, "-cp", classpath, "io.jjamtong.analysis.Main",
               "--source-root", str(fixture / "sources"), "--artifact", str(fixture / "fixture.jar"),
               "--metadata", str(fixture / "metadata.json"), "--module", "scale-" + str(size),
               "--include-package", "fixture.scale", "--entrypoint", "fixture.scale.Main", "--output", str(output)]
    result = measure(command, output.with_suffix(".log"), timeout=60)
    result.update({"jvmHeapBytes": (1 if heap == "1g" else 2) * 1024 ** 3,
                   "deadlineSeconds": 60, "outputPublished": output.exists(),
                   "diagnosticLargerHeap": heap != "1g"})
    if not result["success"]:
        assert not output.exists(), "failed baseline published a new output"
        return result
    before, after = semantic(output), semantic(current)
    result["baselineAdapterVersion"] = before["provenance"].pop("adapterVersion")
    result["currentAdapterVersion"] = after["provenance"].pop("adapterVersion")
    result["exactBodyMatch"] = before == after
    assert result["exactBodyMatch"], "source positions or relation bodies differ from baseline"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--baseline-revision", required=True,
                        help="trusted local Git revision of this repository's analyzer to compile and execute")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.java_home, args.fixture_dir, args.output = args.java_home.resolve(), args.fixture_dir.resolve(), args.output.resolve()
    for size in [100000, 300000]:
        fixture = args.fixture_dir / ("scale-" + str(size))
        if not all((fixture / name).exists() for name in ["sources", "fixture.jar", "metadata.json", "cold.json"]):
            raise ValueError("run the current synthetic scale experiment first")
    args.output.mkdir(parents=True, exist_ok=False)
    revision, classpath, sources = compile_reference(args.baseline_revision, args.java_home, args.output)
    result = {"schema": "jjamtong.analysis-memory-reference.v1", "synthetic": True,
              "baselineRevision": revision, "baselineSourcesSha256": sources,
              "currentAdapterJarSha256": hashlib.sha256((ROOT / "tools/java-call-analysis/target/java-call-analysis-0.1.0.jar").read_bytes()).hexdigest(),
              "comparisonExcludedFields": ["metadata", "input.metadataInputSha256", "provenance.adapterVersion"],
              "diagnosticPurpose": "The 2 GiB baseline is only a correctness reference, not an equal-budget cost comparison.",
              "cases": {}}
    for size, heap, label in [(100000, "1g", "baseline-100k"), (300000, "1g", "baseline-300k"),
                               (300000, "2g", "diagnostic-300k-2g")]:
        fixture = args.fixture_dir / ("scale-" + str(size))
        value = compare(args.java_home, classpath, fixture, args.output / (label + ".json"), size, heap, fixture / "cold.json")
        result["cases"][label] = value
        (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
        print(label, json.dumps(value), flush=True)


if __name__ == "__main__":
    main()
