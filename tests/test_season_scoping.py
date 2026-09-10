"""A backfill of an earlier season may not silently change this season's numbers.

WHY THIS FILE EXISTS
--------------------
On 2026-09-10 the results store held one season. Later the same day it
gained a second (2025 ingested, 2,212 games) so that measurements had more
to stand on.

Two accessors written that afternoon walked the whole store and took
everything before a cutoff: `parkfactors.park_factors` and
`bullpen.relief_rates_by_team`. Both would have started including 2025 the
moment it landed -- not a leak, since 2025 genuinely precedes 2026, but
every number already recorded against the single-season store would have
become unreproducible with nothing in the repo to explain why.

`src.pipeline.features.games_before` has had `same_season_only=True` since
it was written, for a stated reason. These now match it.

The park case is arguable on the merits: a ballpark barely changes over a
winter and more games would mean less regression. The bullpen case is not --
a relief corps turns over between seasons and folding last year's innings in
would be wrong, not merely broader. Either way the choice belongs to a
caller passing the flag, not to whatever a data ingest happens to leave on
disk.

Verified live: with 2025 in the store, `scripts/test_bullpen_rate.py` and
`scripts/test_park_factor.py` reproduce their recorded figures to the digit.
"""

from __future__ import annotations

import unittest

from src.pipeline import bullpen, parkfactors


def _game(pk, date, away, home, away_score, home_score):
    return {"game_pk": str(pk), "date": date, "away_team": away,
            "home_team": home, "away_score": str(away_score),
            "home_score": str(home_score)}


def _relief(date, team, innings, earned):
    return {"date": date, "team": team, "started": False,
            "innings": innings, "earned_runs": earned, "person_id": 1}


class ParkFactorsStayInSeason(unittest.TestCase):
    def setUp(self):
        store = {}
        # Prior season at COL: wildly high scoring, 20 home and 20 road games.
        for i in range(20):
            store[f"p{i}"] = _game(f"p{i}", f"2025-05-{i % 28 + 1:02d}",
                                   "SD", "COL", 10, 10)
            store[f"q{i}"] = _game(f"q{i}", f"2025-06-{i % 28 + 1:02d}",
                                   "COL", "SD", 1, 1)
        # This season at COL: neutral, same counts.
        for i in range(20):
            store[f"a{i}"] = _game(f"a{i}", f"2026-05-{i % 28 + 1:02d}",
                                   "SD", "COL", 4, 4)
            store[f"b{i}"] = _game(f"b{i}", f"2026-06-{i % 28 + 1:02d}",
                                   "COL", "SD", 4, 4)
        self.store = store

    def test_the_prior_season_is_excluded_by_default(self):
        factors = parkfactors.park_factors(self.store, "2026-07-01")
        # 2026 alone is exactly neutral, so the regressed factor is 1.0.
        self.assertAlmostEqual(1.0, factors["COL"]["factor"], places=4)
        self.assertAlmostEqual(1.0, factors["COL"]["raw_factor"], places=4)

    def test_opting_in_brings_the_prior_season_back(self):
        """The flag has to actually do something, or the default is
        untested and the guard is decorative."""
        factors = parkfactors.park_factors(self.store, "2026-07-01",
                                           same_season_only=False)
        self.assertGreater(factors["COL"]["raw_factor"], 1.0)

    def test_a_game_on_the_cutoff_is_never_counted(self):
        store = dict(self.store)
        store["same_day"] = _game("same_day", "2026-07-01", "SD", "COL", 30, 30)
        with_it = parkfactors.park_factors(store, "2026-07-01")
        without = parkfactors.park_factors(self.store, "2026-07-01")
        self.assertEqual(without["COL"]["home_games"],
                         with_it["COL"]["home_games"])


class ReliefRatesStayInSeason(unittest.TestCase):
    def setUp(self):
        self.log = (
            # Last season's bullpen: terrible, and plenty of it.
            [_relief(f"2025-05-{i % 28 + 1:02d}", "NYY", 1.0, 5)
             for i in range(200)]
            # This season's: excellent.
            + [_relief(f"2026-05-{i % 28 + 1:02d}", "NYY", 1.0, 0)
               for i in range(200)]
            # A starter's outing, which must never count either way.
            + [{"date": "2026-05-02", "team": "NYY", "started": True,
                "innings": 6.0, "earned_runs": 9, "person_id": 2}]
        )

    def test_the_prior_season_is_excluded_by_default(self):
        rates = bullpen.relief_rates_by_team(self.log, "2026-07-01")
        self.assertEqual(200.0, rates["NYY"]["innings"])
        self.assertAlmostEqual(0.0, rates["NYY"]["raw_rate"], places=4)

    def test_opting_in_brings_the_prior_season_back(self):
        rates = bullpen.relief_rates_by_team(self.log, "2026-07-01",
                                             same_season_only=False)
        self.assertEqual(400.0, rates["NYY"]["innings"])
        self.assertGreater(rates["NYY"]["raw_rate"], 0.0)

    def test_the_single_team_accessor_agrees_with_the_bulk_one(self):
        one = bullpen.relief_rate(self.log, "NYY", "2026-07-01")
        many = bullpen.relief_rates_by_team(self.log, "2026-07-01")["NYY"]
        self.assertAlmostEqual(one["rate"], many["rate"], places=6)
        self.assertEqual(one["innings"], many["innings"])

    def test_a_starter_never_counts_as_relief(self):
        rates = bullpen.relief_rates_by_team(self.log, "2026-07-01")
        self.assertEqual(200.0, rates["NYY"]["innings"])


if __name__ == "__main__":
    unittest.main()
