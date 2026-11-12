#!/usr/bin/env python3
"""Closed-loop local HTTP comparison, preserving failed requests and raw evidence.

Only --run launches containers. Existing output is immutable evidence: resume
remaining cases with --only-case; --summarize revalidates hashes and raw records.
The baseline still contains version-contract/manual probes. This is not the cost
of removing all JJAM instrumentation, a fixed-arrival test, or a capacity/SLO test.
"""
import argparse
from collections import Counter
import datetime
import hashlib
import http.client
import json
import math
from pathlib import Path
import platform
import queue
import re
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.execution_agent_smoke import AGENT_SHA, BUILD_KEYS, METHODS, digest, file_digest, properties


TARGET_REVISION = "1707e7c9e01e19d52bb90fbf13cb70414d5d7a6d"
MODELS = {"mvc-platform": ("execution-mvc", "mp"), "mvc-virtual": ("execution-mvc", "mv"),
          "netty": ("execution-netty", "nt")}
ARMS = ("none", "default", "selected")
PORT = 28380
LOG_LIMIT = 256 * 1024 * 1024
PHASE_TIMEOUT = 90
QUIET_SECONDS = .5
RESOURCE_SHELL = """printf 'CPU_STAT\n'; cat /sys/fs/cgroup/cpu.stat
printf 'MEMORY_CURRENT\n'; cat /sys/fs/cgroup/memory.current
printf 'PROCESS_STATUS\n'; cat /proc/1/status
printf 'PROCESS_COMM\n'; cat /proc/1/comm
printf 'CPU_MAX\n'; cat /sys/fs/cgroup/cpu.max
"""


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def cmd(parts, timeout=30, check=True):
    result = subprocess.run([str(x) for x in parts], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # Do not expose command environments, SQL, or arbitrary Docker output.
        raise RuntimeError("Local command failed: " + str(parts[0]) + " exit=" + str(result.returncode))
    return result


def containers():
    return sorted(cmd(["docker", "ps", "--format", "{{.ID}} {{.Names}}"] ).stdout.splitlines())


def script_hashes():
    return {"runner": file_digest(Path(__file__)),
            "sharedUtilities": file_digest(ROOT / "experiments/execution_agent_smoke.py")}


def nearest_rank(values, fraction):
    if not 0 < fraction <= 1: raise ValueError("Quantile must be in (0,1]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)] if ordered else None


def latency_summary(rows, wall_ns):
    completed = [r for r in rows if r["status"] is not None]
    successful = [r for r in rows if r["status"] == 201 and r["validationError"] is None]
    offered = [r for r in rows if r["sent"]]
    def quantiles(items):
        values = [r["latencyNs"] for r in items]
        return {"count": len(values), **{label: nearest_rank(values, q) for label, q in
                                         (("p50Ns", .5), ("p95Ns", .95), ("p99Ns", .99))}}
    return {"planned": len(rows), "offered": len(offered), "completedResponses": len(completed),
            "completedAttempts": sum(r["sent"] and r["latencyNs"] is not None for r in rows),
            "successful": len(successful), "errors": len(rows) - len(successful),
            "statusCounts": dict(sorted(Counter(str(r["status"]) if r["status"] is not None else "NO_RESPONSE" for r in rows).items())),
            "validationErrors": dict(sorted(Counter(r["validationError"] for r in rows if r["validationError"]).items())),
            "allCompletedResponseLatency": quantiles(completed), "successfulResponseLatency": quantiles(successful),
            "httpWallNs": wall_ns, "successfulGoodputPerSecond": len(successful) * 1e9 / wall_ns if wall_ns else None,
            "latencyDefinition": "HTTP request through complete response read; validation and JSONL recording excluded; no-response attempts retained separately"}


def parse_resource(text, before_ns, after_ns):
    sections, current = {}, None
    for line in text.splitlines():
        if line in {"CPU_STAT", "MEMORY_CURRENT", "PROCESS_STATUS", "PROCESS_COMM", "CPU_MAX"}:
            current = line; sections[current] = []
        elif current: sections[current].append(line)
    cpu = {k: int(v) for k, v in (line.split() for line in sections["CPU_STAT"])}
    status = dict(line.split(":", 1) for line in sections["PROCESS_STATUS"] if ":" in line)
    return {"beforeNs": before_ns, "afterNs": after_ns, "readWallNs": after_ns - before_ns,
            "cpuStat": cpu, "memoryCurrentBytes": int(sections["MEMORY_CURRENT"][0]),
            "vmRssBytes": int(status["VmRSS"].split()[0]) * 1024,
            "vmHwmBytes": int(status["VmHWM"].split()[0]) * 1024,
            "pid1Comm": sections["PROCESS_COMM"][0], "cpuMax": sections["CPU_MAX"][0]}


def snapshot(container):
    before = time.perf_counter_ns()
    result = cmd(["docker", "exec", container, "sh", "-c", RESOURCE_SHELL], timeout=10)
    return parse_resource(result.stdout, before, time.perf_counter_ns())


def cpu_window(start, end, completed, successful):
    first, last = start["cpuStat"], end["cpuStat"]
    delta = {key: last[key] - first[key] for key in ("usage_usec", "nr_periods", "nr_throttled", "throttled_usec")}
    if any(value < 0 for value in delta.values()): raise AssertionError("CPU counter decreased within one fresh container")
    bracket = end["afterNs"] - start["beforeNs"]
    if bracket <= 0: raise AssertionError("Nonpositive resource wall bracket")
    return {"counterDeltas": delta, "measurementBracketWallNs": bracket,
            "averageCoresInBracket": delta["usage_usec"] * 1000 / bracket,
            "cpuMsPerCompletedResponse": delta["usage_usec"] / 1000 / completed if completed else None,
            "cpuMsPerSuccessfulResponse": delta["usage_usec"] / 1000 / successful if successful else None,
            "denominator": {"completedResponses": completed, "successfulResponses": successful},
            "boundary": "cgroup snapshots bracket both docker-exec reads; app cgroup includes sampler shell/cat overhead"}


class Sampler:
    def __init__(self, container):
        self.container, self.rows, self.errors = container, [], []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="resource-sampler", daemon=True)

    def loop(self):
        while not self.stop_event.wait(1):
            try: self.rows.append(snapshot(self.container))
            except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError) as error:
                self.errors.append(type(error).__name__)

    def __enter__(self):
        self.thread.start(); return self

    def __exit__(self, *_):
        self.stop_event.set(); self.thread.join(12)
        if self.thread.is_alive(): raise RuntimeError("Resource sampler did not stop")


