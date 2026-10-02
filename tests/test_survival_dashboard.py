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
        text = sd.render(CONFIG, date(2026, 10, 1), "2026-10-01 00:00Z",
                         queue_rows=[], pipeline_rows=[], record=[])
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


FIELDS = ["lead_id", "person_channel", "source", "sport_interest", "message_version", "sent_at",
          "reply_at", "reply_classification", "signup_at", "activated_at", "payment_at",
          "next_followup", "notes", "batch", "would_pay_at"]


def lead(n, **kw):
    row = {f: "" for f in FIELDS}
    row.update({"lead_id": f"l{n:03d}-lead-{n}", "person_channel": f"Lead {n}", "source": "creator",
                "batch": "1"})
    row.update(kw)
    return row


def sent_five():
    """5 leads sent; 2 replied (1 of them auto); 1 signup; nobody paid."""
    rows = [lead(i, sent_at=f"2026-10-0{i}T09:00:00Z") for i in range(1, 6)]
    rows[0].update(reply_at="2026-10-03T10:00:00Z", reply_classification="interested",
                   signup_at="2026-10-04T10:00:00Z")
    rows[1].update(reply_at="2026-10-03T08:00:00Z", reply_classification="auto")
    return rows


def render(config=CONFIG, queue=None, pipeline=None):
    return sd.render(config, date(2026, 10, 1), "2026-10-01 00:00Z",
                     queue_rows=queue if queue is not None else [], pipeline_rows=pipeline or [],
                     record=["- record fixture"])


class FunnelFromTheQueue(unittest.TestCase):
    def test_counts_come_from_distinct_lead_rows(self):
        text = render(queue=sent_five())
        for line in ("| Unique leads | 5 |", "| Messages sent | 5 |",
                     "| Replies | 1 (plus 1 auto-reply, not counted) |", "| Signups | 1 |",
                     "| Active users | 0 |", "| People who said they would pay | 0 |",
                     "| Paid customers | 0 |"):
            self.assertIn(line, text)
        self.assertIn("| Conversion rate (paid / leads sent) | 0.0% (0 of 5 leads sent) |", text)

    def test_a_repeated_lead_id_is_one_lead_and_is_flagged(self):
        rows = sent_five() + [dict(sent_five()[0], signup_at="2026-10-09T00:00:00Z")]
        text = render(queue=rows)
        self.assertIn("| Unique leads | 5 |", text)
        self.assertIn("| Signups | 1 |", text)
        self.assertIn("1 repeated lead_id row(s) in the queue were merged, not counted", text)

    def test_zero_denominator_prints_n_a_never_zero_percent(self):
        for queue in ([], [lead(1), lead(2)]):                  # no leads; leads but nothing sent
            text = render(queue=queue)
            self.assertIn("| Conversion rate (paid / leads sent) | n/a", text)
            self.assertNotIn("0.0%", text)
            self.assertNotIn("0%", text)
        self.assertIn("| Unique leads | 2 |", render(queue=[lead(1), lead(2)]))

    def test_paid_over_sent_is_the_conversion_rate(self):
        rows = sent_five()
        rows[2].update(payment_at="2026-10-06T09:00:00Z")
        self.assertIn("| Conversion rate (paid / leads sent) | 20.0% (1 of 5 leads sent) |", render(queue=rows))

    def test_milestones_show_first_timestamps_and_not_yet(self):
        text = render(queue=sent_five())
        self.assertIn("- First message sent: 2026-10-01T09:00:00Z", text)
        self.assertIn("- First real reply (not auto): 2026-10-03T10:00:00Z", text)   # the auto at 08:00 is skipped
        self.assertIn("- First signup: 2026-10-04T10:00:00Z", text)
        self.assertIn("- First payment: not yet", text)
        self.assertIn("- First active user: not yet", text)

    def test_revenue_is_only_what_a_paid_event_recorded(self):
        rows = sent_five()
        rows[2].update(payment_at="2026-10-06T09:00:00Z")
        self.assertIn("| Revenue (payments logged in the queue) | none logged", render())
        no_amount = render(queue=rows)
        self.assertIn("| Revenue (payments logged in the queue) | UNKNOWN (1 payment(s) logged "
                      "without a revenue figure) |", no_amount)
        event = {"stage": "paid", "target": "lead 3", "revenue": "19.99"}
        self.assertIn("| Revenue (payments logged in the queue) | $19.99 |", render(queue=rows, pipeline=[event]))

    def test_a_missing_queue_file_is_said_not_hidden(self):
        original = sd.QUEUE
        sd.QUEUE = sd.ROOT / "docs" / "sales" / "no-such-queue.csv"
        self.addCleanup(setattr, sd, "QUEUE", original)
        text = sd.render(CONFIG, date(2026, 10, 1), "x", pipeline_rows=[], record=[])
        self.assertIn("outreach_queue.csv not found", text)
        self.assertIn("| Unique leads | 0 |", text)


