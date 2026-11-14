import unittest

from .model import AnalysisVersion, ObservedSpan, TraceStream


BUILD = ("local:test", "revision-a", "build-a", "board", "a" * 64)
CONFIG = "c" * 64
TRACE = "1" * 32


def span(span_id="2" * 16, **changes):
    values = dict(trace_id=TRACE, span_id=span_id, build_identity=BUILD,
                  telemetry_config_sha256=CONFIG, class_name="fixture.Board", method_name="find")
    values.update(changes)
    return ObservedSpan(**values)


class TraceStreamContractTests(unittest.TestCase):
    def setUp(self):
        self.version = AnalysisVersion("run-a", "b" * 64, BUILD, CONFIG)
        self.stream = TraceStream(self.version)

    def test_append_and_identical_replay_are_idempotent(self):
        item = span()
        self.assertEqual("APPENDED", self.stream.append(item)["outcome"])
        self.assertEqual("REPLAYED", self.stream.append(item)["outcome"])
        result = self.stream.replay(TRACE, {("fixture.Board", "find"): (("board", "fixture.Board", "find", "()V"),)})
        self.assertEqual("OBSERVED", result["status"])
        self.assertEqual(1, len(result["spans"]))
        self.assertEqual("unique-name-resolved", result["spans"][0]["symbolStatus"])
        self.assertEqual("run-a", result["analysisVersion"]["run_id"])

    def test_conflicting_replay_never_overwrites_first_observation(self):
        self.stream.append(span())
        conflict = self.stream.append(span(method_name="other"))
        self.assertEqual({"outcome": "CONFLICT", "reason": "CONFLICTING_SPAN_REPLAY"}, conflict)
        replay = self.stream.replay(TRACE, {})
        self.assertEqual("find", replay["spans"][0]["method"])
        self.assertEqual("PARTIAL", replay["status"])
        self.assertIn("CONFLICTING_SPAN_REPLAY", replay["collectionReasons"])
        self.assertEqual(["2" * 16], replay["conflictingSpanIds"])

    def test_conflicts_do_not_contaminate_a_different_trace(self):
        self.stream.append(span())
        self.stream.append(span(method_name="other"))
        other = "6" * 32
        self.stream.append(span(trace_id=other))
        replay = self.stream.replay(other, {})
        self.assertEqual("OBSERVED", replay["status"])
        self.assertEqual([], replay["conflictingSpanIds"])
        self.assertNotIn("CONFLICTING_SPAN_REPLAY", replay["collectionReasons"])

    def test_partial_frame_preserves_limit_and_invalid_input_without_success_claim(self):
        outcomes = self.stream.append_frame([span(), object()], complete=False)
        self.assertEqual(["APPENDED", "REJECTED"], [outcome["outcome"] for outcome in outcomes])
        result = self.stream.replay(TRACE, {})
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(["INPUT_FRAME_NOT_FINAL", "PARTIAL_OR_INVALID_INPUT"], result["collectionReasons"])

    def test_exact_version_boundaries_reject_other_build_or_telemetry_configuration(self):
        self.assertEqual("BUILD_IDENTITY_MISMATCH", self.stream.append(span(build_identity=BUILD[:-1] + ("d" * 64,)))["reason"])
        self.assertEqual("TELEMETRY_CONFIG_MISMATCH", self.stream.append(span(telemetry_config_sha256="e" * 64))["reason"])
        result = self.stream.replay(TRACE, {})
        self.assertEqual("UNRESOLVED", result["status"])
        self.assertEqual("b" * 64, result["analysisVersion"]["index_sha256"])

    def test_parent_and_link_are_observed_relations_and_overload_stays_unresolved(self):
        child = span(parent_span_id="3" * 16, links=(("4" * 32, "5" * 16),))
        self.stream.append(child)
        candidates = {("fixture.Board", "find"): (("board", "fixture.Board", "find", "()V"),
                                                     ("board", "fixture.Board", "find", "(I)V"))}
        result = self.stream.replay(TRACE, candidates)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual("UNRESOLVED_CODE_SYMBOL", result["spans"][0]["symbolStatus"])
        self.assertEqual("observed-span-parent", result["observedParents"][0]["relation"])
        self.assertEqual("external-or-not-collected", result["observedParents"][0]["parentState"])
        self.assertEqual("observed-span-link", result["observedLinks"][0]["relation"])
        self.assertIn("PARENT_EXTERNAL_OR_NOT_COLLECTED", result["collectionReasons"])


if __name__ == "__main__":
    unittest.main()
