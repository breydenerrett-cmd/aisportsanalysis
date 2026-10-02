"""The landing page's first screen, per docs/CONVERSION_REVIEW_2026-10-02.md.

A stranger on a 390 px phone must learn within the first screen what this is,
what they get today, which sports, and what to do next, with the trust evidence
supporting the offer rather than being the headline. This file pins the seven
changes of that review (written 2026-10-02):

  1. the headline names the product; the method is the second sentence;
  2. the button says "Request early access" in every billing-off state, and the
     on-state wording is untouched (checkout.js is the one place that decides);
  3. a compact "what you get" block sits under the buttons and above the
     record panel, in DOM order;
  4. the record panel's labels are plain words (and no figure changed);
  5. one "Proven / Not proven" line sits under the record panel;
  6. Pricing sits directly after the free sample, and "How it works" and
     "Why we publish the losses" are folded into "what is proven";
  7. one <footer> element, with every link and legal sentence still present.

The static half reads web/landing.html as text. The behavioural half runs the
real web/js modules under node against a small fake DOM (the pattern of
tests/test_checkout_copy_states.py); skipped when node is not installed.
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
HTML = (WEB / "landing.html").read_text(encoding="utf-8")
LANDING_JS = (JS / "landing.js").read_text(encoding="utf-8")


def _markup() -> str:
    """The page with comments removed, so a hook named in a comment is not
    mistaken for the element."""
    return re.sub(r"<!--.*?-->", "", HTML, flags=re.S)


MARKUP = _markup()


def _at(needle: str) -> int:
    index = MARKUP.find(needle)
    assert index >= 0, f"{needle!r} is not in web/landing.html"
    return index


def _visible(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", text).strip()


class TheFirstScreenReadsInOrder(unittest.TestCase):
    def test_headline_then_buttons_then_what_you_get_then_the_record_panel(self):
        order = [
            ("headline", 'class="hero__claim-title"'),
            ("lede", 'class="hero__claim-body"'),
            ("primary button", 'data-hook="cta-signup-hero"'),
            ("secondary button", 'data-hook="cta-record-secondary"'),
            ("note", 'data-hook="hero-cta-note"'),
            ("what you get", 'data-hook="hero-wyg"'),
            ("record panel", 'data-hook="hero-proof"'),
        ]
        positions = [_at(needle) for _label, needle in order]
        self.assertEqual(positions, sorted(positions),
                         f"first-screen order broken: {[label for label, _ in order]}")
        self.assertEqual(len(set(positions)), len(positions))

    def test_the_headline_names_the_product_not_our_behaviour(self):
        title = re.search(r'<h1 class="hero__claim-title">(.*?)</h1>', MARKUP, re.S).group(1)
        self.assertEqual(title.strip(), "Tonight's MLB, NFL and UFC bets, posted before the game.")
        self.assertEqual(MARKUP.count("<h1"), 1)

    def test_the_lede_is_one_short_paragraph_with_no_schedule_and_no_figure(self):
        lede = re.search(r'<p class="hero__claim-body">(.*?)</p>', MARKUP, re.S).group(1).strip()
        self.assertEqual(
            lede,
            "A short card each night: the bet, the best price and where to find it, and why. "
            "Every card is graded in public afterwards, wins and losses.")

    def test_the_what_you_get_block_has_two_short_groups_and_no_bet_check(self):
        block = re.search(r'<div class="hero__wyg" data-hook="hero-wyg".*?</ul>\s*</div>\s*</div>',
                          MARKUP, re.S).group(0)
        text = _visible(block)
        self.assertIn("Free now", text)
        self.assertIn("For subscribers", text)
        free = block.split('data-hook="hero-wyg-subscribers"')[0]
        subs = block.split('data-hook="hero-wyg-subscribers"')[1]
        self.assertIn("The full graded record", free)
        self.assertIn("MLB postseason odds", free)
        self.assertIn("Tonight's card, before the game", subs)
        self.assertIn("Matchups, odds and props", subs)
        self.assertEqual(block.count("<li"), 4)
        self.assertNotRegex(text, r"\d", "a figure typed into the what-you-get block goes stale")
        self.assertNotRegex(text.lower(), r"bet[\s-]*check|trial|cancel anytime")

    def test_the_hero_note_is_the_early_access_offer_then_the_planned_price(self):
        note = re.search(r'<p class="hero__cta-note" data-hook="hero-cta-note">(.*?)</p>',
                         MARKUP, re.S).group(1).strip()
        self.assertEqual(
            note,
            "Early access: the first 20 testers get 7 days free, no card. "
            "Not on sale yet; planned price $19.99 a month. "
            "The record and the postseason odds are free now.")


class TheSecondButtonAndTheFullRecordLink(unittest.TestCase):
    def test_as_written_the_secondary_button_is_a_link_that_works_with_no_script(self):
        # The sample section is hidden until a script fills it, so the markup
        # must not point at it: with scripts off that button went nowhere.
        # landing.js upgrades it once the sample is showing (tested below).
        tag = re.search(r'<a\b[^>]*data-hook="cta-record-secondary"[^>]*>(.*?)</a>', MARKUP, re.S)
        self.assertEqual(tag.group(1).strip(), "See every pick, graded")
        self.assertIn('href="index.html#/record-card"', tag.group(0))
        self.assertNotIn('href="#free-sample"', tag.group(0))
        self.assertIn('id="free-sample"', MARKUP)
        self.assertIn('data-hook="last-card"', re.search(r'<section\b[^>]*id="free-sample"[^>]*>',
                                                         MARKUP).group(0))

    def test_the_full_record_is_one_visible_real_link_right_under_the_buttons(self):
        link = re.search(r'<a\b[^>]*data-hook="hero-record-link"[^>]*>', MARKUP).group(0)
        self.assertIn('href="index.html#/record-card"', link)
        self.assertNotIn('tabindex="-1"', link)
        group = re.search(r'<div class="hero__cta-group".*?</div>', MARKUP, re.S).group(0)
        self.assertIn('data-hook="hero-record-link"', group)

    def test_every_in_page_anchor_has_a_target(self):
        ids = set(re.findall(r'\sid="([^"]+)"', MARKUP))
        for target in set(re.findall(r'href="#([^"]+)"', MARKUP)):
            self.assertIn(target, ids, f"href=\"#{target}\" has no element with that id")

    def test_the_funnel_hooks_still_exist_exactly_once_each(self):
        for hook in ("cta-primary", "cta-signup-hero", "cta-signup", "cta-signup-bottom",
                     "cta-record-secondary"):
            self.assertEqual(MARKUP.count(f'data-hook="{hook}"'), 1, hook)


class TheEarlyAccessLabelIsOneDecision(unittest.TestCase):
    def test_every_static_checkout_button_says_request_early_access(self):
        labels = [m.strip() for m in re.findall(r"<a[^>]*data-checkout-cta[^>]*>(.*?)</a>", MARKUP, re.S)]
        self.assertEqual(len(labels), 4, "nav, hero, pricing card, closing band")
        self.assertEqual(set(labels), {"Request early access"})
        self.assertNotIn("Get notified when checkout opens", MARKUP)

    def test_the_label_is_decided_in_checkout_js_alone(self):
        checkout = (JS / "checkout.js").read_text(encoding="utf-8")
        self.assertIn('export const CAUTIOUS_CTA = "Request early access";', checkout)
        for name in ("landing.js", "signup.js", "signin.js", "cardrecord.js", "dom.js"):
            source = (JS / name).read_text(encoding="utf-8")
            self.assertNotIn("Request early access", source, name)
            self.assertNotIn("Join the waitlist", source, name)


class TheRecordPanelUsesPlainWords(unittest.TestCase):
    def test_no_rule_vocabulary_is_left_in_a_visible_label(self):
        for needle in ("Current rule", "Previous rule", "CURRENT RULE", "PREVIOUS RULE"):
            self.assertNotIn(needle, MARKUP, needle)
        code = re.sub(r"/\*.*?\*/", " ", LANDING_JS, flags=re.S)
        code = "\n".join(l for l in code.splitlines() if not l.strip().startswith("//"))
        for needle in ("Current rule", "Previous rule", "current rule"):
            self.assertNotIn(needle, code, needle)

    def test_the_labels_are_current_method_and_earlier_method_retired(self):
        labels = re.findall(r'data-hook="[\w-]+-(?:current|previous)-label">([^<]*)</p>', MARKUP)
        self.assertEqual(len(labels), 8, "hero + MLB + NFL + UFC, current and previous each")
        self.assertEqual(sorted(set(labels)), ["Current method", "Earlier method (retired)"])
        self.assertIn('{ role: "current", label: "Current method" }', LANDING_JS)
        self.assertIn('{ role: "previous", label: "Earlier method (retired)" }', LANDING_JS)

    def test_the_panel_still_shows_all_six_figures_in_the_same_markup(self):
        panel = re.search(r'<aside class="hero__proof".*?</aside>', MARKUP, re.S).group(0)
        for kind in ("wl", "units", "days"):
            for role in ("current", "previous"):
                self.assertIn(f'data-hook="hero-{role}-{kind}"', panel)
        self.assertEqual(panel.count("hero__stat-value"), 6)


class TheProvenLine(unittest.TestCase):
    LINE = ("Proven: every pick is published before the game and never edited. "
            "Not proven: that the picks make money.")

    def test_the_line_is_present_verbatim_in_the_static_html(self):
        node = re.search(r'<p class="hero__proven-line" data-hook="hero-proven-line">(.*?)</p>', MARKUP, re.S)
        self.assertIsNotNone(node, "no proven / not proven line under the record panel")
        self.assertEqual(_visible(node.group(1)), self.LINE)

    def test_it_sits_under_the_record_panel_and_before_the_rest_of_the_page(self):
        self.assertGreater(_at('data-hook="hero-proven-line"'), _at("</aside>"))
        self.assertLess(_at('data-hook="hero-proven-line"'), _at('data-hook="what-you-get"'))
        self.assertLess(_at('data-hook="hero-proven-line"'), _at('data-hook="hero-feature"'))

    def test_it_is_not_hidden_behind_a_click_or_an_attribute(self):
        tag = re.search(r'<p class="hero__proven-line"[^>]*>', MARKUP).group(0)
        self.assertNotIn("hidden", tag)
        self.assertNotIn("<details", re.search(r'<div class="hero__proof-col">.*?</div>\s*</div>',
                                                MARKUP, re.S).group(0))


class PricingFollowsTheSampleAndTheTrustSectionsAreMerged(unittest.TestCase):
    def test_pricing_comes_directly_after_the_free_sample(self):
        sample_end = MARKUP.index("</section>", _at('data-hook="last-card"')) + len("</section>")
        pricing_open = MARKUP.rfind("<section", 0, _at('data-hook="pricing"'))
        between = MARKUP[sample_end:pricing_open]
        self.assertEqual(between.strip(), "", f"markup between the sample and pricing: {between!r}")

    def test_the_old_order_is_gone(self):
        self.assertLess(_at('data-hook="last-card"'), _at('data-hook="pricing"'))
        self.assertLess(_at('data-hook="pricing"'), _at('data-hook="losing-pick-demo"'))
        self.assertLess(_at('data-hook="pricing"'), _at('data-hook="sports-covered"'))
        self.assertLess(_at('data-hook="pricing"'), _at('data-hook="faq"'))

    def test_how_it_works_and_why_we_publish_the_losses_are_folded_in(self):
        self.assertNotIn('data-hook="how-it-works"', MARKUP)
        self.assertNotIn("Three steps. Nothing hidden.", MARKUP)
        self.assertNotIn("Why we publish the losses", MARKUP)
        proven = re.search(r'<section\b[^>]*data-hook="proven-block"[^>]*>.*?</section>', MARKUP, re.S).group(0)
        self.assertIn('id="how-it-works"', proven)
        text = _visible(proven)
        for claim in ("how likely it is by the whole market and by our own numbers",
                      "what the price needs to break even",
                      "hash-chained",
                      "Nothing is re-graded, re-ranked, removed or edited",
                      "Losses stay on the record at the same size as the wins",
                      "one public page you can open yourself",
                      "pre-registered",
                      "bullpen workload",
                      "We publish that too"):
            self.assertIn(claim, text, claim)
        self.assertEqual(MARKUP.count("hash-chained"), 1, "said once")

    def test_the_wrong_pick_stays_and_the_negative_record_is_untouched(self):
        self.assertIn("A pick we got wrong, in full", MARKUP)
        self.assertIn('data-hook="losing-pick-demo"', MARKUP)
        self.assertEqual(MARKUP.count('data-hook="card-record"'), 1)
        self.assertEqual(MARKUP.count('data-hook="research-count"'), 1,
                         "the figure lives in the FAQ answer only")


class OneFooter(unittest.TestCase):
    def test_exactly_one_footer_element_in_the_static_page(self):
        self.assertEqual(len(re.findall(r"<footer\b", MARKUP)), 1)
        self.assertEqual(len(re.findall(r"</footer>", MARKUP)), 1)

    def test_every_footer_link_and_sentence_is_still_there(self):
        footer = re.search(r"<footer\b.*?</footer>", MARKUP, re.S).group(0)
        for href in ('href="#how-it-works"', 'href="#pricing"', 'href="#faq"',
                     'href="index.html#/betcheck"'):
            self.assertIn(href, footer, href)
        text = _visible(footer)
        self.assertIn("About the data on this page", text)
        self.assertIn("real pick from our public ledger", text)
        self.assertIn('data-hook="disclaimer-host"', footer)
        self.assertEqual(MARKUP.count('data-hook="disclaimer-host"'), 1)

    def test_the_shared_legal_block_mounts_as_a_group_inside_the_footer(self):
        meta = (JS / "meta.js").read_text(encoding="utf-8")
        self.assertIn('container.closest("footer")', meta)
        # the legal sentences themselves are still rendered, unchanged
        for sentence in ("21+ · PLAY RESPONSIBLY", "1-800-GAMBLER", "This is analysis, not advice."):
            self.assertIn(sentence, meta, sentence)


# ---------------------------------------------------------------------------
# Behavioural half -- the real modules under node.
# ---------------------------------------------------------------------------

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.isRoot = false; this.style = {};
    this.ancestorFooter = false;
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
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener() {}
  closest(sel) {
    for (let n = this; n; n = n.parentNode) if (n.tagName && n.tagName.toLowerCase() === sel) return n;
    return null;
  }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:=(?:'([^']*)'|"([^"]*)"))?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const name = m[1]; const val = m[2] !== undefined ? m[2] : m[3];
    return this._all([]).filter((n) => name in n.attrs && (val === undefined || n.attrs[name] === val));
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
globalThis.fetch = async (url) => {
  url = String(url);
  if (url.startsWith("/card/history")) {
    if (scenario.history && scenario.history.throw) throw new Error("offline");
    const { status, body: payload } = scenario.history;
    return { ok: status < 400, status, text: async () => JSON.stringify(payload) };
  }
  throw new Error("offline");
};

const out = {};
if (scenario.kind === "labels") {
  const c = await import("./checkout.js");
  const state = c.checkoutState(scenario.meta);
  out.on = state.on;
  out.cta = c.ctaLabel(state); out.gate = c.gateLabel(state); out.record = c.recordCtaLabel(state);
  out.hero = c.heroNote(state); out.signin = c.signinLinkLabel(state);
} else if (scenario.kind === "button") {
  const mk = (tag, hook, attrs) => {
    const n = new Elem(tag); n.setAttribute("data-hook", hook);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    return n;
  };
  const button = mk("a", "cta-record-secondary", { href: "#free-sample" });
  button.textContent = "See last night's card, graded";
  const section = mk("section", "last-card", { hidden: "" });
  const bodyNode = mk("div", "last-card-body");
  section.appendChild(bodyNode);
  body.appendChild(button); body.appendChild(section);
  const landing = await import("./landing.js");
  await landing.fillLastCard();
  out.label = button.textContent; out.href = button.getAttribute("href"); out.hidden = section.hidden;
} else if (scenario.kind === "footer") {
  const { renderDisclaimerFooter } = await import("./meta.js");
  const host = new Elem(scenario.inFooter ? "div" : "div");
  const holder = new Elem(scenario.inFooter ? "footer" : "div");
  holder.appendChild(host); body.appendChild(holder);
  await renderDisclaimerFooter(host);
  const region = host.children[0];
  out.tag = region.tagName; out.role = region.getAttribute("role");
  out.label = region.getAttribute("aria-label"); out.hook = region.getAttribute("data-hook");
  out.footers = body._all([]).filter((n) => n.tagName === "FOOTER").length;
  out.text = (function t(n) { return n.nodeType === 3 ? n.textContent : n.childNodes.map(t).join("|"); })(region);
}
console.log("@@" + JSON.stringify(out));
"""

