"""api/datasvc.py: GET /data/v1/nfl/... over the synthetic league of tests/_nfl_world.py.

FastAPI is an api/-only dependency and the Linux CI has none, so every test here is
`skipUnless(HAS_FASTAPI)`. The data is injected (`datasvc.use_nfl_data_dir`) and the clock pinned, so no test
depends on the machine, the real files or the time of day. Auth is real: a user and an invite token are made in
a throwaway sqlite file, so a request either carries a token the real `require_paid_access` accepts or it does
not, exactly as in tests/test_datasvc_ufc_api.py (whose ASGI helper is reused).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import FastAPI
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.datasvc import store as jsonl
from src.datasvc.nfl import features as nfl_features
from src.datasvc.nfl import matchup as nfl_matchup
from src.datasvc.nfl import store as nfl_store
from tests import _nfl_world as W
from tests.test_datasvc_ufc_api import request
from tests.test_datasvc_nfl_features import G, KICK

if HAS_FASTAPI:
    from api import datasvc

NOW = datetime(2025, 10, 20, 12, 0, tzinfo=timezone.utc)
PREFIX = "/data/v1"
NFL = "/data/v1/nfl"

ALL_NFL_ROUTES = (f"{NFL}/games", f"{NFL}/games/{G['g05']}", f"{NFL}/team-games", f"{NFL}/player-games", f"{NFL}/injuries",
                  f"{NFL}/matchup?game_id={G['g14']}", f"{NFL}/teams/KC/features", f"{NFL}/players/00-KCWR1/features",
                  f"{PREFIX}/status")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class NflApiCase(unittest.TestCase):
    """A fresh data directory, users database, app and pinned clock for every test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "nfl"
        self.store = W.build_world(self.dir)
        self.store.write_manifest(extra={"coverage": {"seasons": [2024, 2025], "player_games_since": 2025}})
        self.empty_ufc = Path(self._tmp.name) / "ufc"                        # no UFC data at all: its datasets are absent
        self.db = Path(self._tmp.name) / "app.db"
        for patcher in (mock.patch.object(users_store, "db_path", lambda: self.db),
                        mock.patch.object(datasvc, "_now", lambda: NOW)):
            patcher.start()
            self.addCleanup(patcher.stop)
        datasvc.use_nfl_data_dir(self.dir)
        datasvc.use_data_dir(self.empty_ufc)
        self.addCleanup(datasvc.use_nfl_data_dir, None)
        self.addCleanup(datasvc.use_data_dir, None)
        user = users_store.create_user("analyst@example.com", status="active", db=self.db)
        self.token = users_store.issue_invite_token(user.id, db=self.db)
        self.app = FastAPI()
        self.app.include_router(datasvc.router)

    def get(self, path, token=True):
        headers = {"Authorization": f"Bearer {self.token}"} if token is True else (
            {"Authorization": f"Bearer {token}"} if token else {})
        return request(self.app, "GET", path, headers)

    def ok(self, path):
        status, body, _ = self.get(path)
        self.assertEqual(status, 200, body)
        return body

    def expect_error(self, path, status, code):
        got, body, _ = self.get(path)
        self.assertEqual(got, status, body)
        self.assertEqual(body["error"]["code"], code, body)
        return body["error"]

    def pages(self, path, limit):
        """Follow next_cursor to the end; returns the list of pages' data."""
        out, cursor = [], None
        for _ in range(100):
            url = f"{path}{'&' if '?' in path else '?'}limit={limit}" + (f"&cursor={cursor}" if cursor else "")
            body = self.ok(url)
            out.append(body["data"])
            cursor = body["page"]["next_cursor"]
            if not cursor:
                return out
        self.fail("pagination did not end")


