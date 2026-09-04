"""Wraps a validated evolab `Genome` as an `AnalysisSystem`.

EQUIVALENCE, NOT REIMPLEMENTATION
-----------------------------------
This adapter does not re-derive the genome's decision logic. It calls
`src.evolab.decide.decide_with_reason` directly, against a `WorldView` it
rebuilds from the `PriceBlindSnapshot` it was handed. That is deliberate:
"the equivalence obligation" (docs/ENGINE_CONTRACT.md) means the waist must
answer identically to evolab's own decision API on the same inputs, and the
only way a divergence can honestly be attributed to "the adapter or the
waist, never evolab" is if evolab's own function is the one being called,
not a second copy of its rules that could silently drift from the first.

`WorldView.board` (the price-shaped field `decide()` reads for book counts
and simultaneity -- never for a price value; see decide.py's own docstring:
the genome's `score` is never edge, and `decide()` performs no de-vig, no
price comparison, nothing price-shaped) is reconstructed here from
`PriceBlindSnapshot.books_by_market` and `.point_meta`, which is exactly the
subset of board information decide() actually reads -- book presence and
counts, not price levels. This is not a leak: PriceBlindSnapshot never
carried a price to begin with, so nothing rebuilt from it can carry one
either. `propose()` never reads `PricedBoard` at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.board.ids import selection_id as _selection_id
from src.board.record import PriceObservation
from src.engine.analyze import Proposal
from src.engine.analyze import analyze as _analyze
from src.engine.snapshot import PriceBlindSnapshot, PricedBoard
from src.evolab.decide import BoardMeta, WorldView, decide_with_reason
from src.evolab.genome import F5_MARKET, Genome, enumerate_genomes
from src.evolab.registry import DEFAULT_REGISTRY
from src.ledger.records import (
    PROBABILITY_PROVENANCE_MARKET_DERIVED,
    PROBABILITY_PROVENANCE_NONE,
    PROBABILITY_PROVENANCE_PLACEHOLDER,
    RECORD_PROVENANCE_REPLAY,
)


def _rebuild_worldview(genome: Genome, snapshot: PriceBlindSnapshot) -> WorldView:
    meta = snapshot.point_meta
    board_meta = BoardMeta(
        observed_utc=snapshot.t,
        books=(),
        simultaneous=(meta.simultaneous if meta is not None else False),
        staleness_seconds=(meta.staleness_seconds if meta is not None else 0),
    )
    # decide() only ever calls `worldview.books_for(market)` (a count) and
    # `worldview.board_meta.simultaneous` -- never a price out of `board`.
    # An empty per-book dict of the declared count-worth of placeholder
    # entries reproduces `books_for`'s `len(...)` exactly without carrying a
    # single price value.
    board = {
        market: {f"__book_{i}": {} for i in range(count)}
        for market, count in snapshot.books_by_market.items()
        if count > 0
    }
    return WorldView(
        game_id=snapshot.game_pk,
        official_date=snapshot.t[:10],
        commence_time=snapshot.t,
        point_class=snapshot.point_class,
        game={},
        features=dict(snapshot.features),
        board=board,
        board_meta=board_meta,
        available=tuple(snapshot.available_markets),
        lineup_posted=snapshot.lineup_posted,
    )


@dataclass(frozen=True)
class EvolabGenomeSystem:
    """An `AnalysisSystem` wrapping one validated evolab `Genome`."""

    genome: Genome
    registry: object = DEFAULT_REGISTRY
    id: str = ""
    version: str = "evolab-1"
    spec_hash: str = ""
    declared_markets: tuple = ()
    declared_inputs: tuple = ()
    min_grade: str = "D"
    expected_selection_rate: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", self.genome.strategy_id)
        if not self.spec_hash:
            object.__setattr__(self, "spec_hash", self.genome.strategy_id)

    def propose(self, view: PriceBlindSnapshot) -> tuple:
        worldview = _rebuild_worldview(self.genome, view)
        decision, reason = decide_with_reason(
            self.genome, worldview, registry=self.registry)
        if not decision:
            return ()
        # A genome's `score` is explicitly NOT a probability or an edge
        # (decide.py's own docstring). It cannot be projected onto a price
        # as a p_model without inventing information the genome never
        # claimed to have, so this adapter reports p_model=None: PROJECT's
        # edge_bps is then honestly None for evolab-origin proposals too,
        # and the equivalence check below compares the SELECTION only
        # (market, side), which is the entire output surface `decide()`
        # actually promises.
        return (Proposal(
            system_id=self.id,
            system_version=self.version,
            market_key=decision.market,
            side=decision.side,
            p_model_provenance=PROBABILITY_PROVENANCE_NONE,
            thesis=f"evolab genome {self.genome.strategy_id}: "
                   f"{decision.signals_fired}",
            evidence=(f"score={decision.score!r}",
                      f"execution_mode={decision.execution_mode}"),
        ),)


# ---------------------------------------------------------------------------
# Two more trivial null controls (B6 fix): siblings of
# `src.engine.glue.TrivialAlwaysHomeSystem` for the two markets a genome
# structurally cannot name (`src.evolab.genome.MARKETS` is h2h and the F5
# h2h mirror only -- see the note above `REGISTERED_F5_GENOME_COUNT`).
#
# Each is a NULL CONTROL, not a strategy: a fixed, pre-registered direction
# never derived from price, a clock, or a search process, exactly the same
# posture `TrivialAlwaysHomeSystem` already takes for h2h.
#
# N2/honesty fix (2026-09-04): both now carry the SAME fixed-convention
# posture `TrivialAlwaysHomeSystem` does -- a `p_model` that is a declared
# constant (0.5, a coin flip, chosen for having no informational content at
# all), `p_model_provenance="placeholder"`. Before this fix these two used
# `p_model=None` specifically to dodge fabricating an edge from a made-up
# number (the flagged N2 defect was `TrivialAlwaysHomeSystem`'s 0.52 doing
# exactly that) -- now that `analyze()`/`DecisionRecord` enforce the
# edge-requires-model_derived invariant structurally (raise, not warn), that
# workaround is no longer needed: naming the placeholder plainly is more
# honest than hiding it behind an absent probability, and it is
# structurally impossible for either control to produce a non-null
# `edge_bps` regardless. `value_basis` still records `price_standing_only`
# for every decision either one produces (src.engine.analyze.analyze), same
# as every evolab-origin proposal.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TrivialAlwaysHomeSpreadSystem:
    """Null control for the spreads (run line) market: always proposes the
    HOME side, unconditionally. The direction is frozen here, at
    construction, mirroring `TrivialAlwaysHomeSystem`'s own frozen home-side
    convention for h2h rather than inventing a second, unrelated one for
    this market -- there is no claim about the run-line NUMBER, only about
    which team's side of it this control always takes."""

    id: str = "trivial_always_home_spread"
    version: str = "trivial-1"
    spec_hash: str = "trivial_always_home_spread:1"
    declared_markets: tuple = ("spreads",)
    declared_inputs: tuple = ()
    min_grade: str = "D"
    expected_selection_rate: float = 1.0
    p_model: float = 0.5

    def propose(self, view: PriceBlindSnapshot) -> tuple:
        if "spreads" not in view.available_markets:
            return ()
        return (Proposal(
            system_id=self.id, system_version=self.version,
            market_key="spreads", side="home", p_model=self.p_model,
            p_model_provenance=PROBABILITY_PROVENANCE_PLACEHOLDER,
            thesis="null control for spreads: always proposes home on the "
                   "run line, a fixed direction never derived from price "
                   "or a clock; p_model is a declared coin-flip constant "
                   "(provenance=placeholder), so no edge_bps can ever be "
                   "computed for this market -- "
                   "src.engine.adapters.evolab_system",
            evidence=("trivial_fallback_spreads",),
        ),)


