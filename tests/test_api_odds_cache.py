"""api/odds.py's per-date (schedule, multi-book board) cache, exercised
through the real route functions -- same style, same assertions as
tests/test_api_caching.py's GamesEntriesCacheTests for api/games.py's
identical `_build_entries` pattern.

Contract-shape assertions for GET /odds/{date} and
GET /odds/{date}/{away}/{home} (required keys/types, mobile-readiness,
no-board-is-not-an-error) live in tests/test_api_contracts.py; this file is
only about proving the CACHE itself behaves the way api/games.py's does:
same TTL, one shared rebuild per date across both routes, single-flight,
and serve-stale-with-flag on a rebuild failure rather than a bare 502.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.appstate import freshness

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import odds as odds_api
    from src.analysis import prices as prices_mod
    from src.providers import mlb


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990701, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


def _quote(ts, book, away, home):
    return {"ts": ts, "book": book, "away_price": away, "home_price": home}


def _boards(date="2026-08-31"):
    """Six books -- prices.MIN_BOOKS -- so a consensus actually computes
    rather than hitting the below-the-floor `skipped` path; mirrors
    tests/test_api_contracts.py's own odds fixture, except `observed_utc`
    is stamped at call time (not a fixed 2026-08-31 literal): this file's
    tests assert on freshness.SingleFlightTTLCache's own `stale` flag
    (a CACHE fact), and a fixed, ever-aging timestamp would eventually --
    already does, past 2026-08-31 -- trip oddspayload's SEPARATE odds-age
    staleness check instead, for a reason that has nothing to do with what
    these tests are checking.
    """
    observed_utc = datetime.now(timezone.utc).isoformat()
    quotes = [_quote(observed_utc, "fanduel", -110, -110),
              _quote(observed_utc, "draftkings", -108, -112),
              _quote(observed_utc, "betmgm", -105, -115),
              _quote(observed_utc, "caesars", -112, -108),
              _quote(observed_utc, "pointsbet", -115, -105),
              _quote(observed_utc, "wynn", -120, -100)]
    key = ("BOS", "NYY", date)
    return {key: {"quotes": quotes, "observed_utc": observed_utc, "source": "test"}}


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class OddsCacheTests(unittest.TestCase):
    """api/odds.py's shared per-date (games, boards) cache, exercised
    through the real route functions (same style as
    tests/test_api_caching.py's GamesEntriesCacheTests)."""

    def setUp(self):
        # Fresh cache per test -- see tests/test_api_games.py's
        # _ResetEntriesCache docstring for why a shared module-level cache
        # would let one test's fixture leak into the next.
        odds_api._odds_cache = freshness.SingleFlightTTLCache(
            ttl_s=odds_api.ODDS_CACHE_TTL_S)

    def test_freshness_key_is_additive_on_both_routes(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_boards()):
            slate = odds_api.get_odds("2026-08-31")
            game = odds_api.get_odds_game("2026-08-31", "BOS", "NYY")
        for payload in (slate, game):
            self.assertIn("freshness", payload)
            for key in ("served_at", "built_at", "age_s", "stale", "stale_reason"):
                self.assertIn(key, payload["freshness"])
            self.assertFalse(payload["freshness"]["stale"])
        # Existing fields untouched by the additive freshness key.
        self.assertIn("games", slate)
        self.assertIn("summary", slate)
        self.assertIn("markets", game)

    def test_both_routes_for_the_same_date_share_one_rebuild(self):
        """The whole point of caching _build_odds_inputs once: /odds/{date}
        and /odds/{date}/{away}/{home} for the same date must not each pay
        for their own schedule fetch and board-store read."""
        with patch.object(mlb, "fetch_games",
                          return_value=_schedule()) as fetch_mock, \
             patch.object(prices_mod, "boards_by_matchup",
                          return_value=_boards()) as boards_mock:
            odds_api.get_odds("2026-08-31")
            odds_api.get_odds_game("2026-08-31", "BOS", "NYY")
        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(boards_mock.call_count, 1)

    def test_second_call_within_ttl_is_a_cache_hit_not_a_second_fetch(self):
        with patch.object(mlb, "fetch_games",
                          return_value=_schedule()) as fetch_mock, \
             patch.object(prices_mod, "boards_by_matchup",
                          return_value=_boards()) as boards_mock:
            first = odds_api.get_odds("2026-08-31")
            second = odds_api.get_odds("2026-08-31")
        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(boards_mock.call_count, 1)
        # A cache hit still rebuilds the JSON payload fresh against `now`
        # (see api/odds.py's CACHING docstring), so only the STABLE content
        # -- never a live-clock field like staleness.age_seconds -- is
        # compared here.
        self.assertEqual(first["games"][0]["away_team"],
                         second["games"][0]["away_team"])
        self.assertEqual(first["summary"]["games_count"],
                         second["summary"]["games_count"])

    def test_rebuild_failure_after_a_good_build_serves_stale_not_a_502(self):
        odds_api._odds_cache = freshness.SingleFlightTTLCache(ttl_s=0.05)
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_boards()):
            good = odds_api.get_odds("2026-08-31")
        self.assertFalse(good["freshness"]["stale"])

        time.sleep(0.08)  # force TTL expiry so the next call attempts a rebuild

        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            stale = odds_api.get_odds("2026-08-31")
        self.assertTrue(stale["freshness"]["stale"])
        self.assertIn("rebuild failed", stale["freshness"]["stale_reason"])
        # The last-good (games, boards) pair is what gets served, not a
        # fabricated replacement -- same game, same summary count.
        self.assertEqual(len(stale["games"]), len(good["games"]))
        self.assertEqual(stale["games"][0]["away_team"], good["games"][0]["away_team"])

    def test_rebuild_failure_with_no_prior_build_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_api.get_odds("2026-08-31")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("2026-08-31", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
