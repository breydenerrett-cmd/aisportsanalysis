"""ONE feature builder for both the live engine and the historical replay.

`build_features(game_ref, t, sources) -> dict[str, FeatureValue]` computes,
from primitives and honouring stop-at-T, the matchup features
`src.engine.glue.build_snapshot` puts on `PriceBlindSnapshot.features` and
`src.evolab.replay.world_view` would put on `WorldView.features` if it were
routed through this module instead of reading a precomputed matrix row
directly (S3, not this packet). Feature NAMES and semantics are identical on
both paths -- `tests/test_engine_features.py`'s matrix-equivalence test
proves it against real 2023 matchup-matrix rows.

CORRECTION (this revision): an earlier version of this module excluded six of
`src.research.matrix`'s seven numeric per-side columns, reasoning that their
source accumulator (`src.pipeline.rebuilt` over `src.providers
.statcast_pitches`, `historical_path("statcast")`) was a 2023-24-only
backfill. That was wrong, checked against the real store rather than assumed:
`data/historical/statcast/manifest.json` holds 180 four-day windows running
2023-03-30 through 2026-08-27 (39 of them in 2026), and `rebuilt.py`'s own
docstring says a cutoff is "pure accumulation over pitches with `game_date <
cutoff`... a filter rather than a re-request" -- true for ANY cutoff, not a
season-scoped one. All seven of `matrix.row_for_game`'s numeric columns are
therefore wired here, on both eras, through the one `rebuilt` accumulator.

ALL SEVEN NUMERIC MATRIX FEATURES, ONE PRIMITIVE SET, TWO ERAS
------------------------------------------------------------------
`REPRODUCIBLE_FEATURES` names all seven (matches
`src.research.funnel.NUMERIC_FEATURES` exactly -- a test asserts this):
`lineup_platoon_share`, `starter_platoon_gap`, `lineup_vs_primary_pitch`,
`primary_pitch_share`, `top_minus_bottom`, `starter_velocity_gap`,
`starter_groundball_share`. `UNAVAILABLE_FEATURES` is now empty: nothing
numeric that `matrix.py` computes is structurally unreachable from a live
2025+ instant. (`primary_pitch`, a pitch-TYPE string, and
`lineup_vs_starter_history`, a `{pa, woba}` dict, are matrix.py columns too
but are not numeric features at all -- `src.evolab.replay._features_for`
already coerces both to None for the same reason; named in
`NON_NUMERIC_MATRIX_COLUMNS` for a complete accounting, not counted against
either tuple above.)

Every feature's inputs, both eras:
  - `lineup_platoon_share`: the posted lineup + the opposing probable's
    throwing hand (shared handedness cache). No pitch-accumulator cutoff
    dependency at all (matrix.py:262-268 reads it independently of `acc`).
  - the other six: `src.pipeline.rebuilt.accumulate(cutoff, store=...)` over
    the SAME `data/historical/statcast` pitch store both eras share, called
    with `platoon_split`/`fastball_velocity`/`league_fastball_velocity`/
    `groundball_share`/`pitch_mix`/`batter_vs_pitch_type` -- the identical
    functions `matrix.row_for_game` calls -- plus `matrix._batter_totals`/
    `_pooled_woba`/`_order` for `top_minus_bottom`, imported directly rather
    than re-derived so the two modules cannot silently drift apart on the
    same arithmetic.
  Replay (2023-24) reads the posted-lineup store + `mlb_results.csv` for the
  opposing probable id, same as before. Live (2025+) reads
  `lineups_watch`/`probables_watch` through `src.core.asof`, same as before.

THE CUTOFF: WHERE `t` COMES FROM, PER ERA, AND WHY THEY DIFFER
------------------------------------------------------------------
Replay: to reproduce `data/research/matchup_matrix_2023.jsonl`'s row
byte-for-byte (the task's own bar), the pitch-accumulator cutoff MUST be the
exact one `matrix.row_for_game` used building that file: the first day of
the game's own month (`matrix._cutoff_for`, imported directly, not
re-derived). That is deliberately coarser than `t` itself -- matrix.py's own
docstring calls this "under-informed by up to a month, never over-informed
by a second" -- and this module reproduces that exact historical choice
rather than a fresher one, because reproducing the frozen discovery-era
artifact is the job on this branch.

Live: there is no frozen artifact to reproduce, so the cutoff is the
FRESHEST safe one the primitive's own resolution allows: the calendar date
of `t` itself (`rebuilt.accumulate` treats `game_date < cutoff` as strictly
excluded, so `t`'s own day -- and everything after -- never contributes).
The pitch store carries no intraday timestamp (`statcast_pitches.KEEP` has
`game_date` only, no clock time), so calendar-day is the finest truncation
this primitive can honestly support; excluding the whole of `t`'s own day
is therefore the correct, and only available, reading of "a pitch thrown at
or after `t` must never contribute" -- as strict as the rule asks for, never
looser.

FRESHNESS IS REPORTED HONESTLY, NOT ASSUMED CURRENT
------------------------------------------------------
The live pitch store lags: its newest window today ends 2026-08-27, while a
game decided today (2026-09-03) wants cutoff 2026-09-03. `_pitch_coverage_end`
reads the store's own manifest for the true latest covered date and this
module NEVER claims fresher knowledge than that. Concretely: if the store's
coverage reaches through the day before `t`'s own day, the six
pitch-accumulator features grade A (genuinely current, `known_at` = that
coverage bound); if the store lags behind that (today's real state: a ~1-week
gap), they grade D and `known_at` is None -- present, honestly stale, never
promoted to "as of t". `observed_utc` in the lagging case is the store's own
coverage bound, not `t` -- reporting `t` there would be exactly the
"pretending it is current" the task warns against. This module does NOT
build a forward pitch-ingest cadence to close that gap -- keeping these six
features fresh in production needs one (a scheduled `statcast_pitches.build`
run against the current season), and that is a follow-up, not this lane.

NONE OVER GUESS, AND ABSENCE OVER DEFAULT
------------------------------------------
A feature whose inputs are not all present at `t`, or that fails its own
`rebuilt` sample floor (e.g. fewer than 60 batters faced per platoon side),
is simply absent from the returned dict -- never defaulted to 0.0 or
interpolated, matching `matrix.row_for_game`'s own "None over guess" rule
exactly (same floors, same functions).

STOP-AT-T
---------
`lineup_platoon_share`: unchanged from the prior revision -- shifting `t`
earlier can only remove the lineup/probable inputs it depends on, never
change a value that stays present (see that feature's own note above; no
cutoff dependency at all). The other six: shifting `t` (live) or the game's
own month (replay, in principle) earlier can and typically DOES change a
present value -- an accumulation over less history is a different, still
honest, number -- but by construction of `rebuilt.accumulate`/
`iter_rows_dated` (a pitch's own `game_date` gates it, always compared
strictly-less-than the cutoff) a pitch dated on or after the cutoff can never
enter the sum feeding either kind of value change. `tests/
test_engine_features.py` proves this directly: a synthetic store carrying a
pitch dated on `t`'s own day is shown to leave every returned value
unaffected by that pitch's presence.

MEASURED COST, AND WHY THIS MODULE CACHES `accumulate()` PER (store, cutoff)
------------------------------------------------------------------------------
`rebuilt.accumulate` walks the store from its first row up to the requested
cutoff. Measured against the real, ~4M-row store in this session: a cutoff
near the store's own end (the realistic live case) takes ~27s; a cutoff near
the store's start (most 2023 replay games) takes ~1s. Calling it uncached,
once per game, would make a same-day slate of N games cost N times that --
minutes, for no reason, since every game decided "today" shares the same
live cutoff (`t`'s own calendar day) and would recompute an identical
accumulation. `_accumulate_cached` (an `lru_cache` keyed on `(store,
cutoff)`, small and process-local) is therefore load-bearing for this module
to be usable at all in a same-day slate, NOT an optional nicety -- it changes
nothing about freshness or correctness (the underlying call is pure and
deterministic; caching a pure function's result changes only how many times
it is computed, never what it returns), and is orthogonal to the forward
pitch-ingest cadence named above, which is about how STALE the store's
CONTENT is, not how often this module re-reads it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

from src.core import asof as asof_module
from src.pipeline import history as history_mod
from src.pipeline import lineup_store as lineup_store_mod
from src.pipeline import lineups as lineup_mod
from src.pipeline import rebuilt as rebuilt_mod
from src.providers import statcast_pitches as sp
from src.research import matrix as matrix_module

# Mirrors src.core.asof._LIVE_CAPTURE_START exactly: the boundary between
# "2023-24 backfill, no real known_at possible" and "2025+ live capture,
# real per-field timestamps exist" that this module uses to pick which
# primitive set to read. Kept as its own constant (not re-exported from
# asof.py, whose rules this task freezes as unchanged) but pinned equal to
# it by tests/test_engine_features.py so the two cannot silently drift onto
# different eras.
_LIVE_CAPTURE_START = asof_module._LIVE_CAPTURE_START

# Every numeric matrix.py per-side column, all now reproducible from
# primitives with a real stop-at-T guarantee on both paths. Matches
# src.research.funnel.NUMERIC_FEATURES exactly -- a test asserts this so the
# two cannot silently diverge if either module grows a column.
REPRODUCIBLE_FEATURES = (
    "lineup_platoon_share",
    "starter_platoon_gap",
    "lineup_vs_primary_pitch",
    "primary_pitch_share",
    "top_minus_bottom",
    "starter_velocity_gap",
    "starter_groundball_share",
)

# Nothing numeric remains unreachable. Kept as a named, exported tuple
# (rather than deleted) so a future feature that genuinely has no live
# primitive has an obvious place to be listed, with its specific reason --
# the bar the task sets: "the primitive genuinely does not exist", not
# "no live wiring exists yet".
UNAVAILABLE_FEATURES: tuple = ()

# `primary_pitch` (a pitch-type string) and `lineup_vs_starter_history` (a
# {pa, woba} dict) are matrix.py columns too, but are not numeric matrix
# features at all (src.evolab.replay._features_for already coerces both to
# None for the same reason) -- named here so the accounting is complete, kept
# out of both tuples above because those are checked against
# funnel.NUMERIC_FEATURES specifically.
NON_NUMERIC_MATRIX_COLUMNS = ("primary_pitch", "lineup_vs_starter_history")

# The six features computed from the shared pitch accumulator, as opposed to
# lineup_platoon_share (no accumulator dependency at all).
PITCH_ACCUMULATOR_FEATURES = tuple(
    f for f in REPRODUCIBLE_FEATURES if f != "lineup_platoon_share")

SIDES = ("away", "home")


class FeatureError(RuntimeError):
    """Raised when build_features is asked to do something it cannot do
    honestly (a malformed request), never for an ordinary data gap -- those
    are silent absence, per the module docstring."""


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """One feature's value plus its provenance -- shaped like
    `src.core.asof.FieldObservation` on purpose: same four provenance
    fields, same meaning, so a caller that already knows how to read one
    knows how to read the other."""

    value: float
    source: str
    observed_utc: str | None
    known_at: str | None
    known_at_grade: str


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One entry in `FEATURE_SPECS` -- the registry of what a PROPOSE-phase
    system may read from `PriceBlindSnapshot.features` today. Nothing else
    is a legitimate feature name, regardless of what `src.research.matrix`
    or `src.evolab.registry` separately know how to compute."""

    name: str
    mechanism: str
    direction: str  # "+1", "-1", or "undirected" -- never a bare int, so a
                     # reader cannot mistake this for something matrix.py or
                     # analyze() arithmetic operates on directly.
    grade: str
    seasons_available: tuple


