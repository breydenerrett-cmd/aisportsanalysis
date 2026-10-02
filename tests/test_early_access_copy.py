"""What the public pages say about early access, and what they must not say.

Owner decision (2026-10-02): the first 20 qualified testers get 7 days of
early access, no card, extended only when useful feedback justifies it. Billing
is off in production. Wherever the offer is described it must say, in plain
words, five facts -- it is early access; performance is not proven; the
analysis is informational, not advice; public results are preserved (losses
stay on the record); tester access is temporary -- and it must never promise
profit, an edge or winning picks, and never advertise Bet Check.

web/js/checkout.js is the one place billing-off copy is decided; web/landing.html
mirrors it as static text and must be correct with JavaScript off. The server
enforces the numbers (src/appstate/testers.py), so a test here pins that the
words and the enforcement agree -- the pages cannot import Python.

The behavioural half runs the real web/js modules under node against a small
fake DOM (the pattern of tests/test_checkout_copy_states.py); skipped when node
is not installed.
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

from src.appstate import testers

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "js"
HTML = (WEB / "landing.html").read_text(encoding="utf-8")

# Said by the owner, verbatim (2026-10-02). Any change here is a change to what
# the public is told and belongs to him.
HERO_NOTE = ("Early access: the first 20 testers get 7 days free, no card. "
             "Not on sale yet; planned price $19.99 a month. "
             "The record and the postseason odds are free now.")
CONFIRMATION = ("You're on the list. The first 20 testers get 7 days of early access, no card needed. "
                "If you're picked, your access link comes by email from Brey, usually within a day. "
                "What you should know: this is early access; performance is not proven; "
                "the analysis is informational, not advice; every result stays on the public record, "
                "losses included; tester access is temporary.")

# What the owner will never let a page say about this offer.
FORBIDDEN = (
    (r"\bprofit", "profit"), (r"\bedge\b", "edge"), (r"\bwinning\b", "winning"),
    (r"\bguarantee", "guarantee"), (r"\bsharp\b", "sharp"), (r"\bbeat the book", "beat the book"),
    (r"bet[\s-]*check", "Bet Check"), (r"\btrial\b", "trial"), (r"cancel anytime", "cancel anytime"),
    (r"!", "exclamation mark"),
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _faq_entry() -> str:
    match = re.search(r'<details\b[^>]*data-hook="faq-early-access"[^>]*>.*?</details>', HTML, re.S)
    assert match, "no early-access entry in the landing FAQ"
    return match.group(0)


class TheFiveFacts(unittest.TestCase):
    """The same five facts in every place the offer is described."""

    FACTS = (
        ("early access", r"early access"),
        ("performance is not proven", r"performance is not proven"),
        ("informational, not advice", r"informational, not advice"),
        ("public results preserved, losses included", r"public record, losses included"),
        ("tester access is temporary", r"tester access is temporary"),
    )

    def _check(self, text, where, facts=FACTS):
        lowered = text.lower()
        for label, pattern in facts:
            self.assertRegex(lowered, pattern, f"{where} does not say: {label}")
        for pattern, label in FORBIDDEN:
            self.assertIsNone(re.search(pattern, lowered), f"{where} says {label!r}: {text!r}")

    def test_the_confirmation_says_all_five(self):
        self._check(CONFIRMATION, "the waitlist confirmation")

    def test_the_faq_entry_says_all_five_in_the_static_page(self):
        entry = _faq_entry()
        self.assertEqual(re.search(r"<summary>(.*?)</summary>", entry, re.S).group(1).strip(),
                         "What is early access?")
        body = _flat(re.search(r'<p class="faq-item__body">(.*?)</p>', entry, re.S).group(1))
        facts = list(self.FACTS)
        facts[3] = ("public results preserved, losses included",
                    r"public record, losses included")
        self._check(body, "the FAQ entry", facts)
        self.assertNotIn("hidden", entry.split(">")[0], "the entry must not start hidden")

    def test_the_hero_note_names_the_offer_without_overclaiming(self):
        lowered = HERO_NOTE.lower()
        self.assertIn("early access", lowered)
        self.assertIn("not on sale yet", lowered)
        for pattern, label in FORBIDDEN:
            self.assertIsNone(re.search(pattern, lowered), label)

    def test_the_confirmation_promises_nothing_the_owner_does_not_do_by_hand(self):
        # There is still no email sender: the only email promised is Brey's own,
        # to someone he picked.
        self.assertIn("If you're picked", CONFIRMATION)
        self.assertIn("from Brey", CONFIRMATION)
        self.assertNotIn("we'll email", CONFIRMATION.lower())
        self.assertNotIn("on the waitlist", CONFIRMATION.lower())


class TheWordsAgreeWithWhatIsEnforced(unittest.TestCase):
    def test_every_place_says_the_enforced_cap_and_window(self):
        entry = _flat(_faq_entry())
        for where, text in (("hero note", HERO_NOTE), ("confirmation", CONFIRMATION),
                            ("FAQ", entry)):
            with self.subTest(where=where):
                m = re.search(r"first (\d+) testers get (\d+) days", text)
                self.assertIsNotNone(m, f"{where} does not state the offer")
                self.assertEqual(int(m.group(1)), testers.TESTER_LIMIT)
                self.assertEqual(int(m.group(2)), testers.TESTER_ACCESS_TTL.days)
        self.assertIn(f"lasts {testers.TESTER_ACCESS_TTL.days} days", entry)

    def test_the_static_hero_note_and_buttons_are_the_ones_checkout_js_decides(self):
        source = (JS / "checkout.js").read_text(encoding="utf-8")
        self.assertIn('export const CAUTIOUS_CTA = "Request early access";', source)
        self.assertIn('"Early access: the first 20 testers get 7 days free, no card."', source)
        note = re.search(r'<p class="hero__cta-note" data-hook="hero-cta-note">(.*?)</p>', HTML, re.S)
        self.assertEqual(note.group(1).strip(), HERO_NOTE)
        labels = [m.strip() for m in re.findall(r"<a[^>]*data-checkout-cta[^>]*>(.*?)</a>", HTML, re.S)]
        self.assertEqual(labels, ["Request early access"] * 4)


class TheLandingPageStaysHonestWithJavaScriptOff(unittest.TestCase):
    def test_no_trial_or_cancel_wording_appears_in_the_new_static_copy(self):
        for where, text in (("hero note", HERO_NOTE), ("FAQ", _flat(_faq_entry()))):
            self.assertIsNone(re.search(r"\btrial\b|cancel anytime|7-day", text, re.I), where)

    def test_the_old_waitlist_label_is_gone_from_the_page(self):
        self.assertNotIn("Join the waitlist", HTML)

    def test_the_faq_entry_names_no_bet_check(self):
        self.assertIsNone(re.search(r"bet[\s-]*check", _faq_entry(), re.I))


# ---------------------------------------------------------------------------
# Behavioural half
# ---------------------------------------------------------------------------

HARNESS = r"""
import fs from "node:fs";

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
const calls = [];
globalThis.fetch = async (url, init) => {
  url = String(url);
  calls.push({ url, method: (init && init.method) || "GET" });
  const json = (status, bodyObj) => ({ ok: status < 400, status, text: async () => JSON.stringify(bodyObj) });
  if (url.startsWith("/meta")) {
    if (scenario.meta === null) throw new Error("offline");
    return json(200, scenario.meta);
  }
  if (url === "/signup") return json(200, scenario.signup);
  return json(200, {});
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const main = document.createElement("main"); body.appendChild(main);

const out = { calls };
const { renderSignup } = await import("./signup.js");
await renderSignup(main);
const input = main.querySelector("[data-hook='signup-email-input']");
input.value = "someone@example.com";
const form = main.querySelector("[data-hook='signup-form']");
await form.listeners.submit[0]({ preventDefault() {} });
const hooks = main._all([]).filter((x) => "data-hook" in x.attrs).map((x) => x.attrs["data-hook"]);
const note = main.querySelector("[data-hook='signup-waitlisted']");
out.waitlisted = note ? note.textContent : null;
out.hooks = hooks;
out.page = text(main);
console.log("@@" + JSON.stringify(out));
"""

DUMP = r"""
import * as c from "./checkout.js";
const metas = JSON.parse(process.env.METAS);
const out = {};
for (const [name, meta] of Object.entries(metas)) {
  const s = c.checkoutState(meta);
  out[name] = {
    cta: c.ctaLabel(s), gate: c.gateLabel(s), record: c.recordCtaLabel(s),
    hero: c.heroNote(s), pricing: c.pricingNote(s), card: c.cardRequiredNotice(s),
    started: c.trialStartedNote(s), signinNote: c.signinNote(s), signinLink: c.signinLinkLabel(s),
    trialPhrase: c.trialPhrase(s), plannedPrice: c.plannedPrice(s),
  };
}
out.noPriceHero = c.heroNote({ on: false, trialDays: 0, priceCents: null });
out.constants = { cta: c.CAUTIOUS_CTA, note: c.EARLY_ACCESS_NOTE, confirmation: c.WAITLIST_CONFIRMATION };
console.log("@@" + JSON.stringify(out));
"""

FOUNDING = ("This is the founding price: it rises as the public record grows, and it can fall "
            "if the record does. Founding members keep $19.99 for as long as their subscription "
            "stays active.")
# Captured by running the PRE-CHANGE web/js/checkout.js (git HEAD fe9ddaf5) under
# node on these same inputs; the owner's rule is that when checkout IS on, every
# string stays byte-identical.
ON_STATE_BEFORE = {
    "ON7": {
        "cta": "Start your 7-day free trial", "gate": "Start free trial",
        "record": "Start your 7-day free trial to see tonight's card",
        "hero": "7-day free trial, then $19.99/month. Cancel anytime.",
        "pricing": "7-day free trial, then $19.99/month. Cancel anytime. " + FOUNDING,
        "card": "A card is required to start the trial. Nothing is charged for 7 days, and you can cancel before then.",
        "started": "Your free trial has started; nothing has been charged yet.",
        "signinNote": "NO ACCOUNT YET? START YOUR FREE TRIAL.",
        "signinLink": "START YOUR 7-DAY FREE TRIAL", "trialPhrase": "7-day free trial",
        "plannedPrice": "Planned price: $19.99/month",
    },
    "ON14": {
        "cta": "Start your 14-day free trial", "gate": "Start free trial",
        "record": "Start your 14-day free trial to see tonight's card",
        "hero": "14-day free trial, then $19.99/month. Cancel anytime.",
        "pricing": "14-day free trial, then $19.99/month. Cancel anytime. " + FOUNDING,
        "card": "A card is required to start the trial. Nothing is charged for 14 days, and you can cancel before then.",
        "started": "Your free trial has started; nothing has been charged yet.",
        "signinNote": "NO ACCOUNT YET? START YOUR FREE TRIAL.",
        "signinLink": "START YOUR 14-DAY FREE TRIAL", "trialPhrase": "14-day free trial",
        "plannedPrice": "Planned price: $19.99/month",
    },
    "ON0": {
        "cta": "Start your subscription", "gate": "Subscribe",
        "record": "Subscribe to see tonight's card",
        "hero": "$19.99/month. Cancel anytime.",
        "pricing": "$19.99/month. Cancel anytime. " + FOUNDING,
        "card": None, "started": None,
        "signinNote": "NO ACCOUNT YET? SUBSCRIBE.", "signinLink": "START YOUR SUBSCRIPTION",
        "trialPhrase": None, "plannedPrice": "Planned price: $19.99/month",
    },
    "ON7_NOPRICE": {
        "cta": "Start your 7-day free trial", "gate": "Start free trial",
        "record": "Start your 7-day free trial to see tonight's card",
        "hero": "7-day free trial. Cancel anytime.",
        "pricing": ("7-day free trial. Cancel anytime. This is the founding price: it rises as the "
                    "public record grows, and it can fall if the record does."),
        "card": "A card is required to start the trial. Nothing is charged for 7 days, and you can cancel before then.",
        "started": "Your free trial has started; nothing has been charged yet.",
        "signinNote": "NO ACCOUNT YET? START YOUR FREE TRIAL.",
        "signinLink": "START YOUR 7-DAY FREE TRIAL", "trialPhrase": "7-day free trial",
        "plannedPrice": None,
    },
}
METAS = {
    "ON7": {"billing": {"checkout": "on", "trial_days": 7, "price_cents": 1999}},
    "ON14": {"billing": {"checkout": "on", "trial_days": 14, "price_cents": 1999}},
    "ON0": {"billing": {"checkout": "on", "trial_days": 0, "price_cents": 1999}},
    "ON7_NOPRICE": {"billing": {"checkout": "on", "trial_days": 7}},
    "OFF": {"billing": {"checkout": "off", "trial_days": 7, "price_cents": 1999}},
    "UNAVAILABLE": {"billing": {"checkout": "unavailable", "trial_days": 7, "price_cents": 1999}},
    "UNREACHABLE": None,
}
OFF = {"billing": {"checkout": "off", "trial_days": 7, "price_cents": 1999}}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class UnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")
        Path(cls._tmp.name, "dump.mjs").write_text(DUMP, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _node(self, script, **env):
        proc = subprocess.run(["node", script], cwd=self._tmp.name, env=dict(os.environ, **env),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def _helpers(self):
        return self._node("dump.mjs", METAS=json.dumps(METAS))

    def _signup(self, meta, signup):
        return self._node("harness.mjs", SCENARIO=json.dumps({"meta": meta, "signup": signup}))

    # ---- checkout off ------------------------------------------------------

    def test_every_billing_off_state_shows_the_early_access_copy(self):
        helpers = self._helpers()
        for name in ("OFF", "UNAVAILABLE", "UNREACHABLE"):
            with self.subTest(state=name):
                got = helpers[name]
                self.assertEqual(got["cta"], "Request early access")
                self.assertEqual(got["gate"], "Request early access")
                self.assertEqual(got["record"], "Request early access")
                self.assertEqual(got["signinLink"], "REQUEST EARLY ACCESS")
                self.assertEqual(got["hero"], HERO_NOTE)

    def test_the_hero_note_without_a_price_drops_only_the_price(self):
        # Not reachable from /meta (a not-on state always carries the plan's own
        # planned price), but the function must not invent one if it is handed none.
        hero = self._helpers()["noPriceHero"]
        self.assertEqual(hero, "Early access: the first 20 testers get 7 days free, no card. "
                               "Not on sale yet. The record and the postseason odds are free now.")

    def test_the_constants_the_pages_share(self):
        constants = self._helpers()["constants"]
        self.assertEqual(constants["cta"], "Request early access")
        self.assertEqual(constants["note"], HERO_NOTE.split(" Not on sale")[0])
        self.assertEqual(constants["confirmation"], CONFIRMATION)

    # ---- checkout on: byte-identical ---------------------------------------

    def test_every_on_state_string_is_byte_identical_to_what_it_was(self):
        helpers = self._helpers()
        for name, expected in ON_STATE_BEFORE.items():
            with self.subTest(state=name):
                self.assertEqual(helpers[name], expected)

    def test_none_of_the_early_access_copy_leaks_into_the_on_state(self):
        helpers = self._helpers()
        for name in ON_STATE_BEFORE:
            blob = json.dumps(helpers[name]).lower()
            for needle in ("early access", "testers", "request early"):
                self.assertNotIn(needle, blob, (name, needle))

    # ---- the waitlist confirmation, rendered by the real signup page --------

    def test_a_waitlisted_signup_shows_the_confirmation_exactly(self):
        out = self._signup(OFF, {"user_id": 1, "status": "waitlisted"})
        self.assertEqual(out["waitlisted"], CONFIRMATION)
        self.assertIn({"url": "/signup", "method": "POST"}, out["calls"])

    def test_the_confirmation_replaces_the_old_not_open_message(self):
        out = self._signup(OFF, {"user_id": 1, "status": "waitlisted"})
        self.assertNotIn("Your email is saved", out["page"])
        self.assertEqual(out["page"].count("You're on the list."), 1)

    def test_no_other_signup_outcome_shows_the_confirmation(self):
        for result in ({"user_id": 1, "status": "invited"},
                       {"user_id": 1, "status": "active"},
                       {"user_id": 1, "status": "error", "message": "payments are not available right now; nothing has been charged"}):
            with self.subTest(result=result["status"]):
                out = self._signup(OFF, result)
                self.assertIsNone(out["waitlisted"])
                self.assertNotIn("You're on the list.", out["page"])

    def test_the_signup_form_still_promises_no_trial_while_off(self):
        out = self._signup(OFF, {"user_id": 1, "status": "waitlisted"})
        page = out["page"].replace(CONFIRMATION, "")
        self.assertIsNone(re.search(r"\btrial\b|cancel anytime|7-day", page, re.I), page)


if __name__ == "__main__":
    unittest.main()
