"""Coming back to the checkout success page, and getting back in without it.

THE STORY (2026-10-05, W02 / W03). Stripe sends the buyer to
`#/signup/complete?session_id=...`. The page exchanges the session id for the
access token, stores it, and scrubs the session id from the address (kept, on
purpose: the owner rejected leaving it in history, docs/decisions/
closed-tab-token-recovery.md). The buyer who then reopens `#/signup/complete`
from history met "Check your link. No token was included in this link." on a
browser that held a perfectly good token; a reload after the re-read window
closed trusted whatever was stored without asking the server; and a real
refusal ended on "Almost there." with nothing to do next.

PART 1 (the page, run for real under node against a small fake DOM, the
pattern of tests/test_expired_tester_paid_path.py). Whenever the page would
rely on a stored token it asks GET /billing/status with it:

  * 200                      -> "You're signed in." and the app link
  * 401 unknown or revoked   -> the stored token is cleared; an honest
                                signed-out state: nothing is lost, Sign in,
                                Get help
  * 401 tester_access_expired-> kept; the real state (the ended date) and the
                                existing upgrade path (the sign-in page)
  * network / 5xx / 429      -> "could not be checked", the token kept, retry
  * no token, no session id  -> the same honest state, never "No token was
                                included"
  * a refusal after a session id -> the same honest state, not a dead end

and a PYTHON class pins that /billing/status really does distinguish those
for a tester, a paid user, a lapsed paid user, an expired tester and a revoked
token (the client's whole decision rests on it).

PART 2 (support recovery, not self-service; there is no email sender): the
admin re-issue route keeps the window and paid-through, revokes what it
replaces, is written to the audit log with a reason, answers an unknown email
exactly like an ineligible account, and needs the admin credential. A buyer
whose payment only ever reached the webhook (no browser tab) is recoverable
through it.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
SIGNUP_JS = JS / "signup.js"

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

# ===========================================================================
# PART 1 -- the page under node
# ===========================================================================

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
  get isConnected() { let n = this; while (n) { if (n.isRoot) return true; n = n.parentNode; } return false; }
  closest() { return null; }
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
const store = new Map();
if (scenario.token) store.set("aisportsanalysis.invite_token", scenario.token);
const replaced = [];          // every address history.replaceState was given
const assigned = [];          // every URL window.location.assign was given
const wrote = [];             // every value written to storage, in order
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { wrote.push([k, String(v)]); store.set(k, String(v)); },
    removeItem: (k) => store.delete(k),
  },
  location: { search: scenario.search || "", host: "linehound.test", pathname: "/index.html",
              hash: scenario.hash || "", assign(url) { assigned.push(String(url)); } },
  history: { replaceState(state, title, url) { replaced.push(String(url)); } },
  addEventListener() {}, dispatchEvent() { return true; },
  crypto: globalThis.crypto,
};

// The poll sleeps 2000 ms between asks and gives up after 60 s: run that on a
// fake clock so a "never lands" scenario takes milliseconds. api.js's own
// 20 s abort timer keeps the real setTimeout.
let clock = Date.now();
Date.now = () => clock;
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => {
  if (ms === 2000) { clock += 2000; return realSetTimeout(fn, 0, ...rest); }
  return realSetTimeout(fn, ms, ...rest);
};

const calls = [];
const seq = { status: 0, complete: 0 };
const pickStep = (list, key) => {
  const step = list[Math.min(seq[key], list.length - 1)]; seq[key] += 1; return step;
};
globalThis.fetch = async (url, init) => {
  url = String(url);
  const headers = (init && init.headers) || {};
  calls.push({ url, method: (init && init.method) || "GET", auth: headers.Authorization || null });
  const json = (status, bodyObj) => ({ ok: status < 400, status, text: async () => JSON.stringify(bodyObj) });
  if (url.startsWith("/meta")) {
    if (scenario.meta === null) throw new Error("offline");
    return json(200, scenario.meta || { billing: { checkout: "off", trial_days: 7, price_cents: 1999 } });
  }
  if (url === "/billing/status") {
    // Per-token answers (a stored token and a freshly exchanged one can differ),
    // else the numbered sequence.
    const sent = String(headers.Authorization || "").replace(/^Bearer /, "");
    const byToken = scenario.statusByToken && scenario.statusByToken[sent];
    const r = byToken || pickStep(scenario.status || [{ code: 200, body: { status: "not_configured" } }], "status");
    // Another tab stores a different token while this request is in flight.
    if (scenario.swapDuringStatus) { store.set("aisportsanalysis.invite_token", scenario.swapDuringStatus); }
    if (r.network) throw new Error("offline");
    return json(r.code, r.body);
  }
  if (url.startsWith("/signup/complete")) {
    const r = pickStep(scenario.complete || [{ code: 404, body: { detail: { error: "not_found" } } }], "complete");
    if (r.network) throw new Error("offline");
    return json(r.code, r.body);
  }
  return json(200, {});
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const hooks = (n) => n._all([]).filter((x) => "data-hook" in x.attrs).map((x) => x.attrs["data-hook"]);
const hrefs = (n) => n._all([]).filter((x) => x.tagName === "A")
  .map((x) => ({ hook: x.attrs["data-hook"] || null, href: x.attrs.href || null, text: x.textContent }));
const settle = () => new Promise((r) => realSetTimeout(r, 30));
const main = document.createElement("main"); body.appendChild(main);

const { renderSignupComplete } = await import("./signup.js");
await renderSignupComplete(main, scenario.query || {});
await settle();
const first = { page: text(main), hooks: hooks(main), hrefs: hrefs(main) };
let afterRetry = null;
if (scenario.retry) {
  const button = main.querySelector("[data-hook='signup-check-retry']");
  if (!button) throw new Error("no retry button on the page: " + first.page);
  await button.listeners.click[0]();
  await settle();
  afterRetry = { page: text(main), hooks: hooks(main), hrefs: hrefs(main) };
}
const stored = store.has("aisportsanalysis.invite_token") ? store.get("aisportsanalysis.invite_token") : null;
console.log("@@" + JSON.stringify({ ...first, afterRetry, stored, calls, replaced, assigned, wrote }));
"""

