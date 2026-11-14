"""Fail-closed whole-analysis cache; it does not implement incremental CHA."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

MAX_BYTES = 10 * 1024 * 1024
SCHEMA = "jjamtong.analysis-reuse.v1"
ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "java-call-analysis"
ENVIRONMENT_OPTIONS = ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS")


@dataclass(frozen=True)
class AnalysisRequest:
    tenant: str
    source_root: Path
    artifact: Path
    metadata: Path
    module: str
    java_home: Path
    include_package: str = "fixture.board"
    entrypoint: str = "fixture.board.Main"
    artifact_format: str = "plain"
    entrypoint_policy: str = "main"
    exclude_packages: tuple[str, ...] = ("fixture.board.excluded",)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _file_digest(path: Path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _bounded_json(path, label):
    with Path(path).open("rb") as stream:
        encoded = stream.read(MAX_BYTES + 1)
    if len(encoded) > MAX_BYTES:
        raise ValueError(label + " exceeds 10 MiB")
    try:
        return json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as failure:
        raise ValueError(label + " is not valid JSON") from failure


def _source_files(root: Path):
    if not root.is_dir():
        raise ValueError("source-root must be a directory")
    files = {}
    for path in sorted(root.rglob("*.java")):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        files[name] = _file_digest(path)
    if not files:
        raise ValueError("source-root has no .java files")
    return files


def _source_digest(files):
    return hashlib.sha256("".join(name + "\0" + value + "\n" for name, value in files.items()).encode()).hexdigest()


def _identity(manifest):
    fields = ("repository", "revision", "build", "module", "artifactSha256")
    result = {}
    for field in fields:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError("missing or invalid build field: " + field)
        result[field] = value
    result["artifactSha256"] = result["artifactSha256"].lower()
    if len(result["artifactSha256"]) != 64 or any(char not in "0123456789abcdef" for char in result["artifactSha256"]):
        raise ValueError("invalid artifact digest")
    return result


def _tool_fingerprints(java_home: Path):
    targets = [Path(sys.executable), Path(__file__), ADAPTER / "analyze.py", ADAPTER / "target" / "java-call-analysis-0.1.0.jar"]
    targets.extend(sorted((ADAPTER / "target" / "dependency").glob("*.jar")))
    targets.extend(java_home / item for item in ("release", "bin/java", "lib/modules", "lib/jrt-fs.jar"))
    result = {}
    for target in targets:
        if not target.is_file():
            raise ValueError("required runner or JDK file is missing: " + str(target))
        result[str(target.resolve())] = _file_digest(target)
    return result


def _options(request):
    if not request.tenant.strip() or not request.module.strip():
        raise ValueError("tenant and module are required")
    if request.artifact_format not in ("plain", "spring-boot") or request.entrypoint_policy not in ("main", "all-included-methods"):
        raise ValueError("unsupported artifact format or entrypoint policy")
    if request.artifact_format == "plain" and request.entrypoint_policy != "main":
        raise ValueError("plain JAR analysis requires main entrypoint policy")
    if request.artifact_format == "spring-boot" and request.entrypoint_policy != "all-included-methods":
        raise ValueError("Spring Boot requires all-included-methods policy")
    return {"includePackage": request.include_package.rstrip("."), "entrypoint": request.entrypoint,
            "artifactFormat": request.artifact_format, "entrypointPolicy": request.entrypoint_policy,
            "excludedPackages": sorted({item.rstrip(".") for item in request.exclude_packages})}


def _snapshot(request: AnalysisRequest):
    for name in ENVIRONMENT_OPTIONS:
        if os.environ.get(name):
            raise ValueError(name + " must be empty; JVM arguments are not cache-keyed")
    options = _options(request)
    artifact, metadata = Path(request.artifact), Path(request.metadata)
    if not artifact.is_file() or not metadata.is_file():
        raise ValueError("artifact and metadata must be regular files")
    try:
        manifest = _bounded_json(metadata, "metadata")
    except OSError as failure:
        raise ValueError("metadata must be a JSON object") from failure
    if not isinstance(manifest, dict):
        raise ValueError("metadata must be a JSON object")
    identity = _identity(manifest)
    if identity["module"] != request.module or manifest.get("sourceState") != "clean":
        raise ValueError("manifest module mismatch or source is not clean")
    files = _source_files(Path(request.source_root))
    expected = manifest.get("sourceFiles")
    if not isinstance(expected, list):
        raise ValueError("manifest sourceFiles is required")
    expected_files = {}
    for item in expected:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str) or item["path"] in expected_files:
            raise ValueError("invalid manifest sourceFiles")
        expected_files[item["path"]] = item["sha256"].lower()
    if files != expected_files:
        raise ValueError("build manifest source set mismatch")
    artifact_digest = _file_digest(artifact)
    if artifact_digest != identity["artifactSha256"]:
        raise ValueError("artifact bytes mismatch")
    return {"identity": identity, "metadata": manifest, "sourceFiles": files, "sourceDigest": _source_digest(files),
            "artifactDigest": artifact_digest, "metadataDigest": _file_digest(metadata), "options": options,
            "toolchain": _tool_fingerprints(Path(request.java_home))}


def _key_spec(request, snap):
    # Build/revision and metadata bytes are provenance, not graph-computation inputs.
    return {"schema": SCHEMA, "tenant": request.tenant, "repository": snap["identity"]["repository"],
            "module": request.module, "sourceDigest": snap["sourceDigest"], "artifactDigest": snap["artifactDigest"],
            "options": snap["options"], "toolchain": snap["toolchain"]}


def _validate_body(body, request, snap):
    if not isinstance(body, dict) or body.get("schema") != "jjamtong.methods.v1" or body.get("module") != request.module:
        raise ValueError("cached analysis schema or module mismatch")
    if body.get("status") != "complete-with-limitations":
        raise ValueError("analyzer result is not complete-with-limitations")
    input_ = body.get("input", {})
    if input_.get("artifactSha256") != snap["artifactDigest"] or input_.get("sourceTreeSha256") != snap["sourceDigest"]:
        raise ValueError("cached analysis input mismatch")
    scope = body.get("scope", {})
    if scope.get("includePackage") != snap["options"]["includePackage"] or scope.get("excludedPackages") != snap["options"]["excludedPackages"]:
        raise ValueError("cached analysis scope mismatch")
    if not isinstance(body.get("provenance"), dict) or not isinstance(body.get("tools"), dict):
        raise ValueError("cached analysis provenance mismatch")
    if not isinstance(body.get("limitations"), list):
        raise ValueError("analysis limitations are missing")
    for name in ("javaparser", "wala"):
        tool = body["tools"].get(name)
        if not isinstance(tool, dict) or not isinstance(tool.get("version"), str):
            raise ValueError("analysis tool is missing: " + name)
        for field in ("methods", "calls", "unresolved", "excluded"):
            if not isinstance(tool.get(field), list):
                raise ValueError("analysis collection is missing: " + name + "." + field)
        if not tool["methods"] or not tool["calls"]:
            raise ValueError("analysis tool has an empty inventory: " + name)


def _cached_body(result):
    body = dict(result)
    body.pop("metadata", None)
    input_ = dict(body.get("input", {}))
    input_.pop("metadataInputSha256", None)
    body["input"] = input_
    return body


def _load_cache(path, key, request, snap):
    envelope = _bounded_json(path, "corrupt cache")
    if not isinstance(envelope, dict) or envelope.get("schema") != SCHEMA or envelope.get("key") != key or envelope.get("keySpec") != _key_spec(request, snap):
        raise ValueError("corrupt cache: key mismatch")
    body = envelope.get("analysis")
    if envelope.get("contentSha256") != _digest(body):
        raise ValueError("corrupt cache: content digest mismatch")
    _validate_body(body, request, snap)
    return body


def _publish_exclusive(destination: Path, data: bytes):
    if destination.exists():
        raise FileExistsError("new output must not already exist: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".analysis-reuse-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _run_analyzer(request, temporary_output: Path):
    options = _options(request)
    command = [sys.executable, str(ADAPTER / "analyze.py"), "--java-home", str(request.java_home),
               "--source-root", str(request.source_root), "--artifact", str(request.artifact), "--metadata", str(request.metadata),
               "--module", request.module, "--output", str(temporary_output), "--include-package", options["includePackage"],
               "--entrypoint", options["entrypoint"], "--artifact-format", options["artifactFormat"],
               "--entrypoint-policy", options["entrypointPolicy"]]
    for package in options["excludedPackages"]:
        command.extend(("--exclude-package", package))
    # The public CLI reserves stdout for its machine-readable receipt.
    subprocess.run(command, check=True, stdout=sys.stderr)


def _output(body, snap):
    value = dict(body)
    value["metadata"] = snap["metadata"]
    input_ = dict(value["input"]); input_["metadataInputSha256"] = snap["metadataDigest"]; value["input"] = input_
    return value


@contextmanager
def _key_lock(path):
    """POSIX advisory lock; the kernel releases it if an analyzer process dies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        deadline = time.monotonic() + 75
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("same-key analysis lock exceeded 75 seconds")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def execute(request: AnalysisRequest, cache: Path, output: Path):
    """Run or reuse an exact complete analysis; return a JSON-serializable receipt."""
    if Path(output).exists():
        raise FileExistsError("new output must not already exist: " + str(output))
    started = time.monotonic(); snap = _snapshot(request); input_seconds = time.monotonic() - started
    key = _digest(_key_spec(request, snap)); cache_path = Path(cache) / (key + ".json")
    analysis_seconds = 0.0; origin = "reused"
    with _key_lock(cache_path.with_suffix(".lock")):
        # A waiter rechecks after the writer completes, avoiding duplicate JVMs.
        if cache_path.exists():
            body = _load_cache(cache_path, key, request, snap)
        else:
            origin = "analyzed"; analysis_started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="jjamtong-analysis-reuse-") as directory:
                temporary_output = Path(directory) / "analysis.json"
                _run_analyzer(request, temporary_output)
                if not temporary_output.is_file():
                    raise ValueError("analyzer did not produce a bounded result")
                result = _bounded_json(temporary_output, "analyzer result")
            analysis_seconds = time.monotonic() - analysis_started
            after = _snapshot(request)
            if after != snap: raise ValueError("analysis inputs changed during analysis")
            body = _cached_body(result); _validate_body(body, request, snap)
            envelope = {"schema": SCHEMA, "key": key, "keySpec": _key_spec(request, snap), "analysis": body, "contentSha256": _digest(body)}
            encoded = (_json(envelope) + "\n").encode()
            if len(encoded) > MAX_BYTES: raise ValueError("cache envelope exceeds 10 MiB")
            try: _publish_exclusive(cache_path, encoded)
            except FileExistsError:
                body = _load_cache(cache_path, key, request, snap); origin = "reused"
    publish_started = time.monotonic(); final = _output(body, snap)
    encoded = (json.dumps(final, indent=2, ensure_ascii=False) + "\n").encode()
    if len(encoded) > MAX_BYTES: raise ValueError("analysis output exceeds 10 MiB")
    # Recheck even on hits; every request reads semantic inputs before publication.
    if _snapshot(request) != snap: raise ValueError("analysis inputs changed before publication")
    _publish_exclusive(Path(output), encoded)
    return {"status": origin, "cacheKey": key, "inputSeconds": input_seconds, "analysisSeconds": analysis_seconds,
            "publishSeconds": time.monotonic() - publish_started, "resultBytes": len(encoded), "sourceCacheOrigin": origin}
