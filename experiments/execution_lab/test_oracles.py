"""The runner must reject corrupted version/context observations and empty evidence."""
import copy
import unittest

from experiments.execution_lab.compare import validate_event


class EvidenceOracleTest(unittest.TestCase):
    def fixture(self):
        parent, digest = '00-' + '1' * 32 + '-' + '2' * 16 + '-01', 'a' * 64
        stages = ['request-ingress', 'request-work', 'request-clean', 'outbox-publish',
                  'publisher-clean', 'consumer-attempt', 'consumer-clean']
        event = {'outbox': [{'published': True, 'traceparent': parent}],
                 'effects': [{'applied_count': 1}],
                 'attempts': [{'traceparent': parent}],
                 'observations': [{'stage': stage, 'artifact_sha256': digest,
                                   'build_id': 'test-build',
                                   'context_before': None, 'context_after': None,
                                   'traceparent': None if stage.endswith('-clean') else parent}
                                  for stage in stages]}
        return event, parent, digest, 'test-build'

    def test_realistic_evidence_is_accepted(self):
        validate_event(*self.fixture())

    def test_wrong_build_rejected(self):
        event, parent, digest, build_id = self.fixture()
        for key in ['artifact_sha256', 'build_id']:
            corrupt = copy.deepcopy(event)
            corrupt['observations'][1][key] = 'wrong-build'
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_event(corrupt, parent, digest, build_id)

    def test_cross_request_context_and_leak_rejected(self):
        event, parent, digest, build_id = self.fixture()
        for key in ['traceparent', 'context_before']:
            corrupt = copy.deepcopy(event)
            corrupt['observations'][1][key] = 'another-request'
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_event(corrupt, parent, digest, build_id)

    def test_missing_stage_and_duplicate_effect_rejected(self):
        event, parent, digest, build_id = self.fixture()
        for key, value in [('observations', []), ('attempts', []), ('effects', [{'applied_count': 2}])]:
            corrupt = copy.deepcopy(event)
            corrupt[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_event(corrupt, parent, digest, build_id)

    def test_missing_context_stays_explicitly_unresolved(self):
        event, parent, digest, build_id = self.fixture()
        event['attempts'][0]['traceparent'] = None
        next(row for row in event['observations'] if row['stage'] == 'consumer-attempt')['traceparent'] = None
        validate_event(event, parent, digest, build_id, missing=True)
        with self.assertRaises(AssertionError):
            validate_event(event, parent, digest, build_id)

    def test_missing_identity_is_not_a_matching_version(self):
        event, parent, digest, build_id = self.fixture()
        for row in event['observations']:
            row['artifact_sha256'] = None
        with self.assertRaises(AssertionError):
            validate_event(event, parent, None, build_id)
        event, parent, digest, build_id = self.fixture()
        for row in event['observations']:
            row['build_id'] = None
        with self.assertRaises(AssertionError):
            validate_event(event, parent, digest, None)


if __name__ == '__main__':
    unittest.main()
