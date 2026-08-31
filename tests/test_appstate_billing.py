"""src/appstate/billing.py: the billing ABSTRACTION and NullBillingProvider.

No real provider exists yet (docs/LAUNCH_DECISIONS.md Decision 2 is still
open) -- these tests pin that NullBillingProvider is honest about that,
not that it does anything billing-shaped.
"""

from __future__ import annotations

import unittest

from src.appstate import billing


class NullBillingProviderTests(unittest.TestCase):

    def setUp(self):
        self.provider = billing.NullBillingProvider()

    def test_create_checkout_returns_no_real_url_but_records_the_intent(self):
        result = self.provider.create_checkout(1, "beta")
        self.assertEqual(result, "")
        intents = self.provider.recorded_intents()
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].method, "create_checkout")
        self.assertEqual(intents[0].user_id, 1)
        self.assertEqual(intents[0].plan_id, "beta")

    def test_subscription_status_is_honestly_not_configured(self):
        sub = self.provider.subscription_status(1)
        self.assertEqual(sub.status, "not_configured")
        self.assertIsNone(sub.provider_ref)

    def test_cancel_is_idempotent(self):
        first = self.provider.cancel(1)
        second = self.provider.cancel(1)
        self.assertEqual(first.status, "canceled")
        self.assertEqual(second.status, "canceled")
        # Calling cancel twice must not raise or double-record a failure --
        # it's what makes a one-click-cancel button safe to double-click.
        self.assertEqual(
            [i.method for i in self.provider.recorded_intents()],
            ["cancel", "cancel"])

    def test_cancel_then_status_reflects_canceled(self):
        self.provider.cancel(5)
        sub = self.provider.subscription_status(5)
        self.assertEqual(sub.status, "canceled")

    def test_intents_are_per_instance_not_global(self):
        other = billing.NullBillingProvider()
        self.provider.create_checkout(1, "beta")
        self.assertEqual(other.recorded_intents(), [])

    def test_protocol_methods_present(self):
        """BillingProvider is a Protocol -- this pins that
        NullBillingProvider actually implements its full shape, since
        Protocol conformance is structural and easy to silently drift
        from."""
        for method in ("create_checkout", "subscription_status", "cancel"):
            self.assertTrue(callable(getattr(self.provider, method)))


if __name__ == "__main__":
    unittest.main()
