"""Tests for src.appstate.live_ledger."""

import unittest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

from src.appstate import live_ledger


class TestRecordCandidate(unittest.TestCase):
    """Test record_candidate and deduplication."""

    def setUp(self):
        """Create temp ledger."""
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        """Clean up temp."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_candidate_appends_row(self):
        """record_candidate appends a new row."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_1",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc123",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        result = live_ledger.record_candidate(
            candidate,
            now="2026-09-14T20:15:00Z",
            path=self.ledger_path
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], live_ledger.KIND_CANDIDATE)
        self.assertEqual(result["rule_id"], "mlb_favorite_trails_after_3")
        self.assertEqual(result["date"], "2026-09-14")
        self.assertIn("prev_hash", result)
        self.assertIn("row_hash", result)

    def test_record_candidate_dedup_on_rule_sport_game(self):
        """record_candidate dedup on (rule_id, sport, game_id)."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_2",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc123",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        result1 = live_ledger.record_candidate(candidate, path=self.ledger_path)
        self.assertIsNotNone(result1)

        # Try to record the same (rule_id, sport, game_id) again
        result2 = live_ledger.record_candidate(candidate, path=self.ledger_path)
        self.assertIsNone(result2)  # Deduplicated

    def test_record_candidate_different_rules_not_dedup(self):
        """Different rules on same game are recorded separately."""
        candidate1 = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_3",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc123",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        candidate2 = {
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_3",
            "side": "away",
            "team": "Red Sox",
            "bet": "Red Sox moneyline, in play",
            "price": 110,
            "books": 5,
            "state_id": "abc124",
            "observed_utc": "2026-09-14T20:05:00Z",
            "trigger": {"pitcher_changed": True},
        }

        result1 = live_ledger.record_candidate(candidate1, path=self.ledger_path)
        result2 = live_ledger.record_candidate(candidate2, path=self.ledger_path)

        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)  # Different rules, both recorded


class TestSettle(unittest.TestCase):
    """Test settle with proper profit calculations."""

    def setUp(self):
        """Create temp ledger."""
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        """Clean up temp."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_settle_win_positive_odds(self):
        """Win at +150 pays (1 + 150/100) - 1 = 1.5 profit."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_100",
            "side": "away",
            "team": "Red Sox",
            "bet": "Red Sox moneyline, in play",
            "price": 150,
            "books": 5,
            "state_id": "abc123",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {
            "mlb_100": {"home_score": 2, "away_score": 3}
        }

        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["graded"], 1)
        self.assertEqual(summary["voids"], 0)
        self.assertNotIn("wins", summary)
        self.assertNotIn("units", summary)

        # The row itself still carries the real grade -- only the printed
        # summary is stripped.
        rows = [r for r in live_ledger._ledger(self.ledger_path).read()
                if r.get("kind") == live_ledger.KIND_SETTLED]
        self.assertEqual(rows[0]["result"], "WIN")
        self.assertAlmostEqual(rows[0]["profit_units"], 1.5, places=2)

    def test_settle_win_negative_odds(self):
        """Win at -132 pays (100/132) profit ≈ 0.7576."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_101",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -132,
            "books": 5,
            "state_id": "abc124",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {
            "mlb_101": {"home_score": 4, "away_score": 2}
        }

        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["graded"], 1)
        rows = [r for r in live_ledger._ledger(self.ledger_path).read()
                if r.get("kind") == live_ledger.KIND_SETTLED]
        self.assertEqual(rows[0]["result"], "WIN")
        # Profit: 100/132 ≈ 0.7576, rounded
        self.assertAlmostEqual(rows[0]["profit_units"], 100/132, places=3)

    def test_settle_loss_pays_minus_1(self):
        """Loss always pays -1.0."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_102",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc125",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {
            "mlb_102": {"home_score": 1, "away_score": 3}
        }

        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["graded"], 1)
        rows = [r for r in live_ledger._ledger(self.ledger_path).read()
                if r.get("kind") == live_ledger.KIND_SETTLED]
        self.assertEqual(rows[0]["result"], "LOSS")
        self.assertAlmostEqual(rows[0]["profit_units"], -1.0, places=2)

    def test_settle_push_is_zero(self):
        """Push scores zero profit."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_103",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc126",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {
            "mlb_103": {"home_score": 2, "away_score": 2}
        }

        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["graded"], 1)
        rows = [r for r in live_ledger._ledger(self.ledger_path).read()
                if r.get("kind") == live_ledger.KIND_SETTLED]
        self.assertEqual(rows[0]["result"], "PUSH")
        self.assertAlmostEqual(rows[0]["profit_units"], 0.0, places=2)

    def test_settle_no_final_stays_unsettled_not_void(self):
        """D11 fix: a candidate with no final yet stays UNSETTLED, not VOID.

        The old behaviour wrote a permanent VOID the first time settle() ran
        without a final for the game -- a window that stopped early, or a
        feed that briefly failed, would void a real candidate forever. R16-L7
        requires it stay unsettled and be retried, with VOID reserved for
        candidates whose OWN date is 7+ days old (see
        test_live_settle.test_void_only_after_seven_days).
        """
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_104",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc127",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {}  # No result for this game yet

        summary = live_ledger.settle(
            "2026-09-14", results, now="2026-09-14T23:00:00Z",
            path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["voids"], 0)
        self.assertEqual(summary["graded"], 0)
        self.assertEqual(summary["unsettled"], 1)

        # Still shows up as unsettled, not silently dropped.
        still = live_ledger.unsettled(date="2026-09-14", path=self.ledger_path)
        self.assertEqual(len(still), 1)

    def test_settle_returns_none_if_no_candidates(self):
        """settle returns None if no unsettled candidates."""
        results = {}
        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)
        self.assertIsNone(summary)

    def test_settle_summary_has_no_win_loss_keys(self):
        """R16-L7: settle()'s return is counts only -- no wins/losses/units/
        by_rule anywhere, so a log that prints it cannot leak an interim
        per-rule record (Stage 0, docs/LIVE_BETTING_SYSTEM.md 3.1)."""
        candidate1 = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_210",
            "side": "home",
            "price": -110,
            "observed_utc": "2026-09-14T20:00:00Z",
        }
        candidate2 = {
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_211",
            "side": "away",
            "price": 150,
            "observed_utc": "2026-09-14T20:05:00Z",
        }
        live_ledger.record_candidate(candidate1, path=self.ledger_path)
        live_ledger.record_candidate(candidate2, path=self.ledger_path)

        results = {
            "mlb_210": {"home_score": 3, "away_score": 1},
            "mlb_211": {"home_score": 2, "away_score": 4},
        }
        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(set(summary.keys()), {"date", "graded", "voids", "unsettled"})
        for forbidden in ("wins", "losses", "units", "by_rule", "pushes"):
            self.assertNotIn(forbidden, summary)

    def test_settle_by_rule_breakdown(self):
        """settle() itself is counts-only (no by_rule); the internal
        record() aggregate -- never printed by the daily loop -- still
        carries a by-rule breakdown from the settled rows."""
        candidate1 = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_200",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc200",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        candidate2 = {
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_201",
            "side": "away",
            "team": "Red Sox",
            "bet": "Red Sox moneyline, in play",
            "price": 150,
            "books": 5,
            "state_id": "abc201",
            "observed_utc": "2026-09-14T20:05:00Z",
            "trigger": {"pitcher_changed": True},
        }

        live_ledger.record_candidate(candidate1, path=self.ledger_path)
        live_ledger.record_candidate(candidate2, path=self.ledger_path)

        results = {
            "mlb_200": {"home_score": 3, "away_score": 1},
            "mlb_201": {"home_score": 2, "away_score": 4},
        }

        summary = live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["graded"], 2)
        self.assertNotIn("by_rule", summary)

        full = live_ledger.record(path=self.ledger_path)
        self.assertEqual(full["wins"], 2)
        self.assertIn("mlb_favorite_trails_after_3", full["by_rule"])
        self.assertIn("mlb_starter_pulled_early", full["by_rule"])


