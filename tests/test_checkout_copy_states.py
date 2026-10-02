"""Every paying-related sentence the public pages show, in every billing state.

States: checkout "on" (with a trial of N days, N = 0 included), "off" (null
provider), "unavailable" (stripe selected but something required is missing),
and /meta unreachable. The rule (web/js/checkout.js): unless /meta says "on"
there is no trial promise and no "cancel anytime" anywhere; when it IS on, the
trial length and price shown come from /meta.billing, never static text.

No JS test runner exists in this repo, so the real modules are executed under
node against a small fake DOM (the pattern of PollingLoopRunsUnderNode in
tests/test_checkout_to_card_web.py): web/js is copied to a scratch directory
marked as ES modules and each scenario runs in its own process (meta.js caches
/meta once per page load, as it does in a browser).

The six places that must agree -- landing buttons + hero note, the sign-in
link, the record page call to action, the gate button, the signup form -- are
each driven here with the same /meta payloads.
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

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "js"

HARNESS = r"""
import fs from "node:fs";

class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.listeners = {}; this.isRoot = false;
    this.style = {};
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
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
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
const store = new Map();
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "" },
  history: { replaceState() {} },
  addEventListener() {}, dispatchEvent() { return true; },
  crypto: globalThis.crypto,
};

const scenario = JSON.parse(process.env.SCENARIO);

let clock = 0;
Date.now = () => (clock += 1000);
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (f, ms, ...rest) => (ms === 2000 ? (f(), 0) : realSetTimeout(f, ms, ...rest));

