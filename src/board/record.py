"""The universal record: PriceObservation, InformationEvent, MarketFamilySpec.

Frozen per synthesis-judge.md section 4.2 plus the field additions named in
ARCHITECTURE_BETTING_ENGINE.md section 4 (the attack's guards). The owner
amendment this packet encodes: a probability (p_model, something a system
believes) and a price-derived quantity (an American price, an implied
probability, a de-vigged fair price) are never the same field, never
interchangeable, and never silently converted into each other inside this
record -- that conversion belongs to engine/analyze.py's PROJECT phase, in
the open, with the friction it costs made explicit. PriceObservation carries
prices. InformationEvent carries facts. Neither carries a model's belief.

Fields present here but not in a naive reading of synthesis 4.2:
  limit_observed    (F12) the stake size the provider actually exposed, if
                     any -- distinct from assumed_max_stake_units, which is a
                     declared assumption on MarketFamilySpec, not a fact
                     observed on a single quote.
  venue_kind        (attack.md M4/S-series) "sportsbook" | "exchange"; fee
                     structure and depth semantics differ and must not be
                     silently pooled.
  is_close          (design-data-first.md) rows with is_close=True belong in
                     the SEALED partition; a reader that can open them is a
                     leakage bug by construction, not by discipline.
  l0_available      (S6) backfilled 2023-25 rows are stamped False and must
                     never be quoted as byte-reproducible from provider L0.

`price_age_seconds` is deliberately NOT a field here (per the task boundary):
it is derived at decision time from `observed_utc` and the decision clock,
not a fact about the observation itself -- storing it here would let staleness
silently drift out of sync with whatever instant a later reader treats as
"now".
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping

_GRADES = frozenset("ABCD")
_LINE_RE = re.compile(r"^-?\d+(\.\d+)?$")
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


class RecordValidationError(ValueError):
    """Raised by a record's __post_init__ when a field violates its contract.

    Named separately from ValueError so callers can catch validation
    failures specifically without swallowing unrelated bugs (e.g. a TypeError
    from a genuinely missing required argument).
    """


def _require_int_price(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordValidationError(
            f"{field_name} must be an American int price, got {value!r} "
            f"({type(value).__name__}) -- decimal/implied odds are derived, "
            "never stored"
        )
    if -100 < value < 100:
        raise RecordValidationError(
            f"{field_name}={value} is not a valid American price "
            "(must be <= -100 or >= 100)"
        )


def _require_line(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise RecordValidationError(
            f"{field_name} must be a decimal string or None, got "
            f"{type(value).__name__} -- lines are never floats (see "
            "src/board/ids.py module docstring)"
        )
    if not _LINE_RE.match(value):
        raise RecordValidationError(
            f"{field_name}={value!r} does not match ^-?\\d+(\\.\\d+)?$"
        )


def _require_grade(value: str, field_name: str) -> None:
    if value not in _GRADES:
        raise RecordValidationError(
            f"{field_name}={value!r} must be one of {sorted(_GRADES)}"
        )


def _require_iso(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _ISO_RE.match(value):
        raise RecordValidationError(
            f"{field_name}={value!r} must be an ISO-8601 UTC string "
            "(e.g. 2026-08-31T10:08:30Z or with fractional seconds/offset)"
        )


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One book's quote for one selection at one instant. A price, not a belief.

    See module docstring for the fields added beyond synthesis-judge.md 4.2
    (limit_observed, venue_kind, is_close, l0_available) and for why
    price_age_seconds is deliberately absent.
    """

    sport: str
    event_id: str
    game_pk: int | None
    market_key: str
    selection_id: str
    side: str
    subject_kind: str | None
    subject_id: str | None
    line: str | None  # DECIMAL STRING -- never a float
    book: str
    price_american: int  # American only; decimal/implied are derived
    observed_utc: str  # when WE saw it
    book_last_update: str | None  # when the BOOK moved
    known_at: str
    known_at_grade: str  # "A" | "B" | "C" | "D"
    capture_id: str
    source: str
    region: str
    provider_market_key: str
    venue_kind: str = "sportsbook"  # "sportsbook" | "exchange" (fees differ)
    is_close: bool = False  # is_close rows live in the sealed partition
    limit_observed: int | None = None  # stake size the provider exposed, if any
    l0_available: bool = True  # False for backfilled rows with no verbatim L0

    def __post_init__(self) -> None:
        _require_int_price(self.price_american, "price_american")
        _require_line(self.line, "line")
        _require_grade(self.known_at_grade, "known_at_grade")
        _require_iso(self.observed_utc, "observed_utc")
        _require_iso(self.book_last_update, "book_last_update")
        _require_iso(self.known_at, "known_at")
        if self.venue_kind not in ("sportsbook", "exchange"):
            raise RecordValidationError(
                f"venue_kind={self.venue_kind!r} must be 'sportsbook' or "
                "'exchange'"
            )
        if self.limit_observed is not None and (
            isinstance(self.limit_observed, bool)
            or not isinstance(self.limit_observed, int)
        ):
            raise RecordValidationError(
                f"limit_observed must be an int or None, got "
                f"{type(self.limit_observed).__name__}"
            )


