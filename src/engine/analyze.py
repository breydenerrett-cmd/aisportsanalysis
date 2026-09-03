"""The waist: `analyze(snapshot, board, systems, adversaries, t) -> Analysis`.

Five phases, per docs/ARCHITECTURE_BETTING_ENGINE.md section 3 and
synthesis-judge.md 4.2. See docs/ENGINE_CONTRACT.md for the full contract.
This module is PURE: no I/O, no clock read, no randomness, no globals, no
model call. It cannot tell whether it is running live tonight or replaying
2023-04-11 -- the only inputs it ever consults are its own arguments.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Protocol

from src.engine.snapshot import PriceBlindSnapshot, PricedBoard
from src.ledger.records import DecisionRecord

ENGINE_VERSION = "engine-1"


# ---------------------------------------------------------------------------
# PROPOSE-phase types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Proposal:
    """One system's belief about one market/side. Never a price, never bps."""

    system_id: str
    system_version: str
    market_key: str
    side: str
    subject_kind: str | None = None
    subject_id: str | None = None
    line: str | None = None
    p_model: float | None = None
    thesis: str = ""
    evidence: tuple = ()


class AnalysisSystem(Protocol):
    id: str
    version: str
    spec_hash: str
    declared_markets: tuple
    declared_inputs: tuple
    min_grade: str
    expected_selection_rate: float

    def propose(self, view: PriceBlindSnapshot) -> tuple:
        ...


# ---------------------------------------------------------------------------
# ATTACK-phase types
# ---------------------------------------------------------------------------

FATAL = "FATAL"
MAJOR = "MAJOR"
MINOR = "MINOR"
_SEVERITIES = frozenset({FATAL, MAJOR, MINOR})


@dataclass(frozen=True, slots=True)
class Counterargument:
    adversary_id: str
    cause: str
    severity: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES:
            raise ValueError(
                f"severity={self.severity!r} must be one of "
                f"{sorted(_SEVERITIES)}")


class Adversary(Protocol):
    id: str

    def attack(self, candidate: "Candidate", snapshot: PriceBlindSnapshot,
               board: PricedBoard) -> tuple:
        ...


# ---------------------------------------------------------------------------
# Intermediate candidate (PROJECT output, ATTACK/RATE input)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Candidate:
    proposal: Proposal
    selection_id: str
    consensus_fair: float | None
    books_at_decision: int
    friction: dict
    price_american: int | None
    edge_bps: int | None
    counterarguments: tuple = ()
    rating: dict | None = None


@dataclass(frozen=True, slots=True)
class Analysis:
    """The full result of one `analyze()` call: 0..N ranked DecisionRecords.

    Empty is a normal answer -- a board where every proposal was vetoed, or
    where no system proposed anything, produces `records == ()`, not an
    error.
    """

    game_pk: str
    t: str
    records: tuple = ()


class EngineConfig:
    """Pinned knobs analyze() reads. No field here may be a clock, a random
    seed source, or a network handle -- config is data, not a side channel."""

    def __init__(self, *, min_books: int = 1, devig_method: str = "proportional",
                 friction_bps: int = 0):
        self.min_books = min_books
        self.devig_method = devig_method
        self.friction_bps = friction_bps  # a flat cost, in bps, netted from edge


DEFAULT_CONFIG = EngineConfig()
DEFAULT_ADVERSARIES: tuple = ()


# ---------------------------------------------------------------------------
# The waist
# ---------------------------------------------------------------------------

