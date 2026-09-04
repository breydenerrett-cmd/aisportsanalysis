#!/usr/bin/env python3
"""Reconstruct the 8,811-strategy decision masks for the REAL sweep artifact.

See docs/FACTORY_SCALE_DESIGN.md section 0 and `src/evolab/sweep.py`'s
`WorldFitness.masks`. The existing artifact
(`data/research/evolab/sweep-0014914df78666b9-REAL.json`) was written before
`SweepReport.to_dict()` serialized masks (that gap is closed for FUTURE
sweeps by `sweep.py`'s `include_masks` flag, added alongside this script).
This is the one-off backfill for the artifact that already exists: replay
every genome's DECISION over the exact same real world, deterministically,
and write the resulting masks out-of-band rather than re-running the sweep.

WHY THIS IS A REPLAY, NOT A RE-EVALUATION
------------------------------------------
Only `sweep._side_profiles` / `sweep._resolve_ties` run here -- the same
bitset decision engine `sweep_world` calls, called the same way, over the
same `placebo.World`. Nothing here touches `home_won`, reads
`data/historical/mlb_results.csv`, or computes movement/ROI: this script
builds its `placebo.Game` rows with `home_won=None` and never calls
`feed.read_outcomes`/`feed.join_outcomes` at all, so it is structurally
incapable of reading an outcome. That is a stronger guarantee than "we didn't
use the number" -- the outcome is never loaded into the process.

WHY THE WORLD IS PROVABLY THE SAME ONE THE ARTIFACT USED
-----------------------------------------------------------
`src/evolab/feed.py`'s `resolve_decisions()` is itself deterministic and
already hashes its own output (`decisions_digest`) BEFORE any outcome would
be read. The REAL artifact's `replay_manifest.decision_digest` is exactly
that hash, stamped by `feed.build_feed` when the artifact was produced. This
script recomputes `resolve_decisions()` from the same historical stores and
asserts its digest matches the artifact's stamped one before doing anything
else -- if the underlying historical data has moved on since, this script
refuses rather than silently mask a different world's decisions as this
artifact's.

Likewise, `genome.enumeration_spec`/`spec_hash` over the artifact's own
`config` (registry defaults, eligibility, routings, execution, max_signals --
weight_vectors is not overridden by this project's one real sweep, so the
default is exactly what produced it) is asserted equal to the artifact's
`enumeration_spec_hash` before any genome is scored.

OUTPUT
------
`data/research/evolab/masks-<spec_hash16>.bin` -- for each strategy that
cleared `min_selections`, sorted by `strategy_id`, the away mask then the
home mask, each packed little-endian into a fixed-width byte field
(`ceil(n_games/8)` bytes). `data/research/evolab/masks-<spec_hash16>.index.json`
carries everything needed to read the `.bin` back: strategy order, per-mask
byte width, the world's game order (so bit `i` maps to a `game_pk`), and the
provenance (`decision_digest`, `enumeration_spec_hash`, `source_artifact`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evolab import feed, genome as genome_mod, placebo, replay, sweep  # noqa: E402
from src.evolab.bitsets import build_signal_mask_table, count_bits, universe_mask  # noqa: E402
from src.evolab.registry import DEFAULT_REGISTRY  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = (REPO_ROOT / "data" / "research" / "evolab" /
                 "sweep-0014914df78666b9-REAL.json")
OUT_DIR = REPO_ROOT / "data" / "research" / "evolab"


class ReplayMismatch(RuntimeError):
    """Raised when the replayed world or genome space provably differs from
    what produced the artifact -- refuse rather than mask a different world's
    decisions as this one's."""


