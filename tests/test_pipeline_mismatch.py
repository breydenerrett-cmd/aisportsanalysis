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

    def test_the_ace_duel_never_even_becomes_a_candidate(self):
        scan = mismatch.scan_game(GAME, teams(),
                                  starters(away_fip=2.90, home_fip=3.40))
        self.assertEqual(scan["verdict"], mismatch.NO_PLAY)


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
    """Stage one is talent only. No price may reach it."""

    def test_two_agreeing_signals_make_a_candidate_not_a_flag(self):
        scan = mismatch.scan_game(GAME, teams(), starters())
        self.assertEqual(scan["verdict"], mismatch.CANDIDATE)
        self.assertEqual(scan["side"], "home")
        self.assertEqual(scan["market"], mismatch.MARKET_F5)
        # Unpriced, so no market signal exists yet.
        self.assertNotIn("market", scan["signals"])

    def test_one_signal_alone_is_below_the_bar(self):
        scan = mismatch.scan_game(GAME, teams(away_rd=0.10, home_rd=0.20), starters())
        self.assertEqual(scan["verdict"], mismatch.NO_PLAY)
        self.assertEqual(scan["side"], "home")
        self.assertIn("single signal", scan["summary"])

    def test_signals_pointing_opposite_ways_are_not_obvious(self):
        scan = mismatch.scan_game(GAME, teams(away_rd=0.90, home_rd=-0.80), starters())
        self.assertEqual(scan["verdict"], mismatch.NO_PLAY)
        self.assertIn("contradict", scan["summary"])

    def test_every_verdict_carries_reasons(self):
        for feats in (teams(), teams(away_rd=0.1, home_rd=0.2)):
            scan = mismatch.scan_game(GAME, feats, starters())
            self.assertTrue(scan["reasons"])
            self.assertTrue(all(r for r in scan["reasons"]))


class TestScreenRunsOnTheRoutedMarket(unittest.TestCase):
    """The defect the two-stage split exists to fix.

    Measured live on 27 Aug 2026: both flagged games' first-five prices de-vigged
    SHORTER than their full-game prices, because a first-five line is a starter line
    and is priced as one. MIL @ NYM passed a 0.65 screen on the full game at 64.1%
    and would have failed it on the F5 market at 65.2% -- the market it was being
    routed to. A single-stage scanner screens on whatever price it happens to hold,
    which is the wrong one for every F5-routed game.
    """

    def test_a_candidate_needs_a_price_to_become_a_flag(self):
        candidate = mismatch.scan_game(GAME, teams(), starters())
        flagged = mismatch.apply_market_screen(candidate, 150, -170)
        self.assertEqual(flagged["verdict"], mismatch.FLAGGED)

    def test_the_same_candidate_fails_on_a_shorter_routed_price(self):
        # +160/-190 de-vigs home to 0.6301 and passes; +180/-220 de-vigs to 0.6581
        # and does not. That gap is the whole defect: it is roughly the distance
        # measured live between a full-game price and the first-five price of the
        # same game, and the screen has to see the second one.
        candidate = mismatch.scan_game(GAME, teams(), starters())
        self.assertEqual(
            mismatch.apply_market_screen(candidate, 160, -190)["verdict"],
            mismatch.FLAGGED)
        self.assertEqual(
            mismatch.apply_market_screen(candidate, 180, -220)["verdict"],
            mismatch.NO_PLAY)

    def test_the_screen_records_which_market_it_priced(self):
        candidate = mismatch.scan_game(GAME, teams(), starters())
        screened = mismatch.apply_market_screen(candidate, 150, -170)
        self.assertEqual(screened["signals"]["market"]["priced_market"],
                         candidate["market"])

    def test_screening_does_not_mutate_the_candidate(self):
        candidate = mismatch.scan_game(GAME, teams(), starters())
        mismatch.apply_market_screen(candidate, 160, -190)
        self.assertEqual(candidate["verdict"], mismatch.CANDIDATE)
        self.assertNotIn("market", candidate["signals"])

    def test_screening_a_non_candidate_changes_nothing(self):
        scan = mismatch.scan_game(GAME, teams(0.1, 0.2), starters())
        self.assertEqual(mismatch.apply_market_screen(scan, 150, -170)["verdict"],
                         mismatch.NO_PLAY)


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

    def test_a_candidate_carries_its_market_before_any_price_exists(self):
        # The routing has to be known BEFORE pricing, because it decides which price
        # to buy -- and first-five prices are billed per game.
        scan = mismatch.scan_game(GAME, teams(), starters())
        self.assertEqual(scan["market"], mismatch.MARKET_F5)


