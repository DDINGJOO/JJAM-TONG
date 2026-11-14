"""Contract tests for declared manifests and their local verifier record."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.build_inventory.inventory import (
    SafeReader, Snapshot, canonical_json, canonical_path, capture, link_analysis,
    load_manifest, load_snapshot, save_snapshot,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class InventoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS commonly exposes its temporary directory through /var, which is
        # itself a symlink.  The production reader intentionally rejects that
        # spelling, so fixtures use the physical absolute root.
        self.root = Path(self.temp.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "src" / "Main.java").write_bytes(b"class Main {}\n")
        (self.root / "app.jar").write_bytes(b"declared artifact")

    def manifest(self) -> dict:
        source, artifact = (self.root / "src" / "Main.java").read_bytes(), (self.root / "app.jar").read_bytes()
        files = lambda path, payload: {"state": "present", "files": [{"path": path, "sha256": sha(payload)}]}
        empty = {"state": "unavailable", "files": []}
        return {
            "schema": "jjamtong.build-manifest.v1", "repository": "example/repo",
            "revision": "r1", "build": "b1", "recordedAt": "2026-01-02T03:04:05.678901Z",
            "producer": {"name": "owner-export", "version": "1"}, "moduleCoverage": "complete",
            "modules": [{"id": "app", "descriptor": "pom.xml", "dependencies": {"state": "present", "modules": []},
                         "artifacts": files("app.jar", artifact),
                         "inputs": {"sources": files("src/Main.java", source), "generatedSources": empty,
                                    "classpath": empty, "toolchain": empty, "conditions": empty}}],
        }

    def test_canonical_literal_bytes_and_safe_paths(self) -> None:
        self.assertEqual(b'{"a":"x","b":"\xed\x95\x9c"}', canonical_json({"b": "한", "a": "x"}))
        self.assertEqual("src/Main.java", canonical_path("src/Main.java"))
        with self.assertRaises(ValueError):
            canonical_path("invalid\x00descriptor")

    def test_unhashable_enum_values_are_invalid_input(self) -> None:
        for location in ("moduleCoverage", "artifacts", "dependencies", "sources"):
            document = self.manifest()
            if location == "moduleCoverage":
                document[location] = {}
            elif location == "sources":
                document["modules"][0]["inputs"][location]["state"] = []
            else:
                document["modules"][0][location]["state"] = {}
            with self.subTest(location=location), self.assertRaises(ValueError):
                capture(document, self.root, "t")
        for value in ("../x", "/x", "x//y", "x/./y", "x\\y"):
            with self.assertRaises(ValueError):
                canonical_path(value)

    def test_capture_distinguishes_declared_states_and_records_counts(self) -> None:
        snapshot = capture(self.manifest(), self.root, "tenant-a", "2026-01-02T03:04:06.000000Z")
        self.assertEqual(2, snapshot.verification["checkedFiles"])
        self.assertEqual(len(b"declared artifact") + len(b"class Main {}\n"), snapshot.verification["checkedBytes"])
        self.assertEqual("2026-01-02T03:04:05.678901Z", snapshot.document["recordedAt"])
        self.assertEqual("2026-01-02T03:04:06.000000Z", snapshot.verification["verifiedAt"])
        present_empty = self.manifest()
        present_empty["modules"][0]["artifacts"] = {"state": "present", "files": []}
        self.assertEqual([], capture(present_empty, self.root, "tenant-a").modules[0]["artifacts"]["files"])

    def test_rejects_bad_time_counts_and_unknown_nonempty_states(self) -> None:
        for bad_time in ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05.00000Z", "2026-01-02T03:04:05.000000+00:00", "2026-02-30T03:04:05.000000Z"):
            document = self.manifest(); document["recordedAt"] = bad_time
            with self.assertRaises(ValueError): capture(document, self.root, "tenant-a")
        document = self.manifest()
        document["modules"][0]["artifacts"]["state"] = "unavailable"
        with self.assertRaises(ValueError): capture(document, self.root, "tenant-a")
        snap = capture(self.manifest(), self.root, "tenant-a")
        envelope = snap.verification
        envelope["checkedFiles"] = True
        with self.assertRaises(ValueError):
            Snapshot(snap.tenant, snap.manifest_json, canonical_json(envelope).decode(), snap.manifest_sha256, sha(canonical_json(envelope)))

    def test_mutation_isolated_and_duplicate_paths_are_rejected(self) -> None:
        document = self.manifest()
        snapshot = capture(document, self.root, "tenant-a")
        document["repository"] = "changed"
        view = snapshot.document
        view["modules"][0]["id"] = "changed"
        self.assertEqual("example/repo", snapshot.repository)
        self.assertEqual("app", snapshot.modules[0]["id"])
        duplicate = self.manifest()
        duplicate["modules"][0]["inputs"]["sources"]["files"].append(copy.deepcopy(duplicate["modules"][0]["inputs"]["sources"]["files"][0]))
        with self.assertRaises(ValueError): capture(duplicate, self.root, "tenant-a")

    def test_file_mismatch_symlink_and_budget_fail_closed(self) -> None:
        document = self.manifest()
        (self.root / "app.jar").write_bytes(b"changed")
        with self.assertRaises(ValueError): capture(document, self.root, "tenant-a")
        (self.root / "linked.jar").symlink_to(self.root / "src" / "Main.java")
        with SafeReader(self.root) as reader:
            with self.assertRaises(ValueError): reader.hash_file("linked.jar")
        (self.root / "large").write_bytes(b"1234")
        with SafeReader(self.root, file_limit=3) as reader:
            with self.assertRaises(ValueError): reader.read_bytes("large", max_bytes=3)

    def test_reader_rejects_root_symlink_unsupported_platform_and_read_mutation(self) -> None:
        alias = self.root / "inventory-root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            with SafeReader(alias):
                pass
        with mock.patch("tools.build_inventory.inventory.os.name", "nt"):
            with self.assertRaises(ValueError):
                with SafeReader(self.root):
                    pass
        original_read = __import__("os").read
        changed = False

        def mutate_after_read(fd, size):
            nonlocal changed
            result = original_read(fd, size)
            if not changed:
                changed = True
                (self.root / "app.jar").write_bytes(b"concurrent replacement")
            return result

        with SafeReader(self.root) as reader, mock.patch("tools.build_inventory.inventory.os.read", side_effect=mutate_after_read):
            with self.assertRaisesRegex(ValueError, "changed"):
                reader.hash_file("app.jar")

    def test_reader_never_follows_a_path_replaced_with_symlink_before_open(self) -> None:
        raced = self.root / "raced"
        raced.write_bytes(b"inside")
        outside = self.root.parent / "outside-build-inventory-race"
        outside.write_bytes(b"outside must not be read")
        self.addCleanup(outside.unlink, missing_ok=True)
        original_open = __import__("os").open
        replaced = False

        def replace_at_final_open(path, flags, *args, **kwargs):
            nonlocal replaced
            if path == "raced" and not replaced:
                replaced = True
                raced.unlink()
                raced.symlink_to(outside)
            return original_open(path, flags, *args, **kwargs)

        with SafeReader(self.root) as reader, mock.patch("tools.build_inventory.inventory.os.open", side_effect=replace_at_final_open):
            with self.assertRaises(ValueError):
                reader.read_bytes("raced", max_bytes=1024)
        self.assertTrue(replaced)
        self.assertEqual(b"outside must not be read", outside.read_bytes())

    def test_persistence_is_exclusive_and_historical_reload_never_rereads_inputs(self) -> None:
        snapshot = capture(self.manifest(), self.root, "tenant-a")
        destination = self.root / "saved.json"
        save_snapshot(snapshot, destination)
        (self.root / "app.jar").write_bytes(b"later mutation")
        reloaded = load_snapshot(destination)
        self.assertEqual(snapshot, reloaded)
        with self.assertRaises(FileExistsError): save_snapshot(snapshot, destination)
        stored = json.loads(destination.read_text())
        stored["manifest"]["build"] = "tampered"
        (self.root / "tampered.json").write_text(json.dumps(stored))
        with self.assertRaises(ValueError): load_snapshot(self.root / "tampered.json")

    def test_load_snapshot_consumer_api_uses_absolute_path_and_stored_tenant(self) -> None:
        snapshot = capture(self.manifest(), self.root, "tenant-a")
        destination = self.root / "consumer-snapshot.json"
        save_snapshot(snapshot, destination)
        restored = load_snapshot(destination)
        self.assertEqual("tenant-a", restored.tenant)
        with self.assertRaisesRegex(ValueError, "absolute"):
            load_snapshot("consumer-snapshot.json")
        alias = self.root.parent / "snapshot-parent-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(alias.unlink, missing_ok=True)
        with self.assertRaises(ValueError):
            load_snapshot(alias / destination.name)

    def test_load_snapshot_rejects_invalid_stored_schema_and_tenant(self) -> None:
        snapshot = capture(self.manifest(), self.root, "tenant-a")
        destination = self.root / "saved.json"
        save_snapshot(snapshot, destination)
        stored = json.loads(destination.read_text())
        stored["schema"] = "unknown"
        invalid_schema = self.root / "invalid-schema.json"
        invalid_schema.write_text(json.dumps(stored))
        with self.assertRaises(ValueError):
            load_snapshot(invalid_schema)
        stored["schema"] = "jjamtong.build-snapshot.v1"
        stored["tenant"] = ""
        invalid_tenant = self.root / "invalid-tenant.json"
        invalid_tenant.write_text(json.dumps(stored))
        with self.assertRaises(ValueError):
            load_snapshot(invalid_tenant)

    def test_load_manifest_rejects_duplicate_json_key(self) -> None:
        (self.root / "manifest.json").write_bytes(b'{"schema":"jjamtong.build-manifest.v1","schema":"x"}')
        with self.assertRaises(ValueError): load_manifest("manifest.json", self.root, "tenant-a")

    def test_link_requires_explicit_exact_present_artifact(self) -> None:
        # The real bridge validates a full method-index v1 document before this
        # comparison; this test verifies the core's own no-selection shortcut.
        snapshot = capture(self.manifest(), self.root, "tenant-a")
        with self.assertRaises(ValueError):
            link_analysis(snapshot, {}, "app", "missing.jar", "a" * 64, "b" * 64)
        unknown = self.manifest()
        unknown["modules"][0]["artifacts"] = {"state": "not-applicable", "files": []}
        no_artifact = capture(unknown, self.root, "tenant-a")
        with self.assertRaises(ValueError):
            link_analysis(no_artifact, {}, "app", "app.jar", "a" * 64, "b" * 64)

    def test_link_requires_all_five_exact_v1_identity_fields(self) -> None:
        from tools.method_evidence.evidence import create_index, source_digest
        snapshot = capture(self.manifest(), self.root, "tenant-a")
        identity = {"repository": "example/repo", "revision": "r1", "build": "b1", "module": "app",
                    "artifactSha256": sha((self.root / "app.jar").read_bytes())}
        method = {"module": "app", "class": "fixture.Main", "name": "main", "descriptor": "()V"}
        source_root = self.root / "src"
        analysis = {"schema": "jjamtong.methods.v1", "module": "app", "metadata": identity,
                    "input": {"artifactSha256": identity["artifactSha256"], "sourceTreeSha256": source_digest(source_root)},
                    "scope": {"includePackage": "fixture"}, "provenance": {"adapterVersion": "test"},
                    "tools": {"javaparser": {"version": "test", "methods": [method], "calls": []},
                              "wala": {"version": "test", "methods": [method], "calls": []}}, "limitations": []}
        index = create_index(analysis, dict(identity, sourceState="clean", sourceFiles=[
            {"path": "Main.java", "sha256": sha((source_root / "Main.java").read_bytes())}]),
            self.root / "app.jar", source_root, "run-a")
        bridge = link_analysis(snapshot, index, "app", "app.jar", index["indexSha256"], index["configSha256"])
        self.assertEqual("app", dict(bridge.build_identity)["module"])
        with self.assertRaisesRegex(ValueError, "exact"):
            link_analysis(snapshot, index, "app", "app.jar", "0" * 64, index["configSha256"])