_PITCH_GRADE_NOTE = (
    "A only when the shared pitch store's own coverage reaches through the "
    "day before t (genuinely current, no capture lag) AND the opposing "
    "probable/posted lineup this feature also needs was itself observed "
    "grade A; D otherwise -- including unconditionally for 2023-24 (no real "
    "known_at reconstructable for that era) and for any 2025+ game where "
    "the pitch store's own ingest lag leaves the accumulation behind t "
    "(see module docstring: a forward pitch-ingest cadence is a follow-up, "
    "not built in this lane)"
)

FEATURE_SPECS: tuple = (
    FeatureSpec(
        name="lineup_platoon_share",
        mechanism=(
            "the classic exploitation: a lineup posted one-handed against a "
            "starter it holds the platoon advantage over gets more of its "
            "plate appearances in the favourable split than the club-level "
            "season line the market prices ever reflects"
        ),
        direction="+1",
        grade=(
            "A when the posted lineup and the opposing probable were both "
            "observed via a real pre-game poll (2025+ src.core.asof reads); "
            "D for every 2023-24 game, unconditionally -- no real known_at "
            "can be reconstructed for that era (src.core.asof rules)"
        ),
        seasons_available=(2023, 2024, 2025, 2026),
    ),
    FeatureSpec(
        name="starter_platoon_gap",
        mechanism=(
            "a signed platoon split (wOBA allowed vs left-handed hitters "
            "minus vs right-handed hitters) whose effect on a game depends "
            "on which hand the facing lineup is loaded toward, not on the "
            "gap's sign alone -- src.evolab.registry deliberately leaves it "
            "unregistered for exactly this reason, and lineup_platoon_share "
            "is the interaction feature that DOES have a frozen sign"
        ),
        direction="undirected",
        grade=_PITCH_GRADE_NOTE,
        seasons_available=(2023, 2024, 2025, 2026),
    ),
    FeatureSpec(
        name="lineup_vs_primary_pitch",
        mechanism=(
            "a starter who leans on one pitch, against a lineup that has "
            "measurably hit that pitch, has nowhere to hide for eighteen "
            "outs; the market prices his season line, not tonight's "
            "specific collision"
        ),
        direction="+1",
        grade=_PITCH_GRADE_NOTE,
        seasons_available=(2023, 2024, 2025, 2026),
    ),
    FeatureSpec(
        name="primary_pitch_share",
        mechanism=(
            "concentration in one pitch is predictability: the more of a "
            "starter's arsenal is a single offering, the more of the "
            "lineup's preparation transfers, and pitch-level lean is not a "
            "term in any club-level price"
        ),
        direction="+1",
        grade=_PITCH_GRADE_NOTE,
        seasons_available=(2023, 2024, 2025, 2026),
    ),
    FeatureSpec(
        name="top_minus_bottom",
        mechanism=(
            "a top-heavy order concentrates its best bats where the extra "
            "plate appearances go, and club-level pricing averages that "
            "concentration away"
        ),
        direction="+1",
        grade=_PITCH_GRADE_NOTE,
        seasons_available=(2023, 2024, 2025, 2026),
    ),
    FeatureSpec(
        name="starter_velocity_gap",
        mechanism=(
            "a starter whose fastball sits above league pace is holding "
            "stuff the season line has not caught up to, so the lineup "
            "facing the harder thrower is the disadvantaged side"
        ),
        direction="-1",
        grade=_PITCH_GRADE_NOTE,
        seasons_available=(2023, 2024, 2025, 2026),
    ),
    FeatureSpec(
        name="starter_groundball_share",
        mechanism=(
            "a career ground-ball starter takes the air out of an offence "
            "that lives on balls in the air, so the lineup facing the "
            "higher ground-ball share is the disadvantaged side"
        ),
        direction="-1",
        grade=_PITCH_GRADE_NOTE,
        seasons_available=(2023, 2024, 2025, 2026),
    ),
)


