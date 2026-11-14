import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from .run import _case, compare


class ComparisonTest(unittest.TestCase):
    def test_timeout_retains_marker_observation_and_remaining_results(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "comparison"
            code = ("from pathlib import Path; import sys,time; "
                    "p=Path(sys.argv[1]); p.mkdir(parents=True); "
                    "(p/'complete.json').write_text('{}'); time.sleep(10)")
            result = compare(output, 1, timeout=1,
                             commands={"bundle": [sys.executable, "-c", code, str(output / "bundle")]})
            self.assertEqual(result["cases"]["single"]["status"], "complete")
            self.assertEqual(result["cases"]["single-expanded"]["status"], "complete")
            expired = result["cases"]["bundle"]
            self.assertEqual(expired["status"], "deadline-exceeded")
            self.assertTrue(expired["completionMarkerObserved"])
            self.assertEqual(expired["verification"], "not-performed")
            self.assertNotIn("recordDigest", expired)
            self.assertEqual(json.loads((output / "results.json").read_text()), result)

    def test_worker_failure_and_timeout_before_output_have_no_completion_proof(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "absent"
            failed = _case([sys.executable, "-c", "raise SystemExit(7)"], output, 1)
            self.assertEqual(failed["status"], "worker-failed")
            self.assertEqual(failed["returncode"], 7)
            expired = _case([sys.executable, "-c", "import time; time.sleep(10)"], output, 0.1)
            self.assertEqual(expired["status"], "deadline-exceeded")
            self.assertFalse(expired["completionMarkerObserved"])
