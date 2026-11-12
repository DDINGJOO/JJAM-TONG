#!/usr/bin/env python3
"""Observe a selected agent on three existing local execution fixtures.

Preparation is read-only except ignored output. --run starts/stops only a new
Compose project; the baseline container IDs must remain unchanged. No target
source, existing image, table schema, consumer offset, or production resource is
reset. The outbox's manual string carrier is not assumed to restore SDK context.
"""
import argparse
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
AGENT_SHA = "e43a270df53c6f423e0ab157be9c27ccc01d5dc3232e162fe54777573db2f149"
PROJECT = "jjamtong-execution-agent"
MODES = {"mvc-platform": (28280, "execution-mvc"), "mvc-virtual": (28281, "execution-mvc"), "netty": (28282, "execution-netty")}
METHODS = ("io.jjamtong.sandbox.execution.ProbeService[create,publish,accept];"
           "io.jjamtong.sandbox.executionmvc.ExecutionMvcController[create];"
           "io.jjamtong.sandbox.executionnetty.ExecutionNettyController[create]")
BUILD_KEYS = {"repository": "jjamtong.repository", "revision": "jjamtong.revision", "build": "jjamtong.build",
              "module": "jjamtong.module", "artifactSha256": "jjamtong.artifact.sha256"}
ATTRIBUTES = {"code.namespace", "code.function", "thread.name", "thread.id", "messaging.system",
              "messaging.operation.type", "messaging.operation.name", "messaging.destination.name",
              "messaging.destination.partition.id", "messaging.kafka.offset", "messaging.kafka.consumer.group",
              "messaging.consumer.group.name", "db.system", "db.system.name"}
