"""The first-tester journey, walked end to end through the real app over ASGI.

WHO THIS IS FOR. A prospect who gets one of the five outreach messages
(docs/sales/SEND_ORDER.md), opens the sample brief, asks for early access, is
granted seven days by hand (docs/sales/DISCOVERY_GUIDE.md "First 20 testers"),
signs in with the token, uses the product, and on day eight finds the week over.
It was walked once by hand against a real local server (uvicorn on 127.0.0.1,
APP_PUBLIC_DEMO unset, billing provider unset, a throwaway database) and this
file pins what that walk found.

HOW IT RUNS. api.app.app is called directly through ASGI (no network, no
httpx); the database is a temp file; the schedule provider and the price boards
are stubbed. The sample brief and the analyst route read the repo's shipped
pilot ledger and config/sample_brief.json, because "the sample page shows the
designated brief" is exactly the claim a prospect depends on. Nothing here
calls a provider, spends a credit or reads the sealed window.

HOW IT READS. Plain tests pin steps that work. A step that is broken today, or
that tells a person something that is not true today, is an `expectedFailure`
whose body asserts what SHOULD be true. When the product is fixed the test turns
into an unexpected success and the decorator has to come off, which is the
point: the list of known breaks is the list of expectedFailure decorators.

Skipped where FastAPI is absent (the Linux CI image).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
ADMIN = "admin-token-for-the-journey-test"

AWAY, HOME = "SD", "MIL"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _asgi(app, method, path, *, headers=None, query="", body=None):
    """One request through the ASGI app. Returns (status, parsed body or text)."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    payload = b"" if body is None else json.dumps(body).encode()
    if body is not None:
        raw_headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "headers": raw_headers,
        "client": ("127.0.0.1", 22222), "server": ("testserver", 80),
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


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _Journey(unittest.TestCase):
    """The real app, a temp database, the network stubbed, the paid gate ON,
    billing OFF."""

    @classmethod
    def setUpClass(cls):
        import api.app as app_module
        if app_module.PUBLIC_DEMO:
            raise unittest.SkipTest("APP_PUBLIC_DEMO is set: the game surface is open")
        cls.app = app_module.app

    def setUp(self):
        from api import games as games_api, sample as sample_api, signup as signup_api
        from src.analysis import prices as prices_mod
        from src.appstate import freshness, ratelimit
        from src.providers import mlb

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "app.db"
        env = mock.patch.dict(os.environ, {
            "APP_DB_PATH": str(self.db_path), "APP_ADMIN_TOKEN": ADMIN})
        env.start()
        self.addCleanup(env.stop)
        # Billing is off in production and must be off here, whatever the host has set.
        for name in ("BILLING_PROVIDER", "STRIPE_API_KEY", "STRIPE_BETA_PRICE_ID"):
            patcher = mock.patch.dict(os.environ)
            patcher.start()
            self.addCleanup(patcher.stop)
            os.environ.pop(name, None)

        self.designated = sample_api.designated()
        self.date = (self.designated or {}).get("date", "2026-10-04")

        def schedule(date):
            return [{"game_pk": 990777, "date": date, "away_team": AWAY, "home_team": HOME,
                     "venue": "American Family Field", "start_time_utc": f"{date}T20:10:00Z"}]

        patches = [
            mock.patch.object(games_api, "_entries_cache",
                              freshness.SingleFlightTTLCache(ttl_s=60.0)),
            mock.patch.object(mlb, "fetch_games", lambda d: schedule(d)),
            mock.patch.object(prices_mod, "boards_by_matchup", lambda date=None: {}),
            # a fresh limiter per test: ten signups an hour per address is the real rule
            mock.patch.object(signup_api, "_signup_limiter",
                              ratelimit.FixedWindowLimiter(limit=1000, window_s=3600.0)),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    # -- helpers ---------------------------------------------------------------

    def call(self, method, path, *, token=None, admin=False, query="", body=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if admin:
            headers["X-Admin-Token"] = ADMIN
        return _asgi(self.app, method, path, headers=headers, query=query, body=body)

    def signup(self, email, attribution=None):
        body = {"email": email}
        if attribution is not None:
            body["attribution"] = attribution
        return self.call("POST", "/signup", body=body)

    def grant(self, email):
        status, body = self.call("POST", "/admin/testers", admin=True, body={"email": email})
        self.assertEqual(status, 200, body)
        return body

    def expire(self, user_id, days_ago=1):
        """Move the person's token and tester window into the past, in the test database."""
        past = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("UPDATE tokens SET expires_at = ? WHERE user_id = ?", (past, user_id))
            conn.execute("UPDATE testers SET expires_at = ? WHERE user_id = ?", (past, user_id))
            conn.commit()
        return past

    def row_for(self, user_id):
        status, body = self.call("GET", "/admin/testers", admin=True)
        self.assertEqual(status, 200, body)
        return next(t for t in body["testers"] if t["user_id"] == user_id)

    def activation(self):
        status, body = self.call("GET", "/admin/activation", admin=True)
        self.assertEqual(status, 200, body)
        return body


# ===========================================================================
# 1. The public sample, signed out
# ===========================================================================

class SampleSignedOut(_Journey):

    def test_the_sample_page_and_its_script_are_served_without_a_token(self):
        for path in ("/web/sample.html", "/web/js/sample.js", "/web/landing.html"):
            status, _ = self.call("GET", path)
            self.assertEqual(status, 200, path)

    def test_sample_brief_is_the_designated_game_with_the_supervised_label(self):
        from src.analyst import PILOT_LABEL
        self.assertIsNotNone(self.designated, "config/sample_brief.json names no game")
        status, body = self.call("GET", "/sample/brief")
        self.assertEqual(status, 200)
        self.assertTrue(body["available"], "the designated game has no row in the pilot ledger")
        self.assertEqual(body["label"], PILOT_LABEL)
        analysis = body["analysis"]
        self.assertEqual((analysis["date"], analysis["away"], analysis["home"]),
                         (self.designated["date"], self.designated["away"], self.designated["home"]))
        self.assertTrue(analysis["calls"], "a brief with no calls")
        self.assertTrue(body["published_utc"] and body["first_pitch_utc"])

    def test_no_query_parameter_can_pick_another_game(self):
        status, body = self.call("GET", "/sample/brief", query="date=2020-01-01&away=NYY&home=BOS")
        self.assertEqual(status, 200)
        self.assertEqual(body["analysis"]["date"], self.designated["date"])

    def test_the_three_links_go_to_pages_and_routes_that_exist(self):
        src = _read(JS / "sample.js")
        links = dict(re.findall(r'(\w+): \{ href: "([^"]+)"', src))
        self.assertEqual(links, {"record": "index.html#/record-card", "landing": "landing.html",
                                 "signup": "index.html#/signup"})
        for href in links.values():
            self.assertTrue((ROOT / "web" / href.split("#")[0]).is_file(), href)
        main = _read(JS / "main.js")
        for route in ("record-card", "signup"):
            self.assertIn(route, main)

    def test_the_offer_line_agrees_with_the_landing_page_on_the_shared_facts(self):
        offer = re.search(r'OFFER_LINE =\s*"(.*?)";', _read(JS / "sample.js"), re.S)
        offer = re.sub(r'"\s*\+\s*"', "", offer.group(1))
        landing = _read(ROOT / "web" / "landing.html")
        hero = re.search(r'data-hook="hero-cta-note">(.*?)</p>', landing, re.S).group(1)
        for fact in ("7 days", "no card", "$19.99"):
            self.assertIn(fact, offer)
            self.assertIn(fact, hero)
        self.assertIn("MLB postseason", offer)
        self.assertIn("Analysis, not advice", offer)

    def test_the_sample_offer_line_says_it_is_not_on_sale_and_hand_picked(self):
        # The landing page and the signup form say both: "first 20 testers", "not on sale yet",
        # "if you're picked". The sample page says "Free for 7 days for the first testers" and
        # a link labelled "Start the free 7 days" that opens a request form, not a start.
        offer = _read(JS / "sample.js")
        self.assertRegex(offer, r"(?i)not on sale")
        self.assertNotIn("Start the free 7 days", offer)

    def test_the_outreach_message_does_not_promise_paying_to_keep_it_while_checkout_is_off(self):
        status, meta = self.call("GET", "/meta")
        self.assertEqual(status, 200)
        self.assertEqual(meta["billing"]["checkout"], "off")
        text = _read(ROOT / "docs" / "sales" / "SEND_ORDER.md")
        top = text.split("## Send these five first", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("only if you want to keep it", top)


# ===========================================================================
# 2 and 3. The utm source, and "Request early access"
# ===========================================================================

LEAD = {"utm_source": "l009-tommy-lorenzo", "utm_medium": "x_account",
        "utm_campaign": "brief_01", "anon_id": "fc03f186144ad4b7fceaa33323315fc2"}


class RequestEarlyAccess(_Journey):

    def test_the_lead_source_is_kept_on_the_signup_record_and_the_account_event(self):
        from src.appstate import customers, events
        status, body = self.signup("Prospect@Example.test", LEAD)
        self.assertEqual((status, body["status"]), (200, "waitlisted"))
        stored = customers.get_signup_attribution(body["user_id"])
        for key in ("utm_source", "utm_medium", "utm_campaign"):
            self.assertEqual(stored[key], LEAD[key])
        created = [e for e in events.list_events() if e.kind == events.ACCOUNT_CREATED]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].properties["utm_source"], "l009-tommy-lorenzo")
        status, funnel = self.call("GET", "/admin/funnel", admin=True)
        self.assertEqual(funnel["by_source"]["l009-tommy-lorenzo"]["account_created"], 1)

    def test_the_first_touch_is_not_overwritten_by_a_later_request(self):
        from src.appstate import customers
        _, first = self.signup("prospect@example.test", LEAD)
        self.signup("prospect@example.test", dict(LEAD, utm_source="somebody-else"))
        self.assertEqual(customers.get_signup_attribution(first["user_id"])["utm_source"],
                         "l009-tommy-lorenzo")

    def test_a_request_stores_the_email_and_charges_and_promises_nothing_paid(self):
        from src.appstate import customers, users as users_store
        status, body = self.signup("prospect@example.test", LEAD)
        self.assertEqual((status, body["status"]), (200, "waitlisted"))
        self.assertNotIn("checkout", body)
        user = users_store.get_user_by_email("prospect@example.test")
        self.assertEqual((user.status, user.plan), ("waitlisted", "none"))
        self.assertIsNone(customers.get_subscription_record(user.id))
        self.assertIsNone(customers.get_customer_ref(user.id))
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0], 0)
        # asking twice is the same answer, not a second row
        self.assertEqual(self.signup("PROSPECT@example.test")[1]["user_id"], user.id)
        self.assertEqual(self.call("POST", "/signup", body={"email": "nope"})[0], 400)

    def test_the_confirmation_states_the_terms(self):
        text = _read(JS / "checkout.js").split("WAITLIST_CONFIRMATION =", 1)[1].split("export const NOT_ON", 1)[0]
        text = re.sub(r'"\s*\+\s*"', "", text).replace("\n", " ")
        for fact in ("no card needed", "performance is not proven", "not advice",
                     "losses included", "temporary"):
            self.assertIn(fact, text)

    def test_the_confirmation_does_not_promise_a_timing_the_guide_does_not_keep(self):
        # The guide tells the owner to answer an unselected signup with "I'll write when one
        # opens"; the page tells every signup an email "usually within a day" is coming.
        text = _read(JS / "checkout.js")
        self.assertNotIn("usually within a day", text)


