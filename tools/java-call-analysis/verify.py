#!/usr/bin/env python3
"""Run the synthetic positive/negative oracle on an installed JDK 17 or 21."""
import argparse
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", required=True, type=Path)
    args = parser.parse_args()
    classpath = f"{HERE / 'target/test-classes'}:{HERE / 'target/classes'}:{HERE / 'target/dependency/*'}"
    subprocess.run([str(args.java_home / "bin/java"), "-Xmx1g", "-cp", classpath,
                    "io.jjamtong.analysis.SyntheticOracle"], check=True, timeout=60)


if __name__ == "__main__":
    main()
