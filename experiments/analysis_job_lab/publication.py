"""Local publication comparison, with immutable files and explicit completion.

The caller owns a trusted directory. This is not a distributed job executor,
authentication boundary, OS memory limiter or existing Java/DB wire format.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .model import Budget, Job, _verified_completion

SCHEMA = "jjamtong.analysis-bundle.v1"
SINGLE_SCHEMA = "jjamtong.analysis-single.v1"
ENCODER = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class OutputLimit(ValueError):
    """A record, part, aggregate, count or manifest budget was exceeded."""


class PublicationConflict(ValueError):
    """An immutable path already contains different bytes."""


def _line(value, limit):
    # A JSON encoder fragment (or the caller's record) may itself be large.
    # This bounds accepted bytes, not the producer's total memory allocation.
    pieces, size = [], 1
    for fragment in ENCODER.iterencode(value):
        encoded = fragment.encode("utf-8")
        size += len(encoded)
        if size > limit:
            raise OutputLimit("serialized record or manifest exceeds its byte budget")
        pieces.append(encoded)
    return b"".join(pieces) + b"\n"


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def _atomic(path, writer):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            if _hash_file(path) != _hash_file(temporary):
                raise PublicationConflict("immutable destination has different content")
            return False
    finally:
        temporary.unlink(missing_ok=True)


def _context(input_key, attempt, expected_stages, stages):
    if not isinstance(expected_stages, tuple):
        raise ValueError("expected stages must be a stable tuple")
    Job(input_key, attempt, tuple(expected_stages))  # Validate opaque IDs and scope.
    if set(stages) != set(expected_stages):
        raise ValueError("missing or unexpected analysis stage")
    return {"inputKey": input_key, "attempt": attempt, "expectedStages": list(expected_stages)}


def publish_single(directory, input_key, attempt, expected_stages, stages, budget=Budget(), checkpoint=lambda event: None):
    """Stream JSONL to a temporary file and publish only after its complete footer."""
    context = _context(input_key, attempt, expected_stages, stages)
    summary = {"bytes": 0, "records": 0}

    def write(stream):
        def emit(value, limit):
            encoded = _line(value, limit)
            if summary["bytes"] + len(encoded) > min(budget.max_total_bytes, budget.max_file_bytes):
                raise OutputLimit("single file exceeds file or total byte budget")
            stream.write(encoded)
            summary["bytes"] += len(encoded)

        emit({"type": "header", "schema": SINGLE_SCHEMA, **context}, budget.max_manifest_bytes)
        counts = {}
        for stage in expected_stages:
            counts[stage] = 0
            for record in stages[stage]:
                checkpoint("record")
                if not isinstance(record, dict):
                    raise ValueError("evidence record must be a JSON object")
                emit({"type": "record", "stage": stage, "record": record}, budget.max_record_bytes)
                counts[stage] += 1
                summary["records"] += 1
        emit({"type": "complete", "counts": counts}, budget.max_manifest_bytes)
        checkpoint("before-complete")

    summary["created"] = _atomic(Path(directory) / "result.jsonl", write)
    return summary


def publish_bundle(directory, input_key, attempt, expected_stages, stages, budget=Budget(), checkpoint=lambda event: None):
    """Store bounded immutable parts; the final manifest is the completion marker."""
    directory = Path(directory)
    context = _context(input_key, attempt, expected_stages, stages)
    parts, total_bytes, counts = [], 0, {}

    for stage in expected_stages:
        counts[stage] = 0

        def header():
            return _line({"schema": SCHEMA, "inputKey": input_key, "attempt": attempt,
                          "stage": stage, "ordinal": len(parts)}, budget.max_chunk_bytes)

        pieces, size, records = [header()], 0, 0
        size = len(pieces[0])

        def flush():
            nonlocal total_bytes
            if len(parts) >= budget.max_chunks:
                raise OutputLimit("part count exceeds budget")
            if total_bytes + size > budget.max_total_bytes:
                raise OutputLimit("parts exceed aggregate byte budget")
            encoded = b"".join(pieces)
            digest = hashlib.sha256(encoded).hexdigest()
            checkpoint("before-part")
            _atomic(directory / "objects" / (digest + ".jsonl"), lambda stream: stream.write(encoded))
            parts.append({"sha256": digest, "stage": stage, "bytes": size, "records": records})
            total_bytes += size
            checkpoint("after-part")

        for record in stages[stage]:
            checkpoint("record")
            if not isinstance(record, dict):
                raise ValueError("evidence record must be a JSON object")
            encoded = _line({"record": record}, budget.max_record_bytes)
            if size + len(encoded) > budget.max_chunk_bytes and records:
                flush()
                pieces, records = [header()], 0
                size = len(pieces[0])
            if size + len(encoded) > budget.max_chunk_bytes:
                raise OutputLimit("one record cannot fit in a part")
            pieces.append(encoded)
            size += len(encoded)
            records += 1
            counts[stage] += 1
        flush()  # An empty stage has an explicit, verifiable zero-record part.

    manifest = {"schema": SCHEMA, **context, "complete": True, "counts": counts,
                "parts": parts, "partsBytes": total_bytes, "totalRecords": sum(counts.values())}
    encoded = _line(manifest, min(budget.max_manifest_bytes, budget.max_file_bytes))
    if total_bytes + len(encoded) > budget.max_total_bytes:
        raise OutputLimit("parts and completion manifest exceed aggregate byte budget")
    checkpoint("before-complete")
    created = _atomic(directory / "complete.json", lambda stream: stream.write(encoded))
    return {"bytes": total_bytes + len(encoded), "partsBytes": total_bytes,
            "records": sum(counts.values()), "parts": len(parts),
            "manifestBytes": len(encoded), "created": created}


def _read(path, limit):
    with path.open("rb") as stream:
        encoded = stream.read(limit + 1)
    if len(encoded) > limit:
        raise OutputLimit("stored file exceeds read budget")
    return encoded


def _part(directory, manifest, part, ordinal, budget):
    digest = part.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid part digest")
    encoded = _read(directory / "objects" / (digest + ".jsonl"), budget.max_chunk_bytes)
    if hashlib.sha256(encoded).hexdigest() != digest or len(encoded) != part.get("bytes"):
        raise ValueError("part hash or size mismatch")
    lines = encoded.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") for line in lines):
        raise ValueError("incomplete part")
    expected = {"schema": SCHEMA, "inputKey": manifest["inputKey"], "attempt": manifest["attempt"],
                "stage": part.get("stage"), "ordinal": ordinal}
    if json.loads(lines[0]) != expected or part.get("stage") not in manifest["expectedStages"]:
        raise ValueError("part belongs to another input, attempt, stage or position")
    if type(part.get("records")) is not int or len(lines) - 1 != part["records"]:
        raise ValueError("part record count mismatch")
    for line in lines[1:]:
        if len(line) > budget.max_record_bytes:
            raise OutputLimit("stored record exceeds read budget")
        value = json.loads(line)
        if set(value) != {"record"} or not isinstance(value["record"], dict):
            raise ValueError("invalid evidence record")
    return lines[1:]


def _verify_manifest(directory, input_key, attempt, expected_stages, budget):
    """Validate every referenced part before returning any completion proof."""
    directory = Path(directory)
    context = _context(input_key, attempt, expected_stages, dict.fromkeys(expected_stages))
    encoded_manifest = _read(directory / "complete.json", min(budget.max_manifest_bytes, budget.max_file_bytes))
    manifest = json.loads(encoded_manifest)
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or manifest.get("complete") is not True:
        raise ValueError("invalid completion manifest")
    if any(manifest.get(key) != value for key, value in context.items()):
        raise ValueError("completion belongs to another input, attempt or scope")
    parts = manifest.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= budget.max_chunks:
        raise OutputLimit("invalid part count")
    counts, total, seen = Counter(), 0, set()
    for ordinal, part in enumerate(parts):
        if not isinstance(part, dict) or part.get("sha256") in seen:
            raise ValueError("invalid or duplicate part reference")
        _part(directory, manifest, part, ordinal, budget)
        seen.add(part["sha256"])
        total += part["bytes"]
        counts[part["stage"]] += part["records"]
        if total + len(encoded_manifest) > budget.max_total_bytes:
            raise OutputLimit("stored aggregate exceeds read budget")
    if (set(counts) != set(expected_stages) or dict(counts) != manifest.get("counts") or
            total != manifest.get("partsBytes") or sum(counts.values()) != manifest.get("totalRecords")):
        raise ValueError("completion coverage or totals mismatch")
    return manifest


def verify_bundle(directory, input_key, attempt, expected_stages, budget=Budget()):
    """Return a typed completion receipt only after verifying every stored byte."""
    _verify_manifest(directory, input_key, attempt, expected_stages, budget)
    return _verified_completion(input_key, attempt, expected_stages)


def iter_bundle(directory, input_key, attempt, expected_stages, budget=Budget()):
    """Verify completion first, then read each bounded part again for consumption.

    Consumers must commit derived state only after consuming the entire iterator.
    Shared-storage immutability, permissions and distributed fencing are separate.
    """
    directory = Path(directory)
    manifest = _verify_manifest(directory, input_key, attempt, expected_stages, budget)
    for ordinal, part in enumerate(manifest["parts"]):
        for line in _part(directory, manifest, part, ordinal, budget):
            yield part["stage"], json.loads(line)["record"]


def _single_records(directory, input_key, attempt, expected_stages, budget):
    context = _context(input_key, attempt, expected_stages, dict.fromkeys(expected_stages))
    total, counts = 0, dict.fromkeys(expected_stages, 0)
    with (Path(directory) / "result.jsonl").open("rb") as stream:
        encoded = stream.readline(budget.max_manifest_bytes + 1)
        if len(encoded) > budget.max_manifest_bytes:
            raise OutputLimit("single header exceeds budget")
        if json.loads(encoded) != {"type": "header", "schema": SINGLE_SCHEMA, **context}:
            raise ValueError("single file belongs to another input, attempt or scope")
        total += len(encoded)
        if total > min(budget.max_total_bytes, budget.max_file_bytes):
            raise OutputLimit("single file exceeds read budget")
        while True:
            encoded = stream.readline(max(budget.max_record_bytes, budget.max_manifest_bytes) + 1)
            if not encoded or not encoded.endswith(b"\n"):
                raise ValueError("single file has no complete footer")
            total += len(encoded)
            if total > min(budget.max_total_bytes, budget.max_file_bytes):
                raise OutputLimit("single file exceeds read budget")
            value = json.loads(encoded)
            if value.get("type") == "complete":
                if (len(encoded) > budget.max_manifest_bytes or value != {"type": "complete", "counts": counts}
                        or stream.read(1)):
                    raise ValueError("single completion coverage or boundary mismatch")
                return
            if len(encoded) > budget.max_record_bytes:
                raise OutputLimit("stored single record exceeds budget")
            stage = value.get("stage")
            if (set(value) != {"type", "stage", "record"} or value.get("type") != "record" or
                    stage not in counts or not isinstance(value.get("record"), dict)):
                raise ValueError("invalid single evidence record")
            counts[stage] += 1
            yield stage, value["record"]


def iter_single(directory, input_key, attempt, expected_stages, budget=Budget()):
    """Validate the whole file first; derived consumers must still commit at end."""
    for _ in _single_records(directory, input_key, attempt, expected_stages, budget):
        pass
    yield from _single_records(directory, input_key, attempt, expected_stages, budget)
