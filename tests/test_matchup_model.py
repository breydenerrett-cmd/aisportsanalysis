"""tests/test_matchup_model.py -- Lane C's richer per-game candidate
(src/analysis/matchup_model.py), built on top of the UNMODIFIED
src.analysis.strength.model_line.

Every test here uses a small synthetic in-memory store/pitcher-log/
bullpen-log, never the real data files, so this suite is fast, deterministic
and independent of whatever the historical store happens to contain on a
given day. `scripts/postseason_demo.py`'s own run (captured in
evidence/postseason/) is the check against real data; this file checks the
PLUMBING: that the frozen aggregate reference and the richer candidate
route through the identical model_line, that every named factor carries
exactly one disposition, that the neutral-site approximation used by the
postseason bracket engine has the algebraic property its own docstring
claims, and that missing data produces an honest None/error rather than a
fabricated number.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from src.analysis import matchup_model as mm
from src.analysis import strength
from src.pipeline import features as features_mod


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _game(pk, d, away, home, away_score, home_score, game_type="R"):
    winner = home if home_score > away_score else away
    return {
        "game_pk": pk, "date": d, "game_type": game_type,
        "away_team": away, "home_team": home,
        "away_score": away_score, "home_score": home_score,
        "winner": winner, "home_won": "1" if winner == home else "0",
        "away_probable_id": None, "home_probable_id": None,
    }


def build_rich_fixture():
    """A synthetic 2024 season with enough games/innings for every rate in
    strength.py, src.pipeline.pitchers and src.pipeline.bullpen to clear its
    own MIN_*/regression threshold for both AAA and BBB -- so model_line and
    every richer-feature source below can actually be exercised, not just
    hit their thin-sample fallback.

    AAA and BBB each play 15 games at home and 15 on the road (against
    disposable opponents), all before the fixture's TEST_DATE, which is the
    one game this module's tests price: AAA @ BBB.
    """
    store = {}
    pk = 1
    d = date(2024, 4, 1)

    def next_date():
        nonlocal d
        d += timedelta(days=1)
        return d.isoformat()

    for team, opp_prefix in (("AAA", "OPP"), ("BBB", "OPQ")):
        for i in range(15):
            store[str(pk)] = _game(pk, next_date(), f"{opp_prefix}{i}", team, 3, 5)
            pk += 1
        for i in range(15):
            store[str(pk)] = _game(pk, next_date(), team, f"{opp_prefix}{i + 20}", 4, 3)
            pk += 1

    test_date = next_date()  # strictly after every fixture game above

    pitcher_logs = {
        "9001": [{"person_id": 9001, "date": "2024-04-05", "season": "2024",
                  "games_started": 1, "innings_pitched": 30.0, "earned_runs": 10,
                  "hits": 25, "walks": 8, "strikeouts": 28, "home_runs": 3,
                  "batters_faced": 130}],
        "9002": [{"person_id": 9002, "date": "2024-04-05", "season": "2024",
                  "games_started": 1, "innings_pitched": 30.0, "earned_runs": 20,
                  "hits": 40, "walks": 15, "strikeouts": 12, "home_runs": 8,
                  "batters_faced": 150}],
    }

    bullpen_log = []
    for i in range(20):
        bullpen_log.append({"date": f"2024-05-{(i % 27) + 1:02d}", "team": "AAA",
                            "started": False, "innings": 6.0, "earned_runs": 2,
                            "person_id": 8001, "name": "AAA Reliever"})
        bullpen_log.append({"date": f"2024-05-{(i % 27) + 1:02d}", "team": "BBB",
                            "started": False, "innings": 6.0, "earned_runs": 5,
                            "person_id": 8002, "name": "BBB Reliever"})

    return store, pitcher_logs, bullpen_log, test_date


class SyntheticFixtureMixin:
    @classmethod
    def setUpClass(cls):
        cls.store, cls.pitcher_logs, cls.bullpen_log, cls.test_date = build_rich_fixture()
        cls.league_rpg = mm.league_rpg_from_store(cls.store, cls.test_date)


# ---------------------------------------------------------------------------
# The disposition table
# ---------------------------------------------------------------------------

class FactorDispositionTests(unittest.TestCase):
    """Every factor named in the Lane C task gets EXACTLY one disposition,
    from the four the task's honesty constraints define."""

    REQUIRED_FACTORS = {
        "starting_pitcher", "bullpen_quality", "park_factor",
        "bullpen_recent_availability", "rest_travel",
        "lineup_composition", "documented_injuries",
    }
    ALLOWED = {mm.MODEL_USED, mm.SCENARIO_INPUT, mm.CONTEXT_ONLY, mm.UNAVAILABLE}

    def test_every_required_factor_present_exactly_once(self):
        self.assertEqual(self.REQUIRED_FACTORS, set(mm.FACTOR_DISPOSITIONS))

    def test_every_disposition_is_one_of_the_four_allowed_values(self):
        for factor, disposition in mm.FACTOR_DISPOSITIONS.items():
            self.assertIn(disposition, self.ALLOWED, msg=factor)

    def test_every_factor_has_a_note(self):
        for factor in mm.FACTOR_DISPOSITIONS:
            self.assertIn(factor, mm.FACTOR_NOTES)
            self.assertTrue(mm.FACTOR_NOTES[factor])

    def test_model_used_factors_are_the_three_the_docstring_names(self):
        model_used = {f for f, disp in mm.FACTOR_DISPOSITIONS.items()
                      if disp == mm.MODEL_USED}
        self.assertEqual({"starting_pitcher", "bullpen_quality", "park_factor"}, model_used)

    def test_unavailable_factors_have_no_pipeline_in_this_repo(self):
        unavailable = {f for f, disp in mm.FACTOR_DISPOSITIONS.items()
                      if disp == mm.UNAVAILABLE}
        self.assertEqual({"lineup_composition", "documented_injuries"}, unavailable)


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------