OFF_META = {"billing": {"checkout": "off", "trial_days": 7, "price_cents": 1999}}
EXPIRED_401 = {"code": 401, "body": {"detail": {
    "error": "tester_access_expired", "message": "early access has ended for this token",
    "expires_at": "2026-10-03T12:00:00+00:00"}}}
PLAIN_401 = {"code": 401, "body": {"detail": {
    "error": "unauthorized", "message": "missing, invalid, expired, or revoked token"}}}
OK_TESTER = {"code": 200, "body": {"status": "not_configured"}}
NETWORK = {"network": True}

SESSION_QUERY = {"session_id": "cs_test_return_1"}
NOT_YET = {"code": 404, "body": {"detail": {"error": "not_found"}}}
BUYER_TOKEN = "tok_buyer_long_lived_secret_value"


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheReturnPageUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_scenario(self, **scenario):
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    @staticmethod
    def link_to(out, href):
        return [h for h in out["hrefs"] if h["href"] == href]

    def assert_honest_signed_out(self, out):
        """The one recoverable state every dead end now ends in: nothing is lost,
        the two ways on are links, and it never claims the link was wrong."""
        page = out["page"]
        self.assertIn("not lost", page)
        self.assertNotIn("No token was included", page)
        self.assertNotIn("Check your link", page)
        self.assertNotIn("Almost there", page)
        self.assertTrue(self.link_to(out, "#/signin"), "no Sign in link")
        self.assertTrue(self.link_to(out, "#/support"), "no Get help link")

    # ---- a stored token the server accepts ------------------------------------

    def test_a_valid_stored_token_is_checked_with_the_server_and_signs_you_in(self):
        out = self.run_scenario(token="tok_tester_good", query={}, status=[OK_TESTER])
        self.assertIn("You're signed in.", out["page"])
        self.assertTrue(self.link_to(out, "index.html#/today"), "no link into the app")
        self.assertNotIn("No token was included", out["page"])
        # the page asked the server, with the stored token
        self.assertIn({"url": "/billing/status", "method": "GET", "auth": "Bearer tok_tester_good"},
                      out["calls"])
        self.assertEqual(out["stored"], "tok_tester_good")

    def test_a_paid_user_whose_period_has_ended_is_told_so_and_pointed_at_billing(self):
        lapsed = {"code": 200, "body": {"status": "canceled",
                                        "current_period_end": "2026-09-01T00:00:00+00:00"}}
        out = self.run_scenario(token="tok_paid_lapsed", query={}, status=[lapsed])
        self.assertIn("You're signed in.", out["page"])
        self.assertTrue(self.link_to(out, "#/billing"), "no way to the billing page")
        self.assertEqual(out["stored"], "tok_paid_lapsed")

    def test_a_paid_user_in_date_gets_no_lapsed_note(self):
        live = {"code": 200, "body": {"status": "active",
                                      "current_period_end": "2099-01-01T00:00:00+00:00"}}
        out = self.run_scenario(token="tok_paid", query={}, status=[live])
        self.assertIn("You're signed in.", out["page"])
        self.assertFalse(self.link_to(out, "#/billing"))

    def test_after_the_reread_window_a_stored_token_is_still_asked_about(self):
        # session id in the address, the server has stopped giving the token out
        # (404 for ever), and the device holds one: that used to be trusted unseen.
        out = self.run_scenario(token="tok_stored", query=SESSION_QUERY,
                                complete=[NOT_YET], status=[OK_TESTER])
        self.assertIn("You're signed in.", out["page"])
        self.assertIn({"url": "/billing/status", "method": "GET", "auth": "Bearer tok_stored"},
                      out["calls"])

    def test_a_stored_token_the_server_refuses_is_not_trusted_whatever_the_poll_said(self):
        # a 404 for a minute: the checkout may genuinely still be in flight, so the
        # buyer keeps the screen that has "Check again"; the dead token is gone either way
        out = self.run_scenario(token="tok_dead", query=SESSION_QUERY,
                                complete=[NOT_YET], status=[PLAIN_401])
        self.assertNotIn("You're signed in.", out["page"])
        self.assertIsNone(out["stored"])
        self.assertIn("signup-retry", out["hooks"])
        self.assertTrue(self.link_to(out, "#/support"))
        # a flat refusal is not in flight: the honest signed-out state
        out = self.run_scenario(token="tok_dead", query=SESSION_QUERY,
                                complete=[{"code": 400, "body": {"detail": "bad"}}],
                                status=[PLAIN_401])
        self.assertIsNone(out["stored"])
        self.assert_honest_signed_out(out)

    # ---- no token at all --------------------------------------------------------

    def test_no_token_and_no_session_id_is_an_honest_state_not_a_broken_link(self):
        out = self.run_scenario(token=None, query={})
        self.assert_honest_signed_out(out)
        # nothing to check, so nothing was asked
        self.assertEqual([c for c in out["calls"] if c["url"] == "/billing/status"], [])
        self.assertNotIn("You're signed in.", out["page"])

    # ---- a token the server does not know ----------------------------------------

    def test_a_revoked_or_unknown_token_is_cleared_and_you_are_told_what_to_do(self):
        out = self.run_scenario(token="tok_revoked", query={}, status=[PLAIN_401])
        self.assertIsNone(out["stored"], "a token the server refused was kept")
        self.assertNotIn("You're signed in.", out["page"])
        self.assert_honest_signed_out(out)

    # ---- an expired tester -------------------------------------------------------

    def test_an_expired_tester_token_shows_the_real_state_and_keeps_the_token(self):
        out = self.run_scenario(token="tok_tester_old", query={}, status=[EXPIRED_401],
                                meta=OFF_META)
        self.assertIn("Your early access ended on 3 October 2026.", out["page"])
        self.assertNotIn("You're signed in.", out["page"])
        self.assertNotIn("not lost", out["page"].split("Your early access ended")[0])
        self.assertEqual(out["stored"], "tok_tester_old", "the expired token is how they convert")
        # the existing upgrade path (the sign-in page reads the stored token)
        self.assertTrue(self.link_to(out, "#/signin"))
        self.assertTrue(self.link_to(out, "#/support"))
        self.assertIn("Paid plans are not open yet", out["page"])

    # ---- the server cannot be reached ----------------------------------------------

    def test_an_unreachable_server_keeps_the_token_and_offers_a_retry(self):
        for name, step in (("offline", NETWORK),
                           ("server error", {"code": 503, "body": {"detail": "down"}}),
                           ("throttled", {"code": 429, "body": {"detail": "slow down"}})):
            with self.subTest(failure=name):
                out = self.run_scenario(token="tok_keep_me", query={}, status=[step])
                self.assertIn("could not check", out["page"])
                self.assertNotIn("You're signed in.", out["page"])
                self.assertEqual(out["stored"], "tok_keep_me")
                self.assertIn("signup-check-retry", out["hooks"])

    def test_the_retry_asks_again_and_a_good_answer_signs_you_in(self):
        out = self.run_scenario(token="tok_keep_me", query={}, retry=True,
                                status=[NETWORK, OK_TESTER])
        self.assertIn("could not check", out["page"])
        self.assertIn("You're signed in.", out["afterRetry"]["page"])
        self.assertEqual(out["stored"], "tok_keep_me")
        self.assertEqual(len([c for c in out["calls"] if c["url"] == "/billing/status"]), 2)

    # ---- the real refusal after a session id ------------------------------------------

    def test_a_refusal_after_a_session_id_is_not_a_dead_end(self):
        out = self.run_scenario(token=None, query=SESSION_QUERY,
                                complete=[{"code": 400, "body": {"detail": "bad session"}}])
        self.assert_honest_signed_out(out)
        self.assertNotIn("bad session", out["page"])

    # ---- the address bar ------------------------------------------------------------------

    def test_the_session_id_is_still_scrubbed_from_the_address_after_activation(self):
        out = self.run_scenario(
            token=None, query=SESSION_QUERY,
            hash="#/signup/complete?session_id=cs_test_return_1",
            complete=[NOT_YET, {"code": 200, "body": {"user_id": 3, "token": BUYER_TOKEN}}])
        self.assertIn("You're in.", out["page"])
        self.assertEqual(out["stored"], BUYER_TOKEN)
        self.assertTrue(out["replaced"], "the address was never rewritten")
        self.assertEqual(out["replaced"][-1], "/index.html#/signup/complete")
        for url in out["replaced"]:
            self.assertNotIn("session_id", url)
            self.assertNotIn("cs_test", url)

    def test_no_long_lived_secret_is_ever_written_to_the_address(self):
        scenarios = [
            dict(token=None, query=SESSION_QUERY,
                 complete=[{"code": 200, "body": {"user_id": 3, "token": BUYER_TOKEN}}]),
            dict(token=BUYER_TOKEN, query={}, status=[OK_TESTER]),
            dict(token=BUYER_TOKEN, query={}, status=[PLAIN_401]),
            dict(token=BUYER_TOKEN, query={}, status=[EXPIRED_401]),
            dict(token=BUYER_TOKEN, query={}, status=[NETWORK]),
            dict(token=None, query={"token": BUYER_TOKEN}),
        ]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                out = self.run_scenario(**scenario)
                for url in out["replaced"] + out["assigned"]:
                    self.assertNotIn(BUYER_TOKEN, url)
                # and the page asks the server with a header, never a query string
                for call in out["calls"]:
                    self.assertNotIn(BUYER_TOKEN, call["url"])

    def test_a_token_that_arrived_on_the_address_is_stored_and_then_scrubbed_from_it(self):
        out = self.run_scenario(token=None, query={"token": BUYER_TOKEN},
                                hash="#/signup/complete?token=" + BUYER_TOKEN)
        self.assertEqual(out["stored"], BUYER_TOKEN)
        self.assertTrue(out["replaced"], "the token was left in the address bar")
        self.assertEqual(out["replaced"][-1], "/index.html#/signup/complete")

    def test_option_b_is_not_applied_the_session_id_is_not_kept_in_history(self):
        src = SIGNUP_JS.read_text(encoding="utf-8")
        self.assertNotIn("SIGNUP_SESSION_ID_LIFETIME_MS", src)
        self.assertNotIn("dropTimer", src)

    # ---- review 2026-10-05: a token the server hands out must be a token it accepts ----

    def test_an_exchanged_token_the_server_rejects_never_replaces_a_good_stored_one(self):
        # a re-issue replaced the buyer's token; the activation bridge still gave out the
        # old one (before the server fix), and this page stored it over the good one
        out = self.run_scenario(
            token="tok_good", query=SESSION_QUERY,
            complete=[{"code": 200, "body": {"user_id": 3, "token": "tok_dead_activation"}}],
            statusByToken={"tok_dead_activation": PLAIN_401, "tok_good": OK_TESTER})
        self.assertEqual(out["stored"], "tok_good")
        for _key, value in out["wrote"]:
            self.assertNotEqual(value, "tok_dead_activation", "the dead token was written to storage")
        self.assertNotIn("tok_dead_activation", out["page"])
        # what the buyer is told is true: the token this browser holds works
        self.assertIn("You're signed in.", out["page"])
        # the exchanged token was asked about with its own header, the stored one after it
        auths = [c["auth"] for c in out["calls"] if c["url"] == "/billing/status"]
        self.assertEqual(auths, ["Bearer tok_dead_activation", "Bearer tok_good"])

    def test_an_exchanged_token_the_server_rejects_with_nothing_stored_is_not_signed_in(self):
        out = self.run_scenario(
            token=None, query=SESSION_QUERY,
            complete=[{"code": 200, "body": {"user_id": 3, "token": "tok_dead_activation"}}],
            statusByToken={"tok_dead_activation": PLAIN_401})
        self.assertIsNone(out["stored"])
        self.assertNotIn("You're in.", out["page"])
        self.assertNotIn("You're signed in.", out["page"])
        self.assertNotIn("tok_dead_activation", out["page"])
        self.assert_honest_signed_out(out)

    def test_an_exchanged_token_the_server_accepts_replaces_a_dead_stored_one(self):
        out = self.run_scenario(
            token="tok_old_dead", query=SESSION_QUERY,
            complete=[{"code": 200, "body": {"user_id": 3, "token": "tok_new"}}],
            statusByToken={"tok_new": OK_TESTER, "tok_old_dead": PLAIN_401})
        self.assertEqual(out["stored"], "tok_new")
        self.assertIn("You're in.", out["page"])
        self.assertIn("tok_new", out["page"])

    def test_when_the_exchanged_token_cannot_be_checked_it_is_not_stored_and_retry_works(self):
        out = self.run_scenario(
            token="tok_good", query=SESSION_QUERY, retry=True,
            complete=[{"code": 200, "body": {"user_id": 3, "token": "tok_new"}}],
            statusByToken={"tok_new": NETWORK, "tok_good": OK_TESTER})
        self.assertIn("could not check", out["page"])
        self.assertNotIn("You're in.", out["page"])
        self.assertEqual(out["stored"], "tok_good")
        self.assertIn("signup-check-retry", out["hooks"])

    # ---- review 2026-10-05: clear what was checked, not what is stored now ----

    def test_a_401_clears_only_the_token_that_was_checked(self):
        # another tab signed in with a fresh token while the answer was in flight
        out = self.run_scenario(token="tok_checked_dead", query={}, status=[PLAIN_401],
                                swapDuringStatus="tok_signed_in_meanwhile")
        self.assertEqual(out["stored"], "tok_signed_in_meanwhile")
        self.assertNotIn("You're signed in.", out["page"])

    def test_a_401_still_clears_the_token_when_nothing_changed_meanwhile(self):
        out = self.run_scenario(token="tok_checked_dead", query={}, status=[PLAIN_401])
        self.assertIsNone(out["stored"])


