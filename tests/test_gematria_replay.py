"""research/rabbitszn: the ledger's shape, the replay's arithmetic, and that the replay is labelled in-sample.

The replay itself reads the real stores and facts (a diagnostic, not a unit), so only its pure parts are run here, on synthetic rows.
"""

import csv
import importlib.util
import unittest
from pathlib import Path

from src.hounds.gematria import facts as facts_mod

ROOT = Path(__file__).resolve().parents[1]
RAB = ROOT / "research" / "rabbitszn"
spec = importlib.util.spec_from_file_location("rabbit_replay", RAB / "replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class LedgerShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = list(csv.DictReader((RAB / "ledger.csv").open(encoding="utf-8")))

    def test_one_row_per_distinct_pick_with_the_documented_columns(self):
        ids = [r["pick_id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 60)
        for col in ("post_date", "sport", "selection", "market", "price_selected", "confidence_text", "headline_claim", "support_bullets",
                    "warn_bullets", "timestamp_status", "result", "result_source"):
            self.assertIn(col, self.rows[0])

    def test_the_three_losses_and_the_broncos_win_are_in_it(self):
        by = {(r["post_date"], r["selection"]): r for r in self.rows}
        self.assertEqual(by[("2026-10-20", "Boston Celtics")]["result"], "LOSS")
        self.assertEqual(by[("2026-10-17", "Cincinnati")]["result"], "LOSS")
        self.assertEqual(by[("2026-10-16", "Coastal Carolina")]["result"], "LOSS")
        self.assertEqual(by[("2026-10-15", "Denver Broncos")]["result"], "WIN")

    def test_every_timestamp_is_marked_unauthenticated(self):
        for r in self.rows:
            self.assertIn("not authenticated", r["timestamp_status"].lower(), r["pick_id"])

    def test_a_pick_at_minus_200_or_worse_is_flagged_so_the_hound_never_copies_it(self):
        for r in self.rows:
            if r["market"] == "ML" and r["price_selected"] and int(r["price_selected"]) <= -200:
                self.assertIn("-200 OR WORSE", r["notes"], r["pick_id"])

    def test_a_graded_row_cites_a_source(self):
        for r in self.rows:
            if r["result"] in ("WIN", "LOSS", "VOID"):
                self.assertTrue(r["result_source"].startswith(("http", "owner screenshot")), r["pick_id"])

    def test_the_soft_pass_is_not_a_pick(self):
        (soft,) = [r for r in self.rows if r["pick_strength"] == "soft_pass"]
        self.assertEqual((soft["market"], soft["side"], soft["result"]), ("soft_pass", "none", ""))


class ReplayArithmeticTests(unittest.TestCase):
    def test_summary_counts_agreement_and_the_engine_record(self):
        rows = [
            dict(code="bet", our="home", his_side="home", agrees="yes", his_result="WIN"),
            dict(code="bet", our="away", his_side="home", agrees="no", his_result="WIN"),      # he won; the opposite side lost
            dict(code="bet", our="away", his_side="home", agrees="no", his_result="LOSS"),     # he lost; the opposite side won
            dict(code="uneven_search", our="PASS", his_side="home", agrees="", his_result="WIN"),
            dict(code="not_placed", our="n/a", his_side="home", agrees="", his_result="LOSS"),
        ]
        s = replay.summarise(rows)
        self.assertEqual((s["placed"], s["engine_picks"], s["engine_passes"], s["same_side_as_him"]), (4, 3, 1, 1))
        self.assertEqual(s["engine_record_in_sample"], {"W": 2, "L": 1, "n/a": 0})
        self.assertEqual(s["his_record_on_placed_games"], {"W": 3, "L": 1})

    def test_team_names_resolve_only_when_unambiguous(self):
        book = facts_mod.FactsBook({"teams": {
            "ncaaf:washingtonhuskies": {"sport": "ncaaf", "name": "Washington Huskies", "mascot": {"value": "Huskies"}},
            "ncaaf:washingtonstatecougars": {"sport": "ncaaf", "name": "Washington State Cougars", "mascot": {"value": "Cougars"}},
            "nfl:denverbroncos": {"sport": "nfl", "name": "Denver Broncos", "mascot": {"value": "Broncos"}}}})
        self.assertEqual(replay.resolve_team(book, "ncaaf", "Washington"), "Washington Huskies")      # the alias table
        self.assertEqual(replay.resolve_team(book, "nfl", "Denver Broncos"), "Denver Broncos")
        self.assertEqual(replay.resolve_team(book, "nfl", "Broncos"), "Denver Broncos")
        self.assertIsNone(replay.resolve_team(book, "nfl", "Nobody"))

    def test_the_replay_is_labelled_in_sample_and_not_a_hound_result(self):
        text = (RAB / "replay.py").read_text(encoding="utf-8")
        self.assertIn("IN-SAMPLE", text)
        self.assertIn("not a result for the hound", text.lower().replace("Not a result", "not a result"))


if __name__ == "__main__":
    unittest.main()
