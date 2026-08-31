"""The strategy genome: what evolution is allowed to vary, and nothing else.

NOTHING IN THIS PACKAGE IS EVIDENCE. See registry.py's docstring and
docs/EVOLAB_DESIGN.md sections 11 and 15.

WHAT A GENOME IS
----------------
Design section 3, six modules, kept modular so Phase B crossover can swap one
without touching the rest:

    eligibility  -- which markets, how many books, must the lineup be up
    signals      -- <= MAX_SIGNALS (feature, threshold_index, weight) triples
    combination  -- weighted_sum or k_of_n
    entry        -- min_score, min_confirmations
    routing      -- market preference order and the first-five condition
    execution    -- held CONSTANT during predictive search (design section 5)

THE THREE STRUCTURAL REFUSALS
-----------------------------
Each removes noise-fitting capacity that demonstrably killed a real family
here, and each is a REFUSAL rather than a penalty, because a penalty can be
outrun by a large enough apparent effect:

1. No direction anywhere. `validate` walks the whole incoming structure and
   rejects any key named sign/direction/polarity/flip/invert/negate/reverse at
   any depth, even if its value is harmless. The sign lives in the registry
   (registry.py) and is not reachable from here.

   The subtle half of the same rule: **a weight must be strictly positive.** A
   negative weight is a sign flip wearing a costume -- it makes a signal count
   against the side its mechanism points at -- and it would defeat the registry
   completely while passing any "no direction field" check. Zero is refused
   too: a zero-weight signal is decoration that still consumes a slot from the
   complexity cap.

2. Complexity is capped. At most MAX_SIGNALS signals, threshold indices drawn
   from a fixed three-rung ladder, no nesting.

3. No feature without a mechanism, enforced by refusing any feature the
   registry does not know.

Plus one that falls out of the above: **no duplicate feature.** The same
feature at two ladder rungs is one signal counted twice -- it inflates a
weighted sum with a single measurement and reads as two confirmations when
there is one. The refusal is by FEATURE, not by (feature, rung).

ENUMERATION ORDER IS PART OF THE SPEC
-------------------------------------
`enumerate_genomes` is deterministic and its ordering is documented on the
function. That matters twice: the CSCV table of design section 8 is indexed by
position, and the enumeration spec hash has to describe a space that is the
same space on the next run. Registry iteration is sorted, never insertion
order, for exactly this reason.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from itertools import combinations, product

from src.evolab.registry import DEFAULT_REGISTRY, MAX_SIGNALS, RegistryError

# Any key with one of these names, at any depth of an incoming genome, is a
# refusal. They are the names a search process would reach for to reintroduce
# a searchable sign. The check is on the KEY, not the value: a genome that
# carries `"direction": None` is still a genome someone built a slot for.
FORBIDDEN_KEYS = frozenset({
    "sign", "signs", "direction", "directions", "polarity", "flip", "invert",
    "inverted", "negate", "reverse", "reversed", "side_rule",
})

# Markets the lab may name. Tuples, not free strings, so adding one is a
# visible edit here rather than a stringly-typed drive-by -- the same
# discipline funnel.MARKETS uses.
MARKETS = ("h2h", "h2h_1st_5_innings")
F5_MARKET = "h2h_1st_5_innings"

COMBINATION_RULES = ("weighted_sum", "k_of_n")

# When a first-five market may be selected. "never" is full-game only;
# "if_all_signals_first_five" allows F5 only when every registered signal in
# the genome has FIRST_FIVE scope, so a full-game mechanism can never be
# routed into a market that settles before it applies.
F5_CONDITIONS = ("never", "if_all_signals_first_five")

# Design section 5. CONSENSUS_EXECUTION is the primary mode and is held
# identical across the population during predictive search, so no strategy can
# win by execution while claiming prediction.
EXECUTION_MODES = ("CONSENSUS_EXECUTION", "SPECIFIC_BOOK_EXECUTION",
                   "BEST_OBSERVED_EXECUTION")
DEFAULT_EXECUTION = "CONSENSUS_EXECUTION"

# The weight vectors enumeration uses, per signal count. All-ones plus one
# double-weighted position: enough for weighted_sum to express something
# k_of_n cannot (one signal carrying the score alone), without opening a
# continuous magnitude axis that would multiply the space by nothing useful.
# Phase B mutation tunes magnitudes freely; enumeration does not.
ENUM_WEIGHT_VECTORS = {
    1: ((1.0,),),
    2: ((1.0, 1.0), (2.0, 1.0), (1.0, 2.0)),
    3: ((1.0, 1.0, 1.0), (2.0, 1.0, 1.0), (1.0, 2.0, 1.0), (1.0, 1.0, 2.0)),
}


class GenomeError(RuntimeError):
    """Raised when a genome cannot be built or validated honestly."""


@dataclass(frozen=True)
class Signal:
    feature: str
    threshold_index: int
    weight: float


@dataclass(frozen=True)
class Eligibility:
    markets: tuple
    min_books: int
    require_lineup: bool


@dataclass(frozen=True)
class Combination:
    rule: str
    k: int = 0          # meaningful only for k_of_n; 0 elsewhere, never None,
                        # so the canonical JSON has one shape for every genome


@dataclass(frozen=True)
class Entry:
    min_score: float
    min_confirmations: int


@dataclass(frozen=True)
class Routing:
    market_preference: tuple
    f5_condition: str


@dataclass(frozen=True)
class Genome:
    """A validated strategy. Frozen: a genome that mutates after validation is
    a genome nobody validated."""

    eligibility: Eligibility
    signals: tuple
    combination: Combination
    entry: Entry
    routing: Routing
    execution: str
    # The fingerprint of the registry this genome was validated against. Not
    # a searchable field -- validate() sets it from the registry and refuses
    # any incoming value that disagrees. It exists because the same three
    # signals decided under a registry with different frozen signs are a
    # different strategy that bets the other side, and nothing else in the
    # genome would notice the swap. decide() checks it.
    registry_fingerprint: str = ""

    def to_dict(self) -> dict:
        """The canonical dict form -- what gets hashed and what gets stored."""
        return {
            "eligibility": asdict(self.eligibility),
            "signals": [asdict(s) for s in self.signals],
            "combination": asdict(self.combination),
            "entry": asdict(self.entry),
            "routing": asdict(self.routing),
            "execution": self.execution,
            "registry_fingerprint": self.registry_fingerprint,
        }

    @property
    def strategy_id(self) -> str:
        """A content hash of the genome: stable, and its lineage founder id.

        Content-addressed rather than sequential so the same genome enumerated
        in two different runs (or two different spaces) carries the same id,
        which is what design section 10's lineage needs to join across worlds.
        """
        return _sha256_of(self.to_dict())[:16]


def _sha256_of(obj) -> str:
    """Hash of a canonical JSON rendering: sorted keys, no whitespace slack.

    sort_keys is the whole point -- dict insertion order must not reach the
    hash, or the same genome hashes differently depending on how it was built.
    """
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         default=list)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_forbidden_keys(node, path="genome"):
    """Walk an incoming structure and refuse any direction-shaped key."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_KEYS:
                raise GenomeError(
                    f"{path}.{key}: a genome may not carry a direction. The "
                    "sign of every feature is frozen in the registry with its "
                    "written mechanism, precisely so no search process can "
                    "flip it -- that flip is how research families V4 and V5 "
                    "died. Remove the field; it has no effect anywhere")
            _reject_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            _reject_forbidden_keys(value, f"{path}[{i}]")


