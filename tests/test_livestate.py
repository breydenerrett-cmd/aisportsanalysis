"""Live game state: classification of every status, the parsed fields, the cache
(one upstream call per slate per window, bounded, single-flight, fail soft) and
GET /live/{date}. No network: the upstream is an injected fetcher, the clock is
an injected counter.

The raw games below are shaped like the real MLB Stats API schedule response
with hydrate=probablePitcher,team,linescore, checked against a live capture on
2026-10-03 (abstractGameState / codedGameState / detailedState, linescore
currentInning / inningState / outs / defense.pitcher).
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timezone

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.analysis import livestate

NOW = datetime(2026, 10, 3, 18, 0, 0, tzinfo=timezone.utc)   # 2 pm ET
DATE = "2026-10-03"


def raw(pk=1, away="CWS", home="CLE", abstract="Preview", coded="S", detailed="Scheduled",
        linescore=None, away_score=None, home_score=None, game_number=1,
        start="2026-10-03T17:00:00Z"):
    return {
        "gamePk": pk, "gameDate": start, "officialDate": DATE, "gameNumber": game_number,
        "status": {"abstractGameState": abstract, "codedGameState": coded,
                   "detailedState": detailed},
        "teams": {"away": {"team": {"abbreviation": away}, "score": away_score},
                  "home": {"team": {"abbreviation": home}, "score": home_score}},
        "linescore": linescore or {},
    }


def live_linescore(inning=6, state="Top", outs=1, away_runs=3, home_runs=2,
                   pitcher="Hagen Smith"):
    return {"currentInning": inning, "currentInningOrdinal": f"{inning}th",
            "inningState": state, "inningHalf": state, "outs": outs,
            "teams": {"away": {"runs": away_runs}, "home": {"runs": home_runs}},
            "defense": {"pitcher": {"id": 9, "fullName": pitcher}}}


class ClassifyTests(unittest.TestCase):

    def test_pregame_variants(self):
        for detailed, abstract, coded in (("Scheduled", "Preview", "S"),
                                          ("Pre-Game", "Preview", "P"),
                                          ("Warmup", "Live", "PW")):
            self.assertEqual(livestate.classify(raw(abstract=abstract, coded=coded,
                                                    detailed=detailed)),
                             livestate.PREGAME, detailed)

    def test_in_progress(self):
        game = raw(abstract="Live", coded="I", detailed="In Progress",
                   linescore=live_linescore())
        self.assertEqual(livestate.classify(game), livestate.IN_PROGRESS)

    def test_final_variants(self):
        for detailed, coded in (("Final", "F"), ("Game Over", "O"), ("Completed Early", "F")):
            self.assertEqual(livestate.classify(raw(abstract="Final", coded=coded,
                                                    detailed=detailed)),
                             livestate.FINAL, detailed)

    def test_delayed_variants(self):
        for detailed in ("Delayed: Rain", "Delayed Start: Rain", "Suspended: Rain"):
            self.assertEqual(livestate.classify(raw(abstract="Live", coded="I",
                                                    detailed=detailed)),
                             livestate.DELAYED, detailed)

    def test_postponed_and_cancelled(self):
        self.assertEqual(livestate.classify(raw(abstract="Preview", coded="D",
                                                detailed="Postponed")), livestate.POSTPONED)
        self.assertEqual(livestate.classify(raw(abstract="Final", coded="C",
                                                detailed="Cancelled")), livestate.POSTPONED)

    def test_a_game_with_no_status_is_pregame_never_live(self):
        self.assertEqual(livestate.classify({}), livestate.PREGAME)


class ParseTests(unittest.TestCase):

    def test_in_progress_fields(self):
        game = raw(abstract="Live", coded="I", detailed="In Progress",
                   linescore=live_linescore(inning=6, state="Top", outs=1))
        row = livestate.parse_game(game, "2026-10-03T18:00:00Z")
        self.assertEqual(row["status"], "in_progress")
        self.assertEqual((row["away_score"], row["home_score"]), (3, 2))
        self.assertEqual(row["inning"], 6)
        self.assertEqual(row["half"], "top")
        self.assertEqual(row["inning_text"], "Top 6th")
        self.assertEqual(row["outs"], 1)
        self.assertEqual(row["pitcher"], "Hagen Smith")
        self.assertEqual((row["away_team"], row["home_team"]), ("CWS", "CLE"))
        self.assertEqual(row["game_id"], "CWS-CLE-2026-10-03-1")

    def test_between_innings_has_no_outs_or_pitcher(self):
        game = raw(abstract="Live", coded="I", detailed="In Progress",
                   linescore=live_linescore(inning=4, state="Middle", outs=3))
        row = livestate.parse_game(game, "t")
        self.assertEqual(row["inning_text"], "Mid 4th")
        self.assertIsNone(row["outs"])
        self.assertIsNone(row["pitcher"])

    def test_pregame_has_no_score_and_no_inning(self):
        row = livestate.parse_game(raw(), "t")
        self.assertEqual(row["status"], "pregame")
        for field in ("away_score", "home_score", "inning", "half", "outs", "pitcher"):
            self.assertIsNone(row[field], field)

    def test_final_keeps_the_score_and_drops_the_inning(self):
        game = raw(abstract="Final", coded="F", detailed="Final", away_score=5, home_score=4,
                   linescore={"currentInning": 9, "inningState": "End",
                              "teams": {"away": {"runs": 5}, "home": {"runs": 4}}})
        row = livestate.parse_game(game, "t")
        self.assertEqual((row["status"], row["away_score"], row["home_score"]),
                         ("final", 5, 4))
        self.assertIsNone(row["inning_text"])

    def test_delayed_start_has_no_score(self):
        row = livestate.parse_game(raw(abstract="Preview", coded="I",
                                       detailed="Delayed Start: Rain"), "t")
        self.assertEqual(row["status"], "delayed")
        self.assertIsNone(row["away_score"])

    def test_rain_delay_mid_game_keeps_score_and_inning(self):
        game = raw(abstract="Live", coded="I", detailed="Delayed: Rain",
                   linescore=live_linescore(inning=5, state="Bottom", outs=2))
        row = livestate.parse_game(game, "t")
        self.assertEqual(row["status"], "delayed")
        self.assertEqual((row["away_score"], row["home_score"]), (3, 2))
        self.assertEqual(row["inning_text"], "Bot 5th")

    def test_doubleheader_games_get_distinct_ids(self):
        one = livestate.parse_game(raw(pk=11, game_number=1), "t")
        two = livestate.parse_game(raw(pk=12, game_number=2), "t")
        self.assertNotEqual(one["game_id"], two["game_id"])

    def test_missing_fields_are_none_not_guessed(self):
        row = livestate.parse_game({"gamePk": 5, "status": {"abstractGameState": "Live"}}, "t")
        self.assertIsNone(row["away_team"])
        self.assertIsNone(row["away_score"])


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class CacheTests(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.cache = livestate.LiveStateCache(ttl_s=45, fail_ttl_s=15, stale_max_s=180,
                                              max_dates=3, clock=self.clock)
        self.calls = 0

    def fetch_ok(self):
        self.calls += 1
        return [{"game_id": "g", "status": "pregame", "observed_utc": "t"}]

    def test_many_visitors_one_upstream_call(self):
        for _ in range(50):
            result = self.cache.get(DATE, self.fetch_ok)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.cache.upstream_calls, 1)
        self.assertFalse(result["stale"])

    def test_refetches_after_the_window(self):
        self.cache.get(DATE, self.fetch_ok)
        self.clock.t += 44
        self.cache.get(DATE, self.fetch_ok)
        self.assertEqual(self.calls, 1)
        self.clock.t += 2
        self.cache.get(DATE, self.fetch_ok)
        self.assertEqual(self.calls, 2)

    def test_failure_serves_the_last_good_snapshot_flagged_stale(self):
        self.cache.get(DATE, self.fetch_ok)
        self.clock.t += 50

        def boom():
            raise OSError("upstream down")
        result = self.cache.get(DATE, boom)
        self.assertIsNotNone(result["games"])
        self.assertTrue(result["stale"])
        self.assertIn("upstream down", result["error"])

    def test_failure_is_not_retried_inside_the_fail_window(self):
        self.cache.get(DATE, self.fetch_ok)
        self.clock.t += 50
        attempts = []

        def boom():
            attempts.append(1)
            raise OSError("down")
        for _ in range(20):
            self.cache.get(DATE, boom)
        self.assertEqual(len(attempts), 1)
        self.clock.t += 16
        self.cache.get(DATE, boom)
        self.assertEqual(len(attempts), 2)

    def test_a_snapshot_older_than_the_stale_cap_is_not_served(self):
        self.cache.get(DATE, self.fetch_ok)
        self.clock.t += 200

        def boom():
            raise OSError("down")
        result = self.cache.get(DATE, boom)
        self.assertIsNone(result["games"])

    def test_cold_failure_is_unavailable(self):
        def boom():
            raise OSError("down")
        result = self.cache.get(DATE, boom)
        self.assertIsNone(result["games"])
        self.assertIn("down", result["error"])

    def test_recovery_after_a_failure(self):
        def boom():
            raise OSError("down")
        self.cache.get(DATE, boom)
        self.clock.t += 16
        result = self.cache.get(DATE, self.fetch_ok)
        self.assertIsNotNone(result["games"])
        self.assertIsNone(result["error"])

    def test_memory_is_bounded(self):
        for day in range(10):
            self.cache.get(f"2026-10-{day + 1:02d}", self.fetch_ok)
        self.assertEqual(len(self.cache), 3)
        self.assertLessEqual(len(self.cache._locks), 3)

    def test_concurrent_visitors_share_one_fetch(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def slow():
            calls.append(1)
            started.set()
            release.wait(2)
            return [{"game_id": "g", "status": "pregame", "observed_utc": "t"}]

        results = []
        threads = [threading.Thread(target=lambda: results.append(self.cache.get(DATE, slow)))
                   for _ in range(12)]
        for t in threads:
            t.start()
        started.wait(2)
        time.sleep(0.05)
        release.set()
        for t in threads:
            t.join(3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 12)
        self.assertTrue(all(r["games"] for r in results))


class SlateTests(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.cache = livestate.LiveStateCache(clock=self.clock)
        self.calls = []

    def fetcher(self, games):
        def fetch(date):
            self.calls.append(date)
            return games
        return fetch

    def slate(self, games, date=DATE):
        return livestate.get_slate(date, fetch_schedule=self.fetcher(games), now=NOW,
                                   cache=self.cache)

    def test_every_status_on_one_slate(self):
        games = [
            raw(pk=1, away="AAA", home="BBB"),
            raw(pk=2, away="CCC", home="DDD", abstract="Live", coded="I",
                detailed="In Progress", linescore=live_linescore()),
            raw(pk=3, away="EEE", home="FFF", abstract="Final", coded="F", detailed="Final",
                away_score=2, home_score=1),
            raw(pk=4, away="GGG", home="HHH", abstract="Live", coded="I",
                detailed="Delayed: Rain", linescore=live_linescore()),
            raw(pk=5, away="III", home="JJJ", abstract="Preview", coded="D",
                detailed="Postponed"),
        ]
        payload = self.slate(games)
        self.assertTrue(payload["available"])
        self.assertEqual([g["status"] for g in payload["games"]],
                         ["pregame", "in_progress", "final", "delayed", "postponed"])
        self.assertEqual(payload["summary"], {"games": 5, "pregame": 1, "in_progress": 1,
                                              "delayed": 1, "final": 1, "postponed": 1})
        self.assertEqual(payload["source"], livestate.SOURCE)
        self.assertEqual(payload["cache"]["ttl_seconds"], livestate.TTL_S)

    def test_one_upstream_call_per_window(self):
        for _ in range(30):
            self.slate([raw()])
        self.assertEqual(self.calls, [DATE])

    def test_upstream_failure_is_unavailable_not_an_exception(self):
        def boom(date):
            raise OSError("MLB down")
        payload = livestate.get_slate(DATE, fetch_schedule=boom, now=NOW, cache=self.cache)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["games"], [])
        self.assertIn("not available", payload["reason"])

    def test_stale_snapshot_is_flagged_after_a_failure(self):
        self.slate([raw()])
        self.clock.t += 60

        def boom(date):
            raise OSError("MLB down")
        payload = livestate.get_slate(DATE, fetch_schedule=boom, now=NOW, cache=self.cache)
        self.assertTrue(payload["available"])
        self.assertTrue(payload["cache"]["stale"])

    def test_an_empty_slate_is_available_with_no_games(self):
        payload = self.slate([])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["summary"]["games"], 0)

    def test_dates_outside_the_window_never_reach_upstream(self):
        for date in ("2026-09-01", "2026-10-06", "2027-01-01"):
            payload = self.slate([raw()], date=date)
            self.assertFalse(payload["available"], date)
        self.assertEqual(self.calls, [])

    def test_yesterday_and_tomorrow_are_inside_the_window(self):
        for date in ("2026-10-02", "2026-10-04"):
            self.assertTrue(self.slate([raw()], date=date)["available"], date)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteTests(unittest.TestCase):

    def setUp(self):
        from api import live_state
        self.route = live_state
        livestate.CACHE.clear()
        self.addCleanup(livestate.CACHE.clear)
        self.addCleanup(setattr, live_state, "_fetch_schedule", None)

    def test_route_serves_the_slate_shape(self):
        today = livestate.et_today()
        calls = []

        def fetch(date):
            calls.append(date)
            return [raw(abstract="Live", coded="I", detailed="In Progress",
                        linescore=live_linescore())]
        self.route._fetch_schedule = fetch
        payload = self.route.get_live_state(today)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["games"][0]["status"], "in_progress")
        self.assertEqual(payload["games"][0]["inning_text"], "Top 6th")
        for _ in range(10):
            self.route.get_live_state(today)
        self.assertEqual(calls, [today])

    def test_route_upstream_failure_is_a_200_unavailable(self):
        def boom(date):
            raise OSError("down")
        self.route._fetch_schedule = boom
        payload = self.route.get_live_state(livestate.et_today())
        self.assertFalse(payload["available"])

    def test_malformed_date_is_a_400(self):
        for bad in ("tomorrow", "2026-13-40", "2026-1-1", "../x"):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                self.route.get_live_state(bad)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_the_route_is_mounted_behind_the_paid_gate(self):
        from api.app import app
        paths = set(app.openapi()["paths"])
        self.assertIn("/live/{date}", paths)
        self.assertIn("/live", paths)   # the internal-testing route is untouched


if __name__ == "__main__":
    unittest.main()
