"""Tests for src/pipeline/mismatch.py.

The centrepiece is TestYamamotoSaleRule. The scanner's whole reason for existing is
that it must stay quiet on a great pitching matchup -- the exact game an
expected-value model would shout loudest about, because a near-even price is where a
small probability difference produces the largest apparent edge. If that suppression
ever stops firing, the scanner has silently reverted to being an EV model.

The second most important test is TestNoPlayIsAResult. An empty slate has to come back
as a complete, correct answer with a verdict, not as an empty list a caller might read
as a failure.
"""

import unittest

from src.pipeline import mismatch


def starters(away_fip=4.60, home_fip=3.30, away_kbb=0.12, home_kbb=0.25,
             known=True, thin=False):
    """Build a pitcher feature dict with the same field names the real builder emits."""
    feats = {
        "both_sp_known": known,
        "either_sp_thin": thin,
        "away_sp_fip": away_fip,
        "home_sp_fip": home_fip,
        "away_sp_k_bb_pct": away_kbb,
        "home_sp_k_bb_pct": home_kbb,
    }
    if None not in (away_fip, home_fip):
        feats["diff_sp_fip"] = round(home_fip - away_fip, 4)
    if None not in (away_kbb, home_kbb):
        feats["diff_sp_k_bb_pct"] = round(home_kbb - away_kbb, 4)
    return feats


def teams(away_rd=-0.60, home_rd=0.70):
    return {"away_run_diff_pg": away_rd, "home_run_diff_pg": home_rd}


GAME = {"game_pk": 1, "date": "2026-08-27", "away_team": "MIA", "home_team": "LAD"}


class TestYamamotoSaleRule(unittest.TestCase):
    """Two good starters means an unpredictable game, whatever the gap between them."""

    def test_both_strong_starters_suppress_the_signal(self):
        # 2.90 vs 3.40: a 0.50 gap, and both comfortably under the strong threshold.
        signal = mismatch.starter_signal(starters(away_fip=2.90, home_fip=3.40))
        self.assertFalse(signal["fires"])
        self.assertIn("both starters are strong", signal["reason"])

    def test_suppression_fires_even_when_the_gap_is_enormous(self):
        # A full run of gap, which would clear OBVIOUS_FIP_GAP on its own -- but both
        # men are still good, so the outcome is still a coin flip. The rule must run
        # BEFORE the gap is measured, not after.
        signal = mismatch.starter_signal(starters(away_fip=2.40, home_fip=3.45,
                                                  away_kbb=0.30, home_kbb=0.18))
        self.assertFalse(signal["fires"])
        self.assertIn("both starters are strong", signal["reason"])
        self.assertTrue(signal["detail"]["both_strong"])

    def test_the_same_gap_fires_when_one_starter_is_not_strong(self):
        # Identical 1.05 gap, shifted so the worse starter is genuinely bad. This is
        # the "superstar on one team and not on the other" case.
        signal = mismatch.starter_signal(starters(away_fip=4.60, home_fip=3.55,
                                                  away_kbb=0.10, home_kbb=0.24))
        self.assertTrue(signal["fires"])
        self.assertEqual(signal["side"], "home")

    def test_a_flagged_game_survives_the_full_scan_but_the_ace_duel_does_not(self):
        duel = dict(GAME, team_features=teams(), pitcher_features=starters(
            away_fip=2.90, home_fip=3.40), ml_away_price=105, ml_home_price=-115)
        self.assertEqual(mismatch.scan_game(
            duel, duel["team_features"], duel["pitcher_features"],
            105, -115)["verdict"], mismatch.NO_PLAY)


class TestStarterSignal(unittest.TestCase):

    def test_unknown_starter_is_not_a_signal(self):
        signal = mismatch.starter_signal(starters(known=False))
        self.assertFalse(signal["fires"])
        self.assertIn("unannounced", signal["reason"])

    def test_thin_sample_is_refused_rather_than_used(self):
        signal = mismatch.starter_signal(starters(thin=True))
        self.assertFalse(signal["fires"])
        self.assertIn("small-sample", signal["reason"])

    def test_close_starters_do_not_fire(self):
        signal = mismatch.starter_signal(starters(away_fip=4.10, home_fip=3.90,
                                                  away_kbb=0.17, home_kbb=0.19))
        self.assertFalse(signal["fires"])
        self.assertIn("close", signal["reason"])

    def test_direction_is_correct_for_fip_where_lower_is_better(self):
        # Away starter is the better one here. Getting this backwards would flag the
        # wrong team on every game and nothing would raise.
        signal = mismatch.starter_signal(starters(away_fip=3.20, home_fip=4.90,
                                                  away_kbb=0.26, home_kbb=0.11))
        self.assertEqual(signal["side"], "away")

    def test_direction_is_correct_for_k_bb_where_higher_is_better(self):
        # FIP gap deliberately below threshold so only K-BB% decides the side.
        signal = mismatch.starter_signal(starters(away_fip=4.20, home_fip=3.90,
                                                  away_kbb=0.28, home_kbb=0.10))
        self.assertTrue(signal["fires"])
        self.assertEqual(signal["side"], "away")

    def test_contradicting_rates_do_not_fire(self):
        # FIP says home is much better, K-BB% says away is much better.
        signal = mismatch.starter_signal(starters(away_fip=5.20, home_fip=3.90,
                                                  away_kbb=0.30, home_kbb=0.12))
        self.assertFalse(signal["fires"])
        self.assertIn("disagree", signal["reason"])


