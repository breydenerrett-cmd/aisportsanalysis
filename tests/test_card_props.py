"""Player props on the card -- the owner's ask, 2026-09-12: "Did you wire
everything? It's still showing ML's". The card stays moneyline-first; the
likeliest player props that clear their price join it as frozen, graded
picks, exactly like a game pick.

Covers, in order:
  * `src.analysis.daily_card.select_props` -- the selection rule, pure
  * `src.appstate.card_ledger` -- publish carries/replaces prop picks,
    settle grades them from synthetic box rows, record splits by kind
  * `src.report.card` -- frozen_card stamps position, card_for_date with an
    injected prop board (never the real disk)

Every test runs against a temporary ledger path or an injected board; none
of them touch evidence/cards_v1.jsonl or data/processed/*.jsonl.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from src.analysis import daily_card
from src.appstate import card_ledger


NOW = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
FUTURE = "2026-09-12T23:10:00Z"   # 5h10m after NOW: open, not locked
SOON = "2026-09-12T21:30:00Z"     # 3h30m after NOW: within the 4h lock window
PAST = "2026-09-12T17:00:00Z"     # before NOW: started


def _contract(player="Rafael Devers", market="batter_hits", line=0.5,
             side="Over", probability=0.65, market_probability=0.62,
             breakeven=0.55, price=-140, book="fanduel", books=7,
             batting_slot=3, expected_pa=4.3,
             expected_pa_source="batting_slot",
             game_pk=823499, event_id="e1", away_team="KC", home_team="BOS",
             first_pitch_utc=FUTURE, team="BOS", season_rate=0.71,
             observed_utc="2026-09-12T16:00:00Z"):
    """A prop contract already ENRICHED with game identity -- the shape
    `src.report.card._build_prop_picks` hands to `select_props`, per that
    function's own docstring."""
    return {
        "player": player, "market": market, "line": line, "side": side,
        "probability": probability, "market_probability": market_probability,
        "breakeven": breakeven, "price": price, "book": book, "books": books,
        "batting_slot": batting_slot, "expected_pa": expected_pa,
        "expected_pa_source": expected_pa_source,
        "game_pk": game_pk, "event_id": event_id,
        "away_team": away_team, "home_team": home_team,
        "first_pitch_utc": first_pitch_utc, "team": team,
        "season_rate": season_rate, "observed_utc": observed_utc,
    }


