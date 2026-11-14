"""Bounded, read-only discovery of declared Maven and Gradle build candidates."""

from __future__ import annotations

from hashlib import sha256
import posixpath
import re
from typing import Any
import xml.etree.ElementTree as ElementTree

from .inventory import SafeReader, canonical_path


MAX_DESCRIPTOR_BYTES = 1024 * 1024
MAX_MODULES = 1000
MAX_DEPTH = 32
MODE = "DECLARED_CANDIDATES"


def _result(adapter: str, status: str = "OK", **values: Any) -> dict[str, Any]:
    return {"adapter": adapter, "mode": MODE, "status": status, **values}


def _relative_path(value: str) -> str:
    """Normalize a descriptor-relative literal without permitting root escape."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    normalized = posixpath.normpath(value)
    if normalized in (".", "..") or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError("path escapes discovery root")
    # The core helper is the final canonical-path gate used by SafeReader.
    return canonical_path(normalized)


def _join(base: str, literal: str) -> str:
    return _relative_path(posixpath.join(base, literal))


def _read(reader: SafeReader, path: str) -> bytes:
    try:
        return reader.read_bytes(path, max_bytes=MAX_DESCRIPTOR_BYTES)
    except ValueError as error:
        # Missing optional descriptors are discovery gaps; all other secure
        # reader failures (including symlinks and permissions) stay invalid.
        if isinstance(error.__cause__, FileNotFoundError):
            raise FileNotFoundError(path) from error
        raise


def _xml_child(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == name:
            return (child.text or "").strip() or None
    return None


def _maven_descriptor(data: bytes, path: str) -> tuple[dict[str, Any], list[str], list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Maven descriptors must be UTF-8") from error
    if "\x00" in text:
        raise ValueError("Maven descriptors must be UTF-8 without NUL bytes")
    encoding = re.search(r"<\?xml\b[^?]*\bencoding\s*=\s*['\"]([^'\"]+)", text, re.I)
    if encoding and encoding.group(1).lower() not in ("utf-8", "utf8"):
        raise ValueError("Maven descriptor encoding is unsupported")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML DTD/entity declarations are not supported")
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, UnicodeDecodeError) as error:
        raise ValueError("invalid Maven XML") from error
    artifact_id = _xml_child(root, "artifactId")
    group_id = _xml_child(root, "groupId")
    declared_id = f"{group_id}:{artifact_id}" if group_id and artifact_id else artifact_id
    module_literals: list[str] = []
    limitations: list[str] = []
    for child in root:
        local = child.tag.rsplit("}", 1)[-1]
        if local == "modules":
            for module in child:
                if module.tag.rsplit("}", 1)[-1] == "module":
                    value = (module.text or "").strip()
                    if value:
                        module_literals.append(value)
                    else:
                        limitations.append("empty module declaration")
        elif local in {"profiles", "properties", "parent", "build"}:
            limitations.append(f"{local} is not evaluated")
    candidate = {
        "descriptorPath": path,
        "descriptorSha256": sha256(data).hexdigest(),
        "declaredArtifactId": declared_id,
        "packaging": _xml_child(root, "packaging"),
        "modulePaths": module_literals,
    }
    return candidate, module_literals, limitations


def discover_maven(root: str, entry: str = "pom.xml") -> dict[str, Any]:
    """Discover literal Maven aggregator modules without evaluating a POM."""
    try:
        entry_path = _relative_path(entry)
    except ValueError as error:
        return _result("maven", "INVALID", candidates=[], gaps=[str(error)], limitations=[])
    candidates: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    limitations = [
        "declared POM data only; effective model is not evaluated",
        "properties, profiles, inheritance, plugins, dependencies, artifacts, classpath, and runtime are unresolved",
    ]
    pending: list[tuple[str, int]] = [(entry_path, 0)]
    queued: set[str] = {entry_path}
    visited: set[str] = set()
    try:
        with SafeReader(root) as reader:
            while pending:
                descriptor, depth = pending.pop(0)
                if descriptor in visited:
                    gaps.append({"path": descriptor, "reason": "duplicate or cycle declaration"})
                    continue
                if len(visited) >= MAX_MODULES:
                    return _result("maven", "PARTIAL", candidates=candidates, gaps=gaps,
                                   limitations=limitations + ["module limit reached"])
                if depth > MAX_DEPTH:
                    gaps.append({"path": descriptor, "reason": "depth limit reached"})
                    continue
                visited.add(descriptor)
                try:
                    data = _read(reader, descriptor)
                except FileNotFoundError:
                    if descriptor == entry_path:
                        return _result("maven", "NOT_FOUND", candidates=[], gaps=[{"path": descriptor, "reason": "descriptor missing"}], limitations=limitations)
                    candidates.append({"descriptorPath": descriptor, "descriptorStatus": "MISSING"})
                    gaps.append({"path": descriptor, "reason": "declared module descriptor missing"})
                    continue
                candidate, module_literals, local_limits = _maven_descriptor(data, descriptor)
                candidates.append(candidate)
                limitations.extend(local_limits)
                parent = posixpath.dirname(descriptor)
                for literal in module_literals:
                    if len(queued) >= MAX_MODULES:
                        limitations.append("module limit reached")
                        gaps.append({"path": descriptor, "reason": "module expansion limit reached"})
                        break
                    if "${" in literal:
                        gaps.append({"path": literal, "reason": "module property expression is unresolved"})
                        continue
                    try:
                        module_dir = _join(parent, literal)
                    except ValueError:
                        gaps.append({"path": literal, "reason": "module path escapes root or is invalid"})
                        continue
                    child = _join(module_dir, "pom.xml")
                    if child in queued or child in visited:
                        gaps.append({"path": child, "reason": "duplicate or cycle declaration"})
                        continue
                    queued.add(child)
                    pending.append((child, depth + 1))
    except (ValueError, OSError, UnicodeError) as error:
        return _result("maven", "INVALID", candidates=[], gaps=[{"path": entry_path, "reason": str(error)}], limitations=limitations)
    return _result("maven", "PARTIAL" if gaps else "OK", candidates=candidates, gaps=gaps,
                   limitations=sorted(set(limitations)))


def _strip_comments(source: str) -> str:
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote:
            output.append(char)
            if char == "\\" and index + 1 < len(source):
                output.append(source[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "\"'":
            quote = char
            output.append(char)
            index += 1
        elif source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            output.extend(" " if part != "\n" else "\n" for part in source[index:end])
            index = end
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated block comment")
            end += 2
            output.extend("\n" if part == "\n" else " " for part in source[index:end])
            index = end
        else:
            output.append(char)
            index += 1
    if quote:
        raise ValueError("unterminated string")
    return "".join(output)


def _top_level_statements(source: str) -> tuple[list[str], list[str]]:
    source = _strip_comments(source)
    statements: list[str] = []
    unsupported: list[str] = []
    start = 0
    braces = parentheses = 0
    quote: str | None = None
    index = 0
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "\"'":
            if source.startswith(char * 3, index):
                unsupported.append("triple-quoted string is unresolved")
            quote = char
        elif char == "{":
            braces += 1
        elif char == "}":
            braces = max(0, braces - 1)
        elif char == "(":
            parentheses += 1
        elif char == ")":
            parentheses = max(0, parentheses - 1)
        boundary = char == ";" or (char == "\n" and parentheses == 0)
        if boundary and braces == 0:
            statement = source[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    tail = source[start:].strip()
    if tail and braces == 0:
        statements.append(tail)
    if braces or parentheses:
        unsupported.append("unbalanced or scoped settings expression is unresolved")
    return statements, unsupported


_LITERAL = r"(?:'[^'\\\n]*'|\"[^\"\\\n$]*\")"
_INCLUDE_PARENS = re.compile(rf"^include\s*\(\s*({_LITERAL}(?:\s*,\s*{_LITERAL})*)\s*\)$", re.S)
_INCLUDE_GROOVY = re.compile(rf"^include\s+({_LITERAL}(?:\s*,\s*{_LITERAL})*)$", re.S)
_REMAP = re.compile(rf"^project\s*\(\s*({_LITERAL})\s*\)\s*\.\s*projectDir\s*=\s*file\s*\(\s*({_LITERAL})\s*\)$", re.S)
_ROOT_NAME = re.compile(rf"^rootProject\s*\.\s*name\s*=\s*{_LITERAL}$", re.S)


def _literals(value: str) -> list[str]:
    return [match.group(0)[1:-1] for match in re.finditer(_LITERAL, value)]


def _project_id(value: str) -> str:
    return value if value.startswith(":") else ":" + value


def _gradle_build_path(reader: SafeReader, project_dir: str) -> tuple[str | None, str | None]:
    for filename in ("build.gradle", "build.gradle.kts"):
        path = _join(project_dir, filename) if project_dir else filename
        try:
            data = _read(reader, path)
        except FileNotFoundError:
            continue
        return path, sha256(data).hexdigest()
    return None, None


def discover_gradle(root: str, entry: str | None = None) -> dict[str, Any]:
    """Discover only literal, top-level Gradle settings declarations."""
    requested = [entry] if entry else ["settings.gradle", "settings.gradle.kts"]
    limitations = [
        "declared settings literals only; Gradle settings are not executed",
        "dependencies, artifacts, classpath, toolchain, conditions, and runtime are unresolved",
    ]
    try:
        with SafeReader(root) as reader:
            settings_path = None
            data = None
            for requested_path in requested:
                path = _relative_path(requested_path)
                try:
                    data = _read(reader, path)
                    settings_path = path
                    break
                except FileNotFoundError:
                    continue
            if settings_path is None or data is None:
                root_build, root_hash = _gradle_build_path(reader, "")
                if root_build:
                    return _result("gradle", "PARTIAL", settingsPath=None,
                                   candidates=[{"id": ":", "projectDir": "", "buildFilePath": root_build,
                                                "buildFileSha256": root_hash}], gaps=[],
                                   limitations=limitations + ["settings descriptor missing; root build file only"])
                return _result("gradle", "NOT_FOUND", candidates=[], gaps=[{"path": requested[0], "reason": "settings and root build descriptors missing"}], limitations=limitations)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Gradle settings must be UTF-8") from error
            statements, unresolved = _top_level_statements(text)
            projects: list[str] = []
            remaps: dict[str, str] = {}
            for statement in statements:
                match = _INCLUDE_PARENS.fullmatch(statement) or _INCLUDE_GROOVY.fullmatch(statement)
                if match:
                    projects.extend(_project_id(value) for value in _literals(match.group(1)))
                    continue
                match = _REMAP.fullmatch(statement)
                if match:
                    remaps[_project_id(_literals(match.group(1))[0])] = _literals(match.group(2))[0]
                    continue
                if not _ROOT_NAME.fullmatch(statement):
                    unresolved.append("unsupported top-level Gradle settings statement")
            candidates: list[dict[str, Any]] = []
            gaps: list[dict[str, str]] = []
            seen: set[str] = set()
            root_build, root_hash = _gradle_build_path(reader, "")
            candidates.append({"id": ":", "projectDir": "", "buildFilePath": root_build,
                               "buildFileSha256": root_hash})
            if root_build is None:
                gaps.append({"path": "", "reason": "root build file missing"})
            for project in projects:
                if not project.startswith(":") or project in (":",) or project in seen or "::" in project:
                    gaps.append({"path": project, "reason": "unsafe, empty, or duplicate project path"})
                    continue
                seen.add(project)
                if len(seen) > MAX_MODULES:
                    unresolved.append("module limit reached")
                    break
                default_dir = project[1:].replace(":", "/")
                try:
                    project_dir = _relative_path(remaps.get(project, default_dir))
                except ValueError:
                    gaps.append({"path": project, "reason": "project directory escapes root or is invalid"})
                    continue
                build_path, build_hash = _gradle_build_path(reader, project_dir)
                candidate = {"id": project, "projectDir": project_dir, "buildFilePath": build_path,
                             "buildFileSha256": build_hash}
                candidates.append(candidate)
                if build_path is None:
                    gaps.append({"path": project_dir, "reason": "declared module build file missing"})
            status = "PARTIAL" if gaps or unresolved else "OK"
            return _result("gradle", status, settingsPath=settings_path,
                           settingsSha256=sha256(data).hexdigest(), candidates=candidates, gaps=gaps,
                           limitations=sorted(set(limitations + unresolved)))
    except (ValueError, OSError, UnicodeError) as error:
        return _result("gradle", "INVALID", candidates=[], gaps=[{"path": entry or "settings.gradle", "reason": str(error)}], limitations=limitations)


def discover(root: str, adapter: str | None = None, entry: str | None = None) -> dict[str, Any]:
    """Select an explicit adapter or report an ambiguous dual build declaration."""
    if adapter == "maven":
        return discover_maven(root, entry or "pom.xml")
    if adapter == "gradle":
        return discover_gradle(root, entry)
    if adapter is not None:
        return _result(str(adapter), "INVALID", candidates=[], gaps=[{"path": "", "reason": "unknown adapter"}], limitations=[])
    maven = discover_maven(root, "pom.xml")
    gradle = discover_gradle(root, entry)
    maven_found = maven["status"] != "NOT_FOUND"
    gradle_found = gradle["status"] != "NOT_FOUND"
    if maven_found and gradle_found:
        return _result("auto", "AMBIGUOUS", candidates=[], gaps=[], limitations=["both Maven and Gradle descriptors are present; select an adapter"], adapters={"maven": maven, "gradle": gradle})
    if maven_found:
        return maven
    if gradle_found:
        return gradle
    return _result("auto", "NOT_FOUND", candidates=[], gaps=[{"path": "", "reason": "no Maven or Gradle descriptor found"}], limitations=[])