def _load_artifact(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _rebuild_world(artifact: dict) -> tuple["placebo.World", str]:
    """The real world, decisions only -- NO outcome store is ever opened.

    Returns (world, decision_digest); the caller asserts the digest against
    the artifact before trusting anything built from this world.
    """
    universe = replay.load_universe(seasons=replay.REPLAY_SEASONS)
    rows, _exclusions = feed.resolve_decisions(universe)
    digest = feed.decisions_digest(rows)
    games = [
        placebo.make_game(
            game_id=row.game_pk, date=row.official_date, season=row.season,
            home_team=row.home_team, away_team=row.away_team,
            home_price=row.home_price, away_price=row.away_price,
            home_won=None,   # structurally: no outcome is read to get here
            features=dict(row.features), home_fair=row.home_fair,
            home_fair_close=row.home_fair_late,
        )
        for row in rows
    ]
    world = placebo.real_world(games, world_id=artifact["real_world_id"])
    return world, digest


def _rebuild_genomes(artifact: dict) -> tuple[list, str]:
    cfg = artifact["config"]
    kwargs = dict(
        registry=DEFAULT_REGISTRY, eligibility=cfg["eligibility"],
        routings=cfg["routings"], execution=cfg["execution"],
        max_signals=cfg["max_signals"], weight_vectors=None)
    spec = genome_mod.enumeration_spec(**kwargs)
    spec_hash = genome_mod.spec_hash(spec)
    genomes = genome_mod.enumerate_genomes(**kwargs)
    return genomes, spec_hash


def _compute_masks(world: "placebo.World", genomes: list,
                   min_selections: int) -> dict[str, tuple[int, int]]:
    """{strategy_id: (away_mask, home_mask)} -- decisions only.

    Exactly `sweep._side_profiles` / `sweep._resolve_ties`, the same private
    functions `sweep_world` calls -- not reimplemented, imported as
    `sweep._side_profiles` etc. below -- so this script cannot silently drift
    from the decision semantics the artifact was actually produced under.
    Movement and ROI (the rest of `sweep_world`'s body) are never computed:
    this is the "decisions only" slice of that function.
    """
    diffs = sweep._differentials_by_feature(world, DEFAULT_REGISTRY)
    mask_table = build_signal_mask_table(DEFAULT_REGISTRY, diffs)
    universe = universe_mask(world.n_games)
    masks = {}
    for g in genomes:
        away_mask, home_mask = sweep._resolve_ties(
            sweep._side_profiles(g, mask_table, universe))
        selected = count_bits(away_mask) + count_bits(home_mask)
        if selected < min_selections:
            continue
        masks[g.strategy_id] = (away_mask, home_mask)
    return masks


def _write_bin_and_index(masks: dict, world: "placebo.World",
                         artifact: dict, spec_hash: str,
                         decision_digest: str, elapsed_s: float
                         ) -> tuple[str, str]:
    n_games = world.n_games
    n_bytes = (n_games + 7) // 8
    stem = f"masks-{spec_hash[:16]}"
    bin_path = OUT_DIR / f"{stem}.bin"
    index_path = OUT_DIR / f"{stem}.index.json"

    strategy_ids = sorted(masks)
    with open(bin_path, "wb") as fh:
        for sid in strategy_ids:
            away, home = masks[sid]
            fh.write(away.to_bytes(n_bytes, "little"))
            fh.write(home.to_bytes(n_bytes, "little"))

    index = {
        "schema": "evolab.masks_bin/1",
        "source_artifact": os.path.relpath(ARTIFACT_PATH, REPO_ROOT),
        "enumeration_spec_hash": spec_hash,
        "decision_digest": decision_digest,
        "real_world_id": world.world_id,
        "n_games": n_games,
        "bytes_per_mask": n_bytes,
        "bytes_per_strategy": 2 * n_bytes,
        "record_layout": "for each strategy_id in `strategy_order`: "
                         "`bytes_per_mask` bytes of the away mask (LE-packed "
                         "bits, bit i = game_order[i]) then `bytes_per_mask` "
                         "bytes of the home mask, same encoding",
        "strategy_order": strategy_ids,
        "game_order": [g.game_id for g in world.games],
        "n_strategies_with_masks": len(strategy_ids),
        "n_strategies_real_in_artifact": artifact["n_strategies_real"],
        "min_selections": artifact["config"]["min_selections"],
        "replay_elapsed_seconds": round(elapsed_s, 3),
        "note": ("Decisions only. Built with home_won=None throughout and "
                "never calls feed.read_outcomes/join_outcomes -- no game "
                "outcome was read to produce this file."),
    }
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, sort_keys=True, indent=2)
        fh.write("\n")
    return str(bin_path), str(index_path)


def main(argv: list[str] | None = None) -> int:
    if not ARTIFACT_PATH.exists():
        print(f"artifact not found: {ARTIFACT_PATH}; nothing to replay")
        return 1
    artifact = _load_artifact(ARTIFACT_PATH)

    t0 = time.time()
    world, decision_digest = _rebuild_world(artifact)
    stamped_digest = artifact["replay_manifest"]["decision_digest"]
    if decision_digest != stamped_digest:
        raise ReplayMismatch(
            f"replayed decision_digest {decision_digest!r} does not match "
            f"the artifact's stamped {stamped_digest!r}; the historical "
            "stores have moved since this artifact was produced and this "
            "script refuses to mask a different world's decisions as this "
            "artifact's")
    print(f"world reconstructed and digest verified: {decision_digest} "
          f"({world.n_games} games)")

    genomes, spec_hash = _rebuild_genomes(artifact)
    if spec_hash != artifact["enumeration_spec_hash"]:
        raise ReplayMismatch(
            f"replayed enumeration_spec_hash {spec_hash!r} does not match "
            f"the artifact's {artifact['enumeration_spec_hash']!r}; the "
            "genome space this script would enumerate is not the one that "
            "produced the artifact")
    print(f"genome space verified: {spec_hash} ({len(genomes)} genomes)")

    masks = _compute_masks(world, genomes, artifact["config"]["min_selections"])
    elapsed = time.time() - t0
    print(f"{len(masks)} strategies cleared min_selections="
          f"{artifact['config']['min_selections']} "
          f"(artifact reports n_strategies_real={artifact['n_strategies_real']}) "
          f"in {elapsed:.1f}s")
    if len(masks) != artifact["n_strategies_real"]:
        raise ReplayMismatch(
            f"replayed {len(masks)} surviving strategies, artifact reports "
            f"{artifact['n_strategies_real']}; the replay does not agree "
            "with the artifact it is supposed to reconstruct")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bin_path, index_path = _write_bin_and_index(
        masks, world, artifact, spec_hash, decision_digest, elapsed)
    print(f"wrote {bin_path}")
    print(f"wrote {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
