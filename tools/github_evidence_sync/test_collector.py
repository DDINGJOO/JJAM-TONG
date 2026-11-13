"""Offline adversarial checks for the GitHub pull boundary."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

from tools.github_evidence_sync.collector import Collector, GitHubTransport, ImportError, SourceConfig
from tools.github_evidence_sync.contract import CONTRACT
from tools.method_evidence.evidence import digest


REPOSITORY = "owner/repository"
REPOSITORY_ID = 1234
RUN_ID = 987
ATTEMPT = 2
SHA = "a" * 40


def rehash(index):
    index["indexSha256"] = digest({key: value for key, value in index.items() if key != "indexSha256"})
    return index


def index():
    method = {"module": "method-fixture", "class": "fixture.Main", "name": "run", "descriptor": "()V"}
    tool = {"version": "test", "methods": [method], "calls": [], "unresolved": [], "excluded": []}
    config = {"schema": "jjamtong.methods.v1", "adapter": "test", "tools": {}}
    return rehash({"schema": "jjamtong.method-index.v1", "analysisRunId": "gh-1234-987-2",
                   "buildIdentity": {"repository": "https://github.com/owner/repository", "revision": SHA,
                                     "build": "gh-987-2", "module": "method-fixture", "artifactSha256": "b" * 64},
                   "config": config, "configSha256": digest(config), "methods": [method],
                   "input": {key: "c" * 64 for key in ("artifactSha256", "classInputSha256", "metadataInputSha256", "sourceTreeSha256")},
                   "provenance": {"adapterVersion": "test"}, "staticEvidence": {"javaparser": copy.deepcopy(tool), "wala": copy.deepcopy(tool)},
                   "limitations": ["test"], "identityAssurance": "test"})


def contract():
    """Tests use the collector's committed production agreement."""
    return CONTRACT


