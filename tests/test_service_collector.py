import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path('/Library/Java/JavaVirtualMachines/amazon-corretto-21.jdk/Contents/Home')


@unittest.skipUnless(JAVA.is_dir(), 'JDK 21 required')
class ServiceCollectorTests(unittest.TestCase):
    def test_source_declarations_routes_overloads_and_declared_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'app'; source = root / 'src/main/java/sample'; source.mkdir(parents=True)
            (source / 'Api.java').write_text('''package sample;
import org.springframework.web.bind.annotation.GetMapping;
class Api { @GetMapping("/items") public String get(int n) { if (n > 0 && "secret".equals("secret")) return helper("secret"); else return helper("x"); }
  private String helper(String s) { return s; }
  private String helper(int n) { return ""; }
  abstract static class AbstractThing { abstract void missing(); }
}''')
            output = Path(temp) / 'out.json'
            result = subprocess.run(['python3', '-m', 'tools.service_analysis.collect', '--source', str(root), '--output', str(output), '--java-home', str(JAVA)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            data = json.loads(output.read_text())
            self.assertEqual('jjamtong.service-source.v1', data['schema'])
            self.assertEqual('SOURCE_DECLARATIONS', data['service']['scope'])
            self.assertEqual(1, data['metrics']['routeCount'])
            self.assertEqual(1, data['metrics']['abstractDeclarations'])
            methods = {m['name']: m for m in data['methods']}
            self.assertEqual('private', methods['helper']['visibility'])
            self.assertNotIn('simple-accessor', methods['helper']['noiseReasons'])
            self.assertEqual(2, sum(m['name'] == 'helper' for m in data['methods']))
            self.assertEqual(0, data['metrics']['unresolvedCallCount'])
            by_id = {m['id']: m for m in data['methods']}
            edges = [e for e in data['edges'] if by_id[e['target']]['name'] == 'helper']
            self.assertEqual(2, len(edges))
            self.assertEqual('if', edges[0]['sites'][0]['conditions'][0]['kind'])
            self.assertIn('<string>', json.dumps(edges))


if __name__ == '__main__':
    unittest.main()
