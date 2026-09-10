"""Tests for src.report.daily_record (Task C1: FROZEN PREGAME RECORD).

Hermetic: the one real store this suite writes through is a paper account's
own hash-chained ledger (`src.accounts.paper.PaperAccount`, same as
tests/test_paper_performance.py's own `_HermeticBase`) -- every other input
(`decisions`, `wagers`, `boxscores`, `index`) is a small fixture list/dict
injected directly, never touching `evidence/`, `data/paper_accounts/`, or
`data/processed/` in the real checkout. `gamekey.load_map()` and this
module's own event_game_map fallback DO still read the real
`data/processed/event_game_map.jsonl` (there is no injectable override for
either, by this task's own function signatures -- see
`src/report/daily_record.py`'s docstring), but every event_id used below is
a fixture-only string (`ev-ath`, `ev-noboard`, `ev-pending`) that cannot
collide with a real event_id, so that fallback is exercised as a no-op
here, exactly as `src.report.engine_bridge`'s own tests already rely on for
`event_index()`.
"""

from __future__ import annotations

import ast
import re
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.accounts import paper as paper_mod
from src.accounts.paper import PaperAccount, PaperBet
from src.board.settle import GameResult
from src.core import odds as odds_math
from src.analysis import priceverdict
from src.report import daily_record as dr

FWD = "abc123deadbeef01"          # no prefix -> FORWARD_TEST
CTRL = "trivial_test_control"     # trivial_ prefix -> CONTROL
MKT = "market_derived_consensus_h2h_home"  # -> MARKET_REFERENCE
ORPHAN = "orphan_system_id"       # staked, but its DecisionRecord is "missing"


# ---------------------------------------------------------------------------
# Shared hermetic fixture
# ---------------------------------------------------------------------------