def validate(spec, registry=DEFAULT_REGISTRY) -> Genome:
    """A validated Genome from a plain dict, or GenomeError.

    Hard validation with no coercion or defaulting of anything meaningful: a
    field silently defaulted is a strategy nobody actually specified, which is
    the same lesson funnel.validate_spec records.
    """
    if isinstance(spec, Genome):
        spec = spec.to_dict()
    if not isinstance(spec, dict):
        raise GenomeError(
            f"a genome must be a dict, got {type(spec).__name__}")
    _reject_forbidden_keys(spec)

    missing = [k for k in ("eligibility", "signals", "combination", "entry",
                           "routing", "execution") if k not in spec]
    if missing:
        raise GenomeError(f"genome is missing {missing}")

    eligibility = _validated_eligibility(spec["eligibility"])
    signals = _validated_signals(spec["signals"], registry)
    combination = _validated_combination(spec["combination"], len(signals))
    entry = _validated_entry(spec["entry"], signals, combination)
    routing = _validated_routing(spec["routing"], eligibility, signals,
                                 registry)

    execution = spec["execution"]
    if execution not in EXECUTION_MODES:
        raise GenomeError(f"execution must be one of {EXECUTION_MODES}, got "
                          f"{execution!r}")

    fingerprint = registry.fingerprint()
    carried = spec.get("registry_fingerprint")
    if carried and carried != fingerprint:
        raise GenomeError(
            f"genome was built against registry {carried} but is being "
            f"validated against {fingerprint}; the frozen signs, ladders or "
            "scopes differ, so this is a different strategy wearing the same "
            "signals. Re-enumerate against the registry you mean to use")

    return Genome(eligibility=eligibility, signals=signals,
                  combination=combination, entry=entry, routing=routing,
                  execution=execution, registry_fingerprint=fingerprint)


