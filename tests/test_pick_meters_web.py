"""The pick meters as a person sees them: two half-dial gauges on a ticket, built from the server's ``grades`` block only.

What is pinned (web/js/pick-meters.js, web/css/pick-meters.css, the mounts in web/js/hounds-tickets.js):

  * ARIA. Each dial is a ``role="meter"`` with min 0, max 100, the server's score as ``aria-valuenow`` and the server's word as
    ``aria-valuetext``. A dial with no reading is a ``role="img"`` that says so, and has no needle: "not yet available" is
    never a needle parked at 0.
  * THE CLIENT COMPUTES NOTHING. Every number and sentence on screen is in the payload; the zone colours mirror the server's
    thresholds, and a test pins that the two tables agree.
  * MOTION. The sweep is armed ONLY when the viewer has not asked for reduced motion; everyone else gets the needle at rest.
  * THE STYLESHEET is linked once, by the module, so no HTML file has to list it.
  * THE MOUNTS. A ticket that carries ``grades`` shows the dials on its card and the reasons in the "Why this bet" fold; a
    ticket from a feed that carries none shows nothing new.

The page runs the real modules under node against a small fake DOM; skipped when node is not installed. The browser's layout is
not run here (the screenshot is docs/audit/2026-10-29/pick-meters-400.jpg).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.hounds import pick_grades as pg
from tests.hounds_web_runner import HAS_NODE, WEB, run_js

CSS = (WEB / "css" / "pick-meters.css").read_text(encoding="utf-8")

# A fake document rich enough for hounds-core's h() and s(): elements keep attributes, children and listeners, can be found by
# class / tag / [attr], and the document has a <head> that records what is appended to it. Timers run when the test says so.
SHIM = r"""
class El {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; this.listeners = {}; this.style = {}; this.parent = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(c) { if (c.parent) c.parent.kids.splice(c.parent.kids.indexOf(c), 1); c.parent = this; this.kids.push(c); return c; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  fire(t) { for (const f of this.listeners[t] || []) f({ type: t, target: this }); }
  set textContent(v) { this.kids = [{ tag: "#text", text: String(v), kids: [] }]; }
  get textContent() { return this.kids.map((k) => (k.tag === "#text" ? k.text : k.textContent)).join(""); }
  get children() { return this.kids.filter((k) => k.tag !== "#text"); }
  all(out = []) { for (const k of this.children) { out.push(k); k.all(out); } return out; }
  matches(sel) {
    const m = /^([a-z]*)((?:\.[\w-]+)*)(?:\[([\w-]+)(?:="([^"]*)")?\])?$/.exec(sel);
    if (!m) throw new Error("selector " + sel);
    if (m[1] && this.tag !== m[1]) return false;
    const cls = (this.attrs.class || "").split(/\s+/);
    if (!m[2].split(".").filter(Boolean).every((c) => cls.includes(c))) return false;
    if (m[3] && !(m[3] in this.attrs)) return false;
    if (m[3] && m[4] !== undefined && this.attrs[m[3]] !== m[4]) return false;
    return true;
  }
  querySelectorAll(sel) { return this.all().filter((n) => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const head = new El("head");
const timers = [];
globalThis.setTimeout = (fn) => { timers.push(fn); return timers.length; };
const flush = () => { while (timers.length) timers.shift()(); };
globalThis.document = {
  head, createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), createTextNode: (t) => ({ tag: "#text", text: String(t), kids: [] }),
  querySelector: (sel) => (sel === "head" ? head : head.querySelector(sel)),
};
const motion = (allowed) => { globalThis.window = { matchMedia: (q) => ({ matches: allowed && /no-preference/.test(q) }) }; };
const first = (n, sel) => n.querySelector(sel);
const hooks = (n, hook) => n.querySelectorAll(`[data-hook="${hook}"]`);
"""

GRADES = {
    "value": {"score": 66, "label": "Value", "slice": {"name": "NHL totals, near even, favourite", "n": 23, "w": 16, "l": 7,
                                                         "expected_w": 12.0},
              "shrunk_rate": 0.5559, "implied": 0.5238,
              "reason": "Its NHL totals, near even, favourite: 16-7. -110 implies 52%; its record shrinks to 55%."},
    "confidence": {"score": 41, "label": "Medium", "parts": {"sample": 53, "consistency": 83, "market": 83},
                   "reason": "Built on 23 similar bets; its record in them is ahead of the prices; 8 books quoted it. Not a win chance."},
    "clv": {"pts": 1.3, "label": "Beat the close"},
}
UNAVAILABLE = {
    "value": {"score": None, "label": "Not yet available", "slice": None, "shrunk_rate": None, "implied": 0.5238,
              "reason": "No settled bets like this before it was placed."},
    "confidence": {"score": None, "label": "Not yet available", "parts": None,
                   "reason": "No settled bets like this before it was placed."},
    "clv": None,
}


def run(body: str):
    return run_js('import * as P from "./pick-meters.js";\nimport * as T from "./hounds-tickets.js";\n'
                  + SHIM + body, viewer=None)


def js(**values):
    return "".join(f"const {k} = {json.dumps(v)};\n" for k, v in values.items())


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheDialsCarryTheServersNumbers(unittest.TestCase):
    def setUp(self):
        self.out = run(js(G=GRADES) + """
motion(false);
const root = P.renderPickMeters(G, { compact: false });
const meters = root.querySelectorAll('[role="meter"]').map((m) => ({ ...m.attrs }));
console.log(JSON.stringify({ meters, text: root.textContent,
  needles: root.querySelectorAll(".pm__needle").map((n) => n.attrs.style),
  cls: root.attrs.class, hooks: [...new Set(root.all().map((n) => n.attrs["data-hook"]).filter(Boolean))] }));
""")

    def test_each_dial_is_a_meter_with_the_servers_score_and_word(self):
        by_label = {m["aria-label"]: m for m in self.out["meters"]}
        self.assertEqual(set(by_label), {"Confidence", "Value"})
        self.assertEqual((by_label["Value"]["aria-valuemin"], by_label["Value"]["aria-valuemax"]), ("0", "100"))
        self.assertEqual((by_label["Value"]["aria-valuenow"], by_label["Value"]["aria-valuetext"]), ("66", "Value"))
        self.assertEqual((by_label["Confidence"]["aria-valuenow"], by_label["Confidence"]["aria-valuetext"]), ("41", "Medium"))

    def test_the_needle_points_where_the_score_is(self):
        # confidence 41 is left of centre, value 66 right of it (0 is the far left, -90deg; 100 the far right, +90deg)
        angles = sorted(float(re.search(r"(-?[\d.]+)deg", s).group(1)) for s in self.out["needles"])
        self.assertEqual(angles, [-16.2, 28.8])

    def test_the_numbers_and_words_on_screen_are_the_servers(self):
        for word in ("41", "Medium", "66", "Value", "Confidence", "Beat the close +1.3 pts"):
            self.assertIn(word, self.out["text"])

    def test_the_sentences_behind_the_scores_and_the_note_are_there(self):
        self.assertIn(GRADES["value"]["reason"], self.out["text"])
        self.assertIn(GRADES["confidence"]["reason"], self.out["text"])
        self.assertIn("Not a promise. Paper bets only.", self.out["text"])
        self.assertIn("Not a win chance.", self.out["text"])

    def test_the_full_size_names_the_ends_of_each_scale(self):
        for word in ("Overpriced", "Fair", "Low", "High"):
            self.assertIn(word, self.out["text"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheCompactForm(unittest.TestCase):
    def test_dials_and_readings_only_with_the_one_line_note(self):
        out = run(js(G=GRADES) + """
motion(false);
const root = P.renderPickMeters(G, { compact: true });
console.log(JSON.stringify({ text: root.textContent, reasons: root.querySelectorAll(".pm__reason").length,
  meters: root.querySelectorAll('[role="meter"]').length, clv: hooks(root, "meter-clv").length,
  note: hooks(root, "meter-note").map((n) => n.textContent) }));
""")
        self.assertEqual((out["reasons"], out["meters"], out["clv"]), (0, 2, 0))
        self.assertEqual(len(out["note"]), 1)
        self.assertIn("Not a promise. Paper bets only.", out["note"][0])
        self.assertIn("Confidence is not a win chance.", out["note"][0])

    def test_the_fold_form_has_the_sentences_and_no_second_set_of_dials_or_notes(self):
        out = run(js(G=GRADES) + """
motion(false);
const root = P.renderPickMeters(G, { compact: false, dials: false, note: false });
console.log(JSON.stringify({ text: root.textContent, meters: root.querySelectorAll('[role="meter"]').length,
  note: hooks(root, "meter-note").length, label: root.attrs["aria-label"] }));
""")
        self.assertEqual((out["meters"], out["note"]), (0, 0))
        self.assertIn(GRADES["value"]["reason"], out["text"])
        self.assertIn("Beat the close", out["text"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class NotYetAvailableIsNotAZero(unittest.TestCase):
    def check(self, grades_js):
        return run(f"const G = {grades_js};\nmotion(false);\n" + """
const root = P.renderPickMeters(G, { compact: false });
console.log(JSON.stringify({ meters: root.querySelectorAll('[role="meter"]').length,
  imgs: root.querySelectorAll('[role="img"]').map((n) => n.attrs["aria-label"]),
  needles: root.querySelectorAll(".pm__needle").length, hubs: root.querySelectorAll(".pm__hub").length,
  na: root.querySelectorAll(".pm__dial--na").length, text: root.textContent, nums: root.querySelectorAll(".pm__num").length }));
""")

    def test_a_block_with_no_reading_is_a_grey_dial_with_no_needle(self):
        out = self.check(json.dumps(UNAVAILABLE))
        self.assertEqual((out["meters"], out["needles"], out["na"], out["nums"]), (0, 0, 2, 0))
        self.assertEqual(sorted(out["imgs"]), ["Confidence: not yet available", "Value: not yet available"])
        self.assertEqual(out["text"].count("Not yet available"), 2)
        self.assertEqual(out["text"].count("No settled bets like this before it was placed."), 1)      # said once, not twice

    def test_no_grades_at_all_is_the_same_state(self):
        for value in ("null", "undefined", '"junk"', "{}", '{"value": {"score": "high"}, "confidence": {"score": NaN}}'):
            out = self.check(value)
            self.assertEqual((out["meters"], out["needles"], out["na"]), (0, 0, 2), value)
            self.assertIn("Not yet available", out["text"])
            self.assertIn("Not a promise. Paper bets only.", out["text"])

    def test_one_dial_can_be_available_while_the_other_is_not(self):
        out = self.check(json.dumps({"value": GRADES["value"], "confidence": UNAVAILABLE["confidence"], "clv": None}))
        self.assertEqual((out["meters"], out["needles"], out["na"]), (1, 1, 1))

    def test_a_score_of_zero_is_a_real_reading_not_a_missing_one(self):
        out = self.check(json.dumps({"value": {"score": 0, "label": "Overpriced", "reason": "r"},
                                      "confidence": {"score": 0, "label": "Low", "reason": "r2"}, "clv": None}))
        self.assertEqual((out["meters"], out["needles"], out["na"]), (2, 2, 0))


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheSweepIsForTheViewerWhoAllowsMotion(unittest.TestCase):
    def test_reduced_motion_gets_a_static_needle_and_no_timer_or_observer(self):
        out = run(js(G=GRADES) + """
motion(false);
let observed = 0;
globalThis.IntersectionObserver = class { observe() { observed += 1; } disconnect() {} };
const root = P.renderPickMeters(G, {});
flush();
console.log(JSON.stringify({ cls: root.attrs.class, observed, timers: timers.length }));
""")
        self.assertIn("pm--static", out["cls"])
        self.assertNotIn("pm--anim", out["cls"])
        self.assertNotIn("pm--in", out["cls"])
        self.assertEqual(out["observed"], 0)

    def test_no_matchmedia_at_all_is_static_too(self):
        out = run(js(G=GRADES) + "globalThis.window = {};\nconst root = P.renderPickMeters(G, {});\nflush();\n"
                  "console.log(JSON.stringify({ cls: root.attrs.class }));")
        self.assertIn("pm--static", out["cls"])

    def test_motion_allowed_arms_the_sweep_and_the_class_flips_when_the_dial_is_on_screen(self):
        out = run(js(G=GRADES) + """
motion(true);
let cb = null;
globalThis.IntersectionObserver = class { constructor(f) { cb = f; } observe() {} disconnect() {} };
const root = P.renderPickMeters(G, {});
const before = root.attrs.class;
cb([{ isIntersecting: false }]);
const offscreen = root.attrs.class;
cb([{ isIntersecting: true }]);
console.log(JSON.stringify({ before, offscreen, after: root.attrs.class }));
""")
        self.assertIn("pm--anim", out["before"])
        self.assertNotIn("pm--in", out["before"])
        self.assertNotIn("pm--in", out["offscreen"])
        self.assertIn("pm--in", out["after"])

    def test_without_an_observer_the_class_flips_on_the_next_tick(self):
        out = run(js(G=GRADES) + """
motion(true);
const root = P.renderPickMeters(G, {});
const before = root.attrs.class;
flush();
console.log(JSON.stringify({ before, after: root.attrs.class }));
""")
        self.assertNotIn("pm--in", out["before"])
        self.assertIn("pm--in", out["after"])

    def test_opening_a_fold_replays_the_sweep(self):
        out = run(js(G=GRADES) + """
motion(true);
const root = P.renderPickMeters(G, {});
flush();
const played = root.attrs.class;
P.replayPickMeters(root);
const reset = root.attrs.class;
flush(); flush();
console.log(JSON.stringify({ played, reset, again: root.attrs.class }));
""")
        self.assertIn("pm--in", out["played"])
        self.assertNotIn("pm--in", out["reset"])
        self.assertIn("pm--in", out["again"])

    def test_the_stylesheet_animates_only_under_no_preference_and_rests_otherwise(self):
        rest = CSS.split("@media (prefers-reduced-motion: no-preference)")[0]
        self.assertRegex(rest, r"\.pm__needle\s*\{[^}]*transform:\s*rotate\(var\(--pm-angle")
        self.assertNotIn("transition", rest)
        block = CSS.split("@media (prefers-reduced-motion: no-preference)")[1]
        self.assertIn("transition: transform 600ms", block)
        self.assertRegex(block, r"\.pm--anim\.pm--in \.pm__needle\s*\{\s*transform:\s*rotate\(var\(--pm-angle")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheStylesheetIsLinkedOnce(unittest.TestCase):
    def test_three_renders_add_one_link(self):
        out = run(js(G=GRADES) + """
motion(false);
P.renderPickMeters(G, {}); P.renderPickMeters(null, { compact: true }); P.renderPickMeters(G, { compact: true });
const again = P.ensurePickMeterStyles();
console.log(JSON.stringify({ links: head.children.map((l) => ({ tag: l.tag, ...l.attrs })), again }));
""")
        self.assertEqual(len(out["links"]), 1)
        link = out["links"][0]
        self.assertEqual((link["tag"], link["rel"]), ("link", "stylesheet"))
        self.assertTrue(link["href"].endswith("css/pick-meters.css"), link["href"])
        self.assertFalse(out["again"])

    def test_a_page_without_a_head_just_renders(self):
        out = run(js(G=GRADES) + "document.head = null; document.querySelector = () => null;\nmotion(false);\n"
                  "console.log(JSON.stringify({ n: P.renderPickMeters(G, {}).querySelectorAll('[role=\"meter\"]').length }));")
        self.assertEqual(out["n"], 2)

    def test_the_stylesheet_file_exists_where_the_link_points(self):
        self.assertTrue((WEB / "css" / "pick-meters.css").is_file())


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheDialZonesAgreeWithTheServer(unittest.TestCase):
    def test_the_zone_bounds_are_the_label_thresholds(self):
        zones = run("console.log(JSON.stringify(P.ZONES));")
        self.assertEqual(zones["value"]["bounds"], [0, pg.OVERPRICED_BELOW, pg.VALUE_ABOVE, 100])
        self.assertEqual(zones["confidence"]["bounds"], [0, pg.LOW_BELOW, pg.HIGH_ABOVE, 100])
        self.assertEqual(zones["value"]["names"], [pg.LABEL_OVERPRICED, pg.LABEL_FAIR, pg.LABEL_VALUE])
        self.assertEqual(zones["confidence"]["names"], [pg.LABEL_LOW, pg.LABEL_MEDIUM, pg.LABEL_HIGH])

    def test_the_bright_zone_is_the_one_the_servers_word_names(self):
        out = run(js(G=GRADES) + """
motion(false);
const root = P.renderPickMeters(G, {});
const on = (kind) => root.querySelector(`.pm__dial--${kind}`).querySelectorAll(".pm__zone--on").map((z) => z.attrs.class);
console.log(JSON.stringify({ value: on("value"), confidence: on("confidence") }));
""")
        self.assertEqual(len(out["value"]), 1)
        self.assertIn("pm__zone--hi", out["value"][0])            # "Value" is the high zone of the value dial
        self.assertIn("pm__zone--mid", out["confidence"][0])      # "Medium"


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheTableChip(unittest.TestCase):
    def test_the_chip_reads_c_and_v(self):
        out = run(js(G=GRADES, N=UNAVAILABLE) + """
console.log(JSON.stringify({ a: P.gradeChip(G).textContent, title: P.gradeChip(G).attrs.title, b: P.gradeChip(N).textContent,
  none: P.gradeChip(null), nothing: P.gradeChip(undefined) }));
""")
        self.assertEqual(out["a"], "C 41 · V 66")
        self.assertEqual(out["b"], "C – · V –")
        self.assertIsNone(out["none"])
        self.assertIn("Confidence 41 (Medium)", out["title"])
        self.assertIn("Confidence is not a win chance.", out["title"])

    def test_the_fold_builds_its_dials_only_when_opened(self):
        out = run(js(G=GRADES) + """
motion(false);
const fold = P.gradeFold(G);
const closed = fold.querySelectorAll(".pm").length;
fold.setAttribute("open", "");
fold.fire("toggle");
const opened = fold.querySelectorAll('[role="meter"]').length;
fold.fire("toggle");
console.log(JSON.stringify({ closed, opened, again: fold.querySelectorAll(".pm").length, none: P.gradeFold(null) }));
""")
        self.assertEqual((out["closed"], out["opened"], out["again"]), (0, 2, 1))
        self.assertIsNone(out["none"])


TICKET = {
    "hound_id": "u-1", "date": "2026-10-25", "game": "Brewers at Cubs", "market": "totals", "selection": "Over 8.5", "price": -105,
    "price_average": -110, "book": "williamhill_us", "book_count": 8, "recorded_utc": "2026-10-26T00:20:00Z",
    "start_utc": "2026-10-26T01:00:00Z", "result": None, "status": "OPEN", "reason": "Total of 8.5 is under the hound's cap.",
}


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheTicketMounts(unittest.TestCase):
    def mount(self, ticket, extra=""):
        return run(js(T0=ticket) + "motion(false);\n" + extra + """
const card = T.ticketCard(T0);
const fold = card.querySelector('[data-hook="card-why"]');
console.log(JSON.stringify({ face: hooks(card, "card-meters").length, meters: card.querySelectorAll('[role="meter"]').length,
  fold: fold ? fold.textContent : null, foldMeters: fold ? fold.querySelectorAll('[role="meter"]').length : 0,
  notes: hooks(card, "meter-note").length, text: card.textContent }));
""")

    def test_a_card_with_grades_shows_dials_on_its_face_and_reasons_in_the_fold(self):
        out = self.mount(dict(TICKET, grades=GRADES))
        self.assertEqual((out["face"], out["meters"]), (1, 2))          # two dials on the face, none repeated in the fold
        self.assertEqual(out["foldMeters"], 0)
        self.assertIn("Why this bet", out["fold"])
        self.assertIn(TICKET["reason"], out["fold"])
        self.assertIn(GRADES["value"]["reason"], out["fold"])
        self.assertIn(GRADES["confidence"]["reason"], out["fold"])
        self.assertEqual(out["notes"], 1)                               # the note once per card

    def test_a_card_from_a_feed_without_grades_is_what_it_was(self):
        out = self.mount(TICKET)
        self.assertEqual((out["face"], out["meters"], out["notes"]), (0, 0, 0))
        self.assertIn("Total of 8.5", out["fold"])
        self.assertNotIn("Confidence", out["text"])

    def test_a_replay_ticket_with_null_grades_shows_no_dials(self):
        out = self.mount(dict(TICKET, segment="replay", grades=None))
        self.assertEqual((out["face"], out["meters"]), (0, 0))

    def test_a_card_with_grades_but_no_rule_reason_still_has_the_fold(self):
        out = self.mount(dict(TICKET, reason="", grades=GRADES))
        self.assertIn(GRADES["value"]["reason"], out["fold"])

    def test_a_card_with_an_unavailable_block_says_so_on_its_face(self):
        out = self.mount(dict(TICKET, grades=UNAVAILABLE))
        self.assertEqual((out["face"], out["meters"]), (1, 0))
        self.assertIn("Not yet available", out["text"])

    def test_the_wide_table_and_list_row_carry_the_chip_and_the_table_keeps_its_columns(self):
        out = run(js(T0=dict(TICKET, grades=GRADES), P0=TICKET) + "motion(false);\n" + """
const withG = T.ticketTable([T0], { graded: false });
const without = T.ticketTable([P0], { graded: false });
const row = T.ticketItem(T0, { showModel: false });
console.log(JSON.stringify({ chip: hooks(withG.querySelector("table"), "grade-fold").length,
  cols: withG.querySelectorAll("th").length, colsBefore: without.querySelectorAll("th").length,
  chipPlain: hooks(without.querySelector("table"), "grade-fold").length,
  rowChips: hooks(row, "grade-chip").map((c) => c.textContent) }));
""")
        self.assertEqual((out["chip"], out["chipPlain"]), (1, 0))
        self.assertEqual(out["cols"], out["colsBefore"])
        self.assertEqual(out["rowChips"], ["C 41 · V 66"])        # the wide row's chip; the phone card inside it shows dials, not a chip


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheWordsStayHonest(unittest.TestCase):
    BANNED = re.compile(r"\b(edge|lock|locks|locked|profit|guarantee|beta|sure thing|free money|new)\b", re.I)

    def test_nothing_rendered_makes_a_claim(self):
        out = run(js(G=GRADES, N=UNAVAILABLE) + """
motion(false);
const parts = [P.renderPickMeters(G, {}), P.renderPickMeters(G, { compact: true }), P.renderPickMeters(N, {}),
  P.renderPickMeters(null, { compact: true }), P.gradeChip(G), P.gradeChip(N)].map((n) => n.textContent + " " + (n.attrs.title || ""));
console.log(JSON.stringify(parts.join(" ")));
""")
        self.assertIsNone(self.BANNED.search(out), out)

    def test_the_source_never_computes_a_rating(self):
        src = (WEB / "js" / "pick-meters.js").read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith(("*", "/*", "//")))
        for banned in ("Math.log", "Math.exp", "Math.sqrt", "implied", "shrunk", "expected"):
            self.assertNotIn(banned, code, banned)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_NODE, "node is not installed")
class OnTheModelPage(unittest.TestCase):
    """The real model-page script (hounds-detail.js) over the fixture race: grades in the bets payload reach the cards."""

    def page(self, with_grades: bool):
        from tests.test_hounds_board_pages import ticket_routes
        from tests.test_hounds_web_pages import q, routes
        from tests.hounds_web_runner import run_page
        r = routes()
        r.update(ticket_routes("closer"))
        if with_grades:
            for key, (status, body) in list(r.items()):
                if "/hounds/closer/bets" in key and isinstance(body, dict):
                    for item in body.get("items", []):
                        item["grades"] = GRADES
        return run_page("hound", routes=r, search="?id=closer", queries=[
            q("face", "[data-hook='bets-table-cards'] [data-hook='card-meters']", "count"),
            q("dials", "[data-hook='bets-table-cards'] [data-hook='card-meters'] [role='meter']", "count"),
            q("folds", "[data-hook='bets-table'] [data-hook='grade-fold']", "count"),
            q("rows", "[data-hook='bets-table'] tbody tr", "count"),
            q("cards", "[data-hook='bets-table-cards'] [data-hook='ticket-card']", "count"),
        ])

    def test_graded_tickets_with_grades_show_dials_on_each_card_and_a_chip_in_each_row(self):
        out = self.page(True)["final"]
        self.assertGreater(out["cards"], 0)
        self.assertEqual(out["face"], out["cards"])
        self.assertEqual(out["dials"], 2 * out["cards"])
        self.assertEqual(out["folds"], out["rows"])

    def test_the_same_page_without_grades_has_none_of_it(self):
        out = self.page(False)["final"]
        self.assertGreater(out["cards"], 0)
        self.assertEqual((out["face"], out["dials"], out["folds"]), (0, 0, 0))
