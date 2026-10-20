"""ESPN-fed data service: parsers, append-only store, pipeline, read API and CLI.

Recorded fixtures only (tests/fixtures/datasvc_espn, trimmed real ESPN payloads); a fake opener stands in
for the network and every store and cache lives in a temp directory.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import date, datetime
from pathlib import Path

from src.datasvc import client as core
from src.datasvc.espn import cli as espn_cli, leagues, parse, pipeline, service
from src.datasvc.espn.store import EspnStore
from src.datasvc.http import PoliteFetcher

FIX = Path(__file__).parent / "fixtures" / "datasvc_espn"
NOW = datetime(2026, 1, 20, 12, 0, 0)
NOW_ISO = "2026-01-20T12:00:00Z"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class _Resp:
    status = 200
    headers = {"content-type": "application/json"}

    def __init__(self, body):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """An opener: routes are (url substring, payload | callable | raw bytes); first match wins; else 404."""

    def __init__(self, routes):
        self.routes = list(routes)
        self.urls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        for needle, payload in self.routes:
            if needle in url:
                p = payload() if callable(payload) else payload
                body = p if isinstance(p, bytes) else json.dumps(p).encode("utf-8")
                return _Resp(body)
        raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))


def fetcher(net, cache, iso=NOW_ISO, **kw):
    return PoliteFetcher(cache_dir=cache, opener=net, sleep=lambda s: None, delay_s=0, now_iso=lambda: iso, **kw)


def nba_teams():
    """The 3-team fixture plus Orlando (19) and Memphis (29), the clubs in the fixture game."""
    t = fx("nba_teams.json")
    lst = t["sports"][0]["leagues"][0]["teams"]
    for tid, ab, loc, name in (("19", "ORL", "Orlando", "Magic"), ("29", "MEM", "Memphis", "Grizzlies")):
        lst.append({"team": {"id": tid, "abbreviation": ab, "location": loc, "name": name,
                             "displayName": f"{loc} {name}", "shortDisplayName": name, "isActive": True}})
    return t


def nba_routes(injuries=None):
    sb = fx("nba_scoreboard.json")
    first = sb["events"][0]["id"]
    return [("scoreboard?dates=20260115", sb), ("scoreboard?", {"events": []}),
            (f"summary?event={first}", fx("nba_summary.json")),
            ("/teams?limit", nba_teams()), ("/standings", fx("nba_standings.json")),
            ("/injuries", injuries or fx("nba_injuries.json")),
            ("/roster", fx("nba_roster.json"))]


class ParseTests(unittest.TestCase):
    def test_games_scores_and_state(self):
        rows = parse.games(fx("nba_scoreboard.json"), "nba", "T", "2026-01-15")
        g = rows[0]
        self.assertEqual((g["game_id"], g["state"], g["completed"], g["season"]), ("401810433", "post", True, 2026))
        self.assertEqual((g["home_abbr"], g["home_score"], g["away_score"], g["home_winner"]), ("ORL", 118, 111, True))
        self.assertEqual(g["scoreboard_date"], "2026-01-15")
        self.assertEqual(g["date_utc"], "2026-01-15T19:00:00Z")
        self.assertIsInstance(g["home_score"], int)

    def test_pregame_has_no_score(self):
        sb = fx("nba_scoreboard.json")
        c = sb["events"][0]["competitions"][0]
        c["status"]["type"].update(state="pre", completed=False, name="STATUS_SCHEDULED")
        for x in c["competitors"]:
            x["score"] = "0"
            x.pop("winner", None)
        g = parse.games(sb, "nba", "T")[0]
        self.assertEqual(g["state"], "pre")
        self.assertNotIn("home_score", g)
        self.assertNotIn("home_winner", g)

    def test_placeholder_side_is_skipped(self):
        sb = fx("nba_scoreboard.json")
        sb["events"][0]["competitions"][0]["competitors"] = sb["events"][0]["competitions"][0]["competitors"][:1]
        self.assertEqual([r["game_id"] for r in parse.games(sb, "nba", "T")], ["401810434"])

    def test_null_odds_entry_does_not_crash(self):
        sb = fx("nba_scoreboard.json")
        sb["events"][0]["competitions"][0]["odds"] = [None, {"provider": {"name": "X"}, "details": "A -3", "overUnder": 200}]
        g = parse.games(sb, "nba", "T")[0]
        self.assertEqual(g["espn_odds"], [{"provider": "X", "details": "A -3", "over_under": 200}])

    def test_team_games_keep_display_strings(self):
        g = parse.games(fx("nba_scoreboard.json"), "nba", "T")[0]
        tg = parse.team_games(fx("nba_summary.json"), g, "T")
        by = {r["home_away"]: r for r in tg}
        self.assertEqual(by["home"]["team_id"], g["home_id"])
        self.assertEqual((by["home"]["points"], by["home"]["points_against"]), (118, 111))
        self.assertEqual(by["away"]["opponent_id"], g["home_id"])
        self.assertEqual(by["away"]["stats"]["fieldGoalsMade-fieldGoalsAttempted"], "38-83")

    def test_nba_players(self):
        g = parse.games(fx("nba_scoreboard.json"), "nba", "T")[0]
        pg = parse.player_games(fx("nba_summary.json"), g, "T")
        jj = next(r for r in pg if r["player_id"] == "4277961")
        self.assertEqual(jj["stats"]["all"]["points"], "30")
        self.assertTrue(jj["starter"])
        self.assertEqual(jj["team_id"], "29")

    def test_hockey_groups_and_football_groups(self):
        hg = parse.games(fx("nhl_scoreboard.json"), "nhl", "T")[0]
        groups = {k for r in parse.player_games(fx("nhl_summary.json"), hg, "T") for k in r["stats"]}
        self.assertEqual(groups, {"forwards", "defenses"})
        cg = parse.games(fx("ncaaf_scoreboard.json"), "ncaaf", "T")[0]
        groups = {k for r in parse.player_games(fx("ncaaf_summary.json"), cg, "T") for k in r["stats"]}
        self.assertTrue({"passing", "rushing", "receiving"} <= groups)

    def test_soccer_players_come_from_rosters(self):
        eg = parse.games(fx("epl_scoreboard.json"), "epl", "T")[0]
        self.assertEqual(eg["season"], 2025)
        pg = parse.player_games(fx("epl_summary.json"), eg, "T")
        self.assertTrue(pg)
        self.assertIn("appearances", pg[0]["stats"]["all"])
        tg = parse.team_games(fx("epl_summary.json"), eg, "T")
        self.assertIn("yellowCards", tg[0]["stats"])

    def test_standings_groups_nested(self):
        rows = parse.standings(fx("ncaaf_standings.json"), "ncaaf", "T")
        self.assertEqual({r["group"] for r in rows}, {"Atlantic Coast Conference", "American Conference"})
        self.assertEqual(rows[0]["season"], 2026)
        nba = parse.standings(fx("nba_standings.json"), "nba", "T")
        self.assertEqual({r["group"] for r in nba}, {"Eastern Conference", "Western Conference"})

    def test_injury_player_id_from_link(self):
        rows = parse.injuries(fx("nba_injuries.json"), "nba", "T")
        self.assertEqual(rows[0]["player_id"], "4712863")
        self.assertEqual((rows[0]["team_id"], rows[0]["status"]), ("1", "Out"))

    def test_rosters_flat_and_grouped(self):
        self.assertEqual(len(parse.roster(fx("nba_roster.json"), "nba", "1", "T")), 3)
        nhl = parse.roster(fx("nhl_roster.json"), "nhl", "25", "T")
        self.assertEqual(nhl[0]["name"], "Leo Carlsson")

    def test_norm_ts(self):
        self.assertEqual(parse.norm_ts("2026-01-15T19:00Z"), "2026-01-15T19:00:00Z")
        self.assertIsNone(parse.norm_ts("tomorrow"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = EspnStore(Path(self.tmp.name) / "espn")

    def rows(self, observed, score=100):
        return [{"league": "nba", "game_id": "1", "season": 2026, "observed_utc": observed, "state": "post",
                 "home_score": score}]

    def test_unchanged_writes_nothing(self):
        self.assertEqual(self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z"))["added"], 1)
        path = self.store.path("nba", "games", 2026)
        before = path.read_bytes()
        c = self.store.append("nba", "games", self.rows("2026-01-02T00:00:00Z"))
        self.assertEqual((c["added"], c["versioned"], c["unchanged"]), (0, 0, 1))
        self.assertEqual(path.read_bytes(), before)

    def test_change_appends_a_version_and_old_row_survives(self):
        self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z", 100))
        c = self.store.append("nba", "games", self.rows("2026-01-02T00:00:00Z", 101))
        self.assertEqual(c["versioned"], 1)
        self.assertEqual(len(self.store.versions("nba", "games", 2026)), 2)
        self.assertEqual(self.store.latest("nba", "games", 2026)[("1",)]["home_score"], 101)

    def test_as_of_reads_what_was_known(self):
        self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z", 100))
        self.store.append("nba", "games", self.rows("2026-01-02T00:00:00Z", 101))
        old = self.store.latest("nba", "games", 2026, as_of="2026-01-01T12:00:00Z")
        self.assertEqual(old[("1",)]["home_score"], 100)
        self.assertEqual(self.store.latest("nba", "games", 2026, as_of="2025-12-31T00:00:00Z"), {})

    def test_same_second_different_content_is_not_a_duplicate_key_crash(self):
        self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z", 100))
        c = self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z", 102))
        self.assertEqual(c["unchanged"], 1)
        self.assertEqual(len(self.store.versions("nba", "games", 2026)), 1)

    def test_season_partition_files(self):
        self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z"))
        other = self.rows("2026-01-01T00:00:00Z")
        other[0].update(game_id="2", season=2025)
        self.store.append("nba", "games", other)
        self.assertEqual(self.store.seasons("nba", "games"), ["2025", "2026"])

    def test_manifest_matches_files(self):
        self.store.append("nba", "games", self.rows("2026-01-01T00:00:00Z"))
        m = self.store.write_manifest("nba", extra={"refreshed_utc": "X"})
        self.assertEqual(m["files"]["games_2026.jsonl"]["records"], 1)
        self.assertEqual(self.store.read_manifest("nba")["refreshed_utc"], "X")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EspnStore(self.root / "espn")
        self.cache = self.root / "raw"

    def run_refresh(self, net, **kw):
        kw.setdefault("today", date(2026, 1, 15))
        kw.setdefault("days_back", 0)
        kw.setdefault("days_ahead", 0)
        return pipeline.refresh("nba", store=self.store, fetcher=fetcher(net, self.cache), now=lambda: NOW, **kw)

    def test_refresh_fills_every_dataset(self):
        net = FakeNet(nba_routes())
        s = self.run_refresh(net, rosters=True)
        self.assertEqual((s["games"], s["box_scores"], s["team_games"]), (2, 1, 2))
        self.assertEqual(s["player_games"], 8)
        self.assertEqual((s["teams"], s["standings"], s["injuries"]), (5, 6, 3))
        self.assertGreater(s["players"], 0)
        self.assertIsNone(s["stopped"])
        self.assertEqual(self.store.read_manifest("nba")["refreshed_utc"], s["finished_utc"])
        self.assertTrue(pipeline.check(self.store, ["nba"])["ok"])

    def test_second_run_is_free_and_changes_nothing(self):
        self.run_refresh(FakeNet(nba_routes()))
        files = {p.name: p.read_bytes() for p in (self.store.league_dir("nba")).glob("*.jsonl")}
        net2 = FakeNet(nba_routes())
        s = self.run_refresh(net2)
        self.assertEqual(s["games"] + s["team_games"] + s["player_games"] + s["standings"] + s["injuries"], 0)
        # historical scoreboard and box score came from the cache; only a "live" refetch is allowed to hit the net
        self.assertFalse([u for u in net2.urls if "summary" in u or "dates=20260115" in u])
        self.assertEqual(files, {p.name: p.read_bytes() for p in self.store.league_dir("nba").glob("*.jsonl")})

    def test_min_age_gate_skips_network(self):
        self.run_refresh(FakeNet(nba_routes()))
        net = FakeNet(nba_routes())
        # the manifest says refreshed at the real clock time, so pin "now" to just after it
        manifest = self.store.read_manifest("nba")
        stamp = datetime.strptime(manifest["refreshed_utc"], "%Y-%m-%dT%H:%M:%SZ")
        s = pipeline.refresh("nba", store=self.store, fetcher=fetcher(net, self.cache), now=lambda: stamp,
                             min_age_minutes=180, today=date(2026, 1, 15))
        self.assertIsNotNone(s["skipped"])
        self.assertEqual(net.urls, [])

    def test_injury_leaving_the_report_becomes_cleared(self):
        self.run_refresh(FakeNet(nba_routes()))
        shorter = copy.deepcopy(fx("nba_injuries.json"))
        gone = shorter["injuries"][0]["injuries"].pop(0)
        cache2 = self.root / "raw2"
        pipeline.refresh("nba", store=self.store, fetcher=fetcher(FakeNet(nba_routes(shorter)), cache2, iso="2026-01-21T00:00:00Z"),
                         today=date(2026, 1, 15), days_back=0, days_ahead=0, now=lambda: NOW)
        latest = self.store.latest("nba", "injuries")
        pid = parse.athlete_id(gone["athlete"])
        row = latest[(shorter["injuries"][0]["id"], pid)]
        self.assertEqual(row["status"], "Cleared")
        self.assertEqual(len(self.store.versions("nba", "injuries")), 4)   # 3 original + the tombstone

    def test_empty_injury_feed_does_not_clear_everyone(self):
        self.run_refresh(FakeNet(nba_routes()))
        pipeline.refresh("nba", store=self.store, fetcher=fetcher(FakeNet(nba_routes({"injuries": []})), self.root / "r3", iso="2026-01-21T00:00:00Z"),
                         today=date(2026, 1, 15), days_back=0, days_ahead=0, now=lambda: NOW)
        self.assertEqual(len(self.store.versions("nba", "injuries")), 3)

    def test_browser_check_stops_the_run_and_stores_nothing(self):
        net = FakeNet([("scoreboard", b"<html>Just a moment... checking your browser</html>")])
        s = self.run_refresh(net)
        self.assertTrue(s["stopped"].startswith("source blocked"))
        self.assertEqual(self.store.versions("nba", "games"), [])

    def test_request_cap_stops_cleanly(self):
        net = FakeNet(nba_routes())
        s = pipeline.refresh("nba", store=self.store, fetcher=fetcher(net, self.cache, max_requests=2),
                             today=date(2026, 1, 15), days_back=0, days_ahead=0, now=lambda: NOW)
        self.assertTrue(s["stopped"].startswith("request cap"))
        self.assertLessEqual(len(net.urls), 2)

    def test_failed_summary_is_skipped_not_fatal(self):
        routes = [(n, p) for n, p in nba_routes() if not n.startswith("summary")]
        s = self.run_refresh(FakeNet(routes))
        self.assertEqual((s["games"], s["box_scores"]), (2, 0))
        self.assertIsNone(s["stopped"])

    def test_live_scoreboard_cached_during_play_is_refetched_after(self):
        # fetched while "live" (before settle), then re-run after the day is over: must hit the network again
        net = FakeNet(nba_routes())
        early = datetime(2026, 1, 15, 22, 0, 0)
        f1 = PoliteFetcher(cache_dir=self.cache, opener=net, sleep=lambda s: None, delay_s=0,
                           now_iso=lambda: "2026-01-15T22:00:00Z")
        pipeline.refresh("nba", store=self.store, fetcher=f1, today=date(2026, 1, 15), days_back=0, days_ahead=0,
                         now=lambda: early)
        n_before = len([u for u in net.urls if "dates=20260115" in u])
        pipeline.refresh("nba", store=self.store, fetcher=fetcher(net, self.cache), today=date(2026, 1, 15),
                         days_back=0, days_ahead=0, now=lambda: NOW)
        self.assertEqual(len([u for u in net.urls if "dates=20260115" in u]), n_before + 1)

    def test_backfill_walks_days_and_college_skips_players(self):
        cf = fx("ncaaf_scoreboard.json")
        gid = cf["events"][0]["id"]
        net = FakeNet([("scoreboard?dates=20251115", cf), ("scoreboard?", {"events": []}),
                       (f"summary?event={gid}", fx("ncaaf_summary.json")), ("/teams?limit", nba_teams())])
        s = pipeline.backfill("ncaaf", date(2025, 11, 14), date(2025, 11, 16), store=self.store,
                              fetcher=fetcher(net, self.cache), now=lambda: NOW)
        self.assertEqual((s["scoreboards"], s["games"], s["box_scores"], s["player_games"]), (3, 1, 1, 0))
        self.assertEqual(self.store.versions("ncaaf", "player_games"), [])
        self.assertIn("&groups=80", [u for u in net.urls if "dates=20251115" in u][0])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EspnStore(self.root / "espn")
        pipeline.refresh("nba", store=self.store, fetcher=fetcher(FakeNet(nba_routes()), self.root / "raw"),
                         today=date(2026, 1, 15), days_back=0, days_ahead=0, rosters=True, now=lambda: NOW)
        self.svc = service.EspnService(self.store, clock=lambda: NOW_ISO)

    def test_schedule_by_date_and_team(self):
        out = self.svc.schedule("nba", date="2026-01-15")
        self.assertTrue(out["available"])
        self.assertEqual(len(out["data"]), 2)
        self.assertEqual(len(self.svc.schedule("nba", date="2026-01-15", team="ORL")["data"]), 1)
        self.assertEqual(self.svc.schedule("nba", date="2026-01-14")["data"], [])

    def test_game_has_box_score_and_missing_is_explicit(self):
        gid = fx("nba_scoreboard.json")["events"][0]["id"]
        out = self.svc.game("nba", gid)
        self.assertEqual(len(out["data"]["team_games"]), 2)
        self.assertEqual(len(out["data"]["player_games"]), 8)
        other = self.svc.game("nba", fx("nba_scoreboard.json")["events"][1]["id"])
        self.assertEqual(other["meta"]["missing"][0]["item"], "team_games")
        self.assertFalse(self.svc.game("nba", "nope")["available"])

    def test_as_of_before_first_observation_has_no_game(self):
        out = self.svc.schedule("nba", date="2026-01-15", as_of="2026-01-01T00:00:00Z")
        self.assertEqual(out["data"], [])
        self.assertFalse(self.svc.game("nba", "401810433", as_of="2026-01-01T00:00:00Z")["available"])

    def test_team_resolution_ambiguity_and_unknown(self):
        self.assertTrue(self.svc.team_history("nba", "Orlando Magic")["available"])
        bad = self.svc.schedule("nba", team="Zzyzx")
        self.assertFalse(bad["available"])
        self.assertIn("Zzyzx", bad["missing"][0]["reason"])

    def test_histories(self):
        th = self.svc.team_history("nba", "19")
        self.assertEqual(th["data"][0]["points"], 118)
        ph = self.svc.player_history("nba", "4277961")
        self.assertEqual(ph["data"][0]["stats"]["all"]["points"], "30")
        self.assertFalse(self.svc.player_history("nba", "1")["available"])

    def test_standings_injuries_players(self):
        self.assertEqual(len(self.svc.standings("nba")["data"]), 6)
        inj = self.svc.injuries("nba", team="ATL")
        self.assertEqual(len(inj["data"]), 2)
        self.assertEqual(self.svc.players("nba", team="ATL", search="Alexander")["data"][0]["player_id"], "4278039")

    def test_unavailable_shapes_for_unstored_features(self):
        self.assertFalse(self.svc.schedule("nhl")["available"])
        self.assertFalse(self.svc.injuries("ncaab")["available"])
        self.assertFalse(self.svc.players("ncaab")["available"])
        self.assertFalse(self.svc.capabilities("ncaab")["player_history"]["available"])

    def test_dataclient_league_view(self):
        client = core.DataClient()
        client._espn = self.svc
        view = client.league("nba")
        self.assertEqual(len(view.schedule(date="2026-01-15")["data"]), 2)
        with self.assertRaises(KeyError):
            client.league("cricket")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        pipeline.refresh("nba", store=EspnStore(self.root / "espn"),
                         fetcher=fetcher(FakeNet(nba_routes()), self.root / "raw"),
                         today=date(2026, 1, 15), days_back=0, days_ahead=0, now=lambda: NOW)

    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = espn_cli.run(list(argv) + ["--root", str(self.root / "espn")])
        return code, buf.getvalue()

    def test_schedule_command(self):
        code, out = self.call("nba", "schedule", "--date", "2026-01-15")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["data"]), 2)

    def test_box_needs_game_id_and_unknown_league(self):
        self.assertEqual(self.call("nba", "box")[0], 2)
        self.assertEqual(self.call("cricket", "status")[0], 2)

    def test_status_and_check(self):
        code, out = self.call("all", "status")
        self.assertIn("nba", json.loads(out))
        self.assertEqual(self.call("nba", "check")[0], 0)

    def test_src_cli_forwards(self):
        from src import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["datasvc", "nba", "standings", "--root", str(self.root / "espn")])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["kind"], "standings")

    def test_registry_is_consistent(self):
        for code, L in leagues.LEAGUES.items():
            self.assertEqual(code, L.code)
            self.assertIn(L.family, ("basketball", "hockey", "football", "soccer"))
        self.assertTrue(set(leagues.DEFAULT_REFRESH) <= set(leagues.LEAGUES))


if __name__ == "__main__":
    unittest.main()
