"""Cross-producer and bounded-history regressions for the import boundary."""
import copy
import io
import unittest
import zipfile

from tools.github_evidence_publish import GitHubContext, bundle
from .collector import Collector, GitHubTransport, ImportError, SourceConfig
from .contract import CONTRACT
from .test_collector import (ATTEMPT, REPOSITORY, REPOSITORY_ID, RUN_ID, SHA,
                             FakeStore, FakeTransport, index)


class IntegrationContractTests(unittest.TestCase):
    def collector(self, transport, store=None, pages=3):
        return Collector(SourceConfig(REPOSITORY, "ci.yml", "main", "test-team", pages),
                         transport, store or FakeStore(), CONTRACT)

    def test_real_producer_bundle_is_accepted_by_committed_consumer_contract(self):
        context = GitHubContext(REPOSITORY, str(REPOSITORY_ID), SHA, str(RUN_ID), str(ATTEMPT))
        files = bundle(context, index())
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            for name, raw in files.items():
                output.writestr(name, raw)
        store = FakeStore()
        collector = self.collector(FakeTransport(archive.getvalue()), store)
        first = collector.collect(str(RUN_ID))[0]
        self.assertEqual(context.analysis_run_id, first.analysis_run_id)
        self.assertEqual("created", first.status)
        self.assertEqual("replay", collector.collect(str(RUN_ID))[0].status)

    def test_full_configured_history_window_still_returns_recent_runs(self):
        class FullPage(FakeTransport):
            def json(self, path):
                if "/runs?" in path:
                    self.paths.append(path)
                    runs = [dict(self.run, id=i) for i in range(1, 101)] if "event=push" in path else []
                    return {"total_count": 10000, "workflow_runs": runs}
                return super().json(path)

        transport = FullPage()
        runs = self.collector(transport, pages=1)._runs()
        self.assertEqual(100, len(runs))
        self.assertEqual(2, len(transport.paths))
        self.assertTrue(all("page=1" in path for path in transport.paths))

    def test_rerun_starting_after_download_cannot_publish_old_attempt(self):
        class Rerun(FakeTransport):
            changed = False

            def json(self, path):
                value = copy.deepcopy(super().json(path))
                if path.endswith("/actions/runs/987") and self.changed:
                    value["run_attempt"] += 1
                return value

            def bytes(self, url):
                self.changed = True
                return super().bytes(url)

        store = FakeStore()
        with self.assertRaisesRegex(ImportError, "RUN_METADATA_CHANGED"):
            self.collector(Rerun(), store).collect(str(RUN_ID))
        self.assertEqual({}, store.values)

    def test_malformed_url_port_cannot_echo_payload_or_publish(self):
        marker = "private-payload-marker"
        transport, store = FakeTransport(), FakeStore()
        original = transport.json

        def malformed(path):
            value = original(path)
            if "/artifacts?name=" in path:
                value["artifacts"][0]["archive_download_url"] = "https://api.github.com:" + marker + "/archive"
            return value

        transport.json = malformed
        with self.assertRaisesRegex(ImportError, "^ARTIFACT_METADATA_INCOMPLETE$"):
            self.collector(transport, store).collect(str(RUN_ID))
        self.assertEqual({}, store.values)
        with self.assertRaisesRegex(ImportError, "^INVALID_URL$"):
            GitHubTransport("unused-test-token").bytes("https://api.github.com:" + marker + "/archive")


if __name__ == "__main__":
    unittest.main()