const calls = [];
let completeCalls = 0;
let onFirstComplete = () => {};
globalThis.fetch = async (url, init) => {
  url = String(url);
  calls.push(url);
  const json = (status, bodyObj) => ({ ok: status < 400, status, text: async () => JSON.stringify(bodyObj) });
  if (url.startsWith("/meta")) {
    if (scenario.meta === null) throw new Error("offline");
    return json(200, scenario.meta);
  }
  if (url.startsWith("/signup/complete")) {
    completeCalls += 1;
    if (completeCalls === 1) onFirstComplete();
    const plan = scenario.complete || [{ status: 404 }];
    const step = plan[Math.min(completeCalls - 1, plan.length - 1)];
    return json(step.status, step.body || {});
  }
  return json(200, {});
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const hooks = (n) => n._all([]).filter((x) => "data-hook" in x.attrs).map((x) => x.attrs["data-hook"]);
const main = document.createElement("main"); body.appendChild(main);

const out = { calls };
if (scenario.kind === "signup") {
  const { renderSignup } = await import("./signup.js");
  await renderSignup(main);
  out.text = text(main); out.hooks = hooks(main);
  const button = main.querySelector("[data-hook='signup-submit']");
  out.button = button && button.textContent;
  const title = main.querySelector("[data-hook='signup-title']");
  out.title = title && title.textContent;
} else if (scenario.kind === "complete") {
  const { renderSignupComplete } = await import("./signup.js");
  onFirstComplete = () => { out.waiting = text(main); };
  await renderSignupComplete(main, scenario.query);
  out.text = text(main); out.hooks = hooks(main);
} else if (scenario.kind === "signin") {
  const { renderSignin } = await import("./signin.js");
  await renderSignin(main, {});
  await new Promise((r) => realSetTimeout(r, 20));
  out.text = text(main);
  out.link = main.querySelector("[data-hook='signin-start-trial']").textContent;
  out.note = main.querySelector("[data-hook='signin-note']").textContent;
} else if (scenario.kind === "gate") {
  const { renderError } = await import("./dom.js");
  await renderError(main, { status: 401, detail: null });
  await new Promise((r) => realSetTimeout(r, 20));
  out.link = main.querySelector("[data-hook='signup-link']").textContent;
  out.initial = scenario.initial;
} else if (scenario.kind === "record") {
  const { signupCta } = await import("./cardrecord.js");
  const node = signupCta("top");
  main.appendChild(node);
  out.before = main.querySelector("[data-hook='record-start-trial']").textContent;
  await new Promise((r) => realSetTimeout(r, 20));
  out.link = main.querySelector("[data-hook='record-start-trial']").textContent;
} else if (scenario.kind === "landing") {
  for (const spec of scenario.nodes) {
    const node = document.createElement(spec.tag);
    for (const [k, v] of Object.entries(spec.attrs)) node.setAttribute(k, v);
    node.textContent = spec.text;
    body.appendChild(node);
  }
  const { applyCheckoutCopy } = await import("./landing.js");
  const { checkoutState } = await import("./checkout.js");
  applyCheckoutCopy(checkoutState(scenario.meta));
  out.nodes = body.children.filter((n) => "data-hook" in n.attrs).map((n) => ({
    hook: n.attrs["data-hook"], text: n.textContent, hidden: n.hidden,
  }));
} else if (scenario.kind === "helpers") {
  const c = await import("./checkout.js");
  const state = c.checkoutState(scenario.meta);
  out.state = state;
  out.cta = c.ctaLabel(state); out.gate = c.gateLabel(state); out.record = c.recordCtaLabel(state);
  out.hero = c.heroNote(state); out.pricing = c.pricingNote(state);
  out.card = c.cardRequiredNotice(state); out.started = c.trialStartedNote(state);
  out.notOn = { cta: c.ctaLabel(c.NOT_ON), hero: c.heroNote(c.NOT_ON) };
}
console.log("@@" + JSON.stringify(out));
"""


def _billing(checkout="on", trial_days=7, price_cents=1999):
    return {"billing": {"checkout": checkout, "trial_days": trial_days, "price_cents": price_cents}}


ON7 = _billing()
ON14 = _billing(trial_days=14)
ON0 = _billing(trial_days=0)
OFF = _billing("off", 7, 1999)
UNAVAILABLE = _billing("unavailable", 7, 1999)
UNREACHABLE = None

NOT_ON_CASES = (("off", OFF), ("unavailable", UNAVAILABLE), ("unreachable", UNREACHABLE),
                ("no billing key", {}), ("garbage", {"billing": {"checkout": "yes"}}))

TRIAL_RE = re.compile(r"trial|cancel anytime|cancel before|7-day|7 day", re.I)
# Owner decision 2026-10-02: the one sentence allowed to say "7 days" while
# checkout is off. Early access by invitation, not a trial anyone can start:
# see web/js/checkout.js, "THE ONE EXCEPTION WHILE CHECKOUT IS NOT ON".
EARLY_ACCESS_SENTENCE = "Early access: the first 20 testers get 7 days free, no card."


@unittest.skipUnless(shutil.which("node"), "node not installed")
class CheckoutCopyInEveryState(unittest.TestCase):
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
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- the shared decision -------------------------------------------------

    def test_not_on_states_say_the_cautious_thing_everywhere(self):
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                out = self.run_scenario(kind="helpers", meta=meta)
                self.assertFalse(out["state"]["on"])
                self.assertEqual(out["cta"], "Request early access")
                self.assertEqual(out["gate"], "Request early access")
                self.assertEqual(out["record"], "Request early access")
                self.assertEqual(out["hero"], "Early access: the first 20 testers get 7 days free, no card. Not on sale yet; planned price $19.99 a month. The record and the postseason odds are free now.")
                self.assertEqual(out["pricing"], "Planned price: $19.99/month")
                self.assertIsNone(out["card"])
                self.assertIsNone(out["started"])
                for key in ("hero", "pricing", "cta", "gate", "record"):
                    # The owner's early-access sentence says "7 days", which
                    # TRIAL_RE's "7 day" matches by spelling alone. It is the ONE
                    # sentence exempted, by exact text, and only from the hero
                    # note: any other trial or cancel wording in the hero, and
                    # any of it in the other four strings, still fails.
                    text = out[key].replace(EARLY_ACCESS_SENTENCE, "") if key == "hero" else out[key]
                    self.assertIsNone(TRIAL_RE.search(text), (key, out[key]))

    def test_on_takes_trial_length_and_price_from_meta(self):
        out = self.run_scenario(kind="helpers", meta=ON14)
        self.assertEqual(out["cta"], "Start your 14-day free trial")
        self.assertIn("14-day free trial, then $19.99/month.", out["hero"])
        out = self.run_scenario(kind="helpers", meta=_billing(trial_days=7, price_cents=2499))
        self.assertIn("7-day free trial, then $24.99/month.", out["hero"])
        self.assertNotIn("19.99", out["hero"])

    def test_on_with_zero_trial_days_has_no_trial_sentence_anywhere(self):
        out = self.run_scenario(kind="helpers", meta=ON0)
        self.assertTrue(out["state"]["on"])
        for key in ("cta", "gate", "record", "hero", "pricing", "card", "started"):
            self.assertIsNone(TRIAL_RE.search(out[key] or "") if key not in ("hero", "pricing")
                              else TRIAL_RE.search(re.sub(r"cancel anytime\.?", "", out[key], flags=re.I)),
                              (key, out[key]))
        self.assertIsNone(out["card"])
        self.assertIsNone(out["started"])
        self.assertEqual(out["cta"], "Start your subscription")

    def test_the_static_landing_defaults_equal_the_helpers_not_on_wording(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        out = self.run_scenario(kind="helpers", meta=OFF)
        for cta in re.findall(r"<a[^>]*data-checkout-cta[^>]*>(.*?)</a>", html, flags=re.S):
            self.assertEqual(cta.strip(), out["notOn"]["cta"])
        note = re.search(r'<p[^>]*data-hook="hero-cta-note"[^>]*>(.*?)</p>', html, flags=re.S)
        self.assertEqual(note.group(1).strip(), out["notOn"]["hero"])

    # ---- the signup form (A2, A3) -------------------------------------------

    def test_signup_form_when_not_on_promises_nothing(self):
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                out = self.run_scenario(kind="signup", meta=meta)
                self.assertEqual(out["title"], "Request early access")
                self.assertEqual(out["button"], "Request early access")
                self.assertIn("Planned price: $19.99/month", out["text"])
                self.assertIsNone(TRIAL_RE.search(out["text"]), out["text"])
                self.assertNotIn("signup-card-required", out["hooks"])
                self.assertNotIn("founding price", out["text"].lower())
                self.assertNotIn("founding members", out["text"].lower())

    def test_signup_form_when_on_states_the_trial_from_meta(self):
        for meta, days in ((ON7, 7), (ON14, 14)):
            with self.subTest(days=days):
                out = self.run_scenario(kind="signup", meta=meta)
                self.assertEqual(out["title"], f"Start your {days}-day free trial")
                self.assertEqual(out["button"], f"Start your {days}-day free trial")
                self.assertIn(f"{days}-day free trial, then $19.99/month.", out["text"])
                other = 14 if days == 7 else 7
                self.assertNotIn(f"{other}-day", out["text"])
                self.assertIn(
                    "A card is required to start the trial. "
                    f"Nothing is charged for {days} days, and you can cancel before then.",
                    out["text"])
                self.assertIn("signup-card-required", out["hooks"])

    def test_the_card_notice_sits_before_the_button(self):
        out = self.run_scenario(kind="signup", meta=ON7)
        self.assertLess(out["hooks"].index("signup-card-required"), out["hooks"].index("signup-submit"))

    def test_signup_form_with_zero_trial_days_has_no_trial_or_card_sentence(self):
        out = self.run_scenario(kind="signup", meta=ON0)
        self.assertEqual(out["title"], "Start your subscription")
        self.assertIsNone(re.search(r"trial|nothing is charged|7-day", out["text"], re.I), out["text"])
        self.assertNotIn("signup-card-required", out["hooks"])
        self.assertIn("$19.99/month", out["text"])

    def test_the_price_shown_follows_meta(self):
        out = self.run_scenario(kind="signup", meta=_billing(price_cents=2999))
        self.assertIn("$29.99/month", out["text"])
        self.assertNotIn("19.99", out["text"])

    # ---- the completion page (A4) -------------------------------------------

    def test_waiting_screen_never_says_payment_received(self):
        for meta in (ON7, ON0, OFF, UNREACHABLE):
            with self.subTest(meta=meta):
                out = self.run_scenario(kind="complete", meta=meta,
                                        query={"session_id": "cs_typed_by_hand"},
                                        complete=[{"status": 404}])
                self.assertIn("Finishing your signup...", out["waiting"])
                self.assertNotIn("payment received", (out["waiting"] + out["text"]).lower())
                self.assertIsNone(re.search(r"your payment|payment (has|was)", out["text"], re.I),
                                  out["text"])
                self.assertIn("signup-timed-out", out["hooks"])
                self.assertNotIn("signup-token", out["hooks"])

    def test_after_the_token_arrives_it_says_youre_in_and_the_trial_started(self):
        out = self.run_scenario(kind="complete", meta=ON7, query={"session_id": "cs_real"},
                                complete=[{"status": 404}, {"status": 404},
                                          {"status": 200, "body": {"user_id": 1, "token": "tok_abc"}}])
        self.assertIn("Finishing your signup...", out["waiting"])
        self.assertNotIn("You're in.", out["waiting"])
        self.assertIn("You're in.", out["text"])
        self.assertIn("Your free trial has started; nothing has been charged yet.", out["text"])
        self.assertIn("signup-token", out["hooks"])
        self.assertNotIn("payment received", out["text"].lower())

    def test_no_trial_sentence_after_the_token_when_there_is_no_trial(self):
        for meta in (ON0, OFF, UNREACHABLE):
            with self.subTest(meta=meta):
                out = self.run_scenario(kind="complete", meta=meta, query={"session_id": "cs_real"},
                                        complete=[{"status": 200, "body": {"user_id": 1, "token": "tok_abc"}}])
                self.assertIn("You're in.", out["text"])
                self.assertNotIn("free trial", out["text"].lower())
                self.assertNotIn("charged", out["text"].lower())

    # ---- sign-in, gate, record page (A5) -------------------------------------

    def test_signin_view(self):
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                out = self.run_scenario(kind="signin", meta=meta)
                self.assertEqual(out["link"], "REQUEST EARLY ACCESS")
                self.assertIsNone(TRIAL_RE.search(out["note"]), out["note"])
        out = self.run_scenario(kind="signin", meta=ON14)
        self.assertEqual(out["link"], "START YOUR 14-DAY FREE TRIAL")
        out = self.run_scenario(kind="signin", meta=ON0)
        self.assertEqual(out["link"], "START YOUR SUBSCRIPTION")
        self.assertIsNone(re.search(r"trial", out["note"], re.I))

    def test_sign_in_gate_button(self):
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                self.assertEqual(self.run_scenario(kind="gate", meta=meta)["link"],
                                 "Request early access")
        self.assertEqual(self.run_scenario(kind="gate", meta=ON7)["link"], "Start free trial")
        self.assertEqual(self.run_scenario(kind="gate", meta=ON0)["link"], "Subscribe")

    def test_record_page_call_to_action(self):
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                out = self.run_scenario(kind="record", meta=meta)
                self.assertEqual(out["before"], "Request early access")
                self.assertEqual(out["link"], "Request early access")
        out = self.run_scenario(kind="record", meta=ON14)
        self.assertEqual(out["before"], "Request early access",
                         "the first paint must be the cautious wording")
        self.assertEqual(out["link"], "Start your 14-day free trial to see tonight's card")
        out = self.run_scenario(kind="record", meta=ON0)
        self.assertEqual(out["link"], "Subscribe to see tonight's card")

    # ---- the landing page (A5), driven against the REAL html ------------------

    def _landing_nodes(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        nodes = []

        def attrs_of(raw):
            return {k: v for k, v in re.findall(r'([\w-]+)="([^"]*)"', raw)} | {
                k: "" for k in re.findall(r"\s(hidden|data-checkout-cta)(?=[\s>]|$)", raw)}

        pattern = re.compile(r"<(a|p|span|li)\b([^>]*)>(.*?)</\1>", re.S)
        for tag, raw, inner in pattern.findall(html):
            if any(key in raw for key in ("data-checkout-cta", 'data-hook="hero-cta-note"',
                                          'data-hook="pricing-trial-badge"',
                                          'data-hook="pricing-cancel-line"')):
                attrs = attrs_of(raw)
                if "data-checkout-cta" in raw and "data-hook" not in attrs:
                    attrs["data-hook"] = "cta"
                nodes.append({"tag": tag, "attrs": attrs, "text": inner.strip()})
        nodes.append({"tag": "div", "attrs": {"data-hook": "pricing-host"}, "text": ""})
        return nodes

    def test_landing_html_upgrades_only_when_meta_says_on(self):
        nodes = self._landing_nodes()
        ctas = [n for n in nodes if "data-checkout-cta" in n["attrs"]]
        self.assertEqual(len(ctas), 4, "primary, hero, pricing card, closing band")
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                out = self.run_scenario(kind="landing", meta=meta, nodes=nodes)
                by = {n["hook"]: n for n in out["nodes"]}
                for hook in ("cta-primary", "cta-signup-hero", "cta-signup", "cta-signup-bottom"):
                    self.assertEqual(by[hook]["text"], "Request early access", hook)
                self.assertEqual(by["hero-cta-note"]["text"],
                                 "Early access: the first 20 testers get 7 days free, no card. Not on sale yet; planned price $19.99 a month. The record and the postseason odds are free now.")
                self.assertTrue(by["pricing-trial-badge"]["hidden"])
                self.assertTrue(by["pricing-cancel-line"]["hidden"])
                self.assertEqual(by["pricing-host"]["text"].strip(), "Planned price: $19.99/month")
        out = self.run_scenario(kind="landing", meta=ON14, nodes=nodes)
        by = {n["hook"]: n for n in out["nodes"]}
        for hook in ("cta-primary", "cta-signup-hero", "cta-signup", "cta-signup-bottom"):
            self.assertEqual(by[hook]["text"], "Start your 14-day free trial", hook)
        self.assertEqual(by["hero-cta-note"]["text"], "14-day free trial, then $19.99/month. Cancel anytime.")
        self.assertFalse(by["pricing-trial-badge"]["hidden"])
        self.assertEqual(by["pricing-trial-badge"]["text"], "14-day free trial")
        self.assertFalse(by["pricing-cancel-line"]["hidden"])
        out = self.run_scenario(kind="landing", meta=ON0, nodes=nodes)
        by = {n["hook"]: n for n in out["nodes"]}
        self.assertEqual(by["hero-cta-note"]["text"], "$19.99/month. Cancel anytime.")
        self.assertTrue(by["pricing-trial-badge"]["hidden"])
        self.assertNotIn("trial", by["pricing-host"]["text"].lower())

    def test_the_landing_html_itself_carries_no_trial_promise_before_js_runs(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        visible = re.sub(r"<(script|style)[\s\S]*?</\1>", "", html)
        # The only trial wording allowed in the static page is inside elements the
        # script reveals and that start hidden.
        for match in re.finditer(r"[^<>]*(?:free trial|7-day|Cancel anytime)[^<>]*", visible, re.I):
            start = visible.rfind("<", 0, match.start())
            tag = visible[start:visible.find(">", start) + 1]
            if tag.startswith("<summary"):
                # The FAQ question "Can I cancel anytime?" states the policy for the plan;
                # it promises no trial and no checkout. Its answer is not a trial claim.
                continue
            self.assertIn("hidden", tag, f"static trial wording outside a hidden element: {match.group(0)!r}")

    def test_the_meta_description_makes_no_trial_promise(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
        self.assertIsNone(re.search(r"trial", desc, re.I))
        self.assertIn("Planned price: $19.99/month", desc)


class NoPageHardCodesTheTrialAnyMore(unittest.TestCase):
    """The six places and the success page must not carry the static words."""

    def test_no_public_view_file_has_a_static_trial_or_payment_received_string(self):
        for name in ("signup.js", "landing.js", "signin.js", "cardrecord.js", "dom.js"):
            source = (JS / name).read_text(encoding="utf-8")
            for forbidden in ("7-day free trial", "START YOUR 7-DAY", "Start your 7-day",
                              "Payment received", "Cancel anytime"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden!r}")

    def test_every_decision_goes_through_checkout_js(self):
        for name in ("signup.js", "landing.js", "signin.js", "cardrecord.js", "dom.js"):
            source = (JS / name).read_text(encoding="utf-8")
            self.assertIn('from "./checkout.js"', source, name)
            self.assertNotIn('billing.checkout === "on"', source, name)
        self.assertIn('billing.checkout === "on"', (JS / "checkout.js").read_text(encoding="utf-8"))

    def test_checkout_js_imports_meta_lazily_so_dom_js_has_no_import_cycle(self):
        source = (JS / "checkout.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'^import .*"\./meta\.js"', source, re.M))
        self.assertIn('import("./meta.js")', source)


if __name__ == "__main__":
    unittest.main()