RESOURCE_ATTRIBUTES = set(BUILD_KEYS.values()) | {"jjamtong.config.sha256", "service.name", "telemetry.distro.version",
                                               "telemetry.sdk.version", "process.runtime.version"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def command(parts, *, timeout=180, check=True):
    return subprocess.run([str(x) for x in parts], check=check, text=True, capture_output=True, timeout=timeout)


def active_containers():
    rows = command(["docker", "ps", "--format", "{{.ID}} {{.Names}}"], timeout=20).stdout.splitlines()
    return sorted(rows)


def properties(path):
    return dict(line.split("=", 1) for line in Path(path).read_text().splitlines() if line and not line.startswith("#"))


def request(port, path, body=None, parent=None):
    headers = {"Content-Type": "application/json"}
    if parent: headers["traceparent"] = parent
    req = urllib.request.Request(f"http://127.0.0.1:{port}" + path, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_for(check, seconds=90):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = check()
            if last: return last
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    raise AssertionError("Timed out waiting for fixture readiness/effect: " + repr(last))


def prepare(args):
    if file_digest(args.agent) != AGENT_SHA: raise AssertionError("Agent digest differs from the selected 2.33.1 artifact")
    if args.output.exists(): raise ValueError("Use a new ignored output directory to preserve earlier evidence")
    args.output.mkdir(parents=True)
    override = {"services": {}}
    settings, identities, images = {}, {}, {}
    for mode, (_, module) in MODES.items():
        identity = properties(args.target / ".local/artifacts" / args.build_id / (module + ".properties"))
        artifact = args.target / ".local/artifacts" / args.build_id / (module + ".jar")
        if file_digest(artifact) != identity["artifactSha256"]: raise AssertionError("Existing target artifact/sidecar mismatch")
        values = {"otel.traces.sampler": "always_on", "otel.traces.exporter": "logging-otlp", "otel.metrics.exporter": "none",
                  "otel.logs.exporter": "none", "otel.bsp.max.queue.size": "8192", "otel.bsp.max.export.batch.size": "512",
                  "otel.bsp.schedule.delay": "100", "otel.service.name": "execution-agent-" + mode,
                  "otel.instrumentation.methods.include": METHODS,
                  "otel.instrumentation.jdbc.query-sanitization.enabled": "true",
                  "otel.instrumentation.jdbc.experimental.capture-query-parameters": "false",
                  "otel.instrumentation.jdbc.experimental.sqlcommenter.enabled": "false"}
        config = digest({"agentSha256": AGENT_SHA, "settings": values})
        resource = {BUILD_KEYS[key]: identity[key] for key in BUILD_KEYS}
        resource["jjamtong.config.sha256"] = config
        values["otel.resource.attributes"] = ",".join(key + "=" + value for key, value in resource.items())
        java_options = "-javaagent:/otel/opentelemetry-javaagent.jar " + " ".join("-D" + key + "=" + value for key, value in sorted(values.items()))
        image = "jjamtong-sandbox/" + module + ":" + args.build_id
        override["services"][mode] = {"image": image,
                                      "volumes": [str(args.agent.resolve()) + ":/otel/opentelemetry-javaagent.jar:ro"],
                                      "environment": {"JAVA_TOOL_OPTIONS": java_options}}
        settings[mode] = {"configSha256": config, "settings": values}
        identities[mode] = identity
        images[mode] = {"name": image, "id": command(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=20).stdout.strip()}
    (args.output / "compose-override.json").write_text(json.dumps(override, indent=2) + "\n")
    metadata = {"agentVersion": "2.33.1", "agentSha256": AGENT_SHA, "identities": identities, "images": images,
                "configs": settings, "baselineContainers": active_containers()}
    if len(metadata["baselineContainers"]) != 11: raise AssertionError("Expected exactly eleven pre-existing running containers")
    (args.output / "prepared.json").write_text(json.dumps(metadata, indent=2) + "\n")
    compose = ["docker", "compose", "--project-name", PROJECT, "-f", args.target / "compose.execution.yaml",
               "-f", args.output / "compose-override.json"]
    command(compose + ["config", "--quiet"], timeout=30)
    return metadata, compose


def scalar_attributes(values, allow):
    result = {}
    for entry in values:
        key = entry.get("key")
        if key not in allow: continue
        value = entry.get("value", {})
        for kind in ("stringValue", "intValue", "boolValue"):
            if kind in value:
                result[key] = value[kind]
                break
    return result


def collect(path):
    spans = []
    consumed = 0
    with path.open("rb") as stream:
        for raw in stream:
            consumed += len(raw)
            if consumed > 64 * 1024 * 1024: raise AssertionError("Smoke telemetry exceeds the explicit 64 MiB input bound")
            line = raw.decode(errors="replace")
            start = line.find("{")
            if start < 0: continue
            try: value = json.loads(line[start:])
            except json.JSONDecodeError: continue
            if not isinstance(value, dict) or "scopeSpans" not in value: continue
            resource = scalar_attributes(value.get("resource", {}).get("attributes", []), RESOURCE_ATTRIBUTES)
            for scope in value["scopeSpans"]:
                for span in scope.get("spans", []):
                    spans.append({"traceId": span.get("traceId"), "spanId": span.get("spanId"),
                                  "parentSpanId": span.get("parentSpanId"), "kind": span.get("kind"),
                                  "scope": scope.get("scope", {}).get("name"), "resource": resource,
                                  "attributes": scalar_attributes(span.get("attributes", []), ATTRIBUTES),
                                  "error": span.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR"),
                                  "links": [{"traceId": x.get("traceId"), "spanId": x.get("spanId")} for x in span.get("links", [])]})
    return spans


def descends_from(span, ancestors, by_id):
    seen = set()
    current = span
    while current and current.get("parentSpanId"):
        key = (current["traceId"], current["parentSpanId"])
        if key in ancestors: return True
        if key in seen: return False
        seen.add(key)
        current = by_id.get(key)
    return False


def summarize(mode, metadata, runtime, event, parent, spans, created):
    incoming_trace = parent.split("-")[1]
    header_values = sorted({row["traceparent"] for row in event["attempts"] if row.get("traceparent")})
    methods = [s for s in spans if s["scope"] == "io.opentelemetry.methods"]
    # Bind the owned event to its received record header, rather than accepting
    # any unrelated Kafka producer observed while other modes are running.
    header_contexts = {(value.split("-")[1], value.split("-")[2]) for value in header_values}
    producer = [s for s in spans if s["attributes"].get("messaging.system") == "kafka" and s["kind"] == 4
                and (s["traceId"], s["spanId"]) in header_contexts]
    producer_ids = {(s["traceId"], s["spanId"]) for s in producer}
    producer_traces = sorted({s["traceId"] for s in producer})
    consumer = [s for s in spans if s["attributes"].get("messaging.system") == "kafka" and s["kind"] == 5]
    connected = [s for s in consumer if (s["traceId"], s.get("parentSpanId")) in producer_ids
                 or any((link["traceId"], link["spanId"]) in producer_ids for link in s["links"])]
    http = [s for s in spans if s["kind"] == 2 and s["traceId"] == incoming_trace
            and s.get("parentSpanId") == parent.split("-")[2]]
    creates = [s for s in methods if s["attributes"].get("code.namespace") == "io.jjamtong.sandbox.execution.ProbeService"
               and s["attributes"].get("code.function") == "create" and s["traceId"] == incoming_trace]
    own_consumes = [s for s in methods if s["attributes"].get("code.namespace") == "io.jjamtong.sandbox.execution.ProbeService"
                    and s["attributes"].get("code.function") == "accept" and s["traceId"] in producer_traces]
    by_id = {(s["traceId"], s["spanId"]): s for s in spans}
    connected_ids = {(s["traceId"], s["spanId"]) for s in connected}
    linked_accepts = [s for s in methods if s["attributes"].get("code.namespace") == "io.jjamtong.sandbox.execution.ProbeService"
                      and s["attributes"].get("code.function") == "accept" and descends_from(s, connected_ids, by_id)]
    jdbc = [s for s in spans if s["traceId"] == incoming_trace
            and (s["attributes"].get("db.system") or s["attributes"].get("db.system.name")) == "postgresql"]
    redis = [s for s in spans if s["traceId"] == incoming_trace
             and ((s["attributes"].get("db.system") or s["attributes"].get("db.system.name")) == "redis"
                  or "lettuce" in (s.get("scope") or "").lower())]
    observed_header_traces = sorted({value.split("-")[1] for value in header_values})
    identity = metadata["identities"][mode]
    required_resource = {BUILD_KEYS[key]: identity[key] for key in BUILD_KEYS}
    required_resource["jjamtong.config.sha256"] = metadata["configs"][mode]["configSha256"]
    for span in spans:
        if any(span["resource"].get(key) != value for key, value in required_resource.items()):
            raise AssertionError("Runtime resource does not preserve the actual deployed artifact/config identity")
    retained_traces = {incoming_trace, *producer_traces, *(s["traceId"] for s in connected)}
    selected = [s for s in spans if s["traceId"] in retained_traces]
    evidence = {"mode": mode, "identity": identity, "configSha256": metadata["configs"][mode]["configSha256"],
                "javaVersion": runtime["javaVersion"], "server": runtime["server"],
                "requestThreadEvidence": [row for row in event["observations"] if row["stage"] in ("request-ingress", "request-work", "outbox-publish", "consumer-attempt")],
                "httpIncomingTraceId": incoming_trace, "httpExtractionObserved": bool(http),
                "selectedCreateInHttpTrace": bool(creates), "producerTraceIds": producer_traces,
                "consumerRecordTraceparents": header_values,
                "outboxOriginalTraceparent": event["outbox"][0]["traceparent"],
                "producerAndConsumerRelationObserved": bool(connected),
                "consumerProducerDirectParents": sum((s["traceId"], s.get("parentSpanId")) in producer_ids for s in connected),
                "consumerProducerLinks": sum(any((link["traceId"], link["spanId"]) in producer_ids for link in s["links"]) for s in connected),
                "selectedAcceptInProducerTrace": bool(own_consumes),
                "selectedAcceptDescendsFromConnectedConsumer": bool(linked_accepts),
                "consumerHeaderMatchesProducerTrace": bool(set(observed_header_traces) & set(producer_traces)),
                "consumerHeaderMatchesOwnedProducerSpan": bool(producer),
                "jdbcClientSpanCountInHttpTrace": len(jdbc),
                "redisBusinessRoundTripObserved": created.get("redisRoundTrip") is True,
                "redisClientSpanCountInHttpTrace": len(redis),
                "redisCoverage": "CLIENT_SPAN_AND_BUSINESS_ROUND_TRIP" if redis else "BUSINESS_ROUND_TRIP_ONLY; client span absent, cause unverified",
                "scheduledOutboxPreservedIncomingSdkTrace": incoming_trace in producer_traces,
                "manualCarrierOverwrittenAtTransport": bool(header_values) and parent not in header_values,
                "effects": sum(row["applied_count"] for row in event["effects"]),
                "spanCount": len(spans), "spanCountsByScope": dict(sorted(Counter(s["scope"] for s in spans).items())),
                "selectedTraceSpans": selected, "selectedTraceSpanLimit": 200,
                "spanFieldsPolicy": "allowlisted identifiers, scope, kind, parent/links, code/thread/messaging-system metadata; no bodies, args, returns, SQL, URLs, exceptions or process paths"}
    if len(selected) > 200: raise AssertionError("Selected synthetic flow unexpectedly exceeds 200 retained spans")
    if not methods: raise AssertionError("Agent produced no selected-method evidence")
    required = {"httpExtractionObserved", "selectedCreateInHttpTrace", "producerAndConsumerRelationObserved",
                "selectedAcceptDescendsFromConnectedConsumer", "consumerHeaderMatchesOwnedProducerSpan",
                "consumerHeaderMatchesProducerTrace", "redisBusinessRoundTripObserved"}
    missing = sorted(key for key in required if evidence[key] is not True)
    if missing: raise AssertionError("Missing required owned-flow evidence: " + ", ".join(missing))
    if not jdbc: raise AssertionError("No JDBC client span in the owned HTTP trace")
    if evidence["effects"] != 1: raise AssertionError("Expected exactly one business effect for the owned event")
    return evidence


def save_summary(args, observations):
    summary = {"schemaVersion": 1, "agentVersion": "2.33.1", "agentSha256": AGENT_SHA,
               "recordedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "observations": observations,
               "validatorCodeSha256": file_digest(Path(__file__)),
               "rawLogSha256": {mode: file_digest(args.output / (mode + "-telemetry.log")) for mode in MODES},
               "inputBoundBytesPerLog": 64 * 1024 * 1024, "selectedSpanLimitPerMode": 200,
               "baselineContainersPreserved": True, "baselineContainerCount": 11, "addedContainersStoppedAndRemoved": True,
               "businessPathsPassed": 3, "telemetryScope": "selected concrete methods plus observed HTTP/JDBC/Kafka integration",
               "limitations": ["existing deployed revision/artifact retained; current target HEAD is not substituted",
                               "manual string/outbox correlation does not prove SDK context propagation; no outbox SDK context bridge was implemented",
                               "no complete-method coverage, sampling/production workload or cross-version support claim",
                               "Boot fixture has no static index/descriptor join in this smoke; its method spans carry class/name evidence",
                               "Redis business round trip succeeded, but no Redis/Lettuce client span was observed; cause unverified",
                               "consumer Record.headers and SDK span parent/links are observed; no broker payload is retained"]}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def run(args, metadata, compose):
    events, runtimes, parents, creations = {}, {}, {}, {}
    failure = None
    try:
        if active_containers() != metadata["baselineContainers"]: raise AssertionError("Baseline changed after preparation")
        started = command(compose + ["up", "-d", "--no-build", "--pull", "never"], timeout=240)
        (args.output / "compose-up.log").write_text(started.stdout + started.stderr)
        for mode, (port, _) in MODES.items():
            wait_for(lambda: request(port, "/probe/health")[0] == 200, seconds=120)
            code, runtime = request(port, "/probe/runtime")
            if code != 200: raise AssertionError("Runtime metadata unavailable")
            build = runtime["buildEvidence"]["build"]
            if any(build[key] != metadata["identities"][mode][key] for key in BUILD_KEYS): raise AssertionError("Deployed identity changed")
            if runtime["buildEvidence"]["artifactDigestVerified"] is not True: raise AssertionError("Runtime artifact hash not checked")
            runtimes[mode] = runtime
        for mode, (port, _) in MODES.items():
            parent = "00-" + uuid.uuid4().hex + "-" + uuid.uuid4().hex[:16] + "-01"
            parents[mode] = parent
            body = {"delayMillis": 0, "retryFailures": 0, "dropHeader": False, "failAfterInsert": False, "eventId": str(uuid.uuid4())}
            code, created = request(port, "/probe/requests", body, parent)
            if code != 201 or created["redisRoundTrip"] is not True: raise AssertionError("Business/Redis request failed")
            event_id = created["eventId"]
            creations[mode] = created
            (args.output / (mode + "-request.json")).write_text(json.dumps({"parent": parent, "created": created}, indent=2) + "\n")
            def finished():
                code, event = request(port, "/probe/events/" + event_id)
                return event if code == 200 and event.get("effects") and event.get("attempts") else None
            event = wait_for(finished)
            if len(event["outbox"]) != 1 or event["outbox"][0]["traceparent"] != parent: raise AssertionError("Original manual outbox carrier lost")
            if sum(row["applied_count"] for row in event["effects"]) != 1: raise AssertionError("Kafka business effect differs")
            events[mode] = event
            (args.output / (mode + "-event.json")).write_text(json.dumps({"parent": parent, "created": created, "event": event}, indent=2) + "\n")
        time.sleep(.5)
    except BaseException as error:
        failure = error
    finally:
        # Keep the stopped containers until their shutdown-flushed exporter logs have been captured.
        stopped = command(compose + ["stop", "--timeout", "10"], timeout=90, check=False)
        (args.output / "compose-stop.log").write_text(stopped.stdout + stopped.stderr)
        for mode in MODES:
            found = command(compose + ["ps", "-a", "-q", mode], timeout=20, check=False).stdout.strip()
            if found:
                with (args.output / (mode + "-telemetry.log")).open("w") as stream:
                    subprocess.run(["docker", "logs", found], check=True, text=True, stdout=stream, stderr=subprocess.STDOUT, timeout=30)
        removed = command(compose + ["down"], timeout=90, check=False)
        (args.output / "compose-down.log").write_text(removed.stdout + removed.stderr)
        baseline_preserved = active_containers() == metadata["baselineContainers"]
        (args.output / "lifecycle.json").write_text(json.dumps({"baselineCount": len(metadata["baselineContainers"]), "baselinePreserved": baseline_preserved,
                                                               "stopExitCode": stopped.returncode, "downExitCode": removed.returncode}, indent=2) + "\n")
        if not baseline_preserved: raise AssertionError("Baseline container IDs changed")
    if failure: raise failure
    observations = []
    for mode in MODES:
        spans = collect(args.output / (mode + "-telemetry.log"))
        observations.append(summarize(mode, metadata, runtimes[mode], events[mode], parents[mode], spans, creations[mode]))
    save_summary(args, observations)
    print(json.dumps({"businessPathsPassed": 3, "baselinePreserved": True, "addedAppsStopped": True,
                      "modes": [{key: row[key] for key in ("mode", "httpExtractionObserved", "producerAndConsumerRelationObserved",
                                                          "scheduledOutboxPreservedIncomingSdkTrace", "manualCarrierOverwrittenAtTransport", "spanCount")} for row in observations]}))


def revalidate(args):
    metadata = json.loads((args.output / "prepared.json").read_text())
    previous = json.loads((args.output / "summary.json").read_text())
    lifecycle = json.loads((args.output / "lifecycle.json").read_text())
    if lifecycle != {"baselineCount": 11, "baselinePreserved": True, "stopExitCode": 0, "downExitCode": 0}:
        raise AssertionError("Original lifecycle verification did not complete")
    old_runtime = {row["mode"]: {key: row[key] for key in ("javaVersion", "server")} for row in previous["observations"]}
    observations = []
    for mode in MODES:
        identity = metadata["identities"][mode]
        artifact = args.target / ".local/artifacts" / identity["build"] / (identity["module"] + ".jar")
        if file_digest(artifact) != identity["artifactSha256"]: raise AssertionError("Preserved artifact differs from run metadata")
        saved = json.loads((args.output / (mode + "-event.json")).read_text())
        observations.append(summarize(mode, metadata, old_runtime[mode], saved["event"], saved["parent"],
                                      collect(args.output / (mode + "-telemetry.log")), saved["created"]))
    save_summary(args, observations)
    print(json.dumps({"revalidatedModes": len(observations), "containersStarted": False,
                      "validatorCodeSha256": file_digest(Path(__file__)),
                      "redisClientSpanCounts": [row["redisClientSpanCountInHttpTrace"] for row in observations]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--build-id", default="execution-probe-b1", help="Select an existing artifact/sidecar/image set without rebuilding it")
    parser.add_argument("--agent", type=Path, default=ROOT / ".local/method-observability/opentelemetry-javaagent-2.33.1.jar")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="After the leader's benchmark gate, start only the isolated comparison project")
    parser.add_argument("--revalidate", action="store_true", help="Recheck preserved logs/events/artifacts without Docker or app starts")
    args = parser.parse_args()
    args.target = args.target.resolve(); args.output = args.output.resolve()
    if args.revalidate:
        if args.run: parser.error("Choose --run or --revalidate")
        revalidate(args)
        return
    metadata, compose = prepare(args)
    if args.run: run(args, metadata, compose)
    else: print(json.dumps({"prepared": True, "baselineCount": len(metadata["baselineContainers"]), "agentVersion": "2.33.1", "containersStarted": False}))


if __name__ == "__main__": main()
