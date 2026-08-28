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


if __name__ == "__main__":
    unittest.main()
