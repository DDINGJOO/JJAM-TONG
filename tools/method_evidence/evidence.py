"""Fail-closed join of a verified artifact index and allowlisted OTLP span evidence.

Resource metadata is a caller assertion, not remote build provenance attestation.
The selected OTel agent supplies names but no JVM descriptors. Unique resolution
is therefore explicitly derived from this exact index, never reported as emitted.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

BUILD_FIELDS = ("repository", "revision", "build", "module", "artifactSha256")
RESOURCE_KEYS = {key: "jjamtong." + ("artifact.sha256" if key == "artifactSha256" else key)
                 for key in BUILD_FIELDS}
RESOURCE_KEYS["configSha256"] = "jjamtong.config.sha256"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
MAX_BYTES = 10 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def build_identity(value):
    result = {}
    for key in BUILD_FIELDS:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise ValueError("Missing or invalid build field: " + key)
        result[key] = item
    result["artifactSha256"] = result["artifactSha256"].lower()
    if not HEX64.fullmatch(result["artifactSha256"]):
        raise ValueError("Invalid artifact digest")
    return result


def method_key(method):
    return tuple(method[key] for key in ("module", "class", "name", "descriptor"))


def source_digest(root):
    root = Path(root)
    entries = [path.relative_to(root).as_posix() + "\0" + file_digest(path) + "\n"
               for path in sorted(root.rglob("*.java"))]
    return hashlib.sha256("".join(entries).encode()).hexdigest()


def create_index(analysis, manifest, artifact, sources, run_id):
    """Verify local input bytes before publishing an immutable analysis snapshot."""
    if not IDENTIFIER.fullmatch(run_id):
        raise ValueError("Invalid analysis run ID")
    identity = build_identity(manifest)
    if manifest.get("sourceState") != "clean":
        raise ValueError("Final evidence requires a clean-source manifest")
    if analysis.get("schema") != "jjamtong.methods.v1" or analysis.get("module") != identity["module"]:
        raise ValueError("Unsupported schema or module")
    if build_identity(analysis.get("metadata", {})) != identity:
        raise ValueError("Analysis/manifest build mismatch")
    if file_digest(artifact) != identity["artifactSha256"] or analysis["input"]["artifactSha256"] != identity["artifactSha256"]:
        raise ValueError("Artifact bytes mismatch")
    if analysis["input"]["sourceTreeSha256"] != source_digest(sources):
        raise ValueError("Analysis source bytes mismatch")
    actual_sources = {p.relative_to(sources).as_posix(): file_digest(p)
                      for p in Path(sources).rglob("*.java")}
    expected_sources = {p["path"]: p["sha256"] for p in manifest.get("sourceFiles", [])}
    if not actual_sources or actual_sources != expected_sources:
        raise ValueError("Build manifest source set mismatch")
    tools = analysis["tools"]
    if set(tools) != {"javaparser", "wala"}:
        raise ValueError("Expected the two experimental static adapters")
    methods = {}
    for tool in tools.values():
        for item in tool["methods"]:
            key = method_key(item)
            if key[0] != identity["module"] or not all(isinstance(v, str) and v for v in key):
                raise ValueError("Invalid method identity")
            methods[key] = dict(zip(("module", "class", "name", "descriptor"), key))
    if not methods:
        raise ValueError("Empty method inventory is not successful analysis")
    config = {"scope": analysis["scope"], "schema": analysis["schema"],
              "adapter": analysis["provenance"]["adapterVersion"],
              "tools": {key: {field: value.get(field) for field in
                               ("version", "algorithm", "entrypoints", "reflectionPolicy")}
                        for key, value in tools.items()}}
    result = {"schema": "jjamtong.method-index.v1", "analysisRunId": run_id,
              "buildIdentity": identity, "configSha256": digest(config), "config": config,
              "input": analysis["input"], "provenance": analysis["provenance"],
              "methods": [methods[key] for key in sorted(methods)],
              "staticEvidence": tools, "limitations": analysis["limitations"],
              "identityAssurance": "local bytes checked against caller-supplied manifest; not build attestation"}
    result["indexSha256"] = digest(result)
    return result


def validate_index(index):
    body = {key: value for key, value in index.items() if key != "indexSha256"}
    if index.get("schema") != "jjamtong.method-index.v1" or digest(body) != index.get("indexSha256"):
        raise ValueError("Index digest or schema mismatch")
    build_identity(index["buildIdentity"])
    if not index.get("methods") or digest(index["config"]) != index["configSha256"]:
        raise ValueError("Missing inventory or altered configuration")
    return index


def save_index(index, store):
    validate_index(index)
    run_id = index["analysisRunId"]
    if not IDENTIFIER.fullmatch(run_id):
        raise ValueError("Invalid analysis run ID")
    destination = Path(store) / (run_id + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: no implicit overwrite or latest-pointer mutation.
    data = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    if len(data.encode()) > MAX_BYTES:
        raise ValueError("Index exceeds 10 MiB")
    descriptor, temporary = tempfile.mkstemp(prefix=".index-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)  # atomic publish; fails if this run already exists
    finally:
        Path(temporary).unlink()
    return destination


def load_index(store, run_id):
    if not IDENTIFIER.fullmatch(run_id):
        raise ValueError("Invalid analysis run ID")
    destination = Path(store) / (run_id + ".json")
    if not destination.is_file():
        return None
    if destination.stat().st_size > MAX_BYTES:
        raise ValueError("Index exceeds 10 MiB")
    index = validate_index(json.loads(destination.read_text()))
    if index["analysisRunId"] != run_id:
        raise ValueError("Analysis run mismatch")
    return index


def attributes(values):
    result = {}
    for item in values:
        key, value = item.get("key"), item.get("value", {})
        if key in result:
            raise ValueError("Duplicate OTLP attribute")
        if "stringValue" in value:
            result[key] = value["stringValue"]
    return result


def valid_id(value, size):
    return (isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(size) + "}", value)
            is not None and int(value, 16) != 0)


def read_otlp(path):
    """Read logging-otlp ResourceSpans messages, discarding all payload fields.

    A byte limit is a persistence boundary, not a claim that the application or
    SDK has stopped generating spans. Raw test logs remain private/ignored.
    """
    spans, reasons, consumed = [], [], 0
    with Path(path).open("rb") as stream:
        while True:
            raw = stream.readline(MAX_BYTES + 1)
            if not raw:
                break
            consumed += len(raw)
            if consumed > MAX_BYTES:
                reasons.append("OUTPUT_BYTE_LIMIT")
                break
            line = raw.decode("utf-8", errors="replace")
            start = line.find("{")
            if start < 0:
                continue
            try:
                message = json.loads(line[start:])
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict) or "resource" not in message or "scopeSpans" not in message:
                continue
            try:
                raw_resource = attributes(message["resource"].get("attributes", []))
            except ValueError:
                reasons.append("DUPLICATE_RESOURCE_ATTRIBUTE")
                continue
            resource = {key: raw_resource[value] for key, value in RESOURCE_KEYS.items() if value in raw_resource}
            for scope in message["scopeSpans"]:
                for span in scope.get("spans", []):
                    try:
                        attrs = attributes(span.get("attributes", []))
                    except ValueError:
                        reasons.append("DUPLICATE_SPAN_ATTRIBUTE")
                        continue
                    trace, span_id = span.get("traceId"), span.get("spanId")
                    parent = span.get("parentSpanId") or None
                    if not valid_id(trace, 32) or not valid_id(span_id, 16) or (parent and not valid_id(parent, 16)):
                        reasons.append("INVALID_SPAN_ID")
                        continue
                    links = [{"traceId": link["traceId"], "spanId": link["spanId"]}
                             for link in span.get("links", [])
                             if valid_id(link.get("traceId"), 32) and valid_id(link.get("spanId"), 16)]
                    spans.append({"traceId": trace, "spanId": span_id, "parentSpanId": parent,
                                  "resource": resource, "class": attrs.get("code.namespace"),
                                  "method": attrs.get("code.function"), "links": links,
                                  "startTimeUnixNano": span.get("startTimeUnixNano"),
                                  "endTimeUnixNano": span.get("endTimeUnixNano"),
                                  "error": span.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR")})
    return {"spans": spans, "collectionReasons": sorted(set(reasons)), "consumedBytes": consumed,
            "policy": "allowlist-v1; arguments, return bodies, SQL, URL, events and exception messages discarded"}


def query(index, collection, trace_id, telemetry_config=None, per_trace_limit=100):
    if not valid_id(trace_id, 32) or not isinstance(per_trace_limit, int) or per_trace_limit < 1:
        raise ValueError("Invalid trace ID or collection limit")
    if index is None:
        return {"status": "UNRESOLVED", "reason": "HISTORY_NOT_COLLECTED", "traceId": trace_id}
    validate_index(index)
    if not isinstance(telemetry_config, str) or not HEX64.fullmatch(telemetry_config):
        return {"status": "UNRESOLVED", "reason": "MISSING_TELEMETRY_CONFIG",
                "traceId": trace_id, "analysisRunId": index["analysisRunId"]}
    reasons = set(collection["collectionReasons"])
    candidates = {}
    for item in index["methods"]:
        candidates.setdefault((item["class"], item["name"]), []).append(item)
    selected, seen, rejected = [], {}, []
    for item in collection["spans"]:
        if item["traceId"] != trace_id:
            continue
        try:
            identity = build_identity(item["resource"])
        except ValueError:
            rejected.append({"spanId": item["spanId"], "reason": "MISSING_BUILD_IDENTITY"})
            continue
        if identity != index["buildIdentity"]:
            rejected.append({"spanId": item["spanId"], "reason": "BUILD_IDENTITY_MISMATCH"})
            continue
        if item["resource"].get("configSha256") != telemetry_config:
            rejected.append({"spanId": item["spanId"], "reason": "TELEMETRY_CONFIG_MISMATCH"})
            continue
        span_id = item["spanId"]
        if span_id in seen:
            if seen[span_id] != item:
                raise ValueError("Conflicting span replay")
            continue
        seen[span_id] = item
        if len(selected) >= per_trace_limit:
            reasons.add("PER_TRACE_RECORD_LIMIT")
            continue
        possible = candidates.get((item["class"], item["method"]), [])
        record = dict(item)
        record["symbolCandidates"] = possible
        record["symbolStatus"] = ("unique-name-resolved" if len(possible) == 1
                                  else "UNRESOLVED_CODE_SYMBOL")
        record["symbolReason"] = ("sole class/name candidate in this exact index; descriptor derived"
                                  if len(possible) == 1 else "OTel method span supplies no JVM descriptor")
        selected.append(record)
    present = {item["spanId"] for item in selected}
    edges = [{"parentSpanId": item["parentSpanId"], "childSpanId": item["spanId"],
              "relation": "observed-span-parent", "parentState": "collected" if item["parentSpanId"] in present
              else "external-or-not-collected"}
             for item in selected if item["parentSpanId"]]
    if any(edge["parentState"] == "external-or-not-collected" for edge in edges):
        reasons.add("PARENT_EXTERNAL_OR_NOT_COLLECTED")
    reasons.update(item["reason"] for item in rejected)
    if not selected:
        reasons.add("NO_MATCHING_SPANS")
    # Missing spans alone cannot distinguish sampling, out-of-scope, native,
    # exporter loss or an unexecuted path. Independent controls supply that cause.
    return {"status": "OBSERVED" if selected and not reasons else "PARTIAL" if selected else
            "MISMATCH" if "BUILD_IDENTITY_MISMATCH" in reasons else "UNRESOLVED",
            "traceId": trace_id, "analysisRunId": index["analysisRunId"],
            "indexSha256": index["indexSha256"], "analysisConfigSha256": index["configSha256"],
            "buildIdentity": index["buildIdentity"], "spans": selected, "edges": edges,
            "rejected": rejected, "collectionReasons": sorted(reasons),
            "limitations": ["Span parentage is observed context, not proof of a synchronous source call.",
                            "No spans does not prove non-execution; collection completeness needs an independent oracle."]}
