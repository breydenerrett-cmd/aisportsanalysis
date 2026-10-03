"""The real API records value actions, and only the ones it should.

tests/test_activation.py pins the definitions and the SQL. This file drives the
REAL app (api.app.app) over ASGI, with the content builders stubbed and the
database a temp file, and proves the claims the owner's measurement depends on:

  * each route the web app actually calls, and that is labelled, records exactly
    ONE `page_view` event with the right feature, surface and sport, and the
    labels it emits are exactly activation.MEASURED_FEATURES;
  * an unauthorised request (no token, a bad token, an expired one, a
    suspended account, a lapsed subscription) records nothing, because the
    route body never runs;
  * a failed request (404, 400, 502) with a valid token records nothing;
  * the public postseason page records a signed-in tester's visit only when a
    valid token is presented, never for an anonymous visitor, a bad token, or
    the "not available" answer;
  * routes that are fetched in the background (/today, /changed, the odds
    board) are NOT value actions, so opening Today does not make a tester look
    like they used price comparison;
  * a client cannot claim a feature: a query parameter is ignored and the
    public beacon refuses the page_view kind;
  * a recording failure never breaks the response;
  * GET /admin/activation is 401 without the admin token, carries no email,
    and lists every feature label with zeros;
  * redeeming a token alone (a real GET /my-bets) leaves a tester unactivated,
    and the first content fetch activates them.

Skipped where FastAPI is absent (the Linux CI image).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import activation, attribution, customers, events, testers
from src.appstate import freshness
from src.appstate import users as users_store

ADMIN = "admin-token-for-the-activation-tests"
DATE = "2026-08-31"


def _asgi(app, method, path, *, headers=None, query="", body=None):
    """One request through the ASGI app. Returns (status, parsed body)."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    payload = b"" if body is None else json.dumps(body).encode()
    if body is not None:
        raw_headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "headers": raw_headers,
        "client": ("127.0.0.1", 11111), "server": ("testserver", 80),
    }
    captured, parts = {}, []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    raw = b"".join(parts)
    try:
        return captured.get("status"), json.loads(raw)
    except ValueError:
        return captured.get("status"), raw.decode("utf-8", "replace")