def one_request(connection, index, phase, mode, delay):
    event_id, trace_id, parent_id = str(uuid.uuid4()), uuid.uuid4().hex, uuid.uuid4().hex[:16]
    parent = "00-" + trace_id + "-" + parent_id + "-01"
    row = {"id": index, "phase": phase, "eventId": event_id, "traceId": trace_id, "parentSpanId": parent_id,
           "sent": True, "latencyNs": None, "status": None, "validationError": None}
    body = json.dumps({"delayMillis": delay, "retryFailures": 0, "dropHeader": False,
                       "failAfterInsert": False, "eventId": event_id})
    start = time.perf_counter_ns()
    try:
        connection.request("POST", "/probe/requests", body, {"Content-Type": "application/json", "traceparent": parent})
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        row["latencyNs"] = time.perf_counter_ns() - start
        row["status"] = response.status
        if response.status != 201: row["validationError"] = "HTTP_" + str(response.status)
        elif len(raw) > 1024 * 1024: row["validationError"] = "RESPONSE_BOUND_EXCEEDED"
        else:
            value = json.loads(raw)
            if value.get("redisRoundTrip") is not True: row["validationError"] = "REDIS_ROUND_TRIP_FALSE"
            elif value.get("eventId") != event_id: row["validationError"] = "EVENT_ID_MISMATCH"
            elif value.get("mode") != mode: row["validationError"] = "MODE_MISMATCH"
            elif value.get("traceparent") != parent: row["validationError"] = "MANUAL_CARRIER_MISMATCH"
    except (OSError, http.client.HTTPException, ValueError) as error:
        row["latencyNs"] = time.perf_counter_ns() - start
        row["validationError"] = type(error).__name__
        connection.close()
    return row


def load_phase(path, phase, count, workers, mode, delay):
    jobs = queue.Queue()
    for index in range(count): jobs.put(index)
    lock, stop, rows, connections = threading.Lock(), threading.Event(), [], []
    started = time.perf_counter_ns()
    deadline = time.monotonic() + PHASE_TIMEOUT
    with path.open("x") as stream:
        def work():
            connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
            with lock: connections.append(connection)
            try:
                while not stop.is_set() and time.monotonic() < deadline:
                    try: index = jobs.get_nowait()
                    except queue.Empty: return
                    connection.timeout = max(.05, min(10, deadline - time.monotonic()))
                    row = one_request(connection, index, phase, mode, delay)
                    with lock:
                        rows.append(row); stream.write(json.dumps(row, sort_keys=True) + "\n"); stream.flush()
            finally: connection.close()
        threads = [threading.Thread(target=work, name="load-" + str(i), daemon=True) for i in range(workers)]
        try:
            for thread in threads: thread.start()
            for thread in threads: thread.join(max(0, deadline - time.monotonic()))
        finally:
            stop.set()
            for connection in connections:
                if connection.sock:
                    try: connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                connection.close()
            for thread in threads: thread.join(2)
            if any(thread.is_alive() for thread in threads): raise RuntimeError("Load worker did not stop")
        completed_ids = {r["id"] for r in rows}
        for index in range(count):
            if index not in completed_ids:
                row = {"id": index, "phase": phase, "eventId": None, "traceId": None, "parentSpanId": None,
                       "sent": False, "latencyNs": None, "status": None, "validationError": "NOT_SENT_PHASE_DEADLINE"}
                rows.append(row); stream.write(json.dumps(row, sort_keys=True) + "\n")
    wall = time.perf_counter_ns() - started
    return rows, latency_summary(rows, wall)


def owned_snapshot(postgres, mode):
    if not re.fullmatch(r"[a-z0-9-]{1,32}", mode): raise ValueError("Unsafe owned mode")
    # Scope is immutable, randomly unique, and syntax checked. This command is
    # READ ONLY and never changes a table, offset, or unrelated mode.
    sql = """BEGIN READ ONLY; SELECT json_build_object(
      'outboxRows',COALESCE((SELECT json_agg(json_build_object('eventId',event_id::text,'published',published,'publishAttempts',publish_attempts)) FROM execution_probe_outbox WHERE run_mode='%s'),'[]'::json),
      'effectRows',COALESCE((SELECT json_agg(json_build_object('eventId',event_id::text,'appliedCount',applied_count)) FROM execution_probe_effects WHERE run_mode='%s'),'[]'::json),
      'cleanEventIds',COALESCE((SELECT json_agg(DISTINCT event_id::text) FROM execution_probe_observations WHERE run_mode='%s' AND stage='request-clean'),'[]'::json),
      'attemptCounts',COALESCE((SELECT json_object_agg(outcome,n) FROM (SELECT outcome,count(*) n FROM execution_probe_attempts WHERE run_mode='%s' GROUP BY outcome) x),'{}'::json)); COMMIT;""" % (mode, mode, mode, mode)
    raw = cmd(["docker", "exec", postgres, "psql", "-X", "-qAt", "-U", "lab", "-d", "board", "-c", sql], timeout=10).stdout
    return json.loads(raw)


