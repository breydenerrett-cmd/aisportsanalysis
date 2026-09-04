"""Decision dedup and Jaccard family clustering. See
docs/FACTORY_SCALE_DESIGN.md sections 1.4, 2, 3 and src/evolab/overlap.py.
"""

import unittest

from src.evolab.overlap import (
    FAMILY_THRESHOLD,
    cluster_families,
    dedup_stats,
    effective_n,
    jaccard,
    pairwise_jaccard,
)


class TestDedupStats(unittest.TestCase):

    def test_no_overlap_ratio_is_one(self):
        selections = {"s1": frozenset({"w1", "w2"}), "s2": frozenset({"w3", "w4"})}
        stats = dedup_stats(selections)
        self.assertEqual(stats.n_strategies, 2)
        self.assertEqual(stats.total_decisions, 4)
        self.assertEqual(stats.unique_wagers, 4)
        self.assertEqual(stats.dedup_ratio, 1.0)

    def test_total_duplication_ratio_is_half(self):
        # Two strategies making the identical two bets: 4 total decisions,
        # 2 unique wagers -- the exact "population size lies about evidence"
        # case this module exists to catch.
        selections = {"s1": frozenset({"w1", "w2"}), "s2": frozenset({"w1", "w2"})}
        stats = dedup_stats(selections)
        self.assertEqual(stats.total_decisions, 4)
        self.assertEqual(stats.unique_wagers, 2)
        self.assertEqual(stats.dedup_ratio, 0.5)

    def test_empty_population_ratio_is_zero_not_error(self):
        stats = dedup_stats({})
        self.assertEqual(stats.total_decisions, 0)
        self.assertEqual(stats.dedup_ratio, 0.0)

    def test_to_dict_shape(self):
        stats = dedup_stats({"s1": frozenset({"w1"})})
        d = stats.to_dict()
        self.assertEqual(set(d), {"n_strategies", "total_decisions",
                                  "unique_wagers", "dedup_ratio"})


class TestJaccard(unittest.TestCase):

    def test_identical_sets_is_one(self):
        self.assertEqual(jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})), 1.0)

    def test_disjoint_sets_is_zero(self):
        self.assertEqual(jaccard(frozenset({"a"}), frozenset({"b"})), 0.0)

    def test_partial_overlap(self):
        # {a,b,c} vs {b,c,d}: intersection 2, union 4 -> 0.5
        self.assertEqual(
            jaccard(frozenset({"a", "b", "c"}), frozenset({"b", "c", "d"})), 0.5)

    def test_both_empty_is_zero_not_nan(self):
        self.assertEqual(jaccard(frozenset(), frozenset()), 0.0)

    def test_one_empty_is_zero(self):
        self.assertEqual(jaccard(frozenset(), frozenset({"a"})), 0.0)

    def test_pairwise_jaccard_keys_sorted_and_complete(self):
        selections = {
            "s3": frozenset({"a"}),
            "s1": frozenset({"a"}),
            "s2": frozenset({"b"}),
        }
        pairs = pairwise_jaccard(selections)
        self.assertEqual(set(pairs), {("s1", "s2"), ("s1", "s3"), ("s2", "s3")})
        self.assertEqual(pairs[("s1", "s3")], 1.0)
        self.assertEqual(pairs[("s1", "s2")], 0.0)


class TestClusterFamilies(unittest.TestCase):

    def test_identical_strategies_join_one_family(self):
        selections = {
            "s1": frozenset({"w1", "w2"}),
            "s2": frozenset({"w1", "w2"}),
            "s3": frozenset({"w9"}),
        }
        families = cluster_families(selections)
        sizes = sorted(len(f) for f in families)
        self.assertEqual(sizes, [1, 2])
        pair_family = next(f for f in families if len(f) == 2)
        self.assertEqual(pair_family, ["s1", "s2"])

    def test_below_threshold_stays_separate(self):
        # J = 1/3 for these two -- well under FAMILY_THRESHOLD (0.8).
        selections = {
            "s1": frozenset({"w1", "w2", "w3"}),
            "s2": frozenset({"w1", "w4", "w5"}),
        }
        families = cluster_families(selections)
        self.assertEqual(len(families), 2)

    def test_transitive_chain_forms_one_family(self):
        # s1~s2 (J=1.0), s2~s3 (J=1.0), s1 and s3 share no direct edge test
        # here but must land in the same connected component transitively.
        selections = {
            "s1": frozenset({"w1", "w2"}),
            "s2": frozenset({"w1", "w2"}),
            "s3": frozenset({"w1", "w2"}),
        }
        families = cluster_families(selections)
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0], ["s1", "s2", "s3"])

    def test_threshold_boundary_is_inclusive(self):
        # Exactly FAMILY_THRESHOLD (0.8) must join, per ">=" in the docstring.
        selections = {
            "s1": frozenset({"w1", "w2", "w3", "w4"}),
            "s2": frozenset({"w1", "w2", "w3", "w5"}),  # J = 3/5 = 0.6, below
        }
        j = jaccard(selections["s1"], selections["s2"])
        self.assertLess(j, FAMILY_THRESHOLD)
        families = cluster_families(selections)
        self.assertEqual(len(families), 2)

        selections_at_boundary = {
            "s1": frozenset({"w1", "w2", "w3", "w4"}),
            "s2": frozenset({"w1", "w2", "w3", "w4", "w5"}),  # J = 4/5 = 0.8
        }
        j2 = jaccard(selections_at_boundary["s1"], selections_at_boundary["s2"])
        self.assertEqual(j2, FAMILY_THRESHOLD)
        families2 = cluster_families(selections_at_boundary)
        self.assertEqual(len(families2), 1)

    def test_result_sorted_largest_family_first(self):
        selections = {
            "s1": frozenset({"w1"}),
            "s2": frozenset({"w1"}),
            "s3": frozenset({"w1"}),
            "s4": frozenset({"w9"}),
        }
        families = cluster_families(selections)
        self.assertEqual(len(families[0]), 3)
        self.assertEqual(len(families[1]), 1)


class TestEffectiveN(unittest.TestCase):

    def test_all_singletons(self):
        families = [["s1"], ["s2"], ["s3"]]
        en = effective_n(families)
        self.assertEqual(en.n_families, 3)
        # log2(1) == 0, so each singleton contributes exactly 1.0.
        self.assertEqual(en.credit, 3.0)

    def test_one_big_family_credit_less_than_size(self):
        families = [["s1", "s2", "s3", "s4"]]
        en = effective_n(families)
        self.assertEqual(en.n_families, 1)
        # 1 + log2(4) = 3.0, well under the raw strategy count of 4 --
        # the whole point of the discount.
        self.assertAlmostEqual(en.credit, 3.0)
        self.assertLess(en.credit, 4)

    def test_empty_families_list(self):
        en = effective_n([])
        self.assertEqual(en.n_families, 0)
        self.assertEqual(en.credit, 0.0)

    def test_to_dict_flags_heuristic(self):
        d = effective_n([["s1"]]).to_dict()
        self.assertTrue(d["credit_is_heuristic_not_calibrated"])


if __name__ == "__main__":
    unittest.main()