class _FakePostseasonCache:
    """Stands in for api.postseason._cache: serves a fixed good page."""

    def __init__(self, fail=False):
        self.fail = fail

    def get(self, key, builder):
        if self.fail:
            raise RuntimeError("no page to serve")
        return ({"available": True, "series": [], "as_of": "2026-10-05T12:00:00+00:00"},
                {"served_at": "x", "built_at": "x", "stale": False, "stale_reason": None})


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _AppCase(unittest.TestCase):
    """The real app, a temp database, content builders stubbed, caches fresh."""

    @classmethod
    def setUpClass(cls):
        import api.app as app_module
        if app_module.PUBLIC_DEMO:
            raise unittest.SkipTest("APP_PUBLIC_DEMO is set: the game surface is open")
        cls.app = app_module.app

    def setUp(self):
        from api import card as card_api, games as games_api, odds as odds_api
        from api import postseason as postseason_api, props as props_api, today as today_api
        from src.analysis import prices as prices_mod
        from src.pipeline import nfl_slate
        from src.providers import mlb
        from src.report import card as card_mod, card_v2, nfl_card, ufc_card
        from src.report import props as props_mod
        from tests.test_api_odds import _boards, _schedule

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "APP_DB_PATH": str(Path(self._tmp.name) / "app.db"), "APP_ADMIN_TOKEN": ADMIN})
        env.start()
        self.addCleanup(env.stop)

        def cache():
            return freshness.SingleFlightTTLCache(ttl_s=60.0)

        self.postseason = _FakePostseasonCache()
        patches = [
            mock.patch.object(games_api, "_entries_cache", cache()),
            mock.patch.object(odds_api, "_odds_cache", cache()),
            mock.patch.object(props_api, "_props_cache", cache()),
            mock.patch.object(card_api, "_nfl_card_cache", cache()),
            mock.patch.object(card_api, "_mma_card_cache", cache()),
            mock.patch.object(card_api, "_mlb_live_card_cache", cache()),
            mock.patch.object(today_api, "_today_cache", cache()),
            mock.patch.object(postseason_api, "_cache", self.postseason),
            mock.patch.object(mlb, "fetch_games", lambda d: _schedule(d)),
            mock.patch.object(prices_mod, "boards_by_matchup",
                              lambda date=None: _boards(date or DATE)),
            mock.patch.object(props_mod, "board_for_date",
                              lambda d, limit=None: {"date": d, "contracts": [], "reason": None}),
            mock.patch.object(card_v2, "frozen_card_v2",
                              lambda d: {"picks": [], "frozen": True, "rule": "v2"}),
            mock.patch.object(card_mod, "frozen_card",
                              lambda d: {"picks": [], "frozen": True, "rule": "v1"}),
            mock.patch.object(nfl_card, "card_for_date",
                              lambda d, now=None: {"sport": "nfl", "picks": []}),
            mock.patch.object(ufc_card, "card_for_date",
                              lambda d, now=None: {"sport": "mma", "picks": []}),
            mock.patch.object(nfl_slate, "entries_for_date", lambda d: []),
            mock.patch.object(today_api, "build_today_payload",
                              lambda games, store, date=None, now=None, **kw: {
                                  "date": date, "games": [], "notes": [], "slip": None}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    # -- helpers ---------------------------------------------------------------

    def get(self, path, token=None, *, query="", headers=None):
        merged = dict(headers or {})
        if token:
            merged["Authorization"] = f"Bearer {token}"
        return _asgi(self.app, "GET", path, headers=merged, query=query)

    def admin(self, path, *, token=ADMIN):
        return _asgi(self.app, "GET", path,
                     headers={"X-Admin-Token": token} if token else {})

    def grant(self, i=1, *, age=None):
        real_now = datetime.now(timezone.utc)
        return testers.grant_tester(email=f"t{i}@example.com",
                                    now=real_now - (age or timedelta(0)))

    def page_views(self):
        return [e for e in events.list_events() if e.kind == events.PAGE_VIEW]

    def value_actions(self):
        return [e for e in self.page_views() if "feature" in e.properties]


class EveryLabelledRouteRecordsOneValueAction(_AppCase):
    # (what it is, path, query, expected properties; date None = today, not pinned)
    ROUTES = [
        ("card, the default rule", "/card/" + DATE, "",
         {"route": "card", "date": DATE, "feature": "card", "surface": "card", "sport": "mlb"}),
        ("card, rule v1", "/card/" + DATE, "rule=v1",
         {"route": "card", "date": DATE, "feature": "card", "surface": "card", "sport": "mlb"}),
        ("card, today", "/card", "",
         {"route": "card", "date": None, "feature": "card", "surface": "card", "sport": "mlb"}),
        ("card, NFL", "/card/" + DATE, "sport=nfl",
         {"route": "card", "date": DATE, "feature": "nfl", "surface": "card", "sport": "nfl"}),
        ("card, UFC", "/card/" + DATE, "sport=mma",
         {"route": "card", "date": DATE, "feature": "ufc", "surface": "card", "sport": "mma"}),
        ("slate", "/games/" + DATE, "",
         {"route": "/games/{date}", "date": DATE, "feature": "slate", "surface": "slate",
          "sport": "mlb"}),
        ("slate, NFL", "/games/" + DATE, "sport=nfl",
         {"route": "/games/{date}", "date": DATE, "feature": "nfl", "surface": "slate",
          "sport": "nfl"}),
        ("slate, a sport it does not serve is the MLB slate", "/games/" + DATE, "sport=mma",
         {"route": "/games/{date}", "date": DATE, "feature": "slate", "surface": "slate",
          "sport": "mlb"}),
        ("matchup", f"/game/{DATE}/BOS/NYY", "",
         {"route": "/game/{date}/{away}/{home}", "date": DATE, "feature": "matchup",
          "surface": "matchup", "sport": "mlb"}),
        ("props for a date", "/props/" + DATE, "",
         {"route": "/props/{date}", "date": DATE, "feature": "props", "surface": "props",
          "sport": "mlb"}),
        ("props, tonight", "/props", "",
         {"route": "/props", "date": None, "feature": "props", "surface": "props",
          "sport": "mlb"}),
        ("price comparison for one game", f"/odds/{DATE}/BOS/NYY", "",
         {"route": "/odds/{date}/{away}/{home}", "date": DATE, "feature": "prices",
          "surface": "prices", "sport": "mlb"}),
    ]

    def test_each_route_records_exactly_one_page_view_with_its_feature(self):
        token = self.grant().token
        seen = set()
        for name, path, query, expected in self.ROUTES:
            with self.subTest(name):
                before = len(self.page_views())
                status, _ = self.get(path, token, query=query)
                self.assertEqual(status, 200, name)
                recorded = self.page_views()[before:]
                self.assertEqual(len(recorded), 1, f"{name}: one request, one insert")
                got = dict(recorded[0].properties)
                if expected["date"] is None:
                    self.assertRegex(got.pop("date"), r"^\d{4}-\d{2}-\d{2}$")
                    expected = {k: v for k, v in expected.items() if k != "date"}
                self.assertEqual(got, expected)
                seen.add(expected["feature"])
        # The public postseason page is the one labelled route that takes an
        # optional token rather than a required one.
        before = len(self.page_views())
        self.assertEqual(self.get("/postseason", token)[0], 200)
        seen.add(self.page_views()[before].properties["feature"])
        self.assertEqual(seen, set(activation.MEASURED_FEATURES),
                         "the labels the real routes emit are exactly the measured ones")

    def test_the_postseason_page_records_a_signed_in_testers_visit(self):
        token = self.grant().token
        status, body = self.get("/postseason", token)
        self.assertEqual(status, 200)
        self.assertTrue(body["available"])
        views = self.page_views()
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].properties, {
            "route": "/postseason", "date": None, "feature": "postseason",
            "surface": "postseason", "sport": "mlb"})
        self.assertEqual(views[0].user_hash, events.hash_user_id(
            users_store.authenticate(token).id))

    def test_the_recorded_visits_make_the_tester_activated_in_the_admin_listing(self):
        grant = self.grant()
        self.get("/card/" + DATE, grant.token)
        self.get("/props/" + DATE, grant.token)
        self.get("/card/" + DATE, grant.token, query="sport=nfl")
        status, listing = self.admin("/admin/testers")
        self.assertEqual(status, 200)
        row = listing["testers"][0]
        self.assertTrue(row["activated"])
        self.assertEqual(row["features"], {"card": 1, "props": 1, "nfl": 1})
        self.assertEqual(row["active_days"], 1)
        self.assertFalse(row["returning"])
        self.assertGreaterEqual(row["hours_signup_to_activation"], 0)


