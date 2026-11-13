import unittest

from .fixtures import ANALYSIS, dataset, expected_reachable, fingerprint, key, scope


class FixtureContracts(unittest.TestCase):
    def setUp(self):
        self.rows = dataset(25, 40)

    def test_two_artifacts_at_same_commit(self):
        nodes = [r for r in self.rows if r["kind"] == "node"]
        self.assertEqual(len({r["commit"] for r in nodes}), 1)
        self.assertEqual(len({r["artifact"] for r in nodes}), 2)
        self.assertEqual(len({r["id"] for r in self.rows}), len(self.rows))

    def test_known_first_hop_and_build_change(self):
        for build, suffixes in (("build-A", (1, 7)), ("build-B", (2, 7))):
            self.assertEqual(expected_reachable(self.rows, scope(build=build), key("alpha", build, "method-0"), 1),
                             sorted(key("alpha", build, "method-%d" % i) for i in suffixes))

    def test_analysis_configuration_isolated(self):
        analysis = "analyzer-1.config-partial.schema-1"
        self.assertEqual(expected_reachable(self.rows, scope(analysis=analysis), key("alpha", "build-A", "method-0", analysis), 3),
                         [key("alpha", "build-A", "method-24", analysis)])

    def test_infrastructure_and_observed_edges_are_distinct(self):
        result = expected_reachable(self.rows, scope(), key("alpha", "build-A", "method-0"), 6, "INFRA")
        self.assertEqual({s.rsplit("/", 1)[1] for s in result}, {"service", "deployment", "pod", "subnet", "vpc", "rds", "s3"})
        self.assertEqual(len([r for r in self.rows if r["kind"] == "span" and r["tenant"] == "alpha" and r["build"] == "build-A"]), 3)

    def test_reproducible_input(self):
        self.assertEqual(fingerprint(self.rows), fingerprint(dataset(25, 40)))

    def test_missing_scope_fails_closed(self):
        for selected in (("", "build-A", ANALYSIS), ("alpha", "", ANALYSIS), ("alpha", "build-A", "")):
            with self.assertRaises(ValueError):
                scope(*selected)


if __name__ == "__main__":
    unittest.main()
