"""M2 -- is the latest price always the sharpest one?

THE QUESTION
------------
The whole system assumes later is better: the closing line is the benchmark,
and beating it is the evidence that a bet was good. That assumption is load
bearing, and it has never been checked on our own data.

The Management Science study of 3,681 MLB games found it is not universally
true. Forecast quality does not improve monotonically toward first pitch, and
specifically, prices at the start of WEEKEND DAY games forecast worse than
prices ninety minutes earlier. Late movement on those slates is noise, and the
earlier quote is the better estimate.

WHY IT MATTERS EVEN IF THERE IS NO BET IN IT
--------------------------------------------
If the T-90 price is sharper than the T-0 price on some slates, then every
closing-line-value number the system computes on those slates is measured
against the wrong yardstick. A strategy could be "beating the close" on weekend
afternoons purely by beating a worse forecast. Getting this right is a
prerequisite for trusting M1 and M3, which is why it runs before them.

WHAT IS MEASURED
----------------
For each event, the consensus de-vigged home probability at two moments -- the
latest snapshot at least 90 minutes out, and the latest snapshot before first
pitch -- scored by log loss against the result, split by day of week and by
whether the game starts in the afternoon. If the effect is real, the T-90 price
wins on weekend afternoons and loses everywhere else.

THE HONEST LIMIT
----------------
Our snapshot grid is a handful of quotes per game, not the tick-level history
the paper used. The "T-90" quote is the latest one at least 90 minutes out,
which on a sparse game might be five hours out. Every cell reports its actual
median gap so a difference driven by staleness rather than by timing is
visible rather than hidden.
"""

from __future__ import annotations

import math

from src.data import parks
from src.research import m5_devig
from src.research import pricepath

EARLY_LEAD_MINUTES = 90

# Local first pitch before this hour counts as a day game. 17:00 splits the
# populations cleanly: MLB afternoon games start 12:00-16:10 and night games
# 18:00 onward, so nothing lands near the boundary.
DAY_GAME_BEFORE_HOUR = 17

# Approximate UTC offset from longitude, plus one hour because the regular
# season runs entirely inside daylight saving time. Good to well under an hour
# for every US park, which is all a day/night split needs. It is not accurate
# enough to timestamp anything, and is used for nothing else.
def _local_hour(commence_time, home_team) -> float:
    try:
        _, lon = parks.coordinates(home_team)
    except parks.ParkError:
        return None
    offset = lon / 15.0 + 1.0
    return (commence_time.hour + commence_time.minute / 60.0 + offset) % 24


def _log_loss(probability, outcome):
    p = min(max(probability, 1e-6), 1 - 1e-6)
    return -(math.log(p) if outcome else math.log(1 - p))


def rows(paths, method="proportional", early_lead=EARLY_LEAD_MINUTES,
         max_early_gap=None, max_late_gap=None) -> list:
    """One row per event carrying both prices, or nothing.

    A row needs BOTH quotes to exist and to be genuinely different snapshots.
    When a game's last quote is already more than ninety minutes out, the two
    prices are the same number and comparing them would contribute a guaranteed
    tie that dilutes whatever real effect exists.
    """
    out = []
    for path in paths:
        early = pricepath.quote_at(path, early_lead)
        late = pricepath.latest_quote(path)
        if early is None or late is None:
            continue
        if early[0] == late[0]:
            continue
        # The strict variant of the test. Without these, "the price 90 minutes
        # out" is really "the latest price at least 90 minutes out", which on a
        # sparsely sampled game is sixteen hours out -- a different question
        # with a different and obvious answer.
        if max_early_gap is not None and early[1][0]["gap_minutes"] > max_early_gap:
            continue
        if max_late_gap is not None and late[1][0]["gap_minutes"] > max_late_gap:
            continue
        early_p = m5_devig.consensus(early[1], method)
        late_p = m5_devig.consensus(late[1], method)
        if early_p is None or late_p is None:
            continue
        local = _local_hour(path["commence_time"], path["home_team"])
        if local is None:
            continue
        weekday = path["commence_time"].weekday()
        out.append({
            "event_id": path["event_id"],
            "date": path["date"],
            "home_won": path["home_won"],
            "early_probability": early_p,
            "late_probability": late_p,
            "early_gap_minutes": early[1][0]["gap_minutes"],
            "late_gap_minutes": late[1][0]["gap_minutes"],
            "local_hour": local,
            "is_day_game": local < DAY_GAME_BEFORE_HOUR,
            # Saturday/Sunday in LOCAL terms. A UTC weekday would call a Friday
            # night game Saturday and put it in the wrong cell.
            "is_weekend": ((weekday if commence_is_same_local_day(path, local)
                            else (weekday - 1) % 7) in (5, 6)),
        })
    return out


def commence_is_same_local_day(path, local_hour) -> bool:
    """Whether the local date matches the UTC date.

    A 19:00 local night game is 02:00 UTC the next day, so its UTC weekday is
    one ahead of its real one. Comparing the UTC hour against the local hour
    detects the rollover without needing a timezone database.
    """
    return path["commence_time"].hour >= local_hour


def _cell_score(subset) -> dict:
    early = [_log_loss(r["early_probability"], r["home_won"]) for r in subset]
    late = [_log_loss(r["late_probability"], r["home_won"]) for r in subset]
    early_mean = sum(early) / len(early)
    late_mean = sum(late) / len(late)
    gaps = sorted(r["early_gap_minutes"] for r in subset)
    return {
        "n": len(subset),
        "early_log_loss": early_mean,
        "late_log_loss": late_mean,
        # Positive means the EARLY price forecast better -- the paper's claim.
        "early_advantage": late_mean - early_mean,
        "median_early_gap_minutes": gaps[len(gaps) // 2],
        "median_late_gap_minutes": sorted(
            r["late_gap_minutes"] for r in subset)[len(subset) // 2],
        "mean_price_move": sum(
            abs(r["late_probability"] - r["early_probability"]) for r in subset
        ) / len(subset),
    }


def evaluate(paths, method="proportional", early_lead=EARLY_LEAD_MINUTES,
             max_early_gap=None, max_late_gap=None) -> dict:
    """Early-vs-late forecast quality, overall and by weekend/daytime cell.

    Pass `max_early_gap` and `max_late_gap` for the strict version of the
    paper's test, which compares a genuinely-90-minutes-out price against a
    genuinely-near-first-pitch one. Our snapshot grid only supports that on a
    small subset, so the strict run is expected to be underpowered.
    """
    data = rows(paths, method, early_lead, max_early_gap, max_late_gap)
    if not data:
        return {"n": 0, "reason": "no event had two distinct pre-game snapshots"}

    cells = {}
    for row in data:
        key = ("weekend" if row["is_weekend"] else "weekday",
               "day" if row["is_day_game"] else "night")
        cells.setdefault(key, []).append(row)

    return {
        "n": len(data),
        "method": method,
        "overall": _cell_score(data),
        "cells": {f"{a}-{b}": _cell_score(subset)
                  for (a, b), subset in sorted(cells.items())},
        # The paper's specific prediction, isolated. Everything else is context
        # for judging whether a hit here is the effect or is one cell of four
        # coming up positive by chance.
        "prediction_cell": "weekend-day",
    }