class SelectionRule(unittest.TestCase):
    def test_ranked_by_probability_never_by_the_gap(self):
        """A must outrank B: A's probability is higher even though B's gap
        over its own breakeven (probability - breakeven) is bigger. Ranking
        by the gap would put B first; the rule forbids that."""
        low_prob_big_gap = _contract(player="Big Gap", probability=0.60,
                                     breakeven=0.50, market="batter_hits")
        high_prob_small_gap = _contract(player="Small Gap", probability=0.65,
                                        breakeven=0.64, market="batter_total_bases")
        picks = daily_card.select_props(
            [low_prob_big_gap, high_prob_small_gap], now=NOW)
        self.assertEqual(2, len(picks))
        self.assertEqual("Small Gap", picks[0]["player"])
        self.assertEqual("Big Gap", picks[1]["player"])
        self.assertEqual(1, picks[0]["position"])
        self.assertEqual(2, picks[1]["position"])

    def test_the_floor_is_more_likely_than_not_strictly(self):
        at_floor = _contract(player="At Floor", probability=0.50, breakeven=0.40)
        above_floor = _contract(player="Above Floor", probability=0.501, breakeven=0.40)
        picks = daily_card.select_props([at_floor, above_floor], now=NOW)
        players = {p["player"] for p in picks}
        self.assertNotIn("At Floor", players)
        self.assertIn("Above Floor", players)

    def test_must_clear_its_own_price(self):
        """More likely than not is not enough -- our number has to beat
        what the price requires."""
        does_not_clear = _contract(player="No Clear", probability=0.55, breakeven=0.56)
        clears = _contract(player="Clears", probability=0.55, breakeven=0.54)
        picks = daily_card.select_props([does_not_clear, clears], now=NOW)
        players = {p["player"] for p in picks}
        self.assertNotIn("No Clear", players)
        self.assertIn("Clears", players)

    def test_a_season_average_fallback_is_never_a_pick(self):
        """No posted lineup, no pick -- `expected_pa_source` must read
        'batting_slot', not the season-average fallback."""
        no_lineup = _contract(player="No Lineup",
                              expected_pa_source="season_average")
        picks = daily_card.select_props([no_lineup], now=NOW)
        self.assertEqual([], picks)

    def test_one_pick_per_player_the_higher_probability_one(self):
        weak = _contract(player="Two Props", market="batter_hits",
                         probability=0.55, breakeven=0.50)
        strong = _contract(player="Two Props", market="batter_total_bases",
                           probability=0.70, breakeven=0.50)
        picks = daily_card.select_props([weak, strong], now=NOW)
        self.assertEqual(1, len(picks))
        self.assertEqual("batter_total_bases", picks[0]["market"])

    def test_max_three_picks_no_minimum(self):
        contracts = [_contract(player=f"Player {i}", probability=0.60 + i * 0.01,
                               breakeven=0.50)
                    for i in range(5)]
        picks = daily_card.select_props(contracts, now=NOW)
        self.assertEqual(daily_card.MAX_PROP_PICKS, len(picks))
        self.assertEqual(3, len(picks))
        # Highest probabilities kept, in descending order.
        self.assertEqual(["Player 4", "Player 3", "Player 2"],
                         [p["player"] for p in picks])

    def test_no_candidates_is_an_empty_list_not_an_error(self):
        self.assertEqual([], daily_card.select_props([], now=NOW))

    def test_a_started_game_is_excluded(self):
        started = _contract(player="Started", first_pitch_utc=PAST)
        open_game = _contract(player="Open", first_pitch_utc=FUTURE)
        picks = daily_card.select_props([started, open_game], now=NOW)
        players = {p["player"] for p in picks}
        self.assertNotIn("Started", players)
        self.assertIn("Open", players)

    def test_home_runs_never_reach_the_card(self):
        """Never a home run and never any other likelihood-only market,
        whatever the probability says -- `propboard.assessable` refuses it
        before probability is even read."""
        home_run = _contract(player="Slugger", market="batter_home_runs",
                             probability=0.90, breakeven=0.10)
        picks = daily_card.select_props([home_run], now=NOW)
        self.assertEqual([], picks)

    def test_runs_scored_never_reaches_the_card(self):
        """Caught 2026-09-12 by the second check: `propboard.assessable`
        admits three markets and the card's sentence builders know two, so
        a runs contract rendered "Take Juan Soto under 0.5
        batter_runs_scored at -140" and would have graded VOID forever
        (settlement keys runs as 'batter_runs'). Fails on the code that
        gated on `assessable` alone."""
        runs = _contract(player="Juan Soto", market="batter_runs_scored",
                         line=0.5, side="Under", probability=0.90,
                         breakeven=0.10)
        self.assertEqual([], daily_card.select_props([runs], now=NOW))

    def test_the_card_markets_are_the_ones_it_can_describe_and_settle(self):
        """The gate, the sentence vocabulary and the settlement rules must
        name the same markets, or a pick prints a field name or grades
        VOID with "no settlement rule" beside it."""
        from src.board import settle_props
        self.assertEqual(tuple(daily_card._PROP_MARKET_WORD), daily_card.PROP_MARKETS)
        for market in daily_card.PROP_MARKETS:
            self.assertIn(market, settle_props.PROP_STAT_RULES, market)
        self.assertNotIn("batter_runs_scored", daily_card.PROP_MARKETS)


