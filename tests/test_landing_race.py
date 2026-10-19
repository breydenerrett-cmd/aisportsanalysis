"""The landing page's hero visual: the top models racing on their real paper bankroll (web/js/landing-race.js).

Design system v2, 2026-10-19. What this file holds the picture to:
  * every line is a real model's account from the same GET /hounds payload the board reads (no new route);
  * the geometry is honest and legible: the $1,000 start line is always on the chart, no two finish slots overlap,
    a line starts at the start line and ends at the balance the board prints;
  * it says what it is: each model's bet count beside its balance, the season's age, and, while every model has
    fewer than 30 bets, one sentence that a few bets say little;
  * no claim: no "edge", no "profit", no "guarantee" and no emoji anywhere in the picture;
  * with no model to show it says so and draws no line; reduced motion draws the finished picture at once.
"""

from __future__ import annotations

import json
import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_hounds_board_pages import EMOJI


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureGeometry(unittest.TestCase):
    def js(self, body):
        return run_js('import * as R from "./landing-race.js";\n' + body)

    def test_a_series_runs_from_the_start_to_the_balance_and_never_invents_a_point(self):
        got = self.js('''
const h = (spark, now) => ({ spark, bankroll: { start: 1000, current: now, unit_usd: 10 } });
console.log(JSON.stringify([R.raceSeries(h([0, 0.5, 1.2], 1012)), R.raceSeries(h([], 1007)), R.raceSeries(h(undefined, 993)),
  R.raceSeries({ spark: [0, 1] }), R.raceSeries(h([0, 0], 1000))]));''')
        self.assertEqual([round(v, 6) for v in got[0]], [1000, 1005, 1012])
        self.assertEqual(got[1], [1000, 1007])
        self.assertEqual(got[2], [1000, 993])
        self.assertIsNone(got[3], "no balance in the payload: no line")
        self.assertEqual(got[4], [1000, 1000], "two flat points stay two flat points")

    def test_the_y_scale_always_holds_the_start_line_and_uses_round_ticks(self):
        got = self.js('console.log(JSON.stringify([R.yScale([[1000, 1021]]), R.yScale([[1000, 1002]]), R.yScale([[1000, 940]])]));')
        for sc in got:
            self.assertLessEqual(sc["lo"], 1000)
            self.assertGreaterEqual(sc["hi"], 1000)
            steps = {round(b - a, 6) for a, b in zip(sc["ticks"], sc["ticks"][1:])}
            self.assertEqual(len(steps), 1)
            self.assertIn(steps.pop(), (5, 10, 20, 50, 100))
        self.assertGreaterEqual(got[0]["hi"], 1021)
        self.assertLessEqual(got[2]["lo"], 940)

    def test_finish_labels_never_overlap_and_stay_in_bounds(self):
        got = self.js('console.log(JSON.stringify([R.spreadLabels([100, 101, 102, 103, 104], 40, 20, 300), R.spreadLabels([290, 295, 299], 40, 20, 300), R.spreadLabels([], 40, 0, 10)]));')
        for ys in got[:2]:
            order = sorted(ys)
            self.assertTrue(all(b - a >= 40 - 1e-9 for a, b in zip(order, order[1:])), ys)
            self.assertTrue(all(20 <= y <= 300 for y in ys), ys)
        self.assertEqual(got[2], [])

    def test_the_layout_puts_five_dogs_apart_and_every_line_on_the_chart(self):
        got = self.js('''
const mk = (id, vals) => ({ id, name: id, series: vals });
const racers = [mk("a", [1000, 1021]), mk("b", [1000, 1018]), mk("c", [1000, 1009]), mk("d", [1000, 1008]), mk("e", [1000, 1008])];
const out = [R.layoutRace(racers, 640), R.layoutRace(racers, 340)];
console.log(JSON.stringify(out.map((g) => ({ wide: g.wide, W: g.W, H: g.H, face: g.face, slotX: g.slotX, baseY: g.baseY, m: g.m,
  slots: g.lines.map((l) => l.slot.y), starts: g.lines.map((l) => l.points[0].y), ends: g.lines.map((l) => l.points[l.points.length - 1].y) }))));''')
        wide, narrow = got
        self.assertTrue(wide["wide"] and not narrow["wide"])
        for g in got:
            ys = sorted(g["slots"])
            self.assertTrue(all(b - a >= g["face"] + 8 - 1e-9 for a, b in zip(ys, ys[1:])), "dogs overlap")
            self.assertTrue(all(abs(s - g["baseY"]) < 1e-6 for s in g["starts"]), "every line starts on the $1,000 line")
            self.assertTrue(all(g["m"]["t"] <= e <= g["H"] - g["m"]["b"] for e in g["ends"]))
            self.assertLessEqual(g["slotX"] + g["face"], g["W"] + 1)
        self.assertLess(wide["ends"][0], wide["ends"][2], "a higher balance sits higher (smaller y)")

    def test_a_partial_line_is_cut_at_the_fraction_and_ends_on_the_last_point(self):
        got = self.js('''
const pts = [{ x: 0, y: 10, v: 1 }, { x: 10, y: 0, v: 2 }, { x: 20, y: 0, v: 3 }];
const a = R.partial(pts, 0), b = R.partial(pts, 0.25), c = R.partial(pts, 1), d = R.partial([pts[0]], 0.5);
console.log(JSON.stringify([a.tip, b.tip, c.tip, c.d, d.d]));''')
        self.assertEqual(got[0], {"x": 0, "y": 10, "v": 1})
        self.assertEqual((got[1]["x"], got[1]["y"]), (5, 5))
        self.assertEqual((got[2]["x"], got[2]["y"]), (20, 0))
        self.assertEqual(got[3], "M0 10 L10 0 L20 0")
        self.assertEqual(got[4], "M0 10")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRaceOnThePage(unittest.TestCase):
    def routes(self, **over):
        r = {k: list(v) for k, v in F.routes().items()}
        r.update(over)
        return r

    def page(self, routes=None, **kw):
        return run_page("landing_board", routes=self.routes() if routes is None else routes, **kw)

    def test_the_race_draws_one_line_and_one_dog_per_board_model(self):
        out = self.page(queries=[
            q("lines", "[data-hook='lb-race'] path.lbrace__line", "count"), q("dogs", "[data-hook='lb-race'] svg.dk-badge", "count"),
            q("chart", "[data-hook='lb-race'] svg.lbrace__svg", "count"), q("legend", "[data-hook='lb-race-legend'] li", "count"),
            q("state", "[data-hook='lb-race']", "attr", attr="data-state"), q("ids", "path.lbrace__line", "attrs", attr="data-id"),
            q("board", "[data-hook='lb-board'] .lbrow", "attrs", attr="data-hound")])
        f = out["final"]
        self.assertEqual((f["lines"], f["dogs"], f["chart"], f["legend"]), (5, 5, 1, 5))
        self.assertEqual(f["state"], "ready")
        self.assertEqual(f["ids"], f["board"], "the race shows the same models, in the same order, as the board")

    def test_it_asks_for_nothing_the_board_does_not(self):
        out = self.page()
        self.assertEqual(sorted(g.split("?")[0] for g in out["gets"]), ["/hounds", "/hounds/stream"])

    def test_every_model_carries_its_bet_count_and_the_picture_says_a_few_bets_say_little(self):
        board = json.loads(json.dumps(F.leaderboard()))
        for h in board["hounds"]:
            h["record"] = dict(h["record"], bets=min(h["record"].get("bets", 3), 9))
        out = self.page(routes=self.routes(**{"/hounds": [200, board]}), queries=[
            q("sub", "[data-hook='lb-race-sub']"), q("note", "[data-hook='lb-race-note']"),
            q("bets", ".lbrace__itembets", "texts"), q("label", "svg.lbrace__svg", "attr", attr="aria-label")])
        f = out["final"]
        self.assertIn("$1,000", f["sub"])
        self.assertIn("a few bets say little", f["note"])
        self.assertEqual(len(f["bets"]), 5)
        self.assertTrue(all(re.fullmatch(r"\d+ bets?", b) for b in f["bets"]), f["bets"])
        self.assertIn("each starting at $1,000", f["label"])

    def test_with_thirty_bets_the_thin_sample_sentence_is_dropped_but_the_plain_one_stays(self):
        board = json.loads(json.dumps(F.leaderboard()))
        for h in board["hounds"]:
            h["record"] = dict(h["record"], bets=60)
        out = self.page(routes=self.routes(**{"/hounds": [200, board]}), queries=[q("note", "[data-hook='lb-race-note']")])
        self.assertNotIn("few bets", out["final"]["note"])
        self.assertIn("nothing more", out["final"]["note"])

    def test_the_picture_claims_nothing_and_has_no_emoji(self):
        out = self.page(queries=[q("race", "[data-hook='lb-race']")])
        text = out["final"]["race"]
        self.assertIsNone(re.search(r"(?i)\bedge\b|\bprofit|guarantee|\bEV\b|will win|beat the market|\bsharp\b|\block\b", text), text)
        self.assertEqual(EMOJI.findall(text), [])

    def test_no_model_to_show_says_so_and_draws_no_line(self):
        r = self.routes(**{"/hounds": [200, {"hounds": []}], "/hounds/stream": [200, {"items": []}]})
        out = self.page(routes=r, queries=[q("lines", "path.lbrace__line", "count"), q("state", "[data-hook='lb-race']", "attr", attr="data-state"),
                                           q("sub", "[data-hook='lb-race-sub']")])
        f = out["final"]
        self.assertEqual(f["lines"], 0)
        self.assertEqual(f["state"], "empty")
        self.assertIn("No model has a settled bet", f["sub"])
        self.assertNotRegex(f["sub"], r"[+-]\$?\d")

    def test_no_answer_leaves_the_static_line_and_names_no_figure(self):
        out = self.page(routes={}, queries=[q("sub", "[data-hook='lb-race-sub']"), q("lines", "path.lbrace__line", "count")])
        self.assertEqual(out["final"]["lines"], 0)
        self.assertIn("once the leaderboard loads", out["final"]["sub"])
        self.assertNotRegex(out["final"]["sub"], r"\d")

    def test_the_static_markup_has_the_race_container_and_no_dog_word(self):
        with open("web/landing.html", encoding="utf-8") as fh:
            html = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
        block = re.search(r'<div class="lbhero__race".*?</ol>', html, re.S).group(0)
        self.assertNotRegex(re.sub(r"<[^>]+>", " ", block).lower(), r"kennel|\bdog|bark|houndmaster")
        self.assertIn('data-hook="lb-race-replay"', block)
        self.assertEqual(html.count('data-hook="lb-race"'), 1)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ReducedMotionDrawsTheFinishedPicture(unittest.TestCase):
    def test_reduced_motion_never_schedules_a_frame_and_hides_replay(self):
        got = run_js('''
globalThis.window = { matchMedia: () => ({ matches: true }) };
let frames = 0; globalThis.requestAnimationFrame = () => { frames += 1; };
const mkEl = (tag) => ({ tag, attrs: {}, kids: [], parentNode: null, firstChild: null,
  setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }, removeAttribute(k) { delete this.attrs[k]; },
  appendChild(c) { c.parentNode = this; this.kids.push(c); this.firstChild = this.kids[0]; return c; },
  removeChild(c) { this.kids = this.kids.filter((x) => x !== c); this.firstChild = this.kids[0] || null; return c; },
  set textContent(v) { this.text = v; }, addEventListener() {}, getBoundingClientRect() { return { width: 600 }; } });
globalThis.document = { createElement: mkEl, createElementNS: (ns, t) => mkEl(t), createTextNode: (t) => ({ nodeType: 3, textContent: t }) };
const R = await import("./landing-race.js");
const mk = (id, now) => ({ id, name: id, status: "running", record: { bets: 3 }, spark: [0, (now - 1000) / 10], bankroll: { start: 1000, current: now, unit_usd: 10, return_pct: (now - 1000) / 10 } });
const host = mkEl("div"); const chart = mkEl("div"); const sub = mkEl("p"); const legend = mkEl("ol"); const note = mkEl("p"); const replay = mkEl("button");
const hooks = { "lb-race-chart": chart, "lb-race-sub": sub, "lb-race-legend": legend, "lb-race-note": note, "lb-race-replay": replay };
host.querySelector = (sel) => hooks[(/data-hook='([^']+)'/.exec(sel) || [])[1]] || null;
R.renderRace(host, [mk("a", 1021), mk("b", 1010)], { label: "Season 2", start: "2026-10-18" }, "2026-10-19");
console.log(JSON.stringify([frames, host.attrs["data-run"], replay.attrs.hidden !== undefined, chart.kids.length, host.attrs["data-state"]]));''')
        self.assertEqual(got, [0, "done", True, 1, "ready"])


if __name__ == "__main__":
    unittest.main()