@dataclass(frozen=True, slots=True)
class TrivialUnderTotalSystem:
    """Null control for the totals market: always proposes UNDER,
    unconditionally. The direction is frozen at construction, never derived
    from price, a clock, or a search process -- the same posture
    `TrivialAlwaysHomeSystem` takes for h2h, applied to the one side pair
    (over/under) this market actually has."""

    id: str = "trivial_under_total"
    version: str = "trivial-1"
    spec_hash: str = "trivial_under_total:1"
    declared_markets: tuple = ("totals",)
    declared_inputs: tuple = ()
    min_grade: str = "D"
    expected_selection_rate: float = 1.0
    p_model: float = 0.5

    def propose(self, view: PriceBlindSnapshot) -> tuple:
        if "totals" not in view.available_markets:
            return ()
        return (Proposal(
            system_id=self.id, system_version=self.version,
            market_key="totals", side="under", p_model=self.p_model,
            p_model_provenance=PROBABILITY_PROVENANCE_PLACEHOLDER,
            thesis="null control for totals: always proposes under, a "
                   "fixed direction never derived from price or a clock; "
                   "p_model is a declared coin-flip constant "
                   "(provenance=placeholder), so no edge_bps can ever be "
                   "computed for this market -- "
                   "src.engine.adapters.evolab_system",
            evidence=("trivial_fallback_totals",),
        ),)


