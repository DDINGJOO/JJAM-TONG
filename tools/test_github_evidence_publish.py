"""CI-context mismatch controls independent of the Java analyzer implementation."""
import hashlib
import json
import unittest

from tools.evidence_store.test_contracts import rehash, sample
from tools.github_evidence_publish import GitHubContext, bundle


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.context = GitHubContext("example/playground", "123", "c" * 40, "456", "1")
        self.index = sample(self.context.analysis_run_id, self.context.build_id)
        self.index["buildIdentity"].update(repository="https://github.com/example/playground",
                                           revision="c" * 40, module="method-fixture")
        for method in self.index["methods"]:
            method["module"] = "method-fixture"
        for tool in self.index["staticEvidence"].values():
            for method in tool["methods"]:
                method["module"] = "method-fixture"
            for call in tool["calls"]:
                call["caller"]["module"] = call["target"]["module"] = "method-fixture"
        rehash(self.index)

    def test_bundle_digest_binds_exact_file_bytes_and_context(self):
        files = bundle(self.context, self.index)
        self.assertEqual({"manifest.json", "index.json"}, set(files))
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(json.dumps(self.index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(), files["index.json"])
        self.assertNotIn(b"\n", files["index.json"])
        self.assertTrue(files["manifest.json"].endswith(b"\n"))
        self.assertEqual(hashlib.sha256(files["index.json"]).hexdigest(), manifest["indexFileSha256"])
        self.assertEqual("c" * 40, manifest["revision"])
        self.assertEqual(123, manifest["repositoryId"])

    def test_wrong_repository_commit_build_module_rejected(self):
        for field, value in (("repository", "https://github.com/other/repo"), ("revision", "d" * 40),
                             ("build", "another-build"), ("module", "other-module")):
            with self.subTest(field=field):
                original = self.index["buildIdentity"][field]
                self.index["buildIdentity"][field] = value
                rehash(self.index)
                with self.assertRaises(ValueError):
                    bundle(self.context, self.index)
                self.index["buildIdentity"][field] = original
                rehash(self.index)

    def test_other_attempt_cannot_reuse_analysis_run(self):
        other = GitHubContext("example/playground", "123", "c" * 40, "456", "2")
        with self.assertRaises(ValueError):
            bundle(other, self.index)

    def test_changed_index_body_rejected(self):
        self.index["limitations"].append("changed")
        with self.assertRaises(ValueError):
            bundle(self.context, self.index)

    def test_invalid_ci_identifiers_rejected(self):
        for position, value in ((0, "../repo"), (1, "0"), (2, "latest"), (3, "-1"), (4, "1/../2")):
            args = ["example/playground", "123", "c" * 40, "456", "1"]
            args[position] = value
            with self.subTest(position=position), self.assertRaises(ValueError):
                GitHubContext(*args)


if __name__ == "__main__":
    unittest.main()
