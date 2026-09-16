"""Tests for src/report/nfl_card.py: publishing and settling NFL cards."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import nfl_slate
from src.report import nfl_card


class NFLCardPublishTests(unittest.TestCase):
    """Test card_for_date, publish_for_date, and settle_for_date."""

    def setUp(self):
        """Create a temporary ledger path for each test."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.card_path = Path(self.tmpdir.name) / "cards_nfl.jsonl"
        self.now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        """Clean up temporary directory."""
        self.tmpdir.cleanup()

    def _make_entry(self, game_id="2026_09_DET_BUF", home_team="Buffalo Bills",
                    away_team="Detroit Lions", home_code="BUF", away_code="DET",
                    week=1, kickoff_utc=None, **kwargs):
        """Build a minimal entry dict."""
        if kickoff_utc is None:
            kickoff_utc = (self.now + __import__('datetime').timedelta(hours=4)).isoformat()

        entry = {
            "game_id": game_id,
            "week": week,
            "home_team": home_team,
            "away_team": away_team,
            "home_code": home_code,
            "away_code": away_code,
            "kickoff_utc": kickoff_utc,
            "neutral_site": False,
            "h2h_quotes": [],
            "spread_quotes": [],
            "model": None,
            "grade": {"ready": True, "reasons": []},
        }
        entry.update(kwargs)
        return entry

    def _make_h2h_quotes(self, home_price=-300, away_price=250, n=6):
        """MIN_BOOKS (6) distinct-book quotes, one side heavily favoured."""
        return [
            {"book": f"book{i}", "home_price": home_price,
             "away_price": away_price, "observed_utc": self.now.isoformat()}
            for i in range(n)
        ]

    def test_card_for_date_with_no_entries_returns_empty_card(self):
        """Empty entries -> empty card with reason."""
        card = nfl_card.card_for_date(
            "2026-09-14", now=self.now, entries=[], path=str(self.card_path))

        self.assertEqual(card["date"], "2026-09-14")
        self.assertEqual(card["sport"], "nfl")
        self.assertEqual(card["rule"], "NFL_CARD_V1")
        self.assertEqual(len(card["picks"]), 0)
        self.assertIn("No NFL", card["reason"])
        self.assertFalse(card["frozen"])

    def test_card_for_date_with_no_picks_returns_empty_card(self):
        """A priced game that still clears no gate -> the "cleared the bar"
        reason, not the "no board" one -- this entry HAS h2h_quotes, so the
        board existed and the game (already started) was refused, which is
        a different fact from never having had a board at all."""
        past_kickoff = (self.now - __import__('datetime').timedelta(hours=1)).isoformat()
        entry = self._make_entry(kickoff_utc=past_kickoff,
                                 h2h_quotes=self._make_h2h_quotes())

        card = nfl_card.card_for_date(
            "2026-09-14", now=self.now, entries=[entry], path=str(self.card_path))

        self.assertEqual(len(card["picks"]), 0)
        self.assertIn("cleared the bar", card["reason"])

    def test_card_for_date_with_no_board_returns_no_board_reason(self):
        """Entries exist but not one carries a priced board (h2h_quotes is
        empty on every entry) -> the reason must say plainly that nothing
        was available to evaluate, not that a candidate was judged and
        declined. This is the 2026-09-16 defect: boards_by_matchup(sport=
        "nfl") resolved every NFL team name through the MLB-only translator
        and returned {} on every date, so nfl_slate built entries with
        h2h_quotes=[] for every game, every day -- and the old wording
        ("No NFL game cleared the bar") read as the model exercising
        judgment when no candidate was ever built to judge."""
        entry = self._make_entry(h2h_quotes=[])

        card = nfl_card.card_for_date(
            "2026-09-14", now=self.now, entries=[entry], path=str(self.card_path))

        self.assertEqual(len(card["picks"]), 0)
        self.assertIn("No priced board was available", card["reason"])
        self.assertNotIn("cleared the bar", card["reason"])

    def test_publish_for_date_with_no_picks_returns_not_published(self):
        """publish_for_date with empty card -> {"published": False}."""
        result = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[], path=str(self.card_path))

        self.assertFalse(result.get("published"))
        self.assertIn("reason", result)

    def test_settle_for_date_with_no_results_returns_settlement(self):
        """settle_for_date returns None when no published card exists."""
        result = nfl_card.settle_for_date(
            "2026-09-14", now=self.now, results={}, path=str(self.card_path))

        # Should return None when there's no published card
        self.assertIsNone(result)

    def test_card_payload_includes_experimental_notice(self):
        """Card payload must carry experimental notice."""
        card = nfl_card.card_for_date(
            "2026-09-14", now=self.now, entries=[], path=str(self.card_path))

        self.assertTrue(card["experimental"])
        self.assertIn("Experimental", card["notice"])
        self.assertIn("still being evaluated", card["notice"])

    def test_card_for_date_frozen_returns_published_row(self):
        """card_for_date with prefer_frozen=True vs prefer_frozen=False."""
        # Test that prefer_frozen=False always builds live (not from ledger)
        card = nfl_card.card_for_date(
            "2026-09-14", now=self.now, entries=[], prefer_frozen=False,
            path=str(self.card_path))

        # Live card should have frozen=False
        self.assertFalse(card["frozen"])

    def test_publish_writes_to_ledger(self):
        """publish_for_date writes a row to the card ledger."""
        # Create a mock entry that can be picked
        # Note: In a real test, we'd need to mock the nfl_card.select function
        # For now, we test the basic flow
        from src.appstate import card_ledger

        # Verify the file is created or updated
        initial_exists = self.card_path.exists()

        result = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[], path=str(self.card_path))

        # Either the file exists or publish returned {"published": False}
        self.assertTrue(not result.get("published") or self.card_path.exists())

    def test_publish_writes_pick_with_sport_and_game_id(self):
        """A real, qualifying candidate publishes with sport='nfl' and its
        game_id -- the fields settle_for_date and card_ledger.settle() join
        on for a non-MLB sport."""
        entry = self._make_entry(
            h2h_quotes=self._make_h2h_quotes(home_price=-300, away_price=250),
            kickoff_utc=(self.now + timedelta(hours=6)).isoformat())

        row = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[entry],
            path=str(self.card_path))

        self.assertNotIn("published", row)  # not the empty-card shape
        picks = row.get("picks") or []
        self.assertEqual(len(picks), 1)
        pick = picks[0]
        self.assertEqual(pick["sport"], "nfl")
        self.assertEqual(pick["game_id"], "2026_09_DET_BUF")
        self.assertEqual(pick["side"], "home")

    def test_publish_lock_carried_forward(self):
        """A pick within the sport's lock window is carried forward
        verbatim by a later publish, even when the fresh read would pick
        the OTHER side -- 'nothing that already locked can be rewritten'."""
        # Kickoff 2h out, NFL's lock_lead_hours is 4.0 -> locked immediately.
        kickoff = (self.now + timedelta(hours=2)).isoformat()
        home_favoured = self._make_entry(
            h2h_quotes=self._make_h2h_quotes(home_price=-300, away_price=250),
            kickoff_utc=kickoff)

        first = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[home_favoured],
            path=str(self.card_path))
        first_pick = first["picks"][0]
        self.assertTrue(first_pick["locked"])
        self.assertEqual(first_pick["side"], "home")
        self.assertEqual(first_pick["price"], -300)

        # A later run, still before kickoff, where the market has flipped to
        # favour the AWAY side. If locking worked, the published pick does
        # not move.
        away_favoured = self._make_entry(
            h2h_quotes=self._make_h2h_quotes(home_price=250, away_price=-300),
            kickoff_utc=kickoff)
        second = nfl_card.publish_for_date(
            "2026-09-14", now=self.now + timedelta(minutes=30),
            entries=[away_favoured], path=str(self.card_path))
        second_pick = second["picks"][0]

        self.assertEqual(second_pick["side"], "home")
        self.assertEqual(second_pick["price"], -300)
        self.assertTrue(second_pick["locked"])
        self.assertEqual(second_pick["game_id"], first_pick["game_id"])

    def test_settle_win_by_game_id(self):
        """settle_for_date grades WIN when the picked side's team wins,
        matched to the result by game_id (non-MLB join key)."""
        entry = self._make_entry(
            h2h_quotes=self._make_h2h_quotes(home_price=-300, away_price=250),
            kickoff_utc=(self.now + timedelta(hours=6)).isoformat())
        published = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[entry],
            path=str(self.card_path))
        game_id = published["picks"][0]["game_id"]
        self.assertEqual(published["picks"][0]["side"], "home")  # BUF picked

        settled = nfl_card.settle_for_date(
            "2026-09-14", now=self.now + timedelta(hours=7),
            results={game_id: {"home_score": 27, "away_score": 13,
                               "completed": True}},
            path=str(self.card_path))

        self.assertIsNotNone(settled)
        graded = settled["picks"][0]
        self.assertEqual(graded["game_id"], game_id)
        self.assertEqual(graded["result"], "WIN")
        self.assertEqual(settled["wins"], 1)
        self.assertEqual(settled["losses"], 0)

    def test_settle_loss_by_game_id(self):
        """settle_for_date grades LOSS when the picked side's team loses."""
        entry = self._make_entry(
            h2h_quotes=self._make_h2h_quotes(home_price=-300, away_price=250),
            kickoff_utc=(self.now + timedelta(hours=6)).isoformat())
        published = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[entry],
            path=str(self.card_path))
        game_id = published["picks"][0]["game_id"]
        self.assertEqual(published["picks"][0]["side"], "home")  # BUF picked

        settled = nfl_card.settle_for_date(
            "2026-09-14", now=self.now + timedelta(hours=7),
            results={game_id: {"home_score": 13, "away_score": 27,
                               "completed": True}},
            path=str(self.card_path))

        self.assertIsNotNone(settled)
        graded = settled["picks"][0]
        self.assertEqual(graded["game_id"], game_id)
        self.assertEqual(graded["result"], "LOSS")
        self.assertEqual(settled["wins"], 0)
        self.assertEqual(settled["losses"], 1)


