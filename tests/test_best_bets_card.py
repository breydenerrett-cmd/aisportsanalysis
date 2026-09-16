"""Fixture-only tests for `src.analysis.best_bets_card` (registration
`docs/PREREG_CARD_V2.md`, build plan T2).

SCOPE OF THIS FILE
-------------------
The build plan's T2 row sketches roughly fifteen separate test files, one
per invariant family. This file covers the same invariants in one place
instead: the `RuleParams` shape and the four family arms differing in
exactly the registered fields, the score/edge/markdown arithmetic against
the registration's own worked numbers, gate behaviour for both price
classes, the G11-then-G14-then-G12 ordering the registration fixes in
section 5 (and the build plan calls out as "a design script got this
wrong"), the fill/floor/ceiling mechanics, and the copy strings this module
owns. It does not reproduce the registration's section 14 illustration
fixture (that needs the real 2026-09-15 board, out of a fixture-only unit
test's reach) or every rendering assertion `tests/test_card_v2_copy.py`
would eventually own; both are natural follow-up work once the report layer
(T5) exists to feed this module real candidates.

Every fixture here is inline. No disk read, no network call, no naked
`datetime.now()`.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import best_bets_card as card
from src.core import odds


NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _fresh(seconds_ago=60):
    return NOW - timedelta(seconds=seconds_ago)


def _candidate(**over):
    base = dict(
        game_id="G1",
        price=-140,
        market_probability=0.55,
        our_probability=0.65,
        books=8,
        observed_utc=_fresh(),
        has_started=False,
        calibrated=True,
        bet_sentence="the Padres",
        first_pitch="2026-09-16T23:00:00Z",
    )
    base.update(over)
    return base


class RuleParamsShape(unittest.TestCase):
    """Registration 3/4/17.1: the constants and their source."""

    def test_v2_constants_match_registration(self):
        self.assertEqual(card.V2.worst_price, -160.0)
        self.assertEqual(card.V2.best_price, 250.0)
        self.assertEqual(card.V2.base_price, -160.0)
        self.assertEqual(card.V2.markdown, 0.038)
        self.assertEqual(card.V2.base_edge, 0.010)
        self.assertEqual(card.V2.main_market_floor, 0.50)
        self.assertEqual(card.V2.main_our_floor, 0.50)
        self.assertEqual(card.V2.plus_market_floor, 0.20)
        self.assertEqual(card.V2.plus_our_floor, 0.30)
        self.assertEqual(card.V2.plus_money_subcap, 3)
        self.assertEqual(card.V2.ceiling, 10)
        self.assertEqual(card.V2.floor, 3)
        self.assertFalse(card.V2.require_lineup)
        # Constants imported from their named modules, not retyped.
        self.assertEqual(card.V2.game_min_books, 6)
        self.assertEqual(card.V2.prop_min_books, 2)
        self.assertEqual(card.V2.prop_min_season_games, 15)
        self.assertEqual(card.V2.fresh_seconds, 3600)

    def test_no_longest_price_first_field_on_v2(self):
        # Question 8 replaced the draft's price-first key with the score;
        # only SHADOW_E carries the old key, and only via `rank`.
        self.assertEqual(card.V2.rank, "score")

    def test_no_shadow_d_and_no_zero_markdown_parameter_set(self):
        self.assertFalse(hasattr(card, "SHADOW_D"))
        all_sets = [card.V2, card.SHADOW_A, card.SHADOW_C, card.SHADOW_E,
                    card.A1, card.A2, card.A3, card.A4]
        for params in all_sets:
            if params.rule_id == card.SHADOW_E.rule_id:
                continue  # E is the superseded draft rule itself.
            self.assertNotEqual(params.markdown, 0.0, params.rule_id)

    def test_shadow_a_has_no_likelihood_floors_value_test_disagreement_cap_or_subcap(self):
        self.assertIsNone(card.SHADOW_A.main_our_floor)
        self.assertIsNone(card.SHADOW_A.plus_our_floor)
        self.assertFalse(card.SHADOW_A.value_test)
        self.assertIsNone(card.SHADOW_A.disagreement_cap)
        self.assertIsNone(card.SHADOW_A.plus_money_subcap)

    def test_shadow_c_differs_from_v2_only_in_worst_price(self):
        d = dataclasses.asdict(card.V2)
        e = dataclasses.asdict(card.SHADOW_C)
        diffs = {k for k in d if d[k] != e[k] and k != "rule_id"}
        self.assertEqual(diffs, {"worst_price"})


class FamilyArms(unittest.TestCase):
    """Registration 17.1: four arms, three fields differ, no more."""

    def test_a1_is_v2(self):
        self.assertIs(card.A1, card.V2)

    def test_each_arm_differs_from_v2_in_named_fields_only(self):
        d = dataclasses.asdict(card.V2)
        expected = {
            "A2": {"plus_money_subcap"},
            "A3": {"markdown", "base_edge"},
            "A4": {"markdown", "base_edge", "plus_money_subcap"},
        }
        for name, allowed in expected.items():
            arm = dataclasses.asdict(card.ARMS[name])
            diffs = {k for k in d if d[k] != arm[k] and k != "rule_id"}
            self.assertEqual(diffs, allowed, name)

    def test_loose_arms_reproduce_17_1_bar_table(self):
        # registration 17.1: 66.34/62.68 at -160, 45.34/41.27 at +150,
        # 34.53/29.99 at +250, to two decimals -- the first of each pair is
        # V2's (strict) bar, the second the loose arms' (A3/A4) bar.
        cases = [(-160, 66.34, 62.68), (150, 45.34, 41.27), (250, 34.53, 29.99)]
        for price, strict_pct, loose_pct in cases:
            strict_need = card.value_need(price, card.V2) + card.V2.markdown
            loose_need = card.value_need(price, card.A3) + card.A3.markdown
            self.assertAlmostEqual(strict_need * 100, strict_pct, places=2, msg=price)
            self.assertAlmostEqual(loose_need * 100, loose_pct, places=2, msg=price)


class ArithmeticWorkedExamples(unittest.TestCase):
    """Hand-checked against the registration's own numbers."""

    def test_price_class_bands(self):
        self.assertEqual(card.price_class(-160), "MAIN")
        self.assertEqual(card.price_class(-100), "MAIN")
        self.assertIsNone(card.price_class(-99))
        self.assertEqual(card.price_class(100), "PLUS_MONEY")
        self.assertEqual(card.price_class(250), "PLUS_MONEY")
        self.assertIsNone(card.price_class(251))
        self.assertIsNone(card.price_class(99))

    def test_marked_down_worked_example(self):
        # registration section 4: marked_down = max(0, p - 0.038).
        # 0.65 - 0.038 = 0.612, hand-checked.
        self.assertAlmostEqual(card.marked_down(0.65, card.V2), 0.612)
        # Floors at 0.0, never negative.
        self.assertEqual(card.marked_down(0.01, card.V2), 0.0)

    def test_required_edge_worked_examples(self):
        # registration 4.2 table: 1.00 pt at -160 (base price, ratio 1.0),
        # 2.15 pt at +250. decimal(-160) = 1 + 100/160 = 1.625.
        # decimal(250) = 1 + 250/100 = 3.5. ratio = 3.5/1.625 = 2.153846...
        # required_edge = 0.010 * ratio.
        base_decimal = odds.american_to_decimal(-160)
        self.assertAlmostEqual(base_decimal, 1.625)
        self.assertAlmostEqual(card.required_edge(-160, card.V2), 0.010, places=4)
        long_decimal = odds.american_to_decimal(250)
        self.assertAlmostEqual(long_decimal, 3.5)
        expected_250 = 0.010 * (3.5 / 1.625)
        self.assertAlmostEqual(card.required_edge(250, card.V2), expected_250)
        self.assertAlmostEqual(card.required_edge(250, card.V2) * 100, 2.15, places=2)

    def test_score_is_kelly_fraction_on_marked_down_number(self):
        # At the +250 ceiling with our raw number exactly at the registered
        # bar (34.53%, from 4.6's table), marked_down = 0.3453 - 0.038 =
        # 0.3073; breakeven(250) = 100/350 = 0.285714...
        price = 250
        raw = 0.3453
        d = odds.american_to_decimal(price)
        self.assertAlmostEqual(d, 3.5)
        p = card.marked_down(raw, card.V2)
        self.assertAlmostEqual(p, 0.3073, places=4)
        expected_score = p - (1.0 - p) / (d - 1.0)
        got = card.score(raw, price, card.V2)
        self.assertAlmostEqual(got, expected_score)
        # Hand arithmetic: (1-0.3073)/(3.5-1) = 0.6927/2.5 = 0.27708
        self.assertAlmostEqual(expected_score, 0.3073 - 0.27708, places=4)

    def test_score_positive_exactly_above_breakeven(self):
        # score > 0 iff marked_down(p) > breakeven(price) (registration
        # section 4, the line right after the score block).
        price = -160
        be = card.breakeven(price)
        just_above = be + 1e-6 + card.V2.markdown
        just_below = be - 1e-6 + card.V2.markdown
        self.assertGreater(card.score(just_above, price, card.V2), 0.0)
        self.assertLess(card.score(just_below, price, card.V2), 0.0)

    def test_score_has_no_fractional_multiplier_or_cap(self):
        # A positive rescaling of the score changes nothing about ordering;
        # there is no registered constant this module could apply that
        # would break that invariant, and none is exposed.
        self.assertFalse(hasattr(card, "KELLY_MULTIPLIER"))
        self.assertFalse(hasattr(card, "SCORE_CAP"))
        s = card.score(0.60, -140, card.V2)
        self.assertEqual(s * 3, s * 3)  # rescaling preserves order trivially


