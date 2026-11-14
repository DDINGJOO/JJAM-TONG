import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .probe import runtime_dependencies


PRODUCER = "java-call-analysis-0.1.0.jar"
DIRECT = "direct.jar"
TRANSITIVE = "transitive.jar"


class RuntimeDependenciesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.adapter = Path(self.temporary.name) / "adapter"
        self.jars = self.adapter / "target/dependency"
        self.jars.mkdir(parents=True)
        self.producer = self.adapter / "target" / PRODUCER
        self.producer.write_bytes(b"synthetic producer JAR")
        self.direct = self.jars / DIRECT
        self.direct.write_bytes(b"synthetic direct runtime JAR")
        self.transitive = self.jars / TRANSITIVE
        self.transitive.write_bytes(b"synthetic transitive runtime JAR")
        self.write_contract()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_contract(self, artifacts=None, pinned=None):
        artifacts = artifacts or [
            {"file": PRODUCER, "sha256": self.digest(self.producer)},
            {"file": DIRECT, "sha256": self.digest(self.direct)},
            {"file": TRANSITIVE, "sha256": self.digest(self.transitive)},
        ]
        pinned = pinned if pinned is not None else {DIRECT: self.digest(self.direct)}
        (self.adapter / "target/dependency-sha256.json").write_text(json.dumps({
            "schema": "jjamtong.analysis-dependencies.v1", "artifacts": artifacts,
        }))
        (self.adapter / "dependency-provenance.json").write_text(json.dumps({"binarySha256": pinned}))

    def test_accepts_complete_manifest_with_direct_and_transitive_runtime_jars(self):
        self.assertEqual(runtime_dependencies(self.adapter), {
            DIRECT: self.digest(self.direct), TRANSITIVE: self.digest(self.transitive),
        })

    def test_rejects_extra_runtime_jar(self):
        (self.jars / "unexpected.jar").write_bytes(b"unexpected")
        with self.assertRaises(ValueError):
            runtime_dependencies(self.adapter)

    def test_rejects_missing_runtime_jar(self):
        self.transitive.unlink()
        with self.assertRaises(ValueError):
            runtime_dependencies(self.adapter)

    def test_rejects_modified_runtime_jar_bytes(self):
        self.transitive.write_bytes(b"modified transitive runtime JAR")
        with self.assertRaises(ValueError):
            runtime_dependencies(self.adapter)

    def test_rejects_modified_direct_dependency_contract(self):
        self.write_contract(pinned={DIRECT: "0" * 64})
        with self.assertRaises(ValueError):
            runtime_dependencies(self.adapter)

    def test_rejects_duplicate_and_unsafe_manifest_entries(self):
        valid = [
            {"file": PRODUCER, "sha256": self.digest(self.producer)},
            {"file": DIRECT, "sha256": self.digest(self.direct)},
            {"file": TRANSITIVE, "sha256": self.digest(self.transitive)},
        ]
        for invalid in (
            valid + [{"file": DIRECT, "sha256": self.digest(self.direct)}],
            valid[:-1] + [{"file": "../" + TRANSITIVE, "sha256": self.digest(self.transitive)}],
        ):
            with self.subTest(artifacts=invalid):
                self.write_contract(artifacts=invalid)
                with self.assertRaises(ValueError):
                    runtime_dependencies(self.adapter)


if __name__ == "__main__":
    unittest.main()
