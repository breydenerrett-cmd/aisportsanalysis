"""Factory promotion gates: G-cadence, G0-G7, and the LOCK tier.

docs/ARCHITECTURE_BETTING_ENGINE.md §5 names an ordered ladder of gates that
precede every paid tier switch-on and every promotion. This module makes
each gate a PURE function over explicit inputs -- no I/O, no clock, no
reading a store itself -- so a gate's pass/fail is reproducible from the
values it was handed and a test can assert every branch without touching
disk. `gate_ladder` evaluates the whole ladder in the §5 order and stops at
the first failure: nothing after a failed gate may report a result, because
nothing downstream of a failed gate is allowed to have been evaluated yet
("nothing may skip a gate").

LOCK is a separate thing from the G-ladder: §5 names it as a pre-registered,
highest-evidence tier, "never a guarantee" (§9.1 decision 5). Its criteria
are captured here as `LOCK_CRITERIA`, a frozen tuple of (name, description)
pairs copied verbatim from §5, hashed so any edit to the criteria is a
loud, deliberate test change rather than a silent drift -- see
`LOCK_CRITERIA_HASH` and tests/test_factory_gates.py.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class GateError(ValueError):
    """A gate was evaluated with malformed inputs (a bug, not a failed gate)."""


def _canonical_hash(payload: Any) -> str:
    """sha256 of `payload` serialised the same way regardless of dict order.

    Mirrors src/ledger/chain.py's canonical_bytes discipline -- used here so
    a GateResult's `inputs_hash` is reproducible from the same logical
    inputs no matter what order a caller built the mapping in.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GateResult:
    """The outcome of evaluating one gate.

    `inputs_hash` is a hash of the exact inputs the gate was evaluated
    against -- not a summary, not a subset -- so a later dispute over "what
    did this gate actually see" is answerable without re-running anything.
    `reasons` is always populated: on a pass it names what was satisfied, on
    a failure it names what specifically was not (never a bare boolean).
    """

    gate: str
    passed: bool
    reasons: tuple
    inputs_hash: str

    def __bool__(self) -> bool:
        return self.passed


def _result(gate: str, passed: bool, reasons: Sequence[str],
            inputs: Mapping[str, Any]) -> GateResult:
    if not reasons:
        raise GateError(f"{gate}: reasons must never be empty")
    return GateResult(gate=gate, passed=passed, reasons=tuple(reasons),
                       inputs_hash=_canonical_hash(inputs))


# -- G-cadence --------------------------------------------------------------

def gate_cadence(daily_grades: Sequence[str], *,
                  required_consecutive_days: int = 7) -> GateResult:
    """Seven consecutive days of measured capture cadence green.

    `daily_grades` is the sequence of per-day grades already computed by
    src/capture/cadence.py (`grade_from_gap` on the longest gap that day),
    oldest first. "Green" here means every one of the most recent
    `required_consecutive_days` days graded B (the SLO's own definition of
    a clean day) -- a single C or D day, or a day with no measurement at
    all (None), breaks the streak and this gate refuses.
    """
    inputs = {"daily_grades": list(daily_grades),
              "required_consecutive_days": required_consecutive_days}
    if len(daily_grades) < required_consecutive_days:
        return _result("G-cadence", False, (
            f"only {len(daily_grades)} measured day(s), need "
            f"{required_consecutive_days} consecutive green days",
        ), inputs)
    window = list(daily_grades)[-required_consecutive_days:]
    bad = [(i, g) for i, g in enumerate(window) if g != "B"]
    if bad:
        return _result("G-cadence", False, (
            f"{len(bad)} of the last {required_consecutive_days} days did "
            f"not grade B: {bad}",
        ), inputs)
    return _result("G-cadence", True, (
        f"last {required_consecutive_days} days all graded B",
    ), inputs)


# -- G0 Record conformance ---------------------------------------------------

