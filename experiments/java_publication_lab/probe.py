"""Run an isolated 32 MiB Java-publication probe without editing production sources."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "tools" / "java-call-analysis"
PUBLICATION_CALL = "ResultPublication.publish(config.output(), result)"


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
    main = ADAPTER / "src/main/java/io/jjamtong/analysis/Main.java"
    text = main.read_text(encoding="utf-8")
    if text.count(PUBLICATION_CALL) != 1 or text.count('"adapterVersion", "0.2.2"') != 1:
        raise ValueError("production Main.java no longer has the expected single publication/version marker")
    source = output / "source" / "io" / "jjamtong" / "analysis" / "Main.java"
    source.parent.mkdir(parents=True)
    source.write_text(text.replace(PUBLICATION_CALL, "ResultPublication.publish(config.output(), result, 32L * 1024 * 1024)")
                      .replace('"adapterVersion", "0.2.2"', '"adapterVersion", "0.2.2-probe32"'), encoding="utf-8")
    classes = output / "classes"
    classes.mkdir()
    classpath = f"{ADAPTER / 'target/classes'}:{ADAPTER / 'target/dependency/*'}"
    javac = java_home / "bin" / "javac"
    java = java_home / "bin" / "java"
    subprocess.run([str(javac), "--release", "17", "-cp", classpath, "-d", str(classes), str(source)],
                   check=True, timeout=60, capture_output=True, text=True)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    methods = output / "methods.json"
    args = [str(java), "-Xmx1g", "-cp", f"{classes}:{classpath}", "io.jjamtong.analysis.Main",
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
    result = {"schema": "jjamtong.java-publication-probe.v1", "adapterVersion": "0.2.2-probe32",
              "javaExitCode": process.returncode, "javaSeconds": time.monotonic() - started,
              "javaPeakRssBytes": None, "outputBytes": methods.stat().st_size,
              "fixture": fixture.name, "javaOutput": stdout.strip()}
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
