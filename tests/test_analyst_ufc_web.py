"""The UFC analyst on the page: one event's calls and the record table.

Two halves, the pattern of tests/test_analyst_web.py:

  * static checks on web/js/analyst_ufc.js;
  * a behavioural half that runs the real analyst_ufc.js under node against a small fake
    DOM. Skipped when node is missing. It imports nothing from `api.*`.

The module is self-contained and is NOT mounted on any page by this change (the fight-night
page is another worker's); the static checks say what it reads and what it must never do.
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

from tests.test_analyst_web import BANNED, HARNESS as MLB_HARNESS, _string_literals

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
UFC_JS = (JS / "analyst_ufc.js").read_text(encoding="utf-8")
LABEL = "Written by an AI model from the data on this page. Unproven. Analysis, not advice."


class StaticChecks(unittest.TestCase):
    def test_the_label_is_the_shared_one_and_is_not_redefined(self):
        self.assertIn('import { ANALYST_LABEL, callNode } from "./analyst.js";', UFC_JS)
        self.assertNotIn("Unproven. Analysis, not advice", UFC_JS.replace("UNPROVEN", ""))
        self.assertIn(f'"{LABEL}"', (JS / "analyst.js").read_text(encoding="utf-8"))

    def test_no_banned_word_is_in_any_string_the_page_can_show(self):
        offenders = []
        for literal in _string_literals(UFC_JS):
            for pattern, name in BANNED:
                if re.search(pattern, literal):
                    offenders.append(f"{name}: {literal[:70]!r}")
        self.assertEqual(offenders, [])

    def test_it_never_computes_a_rate_of_its_own(self):
        for needle in ("wins /", "losses /", "/ decided", "wins +", "losses +"):
            self.assertNotIn(needle, UFC_JS)

    def test_it_makes_no_model_call_and_reads_one_route_each(self):
        self.assertIn("/analyst/ufc/${encodeURIComponent(eventId)}", UFC_JS)
        self.assertIn('apiGet("/analyst/ufc/record")', UFC_JS)
        self.assertEqual(len(re.findall(r"apiGet\(", UFC_JS)), 2)
        self.assertNotIn("anthropic", UFC_JS.lower())
        self.assertNotIn("fetch(", UFC_JS)

    def test_it_draws_every_call_with_the_shared_call_renderer(self):
        self.assertIn("callNode(call)", UFC_JS)

    def test_it_imports_only_the_shared_modules(self):
        code = re.sub(r"/\*.*?\*/", " ", UFC_JS, flags=re.S)         # the header comment shows a usage example
        imports = re.findall(r'from "(\./[^"]+)"', code)
        self.assertEqual(sorted(imports), ["./analyst.js", "./api.js", "./dom.js"])

    def test_the_section_is_mounted_only_through_the_fight_night_analyst_option(self):
        """2026-10-03 integration: main.js mounts the UFC analyst into the fight-night page's
        bout slots (ufcfights.js's `analyst` option). The page modules themselves still do
        not import it, and the MLB game page and the record page are unchanged."""
        for name in ("games.js", "cardrecord.js"):
            self.assertNotIn("analyst_ufc", (JS / name).read_text(encoding="utf-8"), name)
        ufc_pages = [p for p in JS.glob("*.js") if p.name.startswith("ufc")]
        for page in ufc_pages:
            self.assertNotIn("analyst_ufc", page.read_text(encoding="utf-8"), page.name)
        main = (JS / "main.js").read_text(encoding="utf-8")
        self.assertIn('import { fetchUfcAnalyst, boutNode as ufcAnalystBout } from "./analyst_ufc.js";', main)
        branch = main.split('} else if (sport === "ufc") {')[1].split('} else if (sport === "nba"')[0]
        self.assertIn("analyst: async (slot, ctx) =>", branch)
        self.assertIn("fetchUfcAnalyst(ctx.event.event_id)", branch)

    def test_the_families_are_the_ones_the_grader_counts(self):
        from src.analyst import ufc_grading
        order = re.search(r"UFC_FAMILY_ORDER = \[([^\]]+)\]", UFC_JS).group(1)
        self.assertEqual(re.findall(r'"([a-z_]+)"', order), list(ufc_grading.FAMILIES))
        labels = re.search(r"UFC_FAMILY_LABEL = \{(.*?)\};", UFC_JS, re.S).group(1)
        for family, words in ufc_grading.FAMILY_LABELS.items():
            self.assertIn(f'{family}: "{words}"', labels)

    def test_the_styles_it_needs_are_in_the_analyst_stylesheet(self):
        css = (ROOT / "web" / "css" / "analyst.css").read_text(encoding="utf-8")
        for cls in ("an-ufc-bout", "an-ufc-bout__head", "an-ufc-bout__meta", "an-ufc-bout__result"):
            self.assertIn(f".{cls}", css)
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("css/analyst.css", html)            # already linked: nothing to add to the page


HARNESS = MLB_HARNESS.replace('import("./analyst.js")', 'import("./analyst_ufc.js")').replace(
    'const node = scenario.kind === "record" ? mod.renderAnalystRecord(scenario.data) : mod.renderAnalystSection(scenario.data);',
    'const node = scenario.kind === "record" ? mod.renderUfcAnalystRecord(scenario.data) : mod.renderUfcAnalystEvent(scenario.data);',
).replace(
    '  families: hook("analyst-family").map((n) => n.attrs["data-family"]),',
    '  families: hook("analyst-family").map((n) => n.attrs["data-family"]),\n'
    '  bouts: hook("analyst-ufc-bout").map((b) => ({ id: b.attrs["data-bout"], text: text(b),\n'
    '    head: text(b._all([]).find((x) => x.attrs["data-hook"] === "analyst-ufc-bout-head")),\n'
    '    families: b._all([]).filter((x) => x.attrs["data-hook"] === "analyst-family").map((x) => x.attrs["data-family"]),\n'
    '    calls: b._all([]).filter((x) => x.attrs["data-hook"] === "analyst-call").map((x) => x.attrs["data-slot"]),\n'
    '    summaries: b._all([]).filter((x) => x.attrs["data-hook"] === "analyst-summary").length })),',
)


def call(slot, verdict, family, **extra):
    base = {"slot_id": slot, "market": family, "family": family, "title": "Moneyline",
            "selection": "Ben Brawler", "verdict": verdict, "price": 145, "book": "DraftKings",
            "fair_estimate": 0.45, "confidence": "medium",
            "reasons": [{"claim": "The books make the other fighter the favourite.", "evidence": []},
                        {"claim": "The sample behind the favourite is thin.", "evidence": []}],
            "pass_price": 130, "what_would_change_it": "A late price move.",
            "verification": {"status": "verified", "problems": []}}
    base.update(extra)
    return base


def bout(bout_id="9101", calls=None, **extra):
    base = {"bout_id": bout_id, "event_id": "7013", "date": "2026-10-10", "start_utc": "2026-10-10T23:00:00Z",
            "published_utc": "2026-10-10T16:00:00Z", "model": "m", "version": 1,
            "fighter_a": "Alex Archer", "fighter_b": "Ben Brawler", "weight_class": "Welterweight",
            "scheduled_rounds": 5, "card_segment": "main", "match_number": 1,
            "summary": "First paragraph of the argument.\n\nSecond paragraph.", "summary_status": "ok",
            "calls": calls if calls is not None else [call("moneyline", "TAKE_OTHER_SIDE", "moneyline")],
            "final": None, "result_text": None, "graded": False}
    base.update(extra)
    return base


def event(bouts, **extra):
    analysis = {"event_id": "7013", "event_name": "Synthetic Championship Night", "date": "2026-10-10",
                "bouts": bouts}
    analysis.update(extra)
    return {"available": True, "label": LABEL, "analysis": analysis, "reason": None}


def family(taken=0, passes=0, graded=0, wins=0, losses=0, pushes=0, voids=0, rate=None, units=None,
           reason="fewer than 30 graded calls (0 so far)"):
    return {"taken": taken, "taken_other_side": 0, "passes": passes, "graded": graded, "wins": wins,
            "losses": losses, "pushes": pushes, "voids": voids, "unresolved": 0, "win_rate": rate,
            "units": units, "withheld_reason": None if rate is not None else reason}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheUfcAnalystRendersUnderNode(unittest.TestCase):
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

    def render(self, kind, data):
        env = dict(os.environ, SCENARIO=json.dumps({"kind": kind, "data": data}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- the event section -----------------------------------------------

    def test_the_label_is_the_first_thing_under_the_heading_once(self):
        out = self.render("section", event([bout(), bout("9102")]))
        self.assertEqual(out["firstParagraph"], LABEL)
        self.assertEqual(out["labelCount"], 1)
        self.assertIn("AI ANALYST", out["text"])
        self.assertIn("Synthetic Championship Night", out["text"])

    def test_every_bout_is_a_block_in_the_order_the_server_sent(self):
        out = self.render("section", event([bout("9101"), bout("9102", fighter_a="Dan Silva",
                                                              fighter_b="Eli Silva", card_segment="prelims",
                                                              weight_class="Welterweight", match_number=5)]))
        self.assertEqual([b["id"] for b in out["bouts"]], ["9101", "9102"])
        self.assertEqual([b["head"] for b in out["bouts"]], ["Alex Archer vs Ben Brawler", "Dan Silva vs Eli Silva"])
        self.assertIn("Welterweight · Main card · 5 rounds", out["bouts"][0]["text"])
        self.assertIn("Welterweight · Prelims · 5 rounds", out["bouts"][1]["text"])

    def test_the_summary_is_shown_as_paragraphs_before_the_calls(self):
        out = self.render("section", event([bout()]))
        self.assertIn("First paragraph of the argument.", out["text"])
        self.assertIn("Second paragraph.", out["text"])
        self.assertLess(out["hooks"].index("analyst-summary"), out["hooks"].index("analyst-call"))
        self.assertEqual(out["bouts"][0]["summaries"], 2)

    def test_calls_are_grouped_by_market_in_a_fixed_order_inside_each_bout(self):
        calls = [call("method_a_ko", "PASS", "method", title="Method of victory", selection="Alex Archer by KO/TKO/DQ"),
                 call("rounds_total", "PASS", "rounds_total", title="Rounds total", selection="Over 4.5"),
                 call("moneyline", "TAKE_OTHER_SIDE", "moneyline"),
                 call("method_b_dec", "PASS", "method", title="Method of victory", selection="Ben Brawler by decision")]
        out = self.render("section", event([bout(calls=calls)]))
        self.assertEqual(out["bouts"][0]["families"], ["moneyline", "method", "rounds_total"])
        self.assertEqual(out["bouts"][0]["calls"], ["moneyline", "method_a_ko", "method_b_dec", "rounds_total"])
        for words in ("Moneyline", "Method of victory", "Rounds total"):
            self.assertIn(words, out["text"])
        self.assertIn("Method of victory: Alex Archer by KO/TKO/DQ", out["text"])

    def test_a_pass_is_drawn_exactly_as_plainly_as_a_take(self):
        out = self.render("section", event([bout(calls=[
            call("moneyline", "TAKE", "moneyline"),
            call("rounds_total", "TAKE_OTHER_SIDE", "rounds_total", title="Rounds total"),
            call("method_a_ko", "PASS", "method", title="Method of victory")])]))
        # calls are grouped by market (moneyline, method, rounds total), not in the order sent
        self.assertEqual([c["verdictWord"] for c in out["calls"]], ["Take", "Pass", "Take the other side"])
        for c in out["calls"]:
            self.assertTrue(c["cls"].startswith("an-call "))
            self.assertEqual(c["verdictCls"], "an-call__verdict")
            self.assertEqual(len(c["reasons"]), 2)
            self.assertTrue(c["hasPassPrice"])
            self.assertIn("145 at DraftKings", c["price"].replace("+", ""))
        self.assertIn("Would start to take it at +130", out["calls"][1]["text"])

    def test_a_struck_call_reads_as_a_pass_that_could_not_be_verified(self):
        struck = call("moneyline", "PASS", "moneyline", fair_estimate=None, confidence="low", pass_price=None,
                      what_would_change_it="A call that can be checked against the data.",
                      reasons=[{"claim": "Could not be verified.", "evidence": []}],
                      verification={"status": "could not be verified", "problems": []})
        out = self.render("section", event([bout(calls=[struck])]))
        c = out["calls"][0]
        self.assertEqual(c["verdictWord"], "Pass")
        self.assertIn("Could not be verified.", c["reasons"])
        self.assertFalse(c["hasPassPrice"])
        self.assertNotIn("What would change it", c["text"])

    def test_results_and_what_a_pass_would_have_done_are_shown_with_the_result_in_words(self):
        calls = [call("moneyline", "TAKE_OTHER_SIDE", "moneyline", result="WIN"),
                 call("rounds_total", "TAKE", "rounds_total", result="PUSH"),
                 call("method_a_ko", "PASS", "method", result="PASS", would_have={"result": "LOSS", "price": 280}),
                 call("method_b_ko", "TAKE", "method", result="VOID"),
                 call("method_a_sub", "TAKE", "method", result="LOSS")]
        out = self.render("section", event([bout(calls=calls, graded=True,
                                                 result_text="Ben Brawler won by KO/TKO in round 2.")]))
        self.assertEqual([c["result"] for c in out["calls"]],       # grouped: moneyline, method x3, total
                         ["Won", "The side passed on lost.", "Void", "Lost", "Push"])
        self.assertIn("Ben Brawler won by KO/TKO in round 2.", out["text"])
        self.assertIn("analyst-ufc-result", out["hooks"])

    def test_an_unverifiable_summary_is_withheld_with_a_plain_notice_per_bout(self):
        out = self.render("section", event([bout(summary=None, summary_status="withheld")]))
        self.assertIn("could not be verified against the data, so it is not shown", out["text"])
        self.assertNotIn("First paragraph", out["text"])
        self.assertEqual(len(out["calls"]), 1)

    def test_an_event_with_no_analysis_says_so_and_still_carries_the_label(self):
        out = self.render("section", {"available": False, "label": LABEL, "analysis": None,
                                      "reason": "No analysis has been published for this event."})
        self.assertEqual(out["firstParagraph"], LABEL)
        self.assertIn("No analysis has been published for this event.", out["text"])
        self.assertEqual(out["bouts"], [])

    def test_an_available_event_with_no_bouts_says_so_too(self):
        out = self.render("section", event([]))
        self.assertIn("No analysis has been published for this event.", out["text"])

    def test_a_missing_price_is_said_not_blanked(self):
        out = self.render("section", event([bout(calls=[call("moneyline", "PASS", "moneyline", price=None, book=None)])]))
        self.assertIn("No price named", out["calls"][0]["price"])

    def test_an_unnamed_family_is_still_shown_after_the_known_ones(self):
        out = self.render("section", event([bout(calls=[call("x", "PASS", "other"), call("moneyline", "PASS", "moneyline")])]))
        self.assertEqual(out["bouts"][0]["families"], ["moneyline", "other"])

    # ---- the record ------------------------------------------------------

    def record(self, **fams):
        base = {name: family() for name in ("moneyline", "method", "rounds_total")}
        base.update(fams)
        return {"label": LABEL, "min_graded": 30, "bouts_published": 12, "bouts_settled": 9,
                "families": base, "recent": []}

    def test_under_thirty_graded_calls_no_rate_and_no_units_are_printed(self):
        out = self.render("record", self.record(
            method=family(taken=14, passes=5, graded=14, wins=9, losses=5,
                          reason="fewer than 30 graded calls (14 so far)")))
        row = next(r for r in out["rows"] if r["family"] == "method")
        self.assertTrue(row["withheld"])
        self.assertFalse(row["hasRate"])
        self.assertIn("fewer than 30 graded calls (14 so far)", " ".join(row["cells"]))
        self.assertEqual(row["cells"][1:5], ["14", "5", "14", "9-5-0"])
        self.assertNotRegex(" ".join(row["cells"]), r"%|u$|[+]\d")

    def test_at_thirty_the_server_sends_a_rate_and_units_and_they_are_printed(self):
        out = self.render("record", self.record(
            moneyline=family(taken=30, graded=30, wins=18, losses=12, rate=0.6, units=2.31)))
        row = next(r for r in out["rows"] if r["family"] == "moneyline")
        self.assertTrue(row["hasRate"])
        self.assertIn("60.0%", row["cells"])
        self.assertIn("+2.31u", row["cells"])
        other = next(r for r in out["rows"] if r["family"] == "rounds_total")
        self.assertTrue(other["withheld"])                 # one family's rate never lifts another

    def test_every_family_has_a_row_and_the_label_leads(self):
        out = self.render("record", self.record())
        self.assertEqual([r["family"] for r in out["rows"]], ["moneyline", "method", "rounds_total"])
        self.assertEqual(out["firstParagraph"], LABEL)
        self.assertIn("kept apart from the card record and from the MLB analyst record", out["text"])
        self.assertIn("after it has 30 graded calls", out["text"])
        self.assertIn("UFC AI ANALYST RECORD", out["text"])

    def test_recent_graded_calls_are_listed_with_their_results(self):
        data = self.record()
        data["recent"] = [{"date": "2026-10-10", "fighter_a": "Alex Archer", "fighter_b": "Ben Brawler",
                           "family": "moneyline", "selection": "Ben Brawler", "verdict": "TAKE_OTHER_SIDE",
                           "price": 145, "result": "WIN"},
                          {"date": "2026-10-10", "fighter_a": "Dan Silva", "fighter_b": "Eli Silva",
                           "family": "rounds_total", "selection": "Under 2.5", "verdict": "TAKE",
                           "price": -110, "result": "PUSH"}]
        out = self.render("record", data)
        self.assertIn("2026-10-10: Alex Archer vs Ben Brawler, Ben Brawler at +145 — Won", out["text"])
        self.assertIn("2026-10-10: Dan Silva vs Eli Silva, Under 2.5 at -110 — Push", out["text"])


if __name__ == "__main__":
    unittest.main()
