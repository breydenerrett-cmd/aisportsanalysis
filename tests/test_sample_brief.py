"""The public sample brief: GET /sample/brief and web/sample.html.

THE ROUTE (skipped without FastAPI, as on the Linux CI job) serves exactly one game: the one
`config/sample_brief.json` designates, from the PILOT ledger, or `available: false`. The ledger rows
are injected and the config is a temp file: nothing here reads the repo's evidence or calls a model.

THE PAGE half runs the real web/js/sample.js (and analyst.js, dom.js, attribution.js) under node
against a small fake DOM, the pattern of tests/test_analyst_web.py. Skipped when node is missing.
`HARNESS` is shared with tests/test_sample_attribution.py, which pins that the page stores the
outreach link's first touch.
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
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analyst import LABEL, PILOT_LABEL
from src.analyst import ledger, pilot
from tests import analyst_fixtures as F
from tests.test_analyst_pilot import item

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
SAMPLE_JS = (JS / "sample.js").read_text(encoding="utf-8")
SAMPLE_HTML = (ROOT / "web" / "sample.html").read_text(encoding="utf-8")


def publish_pilot_game(root: Path, away="NYY", home="TB") -> None:
    """One pilot row through the real commands, in the temp `root`."""
    it = item()
    adv = it["payload"]["advanced"]
    if (away, home) != ("NYY", "TB"):
        adv["game_id"] = f"{away}-{home}-2026-10-03-1"
        adv["game"].update(away_team=away, home_team=home, game_pk=2)
    out = []
    pilot.prepare(F.DATE, f"{away}@{home}", cfg=F.CFG, root=root, now=lambda: F.NOW, out=out.append,
                  loader=lambda d: [it])
    # the good answer is built from the packet this game's prepare froze
    packet = json.loads((pilot.game_folder(F.DATE, away, home, root) / "packet.json").read_text(encoding="utf-8"))
    answer = F.good_output(packet) if (away, home) == ("NYY", "TB") else only_passes(packet)
    path = root / f"answer_{away}_{home}.json"
    path.write_text(json.dumps(answer), encoding="utf-8")
    # the operator's flow: a check records the attempt, and a publish of an unchecked answer is refused
    pilot.check(str(pilot.game_folder(F.DATE, away, home, root)), str(path), out=out.append, now=lambda: F.NOW)
    code = pilot.publish(str(pilot.game_folder(F.DATE, away, home, root)), str(path), model="claude-sonnet-5-5",
                         cfg=F.CFG, root=root, now=lambda: F.NOW, out=out.append)
    assert code == 0, out


def only_passes(packet) -> dict:
    return {"summary": F.SUMMARY, "calls": [F.pass_call(packet, s["slot_id"]) for s in packet["slots"]]}


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        publish_pilot_game(cls.root, "NYY", "TB")
        publish_pilot_game(cls.root, "BOS", "NYM")
        cls.rows = ledger.rows(pilot.store_paths(cls.root)["store"])
        (cls.root / "config").mkdir()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        from api import analyst as api_analyst
        from api import sample
        self.api, self.sample = api_analyst, sample

    def get(self, config, rows=None):
        path = self.root / "config" / "sample_brief.json"
        if config is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(config if isinstance(config, str) else json.dumps(config), encoding="utf-8")
        with mock.patch.object(self.sample, "repo_root", return_value=self.root), \
                mock.patch.object(self.api, "_pilot_rows", return_value=self.rows if rows is None else rows), \
                mock.patch.object(self.api, "_rows", side_effect=AssertionError("the main ledger was read")):
            return self.sample.get_sample_brief()

    def test_it_serves_the_designated_game_with_its_label_times_and_analysis(self):
        body = self.get({"date": F.DATE, "away": "NYY", "home": "TB"})
        self.assertTrue(body["available"])
        self.assertEqual(body["label"], PILOT_LABEL)
        self.assertEqual(body["first_pitch_utc"], F.FIRST_PITCH)
        self.assertEqual(body["published_utc"], "2026-10-03T18:00:00Z")
        a = body["analysis"]
        self.assertEqual((a["game_id"], a["provenance"]), ("NYY-TB-2026-10-03-1", "session_assisted"))
        self.assertTrue(a["calls"] and a["missing"] is not None)

    def test_it_serves_only_the_designated_game_never_another_the_pilot_holds(self):
        body = self.get({"date": F.DATE, "away": "NYY", "home": "TB"})
        self.assertNotIn("BOS-NYM", json.dumps(body))
        other = self.get({"date": F.DATE, "away": "BOS", "home": "NYM"})
        self.assertEqual(other["analysis"]["game_id"], "BOS-NYM-2026-10-03-1")
        self.assertNotIn("NYY-TB", json.dumps(other))

    def test_the_route_takes_no_parameters_so_no_url_can_pick_a_game(self):
        route = next(r for r in self.sample.public_router.routes if r.path == "/sample/brief")
        self.assertEqual(route.dependant.query_params, [])
        self.assertEqual(route.dependant.path_params, [])
        self.assertEqual(route.methods, {"GET"})

    def test_when_nothing_is_designated_it_is_not_available(self):
        for config in ("null", None, "not json", "[]", {"date": F.DATE}, {"date": "2026-13-45", "away": "NYY", "home": "TB"},
                       {"date": F.DATE, "away": "NYY/..", "home": "TB"}, {"date": 5, "away": "NYY", "home": "TB"}):
            body = self.get(config)
            self.assertFalse(body["available"], config)
            self.assertIsNone(body["analysis"])
            self.assertEqual(body["label"], PILOT_LABEL)
            self.assertTrue(body["reason"])

    def test_a_designated_game_the_pilot_has_not_published_is_not_available(self):
        body = self.get({"date": F.DATE, "away": "LAD", "home": "SD"})
        self.assertFalse(body["available"])
        self.assertIsNone(body["first_pitch_utc"])

    def test_with_an_empty_pilot_ledger_it_is_not_available(self):
        self.assertFalse(self.get({"date": F.DATE, "away": "NYY", "home": "TB"}, rows=[])["available"])

    def test_it_never_reads_the_main_ledger_and_never_calls_the_model(self):
        from src.analyst import analyst as A
        with mock.patch.object(A, "urllib_post", side_effect=AssertionError("network used")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            self.assertTrue(self.get({"date": F.DATE, "away": "NYY", "home": "TB"})["available"])

    def test_a_graded_game_carries_its_results(self):
        graded = list(self.rows)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.jsonl"
            path.write_bytes(Path(pilot.store_paths(self.root)["store"]).read_bytes())
            ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [], now=F.NOW, path=str(path))
            graded = ledger.rows(str(path))
        body = self.get({"date": F.DATE, "away": "NYY", "home": "TB"}, rows=graded)
        self.assertTrue(body["analysis"]["graded"])
        self.assertEqual(body["analysis"]["final"], {"away_score": 5, "home_score": 3})
        self.assertEqual(next(c for c in body["analysis"]["calls"] if c["slot_id"] == "moneyline")["result"], "WIN")

    def test_it_is_public_and_rate_limited_like_the_record(self):
        route = next(r for r in self.sample.public_router.routes if r.path == "/sample/brief")
        self.assertTrue(any(d.dependency is self.sample._rate_limit for d in route.dependencies))
        self.assertEqual(self.sample.PUBLIC_RATE_LIMIT_PER_MIN, self.api.PUBLIC_RATE_LIMIT_PER_MIN)

    def test_it_is_mounted_in_the_app_and_not_behind_the_paid_gate(self):
        # Read off the OpenAPI schema and the mount line: this FastAPI keeps an included router as one
        # opaque entry, so walking `app.routes` finds nothing (tests/test_api_props.py says the same).
        from api import app as app_module
        self.assertIn("/sample/brief", app_module.app.openapi()["paths"])
        mount = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(sample_public_router)\n", mount.replace("\r\n", "\n"))
        self.assertNotRegex(mount, r"sample_public_router[^\n]*dependencies")

    def test_the_shipped_config_is_readable_from_any_working_directory_and_is_valid(self):
        self.assertTrue(self.sample.repo_root().joinpath(self.sample.CONFIG_PATH).is_file())
        shipped = json.loads((ROOT / "config" / "sample_brief.json").read_text(encoding="utf-8"))
        self.assertTrue(shipped is None or set(shipped) == {"date", "away", "home"})

    def test_the_module_imports_no_model_code(self):
        text = (ROOT / "api" / "sample.py").read_text(encoding="utf-8")
        self.assertNotIn("analyze(", text)
        self.assertNotIn("urllib", text)


# ---------------------------------------------------------------------------
# the page, under node
# ---------------------------------------------------------------------------

HARNESS = r"""
class TextNode { constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; } }
class Elem {
  constructor(tag) { this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {}; this.dataset = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
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
process.on("unhandledRejection", () => {});
const body = new Elem("body");
for (const hook of ["app-outlet", "disclaimer-host"]) {
  const node = new Elem("div"); node.setAttribute("data-hook", hook); body.appendChild(node);
}
const listeners = {};
globalThis.document = {
  createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t), body, referrer: scenario.referrer || "",
  addEventListener: (t, f) => { (listeners[t] ||= []).push(f); },
  querySelector: (s) => body.querySelector(s), querySelectorAll: (s) => body.querySelectorAll(s),
};
const store = new Map(Object.entries(scenario.stored || {}));
const storage = {
  getItem: (k) => { if (scenario.brokenStorage) throw new Error("denied"); return store.has(k) ? store.get(k) : null; },
  setItem: (k, v) => { if (scenario.brokenStorage) throw new Error("denied"); store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
};
globalThis.window = {
  localStorage: storage, sessionStorage: storage,
  location: { search: scenario.search || "", host: "linehound.test", pathname: "/web/sample.html", hash: "" },
  history: { replaceState() {} }, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
  scrollTo() {}, crypto: globalThis.crypto,
};
globalThis.location = window.location;
globalThis.localStorage = storage;
globalThis.sessionStorage = storage;
const gets = [];
const posts = [];
globalThis.fetch = async (url, init) => {
  url = String(url);
  if (init && init.method === "POST") posts.push(url); else gets.push(url);
  if (url.startsWith("/sample/brief") && scenario.brief !== undefined) {
    if (scenario.briefFails) return { ok: false, status: 500, text: async () => "boom" };
    return { ok: true, status: 200, text: async () => JSON.stringify(scenario.brief) };
  }
  return { ok: true, status: 200, text: async () => "{}" };
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const out = { crashed: false };
try {
  const mod = await import("./sample.js");
  let root = null;
  if (scenario.kind === "render") {
    root = mod.renderSample(scenario.data);
  } else {
    for (const fn of listeners.DOMContentLoaded || []) fn();
    await new Promise((r) => setTimeout(r, 80));
    root = body.querySelector("[data-hook='app-outlet']");
  }
  const all = root._all([]);
  out.text = text(root);
  out.hooks = all.map((n) => n.attrs["data-hook"]).filter(Boolean);
  out.links = all.filter((n) => n.tagName === "A").map((n) => ({ hook: n.attrs["data-hook"], href: n.attrs.href, text: text(n) }));
  out.labelParagraphs = all.filter((n) => n.attrs["data-hook"] === "analyst-label").map(text);
  out.firstLabelBeforeSummary = out.hooks.indexOf("analyst-label") < out.hooks.indexOf("analyst-summary");
  out.callCount = all.filter((n) => n.attrs["data-hook"] === "analyst-call").length;
  out.caseAgainstCount = all.filter((n) => n.attrs["data-hook"] === "analyst-case-against").length;
  out.results = all.filter((n) => n.attrs["data-hook"] === "analyst-result").map(text);
  out.facts = all.filter((n) => (n.attrs["data-hook"] || "").startsWith("sample-") && n.tagName === "LI").map((n) => [n.attrs["data-hook"], text(n)]);
  out.footerChildren = body.querySelector("[data-hook='disclaimer-host']").childNodes.length;
} catch (err) {
  out.crashed = String(err && err.stack || err);
}
out.gets = gets;
out.posts = posts;
out.stored = Object.fromEntries(store);
console.log("@@" + JSON.stringify(out));
"""

BANNED = (
    (r"\bedge\b", "edge"), (r"\bprofit(?:s|able)?\b", "profit"), (r"\block(?:s|ed|ing)?\b", "lock"),
    (r"\bsharp\b", "sharp"), (r"\bwinning\b", "winning"), (r"\bguarantee[sd]?\b", "guaranteed"),
    (r"(?i)bet[\s-]*check", "Bet Check"), (r"!", "exclamation mark"), (r"(?i)free money", "free money"),
    (r"(?i)\bsure thing\b", "sure thing"), (r"\bROI\b", "ROI"), (r"(?i)\bbeat the (?:book|market)", "beat the books"),
)


def brief(graded=False, *, available=True, **over):
    calls = [
        {"slot_id": "moneyline", "market": "moneyline", "family": "moneyline", "title": "Moneyline",
         "selection": "NYY", "verdict": "TAKE_OTHER_SIDE", "price": 117, "book": "fanduel", "fair_estimate": 0.49,
         "confidence": "medium", "pass_price": 105, "what_would_change_it": "A lineup change.",
         "reasons": [{"claim": "The books make the home side the favourite.", "evidence": []}],
         "case_against": {"claim": "The home starter has the lower ERA.", "evidence": []},
         "verification": {"status": "verified", "problems": []}},
        {"slot_id": "total", "market": "total", "family": "total", "title": "Game total", "selection": "Under 7",
         "verdict": "PASS", "price": -110, "book": "draftkings", "fair_estimate": None, "confidence": "low",
         "pass_price": None, "what_would_change_it": "A price that moves.",
         "reasons": [{"claim": "The books' own number is the best read here.", "evidence": []}],
         "case_against": None, "verification": {"status": "verified", "problems": []}}]
    if graded:
        calls[0]["result"] = "WIN"
        calls[1]["would_have"] = {"result": "LOSS", "price": -110}
    analysis = {"game_id": "NYY-TB-2026-10-03-1", "date": "2026-10-03", "away": "NYY", "home": "TB",
                "published_utc": "2026-10-03T18:00:00Z", "first_pitch_utc": "2026-10-03T22:30:00Z",
                "model": "claude-sonnet-5-5", "version": 1, "provenance": "session_assisted",
                "summary": "First paragraph of the argument.", "summary_status": "ok",
                "missing": [{"item": "lineups", "kind": "absent", "reason": "lineup not posted yet"}],
                "calls": calls, "final": {"away_score": 5, "home_score": 3} if graded else None, "graded": graded}
    data = {"available": available, "label": PILOT_LABEL, "analysis": analysis if available else None,
            "reason": None if available else "There is no sample brief to show right now.",
            "first_pitch_utc": "2026-10-03T22:30:00Z", "published_utc": "2026-10-03T18:00:00Z"}
    data.update(over)
    return data


def string_literals(source: str) -> list:
    code = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
    return [lit[1:-1] for lit in re.findall(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', code)]


def visible_html(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


class StaticChecks(unittest.TestCase):
    def test_no_banned_word_is_in_any_string_the_page_can_show(self):
        offenders = [f"{name}: {lit[:60]!r}" for lit in string_literals(SAMPLE_JS)
                     for pattern, name in BANNED if re.search(pattern, lit)]
        self.assertEqual(offenders, [])

    def test_the_html_has_no_banned_word_and_says_unproven(self):
        shown = visible_html(SAMPLE_HTML) + " ".join(re.findall(r'content="([^"]*)"', SAMPLE_HTML))
        for pattern, name in BANNED:
            self.assertIsNone(re.search(pattern, shown), name)
        self.assertIn("Unproven. Analysis, not advice.", SAMPLE_HTML)

    def test_the_page_is_signed_out_it_mounts_only_the_sample_module_and_the_analyst_styles(self):
        self.assertIn('<script type="module" src="js/sample.js"></script>', SAMPLE_HTML)
        self.assertIn("css/analyst.css", SAMPLE_HTML)
        self.assertNotIn("main.js", SAMPLE_HTML)
        self.assertNotIn("Authorization", SAMPLE_JS)
        self.assertIn('apiGet("/sample/brief")', SAMPLE_JS)
        self.assertNotIn("anthropic", SAMPLE_JS.lower())

    def test_it_never_names_a_game_in_its_request(self):
        self.assertEqual([lit for lit in string_literals(SAMPLE_JS) if "/sample" in lit], ["/sample/brief"])
        self.assertNotIn("encodeURIComponent", SAMPLE_JS)

    def test_the_offer_is_one_line_with_the_terms_the_owner_set(self):
        m = re.search(r'OFFER_LINE =\s*"([^"]+)"\s*\+\s*"([^"]+)"', SAMPLE_JS)
        line = m.group(1) + m.group(2)
        for phrase in ("MLB postseason briefs", "posted before first pitch", "7 days free",
                       "first 20 testers", "hand-picked", "no card", "Not on sale yet",
                       "planned price $19.99 a month", "Analysis, not advice."):
            self.assertIn(phrase, line)

    def test_the_price_matches_the_one_the_landing_page_and_pricing_module_state(self):
        pricing = (JS / "pricing.js").read_text(encoding="utf-8")
        self.assertRegex(pricing, r"19\.99")

    def test_every_html_file_in_web_still_parses_with_the_new_page(self):
        from html.parser import HTMLParser
        HTMLParser().feed(SAMPLE_HTML)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ThePageUnderNode(unittest.TestCase):
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
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        out = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])
        self.assertFalse(out["crashed"], out["crashed"])
        return out

    def render(self, data):
        return self.run_scenario(kind="render", data=data)

    def test_the_label_comes_from_the_server_and_leads_the_analysis(self):
        out = self.render(brief(label="A label the server chose. Unproven. Analysis, not advice."))
        self.assertEqual(out["labelParagraphs"], ["A label the server chose. Unproven. Analysis, not advice."])
        self.assertTrue(out["firstLabelBeforeSummary"])
        out = self.render(brief())
        self.assertEqual(out["labelParagraphs"], [PILOT_LABEL])

    def test_it_says_when_the_brief_was_frozen_and_when_the_game_starts(self):
        out = self.render(brief())
        facts = dict(out["facts"])
        self.assertRegex(facts["sample-frozen"], r"^Frozen at \d{1,2}:\d{2} [AP]M \w+, before the game\.$")
        self.assertRegex(facts["sample-first-pitch"], r"^First pitch \d{1,2}:\d{2} [AP]M \w+\.$")

    def test_ungraded_it_says_the_result_is_to_come_and_shows_none(self):
        out = self.render(brief())
        self.assertIn("Not graded yet", dict(out["facts"])["sample-graded"])
        self.assertEqual(out["results"], [])

    def test_graded_it_shows_the_final_score_and_each_calls_result(self):
        out = self.render(brief(graded=True))
        self.assertIn("Graded. Final: NYY 5, TB 3.", dict(out["facts"])["sample-graded"])
        self.assertEqual(out["results"], ["Won", "The side passed on lost."])

    def test_every_take_shows_its_case_against_and_the_pass_is_as_present_as_the_take(self):
        out = self.render(brief())
        self.assertEqual(out["callCount"], 2)
        self.assertEqual(out["caseAgainstCount"], 1)
        self.assertIn("The case against", out["text"])
        self.assertIn("The home starter has the lower ERA.", out["text"])
        self.assertIn("What the analysis could not use", out["text"])
        self.assertIn("Lineup not posted yet.", out["text"])

    def test_it_links_the_record_the_landing_page_and_signup_with_plain_addresses(self):
        out = self.render(brief())
        links = {l["hook"]: l["href"] for l in out["links"]}
        self.assertEqual(links, {"sample-link-record": "index.html#/record-card",
                                 "sample-link-landing": "landing.html",
                                 "sample-link-signup": "index.html#/signup"})
        for href in links.values():
            self.assertNotIn("utm_", href)         # the stored first touch rides along, not the URL

    def test_it_states_the_offer_in_one_line(self):
        out = self.render(brief())
        self.assertIn("The first 20 testers are hand-picked: 7 days free, no card. "
                      "Not on sale yet; planned price $19.99 a month. Analysis, not advice.", out["text"])
        self.assertEqual(out["hooks"].count("sample-offer"), 1)

    def test_no_brief_says_so_and_keeps_the_links_and_the_offer(self):
        out = self.render(brief(available=False))
        self.assertIn("There is no sample brief to show right now.", out["text"])
        self.assertEqual(out["callCount"], 0)
        self.assertNotIn("sample-facts", out["hooks"])
        self.assertEqual(len(out["links"]), 3)
        self.assertIn("sample-offer", out["hooks"])

    def test_the_page_makes_no_claim_about_results_money_or_the_analysts_skill(self):
        for data in (brief(), brief(graded=True), brief(available=False)):
            text = self.render(data)["text"]
            for pattern, name in BANNED:
                self.assertIsNone(re.search(pattern, text), name)

    def test_loading_fetches_the_one_route_and_draws_the_brief_and_the_footer(self):
        out = self.run_scenario(kind="load", brief=brief())
        self.assertEqual([g for g in out["gets"] if g != "/meta"], ["/sample/brief"])   # /meta is the footer's
        self.assertEqual(out["callCount"], 2)
        self.assertGreater(out["footerChildren"], 0)

    def test_a_failed_fetch_leaves_a_page_that_says_there_is_no_sample(self):
        out = self.run_scenario(kind="load", brief={}, briefFails=True)
        self.assertIn("There is no sample brief to show right now.", out["text"])
        self.assertEqual(len(out["links"]), 3)


if __name__ == "__main__":
    unittest.main()
