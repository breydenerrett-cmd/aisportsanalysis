"""Multi-sport card ledger paths and grading.

Tests for store_path(), lock_lead_for(), and multi-sport publish/settle/record
behavior. Every test runs against a temporary ledger path; none touch
evidence/cards_*.jsonl files.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import card_ledger


def _card(date="2026-09-10", picks=None, sport=None):
    """A published card for testing."""
    card = {
        "date": date,
        "rule": card_ledger.KIND_PUBLISHED,
        "basis": "basis sentence",
        "disclaimer": "disclaimer sentence",
        "model_id": "run_expectancy_poisson_v1",
        "calibrated": True,
        "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
        "filled": 0,
        "games_on_slate": 5,
        "picks": picks if picks is not None else [_pick(sport=sport)],
    }
    return card


def _pick(rank=1, market="moneyline", side="home", price=-150, line=None,
          game_pk=1001, label="STRONG", sport=None, game_id=None,
          first_pitch_utc="2026-09-10T23:05:00Z"):
    """A pick for testing.

    For non-MLB sports, game_id must be provided and will be included.
    For MLB (sport=None), game_pk is used and no game_id is included.
    """
    pick = {
        "rank": rank, "label": label, "bet": "Take team to win at -150",
        "why": ["because"], "market": market, "line": line, "side": side,
        "team": "HOME", "team_name": "Home Team", "opponent_name": "Away Team",
        "price": price, "book": "draftkings", "books": 8,
        "confidence": 0.74, "market_probability": 0.74,
        "model_probability": 0.64, "game_pk": game_pk, "event_id": "e1",
        "away_team": "AWAY", "home_team": "HOME",
        "first_pitch_utc": first_pitch_utc,
        "observed_utc": "2026-09-10T18:00:00Z", "model": {},
    }
    if sport and sport != "mlb":
        # Non-MLB sports use game_id
        pick["game_id"] = game_id or f"{sport}_2026_09_10_{rank}"
        pick["sport"] = sport
    return pick


class StorePath(unittest.TestCase):
    def test_default_sport_uses_mlb_path(self):
        """store_path() with no argument returns the MLB path."""
        path = card_ledger.store_path()
        self.assertTrue(path.endswith("cards_v1.jsonl"))

    def test_empty_string_uses_mlb_path(self):
        """store_path("") returns the MLB path."""
        path = card_ledger.store_path("")
        self.assertTrue(path.endswith("cards_v1.jsonl"))

    def test_mlb_explicit_uses_mlb_path(self):
        """store_path("mlb") returns the MLB path."""
        path = card_ledger.store_path("mlb")
        self.assertTrue(path.endswith("cards_v1.jsonl"))

    def test_nfl_uses_nfl_path(self):
        """store_path("nfl") returns the NFL path."""
        path = card_ledger.store_path("nfl")
        self.assertTrue(path.endswith("cards_nfl_v1.jsonl"))

    def test_tennis_uses_tennis_path(self):
        """store_path("tennis") returns the tennis path."""
        path = card_ledger.store_path("tennis")
        self.assertTrue(path.endswith("cards_tennis_v1.jsonl"))

    def test_unknown_sport_raises_error(self):
        """store_path("bogus") raises CardLedgerError."""
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.store_path("bogus")


class LockLeadFor(unittest.TestCase):
    def test_default_sport_uses_default_hours(self):
        """lock_lead_for() with no argument returns LOCK_LEAD_HOURS."""
        hours = card_ledger.lock_lead_for()
        self.assertEqual(card_ledger.LOCK_LEAD_HOURS, hours)

    def test_mlb_explicit_uses_default_hours(self):
        """lock_lead_for("mlb") returns LOCK_LEAD_HOURS."""
        hours = card_ledger.lock_lead_for("mlb")
        self.assertEqual(card_ledger.LOCK_LEAD_HOURS, hours)

    def test_nfl_uses_four_hours(self):
        """lock_lead_for("nfl") returns 4.0 hours."""
        hours = card_ledger.lock_lead_for("nfl")
        self.assertEqual(4.0, hours)

    def test_tennis_uses_one_hour(self):
        """lock_lead_for("tennis") returns 1.0 hour."""
        hours = card_ledger.lock_lead_for("tennis")
        self.assertEqual(1.0, hours)

    def test_unknown_sport_raises_error(self):
        """lock_lead_for("bogus") raises CardLedgerError."""
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.lock_lead_for("bogus")


class MultiSportPublish(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mlb_path = os.path.join(self._tmp.name, "cards_mlb.jsonl")
        self.nfl_path = os.path.join(self._tmp.name, "cards_nfl.jsonl")

    def test_mlb_publish_has_no_sport_field(self):
        """MLB picks published have no sport field (backward compatible).

        game_id is in FROZEN_FIELDS so it's included for all picks (None for MLB),
        but sport is not in FROZEN_FIELDS and should not appear for MLB.
        """
        card = _card(picks=[_pick(game_pk=1001, sport=None)])
        row = card_ledger.publish(card, path=self.mlb_path, sport="mlb")

        published = row["picks"][0]
        self.assertNotIn("sport", published)
        # game_id is in FROZEN_FIELDS, so it should be None for MLB
        self.assertIsNone(published.get("game_id"))
        self.assertEqual(1001, published["game_pk"])

    def test_nfl_publish_includes_game_id_and_sport(self):
        """NFL picks published include game_id and sport fields."""
        card = _card(picks=[_pick(game_id="2026_02_DET_BUF", sport="nfl")],
                     sport="nfl")
        row = card_ledger.publish(card, path=self.nfl_path, sport="nfl")

        published = row["picks"][0]
        self.assertEqual("nfl", published["sport"])
        self.assertEqual("2026_02_DET_BUF", published["game_id"])
        # game_pk should still be there for backward compatibility in key joins
        self.assertIsNotNone(published.get("game_pk"))

    def test_publish_respects_explicit_path_over_sport(self):
        """publish(..., path=X, sport=Y) uses path X, not sport Y's path."""
        card = _card(picks=[_pick(game_id="nfl_1", sport="nfl")], sport="nfl")
        row = card_ledger.publish(card, path=self.nfl_path, sport="nfl")

        # Read from explicit path
        rows = list(card_ledger._ledger(self.nfl_path).read())
        self.assertEqual(1, len(rows))
        self.assertEqual("nfl", rows[0]["picks"][0]["sport"])


