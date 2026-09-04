"""The Phase 2B sweep driver -- the enumerable search over every world.

NOTHING THIS MODULE PRODUCES IS EVIDENCE. See registry.py's docstring and
docs/EVOLAB_DESIGN.md sections 11 and 15. This module writes only under
`data/research/evolab/`, cannot alter frozen research families, and cannot
promote anything.

WHAT THIS MODULE IS
--------------------
The conductor, not a new instrument. Every real piece of machinery already
exists and is imported, never re-implemented: `genome.enumerate_genomes` for
the space, `bitsets` for the once-per-world mask precompute, `placebo` for the
null worlds, `cscv`/`spa` for the multiplicity statistics, `ceiling` for the
verdict. This module's only job is to run that machinery identically over the
real world and the placebo worlds and assemble the stamped report (design
sections 6, 7, 8, 12, 14b, 15).

THE INJECTED REPLAY PROVIDER
-----------------------------
`src/evolab/replay.py` is being built separately (by another worker) against
the WorldView / DecisionPoint schema of design sections 2 and 4: a stream of
`(game, T)` decision points, each served as a `WorldView`. That is the right
shape for a single decision, and the wrong shape for an enumerable sweep of
11,000-odd genomes against ~4,800 games -- the sweep needs, per world, ONE
resolved row per game: the CONSENSUS_EXECUTION price at the decision instant,
that same de-vigged probability at the close (for movement fitness, design
section 6), the graded outcome, and the feature differentials. That is exactly
`placebo.World` / `placebo.Game`'s shape, chosen deliberately: it is the shape
every generator in `placebo.py` already speaks, so "the whole machine runs on
every world" (design section 7) is not a slogan here, it is one function
(`sweep_world`) called on 51 identical structures.

So the seam is `ReplayProvider`: a zero-argument callable returning a
`ReplayFeed` -- a `placebo.World` (the REAL world, in canonical `Game` form)
plus an optional manifest. Reducing a `WorldView` stream down to that shape --
picking the decision point, resolving CONSENSUS_EXECUTION, checking
`min_books` and `require_lineup`, reading the close and the grade -- is the
adapter's job, and it lives wherever the caller wires the real engine in, not
in this module. That reduction is exactly design section 5's "execution held
constant across the whole population": once the provider has resolved it, no
per-genome branch on eligibility, routing or execution belongs here, and one
does not exist -- a genome that would route to a market this feed does not
carry (`F5_MARKET` today) is refused loudly by `sweep_world` rather than
silently scored against the wrong price.

This is what makes the module "fully testable today with a synthetic provider
and simply plugs in the real one when it lands": every test below builds a
`ReplayFeed` from `placebo.make_game`/`placebo.real_world` directly, with no
dependency on `replay.py` at all, and the one function that will change on the
day the real engine lands is the adapter that builds a `ReplayFeed`, not
anything in this file.

WHY DECISION LOGIC IS RE-EXPRESSED AS BITSETS RATHER THAN CALLING `decide()`
-----------------------------------------------------------------------------
`decide.py` is the correctness reference: one genome, one `WorldView`, pure,
byte-identical. But calling it 11,000 times per game per world is exactly the
"24 million Python-level decisions" design section 12 built the bitset engine
to avoid. `_side_profiles` below computes, for a genome's <= 3 signals, the
same partition `decide._side_score` would compute one game at a time: every
subset of signals that could fire together has a FIXED score and confirmation
count (weights and rule are genome properties, not game properties), so the
exact-fired-subset masks partition the world once per genome, in
`2**n_signals <= 8` bitwise passes, rather than once per game. The four
tie-break rules of `decide.py`'s module docstring are then applied to whole
subset-masks in `_resolve_ties`, not to individual games -- same rules,
applied at the granularity the enumeration actually affords. Nothing here
reads a WorldView or a Decision; it is bound to `decide.py`'s documented
semantics by the docstring, and by the cross-check test that runs both paths
over the same genomes and games and asserts identical selections.

DETERMINISM END TO END
-----------------------
Every seed source is explicit (`base_seed` feeds `placebo.placebo_suite`,
`spa_seed` feeds `spa.spa_test`); nothing here reads the clock, the
filesystem's mtimes, or a global RNG. Genome order is `enumerate_genomes`'s
documented order; every dict written to a report is built from a sorted
iteration. `SweepReport.canonical_json` is what determinism is tested against:
same provider, same config, same bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Callable, Mapping, Sequence

from src.core import odds as odds_math
from src.core.timing import TimingCollector, require_timings, stage
from src.evolab import ceiling, cscv, genome as genome_mod, placebo, spa
from src.evolab.bitsets import build_signal_mask_table, count_bits, \
    iter_set_bits, universe_mask
from src.evolab.registry import DEFAULT_REGISTRY, SignalRegistry

DEFAULT_N_BLOCKS = 10
DEFAULT_MIN_SELECTIONS = 30
DEFAULT_SPA_N_BOOTSTRAP = 1000
DEFAULT_SPA_BLOCK_LENGTH = 7.0

# Design section 7's P4 note: P4 carries a real edge into its "null" world
# intact and is reclassified as a dispersion diagnostic, excluded from the
# ceiling and the kill criterion.
CEILING_EXCLUDED_GENERATORS = (placebo.P4,)

# Design section 7's SECOND GENERATOR AMENDMENT: the ceiling is evaluated PER
# FITNESS, each over the generators that actually null it. This sweep's search
# maximises MOVEMENT (design section 6), so its ceiling is the movement one.
# The outcome set is carried here because the confirmation fitness (`roi_table`
# in `WorldFitness`) is scored on the same worlds and must never be judged
# against the movement set, nor the movement ceiling against P1/P5 -- both
# mistakes are silent and both invert the verdict.
MOVEMENT_CEILING_GENERATORS = placebo.MOVEMENT_NULL_GENERATORS   # (P2, P3, P6)
OUTCOME_CEILING_GENERATORS = placebo.OUTCOME_NULL_GENERATORS     # (P1,P2,P3,P5)

# The sweep's primary fitness, and therefore which set its ceiling defaults to.
PRIMARY_FITNESS = "movement"


def default_ceiling_generators(generator_ids: Sequence[str],
                               fitness: str = PRIMARY_FITNESS) -> tuple:
    """Which of `generator_ids` may vote on `fitness`'s ceiling, in order.

    Intersection, not substitution: a caller who ran a narrower suite gets a
    narrower vote rather than a vote over worlds that were never built.
    """
    if fitness == "movement":
        allowed = MOVEMENT_CEILING_GENERATORS
    elif fitness == "outcome":
        allowed = OUTCOME_CEILING_GENERATORS
    else:
        raise SweepError(
            f"unknown fitness {fitness!r}; known: 'movement', 'outcome'")
    return tuple(g for g in generator_ids if g in allowed)


def majority(n: int) -> int:
    """A strict majority of `n` voters -- the default `min_generators`.

    `ceiling.DEFAULT_MIN_GENERATORS` is 3, the majority of the original five.
    With per-fitness sets the size of the electorate changes, so the majority
    is derived from the set actually voting instead of being pinned to five.
    """
    return max(1, n // 2 + 1)

ARTIFACT_ROOT = os.path.join("data", "research", "evolab")


class SweepError(RuntimeError):
    """Raised when a sweep cannot be run or reported honestly."""


# ---------------------------------------------------------------------------
# the injected replay seam
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplayFeed:
    """What an injected `ReplayProvider` hands the sweep. See module docstring.

    `world` must be a `placebo.World` whose games already reflect exactly one
    resolved CONSENSUS_EXECUTION decision per game: `home_price`/`away_price`
    and the de-vigged `home_fair` at the decision instant, `home_fair_close`
    at the close (`None` when not knowable -- movement fitness then skips that
    game rather than inventing a close), `home_won` (`None` if ungraded), and
    every registered feature as `away_<feature>`/`home_<feature>`.

    `manifest` is whatever `replay.ReplayManifest` (or an equivalent plain
    dict) the provider wants stamped onto every artifact this sweep produces
    (design section 11). `None` is legal -- exactly the synthetic-provider
    case this module is built to run fully tested without.
    """

    world: "placebo.World"
    manifest: object = None


ReplayProvider = Callable[[], ReplayFeed]


def _manifest_to_dict(manifest) -> dict | None:
    if manifest is None:
        return None
    if hasattr(manifest, "to_dict"):
        return manifest.to_dict()
    if isinstance(manifest, Mapping):
        return dict(manifest)
    raise SweepError(
        f"replay manifest must be a dict or carry .to_dict(), got "
        f"{type(manifest).__name__}")


# ---------------------------------------------------------------------------
# one world, the whole search
# ---------------------------------------------------------------------------

def _differentials_by_feature(world: "placebo.World",
                              registry: SignalRegistry) -> dict:
    """{feature: [d_0, d_1, ...]} for every registered feature, world order.

    Always one entry per registered feature, even when a feature is absent
    from every game in this world (a list of `None`s) -- so
    `build_signal_mask_table` never SKIPS a pair the way it would for a
    genuinely-never-supplied feature, and every genome's signal lookups
    resolve to a (possibly empty) mask rather than a KeyError. Absence still
    means "never fires", exactly as `bitsets.signal_masks` already treats a
    `None` differential.
    """
    out = {}
    for spec in registry.specs():
        vals = []
        for g in world.games:
            away = g.features.get("away_" + spec.feature)
            home = g.features.get("home_" + spec.feature)
            vals.append(None if away is None or home is None else away - home)
        out[spec.feature] = vals
    return out


def _side_profiles(g: "genome_mod.Genome", mask_table: dict, universe: int):
    """{'away': [[mask, score, confirmations], ...], 'home': [...]}

    One entry per subset of `g.signals` that clears the entry gate, exactly
    mirroring `decide._side_score` / `decide._passes_entry` -- see the module
    docstring. The subsets partition the world for a given side: no game can
    belong to two entries of the same side's list.
    """
    signals = g.signals
    n = len(signals)
    masks = [mask_table[(s.feature, s.threshold_index)] for s in signals]
    weights = [s.weight for s in signals]
    profiles = {"away": [], "home": []}
    for subset in range(1, 1 << n):
        confirmations = bin(subset).count("1")
        if confirmations < g.entry.min_confirmations:
            continue
        if g.combination.rule == "k_of_n":
            if confirmations < g.combination.k:
                continue
            score = float(confirmations)
        else:
            score = sum(weights[i] for i in range(n) if subset & (1 << i))
        if score < g.entry.min_score:
            continue
        for side_index, side in enumerate(("away", "home")):
            profile_mask = universe
            for i in range(n):
                side_mask = masks[i][side_index]
                if subset & (1 << i):
                    profile_mask &= side_mask
                else:
                    profile_mask &= (universe & ~side_mask)
                if not profile_mask:
                    break
            if profile_mask:
                profiles[side].append([profile_mask, score, confirmations])
    return profiles


def _resolve_ties(profiles: dict) -> tuple[int, int]:
    """(away_mask, home_mask), disjoint, after decide.py's tie-break rules.

    Rules 2-4 of decide.py's module docstring, applied to whole profile masks
    rather than one game at a time: strictly greater score wins; if equal,
    strictly more confirmations wins; if that is equal too, the overlap goes
    to neither side (CONFLICTING_SIGNALS -- NO_PLAY). Correct because away
    profiles are pairwise disjoint, and home profiles are pairwise disjoint,
    so removing one home profile's overlap with one away profile never
    touches bits any other away profile still claims.
    """
    away_profiles = profiles["away"]
    home_profiles = profiles["home"]
    for aw in away_profiles:
        for hm in home_profiles:
            overlap = aw[0] & hm[0]
            if not overlap:
                continue
            if aw[1] != hm[1]:
                loser = hm if aw[1] > hm[1] else aw
                loser[0] &= ~overlap
            elif aw[2] != hm[2]:
                loser = hm if aw[2] > hm[2] else aw
                loser[0] &= ~overlap
            else:
                aw[0] &= ~overlap
                hm[0] &= ~overlap
    away_mask = 0
    for aw in away_profiles:
        away_mask |= aw[0]
    home_mask = 0
    for hm in home_profiles:
        home_mask |= hm[0]
    return away_mask, home_mask


@dataclass(frozen=True)
class WorldFitness:
    """One world's sweep: per-strategy per-block fitness, gate survivors only.

    Strategies that never reach `min_selections` are ABSENT, not zeroed --
    design section 6's "gates are gates, not additive terms": a death is not a
    deduction, and a dead strategy competing for the search maximum at 0.0
    would understate how hostile the space actually is.
    """

    world_id: str
    generator: str
    seed: int | None
    n_games: int
    n_strategies: int
    movement_table: Mapping[str, tuple]   # strategy_id -> per-block mean movement
    roi_table: Mapping[str, tuple]        # strategy_id -> per-block mean outcome ROI
    totals_movement: Mapping[str, float]  # strategy_id -> overall mean movement
    totals_roi: Mapping[str, float]       # strategy_id -> overall mean outcome ROI
    n_selected: Mapping[str, int]         # strategy_id -> selection count
    masks: Mapping[str, tuple]            # strategy_id -> (away_mask, home_mask)

    def totals(self, fitness: str) -> Mapping[str, float]:
        """The per-strategy overall table for `fitness` -- 'movement' or 'outcome'.

        The single seam the ceiling path reads through so the movement and
        outcome verdicts are computed by literally the same code, never two
        parallel copies that could drift (see `run_sweep`'s `primary_fitness`).
        """
        if fitness == "movement":
            return self.totals_movement
        if fitness == "outcome":
            return self.totals_roi
        raise SweepError(
            f"unknown fitness {fitness!r}; known: 'movement', 'outcome'")


def sweep_world(world: "placebo.World", genomes: Sequence,
                registry: SignalRegistry = DEFAULT_REGISTRY, *,
                n_blocks: int = DEFAULT_N_BLOCKS,
                min_selections: int = DEFAULT_MIN_SELECTIONS) -> WorldFitness:
    """Run every genome in `genomes` over one world; the per-world sweep.

    CONSENSUS_EXECUTION only: `world`'s prices are already that resolved
    price (see `ReplayFeed`), so nothing here consults `genome.execution`.
    Every genome must route only to markets this feed carries a price for --
    today, `h2h` alone; a genome preferring `genome.F5_MARKET` is refused
    loudly rather than scored against the full-game price wearing an F5 mask,
    which is exactly the `MARKET_SELECTION_ADVANTAGE` design section 9 warns
    against manufacturing by accident.
    """
    for g in genomes:
        if genome_mod.F5_MARKET in g.routing.market_preference:
            raise SweepError(
                f"genome {g.strategy_id} routes to {genome_mod.F5_MARKET}, but "
                "this feed carries one full-game h2h price per game; sweeping "
                "an F5 market needs a provider that resolves an F5 price, not "
                "a genome-level branch here")

    diffs = _differentials_by_feature(world, registry)
    mask_table = build_signal_mask_table(registry, diffs)
    universe = universe_mask(world.n_games)

    days = world.days()
    if len(days) < n_blocks:
        raise SweepError(
            f"world {world.world_id} has {len(days)} game-day(s), fewer than "
            f"n_blocks={n_blocks}; a block with no data cannot be scored "
            "(design section 8)")
    bounds = cscv.chronological_blocks(len(days), n_blocks)
    block_of_day_index = {}
    for block_index, (lo, hi) in enumerate(bounds):
        for position in range(lo, hi):
            block_of_day_index[days[position][0]] = block_index
    game_block = [block_of_day_index[g.day_index] for g in world.games]

    movement_table, roi_table, totals_movement, totals_roi = {}, {}, {}, {}
    n_selected, masks = {}, {}

    for g in genomes:
        away_mask, home_mask = _resolve_ties(_side_profiles(g, mask_table, universe))
        selected = count_bits(away_mask) + count_bits(home_mask)
        if selected < min_selections:
            continue

        mv_returns, mv_counts = [0.0] * n_blocks, [0] * n_blocks
        roi_returns, roi_counts = [0.0] * n_blocks, [0] * n_blocks
        for side, mask in (("away", away_mask), ("home", home_mask)):
            for i in iter_set_bits(mask):
                game = world.games[i]
                block = game_block[i]
                if game.home_fair_close is not None:
                    movement = ((game.home_fair_close - game.home_fair)
                                if side == "home" else
                                (game.home_fair - game.home_fair_close))
                    mv_returns[block] += movement
                    mv_counts[block] += 1
                if game.home_won is not None:
                    won = game.home_won if side == "home" else not game.home_won
                    price = game.home_price if side == "home" else game.away_price
                    roi_returns[block] += (
                        odds_math.american_to_decimal(price) - 1.0
                        if won else -1.0)
                    roi_counts[block] += 1

        sid = g.strategy_id
        n_mv, n_roi = sum(mv_counts), sum(roi_counts)
        movement_table[sid] = tuple(
            r / c if c else 0.0 for r, c in zip(mv_returns, mv_counts))
        roi_table[sid] = tuple(
            r / c if c else 0.0 for r, c in zip(roi_returns, roi_counts))
        totals_movement[sid] = (sum(mv_returns) / n_mv) if n_mv else 0.0
        totals_roi[sid] = (sum(roi_returns) / n_roi) if n_roi else 0.0
        n_selected[sid] = selected
        masks[sid] = (away_mask, home_mask)

    return WorldFitness(
        world_id=world.world_id, generator=world.generator, seed=world.seed,
        n_games=world.n_games, n_strategies=len(movement_table),
        movement_table=movement_table, roi_table=roi_table,
        totals_movement=totals_movement, totals_roi=totals_roi,
        n_selected=n_selected, masks=masks)


def _movement_series_by_day(world: "placebo.World",
                            masks: Mapping[str, tuple]) -> dict:
    """{strategy_id: [mean movement per game-day, 0.0 where no selection]}.

    The per-DAY granularity design section 8 requires for SPA (a period is a
    game-day, never a per-selection row), computed from the masks
    `sweep_world` already built so the two analyses can never disagree about
    which games a strategy selected.
    """
    day_order = [d for d, _ in world.days()]
    position_of_day = {d: i for i, d in enumerate(day_order)}
    n_days = len(day_order)
    series = {}
    for sid, (away_mask, home_mask) in masks.items():
        sums = [0.0] * n_days
        counts = [0] * n_days
        for side, mask in (("away", away_mask), ("home", home_mask)):
            for i in iter_set_bits(mask):
                game = world.games[i]
                if game.home_fair_close is None:
                    continue
                pos = position_of_day[game.day_index]
                movement = ((game.home_fair_close - game.home_fair)
                            if side == "home" else
                            (game.home_fair - game.home_fair_close))
                sums[pos] += movement
                counts[pos] += 1
        series[sid] = [sums[i] / counts[i] if counts[i] else 0.0
                       for i in range(n_days)]
    return series


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=5, check=False)
    except Exception:
        return None
    commit = out.stdout.strip()
    return commit or None


# ---------------------------------------------------------------------------
# mask serialization -- FACTORY_SCALE_DESIGN.md section 0's named gap: the
# masks WorldFitness already computes but SweepReport.to_dict() never wrote.
# ---------------------------------------------------------------------------

MASKS_SCHEMA = "evolab.masks/1"


def _pack_mask(mask: int, n_games: int) -> str:
    """One decision mask -> base64 of packed little-endian bits.

    Bit `i` (0-indexed, LSB first) is game index `i` in the world's own game
    order -- the same order `sweep_world`'s `iter_set_bits` already walks, so
    a consumer with that same `placebo.World` can zip bit position to game
    without this module restating the game list a second time. Packed rather
    than left as a decimal integer string because `n_games_real` is ~4-5
    thousand: an unpacked bitmask is ~4-5x the byte count of both boolean
    values as one bit each, and this field is written once per strategy for
    every strategy that clears the gate (thousands per artifact).
    """
    n_bytes = (n_games + 7) // 8
    return base64.b64encode(mask.to_bytes(n_bytes, "little")).decode("ascii")


def _unpack_mask(encoded: str) -> int:
    """Inverse of `_pack_mask`. Byte length is carried by the string itself
    (base64 of a fixed-width `n_games`-bit field), so no separate length
    argument is needed to round-trip the integer exactly."""
    return int.from_bytes(base64.b64decode(encoded.encode("ascii")), "little")


def encode_masks(masks: Mapping[str, tuple], n_games: int) -> dict:
    """`{strategy_id: (away_mask, home_mask)}` -> the on-disk `decision_masks`
    block. A pure function of its arguments (no report state) so
    `scripts/factory_masks_from_sweep.py` can build the identical block from
    a freshly-replayed `WorldFitness.masks` without importing `SweepReport`.
    """
    return {
        "schema": MASKS_SCHEMA,
        "encoding": "base64 of a little-endian packed bitfield; bit i is "
                    "game index i in the world's game order (bit 0 = LSB "
                    "of the first byte)",
        "n_games": n_games,
        "strategies": {
            sid: {"away": _pack_mask(away, n_games),
                  "home": _pack_mask(home, n_games)}
            for sid, (away, home) in sorted(masks.items())
        },
    }


def decode_masks(block: Mapping) -> dict[str, tuple]:
    """Inverse of `encode_masks`: the on-disk block -> `{strategy_id:
    (away_mask, home_mask)}`. Raises `SweepError` on an unrecognised schema
    rather than guessing at a format this module did not write."""
    if block.get("schema") != MASKS_SCHEMA:
        raise SweepError(
            f"unknown decision_masks schema {block.get('schema')!r}; known: "
            f"{MASKS_SCHEMA!r}")
    return {
        sid: (_unpack_mask(pair["away"]), _unpack_mask(pair["home"]))
        for sid, pair in block.get("strategies", {}).items()
    }


# ---------------------------------------------------------------------------
# the full report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SweepReport:
    """Everything design section 11 requires stamped, plus the verdict."""

    enumeration_spec_hash: str
    registry_fingerprint: str
    code_commit: str | None
    replay_manifest: dict | None
    real_world_id: str
    n_games_real: int
    n_strategies_real: int
    real_champion: str | None
    # Named for the original movement-only sweep; holds the real search
    # maximum of whichever fitness `config["primary_fitness"]` names (movement
    # or outcome). Kept as-is rather than renamed so existing consumers and
    # tests reading this field for the movement sweep are undisturbed --
    # `config["primary_fitness"]` is the field that says which fitness it is.
    real_max_movement: float | None
    placebo_world_ids: Mapping[str, tuple]
    placebo_seeds: Mapping[str, tuple]
    placebo_maxima: Mapping[str, tuple]
    placebo_n_strategies: Mapping[str, tuple]
    ceiling: "ceiling.CeilingReport"
    p4_dispersion: dict | None
    cscv: "cscv.CSCVResult"
    spa: "spa.SPAResult"
    spa_cross_check_status: str
    spa_cross_check_explanation: str
    config: dict
    # strategy_id -> (away_mask, home_mask) on the REAL world, the same
    # mapping `sweep_world` already returns as `WorldFitness.masks` (design
    # section 0's named gap: computed there, never serialized until now).
    # Default {} so every report built by pre-existing test/caller code that
    # never passed this still constructs and, per `to_dict`'s `include_masks`
    # flag, emits nothing extra -- an empty mapping is indistinguishable on
    # disk from "masks not carried here at all".
    real_masks: Mapping[str, tuple] = field(default_factory=dict)
    warnings: tuple = field(default_factory=tuple)
    # Per-stage wall/CPU/RSS, map-compute-scale.md section 1: the "51 ms"
    # design estimate was never measured because nothing recorded it.
    # Default () rather than None so a report built by old test code that
    # forgot to pass timings fails loudly at write() (require_timings),
    # instead of writing a schema-valid artifact with a null hole in it.
    timings: tuple = field(default_factory=tuple)

    @property
    def is_kill(self) -> bool:
        return self.ceiling.is_kill

    def to_dict(self, include_masks: bool = True) -> dict:
        """The report as a plain dict -- what `write()` serializes.

        `include_masks` defaults ON (FACTORY_SCALE_DESIGN.md section 0 asks
        that the masks `WorldFitness` already computes stop being silently
        dropped). With it False, or when this report carries no masks at
        all (`real_masks` empty -- every report built before this slice),
        the payload has NO `decision_masks` key, not a null one: a consumer
        keyed on the key's presence, not its value, and a pre-existing
        artifact's schema is reproduced byte-for-byte by `include_masks=False`
        -- see `tests/test_evolab_sweep.py`'s
        `test_masks_flag_off_matches_pre_mask_schema`.
        """
        payload = {
            "schema": "evolab.sweep/1",
            "enumeration_spec_hash": self.enumeration_spec_hash,
            "registry_fingerprint": self.registry_fingerprint,
            "code_commit": self.code_commit,
            "replay_manifest": self.replay_manifest,
            "real_world_id": self.real_world_id,
            "n_games_real": self.n_games_real,
            "n_strategies_real": self.n_strategies_real,
            "real_champion": self.real_champion,
            "real_max_movement": self.real_max_movement,
            "placebo_world_ids": {k: list(v) for k, v in
                                 sorted(self.placebo_world_ids.items())},
            "placebo_seeds": {k: list(v) for k, v in
                             sorted(self.placebo_seeds.items())},
            "placebo_maxima": {k: list(v) for k, v in
                              sorted(self.placebo_maxima.items())},
            "placebo_n_strategies": {k: list(v) for k, v in
                                    sorted(self.placebo_n_strategies.items())},
            "ceiling": asdict(self.ceiling),
            "p4_dispersion": self.p4_dispersion,
            "cscv": asdict(self.cscv),
            "spa": asdict(self.spa),
            "spa_cross_check": {"status": self.spa_cross_check_status,
                                "explanation": self.spa_cross_check_explanation},
            "config": self.config,
            "warnings": list(self.warnings),
            "timings": list(self.timings),
        }
        if include_masks and self.real_masks:
            payload["decision_masks"] = encode_masks(
                self.real_masks, self.n_games_real)
        return payload

    def canonical_json(self) -> str:
        """Sorted-key, no-whitespace-slack JSON -- what determinism is hashed
        against. `default=str` handles the rare non-JSON-native value (e.g. an
        infinite placebo maximum for a world where nothing cleared the gate)
        without ever silently coercing it to a number.

        `timings` is excluded from what gets hashed: wall/CPU seconds and
        peak RSS vary run to run on identical inputs (machine load, GC
        timing) by construction -- they are not part of the search result,
        and hashing them would make `content_hash()` fail to recognize two
        runs of the identical sweep as identical, defeating the exact
        property this method exists to check (see the determinism tests in
        tests/test_evolab_sweep.py). Timings still ship in the written
        artifact (`to_dict()`/`write()`); they are just not decision content.
        """
        payload = self.to_dict()
        payload.pop("timings", None)
        return json.dumps(payload, sort_keys=True,
                          separators=(",", ":"), default=str)

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def write(self, out_dir: str = ARTIFACT_ROOT, *,
             include_masks: bool = True) -> str:
        """Write this report as deterministic, indented JSON under `out_dir`.

        Namespace isolation (design section 11) is enforced here, not left to
        convention: `out_dir` must resolve inside `data/research/evolab/`.
        The filename is content-addressed (spec hash, real world id), never a
        timestamp, so a re-run with identical inputs overwrites the same path
        with identical bytes rather than accumulating copies.

        `include_masks` defaults ON, matching `to_dict()`; pass False to
        write the pre-existing (pre-mask) artifact schema exactly, e.g. to
        reproduce a byte-identical artifact for a diff against one written
        before this slice.

        `require_timings` runs before any byte reaches disk (map-compute-
        scale.md section 1: the Phase 2B artifact that shipped with no
        timing field at all is exactly what this guard now prevents from
        happening again).
        """
        payload = self.to_dict(include_masks=include_masks)
        # Validated BEFORE the 'write' stage below is appended: this must
        # fail on a report that never measured its own computation, not be
        # rescued by the write() call's own timing of itself -- the whole
        # point is that upstream stages were measured, not merely that
        # SOME timing record exists on disk.
        require_timings(payload)
        root = os.path.normpath(os.path.join(os.getcwd(), ARTIFACT_ROOT))
        resolved = os.path.normpath(os.path.join(os.getcwd(), out_dir))
        if resolved != root and not resolved.startswith(root + os.sep):
            raise SweepError(
                f"refusing to write outside {ARTIFACT_ROOT}/: {out_dir!r} "
                "(design section 11: nothing here writes outside its own "
                "namespace)")
        os.makedirs(resolved, exist_ok=True)
        name = f"sweep-{self.enumeration_spec_hash[:16]}-{self.real_world_id}.json"
        path = os.path.join(resolved, name)
        # The "write" stage covers JSON serialization (the dominant cost for
        # a multi-hundred-KB report) -- the namespace checks above are
        # validation, not the write this stage measures. Appended into the
        # payload's own 'timings' list, so the artifact ships a record of its
        # own write cost (necessarily approximate: the record itself cannot
        # time the one extra bytes-on-the-wire re-serialization needed to
        # embed the record).
        write_timings = TimingCollector()
        with stage("write", collector=write_timings, rows=1):
            body = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
        payload["timings"] = list(payload["timings"]) + write_timings.to_list()
        # Re-serialize once more so the on-disk artifact's own 'timings' list
        # includes the 'write' stage just measured -- the file byte count
        # therefore reflects one extra stage record versus `body` above, an
        # accepted, tiny (one JSON object) discrepancy rather than under- or
        # over-reporting the write stage's own cost.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, indent=2, default=str))
            fh.write("\n")
        return path


def run_sweep(replay_provider: ReplayProvider, *,
             registry: SignalRegistry = DEFAULT_REGISTRY,
             eligibility: dict | None = None,
             routings: Sequence[dict] | None = None,
             execution: str = genome_mod.DEFAULT_EXECUTION,
             max_signals: int = genome_mod.MAX_SIGNALS,
             weight_vectors: dict | None = None,
             n_blocks: int = DEFAULT_N_BLOCKS,
             min_selections: int = DEFAULT_MIN_SELECTIONS,
             replicates: int = placebo.DEFAULT_REPLICATES,
             base_seed: int = 0,
             generator_ids: Sequence[str] = placebo.GENERATOR_IDS,
             ceiling_generator_ids: Sequence[str] | None = None,
             threshold_pct: float = ceiling.DEFAULT_PERCENTILE,
             min_generators: int | None = None,
             min_worlds: int | None = None,
             spa_n_bootstrap: int = DEFAULT_SPA_N_BOOTSTRAP,
             spa_block_length: float = DEFAULT_SPA_BLOCK_LENGTH,
             spa_seed: int = 0,
             code_commit: str | None = None,
             primary_fitness: str = PRIMARY_FITNESS) -> SweepReport:
    """The Phase 2B sweep: enumerate once, run it identically on every world.

    Pure orchestration over already-validated machinery -- see the module
    docstring for what belongs here and what does not. `replay_provider` is
    called exactly once; every placebo world is derived from the `World` it
    returns via `placebo.placebo_suite`, so the real and placebo runs share
    every parameter (`registry`, `n_blocks`, `min_selections`) by construction
    and cannot silently drift apart.

    `primary_fitness` picks which of `WorldFitness`'s two per-strategy tables
    the champion, the ceiling, and the electorate default are read from
    (`WorldFitness.totals`): 'movement' (design section 6, the default -- what
    Phase 2B ran) reads `totals_movement` and votes {P2,P3,P6}; 'outcome'
    reads `totals_roi` and votes {P1,P2,P3,P5} (design section 7's SECOND
    GENERATOR AMENDMENT -- P1/P5 permute or resample outcomes only, so they
    null outcome-ROI fitness but are a tie, not a ceiling, for movement).
    Both paths run the identical search over the identical worlds; only which
    column of `sweep_world`'s output the ceiling reads changes, so the two
    verdicts can never silently disagree about what ran.
    """
    if primary_fitness not in ("movement", "outcome"):
        raise SweepError(
            f"unknown primary_fitness {primary_fitness!r}; known: 'movement', "
            "'outcome'")
    if execution != "CONSENSUS_EXECUTION":
        raise SweepError(
            "Phase 2B sweeps CONSENSUS_EXECUTION only (design section 5), "
            f"got {execution!r}; the other modes are execution-honesty "
            "studies, not predictive search, and must not share this ceiling")
    if ceiling_generator_ids is None:
        # Per-fitness by default (design section 7's second amendment): a
        # movement sweep excludes P1/P5, which cannot move movement; an
        # outcome sweep votes {P1,P2,P3,P5} instead, and P4 is excluded from
        # either by not being in any null set. A caller who wants a different
        # electorate passes one; the override is deliberately still here.
        ceiling_generator_ids = default_ceiling_generators(
            generator_ids, primary_fitness)
        if not ceiling_generator_ids:
            allowed = (MOVEMENT_CEILING_GENERATORS if primary_fitness == "movement"
                      else OUTCOME_CEILING_GENERATORS)
            raise SweepError(
                f"none of generator_ids={list(generator_ids)} nulls the "
                f"{primary_fitness} fitness (that set is {list(allowed)}); a "
                "ceiling built from the rest would be a tie reported as a "
                "verdict")
    if min_generators is None:
        min_generators = majority(len(ceiling_generator_ids))
    if min_worlds is None:
        min_worlds = replicates

    # map-compute-scale.md section 1: this collector is the sweep's own
    # wall/CPU/RSS harness -- the thing that turns "51 ms" from a design
    # estimate into a persisted, per-stage measurement on every real run.
    timings = TimingCollector()

    with stage("load", collector=timings):
        feed = replay_provider()
        if not isinstance(feed, ReplayFeed):
            raise SweepError(
                f"replay_provider() must return a sweep.ReplayFeed, got "
                f"{type(feed).__name__}")
        real_world = feed.world
        manifest = _manifest_to_dict(feed.manifest)

    with stage("masks", collector=timings, rows=real_world.n_games):
        genomes = genome_mod.enumerate_genomes(
            registry, eligibility=eligibility, routings=routings,
            execution=execution, max_signals=max_signals,
            weight_vectors=weight_vectors)
        spec = genome_mod.enumeration_spec(
            registry, eligibility=eligibility, routings=routings,
            execution=execution, max_signals=max_signals,
            weight_vectors=weight_vectors)
        spec_hash = genome_mod.spec_hash(spec)

    with stage("evaluate", collector=timings, rows=real_world.n_games,
              decisions=len(genomes) * real_world.n_games):
        real_fitness = sweep_world(real_world, genomes, registry,
                                   n_blocks=n_blocks, min_selections=min_selections)
    real_totals = real_fitness.totals(primary_fitness)
    if not real_totals:
        raise SweepError(
            f"no strategy cleared min_selections={min_selections} on the real "
            f"world ({real_world.n_games} games, {len(genomes)} genomes); "
            "lower the gate or check the feed before sweeping placebo worlds")
    real_champion, real_max = ceiling.search_maximum(real_totals)

    warnings: list = []
    placebo_world_ids, placebo_seeds = {}, {}
    placebo_maxima, placebo_n_strategies = {}, {}
    n_placebo_worlds = len(generator_ids) * replicates

    with stage("placebo_worlds", collector=timings, rows=n_placebo_worlds,
              decisions=len(genomes) * n_placebo_worlds):
        for gid in generator_ids:
            ids, seeds, maxima, n_strats = [], [], [], []
            for world in placebo.placebo_suite(
                    real_world, replicates=replicates, base_seed=base_seed,
                    generator_ids=(gid,)):
                fit = sweep_world(world, genomes, registry, n_blocks=n_blocks,
                                  min_selections=min_selections)
                ids.append(world.world_id)
                seeds.append(world.seed)
                n_strats.append(fit.n_strategies)
                fit_totals = fit.totals(primary_fitness)
                if fit_totals:
                    _, pmax = ceiling.search_maximum(fit_totals)
                else:
                    pmax = float("-inf")
                    warnings.append(
                        f"{world.world_id}: no strategy cleared min_selections on "
                        "this placebo world; recorded as -inf, which can only "
                        "make the ceiling easier to clear, never harder, and is "
                        "reported rather than silently dropped")
                maxima.append(pmax)
                if fit.n_strategies != real_fitness.n_strategies:
                    warnings.append(
                        f"{world.world_id}: {fit.n_strategies} strategies cleared "
                        f"the gate here vs {real_fitness.n_strategies} on the real "
                        "world; the ceiling is only a ceiling when the same "
                        "search ran on both sides")
            placebo_world_ids[gid] = tuple(ids)
            placebo_seeds[gid] = tuple(seeds)
            placebo_maxima[gid] = tuple(maxima)
            placebo_n_strategies[gid] = tuple(n_strats)
            if maxima and all(v == real_max for v in maxima):
                # A generator whose EVERY replicate reproduces the real maximum
                # exactly cannot be a null for whatever fitness the search
                # maximised -- it changed nothing that fitness depends on. This is
                # a real, measured property: under `primary_fitness='movement'`,
                # P1 and P5 permute only `home_won`, and market-relative movement
                # (design section 6) is computed from `home_fair`/
                # `home_fair_close`/features alone, none of which either
                # generator touches. It is reported rather than hidden or
                # silently excluded -- see docs/EVOLAB_DESIGN.md section 7 and
                # the sweep module docstring's discussion of which generators
                # discriminate which fitness.
                warnings.append(
                    f"{gid}: every placebo maximum under this generator exactly "
                    f"equals the real {primary_fitness} maximum; {gid} changed "
                    f"nothing the {primary_fitness} fitness depends on and is "
                    "structurally uninformative here -- its 'does not clear' "
                    "verdict is a tie, not evidence of a ceiling")

    with stage("ceiling", collector=timings):
        ceiling_maxima = {gid: placebo_maxima[gid] for gid in ceiling_generator_ids}
        report_ceiling = ceiling.ceiling_report(
            real_max, ceiling_maxima, real_champion=real_champion,
            threshold_pct=threshold_pct, min_worlds=min_worlds,
            min_generators=min_generators)

        p4_dispersion = None
        for excluded in CEILING_EXCLUDED_GENERATORS:
            if excluded not in placebo_maxima:
                continue
            finite = [v for v in placebo_maxima[excluded] if v != float("-inf")]
            if not finite:
                continue
            p4_dispersion = {
                "generator": excluded,
                "n_worlds": len(finite),
                "min": min(finite), "median": _median(finite), "max": max(finite),
                "real_max": real_max,
                "note": (f"{excluded} is a dispersion diagnostic, not a null "
                        "(design section 7); excluded from the ceiling and the "
                        "kill criterion."),
            }

        cscv_result = cscv.cscv(real_fitness.movement_table)

        day_series = _movement_series_by_day(real_world, real_fitness.masks)
        spa_result = spa.spa_test(day_series, seed=spa_seed,
                                  block_length=spa_block_length,
                                  n_bootstrap=spa_n_bootstrap)
        spa_status, spa_explanation = spa.cross_check(
            spa_result,
            clears_ceiling=(report_ceiling.verdict == ceiling.CLEARS_PLACEBO_CEILING))

    config = {
        "n_blocks": n_blocks, "min_selections": min_selections,
        "replicates": replicates, "base_seed": base_seed,
        "generator_ids": list(generator_ids),
        "ceiling_generator_ids": list(ceiling_generator_ids),
        "primary_fitness": primary_fitness,
        "movement_ceiling_generators": list(MOVEMENT_CEILING_GENERATORS),
        "outcome_ceiling_generators": list(OUTCOME_CEILING_GENERATORS),
        "threshold_pct": threshold_pct, "min_generators": min_generators,
        "min_worlds": min_worlds, "spa_n_bootstrap": spa_n_bootstrap,
        "spa_block_length": spa_block_length, "spa_seed": spa_seed,
        "execution": execution, "max_signals": max_signals,
        "eligibility": eligibility, "routings": (
            [dict(r) for r in routings] if routings is not None else None),
    }

    return SweepReport(
        enumeration_spec_hash=spec_hash,
        registry_fingerprint=registry.fingerprint(),
        code_commit=code_commit if code_commit is not None else _git_commit(),
        replay_manifest=manifest,
        real_world_id=real_world.world_id,
        n_games_real=real_world.n_games,
        n_strategies_real=real_fitness.n_strategies,
        real_champion=real_champion,
        real_max_movement=real_max,
        placebo_world_ids=placebo_world_ids,
        placebo_seeds=placebo_seeds,
        placebo_maxima=placebo_maxima,
        placebo_n_strategies=placebo_n_strategies,
        ceiling=report_ceiling,
        p4_dispersion=p4_dispersion,
        cscv=cscv_result,
        spa=spa_result,
        spa_cross_check_status=spa_status,
        spa_cross_check_explanation=spa_explanation,
        config=config,
        real_masks=dict(real_fitness.masks),
        warnings=tuple(warnings),
        timings=tuple(timings.to_list()),
    )