class TestRosterSignal(unittest.TestCase):

    def test_thin_team_sample_is_refused(self):
        signal = mismatch.roster_signal(teams(away_rd=None, home_rd=0.7))
        self.assertFalse(signal["fires"])
        self.assertIn("fewer than", signal["reason"])

    def test_close_teams_do_not_fire(self):
        signal = mismatch.roster_signal(teams(away_rd=0.10, home_rd=0.30))
        self.assertFalse(signal["fires"])

    def test_large_gap_fires_toward_the_better_team(self):
        signal = mismatch.roster_signal(teams(away_rd=-0.80, home_rd=0.90))
        self.assertTrue(signal["fires"])
        self.assertEqual(signal["side"], "home")
        self.assertAlmostEqual(signal["magnitude"], 1.70, places=4)


class TestMarketScreen(unittest.TestCase):
    """The screen asks whether the gap is already priced -- never whether it is +EV."""

    def test_blown_out_favourite_is_screened_out(self):
        screen = mismatch.market_screen(320, -400, "home")
        self.assertFalse(screen["fires"])
        self.assertIn("already prices", screen["reason"])

    def test_modest_favourite_passes(self):
        screen = mismatch.market_screen(120, -140, "home")
        self.assertTrue(screen["fires"])

    def test_screen_is_applied_to_the_flagged_side_not_the_favourite(self):
        # Market likes home; our signals like away. The away price is the long one,
        # so the screen must pass -- screening on the favourite would wrongly kill it.
        screen = mismatch.market_screen(320, -400, "away")
        self.assertTrue(screen["fires"])

    def test_missing_prices_do_not_fabricate_a_screen(self):
        screen = mismatch.market_screen(None, -140, "home")
        self.assertFalse(screen["fires"])
        self.assertIsNone(screen["detail"].get("side_fair_prob"))

    def test_probabilities_reported_are_devigged_not_raw(self):
        screen = mismatch.market_screen(-110, -110, "home")
        # Raw implied on -110 is 0.5238; de-vigged it is 0.5000.
        self.assertAlmostEqual(screen["detail"]["home_fair_prob"], 0.5, places=4)


class TestScanGame(unittest.TestCase):

    def test_two_agreeing_signals_and_a_live_price_flag_the_game(self):
        scan = mismatch.scan_game(GAME, teams(), starters(), 150, -170)
        self.assertEqual(scan["verdict"], mismatch.FLAGGED)
        self.assertEqual(scan["side"], "home")

    def test_one_signal_alone_is_below_the_bar(self):
        # Starters lopsided, teams level. Reported, not flagged.
        scan = mismatch.scan_game(GAME, teams(away_rd=0.10, home_rd=0.20),
                                  starters(), 150, -170)
        self.assertEqual(scan["verdict"], mismatch.NO_PLAY)
        self.assertEqual(scan["side"], "home")
        self.assertIn("single signal", scan["summary"])

    def test_signals_pointing_opposite_ways_are_not_obvious(self):
        scan = mismatch.scan_game(GAME, teams(away_rd=0.90, home_rd=-0.80),
                                  starters(), 150, -170)
        self.assertEqual(scan["verdict"], mismatch.NO_PLAY)
        self.assertIn("contradict", scan["summary"])

    def test_an_already_priced_mismatch_is_not_flagged(self):
        scan = mismatch.scan_game(GAME, teams(), starters(), 380, -500)
        self.assertEqual(scan["verdict"], mismatch.NO_PLAY)
        self.assertIn("already prices", scan["summary"])

    def test_every_verdict_carries_reasons(self):
        for feats in (teams(), teams(away_rd=0.1, home_rd=0.2)):
            scan = mismatch.scan_game(GAME, feats, starters(), 150, -170)
            self.assertTrue(scan["reasons"])
            self.assertTrue(all(r for r in scan["reasons"]))


