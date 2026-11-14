"""Independent synthetic cases and optional retained public-artifact verification."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time

from tools.build_inventory.baseline import compare
from tools.build_inventory.discovery import discover_maven
from tools.build_inventory.inventory import (SafeReader, _json_no_duplicates, capture,
                                             link_analysis, load_snapshot, save_snapshot)

MAX_SIDECAR_BYTES = 10 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def file_set(state="present", files=()):
    return {"state": state, "files": list(files)}


def module(root, name, data, dependencies=()):
    path = name + ".bin"
    (root / path).write_bytes(data)
    return {"id": name, "descriptor": name + "/pom.xml",
            "dependencies": {"state": "present", "modules": list(dependencies)},
            "artifacts": file_set(files=[{"path": path, "sha256": sha(data)}]),
            "inputs": {key: file_set("not-applicable") for key in
                       ("sources", "generatedSources", "classpath", "toolchain", "conditions")}}


def document(modules, build="b1"):
    return {"schema": "jjamtong.build-manifest.v1", "repository": "synthetic:community",
            "revision": "synthetic-source-v1", "build": build,
            "recordedAt": "2026-11-14T03:00:00.000000Z",
            "producer": {"name": "independent-fixture", "version": "1"},
            "moduleCoverage": "complete", "modules": modules}


def rejected(operation):
    try:
        operation()
    except ValueError:
        return True
    return False


def check(case_id, expected, actual):
    return {"id": case_id, "expected": expected, "actual": actual, "pass": actual == expected}


def synthetic():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "pom.xml").write_text("<project><modules><module>shared</module><module>board</module></modules></project>")
        for name in ("shared", "board"):
            (root / name).mkdir()
            (root / name / "pom.xml").write_text("<project><artifactId>" + name + "</artifactId></project>")
        discovered = discover_maven(root)
        before_doc = document([module(root, "shared", b"shared-v1"),
                               module(root, "board", b"board-v1", ("shared",)),
                               module(root, "worker", b"worker-v1", ("shared",))])
        before = capture(before_doc, root, "synthetic-tenant",
                         verified_at="2026-11-14T03:01:00.000000Z")
        after_doc = copy.deepcopy(before_doc)
        after_doc["build"] = "b2"
        after_doc["modules"][0] = module(root, "shared", b"shared-v2")
        mismatch = rejected(lambda: capture(before_doc, root, "synthetic-tenant"))
        after = capture(after_doc, root, "synthetic-tenant",
                        verified_at="2026-11-14T03:02:00.000000Z")
        delta = compare(before, after, before.manifest_sha256, after.manifest_sha256)
        wrong_pin = rejected(lambda: compare(before, after, "f" * 64, after.manifest_sha256))
        partial_doc = copy.deepcopy(after_doc)
        partial_doc["moduleCoverage"] = "partial"
        partial_doc["modules"] = partial_doc["modules"][:1]
        partial_doc["modules"][0]["inputs"]["classpath"] = file_set("unavailable")
        partial = capture(partial_doc, root, "synthetic-tenant")
        missing = compare(before, partial, before.manifest_sha256, partial.manifest_sha256)
        path = root / "before.snapshot.json"
        save_snapshot(before, path)
        (root / "shared.bin").unlink()
        restored = load_snapshot(path)
        expected_paths = [
            {"side": "baseline", "changedModule": "shared", "path": ["board", "shared"]},
            {"side": "baseline", "changedModule": "shared", "path": ["worker", "shared"]},
            {"side": "current", "changedModule": "shared", "path": ["board", "shared"]},
            {"side": "current", "changedModule": "shared", "path": ["worker", "shared"]},
        ]
        cases = [check("BDD-BLD-001", ["pom.xml", "shared/pom.xml", "board/pom.xml"],
                       [item["descriptorPath"] for item in discovered["candidates"]]),
                 check("BDD-BLD-002", True, mismatch),
                 check("BDD-BLD-004-pin", True, wrong_pin),
                 check("BDD-BLD-004-paths", expected_paths, delta["changes"]["impactPaths"]),
                 check("BDD-BLD-004-module", [("shared", "ARTIFACTS")],
                       [(item["module"], item["reason"]) for item in delta["changes"]["moduleChanges"]]),
                 check("BDD-BLD-005-status", "PARTIAL", missing["status"]),
                 check("BDD-BLD-005-missing", [{"module": "board", "missingFrom": "current"},
                                               {"module": "worker", "missingFrom": "current"}],
                       missing["possiblyMissingModules"]),
                 check("BDD-BLD-006", before.to_dict(), restored.to_dict())]
        return {"cases": cases, "discovery": discovered, "baselineComparison": delta,
                "partialComparison": missing,
                "limitations": ["synthetic bytes, not compiled application artifacts",
                                "declared module graph, no actual request or causal claim"]}


def git(target, *args):
    deadline = time.monotonic() + 20
    output = bytearray()
    with subprocess.Popen(["git", "-C", str(target), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ValueError("git inspection timed out")
                    chunk = os.read(process.stdout.fileno(), min(65536, MAX_GIT_OUTPUT_BYTES + 1 - len(output)))
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > MAX_GIT_OUTPUT_BYTES:
                        raise ValueError("git inspection exceeded output limit")
            if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                raise ValueError("git inspection failed")
        except BaseException:
            process.kill()
            process.wait()
            raise
    return output.decode("utf-8").strip()


def read_fixture_json(evidence_root, path):
    root = Path(evidence_root).absolute()
    try:
        relative = Path(path).absolute().relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("sidecar must be inside the explicit public evidence root") from error
    with SafeReader(root, file_limit=MAX_SIDECAR_BYTES) as reader:
        return _json_no_duplicates(reader.read_bytes(relative, max_bytes=MAX_SIDECAR_BYTES))


def public_pair(target, evidence_root, metadata_paths, index_paths):
    target = target.absolute()
    repository = "https://github.com/DDINGJOO/JJAM-TONG-playground"
    if git(target, "remote", "get-url", "origin").removesuffix(".git") != repository:
        raise ValueError("the publishable integration fixture must be the designated public playground")
    status_before = sha(git(target, "status", "--porcelain", "--untracked-files=all").encode("utf-8"))
    snapshots, bridges, cases = [], [], []
    for position, (metadata_path, index_path) in enumerate(zip(metadata_paths, index_paths)):
        metadata = read_fixture_json(evidence_root, metadata_path)
        index = read_fixture_json(evidence_root, index_path)
        if metadata["repository"] != repository:
            raise ValueError("unexpected public repository metadata")
        name, build = metadata["module"], metadata["build"]
        artifact = ".local/artifacts/" + build + "/" + name + ".jar"
        sources = [{"path": name + "/src/main/java/" + item["path"], "sha256": item["sha256"]}
                   for item in metadata["sourceFiles"]]
        item = {"id": name, "descriptor": name + "/pom.xml",
                "dependencies": {"state": "unavailable", "modules": []},
                "artifacts": file_set(files=[{"path": artifact, "sha256": metadata["artifactSha256"]}]),
                "inputs": {key: file_set("unavailable") for key in
                           ("sources", "generatedSources", "classpath", "toolchain", "conditions")}}
        item["inputs"]["sources"] = file_set(files=sources)
        manifest = {"schema": "jjamtong.build-manifest.v1", "repository": repository,
                    "revision": metadata["revision"], "build": build, "recordedAt": utc(),
                    "producer": {"name": "retained-public-fixture-adapter", "version": "1"},
                    "moduleCoverage": "partial", "modules": [item]}
        snapshot = capture(manifest, target, "public-fixture")
        bridge = link_analysis(snapshot, index, name, artifact, index["indexSha256"], index["configSha256"])
        expected = {key: metadata[key] for key in ("repository", "revision", "build", "module", "artifactSha256")}
        cases.append(check("BDD-BLD-003-public-" + str(position + 1), expected, dict(bridge.build_identity)))
        cases.append(check("BDD-BLD-003-index-mismatch-" + str(position + 1), True,
                           rejected(lambda: link_analysis(snapshot, index, name, artifact,
                                                          "f" * 64, index["configSha256"]))))
        snapshots.append(snapshot)
        bridges.append(bridge.to_dict())
    baseline, current = snapshots
    delta = compare(baseline, current, baseline.manifest_sha256, current.manifest_sha256)
    discovery = discover_maven(target)
    cases.append(check("BDD-BLD-001-public", ["activity-worker/pom.xml", "board-api/pom.xml", "common/pom.xml",
                                            "execution-common/pom.xml", "execution-mvc/pom.xml",
                                            "execution-netty/pom.xml", "pom.xml"],
                       sorted(item["descriptorPath"] for item in discovery["candidates"])))
    cases.append(check("public-partial-inputs", "PARTIAL", delta["status"]))
    cases.append(check("target-read-only", status_before,
                       sha(git(target, "status", "--porcelain", "--untracked-files=all").encode("utf-8"))))
    return {"cases": cases, "snapshots": [item.to_dict() for item in snapshots],
            "bridges": bridges, "comparison": delta, "discovery": discovery,
            "limitations": ["retained source hashes matched the available files during this run",
                            "new declaration and verification times, not historic collection-time proof",
                            "complete compiler inputs and source-to-artifact provenance unavailable",
                            "no new Java analysis, build execution, application requests or DB writes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-target", type=Path)
    parser.add_argument("--public-evidence-root", type=Path)
    parser.add_argument("--baseline-metadata", type=Path)
    parser.add_argument("--current-metadata", type=Path)
    parser.add_argument("--baseline-index", type=Path)
    parser.add_argument("--current-index", type=Path)
    args = parser.parse_args()
    public_args = (args.public_target, args.public_evidence_root, args.baseline_metadata, args.current_metadata,
                   args.baseline_index, args.current_index)
    if any(public_args) and not all(public_args):
        parser.error("all six public-fixture paths must be supplied together")
    report = {"schema": "jjamtong.build-inventory-lab.v1", "synthetic": synthetic()}
    if args.public_target:
        report["publicFixture"] = public_pair(args.public_target, args.public_evidence_root,
                                             (args.baseline_metadata, args.current_metadata),
                                             (args.baseline_index, args.current_index))
    cases = report["synthetic"]["cases"] + report.get("publicFixture", {}).get("cases", [])
    report["summary"] = {"passed": sum(case["pass"] for case in cases), "total": len(cases)}
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report["summary"]))
    return 0 if all(case["pass"] for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