def gate_g0_record_conformance(
    *, reproduced_rows: int, total_rows: int, overlap_days: int,
    backfill_rows_stamped_l0_unavailable: bool,
    required_overlap_days: int = 7,
) -> GateResult:
    """L1 projection reproduces the legacy store row-for-row over 7 days;
    2023-25 backfill rows carry `l0_available: false` and are never quoted
    as byte-reproducible from source."""
    inputs = dict(reproduced_rows=reproduced_rows, total_rows=total_rows,
                  overlap_days=overlap_days,
                  backfill_rows_stamped_l0_unavailable=backfill_rows_stamped_l0_unavailable,
                  required_overlap_days=required_overlap_days)
    reasons = []
    ok = True
    if overlap_days < required_overlap_days:
        ok = False
        reasons.append(f"overlap_days={overlap_days} < required "
                        f"{required_overlap_days}")
    if total_rows <= 0:
        ok = False
        reasons.append("total_rows must be > 0 to claim conformance")
    elif reproduced_rows != total_rows:
        ok = False
        reasons.append(f"reproduced_rows={reproduced_rows} != "
                        f"total_rows={total_rows}")
    if not backfill_rows_stamped_l0_unavailable:
        ok = False
        reasons.append("backfill rows are not stamped l0_available: false")
    if ok:
        reasons.append(f"{reproduced_rows}/{total_rows} rows reproduced "
                        f"over {overlap_days} days; backfill stamped")
    return _result("G0", ok, reasons, inputs)


# -- G1 Grade audit -----------------------------------------------------------

def gate_g1_grade_audit(
    *, inputs_missing_known_at_grade: int, artifacts_missing_assumption_exposure: int,
    scorecards_missing_grade_cd_share: int,
) -> GateResult:
    """Every registered input carries a computed known_at_grade; every
    artifact prints assumption_exposure; every scorecard carries
    share_of_selections_driven_by_grade_CD."""
    inputs = dict(
        inputs_missing_known_at_grade=inputs_missing_known_at_grade,
        artifacts_missing_assumption_exposure=artifacts_missing_assumption_exposure,
        scorecards_missing_grade_cd_share=scorecards_missing_grade_cd_share,
    )
    reasons = []
    ok = True
    if inputs_missing_known_at_grade:
        ok = False
        reasons.append(
            f"{inputs_missing_known_at_grade} registered input(s) lack a "
            "computed known_at_grade"
        )
    if artifacts_missing_assumption_exposure:
        ok = False
        reasons.append(
            f"{artifacts_missing_assumption_exposure} artifact(s) do not "
            "print assumption_exposure"
        )
    if scorecards_missing_grade_cd_share:
        ok = False
        reasons.append(
            f"{scorecards_missing_grade_cd_share} scorecard(s) lack "
            "share_of_selections_driven_by_grade_CD"
        )
    if ok:
        reasons.append("every input graded, every artifact exposed, every "
                        "scorecard carries its grade-C/D share")
    return _result("G1", ok, reasons, inputs)


# -- G2 Budget ----------------------------------------------------------------

def gate_g2_budget(
    *, monthly_allotment: int, daily_envelope: int, measured_probe_per_family: Mapping[str, int],
    coded_drop_order: Sequence[str], tier_reconciled: bool, balance_dated: bool,
) -> GateResult:
    """MONTHLY_ALLOTMENT and derived DAILY_ENVELOPE as constants; a measured
    probe per family; a coded drop order; tier and balance reconciled and
    dated."""
    inputs = dict(
        monthly_allotment=monthly_allotment, daily_envelope=daily_envelope,
        measured_probe_per_family=dict(measured_probe_per_family),
        coded_drop_order=list(coded_drop_order),
        tier_reconciled=tier_reconciled, balance_dated=balance_dated,
    )
    reasons = []
    ok = True
    if monthly_allotment <= 0:
        ok = False
        reasons.append("monthly_allotment must be a positive constant")
    if daily_envelope <= 0 or daily_envelope * 28 > monthly_allotment:
        ok = False
        reasons.append(
            f"daily_envelope={daily_envelope} is not a sane derivation of "
            f"monthly_allotment={monthly_allotment}"
        )
    if not measured_probe_per_family:
        ok = False
        reasons.append("no measured credit probe recorded per family")
    if not coded_drop_order:
        ok = False
        reasons.append("no coded drop order")
    if not tier_reconciled:
        ok = False
        reasons.append("tier not reconciled")
    if not balance_dated:
        ok = False
        reasons.append("balance not dated")
    if ok:
        reasons.append("budget constants, probes, drop order and "
                        "reconciliation all present")
    return _result("G2", ok, reasons, inputs)


