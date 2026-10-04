"""Does feeding the opposing starter improve the batter total-bases model?

Pure functions for ONE bounded, pre-registered paper comparison
(`docs/PREREG_TB_STARTER_AWARE.md`). Nothing here reads a file, a clock or a
network; `scripts/tb_starter_compare.py` does the I/O and hands rows in.

THE QUESTION
------------
`playerprops.price_prop` already contains an opposing-starter adjustment
(`pitcher_hit_factor`, `STARTER_SHARE`, `BF_REGRESSION`, bounds 0.80..1.25) and
no caller passes it. This module prices the same batter-game twice:

    WITHOUT  price_prop(...)                               (what ships today)
    WITH     price_prop(..., pitcher_hits_allowed=H,
                            pitcher_batters_faced=BF)      (the unused path)

and scores both against what the batter did. Nothing is tuned, fitted or
re-specified; this module only CALLS `price_prop`. Everything else (the
batter's own rates, the league rates, the slot table, the plate-appearance
fallback) is identical in both arms.

SIGN CONVENTION, STATED ONCE
----------------------------
    d = loss(WITHOUT) - loss(WITH)        per batter-game, log loss in nats

POSITIVE d means the starter-aware arm predicted better. A confidence interval
for the mean of d that lies entirely above zero is evidence FOR feeding the
starter; entirely below zero is evidence AGAINST it.

POINT-IN-TIME, BY CONSTRUCTION
------------------------------
* A batter's prior lines are his own regular-season rows with date STRICTLY
  BEFORE the game's date. A game on the date contributes nothing, so the
  first game of a doubleheader never feeds the second.
* The league rates are the same strictly-before set.
* The starter's hits allowed and batters faced are his same-season
  appearances with date STRICTLY BEFORE the game's date.
* Every date that enters is refused unless it is inside 2023-01-01..2024-12-31
  (`assert_allowed_date`). 2025 is tuning-only and 2026 is sealed; the guard
  is structural, a raised `SealedDataError`, not a policy someone must
  remember.

ONE KNOWN LIMIT OF THE INPUTS, NOT HIDDEN
-----------------------------------------
The starter's IDENTITY comes from `mlb_results.csv`'s `*_probable_id`, which
`docs/AUDIT_PROBABLE_PITCHER_PIT.md` measured as the starter at first pitch,
not the announcement (99.9% equal to who threw the first pitch). The starter's
STATISTICS fed to the model are strictly pre-game; only who he is carries
hindsight. That is disclosed in the pre-registration and bounds how far this
comparison can speak for a live board.

Pure. stdlib only.
"""

from __future__ import annotations

import bisect
import math
import random
from typing import Iterable, Mapping, Optional, Sequence

from src.analysis import playerprops

# ---------------------------------------------------------------------------
# Evidence window. Mirrors `src/research/matrix.ALLOWED_SEASONS` (a test pins
# the equality) without importing the matrix module's whole dependency tree.
# ---------------------------------------------------------------------------

ALLOWED_SEASONS = (2023, 2024)
WINDOW_START = "2023-01-01"
WINDOW_END = "2024-12-31"

MARKET = "batter_total_bases"
PRIMARY_LINE = 1.5     # P(2 or more total bases)
SECONDARY_LINE = 0.5   # P(1 or more total bases)
LINES = (PRIMARY_LINE, SECONDARY_LINE)

# Numerical necessity, applied identically to both arms (same convention as
# `scripts/prereg_market_vs_model.py`).
EPS = 1e-6

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261003
CI_LOW_QUANTILE = 0.025
CI_HIGH_QUANTILE = 0.975

# A probability that moves by more than this between the arms counts as
# "moved" in the descriptive table.
MOVE_THRESHOLD = 0.01


class SealedDataError(ValueError):
    """A date outside 2023-01-01..2024-12-31 reached code that must refuse it."""


