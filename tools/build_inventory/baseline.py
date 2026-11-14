"""Bounded comparisons for immutable declared build-inventory snapshots.

This module compares producer declarations only.  It intentionally does not
infer a build, runtime behaviour, or causal impact from a declared graph.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from typing import Any

from .inventory import Snapshot


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INPUT_NAMES = ("sources", "generatedSources", "classpath", "toolchain", "conditions")
_MAX_LIMIT = 1000
_MAX_EDGE_CHECKS = 10000
_MAX_PATH_DEPTH = 32
_MAX_SERIALIZED = 10 * 1024 * 1024


def _snapshot_ref(snapshot: Snapshot) -> dict[str, Any]:
    document = snapshot.document
    verification = json.loads(snapshot.verification_json)
    return {
        "tenant": snapshot.tenant,
        "repository": document["repository"],
        "revision": document["revision"],
        "build": document["build"],
        "manifestSha256": snapshot.manifest_sha256,
        "verificationSha256": snapshot.verification_sha256,
        "recordedAt": document["recordedAt"],
        "verifiedAt": verification["verifiedAt"],
        "verificationMode": verification["mode"],
    }


def _append(items: list[Any], value: Any, limit: int, limits: set[str]) -> None:
    if len(items) >= limit:
        limits.add("QUERY_LIMIT")
        return
    items.append(value)


def _module_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {module["id"]: module for module in document["modules"]}


def _declaration_identity(value: dict[str, Any]) -> dict[str, str]:
    """Keep reports bounded without discarding a compared declaration identity."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"state": value["state"], "declarationSha256": hashlib.sha256(encoded).hexdigest()}


def _unknown_module(module: dict[str, Any]) -> bool:
    if module["dependencies"]["state"] == "unavailable":
        return True
    if module["artifacts"]["state"] == "unavailable":
        return True
    return any(module["inputs"][name]["state"] == "unavailable" for name in _INPUT_NAMES)


def _edge_index(
    modules: dict[str, dict[str, Any]], budget: list[int], limits: set[str],
) -> tuple[set[tuple[str, str]], dict[str, list[str]], dict[str, set[str]]]:
    """Index declared edges once, sharing the comparison-wide edge budget."""
    edges: set[tuple[str, str]] = set()
    consumers: dict[str, list[str]] = {}
    outgoing: dict[str, set[str]] = {}
    for module_id, module in modules.items():
        dependencies = module["dependencies"]
        if dependencies["state"] != "present":
            continue
        for dependency in dependencies["modules"]:
            if budget[0] >= _MAX_EDGE_CHECKS:
                limits.add("TRAVERSAL_BUDGET")
                return edges, consumers, outgoing
            budget[0] += 1
            edges.add((module_id, dependency))
            consumers.setdefault(dependency, []).append(module_id)
            outgoing.setdefault(module_id, set()).add(dependency)
    for values in consumers.values():
        values.sort()
    return edges, consumers, outgoing


def _reverse_paths(
    target: str,
    consumers: dict[str, list[str]],
    side: str,
    limit: int,
    budget: list[int],
    limits: set[str],
) -> list[dict[str, Any]]:
    """Return consumer-to-target paths, with one bounded cycle-safe path per node."""
    paths: list[dict[str, Any]] = []
    queue: deque[list[str]] = deque([[target]])
    seen = {target}
    while queue:
        reverse_path = queue.popleft()  # target -> ... -> consumer
        if len(reverse_path) > _MAX_PATH_DEPTH:
            limits.add("PATH_DEPTH_LIMIT")
            continue
        for consumer in consumers.get(reverse_path[-1], ()):
            if budget[0] >= _MAX_EDGE_CHECKS:
                limits.add("TRAVERSAL_BUDGET")
                return paths
            budget[0] += 1
            if consumer in seen:
                continue
            seen.add(consumer)
            next_path = reverse_path + [consumer]
            if len(next_path) > _MAX_PATH_DEPTH:
                limits.add("PATH_DEPTH_LIMIT")
                continue
            _append(paths, {"side": side, "changedModule": target,
                            "path": list(reversed(next_path))}, limit, limits)
            if "QUERY_LIMIT" in limits:
                return paths
            queue.append(next_path)
    return paths


