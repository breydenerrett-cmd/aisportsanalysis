"""tests/test_postseason_config.py -- C1b: the verified tournament
configuration (src/analysis/postseason_config.py).

postseason_config.py is deliberately dependency-free (pure stdlib
constants, no imports of its own), so this file is where its game_type
strings get cross-checked against src.providers.mlb's canonical codes, and
where the verification record itself (what was checked, when, from where)
is asserted to actually be present -- not just written in a docstring
nobody tests.
"""

from __future__ import annotations

import unittest

from src.analysis import postseason_config as pc
from src.providers import mlb


class FormatVerificationRecordTests(unittest.TestCase):
    def test_verification_record_names_its_sources_and_retrieval_date(self):
        self.assertEqual("2026-09-24", pc.FORMAT_VERIFICATION["retrieved"])
        self.assertGreaterEqual(len(pc.FORMAT_VERIFICATION["sources"]), 2)
        for url in pc.FORMAT_VERIFICATION["sources"]:
            self.assertTrue(url.startswith("https://www.mlb.com/"), url)

    def test_world_series_home_field_fact_is_recorded_as_record_based(self):
        fact = pc.FORMAT_VERIFICATION["facts"]["world_series_home_field"]
        self.assertIn("REGULAR-SEASON RECORD", fact)
        self.assertIn("NOT", fact)

    def test_division_series_pairing_fact_records_no_reseeding(self):
        fact = pc.FORMAT_VERIFICATION["facts"]["division_series_pairing"]
        self.assertIn("NOT re-seeded", fact)

    def test_unresolved_tiebreak_is_named_rather_than_silently_dropped(self):
        self.assertIn("world_series_tiebreak_if_records_equal",
                      pc.FORMAT_VERIFICATION["facts"])


class RoundFormatShapeTests(unittest.TestCase):
    def test_best_of_and_k_and_pattern_length_are_mutually_consistent(self):
        for rnd in pc.ROUNDS_IN_ORDER:
            self.assertEqual(rnd["best_of"], 2 * rnd["k"] - 1, rnd["name"])
            self.assertEqual(rnd["best_of"], len(rnd["home_pattern"]), rnd["name"])

    def test_wild_card_is_best_of_three_all_home_for_the_higher_seed(self):
        self.assertEqual(3, pc.WILD_CARD["best_of"])
        self.assertEqual(2, pc.WILD_CARD["k"])
        self.assertEqual((True, True, True), pc.WILD_CARD["home_pattern"])
        self.assertEqual(pc.HOME_FIELD_BY_SEED, pc.WILD_CARD["home_field_by"])

    def test_division_series_is_best_of_five_2_2_1(self):
        self.assertEqual(5, pc.DIVISION_SERIES["best_of"])
        self.assertEqual(3, pc.DIVISION_SERIES["k"])
        self.assertEqual((True, True, False, False, True),
                         pc.DIVISION_SERIES["home_pattern"])
        self.assertEqual(pc.HOME_FIELD_BY_SEED, pc.DIVISION_SERIES["home_field_by"])

    def test_lcs_is_best_of_seven_2_3_2_seed_based(self):
        self.assertEqual(7, pc.LCS["best_of"])
        self.assertEqual(4, pc.LCS["k"])
        self.assertEqual((True, True, False, False, False, True, True),
                         pc.LCS["home_pattern"])
        self.assertEqual(pc.HOME_FIELD_BY_SEED, pc.LCS["home_field_by"])

    def test_world_series_is_best_of_seven_2_3_2_shape_but_record_based(self):
        """The one fact this task's own prompt implied was seed-based but
        verification showed is not: the World Series home/away SHAPE
        matches the LCS exactly, but who gets home field does not follow
        the same rule."""
        self.assertEqual(7, pc.WORLD_SERIES["best_of"])
        self.assertEqual(4, pc.WORLD_SERIES["k"])
        self.assertEqual(pc.LCS["home_pattern"], pc.WORLD_SERIES["home_pattern"])
        self.assertEqual(pc.HOME_FIELD_BY_RECORD, pc.WORLD_SERIES["home_field_by"])
        self.assertNotEqual(pc.WORLD_SERIES["home_field_by"], pc.LCS["home_field_by"])