class Authentication(NflApiCase):
    def test_every_nfl_route_needs_a_token_and_says_so_in_the_one_error_shape(self):
        for path in ALL_NFL_ROUTES + (f"{NFL}/nothing/here",):
            status, body, _ = self.get(path, token=None)
            self.assertEqual(status, 401, path)
            self.assertEqual(set(body), {"error"}, path)
            self.assertEqual(body["error"]["code"], "unauthorized", path)

    def test_a_wrong_token_is_401_and_a_lapsed_subscription_is_402(self):
        self.assertEqual(self.get(f"{NFL}/games", token="nope")[0], 401)
        from src.appstate import customers
        lapsed = users_store.create_user("lapsed@example.com", status="active", db=self.db)
        token = users_store.issue_invite_token(lapsed.id, db=self.db)
        customers.upsert_subscription(lapsed.id, "sub_lapsed", "canceled", current_period_end="2020-01-01T00:00:00Z", db=self.db)
        status, body, _ = self.get(f"{NFL}/games", token=token)
        self.assertEqual((status, body["error"]["code"]), (402, "subscription_expired"))

    def test_a_valid_token_gets_through_to_every_route(self):
        for path in ALL_NFL_ROUTES:
            status, body, _ = self.get(path)
            self.assertEqual(status, 200, (path, body))

    def test_the_real_app_serves_the_nfl_routes_behind_sign_in(self):
        from api.app import app
        for path in (f"{NFL}/games", f"{NFL}/matchup?a=KC&b=BUF", f"{NFL}/players/x/features"):
            status, body, _ = request(app, "GET", path)
            self.assertEqual((status, body["error"]["code"]), (401, "unauthorized"), path)

    def test_the_tier_the_seam_returns_caps_the_nfl_page_size_too(self):
        small = datasvc.Tier("signed_in", max_limit=2)
        with mock.patch.dict(datasvc.TIERS, {"signed_in": small}):
            body = self.ok(f"{NFL}/games?limit=50")
        self.assertEqual((body["page"]["limit"], body["page"]["count"], body["page"]["total"]), (2, 2, 15))


