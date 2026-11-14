"""Adapters for publishing the Java ``jjamtong.methods.v1`` result locally.

This module validates structure and preserves data; callers remain responsible
for obtaining and authorizing the exact input key used for publication.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from experiments.analysis_job_lab.model import Budget
from experiments.analysis_job_lab.publication import OutputLimit, iter_bundle, publish_bundle


SCHEMA = "jjamtong.methods.v1"
TOOLS = ("javaparser", "wala")
FIELDS = ("methods", "calls", "unresolved", "excluded")
STAGES = ("envelope",) + tuple(f"{tool}-{field}" for tool in TOOLS for field in FIELDS)
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_ENCODER = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_analysis(analysis: Any) -> dict[str, Any]:
    if not isinstance(analysis, dict) or analysis.get("schema") != SCHEMA:
        raise ValueError(f"analysis must be a {SCHEMA} object")
    tools = analysis.get("tools")
    if not isinstance(tools, dict) or set(tools) != set(TOOLS):
        raise ValueError("analysis tools must be exactly javaparser and wala")
    for tool in TOOLS:
        value = tools[tool]
        if not isinstance(value, dict):
            raise ValueError(f"{tool} must be an object")
        for field in FIELDS:
            records = value.get(field)
            if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
                raise ValueError(f"{tool}.{field} must be a list of objects")
    return analysis


def stages(analysis: dict[str, Any]) -> dict[str, Iterable[dict[str, Any]]]:
    """Split a valid result without changing record order or optional fields."""
    analysis = _validate_analysis(analysis)
    envelope = dict(analysis)
    envelope["tools"] = {
        tool: {key: value for key, value in analysis["tools"][tool].items() if key not in FIELDS}
        for tool in TOOLS
    }
    result: dict[str, Iterable[dict[str, Any]]] = {"envelope": (envelope,)}
    for tool in TOOLS:
        for field in FIELDS:
            result[f"{tool}-{field}"] = analysis["tools"][tool][field]
    return result


def _envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("envelope must be one methods.v1 object")
    tools = value.get("tools")
    if not isinstance(tools, dict) or set(tools) != set(TOOLS):
        raise ValueError("envelope tools must be exactly javaparser and wala")
    for tool in TOOLS:
        if not isinstance(tools[tool], dict) or any(field in tools[tool] for field in FIELDS):
            raise ValueError("envelope must not contain staged tool lists")
    return value


def restore(rows: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Restore an analysis result from the records returned by ``iter_bundle``."""
    envelope: dict[str, Any] | None = None
    records = {stage: [] for stage in STAGES[1:]}
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 2:
            raise ValueError("publication rows must be (stage, record) tuples")
        stage, record = row
        if stage not in STAGES:
            raise ValueError("unknown publication stage")
        if not isinstance(record, dict):
            raise ValueError("publication records must be objects")
        if stage == "envelope":
            if envelope is not None:
                raise ValueError("publication has multiple envelopes")
            envelope = _envelope(record)
        else:
            records[stage].append(record)
    if envelope is None:
        raise ValueError("publication is missing its envelope")

    restored = dict(envelope)
    restored_tools = {tool: dict(envelope["tools"][tool]) for tool in TOOLS}
    restored["tools"] = restored_tools
    for tool in TOOLS:
        for field in FIELDS:
            restored_tools[tool][field] = records[f"{tool}-{field}"]
    return _validate_analysis(restored)


def publish_parts(analysis: dict[str, Any], directory: str | Path, input_key: str, attempt: str,
                  budget: Budget = Budget()):
    """Publish the nine Java-result stages through the verified bundle format."""
    return publish_bundle(directory, input_key, attempt, STAGES, stages(analysis), budget)


def read_parts(directory: str | Path, input_key: str, attempt: str, budget: Budget = Budget()) -> dict[str, Any]:
    """Verify all parts with the existing bundle reader before restoring them."""
    return restore(iter_bundle(directory, input_key, attempt, STAGES, budget))


def publish_compact(analysis: dict[str, Any], destination: str | Path,
                    max_bytes: int = DEFAULT_MAX_BYTES) -> int:
    """Atomically write compact JSON plus a newline, subject to a byte cap.

    Encoding fragments and input values can still allocate memory; this is a
    serialized-output limit, not an operating-system memory guarantee.
    """
    _validate_analysis(analysis)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            for fragment in _ENCODER.iterencode(analysis):
                encoded = fragment.encode("utf-8")
                size += len(encoded)
                if size > max_bytes:
                    raise OutputLimit("compact JSON exceeds byte budget")
                stream.write(encoded)
            size += 1
            if size > max_bytes:
                raise OutputLimit("compact JSON exceeds byte budget")
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return size
    finally:
        temporary.unlink(missing_ok=True)