class _HermeticBase(unittest.TestCase):
    """One settled game (TOR @ ATH, deliberately raw/uncanonicalised in the
    fixture index -- see the ATH/OAK test below), one "no board" game with
    a single unstaked market_unavailable decision, and one later, still-
    pending game -- exactly the shapes the task's own deliverable list
    names: frozen pass-through, settlement join by bet_id, pending vs
    unsettled, a game with no recommendations, ATH/OAK canonical keying.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.accounts_dir = Path(self._tmpdir.name) / "paper_accounts"
        self.accounts_dir.mkdir(parents=True)

        patcher = mock.patch.object(
            paper_mod, "default_ledger_path",
            side_effect=lambda sid: self.accounts_dir / f"{sid}.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)

        # Settle bet-a1 (FWD, home) as a WIN and bet-a2 (CTRL, away) as a
        # LOSS on the same real game result -- home_runs=5 > away_runs=2.
        # bet-orphan and bet-pending are DELIBERATELY never settled.
        result = GameResult(home_runs=5, away_runs=2)
        fwd_account = PaperAccount(system_id=FWD)
        fwd_account.settle_and_record(
            PaperBet(bet_id="bet-a1", system_id=FWD, market_key="h2h",
                     selection_id="home", side="home", line=None,
                     price_american=150, settlement_rule="h2h"),
            result, day="2026-09-08")
        ctrl_account = PaperAccount(system_id=CTRL)
        ctrl_account.settle_and_record(
            PaperBet(bet_id="bet-a2", system_id=CTRL, market_key="h2h",
                     selection_id="away", side="away", line=None,
                     price_american=-110, settlement_rule="h2h"),
            result, day="2026-09-08")

        self.index = {
            "ev-ath": {
                "away_abbrev": "TOR", "home_abbrev": "ATH",
                "away_name": "Toronto Blue Jays", "home_name": "Athletics",
                "commence_time": "2026-09-08T23:07:00Z", "date": "2026-09-08",
            },
            "ev-noboard": {
                "away_abbrev": "BOS", "home_abbrev": "NYY",
                "away_name": "Boston Red Sox", "home_name": "New York Yankees",
                "commence_time": "2026-09-08T23:05:00Z", "date": "2026-09-08",
            },
            "ev-pending": {
                "away_abbrev": "SEA", "home_abbrev": "LAA",
                "away_name": "Seattle Mariners", "home_name": "Los Angeles Angels",
                "commence_time": "2026-09-09T23:05:00Z", "date": "2026-09-09",
            },
        }

        self.decisions = [
            {  # D1: staked, settles WIN
                "event_id": "ev-ath", "system_id": FWD, "market_key": "h2h",
                "selection_id": "home", "line": None, "price_american": 150,
                "decision_utc": "2026-09-08T20:00:00+00:00", "verdict": "play",
                "consensus_fair": 0.45, "books_at_decision": 8,
                "known_at_grade": "B", "p_model_provenance": "none",
                "thesis": "genome thesis text",
                "counterarguments": [{"severity": "MAJOR", "cause": "c1", "detail": "d1"}],
                "game_pk": 900001,
            },
            {  # D2: staked, settles LOSS, CONTROL -- thesis must never surface
                "event_id": "ev-ath", "system_id": CTRL, "market_key": "h2h",
                "selection_id": "away", "line": None, "price_american": -110,
                "decision_utc": "2026-09-08T20:00:01+00:00", "verdict": "play",
                "consensus_fair": 0.55, "books_at_decision": 8,
                "known_at_grade": "B", "p_model_provenance": "placeholder",
                "thesis": "must never appear -- CONTROL never shows a thesis",
                "counterarguments": [], "game_pk": 900001,
            },
            {  # D3: never staked -- MARKET_REFERENCE, no_play
                "event_id": "ev-ath", "system_id": MKT, "market_key": "h2h",
                "selection_id": "home", "line": None, "price_american": 130,
                "decision_utc": "2026-09-08T20:00:02+00:00", "verdict": "no_play",
                "consensus_fair": 0.48, "books_at_decision": 8,
                "known_at_grade": "C", "p_model_provenance": "market_derived",
                "thesis": "must never appear -- MARKET_REFERENCE never shows one",
                "counterarguments": [], "game_pk": 900001,
            },
            {  # D4: a game with no board at all -- never staked
                "event_id": "ev-noboard", "system_id": FWD, "market_key": "h2h",
                "selection_id": None, "line": None, "price_american": None,
                "decision_utc": "2026-09-08T20:05:00+00:00",
                "verdict": "market_unavailable", "consensus_fair": None,
                "books_at_decision": None, "known_at_grade": "D",
                "p_model_provenance": "none", "thesis": None,
                "counterarguments": [], "game_pk": None,
            },
            {  # D6: staked, still pending (dated after settled_through)
                "event_id": "ev-pending", "system_id": FWD, "market_key": "totals",
                "selection_id": "over", "line": "8.5", "price_american": -105,
                "decision_utc": "2026-09-09T20:00:00+00:00", "verdict": "play",
                "consensus_fair": 0.50, "books_at_decision": 10,
                "known_at_grade": "A", "p_model_provenance": "none",
                "thesis": "pending thesis text",
                "counterarguments": [], "game_pk": 900002,
            },
        ]

        self.wagers = [
            {"bet_id": "bet-a1", "date": "2026-09-08", "event_id": "ev-ath",
             "system_id": FWD, "market_key": "h2h", "selection_id": "home",
             "side": "home", "line": None, "price_american": 150,
             "decision_utc": "2026-09-08T20:00:00+00:00", "game_pk": 900001,
             "stake_units": 1.0},
            {"bet_id": "bet-a2", "date": "2026-09-08", "event_id": "ev-ath",
             "system_id": CTRL, "market_key": "h2h", "selection_id": "away",
             "side": "away", "line": None, "price_american": -110,
             "decision_utc": "2026-09-08T20:00:01+00:00", "game_pk": 900001,
             "stake_units": 1.0},
            {  # orphan: staked, but no matching DecisionRecord exists at all
             "bet_id": "bet-orphan", "date": "2026-09-08", "event_id": "ev-ath",
             "system_id": ORPHAN, "market_key": "h2h", "selection_id": "home",
             "side": "home", "line": None, "price_american": 120,
             "decision_utc": "2026-09-08T20:00:03+00:00", "game_pk": 900001,
             "stake_units": 1.0},
            {"bet_id": "bet-pending", "date": "2026-09-09", "event_id": "ev-pending",
             "system_id": FWD, "market_key": "totals", "selection_id": "over",
             "side": "over", "line": "8.5", "price_american": -105,
             "decision_utc": "2026-09-09T20:00:00+00:00", "game_pk": 900002,
             "stake_units": 1.0},
        ]

        self.boxscores = [
            {"type": "linescore", "game_pk": 900001,
             "innings": [{"num": 1, "home_runs": 5, "away_runs": 2}]},
            # 900002 (ev-pending) deliberately has NO linescore row.
        ]

    def _kwargs(self):
        return dict(decisions=self.decisions, wagers=self.wagers,
                   accounts_dir=self.accounts_dir, boxscores=self.boxscores,
                   index=self.index)


# ---------------------------------------------------------------------------
# day_record
# ---------------------------------------------------------------------------

class DayRecordShapeTests(_HermeticBase):
    def test_top_level_keys(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        for key in ("date", "games", "rollup", "freshness", "notes",
                   "stake_policy", "label", "basis"):
            self.assertIn(key, rec)
        self.assertEqual(rec["date"], "2026-09-08")
        self.assertEqual(rec["stake_policy"], "FLAT_1U")
        self.assertEqual(rec["label"], "FROZEN PREGAME RECORD")

    def test_two_games_on_the_date(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        self.assertEqual(len(rec["games"]), 2)

    def test_pending_game_excluded_from_an_earlier_date(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        matchups = {tuple(g["game_key"][:2]) for g in rec["games"]}
        self.assertNotIn(("SEA", "LAA"), matchups)


class AthOakCanonicalKeyingTests(_HermeticBase):
    def test_ath_canonicalises_to_oak(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "TOR")
        self.assertEqual(game["home_team"], "OAK")
        self.assertEqual(game["game_key"], ["TOR", "OAK", "2026-09-08"])


class FrozenValuesPassThroughTests(_HermeticBase):
    """D1's price/consensus/grade/thesis/counterarguments must reach the
    output byte-for-byte -- this module never recomputes any of them."""

    def _game(self, rec):
        return next(g for g in rec["games"] if g["away_team"] == "TOR")

    def _rec_for(self, rec, system_id):
        game = self._game(rec)
        return next(r for r in game["recommendations"] if r["system_id"] == system_id)

    def test_frozen_price_and_consensus_unchanged(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        d1 = self._rec_for(rec, FWD)
        self.assertEqual(d1["price_american"], 150)
        self.assertEqual(d1["consensus_fair"], 0.45)
        self.assertEqual(d1["books_at_decision"], 8)
        self.assertEqual(d1["known_at_grade"], "B")
        self.assertEqual(d1["p_model_provenance"], "none")
        self.assertEqual(d1["market_implied_probability"], 0.45)
        self.assertEqual(
            d1["counterarguments"],
            [{"severity": "MAJOR", "cause": "c1", "detail": "d1"}])

    def test_value_points_reuses_priceverdict_not_a_rederivation(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        d1 = self._rec_for(rec, FWD)
        expected_stated = round(odds_math.american_to_probability(150), 4)
        expected_vp = round((0.45 - expected_stated) * 100, 2)
        self.assertEqual(d1["stated_implied_probability"], expected_stated)
        self.assertEqual(d1["value_points"], expected_vp)

    def test_thesis_only_on_forward_test(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        d1 = self._rec_for(rec, FWD)
        d2 = self._rec_for(rec, CTRL)
        d3 = self._rec_for(rec, MKT)
        self.assertEqual(d1["thesis"], "genome thesis text")
        self.assertIsNone(d2["thesis"])
        self.assertIsNone(d3["thesis"])

    def test_stake_units_and_policy_always_flat_one(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        for game in rec["games"]:
            for r in game["recommendations"]:
                self.assertEqual(r["stake_units"], 1.0)
        self.assertEqual(rec["stake_policy"], "FLAT_1U")


class ValuePointsBookFloorTests(_HermeticBase):
    """A value comparison needs a real consensus behind it.

    Regression, 2026-09-07: `consensus_fair` on the run line was routinely a
    TWO-book average, and subtracting a price from it produced value_points
    like +14.01, which `strongest_pregame` then crowned as the day's
    best-supported play. Below `priceverdict.MIN_BOOKS` this must report no
    value at all, say why, and stay out of the ranking -- while leaving the
    frozen `consensus_fair` and `books_at_decision` untouched, because the
    record keeps whatever the engine wrote.
    """

    def _rec_for(self, rec, system_id):
        game = next(g for g in rec["games"] if g["away_team"] == "TOR")
        return next(r for r in game["recommendations"] if r["system_id"] == system_id)

    def _thin(self, books):
        decisions = [dict(d) for d in self.decisions]
        for d in decisions:
            d["books_at_decision"] = books
        return dr.day_record("2026-09-08",
                             **{**self._kwargs(), "decisions": decisions})

    def test_below_the_floor_reports_no_value_and_names_the_reason(self):
        rec = self._thin(2)
        d1 = self._rec_for(rec, FWD)
        self.assertIsNone(d1["value_points"])
        self.assertIn("2 book(s)", d1["value_points_reason"])
        self.assertIn(f"{priceverdict.MIN_BOOKS}-book floor",
                      d1["value_points_reason"])
        # the frozen inputs are still reported verbatim
        self.assertEqual(d1["books_at_decision"], 2)
        self.assertEqual(d1["consensus_fair"], 0.45)

    def test_at_the_floor_the_comparison_is_reported(self):
        rec = self._thin(priceverdict.MIN_BOOKS)
        d1 = self._rec_for(rec, FWD)
        self.assertIsNotNone(d1["value_points"])
        self.assertIsNone(d1["value_points_reason"])

    def test_a_thin_rec_can_never_be_the_strongest_pregame(self):
        rollup = self._thin(2)["rollup"]
        self.assertIsNone(rollup["strongest_pregame"])


class SettlementJoinByBetIdTests(_HermeticBase):
    def _game(self, rec):
        return next(g for g in rec["games"] if g["away_team"] == "TOR")

    def test_win_and_loss_join_real_profit(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = self._game(rec)
        d1 = next(r for r in game["recommendations"] if r["system_id"] == FWD)
        d2 = next(r for r in game["recommendations"] if r["system_id"] == CTRL)
        self.assertEqual(d1["settlement"],
                         {"status": "win", "profit_units": 1.5,
                          "settled_day": "2026-09-08"})
        self.assertEqual(d2["settlement"],
                         {"status": "loss", "profit_units": -1.0,
                          "settled_day": "2026-09-08"})

    def test_never_staked_is_unsettled_not_pending(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = self._game(rec)
        d3 = next(r for r in game["recommendations"] if r["system_id"] == MKT)
        self.assertFalse(d3["staked"])
        self.assertIsNone(d3["bet_id"])
        self.assertEqual(d3["settlement"]["status"], "unsettled")
        self.assertIsNone(d3["settlement"]["profit_units"])

    def test_staked_with_no_settlement_on_or_before_settled_through_is_unsettled(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = self._game(rec)
        orphan = next(r for r in game["recommendations"] if r["system_id"] == ORPHAN)
        self.assertTrue(orphan["staked"])
        self.assertEqual(orphan["bet_id"], "bet-orphan")
        self.assertEqual(orphan["settlement"]["status"], "unsettled")
        self.assertIsNone(orphan["settlement"]["profit_units"])

    def test_staked_after_settled_through_is_pending(self):
        rec = dr.day_record("2026-09-09", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "SEA")
        d6 = next(r for r in game["recommendations"] if r["system_id"] == FWD)
        self.assertEqual(d6["settlement"],
                         {"status": "pending", "profit_units": None,
                          "settled_day": None})

    def test_orphan_wager_with_no_decision_still_builds_a_rec(self):
        """A wager whose DecisionRecord is missing from the ledger still
        produces a recommendation, with every decision-only field null
        rather than guessed at."""
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = self._game(rec)
        orphan = next(r for r in game["recommendations"] if r["system_id"] == ORPHAN)
        self.assertEqual(orphan["verdict"], "play")
        self.assertIsNone(orphan["consensus_fair"])
        self.assertIsNone(orphan["market_implied_probability"])
        self.assertIsNone(orphan["value_points"])
        self.assertIsNone(orphan["known_at_grade"])
        self.assertIsNone(orphan["p_model_provenance"])
        self.assertIsNone(orphan["thesis"])
        self.assertEqual(orphan["counterarguments"], [])


class NoBoardGameTests(_HermeticBase):
    def test_game_with_no_recommendations_still_appears(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "BOS")
        self.assertEqual(game["n_staked"], 0)
        self.assertEqual(game["n_recommendations"], 1)
        d4 = game["recommendations"][0]
        self.assertEqual(d4["verdict"], "market_unavailable")
        self.assertIsNone(d4["price_american"])
        self.assertIsNone(d4["stated_implied_probability"])
        self.assertIsNone(d4["value_points"])
        self.assertFalse(d4["staked"])

    def test_final_score_null_with_a_reason_when_game_pk_never_resolves(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "BOS")
        self.assertIsNone(game["final_score"])
        self.assertIsInstance(game["final_score_reason"], str)
        self.assertTrue(game["final_score_reason"])

    def test_status_is_unknown_not_scheduled_when_date_already_settled_elsewhere(self):
        """2026-09-08 has ALREADY settled (settled_through) via the TOR@OAK
        game -- a same-date game whose boxscore this module still could not
        join is a genuine "unknown", never mislabelled "scheduled"."""
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "BOS")
        self.assertEqual(game["status"], "unknown")

    def test_status_is_scheduled_for_a_date_not_yet_settled(self):
        rec = dr.day_record("2026-09-09", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "SEA")
        self.assertEqual(game["status"], "scheduled")
        self.assertIsNone(game["final_score"])


class FinalScoreJoinTests(_HermeticBase):
    def test_final_score_resolves_and_status_is_final(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "TOR")
        self.assertEqual(game["final_score"], {"away": 2, "home": 5})
        self.assertIsNone(game["final_score_reason"])
        self.assertEqual(game["status"], "final")


class RecOrderingTests(_HermeticBase):
    def test_staked_first_then_by_value_points_desc_then_system_id(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "TOR")
        order = [r["system_id"] for r in game["recommendations"]]
        # D1 (value_points ~5.0) outranks D2 (~2.62); the orphan (no
        # value_points) still sorts ahead of D3 for being staked; D3
        # (never staked) is always last.
        self.assertEqual(order, [FWD, CTRL, ORPHAN, MKT])


class GameRollupTests(_HermeticBase):
    def test_game_level_record_and_settled_units_net(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        game = next(g for g in rec["games"] if g["away_team"] == "TOR")
        self.assertEqual(game["record"], {"wins": 1, "losses": 1, "pushes": 0, "pending": 0})
        self.assertAlmostEqual(game["settled_units_net"], 0.5, places=6)


class DayRecordRollupTests(_HermeticBase):
    def test_day_wide_rollup_matches_hand_computed_totals(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        r = rec["rollup"]
        self.assertEqual(r["n_games"], 2)
        self.assertEqual(r["n_recommendations"], 5)
        self.assertEqual(r["n_staked"], 3)
        self.assertEqual(r["wins"], 1)
        self.assertEqual(r["losses"], 1)
        self.assertEqual(r["pushes"], 0)
        # The orphan's "unsettled" bet is staked but neither pending nor
        # settled -- it must not inflate `pending` either.
        self.assertEqual(r["pending"], 0)
        self.assertEqual(r["units_staked"], 2.0)
        self.assertAlmostEqual(r["units_net"], 0.5, places=6)
        self.assertAlmostEqual(r["return_on_units"], 0.25, places=6)
        expected_avg = statistics.mean(
            [odds_math.american_to_decimal(150), odds_math.american_to_decimal(-110)])
        self.assertAlmostEqual(r["avg_odds_decimal"], expected_avg, places=6)

    def test_by_market_and_by_class(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        r = rec["rollup"]
        self.assertEqual(r["by_market"]["h2h"]["wins"], 1)
        self.assertEqual(r["by_market"]["h2h"]["losses"], 1)
        self.assertAlmostEqual(r["by_market"]["h2h"]["units_net"], 0.5, places=6)
        self.assertEqual(r["by_class"][dr.FORWARD_TEST]["wins"], 1)
        self.assertEqual(r["by_class"][dr.CONTROL]["losses"], 1)

    def test_best_worst_and_strongest_pregame(self):
        rec = dr.day_record("2026-09-08", **self._kwargs())
        r = rec["rollup"]
        self.assertEqual(r["best_bet"]["matchup"], "TOR @ OAK")
        self.assertEqual(r["best_bet"]["profit_units"], 1.5)
        self.assertEqual(r["worst_bet"]["profit_units"], -1.0)
        self.assertEqual(r["strongest_pregame"]["side"], "home")
        self.assertEqual(r["strongest_pregame"]["price_american"], 150)
        self.assertIn("basis", r["strongest_pregame"])


# ---------------------------------------------------------------------------
# day_rollup, standalone -- exact hand-computed math, including ties.
# ---------------------------------------------------------------------------

def _fake_rec(*, market_key="h2h", side="home", line=None, price_american=100,
             decision_utc="2026-09-01T00:00:00+00:00", system_class=dr.FORWARD_TEST,
             staked=True, status="win", profit_units=None, value_points=None):
    return {
        "market_key": market_key, "side": side, "line": line,
        "price_american": price_american, "decision_utc": decision_utc,
        "system_class": system_class, "staked": staked, "value_points": value_points,
        "settlement": {"status": status, "profit_units": profit_units, "settled_day": None},
    }


class DayRollupMathTests(unittest.TestCase):
    T1, T2, T3, T4, T5, T6 = (
        "2026-09-01T01:00:00+00:00", "2026-09-01T02:00:00+00:00",
        "2026-09-01T03:00:00+00:00", "2026-09-01T04:00:00+00:00",
        "2026-09-01T05:00:00+00:00", "2026-09-01T06:00:00+00:00",
    )

    def setUp(self):
        self.win_a = _fake_rec(market_key="h2h", price_american=150, decision_utc=self.T2,
                               system_class=dr.FORWARD_TEST, status="win",
                               profit_units=2.0, value_points=5.0)
        self.win_b = _fake_rec(market_key="h2h", price_american=-110, decision_utc=self.T1,
                               system_class=dr.CONTROL, status="win",
                               profit_units=2.0, value_points=12.0)
        self.loss_a = _fake_rec(market_key="totals", price_american=120, decision_utc=self.T4,
                                system_class=dr.FORWARD_TEST, status="loss",
                                profit_units=-3.0, value_points=3.0)
        self.loss_b = _fake_rec(market_key="totals", price_american=-130, decision_utc=self.T3,
                                system_class=dr.MARKET_REFERENCE, status="loss",
                                profit_units=-3.0, value_points=-2.0)
        self.push = _fake_rec(market_key="h2h", price_american=100, decision_utc=self.T5,
                              system_class=dr.MARKET_REFERENCE, status="push",
                              profit_units=0.0, value_points=0.0)
        self.pending = _fake_rec(market_key="totals", price_american=-105, decision_utc=self.T6,
                                 system_class=dr.FORWARD_TEST, status="pending",
                                 profit_units=None, value_points=20.0)
        self.not_staked = _fake_rec(staked=False, status="unsettled", value_points=999.0)
        self.game = {"away_team": "AAA", "home_team": "BBB", "recommendations": [
            self.win_a, self.win_b, self.loss_a, self.loss_b,
            self.push, self.pending, self.not_staked,
        ]}
        self.games = [self.game]

    def test_counts(self):
        r = dr.day_rollup(self.games)
        self.assertEqual(r["n_games"], 1)
        self.assertEqual(r["n_recommendations"], 7)
        self.assertEqual(r["n_staked"], 6)
        self.assertEqual(r["wins"], 2)
        self.assertEqual(r["losses"], 2)
        self.assertEqual(r["pushes"], 1)
        self.assertEqual(r["pending"], 1)

    def test_units_and_return(self):
        r = dr.day_rollup(self.games)
        self.assertEqual(r["units_staked"], 4.0)  # push never counts as staked exposure
        self.assertAlmostEqual(r["units_net"], -2.0, places=6)
        self.assertAlmostEqual(r["return_on_units"], -0.5, places=6)

    def test_avg_odds_decimal_over_every_settled_bet_including_push(self):
        r = dr.day_rollup(self.games)
        expected = statistics.mean([
            odds_math.american_to_decimal(150), odds_math.american_to_decimal(-110),
            odds_math.american_to_decimal(120), odds_math.american_to_decimal(-130),
            odds_math.american_to_decimal(100),
        ])
        self.assertAlmostEqual(r["avg_odds_decimal"], expected, places=6)

    def test_by_market_and_by_class(self):
        r = dr.day_rollup(self.games)
        self.assertEqual(r["by_market"]["h2h"], {"wins": 2, "losses": 0, "pushes": 1, "units_net": 4.0})
        self.assertEqual(r["by_market"]["totals"], {"wins": 0, "losses": 2, "pushes": 0, "units_net": -6.0})
        self.assertEqual(r["by_class"][dr.FORWARD_TEST]["wins"], 1)
        self.assertEqual(r["by_class"][dr.FORWARD_TEST]["losses"], 1)
        self.assertAlmostEqual(r["by_class"][dr.FORWARD_TEST]["units_net"], -1.0, places=6)
        # units_staked joined this bucket 2026-09-10 so a caller can compute
        # a RETURN per class, not just a unit total -- the Daily Recap
        # gallery needed a denominator to show the forward-test slice
        # instead of the pooled figures it was printing beneath a strip
        # captioned "our forward-test systems only".
        self.assertEqual(r["by_class"][dr.CONTROL],
                         {"wins": 1, "losses": 0, "pushes": 0,
                          "units_net": 2.0, "units_staked": 1.0})
        self.assertEqual(r["by_class"][dr.MARKET_REFERENCE]["losses"], 1)
        self.assertEqual(r["by_class"][dr.MARKET_REFERENCE]["pushes"], 1)
        # A push never counts toward stake exposure (src.accounts.paper's
        # convention), so this class staked one unit across two settlements.
        self.assertEqual(r["by_class"][dr.MARKET_REFERENCE]["units_staked"], 1.0)

    def test_best_bet_tie_break_is_earliest_decision_utc(self):
        r = dr.day_rollup(self.games)
        # win_a and win_b are tied at profit=2.0 -- win_b (T1) is earlier.
        self.assertEqual(r["best_bet"]["price_american"], -110)
        self.assertEqual(r["best_bet"]["system_class"], dr.CONTROL)
        self.assertEqual(r["best_bet"]["profit_units"], 2.0)

    def test_worst_bet_tie_break_is_earliest_decision_utc(self):
        r = dr.day_rollup(self.games)
        # loss_a and loss_b are tied at profit=-3.0 -- loss_b (T3) is earlier.
        self.assertEqual(r["worst_bet"]["price_american"], -130)
        self.assertEqual(r["worst_bet"]["system_class"], dr.MARKET_REFERENCE)
        self.assertEqual(r["worst_bet"]["profit_units"], -3.0)

    def test_strongest_pregame_ignores_outcome_and_the_unstaked_rec(self):
        r = dr.day_rollup(self.games)
        # The pending rec has the highest value_points (20.0) of any STAKED
        # rec -- chosen despite not having settled yet, and despite the
        # not_staked rec's even-higher 999.0 (which must never be eligible).
        self.assertEqual(r["strongest_pregame"]["value_points"], 20.0)
        self.assertEqual(r["strongest_pregame"]["settlement_status"], "pending")
        self.assertIn("basis", r["strongest_pregame"])

    def test_matchup_string(self):
        r = dr.day_rollup(self.games)
        self.assertEqual(r["best_bet"]["matchup"], "AAA @ BBB")

    def test_empty_games_list_is_honestly_zeroed(self):
        r = dr.day_rollup([])
        self.assertEqual(r["n_games"], 0)
        self.assertEqual(r["n_recommendations"], 0)
        self.assertIsNone(r["return_on_units"])
        self.assertIsNone(r["avg_odds_decimal"])
        self.assertIsNone(r["best_bet"])
        self.assertIsNone(r["worst_bet"])
        self.assertIsNone(r["strongest_pregame"])


# ---------------------------------------------------------------------------
# day_index
# ---------------------------------------------------------------------------

class DayIndexTests(_HermeticBase):
    def test_newest_first_one_row_per_date(self):
        rows = dr.day_index(limit=30, **self._kwargs())
        dates = [row["date"] for row in rows]
        self.assertEqual(dates, ["2026-09-09", "2026-09-08"])

    def test_row_matches_day_record_rollup_for_the_same_date(self):
        rows = {row["date"]: row for row in dr.day_index(limit=30, **self._kwargs())}
        rec = dr.day_record("2026-09-08", **self._kwargs())
        row = rows["2026-09-08"]
        self.assertEqual(row["n_games"], rec["rollup"]["n_games"])
        self.assertEqual(row["n_staked"], rec["rollup"]["n_staked"])
        self.assertEqual(row["wins"], rec["rollup"]["wins"])
        self.assertEqual(row["losses"], rec["rollup"]["losses"])
        self.assertAlmostEqual(row["units_net"], rec["rollup"]["units_net"], places=6)
        # `settled` counts literal "pending" only -- the orphan's
        # "unsettled" bet does not stop this date from reading settled.
        self.assertTrue(row["settled"])

    def test_pending_date_is_not_settled(self):
        rows = {row["date"]: row for row in dr.day_index(limit=30, **self._kwargs())}
        self.assertFalse(rows["2026-09-09"]["settled"])
        self.assertEqual(rows["2026-09-09"]["pending"], 1)

    def test_limit_is_respected(self):
        rows = dr.day_index(limit=1, **self._kwargs())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-09-09")

    def test_loaders_called_once_regardless_of_date_count(self):
        """day_index must load decisions/wagers ONCE, not once per date --
        proved with counting fakes standing in for the default loaders."""
        with mock.patch.object(dr, "load_decisions", return_value=tuple(self.decisions)) as m_dec, \
             mock.patch.object(dr, "HashChainLedger") as m_hcl:
            m_hcl.return_value.read.return_value = list(self.wagers)
            rows = dr.day_index(limit=30, decisions=None, wagers=None,
                                accounts_dir=self.accounts_dir,
                                boxscores=self.boxscores, index=self.index)
        self.assertEqual(m_dec.call_count, 1)
        self.assertEqual(m_hcl.call_count, 1)
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# record_strip
# ---------------------------------------------------------------------------

class RecordStripTests(_HermeticBase):
    def test_today_window_is_all_pending(self):
        strip = dr.record_strip("2026-09-09", wagers=self.wagers,
                                accounts_dir=self.accounts_dir)
        today_w = strip["today"]
        self.assertEqual(today_w["label"], "TODAY")
        self.assertEqual(today_w["n_settled"], 0)
        self.assertEqual(today_w["pending"], 1)
        self.assertIsNone(today_w["units_net"])
        self.assertIsNone(today_w["return_on_units"])

    def test_last_7_is_forward_test_only(self):
        """doctrine section 6, fixed 2026-09-09: the headline windows report
        the product's own record, not CONTROL pooled in beside it. bet-a1
        (FWD, +150) won; bet-a2 (CTRL, -110) lost on the same game -- the
        headline strip must show only the win."""
        strip = dr.record_strip("2026-09-09", wagers=self.wagers,
                                accounts_dir=self.accounts_dir)
        last7 = strip["last_7"]
        self.assertEqual(last7["wins"], 1)
        self.assertEqual(last7["losses"], 0)
        self.assertAlmostEqual(last7["units_net"], 1.5, places=6)
        self.assertEqual(last7["n_settled"], 1)
        # bet-orphan (unsettled) and bet-pending both count toward pending
        # at this summary-tile granularity -- see the module docstring.
        # bet-a2 (CTRL) is excluded from this window entirely, not counted
        # as pending -- it is not the product's record, not an open position
        # in it.
        self.assertEqual(last7["pending"], 2)

    def test_all_classes_still_carries_the_pooled_diagnostic(self):
        """The unfiltered view is not deleted -- CONTROL's loss is still
        fully visible, just no longer inside the number a customer reads
        as the product's own record."""
        strip = dr.record_strip("2026-09-09", wagers=self.wagers,
                                accounts_dir=self.accounts_dir)
        pooled = strip["all_classes"]["last_7"]
        self.assertEqual(pooled["wins"], 1)
        self.assertEqual(pooled["losses"], 1)
        self.assertAlmostEqual(pooled["units_net"], 0.5, places=6)
        self.assertEqual(pooled["n_settled"], 2)

    def test_settled_through(self):
        strip = dr.record_strip("2026-09-09", wagers=self.wagers,
                                accounts_dir=self.accounts_dir)
        self.assertEqual(strip["settled_through"], "2026-09-08")

    def test_window_with_no_wagers_at_all_is_none(self):
        strip = dr.record_strip("2026-09-09", wagers=[], accounts_dir=self.accounts_dir)
        self.assertIsNone(strip["today"])

    def test_today_none_returns_every_window_none_with_a_note(self):
        strip = dr.record_strip(None, wagers=[], accounts_dir=self.accounts_dir)
        self.assertIsNone(strip["today"])
        self.assertIsNone(strip["last_7"])
        self.assertIsNone(strip["last_30"])
        self.assertIn("no 'today'", strip["note"])

    def test_malformed_today_never_raises(self):
        strip = dr.record_strip("not-a-date", wagers=[], accounts_dir=self.accounts_dir)
        self.assertIsNone(strip["today"])
        self.assertIn("not a valid ISO date", strip["note"])


