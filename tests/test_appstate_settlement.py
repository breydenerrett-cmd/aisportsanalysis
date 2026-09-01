"""src/appstate/settlement.py: grading saved bets against final results."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.appstate import savedbets, settlement


def _result(game_pk, game_date, away, home, away_score, home_score, home_won=None):
    """A minimal src.pipeline.history-shaped result row -- only the columns
    settlement.py actually reads, so this test does not need a real
    ingest_date/mlb fetch to exercise the grading rules."""
    if home_won is None:
        home_won = "1" if home_score > away_score else "0"
    return {
        "game_pk": str(game_pk), "date": game_date,
        "away_team": away, "home_team": home,
        "away_score": str(away_score), "home_score": str(home_score),
        "home_won": home_won,
    }


class GradeBetTests(unittest.TestCase):
    """grade_bet is pure -- no db, no clock -- so these exercise the grading
    rules directly against a hand-built results dict."""

    def _bet(self, game, side, saved_at="2026-04-01T18:00:00+00:00"):
        return savedbets.SavedBet(
            id=1, user_id=1, game=game, side=side, price=-120,
            saved_at=saved_at, snapshot_digest=None, deleted_at=None)

    def test_home_side_wins(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        bet = self._bet("BOS@NYY", "NYY ML")
        self.assertEqual(settlement.grade_bet(bet, results)["outcome"], "won")

    def test_home_side_loses(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 5, 2)}
        bet = self._bet("BOS@NYY", "NYY ML")
        self.assertEqual(settlement.grade_bet(bet, results)["outcome"], "lost")

    def test_away_side_wins(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 7, 1)}
        bet = self._bet("BOS@NYY", "BOS ML")
        self.assertEqual(settlement.grade_bet(bet, results)["outcome"], "won")

    def test_bare_home_away_literal_side(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        self.assertEqual(
            settlement.grade_bet(self._bet("BOS@NYY", "home"), results)["outcome"],
            "won")
        self.assertEqual(
            settlement.grade_bet(self._bet("BOS@NYY", "away"), results)["outcome"],
            "lost")

    def test_side_is_case_insensitive(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        bet = self._bet("BOS@NYY", "nyy ml")
        self.assertEqual(settlement.grade_bet(bet, results)["outcome"], "won")

    def test_push_on_a_tied_final(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 3, 3, home_won="")}
        bet = self._bet("BOS@NYY", "NYY ML")
        self.assertEqual(settlement.grade_bet(bet, results)["outcome"], "push")

    def test_void_unmatchable_when_side_names_neither_club(self):
        """The club-name matching edge: a saved bet's `side` naming a club
        that is not one of the two clubs actually in `game` (a typo, or a
        third club's abbreviation) must never be guessed into a winner or
        loser -- it is a settled verdict of its own kind."""
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        bet = self._bet("BOS@NYY", "LAD ML")
        verdict = settlement.grade_bet(bet, results)
        self.assertEqual(verdict["outcome"], "void-unmatchable")
        self.assertIn("LAD", verdict["reason"])

    def test_unmatched_game_stays_unsettled_with_reason(self):
        results = {}  # nothing ingested at all
        bet = self._bet("BOS@NYY", "NYY ML")
        verdict = settlement.grade_bet(bet, results)
        self.assertEqual(verdict["outcome"], "unsettled")
        self.assertIn("no final result", verdict["reason"])

    def test_game_not_yet_final_stays_unsettled(self):
        results = {"1": {"game_pk": "1", "date": "2026-04-01",
                         "away_team": "BOS", "home_team": "NYY",
                         "away_score": None, "home_score": None,
                         "home_won": None}}
        bet = self._bet("BOS@NYY", "NYY ML")
        verdict = settlement.grade_bet(bet, results)
        self.assertEqual(verdict["outcome"], "unsettled")
        self.assertIn("no decided winner", verdict["reason"])

    def test_doubleheader_ambiguity_stays_unsettled(self):
        results = {
            "1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5),
            "2": _result(2, "2026-04-01", "BOS", "NYY", 1, 0),
        }
        bet = self._bet("BOS@NYY", "NYY ML")
        verdict = settlement.grade_bet(bet, results)
        self.assertEqual(verdict["outcome"], "unsettled")
        self.assertIn("doubleheader", verdict["reason"])

    def test_wrong_date_never_matches(self):
        """The game date is derived from saved_at -- a result on a
        different date for the same two clubs must not be treated as a
        match just because the clubs line up."""
        results = {"1": _result(1, "2026-05-15", "BOS", "NYY", 2, 5)}
        bet = self._bet("BOS@NYY", "NYY ML", saved_at="2026-04-01T18:00:00+00:00")
        self.assertEqual(settlement.grade_bet(bet, results)["outcome"], "unsettled")

    def test_unparseable_game_string_stays_unsettled(self):
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        bet = self._bet("not a matchup", "home")
        verdict = settlement.grade_bet(bet, results)
        self.assertEqual(verdict["outcome"], "unsettled")
        self.assertIn("AWAY@HOME", verdict["reason"])


class SettleSavedBetsTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_settles_a_winner_and_persists_it(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML",
                           db=self.db)  # saved_at is "now" -- see below
        # Force a known saved_at so the result's date lines up.
        bet = savedbets.list_bets(1, db=self.db)[0]
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE saved_bets SET saved_at = ? WHERE id = ?",
                    ("2026-04-01T18:00:00+00:00", bet.id))
        conn.commit()
        conn.close()

        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        report = settlement.settle_saved_bets(lambda: results, db=self.db)

        self.assertEqual(report["settled"], 1)
        self.assertEqual(report["counts"]["won"], 1)
        self.assertEqual(report["unsettled"], 0)
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertEqual(row.settlement_status, "won")
        self.assertIsNotNone(row.settled_at)

    def test_accepts_a_plain_dict_as_well_as_a_callable(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", db=self.db)
        bet = savedbets.list_bets(1, db=self.db)[0]
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE saved_bets SET saved_at = ? WHERE id = ?",
                    ("2026-04-01T18:00:00+00:00", bet.id))
        conn.commit()
        conn.close()
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        report = settlement.settle_saved_bets(results, db=self.db)
        self.assertEqual(report["counts"]["won"], 1)

    def test_unmatched_bet_is_reported_but_not_written(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", db=self.db)
        report = settlement.settle_saved_bets(lambda: {}, db=self.db)
        self.assertEqual(report["settled"], 0)
        self.assertEqual(report["unsettled"], 1)
        self.assertIn("reason", report["unsettled_detail"][0])
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertIsNone(row.settlement_status)

    def test_idempotent_rerun_does_not_touch_an_already_settled_bet(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", db=self.db)
        bet = savedbets.list_bets(1, db=self.db)[0]
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE saved_bets SET saved_at = ? WHERE id = ?",
                    ("2026-04-01T18:00:00+00:00", bet.id))
        conn.commit()
        conn.close()
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        settlement.settle_saved_bets(lambda: results, db=self.db)
        first_settled_at = savedbets.list_bets(1, db=self.db)[0].settled_at

        report_again = settlement.settle_saved_bets(lambda: results, db=self.db)
        self.assertEqual(report_again["settled"], 0)  # nothing left to grade
        self.assertEqual(
            savedbets.list_bets(1, db=self.db)[0].settled_at, first_settled_at)


class DailyLoopNoOpTests(unittest.TestCase):
    """The daily-loop hook: research pipeline must never depend on, or
    create, the product db."""

    def test_missing_app_db_is_a_clean_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_db = Path(tmp) / "does-not-exist" / "app.db"
            report = settlement.settle_saved_bets_if_app_db_exists(
                lambda: {}, db=missing_db)
            self.assertTrue(report["skipped"])
            self.assertFalse(missing_db.exists(),
                             "the hook must never create the app db")

    def test_runs_normally_when_the_app_db_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            savedbets.save_bet(1, "BOS@NYY", "NYY ML", db=db)  # creates the file
            self.assertTrue(db.exists())
            report = settlement.settle_saved_bets_if_app_db_exists(
                lambda: {}, db=db)
            self.assertNotIn("skipped", report)
            self.assertEqual(report["unsettled"], 1)


if __name__ == "__main__":
    unittest.main()