# ===========================================================================
# What the page's decision rests on: GET /billing/status
# ===========================================================================

if HAS_FASTAPI:
    from tests.test_tester_journey_e2e import _Journey, _asgi, ADMIN
else:  # Linux CI has no FastAPI: the classes below are skipped, but must still load
    _Journey = _Case = unittest.TestCase


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class BillingStatusTellsTheKindsOfTokenApart(_Journey):
    """The page treats 200 as "known" and a plain 401 as "unknown or revoked";
    these are the five shapes it will meet."""

    def test_a_tester_is_200_not_configured(self):
        token = self.grant("a@example.test")["token"]
        status, body = self.call("GET", "/billing/status", token=token)
        self.assertEqual((status, body), (200, {"status": "not_configured"}))

    def test_an_expired_tester_is_the_named_401(self):
        grant = self.grant("a@example.test")
        self.expire(grant["user_id"])
        status, body = self.call("GET", "/billing/status", token=grant["token"])
        self.assertEqual((status, body["detail"]["error"]), (401, "tester_access_expired"))

    def test_a_revoked_token_is_the_plain_401(self):
        grant = self.grant("a@example.test")
        from src.appstate import users as users_store
        users_store.revoke_all_tokens(grant["user_id"])
        status, body = self.call("GET", "/billing/status", token=grant["token"])
        self.assertEqual((status, body["detail"]["error"]), (401, "unauthorized"))

    def test_an_unknown_token_is_the_plain_401(self):
        status, body = self.call("GET", "/billing/status", token="never-issued")
        self.assertEqual((status, body["detail"]["error"]), (401, "unauthorized"))

    def test_a_paid_user_is_200_even_after_the_period_ended(self):
        from src.appstate import customers, users as users_store
        user = users_store.create_user("payer@example.test", status="active", plan="beta")
        token = users_store.issue_invite_token(user.id)
        customers.upsert_subscription(
            user.id, "sub_x", "canceled",
            current_period_end=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat())
        status, body = self.call("GET", "/billing/status", token=token)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "canceled")