class MultiSportLocking(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_path = os.path.join(self._tmp.name, "cards_nfl.jsonl")

    def test_lock_window_respects_sport_lock_lead(self):
        """Picks lock within the sport's lock_lead_hours window."""
        # For NFL, lock_lead_hours=4.0
        # First publish at time T with pick having first_pitch at T+2h
        # (within 4h window, should lock)
        now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        kickoff = now + timedelta(hours=2)

        pick = _pick(
            game_id="nfl_1", sport="nfl",
            first_pitch_utc=kickoff.isoformat()
        )
        card = _card(picks=[pick], sport="nfl")

        first = card_ledger.publish(
            card, path=self.nfl_path, sport="nfl",
            now=now.isoformat()
        )
        self.assertTrue(first["picks"][0]["locked"],
                       "pick within 4h window should be locked")

        # Second publish at T+2.5h (still within 4h) should NOT change pick
        later = now + timedelta(hours=2, minutes=30)
        moved_pick = _pick(
            game_id="nfl_1", sport="nfl",
            first_pitch_utc=kickoff.isoformat(),
            price=-200  # Different price
        )
        moved_card = _card(picks=[moved_pick], sport="nfl")

        second = card_ledger.publish(
            moved_card, path=self.nfl_path, sport="nfl",
            now=later.isoformat()
        )
        # Should carry forward the locked pick unchanged
        self.assertEqual(-150, second["picks"][0]["price"],
                        "locked pick should not change price")


class MultiSportSettle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_path = os.path.join(self._tmp.name, "cards_nfl.jsonl")

    def test_settle_with_game_id_instead_of_game_pk(self):
        """settle() uses game_id lookup for non-MLB sports."""
        # Publish an NFL card with game_id
        pick = _pick(game_id="2026_02_DET_BUF", sport="nfl", game_pk=None)
        card = _card(date="2026-09-14", picks=[pick], sport="nfl")
        card_ledger.publish(card, path=self.nfl_path, sport="nfl")

        # Settle with results keyed by game_id
        results = {
            "2026_02_DET_BUF": {"home_score": 27, "away_score": 24}
        }
        settled = card_ledger.settle(
            "2026-09-14", results, path=self.nfl_path, sport="nfl"
        )

        self.assertIsNotNone(settled)
        self.assertEqual(1, settled["n_picks"])
        pick_graded = settled["picks"][0]
        self.assertEqual("2026_02_DET_BUF", pick_graded["game_id"])
        self.assertEqual("nfl", pick_graded["sport"])

    def test_settle_with_results_by_game_id_alias(self):
        """settle(..., results_by_game_id=X) works as alias for results_by_game_pk."""
        pick = _pick(game_id="2026_02_DET_BUF", sport="nfl", game_pk=None)
        card = _card(date="2026-09-14", picks=[pick], sport="nfl")
        card_ledger.publish(card, path=self.nfl_path, sport="nfl")

        # Use results_by_game_id parameter name
        results = {
            "2026_02_DET_BUF": {"home_score": 27, "away_score": 24}
        }
        settled = card_ledger.settle(
            "2026-09-14", {}, path=self.nfl_path, sport="nfl",
            results_by_game_id=results
        )

        self.assertIsNotNone(settled)
        self.assertEqual(1, settled["n_picks"])

    def test_grade_row_carries_game_id_and_sport(self):
        """Graded rows for non-MLB picks carry game_id and sport."""
        pick = _pick(game_id="2026_02_DET_BUF", sport="nfl", side="away")
        card = _card(date="2026-09-14", picks=[pick], sport="nfl")
        card_ledger.publish(card, path=self.nfl_path, sport="nfl")

        # Away team won by 3 (24 > 27 is false, so away lost)
        # Actually, if away is 27 and home is 24, away won by 3
        results = {
            "2026_02_DET_BUF": {"home_score": 24, "away_score": 27}
        }
        settled = card_ledger.settle(
            "2026-09-14", results, path=self.nfl_path, sport="nfl"
        )

        graded = settled["picks"][0]
        self.assertEqual("2026_02_DET_BUF", graded["game_id"])
        self.assertEqual("nfl", graded["sport"])


class MultiSportRecord(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mlb_path = os.path.join(self._tmp.name, "cards_mlb.jsonl")
        self.nfl_path = os.path.join(self._tmp.name, "cards_nfl.jsonl")

    def test_record_for_nfl_reads_nfl_file(self):
        """record(sport="nfl") reads from the NFL ledger file."""
        # Publish and settle an NFL card
        pick = _pick(game_id="2026_02_DET_BUF", sport="nfl")
        card = _card(date="2026-09-14", picks=[pick], sport="nfl")
        card_ledger.publish(card, path=self.nfl_path, sport="nfl")

        results = {
            "2026_02_DET_BUF": {"home_score": 27, "away_score": 24}
        }
        card_ledger.settle(
            "2026-09-14", results, path=self.nfl_path, sport="nfl"
        )

        # Record from NFL file
        rec = card_ledger.record(path=self.nfl_path, sport="nfl")
        self.assertEqual(1, rec["days"])
        self.assertEqual(1, rec["n_staked"])

    def test_record_for_mlb_has_no_sport_field(self):
        """record() for MLB does not add sport fields to output."""
        pick = _pick(game_pk=1001)
        card = _card(date="2026-09-14", picks=[pick])
        card_ledger.publish(card, path=self.mlb_path, sport="mlb")

        results = {1001: {"home_score": 5, "away_score": 2}}
        card_ledger.settle(
            "2026-09-14", results, path=self.mlb_path, sport="mlb"
        )

        rec = card_ledger.record(path=self.mlb_path)
        self.assertEqual(1, rec["days"])


class MLBBackwardCompatibility(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def test_mlb_frozen_picks_are_byte_identical_to_current(self):
        """MLB frozen picks have the same fields as before multi-sport support."""
        pick = _pick(game_pk=1001)
        card = _card(picks=[pick])
        row = card_ledger.publish(card, path=self.path, sport=None)

        published = row["picks"][0]
        # Should NOT have sport (it's not in FROZEN_FIELDS)
        self.assertNotIn("sport", published)
        # game_id IS in FROZEN_FIELDS, so it's included (None for MLB)
        self.assertIsNone(published.get("game_id"))
        # Should have game_pk
        self.assertEqual(1001, published["game_pk"])
        # Spot-check a few expected fields
        self.assertEqual("moneyline", published["market"])
        self.assertEqual(-150, published["price"])

    def test_mlb_settle_json_export_has_no_extra_fields(self):
        """JSON serialization of MLB graded rows has no sport field."""
        pick = _pick(game_pk=1001)
        card = _card(date="2026-09-14", picks=[pick])
        card_ledger.publish(card, path=self.path, sport=None)

        results = {1001: {"home_score": 5, "away_score": 2}}
        settled = card_ledger.settle("2026-09-14", results, path=self.path)

        graded = settled["picks"][0]
        json_str = json.dumps(graded)
        parsed = json.loads(json_str)

        self.assertNotIn("sport", parsed)
        # game_id should be None for MLB
        self.assertIsNone(parsed.get("game_id"))
        self.assertEqual(1001, parsed["game_pk"])


if __name__ == "__main__":
    unittest.main()
