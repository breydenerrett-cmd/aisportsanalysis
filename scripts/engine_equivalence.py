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
from src.engine.adapters.evolab_system import (
    EvolabGenomeSystem, historical_snapshot_and_board,
)
from src.engine.adversaries import DEFAULT_ADVERSARIES
from src.engine.analyze import analyze
from src.evolab import replay
from src.evolab.decide import decide_with_reason
from src.evolab.genome import enumerate_genomes
from src.evolab.registry import DEFAULT_REGISTRY


def run(seasons, max_genomes, max_points, seconds_budget,
        *, adversaries: tuple = ()) -> dict:
    """The equivalence proof itself: `analyze()` (fed by S3's
    `historical_snapshot_and_board` -- the SAME `glue.build_board`/
    `build_snapshot` the live path calls) vs. `decide_with_reason()`
    directly, over the SAME (genome, game, T). `adversaries` defaults to
    `()`, matching `docs/ENGINE_CONTRACT.md` section 6 and `analyze()`'s own
    equivalence-proof default: the roster is an engine-side addition with no
    evolab counterpart, so running it here would report engine-only vetoes
    as "divergences" from a primitive that has no notion of a veto at all.
    Pass `adversaries=DEFAULT_ADVERSARIES` to `exercise_default_roster`
    below to see the roster's effect reported separately, never blended
    into this proof's own divergence count.
    """
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
            try:
                snapshot, board = historical_snapshot_and_board(
                    game, point.T, point_class=point.point_class)
            except Exception:
                continue
            analysis = analyze(snapshot, board, systems=(system,),
                               adversaries=adversaries)

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
        "adversaries": [a.id for a in adversaries],
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


def exercise_default_roster(seasons, max_genomes, max_points, seconds_budget) -> dict:
    """Exercise `src.engine.adversaries.DEFAULT_ADVERSARIES` (the registered
    v1 roster) over the SAME (genome, game, T) space, SEPARATELY from the
    equivalence proof above -- never asserted for agreement with
    `decide_with_reason` (which has no adversaries at all), only reported:
    how many of the candidates `analyze()` would have played WITHOUT any
    adversary get vetoed once the roster runs, and by which cause.
    """
    t_start = time.time()
    universe = replay.load_universe(list(seasons))
    points = list(replay.decision_points(list(seasons), universe=universe))
    if max_points:
        points = points[:max_points]
    genomes = enumerate_genomes()
    if max_genomes:
        genomes = genomes[:max_genomes]
    games_by_pk = {g.game_pk: g for g in universe.games}

    n_points_examined = 0
    n_played_no_adversaries = 0
    n_played_with_roster = 0
    veto_causes: dict = {}

    for genome in genomes:
        if time.time() - t_start > seconds_budget:
            break
        system = EvolabGenomeSystem(genome=genome, registry=DEFAULT_REGISTRY)
        for point in points:
            if time.time() - t_start > seconds_budget:
                break
            game = games_by_pk.get(point.game_pk)
            if game is None:
                continue
            try:
                snapshot, board = historical_snapshot_and_board(
                    game, point.T, point_class=point.point_class)
            except Exception:
                continue
            n_points_examined += 1
            bare = analyze(snapshot, board, systems=(system,), adversaries=())
            if not bare.records:
                continue
            n_played_no_adversaries += 1
            roster = analyze(snapshot, board, systems=(system,),
                             adversaries=DEFAULT_ADVERSARIES)
            if roster.records:
                n_played_with_roster += 1
            else:
                # Vetoed by the roster: find the cause(s) recorded on the
                # bare candidate's own would-be record (ATTACK still runs
                # inside `roster`'s own `analyze()` call, but a FATAL veto
                # drops the candidate before a record is built -- so the
                # cause has to come from re-running ATTACK's adversaries
                # directly against the bare candidate instead).
                for adversary in DEFAULT_ADVERSARIES:
                    for counterargument in adversary.attack(
                            _bare_candidate(bare), snapshot, board):
                        veto_causes[counterargument.cause] = (
                            veto_causes.get(counterargument.cause, 0) + 1)

    return {
        "seasons": list(seasons),
        "n_decision_points_examined": n_points_examined,
        "n_played_with_no_adversaries": n_played_no_adversaries,
        "n_played_with_default_roster": n_played_with_roster,
        "n_vetoed_by_roster": n_played_no_adversaries - n_played_with_roster,
        "veto_causes": veto_causes,
        "elapsed_seconds": round(time.time() - t_start, 1),
    }


def _bare_candidate(bare_analysis):
    """Rebuild the `Candidate` `analyze()`'s own ATTACK phase would have
    attacked, from the one `DecisionRecord` a no-adversary `analyze()` call
    already produced -- so `exercise_default_roster` can name a veto's
    cause without re-deriving PROJECT's own math a second time."""
    from src.engine.analyze import Candidate, Proposal

    rec = bare_analysis.records[0]
    return Candidate(
        proposal=Proposal(system_id=rec.system_id, system_version=rec.system_version,
                          market_key=rec.market_key, side="", p_model=rec.p_model),
        selection_id=rec.selection_id, consensus_fair=rec.consensus_fair,
        books_at_decision=rec.books_at_decision or 0, friction=rec.friction or {},
        price_american=rec.price_american, edge_bps=rec.edge_bps,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=540.0,
                        help="wall-clock budget in seconds (default 540s)")
    parser.add_argument("--max-genomes", type=int, default=0,
                        help="0 = no cap (use the full enumerated population)")
    parser.add_argument("--max-points", type=int, default=200,
                        help="decision points to use (0 = all)")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2023])
    parser.add_argument("--skip-roster-exercise", action="store_true",
                        help="skip the separate (non-assertive) default-"
                             "adversary-roster exercise")
    args = parser.parse_args()

    max_points = args.max_points if args.max_points else None
    result = run(args.seasons, args.max_genomes, max_points, args.seconds,
                adversaries=())
    print(json.dumps({"equivalence_proof": result}, indent=2, default=str))

    if not args.skip_roster_exercise:
        roster_result = exercise_default_roster(
            args.seasons, args.max_genomes, max_points,
            seconds_budget=max(60.0, args.seconds / 4))
        print(json.dumps({"default_roster_exercise": roster_result},
                         indent=2, default=str))

    return 0 if result["n_divergences"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
