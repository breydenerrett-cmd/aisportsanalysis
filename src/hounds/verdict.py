"""The referee: "good or lucky", decided mechanically.

Every threshold and rule here is quoted from ``docs/PREREG_HOUND_VERDICT.md``,
which was committed before this file existed and before any hound's closing
line value had been computed. Do not tune a constant to move a hound's label;
a change is a new dated section in that file first.

WHAT THE LABEL READS, AND WHAT IT NEVER READS
----------------------------------------------
The label reads one thing: the mean closing-line value of a hound's FORWARD,
measurable bets, with a date-clustered bootstrap interval. It never reads
units, win rate, streaks or a replay result. A hound that is up 40 units and
below the closing price is PAYING THE VIG, and the sentence says so.

The bootstrap is ``src.model.discovery.clustered_bootstrap`` re-expressed over
per-date ``(sum, count)`` pairs. Same RNG, same sorted dates, same percentile
indices, so the answer is the same to the 5th decimal (a test pins it against
the original); the re-expression exists because the retirement walk asks the
question once per settled day and a per-bet list copy per resample is the
difference between milliseconds and minutes.
"""

from __future__ import annotations

import random
from datetime import date as date_cls
from typing import Iterable, NamedTuple, Optional

# ---- Pre-registered constants (docs/PREREG_HOUND_VERDICT.md sections 2-5) ----

MIN_MEASURABLE_BETS = 150          # section 3: below this the label is TOO EARLY
BOOTSTRAP_RESAMPLES = 2000         # section 2
BOOTSTRAP_SEED = 20260828          # section 2 (src.model.discovery.BOOTSTRAP_SEED)
UNITS_SAY_NOTHING_BELOW = 1000     # section 4
RETIRE_UNITS_BELOW = -25.0         # section 5(1): more than 25 units below zero
RETIRE_CLV_MIN_BETS = 300          # section 5(2)
BENCH_AFTER_DAYS = 7               # section 5: no bets in 7 days
VERIFIED_SHARE_OF_CHECKABLE = 0.95  # section 6
CHECKABLE_SHARE_OF_BETS = 0.90      # section 6
AVERAGE_PRICE_COVERAGE = 0.90       # section 4: below this units_average is null
CLV_SERIES_MIN_BETS = 20           # coordinator's series contract: null below 20

TOO_EARLY = "TOO EARLY"
BEATING_THE_CLOSE = "BEATING THE CLOSE"
PAYING_THE_VIG = "PAYING THE VIG"
NO_DIFFERENT = "NO DIFFERENT FROM THE MARKET"
NOT_MEASURED = "NOT MEASURED"
LABELS = (TOO_EARLY, BEATING_THE_CLOSE, PAYING_THE_VIG, NO_DIFFERENT, NOT_MEASURED)

# Order used when a board needs a stable, NON-UNITS ordering: the hounds the
# referee can say something about first, the ones it cannot after.
LABEL_RANK = {BEATING_THE_CLOSE: 0, NO_DIFFERENT: 1, PAYING_THE_VIG: 2,
              TOO_EARLY: 3, NOT_MEASURED: 4}

STATUS_RUNNING = "running"
STATUS_BENCHED = "benched"
STATUS_RETIRED = "retired"

CAUSE_UNITS = "retired: down more than 25 units"
CAUSE_CLV = "retired: closing price verdict PAYING THE VIG at 300+ bets"


class Verdict(NamedTuple):
    label: str
    sentence: str
    n: int
    mean_pts: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]


def _day(value) -> str:
    return str(value)[:10]


def per_date_sums(points: Iterable) -> dict:
    """``{date: [sum, count]}`` from ``(date, clv_pts)`` pairs."""
    out: dict = {}
    for when, value in points:
        cell = out.setdefault(_day(when), [0.0, 0])
        cell[0] += float(value)
        cell[1] += 1
    return out


def clustered_ci(sums: dict, resamples: int = BOOTSTRAP_RESAMPLES,
                 seed: int = BOOTSTRAP_SEED) -> Optional[tuple]:
    """``(low, high)`` 95% interval of the mean, resampling whole dates.

    ``sums`` is ``per_date_sums`` output. None when fewer than two distinct
    dates exist (no interval is better than a fake one). Mirrors
    ``src.model.discovery.clustered_bootstrap`` exactly: sorted dates, one
    ``random.Random(seed)``, ``len(dates)`` draws per resample, percentile
    indices ``int(0.025*k)`` and ``min(k-1, int(0.975*k))``.
    """
    dates = sorted(sums)
    if len(dates) < 2:
        return None
    cells = [sums[d] for d in dates]
    k_dates = len(cells)
    rng = random.Random(seed)
    randrange = rng.randrange
    draws = []
    for _ in range(resamples):
        total = 0.0
        count = 0
        for _ in range(k_dates):
            cell = cells[randrange(k_dates)]
            total += cell[0]
            count += cell[1]
        if count:
            draws.append(total / count)
    if not draws:
        return None
    draws.sort()
    k = len(draws)
    return (round(draws[int(0.025 * k)], 5),
            round(draws[min(k - 1, int(0.975 * k))], 5))