class AggregateReferenceTests(SyntheticFixtureMixin, unittest.TestCase):
    def test_aggregate_reference_matches_features_matchup_features_exactly(self):
        """The frozen aggregate reference IS features.matchup_features's
        output -- not a copy, not a near-miss. Any drift here would mean the
        'baseline' this module compares against secretly differs from the
        real src.pipeline.features baseline the rest of the project uses."""
        expected = features_mod.matchup_features(self.store, "AAA", "BBB", self.test_date)
        actual = mm.aggregate_reference_features(self.store, "AAA", "BBB", self.test_date)
        self.assertEqual(expected, actual)

    def test_aggregate_reference_carries_no_starter_bullpen_or_park_keys(self):
        feats = mm.aggregate_reference_features(self.store, "AAA", "BBB", self.test_date)
        for key in ("away_sp_fip", "home_sp_fip", "away_bullpen_rate",
                   "home_bullpen_rate", "park_factor"):
            self.assertNotIn(key, feats)


class RicherFeaturesTests(SyntheticFixtureMixin, unittest.TestCase):
    def test_richer_features_is_a_strict_superset_of_the_aggregate_reference(self):
        baseline = mm.aggregate_reference_features(self.store, "AAA", "BBB", self.test_date)
        richer = mm.richer_features(self.store, self.pitcher_logs, self.bullpen_log,
                                    "AAA", "BBB", 9001, 9002, self.test_date)
        for key, value in baseline.items():
            self.assertEqual(value, richer[key], msg=key)

    def test_richer_features_adds_starter_bullpen_and_park(self):
        richer = mm.richer_features(self.store, self.pitcher_logs, self.bullpen_log,
                                    "AAA", "BBB", 9001, 9002, self.test_date)
        self.assertTrue(richer["away_sp_known"])
        self.assertTrue(richer["home_sp_known"])
        self.assertIsNotNone(richer["away_sp_fip"])
        self.assertIsNotNone(richer["home_sp_fip"])
        self.assertIsNotNone(richer["away_bullpen_rate"])
        self.assertIsNotNone(richer["home_bullpen_rate"])
        self.assertIsNotNone(richer["park_factor"])

    def test_unknown_probable_id_is_reported_unavailable_not_guessed(self):
        richer = mm.richer_features(self.store, self.pitcher_logs, self.bullpen_log,
                                    "AAA", "BBB", None, None, self.test_date)
        self.assertFalse(richer["away_sp_known"])
        self.assertFalse(richer["home_sp_known"])
        self.assertIsNone(richer["away_sp_fip"])
        self.assertIsNone(richer["home_sp_fip"])

    def test_pitcher_logs_none_behaves_like_empty_not_a_crash(self):
        richer = mm.richer_features(self.store, None, self.bullpen_log,
                                    "AAA", "BBB", None, None, self.test_date)
        self.assertFalse(richer["away_sp_known"])
        self.assertIsNotNone(richer["away_bullpen_rate"])  # bullpen still real