def bundle(value=None, extra=None):
    value = index() if value is None else value
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    manifest = {"schema": contract()["schema"], "repository": REPOSITORY, "repositoryId": REPOSITORY_ID, "revision": SHA,
                "workflow": ".github/workflows/ci.yml", "runId": str(RUN_ID), "runAttempt": str(ATTEMPT),
                "analysisRunId": "gh-1234-987-2", "indexSha256": value["indexSha256"],
                "indexFileSha256": hashlib.sha256(raw).hexdigest()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("index.json", raw)
        if extra:
            archive.writestr(extra, b"x")
    return output.getvalue()


class FakeTransport:
    def __init__(self, archive=None):
        self.archive = bundle() if archive is None else archive
        self.paths = []
        self.run = {"id": RUN_ID, "run_attempt": ATTEMPT, "head_sha": SHA, "conclusion": "success", "status": "completed",
                    "event": "push", "head_branch": "main", "workflow_id": 55,
                    "repository": {"id": REPOSITORY_ID}, "head_repository": {"id": REPOSITORY_ID}}

    def json(self, path):
        self.paths.append(path)
        if path == "/repos/" + REPOSITORY:
            return {"id": REPOSITORY_ID, "full_name": REPOSITORY}
        if "/actions/workflows/55" in path:
            return {"id": 55, "path": ".github/workflows/ci.yml"}
        if "/artifacts?name=" in path:
            return {"total_count": 1, "artifacts": [{"id": 12, "name": "jjamtong-method-index-987-2", "expired": False,
                                    "size_in_bytes": len(self.archive),
                                    "archive_download_url": "https://api.github.com/repos/owner/repository/actions/artifacts/12/zip", "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
                                    "workflow_run": {"id": RUN_ID, "repository_id": REPOSITORY_ID,
                                                     "head_repository_id": REPOSITORY_ID, "head_branch": "main", "head_sha": SHA}}]}
        if "/actions/runs/987" in path:
            return self.run
        if "/runs?" in path:
            return {"workflow_runs": [self.run]}
        raise AssertionError(path)

    def bytes(self, url):
        self.downloaded = url
        return self.archive


class FakeStore:
    def __init__(self): self.values = {}
    def publish(self, tenant, value):
        key = (tenant, value["analysisRunId"])
        previous = self.values.get(key)
        if previous is None:
            self.values[key] = value["indexSha256"]
            return True
        if previous != value["indexSha256"]:
            raise AssertionError("conflict")
        return False


class Response:
    def __init__(self, code, body=b"", location=None):
        self.code, self.body = code, body
        self.headers = {} if location is None else {"Location": location}
    def getcode(self): return self.code
    def read(self, size=-1): return self.body
    def close(self): pass


class Opener:
    def __init__(self): self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        if len(self.requests) == 1:
            return Response(302, location="https://signed.example/archive")
        return Response(200, b"archive")


class CollectorTests(unittest.TestCase):
    def collector(self, transport=None, store=None):
        return Collector(SourceConfig(REPOSITORY, ".github/workflows/ci.yml", "main", "team-a"), transport or FakeTransport(), store or FakeStore(), contract())

    def test_publish_then_replay_and_tenant_is_not_bundle_field(self):
        transport, store = FakeTransport(), FakeStore()
        first = self.collector(transport, store).collect(str(RUN_ID))[0]
        second = self.collector(transport, store).collect(str(RUN_ID))[0]
        self.assertEqual("created", first.status)
        self.assertEqual("replay", second.status)
        self.assertEqual("team-a", first.tenant)
        self.assertEqual((SHA, "gh-987-2", "gh-1234-987-2"),
                         (first.revision, first.build, first.analysis_run_id))
        self.assertEqual(".github/workflows/ci.yml", SourceConfig(REPOSITORY, "ci.yml", "main", "team-a").workflow)

    def test_wrong_revision_and_attempt_are_rejected_before_publish(self):
        transport, store = FakeTransport(), FakeStore()
        transport.run["head_sha"] = "d" * 40
        with self.assertRaises(ImportError):
            self.collector(transport, store).collect(str(RUN_ID))
        self.assertEqual({}, store.values)
        transport = FakeTransport()
        transport.run["run_attempt"] = 3
        with self.assertRaises(ImportError):
            self.collector(transport, store).collect(str(RUN_ID))

    def test_failed_pr_fork_and_workflow_are_rejected(self):
        for field, value in (("conclusion", "failure"), ("event", "pull_request"), ("head_repository", {"id": 9}), ("head_branch", "other")):
            transport = FakeTransport()
            transport.run[field] = value
            with self.subTest(field=field), self.assertRaises(ImportError):
                self.collector(transport).collect(str(RUN_ID))
        transport = FakeTransport()
        original = transport.json
        transport.json = lambda path: {"id": 55, "path": ".github/workflows/other.yml"} if "/workflows/55" in path else original(path)
        with self.assertRaisesRegex(ImportError, "WORKFLOW_MISMATCH"):
            self.collector(transport).collect(str(RUN_ID))

    def test_digest_zip_extra_duplicate_and_budget_tampering_fail_before_publish(self):
        duplicate = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "w") as archive:
                archive.writestr("manifest.json", b"{}")
                archive.writestr("manifest.json", b"{}")
                archive.writestr("index.json", b"{}")
        cases = [(bundle(extra="../escape"), "INVALID_ARCHIVE_CONTENTS"), (duplicate.getvalue(), "INVALID_ARCHIVE_CONTENTS"),
                 (b"not a zip", "INVALID_ARCHIVE"), (b"x" * (12 * 1024 * 1024 + 1), "ARTIFACT_METADATA_INCOMPLETE")]
        for archive, reason in cases:
            transport, store = FakeTransport(archive), FakeStore()
            with self.subTest(reason=reason), self.assertRaisesRegex(ImportError, reason):
                self.collector(transport, store).collect(str(RUN_ID))
            self.assertEqual({}, store.values)
        transport, store = FakeTransport(), FakeStore()
        original = transport.json
        def mismatched(path):
            result = original(path)
            if "/artifacts?name=" in path:
                result["artifacts"][0]["digest"] = "sha256:" + "0" * 64
            return result
        transport.json = mismatched
        with self.assertRaisesRegex(ImportError, "ARCHIVE_DIGEST_MISMATCH"):
            self.collector(transport, store).collect(str(RUN_ID))

    def test_duplicate_json_keys_are_rejected(self):
        raw_index = json.dumps(index(), sort_keys=True, separators=(",", ":")).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", b'{"schema":"a","schema":"b"}')
            archive.writestr("index.json", raw_index)
        with self.assertRaisesRegex(ImportError, "DUPLICATE_JSON_KEY"):
            self.collector(FakeTransport(output.getvalue())).collect(str(RUN_ID))

    def test_signed_download_redirect_strips_authorization_and_requires_https(self):
        transport, opener = GitHubTransport("test-token"), Opener()
        transport._opener = opener
        self.assertEqual(b"archive", transport.bytes("https://api.github.com/repos/x/actions/artifacts/1/zip"))
        self.assertEqual("Bearer test-token", opener.requests[0].get_header("Authorization"))
        self.assertIsNone(opener.requests[1].get_header("Authorization"))
        with self.assertRaisesRegex(ImportError, "HTTPS_REQUIRED"):
            transport.bytes("http://api.github.com/not-allowed")

    def test_changed_index_body_is_rejected_before_publish(self):
        changed = index()
        changed["buildIdentity"]["revision"] = "d" * 40
        rehash(changed)
        transport, store = FakeTransport(bundle(changed)), FakeStore()
        with self.assertRaisesRegex(ImportError, "BUILD_IDENTITY_MISMATCH"):
            self.collector(transport, store).collect(str(RUN_ID))
        self.assertEqual({}, store.values)

    def test_expired_named_artifact_is_unavailable(self):
        transport = FakeTransport()
        original = transport.json
        def expired(path):
            result = original(path)
            if "/artifacts?name=" in path:
                result["artifacts"][0]["expired"] = True
            return result
        transport.json = expired
        with self.assertRaisesRegex(ImportError, "UNAVAILABLE"):
            self.collector(transport).collect(str(RUN_ID))

    def test_polling_uses_filename_and_allowed_api_filters(self):
        transport = FakeTransport()
        self.collector(transport).collect()
        polls = [path for path in transport.paths if "/actions/workflows/ci.yml/runs?" in path]
        self.assertEqual(2, len(polls))
        self.assertTrue(all("branch=main" in path and "status=success" in path and "per_page=100" in path for path in polls))
        self.assertEqual({"push", "workflow_dispatch"}, {path.split("event=")[1].split("&")[0] for path in polls})
        self.assertTrue(any("/artifacts?name=jjamtong-method-index-987-2&per_page=100&page=1" in path for path in transport.paths))

    def test_post_download_artifact_change_rejects_before_publish(self):
        class ChangedAfterDownload(FakeTransport):
            def __init__(self):
                super().__init__()
                self.changed = False

            def bytes(self, url):
                self.changed = True
                return super().bytes(url)

            def json(self, path):
                value = super().json(path)
                if self.changed and "/artifacts?name=" in path:
                    value["artifacts"][0]["digest"] = "sha256:" + "0" * 64
                return value

        transport, store = ChangedAfterDownload(), FakeStore()
        with self.assertRaisesRegex(ImportError, "ARTIFACT_METADATA_CHANGED"):
            self.collector(transport, store).collect(str(RUN_ID))
        self.assertEqual({}, store.values)

    def test_watch_style_poll_skips_bad_run_and_publishes_later_good_run(self):
        class Mixed(FakeTransport):
            def __init__(self):
                super().__init__()
                self.bad = dict(self.run, id=988, conclusion="failure")

            def json(self, path):
                if path.endswith("/actions/runs/988"):
                    self.paths.append(path)
                    return self.bad
                value = super().json(path)
                if "/runs?" in path and "event=push" in path:
                    return {"workflow_runs": [self.bad, self.run]}
                if "/runs?" in path and "event=workflow_dispatch" in path:
                    return {"workflow_runs": []}
                return value

        transport, store, errors = Mixed(), FakeStore(), []
        receipts = self.collector(transport, store).collect(continue_on_error=True, on_error=lambda exc: errors.append(str(exc)))
        self.assertEqual([str(RUN_ID)], [receipt.run_id for receipt in receipts])
        self.assertEqual(["RUN_NOT_ALLOWED"], errors)

    def test_invalid_inputs_and_malformed_manifest_never_publish(self):
        for repository, workflow in (("../repo", "ci.yml"), ("owner/repo", ".github/workflows/../ci.yml")):
            with self.subTest(repository=repository, workflow=workflow), self.assertRaises(ValueError):
                SourceConfig(repository, workflow, "main", "team-a")
        malformed = io.BytesIO()
        with zipfile.ZipFile(malformed, "w") as archive:
            archive.writestr("manifest.json", b"[]")
            archive.writestr("index.json", b"[]")
        store = FakeStore()
        with self.assertRaisesRegex(ImportError, "MANIFEST_FIELDS_MISMATCH"):
            self.collector(FakeTransport(malformed.getvalue()), store).collect(str(RUN_ID))
        self.assertEqual({}, store.values)

    def test_cli_uses_committed_contract_without_local_state(self):
        root = str(Path(__file__).resolve().parents[2])
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, PYTHONPATH=root)
            result = subprocess.run([sys.executable, "-m", "tools.github_evidence_sync", "--help"], cwd=directory,
                                    env=environment, text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(".local/github-sync/contract.json", Path(__file__).with_name("__main__.py").read_text())


if __name__ == "__main__":
    unittest.main()
