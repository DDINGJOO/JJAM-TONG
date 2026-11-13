"""Failure cleanup and a deterministic regression for the measurement interval."""
import threading
import unittest
from unittest.mock import Mock, patch

from . import federation, run
from .fixtures import dataset, expected_counts, expected_events, expected_reachable, key, scope


class RunnerContracts(unittest.TestCase):
    def test_initial_readiness_failure_still_stops_engine(self):
        with patch.object(run, "compose") as compose, patch.object(run, "ready", side_effect=RuntimeError("not ready")):
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                run.run_engine("neo4j", [], 1, False)
        self.assertIn(unittest.mock.call("stop", "neo4j"), compose.call_args_list)
        self.assertIn(unittest.mock.call("stop", "postgres"), compose.call_args_list)

    def test_partial_federation_startup_closes_opened_store(self):
        primary = Mock()
        with patch.object(federation, "compose"), patch.object(federation, "ready", side_effect=[primary, RuntimeError("not ready")]):
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                federation.run()
        primary.close.assert_called_once()

    def test_parent_scheduling_delay_cannot_exclude_worker_operations(self):
        rows = dataset(150, 1000)
        counts = expected_counts(rows, scope())
        events = expected_events(rows, scope(), "timeout")
        graph = expected_reachable(rows, scope(), key("alpha", "build-A", "dispatcher"), 3)
        clock, active = [0.0], []
        lock = threading.Lock()
        real_barrier = threading.Barrier

        class DelayedParent:
            def __init__(self, parties, action=None):
                self.barrier = real_barrier(parties, action=action)
                self.remaining = parties - 1
                self.done = threading.Event()
                active[:] = [self]

            def wait(self, timeout):
                self.barrier.wait(timeout)
                if threading.current_thread() is threading.main_thread():
                    if not self.done.wait(timeout):
                        raise AssertionError("workers did not finish")

        class Adapter:
            def query(self, result):
                with lock:
                    clock[0] += 1.0
                return result

            def counts(self, selected):
                return self.query(counts)

            def events(self, selected, token):
                return self.query(events)

            def reachable(self, *args):
                return self.query(graph)

            def close(self):
                with lock:
                    active[0].remaining -= 1
                    if active[0].remaining == 0:
                        active[0].done.set()

        with patch.dict(run.STORES, test=Adapter), patch.object(run.threading, "Barrier", DelayedParent), \
                patch.object(run.time, "perf_counter", side_effect=lambda: clock[0]):
            measured = run.concurrent_reads("test", rows)
        for probe in measured:
            self.assertEqual(probe["elapsed_seconds"], probe["operations"])


if __name__ == "__main__":
    unittest.main()
