"""The UFC modules agree with each other: features and the matchup read the rows that
fightstats.py and odds.py actually write.

Found 2026-10-03 by running features on the first real backfill: control time and
submission attempts were null for every fighter (features read `time_in_control` and
`submissions`; fightstats writes `control_time_s` and `submission_attempts`), the
matchup could pick ESPN's in-fight provider as the market, and a provider with no
separate closing price showed no close for a finished bout.
"""
import tempfile
import unittest
from pathlib import Path

from src.datasvc.ufc import features, matchup
from src.datasvc.ufc.store import UfcStore


def stats_row(bout_id, fighter_id, opponent_id, **values):
    """A fight_stats row with fightstats.py's field names."""
    row = {"bout_id": bout_id, "fighter_id": fighter_id, "opponent_id": opponent_id,
           "event_id": "e1", "date_utc": "2026-05-01T22:00Z", "sig_strikes_landed": 40,
           "sig_strikes_attempted": 90, "takedowns_landed": 2, "takedowns_attempted": 5,
           "knockdowns": 0, "control_time_s": 0, "submission_attempts": 0,
           "stats_complete": False, "stats_missing": ["wallclock_epoch_s"]}
    row.update(values)
    return row


class FeaturesReadTheFightstatsFieldNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UfcStore(Path(self.tmp.name))
        self.store.upsert("bouts", [{
            "bout_id": "b1", "event_id": "e1", "date_utc": "2026-05-01T22:00Z", "status": "final",
            "fighter_a_id": "a", "fighter_b_id": "b", "winner_id": "a", "result_method": "DEC_UNANIMOUS",
            "end_round": 3, "end_time_s": 300.0, "fight_time_s": 900.0, "scheduled_rounds": 3}])
        self.store.upsert("fight_stats", [
            stats_row("b1", "a", "b", control_time_s=450, submission_attempts=3),
            stats_row("b1", "b", "a", control_time_s=60, submission_attempts=0)])

    def figure(self, name):
        out = features.features_as_of(self.store, "a", "2026-10-03")
        figs = out.get("figures", out)
        return figs[name]["value"]

    def test_control_time_share_reads_control_time_s(self):
        self.assertAlmostEqual(self.figure("control_time_share"), 450 / 900, places=4)

    def test_submission_attempts_per_15_reads_submission_attempts(self):
        self.assertAlmostEqual(self.figure("submission_attempts_per_15"), 3 / 15 * 15, places=4)


def odds_row(provider_id, provider, **values):
    row = {"bout_id": "b9", "event_id": "e9", "provider_id": provider_id, "provider": provider,
           "orientation": "verified", "a_side": "home", "in_play": False, "is_closing": True,
           "a_ml_open": 150, "b_ml_open": -170, "a_ml_close": None, "b_ml_close": None,
           "a_ml_current": 160, "b_ml_current": -185, "fetched_utc": "2026-10-03T19:00:00Z"}
    row.update(values)
    return row


class TheMatchupMarket(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UfcStore(Path(self.tmp.name))
        self.bout = {"bout_id": "b9", "event_id": "e9", "date_utc": "2026-09-26T22:00Z", "status": "final",
                     "fighter_a_id": "a", "fighter_b_id": "b", "winner_id": "a"}
        self.store.upsert("bouts", [self.bout])

    def test_an_in_fight_provider_is_never_the_market(self):
        # the pre-fight book's id sorts AFTER the live one, so ordering alone cannot pass this
        self.store.upsert("odds", [
            odds_row("59", "ESPN Bet - Live Odds", in_play=True, is_closing=False,
                     a_ml_current=-3000, b_ml_current=1200),
            odds_row("61", "A pre-fight book")])
        block = matchup.bout_odds(self.store, self.bout, "a", "b")
        self.assertEqual(block["provider_id"], "61")
        self.assertEqual(block["moneyline"]["current"]["a"], 160)

    def test_only_in_fight_prices_means_no_market_shown(self):
        self.store.upsert("odds", [odds_row("59", "ESPN Bet - Live Odds", in_play=True, is_closing=False)])
        block = matchup.bout_odds(self.store, self.bout, "a", "b")
        self.assertIsNone(block["moneyline"])
        self.assertIn("in-fight", block["note"])

    def test_a_finished_bout_without_a_separate_close_uses_its_current_price(self):
        self.store.upsert("odds", [odds_row("58", "ESPN BET")])
        close = matchup.bout_odds(self.store, self.bout, "a", "b")["moneyline"]["close"]
        self.assertEqual((close["a"], close["b"], close["from_snapshot"]), (160, -185, "current"))

    def test_an_upcoming_bout_has_no_close(self):
        self.store.upsert("odds", [odds_row("58", "ESPN BET", is_closing=False)])
        self.assertIsNone(matchup.bout_odds(self.store, self.bout, "a", "b")["moneyline"]["close"])

    def test_a_real_close_is_kept(self):
        self.store.upsert("odds", [odds_row("58", "ESPN BET", a_ml_close=155, b_ml_close=-175)])
        close = matchup.bout_odds(self.store, self.bout, "a", "b")["moneyline"]["close"]
        self.assertEqual((close["a"], close["b"]), (155, -175))
        self.assertNotIn("from_snapshot", close)


if __name__ == "__main__":
    unittest.main()