def verdict_from_sums(sums: dict) -> Verdict:
    """The label for a hound whose measurable forward bets sum to ``sums``."""
    n = sum(cell[1] for cell in sums.values())
    if n == 0:
        return Verdict(TOO_EARLY, _too_early_sentence(0), 0, None, None, None)
    mean = sum(cell[0] for cell in sums.values()) / n
    if n < MIN_MEASURABLE_BETS:
        return Verdict(TOO_EARLY, _too_early_sentence(n), n, round(mean, 4),
                       None, None)
    ci = clustered_ci(sums)
    if ci is None:
        return Verdict(TOO_EARLY, _too_early_sentence(n), n, round(mean, 4),
                       None, None)
    low, high = ci
    if low > 0:
        label = BEATING_THE_CLOSE
        sentence = (f"The price it took beat the closing market by "
                    f"{mean:.2f} points on average (95% interval {low:.2f} "
                    f"to {high:.2f}) over {n} bets.")
    elif high < 0:
        label = PAYING_THE_VIG
        sentence = (f"The price it took was worse than the closing market by "
                    f"{abs(mean):.2f} points on average (95% interval "
                    f"{low:.2f} to {high:.2f}) over {n} bets.")
    else:
        label = NO_DIFFERENT
        sentence = (f"Over {n} bets its price was {mean:+.2f} points from the "
                    f"closing market on average (95% interval {low:.2f} to "
                    f"{high:.2f}); that cannot be told apart from zero.")
    return Verdict(label, sentence, n, round(mean, 4), low, high)


def verdict_for(points: Iterable) -> Verdict:
    """``verdict_from_sums(per_date_sums(points))`` for ``(date, pts)`` pairs."""
    return verdict_from_sums(per_date_sums(points))


def not_measured_verdict(reason: str) -> Verdict:
    return Verdict(NOT_MEASURED, reason, 0, None, None, None)


def _too_early_sentence(n: int) -> str:
    return (f"Only {n} of its bets have a measurable closing price. At least "
            f"{MIN_MEASURABLE_BETS} are needed before this means anything.")


def units_note(graded_bets: int) -> str:
    """The separate, always-shown line about units (prereg section 4)."""
    if graded_bets < UNITS_SAY_NOTHING_BELOW:
        return ("Win/loss units over fewer than 1,000 bets say nothing about "
                "skill. At one unit a bet, ordinary luck alone moves a "
                "1,000-bet total by about 32 units either way.")
    return ("Win/loss units are shown for the record. They never change the "
            "label above.")


# ---- Status ------------------------------------------------------------------

def days_between(later: str, earlier: str) -> int:
    return (date_cls.fromisoformat(_day(later))
            - date_cls.fromisoformat(_day(earlier))).days


def status_for(last_bet_day: Optional[str], as_of_day: Optional[str],
               retired: bool = False) -> str:
    """retired > benched (no bet in 7 days of the data's own as-of) > running.

    ``as_of_day`` is the newest decision date in the data, never the wall
    clock, so the answer is a function of the ledgers (prereg section 5).
    """
    if retired:
        return STATUS_RETIRED
    if not last_bet_day or not as_of_day:
        return STATUS_BENCHED
    return (STATUS_BENCHED if days_between(as_of_day, last_bet_day) > BENCH_AFTER_DAYS
            else STATUS_RUNNING)


def find_retirement(days: list, clv_points: list) -> Optional[tuple]:
    """``(date, cause)`` of the FIRST settled day a retirement condition held.

    ``days``: ``[(day, cumulative_units_for_the_rule), ...]`` ascending, forward
    bets only. ``clv_points``: ``[(decision_day, clv_pts), ...]`` measurable
    forward bets. Walks the days in order using only data up to each day, so a
    later result can never un-retire a hound (the ledgers are append-only).
    Condition 1 is checked before condition 2 on the same day.
    """
    by_day = {}
    for when, value in sorted(clv_points, key=lambda p: _day(p[0])):
        by_day.setdefault(_day(when), []).append((when, value))
    day_keys = sorted(by_day)
    sums: dict = {}
    n_cum = 0
    idx = 0
    for day, cum_units in days:
        day = _day(day)
        while idx < len(day_keys) and day_keys[idx] <= day:
            for when, value in by_day[day_keys[idx]]:
                cell = sums.setdefault(_day(when), [0.0, 0])
                cell[0] += float(value)
                cell[1] += 1
                n_cum += 1
            idx += 1
        if cum_units is not None and cum_units < RETIRE_UNITS_BELOW:
            return day, CAUSE_UNITS
        if n_cum >= RETIRE_CLV_MIN_BETS:
            if verdict_from_sums(sums).label == PAYING_THE_VIG:
                return day, CAUSE_CLV
    return None
