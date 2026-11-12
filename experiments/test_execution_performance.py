"""Independent failure oracles for the local performance evidence boundary."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments import execution_performance as runner


def request_row(index, latency=100, status=201, error=None, phase="serial"):
    return {"id": index, "phase": phase, "eventId": "event-" + str(index), "traceId": str(index + 1) * 32,
            "parentSpanId": "2" * 16, "sent": True, "latencyNs": latency, "status": status, "validationError": error}


def resource(usage, before=1, after=2):
    return {"beforeNs": before, "afterNs": after, "cpuStat": {"usage_usec": usage, "nr_periods": 1, "nr_throttled": 2, "throttled_usec": 3}}


class MeasurementOracleTests(unittest.TestCase):
    def test_nearest_rank_does_not_interpolate(self):
        self.assertEqual(95, runner.nearest_rank(list(range(1, 101)), .95))
        self.assertEqual(30, runner.nearest_rank([30, 10, 20], .95))
        self.assertIsNone(runner.nearest_rank([], .99))
        with self.assertRaises(ValueError): runner.nearest_rank([1], 0)

    def test_fast_429_responses_cannot_hide_success_p95_or_inflate_goodput(self):
        rows = [request_row(i, 1, 429, "HTTP_429") for i in range(100)] + [request_row(100, 1000)]
        result = runner.latency_summary(rows, 1_000_000_000)
        self.assertEqual(1, result["allCompletedResponseLatency"]["p95Ns"])
        self.assertEqual(1000, result["successfulResponseLatency"]["p95Ns"])
        self.assertEqual(100, result["errors"])
        self.assertEqual(1, result["successfulGoodputPerSecond"])
        self.assertEqual({"201": 1, "429": 100}, result["statusCounts"])

    def test_timeout_and_unsent_deadline_samples_remain_in_denominators(self):
        timeout = request_row(1, 500, None, "TimeoutError")
        unsent = dict(request_row(2, None, None, "NOT_SENT_PHASE_DEADLINE"), sent=False)
        result = runner.latency_summary([request_row(0), timeout, unsent], 1000)
        self.assertEqual((3, 2, 1, 2, 1, 2), tuple(result[k] for k in
                         ("planned", "offered", "completedResponses", "completedAttempts", "successful", "errors")))
        self.assertEqual(1, result["successfulResponseLatency"]["count"])

    def test_cpu_counter_reset_is_not_negative_overhead(self):
        with self.assertRaisesRegex(AssertionError, "counter decreased"):
            runner.cpu_window(resource(200), resource(100, 10, 11), 1, 1)

    def test_cpu_cost_uses_explicit_response_and_success_denominators(self):
        result = runner.cpu_window(resource(1000, 0, 1000), resource(5000, 9_000_000, 10_000_000), 4, 2)
        self.assertEqual(4_000, result["counterDeltas"]["usage_usec"])
        self.assertEqual(1, result["cpuMsPerCompletedResponse"])
        self.assertEqual(2, result["cpuMsPerSuccessfulResponse"])
        self.assertEqual(.4, result["averageCoresInBracket"])

    def test_pid_memory_and_cgroup_memory_are_distinct(self):
        text = "CPU_STAT\nusage_usec 42\nnr_throttled 0\nthrottled_usec 0\nMEMORY_CURRENT\n9000\nPROCESS_STATUS\nName:\tjava\nVmRSS:\t2 kB\nVmHWM:\t3 kB\nPROCESS_COMM\njava\nCPU_MAX\n100000 100000\n"
        result = runner.parse_resource(text, 1, 5)
        self.assertEqual((2048, 3072, 9000), tuple(result[k] for k in ("vmRssBytes", "vmHwmBytes", "memoryCurrentBytes")))
        self.assertEqual("java", result["pid1Comm"])


class DrainOracleTests(unittest.TestCase):
    def setUp(self):
        self.rows = [request_row(0), request_row(1, 1000, None, "TimeoutError")]
        self.state = {"outboxRows": [{"eventId": r["eventId"], "published": True, "publishAttempts": 1} for r in self.rows],
                      "effectRows": [{"eventId": r["eventId"], "appliedCount": 1} for r in self.rows],
                      "cleanEventIds": [r["eventId"] for r in self.rows], "attemptCounts": {"applied": 2}}

    def test_timed_out_committed_event_is_still_inspected_and_drained(self):
        result = runner.drain_oracle(self.state, self.rows)
        self.assertTrue(result["complete"])
        self.assertEqual(["event-1"], result["unacknowledgedCommitted"])
        self.assertEqual((2, 1, 2), (result["sent"], result["accepted"], result["effectsExactlyOnce"]))

    def test_absent_outbox_does_not_prove_timed_out_work_has_ended(self):
        self.state["outboxRows"].pop(); self.state["effectRows"].pop(); self.state["cleanEventIds"].pop()
        result = runner.drain_oracle(self.state, self.rows)
        self.assertFalse(result["complete"])
        self.assertEqual(["event-1"], result["unresolvedSentRequestIds"])
        self.state["cleanEventIds"].append("event-1")
        self.assertTrue(runner.drain_oracle(self.state, self.rows)["complete"])

    def test_unpublished_or_missing_business_effect_never_passes_drain(self):
        self.state["outboxRows"][0]["published"] = False
        self.assertFalse(runner.drain_oracle(self.state, self.rows)["complete"])
        self.state["outboxRows"][0]["published"] = True
        self.state["effectRows"].pop()
        self.assertFalse(runner.drain_oracle(self.state, self.rows)["complete"])

    def test_success_after_duplicate_or_retry_is_not_clean_comparison(self):
        self.state["attemptCounts"].update({"duplicate": 1, "retryable-failure": 1})
        result = runner.drain_oracle(self.state, self.rows)
        self.assertTrue(result["complete"])
        self.assertFalse(result["expectedAttemptOutcomes"])

    def test_duplicate_effect_or_unowned_id_fails_closed(self):
        self.state["effectRows"][0]["appliedCount"] = 2
        with self.assertRaisesRegex(AssertionError, "exactly one"):
            runner.drain_oracle(self.state, self.rows)
        self.state["effectRows"][0] = {"eventId": "foreign", "appliedCount": 1}
        with self.assertRaisesRegex(AssertionError, "not sent"):
            runner.drain_oracle(self.state, self.rows)

    def test_sql_scope_rejects_interpolation_before_any_subprocess(self):
        with patch.object(runner, "cmd") as command:
            with self.assertRaises(ValueError): runner.owned_snapshot("container", "bad'; DELETE")
            command.assert_not_called()


class AgentCoverageTests(unittest.TestCase):
    def setUp(self):
        self.identity = {"repository": "local:test", "revision": "a" * 40, "build": "test", "module": "execution-mvc", "artifactSha256": "b" * 64}
        self.case = {"arm": "selected", "agentConfigSha256": "c" * 64}
        self.rows = [request_row(0), request_row(1, phase="parallel")]
        attrs = {"jjamtong.repository": "local:test", "jjamtong.revision": "a" * 40, "jjamtong.build": "test",
                 "jjamtong.module": "execution-mvc", "jjamtong.artifact.sha256": "b" * 64, "jjamtong.config.sha256": "c" * 64,
                 "telemetry.distro.version": "2.33.1", "telemetry.sdk.version": "1.67.0", "process.runtime.version": "21"}
        self.export = {"resource": {"attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()]},
                       "scopeSpans": [{"scope": {"name": "http"}, "spans": [
                           {"kind": 2, "traceId": r["traceId"], "parentSpanId": r["parentSpanId"]} for r in self.rows]},
                           {"scope": {"name": "io.opentelemetry.methods"}, "spans": [
                               {"kind": 1, "traceId": r["traceId"], "attributes": [
                                   {"key": "code.namespace", "value": {"stringValue": "io.jjamtong.sandbox.execution.ProbeService"}},
                                   {"key": "code.function", "value": {"stringValue": "create"}}]} for r in self.rows]}]}

    def evaluate(self, value=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.log"
            path.write_text(json.dumps(self.export if value is None else value) + "\n")
            return runner.telemetry_summary(path, self.case, self.identity, self.rows)

    def test_selected_positive_correlates_each_phase_input(self):
        result = self.evaluate()
        self.assertEqual("EXPECTED_INPUTS_OBSERVED", result["status"])
        self.assertEqual((2, 2, 2), tuple(result[k] for k in ("expectedSuccessfulInputs", "observedHttpInputs", "observedSelectedCreateInputs")))

    def test_missing_one_method_is_partial_even_when_other_methods_exist(self):
        self.export["scopeSpans"][1]["spans"].pop()
        result = self.evaluate()
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual([self.rows[1]["traceId"]], result["missingSelectedCreateTraceIds"])

    def test_zero_agent_coverage_is_partial_not_zero_loss(self):
        result = self.evaluate({})
        self.assertEqual("PARTIAL", result["status"])
        self.assertIn("ZERO_AGENT_HTTP_COVERAGE", result["issues"])

    def test_wrong_artifact_identity_is_rejected(self):
        self.identity["artifactSha256"] = "f" * 64
        with self.assertRaisesRegex(AssertionError, "artifact identity mismatch"): self.evaluate()

    def test_default_must_have_http_and_no_selected_method_spans(self):
        self.case["arm"] = "default"
        self.assertIn("UNEXPECTED_METHOD_SPANS_IN_DEFAULT", self.evaluate()["issues"])
        self.export["scopeSpans"].pop()
        self.assertEqual("EXPECTED_INPUTS_OBSERVED", self.evaluate()["status"])

    def test_none_must_have_no_agent_spans(self):
        self.case["arm"] = "none"
        self.assertIn("UNEXPECTED_AGENT_SPANS_IN_NONE", self.evaluate()["issues"])
        self.assertEqual("EXPECTED_INPUTS_OBSERVED", self.evaluate({})["status"])

    def test_http_same_trace_wrong_remote_parent_is_partial(self):
        self.export["scopeSpans"][0]["spans"][0]["parentSpanId"] = "f" * 16
        self.assertIn(self.rows[0]["traceId"], self.evaluate()["missingHttpTraceIds"])


class RepeatAndPreservationTests(unittest.TestCase):
    def result(self, arm, rep, value, eligible=True):
        latency = runner.latency_summary([request_row(0, value)], 1_000_000_000)
        phase = {"phase": "serial", "latency": latency,
                 "resources": {"httpWindow": {"cpuMsPerSuccessfulResponse": value},
                               "completionWindow": {"cpuMsPerSuccessfulResponse": value},
                               "sampledVmRssPeakBytes": value, "sampledCgroupMemoryPeakBytes": value}}
        return {"case": {"model": "mvc-platform", "arm": arm, "repetition": rep}, "phases": [phase], "comparisonEligible": eligible}

    def test_repeat_median_paired_range_and_error_arm_exclusion(self):
        results = [self.result(arm, rep, value, not (arm == "selected" and rep == 3))
                   for arm, values in (("none", [100, 200, 400]), ("default", [110, 220, 440]), ("selected", [120, 240, 1]))
                   for rep, value in enumerate(values, 1)]
        result = runner.aggregate(results)
        group = next(g for g in result["groups"] if g["arm"] == "selected" and g["phase"] == "serial")
        self.assertEqual([120, 240, 1], group["metrics"]["successP95Ns"]["raw"])
        self.assertFalse(group["allComparisonEligible"])
        delta = next(d for d in result["pairedDeltas"] if d["baselineArm"] == "none" and d["candidateArm"] == "selected" and d["phase"] == "serial")
        self.assertEqual({"median": 20, "min": 20, "max": 20}, delta["eligibleMedianAndRange"]["successP95Ns"])
        incremental = next(d for d in result["pairedDeltas"] if d["baselineArm"] == "default" and d["candidateArm"] == "selected" and d["phase"] == "serial")
        self.assertAlmostEqual(100 / 11, incremental["eligibleMedianAndRange"]["successP95Ns"]["median"])

    def test_raw_record_mutation_fails_before_any_container_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            raw = path / "serial-latency.jsonl"; raw.write_text("original\n")
            runner.write_json(path / "hashes.json", {raw.name: runner.file_digest(raw)})
            raw.write_text("mutated\n")
            with patch.object(runner, "cmd") as command:
                with self.assertRaisesRegex(AssertionError, "raw evidence hash mismatch"):
                    runner.revalidate_case(path, {}, {})
                command.assert_not_called()

    def test_reloaded_rows_keep_original_phase_order_for_drain_sentinel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for i, phase in enumerate(("parallel", "warmup", "serial", "preflight")):
                (path / (phase + "-latency.jsonl")).write_text(json.dumps(request_row(i, phase=phase)) + "\n")
            self.assertEqual(["preflight", "warmup", "serial", "parallel"], [r["phase"] for r in runner.read_rows(path)])


class CleanupAndSamplerFailureTests(unittest.TestCase):
    def exercise_cleanup(self, directory, *, stop_error=None, log_error=None, inspect_error=None, mismatch=False):
        case = {"id": "mvc-platform-r1-none", "module": "execution-mvc", "model": "mvc-platform",
                "arm": "none", "mode": "perf-test-mp-1-none"}
        baseline = ["baseline-id jjamtong-sandbox-postgres-1"]
        manifest = {"session": "test", "identities": {"execution-mvc": {}},
                    "imageIds": {"execution-mvc": "sha256:synthetic"}, "baselineContainers": baseline}
        labels = {"jjamtong.experiment": "execution-performance", "jjamtong.session": "test", "jjamtong.case": case["id"]}
        if mismatch: labels["jjamtong.session"] = "another-owner"
        calls = []
        def command(parts, **_):
            calls.append(parts)
            operation = parts[1]
            if operation == "run": return SimpleNamespace(stdout="owned-id\n", returncode=0)
            if operation == "inspect":
                if inspect_error: raise inspect_error
                return SimpleNamespace(stdout=json.dumps(labels), returncode=0)
            if operation == "stop" and stop_error: raise stop_error
            return SimpleNamespace(stdout="", returncode=0)
        def logs(_container, path):
            if log_error: raise log_error
            path.write_bytes(b"")
            return {"complete": True, "sha256": runner.file_digest(path)}
        with patch.object(runner, "cmd", side_effect=command), \
                patch.object(runner, "containers", return_value=baseline) as baseline_check, \
                patch.object(runner, "wait_ready", side_effect=RuntimeError("synthetic startup failure")), \
                patch.object(runner, "capture_logs", side_effect=logs):
            with self.assertRaisesRegex(RuntimeError, "synthetic startup failure"):
                runner.run_case(SimpleNamespace(output=directory), manifest, case)
        path = directory / case["id"]
        result, hashes = json.loads((path / "result.json").read_text()), json.loads((path / "hashes.json").read_text())
        self.assertEqual(2, baseline_check.call_count, "Baseline verification was skipped after cleanup failure")
        self.assertEqual(runner.file_digest(path / "result.json"), hashes["result.json"])
        self.assertEqual(runner.file_digest(path / "case.json"), hashes["case.json"])
        return calls, result

    def test_stop_timeout_and_log_failure_still_remove_owned_container_and_persist_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            calls, result = self.exercise_cleanup(Path(directory), stop_error=subprocess.TimeoutExpired(["docker", "stop"], 30),
                                                  log_error=RuntimeError("synthetic log failure"))
        self.assertEqual("rm", calls[-1][1])
        self.assertEqual("owned-id", calls[-1][-1])
        self.assertTrue(result["removed"])
        self.assertTrue(result["baselineContainersPreserved"])
        self.assertEqual([{"stage": "stop", "errorType": "TimeoutExpired"}, {"stage": "logs", "errorType": "RuntimeError"}],
                         result["cleanupFailures"])

    def test_unknown_or_mismatched_ownership_preserves_evidence_without_removal(self):
        for options in ({"inspect_error": subprocess.TimeoutExpired(["docker", "inspect"], 30)}, {"mismatch": True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                calls, result = self.exercise_cleanup(Path(directory), **options)
                self.assertFalse(any(c[1] in {"stop", "rm"} for c in calls))
                self.assertFalse(result["ownershipVerified"])
                self.assertFalse(result["removed"])
                self.assertEqual("ownership-inspect", result["cleanupFailures"][0]["stage"])

    def test_sampler_parse_errors_are_recorded_and_exclude_comparison(self):
        oracle = {"complete": True, "expectedAttemptOutcomes": True}
        phase = {"phase": "serial", "latency": {"errors": 0}, "drain": {"oracle": oracle}, "resources": {"samplerErrors": []}}
        result = {"status": "BUSINESS_COMPLETE", "phases": [deepcopy(phase), dict(deepcopy(phase), phase="parallel")],
                  "warmup": {"latency": {"errors": 0}, "drain": {"oracle": oracle}},
                  "preflight": {"drain": {"oracle": oracle}}, "finalDrain": {"oracle": oracle},
                  "baselineContainersPreserved": True, "removed": True, "stop": {"exitCode": 0}}
        self.assertTrue(runner.comparison_eligible(result, {"status": "EXPECTED_INPUTS_OBSERVED"}))
        for error in (ValueError("bad counter"), KeyError("CPU_STAT")):
            with self.subTest(error=type(error).__name__):
                sampler = runner.Sampler("synthetic-container")
                with patch.object(sampler.stop_event, "wait", side_effect=[False, True]), patch.object(runner, "snapshot", side_effect=error):
                    sampler.loop()
                self.assertEqual([type(error).__name__], sampler.errors)
                result["phases"][0]["resources"]["samplerErrors"] = sampler.errors
                self.assertFalse(runner.comparison_eligible(result, {"status": "EXPECTED_INPUTS_OBSERVED"}))


if __name__ == "__main__":
    unittest.main()
