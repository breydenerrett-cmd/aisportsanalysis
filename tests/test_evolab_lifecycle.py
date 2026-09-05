"""The strategy-family lifecycle state machine. See
docs/FACTORY_LIFECYCLE.md and src/evolab/lifecycle.py.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.evolab.lifecycle import (
    CANDIDATE,
    FORWARD_TESTING,
    PROMOTED_GATED,
    REPLACED,
    RETIRED,
    BatteryEvidence,
    LifecycleError,
    PreRegistration,
    PromotionGate,
    ReplacementEvidence,
    RetestResult,
    admit,
    append_audit,
    begin_forward_testing,
    promote,
    read_audit,
    replace,
    retest_due,
    retire,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _pre_reg(mechanism="market underrates rested bullpen depth in game 3"):
    return PreRegistration(mechanism=mechanism, registered_at=NOW.isoformat())


def _battery(**overrides):
    fields = dict(pre_registered=True, replication_passed=True,
                 battery_passed=True)
    fields.update(overrides)
    return BatteryEvidence(**fields)


def _gate(**overrides):
    fields = dict(pre_registered=True, replication_passed=True,
                 battery_passed=True, cscv_passed=True, spa_passed=True,
                 ceiling_cleared=True, forward_ledger_n=40)
    fields.update(overrides)
    return PromotionGate(**fields)


class TestPreRegistration(unittest.TestCase):

    def test_empty_mechanism_refused(self):
        with self.assertRaises(LifecycleError):
            PreRegistration(mechanism="   ", registered_at=NOW.isoformat())


class TestAdmit(unittest.TestCase):

    def test_admits_to_candidate_with_history_row(self):
        entry = admit("fam1", frozenset({"w1", "w2"}), _pre_reg(), now=NOW)
        self.assertEqual(entry.state, CANDIDATE)
        self.assertEqual(len(entry.history), 1)
        row = entry.history[0]
        self.assertEqual(row["from_state"], CANDIDATE)
        self.assertEqual(row["to_state"], CANDIDATE)
        self.assertEqual(row["trigger"], "admit")
        self.assertEqual(row["timestamp"], NOW.isoformat())

    def test_refuses_near_duplicate_of_retired_family(self):
        # J({w1,w2,w3,w4}, {w1,w2,w3}) = 3/4 = 0.75 < 0.8 -- not a duplicate.
        # J({w1,w2,w3,w4}, {w1,w2,w3,w4,w5}) = 4/5 = 0.8 -- exactly the bar.
        retired = {"fam0": frozenset({"w1", "w2", "w3", "w4", "w5"})}
        with self.assertRaises(LifecycleError):
            admit("fam1", frozenset({"w1", "w2", "w3", "w4"}), _pre_reg(),
                 retired_families=retired, now=NOW)

    def test_admits_when_below_family_threshold(self):
        retired = {"fam0": frozenset({"w1", "w2", "w3", "w4", "w5", "w6",
                                      "w7", "w8", "w9", "w10"})}
        entry = admit("fam1", frozenset({"w1", "w2"}), _pre_reg(),
                     retired_families=retired, now=NOW)
        self.assertEqual(entry.state, CANDIDATE)

    def test_refuses_missing_family_id(self):
        with self.assertRaises(LifecycleError):
            admit("", frozenset({"w1"}), _pre_reg(), now=NOW)


class TestBeginForwardTesting(unittest.TestCase):

    def test_advances_with_full_battery_evidence(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        entry = begin_forward_testing(entry, _battery(), now=NOW)
        self.assertEqual(entry.state, FORWARD_TESTING)
        self.assertEqual(len(entry.history), 2)

    def test_refuses_when_replication_missing(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        with self.assertRaises(LifecycleError) as ctx:
            begin_forward_testing(entry, _battery(replication_passed=False),
                                  now=NOW)
        self.assertIn("replication_passed", str(ctx.exception))

    def test_refuses_from_wrong_state(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        entry = begin_forward_testing(entry, _battery(), now=NOW)
        with self.assertRaises(LifecycleError):
            begin_forward_testing(entry, _battery(), now=NOW)


class TestPromote(unittest.TestCase):

    def _forward_entry(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        return begin_forward_testing(entry, _battery(), now=NOW)

    def test_promotes_when_every_gate_flag_true_and_n_floor_met(self):
        entry = self._forward_entry()
        entry = promote(entry, _gate(), now=NOW)
        self.assertEqual(entry.state, PROMOTED_GATED)

    def test_refuses_from_candidate_state(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        with self.assertRaises(LifecycleError):
            promote(entry, _gate(), now=NOW)

    def test_refuses_below_forward_ledger_floor(self):
        entry = self._forward_entry()
        with self.assertRaises(LifecycleError) as ctx:
            promote(entry, _gate(forward_ledger_n=5), now=NOW)
        self.assertIn("forward_ledger_n", str(ctx.exception))

    def test_bankroll_only_promotion_attempt_fails(self):
        """The owner rule under test: no promotion on bankroll alone. There
        is no bankroll/ROI field on PromotionGate at all -- attempting to
        smuggle one in raises a TypeError from the dataclass itself, and a
        gate built with every evidence flag left at its honest default
        (False) refuses regardless of how much "bankroll" text is attached
        to the attempt."""
        entry = self._forward_entry()
        with self.assertRaises(TypeError):
            PromotionGate(pre_registered=False, replication_passed=False,
                         battery_passed=False, cscv_passed=False,
                         spa_passed=False, ceiling_cleared=False,
                         forward_ledger_n=999999,  # huge bankroll-like number
                         roi=4.2)  # not a real field -- must reject
        # Even a syntactically legal gate with every real flag False (as if
        # only a giant forward_ledger_n / implied bankroll were offered as
        # evidence) is refused.
        bankroll_flavored_gate = PromotionGate(
            pre_registered=False, replication_passed=False,
            battery_passed=False, cscv_passed=False, spa_passed=False,
            ceiling_cleared=False, forward_ledger_n=999999)
        with self.assertRaises(LifecycleError) as ctx:
            promote(entry, bankroll_flavored_gate, now=NOW)
        msg = str(ctx.exception)
        for flag in PromotionGate.FLAGS:
            self.assertIn(flag, msg)


class TestRetire(unittest.TestCase):

    def _forward_entry(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        return begin_forward_testing(entry, _battery(), now=NOW)

    def test_retires_when_failed_and_coverage_survives(self):
        entry = self._forward_entry()
        failed = RetestResult(passed=False, block_index=3, reference="ref1")
        entry = retire(entry, failed, family_still_has_passing_member=True,
                       now=NOW)
        self.assertEqual(entry.state, RETIRED)

    def test_refuses_retire_when_retest_passed(self):
        entry = self._forward_entry()
        passed = RetestResult(passed=True, block_index=3, reference="ref1")
        with self.assertRaises(LifecycleError):
            retire(entry, passed, family_still_has_passing_member=True,
                  now=NOW)

    def test_refuses_retire_when_no_surviving_coverage(self):
        # Failed retest but nothing else covers the same wagers -- this is a
        # replace() case, not a plain retirement (design section 4).
        entry = self._forward_entry()
        failed = RetestResult(passed=False, block_index=3, reference="ref1")
        with self.assertRaises(LifecycleError):
            retire(entry, failed, family_still_has_passing_member=False,
                  now=NOW)

    def test_bad_recent_block_alone_does_not_retire(self):
        """A strategy with a bad recent block but a still-passing gate is not
        retired -- noisy is not the same as falsified (design section 4)."""
        entry = self._forward_entry()
        still_passing = RetestResult(passed=True, block_index=3,
                                     reference="ref1")
        with self.assertRaises(LifecycleError):
            retire(entry, still_passing, family_still_has_passing_member=True,
                  now=NOW)


class TestReplace(unittest.TestCase):

    def _retired_entry(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        entry = begin_forward_testing(entry, _battery(), now=NOW)
        failed = RetestResult(passed=False, block_index=3, reference="ref1")
        return retire(entry, failed, family_still_has_passing_member=True,
                      now=NOW)

    def test_replaces_with_fresh_pre_registered_evidence(self):
        entry = self._retired_entry()
        retirement_ref = entry.history[-1]["evidence_ref"]
        ev = ReplacementEvidence(pre_registered=True, battery_passed=True,
                                 candidate_strategy_id="strat-new",
                                 retirement_evidence_ref=retirement_ref)
        entry = replace(entry, ev, lost_last_passing_member=True, now=NOW)
        self.assertEqual(entry.state, REPLACED)

    def test_refuses_without_coverage_gap(self):
        entry = self._retired_entry()
        ev = ReplacementEvidence(pre_registered=True, battery_passed=True,
                                 candidate_strategy_id="strat-new",
                                 retirement_evidence_ref="x")
        with self.assertRaises(LifecycleError):
            replace(entry, ev, lost_last_passing_member=False, now=NOW)

    def test_refuses_without_fresh_pre_registration(self):
        entry = self._retired_entry()
        ev = ReplacementEvidence(pre_registered=False, battery_passed=True,
                                 candidate_strategy_id="strat-new",
                                 retirement_evidence_ref="x")
        with self.assertRaises(LifecycleError):
            replace(entry, ev, lost_last_passing_member=True, now=NOW)

    def test_refuses_from_non_retired_state(self):
        entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
        ev = ReplacementEvidence(pre_registered=True, battery_passed=True,
                                 candidate_strategy_id="strat-new",
                                 retirement_evidence_ref="x")
        with self.assertRaises(LifecycleError):
            replace(entry, ev, lost_last_passing_member=True, now=NOW)


class TestRetestDue(unittest.TestCase):

    def test_due_once_block_full(self):
        self.assertTrue(retest_due(10, block_width=10))
        self.assertTrue(retest_due(11, block_width=10))

    def test_not_due_below_block_width(self):
        self.assertFalse(retest_due(9, block_width=10))

    def test_rejects_negative_games(self):
        with self.assertRaises(LifecycleError):
            retest_due(-1)

    def test_uses_default_block_width_matching_sweep(self):
        from src.evolab.sweep import DEFAULT_N_BLOCKS
        self.assertFalse(retest_due(DEFAULT_N_BLOCKS - 1))
        self.assertTrue(retest_due(DEFAULT_N_BLOCKS))


class TestAuditLog(unittest.TestCase):

    def test_append_and_read_round_trip_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            append_audit(path, {"a": 1})
            append_audit(path, {"a": 2})
            rows = read_audit(path)
            self.assertEqual([r["a"] for r in rows], [1, 2])

    def test_read_missing_file_is_empty_not_error(self):
        rows = read_audit("/nonexistent/path/audit.jsonl")
        self.assertEqual(rows, [])

    def test_transitions_write_stable_evidence_ref(self):
        # The same PreRegistration content produces the same evidence_ref
        # hash regardless of admit() call order -- reproducibility, not a
        # random id.
        e1 = admit("fam1", frozenset({"w1"}), _pre_reg("reason a"), now=NOW)
        e2 = admit("fam2", frozenset({"w9"}), _pre_reg("reason a"), now=NOW)
        self.assertEqual(e1.history[0]["evidence_ref"],
                         e2.history[0]["evidence_ref"])

    def test_full_lifecycle_audit_trail_is_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            entry = admit("fam1", frozenset({"w1"}), _pre_reg(), now=NOW)
            append_audit(path, entry.history[-1])
            entry = begin_forward_testing(entry, _battery(), now=NOW)
            append_audit(path, entry.history[-1])
            entry = promote(entry, _gate(), now=NOW)
            append_audit(path, entry.history[-1])
            rows = read_audit(path)
            self.assertEqual([r["to_state"] for r in rows],
                             [CANDIDATE, FORWARD_TESTING, PROMOTED_GATED])
            # Every row is well-formed JSON with the required keys.
            for row in rows:
                for key in ("family_id", "from_state", "to_state", "trigger",
                           "evidence_ref", "timestamp"):
                    self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
