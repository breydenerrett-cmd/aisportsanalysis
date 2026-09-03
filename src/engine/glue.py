"""The seam from disk to the waist: `build_board`, `build_snapshot`, and the
sampling/arrival helpers `engine truncation` (`src.cli`) needs to run the
G4 gate against real captures.

Neither `src.engine.analyze.analyze` nor `src.engine.truncation` performs any
I/O -- both are handed already-built `PriceBlindSnapshot`/`PricedBoard` pairs
(see truncation.py's own module docstring: "this module does not itself
build snapshots/boards from disk"). This module is that missing seam: it
reads `data/processed/l1_observations.jsonl` (`src/board/l1.py`'s output)
for the price side and `src.core.asof.as_of` for the point-in-time-feature
side, and does nothing else that could make its output depend on when it was
run rather than on the stores it read plus the `t` it was asked for.

THE game_pk / event_id GAP (read before touching any test or CLI wiring)
--------------------------------------------------------------------------
`src.board.l1`'s three source stores (`odds_multibook.jsonl`,
`odds_snapshots.jsonl`, `f5_close.jsonl`) key every row on the odds
provider's own `event_id` -- an opaque hash -- and stamp `game_pk: null` on
every PriceObservation it emits (verified against the real backfilled store
in this worktree: zero of 56,680 rows carry a non-null `game_pk`). The
forward stores `src.core.asof.as_of` reads (`data/watch/*.jsonl`,
`data/processed/information_events.jsonl`, `weather_forecast.jsonl`,
`boxscores_2026.jsonl`) key on the MLB numeric `game_pk` instead, and no
store tracked in this worktree pairs the two ids for a game that has not
yet had a final boxscore written (the one join key `src.board.events` uses,
`(team_name, date)` against `boxscores_2026.jsonl`, only exists for
*finished* games -- see that module's docstring). For an in-progress or
future slate there is therefore no honest way to resolve an odds `event_id`
to its MLB `game_pk` from data already on disk, and this module does not
invent one: `GameRef` carries both ids as *optional*, independent fields,
`build_board` uses only `event_id` (or `game_pk`, if that is all a future L1
row carries), and `build_snapshot`'s `as_of` read is skipped -- honestly,
not silently -- whenever no `game_pk` is known for the game being built.
That yields a real but feature-sparse `PriceBlindSnapshot` for today's odds
captures; a future packet that adds the id join populates `assumption_exposure`
and non-price features on the same call graph without a signature change
here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from src.board.record import (
    PriceObservation, RecordValidationError, price_observation_from_dict,
)
from src.core import asof as asof_module
from src.engine.analyze import Proposal
from src.engine.snapshot import PriceBlindSnapshot, PricedBoard
from src.engine.truncation import ArrivalRecord, TruncationSample
from src.paths import processed_path

L1_PATH = processed_path("l1_observations.jsonl")
# `l1_observations.jsonl` rows (PriceObservation) carry no `commence_time`
# field at all (src/board/record.py); the odds provider's own pre-projection
# store does, one value per event_id (verified against the real backfilled
# store in this worktree). This is the first-pitch guard's only source for
# "when does this game actually start" -- see `commence_time_for` below.
ODDS_SNAPSHOTS_PATH = processed_path("odds_snapshots.jsonl")
# How far before commence_time a sampled decision instant `t` must sit.
# `engine truncation` picks t = min(latest capture, commence_time - margin)
# per game specifically so a game whose latest capture landed a minute
# before first pitch does not get sampled right at the wire.
DEFAULT_PRE_GAME_MARGIN_MINUTES = 5


class GlueError(ValueError):
    """A glue-layer request was malformed, or a store had nothing to answer
    it with -- never silently papered over with a fabricated sample."""


def _parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise GlueError(f"timestamp {value!r} is not timezone-aware")
        return value.astimezone(timezone.utc)
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        d = datetime.fromisoformat(v)
    except ValueError as exc:
        raise GlueError(f"timestamp {value!r} is not ISO-8601: {exc}") from None
    if d.tzinfo is None:
        raise GlueError(f"timestamp {value!r} is not timezone-aware")
    return d.astimezone(timezone.utc)


def _iso(value: str | datetime) -> str:
    return value if isinstance(value, str) else _parse_utc(value).isoformat()


@dataclass(frozen=True, slots=True)
class GameRef:
    """One game, in whichever of the two id spaces this glue module has to
    bridge (see module docstring). At least one of the two must be given;
    `board_key` (what `PricedBoard.game_pk`/L1 rows are matched on) prefers
    `event_id` because every L1 row in this project currently carries one
    and none carries a `game_pk`; `asof_key` is `game_pk` alone, since
    `src.core.asof`'s forward stores have no notion of `event_id` at all.
    """

    event_id: str | None = None
    game_pk: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id and not self.game_pk:
            raise GlueError("GameRef needs event_id and/or game_pk")

    @property
    def board_key(self) -> str:
        return self.event_id or self.game_pk

    @property
    def asof_key(self) -> str | None:
        return self.game_pk

    @staticmethod
    def of(game: "GameRef | str | int") -> "GameRef":
        if isinstance(game, GameRef):
            return game
        return GameRef(event_id=str(game))


# ---------------------------------------------------------------------------
# L1 reads
# ---------------------------------------------------------------------------

def _iter_l1_raw(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _row_key(raw: Mapping) -> str | None:
    if raw.get("event_id"):
        return str(raw["event_id"])
    if raw.get("game_pk") is not None:
        return str(raw["game_pk"])
    return None


def read_l1_observations(game: "GameRef | str | int", *,
                          path: Path | str = L1_PATH
                          ) -> tuple[PriceObservation, ...]:
    """Every L1 `PriceObservation` row for `game`, unfiltered by time.
    Malformed rows (a future store-shape change this record's own
    validators reject) are skipped, never raised past the caller -- L1 is a
    read this module does not own the writing side of."""
    ref = GameRef.of(game)
    key = ref.board_key
    out = []
    for raw in _iter_l1_raw(Path(path)):
        if _row_key(raw) != key:
            continue
        try:
            out.append(price_observation_from_dict(raw))
        except RecordValidationError:
            continue
    return tuple(out)


def commence_time_for(game: "GameRef | str | int", *,
                       path: Path | str = ODDS_SNAPSHOTS_PATH
                       ) -> str | None:
    """The event's own `commence_time`, read from `odds_snapshots.jsonl`
    rows keyed by `event_id` (see `ODDS_SNAPSHOTS_PATH` module note).
    `None` when no row for this game carries one -- either the store is
    missing, or this game is unknown to it -- so a caller with a
    first-pitch guard to enforce can tell "verified pre-game" apart from
    "cannot verify" and refuse rather than assume pre-game."""
    ref = GameRef.of(game)
    key = ref.board_key
    for raw in _iter_l1_raw(Path(path)):
        if str(raw.get("event_id")) == key and raw.get("commence_time"):
            return raw["commence_time"]
    return None


def games_captured_on(date_str: str, *, path: Path | str = L1_PATH
                       ) -> tuple[str, ...]:
    """Every `board_key` (see `GameRef`) with at least one L1 observation
    whose `observed_utc` date-prefix is `date_str`, sorted for determinism.
    Empty when the date has no captures at all -- callers refuse on that,
    this function just reports it honestly."""
    keys: set[str] = set()
    for raw in _iter_l1_raw(Path(path)):
        observed = raw.get("observed_utc") or ""
        if observed[:10] != date_str:
            continue
        key = _row_key(raw)
        if key:
            keys.add(key)
    return tuple(sorted(keys))


def latest_capture_time(game: "GameRef | str | int", date_str: str, *,
                         path: Path | str = L1_PATH) -> str | None:
    """The latest `observed_utc` on `date_str` for `game`, or `None` when
    the game has no L1 observation that day. Used as a game's own decision
    instant `t` when a caller has no other reason to pick one -- the
    honest choice given only "what did we capture" to go on."""
    rows = read_l1_observations(game, path=path)
    stamps = [r.observed_utc for r in rows if r.observed_utc[:10] == date_str]
    return max(stamps) if stamps else None


# ---------------------------------------------------------------------------
# Board / snapshot construction
# ---------------------------------------------------------------------------

def build_board(game: "GameRef | str | int", t: str | datetime, *,
                 path: Path | str = L1_PATH,
                 observations: Iterable[PriceObservation] | None = None,
                 commence_time: str | datetime | None = None
                 ) -> PricedBoard:
    """The stop-at-T `PricedBoard` for one game from L1 `PriceObservation`
    rows: every row with `observed_utc <= t`, nothing observed after `t`
    ever reaches the result (mirrors `src.core.asof.as_of`'s own stop-at-T
    discipline). Deterministic and pure once `observations` is supplied
    (the default reads the L1 store, which is itself a deterministic
    function of what is on disk).

    First-pitch guard: when `commence_time` is given, `t` must be strictly
    before it -- a board built at or after first pitch is an in-play board,
    not the pre-game board this engine's decision path is contracted to
    price (docs/planning bug #2). `commence_time=None` means "the caller
    did not or could not verify" and is NOT treated as "verified pre-game";
    it simply skips the guard, so a caller that needs the guarantee must
    supply `commence_time` (see `commence_time_for`).
    """
    ref = GameRef.of(game)
    t_dt = _parse_utc(t)
    if commence_time is not None:
        commence_dt = _parse_utc(commence_time)
        if t_dt >= commence_dt:
            raise GlueError(
                f"refusing to build an in-play board for {ref.board_key}: "
                f"t={_iso(t)} is not strictly before commence_time="
                f"{_iso(commence_time)}")
    rows = (tuple(observations) if observations is not None
            else read_l1_observations(ref, path=path))
    truncated = tuple(r for r in rows if _parse_utc(r.observed_utc) <= t_dt)
    return PricedBoard.from_price_observations(ref.board_key, _iso(t), truncated)


def board_facts(board: PricedBoard) -> tuple[tuple, dict]:
    """`(available_markets, books_by_market)` derivable from a `PricedBoard`
    -- the two non-price, board-shaped facts `PriceBlindSnapshot` may
    legitimately carry (docs/ENGINE_CONTRACT.md section 3: "a book count is
    not a price"). Computed from the board's own quotes, never from a
    price value on any of them."""
    markets = sorted({q.market_key for q in board.quotes})
    books_by_market = {
        m: len({q.book for q in board.quotes if q.market_key == m})
        for m in markets
    }
    return tuple(markets), books_by_market


def build_snapshot(game: "GameRef | str | int", t: str | datetime, *,
                    point_class: str = "LATE_BOARD",
                    features: Mapping[str, float] | None = None,
                    board: PricedBoard | None = None,
                    lineup_posted: bool = False,
                    as_of_stores=None) -> PriceBlindSnapshot:
    """The stop-at-T `PriceBlindSnapshot` for one game.

    Non-price features (point-in-time `as_of` reads) are pulled in only
    when `game` carries a `game_pk` -- see the module docstring's
    `game_pk`/`event_id` gap note; a game known only by `event_id` gets an
    honestly feature-sparse snapshot rather than a guessed one.
    `available_markets`/`books_by_market` are derived from `board` (this
    call's own `PricedBoard`, or the caller's) via `board_facts` when given
    -- board-shaped, never price-shaped, facts a PROPOSE-side system may
    see (ENGINE_CONTRACT.md section 3).
    """
    ref = GameRef.of(game)
    as_of_snapshot = None
    if ref.asof_key is not None:
        as_of_snapshot = asof_module.as_of(ref.asof_key, t, stores=as_of_stores)
    available_markets, books_by_market = (
        board_facts(board) if board is not None else ((), {}))
    return PriceBlindSnapshot.from_asof(
        game_pk=ref.board_key, t=_iso(t), point_class=point_class,
        features=features or {}, as_of_snapshot=as_of_snapshot,
        available_markets=available_markets, books_by_market=books_by_market,
        lineup_posted=lineup_posted,
    )


# ---------------------------------------------------------------------------
# Arrivals -- the provenance the truncation differential checks diffs against
# ---------------------------------------------------------------------------

def field_arrivals(game: "GameRef | str | int", t2h: str, t: str, *,
                    as_of_stores=None) -> tuple[ArrivalRecord, ...]:
    """`ArrivalRecord`s for `as_of` fields that became knowable strictly
    inside `(t2h, t]` for `game` -- a lineup posting, a probable-pitcher
    change, an umpire assignment. Empty when `game` carries no `game_pk`
    (`as_of` has nothing to key on there) -- honestly absent, not
    fabricated."""
    ref = GameRef.of(game)
    if ref.asof_key is None:
        return ()
    before = asof_module.as_of(ref.asof_key, t2h, stores=as_of_stores)
    after = asof_module.as_of(ref.asof_key, t, stores=as_of_stores)
    t2h_dt, t_dt = _parse_utc(t2h), _parse_utc(t)
    out = []
    for name, obs in after.fields.items():
        prior = before.fields.get(name)
        if prior is not None and prior.observed_utc == obs.observed_utc:
            continue  # same fact the t2h run already had -- not an arrival
        obs_dt = _parse_utc(obs.observed_utc)
        if t2h_dt < obs_dt <= t_dt:
            out.append(ArrivalRecord(field=name, observed_utc=obs.observed_utc))
    return tuple(out)


def price_arrivals(game: "GameRef | str | int", t2h: str, t: str, *,
                    path: Path | str = L1_PATH,
                    observations: Iterable[PriceObservation] | None = None
                    ) -> tuple[ArrivalRecord, ...]:
    """`ArrivalRecord`s for new L1 price observations inside `(t2h, t]` --
    a book quoting (or re-quoting) a market for the first time in the
    window. `ArrivalRecord`'s own docstring names `books_by_market:totals`
    as an example field; this is that field, populated from real data. A
    quote observed at X is honestly knowable at X, so recording its arrival
    is what makes ordinary price movement between `t2h` and `t`
    attributable rather than an unexplained (and therefore leakage-flagged)
    difference."""
    ref = GameRef.of(game)
    rows = (tuple(observations) if observations is not None
            else read_l1_observations(ref, path=path))
    t2h_dt, t_dt = _parse_utc(t2h), _parse_utc(t)
    seen: set[tuple] = set()
    out = []
    for row in rows:
        obs_dt = _parse_utc(row.observed_utc)
        if not (t2h_dt < obs_dt <= t_dt):
            continue
        key = (row.market_key, row.observed_utc)
        if key in seen:
            continue
        seen.add(key)
        out.append(ArrivalRecord(field=f"books_by_market:{row.market_key}",
                                  observed_utc=row.observed_utc))
    return tuple(sorted(out, key=lambda a: (a.observed_utc, a.field)))


def build_truncation_sample(game: "GameRef | str | int", t2h: str, t: str, *,
                             path: Path | str = L1_PATH,
                             point_class: str = "LATE_BOARD",
                             features_t2h: Mapping[str, float] | None = None,
                             features_t: Mapping[str, float] | None = None,
                             as_of_stores=None,
                             commence_time: str | None = None
                             ) -> TruncationSample:
    """One game's `TruncationSample`, built entirely from `build_board`,
    `build_snapshot` and the two arrival helpers above -- the whole seam
    `engine truncation` needs, in one call. `commence_time`, when given, is
    passed to both `build_board` calls so an in-play `t` OR `t2h` is
    refused (bug #2's first-pitch guard) rather than silently sampled."""
    ref = GameRef.of(game)
    rows = read_l1_observations(ref, path=path)
    board_t2h = build_board(ref, t2h, observations=rows,
                             commence_time=commence_time)
    board_t = build_board(ref, t, observations=rows,
                           commence_time=commence_time)
    snapshot_t2h = build_snapshot(
        ref, t2h, point_class=point_class, features=features_t2h,
        board=board_t2h, as_of_stores=as_of_stores)
    snapshot_t = build_snapshot(
        ref, t, point_class=point_class, features=features_t,
        board=board_t, as_of_stores=as_of_stores)
    arrivals = (field_arrivals(ref, t2h, t, as_of_stores=as_of_stores)
                + price_arrivals(ref, t2h, t, observations=rows))
    return TruncationSample(
        game_pk=ref.board_key, t2h=t2h, t=t,
        snapshot_t2h=snapshot_t2h, board_t2h=board_t2h,
        snapshot_t=snapshot_t, board_t=board_t, arrivals=arrivals,
    )


@dataclass(frozen=True, slots=True)
class SkippedGame:
    """One game `sample_truncation_inputs` declined to sample, and why --
    surfaced so a caller (the `engine truncation` CLI) can report the
    first-pitch guard's effect honestly instead of a silent shrink."""

    game: str
    reason: str


def sample_truncation_inputs(date_str: str, sample_size: int, *,
                              t_offset_minutes: int = 120,
                              path: Path | str = L1_PATH,
                              as_of_stores=None,
                              commence_path: Path | str = ODDS_SNAPSHOTS_PATH,
                              pre_game_margin_minutes: int =
                                  DEFAULT_PRE_GAME_MARGIN_MINUTES,
                              return_skipped: bool = False,
                              ) -> "tuple[TruncationSample, ...]":
    """Up to `sample_size` `TruncationSample`s for games captured on
    `date_str`, chosen by sorted `board_key` so the same date and sample
    size always consider the same games in the same order.

    First-pitch guard (bug #2): each game's own `t` is
    `min(latest L1 capture that day, commence_time - pre_game_margin_minutes)`,
    never the latest capture alone -- a game whose latest capture that day
    landed in-play would otherwise hand `analyze()` a board built after
    first pitch. `t2h` is `t - t_offset_minutes`. A game is SKIPPED
    (excluded, not erred on) when its `commence_time` cannot be found in
    `commence_path` (cannot verify pre-game, so it is never assumed
    pre-game) or when it has no L1 capture on `date_str` at all; skipping
    continues past sample_size candidates until either `sample_size`
    eligible games are found or the day's games are exhausted, so a date
    with some in-play games can still fill the sample from others. Pass
    `return_skipped=True` to additionally get back the list of
    `SkippedGame` this run declined and why.

    Refuses (`GlueError`) when the date has no captures at all, or when
    EVERY captured game was skipped, rather than returning an empty tuple a
    caller might mistake for a vacuously passing gate.
    """
    if sample_size <= 0:
        raise GlueError(f"sample_size must be positive, got {sample_size}")
    games = games_captured_on(date_str, path=path)
    if not games:
        raise GlueError(
            f"no L1 captures found for {date_str} in {path} -- refusing to "
            "fabricate a truncation sample. Run `python3 -m src.cli l1 "
            "--backfill` if new forward captures exist but L1 has not been "
            "reprojected yet.")
    samples = []
    skipped: list[SkippedGame] = []
    for key in games:
        if len(samples) >= sample_size:
            break
        latest = latest_capture_time(key, date_str, path=path)
        if latest is None:
            skipped.append(SkippedGame(key, "no L1 capture on this date"))
            continue
        commence = commence_time_for(key, path=commence_path)
        if commence is None:
            skipped.append(SkippedGame(
                key, "commence_time unknown in commence_path -- cannot "
                     "verify pre-game, refusing to assume it"))
            continue
        commence_dt = _parse_utc(commence)
        margin_cutoff = commence_dt - timedelta(minutes=pre_game_margin_minutes)
        t_dt = min(_parse_utc(latest), margin_cutoff)
        t2h_dt = t_dt - timedelta(minutes=t_offset_minutes)
        if t_dt >= commence_dt:
            skipped.append(SkippedGame(
                key, f"latest capture {latest} is at/after commence_time "
                     f"{commence} -- in-play, refusing"))
            continue
        t, t2h = _iso(t_dt), _iso(t2h_dt)
        samples.append(build_truncation_sample(
            key, t2h, t, path=path, as_of_stores=as_of_stores,
            commence_time=commence))
    if not samples:
        raise GlueError(
            f"no eligible PRE-GAME truncation samples for {date_str}: all "
            f"{len(skipped)} captured game(s) were skipped (in-play or "
            f"commence_time unknown) -- {[(s.game, s.reason) for s in skipped]}")
    if return_skipped:
        return tuple(samples), tuple(skipped)
    return tuple(samples)


# ---------------------------------------------------------------------------
# The trivial fallback system
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TrivialAlwaysHomeSystem:
    """The "registered trivial system" fallback for `engine truncation`
    when no evolab-adapter genome can be wired honestly.

    `src.engine.adapters.EvolabGenomeSystem` decides off signal features
    (`era_diff`, `whip_diff`, ...) that this project's point-in-time
    feature pipeline has never populated for an odds-provider `event_id` --
    no `game_pk` mapping exists in this worktree's tracked data for an
    in-progress slate (module docstring), so a real genome would honestly
    see empty `features` and never propose, making the differential
    trivially and uninterestingly empty. This system instead proposes
    deterministically -- a fixed `p_model`, never derived from price or a
    clock -- so PROJECT/ATTACK/RATE still run against the real L1 price
    data end to end: whatever changes between its `t-2h` and `t`
    `DecisionRecord`s changes for exactly one honest reason, the board's
    own price data moving.
    """

    id: str = "trivial_always_home"
    version: str = "trivial-1"
    spec_hash: str = "trivial_always_home:1"
    declared_markets: tuple = ("h2h",)
    declared_inputs: tuple = ()
    min_grade: str = "D"
    expected_selection_rate: float = 1.0
    p_model: float = 0.52

    def propose(self, view: PriceBlindSnapshot) -> tuple:
        if "h2h" not in view.available_markets:
            return ()
        return (Proposal(
            system_id=self.id, system_version=self.version,
            market_key="h2h", side="home", p_model=self.p_model,
            thesis="trivial fallback: always proposes home at a fixed, "
                   "never price/clock-derived p_model -- src.engine.glue",
            evidence=("trivial_fallback",),
        ),)
