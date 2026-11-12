"""Contract, failure-injection, and oracle-sensitivity tests for the experiment."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.architecture_lab.lab import (
    HERE, VARIANTS, Engine, InjectedCrash, Source, delivery, run_case,
)


class ArchitectureLabTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.records = json.loads((HERE / "fixtures/base.json").read_text())
        self.cases = json.loads((HERE / "fixtures/scenarios.json").read_text())

    def tearDown(self):
        self.temporary.cleanup()

    def engine(self, variant="events"):
        engine = Engine(variant, Source(self.records), self.root / "state.sqlite")
        self.addCleanup(lambda: engine.store.close())
        self.assertTrue(engine.poll())
        return engine

    def test_all_scenarios_and_variants_enforce_safety_oracles(self):
        for case in self.cases:
            for variant in VARIANTS:
                with self.subTest(case=case["id"], variant=variant):
                    directory = self.root / (case["id"] + variant)
                    directory.mkdir()
                    result = run_case(case, variant, directory)
                    self.assertTrue(result["safety_oracles_passed"])

    def test_crash_rolls_back_projection_and_processed_marker_together(self):
        engine = self.engine()
        record = engine.source.change("catalog/api", {"payload": {"owner": "team-B"}}, 1)
        with self.assertRaises(InjectedCrash):
            engine.receive(delivery(record, "one"), "mid_projection")
        self.assertEqual(engine.store.stats()["pending_deliveries"], 1)
        self.assertEqual(engine.store.stats()["evidence_revisions"], 10)
        engine.tick = 1
        engine.restart()
        self.assertEqual(engine.store.stats()["pending_deliveries"], 0)
        self.assertEqual(engine.view()["catalog/api"]["payload"]["owner"], "team-B")

    def test_successful_redelivery_is_idempotent_and_conflicts_are_rejected(self):
        engine = self.engine()
        engine.tick = 1
        record = engine.source.change("catalog/api", {"payload": {"owner": "team-B"}}, 1)
        message = delivery(record, "one")
        engine.receive(message)
        engine.receive(message)
        self.assertEqual(engine.store.stats()["evidence_revisions"], 11)
        self.assertEqual(engine.store.stats()["inbox_rows"], 1)
        changed = copy.deepcopy(record)
        changed["payload"]["owner"] = "conflict"
        with self.assertRaises(ValueError):
            engine.receive(delivery(changed, "one"))
        with self.assertRaises(ValueError):
            engine.receive(delivery(changed, "different-delivery"))
        self.assertEqual(engine.view()["catalog/api"]["payload"]["owner"], "team-B")

    def test_incomplete_scan_does_not_publish_or_advance_success(self):
        engine = self.engine("poll")
        engine.source.change("catalog/api", {"payload": {"owner": "team-B"}}, 1)
        engine.source.fail_page = 2
        engine.advance(5)
        self.assertEqual(engine.store.stats()["last_scan_success"], 0)
        self.assertEqual(engine.store.stats()["evidence_revisions"], 10)
        self.assertEqual(engine.view()["catalog/api"]["payload"]["owner"], "team-A")

    def test_request_does_not_fall_back_to_an_incompatible_code_snapshot(self):
        engine = self.engine()
        bad = engine.source.change("code/A", {"payload": {
            "build": "B", "artifact": "sha256:bbb", "methods": ["BoardService.list"]}}, 1)
        engine.tick = 1
        engine.receive(delivery(bad, "bad-code"))
        self.assertEqual(engine.inspect_request("trace/A"), {"status": "mismatch"})

    def test_oracle_rejects_latest_build_for_old_trace(self):
        case = next(c for c in self.cases if c["id"] == "X09")
        with patch.object(Engine, "inspect_request", return_value={
                "status": "ok", "build": "B", "artifact": "sha256:bbb", "method": "BoardService.list"}):
            with self.assertRaises(AssertionError):
                run_case(case, "hybrid", self.root)

    def test_oracle_rejects_an_always_empty_result(self):
        case = next(c for c in self.cases if c["id"] == "X01")
        with patch.object(Engine, "view", return_value={}):
            with self.assertRaises(AssertionError):
                run_case(case, "hybrid", self.root)

    def test_source_namespaces_are_not_silently_merged(self):
        engine = self.engine()
        other = copy.deepcopy(self.records[0])
        other["source"] = "different-provider"
        engine.store.snapshot([other], 0)
        with self.assertRaises(ValueError):
            engine.view()

    def test_os_process_exit_recovers_inbox_and_uncommitted_projection(self):
        script = '''
import json, os, sys
from experiments.architecture_lab.lab import HERE, Engine, Source, delivery, InjectedCrash
engine = Engine("events", Source(json.loads((HERE / "fixtures/base.json").read_text())), sys.argv[1])
engine.poll()
engine.tick = 1
record = engine.source.change("catalog/api", {"payload": {"owner": "team-B"}}, 1)
if sys.argv[2] == "mid_projection":
    original = engine.store._project
    def crash(record, tick):
        original(record, tick)
        os._exit(17)
    engine.store._project = crash
    engine.receive(delivery(record, "durable-one"))
else:
    try:
        engine.receive(delivery(record, "durable-one"), "after_inbox")
    except InjectedCrash:
        os._exit(17)
raise RuntimeError("crash was not reached")
'''
        for fault in ("after_inbox", "mid_projection"):
            with self.subTest(fault=fault):
                path = self.root / (fault + ".sqlite")
                process = subprocess.run([sys.executable, "-c", script, str(path), fault],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 17, process.stderr)
                engine = Engine("events", Source(self.records), path)
                try:
                    self.assertEqual(engine.store.stats()["evidence_revisions"], 10)
                    self.assertEqual(engine.store.stats()["pending_deliveries"], 1)
                    engine.tick = 1
                    engine.store.recover(1)
                    self.assertEqual(engine.store.stats()["pending_deliveries"], 0)
                    self.assertEqual(engine.view()["catalog/api"]["payload"]["owner"], "team-B")
                finally:
                    engine.store.close()


if __name__ == "__main__":
    unittest.main()
