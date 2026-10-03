"""The landing page tells a stranger what is free, what is for subscribers,
what is proven and what is not, and shows one real graded card.

Written 2026-10-01. A stranger could not tell what $19.99 buys that the free
record does not already show: the pricing card said "Every pick, every sport,
the full record" while the full graded record is public (api/card.py's
public_router). This file pins the three blocks that fix that, in two halves:

  * static checks on web/landing.html and web/js/landing.js -- the two columns
    and their hooks, the position right under the hero, the banned words, no
    typed record figure or trial wording, "Bet Check" absent (owner ruling,
    2026-09-22), the sample block hidden by default, and each "you get" line
    tied to a route that really is public or really is behind the paywall
    (read from api/app.py as TEXT, so nothing here needs FastAPI);
  * a behavioural half that runs the real web/js/landing.js under node against
    a small fake DOM (the pattern of tests/test_checkout_copy_states.py), with
    a fake GET /card/history payload holding a pick, a fill, a void, a heavy
    favourite and a withdrawn entry, and a failed fetch that must render
    nothing. Skipped when node is not installed.
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
APP_PY = (ROOT / "api" / "app.py").read_text(encoding="utf-8")

# The words the owner's brief bans from the new copy. "edge" is only allowed in
# a sentence that already existed (the FAQ's "No betting edge found yet"), which
# is outside the blocks scanned here.
BANNED = (
    (r"\bedge\b", "edge"),
    (r"\bprofit(?:s|able)?\b", "profit"),
    (r"\block(?:s|ed|ing)?\b", "lock"),
    (r"\bsharp\b", "sharp"),
    (r"\bwinning\b", "winning"),
    (r"\bguarantee[sd]?\b", "guaranteed"),
    (r"\bbeat the books?\b", "beat the book"),
    (r"\bsystems?\b", "system"),
    (r"\bexperts?\b", "expert"),
    (r"!", "exclamation mark"),
)
TRIAL_RE = re.compile(r"trial|\d+-day|cancel anytime|cancel before", re.I)


def _section(hook: str) -> str:
    """The whole <section ... data-hook="hook" ...> ... </section> element."""
    match = re.search(
        r'<section\b[^>]*data-hook="%s"[^>]*>.*?</section>' % re.escape(hook),
        HTML, flags=re.S)
    assert match, f"no <section data-hook={hook!r}> in landing.html"
    return match.group(0)


def _visible(fragment: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _string_literals(source: str) -> list:
    """Every string and template literal in `source` with comments removed --
    the copy a renderer can put on screen, without the identifiers around it."""
    code = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
    literals = re.findall(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', code)
    return [lit[1:-1] for lit in literals]


NEW_JS = LANDING_JS.split("WHAT IS PROVEN AND WHAT IS NOT; THE FREE SAMPLE")[1].split("\nfunction boot()")[0]


class TheWhatYouGetColumns(unittest.TestCase):
    def test_both_columns_exist_with_their_hooks(self):
        block = _section("what-you-get")
        self.assertIn('data-hook="wyg-free"', block)
        self.assertIn('data-hook="wyg-subscribers"', block)
        self.assertIn("Free, no account", block)
        self.assertIn("Subscribers", block)

    def test_it_sits_directly_after_the_hero_record_block(self):
        hero_end = HTML.index("</section>", HTML.index('data-hook="hero"')) + len("</section>")
        opening = HTML.rfind("<section", 0, HTML.index('data-hook="what-you-get"'))
        between = re.sub(r"<!--.*?-->", "", HTML[hero_end:opening], flags=re.S)
        self.assertNotIn("<section", between,
                         "another section sits between the hero and 'What you get'")
        self.assertEqual(between.strip(), "", "markup sits between the hero and 'What you get'")
        self.assertLess(HTML.index('data-hook="what-you-get"'), HTML.index('id="how-it-works"'))

    def test_free_column_names_the_record_and_the_postseason_page(self):
        free = HTML.split('data-hook="wyg-free"')[1].split('data-hook="wyg-subscribers"')[0]
        self.assertIn('data-hook="wyg-free-record"', free)
        self.assertIn('data-hook="wyg-free-postseason"', free)
        self.assertIn('href="index.html#/record-card"', free)
        self.assertIn('href="postseason.html"', free)
        self.assertTrue((WEB / "postseason.html").is_file())

    def test_subscriber_column_names_each_paid_view_and_nothing_else(self):
        subs = HTML.split('data-hook="wyg-subscribers"')[1].split("</section>")[0]
        hooks = re.findall(r'<li data-hook="(wyg-sub-[a-z]+)"', subs)
        self.assertEqual(hooks, ["wyg-sub-card", "wyg-sub-matchups", "wyg-sub-odds",
                                 "wyg-sub-props", "wyg-sub-tennis"])

    def test_nothing_in_the_new_blocks_names_bet_check(self):
        for hook in ("what-you-get", "proven-block", "last-card"):
            block = _section(hook)
            self.assertNotRegex(block, r"(?i)bet[\s-]*check", hook)
            self.assertNotIn("betcheck", block.lower(), hook)
        for literal in _string_literals(NEW_JS):
            self.assertNotRegex(literal, r"(?i)bet[\s-]*check")


class EachYouGetLineIsTiedToARealRoute(unittest.TestCase):
    """Read as text from api/app.py, so this runs where FastAPI is absent."""

    def _mounts(self):
        mounts = {}
        for match in re.finditer(r"app\.include_router\((\w+)(?:,\s*dependencies=(\w+))?\)", APP_PY):
            mounts[match.group(1)] = match.group(2)
        return mounts

    def test_the_paid_views_are_behind_the_paid_group(self):
        mounts = self._mounts()
        for router in ("card_router", "games_router", "odds_router", "props_router", "tennis_router"):
            self.assertEqual(mounts.get(router), "_authed_paid", router)

    def test_the_free_surfaces_are_mounted_with_no_gate(self):
        mounts = self._mounts()
        for router in ("card_public_router", "postseason_router", "meta_router"):
            self.assertIn(router, mounts)
            self.assertIsNone(mounts[router], f"{router} must carry no auth dependency")

    def test_the_public_card_router_serves_record_history_and_accounts_only(self):
        card_py = (ROOT / "api" / "card.py").read_text(encoding="utf-8")
        public = re.findall(r'@public_router\.get\("([^"]+)"', card_py)
        # "/card/accounts" (example accounts, 2026-10-03) is settled-day
        # arithmetic over the public record, so it is public like the record.
        self.assertEqual(sorted(public), ["/card/accounts", "/card/history", "/card/record"])
        paid = re.findall(r'@router\.get\("([^"]+)"', card_py)
        self.assertEqual(sorted(paid), ["/card", "/card/{date}"])

    def test_the_paid_views_are_in_the_app_navigation(self):
        sport_js = (JS / "sport.js").read_text(encoding="utf-8")
        main_js = (JS / "main.js").read_text(encoding="utf-8")
        for label in ('label: "GAMEDAY"', 'label: "MATCHUPS"', 'label: "PROPS"', 'label: "BOARD"'):
            self.assertIn(label, sport_js)
        self.assertIn('route === "odds"', main_js)
        self.assertIn('"#/postseason"', main_js)
        self.assertIn('"#/record-card"', main_js)


class TheProvenBlock(unittest.TestCase):
    def test_five_short_lines_with_their_hooks(self):
        block = _section("proven-block")
        for hook in ("proven-published", "proven-graded", "proven-record",
                     "proven-research", "proven-postseason"):
            self.assertIn(f'data-hook="{hook}"', block)
            self.assertIn(f'data-hook="{hook}-text"', block)
        self.assertEqual(block.count("<li "), 5)

    def test_the_static_sentences_carry_no_figure(self):
        block = _visible(_section("proven-block"))
        self.assertNotRegex(block, r"\d", f"a figure in the no-JS wording goes stale: {block!r}")

    def test_the_static_record_line_does_not_imply_the_picks_make_money(self):
        block = _section("proven-block")
        line = re.search(r'data-hook="proven-record-text">([^<]*)<', block).group(1)
        self.assertIn("has not shown that the picks make money", line)

    def test_numbers_come_from_meta_not_the_markup(self):
        self.assertIn("meta.research", NEW_JS)
        self.assertIn("effective_record", NEW_JS)
        self.assertIn("fillProvenBlock();", LANDING_JS)


class TheSampleBlockIsHiddenUntilItHasSomethingToShow(unittest.TestCase):
    def test_the_section_is_hidden_by_default_and_empty(self):
        block = _section("last-card")
        self.assertRegex(block.split(">")[0], r"\bhidden\b")
        self.assertNotIn("<li", block)
        self.assertNotRegex(_visible(block).replace("Last night's card", ""), r"\d")

    def test_the_heading_is_the_one_the_brief_asks_for(self):
        self.assertIn("Last night's card, as published, with what happened",
                      _section("last-card"))

    def test_it_reads_the_public_history_route_with_no_token_wording(self):
        self.assertIn('apiGet("/card/history?limit=1")', LANDING_JS)
        self.assertIn("fillLastCard();", LANDING_JS)

    def test_a_failed_fetch_hides_the_section_and_never_fills_it(self):
        body = LANDING_JS.split("async function fillLastCard(")[1].split("\nfunction ")[0]
        self.assertIn("section.hidden = true", body)


class TheCopyIsPlainAndCautious(unittest.TestCase):
    NEW_HTML_BLOCKS = ("what-you-get", "proven-block", "last-card")

    def test_no_banned_word_in_the_new_html_blocks(self):
        for hook in self.NEW_HTML_BLOCKS:
            text = _visible(_section(hook))
            for pattern, label in BANNED:
                self.assertIsNone(re.search(pattern, text, re.I), f"{label!r} in {hook}: {text[:80]!r}")

    def test_no_banned_word_in_the_hero_sub_line_or_the_pricing_list(self):
        claim = re.search(r'<p class="hero__claim-body">(.*?)</p>', HTML, re.S).group(1)
        includes = re.search(r'<li data-hook="pricing-includes">(.*?)</li>', HTML, re.S).group(1)
        for text in (claim, includes):
            for pattern, label in BANNED:
                self.assertIsNone(re.search(pattern, text, re.I), f"{label!r} in {text!r}")

    def test_no_banned_word_in_the_new_javascript_strings(self):
        for literal in _string_literals(NEW_JS):
            for pattern, label in BANNED:
                self.assertIsNone(re.search(pattern, literal, re.I), f"{label!r} in {literal!r}")

    def test_no_typed_record_figure_or_trial_wording_in_the_new_blocks(self):
        for hook in ("what-you-get", "proven-block"):
            text = _visible(_section(hook))
            self.assertNotRegex(text, r"\d", hook)
            self.assertIsNone(TRIAL_RE.search(text), (hook, text))
        self.assertIsNone(TRIAL_RE.search(
            re.search(r'<li data-hook="pricing-includes">(.*?)</li>', HTML, re.S).group(1)))
        claim = re.search(r'<p class="hero__claim-body">(.*?)</p>', HTML, re.S).group(1)
        self.assertNotRegex(claim, r"\d")
        self.assertIsNone(TRIAL_RE.search(claim))

    def test_no_units_or_won_lost_figure_is_typed_anywhere_new(self):
        page = _visible(HTML)
        self.assertIsNone(re.search(r"[+\-−]\d+\.\d{2}\s*units", page))
        for hook in ("what-you-get", "proven-block", "last-card"):
            self.assertIsNone(re.search(r"(?<![\d-])\d{1,3}\s*[-–]\s*\d{1,3}(?![\d-])", _visible(_section(hook))))

    def test_the_pricing_card_lists_the_subscriber_items_not_the_old_line(self):
        self.assertNotIn("Every pick, every sport, the full record", HTML)
        includes = re.search(r'<li data-hook="pricing-includes">(.*?)</li>', HTML, re.S).group(1)
        for word in ("Matchups", "Odds", "Props", "Tennis"):
            self.assertIn(word, includes)
        self.assertIn("graded record stays free", includes)
        # The checkout-state behaviour is untouched: every CTA still carries
        # the hook applyCheckoutCopy reads, with the cautious wording.
        for cta in re.findall(r"<a[^>]*data-checkout-cta[^>]*>(.*?)</a>", HTML, re.S):
            self.assertEqual(cta.strip(), "Request early access")

    def test_the_hero_lede_says_what_a_card_is_and_the_grading_schedule_lives_lower(self):
        # 2026-10-02 (docs/CONVERSION_REVIEW_2026-10-02.md change 1): the lede
        # says what a card holds; the by-hand UFC grading fact is no longer in
        # the hero but must still be on the page, in the FAQ and the sport tiles.
        claim = re.search(r'<p class="hero__claim-body">(.*?)</p>', HTML, re.S).group(1)
        self.assertEqual(
            claim.strip(),
            "A short card each night: the bet, the best price and where to find it, and why. "
            "Every card is graded in public afterwards, wins and losses.")
        self.assertNotIn("entered by hand", claim)
        faq = re.sub(r"\s+", " ", _section("faq"))
        self.assertIn("MLB and NFL grade automatically the next morning; "
                      "UFC picks grade once results are entered by hand.", faq)


class TheCssAddsOnlyWhatTheBlocksNeed(unittest.TestCase):
    def test_the_two_columns_cannot_force_a_sideways_scroll(self):
        css = (WEB / "css" / "landing.css").read_text(encoding="utf-8")
        self.assertIn("minmax(min(100%, 300px), 1fr)", css)
        self.assertIn(".lc-row {", css)
        self.assertIn("overflow-wrap: anywhere", css)


# ---------------------------------------------------------------------------
# Behavioural half -- the real landing.js under node.
# ---------------------------------------------------------------------------

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.isRoot = false; this.style = {};
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
const calls = [];
globalThis.fetch = async (url) => {
  url = String(url);
  calls.push(url);
  if (url.startsWith("/card/history")) {
    if (scenario.history.throw) throw new Error("offline");
    const { status, body: payload } = scenario.history;
    return { ok: status < 400, status, text: async () => JSON.stringify(payload) };
  }
  return { ok: true, status: 200, text: async () => "{}" };
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const mk = (tag, hook, hidden) => {
  const node = new Elem(tag); node.setAttribute("data-hook", hook);
  if (hidden) node.hidden = true; return node;
};
const section = mk("section", "last-card", true);
const title = mk("h2", "last-card-title"); title.textContent = "Last night's card, as published, with what happened";
const date = mk("p", "last-card-date");
const content = mk("div", "last-card-body");
section.appendChild(title); section.appendChild(date); section.appendChild(content);
body.appendChild(section);

const landing = await import("./landing.js");
const out = { calls };
if (scenario.kind === "fill") {
  await landing.fillLastCard();
} else if (scenario.kind === "render") {
  out.returned = landing.renderLastCard(section, scenario.payload, new Date(scenario.now));
} else if (scenario.kind === "pure") {
  out.record = scenario.cohorts.map((c) => landing.provenRecordSentence(c));
  out.research = scenario.research.map((r) => landing.researchSentence(r));
}
out.hidden = section.hidden;
out.title = title.textContent;
out.date = date.textContent;
out.body = text(content);
out.rows = section.querySelectorAll("[data-hook='last-card-row']").map((r) => ({
  kind: r.attrs["data-kind"], result: r.attrs["data-result"], text: text(r),
}));
out.hooks = section._all([]).map((n) => n.attrs["data-hook"]).filter(Boolean);
console.log("@@" + JSON.stringify(out));
"""