# ---------------------------------------------------------------------------
# Running the model
# ---------------------------------------------------------------------------

class ModelLineOrNoneTests(SyntheticFixtureMixin, unittest.TestCase):
    def test_returns_a_line_and_no_error_for_good_features(self):
        feats = mm.aggregate_reference_features(self.store, "AAA", "BBB", self.test_date)
        line, err = mm.model_line_or_none(feats, league_rpg=self.league_rpg)
        self.assertIsNone(err)
        self.assertIn("p_home", line)

    def test_returns_none_and_an_error_string_for_empty_features(self):
        line, err = mm.model_line_or_none({}, league_rpg=self.league_rpg)
        self.assertIsNone(line)
        self.assertIsInstance(err, str)
        self.assertTrue(err)

    def test_never_raises_even_on_bad_input(self):
        try:
            line, err = mm.model_line_or_none({"garbage": object()}, league_rpg=4.5)
        except strength.StrengthError:
            self.fail("model_line_or_none must catch StrengthError, not propagate it")
        self.assertIsNone(line)


class CompareGameTests(SyntheticFixtureMixin, unittest.TestCase):
    def test_richer_starter_moves_p_home_away_from_baseline(self):
        """The one load-bearing claim of this whole module: with two starters
        of genuinely different FIP, the richer candidate's p_home must
        differ from the frozen aggregate reference's p_home for the SAME
        game. If this assertion ever fails, the richer candidate is not
        actually richer."""
        result = mm.compare_game(self.store, self.pitcher_logs, self.bullpen_log,
                                 "AAA", "BBB", 9001, 9002, self.test_date,
                                 league_rpg=self.league_rpg)
        self.assertIsNotNone(result["baseline"]["p_home"])
        self.assertIsNotNone(result["richer"]["p_home"])
        self.assertNotAlmostEqual(result["baseline"]["p_home"], result["richer"]["p_home"],
                                  places=6)
        self.assertAlmostEqual(
            result["p_home_delta"],
            round(result["richer"]["p_home"] - result["baseline"]["p_home"], 4), places=4)

    def test_factor_dispositions_echoed_verbatim(self):
        result = mm.compare_game(self.store, self.pitcher_logs, self.bullpen_log,
                                 "AAA", "BBB", 9001, 9002, self.test_date,
                                 league_rpg=self.league_rpg)
        self.assertEqual(mm.FACTOR_DISPOSITIONS, result["factor_dispositions"])

    def test_both_sides_report_none_rather_than_crash_with_no_league_rpg_data(self):
        result = mm.compare_game({}, {}, [], "ZZZ", "YYY", None, None, "2024-01-01",
                                 league_rpg=4.5)
        self.assertIsNone(result["baseline"]["p_home"])
        self.assertIsNone(result["richer"]["p_home"])
        self.assertIsNotNone(result["baseline"]["error"])
        self.assertIsNotNone(result["richer"]["error"])


# ---------------------------------------------------------------------------
# league_rpg_from_store
# ---------------------------------------------------------------------------

