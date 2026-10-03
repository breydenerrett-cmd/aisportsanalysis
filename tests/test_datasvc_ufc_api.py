"""api/datasvc.py: GET /data/v1/... over the synthetic world of the features tests.

FastAPI is an api/-only dependency and the Linux CI has none, so every test here is
`skipUnless(HAS_FASTAPI)`. Starlette's TestClient needs an HTTP client package this repo
does not depend on, so `_request` speaks ASGI to the app directly, as
tests/test_api_adversarial.py does. Auth is real: a user and an invite token are made in a
throwaway sqlite file that `users_store.db_path` is pointed at, so a request either carries
a token the real `require_paid_access` accepts or it does not.

The data is injected: `datasvc.use_data_dir` points the API at a temporary directory built
by `build_store`, and `datasvc._now` is pinned, so no test depends on the machine, the real
files or the clock.
"""

from __future__ import annotations

import asyncio
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
from types import SimpleNamespace
from unittest import mock

try:
    from fastapi import FastAPI
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.datasvc import store as jsonl
from src.datasvc.ufc import features, matchup
from src.datasvc.ufc.store import FILES
from tests.test_datasvc_ufc_features import STATS, build_store, odds_row

if HAS_FASTAPI:
    from api import datasvc

NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
PREFIX = "/data/v1"
UFC = "/data/v1/ufc"


def request(app, method, path, headers=None):
    """One request through the ASGI app: (status, decoded body, response headers)."""
    path, _, query = path.partition("?")
    raw_headers = [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in (headers or {}).items()]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path,
             "raw_path": path.encode("utf-8"), "root_path": "", "scheme": "http",
             "query_string": query.encode("utf-8"), "headers": raw_headers,
             "client": ("127.0.0.1", 5000), "server": ("testserver", 80)}
    captured, chunks = {}, []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
            captured["headers"] = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    asyncio.run(app(scope, receive, send))
    raw = b"".join(chunks)
    try:
        body = json.loads(raw)
    except ValueError:
        body = raw.decode("utf-8", "replace")
    return captured.get("status"), body, captured.get("headers", {})


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ApiCase(unittest.TestCase):
    """A fresh data directory, users database, app and pinned clock for every test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "ufc"
        self.store = build_store(self.dir)
        self.db = Path(self._tmp.name) / "app.db"
        for patcher in (mock.patch.object(users_store, "db_path", lambda: self.db),
                        mock.patch.object(datasvc, "_now", lambda: NOW)):
            patcher.start()
            self.addCleanup(patcher.stop)
        datasvc.use_data_dir(self.dir)
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


# -- auth and the seam -------------------------------------------------------------------------------

ALL_ROUTES = (f"{PREFIX}/status", f"{UFC}/events", f"{UFC}/events/7013", f"{UFC}/bouts/9101", f"{UFC}/fighters",
              f"{UFC}/fighters?search=archer", f"{UFC}/fighters/101", f"{UFC}/fighters/101/fights",
              f"{UFC}/fighters/101/features", f"{UFC}/matchup?a=101&b=102", f"{UFC}/upcoming",
              f"{PREFIX}/nothing/here")


class Authentication(ApiCase):
    def test_every_route_needs_a_token_and_says_so_in_the_one_error_shape(self):
        for path in ALL_ROUTES:
            status, body, _ = self.get(path, token=None)
            self.assertEqual(status, 401, path)
            self.assertEqual(set(body), {"error"}, path)
            self.assertEqual(body["error"]["code"], "unauthorized", path)
            self.assertTrue(body["error"]["message"], path)

    def test_a_wrong_token_and_a_suspended_account_are_401(self):
        status, body, _ = self.get(f"{PREFIX}/status", token="not-a-real-token")
        self.assertEqual((status, body["error"]["code"]), (401, "unauthorized"))
        suspended = users_store.create_user("gone@example.com", status="suspended", db=self.db)
        token = users_store.issue_invite_token(suspended.id, db=self.db)
        status, body, _ = self.get(f"{PREFIX}/status", token=token)
        self.assertEqual((status, body["error"]["code"]), (401, "unauthorized"))

    def test_a_lapsed_subscription_is_402_in_the_same_error_shape_and_a_live_one_is_not(self):
        """Same paid gate as the product's other signed-in content routes (api.auth.require_paid_access)."""
        from src.appstate import customers
        lapsed = users_store.create_user("lapsed@example.com", status="active", db=self.db)
        token = users_store.issue_invite_token(lapsed.id, db=self.db)
        customers.upsert_subscription(lapsed.id, "sub_lapsed", "canceled",
                                      current_period_end="2020-01-01T00:00:00Z", db=self.db)
        status, body, _ = self.get(f"{UFC}/events", token=token)
        self.assertEqual(status, 402)
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], "subscription_expired")
        live = users_store.create_user("live@example.com", status="active", db=self.db)
        live_token = users_store.issue_invite_token(live.id, db=self.db)
        customers.upsert_subscription(live.id, "sub_live", "active", db=self.db)
        self.assertEqual(self.get(f"{UFC}/events", token=live_token)[0], 200)

    def test_a_valid_token_gets_through_to_every_route(self):
        for path in ALL_ROUTES[:-1]:
            status, body, _ = self.get(path)
            self.assertEqual(status, 200, (path, body))

    def test_the_router_carries_the_seam_dependency_itself(self):
        """Mounted anywhere, the router is gated: nothing depends on the mount remembering to add auth."""
        self.assertIn(datasvc.data_access, [d.dependency for d in datasvc.router.dependencies])

    def test_data_access_returns_who_and_which_tier_and_remembers_it_on_the_request(self):
        fake_request = SimpleNamespace(state=SimpleNamespace())
        caller = datasvc.data_access(fake_request, SimpleNamespace(id=7))
        self.assertEqual((caller.user_id, caller.tier.name, caller.via), (7, "signed_in", "bearer_token"))
        self.assertIs(fake_request.state.data_caller, caller)

    def test_the_tier_the_seam_returns_is_what_caps_the_page_size(self):
        """The one thing the routes read from the caller is the tier's max_limit, so keys can raise or lower it."""
        small = datasvc.Tier("signed_in", max_limit=2)
        with mock.patch.dict(datasvc.TIERS, {"signed_in": small}):
            body = self.ok(f"{UFC}/events?limit=50")
        self.assertEqual((body["page"]["limit"], body["page"]["count"]), (2, 2))

    def test_the_real_app_mounts_the_router_behind_sign_in(self):
        from api.app import app
        for path in (f"{PREFIX}/status", f"{UFC}/events", f"{UFC}/matchup?a=1&b=2", f"{PREFIX}/no/such/thing"):
            status, body, _ = request(app, "GET", path)
            self.assertEqual(status, 401, path)
            self.assertEqual(body["error"]["code"], "unauthorized", path)        # the data API's own error shape


