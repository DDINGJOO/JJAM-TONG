"""Compare local publication contracts using generated evidence, not an analyzer."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import tracemalloc

from .model import Budget
from .publication import OutputLimit, iter_bundle, iter_single, publish_bundle, publish_single

STAGES = ("inventory", "relations")
KEY = hashlib.sha256(b"synthetic-analysis-job-input-v1").hexdigest()
ATTEMPT = "attempt-a"


def evidence(stage, count):
    for number in range(count):
        record = {"ordinal": number, "module": "synthetic-community", "method": "BoardService.method" + str(number),
                  "source": "example/board/BoardService.java", "line": number + 1,
                  "descriptor": "(Ljava/lang/String;)Ljava/lang/String;", "syntheticPayload": "x" * 128}
        if stage == "relations":
            record.update(kind=("declared-call", "cha-candidate", "observed-call", "unresolved")[number % 4],
                          target="Repository.method" + str(number))
        else:
            record["kind"] = "method-declaration"
        yield record


def digest_records(rows):
    digest, count = hashlib.sha256(), 0
    for stage, record in rows:
        digest.update(json.dumps([stage, record], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
        count += 1
    return digest.hexdigest(), count


def worker(output, variant, count):
    budget = Budget(max_total_bytes=32 * 1024 * 1024,
                    max_file_bytes=(32 if variant == "single-expanded" else 10) * 1024 * 1024)
    stages = {stage: evidence(stage, count) for stage in STAGES}
    started = time.perf_counter()
    tracemalloc.start()
    try:
        publisher = publish_bundle if variant == "bundle" else publish_single
        summary = publisher(output, KEY, ATTEMPT, STAGES, stages, budget)
        published = time.perf_counter()
        reader = iter_bundle if variant == "bundle" else iter_single
        digest, records = digest_records(reader(output, KEY, ATTEMPT, STAGES, budget))
        result = {"status": "complete", "publishSeconds": published - started,
                  "verifyAndConsumeSeconds": time.perf_counter() - published,
                  "recordDigest": digest, "records": records, **summary}
    except OutputLimit:
        result = {"status": "output-limit", "publishSeconds": time.perf_counter() - started,
                  "newCompletionPublished": (output / "complete.json").exists() or (output / "result.jsonl").exists()}
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result.update(budget=asdict(budget), pythonPeakAllocatedBytes=peak)
    try:
        import resource
        result["processMaxRssBytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform.startswith("linux") else 1)
    except ImportError:
        result["processMaxRssBytes"] = None
    return result


def _case(command, output, timeout):
    started = time.perf_counter()
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "deadline-exceeded", "wallSeconds": time.perf_counter() - started,
                "deadlineSeconds": timeout, "completionMarkerObserved":
                (output / "complete.json").exists() or (output / "result.jsonl").exists(),
                "verification": "not-performed"}
    if run.returncode:
        return {"status": "worker-failed", "returncode": run.returncode,
                "wallSeconds": time.perf_counter() - started, "verification": "not-performed",
                "completionMarkerObserved": (output / "complete.json").exists() or (output / "result.jsonl").exists()}
    return json.loads(run.stdout)


def compare(output, records_per_stage, timeout=180, commands=None):
    """Each case retains its outcome even if another worker exceeds its deadline."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    expected, count = digest_records((stage, record) for stage in STAGES for record in evidence(stage, records_per_stage))
    result = {"schema": "jjamtong.analysis-job-comparison.v1", "synthetic": True,
              "scope": "Local publication and verification only; no Java/DB/CI integration or enterprise capacity claim.",
              "environment": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
              "expectedRecordDigest": expected, "expectedRecords": count, "cases": {}}
    for variant in ("single", "bundle", "single-expanded"):
        command = [sys.executable, "-m", "experiments.analysis_job_lab.run", "--worker", variant,
                   "--records-per-stage", str(records_per_stage), "--output", str(output / variant)]
        if commands and variant in commands:
            command = commands[variant]
        value = _case(command, output / variant, timeout)
        if value["status"] == "complete":
            if value["recordDigest"] != expected or value["records"] != count:
                raise ValueError("published evidence differs from the independent input stream")
        elif value["status"] == "output-limit" and value["newCompletionPublished"]:
            raise ValueError("failed attempt published a completion marker")
        result["cases"][variant] = value
        (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
        print(variant, value["status"], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--records-per-stage", type=int, default=30000)
    parser.add_argument("--worker", choices=("single", "single-expanded", "bundle"))
    args = parser.parse_args()
    if not 1 <= args.records_per_stage <= 100000:
        parser.error("records per stage must be between 1 and 100000")
    output = args.output.resolve()
    if args.worker:
        output.mkdir(parents=True, exist_ok=False)
        print(json.dumps(worker(output, args.worker, args.records_per_stage)))
    else:
        compare(output, args.records_per_stage)


if __name__ == "__main__":
    main()