# ---------------------------------------------------------------------------
# Sources: where build_features reads primitives from, injectable for tests.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FeatureSources:
    """Everything build_features may need to read, all overridable so tests
    never touch the real data/ tree. Leaving every field at its default
    reads the real, on-disk primitive stores for whichever branch (live or
    replay) `t` selects.

    Live (2025+) fields:
      as_of_stores    -- passed through to `src.core.asof.as_of` verbatim;
                         `None` means "asof's own default store list".
      as_of_snapshot  -- a precomputed `src.core.asof.Snapshot` for this
                         exact (game, t). When given, no as_of read happens
                         here at all -- `glue.build_snapshot` already builds
                         one for its own provenance bookkeeping and passes
                         it through so this module never reads the same
                         forward stores twice.
    Shared:
      handedness      -- an injectable in-memory handedness cache
                         ({person_id(str): {"throws":.., "bats":..}}); when
                         None, reads the real, on-disk cache
                         (`src.pipeline.lineups.DEFAULT_HANDEDNESS`) --
                         biographical and stable, so it needs no stop-at-T
                         gate of its own on either path.
      handedness_path -- overrides where that on-disk read happens; ignored
                         when `handedness` is given directly.
      statcast_store  -- overrides the pitch-level store
                         `src.pipeline.rebuilt.accumulate` reads
                         (`src.providers.statcast_pitches.DEFAULT_STORE` by
                         default) -- the SAME store on both eras, since it
                         is one continuous, ever-growing store rather than a
                         historical/live pair.
    Replay (2023-24) fields:
      lineups_by_pk   -- an injectable `{game_pk(str): {"away":[...],
                         "home":[...]}}` map; when None, reads
                         `src.pipeline.lineup_store.read()`.
      lineups_path    -- overrides that on-disk read; ignored when
                         `lineups_by_pk` is given directly.
      results         -- an injectable `{game_pk(str): {...}}` map (the
                         shape `src.pipeline.history.read_results` returns);
                         when None, reads that function's real, on-disk
                         store.
      results_path    -- overrides that on-disk read; ignored when
                         `results` is given directly.
    """

    as_of_stores: Iterable | None = None
    as_of_snapshot: asof_module.Snapshot | None = None
    handedness: Mapping | None = None
    handedness_path: str | Path = lineup_mod.DEFAULT_HANDEDNESS
    statcast_store: str | Path = sp.DEFAULT_STORE
    lineups_by_pk: Mapping | None = None
    lineups_path: str | Path = lineup_store_mod.DEFAULT_STORE
    results: Mapping | None = None
    results_path: str | Path = history_mod.DEFAULT_STORE


