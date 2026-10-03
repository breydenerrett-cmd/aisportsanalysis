"""The survival dashboard's arithmetic and its refusal to guess."""
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts import outreach_batch as ob
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


FIELDS = ob.QUEUE_FIELDS
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def person(n, **kw):
    row = {f: "" for f in FIELDS}
    row.update({"lead_id": f"l{n:03d}-lead-{n}", "kind": "person", "person": f"Lead {n}", "channel": "creator",
                "campaign": "batch_01", "batch": "1"})
    row.update(kw)
    return row


def post(n, **kw):
    return person(n, kind="channel_post", channel="forum", person=f"Thread {n}", **kw)


def sent_five():
    """5 people sent a message; 2 replied (1 of them spam); 1 signup; nobody paid."""
    rows = [person(i, sent_at=f"2026-10-0{i}T09:00:00Z") for i in range(1, 6)]
    rows[0].update(reply_at="2026-10-03T10:00:00Z", reply_type="POSITIVE_INTEREST",
                   signup_at="2026-10-04T10:00:00Z")
    rows[1].update(reply_at="2026-10-03T08:00:00Z", reply_type="SPAM_OR_IRRELEVANT")
    return rows


def render(config=CONFIG, queue=None, pipeline=None, now=NOW):
    return sd.render(config, date(2026, 10, 1), "2026-10-01 00:00Z",
                     queue_rows=queue if queue is not None else [], pipeline_rows=pipeline or [],
                     record=["- record fixture"], now=now)


def cell(text, label):
    """The value cell of the table row whose first cell is `label`."""
    for line in text.splitlines():
        parts = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if line.startswith("|") and parts and parts[0] == label:
            return parts[1]
    raise AssertionError(f"no row {label!r}")


