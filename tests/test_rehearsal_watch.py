"""scripts/rehearsal_watch.py against fixture lines and against lines the real
code emits.

Two kinds of evidence, kept apart on purpose:

  * FIXTURE lines in the shape `fly logs` prints (timestamp, ANSI colour, two
    writes glued onto one line). These pin the parser against the staging
    format observed 2026-10-04.
  * EMITTED lines: the request-log line comes from reqlog.format_line and the
    webhook lines from the real handler driven by the in-process Stripe
    stand-in, so a change to either log format fails here instead of silently
    blinding the rehearsal.
"""

from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path

from src.appstate import reqlog

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("rehearsal_watch", ROOT / "scripts" / "rehearsal_watch.py")
watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch)

U = "6b86b273ff34fce1"


def fly(ts, body, colour=True):
    """One staging line as `fly logs` prints it."""
    if colour:
        return (f"\x1b[2m{ts}\x1b[0m app[8e257da7795538] \x1b[32miad\x1b[0m "
                f"[\x1b[34minfo\x1b[0m]{body}")
    return f"{ts} app[8e257da7795538] iad [info]{body}"


def req(method, path, status, user="-"):
    return f"method={method} path={path} status={status} latency_ms=12.3 user={user}"


def hook(kind, user=U, paid="-", status="'active'", evt="evt_1"):
    return (f"billing: webhook type='{kind}' event='{evt}' user={user} "
            f"paid_through={paid} status={status}")


PAID = "'2026-11-04T19:00:00+00:00'"


