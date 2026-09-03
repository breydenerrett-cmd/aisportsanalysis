#!/usr/bin/env python3
"""Equivalence proof: src.engine.analyze() vs src.evolab.decide() directly.

Runs the SAME genomes over the SAME (game, T) decision points from the real
2023 replay universe through both paths and asserts they name the same
selection (market, side) -- decide()'s entire output surface, per
src/engine/adapters/evolab_system.py's docstring on why the adapter compares
selection only and not a fabricated p_model.

Per the task packet: target is 8,811 genomes x 200 decision points; this
script runs as many as fit in the time budget it is given (default ~10
minutes) and reports what it actually ran. Any divergence is logged as a bug
in the adapter or the waist -- per instructions, NEVER attributed to evolab.

Usage:
    python3 scripts/engine_equivalence.py [--seconds 600] [--max-genomes N]
                                          [--max-points N] [--seasons 2023]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.board.ids import selection_id as _selection_id
from src.board.record import PriceObservation
from src.engine.adapters.evolab_system import EvolabGenomeSystem
from src.engine.analyze import analyze
from src.engine.snapshot import PointMeta, PriceBlindSnapshot, PricedBoard
from src.evolab import replay
from src.evolab.decide import decide_with_reason
from src.evolab.genome import enumerate_genomes
from src.evolab.registry import DEFAULT_REGISTRY


def snapshot_and_board_from_worldview(view) -> tuple:
    """The one place a WorldView is split into the waist's two halves, for
    this proof only -- production code builds PriceBlindSnapshot/PricedBoard
    from as_of()/PriceObservation directly (src/engine/snapshot.py), never
    from a WorldView. This function exists so the SAME real decision points
    evolab's own replay loader already produces can drive both paths without
    a second, parallel data-loading path that could disagree with the first
    about what a game's board looked like at T.

    The REAL h2h quotes on `view.board` (the only market this replay store
    carries) are copied into PriceObservation rows for the PricedBoard half
    -- this is legitimate here because PricedBoard is the PROJECT-only,
    price-carrying half of the waist; only PriceBlindSnapshot (built without
    ever reading view.board's prices) must never see them.
    """
    books_by_market = {m: len(view.board.get(m) or {}) for m in view.available}
    snapshot = PriceBlindSnapshot.from_asof(
        game_pk=view.game_id, t=view.commence_time, point_class=view.point_class,
        features=view.features, available_markets=view.available,
        books_by_market=books_by_market,
        point_meta=PointMeta(observed_utc=view.board_meta.observed_utc,
                             simultaneous=view.board_meta.simultaneous,
                             staleness_seconds=view.board_meta.staleness_seconds),
        lineup_posted=view.lineup_posted,
    )

    rows = []
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
                    capture_id="equivalence-proof", source="evolab_replay",
                    region="us", provider_market_key=market,
                    l0_available=False,
                ))
    board = PricedBoard.from_price_observations(
        view.game_id, view.commence_time, tuple(rows))
    return snapshot, board


def run(seasons, max_genomes, max_points, seconds_budget) -> dict:
    t_start = time.time()
    universe = replay.load_universe(list(seasons))
    points = list(replay.decision_points(list(seasons), universe=universe))
    if max_points:
        points = points[:max_points]

    genomes = enumerate_genomes()
    if max_genomes:
        genomes = genomes[:max_genomes]

    games_by_pk = {g.game_pk: g for g in universe.games}

    n_compared = 0
    n_agree = 0
    divergences = []
    genomes_run = 0

    for genome in genomes:
        if time.time() - t_start > seconds_budget:
            break
        genomes_run += 1
        system = EvolabGenomeSystem(genome=genome, registry=DEFAULT_REGISTRY)
        for point in points:
            if time.time() - t_start > seconds_budget:
                break
            game = games_by_pk.get(point.game_pk)
            if game is None:
                continue
            try:
                view = replay.world_view(game, point.T,
                                         point_class=point.point_class)
            except Exception:
                continue

            evolab_decision, _reason = decide_with_reason(
                genome, view, registry=DEFAULT_REGISTRY)
            snapshot, board = snapshot_and_board_from_worldview(view)
            analysis = analyze(snapshot, board, systems=(system,))

            n_compared += 1
            engine_played = bool(analysis.records)
            evolab_played = bool(evolab_decision)
            if engine_played != evolab_played:
                divergences.append({
                    "genome": genome.strategy_id, "game_pk": point.game_pk,
                    "T": point.T, "kind": "play_vs_no_play",
                    "evolab": bool(evolab_decision), "engine": engine_played})
                continue
            if not evolab_played:
                n_agree += 1
                continue
            rec = analysis.records[0]
            expected_selection = _selection_id(
                sport="mlb", market_key=evolab_decision.market,
                side=evolab_decision.side)
            if rec.market_key == evolab_decision.market and \
                    rec.selection_id == expected_selection:
                n_agree += 1
            else:
                divergences.append({
                    "genome": genome.strategy_id, "game_pk": point.game_pk,
                    "T": point.T, "kind": "selection_mismatch",
                    "evolab": (evolab_decision.market, evolab_decision.side),
                    "engine": (rec.market_key, rec.selection_id)})

    elapsed = time.time() - t_start
    return {
        "seasons": list(seasons),
        "genomes_available": len(enumerate_genomes()) if not max_genomes else None,
        "genomes_run": genomes_run,
        "decision_points_available": len(points) if not max_points else None,
        "decision_points_used": len(points),
        "n_compared": n_compared,
        "n_agree": n_agree,
        "n_divergences": len(divergences),
        "divergences_sample": divergences[:20],
        "elapsed_seconds": round(elapsed, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=540.0,
                        help="wall-clock budget in seconds (default 540s)")
    parser.add_argument("--max-genomes", type=int, default=0,
                        help="0 = no cap (use the full enumerated population)")
    parser.add_argument("--max-points", type=int, default=200,
                        help="decision points to use (0 = all)")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2023])
    args = parser.parse_args()

    result = run(args.seasons, args.max_genomes,
                args.max_points if args.max_points else None, args.seconds)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["n_divergences"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
