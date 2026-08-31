"""Tests for src/detect/detectors.py and the dossier they read from.

The centrepiece is TestImpliedBullpenDisagreement. That detector is the project's
most original idea -- the full-game minus first-five price gap IS the market's
bullpen opinion -- and it is only meaningful if the two prices are de-vigged and
subtracted in the right order. A sign error there would silently credit the wrong
bullpen on every game in the league.
"""

import unittest

from src.analysis import synthesis
from src.detect import base, detectors
from src.detect import dossier as dossier_mod


def dossier(market=None, bullpen=None, starters=None,
            away="BOS", home="NYY"):
    d = dossier_mod.Dossier({"away_team": away, "home_team": home,
                             "date": "2026-08-28", "game_pk": 1})
    if market is not None:
        d.add("market", market)
    if bullpen is not None:
        d.add("bullpen", bullpen)
    if starters is not None:
        d.add("starters", starters)
    return d


def pen(team, unavailable=0, arms=8):
    relievers = []
    for i in range(arms):
        status = (detectors.bullpen_mod.LIKELY_UNAVAILABLE if i < unavailable
                  else detectors.bullpen_mod.AVAILABLE)
        relievers.append({"name": f"{team}{i}", "availability": status,
                          "innings": 1.0, "availability_reason": "because"})
    return {"team": team, "relievers": relievers, "total_innings": float(arms),
            "window_days": 7}


class TestImpliedBullpenDisagreement(unittest.TestCase):

    def setUp(self):
        self.detector = detectors.ImpliedBullpenDisagreement()

    def test_no_first_five_price_means_no_finding(self):
        self.assertEqual(self.detector.run(dossier(market={"markets": {}})), [])

    def test_the_market_read_is_reported_with_the_right_side(self):
        # A positive shift means the HOME side gains from innings 6-9.
        found = self.detector.run(dossier(
            market={"implied_bullpen_shift": 0.044, "markets": {}}))
        self.assertEqual(found[0].side, base.HOME)
        self.assertIn("NYY", found[0].claim)

    def test_a_negative_shift_credits_the_away_bullpen(self):
        # The sign error this guards would credit the wrong pen on every game.
        found = self.detector.run(dossier(
            market={"implied_bullpen_shift": -0.044, "markets": {}}))
        self.assertEqual(found[0].side, base.AWAY)
        self.assertIn("BOS", found[0].claim)

    def test_it_fires_when_the_favoured_pen_is_the_gassed_one(self):
        found = self.detector.run(dossier(
            market={"implied_bullpen_shift": 0.04, "markets": {}},
            bullpen={"NYY": pen("NYY", unavailable=3), "BOS": pen("BOS", 0)}))
        signals = [f for f in found if f.kind is base.SIGNAL]
        self.assertEqual(len(signals), 1)
        # The signal argues AGAINST the side the market favours.
        self.assertEqual(signals[0].side, base.AWAY)
        self.assertIn("likely unavailable", signals[0].claim)

    def test_it_stays_quiet_when_the_market_and_our_read_agree(self):
        found = self.detector.run(dossier(
            market={"implied_bullpen_shift": 0.04, "markets": {}},
            bullpen={"NYY": pen("NYY", 0), "BOS": pen("BOS", unavailable=3)}))
        self.assertEqual([f for f in found if f.kind is base.SIGNAL], [])

    def test_one_missing_bullpen_produces_no_comparison(self):
        found = self.detector.run(dossier(
            market={"implied_bullpen_shift": 0.04, "markets": {}},
            bullpen={"NYY": pen("NYY", 2)}))
        self.assertEqual([f for f in found if f.kind is base.SIGNAL], [])

    def test_every_finding_is_labelled_unproven(self):
        # The comparison is sound; the threshold is a guess, and the page must
        # never let that guess read as a validated result.
        found = self.detector.run(dossier(
            market={"implied_bullpen_shift": 0.04, "markets": {}},
            bullpen={"NYY": pen("NYY", 3), "BOS": pen("BOS", 0)}))
        self.assertTrue(all(f.evidence == base.UNPROVEN for f in found))


