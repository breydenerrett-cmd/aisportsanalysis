"""The admin page's "Jarvis briefing" tab (web/admin.html, web/js/admin-jarvis.js), run for real under node against the page's own HTML
(tests/hounds_web_harness.mjs), with a briefing in the shape src/jarvis/brief.py saves and api/jarvis.py serves
(GET /admin/jarvis/brief?date=YYYY-MM-DD, admin token in a header).

What it pins: the tab reads the briefing only when it is opened (the other tabs' fetches are unchanged); every pick shows pick, best and average price,
max acceptable price, probability against break-even, the estimated EV, confidence, the EXPERIMENTAL label, its reasons and how it could lose; the parlays
show their legs; times are the viewer's zone (no raw [[w:...]] token reaches the page); a date with no briefing says so (404 is not a failure); a small
slate says it is small; the 21+ / 1-800-GAMBLER line stays; and the copy never says dog, beta, new, a guarantee or a profit claim.
"""

from __future__ import annotations

import re
import unittest

from tests import admin_dashboard_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_admin_dashboard import ADMIN_TOKEN, NOW, STORED, all_unauthorized, go, q, routes

BRIEF_PATH = "/admin/jarvis/brief"


def pick(rank, label_text, game, best, avg, mx, prob, be, ev, **over):
    base = {
        "rank": rank, "kind": "single", "label_text": label_text, "game": game, "first_pitch": "[[w:2026-10-19T23:05:00Z]]",
        "best_price": best, "best_book": "Book A", "average_price": avg, "max_acceptable_price": mx,
        "probability": prob, "break_even": be, "expected_value": ev, "confidence": "medium", "confidence_why": "Two books agree within 5 cents.",
        "label": "EXPERIMENTAL", "captured": "[[w:2026-10-19T13:40:00Z]]",
        "reasons": ["Both starters are confirmed.", "The stored model and the market fair price are close."],
        "could_lose": ["The probability is EXPERIMENTAL: this source has not been shown to be calibrated.", "A late scratch moves the price."],
        "avoid": ["Skip it if the lineup posts without him."],
    }
    base.update(over)
    return base


def brief(**over):
    leg1 = pick(0, "Boston Red Sox to win", "Boston Red Sox at Toronto Blue Jays", 120, 112, 108, 0.4821, 0.4545, 0.0607)
    leg2 = pick(0, "Over 8.5 Seattle Mariners at Texas Rangers", "Seattle Mariners at Texas Rangers", -105, -108, -113, 0.5400, 0.5122, 0.0546)
    body = {
        "schema": "jarvis.brief.v1", "date": "2026-10-19", "sport": "mlb", "as_of": "2026-10-19T14:00:00Z", "generated_utc": "2026-10-19T14:01:00Z",
        "paper_only": True,
        "disclaimer": "Paper bets only. This is an estimate-based briefing, not advice and not a promise of any result. "
                      "21+. If gambling stops being fun, call 1-800-GAMBLER (1-800-426-2537).",
        "rules": ["Nothing shorter than -199 is ever offered, as a pick, a parlay leg or a maximum acceptable price."],
        "singles": [leg1, dict(leg2, rank=2)],
        "parlays": [{
            "rank": 1, "kind": "parlay", "legs": [leg1, leg2], "label_text": "Boston Red Sox to win + Over 8.5 Seattle Mariners at Texas Rangers",
            "best_price": 276, "max_acceptable_price": 262, "probability": 0.2603, "break_even": 0.2660, "expected_value": 0.0012,
            "confidence": "low", "label": "EXPERIMENTAL",
            "reasons": ["Both legs cleared the bar on their own."], "could_lose": ["A parlay loses if either leg loses."], "avoid": ["Do not swap in a different line."]}],
        "parlay_note": None, "vanished_edges": [], "excluded": {},
        "inputs": {"games_on_board": 15, "selections_evaluated": 120, "eligible": 2}, "status": "ok",
    }
    body.update(over)
    return body


