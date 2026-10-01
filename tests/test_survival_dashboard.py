"""The survival dashboard's arithmetic and its refusal to guess."""
import unittest
from datetime import date

from scripts import survival_dashboard as sd

CONFIG = {
    "deadline": "2026-10-31",
    "costs_monthly": [
        {"item": "data", "usd": 59.0, "known": True, "class": "KEEP", "note": ""},
        {"item": "hosting", "usd": 31.0, "known": False, "class": "KEEP", "note": ""},
        {"item": "claude", "usd": None, "known": False, "class": "REDUCE", "note": ""},
    ],
    "claude_planning_assumption_usd": 200.0,
    "offers": [{"name": "sub", "price_usd": 19.99, "net_after_stripe_usd": 18.97},
               {"name": "feed", "price_usd": 149.0, "net_after_stripe_usd": 143.33}],
    "revenue": {"mrr_usd": 0.0, "paying_customers": 0, "trials": 0},
}


class Arithmetic(unittest.TestCase):
    def test_costs_separate_known_estimated_and_unknown(self):
        costs = sd.cost_summary(CONFIG)
        self.assertEqual(costs["known"], 59.0)
        self.assertEqual(costs["estimated"], 31.0)
        self.assertEqual(costs["unknown_items"], ["claude"])
        self.assertEqual(costs["planning_total"], 290.0)

    def test_break_even_rounds_up_on_net_revenue(self):
        self.assertEqual(sd.break_even(90.0, CONFIG["offers"]),
                         [("sub", 19.99, 5), ("feed", 149.0, 1)])
        self.assertEqual(sd.break_even(290.0, CONFIG["offers"])[0][2], 16)

    def test_render_counts_days_and_never_prints_a_guess_for_unknown_costs(self):
        text = sd.render(CONFIG, date(2026, 10, 1), "2026-10-01 00:00Z")
        self.assertIn("| Days until 2026-10-31 | **30** |", text)
        self.assertIn("| claude | UNKNOWN |", text)
        self.assertIn("unknown: claude", text)



class PipelineIsAHistoryNotAList(unittest.TestCase):
    """`outreach_batch.py reply` appends a row when a target moves on. A lead
    is a person, not a row."""

    HEADER = "date,source,campaign,target,contact_path,message_variant,stage,last_touch,next_action,revenue,notes"

    def _counts(self, lines):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipeline.csv"
            path.write_text(chr(10).join([self.HEADER] + lines) + chr(10), encoding="utf-8")
            return sd.pipeline_counts(path)

    def test_a_target_that_replied_and_then_paid_is_one_lead(self):
        counts = self._counts([
            "2026-10-02,discord_server,batch_01,Unit Circle,DM,B,sent,2026-10-02,,0,",
            "2026-10-02,x_account,batch_01,Someone,X,X,sent,2026-10-02,,0,",
            "2026-10-03,discord_server,batch_01,unit circle,DM,B,replied,2026-10-03,,0,",
            "2026-10-09,discord_server,batch_01,Unit Circle,DM,B,paid,2026-10-09,,149,",
        ])
        self.assertEqual(counts["rows"], 2)
        self.assertEqual(counts["counts"]["paid"], 1)
        self.assertEqual(counts["counts"]["sent"], 1)
        self.assertEqual(counts["counts"]["replied"], 0)     # it moved on
        self.assertEqual(counts["reached"]["replied"], 1)    # but it did reply
        self.assertEqual(counts["revenue"], 149.0)

    def test_an_empty_file_is_zero_leads(self):
        counts = self._counts([])
        self.assertEqual(counts["rows"], 0)
        self.assertEqual(counts["revenue"], 0.0)


if __name__ == "__main__":
    unittest.main()
