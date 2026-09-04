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
from src.ledger.records import (
    DecisionRecord,
    PROBABILITY_PROVENANCE_MARKET_DERIVED,
    PROBABILITY_PROVENANCE_MODEL_DERIVED,
    PROBABILITY_PROVENANCE_VALUES,
)
from src.ledger.records import VALUE_BASIS_PRICE_STANDING_ONLY as _VALUE_BASIS_PRICE_STANDING_ONLY

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
    # N2/honesty fix (2026-09-04): REQUIRED, no default -- see
    # src.ledger.records's PROBABILITY_PROVENANCE_* block. A system cannot
    # propose without naming where its p_model (or its absence) came from.
    p_model_provenance: str
    subject_kind: str | None = None
    subject_id: str | None = None
    line: str | None = None
    p_model: float | None = None
    thesis: str = ""
    evidence: tuple = ()
    # The post-game predicates this proposal's reasoning promises, built at
    # PROPOSE time by `src.engine.mechanism_predicates.predicates_for` and
    # carried through onto the frozen DecisionRecord. `()` for a system that
    # makes no falsifiable mechanism claim -- a null control, the
    # market-derived republisher -- which is the honest report, not a gap.
    mechanism_predicates: tuple = ()

    def __post_init__(self) -> None:
        if self.p_model_provenance not in PROBABILITY_PROVENANCE_VALUES:
            raise ValueError(
                f"p_model_provenance={self.p_model_provenance!r} must be "
                f"one of {sorted(PROBABILITY_PROVENANCE_VALUES)}"
            )


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

# Honest probabilities: an evolab genome (or any other system) makes a
# directional pick with NO calibrated probability -- `Proposal.p_model` is
# `None`, not a value analyze() may invent a default for. A candidate built
# from such a proposal is a PRICE-STANDING-ONLY candidate: RATE never
# fabricates a Bet Rating for it (there is nothing calibrated to rate), and
# its DecisionRecord names, in `value_basis`, exactly what its selection
# rested on instead of a probability -- here, the board's own consensus/
# price standing at decision time. This is the ONLY value_basis this module
# assigns; a record whose proposal DID carry a p_model gets `value_basis =
# None` (its value basis is already the edge_bps/p_model pair -- "the
# existing value projection" the task distinguishes this from).
#
# N2/honesty fix (2026-09-04): the condition this basis applies under has
# widened from "p_model is None" to "p_model_provenance != model_derived" --
# a placeholder or market_derived p_model is no less price-standing-only
# than no p_model at all, since none of the three is independent of the
# price edge_bps would otherwise diff it against. The constant itself now
# lives in src.ledger.records (DecisionRecord.from_row's legacy backfill
# needs it too, and records.py cannot import analyze.py without a cycle);
# re-exported here under its original name for every existing importer.
VALUE_BASIS_PRICE_STANDING_ONLY = _VALUE_BASIS_PRICE_STANDING_ONLY


# ---------------------------------------------------------------------------
# The waist
# ---------------------------------------------------------------------------