def _parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        d = value
    else:
        v = value.replace("Z", "+00:00") if value.endswith("Z") else value
        d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        raise FeatureError(f"t={value!r} is not timezone-aware")
    return d.astimezone(timezone.utc)


def _load_handedness(path) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FeatureError(f"{target} is not valid JSON") from exc


def _throws(handedness: Mapping, person_id) -> str | None:
    if person_id is None:
        return None
    return (handedness.get(str(person_id)) or {}).get("throws")


def _slots_from_ids(ids: Iterable | None) -> list:
    """`lineups_watch`'s `home_lineup`/`away_lineup` is a flat, order-implied
    list of person ids (verified against the real store: `[807712, 686797,
    ...]`); `lineup_mod.platoon_advantage_share` (and the rebuilt-derived
    features below) want the historical store's `{"order":, "person_id":}`
    slot shape. This is that one, structural, conversion -- no data
    invented, just the same nine ids relabelled with the position they
    already held in the list."""
    if not ids:
        return []
    return [{"order": i + 1, "person_id": pid} for i, pid in enumerate(ids)]


def _pitch_coverage_end(store) -> str | None:
    """The latest `game_date` (inclusive) this project has actually
    ingested into the shared pitch store, read from its own manifest --
    the honest ceiling on how fresh any `rebuilt`-derived feature can claim
    to be, regardless of what cutoff was requested. `None` when the store
    has no windows at all (missing entirely, or not yet built)."""
    manifest = sp.read_manifest(store)
    windows = manifest.get("windows") or {}
    ends = [key.split("..")[-1] for key in windows if ".." in key]
    return max(ends) if ends else None


