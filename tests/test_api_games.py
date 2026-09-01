"""api/games.py: the three game-level endpoints, with the network call
stubbed out.

SKIP-IF-NO-FASTAPI, LIKE THE REST OF api/
------------------------------------------
api/ is allowed to depend on FastAPI (tests/test_api_boundary.py is the test
that enforces src/ never does); this repo's test environment does not always
have it installed, though. This file mirrors the pattern api/today.py's own
module docstring anticipates -- if FastAPI is unavailable, api/games.py
cannot even be imported, and the whole class is skipped rather than the
suite failing on an unrelated dependency gap.

The endpoint functions are plain callables (an APIRouter route decorator
registers a route and returns the same function), so they are exercised
directly here -- no live HTTP server and no TestClient needed. The one
network call each one makes (mlb.fetch_games) is patched to a fixed,
offline schedule; the historical store is the real repo store, read
offline, exactly like tests/test_api_today.py already does for /today.

CACHE ISOLATION BETWEEN TESTS
------------------------------
api/games.py now caches `_build_entries` per date (src/appstate/freshness.py)
so repeated requests for the same date share one rebuild -- the whole
point of this task's caching work. Several test methods below reuse the
same "2026-08-31" date on purpose (to exercise the same fixed offline
schedule), which would otherwise mean whichever test runs first "wins" the
cache and every later test in the run observes its result instead of
exercising its own patched `mlb.fetch_games`. `_ResetEntriesCache.setUp`
gives every test a fresh, empty cache so each one still observes its own
patch as if caching did not exist -- caching itself is exercised
separately, in tests/test_appstate_freshness.py.
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
    from api import games as games_mod
    from src.appstate import freshness
    from src.providers import mlb


class _ResetEntriesCache(unittest.TestCase):
    """Shared setUp: see the module docstring's CACHE ISOLATION note."""

    def setUp(self):
        if _HAVE_FASTAPI:
            games_mod._entries_cache = freshness.SingleFlightTTLCache(
                ttl_s=games_mod.ENTRIES_CACHE_TTL_S)


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990101, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetGamesTests(_ResetEntriesCache):

    def test_returns_the_real_slate_list_shape(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = games_mod.get_games("2026-08-31")
        blob = json.loads(json.dumps(payload))  # JSON-serialisable end to end
        self.assertEqual(blob["date"], "2026-08-31")
        self.assertEqual(blob["checked_games"], 1)
        self.assertEqual(len(blob["games"]), 1)
        self.assertEqual(blob["games"][0]["away_team"], "BOS")

    def test_schedule_provider_failure_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                games_mod.get_games("2026-08-31")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("2026-08-31", ctx.exception.detail)

    def test_no_games_scheduled_is_an_honest_empty_slate(self):
        with patch.object(mlb, "fetch_games", return_value=[]):
            payload = games_mod.get_games("2026-12-25")
        self.assertEqual(payload["checked_games"], 0)
        self.assertEqual(payload["games"], [])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetGameTests(_ResetEntriesCache):

    def test_returns_quick_and_advanced_together(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = games_mod.get_game("2026-08-31", "BOS", "NYY")
        blob = json.loads(json.dumps(payload))
        self.assertIn("quick", blob)
        self.assertIn("advanced", blob)
        self.assertEqual(blob["quick"]["away_team"], "BOS")
        self.assertEqual(blob["advanced"]["away_team"], "BOS")

    def test_unknown_game_is_a_structured_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                games_mod.get_game("2026-08-31", "SEA", "TEX")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("SEA", ctx.exception.detail)
        self.assertIn("TEX", ctx.exception.detail)

    def test_unknown_date_is_a_structured_404_not_a_crash(self):
        with patch.object(mlb, "fetch_games", return_value=[]):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                games_mod.get_game("2026-12-25", "BOS", "NYY")
        self.assertEqual(ctx.exception.status_code, 404)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetChangedTests(_ResetEntriesCache):

    def test_returns_the_what_changed_band_shape(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = games_mod.get_changed("2026-08-31")
        blob = json.loads(json.dumps(payload))
        self.assertEqual(blob["date"], "2026-08-31")
        self.assertEqual(blob["checked_games"], 1)
        self.assertIn("items", blob)
        self.assertIn("notes", blob)

    def test_schedule_provider_failure_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                games_mod.get_changed("2026-08-31")
        self.assertEqual(ctx.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
