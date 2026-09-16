"""Tests for R16-L6 (ledger rows, section 3.1 fields, pre-game refusal, one
trigger per rule per game) and R16-L7 (settlement from authoritative
finals, the 7-day VOID rule, counts-only output) in
`src.appstate.live_ledger`.

Every test here is proven, before being trusted, to fail against the parent
commit's `live_ledger.py` for the reason named in its docstring -- see the
PARENT-COMMIT BEHAVIOUR notes.
"""

import unittest
import tempfile
import os
import shutil

from src.appstate import live_ledger


class TestPregameRefusal(unittest.TestCase):
    """R16-L6: refuse a candidate row when any pre-game quote is at or
    after the game's start.

    PARENT-COMMIT BEHAVIOUR: the parent commit's `record_candidate` has no
    concept of `commence_time` or pre-game quotes at all -- it stores
    whatever dict it is handed. This test fails against it because
    `LiveLedgerError` is never raised (the call just returns a row) and
    `AssertRaises` sees no exception.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_refuses_pregame_quote_at_commence_time(self):
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_900",
            "side": "home",
            "price": -110,
            "commence_time": "2026-09-14T23:05:00Z",
            "pregame_quotes": [
                {"book": "fanduel", "price": -120, "observed_utc": "2026-09-14T22:50:00Z"},
                # This one is AT commence_time -- not pre-game proof.
                {"book": "draftkings", "price": -115, "observed_utc": "2026-09-14T23:05:00Z"},
            ],
        }
        with self.assertRaises(live_ledger.LiveLedgerError):
            live_ledger.record_candidate(candidate, path=self.ledger_path)

        # Nothing was written.
        self.assertEqual(live_ledger.candidates(path=self.ledger_path), [])

    def test_refuses_pregame_quote_after_commence_time(self):
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_901",
            "side": "home",
            "price": -110,
            "commence_time": "2026-09-14T23:05:00Z",
            "pregame_newest_observed_utc": "2026-09-14T23:10:00Z",
        }
        with self.assertRaises(live_ledger.LiveLedgerError):
            live_ledger.record_candidate(candidate, path=self.ledger_path)

    def test_accepts_pregame_quotes_strictly_before_commence(self):
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_902",
            "side": "home",
            "price": -110,
            "commence_time": "2026-09-14T23:05:00Z",
            "pregame_quotes": [
                {"book": "fanduel", "price": -120, "observed_utc": "2026-09-14T22:50:00Z"},
            ],
            "pregame_newest_observed_utc": "2026-09-14T22:50:00Z",
        }
        row = live_ledger.record_candidate(candidate, path=self.ledger_path)
        self.assertIsNotNone(row)
        self.assertEqual(row["commence_time"], "2026-09-14T23:05:00Z")


class TestSection31Fields(unittest.TestCase):
    """R16-L6: the row carries section 3.1's field groups and the UNPRICED
    statuses.

    PARENT-COMMIT BEHAVIOUR: the parent commit's row has no `status` field
    at all (or `schema_version`, `code_commit`, `favourite_prob`, etc.), so
    `row["status"]` raises KeyError instead of reading "PRICED", and passing
    an UNPRICED status is silently dropped rather than stored.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_priced_row_carries_identity_and_quote_fields(self):
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "rule_version": "1",
            "prereg_doc": "docs/LIVE_BETTING_SYSTEM.md",
            "prereg_commit": "abc123",
            "sport": "mlb",
            "game_id": "mlb_910",
            "side": "home",
            "price": -110,
            "books": [{"book": "fanduel", "price": -110, "last_update": "2026-09-14T20:00:10Z"}],
            "fresh_books": 3,
            "status": live_ledger.STATUS_PRICED,
            "in_band": True,
            "band_version": "v0",
        }
        row = live_ledger.record_candidate(candidate, path=self.ledger_path)
        self.assertEqual(row["status"], live_ledger.STATUS_PRICED)
        self.assertEqual(row["rule_version"], "1")
        self.assertEqual(row["prereg_doc"], "docs/LIVE_BETTING_SYSTEM.md")
        self.assertEqual(row["fresh_books"], 3)
        self.assertFalse(row["customer_eligible"])
        self.assertEqual(row["in_band"], True)

    def test_unpriced_status_is_stored(self):
        candidate = {
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_911",
            "status": live_ledger.STATUS_UNPRICED_NO_FRESH_QUOTE,
        }
        row = live_ledger.record_candidate(candidate, path=self.ledger_path)
        self.assertEqual(row["status"], live_ledger.STATUS_UNPRICED_NO_FRESH_QUOTE)

    def test_unrecognized_status_refused(self):
        candidate = {
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_912",
            "status": "MAYBE_LATER",
        }
        with self.assertRaises(live_ledger.LiveLedgerError):
            live_ledger.record_candidate(candidate, path=self.ledger_path)

    def test_missing_identity_refused(self):
        with self.assertRaises(live_ledger.LiveLedgerError):
            live_ledger.record_candidate({"sport": "mlb", "game_id": "mlb_913"},
                                         path=self.ledger_path)


