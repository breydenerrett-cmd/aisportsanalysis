"""Tests for src.report.eod: build_review / render_markdown / write_review."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.factory.scorecard import decision_key_for
from src.ledger.records import AccountSummary, DecisionRecord, ReviewRecord, Scorecard
from src.report.eod import (
    AccountDay,
    EodReviewError,
    SettlementSummary,
    account_day_from_ledger_rows,
    build_review,
    render_markdown,
    write_review,
)


def _decision(event_id, *, verdict="play", known_at_grade="A", price_american=-110,
              edge_bps=200, refusal_reason=None, assumption_exposure=None,
              day="2026-09-03"):
    return DecisionRecord(
        engine_version="v1", system_id="sys-1", system_version="1.0.0",
        registry_fingerprint="fp1", frame_fingerprint=None,
        snapshot_fingerprint="snap1", game_pk=1, event_id=event_id,
        decision_utc=f"{day}T18:00:00Z", point_class="LATE_BOARD",
        information_time=f"{day}T17:55:00Z", recorded_utc=f"{day}T18:00:01Z",
        verdict=verdict,
        selection_id="home" if verdict == "play" else None,
        market_key="h2h" if verdict == "play" else None,
        line=None, book="book_a" if verdict == "play" else None,
        price_american=price_american if verdict == "play" else None,
        consensus_fair=0.5, books_at_decision=5, friction=None,
        p_model=0.6 if verdict == "play" else None, p_model_interval=None,
        edge_bps=edge_bps if verdict == "play" else None,
        price_improvement_bps=None, rating=None,
        thesis="thesis note" if verdict == "play" else None,
        evidence=["evidence note"] if verdict == "play" else [],
        counterarguments=[], supporting_systems=[],
        refusal_reason=refusal_reason,
        assumption_exposure=assumption_exposure or {},
        stake_units=1.0 if verdict == "play" else 0.0,
        known_at_grade=known_at_grade,
    )


def _review(decision, *, settled="win", close_price=None):
    return ReviewRecord(
        decision_key=decision_key_for(decision),
        review_utc=decision.decision_utc, settled=settled,
        thesis_outcome="UNTESTED", mechanism_checks=(),
        market_path={} if close_price is None else {"close_price": close_price},
        late_information=(), missed_information=(), lineup_delta={},
        bullpen_delta={}, counterargument_realized=(), variance_flag=False,
        system_action="none", new_hypothesis=None,
    )


def _account_summary():
    return AccountSummary(bankroll=1000.0, units=10.0, drawdown=1.0,
                          roi_units=0.05, profit_units=0.5)


def _scorecard(system_id="sys-1", window="2026-09-02", **overrides):
    base = dict(
        system_id=system_id, world="real", window=window,
        point_class="LATE_BOARD", market_key="h2h", n_decisions=10,
        n_independent_clusters=2, logloss_vs_market=0.6, brier=0.2,
        reliability_bins=(), realized_return=0.01, realized_return_ci=(),
        avg_odds_decimal=1.9, clv_bps_mean=5.0, stability={},
        price_sensitivity={}, top5_win_share=0.2, placebo_percentile=50.0,
        cscv_pbo=0.5, spa_p=0.5, battery_verdict="NOT_RUN",
        battery_rules_version="absent", effective_tests=0, raw_tests=0,
        total_searched_at_verdict=0, account=_account_summary(),
    )
    base.update(overrides)
    return Scorecard(**base)


class BuildReviewRefusalTests(unittest.TestCase):
    def test_refuses_when_no_decisions(self):
        with self.assertRaises(EodReviewError):
            build_review("2026-09-03", [], [], [], [])

    def test_refuses_write_review_too_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp) / "docs" / "eod"
            with self.assertRaises(EodReviewError):
                write_review("2026-09-03", [], [], [], [], docs_dir=docs_dir,
                             chain_path=str(Path(tmp) / "chain.jsonl"))
            self.assertFalse((docs_dir / "2026-09-03.md").exists())
            self.assertFalse((Path(tmp) / "chain.jsonl").exists())


class BuildReviewContentTests(unittest.TestCase):
    def setUp(self):
        self.play = _decision("evt-1", verdict="play")
        self.refused = _decision("evt-2", verdict="refused_thin",
                                 refusal_reason="book_count below threshold")
        self.refused2 = _decision("evt-3", verdict="refused_thin",
                                  refusal_reason="book_count below threshold")
        self.grade_d = _decision("evt-4", verdict="play", known_at_grade="D",
                                 assumption_exposure={"no_lineup": True})
        self.decisions = [self.play, self.refused, self.refused2, self.grade_d]

    def test_decisions_made_only_lists_plays(self):
        review = build_review("2026-09-03", [], self.decisions, [], [])
        event_ids = {d.event_id for d in review.decisions_made}
        self.assertEqual(event_ids, {"evt-1", "evt-4"})

    def test_vetoes_grouped_by_cause_with_counts_and_reasons(self):
        review = build_review("2026-09-03", [], self.decisions, [], [])
        self.assertEqual(len(review.vetoes), 1)
        group = review.vetoes[0]
        self.assertEqual(group.verdict, "refused_thin")
        self.assertEqual(group.count, 2)
        self.assertEqual(group.reasons, ("book_count below threshold",))

    def test_grade_cd_share_computed(self):
        review = build_review("2026-09-03", [], self.decisions, [], [])
        self.assertAlmostEqual(review.grade_cd_share, 1 / 4)

    def test_assumption_exposure_section_lists_only_nonempty(self):
        review = build_review("2026-09-03", [], self.decisions, [], [])
        self.assertEqual(len(review.assumption_exposure_items), 1)
        self.assertEqual(review.assumption_exposure_items[0].event_id, "evt-4")

    def test_settlements_include_losers_and_losers_always_shown(self):
        win = SettlementSummary(system_id="sys-1", bet_id="b1",
                                market_key="h2h", selection_id="home",
                                price_american=-110, outcome="win",
                                profit_units=0.9)
        loss = SettlementSummary(system_id="sys-1", bet_id="b2",
                                 market_key="h2h", selection_id="away",
                                 price_american=-110, outcome="loss",
                                 profit_units=-1.0)
        account = AccountDay(
            system_id="sys-1", day="2026-09-03", starting_bankroll=1000.0,
            bankroll=999.9, peak=1000.9, drawdown_current=1.0,
            drawdown_max=1.0, roi_units=-0.05, n_settled=2, n_wins=1,
            n_losses=1, n_pushes=0, n_voids=0, total_staked_units=2.0,
            total_profit_units=-0.1, settlements=(win, loss),
        )
        review = build_review("2026-09-03", [account], self.decisions, [], [])
        self.assertIn(loss, review.settlements)
        self.assertEqual(review.losing_settlements, (loss,))

    def test_losing_section_rendered_even_when_present(self):
        loss = SettlementSummary(system_id="sys-1", bet_id="b2",
                                 market_key="h2h", selection_id="away",
                                 price_american=-110, outcome="loss",
                                 profit_units=-1.0)
        account = AccountDay(
            system_id="sys-1", day="2026-09-03", starting_bankroll=1000.0,
            bankroll=999.0, peak=1000.0, drawdown_current=1.0,
            drawdown_max=1.0, roi_units=-1.0, n_settled=1, n_wins=0,
            n_losses=1, n_pushes=0, n_voids=0, total_staked_units=1.0,
            total_profit_units=-1.0, settlements=(loss,),
        )
        review = build_review("2026-09-03", [account], self.decisions, [], [])
        markdown = render_markdown(review)
        self.assertIn("## Losing bets", markdown)
        self.assertIn("b2", markdown)

    def test_price_vs_close_available_only_where_close_captured(self):
        review_with_close = _review(self.play, close_price=-130)
        review_without_close = _review(self.grade_d, close_price=None)
        review = build_review("2026-09-03", [], self.decisions,
                              [review_with_close, review_without_close], [])
        self.assertEqual(review.n_reviewed, 2)
        self.assertEqual(len(review.price_vs_close), 1)
        self.assertEqual(review.price_vs_close[0].event_id, "evt-1")

    def test_scorecard_deltas_none_with_single_scorecard(self):
        review = build_review("2026-09-03", [], self.decisions, [],
                              [_scorecard(window="2026-09-03")])
        self.assertEqual(len(review.scorecard_deltas), 1)
        delta = review.scorecard_deltas[0]
        self.assertIsNone(delta.previous_window)
        self.assertEqual(delta.deltas, {})

    def test_scorecard_deltas_computed_with_two_scorecards(self):
        prev = _scorecard(window="2026-09-02", realized_return=0.01)
        curr = _scorecard(window="2026-09-03", realized_return=0.03)
        review = build_review("2026-09-03", [], self.decisions, [], [prev, curr])
        delta = review.scorecard_deltas[0]
        self.assertEqual(delta.previous_window, "2026-09-02")
        self.assertEqual(delta.current_window, "2026-09-03")
        prev_v, curr_v, d = delta.deltas["realized_return"]
        self.assertAlmostEqual(prev_v, 0.01)
        self.assertAlmostEqual(curr_v, 0.03)
        self.assertAlmostEqual(d, 0.02)

    def test_scorecard_delta_never_uses_a_window_after_the_report_date(self):
        """N6 regression: this project's real settle history ran
        2026-09-02 BEFORE 2026-08-31 (a later date settled first), so an
        EOD report for 2026-08-31 must never pull in the 2026-09-02
        scorecard as "current" -- that published a delta reading
        "2026-08-31 -> 2026-09-02" inside the 2026-08-31 report itself,
        backwards from what the report's own date claims."""
        earlier = _scorecard(window="2026-08-31", realized_return=0.02)
        later = _scorecard(window="2026-09-02", realized_return=0.09)
        review = build_review("2026-08-31", [], self.decisions, [],
                              [later, earlier])  # settled/appended in this
                                                  # exact real-world order
        self.assertEqual(len(review.scorecard_deltas), 1)
        delta = review.scorecard_deltas[0]
        self.assertEqual(delta.current_window, "2026-08-31")
        self.assertIsNone(delta.previous_window)
        self.assertEqual(delta.deltas, {})

    def test_a_later_correction_row_for_the_same_window_supersedes_it(self):
        """B4 fix, applied without rewriting ledger history: a correction
        Scorecard appended LATER for a window that already has one must be
        the one an EOD report uses for that window -- never averaged with,
        and never shadowed by, the earlier (contaminated) row."""
        previous = _scorecard(window="2026-08-30", realized_return=0.01)
        original = _scorecard(window="2026-08-31", realized_return=0.5)
        correction = _scorecard(window="2026-08-31", realized_return=0.0)
        review = build_review(
            "2026-08-31", [], self.decisions, [],
            [previous, original, correction])  # correction appended LAST
        self.assertEqual(len(review.scorecard_deltas), 1)
        delta = review.scorecard_deltas[0]
        self.assertEqual(delta.current_window, "2026-08-31")
        self.assertEqual(delta.previous_window, "2026-08-30")
        prev_v, curr_v, _ = delta.deltas["realized_return"]
        self.assertAlmostEqual(prev_v, 0.01)
        self.assertAlmostEqual(curr_v, 0.0)  # the CORRECTION's value, not
                                              # the original 0.5