# ===========================================================================
# 4. The owner grants seven days
# ===========================================================================

class AdminGrant(_Journey):

    def test_grant_returns_the_token_once_with_a_seven_day_expiry(self):
        self.signup("prospect@example.test", LEAD)
        before = datetime.now(timezone.utc)
        grant = self.grant("prospect@example.test")
        self.assertEqual(set(grant), {"user_id", "email", "token", "expires_at",
                                      "testers_granted", "testers_limit"})
        self.assertEqual((grant["testers_granted"], grant["testers_limit"]), (1, 20))
        ends = datetime.fromisoformat(grant["expires_at"])
        self.assertAlmostEqual((ends - before).total_seconds(), 7 * 86400, delta=120)
        # the token is shown once: no admin read gives it back
        for path in ("/admin/testers", "/admin/users", "/admin/overview"):
            _, body = self.call("GET", path, admin=True)
            self.assertNotIn(grant["token"], json.dumps(body))
        users = self.call("GET", "/admin/users", admin=True)[1]["users"]
        self.assertEqual([(u["status"], u["tester"]) for u in users], [("invited", True)])

    def test_the_route_is_admin_only_and_refuses_a_second_grant(self):
        self.assertEqual(self.call("POST", "/admin/testers", body={"email": "a@example.test"})[0], 401)
        self.assertEqual(self.call("POST", "/admin/testers", admin=True, body={})[0], 400)
        self.grant("a@example.test")
        status, body = self.call("POST", "/admin/testers", admin=True, body={"email": "a@example.test"})
        self.assertEqual((status, body["detail"]["error"]), (409, "already_a_tester"))

    def test_the_guides_button_label_is_the_admin_pages_label(self):
        page = _read(JS / "admin.js")
        self.assertIn("`Grant ${days}-day tester access`", page)
        guide = " ".join(_read(ROOT / "docs" / "sales" / "DISCOVERY_GUIDE.md").split())
        self.assertIn('"Grant 7-day tester access"', guide)

    def test_an_email_that_belongs_to_a_tester_gets_a_status_word_and_nothing_else(self):
        from src.appstate import customers
        grant = self.grant("a@example.test")
        status, body = self.signup("a@example.test", dict(LEAD, utm_source="stranger"))
        self.assertEqual((status, body), (200, {"user_id": grant["user_id"], "status": "tester_active"}))
        self.assertEqual(customers.get_signup_attribution(grant["user_id"]), {})


