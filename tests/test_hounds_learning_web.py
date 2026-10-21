"""The learning loop's two surfaces, run for real under node against a fake DOM, fed payloads built by the
real Python code (src/hounds/learning/views.py), so a drift fails a test instead of a visitor:

  web/learning.html        the system scorecard with the random-control line, the lessons
  web/hound.html           the "Versions and challengers" section

Skipped when node is not installed. Static checks (not-advice, no banned words, links) need no node.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds.learning import ledger as L, lessons, pause, scorecard, views
from tests import _learning_fixtures as F
from tests import hounds_web_fixtures as WF
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page

NOW = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)
INFO = {"professor_paws": {"kind": "house", "category": "stats", "status": "running"},
        "coin_flip_collie": {"kind": "house", "category": "random", "status": "running"}}


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def clv_bets(day, n, champion, control):
    games = [f"g{day}-{i}" for i in range(n)]
    return ([("professor_paws", g, "h2b", day, champion) for g in games]
            + [("coin_flip_collie", g, "h2b", day, control) for g in games])


def scopes_with_data(root: Path, days=5, n=60):
    scope_map = {"house": L.Scope.house(root / "h"), "user": L.Scope.user(root / "u")}
    house = scope_map["house"]
    for i in range(days):
        day = NOW - timedelta(days=days - 1 - i)
        bets = clv_bets(day.date().isoformat(), n, -1.0 + i * 0.1, -1.5)
        card = scorecard.compute(house, now=day, clv_bets=bets, hound_info=INFO, matured_fn=lambda p: None)
        scorecard.store(house, card, now=day)
    return scope_map


def learning_payload(root: Path, lesson_count=0, paused=False, enough=True):
    scope_map = scopes_with_data(root, n=60 if enough else 10)
    house = scope_map["house"]
    for i in range(lesson_count):
        F.propose_raw(house, cid=f"c-{i}", hound_id="professor_paws", created=f"2026-11-{i + 1:02d}T01:00:00Z",
                      hypothesis=f"Hypothesis number {i} written by the coach.")
        c = L.read_state(house).challengers[f"c-{i}"]
        lessons.write(house, c, {"outcome": "retired" if i % 2 else "promoted", "reason": "harm"}, None,
                      now=F.utc(f"2026-12-{i + 1:02d}T00:00:00Z"))
    if paused:
        pause.pause(house, "promotion hit rate 0.30 over 12 matured promotions", now=NOW,
                    config_file=root / "cfg.json")
        card = scorecard.compute(house, now=NOW + timedelta(days=1), clv_bets=[], hound_info=INFO,
                                 matured_fn=lambda p: None)
        scorecard.store(house, card, now=NOW + timedelta(days=1))
    return jsonable(views.learning_payload(scope_map))


def visible(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<(script|style|head)\b.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    for ent, ch in (("&middot;", "·"), ("&rarr;", "->"), ("&larr;", "<-"), ("&amp;", "&")):
        text = text.replace(ent, ch)
    return re.sub(r"\s+", " ", text).strip()


class StaticFacts(unittest.TestCase):
    HTML = (WEB / "learning.html").read_text(encoding="utf-8")

    def test_paper_only_not_advice_21_plus_and_the_help_line_are_static_markup(self):
        text = visible(self.HTML)
        self.assertRegex(text, r"(?i)paper bets only, not advice")
        self.assertIn("21+", text)
        self.assertIn("Gamble responsibly.", text)
        self.assertIn("1-800-GAMBLER", text)
        self.assertIn("not-advice", self.HTML)

    def test_landmarks_skip_link_viewport_and_local_assets_only(self):
        for needle in ('class="hd-skip"', 'id="main-content"', "<main", 'name="viewport"', '<html lang="en">'):
            self.assertIn(needle, self.HTML)
        self.assertNotRegex(self.HTML, r"<img\b")
        for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', self.HTML):
            self.assertFalse(src.startswith(("http:", "https:", "//")), src)
            self.assertTrue((WEB / src).is_file(), src)
        for href in re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', self.HTML):
            self.assertTrue((WEB / href).is_file(), href)

    def test_the_copy_makes_no_claim_an_edge_a_profit_or_a_guarantee_and_never_names_bet_check(self):
        for path in (WEB / "learning.html", WEB / "js" / "hounds-learning.js", WEB / "js" / "hounds-lineage.js"):
            raw = path.read_text(encoding="utf-8")
            body = re.sub(r"/\*.*?\*/", "", raw, flags=re.S) if path.suffix == ".js" else raw
            body = re.sub(r"(?m)^\s*//.*$", "", body)
            body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
            self.assertNotRegex(body.lower(), r"bet[\s_-]*check", path.name)
            self.assertNotRegex(body, r"(?i)\b(profit|guarantee[sd]?|roi|win rate|sure thing|beat the market|edge)\b", path.name)

    def test_the_race_and_the_hound_page_link_to_it(self):
        for name in ("hounds.html", "hound.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            # the one navigation (web/js/nav.js) names it "Training camp"
            self.assertRegex(html, r'<a href="learning.html" data-nav="camp"[^>]*>Training camp</a>', name)

    def test_the_coach_report_card_section_is_the_first_panel_and_wears_the_voice(self):
        html = self.HTML
        coach = html.index('data-hook="coach-section"')
        self.assertLess(coach, html.index('data-hook="learning-chance-section"'))
        text = visible(html)
        for needle in ("Coach report card", "is the coach any good", "Hindsight", "TOO EARLY",
                       "Graded by code, never by the coach", "Paper bets only, not advice"):
            self.assertIn(needle, text)

    def test_the_hound_page_has_the_versions_and_challengers_section(self):
        html = (WEB / "hound.html").read_text(encoding="utf-8")
        self.assertIn('data-hook="hound-lineage-section"', html)
        self.assertIn("Versions", html)
        self.assertIn("A hound is never edited", html)        # owner ruling 2026-10-20 kennel-first: hound, not model


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheScorecardPage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def page(self, payload, **kw):
        routes = {"/hounds/learning": [200, payload]}
        routes.update(kw.pop("routes", {}))
        return run_page("learning", routes=routes, queries=kw.pop("queries", []), **kw)

    def test_the_random_control_line_is_drawn_with_both_lines_and_the_gap_is_in_words(self):
        payload = learning_payload(self.root)
        out = self.page(payload, queries=[
            q("chart", "[data-hook='chance-chart']", "exists"), q("empty", "[data-hook='chance-chart'][data-empty]", "exists"),
            q("lines", "[data-hook='chance-chart'] [data-line]", "attrs", attr="data-line"),
            q("cols", "[data-hook='chart-data-table'] thead th", "texts"),
            q("w30", "[data-hook='chance-30']"), q("w90", "[data-hook='chance-90']")])
        self.assertTrue(out["final"]["chart"])
        self.assertFalse(out["final"]["empty"])
        self.assertEqual(out["final"]["lines"], ["champions", "controls"])
        self.assertIn("Starters (30-day average) (points)", out["final"]["cols"])
        self.assertIn("Random controls (30-day average) (points)", out["final"]["cols"])
        w30 = out["final"]["w30"]
        self.assertIn("above the controls", w30)               # -0.6 against -1.5 on the last day
        self.assertIn("60 shared games", w30)
        self.assertIn("read it as a scoreboard, not a verdict", w30)
        self.assertEqual(sorted(out["gets"]), ["/hounds/coach/report", "/hounds/learning"])

    def test_too_few_bets_says_so_with_the_counts_instead_of_a_number(self):
        out = self.page(learning_payload(self.root, enough=False), queries=[q("w30", "[data-hook='chance-30']")])
        self.assertIn("The comparison builds as bets settle", out["final"]["w30"])   # owner ruling 2026-10-20, complete-product positioning
        self.assertIn("10 starter bets and 10 control bets", out["final"]["w30"])
        self.assertIn("50 measurable bets on each side", out["final"]["w30"])
        self.assertNotRegex(out["final"]["w30"], r"averaged [-+]\d")

    def test_before_any_scorecard_the_page_says_so_and_invents_nothing(self):
        scope_map = {"house": L.Scope.house(self.root / "h"), "user": L.Scope.user(self.root / "u")}
        payload = jsonable(views.learning_payload(scope_map))
        out = self.page(payload, queries=[q("nc", "[data-hook='not-computed']"),
                                          q("hold", "[data-hook='hold-text']"),
                                          q("lessons", "[data-hook='lessons-empty']"),
                                          q("rules", "[data-hook='rules-list'] li", "count")])
        self.assertIn("No daily scorecard has been stored yet", out["final"]["nc"])
        self.assertIn("nothing to hold up", out["final"]["hold"])
        self.assertIn("No tryout has ended yet", out["final"]["lessons"])
        self.assertGreaterEqual(out["final"]["rules"], 5)
        self.assertNotIn("NaN", out["text"])
        self.assertNotIn("undefined", out["text"])

    def test_a_paused_loop_shows_a_banner_with_its_reason_and_who_must_resume_it(self):
        out = self.page(learning_payload(self.root, paused=True), queries=[
            q("hidden", "[data-hook='learning-paused']", "hidden"), q("banner", "[data-hook='learning-paused']"),
            q("reason", "[data-hook='pause-reason']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Camp has shut itself down", out["final"]["banner"])
        self.assertIn("until the owner turns it back on", out["final"]["banner"])
        self.assertIn("promotion hit rate 0.30 over 12 matured promotions", out["final"]["reason"])

    def test_an_unpaused_loop_hides_the_banner(self):
        out = self.page(learning_payload(self.root), queries=[q("hidden", "[data-hook='learning-paused']", "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_activity_the_budget_and_the_chain_status(self):
        out = self.page(learning_payload(self.root), queries=[
            q("facts", "[data-hook='activity-facts'] dd", "texts"), q("budget", "[data-hook='budget-text']"),
            q("chain", "[data-hook='chain-status']")])
        self.assertEqual(out["final"]["facts"][:3], ["0", "0", "0"])
        self.assertIn("Fluke check level 0.1", out["final"]["budget"])
        self.assertIn("cap 3 per scope", out["final"]["budget"])
        self.assertIn("passes its tamper check", out["final"]["chain"])

    def test_lessons_are_listed_newest_first_and_older_ones_load_on_demand(self):
        payload = learning_payload(self.root, lesson_count=7)
        scope_map = {"house": L.Scope.house(self.root / "h"), "user": L.Scope.user(self.root / "u")}
        older = jsonable(views.lessons_payload(scope_map, hound=None, category=None, page=2, page_size=5))
        out = self.page(payload, routes={"/hounds/learning/lessons?page=2&page_size=5": [200, older]}, queries=[
            q("n", "[data-hook='lessons-list'] li", "count"), q("first", "[data-hook='lessons-list'] li"),
            q("more", "[data-hook='lessons-more']", "exists")], actions=[
            dict(do="click", sel="[data-hook='lessons-more']", wait=80,
                 capture=[q("n", "[data-hook='lessons-list'] li", "count"),
                          q("hidden", "[data-hook='lessons-more']", "hidden")])])
        self.assertEqual(out["final"]["n"], 5 + 2)
        self.assertTrue(out["final"]["more"])
        self.assertIn("Hypothesis number 6 written by the coach", out["final"]["first"])      # newest first
        self.assertIn("The coach's pitch, quoted", out["final"]["first"])
        self.assertEqual(out["captures"]["0"]["n"], 7)
        self.assertTrue(out["captures"]["0"]["hidden"])
        self.assertTrue(any("page=2" in g for g in out["gets"]))

    def test_a_down_server_is_not_shown_as_an_empty_loop(self):
        out = run_page("learning", routes={}, down=["/hounds/learning"], queries=[
            q("kinds", "[data-hook='section-state']", "attrs", attr="data-kind"),
            q("retry", "[data-hook='learning-chance'] button", "count"),
            q("paper", "[data-hook='paper-only-notice']")])
        self.assertTrue(out["final"]["kinds"])
        self.assertEqual(set(out["final"]["kinds"]), {"down"})
        self.assertEqual(out["final"]["retry"], 1)
        self.assertIn("Paper bets only. Not advice.", out["final"]["paper"])

    def test_a_broken_ledger_is_called_out(self):
        payload = learning_payload(self.root)
        payload["chain"]["house"] = False
        out = self.page(payload, queries=[q("chain", "[data-hook='chain-status']")])
        self.assertIn("failed its integrity check (house)", out["final"]["chain"])


def coach_report_payload(root: Path, tips=()):
    """The real report payload (src/hounds/coach_report.py) from a temp ledger. ``tips`` are
    (issue, hindsight_units or None, forward label or None, n, units) tuples."""
    from src.hounds import coach_card as CC, coach_report as CR
    from tests import _coach_card_fixtures as CF
    paths = CF.paths_in(root / "coach")
    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    for issue, hind, label, n, units in tips:
        rec = f"2026-10-{10 + issue:02d}T12:00:00Z"
        CC.append(paths, CC.K_SUGGESTION, now=CC.parse(rec), **CF.suggestion_row(issue=issue, recorded=rec))
        if hind is not None:
            CC.append(paths, CC.K_HINDSIGHT, now=CC.parse(rec), issue=issue, hound="fake_dog", hindsight=True,
                      status="ok", units_diff=hind, window_first="2026-09-01", window_last="2026-10-01",
                      window_days=30)
        if label is not None:
            CC.append(paths, CC.K_FORWARD, now=CC.parse(rec), issue=issue, hound="fake_dog", label=label,
                      n_paired=n, n_dates=min(n, 5), units_diff=units)
    CR._CACHE.clear()
    return jsonable(CR.build(paths))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCoachReportCard(unittest.TestCase):
    """The top section, "Is the coach any good?", rendered by the real page script from the real payload."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def page(self, report, *, status=200, **kw):
        payload = learning_payload(self.root)
        routes = {"/hounds/learning": [200, payload], "/hounds/coach/report": [status, report]}
        return run_page("learning", routes=routes, queries=kw.pop("queries", []), **kw)

    TIPS = ((1, 2.1, "HELPED", 25, 3.2), (2, -1.0, "HURT", 22, -2.0), (3, 0.5, "NO DIFFERENCE", 30, 0.1),
            (4, 1.0, "TOO EARLY", 3, 0.5), (5, None, None, 0, 0.0))

    def test_the_summary_the_four_badges_and_the_tip_lines_are_on_the_page(self):
        out = self.page(coach_report_payload(self.root, self.TIPS), queries=[
            q("summary", "[data-hook='coach-summary']"), q("facts", "[data-hook='coach-facts'] dt", "texts"),
            q("badges", "[data-hook='coach-badge']", "texts"), q("n", "[data-hook='coach-list'] li", "count"),
            q("lines", "[data-hook='coach-line']", "texts"), q("totals", "[data-hook='coach-totals']"),
            q("labels", "[data-hook='coach-list'] li", "attrs", attr="data-label"),
            q("title", "#coach-h")])
        f = out["final"]
        self.assertIn("5 tips so far.", f["summary"])
        self.assertIn("3 graded live: 1 helped, 1 hurt, 1 no difference.", f["summary"])
        self.assertIn("2 awaiting a verdict", f["summary"])   # owner ruling 2026-10-20, complete-product positioning
        # the grade word on screen is IN PROGRESS; the data label stays TOO EARLY (owner ruling 2026-10-20,
        # complete-product positioning)
        self.assertEqual(f["facts"], ["Tips made", "Tips refused", "HELPED", "HURT", "NO DIFFERENCE",
                                      "IN PROGRESS"])
        self.assertEqual(sorted(f["badges"]), sorted(["HELPED", "HURT", "NO DIFFERENCE", "IN PROGRESS",
                                                      "IN PROGRESS"]))
        self.assertEqual(f["n"], 5)
        self.assertEqual(f["labels"][0], "IN PROGRESS")                       # newest tip first (issue 5, no grade yet)
        self.assertTrue(any("Hindsight: +2.1u better. Live: helped (+3.2u over 25 bets)." in ln for ln in f["lines"]))
        self.assertTrue(any("Live: too early (0 bets)." in ln for ln in f["lines"]))
        self.assertIn("Coach told Fake Dog to change", f["lines"][0])
        self.assertIn("Hindsight:", f["totals"])
        self.assertIn("rehearsal, not a result", f["totals"])             # hindsight is labelled on the page
        self.assertIn("Coach report card", f["title"])

    def test_before_any_tip_the_page_says_so_and_invents_nothing(self):
        out = self.page(coach_report_payload(self.root), queries=[
            q("summary", "[data-hook='coach-summary']"), q("empty", "[data-hook='coach-empty']")])
        self.assertIn("No tips yet", out["final"]["summary"])
        self.assertIn("has not made a suggestion yet", out["final"]["empty"])
        self.assertNotIn("NaN", out["text"])
        self.assertNotIn("undefined", out["text"])

    def test_a_server_without_the_report_route_is_a_calm_note_and_the_scorecard_still_renders(self):
        out = self.page({"detail": "Not Found"}, status=404, queries=[
            q("state", "[data-hook='coach-state']"), q("kind", "[data-hook='coach-state']", "attr", attr="data-kind"),
            q("chance", "[data-hook='chance-30']")])
        self.assertIn("not switched on yet", out["final"]["state"])
        self.assertEqual(out["final"]["kind"], "missing")
        self.assertIn("above the controls", out["final"]["chance"])

    def test_the_scorecard_being_down_does_not_hide_the_report_card(self):
        payload = coach_report_payload(self.root, self.TIPS)
        out = run_page("learning", routes={"/hounds/coach/report": [200, payload]}, down=["/hounds/learning"],
                       queries=[q("n", "[data-hook='coach-list'] li", "count"),
                                q("kinds", "[data-hook='section-state']", "attrs", attr="data-kind")])
        self.assertEqual(out["final"]["n"], 5)
        self.assertEqual(set(out["final"]["kinds"]), {"down"})

    def test_a_broken_coach_ledger_is_called_out(self):
        report = coach_report_payload(self.root, self.TIPS)
        report["chain_ok"] = False
        out = self.page(report, queries=[q("chain", "[data-hook='coach-chain']")])
        self.assertIn("failed its integrity check", out["final"]["chain"])

    def test_a_challenger_tip_says_it_also_made_the_tryouts(self):
        report = coach_report_payload(self.root, self.TIPS)
        report["items"][0]["mode"] = "challenger"
        out = self.page(report, queries=[q("text", "[data-hook='coach-list']")])
        self.assertIn("also made the rookie tryouts", out["final"]["text"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCoachPureText(unittest.TestCase):
    def js(self, body):
        return run_js('import * as C from "./hounds-learning.js";\n' + body)

    def test_badges_always_carry_the_word_beside_the_emoji(self):
        out = self.js('console.log(JSON.stringify(["HELPED", "hurt", "NO DIFFERENCE", "TOO EARLY", "weird", null]'
                      '.map(C.coachBadge).map(b => b.text)));')
        self.assertEqual(out, ["HELPED", "HURT", "NO DIFFERENCE", "IN PROGRESS", "NOT GRADED",
                               "NOT GRADED"])

    def test_the_summary_sentence(self):
        s = {"suggestions": 1, "refused": 0, "helped": 0, "hurt": 0, "no_difference": 0, "too_early": 1}
        out = self.js(f"console.log(JSON.stringify([C.coachSummaryText({json.dumps(s)}), C.coachSummaryText(null), "
                      f"C.coachSummaryText({json.dumps(dict(s, suggestions=0, too_early=0, refused=2))})]));")
        self.assertIn("1 tip so far.", out[0])
        self.assertIn("None has been graded live yet.", out[0])
        self.assertIn("it needs 20 settled bets", out[0])   # owner ruling 2026-10-20, complete-product positioning
        self.assertIn("No tips yet", out[1])
        self.assertIn("2 suggestions were refused", out[2])

    def test_the_totals_label_hindsight_a_rehearsal_and_do_not_invent_a_live_number(self):
        out = self.js('console.log(JSON.stringify([C.coachTotalsText({forward_units_diff: 1.25, '
                      'hindsight_units_diff: -3}), C.coachTotalsText({forward_units_diff: null, '
                      'hindsight_units_diff: null})]));')
        self.assertIn("Live, all tips together: +1.25u", out[0])
        self.assertIn("Hindsight: -3.00u", out[0])
        self.assertIn("rehearsal, not a result", out[0])
        self.assertEqual(out[1], "Live: no settled games yet.")


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureText(unittest.TestCase):
    def js(self, body):
        return run_js('import * as C from "./hounds-learning.js";\nimport * as V from "./hounds-lineage.js";\n' + body)

    def test_chance_line_and_hold_text(self):
        w = {"days": 30, "games": 60, "champion_bets": 90, "control_bets": 80, "champion_mean": -0.5,
             "control_mean": -1.5, "difference": 1.0, "enough": True}
        out = self.js(f"console.log(JSON.stringify([C.chanceLine({json.dumps(w)}), "
                      f"C.chanceLine({json.dumps(dict(w, difference=-0.25, enough=True))}), "
                      f"C.chanceLine({json.dumps(dict(w, difference=0.0))}), "
                      f"C.chanceLine({json.dumps(dict(w, enough=False, difference=None))}), C.chanceLine(null)]));")
        self.assertIn("1.00 points above the controls", out[0])
        self.assertIn("0.25 points below the controls", out[1])
        self.assertIn("level with the controls", out[2])
        self.assertIn("The comparison builds as bets settle (90 starter bets and 80 control bets on 60 shared games)", out[3])   # owner ruling 2026-10-20, complete-product positioning
        self.assertEqual(out[4], "Not reported.")

    def test_hold_text_covers_no_promotions_none_matured_and_a_rate(self):
        out = self.js("console.log(JSON.stringify([C.holdText({promotions: 0}), "
                      "C.holdText({promotions: 2, matured: 0}), "
                      "C.holdText({promotions: 12, matured: 10, hits: 4, rate: 0.4, floor: 0.4, min_matured_for_floor: 10}), "
                      "C.holdText(null)]));")
        self.assertIn("nothing to hold up", out[0])
        self.assertIn("2 rookies have made the team; none has made 100 bets", out[1])
        self.assertIn("4 of 10 rookies who made the team priced at least as well", out[2])
        self.assertIn("40%", out[2])
        self.assertIn("nothing to hold up", out[3])

    def test_history_series_keeps_only_days_with_both_means(self):
        hist = [{"date": "2026-12-01", "champion_mean_30": -1.0, "control_mean_30": -2.0},
                {"date": "2026-12-02", "champion_mean_30": None, "control_mean_30": -2.0},
                {"date": "2026-12-03", "champion_mean_30": -0.5, "control_mean_30": None},
                {"date": "2026-12-04", "champion_mean_30": 0.0, "control_mean_30": -1.0}]
        out = self.js(f"console.log(JSON.stringify(C.historySeries({json.dumps(hist)}).map(s => [s.id, s.points.map(p => p.date)])));")
        self.assertEqual(out, [["champions", ["2026-12-01", "2026-12-04"]], ["controls", ["2026-12-01", "2026-12-04"]]])

    def test_diff_and_look_text(self):
        c = {"latest_look": {"look_no": 1, "n": 100, "mean": 1.2, "lower": 0.3, "upper": 2.1, "eligible": True}}
        out = self.js(f"console.log(JSON.stringify([V.diffText({{GAP: [0.02, 0.03], markets: [['moneyline', 'spread'], ['moneyline']]}}), "
                      f"V.diffText({{}}), V.lookText({json.dumps(c)}), V.lookText({{}}), "
                      f"V.lookText({json.dumps({'latest_look': {'look_no': 2, 'n': 150, 'mean': -1.0, 'harm': True}})})]));")
        self.assertEqual(out[0], "GAP: 0.02 -> 0.03; markets: [moneyline, spread] -> [moneyline]")
        self.assertEqual(out[1], "no change recorded")
        self.assertIn("Look 1, after 100 paired games: its prices beat the current version's by +1.20 points on average (somewhere between +0.30 and +2.10)", out[2])
        self.assertIn("cleared the first bar", out[2])
        self.assertIn("Waiting for its first look, at 100 paired games", out[3])
        self.assertIn("doing worse than the current version", out[4])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHoundPagesVersionsSection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def lineage(self, versions, live=(), failed=(), lesson_rows=(), paused=False):
        return {"hound_id": "closer", "paused": paused, "versions": versions, "live_challengers": list(live),
                "tried_and_failed": list(failed), "closed_undecided": [], "promoted": [], "lessons": list(lesson_rows),
                "paper_only": True}

    def page(self, lineage, status=200, **kw):
        r = {k: list(v) for k, v in WF.routes().items()}
        if lineage is not None:
            r["/hounds/closer/lineage"] = [status, lineage]
        return run_page("hound", routes=r, search="?id=closer", queries=kw.pop("queries", []), **kw)

    def version(self, n, current, cid="closer", status="running", cause=None):
        return {"id": cid, "name": "Closer", "version_no": n, "current": current, "status": status,
                "retired": ({"date": "2026-11-01", "cause": cause} if cause else None),
                "record": {"bets": 12, "wins": 6, "losses": 6, "pushes": 0, "voids": 0, "units_recorded_price": 0.4,
                           "units_average_price": 0.2},
                "verdict": {"label": "TOO EARLY", "sentence": "s"}}

    def test_a_hound_with_one_version_and_no_challengers_says_exactly_that(self):
        out = self.page(self.lineage([self.version(1, True)]), queries=[
            q("hidden", "[data-hook='hound-lineage-section']", "hidden"), q("empty", "[data-hook='lineage-empty']"),
            q("note", "[data-hook='referee-note']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertEqual(out["final"]["empty"], "This model has one version and no challengers testing.")
        self.assertIn("never because of what anyone wrote about it", out["final"]["note"])
        self.assertIn("/hounds/closer/lineage", out["gets"])

    def test_versions_each_keep_a_record_and_the_old_one_is_linked(self):
        versions = [self.version(1, False, cid="closer@v1", status="retired", cause="superseded by version 2"),
                    self.version(2, True)]
        out = self.page(self.lineage(versions), queries=[
            q("n", "[data-hook='versions-list'] li", "count"), q("cur", "[data-version='2']", "attr", attr="data-current"),
            q("old", "[data-version='1']"), q("link", "[data-version='1'] [data-hook='version-link']", "attr", attr="href"),
            q("nolink", "[data-version='2'] [data-hook='version-link']", "count")])
        self.assertEqual(out["final"]["n"], 2)
        self.assertEqual(out["final"]["cur"], "true")
        self.assertIn("Retired: superseded by version 2", out["final"]["old"])
        self.assertIn("Its own record: 12 bets (6-6)", out["final"]["old"])
        self.assertIn("closer%40v1", out["final"]["link"])
        self.assertEqual(out["final"]["nolink"], 0)

    def test_a_live_challenger_shows_what_it_changes_the_quoted_reason_and_where_it_stands(self):
        live = [{"id": "c-abc", "status": "live", "hypothesis": "A wider bar keeps only the clearest disagreements.",
                 "spec_diff": {"GAP": [0.02, 0.03]}, "created_utc": "2026-11-05T00:00:00Z", "looks": 1,
                 "latest_look": {"look_no": 1, "n": 100, "mean": 0.8, "lower": -0.2, "upper": 1.8, "eligible": False}}]
        out = self.page(self.lineage([self.version(1, True)], live=live), queries=[
            q("c", "[data-hook='live-challengers'] li"), q("diff", ".hd-challenger__diff"), q("look", ".hd-challenger__look")])
        self.assertIn("Challenger c-abc", out["final"]["c"])
        self.assertEqual(out["final"]["diff"], "What it changes: GAP: 0.02 -> 0.03")
        self.assertIn("The coach's pitch (quoted): \"A wider bar keeps only the clearest disagreements.\"", out["final"]["c"])
        self.assertIn("Look 1, after 100 paired games", out["final"]["look"])
        self.assertNotIn("promoted", out["final"]["look"])

    def test_the_tried_and_failed_list_shows_the_code_written_lesson(self):
        failed = [{"id": "c-old", "status": "retired", "outcome_reason": "harm", "spec_diff": {"GAP": [0.02, 0.04]},
                   "hypothesis": "h", "created_utc": "2026-10-01T00:00:00Z", "looks": 2}]
        rows = [{"lesson_id": "l-c-old", "lesson": "On professor_paws, GAP 0.02 -> 0.04 was retired: it did worse than the champion (100 paired slots, mean CLV difference -1.20 pts)."}]
        out = self.page(self.lineage([self.version(1, True)], failed=failed, lesson_rows=rows), queries=[
            q("f", "[data-hook='failed-challengers'] li")])
        self.assertIn("Challenger c-old retired: harm", out["final"]["f"])
        # the code-written lesson, said in camp's words: cut, the starter, plain numbers
        self.assertIn("was retired: it did worse than the current version", out["final"]["f"])
        self.assertIn("100 paired games, its prices beat the current version's by -1.20 pts on average", out["final"]["f"])

    def test_a_paused_loop_is_said_on_the_hound_page(self):
        out = self.page(self.lineage([self.version(1, True)], paused=True), queries=[q("p", "[data-hook='lineage-paused']")])
        self.assertIn("The learning loop has shut itself down", out["final"]["p"])

    def test_a_missing_lineage_endpoint_does_not_take_the_hound_page_down(self):
        out = self.page(None, queries=[q("s", "[data-hook='hound-lineage'] [data-hook='section-state']", "attr", attr="data-kind"),
                                       q("name", "[data-hook='hound-name']"), q("rule", "[data-hook='rule-text']", "exists"),
                                       q("bets", "[data-hook='bets-table'] tbody tr", "count")])
        self.assertEqual(out["final"]["s"], "missing")
        self.assertTrue(out["final"]["name"])
        self.assertTrue(out["final"]["rule"])
        self.assertGreater(out["final"]["bets"], 0)

    def test_the_real_python_lineage_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tests.test_hounds_learning_views import world_with_promotion
            from src.hounds import stats
            src, scope = world_with_promotion(Path(tmp))
            book = stats.build(src)
            F.propose_raw(scope, cid="c-live", hound_id="charlie", created="2026-10-05T00:00:00Z")
            payload = jsonable(views.lineage_view("charlie", book, scope_map={"house": scope, "user": L.Scope.user(Path(tmp) / "u")}))
        r = {k: list(v) for k, v in WF.routes().items()}
        r["/hounds/closer/lineage"] = [200, payload]
        out = run_page("hound", routes=r, search="?id=closer", queries=[
            q("versions", "[data-hook='versions-list'] li", "count"), q("live", "[data-hook='live-challengers'] li", "count")])
        self.assertEqual(out["final"]["versions"], 2)
        self.assertEqual(out["final"]["live"], 1)


if __name__ == "__main__":
    unittest.main()
