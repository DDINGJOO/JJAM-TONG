"""Independent fixtures for bounded, declared build discovery."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from tools.build_inventory import discovery


class _Reader:
    files: dict[str, bytes] = {}

    def __init__(self, _root, **_limits):
        self.checked_files = self.checked_bytes = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read_bytes(self, path, *, max_bytes):
        if path not in self.files:
            raise FileNotFoundError(path)
        data = self.files[path]
        if len(data) > max_bytes:
            raise ValueError("descriptor too large")
        self.checked_files += 1
        self.checked_bytes += len(data)
        return data


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


class DiscoveryTests(unittest.TestCase):
    def test_real_kotlin_only_settings_and_missing_module_build_are_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "settings.gradle.kts").write_text('include("api")')
            result = discovery.discover_gradle(root)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual([":", ":api"], [item["id"] for item in result["candidates"]])

    def test_real_maven_only_root_is_not_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "pom.xml").write_text("<project><artifactId>only</artifactId></project>")
            result = discovery.discover(root)
        self.assertEqual("maven", result["adapter"])
        self.assertEqual("OK", result["status"])

    def run_discovery(self, files, function, *args, **kwargs):
        _Reader.files = files
        with patch.object(discovery, "SafeReader", _Reader):
            return function("fixture-root", *args, **kwargs)

    def test_utf16_dtd_cannot_bypass_descriptor_rejection(self):
        data = "<!DOCTYPE project [<!ENTITY x 'expanded'>]><project><artifactId>&x;</artifactId></project>".encode("utf-16")
        result = self.run_discovery({"pom.xml": data}, discovery.discover_maven)
        self.assertEqual("INVALID", result["status"])
        self.assertEqual([], result["candidates"])

    def test_maven_property_module_is_unresolved_not_a_missing_literal_module(self):
        data = b"<project><modules><module>${selected}</module></modules></project>"
        result = self.run_discovery({"pom.xml": data}, discovery.discover_maven)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(["pom.xml"], [x["descriptorPath"] for x in result["candidates"]])
        self.assertTrue(any("unresolved" in item["reason"] for item in result["gaps"]))

    def test_maven_bounds_queued_modules_before_reading_children(self):
        data = b"<project><modules><module>a</module><module>b</module><module>c</module></modules></project>"
        with patch.object(discovery, "MAX_MODULES", 2):
            with patch.object(discovery, "_join", wraps=discovery._join) as expand:
                result = self.run_discovery({"pom.xml": data}, discovery.discover_maven)
        self.assertLessEqual(expand.call_count, 2)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(["pom.xml", "a/pom.xml"], [x["descriptorPath"] for x in result["candidates"]])
        self.assertIn("module limit reached", result["limitations"])

    def test_gradle_unprefixed_literal_ids_are_normalized_before_matching_remap(self):
        data = b"include 'api', ':shared'\nproject('api').projectDir = file('services/api')\n"
        result = self.run_discovery({"settings.gradle": data, "build.gradle": b"",
                                     "services/api/build.gradle": b"", "shared/build.gradle": b""},
                                    discovery.discover_gradle)
        self.assertEqual("OK", result["status"])
        self.assertEqual([":", ":api", ":shared"], [x["id"] for x in result["candidates"]])
        self.assertEqual("services/api", result["candidates"][1]["projectDir"])

    def test_gradle_quoted_comma_in_remap_is_one_literal(self):
        data = b"include(\"api\")\nproject(\"api\").projectDir = file(\"services/api,worker\")"
        result = self.run_discovery({"settings.gradle.kts": data, "build.gradle.kts": b"",
                                     "services/api,worker/build.gradle.kts": b""}, discovery.discover_gradle)
        self.assertEqual("OK", result["status"])
        self.assertEqual("services/api,worker", result["candidates"][1]["projectDir"])

    def test_gradle_unknown_settings_code_is_not_silently_accepted(self):
        data = b"include(':api')\nconfigureOtherModules()\n"
        result = self.run_discovery({"settings.gradle": data, "build.gradle": b"", "api/build.gradle": b""},
                                    discovery.discover_gradle)
        self.assertEqual("PARTIAL", result["status"])

    def test_maven_root_children_cycle_and_missing_descriptor_are_literal(self):
        root = b"<project><groupId>demo</groupId><artifactId>root</artifactId><modules><module>api</module><module>lib</module><module>api</module></modules></project>"
        api = b"<project><artifactId>api</artifactId><modules><module>../lib</module></modules></project>"
        result = self.run_discovery({"pom.xml": root, "api/pom.xml": api}, discovery.discover_maven)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(
            ["pom.xml", "api/pom.xml", "lib/pom.xml"],
            [candidate["descriptorPath"] for candidate in result["candidates"]],
        )
        self.assertEqual(_digest(root), result["candidates"][0]["descriptorSha256"])
        self.assertEqual("demo:root", result["candidates"][0]["declaredArtifactId"])
        self.assertEqual({"path": "api/pom.xml", "reason": "duplicate or cycle declaration"}, result["gaps"][0])
        self.assertEqual({"path": "lib/pom.xml", "reason": "duplicate or cycle declaration"}, result["gaps"][1])
        self.assertEqual({"path": "lib/pom.xml", "reason": "declared module descriptor missing"}, result["gaps"][2])

    def test_maven_rejects_dtd_and_path_escape_without_candidates(self):
        dtd = b"<!DOCTYPE project [<!ENTITY x 'x'>]><project><artifactId>&x;</artifactId></project>"
        invalid = self.run_discovery({"pom.xml": dtd}, discovery.discover_maven)
        self.assertEqual("INVALID", invalid["status"])
        self.assertEqual([], invalid["candidates"])
        escaped = self.run_discovery({"pom.xml": b"<project><modules><module>../../outside</module></modules></project>"}, discovery.discover_maven)
        self.assertEqual("PARTIAL", escaped["status"])
        self.assertEqual({"path": "../../outside", "reason": "module path escapes root or is invalid"}, escaped["gaps"][0])

    def test_gradle_literal_top_level_include_and_remap(self):
        settings = b"""// a decoy include(':ignored')
