"""A visitor from an outreach link is visible in the admin funnel under that
link's source, whichever public page the link points at.

THE BUG (2026-10-01). Outreach links do not point at landing.html; they point
at the record page (index.html?utm_source=<lead>&utm_medium=<channel>&
utm_campaign=<batch>#/record-card) and at postseason.html. Only landing.js
stored the first touch and only landing.js sent a funnel event, so a lead who
read the record page was invisible, and if they signed up later the account
read "(direct)". These tests pin the whole chain:

  * the REAL web/js modules (main.js's boot, postseason-page.js, pageview.js,
    attribution.js, api.js) are executed under node against a small fake DOM
    (the pattern of tests/test_checkout_copy_states.py): the first touch is
    stored from the query string (which sits BEFORE the hash), ONE
    public_page_view beacon goes out per page load, first touch wins, and a
    blocked localStorage never breaks the page;
  * the beacon that node produced and the signup payload it produced are then
    fed to the REAL api/ route functions, and GET /admin/funnel's `by_source`
    must show the lead under its source -- the arrival column AND, after the
    signup, account_created -- while the landing_view number is untouched;
  * the public endpoint stays narrow: the new kind's `page` label is checked.

Python route tests are skipped when FastAPI is not installed (the Linux CI job
has none); the node tests are skipped when node is missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from tests.test_attribution_flow import _DbCase
from tests.test_appstate_billing import _FakeTransport

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"

OUTREACH_QUERY = "?utm_source=lead-017&utm_medium=discord_dm&utm_campaign=batch-01"

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {}; this.dataset = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set innerHTML(v) { this.childNodes = []; }
  addEventListener() {}
  removeEventListener() {}
  focus() {}
  closest() { return null; }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:(\^?=)'([^']*)')?\]$/);
    if (!m) return [];
    const [, name, op, val] = m;
    return this._all([]).filter((n) => {
      if (!(name in n.attrs)) return false;
      if (!op) return true;
      return op === "=" ? n.attrs[name] === val : n.attrs[name].startsWith(val);
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const scenario = JSON.parse(process.env.SCENARIO);
process.on("unhandledRejection", () => {});   // views render against empty fakes

const body = new Elem("body");
for (const hook of ["app-outlet", "disclaimer-host", "primary-nav", "primary-nav-mobile",
                    "news-host", "shell-clock", "skip-link"]) {
  const node = new Elem("div"); node.setAttribute("data-hook", hook); body.appendChild(node);
}
const listeners = {};
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  body, referrer: "",
  addEventListener: (t, f) => { (listeners[t] ||= []).push(f); },
  querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s),
};
const store = new Map(Object.entries(scenario.stored || {}));
const storage = {
  getItem: (k) => { if (scenario.brokenStorage) throw new Error("denied"); return store.has(k) ? store.get(k) : null; },
  setItem: (k, v) => { if (scenario.brokenStorage) throw new Error("denied"); store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
};
const winListeners = {};
globalThis.window = {
  localStorage: storage,
  sessionStorage: storage,
  location: { search: scenario.search || "", host: "linehound.test", pathname: "/web/index.html", hash: scenario.hash || "" },
  history: { replaceState() {} },
  addEventListener: (t, f) => { (winListeners[t] ||= []).push(f); },
  removeEventListener() {},
  dispatchEvent() { return true; },
  scrollTo() {},
  crypto: globalThis.crypto,
};
globalThis.location = window.location;
globalThis.localStorage = storage;
globalThis.sessionStorage = storage;

const posts = [];
const gets = [];
globalThis.fetch = async (url, init) => {
  url = String(url);
  if (init && init.method === "POST" && url.startsWith("/funnel/event")) {
    posts.push(JSON.parse(init.body));
  } else {
    gets.push(url);
  }
  return { ok: true, status: 200, text: async () => "{}", json: async () => ({}) };
};

const settle = () => new Promise((r) => setTimeout(r, 60));
const out = {};
try {
  if (scenario.kind === "shell") {
    await import("./main.js");
    for (const fn of listeners.DOMContentLoaded || []) fn();
    await settle();
    for (const nextHash of scenario.then || []) {   // in-app navigation after arrival
      window.location.hash = nextHash;
      for (const fn of winListeners.hashchange || []) fn();
      await settle();
    }
  } else if (scenario.kind === "postseason") {
    await import("./postseason-page.js");
    for (const fn of listeners.DOMContentLoaded || []) fn();
    await settle();
  }
  out.crashed = false;
} catch (err) {
  out.crashed = String(err && err.stack || err);
}
out.posts = posts;
out.gets = gets;
out.stored = Object.fromEntries(store);
console.log("@@" + JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PublicPagesCaptureAndCount(unittest.TestCase):
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
        env = dict(os.environ, SCENARIO=json.dumps(scenario))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        out = json.loads(line[2:])
        self.assertFalse(out["crashed"], out["crashed"])
        return out

    def arrive(self, hash_, search=OUTREACH_QUERY, **extra):
        return self.run_scenario(kind="shell", hash=hash_, search=search, **extra)

    # ---- the app shell: query BEFORE the hash ---------------------------------

    def test_record_page_stores_the_first_touch_from_the_query_string(self):
        out = self.arrive("#/record-card")
        touch = json.loads(out["stored"]["linehound.first_touch"])
        self.assertEqual(touch["utm_source"], "lead-017")
        self.assertEqual(touch["utm_medium"], "discord_dm")
        self.assertEqual(touch["utm_campaign"], "batch-01")

    def test_record_page_sends_exactly_one_public_page_view_with_the_touch_and_anon_id(self):
        out = self.arrive("#/record-card")
        self.assertEqual(len(out["posts"]), 1, out["posts"])
        beacon = out["posts"][0]
        self.assertEqual(beacon["kind"], "public_page_view")
        self.assertEqual(beacon["properties"]["page"], "record-card")
        self.assertEqual(beacon["properties"]["utm_source"], "lead-017")
        self.assertEqual(beacon["properties"]["utm_campaign"], "batch-01")
        self.assertRegex(beacon["anon_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(out["stored"]["linehound.anon_id"], beacon["anon_id"])

    def test_the_router_still_mounts_the_record_view_with_a_query_string_present(self):
        out = self.arrive("#/record-card")
        self.assertTrue(any(url.startswith("/card/record") for url in out["gets"]),
                        f"record view never fetched its data: {out['gets']}")
        out = self.arrive("#/record-card", search="")
        self.assertTrue(any(url.startswith("/card/record") for url in out["gets"]))

    def test_every_public_record_route_and_the_results_alias_is_counted(self):
        cases = {"#/record-card": "record-card", "#/results": "record-card",
                 "#/nfl/record": "nfl-record", "#/ufc/record": "ufc-record",
                 "#/postseason": "postseason", "#/record-card?rule=v1": "record-card"}
        for hash_, page in cases.items():
            with self.subTest(hash=hash_):
                out = self.arrive(hash_)
                self.assertEqual([p["properties"]["page"] for p in out["posts"]], [page])
                self.assertEqual(out["posts"][0]["properties"]["utm_source"], "lead-017")

    def test_non_public_routes_send_no_page_view_but_still_remember_the_source(self):
        for hash_ in ("#/signin", "#/signup", "#/billing", "#/mybets", "#/today"):
            with self.subTest(hash=hash_):
                out = self.arrive(hash_)
                # (the signup form sends its own signup_started, which is fine)
                self.assertNotIn("public_page_view", [p["kind"] for p in out["posts"]], hash_)
                touch = json.loads(out["stored"]["linehound.first_touch"])
                self.assertEqual(touch["utm_source"], "lead-017")

    def test_navigating_inside_the_app_is_not_a_second_arrival(self):
        out = self.arrive("#/record-card", then=["#/nfl/record", "#/postseason", "#/record-card"])
        self.assertEqual(len(out["posts"]), 1, out["posts"])

    def test_first_touch_wins_and_the_event_carries_the_stored_one(self):
        earlier = {"utm_source": "lead-001", "utm_medium": "email"}
        out = self.arrive("#/record-card", stored={"linehound.first_touch": json.dumps(earlier)})
        self.assertEqual(json.loads(out["stored"]["linehound.first_touch"]), earlier)
        self.assertEqual(out["posts"][0]["properties"]["utm_source"], "lead-001")

    def test_a_direct_visit_is_counted_without_inventing_a_source(self):
        out = self.arrive("#/record-card", search="")
        self.assertNotIn("linehound.first_touch", out["stored"])
        self.assertEqual(out["posts"][0]["properties"], {"page": "record-card"})

    def test_blocked_storage_never_breaks_the_page_and_the_visit_is_still_attributed(self):
        out = self.arrive("#/record-card", brokenStorage=True)
        self.assertEqual(len(out["posts"]), 1)
        self.assertEqual(out["posts"][0]["properties"]["utm_source"], "lead-017")
        self.assertTrue(any(url.startswith("/card/record") for url in out["gets"]))

    # ---- postseason.html ------------------------------------------------------

    def test_postseason_page_stores_the_touch_and_sends_one_event(self):
        out = self.run_scenario(kind="postseason", search=OUTREACH_QUERY, hash="")
        touch = json.loads(out["stored"]["linehound.first_touch"])
        self.assertEqual(touch["utm_source"], "lead-017")
        self.assertEqual(len(out["posts"]), 1, out["posts"])
        self.assertEqual(out["posts"][0]["kind"], "public_page_view")
        self.assertEqual(out["posts"][0]["properties"]["page"], "postseason")
        self.assertEqual(out["posts"][0]["properties"]["utm_source"], "lead-017")

    def test_postseason_page_survives_blocked_storage(self):
        out = self.run_scenario(kind="postseason", search=OUTREACH_QUERY, hash="",
                                brokenStorage=True)
        self.assertEqual(len(out["posts"]), 1)


# ---------------------------------------------------------------------------
# The server half, fed with what node actually produced.
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class PublicPageViewInTheAdminFunnel(_DbCase):
    def _post(self, kind, props=None, anon=None):
        from api.funnel import FunnelEventRequest, post_funnel_event
        return post_funnel_event(FunnelEventRequest(kind=kind, properties=props, anon_id=anon))

    def _funnel(self):
        from api.funnel import get_admin_funnel
        return get_admin_funnel(_admin=None)

    def test_a_record_page_visit_appears_under_its_source(self):
        self._post("public_page_view", {"utm_source": "lead-017", "page": "record-card"},
                   anon="a" * 32)
        by_source = self._funnel()["by_source"]
        self.assertEqual(by_source["lead-017"]["public_page_view"], 1)

    def test_it_does_not_inflate_or_redefine_landing_view(self):
        self._post("landing_view", {"utm_source": "reddit"}, anon="b" * 32)
        for n in range(5):
            self._post("public_page_view", {"utm_source": "lead-017", "page": "record-card"},
                       anon="a" * 32)
        funnel = self._funnel()
        steps = {s["kind"]: s for s in funnel["steps"]}
        self.assertEqual(steps["landing_view"]["count"], 1)
        self.assertEqual(steps["landing_view"]["unique_visitors"], 1)
        self.assertNotIn("public_page_view", steps)
        self.assertEqual(funnel["by_source"]["lead-017"]["landing_view"], 0)
        self.assertEqual(funnel["by_source"]["reddit"]["landing_view"], 1)
        self.assertEqual(funnel["by_source"]["reddit"]["public_page_view"], 0)

    def test_the_main_funnel_steps_are_unchanged(self):
        from api.funnel import FUNNEL_STEPS
        self.assertNotIn(events.PUBLIC_PAGE_VIEW, FUNNEL_STEPS)

    def test_a_source_with_only_page_views_is_listed_and_sorted_after_landing_sources(self):
        self._post("landing_view", {"utm_source": "reddit"}, anon="b" * 32)
        self._post("public_page_view", {"utm_source": "lead-017", "page": "postseason"},
                   anon="a" * 32)
        self.assertEqual(list(self._funnel()["by_source"]), ["reddit", "lead-017"])

    def test_the_page_label_is_checked_so_the_public_endpoint_stays_narrow(self):
        bad = [None, {}, {"page": ""}, {"page": 7}, {"page": ["x"]}, {"page": "Record Card"},
               {"page": "../../etc/passwd"}, {"page": "x" * 33}, {"page": "a" * 500},
               {"utm_source": "lead-017"}]
        for props in bad:
            with self.subTest(props=props):
                with self.assertRaises(HTTPException) as ctx:
                    self._post("public_page_view", props, anon="a" * 32)
                self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(events.list_events(db=self.db), [])

    def test_oversized_properties_and_authed_kinds_are_still_refused(self):
        with self.assertRaises(HTTPException) as ctx:
            self._post("public_page_view", {"page": "record-card", "pad": "x" * 3000})
        self.assertEqual(ctx.exception.status_code, 400)
        for kind in ("account_created", "checkout_completed", "bet_saved"):
            with self.assertRaises(HTTPException):
                self._post(kind, {"page": "record-card"})

    def test_the_route_is_still_rate_limited(self):
        from api import funnel
        route = [r for r in funnel.router.routes if r.path == "/funnel/event"][0]
        self.assertTrue(route.dependencies, "the public beacon lost its rate limit")


@unittest.skipUnless(shutil.which("node") and HAS_FASTAPI, "node or fastapi not installed")
class OutreachVisitorToAccountCreated(_DbCase):
    """Record page with ?utm_source=lead-017 first, signup later: the account
    is attributed to lead-017 in /admin/funnel by_source."""

    def _provider(self, transport):
        return billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=transport,
            customer_ref_lookup=lambda uid: customers.get_customer_ref(uid, db=self.db),
            on_customer_created=lambda uid, cid: customers.upsert_customer(uid, cid, db=self.db))

    def test_first_page_was_the_record_page_and_the_account_lands_under_the_lead(self):
        from api.funnel import FunnelEventRequest, get_admin_funnel, post_funnel_event
        from api.signup import SignupRequest, signup
        with tempfile.TemporaryDirectory() as tmp:
            for path in JS.glob("*.js"):
                shutil.copy(path, tmp)
            Path(tmp, "package.json").write_text('{"type": "module"}', encoding="utf-8")
            Path(tmp, "harness.mjs").write_text(
                HARNESS.replace('out.crashed = false;', """
    if (scenario.kind === "shell") {
      // The visitor now opens the signup form IN THE SAME BROWSER (the
      // landing query string is gone: first touch must come from storage).
      window.location.search = ""; window.location.hash = "#/signup";
      const { attributionPayload } = await import("./attribution.js");
      out.signupAttribution = attributionPayload();
    }
    out.crashed = false;"""), encoding="utf-8")
            env = dict(os.environ, SCENARIO=json.dumps(
                {"kind": "shell", "hash": "#/record-card", "search": OUTREACH_QUERY}))
            proc = subprocess.run(["node", "harness.mjs"], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        out = json.loads(line[2:])
        self.assertFalse(out["crashed"], out["crashed"])
        self.assertEqual(len(out["posts"]), 1)

        # Replay exactly what the browser sent.
        post_funnel_event(FunnelEventRequest(**out["posts"][0]))
        transport = _FakeTransport()
        transport.queue(200, {"id": "cus_lead_017"})
        transport.queue(200, {"id": "cs_lead_017", "url": "https://checkout.stripe.com/lead017"})
        with mock.patch.object(billing, "get_billing_provider",
                               return_value=self._provider(transport)):
            signup(SignupRequest(email="lead017@example.com",
                                 attribution=out["signupAttribution"]), _rate_limit=None)

        by_source = get_admin_funnel(_admin=None)["by_source"]
        self.assertEqual(by_source["lead-017"]["public_page_view"], 1)
        self.assertEqual(by_source["lead-017"]["account_created"], 1)
        self.assertNotIn("(direct)", by_source)


if __name__ == "__main__":
    unittest.main()
