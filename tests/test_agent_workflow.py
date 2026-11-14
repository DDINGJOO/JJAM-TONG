import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "tools" / "agent_workflow.py"
SPEC = importlib.util.spec_from_file_location("agent_workflow", SCRIPT)
workflow = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(workflow)


def task(name, owner="a", state="running", **extra):
    value = {"id": name, "ticket": "#87", "lane": name, "owner": owner, "role": "executor", "scopes": ["owned.txt"], "dependencies": [], "state": state, "acceptance": ["works"], "result": {"state": "complete" if state == "complete" else "unknown"}}
    value.update(extra); return value


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root, self.state = Path(self.tmp.name), Path(self.tmp.name) / "state"
        (self.root / "owned.txt").write_text("before")

    def manifest(self, tasks, revision="r1"):
        return {"run": {"id": "run", "version": "v1", "revision": revision, "source_scope": "owned", "source_root": str(self.root)}, "tasks": tasks}

    def write(self, value):
        path = self.root / "run.json"; path.write_text(json.dumps(value)); return path

    def complete_manifest(self, **extra):
        item = task("one", state="complete", **extra); manifest = self.manifest([item])
        fingerprint = workflow.task_fingerprint(manifest, item)
        validation = {"status":"pass", "command":"python -m unittest", "exit_code":0, "version":"v1", "revision":"r1", "fingerprint":fingerprint, "timestamp":1, "reference":"test"}
        item["validation"] = extra.get("validation", [validation])
        return manifest

    def run_cli(self, *args, cwd=None, stdin=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--state-dir", str(self.state), *args], cwd=cwd or self.root, input=stdin, text=True, capture_output=True, check=False)

    def test_scope_normalization_and_dependencies_are_enforced(self):
        self.assertTrue(workflow.scope_overlap(["tools/x/../one"], ["tools/one/file"]))
        self.assertFalse(workflow.evaluate(self.manifest([task("one"), task("two", scopes=["owned.txt"])]))["ok"])
        done = task("one", state="complete", validation=[])
        dependent = task("two", state="complete", dependencies=["one"], validation=[])
        self.assertFalse(workflow.evaluate(self.manifest([done, dependent]))["ok"])
        cyclic = []; cyclic.append(cyclic)
        self.assertFalse(workflow.evaluate({"run": self.manifest([])["run"], "tasks": cyclic})["ok"])

    def test_dependency_cycles_and_blank_reasons_are_rejected(self):
        first = task("one", state="complete", dependencies=["two"])
        second = task("two", state="complete", dependencies=["one"])
        manifest = self.manifest([first, second])
        fingerprints = {item["id"]: workflow.task_fingerprint(manifest, item) for item in manifest["tasks"]}
        for item in manifest["tasks"]:
            item["validation"] = [{"status":"pass", "command":"test", "exit_code":0, "version":"v1", "revision":"r1", "fingerprint":fingerprints[item["id"]], "timestamp":1, "reference":"test"}]
        self.assertIn("task dependency cycle", workflow.evaluate(manifest, fingerprints)["message"])
        self.assertIn("task dependency cycle", workflow.evaluate(self.manifest([task("self", dependencies=["self"])]))["message"])
        self.assertFalse(workflow.evaluate(self.manifest([task("wait", state="deferred", reason=" \t ")]))["ok"])

    def test_check_requires_command_and_source_mutation_invalidates_evidence(self):
        manifest = self.complete_manifest(validation=[]); path = self.write(manifest)
        self.assertFalse(workflow.check(path, self.state)["ok"])
        fingerprint = workflow.task_fingerprint(manifest, manifest["tasks"][0])
        manifest["tasks"][0]["validation"] = [{"status":"pass", "command":"python -m unittest", "exit_code":0, "version":"v1", "revision":"r1", "fingerprint":fingerprint, "timestamp":1, "reference":"test"}]
        path = self.write(manifest); self.assertTrue(workflow.check(path, self.state)["ok"])
        (self.root / "owned.txt").write_text("after")
        self.assertFalse(workflow.check(path, self.state)["ok"])

    def test_fingerprint_rejects_symlinked_scope_ancestor(self):
        nested = self.root / "nested"; nested.mkdir()
        (nested / "owned.txt").write_text("content")
        (self.root / "alias").symlink_to(nested, target_is_directory=True)
        manifest = self.manifest([task("one", scopes=["alias/owned.txt"])])
        with self.assertRaisesRegex(ValueError, "owned scope escapes source root"):
            workflow.task_fingerprint(manifest, manifest["tasks"][0])

    def test_qa_requires_current_independent_reviewer_or_coordinator(self):
        manifest = self.complete_manifest(milestone=True, assessments=[])
        fingerprint = workflow.task_fingerprint(manifest, manifest["tasks"][0])
        manifest["tasks"][0]["assessments"] = [{"kind":"human", "status":"pass", "reviewer":"r", "revision":"old", "fingerprint":fingerprint}, {"kind":"agent", "status":"na", "reason":"not applicable", "coordinator":"lead", "revision":"r1", "fingerprint":fingerprint}]
        self.assertFalse(workflow.evaluate(manifest, {"one": fingerprint})["ok"])
        manifest["tasks"][0]["assessments"][0].update({"revision":"r1", "version":"v1"})
        manifest["tasks"][0]["assessments"][1]["version"] = "v1"
        self.assertTrue(workflow.evaluate(manifest, {"one": fingerprint})["ok"])
        manifest["tasks"][0]["assessments"][1]["coordinator"] = "a"
        self.assertFalse(workflow.evaluate(manifest, {"one": fingerprint})["ok"])

    def test_completion_schema_rejects_malformed_identity_acceptance_and_assessors(self):
        manifest = self.complete_manifest()
        fingerprint = workflow.task_fingerprint(manifest, manifest["tasks"][0])
        for field, value in (("id", True), ("version", {}), ("revision", " "), ("source_scope", [])):
            candidate = json.loads(json.dumps(manifest)); candidate["run"][field] = value
            self.assertFalse(workflow.evaluate(candidate, {"one": fingerprint})["ok"], field)
        for acceptance in ("works", [], ["works", " \t "], ["works"] * (workflow.MAX_ACCEPTANCE + 1)):
            candidate = json.loads(json.dumps(manifest)); candidate["tasks"][0]["acceptance"] = acceptance
            self.assertFalse(workflow.evaluate(candidate, {"one": fingerprint})["ok"], repr(acceptance))
        for field, value in (("version", True), ("revision", {}), ("fingerprint", []), ("timestamp", float("nan"))):
            candidate = json.loads(json.dumps(manifest)); candidate["tasks"][0]["validation"][0][field] = value
            self.assertFalse(workflow.evaluate(candidate, {"one": fingerprint})["ok"], field)
        manifest = self.complete_manifest(milestone=True)
        fingerprint = workflow.task_fingerprint(manifest, manifest["tasks"][0])
        manifest["tasks"][0]["assessments"] = [
            {"kind":"human", "status":"pass", "reviewer":True, "version":"v1", "revision":"r1", "fingerprint":fingerprint},
            {"kind":"agent", "status":"pass", "reviewer":"reviewer", "version":"v1", "revision":"r1", "fingerprint":fingerprint},
        ]
        self.assertFalse(workflow.evaluate(manifest, {"one": fingerprint})["ok"])
        manifest["tasks"][0]["assessments"][0]["reviewer"] = "human-reviewer"
        self.assertTrue(workflow.evaluate(manifest, {"one": fingerprint})["ok"])
        manifest["tasks"][0]["assessments"][1]["reviewer"] = {"not": "an identity"}
        self.assertFalse(workflow.evaluate(manifest, {"one": fingerprint})["ok"])

    def test_false_exit_code_and_stale_assessment_version_are_rejected(self):
        manifest = self.complete_manifest()
        fingerprint = workflow.task_fingerprint(manifest, manifest["tasks"][0])
        manifest["tasks"][0]["validation"][0]["exit_code"] = False
        self.assertFalse(workflow.evaluate(manifest, {"one": fingerprint})["ok"])
        manifest = self.complete_manifest(milestone=True)
        fingerprint = workflow.task_fingerprint(manifest, manifest["tasks"][0])
        manifest["tasks"][0]["assessments"] = [
            {"kind":"human", "status":"pass", "reviewer":"r", "version":"old", "revision":"r1", "fingerprint":fingerprint},
            {"kind":"agent", "status":"pass", "reviewer":"r2", "version":"v1", "revision":"r1", "fingerprint":fingerprint},
        ]
        self.assertFalse(workflow.evaluate(manifest, {"one": fingerprint})["ok"])

    def test_real_hook_events_bind_and_stop_for_both_tools_from_subdir(self):
        manifest = self.complete_manifest(); path = self.write(manifest)
        for tool in ("codex", "claude"):
            bound = self.run_cli("bind", "--manifest", str(path), "--task", "one", "--session-id", "s", "--tool", tool)
            self.assertEqual(0, bound.returncode, bound.stderr)
        subdir = self.root / "nested"; subdir.mkdir()
        for tool in ("codex", "claude"):
            start = self.run_cli("hook", "--tool", tool, cwd=subdir, stdin=json.dumps({"hook_event_name":"SessionStart", "session_id":"s"}))
            self.assertEqual(0, start.returncode); self.assertIn("bound", json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"])
            stopped = self.run_cli("hook", "--tool", tool, cwd=subdir, stdin=json.dumps({"hook_event_name":"Stop", "session_id":"s", "stop_hook_active":False}))
            self.assertEqual({}, json.loads(stopped.stdout))
            child = self.run_cli("hook", "--tool", tool, cwd=subdir, stdin=json.dumps({"hook_event_name":"SubagentStop", "session_id":"s", "agent_id":"child-1", "agent_type":"executor", "stop_hook_active":False}))
            self.assertEqual({}, json.loads(child.stdout))
            for event in ("Stop", "SubagentStop"):
                loop_payload = {"hook_event_name":event, "session_id":"s", "stop_hook_active":True}
                if event == "SubagentStop": loop_payload.update({"agent_id":"child-1", "agent_type":"executor"})
                loop = self.run_cli("hook", "--tool", tool, cwd=subdir, stdin=json.dumps(loop_payload))
                self.assertEqual({}, json.loads(loop.stdout))

    def test_real_stop_blocks_incomplete_but_deferred_stops_with_pending_work(self):
        incomplete = self.write(self.manifest([task("one")]))
        self.assertEqual(0, self.run_cli("bind", "--manifest", str(incomplete), "--task", "one", "--session-id", "open", "--tool", "codex").returncode)
        blocked = self.run_cli("hook", "--tool", "codex", stdin=json.dumps({"hook_event_name":"Stop", "session_id":"open", "stop_hook_active":False}))
        self.assertEqual(0, blocked.returncode); self.assertEqual("block", json.loads(blocked.stdout)["decision"])
        for tool in ("codex", "claude"):
            child = self.run_cli("hook", "--tool", tool, stdin=json.dumps({"hook_event_name":"SubagentStop", "session_id":"open", "agent_id":"child-1", "agent_type":"executor", "stop_hook_active":False}))
            self.assertEqual(0, child.returncode); self.assertEqual({}, json.loads(child.stdout))
        deferred = self.write(self.manifest([task("two", state="deferred", reason="await dependency")]))
        self.assertEqual(0, self.run_cli("bind", "--manifest", str(deferred), "--task", "two", "--session-id", "deferred", "--tool", "claude").returncode)
        allowed = self.run_cli("hook", "--tool", "claude", stdin=json.dumps({"hook_event_name":"Stop", "session_id":"deferred", "stop_hook_active":False}))
        self.assertEqual({}, json.loads(allowed.stdout))
        status = self.run_cli("status")
        self.assertEqual("deferred", json.loads(status.stdout)["pending"][0]["state"])

    def test_unbound_advisory_malformed_state_and_input_are_bounded(self):
        advisory = self.run_cli("hook", "--tool", "codex", stdin=json.dumps({"hook_event_name":"UserPromptSubmit", "session_id":"none"}))
        self.assertEqual(0, advisory.returncode); self.assertIn("advisory", advisory.stdout)
        self.state.mkdir(); (self.state / "state.json").write_text("{")
        status = self.run_cli("status")
        self.assertNotEqual(0, status.returncode); self.assertIn("workflow state invalid", status.stdout)
        loop = self.run_cli("hook", "--tool", "codex", stdin=json.dumps({"hook_event_name":"Stop", "session_id":"s", "stop_hook_active":True}))
        self.assertEqual(0, loop.returncode); self.assertEqual({}, json.loads(loop.stdout))
        bad = self.run_cli("hook", "--tool", "codex", stdin="x" * (workflow.MAX_INPUT + 1))
        self.assertEqual(0, bad.returncode); self.assertLessEqual(len(bad.stdout), 600); self.assertNotIn("x" * 20, bad.stdout)

    def test_corrupt_state_and_broken_bound_manifest_have_distinct_stop_decisions(self):
        manifest = self.complete_manifest(); path = self.write(manifest)
        for tool in ("codex", "claude"):
            self.assertEqual(0, self.run_cli("bind", "--manifest", str(path), "--task", "one", "--session-id", "bound", "--tool", tool).returncode)
        path.write_text("{")
        for tool in ("codex", "claude"):
            broken = self.run_cli("hook", "--tool", tool, stdin=json.dumps({"hook_event_name":"Stop", "session_id":"bound", "stop_hook_active":False}))
            self.assertEqual(0, broken.returncode); self.assertEqual("block", json.loads(broken.stdout)["decision"])
            self.assertEqual("bound task manifest unavailable", json.loads(broken.stdout)["reason"])
        (self.state / "state.json").write_text("{")
        for tool in ("codex", "claude"):
            stopped = self.run_cli("hook", "--tool", tool, stdin=json.dumps({"hook_event_name":"Stop", "session_id":"bound", "stop_hook_active":False}))
            child = self.run_cli("hook", "--tool", tool, stdin=json.dumps({"hook_event_name":"SubagentStop", "session_id":"bound", "agent_id":"child-1", "agent_type":"executor", "stop_hook_active":False}))
            self.assertEqual(0, stopped.returncode); self.assertEqual({}, json.loads(stopped.stdout))
            self.assertEqual(0, child.returncode); self.assertEqual({}, json.loads(child.stdout))

    def test_same_session_id_is_isolated_by_tool(self):
        incomplete = self.write(self.manifest([task("one")]))
        bound = self.run_cli("bind", "--manifest", str(incomplete), "--task", "one", "--session-id", "shared", "--tool", "codex")
        self.assertEqual(0, bound.returncode, bound.stderr)
        codex = self.run_cli("hook", "--tool", "codex", stdin=json.dumps({"hook_event_name":"Stop", "session_id":"shared", "stop_hook_active":False}))
        claude = self.run_cli("hook", "--tool", "claude", stdin=json.dumps({"hook_event_name":"Stop", "session_id":"shared", "stop_hook_active":False}))
        self.assertEqual("block", json.loads(codex.stdout)["decision"])
        self.assertEqual({}, json.loads(claude.stdout))

    def test_malformed_manifest_field_types_return_structured_failures(self):
        path = self.write({"run": [], "tasks": [{"id":"one", "result": []}]})
        result = self.run_cli("check", "--manifest", str(path))
        self.assertNotEqual(0, result.returncode); self.assertEqual(False, json.loads(result.stdout)["ok"])
        path = self.write({"run": self.manifest([])["run"], "tasks": {"not":"a list"}})
        result = self.run_cli("fingerprint", "--manifest", str(path), "--task", "one")
        self.assertNotEqual(0, result.returncode); self.assertEqual(False, json.loads(result.stdout)["ok"])


if __name__ == "__main__": unittest.main()
