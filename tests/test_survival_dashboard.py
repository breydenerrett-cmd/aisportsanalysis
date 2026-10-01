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


if __name__ == "__main__":
    unittest.main()
