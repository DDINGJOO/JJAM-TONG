"""Produce a bounded method-index bundle for one clean GitHub Actions checkout.

Only the existing dependency-free Playground method fixture is supported. No
application source or executable artifact is included in the published bundle.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from tools.evidence_store.contracts import prepare
from tools.method_evidence.evidence import MAX_BYTES, create_index

PLATFORM = Path(__file__).resolve().parents[1]
SCHEMA = "jjamtong.github-method-evidence.v1"


@dataclass(frozen=True)
class GitHubContext:
    repository: str
    repository_id: str
    revision: str
    run_id: str
    run_attempt: str
    workflow: str = ".github/workflows/ci.yml"

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}", self.repository):
            raise ValueError("Expected an explicit owner/repository")
        for value in (self.repository_id, self.run_id, self.run_attempt):
            if not re.fullmatch(r"[1-9][0-9]{0,19}", value):
                raise ValueError("Expected a positive GitHub numeric identifier")
        if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
            raise ValueError("Expected an exact Git commit SHA")
        if not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.ya?ml", self.workflow):
            raise ValueError("Expected a workflow file path")

    @property
    def analysis_run_id(self):
        return f"gh-{self.repository_id}-{self.run_id}-{self.run_attempt}"

    @property
    def build_id(self):
        return f"gh-{self.run_id}-{self.run_attempt}"


def bundle(context, index):
    """Bind the immutable index to the CI context, without changing its schema."""
    prepare(index)
    identity = index["buildIdentity"]
    expected = {"repository": "https://github.com/" + context.repository,
                "revision": context.revision, "build": context.build_id, "module": "method-fixture"}
    if any(identity[key] != value for key, value in expected.items()):
        raise ValueError("Index build differs from the selected CI context")
    if index["analysisRunId"] != context.analysis_run_id:
        raise ValueError("Index analysis run differs from the selected CI context")
    raw = json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Index exceeds 10 MiB")
    manifest = {"schema": SCHEMA, "repository": context.repository,
                "repositoryId": int(context.repository_id), "revision": context.revision,
                "workflow": context.workflow, "runId": context.run_id, "runAttempt": context.run_attempt,
                "analysisRunId": context.analysis_run_id, "indexSha256": index["indexSha256"],
                "indexFileSha256": hashlib.sha256(raw).hexdigest()}
    return {"index.json": raw, "manifest.json": (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()}


def verify_checkout(target, context):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=target, text=True).strip()
    if head != context.revision or dirty:
        raise ValueError("CI evidence requires the exact clean source revision")


def produce(target, java_home, output, context):
    verify_checkout(target, context)
    if output.exists():
        raise ValueError("Bundle output already exists; preserve the previous evidence")
    build_script = target / "scripts/build_method_fixture.py"
    subprocess.run([os.sys.executable, str(build_script), "--java-home", str(java_home),
                    "--variant", "A", "--build-id", context.build_id, "--smoke"],
                   cwd=target, check=True, timeout=120)
    built = target / ".local/method-fixture/artifacts" / context.build_id
    manifest_path = built / "identity.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("sourceState") != "clean" or manifest.get("revision") != context.revision:
        raise ValueError("Fixture build differs from the clean source revision")
    analysis_path = built / "methods.json"
    subprocess.run([os.sys.executable, str(PLATFORM / "tools/java-call-analysis/analyze.py"),
                    "--java-home", str(java_home), "--source-root", str(built / "sources"),
                    "--artifact", str(built / "method-fixture.jar"), "--module", "method-fixture",
                    "--metadata", str(manifest_path), "--output", str(analysis_path)],
                   cwd=PLATFORM, check=True, timeout=90)
    index = create_index(json.loads(analysis_path.read_text()), manifest, built / "method-fixture.jar",
                         built / "sources", context.analysis_run_id)
    data = bundle(context, index)
    # Check again after build/analysis; failed work never becomes a success bundle.
    verify_checkout(target, context)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".bundle-", dir=output.parent))
    try:
        for name, raw in data.items():
            (work / name).write_bytes(raw)
        work.rename(output)
    finally:
        if work.exists():
            shutil.rmtree(work)
    return {"analysisRunId": context.analysis_run_id, "indexSha256": index["indexSha256"],
            "revision": context.revision, "methods": len(index["methods"]),
            "artifactName": f"jjamtong-method-index-{context.run_id}-{context.run_attempt}",
            "scope": "method-fixture; static candidates only; no Boot nested JAR or runtime collection"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name, env in (("repository", "GITHUB_REPOSITORY"), ("repository-id", "GITHUB_REPOSITORY_ID"),
                      ("revision", "GITHUB_SHA"), ("run-id", "GITHUB_RUN_ID"),
                      ("run-attempt", "GITHUB_RUN_ATTEMPT")):
        parser.add_argument("--" + name, default=os.environ.get(env))
    parser.add_argument("--workflow", default=".github/workflows/ci.yml")
    args = parser.parse_args()
    try:
        context = GitHubContext(args.repository or "", args.repository_id or "", args.revision or "",
                                args.run_id or "", args.run_attempt or "", args.workflow)
        result = produce(args.target_root.resolve(), args.java_home.resolve(), args.output.resolve(), context)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError):
        parser.exit(1, "Method evidence production failed; no new success bundle published.\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
