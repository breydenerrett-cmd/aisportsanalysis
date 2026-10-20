"""src/hounds/user_spec.py: the fixed menu, strict validation and the generated rule text."""
from __future__ import annotations

import unittest

from src.hounds import user_spec
from tests._hounds_user_fixtures import spec_dict


def errors_for(**over) -> dict:
    try:
        user_spec.validate_spec(spec_dict(**over))
    except user_spec.SpecError as exc:
        return exc.errors
    return {}


class MenuBounds(unittest.TestCase):
    def test_a_good_spec_validates_and_is_normalised(self):
        spec = user_spec.validate_spec(spec_dict(sports="MLB", markets="moneyline"))
        self.assertEqual(spec["sports"], ["MLB"])
        self.assertEqual(spec["version"], user_spec.SPEC_VERSION)

    def test_each_numeric_bound_is_enforced(self):
        self.assertIn("min_books", errors_for(min_books=0))
        self.assertIn("min_books", errors_for(min_books=11))
        self.assertEqual(errors_for(min_books=10), {})
        self.assertIn("max_bets_per_day", errors_for(max_bets_per_day=0))
        self.assertIn("max_bets_per_day", errors_for(max_bets_per_day=6))
        self.assertEqual(errors_for(max_bets_per_day=5), {})
        self.assertIn("lock_minutes", errors_for(lock_minutes=90))
        for ok in (60, 120, 180):
            self.assertEqual(errors_for(lock_minutes=ok), {})
        self.assertIn("min_books", errors_for(min_books=True))   # bool is not a count

    def test_menu_choices_are_closed(self):
        # NBA is on the menu since the all-sports catalog (2026-10-19); a sport nobody prices is not.
        self.assertIn("sports", errors_for(sports=["MLB", "CURLING"]))
        self.assertEqual(errors_for(sports=["MLB", "NBA"]), {})
        self.assertIn("markets", errors_for(markets=["moneyline", "prop"]))
        self.assertIn("side_rule", errors_for(side_rule="coin_flip"))

    def test_unknown_fields_are_refused_not_ignored(self):
        self.assertIn("stake", errors_for(stake=100))

    def test_side_rule_must_fit_every_market(self):
        self.assertIn("side_rule", errors_for(side_rule="over", markets=["moneyline"]))
        self.assertIn("side_rule", errors_for(side_rule="favourite", markets=["moneyline", "total"]))
        self.assertEqual(errors_for(side_rule="over", markets=["total"]), {})
        self.assertEqual(errors_for(side_rule="market_moved_toward",
                                    markets=["moneyline", "spread", "total"]), {})

    def test_every_problem_is_reported_at_once(self):
        errs = errors_for(name="x", min_books=0, lock_minutes=1)
        self.assertGreaterEqual(len(errs), 3)


class TheCapIsNotASetting(unittest.TestCase):
    def test_minus_200_or_worse_is_refused_in_either_price_field(self):
        for bad in (-200, -201, -250, -950):
            self.assertIn("price_min", errors_for(price_min=bad, price_max=100))
            self.assertIn("price_max", errors_for(price_min=-190, price_max=bad))

    def test_minus_199_is_the_shortest_allowed(self):
        self.assertEqual(errors_for(price_min=-199, price_max=100), {})

    def test_the_band_must_run_short_to_long(self):
        self.assertIn("price_max", errors_for(price_min=200, price_max=100))
        self.assertEqual(errors_for(price_min=-110, price_max=100), {})   # across even money is fine

    def test_prices_inside_the_dead_zone_are_refused(self):
        self.assertIn("price_min", errors_for(price_min=50))

    def test_beyond_cap_is_the_single_definition(self):
        self.assertTrue(user_spec.beyond_cap(-200))
        self.assertTrue(user_spec.beyond_cap(-450))
        self.assertFalse(user_spec.beyond_cap(-199))
        self.assertFalse(user_spec.beyond_cap(150))

    def test_in_band_compares_in_decimal_across_even_money(self):
        self.assertTrue(user_spec.in_band(-105, -110, 120))
        self.assertTrue(user_spec.in_band(105, -110, 120))
        self.assertFalse(user_spec.in_band(-130, -110, 120))
        self.assertFalse(user_spec.in_band(150, -110, 120))