def _validated_eligibility(node) -> Eligibility:
    if not isinstance(node, dict):
        raise GenomeError("eligibility must be a dict")
    for key in ("markets", "min_books", "require_lineup"):
        if key not in node:
            raise GenomeError(f"eligibility is missing {key!r}")
    markets = tuple(node["markets"])
    if not markets:
        raise GenomeError("eligibility.markets must name at least one market")
    bad = [m for m in markets if m not in MARKETS]
    if bad:
        raise GenomeError(f"eligibility.markets {bad} are not among {MARKETS}")
    if len(set(markets)) != len(markets):
        raise GenomeError("eligibility.markets repeats a market")
    min_books = node["min_books"]
    if not isinstance(min_books, int) or isinstance(min_books, bool) \
            or min_books < 1:
        raise GenomeError("eligibility.min_books must be an int >= 1 -- a "
                          "price quoted by nobody is not a price")
    require_lineup = node["require_lineup"]
    if not isinstance(require_lineup, bool):
        raise GenomeError("eligibility.require_lineup must be a bool")
    return Eligibility(markets=markets, min_books=min_books,
                       require_lineup=require_lineup)


def _validated_signals(node, registry) -> tuple:
    if not isinstance(node, (list, tuple)):
        raise GenomeError("signals must be a list")
    if not node:
        raise GenomeError("a genome with no signals has no hypothesis")
    if len(node) > MAX_SIGNALS:
        raise GenomeError(
            f"{len(node)} signals exceeds MAX_SIGNALS={MAX_SIGNALS}. The cap "
            "is structural, not a penalty: a penalty can be outrun by a large "
            "enough apparent effect")

    out = []
    for i, raw in enumerate(node):
        if not isinstance(raw, dict):
            raise GenomeError(f"signals[{i}] must be a dict")
        extra = sorted(set(raw) - {"feature", "threshold_index", "weight"})
        if extra:
            raise GenomeError(
                f"signals[{i}] carries unknown field(s) {extra}; a signal is "
                "exactly a feature, a ladder rung and a positive weight")
        feature = raw.get("feature")
        try:
            spec = registry.get(feature)
        except RegistryError as exc:
            raise GenomeError(
                f"signals[{i}]: {exc}. A feature reaches the lab only through "
                "the registry, which requires a written mechanism") from exc
        index = raw.get("threshold_index")
        try:
            spec.threshold(index)
        except RegistryError as exc:
            raise GenomeError(f"signals[{i}]: {exc}") from exc
        weight = raw.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            raise GenomeError(f"signals[{i}]: weight must be a number")
        if not weight > 0:
            raise GenomeError(
                f"signals[{i}]: weight must be > 0, got {weight}. A negative "
                "weight is a sign flip wearing a costume -- it makes a signal "
                "count against the side its frozen mechanism points at -- and "
                "a zero weight is decoration that still spends a slot of the "
                "complexity cap")
        out.append(Signal(feature=feature, threshold_index=int(index),
                          weight=float(weight)))

    features = [s.feature for s in out]
    dupes = sorted({f for f in features if features.count(f) > 1})
    if dupes:
        raise GenomeError(
            f"duplicate feature(s) {dupes}: the same feature at two ladder "
            "rungs is one signal counted twice -- it inflates a weighted sum "
            "from a single measurement and reads as two confirmations when "
            "there is one")

    # CANONICAL ORDER, by feature name. Not cosmetic: decide() sums weights in
    # this order, and float addition is not associative, so two genomes that
    # differ only in the order their signals were written would otherwise be
    # able to produce different scores from identical inputs.
    return tuple(sorted(out, key=lambda s: s.feature))


