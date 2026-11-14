"""Compile synthetic inputs, compare real adapters, and retain bounded measurements."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(root, build, module):
    sources = root / "sources"
    manifest = {
        "repository": "https://example.invalid/jjamtong-synthetic-analysis",
        "revision": hashlib.sha256(build.encode()).hexdigest()[:40],
        "build": build, "module": module, "artifactSha256": digest(root / "fixture.jar"),
        "sourceState": "clean",
        "sourceFiles": [{"path": p.relative_to(sources).as_posix(), "sha256": digest(p)}
                        for p in sorted(sources.rglob("*.java"))],
    }
    (root / "metadata.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")


def compile_fixture(root, java_home, module, build):
    files = sorted((root / "sources").rglob("*.java"))
    classes = root / "classes"
    classes.mkdir()
    started = time.monotonic()
    subprocess.run([str(java_home / "bin/javac"), "--release", "17", "-g", "-d", str(classes),
                    *map(str, files)], check=True, capture_output=True, timeout=150)
    compile_seconds = time.monotonic() - started
    with zipfile.ZipFile(root / "fixture.jar", "w") as archive:
        for path in sorted(classes.rglob("*.class")):
            entry = zipfile.ZipInfo(path.relative_to(classes).as_posix(), (2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    write_manifest(root, build, module)
    return {"sourceFiles": len(files), "actualLines": sum(len(p.read_text().splitlines()) for p in files),
            "artifactBytes": (root / "fixture.jar").stat().st_size, "compileSeconds": compile_seconds}


def scale_fixture(root, java_home, target_lines, module, variant=False):
    package = root / "sources/fixture/scale"
    package.mkdir(parents=True)
    count, total = 0, 0
    while total < target_lines:
        lines = ["package fixture.scale;", f"public final class Unit{count:04d} {{"]
        for method in range(20):
            rename = "Updated" if variant and count == 0 and method == 19 else ""
            lines += [f"  public static int m{method}{rename}(int value) {{", "    int result = value;"]
            lines += [f"    result = (result ^ {1 + count * 1000 + method * 43 + step}) + (result >>> 1);"
                      for step in range(42)]
            next_rename = "Updated" if variant and count == 0 and method + 1 == 19 else ""
            lines += [f"    return m{method + 1}{next_rename}(result);" if method < 19 else "    return result;", "  }"]
        lines += ["}"]
        (package / f"Unit{count:04d}.java").write_text("\n".join(lines) + "\n")
        total += len(lines)
        count += 1
    main = ["package fixture.scale;", "public final class Main {", "  public static void main(String[] args) {",
            "    int result = args.length;"]
    main += [f"    result += Unit{i:04d}.m0(result);" for i in range(count)]
    main += ["    if (result == 42) throw new IllegalStateException();", "  }", "}"]
    (package / "Main.java").write_text("\n".join(main) + "\n")
    return compile_fixture(root, java_home, module, f"{module}-{target_lines}-v{int(variant)}")


def structural_fixture(root, java_home, variant=False):
    package = root / "sources/fixture/legacy"
    package.mkdir(parents=True)
    sources = {
        "Main": '''public final class Main {
  public static void main(String[] args) throws Exception {
    Facade facade = new Facade(args.length == 0 ? new PrimaryStore() : new SecondaryStore());
    facade.query(1); facade.normalize(2); facade.normalize("2"); CycleA.step(2);
    Converter<String> converter = new StringConverter(); converter.convert("value");
    Runnable job = () -> facade.query(3); job.run(); Runnable ref = facade::background; ref.run();
    Reflective.invoke();
  }
}''',
        "Store": "public interface Store { String find(int id); }",
        "PrimaryStore": "public final class PrimaryStore implements Store { public String find(int id) { return Integer.toString(id); } }",
        "SecondaryStore": "public final class SecondaryStore implements Store { public String find(int id) { return Integer.toHexString(id); } }",
        "Facade": '''public final class Facade {
  private final Store store; public Facade(Store store) { this.store = store; }
  public String query(int id) { return store.find(id); }
  public int normalize(int value) { return fixture.legacy.shared.LegacyRules.normalize(value) + 1; }
  public String normalize(String value) { return value.trim(); }
  public void background() { query(4); }
  public String removed() { return query(5); }
}''',
        "CycleA": "public final class CycleA { public static int step(int n) { return n > 0 ? CycleB.step(n - 1) : n; } }",
        "CycleB": "public final class CycleB { public static int step(int n) { return n > 0 ? CycleA.step(n - 1) : n; } }",
        "Converter": "public interface Converter<T> { T convert(T value); }",
        "StringConverter": "public final class StringConverter implements Converter<String> { public String convert(String value) { return value.trim(); } }",
        "Reflective": '''public final class Reflective {
  public static void invoke() throws Exception {
    Class.forName("fixture.legacy.Hidden").getDeclaredMethod("legacy").invoke(null);
  }
}''',
        "Hidden": "public final class Hidden { public static int legacy() { return 42; } }",
    }
    if variant:
        sources["Facade"] = sources["Facade"].replace("  public String removed() { return query(5); }\n", "")
    for name, body in sources.items():
        (package / f"{name}.java").write_text("package fixture.legacy;\n" + body + "\n")
    shared = package / "shared"
    shared.mkdir()
    (shared / "LegacyRules.java").write_text(
        "package fixture.legacy.shared;\npublic final class LegacyRules { public static int normalize(int value) { return value; } }\n")
    return compile_fixture(root, java_home, "legacy-fixture", f"legacy-v{int(variant)}")


def command(root, java_home, module, package, output, cache=None):
    common = ["--java-home", str(java_home), "--source-root", str(root / "sources"),
              "--artifact", str(root / "fixture.jar"), "--metadata", str(root / "metadata.json"),
              "--module", module, "--include-package", package, "--entrypoint", package + ".Main", "--output", str(output)]
    if cache is None:
        return [sys.executable, str(ROOT / "tools/java-call-analysis/analyze.py"), *common]
    return [sys.executable, "-m", "tools.analysis_reuse", "--tenant", "synthetic-local", "--cache", str(cache), *common]


def measure(command_, log):
    timer = Path("/usr/bin/time")
    measured = timer.is_file() and platform.system() in ("Darwin", "Linux")
    prefix = [str(timer), "-l" if platform.system() == "Darwin" else "-v"] if measured else []
    started = time.monotonic()
    with log.open("w") as errors:
        process = subprocess.Popen([*prefix, *command_], cwd=ROOT, stdout=subprocess.PIPE, stderr=errors,
                                   text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=100)
        except subprocess.TimeoutExpired:
            # The adapter owns a stricter 60 s JVM deadline. This outer deadline
            # bounds orchestration as well; inputs/output stay in this owned directory.
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return {"success": False, "failure": "outer-deadline", "wallSeconds": time.monotonic() - started}
    detail = log.read_text()
    rss = re.search(r"(\d+)\s+maximum resident set size", detail) if platform.system() == "Darwin" else re.search(
        r"Maximum resident set size \(kbytes\):\s*(\d+)", detail)
    result = {"success": process.returncode == 0, "exitCode": process.returncode,
              "wallSeconds": time.monotonic() - started,
              "peakProcessRssBytes": int(rss[1]) * (1024 if platform.system() == "Linux" else 1) if rss else None}
    if process.returncode:
        result["failure"] = ("output-cap" if "10 MiB" in detail or "output limit" in detail.lower() else
                             "jvm-heap" if "OutOfMemoryError" in detail else
                             "adapter-deadline" if "TimeoutExpired" in detail else "analysis-error")
    elif "--cache" in command_:
        result["receipt"] = json.loads(stdout)
    return result


def semantic(path):
    value = json.loads(path.read_text())
    value.pop("metadata")
    value["input"].pop("metadataInputSha256")
    return value


def inventory(path):
    value = json.loads(path.read_text())
    return {name: {"methods": len(tool["methods"]), "calls": len(tool["calls"]),
                   "unresolved": len(tool["unresolved"])} for name, tool in value["tools"].items()}


def compare(root, changed, java_home, module, package, cache):
    stages = {}
    for name, fixture, direct in (("cold", root, False), ("warm", root, False),
                                  ("changed", changed, False), ("reference", changed, True)):
        out = root / f"{name}.json"
        stages[name] = measure(command(fixture, java_home, module, package, out, None if direct else cache), root / f"{name}.log")
        stages[name]["outputPublished"] = out.exists()
        if stages[name]["success"]:
            stages[name]["outputBytes"] = out.stat().st_size
            stages[name]["inventory"] = inventory(out)
        else:
            # A bounded failure is a result; don't retry the same oversized unit.
            assert not out.exists(), "failed stage published output"
            return {"stages": stages, "equality": None}
        if name == "cold":
            # Same content under a new build: warm output must carry new provenance.
            write_manifest(root, module + "-new-build-same-input", module)
    equal = semantic(root / "cold.json") == semantic(root / "warm.json") and semantic(root / "changed.json") == semantic(root / "reference.json")
    warm_metadata = json.loads((root / "warm.json").read_text())["metadata"]
    assert warm_metadata["build"] == module + "-new-build-same-input"
    assert equal, "reuse or changed analysis differs from independent full result"
    assert stages["cold"]["receipt"]["status"] == "analyzed"
    assert stages["warm"]["receipt"]["status"] == "reused"
    assert stages["changed"]["receipt"]["status"] == "analyzed"
    if package == "fixture.scale":
        changed_tools = json.loads((root / "changed.json").read_text())["tools"]
        for tool in changed_tools.values():
            names = {m["name"] for m in tool["methods"] if m["class"] == "fixture.scale.Unit0000"}
            assert "m19Updated" in names and "m19" not in names
    return {"stages": stages, "equality": equal}


def structural_assertions(root):
    value = json.loads((root / "cold.json").read_text())
    tools = value["tools"]
    def edge(tool, caller_class, caller_name, target_class, target_name):
        return any(c["caller"]["class"] == "fixture.legacy." + caller_class and c["caller"]["name"] == caller_name
                   and c["target"]["class"] == "fixture.legacy." + target_class and c["target"]["name"] == target_name
                   for c in tools[tool]["calls"])
    checks = {
        "interfaceDeclaration": edge("javaparser", "Facade", "query", "Store", "find"),
        "twoImplementationCandidates": all(edge("wala", "Facade", "query", impl, "find") for impl in ("PrimaryStore", "SecondaryStore")),
        "cycleRetained": edge("wala", "CycleA", "step", "CycleB", "step") and edge("wala", "CycleB", "step", "CycleA", "step"),
        "overloadsDistinct": len({m["descriptor"] for m in tools["javaparser"]["methods"]
                                  if m["class"] == "fixture.legacy.Facade" and m["name"] == "normalize"}) == 2,
        "reflectionGapReported": any(x["reason"] == "reflection-target-not-inferred" for x in tools["javaparser"]["unresolved"]),
        "noInventedReflectionEdge": not edge("wala", "Reflective", "invoke", "Hidden", "legacy"),
        "lambdaGapReported": any(x["reason"] == "lambda-body-not-attributed-to-enclosing-method" for x in tools["javaparser"]["unresolved"]),
        "methodReferenceGapReported": any(x["reason"] == "method-reference-not-expanded" for x in tools["javaparser"]["unresolved"]),
        "compilerBridgeDistinct": len({m["descriptor"] for m in tools["wala"]["methods"]
                                       if m["class"] == "fixture.legacy.StringConverter" and m["name"] == "convert"}) == 2,
        "crossPackageCandidate": edge("wala", "Facade", "normalize", "shared.LegacyRules", "normalize"),
    }
    changed = json.loads((root / "changed.json").read_text())
    checks["removedMethodAbsent"] = all(not any(m["name"] == "removed" for m in tool["methods"]) for tool in changed["tools"].values())
    assert all(checks.values()), checks
    return checks


def modular_update(output, java_home, cache):
    """Change one independent unit, reuse two, and compare the changed unit in full."""
    changed = output / "module-0-changed"
    scale_fixture(changed, java_home, 100000, "module-0", True)
    stages = []
    for i in range(3):
        root = changed if i == 0 else output / f"module-{i}"
        if i:
            write_manifest(root, f"module-{i}-next-build", f"module-{i}")
        stage = measure(command(root, java_home, f"module-{i}", "fixture.scale", root / "next.json", cache), root / "next.log")
        assert stage["success"], stage
        assert stage["receipt"]["status"] == ("analyzed" if i == 0 else "reused")
        if i:
            assert semantic(root / "next.json") == semantic(root / "cold.json")
        stages.append(stage)
    reference = measure(command(changed, java_home, "module-0", "fixture.scale", changed / "reference.json"), changed / "reference.log")
    assert reference["success"], reference
    assert semantic(changed / "next.json") == semantic(changed / "reference.json")
    return {"stages": stages, "reference": reference, "reusedUnits": 2, "totalUnits": 3, "equality": True}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="*", default=[100000, 300000])
    parser.add_argument("--modular", action="store_true", help="also compare three independent 100k-line analysis units")
    args = parser.parse_args()
    args.output = args.output.resolve(); args.java_home = args.java_home.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "jjamtong.analysis-reuse-experiment.v1", "synthetic": True,
              "environment": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version(),
                              "logicalCpus": os.cpu_count(), "javaRelease": next(line.split("=", 1)[1].strip('"') for line in
                                  (args.java_home / "release").read_text().splitlines() if line.startswith("JAVA_VERSION="))},
              "limits": {"jvmHeapBytes": 1073741824, "adapterSeconds": 60, "outputBytes": 10485760}, "cases": {}}
    cache = args.output / "cache"
    for size in args.sizes:
        module = f"scale-{size}"
        root, changed = args.output / module, args.output / (module + "-changed")
        info = scale_fixture(root, args.java_home, size, module)
        scale_fixture(changed, args.java_home, size, module, True)
        result["cases"][module] = {"input": info, **compare(root, changed, args.java_home, module, "fixture.scale", cache)}
        print(module, json.dumps(result["cases"][module]), flush=True)
    root, changed = args.output / "legacy", args.output / "legacy-changed"
    info = structural_fixture(root, args.java_home)
    structural_fixture(changed, args.java_home, True)
    result["cases"]["legacy"] = {"input": info, **compare(root, changed, args.java_home, "legacy-fixture", "fixture.legacy", cache)}
    if result["cases"]["legacy"]["equality"]:
        result["cases"]["legacy"]["checks"] = structural_assertions(root)
    if args.modular:
        units = []
        for i in range(3):
            module = f"module-{i}"
            root = args.output / module
            info = scale_fixture(root, args.java_home, 100000, module)
            stages = {}
            for name in ("cold", "warm"):
                stages[name] = measure(command(root, args.java_home, module, "fixture.scale", root / (name + ".json"), cache), root / (name + ".log"))
                assert stages[name]["success"], stages[name]
            units.append({"input": info, "stages": stages})
        result["modular"] = {"independentUnits": units, "crossUnitGraphMerge": False,
                             "nextBuild": modular_update(args.output, args.java_home, cache)}
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print("results", args.output / "results.json", flush=True)


if __name__ == "__main__":
    main()
