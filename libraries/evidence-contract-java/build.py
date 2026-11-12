#!/usr/bin/env python3
"""Build and test the experimental Java contract using an explicitly selected JDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', type=Path, default=os.environ.get('JAVA_HOME'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    build = root / 'build'
    build.mkdir(exist_ok=True)

    def tool(name):
        path = str(Path(args.java_home) / 'bin' / name) if args.java_home else shutil.which(name)
        if not path or not Path(path).is_file():
            parser.error(f'{name} unavailable; pass --java-home pointing to a JDK 17+')
        return path

    javac, java, jar = (tool(name) for name in ('javac', 'java', 'jar'))

    def run(command):
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        return (result.stdout + result.stderr).strip()

    with tempfile.TemporaryDirectory(prefix='compile-', dir=build) as temporary:
        work = Path(temporary)
        classes, tests = work / 'classes', work / 'tests'
        classes.mkdir()
        tests.mkdir()
        sources = sorted(str(p) for p in (root / 'src/main/java').rglob('*.java'))
        test_sources = sorted(str(p) for p in (root / 'src/test/java').rglob('*.java'))
        run([javac, '--release', '17', '-Xlint:all', '-Werror', '-d', str(classes), *sources])
        temporary_jar = work / 'evidence-contract.jar'
        run([jar, '--create', '--file', str(temporary_jar), '-C', str(classes), '.'])
        # Compile and execute the consumer against the JAR, not source/classes on a shared classpath.
        run([javac, '--release', '17', '-Xlint:all', '-Werror', '-cp', str(temporary_jar),
             '-d', str(tests), *test_sources])
        outcome = run([java, '-cp', os.pathsep.join((str(temporary_jar), str(tests))),
                       'io.jjamtong.evidence.ContractTest'])
        artifact = build / 'evidence-contract.jar'
        shutil.copyfile(temporary_jar, artifact)
        report = {'java': run([java, '-version']), 'javac': run([javac, '-version']),
                  'release': 17, 'tests': outcome, 'external_dependencies': [],
                  'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}
        (build / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        print(outcome)
        print(f'JAR {artifact.name} SHA256 {report["artifact_sha256"]}')


if __name__ == '__main__':
    main()