class TheGamesList(NflApiCase):
    def test_newest_first_by_default_and_oldest_first_on_request(self):
        body = self.ok(f"{NFL}/games")
        ids = [g["game_id"] for g in body["data"]]
        self.assertEqual(len(ids), 15)
        self.assertEqual(ids[0], G["g14"])                              # g14 and g15: g14 kicks off 20 minutes later
        self.assertEqual(ids[-1], G["g01"])
        self.assertEqual(body["page"], {"limit": 50, "count": 15, "total": 15, "next_cursor": None})
        asc = [g["game_id"] for g in self.ok(f"{NFL}/games?order=asc")["data"]]
        self.assertEqual(asc, ids[::-1])

    def test_each_item_is_the_stored_record(self):
        stored = {g["game_id"]: g for g in self.store.games}
        for item in self.ok(f"{NFL}/games")["data"]:
            self.assertEqual(item, stored[item["game_id"]])

    def test_filters(self):
        self.assertEqual(self.ok(f"{NFL}/games?season=2024")["page"]["total"], 2)
        self.assertEqual({g["week"] for g in self.ok(f"{NFL}/games?season=2025&week=5")["data"]}, {5})
        self.assertEqual(self.ok(f"{NFL}/games?season=2025&week=5")["page"]["total"], 2)
        self.assertEqual(self.ok(f"{NFL}/games?status=scheduled")["page"]["total"], 2)
        self.assertEqual(self.ok(f"{NFL}/games?status=final")["page"]["total"], 13)
        self.assertEqual(self.ok(f"{NFL}/games?game_type=REG")["page"]["total"], 15)
        self.assertEqual(self.ok(f"{NFL}/games?game_type=SB")["page"]["total"], 0)

    def test_a_team_filter_takes_a_code_a_nickname_or_an_alias_and_matches_home_or_away(self):
        for value in ("KC", "kc", "Chiefs", "Kansas City Chiefs"):
            body = self.ok(f"{NFL}/games?team={value.replace(' ', '%20')}")
            self.assertEqual(body["page"]["total"], 7, value)
            self.assertTrue(all("KC" in (g["home_team"], g["away_team"]) for g in body["data"]))
        self.assertEqual(self.ok(f"{NFL}/games?team=SEA&season=2025&status=scheduled")["page"]["total"], 1)

    def test_a_valid_team_with_no_game_is_an_empty_list_not_an_error(self):
        body = self.ok(f"{NFL}/games?team=DAL")
        self.assertEqual((body["data"], body["page"]["total"]), ([], 0))

    def test_it_is_paginated_by_keyset_with_no_repeats_or_skips(self):
        pages = self.pages(f"{NFL}/games", 4)
        ids = [g["game_id"] for page in pages for g in page]
        self.assertEqual(len(pages), 4)
        self.assertEqual(ids, [g["game_id"] for g in self.ok(f"{NFL}/games")["data"]])
        self.assertEqual(len(set(ids)), 15)
        asc = [g["game_id"] for page in self.pages(f"{NFL}/games?order=asc", 4) for g in page]
        self.assertEqual(asc, ids[::-1])

    def test_a_row_added_between_pages_does_not_shift_the_next_page(self):
        first = self.ok(f"{NFL}/games?limit=5")
        newest = dict(self.store.game_by_id()[G["g14"]], game_id="2025_09_BUF_KC", week=9, kickoff_utc="2025-11-02T18:00:00Z",
                      gameday="2025-11-02")
        self.store.upsert("games", [newest])                            # arrives after the first page was served
        second = self.ok(f"{NFL}/games?limit=5&cursor={first['page']['next_cursor']}")
        self.assertEqual([g["game_id"] for g in second["data"]],
                         [g["game_id"] for g in self.ok(f"{NFL}/games?limit=100")["data"] if g["game_id"] != "2025_09_BUF_KC"][5:10])
        self.assertNotIn("2025_09_BUF_KC", [g["game_id"] for g in second["data"]])

    def test_a_cursor_from_another_query_or_made_up_is_refused(self):
        cursor = self.ok(f"{NFL}/games?limit=2")["page"]["next_cursor"]
        self.expect_error(f"{NFL}/games?limit=2&season=2025&cursor={cursor}", 422, "invalid_cursor")
        self.expect_error(f"{NFL}/games?order=asc&cursor={cursor}", 422, "invalid_cursor")
        self.expect_error(f"{NFL}/games?cursor=abc", 422, "invalid_cursor")

    def test_bad_parameters_are_422_naming_the_parameter(self):
        for path, param in ((f"{NFL}/games?season=1800", "season"), (f"{NFL}/games?week=0", "week"),
                            (f"{NFL}/games?week=99", "week"), (f"{NFL}/games?limit=0", "limit"),
                            (f"{NFL}/games?team=Zebras", "team"), (f"{NFL}/games?game_type=XYZ", "game_type"),
                            (f"{NFL}/games?status=bogus", "status"), (f"{NFL}/games?order=sideways", "order"),
                            (f"{NFL}/team-games?team=Zebras", "team"), (f"{NFL}/player-games?position_group=ZZ", "position_group"),
                            (f"{NFL}/injuries?week=0", "week")):
            status, body, _ = self.get(path)
            self.assertEqual(status, 422, path)
            self.assertEqual(body["error"]["code"], "invalid_parameter", path)
            self.assertIn(param, body["error"]["message"], path)
            self.assertEqual(body["error"]["details"]["errors"][0]["param"], param, path)


class OneGame(NflApiCase):
    def test_the_game_and_both_teams_rows(self):
        data = self.ok(f"{NFL}/games/{G['g05']}")["data"]
        self.assertEqual(data["game"], self.store.game_by_id()[G["g05"]])
        self.assertEqual({r["team"] for r in data["team_games"]}, {"KC", "SEA"})
        sea = next(r for r in data["team_games"] if r["team"] == "SEA")
        self.assertEqual((sea["points_for"], sea["result"], sea["net_yards"], sea["turnover_margin"]), (24, "W", 340, 1))

    def test_a_scheduled_game_has_rows_with_no_result(self):
        data = self.ok(f"{NFL}/games/{G['g14']}")["data"]
        self.assertEqual({(r["result"], r["has_stats"]) for r in data["team_games"]}, {(None, False)})

    def test_an_unknown_game_is_404(self):
        error = self.expect_error(f"{NFL}/games/2099_01_AAA_BBB", 404, "not_found")
        self.assertIn("2099_01_AAA_BBB", error["message"])


