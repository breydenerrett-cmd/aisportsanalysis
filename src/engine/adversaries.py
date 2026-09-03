"""Adversary roster v1: `docs/ENGINE_CONTRACT.md` section 5 names the
intended roster (StaleBook, ThinBoard, NonSimultaneous, Grade,
CorrelatedEvidence, MarketDisagreement, Sample, Regime, Friction) and left
`DEFAULT_ADVERSARIES = ()` for a later packet to wire. This is that packet's
first four: each one attacks in ATTACK (after PROJECT, so it sees the
priced `Candidate` -- consensus, friction, price -- that a PROPOSE-side
system never gets), and each has one registered, documented `CAUSE` string
so a veto can always be traced back to a named rule rather than an ad hoc
string invented at veto time (`docs/ARCHITECTURE_BETTING_ENGINE.md` section
4: "a cause must be registered, not invented ad hoc at veto time").

Roster
------
StaleBook            -- the quoted price is older than a threshold; a stale
                         quote is not a live tradeable price.
ThinBoard            -- fewer books quote both sides than `min_books`; the
                         consensus this candidate was priced against is
                         unreliable at this depth.
PriceMovedAgainst     -- the price has moved against the bettor since a
                         reference price the caller supplies (line shopping
                         / stale-quote capture in reverse: the board is live
                         but has already repriced away from the edge).
DegradedInformation   -- the snapshot's own `assumption_exposure` implies a
                         `ReplayLabel.DEGRADED_INFORMATION` classification
                         (mirrors `src.core.asof.information_grade`'s
                         sentinel-field rule, restated here in terms of the
                         `PriceBlindSnapshot.assumption_exposure` counts
                         that survive into `analyze()`, since ATTACK never
                         sees the original `src.core.asof.Snapshot`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.core.asof import DEGRADED_SENTINEL_FIELDS, ReplayLabel
from src.engine.analyze import FATAL, MAJOR, Counterargument


@dataclass(frozen=True, slots=True)
class StaleBook:
    """FATAL: the best-quoted book's `staleness_seconds` exceeds
    `max_staleness_seconds`. A price this old is not a live tradeable
    quote, so no candidate priced against it may play."""

    id: str = "stale_book"
    max_staleness_seconds: int = 1800
    CAUSE: ClassVar[str] = "stale_book:staleness_seconds_exceeds_threshold"

    def attack(self, candidate, snapshot, board) -> tuple:
        staleness = (candidate.friction or {}).get("staleness_seconds")
        if staleness is None or staleness <= self.max_staleness_seconds:
            return ()
        return (Counterargument(
            adversary_id=self.id, cause=self.CAUSE, severity=FATAL,
            detail=f"staleness_seconds={staleness} > "
                   f"{self.max_staleness_seconds}",
        ),)


@dataclass(frozen=True, slots=True)
class ThinBoard:
    """FATAL: fewer than `min_books` books quote both sides of the
    candidate's market at decision time. Guard M7 (consensus-undefined is
    an explicit friction state) already makes `board.consensus()` return
    `None` below this depth; this adversary is the ATTACK-phase veto for
    the case where a consensus DID form but off too few books to trust."""

    id: str = "thin_board"
    min_books: int = 2
    CAUSE: ClassVar[str] = "thin_board:books_at_decision_below_min_books"

    def attack(self, candidate, snapshot, board) -> tuple:
        if candidate.books_at_decision >= self.min_books:
            return ()
        return (Counterargument(
            adversary_id=self.id, cause=self.CAUSE, severity=FATAL,
            detail=f"books_at_decision={candidate.books_at_decision} < "
                   f"{self.min_books}",
        ),)


@dataclass(frozen=True, slots=True)
class PriceMovedAgainst:
    """MAJOR: the candidate's price has moved against the bettor since a
    reference price recorded earlier for the same selection. `reference_prices`
    is a plain mapping the caller populates from its own prior capture (this
    adversary performs no I/O and reads no clock -- the reference is data,
    handed in, not fetched); a selection absent from the mapping is silently
    not attacked (no reference means nothing to compare against, never a
    veto by omission)."""

    id: str = "price_moved_against"
    reference_prices: "dict" = None
    CAUSE: ClassVar[str] = "price_moved_against:price_worse_than_reference"

    def __post_init__(self) -> None:
        if self.reference_prices is None:
            object.__setattr__(self, "reference_prices", {})

    def attack(self, candidate, snapshot, board) -> tuple:
        ref = self.reference_prices.get(candidate.selection_id)
        cur = candidate.price_american
        if ref is None or cur is None:
            return ()
        from src.core import odds as odds_math
        ref_dec = odds_math.american_to_decimal(ref)
        cur_dec = odds_math.american_to_decimal(cur)
        if cur_dec >= ref_dec:
            return ()  # unchanged or improved -- not an adversary's business
        return (Counterargument(
            adversary_id=self.id, cause=self.CAUSE, severity=MAJOR,
            detail=f"price moved from {ref} to {cur} (decimal "
                   f"{ref_dec:.4f} -> {cur_dec:.4f})",
        ),)


@dataclass(frozen=True, slots=True)
class DegradedInformation:
    """MAJOR: the snapshot's `assumption_exposure` shows one of
    `src.core.asof.DEGRADED_SENTINEL_FIELDS` present only at a non-A grade,
    or (via `min_exposed_sentinel_fields`) absent entirely -- the same rule
    `src.core.asof.information_grade` applies to a full `Snapshot`, restated
    against the coarser `assumption_exposure` counts that are all ATTACK
    has to work with post-PROJECT. Labels the veto with the `ReplayLabel`
    it corresponds to, per the packet's requirement that this adversary
    "uses ReplayLabel"."""

    id: str = "degraded_information"
    sentinel_fields: tuple = DEGRADED_SENTINEL_FIELDS
    CAUSE: ClassVar[str] = "degraded_information:replay_label_degraded_information"

    def attack(self, candidate, snapshot, board) -> tuple:
        exposure = snapshot.assumption_exposure or {}
        reasons = []
        for name in self.sentinel_fields:
            graded_a = exposure.get(f"A:{name}", 0) > 0
            any_grade = any(k.endswith(f":{name}") for k in exposure)
            if not any_grade:
                reasons.append(f"{name}: not present in assumption_exposure")
            elif not graded_a:
                reasons.append(f"{name}: present but not grade A")
        if not reasons:
            return ()
        return (Counterargument(
            adversary_id=self.id, cause=self.CAUSE, severity=MAJOR,
            detail=f"{ReplayLabel.DEGRADED_INFORMATION.value}: "
                   + "; ".join(sorted(reasons)),
        ),)


DEFAULT_ADVERSARIES: tuple = (
    StaleBook(), ThinBoard(), PriceMovedAgainst(), DegradedInformation(),
)
