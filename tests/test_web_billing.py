"""The billing view must be able to actually take money.

WHY THIS FILE EXISTS
---------------------
api/billing.py has had a complete checkout endpoint -- allowlisted plan id,
rate limited, Stripe-hosted URL -- since before launch. web/js/billing.js
rendered `renderUnknown(payload)`, the raw status JSON, and its own docstring
said it "does not attempt checkout here." So the server could take money and
the product had no button that asked for it, and that view is the landing
target every paid surface's 402 redirects to. A prospect who hit the paywall
arrived at a JSON dump.

Nothing failed. No test was red. No error was logged. The revenue path simply
did not exist, which is the same shape as the cadence gate that ran nowhere
and the gameflow ingest nothing called -- a wired-looking system with one
silent hole in the middle.

These tests pin the parts that make it a payment path rather than a page
about payments.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BILLING_JS = REPO / "web" / "js" / "billing.js"
PRICING_JS = REPO / "web" / "js" / "pricing.js"
BILLING_API = REPO / "api" / "billing.py"
APPSTATE_BILLING = REPO / "src" / "appstate" / "billing.py"


class BillingViewTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BILLING_JS.is_file(), "web/js/billing.js is missing")
        self.text = BILLING_JS.read_text(encoding="utf-8")
        # Comments stripped before matching, for the reason
        # tests/test_cadence_is_deployed.py learned the hard way: this file's
        # header discusses checkout at length, so a scan of the raw text
        # passes on the documentation even if every call is deleted.
        lines = []
        in_block = False
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("/*"):
                in_block = True
            if in_block:
                if "*/" in stripped:
                    in_block = False
                continue
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            lines.append(line)
        self.code = "\n".join(lines)

    def test_it_calls_the_checkout_endpoint(self):
        self.assertIn(
            "/billing/checkout", self.code,
            "the billing view never calls POST /billing/checkout, so there "
            "is no way for a customer to start paying")

    def test_it_redirects_to_the_hosted_checkout_url(self):
        """The endpoint answers {status:'redirect', checkout_url}. A view
        that reads the status but never navigates is the old failure with a
        button bolted on."""
        self.assertIn("checkout_url", self.code)
        self.assertTrue(
            re.search(r"location\.(assign|href)", self.code),
            "the view never navigates to the returned checkout_url")

    def test_it_never_collects_card_details_on_this_origin(self):
        """Card data belongs on Stripe's origin and nowhere else."""
        for banned in ("card", "cvc", "cvv", "expiry", "credit-card",
                       "cardnumber"):
            self.assertNotIn(
                banned, self.code.lower(),
                f"billing.js mentions {banned!r}; card details must only ever "
                f"be entered on Stripe's hosted checkout")

    def test_it_offers_cancel_and_reactivate(self):
        """Both endpoints exist and a subscriber needs both. A cancel button
        that isn't there is a support ticket; one that can't be undone is a
        lost customer."""
        self.assertIn("/billing/cancel", self.code)
        self.assertIn("/billing/reactivate", self.code)

    def test_not_configured_does_not_render_a_dead_button(self):
        """A deploy without Stripe wired must say so rather than show a
        Subscribe button that fails on click."""
        self.assertIn("not_configured", self.code,
                      "the view does not handle the not_configured answer, "
                      "so an unwired deploy shows a button that cannot work")

    def test_the_plan_id_comes_from_the_shared_price_source(self):
        """A hardcoded plan id here would drift from the server allowlist
        and every checkout would 400."""
        self.assertIn("BETA_TIER", self.code,
                      "billing.js does not import the shared pricing tier")
        self.assertNotIn('plan_id: "beta"', self.code,
                         "plan_id is hardcoded rather than read from "
                         "pricing.js's BETA_TIER")

    def test_the_client_plan_id_matches_the_server_allowlist(self):
        """api/billing.py rejects any plan_id but billing.BETA_PLAN_ID."""
        client = re.search(r'id:\s*"([^"]+)"',
                           PRICING_JS.read_text(encoding="utf-8"))
        server = re.search(r'BETA_PLAN_ID\s*=\s*"([^"]+)"',
                           APPSTATE_BILLING.read_text(encoding="utf-8"))
        self.assertIsNotNone(client, "no id on pricing.js's BETA_TIER")
        self.assertIsNotNone(server, "no BETA_PLAN_ID in appstate/billing.py")
        self.assertEqual(
            client.group(1), server.group(1),
            "the plan id the view sends is not the one the API accepts; "
            "every checkout would be refused with a 400")

    def test_the_displayed_price_matches_what_stripe_charges(self):
        """Showing one number and charging another is the exact dishonesty
        this product exists to reject."""
        shown = re.search(r"price_cents:\s*(\d+)",
                          PRICING_JS.read_text(encoding="utf-8"))
        charged = re.search(r"BETA_PLAN_PRICE_CENTS\s*=\s*(\d+)",
                            APPSTATE_BILLING.read_text(encoding="utf-8"))
        self.assertIsNotNone(shown, "no price_cents in pricing.js")
        if charged is None:
            self.skipTest("BETA_PLAN_PRICE_CENTS not found in "
                          "src/appstate/billing.py")
        self.assertEqual(int(shown.group(1)), int(charged.group(1)),
                         "the price on the page is not the price charged")

    def test_every_data_hook_is_unique(self):
        """The bug this test exists for: the Subscribe PANEL and the
        Subscribe BUTTON both carried data-hook="billing-subscribe". The
        panel comes first in the document, so every querySelector -- mine in
        the browser, and any future e2e test's -- matched the <section>.
        Clicking it did nothing: no request, no navigation, no error, no
        console warning. The string-grep tests above all stayed green while
        the payment button was inert, which is precisely why greping for
        "/billing/checkout" is not evidence that checkout can be reached.
        """
        hooks = re.findall(r'"data-hook":\s*"([^"]+)"', self.code)
        duplicated = sorted({h for h in hooks if hooks.count(h) > 1})
        self.assertEqual(
            [], duplicated,
            f"data-hook values are reused in billing.js: {duplicated}. The "
            f"first element in the document wins every selector, so a hook "
            f"shared between a container and its button silently makes the "
            f"button unclickable")

    def test_billing_dates_are_not_run_through_the_eastern_formatter(self):
        """Stripe period boundaries arrive at UTC midnight. dom.js's
        formatEasternDate shifts those back four or five hours -- into the
        previous day -- so `2026-10-09T00:00:00Z` rendered as "OCT 8" and
        told a paying customer their access ended a day early. Game times
        belong in Eastern; billing timestamps do not."""
        self.assertNotIn(
            "formatEasternDate", self.code,
            "billing.js formats billing timestamps with the Eastern game-time "
            "formatter, which renders a UTC-midnight period end as the "
            "previous day")

    def test_a_failed_payment_is_not_described_as_renewing(self):
        """"Payment failed" beside "Renews Sep 19" is a contradiction, and
        the reassuring half is the false half."""
        self.assertIn(
            "past_due", self.code,
            "billing.js does not distinguish a failed payment, so it tells a "
            "past_due customer their subscription renews on schedule")

    def test_the_api_still_exposes_what_this_view_calls(self):
        """Pins the two sides together: a renamed route would leave the view
        calling a 404 with no test noticing."""
        api = BILLING_API.read_text(encoding="utf-8")
        for route in ("/billing/checkout", "/billing/status",
                      "/billing/cancel", "/billing/reactivate"):
            self.assertIn(route, api,
                          f"api/billing.py no longer serves {route}, which "
                          f"web/js/billing.js calls")


if __name__ == "__main__":
    unittest.main()