class Surface(ApiCase):
    def test_the_openapi_schema_builds_and_lists_exactly_the_documented_endpoints(self):
        """FastAPI builds /openapi.json for the whole product from every route, so a signature it
        cannot describe would break the docs endpoint of the entire app, not just this router."""
        paths = self.app.openapi()["paths"]
        self.assertEqual(set(paths), {
            f"{PREFIX}/status", f"{UFC}/events", f"{UFC}/events/{{event_id}}", f"{UFC}/bouts/{{bout_id}}",
            f"{UFC}/fighters", f"{UFC}/fighters/{{fighter_id}}", f"{UFC}/fighters/{{fighter_id}}/fights",
            f"{UFC}/fighters/{{fighter_id}}/features", f"{UFC}/matchup", f"{UFC}/upcoming"})
        for path, methods in paths.items():
            self.assertEqual(list(methods), ["get"], path)          # read-only: nothing here writes


# -- the one error shape ------------------------------------------------------------------------------

class ErrorShape(ApiCase):
    def assert_shape(self, body):
        self.assertEqual(set(body), {"error"})
        self.assertTrue(set(body["error"]) <= {"code", "message", "details"}, body)
        self.assertIsInstance(body["error"]["code"], str)
        self.assertIsInstance(body["error"]["message"], str)

    def test_not_found_in_every_flavour(self):
        for path in (f"{UFC}/events/nope", f"{UFC}/bouts/nope", f"{UFC}/fighters/nope", f"{UFC}/fighters/nope/fights",
                     f"{UFC}/fighters/nope/features", f"{UFC}/fighters?search=zzzzzz", f"{UFC}/matchup?a=101&b=zzzzzz",
                     f"{PREFIX}/no/such/route", f"{PREFIX}/ufc/nope"):
            status, body, _ = self.get(path)
            self.assertEqual(status, 404, path)
            self.assert_shape(body)
            self.assertEqual(body["error"]["code"], "not_found", path)

    def test_a_wrong_method_is_405_with_allow(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            status, body, headers = request(self.app, method, f"{UFC}/events",
                                            {"Authorization": f"Bearer {self.token}"})
            self.assertEqual(status, 405, method)
            self.assertEqual(headers.get("allow"), "GET", method)
            if method != "HEAD":
                self.assert_shape(body)
                self.assertEqual(body["error"]["code"], "method_not_allowed", method)

    def test_a_wrong_method_on_an_unknown_path_is_404_not_405(self):
        status, body, _ = request(self.app, "POST", f"{PREFIX}/nothing/here", {"Authorization": f"Bearer {self.token}"})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_bad_parameters_are_422_naming_the_parameter(self):
        for path, param in ((f"{UFC}/events?limit=0", "limit"), (f"{UFC}/events?limit=abc", "limit"),
                            (f"{UFC}/events?year=1800", "year"), (f"{UFC}/events?status=bogus", "status"),
                            (f"{UFC}/events?order=sideways", "order"), (f"{UFC}/fighters/101/features?as_of=whenever", "as_of"),
                            (f"{UFC}/matchup?a=101", "b"), (f"{UFC}/matchup?a=101&b=102&as_of=nope", "as_of"),
                            (f"{UFC}/fighters?search=", "search"), (f"{UFC}/upcoming?days=0", "days")):
            status, body, _ = self.get(path)
            self.assertEqual(status, 422, path)
            self.assert_shape(body)
            self.assertEqual(body["error"]["code"], "invalid_parameter", path)
            self.assertIn(param, body["error"]["message"], path)
            self.assertEqual(body["error"]["details"]["errors"][0]["param"], param, path)

    def test_an_unhandled_bug_is_a_500_with_an_error_id_in_the_log_and_no_traceback(self):
        buf = io.StringIO()
        with mock.patch.object(features, "features_as_of", side_effect=RuntimeError("secret internals")), \
                contextlib.redirect_stderr(buf):
            status, body, _ = self.get(f"{UFC}/fighters/101/features")
        self.assertEqual(status, 500)
        self.assert_shape(body)
        self.assertEqual(body["error"]["code"], "internal_error")
        message = body["error"]["message"]
        self.assertNotIn("secret internals", message)
        self.assertNotIn("Traceback", message)
        error_id = message.split("error_id=")[1].split(")")[0]
        self.assertEqual(len(error_id), 32)
        self.assertIn(error_id, buf.getvalue())                     # the log line the id ties to
        self.assertIn("secret internals", buf.getvalue())

    def test_an_unreadable_file_is_a_503_that_does_not_leak_its_path(self):
        (self.dir / FILES["events"]).write_text('{"event_id": "1"}\nthis is not json\n', encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, body, _ = self.get(f"{UFC}/events")
        self.assertEqual(status, 503)
        self.assert_shape(body)
        self.assertEqual(body["error"]["code"], "data_unavailable")
        self.assertIn("events", body["error"]["message"])
        self.assertNotIn(str(self.dir), body["error"]["message"])
        self.assertNotIn("events.jsonl", body["error"]["message"])
        # other datasets still answer
        self.assertEqual(self.get(f"{UFC}/fighters/101")[0], 200)

    def test_a_missing_dataset_is_an_empty_page_not_an_error(self):
        (self.dir / FILES["events"]).unlink()
        body = self.ok(f"{UFC}/events")
        self.assertEqual((body["data"], body["page"]["total"], body["page"]["next_cursor"]), ([], 0, None))


# -- pagination ---------------------------------------------------------------------------------------

class Pagination(ApiCase):
    def ids(self, pages):
        return [e["event_id"] for page in pages for e in page]

    def test_following_the_cursor_visits_every_event_once_newest_first(self):
        every = self.ids(self.pages(f"{UFC}/events", 4))
        self.assertEqual(len(every), 14)
        self.assertEqual(len(set(every)), 14)
        dates = [e["date_utc"] for page in self.pages(f"{UFC}/events", 5) for e in page]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(every[0], "7013")                               # the scheduled card is the newest

    def test_ascending_order_is_the_exact_reverse(self):
        newest_first = self.ids(self.pages(f"{UFC}/events", 3))
        oldest_first = self.ids(self.pages(f"{UFC}/events?order=asc", 3))
        self.assertEqual(oldest_first, newest_first[::-1])

    def test_the_page_object_reports_limit_count_total_and_the_next_cursor(self):
        body = self.ok(f"{UFC}/events?limit=5")
        self.assertEqual({k: body["page"][k] for k in ("limit", "count", "total")}, {"limit": 5, "count": 5, "total": 14})
        self.assertTrue(body["page"]["next_cursor"])
        last = self.ok(f"{UFC}/events?limit=14")
        self.assertEqual((last["page"]["count"], last["page"]["next_cursor"]), (14, None))   # exactly full: no phantom page

    def test_limit_defaults_to_50_and_is_capped_at_100(self):
        self.assertEqual(self.ok(f"{UFC}/events")["page"]["limit"], 50)
        self.assertEqual(self.ok(f"{UFC}/events?limit=1000")["page"]["limit"], 100)
        self.assertEqual(self.ok(f"{UFC}/events?limit=100")["page"]["limit"], 100)

    def test_filters_by_year_and_status(self):
        by_year = {y: self.ok(f"{UFC}/events?year={y}")["page"]["total"] for y in (2025, 2026, 2024)}
        self.assertEqual(by_year, {2025: 7, 2026: 7, 2024: 0})
        by_status = {s: self.ok(f"{UFC}/events?status={s}")["page"]["total"]
                     for s in ("final", "scheduled", "canceled", "postponed")}
        self.assertEqual(by_status, {"final": 12, "scheduled": 1, "canceled": 1, "postponed": 0})
        both = self.ok(f"{UFC}/events?year=2026&status=final")
        self.assertEqual(sorted(e["event_id"] for e in both["data"]), ["7008", "7009", "7010", "7011", "7012"])

    def test_an_event_summary_has_the_bout_count(self):
        body = self.ok(f"{UFC}/events?status=scheduled")
        self.assertEqual(body["data"][0]["bout_count"], 2)
        self.assertEqual(body["data"][0]["name"], "Synthetic Championship Night")

    def test_a_cursor_cannot_be_replayed_against_a_different_query(self):
        cursor = self.ok(f"{UFC}/events?year=2025&limit=2")["page"]["next_cursor"]
        error = self.expect_error(f"{UFC}/events?year=2026&limit=2&cursor={cursor}", 422, "invalid_cursor")
        self.assertIn("different query", error["message"])
        self.expect_error(f"{UFC}/events?year=2025&limit=2&order=asc&cursor={cursor}", 422, "invalid_cursor")
        self.ok(f"{UFC}/events?year=2025&limit=2&cursor={cursor}")                     # the right query still works

    def test_garbage_cursors_are_422_never_a_500(self):
        import base64
        enc = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")  # noqa: E731
        for cursor in ("not base64 !!", "abc", enc(b"not json"), enc(b'["list"]'), enc(b'{"q": "x"}'),
                       enc(b'{"q": "x", "k": "scalar"}'), enc(b'{"q": "x", "k": [1, 2]}'), enc(b'{"q": "x", "k": []}'),
                       enc(b"\xff\xfe")):
            self.expect_error(f"{UFC}/events?cursor={cursor}", 422, "invalid_cursor")

    def test_a_page_never_repeats_or_skips_when_new_data_arrives_between_requests(self):
        """Keyset pagination: an event newer than everything lands after page one is served."""
        first = self.ok(f"{UFC}/events?limit=5")
        served = [e["event_id"] for e in first["data"]]
        newer = dict(self.store.event_by_id()["7013"], event_id="7099", name="Late Addition",
                     date_utc="2026-12-01T00:00Z", bout_ids=[])
        self.store.upsert("events", [newer])
        rest = self.pages(f"{UFC}/events?limit=5", 5)           # a fresh walk includes the new one first
        self.assertEqual(self.ids(rest)[0], "7099")
        second = self.ok(f"{UFC}/events?limit=5&cursor={first['page']['next_cursor']}")
        self.assertFalse(set(served) & {e["event_id"] for e in second["data"]})          # no repeats
        expected = [e["event_id"] for e in self.ok(f"{UFC}/events?limit=100")["data"]]
        expected = [i for i in expected if i != "7099"]
        self.assertEqual(served + [e["event_id"] for e in second["data"]], expected[:10])    # no gaps

    def test_paginate_on_plain_lists(self):
        items = [(f"{i:02d}",) for i in range(7)]
        key = lambda t: t  # noqa: E731
        for descending in (False, True):
            ordered = items[::-1] if descending else items
            for limit in (1, 2, 3, 7, 10):
                got, cursor, seen = [], None, 0
                while True:
                    page, cursor = datasvc.paginate(items, key, limit=limit, cursor=cursor, sig="s", descending=descending)
                    got += page
                    seen += 1
                    if not cursor:
                        break
                self.assertEqual(got, ordered, (descending, limit))
                self.assertEqual(seen, -(-7 // limit), (descending, limit))
        self.assertEqual(datasvc.paginate([], key, limit=5, cursor=None, sig="s", descending=True), ([], None))


# -- events, bouts, fighters ------------------------------------------------------------------------------

class Resources(ApiCase):
    def test_an_event_comes_with_its_bouts_in_card_order_and_the_fighters_named(self):
        data = self.ok(f"{UFC}/events/7013")["data"]
        self.assertEqual(data["event"]["name"], "Synthetic Championship Night")
        self.assertEqual([b["bout_id"] for b in data["bouts"]], ["9101", "9102"])           # main event first
        self.assertEqual(data["bouts"][0]["fighter_a"], {"fighter_id": "101", "name": "Alex Archer"})
        self.assertEqual(data["bouts"][1]["card_segment"], "prelims")
        self.assertEqual(data["missing_bout_ids"], [])

    def test_an_events_bout_that_is_not_in_the_store_is_named_not_dropped_silently(self):
        event = dict(self.store.event_by_id()["7013"], bout_ids=["9101", "9999"])
        self.store.upsert("events", [event])
        data = self.ok(f"{UFC}/events/7013")["data"]
        self.assertEqual([b["bout_id"] for b in data["bouts"]], ["9101"])
        self.assertEqual(data["missing_bout_ids"], ["9999"])

    def test_a_finished_bout_with_fighters_result_statistics_and_no_odds(self):
        data = self.ok(f"{UFC}/bouts/9009")["data"]
        self.assertEqual(data["bout"]["result_method"], "DEC_UNANIMOUS")
        self.assertEqual(data["event"]["event_id"], "7009")
        self.assertEqual({k: v["name"] for k, v in data["fighters"].items()}, {"a": "Alex Archer", "b": "Ben Brawler"})
        self.assertEqual(data["result"]["outcome"], "decided")
        self.assertEqual((data["result"]["winner_id"], data["result"]["winner_name"]), ("102", "Ben Brawler"))
        self.assertEqual((data["result"]["loser_id"], data["result"]["method"]), ("101", "DEC_UNANIMOUS"))
        self.assertEqual((data["result"]["end_round"], data["result"]["fight_time_s"]), (5, 1500.0))
        self.assertEqual(sorted(r["fighter_id"] for r in data["stats"]), ["101", "102"])
        self.assertEqual(data["odds"], [])

    def test_a_scheduled_bout_has_odds_and_no_result(self):
        data = self.ok(f"{UFC}/bouts/9101")["data"]
        self.assertIsNone(data["result"])
        self.assertEqual(data["stats"], [])
        self.assertEqual([o["provider"] for o in data["odds"]], ["DraftKings"])
        self.assertEqual(data["odds"][0]["a_ml_current"], -170)

    def test_draws_and_no_contests_have_a_result_block_with_no_winner(self):
        nc = self.ok(f"{UFC}/bouts/9007")["data"]["result"]
        self.assertEqual((nc["outcome"], nc["winner_id"], nc["method"]), ("no_contest", None, "NC"))
        self.assertIsNone(self.ok(f"{UFC}/bouts/9013")["data"]["result"])                       # cancelled

    def test_a_bout_with_a_statistics_row_for_one_fighter_returns_just_that_row(self):
        data = self.ok(f"{UFC}/bouts/9004")["data"]
        self.assertEqual([r["fighter_id"] for r in data["stats"]], ["102"])

    def test_search_exact_partial_and_case_and_accent_insensitive(self):
        exact = self.ok(f"{UFC}/fighters?search=Alex%20Archer")["data"]
        self.assertEqual((exact["match"]["fighter_id"], exact["match"]["score"]), ("101", 1.0))
        self.assertEqual(exact["match"]["name"], "Alex Archer")
        partial = self.ok(f"{UFC}/fighters?search=archer")["data"]
        self.assertEqual(partial["match"]["fighter_id"], "101")
        self.assertEqual(partial["match"]["score"], 0.9)
        self.assertEqual(partial["match"]["matched_name"], "Alex Archer")        # the display name scored first
        self.assertEqual(self.ok(f"{UFC}/fighters?search=ALEX%20archer")["data"]["match"]["fighter_id"], "101")
        self.assertEqual(partial["candidates"][0]["fighter_id"], "101")
        self.assertEqual(partial["query"], "archer")

    def test_an_ambiguous_search_is_409_with_every_candidate_and_picks_nobody(self):
        error = self.expect_error(f"{UFC}/fighters?search=silva", 409, "ambiguous_name")
        self.assertEqual(error["details"]["query"], "silva")
        self.assertEqual({c["fighter_id"] for c in error["details"]["candidates"]}, {"104", "105"})
        self.assertEqual({c["name"] for c in error["details"]["candidates"]}, {"Dan Silva", "Eli Silva"})
        self.assertTrue(all("score" in c for c in error["details"]["candidates"]))
        # a fuller name settles it
        self.assertEqual(self.ok(f"{UFC}/fighters?search=dan%20silva")["data"]["match"]["fighter_id"], "104")

    def test_a_search_with_no_match_is_404(self):
        error = self.expect_error(f"{UFC}/fighters?search=Conor%20Nobody", 404, "not_found")
        self.assertIn("Conor Nobody", error["message"])

    def test_fighters_are_listed_by_name_in_pages(self):
        pages = self.pages(f"{UFC}/fighters", 2)
        names_in_order = [f["name"] for page in pages for f in page]
        self.assertEqual(names_in_order, ["Alex Archer", "Ben Brawler", "Cal Clinch", "Dan Silva", "Eli Silva"])
        self.assertEqual([len(p) for p in pages], [2, 2, 1])
        self.assertEqual(pages[0][0]["stance"], "Orthodox")

    def test_one_fighter_with_and_without_a_ufccom_profile(self):
        with_profile = self.ok(f"{UFC}/fighters/101")["data"]
        self.assertEqual(with_profile["fighter"]["name"], "Alex Archer")
        self.assertEqual(with_profile["ufccom_profile"]["ufc_slug"], "alex-archer")
        self.assertEqual(with_profile["ufc_bouts_in_store"], 7)          # 5 fought, 1 cancelled, 1 scheduled
        self.assertIsNone(self.ok(f"{UFC}/fighters/102")["data"]["ufccom_profile"])

    def test_a_fighters_fights_newest_first_with_results_from_their_side(self):
        pages = self.pages(f"{UFC}/fighters/101/fights", 3)
        fights = [f for page in pages for f in page]
        self.assertEqual([f["bout_id"] for f in fights], ["9101", "9011", "9013", "9009", "9006", "9003", "9001"])
        by_id = {f["bout_id"]: f for f in fights}
        self.assertEqual((by_id["9009"]["result"], by_id["9009"]["opponent_name"]), ("loss", "Ben Brawler"))
        self.assertEqual((by_id["9001"]["result"], by_id["9001"]["method"], by_id["9001"]["method_detail"]),
                         ("win", "KO_TKO", "Punch"))
        self.assertIsNone(by_id["9101"]["result"])
        self.assertEqual(by_id["9101"]["status"], "scheduled")
        self.assertIsNone(by_id["9013"]["result"])
        self.assertEqual(by_id["9013"]["status"], "canceled")
        self.assertFalse(by_id["9006"]["has_stats"])                      # the bout with no statistics rows
        self.assertTrue(by_id["9011"]["has_stats"])
        self.assertEqual(by_id["9011"]["event_name"], "Synthetic Fight Night 11")

    def test_the_fights_cursor_is_tied_to_the_fighter(self):
        cursor = self.ok(f"{UFC}/fighters/101/fights?limit=2")["page"]["next_cursor"]
        self.expect_error(f"{UFC}/fighters/102/fights?limit=2&cursor={cursor}", 422, "invalid_cursor")


class FeaturesEndpoint(ApiCase):
    def test_the_response_is_exactly_features_as_of(self):
        body = self.ok(f"{UFC}/fighters/101/features?as_of=2026-07-01")["data"]
        self.assertEqual(body, features.features_as_of(self.store, "101", "2026-07-01"))
        self.assertEqual(body["figures"]["sig_strikes_landed_per_min"]["value"], 4)

    def test_as_of_is_honoured_and_the_leakage_rule_holds_through_the_api(self):
        on_the_day = self.ok(f"{UFC}/fighters/101/features?as_of=2026-06-13")["data"]
        self.assertEqual(on_the_day["record"]["fights"], 4)                 # 9011 starts that evening
        self.assertEqual(self.ok(f"{UFC}/fighters/101/features?as_of=2026-06-14")["data"]["record"]["fights"], 5)
        self.assertEqual(self.ok(f"{UFC}/fighters/101/features?as_of=2026-06-13T22:00Z")["data"]["record"]["fights"], 4)

    def test_without_as_of_it_is_now(self):
        data = self.ok(f"{UFC}/fighters/101/features")["data"]
        self.assertEqual(data["as_of"], "2026-10-03T15:00:00Z")
        self.assertEqual(data["record"]["fights"], 5)

    def test_a_fighter_who_is_only_in_the_bouts_still_has_features(self):
        self.store.write("fighters", [f for f in self.store.fighters if f["fighter_id"] != "101"])
        self.expect_error(f"{UFC}/fighters/101", 404, "not_found")
        data = self.ok(f"{UFC}/fighters/101/features")["data"]
        self.assertEqual(data["record"]["fights"], 5)
        self.assertIsNone(data["name"])


class MatchupEndpoint(ApiCase):
    def test_by_ids(self):
        data = self.ok(f"{UFC}/matchup?a=101&b=102")["data"]
        self.assertEqual(data["as_of"], "2026-10-10T23:00:00Z")
        self.assertEqual(data["bout"]["bout_id"], "9101")
        self.assertEqual(data["odds"]["moneyline"]["current"]["without_margin"], {"a": 0.6067, "b": 0.3933})
        self.assertEqual(data["resolved"], {"a": {"query": "101", "fighter_id": "101", "matched_by": "id"},
                                            "b": {"query": "102", "fighter_id": "102", "matched_by": "id"}})

    def test_by_names_and_mixed(self):
        by_name = self.ok(f"{UFC}/matchup?a=Alex%20Archer&b=brawler")["data"]
        self.assertEqual((by_name["a"]["fighter_id"], by_name["b"]["fighter_id"]), ("101", "102"))
        self.assertEqual(by_name["resolved"]["b"], {"query": "brawler", "fighter_id": "102", "matched_by": "name"})
        mixed = self.ok(f"{UFC}/matchup?a=101&b=Ben%20Brawler")["data"]
        self.assertEqual(mixed["resolved"]["a"]["matched_by"], "id")
        self.assertEqual(mixed["resolved"]["b"]["matched_by"], "name")

    def test_the_response_is_the_matchup_function_plus_how_the_names_resolved(self):
        data = self.ok(f"{UFC}/matchup?a=101&b=102")["data"]
        direct = matchup.matchup(self.store, "101", "102", now=NOW)
        data.pop("resolved")
        self.assertEqual(data, direct)

    def test_order_matters_for_the_sides_and_the_prices(self):
        data = self.ok(f"{UFC}/matchup?a=102&b=101")["data"]
        self.assertEqual(data["odds"]["moneyline"]["current"]["a"], 145)

    def test_as_of_is_passed_through(self):
        data = self.ok(f"{UFC}/matchup?a=101&b=102&as_of=2026-03-14")["data"]
        self.assertEqual((data["as_of"], data["as_of_source"]), ("2026-03-14T00:00:00Z", "argument"))
        self.assertEqual(data["previous_meetings"], [])

    def test_an_ambiguous_name_is_409_naming_which_parameter(self):
        error = self.expect_error(f"{UFC}/matchup?a=101&b=silva", 409, "ambiguous_name")
        self.assertEqual(error["details"]["param"], "b")
        self.assertEqual({c["fighter_id"] for c in error["details"]["candidates"]}, {"104", "105"})

    def test_an_unknown_fighter_and_the_same_fighter_twice(self):
        self.expect_error(f"{UFC}/matchup?a=nobody%20here&b=102", 404, "not_found")
        error = self.expect_error(f"{UFC}/matchup?a=101&b=Alex%20Archer", 422, "invalid_parameter")
        self.assertIn("same fighter", error["message"])


class UpcomingEndpoint(ApiCase):
    def test_scheduled_events_with_bouts_and_current_odds(self):
        body = self.ok(f"{UFC}/upcoming")
        self.assertEqual(body["page"]["total"], 1)                          # the cancelled night is not upcoming
        event = body["data"][0]
        self.assertEqual((event["event_id"], event["status"], event["bout_count"]), ("7013", "scheduled", 2))
        main, prelim = event["bouts"]
        self.assertEqual((main["bout_id"], main["card_segment"], main["match_number"]), ("9101", "main", 1))
        self.assertEqual((main["fighter_a"]["name"], main["fighter_b"]["name"]), ("Alex Archer", "Ben Brawler"))
        self.assertEqual(main["odds"]["moneyline"]["current"]["a"], -170)
        self.assertEqual(main["odds"]["moneyline"]["current"]["without_margin"], {"a": 0.6067, "b": 0.3933})
        self.assertEqual(main["odds"]["moneyline"]["open"]["a"], -150)
        self.assertEqual(set(main["odds"]["rounds_total"]), {"line", "current"})
        self.assertIsNone(prelim["odds"])                                    # 9102 has no odds row

    def test_the_horizon(self):
        self.assertEqual(self.ok(f"{UFC}/upcoming?days=3")["page"]["total"], 0)       # the card is 7 days out
        self.assertEqual(self.ok(f"{UFC}/upcoming?days=30")["page"]["total"], 1)

    def test_a_card_in_progress_stays_and_a_stale_scheduled_row_goes(self):
        base = self.store.event_by_id()["7013"]
        self.store.upsert("events", [
            dict(base, event_id="7090", name="Tonight", date_utc="2026-10-02T23:00Z", status="in_progress", bout_ids=[]),
            dict(base, event_id="7091", name="Zombie", date_utc="2026-08-01T23:00Z", status="scheduled", bout_ids=[])])
        ids = [e["event_id"] for e in self.ok(f"{UFC}/upcoming")["data"]]
        self.assertEqual(ids, ["7090", "7013"])                                  # soonest first; the zombie is dropped

    def test_it_is_paginated(self):
        base = self.store.event_by_id()["7013"]
        self.store.upsert("events", [dict(base, event_id=f"73{n}", name=f"Future {n}", date_utc=f"2026-11-{n:02d}T23:00Z",
                                          bout_ids=[]) for n in range(1, 6)])
        pages = self.pages(f"{UFC}/upcoming", 2)
        ids = [e["event_id"] for page in pages for e in page]
        self.assertEqual(ids, ["7013", "731", "732", "733", "734", "735"])


# -- status ------------------------------------------------------------------------------------------------

class Status(ApiCase):
    def test_counts_newest_and_age_from_the_files_when_there_is_no_manifest(self):
        data = self.ok(f"{PREFIX}/status")["data"]
        ds = data["datasets"]
        self.assertEqual(set(ds), set(FILES))
        self.assertEqual({k: ds[k]["records"] for k in ds}, {
            "events": 14, "bouts": 15, "fighters": 5, "fight_stats": len(STATS), "odds": 1, "ufccom_profiles": 1})
        self.assertTrue(all(d["source"] == "files" and d["present"] for d in ds.values()))
        self.assertEqual(ds["fighters"]["newest"], "2026-10-03T12:00:00Z")
        self.assertEqual(ds["fighters"]["newest_field"], "fetched_utc")
        self.assertEqual(ds["fighters"]["age_seconds"], 3 * 3600)             # fetched 12:00, now 15:00
        self.assertEqual(ds["fighters"]["age_days"], 0.12)
        self.assertEqual(ds["events"]["newest"], "2026-10-10T21:00Z")          # a scheduled card
        self.assertEqual(ds["events"]["age_seconds"], -(7 * 86400 + 6 * 3600))  # in the future: negative, and said so
        self.assertEqual(ds["bouts"]["newest"], "2026-10-10T23:00Z")
        self.assertIsNone(data["manifest_generated_utc"])
        self.assertEqual(data["generated_utc"], "2026-10-03T15:00:00Z")

    def test_the_manifest_is_used_when_it_describes_the_file_and_distrusted_when_it_does_not(self):
        manifest = self.store.write_manifest()
        data = self.ok(f"{PREFIX}/status")["data"]
        self.assertTrue(all(d["source"] == "manifest" for d in data["datasets"].values()))
        self.assertEqual(data["manifest_generated_utc"], manifest["generated_utc"])
        self.assertEqual(data["datasets"]["events"]["records"], 14)
        # the events file changes after the manifest was written: the manifest no longer describes it
        extra = dict(self.store.event_by_id()["7013"], event_id="7055", name="After The Manifest", bout_ids=[])
        self.store.upsert("events", [extra])
        data = self.ok(f"{PREFIX}/status")["data"]
        self.assertEqual((data["datasets"]["events"]["records"], data["datasets"]["events"]["source"]), (15, "files"))
        self.assertEqual(data["datasets"]["bouts"]["source"], "manifest")

    def test_a_missing_file_is_present_false_not_an_error(self):
        (self.dir / FILES["odds"]).unlink()
        odds = self.ok(f"{PREFIX}/status")["data"]["datasets"]["odds"]
        self.assertEqual((odds["present"], odds["records"], odds["newest"], odds["age_seconds"]), (False, 0, None, None))

    def test_status_does_not_scan_the_files_again_on_every_request(self):
        spy = mock.patch.object(datasvc.StoreHolder, "_measure", autospec=True, side_effect=datasvc.StoreHolder._measure)
        with spy as measured:
            for _ in range(5):
                self.ok(f"{PREFIX}/status")
            self.assertEqual(measured.call_count, len(FILES))                    # once per dataset, not per request
            self.store.upsert("odds", [odds_row(a_ml_current=-180)])
            self.ok(f"{PREFIX}/status")
            self.assertEqual(measured.call_count, len(FILES) + 1)                # only the changed file is re-measured

    def test_a_corrupt_file_makes_status_a_503_not_a_wrong_count(self):
        (self.dir / FILES["bouts"]).write_text("garbage\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.expect_error(f"{PREFIX}/status", 503, "data_unavailable")


# -- the store is loaded once and reloaded only when a file changes -----------------------------------------

class CountingReads:
    """Counts how many times each dataset file is read, by wrapping the JSONL reader."""

    def __init__(self, delay=0.0):
        self.reads = []
        self.delay = delay
        self._real = jsonl.read_jsonl

    def __call__(self, path):
        self.reads.append(Path(path).name)
        if self.delay:
            time.sleep(self.delay)
        return self._real(path)


class StoreLoading(ApiCase):
    def touch(self, name):
        path = self.dir / FILES[name]
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    def test_the_files_are_read_once_not_once_per_request(self):
        counter = CountingReads()
        with mock.patch.object(jsonl, "read_jsonl", counter):
            for _ in range(10):
                self.ok(f"{UFC}/events")
                self.ok(f"{UFC}/events/7013")
                self.ok(f"{UFC}/fighters/101/features")
                self.ok(f"{UFC}/matchup?a=101&b=102")
                self.ok(f"{UFC}/fighters?search=archer")
                self.ok(f"{UFC}/upcoming")
        self.assertEqual(sorted(counter.reads), sorted(set(counter.reads)), "a file was read twice")
        self.assertLessEqual(len(counter.reads), len(FILES))
        self.assertEqual(datasvc.holder.reloads, 1)

    def test_a_corrupt_file_is_not_re_parsed_on_every_request_and_recovers_when_it_is_fixed(self):
        """A failed read is remembered for the store version; only a changed file earns another try."""
        (self.dir / FILES["events"]).write_text('{"event_id": "1"}\nthis is not json\n', encoding="utf-8")
        counter = CountingReads()
        with mock.patch.object(jsonl, "read_jsonl", counter), contextlib.redirect_stderr(io.StringIO()):
            statuses = [self.get(f"{UFC}/events")[0] for _ in range(5)]
        self.assertEqual(statuses, [503] * 5)
        self.assertEqual(counter.reads.count("events.jsonl"), 1)
        good = dict(build_store(self.dir.parent / "elsewhere").events[0])
        self.store.write("events", [good])                       # the file is repaired
        body = self.ok(f"{UFC}/events")
        self.assertEqual([e["event_id"] for e in body["data"]], [good["event_id"]])

    def test_a_dataset_a_route_never_touches_is_never_read(self):
        counter = CountingReads()
        with mock.patch.object(jsonl, "read_jsonl", counter):
            self.ok(f"{UFC}/fighters?search=archer")
        self.assertEqual(counter.reads, ["fighters.jsonl"])

    def test_a_changed_modification_time_swaps_in_a_fresh_store_and_nothing_else_does(self):
        self.ok(f"{UFC}/events")
        self.assertEqual(datasvc.holder.reloads, 1)
        first = datasvc.holder.store()
        for _ in range(5):
            self.ok(f"{UFC}/events")
        self.assertEqual(datasvc.holder.reloads, 1)
        self.assertIs(datasvc.holder.store(), first)
        # touching a file the store does not read, or the manifest, changes nothing
        (self.dir / "notes.txt").write_text("hello", encoding="utf-8")
        self.store.write_manifest()
        self.ok(f"{UFC}/events")
        self.assertEqual(datasvc.holder.reloads, 1)
        # a dataset file whose modification time moves, with identical content
        self.touch("odds")
        self.ok(f"{UFC}/events")
        self.assertEqual(datasvc.holder.reloads, 2)
        self.assertIsNot(datasvc.holder.store(), first)

    def test_new_data_is_visible_after_the_file_changes_and_not_before(self):
        self.assertEqual(self.ok(f"{UFC}/events?status=scheduled")["page"]["total"], 1)
        extra = dict(self.store.event_by_id()["7013"], event_id="7060", name="Brand New", date_utc="2026-11-07T23:00Z")
        self.store.upsert("events", [extra])
        self.assertEqual(self.ok(f"{UFC}/events?status=scheduled")["page"]["total"], 2)
        self.assertEqual(self.ok(f"{UFC}/events/7060")["data"]["event"]["name"], "Brand New")

    def test_a_request_that_began_on_the_old_store_finishes_on_it(self):
        old = datasvc.holder.store()
        self.assertEqual(len(old.events), 14)
        self.store.upsert("events", [dict(self.store.event_by_id()["7013"], event_id="7061", bout_ids=[])])
        fresh = datasvc.holder.store()
        self.assertIsNot(fresh, old)
        self.assertEqual(len(old.events), 14)             # a consistent snapshot, not half old and half new
        self.assertEqual(len(fresh.events), 15)

    def test_concurrent_first_requests_read_each_file_once(self):
        counter = CountingReads(delay=0.05)               # slow reads so the threads genuinely overlap
        errors, results = [], []

        def worker():
            try:
                results.append(len(datasvc.holder.store().bouts_by_fighter()))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with mock.patch.object(jsonl, "read_jsonl", counter):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(counter.reads.count("bouts.jsonl"), 1)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(datasvc.holder.reloads, 1)

    def test_the_default_data_directory_is_the_foundations(self):
        from src.datasvc.ufc import store as ufc_store
        datasvc.use_data_dir(None)
        self.assertEqual(datasvc.holder.root, ufc_store.DEFAULT_DIR)


if __name__ == "__main__":
    unittest.main()
