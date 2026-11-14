"""Independent source-to-UI expectations; the target application is never run."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from .workspace import SourceWorkspace

REPO = Path(__file__).resolve().parents[2]
JAVA_HOME = Path(os.environ.get("JJAMTONG_TEST_JAVA_HOME", "/Library/Java/JavaVirtualMachines/amazon-corretto-21.jdk/Contents/Home"))


@unittest.skipUnless((JAVA_HOME / "bin/javac").is_file(), "An explicit JDK 21 installation is required")
class CollectorContractTests(unittest.TestCase):
    def test_source_routes_call_identity_and_branch_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "app"
            package = root / "web/src/main/java/sample"
            package.mkdir(parents=True)
            (package / "Api.java").write_text('''package sample;
import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping(path={"/v1", "/v2"})
class Api {
  private String name;
  @GetMapping(path={"/posts/{id}", "/entries/{id}"})
  public String read(String id) {
    if (allowed()) return helper(id);
    else return helper(2);
  }
  @GetMapping public String health() { return "ok"; }
  @RequestMapping(path="/write", method={RequestMethod.POST, RequestMethod.PUT})
  public void write() { System.out.println("must-never-serialize"); }
  public void unmapped() { helper(1); }
  private boolean allowed() { return true; }
  private String helper(String value) { return value; }
  private String helper(int value) { return "x"; }
  public String getName() { return name; }
  public String compute() { return helper("must-never-serialize"); }
  public void deferred() { Runnable r = () -> helper(4); }
  public void guarded() {
    if ("must-never-serialize\\\"escape".isEmpty()) helper(3);
  }
  public void textBlockGuarded() {
    if (("""
must-never-serialize-text-block
""").isEmpty()) helper(5);
  }
}
interface Contract { String query(); }
''', encoding="utf-8")
            (package / "Other.java").write_text('''package sample;
@interface FakeMapping { }
class Other { @FakeMapping public void notHttp() { } }
''')
            output = Path(temp) / "snapshot.json"
            run = subprocess.run(["python3", "-m", "tools.service_analysis.collect", "--source", str(root),
                                  "--output", str(output), "--java-home", str(JAVA_HOME), "--deadline", "40"],
                                 cwd=REPO, text=True, capture_output=True, timeout=80)
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])
            data = json.loads(output.read_text())
            workspace = SourceWorkspace(output)  # Every edge must resolve to a known source node.
            routes = data["endpoints"]
            self.assertEqual(len(routes), 10)
            self.assertEqual({r["httpMethod"] for r in routes}, {"GET", "POST", "PUT"})
            self.assertTrue(all(r["resolution"] == "literal" for r in routes))
            methods = {m["id"]: m for m in data["methods"]}
            self.assertEqual({methods[r["handlerId"]]["name"] for r in routes}, {"read", "health", "write"})
            self.assertTrue(all(m["path"].startswith("web/src/main/java/") for m in methods.values()))
            read = next(m for m in methods.values() if m["name"] == "read")
            edges = workspace.graph({"method_id": read["id"]})["edges"]
            helper_edges = [e for e in edges if methods[e["target"]]["name"] == "helper"]
            self.assertEqual(len({e["target"] for e in helper_edges}), 2, "Overloads need exact distinct identities")
            self.assertEqual({s["conditions"][0]["branch"] for e in helper_edges for s in e["sites"]}, {"then", "else"})
            predicate_edges = [e for e in edges if methods[e["target"]]["name"] == "allowed"]
            self.assertEqual(len(predicate_edges), 1)
            self.assertEqual(predicate_edges[0]["sites"][0]["conditions"], [], "Evaluating a predicate does not take its branch")
            deferred = next(m for m in methods.values() if m["name"] == "deferred")
            self.assertEqual(workspace.graph({"method_id": deferred["id"]})["edges"], [], "Lambda execution is not its enclosing method's execution")
            query = next(m for m in methods.values() if m["name"] == "query")
            self.assertTrue(query["abstract"])
            self.assertFalse(data.get("diagnostics", {}).get(query["id"]), "An interface declaration is valid")
            compute = next(m for m in methods.values() if m["name"] == "compute")
            self.assertNotIn("simple-accessor", compute["noiseReasons"])
            self.assertNotIn("must-never-serialize", output.read_text())
            text_block = next(m for m in methods.values() if m["name"] == "textBlockGuarded")
            text_block_call = next(c for c in data["calls"] if c["source"] == text_block["id"] and c["expression"] == "helper(…)")
            self.assertIn("<text-block>", text_block_call["conditions"][0]["expression"])
            provenance = data["provenance"]
            self.assertEqual(provenance["analyzerImplementationSha256"], hashlib.sha256((REPO / "tools/service_analysis/SourceIndex.java").read_bytes()).hexdigest())
            self.assertEqual(provenance["launcherImplementationSha256"], hashlib.sha256((REPO / "tools/service_analysis/collect.py").read_bytes()).hexdigest())
            self.assertGreater(data["metrics"]["maxRssBytes"], 0)
            calls = data["calls"]
            self.assertTrue(any(c["resolution"] == "EXTERNAL_DECLARATION" for c in calls))
            self.assertTrue(any(c["resolution"] == "DEFERRED_LAMBDA" for c in calls))
            self.assertTrue(all("line" in c and "expression" in c for c in calls))

    def test_parse_failure_keeps_relative_path_and_does_not_mutate_previous_output_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "app"
            package = root / "mod/src/main/java/example"
            package.mkdir(parents=True)
            (package / "Broken.java").write_text("package example; class Broken { void missing( }")
            output = Path(temp) / "snapshot.json"
            command = ["python3", "-m", "tools.service_analysis.collect", "--source", str(root),
                       "--output", str(output), "--java-home", str(JAVA_HOME)]
            run = subprocess.run(command, cwd=REPO, text=True, capture_output=True, timeout=80)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(output.read_text())
            self.assertEqual(data["metrics"]["failedFiles"], 1)
            self.assertEqual(data["fileDiagnostics"][0]["path"], "mod/src/main/java/example/Broken.java")
            self.assertEqual(data["modules"][0]["sourceFiles"], 1)
            saved = output.read_bytes()
            run = subprocess.run(command + ["--deadline", "0"], cwd=REPO, capture_output=True, timeout=5)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
