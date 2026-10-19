"""The landing page's AI-desk section (the old first screen), per docs/CONVERSION_REVIEW_2026-10-02.md.

PROFESSIONAL PASS, 2026-10-19: the first screen is now a live leaderboard hero ("AI betting models, tracked in
public."), and the AI desk below it is unchanged.

OWNER VOICE PASS, 2026-10-18 (docs/VOICE.md): the first screen is now the kennel ("Paper betting bots
fighting it out every day ..."), and everything this file pins about the old first screen is the SECOND
section, "Our AI desk reads every game", unchanged in order and in its funnel hooks. The long honesty essays
(what is proven, a pick we got wrong, the research-count FAQ) are cut to one human line and a link; the tests
that pinned them are replaced below by tests that pin the cut.

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

    def test_the_ai_desk_headline_names_the_product_not_our_behaviour(self):
        title = re.search(r'<h2 class="hero__claim-title">(.*?)</h2>', MARKUP, re.S).group(1)
        self.assertEqual(title.strip(), 'Our AI desk reads every game.')
        self.assertNotRegex(title.lower(), r"tonight|picks|bets|posted before")
        self.assertEqual(MARKUP.count("<h1"), 1, "one h1 on the page: the leaderboard hero's")

    def test_the_lede_is_one_short_paragraph_with_no_schedule_and_no_figure(self):
        lede = re.search(r'<p class="hero__claim-body">(.*?)</p>', MARKUP, re.S).group(1).strip()
        self.assertEqual(lede, (
            "An AI analyst reads each matchup, calls every market take or pass, gives the strongest case "
            "against any bet it takes, and says what it could not know. Every call is graded in public. "
            "Analysis, not advice."))
        self.assertNotRegex(lede, r"\d")

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
        self.assertIn("A brief for every game we cover, before it starts", subs)
        self.assertNotIn("Tonight's card", subs)
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
        self.assertEqual(tag.group(1).strip(), "Open the graded record")
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


class TheLeaderboardIsTheFirstScreen(unittest.TestCase):
    """Owner, 2026-10-19: the site "looks like a kids playground, not a professional gambling AI website". The first
    screen is a plain headline, one sentence on how it works, a live mini leaderboard and the latest tickets."""

    TITLE = "AI betting models, tracked in public."
    SUB = ("Dozens of models make paper bets every day. Every ticket is recorded before the game and graded after. "
           "Follow the ones that are winning.")

    def test_the_one_h1_is_the_headline_verbatim_and_the_subline_follows_it(self):
        h1 = re.search(r'<h1 class="lbhero__title" data-hook="lb-title">(.*?)</h1>', MARKUP, re.S)
        self.assertIsNotNone(h1)
        self.assertEqual(_visible(h1.group(1)), self.TITLE)
        self.assertEqual(MARKUP.count("<h1"), 1)
        sub = re.search(r'<p class="lbhero__sub" data-hook="lb-sub">(.*?)</p>', MARKUP, re.S)
        self.assertEqual(_visible(sub.group(1)), self.SUB)

    def test_the_hero_comes_first_then_buttons_then_the_leaderboard_then_the_ai_desk(self):
        order = [("hero", 'data-hook="lb-hero"'), ("headline", 'data-hook="lb-title"'), ("subline", 'data-hook="lb-sub"'),
                 ("enter", 'data-hook="cta-kennel-enter"'), ("build", 'data-hook="cta-kennel-build"'),
                 ("straight", 'data-hook="kennel-straight"'), ("board", 'data-hook="lb-board"'),
                 ("tickets", 'data-hook="lb-tickets"'), ("ai desk", 'data-hook="hero"')]
        positions = [_at(needle) for _label, needle in order]
        self.assertEqual(positions, sorted(positions), [label for label, _ in order])
        self.assertLess(_at('data-hook="landing-header"'), _at('data-hook="lb-hero"'))

    def test_the_two_calls_to_action_are_view_the_leaderboard_and_build_a_model(self):
        enter = re.search(r'<a\b[^>]*data-hook="cta-kennel-enter"[^>]*>(.*?)</a>', MARKUP, re.S)
        build = re.search(r'<a\b[^>]*data-hook="cta-kennel-build"[^>]*>(.*?)</a>', MARKUP, re.S)
        self.assertEqual(enter.group(1).strip(), "View the leaderboard")
        self.assertIn('href="hounds.html"', enter.group(0))
        self.assertEqual(build.group(1).strip(), "Build a model")
        self.assertIn('href="build-a-hound.html"', build.group(0))
        # data-hook starts with "cta", so landing.js's delegated listener counts both clicks
        self.assertIn("closest(\"[data-hook^='cta']\")", LANDING_JS)

    def test_the_disclosure_is_said_once_on_the_page_in_the_shared_footer_and_not_in_the_body_copy(self):
        main = re.search(r"<main>.*?</main>", MARKUP, re.S).group(0)
        text = _visible(main)
        self.assertNotRegex(text, r"(?i)paper bets only")
        self.assertNotRegex(text, r"(?i)nobody here bets real money")
        self.assertEqual(len(re.findall(r"21\+", text)), 0, "21+ is the footer's line, not the body's")
        self.assertNotIn('data-hook="kennel-legal"', MARKUP)
        # the footer mounts the shared legal block: 21+, the helpline, the not-advice summary
        self.assertIn('data-hook="disclaimer-host"', MARKUP)

    def test_the_mini_leaderboard_is_filled_by_a_script_and_names_no_figure_when_it_has_none(self):
        panel = re.search(r'<section class="lbpanel" aria-label="top models".*?</section>', MARKUP, re.S).group(0)
        text = _visible(panel)
        self.assertIn("Top models by bankroll", text)
        self.assertIn("Every model starts with the same $1,000 paper bankroll. 1 unit = $10.", text)   # the shared start, static
        self.assertIn("Checking the leaderboard", text)
        self.assertNotRegex(text, r"[+-]\d")
        self.assertIn('href="hounds.html"', panel)
        self.assertIn("fillBoard", LANDING_JS)
        self.assertIn('from "./landing-board.js"', LANDING_JS)
        self.assertNotIn("landing-kennel", LANDING_JS)

    def test_the_first_screen_has_no_toy_voice_no_emoji_and_no_cartoon(self):
        hero = re.search(r'<section class="lbhero".*?</section>\s*(?=<section class="(?:kncard|hero)")', MARKUP, re.S).group(0)
        text = _visible(hero).lower()
        for word in ("kennel", "dog", "bark", "put down", "doghouse", "houndmaster", "fighting it out"):
            self.assertNotIn(word, text, word)
        self.assertNotRegex(hero, "[\U0001F300-\U0001FAFF\u2600-\u27BF]")
        self.assertNotIn("<svg", hero)
        self.assertNotIn("kennel__", MARKUP)

    def test_the_honesty_essays_are_gone_and_one_human_line_links_to_the_full_story(self):
        for hook in ("proven-block", "honesty-story", "losing-pick-demo", "hero-proven-line", "hero-pause-note",
                     "faq-no-edge", "faq-hit-rate", "faq-price-improvement"):
            self.assertNotIn(f'data-hook="{hook}"', MARKUP, hook)
        text = _visible(MARKUP)
        for gone in ("hash-chained", "pre-registered", "bullpen workload", "A pick we got wrong",
                     "What is proven and what is not", "falsification"):
            self.assertNotIn(gone, text, gone)
        line = re.search(r'<p class="lbhero__straight" data-hook="kennel-straight">(.*?)</p>', MARKUP, re.S).group(1)
        self.assertIn('href="why-we-paused.html"', line)
        self.assertEqual(MARKUP.count("why-we-paused.html"), 1)

    def test_the_faq_does_not_repeat_the_disclaimer(self):
        faq = re.search(r'<section[^>]*data-hook="faq".*?</section>', MARKUP, re.S).group(0)
        self.assertNotIn('data-hook="faq-gambling-advice"', faq)
        self.assertIn('data-hook="faq-kennel"', faq)             # the hook is kept; the copy now says "models"
        self.assertIn("What are the models?", faq)


class PricingFollowsTheSampleAndTheTrustSectionsAreMerged(unittest.TestCase):
    def test_pricing_comes_directly_after_the_free_sample(self):
        sample_end = MARKUP.index("</section>", _at('data-hook="last-card"')) + len("</section>")
        pricing_open = MARKUP.rfind("<section", 0, _at('data-hook="pricing"'))
        between = MARKUP[sample_end:pricing_open]
        self.assertEqual(between.strip(), "", f"markup between the sample and pricing: {between!r}")

    def test_the_old_order_is_gone(self):
        self.assertLess(_at('data-hook="last-card"'), _at('data-hook="pricing"'))
        self.assertLess(_at('data-hook="pricing"'), _at('data-hook="sports-covered"'))
        self.assertLess(_at('data-hook="pricing"'), _at('data-hook="faq"'))
        self.assertNotIn('data-hook="losing-pick-demo"', MARKUP)

    def test_the_trust_essays_are_cut_down_to_the_kennel_line_and_a_link(self):
        # was: "how it works" and "why we publish the losses" folded into one "what is proven" section. Owner voice
        # pass, 2026-10-18: that section is the essay the owner asked us to cut; its facts live on the why-we-stopped page.
        self.assertNotIn('data-hook="how-it-works"', MARKUP)
        self.assertNotIn('data-hook="proven-block"', MARKUP)
        self.assertNotIn("Three steps. Nothing hidden.", MARKUP)
        self.assertNotIn("Why we publish the losses", MARKUP)
        self.assertEqual(MARKUP.count("hash-chained"), 0)
        self.assertIn('id="desk"', MARKUP)

    def test_the_record_figures_are_filled_from_the_ledger_and_not_typed(self):
        self.assertEqual(MARKUP.count('data-hook="card-record"'), 1)
        self.assertEqual(MARKUP.count('data-hook="research-count"'), 0,
                         "the research-count FAQ essay is cut; the fill is a no-op without its node")


class OneFooter(unittest.TestCase):
    def test_exactly_one_footer_element_in_the_static_page(self):
        self.assertEqual(len(re.findall(r"<footer\b", MARKUP)), 1)
        self.assertEqual(len(re.findall(r"</footer>", MARKUP)), 1)

    def test_every_footer_link_and_sentence_is_still_there(self):
        footer = re.search(r"<footer\b.*?</footer>", MARKUP, re.S).group(0)
        for href in ('href="hounds.html"', 'href="#desk"', 'href="#pricing"', 'href="#faq"',
                     'href="index.html#/betcheck"'):
            self.assertIn(href, footer, href)
        text = _visible(footer)
        self.assertIn("About the data on this page", text)
        self.assertIn("live results from our public ledger", text)
        self.assertIn('data-hook="disclaimer-host"', footer)
        self.assertEqual(MARKUP.count('data-hook="disclaimer-host"'), 1)

    def test_the_shared_legal_block_mounts_as_a_group_inside_the_footer(self):
        meta = (JS / "meta.js").read_text(encoding="utf-8")
        self.assertIn('container.closest("footer")', meta)
        # the legal sentences themselves are still rendered, unchanged
        for sentence in ("21+ · Gamble responsibly.", "1-800-GAMBLER", "This is analysis, not advice."):
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
  button.textContent = "See the latest graded card";
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
                self.assertEqual(out["label"], "Open the graded record")
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
        self.assertEqual(out["label"], "See the latest graded card")
        self.assertEqual(out["href"], "#free-sample")

    # ---- change 7: one footer, at run time too ------------------------------

    def test_inside_the_page_footer_the_shared_legal_block_is_a_group_not_a_second_footer(self):
        out = self.run_scenario(kind="footer", inFooter=True)
        self.assertEqual(out["tag"], "DIV")
        self.assertEqual(out["role"], "group")
        self.assertEqual(out["label"], "disclaimer")
        self.assertEqual(out["hook"], "disclaimer")
        self.assertEqual(out["footers"], 1, "only the page's own <footer> remains")
        for sentence in ("21+ · Gamble responsibly.", "1-800-GAMBLER", "This is analysis, not advice."):
            self.assertIn(sentence, out["text"])

    def test_the_app_shell_still_gets_its_own_footer_element(self):
        out = self.run_scenario(kind="footer", inFooter=False)
        self.assertEqual(out["tag"], "FOOTER")
        self.assertIsNone(out["role"])
        self.assertEqual(out["footers"], 1)


if __name__ == "__main__":
    unittest.main()
