"""Customer product contracts — the six page shapes, locked as code.

These frozen dataclasses are the load-bearing shapes for the customer
product (docs/SAAS_APPLICATION_ARCHITECTURE.md §4, docs/PRODUCT_DESIGN_HANDOFF.md
page specs, docs/CAPABILITY_RECONCILIATION.md truth table). Two rules are
enforced by SHAPE, not convention:

  Rule S — every quantitative claim carries its sample size.
  Rule E — every claim carries its evidence label.

A `Claim` cannot be constructed quantitative without both. That refusal is
the product.

FOUR SEPARATE VOCABULARIES (never merged — §4.1 of the architecture doc):
  evidence ladder   detect.base.EVIDENCE_ORDER   (how much do we know?)
  observation       synthesis.OBSERVED           (not a hypothesis at all)
  game verdict      no_play/candidate/flagged/market_unavailable
  relevance tier    HIGH/MEDIUM/LOW/UNKNOWN      (how much could it matter?)

MARKET SEMANTICS: a quoted price, the market-implied consensus, and a price
improvement are three distinct types and are never collapsible into each
other. The de-vigged number is MARKET-IMPLIED CONSENSUS — it is never
described as the market's "true" anything. Price improvement is
line-shopping value: a better execution price, never expected value and
never an edge. No model win-probability field exists anywhere in this
module: the model is UNCALIBRATED and no screen may display one.

stdlib only. Pydantic mirrors live in api/ later; src/ stays dependency-free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, asdict
from typing import Optional, Tuple

from src.analysis import synthesis
from src.analysis import relevance
from src.analysis import prices as prices_mod
from src.detect import base as detect

# ---------------------------------------------------------------------------
# Capability states — from docs/CAPABILITY_RECONCILIATION.md. Every contract
# field that is not REAL TODAY carries its state as dataclass field metadata.
# ---------------------------------------------------------------------------

REAL_TODAY = "REAL_TODAY"
PARTIAL = "PARTIAL"
ENGINEERING_REQUIRED = "ENGINEERING_REQUIRED"
RESEARCH_DEPENDENT = "RESEARCH_DEPENDENT"
BLOCKED_CAPABILITY = "BLOCKED"
UNKNOWN_CAPABILITY = "UNKNOWN"

CAPABILITY_STATES = frozenset({
    REAL_TODAY, PARTIAL, ENGINEERING_REQUIRED, RESEARCH_DEPENDENT,
    BLOCKED_CAPABILITY, UNKNOWN_CAPABILITY,
})


def _cap(state: str) -> dict:
    if state not in CAPABILITY_STATES:
        raise ValueError(f"unknown capability state: {state!r}")
    return {"capability": state}


def field_capabilities(cls) -> dict:
    """Capability state per field of a contract class (REAL_TODAY default)."""
    return {f.name: f.metadata.get("capability", REAL_TODAY)
            for f in fields(cls)}


# ---------------------------------------------------------------------------
# Internal evidence vocabulary — synthesis.EVIDENCE_LABELS is the single
# authority. Its keys are the ladder statuses plus the off-ladder OBSERVED.
# ---------------------------------------------------------------------------

INTERNAL_EVIDENCE = frozenset(synthesis.EVIDENCE_LABELS)

RELEVANCE_TIERS = frozenset({relevance.HIGH, relevance.MEDIUM,
                             relevance.LOW, relevance.UNKNOWN})

VERDICTS = frozenset({"no_play", "candidate", "flagged", "market_unavailable"})


# ---------------------------------------------------------------------------
# Evidence translation — internal identity -> customer vocabulary.
# The handoff's ladder: Observation / Exploratory / Historical support /
# Forward testing / Validated. Labelling is DIFFERENTIAL: ordinary
# observations get NO badge (the current 153-UNPROVEN-badge behaviour is the
# measured failure this replaces). Pure translation, no semantic drift.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CustomerEvidence:
    """How one internal evidence status renders on the customer surface."""
    internal: str            # the internal status, preserved for audit
    tier: int                # 1..5 on the customer ladder; 0 = off-ladder
    label: str               # customer wording
    show_badge: bool         # differential labelling: default is NO badge


_CUSTOMER_EVIDENCE = {
    # Off-ladder / tier-1 defaults: measured, no predictive claim, NO badge.
    synthesis.OBSERVED: CustomerEvidence(synthesis.OBSERVED, 1,
                                         "Observation", False),
    detect.UNPROVEN: CustomerEvidence(detect.UNPROVEN, 1,
                                      "Observation", False),
    # Blocked is a data gap, not an evidence strength; rendered as the gap
    # itself, never as a badge on the ladder.
    detect.BLOCKED: CustomerEvidence(detect.BLOCKED, 0,
                                     "Not available with our data", False),
    # Negative evidence is first-class and always visibly labelled.
    detect.TESTED_NULL: CustomerEvidence(detect.TESTED_NULL, 1,
                                         "Tested — did not hold up", True),
    # Being researched whether it matters.
    detect.HISTORICAL_CANDIDATE: CustomerEvidence(detect.HISTORICAL_CANDIDATE,
                                                  2, "Exploratory", True),
    detect.TUNING_EVIDENCE: CustomerEvidence(detect.TUNING_EVIDENCE, 2,
                                             "Exploratory", True),
    # Held up in past data, not forward-tested.
    detect.PROVISIONAL: CustomerEvidence(detect.PROVISIONAL, 3,
                                         "Historical support", True),
    detect.FORWARD_TESTING: CustomerEvidence(detect.FORWARD_TESTING, 4,
                                             "Forward testing", True),
    detect.PROVEN: CustomerEvidence(detect.PROVEN, 5, "Validated", True),
}


def customer_evidence(internal_status: str) -> CustomerEvidence:
    """Translate an internal evidence status to the customer vocabulary.

    Total over the internal vocabulary: every key of
    synthesis.EVIDENCE_LABELS maps exactly once; anything else is refused
    rather than guessed.
    """
    try:
        return _CUSTOMER_EVIDENCE[internal_status]
    except KeyError:
        raise ValueError(
            f"unknown internal evidence status: {internal_status!r}; "
            f"the vocabulary authority is synthesis.EVIDENCE_LABELS")


# ---------------------------------------------------------------------------
# Market semantics — three distinct, non-interchangeable types.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuotedPrice:
    """A price actually quoted by one named book at one instant. A fact."""
    book: str
    american_price: int
    observed_utc: str

    def __post_init__(self):
        if not self.book:
            raise ValueError("a quoted price names its book")
        if not self.observed_utc:
            raise ValueError("a quoted price carries its capture instant")

    def to_json(self) -> str:
        return _dumps(asdict(self))


@dataclass(frozen=True)
class MarketImpliedConsensus:
    """The de-vigged multi-book consensus: MARKET-IMPLIED, an average of
    books' opinions with the vig removed. Not a prediction, not a "true"
    probability, not the market's "true" read — implied consensus only."""
    implied_probability: float
    books: int
    observed_utc: str

    def __post_init__(self):
        if not (0.0 < self.implied_probability < 1.0):
            raise ValueError("implied probability must be a fraction in (0,1)")
        if self.books < prices_mod.MIN_BOOKS:
            raise ValueError(
                f"below the {prices_mod.MIN_BOOKS}-book floor a consensus "
                f"means a handful's opinion, not a market's")
        if not self.observed_utc:
            raise ValueError("a consensus carries its capture instant")

    def to_json(self) -> str:
        return _dumps(asdict(self))