class RedeemingATokenIsNotActivation(_AppCase):
    def test_a_real_sign_in_alone_leaves_the_tester_unactivated_and_the_first_fetch_activates(self):
        grant = self.grant()
        status, _ = self.get("/my-bets", grant.token)       # authenticated, personal data only
        self.assertEqual(status, 200)
        _, listing = self.admin("/admin/testers")
        row = listing["testers"][0]
        self.assertIsNotNone(row["first_signin_at"], "the sign-in was recorded")
        self.assertEqual(row["first_used_at"], row["first_signin_at"])
        self.assertFalse(row["activated"], "a sign-in is not activation")
        self.assertIsNone(row["activated_at"])
        self.assertEqual(self.admin("/admin/activation")[1]["activated"], 0)

        self.assertEqual(self.get("/card/" + DATE, grant.token)[0], 200)
        _, listing = self.admin("/admin/testers")
        row = listing["testers"][0]
        self.assertTrue(row["activated"])
        self.assertIsNotNone(row["activated_at"])
        self.assertEqual(self.admin("/admin/activation")[1]["activated"], 1)


class ARequestThatIsNotAuthorisedRecordsNothing(_AppCase):
    PAID = ["/card/" + DATE, "/games/" + DATE, f"/game/{DATE}/BOS/NYY", "/props/" + DATE,
            f"/odds/{DATE}/BOS/NYY"]

    def assert_nothing(self, *tokens, expect=401):
        for path in self.PAID:
            for token in tokens:
                with self.subTest(path=path, token=bool(token)):
                    self.assertEqual(self.get(path, token)[0], expect)
        self.assertEqual(self.page_views(), [])

    def test_no_token(self):
        self.assert_nothing(None)

    def test_a_token_that_was_never_issued(self):
        self.assert_nothing("tok_not_a_real_token")

    def test_an_expired_token(self):
        self.assert_nothing(self.grant(age=timedelta(days=8)).token)

    def test_a_revoked_token(self):
        grant = self.grant()
        users_store.revoke_all_tokens(grant.user_id)
        self.assert_nothing(grant.token)

    def test_a_suspended_account(self):
        grant = self.grant()
        users_store.set_user_status(grant.user_id, "suspended")
        self.assert_nothing(grant.token)

    def test_a_lapsed_subscription_is_a_402_and_records_nothing(self):
        user = users_store.create_user("lapsed@example.com", status="active", plan="beta")
        customers.upsert_customer(user.id, "cus_1")
        customers.upsert_subscription(user.id, "sub_1", "canceled")
        self.assert_nothing(users_store.issue_invite_token(user.id), expect=402)

    def test_the_postseason_page_for_an_anonymous_visitor(self):
        status, body = self.get("/postseason")
        self.assertEqual(status, 200)
        self.assertTrue(body["available"])
        self.assertEqual(self.page_views(), [])

    def test_the_postseason_page_with_a_token_that_does_not_work(self):
        grant = self.grant()
        for token in ("tok_not_a_real_token", self.grant(2, age=timedelta(days=8)).token):
            self.assertEqual(self.get("/postseason", token)[0], 200, "public: never a 401")
        users_store.set_user_status(grant.user_id, "suspended")
        self.assertEqual(self.get("/postseason", grant.token)[0], 200)
        self.assertEqual(self.page_views(), [])

    def test_the_postseason_page_with_a_malformed_authorization_header(self):
        for value in ("Bearer", "Basic abc", "tok_without_scheme", "Bearer  "):
            self.assertEqual(self.get("/postseason", headers={"Authorization": value})[0], 200)
        self.assertEqual(self.page_views(), [])

    def test_the_postseason_unavailable_answer_is_not_content(self):
        grant = self.grant()
        self.postseason.fail = True
        with mock.patch.object(sys, "stderr", new=mock.Mock()):
            status, body = self.get("/postseason", grant.token)
        self.assertEqual(status, 200)
        self.assertFalse(body.get("available", True))
        self.assertEqual(self.page_views(), [])

    def test_the_public_beacon_refuses_to_record_a_page_view_for_anyone(self):
        """A client cannot claim a value action by posting one."""
        status, body = _asgi(self.app, "POST", "/funnel/event",
                             body={"kind": "page_view", "properties": {"feature": "card"}})
        self.assertEqual(status, 400)
        self.assertEqual(body["detail"]["error"], "kind_not_public")
        self.assertEqual(events.list_events(), [])


