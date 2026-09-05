"""The strategy-family lifecycle state machine: CANDIDATE -> FORWARD_TESTING
-> {RETIRED -> REPLACED} / PROMOTED_GATED.

See docs/FACTORY_LIFECYCLE.md for the full design and the exact evidence
condition behind every transition; this module is the implementation of
that document only -- it does not invent a rule the doc does not already
state. docs/FACTORY_SCALE_DESIGN.md section 4 (retire/mutate/replace) and
section 5 (scheduled retest) are the source of truth this mirrors.

WHY THIS IS PURE FUNCTIONS OVER EXPLICIT EVIDENCE RECORDS
-----------------------------------------------------------
A lifecycle transition is a claim about evidence ("this family cleared the
battery", "this retest failed CSCV/SPA"). If the function that makes that
claim can also go fetch the evidence itself, a bug in the fetch is
indistinguishable from a bug in the claim, and no test can pin either one
without a live store. So every function below takes the evidence as an
explicit, frozen dataclass and returns a new `LifecycleEntry` (or raises
`LifecycleError`) -- no I/O, no clock read (callers pass `now` explicitly,
defaulting only at the call site), no disk. The ONE exception is
`append_audit`/`read_audit`, which are the append-only JSONL audit log the
task requires; they are deliberately isolated at the bottom of this file so
"no I/O beyond the audit log" is visible at a glance.

WHY BANKROLL/ROI HAS NO FIELD ANYWHERE IN THIS FILE
-----------------------------------------------------
`docs/FACTORY_LIFECYCLE.md` states the owner rule: no promotion on bankroll
alone. The strongest way to enforce "alone" is to make it structurally
impossible to enforce anything else -- there is no ROI/bankroll/price field
on `PromotionGate`, `BatteryEvidence`, `RetestResult` or any other evidence
record here. `promote()` cannot be tricked into reading a bankroll number
because there is nothing in its input type for a bankroll number to occupy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

from src.evolab.overlap import FAMILY_THRESHOLD, jaccard
from src.evolab.sweep import DEFAULT_MIN_SELECTIONS, DEFAULT_N_BLOCKS

# -- States -------------------------------------------------------------

CANDIDATE = "CANDIDATE"
FORWARD_TESTING = "FORWARD_TESTING"
RETIRED = "RETIRED"
REPLACED = "REPLACED"
PROMOTED_GATED = "PROMOTED_GATED"

STATES = (CANDIDATE, FORWARD_TESTING, RETIRED, REPLACED, PROMOTED_GATED)


class LifecycleError(RuntimeError):
    """Raised when a transition cannot be justified by the evidence given."""


def _now(now: Optional[datetime]) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _hash(payload: Mapping) -> str:
    """sha256 of `payload` under canonical JSON -- mirrors
    src/factory/gates.py's `_canonical_hash` so an evidence_ref is
    reproducible from the same logical evidence regardless of dict order."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# -- Evidence records -----------------------------------------------------

@dataclass(frozen=True)
class PreRegistration:
    """A hypothesis written down before any battery result exists. Mirrors
    src/research/funnel.py's mechanism requirement: no reason stated for why
    the market should misprice this, no admission."""

    mechanism: str
    registered_at: str

    def __post_init__(self):
        if not isinstance(self.mechanism, str) or not self.mechanism.strip():
            raise LifecycleError(
                "PreRegistration.mechanism is required and non-empty -- a "
                "hypothesis with no stated reason does not get admitted")


@dataclass(frozen=True)
class BatteryEvidence:
    """Evidence required to leave CANDIDATE for FORWARD_TESTING (design
    section 4's eligibility check, read forward: eligible == cleared)."""

    pre_registered: bool
    replication_passed: bool
    battery_passed: bool

    def missing(self) -> tuple:
        names = ("pre_registered", "replication_passed", "battery_passed")
        return tuple(n for n in names if not getattr(self, n))


@dataclass(frozen=True)
class PromotionGate:
    """Every named flag must be True for `promote()` to succeed. There is
    deliberately no field here (or anywhere in this module) an ROI/bankroll
    number could occupy -- see the module docstring."""

    pre_registered: bool
    replication_passed: bool
    battery_passed: bool
    cscv_passed: bool
    spa_passed: bool
    ceiling_cleared: bool
    forward_ledger_n: int

    FLAGS = ("pre_registered", "replication_passed", "battery_passed",
             "cscv_passed", "spa_passed", "ceiling_cleared")

    def __post_init__(self):
        if not isinstance(self.forward_ledger_n, int) or \
                isinstance(self.forward_ledger_n, bool) or \
                self.forward_ledger_n < 0:
            raise LifecycleError(
                "PromotionGate.forward_ledger_n must be a non-negative int, "
                f"got {self.forward_ledger_n!r}")

    def missing_flags(self) -> tuple:
        return tuple(n for n in self.FLAGS if not getattr(self, n))

    @property
    def all_evidence_true(self) -> bool:
        return not self.missing_flags()