# ===========================================================================
# PART 2 -- support recovery: POST /admin/users/reissue
# ===========================================================================

REASON = "lost the token; verified by reply from the account mailbox, ticket 41"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ReissueRoute(_Journey):
    """The lost-token door, through the real app over ASGI so the admin
    dependency is exercised (a direct function call would skip it)."""

    def reissue(self, admin=True, **body):
        body.setdefault("reason", REASON)
        return self.call("POST", "/admin/users/reissue", admin=admin, body=body)

    def paying_user(self, email="payer@example.test", *, days_left=20):
        from src.appstate import customers, users as users_store
        user = users_store.create_user(email, status="active", plan="beta")
        token = users_store.issue_invite_token(user.id)
        ends = (datetime.now(timezone.utc) + timedelta(days=days_left)).isoformat()
        customers.upsert_subscription(user.id, "sub_reissue", "active", current_period_end=ends,
                                      paid_through=ends)
        return user, token, ends

    # ---- who may call it --------------------------------------------------------

    def test_it_needs_the_admin_credential(self):
        grant = self.grant("a@example.test")
        for headers in ({}, {"X-Admin-Token": "wrong"}, {"Authorization": f"Bearer {grant['token']}"}):
            status, _ = _asgi(self.app, "POST", "/admin/users/reissue", headers=headers,
                              body={"user_id": grant["user_id"], "reason": REASON})
            self.assertEqual(status, 401, headers)
        # and nothing happened: the tester's own token is still alive
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)

    def test_without_an_admin_token_configured_the_route_does_not_exist(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("APP_ADMIN_TOKEN", None)
            status, _ = self.reissue(email="a@example.test")
        self.assertEqual(status, 404)

    # ---- a paid user ----------------------------------------------------------------

    def test_a_paid_users_reissue_keeps_paid_through_and_the_old_token_stops_working(self):
        from src.appstate import customers
        user, old, _ends = self.paying_user()
        before = customers.get_subscription_record(user.id)
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=old)[0], 200)
        status, fresh = self.reissue(email="Payer@Example.test ")
        self.assertEqual(status, 200, fresh)
        self.assertEqual(fresh["kind"], "subscriber")
        self.assertEqual(customers.get_subscription_record(user.id), before,
                         "a re-issue must not touch the subscription record")
        self.assertEqual(customers.get_subscription_record(user.id)["paid_through"],
                         before["paid_through"])
        # the new token opens the paid surface; the replaced one is refused on it
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=fresh["token"])[0], 200)
        status, body = self.call("GET", f"/games/{self.date}", token=old)
        self.assertEqual((status, body["detail"]["error"]), (401, "unauthorized"))
        self.assertEqual(self.call("GET", "/billing/status", token=old)[0], 401)

    # ---- a tester -----------------------------------------------------------------------

    def test_a_testers_reissue_changes_neither_the_window_nor_the_slots(self):
        grant = self.grant("a@example.test")
        before = self.call("GET", "/admin/testers", admin=True)[1]
        status, fresh = self.reissue(user_id=grant["user_id"])
        self.assertEqual((status, fresh["kind"]), (200, "tester"))
        after = self.call("GET", "/admin/testers", admin=True)[1]
        self.assertEqual((after["granted"], after["remaining"]), (before["granted"], before["remaining"]))
        self.assertEqual(after["testers"][0]["expires_at"], before["testers"][0]["expires_at"])
        self.assertEqual(after["testers"][0]["extensions"], [])

    def test_an_expired_testers_reissue_is_a_token_that_can_still_start_the_conversion(self):
        from src.appstate import tester_upgrade
        grant = self.grant("a@example.test")
        self.expire(grant["user_id"])
        status, fresh = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 200, fresh)
        # it does not reopen the week...
        status, body = self.call("GET", f"/games/{self.date}", token=fresh["token"])
        self.assertEqual((status, body["detail"]["error"]), (401, "tester_access_expired"))
        # ...but it identifies the account to the one door an ended tester has
        self.assertIsNotNone(tester_upgrade.tester_for_token(fresh["token"]))
        self.assertIsNone(tester_upgrade.tester_for_token(grant["token"]),
                          "the replaced token must be revoked")

    # ---- what it refuses, and how it says so ----------------------------------------------

    def test_an_unknown_email_is_refused_exactly_like_an_account_with_nothing_to_give(self):
        self.signup("waiting@example.test")        # a real account, waitlisted: no token to re-issue
        unknown = self.reissue(email="nobody-at-all@example.test")
        waitlisted = self.reissue(email="waiting@example.test")
        by_id = self.reissue(user_id=987654)
        self.assertEqual(unknown[0], 409)
        self.assertEqual(unknown, waitlisted)
        self.assertEqual(unknown, by_id)
        blob = json.dumps(unknown[1]).lower()
        for word in ("no such", "not found", "unknown", "exist", "waitlist"):
            self.assertNotIn(word, blob)

    def test_a_lapsed_subscriber_and_a_suspended_tester_get_the_same_refusal(self):
        from src.appstate import users as users_store
        user, _token, _ends = self.paying_user("lapsed@example.test", days_left=-3)
        grant = self.grant("susp@example.test")
        users_store.set_user_status(grant["user_id"], "suspended")
        reference = self.reissue(email="nobody-at-all@example.test")
        self.assertEqual(self.reissue(user_id=user.id), reference)
        self.assertEqual(self.reissue(user_id=grant["user_id"]), reference)

    def test_a_refusal_changes_nothing(self):
        from src.appstate import users as users_store
        user, token, _ends = self.paying_user("lapsed@example.test", days_left=-3)
        self.reissue(user_id=user.id)
        self.assertIsNotNone(users_store.authenticate(token))

    def test_the_body_is_checked_before_any_lookup(self):
        grant = self.grant("a@example.test")
        for body, error in (({"email": "a@example.test", "user_id": grant["user_id"]}, None),
                            ({}, None),
                            ({"email": "a@example.test", "reason": ""}, "reason_required"),
                            ({"email": "a@example.test", "reason": "   "}, "reason_required"),
                            ({"email": "a@example.test", "reason": "x" * 501}, "reason_too_long")):
            status, answer = self.call("POST", "/admin/users/reissue", admin=True, body=body)
            self.assertEqual(status, 400, body)
            if error:
                self.assertEqual(answer["detail"]["error"], error)
        # a missing reason is the same 400 for an account that does not exist
        status, answer = self.call("POST", "/admin/users/reissue", admin=True,
                                   body={"email": "nobody@example.test"})
        self.assertEqual((status, answer["detail"]["error"]), (400, "reason_required"))
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)

    def test_a_reason_that_is_a_pasted_token_is_refused(self):
        grant = self.grant("a@example.test")
        status, answer = self.reissue(user_id=grant["user_id"], reason=grant["token"])
        self.assertEqual((status, answer["detail"]["error"]), (400, "reason_looks_like_a_secret"))
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)

    # ---- the audit log --------------------------------------------------------------------------

    def audit(self):
        from src.appstate import events
        return [e for e in events.list_events() if e.kind == events.SUPPORT_TOKEN_REISSUED]

    def test_every_issue_is_in_the_audit_log_with_the_reason_and_never_a_token(self):
        from src.appstate import events
        grant = self.grant("a@example.test")
        status, fresh = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 200)
        logged = self.audit()
        self.assertEqual(len(logged), 1)
        entry = logged[0]
        self.assertEqual(entry.user_hash, events.hash_user_id(grant["user_id"]))
        self.assertEqual(entry.properties["reason"], REASON)
        self.assertEqual((entry.properties["kind"], entry.properties["revoked_tokens"]), ("tester", 1))
        dump = json.dumps(entry.properties) + str(entry)
        for secret in (fresh["token"], grant["token"], "a@example.test"):
            self.assertNotIn(secret, dump)

    def test_a_refusal_writes_nothing_to_the_audit_log(self):
        self.reissue(email="nobody-at-all@example.test")
        self.assertEqual(self.audit(), [])

    def test_when_the_audit_log_cannot_be_written_nothing_is_issued_or_revoked(self):
        # the audit row is written inside the token change's transaction (see
        # tests/test_reissue_review.py), so a failed write rolls the change back
        grant = self.grant("a@example.test")
        with mock.patch("api.admin._write_reissue_audit", side_effect=sqlite3.OperationalError("disk full")):
            status, answer = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 503, answer)
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0], 1)

    def test_the_new_token_is_never_printed(self):
        import io
        grant = self.grant("a@example.test")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            _, fresh = self.reissue(user_id=grant["user_id"])
        self.assertNotIn(fresh["token"], out.getvalue() + err.getvalue())