class AFailedRequestRecordsNothing(_AppCase):
    def test_a_game_that_is_not_on_the_schedule_is_a_404_and_records_nothing(self):
        token = self.grant().token
        for path in (f"/game/{DATE}/SEA/TEX", f"/odds/{DATE}/SEA/TEX"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, token)[0], 404)
        self.assertEqual(self.page_views(), [])

    def test_a_bad_date_is_a_400_and_records_nothing(self):
        token = self.grant().token
        for path in ("/props/not-a-date", "/games/not-a-date", "/game/not-a-date/BOS/NYY",
                     "/odds/not-a-date/BOS/NYY"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, token)[0], 400)
        self.assertEqual(self.page_views(), [])

    def test_an_unreachable_schedule_is_a_502_and_records_nothing(self):
        from src.providers import mlb
        token = self.grant().token
        with mock.patch.object(mlb, "fetch_games", side_effect=mlb.MLBError("down")):
            for path in ("/games/" + DATE, f"/game/{DATE}/BOS/NYY", f"/odds/{DATE}/BOS/NYY"):
                with self.subTest(path=path):
                    self.assertEqual(self.get(path, token)[0], 502)
        self.assertEqual(self.page_views(), [])

    def test_an_unreadable_prop_store_is_a_502_and_records_nothing(self):
        from src.report import props as props_mod
        token = self.grant().token
        with mock.patch.object(props_mod, "board_for_date", side_effect=OSError("disk")):
            self.assertEqual(self.get("/props/" + DATE, token)[0], 502)
        self.assertEqual(self.page_views(), [])

    def test_tennis_is_a_notice_not_a_value_action(self):
        token = self.grant().token
        status, body = self.get("/card/" + DATE, token, query="sport=tennis")
        self.assertEqual(status, 200)
        self.assertIn("Research only", body["reason"])
        self.assertEqual(self.value_actions(), [])

    def test_a_recording_failure_never_breaks_the_response(self):
        token = self.grant().token
        with mock.patch.object(events, "record_event", side_effect=RuntimeError("disk full")), \
                mock.patch.object(sys, "stderr", new=mock.Mock()):
            for path in ("/props/" + DATE, "/games/" + DATE, "/card/" + DATE,
                         f"/odds/{DATE}/BOS/NYY"):
                with self.subTest(path=path):
                    self.assertEqual(self.get(path, token)[0], 200)
            self.assertEqual(self.get("/postseason", token)[0], 200)