class SeedingStructureTests(unittest.TestCase):
    def test_bye_seeds_are_one_and_two(self):
        self.assertEqual((1, 2), pc.BYE_SEEDS)

    def test_wild_card_pairings_cover_seeds_three_through_six_exactly_once(self):
        covered = []
        for pairing in pc.WILD_CARD_PAIRINGS.values():
            covered.extend(pairing)
        self.assertEqual({3, 4, 5, 6}, set(covered))
        self.assertEqual(4, len(covered), "a seed appears in more than one pairing")

    def test_wild_card_pairings_put_the_seed_hosting_first(self):
        for key, (hi, lo) in pc.WILD_CARD_PAIRINGS.items():
            self.assertLess(hi, lo, key)

    def test_field_seeds_is_bye_seeds_plus_wild_card_pairing_seeds(self):
        covered = set(pc.BYE_SEEDS)
        for pairing in pc.WILD_CARD_PAIRINGS.values():
            covered.update(pairing)
        self.assertEqual(set(pc.FIELD_SEEDS), covered)

    def test_division_series_opponent_rule_covers_both_bye_seeds_and_both_wc_series(self):
        self.assertEqual(set(pc.BYE_SEEDS), set(pc.DS_OPPONENT_SERIES_FOR_SEED))
        self.assertEqual(set(pc.WILD_CARD_SERIES_KEYS),
                         set(pc.DS_OPPONENT_SERIES_FOR_SEED.values()))

    def test_the_two_bye_seeds_do_not_share_a_wild_card_opponent_series(self):
        self.assertNotEqual(pc.DS_OPPONENT_SERIES_FOR_SEED[1],
                            pc.DS_OPPONENT_SERIES_FOR_SEED[2])


class GameTypeCodesMatchProviderTests(unittest.TestCase):
    """postseason_config.py deliberately does not import src.providers.mlb
    (kept dependency-free), but its game_type strings must still agree with
    that module's canonical codes -- the cross-check promised in
    postseason_config's own module docstring."""

    def test_every_round_game_type_is_decisive_in_the_provider(self):
        for rnd in pc.ROUNDS_IN_ORDER:
            self.assertIn(rnd["game_type"], mlb.DECISIVE_GAME_TYPES, rnd["name"])

    def test_round_game_types_are_exactly_the_non_regular_decisive_codes(self):
        non_regular_decisive = mlb.DECISIVE_GAME_TYPES - {mlb.GAME_TYPE_REGULAR, "P"}
        round_types = {rnd["game_type"] for rnd in pc.ROUNDS_IN_ORDER}
        self.assertEqual(non_regular_decisive, round_types)

    def test_calendar_game_types_match_round_game_types(self):
        by_round_name = {
            "wild_card": pc.WILD_CARD, "division_series": pc.DIVISION_SERIES,
            "lcs": pc.LCS, "world_series": pc.WORLD_SERIES,
        }
        for key, rnd in by_round_name.items():
            self.assertEqual(pc.CALENDAR[key]["game_type"], rnd["game_type"], key)


class CalendarAdoptedFromSeasonEndPlanTests(unittest.TestCase):
    """These dates are adopted, not re-verified here (see module docstring)
    -- this just pins them against silent drift from what
    docs/SEASON_END_PLAN.md:9-17 recorded."""

    def test_regular_season_end_date(self):
        self.assertEqual("2026-09-27", pc.REGULAR_SEASON_ENDS)

    def test_round_date_ranges(self):
        self.assertEqual(("2026-09-29", "2026-10-01"),
                         (pc.CALENDAR["wild_card"]["start"], pc.CALENDAR["wild_card"]["end"]))
        self.assertEqual(("2026-10-03", "2026-10-10"),
                         (pc.CALENDAR["division_series"]["start"],
                          pc.CALENDAR["division_series"]["end"]))
        self.assertEqual(("2026-10-11", "2026-10-20"),
                         (pc.CALENDAR["lcs"]["start"], pc.CALENDAR["lcs"]["end"]))
        self.assertEqual(("2026-10-23", "2026-10-31"),
                         (pc.CALENDAR["world_series"]["start"],
                          pc.CALENDAR["world_series"]["end"]))

    def test_rounds_are_in_chronological_order(self):
        starts = [pc.CALENDAR[key]["start"] for key in pc.CALENDAR_ROUNDS_IN_ORDER]
        self.assertEqual(sorted(starts), starts)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
