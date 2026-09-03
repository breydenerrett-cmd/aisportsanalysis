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

from src.engine.analyze import Proposal
from src.engine.snapshot import PriceBlindSnapshot
from src.evolab.decide import BoardMeta, WorldView, decide_with_reason
from src.evolab.genome import Genome
from src.evolab.registry import DEFAULT_REGISTRY


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
