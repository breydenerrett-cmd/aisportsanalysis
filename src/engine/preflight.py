"""S8 pre-slate freshness guard: `engine slate` refuses, loudly and before
placing a single wager, when either input the slate runner depends on is too
old to bet on. Wired into `src.cli._cmd_engine_slate` so it runs before
`src.engine.slate.run_slate` on every unattended and manual invocation --
see docs/CHECKPOINT_PHASE0_2026-09-03.md S8.

TWO CHECKS, TWO NAMED THRESHOLDS
---------------------------------
1. Price capture freshness (`PRICE_CAPTURE_STALE_HOURS`): is there a recent
   L1 price observation for the date being sliced. `engine slate` reads
   prices through this same L1 store (`src.board.l1`, via
   `src.engine.glue.build_board`), so a capture outage before this guard
   would otherwise have the engine silently price a slate off of hours-old
   quotes with no sign anything was wrong -- exactly the "quietly betting
   on stale inputs" failure this guard exists to close (task S8, point 2).

2. Matchup feature coverage (`MATCHUP_COVERAGE_MAX_LAG_DAYS`): how far
   behind today the Statcast pitch store's manual backfill sits
   (`src.providers.statcast_pitches`, `SEASON_BOUNDS[2026]`). Six of the
   seven matchup features the research matrix computes
   (`src.research.matrix`) are pitch-derived and rebuilt forward from this
   store (`src.pipeline.rebuilt`); once its coverage falls far enough
   behind, those six features describe a roster/form snapshot from over a
   week ago rather than the truth on the day being decided. There is
   deliberately no automated forward-ingest for this store yet (see
   docs/RUNBOOK.md's named gap) -- this guard is what keeps that gap from
   being invisible instead of quietly shipping stale features.

Both checks are read-only over already-captured stores; neither one
fetches anything or writes anything on a pass or a refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.engine import glue as glue_module
from src.providers import statcast_pitches

# Hourly forward-capture cadence (scripts/forward_capture.sh) means the
# newest L1 observation for a live day should normally be well under an
# hour old. 3 hours tolerates up to two consecutive missed hourly cycles
# (a transient provider outage, a container restart -- docs/OVERNIGHT_RUN.md
# has examples of both) before treating the board as too old to safely
# price a slate off of; that is meaningfully tighter than the ~24h gap
# between daily-loop runs, so a bad night is caught the next morning
# rather than waved through.
PRICE_CAPTURE_STALE_HOURS = 3

# The Statcast pitch-store backfill (docs/CHECKPOINT_PHASE0_2026-09-03.md
# §5 point 5) is manual with no forward-ingest cadence yet, so its coverage
# only ever falls further behind today until that follow-up lands. 3 days
# is deliberately tight -- tight enough that it is already tripped by the
# store's real, currently-known coverage gap (ending 2026-08-27), which is
# exactly the honest outcome wanted here: this guard must refuse today
# rather than understate how stale the six pitch-derived matchup features
# already are.
MATCHUP_COVERAGE_MAX_LAG_DAYS = 3


class PreflightError(ValueError):
    """`now` given to `check()` was not usable (not timezone-aware)."""


@dataclass(frozen=True, slots=True)
class PreflightResult:
    ok: bool
    reasons: tuple[str, ...]
    price_capture_age_hours: float | None
    matchup_coverage_end: str | None
    matchup_coverage_lag_days: int | None


def _parse_utc(value: str) -> datetime:
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _price_capture_age_hours(date_str: str, now: datetime, *,
                              l1_path=None) -> float | None:
    """Hours since the newest L1 observation captured on `date_str`, across
    every game with any capture that day. `None` when the date has no
    capture at all -- a distinct, equally-refusing case from "too old".
    `l1_path` overrides the real L1 store -- tests only; production always
    reads `glue_module.L1_PATH` via the default."""
    kwargs = {"path": l1_path} if l1_path is not None else {}
    games = glue_module.games_captured_on(date_str, **kwargs)
    latest = None
    for game in games:
        stamp = glue_module.latest_capture_time(game, date_str, **kwargs)
        if stamp is None:
            continue
        parsed = _parse_utc(stamp)
        if latest is None or parsed > latest:
            latest = parsed
    if latest is None:
        return None
    return (now - latest).total_seconds() / 3600.0


def _matchup_coverage_end(store=None) -> str | None:
    """The latest date the Statcast pitch store has actually ingested, read
    from its manifest (not the declared `SEASON_BOUNDS` target, which is
    where the backfill is aiming, not what is on disk). `None` when the
    manifest has no windows at all."""
    manifest = statcast_pitches.read_manifest(
        store if store is not None else statcast_pitches.DEFAULT_STORE)
    windows = manifest.get("windows") or {}
    ends = [key.split("..", 1)[1] for key in windows if ".." in key]
    return max(ends) if ends else None


def check(date_str: str, *, now: datetime | None = None,
          l1_path=None, statcast_store=None) -> PreflightResult:
    """Run both freshness checks for the slate being built for `date_str`.

    Pure and read-only: reads the L1 store and the Statcast manifest, never
    the network, and never writes anything. `result.ok` is False when
    either check fails; `result.reasons` names every failure (both may fire
    together, never truncated to the first one), so a refusal is fully
    explained in the printed output rather than requiring a second look.
    `l1_path`/`statcast_store` override the real stores -- tests only;
    `_cmd_engine_slate` always calls this with the defaults.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise PreflightError(f"now={now!r} is not timezone-aware")

    reasons: list[str] = []

    price_age = _price_capture_age_hours(date_str, now, l1_path=l1_path)
    if price_age is None:
        reasons.append(
            f"no price capture observed for {date_str} at all -- refusing "
            "to slate on zero data")
    elif price_age > PRICE_CAPTURE_STALE_HOURS:
        reasons.append(
            f"price capture for {date_str} is {price_age:.1f}h stale, past "
            f"the {PRICE_CAPTURE_STALE_HOURS}h threshold "
            "(PRICE_CAPTURE_STALE_HOURS)")

    coverage_end = _matchup_coverage_end(store=statcast_store)
    lag_days = None
    if coverage_end is None:
        reasons.append(
            "the matchup feature store (Statcast pitch backfill) has no "
            "coverage recorded at all")
    else:
        lag_days = (now.date() - date.fromisoformat(coverage_end)).days
        if lag_days > MATCHUP_COVERAGE_MAX_LAG_DAYS:
            reasons.append(
                f"the matchup feature store's coverage ends {coverage_end} "
                f"({lag_days}d before {now.date().isoformat()}), past the "
                f"{MATCHUP_COVERAGE_MAX_LAG_DAYS}d threshold "
                "(MATCHUP_COVERAGE_MAX_LAG_DAYS)")

    return PreflightResult(
        ok=not reasons, reasons=tuple(reasons),
        price_capture_age_hours=price_age,
        matchup_coverage_end=coverage_end,
        matchup_coverage_lag_days=lag_days,
    )