def drain_oracle(state, rows):
    sent = {r["eventId"] for r in rows if r["sent"]}
    accepted = {r["eventId"] for r in rows if r["status"] == 201 and not r["validationError"]}
    outbox = {r["eventId"]: r for r in state["outboxRows"]}
    effects = {r["eventId"]: r["appliedCount"] for r in state["effectRows"]}
    unknown = (set(outbox) | set(effects)) - sent
    if unknown: raise AssertionError("Owned mode contains an event not sent by this case")
    if any(v != 1 for v in effects.values()): raise AssertionError("Owned event business effect is not exactly one")
    expected_commits = {r["eventId"] for r in rows if r["status"] == 201}
    # A disconnected caller may finish before its DB transaction. A missing
    # outbox row alone cannot prove the timed-out request has stopped executing.
    unresolved = {r["eventId"] for r in rows if r["sent"] and r["status"] is None} - set(state["cleanEventIds"])
    attempts = state["attemptCounts"]
    complete = (expected_commits <= set(outbox) and set(outbox) == set(effects)
                and all(r["published"] for r in outbox.values()) and not unresolved
                and attempts.get("applied", 0) >= len(outbox))
    return {"complete": complete, "sent": len(sent), "accepted": len(accepted), "outbox": len(outbox),
            "published": sum(r["published"] for r in outbox.values()), "effectsExactlyOnce": len(effects),
            "missingAccepted": sorted(accepted - set(effects)),
            "unacknowledgedCommitted": sorted(set(outbox) - accepted),
            "unresolvedSentRequestIds": sorted(unresolved),
            "attemptCounts": state["attemptCounts"],
            "expectedAttemptOutcomes": (attempts.get("applied", 0) == len(outbox)
                                        and not any(n for outcome, n in attempts.items() if outcome != "applied")),
            "lastSentinelEventId": next((r["eventId"] for r in reversed(rows) if r["status"] == 201 and not r["validationError"]), None),
            "allSentIdsInspected": True}


def drain(postgres, mode, rows, seconds=PHASE_TIMEOUT):
    start, deadline, polls = time.perf_counter_ns(), time.monotonic() + max(0, seconds), 0
    while True:
        state = owned_snapshot(postgres, mode); polls += 1
        oracle = drain_oracle(state, rows)
        if oracle["complete"] or time.monotonic() >= deadline:
            return {"wallNs": time.perf_counter_ns() - start, "polls": polls, "oracle": oracle, "snapshot": state}
        time.sleep(.25)


def measure_phase(directory, phase, count, workers, case, container, postgres, all_rows, delay):
    deadline = time.monotonic() + PHASE_TIMEOUT
    start = snapshot(container)
    with Sampler(container) as sampler:
        rows, latency = load_phase(directory / (phase + "-latency.jsonl"), phase, count, workers, case["mode"], delay)
        http_end = snapshot(container)
        all_rows.extend(rows)
        drained = drain(postgres, case["mode"], all_rows, seconds=deadline - time.monotonic())
        drain_end = snapshot(container)
        time.sleep(QUIET_SECONDS)
        completion_end = snapshot(container)
    snapshots = [start, http_end, drain_end, completion_end, *sampler.rows]
    metrics = {"phase": phase, "workers": workers, "latency": latency, "drain": drained,
               "resources": {"start": start, "httpEnd": http_end, "drainEnd": drain_end, "completionEnd": completion_end,
                             "samples": sampler.rows, "samplerErrors": sampler.errors,
                             "httpWindow": cpu_window(start, http_end, latency["completedResponses"], latency["successful"]),
                             "completionWindow": cpu_window(start, completion_end, latency["completedResponses"], latency["successful"]),
                             "quietTailWindow": cpu_window(drain_end, completion_end, latency["completedResponses"], latency["successful"]),
                             "sampledVmRssPeakBytes": max(s["vmRssBytes"] for s in snapshots),
                             "sampledCgroupMemoryPeakBytes": max(s["memoryCurrentBytes"] for s in snapshots),
                             "processLifetimeVmHwmBytes": completion_end["vmHwmBytes"],
                             "resourceReadCount": len(snapshots), "resourceReadWallNs": sum(s["readWallNs"] for s in snapshots)},
               "completionWallNs": completion_end["afterNs"] - start["beforeNs"],
               "successfulCompletionGoodputPerSecond": latency["successful"] * 1e9 / (completion_end["afterNs"] - start["beforeNs"]),
               "quietTailSeconds": QUIET_SECONDS,
               "completionBoundary": "owned outbox/effects drained then fixed quiet tail; exporter queue emptiness not proved; shutdown flush separate"}
    write_json(directory / (phase + ".json"), metrics)
    return metrics


