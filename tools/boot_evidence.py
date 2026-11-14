"""Index one clean, separately built Spring Boot module without running its code."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from tools.method_evidence.evidence import (build_identity, create_index, file_digest,
                                            IDENTIFIER, save_index)

ROOT = Path(__file__).resolve().parents[1]


def git(target, *args):
    return subprocess.run(["git", "-C", str(target), *args], check=True, text=True,
                          capture_output=True, timeout=20).stdout.strip()


def clean_revision(target):
    revision = git(target, "rev-parse", "HEAD")
    if not re.fullmatch("[0-9a-f]{40}", revision) or git(target, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("A clean committed target checkout is required")
    return revision


def manifest(target, module, build_id):
    """Recheck caller-supplied build sidecar and current source; not attestation."""
    for value in (module, build_id):
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or value in (".", ".."):
            raise ValueError("Invalid module or build identifier")
    revision = clean_revision(target)
    directory = target / ".local/artifacts" / build_id
    artifact = directory / (module + ".jar")
    sidecar = directory / (module + ".properties")
    values = {}
    for line in sidecar.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError("Duplicate build sidecar field")
        values[key] = value
    identity = build_identity(values)
    remote = git(target, "remote", "get-url", "origin").removesuffix(".git")
    if (identity["revision"] != revision or identity["module"] != module or
            identity["build"] != build_id or identity["repository"] != remote or
            values.get("sourceState") != "clean" or file_digest(artifact) != identity["artifactSha256"]):
        raise ValueError("Artifact, checkout and build sidecar must match exactly")
    sources = target / module / "src/main/java"
    files = sorted(sources.rglob("*.java"))
    if not files or any(path.is_symlink() or not path.is_file() for path in files):
        raise ValueError("Expected regular Java source files")
    source_files = [{"path": p.relative_to(sources).as_posix(), "sha256": file_digest(p)} for p in files]
    return {**identity, "sourceState": "clean", "sourceFiles": source_files}, artifact, sources


def publish(target, module, build_id, include_package, java_home, run_id, output):
    if not IDENTIFIER.fullmatch(run_id) or not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+", include_package):
        raise ValueError("Choose an explicit run ID and application package")
    before, artifact, sources = manifest(target, module, build_id)
    # Exclusive directory: do not overwrite an older successful analysis.
    output.mkdir()
    try:
        metadata = output / "build-manifest.json"
        metadata.write_text(json.dumps(before, indent=2) + "\n")
        analysis = output / "methods.json"
        subprocess.run([sys.executable, str(ROOT / "tools/java-call-analysis/analyze.py"),
                        "--java-home", str(java_home), "--source-root", str(sources),
                        "--artifact", str(artifact), "--module", module, "--metadata", str(metadata),
                        "--output", str(analysis), "--include-package", include_package,
                        "--artifact-format", "spring-boot", "--entrypoint-policy", "all-included-methods"],
                       check=True, timeout=70)
        after, _, _ = manifest(target, module, build_id)
        if after != before:
            raise ValueError("Target inputs changed during analysis")
        index = create_index(json.loads(analysis.read_text()), before, artifact, sources, run_id)
        save_index(index, output)
        return index
    except BaseException:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--include-package", required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index = publish(args.target.resolve(), args.module, args.build_id, args.include_package,
                    args.java_home, args.run_id, args.output.absolute())
    print(json.dumps({"analysisRunId": index["analysisRunId"], "indexSha256": index["indexSha256"],
                      "buildIdentity": index["buildIdentity"], "methods": len(index["methods"])}))


if __name__ == "__main__":
    main()