class TestBullpenWorkload(unittest.TestCase):

    def setUp(self):
        self.detector = detectors.BullpenWorkload()

    def test_one_arm_down_is_context_not_news(self):
        # A normal Tuesday. Ranking it as a signal puts noise at the top and
        # teaches the reader to ignore the ranking.
        found = self.detector.run(dossier(bullpen={"NYY": pen("NYY", 1)}))
        self.assertEqual(found[0].kind, base.CONTEXT)

    def test_several_arms_down_is_a_signal(self):
        found = self.detector.run(dossier(bullpen={"NYY": pen("NYY", 3)}))
        self.assertEqual(found[0].kind, base.SIGNAL)
        self.assertEqual(found[0].side, base.HOME)

    def test_a_full_bullpen_says_nothing(self):
        self.assertEqual(self.detector.run(dossier(bullpen={"NYY": pen("NYY", 0)})), [])

    def test_the_reason_for_the_worst_arm_is_quoted(self):
        found = self.detector.run(dossier(bullpen={"NYY": pen("NYY", 3)}))
        self.assertIn("because", found[0].claim)

    def test_the_sample_names_denominators_not_a_period(self):
        # It read "7-day window" -- the period looked at, no amount of evidence
        # at all -- so the renderer printed "no sample size stated" beside a
        # finding that does rest on countable play.
        found = self.detector.run(dossier(bullpen={"NYY": pen("NYY", 3)}))
        self.assertIn("8 relievers", found[0].sample)
        self.assertEqual(synthesis.sample_size(found[0].sample), 8)

    def test_a_complete_pitch_log_is_counted_in_the_sample(self):
        workload = pen("NYY", 3)
        for i, reliever in enumerate(workload["relievers"]):
            reliever["pitches"] = 20 + i
        found = self.detector.run(dossier(bullpen={"NYY": workload}))
        total = sum(20 + i for i in range(8))
        self.assertIn(f"{total} pitches", found[0].sample)
        self.assertEqual(synthesis.sample_size(found[0].sample), total)

    def test_a_partial_pitch_log_states_no_pitch_total(self):
        # A total short by one reliever would read as the workload behind the
        # claim while being smaller than it.
        workload = pen("NYY", 3)
        for reliever in workload["relievers"]:
            reliever["pitches"] = 20
        workload["relievers"][0]["pitches_known"] = False
        found = self.detector.run(dossier(bullpen={"NYY": workload}))
        self.assertNotIn("pitches", found[0].sample)
        self.assertEqual(synthesis.sample_size(found[0].sample), 8)

    def test_the_score_and_kind_are_untouched_by_the_sample_wording(self):
        found = self.detector.run(dossier(bullpen={"NYY": pen("NYY", 3)}))
        self.assertEqual(found[0].kind, base.SIGNAL)
        self.assertEqual(found[0].value, 3)
        self.assertEqual(found[0].baseline, float(detectors.TYPICAL_UNAVAILABLE))


