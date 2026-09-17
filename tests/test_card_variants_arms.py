"""T2v: pins registration 17.1 -- the four arms differ from V2 in exactly the
named fields and in nothing else."""

import dataclasses
import unittest

from src.analysis import best_bets_card
from src.analysis import card_variants


class TestArmsDifferOnlyInNamedFields(unittest.TestCase):
    def _diff_fields(self, arm):
        base = dataclasses.asdict(best_bets_card.V2)
        other = dataclasses.asdict(arm)
        return {k for k in base if base[k] != other[k]}

    def test_a1_is_v2(self):
        self.assertIs(best_bets_card.A1, best_bets_card.V2)

    def test_a2_changes_only_subcap_and_rule_id(self):
        self.assertEqual(self._diff_fields(best_bets_card.A2), {"plus_money_subcap", "rule_id"})

    def test_a3_changes_only_markdown_base_edge_and_rule_id(self):
        self.assertEqual(self._diff_fields(best_bets_card.A3), {"markdown", "base_edge", "rule_id"})

    def test_a4_changes_only_those_three_fields_and_rule_id(self):
        self.assertEqual(
            self._diff_fields(best_bets_card.A4),
            {"markdown", "base_edge", "plus_money_subcap", "rule_id"},
        )

    def test_rule_ids_are_the_registered_strings(self):
        self.assertEqual(best_bets_card.A1.rule_id, "DAILY_CARD_BEST_BETS_V2")
        self.assertEqual(best_bets_card.A2.rule_id, "DAILY_CARD_BEST_BETS_V2_VAR_STRICT_NOCAP")
        self.assertEqual(best_bets_card.A3.rule_id, "DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_CAP3")
        self.assertEqual(best_bets_card.A4.rule_id, "DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_NOCAP")

    def test_published_arm_is_a1(self):
        self.assertEqual(card_variants.PUBLISHED_ARM, "A1")
        self.assertIs(card_variants.ARMS["A1"], best_bets_card.A1)

    def test_arms_mapping_has_all_four_in_order(self):
        self.assertEqual(list(card_variants.ARMS.keys()), ["A1", "A2", "A3", "A4"])


if __name__ == "__main__":
    unittest.main()
