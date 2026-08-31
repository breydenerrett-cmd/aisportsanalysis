"""The signal registry: every feature the lab may search, with a frozen sign.

NOTHING IN THIS PACKAGE IS EVIDENCE
-----------------------------------
The Evolution Lab is a sandbox whose first scientific purpose is to measure how
much apparent edge our own search manufactures from noise. Nothing produced
here promotes anything, appends to the research scoreboard, or counts as a
finding. See docs/EVOLAB_DESIGN.md sections 11 and 15.

WHY THE DIRECTION LIVES HERE AND NOT IN THE GENOME
--------------------------------------------------
Research families V4 and V5 both died the same death: a feature screened strong
in 2023 and reversed in 2024. The move that kills you is screen-then-flip --
look at the data, notice the sign is wrong, keep the feature and flip the sign,
and report the flipped version as though it had been predicted. A penalty for
it can be outrun by a large enough apparent effect. A cap cannot.

So the sign is not a searchable parameter anywhere in this package. It is an
attribute of the MECHANISM, written down here in prose before any search runs,
and the genome has no field that can hold it (see genome.py, which refuses any
genome carrying a `sign` or `direction` key at all). Evolution may tune
magnitudes, thresholds, combinations and routing. It can never flip a sign,
because there is no sign for it to reach.

This is the same rule src/research/funnel.py already enforces with
`direction`-before-results pre-registration; the registry is that rule made
structural rather than procedural.

SIGN CONVENTION -- ONE SENTENCE, MEMORISE IT
--------------------------------------------
The matrix carries every feature per side, and a side's features describe the
matchup that side's LINEUP faces: `away_starter_velocity_gap` is the velocity
gap of the starter the AWAY lineup bats against, i.e. the HOME team's starter.
That crossing happens once, in src/research/matrix.py, and is not re-derived
here. The game-level differential is always

    d = away_<feature> - home_<feature>

so `direction = +1` means "the side holding more of this feature is the side
the mechanism favours", and `direction = -1` means "the side holding more of it
is the side the mechanism harms". The side a fired signal points to is then

    AWAY if d * direction > 0 else HOME

which is the funnel's `back_advantaged` / `direction` pair collapsed into one
number. Either side missing means no signal: None over guess, and half a
differential is not a differential.

THE THRESHOLD LADDER IS DERIVED, NOT CHOSEN
-------------------------------------------
Each feature gets exactly three thresholds -- a fixed dose ladder, per design
section 3's complexity cap. They are the 50th, 75th and 90th percentiles of
|d| over the 2023-24 posted-lineup matrix, the SAME three percentiles for every
feature, so no feature can receive a hand-tuned ladder that happens to sit
where its noise is. Nearest-rank percentiles, no interpolation, so the number
is a value the data actually took.

The ladder reads the feature's MARGINAL DISTRIBUTION ONLY. No outcome, no
price, no result touches it, so it cannot encode an edge it then pretends to
discover -- which is why deriving it on the discovery seasons is not a leak.
2023-24 is in any case the explicitly exploratory, non-evidential sandbox.

WHAT IS NOT REGISTERED, AND WHY
-------------------------------
`starter_platoon_gap` is a numeric matrix column and is deliberately ABSENT.
Its value is signed (wOBA against left-handers minus against right-handers),
so a large positive gap helps a left-heavy lineup and hurts a right-heavy one.
There is therefore no sign that is true of the feature alone -- only of the
feature crossed with the facing lineup's handedness, which is what
`lineup_platoon_share` already measures. Freezing a standalone direction for it
would be inventing exactly the unjustified sign this module exists to prevent.
It can be registered the day someone writes the interaction feature that makes
its direction mechanical; until then, absence is the honest answer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from src.research import funnel

# The complexity cap of design section 3, kept here because the registry is
# what a genome's signals are drawn from. Three, not "three unless the effect
# is big": a cap, not a penalty.
MAX_SIGNALS = 3

# A ladder is exactly this long for every feature. A feature with a longer
# ladder would get more shots at the same data than its neighbours, and the
# multiplicity accounting downstream assumes a uniform per-feature budget.
LADDER_LENGTH = 3

# The three percentiles of |away - home| that produce every ladder. Median
# (permissive, roughly half the games), upper quartile, top decile. Identical
# for all features by construction.
LADDER_PERCENTILES = (50.0, 75.0, 90.0)

# A mechanism is a sentence explaining why the market should misprice this,
# not a label. Five words is a low bar deliberately -- it exists to stop
# "momentum" and "it works", not to grade prose.
MIN_MECHANISM_WORDS = 5

# Whether the mechanism's effect is contained in the innings the starting
# pitcher throws. It gates F5 routing in genome.py: a full-game mechanism
# routed to a first-five market is a claim nobody made.
SCOPES = ("FIRST_FIVE", "FULL_GAME")

DIRECTIONS = (-1, 1)


class RegistryError(RuntimeError):
    """Raised when a feature cannot be registered honestly."""


@dataclass(frozen=True)
class SignalSpec:
    """One registered feature: its mechanism, its frozen sign, its ladder.

    Frozen dataclass because a spec that can be mutated after registration is
    a sign that can be flipped after seeing results, which is the whole thing
    this package is built to make impossible.
    """

    feature: str
    mechanism: str
    direction: int
    ladder: tuple
    scope: str
    provenance: str

    def threshold(self, index: int) -> float:
        """The ladder value at `index`, or RegistryError.

        Indexed rather than named because the genome carries an index: an
        index cannot be a number somebody typed, and the set of legal values
        is the length of the ladder.
        """
        if not isinstance(index, int) or isinstance(index, bool):
            raise RegistryError(
                f"{self.feature}: threshold_index must be an int, got "
                f"{type(index).__name__}")
        if not 0 <= index < len(self.ladder):
            raise RegistryError(
                f"{self.feature}: threshold_index {index} is outside the "
                f"ladder 0..{len(self.ladder) - 1}")
        return self.ladder[index]

    def side_for(self, differential):
        """"away", "home", or None -- which side a differential points to.

        None when the differential is absent (either side unmeasured) or
        exactly zero. Zero is not a tie to be broken: at d == 0 neither side
        holds more of the feature, so the mechanism says nothing at all.
        """
        if differential is None or differential == 0:
            return None
        return "away" if differential * self.direction > 0 else "home"

    def fires(self, differential, index: int) -> bool:
        """True when |d| clears the ladder rung and the side is defined."""
        if differential is None:
            return False
        return abs(differential) >= self.threshold(index)


class SignalRegistry:
    """A frozen-once collection of SignalSpecs, keyed by feature name.

    A class rather than a module dict so tests can build small registries
    without touching the real one -- enumeration counts are only checkable by
    hand on a small registry, and the alternative (monkeypatching a global)
    is exactly the mutable-shared-state hazard design section 4 rules out.
    """

    def __init__(self):
        self._specs = {}
        self._order = []

    def register(self, feature, mechanism, direction, ladder, scope,
                 provenance) -> SignalSpec:
        """Add one feature, or RegistryError.

        Every rejection here is a documented failure mode rather than a
        defensive reflex:
          - unknown feature: a typo surfaces downstream as 0% coverage, which
            is indistinguishable from honest data poverty (funnel.py learned
            this the same way).
          - no mechanism: design section 3 rule 3 -- the registry is the gate.
          - bad direction: only -1 and +1 exist; 0 is "no claim" and does not
            get to be a claim.
          - re-registration: the second call is the flip attempt, whether or
            not the sign actually differs.
        """
        if not isinstance(feature, str) or not feature.strip():
            raise RegistryError("feature must be a non-empty string")
        feature = feature.strip()
        if feature in self._specs:
            raise RegistryError(
                f"{feature} is already registered; a registry entry is frozen "
                "on first write, because a second write is where a sign gets "
                "flipped after seeing results")
        if feature not in funnel.NUMERIC_FEATURES:
            raise RegistryError(
                f"{feature!r} is not a numeric matrix column; expected one of "
                f"{funnel.NUMERIC_FEATURES}. The registry may only name "
                "features the point-in-time matrix actually computes")
        if not isinstance(mechanism, str) or \
                len(mechanism.split()) < MIN_MECHANISM_WORDS:
            raise RegistryError(
                f"{feature}: a mechanism of at least {MIN_MECHANISM_WORDS} "
                "words is required -- a feature that cannot say why the "
                "market should misprice it is a data-dredge with a name")
        if direction not in DIRECTIONS or isinstance(direction, bool):
            raise RegistryError(
                f"{feature}: direction must be -1 or +1, got {direction!r}")
        ladder = tuple(ladder)
        if len(ladder) != LADDER_LENGTH:
            raise RegistryError(
                f"{feature}: the ladder must have exactly {LADDER_LENGTH} "
                f"rungs, got {len(ladder)}")
        if any(not isinstance(v, (int, float)) or isinstance(v, bool)
               or v <= 0 for v in ladder):
            raise RegistryError(
                f"{feature}: every ladder rung must be a number > 0 (at 0 the "
                "fired side is undefined)")
        if list(ladder) != sorted(ladder) or len(set(ladder)) != len(ladder):
            raise RegistryError(
                f"{feature}: the ladder must be strictly increasing -- it is "
                "a dose ladder, and two equal rungs are one rung tested twice")
        if scope not in SCOPES:
            raise RegistryError(
                f"{feature}: scope must be one of {SCOPES}, got {scope!r}")
        if not isinstance(provenance, str) or not provenance.strip():
            raise RegistryError(
                f"{feature}: provenance must say where the ladder came from")

        spec = SignalSpec(feature=feature, mechanism=mechanism.strip(),
                          direction=int(direction),
                          ladder=tuple(float(v) for v in ladder),
                          scope=scope, provenance=provenance.strip())
        self._specs[feature] = spec
        self._order.append(feature)
        return spec

    def __contains__(self, feature) -> bool:
        return feature in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def get(self, feature) -> SignalSpec:
        """The spec for `feature`, or RegistryError naming what is known."""
        spec = self._specs.get(feature)
        if spec is None:
            raise RegistryError(
                f"{feature!r} is not registered; registered features are "
                f"{self.features()}")
        return spec

    def features(self) -> tuple:
        """Registered feature names, sorted.

        SORTED, never insertion order: enumeration order is part of the
        enumeration spec hash, and insertion order would make that hash depend
        on the order somebody happened to write the register() calls in.
        """
        return tuple(sorted(self._specs))

    def specs(self) -> tuple:
        """Every spec, in the same sorted order as features()."""
        return tuple(self._specs[f] for f in self.features())

    def fingerprint(self) -> str:
        """A content hash of every frozen sign, ladder and scope.

        A genome means nothing without the sign table it was validated
        against: the same three signals decided under a registry whose
        directions differ are a different strategy that would happily bet the
        other side. So a genome carries this fingerprint and decide() refuses
        a registry that does not match. Content-addressed, so two separately
        constructed registries with identical contents are interchangeable --
        which is what makes the check a correctness guard rather than an
        identity nuisance.
        """
        payload = json.dumps(
            [[s.feature, s.direction, list(s.ladder), s.scope]
             for s in self.specs()],
            sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def pairs(self) -> tuple:
        """Every (feature, threshold_index) pair, sorted then by rung.

        This is the enumeration alphabet and the bitset precompute list of
        design section 12: with 6 features it is 18 pairs, and one mask pair
        gets built per entry, once per world.
        """
        return tuple((f, i) for f in self.features()
                     for i in range(len(self._specs[f].ladder)))


# ---------------------------------------------------------------------------
# The frozen default registry
# ---------------------------------------------------------------------------

# Provenance shared by every ladder below. Recomputable at any time with
# derive_ladder() over the same two files; the counts are per-feature and
# recorded on each entry.
_LADDER_SOURCE = ("nearest-rank p50/p75/p90 of |away-home| over "
                  "data/research/matchup_matrix_{2023,2024}.jsonl, 4,859 "
                  "posted-lineup games")


def _default_registry() -> SignalRegistry:
    """The six features the lab may search, with mechanisms and frozen signs.

    Six, not the matrix's seven: see the module docstring on
    starter_platoon_gap. The mechanism prose is the project's own, carried
    over from the V4 and V5 pre-registrations (data/research/family_v4_*.json,
    family_v5_stuff.json) rather than rewritten here -- these hypotheses were
    stated before their results were known, and restating them now in fresh
    words would quietly relaunder the dates.
    """
    reg = SignalRegistry()

    reg.register(
        feature="lineup_platoon_share",
        mechanism=(
            "the classic exploitation: a lineup posted one-handed against a "
            "starter it holds the platoon advantage over gets more of its "
            "plate appearances in the favourable split than the club-level "
            "season line the market prices ever reflects"),
        direction=+1,
        ladder=(0.222, 0.334, 0.445),
        scope="FIRST_FIVE",
        provenance=_LADDER_SOURCE + "; 4,856 games with both sides measured",
    )

    reg.register(
        feature="lineup_vs_primary_pitch",
        mechanism=(
            "a starter who leans on one pitch, against a lineup that has "
            "measurably hit that pitch, has nowhere to hide for eighteen "
            "outs; the market prices his season line, not tonight's specific "
            "collision"),
        direction=+1,
        ladder=(0.0292, 0.0527, 0.0921),
        scope="FIRST_FIVE",
        provenance=_LADDER_SOURCE + "; 4,048 games with both sides measured",
    )

    reg.register(
        feature="primary_pitch_share",
        mechanism=(
            "concentration in one pitch is predictability: the more of a "
            "starter's arsenal is a single offering, the more of the lineup's "
            "preparation transfers, and pitch-level lean is not a term in any "
            "club-level price"),
        direction=+1,
        ladder=(0.097, 0.163, 0.231),
        scope="FIRST_FIVE",
        provenance=_LADDER_SOURCE + "; 4,061 games with both sides measured",
    )

    reg.register(
        feature="top_minus_bottom",
        mechanism=(
            "a top-heavy order concentrates its best bats where the extra "
            "plate appearances go, and club-level pricing averages that "
            "concentration away; the weakest mechanism of the six, kept "
            "because V4 stated it before seeing its result"),
        direction=+1,
        ladder=(0.0227, 0.0422, 0.0777),
        scope="FIRST_FIVE",
        provenance=_LADDER_SOURCE + "; 4,838 games with both sides measured",
    )

    reg.register(
        feature="starter_velocity_gap",
        mechanism=(
            "a starter whose fastball sits above league pace is holding stuff "
            "the season line has not caught up to, so the lineup facing the "
            "harder thrower is the disadvantaged side; velocity leads results "
            "and the market prices results"),
        direction=-1,
        ladder=(1.9615, 3.3837, 4.7805),
        scope="FIRST_FIVE",
        provenance=_LADDER_SOURCE + "; 3,149 games with both sides measured",
    )

    reg.register(
        feature="starter_groundball_share",
        mechanism=(
            "a career ground-ball starter takes the air out of an offence "
            "that lives on balls in the air, so the lineup facing the higher "
            "ground-ball share is the disadvantaged side and club-level "
            "pricing averages the collision out"),
        direction=-1,
        ladder=(0.0648, 0.1155, 0.1749),
        scope="FIRST_FIVE",
        provenance=_LADDER_SOURCE + "; 3,516 games with both sides measured",
    )

    return reg


DEFAULT_REGISTRY = _default_registry()


def derive_ladder(values, percentiles=LADDER_PERCENTILES) -> tuple:
    """The nearest-rank percentile ladder of `values`, or None if unusable.

    Pure and outcome-blind by construction: it sees a list of numbers and
    nothing else, so a ladder derived with it cannot smuggle in a result. This
    is how the frozen ladders above were produced, and the function is kept so
    the derivation is reproducible rather than merely asserted.

    Nearest-rank, not interpolated: an interpolated percentile is a number the
    feature never took, and a threshold nobody's data ever equalled is a
    slightly fictional dose rung. Returns None when the sample is empty or the
    percentiles collapse onto equal rungs (a feature too degenerate to carry a
    three-rung ladder is one the registry should refuse, not one to paper over
    with duplicate thresholds).
    """
    clean = sorted(abs(v) for v in values if v is not None)
    if not clean:
        return None
    rungs = []
    for p in percentiles:
        # ceil(p/100 * n) without importing math: integer arithmetic keeps the
        # rank exact and identical across platforms.
        rank = -((-int(round(p * 1000)) * len(clean)) // 100000)
        rank = max(1, min(rank, len(clean)))
        rungs.append(clean[rank - 1])
    if len(set(rungs)) != len(rungs) or rungs[0] <= 0:
        return None
    return tuple(rungs)
