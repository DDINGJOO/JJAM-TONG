"""Independent-oracle tests for declared build baseline comparisons."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.build_inventory import baseline
from tools.build_inventory.baseline import compare
from tools.build_inventory.inventory import capture


NOW = "2026-11-14T12:00:00.000000Z"
TEMP_ROOT = "/private/tmp"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _set(state: str, path: str | None = None, data: bytes | None = None) -> dict:
    return {"state": state, "files": [] if path is None else [{"path": path, "sha256": _digest(data or b"")}]}


def _module(module_id: str, *, dependencies=(), source=b"source", artifact_state="present",
            artifact=b"artifact", classpath_state="present", descriptor=None) -> dict:
    return {
        "id": module_id,
        "descriptor": descriptor or f"{module_id}/build.gradle",
        "dependencies": {"state": "present", "modules": list(dependencies)},
        "artifacts": _set(artifact_state, None if artifact_state != "present" else f"{module_id}/out.bin", artifact),
        "inputs": {
            "sources": _set("present", f"{module_id}/source.txt", source),
            "generatedSources": _set("present"),
            "classpath": _set(classpath_state),
            "toolchain": _set("not-applicable"),
            "conditions": _set("present"),
        },
    }


def _snapshot(root: Path, modules: list[dict], *, coverage="complete", tenant="tenant",
              repository="repo", revision="r1", build="b1"):
    fixture_bytes = (b"artifact", b"source", b"changed", b"new-a", b"new-b")
    by_digest = {_digest(value): value for value in fixture_bytes}
    for module in modules:
        for file_set in [module["artifacts"], *module["inputs"].values()]:
            for item in file_set["files"]:
                path = root / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                # The expected hash is an independent oracle, supplied by the fixture.
                data = by_digest[item["sha256"]]
                path.write_bytes(data)
                item["sha256"] = _digest(data)
    manifest = {
        "schema": "jjamtong.build-manifest.v1", "repository": repository,
        "revision": revision, "build": build, "recordedAt": NOW,
        "producer": {"name": "fixture", "version": "1"},
        "moduleCoverage": coverage, "modules": modules,
    }
    return capture(manifest, root, tenant, verified_at=NOW)


class BaselineComparisonTest(unittest.TestCase):
    def test_changed_common_reports_old_and_new_reverse_consumer_paths(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), [_module("common"), _module("consumer", dependencies=("common",))])
            new = _snapshot(Path(new_dir), [_module("common", source=b"changed"), _module("consumer", dependencies=("common",))])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertEqual("CHANGES", result["status"])
        self.assertIn({"side": "baseline", "changedModule": "common", "path": ["consumer", "common"]}, result["changes"]["impactPaths"])
        self.assertIn({"side": "current", "changedModule": "common", "path": ["consumer", "common"]}, result["changes"]["impactPaths"])
        self.assertEqual("DECLARED", result["mode"])
        self.assertEqual(NOW, result["baseline"]["recordedAt"])
        self.assertEqual(NOW, result["current"]["verifiedAt"])

    def test_added_and_deleted_edges_and_cycles_are_bounded(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), [_module("a", dependencies=("b",)), _module("b", dependencies=("a", "gone")), _module("gone")])
            new = _snapshot(Path(new_dir), [_module("a", dependencies=("b", "new")), _module("b", dependencies=("a",)), _module("new")])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertIn({"consumer": "a", "dependency": "new"}, result["changes"]["addedEdges"])
        self.assertIn({"consumer": "b", "dependency": "gone"}, result["changes"]["removedEdges"])
        self.assertIn({"side": "baseline", "changedModule": "gone", "path": ["b", "gone"]}, result["changes"]["impactPaths"])
        self.assertTrue(all(len(item["path"]) <= 32 for item in result["changes"]["impactPaths"]))

    def test_all_artifact_states_and_input_unknown_are_preserved_as_declarations(self):
        states = ("present", "not-applicable", "unavailable")
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            for state in states:
                old = _snapshot(Path(old_dir), [_module("m", artifact_state=state)])
                new = _snapshot(Path(new_dir), [_module("m", artifact_state="present")])
                result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
                if state == "unavailable":
                    self.assertEqual("PARTIAL", result["status"])
                else:
                    self.assertTrue(result["changes"]["moduleChanges"] or state == "present")
            partial_old = _snapshot(Path(old_dir), [_module("old")], coverage="partial")
            partial_new = _snapshot(Path(new_dir), [_module("new", classpath_state="unavailable")], coverage="partial")
            result = compare(partial_old, partial_new, partial_old.manifest_sha256, partial_new.manifest_sha256)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual([], result["changes"]["removedModules"])
        self.assertIn({"module": "old", "missingFrom": "current"}, result["possiblyMissingModules"])
        self.assertIn("PARTIAL", result["limitations"])

    def test_present_empty_artifact_and_each_input_set_have_independent_change_reasons(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            empty_artifact = _module("m")
            empty_artifact["artifacts"] = _set("present")
            old = _snapshot(Path(old_dir), [empty_artifact])
            new = _snapshot(Path(new_dir), [_module("m")])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
            self.assertIn("ARTIFACTS", [item["reason"] for item in result["changes"]["moduleChanges"]])
            for input_name in ("sources", "generatedSources", "classpath", "toolchain", "conditions"):
                old_module, new_module = _module("m"), _module("m")
                old_module["inputs"][input_name] = _set("not-applicable")
                new_module["inputs"][input_name] = _set("present")
                old = _snapshot(Path(old_dir), [old_module])
                new = _snapshot(Path(new_dir), [new_module])
                result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
                self.assertIn("INPUT_" + input_name.upper(),
                              [item["reason"] for item in result["changes"]["moduleChanges"]])

    def test_descriptor_remap_is_not_mistaken_for_a_module_add_or_remove(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), [_module("stable", descriptor="old/build.gradle")])
            new = _snapshot(Path(new_dir), [_module("stable", descriptor="new/build.gradle")])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertEqual([], result["changes"]["addedModules"])
        self.assertEqual([], result["changes"]["removedModules"])
        self.assertIn({"module": "stable", "reason": "DESCRIPTOR", "baseline": "old/build.gradle",
                       "current": "new/build.gradle"}, result["changes"]["moduleChanges"])

    def test_known_identical_declarations_only_report_no_change_in_available_evidence(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            snapshot = _snapshot(Path(directory), [_module("m")])
            result = compare(snapshot, snapshot, snapshot.manifest_sha256, snapshot.manifest_sha256)
        self.assertEqual("NO_CHANGE_IN_AVAILABLE_EVIDENCE", result["status"])
        self.assertEqual([], result["changes"]["impactPaths"])

    def test_pins_tenant_repository_and_limit_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), [_module("m")])
            other_tenant = _snapshot(Path(new_dir), [_module("m")], tenant="other")
            other_repo = _snapshot(Path(new_dir), [_module("m")], repository="other")
            with self.assertRaises(ValueError):
                compare(old, other_tenant, old.manifest_sha256, other_tenant.manifest_sha256)
            with self.assertRaises(ValueError):
                compare(old, other_repo, old.manifest_sha256, other_repo.manifest_sha256)
            with self.assertRaises(ValueError):
                compare(old, old, "0" * 64, old.manifest_sha256)
            with self.assertRaises(ValueError):
                compare(old, old, old.manifest_sha256, old.manifest_sha256, limit=1001)

    def test_display_limit_marks_partial_instead_of_hiding_extra_work(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), [_module("a"), _module("b")])
            new = _snapshot(Path(new_dir), [_module("a", source=b"new-a"), _module("b", source=b"new-b")])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256, limit=1)
        self.assertEqual("PARTIAL", result["status"])
        self.assertIn("QUERY_LIMIT", result["limitations"])
        self.assertLessEqual(len(result["changes"]["moduleChanges"]), 1)

    def test_unavailable_dependency_declaration_only_reports_possibly_missing_edges(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old_module = _module("consumer", dependencies=("old-dependency",))
            new_module = _module("consumer", dependencies=("new-dependency",))
            new_module["dependencies"] = {"state": "unavailable", "modules": []}
            old = _snapshot(Path(old_dir), [old_module, _module("old-dependency")])
            new = _snapshot(Path(new_dir), [new_module, _module("old-dependency")])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual([], result["changes"]["addedEdges"])
        self.assertEqual([], result["changes"]["removedEdges"])
        self.assertIn({"consumer": "consumer", "dependency": "old-dependency", "missingFrom": "current"},
                      result["possiblyMissingEdges"])

    def test_unknown_declarations_on_added_and_removed_modules_are_partial(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            removed = _module("removed", artifact_state="unavailable")
            added = _module("added", classpath_state="unavailable")
            old = _snapshot(Path(old_dir), [removed])
            new = _snapshot(Path(new_dir), [added])
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(["added"], result["changes"]["addedModules"])
        self.assertEqual(["removed"], result["changes"]["removedModules"])

    def test_revision_and_build_identity_changes_are_explicit_without_module_changes(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), [_module("stable")], revision="r1", build="b1")
            new = _snapshot(Path(new_dir), [_module("stable")], revision="r2", build="b2")
            result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertEqual("CHANGES", result["status"])
        self.assertEqual([], result["changes"]["moduleChanges"])
        self.assertEqual([
            {"field": "revision", "baseline": "r1", "current": "r2"},
            {"field": "build", "baseline": "b1", "current": "b2"},
        ], result["changes"]["identityChanges"])

    def test_global_edge_budget_stops_reverse_paths_for_many_changed_modules(self):
        old_modules = [_module(f"m{index}", dependencies=("shared",)) for index in range(8)]
        new_modules = [_module(f"m{index}", dependencies=("shared",), source=b"changed") for index in range(8)]
        old_modules.append(_module("shared"))
        new_modules.append(_module("shared"))
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as old_dir, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as new_dir:
            old = _snapshot(Path(old_dir), old_modules)
            new = _snapshot(Path(new_dir), new_modules)
            with patch.object(baseline, "_MAX_EDGE_CHECKS", 4), \
                    patch.object(baseline, "_edge_index", wraps=baseline._edge_index) as edge_index:
                result = compare(old, new, old.manifest_sha256, new.manifest_sha256)
        self.assertEqual("PARTIAL", result["status"])
        self.assertIn("TRAVERSAL_BUDGET", result["limitations"])
        self.assertEqual([], result["changes"]["impactPaths"])
        self.assertEqual(2, edge_index.call_count)


if __name__ == "__main__":
    unittest.main()