def _reason_changes(
    old: dict[str, Any], new: dict[str, Any], module_id: str,
    changes: list[dict[str, Any]], limit: int, limits: set[str],
) -> bool:
    changed = False
    if old["descriptor"] != new["descriptor"]:
        _append(changes, {"module": module_id, "reason": "DESCRIPTOR", "baseline": old["descriptor"],
                          "current": new["descriptor"]}, limit, limits)
        changed = True
    if old["artifacts"] != new["artifacts"]:
        _append(changes, {"module": module_id, "reason": "ARTIFACTS",
                          "baseline": _declaration_identity(old["artifacts"]),
                          "current": _declaration_identity(new["artifacts"])}, limit, limits)
        changed = True
    for name in _INPUT_NAMES:
        if old["inputs"][name] != new["inputs"][name]:
            _append(changes, {"module": module_id, "reason": "INPUT_" + name.upper(),
                              "baseline": _declaration_identity(old["inputs"][name]),
                              "current": _declaration_identity(new["inputs"][name])}, limit, limits)
            changed = True
    return changed


def compare(baseline: Snapshot, current: Snapshot, baseline_sha256: str,
            current_sha256: str, limit: int = 100) -> dict[str, Any]:
    """Compare two exactly pinned immutable snapshots in ``DECLARED`` mode.

    Missing coverage or unavailable declaration sets are retained as partial
    evidence.  Consequently this function never turns absence from such a set
    into proof that a module, dependency, artifact, or input does not exist.
    """
    if not isinstance(baseline, Snapshot) or not isinstance(current, Snapshot):
        raise ValueError("baseline and current must be validated Snapshot values")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
        raise ValueError("limit must be an integer from 1 through 1000")
    for label, supplied, snapshot in (("baseline", baseline_sha256, baseline),
                                      ("current", current_sha256, current)):
        if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied):
            raise ValueError(f"{label} manifest SHA-256 is invalid")
        if supplied != snapshot.manifest_sha256:
            raise ValueError(f"{label} manifest SHA-256 does not match snapshot")

    old_document = baseline.document
    new_document = current.document
    if baseline.tenant != current.tenant:
        raise ValueError("snapshots have different tenants")
    if old_document["repository"] != new_document["repository"]:
        raise ValueError("snapshots have different repositories")

    limitations: set[str] = set()
    old_modules = _module_map(old_document)
    new_modules = _module_map(new_document)
    old_ids, new_ids = set(old_modules), set(new_modules)
    changes: list[dict[str, Any]] = []
    added_modules: list[str] = []
    removed_modules: list[str] = []
    possibly_missing: list[dict[str, Any]] = []
    possibly_missing_edges: list[dict[str, str]] = []
    changed_targets: set[str] = set()

    complete_modules = (old_document["moduleCoverage"] == "complete" and
                        new_document["moduleCoverage"] == "complete")
    for module_id in sorted(new_ids - old_ids):
        if complete_modules:
            _append(added_modules, module_id, limit, limitations)
            changed_targets.add(module_id)
        else:
            _append(possibly_missing, {"module": module_id, "missingFrom": "baseline"}, limit, limitations)
            limitations.add("PARTIAL")
    for module_id in sorted(old_ids - new_ids):
        if complete_modules:
            _append(removed_modules, module_id, limit, limitations)
            changed_targets.add(module_id)
        else:
            _append(possibly_missing, {"module": module_id, "missingFrom": "current"}, limit, limitations)
            limitations.add("PARTIAL")

    for module_id in sorted(old_ids & new_ids):
        old, new = old_modules[module_id], new_modules[module_id]
        if _unknown_module(old) or _unknown_module(new):
            limitations.add("PARTIAL")
        if _reason_changes(old, new, module_id, changes, limit, limitations):
            changed_targets.add(module_id)

    # Declarations on added and removed modules are just as capable of making
    # the comparison partial as declarations on common modules.
    if any(_unknown_module(module) for module in (*old_modules.values(), *new_modules.values())):
        limitations.add("PARTIAL")

    if old_document["moduleCoverage"] != "complete" or new_document["moduleCoverage"] != "complete":
        limitations.add("PARTIAL")

    budget = [0]
    _, old_consumers, old_outgoing = _edge_index(old_modules, budget, limitations)
    _, new_consumers, new_outgoing = _edge_index(new_modules, budget, limitations)
    added_edges: list[dict[str, str]] = []
    removed_edges: list[dict[str, str]] = []

    def append_edge_change(destination: list[dict[str, str]], consumer: str, dependency: str) -> None:
        _append(destination, {"consumer": consumer, "dependency": dependency}, limit, limitations)
        changed_targets.update((consumer, dependency))

    def append_uncertain_edges(consumer: str, dependencies: set[str], missing_from: str) -> None:
        if not dependencies:
            return
        limitations.add("PARTIAL")
        for dependency in sorted(dependencies):
            _append(possibly_missing_edges,
                    {"consumer": consumer, "dependency": dependency, "missingFrom": missing_from},
                    limit, limitations)

    if "TRAVERSAL_BUDGET" not in limitations:
        for consumer in sorted(old_ids | new_ids):
            old, new = old_modules.get(consumer), new_modules.get(consumer)
            old_set, new_set = old_outgoing.get(consumer, set()), new_outgoing.get(consumer, set())
            if old is None:
                if old_document["moduleCoverage"] != "complete":
                    append_uncertain_edges(consumer, new_set, "baseline")
                elif new["dependencies"]["state"] == "present":
                    for dependency in sorted(new_set):
                        append_edge_change(added_edges, consumer, dependency)
                else:
                    limitations.add("PARTIAL")
                continue
            if new is None:
                if new_document["moduleCoverage"] != "complete":
                    append_uncertain_edges(consumer, old_set, "current")
                elif old["dependencies"]["state"] == "present":
                    for dependency in sorted(old_set):
                        append_edge_change(removed_edges, consumer, dependency)
                else:
                    limitations.add("PARTIAL")
                continue

            old_dependencies, new_dependencies = old["dependencies"], new["dependencies"]
            if old_dependencies["state"] == "present" and new_dependencies["state"] == "present":
                for dependency in sorted(new_set - old_set):
                    append_edge_change(added_edges, consumer, dependency)
                for dependency in sorted(old_set - new_set):
                    append_edge_change(removed_edges, consumer, dependency)
            elif old_dependencies["state"] == "present":
                append_uncertain_edges(consumer, old_set, "current")
            elif new_dependencies["state"] == "present":
                append_uncertain_edges(consumer, new_set, "baseline")
            else:
                limitations.add("PARTIAL")

    impacts: list[dict[str, Any]] = []
    for target in sorted(changed_targets):
        if "TRAVERSAL_BUDGET" in limitations or "QUERY_LIMIT" in limitations:
            break
        for side, consumers in (("baseline", old_consumers), ("current", new_consumers)):
            for path in _reverse_paths(target, consumers, side, limit, budget, limitations):
                _append(impacts, path, limit, limitations)
                if "TRAVERSAL_BUDGET" in limitations or "QUERY_LIMIT" in limitations:
                    break
            if "TRAVERSAL_BUDGET" in limitations or "QUERY_LIMIT" in limitations:
                break

    partial = bool(limitations)
    identity_changes = [
        {"field": field, "baseline": old_document[field], "current": new_document[field]}
        for field in ("revision", "build") if old_document[field] != new_document[field]
    ]
    has_changes = bool(changes or added_modules or removed_modules or added_edges or removed_edges or identity_changes)
    status = "PARTIAL" if partial else ("CHANGES" if has_changes else "NO_CHANGE_IN_AVAILABLE_EVIDENCE")
    report = {
        "schema": "jjamtong.build-baseline-comparison.v1",
        "mode": "DECLARED",
        "status": status,
        "baseline": _snapshot_ref(baseline),
        "current": _snapshot_ref(current),
        "changes": {
            "addedModules": added_modules,
            "removedModules": removed_modules,
            "moduleChanges": changes,
            "addedEdges": added_edges,
            "removedEdges": removed_edges,
            "impactPaths": impacts,
            "identityChanges": identity_changes,
        },
        "possiblyMissingModules": possibly_missing,
        "possiblyMissingEdges": possibly_missing_edges,
        "limitations": sorted(limitations),
        "notes": [
            "Declared build metadata only; this comparison does not establish runtime behavior or causality.",
            "recordedAt is producer-declared time; verifiedAt is local file-verification time.",
        ],
    }
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_SERIALIZED:
        raise ValueError("comparison report exceeds 10 MiB")
    return report
