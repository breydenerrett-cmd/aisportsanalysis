"""tests for src.ledger.records: DecisionRecord/ReviewRecord/Scorecard contracts.

Field names are pinned against docs/planning/synthesis-judge.md section 4.2
verbatim -- a rename there without updating this file (or vice versa) fails
here, which is the point.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from dataclasses import fields

from src.ledger import records as records_module
from src.ledger.records import (
    FORBIDDEN_OBJECTIVE_FIELDS,
    AccountSummary,
    DecisionRecord,
    ObjectiveView,
    PRICE_OBSERVATION_IDENTITY_FIELDS,
    RecordContractError,
    ReviewRecord,
    Scorecard,
    compute_thesis_outcome,
    objective,
)

# The frozen field lists, copied verbatim from synthesis-judge.md 4.2.
DECISION_RECORD_FIELDS = [
    "engine_version", "system_id", "system_version", "registry_fingerprint",
    "frame_fingerprint", "snapshot_fingerprint", "game_pk", "event_id",
    "decision_utc", "point_class", "information_time", "recorded_utc",
    "verdict", "selection_id", "market_key", "line", "book",
    "price_american", "consensus_fair", "books_at_decision", "friction",
    "p_model", "p_model_interval", "edge_bps", "price_improvement_bps",
    "rating", "thesis", "evidence", "counterarguments", "supporting_systems",
    "refusal_reason", "assumption_exposure", "stake_units",
    "prev_hash", "row_hash",
]

REVIEW_RECORD_FIELDS = [
    "decision_key", "review_utc", "settled", "thesis_outcome",
    "mechanism_checks", "market_path", "late_information",
    "missed_information", "lineup_delta", "bullpen_delta",
    "counterargument_realized", "variance_flag", "system_action",
    "new_hypothesis",
]

SCORECARD_FIELDS = [
    "system_id", "world", "window", "point_class", "market_key",
    "n_decisions", "n_independent_clusters", "logloss_vs_market", "brier",
    "reliability_bins", "realized_return", "realized_return_ci",
    "avg_odds_decimal", "clv_bps_mean", "stability", "price_sensitivity",
    "top5_win_share", "placebo_percentile", "cscv_pbo", "spa_p",
    "battery_verdict", "battery_rules_version", "effective_tests",
    "raw_tests", "total_searched_at_verdict", "account",
]


def _field_names(dc) -> list[str]:
    return [f.name for f in fields(dc)]


class ContractFieldNameTests(unittest.TestCase):
    def test_decision_record_field_names_verbatim(self):
        actual = _field_names(DecisionRecord)
        # known_at_grade is a task-required addition beyond 4.2's literal
        # text (alongside the PriceObservation identity fields); every 4.2
        # name must still be present.
        for name in DECISION_RECORD_FIELDS:
            self.assertIn(name, actual, f"DecisionRecord is missing {name!r}")

    def test_decision_record_carries_known_at_grade(self):
        self.assertIn("known_at_grade", _field_names(DecisionRecord))

    def test_decision_record_carries_price_observation_identity(self):
        # MARKET/SELECTION/LINE/PRICE/BOOK/TIMESTAMP, per the task.
        actual = set(_field_names(DecisionRecord))
        for human_name, field_name in PRICE_OBSERVATION_IDENTITY_FIELDS.items():
            self.assertIn(field_name, actual,
                          f"{human_name} -> {field_name} missing from DecisionRecord")
        self.assertEqual(
            set(PRICE_OBSERVATION_IDENTITY_FIELDS.keys()),
            {"MARKET", "SELECTION", "LINE", "PRICE", "BOOK", "TIMESTAMP"},
        )

    def test_review_record_field_names_verbatim(self):
        self.assertEqual(_field_names(ReviewRecord), REVIEW_RECORD_FIELDS)

    def test_scorecard_field_names_verbatim(self):
        self.assertEqual(_field_names(Scorecard), SCORECARD_FIELDS)

    def test_forbidden_objective_fields_match_synthesis_4_2(self):
        self.assertEqual(
            FORBIDDEN_OBJECTIVE_FIELDS,
            frozenset({"account", "bankroll", "units", "drawdown",
                       "roi_units", "profit_units"}),
        )


def _account() -> AccountSummary:
    return AccountSummary(bankroll=10000.0, units=100.0, drawdown=5.0,
                          roi_units=1.5, profit_units=15.0)


def _scorecard(**overrides) -> Scorecard:
    base = dict(
        system_id="sys1", world="real", window="2026", point_class="LATE_BOARD",
        market_key="h2h", n_decisions=250, n_independent_clusters=40,
        logloss_vs_market=0.65, brier=0.22, reliability_bins=(),
        realized_return=0.03, realized_return_ci=(-0.01, 0.07),
        avg_odds_decimal=1.91, clv_bps_mean=4.2, stability={},
        price_sensitivity={}, top5_win_share=0.3, placebo_percentile=80.0,
        cscv_pbo=0.4, spa_p=0.2, battery_verdict="ABOVE_PLACEBO_CEILING",
        battery_rules_version="v1", effective_tests=12, raw_tests=40,
        total_searched_at_verdict=100, account=_account(),
    )
    base.update(overrides)
    return Scorecard(**base)


def _decision(**overrides) -> DecisionRecord:
    base = dict(
        engine_version="v1", system_id="sys1", system_version="1.0.0",
        registry_fingerprint="fp1", frame_fingerprint=None,
        snapshot_fingerprint="snap1", game_pk=12345, event_id="evt1",
        decision_utc="2026-09-03T18:00:00Z", point_class="LATE_BOARD",
        information_time="2026-09-03T17:55:00Z",
        recorded_utc="2026-09-03T18:00:01Z", verdict="no_play",
        selection_id=None, market_key=None, line=None, book=None,
        price_american=None, consensus_fair=None, books_at_decision=None,
        friction=None, p_model=None, p_model_interval=None, edge_bps=None,
        price_improvement_bps=None, rating=None, thesis=None, evidence=[],
        counterarguments=[], supporting_systems=[], refusal_reason=None,
        assumption_exposure={}, stake_units=0.0, known_at_grade="A",
    )
    base.update(overrides)
    return DecisionRecord(**base)


class DecisionRecordTests(unittest.TestCase):
    def test_no_play_decision_constructs(self):
        d = _decision()
        self.assertEqual(d.verdict, "no_play")

    def test_play_requires_price_american(self):
        with self.assertRaises(RecordContractError):
            _decision(verdict="play", price_american=None,
                      evidence=["x"], counterarguments=[])

    def test_play_requires_evidence_or_counterarguments(self):
        with self.assertRaises(RecordContractError):
            _decision(verdict="play", price_american=-110,
                      evidence=[], counterarguments=[])

    def test_play_with_price_and_evidence_constructs(self):
        d = _decision(verdict="play", price_american=-110, evidence=["thesis note"],
                      selection_id="sel1", market_key="h2h", book="book_a")
        self.assertEqual(d.price_american, -110)

    def test_unknown_verdict_rejected(self):
        with self.assertRaises(RecordContractError):
            _decision(verdict="maybe")

    def test_unknown_known_at_grade_rejected(self):
        with self.assertRaises(RecordContractError):
            _decision(known_at_grade="Z")

    def test_line_must_be_string_not_float(self):
        with self.assertRaises(RecordContractError):
            _decision(line=6.5)

    def test_line_as_decimal_string_is_fine(self):
        d = _decision(line="6.5")
        self.assertEqual(d.line, "6.5")


class ReviewRecordTests(unittest.TestCase):
    def _checks(self, verdict):
        return ({"name": "check1", "expected": "x", "observed": "x",
                "verdict": verdict},)

    def test_thesis_outcome_must_be_computed_not_asserted(self):
        with self.assertRaises(RecordContractError):
            ReviewRecord(
                decision_key=("g1",), review_utc="2026-09-03T00:00:00Z",
                settled="win", thesis_outcome="CONFIRMED",
                mechanism_checks=(), market_path={}, late_information=(),
                missed_information=(), lineup_delta={}, bullpen_delta={},
                counterargument_realized=(), variance_flag=False,
                system_action="none", new_hypothesis=None,
            )

    def test_confirmed_on_win_with_all_checks_confirmed(self):
        r = ReviewRecord(
            decision_key=("g1",), review_utc="2026-09-03T00:00:00Z",
            settled="win", thesis_outcome="CONFIRMED",
            mechanism_checks=self._checks("confirmed"), market_path={},
            late_information=(), missed_information=(), lineup_delta={},
            bullpen_delta={}, counterargument_realized=(), variance_flag=False,
            system_action="none", new_hypothesis=None,
        )
        self.assertEqual(r.thesis_outcome, "CONFIRMED")

    def test_variance_requires_variance_flag(self):
        with self.assertRaises(RecordContractError):
            ReviewRecord(
                decision_key=("g1",), review_utc="2026-09-03T00:00:00Z",
                settled="loss", thesis_outcome="VARIANCE",
                mechanism_checks=self._checks("confirmed"), market_path={},
                late_information=(), missed_information=(), lineup_delta={},
                bullpen_delta={}, counterargument_realized=(),
                variance_flag=False,  # wrong -- must be True
                system_action="none", new_hypothesis=None,
            )

    def test_variance_with_flag_set_constructs(self):
        r = ReviewRecord(
            decision_key=("g1",), review_utc="2026-09-03T00:00:00Z",
            settled="loss", thesis_outcome="VARIANCE",
            mechanism_checks=self._checks("confirmed"), market_path={},
            late_information=(), missed_information=(), lineup_delta={},
            bullpen_delta={}, counterargument_realized=(), variance_flag=True,
            system_action="watch", new_hypothesis=None,
        )
        self.assertEqual(r.thesis_outcome, "VARIANCE")

    def test_compute_thesis_outcome_no_checks_is_untested(self):
        self.assertEqual(compute_thesis_outcome((), "win"), "UNTESTED")

    def test_compute_thesis_outcome_any_refuted_is_refuted(self):
        checks = ({"verdict": "confirmed"}, {"verdict": "refuted"})
        self.assertEqual(compute_thesis_outcome(checks, "win"), "REFUTED")

    def test_the_variance_scenario_from_the_docstring(self):
        # "this starter collapses third time through" and won anyway because
        # a reliever imploded -- mechanism NOT confirmed, so NOT CONFIRMED
        # even though the bet won. thesis_outcome must not launder this into
        # a win for the thesis.
        checks = ({"name": "starter_collapse_3rd_time", "verdict": "refuted"},)
        self.assertEqual(compute_thesis_outcome(checks, "win"), "REFUTED")


class ScorecardTests(unittest.TestCase):
    def test_constructs_with_account(self):
        s = _scorecard()
        self.assertIsInstance(s.account, AccountSummary)

    def test_account_must_be_account_summary(self):
        with self.assertRaises(RecordContractError):
            _scorecard(account={"bankroll": 1})

    def test_effective_tests_cannot_exceed_raw_tests(self):
        with self.assertRaises(RecordContractError):
            _scorecard(effective_tests=50, raw_tests=40)

    def test_objective_view_projection_has_no_account_field(self):
        s = _scorecard()
        view = s.objective_view()
        self.assertNotIn("account", [f.name for f in fields(view)])


class ObjectiveViewTwoLedgerTests(unittest.TestCase):
    def _kwargs(self, **overrides):
        base = dict(
            system_id="sys1", world="real", window="2026",
            point_class="LATE_BOARD", market_key="h2h", n_decisions=250,
            n_independent_clusters=40, logloss_vs_market=0.65, brier=0.22,
            reliability_bins=(), avg_odds_decimal=1.91, clv_bps_mean=4.2,
            stability={}, price_sensitivity={}, top5_win_share=0.3,
            placebo_percentile=80.0, cscv_pbo=0.4, spa_p=0.2,
            battery_verdict="ABOVE_PLACEBO_CEILING", battery_rules_version="v1",
            effective_tests=12, raw_tests=40, total_searched_at_verdict=100,
        )
        base.update(overrides)
        return base

    def test_constructs_without_money(self):
        view = ObjectiveView(**self._kwargs())
        self.assertEqual(view.system_id, "sys1")

    def test_refuses_bankroll_smuggled_via_extra(self):
        with self.assertRaises(RecordContractError):
            ObjectiveView(**self._kwargs(extra={"bankroll": 500}))

    def test_refuses_units_smuggled_nested_inside_extra(self):
        with self.assertRaises(RecordContractError):
            ObjectiveView(**self._kwargs(extra={"nested": {"units": 3}}))

    def test_refuses_roi_units_smuggled_inside_a_list(self):
        with self.assertRaises(RecordContractError):
            ObjectiveView(**self._kwargs(extra={"items": [{"roi_units": 1}]}))

    def test_every_forbidden_field_is_individually_refused(self):
        for name in FORBIDDEN_OBJECTIVE_FIELDS:
            with self.subTest(field=name):
                with self.assertRaises(RecordContractError):
                    ObjectiveView(**self._kwargs(extra={name: 1}))

    def test_benign_extra_is_accepted(self):
        view = ObjectiveView(**self._kwargs(extra={"note": "fine"}))
        self.assertEqual(view.extra["note"], "fine")

    def test_scorecard_to_objective_view_round_trip_cannot_see_money(self):
        s = _scorecard()
        view = s.objective_view()
        dumped = view.to_dict()
        for forbidden in FORBIDDEN_OBJECTIVE_FIELDS:
            self.assertNotIn(forbidden, dumped)


class ObjectiveFunctionASTTests(unittest.TestCase):
    """The AST test named in synthesis 4.2: `objective()` fails if any
    FORBIDDEN_OBJECTIVE_FIELDS name appears anywhere in its source, as a
    second, independent line of enforcement behind ObjectiveView's type."""

    def test_objective_function_signature_takes_an_objective_view(self):
        sig = inspect.signature(objective)
        params = list(sig.parameters.values())
        self.assertEqual(len(params), 1)

    def test_objective_source_never_names_a_forbidden_field(self):
        source = inspect.getsource(objective)
        tree = ast.parse(source)
        names_used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names_used.add(node.id)
            elif isinstance(node, ast.Attribute):
                names_used.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names_used.add(node.value)
        offending = names_used & FORBIDDEN_OBJECTIVE_FIELDS
        self.assertEqual(offending, set(),
                         f"objective() source names forbidden field(s): {offending}")

    def test_an_adversarial_objective_smuggling_bankroll_is_caught_by_this_test(self):
        # Prove the AST test mechanism itself works, using a function that
        # SHOULD fail it -- guards against the test silently checking nothing.
        def fake_objective(view):
            bankroll = getattr(view, "extra", {}).get("bankroll", 0)
            return view.logloss_vs_market + bankroll

        source = textwrap.dedent(inspect.getsource(fake_objective))
        tree = ast.parse(source)
        names_used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names_used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names_used |= {n.value for n in ast.walk(tree)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertTrue(names_used & FORBIDDEN_OBJECTIVE_FIELDS)


if __name__ == "__main__":
    unittest.main()