class AccountDayReplayTests(unittest.TestCase):
    def test_replays_bankroll_and_isolates_the_days_settlements(self):
        rows = [
            {"system_id": "sys-1", "bet_id": "b1", "market_key": "h2h",
             "selection_id": "home", "price_american": -110,
             "stake_units": 1.0, "outcome": "win", "profit_units": 0.9,
             "day": "2026-09-02"},
            {"system_id": "sys-1", "bet_id": "b2", "market_key": "h2h",
             "selection_id": "away", "price_american": -110,
             "stake_units": 1.0, "outcome": "loss", "profit_units": -1.0,
             "day": "2026-09-03"},
            {"system_id": "sys-1", "bet_id": "b3", "market_key": "h2h",
             "selection_id": "home", "price_american": -110,
             "stake_units": 1.0, "outcome": "win", "profit_units": 0.9,
             "day": "2026-09-04"},  # after the report date -- excluded
        ]
        account = account_day_from_ledger_rows("sys-1", rows, "2026-09-03",
                                               starting_bankroll=1000.0)
        self.assertEqual(account.n_settled, 2)
        self.assertEqual(len(account.settlements), 1)
        self.assertEqual(account.settlements[0].bet_id, "b2")
        self.assertAlmostEqual(account.bankroll, 1000.0 + 0.9 - 1.0)
        self.assertAlmostEqual(account.total_staked_units, 2.0)