# ---------------------------------------------------------------------------
# The MARKET_DERIVED probability, zero-parameter (docs/PREREG_CALIBRATED_
# PROBABILITY.md §1-2): p_model is the board's own de-vigged consensus for
# the selection, republished under the identity map -- no recalibration
# intercept, no Platt, no isotonic refit. This is NOT a strategy: it makes
# no directional claim, has no thesis beyond "the market's own price", and
# is never staked on value grounds (`edge_bps` is structurally None for
# every provenance but `model_derived` -- src.engine.analyze.analyze /
# src.ledger.records.DecisionRecord).
#
# `propose()` runs at PROPOSE time, price-blind by construction
# (PriceBlindSnapshot carries no price field), so it CANNOT compute its own
# p_model here -- it proposes with `p_model=None` and names its provenance
# as `market_derived`; `analyze()`'s PROJECT phase is where the identity map
# actually happens, filling `p_model` in from `board.consensus(...)` per
# selection (see analyze.py's PROJECT loop). This class exists only to name
# the (market, side) pairs worth republishing a consensus for and to declare
# the provenance -- it carries no pricing logic of its own, on purpose:
# there must be exactly one de-vig implementation in this codebase for the
# identity to hold by construction rather than by two independent
# implementations happening to agree (§6.5's named wiring-failure risk).
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MarketDerivedConsensusSystem:
    """Republishes the board's own de-vigged consensus for one (market,
    side) as `p_model`, verbatim, via the identity map. Zero fitted
    parameters; `p_model` is filled in by PROJECT, not here."""

    market_key: str
    side: str
    version: str = "market-derived-1"
    declared_markets: tuple = ()
    declared_inputs: tuple = ()
    min_grade: str = "D"
    expected_selection_rate: float = 1.0
    id: str = ""
    spec_hash: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self, "id", f"market_derived_consensus_{self.market_key}_{self.side}")
        if not self.spec_hash:
            object.__setattr__(self, "spec_hash", f"{self.id}:1")
        if not self.declared_markets:
            object.__setattr__(self, "declared_markets", (self.market_key,))

    def propose(self, view: PriceBlindSnapshot) -> tuple:
        if self.market_key not in view.available_markets:
            return ()
        return (Proposal(
            system_id=self.id, system_version=self.version,
            market_key=self.market_key, side=self.side, p_model=None,
            p_model_provenance=PROBABILITY_PROVENANCE_MARKET_DERIVED,
            thesis=(
                "MARKET_DERIVED, zero-parameter: p_model is the board's "
                "own de-vigged consensus for this selection, republished "
                "under the identity map by analyze()'s PROJECT phase -- no "
                "recalibration intercept, no Platt, no isotonic refit "
                "(docs/PREREG_CALIBRATED_PROBABILITY.md §2). Not a "
                "strategy: edge_bps is structurally None; this may be "
                "published as prediction confidence only."
            ),
            evidence=("market_derived_identity_map",),
        ),)