class NameFilter(unittest.TestCase):
    def test_length_and_characters(self):
        self.assertIn("name", errors_for(name="ab"))
        self.assertIn("name", errors_for(name="a" * 25))
        self.assertIn("name", errors_for(name="Dog_Days"))
        self.assertIn("name", errors_for(name="Dog  Days"))
        self.assertIn("name", errors_for(name="123"))
        self.assertEqual(errors_for(name="Dog-Days 2"), {})

    def test_profanity_including_disguised(self):
        for bad in ("Fuck Off", "F u c k", "Sh1t Show", "Big Ass"):
            self.assertIn("name", errors_for(name=bad), bad)
        self.assertEqual(errors_for(name="Class Act"), {})       # no false positive on 'ass'

    def test_brands_and_reserved_words(self):
        for bad in ("DraftKings Dog", "Official Pick", "LineHound Prime", "FanDuel Fan"):
            self.assertIn("name", errors_for(name=bad), bad)

    def test_real_team_and_player_names_are_refused(self):
        self.assertIn("name", errors_for(name="Yankees"))
        self.assertIn("name", errors_for(name="Red Sox Fan"))
        self.assertIn("name", errors_for(name="Chiefs"))
        extra = {"Aaron Judge": "player"}
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec(spec_dict(name="Aaron Judge"), extra_real_names=extra)
        self.assertIn("name", ctx.exception.errors)

    def test_uniqueness_ignores_case_and_spacing(self):
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec(spec_dict(name="dog days"), taken_names=["Dog Days"])
        self.assertIn("name", ctx.exception.errors)
        with self.assertRaises(user_spec.SpecError):
            user_spec.validate_spec(spec_dict(name="Dog-Days"), taken_names=["Dog Days"])

    def test_tagline_limits_and_filter(self):
        self.assertIn("tagline", errors_for(tagline="x" * 81))
        self.assertEqual(errors_for(tagline="x" * 80), {})
        self.assertIn("tagline", errors_for(tagline="what the fuck"))
        self.assertIn("tagline", errors_for(tagline="<script>"))


class RuleText(unittest.TestCase):
    def test_rule_text_is_generated_from_the_spec_and_names_every_choice(self):
        spec = user_spec.validate_spec(spec_dict(
            sports=["MLB", "NFL"], markets=["moneyline", "total"], side_rule="market_moved_toward",
            price_min=-150, price_max=180, min_books=4, max_bets_per_day=3, lock_minutes=60))
        text = user_spec.rule_text(spec)
        for needle in ("MLB and NFL", "moneylines and game totals", "60 minutes", "moved toward",
                       "-150", "+180", "at least 4 books", "At most 3 bets", "-200 or worse",
                       "average price", user_spec.NOT_ADVICE):
            self.assertIn(needle, text)

    def test_rule_text_changes_when_a_rule_field_changes_and_not_otherwise(self):
        a = user_spec.validate_spec(spec_dict())
        b = user_spec.validate_spec(spec_dict(name="Other Name", tagline="hi"))
        c = user_spec.validate_spec(spec_dict(side_rule="favourite"))
        self.assertEqual(user_spec.rule_text(a), user_spec.rule_text(b))
        self.assertNotEqual(user_spec.rule_text(a), user_spec.rule_text(c))
        self.assertEqual(user_spec.spec_hash(a), user_spec.spec_hash(b))
        self.assertNotEqual(user_spec.spec_hash(a), user_spec.spec_hash(c))

    def test_sport_words_follow_the_sport(self):
        mlb = user_spec.rule_text(user_spec.validate_spec(
            spec_dict(markets=["spread"], side_rule="home")))
        nfl = user_spec.rule_text(user_spec.validate_spec(
            spec_dict(sports=["NFL"], markets=["spread"], side_rule="home")))
        self.assertIn("run lines", mlb)
        self.assertIn("first pitch", mlb)
        self.assertIn("point spreads", nfl)
        self.assertIn("kickoff", nfl)

    def test_menu_lists_every_choice_and_the_cap(self):
        menu = user_spec.menu()
        self.assertTrue(menu["paper_only"])
        self.assertEqual([s["value"] for s in menu["side_rules"]], list(user_spec.SIDE_RULES))
        self.assertEqual(menu["lock_minutes"]["choices"], [60, 120, 180])
        self.assertIn("-200", menu["price_cap_note"])
        self.assertEqual(menu["max_running_per_account"], 5)


if __name__ == "__main__":
    unittest.main()