class RoutesTheWebAppFetchesInTheBackgroundAreNotValueActions(_AppCase):
    """Opening Today fires /today, /games, /odds, /changed, /card, /daily and
    /opportunities together. A label on a route a page fetches in the
    background would make every Today view look like use of that feature."""

    def test_today_changed_and_the_odds_board_carry_no_feature(self):
        grant = self.grant()
        for path in ("/today", f"/changed/{DATE}", f"/odds/{DATE}"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, grant.token)[0], 200)
        self.assertEqual(self.value_actions(), [])
        routes = sorted(e.properties["route"] for e in self.page_views())
        self.assertEqual(routes, ["/changed/{date}", "/today"],
                         "today and changed still record the plain page_view they always did")
        self.assertFalse(self.admin("/admin/testers")[1]["testers"][0]["activated"])

    def test_the_opportunities_board_carries_no_feature(self):
        grant = self.grant()
        self.assertEqual(self.get("/opportunities/" + DATE, grant.token)[0], 200)
        self.assertEqual(self.value_actions(), [])

    def test_the_price_board_is_not_price_comparison_but_one_games_prices_are(self):
        grant = self.grant()
        self.assertEqual(self.get(f"/odds/{DATE}", grant.token)[0], 200)
        self.assertEqual(self.value_actions(), [])
        self.assertEqual(self.get(f"/odds/{DATE}/BOS/NYY", grant.token)[0], 200)
        self.assertEqual([e.properties["feature"] for e in self.value_actions()], ["prices"])


class AClientCannotClaimAFeature(_AppCase):
    def test_query_parameters_and_headers_never_choose_the_label(self):
        token = self.grant().token
        self.get("/props/" + DATE, token, query="feature=card&surface=card&sport=nfl",
                 headers={"X-Feature": "card"})
        recorded = self.value_actions()
        self.assertEqual([(e.properties["feature"], e.properties["surface"],
                           e.properties["sport"]) for e in recorded], [("props", "props", "mlb")])

    def test_the_sport_comes_from_what_was_served_not_from_the_query_string(self):
        token = self.grant().token
        self.get("/games/" + DATE, token, query="sport=mma")
        self.assertEqual([e.properties["feature"] for e in self.value_actions()], ["slate"],
                         "/games serves the MLB slate for any sport but nfl: it is not UFC")


