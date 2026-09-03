"""ONE feature builder for both the live engine and the historical replay.

`build_features(game_ref, t, sources) -> dict[str, FeatureValue]` computes,
from primitives and honouring stop-at-T, the matchup features
`src.engine.glue.build_snapshot` puts on `PriceBlindSnapshot.features` and
`src.evolab.replay.world_view` would put on `WorldView.features` if it were
routed through this module instead of reading a precomputed matrix row
directly (S3, not this packet). Feature NAMES and semantics are identical on
both paths -- `tests/test_engine_features.py`'s matrix-equivalence test
proves it against a real 2023 matchup-matrix row.

WHICH OF THE MATRIX'S NINE PER-SIDE FEATURES THIS MODULE CAN HONESTLY SERVE
----------------------------------------------------------------------------
`src/research/matrix.py:row_for_game` computes nine per-side columns. Of
those, exactly ONE has a primitive source that exists, with a real stop-at-T
story, on BOTH the 2026 live path (`src.core.asof` forward stores) and the
2023-24 replay path (this project's historical backfill stores):

  lineup_platoon_share -- the posted lineup's share of plate appearances with
  the platoon advantage against the opposing probable starter. Its only
  inputs are (a) the posted lineup, (b) each hitter's throws/bats side from
  the shared biographical handedness cache (stable, not time-varying, so it
  needs no stop-at-T gate of its own), and (c) the opposing probable
  starter's own throwing hand from that same cache. Every one of those three
  inputs has a real counterpart on both paths:
    - live (2025+):    `home_lineup`/`away_lineup` (`lineups_watch`) and
                        `home_probable_id`/`away_probable_id`
                        (`probables_watch`), both read through
                        `src.core.asof.as_of` at `t`, real per-field
                        `observed_utc`/`known_at_grade`.
    - replay (2023-24): the posted-lineup store
                        (`src.pipeline.lineup_store.read`) and the results
                        CSV's own `home_probable_id`/`away_probable_id`
                        columns (`src.pipeline.history.read_results`) -- the
                        SAME two stores `src.research.matrix.row_for_game`
                        itself reads (matrix.py:262-268) to compute this
                        exact column, so a value produced here is checked
                        against `data/research/matchup_matrix_2023.jsonl`'s
                        own row byte-for-byte, not merely by inspection.
  Matches `src.evolab.registry.DEFAULT_REGISTRY`'s frozen mechanism/direction
  for this feature (the registry is the one place a sign may be written).

The other EIGHT matrix columns are NOT served here, and this is a deliberate
exclusion, not an oversight (per the task: "if any feature cannot be
reproduced from primitives with a stop-at-T guarantee, do NOT approximate
it -- exclude it"):

  starter_platoon_gap, starter_velocity_gap, starter_groundball_share,
  lineup_vs_primary_pitch, primary_pitch, primary_pitch_share,
  top_minus_bottom, lineup_vs_starter_history

  Every one of these is computed by `src.research.matrix.row_for_game` from
  `src.pipeline.rebuilt`'s forward accumulation over the FULL per-pitch
  Statcast store (`src.providers.statcast_pitches`, `historical_path
  ("statcast")`), walked to a MONTHLY cutoff snapshot
  (`rebuilt.build_snapshots`). That accumulator exists, in this project,
  ONLY as a 2023-24 historical backfill -- there is no forward/live 2026
  equivalent reachable through `src.core.asof` (verified: `asof.py`'s
  `_default_stores()` has no pitch-level, arsenal, platoon-split, velocity,
  ground-ball or matchup-history StoreSpec of any kind) or anywhere else in
  this codebase's live capture path. Building these eight for a 2023-24 game
  from the SAME `rebuilt` accumulator matrix.py itself uses is possible, but
  building them for a LIVE 2026 game is not honestly possible today: there is
  no primitive to read. Since the task requires identical semantics on BOTH
  paths, and "for 2026 they are the forward stores via `src.core.asof`" is
  the live contract, these eight are excluded everywhere rather than served
  only on replay and silently empty on live (which would make `analyze()`'s
  feature surface depend on which era it happened to be looking at -- exactly
  the trap `src.evolab.registry`'s six-of-nine exclusion already names for
  three of these eight, for an unrelated reason: no frozen sign / non-numeric
  value). `UNAVAILABLE_FEATURES` below names them for a test to check this
  list stays exhaustive against `src.research.funnel.NUMERIC_FEATURES`.

NONE OVER GUESS, AND ABSENCE OVER DEFAULT
------------------------------------------
A feature whose inputs are not all present at `t` is simply absent from the
returned dict -- never defaulted to 0.0 or interpolated. Every `FeatureValue`
that IS returned carries its own `{source, observed_utc, known_at,
known_at_grade}`, mirroring `src.core.asof.FieldObservation`'s shape exactly
(deliberately -- a caller already knows how to read one of these). On the
live path, the grade is the worst of the as_of fields this feature actually
drew from (real per-field provenance, timestamped). On the replay path,
every 2023-24 value is grade D, `known_at=None`: this project did not capture
a real point-in-time for when a 2023-24 lineup/probable became public
(`docs/AUDIT_PROBABLE_PITCHER_PIT.md`), the same rule
`src.core.asof._known_at_for` already applies to its own forward stores for
any 2023-24 row, restated here rather than re-derived so the two modules
cannot silently drift onto different eras. `glue.build_snapshot` folds this
per-feature grade into `PriceBlindSnapshot.assumption_exposure` alongside the
as_of snapshot's own field provenance, so a 2023-24 game's `known_at_grade`
is never wrongly promoted to A merely because that game's forward stores
(which did not exist yet) happened to read back empty.

STOP-AT-T
---------
Live: inherited directly from `src.core.asof.as_of`'s own stop-at-T
discipline -- a `home_lineup`/`away_lineup`/`*_probable_id` row observed
after `t` is never read, so shifting `t` earlier can only ever remove an
input this feature depends on, never change one that stays present with a
different value. Replay: `lineup_platoon_share` has no cutoff dependency in
`matrix.row_for_game` either (matrix.py:262-268 -- it reads the posted lineup
and the schedule-fact probable id directly, not through the monthly `acc`
snapshot at all), so it carries no synthetic per-instant truncation on the
replay path; the seasons-are-DEGRADED-by-construction rule
(`asof.season_replay_label`) is what marks 2023-24 uses of it honestly,
not a fabricated intra-game timestamp.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from src.core import asof as asof_module
from src.pipeline import history as history_mod
from src.pipeline import lineup_store as lineup_store_mod
from src.pipeline import lineups as lineup_mod

# Mirrors src.core.asof._LIVE_CAPTURE_START exactly: the boundary between
# "2023-24 backfill, no real known_at possible" and "2025+ live capture,
# real per-field timestamps exist" that this module uses to pick which
# primitive set to read. Kept as its own constant (not re-exported from
# asof.py, whose rules this task freezes as unchanged) but pinned equal to
# it by tests/test_engine_features.py so the two cannot silently drift onto
# different eras.
_LIVE_CAPTURE_START = asof_module._LIVE_CAPTURE_START

# The one matrix.py per-side feature this module can honestly reproduce from
# primitives, with a real stop-at-T guarantee, on both the live and replay
# paths. See the module docstring for the full reasoning.
REPRODUCIBLE_FEATURES = ("lineup_platoon_share",)

# Every other numeric matrix.py column, named so a test can assert this list
# stays exhaustive against src.research.funnel.NUMERIC_FEATURES, and so
# anyone reading this module sees the full accounting in one place rather
# than having to diff matrix.py against registry.py by hand. See the module
# docstring for why each one is excluded.
UNAVAILABLE_FEATURES = (
    "starter_platoon_gap",
    "lineup_vs_primary_pitch",
    "primary_pitch_share",
    "top_minus_bottom",
    "starter_velocity_gap",
    "starter_groundball_share",
)
# `primary_pitch` (a pitch-type string) and `lineup_vs_starter_history` (a
# {pa, woba} dict) are matrix.py columns too, but are not numeric matrix
# features at all (src.evolab.replay._features_for already coerces both to
# None for the same reason) -- named here so the accounting is complete, kept
# out of UNAVAILABLE_FEATURES because that tuple is checked against
# funnel.NUMERIC_FEATURES specifically.
NON_NUMERIC_MATRIX_COLUMNS = ("primary_pitch", "lineup_vs_starter_history")

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
    ...]`); `lineup_mod.platoon_advantage_share` wants the historical store's
    `{"order":, "person_id":}` slot shape. This is that one, structural,
    conversion -- no data invented, just the same nine ids relabelled with
    the position they already held in the list."""
    if not ids:
        return []
    return [{"order": i + 1, "person_id": pid} for i, pid in enumerate(ids)]


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

    out: dict[str, FeatureValue] = {}
    for side, opposing_key in (("away", "home_probable_id"),
                               ("home", "away_probable_id")):
        slots = posted.get(side) or []
        pitcher_id = game.get(opposing_key)
        if not slots or not pitcher_id:
            continue
        throws = _throws(handedness, pitcher_id)
        advantage = lineup_mod.platoon_advantage_share(slots, handedness, throws)
        if advantage["share"] is None:
            continue
        out[f"{side}_lineup_platoon_share"] = FeatureValue(
            value=float(advantage["share"]),
            source="historical:lineup_store+mlb_results+handedness_cache",
            observed_utc=game.get("date"),
            known_at=None,
            known_at_grade=asof_module.GRADE_D,
        )
    return out


