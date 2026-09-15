"""S6a -- settle (`src.engine.settle_slate`): refusal on partial results,
idempotency, FLAT_1U arithmetic, and chain integrity after settlement.
Every store is a temp-directory fixture and every account ledger is
redirected to a temp path via `account_ledger_path_fn` -- no real project
data (`data/paper_accounts/`, `evidence/reviews_v2.jsonl`,
`evidence/scorecards_v2.jsonl`) is ever touched.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.engine import settle_slate
from src.factory.scorecard import decision_key_for
from src.ledger.chain import HashChainLedger
from src.ledger.records import (
    DecisionRecord,
    PROBABILITY_PROVENANCE_NONE,
    ReviewRecord,
    compute_thesis_outcome,
)
from src.research import battery

SYSTEM = "test_system"
OTHER_SYSTEM = "test_system_2"
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
              market_key="h2h", selection_id="sel1", side="home",
              system_id=SYSTEM):
    return {
        "label": "PAPER", "date": date_str, "bet_id": bet_id,
        "system_id": system_id, "market_key": market_key,
        "selection_id": selection_id, "side": side, "line": None,
        "price_american": price_american, "settlement_rule": "h2h",
        "stake_units": 1.0, "game_pk": game_pk, "event_id": f"evt-{bet_id}",
        "decision_utc": f"{date_str}T18:00:00+00:00",
        "selection_rule": "TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1",
    }


# ---------------------------------------------------------------------------
# Battery-wiring fixtures -- a decision/review pair per graded selection,
# written straight to the decisions/reviews hash chains (independent of any
# wager this run settles), matching the row shapes
# `src.engine.settle_slate._battery_rows_for_system` reads.
# ---------------------------------------------------------------------------

def _battery_decision(day, idx, system_id=SYSTEM):
    return DecisionRecord(
        engine_version="v1", system_id=system_id, system_version="1.0.0",
        registry_fingerprint="fp1", frame_fingerprint=None,
        snapshot_fingerprint="snap1", game_pk=1, event_id=f"evt-battery-{idx}",
        decision_utc=f"{day}T12:00:00+00:00", point_class="LATE_BOARD",
        information_time=f"{day}T11:55:00+00:00",
        recorded_utc=f"{day}T12:00:01+00:00", verdict="play",
        selection_id="home", market_key="h2h", line=None, book="book_a",
        price_american=-110, consensus_fair=0.5, books_at_decision=5,
        friction=None, p_model=None, p_model_interval=None, edge_bps=None,
        price_improvement_bps=None, rating=None, thesis="t",
        evidence=["e"], counterarguments=[], supporting_systems=[],
        refusal_reason=None, assumption_exposure={}, stake_units=1.0,
        known_at_grade="A", p_model_provenance=PROBABILITY_PROVENANCE_NONE,
    )


def _append_decision(ledger: HashChainLedger, decision: DecisionRecord) -> None:
    row = decision.to_dict()
    row.pop("prev_hash", None)
    row.pop("row_hash", None)
    ledger.append(row)


def _append_review(ledger: HashChainLedger, decision: DecisionRecord,
                   settled: str) -> None:
    review = ReviewRecord(
        decision_key=decision_key_for(decision),
        review_utc=decision.decision_utc, settled=settled,
        thesis_outcome=compute_thesis_outcome((), settled),
        mechanism_checks=(), market_path={}, late_information=(),
        missed_information=(), lineup_delta={}, bullpen_delta={},
        counterargument_realized=(), variance_flag=False,
        system_action="none", new_hypothesis=None,
    )
    ledger.append(review.to_dict())


def _seed_graded_selections(decisions_path, review_path, n, *, system_id=SYSTEM,
                            start_day="2026-08-01", loss_every=4):
    """Write `n` decision/review pairs for `system_id`, one per day starting
    at `start_day`, every `loss_every`-th one a LOSS and the rest WIN, all
    carrying `consensus_fair=0.5` -- exactly the `{"date", "won", "implied"}`
    shape `battery.run` documents, once joined by
    `_battery_rows_for_system`. Returns the list of ISO day strings used."""
    decisions_ledger = HashChainLedger(decisions_path)
    reviews_ledger = HashChainLedger(review_path)
    base = dt.date.fromisoformat(start_day)
    days = []
    for i in range(n):
        day = (base + dt.timedelta(days=i)).isoformat()
        days.append(day)
        decision = _battery_decision(
            day, f"{system_id}-{start_day}-{i}", system_id=system_id)
        _append_decision(decisions_ledger, decision)
        _append_review(reviews_ledger, decision,
                       "loss" if i % loss_every == 0 else "win")
    return days


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
        self.game_pk_map_path = base / "event_game_map.jsonl"

    def account_ledger_path_fn(self, system_id):
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in system_id)
        return self.accounts_dir / f"{safe}.jsonl"

    def run_settle(self, date_str, **kwargs):
        # Hermetic: never read the real event->game_pk map from a test.
        kwargs.setdefault("game_pk_map_path", self.game_pk_map_path)
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

    def test_resolves_a_none_game_pk_from_the_gamekey_map(self):
        # Regression for 2026-09-05: the slate wrote every wager with
        # game_pk=None (the map had no row for its event yet) and the
        # hash-chained wager row can never be edited. A map row that exists
        # BY SETTLE TIME must rescue the wager -- an identity join, not an
        # outcome read -- and the settled bet must carry the resolved pk.
        _write_jsonl(self.wagers_path, [_wager_row("bet-1", None, 150)])
        _write_jsonl(self.game_pk_map_path, [{
            "event_id": "evt-bet-1", "game_pk": str(GAME_WIN),
            "resolved": True, "ambiguous": False,
            "home_team": "H", "away_team": "A",
            "commence_time": "2026-09-02T18:00:00Z",
        }])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        report = self.run_settle("2026-09-02")
        settled = report.systems[0].settled
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0].bet.game_pk, GAME_WIN)
        # The ledger row itself is untouched: still game_pk=None on disk.
        on_disk = [r for r in HashChainLedger(self.wagers_path).read()
                   if r.get("bet_id") == "bet-1"]
        self.assertIsNone(on_disk[0]["game_pk"])

    def test_map_never_overrides_a_game_pk_the_slate_resolved(self):
        _write_jsonl(self.wagers_path, [_wager_row("bet-1", GAME_WIN, 150)])
        _write_jsonl(self.game_pk_map_path, [{
            "event_id": "evt-bet-1", "game_pk": str(GAME_LOSS),
            "resolved": True, "ambiguous": False,
        }])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        report = self.run_settle("2026-09-02")
        self.assertEqual(report.systems[0].settled[0].bet.game_pk, GAME_WIN)


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


class TestBatteryWiredAboveFloor(SettleTestBase):
    """docs/ROADMAP.md Stage 13 item 1: a system with >= battery.MIN_N
    point-in-time graded selections gets a real battery verdict, not the
    permanent NOT_RUN scripts/research_readiness.py escalates about."""

    def test_system_with_min_n_graded_selections_gets_a_battery_verdict(self):
        _seed_graded_selections(self.decisions_path, self.review_path,
                                battery.MIN_N, system_id=SYSTEM)
        _write_jsonl(self.wagers_path, [_wager_row("bet-1", GAME_WIN, 150)])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        calls = []

        def fake_battery_run(rows, **kwargs):
            calls.append(rows)
            return {"survives": True, "ran": True, "fatal": [], "report": {},
                    "rules": {"version": "9.9.9", "fingerprint": "abc123"}}

        self.run_settle("2026-09-02", battery_run=fake_battery_run)

        self.assertEqual(len(calls), 1)
        self.assertGreaterEqual(len(calls[0]), battery.MIN_N)
        for row in calls[0]:
            self.assertEqual(set(row), {"date", "won", "implied"})
            self.assertLessEqual(row["date"], "2026-09-02")

        rows = [r for r in HashChainLedger(self.scorecard_path).read()
               if r.get("kind") != "genesis"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["battery_verdict"], "PASS")
        self.assertEqual(rows[0]["battery_rules_version"], "9.9.9")


class TestBatteryBelowFloorStaysNotRun(SettleTestBase):
    def test_system_below_min_n_never_calls_battery_and_stays_not_run(self):
        _seed_graded_selections(self.decisions_path, self.review_path,
                                battery.MIN_N - 1, system_id=SYSTEM)
        _write_jsonl(self.wagers_path, [_wager_row("bet-1", GAME_WIN, 150)])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
        ])
        calls = []

        def fake_battery_run(rows, **kwargs):
            calls.append(rows)
            return {"survives": True, "ran": True, "fatal": []}

        self.run_settle("2026-09-02", battery_run=fake_battery_run)

        self.assertEqual(calls, [])  # never invoked -- below the floor
        rows = [r for r in HashChainLedger(self.scorecard_path).read()
               if r.get("kind") != "genesis"]
        self.assertEqual(rows[0]["battery_verdict"], "NOT_RUN")


class TestBatteryErrorDoesNotAbortSettlement(SettleTestBase):
    def test_battery_exception_yields_error_verdict_and_other_systems_still_settle(self):
        _seed_graded_selections(self.decisions_path, self.review_path,
                                battery.MIN_N, system_id=SYSTEM)
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, 150, selection_id="sel1"),
            _wager_row("bet-2", GAME_LOSS, 150, selection_id="sel2",
                      system_id=OTHER_SYSTEM),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
            {"game_pk": GAME_LOSS, "date": "2026-09-02",
             "home_score": 2, "away_score": 5},
        ])

        def raising_battery_run(rows, **kwargs):
            raise RuntimeError("battery blew up")

        report = self.run_settle("2026-09-02", battery_run=raising_battery_run)

        # Settlement did not abort: both systems are in the report, and both
        # settled their one new bet each.
        self.assertEqual(len(report.systems), 2)
        for settlement in report.systems:
            self.assertEqual(len(settlement.settled), 1)

        rows = {r["system_id"]: r
               for r in HashChainLedger(self.scorecard_path).read()
               if r.get("kind") != "genesis"}
        # SYSTEM met the floor -- battery_run was called, raised, and the
        # error was translated rather than propagated. The real battery has
        # no "FAILED" it did not earn and no "unknown" rules version; this
        # combination is the honest tell that the battery errored rather
        # than ran.
        self.assertEqual(rows[SYSTEM]["battery_verdict"], "FAILED")
        self.assertEqual(rows[SYSTEM]["battery_rules_version"], "unknown")
        # OTHER_SYSTEM never had graded selections seeded -- below the
        # floor, unaffected by SYSTEM's battery blowing up.
        self.assertEqual(rows[OTHER_SYSTEM]["battery_verdict"], "NOT_RUN")


class TestBatteryPointInTime(SettleTestBase):
    def test_battery_only_sees_selections_graded_on_or_before_the_settle_date(self):
        # 30 graded selections on/before the settle date (2026-08-31)...
        before = _seed_graded_selections(
            self.decisions_path, self.review_path, battery.MIN_N,
            system_id=SYSTEM, start_day="2026-08-01")
        self.assertEqual(max(before), "2026-08-30")
        # ...plus 5 more graded AFTER it, from the same system's later
        # history -- these must never reach the battery for THIS settle run.
        _seed_graded_selections(
            self.decisions_path, self.review_path, 5,
            system_id=SYSTEM, start_day="2026-09-03")

        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, 150, date_str="2026-08-31"),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-08-31",
             "home_score": 5, "away_score": 2},
        ])
        calls = []

        def fake_battery_run(rows, **kwargs):
            calls.append(rows)
            return {"survives": True, "ran": True, "fatal": []}

        self.run_settle("2026-08-31", battery_run=fake_battery_run)

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), battery.MIN_N)
        self.assertTrue(all(row["date"] <= "2026-08-31" for row in calls[0]))


class TestScorecardRowShapeUnchanged(SettleTestBase):
    def test_battery_wiring_adds_no_new_fields_to_the_scorecard_row(self):
        _seed_graded_selections(self.decisions_path, self.review_path,
                                battery.MIN_N, system_id=SYSTEM)
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-1", GAME_WIN, 150, selection_id="sel1"),
            _wager_row("bet-2", GAME_LOSS, 150, selection_id="sel2",
                      system_id=OTHER_SYSTEM),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": GAME_WIN, "date": "2026-09-02",
             "home_score": 5, "away_score": 2},
            {"game_pk": GAME_LOSS, "date": "2026-09-02",
             "home_score": 2, "away_score": 5},
        ])

        def fake_battery_run(rows, **kwargs):
            return {"survives": True, "ran": True, "fatal": []}

        self.run_settle("2026-09-02", battery_run=fake_battery_run)

        rows = {r["system_id"]: r
               for r in HashChainLedger(self.scorecard_path).read()
               if r.get("kind") != "genesis"}
        # SYSTEM: battery PASS. OTHER_SYSTEM: below the floor, NOT_RUN --
        # same row shape either way, only the two battery fields differ.
        self.assertEqual(rows[SYSTEM]["battery_verdict"], "PASS")
        self.assertEqual(rows[OTHER_SYSTEM]["battery_verdict"], "NOT_RUN")
        self.assertEqual(set(rows[SYSTEM]), set(rows[OTHER_SYSTEM]))


if __name__ == "__main__":
    unittest.main()