class LeagueRpgFromStoreTests(unittest.TestCase):
    def test_exact_arithmetic_on_a_tiny_store(self):
        store = {
            "1": _game(1, "2024-04-01", "A", "B", 2, 4),   # 6 runs
            "2": _game(2, "2024-04-02", "C", "D", 5, 1),   # 6 runs
        }
        # 12 runs over 4 team-games = 3.0
        self.assertAlmostEqual(3.0, mm.league_rpg_from_store(store, "2024-04-03"))

    def test_cutoff_is_strict_not_inclusive(self):
        store = {"1": _game(1, "2024-04-05", "A", "B", 10, 10)}
        self.assertIsNone(mm.league_rpg_from_store(store, "2024-04-05"))
        self.assertIsNotNone(mm.league_rpg_from_store(store, "2024-04-06"))

    def test_same_season_only_excludes_other_years(self):
        store = {
            "1": _game(1, "2023-04-01", "A", "B", 100, 100),  # would blow up the mean
            "2": _game(2, "2024-04-01", "A", "B", 4, 4),
        }
        self.assertAlmostEqual(4.0, mm.league_rpg_from_store(store, "2024-12-31"))

    def test_no_games_returns_none(self):
        self.assertIsNone(mm.league_rpg_from_store({}, "2024-06-01"))


# ---------------------------------------------------------------------------
# neutral_win_prob -- the bracket engine's win_prob_fn
# ---------------------------------------------------------------------------

class NeutralWinProbTests(SyntheticFixtureMixin, unittest.TestCase):
    def test_complementary_by_construction(self):
        """neutral_win_prob(A, B) is built by averaging two flipped
        model_line calls; swapping the arguments swaps and complements
        exactly the same two terms. This must hold to within float error
        for BOTH the aggregate and the richer feature source, or the
        'approximate neutral-site estimate' this function claims to be
        isn't even internally consistent."""
        for use_richer in (False, True):
            p_ab = mm.neutral_win_prob(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", self.test_date,
                                       league_rpg=self.league_rpg, use_richer=use_richer)
            p_ba = mm.neutral_win_prob(self.store, self.pitcher_logs, self.bullpen_log,
                                       "BBB", "AAA", self.test_date,
                                       league_rpg=self.league_rpg, use_richer=use_richer)
            self.assertAlmostEqual(1.0, p_ab + p_ba, places=9, msg=f"use_richer={use_richer}")

    def test_bounded_in_unit_interval(self):
        p = mm.neutral_win_prob(self.store, self.pitcher_logs, self.bullpen_log,
                                "AAA", "BBB", self.test_date,
                                league_rpg=self.league_rpg, use_richer=True)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_raises_matchup_model_error_for_teams_with_no_data(self):
        with self.assertRaises(mm.MatchupModelError):
            mm.neutral_win_prob({}, {}, [], "ZZZ", "YYY", "2024-06-01",
                                league_rpg=4.5, use_richer=False)


# ---------------------------------------------------------------------------
# attribution_breakdown -- 2026-09-25 Opus review, fix 1: per-factor
# attribution. Each MODEL-USED factor must move p_home on its own when its
# input is real and differs, and must leave p_home UNCHANGED from baseline
# when its input is neutral -- proving the isolation is real, not cosmetic.
# ---------------------------------------------------------------------------