def _validated_combination(node, n_signals) -> Combination:
    if not isinstance(node, dict):
        raise GenomeError("combination must be a dict")
    rule = node.get("rule")
    if rule not in COMBINATION_RULES:
        raise GenomeError(f"combination.rule must be one of "
                          f"{COMBINATION_RULES}, got {rule!r}")
    k = node.get("k", 0)
    if rule == "k_of_n":
        if not isinstance(k, int) or isinstance(k, bool):
            raise GenomeError("combination.k must be an int for k_of_n")
        if not 1 <= k <= n_signals:
            raise GenomeError(
                f"combination.k must be between 1 and the {n_signals} "
                f"signal(s) present, got {k}; k > n can never fire and k < 1 "
                "is no rule at all")
    else:
        if k not in (0, None):
            raise GenomeError(
                "combination.k is meaningful only for k_of_n; leave it out "
                "rather than carrying a number the rule ignores")
        k = 0
    return Combination(rule=rule, k=k)


def _validated_entry(node, signals, combination) -> Entry:
    if not isinstance(node, dict):
        raise GenomeError("entry must be a dict")
    for key in ("min_score", "min_confirmations"):
        if key not in node:
            raise GenomeError(f"entry is missing {key!r}")
    min_score = node["min_score"]
    if not isinstance(min_score, (int, float)) or isinstance(min_score, bool):
        raise GenomeError("entry.min_score must be a number")
    if not min_score > 0:
        raise GenomeError("entry.min_score must be > 0 -- at or below zero "
                          "the gate admits a genome whose signals all stayed "
                          "silent")
    min_conf = node["min_confirmations"]
    if not isinstance(min_conf, int) or isinstance(min_conf, bool):
        raise GenomeError("entry.min_confirmations must be an int")
    if not 1 <= min_conf <= len(signals):
        raise GenomeError(
            f"entry.min_confirmations must be between 1 and the "
            f"{len(signals)} signal(s) present, got {min_conf}")

    # An unreachable gate is a strategy that can never trade, and enumerating
    # them would pad the multiplicity denominator with strategies that were
    # never really asked. The largest attainable score is every signal firing
    # for one side.
    reachable = sum(s.weight for s in signals) if \
        combination.rule == "weighted_sum" else float(len(signals))
    if min_score > reachable:
        raise GenomeError(
            f"entry.min_score {min_score} exceeds the maximum attainable "
            f"score {reachable}; this genome could never fire")
    return Entry(min_score=float(min_score), min_confirmations=min_conf)