class TestMarketRouting(unittest.TestCase):
    """A starter gap lives in innings one to five; a roster gap lives in all nine."""

    def test_starter_only_mismatch_routes_to_first_five(self):
        route = mismatch.route_market({"fires": True}, {"fires": False})
        self.assertEqual(route["market"], mismatch.MARKET_F5)
        self.assertIn("bullpen", route["why"])

    def test_roster_only_mismatch_routes_to_the_full_game(self):
        route = mismatch.route_market({"fires": False}, {"fires": True})
        self.assertEqual(route["market"], mismatch.MARKET_FULL)

    def test_both_firing_routes_to_first_five(self):
        route = mismatch.route_market({"fires": True}, {"fires": True})
        self.assertEqual(route["market"], mismatch.MARKET_F5)

    def test_a_flagged_game_carries_its_market(self):
        scan = mismatch.scan_game(GAME, teams(), starters(), 150, -170)
        self.assertEqual(scan["market"], mismatch.MARKET_F5)


class TestNoPlayIsAResult(unittest.TestCase):
    """A quiet day is a correct answer, not an empty response."""

    def test_a_slate_with_nothing_on_it_reports_a_verdict(self):
        games = [dict(GAME, game_pk=i,
                      team_features=teams(away_rd=0.1, home_rd=0.2),
                      pitcher_features=starters(away_fip=3.90, home_fip=4.00,
                                                away_kbb=0.18, home_kbb=0.19),
                      ml_away_price=105, ml_home_price=-115)
                 for i in range(12)]
        result = mismatch.scan_slate(games)
        self.assertEqual(result["verdict"], mismatch.NO_PLAY)
        self.assertEqual(result["games_scanned"], 12)
        self.assertEqual(result["flagged"], [])
        self.assertIn("No play", result["summary"])
        self.assertIn("Most days look like this", result["summary"])

    def test_an_empty_date_is_not_an_error(self):
        result = mismatch.scan_slate([])
        self.assertEqual(result["verdict"], mismatch.NO_PLAY)
        self.assertIn("no games", result["summary"])

    def test_every_scanned_game_appears_in_scans_even_when_nothing_flags(self):
        games = [dict(GAME, game_pk=i, team_features=teams(0.1, 0.2),
                      pitcher_features=starters(known=False))
                 for i in range(5)]
        self.assertEqual(len(mismatch.scan_slate(games)["scans"]), 5)

    def test_a_flagged_slate_names_the_game_and_the_market(self):
        games = [
            dict(GAME, game_pk=1, team_features=teams(0.1, 0.2),
                 pitcher_features=starters(known=False)),
            dict(GAME, game_pk=2, away_team="COL", home_team="NYY",
                 team_features=teams(), pitcher_features=starters(),
                 ml_away_price=150, ml_home_price=-170),
        ]
        result = mismatch.scan_slate(games)
        self.assertEqual(result["verdict"], mismatch.FLAGGED)
        self.assertEqual(len(result["flagged"]), 1)
        self.assertIn("COL @ NYY", result["summary"])
        self.assertIn("first five", result["summary"])


class TestThresholdsArePreRegistered(unittest.TestCase):
    """These constants are the scanner's hypothesis. Changing one changes what it means.

    The test does not assert the values are correct -- nothing here can know that. It
    asserts they are what was written down before any result was seen, so that a later
    quiet tweak toward whatever would have won shows up as a failing test rather than
    as a diff nobody reads.
    """

    def test_pre_registered_values(self):
        self.assertEqual(mismatch.OBVIOUS_FIP_GAP, 1.00)
        self.assertEqual(mismatch.OBVIOUS_K_BB_GAP, 0.10)
        self.assertEqual(mismatch.STRONG_FIP, 3.50)
        self.assertEqual(mismatch.OBVIOUS_RUN_DIFF_GAP, 1.00)
        self.assertEqual(mismatch.ALREADY_PRICED_PROB, 0.65)
        self.assertEqual(mismatch.MIN_AGREEING_SIGNALS, 2)

    def test_sample_gates_track_the_feature_builders(self):
        from src.pipeline import features, pitchers
        self.assertEqual(mismatch.MIN_INNINGS, pitchers.MIN_INNINGS_FOR_RATES)
        self.assertEqual(mismatch.MIN_TEAM_GAMES, features.MIN_GAMES_FOR_RATES)


if __name__ == "__main__":
    unittest.main()
