"""Bind all parts of a comparison to one execution and measurement source."""
import hashlib
import json
from pathlib import Path


SOURCES = ("fixtures.py", "stores.py", "pipeline.py", "run.py", "federation.py",
           "provenance.py", "report.py", "test_fixtures.py", "test_regressions.py",
           "test_evidence.py", "test_runner.py", "compose.yaml", "clickhouse.xml", "requirements.txt")


def source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in SOURCES}


def verify_sources(environment):
    if (not environment.get("run_id") or environment.get("source_tree_dirty") is not False or
            not environment.get("git_commit") or environment.get("source_sha256") != source_hashes()):
        raise ValueError("measurement source identity missing or changed; rerun the comparison")


def load_environment(directory):
    environment = json.loads((directory / "environment.json").read_text())
    verify_sources(environment)
    return environment


def stamped(result, environment):
    verify_sources(environment)
    return dict(result, run_id=environment["run_id"], git_commit=environment["git_commit"],
                source_sha256=environment["source_sha256"])