def analyze(snapshot: PriceBlindSnapshot, board: PricedBoard, *,
            systems: Iterable, adversaries: Iterable | None = None,
            config: EngineConfig = DEFAULT_CONFIG,
            registry_fingerprint: str = "",
            frame_fingerprint: str | None = None) -> Analysis:
    """PROPOSE -> PROJECT -> ATTACK -> RATE -> RANK. See module docstring.

    `adversaries` omitted (the default, `None`) resolves to
    `src.engine.adversaries.DEFAULT_ADVERSARIES` -- the registered v1
    roster (docs/ENGINE_CONTRACT.md section 5) -- via a lazy import (this
    module's own `DEFAULT_ADVERSARIES` stays `()`; `adversaries.py` imports
    FROM `analyze.py`, so importing it back at module scope here would be
    circular). A caller that wants NO adversaries at all still has that
    explicit-argument path: pass `adversaries=()` and the roster is never
    consulted.
    """
    if adversaries is None:
        from src.engine.adversaries import (
            DEFAULT_ADVERSARIES as _registered_default_adversaries,
        )
        adversaries = _registered_default_adversaries

    if snapshot.game_pk != board.game_pk:
        raise ValueError(
            f"snapshot.game_pk={snapshot.game_pk!r} != "
            f"board.game_pk={board.game_pk!r}: analyze() must be handed the "
            "price-blind snapshot and the priced board for the SAME game")

    systems = tuple(systems)
    adversaries = tuple(adversaries)

    # 1. PROPOSE -- each system sees ONLY the price-blind snapshot.
    proposals: list[Proposal] = []
    for system in systems:
        for proposal in system.propose(snapshot):
            proposals.append(proposal)

    # 2. PROJECT -- price every proposal against EVERY selection on the
    # board its thesis covers. A proposal that names a market/side without a
    # subject/line covers every selection on the board sharing that
    # market_key and side (e.g. every line of `totals`/`over`); a proposal
    # that names a subject and/or line covers only selections matching those
    # fields too.
    candidates: list[Candidate] = []
    for proposal in proposals:
        for selection_id in board.selections():
            rows = board.rows_for(selection_id)
            if not rows:
                continue
            row = rows[0]
            if row.market_key != proposal.market_key:
                continue
            if row.side != proposal.side:
                continue
            if proposal.subject_id is not None and \
                    row.subject_id != proposal.subject_id:
                continue
            if proposal.line is not None and row.line != proposal.line:
                continue

            consensus = board.consensus(
                selection_id, min_books=config.min_books,
                method=config.devig_method)
            best = board.best(selection_id)
            friction = board.friction(selection_id, as_of_utc=board.t)

            edge_bps = None
            if consensus is not None and proposal.p_model is not None:
                raw_edge = proposal.p_model - consensus.fair_probability
                edge_bps = int(round(raw_edge * 10_000)) - config.friction_bps

            candidates.append(Candidate(
                proposal=proposal,
                selection_id=selection_id,
                consensus_fair=(consensus.fair_probability
                                if consensus is not None else None),
                books_at_decision=(consensus.n_books
                                   if consensus is not None else 0),
                friction={
                    "vig": friction.vig,
                    "book_count": friction.book_count,
                    "staleness_seconds": friction.staleness_seconds,
                    "dispersion": friction.dispersion,
                },
                price_american=(best.price_american if best else None),
                edge_bps=edge_bps,
            ))

    # 3. ATTACK -- adversaries may veto with a registered cause. FATAL
    # removes the candidate from RATE/RANK and the counterargument is kept
    # on the record (never silently dropped).
    survivors: list[Candidate] = []
    for cand in candidates:
        cargs: list[Counterargument] = []
        for adversary in adversaries:
            for cause in adversary.attack(cand, snapshot, board):
                cargs.append(cause)
        cand = replace(cand, counterarguments=tuple(cargs))
        if any(c.severity == FATAL for c in cargs):
            continue  # vetoed: recorded below as verdict=no_play
        survivors.append(cand)

    # 4. RATE -- Bet Rating: probability quality AND price quality, kept as
    # two SEPARATE numbers (the Two-Ledger rule extends here: a system's
    # calibration is never allowed to blend with the price it happened to
    # get). Neither number is published as "edge"; both are internal fields
    # on `rating`.
    rated: list[Candidate] = []
    for cand in survivors:
        prob_quality = _probability_quality(cand)
        price_quality = _price_quality(cand)
        rating = {
            "probability_quality": prob_quality,
            "price_quality": price_quality,
        }
        rated.append(replace(cand, rating=rating))

    # 5. RANK -- deterministic total order. No tie resolved by chance: sort
    # key is a plain tuple of already-computed numbers and strings.
    def _rank_key(c: Candidate):
        edge = c.edge_bps if c.edge_bps is not None else -(10 ** 9)
        return (-edge, c.selection_id, c.proposal.system_id)

    rated.sort(key=_rank_key)

    records = tuple(
        _to_decision_record(
            cand, snapshot=snapshot, board=board,
            registry_fingerprint=registry_fingerprint,
            frame_fingerprint=frame_fingerprint,
            verdict=("play" if cand.price_american is not None
                     else "market_unavailable"))
        for cand in rated
    )
    return Analysis(game_pk=snapshot.game_pk, t=snapshot.t, records=records)


def _probability_quality(cand: Candidate) -> float | None:
    """A model-only quality score: distance from a coin flip, in the
    system's own stated probability. Never mixes in price."""
    p = cand.proposal.p_model
    if p is None:
        return None
    return abs(p - 0.5) * 2.0


