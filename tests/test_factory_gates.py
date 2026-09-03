"""Tests for src.factory.gates: G-cadence, G0-G7, gate_ladder, LOCK."""

from __future__ import annotations

import unittest

from src.factory.gates import (
    GateError,
    LOCK_CRITERIA,
    LOCK_CRITERIA_HASH,
    TIER_LOCK,
    TIER_NEAR_MISS,
    TIER_NOT_ELIGIBLE,
    TIER_NOT_PROMOTED,
    gate_cadence,
    gate_g0_record_conformance,
    gate_g1_grade_audit,
    gate_g2_budget,
    gate_g3_settlement_before_collection,
    gate_g4_store_fidelity,
    gate_g5_ceiling,
    gate_g6_forward,
    gate_g7_owner_signoff,
    gate_ladder,
    lock_eligible,
)

# Every field this test fills in when it wants a gate's inputs to PASS.
_PASSING_STATE = {
    "G-cadence": {"daily_grades": ["B"] * 7},
    "G0": dict(reproduced_rows=100, total_rows=100, overlap_days=7,
               backfill_rows_stamped_l0_unavailable=True),
    "G1": dict(inputs_missing_known_at_grade=0,
               artifacts_missing_assumption_exposure=0,
               scorecards_missing_grade_cd_share=0),
    "G2": dict(monthly_allotment=100_000, daily_envelope=900,
               measured_probe_per_family={"h2h": 10},
               coded_drop_order=["props", "alternates"],
               tier_reconciled=True, balance_dated=True),
    "G3": dict(has_settlement_rule=True, has_fetchable_result_source=True,
               graded_examples=50, priced_by_system=True),
    "G4": dict(live_snapshot_reproduces_days=7,
               truncation_differential_byte_equal=True),
    "G5": dict(cell_preregistered=True, clears_ceiling=True,
               placebo_worlds_through_full_argmax=True, world_count=1000,
               required_world_count=1000, effective_tests_reported=True),
    "G6": dict(n_forward_selections=300, ledger_days=60, point_class="A",
               out_of_sample=True, within_sealed_epochs=True),
    "G7": dict(signed_off=True, signoff_date="2026-09-03", after_g6=True),
}


def _passing_state() -> dict:
    return {k: dict(v) for k, v in _PASSING_STATE.items()}


class GateCadenceTests(unittest.TestCase):
    def test_seven_green_days_pass(self):
        result = gate_cadence(["B"] * 7)
        self.assertTrue(result.passed)
        self.assertEqual(result.gate, "G-cadence")
        self.assertTrue(result.reasons)

    def test_short_history_fails(self):
        result = gate_cadence(["B"] * 3)
        self.assertFalse(result.passed)

    def test_one_bad_day_breaks_streak(self):
        result = gate_cadence(["B"] * 6 + ["C"])
        self.assertFalse(result.passed)

    def test_only_last_n_days_considered(self):
        # A bad day outside the trailing window must not fail the gate.
        result = gate_cadence(["D"] + ["B"] * 7)
        self.assertTrue(result.passed)

    def test_inputs_hash_reproducible(self):
        a = gate_cadence(["B"] * 7)
        b = gate_cadence(["B"] * 7)
        self.assertEqual(a.inputs_hash, b.inputs_hash)

    def test_bool_dunder(self):
        self.assertTrue(bool(gate_cadence(["B"] * 7)))
        self.assertFalse(bool(gate_cadence(["C"] * 7)))


class GateG0Tests(unittest.TestCase):
    def test_passes_with_full_reproduction(self):
        result = gate_g0_record_conformance(**_PASSING_STATE["G0"])
        self.assertTrue(result.passed)

    def test_fails_on_short_overlap(self):
        state = dict(_PASSING_STATE["G0"], overlap_days=3)
        self.assertFalse(gate_g0_record_conformance(**state).passed)

    def test_fails_on_mismatched_rows(self):
        state = dict(_PASSING_STATE["G0"], reproduced_rows=99)
        self.assertFalse(gate_g0_record_conformance(**state).passed)

    def test_fails_without_backfill_stamp(self):
        state = dict(_PASSING_STATE["G0"],
                      backfill_rows_stamped_l0_unavailable=False)
        self.assertFalse(gate_g0_record_conformance(**state).passed)


class GateG3Tests(unittest.TestCase):
    def test_ten_examples_enough_before_pricing(self):
        result = gate_g3_settlement_before_collection(
            has_settlement_rule=True, has_fetchable_result_source=True,
            graded_examples=10, priced_by_system=False,
        )
        self.assertTrue(result.passed)

    def test_ten_examples_not_enough_once_priced(self):
        result = gate_g3_settlement_before_collection(
            has_settlement_rule=True, has_fetchable_result_source=True,
            graded_examples=10, priced_by_system=True,
        )
        self.assertFalse(result.passed)

    def test_fifty_examples_enough_when_priced(self):
        result = gate_g3_settlement_before_collection(
            has_settlement_rule=True, has_fetchable_result_source=True,
            graded_examples=50, priced_by_system=True,
        )
        self.assertTrue(result.passed)


class GateG6Tests(unittest.TestCase):
    def test_class_c_refused(self):
        state = dict(_PASSING_STATE["G6"], point_class="C")
        self.assertFalse(gate_g6_forward(**state).passed)

    def test_below_selection_floor_refused(self):
        state = dict(_PASSING_STATE["G6"], n_forward_selections=299)
        self.assertFalse(gate_g6_forward(**state).passed)

    def test_meets_floor_passes(self):
        self.assertTrue(gate_g6_forward(**_PASSING_STATE["G6"]).passed)


