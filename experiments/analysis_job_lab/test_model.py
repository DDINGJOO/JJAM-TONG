import unittest
from tempfile import TemporaryDirectory

from experiments.analysis_job_lab.model import AnalysisInput, Budget, InputPart, Job, Status, VerifiedCompletion


SHA = "a" * 64
REQUIRED = ("source", "artifact", "dependencies", "generated", "configuration", "toolchain")


def input_for(**changes):
    values = dict(
        tenant="team-a", repository="repo", revision="revision", build="build-1", module="core",
        analyzer="parser", analyzer_version="1", result_schema="result.v1",
        parts=tuple(InputPart(kind, "present", SHA) for kind in REQUIRED),
    )
    values.update(changes)
    return AnalysisInput(**values)


def manifest(job):
    from .publication import publish_bundle, verify_bundle
    with TemporaryDirectory() as directory:
        publish_bundle(directory, job.input_key, job.attempt, job.expected_stages,
                       dict.fromkeys(job.expected_stages, ()))
        return verify_bundle(directory, job.input_key, job.attempt, job.expected_stages)


class AnalysisInputTests(unittest.TestCase):
    def test_identity_includes_every_dimension_and_is_order_independent(self):
        original = input_for()
        reordered = input_for(parts=tuple(reversed(original.parts)))
        self.assertEqual(original.key(), reordered.key())
        for field in ("tenant", "repository", "revision", "build", "module", "analyzer", "analyzer_version", "result_schema"):
            with self.subTest(field=field):
                self.assertNotEqual(original.key(), input_for(**{field: "different"}).key())
        for i, part in enumerate(original.parts):
            changed_part = list(original.parts)
            changed_part[i] = InputPart(part.kind, "present", "b" * 64)
            self.assertNotEqual(original.key(), input_for(parts=tuple(changed_part)).key())
        self.assertEqual(original.as_dict()["contractSchema"], "jjamtong.analysis-job-input.v1")

    def test_unavailable_is_not_not_applicable_or_an_empty_digest(self):
        unavailable = input_for(parts=(InputPart("source", "unavailable"),) + input_for().parts[1:])
        not_applicable = input_for(parts=(InputPart("source", "not-applicable"),) + input_for().parts[1:])
        self.assertNotEqual(unavailable.key(), not_applicable.key())
        with self.assertRaises(ValueError):
            InputPart("source", "unavailable", "")

    def test_parts_and_budgets_reject_malformed_values(self):
        with self.assertRaises(ValueError):
            InputPart("Bad kind", "present", SHA)
        with self.assertRaises(ValueError):
            InputPart("source", "present")
        with self.assertRaises(ValueError):
            input_for(parts=input_for().parts[:-1])
        with self.assertRaises(ValueError):
            input_for(parts=input_for().parts + (InputPart("source", "present", SHA),))
        for kwargs in ({"max_total_bytes": True}, {"max_record_bytes": 3, "max_chunk_bytes": 2}, {"max_manifest_bytes": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Budget(**kwargs)
        with self.assertRaises(ValueError):
            Budget(max_file_bytes=1)
        with self.assertRaises(ValueError):
            input_for(repository="   ")
        with self.assertRaises(ValueError):
            InputPart("source", [])


class JobTests(unittest.TestCase):
    def new_job(self):
        return Job(SHA, "attempt-1", ("scan", "publish"))

    def test_partial_is_not_complete_and_finish_requires_matching_manifest(self):
        job = self.new_job()
        job.start()
        job.stage_complete("scan")
        job.stage_complete("scan")
        self.assertEqual(job.status, Status.PARTIAL)
        with self.assertRaises(ValueError):
            job.finish(manifest(job))
        job.stage_complete("publish")
        for other in (Job("b" * 64, "attempt-1", job.expected_stages),
                      Job(SHA, "attempt-2", job.expected_stages), Job(SHA, "attempt-1", ("scan",))):
            with self.assertRaises(ValueError):
                job.finish(manifest(other))
        raw = {"schema": "jjamtong.analysis-bundle.v1", "inputKey": job.input_key, "attempt": job.attempt,
               "expectedStages": list(job.expected_stages), "complete": True}
        with self.assertRaises(ValueError):
            job.finish(raw)
        with self.assertRaises(TypeError):
            VerifiedCompletion()
        job.finish(manifest(job))
        self.assertEqual(job.status, Status.COMPLETE)

    def test_terminal_mutations_are_rejected_and_cancel_blocks_finish(self):
        job = self.new_job()
        job.terminate(Status.CANCELLED, "operator cancelled")
        for action in (lambda: job.start(), lambda: job.stage_complete("scan"), lambda: job.finish(manifest(job)),
                       lambda: job.terminate(Status.FAILED, "late")):
            with self.assertRaises(ValueError):
                action()

    def test_retry_keeps_history_and_unsupported_is_not_retryable(self):
        job = self.new_job()
        job.terminate(Status.FAILED, "failed")
        replacement = job.retry("attempt-2")
        self.assertEqual(replacement.status, Status.QUEUED)
        self.assertEqual(replacement.previous_attempt, "attempt-1")
        self.assertEqual(job.status, Status.FAILED)
        self.assertEqual(job.reason, "failed")
        self.assertIsNone(replacement.reason)
        with self.assertRaises(ValueError):
            job.retry("attempt-1")
        unsupported = self.new_job()
        unsupported.terminate(Status.UNSUPPORTED, "capability unavailable")
        with self.assertRaises(ValueError):
            unsupported.retry("attempt-2")

    def test_job_validation_and_queued_preflight_termination(self):
        with self.assertRaises(ValueError):
            Job("BAD", "attempt-1", ("scan",))
        with self.assertRaises(ValueError):
            Job(SHA, "Attempt", ("scan",))
        with self.assertRaises(ValueError):
            Job(SHA, "attempt-1", ("scan", "scan"))
        job = self.new_job()
        job.terminate(Status.RESOURCE_EXCEEDED, "preflight budget")
        self.assertEqual(job.status, Status.RESOURCE_EXCEEDED)


if __name__ == "__main__":
    unittest.main()
