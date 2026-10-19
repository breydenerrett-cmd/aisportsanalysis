"""web/js/signin.js: the email + password sign-in page, run for real under node.

A small fake DOM and a scripted fetch (the same approach tests/
test_expired_tester_paid_path.py takes for the same module), so every claim here
is about what the page does when the server says X:

  * email + password is the primary form; the access code is behind
    "Have an access code?";
  * a good login stores the returned token and opens the board; a bad one shows
    the SERVER's sentence and stores nothing; a tester whose window ended is shown
    the ended state instead of being sent to a board that would refuse them;
  * after an access-code sign-in with no password, a one-time card offers to set
    one, once per device;
  * a signed-in visitor gets "Change password" and "Sign out", and sign-out
    revokes on the server and forgets the token here.
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

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web" / "js"
WEB = ROOT / "web"

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.listeners = {}; this.isRoot = false;
    this.style = {}; this.value = "";
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null; return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:(\^?=)'([^']*)')?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const [, name, op, val] = m;
    return this._all([]).filter((n) => {
      if (!(name in n.attrs)) return false;
      if (!op) return true;
      return op === "=" ? n.attrs[name] === val : n.attrs[name].startsWith(val);
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const body = new Elem("body"); body.isRoot = true;
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  body, referrer: "",
  addEventListener() {},
  querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s),
};
const scenario = JSON.parse(process.env.SCENARIO);
const store = new Map(Object.entries(scenario.storage || {}));
const assigned = [];
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "",
              assign(url) { assigned.push(String(url)); } },
  history: { replaceState() {} },
  addEventListener() {}, dispatchEvent() { return true; },
  crypto: globalThis.crypto,
};

// A scripted server: route table from "METHOD /path" to {code, body} or {network: true}.
const routes = scenario.routes || {};
const calls = [];
globalThis.fetch = async (url, init) => {
  url = String(url);
  const method = (init && init.method) || "GET";
  const headers = (init && init.headers) || {};
  const sent = init && init.body ? JSON.parse(init.body) : null;
  calls.push({ url, method, auth: headers.Authorization || null, body: sent });
  const json = (status, b) => ({ ok: status < 400, status, text: async () => JSON.stringify(b) });
  if (url.startsWith("/meta")) return json(200, scenario.meta || { billing: { checkout: "off" } });
  const r = routes[method + " " + url];
  if (!r) return json(200, {});
  if (r.network) throw new Error("offline");
  return json(r.code, r.body);
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const settle = () => new Promise((r) => setTimeout(r, 30));
const main = document.createElement("main"); body.appendChild(main);
const hook = (h) => main.querySelector(`[data-hook='${h}']`);
const say = (h) => { const n = hook(h); return n ? n.textContent : null; };
const submit = (h) => hook(h).listeners.submit[0]({ preventDefault() {} });
const click = (h) => hook(h).listeners.click[0]();

const { renderSignin } = await import("./signin.js");
const out = {};
await renderSignin(main, scenario.query || {});
await settle();
%SCRIPT%
out.calls = calls;
out.assigned = assigned;
out.hash = window.location.hash;
out.storage = Object.fromEntries(store);
out.page = text(main);
console.log("@@" + JSON.stringify(out));
"""

LOGIN_OK = {"code": 200, "body": {"token": "SESSION-TOKEN", "expires_at": "2026-10-26T00:00:00+00:00",
                                  "kind": "tester", "access_active": True, "has_password": True}}