class DashboardLayout(unittest.TestCase):
    FULL = dict(CONFIG, top_blockers=["b1", "b2", "b3", "b4"],
                next_owner_action="owner thing", next_customer_action="customer thing",
                next_product_action="product thing", next_research_action="model thing",
                production_health="green, 0 restarts", capture_cost="620 credits a day",
                active_sports=["MLB"])

    def test_the_asked_for_fields_appear_in_the_asked_for_order(self):
        text = render(self.FULL, sent_five())
        marks = ["| Days until", "Current monthly burn (known", "Identified monthly savings", "| Revenue (",
                 "| MRR (", "| Unique leads", "| Messages sent", "| Replies", "| Signups", "| Active users",
                 "would pay", "| Paid customers", "| Conversion rate", "## Milestones", "## Current sports",
                 "## Performance by market", "## Production health and capture cost", "## Top 3 blockers",
                 "## Next actions"]
        at = [text.index(m) for m in marks]
        self.assertEqual(at, sorted(at))

    def test_savings_are_summed_from_saving_usd_and_named(self):
        costs = [dict(c) for c in CONFIG["costs_monthly"]]
        costs[0].update(saving_usd=29.0, saving_label="downgrade the tier")
        costs[1].update(saving_usd=5.5)
        text = render(dict(CONFIG, costs_monthly=costs))
        self.assertIn("| Identified monthly savings (not yet realised) | $34.50: data: $29.00 (downgrade the tier); "
                      "hosting: $5.50 (see the note in the costs table) |", text)
        self.assertEqual(sd.savings(CONFIG), [])
        self.assertIn("none identified", render())

    def test_only_the_first_three_blockers_are_top_and_actions_default_to_not_set(self):
        text = render(self.FULL)
        top = text.split("## Top 3 blockers")[1].split("## Next actions")[0]
        self.assertIn("3. b3", top)
        self.assertNotIn("b4", top)
        self.assertIn("- b4", text.split("## Other blockers")[1])
        nxt = text.split("## Next actions")[1]
        for label, value in (("Owner", "owner thing"), ("Customer", "customer thing"),
                             ("Product", "product thing"), ("Model", "model thing")):
            self.assertIn(f"- **{label}:** {value}", nxt)
        bare = render().split("## Next actions")[1]
        for label in ("Owner", "Customer", "Product", "Model"):
            self.assertIn(f"- **{label}:** not set", bare)

    def test_production_health_and_capture_cost_come_from_config_else_point_at_the_audit(self):
        text = render(self.FULL)
        self.assertIn("- Production health: green, 0 restarts", text)
        self.assertIn("- Capture cost: 620 credits a day", text)
        bare = render()
        self.assertIn("- Production health: see docs/audit", bare)
        self.assertIn("- Capture cost: see docs/audit", bare)

    def test_clv_points_at_the_value_scan_and_invents_no_figure(self):
        text = render()
        self.assertIn("see `docs/VALUE_SCAN.md`", text)
        self.assertIn("no CLV figure is computed or copied here", text)


class CommittedDashboard(unittest.TestCase):
    def test_the_committed_config_has_the_odds_api_saving(self):
        import json
        config = json.loads((sd.ROOT / "config" / "business.json").read_text(encoding="utf-8"))
        self.assertEqual([(i, usd) for i, usd, _ in sd.savings(config)],
                         [("The Odds API (100K tier)", 29.0)])



class ARateNeedsASample(unittest.TestCase):
    """"ROI +92.6%" off one NFL pick was on the dashboard. The sample size
    leads and a rate appears only from MIN_N_FOR_A_RATE staked picks."""

    def test_a_small_sample_prints_its_n_first_and_no_rate(self):
        text = sd._fig({"wins": 5, "losses": 1, "n_staked": 6, "profit_units": 2.5027})
        self.assertTrue(text.startswith("n=6: 5-1, +2.50u"), text)
        self.assertNotIn("%", text)
        self.assertIn("too few for a rate", text)

    def test_a_rate_appears_at_the_floor(self):
        text = sd._fig({"wins": 16, "losses": 17, "n_staked": 33, "profit_units": -5.05})
        self.assertEqual(text, "n=33: 16-17, -5.05u, ROI -15.3%")
        below = sd._fig({"wins": 15, "losses": 14, "n_staked": sd.MIN_N_FOR_A_RATE - 1, "profit_units": 1.0})
        self.assertNotIn("%", below)

    def test_nothing_graded_stays_nothing_graded(self):
        self.assertEqual(sd._fig({}), "nothing graded")


if __name__ == "__main__":
    unittest.main()