def _price_quality(cand: Candidate) -> float | None:
    """A price-only quality score: how much of the board's own de-vigged
    edge (before friction) this quote captures. Never mixes in the model's
    own confidence."""
    if cand.consensus_fair is None or cand.price_american is None:
        return None
    from src.core import odds as odds_math
    implied = odds_math.american_to_probability(cand.price_american)
    return cand.consensus_fair - implied


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def _to_decision_record(cand: Candidate, *, snapshot: PriceBlindSnapshot,
                         board: PricedBoard, registry_fingerprint: str,
                         frame_fingerprint: str | None,
                         verdict: str) -> DecisionRecord:
    proposal = cand.proposal
    snap_fp = snapshot.fingerprint or hashlib.sha256(
        _canonical_json({"game_pk": snapshot.game_pk, "t": snapshot.t,
                         "features": snapshot.features}).encode()
    ).hexdigest()
    no_real_read = False
    grade = "D"
    if snapshot.assumption_exposure:
        grades = {k.split(":", 1)[0] for k in snapshot.assumption_exposure}
        for g in ("A", "B", "C", "D"):
            if grades == {g}:
                grade = g
                break
        else:
            grade = sorted(grades)[-1] if grades else "D"
    else:
        # assumption_exposure is empty. `PriceBlindSnapshot.from_asof` folds
        # EVERY observed as_of field into assumption_exposure regardless of
        # its own grade (src/engine/snapshot.py), so an empty exposure never
        # means "read some real fields, all grade A" -- it can only mean
        # nothing was read at all: either no as_of call ever happened (no
        # game_pk to key one on -- src.engine.glue's game_pk/event_id gap),
        # or one DID happen and found zero matching rows for this game_pk at
        # this t (e.g. a 2023-24 game_pk against forward stores that did not
        # exist yet, with no reproducible src.engine.features value either).
        # Neither case is evidence of anything; grading either A would
        # assert a provenance this snapshot does not have. Fail closed to D
        # in both, and say which one happened in the counterargument detail.
        grade = "D"
        no_real_read = True

    row = board.rows_for(cand.selection_id)
    market_key = row[0].market_key if row else proposal.market_key
    line = row[0].line if row else proposal.line

    evidence = list(proposal.evidence)
    counterarguments = [
        {"adversary_id": c.adversary_id, "cause": c.cause,
         "severity": c.severity, "detail": c.detail}
        for c in cand.counterarguments
    ]
    if no_real_read:
        if getattr(snapshot, "asof_read", False):
            detail = ("an as_of read occurred for this snapshot but matched "
                       "zero fields (no forward-store row for this game_pk "
                       "at t, and no reproducible src.engine.features value "
                       "either); known_at_grade forced to D rather than "
                       "assumed A")
        else:
            detail = ("no as_of read occurred for this snapshot (no game_pk "
                       "to key one on); known_at_grade forced to D rather "
                       "than assumed A")
        counterarguments.append({
            "adversary_id": "engine",
            "cause": "no_asof_read:known_at_grade_downgraded",
            "severity": MAJOR,
            "detail": detail,
        })
    if verdict == "play" and not evidence and not counterarguments:
        # DecisionRecord requires one of the two non-empty on a play
        # (synthesis-judge 4.2); a system that proposed with no evidence at
        # all still names its own thesis so the record is never silently
        # unsupported.
        evidence = [proposal.thesis or f"system:{proposal.system_id}"]

    return DecisionRecord(
        engine_version=ENGINE_VERSION,
        system_id=proposal.system_id,
        system_version=proposal.system_version,
        registry_fingerprint=registry_fingerprint,
        frame_fingerprint=frame_fingerprint,
        snapshot_fingerprint=snap_fp,
        game_pk=(int(snapshot.game_pk) if str(snapshot.game_pk).isdigit()
                 else None),
        event_id=str(snapshot.game_pk),
        decision_utc=snapshot.t,
        point_class=snapshot.point_class,
        information_time=snapshot.t,
        recorded_utc=snapshot.t,
        verdict=verdict,
        selection_id=cand.selection_id,
        market_key=market_key,
        line=line,
        book=(board.best(cand.selection_id).book
              if board.best(cand.selection_id) else None),
        price_american=cand.price_american,
        consensus_fair=cand.consensus_fair,
        books_at_decision=cand.books_at_decision,
        friction=cand.friction,
        p_model=proposal.p_model,
        p_model_interval=None,
        edge_bps=cand.edge_bps,
        price_improvement_bps=None,
        rating=cand.rating,
        thesis=proposal.thesis or None,
        evidence=evidence,
        counterarguments=counterarguments,
        supporting_systems=[proposal.system_id],
        refusal_reason=None,
        assumption_exposure=dict(snapshot.assumption_exposure),
        stake_units=0.0,
        known_at_grade=grade,
    )
