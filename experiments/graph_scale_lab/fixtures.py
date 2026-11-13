"""Deterministic synthetic call-graph fixtures for scale experiments.

The rows produced here are deliberately synthetic.  They model immutable,
versioned graph inputs; they do not inspect or represent application source.
"""

import hashlib
import json
from collections import deque


_BLOCK_SIZE = 256
_LOCAL_OFFSETS = (1, 3, 7, 17, 31, 63)
_REVISIONS = ("old", "new")
_REQUIRED_METADATA = (
    "tenant",
    "repo",
    "commit",
    "build",
    "artifact",
    "analyzer",
    "schema",
    "config",
    "module_manifest",
)


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-blank string" % name)
    return value


def _validate_size(n, density):
    if not isinstance(n, int) or isinstance(n, bool) or n < 64:
        raise ValueError("n must be an integer of at least 64")
    if density not in range(2, 7):
        raise ValueError("density must be between 2 and 6")


def metadata(revision="old", repo="synthetic/community", config="full", artifact=None, size=None, density=None):
    """Return a complete, synthetic identity for one immutable graph version."""
    revision = _required_text(revision, "revision")
    repo = _required_text(repo, "repo")
    config = _required_text(config, "config")
    if revision not in _REVISIONS:
        raise ValueError("revision must be old or new")
    if artifact is not None:
        artifact = _required_text(artifact, "artifact")
    if size is not None or density is not None:
        _validate_size(size, density)
    return {
        "tenant": "alpha",
        "repo": repo,
        "commit": "synthetic-%s-commit" % revision,
        "build": "synthetic-%s-build" % revision,
        "artifact": artifact or "synthetic-%s-artifact" % revision,
        "analyzer": "synthetic-call-graph-v1",
        "schema": "graph-scale-lab/v1",
        "config": config,
        "module_manifest": "synthetic-module-manifest/v1",
        "fixture_input": "graph-scale/v1/n=%s/degree=%s" % (size, density),
    }


