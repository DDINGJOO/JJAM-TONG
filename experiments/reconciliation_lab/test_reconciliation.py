import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .adapters import GitHub, LocalGit, settings
from .fixtures import Repository
from .receiver import MAX_BODY, FIXTURE_KEY, accept, server, signed
from .reconcile import IntakeRejected, Store, work


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root / "source")
        self.config = settings()
        self.database = self.root / "work.sqlite"
        self.source = LocalGit(self.repo.path, "fixture/community", config=self.config)
        self.store = Store(self.database, self.source.source, self.config)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)

    def body(self, after="deliberately-untrusted", ref="refs/heads/main", repository="fixture/community"):
        return json.dumps({"repository": {"full_name": repository}, "ref": ref, "after": after}).encode()

    def accept(self, delivery="delivery", body=None):
        body = self.body() if body is None else body
        return accept(self.store, body, signed(body, delivery), "fixture/community", "refs/heads/main", FIXTURE_KEY)

    def check_current(self, revision):
        current = self.store.current()
        self.assertEqual(current["revision"], revision)
        self.assertEqual(current["files"], self.repo.expected[revision])
        self.assertGreater(len(current["files"]), 0)

    def bootstrap(self):
        self.assertTrue(self.store.schedule(0, 5))
        self.assertEqual(work(self.store, self.source, 0)["status"], "published")
        self.check_current(self.repo.initial)

    def test_H01_H02_bootstrap_and_skip_unchanged_analysis(self):
        self.bootstrap()
        self.assertFalse(self.store.schedule(4, 5))
        self.assertTrue(self.store.schedule(5, 5))
        result = work(self.store, self.source, 5)
        self.assertEqual(result["index_builds"], 0)
        self.assertEqual(self.source.calls, {"checks": 2, "trees": 1})
        self.assertEqual(self.store.counts()["snapshots"], 1)
        self.assertEqual(self.store.state()["checked_at"], 5)

    def test_H03_H05_payload_is_hint_duplicate_and_old_notification(self):
        self.bootstrap()
        latest = self.repo.commit({"services/posts/PostService.java": "class PostService { void create() {} }\n"})
        self.assertEqual(self.accept("new", self.body(self.repo.initial)), "accepted")
        self.assertEqual(self.accept("new", self.body(self.repo.initial)), "duplicate")
        self.assertEqual(work(self.store, self.source, 1)["status"], "published")
        self.check_current(latest)
        self.accept("late", self.body(self.repo.initial))
        work(self.store, self.source, 2)
        self.check_current(latest)
        with self.assertRaises(IntakeRejected) as error:
            self.accept("new", self.body("conflicting-body"))
        self.assertEqual(error.exception.status, 409)

    def test_H04_H06_lost_event_rename_delete_and_history(self):
        self.bootstrap()
        renamed = self.repo.commit({"services/comments/ReplyService.java": "class ReplyService {}\n"},
                                   ("services/comments/CommentService.java",))
        self.assertFalse(self.store.schedule(4, 5))
        self.check_current(self.repo.initial)
        self.store.schedule(5, 5)
        result = work(self.store, self.source, 5)
        self.assertEqual(result["path_delta"], {"added": ["services/comments/ReplyService.java"],
                                             "removed": ["services/comments/CommentService.java"], "changed": []})
        self.check_current(renamed)
        self.assertNotIn("services/comments/CommentService.java", self.store.current()["files"])
        self.assertEqual(self.store.counts()["snapshots"], 2)
        older = [json.loads(r[0]) for r in self.store.db.execute("SELECT body FROM snapshots")
                 if json.loads(r[0])["revision"] == self.repo.initial]
        self.assertEqual(older[0]["files"], self.repo.expected[self.repo.initial])

    def test_H07_actual_git_unavailability_preserves_success_and_recovers(self):
        self.bootstrap()
        self.store.request()
        self.repo.path.rename(self.root / "offline")
        self.assertEqual(work(self.store, self.source, 1)["status"], "failed")
        self.assertEqual(self.store.state()["checked_at"], 0)
        self.assertEqual(work(self.store, self.source, 5)["status"], "idle")
        (self.root / "offline").rename(self.repo.path)
        self.assertEqual(work(self.store, self.source, 6)["status"], "published")
        self.assertIsNone(self.store.state()["error"])

    def test_H08_real_process_exit_and_transaction_recovery(self):
        for point in ("after_claim", "during_publish"):
            with self.subTest(point=point):
                database = self.root / (point + ".sqlite")
                with_store = Store(database, self.source.source, self.config)
                try:
                    with_store.request("received", "synthetic-digest")
                    result = subprocess.run([sys.executable, "-m", "experiments.reconciliation_lab.worker",
                                             "--database", str(database), "--git", str(self.repo.path),
                                             "--now", "0", "--crash", point], capture_output=True, timeout=20)
                    self.assertEqual(result.returncode, 17, result.stderr)
                    self.assertIsNone(with_store.current())
                    self.assertEqual(with_store.counts()["snapshots"], 0)
                    self.assertEqual(with_store.state()["completed"], 0)
                    self.assertEqual(work(with_store, self.source, 29)["status"], "idle")
                    self.assertEqual(work(with_store, self.source, 31)["status"], "published")
                    self.assertEqual(with_store.current()["files"], self.repo.expected[self.repo.initial])
                    self.assertEqual(with_store.db.execute("SELECT done FROM receipts").fetchone()[0], 1)
                finally:
                    with_store.close()

    def test_H09_two_workers_lease_fencing_and_arrivals_during_work(self):
        other = Store(self.database, self.source.source, self.config)
        self.addCleanup(other.close)
        self.store.request()
        first = self.store.claim(0)
        self.assertIsNone(other.claim(1))
        old, _ = self.source.read()
        newest = self.repo.commit({"services/posts/PostRepository.java": "class PostRepository {}\n"})
        self.store.request("during-work", "digest")
        second = other.claim(31)
        updated, _ = self.source.read()
        self.assertTrue(other.publish(second, updated, None, 32))
        self.assertFalse(self.store.publish(first, old, None, 33))
        self.check_current(newest)
        self.assertEqual(self.store.state()["completed"], 2)

    def test_H09_new_request_does_not_disappear_at_publication(self):
        self.store.request()
        claim = self.store.claim(0)
        snapshot, _ = self.source.read()
        self.store.request("while-reading", "digest")
        self.assertTrue(self.store.publish(claim, snapshot, None, 1))
        self.assertEqual(self.store.state()["completed"], 1)
        self.assertEqual(self.store.state()["requested"], 2)
        self.assertEqual(work(self.store, self.source, 2)["status"], "published")
        self.assertEqual(self.store.state()["completed"], 2)

    def test_H10_revoke_prevents_pending_and_inflight_publication(self):
        self.bootstrap()
        self.accept()
        claim = self.store.claim(1)
        self.repo.commit({"services/posts/Secret.java": "class Secret {}\n"})
        snapshot, _ = self.source.read()
        self.store.revoke()
        self.assertFalse(self.store.publish(claim, snapshot, None, 2))
        self.assertIsNone(self.store.claim(32))
        self.assertFalse(self.store.schedule(40, 5))
        with self.assertRaises(IntakeRejected):
            self.accept("another")
        self.check_current(self.repo.initial)

    def test_H11_coalescing_capacity_and_successful_receipts(self):
        self.store.capacity = 3
        for i in range(3):
            self.accept(str(i))
        self.assertEqual(self.accept("0"), "duplicate")
        with self.assertRaises(IntakeRejected) as error:
            self.accept("overflow")
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(self.store.state()["requested"], 3)
        result = work(self.store, self.source, 0)
        self.assertEqual(result["calls"]["checks"], 1)
        self.assertEqual(self.store.db.execute("SELECT SUM(done) FROM receipts").fetchone()[0], 3)
        self.assertEqual(self.accept("after-drain"), "accepted")

    def test_H12_untrusted_inputs_do_not_schedule_work(self):
        body = self.body()
        with self.assertRaises(IntakeRejected):
            accept(self.store, body, {}, "fixture/community", "refs/heads/main", FIXTURE_KEY)
        with self.assertRaises(IntakeRejected):
            accept(self.store, body, {"X-Hub-Signature-256": "한글"}, "fixture/community", "refs/heads/main", FIXTURE_KEY)
        self.assertEqual(self.accept(body=self.body(ref="refs/heads/other")), "ignored_target")
        self.assertEqual(self.accept(body=self.body(repository="other/repo")), "ignored_target")
        with self.assertRaises(IntakeRejected):
            self.accept(body=b"x" * (MAX_BODY + 1))
        self.assertEqual(self.store.state()["requested"], 0)
        self.assertEqual(self.store.counts()["receipts"], 0)

    def test_H13_rollback_and_analysis_configuration_are_versioned(self):
        self.bootstrap()
        self.repo.commit({"services/posts/PostRepository.java": "class PostRepository {}\n"})
        self.store.request()
        work(self.store, self.source, 1)
        self.repo.git("update-ref", "refs/heads/main", self.repo.initial)
        self.store.request()
        work(self.store, self.source, 2)
        self.check_current(self.repo.initial)
        self.assertEqual(self.store.counts(), {"receipts": 0, "snapshots": 2, "observations": 3})
        changed = settings(("services/posts/",), analyzer="git-file-index/2-experiment")
        self.store.reconfigure(changed)
        other = Store(self.database, self.source.source, changed)
        self.addCleanup(other.close)
        other.request()
        result = work(other, LocalGit(self.repo.path, "fixture/community", config=changed), 3)
        self.assertEqual(result["index_builds"], 1)
        self.assertEqual(other.counts()["snapshots"], 3)
        self.assertEqual(set(other.current()["files"]), {"services/posts/PostController.java", "services/posts/PostService.java"})

    def test_source_namespace_and_inconsistent_immutable_snapshot_rejected(self):
        self.bootstrap()
        with self.assertRaises(ValueError):
            Store(self.database, "other/source", self.config)
        self.store.request()
        claim = self.store.claim(1)
        snapshot = self.store.current()
        snapshot["files"]["services/posts/PostController.java"] = "f" * 40
        with self.assertRaises(ValueError):
            self.store.publish(claim, snapshot, None, 1)
        self.check_current(self.repo.initial)

    def test_loopback_http_ack_is_durable_and_recovers_in_worker(self):
        receiver = server(lambda: Store(self.database, self.source.source, self.config, capacity=1), "fixture/community")
        thread = threading.Thread(target=receiver.serve_forever, daemon=True)
        thread.start()
        try:
            body = self.body()
            request = urllib.request.Request("http://127.0.0.1:%d/webhook" % receiver.server_port,
                                             data=body, headers=signed(body, "over-http"))
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 202)
            overflow = urllib.request.Request("http://127.0.0.1:%d/webhook" % receiver.server_port,
                                              data=body, headers=signed(body, "overflow"))
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(overflow, timeout=5)
            self.assertEqual(error.exception.code, 503)
            self.assertEqual(self.store.counts()["receipts"], 1)
            self.assertIsNone(self.store.current())
            self.assertEqual(work(self.store, self.source, 0)["status"], "published")
            self.check_current(self.repo.initial)
        finally:
            receiver.shutdown()
            receiver.server_close()
            thread.join(timeout=5)

    def test_H09_real_concurrent_worker_processes_claim_once(self):
        self.accept("race")
        command = [sys.executable, "-m", "experiments.reconciliation_lab.worker", "--database", str(self.database),
                   "--git", str(self.repo.path), "--now", "0"]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(2)]
        results = []
        for child in children:
            out, err = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, err)
            results.append(json.loads(out))
        self.assertEqual(sorted(r["status"] for r in results), ["idle", "published"])
        self.check_current(self.repo.initial)
        self.assertEqual(self.store.counts()["snapshots"], 1)

    def test_H09_intake_is_available_while_source_read_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        parent = self

        class Blocked(LocalGit):
            def read(self, previous=None):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test source gate timed out")
                return super().read(previous)

        def worker():
            connection = Store(parent.database, parent.source.source, parent.config)
            try:
                work(connection, Blocked(parent.repo.path, "fixture/community"), 0)
            except BaseException as error:
                failures.append(error)
            finally:
                connection.close()

        self.store.request()
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.accept("while-blocked"), "accepted")
        finally:
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertLess(self.store.state()["completed"], self.store.state()["requested"])

    def test_H13_reconfiguration_fences_running_old_analyzer(self):
        self.store.request()
        claim = self.store.claim(0)
        snapshot, _ = self.source.read()
        self.store.reconfigure(settings(("services/posts/",)))
        self.assertFalse(self.store.publish(claim, snapshot, None, 1))
        with self.assertRaises(ValueError):
            Store(self.database, self.source.source, self.config)

    def test_H14_github_conditional_reads_partial_tree_and_retry_after(self):
        responses = {"revision": "a" * 40, "tree": "b" * 40, "truncated": False, "status": 200}
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                seen.append(dict(handler.headers))
                if responses["status"] != 200:
                    handler.send_response(responses["status"])
                    handler.send_header("Retry-After", "120")
                    handler.end_headers()
                    return
                etag = '"' + responses["revision"] + '"'
                if "/commits/" in handler.path and handler.headers.get("If-None-Match") == etag:
                    handler.send_response(304)
                    handler.end_headers()
                    return
                if "/commits/" in handler.path:
                    body = {"sha": responses["revision"], "commit": {"tree": {"sha": responses["tree"]},
                            "committer": {"date": "2026-11-12T00:00:00Z"}}}
                else:
                    body = {"sha": responses["tree"], "truncated": responses["truncated"],
                            "tree": [{"path": "services/posts/PostService.java", "sha": "c" * 40,
                                      "type": "blob", "mode": "100644"}]}
                raw = json.dumps(body).encode()
                handler.send_response(200)
                handler.send_header("ETag", etag)
                handler.send_header("Content-Length", str(len(raw)))
                handler.end_headers()
                handler.wfile.write(raw)

            def log_message(handler, *args):
                pass

        api = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        source = GitHub("fixture/community", origin="http://127.0.0.1:%d" % api.server_port)
        store = Store(self.root / "github.sqlite", source.source, self.config)
        try:
            store.request()
            self.assertEqual(work(store, source, 0)["status"], "published")
            store.request()
            self.assertEqual(work(store, source, 1)["index_builds"], 0)
            self.assertEqual(source.calls["not_modified"], 1)
            responses.update(revision="d" * 40, truncated=True)
            store.request()
            self.assertEqual(work(store, source, 2)["error"], "incomplete_tree")
            self.assertEqual(store.current()["revision"], "a" * 40)
            self.assertEqual(store.state()["checked_at"], 1)
            self.assertEqual(json.loads(store.state()["cache"])["etag"], '"' + "a" * 40 + '"')
            responses["truncated"] = False
            self.assertEqual(work(store, source, 7)["status"], "published")
            self.assertEqual(store.current()["revision"], "d" * 40)
            responses["status"] = 429
            store.request()
            self.assertEqual(work(store, source, 8)["retry_after"], 120)
            self.assertEqual(work(store, source, 127)["status"], "idle")
            self.assertEqual(store.state()["checked_at"], 7)
            self.assertEqual(seen[0]["X-Github-Api-Version"], "2026-03-10")
        finally:
            store.close()
            api.shutdown()
            api.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
