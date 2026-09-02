"""api/odds.py: the two Odds-tab endpoints, with the network call and the
multi-book store both stubbed out.

SKIP-IF-NO-FASTAPI, LIKE THE REST OF api/
------------------------------------------
Same pattern as tests/test_api_games.py: api/ is allowed to depend on
FastAPI, this repo's test environment does not always have it installed, so
the whole class is skipped rather than the suite failing on an unrelated
dependency gap.

The endpoint functions are plain callables (an APIRouter route decorator
registers a route and returns the same function), so they are exercised
directly here -- no live HTTP server needed. Both the schedule fetch
(mlb.fetch_games) and the multi-book board read (prices.boards_by_matchup)
are patched to fixed, offline data.

CACHE ISOLATION BETWEEN TESTS
------------------------------
api/odds.py now caches `_build_odds_inputs` per date (src/appstate/
freshness.py), mirroring api/games.py's `_build_entries`. Several test
methods below reuse "2026-08-31" on purpose (the same fixed offline
schedule/board fixtures), which would otherwise mean whichever test runs
first "wins" the cache and every later same-date test -- including the two
`..._schedule_provider_failure_is_a_structured_502` tests, which need
`mlb.fetch_games` to actually be CALLED to raise -- observes a cached
result instead of its own patch. `_ResetOddsCache.setUp` gives every test a
fresh, empty cache so each one still observes its own patch as if caching
did not exist -- caching itself is exercised separately, in
tests/test_api_odds_cache.py (same split tests/test_api_games.py and
tests/test_api_caching.py already use for the identical games.py pattern).
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import odds as odds_mod
    from src.analysis import prices as prices_mod
    from src.appstate import freshness
    from src.providers import mlb


class _ResetOddsCache(unittest.TestCase):
    """Shared setUp: see the module docstring's CACHE ISOLATION note."""

    def setUp(self):
        if _HAVE_FASTAPI:
            odds_mod._odds_cache = freshness.SingleFlightTTLCache(
                ttl_s=odds_mod.ODDS_CACHE_TTL_S)

TS = "2026-08-31T19:55:00Z"


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990101, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


def _quote(book, away, home):
    return {"ts": TS, "book": book, "away_price": away, "home_price": home}


def _boards(date="2026-08-31"):
    quotes = [_quote("fanduel", -110, -110), _quote("draftkings", -108, -112),
              _quote("betmgm", -105, -115), _quote("caesars", -112, -108),
              _quote("pointsbet", -115, -105), _quote("wynn", -120, -100)]
    key = ("BOS", "NYY", date)
    return {key: {"quotes": quotes, "observed_utc": TS, "source": "test"}}


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetOddsTests(_ResetOddsCache):

    def test_returns_the_slate_odds_shape(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_boards()):
            payload = odds_mod.get_odds("2026-08-31")
        blob = json.loads(json.dumps(payload))  # JSON-serialisable end to end
        self.assertEqual(blob["date"], "2026-08-31")
        self.assertEqual(blob["summary"]["games_count"], 1)
        self.assertEqual(len(blob["games"]), 1)
        game = blob["games"][0]
        self.assertEqual(game["away_team"], "BOS")
        self.assertTrue(game["markets"]["h2h"]["board_available"])
        self.assertIsNotNone(game["markets"]["h2h"]["consensus"])

    def test_no_games_scheduled_is_an_honest_empty_slate(self):
        with patch.object(mlb, "fetch_games", return_value=[]), \
             patch.object(prices_mod, "boards_by_matchup", return_value={}):
            payload = odds_mod.get_odds("2026-12-25")
        self.assertEqual(payload["summary"]["games_count"], 0)
        self.assertEqual(payload["games"], [])

    def test_schedule_provider_failure_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games", side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_mod.get_odds("2026-08-31")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("2026-08-31", ctx.exception.detail)

    def test_malformed_date_is_a_400_not_a_502(self):
        """Same fix as api/games.py: a malformed date is refused before it
        ever reaches mlb.fetch_games, not surfaced as a provider 502."""
        with patch.object(mlb, "fetch_games") as fetch:
            for bad in ("not-a-date", "2026-13-45", "08/31/2026", ""):
                with self.subTest(bad=bad):
                    with self.assertRaises(fastapi.HTTPException) as ctx:
                        odds_mod.get_odds(bad)
                    self.assertEqual(ctx.exception.status_code, 400)
            fetch.assert_not_called()


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetOddsGameTests(_ResetOddsCache):

    def test_returns_one_game_odds_payload(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_boards()):
            payload = odds_mod.get_odds_game("2026-08-31", "BOS", "NYY")
        blob = json.loads(json.dumps(payload))
        self.assertEqual(blob["away_team"], "BOS")
        self.assertEqual(blob["home_team"], "NYY")
        self.assertTrue(blob["markets"]["h2h"]["board_available"])

    def test_unknown_game_is_a_structured_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_boards()):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_mod.get_odds_game("2026-08-31", "SEA", "TEX")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("SEA", ctx.exception.detail)
        self.assertIn("TEX", ctx.exception.detail)

    def test_unknown_date_is_a_structured_404_not_a_crash(self):
        with patch.object(mlb, "fetch_games", return_value=[]):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_mod.get_odds_game("2026-12-25", "BOS", "NYY")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_schedule_provider_failure_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games", side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_mod.get_odds_game("2026-08-31", "BOS", "NYY")
        self.assertEqual(ctx.exception.status_code, 502)

    def test_malformed_date_is_a_400_not_a_502(self):
        with patch.object(mlb, "fetch_games") as fetch:
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_mod.get_odds_game("not-a-date", "BOS", "NYY")
            self.assertEqual(ctx.exception.status_code, 400)
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