TOKEN_KEY = "aisportsanalysis.invite_token"
SEEN_KEY = "linehound.password_card_seen"


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SigninPageUnderNode(unittest.TestCase):
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
        Path(self._tmp.name, "page.mjs").write_text(
            HARNESS.replace("%SCRIPT%", script), encoding="utf-8")
        proc = subprocess.run(["node", "page.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2500:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- the page as first seen ---------------------------------------------

    def test_email_and_password_come_first_and_the_access_code_is_behind_a_link(self):
        out = self.run_page("""
out.hooks = main._all([]).filter((n) => "data-hook" in n.attrs).map((n) => n.attrs["data-hook"]);
out.codeHiddenAtFirst = hook("signin-form").hidden;
out.toggle = say("show-access-code");
out.emailType = hook("login-email").attrs.type;
out.emailAuto = hook("login-email").attrs.autocomplete;
out.passType = hook("login-password").attrs.type;
out.passAuto = hook("login-password").attrs.autocomplete;
out.submitLabel = say("login-submit");
await click("show-access-code");
out.codeHiddenAfter = hook("signin-form").hidden;
out.expanded = hook("show-access-code").attrs["aria-expanded"];
""")
        self.assertLess(out["hooks"].index("login-form"), out["hooks"].index("signin-form"))
        self.assertTrue(out["codeHiddenAtFirst"])
        self.assertFalse(out["codeHiddenAfter"])
        self.assertEqual(out["expanded"], "true")
        self.assertEqual(out["toggle"], "Have an access code?")
        self.assertEqual((out["emailType"], out["emailAuto"]), ("email", "username"))
        self.assertEqual((out["passType"], out["passAuto"]), ("password", "current-password"))
        self.assertEqual(out["submitLabel"], "Sign in")
        self.assertIn("Access code", out["page"])
        for old in ("Invite token", "Save token", "Clear token", "Paste your access token"):
            self.assertNotIn(old, out["page"])
        self.assertEqual([c for c in out["calls"] if c["url"] != "/meta"], [],
                         "a signed-out visitor triggers no request but the public /meta")

    def test_no_account_box_for_a_signed_out_visitor(self):
        out = self.run_page("out.account = hook('signin-account').hidden;")
        self.assertTrue(out["account"])

    # ---- logging in -----------------------------------------------------------

    def test_a_good_login_stores_the_token_and_opens_the_board(self):
        out = self.run_page("""
hook("login-email").value = "  Member@Example.com ";
hook("login-password").value = "correct horse battery";
await submit("login-form");
await settle();
out.passwordLeft = hook("login-password").value;
out.status = say("login-status");
""", routes={"POST /auth/login": LOGIN_OK, "GET /auth/password": {"code": 200, "body": {"has_password": True}}})
        login = [c for c in out["calls"] if c["url"] == "/auth/login"]
        self.assertEqual(len(login), 1)
        self.assertEqual(login[0]["body"], {"email": "Member@Example.com", "password": "correct horse battery"})
        self.assertEqual(out["storage"][TOKEN_KEY], "SESSION-TOKEN")
        self.assertEqual(out["hash"], "#/today")
        self.assertEqual(out["passwordLeft"], "", "the password field is emptied once it is sent")
        self.assertIn("Signed in", out["status"])
        # The next authed call carries the new token.
        self.assertIn("Bearer SESSION-TOKEN", [c["auth"] for c in out["calls"]])
        self.assertNotIn("correct horse battery", json.dumps(out["storage"]))

    def test_login_goes_to_the_page_the_visitor_was_sent_from_but_only_an_in_app_route(self):
        for nxt, want in (("#/props", "#/props"), ("https://evil.example/", "#/today"),
                          ("javascript:alert(1)", "#/today")):
            out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "correct horse battery";
await submit("login-form"); await settle();
""", routes={"POST /auth/login": LOGIN_OK}, query={"next": nxt})
            self.assertEqual(out["hash"], want, nxt)

    def test_a_refused_login_shows_the_servers_sentence_and_stores_nothing(self):
        cases = (
            (401, {"detail": {"error": "login_failed", "message": "That email and password do not match."}},
             "That email and password do not match."),
            (429, {"detail": {"error": "rate_limited", "message": "Too many attempts. Try again in about 15 minutes."}},
             "Too many attempts. Try again in about 15 minutes."),
            (403, {"detail": {"error": "no_access", "message": "This account has no active access, so no session was started."}},
             "This account has no active access, so no session was started."),
        )
        for code, body, sentence in cases:
            out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "wrong password!!";
await submit("login-form"); await settle();
out.status = say("login-status");
out.disabled = hook("login-submit").disabled;
""", routes={"POST /auth/login": {"code": code, "body": body}})
            self.assertEqual(out["status"], sentence)
            self.assertNotIn(TOKEN_KEY, out["storage"])
            self.assertEqual(out["hash"], "")
            self.assertFalse(out["disabled"], "the button comes back so they can try again")

    def test_an_unreachable_service_gets_a_calm_fallback(self):
        out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "wrong password!!";
await submit("login-form"); await settle();
out.status = say("login-status");
""", routes={"POST /auth/login": {"network": True}})
        self.assertIn("Could not sign in", out["status"])
        self.assertNotIn(TOKEN_KEY, out["storage"])

    def test_a_tester_whose_window_ended_sees_the_ended_state_not_the_board(self):
        ended = dict(LOGIN_OK["body"], access_active=False)
        out = self.run_page("""
hook("login-email").value = "a@b.co"; hook("login-password").value = "correct horse battery";
await submit("login-form"); await settle();
out.ended = say("tester-ended-line");
""", routes={
            "POST /auth/login": {"code": 200, "body": ended},
            "GET /billing/status": {"code": 401, "body": {"detail": {
                "error": "tester_access_expired", "expires_at": "2026-10-03T12:00:00+00:00"}}},
        }, meta={"billing": {"checkout": "off", "trial_days": 7, "price_cents": 1999}})
        self.assertEqual(out["hash"], "", "no navigation to a board that would refuse them")
        self.assertEqual(out["storage"][TOKEN_KEY], "SESSION-TOKEN")
        self.assertIn("early access ended", out["ended"].lower())

    # ---- the one-time "set a password" card ------------------------------------

    CARD_LINE = "Set a password so you can sign in with your email next time."

    def code_signin(self, has_password, storage=None, extra=""):
        return self.run_page("""
await click("show-access-code");
hook("invite-token-input").value = "pasted-access-code";
await submit("signin-form"); await settle();
out.cardHidden = hook("password-card").hidden;
out.cardLine = say("password-card-line");
""" + extra, routes={"GET /auth/password": {"code": 200, "body": {"has_password": has_password}}},
                             storage=storage or {})

    def test_after_an_access_code_signin_with_no_password_the_card_appears_once(self):
        out = self.code_signin(False)
        self.assertFalse(out["cardHidden"])
        self.assertEqual(out["cardLine"], self.CARD_LINE)
        self.assertEqual(out["storage"][SEEN_KEY], "1")
        self.assertEqual(out["storage"][TOKEN_KEY], "pasted-access-code")
        again = self.code_signin(False, storage={SEEN_KEY: "1"})
        self.assertTrue(again["cardHidden"], "shown once per device")

    def test_no_card_when_a_password_already_exists_or_the_code_was_bad(self):
        self.assertTrue(self.code_signin(True)["cardHidden"])
        out = self.run_page("""
await click("show-access-code");
hook("invite-token-input").value = "typo";
await submit("signin-form"); await settle();
out.cardHidden = hook("password-card").hidden;
""", routes={"GET /auth/password": {"code": 401, "body": {"detail": {"error": "unauthorized"}}}})
        self.assertTrue(out["cardHidden"])
        self.assertNotIn(SEEN_KEY, out["storage"])

    def test_the_card_saves_a_password_after_checking_the_two_fields_match(self):
        out = self.code_signin(False, extra="""
hook("password-card-form-new").value = "another long passphrase 42";
hook("password-card-form-again").value = "another long passphrase 43";
await submit("password-card-form"); await settle();
out.mismatch = say("password-card-form-status");
out.postsAfterMismatch = calls.filter((c) => c.method === "POST" && c.url === "/auth/password").length;
hook("password-card-form-again").value = "another long passphrase 42";
await submit("password-card-form"); await settle();
out.saved = say("password-card-form-status");
out.fieldsCleared = hook("password-card-form-new").value;
""")
        self.assertEqual(out["mismatch"], "The two new passwords do not match.")
        self.assertEqual(out["postsAfterMismatch"], 0)
        posts = [c for c in out["calls"] if c["method"] == "POST" and c["url"] == "/auth/password"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["body"], {"new_password": "another long passphrase 42"})
        self.assertEqual(posts[0]["auth"], "Bearer pasted-access-code")
        self.assertIn("Password saved", out["saved"])
        self.assertEqual(out["fieldsCleared"], "")

    def test_the_card_can_be_dismissed(self):
        out = self.code_signin(False, extra="""
await click("password-card-skip");
out.after = hook("password-card").hidden;
""")
        self.assertTrue(out["after"])

    def test_a_rejected_password_shows_the_servers_plain_message(self):
        out = self.run_page("""
await click("show-access-code");
hook("invite-token-input").value = "pasted-access-code";
await submit("signin-form"); await settle();
hook("password-card-form-new").value = "password123";
hook("password-card-form-again").value = "password123";
await submit("password-card-form"); await settle();
out.msg = say("password-card-form-status");
""", routes={"GET /auth/password": {"code": 200, "body": {"has_password": False}},
             "POST /auth/password": {"code": 400, "body": {"detail": {
                 "error": "password_rejected", "message": "That password is too common. Pick something less guessable."}}}})
        self.assertEqual(out["msg"], "That password is too common. Pick something less guessable.")

    # ---- signed in: change password, sign out ------------------------------------

    SIGNED_IN = {"aisportsanalysis.invite_token": "good-session"}

    def test_a_signed_in_visitor_gets_change_password_and_sign_out(self):
        out = self.run_page("""
out.boxHidden = hook("signin-account").hidden;
out.change = say("change-password-open");
out.signOut = say("sign-out");
out.slotHidden = hook("change-password-slot").hidden;
await click("change-password-open");
out.currentField = hook("change-password-current") !== null;
out.slotHiddenAfter = hook("change-password-slot").hidden;
""", storage=self.SIGNED_IN, routes={"GET /auth/password": {"code": 200, "body": {"has_password": True}}})
        self.assertFalse(out["boxHidden"])
        self.assertEqual((out["change"], out["signOut"]), ("Change password", "Sign out"))
        self.assertTrue(out["slotHidden"])
        self.assertFalse(out["slotHiddenAfter"])
        self.assertTrue(out["currentField"], "changing an existing password asks for the current one")

    def test_the_footer_link_opens_the_change_form_straight_away(self):
        out = self.run_page("""
out.open = hook("change-password-current") !== null;
""", storage=self.SIGNED_IN, query={"password": "1"},
                            routes={"GET /auth/password": {"code": 200, "body": {"has_password": True}}})
        self.assertTrue(out["open"])

    def test_changing_a_password_sends_both_and_shows_the_servers_refusal(self):
        script = """
hook("change-password-current").value = "old one";
hook("change-password-new").value = "another long passphrase 42";
hook("change-password-again").value = "another long passphrase 42";
await submit("change-password"); await settle();
out.msg = say("change-password-status");
"""
        out = self.run_page(script, storage=self.SIGNED_IN, query={"password": "1"}, routes={
            "GET /auth/password": {"code": 200, "body": {"has_password": True}},
            "POST /auth/password": {"code": 403, "body": {"detail": {
                "error": "current_password_wrong", "message": "Your current password is not right."}}}})
        post = [c for c in out["calls"] if c["method"] == "POST" and c["url"] == "/auth/password"][0]
        self.assertEqual(post["body"], {"new_password": "another long passphrase 42",
                                        "current_password": "old one"})
        self.assertEqual(out["msg"], "Your current password is not right.")

    def test_no_account_box_when_the_stored_code_is_not_good(self):
        out = self.run_page("out.boxHidden = hook('signin-account').hidden;", storage=self.SIGNED_IN,
                            routes={"GET /auth/password": {"code": 401, "body": {"detail": {"error": "unauthorized"}}}})
        self.assertTrue(out["boxHidden"])

    def test_sign_out_revokes_on_the_server_and_forgets_the_token_here(self):
        out = self.run_page("""
await click("sign-out"); await settle();
out.boxHidden = hook("signin-account").hidden;
out.status = say("login-status");
""", storage=self.SIGNED_IN, routes={
            "GET /auth/password": {"code": 200, "body": {"has_password": True}},
            "POST /auth/logout": {"code": 200, "body": {"ok": True, "revoked": True}}})
        logout = [c for c in out["calls"] if c["url"] == "/auth/logout"]
        self.assertEqual(len(logout), 1)
        self.assertEqual(logout[0]["auth"], "Bearer good-session", "revokes the token it held")
        self.assertNotIn(TOKEN_KEY, out["storage"])
        self.assertTrue(out["boxHidden"])
        self.assertEqual(out["status"], "Signed out.")

    def test_sign_out_still_signs_out_here_if_the_server_cannot_be_reached(self):
        out = self.run_page('await click("sign-out"); await settle();', storage=self.SIGNED_IN, routes={
            "GET /auth/password": {"code": 200, "body": {"has_password": True}},
            "POST /auth/logout": {"network": True}})
        self.assertNotIn(TOKEN_KEY, out["storage"])


class SigninSourceHygiene(unittest.TestCase):
    """Cheap structural facts the behavioural tests above cannot see."""

    def setUp(self):
        self.source = (JS / "signin.js").read_text(encoding="utf-8")

    def test_password_fields_are_password_inputs_with_the_right_autocomplete(self):
        self.assertIn('autocomplete: "username"', self.source)
        self.assertIn('autocomplete: "current-password"', self.source)
        self.assertIn('autocomplete: "new-password"', self.source)
        self.assertNotRegex(self.source, r'type: "text"[^}]*password')

    def test_nothing_is_written_as_html_and_no_password_goes_to_storage_or_a_url(self):
        self.assertNotIn("innerHTML", self.source)
        self.assertNotIn("console.", self.source)
        for line in self.source.splitlines():
            if "setItem" in line or "setToken" in line or "location" in line:
                self.assertNotRegex(line, r"password(Field|\.input|\.value)|new_password", line)

    def test_the_stylesheet_is_linked_and_the_footer_offers_change_password(self):
        index = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="css/signin.css"', index)
        self.assertTrue((WEB / "css" / "signin.css").exists())
        meta = (JS / "meta.js").read_text(encoding="utf-8")
        self.assertIn('"data-hook": "footer-password"', meta)
        self.assertIn("Change password", meta)

    def test_the_stylesheet_is_scoped_to_the_sign_in_page_only(self):
        css = (WEB / "css" / "signin.css").read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for selector in re.findall(r"(?m)^([^{}@\n][^{}]*)\{", css):
            for part in selector.split(","):
                self.assertTrue(part.strip().startswith(".signin"), part.strip())


if __name__ == "__main__":
    unittest.main()