class LikelihoodGates(unittest.TestCase):
    """Registration G5/G6, both classes, raw numbers."""

    def test_main_market_floor_boundary(self):
        c = _candidate(price=-140, market_probability=0.50, our_probability=0.70)
        self.assertIn(card.G5_MARKET, card.failed_gates(c, now=NOW, params=card.V2))
        c["market_probability"] = 0.5001
        self.assertNotIn(card.G5_MARKET, card.failed_gates(c, now=NOW, params=card.V2))

    def test_main_our_floor_boundary(self):
        c = _candidate(price=-140, market_probability=0.60, our_probability=0.50)
        self.assertIn(card.G6_FLOOR, card.failed_gates(c, now=NOW, params=card.V2))

    def test_plus_money_market_band_boundaries(self):
        c = _candidate(price=150, market_probability=0.50, our_probability=0.45)
        self.assertIn(card.G5_MARKET, card.failed_gates(c, now=NOW, params=card.V2))
        c["market_probability"] = 0.4999
        self.assertNotIn(card.G5_MARKET, card.failed_gates(c, now=NOW, params=card.V2))
        c["market_probability"] = 0.1999
        self.assertIn(card.G5_MARKET, card.failed_gates(c, now=NOW, params=card.V2))
        c["market_probability"] = 0.20
        self.assertNotIn(card.G5_MARKET, card.failed_gates(c, now=NOW, params=card.V2))

    def test_plus_money_our_floor_boundary_raw_number(self):
        c = _candidate(price=150, market_probability=0.30, our_probability=0.2999)
        self.assertIn(card.G6_FLOOR, card.failed_gates(c, now=NOW, params=card.V2))
        c["our_probability"] = 0.30
        self.assertNotIn(card.G6_FLOOR, card.failed_gates(c, now=NOW, params=card.V2))

    def test_underdog_market_with_marked_down_number_above_bar_is_a_pick(self):
        # question 5, answered yes: a market underdog at +120 whose
        # marked-down number clears value_need is a pick.
        price = 120
        need = card.value_need(price, card.V2)
        market = 0.45  # market calls the side an underdog (< 0.50)
        our = need + card.V2.markdown + 0.005  # clears the bar, stays within G8's gap
        self.assertLessEqual(abs(our - market), card.V2.disagreement_cap)
        c = _candidate(price=price, market_probability=market, our_probability=our)
        self.assertEqual(card.failed_gates(c, now=NOW, params=card.V2), [])


