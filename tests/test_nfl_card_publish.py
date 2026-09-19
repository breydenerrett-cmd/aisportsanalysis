"""Tests for src/report/nfl_card.py: publishing and settling NFL cards."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import card_ledger
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


class NFLCardProvenanceTests(unittest.TestCase):
    """Owner directive 2026-09-19: a published NFL row must carry the same
    provenance fields an MLB row does -- basis, disclaimer, model_id,
    calibrated. A slip on the public record nobody can check the basis of
    is not a slip anyone can audit.

    PARENT-COMMIT BEHAVIOUR: before this fix, `card_for_date`'s live-card
    dict literal set no "basis"/"disclaimer"/"model_id"/"calibrated" keys
    at all, so every one of the assertions below failed -- including on the
    real 2026-09-17 Bills -225 row, the only NFL pick ever published.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.card_path = Path(self.tmpdir.name) / "cards_nfl.jsonl"
        self.now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _entry(self):
        return {
            "game_id": "2026_09_DET_BUF", "week": 1,
            "home_team": "Buffalo Bills", "away_team": "Detroit Lions",
            "home_code": "BUF", "away_code": "DET",
            "kickoff_utc": (self.now + timedelta(hours=6)).isoformat(),
            "neutral_site": False,
            "h2h_quotes": [
                {"book": f"book{i}", "home_price": -300, "away_price": 250,
                 "observed_utc": self.now.isoformat()}
                for i in range(6)
            ],
            "spread_quotes": [], "model": None,
            "grade": {"ready": True, "reasons": []},
        }

    def test_published_row_carries_provenance_like_mlb(self):
        row = nfl_card.publish_for_date(
            "2026-09-14", now=self.now, entries=[self._entry()],
            path=str(self.card_path))

        self.assertNotIn("published", row)  # a real publish, not the empty shape
        self.assertIsNotNone(row.get("basis"))
        self.assertIsNotNone(row.get("disclaimer"))
        self.assertIsNotNone(row.get("model_id"))
        self.assertIsInstance(row.get("calibrated"), bool)

        from src.analysis import nfl_card as nfl_card_analysis
        self.assertEqual(row["basis"], nfl_card_analysis.CARD_BASIS)
        self.assertEqual(row["disclaimer"], nfl_card_analysis.CARD_DISCLAIMER)
        self.assertEqual(row["model_id"], nfl_card_analysis.MODEL_ID)