# -- G3 Settlement before collection -----------------------------------------

def gate_g3_settlement_before_collection(
    *, has_settlement_rule: bool, has_fetchable_result_source: bool,
    graded_examples: int, priced_by_system: bool,
) -> GateResult:
    """A family needs a settlement rule, a fetchable result source, and ten
    graded examples before it may be captured at all -- fifty before a
    system may price it."""
    inputs = dict(
        has_settlement_rule=has_settlement_rule,
        has_fetchable_result_source=has_fetchable_result_source,
        graded_examples=graded_examples, priced_by_system=priced_by_system,
    )
    reasons = []
    ok = True
    if not has_settlement_rule:
        ok = False
        reasons.append("no settlement rule registered for this family")
    if not has_fetchable_result_source:
        ok = False
        reasons.append("no fetchable result source for this family")
    required = 50 if priced_by_system else 10
    if graded_examples < required:
        ok = False
        reasons.append(
            f"graded_examples={graded_examples} < {required} required "
            f"({'priced by a system' if priced_by_system else 'not yet priced'})"
        )
    if ok:
        reasons.append(
            f"settlement rule + result source + {graded_examples} graded "
            f"examples (>= {required} required)"
        )
    return _result("G3", ok, reasons, inputs)


# -- G4 Store fidelity + truncation differential ------------------------------

def gate_g4_store_fidelity(
    *, live_snapshot_reproduces_days: int, truncation_differential_byte_equal: bool,
    required_days: int = 7,
) -> GateResult:
    """Live snapshot fingerprints reproduce from the store for 7 days AND the
    truncated-store differential is byte-equal on a sampled corpus."""
    inputs = dict(
        live_snapshot_reproduces_days=live_snapshot_reproduces_days,
        truncation_differential_byte_equal=truncation_differential_byte_equal,
        required_days=required_days,
    )
    reasons = []
    ok = True
    if live_snapshot_reproduces_days < required_days:
        ok = False
        reasons.append(
            f"live_snapshot_reproduces_days={live_snapshot_reproduces_days} "
            f"< required {required_days}"
        )
    if not truncation_differential_byte_equal:
        ok = False
        reasons.append("truncated-store differential is not byte-equal on "
                        "the sampled corpus")
    if ok:
        reasons.append(
            f"{live_snapshot_reproduces_days} days reproduced, truncation "
            "differential byte-equal"
        )
    return _result("G4", ok, reasons, inputs)


# -- G5 Ceiling ---------------------------------------------------------------

def gate_g5_ceiling(
    *, cell_preregistered: bool, clears_ceiling: bool, placebo_worlds_through_full_argmax: bool,
    world_count: int, required_world_count: int, effective_tests_reported: bool,
) -> GateResult:
    """A pre-registered cell clears its ceiling with placebo worlds run
    through the full argmax, world count from power analysis, effective
    tests reported."""
    inputs = dict(
        cell_preregistered=cell_preregistered, clears_ceiling=clears_ceiling,
        placebo_worlds_through_full_argmax=placebo_worlds_through_full_argmax,
        world_count=world_count, required_world_count=required_world_count,
        effective_tests_reported=effective_tests_reported,
    )
    reasons = []
    ok = True
    if not cell_preregistered:
        ok = False
        reasons.append("cell was not pre-registered before evaluation")
    if not clears_ceiling:
        ok = False
        reasons.append("cell does not clear its placebo ceiling")
    if not placebo_worlds_through_full_argmax:
        ok = False
        reasons.append("placebo worlds were not run through the full argmax")
    if world_count < required_world_count:
        ok = False
        reasons.append(
            f"world_count={world_count} < required {required_world_count} "
            "(from power analysis)"
        )
    if not effective_tests_reported:
        ok = False
        reasons.append("effective_tests not reported alongside the verdict")
    if ok:
        reasons.append(
            f"pre-registered cell clears ceiling across {world_count} "
            "placebo worlds through the full argmax, effective tests reported"
        )
    return _result("G5", ok, reasons, inputs)