def _validated_routing(node, eligibility, signals, registry) -> Routing:
    if not isinstance(node, dict):
        raise GenomeError("routing must be a dict")
    for key in ("market_preference", "f5_condition"):
        if key not in node:
            raise GenomeError(f"routing is missing {key!r}")
    preference = tuple(node["market_preference"])
    if not preference:
        raise GenomeError("routing.market_preference must name at least one "
                          "market")
    if len(set(preference)) != len(preference):
        raise GenomeError("routing.market_preference repeats a market")
    outside = [m for m in preference if m not in eligibility.markets]
    if outside:
        raise GenomeError(
            f"routing.market_preference {outside} are not in "
            f"eligibility.markets {eligibility.markets}; preferring a market "
            "the genome is not eligible for is a rule with no effect")
    f5 = node["f5_condition"]
    if f5 not in F5_CONDITIONS:
        raise GenomeError(f"routing.f5_condition must be one of "
                          f"{F5_CONDITIONS}, got {f5!r}")
    if f5 == "never" and F5_MARKET in preference:
        raise GenomeError(
            f"routing prefers {F5_MARKET} while f5_condition is 'never'; one "
            "of the two is a mistake and guessing which is not our job")
    if f5 == "if_all_signals_first_five" and F5_MARKET in preference:
        full = sorted({s.feature for s in signals
                       if registry.get(s.feature).scope != "FIRST_FIVE"})
        if full:
            raise GenomeError(
                f"routing prefers {F5_MARKET} but feature(s) {full} carry a "
                "FULL_GAME mechanism; a mechanism that needs nine innings "
                "cannot be settled after five")
    return Routing(market_preference=preference, f5_condition=f5)


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

def _attainable_min_scores(weights) -> tuple:
    """Every distinct positive subset sum of `weights`, ascending.

    The full set of min_score values worth enumerating, and no others. A
    min_score below the smallest weight behaves exactly like the smallest
    weight; one above the total can never fire. Both would enumerate
    strategies nobody asked, and every enumerated strategy is counted in the
    multiplicity denominator whether or not it could ever trade.
    """
    sums = {0.0}
    for w in weights:
        sums |= {s + w for s in sums}
    return tuple(sorted(s for s in sums if s > 0))


