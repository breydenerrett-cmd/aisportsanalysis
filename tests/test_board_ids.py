"""selection_id identity: stability, order-independence via kwargs, no floats."""

import unittest

from src.board.ids import MARKET_CATALOGUE, selection_id


class SelectionIdStabilityTests(unittest.TestCase):
    def test_stable_across_repeated_calls(self):
        a = selection_id(sport="mlb", market_key="h2h", side="home")
        b = selection_id(sport="mlb", market_key="h2h", side="home")
        self.assertEqual(a, b)

    def test_stable_regardless_of_kwarg_order(self):
        a = selection_id(sport="mlb", market_key="totals", side="over", line="8.5")
        b = selection_id(line="8.5", side="over", market_key="totals", sport="mlb")
        self.assertEqual(a, b)

    def test_is_16_hex_chars(self):
        sid = selection_id(sport="mlb", market_key="h2h", side="home")
        self.assertEqual(len(sid), 16)
        int(sid, 16)  # raises if not hex

    def test_different_sides_differ(self):
        home = selection_id(sport="mlb", market_key="h2h", side="home")
        away = selection_id(sport="mlb", market_key="h2h", side="away")
        self.assertNotEqual(home, away)

    def test_different_lines_differ(self):
        a = selection_id(sport="mlb", market_key="totals", side="over", line="8.5")
        b = selection_id(sport="mlb", market_key="totals", side="over", line="9.5")
        self.assertNotEqual(a, b)

    def test_line_as_string_and_equivalent_float_collide_by_design(self):
        # repr(8.5) == "8.5", so a caller who accidentally passes a float
        # collides with the canonical string form -- this is intentional
        # (the point is no SILENT drift, not that floats are forbidden here;
        # record.py's validator is what rejects floats in stored records).
        a = selection_id(sport="mlb", market_key="totals", side="over", line="8.5")
        b = selection_id(sport="mlb", market_key="totals", side="over", line=8.5)
        self.assertEqual(a, b)

    def test_field_concatenation_does_not_collide(self):
        # ("ab", "c") vs ("a", "bc") on subject fields must not hash equal.
        a = selection_id(
            sport="mlb", market_key="batter_hits", side="over",
            subject=("batter", "abc"),
        )
        b = selection_id(
            sport="mlb", market_key="batter_hits", side="over",
            subject=("bat", "terabc"),
        )
        self.assertNotEqual(a, b)

    def test_subject_none_differs_from_subject_present(self):
        a = selection_id(sport="mlb", market_key="batter_hits", side="over")
        b = selection_id(
            sport="mlb", market_key="batter_hits", side="over",
            subject=("batter", "123"),
        )
        self.assertNotEqual(a, b)


class MarketCatalogueTests(unittest.TestCase):
    REQUIRED_KEYS = {
        "h2h", "spreads", "totals", "team_totals", "alternate_spreads",
        "alternate_totals", "h2h_1st_5_innings", "spreads_1st_5_innings",
        "totals_1st_5_innings", "pitcher_strikeouts", "pitcher_outs",
        "pitcher_hits_allowed", "pitcher_earned_runs", "pitcher_walks",
        "batter_hits", "batter_total_bases", "batter_home_runs",
        "batter_rbis", "batter_runs", "batter_walks", "batter_strikeouts",
        "batter_stolen_bases", "batter_hits_runs_rbis",
    }

    def test_required_keys_present(self):
        missing = self.REQUIRED_KEYS - MARKET_CATALOGUE.keys()
        self.assertEqual(missing, set())

    def test_first_inning_markets_present(self):
        first_inning_keys = [k for k in MARKET_CATALOGUE if k.startswith("first_inning_")]
        self.assertGreater(len(first_inning_keys), 0)

    def test_declared_but_blocked_parlay_entry_present(self):
        blocked = [k for k, spec in MARKET_CATALOGUE.items() if spec.status == "BLOCKED"]
        self.assertGreater(len(blocked), 0)
        for key in blocked:
            self.assertIn("parlay", key.lower() + MARKET_CATALOGUE[key].correlation_group.lower())

    def test_every_entry_has_a_valid_status(self):
        for key, spec in MARKET_CATALOGUE.items():
            self.assertIn(
                spec.status, ("LIVE", "PROBE", "DECLARED", "BLOCKED"),
                msg=f"{key} has invalid status {spec.status!r}",
            )

    def test_every_entry_declares_settlement_rule(self):
        for key, spec in MARKET_CATALOGUE.items():
            self.assertTrue(spec.settlement_rule, msg=f"{key} missing settlement_rule")


if __name__ == "__main__":
    unittest.main()