# One instance per (market, side) pair across the four SCOPE_MARKETS
# (src/engine/slate.py's own scope boundary) -- republishing the consensus
# is meaningful for every side of every scoped market, not just h2h/home.
MARKET_DERIVED_SYSTEMS: tuple = tuple(
    MarketDerivedConsensusSystem(market_key=market, side=side)
    for market, sides in (
        ("h2h", ("home", "away")),
        ("spreads", ("home", "away")),
        ("totals", ("over", "under")),
        (F5_MARKET, ("home", "away")),
    )
    for side in sides
)


# ---------------------------------------------------------------------------
# Registered systems for the vertical slice (checkpoint doc S5, item 5): the
# trivial always-home null control plus a small, DETERMINISTICALLY chosen
# set of enumerated genomes, each with a stable id so accounts and
# scorecards can key on it across re-runs.
# ---------------------------------------------------------------------------

# How many enumerated genomes to register alongside the trivial control.
# Chosen small on purpose (checkpoint doc: "say 8-16") -- this is the
# starting population for the slice, not a sweep; mutation/retirement are
# explicitly out of scope (docs/CHECKPOINT_PHASE0_2026-09-03.md S5 closing
# note).
REGISTERED_GENOME_COUNT = 12

# B6 fix (slice-review-2026-09-03): SCOPE_MARKETS (src/engine/slate.py) names
# four markets, but until this module registered ANY system whose eligibility
# and routing actually named a market other than plain h2h, the scope filter
# was a no-op -- every registered genome enumerated with
# `enumerate_genomes()`'s own h2h-only defaults, and F5_MARKET
# ("h2h_1st_5_innings") sat in `genome.MARKETS` fully validated but never
# selected by any caller. The routing GENE is real (`Routing.market_preference`,
# `Routing.f5_condition`) and every registered feature's mechanism is scoped
# FIRST_FIVE (src/evolab/registry.py), so `f5_condition="if_all_signals_first_five"`
# is satisfiable by construction for every genome this registry can produce --
# nothing here invents a probability or a mechanism that was not already
# frozen in the registry; it only exercises a genome axis that was reachable
# in code but never called with non-default arguments.
#
# `genome.MARKETS` itself only names ("h2h", "h2h_1st_5_innings") -- spreads
# and totals are not, and were never meant to be, expressible as a genome:
# the registry's mechanisms are moneyline-direction claims (which SIDE the
# matchup favours), not point-margin or total-runs claims, and inventing a
# spread/total direction for them would be exactly the unjustified-sign
# problem registry.py's own docstring refuses. Spreads and totals are
# instead covered below by explicitly named, pre-registered NON-genome null
# controls, siblings of `src.engine.glue.TrivialAlwaysHomeSystem`, each with
# a frozen direction and p_model=None (no calibrated probability is claimed,
# so PROJECT's edge_bps and RATE's rating stay honestly None/absent for them,
# exactly like every evolab-origin proposal already does).
REGISTERED_F5_GENOME_COUNT = 4

# The F5 eligibility/routing pair: eligible for the F5 market only, and
# routed to it unconditionally once `if_all_signals_first_five` is checked
# (true for every genome this registry enumerates -- see note above).
# `min_books=3` matches the h2h default; L1's own h2h_1st_5_innings rows
# carry 8-9 quoting books at every observed decision instant to date, so the
# bar is not doing any real narrowing here, only staying consistent with the
# rest of the population.
F5_ELIGIBILITY: dict = {
    "markets": (F5_MARKET,), "min_books": 3, "require_lineup": True,
}
F5_ROUTINGS: tuple = (
    {"market_preference": (F5_MARKET,),
     "f5_condition": "if_all_signals_first_five"},
)