class TestOneTriggerPerRulePerGame(unittest.TestCase):
    """R16-L6: an UNPRICED trigger still writes a row, and blocks any later
    trigger for the same rule and game -- price availability cannot select
    the sample.

    PARENT-COMMIT BEHAVIOUR: this passes on the parent commit too (its
    dedup logic is unchanged here) -- included as a direct check of the
    VERIFY item, not a regression case.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unpriced_trigger_writes_row_and_blocks_second_trigger(self):
        first = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_920",
            "status": live_ledger.STATUS_UNPRICED_NO_FRESH_QUOTE,
            "t0_utc": "2026-09-14T20:00:00Z",
        }
        row = live_ledger.record_candidate(first, path=self.ledger_path)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], live_ledger.STATUS_UNPRICED_NO_FRESH_QUOTE)

        # Same rule, same game, later in the game and now priced -- still
        # refused: the UNPRICED row already used this game's one trigger.
        second = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_920",
            "status": live_ledger.STATUS_PRICED,
            "price": -110,
            "t0_utc": "2026-09-14T20:30:00Z",
        }
        blocked = live_ledger.record_candidate(second, path=self.ledger_path)
        self.assertIsNone(blocked)

        rows = live_ledger.candidates(path=self.ledger_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], live_ledger.STATUS_UNPRICED_NO_FRESH_QUOTE)


class TestChainVerifies(unittest.TestCase):
    """The chain must verify across a mixed run of candidates and
    settlements, including UNPRICED and VOID rows."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_verify_ok_after_candidates_and_settlement(self):
        live_ledger.record_candidate({
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_930",
            "side": "home",
            "price": -110,
            "observed_utc": "2026-09-01T20:00:00Z",
            "status": live_ledger.STATUS_PRICED,
        }, now="2026-09-01T20:01:00Z", path=self.ledger_path)
        live_ledger.record_candidate({
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_931",
            "status": live_ledger.STATUS_UNPRICED_NO_MARKET,
            "observed_utc": "2026-09-01T20:05:00Z",
        }, now="2026-09-01T20:06:00Z", path=self.ledger_path)

        live_ledger.settle(
            "2026-09-01", {"mlb_930": {"home_score": 4, "away_score": 1}},
            now="2026-09-01T23:00:00Z", path=self.ledger_path)
        # This one has no final and, checked same-day, stays unsettled --
        # writes no row, but the chain must still verify with a gap in the
        # settled set.
        live_ledger.settle(
            "2026-09-01", {}, now="2026-09-01T23:00:00Z", path=self.ledger_path)

        result = live_ledger.verify(path=self.ledger_path)
        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.rows_checked, 2)


