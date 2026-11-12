"""Regression tests for reviewed cache and subprocess supervision failures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments import method_observability as runner
from tools.method_evidence.evidence import digest, file_digest


class RunnerBoundaryTests(unittest.TestCase):
    def test_timeout_terminates_descendants_as_well_as_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "child-survived"
            child = "import time,pathlib; time.sleep(.7); pathlib.Path(" + repr(str(marker)) + ").touch()"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(5)"
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.run_process([sys.executable, "-c", parent], root / "run", timeout=.2)
            time.sleep(.8)
            self.assertFalse(marker.exists(), "Child continued after supervisor deadline")

    def test_cached_execution_revalidates_and_rejects_raw_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_dir = root / "artifacts/build-A"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "method-fixture.jar").write_bytes(b"synthetic artifact for cache boundary")
            identity = {"repository": "local:test", "revision": "rev-A", "build": "build-A", "module": "board",
                        "artifactSha256": file_digest(artifact_dir / "method-fixture.jar")}
            (artifact_dir / "identity.json").write_text(json.dumps(dict(identity, variant="A")))
            args = SimpleNamespace(java={"17": str(root / "jdk")}, artifacts=root / "artifacts",
                                   agent=root / "agent.jar", store=root / "store", output=root / "runs")
            oracle = {"methodCatalog": {}, "variants": {"A": {"scenarios": {"normal": {
                "expectedOutcome": {"kind": "BUSINESS_OUTCOME", "status": "ok", "result": "SYNTHETIC"}}}}}}
            index = {"indexSha256": "a" * 64}
            command, _, _ = runner.java_command(root / "jdk/bin/java", args.agent,
                                                artifact_dir / "method-fixture.jar", identity, "none", oracle)
            command += ["--scenario", "normal"]
            case = ("17", "build-A", "none", "normal", False, 0, None)
            run = root / "runs/17-build-A-none-normal-function"
            run.mkdir(parents=True)
            outcome = {"kind": "BUSINESS_OUTCOME", "status": "ok", "result": "SYNTHETIC", "elapsedNanos": 0}
            (run / "stdout.jsonl").write_text(json.dumps(outcome) + "\n")
            (run / "telemetry.log").write_text("")
            (run / "command.json").write_text(json.dumps(command))
            (run / "result.json").write_text(json.dumps({
                "fingerprint": digest({"command": command, "artifact": identity["artifactSha256"],
                                       "index": index["indexSha256"], "oracle": oracle}),
                "metrics": {"wallSeconds": 0.1, "maxRssBytes": None}}))
            with patch.object(runner, "load_index", return_value=index), \
                    patch.object(runner, "validate_outcomes", side_effect=AssertionError("current oracle")) as validate:
                with self.assertRaisesRegex(AssertionError, "current oracle"):
                    runner.execute_case(case, args, oracle)
                self.assertEqual(1, validate.call_count)
            with patch.object(runner, "load_index", return_value=index), \
                    patch.object(runner.subprocess, "check_output", return_value="synthetic JDK 17"):
                result = runner.execute_case(case, args, oracle)
                self.assertTrue(result["executionReused"])
                (run / "telemetry.log").write_text("raw bytes changed")
                with self.assertRaisesRegex(ValueError, "raw evidence changed"):
                    runner.execute_case(case, args, oracle)


if __name__ == "__main__":
    unittest.main()
