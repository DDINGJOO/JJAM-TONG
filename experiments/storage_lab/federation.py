"""Bounded multi-store integration: publish, lag detection, exact-build join."""
import argparse
import json
from pathlib import Path
import uuid

from .fixtures import key, record, scope
from .pipeline import Outbox
from .run import ROOT, assert_equal, compose, ready


def joined(primary, graph, search, graph_outbox, search_outbox, selected, expected_artifact):
    nodes = primary.select(selected, "node")
    if not nodes or any(r["artifact"] != expected_artifact for r in nodes):
        return {"status": "version_mismatch"}
    positions = {"graph": graph_outbox.watermark(), "search": search_outbox.watermark()}
    if any(value["status"] != "ready" for value in positions.values()):
        return {"status": "partial", "watermarks": positions}
    tenant, build, analysis = selected
    return {"status": "ready", "watermarks": positions, "build": build, "analysis": analysis,
            "artifact": expected_artifact,
            "static_candidates": graph.reachable(selected, key(tenant, build, "method-0", analysis), 1),
            "events": search.events(selected, "timeout")}


def run():
    compose("up", "-d", "postgres", "neo4j", "elasticsearch")
    primary = graph = search = None
    try:
        primary, graph, search = ready("postgres"), ready("neo4j"), ready("elasticsearch")
        stream = "federated-" + uuid.uuid4().hex[:8]
        graph_queue = Outbox(primary, graph, stream, stream + "-graph")
        search_queue = Outbox(primary, search, stream, stream + "-search")
        selected = scope(stream, "build-A")
        a, b = [record(stream, "build-A", "node", "method-%d" % i) for i in range(2)]
        edge = record(stream, "build-A", "edge", "call-0-1", source=a["id"], target=b["id"], relation="STATIC")
        event = record(stream, "build-A", "event", "event-0", message="synthetic timeout", service="board", level="ERROR")
        rows = [a, b, edge, event]
        for i, row in enumerate(rows):
            graph_queue.publish(stream + "-%d" % i, row)
        checks = []
        graph_queue.drain()
        partial = joined(primary, graph, search, graph_queue, search_queue, selected, a["artifact"])
        assert_equal(partial["status"], "partial", "one read model behind")
        assert_equal("static_candidates" in partial, False, "no silent complete join")
        checks.append("one-projection-behind-is-partial")
        search_queue.drain()
        complete = joined(primary, graph, search, graph_queue, search_queue, selected, a["artifact"])
        assert_equal(complete["status"], "ready", "both watermarks current")
        assert_equal(complete["static_candidates"], [b["id"]], "native graph projection")
        assert_equal(complete["events"], [event["id"]], "native search projection")
        checks.append("postgres-neo4j-elasticsearch-exact-build-join")
        assert_equal(joined(primary, graph, search, graph_queue, search_queue, selected, "sha256:wrong"), {"status": "version_mismatch"}, "wrong artifact cannot join")
        checks.append("artifact-mismatch-rejected")
        assert_equal(joined(primary, graph, search, graph_queue, search_queue, scope(stream, "unknown"), a["artifact"]), {"status": "version_mismatch"}, "no latest-build fallback")
        checks.append("unknown-build-has-no-latest-fallback")
        late = record(stream, "build-A", "event", "event-late", message="timeout late", known=300, occurred=120)
        graph_queue.publish(stream + "-late", late)
        graph_queue.drain()
        assert_equal(joined(primary, graph, search, graph_queue, search_queue, selected, a["artifact"])["status"], "partial", "lag after previous successful join")
        checks.append("new-write-invalidates-previous-ready-watermark")
        search_queue.drain()
        assert_equal(joined(primary, graph, search, graph_queue, search_queue, selected, a["artifact"])["events"], sorted([event["id"], late["id"]]), "late event reaches joined view")
        checks.append("catch-up-restores-joined-view")
        return {"checks": checks, "partial_example": partial, "ready_example": complete,
                "limits": ["single writer and consumer per projection", "no distributed snapshot during concurrent updates",
                           "no real policy engine or database tenant authorization", "no alias cutover or cloud deployment"]}
    finally:
        for store in (primary, graph, search):
            if store:
                store.close()
        compose("stop", "neo4j", "elasticsearch", "postgres")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results/storage-lab/federation.json")
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print("PASS federation checks=%d" % len(result["checks"]))


if __name__ == "__main__":
    main()
