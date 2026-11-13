"""Reject incomplete or altered measurements instead of reporting a false winner."""
import copy
import unittest
from unittest.mock import patch

from . import run


def successful_sample(expected):
    return {"status": "correct", "ms": 1.0, "count": len(expected),
            "sha256": run.result_hash(expected), "round_trips": 1}


def minimal_record():
    n, density = 64, 2
    inputs, checks = run.expected_cases(n, density)
    case = {"engine": "postgres", "methods_per_build": n, "local_static_degree": density,
            "input_sha256": run.fingerprint(n, density),
            "scopes": [{"id": sid, "metadata": meta, "nodes": len(ns), "edges": len(es)}
                       for sid, meta, ns, es in inputs],
            "scope_checks": {"unknown_empty": True, "missing_rejected": True},
            "sequential": [], "concurrent": []}
    for mode in ("native", "frontier"):
        for check in checks:
            item = {k: v for k, v in check.items() if k != "expected"}
            sample = successful_sample(check["expected"])
            item.update({"mode": mode, "expected_count": len(check["expected"]),
                         "expected_sha256": run.result_hash(check["expected"]),
                         "warmups": [] if check["revision"] == "decoy" else [sample] * run.WARMUPS,
                         "samples": [sample] * (1 if check["revision"] == "decoy" else run.REPETITIONS)})
            item["summary"] = run.summarize(item["samples"])
            case["sequential"].append(item)
    for mode in ("native", "frontier"):
        for clients in (1, 4, 8):
            samples = [{"label": c["question"]["label"], **successful_sample(c["expected"])}
                       for c in checks if c["revision"] == "old"] * clients
            case["concurrent"].append({"mode": mode, "clients": clients, "samples": samples,
                                       "operations_per_client": 6, "elapsed_seconds": 1,
                                       "completed_ops_per_second": len(samples),
                                       "summary": run.summarize(samples)})
    neo = copy.deepcopy(case)
    neo["engine"] = "neo4j"
    case["plans"] = [{"question": q, "plan": {"plan": {"Node Type": "Recursive Union"}}}
                     for q in run.questions(n)]
    neo["plans"] = [{"question": q, "plan": {"plan": {"operatorType": "VarLengthExpand(Pruning,BFS,All)"}}}
                    for q in run.questions(n)]
    return {"schema": "graph-scale-run/v1", "status": "complete", "run_id": "unit-test-only",
            "cases": [case, neo], "cleanup": {"lab_containers_removed": True, "unrelated_still_running": True}}


class MeasurementContractTest(unittest.TestCase):
    def setUp(self):
        self.manifest = patch.object(run, "verify_manifest")
        self.scales = patch.object(run, "SCALES", ((64, 2),))
        self.manifest.start()
        self.scales.start()
        self.addCleanup(self.manifest.stop)
        self.addCleanup(self.scales.stop)

    def test_complete_record_and_native_budget_are_distinct(self):
        record = minimal_record()
        self.assertEqual(run.validate(record)["status"], "verified")
        item = record["cases"][0]["sequential"][0]
        item["samples"][0] = {"status": "budget_exceeded", "ms": 10001.0,
                              "code": "57014", "error": "server cancelled"}
        item["summary"] = run.summarize(item["samples"])
        self.assertEqual(run.validate(record)["status"], "verified")
        self.assertEqual(item["summary"]["budget_exceeded"], 1)

    def test_corruption_and_missing_evidence_rejected(self):
        mutations = [
            lambda r: r["cases"].pop(),
            lambda r: r["cases"][0]["scopes"][0].update(nodes=0),
            lambda r: r["cases"][0]["sequential"].pop(),
            lambda r: r["cases"][1]["plans"][1]["plan"].update(plan={"operatorType": "VarLengthExpand(All)"}),
            lambda r: r["cases"][0]["sequential"][0]["samples"].pop(),
            lambda r: r["cases"][0]["sequential"][0]["samples"][0].update(sha256="wrong"),
            lambda r: r["cases"][0]["concurrent"][0]["samples"].pop(),
            lambda r: r["cases"][0]["concurrent"][0].update(mode="unknown"),
            lambda r: r["cases"][0]["concurrent"][0].update(completed_ops_per_second=1000),
            lambda r: r["cases"][0]["concurrent"][0].update(operations_per_client=1),
            lambda r: r["cases"][0]["concurrent"][0]["samples"][0].update(ms=float("nan")),
            lambda r: r["cleanup"].update(unrelated_still_running=False),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                record = minimal_record()
                mutation(record)
                with self.assertRaises(ValueError):
                    run.validate(record)

    def test_arbitrary_server_errors_are_not_timeouts(self):
        for code in ("Neo.ClientError.Statement.SyntaxError", "transport.timeout", "BudgetExceeded"):
            with self.assertRaises(ValueError):
                run.check_sample({"status": "budget_exceeded", "ms": 5, "code": code}, 0, "hash")

    def test_repeating_easy_question_cannot_replace_deep_workload(self):
        record = minimal_record()
        result = record["cases"][0]["concurrent"][0]
        result["samples"] = [copy.deepcopy(result["samples"][0]) for _ in range(6)]
        with self.assertRaises(ValueError):
            run.validate(record)

    def test_all_scale_inputs_have_distinct_immutable_scopes(self):
        scopes = {run.scope_id(run.metadata(revision, size=n, density=density))
                  for n, density in ((10000, 2), (10000, 6), (100000, 2), (100000, 6))
                  for revision in ("old", "new")}
        self.assertEqual(len(scopes), 8)

    def test_monotonic_percentile_and_timeout_exclusion(self):
        self.assertEqual(run.percentile(list(range(1, 21)), .95), 19)
        summary = run.summarize([{"status": "correct", "ms": 2},
                                 {"status": "budget_exceeded", "ms": 10000}])
        self.assertEqual(summary, {"correct": 1, "budget_exceeded": 1, "p50_ms": 2, "p95_ms": 2})


if __name__ == "__main__":
    unittest.main()
