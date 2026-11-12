"""Owned-flow evidence must survive valid Links and reject causal mutations.

These are hand-authored span graphs, independent of an exporter or Docker.
They test the acceptance boundary used to revalidate preserved smoke evidence.
"""
from copy import deepcopy
import unittest

from experiments import execution_agent_smoke as runner


class OwnedFlowEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.mode = "mvc-platform"
        self.http_trace = "1" * 32
        self.producer_trace = "6" * 32
        self.parent = "00-" + self.http_trace + "-" + "2" * 16 + "-01"
        self.header = "00-" + self.producer_trace + "-" + "7" * 16 + "-03"
        identity = {"repository": "local:synthetic", "revision": "a" * 40,
                    "build": "synthetic-b1", "module": "execution-mvc", "artifactSha256": "b" * 64}
        self.metadata = {"identities": {self.mode: identity},
                         "configs": {self.mode: {"configSha256": "c" * 64}}}
        self.resource = {"jjamtong.repository": "local:synthetic", "jjamtong.revision": "a" * 40,
                         "jjamtong.build": "synthetic-b1", "jjamtong.module": "execution-mvc",
                         "jjamtong.artifact.sha256": "b" * 64, "jjamtong.config.sha256": "c" * 64}
        self.runtime = {"javaVersion": "synthetic-21", "server": "synthetic-tomcat"}
        self.event = {"outbox": [{"traceparent": self.parent}], "observations": [],
                      "attempts": [{"traceparent": self.header}], "effects": [{"applied_count": 1}]}
        self.created = {"redisRoundTrip": True}
        self.spans = [
            self.span(self.http_trace, "3", "2", 2, "http-server"),
            self.span(self.http_trace, "4", "3", 1, "io.opentelemetry.methods",
                      {"code.namespace": "io.jjamtong.sandbox.execution.ProbeService", "code.function": "create"}),
            self.span(self.http_trace, "5", "4", 3, "jdbc", {"db.system": "postgresql"}),
            self.span(self.producer_trace, "7", None, 4, "kafka", {"messaging.system": "kafka"}),
            self.span(self.producer_trace, "8", "7", 5, "kafka", {"messaging.system": "kafka"}),
            self.span(self.producer_trace, "9", "8", 1, "io.opentelemetry.methods",
                      {"code.namespace": "io.jjamtong.sandbox.execution.ProbeService", "code.function": "accept"}),
        ]

    def span(self, trace, own, parent, kind, scope, attributes=None):
        return {"traceId": trace, "spanId": own * 16, "parentSpanId": parent * 16 if parent else None,
                "kind": kind, "scope": scope, "resource": deepcopy(self.resource),
                "attributes": attributes or {}, "links": [], "error": False}

    def validate(self):
        return runner.summarize(self.mode, self.metadata, self.runtime, self.event,
                                self.parent, self.spans, self.created)

    def test_direct_parent_flow_accepts_business_without_redis_client_span(self):
        result = self.validate()
        self.assertEqual(1, result["effects"])
        self.assertEqual(1, result["consumerProducerDirectParents"])
        self.assertEqual(0, result["consumerProducerLinks"])
        self.assertTrue(result["redisBusinessRoundTripObserved"])
        self.assertEqual(0, result["redisClientSpanCountInHttpTrace"])
        self.assertFalse(result["scheduledOutboxPreservedIncomingSdkTrace"])

    def test_cross_trace_link_is_valid_causality(self):
        self.spans[4]["traceId"] = "d" * 32
        self.spans[4]["parentSpanId"] = None
        self.spans[4]["links"] = [{"traceId": self.producer_trace, "spanId": "7" * 16}]
        self.spans[5]["traceId"] = "d" * 32
        result = self.validate()
        self.assertEqual(0, result["consumerProducerDirectParents"])
        self.assertEqual(1, result["consumerProducerLinks"])
        self.assertTrue(result["selectedAcceptDescendsFromConnectedConsumer"])
        self.assertFalse(result["selectedAcceptInProducerTrace"])

    def test_future_preserved_sdk_context_is_observation_not_failure(self):
        for span in self.spans[3:]:
            span["traceId"] = self.http_trace
        self.event["attempts"][0]["traceparent"] = "00-" + self.http_trace + "-" + "7" * 16 + "-03"
        self.assertTrue(self.validate()["scheduledOutboxPreservedIncomingSdkTrace"])

    def test_header_trace_match_without_exact_producer_span_does_not_pass(self):
        self.event["attempts"][0]["traceparent"] = "00-" + self.producer_trace + "-" + "f" * 16 + "-03"
        with self.assertRaisesRegex(AssertionError, "consumerHeaderMatchesOwnedProducerSpan"):
            self.validate()

    def test_consumer_in_same_trace_with_wrong_parent_does_not_pass(self):
        self.spans[4]["parentSpanId"] = "f" * 16
        with self.assertRaisesRegex(AssertionError, "producerAndConsumerRelationObserved"):
            self.validate()

    def test_http_trace_without_supplied_remote_parent_does_not_pass(self):
        self.spans[0]["parentSpanId"] = "f" * 16
        with self.assertRaisesRegex(AssertionError, "httpExtractionObserved"):
            self.validate()

    def test_jdbc_in_unrelated_trace_does_not_prove_owned_request(self):
        self.spans[2]["traceId"] = "e" * 32
        with self.assertRaisesRegex(AssertionError, "No JDBC client span"):
            self.validate()

    def test_controller_create_cannot_substitute_for_service_method(self):
        self.spans[1]["attributes"]["code.namespace"] = "io.jjamtong.sandbox.executionmvc.ExecutionMvcController"
        with self.assertRaisesRegex(AssertionError, "selectedCreateInHttpTrace"):
            self.validate()

    def test_accept_method_in_trace_but_outside_consumer_descendants_does_not_pass(self):
        self.spans[5]["parentSpanId"] = "f" * 16
        with self.assertRaisesRegex(AssertionError, "selectedAcceptDescendsFromConnectedConsumer"):
            self.validate()

    def test_missing_selected_accept_method_does_not_pass(self):
        self.spans.pop()
        with self.assertRaisesRegex(AssertionError, "selectedAcceptDescendsFromConnectedConsumer"):
            self.validate()

    def test_spans_cannot_substitute_for_redis_business_result(self):
        self.created["redisRoundTrip"] = False
        with self.assertRaisesRegex(AssertionError, "redisBusinessRoundTripObserved"):
            self.validate()

    def test_duplicate_business_effect_is_rejected(self):
        self.event["effects"][0]["applied_count"] = 2
        with self.assertRaisesRegex(AssertionError, "exactly one business effect"):
            self.validate()

    def test_wrong_deployed_artifact_is_rejected(self):
        self.spans[2]["resource"]["jjamtong.artifact.sha256"] = "f" * 64
        with self.assertRaisesRegex(AssertionError, "actual deployed artifact/config identity"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