# ---------------------------------------------------------------------------
# A buyer whose payment only ever reached the webhook
# ---------------------------------------------------------------------------

if HAS_FASTAPI:
    from tests.test_billing_acceptance_path import _Case
    from src.appstate import customers


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AWebhookOnlyBuyerIsRecoverable(_Case):
    """No browser tab was ever involved: Stripe's webhook landed, the success
    page never ran (a phone that died on the redirect), and the activation
    token was never read. Access is on disk; the token is one support
    re-issue away."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"APP_DB_PATH": str(self.db)})
        env.start()
        self.addCleanup(env.stop)
        # the audit log lives in the same file, whatever another module left patched
        from src.appstate import events as events_module
        patcher = mock.patch.object(events_module, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_verified_purchase_grants_access_and_support_can_hand_over_a_token(self):
        from api.admin import ReissueAccessRequest, reissue_access_token
        from src.appstate import events
        started = self.signup("webhook-only@example.com")
        user_id = started["user_id"]
        self.webhook(self.completed_event(user_id))
        self.webhook(self.subscription_event("created", "trialing"))

        # access exists with no page ever having asked for the token
        self.assertTrue(customers.has_paid_access(user_id))
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT raw_token, retrieved_at FROM signup_activation_tokens "
                               "WHERE user_id = ?", (user_id,)).fetchone()
        self.assertIsNotNone(row, "the webhook minted no activation token")
        self.assertIsNone(row[1], "a browser read the token; this test is about nobody having")
        before = customers.get_subscription_record(user_id)

        fresh = reissue_access_token(ReissueAccessRequest(email="webhook-only@example.com",
                                                          reason=REASON), _admin=None)
        self.assertEqual(fresh["kind"], "subscriber")
        self.assertEqual(self.open_paid_page(fresh["token"]).id, user_id)
        self.assertEqual(customers.get_subscription_record(user_id), before)
        # the activation token that was waiting to be read is a replaced credential too
        from api.auth import get_current_user
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            get_current_user(authorization=f"Bearer {row[0]}", request=None)
        logged = [e for e in events.list_events() if e.kind == events.SUPPORT_TOKEN_REISSUED]
        self.assertEqual([e.properties["reason"] for e in logged], [REASON])


# ---------------------------------------------------------------------------
# The store primitive, the support page and the two documents
# ---------------------------------------------------------------------------

class ReissueTokenStore(unittest.TestCase):
    """users.reissue_token: replace every token with one that ends exactly where
    the caller says, in one transaction."""

    def setUp(self):
        from src.appstate import users as users_store
        self.users = users_store
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = users_store.create_user("store@example.test", status="active")

    def test_it_ends_the_new_token_exactly_where_asked_and_revokes_the_rest(self):
        old_a = self.users.issue_invite_token(self.user.id)
        old_b = self.users.issue_invite_token(self.user.id)
        when = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
        ends = when + timedelta(days=3, hours=2)
        fresh, revoked = self.users.reissue_token(self.user.id, expires_at=ends, now=when)
        self.assertEqual(revoked, 2)
        self.assertIsNone(self.users.authenticate(old_a))
        self.assertIsNone(self.users.authenticate(old_b))
        self.assertIsNotNone(self.users.authenticate(fresh, now=when))
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            stored = conn.execute("SELECT expires_at FROM tokens WHERE revoked_at IS NULL").fetchall()
        self.assertEqual([datetime.fromisoformat(r[0]) for r in stored], [ends])
        self.assertIsNone(self.users.authenticate(fresh, now=ends))     # the same boundary as every token

    def test_a_time_in_the_past_is_allowed_and_opens_nothing(self):
        past = datetime.now(timezone.utc) - timedelta(days=2)
        fresh, _ = self.users.reissue_token(self.user.id, expires_at=past)
        self.assertIsNone(self.users.authenticate(fresh))

    def test_the_count_matches_what_a_reissue_then_revokes(self):
        self.users.issue_invite_token(self.user.id)
        self.users.issue_invite_token(self.user.id)
        self.users.revoke_all_tokens(self.user.id)
        self.users.issue_invite_token(self.user.id)
        self.assertEqual(self.users.count_unrevoked_tokens(self.user.id), 1)
        _, revoked = self.users.reissue_token(
            self.user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        self.assertEqual(revoked, 1)

    def test_another_users_tokens_are_left_alone(self):
        other = self.users.create_user("other@example.test", status="active")
        theirs = self.users.issue_invite_token(other.id)
        self.users.reissue_token(self.user.id,
                                 expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        self.assertIsNotNone(self.users.authenticate(theirs))


class SupportPageTellsALockedOutBuyerWhatToSend(unittest.TestCase):
    def setUp(self):
        self.src = (JS / "support.js").read_text(encoding="utf-8")
        steps = self.src.split("export const LOCKED_OUT_STEPS = [", 1)[1].split("];", 1)[0]
        self.steps = " ".join(steps.split())

    def test_it_says_which_mailbox_what_subject_and_what_not_to_send(self):
        for fact in ("from the email address your account uses", "We answer only that address",
                     "\\\"Locked out\\\" in the subject", "bought a plan or were given early access",
                     "old one stops working", "Do not send a card number or an old token",
                     "is not enough"):
            self.assertIn(fact, self.steps)

    def test_it_says_to_expect_a_confirmation_email_and_to_reply_from_the_account_address(self):
        for fact in ("write to the address on the account first, to confirm the request",
                     "Reply to that email from the email address your account uses",
                     "Until your reply arrives nothing changes",
                     "your current token keeps working"):
            self.assertIn(fact, self.steps)

    def test_it_is_support_recovery_it_promises_no_button_and_no_turnaround(self):
        note = self.src.split("function lockedOutNote()", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("by hand", note)
        self.assertIn("not lost", note)
        for promise in ("instantly", "within", "minutes", "hours", "automatic", "reset your password"):
            self.assertNotIn(promise, (note + self.steps).lower())

    def test_the_note_is_on_the_page(self):
        body = self.src.split("export async function renderSupport(", 1)[1]
        self.assertIn("section.appendChild(lockedOutNote())", body)


class TheDocumentsSayWhatWasDecided(unittest.TestCase):
    def test_the_procedure_is_labelled_support_recovery_and_covers_the_six_cases(self):
        text = (ROOT / "docs" / "billing" / "RECOVERY_PROCEDURE.md").read_text(encoding="utf-8")
        self.assertIn("support recovery, not self-service", text.lower())
        for case in ("Same browser", "closed the tab", "10-minute re-read window", "Another device",
                     "Tester whose week ended", "Revoked or unknown token"):
            self.assertIn(case, text)
        for rule in ("mailbox", "reason", "audit", "stops working", "alone"):
            self.assertIn(rule, text.lower())

    def test_a_form_submission_is_not_proof_and_nothing_is_revoked_before_the_reply(self):
        # review 2026-10-05: the form's email field is typed, so the procedure may not
        # treat a submission as arriving "from the address"
        text = " ".join((ROOT / "docs" / "billing" / "RECOVERY_PROCEDURE.md").read_text(
            encoding="utf-8").split())
        self.assertNotIn("arrives from the address on the account (the Get help form", text)
        for fact in ("typed and unverified", "anyone can type a victim's address",
                     "first write to the address on the account",
                     "until a reply arrives from that mailbox",
                     "nothing is revoked or issued before that",
                     "keeps working", "lock a paying customer out"):
            self.assertIn(fact, text)

    def test_option_b_is_recorded_as_not_applied(self):
        text = (ROOT / "docs" / "decisions" / "closed-tab-token-recovery.md").read_text(encoding="utf-8")
        self.assertIn("Decision 2026-10-05: Option B not applied", text)
        self.assertNotIn("Status: PROPOSED", text)
