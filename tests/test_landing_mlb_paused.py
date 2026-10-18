"""The landing page after the MLB value picks were paused (owner decision 2026-10-16,
docs/decisions/MLB_VALUE_PICKS_PAUSED.md).

The page used to sell "tonight's picks, frozen before first pitch". From the 2026-10-17
slate that is false for MLB, so the first screen now describes what is live (the matchup
brief, the board, the public record), says the pause in one sentence beside the record
link, and the hero's live module never shows a pick while `GET /card` answers
`paused: true`.

Static half: web/landing.html read as text. Behavioural half: the real
web/js/landing-live.js under node against a small fake DOM and a fake fetch (the pattern
of tests/test_landing_first_screen.py); skipped when node is not installed.
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
MARKUP = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)


def _visible(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", text).strip()


def _first_screen() -> str:
    """Everything from the opening <main> through the end of the hero section."""
    start = MARKUP.index("<main>")
    end = MARKUP.index("</section>", MARKUP.index('data-hook="hero-feature"'))
    return MARKUP[start:end]


PAUSE_SENTENCE = (
    "MLB value picks are paused as of Oct 16, 2026, because they paid a premium over the "
    "market's own number and our forecasts carried no information the market lacked.")


class TheStaticPageNoLongerSellsPicks(unittest.TestCase):
    def test_title_and_descriptions_describe_the_brief_not_tonights_picks(self):
        title = re.search(r"<title>(.*?)</title>", HTML, re.S).group(1)
        desc = re.search(r'<meta name="description" content="([^"]*)"', HTML).group(1)
        og_title = re.search(r'<meta property="og:title" content="([^"]*)"', HTML).group(1)
        og_desc = re.search(r'<meta property="og:description" content="([^"]*)"', HTML).group(1)
        for label, text in (("title", title), ("description", desc),
                            ("og:title", og_title), ("og:description", og_desc)):
            self.assertNotRegex(text.lower(), r"tonight|frozen before|posted before the game|"
                                r"every pick published", label)
            self.assertNotRegex(text.lower(), r"bet[\s-]*check", label)
        # owner voice pass, 2026-10-18: the page sells the kennel first; the brief is the second section
        self.assertIn("paper betting", title.lower())
        self.assertIn("paper betting", og_title.lower())
        self.assertIn("AI desk", desc)
        self.assertIn("paused", desc)
        self.assertIn("paused", og_desc)
        self.assertIn("Paper bets only, not advice", desc)
        self.assertIn("Planned price: $19.99/month", desc)
        self.assertNotRegex(desc + og_desc, r"(?i)\bwin rate\b|\bprofit\b|\bROI\b")

    def test_the_first_screen_sells_nothing_that_stopped(self):
        text = _visible(_first_screen())
        for phrase in ("every pick published", "Tonight's MLB", "bets, posted before the game",
                       "Tonight's card", "See every pick, graded", "A short card each night"):
            self.assertNotIn(phrase, text, phrase)
        self.assertNotRegex(text.lower(), r"bet[\s-]*check")

    def test_the_first_screen_says_what_is_live(self):
        text = _visible(_first_screen())
        self.assertIn("21+ paper betting bots fighting it out every day.", text)
        self.assertIn("Our AI desk reads every game.", text)           # the brief, now the second section
        self.assertIn("take or pass", text)
        self.assertIn("strongest case against any bet it takes", text)
        self.assertIn("what it could not know", text)
        self.assertIn("graded in public", text)
        self.assertIn("Analysis, not advice", text)
        self.assertIn("MLB briefs", text)
        self.assertIn("The graded record stays public", text)
        # unchanged offer facts
        self.assertIn("the first 20 testers get 7 days free, no card", text)
        self.assertIn("Not on sale yet; planned price $19.99 a month", text)

    def test_the_pause_is_one_human_line_with_the_reason_and_a_link_on_the_first_screen(self):
        # owner voice pass, 2026-10-18: the long pause paragraph is one line and a link to the full story
        note = re.search(r'<p class="kennel__straight" data-hook="kennel-straight">(.*?)</p>', MARKUP, re.S)
        self.assertIsNotNone(note, "no pause line on the first screen")
        text = _visible(note.group(1))
        self.assertIn("We stopped selling MLB picks on Oct 16, 2026 because they didn't beat the market.", text)
        self.assertIn("The graded record stays public", text)
        self.assertIn("NFL picks carry on", text)
        self.assertIn("Why we stopped selling picks", text)
        self.assertLess(len(text), 220, "one line, not an essay")
        self.assertLess(MARKUP.index("kennel-straight"), MARKUP.index('data-hook="hero"'))
        # the record link and the sample brief are still one click away in the AI desk section
        group = re.search(r'<div class="hero__cta-group".*?</div>', MARKUP, re.S).group(0)
        for hook in ("hero-record-link", "hero-sample-link"):
            self.assertIn(f'data-hook="{hook}"', group, hook)
        # no profit or win-rate claim, no figure other than the date
        self.assertNotRegex(re.sub(r"Oct 16, 2026", "", text), r"\d")
        self.assertNotRegex(text.lower(), r"profit|win rate|roi\b|guarantee")

    def test_the_sample_brief_is_one_click_from_the_first_screen(self):
        link = re.search(r'<a\b[^>]*data-hook="hero-sample-link"[^>]*>', MARKUP).group(0)
        self.assertIn('href="sample.html"', link)
        self.assertTrue((WEB / "sample.html").is_file())

    def test_no_section_still_promises_tonights_mlb_card(self):
        page = _visible(MARKUP)
        for phrase in ("Tonight's card, before the game", "Tonight's cards before the game",
                       "The next card posts before first pitch",
                       "MLB and NFL carry live picks", "tonight's card joins the free record",
                       "The full card, every night of the season"):
            self.assertNotIn(phrase, page, phrase)
        self.assertIn("Value picks paused as of Oct 16, 2026", page)
        # the NFL is still described as live: the pause does not touch it
        self.assertIn("NFL carries live picks", page)

    def test_the_paused_module_starts_hidden_and_carries_no_pick(self):
        module = re.search(r'<div class="hero__paused[^"]*" data-hook="hero-paused"[^>]*>.*?</div>',
                           MARKUP, re.S).group(0)
        self.assertIn("hidden", module.split(">")[0])
        text = _visible(module)
        self.assertIn("MLB picks are paused", text)
        self.assertIn("Read a sample brief", text)
        self.assertIn('href="sample.html"', module)
        self.assertNotRegex(text, r"[+\-−]\d{3}")
        # and the server's own sentence, word for word
        config = json.loads((ROOT / "config" / "mlb_public_card.json").read_text(encoding="utf-8"))
        default = _visible(re.search(r'data-hook="hero-paused-reason">(.*?)</p>', module, re.S).group(1))
        self.assertEqual(default, config["reason"])


# ---------------------------------------------------------------------------
# Behavioural half.
# ---------------------------------------------------------------------------

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {};
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:=(?:'([^']*)'|"([^"]*)"))?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const name = m[1]; const val = m[2] !== undefined ? m[2] : m[3];
    return this._all([]).filter((n) => name in n.attrs && (val === undefined || n.attrs[name] === val));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const body = new Elem("body");
globalThis.document = {
  createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t),
  body, referrer: "", addEventListener() {},
  querySelector: (s) => body.querySelector(s), querySelectorAll: (s) => body.querySelectorAll(s),
};
const store = new Map();
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k),
  },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "" },
  history: { replaceState() {} }, addEventListener() {}, dispatchEvent() { return true; },
  crypto: globalThis.crypto,
};

const scenario = JSON.parse(process.env.SCENARIO);
const requested = [];
globalThis.fetch = async (url) => {
  url = String(url).split("?")[0];
  requested.push(url);
  const answer = scenario.routes[url];
  if (!answer || answer.throw) throw new Error("offline");
  return { ok: answer.status < 400, status: answer.status, text: async () => JSON.stringify(answer.body) };
};

const mk = (hook, text, hidden) => {
  const n = new Elem("div"); n.setAttribute("data-hook", hook);
  if (text !== undefined) n.textContent = text;
  if (hidden) n.hidden = true;
  body.appendChild(n); return n;
};
const feature = mk("hero-feature", "", false);          // visible so the test sees it get hidden
const paused = mk("hero-paused", "", true);
const reason = mk("hero-paused-reason", scenario.defaultReason, false);
paused.appendChild(reason);
const scanner = mk("hero-scanner-text", "Example slate", false);
const badge = mk("sample-slate-badge", "Sample slate · demo data", false);
const price = mk("hero-price-block", "", false);
const label = mk("hero-price-label", "", false);
const figure = mk("hero-price-figure", "", false);
for (const h of ["hero-away-name", "hero-home-name", "hero-vs-time", "hero-away-record",
                 "hero-home-record", "hero-away-pitcher", "hero-home-pitcher",
                 "hero-price-needs", "hero-price-needs-wrap", "hero-away-rule", "hero-home-rule"]) mk(h, "", false);

const live = await import("./landing-live.js");
await live.mountLiveHero(document);
const out = {
  requested,
  pausedHidden: paused.hidden, featureHidden: feature.hidden,
  reasonText: body.querySelector('[data-hook="hero-paused-reason"]').textContent,
  scanner: scanner.textContent, figure: figure.textContent, label: label.textContent,
};
console.log("@@" + JSON.stringify(out));
"""