# ===========================================================================
# 5. The tester signs in
# ===========================================================================

class TesterSignedIn(_Journey):

    def test_the_game_surface_and_the_brief_answer_with_the_token_and_401_without(self):
        from src.analyst import PILOT_LABEL
        token = self.grant("a@example.test")["token"]
        paths = [f"/games/{self.date}", f"/game/{self.date}/{AWAY}/{HOME}",
                 f"/analyst/{self.date}/{AWAY}/{HOME}"]
        for path in paths:
            self.assertEqual(self.call("GET", path, token=token)[0], 200, path)
            status, body = self.call("GET", path)
            self.assertEqual((status, body["detail"]["error"]), (401, "unauthorized"), path)
            self.assertEqual(self.call("GET", path, token="not-a-token")[0], 401, path)
        status, brief = self.call("GET", paths[2], token=token)
        self.assertTrue(brief["available"])
        self.assertEqual(brief["label"], PILOT_LABEL)
        self.assertEqual(brief["analysis"], self.call("GET", "/sample/brief")[1]["analysis"])


# ===========================================================================
# 6. Activation, and our own traffic
# ===========================================================================

class Activation(_Journey):

    def test_signing_in_is_not_activation_and_opening_the_slate_and_a_game_is(self):
        grant = self.grant("a@example.test")
        token, uid = grant["token"], grant["user_id"]
        self.assertEqual(self.call("GET", "/billing/status", token=token)[0], 200)   # redeems the token
        row = self.row_for(uid)
        self.assertIsNotNone(row["first_signin_at"])
        self.assertFalse(row["activated"])
        self.assertEqual(self.activation()["activated"], 0)
        self.call("GET", f"/games/{self.date}", token=token)
        self.call("GET", f"/game/{self.date}/{AWAY}/{HOME}", token=token)
        row = self.row_for(uid)
        self.assertTrue(row["activated"])
        self.assertEqual(set(row["features"]), {"slate", "matchup"})
        report = self.activation()
        self.assertEqual((report["testers_granted"], report["activated"], report["internal_excluded"]),
                         (1, 1, 0))
        self.assertNotIn("a@example.test", json.dumps(report))

    def test_an_account_signed_up_with_an_internal_source_is_left_out_of_every_count(self):
        self.signup("owner@example.test", {"utm_source": "internal-brey"})
        token = self.grant("owner@example.test")["token"]
        self.call("GET", f"/games/{self.date}", token=token)
        real = self.grant("real@example.test")["token"]
        self.call("GET", f"/games/{self.date}", token=real)
        report = self.activation()
        self.assertEqual((report["testers_granted"], report["activated"], report["internal_excluded"]),
                         (1, 1, 1))

    def test_the_guide_tells_the_owner_how_to_keep_his_own_account_out_of_the_counts(self):
        # Granting his own email the way the guide says (no earlier signup) leaves no internal
        # tag, so his own page views count as a customer's. Only a signup that carried
        # utm_source=internal... is excluded, and the guide never says so.
        self.assertIn("internal", _read(ROOT / "docs" / "sales" / "DISCOVERY_GUIDE.md"))