@dataclass(frozen=True)
class PriceImprovement:
    """Line-shopping value: the best quoted price versus the market-implied
    consensus, at ONE instant. A better execution price on the same bet —
    never expected value, never an edge, never a prediction."""
    best: QuotedPrice
    consensus: MarketImpliedConsensus
    improvement_points: float        # probability fraction on the wire
    improvement_return_pct: float
    label: str = prices_mod.LABEL    # required, non-empty, never removed

    def __post_init__(self):
        if not isinstance(self.best, QuotedPrice):
            raise TypeError("best must be a QuotedPrice, nothing else")
        if not isinstance(self.consensus, MarketImpliedConsensus):
            raise TypeError("consensus must be a MarketImpliedConsensus, "
                            "nothing else")
        if not self.label:
            raise ValueError("the price-improvement label is required; "
                             "removing it is a product decision nobody gets "
                             "to make silently")

    def to_json(self) -> str:
        return _dumps(asdict(self))


# ---------------------------------------------------------------------------
# Claim — the atom. Refuses to exist quantitative without sample + evidence.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    """One statement the product makes. If it carries a number (`value` is
    not None) it MUST carry sample_n, sample_unit and evidence_label — the
    constructor refuses otherwise. That refusal is the whole product."""
    statement: str
    value: Optional[float] = None
    sample_n: Optional[int] = None
    sample_unit: Optional[str] = None
    evidence_label: str = synthesis.OBSERVED   # internal vocabulary
    capability_state: str = REAL_TODAY

    def __post_init__(self):
        if not self.statement:
            raise ValueError("a claim without a statement is nothing")
        if self.evidence_label not in INTERNAL_EVIDENCE:
            raise ValueError(
                f"evidence_label {self.evidence_label!r} is not in the "
                f"internal vocabulary (synthesis.EVIDENCE_LABELS)")
        if self.capability_state not in CAPABILITY_STATES:
            raise ValueError(
                f"unknown capability_state {self.capability_state!r}")
        if self.value is not None:
            if self.sample_n is None or self.sample_n <= 0:
                raise ValueError(
                    "a quantitative claim without its sample size is "
                    "refused; that refusal is the product (Rule S)")
            if not self.sample_unit:
                raise ValueError(
                    "a quantitative claim names what its sample counts "
                    "(Rule S)")

    @property
    def is_quantitative(self) -> bool:
        return self.value is not None

    @property
    def customer_evidence(self) -> CustomerEvidence:
        return customer_evidence(self.evidence_label)

    def to_json(self) -> str:
        d = asdict(self)
        ce = self.customer_evidence
        d["customer_evidence"] = {"label": ce.label, "tier": ce.tier,
                                  "show_badge": ce.show_badge}
        return _dumps(d)


# ---------------------------------------------------------------------------
# Shared shapes.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GameRef:
    game_id: str
    away: str
    home: str
    date: str
    start_time_utc: Optional[str] = None
    venue: Optional[str] = None
    id_stable: bool = True

    def to_json(self) -> str:
        return _dumps(asdict(self))


@dataclass(frozen=True)
class ChangeItem:
    """One What Changed event. `tier` is the RELEVANCE vocabulary
    (HIGH/MEDIUM/LOW/UNKNOWN), never the evidence ladder."""
    seen_utc: str
    category: str                      # e.g. lineup, starter, weather, bullpen
    headline: str
    tier: str
    game_id: Optional[str] = None
    market_reaction: Optional[str] = field(
        default=None, metadata=_cap(PARTIAL))   # event->price pairing: PARTIAL

    def __post_init__(self):
        if self.tier not in RELEVANCE_TIERS:
            raise ValueError(
                f"tier {self.tier!r} is not a relevance tier; the relevance "
                f"vocabulary is HIGH/MEDIUM/LOW/UNKNOWN and it never merges "
                f"with the evidence ladder")

    def to_json(self) -> str:
        return _dumps(asdict(self))


NO_COUNTERARGUMENTS_TEXT = "No significant counterarguments found"
EMPTY_WHAT_CHANGED_TEXT = "Nothing has changed since this morning."


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. TODAY
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TodayContract:
    """TODAY / daily slate. Never leads with a null count — the summary is a
    sentence stating the work done."""
    date: str
    slate_summary: str = field(metadata=_cap(ENGINEERING_REQUIRED))
    games: Tuple[GameRef, ...] = field(metadata=_cap(REAL_TODAY))
    what_changed: Tuple[ChangeItem, ...] = field(metadata=_cap(REAL_TODAY))
    what_matters: Tuple[Claim, ...] = field(metadata=_cap(PARTIAL))
    best_prices: Tuple[PriceImprovement, ...] = field(
        metadata=_cap(REAL_TODAY))
    data_support_meter: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))

    def __post_init__(self):
        if not self.slate_summary:
            raise ValueError("the slate summary sentence is mandatory; "
                             "a row of zeros is not a summary")

    def to_json(self) -> str:
        return _dumps(_deep(self))


# ---------------------------------------------------------------------------
# 2. GAME QUICK
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Factor:
    """One Quick View factor line. supports=True renders as a check,
    False as a caution."""
    supports: bool
    sentence: str
    claim: Optional[Claim] = None

    def __post_init__(self):
        if not self.sentence:
            raise ValueError("a factor is one plain-English sentence")


MAX_QUICK_FACTORS = 5


@dataclass(frozen=True)
class GameQuickContract:
    ref: GameRef
    factors: Tuple[Factor, ...] = field(metadata=_cap(PARTIAL))
    best_available_price: Optional[QuotedPrice] = field(
        metadata=_cap(REAL_TODAY))
    historical_evidence_note: str = field(metadata=_cap(RESEARCH_DEPENDENT))
    your_bet: Optional[str] = None
    data_support_meter: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    main_reason_for: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    main_reason_against: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))

    def __post_init__(self):
        if len(self.factors) > MAX_QUICK_FACTORS:
            raise ValueError(
                f"Quick View shows at most {MAX_QUICK_FACTORS} factors; "
                f"truncation is the feature — the rest live in Advanced")

    @property
    def counterargument_lines(self) -> Tuple[str, ...]:
        """Both sides always appear. A page that only ever shows support
        is a tout."""
        against = tuple(f.sentence for f in self.factors if not f.supports)
        return against or (NO_COUNTERARGUMENTS_TEXT,)

    def to_json(self) -> str:
        d = _deep(self)
        d["counterargument_lines"] = list(self.counterargument_lines)
        return _dumps(d)


# ---------------------------------------------------------------------------
# 3. GAME ADVANCED
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketBlock:
    """Advanced View market block. Consensus is market-implied; hold is the
    book's margin; dispersion is how much books disagree."""
    consensus: Optional[MarketImpliedConsensus] = field(
        metadata=_cap(REAL_TODAY))
    quotes: Tuple[QuotedPrice, ...] = field(metadata=_cap(REAL_TODAY))
    hold_pct: Optional[float] = field(metadata=_cap(REAL_TODAY))
    book_disagreement: Optional[str] = field(metadata=_cap(REAL_TODAY))
    f5_vs_full_game: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))  # zero F5 rows yet

    def to_json(self) -> str:
        return _dumps(_deep(self))


