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


def _snapshot_row(away, home, commence_time, observed_utc, away_price,
                  home_price, market="h2h"):
    """A minimal src.pipeline.snapshots-shaped h2h row. Odds-feed rows carry
    full club names ("Boston Red Sox"), never this codebase's abbreviations
    -- see settlement.py's module docstring on why compute_closing_price
    reuses src.pipeline.grading's canonical-name matching instead of
    comparing these directly against a saved bet's `game` string."""
    return {
        "observed_utc": observed_utc, "event_id": "evt-1",
        "commence_time": commence_time, "away_team": away, "home_team": home,
        "market": market, "book": "fanduel",
        "prices": {"away_price": away_price, "home_price": home_price},
        "book_last_update": observed_utc,
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


class ComputeClosingPriceTests(unittest.TestCase):
    """compute_closing_price is pure -- no db, no clock -- exercised
    directly against hand-built snapshot rows, the same style GradeBetTests
    uses for grade_bet."""

    def _bet(self, game, side, price=110, saved_at="2026-04-01T18:00:00+00:00"):
        return savedbets.SavedBet(
            id=1, user_id=1, game=game, side=side, price=price,
            saved_at=saved_at, snapshot_digest=None, deleted_at=None)

    def test_computes_the_closing_price_for_the_saved_away_side(self):
        bet = self._bet("BOS@NYY", "BOS ML", price=110)
        rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                              "2026-04-01T23:05:00+00:00",
                              "2026-04-01T22:00:00+00:00", 116, -130)]
        result = settlement.compute_closing_price(bet, rows)
        self.assertEqual(result["closing_price"], 116)
        self.assertEqual(result["closing_observed_utc"],
                         "2026-04-01T22:00:00+00:00")
        self.assertEqual(result["price_vs_close_cents"], 6)
        self.assertIsNone(result["closing_reason"])

    def test_home_side_reads_the_home_price(self):
        bet = self._bet("BOS@NYY", "NYY ML", price=-140)
        rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                              "2026-04-01T23:05:00+00:00",
                              "2026-04-01T22:00:00+00:00", 116, -130)]
        result = settlement.compute_closing_price(bet, rows)
        self.assertEqual(result["closing_price"], -130)
        self.assertIsNone(result["closing_reason"])

    def test_no_snapshots_at_all_reports_a_reason_not_a_guess(self):
        bet = self._bet("BOS@NYY", "BOS ML")
        result = settlement.compute_closing_price(bet, [])
        self.assertIsNone(result["closing_price"])
        self.assertEqual(result["closing_reason"],
                         "no odds snapshots captured for this game")

    def test_unparseable_game_reports_market_not_captured(self):
        bet = self._bet("not a matchup", "home")
        result = settlement.compute_closing_price(bet, [])
        self.assertEqual(result["closing_reason"], "market not captured")

    def test_side_naming_neither_club_reports_market_not_captured(self):
        # The same "cannot tell" case grade_bet settles void-unmatchable --
        # not a market this feature can price a close for either.
        bet = self._bet("BOS@NYY", "LAD ML")
        result = settlement.compute_closing_price(bet, [])
        self.assertEqual(result["closing_reason"], "market not captured")

    def test_no_recorded_price_reports_a_reason(self):
        bet = self._bet("BOS@NYY", "BOS ML", price=None)
        result = settlement.compute_closing_price(bet, [])
        self.assertEqual(result["closing_reason"],
                         "no price recorded for this saved bet")

    def test_only_an_in_play_observation_reports_a_reason(self):
        bet = self._bet("BOS@NYY", "BOS ML")
        rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                              "2026-04-01T23:05:00+00:00",
                              "2026-04-02T01:00:00+00:00", 116, -130)]
        result = settlement.compute_closing_price(bet, rows)
        self.assertEqual(result["closing_reason"],
                         "no snapshot taken before first pitch")

    def test_missing_price_on_the_saved_side_reports_a_reason(self):
        bet = self._bet("BOS@NYY", "BOS ML")
        rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                              "2026-04-01T23:05:00+00:00",
                              "2026-04-01T22:00:00+00:00", None, -130)]
        result = settlement.compute_closing_price(bet, rows)
        self.assertEqual(result["closing_reason"],
                         "closing snapshot has no away_price")

    def test_never_touches_a_database(self):
        """Pure, like grade_bet -- no db argument even exists to pass."""
        import inspect
        params = inspect.signature(settlement.compute_closing_price).parameters
        self.assertNotIn("db", params)


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

    def _settle_at(self, game, side, price, saved_at):
        savedbets.save_bet(1, game, side, price=price, db=self.db)
        bet = savedbets.list_bets(1, db=self.db)[0]
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE saved_bets SET saved_at = ? WHERE id = ?",
                    (saved_at, bet.id))
        conn.commit()
        conn.close()
        return bet.id

    def test_settling_computes_closing_price_fields_when_injected(self):
        self._settle_at("BOS@NYY", "NYY ML", -140, "2026-04-01T18:00:00+00:00")
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        snapshot_rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                                       "2026-04-01T23:05:00+00:00",
                                       "2026-04-01T22:00:00+00:00", 116, -130)]
        settlement.settle_saved_bets(lambda: results, db=self.db,
                                     snapshot_rows=snapshot_rows)
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertEqual(row.settlement_status, "won")  # NYY (5) beat BOS (2)
        self.assertEqual(row.closing_price, -130)
        self.assertEqual(row.price_vs_close_cents, 10)  # -130 - (-140)
        self.assertIsNone(row.closing_reason)
        self.assertIsNotNone(row.closing_computed_at)

    def test_settling_without_snapshot_rows_records_a_reason_not_a_guess(self):
        """No snapshot_rows injected -- settle_saved_bets never reads the
        live production store on its own (src.pipeline.grading.settle's
        own explicit-injection convention); this asserts the honest
        fallback, not a silently-estimated close."""
        self._settle_at("BOS@NYY", "NYY ML", -140, "2026-04-01T18:00:00+00:00")
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        settlement.settle_saved_bets(lambda: results, db=self.db)
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertIsNone(row.closing_price)
        self.assertEqual(row.closing_reason,
                         "no odds snapshots captured for this game")
        self.assertIsNotNone(row.closing_computed_at)

    def test_settling_never_backfills_an_already_settled_bet(self):
        """A bet settled on an earlier run (before snapshot_rows was ever
        available) is not automatically revisited on a later run just
        because that later run happens to pass real snapshot rows --
        settle_saved_bets only ever touches bets list_unsettled_bets
        returns. backfill_closing_prices is the explicit catch-up."""
        self._settle_at("BOS@NYY", "NYY ML", -140, "2026-04-01T18:00:00+00:00")
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        settlement.settle_saved_bets(lambda: results, db=self.db)  # no rows -> a reason
        self.assertIsNone(savedbets.list_bets(1, db=self.db)[0].closing_price)

        snapshot_rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                                       "2026-04-01T23:05:00+00:00",
                                       "2026-04-01T22:00:00+00:00", 116, -130)]
        settlement.settle_saved_bets(lambda: results, db=self.db,
                                     snapshot_rows=snapshot_rows)
        self.assertIsNone(savedbets.list_bets(1, db=self.db)[0].closing_price)


