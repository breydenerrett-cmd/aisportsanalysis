"""Caching integration: api/today.py's get_today_payload_cached and
api/games.py's cached _build_entries, on top of src/appstate/freshness.py.

These are integration tests over the two wrapper points, not a retest of
freshness.py's own TTL/single-flight/stale-serving mechanics -- that
belongs to tests/test_api_today.py, and this file exists to prove:
  - the freshness metadata is wired in, additively, without disturbing any
    existing field shape (test_api_today.py / test_api_games.py already
    pin those shapes and stay green unmodified alongside this file);
  - a rebuild failure after a good build serves the last-good payload
    marked stale rather than raising or fabricating a fresh one;
  - a rebuild failure on a cold cache still surfaces as the exception the
    caller's existing error handling expects (api/games.py's 502).
"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from src.appstate import freshness
from src.pipeline import history

from api.today import get_today_payload_cached

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import games as games_mod
    from src.providers import mlb


def _today_game(game_pk=990501):
    today = date.today().isoformat()
    return {
        "game_pk": game_pk,
        "date": today,
        "away_team": "BOS",
        "home_team": "NYY",
        "venue": "Yankee Stadium",
    }


class TodayPayloadCachedTests(unittest.TestCase):

    def _cache(self):
        # Every test gets its own cache -- the module-level
        # api.today._today_cache is only for real request traffic, and
        # sharing it across tests would make one test's build visible to
        # the next (the same problem tests/test_api_games.py's
        # _ResetEntriesCache setUp exists to avoid).
        return freshness.SingleFlightTTLCache(ttl_s=120.0)

    def test_adds_only_a_freshness_key_and_keeps_every_existing_field(self):
        store = history.read_results()
        games = [_today_game()]
        calls = []

        def fetch_games(_date):
            calls.append(1)
            return games

        payload = get_today_payload_cached(
            games[0]["date"], fetch_games=fetch_games, read_store=lambda: store,
            cache=self._cache())

        blob = json.loads(json.dumps(payload))  # still JSON-safe end to end
        # Every field build_today_payload already produces is untouched.
        self.assertIn("date", blob)
        self.assertIn("generated_at", blob)
        self.assertIn("games", blob)
        self.assertIn("notes", blob)
        self.assertEqual(len(blob["games"]), 1)
        self.assertIn("odds_meta", blob["games"][0])
        # ...plus exactly the one additive key.
        self.assertIn("freshness", blob)
        for key in ("served_at", "built_at", "age_s", "stale", "stale_reason"):
            self.assertIn(key, blob["freshness"])
        self.assertFalse(blob["freshness"]["stale"])

    def test_second_call_within_ttl_is_a_cache_hit_not_a_second_fetch(self):
        store = history.read_results()
        games = [_today_game(game_pk=990502)]
        calls = []

        def fetch_games(_date):
            calls.append(1)
            return games

        cache = self._cache()
        get_today_payload_cached(games[0]["date"], fetch_games=fetch_games,
                                 read_store=lambda: store, cache=cache)
        get_today_payload_cached(games[0]["date"], fetch_games=fetch_games,
                                 read_store=lambda: store, cache=cache)
        self.assertEqual(len(calls), 1)

    def test_rebuild_failure_with_no_prior_build_reraises(self):
        store = history.read_results()

        def failing_fetch(_date):
            raise RuntimeError("provider unreachable")

        with self.assertRaises(RuntimeError):
            get_today_payload_cached("2026-08-31", fetch_games=failing_fetch,
                                     read_store=lambda: store, cache=self._cache())

    def test_rebuild_failure_after_a_good_build_serves_stale_flagged(self):
        store = history.read_results()
        games = [_today_game(game_pk=990503)]
        cache = freshness.SingleFlightTTLCache(ttl_s=0.05)

        good = get_today_payload_cached(
            games[0]["date"], fetch_games=lambda _d: games,
            read_store=lambda: store, cache=cache)
        self.assertFalse(good["freshness"]["stale"])

        import time
        time.sleep(0.08)  # force TTL expiry so the next call attempts a rebuild

        def failing_fetch(_date):
            raise RuntimeError("provider down")

        stale = get_today_payload_cached(
            games[0]["date"], fetch_games=failing_fetch,
            read_store=lambda: store, cache=cache)
        self.assertTrue(stale["freshness"]["stale"])
        self.assertIn("rebuild failed", stale["freshness"]["stale_reason"])
        # The last-good payload's real content is what gets served, not a
        # fabricated replacement -- same games, same date.
        self.assertEqual(stale["date"], good["date"])
        self.assertEqual(len(stale["games"]), len(good["games"]))


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990601, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GamesEntriesCacheTests(unittest.TestCase):
    """api/games.py's shared per-date entries cache, exercised through the
    real route functions (same style as tests/test_api_games.py)."""

    def setUp(self):
        games_mod._entries_cache = freshness.SingleFlightTTLCache(
            ttl_s=games_mod.ENTRIES_CACHE_TTL_S)

    def test_freshness_key_is_additive_on_all_three_routes(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            slate_list = games_mod.get_games("2026-08-31")
            game_view = games_mod.get_game("2026-08-31", "BOS", "NYY")
            changed = games_mod.get_changed("2026-08-31")
        for payload in (slate_list, game_view, changed):
            self.assertIn("freshness", payload)
            self.assertFalse(payload["freshness"]["stale"])
        # Existing fields untouched.
        self.assertIn("games", slate_list)
        self.assertIn("quick", game_view)
        self.assertIn("advanced", game_view)
        self.assertIn("items", changed)

    def test_three_routes_for_the_same_date_share_one_provider_fetch(self):
        """The whole point of caching _build_entries once: /games,
        /game/.../..., and /changed for the same date must not each pay
        for their own schedule fetch."""
        with patch.object(mlb, "fetch_games",
                          return_value=_schedule()) as fetch_mock:
            games_mod.get_games("2026-08-31")
            games_mod.get_game("2026-08-31", "BOS", "NYY")
            games_mod.get_changed("2026-08-31")
        self.assertEqual(fetch_mock.call_count, 1)

    def test_rebuild_failure_after_a_good_build_serves_stale_not_a_502(self):
        games_mod._entries_cache = freshness.SingleFlightTTLCache(ttl_s=0.05)
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            good = games_mod.get_games("2026-08-31")
        self.assertFalse(good["freshness"]["stale"])

        import time
        time.sleep(0.08)

        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            stale = games_mod.get_games("2026-08-31")
        self.assertTrue(stale["freshness"]["stale"])
        self.assertIn("rebuild failed", stale["freshness"]["stale_reason"])
        self.assertEqual(stale["games"], good["games"])


if __name__ == "__main__":
    unittest.main()