class ValueTestAndLineShopping(unittest.TestCase):
    def test_bar_is_breakeven_plus_required_edge_on_marked_down_number(self):
        price = -140
        need = card.value_need(price, card.V2)
        c = _candidate(price=price, market_probability=0.30,
                        our_probability=need + card.V2.markdown - 1e-6)
        self.assertIn(card.G7_VALUE, card.failed_gates(c, now=NOW, params=card.V2))
        c["our_probability"] = need + card.V2.markdown + 1e-6
        self.assertNotIn(card.G7_VALUE, card.failed_gates(c, now=NOW, params=card.V2))

    def test_raw_above_breakeven_but_below_bar_is_refused(self):
        price = -140
        be = card.breakeven(price)
        # Above raw breakeven, below the (higher) bar including markdown.
        our = be + 0.005
        need = card.value_need(price, card.V2)
        self.assertGreater(our, be)
        self.assertLess(card.marked_down(our, card.V2), need)
        c = _candidate(price=price, market_probability=0.30, our_probability=our)
        self.assertIn(card.G7_VALUE, card.failed_gates(c, now=NOW, params=card.V2))

    def test_markdown_applied_exactly_once(self):
        price = -140
        our = 0.70
        # score() and passes_value_test() must agree on where breakeven
        # sits relative to the SAME marked-down number.
        p = card.marked_down(our, card.V2)
        need = card.value_need(price, card.V2)
        passes = card.passes_value_test(our, price, card.V2)
        self.assertEqual(passes, p >= need)

    def test_line_shopping_gate(self):
        price = -140
        be = card.breakeven(price)
        c = _candidate(price=price, market_probability=be + 0.01, our_probability=0.70)
        self.assertIn(card.G13_LINE_SHOPPING, card.failed_gates(c, now=NOW, params=card.V2))
        c["market_probability"] = be
        self.assertNotIn(card.G13_LINE_SHOPPING, card.failed_gates(c, now=NOW, params=card.V2))


