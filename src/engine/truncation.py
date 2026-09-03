"""The truncation differential gate (G4's second leg).

docs/ARCHITECTURE_BETTING_ENGINE.md section 4 guard 6: "the CI-blocking
leakage gate is store-truncated-at-t equality, not live/store equality."
Section 5, G4: "the truncated-store differential is byte-equal on a sampled
corpus." This module is that gate: run the full waist (`src.engine.analyze
.analyze`) once at `t` and once at `t - 2h` for the same game, over a
sample of games, and require that the `t-2h` decision set be a function
ONLY of information available at `t-2h`.

The two decision sets are allowed to differ -- more information exists at
`t` than at `t-2h`, so a different edge, a different verdict, even a
different set of surviving selections is an ordinary and expected outcome.
What is NOT allowed is a difference that cannot be explained by a
provenance-recorded field arrival between `t-2h` and `t`. If field X caused
a selection's decision to change between the two runs, a provenance record
must show X arriving inside `(t-2h, t]`; if no such record exists, the
`t-2h` run must have read information it could not honestly have had --
which is leakage, full stop, and this module reports it as a FAIL, never a
warning.

This module does not itself build snapshots/boards from disk -- that is
`src.core.asof.as_of` and `src.board`'s job, both already point-in-time
disciplined. `TruncationSample` is the seam: a caller (a script, a test, or
`src.cli`'s `engine truncation` command) hands this module the already-built
`(snapshot, board)` pair at each instant plus the provenance arrivals it
recorded, and this module does the comparison and packages a
GateResult-compatible record for G4.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.engine.analyze import (
    DEFAULT_ADVERSARIES, DEFAULT_CONFIG, Analysis, EngineConfig, analyze,
)
from src.engine.snapshot import PriceBlindSnapshot, PricedBoard

# The DecisionRecord fields a differential actually compares. Anything not
# named here (e.g. `recorded_utc`, which legitimately differs because the
# two runs happen at different instants) is not a leakage signal.
_COMPARED_FIELDS = (
    "verdict", "market_key", "line", "price_american", "consensus_fair",
    "books_at_decision", "p_model", "edge_bps", "known_at_grade",
)


class TruncationError(ValueError):
    """A truncation-differential run was invoked with malformed inputs."""


@dataclass(frozen=True, slots=True)
class ArrivalRecord:
    """One provenance-recorded fact becoming knowable, from
    `src.core.asof`'s per-field `known_at`/`observed_utc`. `field` names the
    feature/board fact that arrived (e.g. `"home_probable_id"`,
    `"books_by_market:totals"`); `observed_utc` is when it became knowable.
    """

    field: str
    observed_utc: str


@dataclass(frozen=True, slots=True)
class TruncationSample:
    """One game's inputs at both instants, plus the arrivals between them.

    `t2h` and `t` are the ISO-8601 UTC instants this sample compares --
    named for the P7 packet's own convention (`t` the decision instant,
    `t2h` == `t - 2h`), not hardcoded to exactly two hours here so a caller
    can register other windows without renaming the module.
    """

    game_pk: str
    t2h: str
    t: str
    snapshot_t2h: PriceBlindSnapshot
    board_t2h: PricedBoard
    snapshot_t: PriceBlindSnapshot
    board_t: PricedBoard
    arrivals: tuple = ()  # tuple[ArrivalRecord, ...], observed anywhere


@dataclass(frozen=True, slots=True)
class TruncationDiff:
    game_pk: str
    selection_id: str
    system_id: str
    changed_fields: tuple  # field names that differ between the two runs
    at_t2h: Mapping[str, Any]
    at_t: Mapping[str, Any]
    attributable: bool
    causes: tuple  # ArrivalRecord.field values that explain the change

    def to_dict(self) -> dict:
        return {
            "game_pk": self.game_pk,
            "selection_id": self.selection_id,
            "system_id": self.system_id,
            "changed_fields": list(self.changed_fields),
            "at_t2h": dict(self.at_t2h),
            "at_t": dict(self.at_t),
            "attributable": self.attributable,
            "causes": list(self.causes),
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    """GateResult-compatible: same shape as `src.factory.gates.GateResult`
    (gate, passed, reasons, inputs_hash, `__bool__`), constructed here
    rather than imported so this module never has to reach into a private
    helper of `src.factory.gates` -- the two are structurally identical by
    contract, checked in tests/test_engine_truncation.py.
    """

    gate: str
    passed: bool
    reasons: tuple
    inputs_hash: str

    def __bool__(self) -> bool:
        return self.passed


@dataclass(frozen=True, slots=True)
class TruncationReport:
    sample_size: int
    diffs: tuple  # every TruncationDiff found, attributable or not
    leakage_failures: tuple  # the subset with attributable=False
    gate_result: GateResult

    def to_dict(self) -> dict:
        return {
            "sample_size": self.sample_size,
            "diffs": [d.to_dict() for d in self.diffs],
            "leakage_failures": [d.to_dict() for d in self.leakage_failures],
            "gate_result": {
                "gate": self.gate_result.gate,
                "passed": self.gate_result.passed,
                "reasons": list(self.gate_result.reasons),
                "inputs_hash": self.gate_result.inputs_hash,
            },
        }


def _canonical_hash(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _parse_utc(value: str):
    from datetime import datetime
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        raise TruncationError(f"timestamp {value!r} is not timezone-aware")
    return d


def _record_row(rec) -> dict:
    return {f: getattr(rec, f) for f in _COMPARED_FIELDS}


def _index_records(analysis: Analysis) -> dict:
    """Key by (selection_id, system_id) -- `supporting_systems` on a
    DecisionRecord is a list of exactly the one proposing system's id for
    every record `analyze()` currently emits (one system, one selection per
    record; see `docs/ENGINE_CONTRACT.md` section 4)."""
    out = {}
    for rec in analysis.records:
        systems = tuple(rec.supporting_systems or ())
        system_id = systems[0] if systems else ""
        out[(rec.selection_id, system_id)] = rec
    return out


def diff_one_game(sample: TruncationSample, *, systems: Iterable,
                   adversaries: Iterable = DEFAULT_ADVERSARIES,
                   config: EngineConfig = DEFAULT_CONFIG) -> tuple:
    """Run `analyze()` at both instants for one game and return the
    `TruncationDiff`s between them (empty tuple if nothing changed)."""
    systems = tuple(systems)
    adversaries = tuple(adversaries)

    t2h_dt = _parse_utc(sample.t2h)
    t_dt = _parse_utc(sample.t)
    if t2h_dt >= t_dt:
        raise TruncationError(
            f"t2h={sample.t2h!r} must be strictly before t={sample.t!r}")

    analysis_t2h = analyze(sample.snapshot_t2h, sample.board_t2h,
                            systems=systems, adversaries=adversaries,
                            config=config)
    analysis_t = analyze(sample.snapshot_t, sample.board_t,
                          systems=systems, adversaries=adversaries,
                          config=config)

    rows_t2h = _index_records(analysis_t2h)
    rows_t = _index_records(analysis_t)

    # Arrivals strictly inside (t2h, t] -- anything at or before t2h was
    # already available to the t2h run and explains nothing about a change;
    # anything after t is out of scope for this pair.
    in_window = tuple(
        a for a in sample.arrivals
        if t2h_dt < _parse_utc(a.observed_utc) <= t_dt
    )
    causes = tuple(sorted({a.field for a in in_window}))

    diffs: list = []
    for key in sorted(set(rows_t2h) | set(rows_t), key=lambda k: (k[0], k[1])):
        selection_id, system_id = key
        rec_t2h = rows_t2h.get(key)
        rec_t = rows_t.get(key)
        row_t2h = _record_row(rec_t2h) if rec_t2h is not None else None
        row_t = _record_row(rec_t) if rec_t is not None else None
        if row_t2h == row_t:
            continue
        changed = []
        if row_t2h is None:
            changed = ["__appeared_at_t__"]
        elif row_t is None:
            changed = ["__vanished_at_t__"]
        else:
            changed = sorted(f for f in _COMPARED_FIELDS
                              if row_t2h.get(f) != row_t.get(f))
        diffs.append(TruncationDiff(
            game_pk=sample.game_pk,
            selection_id=selection_id,
            system_id=system_id,
            changed_fields=tuple(changed),
            at_t2h=row_t2h or {},
            at_t=row_t or {},
            attributable=bool(in_window),
            causes=causes,
        ))
    return tuple(diffs)


def truncation_differential(samples: Iterable[TruncationSample], *,
                             systems: Iterable,
                             adversaries: Iterable = DEFAULT_ADVERSARIES,
                             config: EngineConfig = DEFAULT_CONFIG,
                             ) -> TruncationReport:
    """Run the differential over a sample of games and produce a
    GateResult-compatible record for G4.

    Passes only when EVERY diff found across the whole sample is
    attributable to at least one provenance arrival in its game's
    `(t-2h, t]` window. A single unattributable diff on a single game is a
    gate FAIL for the whole sampled corpus -- "byte-equal on a sampled
    corpus" (section 5, G4) does not average.
    """
    samples = tuple(samples)
    if not samples:
        raise TruncationError("truncation_differential requires at least "
                               "one TruncationSample")

    all_diffs: list = []
    for sample in samples:
        all_diffs.extend(diff_one_game(sample, systems=systems,
                                        adversaries=adversaries,
                                        config=config))

    leakage = tuple(d for d in all_diffs if not d.attributable)

    inputs = {
        "sample_size": len(samples),
        "games": sorted(s.game_pk for s in samples),
        "diff_count": len(all_diffs),
    }
    inputs_hash = _canonical_hash(inputs)

    if leakage:
        reasons = tuple(
            f"game={d.game_pk} selection={d.selection_id} "
            f"system={d.system_id} changed {list(d.changed_fields)} "
            "with no provenance arrival in (t-2h, t] to explain it: LEAKAGE"
            for d in leakage
        )
        gate = GateResult(gate="G4", passed=False, reasons=reasons,
                           inputs_hash=inputs_hash)
    else:
        reasons = (
            f"{len(samples)} game(s) sampled, {len(all_diffs)} diff(s) "
            "found, every diff attributable to a provenance arrival in "
            "(t-2h, t]",
        )
        gate = GateResult(gate="G4", passed=True, reasons=reasons,
                           inputs_hash=inputs_hash)

    return TruncationReport(
        sample_size=len(samples), diffs=tuple(all_diffs),
        leakage_failures=leakage, gate_result=gate,
    )
