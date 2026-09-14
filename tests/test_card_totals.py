"""Game totals on the card -- the owner's ask, 2026-09-14: "merge the today
bets for ALL BETS not just MLs include all best bets like player props ...
run lines and the niche bets." Totals are the first of those the scout
found already priced but never read: `src.model.strength.market_probabilities`
already computes `p_over`, and `src.analysis.daily_card.build_pick_candidates`
never passed `totals=` into `model_line` -- so `p_over` was always empty and
no total pick could ever have existed.

Covers, in order:
  * `src.analysis.daily_card.build_total_candidates` / `select_totals` --
    the selection rule, pure
  * `src.report.card.total_rows` -- the plumbing that reads a consensus
    line off the multi-book totals store, injected rows only, never disk
  * `src.report.card.card_for_date` -- proof that `strength.model_line` is
    actually called with `totals=[this game's own line]` now
  * `src.appstate.card_ledger` -- publish carries/replaces total picks,
    settle grades them from a results map, record splits by kind, history
    joins by game_pk + line + side
  * `src.report.card.frozen_card` -- serves total picks stamped by position

Every test runs against a temporary ledger path or injected rows; none of
them touch evidence/cards_v1.jsonl or data/processed/*.jsonl.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from src.analysis import daily_card
from src.appstate import card_ledger


NOW = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
FUTURE = "2026-09-14T22:40:00Z"   # well after NOW: open, not locked
SOON = "2026-09-14T19:30:00Z"     # 3h30m after NOW: within the 4h lock window
PAST = "2026-09-14T15:00:00Z"     # before NOW: started


def _game(gid="SD-COL-2026-09-14-1", game_pk=744001, away="SD", home="COL",
         first_pitch=FUTURE):
    return {
        "game_id": gid, "game_pk": game_pk, "event_id": "e1",
        "away_team": away, "home_team": home,
        "away_name": "Padres", "home_name": "Rockies",
        "first_pitch_utc": first_pitch,
    }


def _detail(line=8.5, over_p=0.60, under_p=0.40, over_price=-115,
           under_price=-105, books=8, observed="2026-09-14T15:30:00Z"):
    return {
        "line": line,
        "over": {"best_price": over_price, "best_book": "dk",
                 "consensus_probability": over_p},
        "under": {"best_price": under_price, "best_book": "fanduel",
                  "consensus_probability": under_p},
        "books": books, "observed_utc": observed,
    }


def _model_line(p_over_map):
    return {"p_over": dict(p_over_map)}


class SelectionRule(unittest.TestCase):
    def test_the_side_is_whichever_the_market_favours(self):
        """Over favoured -> side "over"; the reverse game -> side "under"."""
        over_favoured = _game(gid="g1", game_pk=1)
        under_favoured = _game(gid="g2", game_pk=2)
        games = [over_favoured, under_favoured]
        model_lines = {
            "g1": _model_line({8.5: 0.70}),
            "g2": _model_line({8.5: 0.20}),  # p_over 0.20 -> p_under 0.80
        }
        total_rows = {
            "g1": _detail(line=8.5, over_p=0.60, under_p=0.40),
            "g2": _detail(line=8.5, over_p=0.35, under_p=0.65),
        }
        candidates = daily_card.build_total_candidates(
            games, model_lines=model_lines, total_rows=total_rows)
        by_game = {c["game_id"]: c for c in candidates}
        self.assertEqual("over", by_game["g1"]["side"])
        self.assertEqual("under", by_game["g2"]["side"])
        self.assertEqual(-115, by_game["g1"]["price"],
                         "the OVER side's own price, not the under's")
        self.assertEqual(-105, by_game["g2"]["price"],
                         "the UNDER side's own price, not the over's")

    def test_agreement_is_required_or_the_candidate_is_dropped(self):
        """The market favours Over; our own model does NOT (p_over <= 0.5
        at that exact line) -- no fallback pile, the candidate is simply
        gone."""
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.5: 0.45})}
        total_rows = {game["game_id"]: _detail(line=8.5, over_p=0.60,
                                               under_p=0.40)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual([], candidates)

    def test_must_clear_its_own_price(self):
        """The market and our model agree on Over; our number does not
        clear the break-even the OVER price demands."""
        game = _game()
        # -150 needs 60% to break even; our number agrees (0.55 > 0.5) but
        # does not clear it.
        model_lines = {game["game_id"]: _model_line({8.5: 0.55})}
        total_rows = {game["game_id"]: _detail(
            line=8.5, over_p=0.60, under_p=0.40, over_price=-150)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual([], candidates)

        # Same shape, but our number clears -150's 60% break-even.
        model_lines_clears = {game["game_id"]: _model_line({8.5: 0.66})}
        candidates_clear = daily_card.build_total_candidates(
            [game], model_lines=model_lines_clears, total_rows=total_rows)
        self.assertEqual(1, len(candidates_clear))

    def test_a_line_the_model_was_never_asked_about_is_skipped(self):
        """`model_lines[gid]["p_over"]` has no entry at the board's own
        line -- the caller (src.report.card) is responsible for having
        asked the model about THIS line; if it did not, there is nothing
        to agree or disagree with, and the candidate is dropped rather than
        guessed at."""
        game = _game()
        model_lines = {game["game_id"]: _model_line({7.5: 0.90})}  # wrong line
        total_rows = {game["game_id"]: _detail(line=8.5)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual([], candidates)

    def test_a_game_with_no_total_board_is_skipped_not_an_error(self):
        game = _game()
        candidates = daily_card.build_total_candidates(
            [game], model_lines={game["game_id"]: _model_line({8.5: 0.9})},
            total_rows={})
        self.assertEqual([], candidates)

    def test_at_most_three_ranked_by_market_probability(self):
        games, model_lines, total_rows = [], {}, {}
        # Five candidates, each clearly agreeing and clearing its price, at
        # DIFFERENT market probabilities.
        market_ps = [0.52, 0.58, 0.65, 0.70, 0.55]
        for i, mp in enumerate(market_ps):
            gid = f"g{i}"
            games.append(_game(gid=gid, game_pk=100 + i))
            model_lines[gid] = _model_line({8.5: 0.95})  # comfortably agrees
            total_rows[gid] = _detail(
                line=8.5, over_p=mp, under_p=1.0 - mp, over_price=-110)
        candidates = daily_card.build_total_candidates(
            games, model_lines=model_lines, total_rows=total_rows)
        payload = daily_card.select_totals(candidates)
        self.assertEqual(daily_card.MAX_TOTAL_PICKS, len(payload["picks"]))
        self.assertEqual(3, len(payload["picks"]))
        self.assertEqual(
            [0.70, 0.65, 0.58],
            [round(p["market_probability"], 2) for p in payload["picks"]])
        self.assertEqual(5, payload["considered"])

    def test_no_candidates_is_an_empty_list_not_an_error(self):
        payload = daily_card.select_totals([])
        self.assertEqual([], payload["picks"])
        self.assertEqual(0, payload["considered"])


class WholeNumberLinePushExcluded(unittest.TestCase):
    """Opus checker problem 1, fixed 2026-09-14. A whole-number total can
    land exactly on the line -- a push, refunded, neither side's win -- and
    both the market's de-vigged number and a price's break-even are
    measured ignoring it. The old code read the Under side as `1 -
    p_over[L]`, which folds the push into the Under's win probability.

    Numbers below are the real live ones from the checker's report (BAL@NYM
    8.0 runs, captured 2026-09-14): P(over) = 0.4754, P(over at 7.5) =
    0.5508, so P(push) = 0.0754, push-excluded Under = 0.4858, push-excluded
    Over = 0.5142.
    """

    def test_the_old_bug_would_have_taken_under_the_fix_refuses_it(self):
        """The market favours Under (52.46%, the SAME number the bug
        produced for the model -- that coincidence is what let this ship).
        Push-excluded, our own number for Under is 48.58%: BELOW 50%, so
        agreement fails and the candidate is dropped, not published."""
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.0: 0.4754, 7.5: 0.5508})}
        total_rows = {game["game_id"]: _detail(
            line=8.0, over_p=0.4754, under_p=0.5246, under_price=-110)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual(
            [], candidates,
            "a whole-number Under measured WITH the push folded in would "
            "have agreed here (0.5246 > 0.5); measured correctly it does "
            "not (0.4858 < 0.5)")

    def test_push_excluded_probability_is_correct_on_the_side_that_does_agree(self):
        """Same board, market flipped to favour Over -- push-excluded, our
        Over number is 51.42%, which DOES agree and clears a generous
        price."""
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.0: 0.4754, 7.5: 0.5508})}
        total_rows = {game["game_id"]: _detail(
            line=8.0, over_p=0.55, under_p=0.45, over_price=+100)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual(1, len(candidates))
        self.assertAlmostEqual(0.5142, candidates[0]["model_probability"],
                               places=3)

    def test_a_half_point_line_is_unaffected_by_the_push_fix(self):
        """No push is possible at 8.5, so the old and new arithmetic must
        agree exactly -- a regression guard that the fix did not touch the
        common case."""
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.5: 0.55})}
        total_rows = {game["game_id"]: _detail(
            line=8.5, over_p=0.60, under_p=0.40, over_price=-110)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual(1, len(candidates))
        self.assertAlmostEqual(0.55, candidates[0]["model_probability"],
                               places=6)

    def test_a_whole_number_line_missing_the_half_below_is_refused_not_guessed(self):
        """The caller (src.report.card) is responsible for having asked the
        model about `line - 0.5` too, for exactly this reason -- if it did
        not, there is no way to measure the push and the candidate is
        dropped rather than computed on the old, wrong arithmetic."""
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.0: 0.4754})}  # no 7.5
        total_rows = {game["game_id"]: _detail(
            line=8.0, over_p=0.4754, under_p=0.5246, under_price=-110)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        self.assertEqual([], candidates)


class CardForDatePassesTheHalfLineBelowAWholeNumberTotal(unittest.TestCase):
    """`src.report.card.card_for_date` must ask the model about `line -
    0.5` too, whenever the board's own consensus line is a whole number --
    the plumbing half of the problem-1 fix. Without it,
    `build_total_candidates` always refuses a whole-number line (see
    `test_a_whole_number_line_missing_the_half_below_is_refused_not_guessed`
    above), so a whole-number total would silently never produce a pick."""

    def _entry(self, game_pk, away, home, first_pitch):
        return {"dossier": {
            "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                     "start_time_utc": first_pitch, "game_number": 1},
            "sections": {
                "teams": {
                    "away_runs_scored_pg": 4.6, "away_runs_allowed_pg": 4.2,
                    "away_games_played": 140, "away_wins": 75, "away_losses": 65,
                    "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.1,
                    "home_games_played": 140, "home_wins": 80, "home_losses": 60,
                },
                "starters": {},
            },
        }}

    def test_a_whole_number_board_line_asks_the_model_about_the_half_below_too(self):
        from src.report import card as card_mod

        entries = [self._entry(744003, "BAL", "NYM", FUTURE)]
        multibook_rows = []
        for i in range(6):
            multibook_rows.append({
                "observed_utc": "2026-09-14T15:30:00Z",
                "event_id": "e2", "commence_time": FUTURE,
                "away_team": "Baltimore Orioles", "home_team": "New York Mets",
                "market": "totals", "book": f"book{i}",
                "total": "8", "over_price": -110, "under_price": -110,
            })

        calls = []
        original = card_mod.strength.model_line

        def spy(features, **kwargs):
            calls.append(kwargs.get("totals"))
            return original(features, **kwargs)

        card_mod.strength.model_line = spy
        try:
            card_mod.card_for_date(
                entries, [], date="2026-09-14", now=NOW,
                multibook_rows=multibook_rows, prefer_frozen=False,
                prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        finally:
            card_mod.strength.model_line = original

        self.assertEqual(1, len(calls))
        self.assertEqual(
            [8.0, 7.5], calls[0],
            "a whole-number consensus total must ask the model about the "
            "half-run below it too, so build_total_candidates can measure "
            "the push")


class TotalsArePausedOnTheLiveCard(unittest.TestCase):
    """2026-09-14: the run model read above the market's total in 8 of 9
    games, and every total it would publish cleared only on our number at a
    coin-flip market. Built and graded, not published, until measured."""

    def test_the_switch_is_off_and_the_reason_says_why(self):
        from src.report import card as card_mod
        self.assertFalse(card_mod.TOTALS_ON_CARD)
        self.assertIn("measuring", card_mod._TOTALS_PAUSED)

    def test_a_live_build_carries_no_total_picks_while_paused(self):
        from src.report import card as card_mod
        entries = [CardForDatePassesTheHalfLineBelowAWholeNumberTotal()._entry(
            744003, "BAL", "NYM", FUTURE)]
        rows = [{"observed_utc": "2026-09-14T15:30:00Z", "event_id": "e2",
                 "commence_time": FUTURE, "away_team": "Baltimore Orioles",
                 "home_team": "New York Mets", "market": "totals",
                 "book": f"book{i}", "total": "8.5", "over_price": -110,
                 "under_price": -110} for i in range(6)]
        payload = card_mod.card_for_date(
            entries, [], date="2026-09-14", now=NOW, multibook_rows=rows,
            prefer_frozen=False, prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        self.assertEqual([], payload["total_picks"])
        self.assertEqual(card_mod._TOTALS_PAUSED, payload["total_reason"])


class LabelBands(unittest.TestCase):
    def test_strong_lean_slight_read_off_the_market_number(self):
        strong = daily_card._total_label(0.65)
        lean = daily_card._total_label(0.58)
        slight = daily_card._total_label(0.51)
        self.assertEqual(daily_card.LABEL_STRONG, strong)
        self.assertEqual(daily_card.LABEL_LEAN, lean)
        self.assertEqual(daily_card.LABEL_SLIGHT, slight)
        self.assertFalse(hasattr(daily_card, "LABEL_SPLIT_TOTAL"),
                         "a total pick has no SPLIT label -- disagreement "
                         "disqualifies it before it ever reaches a label")


class BetAndWhySentences(unittest.TestCase):
    def test_the_bet_sentence(self):
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.5: 0.80})}
        total_rows = {game["game_id"]: _detail(
            line=8.5, over_p=0.60, under_p=0.40, over_price=-110)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        payload = daily_card.select_totals(candidates)
        self.assertEqual("Take Over 8.5 runs at -110", payload["picks"][0]["bet"])

    def test_the_why_sentence_carries_both_numbers_and_the_break_even(self):
        game = _game()
        model_lines = {game["game_id"]: _model_line({8.5: 0.80})}
        total_rows = {game["game_id"]: _detail(
            line=8.5, over_p=0.60, under_p=0.40, over_price=-110)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        pick = daily_card.select_totals(candidates)["picks"][0]
        (sentence,) = pick["why"]
        self.assertIn("Padres", sentence)
        self.assertIn("Rockies", sentence)
        self.assertIn("60%", sentence)
        self.assertIn("80%", sentence)
        self.assertIn("-110", sentence)
        self.assertIn("52%", sentence)   # -110's own break-even


class LedgerPublish(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def _total_pick(self, price=-110, first_pitch_utc=FUTURE, line=8.5,
                    side="over", game_pk=744001):
        game = _game(game_pk=game_pk, first_pitch=first_pitch_utc)
        model_lines = {game["game_id"]: _model_line({line: 0.80})}
        total_rows = {game["game_id"]: _detail(
            line=line, over_p=0.60, under_p=0.40, over_price=price,
            under_price=price)}
        candidates = daily_card.build_total_candidates(
            [game], model_lines=model_lines, total_rows=total_rows)
        picks = daily_card.select_totals(candidates)["picks"]
        return picks

    def _card(self, total_picks):
        return {
            "date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
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
                "first_pitch_utc": FUTURE, "observed_utc": "2026-09-14T16:00:00Z",
                "model": {},
            }],
            "total_picks": total_picks,
        }

    def test_an_open_total_pick_is_replaced_on_republish(self):
        first = card_ledger.publish(
            self._card(self._total_pick(price=-110)),
            now=NOW.isoformat(), path=self.path)
        self.assertEqual(-110, first["total_picks"][0]["price"])
        self.assertFalse(first["total_picks"][0]["locked"])

        second = card_ledger.publish(
            self._card(self._total_pick(price=-130)),
            now=NOW.isoformat(), path=self.path)
        self.assertFalse(second["already_published"])
        self.assertEqual(-130, second["total_picks"][0]["price"])

    def test_a_locked_total_pick_carries_forward_untouched(self):
        locking_now = datetime(2026, 9, 14, 16, 30, tzinfo=timezone.utc)
        first = card_ledger.publish(
            self._card(self._total_pick(price=-110, first_pitch_utc=SOON)),
            now=locking_now.isoformat(), path=self.path)
        self.assertTrue(first["total_picks"][0]["locked"])
        self.assertEqual(-110, first["total_picks"][0]["price"])

        later = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
        second = card_ledger.publish(
            self._card(self._total_pick(price=-999, first_pitch_utc=SOON)),
            now=later.isoformat(), path=self.path)
        self.assertEqual(-110, second["total_picks"][0]["price"],
                         "a locked total pick was rewritten")

    def test_a_locked_total_pick_blocks_a_fresh_pick_on_a_different_line_or_side(self):
        """Opus checker problem 2, fixed 2026-09-14. The key used to be
        `(game_pk, line, side)`; a board move after a pick locked -- Over
        8.5 locked, the board moving to 9.0 and flipping to Under -- did not
        match that key, so `_lock_and_merge` carried the locked pick forward
        AND appended the fresh one: one game with two graded total bets on
        opposite sides. `game_pk` alone as the key means the fresh candidate
        can never join the locked one; it is replaced by it."""
        locking_now = datetime(2026, 9, 14, 16, 30, tzinfo=timezone.utc)
        first = card_ledger.publish(
            self._card(self._total_pick(price=-110, line=8.5, side="over",
                                        first_pitch_utc=SOON)),
            now=locking_now.isoformat(), path=self.path)
        self.assertTrue(first["total_picks"][0]["locked"])
        self.assertEqual(8.5, first["total_picks"][0]["line"])
        self.assertEqual("over", first["total_picks"][0]["side"])

        # The board has since moved AND flipped sides -- a fresh candidate
        # for the SAME game, a DIFFERENT bet.
        later = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
        flipped = self._total_pick(price=-120, line=9.0, side="under",
                                   first_pitch_utc=SOON)
        second = card_ledger.publish(
            self._card(flipped), now=later.isoformat(), path=self.path)

        self.assertEqual(
            1, len(second["total_picks"]),
            "the locked Over 8.5 and a fresh Under 9.0 on the same game "
            "both survived -- one game graded on two opposite bets")
        self.assertEqual(8.5, second["total_picks"][0]["line"],
                         "the LOCKED pick must be the one carried forward, "
                         "not silently replaced by the fresh candidate")
        self.assertEqual("over", second["total_picks"][0]["side"])
        self.assertEqual(-110, second["total_picks"][0]["price"])

    def test_republishing_the_same_total_picks_writes_nothing(self):
        card = self._card(self._total_pick())
        first = card_ledger.publish(card, now=NOW.isoformat(), path=self.path)
        second = card_ledger.publish(card, now=NOW.isoformat(), path=self.path)
        self.assertTrue(second["already_published"])
        self.assertEqual(first["row_hash"], second["row_hash"])

    def test_a_card_with_no_total_picks_still_publishes(self):
        row = card_ledger.publish(self._card([]), path=self.path)
        self.assertEqual([], row["total_picks"])
        self.assertFalse(row["already_published"])


class LedgerSettle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def _pick(self, game_pk, line=8.5, side="over", price=-110):
        return {
            "rank": 1, "label": "LEAN", "bet": "x", "why": [],
            "line": line, "side": side, "price": price, "book": "dk",
            "books": 8, "market_probability": 0.6, "model_probability": 0.7,
            "game_id": f"g{game_pk}", "game_pk": game_pk, "event_id": "e1",
            "away_team": "SD", "home_team": "COL",
            "first_pitch_utc": FUTURE, "observed_utc": "x",
        }

    def _publish(self, total_picks):
        card = {
            "date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
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
            "total_picks": total_picks,
        }
        return card_ledger.publish(card, path=self.path)

    def test_win_loss_push_void_from_the_results_map(self):
        over_win = self._pick(2001, line=8.5, side="over")     # 5+6=11 > 8.5
        over_loss = self._pick(2002, line=8.5, side="over")    # 2+3=5 < 8.5
        under_push = self._pick(2003, line=9.0, side="under")  # 4+5=9 == 9.0
        void_pick = self._pick(2004, line=8.5, side="over")    # no result

        self._publish([over_win, over_loss, under_push, void_pick])

        row = card_ledger.settle(
            "2026-09-14", {
                2001: {"away_score": 5, "home_score": 6},
                2002: {"away_score": 2, "home_score": 3},
                2003: {"away_score": 4, "home_score": 5},
                # 2004 has no entry at all.
            }, path=self.path)

        by_game = {g["game_pk"]: g for g in row["total_picks"]}
        self.assertEqual(card_ledger.RESULT_WIN, by_game[2001]["result"])
        self.assertEqual(card_ledger.RESULT_LOSS, by_game[2002]["result"])
        self.assertEqual(card_ledger.RESULT_PUSH, by_game[2003]["result"])
        self.assertEqual(card_ledger.RESULT_VOID, by_game[2004]["result"])
        self.assertEqual(1, row["total_wins"])
        self.assertEqual(1, row["total_losses"])
        self.assertEqual(1, row["total_pushes"])
        self.assertEqual(1, row["total_voids"])
        self.assertAlmostEqual(
            0.9091, by_game[2001]["profit_units"], places=3)
        self.assertEqual(-1.0, by_game[2002]["profit_units"])

    def test_an_under_pick_wins_when_the_total_stays_below_the_line(self):
        under_win = self._pick(3001, line=8.5, side="under")
        self._publish([under_win])
        row = card_ledger.settle(
            "2026-09-14", {3001: {"away_score": 2, "home_score": 2}},
            path=self.path)
        self.assertEqual(card_ledger.RESULT_WIN, row["total_picks"][0]["result"])

    def test_settling_with_no_results_voids_every_total_pick_not_a_crash(self):
        pick = self._pick(4001)
        self._publish([pick])
        row = card_ledger.settle("2026-09-14", {}, path=self.path)
        self.assertEqual(1, row["total_voids"])
        self.assertEqual(0, row["total_wins"])

    def test_the_published_total_picks_are_never_rewritten_by_settle(self):
        pick = self._pick(5001, price=-110)
        published = self._publish([pick])
        card_ledger.settle(
            "2026-09-14", {5001: {"away_score": 5, "home_score": 6}},
            path=self.path)
        again = card_ledger.published_row("2026-09-14", path=self.path)
        self.assertEqual(published["row_hash"], again["row_hash"])
        self.assertEqual(-110, again["total_picks"][0]["price"])


class RecordByKind(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def test_the_record_splits_total_picks_apart_from_game_and_prop(self):
        card = {
            "date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
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
            "total_picks": [{
                "rank": 1, "label": "LEAN", "bet": "x", "why": [],
                "line": 8.5, "side": "over", "price": -110, "book": "dk",
                "books": 8, "market_probability": 0.6, "model_probability": 0.7,
                "game_id": "g1", "game_pk": 1001, "event_id": "e0",
                "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "x",
            }],
        }
        card_ledger.publish(card, path=self.path)
        card_ledger.settle(
            "2026-09-14",
            # NYY (home, the game pick) wins 2-1; total = 3, well under 8.5,
            # so the Over total pick loses.
            {1001: {"away_score": 1, "home_score": 2}},
            path=self.path)

        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["by_kind"]["game"]["wins"])
        self.assertEqual(0, rec["by_kind"]["total"]["wins"])
        self.assertEqual(1, rec["by_kind"]["total"]["losses"])
        self.assertEqual(0, rec["by_kind"]["prop"]["wins"])
        self.assertEqual(0, rec["by_kind"]["prop"]["losses"])
        # The pooled top-level totals stay the GAME picks alone.
        self.assertEqual(rec["wins"], rec["by_kind"]["game"]["wins"])


class History(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def test_history_joins_total_picks_by_game_pk_line_and_side(self):
        card = {
            "date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
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
            "total_picks": [{
                "rank": 1, "label": "LEAN", "bet": "Take Over 8.5 runs at -110",
                "why": [], "line": 8.5, "side": "over", "price": -110,
                "book": "dk", "books": 9, "market_probability": 0.6,
                "model_probability": 0.7, "game_id": "g1", "game_pk": 1001,
                "event_id": "e0", "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": FUTURE, "observed_utc": "x",
            }],
        }
        card_ledger.publish(card, path=self.path)
        card_ledger.settle(
            "2026-09-14", {1001: {"away_score": 5, "home_score": 6}},  # OVER wins
            path=self.path)

        hist = card_ledger.history(path=self.path)
        day = hist["days"][0]
        self.assertEqual(1, len(day["total_picks"]))
        joined = day["total_picks"][0]
        self.assertEqual(card_ledger.RESULT_WIN, joined["result"])
        # Fields joined back from the PUBLISHED row, not the settled one.
        self.assertEqual("dk", joined["book"])
        self.assertEqual(9, joined["books"])
        self.assertEqual("COL", joined["away_team"])
        self.assertEqual("NYY", joined["home_team"])


class FrozenCardServesTotals(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")
        self._real = card_ledger.CARD_STORE
        card_ledger.CARD_STORE = self.path
        self.addCleanup(setattr, card_ledger, "CARD_STORE", self._real)

    def _base_card(self, **total_picks_kwarg):
        card = {
            "date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
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
        card.update(total_picks_kwarg)
        return card

    def _pick(self, game_pk, market_probability):
        return {
            "rank": 1, "label": "LEAN", "bet": "x", "why": [],
            "line": 8.5, "side": "over", "price": -110, "book": "dk",
            "books": 8, "market_probability": market_probability,
            "model_probability": 0.7, "game_id": f"g{game_pk}",
            "game_pk": game_pk, "event_id": "e1", "away_team": "SD",
            "home_team": "COL", "first_pitch_utc": FUTURE, "observed_utc": "x",
        }

    def test_frozen_card_stamps_position_by_market_probability(self):
        from src.report import card as card_mod

        lower = self._pick(2001, 0.55)
        higher = self._pick(2002, 0.70)
        # Stored out of order on purpose -- `position` must be recomputed.
        card_ledger.publish(self._base_card(total_picks=[lower, higher]),
                            path=self.path)

        served = card_mod.frozen_card("2026-09-14")
        self.assertEqual(2, len(served["total_picks"]))
        self.assertEqual(2002, served["total_picks"][0]["game_pk"])
        self.assertEqual(1, served["total_picks"][0]["position"])
        self.assertEqual(2001, served["total_picks"][1]["game_pk"])
        self.assertEqual(2, served["total_picks"][1]["position"])
        self.assertIsNone(served["total_reason"])

    def test_an_old_row_with_no_total_picks_serves_an_empty_list(self):
        """Same checker-problem-4 shape as props: a MISSING `total_picks`
        key (a row published before this feature) must not read as a
        verdict."""
        from src.ledger.chain import HashChainLedger
        from src.report import card as card_mod

        legacy_payload = dict(self._base_card())
        legacy_payload.update({
            "kind": card_ledger.KIND_PUBLISHED,
            "published_utc": "2026-09-01T20:00:00Z",
            "n_picks": 1, "n_filled": 0, "n_locked": 0,
            # No "total_picks" key at all.
        })
        HashChainLedger(self.path).append(legacy_payload)

        served = card_mod.frozen_card("2026-09-14")
        self.assertEqual([], served["total_picks"])
        self.assertEqual(card_mod._TOTAL_NOT_PART_OF_CARD, served["total_reason"])
        self.assertNotIn("cleared", served["total_reason"].lower())

    def test_a_row_that_considered_totals_and_selected_none_says_so_differently(self):
        from src.report import card as card_mod

        card_ledger.publish(self._base_card(total_picks=[]), path=self.path)
        served = card_mod.frozen_card("2026-09-14")
        self.assertEqual([], served["total_picks"])
        self.assertEqual(card_mod._TOTAL_NONE_SELECTED_FROZEN,
                         served["total_reason"])
        self.assertNotEqual(card_mod._TOTAL_NOT_PART_OF_CARD,
                            served["total_reason"])
        self.assertNotIn("bar", served["total_reason"].lower())


class CardForDateWiresTotalsIntoTheModel(unittest.TestCase):
    """Proof of the fix the scout found: `strength.model_line` must be
    called with `totals=[this game's own consensus line]`, not left to its
    default of no totals at all (which leaves `p_over` empty and makes a
    total pick impossible regardless of anything else in this file)."""

    def _entry(self, game_pk, away, home, first_pitch):
        return {"dossier": {
            "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                     "start_time_utc": first_pitch, "game_number": 1},
            "sections": {
                "teams": {
                    "away_runs_scored_pg": 4.6, "away_runs_allowed_pg": 4.2,
                    "away_games_played": 140, "away_wins": 75, "away_losses": 65,
                    "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.1,
                    "home_games_played": 140, "home_wins": 80, "home_losses": 60,
                },
                "starters": {},
            },
        }}

    def test_model_line_is_called_with_the_boards_own_total(self):
        from src.report import card as card_mod

        entries = [self._entry(744001, "SD", "COL", FUTURE)]
        multibook_rows = []
        # Six books, all quoting the SAME total (8.5) -- above prices.MIN_BOOKS.
        for i in range(6):
            multibook_rows.append({
                "observed_utc": "2026-09-14T15:30:00Z",
                "event_id": "e1", "commence_time": FUTURE,
                "away_team": "San Diego Padres", "home_team": "Colorado Rockies",
                "market": "totals", "book": f"book{i}",
                "total": "8.5", "over_price": -115, "under_price": -105,
            })

        calls = []
        original = card_mod.strength.model_line

        def spy(features, **kwargs):
            calls.append(kwargs.get("totals"))
            return original(features, **kwargs)

        card_mod.strength.model_line = spy
        try:
            payload = card_mod.card_for_date(
                entries, [], date="2026-09-14", now=NOW,
                multibook_rows=multibook_rows, prefer_frozen=False,
                prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        finally:
            card_mod.strength.model_line = original

        self.assertEqual(1, len(calls))
        self.assertEqual([8.5], calls[0],
                         "the game's own consensus total line was not "
                         "passed into model_line's totals= argument")
        self.assertIn("total_picks", payload)
        self.assertIn("all_bets", payload)

    def test_a_game_with_no_totals_board_still_builds(self):
        """No totals posted for this game -- `totals=None` reaches
        `model_line` and the game still prices a moneyline; nothing about
        the totals wiring may take the rest of the card down with it."""
        from src.report import card as card_mod

        entries = [self._entry(744002, "SD", "COL", FUTURE)]
        payload = card_mod.card_for_date(
            entries, [], date="2026-09-14", now=NOW, multibook_rows=[],
            prefer_frozen=False,
            prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        self.assertEqual([], payload["total_picks"])
        self.assertIsNotNone(payload["total_reason"])


if __name__ == "__main__":
    unittest.main()
