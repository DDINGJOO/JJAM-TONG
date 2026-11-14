"""Public fixture boundaries and output limits, independent of product inputs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import run


class PublicFixtureBoundaries(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.evidence = self.root / "public-evidence"
        self.evidence.mkdir()

    def test_outside_and_symlink_sidecars_are_rejected(self):
        outside = self.root / "private.json"
        outside.write_text('{"not":"public"}')
        with self.assertRaises(ValueError):
            run.read_fixture_json(self.evidence, outside)
        (self.evidence / "alias.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            run.read_fixture_json(self.evidence, self.evidence / "alias.json")

    def test_duplicate_and_oversized_sidecars_are_rejected(self):
        duplicate = self.evidence / "duplicate.json"
        duplicate.write_text('{"a":"first","a":"second"}')
        with self.assertRaises(ValueError):
            run.read_fixture_json(self.evidence, duplicate)
        large = self.evidence / "large.json"
        large.write_text(json.dumps({"data": "x" * 200}))
        with patch.object(run, "MAX_SIDECAR_BYTES", 64), self.assertRaises(ValueError):
            run.read_fixture_json(self.evidence, large)

    def test_bounded_public_sidecar_is_read(self):
        path = self.evidence / "valid.json"
        path.write_text('{"repository":"synthetic:public"}')
        self.assertEqual({"repository": "synthetic:public"}, run.read_fixture_json(self.evidence, path))

    def test_git_output_limit_fails_closed(self):
        real_popen = subprocess.Popen
        def emit_over_limit(_command, **kwargs):
            return real_popen([sys.executable, "-c", "import sys; sys.stdout.write('x'*4096)"], **kwargs)
        with patch.object(run, "MAX_GIT_OUTPUT_BYTES", 128), patch.object(run.subprocess, "Popen", emit_over_limit):
            with self.assertRaisesRegex(ValueError, "output limit"):
                run.git(self.root, "status")


if __name__ == "__main__":
    unittest.main()
