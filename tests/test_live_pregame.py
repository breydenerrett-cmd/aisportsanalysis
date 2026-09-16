"""Tests for scripts/live_pregame_check.py (R16-L2)."""

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_pregame_check.py"
_spec = importlib.util.spec_from_file_location("live_pregame_check", _SCRIPT_PATH)
live_pregame_check = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("live_pregame_check", live_pregame_check)
_spec.loader.exec_module(live_pregame_check)


def _six_book_rows(event_id, commence_time, observed_utc,
                   home_price=-150, away_price=130,
                   home_team="St. Louis Cardinals", away_team="San Francisco Giants"):
    return [
        {"event_id": event_id, "commence_time": commence_time,
         "home_team": home_team, "away_team": away_team,
         "observed_utc": observed_utc, "book": f"book{i}",
         "home_price": home_price, "away_price": away_price}
        for i in range(6)
    ]


class TestLivePregameCheckIsReadOnly(unittest.TestCase):
    """No paid API call: only fetch_games (free MLB Stats API), and the odds
    rows / gamekey map are handed in, never fetched by this script itself."""

    def test_run_takes_every_input_injected(self):
        games = [{"game_pk": 1, "home_team": "STL", "away_team": "SF",
                  "start_time_utc": "2026-09-15T23:15:00Z",
                  "home_probable_id": 1, "away_probable_id": 2}]
        rows = _six_book_rows("eid1", "2026-09-15T23:15:00Z",
                              "2026-09-15T20:00:00Z")
        gamekey_map = {"eid1": {"game_pk": "1"}}

        called = {"fetch_games": 0}

        def fake_fetch_games(date):
            called["fetch_games"] += 1
            return games

        context = live_pregame_check.run(
            "2026-09-15",
            fetch_games=fake_fetch_games,
            load_map=lambda: gamekey_map,
            load_odds_rows=lambda date: rows,
            now=datetime(2026, 9, 15, 20, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(called["fetch_games"], 1)  # the only network call
        self.assertIn("1", context)
        self.assertTrue(context["1"]["usable"])
        self.assertIsNotNone(context["1"]["favorite"])
        self.assertIsNotNone(context["1"]["favorite_prob"])


class TestRenderIsThinAndPresentational(unittest.TestCase):
    """render() must not reimplement build_pregame_context's logic -- it
    only formats whatever the builder returned."""

    def test_usable_game_prints_favorite_prob_books_starter(self):
        from src.pipeline import livefeed_mlb

        games = [{"game_pk": 1, "home_team": "STL", "away_team": "SF",
                  "start_time_utc": "2026-09-15T23:15:00Z",
                  "home_probable_id": 555, "away_probable_id": 777}]
        rows = _six_book_rows("eid1", "2026-09-15T23:15:00Z",
                              "2026-09-15T20:00:00Z")
        gamekey_map = {"eid1": {"game_pk": "1"}}
        context = livefeed_mlb.build_pregame_context(games, rows, gamekey_map)

        output = live_pregame_check.render(context)
        self.assertIn("USABLE", output)
        self.assertIn("favorite=", output)
        self.assertIn("prob=", output)
        self.assertIn("books=6", output)
        self.assertIn("starter=", output)

    def test_unusable_game_prints_reason_not_usable(self):
        from src.pipeline import livefeed_mlb

        games = [{"game_pk": 2, "home_team": "A", "away_team": "B",
                  "start_time_utc": "2026-09-15T23:00:00Z"}]
        context = livefeed_mlb.build_pregame_context(games, [], {})

        output = live_pregame_check.render(context)
        self.assertIn("NOT USABLE", output)
        self.assertIn("gamekey map", output)
        self.assertNotIn("favorite=", output)


if __name__ == "__main__":
    unittest.main()