class DisagreementCap(unittest.TestCase):
    def test_boundary_both_signs_raw_numbers(self):
        c = _candidate(price=-140, market_probability=0.55, our_probability=0.65)
        self.assertNotIn(card.G8_DISAGREEMENT, card.failed_gates(c, now=NOW, params=card.V2))
        c["our_probability"] = 0.6501
        self.assertIn(card.G8_DISAGREEMENT, card.failed_gates(c, now=NOW, params=card.V2))
        c2 = _candidate(price=-140, market_probability=0.65, our_probability=0.55)
        self.assertNotIn(card.G8_DISAGREEMENT, card.failed_gates(c2, now=NOW, params=card.V2))
        c2["our_probability"] = 0.5499
        self.assertIn(card.G8_DISAGREEMENT, card.failed_gates(c2, now=NOW, params=card.V2))


class Freshness(unittest.TestCase):
    def test_boundary_and_missing(self):
        c = _candidate(observed_utc=NOW - timedelta(seconds=3600))
        self.assertNotIn(card.G3_STALE, card.failed_gates(c, now=NOW, params=card.V2))
        c["observed_utc"] = NOW - timedelta(seconds=3601)
        self.assertIn(card.G3_STALE, card.failed_gates(c, now=NOW, params=card.V2))
        c["observed_utc"] = None
        self.assertIn(card.G3_STALE, card.failed_gates(c, now=NOW, params=card.V2))


class Props(unittest.TestCase):
    def test_no_lineup_required_but_season_games_gates(self):
        c = _candidate(
            kind="prop", price=-120, market_probability=0.40, our_probability=0.60,
            books=3, season_games=14, calibrated=True,
        )
        self.assertIn(card.G10_SAMPLE, card.failed_gates(c, now=NOW, params=card.V2))
        c["season_games"] = 15
        self.assertNotIn(card.G10_SAMPLE, card.failed_gates(c, now=NOW, params=card.V2))
        # No lineup-posted field required to pass; there is no such gate.
        self.assertFalse(hasattr(card, "G10_LINEUP"))

    def test_prop_book_floor_is_two(self):
        c = _candidate(kind="prop", price=-120, market_probability=0.40,
                        our_probability=0.60, books=1, season_games=20)
        self.assertIn(card.G2_BOOKS, card.failed_gates(c, now=NOW, params=card.V2))
        c["books"] = 2
        self.assertNotIn(card.G2_BOOKS, card.failed_gates(c, now=NOW, params=card.V2))