class TbStarterError(ValueError):
    """The inputs cannot be compared honestly."""


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def in_window(date) -> bool:
    """True for an ISO date string inside the evidence window.

    Total, never raises: it is the FILTER a stream uses to drop rows it must
    not keep (2025, 2026). Anything unparseable is simply outside.
    """
    if not isinstance(date, str) or len(date) < 10:
        return False
    head = date[:10]
    if not (head[4] == "-" and head[7] == "-"
            and head[:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit()):
        return False
    return WINDOW_START <= head <= WINDOW_END


def assert_allowed_date(date) -> str:
    """Return the ISO date, or raise `SealedDataError`. A hard error.

    Used on every date that actually enters a computation, as opposed to
    `in_window`, which only filters a stream.
    """
    if not in_window(date):
        raise SealedDataError(
            f"date {date!r} is outside {WINDOW_START}..{WINDOW_END}; 2025 is "
            "tuning-only and 2026-01-01..2026-08-27 is sealed -- refusing")
    return date[:10]


def assert_allowed_season(season) -> int:
    """Return the season as an int, or raise `SealedDataError`."""
    try:
        value = int(season)
    except (TypeError, ValueError):
        raise SealedDataError(f"season {season!r} is not a year") from None
    if isinstance(season, bool) or value not in ALLOWED_SEASONS:
        raise SealedDataError(
            f"season {season!r} is outside {ALLOWED_SEASONS}; 2025 is "
            "tuning-only and 2026 is sealed -- refusing")
    return value


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def clip(p: float) -> float:
    return min(max(float(p), EPS), 1.0 - EPS)


def log_loss_one(p: float, y: int) -> float:
    """Per-event log loss in nats, with the registered clip."""
    p = clip(p)
    return -math.log(p) if y else -math.log(1.0 - p)


def brier_one(p: float, y: int) -> float:
    return (float(p) - y) ** 2


def paired_difference(p_without: float, p_with: float, y: int) -> float:
    """loss(WITHOUT) - loss(WITH). Positive means WITH predicted better."""
    return log_loss_one(p_without, y) - log_loss_one(p_with, y)


# ---------------------------------------------------------------------------
# Clustered bootstrap
# ---------------------------------------------------------------------------

def per_date_aggregates(rows: Iterable[Mapping], value_key: str = "d") -> list:
    """[(date, sum_of_value, n)] sorted ascending by date.

    The date-clustered bootstrap needs only these. Resampling whole dates is
    exactly equivalent to resampling the rows and taking the mean, and costs
    O(dates) per draw instead of O(rows).
    """
    acc: dict = {}
    for row in rows:
        date = row["date"]
        total, n = acc.get(date, (0.0, 0))
        acc[date] = (total + row[value_key], n + 1)
    return [(date, total, n) for date, (total, n) in sorted(acc.items())]


def clustered_mean_interval(aggregates: Sequence, *,
                            resamples: int = BOOTSTRAP_RESAMPLES,
                            seed: int = BOOTSTRAP_SEED) -> dict:
    """95% percentile interval of the mean, resampling DATES with replacement.

    Same algorithm, same index arithmetic and same percentile rule as
    `src.model.discovery.clustered_bootstrap` (sorted dates, `randrange`
    positions, `int(0.025 * N)` and `int(0.975 * N)` order statistics); a test
    pins the two to the same numbers. Seeded and deterministic: the same
    aggregates and seed always return the same interval.

    `aggregates` is `per_date_aggregates` output.
    """
    clusters = [(total, n) for _date, total, n in sorted(aggregates)]
    total_n = sum(n for _t, n in clusters)
    if len(clusters) < 2 or total_n < 1:
        return {"estimate": None, "low": None, "high": None, "resamples": 0,
                "clusters": len(clusters), "n": total_n,
                "reason": "fewer than two distinct dates to resample"}
    estimate = sum(t for t, _n in clusters) / total_n
    rng = random.Random(seed)
    g = len(clusters)
    draws = []
    for _ in range(resamples):
        s = 0.0
        m = 0
        for _ in range(g):
            t, n = clusters[rng.randrange(g)]
            s += t
            m += n
        if m:
            draws.append(s / m)
    draws.sort()
    return {
        "estimate": estimate,
        "low": draws[int(CI_LOW_QUANTILE * len(draws))],
        "high": draws[min(len(draws) - 1, int(CI_HIGH_QUANTILE * len(draws)))],
        "resamples": len(draws), "clusters": g, "n": total_n, "reason": None,
    }


# ---------------------------------------------------------------------------
# Registered decision rule
# ---------------------------------------------------------------------------

SUPPORTED = "SUPPORTED"
WORSE = "WORSE"
NOT_SUPPORTED = "NOT_SUPPORTED"


def decide(first_look: Optional[Mapping], confirming: Optional[Mapping]) -> dict:
    """The registered rule, applied literally.

    `first_look` is the 2023 interval dict, `confirming` the 2024 one (both
    from `clustered_mean_interval`; the quantity is mean(d)).

    SUPPORTED   2024 interval lies entirely above zero AND the 2023 point
                estimate is positive.
    WORSE       2024 interval lies entirely below zero.
    NOT_SUPPORTED   anything else, including any missing input.

    A 2023 point estimate of exactly zero is not "the same sign" and cannot
    support. Nothing here is parameterised: there is no threshold to move.
    """
    def usable(block):
        return (block is not None and block.get("estimate") is not None
                and block.get("low") is not None and block.get("high") is not None)

    if not usable(first_look) or not usable(confirming):
        return {"verdict": NOT_SUPPORTED, "reason": "an interval is missing"}
    est23 = first_look["estimate"]
    lo24, hi24 = confirming["low"], confirming["high"]
    if hi24 < 0:
        return {"verdict": WORSE,
                "reason": "the 2024 interval lies entirely below zero"}
    if lo24 > 0 and est23 > 0:
        return {"verdict": SUPPORTED,
                "reason": "the 2024 interval lies entirely above zero and the "
                          "2023 point estimate is positive"}
    if lo24 > 0:
        return {"verdict": NOT_SUPPORTED,
                "reason": "the 2024 interval lies above zero but the 2023 "
                          "point estimate is not positive"}
    return {"verdict": NOT_SUPPORTED,
            "reason": "the 2024 interval includes zero"}


# ---------------------------------------------------------------------------
# Point-in-time inputs
# ---------------------------------------------------------------------------

class RunningLeague:
    """League per-PA rates over every batter row added so far.

    The totals are fed through `playerprops.league_rates` itself (one
    aggregate row), so the rates are computed by the model's own code and can
    never drift from it.
    """

    _FIELDS = ("pa", "h", "doubles", "triples", "hr", "r", "rbi")

    def __init__(self):
        self._sums = {field: 0 for field in self._FIELDS}
        self.rows = 0

    def add(self, row: Mapping) -> None:
        for field in self._FIELDS:
            self._sums[field] += int(row.get(field) or 0)
        self.rows += 1

    def rates(self) -> Optional[dict]:
        """League rates, or None while there is no plate appearance yet."""
        try:
            return playerprops.league_rates([dict(self._sums)])
        except playerprops.PropError:
            return None


class StarterIndex:
    """A pitcher's same-season hits allowed and batters faced, strictly before a date.

    Built once from appearance rows (`pitcher_logs.jsonl` shape: person_id,
    date, hits, batters_faced). `before(pid, date)` is O(log n) with prefix
    sums, and by construction can only see rows whose date is earlier than the
    one asked about and in the same calendar year.

    Rows with no date (bookkeeping markers), a date outside the evidence
    window, or a missing hits / batters_faced are skipped, not zero-filled.
    """

    def __init__(self, rows: Iterable[Mapping]):
        staging: dict = {}
        self.skipped = {"no_date_or_outside_window": 0, "missing_hits_or_bf": 0}
        for row in rows:
            date = row.get("date")
            if not date or not in_window(str(date)):
                self.skipped["no_date_or_outside_window"] += 1
                continue
            hits, bf = row.get("hits"), row.get("batters_faced")
            if hits is None or bf is None:
                self.skipped["missing_hits_or_bf"] += 1
                continue
            staging.setdefault(int(row["person_id"]), []).append(
                (str(date)[:10], int(hits), int(bf)))
        self._dates: dict = {}
        self._cum_hits: dict = {}
        self._cum_bf: dict = {}
        for pid, items in staging.items():
            items.sort()
            self._dates[pid] = [d for d, _h, _b in items]
            ch, cb = [0], [0]
            for _d, h, b in items:
                ch.append(ch[-1] + h)
                cb.append(cb[-1] + b)
            self._cum_hits[pid] = ch
            self._cum_bf[pid] = cb

    def before(self, pid, date) -> Optional[tuple]:
        """(hits_allowed, batters_faced) strictly before `date`, same season.

        None when the pitcher has no usable prior appearance that season
        (batters faced of zero is no information, not a league-average guess).
        """
        date = assert_allowed_date(date)
        if pid is None or int(pid) not in self._dates:
            return None
        pid = int(pid)
        dates = self._dates[pid]
        stop = bisect.bisect_left(dates, date)              # first date >= game date
        start = bisect.bisect_left(dates, date[:4] + "-01-01")
        if stop <= start:
            return None
        hits = self._cum_hits[pid][stop] - self._cum_hits[pid][start]
        bf = self._cum_bf[pid][stop] - self._cum_bf[pid][start]
        if bf <= 0:
            return None
        return hits, bf


def build_slot_map(lineup_rows: Iterable[Mapping]) -> tuple:
    """({(game_pk, person_id): slot}, stats) from posted-lineup rows.

    A game with two lineup rows that disagree about a batter, or a batter
    listed twice in one lineup with different orders, gets slot None for that
    batter (the model's own fallback then applies) and is counted. Empty
    bookkeeping rows are skipped. Only rows dated inside the window are kept.
    """
    seen: dict = {}
    conflicts = set()
    stats = {"lineup_rows_kept": 0, "lineup_rows_outside_window": 0,
             "lineup_rows_empty_marker": 0, "conflicting_batters": 0}
    for row in lineup_rows:
        if row.get("empty") or row.get("game_pk") is None:
            stats["lineup_rows_empty_marker"] += 1
            continue
        if not in_window(str(row.get("date"))):
            stats["lineup_rows_outside_window"] += 1
            continue
        stats["lineup_rows_kept"] += 1
        for side in ("away", "home"):
            for entry in row.get(side) or ():
                pid, order = entry.get("person_id"), entry.get("order")
                if pid is None:
                    continue
                key = (int(row["game_pk"]), int(pid))
                if key in seen and seen[key] != order:
                    conflicts.add(key)
                seen.setdefault(key, order)
    for key in conflicts:
        seen[key] = None
    stats["conflicting_batters"] = len(conflicts)
    return seen, stats


def slot_table_from_frozen(params: Mapping) -> dict:
    """{int slot: expected PA} from `card_v2_frozen_params.json`'s table."""
    raw = params["slot_plate_appearances"]
    return {int(k): float(v) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# The two arms
# ---------------------------------------------------------------------------

def price_arms(*, line: float, batter_lines: Sequence[Mapping], league: Mapping,
               batting_slot, slot_table: Mapping,
               starter_totals: Optional[tuple]) -> dict:
    """Price one batter-game under both arms for one line.

    `starter_totals` is (hits_allowed, batters_faced) or None. With None the
    WITH call is made with no starter arguments, i.e. the very same call as
    WITHOUT, so the arms are identical by construction and a test can pin it.

    Raises `playerprops.PropError` when the batter has no usable rate; the
    caller counts and excludes that batter-game from BOTH arms.
    """
    common = dict(market=MARKET, line=line, batter_lines=batter_lines,
                  league=league, batting_slot=batting_slot,
                  slot_table=slot_table)
    without = playerprops.price_prop(**common)
    if starter_totals is None:
        with_ = playerprops.price_prop(**common)
    else:
        hits, bf = starter_totals
        with_ = playerprops.price_prop(
            **common, pitcher_hits_allowed=hits, pitcher_batters_faced=bf)
    return {
        "p_without": without["probability"],
        "p_with": with_["probability"],
        "pitcher_factor": with_["pitcher_factor"],
        "blended_factor": with_["blended_factor"],
        "expected_pa": without["expected_pa"],
        "expected_pa_source": without["expected_pa_source"],
        "expected_pa_with": with_["expected_pa"],
    }


def _opposing_probable(result: Mapping, side: str):
    key = "home_probable_id" if side == "away" else "away_probable_id"
    raw = result.get(key)
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _team_side(result: Mapping, row: Mapping):
    """'away' / 'home' from the box row's team_id against the result row, or
    None when the two disagree or are missing."""
    try:
        tid = int(row.get("team_id"))
        away, home = int(result.get("away_team_id")), int(result.get("home_team_id"))
    except (TypeError, ValueError):
        return None
    if tid == away and row.get("side") == "away":
        return "away"
    if tid == home and row.get("side") == "home":
        return "home"
    return None


def build_comparison_rows(*, season, box_rows: Iterable[Mapping],
                          results: Mapping, slot_map: Mapping,
                          starters: StarterIndex, slot_table: Mapping,
                          limit: Optional[int] = None) -> dict:
    """Score every eligible batter-game of one season under both arms.

    `results` maps game_pk -> result row (needs game_type, date, team ids and
    the two probable ids). `box_rows` are box-score rows of ONE season; only
    `type == "batter"` rows of regular-season games are used.

    Returns {"rows": [...], "counts": {...}}. One row per batter per game.
    Games are walked in date order and a date's rows are added to the batter
    and league history only AFTER every row of that date has been priced, so a
    game on the date never counts toward its own prediction.

    `limit` caps the number of PRICED rows, for timing a slice only.
    """
    season = assert_allowed_season(season)
    counts = {
        "box_rows_seen": 0, "batter_rows": 0,
        "excluded_not_regular_season_or_unmatched_game": 0,
        "excluded_wrong_season_date": 0,
        "excluded_result_date_mismatch": 0,
        "excluded_duplicate_batter_game": 0,
        "excluded_side_team_mismatch": 0,
        "excluded_no_outcome": 0,
        "excluded_no_league_history": 0,
        "excluded_no_rate": 0,
        "excluded_no_rate_by_cause": {},
        "scored": 0, "starter_known": 0, "starter_unknown": 0,
        "starter_unknown_by_cause": {"no_probable_id": 0,
                                     "no_prior_logged_appearance": 0},
        "slot_known": 0, "slot_unknown": 0,
    }
    by_date: dict = {}
    seen_keys = set()
    for row in box_rows:
        counts["box_rows_seen"] += 1
        if row.get("type") != "batter":
            continue
        counts["batter_rows"] += 1
        date = str(row.get("date") or "")
        if not in_window(date) or date[:4] != str(season):
            # In-window but another season, or outside the window altogether.
            counts["excluded_wrong_season_date"] += 1
            continue
        game = results.get(row.get("game_pk"))
        if game is None or game.get("game_type") != "R":
            counts["excluded_not_regular_season_or_unmatched_game"] += 1
            continue
        if game.get("date") != date:
            counts["excluded_result_date_mismatch"] += 1
            continue
        key = (row.get("game_pk"), row.get("player_id"))
        if key in seen_keys:
            counts["excluded_duplicate_batter_game"] += 1
            continue
        seen_keys.add(key)
        by_date.setdefault(date, []).append(row)

    history: dict = {}          # player_id -> [(date, row)] in date order
    league = RunningLeague()
    out = []
    priced = 0
    for date in sorted(by_date):
        assert_allowed_date(date)
        league_rates = league.rates()
        for row in sorted(by_date[date],
                          key=lambda r: (r.get("game_pk"), r.get("player_id"))):
            if limit is not None and priced >= limit:
                break
            game = results[row["game_pk"]]
            side = _team_side(game, row)
            if side is None:
                counts["excluded_side_team_mismatch"] += 1
                continue
            tb = row.get("total_bases")
            if tb is None:
                counts["excluded_no_outcome"] += 1
                continue
            if league_rates is None:
                counts["excluded_no_league_history"] += 1
                continue
            prior = [r for d, r in history.get(row["player_id"], ())
                     if d < date]
            slot = slot_map.get((int(row["game_pk"]), int(row["player_id"])))
            probable = _opposing_probable(game, side)
            totals = starters.before(probable, date) if probable is not None else None
            try:
                arms = {line: price_arms(
                    line=line, batter_lines=prior, league=league_rates,
                    batting_slot=slot, slot_table=slot_table,
                    starter_totals=totals) for line in LINES}
            except playerprops.PropError as exc:
                message = str(exc)
                cause = ("below the plate-appearance floor"
                         if "floor" in message else message[:60])
                counts["excluded_no_rate"] += 1
                bucket = counts["excluded_no_rate_by_cause"]
                bucket[cause] = bucket.get(cause, 0) + 1
                continue
            priced += 1
            counts["scored"] += 1
            if totals is None:
                counts["starter_unknown"] += 1
                counts["starter_unknown_by_cause"][
                    "no_probable_id" if probable is None
                    else "no_prior_logged_appearance"] += 1
            else:
                counts["starter_known"] += 1
            counts["slot_known" if slot is not None else "slot_unknown"] += 1
            tb = int(tb)
            y2, y1 = int(tb >= 2), int(tb >= 1)
            main, second = arms[PRIMARY_LINE], arms[SECONDARY_LINE]
            out.append({
                "date": date, "game_pk": int(row["game_pk"]),
                "player_id": int(row["player_id"]), "slot": slot,
                "starter_known": totals is not None,
                "starter_hits": totals[0] if totals else None,
                "starter_bf": totals[1] if totals else None,
                "factor": main["pitcher_factor"],
                "blended_factor": main["blended_factor"],
                "tb": tb, "y2": y2, "y1": y1,
                "p2_without": main["p_without"], "p2_with": main["p_with"],
                "p1_without": second["p_without"], "p1_with": second["p_with"],
                "d2": paired_difference(main["p_without"], main["p_with"], y2),
                "d1": paired_difference(second["p_without"], second["p_with"], y1),
            })
        if limit is not None and priced >= limit:
            break
        # Only now does this date become history.
        for row in by_date[date]:
            history.setdefault(row["player_id"], []).append((date, row))
            league.add(row)
    return {"rows": out, "counts": counts}


# ---------------------------------------------------------------------------
# Descriptive tables (no decision rides on any of them)
# ---------------------------------------------------------------------------

def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def event_summary(rows: Sequence[Mapping], event: str) -> dict:
    """Primary-style summary for one event ('2' = 2+ TB, '1' = 1+ TB)."""
    y_key, d_key = f"y{event}", f"d{event}"
    pw, pv = f"p{event}_without", f"p{event}_with"
    n = len(rows)
    out = {"n": n}
    if not n:
        return out
    out["base_rate"] = _mean([r[y_key] for r in rows])
    out["mean_p_without"] = _mean([r[pw] for r in rows])
    out["mean_p_with"] = _mean([r[pv] for r in rows])
    out["log_loss_without"] = _mean([log_loss_one(r[pw], r[y_key]) for r in rows])
    out["log_loss_with"] = _mean([log_loss_one(r[pv], r[y_key]) for r in rows])
    out["brier_without"] = _mean([brier_one(r[pw], r[y_key]) for r in rows])
    out["brier_with"] = _mean([brier_one(r[pv], r[y_key]) for r in rows])
    out["share_moved_over_one_point"] = _mean(
        [1.0 if abs(r[pv] - r[pw]) > MOVE_THRESHOLD else 0.0 for r in rows])
    out["mean_abs_move"] = _mean([abs(r[pv] - r[pw]) for r in rows])
    out["paired"] = clustered_mean_interval(per_date_aggregates(rows, d_key))
    return out


def reliability_table(rows: Sequence[Mapping], event: str, arm: str,
                      bins: int = 10) -> list:
    """Equal-width reliability table through the repo's own calibration code."""
    from src.core import calibration
    key = f"p{event}_{arm}"
    curve = calibration.reliability_curve(
        [r[key] for r in rows], [r[f"y{event}"] for r in rows], bins=bins)
    return [{"lower": b["lower"], "upper": b["upper"], "count": b["count"],
             "mean_predicted": b["mean_predicted"],
             "observed_rate": b["observed_rate"], "gap": b["gap"]}
            for b in curve]


def factor_distribution(rows: Sequence[Mapping]) -> dict:
    """Distribution of the starter factor over starter-known rows."""
    values = sorted(r["factor"] for r in rows if r["starter_known"])
    if not values:
        return {"n": 0}

    def q(frac):
        return values[min(len(values) - 1, int(frac * len(values)))]

    return {
        "n": len(values), "min": values[0], "p05": q(0.05), "p25": q(0.25),
        "median": q(0.50), "p75": q(0.75), "p95": q(0.95), "max": values[-1],
        "mean": _mean(values),
        "share_at_lower_bound": _mean(
            [1.0 if v <= playerprops.MIN_PITCHER_FACTOR + 1e-12 else 0.0
             for v in values]),
        "share_at_upper_bound": _mean(
            [1.0 if v >= playerprops.MAX_PITCHER_FACTOR - 1e-12 else 0.0
             for v in values]),
    }


def tercile_table(rows: Sequence[Mapping], event: str) -> list:
    """Mean paired difference by starter-factor tercile (starter-known rows).

    Equal-count terciles by rank, ties broken by (date, game_pk, player_id),
    so the split is deterministic. Low factor = a starter who allows fewer
    hits than league; high = more.
    """
    known = sorted((r for r in rows if r["starter_known"]),
                   key=lambda r: (r["factor"], r["date"], r["game_pk"],
                                  r["player_id"]))
    n = len(known)
    d_key = f"d{event}"
    out = []
    for i, label in enumerate(("low_factor", "middle_factor", "high_factor")):
        chunk = known[(i * n) // 3:((i + 1) * n) // 3]
        out.append({
            "tercile": label, "n": len(chunk),
            "factor_min": chunk[0]["factor"] if chunk else None,
            "factor_max": chunk[-1]["factor"] if chunk else None,
            "mean_d": _mean([r[d_key] for r in chunk]),
            "base_rate": _mean([r[f"y{event}"] for r in chunk]),
            "mean_p_without": _mean([r[f"p{event}_without"] for r in chunk]),
            "mean_p_with": _mean([r[f"p{event}_with"] for r in chunk]),
        })
    return out


def summarise_season(rows: Sequence[Mapping]) -> dict:
    """Everything the artifact reports for one season, from scored rows."""
    known = [r for r in rows if r["starter_known"]]
    lineup = [r for r in rows if r["slot"] is not None]
    return {
        "all_rows": {"primary_2plus_tb": event_summary(rows, "2"),
                     "secondary_1plus_tb": event_summary(rows, "1")},
        "starter_known_subset": {"primary_2plus_tb": event_summary(known, "2"),
                                 "secondary_1plus_tb": event_summary(known, "1")},
        "in_posted_lineup_subset_descriptive": {
            "primary_2plus_tb": event_summary(lineup, "2")},
        "factor_distribution": factor_distribution(rows),
        "terciles": {"primary_2plus_tb": tercile_table(rows, "2"),
                     "secondary_1plus_tb": tercile_table(rows, "1")},
        "reliability": {
            event_name: {arm: reliability_table(rows, ev, arm) for arm in
                         ("without", "with")}
            for event_name, ev in (("primary_2plus_tb", "2"),
                                   ("secondary_1plus_tb", "1"))} if rows else {},
        "per_date_primary": [[d, t, n] for d, t, n in
                             per_date_aggregates(rows, "d2")],
        "per_date_secondary": [[d, t, n] for d, t, n in
                               per_date_aggregates(rows, "d1")],
    }
