import unittest

from experiments.graph_scale_lab import fixtures


class FixtureContractTest(unittest.TestCase):
    def test_metadata_scope_is_complete_and_isolated(self):
        old = fixtures.metadata("old")
        new = fixtures.metadata("new")
        self.assertEqual("alpha", old["tenant"])
        self.assertNotEqual(old, new)
        self.assertNotEqual(fixtures.scope_id(old), fixtures.scope_id(new))
        self.assertNotEqual(fixtures.scope_id(old), fixtures.scope_id(fixtures.metadata(repo="synthetic/other")))
        self.assertNotEqual(fixtures.scope_id(old), fixtures.scope_id(fixtures.metadata(config="sample")))
        self.assertNotEqual(fixtures.scope_id(old), fixtures.scope_id(fixtures.metadata(artifact="analysis.jar")))
        for key in ("repo", "commit", "build", "artifact", "analyzer", "schema", "config", "module_manifest"):
            self.assertTrue(old[key])

    def test_metadata_rejects_missing_identity_values(self):
        with self.assertRaises(ValueError):
            fixtures.metadata(repo=" ")
        with self.assertRaises(ValueError):
            fixtures.scope_id({"tenant": "alpha"})
        missing_artifact = fixtures.metadata()
        missing_artifact.pop("artifact")
        with self.assertRaises(ValueError):
            fixtures.scope_id(missing_artifact)

    def test_nodes_and_edges_are_deterministic_and_bounded(self):
        node_rows = fixtures.nodes(300)
        old_rows = fixtures.edges(300, 6, "old")
        self.assertEqual(node_rows, fixtures.nodes(300))
        self.assertEqual(300, len({row[0] for row in node_rows}))
        self.assertGreater(len({row[1] for row in node_rows}), 1)
        self.assertEqual(old_rows, sorted(old_rows))
        self.assertEqual(len(old_rows), len(set(old_rows)))
        self.assertTrue(all(0 <= source < 300 and 0 <= target < 300 for source, target, _ in old_rows))

    def test_relations_and_revisions_remain_separate(self):
        old_rows = fixtures.edges(512, 6, "old")
        new_rows = fixtures.edges(512, 6, "new")
        self.assertTrue(any(kind == "OBSERVED" for _, _, kind in old_rows))
        self.assertTrue(any(kind == "STATIC" for _, _, kind in old_rows))
        static_pairs = {(source, target) for source, target, kind in old_rows if kind == "STATIC"}
        self.assertTrue(all((source, target) not in static_pairs for source, target, kind in old_rows if kind == "OBSERVED"))
        old_first_hop = {target for source, target, kind in old_rows if source == 0 and kind == "STATIC"}
        new_first_hop = {target for source, target, kind in new_rows if source == 0 and kind == "STATIC"}
        self.assertNotEqual(old_first_hop, new_first_hop)
        self.assertEqual(len(old_first_hop), len(new_first_hop))

    def test_questions_and_fingerprint_are_stable(self):
        expected = ["entry_1", "local_3", "hub_6", "reverse_6", "deep_12", "observed_6"]
        self.assertEqual(expected, [item["label"] for item in fixtures.questions(320)])
        self.assertEqual("ac6a2cf67b3cf6a91221e43b3735765a1ffa694bec6c4095d1c24fac5d9dfaeb", fixtures.fingerprint(320, 4))
        self.assertNotEqual(fixtures.fingerprint(320, 4), fixtures.fingerprint(320, 5))

    def test_oracle_handles_cycles_depth_reverse_and_relation(self):
        rows = [
            (0, 1, "STATIC"),
            (1, 2, "STATIC"),
            (2, 0, "STATIC"),
            (2, 3, "STATIC"),
            (0, 4, "OBSERVED"),
        ]
        self.assertEqual([1], fixtures.oracle(rows, 0, 1))
        self.assertEqual([1, 2], fixtures.oracle(rows, 0, 2))
        self.assertEqual([1, 2, 3], fixtures.oracle(rows, 0, 12))
        self.assertEqual([2], fixtures.oracle(rows, 0, 1, reverse=True))
        self.assertEqual([4], fixtures.oracle(rows, 0, 6, relation="OBSERVED"))
        with self.assertRaises(ValueError):
            fixtures.oracle(rows, 99, 1)


if __name__ == "__main__":
    unittest.main()