class SelectOrderingAndCaps(unittest.TestCase):
    """G11 before G14 before G12 (registration section 5, build plan's
    order-of-operations test)."""

    def _plus_money(self, game_id, price, market_p, raw, books=8):
        return _candidate(
            game_id=game_id, price=price, market_probability=market_p,
            our_probability=raw, books=books,
        )

    def test_g14_runs_after_g11_not_before(self):
        # Two plus-money candidates on the SAME game, a high-score one and a
        # low-score one, plus one candidate on another game, sub-cap 2. If
        # G14 ran before G11 it would see three plus-money candidates
        # (counting SAME's duplicate as two), keep the two highest by its
        # own order and drop OTHER outright. Run in the registered order,
        # G11 first collapses SAME to its higher-scored entry, leaving both
        # of the cap's two slots free for SAME and OTHER together -- the
        # exact under-count the build plan's order-of-operations test
        # exists to catch.
        params = dataclasses.replace(card.V2, plus_money_subcap=2)
        high = self._plus_money("SAME", 200, 0.30, 0.395)
        low = self._plus_money("SAME", 200, 0.30, 0.392)
        other = self._plus_money("OTHER", 150, 0.37, 0.46)
        result = card.select([high, low, other], now=NOW, params=params)
        game_ids = {c["game_id"] for c in result["picks"] + result["prop_picks"]}
        self.assertIn("SAME", game_ids)
        self.assertIn("OTHER", game_ids)
        self.assertEqual(result["n_picks"], 2)
        self.assertEqual(result["plus_money_dropped_by_subcap"], [])

    def test_subcap_drops_lowest_scored_plus_money_picks(self):
        params = dataclasses.replace(card.V2, plus_money_subcap=1)
        a = self._plus_money("A", 200, 0.30, 0.396)  # higher score
        b = self._plus_money("B", 200, 0.30, 0.391)  # lower score
        result = card.select([a, b], now=NOW, params=params)
        self.assertEqual(result["n_picks"], 1)
        self.assertEqual(len(result["plus_money_dropped_by_subcap"]), 1)
        self.assertEqual(result["plus_money_dropped_by_subcap"][0]["game_id"], "B")
        # MAIN never dropped by G14.
        main = _candidate(game_id="M", price=-140, market_probability=0.40, our_probability=0.70)
        result2 = card.select([a, b, main], now=NOW, params=params)
        dropped_ids = {c["game_id"] for c in result2["plus_money_dropped_by_subcap"]}
        self.assertNotIn("M", dropped_ids)

    def test_subcap_none_means_only_ceiling_binds(self):
        params = dataclasses.replace(card.V2, plus_money_subcap=None)
        cands = [self._plus_money(f"G{i}", 200, 0.30, 0.395 - i * 0.001) for i in range(5)]
        result = card.select(cands, now=NOW, params=params)
        self.assertEqual(result["n_picks"], 5)
        self.assertEqual(result["plus_money_dropped_by_subcap"], [])

    def test_ceiling_counts_picks_and_fills_together(self):
        params = dataclasses.replace(card.V2, plus_money_subcap=None, ceiling=10)
        picks = [
            _candidate(game_id=f"P{i}", price=-140, market_probability=0.55,
                       our_probability=0.64)
            for i in range(10)
        ]
        result = card.select(picks, now=NOW, params=params)
        self.assertEqual(result["n_picks"], 10)
        self.assertEqual(result["n_fills"], 0)  # no room left for a fill

    def test_eleventh_pick_refused_not_a_withdrawn_fill(self):
        params = dataclasses.replace(card.V2, plus_money_subcap=None, ceiling=10)
        picks = [
            _candidate(game_id=f"P{i}", price=-140, market_probability=0.55,
                       our_probability=0.64)
            for i in range(11)
        ]
        result = card.select(picks, now=NOW, params=params)
        self.assertEqual(result["n_picks"], 10)
        self.assertEqual(len(result["ceiling_refused"]), 1)


