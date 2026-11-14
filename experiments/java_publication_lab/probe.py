"""Run an isolated 32 MiB Java-publication probe without editing production sources."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import hashlib
import re


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "tools" / "java-call-analysis"
PUBLICATION_CALL = "ResultPublication.publish(config.output(), result)"
PRODUCER_COMMIT = "7748983c75f988fd94acdc6b70101581e51ed873"


def runtime_dependencies(adapter: Path = ADAPTER) -> dict[str, str]:
    """Validate the whole local build manifest, including transitive runtime JARs.

    The manifest records this build, rather than being a historical transitive lock.
    The separate provenance contract pins direct dependencies.
    """
    manifest = json.loads((adapter / "target/dependency-sha256.json").read_bytes())
    if manifest.get("schema") != "jjamtong.analysis-dependencies.v1":
        raise ValueError("unsupported build dependency manifest")
    expected = {}
    for item in manifest["artifacts"]:
        name, sha = item["file"], item["sha256"]
        if (Path(name).name != name or not name.endswith(".jar") or name in expected
                or not re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise ValueError("invalid or duplicate dependency manifest entry")
        expected[name] = sha
    producer_name = "java-call-analysis-0.1.0.jar"
    if producer_name not in expected:
        raise ValueError("build manifest lacks producer JAR")
    producer = adapter / "target" / producer_name
    if hashlib.sha256(producer.read_bytes()).hexdigest() != expected.pop(producer_name):
        raise ValueError("built producer JAR differs from build manifest")
    actual = {path.name for path in (adapter / "target/dependency").glob("*.jar")}
    if actual != set(expected):
        raise ValueError("runtime JAR set differs from complete build manifest")
    pinned = json.loads((adapter / "dependency-provenance.json").read_bytes())["binarySha256"]
    if any(expected.get(name) != sha for name, sha in pinned.items()):
        raise ValueError("direct dependency differs from pinned contract")
    for name, sha in expected.items():
        if hashlib.sha256((adapter / "target/dependency" / name).read_bytes()).hexdigest() != sha:
            raise ValueError("runtime dependency bytes differ from build manifest")
    return dict(sorted(expected.items()))


def _empty_output(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("output must be new or empty; the probe never reuses old output")
    path.mkdir(parents=True, exist_ok=True)


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.communicate()


def probe(fixture: Path, output: Path, java_home: Path, timeout: int = 60) -> dict:
    metadata_path = fixture / "metadata.json"
    if not (fixture / "sources").is_dir() or not (fixture / "fixture.jar").is_file() or not metadata_path.is_file():
        raise ValueError("fixture must contain sources, fixture.jar and metadata.json")
    _empty_output(output)
    prefix = "tools/java-call-analysis/"
    def historical(name):
        return subprocess.check_output(["git", "show", PRODUCER_COMMIT + ":" + prefix + name], cwd=ROOT)
    pinned = historical("dependency-provenance.json")
    if pinned != (ADAPTER / "dependency-provenance.json").read_bytes():
        raise ValueError("historical and current pinned dependency contracts differ")
    dependencies = runtime_dependencies()
    dependency_manifest_sha = hashlib.sha256((ADAPTER / "target/dependency-sha256.json").read_bytes()).hexdigest()
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", PRODUCER_COMMIT,
                                     prefix + "src/main/java"], cwd=ROOT, text=True).splitlines()
    historical_sources = {}
    for path in paths:
        if not path.endswith(".java"):
            continue
        relative = path.removeprefix(prefix)
        data = historical(relative)
        historical_sources[relative] = hashlib.sha256(data).hexdigest()
        destination = output / "source" / Path(relative).relative_to("src/main/java")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    source = output / "source/io/jjamtong/analysis/Main.java"
    text = source.read_text(encoding="utf-8")
    if text.count(PUBLICATION_CALL) != 1 or text.count('"adapterVersion", "0.2.2"') != 1:
        raise ValueError("historical Main.java lacks the expected publication/version marker")
    source.write_text(text.replace(PUBLICATION_CALL, "ResultPublication.publish(config.output(), result, 32L * 1024 * 1024)")
                      .replace('"adapterVersion", "0.2.2"', '"adapterVersion", "0.2.2-probe32"'), encoding="utf-8")
    classes = output / "classes"
    classes.mkdir()
    classpath = os.pathsep.join(str(ADAPTER / "target/dependency" / name) for name in dependencies)
    javac = java_home / "bin" / "javac"
    java = java_home / "bin" / "java"
    subprocess.run([str(javac), "--release", "17", "-cp", classpath, "-d", str(classes),
                    *map(str, sorted((output / "source").rglob("*.java")))],
                   check=True, timeout=60, capture_output=True, text=True)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    methods = output / "methods.json"
    args = [str(java), "-Xmx1g", "-cp", str(classes) + os.pathsep + classpath, "io.jjamtong.analysis.Main",
            "--source-root", str(fixture / "sources"), "--artifact", str(fixture / "fixture.jar"),
            "--metadata", str(metadata_path), "--module", metadata["module"], "--include-package", "fixture.scale",
            "--entrypoint", "fixture.scale.Main", "--output", str(methods)]
    started = time.monotonic()
    log = output / "java.log"
    with log.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            _terminate(process)
            raise
    if process.returncode:
        raise RuntimeError("isolated Java probe failed; inspect output/java.log")
    if (runtime_dependencies() != dependencies or hashlib.sha256(
            (ADAPTER / "target/dependency-sha256.json").read_bytes()).hexdigest() != dependency_manifest_sha):
        raise ValueError("runtime dependency provenance changed during replay")
    result = {"schema": "jjamtong.java-publication-probe.v1", "adapterVersion": "0.2.2-probe32",
              "javaExitCode": process.returncode, "javaSeconds": time.monotonic() - started,
              "javaPeakRssBytes": None, "outputBytes": methods.stat().st_size,
              "fixture": fixture.name, "javaOutput": stdout.strip(), "producerCommit": PRODUCER_COMMIT,
              "historicalSourceSha256": historical_sources,
              "dependencyContractSha256": hashlib.sha256(pinned).hexdigest(),
              "runtimeDependencySha256": dependencies,
              "buildDependencyManifestSha256": dependency_manifest_sha,
              "rawSha256": hashlib.sha256(methods.read_bytes()).hexdigest()}
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    print(json.dumps(probe(args.fixture, args.output, args.java_home, args.timeout), indent=2))


if __name__ == "__main__":
    main()
