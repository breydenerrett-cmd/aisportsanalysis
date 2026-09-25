"""tests/test_postseason_bracket.py -- C1b: the bracket engine
(src/analysis/postseason.py's bracket-engine section), exercised over
SYNTHETIC brackets only.

Every team code and win_pct in this file is fictitious (A1..A6 / N1..N6, or
similarly obvious placeholders) -- never a real 2026 contender, per the
task's "do not hardcode any current contenders list." The engine itself is
generic over whatever bracket and win_prob_fn a caller supplies; these tests
exist to prove the WALK is correct (normalization, no eliminated team
advancing, the fixed non-re-seeded Division Series bracket, and the World
Series' record-based-not-seed-based home field), not to say anything about
any real team's chances.
"""

from __future__ import annotations

import unittest

from src.analysis import postseason as ps
from src.analysis import postseason_config as pc


def _team(name, seed, win_pct):
    return {"team": name, "seed": seed, "win_pct": win_pct}


def _symmetric_bracket():
    """Every team's a placeholder; win_pct values are all distinct (so nothing
    hits the World Series exact-tie raise) but otherwise carry no meaning."""
    al = {s: _team(f"AL{s}", s, 0.500 + 0.001 * s) for s in range(1, 7)}
    nl = {s: _team(f"NL{s}", s, 0.520 + 0.001 * s) for s in range(1, 7)}
    return {"AL": al, "NL": nl}


def _always_half(_team_a, _team_b):
    return 0.5


def _log5(pa, pb):
    denom = pa + pb - 2 * pa * pb
    if denom <= 0:
        return 0.5
    return (pa - pa * pb) / denom


def _make_win_prob_fn(strengths):
    def fn(team_a, team_b):
        return _log5(strengths[team_a], strengths[team_b])
    return fn


def _asymmetric_bracket():
    """A synthetic, clearly-fictitious bracket where strength decreases
    with seed number -- used only to exercise the engine over non-trivial,
    non-symmetric probabilities. Not a claim about any real team.

    win_pct ranges are kept strictly disjoint across leagues (every AL
    value above every NL value) so no synthetic World Series pairing can
    ever land on an exact win_pct tie and trip the deliberate
    can't-resolve-a-tie raise.
    """
    al_strengths = [0.60, 0.57, 0.54, 0.51, 0.48, 0.45]
    nl_strengths = [0.58, 0.55, 0.52, 0.49, 0.46, 0.43]
    al = {s: _team(f"A{s}", s, 0.700 - 0.01 * s) for s in range(1, 7)}   # 0.69..0.64
    nl = {s: _team(f"N{s}", s, 0.400 - 0.01 * s) for s in range(1, 7)}   # 0.39..0.34
    strengths = {}
    for s in range(1, 7):
        strengths[f"A{s}"] = al_strengths[s - 1]
        strengths[f"N{s}"] = nl_strengths[s - 1]
    return {"AL": al, "NL": nl}, _make_win_prob_fn(strengths)


class SymmetricNoHomeEdgeExactValueTests(unittest.TestCase):
    """With every pairwise neutral probability at 0.5 and home_edge=0, every
    series in the bracket is an exact coin flip regardless of format, so the
    pennant and World Series probabilities are hand-derivable exactly:

      bye seeds (1, 2):   skip Wild Card (prob 1) -> DS (1/2) -> LCS (1/2)
                           = 0.25 pennant probability each
      field seeds (3-6):  WC (1/2) -> DS (1/2) -> LCS (1/2)
                           = 0.125 pennant probability each

      sum check: 2*0.25 + 4*0.125 = 1.0

    and with home_edge=0 the World Series is ALSO an exact coin flip
    regardless of who is awarded home field, so each team's overall title
    probability is exactly half its own pennant probability.
    """

    def test_bye_seeds_have_exactly_one_quarter_pennant_probability(self):
        bracket = _symmetric_bracket()
        result = ps.league_pennant_probabilities(bracket["AL"], _always_half,
                                                  home_edge=0.0)
        self.assertAlmostEqual(0.25, result["wins_pennant"]["AL1"], places=9)
        self.assertAlmostEqual(0.25, result["wins_pennant"]["AL2"], places=9)

    def test_field_seeds_have_exactly_one_eighth_pennant_probability(self):
        bracket = _symmetric_bracket()
        result = ps.league_pennant_probabilities(bracket["AL"], _always_half,
                                                  home_edge=0.0)
        for s in (3, 4, 5, 6):
            self.assertAlmostEqual(0.125, result["wins_pennant"][f"AL{s}"],
                                   places=9, msg=f"seed {s}")

    def test_world_series_win_probabilities_are_exact_under_full_symmetry(self):
        bracket = _symmetric_bracket()
        result = ps.bracket_probabilities(bracket, _always_half, home_edge=0.0)
        ws = result["world_series"]["wins_world_series"]
        self.assertAlmostEqual(0.125, ws["AL1"], places=9)
        self.assertAlmostEqual(0.125, ws["AL2"], places=9)
        for s in (3, 4, 5, 6):
            self.assertAlmostEqual(0.0625, ws[f"AL{s}"], places=9, msg=f"AL seed {s}")
            self.assertAlmostEqual(0.0625, ws[f"NL{s}"], places=9, msg=f"NL seed {s}")
        self.assertAlmostEqual(1.0, sum(ws.values()), places=9)