def _select_registered_genomes(n: int = REGISTERED_GENOME_COUNT,
                                registry=DEFAULT_REGISTRY, *,
                                eligibility=None, routings=None) -> tuple:
    """`n` genomes spread evenly across `enumerate_genomes()`'s own
    deterministic order (docs/EVOLAB_DESIGN.md / genome.py: "ENUMERATION
    ORDER IS PART OF THE SPEC"), rather than the first `n` -- an even spread
    samples across signal counts/feature combinations/entry thresholds
    instead of clustering on the single-signal end of the space. Purely a
    function of `enumerate_genomes()`'s own fixed order, `eligibility`,
    `routings` and `n`: the same call always returns the same genomes, in
    the same order, forever (until one of those or the registry itself
    changes, all of which are visible edits here, not a silent drift).
    `eligibility`/`routings` default to `None`, which is
    `enumerate_genomes()`'s own h2h-only default -- unchanged from before
    this function grew the two parameters.
    """
    genomes = enumerate_genomes(registry=registry, eligibility=eligibility,
                                routings=routings)
    if not genomes:
        return ()
    if n >= len(genomes):
        return tuple(genomes)
    step = len(genomes) / n
    indices = sorted({int(i * step) for i in range(n)})
    return tuple(genomes[i] for i in indices)


REGISTERED_GENOMES: tuple = _select_registered_genomes()
REGISTERED_F5_GENOMES: tuple = _select_registered_genomes(
    REGISTERED_F5_GENOME_COUNT, eligibility=F5_ELIGIBILITY,
    routings=F5_ROUTINGS)
REGISTERED_EVOLAB_SYSTEMS: tuple = tuple(
    EvolabGenomeSystem(genome=g) for g in REGISTERED_GENOMES) + tuple(
    EvolabGenomeSystem(genome=g) for g in REGISTERED_F5_GENOMES)


def _trivial_system():
    # Imported lazily (function-local) rather than at module scope: glue.py
    # does not import this module, so there is no real import cycle, but
    # importing it here keeps this module usable in contexts (tests,
    # scripts/engine_equivalence.py) that have no reason to touch glue.py's
    # own disk-reading helpers just to get the trivial control's class.
    from src.engine.glue import TrivialAlwaysHomeSystem
    return TrivialAlwaysHomeSystem()


# The trivial always-home null control, then its two sibling null controls
# for the other two markets a genome cannot honestly name (spreads, totals),
# then the registered genomes (h2h, then F5) in their own deterministic
# order -- REGISTERED_SYSTEMS's own ORDER is not meaningful (callers key on
# `.id`), but it is fixed so printed reports are stable across runs.
REGISTERED_SYSTEMS: tuple = (
    (_trivial_system(), TrivialAlwaysHomeSpreadSystem(),
     TrivialUnderTotalSystem())
    + MARKET_DERIVED_SYSTEMS
    + REGISTERED_EVOLAB_SYSTEMS
)

# Recorded (task item 5: "chosen deterministically and recorded") -- the
# exact strategy_ids REGISTERED_GENOMES/REGISTERED_F5_GENOMES resolved to, at
# the time this module was written, for a human to cross-check
# enumerate_genomes() has not silently reordered:
#   see `python3 -c "from src.engine.adapters.evolab_system import
#   REGISTERED_SYSTEMS; print([s.id for s in REGISTERED_SYSTEMS])"`


# ---------------------------------------------------------------------------
# S3: the replay driver -- historical replay through analyze(), not through
# decide_with_reason directly.
#
# docs/CHECKPOINT_PHASE0_2026-09-03.md S3: "Make historical replay run
# through analyze() instead of calling decide_with_reason directly ... for a
# 2023-24 game, build[ ] the board and snapshot through src/engine/glue.py
# (same functions the live path uses) and call[ ] analyze()." Live glue.py
# reads L1 off disk (data/processed/l1_observations.jsonl), which carries no
# 2023-24 rows at all (S1's forward-only capture); this driver instead hands
# glue.build_board/build_snapshot the SAME real prices and features the
# sealed replay universe's own WorldView already carries (src.evolab.replay,
# the exact mechanism scripts/engine_equivalence.py already used for its own
# proof) as their `observations=`/`features=` arguments -- the two
# CONSTRUCTION FUNCTIONS are identical to the live path; only where the
# bytes come from differs. `game_pk_map={}` is passed through explicitly:
# the S1 event_id<->game_pk map is a 2026-forward-capture concept with
# nothing to resolve for a 2023-24 replay event_id, so this opts out of ever
# touching that real (2026-scoped) store rather than silently finding it
# empty for a different reason.
# ---------------------------------------------------------------------------