@dataclass(frozen=True, slots=True)
class InformationEvent:
    """A fact about the world (a lineup, a weather forecast), never a price."""

    sport: str
    scope: str
    scope_id: str
    kind: str  # probable_pitcher | lineup_posted | il_placement | ...
    payload: Mapping[str, Any]
    happened_utc: str | None
    known_at: str
    known_at_grade: str
    observed_utc: str
    source: str
    capture_id: str

    def __post_init__(self) -> None:
        _require_grade(self.known_at_grade, "known_at_grade")
        _require_iso(self.happened_utc, "happened_utc")
        _require_iso(self.known_at, "known_at")
        _require_iso(self.observed_utc, "observed_utc")


@dataclass(frozen=True)
class MarketFamilySpec:
    """Registration metadata for a market family -- not per-quote, per-family."""

    key: str
    provider_key: str
    scope: str
    subject_kind: str
    sides: tuple
    has_line: bool
    devig: str  # registered method id, not a default
    capture_tier: str
    credits_per_event: int
    status: str  # LIVE|PROBE|DECLARED|BLOCKED
    evidence_window: tuple  # per family; h2h/totals differ from props
    settle: str  # SETTLEMENT_RULES key -- REQUIRED
    correlation_group: str
    assumed_max_stake_units: float | None = None  # declared cap, not observed
    # window over which evidence accumulates before this family may be priced
    # by any system (G3: ten graded examples, fifty before pricing) --
    # distinct from evidence_window above, which synthesis 4.2 defines as the
    # per-family lookback/backtest window; this is the accretion counter.
    evidence_window_examples: int | None = None

    def __post_init__(self) -> None:
        if self.status not in ("LIVE", "PROBE", "DECLARED", "BLOCKED"):
            raise RecordValidationError(
                f"status={self.status!r} must be one of "
                "LIVE|PROBE|DECLARED|BLOCKED"
            )


_RECORD_TYPES = (PriceObservation, InformationEvent)


def to_jsonl_line(record: PriceObservation | InformationEvent) -> str:
    """Serialize one record to a single JSONL line (no trailing newline)."""
    return json.dumps(asdict(record), sort_keys=True)


def price_observation_from_dict(data: Mapping[str, Any]) -> PriceObservation:
    valid = {f.name for f in fields(PriceObservation)}
    return PriceObservation(**{k: v for k, v in data.items() if k in valid})


def information_event_from_dict(data: Mapping[str, Any]) -> InformationEvent:
    valid = {f.name for f in fields(InformationEvent)}
    return InformationEvent(**{k: v for k, v in data.items() if k in valid})


def price_observations_from_jsonl(path: str) -> list[PriceObservation]:
    """Read a JSONL file of PriceObservation rows. Raises on any invalid row --
    the record's own validators are the enforcement point, not this reader."""
    rows: list[PriceObservation] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(price_observation_from_dict(json.loads(line)))
    return rows