class Fixtures(unittest.TestCase):
    def test_a_full_rehearsal_passes_every_required_step(self):
        t = "2026-10-04T19:{:02d}:00Z"
        lines = [
            fly(t.format(1), req("POST", "/signup", 200)),
            fly(t.format(2), req("GET", "/signup/complete", 404)),
            fly(t.format(3), hook("checkout.session.completed")),
            fly(t.format(3), req("POST", "/billing/webhook", 200)),
            fly(t.format(3), hook("customer.subscription.created", paid=PAID)),
            fly(t.format(3), hook("invoice.paid", paid=PAID)),
            fly(t.format(4), req("GET", "/signup/complete", 200)),
            fly(t.format(5), req("GET", "/ufc/fight-night", 200, U)),
            fly(t.format(9), req("GET", "/signup/complete", 200)),
            fly(t.format(11), req("POST", "/billing/cancel", 200, U)),
            fly(t.format(15), "billing: invoice.payment_failed user=" + U
                + " subscription='sub_1' attempt='1'"),
        ]
        result = watch.scan(lines)
        self.assertTrue(result.ok, watch.render(result))
        self.assertEqual(result.warnings, [])

    def test_an_empty_log_passes_nothing(self):
        result = watch.scan([])
        self.assertFalse(result.ok)
        self.assertEqual(result.seen, {})
        self.assertEqual(watch.render(result).count("NOT SEEN"), len(watch.STEPS))

    def test_the_webhook_request_line_alone_does_not_pass_a_named_event(self):
        # Every webhook is `POST /billing/webhook 200 user=-`; only the
        # `billing: webhook type=...` line names the event.
        result = watch.scan([fly("2026-10-04T19:01:00Z", req("POST", "/billing/webhook", 200))])
        for key in ("session_completed", "invoice_paid", "access_granted", "payment_failed"):
            self.assertFalse(result.passed(key), key)

    def test_ansi_colour_and_a_glued_second_write_are_tolerated(self):
        glued = fly("2026-10-04T19:02:00Z",
                    req("GET", "/ufc/fight-night", 200, U) + 'INFO:     172.16.25.202:57438 - "GET /ufc/fight-night HTTP/1.1" 200 OK')
        self.assertTrue(watch.scan([glued]).passed("gate_open"))
        self.assertTrue(watch.scan([fly("2026-10-04T19:02:00Z", req("GET", "/ufc/fight-night", 200, U), colour=False)]).passed("gate_open"))

    def test_the_gate_step_needs_a_signed_in_200(self):
        anonymous = watch.scan([req("GET", "/ufc/fight-night", 401), req("GET", "/ufc/fight-night", 200)])
        self.assertFalse(anonymous.passed("gate_open"))
        # 503 (no UFC data on staging) is past the paid gate too; 401 and 402 are not.
        self.assertTrue(watch.scan([req("GET", "/ufc/fight-night", 503, U)]).passed("gate_open"))
        self.assertFalse(watch.scan([req("GET", "/ufc/fight-night", 401, U),
                                     req("GET", "/ufc/fight-night", 402, U)]).passed("gate_open"))
        refused = watch.scan([req("GET", "/ufc/fight-night", 402, U)])
        self.assertTrue(refused.passed("gate_refused"))
        self.assertFalse(refused.ok)

    def test_access_granted_needs_a_paid_through_date_not_just_a_payment_event(self):
        self.assertFalse(watch.scan([hook("checkout.session.completed")]).passed("access_granted"))
        self.assertFalse(watch.scan([hook("invoice.paid", paid="-")]).passed("access_granted"))
        self.assertTrue(watch.scan([hook("invoice.paid", paid=PAID)]).passed("access_granted"))
        self.assertTrue(watch.scan([hook("invoice.payment_succeeded", paid=PAID)]).passed("invoice_paid"))

    def test_return_needs_a_second_success_page_read_after_the_payment(self):
        one = watch.scan([hook("checkout.session.completed"), req("GET", "/signup/complete", 200)])
        self.assertFalse(one.passed("return_after_close"))
        two = watch.scan([hook("checkout.session.completed"),
                          req("GET", "/signup/complete", 200), req("GET", "/signup/complete", 200)])
        self.assertTrue(two.passed("return_after_close"))
        before = watch.scan([req("GET", "/signup/complete", 200), req("GET", "/signup/complete", 200)])
        self.assertFalse(before.passed("return_after_close"))
        expired = watch.scan([hook("checkout.session.completed"),
                              req("GET", "/signup/complete", 200), req("GET", "/signup/complete", 404)])
        self.assertFalse(expired.passed("return_after_close"))

    def test_cancel_needs_a_signed_in_200(self):
        self.assertFalse(watch.scan([req("POST", "/billing/cancel", 401)]).passed("cancel"))
        self.assertFalse(watch.scan([req("POST", "/billing/cancel", 200)]).passed("cancel"))
        self.assertTrue(watch.scan([req("POST", "/billing/cancel", 200, U)]).passed("cancel"))

    def test_checkout_request_paths(self):
        for path in ("/signup", "/billing/checkout", "/billing/tester-checkout"):
            self.assertTrue(watch.scan([req("POST", path, 200)]).passed("checkout_requested"), path)
        self.assertFalse(watch.scan([req("POST", "/signup", 400)]).passed("checkout_requested"))
        self.assertFalse(watch.scan([req("GET", "/signup", 200)]).passed("checkout_requested"))

    def test_problems_are_reported_as_warnings(self):
        result = watch.scan([
            req("POST", "/billing/webhook", 400),
            req("POST", "/billing/webhook", 501),
            req("POST", "/billing/cancel", 500, U),
            "billing: checkout provider call failed for user_id=3: RuntimeError('x')"])
        self.assertEqual(len(result.warnings), 4)

    def test_since_drops_older_timestamped_lines_only(self):
        old = fly("2026-10-04T18:00:00Z", hook("invoice.paid", paid=PAID))
        new = fly("2026-10-04T19:30:00Z", hook("checkout.session.completed"))
        bare = hook("customer.subscription.updated", paid=PAID)
        result = watch.scan([old, new, bare], since=watch.parse_since("2026-10-04T19:00:00Z"))
        self.assertFalse(result.passed("invoice_paid"))
        self.assertTrue(result.passed("session_completed"))
        self.assertTrue(result.passed("access_granted"))

    def test_command_line_reads_a_file_and_exits_nonzero_when_steps_are_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "staging.log"
            path.write_text(fly("2026-10-04T19:01:00Z", hook("invoice.paid", paid=PAID)) + "\n",
                            encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = watch.main([str(path)])
        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("PASS      invoice.paid processed", text)
        self.assertIn("NOT SEEN  invoice.payment_failed processed", text)
        self.assertIn("STEPS STILL MISSING", text)


class EmittedByTheRealCode(unittest.TestCase):
    """Lines produced by reqlog and by the real webhook handler."""

    def test_the_request_log_format_still_matches(self):
        line = reqlog.format_line(method="POST", path_template="/billing/cancel", status=200,
                                  latency_ms=3.2, user_id=7)
        self.assertTrue(watch.scan([line]).passed("cancel"))
        anon = reqlog.format_line(method="GET", path_template="/signup/complete", status=200,
                                  latency_ms=1.0)
        self.assertEqual(len(list(watch.REQUEST.finditer(anon))), 1)

    def test_the_real_webhook_lines_drive_the_event_steps(self):
        from tests import test_billing_acceptance_path as acceptance
        from tests import test_billing_failed_payment as failed
        if not acceptance.HAS_FASTAPI:
            self.skipTest("FastAPI is not installed")

        class Run(failed._FailedPaymentCase):
            def runTest(self):  # driven by hand below
                pass

        case = Run()
        case.setUp()
        try:
            captured = io.StringIO()
            with redirect_stderr(captured):
                user_id = case.signup()["user_id"]
                end = case.now + timedelta(days=30)
                case.webhook(case.completed_event(user_id))
                case.webhook(case.invoice_paid(end))
                case.webhook(case.invoice_failed())
            lines = [fly("2026-10-04T19:00:00Z", row, colour=False)
                     for row in captured.getvalue().splitlines()
                     if row.startswith("billing: webhook") or row.startswith("billing: invoice")]
        finally:
            case.tearDown()
        result = watch.scan(lines)
        for key in ("session_completed", "invoice_paid", "access_granted", "payment_failed"):
            self.assertTrue(result.passed(key), f"{key}: {lines}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