OFF = {"billing": {"checkout": "off", "trial_days": 7, "price_cents": 1999}}
UNAVAILABLE = {"billing": {"checkout": "unavailable", "trial_days": 7, "price_cents": 1999}}
NOT_ON_CASES = (("off", OFF), ("unavailable", UNAVAILABLE), ("unreachable", None),
                ("no billing key", {}), ("garbage", {"billing": {"checkout": "yes"}}))
ON7 = {"billing": {"checkout": "on", "trial_days": 7, "price_cents": 1999}}
ON14 = {"billing": {"checkout": "on", "trial_days": 14, "price_cents": 1999}}
ON0 = {"billing": {"checkout": "on", "trial_days": 0, "price_cents": 1999}}

HERO_OFF = ("Early access: the first 20 testers get 7 days free, no card. "
            "Not on sale yet; planned price $19.99 a month. "
            "The record and the postseason odds are free now.")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class UnderNode(unittest.TestCase):
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
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- change 2: the label in every state --------------------------------

    def test_every_billing_off_state_says_request_early_access_everywhere(self):
        for name, meta in NOT_ON_CASES:
            with self.subTest(state=name):
                out = self.run_scenario(kind="labels", meta=meta)
                self.assertFalse(out["on"])
                for key in ("cta", "gate", "record"):
                    self.assertEqual(out[key], "Request early access", key)
                self.assertEqual(out["signin"], "REQUEST EARLY ACCESS")
                self.assertEqual(out["hero"], HERO_OFF)
                for key in ("cta", "gate", "record", "hero"):
                    self.assertIsNone(re.search(r"trial|cancel anytime|checkout", out[key], re.I),
                                      (key, out[key]))

    def test_the_hero_note_takes_the_planned_price_from_meta(self):
        out = self.run_scenario(kind="labels", meta={"billing": {"checkout": "off", "price_cents": 1999}})
        self.assertIn("planned price $19.99 a month.", out["hero"])

    def test_the_on_state_wording_is_exactly_what_it_was(self):
        out = self.run_scenario(kind="labels", meta=ON14)
        self.assertTrue(out["on"])
        self.assertEqual(out["cta"], "Start your 14-day free trial")
        self.assertEqual(out["gate"], "Start free trial")
        self.assertEqual(out["record"], "Start your 14-day free trial to see tonight's card")
        self.assertEqual(out["hero"], "14-day free trial, then $19.99/month. Cancel anytime.")
        self.assertEqual(out["signin"], "START YOUR 14-DAY FREE TRIAL")
        out = self.run_scenario(kind="labels", meta=ON7)
        self.assertEqual(out["hero"], "7-day free trial, then $19.99/month. Cancel anytime.")
        out = self.run_scenario(kind="labels", meta=ON0)
        self.assertEqual(out["cta"], "Start your subscription")
        self.assertEqual(out["gate"], "Subscribe")
        self.assertEqual(out["record"], "Subscribe to see tonight's card")
        self.assertEqual(out["hero"], "$19.99/month. Cancel anytime.")

    # ---- the second button never points at a section that is not there ----

    def test_the_secondary_button_becomes_the_record_link_when_the_sample_is_hidden(self):
        for name, history in (("fetch fails", {"throw": True}),
                              ("server error", {"status": 500, "body": {"detail": "boom"}}),
                              ("no settled day", {"status": 200, "body": {"days": []}})):
            with self.subTest(case=name):
                out = self.run_scenario(kind="button", history=history)
                self.assertTrue(out["hidden"])
                self.assertEqual(out["label"], "See every pick, graded")
                self.assertEqual(out["href"], "index.html#/record-card")

    def test_the_secondary_button_stays_on_the_sample_when_it_is_showing(self):
        day = {"date": "2026-09-30", "rule": "DAILY_CARD_BEST_BETS_V2", "graded": [
            {"entry_class": "pick", "kind": "game", "market": "moneyline", "withdrawn": False,
             "book": None, "books": 11, "line": None, "player": None, "side": "home",
             "team_name": "Yankees", "price": -135, "result": "WIN", "profit_units": 0.7407,
             "away_team": "BOS", "home_team": "NYY", "away_score": 2, "home_score": 9,
             "reason": None, "bet": None, "game_type": "R"}]}
        out = self.run_scenario(kind="button", history={"status": 200, "body": {"days": [day]}})
        self.assertFalse(out["hidden"])
        self.assertEqual(out["label"], "See last night's card, graded")
        self.assertEqual(out["href"], "#free-sample")

    # ---- change 7: one footer, at run time too ------------------------------

    def test_inside_the_page_footer_the_shared_legal_block_is_a_group_not_a_second_footer(self):
        out = self.run_scenario(kind="footer", inFooter=True)
        self.assertEqual(out["tag"], "DIV")
        self.assertEqual(out["role"], "group")
        self.assertEqual(out["label"], "disclaimer")
        self.assertEqual(out["hook"], "disclaimer")
        self.assertEqual(out["footers"], 1, "only the page's own <footer> remains")
        for sentence in ("21+ · PLAY RESPONSIBLY", "1-800-GAMBLER", "This is analysis, not advice."):
            self.assertIn(sentence, out["text"])

    def test_the_app_shell_still_gets_its_own_footer_element(self):
        out = self.run_scenario(kind="footer", inFooter=False)
        self.assertEqual(out["tag"], "FOOTER")
        self.assertIsNone(out["role"])
        self.assertEqual(out["footers"], 1)


if __name__ == "__main__":
    unittest.main()