class TheAdminActivationRoute(_AppCase):
    def test_it_is_401_without_the_admin_token_and_with_a_wrong_one(self):
        self.grant()
        self.assertEqual(self.admin("/admin/activation", token=None)[0], 401)
        self.assertEqual(self.admin("/admin/activation", token="wrong")[0], 401)
        self.assertEqual(self.admin("/admin/activation", token="")[0], 401)

    def test_it_is_404_when_the_admin_surface_is_not_configured(self):
        with mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": ""}):
            self.assertEqual(self.admin("/admin/activation")[0], 404)

    def test_it_sits_behind_the_one_admin_gate(self):
        import inspect
        from api import admin
        default = inspect.signature(admin.get_activation).parameters["_admin"].default
        self.assertIs(default.dependency, admin._require_admin)

    def test_the_other_testers_route_keeps_its_own_gate(self):
        self.assertEqual(self.admin("/admin/testers", token=None)[0], 401)

    def test_the_answer_has_every_label_with_zeros_and_no_email(self):
        grant = self.grant()
        status, report = self.admin("/admin/activation")
        self.assertEqual(status, 200)
        self.assertEqual(set(report), {
            "as_of", "testers_granted", "testers_in_window", "activated", "returning",
            "median_hours_signup_to_activation", "feature_users", "internal_excluded",
            "unmeasured_features"})
        self.assertEqual(list(report["feature_users"]), list(activation.FEATURES))
        self.assertEqual(set(report["feature_users"].values()), {0})
        self.assertEqual((report["testers_granted"], report["testers_in_window"],
                          report["activated"], report["returning"]), (1, 1, 0, 0))
        self.assertIsNone(report["median_hours_signup_to_activation"])
        blob = json.dumps(report)
        self.assertNotIn("@", blob)
        self.assertNotIn("t1", blob)
        self.assertNotIn(grant.token, blob)
        self.assertNotRegex(blob, r"[0-9a-f]{64}")

    def test_after_use_it_counts_the_testers_and_their_features(self):
        a, b = self.grant(1), self.grant(2)
        self.get("/card/" + DATE, a.token)
        self.get("/props/" + DATE, a.token)
        self.get("/card/" + DATE, b.token, query="sport=mma")
        _, report = self.admin("/admin/activation")
        self.assertEqual((report["testers_granted"], report["activated"]), (2, 2))
        self.assertEqual(report["feature_users"]["card"], 1)
        self.assertEqual(report["feature_users"]["props"], 1)
        self.assertEqual(report["feature_users"]["ufc"], 1)
        self.assertEqual(report["feature_users"]["moneyline"], 0)
        self.assertIsNotNone(report["median_hours_signup_to_activation"])
        self.assertEqual(report["unmeasured_features"], ["moneyline"])

    def test_our_own_test_accounts_are_left_out_and_counted(self):
        real, internal = self.grant(1), self.grant(2)
        customers.record_signup_attribution(internal.user_id, {"utm_source": "internal-test"})
        customers.record_signup_attribution(real.user_id, {"utm_source": "reddit"})
        for grant in (real, internal):
            self.get("/card/" + DATE, grant.token)
        _, report = self.admin("/admin/activation")
        self.assertEqual((report["testers_granted"], report["activated"],
                          report["internal_excluded"]), (1, 1, 1))
        self.assertEqual(report["feature_users"]["card"], 1)

    def test_the_funnel_and_the_activation_report_share_one_internal_rule(self):
        from api import funnel
        for value in ("internal", "internal-test", "Internal-X", "international-bettors",
                      "reddit", None, 5):
            with self.subTest(value=value):
                event = events.AnalyticsEvent(id=1, user_hash="x", kind=events.LANDING_VIEW,
                                              properties={"utm_source": value}, at="x")
                self.assertEqual(funnel._is_internal(event),
                                 attribution.is_internal_source(value))


if __name__ == "__main__":
    unittest.main()