class NormalizationTests(unittest.TestCase):
    """'Normalized advancement probabilities per team': the invariants that
    must hold for ANY bracket, not just the symmetric special case above."""

    def test_reaches_division_series_sums_to_four(self):
        bracket, fn = _asymmetric_bracket()
        result = ps.league_pennant_probabilities(bracket["AL"], fn, home_edge=0.02)
        self.assertAlmostEqual(4.0, sum(result["reaches_division_series"].values()),
                               places=9)

    def test_reaches_lcs_sums_to_two(self):
        bracket, fn = _asymmetric_bracket()
        result = ps.league_pennant_probabilities(bracket["AL"], fn, home_edge=0.02)
        self.assertAlmostEqual(2.0, sum(result["reaches_lcs"].values()), places=9)

    def test_wins_pennant_sums_to_one_for_each_league(self):
        bracket, fn = _asymmetric_bracket()
        for lg in ("AL", "NL"):
            result = ps.league_pennant_probabilities(bracket[lg], fn, home_edge=0.02)
            self.assertAlmostEqual(1.0, sum(result["wins_pennant"].values()),
                                   places=9, msg=lg)

    def test_wins_world_series_sums_to_one(self):
        bracket, fn = _asymmetric_bracket()
        result = ps.bracket_probabilities(bracket, fn, home_edge=0.02)
        total = sum(result["world_series"]["wins_world_series"].values())
        self.assertAlmostEqual(1.0, total, places=9)

    def test_no_probability_is_negative_or_above_one_anywhere(self):
        bracket, fn = _asymmetric_bracket()
        result = ps.bracket_probabilities(bracket, fn, home_edge=0.02)
        for lg in ("AL", "NL"):
            for field in ("reaches_division_series", "reaches_lcs", "wins_pennant"):
                for team, p in result[lg][field].items():
                    self.assertGreaterEqual(p, -1e-12, f"{lg}.{field}.{team}")
                    self.assertLessEqual(p, 1.0 + 1e-9, f"{lg}.{field}.{team}")
        for team, p in result["world_series"]["wins_world_series"].items():
            self.assertGreaterEqual(p, -1e-12, team)
            self.assertLessEqual(p, 1.0 + 1e-9, team)

    def test_better_seed_has_a_higher_pennant_probability_than_the_worst_seed(self):
        bracket, fn = _asymmetric_bracket()
        result = ps.league_pennant_probabilities(bracket["AL"], fn, home_edge=0.02)
        self.assertGreater(result["wins_pennant"]["A1"], result["wins_pennant"]["A6"])