include(':api', ':common');
include ':nested:worker'
project(':api').projectDir = file('services/api')
"""
        result = self.run_discovery({
            "settings.gradle": settings, "build.gradle": b"", "services/api/build.gradle": b"api",
            "common/build.gradle.kts": b"common", "nested/worker/build.gradle": b"worker",
        }, discovery.discover_gradle)
        self.assertEqual("OK", result["status"])
        self.assertEqual("settings.gradle", result["settingsPath"])
        self.assertEqual(_digest(settings), result["settingsSha256"])
        self.assertEqual(
            [(":", "", "build.gradle"), (":api", "services/api", "services/api/build.gradle"),
             (":common", "common", "common/build.gradle.kts"), (":nested:worker", "nested/worker", "nested/worker/build.gradle")],
            [(item["id"], item["projectDir"], item["buildFilePath"]) for item in result["candidates"]],
        )

    def test_gradle_dynamic_and_scoped_forms_are_never_extracted(self):
        settings = b"""if (enabled) { include(':hidden') }
def names = [':variable']
include(names)
includeBuild('other')
plugins { id 'x' }
apply from: 'settings-extra.gradle'
"""
        result = self.run_discovery({"settings.gradle": settings, "build.gradle": b""}, discovery.discover_gradle)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual([":"], [item["id"] for item in result["candidates"]])
        self.assertTrue(any("unsupported" in item for item in result["limitations"]))

    def test_auto_requires_explicit_choice_for_dual_descriptors(self):
        result = self.run_discovery({"pom.xml": b"<project/>", "settings.gradle": b"", "build.gradle": b""}, discovery.discover)
        self.assertEqual("AMBIGUOUS", result["status"])
        self.assertEqual("auto", result["adapter"])
        self.assertEqual("maven", result["adapters"]["maven"]["adapter"])
        self.assertEqual("gradle", result["adapters"]["gradle"]["adapter"])

    def test_no_build_sentinel_does_not_execute_or_infer_a_build(self):
        result = self.run_discovery({}, discovery.discover)
        self.assertEqual("NOT_FOUND", result["status"])
        self.assertEqual([], result["candidates"])


if __name__ == "__main__":
    unittest.main()