def run(**scenario):
    scenario.setdefault("now", NOW.isoformat())
    scenario.setdefault("routes", routes())
    scenario.setdefault("stored", dict(STORED))
    return run_page("admin", **scenario)


OPEN = [go("jarvis")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheJarvisTab(unittest.TestCase):
    def test_nothing_is_fetched_until_the_tab_is_opened_then_the_day_is_asked_for_with_the_token_in_a_header(self):
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}))
        self.assertFalse([g for g in out["gets"] if "jarvis" in g], out["gets"])
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}), actions=OPEN)
        calls = [c for c in out["getCalls"] if "jarvis" in c["url"]]
        self.assertEqual([c["url"] for c in calls], [f"{BRIEF_PATH}?date=2026-10-19"])
        self.assertEqual(calls[0]["headers"].get("X-Admin-Token"), ADMIN_TOKEN)
        self.assertNotIn(ADMIN_TOKEN, calls[0]["url"])

    def test_each_pick_shows_price_probability_ev_confidence_label_reasons_and_how_it_could_lose(self):
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}), actions=OPEN, queries=[
            q("titles", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-title']", "texts"),
            q("best", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-best']", "texts"),
            q("avg", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-avg']", "texts"),
            q("max", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-max']", "texts"),
            q("prob", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-prob']", "texts"),
            q("ev", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-ev']", "texts"),
            q("conf", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-confidence']", "texts"),
            q("label", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-label']", "texts"),
            q("reasons", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-reasons'] li", "texts"),
            q("lose", "[data-hook='admin-jarvis-pick'] [data-hook='admin-jarvis-lose'] li", "texts"),
        ])
        f = out["final"]
        self.assertEqual(f["titles"][0], "Boston Red Sox to win")
        self.assertEqual(f["best"][0], "+120 (Book A)")
        self.assertEqual(f["avg"][0], "+112")
        self.assertEqual(f["max"][0], "+108")
        self.assertEqual(f["prob"][0], "48.2% vs 45.5%")
        self.assertEqual(f["ev"][0], "+6.1%")
        self.assertEqual(f["best"][1], "-105 (Book A)")
        self.assertEqual(f["conf"][0], "Confidence: medium")
        self.assertEqual(f["label"], ["EXPERIMENTAL", "EXPERIMENTAL"])
        self.assertIn("Both starters are confirmed.", f["reasons"])
        self.assertTrue(any("has not been shown to be calibrated" in t for t in f["lose"]))

    def test_the_parlay_lists_its_legs_and_says_experimental(self):
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}), actions=OPEN, queries=[
            q("legs", "[data-hook='admin-jarvis-leg']", "texts"),
            q("best", "[data-hook='admin-jarvis-parlay'] [data-hook='admin-jarvis-best']"),
            q("prob", "[data-hook='admin-jarvis-parlay'] [data-hook='admin-jarvis-prob']"),
            q("label", "[data-hook='admin-jarvis-parlay'] [data-hook='admin-jarvis-label']"),
        ])
        f = out["final"]
        self.assertEqual(len(f["legs"]), 2)
        self.assertIn("Boston Red Sox to win", f["legs"][0])
        self.assertEqual(f["best"], "+276")
        self.assertEqual(f["prob"], "26.0% vs 26.6%")
        self.assertEqual(f["label"], "EXPERIMENTAL")

    def test_times_are_the_viewers_zone_and_no_raw_token_reaches_the_page(self):
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}), actions=OPEN, tz="America/Los_Angeles")
        self.assertNotIn("[[w:", out["text"])
        self.assertRegex(out["text"], r"Mon \d{1,2}:\d{2} (PM|AM) PT")

    def test_a_small_slate_says_it_is_small_and_an_estimate_is_not_an_edge(self):
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}), actions=OPEN, queries=[q("n", "[data-hook='admin-jarvis-sample']")])
        self.assertIn("Small sample: 2 singles and 1 parlay from 120 priced selections on 15 games.", out["final"]["n"])
        self.assertIn("not a demonstrated edge", out["final"]["n"])

    def test_a_date_with_no_briefing_says_so_and_is_not_an_error(self):
        out = run(routes=routes(), actions=OPEN, queries=[
            q("status", "[data-hook='admin-jarvis-status']"), q("picks", "[data-hook='admin-jarvis-pick']", "count"),
            q("shell", "[data-hook='admin-shell']", "hidden")])
        self.assertIn("No briefing has been built for 2026-10-19 yet", out["final"]["status"])
        self.assertEqual((out["final"]["picks"], out["final"]["shell"]), (0, False))

    def test_a_board_with_nothing_over_the_bar_says_nothing_cleared_not_a_verdict_about_games(self):
        empty = brief(singles=[], parlays=[], status="nothing_cleared", parlay_note="no parlay: fewer than two legs cleared the bar")
        out = run(routes=routes(**{BRIEF_PATH: [200, empty]}), actions=OPEN, queries=[
            q("none", "[data-hook='admin-jarvis-no-picks']"), q("par", "[data-hook='admin-jarvis-no-parlays']")])
        self.assertEqual(out["final"]["none"], "Jarvis made no picks from this board.")
        self.assertIn("no parlay", out["final"]["par"])

    def test_a_401_returns_to_the_sign_in_card_and_leaves_no_briefing_on_the_page(self):
        table = routes(**{BRIEF_PATH: [401, {"detail": {"error": "unauthorized"}}]})
        out = run(routes=table, actions=OPEN, queries=[q("gate", "[data-hook='admin-gate']", "hidden"),
                                                       q("chip", "[data-hook='admin-token-chip']"), q("picks", "[data-hook='admin-jarvis-pick']", "count")])
        self.assertFalse(out["final"]["gate"])
        self.assertEqual((out["final"]["chip"], out["final"]["picks"]), ("Token rejected", 0))
        self.assertNotIn("admin_token", "".join(out["storedAfter"]))

    def test_a_server_error_is_shown_as_an_error_with_its_code(self):
        out = run(routes=routes(**{BRIEF_PATH: [500, {"detail": "boom"}]}), actions=OPEN, queries=[q("s", "[data-hook='admin-jarvis-status']")])
        self.assertIn("could not be loaded (500)", out["final"]["s"])

    def test_the_21_plus_and_1_800_gambler_lines_stay_and_the_copy_stays_clean(self):
        out = run(routes=routes(**{BRIEF_PATH: [200, brief()]}), actions=OPEN, queries=[
            q("d", "[data-hook='admin-jarvis-disclaimer']"), q("foot", "[data-hook='not-advice']"), q("view", "[data-hook='admin-view-jarvis']")])
        self.assertIn("21+", out["final"]["d"])
        self.assertIn("1-800-GAMBLER", out["final"]["d"])
        self.assertIn("1-800-GAMBLER", out["final"]["foot"])
        shown = out["final"]["view"]
        for bad in (r"\bdogs?\b", r"\bbeta\b", r"\bnew\b", r"\bguarantee", r"\bprofit", r"\block\b"):
            self.assertIsNone(re.search(bad, shown, re.I), bad)


class ThePageSource(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "admin.html").read_text(encoding="utf-8")

    def test_the_tab_and_its_view_are_in_the_page_and_the_page_still_has_one_script(self):
        self.assertIn('data-route="jarvis"', self.html)
        self.assertIn('data-hook="admin-view-jarvis"', self.html)
        self.assertIn('data-hook="admin-host-jarvis"', self.html)
        self.assertEqual(len(re.findall(r"<script\b", self.html)), 1)
        self.assertIn("1-800-GAMBLER", self.html)

    def test_the_tab_has_its_own_module_and_no_hex_colours_of_its_own(self):
        css = (WEB / "css" / "admin.css").read_text(encoding="utf-8")
        self.assertIn(".adm-jv__facts", css)
        self.assertTrue((WEB / "js" / "admin-jarvis.js").is_file())


if __name__ == "__main__":
    unittest.main()