def telemetry_summary(path, case, identity, rows, complete_log=True):
    expected = {r["traceId"] for r in rows if r["status"] == 201 and not r["validationError"]}
    expected_parents = {(r["traceId"], r["parentSpanId"]) for r in rows if r["status"] == 201 and not r["validationError"]}
    scopes, http, creates, method_count, total, versions = Counter(), set(), set(), 0, 0, set()
    with path.open("rb") as stream:
        consumed = 0
        for raw in stream:
            consumed += len(raw)
            if consumed > LOG_LIMIT: raise AssertionError("Telemetry exceeds bounded raw input")
            start = raw.find(b"{")
            if start < 0: continue
            try: value = json.loads(raw[start:])
            except (ValueError, UnicodeDecodeError): continue
            if not isinstance(value, dict) or "scopeSpans" not in value: continue
            attrs = {a["key"]: a.get("value", {}).get("stringValue") for a in value.get("resource", {}).get("attributes", [])}
            for key, resource in BUILD_KEYS.items():
                if attrs.get(resource) != identity[key]: raise AssertionError("Telemetry artifact identity mismatch")
            if attrs.get("jjamtong.config.sha256") != case["agentConfigSha256"]: raise AssertionError("Telemetry configuration identity mismatch")
            versions.add((attrs.get("telemetry.distro.version"), attrs.get("telemetry.sdk.version"), attrs.get("process.runtime.version")))
            for group in value["scopeSpans"]:
                scope = group.get("scope", {}).get("name", "unknown")
                for span in group.get("spans", []):
                    total += 1; scopes[scope] += 1
                    trace = span.get("traceId")
                    if span.get("kind") == 2 and (trace, span.get("parentSpanId")) in expected_parents: http.add(trace)
                    if scope == "io.opentelemetry.methods":
                        method_count += 1
                        a = {v["key"]: v.get("value", {}).get("stringValue") for v in span.get("attributes", [])}
                        if a.get("code.namespace") == "io.jjamtong.sandbox.execution.ProbeService" and a.get("code.function") == "create" and trace in expected:
                            creates.add(trace)
    issues = []
    if not complete_log: issues.append("RAW_LOG_TRUNCATED")
    if case["arm"] == "none":
        if total: issues.append("UNEXPECTED_AGENT_SPANS_IN_NONE")
    else:
        if not total or not http: issues.append("ZERO_AGENT_HTTP_COVERAGE")
        if expected - http: issues.append("MISSING_EXPECTED_HTTP_TRACES")
        if case["arm"] == "default" and method_count: issues.append("UNEXPECTED_METHOD_SPANS_IN_DEFAULT")
        if case["arm"] == "selected" and (not method_count or expected - creates): issues.append("MISSING_EXPECTED_SELECTED_CREATE_TRACES")
    return {"status": "PARTIAL" if issues else "EXPECTED_INPUTS_OBSERVED", "issues": issues,
            "spanCount": total, "spanCountsByScope": dict(sorted(scopes.items())), "methodSpanCount": method_count,
            "expectedSuccessfulInputs": len(expected), "observedHttpInputs": len(http), "observedSelectedCreateInputs": len(creates),
            "missingHttpTraceIds": sorted(expected - http) if case["arm"] != "none" else [],
            "missingSelectedCreateTraceIds": sorted(expected - creates) if case["arm"] == "selected" else [],
            "versions": [{"agent": a, "sdk": s, "runtime": r} for a, s, r in sorted(versions)],
            "perPhase": {phase: {"successfulInputs": sum(r["phase"] == phase and r["traceId"] in expected for r in rows),
                                  "httpInputs": sum(r["phase"] == phase and r["traceId"] in http for r in rows),
                                  "selectedCreateInputs": sum(r["phase"] == phase and r["traceId"] in creates for r in rows)}
                         for phase in sorted({r["phase"] for r in rows})},
            "coverageBoundary": "successful synthetic input trace/remote-parent correlation checked from shutdown-flushed logs; generated/queue/network losses unknown"}


def agent_settings(arm, case_id):
    if arm == "none": return {}
    values = {"otel.traces.sampler": "always_on", "otel.traces.exporter": "logging-otlp", "otel.metrics.exporter": "none",
              "otel.logs.exporter": "none", "otel.bsp.max.queue.size": "8192", "otel.bsp.max.export.batch.size": "512",
              "otel.bsp.schedule.delay": "100", "otel.service.name": "execution-performance-" + case_id,
              "otel.instrumentation.jdbc.query-sanitization.enabled": "true",
              "otel.instrumentation.jdbc.experimental.capture-query-parameters": "false",
              "otel.instrumentation.jdbc.experimental.sqlcommenter.enabled": "false"}
    if arm == "selected": values["otel.instrumentation.methods.include"] = METHODS
    return values


def configuration(args):
    return {"models": args.models.split(","), "repetitions": args.repetitions, "serialRequests": args.serial_requests,
            "parallelRequests": args.parallel_requests, "warmup": args.warmup, "delayMillis": args.delay_millis,
            "buildId": args.build_id, "cpus": 1, "memoryBytes": 512 * 1024 * 1024, "heapMinMiB": 64, "heapMaxMiB": 192,
            "port": PORT, "network": "jjamtong-sandbox_default", "phaseTimeoutSeconds": PHASE_TIMEOUT,
            "quietTailSeconds": QUIET_SECONDS, "resourceSampleIntervalSeconds": 1, "rawLogLimitBytes": LOG_LIMIT,
            "loadModel": "fixed-request closed loop; workers 1 then 4; fresh keepalive connection per worker"}


def validate_target(args, require_head=True):
    if file_digest(args.agent) != AGENT_SHA: raise AssertionError("Selected agent 2.33.1 digest mismatch")
    if require_head:
        if cmd(["git", "-C", args.target, "status", "--porcelain"]).stdout.strip(): raise AssertionError("Target working tree must be clean")
        if cmd(["git", "-C", args.target, "rev-parse", "HEAD"]).stdout.strip() != TARGET_REVISION: raise AssertionError("Target revision differs from approved fixture")
    identities, images = {}, {}
    for module in sorted({v[0] for v in MODELS.values()}):
        identity = properties(args.target / ".local/artifacts" / args.build_id / (module + ".properties"))
        if identity["revision"] != TARGET_REVISION or identity["sourceState"] != "clean": raise AssertionError("Artifact source identity differs")
        if file_digest(args.target / ".local/artifacts" / args.build_id / (module + ".jar")) != identity["artifactSha256"]:
            raise AssertionError("Actual JAR/sidecar digest mismatch")
        identities[module] = identity
        image = "jjamtong-sandbox/" + module + ":" + args.build_id
        images[module] = cmd(["docker", "image", "inspect", image, "--format", "{{.Id}}"] ).stdout.strip()
    return identities, images