def _day_before(date_str: str) -> str:
    return (date.fromisoformat(date_str) - timedelta(days=1)).isoformat()


# Small and process-local: every game decided for the same date (live) or
# built from the same matrix month (replay) shares one (store, cutoff) pair,
# so this turns an N-game slate's N full-store walks into one. See the
# module docstring's "MEASURED COST" section -- this is load-bearing, not an
# optional nicety. Pure caching of a pure, deterministic function: never
# changes what a call returns, only how many times the walk actually runs.
@lru_cache(maxsize=8)
def _accumulate_cached(store: str, cutoff: str) -> dict:
    return rebuilt_mod.accumulate(cutoff, store=store)


def _starter_features_for_side(acc, batter_totals, slots, pitcher_id) -> dict:
    """The six pitch-accumulator-derived features for one side, exactly as
    `src.research.matrix.row_for_game` computes them (matrix.py:270-370) --
    same `rebuilt` functions, same floors, same rounding, imported rather
    than re-derived. Returns only the features whose sample floor was met;
    absence, never a default, on every gate `rebuilt`/`matrix` itself
    already enforces."""
    out: dict[str, float] = {}
    if pitcher_id:
        split = rebuilt_mod.platoon_split(acc, pitcher_id)
        if split.get("usable"):
            out["starter_platoon_gap"] = split["gap"]

        velo = rebuilt_mod.fastball_velocity(acc, pitcher_id)
        league_velo = rebuilt_mod.league_fastball_velocity(acc)
        if velo.get("usable") and league_velo is not None:
            out["starter_velocity_gap"] = round(velo["avg"] - league_velo, 4)

        gb = rebuilt_mod.groundball_share(acc, pitcher_id)
        if gb.get("usable"):
            out["starter_groundball_share"] = gb["share"]

        mix = rebuilt_mod.pitch_mix(acc, pitcher_id)
        if mix:
            primary = mix[0]  # pitch_mix sorts by usage, most-used first
            out["primary_pitch_share"] = round(primary["usage_pct"] / 100.0, 4)
            if slots:
                weighted, pa_total = 0.0, 0
                for slot in slots:
                    line = rebuilt_mod.batter_vs_pitch_type(
                        acc, slot.get("person_id"), primary["pitch_type"])
                    if line["pa"] and line["woba"] is not None:
                        weighted += line["woba"] * line["pa"]
                        pa_total += line["pa"]
                if pa_total:
                    out["lineup_vs_primary_pitch"] = round(weighted / pa_total, 4)

    if slots:
        top = [s for s in slots if matrix_module._order(s) is not None
               and 1 <= matrix_module._order(s) <= 4]
        bottom = [s for s in slots if matrix_module._order(s) is not None
                  and matrix_module._order(s) >= 5]
        top_woba = matrix_module._pooled_woba(top, batter_totals)
        bottom_woba = matrix_module._pooled_woba(bottom, batter_totals)
        if top_woba is not None and bottom_woba is not None:
            out["top_minus_bottom"] = round(top_woba - bottom_woba, 4)

    return out


