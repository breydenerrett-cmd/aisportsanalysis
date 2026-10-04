"""Does a pitcher-specific strikeout distribution beat a league-rate baseline?

Pure functions for ONE bounded, pre-registered paper comparison
(`docs/PREREG_K_BASELINE.md`). Nothing here reads a file, a clock or a network;
`scripts/k_baseline_compare.py` does the I/O and hands rows in.

THE QUESTION
------------
The product prices starting-pitcher strikeouts nowhere and has no model for
them. Before anyone builds one, this asks the smallest honest question: on a
starter's strikeout COUNT, out of sample, does his own history beat knowing
only the league?

    BASELINE   every start gets the league strikeout distribution, built from
               earlier starts only (`league_pool`).
    CANDIDATE  the pitcher's own strikeouts per batter faced, shrunk toward the
               league rate with a fixed prior weight (PRIOR_WEIGHT_BF), times
               his expected batters faced, shrunk toward the league mean with a
               fixed prior weight (PRIOR_WEIGHT_STARTS); strikeouts are Poisson
               with that mean.

Both are scored on P(strikeouts > line) at 3.5, 4.5, 5.5 and 6.5, and on the
absolute error of expected strikeouts. No price is involved anywhere: there is
no historical strikeout price before 2026, and 2026 inputs before 2026-08-28
are sealed.

WHY POISSON, NOT BINOMIAL (stated before any outcome was read)
--------------------------------------------------------------
A binomial with a point estimate of batters faced assumes every start faces
exactly that many batters. Batters faced varies a lot from start to start (a
quick hook, a long outing), and a mixture of binomials over a varying number of
trials is OVERdispersed relative to a single binomial. Poisson has variance
equal to its mean, which is wider than binomial(n, p) at p near 0.22, so it is
the closer of the two to the true spread. It also needs no integer rounding of
the expected batters faced, so the model's mean equals rate x batters faced
exactly and the mean absolute error of expected strikeouts is not distorted by
a rounding step. This is a reason of principle, fixed in advance; neither
distribution was fitted to anything.

SIGN CONVENTION, STATED ONCE
----------------------------
    d = loss(BASELINE) - loss(CANDIDATE)        per start, log loss in nats
    d_mae = |K - E_baseline| - |K - E_candidate|

POSITIVE means the pitcher-specific candidate predicted better. An interval
for the mean of d that lies entirely above zero is evidence FOR the candidate;
entirely below zero is evidence AGAINST it.

POINT-IN-TIME, BY CONSTRUCTION
------------------------------
* Everything that enters a prediction for a start on date D has a date STRICTLY
  BEFORE D: the league pool, the pitcher's own starts, the prior season's pool.
  Starts are walked in date order and a date's starts join the history only
  AFTER every start of that date has been predicted, so a doubleheader never
  feeds itself.
* The pitcher's own history is the SAME season only. The league pool is the
  same season's earlier starts once MIN_LEAGUE_STARTS exist, else the whole
  prior season when that season is inside the window, else the start is
  excluded (both arms).
* Every date that enters is refused unless it is inside 2023-01-01..2024-12-31,
  and a run for one season never reads another season's rows except the single
  prior season, as a pool, when it is allowed. 2025 is tuning-only and 2026 is
  sealed; the guard is structural, a raised `SealedDataError`.

Pure. stdlib only.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Evidence window. Mirrors `src/research/matrix.ALLOWED_SEASONS` (a test pins
# the equality) without importing the matrix module's dependency tree.
# ---------------------------------------------------------------------------

ALLOWED_SEASONS = (2023, 2024)
WINDOW_START = "2023-01-01"
WINDOW_END = "2024-12-31"

MARKET = "pitcher_strikeouts"
LINES = (3.5, 4.5, 5.5, 6.5)
DECISIVE_LINES = (4.5, 5.5)

# The two fixed prior weights and the two fixed eligibility numbers. Nothing
# tunes them; changing one is a new registration.
PRIOR_WEIGHT_BF = 70.0      # batters faced of league-rate evidence in the K rate
PRIOR_WEIGHT_STARTS = 3.0   # starts of league-mean evidence in expected BF
MIN_LEAGUE_STARTS = 500     # earlier same-season league starts before the pool is used
MIN_PRIOR_STARTS = 1        # a pitcher needs this many earlier same-season starts
SHORT_START_BF = 12         # descriptive only: a start with this few batters or fewer
EXPERIENCED_STARTS = 5      # descriptive subset only

EPS = 1e-6

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261004
CI_LOW_QUANTILE = 0.025
CI_HIGH_QUANTILE = 0.975


class SealedDataError(ValueError):
    """A date or season outside the evidence window reached code that must refuse it."""


class KBaselineError(ValueError):
    """The inputs cannot be compared honestly."""


def line_key(line: float) -> str:
    return f"{float(line):.1f}"


def over_threshold(line: float) -> int:
    """Smallest strikeout count that is OVER a half-point line (4.5 -> 5)."""
    return int(math.floor(float(line))) + 1


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def in_window(date) -> bool:
    """True for an ISO date string inside the evidence window. Total, never raises."""
    if not isinstance(date, str) or len(date) < 10:
        return False
    head = date[:10]
    if not (head[4] == "-" and head[7] == "-"
            and head[:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit()):
        return False
    return WINDOW_START <= head <= WINDOW_END


def assert_allowed_date(date) -> str:
    """Return the ISO date, or raise `SealedDataError`. A hard error."""
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


def paired_difference(p_baseline: float, p_candidate: float, y: int) -> float:
    """loss(BASELINE) - loss(CANDIDATE). Positive means the candidate was better."""
    return log_loss_one(p_baseline, y) - log_loss_one(p_candidate, y)


def paired_abs_error(e_baseline: float, e_candidate: float, k: int) -> float:
    """|K - E_baseline| - |K - E_candidate|. Positive means the candidate was closer."""
    return abs(k - e_baseline) - abs(k - e_candidate)


# ---------------------------------------------------------------------------
# Clustered bootstrap (same algorithm as tb_starter / model.discovery)
# ---------------------------------------------------------------------------

def per_date_aggregates(rows: Iterable[Mapping], value_key: str) -> list:
    """[(date, sum_of_value, n)] sorted ascending by date."""
    acc: dict = {}
    for row in rows:
        total, n = acc.get(row["date"], (0.0, 0))
        acc[row["date"]] = (total + row[value_key], n + 1)
    return [(date, total, n) for date, (total, n) in sorted(acc.items())]


def clustered_mean_interval(aggregates: Sequence, *,
                            resamples: int = BOOTSTRAP_RESAMPLES,
                            seed: int = BOOTSTRAP_SEED) -> dict:
    """95% percentile interval of the mean, resampling DATES with replacement.

    Same algorithm, index arithmetic and percentile rule as
    `src.model.discovery.clustered_bootstrap`; a test pins the two to the same
    numbers. Seeded and deterministic. `aggregates` is `per_date_aggregates`
    output. `se` is the bootstrap half-width over 1.96.
    """
    clusters = [(total, n) for _date, total, n in sorted(aggregates)]
    total_n = sum(n for _t, n in clusters)
    if len(clusters) < 2 or total_n < 1:
        return {"estimate": None, "low": None, "high": None, "se": None,
                "resamples": 0, "clusters": len(clusters), "n": total_n,
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
    low = draws[int(CI_LOW_QUANTILE * len(draws))]
    high = draws[min(len(draws) - 1, int(CI_HIGH_QUANTILE * len(draws)))]
    return {"estimate": estimate, "low": low, "high": high,
            "se": (high - low) / (2 * 1.96),
            "resamples": len(draws), "clusters": g, "n": total_n, "reason": None}


# ---------------------------------------------------------------------------
# Registered decision rule
# ---------------------------------------------------------------------------

SUPPORTED = "SUPPORTED"
WORSE = "WORSE"
NOT_SUPPORTED = "NOT_SUPPORTED"


def _usable(block) -> bool:
    return (block is not None and block.get("estimate") is not None
            and block.get("low") is not None and block.get("high") is not None)


def decide(first_look: Optional[Mapping], confirming: Optional[Mapping]) -> dict:
    """The registered rule, applied literally.

    `first_look` is {line_key: 2023 interval dict}, `confirming` is
    {line_key: 2024 interval dict}; each interval is from
    `clustered_mean_interval` and the quantity is mean(d).

    SUPPORTED       on BOTH decisive lines (4.5 and 5.5): the 2024 interval lies
                    entirely above zero AND the 2023 point estimate is positive.
    WORSE           on BOTH decisive lines the 2024 interval lies entirely
                    below zero.
    NOT_SUPPORTED   anything else, including any missing input and any split
                    between the two lines.

    A 2023 point estimate of exactly zero is not "the same sign". The lines
    3.5 and 6.5 are published and cannot change the verdict. Nothing here is
    parameterised: there is no threshold to move.
    """
    first_look, confirming = first_look or {}, confirming or {}
    keys = [line_key(line) for line in DECISIVE_LINES]
    for key in keys:
        if not _usable(first_look.get(key)) or not _usable(confirming.get(key)):
            return {"verdict": NOT_SUPPORTED,
                    "reason": f"an interval is missing for the {key} line"}
    if all(confirming[k]["high"] < 0 for k in keys):
        return {"verdict": WORSE,
                "reason": "the 2024 interval lies entirely below zero on both "
                          "the 4.5 and 5.5 lines"}
    if all(confirming[k]["low"] > 0 and first_look[k]["estimate"] > 0
           for k in keys):
        return {"verdict": SUPPORTED,
                "reason": "on both the 4.5 and 5.5 lines the 2024 interval lies "
                          "entirely above zero and the 2023 point estimate is "
                          "positive"}
    detail = []
    for k in keys:
        c, f = confirming[k], first_look[k]
        if c["low"] > 0:
            detail.append(f"{k}: 2024 above zero"
                          + ("" if f["estimate"] > 0 else
                             " but the 2023 point estimate is not positive"))
        elif c["high"] < 0:
            detail.append(f"{k}: 2024 entirely below zero")
        else:
            detail.append(f"{k}: the 2024 interval includes zero")
    return {"verdict": NOT_SUPPORTED, "reason": "; ".join(detail)}


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------

def poisson_over(mean: float, line: float) -> float:
    """P(K > line) for K ~ Poisson(mean), at a half-point line."""
    if mean < 0 or not math.isfinite(mean):
        raise KBaselineError(f"Poisson mean {mean!r} is not a finite non-negative number")
    need = over_threshold(line)
    if mean == 0:
        return 0.0
    term = math.exp(-mean)
    cdf = term
    for j in range(1, need):
        term *= mean / j
        cdf += term
    return max(0.0, 1.0 - cdf)


class LeaguePool:
    """Strikeout counts, strikeouts and batters faced over a set of starts."""

    def __init__(self):
        self.counts: dict = {}
        self.starts = 0
        self.k = 0
        self.bf = 0

    def add(self, k: int, bf: int) -> None:
        self.counts[k] = self.counts.get(k, 0) + 1
        self.starts += 1
        self.k += k
        self.bf += bf

    def mean_k(self) -> Optional[float]:
        return self.k / self.starts if self.starts else None

    def k_per_bf(self) -> Optional[float]:
        return self.k / self.bf if self.bf else None

    def mean_bf(self) -> Optional[float]:
        return self.bf / self.starts if self.starts else None

    def over(self, line: float) -> Optional[float]:
        """Empirical share of starts with strictly more than `line` strikeouts."""
        if not self.starts:
            return None
        need = over_threshold(line)
        return sum(c for k, c in self.counts.items() if k >= need) / self.starts


# ---------------------------------------------------------------------------
# The two models
# ---------------------------------------------------------------------------

def baseline_prediction(pool: LeaguePool) -> dict:
    """Every start gets the league distribution. Needs only the pool."""
    return {"expected": pool.mean_k(),
            "over": {line_key(L): pool.over(L) for L in LINES}}


def shrunk_k_rate(pitcher_k: int, pitcher_bf: int, league_rate: float,
                  prior_weight: float = PRIOR_WEIGHT_BF) -> float:
    """(K + w * league_rate) / (BF + w): the pitcher's own K per batter faced,
    shrunk toward the league rate with a fixed weight in batters faced."""
    return (pitcher_k + prior_weight * league_rate) / (pitcher_bf + prior_weight)


def shrunk_batters_faced(pitcher_bf_total: int, pitcher_starts: int,
                         league_mean_bf: float,
                         prior_weight: float = PRIOR_WEIGHT_STARTS) -> float:
    """(sum BF + m * league_mean_bf) / (starts + m): expected batters faced,
    shrunk toward the league mean with a fixed weight in starts."""
    return (pitcher_bf_total + prior_weight * league_mean_bf) / (pitcher_starts + prior_weight)


def candidate_prediction(pool: LeaguePool, history: tuple) -> dict:
    """The pitcher-specific model. `history` is (starts, k, bf) over his own
    earlier same-season starts; the league figures come from the SAME pool the
    baseline uses, so the arms share every league input."""
    starts, k, bf = history
    rate = shrunk_k_rate(k, bf, pool.k_per_bf())
    expected_bf = shrunk_batters_faced(bf, starts, pool.mean_bf())
    mean = rate * expected_bf
    return {"expected": mean, "k_rate": rate, "expected_bf": expected_bf,
            "over": {line_key(L): poisson_over(mean, L) for L in LINES}}


# ---------------------------------------------------------------------------
# Starts
# ---------------------------------------------------------------------------

def extract_starts(rows: Iterable[Mapping]) -> dict:
    """({"starts": [...], "counts": {...}}) from pitcher-log rows.

    Rows outside the window are dropped the moment they are seen: not kept, not
    counted, not aggregated. A START is a row with `games_started == 1`; every
    other in-window appearance is a relief outing and is not used anywhere (not
    as a target, not as history). A start is NOT dropped for being short: a
    one-inning opener with `games_started == 1` is a start, scored in both
    arms; `short_starts` merely counts them.

    A (person, date) with more than one start row is ambiguous and ALL its
    rows are dropped (target and history alike), counted. A start with a
    missing, negative or impossible (K > batters faced) figure is excluded and
    does not feed any history, counted.
    """
    counts = {"in_window_rows": 0, "relief_appearances": 0,
              "games_started_other_value": 0, "duplicate_person_date": 0,
              "missing_or_invalid_k_bf": 0, "starts": 0}
    staged: dict = {}
    for row in rows:
        date = row.get("date")
        if not in_window(date if isinstance(date, str) else None):
            continue
        counts["in_window_rows"] += 1
        gs = row.get("games_started")
        if gs == 0:
            counts["relief_appearances"] += 1
            continue
        if gs != 1 or isinstance(gs, bool):
            counts["games_started_other_value"] += 1
            continue
        staged.setdefault((int(row["person_id"]), str(date)[:10]), []).append(row)
    starts = []
    for (pid, date), group in staged.items():
        if len(group) > 1:
            counts["duplicate_person_date"] += len(group)
            continue
        row = group[0]
        k, bf = row.get("strikeouts"), row.get("batters_faced")
        if (k is None or bf is None or isinstance(k, bool) or isinstance(bf, bool)
                or int(k) != k or int(bf) != bf or k < 0 or bf < 0 or k > bf):
            counts["missing_or_invalid_k_bf"] += 1
            continue
        starts.append({"person_id": pid, "date": date, "k": int(k), "bf": int(bf)})
    starts.sort(key=lambda s: (s["date"], s["person_id"]))
    counts["starts"] = len(starts)
    return {"starts": starts, "counts": counts}


def build_comparison_rows(*, season, starts: Sequence[Mapping],
                          min_league_starts: int = MIN_LEAGUE_STARTS,
                          min_prior_starts: int = MIN_PRIOR_STARTS,
                          limit: Optional[int] = None) -> dict:
    """Score every eligible start of one season under both models.

    `starts` is `extract_starts(...)["starts"]` and may hold other seasons'
    starts; only `season` (targets) and, for the pool fallback, the one prior
    season when it is inside the window are read. Rows of any other year are
    ignored and never touched.

    Returns {"rows": [...], "counts": {...}}. ONE ROW PER START. A start
    excluded for lack of a league pool or of a prior start is excluded from
    BOTH models by construction, because both are computed in the one row.
    `limit` caps scored rows, for a slice only.
    """
    season = assert_allowed_season(season)
    prior_season = season - 1
    use_prior = prior_season in ALLOWED_SEASONS

    pool_prev = LeaguePool()
    by_date: dict = {}
    for s in starts:
        date = assert_allowed_date(s["date"])
        year = int(date[:4])
        if year == season:
            by_date.setdefault(date, []).append(s)
        elif use_prior and year == prior_season:
            pool_prev.add(s["k"], s["bf"])
        # any other in-window year is never read

    counts = {
        "starts_in_season": sum(len(v) for v in by_date.values()),
        "prior_season_pool_starts": pool_prev.starts if use_prior else 0,
        "excluded_no_league_pool": 0,
        "excluded_no_prior_start": 0,
        "scored": 0, "scored_pool_same_season": 0, "scored_pool_prior_season": 0,
        "short_starts_scored": 0,
    }
    pool = LeaguePool()
    history: dict = {}      # person_id -> [starts, k, bf], same season, strictly earlier
    out = []
    for date in sorted(by_date):
        assert_allowed_date(date)
        if pool.starts >= min_league_starts:
            active, source = pool, "same_season"
        elif use_prior and pool_prev.starts >= min_league_starts:
            active, source = pool_prev, "prior_season"
        else:
            active, source = None, None
        group = sorted(by_date[date], key=lambda s: s["person_id"])
        for s in group:
            if limit is not None and counts["scored"] >= limit:
                break
            if active is None:
                counts["excluded_no_league_pool"] += 1
                continue
            h = history.get(s["person_id"])
            if h is None or h[0] < min_prior_starts:
                counts["excluded_no_prior_start"] += 1
                continue
            base = baseline_prediction(active)
            cand = candidate_prediction(active, tuple(h))
            k = s["k"]
            row = {"date": date, "person_id": s["person_id"], "k": k,
                   "bf": s["bf"], "prior_starts": h[0], "pool": source,
                   "short_start": s["bf"] <= SHORT_START_BF,
                   "e_base": base["expected"], "e_cand": cand["expected"],
                   "k_rate": cand["k_rate"], "expected_bf": cand["expected_bf"],
                   "d_mae": paired_abs_error(base["expected"], cand["expected"], k)}
            for L in LINES:
                key = line_key(L)
                y = int(k >= over_threshold(L))
                row[f"y_{key}"] = y
                row[f"p_base_{key}"] = base["over"][key]
                row[f"p_cand_{key}"] = cand["over"][key]
                row[f"d_{key}"] = paired_difference(
                    base["over"][key], cand["over"][key], y)
            out.append(row)
            counts["scored"] += 1
            counts["scored_pool_same_season" if source == "same_season"
                   else "scored_pool_prior_season"] += 1
            if row["short_start"]:
                counts["short_starts_scored"] += 1
        if limit is not None and counts["scored"] >= limit:
            break
        # Only now does this date become history: every start that happened,
        # scored or not, in either model.
        for s in by_date[date]:
            pool.add(s["k"], s["bf"])
            h = history.setdefault(s["person_id"], [0, 0, 0])
            h[0] += 1
            h[1] += s["k"]
            h[2] += s["bf"]
    return {"rows": out, "counts": counts}


# ---------------------------------------------------------------------------
# Summaries (the numbers the result document reports)
# ---------------------------------------------------------------------------

def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def line_summary(rows: Sequence[Mapping], line: float) -> dict:
    key = line_key(line)
    n = len(rows)
    out = {"line": float(line), "n": n}
    if not n:
        return out
    y, pb, pc = f"y_{key}", f"p_base_{key}", f"p_cand_{key}"
    out["base_rate"] = _mean([r[y] for r in rows])
    out["mean_p_baseline"] = _mean([r[pb] for r in rows])
    out["mean_p_candidate"] = _mean([r[pc] for r in rows])
    out["log_loss_baseline"] = _mean([log_loss_one(r[pb], r[y]) for r in rows])
    out["log_loss_candidate"] = _mean([log_loss_one(r[pc], r[y]) for r in rows])
    out["brier_baseline"] = _mean([brier_one(r[pb], r[y]) for r in rows])
    out["brier_candidate"] = _mean([brier_one(r[pc], r[y]) for r in rows])
    paired = clustered_mean_interval(per_date_aggregates(rows, f"d_{key}"))
    paired["minimum_detectable_effect_80pct"] = (
        None if paired["se"] is None else 2.8 * paired["se"])
    out["paired"] = paired
    return out


def mae_summary(rows: Sequence[Mapping]) -> dict:
    n = len(rows)
    out = {"n": n}
    if not n:
        return out
    out["mean_k"] = _mean([r["k"] for r in rows])
    out["mean_expected_baseline"] = _mean([r["e_base"] for r in rows])
    out["mean_expected_candidate"] = _mean([r["e_cand"] for r in rows])
    out["mae_baseline"] = _mean([abs(r["k"] - r["e_base"]) for r in rows])
    out["mae_candidate"] = _mean([abs(r["k"] - r["e_cand"]) for r in rows])
    paired = clustered_mean_interval(per_date_aggregates(rows, "d_mae"))
    paired["minimum_detectable_effect_80pct"] = (
        None if paired["se"] is None else 2.8 * paired["se"])
    out["paired"] = paired
    return out


def reliability_table(rows: Sequence[Mapping], line: float, arm: str,
                      bins: int = 10) -> list:
    """Equal-width reliability table through the repo's own calibration code."""
    from src.core import calibration
    key = line_key(line)
    curve = calibration.reliability_curve(
        [r[f"p_{arm}_{key}"] for r in rows], [r[f"y_{key}"] for r in rows],
        bins=bins)
    return [{"lower": b["lower"], "upper": b["upper"], "count": b["count"],
             "mean_predicted": b["mean_predicted"],
             "observed_rate": b["observed_rate"], "gap": b["gap"]}
            for b in curve]


def _block(rows: Sequence[Mapping]) -> dict:
    return {"lines": {line_key(L): line_summary(rows, L) for L in LINES},
            "expected_strikeouts_mae": mae_summary(rows)}


def summarise_season(rows: Sequence[Mapping]) -> dict:
    """Everything the artifact reports for one season, from scored rows."""
    experienced = [r for r in rows if r["prior_starts"] >= EXPERIENCED_STARTS]
    no_short = [r for r in rows if not r["short_start"]]
    return {
        "all_scored": _block(rows),
        "experienced_pitchers_descriptive": _block(experienced),
        "excluding_short_starts_descriptive": _block(no_short),
        "reliability": {
            line_key(L): {arm: reliability_table(rows, L, arm)
                          for arm in ("base", "cand")} for L in LINES
        } if rows else {},
        "per_date": {line_key(L): [[d, t, n] for d, t, n in
                                   per_date_aggregates(rows, f"d_{line_key(L)}")]
                     for L in LINES},
        "per_date_mae": [[d, t, n] for d, t, n in per_date_aggregates(rows, "d_mae")],
    }
