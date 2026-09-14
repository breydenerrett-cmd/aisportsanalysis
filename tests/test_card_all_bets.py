"""THE MERGED LIST -- every kind of bet in one ranking. The owner, 2026-09-14:
"merge the today bets for ALL BETS not just MLs include all best bets like
player props." `payload["all_bets"]` (`daily_card.merge_all_bets`) is the one
list `picks`, `total_picks` and `prop_picks` are ranked into together; the
three arrays themselves are untouched -- still what the ledger freezes and
grades, one kind at a time.

Covers, in order:
  * `daily_card.prop_rank_probability` / `PROP_RANK_SOURCE` -- the declared
    seam for ranking a prop pick against the other two kinds
  * `daily_card.merge_all_bets` -- the ranking itself, pure
  * `src.report.card.card_for_date` -- the live build carries `all_bets`
  * `src.report.card.frozen_card` -- a frozen row still serves `all_bets`,
    built fresh from its own three served arrays, even for an old row that
    predates total or prop picks entirely

Every test is synthetic; none of them touch evidence/cards_v1.jsonl or
data/processed/*.jsonl.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from src.analysis import daily_card
from src.appstate import card_ledger


FUTURE = "2026-09-14T22:40:00Z"


def _game_pick(market_probability, bet="Take Padres to win at -150",
              first_pitch_utc=FUTURE):
    return {"market_probability": market_probability, "label": "STRONG",
            "bet": bet, "first_pitch_utc": first_pitch_utc}


def _total_pick(market_probability, bet="Take Over 8.5 runs at -110",
                first_pitch_utc=FUTURE):
    return {"market_probability": market_probability, "label": "LEAN",
            "bet": bet, "first_pitch_utc": first_pitch_utc}


def _prop_pick(probability, market_probability=None, breakeven=None,
              bet="Take Devers over 0.5 hits at -140",
              first_pitch_utc=FUTURE):
    return {"probability": probability, "market_probability": market_probability,
            "breakeven": breakeven, "label": "STRONG", "bet": bet,
            "first_pitch_utc": first_pitch_utc}


class PropRankProbability(unittest.TestCase):
    def setUp(self):
        self._real = daily_card.PROP_RANK_SOURCE
        self.addCleanup(setattr, daily_card, "PROP_RANK_SOURCE", self._real)

    def test_declared_source_is_both(self):
        # 2026-09-14: set from docs/PROP_CALIBRATION_2026-09-14.md -- ours
        # runs high on Unders and on big disagreements. Fails if the
        # constant is reverted to "model".
        self.assertEqual("both", daily_card.PROP_RANK_SOURCE)

    def test_both_ranks_last_when_the_market_calls_it_less_likely_than_not(self):
        # 2026-09-14: a plus-money prop whose market number clears its
        # break-even but not 50% -- probability before price. Fails without
        # the LIKELY_FLOOR check on the market's number.
        daily_card.PROP_RANK_SOURCE = "both"
        contract = _prop_pick(0.62, market_probability=0.47, breakeven=0.44)
        self.assertEqual(0.0, daily_card.prop_rank_probability(contract))

    def test_model_reads_our_own_probability(self):
        daily_card.PROP_RANK_SOURCE = "model"
        contract = _prop_pick(0.70, market_probability=0.55)
        self.assertEqual(0.70, daily_card.prop_rank_probability(contract))

    def test_market_reads_the_market_probability(self):
        daily_card.PROP_RANK_SOURCE = "market"
        contract = _prop_pick(0.70, market_probability=0.55)
        self.assertEqual(0.55, daily_card.prop_rank_probability(contract))

    def test_both_ranks_by_market_when_both_clear_the_breakeven(self):
        daily_card.PROP_RANK_SOURCE = "both"
        contract = _prop_pick(0.70, market_probability=0.60, breakeven=0.55)
        self.assertEqual(0.60, daily_card.prop_rank_probability(contract))

    def test_both_gate_is_market_likely_and_ours_clears_the_price(self):
        """2026-09-14, orchestrator: the market's number must say more likely
        than not and OUR number must clear the price. Requiring the market's
        number to beat the best price's break-even as well is a price
        discrepancy between books -- line shopping -- and is not the rule."""
        daily_card.PROP_RANK_SOURCE = "both"
        # Muncy, live 09-14: market 54% likely, ours 62% clears 57% -> ranks at 54%.
        muncy = _prop_pick(0.6245, market_probability=0.5382, breakeven=0.569)
        self.assertEqual(0.5382, daily_card.prop_rank_probability(muncy))
        # The market calls it a coin flip or worse: refused.
        coin_flip = _prop_pick(0.70, market_probability=0.50, breakeven=0.55)
        self.assertEqual(0.0, daily_card.prop_rank_probability(coin_flip))
        # The market likes it, ours does not clear the price: refused.
        market_only = _prop_pick(0.50, market_probability=0.70, breakeven=0.55)
        self.assertEqual(0.0, daily_card.prop_rank_probability(market_only))

    def test_select_props_applies_the_gate_and_ranks_by_the_market(self):
        daily_card.PROP_RANK_SOURCE = "both"
        from tests.test_card_props import _contract, NOW
        high_ours_low_market = _contract(player="Ours High", probability=0.84,
                                         market_probability=0.49, breakeven=0.69)
        market_first = _contract(player="Market First", probability=0.62,
                                 market_probability=0.58, breakeven=0.57)
        market_second = _contract(player="Market Second", probability=0.75,
                                  market_probability=0.54, breakeven=0.60)
        picks = daily_card.select_props(
            [high_ours_low_market, market_second, market_first], now=NOW)
        self.assertEqual(["Market First", "Market Second"], [p["player"] for p in picks])

    def test_missing_probability_never_raises(self):
        self.assertEqual(0.0, daily_card.prop_rank_probability({}))
        daily_card.PROP_RANK_SOURCE = "market"
        self.assertEqual(0.0, daily_card.prop_rank_probability({}))
        daily_card.PROP_RANK_SOURCE = "both"
        self.assertEqual(0.0, daily_card.prop_rank_probability({}))


class MergeAllBets(unittest.TestCase):
    def test_ranked_by_probability_across_all_three_kinds(self):
        picks = [_game_pick(0.60)]
        total_picks = [_total_pick(0.70)]
        prop_picks = [_prop_pick(0.55)]
        merged = daily_card.merge_all_bets(picks, total_picks, prop_picks)
        self.assertEqual(["total", "game", "prop"], [m["kind"] for m in merged])
        self.assertEqual([1, 2, 3], [m["position"] for m in merged])

    def test_index_points_back_into_its_own_array(self):
        picks = [_game_pick(0.60, bet="A"), _game_pick(0.90, bet="B")]
        total_picks = [_total_pick(0.55, bet="C")]
        prop_picks = []
        merged = daily_card.merge_all_bets(picks, total_picks, prop_picks)
        for item in merged:
            if item["kind"] == "game":
                self.assertEqual(picks[item["index"]]["bet"], item["bet"])
            elif item["kind"] == "total":
                self.assertEqual(total_picks[item["index"]]["bet"], item["bet"])
        # Rank order: B (0.90) first, C (0.55) second. B is picks[1].
        self.assertEqual("B", merged[0]["bet"])
        self.assertEqual(1, merged[0]["index"])
        self.assertEqual("game", merged[0]["kind"])

    def test_a_prop_pick_is_ranked_by_prop_rank_probability_not_probability_alone(self):
        real = daily_card.PROP_RANK_SOURCE
        daily_card.PROP_RANK_SOURCE = "market"
        try:
            # Our own probability is higher, but the merge must read the
            # MARKET number when that source is selected.
            prop = _prop_pick(0.90, market_probability=0.40)
            game = _game_pick(0.50)
            merged = daily_card.merge_all_bets([game], [], [prop])
            self.assertEqual("game", merged[0]["kind"])
            self.assertEqual("prop", merged[1]["kind"])
        finally:
            daily_card.PROP_RANK_SOURCE = real

    def test_a_prop_the_rank_source_refuses_carries_no_probability_and_sorts_last(self):
        # 2026-09-14, live 16:30Z: a refused prop came back in all_bets with
        # probability 0.0 ("0%" beside a bet our number put at 62%). Fails on
        # the pre-fix merge, which served 0.0. The contract is one the
        # both-gate refuses: the market calls it a coin flip.
        real = daily_card.PROP_RANK_SOURCE
        daily_card.PROP_RANK_SOURCE = "both"
        try:
            prop = _prop_pick(0.6245, market_probability=0.50, breakeven=0.569)
            merged = daily_card.merge_all_bets([_game_pick(0.51)], [], [prop])
            self.assertEqual(["game", "prop"], [m["kind"] for m in merged])
            self.assertIsNone(merged[1]["probability"])
        finally:
            daily_card.PROP_RANK_SOURCE = real

    def test_empty_arrays_produce_an_empty_merge(self):
        self.assertEqual([], daily_card.merge_all_bets([], [], []))

    def test_every_item_carries_the_declared_shape(self):
        merged = daily_card.merge_all_bets(
            [_game_pick(0.6)], [_total_pick(0.5)], [_prop_pick(0.55)])
        for item in merged:
            for key in ("kind", "position", "index", "probability", "label",
                       "bet", "first_pitch_utc"):
                self.assertIn(key, item)


class CardForDateCarriesAllBets(unittest.TestCase):
    def _entry(self, game_pk, away, home, first_pitch):
        return {"dossier": {
            "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                     "start_time_utc": first_pitch, "game_number": 1},
            "sections": {
                "teams": {
                    "away_runs_scored_pg": 4.6, "away_runs_allowed_pg": 4.2,
                    "away_games_played": 140,
                    "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.1,
                    "home_games_played": 140,
                },
                "starters": {},
            },
        }}

    def test_all_bets_is_present_and_ranked_on_a_live_build(self):
        from src.report import card as card_mod

        now = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        entries = [self._entry(744001, "SD", "COL", FUTURE)]
        payload = card_mod.card_for_date(
            entries, [], date="2026-09-14", now=now, multibook_rows=[],
            prefer_frozen=False,
            prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        self.assertIn("all_bets", payload)
        probs = [m["probability"] for m in payload["all_bets"] if m["probability"] is not None]
        self.assertEqual(sorted(probs, reverse=True), probs)


class FrozenCardAllBets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")
        self._real = card_ledger.CARD_STORE
        card_ledger.CARD_STORE = self.path
        self.addCleanup(setattr, card_ledger, "CARD_STORE", self._real)

    def _game_row_pick(self, market_probability=0.60):
        return {
            "rank": 1, "label": "STRONG", "bet": "Take Yankees to win at -150",
            "why": [], "market": "moneyline", "line": None, "side": "home",
            "team": "NYY", "team_name": "Yankees", "opponent_name": "COL",
            "price": -150, "book": "dk", "books": 8,
            "confidence": market_probability, "market_probability": market_probability,
            "model_probability": 0.64, "game_id": "g1", "game_pk": 1001,
            "event_id": "e0", "away_team": "COL", "home_team": "NYY",
            "first_pitch_utc": FUTURE, "observed_utc": "x", "model": {},
        }

    def _total_row_pick(self, market_probability=0.55):
        return {
            "rank": 1, "label": "LEAN", "bet": "Take Over 8.5 runs at -110",
            "why": [], "line": 8.5, "side": "over", "price": -110, "book": "dk",
            "books": 8, "market_probability": market_probability,
            "model_probability": 0.7, "game_id": "g1", "game_pk": 1001,
            "event_id": "e0", "away_team": "COL", "home_team": "NYY",
            "first_pitch_utc": FUTURE, "observed_utc": "x",
        }

    def _prop_row_pick(self, probability=0.65):
        return {
            "kind": "prop", "rank": 1, "label": "STRONG",
            "bet": "Take Devers over 0.5 hits at -140", "why": [],
            "player": "Rafael Devers", "team": "BOS", "game_pk": 1001,
            "event_id": "e0", "away_team": "COL", "home_team": "NYY",
            "first_pitch_utc": FUTURE, "market": "batter_hits", "line": 0.5,
            "side": "Over", "probability": probability, "market_probability": 0.60,
            "breakeven": 0.55, "price": -140, "book": "fanduel", "books": 7,
            "batting_slot": 3, "expected_pa": 4.3,
            "expected_pa_source": "batting_slot", "observed_utc": "x",
        }

    def test_frozen_card_merges_all_three_kinds(self):
        from src.report import card as card_mod

        card = {
            "date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {},
            "filled": 0, "games_on_slate": 1,
            "picks": [self._game_row_pick(0.60)],
            "total_picks": [self._total_row_pick(0.70)],
            "prop_picks": [self._prop_row_pick(0.55)],
        }
        card_ledger.publish(card, path=self.path)

        served = card_mod.frozen_card("2026-09-14")
        self.assertIn("all_bets", served)
        self.assertEqual(3, len(served["all_bets"]))
        self.assertEqual(["total", "game", "prop"],
                         [m["kind"] for m in served["all_bets"]])
        self.assertEqual([1, 2, 3], [m["position"] for m in served["all_bets"]])

    def test_an_old_row_with_neither_total_nor_prop_picks_still_serves_all_bets(self):
        """A row published before EITHER feature existed (only `picks`) --
        `all_bets` still comes back, one entry, the game pick alone."""
        from src.ledger.chain import HashChainLedger
        from src.report import card as card_mod

        legacy_payload = {
            "kind": card_ledger.KIND_PUBLISHED,
            "date": "2026-09-14", "published_utc": "2026-09-01T20:00:00Z",
            "rule": "r", "basis": "b", "disclaimer": "d", "model_id": "m",
            "calibrated": True, "calibration": {},
            "n_picks": 1, "n_filled": 0, "n_locked": 0,
            "picks": [self._game_row_pick(0.60)],
            "games_on_slate": 1,
            # No "prop_picks" or "total_picks" keys at all.
        }
        HashChainLedger(self.path).append(legacy_payload)

        served = card_mod.frozen_card("2026-09-14")
        self.assertEqual(1, len(served["all_bets"]))
        self.assertEqual("game", served["all_bets"][0]["kind"])
        self.assertEqual([], served["total_picks"])
        self.assertEqual([], served["prop_picks"])


class LineupPostedOnEveryMergedItem(unittest.TestCase):
    """Opus checker problem 3, fixed 2026-09-14: a page reading `all_bets`
    top to bottom had no way to see that a prop pick's estimate stood on no
    posted lineup -- the marker lived one hop away, on `prop_picks[index]`
    alone. Every merged item now carries `lineup_posted`."""

    def test_game_and_total_items_carry_lineup_posted_none(self):
        merged = daily_card.merge_all_bets(
            [_game_pick(0.60)], [_total_pick(0.55)], [])
        by_kind = {m["kind"]: m for m in merged}
        self.assertIsNone(by_kind["game"]["lineup_posted"])
        self.assertIsNone(by_kind["total"]["lineup_posted"])

    def test_a_prop_item_carries_its_own_lineup_posted_value(self):
        pre_lineup = _prop_pick(0.90, bet="Pre-lineup pick")
        pre_lineup["lineup_posted"] = False
        posted = _prop_pick(0.20, bet="Posted pick")
        posted["lineup_posted"] = True
        merged = daily_card.merge_all_bets([], [], [pre_lineup, posted])
        by_bet = {m["bet"]: m for m in merged}
        self.assertFalse(by_bet["Pre-lineup pick"]["lineup_posted"])
        self.assertTrue(by_bet["Posted pick"]["lineup_posted"])

    def test_a_pre_lineup_pick_at_the_top_of_the_merge_is_still_marked(self):
        """The exact shape the checker's live example described: a
        pre-lineup prop ranked ABOVE a game pick must still show, on that
        top row itself, that no lineup stood behind it."""
        # market_probability/breakeven supplied 2026-09-14: PROP_RANK_SOURCE
        # is now "both", which ranks by the market's number.
        pre_lineup_top = _prop_pick(0.90, market_probability=0.80, breakeven=0.60)
        pre_lineup_top["lineup_posted"] = False
        lower_game = _game_pick(0.55)
        merged = daily_card.merge_all_bets([lower_game], [], [pre_lineup_top])
        self.assertEqual("prop", merged[0]["kind"])
        self.assertFalse(merged[0]["lineup_posted"])


if __name__ == "__main__":
    unittest.main()
