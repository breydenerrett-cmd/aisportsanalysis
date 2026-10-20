"""football-data.co.uk history: CSV parsing, the versioned store, the terms gate, and the join to ESPN game ids.

Synthetic CSV text (real column layout, invented odds) and synthetic ESPN rows in temp directories; the fetch path
is exercised with a fake opener that fails the test if the site is ever asked while the gate is closed.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from src.datasvc.espn.store import EspnStore
from src.datasvc.http import PoliteFetcher
from src.datasvc.soccer import cli as soccer_cli, footballdata as fd, match as matcher, service as svc
from tests.test_datasvc_espn import FakeNet

HEADER = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,"
          "B365H,B365D,B365A,PSH,PSD,PSA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,B365>2.5,B365<2.5,AHh,B365AHH,B365AHA,"
          "B365CH,B365CD,B365CA,PSCH,PSCD,PSCA,B365C>2.5,B365C<2.5,AHCh,B365CAHH,B365CAHA")
ROWS = [
    "E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H,1,0,H,A Taylor,19,10,10,3,7,10,6,7,1,2,0,0,"
    "1.3,6,8.5,1.28,6.56,9.07,1.34,6.5,9.5,1.31,5.96,8.31,1.36,3.2,-1.5,1.83,2.03,1.29,6.25,9,1.29,6.55,9.75,1.36,3.2,-1.75,2.03,1.78",
    "E0,16/08/2025,12:30,Man City,Wolves,2,0,H,1,0,H,M Oliver,15,6,6,1,9,11,8,2,0,1,0,0,"
    "1.2,7,13,,,,1.22,7.5,15,1.2,7.1,12.5,1.4,3,-2,1.9,2,1.18,7.5,14,,,,1.4,3,-2.25,2.05,1.8",
    "E0,23/12/2025,19:45,Nott'm Forest,Tottenham,1,1,D,0,0,D,P Tierney,12,12,4,4,10,9,5,6,2,2,0,0,"
    "2.9,3.4,2.5,,,,3,3.5,2.6,2.8,3.4,2.45,1.9,1.95,0,1.95,1.95,2.9,3.3,2.55,,,,1.95,1.9,0,1.95,1.95",
    ",,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,",
]
CSV = HEADER + "\n" + "\n".join(ROWS) + "\n"


def espn_game(gid, day, home, away, hs, as_, *, hn=None, an=None):
    return {"league": "epl", "game_id": gid, "date_utc": f"{day}T15:00:00Z", "state": "post", "completed": True,
            "home_id": home, "away_id": away, "home_name": hn or home, "away_name": an or away,
            "home_score": hs, "away_score": as_, "season": 2025, "observed_utc": "2026-01-01T00:00:00Z"}


def team(tid, display, short=None, abbr=None):
    return {"league": "epl", "team_id": tid, "display_name": display, "name": display, "location": display,
            "short_name": short or display, "abbreviation": abbr or display[:3].upper(),
            "observed_utc": "2026-01-01T00:00:00Z"}


ESPN_TEAMS = {t["team_id"]: t for t in (
    team("364", "Liverpool", "Liverpool", "LIV"), team("349", "AFC Bournemouth", "Bournemouth", "BOU"),
    team("382", "Manchester City", "Man City", "MNC"), team("380", "Wolverhampton Wanderers", "Wolves", "WOL"),
    team("393", "Nottingham Forest", "Nottm Forest", "NFO"), team("367", "Tottenham Hotspur", "Spurs", "TOT"))}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.rows = fd.parse_csv("﻿" + CSV, "epl", 2025, "2026-10-20T00:00:00Z")

    def test_blank_rows_are_skipped_and_bom_is_ignored(self):
        self.assertEqual(len(self.rows), 3)
        self.assertEqual(self.rows[0]["match_id"], "E0-2025-08-15-liverpool-bournemouth")

    def test_result_and_statistics(self):
        r = self.rows[0]
        self.assertEqual((r["ft_home"], r["ft_away"], r["ft_result"], r["ht_result"]), (4, 2, "H", "H"))
        self.assertEqual(r["stats"]["shots_home"], 19)
        self.assertEqual(r["referee"], "A Taylor")
        self.assertEqual((r["season"], r["league"], r["div"]), (2025, "epl", "E0"))

    def test_open_and_closing_odds_by_book(self):
        o = self.rows[0]["odds"]
        self.assertEqual(o["1x2"]["B365"], {"open": [1.3, 6.0, 8.5], "close": [1.29, 6.25, 9.0]})
        self.assertEqual(o["1x2"]["PS"]["close"], [1.29, 6.55, 9.75])
        self.assertEqual(o["1x2"]["Max"]["open"], [1.34, 6.5, 9.5])
        self.assertEqual(o["ou25"]["B365"], {"open": [1.36, 3.2], "close": [1.36, 3.2]})
        self.assertEqual(o["ah"]["line_open"], -1.5)
        self.assertEqual(o["ah"]["line_close"], -1.75)
        self.assertEqual(o["ah"]["B365"], {"open": [1.83, 2.03], "close": [2.03, 1.78]})

    def test_blank_odds_are_absent_not_zero(self):
        o = self.rows[1]["odds"]
        self.assertNotIn("PS", o["1x2"])                 # Pinnacle cells were empty
        self.assertIn("B365", o["1x2"])

    def test_old_column_names_map_onto_the_same_books(self):
        text = ("Div,Date,HomeTeam,AwayTeam,HG,AG,Res,PH,PD,PA,BbMxH,BbMxD,BbMxA,BbAvH,BbAvD,BbAvA,BbMx>2.5,BbMx<2.5\n"
                "E0,13/08/16,Hull,Burnley,2,0,H,2.1,3.3,3.6,2.2,3.5,3.8,2.05,3.3,3.5,1.9,2.1\n")
        r = fd.parse_csv(text, "epl", 2016, "T")[0]
        self.assertEqual((r["date"], r["ft_home"], r["ft_away"], r["ft_result"]), ("2016-08-13", 2, 0, "H"))
        self.assertEqual(r["odds"]["1x2"]["PS"]["open"], [2.1, 3.3, 3.6])
        self.assertEqual(r["odds"]["1x2"]["Max"]["open"], [2.2, 3.5, 3.8])
        self.assertEqual(r["odds"]["1x2"]["Avg"]["open"], [2.05, 3.3, 3.5])
        self.assertEqual(r["odds"]["ou25"]["Max"]["open"], [1.9, 2.1])
        self.assertNotIn("close", r["odds"]["1x2"]["Max"])

    def test_repeated_fixture_gets_a_distinct_id(self):
        text = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,01/01/2025,A,B,1,0\nE0,01/01/2025,A,B,2,0\n"
        ids = [r["match_id"] for r in fd.parse_csv(text, "epl", 2024, "T")]
        self.assertEqual(ids, ["E0-2025-01-01-a-b", "E0-2025-01-01-a-b-2"])

    def test_dates(self):
        self.assertEqual(fd.parse_date("15/08/2025"), "2025-08-15")
        self.assertEqual(fd.parse_date("15/08/25"), "2025-08-15")
        self.assertEqual(fd.parse_date("15/08/99"), "1999-08-15")
        for bad in ("", None, "2025-08-15", "31/02/2025"):
            self.assertIsNone(fd.parse_date(bad))

    def test_uk_time_to_utc_follows_summer_time(self):
        self.assertEqual(fd.uk_to_utc("2025-08-15", "20:00"), "2025-08-15T19:00:00Z")       # BST
        self.assertEqual(fd.uk_to_utc("2025-12-23", "19:45"), "2025-12-23T19:45:00Z")       # GMT
        self.assertEqual(fd.uk_to_utc("2026-03-28", "12:00"), "2026-03-28T12:00:00Z")       # day before the change
        self.assertEqual(fd.uk_to_utc("2026-03-29", "14:00"), "2026-03-29T13:00:00Z")       # the change day, afternoon
        self.assertEqual(fd.uk_to_utc("2026-10-24", "15:00"), "2026-10-24T14:00:00Z")       # still BST
        self.assertEqual(fd.uk_to_utc("2026-10-25", "16:00"), "2026-10-25T16:00:00Z")       # back to GMT
        self.assertIsNone(fd.uk_to_utc("2025-08-15", ""))
        self.assertEqual(self.rows[0]["kickoff_utc_est"], "2025-08-15T19:00:00Z")

    def test_urls(self):
        self.assertEqual(fd.season_url("epl", 2025), "https://www.football-data.co.uk/mmz4281/2526/E0.csv")
        self.assertEqual(fd.season_url("laliga", 1999), "https://www.football-data.co.uk/mmz4281/9900/SP1.csv")


class StoreAndGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = fd.FootballDataStore(self.root / "fd")

    def test_ingest_is_idempotent_and_a_revised_price_is_a_new_version(self):
        a = fd.ingest(self.store, "epl", 2025, CSV, "2026-10-20T00:00:00Z")
        self.assertEqual((a["rows"], a["added"]), (3, 3))
        b = fd.ingest(self.store, "epl", 2025, CSV, "2026-10-21T00:00:00Z")
        self.assertEqual((b["added"], b["versioned"], b["unchanged"]), (0, 0, 3))
        revised = CSV.replace("1.3,6,8.5,1.28", "1.31,6,8.5,1.28")
        c = fd.ingest(self.store, "epl", 2025, revised, "2026-10-22T00:00:00Z")
        self.assertEqual((c["added"], c["versioned"]), (0, 1))
        self.assertEqual(len(self.store.versions("epl", "matches", 2025)), 4)
        first = self.store.latest("epl", "matches", 2025, as_of="2026-10-21T12:00:00Z")[("epl", "E0-2025-08-15-liverpool-bournemouth")]
        self.assertEqual(first["odds"]["1x2"]["B365"]["open"][0], 1.3)

    def test_import_a_downloaded_file(self):
        path = self.root / "E0.csv"
        path.write_text(CSV, encoding="utf-8")
        out = fd.import_csv(self.store, "epl", 2025, path, "2026-10-20T00:00:00Z")
        self.assertEqual(out["rows"], 3)

    def test_fetch_is_refused_without_the_acknowledgement_and_never_touches_the_network(self):
        net = FakeNet([("football-data.co.uk", CSV.encode("utf-8"))])
        f = PoliteFetcher(cache_dir=self.root / "raw", opener=net, sleep=lambda s: None, delay_s=0)
        with self.assertRaises(fd.TermsNotAccepted) as ctx:
            fd.fetch_season(f, "epl", 2025, accept_terms=False)
        self.assertIn("private individuals only", str(ctx.exception))
        with self.assertRaises(fd.TermsNotAccepted):
            fd.fetch_range(self.store, f, "epl", 2015, 2025, accept_terms=False, observed_utc="T")
        self.assertEqual(net.urls, [])

    def test_fetch_with_the_acknowledgement_uses_the_polite_fetcher(self):
        net = FakeNet([("mmz4281/2526/E0.csv", CSV.encode("utf-8"))])
        f = PoliteFetcher(cache_dir=self.root / "raw", opener=net, sleep=lambda s: None, delay_s=0)
        out = fd.fetch_range(self.store, f, "epl", 2025, 2026, accept_terms=True, observed_utc="2026-10-20T00:00:00Z")
        self.assertEqual(out[0]["rows"], 3)
        self.assertTrue(out[1]["missing"])                       # 2026/27 file answered 404 in this fake
        self.assertEqual(len(net.urls), 2)

    def test_cli_fetch_prints_the_notice_and_exits_2(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = soccer_cli.run(["fetch", "--league", "epl", "--root", str(self.root / "fd")])
        self.assertEqual(code, 2)
        self.assertIn("private individuals only", buf.getvalue())
        self.assertFalse((self.root / "fd").exists())

    def test_store_defaults_are_untracked_locations(self):
        self.assertEqual(fd.FootballDataStore.default_dir.name, "footballdata")


class MatchTests(unittest.TestCase):
    def fd_rows(self):
        return fd.parse_csv(CSV, "epl", 2025, "T")

    def games(self, **over):
        g = [espn_game("g1", "2025-08-15", "364", "349", 4, 2, hn="Liverpool", an="AFC Bournemouth"),
             espn_game("g2", "2025-08-16", "382", "380", 2, 0, hn="Manchester City", an="Wolverhampton Wanderers"),
             espn_game("g3", "2025-12-23", "393", "367", 1, 1, hn="Nottingham Forest", an="Tottenham Hotspur")]
        return g

    def test_names_join_all_three_and_scores_agree(self):
        joins, report = matcher.match(self.fd_rows(), self.games(), ESPN_TEAMS)
        self.assertEqual((report["matched"], report["match_rate"], report["unmatched"]), (3, 1.0, 0))
        self.assertEqual({j["match_id"]: j["game_id"] for j in joins},
                         {"E0-2025-08-15-liverpool-bournemouth": "g1", "E0-2025-08-16-man-city-wolves": "g2",
                          "E0-2025-12-23-nott-m-forest-tottenham": "g3"})
        self.assertEqual(report["scores_checked"], 3)

    def test_name_scoring(self):
        self.assertEqual(matcher.name_score("Man City", ["Manchester City", "Man City"]), 1.0)
        self.assertGreaterEqual(matcher.name_score("Man City", ["Manchester City"]), 0.9)
        self.assertLess(matcher.name_score("Man United", ["Manchester City"]), 0.75)
        self.assertEqual(matcher.name_score("Leeds", ["Leeds United"]), 1.0)
        self.assertGreaterEqual(matcher.name_score("Ein Frankfurt", ["Eintracht Frankfurt"]), 0.9)
        self.assertGreaterEqual(matcher.name_score("Nott'm Forest", ["Nottm Forest"]), 1.0)
        self.assertEqual(matcher.name_score("", ["X"]), 0.0)

    def test_a_name_no_token_rule_reaches_is_joined_one_sided_then_learned(self):
        teams = dict(ESPN_TEAMS)
        teams["380"] = team("380", "Wolverhampton Wanderers", "Wolverhampton", "WWF")      # no "Wolves", no WOL either
        joins, report = matcher.match(self.fd_rows(), self.games(), teams, seed={})
        by = {j["match_id"]: j for j in joins}
        self.assertEqual(by["E0-2025-08-16-man-city-wolves"]["method"], "one_side")
        self.assertEqual(report["matched"], 3)

    def test_seed_alias_resolves_a_leftover_in_the_second_pass(self):
        teams = dict(ESPN_TEAMS)
        teams["380"] = team("380", "Wolverhampton Wanderers", "Wolverhampton", "WWF")
        rows = [r for r in self.fd_rows() if "man-city" not in r["match_id"]]
        # a Wolves home fixture on a day with two candidate games: only the seed + alias route can pick it
        extra = dict(rows[0], match_id="E0-2025-09-01-wolves-man-city", date="2025-09-01", home="Wolves", away="Man City",
                     ft_home=1, ft_away=1)
        games = self.games() + [espn_game("g9", "2025-09-01", "380", "382", 1, 1, hn="Wolverhampton Wanderers",
                                          an="Manchester City")]
        joins, report = matcher.match(rows + [extra], games, teams, seed={"Wolves": "Wolverhampton Wanderers"})
        j = next(j for j in joins if j["match_id"] == "E0-2025-09-01-wolves-man-city")
        self.assertEqual(j["game_id"], "g9")
        self.assertIn(j["method"], ("one_side", "alias"))

    def test_utc_and_local_dates_may_differ_by_a_day(self):
        games = self.games()
        games[0]["date_utc"] = "2025-08-16T00:30:00Z"            # a late kickoff dated the next day in UTC
        joins, report = matcher.match(self.fd_rows(), games, ESPN_TEAMS)
        self.assertEqual(report["matched"], 3)
        self.assertEqual(next(j for j in joins if j["game_id"] == "g1")["day_gap"], 1)

    def test_no_game_in_the_window_is_unmatched_with_a_reason(self):
        games = self.games()[:2]
        joins, report = matcher.match(self.fd_rows(), games, ESPN_TEAMS)
        self.assertEqual((report["matched"], report["unmatched"]), (2, 1))
        self.assertIn("nott-m-forest", report["unmatched_examples"][0]["match_id"])

    def test_disagreeing_scores_drop_the_join(self):
        games = self.games()
        games[0]["home_score"], games[0]["away_score"] = 0, 0
        joins, report = matcher.match(self.fd_rows(), games, ESPN_TEAMS)
        self.assertEqual(report["matched"], 2)
        self.assertEqual(report["score_disagreements"][0]["game_id"], "g1")
        self.assertEqual(report["score_disagreements"][0]["fd"], [4, 2])

    def test_one_espn_game_is_never_given_to_two_matches(self):
        rows = self.fd_rows()
        twin = dict(rows[0], match_id="E0-2025-08-15-liverpool-bournemouth-2")
        joins, report = matcher.match(rows + [twin], self.games(), ESPN_TEAMS)
        ids = [j["game_id"] for j in joins]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(report["matched"], 3)
        self.assertEqual(report["unmatched"], 1)

    def test_a_club_missing_from_the_teams_table_is_named_from_its_games(self):
        teams = {k: v for k, v in ESPN_TEAMS.items() if k != "349"}          # Bournemouth not in the teams endpoint
        joins, report = matcher.match(self.fd_rows(), self.games(), teams)
        self.assertEqual(report["matched"], 3)

    def test_empty_inputs(self):
        self.assertEqual(matcher.match([], self.games(), ESPN_TEAMS)[1]["match_rate"], None)
        self.assertEqual(matcher.match(self.fd_rows(), [], ESPN_TEAMS)[1]["matched"], 0)


class ServiceAndCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fd_root = self.root / "fd"
        self.espn_root = self.root / "espn"
        espn = EspnStore(self.espn_root)
        espn.append("epl", "teams", list(ESPN_TEAMS.values()))
        espn.append("epl", "games", MatchTests.games(self))
        (self.root / "E0.csv").write_text(CSV, encoding="utf-8")

    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = soccer_cli.run(list(argv))
        return code, buf.getvalue()

    def test_import_match_odds_status(self):
        code, out = self.call("import", "--league", "epl", "--season", "2025", "--csv", str(self.root / "E0.csv"),
                              "--root", str(self.fd_root))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["added"], 3)
        code, out = self.call("match", "--league", "epl", "--root", str(self.fd_root), "--espn-root", str(self.espn_root))
        report = json.loads(out)
        self.assertEqual((code, report["matched"], report["match_rate"]), (0, 3, 1.0))
        code, out = self.call("odds", "--league", "epl", "--game-id", "g1", "--root", str(self.fd_root))
        got = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(got["data"]["match"]["odds"]["1x2"]["B365"]["close"], [1.29, 6.25, 9.0])
        self.assertEqual(got["data"]["join"]["game_id"], "g1")
        self.assertEqual(self.call("odds", "--league", "epl", "--game-id", "zzz", "--root", str(self.fd_root))[0], 2)
        code, out = self.call("status", "--root", str(self.fd_root))
        files = json.loads(out)["epl"]
        self.assertEqual((files["matches_2025.jsonl"], files["joins_2025.jsonl"]), (3, 3))

    def test_bad_arguments(self):
        self.assertEqual(self.call("import", "--league", "epl", "--root", str(self.fd_root))[0], 2)
        self.assertEqual(self.call("match", "--league", "epl", "--root", str(self.fd_root))[0], 2)     # nothing imported
        self.assertEqual(self.call("odds", "--league", "epl", "--root", str(self.fd_root))[0], 2)
        self.assertEqual(self.call("import", "--league", "nowhere")[0], 2)

    def test_service_filters(self):
        store = fd.FootballDataStore(self.fd_root)
        fd.ingest(store, "epl", 2025, CSV, "T")
        s = svc.SoccerHistoryService(store)
        self.assertEqual(len(s.matches("epl")["data"]), 3)
        self.assertEqual(len(s.matches("epl", date="2025-08-16")["data"]), 1)
        self.assertEqual(len(s.matches("epl", team="forest")["data"]), 1)
        self.assertNotIn("odds", s.matches("epl", odds=False)["data"][0])
        self.assertFalse(s.matches("epl", season=1999)["available"])
        self.assertFalse(s.matches("narnia")["available"])
        self.assertFalse(s.for_game("epl", "g1")["available"])             # not joined yet


if __name__ == "__main__":
    unittest.main()