# ===========================================================================
# 7. Day eight
# ===========================================================================

class DayEight(_Journey):

    def test_an_expired_token_is_a_401_that_names_the_end_date_and_checkout_is_off(self):
        grant = self.grant("a@example.test")
        token = grant["token"]
        past = self.expire(grant["user_id"])
        for path in (f"/games/{self.date}", f"/game/{self.date}/{AWAY}/{HOME}",
                     f"/analyst/{self.date}/{AWAY}/{HOME}"):
            status, body = self.call("GET", path, token=token)
            self.assertEqual(status, 401, path)
            self.assertEqual(body["detail"]["error"], "tester_access_expired")
            self.assertEqual(datetime.fromisoformat(body["detail"]["expires_at"]),
                             datetime.fromisoformat(past))
        status, body = self.call("POST", "/billing/tester-checkout", token=token, body={})
        self.assertEqual((status, body["status"]), (200, "not_configured"))
        self.assertEqual(body["message"], "paid plans are not open yet; nothing has been changed")
        self.assertEqual(self.signup("a@example.test")[1]["status"], "tester_expired")

    def test_the_sign_in_page_words_for_the_ended_week_with_checkout_off(self):
        src = _read(JS / "checkout.js")
        self.assertIn('TESTER_NOT_OPEN = "Paid plans are not open yet. Reply to Brey if you want to keep going."', src)
        self.assertIn("Your early access ended on ${day}.", src)
        self.assertIn("upgradeLabel", _read(JS / "signin.js"))

    def test_a_game_page_for_an_ended_tester_says_the_access_ended(self):
        # The sign-in page does. A game page draws the generic gate for every 401: "This part of
        # the private beta needs your invite token. Add it once and it stays on this device",
        # to a person who has a token, with a "Request early access" button.
        self.assertIn("tester_access_expired", _read(JS / "dom.js"))


