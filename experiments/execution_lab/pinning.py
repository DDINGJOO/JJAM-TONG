#!/usr/bin/env python3
"""Run one identical Java 21 class on explicit JDK 21 and JDK 24+ installations."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)


def compare(java21, java_new, output):
    source = Path(__file__).with_name('PinningProbe.java')
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='pinning-') as temporary:
        classes = Path(temporary) / 'classes'
        classes.mkdir()
        run([str(java21 / 'bin/javac'), '--release', '21', '-Xlint:all', '-Werror',
             '-d', str(classes), str(source)])
        class_file = classes / 'io/jjamtong/experiment/PinningProbe.class'
        class_digest = hashlib.sha256(class_file.read_bytes()).hexdigest()
        for label, java_home in [('jdk21', java21), ('jdk24plus', java_new)]:
            version = run([str(java_home / 'bin/java'), '-version'])
            record_directory = (output / label).resolve()
            result = run([str(java_home / 'bin/java'),
                          '-Djdk.virtualThreadScheduler.parallelism=1',
                          '-Djdk.virtualThreadScheduler.maxPoolSize=1',
                          '-cp', str(classes), 'io.jjamtong.experiment.PinningProbe',
                          str(record_directory)])
            cases = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            assert len(cases) == 2, result.stdout
            unlocked, monitor = cases
            assert unlocked['case'] == 'unlocked-control' and monitor['case'] == 'monitor-sleep'
            assert all(case['virtualThreadStarts'] == case['virtualThreadEnds'] == case['tasks']
                       for case in cases), cases
            assert unlocked['monitorPinnedEvents'] == 0, unlocked
            if label == 'jdk21':
                assert monitor['monitorPinnedEvents'] > 0, 'JDK21 positive control missing'
            else:
                assert monitor['monitorPinnedEvents'] == 0, 'Monitor pinning observed on newer JDK'
            recordings = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(record_directory.glob('*.jfr'))}
            assert len(recordings) == 2
            results.append({'label': label, 'java_version': (version.stdout + version.stderr).strip(),
                            'cases': cases, 'recording_sha256': recordings})
    report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'host_platform': platform.platform(),
              'class_sha256': class_digest, 'compile_release': 21,
              'scheduler_parallelism': 1, 'scheduler_max_pool_size': 1,
              'jfr_event': 'jdk.VirtualThreadPinned', 'threshold_millis': 0,
              'lifecycle_events': ['jdk.VirtualThreadStart', 'jdk.VirtualThreadEnd'],
              'runs': results,
              'limitations': ['Controlled synchronized plus sleep input only',
                              'No production load or throughput comparison',
                              'No event is not proof of absence of every source of pinning',
                              'JVM distribution and version differ; no single-factor benchmark']}
    (output / 'pinning-results.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java21', type=Path, required=True)
    parser.add_argument('--java-new', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('results/execution-pinning'))
    args = parser.parse_args()
    print(json.dumps(compare(args.java21.resolve(), args.java_new.resolve(), args.output), indent=2))


if __name__ == '__main__':
    main()