class FloorAndFills(unittest.TestCase):
    def test_zero_picks_gives_three_fills(self):
        # Each candidate fails only G7 (a close call), so all are fill
        # eligible; none share a game.
        cands = []
        for i in range(4):
            price = -140
            be = card.breakeven(price)
            cands.append(_candidate(
                game_id=f"G{i}", price=price, market_probability=0.55,
                our_probability=be + 0.001,  # passes raw floors, fails G7 only
            ))
        result = card.select(cands, now=NOW, params=card.V2)
        self.assertEqual(result["n_picks"], 0)
        self.assertEqual(result["n_fills"], 3)

    def test_three_picks_gives_zero_fills(self):
        picks = [
            _candidate(game_id=f"P{i}", price=-140, market_probability=0.55,
                       our_probability=0.64)
            for i in range(3)
        ]
        close_call = _candidate(
            game_id="C1", price=-140, market_probability=0.55,
            our_probability=card.breakeven(-140) + 0.001,
        )
        result = card.select(picks + [close_call], now=NOW, params=card.V2)
        self.assertEqual(result["n_picks"], 3)
        self.assertEqual(result["n_fills"], 0)

    def test_never_more_than_floor_fills_on_one_run(self):
        cands = []
        for i in range(6):
            price = -140
            be = card.breakeven(price)
            cands.append(_candidate(
                game_id=f"G{i}", price=price, market_probability=0.55,
                our_probability=be + 0.001,
            ))
        result = card.select(cands, now=NOW, params=card.V2)
        self.assertLessEqual(result["n_fills"], card.V2.floor)

    def test_fill_never_fails_a_hard_gate(self):
        # A candidate failing G1 can never become a fill.
        c = _candidate(price=-140, market_probability=0.55,
                        our_probability=card.breakeven(-140) + 0.001,
                        has_started=True)
        fails = card.failed_gates(c, now=NOW, params=card.V2)
        self.assertFalse(card.is_fill_eligible(fails))


class Copy(unittest.TestCase):
    def test_plus_money_note_never_implies_our_number_more_likely(self):
        note_pick = card.plus_money_note("pick")
        note_fill = card.plus_money_note("bet")
        for note in (note_pick, note_fill):
            self.assertNotIn("our number makes", note.lower())
            self.assertNotIn("more likely than not", note.lower())
        self.assertTrue(note_pick.startswith("This is a plus-money pick"))
        self.assertTrue(note_fill.startswith("This is a plus-money bet"))

    def test_no_lineup_note_text(self):
        self.assertIn("No lineup is posted yet", card.no_lineup_note())

    def test_class_stopped_sentence_names_the_class(self):
        self.assertIn("plus-money bets", card.class_stopped_sentence("PLUS_MONEY"))
        self.assertIn("main-band bets", card.class_stopped_sentence("MAIN"))

    def test_harm_stop_sentence_forms(self):
        closing = card.harm_stop_sentence(["closing_price"])
        hit_rate = card.harm_stop_sentence(["hit_rate"])
        plus_hit = card.harm_stop_sentence(["hit_rate"], price_class_name="PLUS_MONEY")
        both = card.harm_stop_sentence(["closing_price", "hit_rate"])
        self.assertIn("worse prices than the market settled at", closing)
        self.assertNotIn("worse prices", hit_rate)
        self.assertIn("won less often", hit_rate)
        self.assertIn("plus-money picks", plus_hit)
        self.assertIn("worse prices", both)
        self.assertIn("won less often", both)

    def test_short_card_sentence_names_n(self):
        self.assertIn("2 bets are listed", card.short_card_sentence(2))
        self.assertIn("Today the board had 2", card.short_card_sentence(2))


if __name__ == "__main__":
    unittest.main()