def prepare(args):
    config = configuration(args)
    identities, images = validate_target(args, require_head=not args.summarize)
    path = args.output / "manifest.json"
    if path.exists():
        manifest = json.loads(path.read_text())
        if manifest["configuration"] != config or manifest["scriptSha256"] != script_hashes():
            raise AssertionError("Resume configuration/script changed; preserve this run and use a new output directory")
        if manifest["identities"] != identities or manifest["imageIds"] != images: raise AssertionError("Resume artifact/image identity changed")
        return manifest
    if args.summarize: raise ValueError("No existing manifest to summarize")
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = containers()
    if len(baseline) != 11: raise AssertionError("Expected exactly eleven baseline containers")
    info = json.loads(cmd(["docker", "info", "--format", "{{json .}}"] ).stdout)
    machine = {k: info.get(k) for k in ("ServerVersion", "OSType", "Architecture", "KernelVersion", "NCPU", "MemTotal", "CgroupVersion", "OperatingSystem")}
    machine.update({"hostSystem": platform.system(), "hostMachine": platform.machine(), "pythonVersion": platform.python_version()})
    session, cases = uuid.uuid4().hex[:8], []
    for model in config["models"]:
        for rep in range(1, args.repetitions + 1):
            order = ARMS[(rep - 1) % 3:] + ARMS[:(rep - 1) % 3]
            for arm in order:
                case_id = model + "-r" + str(rep) + "-" + arm
                settings = agent_settings(arm, case_id)
                cases.append({"id": case_id, "model": model, "repetition": rep, "arm": arm,
                              "module": MODELS[model][0], "mode": "perf-" + session + "-" + MODELS[model][1] + "-" + str(rep) + "-" + arm,
                              "otelSettings": settings, "agentConfigSha256": digest({"agentSha256": AGENT_SHA, "settings": settings})})
    manifest = {"schemaVersion": 1, "recordedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "session": session, "configuration": config, "configurationSha256": digest(config), "scriptSha256": script_hashes(),
                "agentVersion": "2.33.1", "agentSha256": AGENT_SHA, "targetRevision": TARGET_REVISION,
                "identities": identities, "imageIds": images, "machine": machine, "cases": cases, "baselineContainers": baseline,
                "limitations": ["baseline retains version-contract/manual probes; not total JJAM removal cost",
                                "closed loop, no fixed arrival, saturation, SLO, or statistical significance claim",
                                "resource exec and load-client recording overhead included; no heap/GC measurements",
                                "shared local infrastructure/background baseline may affect repeats; no host isolation",
                                "completion means DB effect drain plus fixed quiet tail, not proof of empty exporter queues"]}
    write_json(path, manifest)
    return manifest


def health():
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
    try:
        connection.request("GET", "/probe/health")
        response = connection.getresponse(); response.read()
        return response.status == 200
    except (OSError, http.client.HTTPException): return False
    finally: connection.close()


def wait_ready(container, mode):
    start, deadline, health_ns, assigned_ns = time.perf_counter_ns(), time.monotonic() + 120, None, None
    while time.monotonic() < deadline:
        if health_ns is None and health(): health_ns = time.perf_counter_ns()
        logs = cmd(["docker", "logs", "--tail", "400", container], timeout=10)
        if re.search(re.escape("execution-probe-" + mode) + r": partitions assigned: \[execution\.probe\.v1-\d", logs.stdout + logs.stderr):
            assigned_ns = time.perf_counter_ns()
        if health_ns and assigned_ns: return {"healthObservedNs": health_ns, "kafkaAssignmentObservedNs": assigned_ns, "readinessWaitStartNs": start}
        time.sleep(.25)
    raise AssertionError("Health/Kafka assignment readiness not observed")


def runtime_identity(identity, mode):
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        connection.request("GET", "/probe/runtime"); response = connection.getresponse()
        value = json.loads(response.read())
        if response.status != 200 or value["mode"] != mode: raise AssertionError("Runtime mode unavailable")
        evidence = value["buildEvidence"]
        if any(evidence["build"][k] != identity[k] for k in BUILD_KEYS) or evidence["artifactDigestVerified"] is not True:
            raise AssertionError("Runtime actual JAR/sidecar identity mismatch")
        return {k: value[k] for k in ("mode", "server", "javaVersion", "admissionLimit", "dbPool")}
    finally: connection.close()


