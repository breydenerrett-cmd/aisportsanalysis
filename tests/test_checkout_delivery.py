"""A customer must never be charged for access we cannot deliver.

WHY THIS FILE EXISTS
---------------------
`deploy/fly.production.toml` carried no PUBLIC_BASE_URL. With billing switched
on, `StripeBillingProvider.create_checkout` would have built a session whose
`success_url` pointed at `https://example.invalid` -- Stripe takes the card,
the browser is sent to a domain that does not exist, and that redirect is the
ONLY route from a payment to the access token it buys, because this repo has
no email sender at all (api/signup.py's "NO-EMAIL-SENDER ACTIVATION BRIDGE").

Charged. Landed nowhere. No token, no email, no way to ask.

Nothing was broken in any testable sense: the checkout code was correct, the
webhook handler was correct, `scripts/funnel_smoke.sh` passed end to end. One
environment variable was absent from one deploy file, and the failure only
existed in production, only for real customers, and only after their money
was gone.

These tests pin the refusal. They are about the CHARGE, not the config.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from src.appstate import apphealth, billing


class DeliveryReadinessTests(unittest.TestCase):
    """`checkout_delivery_ready` returns None when a payment can be honoured,
    and a sentence saying why not when it cannot."""

    def test_a_real_https_base_url_is_ready(self):
        self.assertIsNone(billing.checkout_delivery_ready("https://linehound.app"))

    def test_a_trailing_slash_is_not_a_problem(self):
        self.assertIsNone(billing.checkout_delivery_ready("https://linehound.app/"))

    def test_the_placeholder_is_refused(self):
        reason = billing.checkout_delivery_ready(billing.DEFAULT_PUBLIC_BASE_URL)
        self.assertIsNotNone(reason, "example.invalid was accepted as a "
                                     "redirect target for a paying customer")
        self.assertIn("access token", reason)

    def test_an_empty_base_url_is_refused(self):
        self.assertIsNotNone(billing.checkout_delivery_ready(""))

    def test_a_bare_hostname_is_refused(self):
        """Stripe requires an absolute URL; 'linehound.app' is not one, and a
        session built with it fails after the customer has already entered
        their card."""
        reason = billing.checkout_delivery_ready("linehound.app")
        self.assertIsNotNone(reason)
        self.assertIn("absolute", reason)

    def test_it_reads_the_environment_when_given_no_argument(self):
        with mock.patch.dict(os.environ,
                             {billing.ENV_PUBLIC_BASE_URL: "https://linehound.app"}):
            self.assertIsNone(billing.checkout_delivery_ready())
        with mock.patch.dict(os.environ, {billing.ENV_PUBLIC_BASE_URL: ""}):
            self.assertIsNotNone(billing.checkout_delivery_ready())

    def test_no_reason_string_leaks_a_secret_value(self):
        """Health and API responses carry these strings. They may name the
        VARIABLE; they may never carry its contents, nor any Stripe key."""
        for value in ("", billing.DEFAULT_PUBLIC_BASE_URL, "linehound.app"):
            reason = billing.checkout_delivery_ready(value) or ""
            self.assertNotIn("sk_", reason)
            self.assertNotIn("whsec_", reason)
            self.assertIn(billing.ENV_PUBLIC_BASE_URL, reason)


class CreateCheckoutRefusesTests(unittest.TestCase):
    """The load-bearing test: no Stripe call is made at all."""

    def _provider(self):
        calls = []

        def transport(method, url, **kwargs):
            calls.append((method, url))
            raise AssertionError(
                "create_checkout reached Stripe with an undeliverable "
                "success_url -- a customer would have been charged and sent "
                "to a domain that does not exist")

        return billing.StripeBillingProvider(
            api_key="sk_test_not_a_real_key", transport=transport), calls

    def test_it_refuses_before_calling_stripe(self):
        provider, calls = self._provider()
        with mock.patch.dict(
                os.environ,
                {billing.ENV_PUBLIC_BASE_URL: billing.DEFAULT_PUBLIC_BASE_URL}):
            with self.assertRaises(billing.BillingProviderNotConfigured):
                provider.create_checkout(1, "beta")
        self.assertEqual([], calls,
                         "a Stripe request was made despite the refusal")

    def test_it_refuses_when_the_variable_is_absent_entirely(self):
        provider, calls = self._provider()
        env = {k: v for k, v in os.environ.items()
               if k != billing.ENV_PUBLIC_BASE_URL}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(billing.BillingProviderNotConfigured):
                provider.create_checkout(1, "beta")
        self.assertEqual([], calls)


class HealthReportsItTests(unittest.TestCase):
    """An operator must be able to learn this from /health, not from a
    customer who tried to buy something."""

    def _report(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            return apphealth.report()

    def test_null_provider_reads_off_not_broken(self):
        """Billing deliberately disabled is a different fact from billing
        broken. Flattening them makes the line useless on staging."""
        report = self._report({
            billing.ENV_BILLING_PROVIDER: billing.DEFAULT_BILLING_PROVIDER})
        self.assertEqual("off", report["checkout"]["status"])
        self.assertNotIn("checkout", " ".join(report["reasons"]))

    def test_stripe_without_a_base_url_reads_broken_and_degrades_health(self):
        report = self._report({
            billing.ENV_BILLING_PROVIDER: "stripe",
            billing.ENV_PUBLIC_BASE_URL: billing.DEFAULT_PUBLIC_BASE_URL})
        self.assertEqual("broken", report["checkout"]["status"])
        self.assertEqual("degraded", report["status"])
        self.assertTrue(any("checkout" in r for r in report["reasons"]))

    def test_stripe_with_a_real_base_url_reads_ok(self):
        report = self._report({
            billing.ENV_BILLING_PROVIDER: "stripe",
            billing.ENV_PUBLIC_BASE_URL: "https://linehound.app"})
        self.assertEqual("ok", report["checkout"]["status"])
        self.assertFalse(any("checkout" in r for r in report["reasons"]))

    def test_health_never_500s_on_this_check(self):
        """/health is the one endpoint that must always answer."""
        with mock.patch.object(billing, "checkout_delivery_ready",
                               side_effect=RuntimeError("boom")):
            report = self._report({billing.ENV_BILLING_PROVIDER: "stripe"})
        self.assertEqual("unknown", report["checkout"]["status"])


class SilentWaitlistTests(unittest.TestCase):
    """"Waitlisted" must mean waitlisted, not "this deploy is broken".

    `_attempt_checkout` returning None used to mean two different things:
    billing deliberately off (waitlist honestly) and billing switched on but
    misconfigured (the person came to buy and was told "we'll email you when
    a beta spot opens up" by a codebase with no email sender). A broken
    production deploy looked exactly like a closed beta, and would have kept
    looking like one until somebody happened to try to pay.
    """

    def setUp(self):
        # CI runs this suite WITHOUT api/requirements.txt -- fastapi
        # lives only in api/'s dependencies (tests/test_api_boundary.py
        # exists to prove src/ never needs it). Skip rather than error,
        # so the api-less job stays green and still runs everything else
        # in this file.
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest('fastapi is not installed in this job')
        from api import signup as signup_mod
        self.signup = signup_mod

    def _attempt(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            return self.signup._attempt_checkout(1)

    def test_billing_off_still_waitlists_honestly(self):
        """The default state while there is nothing to sell. Unchanged."""
        env = {k: v for k, v in os.environ.items()
               if k not in (billing.ENV_BILLING_PROVIDER,)}
        env[billing.ENV_BILLING_PROVIDER] = billing.DEFAULT_BILLING_PROVIDER
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(self.signup._attempt_checkout(1))

    def test_billing_on_but_no_price_id_is_a_misconfiguration_not_a_waitlist(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("STRIPE_")}
        env[billing.ENV_BILLING_PROVIDER] = "stripe"
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(self.signup._CheckoutMisconfigured):
                self.signup._attempt_checkout(1)

    def test_billing_on_but_undeliverable_is_a_misconfiguration(self):
        """The PUBLIC_BASE_URL case: a price id exists, the provider refuses
        because a paid customer would land nowhere."""
        with mock.patch.object(billing, "beta_plan_stripe_price_id",
                               return_value="price_abc"), \
             mock.patch.object(billing, "get_billing_provider") as get_provider:
            get_provider.return_value.create_checkout.side_effect = (
                billing.BillingProviderNotConfigured("PUBLIC_BASE_URL is unset"))
            with mock.patch.dict(os.environ,
                                 {billing.ENV_BILLING_PROVIDER: "stripe"}):
                with self.assertRaises(self.signup._CheckoutMisconfigured):
                    self.signup._attempt_checkout(1)

    def test_the_customer_is_not_told_to_try_again(self):
        """Trying again will not fix a config error, and saying it might is
        the same false comfort as an un-emailable waitlist."""
        from src.appstate import users as users_store
        user = mock.Mock(spec=users_store.User)
        user.id, user.status = 1, "pending_payment"
        with mock.patch.object(self.signup, "_attempt_checkout",
                               side_effect=self.signup._CheckoutMisconfigured):
            body = self.signup._respond_for(user)
        self.assertEqual("error", body["status"])
        self.assertNotIn("try again", body["message"])
        self.assertIn("nothing has been charged", body["message"])

    def test_no_config_detail_reaches_the_caller(self):
        from src.appstate import users as users_store
        user = mock.Mock(spec=users_store.User)
        user.id, user.status = 1, "pending_payment"
        with mock.patch.object(self.signup, "_attempt_checkout",
                               side_effect=self.signup._CheckoutMisconfigured):
            body = self.signup._respond_for(user)
        for leak in ("PUBLIC_BASE_URL", "STRIPE", "BILLING_PROVIDER",
                     "example.invalid"):
            self.assertNotIn(leak, body["message"])


class ProductionConfigTests(unittest.TestCase):
    """The deploy file itself. The guard above stops the charge; this stops
    production from shipping in the refusing state at all."""

    def test_production_never_enables_the_public_demo(self):
        """APP_PUBLIC_DEMO=1 does two things, and on production both are
        catastrophic: api/app.py drops the paid dependency from every game
        surface, and web/js/betcheck.js routes anonymous visitors to the
        UNCAPPED /betcheck instead of the three-free-checks route. So the
        entire paid product is given away AND the paywall we are asking
        people to cross silently stops existing.

        Staging sets it on purpose -- it is a demo, and it is how the only
        person with the URL can see anything without a token. That is
        exactly why this test exists: the two configs must not converge by
        somebody copying one to the other.
        """
        from pathlib import Path
        toml = Path(__file__).resolve().parents[1] / "deploy" / "fly.production.toml"
        if not toml.is_file():
            self.skipTest("deploy/fly.production.toml not present")
        code = "\n".join(l for l in toml.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertNotIn(
            "APP_PUBLIC_DEMO", code,
            "production sets APP_PUBLIC_DEMO -- the paid product would be "
            "free to anyone with the URL and the free-check paywall would "
            "never fire")

    def test_staging_still_has_it(self):
        """Belt and braces on the reverse mistake: 'fixing' the line above
        by stripping it from staging too would lock out the only people who
        can currently see the product at all."""
        from pathlib import Path
        toml = Path(__file__).resolve().parents[1] / "deploy" / "fly.staging.toml"
        if not toml.is_file():
            self.skipTest("deploy/fly.staging.toml not present")
        self.assertIn("APP_PUBLIC_DEMO", toml.read_text(encoding="utf-8"))

    def test_production_toml_sets_a_public_base_url(self):
        from pathlib import Path
        toml = Path(__file__).resolve().parents[1] / "deploy" / "fly.production.toml"
        if not toml.is_file():
            self.skipTest("deploy/fly.production.toml not present")
        text = toml.read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertIn(
            billing.ENV_PUBLIC_BASE_URL, code,
            "deploy/fly.production.toml does not set PUBLIC_BASE_URL, so "
            "checkout on production will refuse every payment (or, before "
            "the guard existed, take one it could not deliver)")
        self.assertNotIn(
            billing.DEFAULT_PUBLIC_BASE_URL, code,
            "production still points at the placeholder domain")


if __name__ == "__main__":
    unittest.main()
