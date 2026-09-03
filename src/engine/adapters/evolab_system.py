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
from src.evolab.genome import Genome, enumerate_genomes
from src.evolab.registry import DEFAULT_REGISTRY
from src.ledger.records import RECORD_PROVENANCE_REPLAY


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
            thesis=f"evolab genome {self.genome.strategy_id}: "
                   f"{decision.signals_fired}",
            evidence=(f"score={decision.score!r}",
                      f"execution_mode={decision.execution_mode}"),
        ),)


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


def _select_registered_genomes(n: int = REGISTERED_GENOME_COUNT,
                                registry=DEFAULT_REGISTRY) -> tuple:
    """`n` genomes spread evenly across `enumerate_genomes()`'s own
    deterministic order (docs/EVOLAB_DESIGN.md / genome.py: "ENUMERATION
    ORDER IS PART OF THE SPEC"), rather than the first `n` -- an even spread
    samples across signal counts/feature combinations/entry thresholds
    instead of clustering on the single-signal end of the space. Purely a
    function of `enumerate_genomes()`'s own fixed order and `n`: the same
    call always returns the same genomes, in the same order, forever (until
    `n` or the registry itself changes, both of which are visible edits
    here, not a silent drift).
    """
    genomes = enumerate_genomes(registry=registry)
    if not genomes:
        return ()
    if n >= len(genomes):
        return tuple(genomes)
    step = len(genomes) / n
    indices = sorted({int(i * step) for i in range(n)})
    return tuple(genomes[i] for i in indices)


REGISTERED_GENOMES: tuple = _select_registered_genomes()
REGISTERED_EVOLAB_SYSTEMS: tuple = tuple(
    EvolabGenomeSystem(genome=g) for g in REGISTERED_GENOMES)


def _trivial_system():
    # Imported lazily (function-local) rather than at module scope: glue.py
    # does not import this module, so there is no real import cycle, but
    # importing it here keeps this module usable in contexts (tests,
    # scripts/engine_equivalence.py) that have no reason to touch glue.py's
    # own disk-reading helpers just to get the trivial control's class.
    from src.engine.glue import TrivialAlwaysHomeSystem
    return TrivialAlwaysHomeSystem()


# The trivial always-home null control, first, then the registered genomes
# in their own deterministic order -- REGISTERED_SYSTEMS's own ORDER is not
# meaningful (callers key on `.id`), but it is fixed so printed reports are
# stable across runs.
REGISTERED_SYSTEMS: tuple = (_trivial_system(),) + REGISTERED_EVOLAB_SYSTEMS

# Recorded (task item 5: "chosen deterministically and recorded") -- the
# exact strategy_ids REGISTERED_GENOMES resolved to, at the time this module
# was written, for a human to cross-check enumerate_genomes() has not
# silently reordered:
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