def capture_logs(container, path):
    process = subprocess.Popen(["docker", "logs", container], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    timer = threading.Timer(60, process.kill); timer.start()
    total, truncated = 0, False
    try:
        with path.open("xb") as stream:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk: break
                room = LOG_LIMIT - total
                stream.write(chunk[:room]); total += min(room, len(chunk))
                if len(chunk) > room:
                    truncated = True; process.kill(); break
        code = process.wait(timeout=10)
        return {"bytes": total, "complete": not truncated and code == 0, "exitCode": code, "sha256": file_digest(path)}
    finally:
        timer.cancel(); timer.join(); process.stdout.close()
        if process.poll() is None: process.kill(); process.wait()


def cleanup_owned(container, container_name, labels, directory, result):
    """Delete only a verified owned container; preserve every cleanup failure."""
    failures = result.setdefault("cleanupFailures", [])
    result["removed"] = False
    result["ownershipVerified"] = False
    try:
        if container is None:
            found = cmd(["docker", "inspect", container_name, "--format", "{{.Id}}"], check=False)
            if found.returncode:
                failures.append({"stage": "ownership-inspect", "errorType": "NonzeroExit"})
                return
            container = found.stdout.strip()
        actual = json.loads(cmd(["docker", "inspect", container, "--format", "{{json .Config.Labels}}"] ).stdout)
        if any(actual.get(k) != v for k, v in labels.items()): raise AssertionError("Container ownership mismatch")
    except BaseException as error:
        result["ownershipVerified"] = False
        failures.append({"stage": "ownership-inspect", "errorType": type(error).__name__})
        return
    result["ownershipVerified"] = True
    stop_ns = time.perf_counter_ns()
    try:
        try:
            stopped = cmd(["docker", "stop", "--time", "10", container], timeout=30, check=False)
            result["stop"] = {"exitCode": stopped.returncode}
            if stopped.returncode: failures.append({"stage": "stop", "errorType": "NonzeroExit"})
        except BaseException as error:
            result["stop"] = {"exitCode": None, "errorType": type(error).__name__}
            failures.append({"stage": "stop", "errorType": type(error).__name__})
        finally:
            result["stop"].update({"wallNs": time.perf_counter_ns() - stop_ns,
                                   "boundary": "shutdown and exporter flush separate from measured phases; shutdown CPU not measured"})
    finally:
        try:
            try: result["log"] = capture_logs(container, directory / "telemetry.log")
            except BaseException as error:
                result["log"] = {"complete": False, "failureType": type(error).__name__}
                failures.append({"stage": "logs", "errorType": type(error).__name__})
        finally:
            try:
                removed = cmd(["docker", "rm", "--force", container], timeout=20, check=False)
                result["removed"] = removed.returncode == 0
                if removed.returncode: failures.append({"stage": "remove", "errorType": "NonzeroExit"})
            except BaseException as error:
                failures.append({"stage": "remove", "errorType": type(error).__name__})


def run_case(args, manifest, case):
    directory = args.output / case["id"]
    if directory.exists(): raise ValueError("Case already has immutable evidence; choose remaining --only-case IDs")
    directory.mkdir()
    write_json(directory / "case.json", case)
    container_name = "jjamtong-perf-" + manifest["session"] + "-" + case["id"]
    labels = {"jjamtong.experiment": "execution-performance", "jjamtong.session": manifest["session"], "jjamtong.case": case["id"]}
    identity = manifest["identities"][case["module"]]
    baseline, all_rows, phases, container = manifest["baselineContainers"], [], [], None
    result = {"case": case, "status": "INTERRUPTED", "phases": phases}
    postgres = next(row.split(" ", 1)[0] for row in baseline if row.endswith(" jjamtong-sandbox-postgres-1"))
    write_json(directory / "checkpoint.json", {"state": "prepared"})
    failure = None
    try:
        if containers() != baseline: raise AssertionError("Baseline container IDs changed before case")
        options = "-Xms64m -Xmx192m"
        if case["arm"] != "none":
            resources = {BUILD_KEYS[k]: identity[k] for k in BUILD_KEYS}
            resources["jjamtong.config.sha256"] = case["agentConfigSha256"]
            settings = dict(case["otelSettings"], **{"otel.resource.attributes": ",".join(k + "=" + v for k, v in resources.items())})
            options += " -javaagent:/otel/opentelemetry-javaagent.jar " + " ".join("-D" + k + "=" + v for k, v in sorted(settings.items()))
        run = ["docker", "run", "-d", "--pull", "never", "--name", container_name, "--cpus", "1", "--memory", "512m",
               "--network", "jjamtong-sandbox_default", "-p", "127.0.0.1:" + str(PORT) + ":8080"]
        for k, v in labels.items(): run += ["--label", k + "=" + v]
        environment = {"JDBC_URL": "jdbc:postgresql://postgres:5432/board", "DB_USER": "lab", "DB_PASSWORD": "synthetic-local-only",
                       "KAFKA_BOOTSTRAP": "kafka:9092", "REDIS_HOST": "redis", "REDIS_PORT": "6379", "PROBE_MODE": case["mode"],
                       "SPRING_KAFKA_CONSUMER_AUTO_OFFSET_RESET": "latest", "SPRING_THREADS_VIRTUAL_ENABLED": str(case["model"] == "mvc-virtual").lower(),
                       "JAVA_TOOL_OPTIONS": options}
        for k, v in environment.items(): run += ["-e", k + "=" + v]
        if case["arm"] != "none": run += ["--mount", "type=bind,source=" + str(args.agent) + ",target=/otel/opentelemetry-javaagent.jar,readonly"]
        launch_ns = time.perf_counter_ns()
        container = cmd(run + [manifest["imageIds"][case["module"]]], timeout=60).stdout.strip()
        write_json(directory / "checkpoint.json", {"state": "running", "containerId": container, "containerName": container_name})
        ready = wait_ready(container, case["mode"])
        ready["dockerInvocationNs"] = launch_ns
        ready["invocationToHealthNs"] = ready["healthObservedNs"] - launch_ns
        ready["invocationToKafkaAssignmentNs"] = ready["kafkaAssignmentObservedNs"] - launch_ns
        result["startup"] = ready
        result["runtime"] = runtime_identity(identity, case["mode"])
        result["startupCumulativeResource"] = snapshot(container)
        if result["startupCumulativeResource"]["pid1Comm"] != "java": raise AssertionError("Image PID1 is not java")
        result["preflight"] = None
        rows, summary = load_phase(directory / "preflight-latency.jsonl", "preflight", 1, 1, case["mode"], args.delay_millis)
        all_rows.extend(rows)
        preflight = drain(postgres, case["mode"], all_rows)
        result["preflight"] = {"latency": summary, "drain": preflight}
        if summary["successful"] != 1 or not preflight["oracle"]["complete"]: raise AssertionError("Redis/Kafka preflight did not apply exactly once")
        rows, summary = load_phase(directory / "warmup-latency.jsonl", "warmup", args.warmup, 4, case["mode"], args.delay_millis)
        all_rows.extend(rows)
        result["warmup"] = {"latency": summary, "drain": drain(postgres, case["mode"], all_rows)}
        if not result["warmup"]["drain"]["oracle"]["complete"]: raise AssertionError("Warmup did not drain")
        time.sleep(QUIET_SECONDS)
        for phase, count, workers in (("serial", args.serial_requests, 1), ("parallel", args.parallel_requests, 4)):
            write_json(directory / "checkpoint.json", {"state": "measuring", "phase": phase, "containerId": container})
            measured = measure_phase(directory, phase, count, workers, case, container, postgres, all_rows, args.delay_millis)
            phases.append(measured)
            write_json(directory / "checkpoint.json", {"state": "measured", "phase": phase, "containerId": container})
            if not measured["drain"]["oracle"]["complete"]: raise AssertionError("Measured phase did not drain")
        result["finalDrain"] = drain(postgres, case["mode"], all_rows)
        if not result["finalDrain"]["oracle"]["complete"]: raise AssertionError("Final owned events did not drain")
        result["lifetimePreStopResource"] = snapshot(container)
        result["status"] = "BUSINESS_COMPLETE"
    except BaseException as error:
        failure = error; result["failureType"] = type(error).__name__
    finally:
        try:
            cleanup_owned(container, container_name, labels, directory, result)
        finally:
            try: result["baselineContainersPreserved"] = containers() == baseline
            except BaseException as error:
                result["baselineContainersPreserved"] = False
                result.setdefault("cleanupFailures", []).append({"stage": "baseline-inspect", "errorType": type(error).__name__})
            finally:
                if result.get("cleanupFailures") and result["status"] == "BUSINESS_COMPLETE": result["status"] = "CLEANUP_FAILED"
                if not result["baselineContainersPreserved"]: result["status"] = "BASELINE_CHANGED"
                write_json(directory / "result.json", result)
                files = {p.name: file_digest(p) for p in directory.iterdir() if p.is_file() and p.name not in {"hashes.json", "checkpoint.json"}}
                write_json(directory / "hashes.json", files)
                write_json(directory / "checkpoint.json", {"state": "finished" if not failure and not result.get("cleanupFailures") else "interrupted",
                                                            "baselinePreserved": result["baselineContainersPreserved"]})
    if failure: raise failure
    if not result["baselineContainersPreserved"]: raise AssertionError("Baseline container IDs changed after case")
    if result.get("cleanupFailures"): raise RuntimeError("Owned cleanup failed; inspect preserved result/checkpoint")


def read_rows(directory):
    return [json.loads(line) for phase in ("preflight", "warmup", "serial", "parallel")
            if (path := directory / (phase + "-latency.jsonl")).exists() for line in path.read_text().splitlines()]


def comparison_eligible(result, telemetry):
    errors = [p["phase"] for p in result["phases"] if p["latency"]["errors"] or not p["drain"]["oracle"]["complete"]
              or not p["drain"]["oracle"]["expectedAttemptOutcomes"] or p["resources"]["samplerErrors"]]
    return (result["status"] == "BUSINESS_COMPLETE" and len(result["phases"]) == 2 and not errors
            and not result["warmup"]["latency"]["errors"] and telemetry["status"] != "PARTIAL"
            and result["warmup"]["drain"]["oracle"]["expectedAttemptOutcomes"]
            and result["preflight"]["drain"]["oracle"]["expectedAttemptOutcomes"]
            and result["finalDrain"]["oracle"]["expectedAttemptOutcomes"]
            and result["baselineContainersPreserved"] and result.get("removed") is True
            and result["stop"]["exitCode"] == 0 and not result.get("cleanupFailures"))


def revalidate_case(directory, manifest, case):
    hashes = json.loads((directory / "hashes.json").read_text())
    for name, expected in hashes.items():
        if Path(name).name != name or file_digest(directory / name) != expected: raise AssertionError("Preserved raw evidence hash mismatch")
    if json.loads((directory / "case.json").read_text()) != case: raise AssertionError("Case configuration changed")
    result = json.loads((directory / "result.json").read_text())
    rows = read_rows(directory)
    for phase in result["phases"]:
        current = [r for r in rows if r["phase"] == phase["phase"]]
        if latency_summary(current, phase["latency"]["httpWallNs"]) != phase["latency"]: raise AssertionError("Raw latency revalidation differs")
        resource = phase["resources"]
        for field, end in (("httpWindow", "httpEnd"), ("completionWindow", "completionEnd")):
            if cpu_window(resource["start"], resource[end], phase["latency"]["completedResponses"], phase["latency"]["successful"]) != resource[field]:
                raise AssertionError("Raw CPU revalidation differs")
        # The snapshot belongs to all phases up through this phase, not future IDs.
        stages = {"preflight", "warmup", "serial"} | ({"parallel"} if phase["phase"] == "parallel" else set())
        oracle = drain_oracle(phase["drain"]["snapshot"], [r for r in rows if r["phase"] in stages])
        if oracle != phase["drain"]["oracle"]: raise AssertionError("Owned business effect revalidation differs")
    if result.get("finalDrain") and drain_oracle(result["finalDrain"]["snapshot"], rows) != result["finalDrain"]["oracle"]:
        raise AssertionError("Final owned event drain revalidation differs")
    telemetry = telemetry_summary(directory / "telemetry.log", case, manifest["identities"][case["module"]], rows,
                                  result.get("log", {}).get("complete", False))
    return {"case": case, "comparisonEligible": comparison_eligible(result, telemetry), "status": result["status"], "phases": result["phases"],
            "telemetry": telemetry, "startup": result.get("startup"), "runtime": result.get("runtime"), "stop": result.get("stop"),
            "startupCumulativeResource": result.get("startupCumulativeResource"),
            "lifetimePreStopResource": result.get("lifetimePreStopResource"), "finalDrain": result.get("finalDrain"),
            "rawMeasurements": {"columns": ["id", "latencyNs", "status", "sent", "validationError"],
                                "phases": {phase: [[r[k] for k in ("id", "latencyNs", "status", "sent", "validationError")]
                                                    for r in sorted(rows, key=lambda r: r["id"]) if r["phase"] == phase]
                                           for phase in ("preflight", "warmup", "serial", "parallel")}},
            "rawSha256": hashes, "baselineContainersPreserved": result["baselineContainersPreserved"],
            "cleanupFailures": result.get("cleanupFailures", [])}


def metric_values(result, phase):
    p = next(p for p in result["phases"] if p["phase"] == phase)
    return {"successfulGoodputPerSecond": p["latency"]["successfulGoodputPerSecond"],
            "successP50Ns": p["latency"]["successfulResponseLatency"]["p50Ns"],
            "successP95Ns": p["latency"]["successfulResponseLatency"]["p95Ns"],
            "successP99Ns": p["latency"]["successfulResponseLatency"]["p99Ns"],
            "allCompletedP50Ns": p["latency"]["allCompletedResponseLatency"]["p50Ns"],
            "allCompletedP95Ns": p["latency"]["allCompletedResponseLatency"]["p95Ns"],
            "allCompletedP99Ns": p["latency"]["allCompletedResponseLatency"]["p99Ns"],
            "httpCpuMsPerSuccess": p["resources"]["httpWindow"]["cpuMsPerSuccessfulResponse"],
            "completionCpuMsPerSuccess": p["resources"]["completionWindow"]["cpuMsPerSuccessfulResponse"],
            "sampledVmRssPeakBytes": p["resources"]["sampledVmRssPeakBytes"],
            "sampledCgroupMemoryPeakBytes": p["resources"]["sampledCgroupMemoryPeakBytes"]}


def aggregate(results):
    groups, deltas = [], []
    for model in sorted({r["case"]["model"] for r in results}):
        for phase in ("serial", "parallel"):
            available = [r for r in results if r["case"]["model"] == model and any(p["phase"] == phase for p in r["phases"])]
            for arm in ARMS:
                runs = sorted((r for r in available if r["case"]["arm"] == arm), key=lambda r: r["case"]["repetition"])
                values = [metric_values(r, phase) for r in runs]
                groups.append({"model": model, "phase": phase, "arm": arm,
                               "repetitions": [r["case"]["repetition"] for r in runs],
                               "allComparisonEligible": bool(runs) and all(r["comparisonEligible"] for r in runs),
                               "metrics": {k: {"raw": [v[k] for v in values],
                                                "median": statistics.median([v[k] for v in values if v[k] is not None]) if any(v[k] is not None for v in values) else None}
                                           for k in values[0]} if values else {}})
            for base, candidate in (("none", "default"), ("none", "selected"), ("default", "selected")):
                paired = []
                for rep in sorted({r["case"]["repetition"] for r in available}):
                    by_arm = {r["case"]["arm"]: r for r in available if r["case"]["repetition"] == rep}
                    if base not in by_arm or candidate not in by_arm: continue
                    left, right = metric_values(by_arm[base], phase), metric_values(by_arm[candidate], phase)
                    paired.append({"repetition": rep, "comparisonEligible": by_arm[base]["comparisonEligible"] and by_arm[candidate]["comparisonEligible"],
                                   "percentDelta": {k: (right[k] - left[k]) / left[k] * 100 if left[k] and right[k] is not None else None for k in left}})
                keys = paired[0]["percentDelta"] if paired else {}
                deltas.append({"model": model, "phase": phase, "baselineArm": base, "candidateArm": candidate, "paired": paired,
                               "eligibleMedianAndRange": {k: {"median": statistics.median(v), "min": min(v), "max": max(v)}
                                                          for k in keys if (v := [r["percentDelta"][k] for r in paired if r["comparisonEligible"] and r["percentDelta"][k] is not None])},
                               "direction": "(candidate-baseline)/baseline; latency/CPU/memory positive means higher cost, goodput positive means more successes/sec"})
    return {"groups": groups, "pairedDeltas": deltas, "statisticalSignificanceClaimed": False}


def summarize(args, manifest):
    results, pending, incomplete = [], [], []
    for case in manifest["cases"]:
        directory = args.output / case["id"]
        if not directory.exists(): pending.append(case["id"]); continue
        if not (directory / "hashes.json").exists(): incomplete.append(case["id"]); continue
        results.append(revalidate_case(directory, manifest, case))
    public = {k: manifest[k] for k in ("schemaVersion", "configuration", "configurationSha256", "scriptSha256", "agentVersion", "agentSha256",
                                     "targetRevision", "identities", "imageIds", "machine", "limitations")}
    public.update({"results": results, "pendingCases": pending, "incompleteCases": incomplete, "aggregate": aggregate(results),
                   "validatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    write_json(args.output / "summary.json", public)
    print(json.dumps({"validatedCases": len(results), "eligibleCases": sum(r["comparisonEligible"] for r in results),
                      "pendingCases": pending, "incompleteCases": incomplete, "containersStarted": False if args.summarize else args.run}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--build-id")
    parser.add_argument("--agent", type=Path, default=ROOT / ".local/method-observability/opentelemetry-javaagent-2.33.1.jar")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--serial-requests", type=int)
    parser.add_argument("--parallel-requests", type=int)
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--delay-millis", type=int)
    parser.add_argument("--only-case", help="Comma-separated immutable case IDs; completed cases are revalidated, never rerun")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    args.target = args.target.resolve(); args.agent = args.agent.resolve(); args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / ".local"): parser.error("Raw logs must stay under ignored .local output")
    previous = json.loads((args.output / "manifest.json").read_text())["configuration"] if (args.output / "manifest.json").exists() else {}
    defaults = {"models": ("models", list(MODELS)), "repetitions": ("repetitions", 3), "serial_requests": ("serialRequests", 300),
                "parallel_requests": ("parallelRequests", 600), "warmup": ("warmup", 100), "delay_millis": ("delayMillis", 5),
                "build_id": ("buildId", "method-agent-b1")}
    for name, (key, default) in defaults.items():
        if getattr(args, name) is None: setattr(args, name, previous.get(key, default))
    if isinstance(args.models, list): args.models = ",".join(args.models)
    if not set(args.models.split(",")) <= set(MODELS) or len(args.models.split(",")) != len(set(args.models.split(","))): parser.error("Unknown or duplicate model")
    if not 1 <= args.repetitions <= 9 or not 1 <= args.serial_requests <= 10000 or not 1 <= args.parallel_requests <= 10000 or not 0 <= args.warmup <= 1000 or not 0 <= args.delay_millis <= 1000:
        parser.error("Bounded limits: repetitions1..9, requests1..10000, warmup0..1000, delay0..1000ms")
    def interrupted(_signal, _frame): raise KeyboardInterrupt("Interrupted; preserve checkpoints and resume remaining case IDs")
    signal.signal(signal.SIGTERM, interrupted)
    manifest = prepare(args)
    if args.run:
        selected = set(args.only_case.split(",")) if args.only_case else {c["id"] for c in manifest["cases"]}
        if selected - {c["id"] for c in manifest["cases"]}: parser.error("Unknown --only-case ID")
        for case in manifest["cases"]:
            if case["id"] not in selected: continue
            directory = args.output / case["id"]
            if directory.exists():
                revalidate_case(directory, manifest, case)
                print(json.dumps({"case": case["id"], "revalidatedExisting": True}), flush=True)
                continue
            run_case(args, manifest, case)
            revalidate_case(directory, manifest, case)
            print(json.dumps({"case": case["id"], "completed": True}), flush=True)
    summarize(args, manifest)


if __name__ == "__main__":
    main()
