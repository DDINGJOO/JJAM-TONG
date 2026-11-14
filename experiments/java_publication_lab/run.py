"""Compare local representations of one already-produced Java result.

This is a representation experiment: it neither runs the Java analyzer nor
publishes to a database or a remote service.  Its report deliberately contains
only fixture-relative identifiers and digests, never source content or paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import Callable

from experiments.analysis_job_lab.model import Budget
from experiments.analysis_job_lab.publication import OutputLimit
from experiments.java_publication_lab.formats import (DEFAULT_MAX_BYTES, publish_compact,
                                                       publish_parts, read_parts)
from tools.evidence_store.contracts import prepare
from tools.method_evidence.evidence import create_index, file_digest


RAW_LIMITS = (10 * 1024 * 1024, 32 * 1024 * 1024)
PART_BUDGET = Budget(max_total_bytes=64 * 1024 * 1024, max_chunk_bytes=1024 * 1024,
                     max_record_bytes=128 * 1024, max_manifest_bytes=1024 * 1024,
                     max_chunks=4096, max_file_bytes=10 * 1024 * 1024)


def _measure(action: Callable[[], object]) -> tuple[object, int]:
    started = time.perf_counter_ns()
    value = action()
    return value, time.perf_counter_ns() - started


def _count(analysis: dict) -> dict[str, int]:
    return {field: sum(len(analysis["tools"][tool][field]) for tool in ("javaparser", "wala"))
            for field in ("methods", "calls", "unresolved", "excluded")}


def _index(analysis: dict, metadata: dict, fixture: Path) -> dict:
    return create_index(analysis, metadata, fixture / "fixture.jar", fixture / "sources", "actual-400k")


def _boundary(index: dict, directory: Path) -> dict[str, str]:
    outcomes = {}
    from tools.method_evidence.evidence import save_index
    for name, action in (("saveIndex", lambda: save_index(index, directory / "index")),
                         ("prepare", lambda: prepare(index))):
        try:
            action()
        except ValueError as failure:
            outcomes[name] = "rejected: " + str(failure)
        else:
            outcomes[name] = "accepted"
    return outcomes


def _counterexamples(analysis, directory, key):
    attempt = "attempt-actual-400k"
    outcomes = {}
    retry = publish_parts(analysis, directory, key, attempt, PART_BUDGET)
    if retry["created"]:
        raise AssertionError("identical retry replaced completion")
    outcomes["identicalRetry"] = "same immutable completion"
    for name, supplied_key, supplied_attempt in (("wrongInput", "f" * 64, attempt),
                                                ("wrongAttempt", key, "another-attempt")):
        try:
            read_parts(directory, supplied_key, supplied_attempt, PART_BUDGET)
        except ValueError:
            outcomes[name] = "rejected"
        else:
            raise AssertionError(name + " was accepted")
    manifest = json.loads((directory / "complete.json").read_bytes())
    part = directory / "objects" / (manifest["parts"][0]["sha256"] + ".jsonl")
    prior = part.read_bytes()
    try:
        for name in ("missingPart", "corruptPart"):
            if name == "missingPart":
                part.unlink()
            else:
                part.write_bytes(prior + b"corrupt")
            try:
                read_parts(directory, key, attempt, PART_BUDGET)
            except (ValueError, FileNotFoundError):
                outcomes[name] = "rejected"
            else:
                raise AssertionError(name + " was accepted")
            part.write_bytes(prior)
    finally:
        part.write_bytes(prior)
    try:
        read_parts(directory, key, attempt, Budget(max_total_bytes=1024 * 1024))
    except OutputLimit:
        outcomes["aggregateReadBudget"] = "rejected"
    else:
        raise AssertionError("aggregate budget was ignored")
    if read_parts(directory, key, attempt, PART_BUDGET) != analysis:
        raise AssertionError("restored original bundle changed")
    return outcomes


def compare(analysis_path: Path, fixture: Path, output: Path) -> dict:
    metadata_path, artifact, sources = fixture / "metadata.json", fixture / "fixture.jar", fixture / "sources"
    if not (analysis_path.is_file() and metadata_path.is_file() and artifact.is_file() and sources.is_dir()):
        raise ValueError("analysis and fixture must contain existing methods.json, metadata.json, fixture.jar and sources")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output must be new or empty; comparison never reuses an old checkpoint")
    output.mkdir(parents=True, exist_ok=True)
    raw = analysis_path.read_bytes()
    original, decode_ns = _measure(lambda: json.loads(raw))
    metadata = json.loads(metadata_path.read_bytes())
    original_index, raw_index_ns = _measure(lambda: _index(original, metadata, fixture))
    original_digest = original_index["indexSha256"]
    raw_cap = {str(limit): ("accepted" if len(raw) <= limit else "rejected: serialized result exceeds cap")
               for limit in RAW_LIMITS}

    compact_path = output / "compact.json"
    compact_size, compact_encode_ns = _measure(lambda: publish_compact(original, compact_path, DEFAULT_MAX_BYTES))
    compact, compact_decode_ns = _measure(lambda: json.loads(compact_path.read_bytes()))
    compact_index, compact_index_ns = _measure(lambda: _index(compact, metadata, fixture))

    # The bundle is private temporary state.  The report has aggregate numbers only.
    temporary = Path(tempfile.mkdtemp(prefix=".parts-", dir=output))
    try:
        input_identity = {"buildIdentity": original_index["buildIdentity"], "input": original["input"],
                          "config": original_index["config"], "provenance": original["provenance"],
                          "metadataSha256": file_digest(metadata_path)}
        input_key = hashlib.sha256(json.dumps(input_identity, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=True).encode()).hexdigest()
        summary, parts_encode_ns = _measure(
            lambda: publish_parts(original, temporary, input_key, "attempt-actual-400k", PART_BUDGET))
        parts, parts_decode_ns = _measure(
            lambda: read_parts(temporary, input_key, "attempt-actual-400k", PART_BUDGET))
        parts_index, parts_index_ns = _measure(lambda: _index(parts, metadata, fixture))
        counterexamples = _counterexamples(original, temporary, input_key)
    finally:
        shutil.rmtree(temporary)

    if original != compact or original != parts:
        raise AssertionError("representation changed logical JSON")
    if len({original_digest, compact_index["indexSha256"], parts_index["indexSha256"]}) != 1:
        raise AssertionError("representation changed index digest")

    index_bytes = {"pretty": len((json.dumps(original_index, ensure_ascii=False, indent=2) + "\n").encode()),
                   "default": len((json.dumps(original_index, ensure_ascii=False) + "\n").encode()),
                   "compact": len((json.dumps(original_index, ensure_ascii=False, separators=(",", ":")) + "\n").encode())}
    result = {
        "schema": "jjamtong.java-publication-comparison.v1",
        "representationOnly": True,
        "fixture": {"id": fixture.name, "metadataSha256": file_digest(metadata_path),
                    "artifactSha256": file_digest(artifact), "sourceTreeSha256": original["input"]["sourceTreeSha256"]},
        "analysis": {"schema": original["schema"], "adapterVersion": original["provenance"]["adapterVersion"],
                     "rawSha256": hashlib.sha256(raw).hexdigest(), "rawPrettyBytes": len(raw),
                     "recordCounts": _count(original)},
        "inputIdentity": input_identity,
        "inputKey": input_key,
        "inputKeyAssurance": "local canonical input/config digest; not publisher authentication or the common job-input wire schema",
        "config": {"compactMaxBytes": DEFAULT_MAX_BYTES, "partBudget": {"aggregateBytes": PART_BUDGET.max_total_bytes,
                   "partBytes": PART_BUDGET.max_chunk_bytes}, "rawByteCaps": list(RAW_LIMITS)},
        "representations": {
            "originalPretty": {"bytes": len(raw), "capOutcomes": raw_cap,
                               "decodeNanoseconds": decode_ns, "indexNanoseconds": raw_index_ns},
            "compact": {"bytes": compact_size, "encodeNanoseconds": compact_encode_ns,
                        "decodeNanoseconds": compact_decode_ns, "indexNanoseconds": compact_index_ns},
            "parts": {"bytes": summary["bytes"], "parts": summary["parts"], "records": summary["records"],
                      "encodeNanoseconds": parts_encode_ns, "decodeNanoseconds": parts_decode_ns,
                      "indexNanoseconds": parts_index_ns},
        },
        "logicalJsonEqual": True,
        "indexSha256": original_digest,
        "indexBytes": index_bytes,
        "consumerBoundary": _boundary(original_index, output),
        "fullResultCounterexamples": counterexamples,
        "processLifetimeRssBytes": None,
        "performanceNote": "One local process/sample; timings are descriptive and not a per-format performance ranking.",
    }
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.analysis, args.fixture, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
