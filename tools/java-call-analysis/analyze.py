#!/usr/bin/env python3
"""Run a local analysis with bounded JVM resources and atomic success output."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--java-home", type=Path, required=True)
    args, cli = parser.parse_known_args()
    jar = HERE / "target/java-call-analysis-0.1.0.jar"
    if not jar.is_file():
        parser.error("build the tool first with build.py")
    # JVM has no target-agent or application classpath; it only reads the supplied files.
    classpath = f"{jar}:{HERE / 'target/dependency/*'}"
    try:
        # The parent owns scratch space so JVM timeout/kill cannot leak extracted JARs.
        with tempfile.TemporaryDirectory(prefix="jjamtong-analysis-run-") as scratch:
            subprocess.run([str(args.java_home / "bin/java"), "-Xmx1g", "-Djava.io.tmpdir=" + scratch,
                            "-cp", classpath, "io.jjamtong.analysis.Main", *cli], timeout=60, check=True)
    except subprocess.TimeoutExpired:
        print("analysis failed: 60-second deadline exceeded; no new success result published", file=sys.stderr)
        return 124
    except subprocess.CalledProcessError as failure:
        return failure.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
