"""scripts/analyst_consistency.py: the slot-by-slot comparison of several answers to one request.

It is a diagnostic over answers only, so these tests pin what it reads (calls, never a game result),
what it flags, and the preserved 2026-10-04 Braves-at-Dodgers folder it was written for: one slot,
prop_01, where an answer bets and another passes, and thirteen where all three agree.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "analyst_consistency.py"
FOLDER = ROOT / "evidence" / "analyst_consistency" / "2026-10-04_ATL-LAD"

_spec = importlib.util.spec_from_file_location("analyst_consistency", SCRIPT)
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)


def call(slot, verdict="PASS", selection="Over 6.5", price=-110, book="b", fair=None):
    return {"slot_id": slot, "verdict": verdict, "selection": selection, "price": price, "book": book,
            "fair_estimate": fair}


class Flags(unittest.TestCase):
    def one(self, *calls):
        return ac.flags([None if c is None else {k: c[k] for k in ("verdict", "selection", "price", "book",
                                                                     "fair_estimate")} for c in calls])

    def test_identical_calls_are_not_flagged(self):
        self.assertEqual(self.one(call("s"), call("s")), [])

    def test_a_bet_against_a_pass_is_an_action_disagreement(self):
        out = self.one(call("s", "TAKE_OTHER_SIDE", "Under 6.5", 120, "dk", 0.52), call("s"))
        self.assertTrue(any(f.startswith("ACTION") for f in out), out)

    def test_two_bets_on_opposite_sides_are_flagged_as_sides(self):
        out = self.one(call("s", "TAKE", "Over 6.5"), call("s", "TAKE_OTHER_SIDE", "Under 6.5"))
        self.assertTrue(any(f.startswith("SIDE") for f in out), out)

    def test_estimates_far_apart_are_flagged_and_close_ones_are_not(self):
        self.assertTrue(any(f.startswith("FAIR") for f in self.one(call("s", fair=0.50), call("s", fair=0.56))))
        self.assertEqual(self.one(call("s", fair=0.50), call("s", fair=0.52)), [])

    def test_a_missing_estimate_is_not_a_disagreement(self):
        self.assertEqual(self.one(call("s", fair=0.5), call("s", fair=None)), [])

    def test_prices_for_different_selections_are_not_compared(self):
        out = self.one(call("s", selection="Over 6.5", price=-120), call("s", selection="Under 6.5", price=120))
        self.assertNotIn("PRICE/BOOK", out)

    def test_one_answer_alone_has_nothing_to_disagree_with(self):
        self.assertEqual(self.one(call("s"), None), [])


class OnThePreservedFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.answers = ac.load_answers([str(FOLDER)])
        cls.rows = ac.table(cls.answers)

    def test_three_answers_load_in_the_order_they_were_written_with_the_partial_one_marked(self):
        self.assertEqual([ac.label(a) for a in self.answers],
                         ["attempt1_transcript_record (partial)", "attempt2_published_answer",
                          "sample3_unpublished_answer"])

    def test_all_fourteen_slots_are_compared(self):
        self.assertEqual(len(self.rows), 14)
        self.assertEqual(self.rows[0][0], "moneyline")

    def test_only_prop_01_is_an_action_disagreement(self):
        flagged = {slot: flag for slot, _, flag in self.rows if flag}
        self.assertEqual(list(flagged), ["prop_01"])
        self.assertTrue(any(f.startswith("ACTION") for f in flagged["prop_01"]))

    def test_prop_01_has_the_calls_the_record_says(self):
        calls = dict((slot, c) for slot, c, _ in self.rows)["prop_01"]
        self.assertEqual([(c["verdict"], c["selection"], c["price"], c["book"]) for c in calls],
                         [("TAKE_OTHER_SIDE", "Under 6.5", 120, "draftkings"),
                          ("PASS", "Over 6.5", -120, "fanduel"),
                          ("TAKE_OTHER_SIDE", "Under 6.5", 120, "draftkings")])
        self.assertEqual(calls[0]["fair_estimate"], 0.52)
        self.assertEqual(calls[2]["fair_estimate"], 0.52)
        self.assertIsNone(calls[1]["fair_estimate"])

    def test_the_report_is_a_markdown_table_with_one_row_per_slot(self):
        text = ac.markdown(self.answers, self.rows)
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 2 + 14)
        self.assertTrue(lines[0].startswith("| slot |"))
        self.assertIn("ACTION", [l for l in lines if l.startswith("| prop_01")][0])

    def test_main_prints_and_writes_the_report_and_needs_two_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "r.md"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(ac.main([str(FOLDER), "--report", str(report)]), 0)
            self.assertIn("14 slots, 1 with a disagreement", buffer.getvalue())
            self.assertTrue(report.read_text(encoding="utf-8").startswith("| slot |"))
            (Path(tmp) / "one.json").write_text(json.dumps({"calls": [call("s")]}), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(ac.main([str(Path(tmp) / "one.json")]), 2)


class ItStaysADiagnostic(unittest.TestCase):
    def test_it_imports_only_the_standard_library(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertLessEqual(names, {"__future__", "argparse", "json", "re", "sys", "pathlib", "typing"})

    def test_it_never_reads_a_game_result(self):
        source = SCRIPT.read_text(encoding="utf-8").lower()
        for word in ("final_score", "away_score", "home_score", "boxscore", "grading"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