class TestStaleBook(unittest.TestCase):
    """Arithmetic, not prediction: this is true whether or not anything else is."""

    def setUp(self):
        self.detector = detectors.StaleBook()

    def market(self, prices):
        return {"markets": {}, "all_books": {"h2h": [
            {"book": name, "away_price": away, "home_price": home}
            for name, away, home in prices]}}

    def test_fewer_than_three_books_is_not_a_consensus(self):
        self.assertEqual(self.detector.run(dossier(market=self.market(
            [("a", 150, -170), ("b", 152, -172)]))), [])

    def test_an_outlier_book_is_named_with_its_price(self):
        found = self.detector.run(dossier(market=self.market([
            ("a", 150, -170), ("b", 151, -171), ("c", 152, -172),
            ("outlier", 185, -205)])))
        claims = " ".join(f.claim for f in found)
        self.assertIn("outlier", claims)
        self.assertIn("+185", claims)

    def test_books_in_agreement_produce_nothing(self):
        found = self.detector.run(dossier(market=self.market([
            ("a", 150, -170), ("b", 150, -170), ("c", 151, -170)])))
        self.assertEqual(found, [])

    def test_an_unparseable_quote_is_skipped_not_fatal(self):
        market = self.market([("a", 150, -170), ("b", 151, -171), ("c", 152, -172)])
        market["all_books"]["h2h"].append({"book": "bad", "away_price": None,
                                           "home_price": None})
        self.detector.run(dossier(market=market))  # must not raise


class TestStarterMismatch(unittest.TestCase):

    def setUp(self):
        self.detector = detectors.StarterMismatch()

    def starters(self, away_fip, home_fip, thin=False, known=True):
        return {"both_sp_known": known, "either_sp_thin": thin,
                "away_sp_fip": away_fip, "home_sp_fip": home_fip,
                "away_sp_innings": 120.0, "home_sp_innings": 118.0}

    def test_an_ace_is_a_signal_toward_his_own_team(self):
        found = self.detector.run(dossier(starters=self.starters(2.60, 4.20)))
        self.assertEqual(found[0].side, base.AWAY)
        self.assertIn("BOS", found[0].claim)

    def test_a_poor_starter_is_a_signal_toward_the_OTHER_team(self):
        # The direction that is easy to get backwards and that nothing would
        # raise on: a 5.50 FIP starter is evidence for his opponent.
        found = self.detector.run(dossier(starters=self.starters(5.50, 4.20)))
        self.assertEqual(found[0].side, base.HOME)

    def test_average_starters_say_nothing(self):
        self.assertEqual(self.detector.run(dossier(
            starters=self.starters(4.25, 4.15))), [])

    def test_a_thin_starter_produces_a_debunk_not_a_signal(self):
        found = self.detector.run(dossier(starters=self.starters(1.5, 4.2, thin=True)))
        self.assertEqual(found[0].kind, base.DEBUNK)
        self.assertIn("small-sample", found[0].claim)

    def test_the_thin_warning_is_scoped_to_season_rate_stats(self):
        # "Any rate you see quoted for him tonight" condemned reads with their
        # own denominators -- a 129-fastball velocity line printed in the same
        # card -- and so contradicted the block above it.
        claim = self.detector.run(
            dossier(starters=self.starters(1.5, 4.2, thin=True)))[0].claim
        self.assertIn("rate stats", claim)
        self.assertNotIn("Any rate you see", claim)
        self.assertIn("velocity", claim)

    def test_the_thin_warning_states_a_bound_not_a_sample(self):
        # "<20 IP" says he threw FEWER than twenty innings; counting it as a
        # twenty-inning denominator credits the claim with the sample it warns
        # about.
        found = self.detector.run(dossier(starters=self.starters(1.5, 4.2, thin=True)))
        self.assertEqual(found[0].sample, "<20 IP")
        self.assertIsNone(synthesis.sample_size(found[0].sample))

    def test_an_unknown_starter_produces_nothing(self):
        self.assertEqual(self.detector.run(dossier(
            starters=self.starters(2.6, 4.2, known=False))), [])


class TestBlockedDetectorsAreVisible(unittest.TestCase):
    """A blocked detector is announced, never omitted."""

    def test_a_blocked_detector_reports_itself_rather_than_vanishing(self):
        cls = type("Mute", (base.Detector,),
                   {"name": "mute", "status": base.BLOCKED,
                    "blocked_reason": "the data does not exist",
                    "run": lambda self, g: []})
        found = cls().safe_run(dossier())
        self.assertEqual(found[0].evidence, base.BLOCKED)
        self.assertIn("does not exist", found[0].claim)