def analyze(snapshot: PriceBlindSnapshot, board: PricedBoard, *,
            systems: Iterable, adversaries: Iterable | None = None,
            config: EngineConfig = DEFAULT_CONFIG,
            registry_fingerprint: str = "",
            frame_fingerprint: str | None = None,
            recorded_utc: str | None = None,
            record_provenance: str | None = None) -> Analysis:
    """PROPOSE -> PROJECT -> ATTACK -> RATE -> RANK. See module docstring.

    `adversaries` omitted (the default, `None`) resolves to
    `src.engine.adversaries.DEFAULT_ADVERSARIES` -- the registered v1
    roster (docs/ENGINE_CONTRACT.md section 5) -- via a lazy import (this
    module's own `DEFAULT_ADVERSARIES` stays `()`; `adversaries.py` imports
    FROM `analyze.py`, so importing it back at module scope here would be
    circular). A caller that wants NO adversaries at all still has that
    explicit-argument path: pass `adversaries=()` and the roster is never
    consulted.

    `recorded_utc`/`record_provenance` (B1, slice-review-2026-09-03): this
    module stays PURE -- it never reads a clock -- so it cannot itself know
    the real wall-clock instant a record is written or whether the caller
    is live or replaying. A caller that actually writes to the ledger
    passes both explicitly, computed from its own clock read
    (`src.engine.slate.run_slate` is the one production caller that does).
    Omitted (the default, `None`), `recorded_utc` falls back to
    `snapshot.t` -- the historical, still-unfalsifiable behavior -- for any
    caller (a test, the S3 replay driver, the truncation gate) that has no
    write instant of its own to report; `record_provenance` stays `None`
    in that case, honestly recording that this record carries no
    write-time evidence either way.
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

            # The MARKET_DERIVED identity map (docs/PREREG_CALIBRATED_
            # PROBABILITY.md §2-3): a `market_derived` proposal cannot know
            # its own p_model at PROPOSE time -- PriceBlindSnapshot has no
            # price field at all -- so it proposes with p_model=None and
            # PROJECT fills it in here, per selection, as EXACTLY this same
            # `consensus.fair_probability` object: zero fitted parameters,
            # no recalibration intercept, nothing but the identity. Using
            # the very same float PROJECT already computed for
            # `consensus_fair` below (never a second de-vig call) is what
            # makes the identity hold to full float precision by
            # construction, not by coincidence -- see
            # tests/test_engine_analyze.py's identity test and §6.5's named
            # wiring-failure risk (a second de-vig implementation drifting
            # apart from this one). Undefined consensus (fewer than
            # `min_books` qualifying books) leaves p_model honestly None --
            # never a 0.5 default, matching M7's consensus-undefined guard.
            effective_proposal = proposal
            if proposal.p_model_provenance == PROBABILITY_PROVENANCE_MARKET_DERIVED:
                effective_proposal = replace(
                    proposal,
                    p_model=(consensus.fair_probability
                             if consensus is not None else None),
                )

            # N2/honesty fix: edge is only ever a real measurement when the
            # probability is independent of the price it is diffed against
            # -- model_derived, and nothing else. A placeholder constant, a
            # probability computed FROM these same prices, or no
            # probability at all must never produce an edge_bps, on pain of
            # DecisionRecord.__post_init__ raising below (impossible, not
            # merely discouraged).
            edge_bps = None
            if (effective_proposal.p_model_provenance == PROBABILITY_PROVENANCE_MODEL_DERIVED
                    and consensus is not None and effective_proposal.p_model is not None):
                raw_edge = effective_proposal.p_model - consensus.fair_probability
                edge_bps = int(round(raw_edge * 10_000)) - config.friction_bps

            candidates.append(Candidate(
                proposal=effective_proposal,
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
    # removes the candidate from RATE/RANK (it can never be staked), but
    # the veto and its cause are NOT silently dropped: a FATAL-vetoed
    # candidate is recorded below (verdict=_veto_verdict(cand)) so losers
    # and refusals are always published, never just survivors.
    survivors: list[Candidate] = []
    vetoed: list[Candidate] = []
    for cand in candidates:
        cargs: list[Counterargument] = []
        for adversary in adversaries:
            for cause in adversary.attack(cand, snapshot, board):
                cargs.append(cause)
        cand = replace(cand, counterarguments=tuple(cargs))
        if any(c.severity == FATAL for c in cargs):
            vetoed.append(cand)
            continue
        survivors.append(cand)

    # 4. RATE -- Bet Rating: probability quality AND price quality, kept as
    # two SEPARATE numbers (the Two-Ledger rule extends here: a system's
    # calibration is never allowed to blend with the price it happened to
    # get). Neither number is published as "edge"; both are internal fields
    # on `rating`.
    rated: list[Candidate] = []
    for cand in survivors:
        # N2/honesty fix: a Bet Rating (even the model-only
        # probability_quality half) is a value-adjacent claim about the
        # calibrated probability being good -- not something RATE may
        # publish for a provenance that never claimed a calibrated
        # probability in the first place (placeholder, market_derived,
        # none). Only model_derived earns one, same gate as edge_bps above.
        if (cand.proposal.p_model is None
                or cand.proposal.p_model_provenance
                != PROBABILITY_PROVENANCE_MODEL_DERIVED):
            # Honest probabilities: no calibrated probability means nothing
            # for RATE to rate. `rating` stays None (not a dict with
            # None-valued keys) -- "no Bet Rating" is a structural absence,
            # never a rating dict that merely LOOKS empty.
            rated.append(replace(cand, rating=None))
            continue
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
    vetoed.sort(key=_rank_key)

    play_records = tuple(
        _to_decision_record(
            cand, snapshot=snapshot, board=board,
            registry_fingerprint=registry_fingerprint,
            frame_fingerprint=frame_fingerprint,
            recorded_utc=recorded_utc, record_provenance=record_provenance,
            verdict=("play" if cand.price_american is not None
                     else "market_unavailable"))
        for cand in rated
    )
    # Refusals are always published too (never just survivors/losers): a
    # FATAL-vetoed candidate becomes its own DecisionRecord, verdict mapped
    # from its cause (`_veto_verdict`), `refusal_reason` naming the cause,
    # and the FATAL counterargument(s) still attached.
    refusal_records = tuple(
        _to_decision_record(
            cand, snapshot=snapshot, board=board,
            registry_fingerprint=registry_fingerprint,
            frame_fingerprint=frame_fingerprint,
            verdict=_veto_verdict(cand))
        for cand in vetoed
    )
    records = play_records + refusal_records
    return Analysis(game_pk=snapshot.game_pk, t=snapshot.t, records=records)


# FATAL adversary_id -> the specific refused_* verdict registered for it in
# `src.ledger.records.VERDICTS`. An adversary_id with no entry here still
# gets published -- as the generic "no_play" -- rather than dropped; this
# map only sharpens the verdict when a specific one is registered.
FATAL_VERDICT_BY_ADVERSARY_ID = {
    "stale_book": "refused_stale",
    "thin_board": "refused_thin",
}


def _veto_verdict(cand: Candidate) -> str:
    """The verdict for a FATAL-vetoed candidate: the first FATAL cause's
    adversary_id, mapped to its registered `refused_*` verdict when one
    exists, else the generic "no_play". Never `None`, never a candidate
    silently unrecorded -- this is what makes B/N1's fix real: a refusal
    is a DecisionRecord like any other, distinguishable from a play only by
    `verdict`/`refusal_reason`, not by absence from the ledger."""
    for c in cand.counterarguments:
        if c.severity == FATAL:
            return FATAL_VERDICT_BY_ADVERSARY_ID.get(c.adversary_id, "no_play")
    return "no_play"  # unreachable in practice: vetoed candidates always
                       # carry >=1 FATAL counterargument by construction


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
                         verdict: str,
                         recorded_utc: str | None = None,
                         record_provenance: str | None = None
                         ) -> DecisionRecord:
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
    value_basis = None
    if proposal.p_model_provenance != PROBABILITY_PROVENANCE_MODEL_DERIVED:
        value_basis = VALUE_BASIS_PRICE_STANDING_ONLY

    if verdict == "play" and not evidence and not counterarguments:
        # DecisionRecord requires one of the two non-empty on a play
        # (synthesis-judge 4.2); a system that proposed with no evidence at
        # all still names its own thesis so the record is never silently
        # unsupported.
        evidence = [proposal.thesis or f"system:{proposal.system_id}"]

    refusal_reason = None
    if verdict != "play":
        fatal_causes = [c["cause"] for c in counterarguments
                        if c["severity"] == FATAL]
        if fatal_causes:
            refusal_reason = "; ".join(fatal_causes)

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
        # B1 (slice-review-2026-09-03): the real write instant, when the
        # caller has one to give (see analyze()'s docstring above); falls
        # back to snapshot.t only for a caller with no clock read to report.
        recorded_utc=(recorded_utc if recorded_utc is not None
                     else snapshot.t),
        record_provenance=record_provenance,
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
        p_model_provenance=proposal.p_model_provenance,
        p_model_interval=None,
        edge_bps=cand.edge_bps,
        price_improvement_bps=None,
        rating=cand.rating,
        thesis=proposal.thesis or None,
        evidence=evidence,
        counterarguments=counterarguments,
        supporting_systems=[proposal.system_id],
        refusal_reason=refusal_reason,
        assumption_exposure=dict(snapshot.assumption_exposure),
        stake_units=0.0,
        known_at_grade=grade,
        value_basis=value_basis,
        mechanism_predicates=tuple(proposal.mechanism_predicates or ()),
    )