class TeamGames(NflApiCase):
    def test_one_row_per_team_per_game_newest_first(self):
        body = self.ok(f"{NFL}/team-games")
        self.assertEqual(body["page"]["total"], 30)
        stamps = [(r["kickoff_utc"], r["game_id"]) for r in body["data"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_a_teams_season(self):
        body = self.ok(f"{NFL}/team-games?team=Chiefs&season=2025&status=final&order=asc")
        self.assertEqual([r["game_id"] for r in body["data"]], [G["g03"], G["g05"], G["g07"], G["g10"], G["g12"]])
        self.assertEqual([r["result"] for r in body["data"]], ["W", "L", "W", "W", "W"])
        self.assertEqual({r["team"] for r in body["data"]}, {"KC"})

    def test_paginated(self):
        ids = [(r["game_id"], r["team"]) for page in self.pages(f"{NFL}/team-games?team=KC", 3) for r in page]
        self.assertEqual(len(ids), 7)
        self.assertEqual(len(set(ids)), 7)


class PlayerGames(NflApiCase):
    def test_a_player_by_id_newest_first(self):
        body = self.ok(f"{NFL}/player-games?player=00-KCWR1")
        self.assertEqual([r["game_id"] for r in body["data"]], [G["g12"], G["g10"], G["g05"], G["g03"]])
        self.assertEqual(body["data"][0]["targets"], 9)

    def test_a_player_by_name(self):
        body = self.ok(f"{NFL}/player-games?player=kay%20see")           # an exact name beats the longer ones that contain it
        self.assertEqual({r["player_id"] for r in body["data"]}, {"00-KCWR1"})

    def test_two_equally_good_name_matches_are_a_409_naming_both(self):
        error = self.expect_error(f"{NFL}/player-games?player=see", 409, "ambiguous_name")
        names = {c["name"] for c in error["details"]["candidates"]}
        self.assertTrue({"Kay See", "Kay See Quarterback"} <= names)
        self.assertEqual(error["details"]["param"], "player")

    def test_an_unknown_player_is_404(self):
        self.expect_error(f"{NFL}/player-games?player=zzzzzz", 404, "not_found")

    def test_filters(self):
        self.assertEqual(self.ok(f"{NFL}/player-games?team=SEA")["page"]["total"], 2)             # the traded back, in weeks 4 and 5
        self.assertEqual(self.ok(f"{NFL}/player-games?game_id={G['g05']}")["page"]["total"], 3)   # WR, QB, TE of week 2 at SEA
        self.assertEqual(self.ok(f"{NFL}/player-games?position_group=QB")["page"]["total"], 5)
        self.assertEqual(self.ok(f"{NFL}/player-games?season=2024")["page"]["total"], 0)
        self.assertEqual(self.ok(f"{NFL}/player-games?week=1")["page"]["total"], 4)               # WR, QB, TE of KC and the back for BUF
        self.assertEqual(self.ok(f"{NFL}/player-games")["page"]["total"], 15)

    def test_paginated(self):
        ids = [(r["game_id"], r["player_id"]) for page in self.pages(f"{NFL}/player-games", 4) for r in page]
        self.assertEqual((len(ids), len(set(ids))), (15, 15))


class Injuries(NflApiCase):
    def test_all_rows_newest_first_and_the_stored_shape(self):
        body = self.ok(f"{NFL}/injuries")
        self.assertEqual(body["page"]["total"], 8)
        self.assertEqual(body["data"][0]["game_id"], G["g12"])
        self.assertEqual(set(body["data"][0]), set(self.store.injuries[0]))

    def test_filters(self):
        self.assertEqual(self.ok(f"{NFL}/injuries?game_id={G['g10']}")["page"]["total"], 6)
        self.assertEqual(self.ok(f"{NFL}/injuries?team=KC&week=5")["page"]["total"], 4)
        self.assertEqual(self.ok(f"{NFL}/injuries?report_status=out")["page"]["total"], 3)
        self.assertEqual(self.ok(f"{NFL}/injuries?report_status=OUT")["page"]["total"], 3)
        self.assertEqual(self.ok(f"{NFL}/injuries?report_status=doubtful")["page"]["total"], 1)
        self.assertEqual(self.ok(f"{NFL}/injuries?position_group=WR")["page"]["total"], 3)
        self.assertEqual(self.ok(f"{NFL}/injuries?player_id=00-KCWR1")["page"]["total"], 2)
        self.assertEqual(self.ok(f"{NFL}/injuries?season=2024")["page"]["total"], 0)

    def test_paginated(self):
        ids = [(r["game_id"], r["player_id"]) for page in self.pages(f"{NFL}/injuries", 3) for r in page]
        self.assertEqual((len(ids), len(set(ids))), (8, 8))


class TheMatchupRoute(NflApiCase):
    def test_by_game_id(self):
        data = self.ok(f"{NFL}/matchup?game_id={G['g14']}")["data"]
        self.assertEqual(data["game"]["game_id"], G["g14"])
        self.assertEqual(data["resolved"], {"game_id": G["g14"], "matched_by": "game_id"})
        direct = nfl_matchup.matchup(self.store, G["g14"], None, now=NOW)
        for key in ("home", "away", "differentials", "market", "head_to_head", "missing", "as_of"):
            self.assertEqual(data[key], json.loads(json.dumps(direct[key])), key)

    def test_by_two_teams_in_either_order_picks_the_next_game_between_them(self):
        for query in ("a=KC&b=BUF", "a=Bills&b=chiefs"):
            data = self.ok(f"{NFL}/matchup?{query}")["data"]
            self.assertEqual(data["game"]["game_id"], G["g14"], query)
            self.assertEqual(data["resolved"]["matched_by"], "teams")

    def test_a_season_and_week_pick_the_game_and_as_of_may_be_earlier(self):
        data = self.ok(f"{NFL}/matchup?a=KC&b=BUF&season=2025&week=1")["data"]
        self.assertEqual((data["game"]["game_id"], data["as_of_source"]), (G["g03"], "kickoff"))
        data = self.ok(f"{NFL}/matchup?game_id={G['g14']}&as_of=2025-10-01")["data"]
        self.assertEqual((data["as_of"], data["as_of_source"]), ("2025-10-01T00:00:00Z", "argument"))

    def test_the_sheet_carries_no_score_for_its_own_game(self):
        data = self.ok(f"{NFL}/matchup?game_id={G['g05']}")["data"]
        self.assertNotIn("home_score", data["game"])

    def test_errors(self):
        self.assertEqual(self.expect_error(f"{NFL}/matchup", 422, "invalid_parameter")["details"]["errors"][0]["param"], "game_id")
        self.expect_error(f"{NFL}/matchup?a=KC", 422, "invalid_parameter")
        self.expect_error(f"{NFL}/matchup?game_id=2099_01_AAA_BBB", 404, "not_found")
        self.expect_error(f"{NFL}/matchup?a=KC&b=ZZZ", 404, "not_found")
        same = self.expect_error(f"{NFL}/matchup?a=KC&b=Chiefs", 422, "invalid_parameter")
        self.assertEqual(same["details"]["errors"][0]["param"], "b")
        self.expect_error(f"{NFL}/matchup?a=KC&b=BUF&season=2024&week=1", 404, "not_found")
        late = self.expect_error(f"{NFL}/matchup?game_id={G['g05']}&as_of=2030-01-01", 422, "invalid_parameter")
        self.assertEqual(late["details"]["errors"][0]["param"], "as_of")
        self.assertIn("after the kickoff", late["message"])
        self.expect_error(f"{NFL}/matchup?game_id={G['g05']}&as_of=whenever", 422, "invalid_parameter")


class FeatureRoutes(NflApiCase):
    def test_a_teams_features_are_the_features_module_output(self):
        data = self.ok(f"{NFL}/teams/KC/features?as_of={KICK['g14']}")["data"]
        self.assertEqual(data, json.loads(json.dumps(nfl_features.team_features_as_of(self.store, "KC", KICK["g14"]))))
        self.assertEqual(data["form"]["last_3"]["points_for_per_game"], 27)

    def test_the_default_as_of_is_now_and_a_nickname_works(self):
        data = self.ok(f"{NFL}/teams/chiefs/features")["data"]
        self.assertEqual((data["team"], data["as_of"]), ("KC", "2025-10-20T12:00:00Z"))
        self.assertEqual(self.ok(f"{NFL}/teams/KC/features?season=2024&as_of={KICK['g14']}")["data"]["season"], 2024)

    def test_errors(self):
        self.expect_error(f"{NFL}/teams/ZZZ/features", 404, "not_found")
        self.expect_error(f"{NFL}/teams/KC/features?as_of=whenever", 422, "invalid_parameter")

    def test_a_players_features_by_id_and_by_name(self):
        data = self.ok(f"{NFL}/players/00-KCWR1/features?as_of={KICK['g14']}")["data"]
        direct = json.loads(json.dumps(nfl_features.player_features_as_of(self.store, "00-KCWR1", KICK["g14"])))
        self.assertEqual({k: v for k, v in data.items() if k != "resolved"}, direct)
        self.assertEqual(data["resolved"], {"query": "00-KCWR1", "player_id": "00-KCWR1", "matched_by": "id"})
        # (the ASGI scope's path is already percent-decoded, as a real server hands it over, so the space is a space)
        by_name = self.ok(f"{NFL}/players/Kay See/features?as_of={KICK['g14']}")["data"]
        self.assertEqual((by_name["player_id"], by_name["resolved"]["matched_by"]), ("00-KCWR1", "name"))
        self.assertEqual(data["last_3"]["stats"]["targets"]["total"], 20)

    def test_player_errors(self):
        self.expect_error(f"{NFL}/players/zzzzzz/features", 404, "not_found")
        self.expect_error(f"{NFL}/players/see/features", 409, "ambiguous_name")
        self.expect_error(f"{NFL}/players/00-KCWR1/features?as_of=whenever", 422, "invalid_parameter")


class Status(NflApiCase):
    def nfl(self):
        return self.ok(f"{PREFIX}/status")["data"]["nfl"]

    def test_the_nfl_datasets_are_listed_with_counts_newest_and_age(self):
        nfl = self.nfl()
        ds = nfl["datasets"]
        self.assertEqual(set(ds), set(nfl_store.FILES))
        self.assertEqual({k: ds[k]["records"] for k in ds}, {"games": 15, "team_games": 30, "player_games": 15, "injuries": 8})
        self.assertTrue(all(d["present"] and d["source"] == "manifest" for d in ds.values()))
        self.assertEqual(ds["games"]["newest"], "2025-10-19T13:30:00Z")
        self.assertEqual(ds["games"]["newest_field"], "kickoff_utc")
        self.assertEqual(ds["games"]["age_seconds"], 22 * 3600 + 30 * 60)          # newest game played 13:30 Oct 19, now 12:00 Oct 20
        self.assertEqual(ds["player_games"]["newest"], "2025-10-12T13:30:00Z")
        self.assertEqual(ds["injuries"]["newest_field"], "fetched_utc")
        self.assertIn("CC BY 4.0", nfl["attribution"])
        self.assertEqual(nfl["coverage"], {"seasons": [2024, 2025], "player_games_since": 2025})
        self.assertIsNotNone(nfl["manifest_generated_utc"])

    def test_a_booked_game_never_counts_as_the_newest(self):
        extra = dict(self.store.game_by_id()[G["g14"]], game_id="2026_01_BUF_KC", season=2026, week=1,
                     kickoff_utc="2026-09-10T00:20:00Z", status="scheduled")
        self.store.upsert("games", [extra])
        self.assertEqual(self.nfl()["datasets"]["games"]["newest"], "2025-10-19T13:30:00Z")

    def test_the_ufc_half_of_status_is_untouched_by_the_nfl_half(self):
        data = self.ok(f"{PREFIX}/status")["data"]
        from src.datasvc.ufc.store import FILES as UFC_FILES
        self.assertEqual(set(data["datasets"]), set(UFC_FILES))
        self.assertTrue(all(d["present"] is False for d in data["datasets"].values()))
        # 2026-10-04: the MLB datasets joined /status as one more top-level key (the key-set pin moves with it).
        self.assertEqual(set(data), {"generated_utc", "datasets", "manifest_generated_utc", "service", "note", "nfl",
                                     "mlb"})

    def test_no_nfl_data_at_all_is_absent_not_an_error(self):
        datasvc.use_nfl_data_dir(Path(self._tmp.name) / "nowhere")
        nfl = self.nfl()
        self.assertTrue(all(d["present"] is False and d["records"] == 0 for d in nfl["datasets"].values()))
        self.assertIsNone(nfl["coverage"])

    def test_a_corrupt_nfl_file_is_reported_in_its_own_entry_and_never_breaks_the_status(self):
        (self.dir / "player_games.jsonl").write_text("garbage\n", encoding="utf-8")
        (self.dir / "MANIFEST.json").unlink()                           # force the scan, which meets the bad line
        with contextlib.redirect_stderr(io.StringIO()):
            data = self.ok(f"{PREFIX}/status")["data"]
        bad = data["nfl"]["datasets"]["player_games"]
        self.assertEqual((bad["present"], bad["readable"], bad["records"]), (True, False, None))
        self.assertEqual(data["nfl"]["datasets"]["games"]["records"], 15)
        self.assertEqual(set(data["datasets"]), set(__import__("src.datasvc.ufc.store", fromlist=["FILES"]).FILES))


class LoadingAndErrors(NflApiCase):
    def touch(self, name):
        path = self.dir / nfl_store.FILES[name]
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    def test_the_files_are_read_once_not_once_per_request(self):
        reads = []
        real = jsonl.read_jsonl

        def counting(path):
            reads.append(Path(path).name)
            return real(path)

        with mock.patch.object(jsonl, "read_jsonl", counting):
            for _ in range(5):
                for path in ALL_NFL_ROUTES[:-1]:
                    self.ok(path)
                self.ok(f"{NFL}/matchup?a=KC&b=BUF")
        self.assertEqual(sorted(reads), sorted(set(reads)), "a file was read twice")
        self.assertEqual(set(reads) <= set(nfl_store.FILES.values()), True)
        self.assertEqual(datasvc.nfl_holder.reloads, 1)

    def test_a_dataset_a_route_never_touches_is_never_read(self):
        reads = []
        real = jsonl.read_jsonl
        with mock.patch.object(jsonl, "read_jsonl", lambda p: (reads.append(Path(p).name), real(p))[1]):
            self.ok(f"{NFL}/games")
            self.ok(f"{NFL}/games/{G['g05']}")
        self.assertEqual(sorted(reads), ["games.jsonl", "team_games.jsonl"])                 # no players, no injuries

    def test_a_changed_file_swaps_in_a_fresh_store_and_the_new_data_shows(self):
        self.assertEqual(self.ok(f"{NFL}/games?status=scheduled")["page"]["total"], 2)
        self.assertEqual(datasvc.nfl_holder.reloads, 1)
        for _ in range(3):
            self.ok(f"{NFL}/games")
        self.assertEqual(datasvc.nfl_holder.reloads, 1)
        extra = dict(self.store.game_by_id()[G["g14"]], game_id="2025_09_BUF_KC", week=9, kickoff_utc="2025-11-02T18:00:00Z")
        self.store.upsert("games", [extra])
        self.assertEqual(self.ok(f"{NFL}/games?status=scheduled")["page"]["total"], 3)
        self.assertEqual(datasvc.nfl_holder.reloads, 2)
        self.touch("injuries")
        self.ok(f"{NFL}/games")
        self.assertEqual(datasvc.nfl_holder.reloads, 3)

    def test_the_nfl_holder_never_disturbs_the_ufc_one(self):
        self.ok(f"{NFL}/games")
        self.assertEqual(datasvc.holder.reloads, 0)
        self.assertEqual(self.ok(f"{PREFIX}/ufc/events")["data"], [])                       # the UFC routes still answer

    def test_a_corrupt_dataset_is_a_503_for_its_routes_only_and_is_not_re_parsed_per_request(self):
        (self.dir / "injuries.jsonl").write_text('{"game_id": "x", "player_id": "y"}\nnot json\n', encoding="utf-8")
        reads = []
        real = jsonl.read_jsonl
        with mock.patch.object(jsonl, "read_jsonl", lambda p: (reads.append(Path(p).name), real(p))[1]), \
                contextlib.redirect_stderr(io.StringIO()):
            statuses = [self.get(f"{NFL}/injuries")[0] for _ in range(4)]
            matchup = self.get(f"{NFL}/matchup?game_id={G['g14']}")
            games = self.get(f"{NFL}/games")
        self.assertEqual(statuses, [503] * 4)
        self.assertEqual(matchup[0], 503)                                                    # the sheet needs injuries
        self.assertEqual(matchup[1]["error"]["code"], "data_unavailable")
        self.assertEqual(games[0], 200)                                                      # other datasets still serve
        self.assertEqual(reads.count("injuries.jsonl"), 1)

    def test_a_wrong_method_is_405_with_allow_and_an_unknown_path_is_404(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, body, headers = request(self.app, method, f"{NFL}/games", {"Authorization": f"Bearer {self.token}"})
            self.assertEqual(status, 405, method)
            self.assertEqual(headers.get("allow"), "GET", method)
            self.assertEqual(body["error"]["code"], "method_not_allowed", method)
        self.expect_error(f"{NFL}/nope", 404, "not_found")
        self.expect_error(f"{NFL}/games/x/y/z", 404, "not_found")

    def test_an_unhandled_bug_is_a_500_with_an_error_id_and_no_traceback(self):
        with mock.patch.object(nfl_matchup, "matchup", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(io.StringIO()) as log:
            status, body, _ = self.get(f"{NFL}/matchup?game_id={G['g14']}")
        self.assertEqual((status, body["error"]["code"]), (500, "internal_error"))
        self.assertIn("error_id=", body["error"]["message"])
        self.assertNotIn("Traceback", json.dumps(body))
        self.assertNotIn("boom", json.dumps(body))
        self.assertIn("boom", log.getvalue())

    def test_concurrent_first_requests_read_each_file_once(self):
        counter = {"n": {}}
        real = jsonl.read_jsonl

        def slow(path):
            counter["n"][Path(path).name] = counter["n"].get(Path(path).name, 0) + 1
            time.sleep(0.05)
            return real(path)

        errors = []

        def worker():
            try:
                datasvc.nfl_holder.store().games_by_team()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with mock.patch.object(jsonl, "read_jsonl", slow):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(counter["n"], {"games.jsonl": 1})
        self.assertEqual(datasvc.nfl_holder.reloads, 1)

    def test_the_default_data_directory_is_the_nfl_stores(self):
        datasvc.use_nfl_data_dir(None)
        self.assertEqual(datasvc.nfl_holder.root, nfl_store.DEFAULT_DIR)
        self.assertEqual(nfl_store.DEFAULT_DIR.relative_to(Path(__file__).resolve().parents[1]).as_posix(), "data/datasvc/nfl")


if __name__ == "__main__":
    unittest.main()
