#!/usr/bin/env python3
"""Thin CLI entry for the Phase 2B sweep driver (src/evolab/sweep.py).

Data plane, not model reasoning: this script builds a `ReplayFeed` from a
fixture file and calls `sweep.run_sweep`, exactly as any other caller would.
It contains no strategy logic of its own.

NOT A REAL-STORE RUNNER YET. The real run -- against the actual replay
engine and the live odds/matrix stores -- is a Fable-reviewed event that
happens once `src/evolab/replay.py` lands, and is deliberately not wired in
here (docs/EVOLAB_DESIGN.md sections 11 and 15). This script only accepts a
FIXTURE: a JSON file describing a synthetic or hand-built world, useful for
smoke-testing the plumbing end to end. Running it against a fixture produces
no evidence and promotes nothing, same as everything else in `src/evolab/`.

FIXTURE FORMAT
--------------
A JSON object: `{"games": [ { "game_id", "date", "season", "home_team",
"away_team", "home_price", "away_price", "home_won" (bool or null),
"features" (object of "away_<feature>"/"home_<feature>" -> number or null),
"home_fair_close" (number or null, optional) }, ... ]}`. Every field maps
directly onto `placebo.make_game`'s arguments.

USAGE
-----
    python3 scripts/evolab_sweep.py --fixture path/to/fixture.json \\
        [--out-dir data/research/evolab] [--replicates 10] [--base-seed 0] \\
        [--min-selections 30] [--n-blocks 10] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evolab import placebo, sweep  # noqa: E402


def _load_fixture(path: str) -> placebo.World:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    games = []
    for row in payload["games"]:
        games.append(placebo.make_game(
            game_id=row["game_id"], date=row["date"], season=row["season"],
            home_team=row["home_team"], away_team=row["away_team"],
            home_price=row["home_price"], away_price=row["away_price"],
            home_won=row.get("home_won"), features=row.get("features") or {},
            home_fair_close=row.get("home_fair_close"),
        ))
    return placebo.real_world(games)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", required=True,
                        help="path to a fixture JSON file (see module "
                             "docstring); the real replay engine is not "
                             "wired into this script")
    parser.add_argument("--out-dir", default=sweep.ARTIFACT_ROOT,
                        help=f"must resolve inside {sweep.ARTIFACT_ROOT}/ "
                             "(default: %(default)s)")
    parser.add_argument("--replicates", type=int,
                        default=placebo.DEFAULT_REPLICATES)
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--n-blocks", type=int, default=sweep.DEFAULT_N_BLOCKS)
    parser.add_argument("--min-selections", type=int,
                        default=sweep.DEFAULT_MIN_SELECTIONS)
    parser.add_argument("--spa-n-bootstrap", type=int,
                        default=sweep.DEFAULT_SPA_N_BOOTSTRAP)
    parser.add_argument("--spa-seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true",
                        help="run the sweep and print the report; do not "
                             "write an artifact")
    args = parser.parse_args(argv)

    def provider() -> sweep.ReplayFeed:
        return sweep.ReplayFeed(world=_load_fixture(args.fixture), manifest=None)

    report = sweep.run_sweep(
        provider, n_blocks=args.n_blocks, min_selections=args.min_selections,
        replicates=args.replicates, base_seed=args.base_seed,
        spa_n_bootstrap=args.spa_n_bootstrap, spa_seed=args.spa_seed)

    print(f"real world: {report.real_world_id} "
          f"({report.n_games_real} games, {report.n_strategies_real} "
          "strategies cleared the gate)")
    print(f"real champion: {report.real_champion} "
          f"(movement {report.real_max_movement:.6f})")
    print(f"VERDICT: {report.ceiling.verdict}")
    print(report.ceiling.verdict_reason)
    print(f"CSCV PBO: {report.cscv.pbo:.4f}")
    print(f"SPA p-value ({report.spa.variant}): {report.spa.p_value:.4f}")
    print(f"SPA cross-check: {report.spa_cross_check_status} -- "
          f"{report.spa_cross_check_explanation}")
    if report.p4_dispersion:
        print(f"P4 dispersion diagnostic: {report.p4_dispersion}")
    for w in report.warnings:
        print(f"warning: {w}")

    if not args.dry_run:
        path = report.write(args.out_dir)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
