"""The deterministic decision API: one genome, one WorldView, one answer.

NOTHING IN THIS PACKAGE IS EVIDENCE. See registry.py's docstring and
docs/EVOLAB_DESIGN.md sections 11 and 15.

PURITY IS THE POINT
-------------------
`decide` performs no I/O, reads no clock, draws no randomness and mutates no
global state. Everything it can see arrives in its two arguments. The same
genome and the same WorldView therefore produce a byte-identical Decision
forever, which is what makes design section 14's determinism test meaningful
and what lets 51 worlds be replayed and compared at all.

The module imports nothing that could break that: dataclasses, and the
registry's frozen specs. The default registry is write-once (registering a
feature twice raises), so "global state" here is a constant, not a variable.

WHY THE WORLDVIEW HAS NO OUTCOME AND NO CLOSING PRICE
-----------------------------------------------------
Not filtered out -- ABSENT. `WorldView.__getattr__` raises a loud, specific
error for every outcome-shaped and close-shaped name, and the class uses
__slots__ so nobody can attach one later either. A feature dict key with one
of those names is refused at construction.

This is the single most important correctness property in the lab, and it is
structural for the same reason the sign lives in the registry: a rule that
depends on everyone remembering it is a rule that fails on the day someone is
in a hurry. It mirrors how `statcast_pitches.iter_rows(before=)` already works
-- future rows are not hidden from the caller, they were never read.

TIE-BREAKING, STATED EXPLICITLY
-------------------------------
Design section 4 forbids resolving a tie by "whichever book sorted first". The
rules, in order, and there is no fourth:

  1. If exactly one side passes the entry gate, that side is the selection.
  2. If both sides pass, the side with the strictly greater score wins.
  3. If the scores are exactly equal, the side with strictly more
     confirmations wins.
  4. If those are equal too, the answer is NO_PLAY with reason
     CONFLICTING_SIGNALS.

Rule 4 is a refusal, not a coin flip. A genome whose own signals point both
ways with equal force has not identified a side; picking one by alphabet or by
board order would manufacture a selection the strategy never made, and half of
those manufactured selections would win, which is precisely the kind of
apparent edge this lab exists to measure rather than to create.

Scores are compared for EXACT float equality. That is safe here only because
score accumulation is fully ordered: genome.validate sorts signals by feature
name, and this module sums weights in that order, so two runs perform the same
additions in the same sequence and produce the same bits. Without that
canonical order, exact comparison would be a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.evolab.genome import F5_MARKET, Genome
from src.evolab.registry import DEFAULT_REGISTRY

# Attribute names the WorldView must never answer to. Two families: the game's
# result, and any price from after the decision instant. Spelled out rather
# than pattern-matched so the error message can name the rule, and so adding
# one is a visible edit.
FORBIDDEN_ATTRIBUTES = frozenset({
    # outcomes
    "outcome", "outcomes", "result", "results", "winner", "won", "home_won",
    "away_won", "final", "final_score", "runs", "runs_scored", "settled",
    "graded", "label", "target", "y_true",
    # anything from after T
    "close", "closing", "closing_price", "closing_prices", "closing_line",
    "closing_odds", "close_price", "clv", "closing_board", "future",
})

# Reason labels. They are the death-reason vocabulary of design section 9
# where one already exists, so autopsy reporting is a lookup rather than a
# translation layer.
NO_LINEUP = "NO_LINEUP"
MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
INSUFFICIENT_BOOKS = "INSUFFICIENT_BOOKS"
NOT_SIMULTANEOUS = "NOT_SIMULTANEOUS"
NO_SIGNAL = "NO_SIGNAL"
BELOW_ENTRY = "BELOW_ENTRY"
CONFLICTING_SIGNALS = "CONFLICTING_SIGNALS"

SIDES = ("away", "home")


class WorldViewError(RuntimeError):
    """Raised when a WorldView would be built with something it must not
    see."""


@dataclass(frozen=True)
class BoardMeta:
    """Design section 2's board_meta: what the board is and how fresh it is.

    `simultaneous` is the honesty flag for BEST_OBSERVED_EXECUTION: if the
    quotes on this board were stitched across time rather than observed at one
    instant, best-price execution is disabled outright rather than reported
    with a caveat (design section 5).
    """

    observed_utc: str
    books: tuple = ()
    simultaneous: bool = False
    staleness_seconds: int = 0


@dataclass(frozen=True, slots=True)
class WorldView:
    """Everything visible at one decision point, and structurally nothing else.

    This is the minimal stand-in the design's section 2 describes. The real
    assembler -- which builds these from the point-in-time stores and owns the
    leak-proof generators -- lands separately once the Phase 0 feasibility
    audit fixes the decision-point ladder and the replay universe. Code
    against these fields; the swap is meant to be invisible here.

    __slots__ is load-bearing, not tidiness: it stops anyone attaching an
    `outcome` to a WorldView after construction, which is how a leak would
    actually arrive in practice.
    """

    game_id: str
    official_date: str
    commence_time: str
    point_class: str
    game: dict
    features: dict
    board: dict
    board_meta: BoardMeta
    available: tuple = ()
    lineup_posted: bool = False

    def __post_init__(self):
        bad = sorted(k for k in self.features
                     if str(k).lower() in FORBIDDEN_ATTRIBUTES)
        if bad:
            raise WorldViewError(
                f"features {bad} name an outcome or a post-decision price. A "
                "WorldView carries what was knowable at T and nothing else; "
                "the future is absent here, not filtered")

    def __getattr__(self, name):
        """Raise loudly for outcome- and close-shaped names, plainly otherwise.

        Reached only when normal slot lookup fails, so it cannot shadow a real
        field. It touches no attribute of self, because a __getattr__ that
        does can recurse forever on a half-built object.
        """
        if name.lower() in FORBIDDEN_ATTRIBUTES:
            raise AttributeError(
                f"WorldView has no {name!r} and never will. Outcomes and "
                "closing prices are absent from the decision path by "
                "construction (docs/EVOLAB_DESIGN.md section 2); if you need "
                "one for scoring, take it from the fitness layer, which runs "
                "after every decision is already fixed")
        raise AttributeError(f"WorldView has no attribute {name!r}")

    def differential(self, feature):
        """away_<feature> - home_<feature>, or None if either side is absent.

        The one place the away-minus-home convention is applied, matching
        src/research/funnel.py's sign convention exactly. None over guess:
        half a differential is not a differential.
        """
        away = self.features.get("away_" + feature)
        home = self.features.get("home_" + feature)
        if away is None or home is None:
            return None
        return away - home

    def books_for(self, market) -> int:
        """How many books quote `market` on this board. 0 when absent."""
        return len(self.board.get(market) or {})


class _NoPlay:
    """The singleton no-selection answer. Falsy, so `if decide(...)` reads
    correctly, and a singleton so callers can use `is NO_PLAY`."""

    __slots__ = ()

    def __repr__(self):
        return "NO_PLAY"

    def __bool__(self):
        return False


NO_PLAY = _NoPlay()


@dataclass(frozen=True)
class Decision:
    """One selection. `score` is the genome's own combined score, NOT an edge.

    It is a weighted count of fired signals in the genome's units and has no
    interpretation as expected value, probability or advantage. Naming it
    anything edge-shaped would invite exactly the confusion the project's
    evidence rules exist to prevent.
    """

    market: str
    side: str
    score: float
    signals_fired: tuple
    execution_mode: str


def decide(genome, worldview, *, registry=DEFAULT_REGISTRY):
    """The Decision for this genome at this decision point, or NO_PLAY.

    Pure. See the module docstring for the determinism and tie-breaking rules;
    they are stated there rather than here because they are properties of the
    whole module, not of this call.
    """
    return decide_with_reason(genome, worldview, registry=registry)[0]


def decide_with_reason(genome, worldview, *, registry=DEFAULT_REGISTRY):
    """(Decision, "") or (NO_PLAY, reason) -- the single implementation.

    The reason is carried out rather than recomputed by a second function,
    because two code paths that must agree about why a genome stood down are
    two code paths that will eventually disagree. Reasons use design section
    9's death-label vocabulary so autopsy reporting is a lookup.
    """
    if not isinstance(genome, Genome):
        raise TypeError(
            "decide takes a validated Genome; call genome.validate first so "
            "the complexity cap and the no-direction rule are enforced before "
            "anything is scored")
    if genome.registry_fingerprint != registry.fingerprint():
        # The frozen signs are the whole strategy. Deciding a genome against a
        # registry whose directions differ would silently bet the other side
        # and nothing downstream would ever notice, so it is refused here
        # rather than caught by whoever reads the results months later.
        raise ValueError(
            f"genome was validated against registry "
            f"{genome.registry_fingerprint} but decide() was handed "
            f"{registry.fingerprint()}; pass the registry the genome was "
            "enumerated with")

    if genome.eligibility.require_lineup and not worldview.lineup_posted:
        return NO_PLAY, NO_LINEUP

    market, reason = _select_market(genome, worldview)
    if market is None:
        return NO_PLAY, reason

    fired = _fired_signals(genome, worldview, registry)
    if not any(side is not None for _, _, side in fired):
        return NO_PLAY, NO_SIGNAL

    passing = []
    for side in SIDES:
        score, confirmations, names = _side_score(genome, fired, side)
        if _passes_entry(genome, score, confirmations):
            passing.append((side, score, confirmations, names))

    if not passing:
        return NO_PLAY, BELOW_ENTRY
    if len(passing) == 1:
        side, score, _, names = passing[0]
    else:
        # Both sides cleared the gate. Rules 2-4 of the module docstring.
        by_side = {entry[0]: entry for entry in passing}
        away, home = by_side["away"], by_side["home"]
        if away[1] != home[1]:
            side, score, _, names = away if away[1] > home[1] else home
        elif away[2] != home[2]:
            side, score, _, names = away if away[2] > home[2] else home
        else:
            return NO_PLAY, CONFLICTING_SIGNALS

    return Decision(market=market, side=side, score=score,
                    signals_fired=names,
                    execution_mode=genome.execution), ""


def _select_market(genome, worldview):
    """(market, "") or (None, reason) -- the first preference that is live.

    Preference order is the genome's, taken in order; nothing here consults
    price, so a genome cannot route itself to whichever market happened to
    offer the better number. That would be MARKET_SELECTION_ADVANTAGE
    (design section 9) dressed as prediction.
    """
    available = set(worldview.available)
    reason = MARKET_UNAVAILABLE
    for market in genome.routing.market_preference:
        if market == F5_MARKET and genome.routing.f5_condition == "never":
            continue
        if market not in available or market not in worldview.board:
            continue
        if worldview.books_for(market) < genome.eligibility.min_books:
            reason = INSUFFICIENT_BOOKS
            continue
        if genome.execution == "BEST_OBSERVED_EXECUTION" and \
                not worldview.board_meta.simultaneous:
            # Design section 5: if the quotes were stitched across time, best
            # price is not a price anybody could have taken. Disabled outright
            # rather than reported with a caveat.
            reason = NOT_SIMULTANEOUS
            continue
        return market, ""
    return None, reason


def _fired_signals(genome, worldview, registry):
    """[(signal, spec, side_or_None)] in the genome's canonical order."""
    out = []
    for signal in genome.signals:
        spec = registry.get(signal.feature)
        differential = worldview.differential(signal.feature)
        side = None
        if spec.fires(differential, signal.threshold_index):
            side = spec.side_for(differential)
        out.append((signal, spec, side))
    return out


def _side_score(genome, fired, side):
    """(score, confirmations, fired_names) for one side.

    The sum runs over `fired` in the genome's canonical signal order -- sorted
    by feature name at validation -- so the float additions happen in the same
    sequence on every run and on every machine. This is what makes the exact
    equality comparison in the tie-break rule sound.
    """
    score = 0.0
    confirmations = 0
    names = []
    for signal, _spec, fired_side in fired:
        if fired_side != side:
            continue
        confirmations += 1
        names.append((signal.feature, signal.threshold_index))
        score += signal.weight
    if genome.combination.rule == "k_of_n":
        # k_of_n reads counts, never magnitudes: its score IS the confirmation
        # count, so a weight can never buy a strategy past a count rule.
        score = float(confirmations)
    return score, confirmations, tuple(names)


def _passes_entry(genome, score, confirmations) -> bool:
    if confirmations < genome.entry.min_confirmations:
        return False
    if genome.combination.rule == "k_of_n" and \
            confirmations < genome.combination.k:
        return False
    return score >= genome.entry.min_score
