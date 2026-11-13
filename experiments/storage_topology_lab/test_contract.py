"""Regression tests for publication and readiness, independent of DB engines."""
import copy
import unittest

from experiments.storage_lab.fixtures import dataset
from .authority import Conflict, digest, load, manifest_for, publish, stage, view


class MemoryJournal:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return copy.deepcopy(self.data.get(key))

    def claim(self, key, value):
        if key in self.data and self.data[key] != value:
            raise Conflict(key)
        self.data[key] = copy.deepcopy(value)


class Model:
    def __init__(self, rows):
        self.rows = rows

    def select(self, selected, kind):
        return [r for r in self.rows if (r["tenant"], r["build"], r["analysis"]) == selected and r["kind"] == kind and not r["deleted"]]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.rows = dataset(25, 20)
        self.journal = MemoryJournal()

    def test_staging_is_not_publication(self):
        stage(self.journal, self.rows)
        self.assertIsNone(load(self.journal, "import-1"))

    def test_same_identity_different_content_is_rejected(self):
        publish(self.journal, "import-1", self.rows)
        publish(self.journal, "import-1", self.rows)
        with self.assertRaises(Conflict):
            publish(self.journal, "import-1", self.rows[:-1])
        self.assertEqual(load(self.journal, "import-1"), self.rows)

    def test_chunk_corruption_is_not_complete(self):
        publish(self.journal, "import-1", self.rows)
        key = next(k for k in self.journal.data if k.startswith("chunk:"))
        self.journal.data[key][0]["artifact"] = "corrupt"
        self.assertEqual(view(self.journal, Model(self.rows), "import-1"), "conflict")

    def test_missing_chunk_is_not_complete(self):
        publish(self.journal, "import-1", self.rows)
        del self.journal.data[next(k for k in self.journal.data if k.startswith("chunk:"))]
        self.assertEqual(view(self.journal, Model(self.rows), "import-1"), "conflict")

    def test_wrong_projection_artifact_is_not_complete(self):
        publish(self.journal, "import-1", self.rows)
        wrong = copy.deepcopy(self.rows)
        wrong[0]["artifact"] = "another-build-artifact"
        self.assertEqual(view(self.journal, Model(wrong), "import-1"), "partial")
        self.assertEqual(view(self.journal, Model(self.rows), "import-1"), "ready")

    def test_missing_or_extra_projection_rows_are_partial(self):
        publish(self.journal, "import-1", self.rows)
        self.assertEqual(view(self.journal, Model(self.rows[:-1]), "import-1"), "partial")
        self.assertEqual(view(self.journal, Model(self.rows + [self.rows[0]]), "import-1"), "partial")

    def test_manifest_count_or_identity_corruption_is_rejected(self):
        for field, value in (("rows", 0), ("identities", []), ("sha256", "wrong")):
            journal = MemoryJournal()
            publish(journal, "import-1", self.rows)
            journal.data["catalog:import-1"][field] = value
            self.assertEqual(view(journal, Model(self.rows), "import-1"), "conflict")

    def test_duplicate_or_incomplete_identity_is_rejected(self):
        for rows in (self.rows + [self.rows[0]], [dict(self.rows[0], module="")], []):
            with self.assertRaises(ValueError):
                manifest_for(rows)

    def test_unknown_catalog_does_not_fall_back(self):
        publish(self.journal, "import-1", self.rows)
        self.assertEqual(view(self.journal, Model(self.rows), "unknown"), "missing")

    def test_unavailable_authority_has_no_cached_complete_fallback(self):
        class Unavailable:
            def get(self, key):
                raise ConnectionRefusedError("database stopped")
        self.assertEqual(view(Unavailable(), Model(self.rows), "import-1"), "unavailable")

    def test_query_or_invariant_failure_is_not_an_outage(self):
        class Broken:
            def get(self, key):
                raise RuntimeError("partial response or query budget exceeded")
        with self.assertRaisesRegex(RuntimeError, "partial response"):
            view(Broken(), Model(self.rows), "import-1")
        publish(self.journal, "import-1", self.rows)
        class BrokenProjection:
            def select(self, selected, kind):
                raise RuntimeError("projection query invariant failed")
        with self.assertRaisesRegex(RuntimeError, "projection query invariant"):
            view(self.journal, BrokenProjection(), "import-1")

    def test_tombstone_requires_absence_of_active_projection(self):
        rows = [dict(self.rows[0], deleted=1, seq=2)] + self.rows[1:]
        publish(self.journal, "import-deleted", rows)
        self.assertEqual(view(self.journal, Model(self.rows), "import-deleted"), "partial")
        self.assertEqual(view(self.journal, Model(rows), "import-deleted"), "ready")


if __name__ == "__main__":
    unittest.main()
