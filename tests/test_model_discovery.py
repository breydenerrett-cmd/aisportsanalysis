"""Tests for src/model/discovery.py.

The module's own docstring states the failure these tests guard: selections on
one slate move together, and treating each as its own draw understates the
uncertainty badly enough to turn noise into a result. The interval already
resamples dates; the p handed to the family correction must carry the same
structure, because family.benjamini_hochberg consumes only `p` and nothing
downstream ever looks at the interval to overrule it.
"""

import random
import statistics
import unittest

from src.model import discovery, family


def _two_per_date_rows(dates=60, per_date=6, seed=5):
    """Multi-selection dates whose diffs differ from each other.

    Order-sensitivity in the resampler only shows up when the clusters are
    distinguishable, so every date carries its own draw and every selection
    inside it its own noise.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(dates):
        base = rng.gauss(0.0, 0.09)
        for _ in range(per_date):
            rows.append({"date": f"2023-05-{i + 1:02d}",
                         "_diff": base + rng.gauss(0.0, 0.02)})
    return rows


def _clustered_noise_rows(dates=80, per_date=25, cluster_sd=0.11, mean=0.012,
                          seed=11):
    """Per-selection differences that are identical within a date.

    This is the correlation structure at its most extreme -- one effective
    observation per slate -- and exactly the shape the clustered bootstrap was
    written for. Any p computed as if there were dates * per_date independent
    draws is wrong here by construction.
    """
    rng = random.Random(seed)
    date_effects = [rng.gauss(0.0, cluster_sd) for _ in range(dates)]
    shift = mean - statistics.mean(date_effects)
    date_effects = [d + shift for d in date_effects]
    return [{"date": f"d{i}", "_diff": d}
            for i, d in enumerate(date_effects) for _ in range(per_date)]


class TestClusteredP(unittest.TestCase):

    def test_date_level_noise_does_not_reach_the_shortlist(self):
        # Regression for the confirmed defect: 80 dates x 25 selections of
        # pure date-level noise (clustered CI straddling zero) produced a
        # per-selection p of ~1e-07, and family.apply_gates -- which reads only
        # `p` -- put the detector on the discovery shortlist.
        rows = _clustered_noise_rows()
        diffs = [r["_diff"] for r in rows]
        effect = statistics.mean(diffs)

        ci = discovery.clustered_bootstrap(
            rows, lambda s: statistics.mean(x["_diff"] for x in s))
        self.assertLessEqual(ci["low"], 0.0)
        self.assertGreaterEqual(ci["high"], 0.0)

        p = discovery.clustered_two_sided_p(effect, rows)
        # The interval says "consistent with no effect at all"; the p handed to
        # the FDR gate must not contradict it.
        self.assertGreater(p, 0.05)

        gated = family.apply_gates(
            [{"detector": "X", "p": p, "effect": effect}]
            + [{"detector": f"n{i}", "p": 0.5, "effect": 0.0}
               for i in range(21)])
        self.assertEqual([e["detector"] for e in gated["passed"]], [])

    def test_evaluate_feeds_the_clustered_p_to_the_gate(self):
        # End to end through evaluate: whole slates win or lose together, so
        # 800 selections are 40 effective observations. Per-selection, the
        # effect of +0.07 sits four sigmas out; per-date it is under one.
        rows = []
        for day in range(40):
            won = day < 22  # 22 of 40 winning dates: hit 0.55 vs implied 0.48
            for _ in range(20):
                rows.append({"date": f"2023-04-{day + 1:02d}", "won": won,
                             "implied": 0.48})
        result = discovery.evaluate("clustered", rows)

        self.assertAlmostEqual(result["effect"], 0.07)
        self.assertGreater(result["p"], 0.05)
        self.assertLessEqual(result["ci"]["low"], 0.0)

        gated = family.apply_gates([result])
        self.assertEqual(gated["passed"], [])

    def test_singleton_clusters_collapse_to_the_independent_p(self):
        # With one selection per date the clustering is trivial and nothing
        # may be lost: a genuinely independent effect must still be found.
        rng = random.Random(3)
        values = [rng.gauss(0.03, 0.1) for _ in range(200)]
        rows = [{"date": f"x{i}", "_diff": v} for i, v in enumerate(values)]
        effect = statistics.mean(values)
        self.assertAlmostEqual(
            discovery.clustered_two_sided_p(effect, rows),
            discovery.two_sided_p(effect, values))

    def test_fewer_than_two_dates_refuses_with_p_of_one(self):
        # One date leaves no between-date variance to measure. The bootstrap
        # refuses the same case; falling back to the per-selection p here
        # would be the original defect wearing a smaller n.
        rows = [{"date": "d0", "_diff": 0.05} for _ in range(50)]
        self.assertEqual(discovery.clustered_two_sided_p(0.05, rows), 1.0)


class TestBootstrapDeterminism(unittest.TestCase):
    """A seeded interval must depend on the data, never on the row order.

    Regression for the confirmed defect: the resampler indexed
    `list(by_date)`, whose order is dict INSERTION order, so the same seed drew
    the same sequence of positions out of a differently-ordered list of dates
    and returned a different interval for identical data. Observed on the
    frozen 2023-24 selections: stale_book's low bound moved 0.112 points and
    bullpen_exposure's 0.264 points purely by reordering the input rows.

    This matters because discovery._verdict branches on whether the interval
    covers zero, and stale_book's published high bound sat +0.68 points from
    zero -- twice the drift, but only twice.
    """

    def _ci(self, rows):
        return discovery.clustered_bootstrap(
            rows, lambda s: statistics.mean(x["_diff"] for x in s))

    def test_interval_is_identical_under_any_row_order(self):
        rows = _two_per_date_rows()
        canonical = self._ci(rows)
        self.assertIsNotNone(canonical["low"])

        seen = {(canonical["low"], canonical["high"])}
        for seed in (1, 2, 3, 4, 5):
            shuffled = list(rows)
            random.Random(seed).shuffle(shuffled)
            got = self._ci(shuffled)
            seen.add((got["low"], got["high"]))
        self.assertEqual(
            len(seen), 1,
            f"seeded interval varies with input row order: {sorted(seen)}")

    def test_reversed_rows_give_the_same_interval(self):
        # The cheapest reordering, and the one a caller is most likely to hit
        # by iterating a store backwards or re-sorting for a report.
        rows = _two_per_date_rows()
        self.assertEqual(self._ci(rows), self._ci(list(reversed(rows))))

    def test_the_canonical_order_is_ascending_date(self):
        # Which order wins is not arbitrary: every published interval was
        # computed from selections already stored in ascending date order, so
        # sorting the cluster keys reproduces them rather than restating them.
        rows = _two_per_date_rows()
        shuffled = list(rows)
        random.Random(17).shuffle(shuffled)
        by_date_order = sorted(rows, key=lambda r: r["date"])
        self.assertEqual(self._ci(shuffled), self._ci(by_date_order))

    def test_unorderable_cluster_keys_refuse_by_name(self):
        # Sorting is what buys the reproducibility, so keys that cannot be
        # ordered must stop the run, not quietly fall back to insertion order.
        # Mixed key types are a clustering bug in the caller anyway -- the same
        # slate would land in two clusters.
        import datetime as dt
        rows = ([{"date": "2023-05-01", "_diff": 0.01} for _ in range(5)]
                + [{"date": dt.date(2023, 5, 2), "_diff": -0.01}
                   for _ in range(5)])
        with self.assertRaises(discovery.DiscoveryError):
            self._ci(rows)

    def test_evaluate_verdict_does_not_move_with_row_order(self):
        # End to end: the verdict reads ci.low <= 0 <= ci.high, so an interval
        # that shifts with row order can flip a published live/die call.
        rows = []
        for day in range(50):
            for k in range(8):
                rows.append({"date": f"2023-06-{day + 1:02d}",
                             "won": (day * 8 + k) % 3 != 0,
                             "implied": 0.50 + 0.01 * ((day + k) % 5)})
        first = discovery.evaluate("ordered", rows)
        shuffled = list(rows)
        random.Random(23).shuffle(shuffled)
        second = discovery.evaluate("ordered", shuffled)
        self.assertEqual(first["ci"], second["ci"])
        self.assertEqual(first["verdict"], second["verdict"])


if __name__ == "__main__":
    unittest.main()