@dataclass(frozen=True)
class RetestResult:
    """Verdict of one scheduled retest (an ordinary run_sweep + CSCV/SPA
    pass, unchanged machinery, per design section 5). `passed=False` here
    means the gate failed -- a merely bad recent block with a still-passing
    gate is NOT this; the caller passes the actual gate verdict, this
    dataclass does not compute one."""

    passed: bool
    block_index: int
    reference: str  # e.g. a SweepReport content hash / path


@dataclass(frozen=True)
class ReplacementEvidence:
    """Fresh, pre-registered evidence for the genome/mutation that closes a
    coverage gap left by a family that lost its last passing member."""

    pre_registered: bool
    battery_passed: bool
    candidate_strategy_id: str
    retirement_evidence_ref: str

    def missing(self) -> tuple:
        names = ("pre_registered", "battery_passed")
        return tuple(n for n in names if not getattr(self, n))


# -- The entry ------------------------------------------------------------

@dataclass(frozen=True)
class LifecycleEntry:
    """One family's current lifecycle state plus its decision set (for the
    admission correlation-with-retired-family check) and its transition
    history (append-only tuple -- a new entry is returned, never mutated)."""

    family_id: str
    state: str
    decision_set: frozenset
    history: tuple = field(default_factory=tuple)

    def _advance(self, to_state: str, trigger: str, evidence: Mapping,
                 now: Optional[datetime]) -> "LifecycleEntry":
        record = _transition_record(self.family_id, self.state, to_state,
                                     trigger, evidence, now)
        return LifecycleEntry(family_id=self.family_id, state=to_state,
                              decision_set=self.decision_set,
                              history=self.history + (record,))


def _transition_record(family_id: str, from_state: str, to_state: str,
                       trigger: str, evidence: Mapping,
                       now: Optional[datetime]) -> dict:
    return {
        "family_id": family_id,
        "from_state": from_state,
        "to_state": to_state,
        "trigger": trigger,
        "evidence_ref": _hash(evidence),
        "timestamp": _now(now).isoformat(),
    }


def _evidence_dict(evidence) -> dict:
    return asdict(evidence)


# -- Transitions ------------------------------------------------------------

def admit(family_id: str, decision_set: "frozenset[str]",
          pre_registration: PreRegistration, *,
          retired_families: Mapping[str, "frozenset[str]"] = None,
          now: Optional[datetime] = None) -> LifecycleEntry:
    """New CANDIDATE entry, or LifecycleError.

    Refuses a candidate whose decision set is Jaccard>=FAMILY_THRESHOLD with
    ANY currently-RETIRED family's decision set -- a near-duplicate of
    something already killed does not get to re-enter as fresh evidence
    (docs/FACTORY_LIFECYCLE.md, Admission).
    """
    if not isinstance(family_id, str) or not family_id.strip():
        raise LifecycleError("family_id must be a non-empty string")
    decision_set = frozenset(decision_set)
    for retired_id, retired_set in (retired_families or {}).items():
        j = jaccard(decision_set, frozenset(retired_set))
        if j >= FAMILY_THRESHOLD:
            raise LifecycleError(
                f"{family_id}: refused -- Jaccard={j:.3f} >= "
                f"{FAMILY_THRESHOLD} with RETIRED family {retired_id!r}; a "
                "near-duplicate of a retired family cannot be re-admitted")
    evidence = _evidence_dict(pre_registration)
    entry = LifecycleEntry(family_id=family_id, state=CANDIDATE,
                           decision_set=decision_set)
    return entry._advance(CANDIDATE, "admit", evidence, now)


def begin_forward_testing(entry: LifecycleEntry, evidence: BatteryEvidence,
                          *, now: Optional[datetime] = None) -> LifecycleEntry:
    """CANDIDATE -> FORWARD_TESTING, or LifecycleError naming what's missing."""
    if entry.state != CANDIDATE:
        raise LifecycleError(
            f"{entry.family_id}: begin_forward_testing requires CANDIDATE, "
            f"currently {entry.state}")
    missing = evidence.missing()
    if missing:
        raise LifecycleError(
            f"{entry.family_id}: refused -- missing evidence {missing}")
    return entry._advance(FORWARD_TESTING, "begin_forward_testing",
                          _evidence_dict(evidence), now)


