"""MLB statsapi box scores and player lines: parsers, store, forward-only pipeline, read API, and the SEALED WINDOW.

2026-01-01..2026-08-27 MLB outcomes are never read. Every door has a test here: the fetch (URL guard), the parse,
the store (write and read), the pipeline's day loop, the read API, and the rule that cumulative season fields are
not stored. Fixtures are trimmed real payloads of the 2026-10-19 ALCS game; a fake opener stands in for the
network and fails loudly if a sealed URL is ever requested.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from src.datasvc import client as core
from src.datasvc.http import PoliteFetcher
from src.datasvc.mlb import box_cli, box_service, seal, statsapi
from tests.test_datasvc_espn import FIX, FakeNet, fetcher

NOW = datetime(2026, 10, 22, 12, 0, 0)
NOW_ISO = "2026-10-22T12:00:00Z"
GAME = "849815"
DAY = date(2026, 10, 19)
T = "2026-10-22T12:00:00Z"


def fxm(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def routes(schedule=None, box=None):
    return [("schedule?date=2026-10-19", schedule or fxm("mlb_schedule.json")),
            ("schedule?", {"dates": []}),
            (f"game/{GAME}/boxscore", box or fxm("mlb_boxscore.json")),
            ("teams?sportId=1", fxm("mlb_teams.json"))]


class SealTests(unittest.TestCase):
    def test_window_edges(self):
        self.assertFalse(seal.is_sealed("2025-12-31"))
        self.assertTrue(seal.is_sealed("2026-01-01"))
        self.assertTrue(seal.is_sealed("2026-08-27"))
        self.assertTrue(seal.is_sealed("2026-08-27T23:59:59Z"))
        self.assertFalse(seal.is_sealed("2026-08-28"))
        self.assertFalse(seal.is_sealed(None))
        self.assertTrue(seal.is_sealed(date(2026, 3, 1)))
        self.assertTrue(seal.is_sealed(datetime(2026, 3, 1, 12)))
        self.assertTrue(seal.overlaps_sealed("2026-08-20", "2026-09-05"))
        self.assertFalse(seal.overlaps_sealed("2026-08-28", "2026-09-05"))
        self.assertTrue(seal.overlaps_sealed("2025-06-01", "2026-01-02"))

    def test_forward_floor_is_after_the_window(self):
        self.assertGreater(seal.FORWARD_FROM, seal.SEALED_LAST)

    def test_assert_open_names_the_window(self):
        with self.assertRaises(seal.SealedWindowError) as ctx:
            seal.assert_open("2026-05-01", "game 1")
        self.assertIn("sealed", str(ctx.exception))
        seal.assert_open("2026-10-20")

    def test_drop_sealed(self):
        rows = [{"date": "2026-05-01"}, {"date": "2026-10-19"}, {"date_utc": "2026-08-27T01:00:00Z"}, {"x": 1}]
        self.assertEqual(seal.drop_sealed(rows), [{"date": "2026-10-19"}, {"x": 1}])

    def test_url_guard_allows_only_open_days_listed_games_and_teams(self):
        listed = {"849815"}
        seal.check_url("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-20&hydrate=linescore", listed)
        seal.check_url("https://statsapi.mlb.com/api/v1/game/849815/boxscore", listed)
        seal.check_url("https://statsapi.mlb.com/api/v1/teams?sportId=1", listed)

    def test_url_guard_refuses_sealed_days_ranges_and_season_wide_requests(self):
        listed = {"849815"}
        bad = [
            ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-06-01", seal.SealedWindowError),
            ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-08-27", seal.SealedWindowError),
            ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=2026-08-01&endDate=2026-09-15", seal.SealedWindowError),
            ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=2026-09-01&endDate=2026-09-15", seal.UnsupportedUrl),
            ("https://statsapi.mlb.com/api/v1/people/660271/stats?stats=gameLog&season=2026", seal.SealedWindowError),
            ("https://statsapi.mlb.com/api/v1/people/660271/stats?stats=gameLog&season=2025", seal.UnsupportedUrl),
            ("https://statsapi.mlb.com/api/v1/teams/147/stats?stats=season&season=2026", seal.SealedWindowError),
            ("https://statsapi.mlb.com/api/v1/game/111/boxscore", seal.UnsupportedUrl),              # never listed
            ("https://statsapi.mlb.com/api/v1/game/849815/feed/live", seal.UnsupportedUrl),
            ("https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026", seal.SealedWindowError),
            ("https://example.com/api/v1/schedule?date=2026-10-20", seal.UnsupportedUrl),
        ]
        for url, exc in bad:
            with self.assertRaises(exc, msg=url):
                seal.check_url(url, listed)

    def test_the_fetcher_refuses_before_the_network_is_touched(self):
        net = FakeNet([("statsapi", {})])
        guard = statsapi.SealedFetcher(PoliteFetcher(cache_dir=Path(tempfile.mkdtemp()), opener=net, sleep=lambda s: None, delay_s=0))
        for url in ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-04-01",
                    "https://statsapi.mlb.com/api/v1/people/1/stats?stats=gameLog&season=2026",
                    "https://statsapi.mlb.com/api/v1/game/1/boxscore"):
            with self.assertRaises((seal.SealedWindowError, seal.UnsupportedUrl)):
                guard.get_json(url)
            with self.assertRaises((seal.SealedWindowError, seal.UnsupportedUrl)):
                guard.get_text(url)
        self.assertEqual(net.urls, [])


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.games = statsapi.schedule(fxm("mlb_schedule.json"), T)
        self.game = self.games[0]
        self.box = fxm("mlb_boxscore.json")

    def test_schedule_row(self):
        self.assertEqual(len(self.games), 1)
        g = self.game
        self.assertEqual((g["game_id"], g["date"], g["state"], g["completed"]), (GAME, "2026-10-19", "post", True))
        self.assertEqual(g["scoreboard_date"], "2026-10-19")
        self.assertEqual((g["home_id"], g["away_id"], g["home_score"], g["away_score"]), ("139", "114", 7, 3))
        self.assertEqual((g["home_winner"], g["season"], g["season_type"], g["game_type"]), (True, 2026, 3, "L"))
        self.assertEqual(g["date_utc"], "2026-10-20T00:08:00Z")           # the UTC instant; `date` is the local day
        self.assertEqual(sum(x or 0 for x in g["home_line"]), 7)
        self.assertEqual(sum(x or 0 for x in g["away_line"]), 3)
        self.assertEqual((g["winning_pitcher_id"], g["losing_pitcher_id"]), ("642547", "542888"))
        self.assertEqual(g["description"], "ALCS Game 6")

    def test_schedule_keeps_no_cumulative_record(self):
        blob = json.dumps(self.games)
        for needle in ("leagueRecord", "wins", "losses", "pct", "record"):
            self.assertNotIn(needle, blob)

    def test_unstarted_game_has_no_score(self):
        pre = fxm("mlb_schedule.json")
        g = pre["dates"][0]["games"][0]
        g["status"].update(abstractGameState="Preview", codedGameState="S", detailedState="Scheduled")
        g.pop("linescore", None)
        g.pop("decisions", None)
        row = statsapi.schedule(pre, T)[0]
        self.assertEqual((row["state"], row["completed"]), ("pre", False))
        self.assertNotIn("home_score", row)
        self.assertNotIn("winning_pitcher_id", row)

    def test_a_sealed_game_in_a_payload_raises_instead_of_parsing(self):
        for field, value in (("officialDate", "2026-05-01"), ("gameDate", "2026-08-27T23:00:00Z")):
            payload = fxm("mlb_schedule.json")
            payload["dates"][0]["games"][0][field] = value
            with self.assertRaises(seal.SealedWindowError):
                statsapi.schedule(payload, T)
        payload = fxm("mlb_schedule.json")
        del payload["dates"][0]["games"][0]["officialDate"]
        payload["dates"][0]["date"] = "2026-07-04"
        with self.assertRaises(seal.SealedWindowError):
            statsapi.schedule(payload, T)

    def test_teams_keep_major_league_clubs_only(self):
        rows = statsapi.teams(fxm("mlb_teams.json"), T)
        self.assertEqual(sorted(r["abbreviation"] for r in rows), ["CLE", "NYY", "TB"])
        self.assertEqual(next(r for r in rows if r["abbreviation"] == "TB")["display_name"], "Tampa Bay Rays")

    def test_team_games_are_game_level_counting_stats(self):
        rows = statsapi.team_games(self.box, self.game, T)
        by = {r["home_away"]: r for r in rows}
        home = by["home"]
        self.assertEqual((home["team_id"], home["opponent_id"], home["points"], home["points_against"]), ("139", "114", 7, 3))
        self.assertEqual(home["stats"]["bat.runs"], 7)
        self.assertEqual(home["stats"]["bat.hits"], 7)
        self.assertEqual(home["stats"]["pit.earnedRuns"], 3)
        self.assertEqual(home["stats"]["pit.outs"], 27)                  # 9.0 innings
        self.assertEqual(by["away"]["points"], 3)
        for r in rows:
            for key, value in r["stats"].items():
                self.assertIsInstance(value, int, key)                   # no rate strings
                self.assertNotIn(key.split(".")[1], ("avg", "obp", "slg", "ops", "era", "whip", "stolenBasePercentage"))

    def test_player_lines_exclude_season_to_date_everything(self):
        rows = statsapi.player_games(self.box, self.game, T)
        blob = json.dumps(rows)
        self.assertNotIn("31337", blob)                                  # the marker only exists under seasonStats
        for needle in ("seasonStats", "(W,", "summary", "note", "era", "avg", "ops", "whip"):
            self.assertNotIn(f'"{needle}"', blob)
        self.assertTrue(rows)
        self.assertTrue(all(r["stats"] for r in rows))
        for r in rows:
            for group in r["stats"].values():
                self.assertTrue(all(isinstance(v, int) for v in group.values()))

    def test_pitchers_get_outs_from_innings_and_starters_are_flagged(self):
        rows = statsapi.player_games(self.box, self.game, T)
        starter = next(r for r in rows if r["player_id"] == "642547")      # Peralta, 5.1 IP, started
        self.assertEqual(starter["stats"]["pitching"]["outs"], 16)
        self.assertTrue(starter["starter"])
        self.assertEqual(starter["position"], "P")
        batters = [r for r in rows if "batting" in r["stats"] and r["batting_order"]]
        self.assertTrue(any(r["starter"] for r in batters))
        self.assertTrue(any(r["batting_order"].endswith("01") and not r["starter"] for r in batters))   # a substitute

    def test_empty_bench_player_has_no_row(self):
        rows = statsapi.player_games(self.box, self.game, T)
        ids = {r["player_id"] for r in rows}
        for side in ("home", "away"):
            for p in self.box["teams"][side]["players"].values():
                if not p["stats"]["batting"] and not p["stats"]["pitching"]:
                    self.assertNotIn(str(p["person"]["id"]), ids)

    def test_innings_to_outs(self):
        self.assertEqual(statsapi._outs("6.1"), 19)
        self.assertEqual(statsapi._outs("0.2"), 2)
        self.assertEqual(statsapi._outs("9.0"), 27)
        self.assertEqual(statsapi._outs("9"), 27)
        self.assertIsNone(statsapi._outs("x"))
        self.assertIsNone(statsapi._outs(None))


class StoreGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = statsapi.MlbBoxStore(Path(self.tmp.name) / "datasvc")

    def row(self, gid, day):
        return {"league": "mlb", "game_id": gid, "season": 2026, "observed_utc": T, "date": day, "state": "post",
                "completed": True, "home_id": "1", "away_id": "2"}

    def test_a_sealed_row_is_refused_and_nothing_is_written(self):
        for day in ("2026-01-01", "2026-04-15", "2026-08-27"):
            with self.assertRaises(seal.SealedWindowError):
                self.store.append("mlb", "games", [self.row("1", day)])
        with self.assertRaises(seal.SealedWindowError):
            self.store.append("mlb", "games", [dict(self.row("1", "2026-10-19"), date_utc="2026-05-01T00:00:00Z")])
        self.assertFalse(self.store.path("mlb", "games", 2026).exists())

    def test_open_rows_are_written(self):
        self.assertEqual(self.store.append("mlb", "games", [self.row("1", "2026-08-28"), self.row("2", "2026-10-19")])["added"], 2)

    def test_reads_drop_a_sealed_row_that_got_into_the_file_anyway(self):
        self.store.append("mlb", "games", [self.row("2", "2026-10-19")])
        path = self.store.path("mlb", "games", 2026)
        with path.open("a", encoding="utf-8") as handle:                  # a file edited behind the store's back
            handle.write(json.dumps(self.row("1", "2026-05-05")) + "\n")
        self.assertEqual([r["game_id"] for r in self.store.versions("mlb", "games", 2026)], ["2"])
        self.assertEqual([k[0] for k in self.store.latest("mlb", "games", 2026)], ["2"])
        report = statsapi.check(self.store)
        self.assertFalse(report["ok"])
        self.assertIn("sealed window", report["problems"][0])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = statsapi.MlbBoxStore(self.root / "datasvc")
        self.cache = self.root / "raw"

    def run_refresh(self, net, **kw):
        kw.setdefault("today", date(2026, 10, 20))
        kw.setdefault("days_back", 1)
        kw.setdefault("days_ahead", 0)
        kw.setdefault("floor", DAY)
        return statsapi.refresh(store=self.store, fetcher=fetcher(net, self.cache, iso=NOW_ISO), now=lambda: NOW, **kw)

    def test_refresh_fills_games_team_and_player_lines(self):
        net = FakeNet(routes())
        s = self.run_refresh(net)
        self.assertEqual((s["games"], s["box_scores"], s["team_games"], s["teams"]), (1, 1, 2, 3))
        self.assertGreater(s["player_games"], 4)
        self.assertIsNone(s["stopped"])
        self.assertEqual(s["skipped_sealed"], [])
        self.assertTrue(statsapi.check(self.store)["ok"])
        self.assertEqual(statsapi.status(self.store)["files"]["games_2026.jsonl"], 1)
        self.assertEqual(len([u for u in net.urls if "boxscore" in u]), 1)

    def test_second_run_is_free_and_changes_nothing(self):
        self.run_refresh(FakeNet(routes()))
        before = {p.name: p.read_bytes() for p in self.store.league_dir("mlb").glob("*.jsonl")}
        net = FakeNet(routes())
        s = self.run_refresh(net)
        self.assertEqual(s["games"] + s["team_games"] + s["player_games"], 0)
        self.assertFalse([u for u in net.urls if "boxscore" in u])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.store.league_dir("mlb").glob("*.jsonl")})

    def test_forward_floor_keeps_yesterday_out(self):
        net = FakeNet(routes())
        s = self.run_refresh(net, floor=seal.FORWARD_FROM)                # the shipped default
        self.assertEqual(s["skipped_before_floor"], ["2026-10-19"])
        self.assertFalse([u for u in net.urls if "2026-10-19" in u or "boxscore" in u])
        self.assertEqual(self.store.versions("mlb", "games"), [])

    def test_sealed_days_are_never_requested_even_with_the_floor_lowered_to_the_start_of_the_year(self):
        net = FakeNet(routes() + [("schedule?", {"dates": []})])
        s = self.run_refresh(net, today=date(2026, 8, 30), days_back=6, days_ahead=1, floor=date(2026, 1, 1))
        self.assertEqual(s["skipped_sealed"], ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"])
        requested = [u for u in net.urls if "schedule" in u]
        self.assertEqual(len(requested), 4)                               # 08-28, 08-29, 08-30, 08-31
        for sealed_day in ("2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"):
            self.assertFalse([u for u in net.urls if sealed_day in u], sealed_day)

    def test_a_long_look_back_into_the_window_requests_only_open_days(self):
        net = FakeNet(routes())
        self.run_refresh(net, today=date(2026, 10, 20), days_back=400, days_ahead=0, floor=date(2025, 1, 1))
        for u in net.urls:
            if "date=" in u:
                day = u.split("date=")[1][:10]
                self.assertFalse(seal.is_sealed(day), day)

    def test_a_response_for_a_sealed_game_stops_the_run_and_stores_nothing(self):
        wrong = fxm("mlb_schedule.json")
        wrong["dates"][0]["games"][0]["officialDate"] = "2026-05-01"
        s = self.run_refresh(FakeNet(routes(schedule=wrong)))
        self.assertTrue(s["stopped"].startswith("sealed window guard"))
        self.assertEqual(self.store.versions("mlb", "games"), [])
        self.assertEqual(self.store.versions("mlb", "team_games"), [])

    def test_browser_check_stops_the_run(self):
        net = FakeNet([("schedule", b"<html>Just a moment... checking your browser</html>"), ("teams", fxm("mlb_teams.json"))])
        s = self.run_refresh(net)
        self.assertTrue(s["stopped"].startswith("source blocked"))

    def test_request_cap_and_min_age_gate(self):
        net = FakeNet(routes())
        s = statsapi.refresh(store=self.store, fetcher=fetcher(net, self.cache, iso=NOW_ISO, max_requests=2),
                             today=date(2026, 10, 20), days_back=1, days_ahead=0, floor=DAY, now=lambda: NOW)
        self.assertTrue(s["stopped"].startswith("request cap"))
        self.run_refresh(FakeNet(routes()))
        net2 = FakeNet(routes())
        stamp = datetime.strptime(self.store.read_manifest("mlb")["refreshed_utc"], "%Y-%m-%dT%H:%M:%SZ")
        s = statsapi.refresh(store=self.store, fetcher=fetcher(net2, self.root / "raw2"), today=date(2026, 10, 20),
                             floor=DAY, now=lambda: stamp, min_age_minutes=180)
        self.assertIsNotNone(s["skipped"])
        self.assertEqual(net2.urls, [])

    def test_failed_box_score_is_skipped_not_fatal(self):
        r = [(n, p) for n, p in routes() if "boxscore" not in n]
        s = self.run_refresh(FakeNet(r))
        self.assertEqual((s["games"], s["box_scores"]), (1, 0))
        self.assertIsNone(s["stopped"])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = statsapi.MlbBoxStore(self.root / "datasvc")
        statsapi.refresh(store=self.store, fetcher=fetcher(FakeNet(routes()), self.root / "raw", iso=NOW_ISO),
                         today=date(2026, 10, 20), days_back=1, days_ahead=0, floor=DAY, now=lambda: NOW)
        self.svc = box_service.MlbBoxService(self.store, clock=lambda: NOW_ISO)

    def test_schedule_game_and_histories(self):
        out = self.svc.schedule("mlb", date="2026-10-19")
        self.assertEqual([g["game_id"] for g in out["data"]], [GAME])
        self.assertEqual(out["meta"]["sealed_window"], "2026-01-01..2026-08-27 outcomes are never read")
        game = self.svc.game("mlb", GAME)
        self.assertEqual(len(game["data"]["team_games"]), 2)
        self.assertGreater(len(game["data"]["player_games"]), 4)
        th = self.svc.team_history("mlb", "TB")
        self.assertEqual(th["data"][0]["points"], 7)
        ph = self.svc.player_history("mlb", "642547")
        self.assertEqual(ph["data"][0]["stats"]["pitching"]["outs"], 16)
        self.assertEqual(self.svc.team_history("mlb", "Rays")["data"][0]["game_id"], GAME)

    def test_averages_and_splits_reuse_the_shared_aggregation(self):
        d = self.svc.team_averages("mlb", "TB")["data"]
        self.assertEqual((d["games"], d["wins"], d["stats"]["bat.runs"]["avg"], d["allowed"]["bat.runs"]["avg"]), (1, 1, 7.0, 3.0))
        s = self.svc.team_splits("mlb", "TB", splits=("all", "home", "away"))["data"]
        self.assertEqual((s["home"]["games"], s["away"]["games"]), (1, 0))
        p = self.svc.player_averages("mlb", "642547")["data"]
        self.assertEqual(p["groups"]["pitching"]["stats"]["outs"]["total"], 16.0)
        self.assertEqual(p["starts"], 1)
        late = self.svc.team_averages("mlb", "TB", as_of="2026-10-20T08:00:00Z")      # kickoff 00:08Z + 5 h allowance = 05:08
        self.assertEqual(late["data"]["games"], 1)
        early = self.svc.team_averages("mlb", "TB", as_of="2026-10-20T02:00:00Z")      # may still be playing
        self.assertFalse(early["available"])

    def test_sealed_questions_are_refused_by_name(self):
        for out in (self.svc.schedule("mlb", date="2026-06-01"),
                    self.svc.schedule("mlb", as_of="2026-03-01T00:00:00Z"),
                    self.svc.game("mlb", GAME, as_of="2026-08-27T12:00:00Z"),
                    self.svc.team_history("mlb", "TB", before="2026-07-01"),
                    self.svc.player_history("mlb", "642547", as_of="2026-05-01T00:00:00Z"),
                    self.svc.team_averages("mlb", "TB", as_of="2026-03-01T00:00:00Z"),
                    self.svc.team_splits("mlb", "TB", as_of="2026-03-01T00:00:00Z"),
                    self.svc.player_averages("mlb", "642547", as_of="2026-03-01T00:00:00Z"),
                    self.svc.player_splits("mlb", "642547", as_of="2026-03-01T00:00:00Z")):
            self.assertFalse(out["available"])
            self.assertIn("sealed window", out["missing"][0]["reason"])

    def test_not_stored_features_are_explicit(self):
        for out in (self.svc.players("mlb"), self.svc.standings("mlb"), self.svc.injuries("mlb"), self.svc.play_by_play("mlb", "1")):
            self.assertFalse(out["available"])
        caps = self.svc.capabilities("mlb")
        self.assertTrue(caps["team_averages"]["available"])
        self.assertFalse(caps["standings"]["available"])

    def test_wrong_league_and_dataclient_view(self):
        with self.assertRaises(KeyError):
            self.svc.schedule("nba")
        client = core.DataClient()
        client._mlb_box = self.svc
        view = client.mlb_box()
        self.assertEqual(view.team_averages("TB")["data"]["games"], 1)
        self.assertEqual(view.schedule(date="2026-10-19")["data"][0]["game_id"], GAME)

    def test_cli_reads_and_refuses_sealed_dates(self):
        def call(*argv):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = box_cli.run(list(argv) + ["--root", str(self.store.root)])
            return code, buf.getvalue()

        code, out = call("schedule", "--date", "2026-10-19")
        self.assertEqual((code, len(json.loads(out)["data"])), (0, 1))
        self.assertEqual(call("schedule", "--date", "2026-06-01")[0], 2)
        self.assertEqual(call("averages", "--team", "TB", "--as-of", "2026-03-01T00:00:00Z")[0], 2)
        code, out = call("averages", "--players", "--team", "TB")
        self.assertEqual(code, 0)
        self.assertEqual(call("check")[0], 0)
        self.assertIn("games_2026.jsonl", json.loads(call("status")[1])["files"])
        self.assertEqual(call("box")[0], 2)
        self.assertEqual(call("splits")[0], 2)
        self.assertEqual(call("refresh", "--date", "not-a-date")[0], 2)


if __name__ == "__main__":
    unittest.main()