# -- G6 Forward ---------------------------------------------------------------

def gate_g6_forward(
    *, n_forward_selections: int, ledger_days: int, point_class: str,
    out_of_sample: bool, within_sealed_epochs: bool,
    required_selections: int = 300, required_ledger_days: int = 60,
) -> GateResult:
    """>=300 forward selections with book/price/rating/counterarguments and
    settled close; >=60 ledger days; class A/B; out-of-sample only; within
    sealed epochs."""
    inputs = dict(
        n_forward_selections=n_forward_selections, ledger_days=ledger_days,
        point_class=point_class, out_of_sample=out_of_sample,
        within_sealed_epochs=within_sealed_epochs,
        required_selections=required_selections,
        required_ledger_days=required_ledger_days,
    )
    reasons = []
    ok = True
    if n_forward_selections < required_selections:
        ok = False
        reasons.append(
            f"n_forward_selections={n_forward_selections} < required "
            f"{required_selections}"
        )
    if ledger_days < required_ledger_days:
        ok = False
        reasons.append(
            f"ledger_days={ledger_days} < required {required_ledger_days}"
        )
    if point_class not in ("A", "B"):
        ok = False
        reasons.append(
            f"point_class={point_class!r} is not class A or B"
        )
    if not out_of_sample:
        ok = False
        reasons.append("selections are not out-of-sample")
    if not within_sealed_epochs:
        ok = False
        reasons.append("selections are not within sealed epochs")
    if ok:
        reasons.append(
            f"{n_forward_selections} forward selections over "
            f"{ledger_days} ledger days, class {point_class}, OOS, sealed"
        )
    return _result("G6", ok, reasons, inputs)


# -- G7 Owner sign-off ---------------------------------------------------------

def gate_g7_owner_signoff(
    *, signed_off: bool, signoff_date: str | None, after_g6: bool,
) -> GateResult:
    """Explicit, dated, after G6."""
    inputs = dict(signed_off=signed_off, signoff_date=signoff_date,
                  after_g6=after_g6)
    reasons = []
    ok = True
    if not signed_off:
        ok = False
        reasons.append("owner has not signed off")
    if not signoff_date:
        ok = False
        reasons.append("sign-off is not dated")
    if not after_g6:
        ok = False
        reasons.append("sign-off is not recorded after G6 passed")
    if ok:
        reasons.append(f"owner signed off {signoff_date}, after G6")
    return _result("G7", ok, reasons, inputs)


# -- the ladder ---------------------------------------------------------------

# §5 order, verbatim. G-cadence precedes every paid tier switch-on and every
# analysis packet; G0..G7 then run in numeric order. Nothing may reorder or
# skip an entry here.
GATE_ORDER = ("G-cadence", "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7")

_GATE_FUNCTIONS = {
    "G-cadence": gate_cadence,
    "G0": gate_g0_record_conformance,
    "G1": gate_g1_grade_audit,
    "G2": gate_g2_budget,
    "G3": gate_g3_settlement_before_collection,
    "G4": gate_g4_store_fidelity,
    "G5": gate_g5_ceiling,
    "G6": gate_g6_forward,
    "G7": gate_g7_owner_signoff,
}


@dataclass(frozen=True, slots=True)
class LadderResult:
    """The outcome of walking the whole gate ladder.

    `results` holds every GateResult actually evaluated, in order -- the
    ladder stops at the first failure, so a failure at G3 means G4..G7 are
    simply ABSENT from `results`, not present with passed=False. That
    absence is the enforcement: nothing downstream of a failed gate has an
    opinion recorded about it at all.
    """

    passed: bool
    results: tuple
    stopped_at: str | None  # the gate name that first failed, or None

    def __bool__(self) -> bool:
        return self.passed