CONFIG = json.loads((ROOT / "config" / "mlb_public_card.json").read_text(encoding="utf-8"))
REASON = CONFIG["reason"]

TODAY = {"games": [{"dossier": {"game": {
    "away_team": "BOS", "home_team": "NYY", "start_time_utc": "2026-10-17T23:05:00Z",
    "away_probable": "Crochet", "home_probable": "Cole"}, "sections": {}}}]}
CARD_WITH_PICK = {"date": "2026-10-16", "frozen": True, "picks": [{
    "away_team": "BOS", "home_team": "NYY", "team": "BOS", "team_name": "Red Sox",
    "market": "moneyline", "price": 120, "books": 9, "market_probability": 0.45,
    "model_probability": 0.48, "first_pitch_utc": "2026-10-17T23:05:00Z"}]}
PAUSED_CARD = {"date": "2026-10-17", "sport": "mlb", "picks": [], "count": 0, "paused": True,
               "paused_after": "2026-10-16", "reason": REASON, "frozen": False,
               "links": [{"label": "SEE A SAMPLE BRIEF", "href": "sample.html"}]}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheHeroModuleWhenThePicksArePaused(unittest.TestCase):
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

    def run_scenario(self, routes, default_reason="DEFAULT"):
        env = dict(os.environ, SCENARIO=json.dumps({"routes": routes, "defaultReason": default_reason}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def test_a_paused_answer_shows_the_reason_and_the_sample_link_and_no_pick(self):
        out = self.run_scenario({
            "/card": {"status": 200, "body": PAUSED_CARD},
            "/today": {"status": 200, "body": TODAY},   # a slate exists: it must not be used
        })
        self.assertFalse(out["pausedHidden"], "the paused panel is not shown")
        self.assertTrue(out["featureHidden"], "a featured game is still showing")
        self.assertEqual(out["reasonText"], REASON, "the server's reason is shown verbatim")
        self.assertEqual(out["figure"], "", "a price was written into the hero")
        self.assertNotIn("/today", out["requested"],
                         "the price board's first game must not stand in for a pick")

    def test_a_paused_answer_with_no_reason_keeps_the_pages_own_words(self):
        card = dict(PAUSED_CARD)
        del card["reason"]
        out = self.run_scenario({"/card": {"status": 200, "body": card}}, default_reason="THE PAGE'S WORDS")
        self.assertFalse(out["pausedHidden"])
        self.assertEqual(out["reasonText"], "THE PAGE'S WORDS")
        self.assertTrue(out["featureHidden"])

    def test_a_blank_reason_does_not_blank_the_panel(self):
        out = self.run_scenario({"/card": {"status": 200, "body": dict(PAUSED_CARD, reason="  ")}},
                                default_reason="THE PAGE'S WORDS")
        self.assertEqual(out["reasonText"], "THE PAGE'S WORDS")

    def test_a_card_that_cannot_be_read_shows_neither_a_pick_nor_the_panel(self):
        for name, routes in (
                ("card refused, no slate", {"/card": {"status": 401, "body": {"detail": "no"}},
                                            "/today": {"throw": True}}),
                ("nothing answers", {}),
                ("card offline, slate empty", {"/card": {"throw": True},
                                               "/today": {"status": 200, "body": {"games": []}}})):
            with self.subTest(case=name):
                out = self.run_scenario(routes)
                self.assertTrue(out["pausedHidden"], "the panel appeared with no paused answer")
                self.assertTrue(out["featureHidden"])
                self.assertEqual(out["figure"], "")

    def test_a_live_card_still_features_its_pick_and_leaves_the_panel_hidden(self):
        out = self.run_scenario({"/card": {"status": 200, "body": CARD_WITH_PICK},
                                 "/today": {"status": 200, "body": TODAY}})
        self.assertTrue(out["pausedHidden"])
        self.assertFalse(out["featureHidden"])
        self.assertEqual(out["figure"], "+120")
        self.assertIn("Red Sox to win", out["label"])


if __name__ == "__main__":
    unittest.main()