class NoEliminatedTeamAdvancesTests(unittest.TestCase):
    """`game_probs_from_pattern` clips away from exact 0/1 on purpose (never
    fabricate a certainty -- see its docstring), so a team forced to a
    ~1%-per-game underdog in every series it could possibly play does not
    reach an exact 0.0 probability anywhere downstream; it reaches
    NEGLIGIBLE probability. That is the correct, intended behaviour, and
    these tests check for it directly rather than asserting an exact zero
    that the clipping design makes structurally unreachable through the
    public win_prob_fn interface. (The exact, bit-for-bit zero case IS
    tested, at the solver level where no clipping happens, by
    tests/test_postseason_solver.py::DegenerateTests.)
    """

    def _forced_loser_bracket(self):
        bracket = _symmetric_bracket()

        def fn(team_a, team_b):
            if team_a == "AL6":
                return 0.0
            if team_b == "AL6":
                return 1.0
            return 0.5

        return bracket, fn

    def test_a_guaranteed_wild_card_loser_has_negligible_probability_from_then_on(self):
        bracket, fn = self._forced_loser_bracket()
        result = ps.bracket_probabilities(bracket, fn, home_edge=0.0)
        self.assertLess(result["AL"]["wins_pennant"]["AL6"], 1e-6)
        self.assertLess(result["AL"]["reaches_lcs"]["AL6"], 1e-6)
        self.assertLess(result["world_series"]["wins_world_series"].get("AL6", 0.0), 1e-6)
        # AL3 (its overwhelmingly likely Wild Card conqueror) picks up
        # essentially all of the DS slot AL6 would otherwise have taken.
        self.assertGreater(result["AL"]["reaches_division_series"]["AL3"], 0.999)

    def test_eliminated_teams_only_reach_later_rounds_with_negligible_path_probability(self):
        bracket, fn = self._forced_loser_bracket()
        result = ps.bracket_probabilities(bracket, fn, home_edge=0.0)
        for d in result["AL"]["series_detail"]:
            if d["round"] != pc.WILD_CARD["name"] and "AL6" in (d["team_a"], d["team_b"]):
                self.assertLess(
                    d.get("path_prob", 0.0), 1e-3,
                    "AL6 (a forced near-certain Wild Card loser) should only "
                    "reach a later round along a negligible-probability branch")


class FixedDivisionSeriesBracketTests(unittest.TestCase):
    """Verified: the Division Series is NOT re-seeded after the Wild Card
    round. Seed 1 always faces the ACTUAL 4-vs-5 winner, whoever that turns
    out to be."""

    def test_seed_one_faces_the_actual_four_vs_five_winner_not_a_reseed(self):
        bracket = _symmetric_bracket()

        def fn(team_a, team_b):
            # Force both Wild Card results to near-certainty (AL3 over AL6,
            # AL5 -- the WORSE seed -- over AL4) so there is one dominant
            # bracket to check, and a re-seeding engine would disagree with
            # a fixed-bracket engine about who seed 1 plays next.
            if team_a == "AL5" or team_a == "AL3":
                return 1.0
            if team_b == "AL5" or team_b == "AL3":
                return 0.0
            return 0.5

        result = ps.league_pennant_probabilities(bracket["AL"], fn, home_edge=0.0)
        ds_detail = [d for d in result["series_detail"]
                    if d["round"] == pc.DIVISION_SERIES["name"]]
        # Restrict to the dominant (near-certain) branch: game_probs_from_
        # pattern clips away from an exact 0/1 win_prob_fn, so an
        # exhaustive exact walk still enumerates the negligible-probability
        # "AL4 upsets AL5" branch too -- correctly, since that is what
        # exact enumeration means. Only the dominant branch is a fair test
        # of the pairing RULE itself.
        dominant = [d for d in ds_detail
                   if "AL1" in (d["team_a"], d["team_b"]) and d["path_prob"] > 0.9]
        self.assertTrue(dominant)
        for d in dominant:
            self.assertIn("AL5", (d["team_a"], d["team_b"]),
                          "seed 1 must face AL5 (the actual 4-vs-5 winner), "
                          "not a re-seeded opponent")


