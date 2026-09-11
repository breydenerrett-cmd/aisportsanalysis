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
    from src.appstate import events, freshness
    from src.providers import mlb


class _FakeState:
    def __init__(self, user_id):
        self.user_id = user_id


class _FakeRequest:
    """Stands in for the FastAPI Request object api/games.py reads
    `request.state.user_id` off of -- see api/auth.py's get_current_user,
    which is what actually populates that attribute on a real request."""

    def __init__(self, user_id=None):
        self.state = _FakeState(user_id)


class _ResetEntriesCache(unittest.TestCase):
    """Shared setUp: see the module docstring's CACHE ISOLATION note.

    TWO THINGS THIS GOT WRONG UNTIL 2026-09-11, both silent.

    It built the replacement with `ttl_s` ONLY, dropping
    `ENTRIES_STALE_WINDOW_S`. Production serves stale past the TTL and
    rebuilds behind the caller -- that is the fix for the spinning-slate
    outage -- so every test in this file was exercising a cache shape the
    app does not run.

    And it never put the module's own cache back. The swap outlived the
    class, so whichever of the three files touching `_entries_cache` ran
    last left api.games holding a test double for the remainder of the
    suite. `tests/test_stale_while_revalidate.py` failed on that: green
    alone, red in the full run, asserting against an object this file had
    replaced.
    """

    def setUp(self):
        if not _HAVE_FASTAPI:
            return
        self._real_entries_cache = games_mod._entries_cache
        games_mod._entries_cache = freshness.SingleFlightTTLCache(
            ttl_s=games_mod.ENTRIES_CACHE_TTL_S,
            stale_while_revalidate_s=games_mod.ENTRIES_STALE_WINDOW_S)

    def tearDown(self):
        if _HAVE_FASTAPI:
            games_mod._entries_cache = self._real_entries_cache


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

    def test_malformed_date_is_a_400_not_a_502(self):
        """Red-team round: a malformed {date} used to reach mlb.fetch_games
        unchecked, where src.providers.mlb's own validation raised
        MLBError -- surfacing as this module's 502, a schedule-provider
        failure that was actually the caller's bad input. fetch_games is
        never even called: the malformed date is refused before any
        network path is reached."""
        with patch.object(mlb, "fetch_games") as fetch:
            for bad in ("not-a-date", "2026-13-45", "08/31/2026", "",
                       "2026-08-31T00:00:00Z", "2026-8-31"):
                with self.subTest(bad=bad):
                    with self.assertRaises(fastapi.HTTPException) as ctx:
                        games_mod.get_games(bad)
                    self.assertEqual(ctx.exception.status_code, 400)
            fetch.assert_not_called()

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


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class PageViewEventTests(_ResetEntriesCache):
    """page_view wiring: recorded on a successful GET with a real Request
    carrying a user id, never without one, and never on a 4xx/502."""

    def setUp(self):
        super().setUp()
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        from pathlib import Path
        self.db = Path(self._tmp.name) / "app.db"
        self.addCleanup(self._tmp.cleanup)

    def test_no_request_records_nothing(self):
        """Every existing direct-call test in this file calls these
        functions with no Request -- must keep behaving exactly as before,
        just uninstrumented."""
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            games_mod.get_games("2026-08-31")
        safe.assert_not_called()

    def test_get_games_records_page_view_for_the_authed_caller(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            games_mod.get_games("2026-08-31", request=_FakeRequest(user_id=7))
        safe.assert_called_once_with(
            7, events.PAGE_VIEW, {"route": "/games/{date}", "date": "2026-08-31"})

    def test_get_game_records_page_view_only_on_the_match(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            games_mod.get_game("2026-08-31", "BOS", "NYY", request=_FakeRequest(7))
        safe.assert_called_once_with(
            7, events.PAGE_VIEW,
            {"route": "/game/{date}/{away}/{home}", "date": "2026-08-31"})

    def test_get_game_records_nothing_on_a_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            with self.assertRaises(fastapi.HTTPException):
                games_mod.get_game("2026-08-31", "SEA", "TEX", request=_FakeRequest(7))
        safe.assert_not_called()

    def test_get_changed_records_page_view(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            games_mod.get_changed("2026-08-31", request=_FakeRequest(7))
        safe.assert_called_once_with(
            7, events.PAGE_VIEW, {"route": "/changed/{date}", "date": "2026-08-31"})

    def test_a_request_with_no_user_id_records_nothing(self):
        """A Request whose state.user_id was never set (should never happen
        on a real authed request, but this must not crash if it does)."""
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            games_mod.get_games("2026-08-31", request=_FakeRequest(user_id=None))
        safe.assert_not_called()

    def test_a_broken_events_db_never_breaks_the_response(self):
        """End-to-end through the real record_event_safe (not mocked) --
        proves the whole chain, not just that games.py calls the wrapper."""
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event",
                          side_effect=RuntimeError("disk full")):
            payload = games_mod.get_games("2026-08-31", request=_FakeRequest(7))
        self.assertEqual(payload["checked_games"], 1)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# F-2 (2026-09-07): the store-backed enrichment inputs reach build_slate.
#
# These test the WIRING, not the stores' contents: briefing.build_slate is
# replaced with a spy that records its kwargs, and each store reader is
# patched on its own module. That keeps the tests hermetic and keeps them
# from fabricating a results-store shape team_features would have to parse.
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class EnrichmentWiringTests(_ResetEntriesCache):

    def _spy_slate(self):
        seen = {}

        def fake_build_slate(games, store, **kwargs):
            seen.update(kwargs)
            return {"games": [], "notes": []}
        return seen, fake_build_slate

    def _run(self, seen_builder, *, results=None, logs=None, pen_log=None,
             pen_log_error=None, lineup_rows=None, handedness=None,
             weather_rows=None):
        """Explicit names per store. Two of the readers are both called
        `read` (lineup_store.read, weather_capture.read), so keying patches
        by bare function name once handed the weather rows to the lineup
        store as well -- which is a list, and `.get` on it was the first
        failure this test ever produced. Named by what they ARE instead.

        `pen_log_error` exists because a caller CANNOT wrap this helper in
        its own `with patch.object(bullpen, "read_log", ...)`. Two things
        went wrong when one did, and both were silent:

        1. The store patches here are started with `addCleanup`, which runs
           at tearDown -- AFTER an enclosing `with` block has already
           unwound. So the inner patcher's stop reinstated the OUTER mock
           and left it installed for the rest of the process.
           tests/test_pipeline_bullpen.py then failed with 'bad line', a
           message from a mock in this file, but only when the two ran in
           the same session.

        2. This helper patches `read_log` again, after the enclosing `with`
           took effect, so the outer mock never reached `_build_entries` at
           all. The corrupt-log test passed while exercising an EMPTY log.

        Raising behaviour therefore has to be installed by this helper, in
        the same LIFO order as every other patch.
        """
        from src.pipeline import (briefing, bullpen, history, lineup_store,
                                  lineups, pitchers, travel, weather_capture)
        seen, fake = seen_builder()
        targets = [
            (history, "read_results", results if results is not None else {}),
            (pitchers, "read_logs", logs if logs is not None else {}),
            (lineup_store, "read", lineup_rows if lineup_rows is not None else {}),
            (lineups, "read_handedness", handedness if handedness is not None else {}),
            (weather_capture, "read", weather_rows if weather_rows is not None else []),
        ]
        patches = [patch.object(mod, name, return_value=value)
                   for mod, name, value in targets]
        if pen_log_error is not None:
            patches.append(patch.object(bullpen, "read_log",
                                        side_effect=pen_log_error))
        else:
            patches.append(patch.object(
                bullpen, "read_log",
                return_value=pen_log if pen_log is not None else []))
        patches.append(patch.object(briefing, "build_slate", side_effect=fake))
        patches.append(patch.object(mlb, "fetch_games", return_value=_schedule()))
        patches.append(patch.object(travel, "travel_load",
                                    return_value={"miles": 0, "reason": None}))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        games_mod._build_entries("2026-08-31")
        return seen

    def test_every_store_is_handed_to_build_slate_when_present(self):
        seen = self._run(
            self._spy_slate,
            results={"990101": {"game_pk": "990101"}},
            logs={"123": [{"ip": 6.0}]},
            pen_log=[{"team": "BOS", "date": "2026-08-30"}],
            weather_rows=[{"game_pk": 990101, "observed_utc": "2026-08-31T12:00:00Z",
                   "forecast_hour_utc": "2026-08-31T23:00:00Z",
                   "forecast_hour_offset_hours": 0.0, "temp_f": 71.0,
                   "humidity_pct": 40, "wind_mph": 5.0, "wind_from_deg": 180,
                   "precip_probability_pct": 10, "pressure_hpa": 1012.0}],
            handedness={"123": {"bats": "R", "throws": "R"}},
        )
        self.assertIsNotNone(seen.get("pitcher_logs"))
        self.assertIsNotNone(seen.get("handedness"))
        self.assertIsNotNone(seen.get("weather_by_pk"))
        self.assertIsNotNone(seen.get("travel_by_pk"))
        # The weather reading is reshaped to extract_hour's own keys, and
        # keyed by the schedule's game_pk value.
        reading = seen["weather_by_pk"][990101]
        self.assertEqual(reading["observed_utc"], "2026-08-31T23:00:00Z")
        self.assertEqual(reading["temp_f"], 71.0)
        self.assertNotIn("park", reading)

    def test_absent_stores_are_none_never_an_error(self):
        """A container built without data/historical/ must behave exactly as
        the API did before F-2: every input None, dossier.build records the
        gap, nothing raises."""
        seen = self._run(self._spy_slate)
        for key in ("pitcher_logs", "bullpen_by_team", "lineups_by_pk",
                    "handedness", "weather_by_pk"):
            self.assertIsNone(seen.get(key), key)

    def test_lineups_are_rekeyed_from_the_stores_str_to_the_schedules_int(self):
        """lineup_store.read() keys by str; the schedule carries int; build_slate
        looks up by the schedule's value. The store's own docstring records
        this exact mismatch once silently matching nothing. Guarded."""
        seen = self._run(
            self._spy_slate,
            lineup_rows={"990101": {"game_pk": "990101", "date": "2026-08-31",
                                    "away": [{"person_id": 1}], "home": []}},
        )
        self.assertIn(990101, seen["lineups_by_pk"])
        self.assertNotIn("990101", seen["lineups_by_pk"])

    def test_a_corrupt_bullpen_log_is_a_gap_not_a_500(self):
        # Through _run's own parameter, not an enclosing `with` -- see that
        # helper's docstring for the two failures the `with` version caused,
        # including this assertion passing against an empty log rather than
        # a corrupt one.
        from src.pipeline import bullpen
        seen = self._run(self._spy_slate,
                         pen_log_error=bullpen.BullpenError("bad line"))
        self.assertIsNone(seen.get("bullpen_by_team"))