NOW = "2026-10-01T15:00:00Z"   # so "yesterday" in Eastern is 2026-09-30


def _entry(**fields):
    base = {"entry_class": "pick", "kind": "game", "market": "moneyline", "withdrawn": False,
            "book": None, "books": 11, "line": None, "player": None, "side": None,
            "away_team": None, "home_team": None, "away_score": None, "home_score": None,
            "reason": None, "bet": None, "game_type": "R"}
    base.update(fields)
    return base


def _v2_payload(date="2026-09-30", extra=()):
    graded = [
        # a pick that won
        _entry(team_name="Yankees", side="home", price=-135, result="WIN", profit_units=0.7407,
               away_team="BOS", home_team="NYY", away_score=2, home_score=9),
        # a fill that lost
        _entry(entry_class="fill", kind="prop", market="batter_hits", player="Michael Busch",
               side="Over", line=0.5, price=-130, books=4, result="LOSS", profit_units=-1.0),
        # a void pick
        _entry(kind="prop", market="batter_runs_scored", player="Ethan Salas", side="Over",
               line=0.5, price=110, books=4, result="VOID", profit_units=None,
               reason="game postponed"),
        # retired-rule heavy favourite: must never be shown
        _entry(team_name="Dodgers", price=-210, result="WIN", profit_units=0.4762),
        # withdrawn before the game: not shown, not counted
        _entry(kind="prop", market="batter_hits", player="Withdrawn Guy", side="Over", line=0.5,
               price=120, result="WIN", profit_units=1.2, withdrawn=True),
    ]
    graded.extend(extra)
    return {"days": [{"date": date, "rule": "DAILY_CARD_BEST_BETS_V2", "graded": graded,
                      "wins": 1, "losses": 1}], "total_days": 1, "truncated": False,
            "pending_days": [], "withheld_days": 0}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheSampleRendersUnderNode(unittest.TestCase):
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

    # ---- a pick, a fill and a void, labelled correctly --------------------

    def test_a_pick_a_fill_and_a_void_are_each_labelled_correctly(self):
        out = self.run_scenario(kind="render", payload=_v2_payload(), now=NOW)
        self.assertTrue(out["returned"])
        self.assertFalse(out["hidden"])
        self.assertEqual(out["title"], "Last night's card, as published, with what happened")
        self.assertIn("Wednesday, Sep 30, 2026", out["date"])

        by_bet = {row["text"].split("\n")[0]: row for row in out["rows"]}
        self.assertEqual(sorted(by_bet), ["Ethan Salas over 0.5 runs scored",
                                          "Michael Busch over 0.5 hits", "Yankees to win"])

        pick = by_bet["Yankees to win"]
        self.assertEqual((pick["kind"], pick["result"]), ("pick", "WIN"))
        self.assertIn("Won", pick["text"])
        self.assertIn("+0.74 units", pick["text"])
        self.assertIn("-135", pick["text"])
        self.assertIn("best of 11 books", pick["text"])
        self.assertIn("BOS 2, NYY 9", pick["text"])
        self.assertNotIn("Fill", pick["text"])

        fill = by_bet["Michael Busch over 0.5 hits"]
        self.assertEqual((fill["kind"], fill["result"]), ("fill", "LOSS"))
        self.assertIn("Fill, not a pick", fill["text"])
        self.assertIn("Lost", fill["text"])
        self.assertIn("−1.00 units", fill["text"])

        void = by_bet["Ethan Salas over 0.5 runs scored"]
        self.assertEqual((void["kind"], void["result"]), ("pick", "VOID"))
        self.assertIn("Void", void["text"])
        self.assertIn("game postponed", void["text"])
        self.assertNotIn("units", void["text"])
        self.assertNotIn("Won", void["text"])

        # Fills sit under their own heading, apart from the picks.
        self.assertIn("last-card-picks", out["hooks"])
        self.assertIn("last-card-fills", out["hooks"])
        self.assertIn("Fills, not picks", out["body"])
        self.assertIn("not counted in the record", out["body"])

    def test_picks_and_fills_are_summed_apart(self):
        out = self.run_scenario(kind="render", payload=_v2_payload(), now=NOW)
        lines = out["body"].split("\n")
        self.assertIn("1 won, 0 lost, 1 void, net +0.74 units", lines)
        self.assertIn("0 won, 1 lost", lines)

    def test_a_heavy_favourite_and_a_withdrawn_entry_are_never_shown(self):
        out = self.run_scenario(kind="render", payload=_v2_payload(), now=NOW)
        for forbidden in ("Dodgers", "-210", "Withdrawn Guy"):
            self.assertNotIn(forbidden, out["body"])
        self.assertIn("1 entry priced at -200 or shorter is not shown here.", out["body"])
        self.assertIn("1 entry was withdrawn before the game and is not shown or counted.", out["body"])

    def test_a_day_of_fills_only_says_so_and_calls_nothing_a_pick(self):
        payload = _v2_payload()
        payload["days"][0]["graded"] = [
            _entry(entry_class="fill", team_name="Padres", price=-134, result="WIN", profit_units=0.7463)]
        out = self.run_scenario(kind="render", payload=payload, now=NOW)
        self.assertTrue(out["returned"])
        self.assertIn("No pick passed every check that night, so the card listed fills only.", out["body"])
        self.assertNotIn("last-card-picks", out["hooks"])
        self.assertEqual([row["kind"] for row in out["rows"]], ["fill"])

    def test_an_older_card_is_not_called_last_night(self):
        out = self.run_scenario(kind="render", payload=_v2_payload(date="2026-09-27"), now=NOW)
        self.assertTrue(out["returned"])
        self.assertTrue(out["title"].startswith("The most recent graded card"))
        self.assertIn("Sunday, Sep 27, 2026", out["date"])

    def test_the_older_rule_shape_uses_the_servers_own_bet_and_book(self):
        payload = {"days": [{"date": "2026-09-30", "wins": 1, "losses": 0, "picks": [
            {"bet": "Take Cubs to win at -150", "price": -150, "book": "draftkings", "books": 9,
             "result": "WIN", "profit_units": 0.6667, "away_team": "CHC", "home_team": "SD",
             "away_score": 4, "home_score": 1},
            {"bet": "Take Padres to win at -240", "price": -240, "book": "fanduel", "books": 9,
             "result": "LOSS", "profit_units": -1.0},
        ]}]}
        out = self.run_scenario(kind="render", payload=payload, now=NOW)
        self.assertTrue(out["returned"])
        self.assertEqual(len(out["rows"]), 1)
        self.assertIn("Take Cubs to win at -150", out["rows"][0]["text"])
        self.assertNotIn("Padres", out["body"])

    # ---- nothing to show means nothing is shown ----------------------------

    def test_a_failed_fetch_renders_nothing(self):
        out = self.run_scenario(kind="fill", history={"throw": True})
        self.assertEqual(out["calls"], ["/card/history?limit=1"])
        self.assertTrue(out["hidden"])
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["body"], "")
        self.assertEqual(out["date"], "")

    def test_a_server_error_renders_nothing(self):
        out = self.run_scenario(kind="fill", history={"status": 500, "body": {"detail": "boom"}})
        self.assertTrue(out["hidden"])
        self.assertEqual(out["body"], "")

    def test_no_settled_day_renders_nothing(self):
        for payload in ({"days": [], "total_days": 0}, {}, None, {"days": [{"date": "2026-09-30", "graded": []}]}):
            with self.subTest(payload=payload):
                out = self.run_scenario(kind="fill", history={"status": 200, "body": payload})
                self.assertTrue(out["hidden"])
                self.assertEqual(out["rows"], [])
                self.assertEqual(out["body"], "")

    def test_an_entry_it_cannot_show_honestly_hides_the_whole_block(self):
        unresolved = _v2_payload(extra=[_entry(team_name="Mets", price=-120, result="UNRESOLVED")])
        nameless = _v2_payload(extra=[_entry(price=-120, result="WIN", profit_units=0.8)])
        priceless = _v2_payload(extra=[_entry(team_name="Mets", price=None, result="WIN", profit_units=0.8)])
        for name, payload in (("unresolved", unresolved), ("nameless", nameless), ("priceless", priceless)):
            with self.subTest(case=name):
                out = self.run_scenario(kind="render", payload=payload, now=NOW)
                self.assertFalse(out["returned"])
                self.assertTrue(out["hidden"])
                self.assertEqual(out["body"], "")

    def test_a_good_fetch_fills_and_shows_the_block(self):
        out = self.run_scenario(kind="fill", history={"status": 200, "body": _v2_payload()})
        self.assertEqual(out["calls"], ["/card/history?limit=1"])
        self.assertFalse(out["hidden"])
        self.assertEqual(len(out["rows"]), 3)

    # ---- the two /meta sentences -------------------------------------------

    def test_the_record_and_research_sentences_say_what_meta_says(self):
        graded = {"available": True, "grading_state": "graded", "wins": 16, "losses": 17,
                  "pushes": 0, "profit_units": -5.05, "days": 5}
        winning = dict(graded, wins=20, losses=13, profit_units=3.1)
        ungraded = {"available": True, "grading_state": "published", "reason": "nothing graded"}
        out = self.run_scenario(
            kind="pure", cohorts=[graded, winning, ungraded, None],
            research=[{"read": 37, "surviving": 0}, {"read": 37, "surviving": 2},
                      {"read": None, "surviving": 0}, None])
        negative, positive, absent, none = out["record"]
        self.assertEqual(negative,
                         "The record so far is negative for the current method: 16–17, −5.05 units over 5 nights graded.")
        self.assertIn("20–13, +3.10 units over 5 nights graded", positive)
        self.assertIn("not evidence that the picks make money", positive)
        self.assertNotIn("negative", positive)
        self.assertIsNone(absent)
        self.assertIsNone(none)
        self.assertEqual(out["research"][0], "No research idea has survived testing: 37 tested, none survived.")
        self.assertEqual(out["research"][1], "2 of 37 research ideas tested have survived our checks.")
        self.assertIsNone(out["research"][2])
        self.assertIsNone(out["research"][3])


if __name__ == "__main__":
    unittest.main()
