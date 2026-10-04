"""GET /data/v1/mlb/...: MLB through the data API, and the door as a whole.

FastAPI is an api/-only dependency, so every test here is `skipUnless(HAS_FASTAPI)`. The MLB service is
injected (`datasvc.use_mlb_service`) with a counting schedule fake and a loader over the shared analyst
fixtures; auth is the real `require_paid_access`, as in tests/test_datasvc_ufc_api.py.

Also here: the route-wide acceptance checks that belong to no one sport. Every route the router has is
enumerated FROM THE ROUTER (so a route added later is covered without anyone remembering), and an
anonymous caller is refused on every one of them in the one error shape.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.analyst import packet as packet_mod
from src.datasvc import client as core
from src.datasvc.client import DataClient
from src.datasvc.mlb import service as svc
from tests import analyst_fixtures as F
from tests.test_datasvc_mlb_service import schedule_game
from tests.test_datasvc_ufc_api import HAS_FASTAPI, ApiCase, request

if HAS_FASTAPI:
    from api import datasvc

DATE = F.DATE
MLB = "/data/v1/mlb"


def sample_path(route_path: str) -> str:
    """A concrete URL for a route template: every {parameter} becomes a plain value."""
    return re.sub(r"\{[^}]+\}", "x", route_path).replace(":path", "")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MlbApiCase(ApiCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(datasvc, "_now", lambda: F.NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.games = [schedule_game()]
        self.fetches = []
        self.fetch_error = None
        self.root = Path(self._tmp.name) / "mlb_data"
        self.root.mkdir()

        def fetch(date):
            self.fetches.append(date)
            if self.fetch_error:
                raise RuntimeError(self.fetch_error)
            return [dict(g) for g in self.games]

        def load(date, games, now):
            items = []
            for g in games:
                payload = F.payload(g["state"])
                payload["advanced"]["game"].update(game_pk=g["game_pk"], away_team=g["away_team"],
                                                   home_team=g["home_team"])
                items.append({"payload": payload, "multibook_rows": F.multibook_rows(),
                              "team_total_rows": F.team_total_rows(), "batter_prop_rows": F.batter_prop_rows(),
                              "pitcher_prop_rows": F.pitcher_prop_rows(), "prop_board": F.prop_board(),
                              "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
                              "section_as_of": {"teams": "2026-10-02", "starters": "2026-10-02"}})
            return items

        self.service = svc.MlbService(fetch_games=fetch, loader=load, stores=(), clock=lambda: F.NOW,
                                      config_loader=lambda: dict(F.CFG), data_root=self.root)
        datasvc.use_mlb_service(self.service)
        self.addCleanup(datasvc.use_mlb_service, None)


class EveryRoute(MlbApiCase):
    def routes(self):
        return [r for r in datasvc.router.routes if getattr(r, "methods", None)]

    def test_the_router_has_every_sports_routes_and_the_enumeration_sees_them(self):
        paths = {r.path for r in self.routes()}
        for needle in ("/data/v1/status", "/data/v1/ufc/events", "/data/v1/nfl/games", "/data/v1/mlb/games",
                       "/data/v1/mlb/games/{date}/{away}/{home}/packet"):
            self.assertIn(needle, paths)
        self.assertGreaterEqual(len(paths), 20)

    def test_anonymous_callers_are_refused_on_every_route_in_the_one_error_shape(self):
        for route in self.routes():
            url = sample_path(route.path)
            for token in (None, "not-a-real-token"):
                status, body, _ = self.get(url, token=token)
                self.assertEqual(status, 401, (url, token))
                self.assertEqual(set(body), {"error"}, url)
                self.assertEqual(body["error"]["code"], "unauthorized", url)
                self.assertTrue(body["error"]["message"], url)
        self.assertEqual(self.fetches, [])                                   # refused before any upstream request

    def test_the_real_app_mounts_the_mlb_routes_behind_sign_in_too(self):
        from api.app import app
        for path in (f"{MLB}/games?date={DATE}", f"{MLB}/games/{DATE}/NYY/TB/packet"):
            status, body, _ = request(app, "GET", path)
            self.assertEqual(status, 401, path)
            self.assertEqual(body["error"]["code"], "unauthorized", path)

    def test_a_lapsed_subscription_is_402_on_the_mlb_routes_as_on_the_others(self):
        from src.appstate import customers
        from src.appstate import users as users_store
        lapsed = users_store.create_user("lapsed@example.com", status="active", db=self.db)
        token = users_store.issue_invite_token(lapsed.id, db=self.db)
        customers.upsert_subscription(lapsed.id, "sub_lapsed", "canceled",
                                      current_period_end="2020-01-01T00:00:00Z", db=self.db)
        status, body, _ = self.get(f"{MLB}/games?date={DATE}", token=token)
        self.assertEqual((status, body["error"]["code"]), (402, "subscription_expired"))

    def test_every_documented_route_is_get_only(self):
        for path, methods in self.app.openapi()["paths"].items():
            self.assertEqual(list(methods), ["get"], path)


class MlbGames(MlbApiCase):
    def test_a_days_games_with_results_and_the_meta(self):
        self.games = [schedule_game(pk=1, state="final"), schedule_game(pk=2, away="BOS", home="BAL")]
        body = self.ok(f"{MLB}/games?date={DATE}")
        self.assertEqual([g["game_pk"] for g in body["data"]], [1, 2])
        self.assertEqual(body["data"][0]["result"]["winner"], "NYY")
        self.assertIsNone(body["data"][1]["result"])
        self.assertEqual(body["page"]["total"], 2)
        meta = body["meta"]
        self.assertEqual(meta["observed_utc"], "2026-10-03T18:00:00Z")
        self.assertEqual(meta["sources"][0]["basis"], core.RECONSTRUCTED)
        self.assertIn("retroactive", meta["sources"][0]["basis_note"])

    def test_paging_follows_the_cursor(self):
        self.games = [schedule_game(pk=n, start_time_utc=f"2026-10-03T1{n}:00:00Z") for n in range(1, 5)]
        pages = self.pages(f"{MLB}/games?date={DATE}", 3)
        self.assertEqual([len(p) for p in pages], [3, 1])

    def test_bad_and_missing_dates_are_422_naming_the_parameter(self):
        for path in (f"{MLB}/games", f"{MLB}/games?date=2026-13-40", f"{MLB}/games?date=yesterday!!"):
            status, body, _ = self.get(path)
            self.assertEqual(status, 422, path)
            self.assertEqual(body["error"]["code"], "invalid_parameter", path)
            self.assertIn("date", body["error"]["message"], path)
        self.assertEqual(self.fetches, [])

    def test_an_unreachable_schedule_is_a_503_in_the_one_error_shape(self):
        self.fetch_error = "provider down"
        error = self.expect_error(f"{MLB}/games?date={DATE}", 503, "data_unavailable")
        self.assertIn("provider down", error["message"])
        self.assertTrue(error["details"]["missing"])

    def test_an_off_day_is_a_200_with_an_empty_list_that_says_why(self):
        self.games = []
        body = self.ok(f"{MLB}/games?date={DATE}")
        self.assertEqual(body["data"], [])
        self.assertEqual(body["meta"]["missing"][0]["item"], "games")


class MlbPacket(MlbApiCase):
    def test_the_packet_is_the_analysts_and_carries_its_meta(self):
        body = self.ok(f"{MLB}/games/{DATE}/NYY/TB/packet")
        packet, meta = body["data"], body["meta"]
        self.assertEqual(packet["packet_version"], packet_mod.PACKET_VERSION)
        self.assertEqual(meta["packet_hash"], packet_mod.packet_hash(packet))
        self.assertEqual(packet["built_at"], "2026-10-03T18:00:00Z")
        self.assertIn("moneyline", packet["markets"])                        # the quotes captured before built_at
        self.assertEqual(meta["ids"]["game_pk"], 849835)
        self.assertEqual(meta["missing"], packet["missing"])
        self.assertTrue(meta["data_version"].startswith("dv1-"))

    def test_a_repeat_read_is_served_from_the_snapshot_with_the_same_times(self):
        first = self.ok(f"{MLB}/games/{DATE}/NYY/TB/packet")
        self.service.counters["packet_builds"] = 0
        for _ in range(5):
            again = self.ok(f"{MLB}/games/{DATE}/NYY/TB/packet")
        self.assertEqual(again, first)
        self.assertEqual(self.service.counters["packet_builds"], 0)
        self.assertEqual(len(self.fetches), 1)

    def test_unknown_game_404_doubleheader_409_unreachable_503_bad_date_422(self):
        self.expect_error(f"{MLB}/games/{DATE}/LAD/SF/packet", 404, "not_found")
        # each case uses its own date: the service holds a date's schedule for its TTL, as it should
        self.games = [schedule_game(pk=1), schedule_game(pk=2, game_number=2)]
        self.expect_error(f"{MLB}/games/2026-10-04/NYY/TB/packet", 409, "ambiguous_game")
        self.expect_error(f"{MLB}/games/not-a-date/NYY/TB/packet", 422, "invalid_parameter")
        self.fetch_error = "provider down"
        self.expect_error(f"{MLB}/games/2026-10-05/NYY/TB/packet", 503, "data_unavailable")

    def test_coverage_says_when_a_store_is_absent_or_old_and_never_calls_it_fresh(self):
        meta = self.ok(f"{MLB}/games/{DATE}/NYY/TB/packet")["meta"]
        self.assertEqual(meta["coverage"]["results"], {"through": None, "stale": True})   # no results store at all
        self.assertTrue(all(c["stale"] for c in meta["coverage"].values()))

    def test_serving_a_packet_publishes_nothing(self):
        before = sorted(p.name for p in Path(self._tmp.name).rglob("*"))
        self.ok(f"{MLB}/games/{DATE}/NYY/TB/packet")
        self.assertEqual(sorted(p.name for p in Path(self._tmp.name).rglob("*")), before)


class StatusHasMlb(MlbApiCase):
    def test_status_lists_the_mlb_datasets_from_the_freshness_module_with_their_basis(self):
        hist = self.root / "historical"
        hist.mkdir()
        (hist / "standings.jsonl").write_text('{"date": "2026-10-02", "team": "NYY"}\n', encoding="utf-8")
        mlb = self.ok("/data/v1/status")["data"]["mlb"]
        self.assertEqual(mlb["datasets"]["standings"]["through"], "2026-10-02")
        self.assertFalse(mlb["datasets"]["standings"]["stale"])
        self.assertEqual(mlb["datasets"]["standings"]["basis"], core.OBSERVED)
        self.assertFalse(mlb["datasets"]["mlb_results"]["present"])           # absent is said, not fresh
        self.assertTrue(mlb["datasets"]["mlb_results"]["stale"])
        self.assertEqual(mlb["datasets"]["mlb_results"]["basis"], core.RECONSTRUCTED)
        self.assertIn("mlb_results", mlb["core_stale"])

    def test_a_broken_mlb_half_never_turns_status_into_an_error(self):
        with mock.patch.object(self.service, "status", side_effect=RuntimeError("boom")):
            data = self.ok("/data/v1/status")["data"]
        self.assertFalse(data["mlb"]["readable"])
        self.assertIn("datasets", data)                                       # the UFC half is intact


class HttpAndClientAgree(MlbApiCase):
    def test_the_ufc_matchup_route_serves_what_the_client_builds(self):
        body = self.ok(f"/data/v1/ufc/matchup?a=101&b=102")
        out = DataClient(ufc=datasvc.holder, nfl=datasvc.nfl_holder, mlb=self.service, clock=lambda: F.NOW).matchup(
            "ufc", a="101", b="102")
        self.assertEqual(body["data"], out["data"])
        self.assertEqual(body["meta"]["data_version"], out["meta"]["data_version"])
        self.assertEqual(body["meta"]["ids"]["bout_id"], "9101")

    def test_the_route_and_the_client_share_the_one_store_of_the_process(self):
        self.assertIs(datasvc.holder, core.holder)
        self.assertIs(datasvc.nfl_holder, core.nfl_holder)
        self.ok(f"/data/v1/ufc/events")
        reloads = datasvc.holder.reloads
        DataClient(mlb=self.service).schedule("ufc")
        self.assertEqual(datasvc.holder.reloads, reloads)                     # the client did not open a second store


if __name__ == "__main__":
    unittest.main()