class TestRegistrationIsTheHypothesisCount(unittest.TestCase):
    """Adding a detector is a research decision, not a refactor."""

    def setUp(self):
        self._saved = base.registry()
        base.clear_registry()

    def tearDown(self):
        base.clear_registry()
        for detector in self._saved.values():
            base.register(detector)

    def test_the_default_family_registers_cleanly(self):
        detectors.register_defaults()
        self.assertEqual(len(base.registry()), 11)

    def test_every_registered_detector_declares_its_markets(self):
        detectors.register_defaults()
        for detector in base.registry().values():
            self.assertTrue(detector.markets, f"{detector.name} names no market")


if __name__ == "__main__":
    unittest.main()


class TestTravelAndEnvironment(unittest.TestCase):
    """Free facts, computed from data already on disk, on nobody's stat page."""

    def travel(self, miles=2000, eastward=True, games=7, zones=2.4):
        return {"BOS": {"team": "BOS", "miles": miles, "eastward": eastward,
                        "zones": zones, "games_last_7": games,
                        "last_venue": "SEA", "dense_stretch": games >= 6}}

    def test_a_long_flight_argues_against_the_travelling_club(self):
        d = dossier(away="BOS", home="NYY")
        d.add("travel", self.travel())
        signals = [f for f in detectors.TravelLoad().run(d) if f.kind is base.SIGNAL]
        self.assertEqual(signals[0].side, base.HOME)
        self.assertIn("east", signals[0].claim)

    def test_a_home_stand_is_not_surprising(self):
        # Surprise is absolute distance from a baseline, so a 1,200-mile
        # threshold scored ZERO miles as 1.7 -- a club that did not travel came
        # out looking as notable as one that crossed the country.
        d = dossier(away="BOS", home="NYY")
        d.add("travel", self.travel(miles=0, games=6))
        found = detectors.TravelLoad().run(d)
        self.assertEqual([f for f in found if f.kind is base.SIGNAL], [])
        self.assertTrue(all((f.surprise or 0) < 0.5 for f in found))

    def test_distance_and_density_are_separate_claims(self):
        # Merging them put a distance baseline on a games-played value.
        d = dossier(away="BOS", home="NYY")
        d.add("travel", self.travel(miles=2400, games=7))
        found = detectors.TravelLoad().run(d)
        self.assertEqual(len(found), 2)
        miles = [f for f in found if "flew" in f.claim][0]
        games = [f for f in found if "games in seven days" in f.claim][0]
        self.assertEqual(miles.value, 2400)
        self.assertEqual(games.value, 7.0)
        self.assertEqual(games.baseline, float(detectors.DENSE_BASELINE_GAMES))

    def test_a_short_trip_on_a_light_schedule_says_nothing(self):
        d = dossier(away="BOS", home="NYY")
        d.add("travel", self.travel(miles=200, games=3))
        self.assertEqual(detectors.TravelLoad().run(d), [])

    def test_an_uncomputable_trip_is_skipped_not_zeroed(self):
        # Zero miles is a real and different statement from "we do not know
        # where they were".
        d = dossier(away="BOS", home="NYY")
        d.add("travel", {"BOS": {"team": "BOS", "miles": None,
                                 "games_last_7": 7, "reason": "unknown park"}})
        self.assertEqual(detectors.TravelLoad().run(d), [])

    def test_hot_and_cold_get_opposite_explanations(self):
        for temp, expected in ((94.0, "carries further"), (52.0, "carries less")):
            d = dossier()
            d.add("weather", {"temp_f": temp})
            found = detectors.ParkAndWeather().run(d)
            self.assertIn(expected, found[0].claim)

    def test_an_ordinary_night_says_nothing(self):
        d = dossier()
        d.add("weather", {"temp_f": 75.0, "wind_mph": 5.0})
        d.add("park", {"name": "Somewhere", "altitude_m": 100})
        self.assertEqual(detectors.ParkAndWeather().run(d), [])

    def test_altitude_fires_and_bears_on_the_total_not_a_side(self):
        d = dossier()
        d.add("park", {"name": "Coors Field", "altitude_m": 1580})
        found = detectors.ParkAndWeather().run(d)
        self.assertEqual(found[0].side, base.NEITHER)
        self.assertIn("total", found[0].market_relevance)

    def test_wind_is_reported_but_never_interpreted(self):
        # Park orientation is unknown for all thirty parks. A wrong bearing
        # inverts the effect rather than muting it, so the finding ships BLOCKED.
        d = dossier()
        d.add("weather", {"wind_mph": 22.0})
        found = detectors.ParkAndWeather().run(d)
        self.assertEqual(found[0].evidence, base.BLOCKED)
        self.assertIn("NOT interpreted", found[0].claim)


