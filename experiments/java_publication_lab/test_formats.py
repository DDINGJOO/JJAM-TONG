import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.analysis_job_lab.model import Budget
from experiments.analysis_job_lab.publication import OutputLimit
from .formats import (DEFAULT_MAX_BYTES, STAGES, publish_compact, publish_parts,
                      read_parts, restore, stages)


KEY = "a" * 64


def analysis():
    return {
        "schema": "jjamtong.methods.v1", "status": "complete-with-limitations", "module": "한글-module",
        "metadata": {"unknown": ["preserved"]}, "optionalTop": {"newline": "one\ntwo"},
        "tools": {
            "javaparser": {"version": "x", "optional": {"kept": True},
                           "methods": [{"name": "first"}, {"name": "second"}],
                           "calls": [{"kind": "declared-call", "line": 1}],
                           "unresolved": [], "excluded": [{"reason": "outside"}]},
            "wala": {"version": "y", "algorithm": "CHA", "methods": [],
                     "calls": [{"kind": "possible-call", "line": 2}],
                     "unresolved": [{"reason": "reflection"}], "excluded": []},
        },
    }


class FormatsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.budget = Budget(max_total_bytes=20_000, max_chunk_bytes=1_000, max_record_bytes=500,
                             max_manifest_bytes=5_000, max_chunks=30)

    def test_stages_and_restore_preserve_all_fields_order_and_empty_lists(self):
        value = analysis()
        split = stages(value)
        self.assertEqual(tuple(split), STAGES)
        self.assertEqual(list(split["javaparser-methods"]), value["tools"]["javaparser"]["methods"])
        self.assertNotIn("methods", next(iter(split["envelope"]))["tools"]["javaparser"])
        rows = [(stage, record) for stage in STAGES for record in split[stage]]
        self.assertEqual(restore(rows), value)
        empty = analysis()
        for tool in ("javaparser", "wala"):
            for field in ("methods", "calls", "unresolved", "excluded"):
                empty["tools"][tool][field] = []
        empty_envelope = next(iter(stages(empty)["envelope"]))
        self.assertEqual(restore([("envelope", empty_envelope)]), empty)

    def test_invalid_schema_tools_and_list_shapes_are_rejected(self):
        for mutate in (
            lambda value: value.update(schema="other"),
            lambda value: value.update(tools={"javaparser": value["tools"]["javaparser"]}),
            lambda value: value["tools"]["wala"].update(methods={}),
            lambda value: value["tools"]["wala"].update(calls=["not-an-object"]),
        ):
            value = analysis(); mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                stages(value)

    def test_restore_rejects_unknown_multiple_and_missing_envelopes(self):
        envelope = next(iter(stages(analysis())["envelope"]))
        for rows in ([], [("unknown", {})], [("envelope", envelope), ("envelope", envelope)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                restore(rows)

    def test_compact_is_logically_exact_unicode_newline_and_byte_bounded(self):
        value = analysis()
        path = self.directory / "result.json"
        size = publish_compact(value, path, DEFAULT_MAX_BYTES)
        encoded = path.read_bytes()
        self.assertEqual(size, len(encoded))
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertEqual(json.loads(encoded), value)
        self.assertIn("한글".encode(), encoded)
        exact = self.directory / "exact.json"
        self.assertEqual(publish_compact(value, exact, len(encoded)), len(encoded))

    def test_compact_over_cap_preserves_prior_file_and_cleans_temporary(self):
        path = self.directory / "result.json"
        path.write_bytes(b"previous\n")
        with self.assertRaises(OutputLimit):
            publish_compact(analysis(), path, 1)
        self.assertEqual(path.read_bytes(), b"previous\n")
        self.assertFalse(list(self.directory.glob(".pending-*")))
        for invalid in (True, 0, -1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                publish_compact(analysis(), path, invalid)

    def test_parts_verify_restore_and_reject_missing_corrupt_foreign_and_attempt(self):
        value = analysis()
        publish_parts(value, self.directory, KEY, "attempt-a", self.budget)
        self.assertEqual(read_parts(self.directory, KEY, "attempt-a", self.budget), value)
        for key, attempt in (("b" * 64, "attempt-a"), (KEY, "attempt-b")):
            with self.subTest(key=key, attempt=attempt), self.assertRaises(ValueError):
                read_parts(self.directory, key, attempt, self.budget)
        for case in ("missing", "corrupt", "foreign"):
            directory = self.directory / case
            publish_parts(value, directory, KEY, "attempt-a", self.budget)
            manifest_path = directory / "complete.json"
            manifest = json.loads(manifest_path.read_text())
            part = manifest["parts"][0]
            object_path = directory / "objects" / (part["sha256"] + ".jsonl")
            if case == "missing":
                object_path.unlink()
                error = FileNotFoundError
            elif case == "corrupt":
                object_path.write_bytes(object_path.read_bytes() + b"corrupt")
                error = ValueError
            else:
                lines = object_path.read_bytes().splitlines(keepends=True)
                header = json.loads(lines[0])
                header["inputKey"] = "b" * 64
                changed = json.dumps(header, separators=(",", ":")).encode() + b"\n" + b"".join(lines[1:])
                digest = hashlib.sha256(changed).hexdigest()
                (directory / "objects" / (digest + ".jsonl")).write_bytes(changed)
                part.update(sha256=digest, bytes=len(changed))
                manifest_path.write_text(json.dumps(manifest))
                error = ValueError
            with self.subTest(case=case), self.assertRaises(error):
                read_parts(directory, KEY, "attempt-a", self.budget)

    def test_parts_do_not_complete_after_partial_write(self):
        def stop(event):
            if event == "after-part":
                raise InterruptedError("stop")
        # The adapter intentionally delegates this completion rule to the lab.
        with self.assertRaises(InterruptedError):
            from experiments.analysis_job_lab.publication import publish_bundle
            publish_bundle(self.directory, KEY, "attempt-a", STAGES, stages(analysis()), self.budget, stop)
        self.assertFalse((self.directory / "complete.json").exists())


if __name__ == "__main__":
    unittest.main()