class AttributionBreakdownTests(SyntheticFixtureMixin, unittest.TestCase):
    def test_structure_has_all_five_variants_and_matching_deltas(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", 9001, 9002, self.test_date,
                                       league_rpg=self.league_rpg)
        self.assertEqual({"baseline", "plus_starter", "plus_bullpen", "plus_park", "all_three"},
                         set(att["p_home_by_variant"]))
        baseline_p = att["p_home_by_variant"]["baseline"]
        for name in ("plus_starter", "plus_bullpen", "plus_park", "all_three"):
            self.assertAlmostEqual(
                att["delta_from_baseline"][name],
                round(att["p_home_by_variant"][name] - baseline_p, 4), places=4, msg=name)

    def test_inputs_report_both_starters_fip_both_bullpen_rates_and_park(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", 9001, 9002, self.test_date,
                                       league_rpg=self.league_rpg)
        inputs = att["inputs"]
        self.assertEqual(9001, inputs["away_sp_id"])
        self.assertEqual(9002, inputs["home_sp_id"])
        self.assertIsNotNone(inputs["away_sp_fip"])
        self.assertIsNotNone(inputs["home_sp_fip"])
        self.assertIsNotNone(inputs["away_bullpen_rate"])
        self.assertIsNotNone(inputs["home_bullpen_rate"])
        self.assertIsNotNone(inputs["park_factor"])

    # ---- starter: isolation ----
    def test_starter_alone_moves_p_when_fip_differs(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", 9001, 9002, self.test_date,
                                       league_rpg=self.league_rpg)
        self.assertNotAlmostEqual(att["p_home_by_variant"]["baseline"],
                                  att["p_home_by_variant"]["plus_starter"], places=6)

    def test_starter_alone_leaves_p_unchanged_when_unknown(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", None, None, self.test_date,
                                       league_rpg=self.league_rpg)
        self.assertAlmostEqual(att["p_home_by_variant"]["baseline"],
                               att["p_home_by_variant"]["plus_starter"], places=9)
        self.assertEqual(0.0, att["delta_from_baseline"]["plus_starter"])

    # ---- bullpen: isolation ----
    def test_bullpen_alone_moves_p_when_rates_differ(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", 9001, 9002, self.test_date,
                                       league_rpg=self.league_rpg)
        self.assertNotAlmostEqual(att["p_home_by_variant"]["baseline"],
                                  att["p_home_by_variant"]["plus_bullpen"], places=6)

    def test_bullpen_alone_leaves_p_unchanged_when_log_is_empty(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, [],
                                       "AAA", "BBB", 9001, 9002, self.test_date,
                                       league_rpg=self.league_rpg)
        self.assertAlmostEqual(att["p_home_by_variant"]["baseline"],
                               att["p_home_by_variant"]["plus_bullpen"], places=9)
        self.assertEqual(0.0, att["delta_from_baseline"]["plus_bullpen"])
        self.assertIsNone(att["inputs"]["away_bullpen_rate"])
        self.assertIsNone(att["inputs"]["home_bullpen_rate"])

    # ---- park: isolation ----
    def test_park_alone_moves_p_when_factor_is_not_neutral(self):
        att = mm.attribution_breakdown(self.store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", 9001, 9002, self.test_date,
                                       league_rpg=self.league_rpg)
        self.assertNotEqual(1.0, att["inputs"]["park_factor"])
        self.assertNotAlmostEqual(att["p_home_by_variant"]["baseline"],
                                  att["p_home_by_variant"]["plus_park"], places=6)

    def test_park_alone_leaves_p_unchanged_when_factor_is_neutral(self):
        # A store too thin for either side of park_factors' own
        # MIN_HOME_GAMES gate (10 home AND 10 away) comes back exactly
        # neutral (1.0) by that module's own construction -- 5 and 5 here,
        # deliberately below the gate, using the SAME two teams and the
        # SAME pitcher/bullpen fixtures so only the park input changes.
        thin_store = {}
        pk = 1
        d = date(2024, 4, 1)
        for team, opp_prefix in (("AAA", "OPP"), ("BBB", "OPQ")):
            for i in range(5):
                d += timedelta(days=1)
                thin_store[str(pk)] = _game(pk, d.isoformat(), f"{opp_prefix}{i}", team, 3, 5)
                pk += 1
            for i in range(5):
                d += timedelta(days=1)
                thin_store[str(pk)] = _game(pk, d.isoformat(), team, f"{opp_prefix}{i + 20}", 4, 3)
                pk += 1
        d += timedelta(days=1)
        thin_test_date = d.isoformat()
        thin_league_rpg = mm.league_rpg_from_store(thin_store, thin_test_date)

        att = mm.attribution_breakdown(thin_store, self.pitcher_logs, self.bullpen_log,
                                       "AAA", "BBB", 9001, 9002, thin_test_date,
                                       league_rpg=thin_league_rpg)
        self.assertEqual(1.0, att["inputs"]["park_factor"])
        self.assertAlmostEqual(att["p_home_by_variant"]["baseline"],
                               att["p_home_by_variant"]["plus_park"], places=9)
        self.assertEqual(0.0, att["delta_from_baseline"]["plus_park"])