class LabelBands(unittest.TestCase):
    def test_strong_lean_slight(self):
        strong = daily_card._build_prop_pick(
            _contract(probability=0.62), position=1)
        lean = daily_card._build_prop_pick(
            _contract(probability=0.55), position=1)
        slight = daily_card._build_prop_pick(
            _contract(probability=0.51), position=1)
        self.assertEqual(daily_card.LABEL_STRONG, strong["label"])
        self.assertEqual(daily_card.LABEL_LEAN, lean["label"])
        self.assertEqual(daily_card.LABEL_SLIGHT, slight["label"])


class WhySentences(unittest.TestCase):
    def test_the_why_sentences_carry_the_real_numbers(self):
        pick = daily_card.select_props([_contract()], now=NOW)[0]
        self.assertEqual(
            "Take Rafael Devers over 0.5 hits at -140", pick["bet"])
        first, second = pick["why"]
        self.assertIn("71%", first)
        self.assertIn("3rd", first)
        self.assertIn("4.3", first)
        self.assertIn("at least one hit", first)
        self.assertIn("62%", second)
        self.assertIn("-140", second)
        self.assertIn("58%", second)   # -140's own break-even

    def test_our_own_number_leads_the_why(self):
        """Seen on the first live build, 2026-09-12: "Connor Norby has at
        least one total base in 55% of his games this season" on a STRONG
        pick whose price needs 63% -- the season rate is an input, our
        probability (the rate lifted by tonight's trips) is what the pick
        stands on, and it went unsaid. The reader saw a number below the
        break-even and a label that said the opposite. Fails on the
        sentence that opened with the rate alone."""
        pick = daily_card.select_props(
            [_contract(player="Connor Norby", market="batter_total_bases",
                      line=0.5, probability=0.658, breakeven=0.632,
                      price=-172, season_rate=0.55, batting_slot=2,
                      expected_pa=4.4)], now=NOW)[0]
        first = pick["why"][0]
        self.assertTrue(first.startswith("Our own numbers make it 66%. "), first)
        self.assertIn("55% of his games", first)
        self.assertIn("batting 2nd tonight, he should get about 4.4 trips", first)

    def test_total_bases_gets_its_own_clause(self):
        pick = daily_card.select_props(
            [_contract(market="batter_total_bases", line=1.5,
                      season_rate=0.44)], now=NOW)[0]
        self.assertIn("at least 2 total bases", pick["why"][0])
        self.assertIn("44%", pick["why"][0])

    def test_an_under_pick_quotes_the_under_rate_not_the_over_rate(self):
        """Checker problem 3, live: `season_rate` on a contract is always
        the OVER outcome's rate (`propboard.build` writes the same value
        onto both sides of a line). The real case that shipped wrong: Kevin
        McGonigle Under 1.5 hits, probability 0.758 (STRONG), season_rate
        0.18 (his rate of 2+ hits) -- the first draft printed "has at least
        2 hits in 18% of his games", the rate for the side nobody bet,
        sitting next to a much larger probability for the opposite
        outcome. The sentence must describe the UNDER: at most 1 hit, at
        the complementary rate, 82%."""
        pick = daily_card.select_props(
            [_contract(player="Kevin McGonigle", market="batter_hits",
                      line=1.5, side="Under", probability=0.758,
                      breakeven=0.70, price=-250, season_rate=0.18,
                      batting_slot=9)], now=NOW)[0]
        self.assertEqual(
            "Take Kevin McGonigle under 1.5 hits at -250", pick["bet"])
        first = pick["why"][0]
        self.assertIn("82%", first)
        self.assertNotIn("18%", first)
        self.assertIn("1 hit or fewer", first)
        self.assertNotIn("at least 2 hits", first)

    def test_an_under_total_bases_pick_also_flips_the_rate(self):
        pick = daily_card.select_props(
            [_contract(market="batter_total_bases", line=1.5, side="Under",
                      probability=0.60, breakeven=0.55, season_rate=0.44)],
            now=NOW)[0]
        first = pick["why"][0]
        self.assertIn("56%", first)
        self.assertNotIn("44%", first)
        self.assertIn("1 total base or fewer", first)