def gate_ladder(state: Mapping[str, Mapping[str, Any]]) -> LadderResult:
    """Evaluate G-cadence, G0..G7 in order; stop at the first failure.

    `state` maps each gate name in GATE_ORDER to the keyword-argument
    mapping its function needs (e.g. `state["G3"]` is passed as
    `gate_g3_settlement_before_collection(**state["G3"])`). A gate missing
    from `state` is treated as an automatic failure (its inputs were never
    even prepared) -- the ladder never silently skips ahead.
    """
    results = []
    for gate in GATE_ORDER:
        if gate not in state:
            results.append(_result(gate, False,
                                    (f"{gate}: no inputs provided",), {}))
            return LadderResult(passed=False, results=tuple(results),
                                 stopped_at=gate)
        fn = _GATE_FUNCTIONS[gate]
        try:
            result = fn(**state[gate])
        except TypeError as exc:
            raise GateError(f"{gate}: malformed inputs ({exc})") from exc
        results.append(result)
        if not result.passed:
            return LadderResult(passed=False, results=tuple(results),
                                 stopped_at=gate)
    return LadderResult(passed=True, results=tuple(results), stopped_at=None)


# -- LOCK -----------------------------------------------------------------
#
# LOCK is not a gate in the ladder -- it is a separate, higher tier a
# PROMOTED system's candidate can additionally reach. §9.1 decision 5: "LOCK
# is pre-registered as the highest evidence/confidence tier, never a
# guarantee. No artificial zero-LOCK season; the criteria decide." The
# criteria below are copied verbatim from §5 and frozen: any edit to the
# tuple changes LOCK_CRITERIA_HASH, which is pinned by a test that must be
# updated deliberately, not incidentally.

LOCK_CRITERIA: tuple = (
    ("from_promoted_system",
     "candidate is drawn from a PROMOTED system, never a pre-promotion one"),
    ("band_n_from_power_analysis",
     "band_n comes from a published power analysis"),
    ("band_ece_upper_bound_under_threshold",
     "the upper bootstrap bound of band ECE is under the threshold for k "
     "consecutive review cadences"),
    ("forward_band_monotonicity",
     "forward band monotonicity holds with clustered CIs"),
    ("edge_survives_worst_book_and_shrink",
     "edge survives at the worst book and under a 25% shrink of p_model "
     "toward the market"),
    ("two_systems_below_agreement_thresholds",
     "two systems whose measured selection-agreement and residual "
     "correlation are below pre-registered thresholds"),
    ("no_major_counterargument",
     "no MAJOR counterargument stands against the candidate"),
    ("forward_evidence_days",
     ">=90 days of forward evidence in the family"),
    ("price_drift_monitored",
     "post-publication price drift is recorded, with sustained adverse "
     "drift a demotion trigger"),
    ("base_rate_published_both_tails",
     "base rate is published with both tails (LOCK rate and near-misses "
     "by condition)"),
    ("withdrawal_automatic",
     "withdrawal is published automatically if criteria stop being met"),
)

LOCK_CRITERIA_HASH = hashlib.sha256(
    json.dumps(LOCK_CRITERIA, sort_keys=False, separators=(",", ":"),
               ensure_ascii=True).encode("utf-8")
).hexdigest()

LOCK_CRITERIA_NAMES = tuple(name for name, _ in LOCK_CRITERIA)

# Tiers `lock_eligible` may return. LOCK is the top; the others describe how
# far short a candidate fell, never a probability of winning.
TIER_LOCK = "LOCK"
TIER_NEAR_MISS = "NEAR_MISS"  # met most criteria, at least one unmet
TIER_NOT_ELIGIBLE = "NOT_ELIGIBLE"  # promoted system but far from LOCK
TIER_NOT_PROMOTED = "NOT_PROMOTED"  # not even drawn from a PROMOTED system