# ---------------------------------------------------------------------------
# Missing-file / malformed-input tolerance
# ---------------------------------------------------------------------------

class MissingFileToleranceTests(unittest.TestCase):
    def test_day_record_never_raises_on_missing_everything(self):
        rec = dr.day_record("2026-01-01", decisions=(), wagers=(),
                            accounts_dir=Path("/no/such/dir"), boxscores=(), index={})
        self.assertEqual(rec["games"], [])
        self.assertEqual(rec["rollup"]["n_games"], 0)
        self.assertEqual(rec["notes"], [])

    def test_day_index_never_raises_on_missing_everything(self):
        rows = dr.day_index(limit=5, decisions=(), wagers=(),
                            accounts_dir=Path("/no/such/dir"), boxscores=(), index={})
        self.assertEqual(rows, [])

    def test_record_strip_never_raises_on_missing_everything(self):
        strip = dr.record_strip("2026-01-01", wagers=(), accounts_dir=Path("/no/such/dir"))
        self.assertIsNone(strip["today"])
        self.assertIsNone(strip["settled_through"])

    def test_default_loaders_swallow_exceptions(self):
        with mock.patch.object(dr, "load_decisions", side_effect=RuntimeError("boom")), \
             mock.patch.object(dr, "HashChainLedger", side_effect=RuntimeError("boom")):
            rec = dr.day_record("2026-01-01", accounts_dir=Path("/no/such/dir"))
        self.assertEqual(rec["games"], [])

    def test_missing_accounts_dir_means_every_staked_bet_is_pending(self):
        wagers = [{"bet_id": "b1", "date": "2026-01-01", "event_id": "ev1",
                  "system_id": "trivial_x", "market_key": "h2h",
                  "selection_id": "home", "side": "home", "line": None,
                  "price_american": 100, "decision_utc": "2026-01-01T00:00:00+00:00",
                  "game_pk": 1, "stake_units": 1.0}]
        index = {"ev1": {"away_abbrev": "AAA", "home_abbrev": "BBB",
                        "away_name": "A", "home_name": "B",
                        "commence_time": "2026-01-01T00:00:00Z", "date": "2026-01-01"}}
        rec = dr.day_record("2026-01-01", decisions=[], wagers=wagers,
                            accounts_dir=Path("/no/such/dir"), boxscores=[], index=index)
        r = rec["games"][0]["recommendations"][0]
        self.assertEqual(r["settlement"]["status"], "pending")


