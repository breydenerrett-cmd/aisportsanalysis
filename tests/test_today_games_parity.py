"""tests/test_today_games_parity.py

MISSION (today_parity track, 2026-09-14): GET /today built its slate with
`briefing.build_slate(games, store, **build_slate_kwargs)` and api/app.py
passed no enrichment inputs at all, while GET /games/{date}
(api/games._build_entries) always passed
`src.pipeline.enrichment.enrichment_inputs(games, date, store)`. Same game,
two different sets of facts handed to the same domain function -- and on
2026-09-12 that produced two different verdicts for the same KC@BOS game:
no_play on /today, market_unavailable on /games/{date}.

This file proves the fix (api/today.py's build_today_payload now loads the
same enrichment_inputs api/games._build_entries does, a caller's explicit
build_slate kwarg still winning per dict.update precedence) two ways:

1. Both builders call `enrichment_inputs` with the IDENTICAL (games, date,
   store) -- proven by spying on the one function both of them call.
2. Given the same injected games/store, the two builders produce the
   IDENTICAL verdict for the same game -- the actual customer-visible bug.

Offline, no network: mlb.fetch_games and history.read_results are patched
for the /games path (api/games._build_entries fetches them itself);
build_today_payload takes games/store as direct arguments so no patch is
needed there. Every other store enrichment_inputs reads (pitcher logs,
lineups, bullpen, weather, standings, travel, splits, news, arsenals) is
the real, offline, absent-safe repo store -- the same thing
tests/test_api_today.py and tests/test_api_games.py already read directly.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import games as games_mod
    from api import today as today_mod
    from src.appstate import freshness
    from src.pipeline import enrichment
    from src.providers import mlb


# A far-future date, real-shaped (ISO, passes _validate_date) but never used
# by any other test file or real capture, so this file's cache-fill can
# never collide with another test's or a real request's entry under the
# same ("games_entries", date) key -- on top of the fresh per-test cache
# instance below (see tests/test_api_games.py's _ResetEntriesCache
# docstring for the collision history that guards against).
_PARITY_DATE = "2099-09-09"


def _game(pk, date_str=_PARITY_DATE):
    return {
        "game_pk": pk,
        "date": date_str,
        "away_team": "BOS",
        "home_team": "NYY",
        "venue": "Yankee Stadium",
        "start_time_utc": f"{date_str}T23:05:00Z",
    }


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class TodayGamesEnrichmentParityTests(unittest.TestCase):
    """/today and /games/{date} must hand build_slate the identical
    store-backed enrichment inputs for the identical game, so the same game
    can never carry two verdicts across the two endpoints again."""

    def setUp(self):
        # Same isolation as tests/test_api_games.py's _ResetEntriesCache:
        # swap in a fresh entries cache for the /games path so a prior
        # test's (or a prior run's) cached build under this date can never
        # stand in for this test's own patched rebuild.
        self._real_entries_cache = games_mod._entries_cache
        games_mod._entries_cache = freshness.SingleFlightTTLCache(
            ttl_s=games_mod.ENTRIES_CACHE_TTL_S,
            stale_while_revalidate_s=games_mod.ENTRIES_STALE_WINDOW_S)

    def tearDown(self):
        games_mod._entries_cache = self._real_entries_cache

    def test_both_builders_call_enrichment_inputs_with_identical_args(self):
        """Regression test for the missing call. Before the fix,
        api/today.py never imported `enrichment` and never called
        `enrichment_inputs` at all -- build_today_payload went straight to
        `briefing.build_slate(games, store, **build_slate_kwargs)` with
        whatever (nothing) api/app.py passed. So only ONE call, from
        api/games._build_entries, would ever land in `recorded` here; this
        assertion (`len(recorded) == 2`) fails outright against that code
        (recorded has 1 entry, not 2) -- proof the test catches the defect
        it names, not just its own patching machinery.
        """
        games = [_game(880001)]
        store = {"990000": {"game_pk": "990000"}}
        recorded = []
        original = enrichment.enrichment_inputs

        def spy(games_arg, date_arg, store_arg):
            recorded.append((games_arg, date_arg, store_arg))
            return original(games_arg, date_arg, store_arg)

        with patch.object(enrichment, "enrichment_inputs", side_effect=spy), \
             patch.object(games_mod, "_enrichment_inputs", side_effect=spy), \
             patch.object(mlb, "fetch_games", return_value=games), \
             patch.object(games_mod.history, "read_results", return_value=store):
            today_mod.build_today_payload(games, store, date=_PARITY_DATE)
            games_mod._build_entries(_PARITY_DATE)

        self.assertEqual(
            len(recorded), 2,
            "expected one enrichment_inputs call from build_today_payload "
            "and one from _build_entries; got %d -- /today is not routing "
            "through enrichment_inputs" % len(recorded))
        today_call, games_call = recorded
        self.assertEqual(today_call, games_call,
                         "the two builders called enrichment_inputs with "
                         "different (games, date, store) for the same game")

    def test_identical_verdict_across_both_builders_on_the_same_inputs(self):
        """The actual customer-visible symptom (2026-09-12, KC@BOS):
        no_play on /today, market_unavailable on /games/{date} for the same
        game at the same moment, because /today never saw the lineups,
        bullpen, weather, standings etc. that /games/{date} did. With the
        same injected games/store this must now be one verdict, not two --
        proven here through the REAL, unmocked briefing.build_slate on both
        sides, so a divergence anywhere in that path (not just a missing
        enrichment_inputs call) would still be caught.
        """
        games = [_game(880002)]
        store = {}

        with patch.object(mlb, "fetch_games", return_value=games), \
             patch.object(games_mod.history, "read_results", return_value=store):
            payload = today_mod.build_today_payload(games, store, date=_PARITY_DATE)
            entries, _notes, _meta = games_mod._build_entries(_PARITY_DATE)

        self.assertEqual(len(payload["games"]), 1)
        self.assertEqual(len(entries), 1)
        today_verdict = payload["games"][0]["verdict"]
        games_verdict = entries[0]["verdict"]
        self.assertEqual(
            today_verdict, games_verdict,
            "/today (%r) and /games/{date} (%r) disagreed on the verdict "
            "for the identical game built from identical inputs"
            % (today_verdict, games_verdict))

    def test_a_callers_explicit_kwarg_still_wins_over_the_loaded_default(self):
        """The mission's own precedence rule: 'a caller's explicit kwarg
        still wins'. build_today_payload must not clobber a caller-supplied
        build_slate kwarg with whatever enrichment_inputs loaded for that
        same key -- mirrors api/games._build_entries's own
        `inputs.update(build_slate_kwargs)` precedence exactly."""
        games = [_game(880003)]
        store = {}
        # A real-shaped (empty, not malformed) pitcher_logs value: downstream
        # dossier.build code (src/pipeline/pitchers.py) iterates each
        # player's appearance list, so a non-dict/non-appearance-shaped
        # sentinel would crash there rather than prove the precedence rule.
        # Object identity (assertIs below) distinguishes this from whatever
        # the loaded default happens to be, regardless of its own shape.
        sentinel_logs = {}

        payload = today_mod.build_today_payload(
            games, store, date=_PARITY_DATE, pitcher_logs=sentinel_logs)

        # No direct way to inspect what build_slate received without
        # spying on it too, so spy here specifically for this assertion.
        captured = {}
        real_build_slate = today_mod.briefing.build_slate

        def spy_build_slate(games_arg, store_arg, **kwargs):
            captured.update(kwargs)
            return real_build_slate(games_arg, store_arg, **kwargs)

        with patch.object(today_mod.briefing, "build_slate",
                          side_effect=spy_build_slate):
            today_mod.build_today_payload(
                games, store, date=_PARITY_DATE, pitcher_logs=sentinel_logs)

        self.assertIs(captured.get("pitcher_logs"), sentinel_logs)
        # Also prove the payload still built successfully with the
        # caller's override in place (round-trips, no crash).
        self.assertEqual(len(payload["games"]), 1)


if __name__ == "__main__":
    unittest.main()