# ---------------------------------------------------------------------------
# Live (2025+) primitives, via src.core.asof
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

    out: dict[str, FeatureValue] = {}
    for side, opposing_side in (("away", "home"), ("home", "away")):
        lineup_obs = lineup_field[side]
        probable_obs = probable_field[opposing_side]
        if lineup_obs is None or probable_obs is None:
            continue
        slots = _slots_from_ids(lineup_obs.value)
        if not slots:
            continue
        pitcher_id = probable_obs.value
        throws = _throws(handedness, pitcher_id)
        advantage = lineup_mod.platoon_advantage_share(slots, handedness, throws)
        if advantage["share"] is None:
            continue
        grade = (asof_module.GRADE_A
                 if lineup_obs.known_at_grade == asof_module.GRADE_A
                 and probable_obs.known_at_grade == asof_module.GRADE_A
                 else asof_module.GRADE_D)
        observed_utc = max(lineup_obs.observed_utc, probable_obs.observed_utc)
        known_at = observed_utc if grade == asof_module.GRADE_A else None
        out[f"{side}_lineup_platoon_share"] = FeatureValue(
            value=float(advantage["share"]),
            source="asof:lineups_watch+probables_watch+handedness_cache",
            observed_utc=observed_utc,
            known_at=known_at,
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
    `src.core.asof` forward stores (`_build_live`). This mirrors
    `src.core.asof._known_at_for`'s own era boundary exactly, so a caller
    can never end up on the "wrong" branch by picking an inconsistent t for
    the game's actual season.
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