class TestNoPlayIsAResult(unittest.TestCase):
    """A quiet day is a correct answer, not an empty response."""

    def test_a_slate_with_nothing_on_it_reports_a_verdict(self):
        games = [dict(GAME, game_pk=i,
                      team_features=teams(away_rd=0.1, home_rd=0.2),
                      pitcher_features=starters(away_fip=3.90, home_fip=4.00,
                                                away_kbb=0.18, home_kbb=0.19))
                 for i in range(12)]
        result = mismatch.scan_slate(games)
        self.assertEqual(result["verdict"], mismatch.NO_PLAY)
        self.assertEqual(result["games_scanned"], 12)
        self.assertEqual(result["candidates"], [])
        self.assertIn("No play", result["summary"])
        self.assertIn("Most days look like this", result["summary"])

    def test_an_empty_date_is_not_an_error(self):
        result = mismatch.scan_slate([])
        self.assertEqual(result["verdict"], mismatch.NO_PLAY)
        self.assertIn("no games", result["summary"])

    def test_every_scanned_game_appears_in_scans_even_when_nothing_fires(self):
        games = [dict(GAME, game_pk=i, team_features=teams(0.1, 0.2),
                      pitcher_features=starters(known=False))
                 for i in range(5)]
        self.assertEqual(len(mismatch.scan_slate(games)["scans"]), 5)

    def test_stage_one_reports_candidates_and_flags_nothing(self):
        games = [
            dict(GAME, game_pk=1, team_features=teams(0.1, 0.2),
                 pitcher_features=starters(known=False)),
            dict(GAME, game_pk=2, away_team="COL", home_team="NYY",
                 team_features=teams(), pitcher_features=starters()),
        ]
        result = mismatch.scan_slate(games)
        self.assertEqual(result["verdict"], mismatch.CANDIDATE)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["flagged"], [])
        self.assertFalse(result["priced"])
        self.assertIn("COL @ NYY", result["summary"])
        self.assertIn("first five", result["summary"])


class TestFinalizeSlate(unittest.TestCase):

    def slate(self):
        return mismatch.scan_slate([
            dict(GAME, game_pk=1, team_features=teams(0.1, 0.2),
                 pitcher_features=starters(known=False)),
            dict(GAME, game_pk=2, away_team="COL", home_team="NYY",
                 team_features=teams(), pitcher_features=starters()),
        ])

    def test_a_priced_candidate_becomes_a_flag(self):
        final = mismatch.finalize_slate(
            self.slate(), {2: {"away_price": 150, "home_price": -170}})
        self.assertEqual(final["verdict"], mismatch.FLAGGED)
        self.assertEqual(len(final["flagged"]), 1)

    def test_an_unpriced_candidate_stays_a_candidate_rather_than_being_flagged(self):
        # A missing screen is not a pass. Treating it as one would flag every game
        # whose F5 price happened to be unavailable, which is the opposite of a
        # scanner that stays quiet.
        final = mismatch.finalize_slate(self.slate(), {})
        self.assertEqual(final["flagged"], [])
        self.assertEqual(len(final["candidates"]), 1)
        self.assertEqual(final["verdict"], mismatch.NO_PLAY)
        self.assertIn("could not be priced", final["summary"])

    def test_a_screened_out_candidate_is_neither_flagged_nor_still_a_candidate(self):
        final = mismatch.finalize_slate(
            self.slate(), {2: {"away_price": 380, "home_price": -500}})
        self.assertEqual(final["flagged"], [])
        self.assertEqual(final["candidates"], [])
        screened = [s for s in final["scans"] if s["game_pk"] == 2][0]
        self.assertEqual(screened["verdict"], mismatch.NO_PLAY)
        self.assertIn("already prices", screened["summary"])
        # The slate summary must not claim an unpriced quiet day when the quiet
        # came from a screen that actually ran.
        self.assertNotIn("could not be priced", final["summary"])

    def test_non_candidates_pass_through_untouched(self):
        final = mismatch.finalize_slate(
            self.slate(), {1: {"away_price": 150, "home_price": -170}})
        passed = [s for s in final["scans"] if s["game_pk"] == 1][0]
        self.assertEqual(passed["verdict"], mismatch.NO_PLAY)
        self.assertNotIn("market", passed["signals"])


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


class TestFirstFivePushSemantics(unittest.TestCase):
    """A first-five moneyline is two-way and tie-refunded, so its de-vig is conditional.

    Measured on 558 final regular-season games: the first five ended level 15.9% of
    the time. Every book in the feed offers the market two-way, which means a push,
    not a loss -- and de-vigging a tie-refunded two-way market gives P(win | no push),
    not P(win). Reading 0.65 there as an unconditional probability overstates it by
    about a sixth.
    """

    def test_a_first_five_screen_says_what_the_number_means(self):
        screen = mismatch.market_screen(150, -170, "home", market=mismatch.MARKET_F5)
        self.assertIn("ties refunded", screen["reason"])
        self.assertTrue(screen["detail"]["conditional_on_no_push"])

    def test_a_full_game_screen_does_not_claim_a_push(self):
        screen = mismatch.market_screen(150, -170, "home", market=mismatch.MARKET_FULL)
        self.assertNotIn("ties refunded", screen["reason"])
        self.assertNotIn("conditional_on_no_push", screen["detail"])

    def test_the_qualifier_appears_on_rejections_too(self):
        screen = mismatch.market_screen(380, -500, "home", market=mismatch.MARKET_F5)
        self.assertFalse(screen["fires"])
        self.assertIn("ties refunded", screen["reason"])

    def test_finalizing_an_f5_candidate_carries_the_qualifier_through(self):
        candidate = mismatch.scan_game(GAME, teams(), starters())
        self.assertEqual(candidate["market"], mismatch.MARKET_F5)
        screened = mismatch.apply_market_screen(candidate, 150, -170)
        self.assertIn("ties refunded", screened["signals"]["market"]["reason"])

    def test_the_measured_push_rate_is_recorded(self):
        # Pre-registered alongside the thresholds: it is the number that makes the
        # two screens incommensurable, and a later quiet edit should be visible.
        self.assertEqual(mismatch.FIRST_FIVE_PUSH_RATE, 0.159)
