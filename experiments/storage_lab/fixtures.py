"""Deterministic, synthetic evidence and independent expected answers."""
import hashlib
import json
from collections import Counter

ANALYSIS = "analyzer-1.config-full.schema-1"
STRINGS = ("id", "tenant", "repo", "commit", "build", "artifact", "module",
           "analysis", "kind", "logical", "source", "target", "relation",
           "service", "level", "message", "trace_id")
NUMBERS = ("occurred", "known", "seq", "deleted")
FIELDS = STRINGS + NUMBERS


def scope(tenant="alpha", build="build-A", analysis=ANALYSIS):
    if not all((tenant, build, analysis)):
        raise ValueError("tenant, build and analysis are required")
    return tenant, build, analysis


def key(tenant, build, logical, analysis=ANALYSIS):
    return "/".join((tenant, build, analysis, logical))


def record(tenant, build, kind, logical, analysis=ANALYSIS, **values):
    row = {f: "" for f in STRINGS}
    row.update({f: 0 for f in NUMBERS})
    row.update(id=key(tenant, build, logical, analysis), tenant=tenant,
               repo="synthetic/community", commit="same-commit-for-A-and-B",
               build=build, artifact="sha256:" + hashlib.sha256(build.encode()).hexdigest(),
               module="community", analysis=analysis, kind=kind, logical=logical,
               occurred=100, known=100, seq=1)
    row.update(values)
    return row


def dataset(methods=150, events=1000):
    """methods is per tenant/build; events is total, across four scopes."""
    if methods < 25 or events < 20:
        raise ValueError("at least 25 methods and 20 events are required")
    rows = []
    for tenant in ("alpha", "beta"):
        for build in ("build-A", "build-B"):
            for i in range(methods):
                rows.append(record(tenant, build, "node", "method-%d" % i))
            rows.append(record(tenant, build, "node", "dispatcher"))
            pairs = {(i, i + 1) for i in range(methods - 1)}
            pairs |= {(i, i + 7) for i in range(0, methods - 7, 3)}
            pairs.add((17, 3))  # a cycle
            if build == "build-B":
                pairs.remove((0, 1))
                pairs.add((0, 2))
            for src, dst in sorted(pairs):
                rows.append(record(tenant, build, "edge", "call-%d-%d" % (src, dst),
                                   source=key(tenant, build, "method-%d" % src),
                                   target=key(tenant, build, "method-%d" % dst), relation="STATIC"))
            # A higher-degree entry point grows from 6 to 60 branches with scale.
            for dst in range(0, methods, 25):
                rows.append(record(tenant, build, "edge", "dispatch-%d" % dst,
                                   source=key(tenant, build, "dispatcher"),
                                   target=key(tenant, build, "method-%d" % dst), relation="STATIC"))
            assets = ("service", "deployment", "pod", "subnet", "vpc", "rds", "s3")
            rows.extend(record(tenant, build, "node", name) for name in assets)
            infra = (("method-0", "service"), ("service", "deployment"),
                     ("deployment", "pod"), ("pod", "subnet"), ("subnet", "vpc"),
                     ("pod", "rds"), ("service", "s3"))
            for src, dst in infra:
                rows.append(record(tenant, build, "edge", "infra-" + src + "-" + dst,
                                   source=key(tenant, build, src), target=key(tenant, build, dst),
                                   relation="INFRA"))
            # A request's observed calls remain separate from possible static calls.
            for i, (src, dst) in enumerate(((0, 3), (3, 9), (3, 12))):
                rows.append(record(tenant, build, "span", "span-%d" % i,
                                   source=key(tenant, build, "method-%d" % src),
                                   target=key(tenant, build, "method-%d" % dst),
                                   relation="OBSERVED", trace_id="trace-demo"))
    for i in range(events):
        tenant = "alpha" if i % 2 == 0 else "beta"
        build = "build-A" if (i // 2) % 2 == 0 else "build-B"
        rows.append(record(tenant, build, "event", "event-%d" % i,
                           service=("board", "activity", "identity", "media")[(i // 4) % 4],
                           level="ERROR" if i % 5 == 0 else "INFO",
                           message="kafka timeout synthetic" if i % 7 == 0 else "request completed synthetic",
                           occurred=1000 + i, known=1000 + i + (200 if i % 11 == 0 else 0)))
    # Same build, different analyzer configuration: never merge into full analysis.
    analysis = "analyzer-1.config-partial.schema-1"
    for logical in ("method-0", "method-24"):
        rows.append(record("alpha", "build-A", "node", logical, analysis))
    rows.append(record("alpha", "build-A", "edge", "partial-call", analysis,
                       source=key("alpha", "build-A", "method-0", analysis),
                       target=key("alpha", "build-A", "method-24", analysis), relation="STATIC"))
    return sorted(rows, key=lambda row: row["id"])


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def expected_reachable(rows, selected, start, depth, relation="STATIC", reverse=False):
    """Pure set closure: independent of SQL, Cypher or document adapters."""
    pairs = set()
    for r in rows:
        if (r["tenant"], r["build"], r["analysis"]) == selected and r["kind"] == "edge" and r["relation"] == relation and not r["deleted"]:
            pairs.add((r["target"], r["source"]) if reverse else (r["source"], r["target"]))
    seen, frontier = {start}, {start}
    for _ in range(depth):
        frontier = {b for a, b in pairs if a in frontier} - seen
        seen |= frontier
    return sorted(seen - {start})


def expected_events(rows, selected, token=None, known_before=None):
    return sorted(r["id"] for r in rows if (r["tenant"], r["build"], r["analysis"]) == selected
                  and r["kind"] == "event" and not r["deleted"]
                  and (token is None or token in r["message"].split())
                  and (known_before is None or r["known"] <= known_before))


def expected_counts(rows, selected):
    return dict(Counter(r["service"] for r in rows if (r["tenant"], r["build"], r["analysis"]) == selected
                        and r["kind"] == "event" and r["level"] == "ERROR" and not r["deleted"]))