class TestRecord(unittest.TestCase):
    """Test record() summary stats."""

    def setUp(self):
        """Create temp ledger."""
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        """Clean up temp."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_empty(self):
        """record on empty ledger."""
        summary = live_ledger.record(path=self.ledger_path)

        self.assertEqual(summary["candidates"], 0)
        self.assertEqual(summary["settled"], 0)
        self.assertEqual(summary["wins"], 0)
        self.assertEqual(summary["losses"], 0)
        self.assertEqual(summary["units"], 0.0)

    def test_record_with_candidates_and_settled(self):
        """record pools candidate and settled counts."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_300",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc300",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {
            "mlb_300": {"home_score": 3, "away_score": 1}
        }

        live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        summary = live_ledger.record(path=self.ledger_path)

        self.assertEqual(summary["candidates"], 1)
        self.assertEqual(summary["settled"], 1)
        self.assertEqual(summary["wins"], 1)


class TestHistory(unittest.TestCase):
    """Test history() newest first."""

    def setUp(self):
        """Create temp ledger."""
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        """Clean up temp."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_history_newest_first(self):
        """history returns candidates newest first."""
        candidate1 = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_400",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc400",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        candidate2 = {
            "rule_id": "mlb_starter_pulled_early",
            "sport": "mlb",
            "game_id": "mlb_401",
            "side": "away",
            "team": "Red Sox",
            "bet": "Red Sox moneyline, in play",
            "price": 150,
            "books": 5,
            "state_id": "abc401",
            "observed_utc": "2026-09-14T20:30:00Z",
            "trigger": {"pitcher_changed": True},
        }

        live_ledger.record_candidate(candidate1, path=self.ledger_path)
        live_ledger.record_candidate(candidate2, path=self.ledger_path)

        history = live_ledger.history(path=self.ledger_path)

        # Second candidate should be first (newest)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["game_id"], "mlb_401")
        self.assertEqual(history[1]["game_id"], "mlb_400")

    def test_history_with_settlement(self):
        """history includes settlement if available."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_402",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc402",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        results = {
            "mlb_402": {"home_score": 3, "away_score": 1}
        }

        live_ledger.settle("2026-09-14", results, path=self.ledger_path)

        history = live_ledger.history(path=self.ledger_path)

        self.assertEqual(len(history), 1)
        self.assertIsNotNone(history[0]["settlement"])
        self.assertEqual(history[0]["settlement"]["result"], "WIN")

    def test_history_limit(self):
        """history respects limit."""
        for i in range(5):
            candidate = {
                "rule_id": "mlb_favorite_trails_after_3",
                "sport": "mlb",
                "game_id": f"mlb_{500+i}",
                "side": "home",
                "team": "Yankees",
                "bet": "Yankees moneyline, in play",
                "price": -110,
                "books": 5,
                "state_id": f"abc{500+i}",
                "observed_utc": f"2026-09-14T{20+i}:00:00Z",
                "trigger": {"margin": -1},
            }
            live_ledger.record_candidate(candidate, path=self.ledger_path)

        history = live_ledger.history(path=self.ledger_path, limit=3)
        self.assertEqual(len(history), 3)