class TestPitchMixMismatch(unittest.TestCase):
    """The decomposition at pitch level: what he throws vs who can hit it."""

    def setUp(self):
        self.detector = detectors.PitchMixMismatch()

    def build(self, usage=45.0, woba=0.400, hitters=8, pitch="SI"):
        d = dossier(away="AZ", home="SF")
        d.add("arsenals", {"home": [{"pitch_type": pitch, "pitch_name": "Sinker",
                                     "pitch_usage": usage}]})
        d.add("lineups", {"away": {"vs_pitch": {pitch: [
            {"woba": woba, "pa": 100} for _ in range(hitters)]}}})
        return d

    def test_a_lineup_that_crushes_his_main_pitch_favours_that_lineup(self):
        found = self.detector.run(self.build())
        self.assertEqual(found[0].side, base.AWAY)
        self.assertIn("sinker", found[0].claim)

    def test_a_lineup_helpless_against_it_favours_the_pitcher(self):
        found = self.detector.run(self.build(woba=0.240))
        self.assertEqual(found[0].side, base.HOME)

    def test_a_pitch_he_barely_throws_is_not_the_matchup(self):
        # Reading a matchup off a pitch thrown a fifth of the time overstates
        # its role in what the lineup is actually preparing for.
        self.assertEqual(self.detector.run(self.build(usage=20.0)), [])

    def test_too_few_hitters_with_a_line_is_silence(self):
        self.assertEqual(self.detector.run(self.build(hitters=3)), [])

    def test_an_ordinary_lineup_says_nothing(self):
        self.assertEqual(self.detector.run(self.build(woba=0.320)), [])

    def test_hitters_are_weighted_by_how_much_they_see_the_pitch(self):
        # A hitter who has seen it twice must not swing the lineup's number.
        d = dossier(away="AZ", home="SF")
        d.add("arsenals", {"home": [{"pitch_type": "SI", "pitch_name": "Sinker",
                                     "pitch_usage": 45.0}]})
        d.add("lineups", {"away": {"vs_pitch": {"SI": (
            [{"woba": 0.300, "pa": 200} for _ in range(5)]
            + [{"woba": 0.900, "pa": 2}])}}})
        found = self.detector.run(d)
        # Unweighted this averages to 0.400 and fires; weighted it is ~0.303.
        self.assertEqual(found, [])

    def test_only_the_primary_pitch_is_tested(self):
        # Five pitches would be five hypotheses per start, which is how a family
        # of forty detectors quietly becomes a family of two hundred.
        d = self.build()
        d.sections["arsenals"]["home"].append(
            {"pitch_type": "SL", "pitch_name": "Slider", "pitch_usage": 40.0})
        d.sections["lineups"]["away"]["vs_pitch"]["SL"] = [
            {"woba": 0.500, "pa": 100} for _ in range(8)]
        self.assertEqual(len(self.detector.run(d)), 1)

    def test_no_arsenal_means_silence_not_an_error(self):
        self.assertEqual(self.detector.run(dossier()), [])
