"""What the pages say about the founding offer and the upgrade prompt, run under node.

web/js/pricing.js + checkout.js (the founding line, built from GET /billing/offer) and web/js/upgrade.js
(the 402 `upgrade_required` prompt). Owner decision 2026-10-20: $14.99/mo for the first 50, $19.99 after;
the price is never tied to the record; sold out shows only the standard price; no fake scarcity.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web" / "js"

SCRIPT = r"""
import * as c from "./checkout.js";
import * as p from "./pricing.js";
import * as u from "./upgrade.js";
const on = c.checkoutState({ billing: { checkout: "on", trial_days: 7, price_cents: 1999 } });
const offer = (f) => ({ founding: f, standard: { price_cents: 1999 } });
const avail = (left) => ({ price_cents: 1499, cap: 50, taken: 50 - left, left, available: true });
const out = {};
out.plain = c.pricingNote(on);
out.founding = c.pricingNote(c.withOffer(on, offer(avail(37))));
out.hero = c.heroNote(c.withOffer(on, offer(avail(37))));
out.soldOut = c.pricingNote(c.withOffer(on, offer({ ...avail(0), available: false })));
out.heldLast = c.pricingNote(c.withOffer(on, offer({ ...avail(1), available: false })));
out.unset = c.pricingNote(c.withOffer(on, offer(null)));
out.garbage = c.pricingNote(c.withOffer(on, { founding: { available: true, left: "lots", cap: 50, price_cents: 1499 } }));
out.offState = c.pricingNote(c.withOffer(c.checkoutState(null), offer(avail(10))));
out.line = p.foundingOfferLine({ priceCents: 1499, cap: 50, left: 37 });
out.tier = p.BETA_TIER;
out.refusal = u.isUpgradeRefusal({ status: 402, detail: { error: "upgrade_required", feature: "ask" } });
out.notRefusal = [
  u.isUpgradeRefusal({ status: 402, detail: { error: "subscription_expired" } }),
  u.isUpgradeRefusal({ status: 403, detail: { error: "upgrade_required" } }),
  u.isUpgradeRefusal(null), u.isUpgradeRefusal({ status: 402, detail: "upgrade_required" }),
];
console.log("@@" + JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class FoundingCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "t.mjs").write_text(SCRIPT, encoding="utf-8")
        proc = subprocess.run(["node", "t.mjs"], cwd=cls._tmp.name, capture_output=True, text=True,
                              encoding="utf-8", timeout=60, env=dict(os.environ))
        assert proc.returncode == 0, proc.stderr[-2000:]
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        cls.out = json.loads(line[2:])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_founding_line_says_price_for_life_and_the_true_seats_left(self):
        self.assertEqual(self.out["line"], "Founding member: $14.99/mo for life · 37 of 50 left")
        self.assertIn("Founding member: $14.99/mo for life · 37 of 50 left", self.out["founding"])

    def test_the_trial_note_quotes_the_price_a_checkout_would_charge(self):
        self.assertIn("then $14.99/month", self.out["hero"])
        self.assertIn("then $19.99/month", self.out["plain"])

    def test_the_fine_print_says_for_life_means_while_subscribed(self):
        self.assertIn("for as long as you stay subscribed", self.out["founding"])

    def test_sold_out_or_held_or_unconfigured_shows_the_standard_price_only(self):
        for key in ("soldOut", "heldLast", "unset", "garbage", "plain"):
            with self.subTest(case=key):
                text = self.out[key]
                self.assertIn("$19.99", text)
                self.assertNotIn("14.99", text)
                self.assertNotIn("left", text)
                self.assertNotIn("Founding", text)

    def test_nothing_ties_the_price_to_the_record_or_results(self):
        blob = json.dumps(self.out).lower()
        for needle in ("public record grows", "if the record does", "rises as", "record turns"):
            self.assertNotIn(needle, blob)

    def test_checkout_off_never_mentions_the_founding_offer(self):
        self.assertNotIn("Founding", self.out["offState"])
        self.assertNotIn("14.99", self.out["offState"])

    def test_the_static_tier_is_the_standard_price_and_has_no_founding_story(self):
        tier = self.out["tier"]
        self.assertEqual((tier["price_cents"], tier["price_display"]), (1999, "$19.99/mo"))
        self.assertNotIn("founding price", tier["billing_note"])

    def test_upgrade_refusal_detection_is_exact(self):
        self.assertTrue(self.out["refusal"])
        self.assertEqual(self.out["notRefusal"], [False, False, False, False])


class NoForbiddenCopy(unittest.TestCase):
    FILES = ("upgrade.js", "pricing.js", "checkout.js", "billing.js")

    def test_no_bet_check_no_profit_or_edge_claims_in_the_new_copy(self):
        for name in self.FILES:
            text = (JS / name).read_text(encoding="utf-8").lower()
            with self.subTest(file=name):
                self.assertNotIn("bet check", text)
                self.assertNotIn("betcheck", text)
                self.assertIsNone(re.search(r"guaranteed|risk-free|we win|beat the (book|market)", text))

    def test_the_upgrade_prompt_keeps_the_21_plus_line(self):
        self.assertIn("21+", (JS / "upgrade.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