class CustomerRows(unittest.TestCase):
    LABELS = ("UNIQUE LEADS", "MESSAGES SENT", "REPLIES", "POSITIVE REPLIES", "SIGNUPS", "ACTIVE TESTERS",
              "ACTIVATED USERS", "RETURNING USERS", "WOULD PAY", "PAID USERS", "REVENUE")

    def test_every_row_is_there_with_its_zero_and_a_one_line_definition(self):
        text = render(queue=[])
        for label in self.LABELS:
            rows = [l for l in text.splitlines() if l.startswith(f"| {label} |")]
            self.assertEqual(len(rows), 1, label)
            cells = [c.strip() for c in rows[0].strip().strip("|").split(" | ")]
            self.assertEqual(len(cells), 3, label)
            self.assertTrue(cells[1] and cells[2].endswith("."), label)        # a value and a definition
        for label in ("UNIQUE LEADS", "MESSAGES SENT", "REPLIES", "POSITIVE REPLIES", "SIGNUPS", "ACTIVE TESTERS",
                      "PAID USERS"):
            self.assertEqual(cell(text, label), "0", label)
        self.assertEqual(cell(text, "WOULD PAY"), "0 (0 said no)")
        self.assertEqual(cell(text, "ACTIVATED USERS"), "0 (from the outreach log)")
        self.assertEqual(cell(text, "RETURNING USERS"), "0 (not measured yet)")
        self.assertIn("- queued, not yet contacted: 0", text)
        self.assertIn("- channel posts made: 0", text)

    def test_counts_come_from_distinct_person_rows(self):
        text = render(queue=sent_five())
        self.assertEqual(cell(text, "UNIQUE LEADS"), "5")
        self.assertEqual(cell(text, "MESSAGES SENT"), "5")
        self.assertEqual(cell(text, "REPLIES"), "2 (1 of them spam or irrelevant)")
        self.assertEqual(cell(text, "POSITIVE REPLIES"), "1")
        self.assertEqual(cell(text, "SIGNUPS"), "1")
        self.assertEqual(cell(text, "PAID USERS"), "0")

    def test_a_repeated_lead_id_is_one_lead_and_is_flagged(self):
        rows = sent_five() + [dict(sent_five()[0], signup_at="2026-10-09T00:00:00Z")]
        text = render(queue=rows)
        self.assertEqual(cell(text, "UNIQUE LEADS"), "5")
        self.assertEqual(cell(text, "SIGNUPS"), "1")
        self.assertIn("1 repeated lead_id row(s) in the queue were merged, not counted", text)

    def test_queued_people_and_channel_posts_are_separate_lines_and_never_leads(self):
        rows = sent_five() + [person(i) for i in range(6, 9)] + [post(9, sent_at="2026-10-02T09:00:00Z"), post(10)]
        text = render(queue=rows)
        self.assertEqual(cell(text, "UNIQUE LEADS"), "5")
        self.assertEqual(cell(text, "MESSAGES SENT"), "6")             # the thread posted is a message sent
        self.assertIn("- queued, not yet contacted: 3 ", text)
        self.assertIn("- channel posts made: 1 ", text)

    def test_a_channel_post_never_counts_as_a_reply_signup_or_payment_even_if_hand_edited(self):
        rows = [post(1, sent_at="2026-10-02T09:00:00Z", reply_at="2026-10-03T00:00:00Z", reply_type="WOULD_PAY",
                     signup_at="2026-10-03T00:00:00Z", payment_at="2026-10-04T00:00:00Z", would_pay="yes")]
        text = render(queue=rows)
        for label in ("UNIQUE LEADS", "REPLIES", "POSITIVE REPLIES", "SIGNUPS", "PAID USERS"):
            self.assertEqual(cell(text, label), "0", label)
        self.assertEqual(cell(text, "WOULD PAY"), "0 (0 said no)")
        self.assertEqual(cell(text, "MESSAGES SENT"), "1")

    def test_a_person_who_wrote_in_is_a_lead_and_a_reply_but_not_in_the_reply_rate(self):
        rows = [person(1, reply_at="2026-10-03T10:00:00Z", via_lead="l001-x", reply_type="CURIOUS")]
        text = render(queue=rows)
        self.assertEqual((cell(text, "UNIQUE LEADS"), cell(text, "REPLIES"), cell(text, "MESSAGES SENT")), ("1", "1", "0"))
        self.assertEqual(cell(text, "Reply rate"), "0 of 0 (no rate yet)")

    def test_active_testers_are_those_inside_their_seven_days(self):
        rows = [person(1, tester_access_at="2026-10-03T12:00:00Z"),       # 2 days in
                person(2, tester_access_at="2026-09-28T12:00:00Z"),       # exactly 7 days ago: over
                person(3, tester_access_at="2026-09-28T12:00:01Z"),       # one second left
                person(4, tester_access_at="2026-09-01T00:00:00Z"),       # long over
                person(5)]
        self.assertEqual(cell(render(queue=rows), "ACTIVE TESTERS"), "2")
        self.assertEqual(cell(render(queue=rows, now=NOW + timedelta(days=6)), "ACTIVE TESTERS"), "0")
        self.assertEqual(cell(render(queue=rows, now=NOW - timedelta(days=40)), "ACTIVE TESTERS"), "0")   # not yet granted

    def test_the_active_window_reads_the_page_stamp_when_no_clock_is_injected(self):
        rows = [person(1, tester_access_at="2026-10-30T00:00:00Z")]
        text = sd.render(CONFIG, date(2026, 10, 31), "2026-11-02 00:00Z", queue_rows=rows, pipeline_rows=[], record=[])
        self.assertEqual(cell(text, "ACTIVE TESTERS"), "1")
        text = sd.render(CONFIG, date(2026, 10, 31), "2026-11-20 00:00Z", queue_rows=rows, pipeline_rows=[], record=[])
        self.assertEqual(cell(text, "ACTIVE TESTERS"), "0")

    def test_would_pay_counts_yes_and_says_how_many_said_no(self):
        rows = sent_five()
        rows[0].update(would_pay="yes", would_pay_at="2026-10-04T10:00:00Z")
        rows[1].update(would_pay="no", would_pay_at="2026-10-04T11:00:00Z")
        rows[2].update(would_pay="NO", would_pay_at="2026-10-04T12:00:00Z")
        self.assertEqual(cell(render(queue=rows), "WOULD PAY"), "1 (2 said no)")

    def test_paid_users_and_revenue_are_only_what_a_paid_event_recorded(self):
        rows = sent_five()
        rows[2].update(payment_at="2026-10-06T09:00:00Z")
        self.assertIn("none logged", cell(render(), "REVENUE"))
        no_amount = render(queue=rows)
        self.assertEqual(cell(no_amount, "PAID USERS"), "1")
        self.assertEqual(cell(no_amount, "REVENUE"), "UNKNOWN (1 payment(s) logged without a revenue figure)")
        by_name = {"stage": "paid", "target": "lead 3", "revenue": "19.99"}
        self.assertEqual(cell(render(queue=rows, pipeline=[by_name]), "REVENUE"), "$19.99")
        # a person with no readable name is matched by the lead_id the event carries
        added = [person(7, reply_at="2026-10-03T00:00:00Z", via_lead="l001-x", person="l007-p",
                        lead_id="l007-p", payment_at="2026-10-06T09:00:00Z")]
        by_id = {"stage": "paid", "target": "l007-p", "revenue": "10", "notes": "lead_id=l007-p"}
        self.assertEqual(cell(render(queue=added, pipeline=[by_id]), "REVENUE"), "$10.00")

    def test_a_stale_config_customer_count_is_flagged(self):
        text = render(dict(CONFIG, revenue={"mrr_usd": 0.0, "paying_customers": 2}), sent_five())
        self.assertIn("config says 2 paying customer(s); only 0 are in the queue", text)

    def test_revenue_and_mrr_rows_keep_their_place_in_the_top_table(self):
        text = render(CONFIG, sent_five())
        self.assertIn("| MRR (", text)
        self.assertLess(text.index("| MRR ("), text.index("## Customer discovery"))

    def test_a_missing_queue_file_is_said_not_hidden(self):
        original = sd.QUEUE
        sd.QUEUE = sd.ROOT / "docs" / "sales" / "no-such-queue.csv"
        self.addCleanup(setattr, sd, "QUEUE", original)
        text = sd.render(CONFIG, date(2026, 10, 1), "x", pipeline_rows=[], record=[])
        self.assertIn("outreach_queue.csv not found", text)
        self.assertEqual(cell(text, "UNIQUE LEADS"), "0")

    def test_the_old_header_queue_is_read_and_counted_after_migration(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.csv"
            old = ",".join(ob.OLD_QUEUE_FIELDS)
            path.write_text(old + "\nl001-a,Alpha,creator,MLB,v,2026-10-02T09:00:00Z,2026-10-03T09:00:00Z,interested,,,,,,1,\n"
                            "l002-b,Beta Forum,forum,MLB,v,2026-10-02T09:00:00Z,,,,,,,,1,\n", encoding="utf-8")
            original = sd.QUEUE
            sd.QUEUE = path
            self.addCleanup(setattr, sd, "QUEUE", original)
            text = sd.render(CONFIG, date(2026, 10, 4), "2026-10-04 00:00Z", pipeline_rows=[], record=[])
        self.assertEqual((cell(text, "UNIQUE LEADS"), cell(text, "MESSAGES SENT"), cell(text, "POSITIVE REPLIES")),
                         ("1", "2", "1"))
        self.assertIn("- channel posts made: 1 ", text)


class RatesNeedASample(unittest.TestCase):
    def test_the_rate_format(self):
        self.assertEqual(sd._rate(0, 0), "0 of 0 (no rate yet)")
        self.assertEqual(sd._rate(2, 5), "2 of 5 (40.0%), small sample")
        self.assertEqual(sd._rate(1, 29), "1 of 29 (3.4%), small sample")
        self.assertEqual(sd._rate(1, 30), "1 of 30 (3.3%)")
        self.assertEqual(sd._rate(0, 40), "0 of 40 (0.0%)")

    def test_every_rate_has_its_numerator_and_denominator(self):
        rows = sent_five()
        rows[0].update(activated_at="2026-10-05T00:00:00Z", would_pay="yes", would_pay_at="2026-10-05T00:00:00Z",
                       payment_at="2026-10-06T00:00:00Z")
        rows[1].update(would_pay="no", would_pay_at="2026-10-05T00:00:00Z")
        text = render(queue=rows)
        self.assertEqual(cell(text, "Reply rate"), "2 of 5 (40.0%), small sample")          # replied of sent
        self.assertEqual(cell(text, "Signup rate"), "1 of 5 (20.0%), small sample")         # signups of unique leads
        self.assertEqual(cell(text, "Activation rate"), "1 of 1 (100.0%), small sample")    # activated of signups
        self.assertEqual(cell(text, "Would-pay rate"), "1 of 2 (50.0%), small sample")      # yes of yes + no
        self.assertEqual(cell(text, "Paid conversion"), "1 of 5 (20.0%), small sample")     # paid of unique leads

    def test_zero_denominators_say_no_rate_yet_and_never_print_a_percentage(self):
        for queue in ([], [person(1), person(2)]):               # no leads; people queued but nothing sent
            text = render(queue=queue)
            for label in ("Reply rate", "Signup rate", "Activation rate", "Would-pay rate", "Paid conversion"):
                self.assertEqual(cell(text, label), "0 of 0 (no rate yet)", label)
            self.assertNotIn("%", text.split("## Customer discovery")[1].split("## Milestones")[0])

    def test_thirty_in_the_denominator_drops_the_small_sample_warning(self):
        rows = [person(i, sent_at="2026-10-02T09:00:00Z") for i in range(1, 31)]
        for r in rows[:12]:
            r.update(reply_at="2026-10-03T00:00:00Z", reply_type="CURIOUS")
        self.assertEqual(cell(render(queue=rows), "Reply rate"), "12 of 30 (40.0%)")
        self.assertEqual(cell(render(queue=rows[:29]), "Reply rate"), "12 of 29 (41.4%), small sample")

    def test_the_activation_rate_stays_inside_the_outreach_cohort_even_with_product_numbers(self):
        config = dict(CONFIG, tester_activity={"as_of": "2026-10-04", "activated": 9, "returning": 3})
        text = render(config, sent_five())
        self.assertEqual(cell(text, "ACTIVATED USERS"), "9 (from the product, as of 2026-10-04)")
        self.assertEqual(cell(text, "Activation rate"), "0 of 1 (0.0%), small sample")     # never 9 of 1


class TesterActivityFromTheProduct(unittest.TestCase):
    ACTIVITY = {"as_of": "2026-10-04", "testers_granted": 7, "testers_in_window": 5, "activated": 4,
                "returning": 2, "median_hours_signup_to_activation": 3.5,
                "feature_users": {"card": 4, "props": 2, "odds": 0}}

    def test_activated_and_returning_come_from_config_and_say_so(self):
        text = render(dict(CONFIG, tester_activity=self.ACTIVITY), sent_five())
        self.assertEqual(cell(text, "ACTIVATED USERS"), "4 (from the product, as of 2026-10-04)")
        self.assertEqual(cell(text, "RETURNING USERS"), "2 (from the product, as of 2026-10-04)")
        self.assertIn("### Tester activity (from the product, as of 2026-10-04)", text)
        self.assertIn("- testers granted: 7 of 20", text)
        self.assertIn("- testers inside their 7 days: 5", text)
        self.assertIn("- median hours from signup to activation: 3.5", text)

    def test_feature_users_print_as_a_table_with_the_zeros(self):
        text = render(dict(CONFIG, tester_activity=self.ACTIVITY))
        section = text.split("| Feature | Testers who used it |")[1].split("##")[0]
        self.assertEqual([l for l in section.splitlines() if l.startswith("| ") and "---" not in l],
                         ["| card | 4 |", "| props | 2 |", "| odds | 0 |"])

    def test_a_feature_the_product_cannot_measure_is_not_printed_as_zero(self):
        """The admin page's export lists `unmeasured_features` (moneyline today: no route
        serves it as the page a person chose). Its 0 is not 'nobody used it'."""
        activity = dict(self.ACTIVITY, feature_users={"card": 4, "moneyline": 0, "props": 0},
                        unmeasured_features=["moneyline"], internal_excluded=1)
        text = render(dict(CONFIG, tester_activity=activity))
        section = text.split("| Feature | Testers who used it |")[1].split("##")[0]
        self.assertEqual([l for l in section.splitlines() if l.startswith("| ") and "---" not in l],
                         ["| card | 4 |", "| moneyline | not measured yet |", "| props | 0 |"])

    def test_absent_means_the_log_and_not_measured_and_no_activity_section(self):
        text = render(CONFIG, sent_five())
        self.assertNotIn("Tester activity", text)
        self.assertEqual(cell(text, "RETURNING USERS"), "0 (not measured yet)")
        rows = sent_five()
        rows[0].update(activated_at="2026-10-05T00:00:00Z")
        self.assertEqual(cell(render(queue=rows), "ACTIVATED USERS"), "1 (from the outreach log)")

    def test_a_partial_object_falls_back_per_field_and_bad_values_are_flagged(self):
        partial = {"as_of": "2026-10-04", "activated": 3}
        text = render(dict(CONFIG, tester_activity=partial))
        self.assertEqual(cell(text, "ACTIVATED USERS"), "3 (from the product, as of 2026-10-04)")
        self.assertEqual(cell(text, "RETURNING USERS"), "0 (not measured yet)")
        self.assertIn("- median hours from signup to activation: not measured yet", text)
        bad = {"as_of": "2026-10-04", "activated": "4", "returning": True, "median_hours_signup_to_activation": "x",
               "feature_users": {"card": -1, "odds": 2}}
        text = render(dict(CONFIG, tester_activity=bad), sent_five())
        self.assertEqual(cell(text, "ACTIVATED USERS"), "0 (from the outreach log)")
        self.assertEqual(cell(text, "RETURNING USERS"), "0 (not measured yet)")
        for problem in ("tester_activity.activated is not a whole number", "tester_activity.returning is not a whole number",
                        "median_hours_signup_to_activation is not a number", "feature_users['card']"):
            self.assertIn(problem, text)
        self.assertIn("| odds | 2 |", text)
        self.assertNotIn("| card |", text)
        self.assertIn("is not an object; ignored", render(dict(CONFIG, tester_activity="oops")))

    def test_an_as_of_that_is_missing_is_said_not_invented(self):
        text = render(dict(CONFIG, tester_activity={"activated": 1}))
        self.assertIn("as of an unstated date", text)


class MilestoneRows(unittest.TestCase):
    def test_milestones_show_first_timestamps_with_the_lead_and_not_yet(self):
        text = render(queue=sent_five())
        self.assertIn("- First message sent: 2026-10-01T09:00:00Z (l001-lead-1)", text)
        self.assertIn("- First reply: 2026-10-03T08:00:00Z (l002-lead-2)", text)        # the spam reply is a reply
        self.assertIn("- First positive reply (the time of that lead's first reply): "
                      "2026-10-03T10:00:00Z (l001-lead-1)", text)
        self.assertIn("- First signup: 2026-10-04T10:00:00Z (l001-lead-1)", text)
        for label in ("First tester access", "First active tester", "First feedback", "First would-pay (yes)",
                      "First payment"):
            self.assertIn(f"- {label}: not yet", text)


class DashboardLayout(unittest.TestCase):
    FULL = dict(CONFIG, top_blockers=["b1", "b2", "b3", "b4"],
                next_owner_action="owner thing", next_customer_action="customer thing",
                next_product_action="product thing", next_research_action="model thing",
                production_health="green, 0 restarts", capture_cost="620 credits a day",
                active_sports=["MLB"])

    def test_the_asked_for_fields_appear_in_the_asked_for_order(self):
        text = render(self.FULL, sent_five())
        marks = ["| Days until", "Current monthly burn (known", "Identified monthly savings", "| MRR (",
                 "## Customer discovery", "| UNIQUE LEADS", "| MESSAGES SENT", "| REPLIES", "| POSITIVE REPLIES",
                 "| SIGNUPS", "| ACTIVE TESTERS", "| ACTIVATED USERS", "| RETURNING USERS", "| WOULD PAY",
                 "| PAID USERS", "| REVENUE", "| Reply rate", "| Paid conversion", "## Milestones", "## Current sports",
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


class TestersGrantedRow(unittest.TestCase):
    """Early-access testers are granted by hand; the script never asks
    production. The row exists only when the owner put the count in config."""

    def _text(self, **extra):
        return sd.render(dict(CONFIG, **extra), date(2026, 10, 3), "2026-10-03 00:00Z",
                         queue_rows=[], pipeline_rows=[], record=[])

    def test_no_row_when_the_config_has_no_count(self):
        self.assertNotIn("Testers granted", self._text())
        self.assertNotIn("Testers granted", self._text(testers_granted=None))

    def test_the_row_shows_the_owners_count_against_the_cap(self):
        from src.appstate.testers import TESTER_LIMIT
        self.assertIn(f"| Testers granted | 7 of {TESTER_LIMIT} (config, owner-updated) |",
                      self._text(testers_granted=7))
        self.assertIn("| Testers granted | 0 of 20 (config, owner-updated) |",
                      self._text(testers_granted=0))

    def test_a_count_that_is_not_an_integer_is_not_printed(self):
        for bad in ("7", 7.0, True, [7]):
            self.assertNotIn("Testers granted", self._text(testers_granted=bad), repr(bad))

    def test_the_script_makes_no_network_call(self):
        source = (sd.ROOT / "scripts" / "survival_dashboard.py").read_text(encoding="utf-8")
        for needle in ("urllib", "requests", "http.client", "socket", "/admin/testers"):
            self.assertNotIn(needle, source, needle)


if __name__ == "__main__":
    unittest.main()
