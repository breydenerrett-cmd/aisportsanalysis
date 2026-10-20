"""The "Create a free account" tab on the sign-in page, and what a free member sees next, run for real under node.

Owner decision "yes open signups" (2026-10-19). web/js/signin.js now has two tabs: Create a free account (the first
one a new visitor sees) and Sign in. These tests use the small fake DOM and scripted fetch of
tests/test_signin_password_web.py (the same real modules, no copies), and pin:

  * who sees which tab first: a new device sees Create; a device that has signed in before, or holds a token, sees Sign
    in; `?create=1` (every "Create free account" button) forces Create and `?tab=signin` forces Sign in;
  * what the form sends (email trimmed, the password, the optional kennel name only when given, the honeypot field as
    left), and that on success it stores the token, remembers the device, empties the password and goes to My kennel
    with ?welcome=1;
  * a repeat email: the server's own sentence, no token stored, no redirect, a "Sign in instead" button that carries
    the email across; a refusal: the server's sentence, no token, the button back;
  * the honeypot is out of sight WITHOUT display:none and out of the tab order;
  * a free member who signs in goes to their kennel, not to a board that would refuse them;
  * My kennel's welcome card, the paid board's 403 card, and the sign-in gate's "Create free account" link.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_page as run_hounds_page
from tests.test_signin_password_web import HARNESS, JS, TOKEN_KEY, WEB

HAD_KEY = "linehound.had_account"
SIGNUP_OK = {"code": 200, "body": {"ok": True, "message": "If that email can be used, you're in.",
                                   "token": "FREE-TOKEN", "expires_at": "2026-11-18T00:00:00+00:00",
                                   "kind": "free", "access_active": True, "has_password": True}}
SIGNUP_REPEAT = {"code": 200, "body": {"ok": True, "message": "If that email can be used, you're in. If you already "
                                       "have an account, sign in instead; if you lost your password, use Get help "
                                       "on the support page.", "token": None, "expires_at": None, "kind": None,
                                       "access_active": False, "has_password": False}}

FILL = """
hook("create-email").value = "  New@Example.com ";
hook("create-password").value = "river-bank-lantern-42";
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class CreateTabUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_page(self, script="", **scenario):
        Path(self._tmp.name, "page.mjs").write_text(HARNESS.replace("%SCRIPT%", script), encoding="utf-8")
        proc = subprocess.run(["node", "page.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2500:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    SHOWN = """
out.createHidden = hook("create-form").hidden;
out.loginHidden = hook("login-form").hidden;
out.title = say("signin-title");
out.eyebrow = say("signin-eyebrow");
out.selected = { create: hook("tab-create").attrs["aria-selected"], signin: hook("tab-signin").attrs["aria-selected"] };
out.codeToggleHidden = hook("show-access-code").hidden;
"""

    # ---- which tab first --------------------------------------------------------------

    def test_a_new_visitor_sees_create_a_free_account_first(self):
        out = self.run_page(self.SHOWN)
        self.assertEqual((out["createHidden"], out["loginHidden"]), (False, True))
        self.assertEqual(out["title"], "Create a free account.")
        self.assertEqual(out["eyebrow"], "FREE ACCOUNT")
        self.assertEqual(out["selected"], {"create": "true", "signin": "false"})
        self.assertTrue(out["codeToggleHidden"], "the access code belongs to the Sign in tab")
        self.assertEqual([c for c in out["calls"] if c["url"] != "/meta"], [],
                         "looking at the form costs no request")

    def test_the_tabs_are_named_in_words_and_create_comes_first(self):
        out = self.run_page("""
out.labels = [say("tab-create"), say("tab-signin")];
out.order = main._all([]).filter((n) => "data-hook" in n.attrs).map((n) => n.attrs["data-hook"]);
out.role = hook("signin-tabs").attrs.role;
""")
        self.assertEqual(out["labels"], ["Create a free account", "Sign in"])
        self.assertLess(out["order"].index("tab-create"), out["order"].index("tab-signin"))
        self.assertLess(out["order"].index("create-form"), out["order"].index("login-form"))
        self.assertEqual(out["role"], "tablist")

    def test_a_device_that_has_signed_in_before_sees_sign_in_first(self):
        out = self.run_page(self.SHOWN, storage={HAD_KEY: "1"})
        self.assertEqual((out["createHidden"], out["loginHidden"]), (True, False))
        self.assertEqual(out["title"], "Sign in to view tonight's board.")
        self.assertEqual(out["eyebrow"], "PRIVATE BETA")
        self.assertFalse(out["codeToggleHidden"])

    def test_a_stored_token_or_a_next_page_means_sign_in_first(self):
        for kwargs in (dict(storage={TOKEN_KEY: "x"}), dict(query={"next": "#/props"}), dict(query={"tab": "signin"})):
            with self.subTest(**kwargs):
                out = self.run_page(self.SHOWN, **kwargs)
                self.assertEqual((out["createHidden"], out["loginHidden"]), (True, False))

    def test_create_one_forces_create_even_on_a_returning_device(self):
        out = self.run_page(self.SHOWN, storage={HAD_KEY: "1"}, query={"create": "1"})
        self.assertEqual((out["createHidden"], out["loginHidden"]), (False, True))

    def test_the_tabs_switch_both_ways_and_the_title_follows(self):
        out = self.run_page("""
await click("tab-signin");
out.a = { create: hook("create-form").hidden, login: hook("login-form").hidden, title: say("signin-title") };
await click("tab-create");
out.b = { create: hook("create-form").hidden, login: hook("login-form").hidden, title: say("signin-title") };
""")
        self.assertEqual(out["a"], {"create": True, "login": False, "title": "Sign in to view tonight's board."})
        self.assertEqual(out["b"], {"create": False, "login": True, "title": "Create a free account."})

    # ---- the form -----------------------------------------------------------------------

    def test_the_fields_are_right_for_a_password_manager_and_a_phone(self):
        out = self.run_page("""
const a = (h, k) => hook(h).attrs[k];
out.email = [a("create-email", "type"), a("create-email", "autocomplete"), a("create-email", "inputmode")];
out.password = [a("create-password", "type"), a("create-password", "autocomplete"), a("create-password", "minlength")];
out.kennel = [a("create-kennel", "type"), a("create-kennel", "maxlength")];
out.submit = say("create-submit");
out.page = main.textContent;
""")
        self.assertEqual(out["email"], ["email", "email", "email"])
        self.assertEqual(out["password"], ["password", "new-password", "10"])
        self.assertEqual(out["kennel"], ["text", "40"])
        self.assertEqual(out["submit"], "Create free account")
        self.assertIn("At least 10 characters", out["page"])
        self.assertIn("Kennel name (optional)", out["page"])

    def test_the_honeypot_is_out_of_sight_without_display_none_and_out_of_the_tab_order(self):
        out = self.run_page("""
const t = hook("create-website");
out.trap = { tabindex: t.attrs.tabindex, auto: t.attrs.autocomplete, name: t.attrs.name,
             wrapClass: t.parentNode.attrs.class, wrapHidden: t.parentNode.attrs["aria-hidden"],
             hiddenProp: t.parentNode.hidden === true };
""")
        trap = out["trap"]
        self.assertEqual((trap["tabindex"], trap["auto"], trap["name"]), ("-1", "off", "website"))
        self.assertIn("signin__hp", trap["wrapClass"])
        self.assertEqual(trap["wrapHidden"], "true")
        self.assertFalse(trap["hiddenProp"], "hidden/display:none would tell a bot it is a trap")
        css = (WEB / "css" / "signin.css").read_text(encoding="utf-8")
        rule = re.search(r"\.signin__hp\s*\{([^}]*)\}", css).group(1)
        self.assertIn("left: -9999px", rule)
        self.assertNotIn("display", rule)

    def test_a_good_signup_sends_the_form_stores_the_token_and_opens_my_kennel(self):
        out = self.run_page(FILL + """
hook("create-kennel").value = "  Back Forty ";
await submit("create-form");
await settle();
out.passwordLeft = hook("create-password").value;
out.status = say("create-status");
out.disabled = hook("create-submit").disabled;
""", routes={"POST /auth/signup": SIGNUP_OK})
        posts = [c for c in out["calls"] if c["url"] == "/auth/signup"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["body"], {"email": "New@Example.com", "password": "river-bank-lantern-42",
                                            "website": "", "kennel_name": "Back Forty"})
        self.assertIsNone(posts[0]["auth"], "a signup carries no token")
        self.assertEqual(out["storage"][TOKEN_KEY], "FREE-TOKEN")
        self.assertEqual(out["storage"][HAD_KEY], "1")
        self.assertEqual(out["assigned"], ["kennel.html?welcome=1"])
        self.assertEqual(out["passwordLeft"], "", "the password field is emptied once it is sent")
        self.assertIn("You're in", out["status"])
        self.assertNotIn("river-bank-lantern-42", json.dumps(out["storage"]))

    def test_the_kennel_name_is_left_out_when_the_box_is_empty(self):
        out = self.run_page(FILL + """await submit("create-form"); await settle();""",
                            routes={"POST /auth/signup": SIGNUP_OK})
        self.assertNotIn("kennel_name", [c for c in out["calls"] if c["url"] == "/auth/signup"][0]["body"])

    def test_a_bot_that_fills_the_honeypot_sends_what_it_filled_and_the_server_decides(self):
        out = self.run_page(FILL + """
hook("create-website").value = "http://spam.example";
await submit("create-form"); await settle();
""", routes={"POST /auth/signup": SIGNUP_REPEAT})
        body = [c for c in out["calls"] if c["url"] == "/auth/signup"][0]["body"]
        self.assertEqual(body["website"], "http://spam.example")
        self.assertNotIn(TOKEN_KEY, out["storage"])
        self.assertEqual(out["assigned"], [])

    def test_a_repeat_email_gets_the_servers_sentence_no_session_and_a_way_to_sign_in(self):
        out = self.run_page(FILL + """
await submit("create-form"); await settle();
out.status = say("create-status");
out.repeatHidden = hook("create-repeat").hidden;
out.button = say("create-signin-instead");
await click("create-signin-instead");
out.afterClick = { login: hook("login-form").hidden, create: hook("create-form").hidden,
                   email: hook("login-email").value };
""", routes={"POST /auth/signup": SIGNUP_REPEAT})
        self.assertIn("sign in instead", out["status"])
        self.assertEqual(out["status"], SIGNUP_REPEAT["body"]["message"])
        self.assertFalse(out["repeatHidden"])
        self.assertEqual(out["button"], "Sign in instead")
        self.assertEqual(out["afterClick"], {"login": False, "create": True, "email": "New@Example.com"})
        self.assertNotIn(TOKEN_KEY, out["storage"])
        self.assertEqual(out["assigned"], [])

    def test_a_refusal_shows_the_servers_sentence_stores_nothing_and_gives_the_button_back(self):
        cases = (
            (400, {"detail": {"error": "password_rejected", "message": "That password is too common. Pick something less guessable."}},
             "That password is too common. Pick something less guessable."),
            (400, {"detail": {"error": "invalid_email", "message": "Enter a valid email address."}},
             "Enter a valid email address."),
            (429, {"detail": {"error": "rate_limited", "message": "Too many attempts. Try again in about 57 minutes."}},
             "Too many attempts. Try again in about 57 minutes."),
            (503, {"detail": {"error": "signup_unavailable", "message": "Sign-up is unavailable right now. Try again shortly."}},
             "Sign-up is unavailable right now. Try again shortly."),
        )
        for code, body, sentence in cases:
            with self.subTest(code=code):
                out = self.run_page(FILL + """
await submit("create-form"); await settle();
out.status = say("create-status");
out.disabled = hook("create-submit").disabled;
""", routes={"POST /auth/signup": {"code": code, "body": body}})
                self.assertEqual(out["status"], sentence)
                self.assertNotIn(TOKEN_KEY, out["storage"])
                self.assertEqual(out["assigned"], [])
                self.assertFalse(out["disabled"])

    def test_an_unreachable_service_gets_a_calm_fallback(self):
        out = self.run_page(FILL + """await submit("create-form"); await settle(); out.status = say("create-status");""",
                            routes={"POST /auth/signup": {"network": True}})
        self.assertIn("Could not create the account", out["status"])
        self.assertNotIn(TOKEN_KEY, out["storage"])

    def test_one_request_per_press_however_fast_the_clicks(self):
        out = self.run_page(FILL + """
const a = submit("create-form"); const b = submit("create-form");
await a; await b; await settle();
""", routes={"POST /auth/signup": SIGNUP_OK})
        self.assertEqual(len([c for c in out["calls"] if c["url"] == "/auth/signup"]), 1)

    # ---- after sign-in ------------------------------------------------------------------

    def test_a_free_member_who_signs_in_goes_to_their_kennel_not_the_board(self):
        free = {"code": 200, "body": {"token": "T2", "expires_at": "2026-11-18T00:00:00+00:00", "kind": "free",
                                      "access_active": True, "has_password": True}}
        out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "river-bank-lantern-42";
await submit("login-form"); await settle();
""", routes={"POST /auth/login": free, "GET /auth/password": {"code": 200, "body": {"has_password": True}}},
                            storage={HAD_KEY: "1"})
        self.assertEqual(out["assigned"], ["kennel.html"])
        self.assertEqual(out["hash"], "")
        self.assertEqual(out["storage"][TOKEN_KEY], "T2")

    def test_a_free_member_sent_from_a_page_goes_back_to_that_page(self):
        free = {"code": 200, "body": {"token": "T2", "expires_at": "2026-11-18T00:00:00+00:00", "kind": "free",
                                      "access_active": True, "has_password": True}}
        out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "river-bank-lantern-42";
await submit("login-form"); await settle();
""", routes={"POST /auth/login": free}, query={"next": "#/props"}, storage={HAD_KEY: "1"})
        self.assertEqual((out["assigned"], out["hash"]), ([], "#/props"))

    def test_a_tester_or_subscriber_login_still_opens_the_board(self):
        paid = {"code": 200, "body": {"token": "T3", "expires_at": "2026-11-18T00:00:00+00:00", "kind": "tester",
                                      "access_active": True, "has_password": True}}
        out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "river-bank-lantern-42";
await submit("login-form"); await settle();
""", routes={"POST /auth/login": paid}, storage={HAD_KEY: "1"})
        self.assertEqual((out["assigned"], out["hash"]), ([], "#/today"))

    def test_a_successful_login_remembers_the_device(self):
        ok = {"code": 200, "body": {"token": "T4", "expires_at": "2026-11-18T00:00:00+00:00", "kind": "subscriber",
                                    "access_active": True, "has_password": True}}
        out = self.run_page("""
await click("tab-signin");
hook("login-email").value = "a@b.co"; hook("login-password").value = "river-bank-lantern-42";
await submit("login-form"); await settle();
""", routes={"POST /auth/login": ok})
        self.assertEqual(out["storage"][HAD_KEY], "1")

    def test_a_signed_in_visitor_sees_the_account_box_and_no_tabs(self):
        out = self.run_page("""
await settle();
out.tabsHidden = hook("signin-tabs").hidden;
out.createHidden = hook("create-form").hidden;
out.loginHidden = hook("login-form").hidden;
out.accountHidden = hook("signin-account").hidden;
""", storage={TOKEN_KEY: "tok"}, routes={"GET /auth/password": {"code": 200, "body": {"has_password": True}},
                                         "GET /billing/status": {"code": 200, "body": {}}})
        self.assertEqual((out["tabsHidden"], out["createHidden"], out["loginHidden"], out["accountHidden"]),
                         (True, True, True, False))

    def test_the_early_access_door_for_the_paid_board_is_still_on_the_page(self):
        out = self.run_page("""
out.head = say("signin-early-head");
out.href = hook("signin-start-trial").attrs.href;
out.note = say("signin-note");
""")
        self.assertEqual(out["head"], "EARLY ACCESS TO DAILY PICKS")
        self.assertEqual(out["href"], "#/signup")
        self.assertIn("NO ACCOUNT YET", out["note"])

    # ---- the paid board's 403, and the sign-in gate ----------------------------------------

    def test_the_paid_board_tells_a_free_member_what_they_have_and_where_to_go(self):
        out = self.run_page("""
const { renderError } = await import("./dom.js");
renderError(main, { status: 403, detail: { error: "paid_access_required", message: "x" } });
out.card = main.querySelector("[data-hook='paid-board-only']") !== null;
out.cardText = main.textContent;
out.kennel = hook("paid-board-kennel").attrs.href;
out.door = hook("early-access-link").attrs.href;
out.generic = main.querySelector("[data-hook='view-error']") !== null;
renderError(main, { status: 403, detail: { error: "something_else" } });
out.otherIsGeneric = main.querySelector("[data-hook='view-error']") !== null;
""")
        self.assertTrue(out["card"])
        self.assertFalse(out["generic"], "an account that is fine is not 'request failed'")
        self.assertIn("The daily picks board is early access.", out["cardText"])
        self.assertIn("build dogs", out["cardText"])
        self.assertEqual((out["kennel"], out["door"]), ("kennel.html", "#/signup"))
        self.assertTrue(out["otherIsGeneric"], "any other 403 is still an ordinary failure")

    def test_the_sign_in_gate_offers_create_free_account_beside_the_paid_door(self):
        out = self.run_page("""
const { renderError } = await import("./dom.js");
renderError(main, { status: 401, detail: null });
await settle();
out.create = [say("create-account-link"), hook("create-account-link").attrs.href];
out.signin = hook("signin-link").attrs.href;
out.paidDoor = hook("signup-link").attrs.href;
""")
        self.assertEqual(out["create"], ["Create free account", "#/signin?create=1"])
        self.assertEqual((out["signin"], out["paidDoor"]), ("#/signin", "#/signup"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelWelcome(unittest.TestCase):
    EMPTY = [200, {"handle": "handler-21e8", "display": "Handler 21E8", "dog_count": 0, "dogs": [],
                   "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}]
    ONE = [200, {"handle": "handler-21e8", "display": "Handler 21E8", "dog_count": 1, "season": {"id": "s2", "label": "Season 2"},
                 "paper_only": True, "dogs": [{
                     "id": "u-1", "name": "Gus", "tagline": "", "status": "running", "version_no": 1, "look": None, "sports": ["mlb"],
                     "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "units_average_price": None},
                     "settled": 0, "open_bets": 0, "new": True, "last_pick": None, "page_href": "hound.html?id=u-1",
                     "retired": False, "builder_href": "build-a-hound.html?from=u-1",
                     "bankroll": {"start": 1000.0, "current": 1000.0, "pnl_usd": 0.0, "return_pct": 0.0, "units_total": 0.0,
                                  "bets": 0, "settled": 0, "small_sample": True, "small_sample_min": 20, "basis": "average_price"}}]}]
    SIGNED = {"aisportsanalysis.invite_token": "tok"}
    QUERIES = [dict(name="welcome", sel="[data-hook='kennel-welcome']", mode="text"),
               dict(name="empty", sel="[data-hook='kennel-empty']", mode="count"),
               dict(name="build", sel="[data-hook='kennel-welcome-build']", mode="text")]

    def test_a_new_member_lands_on_a_welcome_card_that_replaces_the_plain_empty_state(self):
        out = run_hounds_page("kennel", routes={"/hounds/kennels/mine": self.EMPTY}, stored=self.SIGNED,
                              search="?welcome=1", queries=self.QUERIES)
        f = out["final"]
        self.assertIn("Welcome to your kennel", f["welcome"])
        self.assertIn("Your account is free", f["welcome"])
        self.assertEqual(f["build"], "Build your first dog")
        self.assertEqual(f["empty"], 0)

    def test_the_build_button_opens_the_studio_on_the_rules_tab(self):
        out = run_hounds_page("kennel", routes={"/hounds/kennels/mine": self.EMPTY}, stored=self.SIGNED, search="?welcome=1",
                              actions=[dict(do="click", sel="[data-hook='kennel-welcome-build']", label="open", wait=120, capture=[
                                  dict(name="hidden", sel="[data-hook='studio']", mode="hidden"),
                                  dict(name="title", sel="[data-hook='studio-title']", mode="text")])])
        cap = out["captures"]["open"]
        self.assertEqual((cap["hidden"], cap["title"]), (False, "New dog"))

    def test_without_the_flag_the_ordinary_empty_state_stays(self):
        out = run_hounds_page("kennel", routes={"/hounds/kennels/mine": self.EMPTY}, stored=self.SIGNED, queries=self.QUERIES)
        self.assertEqual(out["final"]["empty"], 1)
        self.assertEqual(out["final"]["welcome"], None)

    def test_once_there_is_a_dog_the_flag_does_nothing(self):
        out = run_hounds_page("kennel", routes={"/hounds/kennels/mine": self.ONE}, stored=self.SIGNED,
                              search="?welcome=1", queries=self.QUERIES)
        self.assertIsNone(out["final"]["welcome"])
        self.assertEqual(out["final"]["empty"], 0)

    def test_a_signed_out_visitor_with_the_flag_is_still_asked_to_sign_in(self):
        out = run_hounds_page("kennel", routes={}, search="?welcome=1", queries=[
            dict(name="gate", sel="[data-hook='kennel-signin']", mode="text"), self.QUERIES[0]])
        self.assertIn("Sign in to see your dogs", out["final"]["gate"])
        self.assertIsNone(out["final"]["welcome"])


class TheCallsToActionAreOneDecision(unittest.TestCase):
    def test_the_landing_nav_button_is_the_free_account_and_moves_into_the_bar(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<a class="btn btn--primary" href="index.html#/signin\?create=1" data-hook="cta-primary" data-nav-extra>Create free account</a>')

    def test_the_old_paid_signup_page_is_still_routed_and_still_the_paid_boards_door(self):
        main = (JS / "main.js").read_text(encoding="utf-8")
        self.assertIn('route === "signup"', main)
        landing = (WEB / "landing.html").read_text(encoding="utf-8")
        self.assertIn('<a href="index.html#/signup" data-hook="cta-early-access">', landing)


if __name__ == "__main__":
    unittest.main()