@dataclass(frozen=True)
class GameAdvancedContract:
    """Advanced View blocks, in the handoff's order. Every number inside is
    a Claim, so it structurally carries its sample."""
    ref: GameRef
    starting_pitchers: Tuple[Claim, ...] = field(metadata=_cap(PARTIAL))
    lineups: Tuple[Claim, ...] = field(metadata=_cap(PARTIAL))
    bullpen: Tuple[Claim, ...] = field(metadata=_cap(REAL_TODAY))
    market: Optional[MarketBlock] = field(metadata=_cap(PARTIAL))
    context: Tuple[Claim, ...] = field(metadata=_cap(REAL_TODAY))
    evidence_method: Tuple[Claim, ...] = field(metadata=_cap(PARTIAL))
    batted_ball: Tuple[Claim, ...] = field(
        default=(), metadata=_cap(RESEARCH_DEPENDENT))  # Statcast not ingested

    def to_json(self) -> str:
        return _dumps(_deep(self))


# ---------------------------------------------------------------------------
# 4. BET CHECK — the fixed skeleton. Always these fields, always present.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BetQuery:
    raw: str
    parsed: bool
    team: Optional[str] = None
    side: Optional[str] = None
    market: Optional[str] = None
    price: Optional[int] = None
    line: Optional[float] = None
    parse_error: Optional[str] = None

    def __post_init__(self):
        if not self.parsed and not self.parse_error:
            raise ValueError('"I could not read this bet" is a product '
                             "answer and needs its reason")

    def to_json(self) -> str:
        return _dumps(asdict(self))