class RenderDeterminismTests(unittest.TestCase):
    def test_render_is_byte_identical_for_fixed_inputs(self):
        decisions = [_decision("evt-1", verdict="play"),
                    _decision("evt-2", verdict="refused_thin",
                             refusal_reason="thin book")]
        reviews = [_review(decisions[0], close_price=-130)]
        scorecards = [_scorecard(window="2026-09-03")]
        account = account_day_from_ledger_rows(
            "sys-1",
            [{"system_id": "sys-1", "bet_id": "b1", "market_key": "h2h",
              "selection_id": "home", "price_american": -110,
              "stake_units": 1.0, "outcome": "win", "profit_units": 0.9,
              "day": "2026-09-03"}],
            "2026-09-03",
        )
        first = render_markdown(build_review("2026-09-03", [account],
                                             decisions, reviews, scorecards))
        second = render_markdown(build_review("2026-09-03", [account],
                                              decisions, reviews, scorecards))
        self.assertEqual(first, second)
        self.assertIsInstance(first, str)


class WriteReviewTests(unittest.TestCase):
    def test_writes_markdown_file_and_chain_row(self):
        decisions = [_decision("evt-1", verdict="play")]
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp) / "docs" / "eod"
            chain_path = str(Path(tmp) / "chain.jsonl")
            result = write_review("2026-09-03", [], decisions, [], [],
                                  docs_dir=docs_dir, chain_path=chain_path)
            out_file = docs_dir / "2026-09-03.md"
            self.assertTrue(out_file.exists())
            self.assertEqual(out_file.read_text(encoding="utf-8"),
                             result["markdown"])
            self.assertTrue(Path(chain_path).exists())
            self.assertEqual(result["chain_row"]["date"], "2026-09-03")
            self.assertEqual(result["chain_row"]["n_decisions"], 1)

            from src.ledger.chain import HashChainLedger
            verify = HashChainLedger(chain_path).verify()
            self.assertTrue(verify.ok)


if __name__ == "__main__":
    unittest.main()
