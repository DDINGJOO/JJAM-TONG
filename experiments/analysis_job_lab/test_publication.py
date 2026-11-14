from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .model import Budget, Job, Status
from .publication import (OutputLimit, PublicationConflict, iter_bundle, iter_single,
                          publish_bundle, publish_single, verify_bundle)

KEY, OTHER = "a" * 64, "b" * 64
STAGES = ("inventory", "relations")


def records():
    return {"inventory": [{"method": "BoardController.list", "line": 12}, {"method": "Service.find", "line": 28}],
            "relations": [{"kind": kind, "source": "BoardController.list", "target": "Service.find", "label": "게시판"}
                          for kind in ("declared-call", "cha-candidate", "observed-call", "unresolved")]}


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.budget = Budget(max_total_bytes=20000, max_chunk_bytes=600, max_record_bytes=250,
                             max_manifest_bytes=5000, max_chunks=30)

    def write(self, directory=None, key=KEY, attempt="attempt-a", data=None, budget=None, checkpoint=lambda event: None):
        return publish_bundle(directory or self.directory, key, attempt, STAGES,
                              records() if data is None else data, budget or self.budget, checkpoint)

    def read(self, directory=None, key=KEY, attempt="attempt-a", budget=None):
        return list(iter_bundle(directory or self.directory, key, attempt, STAGES, budget or self.budget))

    def manifest(self):
        return json.loads((self.directory / "complete.json").read_text())

    def save_manifest(self, manifest):
        (self.directory / "complete.json").write_text(json.dumps(manifest))

    def test_single_and_bundle_preserve_order_positions_and_evidence_kinds(self):
        expected = [(stage, value) for stage, values in records().items() for value in values]
        summary = self.write()
        self.assertEqual(self.read(), expected)
        self.assertGreater(summary["parts"], len(STAGES))
        publish_single(self.directory / "single", KEY, "attempt-a", STAGES, records(), self.budget)
        self.assertEqual(list(iter_single(self.directory / "single", KEY, "attempt-a", STAGES, self.budget)), expected)

    def test_empty_stage_is_explicit_and_missing_stage_is_rejected(self):
        self.write(data={"inventory": [], "relations": []})
        self.assertEqual(self.read(), [])
        self.assertEqual(self.manifest()["counts"], dict.fromkeys(STAGES, 0))
        with self.assertRaises(ValueError):
            self.write(directory=self.directory / "missing", data={"inventory": []})

    def test_interruption_after_parts_leaves_no_completion_and_retry_succeeds(self):
        def stop(event):
            if event == "after-part":
                raise InterruptedError("injected worker stop")
        with self.assertRaises(InterruptedError):
            self.write(checkpoint=stop)
        self.assertTrue(list((self.directory / "objects").glob("*.jsonl")))
        self.assertFalse((self.directory / "complete.json").exists())
        with self.assertRaises(FileNotFoundError):
            self.read()
        self.write()
        self.assertEqual(len(self.read()), 6)

    def test_cancel_and_changed_input_at_commit_do_not_publish(self):
        source = self.directory / "source.txt"
        source.write_text("version-a")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        def check(event):
            if event == "before-complete":
                source.write_text("version-b")
                if hashlib.sha256(source.read_bytes()).hexdigest() != before:
                    raise ValueError("input changed at caller checkpoint")
        with self.assertRaisesRegex(ValueError, "input changed"):
            self.write(checkpoint=check)
        self.assertFalse((self.directory / "complete.json").exists())
        def cancel(event):
            if event == "before-complete":
                raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            self.write(checkpoint=cancel)
        self.assertFalse((self.directory / "complete.json").exists())

    def test_single_total_limit_and_failure_preserve_previous_output(self):
        publish_single(self.directory, KEY, "attempt-a", STAGES, records(), self.budget)
        old = (self.directory / "result.jsonl").read_bytes()
        tiny = Budget(max_total_bytes=600, max_chunk_bytes=400, max_record_bytes=250, max_manifest_bytes=5000)
        with self.assertRaises(OutputLimit):
            publish_single(self.directory, OTHER, "attempt-b", STAGES, records(), tiny)
        self.assertEqual((self.directory / "result.jsonl").read_bytes(), old)
        with self.assertRaises(ValueError):
            list(iter_single(self.directory, OTHER, "attempt-b", STAGES, self.budget))
        self.assertFalse(list(self.directory.glob(".pending-*")))

    def test_part_count_manifest_aggregate_and_record_limits(self):
        budgets = [Budget(max_total_bytes=20000, max_chunk_bytes=600, max_record_bytes=250, max_chunks=1),
                   Budget(max_total_bytes=20000, max_chunk_bytes=600, max_record_bytes=250, max_manifest_bytes=100),
                   Budget(max_total_bytes=600, max_chunk_bytes=600, max_record_bytes=250),
                   Budget(max_total_bytes=20000, max_chunk_bytes=600, max_record_bytes=50)]
        for i, budget in enumerate(budgets):
            with self.subTest(i=i), self.assertRaises(OutputLimit):
                self.write(directory=self.directory / str(i), budget=budget)
            self.assertFalse((self.directory / str(i) / "complete.json").exists())

    def test_record_cannot_fit_even_when_under_record_limit(self):
        budget = Budget(max_total_bytes=20000, max_chunk_bytes=350, max_record_bytes=300)
        with self.assertRaises(OutputLimit):
            self.write(data={"inventory": [{"text": "x" * 230}], "relations": []}, budget=budget)

    def test_same_aggregate_budget_and_separate_file_budget(self):
        budget = Budget(max_total_bytes=20000, max_file_bytes=4000, max_chunk_bytes=600,
                        max_record_bytes=250, max_manifest_bytes=5000)
        data = {"inventory": [{"n": i, "text": "게시판" * 10} for i in range(60)], "relations": []}
        with self.assertRaises(OutputLimit):
            publish_single(self.directory / "single", KEY, "attempt-a", STAGES, data, budget)
        summary = self.write(data=data, budget=budget)
        self.assertGreater(summary["bytes"], budget.max_file_bytes)
        self.assertEqual(len(self.read(budget=budget)), 60)

    def test_aggregate_includes_completion_manifest(self):
        summary = self.write()
        exact_parts_only = Budget(max_total_bytes=summary["partsBytes"], max_chunk_bytes=600,
                                  max_record_bytes=250, max_manifest_bytes=5000)
        with self.assertRaises(OutputLimit):
            self.write(directory=self.directory / "tight", budget=exact_parts_only)
        self.assertFalse((self.directory / "tight" / "complete.json").exists())
        with self.assertRaises(OutputLimit):
            self.read(budget=exact_parts_only)

    def test_immutable_duplicate_and_conflicting_publications(self):
        self.assertTrue(self.write()["created"])
        self.assertFalse(self.write()["created"])
        previous = (self.directory / "complete.json").read_bytes()
        with self.assertRaises(PublicationConflict):
            self.write(key=OTHER)
        self.assertEqual((self.directory / "complete.json").read_bytes(), previous)
        self.assertEqual(len(self.read()), 6)

    def test_concurrent_identical_writers_publish_one_completion(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            outputs = list(pool.map(lambda _: self.write(), range(4)))
        self.assertEqual(sum(out["created"] for out in outputs), 1)
        self.assertEqual(len(self.read()), 6)

    def test_verified_bundle_completes_retry_without_rewriting_failed_history(self):
        first = Job(KEY, "attempt-a", STAGES)
        first.start()
        first.stage_complete("inventory")
        first.terminate(Status.RESOURCE_EXCEEDED, "output bytes")
        retry = first.retry("attempt-b")
        retry.start()
        self.write(attempt="attempt-b")
        for stage in STAGES:
            retry.stage_complete(stage)
        self.assertEqual(retry.status, Status.PARTIAL)
        retry.finish(verify_bundle(self.directory, KEY, "attempt-b", STAGES, self.budget))
        self.assertEqual(retry.status, Status.COMPLETE)
        self.assertEqual(first.status, Status.RESOURCE_EXCEEDED)
        self.assertEqual(first.reason, "output bytes")

    def test_truncated_or_appended_single_file_has_no_valid_completion(self):
        publish_single(self.directory, KEY, "attempt-a", STAGES, records(), self.budget)
        path = self.directory / "result.jsonl"
        original = path.read_bytes()
        for changed in (original.rsplit(b"\n", 2)[0] + b"\n", original + b"{}\n"):
            path.write_bytes(changed)
            with self.assertRaises(ValueError):
                list(iter_single(self.directory, KEY, "attempt-a", STAGES, self.budget))

    def test_missing_corrupt_and_swapped_objects_are_rejected(self):
        for case in ("missing", "corrupt", "foreign"):
            directory = self.directory / case
            self.write(directory=directory)
            manifest = json.loads((directory / "complete.json").read_text())
            part = manifest["parts"][0]
            path = directory / "objects" / (part["sha256"] + ".jsonl")
            if case == "missing":
                path.unlink()
            elif case == "corrupt":
                path.write_bytes(path.read_bytes().replace(b"BoardController", b"OtherController"))
            else:
                lines = path.read_bytes().splitlines(keepends=True)
                header = json.loads(lines[0]); header["inputKey"] = OTHER
                changed = json.dumps(header).encode() + b"\n" + b"".join(lines[1:])
                digest = hashlib.sha256(changed).hexdigest()
                (directory / "objects" / (digest + ".jsonl")).write_bytes(changed)
                part.update(sha256=digest, bytes=len(changed))
                (directory / "complete.json").write_text(json.dumps(manifest))
            with self.subTest(case=case), self.assertRaises((ValueError, FileNotFoundError)):
                self.read(directory=directory)

    def test_incomplete_scope_duplicate_part_or_wrong_request_is_rejected(self):
        self.write()
        for key, attempt in ((OTHER, "attempt-a"), (KEY, "attempt-b")):
            with self.assertRaises(ValueError):
                self.read(key=key, attempt=attempt)
        original = self.manifest()
        for mutation in (lambda m: m["parts"].pop(), lambda m: m["parts"].append(m["parts"][0]),
                         lambda m: m.update(totalRecords=999), lambda m: m.update(complete=False)):
            manifest = json.loads(json.dumps(original)); mutation(manifest); self.save_manifest(manifest)
            with self.assertRaises((ValueError, OutputLimit)):
                self.read()


if __name__ == "__main__":
    unittest.main()
