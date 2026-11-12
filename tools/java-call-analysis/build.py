#!/usr/bin/env python3
"""Build the experimental adapters with the already available Maven JDK 21 image."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IMAGE = "maven:3.9.9-eclipse-temurin-21"


def main():
    command = [
        "docker", "run", "--rm", "--pull=never", "--memory=1536m", "--cpus=2",
        "-e", "MAVEN_CONFIG=/tmp/maven-method-analysis/.m2",
        "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{REPO}:/workspace",
        "-w", "/workspace", IMAGE, "mvn", "-B", "-ntp",
        "-Duser.home=/tmp/maven-method-analysis",
        "-Dmaven.repo.local=/workspace/.local/method-analysis-m2",
        "-f", "tools/java-call-analysis/pom.xml", "clean", "package",
    ]
    subprocess.run(command, check=True, timeout=240)
    artifacts = sorted((HERE / "target/dependency").glob("*.jar")) + [HERE / "target/java-call-analysis-0.1.0.jar"]
    expected = json.loads((HERE / "dependency-provenance.json").read_text())["binarySha256"]
    for name, digest in expected.items():
        if hashlib.sha256((HERE / "target/dependency" / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"pinned binary digest mismatch: {name}")
    manifest = {
        "schema": "jjamtong.analysis-dependencies.v1",
        "artifacts": [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in artifacts],
    }
    (HERE / "target/dependency-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Built target/java-call-analysis-0.1.0.jar and target/dependency; verification: python3 tools/java-call-analysis/verify.py --java-home <JDK17-or-21>")


if __name__ == "__main__":
    main()