@dataclass(frozen=True)
class BetCheckContract:
    """The fixed skeleton is a trust mechanism: when the shape never
    changes, an omission becomes visible. The counterargument is
    STRUCTURALLY mandatory — empty renders NO_COUNTERARGUMENTS_TEXT,
    never nothing. `recommendation` exists and is permanently None while
    Engine 2 is None: "we do not do that" stated as a field."""
    query: BetQuery
    game: Optional[GameRef]
    thesis_support: Tuple[Claim, ...] = field(metadata=_cap(PARTIAL))
    counterargument: Tuple[Claim, ...] = field(metadata=_cap(PARTIAL))
    best_available_price: Optional[QuotedPrice] = field(
        metadata=_cap(REAL_TODAY))
    market_consensus: Optional[MarketImpliedConsensus] = field(
        metadata=_cap(REAL_TODAY))
    your_price_below_market: Optional[bool] = field(
        metadata=_cap(REAL_TODAY))
    what_changed: Tuple[ChangeItem, ...] = field(metadata=_cap(REAL_TODAY))
    strongest_reason: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    weakest_reason: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    historical_support: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    evidence_status: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    bottom_line: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))
    price_improvement: Optional[PriceImprovement] = field(
        default=None, metadata=_cap(REAL_TODAY))
    recommendation: None = None   # permanently None while Engine 2 is None

    def __post_init__(self):
        if self.recommendation is not None:
            raise ValueError(
                "recommendation is permanently None: the Ranker's Engine 2 "
                "gate stands and we never say 'bet this'")
        if not isinstance(self.counterargument, tuple):
            raise TypeError("counterargument is a mandatory tuple; it may "
                            "be empty, never absent")
        if self.historical_support is not None and \
                self.historical_support not in ("Weak", "Moderate", "Strong"):
            raise ValueError("historical support is Weak/Moderate/Strong")
        if self.evidence_status is not None:
            allowed = {ce.label for ce in _CUSTOMER_EVIDENCE.values()}
            if self.evidence_status not in allowed:
                raise ValueError(
                    f"evidence_status must be a customer-ladder label, "
                    f"got {self.evidence_status!r}")

    @property
    def counterargument_lines(self) -> Tuple[str, ...]:
        lines = tuple(c.statement for c in self.counterargument)
        return lines or (NO_COUNTERARGUMENTS_TEXT,)

    def to_json(self) -> str:
        d = _deep(self)
        d["recommendation"] = None
        d["counterargument_lines"] = list(self.counterargument_lines)
        return _dumps(d)