def enumerate_genomes(registry=DEFAULT_REGISTRY, *, eligibility=None,
                      routings=None, execution=DEFAULT_EXECUTION,
                      max_signals=MAX_SIGNALS,
                      weight_vectors=None) -> tuple:
    """The full genome space, in a stable documented order.

    ORDER, outermost first. Every level is a sort or a declared tuple; no
    level is a set or a dict iteration, because those would make the order an
    accident of hashing:

      1. signal count, ascending (1, then 2, then 3)
      2. feature combination, in `itertools.combinations` order over
         `registry.features()` -- which is sorted, so this is lexicographic
      3. threshold indices, odometer order over the ladder with the LAST
         signal varying fastest (`itertools.product` order)
      4. combination rule, in the declared COMBINATION_RULES order
      5. within weighted_sum: weight vector in declared order, then min_score
         ascending over the attainable subset sums
      6. within k_of_n: k ascending
      7. routing, in the order the caller passed them

    WHAT IS AN AXIS AND WHAT IS A PARAMETER
    ---------------------------------------
    Signals, combination and entry are axes. Eligibility, routing and
    execution are PARAMETERS with defaults, deliberately: design section 5
    holds execution identical across the whole population during predictive
    search, so that no strategy can win by execution while claiming
    prediction. Sweeping routing is legal (pass several `routings`) but it is
    the caller's explicit choice, not something the default space does behind
    their back.

    KNOWN, DELIBERATE REDUNDANCY
    ----------------------------
    Some enumerated genomes overlap behaviourally -- weighted_sum with equal
    weights and min_score m accepts the same confirmation sets as k_of_n with
    k = m. They are not de-duplicated, because two genomes with the same
    accept-set can still disagree when signals confirm OPPOSITE sides, so a
    de-duplication would have to reason about side conflicts and would be a
    subtle correctness risk for a small saving. The redundancy inflates the
    multiplicity denominator, which errs in the safe direction: it makes the
    placebo ceiling harder to clear, never easier.
    """
    if eligibility is None:
        eligibility = {"markets": ("h2h",), "min_books": 3,
                       "require_lineup": True}
    if routings is None:
        routings = ({"market_preference": ("h2h",), "f5_condition": "never"},)
    routings = tuple(routings)
    if not routings:
        raise GenomeError("enumerate_genomes needs at least one routing")
    if not 1 <= max_signals <= MAX_SIGNALS:
        raise GenomeError(
            f"max_signals must be between 1 and MAX_SIGNALS={MAX_SIGNALS}, "
            f"got {max_signals}")
    vectors = ENUM_WEIGHT_VECTORS if weight_vectors is None else weight_vectors

    features = registry.features()
    out = []
    for n in range(1, max_signals + 1):
        if n > len(features):
            break
        for combo in combinations(features, n):
            ladders = [range(len(registry.get(f).ladder)) for f in combo]
            for indices in product(*ladders):
                for rule in COMBINATION_RULES:
                    if rule == "weighted_sum":
                        bodies = [
                            ({"rule": "weighted_sum"}, weights, min_score)
                            for weights in vectors[n]
                            for min_score in _attainable_min_scores(weights)]
                    else:
                        # k_of_n reads counts, not magnitudes, so enumerating
                        # it at anything but equal weights would emit genomes
                        # that differ only in a field the rule never looks at.
                        if n == 1:
                            # k=1 over one signal is weighted_sum with weight
                            # 1 and min_score 1, exactly. Emitting both would
                            # be a duplicate with no compensating expressive
                            # power -- the only case where that is provable
                            # without reasoning about opposite-side conflicts.
                            continue
                        ones = tuple(1.0 for _ in range(n))
                        bodies = [({"rule": "k_of_n", "k": k}, ones, float(k))
                                  for k in range(1, n + 1)]
                    for combination, weights, min_score in bodies:
                        signals = [
                            {"feature": f, "threshold_index": idx,
                             "weight": w}
                            for f, idx, w in zip(combo, indices, weights)]
                        min_conf = (combination["k"]
                                    if combination["rule"] == "k_of_n" else 1)
                        for routing in routings:
                            out.append(validate({
                                "eligibility": eligibility,
                                "signals": signals,
                                "combination": combination,
                                "entry": {"min_score": min_score,
                                          "min_confirmations": min_conf},
                                "routing": routing,
                                "execution": execution,
                            }, registry))
    return tuple(out)


def enumeration_spec(registry=DEFAULT_REGISTRY, *, eligibility=None,
                     routings=None, execution=DEFAULT_EXECUTION,
                     max_signals=MAX_SIGNALS, weight_vectors=None) -> dict:
    """The complete description of an enumeration, for hashing and recording.

    Everything that changes the space is in here, including the registry's
    ladders and frozen directions: a run whose ladders moved has enumerated a
    different space and must not be compared with an earlier one as though it
    had not. Design section 11 requires every artifact to record this hash.
    """
    vectors = ENUM_WEIGHT_VECTORS if weight_vectors is None else weight_vectors
    return {
        "schema": "evolab.genome/1",
        "max_signals": max_signals,
        "combination_rules": list(COMBINATION_RULES),
        "weight_vectors": {str(n): [list(v) for v in vs]
                           for n, vs in sorted(vectors.items())},
        "execution": execution,
        "eligibility": (eligibility if eligibility is not None else
                        {"markets": ["h2h"], "min_books": 3,
                         "require_lineup": True}),
        "routings": [dict(r) for r in (routings if routings is not None else
                                       [{"market_preference": ["h2h"],
                                         "f5_condition": "never"}])],
        "registry": [
            {"feature": s.feature, "direction": s.direction,
             "ladder": list(s.ladder), "scope": s.scope}
            for s in registry.specs()],
    }


def spec_hash(spec) -> str:
    """The content hash of an enumeration spec: sorted-key canonical JSON."""
    return _sha256_of(spec)
