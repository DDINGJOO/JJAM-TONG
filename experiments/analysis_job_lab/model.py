"""Small, local contract model for analysis jobs; it is not an execution service."""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Optional


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_STAGE = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_PART_KIND = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_MAX_OPAQUE_LENGTH = 256
_REQUIRED_PART_KINDS = frozenset(
    {"source", "artifact", "dependencies", "generated", "configuration", "toolchain"}
)


def _opaque(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > _MAX_OPAQUE_LENGTH:
        raise ValueError(f"{name} must be a nonempty string up to {_MAX_OPAQUE_LENGTH} characters")


def _stage_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _STAGE.fullmatch(value):
        raise ValueError(f"{name} must match {_STAGE.pattern}")


@dataclass(frozen=True)
class InputPart:
    kind: str
    availability: str
    sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not _PART_KIND.fullmatch(self.kind):
            raise ValueError("kind must be a nonempty plain identifier")
        if not isinstance(self.availability, str) or self.availability not in {"present", "not-applicable", "unavailable"}:
            raise ValueError("availability must be present, not-applicable, or unavailable")
        if self.availability == "present":
            if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
                raise ValueError("present part requires a lowercase SHA-256")
        elif self.sha256 is not None:
            raise ValueError("non-present part must not have a SHA-256")

    def as_dict(self) -> dict[str, Optional[str]]:
        return {"kind": self.kind, "availability": self.availability, "sha256": self.sha256}


@dataclass(frozen=True)
class AnalysisInput:
    tenant: str
    repository: str
    revision: str
    build: str
    module: str
    analyzer: str
    analyzer_version: str
    result_schema: str
    parts: tuple[InputPart, ...]

    def __post_init__(self) -> None:
        for name in (
            "tenant", "repository", "revision", "build", "module", "analyzer",
            "analyzer_version", "result_schema",
        ):
            _opaque(getattr(self, name), name)
        if not isinstance(self.parts, tuple) or not all(isinstance(part, InputPart) for part in self.parts):
            raise ValueError("parts must be a tuple of InputPart values")
        kinds = [part.kind for part in self.parts]
        if len(kinds) != len(set(kinds)):
            raise ValueError("part kinds must be unique")
        missing = _REQUIRED_PART_KINDS.difference(kinds)
        if missing:
            raise ValueError(f"missing required part kinds: {', '.join(sorted(missing))}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractSchema": "jjamtong.analysis-job-input.v1",
            "tenant": self.tenant,
            "repository": self.repository,
            "revision": self.revision,
            "build": self.build,
            "module": self.module,
            "analyzer": self.analyzer,
            "analyzerVersion": self.analyzer_version,
            "resultSchema": self.result_schema,
            "parts": [part.as_dict() for part in sorted(self.parts, key=lambda part: part.kind)],
        }

    def key(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class Budget:
    max_total_bytes: int = 64 * 1024 * 1024
    max_chunk_bytes: int = 1024 * 1024
    max_record_bytes: int = 128 * 1024
    max_manifest_bytes: int = 1024 * 1024
    max_chunks: int = 4096
    max_file_bytes: int = 10 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_total_bytes", "max_chunk_bytes", "max_record_bytes", "max_manifest_bytes", "max_chunks", "max_file_bytes",
        ):
            _positive_int(getattr(self, name), name)
        if not self.max_record_bytes <= self.max_chunk_bytes <= self.max_total_bytes:
            raise ValueError("max_record_bytes <= max_chunk_bytes <= max_total_bytes is required")
        if self.max_chunk_bytes > self.max_file_bytes:
            raise ValueError("a chunk must fit the per-file budget")


class Status(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    UNSUPPORTED = "UNSUPPORTED"
    RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


_TERMINAL = frozenset({Status.COMPLETE, Status.UNSUPPORTED, Status.RESOURCE_EXCEEDED, Status.CANCELLED, Status.FAILED})
_TERMINABLE = frozenset({Status.UNSUPPORTED, Status.RESOURCE_EXCEEDED, Status.CANCELLED, Status.FAILED})


@dataclass(frozen=True, init=False)
class VerifiedCompletion:
    """A typed local verification result, not a publisher-authentication token."""
    input_key: str
    attempt: str
    expected_stages: tuple[str, ...]

    def __init__(self):
        raise TypeError("completion receipts are returned by verify_bundle")


def _verified_completion(input_key, attempt, expected_stages):
    # Private factory for the publication verifier. Python types are an API
    # misuse guard, not isolation from hostile code in this same process.
    receipt = object.__new__(VerifiedCompletion)
    for name, value in (("input_key", input_key), ("attempt", attempt), ("expected_stages", expected_stages)):
        object.__setattr__(receipt, name, value)
    return receipt


@dataclass
class Job:
    input_key: str
    attempt: str
    expected_stages: tuple[str, ...]
    previous_attempt: Optional[str] = None
    status: Status = field(default=Status.QUEUED, init=False)
    reason: Optional[str] = field(default=None, init=False)
    _completed_stages: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.input_key, str) or not _SHA256.fullmatch(self.input_key):
            raise ValueError("input_key must be a lowercase SHA-256")
        _stage_id(self.attempt, "attempt")
        if not isinstance(self.expected_stages, tuple) or not self.expected_stages:
            raise ValueError("expected_stages must be a nonempty tuple")
        for stage in self.expected_stages:
            _stage_id(stage, "stage")
        if len(self.expected_stages) != len(set(self.expected_stages)):
            raise ValueError("expected_stages must be unique")
        if self.previous_attempt is not None:
            _stage_id(self.previous_attempt, "previous_attempt")
            if self.previous_attempt == self.attempt:
                raise ValueError("previous_attempt must differ from attempt")

    def _assert_mutable(self) -> None:
        if self.status in _TERMINAL:
            raise ValueError("terminal jobs cannot change")

    def start(self) -> None:
        self._assert_mutable()
        if self.status is not Status.QUEUED:
            raise ValueError("only queued jobs can start")
        self.status = Status.RUNNING

    def stage_complete(self, stage: str) -> None:
        self._assert_mutable()
        if self.status not in {Status.RUNNING, Status.PARTIAL}:
            raise ValueError("stages can complete only while running or partial")
        _stage_id(stage, "stage")
        if stage not in self.expected_stages:
            raise ValueError("stage is not expected")
        self._completed_stages.add(stage)
        self.status = Status.PARTIAL

    def finish(self, receipt: VerifiedCompletion) -> None:
        self._assert_mutable()
        if self.status not in {Status.RUNNING, Status.PARTIAL}:
            raise ValueError("only running or partial jobs can finish")
        if set(self.expected_stages) != self._completed_stages:
            raise ValueError("all expected stages must complete before finish")
        if not isinstance(receipt, VerifiedCompletion):
            raise ValueError("completion requires a verified receipt, not a raw manifest")
        if (receipt.input_key != self.input_key or receipt.attempt != self.attempt or
                receipt.expected_stages != self.expected_stages):
            raise ValueError("verified completion does not match the job")
        self.status = Status.COMPLETE

    def terminate(self, status: Status, reason: str) -> None:
        self._assert_mutable()
        if not isinstance(status, Status) or status not in _TERMINABLE:
            raise ValueError("status is not a terminating failure status")
        if not isinstance(reason, str) or not reason:
            raise ValueError("termination reason must be nonempty")
        self.status = status
        self.reason = reason

    def retry(self, new_attempt: str) -> "Job":
        if self.status not in {Status.FAILED, Status.RESOURCE_EXCEEDED, Status.CANCELLED}:
            raise ValueError("only failed, resource-exceeded, or cancelled jobs can retry")
        _stage_id(new_attempt, "new_attempt")
        if new_attempt == self.attempt:
            raise ValueError("new_attempt must differ from attempt")
        return Job(self.input_key, new_attempt, self.expected_stages, previous_attempt=self.attempt)
