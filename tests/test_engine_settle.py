"""S6a -- settle (`src.engine.settle_slate`): refusal on partial results,
idempotency, FLAT_1U arithmetic, and chain integrity after settlement.
Every store is a temp-directory fixture and every account ledger is
redirected to a temp path via `account_ledger_path_fn` -- no real project
data (`data/paper_accounts/`, `evidence/reviews_v2.jsonl`,
`evidence/scorecards_v2.jsonl`) is ever touched.
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.engine import settle_slate
from src.ledger.chain import HashChainLedger

SYSTEM = "test_system"
GAME_WIN = 900001  # bet wins
GAME_LOSS = 900002  # bet loses


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _write_results_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["game_pk", "date", "home_score", "away_score"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _wager_row(bet_id, game_pk, price_american, date_str="2026-09-02",
              market_key="h2h", selection_id="sel1", side="home"):
    return {
        "label": "PAPER", "date": date_str, "bet_id": bet_id,
        "system_id": SYSTEM, "market_key": market_key,
        "selection_id": selection_id, "side": side, "line": None,
        "price_american": price_american, "settlement_rule": "h2h",
        "stake_units": 1.0, "game_pk": game_pk, "event_id": f"evt-{bet_id}",
        "decision_utc": f"{date_str}T18:00:00+00:00",
        "selection_rule": "TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1",
    }


class SettleTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.wagers_path = base / "paper_wagers_v2.jsonl"
        self.results_path = base / "mlb_results.csv"
        self.f5_path = base / "first_five_results.jsonl"
        self.boxscores_glob = str(base / "boxscores_*.jsonl")
        self.info_events_path = base / "information_events.jsonl"
        self.decisions_path = base / "decisions_v2.jsonl"
        self.review_path = base / "reviews_v2.jsonl"
        self.scorecard_path = base / "scorecards_v2.jsonl"
        self.accounts_dir = base / "paper_accounts"

    def account_ledger_path_fn(self, system_id):
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in system_id)
        return self.accounts_dir / f"{safe}.jsonl"

    def run_settle(self, date_str, **kwargs):
        kwargs.setdefault("wagers_path", self.wagers_path)
        kwargs.setdefault("results_path", self.results_path)
        kwargs.setdefault("f5_historical_path", self.f5_path)
        kwargs.setdefault("boxscores_glob", self.boxscores_glob)
        kwargs.setdefault("information_events_path", self.info_events_path)
        kwargs.setdefault("decisions_path", self.decisions_path)
        kwargs.setdefault("review_path", self.review_path)
        kwargs.setdefault("scorecard_path", self.scorecard_path)
        kwargs.setdefault("account_ledger_path_fn", self.account_ledger_path_fn)
        return settle_slate.run_settle(date_str, **kwargs)


class TestRefusalOnPartialResults(SettleTestBase):
    def test_refuses_when_no_wagers_recorded(self):
        with self.assertRaises(settle_slate.SettleError):
            self.run_settle("2026-09-02")

    def test_refuses_the_whole_date_when_any_game_lacks_a_result(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, -150),
            _wager_row("bet-2", GAME_LOSS, 120),
        ])
        # Only GAME_WIN has a confirmed result -- GAME_LOSS's game has not
        # finished. The whole date must refuse, not settle bet-1 alone.
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle("2026-09-02")
        self.assertIn("partial slate", str(ctx.exception))
        # Nothing was written for the one confirmable game either.
        self.assertFalse(self.account_ledger_path_fn(SYSTEM).exists())

    def test_refuses_when_wager_has_no_resolved_game_pk(self):
        row = _wager_row("bet-1", None, -150)
        _write_jsonl(self.wagers_path, [row])
        with self.assertRaises(settle_slate.SettleError):
            self.run_settle("2026-09-02")


class TestFlatOneUnitArithmetic(SettleTestBase):
    def test_win_and_loss_profit_units_are_flat_1u(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-win", GAME_WIN, 150, selection_id="win_sel"),
            _wager_row("bet-loss", GAME_LOSS, -150, selection_id="loss_sel"),
        ])
        _write_results_csv(self.results_path, [
            # home won 5-2 -> "home" side bet-win WINS
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
            # home lost 2-5 -> "home" side bet-loss LOSES
            {"game_pk": GAME_LOSS, "date": "2026-09-02",
             "home_score": 2, "away_score": 5},
        ])
        report = self.run_settle("2026-09-02")
        self.assertEqual(len(report.systems), 1)
        sysres = report.systems[0]
        self.assertEqual(len(sysres.settled), 2)
        by_id = {s.bet.bet_id: s for s in sysres.settled}
        # price=+150 win: profit = 1.0 * 150/100 = 1.5 units
        self.assertAlmostEqual(by_id["bet-win"].profit_units, 1.5)
        self.assertEqual(by_id["bet-win"].outcome, "win")
        # price=-150 loss: profit = -1.0 unit (flat stake lost, not scaled
        # by price)
        self.assertAlmostEqual(by_id["bet-loss"].profit_units, -1.0)
        self.assertEqual(by_id["bet-loss"].outcome, "loss")
        self.assertAlmostEqual(sysres.bankroll, 1000.0 + 1.5 - 1.0)
        for s in sysres.settled:
            self.assertEqual(s.bet.stake_units, 1.0)


class TestIdempotentSettlement(SettleTestBase):
    def test_rerun_settles_nothing_twice(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, 150),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        first = self.run_settle("2026-09-02")
        second = self.run_settle("2026-09-02")

        self.assertEqual(len(first.systems[0].settled), 1)
        self.assertEqual(len(second.systems[0].settled), 0)
        self.assertEqual(second.systems[0].duplicate, 1)
        # Bankroll is identical across both reports -- nothing double-counted.
        self.assertAlmostEqual(first.systems[0].bankroll,
                               second.systems[0].bankroll)

        account_rows = HashChainLedger(
            self.account_ledger_path_fn(SYSTEM)).read()
        self.assertEqual(len(account_rows), 1)


class TestChainVerifyAfterSettlement(SettleTestBase):
    def test_account_review_and_scorecard_chains_all_verify(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, 150),
            _wager_row("bet-2", GAME_LOSS, -150),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
            {"game_pk": GAME_LOSS, "date": "2026-09-02",
             "home_score": 2, "away_score": 5},
        ])
        self.run_settle("2026-09-02")

        account_verify = HashChainLedger(
            self.account_ledger_path_fn(SYSTEM)).verify()
        self.assertTrue(account_verify.ok, account_verify.reason)
        review_verify = HashChainLedger(self.review_path).verify()
        self.assertTrue(review_verify.ok, review_verify.reason)
        scorecard_verify = HashChainLedger(self.scorecard_path).verify()
        self.assertTrue(scorecard_verify.ok, scorecard_verify.reason)


class TestScorecardVerdictAssembled(SettleTestBase):
    def test_promotion_verdict_is_computed_and_recorded(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, 150),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        report = self.run_settle("2026-09-02")
        verdict = report.systems[0].scorecard_verdict
        self.assertIn(verdict.promote, (True, False))
        self.assertTrue(verdict.reasons)
        scorecard_rows = HashChainLedger(self.scorecard_path).read()
        self.assertEqual(len(scorecard_rows), 1)
        self.assertEqual(scorecard_rows[0]["system_id"], SYSTEM)


class TestF5FromBoxscoreLinescore(SettleTestBase):
    def test_h2h_1st_5_settles_from_boxscore_linescore_when_no_historical_f5(self):
        row = _wager_row("bet-f5", GAME_WIN, 150, market_key="h2h_1st_5_innings",
                         selection_id="f5_home")
        row["settlement_rule"] = "h2h_1st_5"
        _write_jsonl(self.wagers_path, [row])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        boxscore_path = Path(self.boxscores_glob.replace("*", "2026"))
        _write_jsonl(boxscore_path, [{
            "type": "linescore", "game_pk": GAME_WIN,
            "innings": [
                {"num": 1, "home_runs": 0, "away_runs": 0},
                {"num": 2, "home_runs": 1, "away_runs": 0},
                {"num": 3, "home_runs": 0, "away_runs": 0},
                {"num": 4, "home_runs": 0, "away_runs": 1},
                {"num": 5, "home_runs": 0, "away_runs": 0},
                {"num": 6, "home_runs": 4, "away_runs": 1},
            ],
        }])
        report = self.run_settle("2026-09-02")
        settled = report.systems[0].settled[0]
        # F5: home 1, away 1 -- a tie pushes on h2h_1st_5 (unlike full-game).
        self.assertEqual(settled.outcome, "push")
        self.assertEqual(settled.profit_units, 0.0)


GAME_EARLY = 900003  # 2026-08-31's game, bet wins
GAME_LATE = 900004   # 2026-09-02's game, bet loses


class TestScorecardBankrollAgreesWithEod(SettleTestBase):
    """N5/N6 regression: settling dates OUT OF CALENDAR ORDER (this
    vertical slice's real backfill settled 2026-09-02 before 2026-08-31)
    must not corrupt a Scorecard's published `account`. Before the fix,
    `build_scorecard`'s `bets` was "whatever the ledger holds right now",
    so the `window=2026-08-31` Scorecard -- settled SECOND, after 09-02 was
    already in the ledger -- would have wrongly folded 09-02's settlement
    into its 08-31 bankroll: exactly the published `bankroll=995.0169`
    (cumulative-through-09-02) vs the EOD report's `bankroll=1000.9470`
    (genuinely as-of-08-31) disagreement the review measured, with the
    fitness "delta" section consequently reading backwards."""

    def test_out_of_order_settlement_still_publishes_the_true_as_of_date_bankroll(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-early", GAME_EARLY, 150,
                       date_str="2026-08-31", selection_id="early_sel"),
            _wager_row("bet-late", GAME_LATE, -150,
                       date_str="2026-09-02", selection_id="late_sel"),
        ])
        _write_results_csv(self.results_path, [
            # bet-early (home, +150) WINS: home 5, away 2.
            {"game_pk": GAME_EARLY, "date": "2026-08-31",
             "home_score": 5, "away_score": 2},
            # bet-late (home, -150) LOSES: home 2, away 5.
            {"game_pk": GAME_LATE, "date": "2026-09-02",
             "home_score": 2, "away_score": 5},
        ])

        # Settle OUT OF CALENDAR ORDER: 2026-09-02 (the later date) first,
        # exactly as this project's real backfill did.
        self.run_settle("2026-09-02")
        self.run_settle("2026-08-31")

        scorecard_rows = HashChainLedger(str(self.scorecard_path)).read()
        by_window = {row["window"]: row for row in scorecard_rows
                    if row.get("kind") != "genesis"}
        sc_early = by_window["2026-08-31"]
        sc_late = by_window["2026-09-02"]

        # The window=2026-08-31 Scorecard must NEVER include 09-02's loss,
        # even though 09-02 was settled first and is already in the
        # ledger by the time 08-31 is settled.
        self.assertAlmostEqual(sc_early["account"]["bankroll"], 1001.5)

        # EOD's own as-of-2026-08-31 replay (the SAME point-in-time cut,
        # applied independently) must agree exactly.
        from src.report.eod import account_day_from_ledger_rows
        account_rows = HashChainLedger(
            self.account_ledger_path_fn(SYSTEM)).read()
        eod_account = account_day_from_ledger_rows(
            SYSTEM, account_rows, "2026-08-31")
        self.assertAlmostEqual(eod_account.bankroll,
                               sc_early["account"]["bankroll"])
        self.assertAlmostEqual(eod_account.roi_units,
                               sc_early["account"]["roi_units"])
        self.assertAlmostEqual(eod_account.drawdown_max,
                               sc_early["account"]["drawdown"])

        # window=2026-09-02 is unaffected (bet-late alone: 1000 - 1.0).
        self.assertAlmostEqual(sc_late["account"]["bankroll"], 999.0)

        # The delta across windows, read in chronological (not settle) order,
        # is the TRUE forward difference -- not an artifact of settle order.
        self.assertAlmostEqual(
            sc_late["account"]["bankroll"] - sc_early["account"]["bankroll"],
            -1.0 - 1.5)


if __name__ == "__main__":
    unittest.main()