def historical_snapshot_and_board(game, T: str, *, point_class: str | None = None
                                   ) -> tuple[PriceBlindSnapshot, PricedBoard]:
    """The (snapshot, board) pair for one 2023-24 replay `game` at `T`,
    built through `src.engine.glue.build_board`/`build_snapshot` -- the SAME
    two functions the live path calls -- fed with the real h2h prices and
    features `src.evolab.replay.world_view` already assembled for this
    (game, T). `game` is a `src.evolab.replay.ReplayGame` (or anything
    `world_view` accepts); `T` is one of that game's own observed instants
    (`world_view` refuses to interpolate one).
    """
    from src.engine import glue as glue_module
    from src.evolab import replay as replay_module

    view = replay_module.world_view(game, T, point_class=point_class)
    ref = glue_module.GameRef(event_id=str(view.game_id))

    rows: list[PriceObservation] = []
    for market, books in view.board.items():
        for book, sides in books.items():
            for side, price_key in (("home", "home_price"), ("away", "away_price")):
                price = sides.get(price_key)
                if price is None:
                    continue
                sel = _selection_id(sport="mlb", market_key=market, side=side)
                rows.append(PriceObservation(
                    sport="mlb", event_id=view.game_id, game_pk=None,
                    market_key=market, selection_id=sel, side=side,
                    subject_kind=None, subject_id=None, line=None,
                    book=book, price_american=int(price),
                    observed_utc=view.board_meta.observed_utc,
                    book_last_update=None,
                    known_at=view.board_meta.observed_utc, known_at_grade="A",
                    capture_id="replay_driver", source="evolab_replay",
                    region="us", provider_market_key=market,
                    l0_available=False,
                ))

    board = glue_module.build_board(
        ref, view.board_meta.observed_utc, observations=rows,
        commence_time=view.commence_time, game_pk_map={})
    snapshot = glue_module.build_snapshot(
        ref, view.board_meta.observed_utc, point_class=view.point_class,
        features=view.features, board=board, lineup_posted=view.lineup_posted,
        game_pk_map={})
    return snapshot, board


def replay_decision(genome_or_system, game, T: str, *,
                     point_class: str | None = None,
                     registry=DEFAULT_REGISTRY,
                     adversaries: tuple = ()):
    """S3: run ONE historical replay decision point through `analyze()`.

    `genome_or_system` is either a validated `Genome` (wrapped here in a
    fresh `EvolabGenomeSystem`) or an already-built `AnalysisSystem` (used
    as-is -- e.g. the trivial control, which has no genome at all).
    `adversaries=()` matches `analyze()`'s and the equivalence proof's own
    default (docs/ENGINE_CONTRACT.md section 6: the adversary roster is an
    engine-side addition with no evolab counterpart) -- pass
    `src.engine.adversaries.DEFAULT_ADVERSARIES` explicitly to exercise the
    roster instead. Returns the `Analysis`.

    Every record this produces carries
    `record_provenance="replay"` (B1, slice-review-2026-09-03) -- this
    driver only ever decides an already-past, already-known `T` (`world_view`
    refuses to interpolate one), and its output is a demonstration, never
    written to any ledger.
    """
    snapshot, board = historical_snapshot_and_board(game, T, point_class=point_class)
    if isinstance(genome_or_system, Genome):
        system = EvolabGenomeSystem(genome=genome_or_system, registry=registry)
    else:
        system = genome_or_system
    return _analyze(snapshot, board, systems=(system,), adversaries=adversaries,
                    record_provenance=RECORD_PROVENANCE_REPLAY)