# ---------------------------------------------------------------------------
# Replay (2023-24) primitives
# ---------------------------------------------------------------------------

def _build_replay(game_pk: str, sources: FeatureSources) -> dict:
    results = sources.results
    if results is None:
        results = history_mod.read_results(sources.results_path)
    game = results.get(str(game_pk))
    if not game:
        return {}

    lineups_by_pk = sources.lineups_by_pk
    if lineups_by_pk is None:
        lineups_by_pk = lineup_store_mod.read(sources.lineups_path)
    posted = lineups_by_pk.get(str(game_pk))
    if not posted:
        return {}

    handedness = sources.handedness
    if handedness is None:
        handedness = _load_handedness(sources.handedness_path)

    game_date = game.get("date")
    # The EXACT cutoff data/research/matchup_matrix_*.jsonl was built with --
    # matrix._cutoff_for, not re-derived -- so a 2023-24 value here matches
    # that file's own row, not a fresher (and therefore non-reproducing)
    # recomputation.
    acc = None
    batter_totals: dict = {}
    if game_date:
        cutoff = matrix_module._cutoff_for(game_date)
        acc = _accumulate_cached(str(sources.statcast_store), cutoff)
        batter_totals = matrix_module._batter_totals(acc)

    out: dict[str, FeatureValue] = {}
    for side, opposing_key in (("away", "home_probable_id"),
                               ("home", "away_probable_id")):
        slots = posted.get(side) or []
        pitcher_id = game.get(opposing_key)

        if slots and pitcher_id:
            throws = _throws(handedness, pitcher_id)
            advantage = lineup_mod.platoon_advantage_share(slots, handedness, throws)
            if advantage["share"] is not None:
                out[f"{side}_lineup_platoon_share"] = FeatureValue(
                    value=float(advantage["share"]),
                    source="historical:lineup_store+mlb_results+handedness_cache",
                    observed_utc=game_date, known_at=None,
                    known_at_grade=asof_module.GRADE_D,
                )

        if acc is not None:
            sub = _starter_features_for_side(acc, batter_totals, slots, pitcher_id)
            for name, value in sub.items():
                out[f"{side}_{name}"] = FeatureValue(
                    value=float(value),
                    source="historical:rebuilt(statcast)+lineup_store+mlb_results",
                    observed_utc=game_date, known_at=None,
                    known_at_grade=asof_module.GRADE_D,
                )
    return out