# ===========================================================================
# 8. A tester who loses the token
# ===========================================================================

class LostToken(_Journey):

    def test_the_only_door_is_extend_by_user_id_with_a_reason_and_it_uses_no_slot(self):
        grant = self.grant("a@example.test")
        uid = grant["user_id"]
        status, body = self.call("POST", "/admin/users/token", admin=True, body={"email": "a@example.test"})
        self.assertEqual(status, 409)                      # the subscriber reissue refuses a tester
        self.assertEqual(self.call("POST", "/admin/testers/extend", admin=True,
                                   body={"user_id": uid})[1]["detail"]["error"], "reason_required")
        self.assertEqual(self.call("POST", "/admin/testers/extend", admin=True,
                                   body={"email": "a@example.test", "reason": "lost it"})[0], 400)
        status, fresh = self.call("POST", "/admin/testers/extend", admin=True,
                                  body={"user_id": uid, "reason": "lost the token"})
        self.assertEqual(status, 200)
        self.assertEqual((fresh["testers_granted"], fresh["extension_number"]), (1, 1))
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=fresh["token"])[0], 200)
        self.assertEqual(self.call("GET", "/admin/testers", admin=True)[1]["remaining"], 19)

    def test_after_the_week_ended_a_re_issued_token_works_and_the_old_one_is_a_plain_401(self):
        grant = self.grant("a@example.test")
        self.expire(grant["user_id"])
        fresh = self.call("POST", "/admin/testers/extend", admin=True,
                          body={"user_id": grant["user_id"], "reason": "lost the token"})[1]
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=fresh["token"])[0], 200)
        status, body = self.call("GET", f"/games/{self.date}", token=grant["token"])
        self.assertEqual((status, body["detail"]["error"]), (401, "unauthorized"))

    @unittest.expectedFailure
    def test_re_sending_a_lost_token_does_not_hand_out_another_week(self):
        grant = self.grant("a@example.test")
        fresh = self.call("POST", "/admin/testers/extend", admin=True,
                          body={"user_id": grant["user_id"], "reason": "lost the token"})[1]
        self.assertLessEqual(datetime.fromisoformat(fresh["expires_at"]),
                             datetime.fromisoformat(grant["expires_at"]))

    @unittest.expectedFailure
    def test_re_sending_a_lost_token_revokes_the_lost_one(self):
        grant = self.grant("a@example.test")
        self.call("POST", "/admin/testers/extend", admin=True,
                  body={"user_id": grant["user_id"], "reason": "lost the token"})
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 401)

    def test_the_guide_says_what_the_owner_does_when_a_tester_loses_the_token(self):
        guide = _read(ROOT / "docs" / "sales" / "DISCOVERY_GUIDE.md")
        self.assertRegex(guide.split("## First 20 testers", 1)[1].split("\n## ", 1)[0], r"(?i)\blost\b")


# ===========================================================================
# What the first message tells a tester is there
# ===========================================================================

class TokenMessageIsTrueToday(_Journey):

    def test_the_message_does_not_offer_a_ufc_card_while_ufc_picks_are_paused(self):
        token = self.grant("a@example.test")["token"]
        status, card = self.call("GET", f"/card/{self.date}", token=token, query="sport=mma")
        self.assertEqual(status, 200)
        if not card.get("paused"):
            self.skipTest("UFC picks are live again: the sentence is true")
        guide = _read(ROOT / "docs" / "sales" / "DISCOVERY_GUIDE.md")
        self.assertNotIn("the UFC card on fight days", guide)


if __name__ == "__main__":
    unittest.main()