def scope_id(meta):
    """Hash the complete canonical graph identity, including the artifact."""
    if not isinstance(meta, dict):
        raise ValueError("meta must be a dictionary")
    for name in _REQUIRED_METADATA:
        _required_text(meta.get(name), name)
    artifact = meta.get("artifact")
    if artifact is not None:
        _required_text(artifact, "artifact")
    payload = json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def nodes(n):
    """Return n stable method identities spread over multiple synthetic modules."""
    _validate_size(n, 2)
    return [
        (idx, "module_%02d" % ((idx // 256) % 8), "method_%06d" % idx)
        for idx in range(n)
    ]


def _block_end(source, n):
    return min(((source // _BLOCK_SIZE) + 1) * _BLOCK_SIZE, n)


def _local_destination(source, offset, n):
    base = (source // _BLOCK_SIZE) * _BLOCK_SIZE
    block_length = _block_end(source, n) - base
    return base + ((source - base + offset) % block_length)


def _local_targets(source, n, density, revision):
    """Produce unique local destinations, even for a short final block."""
    targets = []
    used = set()
    for offset in _LOCAL_OFFSETS[:density]:
        adjusted = offset + (1 if revision == "new" and source % 97 == 0 else 0)
        target = _local_destination(source, adjusted, n)
        # A final block may be shorter than the requested fan-out.  Retain as
        # many unique cyclic targets as exist without expanding outside it.
        while target in used:
            adjusted += 1
            target = _local_destination(source, adjusted, n)
            if len(used) >= _block_end(source, n) - ((source // _BLOCK_SIZE) * _BLOCK_SIZE):
                break
        if target not in used:
            used.add(target)
            targets.append(target)
    return targets


def _observed_destination(source, n, density):
    """Use a deterministic destination distinct from either local version."""
    reserved = {source}
    reserved.update(_local_targets(source, n, density, "old"))
    reserved.update(_local_targets(source, n, density, "new"))
    next_base = ((source // _BLOCK_SIZE) + 1) * _BLOCK_SIZE
    if source % _BLOCK_SIZE == 17 and next_base + 3 < n:
        reserved.add(next_base + 3)
    target = (source * 37 + 11) % n
    while target in reserved:
        target = (target + 1) % n
    return target


def edges(n, density, revision="old"):
    """Return sorted synthetic STATIC and OBSERVED call-graph rows.

    STATIC rows use only local block offsets plus bounded bridge/hub rows, so
    the fixture remains linear in n rather than materialising an all-pairs graph.
    """
    _validate_size(n, density)
    revision = _required_text(revision, "revision")
    if revision not in _REVISIONS:
        raise ValueError("revision must be old or new")

    rows = set()
    for source in range(n):
        for target in _local_targets(source, n, density, revision):
            rows.add((source, target, "STATIC"))

    for base in range(0, n, _BLOCK_SIZE):
        next_base = base + _BLOCK_SIZE
        source = base + 17
        if source < n and next_base + 3 < n:
            rows.add((source, next_base + 3, "STATIC"))

    # These entries give node 0 broad, deterministic reach without adding a
    # quadratic fan-out.  Include at most 128 destinations across the graph.
    hub_count = min(128, max(0, n - 1))
    if hub_count:
        reserved = set(_local_targets(0, n, density, "old"))
        reserved.update(_local_targets(0, n, density, "new"))
        for index in range(1, hub_count + 1):
            target = (index * (n - 1)) // hub_count
            if target and target not in reserved:
                rows.add((0, target, "STATIC"))

    for source in range(0, n, 17):
        target = _observed_destination(source, n, density)
        while (source, target, "STATIC") in rows:
            target = (target + 1) % n
        rows.add((source, target, "OBSERVED"))
    return sorted(rows)


def oracle(edge_rows, start, depth, reverse=False, relation="STATIC"):
    """Return the bounded BFS result for one relation without graph helpers."""
    if not isinstance(start, int) or isinstance(start, bool):
        raise ValueError("start must be an integer")
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= 12:
        raise ValueError("depth must be between 1 and 12")
    _required_text(relation, "relation")

    adjacency = {}
    known = set()
    for source, target, edge_relation in edge_rows:
        known.add(source)
        known.add(target)
        if edge_relation == relation:
            origin, destination = (target, source) if reverse else (source, target)
            adjacency.setdefault(origin, set()).add(destination)
    if start not in known:
        raise ValueError("start must be a known node")

    visited = {start}
    reached = set()
    frontier = deque([(start, 0)])
    while frontier:
        current, current_depth = frontier.popleft()
        if current_depth == depth:
            continue
        for destination in adjacency.get(current, ()):
            if destination not in visited:
                visited.add(destination)
                reached.add(destination)
                frontier.append((destination, current_depth + 1))
    return sorted(reached)


def questions(n):
    _validate_size(n, 2)
    return [
        {"label": "entry_1", "start": 0, "depth": 1, "reverse": False, "relation": "STATIC"},
        {"label": "local_3", "start": min(300, n - 1), "depth": 3, "reverse": False, "relation": "STATIC"},
        {"label": "hub_6", "start": 0, "depth": 6, "reverse": False, "relation": "STATIC"},
        {"label": "reverse_6", "start": min(n - 1, n // 2 + 17), "depth": 6, "reverse": True, "relation": "STATIC"},
        {"label": "deep_12", "start": n // 3, "depth": 12, "reverse": False, "relation": "STATIC"},
        {"label": "observed_6", "start": 0, "depth": 6, "reverse": False, "relation": "OBSERVED"},
    ]


def _fingerprint_row(digest, row):
    digest.update(json.dumps(row, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    digest.update(b"\n")


def fingerprint(n, density):
    """Return a stable SHA-256 over both synthetic graph versions, streamed."""
    _validate_size(n, density)
    digest = hashlib.sha256()
    _fingerprint_row(digest, ("metadata", metadata("old", size=n, density=density)))
    _fingerprint_row(digest, ("metadata", metadata("new", size=n, density=density)))
    for row in nodes(n):
        _fingerprint_row(digest, ("node", row))
    for revision in _REVISIONS:
        for row in edges(n, density, revision):
            _fingerprint_row(digest, (revision, row))
    return digest.hexdigest()
