#!/usr/bin/env python3
"""Build and test the OpenTelemetry API-only context adapter against explicit local JARs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", type=Path, default=os.environ.get("JAVA_HOME"))
    parser.add_argument("--java21-home", type=Path, required=True)
    parser.add_argument("--evidence-contract", type=Path, required=True)
    parser.add_argument("--otel-api", type=Path, required=True)
    parser.add_argument("--otel-context", type=Path, required=True)
    parser.add_argument("--otel-common", type=Path, required=True,
                        help="the API/context runtime dependency, not an SDK")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    build = root / "build"
    build.mkdir(exist_ok=True)
    for dependency in (args.evidence_contract, args.otel_api, args.otel_context, args.otel_common):
        if not dependency.is_file():
            parser.error(f"required JAR is missing: {dependency}")

    def tool(home, name):
        path = str(home / "bin" / name) if home else shutil.which(name)
        if not path or not Path(path).is_file():
            parser.error(f"{name} unavailable; pass a matching JDK home")
        return path

    javac, java, jar = (tool(args.java_home, name) for name in ("javac", "java", "jar"))
    javac21, java21 = (tool(args.java21_home, name) for name in ("javac", "java"))
    dependencies = os.pathsep.join(map(str, (
        args.evidence_contract, args.otel_api, args.otel_context, args.otel_common)))

    def run(command):
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        output = (result.stdout + result.stderr).strip()
        if result.returncode:
            print(output, file=sys.stderr)
            raise SystemExit(result.returncode)
        return output

    with tempfile.TemporaryDirectory(prefix="compile-", dir=build) as temporary:
        work = Path(temporary)
        classes, tests, tests21 = work / "classes", work / "tests", work / "tests21"
        classes.mkdir()
        tests.mkdir()
        tests21.mkdir()
        sources = sorted(str(p) for p in (root / "src/main/java").rglob("*.java"))
        test_sources = sorted(str(p) for p in (root / "src/test/java").rglob("*.java"))
        test_sources21 = sorted(str(p) for p in (root / "src/test/java21").rglob("*.java"))
        run([javac, "--release", "17", "-Xlint:all", "-Werror", "-cp", dependencies,
             "-d", str(classes), *sources])
        temporary_jar = work / "otel-context.jar"
        run([jar, "--create", "--file", str(temporary_jar), "-C", str(classes), "."])
        test_classpath = os.pathsep.join((str(temporary_jar), dependencies))
        run([javac, "--release", "17", "-Xlint:all", "-Werror", "-cp", test_classpath,
             "-d", str(tests), *test_sources])
        api_tests = run([java, "-cp", os.pathsep.join((test_classpath, str(tests))),
                         "io.jjamtong.otelcontext.ContextAdapterTest"])
        run([javac21, "--release", "21", "-Xlint:all", "-Werror", "-cp", test_classpath,
             "-d", str(tests21), *test_sources21])
        virtual_tests = run([java21, "-cp", os.pathsep.join((test_classpath, str(tests21))),
                             "io.jjamtong.otelcontext.VirtualThreadContextTest"])
        artifact = build / "otel-context.jar"
        shutil.copyfile(temporary_jar, artifact)
        report = {
            "java": run([java, "-version"]), "javac": run([javac, "-version"]),
            "java21": run([java21, "-version"]), "javac21": run([javac21, "-version"]),
            "main_release": 17, "virtual_thread_test_release": 21,
            "api_tests": api_tests, "virtual_thread_tests": virtual_tests,
            "external_dependencies": {str(path.name): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in (args.evidence_contract, args.otel_api, args.otel_context,
                                                   args.otel_common)},
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        (build / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(api_tests)
        print(virtual_tests)
        print(f"JAR {artifact.name} SHA256 {report['artifact_sha256']}")


if __name__ == "__main__":
    main()
