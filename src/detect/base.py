"""The detector contract: one narrow observation, or silence.

WHY EVERY DETECTOR MUST CARRY A BASELINE
----------------------------------------
The product is a briefing for someone who already knows a lot about baseball, so
the bar is not "true" but "true and not already in your head". That distinction
is only computable if a detector can say what NORMAL looks like.

"Their starter has a 3.80 ERA" is true and worthless. "Their starter allows a .390
wOBA to left-handed hitters against a league average of .315, and tonight's lineup
carries six left-handed plate appearances" is the same category of fact with a
baseline attached, and it is the reason anyone would read the page.

So a detector without a baseline does not ship. There is no way to tell a finding
from a description without one, and a wall of descriptions is exactly the product
this is trying not to be.

WHY THE SAMPLE GATE IS THE PRODUCT, NOT A SAFEGUARD
---------------------------------------------------
The most-quoted statistic in baseball betting is batter-versus-pitcher history. A
live check of one star hitter against one pitcher returned TWO at-bats.

A tool that prints "he is 0-for-2 against this guy" is worse than useless: it
launders noise into the reader's confidence. A tool that prints "the 4-for-8 you
are about to see elsewhere is eight at-bats and means nothing" is telling a sharp
bettor something he is not thinking about.

Both are facts. The second is harder to produce and worth more, so `Finding`
supports a DEBUNK direction as a first-class result rather than treating a thin
sample purely as a reason to stay quiet.

WHY MARKET RELEVANCE IS A SEPARATE FIELD
----------------------------------------
A large, real, surprising edge that the price already reflects is not a bet. The
project's whole reframe rests on that distinction, so it is a field rather than
something inferred later: a detector states what it found, and separately whether
the market appears to have noticed.
"""

from __future__ import annotations

# Evidence status. Every claim rendered anywhere carries exactly one of these, so
# a reader can never mistake a hypothesis for a result. The ordering is the
# strength ordering and is relied on by the UI.
UNPROVEN = "unproven"
# Tested against outcomes and found not to predict them. Strictly WEAKER than
# UNPROVEN, which merely means nobody has looked: an untested guess might work,
# and this one has been measured and does not. Collapsing the two would let a
# reader mistake a refuted claim for an open question, which is the single
# easiest way for this system to mislead the person using it.
TESTED_NULL = "tested_null"
BLOCKED = "blocked"
HISTORICAL_CANDIDATE = "historical_candidate"
TUNING_EVIDENCE = "tuning_evidence"
PROVISIONAL = "provisional"
FORWARD_TESTING = "forward_testing"
PROVEN = "proven"

EVIDENCE_ORDER = (BLOCKED, TESTED_NULL, UNPROVEN, HISTORICAL_CANDIDATE,
                  TUNING_EVIDENCE, PROVISIONAL, FORWARD_TESTING, PROVEN)

# What a finding is telling you.
SIGNAL = "signal"      # something is unusual and points somewhere
DEBUNK = "debunk"      # something looks like information and is not
CONTEXT = "context"    # true, relevant, not surprising -- shown but never ranked

# Direction relative to the game.
AWAY, HOME, NEITHER = "away", "home", "neither"


class DetectorError(RuntimeError):
    """Raised when a detector is built or declared incorrectly."""


class Finding:
    """One fact, with everything needed to judge it.

    `surprise` is in units of "how far from the baseline", not a raw difference,
    so findings from unrelated detectors can be ranked against each other. A
    detector that cannot express its surprise on that scale must say so rather
    than inventing a number -- see `unscored`.
    """

    __slots__ = ("detector", "kind", "claim", "value", "baseline", "sample",
                 "surprise", "confidence", "side", "market_relevance",
                 "evidence", "detail")

    def __init__(self, detector, kind, claim, value=None, baseline=None,
                 sample=None, surprise=None, confidence=None, side=NEITHER,
                 market_relevance=None, evidence=UNPROVEN, detail=None):
        if kind not in (SIGNAL, DEBUNK, CONTEXT):
            raise DetectorError(f"unknown finding kind {kind!r}")
        if evidence not in EVIDENCE_ORDER:
            raise DetectorError(f"unknown evidence status {evidence!r}")
        if side not in (AWAY, HOME, NEITHER):
            raise DetectorError(f"unknown side {side!r}")
        if kind is SIGNAL and baseline is None:
            # The rule the module docstring exists to enforce. A signal without a
            # baseline is a description, and descriptions are the failure mode.
            raise DetectorError(
                f"detector {detector!r} emitted a signal with no baseline; a "
                "claim that cannot say what normal looks like is a description, "
                "not a finding")
        self.detector = detector
        self.kind = kind
        self.claim = claim
        self.value = value
        self.baseline = baseline
        self.sample = sample
        self.surprise = surprise
        self.confidence = confidence
        self.side = side
        self.market_relevance = market_relevance
        self.evidence = evidence
        self.detail = detail or {}

    @property
    def unscored(self) -> bool:
        """True when this finding cannot be ranked against others."""
        return self.surprise is None

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__slots__}

    def __repr__(self):
        return f"<Finding {self.detector} {self.kind} surprise={self.surprise}>"


