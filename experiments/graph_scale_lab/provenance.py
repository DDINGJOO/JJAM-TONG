"""Pin measured code and inputs; never join runs with different source trees."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def source_paths():
    base = ROOT / "experiments/graph_scale_lab"
    return sorted([str(p.relative_to(ROOT)) for p in base.iterdir()
                   if p.suffix == ".py" or p.name == "compose.yaml"] +
                  ["experiments/storage_lab/requirements.txt"])


def manifest():
    paths = source_paths()
    if git("status", "--porcelain", "--", *paths):
        raise ValueError("commit measurement sources before running")
    return {"commit": git("rev-parse", "HEAD"), "source_hashes": {
        p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}


def verify_manifest(record):
    expected = manifest()["source_hashes"]
    if record["source_hashes"] != expected:
        raise ValueError("measured sources differ from the current sources")
    for path, digest in record["source_hashes"].items():
        data = subprocess.check_output(["git", "show", record["commit"] + ":" + path], cwd=ROOT)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("commit/source mismatch: " + path)


def save(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n")
    temporary.replace(path)