class LedgerPublish(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def _card(self, prop_picks):
        return {
            "date": "2026-09-12", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {},
            "filled": 0, "games_on_slate": 1,
            "picks": [{
                "rank": 1, "label": "STRONG", "bet": "Take Yankees to win at -150",
                "why": ["because"], "market": "moneyline", "line": None,
                "side": "home", "team": "NYY", "team_name": "Yankees",
                "opponent_name": "Rockies", "price": -150, "book": "dk",
                "books": 8, "confidence": 0.74, "market_probability": 0.74,
                "model_probability": 0.64, "game_id": "g1", "game_pk": 1001,
                "event_id": "e0", "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "2026-09-12T16:00:00Z",
                "model": {},
            }],
            "prop_picks": prop_picks,
        }

    def test_an_open_prop_pick_is_replaced_on_republish(self):
        first = card_ledger.publish(
            self._card(daily_card.select_props([_contract(price=-140)], now=NOW)),
            now=NOW.isoformat(), path=self.path)
        self.assertEqual(-140, first["prop_picks"][0]["price"])
        self.assertFalse(first["prop_picks"][0]["locked"])

        second = card_ledger.publish(
            self._card(daily_card.select_props([_contract(price=-160)], now=NOW)),
            now=NOW.isoformat(), path=self.path)
        self.assertFalse(second["already_published"])
        self.assertEqual(-160, second["prop_picks"][0]["price"])

    def test_a_locked_prop_pick_carries_forward_untouched(self):
        """Within the lock window, a later run cannot change what was
        already shown -- the same promise a game pick's `locked` field
        makes."""
        locking_now = datetime(2026, 9, 12, 18, 30, tzinfo=timezone.utc)
        first = card_ledger.publish(
            self._card(daily_card.select_props(
                [_contract(price=-140, first_pitch_utc=SOON)], now=locking_now)),
            now=locking_now.isoformat(), path=self.path)
        self.assertTrue(first["prop_picks"][0]["locked"])
        self.assertEqual(-140, first["prop_picks"][0]["price"])

        later = datetime(2026, 9, 12, 19, 0, tzinfo=timezone.utc)
        second = card_ledger.publish(
            self._card(daily_card.select_props(
                [_contract(price=-999, first_pitch_utc=SOON)], now=later)),
            now=later.isoformat(), path=self.path)
        self.assertEqual(-140, second["prop_picks"][0]["price"],
                         "a locked prop pick was rewritten")

    def test_republishing_the_same_prop_picks_writes_nothing(self):
        card = self._card(daily_card.select_props([_contract()], now=NOW))
        first = card_ledger.publish(card, now=NOW.isoformat(), path=self.path)
        second = card_ledger.publish(card, now=NOW.isoformat(), path=self.path)
        self.assertTrue(second["already_published"])
        self.assertEqual(first["row_hash"], second["row_hash"])

    def test_a_card_with_no_prop_picks_still_publishes(self):
        """No prop picks is a real state (a thin prop board), unlike an
        empty GAME pick list, which refuses."""
        row = card_ledger.publish(self._card([]), path=self.path)
        self.assertEqual([], row["prop_picks"])
        self.assertFalse(row["already_published"])


class LedgerSettle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def _publish(self, prop_picks):
        card = {
            "date": "2026-09-12", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {},
            "filled": 0, "games_on_slate": 1,
            "picks": [{
                "rank": 1, "label": "STRONG", "bet": "x", "why": [],
                "market": "moneyline", "line": None, "side": "home",
                "team": "NYY", "team_name": "Yankees", "opponent_name": "COL",
                "price": -150, "book": "dk", "books": 8, "confidence": 0.74,
                "market_probability": 0.74, "model_probability": 0.64,
                "game_id": "g1", "game_pk": 1001, "event_id": "e0",
                "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "x", "model": {},
            }],
            "prop_picks": prop_picks,
        }
        return card_ledger.publish(card, path=self.path)

    def _box(self, game_pk, player_name, **stats):
        row = {"type": "batter", "game_pk": game_pk, "player_name": player_name,
              "h": 0, "total_bases": 0}
        row.update(stats)
        return row

    def test_win_loss_push_void_from_synthetic_box_rows(self):
        win_pick = daily_card._build_prop_pick(
            _contract(player="Winner", market="batter_hits", line=0.5,
                     side="Over", game_pk=2001), position=1)
        loss_pick = daily_card._build_prop_pick(
            _contract(player="Loser", market="batter_hits", line=0.5,
                     side="Over", game_pk=2001), position=2)
        push_pick = daily_card._build_prop_pick(
            _contract(player="Pusher", market="batter_total_bases", line=1.0,
                     side="Over", game_pk=2001), position=3)
        void_pick = daily_card._build_prop_pick(
            _contract(player="Ghost", market="batter_hits", line=0.5,
                     side="Over", game_pk=2001), position=4)

        self._publish([win_pick, loss_pick, push_pick, void_pick])

        box_rows = [
            self._box(2001, "Winner", h=1, total_bases=1),
            self._box(2001, "Loser", h=0, total_bases=0),
            self._box(2001, "Pusher", h=1, total_bases=1),
            # "Ghost" has no box row at all -- postponed, or never played.
        ]
        row = card_ledger.settle(
            "2026-09-12", {1001: {"away_score": 2, "home_score": 5}},
            prop_box_rows=box_rows, path=self.path)

        by_player = {g["player"]: g for g in row["prop_picks"]}
        self.assertEqual(card_ledger.RESULT_WIN, by_player["Winner"]["result"])
        self.assertEqual(card_ledger.RESULT_LOSS, by_player["Loser"]["result"])
        self.assertEqual(card_ledger.RESULT_PUSH, by_player["Pusher"]["result"])
        self.assertEqual(card_ledger.RESULT_VOID, by_player["Ghost"]["result"])
        self.assertEqual(1, row["prop_wins"])
        self.assertEqual(1, row["prop_losses"])
        self.assertEqual(1, row["prop_pushes"])
        self.assertEqual(1, row["prop_voids"])
        # Flat one-unit stakes, same as a game pick: -140 wins 0.7143u.
        self.assertAlmostEqual(0.7143, by_player["Winner"]["profit_units"], places=3)
        self.assertEqual(-1.0, by_player["Loser"]["profit_units"])

    def test_settling_with_no_box_rows_voids_every_prop_pick_not_a_crash(self):
        pick = daily_card._build_prop_pick(
            _contract(player="Nobody Home", game_pk=2001), position=1)
        self._publish([pick])
        row = card_ledger.settle(
            "2026-09-12", {1001: {"away_score": 1, "home_score": 4}},
            path=self.path)
        self.assertEqual(1, row["prop_voids"])
        self.assertEqual(0, row["prop_wins"])

    def test_the_published_prop_picks_are_never_rewritten_by_settle(self):
        pick = daily_card._build_prop_pick(
            _contract(player="Winner", game_pk=2001, price=-140), position=1)
        published = self._publish([pick])
        card_ledger.settle(
            "2026-09-12", {1001: {"away_score": 2, "home_score": 5}},
            prop_box_rows=[self._box(2001, "Winner", h=2, total_bases=3)],
            path=self.path)
        again = card_ledger.published_row("2026-09-12", path=self.path)
        self.assertEqual(published["row_hash"], again["row_hash"])
        self.assertEqual(-140, again["prop_picks"][0]["price"])


class RecordByKind(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def test_the_record_splits_game_and_prop_picks_apart(self):
        card = {
            "date": "2026-09-12", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {},
            "filled": 0, "games_on_slate": 1,
            "picks": [{
                "rank": 1, "label": "STRONG", "bet": "x", "why": [],
                "market": "moneyline", "line": None, "side": "home",
                "team": "NYY", "team_name": "Yankees", "opponent_name": "COL",
                "price": -150, "book": "dk", "books": 8, "confidence": 0.74,
                "market_probability": 0.74, "model_probability": 0.64,
                "game_id": "g1", "game_pk": 1001, "event_id": "e0",
                "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "x", "model": {},
            }],
            "prop_picks": [daily_card._build_prop_pick(
                _contract(player="Winner", game_pk=1001, price=-140),
                position=1)],
        }
        card_ledger.publish(card, path=self.path)
        card_ledger.settle(
            "2026-09-12",
            {1001: {"away_score": 2, "home_score": 5}},   # game pick WINS
            prop_box_rows=[{"type": "batter", "game_pk": 1001,
                            "player_name": "Winner", "h": 0, "total_bases": 0}],
            path=self.path)   # prop pick LOSES (no hit)

        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["by_kind"]["game"]["wins"])
        self.assertEqual(0, rec["by_kind"]["game"]["losses"])
        self.assertEqual(0, rec["by_kind"]["prop"]["wins"])
        self.assertEqual(1, rec["by_kind"]["prop"]["losses"])
        # The pooled top-level totals stay the GAME picks alone -- unchanged
        # behaviour for every existing reader of record().
        self.assertEqual(rec["wins"], rec["by_kind"]["game"]["wins"])


class FrozenCardServesProps(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")
        self._real = card_ledger.CARD_STORE
        card_ledger.CARD_STORE = self.path
        self.addCleanup(setattr, card_ledger, "CARD_STORE", self._real)

    def test_frozen_card_stamps_position_by_probability(self):
        from src.report import card as card_mod

        lower = daily_card._build_prop_pick(
            _contract(player="Lower", probability=0.55, breakeven=0.50,
                     game_pk=1001), position=1)
        higher = daily_card._build_prop_pick(
            _contract(player="Higher", probability=0.70, breakeven=0.50,
                     game_pk=1002), position=1)
        card = {
            "date": "2026-09-12", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {},
            "filled": 0, "games_on_slate": 1,
            "picks": [{
                "rank": 1, "label": "STRONG", "bet": "x", "why": [],
                "market": "moneyline", "line": None, "side": "home",
                "team": "NYY", "team_name": "Yankees", "opponent_name": "COL",
                "price": -150, "book": "dk", "books": 8, "confidence": 0.74,
                "market_probability": 0.74, "model_probability": 0.64,
                "game_id": "g1", "game_pk": 1001, "event_id": "e0",
                "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "x", "model": {},
            }],
            # Stored out of probability order on purpose -- `position` has
            # to be recomputed at serve time, not trusted from storage.
            "prop_picks": [lower, higher],
        }
        card_ledger.publish(card, path=self.path)

        served = card_mod.frozen_card("2026-09-12")
        self.assertEqual(2, len(served["prop_picks"]))
        self.assertEqual("Higher", served["prop_picks"][0]["player"])
        self.assertEqual(1, served["prop_picks"][0]["position"])
        self.assertEqual("Lower", served["prop_picks"][1]["player"])
        self.assertEqual(2, served["prop_picks"][1]["position"])
        self.assertIsNone(served["prop_reason"])

    def _base_card(self, **prop_picks_kwarg):
        card = {
            "date": "2026-09-12", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {},
            "filled": 0, "games_on_slate": 1,
            "picks": [{
                "rank": 1, "label": "STRONG", "bet": "x", "why": [],
                "market": "moneyline", "line": None, "side": "home",
                "team": "NYY", "team_name": "Yankees", "opponent_name": "COL",
                "price": -150, "book": "dk", "books": 8, "confidence": 0.74,
                "market_probability": 0.74, "model_probability": 0.64,
                "game_id": "g1", "game_pk": 1001, "event_id": "e0",
                "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "x", "model": {},
            }],
        }
        card.update(prop_picks_kwarg)
        return card

    def test_an_old_row_with_no_prop_picks_serves_an_empty_list(self):
        """Checker problem 4: a MISSING `prop_picks` key (an old row, from
        before this feature shipped) must not read as a verdict -- it must
        not claim any prop was evaluated and found wanting.

        `card_ledger.publish()` itself ALWAYS writes a `prop_picks` key now
        (that is `PROP_FROZEN_FIELDS`' whole point), so it cannot be used to
        manufacture a truly key-less row any more -- exactly the 19 real
        rows in evidence/cards_v1.jsonl published before 2026-09-12, which
        predate this feature's schema entirely. Appending straight through
        the chain primitive reproduces that shape without going through
        `publish`'s normalisation.
        """
        from src.ledger.chain import HashChainLedger
        from src.report import card as card_mod

        legacy_payload = dict(self._base_card())
        legacy_payload.update({
            "kind": card_ledger.KIND_PUBLISHED,
            "published_utc": "2026-09-01T20:00:00Z",
            "n_picks": 1, "n_filled": 0, "n_locked": 0,
            # No "prop_picks", "n_prop_picks", or "n_prop_locked" -- this
            # row predates the feature, not just an empty selection.
        })
        HashChainLedger(self.path).append(legacy_payload)

        served = card_mod.frozen_card("2026-09-12")
        self.assertEqual([], served["prop_picks"])
        self.assertIsNotNone(served["prop_reason"])
        self.assertEqual(card_mod._PROP_NOT_PART_OF_CARD, served["prop_reason"])
        self.assertNotIn("cleared", served["prop_reason"].lower())

    def test_a_row_that_considered_props_and_selected_none_says_so_differently(self):
        """The OTHER empty state: `prop_picks` is present and `[]` -- props
        WERE considered, none passed `select_props`. Checker problem 4's
        other half: this reason must read differently from (and more
        specifically than) 'props were never part of this card'."""
        from src.report import card as card_mod

        card_ledger.publish(self._base_card(prop_picks=[]), path=self.path)
        served = card_mod.frozen_card("2026-09-12")
        self.assertEqual([], served["prop_picks"])
        self.assertEqual(card_mod._PROP_NONE_SELECTED_FROZEN, served["prop_reason"])
        self.assertNotEqual(card_mod._PROP_NOT_PART_OF_CARD, served["prop_reason"])
        self.assertNotIn("bar", served["prop_reason"].lower())


class CardForDateWithInjectedBoard(unittest.TestCase):
    """`card_for_date`'s live build, with the prop board (and the
    event_id<->game_pk map) injected -- this must never read
    data/processed/batter_props.jsonl, boxscores, or event_game_map.jsonl
    off the real disk."""

    def _entry(self, game_pk, away, home, first_pitch):
        """PRODUCTION SHAPE, deliberately: `src.providers.mlb.parse_game`
        never emits an `event_id` key (checker BLOCKER, problem 1 -- the
        old version of this helper hand-wrote one, which is why the join
        bug shipped with a green suite). A test that wants a prop to join
        must do it the way production does: through an injected
        `event_map`, not by giving the entry a field it never actually
        carries."""
        return {"dossier": {
            "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                     "start_time_utc": first_pitch, "game_number": 1},
            "sections": {},
        }}

    def test_the_board_is_never_read_from_disk_and_the_pick_carries_identity(self):
        """The join, end to end, against a production-shaped entry (no
        event_id) plus an injected event_map -- this is the exact path that
        was always empty before the BLOCKER fix."""
        from src.report import card as card_mod

        entries = [self._entry(823499, "KC", "BOS", FUTURE)]
        board_calls = []

        def fake_board(date):
            board_calls.append(date)
            return {"date": date, "contracts": [_contract()], "reason": None}

        payload = card_mod.card_for_date(
            entries, [], date="2026-09-12", now=NOW, prop_board=fake_board,
            event_map={"e1": {"game_pk": 823499}},
            prefer_frozen=False)

        self.assertEqual(["2026-09-12"], board_calls)
        self.assertEqual(1, len(payload["prop_picks"]))
        pick = payload["prop_picks"][0]
        self.assertEqual(823499, pick["game_pk"])
        self.assertEqual("KC", pick["away_team"])
        self.assertEqual("BOS", pick["home_team"])
        self.assertIsNone(payload["prop_reason"])
        self.assertFalse(payload["frozen"])

    def test_the_event_map_game_pk_may_be_a_string(self):
        """`data/processed/event_game_map.jsonl` stores `game_pk` as a
        STRING (checker problem 1's fix note); the join must not silently
        fail on a str/int mismatch the way this project has shipped twice
        before (src/core/asof.py's `game_pk_key` docstring)."""
        from src.report import card as card_mod

        entries = [self._entry(823499, "KC", "BOS", FUTURE)]
        payload = card_mod.card_for_date(
            entries, [], date="2026-09-12", now=NOW,
            prop_board=lambda date: {"contracts": [_contract()], "reason": None},
            event_map={"e1": {"game_pk": "823499"}},
            prefer_frozen=False)
        self.assertEqual(1, len(payload["prop_picks"]))

    def test_an_empty_board_leaves_prop_picks_empty_with_a_reason(self):
        from src.report import card as card_mod

        payload = card_mod.card_for_date(
            [], [], date="2026-09-12", now=NOW, prefer_frozen=False,
            prop_board=lambda date: {"contracts": [], "reason": "no props posted"})
        self.assertEqual([], payload["prop_picks"])
        self.assertEqual("no props posted", payload["prop_reason"])

    def test_a_board_that_raises_does_not_take_the_card_down(self):
        from src.report import card as card_mod

        def broken_board(date):
            raise RuntimeError("store is corrupt")

        payload = card_mod.card_for_date(
            [], [], date="2026-09-12", now=NOW, prop_board=broken_board,
            prefer_frozen=False)
        self.assertEqual([], payload["prop_picks"])
        self.assertIsNotNone(payload["prop_reason"])
        # The moneyline branch is untouched by a broken prop board.
        self.assertIn("reason", payload)

    def test_a_contract_whose_game_is_not_on_the_schedule_is_dropped(self):
        """A prop quote for a game the schedule read does not carry -- a
        feed mismatch, or an event_id the map cannot resolve -- cannot
        become a pick without knowing which game or when it starts."""
        from src.report import card as card_mod

        payload = card_mod.card_for_date(
            [], [], date="2026-09-12", now=NOW, prefer_frozen=False,
            event_map={},
            prop_board=lambda date: {"contracts": [_contract(event_id="unknown")],
                                     "reason": None})
        self.assertEqual([], payload["prop_picks"])

    def test_the_selected_reason_avoids_the_retired_register(self):
        """Checker problem 5: the live 'nothing selected' reason must not
        paraphrase 'nothing clears the bar'."""
        from src.report import card as card_mod

        payload = card_mod.card_for_date(
            [], [], date="2026-09-12", now=NOW, prefer_frozen=False,
            event_map={},
            prop_board=lambda date: {
                "contracts": [_contract(expected_pa_source="season_average")],
                "reason": None})
        self.assertEqual([], payload["prop_picks"])
        self.assertNotIn("bar", payload["prop_reason"].lower())
        self.assertNotIn("edge", payload["prop_reason"].lower())

    def test_the_default_board_is_asked_for_the_full_board_not_the_default_page(self):
        """Checker problem 2: the real default must ask
        `props.board_for_date` for `MAX_LIMIT`, not let it silently cap at
        `DEFAULT_LIMIT`. `props_mod.board_for_date` itself is monkeypatched
        (not called) so this never touches disk."""
        from src.report import card as card_mod
        from src.report import props as props_mod

        calls = []
        original = props_mod.board_for_date

        def fake(date, **kwargs):
            calls.append(kwargs.get("limit"))
            return {"contracts": [], "reason": "no props posted"}

        props_mod.board_for_date = fake
        try:
            card_mod.card_for_date(
                [], [], date="2026-09-12", now=NOW, prefer_frozen=False,
                event_map={})
        finally:
            props_mod.board_for_date = original
        self.assertEqual([props_mod.MAX_LIMIT], calls)
        self.assertGreater(props_mod.MAX_LIMIT, props_mod.DEFAULT_LIMIT)


if __name__ == "__main__":
    unittest.main()
