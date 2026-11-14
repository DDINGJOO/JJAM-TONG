import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from .reuse import AnalysisRequest, execute, _file_digest, _source_digest, _load_cache, MAX_BYTES


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.sources = self.root / "src"; self.sources.mkdir()
        self.java = self.sources / "Board.java"; self.java.write_text("class Board {}\n")
        self.artifact = self.root / "board.jar"; self.artifact.write_bytes(b"artifact-one")
        self.metadata = self.root / "manifest.json"; self.cache = self.root / "cache"
        self.write_manifest("build-one")
        self.request = AnalysisRequest("tenant-a", self.sources, self.artifact, self.metadata, "board", self.root / "jdk")
        self.calls = 0

    def write_manifest(self, build):
        self.metadata.write_text(json.dumps({"repository": "local:board", "revision": "rev", "build": build, "module": "board",
            "artifactSha256": _file_digest(self.artifact), "sourceState": "clean",
            "sourceFiles": [{"path": "Board.java", "sha256": _file_digest(self.java)}]}))

    def fake_analyzer(self, request, output):
        self.calls += 1
        source = _source_digest({"Board.java": _file_digest(self.java)})
        output.write_text(json.dumps({"schema": "jjamtong.methods.v1", "module": "board", "metadata": {"stale": "metadata"},
            "status": "complete-with-limitations",
            "input": {"artifactSha256": _file_digest(self.artifact), "sourceTreeSha256": source, "metadataInputSha256": "old"},
            "scope": {"includePackage": request.include_package, "excludedPackages": sorted(request.exclude_packages)},
            "provenance": {"adapterVersion": "test"}, "tools": {
                name: {"version": "test", "methods": [{"name": "fake"}], "calls": [{"kind": "fake"}], "unresolved": [], "excluded": []}
                for name in ("javaparser", "wala")}, "limitations": ["static"]}))

    def execute(self, request=None, name="out.json"):
        with patch("tools.analysis_reuse.reuse._tool_fingerprints", return_value={"runner": "a"}), patch("tools.analysis_reuse.reuse._run_analyzer", self.fake_analyzer):
            return execute(request or self.request, self.cache, self.root / name)

    def test_cold_then_warm_reattaches_current_manifest(self):
        cold = self.execute(); self.assertEqual("analyzed", cold["status"]); self.assertEqual(1, self.calls)
        self.write_manifest("build-two")
        warm = self.execute(name="warm.json")
        value = json.loads((self.root / "warm.json").read_text())
        self.assertEqual("reused", warm["status"]); self.assertEqual(1, self.calls)
        self.assertEqual("build-two", value["metadata"]["build"])
        self.assertEqual(_file_digest(self.metadata), value["input"]["metadataInputSha256"])

    def test_source_artifact_scope_and_namespace_changes_do_not_reuse(self):
        self.execute()
        self.java.write_text("class Board { int changed; }\n"); self.write_manifest("build-two")
        self.execute(name="source.json"); self.assertEqual(2, self.calls)
        self.artifact.write_bytes(b"artifact-two"); self.write_manifest("build-three")
        self.execute(name="artifact.json"); self.assertEqual(3, self.calls)
        changed_scope = AnalysisRequest("tenant-a", self.sources, self.artifact, self.metadata, "board", self.root / "jdk", include_package="other")
        self.execute(changed_scope, "scope.json"); self.assertEqual(4, self.calls)
        other_tenant = AnalysisRequest("tenant-b", self.sources, self.artifact, self.metadata, "board", self.root / "jdk")
        self.execute(other_tenant, "tenant.json"); self.assertEqual(5, self.calls)

    def test_runner_analyzer_or_jdk_fingerprint_change_invalidates(self):
        self.execute()
        with patch("tools.analysis_reuse.reuse._tool_fingerprints", return_value={"runner": "changed"}), patch("tools.analysis_reuse.reuse._run_analyzer", self.fake_analyzer):
            receipt = execute(self.request, self.cache, self.root / "toolchain.json")
        self.assertEqual("analyzed", receipt["status"])
        self.assertEqual(2, self.calls)

    def test_invalid_manifest_mutation_and_failure_publish_nothing(self):
        self.metadata.write_text("{}")
        with self.assertRaisesRegex(ValueError, "build field"):
            self.execute(name="bad.json")
        self.assertFalse((self.root / "bad.json").exists())
        self.write_manifest("build-one")
        with patch("tools.analysis_reuse.reuse._tool_fingerprints", return_value={"runner": "a"}), patch("tools.analysis_reuse.reuse._run_analyzer", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                execute(self.request, self.cache, self.root / "failed.json")
        self.assertFalse((self.root / "failed.json").exists())

    def test_corrupt_cache_fails_closed(self):
        self.execute(); path = next(self.cache.glob("*.json")); path.write_text("not json")
        with self.assertRaisesRegex(ValueError, "corrupt cache"):
            self.execute(name="corrupt.json")
        self.assertFalse((self.root / "corrupt.json").exists())

    def test_mutation_during_analysis_and_existing_output_fail(self):
        def mutate(request, output):
            self.fake_analyzer(request, output); self.java.write_text("class Board { int mutation; }\n")
        with patch("tools.analysis_reuse.reuse._tool_fingerprints", return_value={"runner": "a"}), patch("tools.analysis_reuse.reuse._run_analyzer", mutate):
            with self.assertRaises(ValueError):
                execute(self.request, self.cache, self.root / "mutated.json")
        self.assertFalse((self.root / "mutated.json").exists())
        self.write_manifest("build-two")
        target = self.root / "exists.json"; target.write_text("keep")
        with self.assertRaises(FileExistsError): self.execute(name="exists.json")
        self.assertEqual("keep", target.read_text())

    def test_concurrent_same_key_creators_use_verified_single_cache(self):
        results, errors = [], []
        def slow(request, output):
            time.sleep(0.1); self.fake_analyzer(request, output)
        def invoke(name):
            try:
                results.append(execute(self.request, self.cache, self.root / name))
            except Exception as error: errors.append(error)
        first = threading.Thread(target=invoke, args=("one.json",)); second = threading.Thread(target=invoke, args=("two.json",))
        with patch("tools.analysis_reuse.reuse._tool_fingerprints", return_value={"runner": "a"}), patch("tools.analysis_reuse.reuse._run_analyzer", slow):
            first.start(); second.start(); first.join(timeout=5); second.join(timeout=5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertFalse(errors); self.assertEqual(2, len(results)); self.assertEqual(1, len(list(self.cache.glob("*.json"))))
        self.assertEqual(1, self.calls)
        self.assertEqual({"analyzed", "reused"}, {r["status"] for r in results})
        self.assertTrue((self.root / "one.json").is_file()); self.assertTrue((self.root / "two.json").is_file())

    def test_partial_analyzer_result_is_never_cached(self):
        for failure in ("missing-tool", "partial-status", "empty-calls"):
            with self.subTest(failure=failure):
                def partial(request, output):
                    self.fake_analyzer(request, output)
                    value = json.loads(output.read_text())
                    if failure == "missing-tool": value["tools"]["wala"] = {}
                    elif failure == "partial-status": value["status"] = "partial"
                    else: value["tools"]["wala"]["calls"] = []
                    output.write_text(json.dumps(value))
                with patch("tools.analysis_reuse.reuse._tool_fingerprints", return_value={"runner": "a"}), patch("tools.analysis_reuse.reuse._run_analyzer", partial):
                    with self.assertRaises(ValueError):
                        execute(self.request, self.cache, self.root / "partial.json")
                self.assertFalse((self.root / "partial.json").exists())
                self.assertEqual([], list(self.cache.glob("*.json")))

    def test_metadata_bound_and_unkeyed_jvm_options_fail(self):
        self.metadata.write_bytes(b" " * (MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "metadata exceeds"):
            self.execute()
        self.write_manifest("build-one")
        with patch.dict(os.environ, {"JAVA_TOOL_OPTIONS": "-Danything=1"}):
            with self.assertRaisesRegex(ValueError, "JAVA_TOOL_OPTIONS"):
                self.execute()
        self.assertFalse((self.root / "out.json").exists())

    def test_mutation_on_cache_hit_does_not_publish(self):
        self.execute()
        def mutate(*args):
            body = _load_cache(*args)
            self.java.write_text("class Board { int changed; }\n")
            return body
        with patch("tools.analysis_reuse.reuse._load_cache", mutate):
            with self.assertRaises(ValueError):
                self.execute(name="hit-mutation.json")
        self.assertFalse((self.root / "hit-mutation.json").exists())

    def test_repository_identity_isolation(self):
        first = self.execute()
        value = json.loads(self.metadata.read_text()); value["repository"] = "local:another-repository"
        self.metadata.write_text(json.dumps(value))
        second = self.execute(name="another-repository.json")
        self.assertEqual("analyzed", second["status"])
        self.assertNotEqual(first["cacheKey"], second["cacheKey"])

    def test_changed_cache_content_is_rejected(self):
        self.execute()
        path = next(self.cache.glob("*.json")); value = json.loads(path.read_text())
        value["analysis"]["limitations"] = ["tampered"]
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "content digest"):
            self.execute(name="tampered.json")
        self.assertFalse((self.root / "tampered.json").exists())


if __name__ == "__main__":
    unittest.main()