class TestVerify(unittest.TestCase):
    """Test verify() chain integrity."""

    def setUp(self):
        """Create temp ledger."""
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.temp_dir, "live.jsonl")

    def tearDown(self):
        """Clean up temp."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_verify_empty_ledger(self):
        """verify on empty ledger returns ok."""
        result = live_ledger.verify(path=self.ledger_path)
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 0)

    def test_verify_with_candidates(self):
        """verify with valid candidates."""
        candidate = {
            "rule_id": "mlb_favorite_trails_after_3",
            "sport": "mlb",
            "game_id": "mlb_600",
            "side": "home",
            "team": "Yankees",
            "bet": "Yankees moneyline, in play",
            "price": -110,
            "books": 5,
            "state_id": "abc600",
            "observed_utc": "2026-09-14T20:00:00Z",
            "trigger": {"margin": -1},
        }

        live_ledger.record_candidate(candidate, path=self.ledger_path)

        result = live_ledger.verify(path=self.ledger_path)
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 1)


class TestNoCardLedgerImports(unittest.TestCase):
    """Test that live_ledger.py does not import card_ledger."""

    def test_no_card_ledger_import(self):
        """live_ledger.py should not import card_ledger."""
        module_path = Path(__file__).resolve().parent.parent / "src" / "appstate" / "live_ledger.py"
        source = module_path.read_text()
        self.assertNotIn("from src.appstate import card_ledger", source)
        self.assertNotIn("from src.appstate.card_ledger import", source)

    def test_no_card_ledger_import_in_live_rules(self):
        """live_rules.py should not import card_ledger."""
        module_path = Path(__file__).resolve().parent.parent / "src" / "analysis" / "live_rules.py"
        source = module_path.read_text()
        self.assertNotIn("from src.appstate import card_ledger", source)
        self.assertNotIn("from src.appstate.card_ledger import", source)


if __name__ == "__main__":
    unittest.main()
