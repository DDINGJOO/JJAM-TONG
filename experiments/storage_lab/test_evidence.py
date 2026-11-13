"""Keep incomplete or mixed measurements out of the published comparison."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import report
from .provenance import source_hashes


class ReportEvidence(unittest.TestCase):
    def setUp(self):
        self.published = json.loads((Path(__file__).resolve().parents[2] /
                                     "docs/experiments/storage-engine-run.json").read_text())
        self.published["environment"].update(run_id="unit-test", source_sha256=source_hashes(),
                                             engines=list(report.NAMES), pipeline_enabled=True, source_tree_dirty=False)
        for result in list(self.published["engines"].values()) + [self.published["federation"]]:
            result.update(run_id="unit-test", git_commit=self.published["environment"]["git_commit"],
                          source_sha256=source_hashes(), status="passed")
        self.published["federation"]["checks"] = sorted(report.FEDERATION)
        for name in report.NAMES[1:]:
            self.published["engines"][name]["pipeline"]["retired_watermark"] = {"status": "stale"}

    def run_report(self, data):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "environment.json").write_text(json.dumps(data["environment"]))
            (root / "federation.json").write_text(json.dumps(data["federation"]))
            for name, result in data["engines"].items():
                (root / (name + ".json")).write_text(json.dumps(result))
            with patch("sys.argv", ["report", "--input", str(root), "--output", str(root / "packed.json")]):
                report.main()

    def test_missing_pipeline_cannot_be_published(self):
        data = copy.deepcopy(self.published)
        del data["engines"]["neo4j"]["pipeline"]
        with self.assertRaisesRegex(ValueError, "incomplete pipeline"):
            self.run_report(data)

    def test_different_inputs_cannot_be_compared(self):
        data = copy.deepcopy(self.published)
        data["engines"]["neo4j"]["scales"][1]["input_sha256"] = "different-input"
        with self.assertRaisesRegex(ValueError, "different input"):
            self.run_report(data)

    def test_complete_comparison_can_be_published(self):
        self.run_report(self.published)

    def test_stale_engine_run_cannot_be_published(self):
        data = copy.deepcopy(self.published)
        data["engines"]["neo4j"]["run_id"] = "previous-run"
        with self.assertRaisesRegex(ValueError, "mixed run"):
            self.run_report(data)

    def test_source_changed_after_measurement_cannot_be_published(self):
        data = copy.deepcopy(self.published)
        data["environment"]["source_sha256"]["stores.py"] = "changed-source"
        with self.assertRaisesRegex(ValueError, "source identity"):
            self.run_report(data)

    def test_missing_samples_cannot_be_published(self):
        data = copy.deepcopy(self.published)
        data["engines"]["postgres"]["scales"][0]["queries"]["graph_forward_6"]["samples_ms"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete latency"):
            self.run_report(data)

    def test_federation_from_another_run_cannot_be_published(self):
        data = copy.deepcopy(self.published)
        data["federation"]["run_id"] = "previous-run"
        with self.assertRaisesRegex(ValueError, "mixed run"):
            self.run_report(data)

    def test_retired_projection_cannot_report_ready(self):
        data = copy.deepcopy(self.published)
        data["engines"]["elasticsearch"]["pipeline"]["retired_watermark"]["status"] = "ready"
        with self.assertRaisesRegex(ValueError, "incomplete pipeline"):
            self.run_report(data)

    def test_wrong_check_names_cannot_satisfy_check_count(self):
        data = copy.deepcopy(self.published)
        data["engines"]["postgres"]["scales"][0]["correctness_checks"][0] = "unrelated-check"
        with self.assertRaisesRegex(ValueError, "incomplete correctness"):
            self.run_report(data)

    def test_wrong_git_commit_cannot_be_published(self):
        data = copy.deepcopy(self.published)
        data["engines"]["postgres"]["git_commit"] = "different-commit"
        with self.assertRaisesRegex(ValueError, "mixed run"):
            self.run_report(data)


if __name__ == "__main__":
    unittest.main()