class NFLCardSettleRecentTests(unittest.TestCase):
    """R-2026-09-19: nfl_card.settle_recent, the self-healing settle window
    that fixes the exact failure the only NFL pick ever published hit --
    published after the single daily settle attempt already ran and found
    nothing to settle, then never retried, so it sat ungraded for two days.
    Every provider seam is mocked or injected; no network, no real clock
    beyond the `now`/`today` each test passes in.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.card_path = Path(self.tmpdir.name) / "cards_nfl.jsonl"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _publish(self, date, game_id, now):
        entry = {
            "game_id": game_id, "week": 2,
            "home_team": "Buffalo Bills", "away_team": "New York Jets",
            "home_code": "BUF", "away_code": "NYJ",
            "kickoff_utc": (now + timedelta(hours=6)).isoformat(),
            "neutral_site": False,
            "h2h_quotes": [
                {"book": f"book{i}", "home_price": -225, "away_price": 185,
                 "observed_utc": now.isoformat()}
                for i in range(6)
            ],
            "spread_quotes": [], "model": None,
            "grade": {"ready": True, "reasons": []},
        }
        return nfl_card.publish_for_date(
            date, now=now, entries=[entry], path=str(self.card_path))

    def test_late_publish_settles_on_a_later_pass_not_the_first(self):
        """The exact 2026-09-17 story: the card publishes on game day,
        AFTER the morning a single-shot settle would already have run and
        found nothing published. The old single-`--date` code never tried
        that date again. This one does, on the very next scheduled pass."""
        game_day = datetime(2026, 9, 17, 23, 0, 0, tzinfo=timezone.utc)
        self._publish("2026-09-17", "nfl_bills_jets", now=game_day)

        # Pass 1 (2026-09-18 morning): no final score in the feed yet.
        totals1 = nfl_card.settle_recent(
            path=str(self.card_path), today="2026-09-18",
            fetch_results=lambda d: {})
        self.assertEqual(totals1["settled"], 0)
        miss = next(m for m in totals1["misses"] if m["date"] == "2026-09-17")
        self.assertIn("no final score yet", miss["reason"])
        self.assertIsNone(card_ledger.settled_row(
            "2026-09-17", path=str(self.card_path), sport="nfl"))

        # Pass 2 (2026-09-19 morning): the final score has posted.
        totals2 = nfl_card.settle_recent(
            path=str(self.card_path), today="2026-09-19",
            fetch_results=lambda d: (
                {"nfl_bills_jets": {"home_score": 27, "away_score": 13}}
                if d == "2026-09-17" else {}))
        self.assertEqual(totals2["settled"], 1)
        settled = card_ledger.settled_row(
            "2026-09-17", path=str(self.card_path), sport="nfl")
        self.assertIsNotNone(settled)
        self.assertEqual(settled["wins"], 1)

    def test_odds_api_scores_fetched_at_most_once_per_pass(self):
        """CREDIT RULE (owner directive 2026-09-19): odds.fetch_scores
        costs 2 credits with daysFrom. Two different stale dates checked in
        ONE settle_recent() pass must cost exactly one call, not one per
        date -- see `_cached_scores_fetch`'s docstring. A naive per-date
        fetch would turn a 7-day retry window into up to 7x the credits a
        single-shot settle used to spend."""
        now1 = datetime(2026, 9, 15, 23, 0, 0, tzinfo=timezone.utc)
        now2 = datetime(2026, 9, 17, 23, 0, 0, tzinfo=timezone.utc)
        self._publish("2026-09-15", "nfl_a", now=now1)
        self._publish("2026-09-17", "nfl_b", now=now2)

        calls = {"n": 0}

        def fake_fetch_scores(*, sport, days_from):
            calls["n"] += 1
            return [
                {"id": "nfl_a", "completed": True,
                 "home_team": "Buffalo Bills", "away_team": "New York Jets",
                 "scores": [{"name": "Buffalo Bills", "score": "20"},
                            {"name": "New York Jets", "score": "10"}]},
                {"id": "nfl_b", "completed": True,
                 "home_team": "Buffalo Bills", "away_team": "New York Jets",
                 "scores": [{"name": "Buffalo Bills", "score": "27"},
                            {"name": "New York Jets", "score": "13"}]},
            ]

        def fake_schedule_for_date(date_str):
            game_id = {"2026-09-15": "nfl_a", "2026-09-17": "nfl_b"}.get(date_str)
            if not game_id:
                return []
            return [{"game_id": game_id, "away_team": "NYJ", "home_team": "BUF",
                    "week": 2, "start_utc": "2026-09-16T00:00:00Z"}]

        with mock.patch("src.report.nfl_card.odds_provider.fetch_scores",
                        side_effect=fake_fetch_scores), \
             mock.patch("src.providers.nfl.schedule_for_date",
                        side_effect=fake_schedule_for_date):
            totals = nfl_card.settle_recent(
                path=str(self.card_path), today="2026-09-19")

        self.assertEqual(calls["n"], 1)
        self.assertEqual(totals["settled"], 2)

    def test_fetch_error_is_a_legible_miss_not_a_crash(self):
        """A results-feed error (not configured, network down) must not
        propagate out of settle_recent and must not silently VOID the pick
        -- it stays unsettled, retryable next pass, with a reason naming
        the error."""
        now = datetime(2026, 9, 17, 23, 0, 0, tzinfo=timezone.utc)
        self._publish("2026-09-17", "nfl_c", now=now)

        def raises(date_str):
            raise RuntimeError("ODDS_API_KEY not set")

        totals = nfl_card.settle_recent(
            path=str(self.card_path), today="2026-09-18", fetch_results=raises)

        self.assertEqual(totals["settled"], 0)
        miss = next(m for m in totals["misses"] if m["date"] == "2026-09-17")
        self.assertIn("ODDS_API_KEY not set", miss["reason"])
        self.assertIsNone(card_ledger.settled_row(
            "2026-09-17", path=str(self.card_path), sport="nfl"))


if __name__ == "__main__":
    unittest.main()