# ---------------------------------------------------------------------------
# Live (2025+) primitives, via src.core.asof + the shared pitch store
# ---------------------------------------------------------------------------

def _build_live(game_pk: str, t: str, sources: FeatureSources) -> dict:
    snapshot = sources.as_of_snapshot
    if snapshot is None:
        snapshot = asof_module.as_of(game_pk, t, stores=sources.as_of_stores)

    lineup_field = {"away": snapshot.fields.get("away_lineup"),
                    "home": snapshot.fields.get("home_lineup")}
    probable_field = {"away": snapshot.fields.get("away_probable_id"),
                      "home": snapshot.fields.get("home_probable_id")}

    handedness = sources.handedness
    if handedness is None:
        handedness = _load_handedness(sources.handedness_path)

    t_dt = _parse_utc(t)
    cutoff_date = t_dt.date().isoformat()  # t's own day, and everything
                                            # after, is excluded entirely --
                                            # the finest safe truncation this
                                            # primitive's day-only
                                            # `game_date` resolution allows.
    day_before_cutoff = _day_before(cutoff_date)
    covered_through = _pitch_coverage_end(sources.statcast_store)

    acc = None
    batter_totals: dict = {}
    pitch_grade = asof_module.GRADE_D
    pitch_observed: str | None = None
    if covered_through is not None:
        acc = _accumulate_cached(str(sources.statcast_store), cutoff_date)
        batter_totals = matrix_module._batter_totals(acc)
        if covered_through >= day_before_cutoff:
            # The store's own coverage reaches at least through the day
            # before t: genuinely current, nothing stale being hidden.
            pitch_grade = asof_module.GRADE_A
            pitch_observed = day_before_cutoff
        else:
            # The store lags behind t (measured, real: as of this session
            # the newest window ends 2026-08-27). Report the TRUE coverage
            # bound, never t itself -- see module docstring.
            pitch_grade = asof_module.GRADE_D
            pitch_observed = covered_through

    out: dict[str, FeatureValue] = {}
    for side, opposing_side in (("away", "home"), ("home", "away")):
        lineup_obs = lineup_field[side]
        probable_obs = probable_field[opposing_side]
        slots = _slots_from_ids(lineup_obs.value) if lineup_obs is not None else []
        pitcher_id = probable_obs.value if probable_obs is not None else None

        if lineup_obs is not None and probable_obs is not None and slots:
            throws = _throws(handedness, pitcher_id)
            advantage = lineup_mod.platoon_advantage_share(slots, handedness, throws)
            if advantage["share"] is not None:
                grade = (asof_module.GRADE_A
                         if lineup_obs.known_at_grade == asof_module.GRADE_A
                         and probable_obs.known_at_grade == asof_module.GRADE_A
                         else asof_module.GRADE_D)
                observed_utc = max(lineup_obs.observed_utc, probable_obs.observed_utc)
                known_at = observed_utc if grade == asof_module.GRADE_A else None
                out[f"{side}_lineup_platoon_share"] = FeatureValue(
                    value=float(advantage["share"]),
                    source="asof:lineups_watch+probables_watch+handedness_cache",
                    observed_utc=observed_utc, known_at=known_at,
                    known_at_grade=grade,
                )

        if acc is not None:
            sub = _starter_features_for_side(acc, batter_totals, slots, pitcher_id)
            for name, value in sub.items():
                # top_minus_bottom needs only this side's own posted lineup;
                # every other pitch-accumulator feature needs the opposing
                # probable's id too -- both are guaranteed present here
                # because _starter_features_for_side only emits a name when
                # its own gate (pitcher_id, or slots) was satisfied.
                input_grade = (lineup_obs.known_at_grade if name == "top_minus_bottom"
                              else probable_obs.known_at_grade)
                grade = (asof_module.GRADE_A
                         if pitch_grade == asof_module.GRADE_A
                         and input_grade == asof_module.GRADE_A
                         else asof_module.GRADE_D)
                # The pitch accumulator's own coverage bound IS the
                # observed_utc reported here, unconditionally -- it is the
                # binding, and by far the coarser, provenance fact for a
                # feature built from potentially years of pitch history;
                # the lineup/probable timestamp only gates WHICH pitcher's
                # accumulation this is, not how fresh that accumulation is.
                observed_utc = pitch_observed
                known_at = observed_utc if grade == asof_module.GRADE_A else None
                out[f"{side}_{name}"] = FeatureValue(
                    value=float(value),
                    source=("asof:lineups_watch+probables_watch"
                            "+rebuilt(statcast)+handedness_cache"),
                    observed_utc=observed_utc, known_at=known_at,
                    known_at_grade=grade,
                )
    return out


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------