class TestVoidAfterSevenDays(unittest.TestCase):
    """R16-L7: nothing is VOID before 7 days, and every VOID carries a
    reason.

    PARENT-COMMIT BEHAVIOUR: the parent commit's `settle()` VOIDs a
    candidate the very first time no final score is supplied, regardless of
    age -- this fails against it because `summary["voids"]` is already 1 on
    day 0 instead of `summary["unsettled"]` being 1, and no candidate ever
    survives to day 7.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _record(self, game_id, observed_utc):
        return live_ledger.record_candidate({
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": game_id,
            "side": "home",
            "price": -110,
            "observed_utc": observed_utc,
            "status": live_ledger.STATUS_PRICED,
        }, path=self.ledger_path)

    def test_stays_unsettled_at_six_days(self):
        self._record("mlb_940", "2026-09-01T20:00:00Z")
        summary = live_ledger.settle(
            "2026-09-01", {}, now="2026-09-07T12:00:00Z",  # 6 days later
            path=self.ledger_path)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["voids"], 0)
        self.assertEqual(summary["unsettled"], 1)

    def test_voids_at_seven_days_with_reason(self):
        self._record("mlb_941", "2026-09-01T20:00:00Z")
        summary = live_ledger.settle(
            "2026-09-01", {}, now="2026-09-08T12:00:00Z",  # 7 days later
            path=self.ledger_path)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["voids"], 1)
        self.assertEqual(summary["unsettled"], 0)

        rows = [r for r in live_ledger._ledger(self.ledger_path).read()
                if r.get("kind") == live_ledger.KIND_SETTLED]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], live_ledger.RESULT_VOID)
        self.assertTrue(rows[0].get("reason"))


class TestSettleMlbDate(unittest.TestCase):
    """R16-L7: MLB settles from `mlb.fetch_results`'s `final` bucket."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_settle_mlb_date_uses_final_bucket_only(self):
        live_ledger.record_candidate({
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "12345",
            "side": "home",
            "price": -110,
            "observed_utc": "2026-09-10T20:00:00Z",
            "status": live_ledger.STATUS_PRICED,
        }, path=self.ledger_path)
        live_ledger.record_candidate({
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "67890",
            "side": "away",
            "price": 120,
            "observed_utc": "2026-09-10T20:00:00Z",
            "status": live_ledger.STATUS_PRICED,
        }, path=self.ledger_path)

        def fake_fetch_results(game_date):
            self.assertEqual(game_date, "2026-09-10")
            return {
                "final": [
                    {"game_pk": 12345, "home_score": 5, "away_score": 2},
                ],
                # 67890 is still pending -- must NOT be treated as a final.
                "pending": [{"game_pk": 67890}],
                "cancelled": [],
            }

        summary = live_ledger.settle_mlb_date(
            "2026-09-10", path=self.ledger_path, now="2026-09-10T23:00:00Z",
            fetch_results=fake_fetch_results)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["graded"], 1)
        self.assertEqual(summary["unsettled"], 1)
        self.assertEqual(set(summary.keys()), {"date", "graded", "voids", "unsettled"})


class TestSettleOutputHasNoWinLossUnits(unittest.TestCase):
    """VERIFY: settle output contains no 'wins', 'losses' or 'units' key --
    also exercised through settle_recent(), the function the daily loop
    actually calls."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_settle_recent_output_has_no_win_loss_units(self):
        live_ledger.record_candidate({
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "5555",
            "side": "home",
            "price": -110,
            "observed_utc": "2026-09-14T20:00:00Z",
            "status": live_ledger.STATUS_PRICED,
        }, path=self.ledger_path)

        def fake_fetch_results(game_date):
            return {"final": [{"game_pk": 5555, "home_score": 3, "away_score": 1}]}

        totals = live_ledger.settle_recent(
            path=self.ledger_path, now="2026-09-15T10:00:00Z",
            today="2026-09-15", fetch_results=fake_fetch_results)

        self.assertEqual(set(totals.keys()),
                         {"graded", "voids", "unsettled", "dates_checked"})
        for forbidden in ("wins", "losses", "units", "by_rule"):
            self.assertNotIn(forbidden, totals)
        self.assertEqual(totals["graded"], 1)


if __name__ == "__main__":
    unittest.main()
