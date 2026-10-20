"""Season averages / per-game splits (point in time) and play-by-play for the ESPN-fed leagues.

Synthetic stores in temp directories for the aggregation; trimmed real payloads (tests/fixtures/datasvc_espn)
and a fake opener for the play-by-play pipeline. Nothing touches the network or the real data directory.
"""

from __future__ import annotations

import contextlib
import copy
import gzip
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from src.datasvc import client as core
from src.datasvc.espn import aggregate as agg, cli as espn_cli, leagues, parse, pbp, pipeline, service
from src.datasvc.espn.store import EspnStore
from tests.test_datasvc_espn import FIX, FakeNet, NOW, NOW_ISO, fetcher, fx, nba_routes, nba_teams


def fxp(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# -- a small synthetic basketball league ---------------------------------------------------------------------------

def game(gid, day, home, away, hs, as_, *, season_type=2, state="post", observed="2026-01-20T00:00:00Z", **kw):
    row = {"league": "nba", "game_id": gid, "season": 2026, "season_type": season_type, "state": state,
           "completed": state == "post", "date_utc": f"{day}T00:00:00Z", "home_id": home, "away_id": away,
           "observed_utc": observed}
    if state == "post":
        row.update(home_score=hs, away_score=as_)
    row.update(kw)
    return row


def tg(gid, team, opp, side, pts, opp_pts, day, observed="2026-01-20T00:00:00Z", **stats):
    base = {"points": str(pts), "fg": f"{pts // 3}-{pts // 2}", "paint": str(pts // 4), "possession": "30:00"}
    base.update({k: str(v) for k, v in stats.items()})
    return {"league": "nba", "game_id": gid, "team_id": team, "season": 2026, "observed_utc": observed,
            "date_utc": f"{day}T00:00:00Z", "home_away": side, "opponent_id": opp, "points": pts,
            "points_against": opp_pts, "stats": base}


def pg(gid, player, team, day, pts, *, starter=True, observed="2026-01-20T00:00:00Z", dnp=False, **extra):
    row = {"league": "nba", "game_id": gid, "player_id": player, "team_id": team, "season": 2026,
           "observed_utc": observed, "date_utc": f"{day}T00:00:00Z", "player_name": f"P{player}", "starter": starter,
           "stats": {"all": {"points": str(pts), "minutes": "30"}}}
    row.update(extra)
    if dnp:
        row["did_not_play"] = True
    return row


GAMES = [
    game("g1", "2026-01-10", "1", "2", 100, 90),
    game("g2", "2026-01-12", "2", "1", 95, 105),
    game("g3", "2026-01-14", "1", "3", 110, 100),
    game("g4", "2026-01-16", "3", "1", 101, 99),
    game("g5", "2025-10-05", "1", "2", 130, 120, season_type=1),         # preseason
    game("g6", "2026-01-30", "1", "3", None, None, state="pre"),         # not played yet
]
TEAM_GAMES = [
    tg("g1", "1", "2", "home", 100, 90, "2026-01-10"), tg("g1", "2", "1", "away", 90, 100, "2026-01-10"),
    tg("g2", "2", "1", "home", 95, 105, "2026-01-12"), tg("g2", "1", "2", "away", 105, 95, "2026-01-12"),
    tg("g3", "1", "3", "home", 110, 100, "2026-01-14"), tg("g3", "3", "1", "away", 100, 110, "2026-01-14"),
    tg("g4", "3", "1", "home", 101, 99, "2026-01-16"), tg("g4", "1", "3", "away", 99, 101, "2026-01-16"),
    tg("g5", "1", "2", "home", 130, 120, "2025-10-05"), tg("g5", "2", "1", "away", 120, 130, "2025-10-05"),
]
PLAYER_GAMES = [
    pg("g1", "10", "1", "2026-01-10", 20), pg("g2", "10", "1", "2026-01-12", 30, starter=False),
    pg("g3", "10", "1", "2026-01-14", 10), pg("g4", "10", "1", "2026-01-16", 0, dnp=True),
    pg("g1", "20", "2", "2026-01-10", 12), pg("g5", "10", "1", "2025-10-05", 99),
]
TEAMS = [{"league": "nba", "team_id": t, "observed_utc": "2026-01-20T00:00:00Z", "abbreviation": a,
          "display_name": n, "name": n.split()[-1], "location": n.split()[0]}
         for t, a, n in (("1", "AAA", "Alpha Aces"), ("2", "BBB", "Bravo Bears"), ("3", "CCC", "Charlie Cats"))]


class StatsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = EspnStore(Path(self.tmp.name) / "espn")
        self.load(GAMES, TEAM_GAMES, PLAYER_GAMES)
        self.svc = service.EspnService(self.store, clock=lambda: NOW_ISO)

    def load(self, games, team_games, player_games, teams=TEAMS):
        self.store.append("nba", "teams", teams)
        self.store.append("nba", "games", games)
        self.store.append("nba", "team_games", team_games)
        self.store.append("nba", "player_games", player_games)


class ValueTests(unittest.TestCase):
    def test_parse_value_kinds(self):
        self.assertEqual(agg.parse_value("46"), ("num", 46.0))
        self.assertEqual(agg.parse_value("+6"), ("num", 6.0))
        self.assertEqual(agg.parse_value("-3"), ("num", -3.0))
        self.assertEqual(agg.parse_value("38-83"), ("ratio", 38, 83))
        self.assertEqual(agg.parse_value("11/19"), ("ratio", 11, 19))
        self.assertEqual(agg.parse_value("33:12"), ("clock", 33 * 60 + 12))
        self.assertEqual(agg.parse_value(7), ("num", 7.0))
        for junk in ("", None, "n/a", "--", True, "4-5-6"):
            self.assertIsNone(agg.parse_value(junk), junk)

    def test_summaries_weight_ratios_by_volume_and_average_clocks(self):
        out = agg.summarize_stats([{"fg": "10-20", "pos": "30:00", "pts": "100"},
                                   {"fg": "30-40", "pos": "32:00", "pts": "110"}, {"pts": "x"}])
        self.assertEqual(out["fg"]["pct"], 0.6667)                       # 40/60, not the mean of 50% and 75%
        self.assertEqual((out["fg"]["made_avg"], out["fg"]["att_avg"]), (20.0, 30.0))
        self.assertEqual((out["pos"]["avg"], out["pos"]["total_seconds"]), ("31:00", 3720))
        self.assertEqual((out["pts"]["games"], out["pts"]["avg"]), (2, 105.0))     # the junk game is not counted


class TeamAverageTests(StatsBase):
    def test_overall_record_and_averages_exclude_preseason_and_unplayed(self):
        out = self.svc.team_averages("nba", "AAA")
        d = out["data"]
        self.assertEqual((d["games"], d["wins"], d["losses"]), (4, 3, 1))
        self.assertEqual(d["points_for"]["avg"], (100 + 105 + 110 + 99) / 4)
        self.assertEqual(d["points_against"]["avg"], (90 + 95 + 100 + 101) / 4)
        self.assertEqual(d["margin_avg"], d["points_for"]["avg"] - d["points_against"]["avg"])
        self.assertEqual(d["stats"]["points"]["games"], 4)
        self.assertEqual(out["meta"]["games_used"], 4 + 0)               # g1..g4 only (g5 preseason, g6 not final)
        self.assertEqual(out["meta"]["game_basis"]["excluded_season_type"], 1)
        self.assertEqual(out["meta"]["game_basis"]["excluded_not_final"], 1)

    def test_allowed_is_what_the_opponent_did(self):
        d = self.svc.team_averages("nba", "AAA")["data"]
        self.assertEqual(d["allowed"]["points"]["avg"], (90 + 95 + 100 + 101) / 4)
        self.assertEqual(d["stats"]["points"]["avg"], d["points_for"]["avg"])

    def test_splits(self):
        s = self.svc.team_splits("nba", "AAA", splits=("all", "home", "away", "wins", "losses", "last2", "last10"))["data"]
        self.assertEqual((s["home"]["games"], s["away"]["games"]), (2, 2))
        self.assertEqual(s["home"]["points_for"]["avg"], 105.0)
        self.assertEqual((s["wins"]["games"], s["losses"]["games"]), (3, 1))
        self.assertEqual(s["last2"]["last_game_utc"], "2026-01-16T00:00:00Z")
        self.assertEqual(s["last2"]["first_game_utc"], "2026-01-14T00:00:00Z")      # the two newest, not the two oldest
        self.assertEqual(s["last10"]["games"], 4)
        self.assertEqual(s["last2"]["points_for"]["avg"], (110 + 99) / 2)

    def test_split_and_last_arguments(self):
        out = self.svc.team_averages("nba", "AAA", last=2)
        self.assertEqual((out["data"]["split"], out["data"]["games"]), ("last2", 2))
        self.assertFalse(self.svc.team_averages("nba", "AAA", split="home", last=2)["available"])
        bad = self.svc.team_averages("nba", "AAA", split="sideways")
        self.assertFalse(bad["available"])
        self.assertIn("sideways", bad["missing"][0]["reason"])

    def test_league_table_lists_every_team(self):
        out = self.svc.team_averages("nba")
        self.assertEqual([r["team_abbr"] for r in out["data"]], ["AAA", "BBB", "CCC"])
        self.assertEqual(sum(r["games"] for r in out["data"]), 8)       # 4 final regular games, two teams each

    def test_season_type_choices(self):
        self.assertEqual(self.svc.team_averages("nba", "AAA", season_type="all")["data"]["games"], 5)
        self.assertEqual(self.svc.team_averages("nba", "AAA", season_type="1")["data"]["games"], 1)
        self.assertFalse(self.svc.team_averages("nba", "AAA", season_type="playoffs")["available"])

    def test_unknown_team_and_empty_sample_are_explicit(self):
        self.assertFalse(self.svc.team_averages("nba", "ZZZ")["available"])
        self.assertFalse(self.svc.team_averages("nba", "AAA", season=1999)["available"])
        self.assertFalse(service.EspnService(EspnStore(Path(self.tmp.name) / "empty")).team_averages("nba")["available"])


class PointInTimeTests(StatsBase):
    """as_of uses only games that were final by then."""

    def test_backfilled_games_count_once_old_enough_to_have_finished(self):
        # observed 2026-01-20 (a backfill), asked about the 13th: g1 (10th) and g2 (12th) had finished, g3 had not started
        out = self.svc.team_averages("nba", "AAA", as_of="2026-01-13T12:00:00Z")
        self.assertEqual(out["data"]["games"], 2)
        self.assertEqual(out["data"]["points_for"]["avg"], (100 + 105) / 2)
        self.assertEqual(out["meta"]["game_basis"]["reconstructed"], 2)
        self.assertEqual(out["meta"]["game_basis"]["observed"], 0)

    def test_game_still_in_progress_is_not_used(self):
        # g2 kicks off 2026-01-12T00:00Z; 03:00 later it may still be on (NBA allowance is 3.5 h)
        out = self.svc.team_averages("nba", "AAA", as_of="2026-01-12T03:00:00Z")
        self.assertEqual(out["data"]["games"], 1)
        out = self.svc.team_averages("nba", "AAA", as_of="2026-01-12T03:29:59Z")
        self.assertEqual(out["data"]["games"], 1)
        out = self.svc.team_averages("nba", "AAA", as_of="2026-01-12T03:30:00Z")      # kickoff + the full allowance
        self.assertEqual(out["data"]["games"], 2)

    def test_strict_keeps_only_games_we_saw_final(self):
        self.assertFalse(self.svc.team_averages("nba", "AAA", as_of="2026-01-13T12:00:00Z", strict=True)["available"])
        out = self.svc.team_averages("nba", "AAA", as_of="2026-01-21T00:00:00Z", strict=True)
        self.assertEqual((out["data"]["games"], out["meta"]["game_basis"]["observed"]), (4, 4))

    def test_forward_captured_game_is_observed_not_reconstructed(self):
        self.load([game("g7", "2026-02-01", "1", "2", 120, 100, observed="2026-02-01T05:00:00Z")],
                  [tg("g7", "1", "2", "home", 120, 100, "2026-02-01", observed="2026-02-01T05:00:00Z"),
                   tg("g7", "2", "1", "away", 100, 120, "2026-02-01", observed="2026-02-01T05:00:00Z")], [])
        late = self.svc.team_averages("nba", "AAA", as_of="2026-02-01T06:00:00Z")      # seen final at 05:00
        self.assertEqual((late["data"]["games"], late["meta"]["game_basis"]["observed"],
                          late["meta"]["game_basis"]["reconstructed"]), (5, 5, 0))
        mid = self.svc.team_averages("nba", "AAA", as_of="2026-02-01T04:00:00Z")      # over by kickoff + 3.5 h, not yet seen
        self.assertEqual((mid["data"]["games"], mid["meta"]["game_basis"]["observed"],
                          mid["meta"]["game_basis"]["reconstructed"]), (5, 4, 1))
        soon = self.svc.team_averages("nba", "AAA", as_of="2026-02-01T01:00:00Z")      # kicked off an hour ago
        self.assertEqual(soon["data"]["games"], 4)                                    # g7 may still be on: not used
        self.assertEqual(soon["meta"]["game_basis"]["excluded_after_as_of"], 1)

    def test_box_score_corrections_are_read_as_of(self):
        fixed = [tg("g1", "1", "2", "home", 101, 90, "2026-01-10", observed="2026-01-25T00:00:00Z"),
                 tg("g1", "2", "1", "away", 90, 101, "2026-01-10", observed="2026-01-25T00:00:00Z")]
        self.load([], fixed, [])
        before = self.svc.team_averages("nba", "AAA", as_of="2026-01-22T00:00:00Z", season_type="all")
        after = self.svc.team_averages("nba", "AAA", as_of="2026-01-26T00:00:00Z", season_type="all")
        newest = self.svc.team_averages("nba", "AAA", season_type="all")
        pts = lambda o: o["data"]["stats"]["points"]["total"]
        self.assertEqual(pts(after) - pts(before), 1.0)             # the correction shows up only once it was observed
        self.assertEqual(pts(newest), pts(after))

    def test_earliest_version_is_used_when_nothing_was_observed_by_as_of(self):
        fixed = [tg("g1", "1", "2", "home", 101, 90, "2026-01-10", observed="2026-01-25T00:00:00Z"),
                 tg("g1", "2", "1", "away", 90, 101, "2026-01-10", observed="2026-01-25T00:00:00Z")]
        self.load([], fixed, [])
        out = self.svc.team_averages("nba", "AAA", as_of="2026-01-11T00:00:00Z")
        self.assertEqual(out["data"]["stats"]["points"]["total"], 100.0)

    def test_season_is_chosen_by_as_of(self):
        old = [dict(game("o1", "2025-03-01", "1", "2", 90, 80), season=2025),
               dict(tg("o1", "1", "2", "home", 90, 80, "2025-03-01"), season=2025),
               dict(tg("o1", "2", "1", "away", 80, 90, "2025-03-01"), season=2025)]
        self.store.append("nba", "games", [old[0]])
        self.store.append("nba", "team_games", old[1:])
        a = self.svc.team_averages("nba", "AAA", as_of="2025-04-01T00:00:00Z")
        self.assertEqual((a["meta"]["season"], a["data"]["games"]), ("2025", 1))
        self.assertEqual(self.svc.team_averages("nba", "AAA")["meta"]["season"], "2026")
        self.assertFalse(self.svc.team_averages("nba", "AAA", as_of="2024-01-01T00:00:00Z")["available"])


class PlayerAverageTests(StatsBase):
    def test_games_exclude_did_not_play_and_preseason(self):
        d = self.svc.player_averages("nba", "10")["data"]
        self.assertEqual(d["games"], 3)
        self.assertEqual(d["groups"]["all"]["stats"]["points"]["avg"], 20.0)
        self.assertEqual((d["wins"], d["losses"]), (3, 0))

    def test_splits_home_away_starter_bench_last(self):
        s = self.svc.player_splits("nba", "10", splits=("all", "home", "away", "starter", "bench", "last2"))["data"]
        self.assertEqual(s["home"]["groups"]["all"]["stats"]["points"]["avg"], 15.0)     # g1 (20) and g3 (10)
        self.assertEqual(s["away"]["groups"]["all"]["stats"]["points"]["avg"], 30.0)
        self.assertEqual((s["starter"]["games"], s["bench"]["games"]), (2, 1))
        self.assertEqual(s["last2"]["groups"]["all"]["stats"]["points"]["avg"], 20.0)    # g2 (30) and g3 (10)
        self.assertEqual(s["all"]["starts"], 2)

    def test_league_table_min_games_and_team_filter(self):
        rows = self.svc.player_averages("nba", min_games=2)["data"]
        self.assertEqual([r["player_id"] for r in rows], ["10"])
        rows = self.svc.player_averages("nba", team="BBB")["data"]
        self.assertEqual([r["player_id"] for r in rows], ["20"])

    def test_point_in_time_player_lines(self):
        d = self.svc.player_averages("nba", "10", as_of="2026-01-13T12:00:00Z")["data"]
        self.assertEqual((d["games"], d["groups"]["all"]["stats"]["points"]["total"]), (2, 50.0))

    def test_unknown_player_and_leagues_without_player_lines(self):
        self.assertFalse(self.svc.player_averages("nba", "999")["available"])
        self.assertFalse(self.svc.player_averages("ncaaf")["available"])
        self.assertFalse(self.svc.player_splits("ncaab", "1")["available"])
        self.assertFalse(self.svc.capabilities("ncaaf")["player_averages"]["available"])

    def test_soccer_bench_players_without_an_appearance_are_not_counted(self):
        starter = {"league": "epl", "game_id": "s1", "player_id": "7", "team_id": "1", "season": 2026,
                   "observed_utc": "2026-01-20T00:00:00Z", "starter": True, "stats": {"all": {"appearances": "1", "totalGoals": "1"}}}
        used_sub = dict(starter, game_id="s2", starter=False, subbed_in=True,
                        stats={"all": {"appearances": "1", "totalGoals": "0"}})
        unused = dict(starter, game_id="s3", starter=False, stats={"all": {"appearances": "0", "totalGoals": "0"}})
        self.assertTrue(agg.played(starter, "soccer"))
        self.assertTrue(agg.played(used_sub, "soccer"))
        self.assertFalse(agg.played(unused, "soccer"))
        self.assertTrue(agg.played(unused, "basketball"))


class ClientAndCliTests(StatsBase):
    def test_dataclient_league_view_exposes_the_new_reads(self):
        client = core.DataClient()
        client._espn = self.svc
        view = client.league("nba")
        self.assertEqual(view.team_averages("AAA")["data"]["games"], 4)
        self.assertEqual(view.player_averages("10")["data"]["games"], 3)
        self.assertEqual(view.team_splits("AAA")["kind"], "team_splits")

    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = espn_cli.run(list(argv) + ["--root", str(self.store.root)])
        return code, buf.getvalue()

    def test_cli_averages_and_splits(self):
        code, out = self.call("nba", "averages", "--team", "AAA", "--last", "2")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["data"]["games"], 2)
        code, out = self.call("nba", "averages", "--players", "--min-games", "2")
        self.assertEqual([r["player_id"] for r in json.loads(out)["data"]], ["10"])
        code, out = self.call("nba", "splits", "--team", "AAA", "--as-of", "2026-01-13T12:00:00Z")
        self.assertEqual(json.loads(out)["data"]["all"]["games"], 2)
        self.assertEqual(self.call("nba", "splits")[0], 2)
        self.assertEqual(self.call("nba", "averages", "--team", "ZZZ")[0], 2)


# -- play-by-play ----------------------------------------------------------------------------------------------------

class PbpParseTests(unittest.TestCase):
    def test_nba_plays(self):
        events, drives = pbp.espn_events(fxp("nba_plays.json"))
        self.assertEqual(drives, [])
        self.assertTrue(all(e["n"] == int(e["n"]) for e in events))
        self.assertEqual([e["n"] for e in events], sorted(e["n"] for e in events))
        scoring = [e for e in events if e.get("sc")]
        self.assertTrue(scoring)
        self.assertTrue(all(e["pts"] in (1, 2, 3) for e in scoring))
        end = events[-1]
        self.assertEqual(end["type"], "End Game")
        self.assertNotIn("x", end)                      # ESPN's -214748340 "no coordinate" is dropped
        self.assertTrue(any("x" in e and abs(e["x"]) < 2000 for e in events))
        self.assertEqual((end["as"], end["hs"]), (132, 123))
        shot = next(e for e in events if e.get("shoot") and e.get("ply"))
        self.assertIsInstance(shot["ply"][0], str)

    def test_nhl_plays_keep_roles_strength_and_scoring(self):
        events, _ = pbp.espn_events(fxp("nhl_plays.json"))
        hit = next(e for e in events if e["type"] == "Hit")
        self.assertEqual(hit["plt"], ["hit-credited", "hitted"])
        self.assertEqual(hit["str"], "even-strength")
        goal = next(e for e in events if e["type"] == "Goal")
        self.assertEqual((goal["sc"], goal["pts"]), (1, 1))
        self.assertIn("scorer", goal["plt"])

    def test_football_drives_link_plays_and_keep_down_and_distance(self):
        events, drives = pbp.espn_events(fxp("ncaaf_drives.json"))
        self.assertEqual(len(drives), 2)
        self.assertEqual(drives[0]["k"], "drive")
        self.assertTrue(all(e["drive"] in {d["id"] for d in drives} for e in events))
        first_scrimmage = next(e for e in events if "down" in e and e["down"] >= 1)
        self.assertIn("dist", first_scrimmage)
        self.assertIn("yte", first_scrimmage)

    def test_nhle_events_and_roster(self):
        events, extra = pbp.nhle_events(fxp("nhle_pbp.json"))
        self.assertEqual(extra["nhle_game_id"], "2025020700")
        self.assertEqual(extra["home_abbrev"], "BUF")
        self.assertEqual(len(extra["roster"]), 4)
        goal = next(e for e in events if e["type"] == "goal")
        self.assertIn("scoringPlayerId", goal["d"])
        self.assertEqual(goal["team"], str(goal["d"]["eventOwnerTeamId"]))
        self.assertEqual([e["n"] for e in events], sorted(e["n"] for e in events))

    def test_empty_payloads(self):
        self.assertEqual(pbp.espn_events({}), ([], []))
        self.assertEqual(pbp.nhle_events({})[0], [])


class PbpStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = pbp.PbpStore(Path(self.tmp.name))
        self.events, self.drives = pbp.espn_events(fxp("ncaaf_drives.json"))

    def put(self, gid="1", observed="2026-01-20T00:00:00Z", events=None, source="espn", **kw):
        return self.store.append_game("ncaaf", 2026, gid, source, observed,
                                      self.events if events is None else events, self.drives, **kw)

    def test_round_trip_and_index(self):
        self.assertEqual(self.put("1"), "added")
        got = self.store.read("ncaaf", 2026, "1", "espn")
        self.assertEqual(got["events"], self.events)
        self.assertEqual(got["drives"], self.drives)
        self.assertEqual(got["header"]["game_id"], "1")
        row = self.store.index("ncaaf", 2026)[0]
        self.assertEqual((row["events"], row["drives"], row["offset"]), (len(self.events), 2, 0))

    def test_identical_refetch_writes_nothing_and_a_change_appends_a_version(self):
        self.put("1")
        before = self.store.path("ncaaf", 2026).read_bytes()
        self.assertEqual(self.put("1", observed="2026-01-21T00:00:00Z"), "unchanged")
        self.assertEqual(self.store.path("ncaaf", 2026).read_bytes(), before)
        changed = copy.deepcopy(self.events)
        changed[0]["txt"] = "corrected"
        self.assertEqual(self.put("1", observed="2026-01-22T00:00:00Z", events=changed), "versioned")
        data = self.store.path("ncaaf", 2026).read_bytes()
        self.assertTrue(data.startswith(before))                 # append-only: the old member is untouched
        self.assertEqual(len(self.store.index("ncaaf", 2026)), 2)
        self.assertEqual(self.store.read("ncaaf", 2026, "1", "espn")["events"][0]["txt"], "corrected")
        old = self.store.read("ncaaf", 2026, "1", "espn", as_of="2026-01-21T00:00:00Z")
        self.assertEqual(old["events"], self.events)             # as_of reads the version known then

    def test_as_of_before_first_observation(self):
        self.put("1", observed="2026-01-20T00:00:00Z")
        self.assertIsNone(self.store.read("ncaaf", 2026, "1", "espn", as_of="2026-01-01T00:00:00Z"))
        late = self.store.read("ncaaf", 2026, "1", "espn", as_of="2026-01-01T00:00:00Z", allow_reconstructed=True)
        self.assertEqual(late["index"]["observed_utc"], "2026-01-20T00:00:00Z")

    def test_members_concatenate_into_one_valid_gzip_file(self):
        self.put("1")
        self.put("2")
        with gzip.open(self.store.path("ncaaf", 2026), "rt", encoding="utf-8") as handle:
            lines = [json.loads(l) for l in handle if l.strip()]
        self.assertEqual([l["game_id"] for l in lines if l.get("k") == "game"], ["1", "2"])
        self.assertEqual(len([l for l in lines if "n" in l]), 2 * len(self.events))
        rows = self.store.index("ncaaf", 2026)
        self.assertEqual(rows[1]["offset"], rows[0]["length"])          # a reader can seek straight to game 2
        self.assertEqual(self.store.read("ncaaf", 2026, "2", "espn")["events"], self.events)

    def test_bytes_are_deterministic(self):
        self.put("1")
        other = pbp.PbpStore(Path(self.tmp.name) / "other")
        other.append_game("ncaaf", 2026, "1", "espn", "2026-01-20T00:00:00Z", self.events, self.drives)
        self.assertEqual(self.store.path("ncaaf", 2026).read_bytes(), other.path("ncaaf", 2026).read_bytes())

    def test_sources_are_separate_and_header_extras_are_kept(self):
        self.put("1")
        self.put("1", source="nhle", header={"nhle_game_id": "999"})
        self.assertEqual(self.store.read("ncaaf", 2026, "1", "nhle")["header"]["nhle_game_id"], "999")
        self.assertEqual(sorted(s for (g, s) in self.store.newest_by_game("ncaaf", 2026)), ["espn", "nhle"])
        with self.assertRaises(ValueError):
            self.put("1", source="made-up")

    def test_verify_catches_a_damaged_file(self):
        self.put("1")
        self.put("2")
        self.assertEqual(self.store.verify("ncaaf", 2026), [])
        path = self.store.path("ncaaf", 2026)
        path.write_bytes(path.read_bytes()[:-20])
        problems = self.store.verify("ncaaf", 2026)
        self.assertTrue(problems)
        self.assertIn("2@", problems[0])
        path.unlink()
        self.assertIn("missing", self.store.verify("ncaaf", 2026)[0])

    def test_sizes(self):
        self.put("1")
        size = self.store.sizes("ncaaf")["2026"]
        self.assertEqual((size["games"], size["members"]), (1, 1))
        self.assertGreater(size["gz_bytes"], 0)


def nba_summary_with_plays():
    s = fx("nba_summary.json")
    s["plays"] = fxp("nba_plays.json")["plays"]
    return s


def nba_pbp_routes():
    return [(n, nba_summary_with_plays() if n.startswith("summary?event=") else p) for n, p in nba_routes()]


def nhl_routes(feed=None):
    sb = fx("nhl_scoreboard.json")
    summary = fx("nhl_summary.json")
    summary["plays"] = fxp("nhl_plays.json")["plays"]
    return [("scoreboard?dates=20260115", sb), ("scoreboard?", {"events": []}),
            (f"summary?event={sb['events'][0]['id']}", summary),
            ("schedule/2026-01-15", fxp("nhle_schedule.json")),
            ("gamecenter/2025020700/play-by-play", feed or fxp("nhle_pbp.json"))]


class PbpPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EspnStore(self.root / "espn")
        self.cache = self.root / "raw"
        self.pstore = pbp.PbpStore(self.store.root)

    def refresh(self, code, net, **kw):
        kw.setdefault("today", date(2026, 1, 15))
        return pipeline.refresh(code, store=self.store, fetcher=fetcher(net, self.cache), now=lambda: NOW,
                                days_back=0, days_ahead=0, **kw)

    def test_off_by_default(self):
        s = self.refresh("nba", FakeNet(nba_pbp_routes()))
        self.assertEqual(s["pbp_games"], 0)
        self.assertEqual(self.pstore.seasons("nba"), [])

    def test_refresh_with_pbp_reads_plays_from_the_box_score_page_without_an_extra_request(self):
        net = FakeNet(nba_pbp_routes())
        s = self.refresh("nba", net, pbp=True)
        self.assertEqual((s["box_scores"], s["pbp_games"]), (1, 1))
        self.assertEqual(s["pbp_events"], len(fxp("nba_plays.json")["plays"]))
        self.assertEqual(len([u for u in net.urls if "summary?event=401810433" in u]), 1)      # one fetch served both
        row = self.pstore.index("nba", 2026)[0]
        self.assertEqual((row["game_id"], row["source"]), ("401810433", "espn"))
        self.assertTrue(pipeline.check(self.store, ["nba"])["ok"])

    def test_second_run_is_free(self):
        self.refresh("nba", FakeNet(nba_pbp_routes()), pbp=True)
        before = self.pstore.path("nba", 2026).read_bytes()
        net = FakeNet(nba_pbp_routes())
        s = self.refresh("nba", net, pbp=True)
        self.assertEqual((s["pbp_games"], s["pbp_events"]), (0, 0))
        self.assertFalse([u for u in net.urls if "summary" in u])
        self.assertEqual(self.pstore.path("nba", 2026).read_bytes(), before)

    def test_fill_adds_play_by_play_to_games_already_stored(self):
        self.refresh("nba", FakeNet(nba_pbp_routes()))                     # box scores only
        self.assertEqual(self.pstore.seasons("nba"), [])
        net = FakeNet(nba_pbp_routes())
        s = pipeline.fill_pbp("nba", store=self.store, fetcher=fetcher(net, self.root / "raw2"), now=lambda: NOW)
        self.assertEqual(s["pbp_games"], 1)
        self.assertEqual(s["kind"], "pbp")
        again = pipeline.fill_pbp("nba", store=self.store, fetcher=fetcher(FakeNet(nba_pbp_routes()), self.root / "raw3"),
                                  now=lambda: NOW)
        self.assertEqual(again["pbp_games"], 0)

    def test_fill_limit_makes_it_resumable(self):
        for gid, day in (("1", "2026-01-10"), ("2", "2026-01-11"), ("3", "2026-01-12")):
            self.store.append("nba", "games", [game(gid, day, "1", "2", 1, 0, observed="2026-01-20T00:00:00Z")])
        net = FakeNet([("summary?event=", nba_summary_with_plays())])
        s1 = pipeline.fill_pbp("nba", store=self.store, fetcher=fetcher(net, self.cache), limit=2, now=lambda: NOW)
        self.assertEqual(s1["pbp_games"], 2)
        s2 = pipeline.fill_pbp("nba", store=self.store, fetcher=fetcher(net, self.cache), limit=2, now=lambda: NOW)
        self.assertEqual(s2["pbp_games"], 1)          # only the third game was missing
        self.assertEqual(sorted(k[0] for k in self.pstore.newest_by_game("nba", 2026)), ["1", "2", "3"])

    def test_game_without_plays_is_counted_not_stored(self):
        s = self.refresh("nba", FakeNet(nba_routes()), pbp=True)           # the plain fixture has no plays
        self.assertEqual((s["pbp_games"], s["pbp_missing"]), (0, 1))
        self.assertEqual(self.pstore.seasons("nba"), [])

    def test_unsettled_copy_is_refreshed_once_after_the_day(self):
        early = datetime(2026, 1, 16, 2, 0, 0)         # a few hours after the 2026-01-15 19:00Z tip
        net = FakeNet(nba_pbp_routes())
        f1 = PoliteFetcherFor(net, self.cache, "2026-01-16T02:00:00Z")
        pipeline.refresh("nba", store=self.store, fetcher=f1, today=date(2026, 1, 15), days_back=0, days_ahead=0,
                         now=lambda: early, pbp=True)
        self.assertEqual(len(self.pstore.index("nba", 2026)), 1)
        corrected = nba_summary_with_plays()
        corrected["plays"][0]["text"] = "corrected overnight"
        net2 = FakeNet([(n, corrected if n.startswith("summary?event=") else p) for n, p in nba_routes()])
        s = self.refresh("nba", net2, pbp=True)
        self.assertEqual(s["pbp_games"], 1)
        self.assertEqual(len(self.pstore.index("nba", 2026)), 2)
        self.assertEqual(self.pstore.read("nba", 2026, "401810433", "espn")["events"][0]["txt"], "corrected overnight")

    def test_nhl_official_feed_is_matched_by_team_names_and_date(self):
        net = FakeNet(nhl_routes())
        s = self.refresh("nhl", net, pbp=True)
        self.assertEqual((s["pbp_games"], s["nhle_games"]), (1, 1))
        got = self.pstore.read("nhl", 2026, "401803091", "nhle")
        self.assertEqual(got["header"]["nhle_game_id"], "2025020700")
        self.assertEqual(len([u for u in net.urls if "api-web.nhle.com" in u and "schedule" in u]), 1)
        self.assertTrue(any("2026-01-15" in u for u in net.urls if "schedule" in u))     # the week starts the day BEFORE the UTC date
        self.assertTrue(pipeline.check(self.store, ["nhl"])["ok"])

    def test_nhl_game_listed_in_the_following_week_is_still_found(self):
        routes = [(n, p) for n, p in nhl_routes() if "schedule" not in n]
        routes += [("schedule/2026-01-15", {"gameWeek": []}), ("schedule/2026-01-16", fxp("nhle_schedule.json"))]
        net = FakeNet(routes)
        s = self.refresh("nhl", net, pbp=True)
        self.assertEqual(s["nhle_games"], 1)
        self.assertEqual(len([u for u in net.urls if "api-web" in u and "schedule" in u]), 2)

    def test_nhl_game_the_feed_cannot_match_is_recorded_missing(self):
        routes = [(n, p) for n, p in nhl_routes() if "schedule" not in n]
        s = self.refresh("nhl", FakeNet(routes), pbp=True)
        self.assertEqual((s["pbp_games"], s["nhle_games"], s["pbp_missing"]), (1, 0, 1))

    def test_leagues_without_pbp_are_skipped(self):
        s = pipeline.fill_pbp("ncaab", store=self.store, fetcher=fetcher(FakeNet([]), self.cache), now=lambda: NOW)
        self.assertIn("not enabled", s["skipped"])

    def test_pbp_files_stay_out_of_the_tracked_manifest(self):
        self.refresh("nba", FakeNet(nba_pbp_routes()), pbp=True)
        files = self.store.read_manifest("nba")["files"]
        self.assertFalse([n for n in files if n.startswith("pbp_")])
        self.assertIn("games_2026.jsonl", files)

    def test_check_flags_a_truncated_play_by_play_file(self):
        self.refresh("nba", FakeNet(nba_pbp_routes()), pbp=True)
        path = self.pstore.path("nba", 2026)
        path.write_bytes(path.read_bytes()[:-10])
        report = pipeline.check(self.store, ["nba"])
        self.assertFalse(report["ok"])


def PoliteFetcherFor(net, cache, iso):
    return fetcher(net, cache, iso=iso)


class PbpServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EspnStore(self.root / "espn")
        pipeline.refresh("nhl", store=self.store, fetcher=fetcher(FakeNet(nhl_routes()), self.root / "raw"),
                         today=date(2026, 1, 15), days_back=0, days_ahead=0, now=lambda: NOW, pbp=True)
        self.svc = service.EspnService(self.store, clock=lambda: NOW_ISO)
        self.gid = "401803091"

    def test_reads_default_to_espn_and_list_the_other_source(self):
        out = self.svc.play_by_play("nhl", self.gid)
        self.assertTrue(out["available"])
        d = out["data"]
        self.assertEqual((d["source"], d["sources_available"]), ("espn", ["espn", "nhle"]))
        self.assertEqual(d["n_events"], len(d["events"]))
        self.assertEqual(out["meta"]["game_basis"], "all")
        nhle = self.svc.play_by_play("nhl", self.gid, source="nhle")["data"]
        self.assertEqual(nhle["header"]["nhle_game_id"], "2025020700")
        self.assertFalse(self.svc.play_by_play("nhl", self.gid, source="made-up")["available"])

    def test_filters(self):
        out = self.svc.play_by_play("nhl", self.gid, scoring_only=True)["data"]
        self.assertTrue(out["events"])
        self.assertTrue(all(e.get("sc") for e in out["events"]))
        self.assertEqual(self.svc.play_by_play("nhl", self.gid, period=9)["data"]["events"], [])
        self.assertTrue(self.svc.play_by_play("nhl", self.gid, source="nhle", scoring_only=True)["data"]["events"])

    def test_as_of_needs_the_game_to_be_final_by_then(self):
        # kickoff 2026-01-16T00:00Z, hockey allowance 3.5 h; we observed it on NOW (2026-01-20 12:00)
        early = self.svc.play_by_play("nhl", self.gid, as_of="2026-01-16T01:00:00Z")
        self.assertFalse(early["available"])
        self.assertIn("not final by", early["missing"][0]["reason"])
        ok = self.svc.play_by_play("nhl", self.gid, as_of="2026-01-17T00:00:00Z")
        self.assertTrue(ok["available"])
        self.assertEqual(ok["meta"]["game_basis"], "reconstructed")
        self.assertFalse(self.svc.play_by_play("nhl", self.gid, as_of="2026-01-17T00:00:00Z", strict=True)["available"])

    def test_unavailable_shapes(self):
        self.assertFalse(self.svc.play_by_play("nhl", "nope")["available"])
        self.assertFalse(self.svc.play_by_play("ncaab", "1")["available"])
        self.assertFalse(self.svc.capabilities("ncaab")["play_by_play"]["available"])
        self.assertTrue(self.svc.capabilities("nhl")["play_by_play"]["available"])

    def test_cli_pbp(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = espn_cli.run(["nhl", "pbp", "--game-id", self.gid, "--source", "nhle", "--scoring-only",
                                 "--root", str(self.store.root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["data"]["source"], "nhle")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(espn_cli.run(["nhl", "pbp", "--root", str(self.store.root)]), 2)


class RegistryTests(unittest.TestCase):
    def test_pbp_flags(self):
        self.assertTrue(all(leagues.get(c).pbp for c in ("nba", "nhl", "ncaaf", "wnba")))
        self.assertFalse(any(leagues.get(c).pbp for c in ("epl", "ncaab", "ncaaw")))
        self.assertEqual([c for c, l in leagues.LEAGUES.items() if l.nhle], ["nhl"])

    def test_scheduled_set_grew_in_round_two_and_player_lines_stay_off_for_the_new_soccer_leagues(self):
        self.assertEqual(leagues.DEFAULT_REFRESH[:5], ("nba", "nhl", "ncaaf", "ncaab", "epl"))
        for code in ("wnba", "ncaaw", "laliga", "bundesliga", "seriea", "ligue1", "mls", "ucl"):
            self.assertIn(code, leagues.DEFAULT_REFRESH)
        self.assertEqual(len(leagues.DEFAULT_REFRESH), len(set(leagues.DEFAULT_REFRESH)))
        self.assertTrue(leagues.get("epl").players and leagues.get("wnba").players)
        for code in ("laliga", "bundesliga", "seriea", "ligue1", "mls", "ucl", "ncaaw"):
            self.assertFalse(leagues.get(code).players, code)
        self.assertEqual(espn_cli._codes("all"), list(leagues.DEFAULT_REFRESH))


if __name__ == "__main__":
    unittest.main()