def build_features(game_ref, t: str | datetime,
                    sources: FeatureSources | None = None) -> dict:
    """Every feature this engine can honestly compute for `game_ref` as of
    `t`, keyed `{side}_{feature}` exactly as
    `data/research/matchup_matrix_*.jsonl` and
    `src.evolab.replay._features_for` do.

    `game_ref` is anything with a `.game_pk` (an `str`/`int`, or a
    `src.engine.glue.GameRef` -- duck-typed rather than imported, so this
    module never depends on glue.py and glue.py can depend on this one
    without a cycle). No `game_pk` at all means nothing to key either
    primitive set on: returns `{}`, honestly, never a guess.

    Branch choice is `t` itself, not a caller-supplied flag: `t` before
    `_LIVE_CAPTURE_START` (2025-01-01Z) reads the 2023-24 historical
    primitives (`_build_replay`); `t` at or after it reads the live
    `src.core.asof` forward stores plus the shared pitch accumulator
    (`_build_live`). This mirrors `src.core.asof._known_at_for`'s own era
    boundary exactly, so a caller can never end up on the "wrong" branch by
    picking an inconsistent t for the game's actual season.
    """
    game_pk = getattr(game_ref, "game_pk", None)
    if game_pk is None:
        # Duck-type src.engine.glue.GameRef, whose id a live caller actually
        # wants to key on is `.asof_key` (== .game_pk there in all cases
        # this module cares about), not `.board_key` (the odds event_id).
        game_pk = getattr(game_ref, "asof_key", None)
    if game_pk is None:
        game_pk = game_ref if isinstance(game_ref, (str, int)) else None
    if game_pk is None:
        return {}

    t_dt = _parse_utc(t)
    sources = sources or FeatureSources()
    if t_dt < _LIVE_CAPTURE_START:
        return _build_replay(str(game_pk), sources)
    return _build_live(str(game_pk), t if isinstance(t, str) else t_dt.isoformat(),
                        sources)
