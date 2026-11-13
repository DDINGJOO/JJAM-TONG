"""Engine-independent contracts over an immutable, explicitly selected analysis."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from tools.method_evidence.evidence import (HEX64, IDENTIFIER, MAX_BYTES, build_identity,
                                            method_key, query, validate_index)
from .validation import validate_schema

ANALYZERS = frozenset({"javaparser", "wala"})


class SnapshotConflict(ValueError):
    """An immutable run already exists with different content."""


class VersionMismatch(ValueError):
    """A repository or graph result belongs to a different analysis."""


class EvidenceTimeout(TimeoutError):
    """The repository could not establish a snapshot within its query budget."""


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid tenant or analysis run identifier")
    return value


def symbol(value):
    key = method_key(value) if isinstance(value, dict) else tuple(value)
    if len(key) != 4 or any(not isinstance(v, str) or not v.strip() or len(v) > 2048 for v in key):
        raise ValueError("Expected module, class, method name and JVM descriptor")
    return key


def symbol_json(value):
    return json.dumps(symbol(value), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class SnapshotRef:
    tenant: str
    run_id: str
    index_sha256: str

    def __post_init__(self):
        identifier(self.tenant)
        identifier(self.run_id)
        if not isinstance(self.index_sha256, str) or not HEX64.fullmatch(self.index_sha256):
            raise ValueError("Expected exact immutable index SHA-256")


@dataclass(frozen=True)
class GraphRequest:
    ref: SnapshotRef
    analyzer: str
    root: tuple
    max_depth: int = 4
    max_nodes: int = 200
    max_edges: int = 500

    def __post_init__(self):
        if self.analyzer not in ANALYZERS:
            raise ValueError("Choose javaparser or wala explicitly")
        if not isinstance(self.root, tuple) or symbol(self.root) != self.root:
            raise ValueError("Root must be an immutable four-field symbol tuple")
        for value, ceiling in ((self.max_depth, 12), (self.max_nodes, 5000), (self.max_edges, 10000)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("Graph budget out of range")


@dataclass
class GraphResult:
    request: GraphRequest
    status: str
    methods: list
    calls: list
    reasons: list
    coverage: dict


class AnalysisRepository(Protocol):
    def publish(self, tenant: str, index: dict) -> bool: ...
    def load(self, ref: SnapshotRef) -> dict | None: ...


class GraphQueryPort(Protocol):
    def walk(self, request: GraphRequest) -> GraphResult: ...


def prepare(index):
    """Validate imported snapshots and derive per-analyzer rows without inventing nodes.

    Digest verification detects altered bytes, not a malicious publisher. Inputs must
    already come from the local byte-verifying method_evidence index command.
    """
    if len(json.dumps(index, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Index exceeds the 10 MiB local import budget")
    validate_schema(index)
    validate_index(index)
    identifier(index["analysisRunId"])
    identity = build_identity(index["buildIdentity"])
    if set(index["staticEvidence"]) != ANALYZERS:
        raise ValueError("Expected both supported static analyzers")
    inventory = {symbol(item) for item in index["methods"]}
    derived, union = {}, set()
    for analyzer, tool in index["staticEvidence"].items():
        if not isinstance(tool.get("version"), str) or not tool["version"].strip():
            raise ValueError("Missing analyzer version")
        nodes = {symbol(item) for item in tool["methods"]}
        if any(key[0] != identity["module"] for key in nodes):
            raise ValueError("Method module differs from build identity")
        union.update(nodes)
        edges, dangling = [], 0
        for ordinal, call in enumerate(tool["calls"]):
            caller, target = symbol(call["caller"]), symbol(call["target"])
            if not isinstance(call.get("kind"), str) or not call["kind"].strip():
                raise ValueError("Missing static relation kind")
            if caller not in nodes or target not in nodes:
                dangling += 1
            else:
                edges.append((ordinal, symbol_json(caller), symbol_json(target), call))
        coverage = {"inventoryMethods": len(nodes), "inputCalls": len(tool["calls"]),
                    "indexedCalls": len(edges), "danglingCalls": dangling,
                    "unresolved": len(tool.get("unresolved", [])),
                    "excluded": len(tool.get("excluded", [])), "analyzerVersion": tool["version"]}
        derived[analyzer] = {"nodes": sorted(symbol_json(key) for key in nodes),
                             "edges": edges, "coverage": coverage}
    if union != inventory:
        raise ValueError("Analyzer inventories differ from the combined index inventory")
    return derived


class EvidenceReader:
    """Consumers depend on these ports, never on SQL or a graph engine client."""

    def __init__(self, repository: AnalysisRepository, graph: GraphQueryPort):
        self.repository, self.graph_port = repository, graph

    def _index(self, ref):
        index = self.repository.load(ref)
        if index is not None:
            validate_index(index)
            if index["analysisRunId"] != ref.run_id or index["indexSha256"] != ref.index_sha256:
                raise VersionMismatch("Repository returned another analysis")
        return index

    def graph(self, request):
        try:
            index = self._index(request.ref)
        except EvidenceTimeout:
            return GraphResult(request, "UNRESOLVED", [], [], ["TIME_BUDGET"], {})
        if index is None:
            return GraphResult(request, "UNRESOLVED", [], [], ["HISTORY_NOT_COLLECTED"], {})
        result = self.graph_port.walk(request)
        if result.request != request:
            raise VersionMismatch("Graph projection returned another analysis or query")
        return result

    def trace(self, ref, collection, trace_id, telemetry_config):
        return query(self._index(ref), collection, trace_id, telemetry_config)
