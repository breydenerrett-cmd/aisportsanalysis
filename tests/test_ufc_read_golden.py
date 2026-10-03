"""The golden reads: src/analysis/ufc_read.py on a store built from REAL fixture rows.

tests/fixtures/ufc_read_golden.json holds, for three cases, the fact sheet and the read built from it
(scripts/regen_ufc_read_fixtures.py writes it):

  * Vettori v Naurdiev, a real upcoming bout on UFC 332, from the saved ESPN responses: real records, physical
    attributes and DraftKings prices, and no earlier fights in the fixtures, so the read has almost nothing to
    weigh and says so;
  * Rosas Jr. v Barcelos, the real 2026-09-26 main event as it stands afterwards: one fight each on file, with
    real statistics and a real result, so one fight is an anecdote and nothing is read from it, but the
    previous meeting, the last fight and the thin sample are all stated;
  * the data layer's synthetic world, where every rule has something to say.

Three questions, three failures:

  1. does the read module still make the same read from the same sheet (wording or logic changed);
  2. does the data layer still build the same sheet from the same rows (the data layer changed);
  3. are the real facts the read states the real facts (so a blind regeneration cannot bless nonsense).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.analysis import ufc_read
from tests.test_ufc_read import BANNED, SNAKE, evidence_entries, prose

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "ufc_read_golden.json"
REGEN = "python3 scripts/regen_ufc_read_fixtures.py"


def frozen():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


class TheReadIsStable(unittest.TestCase):
    def test_each_read_is_what_the_module_makes_of_the_frozen_sheet(self):
        for name, case in frozen().items():
            with self.subTest(case=name):
                self.assertEqual(ufc_read.build_read(case["sheet"]), case["read"],
                                 f"the read for {name} changed; if on purpose, review the diff and run {REGEN}")

    def test_the_frozen_sheets_are_what_the_data_layer_still_builds(self):
        from scripts.regen_ufc_read_fixtures import build_sheets
        built = build_sheets()
        cases = frozen()
        self.assertEqual(set(built), set(cases))
        for name, sheet in built.items():
            with self.subTest(case=name):
                self.assertEqual(json.loads(json.dumps(sheet)), cases[name]["sheet"],
                                 f"the sheet for {name} changed (the data layer, not the read); run {REGEN} after reviewing it")

    def test_three_cases_and_a_read_that_is_not_empty(self):
        cases = frozen()
        self.assertEqual(set(cases), {"vettori_v_naurdiev_upcoming", "rosas_v_barcelos_afterwards", "synthetic_main_event"})
        for case in cases.values():
            self.assertTrue(case["read"]["headline"])
            self.assertGreater(len(json.dumps(case["read"])), 3000)


class TheRealFactsAreTheRealFacts(unittest.TestCase):
    """Said in words the fixtures can be checked against: the ESPN responses saved under tests/fixtures/espn_mma."""

    @classmethod
    def setUpClass(cls):
        cls.cases = frozen()

    def test_vettori_v_naurdiev_has_the_real_records_and_the_real_price(self):
        read = self.cases["vettori_v_naurdiev_upcoming"]["read"]
        sheet = self.cases["vettori_v_naurdiev_upcoming"]["sheet"]
        self.assertEqual((read["a"]["name"], read["b"]["name"]), ("Marvin Vettori", "Ismail Naurdiev"))
        self.assertEqual(sheet["bout"]["bout_id"], "401912275")
        self.assertEqual(sheet["bout"]["weight_class"], "Middleweight")
        a_record = [c["sentence"] for c in read["a"]["context"] if c["key"] == "overall_record"][0]
        b_record = [c["sentence"] for c in read["b"]["context"] if c["key"] == "overall_record"][0]
        self.assertIn("shows 19-10-1 overall, 30 professional fights", a_record)
        self.assertIn("shows 25-8-0 overall, 33 professional fights", b_record)
        market = read["market_view"]
        self.assertEqual(market["implied"]["a"]["american"], 114)
        self.assertEqual(market["implied"]["b"]["american"], -135)
        self.assertEqual(market["favourite"], "b")
        self.assertIn("Ismail Naurdiev the 55.1% favourite and Marvin Vettori 44.9%", market["sentences"][0])
        self.assertIn("(Marvin Vettori +114, Ismail Naurdiev -135, fetched 2026-10-03)", market["sentences"][0])
        self.assertTrue([s for s in market["sentences"] if s.startswith("The rounds line is 2.5")])

    def test_vettori_v_naurdiev_says_there_is_nothing_to_weigh_and_the_price_is_better_informed(self):
        read = self.cases["vettori_v_naurdiev_upcoming"]["read"]
        self.assertEqual(read["data_depth"]["level"], "thin")
        self.assertEqual((read["data_depth"]["a"]["fights"], read["data_depth"]["b"]["fights"]), (0, 0))
        self.assertIn("No UFC fights are on file for Marvin Vettori and Ismail Naurdiev.", read["headline"])
        self.assertEqual(read["a"]["strengths"] + read["a"]["weaknesses"] + read["b"]["strengths"] + read["b"]["weaknesses"], [])
        self.assertIn("With this little on file, the price is more likely right than this read.",
                      read["market_view"]["sentences"])

    def test_rosas_v_barcelos_is_one_real_fight_each_and_it_is_not_over_read(self):
        read = self.cases["rosas_v_barcelos_afterwards"]["read"]
        self.assertEqual((read["data_depth"]["a"]["fights"], read["data_depth"]["b"]["fights"]), (1, 1))
        self.assertEqual(read["a"]["strengths"] + read["a"]["weaknesses"] + read["b"]["strengths"] + read["b"]["weaknesses"], [],
                         "a single fight is an anecdote: no strength or weakness may be read from it")
        self.assertIn("Little is on file for Raul Rosas Jr. and Raoni Barcelos.", read["headline"])
        self.assertEqual(read["history"]["previous_meetings"][0]["sentence"],
                         "Raul Rosas Jr. won by knockout or TKO on 2026-09-27, in round 5.")
        last_a = [c["sentence"] for c in read["a"]["context"] if c["key"] == "last_fights"][0]
        last_b = [c["sentence"] for c in read["b"]["context"] if c["key"] == "last_fights"][0]
        self.assertEqual(last_a, "Raul Rosas Jr.'s last fight on file: beat Raoni Barcelos by knockout or TKO on 2026-09-27, round 5.")
        self.assertEqual(last_b, "Raoni Barcelos' last fight on file: lost to Raul Rosas Jr. by knockout or TKO on 2026-09-27, round 5.")

    def test_the_synthetic_main_event_exercises_the_rules(self):
        read = self.cases["synthetic_main_event"]["read"]
        traits = {kind: {i["trait"] for s in ("a", "b") for i in read[s][kind]} for kind in ("strengths", "weaknesses")}
        for expected in ("striking_defence", "takedown_open", "reach", "submission_threat", "results"):
            self.assertIn(expected, traits["strengths"] | traits["weaknesses"])
        self.assertEqual(read["market_view"]["agreement"], "disagrees")
        self.assertTrue(read["history"]["shared_opponents"])
        self.assertEqual(read["history"]["previous_meetings"][0]["sentence"],
                         "Ben Brawler won by unanimous decision on 2026-03-14, in round 5.")


class TheGoldenReadsPassTheSweeps(unittest.TestCase):
    def test_every_evidence_path_resolves_against_its_own_sheet(self):
        total = 0
        for name, case in frozen().items():
            for entry in evidence_entries(case["read"]):
                found, value = ufc_read.resolve_path(case["sheet"], entry["path"])
                self.assertTrue(found, (name, entry))
                if not entry.get("derived"):
                    self.assertEqual(value, entry["value"], (name, entry["path"]))
                total += 1
        self.assertGreater(total, 100)

    def test_no_pick_no_lock_no_profit_no_dash_no_field_name(self):
        for name, case in frozen().items():
            for text in prose(case["read"]):
                self.assertNotIn("—", text)
                self.assertNotIn("–", text)
                self.assertEqual(SNAKE.findall(text), [], (name, text))
                for pattern, label in BANNED:
                    self.assertIsNone(re.search(pattern, text, re.I), f"{name}: {label!r} in {text!r}")


if __name__ == "__main__":
    unittest.main()