# ---------------------------------------------------------------------------
# recent_starters -- fix 2: a rotation projection that never reads a
# future appearance.
# ---------------------------------------------------------------------------

class RecentStartersTests(unittest.TestCase):
    def _store(self):
        return {
            "1": _game(1, "2024-04-01", "OPP", "AAA", 1, 2, "R")
                | {"home_probable_id": 111},
            "2": _game(2, "2024-04-05", "AAA", "OPP", 2, 1, "R")
                | {"away_probable_id": 222},
            "3": _game(3, "2024-04-10", "OPP", "AAA", 1, 3, "R")
                | {"home_probable_id": 111},  # 111 again -- most recent now
            "4": _game(4, "2024-05-01", "OPP", "AAA", 0, 1, "R")
                | {"home_probable_id": 333},  # ON/AFTER a later cutoff, excluded below
        }

    def test_most_recent_start_first_deduplicated(self):
        store = self._store()
        order = mm.recent_starters(store, "AAA", "2024-04-15")
        # 333 (2024-05-01) is on/after the cutoff and must never appear.
        self.assertEqual([111, 222], order)

    def test_cutoff_never_reads_a_future_appearance(self):
        store = self._store()
        # 2024-04-06 sits strictly between game 2 (04-05) and game 3
        # (04-10): 333's 05-01 start and 111's SECOND (04-10) start are both
        # on/after this cutoff and must never appear, however close.
        order = mm.recent_starters(store, "AAA", "2024-04-06")
        self.assertNotIn(333, order)
        self.assertEqual([222, 111], order)  # 222 (04-05) more recent than 111 (04-01)

    def test_limit_caps_the_list(self):
        store = self._store()
        order = mm.recent_starters(store, "AAA", "2024-12-31", limit=1)
        self.assertEqual(1, len(order))

    def test_ids_are_normalized_to_int_even_when_the_store_holds_strings(self):
        """The results store round-trips through CSV, so a real probable id
        is a STRING ("543037"). The 2026-09-25 second review found that an
        un-normalized mix of int and str ids silently broke "already used"
        comparisons elsewhere in this module -- this pins the fix at its
        source."""
        store = {"1": _game(1, "2024-04-01", "OPP", "AAA", 1, 2, "R")
                 | {"home_probable_id": "111"}}  # string, as the CSV store holds it
        order = mm.recent_starters(store, "AAA", "2024-12-31")
        self.assertEqual([111], order)
        self.assertIsInstance(order[0], int)


# ---------------------------------------------------------------------------
# build_rotation_pool / project_team_rotation -- second review, 2026-09-25:
# the corrected rotation projection. Replaces the earlier `project_rotation`
# (a plain fixed-list cycle), which the review found projected a pitcher to
# start again immediately after he just had, and mixed int/str ids.
# ---------------------------------------------------------------------------

