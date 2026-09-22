"""T13 cutover (docs/PREREG_CARD_V2.md, owner directive 2026-09-22 over the
frozen -203 Cubs pick): the PUBLIC MLB card is V2 from `card.CUTOVER_DATE`,
V1 keeps running in shadow only, and no MLB moneyline pick -- whichever rule
built it -- may ever be published at -200 or worse.

Every test runs against a temporary ledger path. None of them touch the real
`evidence/` files.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.appstate import card_ledger
from src.report import card as card_mod
from tests.test_card_ledger import _card, _pick


class CutoverConstants(unittest.TestCase):
    """The switch itself: `ACTIVE_CARD_RULE` and `CUTOVER_DATE` must move
    together, and the date must be one V2 can actually serve (on or after
    the registration commit's own date)."""

    def test_active_card_rule_is_v2(self):
        self.assertEqual("v2", card_mod.ACTIVE_CARD_RULE)

    def test_cutover_date_is_set_and_not_before_registration(self):
        self.assertIsNotNone(card_mod.CUTOVER_DATE)
        self.assertGreaterEqual(card_mod.CUTOVER_DATE, "2026-09-22")


class V1StorePathRouting(unittest.TestCase):
    """`card.v1_store_path`: the one place a V1 publish/settle call decides
    which file it writes to (registration R3 -- `evidence/cards_v1.jsonl`
    "receives no rows dated on or after the cutover date")."""

    def test_before_cutover_uses_the_original_store(self):
        self.assertEqual(card_ledger.CARD_STORE,
                          card_mod.v1_store_path("2026-09-22"))

    def test_on_and_after_cutover_uses_the_shadow_store(self):
        self.assertEqual(card_ledger.CARD_STORE_V1_SHADOW,
                          card_mod.v1_store_path(card_mod.CUTOVER_DATE))
        self.assertEqual(card_ledger.CARD_STORE_V1_SHADOW,
                          card_mod.v1_store_path("2026-12-25"))

    def test_the_two_stores_are_different_files(self):
        self.assertNotEqual(card_ledger.CARD_STORE, card_ledger.CARD_STORE_V1_SHADOW)


class PublishAllRoutesV1ToShadowAfterCutover(unittest.TestCase):
    """`card.publish_all` builds V1 alongside V2 and the shadows from one
    fetched board (registration 17.6) -- its own V1 call must resolve the
    same store `v1_store_path` would, not always the original file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_v1_card_after_cutover_lands_in_the_shadow_store(self):
        # The frozen parameter file (data/processed/card_v2_frozen_params.json)
        # DOES exist in this checkout (T0a), so publish_all's V2/shadow
        # branches run for real too -- every store constant they write to
        # is patched to a temp path here, not only V1's two, so this test
        # can never repeat the mistake of writing a real row into
        # evidence/cards_v2*.jsonl (found and cleaned up once already while
        # building this test).
        import unittest.mock as mock

        v1_card = _card(date=card_mod.CUTOVER_DATE, picks=[_pick(price=-150)])
        temp_path = lambda name: os.path.join(self._tmp.name, name)  # noqa: E731
        with mock.patch.object(card_ledger, "CARD_STORE_V1_SHADOW",
                              temp_path("cards_v1_shadow.jsonl")), \
             mock.patch.object(card_ledger, "CARD_STORE",
                              temp_path("cards_v1.jsonl")), \
             mock.patch.object(card_ledger, "CARD_STORE_V2",
                              temp_path("cards_v2.jsonl")), \
             mock.patch.object(card_ledger, "CARD_STORE_V2_SHADOW_A",
                              temp_path("cards_v2_shadow_a.jsonl")), \
             mock.patch.object(card_ledger, "CARD_STORE_V2_SHADOW_C",
                              temp_path("cards_v2_shadow_c.jsonl")), \
             mock.patch.object(card_ledger, "CARD_STORE_V2_SHADOW_E",
                              temp_path("cards_v2_shadow_e.jsonl")):
            card_mod.publish_all(card_mod.CUTOVER_DATE, v1_card=v1_card)
            self.assertIsNone(card_ledger.published_row(
                card_mod.CUTOVER_DATE, path=card_ledger.CARD_STORE))
            self.assertIsNotNone(card_ledger.published_row(
                card_mod.CUTOVER_DATE, path=card_ledger.CARD_STORE_V1_SHADOW))
            # And confirm none of this leaked into the real evidence/ files.
            self.assertFalse(os.path.exists(os.path.join("evidence", "cards_v2.jsonl")))


class MoneylinePriceGuard(unittest.TestCase):
    """The hard guard added directly to `card_ledger.publish` (and mirrored
    in `publish_v2`): no MLB moneyline pick at -200 or worse is ever
    written, regardless of what any one rule's own gates did or did not
    catch. This is the mechanism that ends the exact failure the owner
    reported -- the -203 Cubs pick -- for every rule that ever reaches this
    file, not only V2."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def test_a_moneyline_pick_at_exactly_the_floor_is_blocked(self):
        # A single-pick card that is entirely blocked raises rather than
        # publishing an empty card -- see
        # test_a_card_that_is_entirely_blocked_raises_rather_than_publishing_empty
        # for that behaviour on its own. Blocking itself, on a card that
        # still has a legal pick left, is covered by
        # test_mixed_card_keeps_the_legal_pick_and_blocks_only_the_illegal_one.
        card = _card(picks=[_pick(price=-200)])
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.publish(card, path=self.path)

    def test_a_moneyline_pick_worse_than_the_floor_is_blocked(self):
        # The exact reported case: -203 is the Cubs pick the owner flagged
        # on 2026-09-22.
        card = _card(picks=[_pick(price=-203)])
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.publish(card, path=self.path)

    def test_a_moneyline_pick_inside_the_floor_publishes_normally(self):
        card = _card(picks=[_pick(price=-199)])
        row = card_ledger.publish(card, path=self.path)
        self.assertEqual(1, row["n_picks"])
        self.assertEqual([], row["blocked_by_price_guard"])

    def test_a_run_line_at_a_short_price_is_not_touched(self):
        # The guard names moneylines only, deliberately -- a run line at a
        # short price is a different bet with different arithmetic and is
        # not what the owner's ruling refers to.
        card = _card(picks=[_pick(price=-250, market="run_line")])
        row = card_ledger.publish(card, path=self.path)
        self.assertEqual(1, row["n_picks"])
        self.assertEqual([], row["blocked_by_price_guard"])

    def test_mixed_card_keeps_the_legal_pick_and_blocks_only_the_illegal_one(self):
        card = _card(picks=[
            _pick(price=-150, game_pk=1001, label="OK"),
            _pick(price=-210, game_pk=1002, label="BLOCKED"),
        ])
        row = card_ledger.publish(card, path=self.path)
        self.assertEqual(1, row["n_picks"])
        self.assertEqual(-150, row["picks"][0]["price"])
        self.assertEqual(1, len(row["blocked_by_price_guard"]))
        self.assertEqual(-210, row["blocked_by_price_guard"][0]["price"])

    def test_a_card_that_is_entirely_blocked_raises_rather_than_publishing_empty(self):
        # An all-refused card is a rule producing nothing but illegal picks,
        # not the ordinary "no bet cleared today" empty state -- it should
        # be loud, not silently swallowed into a normal empty publish.
        card = _card(picks=[_pick(price=-203)])
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.publish(card, path=self.path)

    def test_the_v1_shadow_store_is_exempt_so_v1_is_never_retrofitted(self):
        # Orchestrator review 2026-09-22: after cutover V1 runs in shadow as
        # a frozen rule. Blocking its -200 picks there would edit V1's
        # record midstream. The guard is for what customers are shown.
        shadow = os.path.join(self._tmp.name, "cards_v1_shadow.jsonl")
        with mock.patch.object(card_ledger, "CARD_STORE_V1_SHADOW", shadow):
            row = card_ledger.publish(_card(picks=[_pick(price=-203)]), path=shadow)
        self.assertEqual(1, row["n_picks"])
        self.assertEqual(-203, row["picks"][0]["price"])

    def test_the_guard_is_mlb_only_nfl_moneylines_are_untouched(self):
        # The owner's -200 ruling covers every sport, but NFL enforces it in
        # its own rule (src/analysis/nfl_value.py WORST_PRICE = -200). This
        # MLB-scoped guard must not touch sport="nfl" rows.
        nfl_pick = dict(_pick(price=-250), sport="nfl")
        card = _card(picks=[nfl_pick])
        row = card_ledger.publish(card, path=self.path, sport="nfl")
        self.assertEqual(1, row["n_picks"])
        self.assertEqual([], row["blocked_by_price_guard"])


if __name__ == "__main__":
    unittest.main()
