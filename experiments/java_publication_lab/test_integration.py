import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .integration import PRODUCER_COMMIT, file_digest, verify_baseline


class VerifyBaselineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def analysis(self):
        return {
            "input": {"metadataInputSha256": "m" * 64, "artifactSha256": "a" * 64},
            "provenance": {"adapterVersion": "0.2.3", "producer": "synthetic"},
            "methods": [{"key": "sample.Main#run()V", "source": {"line": 7, "column": 3}}],
            "tools": {"javaparser": {"calls": [{"line": 8, "target": "helper"}]}},
        }

    def index(self):
        return {"buildIdentity": {"repository": "synthetic", "revision": "revision-a",
                                  "build": "build-a", "module": "sample"}}

    def write_case(self, mutate_record=None, mutate_baseline=None, index=None, analysis=None):
        analysis = copy.deepcopy(analysis or self.analysis())
        baseline = copy.deepcopy(analysis)
        baseline["provenance"]["adapterVersion"] = "0.2.2-probe32"
        if mutate_baseline:
            mutate_baseline(baseline)
        baseline_path = self.directory / "baseline.json"
        baseline_path.write_text(json.dumps(baseline, sort_keys=True))
        record = {
            "schema": "jjamtong.java-publication-comparison.v1",
            "producerBaseCommit": PRODUCER_COMMIT,
            "analysis": {"adapterVersion": "0.2.2-probe32", "rawSha256": file_digest(baseline_path)},
            "inputIdentity": {"buildIdentity": copy.deepcopy((index or self.index())["buildIdentity"]),
                              "input": copy.deepcopy(analysis["input"])},
            "fixture": {"metadataSha256": analysis["input"]["metadataInputSha256"]},
        }
        if mutate_record:
            mutate_record(record)
        record_path = self.directory / "record.json"
        record_path.write_text(json.dumps(record, sort_keys=True))
        return baseline_path, record_path, index or self.index(), analysis

    def verify(self, **changes):
        return verify_baseline(*self.write_case(**changes))

    def test_accepts_exact_historical_baseline_after_adapter_normalization(self):
        evidence = self.verify()
        self.assertEqual(evidence["rawSha256"], file_digest(self.directory / "baseline.json"))
        self.assertEqual(evidence["producerCommit"], PRODUCER_COMMIT)
        self.assertEqual(evidence["adapterVersion"], "0.2.2-probe32")

    def test_rejects_corrupt_baseline_byte_hash(self):
        with self.assertRaises(ValueError):
            self.verify(mutate_record=lambda record: record["analysis"].update(rawSha256="0" * 64))

    def test_rejects_wrong_historical_producer_commit(self):
        with self.assertRaises(ValueError):
            self.verify(mutate_record=lambda record: record.update(producerBaseCommit="other-commit"))

    def test_rejects_wrong_historical_baseline_version(self):
        with self.assertRaises(ValueError):
            self.verify(mutate_record=lambda record: record["analysis"].update(adapterVersion="0.2.1"))

    def test_rejects_other_build_identity(self):
        index = self.index()
        baseline_path, record_path, _, analysis = self.write_case()
        index["buildIdentity"]["revision"] = "revision-b"
        with self.assertRaises(ValueError):
            verify_baseline(baseline_path, record_path, index, analysis)

    def test_rejects_other_analysis_input_identity(self):
        baseline_path, record_path, index, analysis = self.write_case()
        analysis["input"]["artifactSha256"] = "b" * 64
        with self.assertRaises(ValueError):
            verify_baseline(baseline_path, record_path, index, analysis)

    def test_rejects_other_metadata_identity(self):
        with self.assertRaises(ValueError):
            self.verify(mutate_record=lambda record: record["fixture"].update(metadataSha256="x" * 64))

    def test_rejects_changed_method_or_source_position_semantics(self):
        for mutate in (
            lambda baseline: baseline["methods"][0].update(key="sample.Main#changed()V"),
            lambda baseline: baseline["methods"][0]["source"].update(line=9),
        ):
            with self.subTest(mutate=mutate), self.assertRaises(AssertionError):
                self.verify(mutate_baseline=mutate)


if __name__ == "__main__":
    unittest.main()