class BuildRotationPoolTests(unittest.TestCase):
    def _store(self, rows):
        return {str(i): row for i, row in enumerate(rows, start=1)}

    def _start(self, pk, d, team, pid, home=True):
        opp = "OPP"
        away, home_team = (opp, team) if home else (team, opp)
        row = _game(pk, d, away, home_team, 1, 2, "R")
        row["home_probable_id" if home else "away_probable_id"] = pid
        return row

    def test_filters_out_a_single_spot_start(self):
        """A reliever with exactly one start in the window (the review's own
        example, Michael Kopech) must not enter the pool."""
        rows = [self._start(1, "2024-10-20", "AAA", 999, home=True)]  # one start only
        for i, (d, pid) in enumerate(
                [("2024-10-10", 111), ("2024-10-15", 111), ("2024-10-18", 222)], start=2):
            rows.append(self._start(i, d, "AAA", pid, home=True))
        pool = mm.build_rotation_pool(self._store(rows), "AAA", "2024-10-25", min_starts=2)
        self.assertNotIn(999, pool)
        self.assertIn(111, pool)

    def test_filters_out_a_stale_starter_outside_the_window(self):
        """29 career starts but none in the last 30 days (the review's real
        Marcus Stroman case) must not enter the pool, even though the
        season-long count alone would clear min_starts easily."""
        rows = []
        pk = 1
        for d in ("2024-06-01", "2024-06-06", "2024-06-11", "2024-06-16"):
            rows.append(self._start(pk, d, "AAA", 555, home=True)); pk += 1
        for d in ("2024-10-15", "2024-10-20"):
            rows.append(self._start(pk, d, "AAA", 111, home=True)); pk += 1
        pool = mm.build_rotation_pool(self._store(rows), "AAA", "2024-10-25",
                                      window_days=30, min_starts=2)
        self.assertNotIn(555, pool)
        self.assertIn(111, pool)

    def test_ids_are_int(self):
        rows = [self._start(i, d, "AAA", pid, home=True) for i, (d, pid) in enumerate(
            [("2024-10-10", 111), ("2024-10-15", 111), ("2024-10-18", 222),
             ("2024-10-20", 222)], start=1)]
        for row in rows:
            row["home_probable_id"] = str(row["home_probable_id"])  # force string, like the CSV store
        pool = mm.build_rotation_pool(self._store(rows), "AAA", "2024-10-25", min_starts=2)
        self.assertTrue(all(isinstance(pid, int) for pid in pool))

    def test_ordered_most_recent_last_start_first(self):
        rows = []
        pk = 1
        for d in ("2024-10-05", "2024-10-10"):
            rows.append(self._start(pk, d, "AAA", 111, home=True)); pk += 1
        for d in ("2024-10-12", "2024-10-20"):
            rows.append(self._start(pk, d, "AAA", 222, home=True)); pk += 1
        pool = mm.build_rotation_pool(self._store(rows), "AAA", "2024-10-25", min_starts=2)
        self.assertEqual([222, 111], pool)  # 222's last start (10-20) beats 111's (10-10)

    def test_empty_store_returns_empty_pool(self):
        self.assertEqual([], mm.build_rotation_pool({}, "AAA", "2024-10-25"))


class ProjectTeamRotationTests(unittest.TestCase):
    def test_never_raises_with_empty_pool(self):
        with self.assertRaises(mm.MatchupModelError):
            mm.project_team_rotation([], {}, 3)

    def test_known_games_use_their_own_starter_untouched(self):
        plan = mm.project_team_rotation([10, 20, 30, 40], {0: 10, 1: 20}, 4)
        self.assertEqual((10, "actual"), plan[0])
        self.assertEqual((20, "actual"), plan[1])

    def test_no_projected_starter_repeats_within_min_rest_games(self):
        """The core owner requirement: a pitcher who just started must not
        be projected again until at least `min_rest_games` OTHER team games
        have happened in between."""
        pool = [10, 20, 30, 40]
        plan = mm.project_team_rotation(pool, {0: 10}, 10, min_rest_games=3)
        sequence = [plan[i][0] for i in range(10)]
        for i in range(len(sequence)):
            for j in range(i + 1, min(i + 4, len(sequence))):  # next 3 games
                self.assertNotEqual(sequence[i], sequence[j],
                                    msg=f"{sequence[i]} repeated at positions {i} and {j}: {sequence}")

    def test_projects_whoever_rested_longest_first(self):
        """Pool ordered most-recent-last-start-first: [40 (most recent), 30,
        20, 10 (rested longest)]. With no games known yet, the very first
        projection must go to 10 -- the one who has rested longest."""
        plan = mm.project_team_rotation([40, 30, 20, 10], {}, 1)
        self.assertEqual(10, plan[0][0])

    def test_a_just_used_starter_is_excluded_from_the_very_next_projection(self):
        """This is the exact bug the second review found on real 2024 data:
        game 1's starter must never be immediately re-projected for game 2."""
        plan = mm.project_team_rotation([40, 30, 20, 10], {0: 40}, 2)
        self.assertNotEqual(40, plan[1][0])

    def test_counts_projected_starts_toward_the_rest_rule_not_just_real_ones(self):
        """'Counting this series's starts': a PROJECTED start earlier in the
        same walk must also block a repeat within min_rest_games, not just
        real/known starts."""
        pool = [10, 20, 30, 40]
        plan = mm.project_team_rotation(pool, {}, 5, min_rest_games=3)
        # plan[0] is a projection (10, rested longest); it must not repeat
        # in any of the next 3 projected games.
        first = plan[0][0]
        for i in range(1, 4):
            self.assertNotEqual(first, plan[i][0])

    def test_never_reads_beyond_its_own_index(self):
        """A pool exactly as large as min_rest_games + 1 has, at every step,
        EXACTLY one legal candidate -- a fully deterministic round-robin,
        checkable by hand rather than merely by absence-of-repeat."""
        pool = [1, 2, 3, 4]  # min_rest_games=3 -> exactly one eligible each time
        plan = mm.project_team_rotation(pool, {}, 8, min_rest_games=3)
        sequence = [plan[i][0] for i in range(8)]
        self.assertEqual([4, 3, 2, 1, 4, 3, 2, 1], sequence)