# ---------------------------------------------------------------------------
# Banned-language scan, targeted at this module's own literal strings --
# same discipline tests/test_customer_language.py enforces over
# src/analysis and src/report generally, applied directly here as a
# self-contained tripwire (mirrors tests/test_paper_performance.py's own
# BannedVocabularyTests).
# ---------------------------------------------------------------------------

class BannedVocabularyTests(unittest.TestCase):
    _BANNED = re.compile(
        r"\b(lock|guaranteed?|sure thing|can'?t lose|win[- ]probabilit\w*)\b"
        r"|\bEV\b|\bCLV\b",
        re.IGNORECASE)

    def test_constants_are_clean(self):
        for text in (dr.LABEL, dr.BASIS, dr.STAKE_POLICY,
                    dr._RECORD_STRIP_NOTE, dr._STRONGEST_PREGAME_BASIS):
            self.assertNotRegex(text, self._BANNED, text)

    def test_edge_never_appears_as_a_customer_noun(self):
        # Word-boundary match, not a bare substring check -- "knowledge"
        # legitimately contains "edge" and must not trip this.
        edge_word = re.compile(r"\bedges?\b", re.IGNORECASE)
        for text in (dr.LABEL, dr.BASIS, dr._RECORD_STRIP_NOTE,
                    dr._STRONGEST_PREGAME_BASIS):
            self.assertNotRegex(text, edge_word, text)

    def test_no_banned_literal_anywhere_in_the_module_source(self):
        """Every non-docstring string literal in daily_record.py, scanned
        with the same rule tests/test_customer_language.py applies to all
        of src/report -- run directly here so this file's own violations
        fail loudly without needing the whole-directory scan to catch them."""
        from tests.test_customer_language import _string_literals, _violations_in

        path = (Path(__file__).resolve().parent.parent / "src" / "report"
               / "daily_record.py")
        violations = []
        for lineno, text in _string_literals(path):
            violations.extend(_violations_in(text, f"daily_record.py:{lineno}"))
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