class VenueAndChronologyTests(unittest.TestCase):
    """The home_pattern returned for one series must be exactly the
    verified pattern (in game order) from the home-field holder's
    perspective, and its exact complement from the other side's."""

    def test_division_series_pattern_matches_for_the_higher_seed(self):
        a = _team("HI", 1, 0.55)
        b = _team("LO", 4, 0.50)
        detail = ps.series_probabilities_for_round(a, b, pc.DIVISION_SERIES,
                                                    _always_half, home_edge=0.03)
        self.assertEqual(pc.DIVISION_SERIES["home_pattern"], detail["team_a_home_pattern"])
        self.assertEqual("HI", detail["home_field_holder"])

    def test_pattern_flips_when_team_a_is_the_lower_seed(self):
        a = _team("LO", 4, 0.50)
        b = _team("HI", 1, 0.55)
        detail = ps.series_probabilities_for_round(a, b, pc.DIVISION_SERIES,
                                                    _always_half, home_edge=0.03)
        expected = tuple(not f for f in pc.DIVISION_SERIES["home_pattern"])
        self.assertEqual(expected, detail["team_a_home_pattern"])
        self.assertEqual("HI", detail["home_field_holder"])

    def test_wild_card_pattern_is_all_home_for_the_higher_seed(self):
        a = _team("HI", 3, 0.52)
        b = _team("LO", 6, 0.50)
        detail = ps.series_probabilities_for_round(a, b, pc.WILD_CARD,
                                                    _always_half, home_edge=0.02)
        self.assertEqual((True, True, True), detail["team_a_home_pattern"])
        self.assertEqual(3, detail["game_probs_team_a"].__len__())


class WorldSeriesHomeFieldIsRecordBasedTests(unittest.TestCase):
    def test_better_record_hosts_even_with_a_worse_seed(self):
        al = _team("AL4", 4, 0.610)   # worse seed, better record
        nl = _team("NL1", 1, 0.560)   # better seed, worse record
        detail = ps.series_probabilities_for_round(al, nl, pc.WORLD_SERIES,
                                                    _always_half, home_edge=0.03)
        self.assertEqual("AL4", detail["home_field_holder"])
        self.assertEqual(pc.WORLD_SERIES["home_pattern"], detail["team_a_home_pattern"])

    def test_tied_regular_season_record_raises_rather_than_guessing(self):
        al = _team("AL1", 1, 0.555)
        nl = _team("NL1", 1, 0.555)
        with self.assertRaises(ps.PostseasonError):
            ps.series_probabilities_for_round(al, nl, pc.WORLD_SERIES,
                                              _always_half, home_edge=0.03)

    def test_lcs_by_contrast_is_seed_based_not_record_based(self):
        a = _team("BetterSeedWorseRecord", 1, 0.500)
        b = _team("WorseSeedBetterRecord", 2, 0.620)
        detail = ps.series_probabilities_for_round(a, b, pc.LCS,
                                                    _always_half, home_edge=0.03)
        self.assertEqual("BetterSeedWorseRecord", detail["home_field_holder"])


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_give_the_same_output(self):
        bracket, fn = _asymmetric_bracket()
        r1 = ps.bracket_probabilities(bracket, fn, home_edge=0.02)
        r2 = ps.bracket_probabilities(bracket, fn, home_edge=0.02)
        self.assertEqual(r1["AL"]["wins_pennant"], r2["AL"]["wins_pennant"])
        self.assertEqual(r1["NL"]["reaches_division_series"],
                         r2["NL"]["reaches_division_series"])
        self.assertEqual(r1["world_series"]["wins_world_series"],
                         r2["world_series"]["wins_world_series"])


class BracketValidationTests(unittest.TestCase):
    def test_missing_league_raises(self):
        bracket = _symmetric_bracket()
        del bracket["NL"]
        with self.assertRaises(ps.PostseasonError):
            ps.bracket_probabilities(bracket, _always_half, home_edge=0.02)

    def test_duplicate_team_name_within_a_league_raises(self):
        bracket = _symmetric_bracket()
        bracket["AL"][2] = _team("AL1", 2, 0.501)  # collides with seed 1's name
        with self.assertRaises(ps.PostseasonError):
            ps.league_pennant_probabilities(bracket["AL"], _always_half, home_edge=0.02)

    def test_duplicate_team_name_across_leagues_raises(self):
        bracket = _symmetric_bracket()
        bracket["NL"][1] = _team("AL1", 1, 0.521)  # collides with AL seed 1
        with self.assertRaises(ps.PostseasonError):
            ps.bracket_probabilities(bracket, _always_half, home_edge=0.02)

    def test_missing_seed_raises(self):
        bracket = _symmetric_bracket()
        del bracket["AL"][3]
        with self.assertRaises(ps.PostseasonError):
            ps.league_pennant_probabilities(bracket["AL"], _always_half, home_edge=0.02)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