class BackfillClosingPricesTests(unittest.TestCase):
    """backfill_closing_prices: the one-time catch-up for bets settled
    before the closing-price feature existed (mark_settled called directly
    here, never through settle_saved_bets, to model exactly that)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fills_a_settled_row_missing_closing_fields(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", price=-140, db=self.db)
        bet = savedbets.list_bets(1, db=self.db)[0]
        # saved_at defaults to "now" -- fix it to the snapshot's date so
        # _find_series's date tolerance actually matches (the game date a
        # closing price is looked up against comes from saved_at; see
        # settlement.py's _game_date and its module docstring).
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE saved_bets SET saved_at = ? WHERE id = ?",
                    ("2026-04-01T18:00:00+00:00", bet.id))
        conn.commit()
        conn.close()
        savedbets.mark_settled(bet.id, "lost", db=self.db)

        snapshot_rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                                       "2026-04-01T23:05:00+00:00",
                                       "2026-04-01T22:00:00+00:00", 116, -130)]
        report = settlement.backfill_closing_prices(snapshot_rows, db=self.db)
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["filled"], 1)
        self.assertEqual(report["ungraded"], 0)
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertEqual(row.closing_price, -130)

    def test_never_touches_an_unsettled_bet(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", price=-140, db=self.db)
        report = settlement.backfill_closing_prices([], db=self.db)
        self.assertEqual(report["checked"], 0)
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertIsNone(row.closing_computed_at)

    def test_a_settled_bet_already_settled_by_settle_saved_bets_is_skipped(self):
        """settle_saved_bets already stamps closing_computed_at (even on
        the "no snapshots" path) -- the backfill must not re-select or
        re-attempt a row that already went through it."""
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", price=-140, db=self.db)
        bet = savedbets.list_bets(1, db=self.db)[0]
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE saved_bets SET saved_at = ? WHERE id = ?",
                    ("2026-04-01T18:00:00+00:00", bet.id))
        conn.commit()
        conn.close()
        results = {"1": _result(1, "2026-04-01", "BOS", "NYY", 2, 5)}
        settlement.settle_saved_bets(lambda: results, db=self.db)  # no rows

        snapshot_rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                                       "2026-04-01T23:05:00+00:00",
                                       "2026-04-01T22:00:00+00:00", 116, -130)]
        report = settlement.backfill_closing_prices(snapshot_rows, db=self.db)
        self.assertEqual(report["checked"], 0)
        row = savedbets.list_bets(1, db=self.db)[0]
        self.assertIsNone(row.closing_price)  # unchanged from settle time

    def test_idempotent_rerun_does_not_recompute(self):
        savedbets.save_bet(1, "BOS@NYY", "NYY ML", price=-140, db=self.db)
        bet = savedbets.list_bets(1, db=self.db)[0]
        savedbets.mark_settled(bet.id, "lost", db=self.db)
        settlement.backfill_closing_prices([], db=self.db)
        first = savedbets.list_bets(1, db=self.db)[0]
        self.assertEqual(first.closing_reason,
                         "no odds snapshots captured for this game")

        snapshot_rows = [_snapshot_row("Boston Red Sox", "New York Yankees",
                                       "2026-04-01T23:05:00+00:00",
                                       "2026-04-01T22:00:00+00:00", 116, -130)]
        report_again = settlement.backfill_closing_prices(snapshot_rows, db=self.db)
        self.assertEqual(report_again["checked"], 0)  # already attempted
        second = savedbets.list_bets(1, db=self.db)[0]
        self.assertIsNone(second.closing_price)  # unchanged


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