@dataclass(frozen=True, slots=True)
class LockVerdict:
    """The tier a candidate reached against LOCK_CRITERIA, with reasons.

    Never a probability of winning -- §9.1 decision 5 is explicit that LOCK
    is "never a guarantee", and this type has no field that could be read
    as one. `unmet` names every criterion (by LOCK_CRITERIA_NAMES key) the
    candidate failed to satisfy; on TIER_LOCK it is empty.
    """

    tier: str
    unmet: tuple
    reasons: tuple
    inputs_hash: str

    def __post_init__(self) -> None:
        if self.tier not in (TIER_LOCK, TIER_NEAR_MISS, TIER_NOT_ELIGIBLE,
                              TIER_NOT_PROMOTED):
            raise GateError(f"unknown LOCK tier {self.tier!r}")
        if self.tier == TIER_LOCK and self.unmet:
            raise GateError("TIER_LOCK must have no unmet criteria")


def lock_eligible(scorecard: Mapping[str, Any],
                   evidence: Mapping[str, Any]) -> LockVerdict:
    """Evaluate a candidate against LOCK_CRITERIA and return its tier.

    `scorecard` and `evidence` are plain mappings (a caller-assembled view
    over a real Scorecard plus whatever additional forward-evidence facts
    LOCK needs, e.g. `system_promoted`, `band_n_from_power_analysis`,
    `band_ece_upper_bound`, `band_ece_threshold`,
    `review_cadences_under_threshold`, `required_review_cadences`,
    `forward_band_monotonic`, `edge_survives_worst_book`,
    `edge_survives_shrink`, `selection_agreement_below_threshold`,
    `residual_correlation_below_threshold`, `major_counterargument`,
    `forward_evidence_days`, `price_drift_monitored`,
    `base_rate_published_both_tails`, `withdrawal_automatic_configured`) --
    this function never reaches into a store itself.

    Returns a LockVerdict. Never returns, computes, or implies a probability
    of winning: only a tier and the named criteria that were or were not
    satisfied.
    """
    combined = dict(scorecard)
    combined.update(evidence)
    inputs_hash = _canonical_hash(combined)

    if not combined.get("system_promoted", False):
        return LockVerdict(
            tier=TIER_NOT_PROMOTED, unmet=LOCK_CRITERIA_NAMES,
            reasons=("candidate is not drawn from a PROMOTED system",),
            inputs_hash=inputs_hash,
        )

    checks = {
        "from_promoted_system": bool(combined.get("system_promoted")),
        "band_n_from_power_analysis": bool(combined.get("band_n_from_power_analysis")),
        "band_ece_upper_bound_under_threshold": (
            combined.get("band_ece_upper_bound") is not None
            and combined.get("band_ece_threshold") is not None
            and combined["band_ece_upper_bound"] < combined["band_ece_threshold"]
            and combined.get("review_cadences_under_threshold", 0) >= combined.get(
                "required_review_cadences", 1)
        ),
        "forward_band_monotonicity": bool(combined.get("forward_band_monotonic")),
        "edge_survives_worst_book_and_shrink": bool(
            combined.get("edge_survives_worst_book")
            and combined.get("edge_survives_shrink")
        ),
        "two_systems_below_agreement_thresholds": bool(
            combined.get("selection_agreement_below_threshold")
            and combined.get("residual_correlation_below_threshold")
        ),
        "no_major_counterargument": not combined.get("major_counterargument", True),
        "forward_evidence_days": (
            combined.get("forward_evidence_days", 0) >= 90
        ),
        "price_drift_monitored": bool(combined.get("price_drift_monitored")),
        "base_rate_published_both_tails": bool(
            combined.get("base_rate_published_both_tails")
        ),
        "withdrawal_automatic": bool(
            combined.get("withdrawal_automatic_configured")
        ),
    }
    unmet = tuple(name for name in LOCK_CRITERIA_NAMES if not checks.get(name))

    if not unmet:
        return LockVerdict(
            tier=TIER_LOCK, unmet=(), reasons=("all LOCK criteria satisfied",),
            inputs_hash=inputs_hash,
        )
    tier = TIER_NEAR_MISS if len(unmet) <= 2 else TIER_NOT_ELIGIBLE
    reasons = tuple(f"unmet: {name}" for name in unmet)
    return LockVerdict(tier=tier, unmet=unmet, reasons=reasons,
                        inputs_hash=inputs_hash)