def promote(entry: LifecycleEntry, gate: PromotionGate, *,
           min_forward_n: int = DEFAULT_MIN_SELECTIONS,
           now: Optional[datetime] = None) -> LifecycleEntry:
    """FORWARD_TESTING -> PROMOTED_GATED. Structurally unable to succeed
    without every named PromotionGate flag True AND forward_ledger_n at or
    above the floor -- see PromotionGate and the module docstring for why
    ROI/bankroll cannot substitute for any of these."""
    if entry.state != FORWARD_TESTING:
        raise LifecycleError(
            f"{entry.family_id}: promote requires FORWARD_TESTING, "
            f"currently {entry.state}")
    reasons = list(gate.missing_flags())
    if gate.forward_ledger_n < min_forward_n:
        reasons.append(
            f"forward_ledger_n {gate.forward_ledger_n} < floor {min_forward_n}")
    if reasons:
        raise LifecycleError(
            f"{entry.family_id}: refused promotion -- {reasons}")
    return entry._advance(PROMOTED_GATED, "promote", _evidence_dict(gate),
                          now)


def retire(entry: LifecycleEntry, retest_result: RetestResult, *,
          family_still_has_passing_member: bool,
          now: Optional[datetime] = None) -> LifecycleEntry:
    """-> RETIRED. Requires BOTH: the scheduled retest failed CSCV/SPA, AND
    the family's unique-wager coverage survives elsewhere (design section 4's
    `retire` row, verbatim -- a family with no other passing coverage is a
    `replace` case, not a plain retirement)."""
    if entry.state not in (CANDIDATE, FORWARD_TESTING):
        raise LifecycleError(
            f"{entry.family_id}: retire requires CANDIDATE or "
            f"FORWARD_TESTING, currently {entry.state}")
    reasons = []
    if retest_result.passed:
        reasons.append("most recent scheduled retest passed -- not falsified")
    if not family_still_has_passing_member:
        reasons.append(
            "no still-passing family member covers this decision set -- "
            "this is a replace() case, not a plain retirement")
    if reasons:
        raise LifecycleError(f"{entry.family_id}: refused retire -- {reasons}")
    evidence = dict(_evidence_dict(retest_result),
                    family_still_has_passing_member=family_still_has_passing_member)
    return entry._advance(RETIRED, "retire", evidence, now)


def replace(entry: LifecycleEntry, evidence: ReplacementEvidence, *,
           lost_last_passing_member: bool,
           now: Optional[datetime] = None) -> LifecycleEntry:
    """RETIRED -> REPLACED. Requires the family to have genuinely lost its
    last passing member (a real coverage gap, separate from retire()'s
    family_still_has_passing_member so the two flags can never be conflated)
    AND a fresh, pre-registered battery pass for the replacement genome."""
    if entry.state != RETIRED:
        raise LifecycleError(
            f"{entry.family_id}: replace requires RETIRED, currently "
            f"{entry.state}")
    reasons = list(evidence.missing())
    if not lost_last_passing_member:
        reasons.append(
            "lost_last_passing_member is False -- no coverage gap to close, "
            "nothing to replace")
    if reasons:
        raise LifecycleError(f"{entry.family_id}: refused replace -- {reasons}")
    payload = dict(_evidence_dict(evidence),
                  lost_last_passing_member=lost_last_passing_member)
    return entry._advance(REPLACED, "replace", payload, now)


# -- Scheduled retest cadence ------------------------------------------------

def retest_due(games_since_last_retest: int,
              block_width: int = DEFAULT_N_BLOCKS) -> bool:
    """True once enough new game-days have accumulated to form one full new
    block of the existing block structure (design section 5) -- wall-clock
    time never enters this calculation, only accumulated evidence does."""
    if not isinstance(games_since_last_retest, int) or \
            isinstance(games_since_last_retest, bool) or \
            games_since_last_retest < 0:
        raise LifecycleError(
            "games_since_last_retest must be a non-negative int, got "
            f"{games_since_last_retest!r}")
    if not isinstance(block_width, int) or block_width <= 0:
        raise LifecycleError(f"block_width must be a positive int, got "
                             f"{block_width!r}")
    return games_since_last_retest >= block_width


# -- Audit log: the one I/O this module performs ----------------------------

def append_audit(path, record: Mapping) -> None:
    """Append one transition record as a JSON line. Append-only: never seeks,
    never truncates, never rewrites an existing line -- a transition once
    logged is permanent, per the audit-trail requirement."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(record), sort_keys=True, ensure_ascii=True)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_audit(path) -> list:
    """Every record in the audit log at `path`, in append order. Empty list
    for a path that does not exist yet -- an audit log with nothing written
    is a legal, if uninteresting, state, not an error."""
    target = Path(path)
    if not target.exists():
        return []
    out = []
    with open(target, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
