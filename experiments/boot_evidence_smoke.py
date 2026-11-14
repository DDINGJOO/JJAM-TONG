"""Run one actual Boot POST in an isolated MSA project, then query exact-build DB evidence."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import uuid

from experiments.execution_agent_smoke import (AGENT_SHA, BUILD_KEYS, active_containers,
                                               command, digest, file_digest, properties,
                                               request, wait_for)
from tools.evidence_store.contracts import EvidenceReader, GraphRequest, SnapshotRef, VersionMismatch
from tools.evidence_store.postgres import PostgresEvidenceStore
from tools.method_evidence.evidence import read_otlp, validate_index

PROJECT = "jjamtong-boot-evidence"
PORT = 28380
METHODS = ("io.jjamtong.sandbox.board.BoardController[create];"
           "io.jjamtong.sandbox.board.PostWriteService[create,normalizeTitle,validate,appendEvent]")


def run(args):
    private_root = Path(__file__).resolve().parents[1] / ".local"
    if not args.output.resolve().is_relative_to(private_root.resolve()):
        raise ValueError("Raw smoke output must stay inside the product's ignored .local directory")
    index = validate_index(json.loads(args.index.read_text()))
    identity = index["buildIdentity"]
    if identity["module"] != "board-api" or file_digest(args.agent) != AGENT_SHA:
        raise ValueError("This smoke requires board-api and the pinned OTel 2.33.1 agent")
    artifact = args.target / ".local/artifacts" / identity["build"] / "board-api.jar"
    if file_digest(artifact) != identity["artifactSha256"]:
        raise ValueError("Deployment artifact differs from index")
    worker_identity = properties(artifact.with_name("activity-worker.properties"))
    worker_artifact = artifact.with_name("activity-worker.jar")
    if (worker_identity["revision"] != identity["revision"] or worker_identity["build"] != identity["build"] or
            file_digest(worker_artifact) != worker_identity["artifactSha256"]):
        raise ValueError("Worker must come from the same actual build")
    if command(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT]).stdout.strip():
        raise ValueError("Smoke project already exists; never take over another run")
    before = active_containers()
    args.output.mkdir(mode=0o700)
    settings = {"otel.traces.sampler": "always_on", "otel.traces.exporter": "logging-otlp",
                "otel.metrics.exporter": "none", "otel.logs.exporter": "none",
                "otel.bsp.schedule.delay": "100", "otel.bsp.max.queue.size": "2048",
                "otel.bsp.max.export.batch.size": "512", "otel.service.name": "boot-evidence-board-api",
                "otel.instrumentation.methods.include": METHODS,
                "otel.instrumentation.jdbc.query-sanitization.enabled": "true",
                "otel.instrumentation.jdbc.experimental.capture-query-parameters": "false"}
    config = digest({"agentSha256": AGENT_SHA, "settings": settings})
    resource = {BUILD_KEYS[key]: value for key, value in identity.items()}
    resource["jjamtong.config.sha256"] = config
    options = "-javaagent:/otel/agent.jar " + " ".join("-D" + key + "=" + value for key, value in sorted(settings.items()))
    options += " -Dotel.resource.attributes=" + ",".join(key + "=" + value for key, value in resource.items())
    model = json.loads(command(["docker", "compose", "-f", args.target / "compose.yaml", "config", "--format", "json"]).stdout)
    model["name"] = PROJECT
    for module, port in (("board-api", PORT), ("activity-worker", PORT + 1)):
        svc = model["services"][module]
        svc["image"] = PROJECT + "/" + module + ":" + identity["build"]
        svc["build"]["args"]["BUILD_ID"] = identity["build"]
        svc["ports"] = [{"target": 8080, "published": str(port), "host_ip": "127.0.0.1", "protocol": "tcp"}]
        if module == "board-api":
            svc["environment"]["JAVA_TOOL_OPTIONS"] = options
            svc["volumes"] = [{"type": "bind", "source": str(args.agent.resolve()), "target": "/otel/agent.jar", "read_only": True}]
            svc["mem_limit"] = "768m"
    for name, volume in model["volumes"].items():
        volume["name"] = PROJECT + "_" + name
    # Resolved config may carry explicit names; keep networks isolated too.
    for name, network in model.get("networks", {}).items():
        network["name"] = PROJECT + "_" + name
    compose_file = args.output / "compose.json"
    compose_file.write_text(json.dumps(model, indent=2) + "\n")
    compose = ["docker", "compose", "-p", PROJECT, "-f", compose_file]
    report = None
    try:
        command(compose + ["config", "--quiet"])
        command(compose + ["build", "board-api", "activity-worker"])
        command(compose + ["up", "-d"], timeout=180)
        runtime = wait_for(lambda: request(PORT, "/evidence/build")[1], seconds=120)
        if runtime.get("build") != identity or runtime.get("artifactDigestVerified") is not True:
            raise AssertionError("Runtime's own deployment hash check must match exact static build")
        trace_id, parent = uuid.uuid4().hex, uuid.uuid4().hex[:16]
        code, post = request(PORT, "/posts", {"title": "synthetic boot evidence", "content": "synthetic only"},
                             "00-" + trace_id + "-" + parent + "-01")
        if code != 201:
            raise AssertionError("Actual POST did not succeed")
        wait_for(lambda: request(PORT, "/_test/outbox/" + post["id"])[1][0]["published"], seconds=30)
        wait_for(lambda: len(request(PORT + 1, "/activities/" + post["id"])[1]) == 1, seconds=30)
        time.sleep(1)
        raw = args.output / "board-private.log"
        raw.write_text(command(compose + ["logs", "--no-color", "--no-log-prefix", "board-api"]).stdout)
        collection = read_otlp(raw)
        store = PostgresEvidenceStore(os.environ["JJAMTONG_EVIDENCE_DSN"])
        store.initialize()
        created = store.publish(args.tenant, index)
        ref = SnapshotRef(args.tenant, index["analysisRunId"], index["indexSha256"])
        reader = EvidenceReader(store, store)
        observed = reader.trace(ref, collection, trace_id, config)
        methods = [s for s in observed["spans"] if s["class"]]
        unique = {(s["class"], s["method"]) for s in methods if s["symbolStatus"] == "unique-name-resolved"}
        required = {("io.jjamtong.sandbox.board.BoardController", "create"),
                    *( ("io.jjamtong.sandbox.board.PostWriteService", name) for name in ("create", "normalizeTitle", "appendEvent"))}
        if not required <= unique:
            raise AssertionError("Actual Controller/Service/private methods must resolve in the exact stored index")
        overloads = [s for s in methods if s["method"] == "validate"]
        if not overloads or any(s["symbolStatus"] != "UNRESOLVED_CODE_SYMBOL" or len(s["symbolCandidates"]) != 2 for s in overloads):
            raise AssertionError("Actual validate overloads must remain explicit unresolved candidates")
        graphs = {}
        for analyzer in ("javaparser", "wala"):
            root = next(m for m in index["staticEvidence"][analyzer]["methods"]
                        if m["class"].endswith(".BoardController") and m["name"] == "create")
            root_key = tuple(root[k] for k in ("module", "class", "name", "descriptor"))
            graph = reader.graph(GraphRequest(ref, analyzer, root_key))
            if not any(e["caller"]["class"].endswith(".BoardController") and e["target"]["class"].endswith(".PostWriteService") and e["target"]["name"] == "create" for e in graph.calls):
                raise AssertionError("Stored graph must preserve Controller -> Service candidate")
            graphs[analyzer] = asdict(graph)
        other = validate_index(json.loads(args.other_index.read_text()))
        if other["buildIdentity"] == identity:
            raise AssertionError("Negative control must be a different real build")
        store.publish(args.tenant, other)
        other_ref = SnapshotRef(args.tenant, other["analysisRunId"], other["indexSha256"])
        other_result = reader.trace(other_ref, collection, trace_id, config)
        if other_result["status"] != "MISMATCH" or other_result["spans"]:
            raise AssertionError("Actual trace must be rejected by the other actual build index")
        wrong = json.loads(json.dumps(collection))
        for span in wrong["spans"]:
            span["resource"]["build"] += "-other"
        rejected = reader.trace(ref, wrong, trace_id, config)
        if rejected["status"] != "MISMATCH" or rejected["spans"]:
            raise AssertionError("A different build must never attach")
        try:
            reader.graph(GraphRequest(SnapshotRef(args.tenant, ref.run_id, "0" * 64), "wala", root_key))
        except VersionMismatch:
            pass
        else:
            raise AssertionError("Wrong index hash must be rejected")
        report = {"schema": "jjamtong.boot-evidence-smoke.v1", "buildIdentity": identity,
                  "analysisRunId": ref.run_id, "indexSha256": ref.index_sha256,
                  "staticInput": index["input"], "analysisProvenance": index["provenance"],
                  "agentSha256": AGENT_SHA, "telemetryConfigSha256": config,
                  "httpStatus": code, "runtimeArtifactVerified": True,
                  "outboxPublished": True, "consumerEffects": 1, "storeCreated": created,
                  "trace": observed, "graphs": graphs, "wrongBuildStatus": rejected["status"],
                  "wrongHashRejected": True, "otherSnapshot": {"ref": asdict(other_ref), "buildIdentity": other["buildIdentity"], "traceStatus": other_result["status"]}, "rawLogSha256": file_digest(raw),
                  "rawLogBytes": raw.stat().st_size, "collectionInputReasons": collection["collectionReasons"],
                  "limitations": ["One local board-api POST, not continuous trace ingestion or enterprise capacity.",
                                  "Runtime names do not carry JVM descriptors; overloads remain unresolved.",
                                  "Scheduled outbox/Kafka continuity is not validated by this same-request trace."]}
    finally:
        cleanup = command(compose + ["down", "--timeout", "15"], check=False)
        if cleanup.returncode or active_containers() != before:
            raise AssertionError("Smoke cleanup failed or baseline container IDs changed")
        if report is not None:
            report["baselineContainersPreserved"] = True
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"traceStatus": report["trace"]["status"], "methods": len(methods), "wrongBuild": rejected["status"]}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("target", "index", "other-index", "agent", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--tenant", default="playground-boot-local")
    run(p.parse_args())


if __name__ == "__main__":
    main()
