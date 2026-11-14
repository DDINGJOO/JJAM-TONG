"""Declared build manifests and local, fail-closed file verification.

The manifest records what a producer declares.  ``capture`` separately records
only the files that this process read safely; it does not authenticate the
producer or prove that a declared compiler input set is complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
from typing import Any


MANIFEST_SCHEMA = "jjamtong.build-manifest.v1"
SNAPSHOT_SCHEMA = "jjamtong.build-snapshot.v1"
VERIFIER_VERSION = "build-inventory-v1"
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_MANIFEST_LIMIT = 10 * 1024**2
_TOTAL_LIMIT = 2 * 1024**3
_FILE_LIMIT = 256 * 1024**2
_MAX_MODULES = 1000
_MAX_DEPENDENCIES = 10_000
_MAX_FILE_REFS = 50_000


def canonical_json(value: Any) -> bytes:
    """Encode JSON in the one byte representation used for identity hashes."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def canonical_path(value: str) -> str:
    """Return a safe, already-canonical, relative POSIX path."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("path must be a canonical relative POSIX path")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("path contains an invalid Unicode surrogate") from exc
    path = PurePosixPath(value)
    if path.is_absolute() or value in (".", "..") or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("unsafe path")
    if str(path) != value:
        raise ValueError("path is not canonical")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_no_duplicates(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"invalid {label} fields")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid {label}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"invalid {label}") from exc
    return value


def _timestamp(value: Any, label: str) -> str:
    value = _text(value, label)
    if len(value) != 27:
        raise ValueError(f"invalid {label}")
    try:
        parsed = datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if parsed.strftime(_UTC_FORMAT) != value:
        raise ValueError(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"invalid {label}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if value.lower() != value:
        raise ValueError(f"invalid {label}")
    return value


def _file_set(value: Any, label: str) -> list[dict[str, str]]:
    item = _exact(value, {"state", "files"}, label)
    if (not isinstance(item["state"], str) or item["state"] not in {"present", "not-applicable", "unavailable"}
            or not isinstance(item["files"], list)):
        raise ValueError(f"invalid {label}")
    files: list[dict[str, str]] = []
    paths: set[str] = set()
    for record in item["files"]:
        record = _exact(record, {"path", "sha256"}, f"{label} file")
        path = canonical_path(record["path"])
        digest = _digest(record["sha256"], f"{label} sha256")
        if path in paths:
            raise ValueError(f"duplicate {label} path")
        paths.add(path)
        files.append({"path": path, "sha256": digest})
    if item["state"] != "present" and files:
        raise ValueError(f"{label} state cannot contain files")
    return files


def _validate_manifest(document: Any) -> dict[str, Any]:
    manifest = _exact(document, {"schema", "repository", "revision", "build", "recordedAt", "producer", "moduleCoverage", "modules"}, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("unknown manifest schema")
    for key in ("repository", "revision", "build"):
        _text(manifest[key], key)
    _timestamp(manifest["recordedAt"], "recordedAt")
    producer = _exact(manifest["producer"], {"name", "version"}, "producer")
    _text(producer["name"], "producer name")
    _text(producer["version"], "producer version")
    if (not isinstance(manifest["moduleCoverage"], str) or manifest["moduleCoverage"] not in {"complete", "partial"}
            or not isinstance(manifest["modules"], list)):
        raise ValueError("invalid module coverage")
    if not 1 <= len(manifest["modules"]) <= _MAX_MODULES:
        raise ValueError("invalid module count")
    module_ids: set[str] = set()
    dependencies: list[tuple[str, str]] = []
    files_seen = 0
    for module in manifest["modules"]:
        module = _exact(module, {"id", "descriptor", "dependencies", "artifacts", "inputs"}, "module")
        module_id = _text(module["id"], "module id")
        if module_id in module_ids:
            raise ValueError("duplicate module id")
        module_ids.add(module_id)
        canonical_path(module["descriptor"])
        dependency = _exact(module["dependencies"], {"state", "modules"}, "dependencies")
        if (not isinstance(dependency["state"], str) or dependency["state"] not in {"present", "unavailable"}
                or not isinstance(dependency["modules"], list)):
            raise ValueError("invalid dependencies")
        if dependency["state"] == "unavailable" and dependency["modules"]:
            raise ValueError("unavailable dependencies cannot list modules")
        local_deps: set[str] = set()
        for target in dependency["modules"]:
            target = _text(target, "dependency module")
            if target in local_deps:
                raise ValueError("duplicate dependency module")
            local_deps.add(target)
            dependencies.append((module_id, target))
        artifact_files = _file_set(module["artifacts"], "artifacts")
        artifact_paths: set[str] = set()
        artifact_hashes: set[str] = set()
        for artifact in artifact_files:
            if artifact["path"] in artifact_paths or artifact["sha256"] in artifact_hashes:
                raise ValueError("duplicate artifact path or digest")
            artifact_paths.add(artifact["path"])
            artifact_hashes.add(artifact["sha256"])
        inputs = _exact(module["inputs"], {"sources", "generatedSources", "classpath", "toolchain", "conditions"}, "inputs")
        files_seen += len(artifact_files)
        for name in ("sources", "generatedSources", "classpath", "toolchain", "conditions"):
            files_seen += len(_file_set(inputs[name], f"inputs {name}"))
    if len(dependencies) > _MAX_DEPENDENCIES or files_seen > _MAX_FILE_REFS:
        raise ValueError("manifest exceeds reference limit")
    if manifest["moduleCoverage"] == "complete" and any(target not in module_ids for _, target in dependencies):
        raise ValueError("complete manifest has unresolved dependency")
    # Round-trip through canonical bytes copies the caller's nested values and
    # also enforces the manifest's string-only metadata contract.
    return _json_no_duplicates(canonical_json(manifest))


class SafeReader:
    """Descriptor-rooted reader which rejects symlinks and unstable files."""
    def __init__(self, root: os.PathLike[str] | str, *, total_limit: int = _TOTAL_LIMIT,
                 file_limit: int = _FILE_LIMIT) -> None:
        if type(total_limit) is not int or type(file_limit) is not int or total_limit < 0 or file_limit < 0:
            raise ValueError("invalid read limit")
        self.root = os.path.abspath(os.fspath(root))
        self.total_limit, self.file_limit = total_limit, file_limit
        self.checked_files = 0
        self.checked_bytes = 0
        self._root_fd: int | None = None

    def __enter__(self) -> "SafeReader":
        required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
        if os.name != "posix" or any(not hasattr(os, flag) for flag in required):
            raise ValueError("secure file verification unsupported")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.split(os.sep)[1:]:
                if not part:
                    continue
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            self._root_fd = fd
            return self
        except Exception:
            os.close(fd)
            raise ValueError("unsafe verification root") from None

    def __exit__(self, *_: Any) -> None:
        if self._root_fd is not None:
            os.close(self._root_fd)
            self._root_fd = None

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def _open(self, path: str, maximum: int) -> tuple[int, os.stat_result]:
        if self._root_fd is None:
            raise ValueError("SafeReader is not active")
        path = canonical_path(path)
        if maximum < 0 or maximum > self.file_limit:
            raise ValueError("file read exceeds limit")
        fd = os.dup(self._root_fd)
        try:
            pieces = path.split("/")
            for piece in pieces[:-1]:
                next_fd = os.open(piece, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            file_fd = os.open(pieces[-1], flags, dir_fd=fd)
            os.close(fd)
            fd = -1
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum or before.st_size > self.file_limit:
                os.close(file_fd)
                raise ValueError("unsafe or oversized file")
            if self.checked_bytes + before.st_size > self.total_limit:
                os.close(file_fd)
                raise ValueError("total read limit exceeded")
            return file_fd, before
        except OSError as exc:
            if fd >= 0:
                os.close(fd)
            raise ValueError("unsafe file path") from exc
        except Exception:
            if fd >= 0:
                os.close(fd)
            raise

    def _consume(self, path: str, maximum: int, digest: bool) -> bytes | str:
        fd, before = self._open(path, maximum)
        try:
            chunks: list[bytes] = []
            hasher = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("file changed while reading")
                remaining -= len(chunk)
                if digest:
                    hasher.update(chunk)
                else:
                    chunks.append(chunk)
            if self._identity(before) != self._identity(os.fstat(fd)):
                raise ValueError("file changed while reading")
            self.checked_files += 1
            self.checked_bytes += before.st_size
            return hasher.hexdigest() if digest else b"".join(chunks)
        finally:
            os.close(fd)

    def read_bytes(self, path: str, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int:
            raise ValueError("max_bytes must be an integer")
        result = self._consume(path, max_bytes, False)
        assert isinstance(result, bytes)
        return result

    def hash_file(self, path: str, *, max_bytes: int | None = None) -> str:
        if max_bytes is None:
            max_bytes = self.file_limit
        if type(max_bytes) is not int:
            raise ValueError("max_bytes must be an integer")
        result = self._consume(path, max_bytes, True)
        assert isinstance(result, str)
        return result


def _verification(manifest_sha256: str, verified_at: str, reader: SafeReader) -> dict[str, Any]:
    return {
        "manifestSha256": manifest_sha256,
        "verifierVersion": VERIFIER_VERSION,
        "verifiedAt": verified_at,
        "mode": "POSIX_FD_NOFOLLOW",
        "checkedFiles": reader.checked_files,
        "checkedBytes": reader.checked_bytes,
        "limitations": [
            "declared manifest only", "per-file verification is not global filesystem atomicity",
            "does not prove complete compiler inputs or source-to-artifact provenance",
        ],
    }


def _validate_verification(value: Any, manifest_sha256: str) -> dict[str, Any]:
    envelope = _exact(value, {"manifestSha256", "verifierVersion", "verifiedAt", "mode", "checkedFiles", "checkedBytes", "limitations"}, "verification")
    if _digest(envelope["manifestSha256"], "verification manifest digest") != manifest_sha256:
        raise ValueError("verification manifest digest mismatch")
    _text(envelope["verifierVersion"], "verifier version")
    _timestamp(envelope["verifiedAt"], "verifiedAt")
    if envelope["mode"] != "POSIX_FD_NOFOLLOW":
        raise ValueError("unsupported verification mode")
    for field in ("checkedFiles", "checkedBytes"):
        if type(envelope[field]) is not int or envelope[field] < 0:
            raise ValueError(f"invalid {field}")
    if not isinstance(envelope["limitations"], list) or not all(isinstance(item, str) for item in envelope["limitations"]):
        raise ValueError("invalid verification limitations")
    return _json_no_duplicates(canonical_json(envelope))


@dataclass(frozen=True, init=False)
class Snapshot:
    tenant: str
    manifest_json: str
    verification_json: str
    manifest_sha256: str
    verification_sha256: str

    def __init__(self, tenant: str, manifest_json: str, verification_json: str,
                 manifest_sha256: str, verification_sha256: str) -> None:
        _text(tenant, "tenant")
        if not isinstance(manifest_json, str) or not isinstance(verification_json, str):
            raise ValueError("snapshot JSON must be text")
        manifest_raw = manifest_json.encode("utf-8")
        verification_raw = verification_json.encode("utf-8")
        manifest = _validate_manifest(_json_no_duplicates(manifest_raw))
        if canonical_json(manifest) != manifest_raw or _sha256(manifest_raw) != _digest(manifest_sha256, "manifest digest"):
            raise ValueError("invalid manifest snapshot")
        verification = _validate_verification(_json_no_duplicates(verification_raw), manifest_sha256)
        if canonical_json(verification) != verification_raw or _sha256(verification_raw) != _digest(verification_sha256, "verification digest"):
            raise ValueError("invalid verification snapshot")
        object.__setattr__(self, "tenant", tenant)
        object.__setattr__(self, "manifest_json", manifest_json)
        object.__setattr__(self, "verification_json", verification_json)
        object.__setattr__(self, "manifest_sha256", manifest_sha256)
        object.__setattr__(self, "verification_sha256", verification_sha256)

    @property
    def document(self) -> dict[str, Any]:
        return _json_no_duplicates(self.manifest_json.encode("utf-8"))

    @property
    def verification(self) -> dict[str, Any]:
        return _json_no_duplicates(self.verification_json.encode("utf-8"))

    @property
    def repository(self) -> str:
        return self.document["repository"]

    @property
    def revision(self) -> str:
        return self.document["revision"]

    @property
    def build(self) -> str:
        return self.document["build"]

    @property
    def modules(self) -> list[dict[str, Any]]:
        return self.document["modules"]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SNAPSHOT_SCHEMA, "tenant": self.tenant, "manifest": self.document,
                "manifestSha256": self.manifest_sha256, "verification": self.verification,
                "verificationSha256": self.verification_sha256}


def capture(document: Any, root: os.PathLike[str] | str, tenant: str,
            verified_at: str | None = None) -> Snapshot:
    manifest = _validate_manifest(document)
    manifest_json = canonical_json(manifest).decode("utf-8")
    manifest_sha256 = _sha256(manifest_json.encode("utf-8"))
    verified_at = (datetime.now(timezone.utc).strftime(_UTC_FORMAT) if verified_at is None
                   else _timestamp(verified_at, "verifiedAt"))
    with SafeReader(root) as reader:
        for module in manifest["modules"]:
            for artifact in module["artifacts"]["files"]:
                if reader.hash_file(artifact["path"]) != artifact["sha256"]:
                    raise ValueError("declared file digest mismatch")
            for file_set in module["inputs"].values():
                for item in file_set["files"]:
                    if reader.hash_file(item["path"]) != item["sha256"]:
                        raise ValueError("declared file digest mismatch")
        verification = _verification(manifest_sha256, verified_at, reader)
    verification_json = canonical_json(_validate_verification(verification, manifest_sha256)).decode("utf-8")
    return Snapshot(tenant, manifest_json, verification_json, manifest_sha256,
                    _sha256(verification_json.encode("utf-8")))


def load_manifest(path: str, root: os.PathLike[str] | str, tenant: str) -> Snapshot:
    with SafeReader(root, file_limit=_MANIFEST_LIMIT) as reader:
        document = _json_no_duplicates(reader.read_bytes(path, max_bytes=_MANIFEST_LIMIT))
    return capture(document, root, tenant)


def save_snapshot(snapshot: Snapshot, path: os.PathLike[str] | str) -> None:
    if not isinstance(snapshot, Snapshot):
        raise ValueError("snapshot is required")
    encoded = canonical_json(snapshot.to_dict())
    if len(encoded) > _MANIFEST_LIMIT + 64 * 1024:
        raise ValueError("snapshot output exceeds limit")
    fd = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(encoded):
            offset += os.write(fd, encoded[offset:])
    finally:
        os.close(fd)


def load_snapshot(path: os.PathLike[str] | str) -> Snapshot:
    """Load one historical snapshot without rereading its declared files.

    ``path`` must be the caller-supplied absolute path to the snapshot.  Its
    parent is verified as the bounded descriptor-rooted reader root; the
    stored tenant remains a declaration, not an authentication decision.
    """
    snapshot_path = os.fspath(path)
    if not os.path.isabs(snapshot_path):
        raise ValueError("snapshot path must be absolute")
    parent, filename = os.path.dirname(snapshot_path), os.path.basename(snapshot_path)
    with SafeReader(parent, file_limit=_MANIFEST_LIMIT + 64 * 1024) as reader:
        stored = _json_no_duplicates(reader.read_bytes(filename, max_bytes=_MANIFEST_LIMIT + 64 * 1024))
    _exact(stored, {"schema", "tenant", "manifest", "manifestSha256", "verification", "verificationSha256"}, "snapshot")
    if stored["schema"] != SNAPSHOT_SCHEMA:
        raise ValueError("unknown snapshot schema")
    manifest_json = canonical_json(stored["manifest"]).decode("utf-8")
    verification_json = canonical_json(stored["verification"]).decode("utf-8")
    return Snapshot(stored["tenant"], manifest_json, verification_json,
                    stored["manifestSha256"], stored["verificationSha256"])


def link_analysis(snapshot: Snapshot, index: dict[str, Any], module_id: str, artifact_path: str,
                  index_sha256: str, config_sha256: str):
    """Bridge one explicitly selected declared artifact to the strict v1 model."""
    if not isinstance(snapshot, Snapshot):
        raise ValueError("snapshot is required")
    module_id = _text(module_id, "module id")
    artifact_path = canonical_path(artifact_path)
    module = next((item for item in snapshot.modules if item["id"] == module_id), None)
    if module is None or module["artifacts"]["state"] != "present":
        raise ValueError("declared present module artifact is required")
    selected = [item for item in module["artifacts"]["files"] if item["path"] == artifact_path]
    if len(selected) != 1:
        raise ValueError("explicit unique artifact selection is required")
    expected = {"repository": snapshot.repository, "revision": snapshot.revision,
                "build": snapshot.build, "module": module_id,
                "artifactSha256": selected[0]["sha256"]}
    from experiments.evidence_model_lab.model import import_v1, require_exact_bridge
    bridge = import_v1(index, snapshot.tenant)
    return require_exact_bridge(bridge, expected, index_sha256, config_sha256)
