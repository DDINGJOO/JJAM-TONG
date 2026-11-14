"""Boundary checks for the clean-checkout Boot index publisher."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.boot_evidence import manifest, publish


class BootEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "board-api/src/main/java/example/Board.java"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("package example; class Board {}\n")
        self.artifact = self.root / ".local/artifacts/boot-b1/board-api.jar"
        self.artifact.parent.mkdir(parents=True)
        self.artifact.write_bytes(b"synthetic artifact")
        self.values = {"repository": "https://github.com/example/target", "revision": "a" * 40,
                       "build": "boot-b1", "module": "board-api", "sourceState": "clean",
                       "artifactSha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest()}
        self.sidecar = self.artifact.with_suffix(".properties")
        self.write_sidecar()
        self.git_mock = patch("tools.boot_evidence.git", side_effect=lambda root, *args:
                              "a" * 40 if args == ("rev-parse", "HEAD") else "https://github.com/example/target.git" if args[:2] == ("remote", "get-url") else "")
        self.git_mock.start()
        self.addCleanup(self.git_mock.stop)

    def write_sidecar(self):
        self.sidecar.write_text("".join(k + "=" + v + "\n" for k, v in self.values.items()))

    def test_manifest_checks_exact_artifact_and_source(self):
        value, artifact, sources = manifest(self.root, "board-api", "boot-b1")
        self.assertEqual(artifact, self.artifact)
        self.assertEqual(value["sourceFiles"], [{"path": "example/Board.java", "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}])
        self.assertEqual(sources, self.root / "board-api/src/main/java")

    def test_altered_artifact_is_rejected(self):
        self.artifact.write_bytes(b"changed bytes")
        with self.assertRaisesRegex(ValueError, "match exactly"):
            manifest(self.root, "board-api", "boot-b1")

    def test_other_revision_and_repository_are_rejected(self):
        for key, value in (("revision", "b" * 40), ("repository", "https://github.com/another/target"), ("sourceState", "dirty")):
            original = self.values[key]
            self.values[key] = value
            self.write_sidecar()
            with self.assertRaises(ValueError):
                manifest(self.root, "board-api", "boot-b1")
            self.values[key] = original

    def test_unsafe_identifiers_and_duplicate_fields_rejected(self):
        for module in ("../board-api", ".", ".."):
            with self.assertRaises(ValueError):
                manifest(self.root, module, "boot-b1")
        with self.sidecar.open("a") as stream:
            stream.write("build=boot-b1\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            manifest(self.root, "board-api", "boot-b1")

    def test_existing_output_is_preserved(self):
        output = self.root / "result"
        output.mkdir()
        (output / "old.json").write_text("old evidence")
        with self.assertRaises(FileExistsError):
            publish(self.root, "board-api", "boot-b1", "example.board", Path("/jdk"), "boot-run1", output)
        self.assertEqual((output / "old.json").read_text(), "old evidence")

    def test_failed_analysis_never_publishes_success(self):
        output = self.root / "failed-result"
        with patch("tools.boot_evidence.subprocess.run", side_effect=subprocess.CalledProcessError(1, "analyze")):
            with self.assertRaises(subprocess.CalledProcessError):
                publish(self.root, "board-api", "boot-b1", "example.board", Path("/jdk"), "boot-run1", output)
        self.assertFalse(output.exists())

    def test_dependency_metadata_is_allowlisted_and_digest_bound(self):
        from tools.evidence_store.test_contracts import sample, rehash
        from tools.evidence_store.contracts import prepare
        index = sample()
        dependency = {"entry": "BOOT-INF/lib/common-0.1.jar", "sha256": "a" * 64}
        index["input"]["dependencyArtifacts"] = [dependency]
        prepare(rehash(index))
        for bad in ({**dependency, "entry": "BOOT-INF/lib/../secret.jar"},
                    {**dependency, "sha256": "bad"}, {**dependency, "sql": "forbidden payload"}):
            index["input"]["dependencyArtifacts"] = [bad]
            with self.assertRaises(ValueError):
                prepare(rehash(index))
        index["input"]["dependencyArtifacts"] = [dependency, dependency]
        with self.assertRaises(ValueError):
            prepare(rehash(index))

    def test_raw_smoke_output_cannot_be_public(self):
        from experiments.boot_evidence_smoke import run
        with self.assertRaisesRegex(ValueError, "ignored .local"):
            run(SimpleNamespace(output=self.root / "public-output"))
        self.assertFalse((self.root / "public-output").exists())

    def test_dirty_checkout_rejected_before_output(self):
        with patch("tools.boot_evidence.git", side_effect=["a" * 40, " M source.java"]):
            with self.assertRaisesRegex(ValueError, "clean committed"):
                manifest(self.root, "board-api", "boot-b1")


if __name__ == "__main__":
    unittest.main()
