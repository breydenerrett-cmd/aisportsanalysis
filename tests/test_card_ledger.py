"""The card's receipts: frozen on publication, graded without re-scoring.

This file guards the two properties that make a public betting record worth
anything, and both of them are properties about what CANNOT happen:

  * a published card cannot be rewritten after the fact
  * a settled result cannot change the published row it grades

Every test runs against a temporary ledger path. None of them touch
`evidence/cards_v1.jsonl` -- a test that appends to the real chain would be
tampering with the evidence it exists to protect.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger


def _card(date="2026-09-10", picks=None):
    return {
        "date": date,
        "rule": card_ledger.KIND_PUBLISHED,
        "basis": "basis sentence",
        "disclaimer": "disclaimer sentence",
        "model_id": "run_expectancy_poisson_v1",
        "calibrated": True,
        "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
        "filled": 0,
        "games_on_slate": 5,
        "picks": picks if picks is not None else [_pick()],
    }


def _pick(rank=1, market="moneyline", side="home", price=-150, line=None,
          game_pk=1001, label="STRONG"):
    return {
        "rank": rank, "label": label, "bet": "Take Yankees to win at -150",
        "why": ["because"], "market": market, "line": line, "side": side,
        "team": "NYY", "team_name": "Yankees", "opponent_name": "Rockies",
        "price": price, "book": "draftkings", "books": 8,
        "confidence": 0.74, "market_probability": 0.74,
        "model_probability": 0.64, "game_id": "COL-NYY-2026-09-10-1",
        "game_pk": game_pk, "event_id": "e1", "away_team": "COL",
        "home_team": "NYY", "first_pitch_utc": "2026-09-10T23:05:00Z",
        "observed_utc": "2026-09-10T18:00:00Z", "model": {},
    }


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")


class PublishFreezes(LedgerCase):
    def test_a_card_publishes_once_and_only_once(self):
        first = card_ledger.publish(_card(), path=self.path)
        self.assertFalse(first["already_published"])

        # A DIFFERENT card for the same date. This is the case that matters:
        # the afternoon pass retrying, or someone re-running the loop after
        # the lines moved. The frozen row has to win.
        moved = _card(picks=[_pick(price=+250, label="SPLIT")])
        second = card_ledger.publish(moved, path=self.path)
        self.assertTrue(second["already_published"])
        self.assertEqual(first["row_hash"], second["row_hash"])
        self.assertEqual(-150, second["picks"][0]["price"])

        rows = [r for r in card_ledger._ledger(self.path).read()
                if r["kind"] == card_ledger.KIND_PUBLISHED]
        self.assertEqual(1, len(rows), "a second row was written for one date")

    def test_an_empty_card_is_refused_rather_than_recorded(self):
        """An empty card is a real state with its own reason, and it is not
        evidence. Writing it would put a row in the chain that claims
        nothing and then has to be excluded from every count."""
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.publish(_card(picks=[]), path=self.path)

    def test_the_chain_verifies(self):
        card_ledger.publish(_card(date="2026-09-10"), path=self.path)
        card_ledger.publish(_card(date="2026-09-11"), path=self.path)
        result = card_ledger.verify(path=self.path)
        self.assertTrue(getattr(result, "ok", False), result)


class GradingIsHonest(LedgerCase):
    def test_a_moneyline_pick_on_the_winner_wins(self):
        grade = card_ledger.grade_pick(
            _pick(side="home", price=-150),
            {"away_score": 2, "home_score": 5})
        self.assertEqual(card_ledger.RESULT_WIN, grade["result"])
        self.assertAlmostEqual(0.6667, grade["profit_units"], places=3)

    def test_a_moneyline_pick_on_the_loser_loses_one_unit(self):
        grade = card_ledger.grade_pick(
            _pick(side="home", price=-150),
            {"away_score": 5, "home_score": 2})
        self.assertEqual(card_ledger.RESULT_LOSS, grade["result"])
        self.assertEqual(-1.0, grade["profit_units"])

    def test_a_favourite_run_line_needs_two(self):
        """-1.5 covers on a two-run win and not on a one-run win. Getting
        this backwards would grade roughly a fifth of all games wrong."""
        laying = _pick(market="run_line", side="home", line=-1.5, price=-149)
        self.assertEqual(
            card_ledger.RESULT_WIN,
            card_ledger.grade_pick(laying, {"away_score": 2, "home_score": 4})["result"])
        self.assertEqual(
            card_ledger.RESULT_LOSS,
            card_ledger.grade_pick(laying, {"away_score": 3, "home_score": 4})["result"])

    def test_an_underdog_run_line_covers_a_one_run_loss(self):
        taking = _pick(market="run_line", side="away", line=1.5, price=-130)
        self.assertEqual(
            card_ledger.RESULT_WIN,
            card_ledger.grade_pick(taking, {"away_score": 3, "home_score": 4})["result"])
        self.assertEqual(
            card_ledger.RESULT_LOSS,
            card_ledger.grade_pick(taking, {"away_score": 2, "home_score": 4})["result"])
        # Winning outright covers too.
        self.assertEqual(
            card_ledger.RESULT_WIN,
            card_ledger.grade_pick(taking, {"away_score": 6, "home_score": 1})["result"])

    def test_a_game_with_no_score_is_void_and_never_a_loss(self):
        """A postponed slate graded as losses makes a public record wrong in
        the one direction nobody would ever check."""
        grade = card_ledger.grade_pick(_pick(), {"away_score": None,
                                                 "home_score": None})
        self.assertEqual(card_ledger.RESULT_VOID, grade["result"])
        self.assertEqual(0.0, grade["profit_units"])

    def test_an_unusable_price_is_void_not_a_silent_zero(self):
        grade = card_ledger.grade_pick(_pick(price=None),
                                       {"away_score": 1, "home_score": 4})
        self.assertEqual(card_ledger.RESULT_VOID, grade["result"])


class SettleNeverRewrites(LedgerCase):
    def test_settle_appends_and_leaves_the_published_row_alone(self):
        published = card_ledger.publish(
            _card(picks=[_pick(rank=1, game_pk=1001, price=-150),
                         _pick(rank=2, game_pk=1002, price=+120,
                               side="away", label="LEAN")]),
            path=self.path)

        row = card_ledger.settle(
            "2026-09-10",
            {1001: {"away_score": 1, "home_score": 4},   # home wins -> pick 1 WIN
             1002: {"away_score": 1, "home_score": 4}},  # away loses -> pick 2 LOSS
            path=self.path)

        self.assertEqual(1, row["wins"])
        self.assertEqual(1, row["losses"])
        self.assertEqual(2, row["n_staked"])
        self.assertEqual(published["row_hash"], row["published_row_hash"])

        # The published row is byte-identical to what it was.
        again = card_ledger.published_row("2026-09-10", path=self.path)
        self.assertEqual(published["row_hash"], again["row_hash"])
        self.assertEqual(-150, again["picks"][0]["price"])

        self.assertTrue(getattr(card_ledger.verify(path=self.path), "ok", False))

    def test_settling_twice_is_a_no_op(self):
        card_ledger.publish(_card(), path=self.path)
        results = {1001: {"away_score": 1, "home_score": 4}}
        self.assertIsNotNone(card_ledger.settle("2026-09-10", results, path=self.path))
        self.assertIsNone(card_ledger.settle("2026-09-10", results, path=self.path))

    def test_settling_a_date_that_was_never_published_does_nothing(self):
        self.assertIsNone(card_ledger.settle("2026-09-10", {}, path=self.path))

    def test_voids_are_excluded_from_the_return_but_reported(self):
        card_ledger.publish(
            _card(picks=[_pick(rank=1, game_pk=1001),
                         _pick(rank=2, game_pk=1002)]),
            path=self.path)
        row = card_ledger.settle(
            "2026-09-10",
            {1001: {"away_score": 1, "home_score": 4},
             1002: {}},  # postponed
            path=self.path)
        self.assertEqual(1, row["voids"])
        self.assertEqual(1, row["n_staked"])
        self.assertEqual(1, row["wins"])


class TheRunningRecord(LedgerCase):
    def test_the_record_pools_settled_days_and_splits_by_label(self):
        card_ledger.publish(
            _card(date="2026-09-10",
                  picks=[_pick(rank=1, game_pk=1, label="STRONG", price=-150),
                         _pick(rank=2, game_pk=2, label="SPLIT", price=+100)]),
            path=self.path)
        card_ledger.settle("2026-09-10",
                           {1: {"away_score": 1, "home_score": 4},
                            2: {"away_score": 6, "home_score": 4}},
                           path=self.path)

        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["days"])
        self.assertEqual(2, rec["n_staked"])
        self.assertEqual(1, rec["wins"])
        self.assertEqual(1, rec["losses"])
        self.assertEqual(1, rec["by_label"]["STRONG"]["wins"])
        self.assertEqual(1, rec["by_label"]["SPLIT"]["losses"])

    def test_an_unsettled_record_reports_nothing_rather_than_zero(self):
        card_ledger.publish(_card(), path=self.path)
        rec = card_ledger.record(path=self.path)
        self.assertEqual(0, rec["days"])
        self.assertIsNone(rec["win_rate"])
        self.assertIsNone(rec["roi_pct"])


class ThePageServesTheFrozenCard(unittest.TestCase):
    """The property that makes the receipts mean anything.

    `card_for_date` rebuilds from live prices. A page that always rebuilt
    would drift away from the ledger row as books move -- so the record page
    would be receipts for a card nobody was ever shown. Once a date is
    published, the page serves the frozen row and says so.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")
        # `frozen_card` reads the module-level default, so point that at the
        # temp chain for the duration. Restored by addCleanup either way.
        self._real = card_ledger.CARD_STORE
        card_ledger.CARD_STORE = self.path
        self.addCleanup(setattr, card_ledger, "CARD_STORE", self._real)

    def test_frozen_card_returns_none_before_anything_is_published(self):
        from src.report import card as card_mod
        self.assertIsNone(card_mod.frozen_card("2026-09-10"))

    def test_the_frozen_row_is_served_verbatim_once_published(self):
        from src.report import card as card_mod

        card_ledger.publish(_card(picks=[_pick(price=-150)]), path=self.path)
        served = card_mod.frozen_card("2026-09-10")
        self.assertTrue(served["frozen"])
        self.assertIsNotNone(served["frozen_at"])
        self.assertEqual(-150, served["picks"][0]["price"])

    def test_the_frozen_payload_carries_every_key_the_live_one_does(self):
        """A payload whose keys vary by branch is a trap for any consumer:
        the renderer cannot tell "absent" from "zero" and prints one for the
        other."""
        from src.report import card as card_mod

        card_ledger.publish(_card(), path=self.path)
        served = card_mod.frozen_card("2026-09-10")
        for key in ("picks", "filled", "considered", "agreed", "split",
                    "rule", "basis", "disclaimer", "min_picks", "max_picks",
                    "calibrated", "calibration", "model_id",
                    "games_on_slate", "games_started", "games_open",
                    "frozen", "frozen_at"):
            self.assertIn(key, served, f"the frozen payload is missing {key}")

    def test_unknown_counts_are_none_not_zero(self):
        from src.report import card as card_mod

        card_ledger.publish(_card(), path=self.path)
        served = card_mod.frozen_card("2026-09-10")
        self.assertIsNone(served["games_open"])
        self.assertIsNone(served["agreed"])

    def test_a_live_build_is_marked_not_frozen(self):
        from src.report import card as card_mod

        built = card_mod.card_for_date([], [], date="2026-09-10")
        self.assertFalse(built["frozen"])
        self.assertIsNone(built["frozen_at"])
        self.assertIn("reason", built)


if __name__ == "__main__":
    unittest.main()