# ---------------------------------------------------------------------------
# 5. ODDS / MARKET BOARD
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OddsRow:
    game_id: str
    market: str                        # customer-facing market name
    best: QuotedPrice = field(metadata=_cap(REAL_TODAY))
    consensus: Optional[MarketImpliedConsensus] = field(
        metadata=_cap(REAL_TODAY))
    book_disagreement: Optional[str] = field(metadata=_cap(REAL_TODAY))
    price_age: Optional[str] = field(default=None, metadata=_cap(PARTIAL))
    movement: Optional[str] = field(default=None, metadata=_cap(PARTIAL))

    def __post_init__(self):
        if not isinstance(self.best, QuotedPrice):
            raise TypeError("best is a QuotedPrice")
        if self.consensus is not None and \
                not isinstance(self.consensus, MarketImpliedConsensus):
            raise TypeError("consensus is a MarketImpliedConsensus")

    def to_json(self) -> str:
        return _dumps(_deep(self))


@dataclass(frozen=True)
class OddsBoardContract:
    observed_utc: str                  # a board without its instant is not one
    rows: Tuple[OddsRow, ...] = field(metadata=_cap(REAL_TODAY))
    f5_vs_full_game: Optional[str] = field(
        default=None, metadata=_cap(ENGINEERING_REQUIRED))

    def __post_init__(self):
        if not self.observed_utc:
            raise ValueError("a board without its capture instant is not a "
                             "board")

    def to_json(self) -> str:
        return _dumps(_deep(self))


# ---------------------------------------------------------------------------
# 6. WHAT CHANGED
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WhatChangedContract:
    """Reverse-chronological, tiered, always timestamped. 'Since you last
    looked' needs accounts; until then the label is 'since this morning'.
    Empty is a legitimate, stated state."""
    since_label: str = field(metadata=_cap(REAL_TODAY))
    events: Tuple[ChangeItem, ...] = field(metadata=_cap(REAL_TODAY))
    personalized: bool = field(
        default=False, metadata=_cap(ENGINEERING_REQUIRED))

    def __post_init__(self):
        if not self.since_label:
            raise ValueError("the feed names its window")
        if self.personalized:
            raise ValueError("'since you last looked' requires accounts, "
                             "which do not exist")

    @property
    def empty_text(self) -> str:
        return EMPTY_WHAT_CHANGED_TEXT

    def to_json(self) -> str:
        d = _deep(self)
        if not self.events:
            d["empty_text"] = EMPTY_WHAT_CHANGED_TEXT
        return _dumps(d)


CONTRACTS = (TodayContract, GameQuickContract, GameAdvancedContract,
             BetCheckContract, OddsBoardContract, WhatChangedContract)


def _deep(obj):
    """asdict over a contract, tuples becoming lists, deterministic."""
    return asdict(obj)
