"""Tests for src/detect/detectors.py and the dossier they read from.

The centrepiece is TestImpliedBullpenDisagreement. That detector is the project's
most original idea -- the full-game minus first-five price gap IS the market's
bullpen opinion -- and it is only meaningful if the two prices are de-vigged and
subtracted in the right order. A sign error there would silently credit the wrong
bullpen on every game in the league.
"""

import unittest

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
        self.assertEqual(len(base.registry()), 7)

    def test_every_registered_detector_declares_its_markets(self):
        detectors.register_defaults()
        for detector in base.registry().values():
            self.assertTrue(detector.markets, f"{detector.name} names no market")


if __name__ == "__main__":
    unittest.main()
