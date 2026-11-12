#!/usr/bin/env python3
"""Local, synthetic Java method comparison. Never touches running app containers.

Build and analyze the external fixture first (see METHOD-OBSERVABILITY-RESULTS.md).
Each command/result remains in ignored output. Successful existing cases may be
resumed only with the same command, artifact and telemetry config fingerprints.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.method_evidence.evidence import (RESOURCE_KEYS, digest, file_digest, load_index,
                                             query, read_otlp)

AGENT_SHA = "e43a270df53c6f423e0ab157be9c27ccc01d5dc3232e162fe54777573db2f149"


def methods_option(oracle, performance=False):
    classes = {}
    for item in oracle["methodCatalog"].values():
        if not item["class"].startswith("fixture.board.") or item["method"] == "nativeProbe":
            continue
        # Selecting both an interface and its implementation applies two method
        # instrumenters to one body in this agent; select concrete bodies once.
        if item["class"] == "fixture.board.Repository":
            continue
        if performance and item["method"] == "main":
            continue
        classes.setdefault(item["class"], set()).add(item["method"])
    return ";".join(name + "[" + ",".join(sorted(values)) + "]" for name, values in sorted(classes.items()))


def java_command(java, agent, artifact, identity, mode, oracle, performance=False, control=None):
    settings = {"otel.traces.sampler": "always_on", "otel.traces.exporter": "logging-otlp",
                "otel.metrics.exporter": "none", "otel.logs.exporter": "none",
                "otel.bsp.max.queue.size": "8192", "otel.bsp.max.export.batch.size": "512",
                "otel.bsp.schedule.delay": "100", "otel.service.name": "synthetic-method-fixture",
                "otel.instrumentation.jdbc.query-sanitization.enabled": "true",
                "otel.instrumentation.jdbc.experimental.capture-query-parameters": "false",
                "otel.instrumentation.jdbc.experimental.sqlcommenter.enabled": "false"}
    if mode == "selected":
        settings["otel.instrumentation.methods.include"] = methods_option(oracle, performance)
    if control == "always-off":
        settings["otel.traces.sampler"] = "always_off"
    if control == "executor-disabled":
        settings["otel.instrumentation.executors.enabled"] = "false"
    config = digest({"agent": "2.33.1" if mode != "none" else None, "settings": settings,
                     "performance": performance})
    resources = dict(identity, configSha256=config)
    settings["otel.resource.attributes"] = ",".join(RESOURCE_KEYS[key] + "=" + value for key, value in resources.items())
    command = [str(java), "-Xms32m", "-Xmx256m"]
    if mode != "none":
        command += ["-javaagent:" + str(agent)] + ["-D" + key + "=" + value for key, value in sorted(settings.items())]
    return command + ["-jar", str(artifact)], config, settings


def run_process(command, directory, timeout=60):
    directory.mkdir(parents=True, exist_ok=True)
    metrics = directory / "process-metrics.txt"
    actual = (["/usr/bin/time", "-l", "-o", str(metrics)] + command) if platform.system() == "Darwin" else command
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("OTEL_") and key not in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS")}
    started = time.monotonic()
    with (directory / "stdout.jsonl").open("w") as stdout, (directory / "telemetry.log").open("w") as stderr:
        process = subprocess.Popen(actual, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    elapsed = time.monotonic() - started
    if returncode:
        raise RuntimeError("Fixture exited " + str(returncode) + "; inspect " + str(directory))
    rss = None
    if metrics.exists():
        for line in metrics.read_text().splitlines():
            if "maximum resident set size" in line:
                rss = int(line.split()[0])  # macOS bytes; not Linux time's KiB.
    return {"wallSeconds": elapsed, "maxRssBytes": rss, "rssMeasurement": "macOS /usr/bin/time -l" if rss else "unavailable"}


def validate_outcomes(lines, expected, count):
    values = [json.loads(line) for line in lines.splitlines() if line.strip()]
    if len(values) != count:
        raise AssertionError("Business outcome count differs")
    for item in values:
        if any(item.get(key) != value for key, value in expected["expectedOutcome"].items()):
            raise AssertionError("Agent changed business outcome")
        if not isinstance(item.get("elapsedNanos"), int) or item["elapsedNanos"] < 0:
            raise AssertionError("Missing in-process timing")
    return values


def runtime_oracle(collection, expected, index, telemetry_config):
    spans = collection["spans"]
    if not spans:
        raise AssertionError("Selected instrumentation returned no spans")
    by_id = {(item["traceId"], item["spanId"]): item for item in spans}
    pairs = [(by_id.get((item["traceId"], item["parentSpanId"])), item) for item in spans if item["parentSpanId"]]

    def matches(span, method):
        return span and (span["class"], span["method"]) == (method["class"], method["method"])

    checked = []
    for edge in expected["requiredEdges"]:
        occurrences = sum(matches(parent, edge["caller"]) and matches(child, edge["callee"]) for parent, child in pairs)
        if occurrences < edge.get("minimumOccurrences", 1):
            raise AssertionError("Missing observed context relation: " + json.dumps(edge))
        checked.append({"caller": edge["caller"], "callee": edge["callee"], "oracleRelation": edge["relation"],
                        "observedRelation": "span-parent", "descriptorAssurance": "not emitted by agent"})
    unverified_forbidden = []
    for method in expected.get("forbiddenRuntimeMethods", []):
        if any(matches(span, method) for span in spans):
            possible = [item for item in index["methods"] if
                        (item["class"], item["name"]) == (method["class"], method["method"])]
            if len(possible) > 1:
                unverified_forbidden.append({"method": method, "reason": "UNRESOLVED_CODE_SYMBOL; overload has no emitted descriptor"})
            else:
                raise AssertionError("Unexecuted or out-of-scope method incorrectly observed")
    for edge in expected.get("forbiddenRuntimeEdges", []):
        if any(matches(parent, edge["caller"]) and matches(child, edge["callee"]) for parent, child in pairs):
            raise AssertionError("Forbidden runtime relation observed")
    for invocation in expected.get("runtimeInvocationCounts", []):
        if sum(matches(span, invocation["method"]) for span in spans) != invocation["count"]:
            raise AssertionError("Runtime invocation instances differ")
    for method in expected.get("expectedErrorMethods", []):
        if not any(matches(span, method) and span["error"] for span in spans):
            raise AssertionError("Thrown exception lost its error span")
    expected_methods = {(method["class"], method["method"], method["descriptor"])
                        for edge in expected["requiredEdges"] for method in (edge["caller"], edge["callee"])}
    expected_count = len(expected_methods) + sum(item["count"] - 1
                                                for item in expected.get("runtimeInvocationCounts", []))
    if len(spans) != expected_count:
        raise AssertionError("Collected span count differs from independent invocation oracle")
    traces = sorted({item["traceId"] for item in spans})
    if len(traces) != 1:
        raise AssertionError("Positive context propagation produced disconnected traces")
    results = [query(index, collection, trace, telemetry_config) for trace in traces]
    if any(value["status"] != "OBSERVED" for value in results):
        raise AssertionError("Runtime build/config join failed")
    unresolved = [span for result in results for span in result["spans"]
                  if span["symbolStatus"] == "UNRESOLVED_CODE_SYMBOL"]
    return {"spanCount": len(spans), "expectedSpanCount": expected_count, "traceCount": len(traces), "checkedRelations": checked,
            "unresolvedSymbols": [{"class": item["class"], "method": item["method"],
                                   "candidates": item["symbolCandidates"]} for item in unresolved],
            "errorSpanCount": sum(item["error"] for item in spans),
            "unverifiedForbiddenMethods": unverified_forbidden,
            "descriptorComplete": not unresolved and not unverified_forbidden, "queries": results}


def execute_case(case, args, oracle):
    java_name, build, mode, scenario, performance, repetition, control = case
    java = Path(args.java[java_name]) / "bin/java"
    artifact_dir = Path(args.artifacts) / build
    manifest = json.loads((artifact_dir / "identity.json").read_text())
    identity = {key: manifest[key] for key in ("repository", "revision", "build", "module", "artifactSha256")}
    artifact = artifact_dir / "method-fixture.jar"
    if file_digest(artifact) != identity["artifactSha256"]:
        raise AssertionError("Artifact changed after analysis")
    index = load_index(args.store, build + "-jdk" + java_name)
    if index is None:
        raise AssertionError("Missing explicitly requested static history")
    command, config, settings = java_command(java, args.agent, artifact, identity, mode, oracle, performance, control)
    command += ["--scenario", scenario]
    if performance:
        command += ["--warmup", "100", "--iterations", "1000"]
    case_id = "-".join([java_name, build, mode, scenario, "cost" + str(repetition) if performance else control or "function"])
    directory = Path(args.output) / case_id
    fingerprint = digest({"command": command, "artifact": identity["artifactSha256"],
                          "index": index["indexSha256"], "oracle": oracle})
    result_path = directory / "result.json"
    cached = None
    if result_path.exists():
        cached = json.loads(result_path.read_text())
        if cached["fingerprint"] != fingerprint:
            raise ValueError("Refusing to reuse different case inputs: " + case_id)
        if json.loads((directory / "command.json").read_text()) != command:
            raise ValueError("Stored command changed: " + case_id)
        hashes = {name: file_digest(directory / name) for name in ("stdout.jsonl", "telemetry.log")}
        if cached.get("evidenceFilesSha256") and hashes != cached["evidenceFilesSha256"]:
            raise ValueError("Stored raw evidence changed: " + case_id)
    metrics = cached["metrics"] if cached else run_process(command, directory)
    expected = oracle["variants"][manifest["variant"]]["scenarios"][scenario]
    values = validate_outcomes((directory / "stdout.jsonl").read_text(), expected, 1000 if performance else 1)
    collection = read_otlp(directory / "telemetry.log")
    if collection["collectionReasons"]:
        raise AssertionError("Unexpected output loss: " + str(collection["collectionReasons"]))
    result = {"case": case_id, "fingerprint": fingerprint, "java": java_name,
              "javaVersion": subprocess.check_output([str(java), "-version"], stderr=subprocess.STDOUT, text=True).strip(),
              "buildIdentity": identity, "variant": manifest["variant"], "mode": mode, "scenario": scenario,
              "telemetryConfigSha256": config, "settings": settings, "performance": performance,
              "control": control, "businessOutcomesUnchanged": True, "outcomeCount": len(values),
              "executionReused": cached is not None,
              "evidenceFilesSha256": {name: file_digest(directory / name) for name in ("stdout.jsonl", "telemetry.log")},
              "validatorSha256": digest({"runner": file_digest(__file__),
                                         "contract": file_digest(ROOT / "tools/method_evidence/evidence.py")}),
              "metrics": metrics, "rawTelemetryBytes": (directory / "telemetry.log").stat().st_size,
              "parsedSpanCount": len(collection["spans"])}
    if performance:
        timings = [item["elapsedNanos"] for item in values]
        ordered = sorted(timings)
        result["latency"] = {"samplesNanos": timings, "medianNanos": statistics.median(timings),
                             "p95Nanos": ordered[int(len(ordered) * .95) - 1],
                             "loopOperationsPerSecond": 1e9 * len(timings) / sum(timings) if sum(timings) else None,
                             "zeroDurationSamples": timings.count(0),
                             "warmup": 100, "measurement": 1000,
                             "scope": "in-process scenario call, excludes startup and shutdown exporter drain"}
        if mode == "selected":
            result["expectedSpansIncludingWarmup"] = 4400
            if len(collection["spans"]) != 4400 or len({s["traceId"] for s in collection["spans"]}) != 1100:
                raise AssertionError("Cost run exporter count differs from independent normal-call oracle")
        elif collection["spans"]:
            raise AssertionError("Unexpected application method spans in baseline")
    elif mode == "selected" and not control:
        result["runtime"] = runtime_oracle(collection, expected, index, config)
    elif control == "always-off":
        if collection["spans"]:
            raise AssertionError("always_off emitted spans")
        result["controlledAbsenceReason"] = "SAMPLING_ALWAYS_OFF; cause known from experiment control, not inferred from empty graph"
    elif control == "executor-disabled":
        tasks = [item for item in collection["spans"] if item["class"] == "fixture.board.AsyncLookup"]
        if len(tasks) != 1 or tasks[0]["parentSpanId"]:
            raise AssertionError("Expected one task with no context after executor instrumentation disabled")
        result["controlledAbsenceReason"] = "ASYNC_PARENT_NOT_PROPAGATED; disconnected task retained, no parent guessed"
        result["disconnectedTaskTraceId"] = tasks[0]["traceId"]
    elif collection["spans"]:
        raise AssertionError("Default/none mode unexpectedly produced fixture method spans")
    (directory / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"case": case_id, "pass": True, "spans": len(collection["spans"])}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--agent", type=Path, required=True)
    parser.add_argument("--jdk17", required=True)
    parser.add_argument("--jdk21", required=True)
    parser.add_argument("--build-a", required=True)
    parser.add_argument("--build-b", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("functional", "cost"), required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        parser.error("workers must be 1..3")
    if file_digest(args.agent) != AGENT_SHA:
        parser.error("Agent checksum mismatch")
    args.java = {"17": args.jdk17, "21": args.jdk21}
    oracle = json.loads((args.target / "method-fixture/oracle.json").read_text())
    cases = []
    for java in args.java:
        if args.phase == "functional":
            for build in (args.build_a, args.build_b):
                variant = json.loads((args.artifacts / build / "identity.json").read_text())["variant"]
                for mode in ("none", "default", "selected"):
                    for scenario in oracle["variants"][variant]["scenarios"]:
                        cases.append((java, build, mode, scenario, False, 0, None))
            for control, scenario in (("always-off", "normal"), ("executor-disabled", "async")):
                cases.append((java, args.build_a, "selected", scenario, False, 0, control))
        else:
            for repetition in range(5):
                for mode in ("none", "default", "selected"):
                    cases.append((java, args.build_a, mode, "normal", True, repetition, None))
    # Functional runs are independent; cost runs stay sequential to reduce self-interference.
    if args.phase == "functional":
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda case: execute_case(case, args, oracle), cases))
    else:
        results = [execute_case(case, args, oracle) for case in cases]
    summary = {"phase": args.phase, "cases": len(results), "results": results,
               "environment": {"platform": platform.platform(), "machine": platform.machine(),
                               "cpuCount": os.cpu_count(), "heapMaxMiBPerProcess": 256,
                               "wallTimeoutSecondsPerProcess": 60,
                               "maxConcurrentProcesses": args.workers if args.phase == "functional" else 1}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / (args.phase + "-results.json")).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"phase": args.phase, "passed": len(results)}))


if __name__ == "__main__":
    main()