class Detector:
    """Base class. Subclasses implement `run` and return a list of Findings.

    A detector that has nothing to say returns an empty list. That is the normal
    case and is not an error -- most detectors are silent on most games, which is
    what keeps the briefing readable.
    """

    name = None
    # Which market the finding bears on, when it bears on one. Part of the
    # pre-registered hypothesis family: the same detector applied to two markets
    # is two hypotheses, and counting it as one understates the correction.
    markets = ()
    # Status of the detector itself, distinct from the evidence status of any
    # individual finding it emits.
    status = UNPROVEN
    blocked_reason = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name is None:
            raise DetectorError(f"{cls.__name__} must define a name")
        if cls.status is BLOCKED and not cls.blocked_reason:
            raise DetectorError(
                f"{cls.name} is blocked but gives no reason; a blocked detector "
                "with no explanation is indistinguishable from a broken one")

    def run(self, game) -> list:
        raise NotImplementedError

    def safe_run(self, game) -> list:
        """Run without letting one detector take down a whole briefing.

        A detector that raises produces a CONTEXT finding saying so, rather than
        vanishing. A silently missing detector looks identical to one that had
        nothing to say, and those two states must never be confused.
        """
        if self.status is BLOCKED:
            return [Finding(self.name, CONTEXT,
                            f"{self.name}: not available -- {self.blocked_reason}",
                            evidence=BLOCKED)]
        try:
            return list(self.run(game) or [])
        except Exception as exc:  # noqa: BLE001 -- deliberate, see docstring
            return [Finding(self.name, CONTEXT,
                            f"{self.name} failed: {exc}", evidence=BLOCKED)]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY = {}


def register(detector) -> object:
    """Register a detector instance. Names must be unique.

    Registration is explicit rather than by import-time scanning, because the
    registry doubles as the pre-registered hypothesis family: the count of what
    is being tested has to be knowable by reading one list, not by discovering
    what happened to be imported.
    """
    if detector.name in _REGISTRY:
        raise DetectorError(f"detector {detector.name!r} is already registered")
    _REGISTRY[detector.name] = detector
    return detector


def registry() -> dict:
    return dict(_REGISTRY)


def clear_registry() -> None:
    _REGISTRY.clear()


def run_all(game, detectors=None) -> list:
    """Every detector against one game, ranked."""
    source = registry() if detectors is None else detectors
    chosen = list(source.values()) if isinstance(source, dict) else list(source)
    findings = []
    for detector in chosen:
        findings.extend(detector.safe_run(game))
    return rank(findings)


def rank(findings) -> list:
    """Signals first, then debunks, then context; stronger evidence above weaker;
    most surprising first within that.

    Context never outranks a signal even when it carries a large number, because
    context is by definition the stuff the reader already assumes.

    Evidence sits ABOVE surprise in the ordering, and it has to. Surprise
    measures how far a number is from normal, not whether that distance means
    anything. A detector we have measured against outcomes and found not to
    predict them can still produce a spectacular-looking gap, and before this
    term existed such a claim would lead the page purely on size -- putting the
    one thing we know does not work at the top, above claims nobody has ruled
    out. Sorting by evidence first puts refuted claims where they belong:
    visible, still true as facts, and below the open questions.
    """
    strength = {name: index for index, name in enumerate(EVIDENCE_ORDER)}

    def key(finding):
        tier = {SIGNAL: 0, DEBUNK: 1, CONTEXT: 2}[finding.kind]
        return (tier, -strength.get(finding.evidence, 0),
                0 if not finding.unscored else 1,
                -(finding.surprise or 0.0))
    return sorted(findings, key=key)


def surprise_score(value, baseline, spread) -> float:
    """How far from normal, in units of normal variation.

    Returns None when spread is missing or zero rather than dividing by it. A
    detector with no measured spread cannot honestly claim a surprise magnitude,
    and returning a large number because the denominator was tiny is the classic
    way a noise finding reaches the top of a ranked list.
    """
    if value is None or baseline is None or not spread:
        return None
    return round(abs(value - baseline) / spread, 3)