# ---------------------------------------------------------------------------
# conditional_series_win_prob -- fix 3: state evolution, reusing
# postseason.exact_series_probability completely unmodified.
# ---------------------------------------------------------------------------

class ConditionalSeriesWinProbTests(unittest.TestCase):
    def test_fair_series_from_scratch_is_one_half(self):
        self.assertAlmostEqual(
            0.5, mm.conditional_series_win_prob([0.5] * 7, 0, 0, 4), places=9)

    def test_p_moves_up_after_a_win_and_down_after_a_loss(self):
        """From the SAME prior state (2 wins, 1 loss; fair coin games from
        here on), game 4 either makes it 3-1 (a win) or 2-2 (a loss) -- the
        two possible outcomes of literally the same next game. A win must
        raise P(wins series) above what a loss would leave it at, both
        relative to the 2-1 state itself."""
        before = mm.conditional_series_win_prob([0.5] * 4, 2, 1, 4)
        after_win = mm.conditional_series_win_prob([0.5] * 3, 3, 1, 4)
        after_loss = mm.conditional_series_win_prob([0.5] * 3, 2, 2, 4)
        self.assertGreater(after_win, after_loss)
        self.assertGreater(after_win, before)
        self.assertLess(after_loss, before)
        # 2-2 with 3 fair games left is exactly symmetric (each side needs 2
        # more wins before the other does) -- a sharp, hand-checkable value.
        self.assertAlmostEqual(0.5, after_loss, places=9)

    def test_reaches_exactly_one_when_already_clinched_by_wins(self):
        """Planting NaN in the untouched remainder proves the clinch is
        never read, mirroring tests/test_postseason_solver.py's own
        convention for the unconditioned solver."""
        p = mm.conditional_series_win_prob([float("nan"), float("nan")], 4, 1, 4)
        self.assertEqual(1.0, p)

    def test_reaches_exactly_zero_when_already_clinched_by_losses(self):
        p = mm.conditional_series_win_prob([float("nan"), float("nan")], 1, 4, 4)
        self.assertEqual(0.0, p)

    def test_wrong_length_raises(self):
        with self.assertRaises(mm.MatchupModelError):
            mm.conditional_series_win_prob([0.5] * 3, 0, 0, 4)  # needs 7, not 3

    def test_negative_wins_or_losses_raises(self):
        with self.assertRaises(mm.MatchupModelError):
            mm.conditional_series_win_prob([0.5] * 8, -1, 0, 4)


if __name__ == "__main__":
    unittest.main()