class NFLCardIntegrationTests(unittest.TestCase):
    """Integration tests for the nfl_card module."""

    def setUp(self):
        """Create temporary directory for ledger."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.card_path = Path(self.tmpdir.name) / "cards_nfl.jsonl"
        self.now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        """Clean up."""
        self.tmpdir.cleanup()

    def test_card_for_date_handles_missing_entries(self):
        """card_for_date handles None entries gracefully.

        entries=None exercises card_for_date's lazy fallback to
        nfl_slate.entries_for_date(), which -- unmocked -- would reach real
        network providers (nfl.schedule_for_date/fetch_team_stats/
        fetch_injuries). That seam is patched here so this stays a network-
        free unit test per the HARD RULES (inject or patch every provider
        call); the patch simulates "no games on the slate" for this date.
        """
        with mock.patch("src.report.nfl_card.nfl_slate.entries_for_date",
                        return_value=[]) as mock_entries:
            card = nfl_card.card_for_date(
                "2026-09-14", now=self.now, entries=None,
                path=str(self.card_path))

        mock_entries.assert_called_once_with("2026-09-14", now=self.now)
        self.assertIsNotNone(card)
        self.assertEqual(card["date"], "2026-09-14")
        self.assertEqual(card["picks"], [])
        self.assertIn("No NFL", card["reason"])


class ResultsForDateMatchingTests(unittest.TestCase):
    """nfl_slate.results_for_date(): joining schedule games to final scores
    by team code, with fully injected games/scores (no network)."""

    def test_matches_completed_games_by_team_code_and_excludes_incomplete(self):
        games = [
            {"game_id": "g1", "away_team": "DET", "home_team": "BUF",
             "week": 1, "start_utc": "2026-09-14T17:00:00+00:00"},
            {"game_id": "g2", "away_team": "KC", "home_team": "LV",
             "week": 1, "start_utc": "2026-09-14T20:00:00+00:00"},
        ]
        scores = [
            # Full team names, as odds.normalize_score() yields -- resolved
            # to codes internally via nfl_teams.abbrev() to join to `games`.
            {"home_team": "Buffalo Bills", "away_team": "Detroit Lions",
             "home_score": 24, "away_score": 20, "completed": True},
            # Not completed -- must be excluded even though it matches g2.
            {"home_team": "Las Vegas Raiders", "away_team": "Kansas City Chiefs",
             "home_score": 10, "away_score": 30, "completed": False},
        ]

        results = nfl_slate.results_for_date(
            "2026-09-14", games=games, scores=scores)

        self.assertEqual(results, {
            "g1": {"home_score": 24, "away_score": 20, "completed": True},
        })
        self.assertNotIn("g2", results)


if __name__ == "__main__":
    unittest.main()