class GateG7Tests(unittest.TestCase):
    def test_undated_signoff_refused(self):
        result = gate_g7_owner_signoff(signed_off=True, signoff_date=None,
                                        after_g6=True)
        self.assertFalse(result.passed)

    def test_signoff_before_g6_refused(self):
        result = gate_g7_owner_signoff(signed_off=True,
                                        signoff_date="2026-01-01",
                                        after_g6=False)
        self.assertFalse(result.passed)


class GateLadderTests(unittest.TestCase):
    def test_all_passing_walks_full_ladder(self):
        result = gate_ladder(_passing_state())
        self.assertTrue(result.passed)
        self.assertIsNone(result.stopped_at)
        self.assertEqual([r.gate for r in result.results],
                          ["G-cadence", "G0", "G1", "G2", "G3", "G4", "G5",
                           "G6", "G7"])

    def test_stops_at_first_failure(self):
        state = _passing_state()
        state["G3"]["graded_examples"] = 0
        result = gate_ladder(state)
        self.assertFalse(result.passed)
        self.assertEqual(result.stopped_at, "G3")
        # Nothing after G3 was evaluated at all.
        self.assertEqual([r.gate for r in result.results],
                          ["G-cadence", "G0", "G1", "G2", "G3"])

    def test_missing_gate_inputs_fails_without_skipping(self):
        state = _passing_state()
        del state["G2"]
        result = gate_ladder(state)
        self.assertFalse(result.passed)
        self.assertEqual(result.stopped_at, "G2")

    def test_early_failure_stops_before_later_gates_even_if_they_would_pass(self):
        state = _passing_state()
        state["G-cadence"]["daily_grades"] = ["D"] * 7
        result = gate_ladder(state)
        self.assertEqual(result.stopped_at, "G-cadence")
        self.assertEqual(len(result.results), 1)


class LockCriteriaHashTests(unittest.TestCase):
    def test_hash_is_pinned(self):
        # Changing LOCK_CRITERIA must be a deliberate, reviewed edit --
        # this literal is the tripwire. If this test fails after an
        # intentional criteria change, update the expected hash here in
        # the same commit as the change, with a reason in the commit
        # message.
        expected = (
            "52eab8f8c1ade14a0f2f8db8c15f1316cdc6ab90d92601a6188a77ae36eb42ed"
        )
        self.assertEqual(LOCK_CRITERIA_HASH, expected)

    def test_hash_matches_independent_recomputation(self):
        import hashlib
        import json
        recomputed = hashlib.sha256(
            json.dumps(LOCK_CRITERIA, sort_keys=False,
                       separators=(",", ":"), ensure_ascii=True)
            .encode("utf-8")
        ).hexdigest()
        self.assertEqual(LOCK_CRITERIA_HASH, recomputed)
        self.assertEqual(len(LOCK_CRITERIA_HASH), 64)

    def test_criteria_count_matches_section_5(self):
        # §5's LOCK paragraph names eleven distinct conditions.
        self.assertEqual(len(LOCK_CRITERIA), 11)


class LockEligibleTests(unittest.TestCase):
    def _full_evidence(self) -> dict:
        return dict(
            system_promoted=True,
            band_n_from_power_analysis=True,
            band_ece_upper_bound=0.01,
            band_ece_threshold=0.05,
            review_cadences_under_threshold=3,
            required_review_cadences=3,
            forward_band_monotonic=True,
            edge_survives_worst_book=True,
            edge_survives_shrink=True,
            selection_agreement_below_threshold=True,
            residual_correlation_below_threshold=True,
            major_counterargument=False,
            forward_evidence_days=120,
            price_drift_monitored=True,
            base_rate_published_both_tails=True,
            withdrawal_automatic_configured=True,
        )

    def test_not_promoted_system_never_reaches_lock(self):
        verdict = lock_eligible({}, {"system_promoted": False})
        self.assertEqual(verdict.tier, TIER_NOT_PROMOTED)
        self.assertEqual(set(verdict.unmet), set(
            name for name, _ in LOCK_CRITERIA))

    def test_all_criteria_met_yields_lock(self):
        verdict = lock_eligible({}, self._full_evidence())
        self.assertEqual(verdict.tier, TIER_LOCK)
        self.assertEqual(verdict.unmet, ())

    def test_near_miss_on_one_unmet_criterion(self):
        evidence = self._full_evidence()
        evidence["major_counterargument"] = True
        verdict = lock_eligible({}, evidence)
        self.assertEqual(verdict.tier, TIER_NEAR_MISS)
        self.assertIn("no_major_counterargument", verdict.unmet)

    def test_not_eligible_with_many_unmet_criteria(self):
        evidence = self._full_evidence()
        evidence["major_counterargument"] = True
        evidence["forward_evidence_days"] = 10
        evidence["price_drift_monitored"] = False
        evidence["base_rate_published_both_tails"] = False
        verdict = lock_eligible({}, evidence)
        self.assertEqual(verdict.tier, TIER_NOT_ELIGIBLE)

    def test_verdict_never_carries_a_probability_field(self):
        verdict = lock_eligible({}, self._full_evidence())
        for f in ("probability", "prob", "win_probability", "p_win", "odds"):
            self.assertFalse(hasattr(verdict, f))

    def test_lock_tier_forbids_nonempty_unmet_by_construction(self):
        from src.factory.gates import LockVerdict
        with self.assertRaises(GateError):
            LockVerdict(tier=TIER_LOCK, unmet=("something",), reasons=("x",),
                        inputs_hash="deadbeef")


if __name__ == "__main__":
    unittest.main()
