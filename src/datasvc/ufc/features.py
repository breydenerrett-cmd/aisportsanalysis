"""Leakage-free fighter features: what a fighter had done as of a moment in time.

THE ONE PROPERTY THIS MODULE EXISTS TO KEEP
-------------------------------------------
`features_as_of(store, fighter_id, as_of)` uses only bouts that started STRICTLY
BEFORE `as_of` and have a result. A bout on the as_of day, a bout that started at
the as_of instant, and every later bout never count, in any figure, including the
strength-of-schedule figure (which looks at each opponent's record as of the start
of the fight it is measuring, not as of `as_of`). One function,
`completed_fights`, is the only place a bout is admitted, so the rule is audited in
one spot and everything else (the matchup, the API) goes through it. A feature that
saw its own outcome would make every backtest on it look brilliant and every live
use of it lose money.

Two blocks are deliberately NOT as-of-date and say so in their own labels: the
career record from the fighter record (current as of when it was fetched, and it
includes fights outside the UFC) and the UFC.com career figures. Nothing in this
module or in `matchup` computes a figure, a differential or a style label from
either of them.

HOW FIGURES ARE BUILT
---------------------
Every statistical figure is `{"value", "unit", "fights", "minutes", ...}`. `fights`
and `minutes` are that figure's OWN sample: the fights that had every number the
figure needs, not the fighter's whole career, because a figure built from one
fight's statistics is not a rate and the reader must be able to tell. A rate is
the sum of the numerators over the sum of the minutes (a fight that went five
rounds weighs five rounds), never an average of per-fight rates. A figure that
cannot be computed has `value` None, carries its reason, and is listed in the
top-level `missing` list. Nothing is filled with an average or a guess.

THE ESPN BREAKDOWN FIELDS ARE ACCURACIES, NOT SHARES
----------------------------------------------------
`posBreakdownDistance`, `posBreakdownClinch`, `posBreakdownGround` and the three
`targetBreakdown*` fields look like "share of strikes by position". Checked against
the strike counts of the 2026 fixture bouts they are landed/attempted at that
position or target: 117 landed of 209 attempted at distance is 0.56, which is
exactly the saved `posBreakdownDistance`. The shares asked for here are therefore
computed from the landed counts (`sig{Distance,Clinch,Ground}{Head,Body,Leg}Strikes
Landed`), and the breakdown fields are never read.

The statistics worker owns the snake case of the stat names; `_num` also accepts
the ESPN camel case and the squashed lower case, so a row that kept ESPN's spelling
still reads.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.datasvc import names

LEAKAGE_RULE = ("uses only bouts that started strictly before as_of and have a result; "
                "a bout on the as_of date or at the as_of instant, and every later bout, is excluded")

_UTC = timezone.utc

# -- instants -------------------------------------------------------------------------

_ISO = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?\s*(Z|z|[+-]\d{2}(?::?\d{2})?)?)?\s*$")


def parse_instant(value: Any) -> datetime:
    """An ISO string, `date` or `datetime` as an aware UTC datetime.

    ESPN's own spelling ("2026-09-27T00:00Z", no seconds) is accepted along with the
    usual forms; `datetime.fromisoformat` of Python 3.10 (the oldest CI version)
    accepts neither that nor a trailing Z. A bare date is the START of that day,
    00:00 UTC, so a bout on that date has not happened yet as of it. A naive value
    is taken as UTC. Raises ValueError for anything else.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=_UTC) if value.tzinfo is None else value.astimezone(_UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=_UTC)
    if not isinstance(value, str):
        raise ValueError(f"not a date or datetime: {value!r}")
    m = _ISO.match(value)
    if not m:
        raise ValueError(f"not an ISO date or datetime: {value!r}")
    year, month, day, hour, minute, second, fraction, zone = m.groups()
    micro = int((fraction or "0").ljust(6, "0")[:6])
    dt = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                  int(second or 0), micro, tzinfo=_UTC)
    if zone and zone not in ("Z", "z"):
        digits = zone[1:].replace(":", "")
        offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:] or 0))
        dt = dt - offset if zone[0] == "+" else dt + offset
    return dt


@lru_cache(maxsize=65536)
def _instant_cached(text: str) -> Optional[datetime]:
    try:
        return parse_instant(text)
    except ValueError:
        return None


def _instant(text: Any) -> Optional[datetime]:
    """`parse_instant` for a stored date string; None when absent or unreadable.

    Cached because the strength-of-schedule figure re-reads each opponent's bout dates
    for every fight; only strings reach the cache, so a corrupt value cannot break it.
    """
    if not isinstance(text, str) or not text:
        return None
    return _instant_cached(text)


def instant(text: Any) -> Optional[datetime]:
    """A stored date string as an aware UTC datetime; None when absent or unreadable."""
    return _instant(text)


def bout_start(bout: dict) -> Optional[datetime]:
    """When the bout started, as an aware UTC datetime; None when its date is absent or unreadable."""
    return _instant(bout.get("date_utc"))


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_of(text: Optional[str]) -> Optional[date]:
    inst = _instant(text)
    return inst.date() if inst else None


# -- results --------------------------------------------------------------------------

class UnknownFighter(LookupError):
    """The id is in neither the fighters file nor any bout."""


# The contract's `result_method` values, grouped for the by-method counts. DRAW and NC
# are results with no winner, so they never reach the by-method counts.
METHOD_GROUP = {
    "KO_TKO": "ko_tko", "SUB": "submission",
    "DEC_UNANIMOUS": "decision", "DEC_SPLIT": "decision", "DEC_MAJORITY": "decision",
    "DECISION": "decision", "DQ": "dq", "OTHER": "other",
    "DRAW": "draw", "NC": "no_contest",
}
WIN_LOSS_GROUPS = ("ko_tko", "submission", "decision", "dq", "other", "unknown")
FINISH_GROUPS = ("ko_tko", "submission")


def outcome_for(bout: dict, fighter_id: str) -> Optional[str]:
    """win, loss, draw or no_contest for `fighter_id`; None when the bout has no usable result.

    A winner makes it a win or a loss. With no winner only the contract's DRAW and NC
    methods are results. A winner who is neither fighter, or a winner on a bout the
    contract says was a draw or no contest, is contradictory data and is left out
    rather than read one way or the other.
    """
    winner = bout.get("winner_id")
    method = bout.get("result_method")
    fighters = (str(bout.get("fighter_a_id")), str(bout.get("fighter_b_id")))
    if str(fighter_id) not in fighters:
        return None
    if winner not in (None, ""):
        if method in ("DRAW", "NC") or str(winner) not in fighters:
            return None
        return "win" if str(winner) == str(fighter_id) else "loss"
    if method == "DRAW":
        return "draw"
    if method == "NC":
        return "no_contest"
    return None


def _group(bout: dict) -> str:
    return METHOD_GROUP.get(bout.get("result_method"), "unknown")


@dataclass(frozen=True, eq=False)
class Fight:
    """One completed bout from one fighter's side.

    `eq=False` keeps it hashable by identity: it holds the bout's dict, which a generated
    value-based hash could not hash.
    """
    bout: dict
    bout_id: str
    start: datetime
    opponent_id: str
    outcome: str                  # win | loss | draw | no_contest
    method: Optional[str]         # the contract's result_method
    group: str                    # ko_tko | submission | decision | dq | other | draw | no_contest | unknown
    seconds: Optional[float]      # fight_time_s when known and positive
    own: Optional[dict]           # this fighter's statistics row for the bout
    opp: Optional[dict]           # the opponent's statistics row for the same bout


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return float(value)
    return None


def _scan(store, fighter_id: str, before: datetime,
          skipped: Optional[Dict[str, list]] = None) -> List[tuple]:
    """(start, bout_id, bout, outcome) for the fighter's bouts admitted by the rule, oldest first.

    THE LEAKAGE GATE. A bout is admitted only when its start is known, is strictly
    before `before`, and it has a result. A bout with no readable start cannot be
    placed relative to `before`, so it is excluded, never assumed to be in the past.
    `skipped` collects what was left out so a reader can see it: bouts that started
    before `before` with no result (cancelled, or a result not recorded yet), and
    decided bouts with no start time.
    """
    rows = []
    for bout in store.bouts_by_fighter().get(str(fighter_id), ()):
        start = bout_start(bout)
        outcome = outcome_for(bout, fighter_id)
        if start is None:
            if outcome is not None and skipped is not None:
                skipped["no_start_time"].append(bout["bout_id"])
            continue
        if not start < before:
            continue
        if outcome is None:
            if skipped is not None:
                skipped["started_without_result"].append(
                    {"bout_id": bout["bout_id"], "date_utc": bout.get("date_utc"), "status": bout.get("status")})
            continue
        rows.append((start, bout["bout_id"], bout, outcome))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def completed_fights(store, fighter_id: str, before: Any,
                     skipped: Optional[Dict[str, list]] = None) -> List[Fight]:
    """The fighter's fights that started strictly before `before` and have a result, oldest first."""
    cutoff = parse_instant(before)
    stats = store.stats_for()
    out = []
    for start, bout_id, bout, outcome in _scan(store, fighter_id, cutoff, skipped):
        a, b = str(bout.get("fighter_a_id")), str(bout.get("fighter_b_id"))
        opponent = b if a == str(fighter_id) else a
        out.append(Fight(
            bout=bout, bout_id=bout_id, start=start, opponent_id=opponent, outcome=outcome,
            method=bout.get("result_method"), group=_group(bout),
            seconds=_positive(bout.get("fight_time_s")),
            own=stats.get((bout_id, str(fighter_id))), opp=stats.get((bout_id, opponent))))
    return out


def tally(outcomes: Sequence[str]) -> Dict[str, int]:
    return {"wins": outcomes.count("win"), "losses": outcomes.count("loss"),
            "draws": outcomes.count("draw"), "no_contests": outcomes.count("no_contest")}


def win_rate_of(counts: Dict[str, int]) -> Optional[float]:
    """wins / (wins + losses + draws); a no contest is not a result of either fighter's."""
    played = counts["wins"] + counts["losses"] + counts["draws"]
    return counts["wins"] / played if played else None


# -- statistics rows ------------------------------------------------------------------

@lru_cache(maxsize=256)
def _variants(name: str) -> Tuple[str, ...]:
    parts = name.split("_")
    camel = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    return tuple(dict.fromkeys((name, camel, name.replace("_", ""))))


def _num(row: Optional[dict], name: str) -> Optional[float]:
    """A statistic as a non-negative finite number, or None when the row lacks it.

    Only real numbers count: a bool, a string or a negative placeholder is treated as
    absent, because the contract says missing is null and a figure built on a
    coerced guess is the thing the rule forbids.
    """
    if not row:
        return None
    for key in _variants(name):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value) and value >= 0:
            return float(value)
    return None


# Keys of a fight_stats row that are not statistics.
_ROW_META = frozenset({"bout_id", "fighter_id", "opponent_id", "event_id", "date_utc", "stats_complete",
                       "source_url", "fetched_utc"})


def _has_stats(row: Optional[dict]) -> bool:
    """True when the row carries at least one statistic.

    A row that exists but is all nulls (ESPN had no numbers for the bout) is not statistics,
    and counting it would make a bout with no data look covered.
    """
    if not row:
        return False
    return any(isinstance(v, (int, float)) and not isinstance(v, bool)
               for k, v in row.items() if k not in _ROW_META)


_POSITIONS = ("distance", "clinch", "ground")
_TARGETS = ("head", "body", "leg")
LANDED_BY_POSITION_TARGET = {(p, t): f"sig_{p}_{t}_strikes_landed" for p in _POSITIONS for t in _TARGETS}


# -- figures --------------------------------------------------------------------------

def _clean(x: Optional[float], digits: int = 4):
    if x is None:
        return None
    r = round(x, digits)
    return int(r) if float(r).is_integer() else r


def _figure(value, unit: str, fights: int = 0, seconds: float = 0.0, *,
            num=None, den=None, reason: Optional[str] = None, digits: int = 4) -> dict:
    fig = {"value": _clean(value, digits), "unit": unit, "fights": fights,
           "minutes": round(seconds / 60.0, 2)}
    if num is not None:
        fig["num"] = _clean(num)
        fig["den"] = _clean(den)
    if value is None and reason:
        fig["reason"] = reason
    return fig


def _static(value, unit: str, reason: Optional[str] = None) -> dict:
    fig = {"value": value, "unit": unit}
    if value is None and reason:
        fig["reason"] = reason
    return fig


def _why(n_fights: int, needs: str) -> str:
    if n_fights == 0:
        return "no UFC fights in the store before as_of"
    return f"none of the {n_fights} fight(s) before as_of has {needs}"


def _rate(fights: Sequence[Fight], getter: Callable[[Fight], Optional[float]], *,
          per_minutes: int, unit: str, needs: str) -> dict:
    """Sum of `getter` over the fights that have it and a fight time, per `per_minutes` minutes."""
    total = seconds = 0.0
    used = 0
    for f in fights:
        v = getter(f)
        if v is None or f.seconds is None:
            continue
        total += v
        seconds += f.seconds
        used += 1
    if not used:
        return _figure(None, unit, reason=_why(len(fights), needs))
    minutes = seconds / 60.0
    return _figure(total / minutes * per_minutes, unit, used, seconds, num=total, den=minutes)


def _ratio(fights: Sequence[Fight], num_of: Callable[[Fight], Optional[float]],
           den_of: Callable[[Fight], Optional[float]], *, unit: str, needs: str,
           zero_den: str, complement: bool = False) -> dict:
    """Sum(num)/Sum(den) over the fights that have both; `complement` reports 1 - that."""
    n = d = seconds = 0.0
    used = 0
    for f in fights:
        a, b = num_of(f), den_of(f)
        if a is None or b is None:
            continue
        n += a
        d += b
        seconds += f.seconds or 0.0
        used += 1
    if not used:
        return _figure(None, unit, reason=_why(len(fights), needs))
    if d <= 0:
        return _figure(None, unit, used, seconds, num=n, den=d, reason=zero_den)
    value = n / d
    return _figure(1.0 - value if complement else value, unit, used, seconds, num=n, den=d)


def _share_figures(fights: Sequence[Fight]) -> Dict[str, dict]:
    """Share of the fighter's landed significant strikes by position and by target.

    A fight counts only when all nine position-by-target landed counts are present,
    so the three position shares sum to 1 and so do the three target shares.
    """
    by_pos = {p: 0.0 for p in _POSITIONS}
    by_tgt = {t: 0.0 for t in _TARGETS}
    seconds = 0.0
    used = 0
    for f in fights:
        cells = {k: _num(f.own, name) for k, name in LANDED_BY_POSITION_TARGET.items()}
        if any(v is None for v in cells.values()):
            continue
        for (p, t), v in cells.items():
            by_pos[p] += v
            by_tgt[t] += v
        seconds += f.seconds or 0.0
        used += 1
    total = sum(by_pos.values())
    out = {}
    needs = "all nine position-by-target landed significant strike counts"
    for label, parts in (("position", by_pos), ("target", by_tgt)):
        for key, part in parts.items():
            name = f"sig_strike_share_{key}"
            unit = f"share of significant strikes landed, by {label}"
            if not used:
                out[name] = _figure(None, unit, reason=_why(len(fights), needs))
            elif total <= 0:
                out[name] = _figure(None, unit, used, seconds, num=part, den=total,
                                    reason="no significant strikes landed in the fights with the breakdown")
            else:
                out[name] = _figure(part / total, unit, used, seconds, num=part, den=total)
    return out


def _count_figure(name_unit: str, numerator: int, denominator: int, fights: Sequence[Fight],
                  reason: str) -> dict:
    seconds = sum(f.seconds or 0.0 for f in fights)
    if denominator <= 0:
        return _figure(None, name_unit, len(fights), seconds, reason=reason)
    return _figure(numerator / denominator, name_unit, len(fights), seconds,
                   num=numerator, den=denominator)


# -- schedule strength, weight classes -----------------------------------------------

# Weight limits in pounds, for the direction of a weight class change. Keyed by
# names.normalise, so "Women's Strawweight" is "womens strawweight". A class not here
# (catchweight, open weight) gets direction "unknown" rather than a guess.
WEIGHT_LIMIT_LB = {
    "strawweight": 115, "flyweight": 125, "bantamweight": 135, "featherweight": 145,
    "lightweight": 155, "welterweight": 170, "middleweight": 185, "light heavyweight": 205,
    "heavyweight": 265,
    "womens strawweight": 115, "womens flyweight": 125, "womens bantamweight": 135,
    "womens featherweight": 145,
}


def _weight_classes(fights: Sequence[Fight]) -> dict:
    seen: Dict[str, dict] = {}
    sequence = []
    for f in fights:
        wc = f.bout.get("weight_class")
        if not wc:
            continue
        sequence.append((wc, f))
        entry = seen.setdefault(wc, {"weight_class": wc, "fights": 0,
                                     "first_utc": iso_utc(f.start), "last_utc": iso_utc(f.start)})
        entry["fights"] += 1
        entry["last_utc"] = iso_utc(f.start)
    change = None
    for i in range(len(sequence) - 1, 0, -1):
        before, after = sequence[i - 1][0], sequence[i][0]
        if before != after:
            lo, hi = WEIGHT_LIMIT_LB.get(names.normalise(before)), WEIGHT_LIMIT_LB.get(names.normalise(after))
            direction = "unknown" if lo is None or hi is None else ("up" if hi > lo else "down" if hi < lo else "unknown")
            change = {"from": before, "to": after, "date_utc": iso_utc(sequence[i][1].start),
                      "bout_id": sequence[i][1].bout_id, "direction": direction}
            break
    return {
        "current": sequence[-1][0] if sequence else None,
        "fought": sorted(seen.values(), key=lambda e: (e["last_utc"], e["weight_class"]), reverse=True),
        "most_recent_change": change,
        "fights_without_weight_class": len(fights) - len(sequence),
    }


def _schedule_strength(store, fights: Sequence[Fight]) -> Tuple[List[dict], int]:
    """Each opponent's UFC record at the START of the fight, from the opponent's own bouts.

    The opponent's history is cut at the start of the fight being measured (strictly
    before it), not at `as_of`: using the opponent's record as of today would credit a
    fighter for how good an opponent LATER turned out to be, which is leakage. An
    opponent with no earlier fight in the store has no win rate and is counted
    separately, never scored as an average opponent.
    """
    detail = []
    without = 0
    for f in fights:
        rows = _scan(store, f.opponent_id, f.start)
        counts = tally([r[3] for r in rows])
        rate = win_rate_of(counts)
        if rate is None:
            without += 1
        detail.append({"bout_id": f.bout_id, "date_utc": iso_utc(f.start), "opponent_id": f.opponent_id,
                       "opponent_record_then": {k: counts[k] for k in ("wins", "losses", "draws", "no_contests")},
                       "opponent_win_rate": _clean(rate)})
    return detail, without


# -- the public function --------------------------------------------------------------

def fight_line(store, f: Fight) -> dict:
    """One fight as a short factual line (last_three here; shared opponents and meetings in matchup)."""
    opponent = store.fighter_by_id().get(f.opponent_id) or {}
    return {"bout_id": f.bout_id, "date_utc": f.bout.get("date_utc"), "opponent_id": f.opponent_id,
            "opponent_name": opponent.get("name"), "result": f.outcome, "method": f.method,
            "detail": f.bout.get("result_detail"), "round": f.bout.get("end_round"),
            "time_s": f.bout.get("end_time_s"), "weight_class": f.bout.get("weight_class")}


def _streak(fights: Sequence[Fight]) -> dict:
    if not fights:
        return {"type": None, "length": 0}
    kind = fights[-1].outcome
    length = 0
    for f in reversed(fights):
        if f.outcome != kind:
            break
        length += 1
    return {"type": kind, "length": length}


def _age(dob: Optional[str], cutoff: datetime) -> Tuple[Optional[float], Optional[str]]:
    born = _date_of(dob)
    if born is None:
        return None, "no date of birth on the fighter record" if not dob else f"unreadable date of birth {dob!r}"
    days = (cutoff.date() - born).days
    if days < 0:
        return None, "date of birth is after as_of"
    return round(days / 365.2425, 2), None


def _ufccom_block(store, fighter_id: str) -> Optional[dict]:
    profile = store.profile_for().get(str(fighter_id))
    if not profile:
        return None
    skip = {"fighter_id", "ufc_slug", "source_url", "fetched_utc"}
    return {
        "label": "UFC.com career figures",
        "as_of_safe": False,
        "note": ("Career numbers as the UFC.com page showed them when fetched. Not as-of-date: they include "
                 "every fight up to the fetch, so they must never feed anything where leakage matters. "
                 "No figure, differential or style label in this module uses them."),
        "ufc_slug": profile.get("ufc_slug"),
        "source_url": profile.get("source_url"),
        "fetched_utc": profile.get("fetched_utc"),
        "figures": {k: v for k, v in profile.items() if k not in skip},
    }


def _career_record_block(fighter: Optional[dict]) -> Optional[dict]:
    record = (fighter or {}).get("record")
    if not isinstance(record, dict):
        return None
    return {
        "label": "Overall professional record from the fighter record, including fights outside the UFC",
        "includes_non_ufc": True,
        "as_of_safe": False,
        "note": "As of the fetch time of the fighter record, not as of as_of; do not use it where leakage matters.",
        "wins": record.get("wins"), "losses": record.get("losses"), "draws": record.get("draws"),
        "no_contests": record.get("no_contests", record.get("noContests")),
        "fetched_utc": fighter.get("fetched_utc"),
    }


def features_as_of(store, fighter_id: str, as_of: Any) -> dict:
    """The fighter's figures using only bouts that started strictly before `as_of`.

    `as_of` is an ISO date or datetime (a date means the start of that day, UTC), or a
    `date`/`datetime`. Raises ValueError for an unreadable `as_of` and UnknownFighter
    when the id is in neither the fighters file nor any bout. See the module docstring
    for the rule and for how a figure's sample and `missing` entry work.
    """
    if as_of is None:
        raise ValueError("as_of is required")
    fighter_id = str(fighter_id)
    cutoff = parse_instant(as_of)
    fighter = store.fighter_by_id().get(fighter_id)
    if fighter is None and fighter_id not in store.bouts_by_fighter():
        raise UnknownFighter(fighter_id)

    skipped: Dict[str, list] = {"no_start_time": [], "started_without_result": []}
    fights = completed_fights(store, fighter_id, cutoff, skipped)
    n = len(fights)
    counts = tally([f.outcome for f in fights])
    wins = [f for f in fights if f.outcome == "win"]
    losses = [f for f in fights if f.outcome == "loss"]
    fight_seconds = sum(f.seconds or 0.0 for f in fights)

    figures: Dict[str, dict] = {}

    # experience and results ---------------------------------------------------------
    figures["ufc_fights"] = _figure(n, "fights", n, fight_seconds)
    played = counts["wins"] + counts["losses"] + counts["draws"]
    figures["win_rate"] = _count_figure("wins / (wins + losses + draws)", counts["wins"], played, fights,
                                        reason=_why(n, "a win, loss or draw"))

    known = [f for f in fights if f.outcome != "no_contest" and f.group != "unknown"]
    known_wins = [f for f in wins if f.group != "unknown"]
    known_losses = [f for f in losses if f.group != "unknown"]
    method_needs = "a decided result with a recorded method"
    figures["finish_rate"] = _count_figure(
        "finishing wins (KO/TKO or submission) per fight", sum(1 for f in known if f.outcome == "win" and f.group in FINISH_GROUPS),
        len(known), known, _why(n, method_needs))
    figures["been_finished_rate"] = _count_figure(
        "losses by KO/TKO or submission per fight", sum(1 for f in known if f.outcome == "loss" and f.group in FINISH_GROUPS),
        len(known), known, _why(n, method_needs))
    figures["finish_share_of_wins"] = _count_figure(
        "share of wins that were KO/TKO or submission", sum(1 for f in known_wins if f.group in FINISH_GROUPS),
        len(known_wins), known_wins, "no wins with a recorded method before as_of")
    figures["finished_share_of_losses"] = _count_figure(
        "share of losses that were KO/TKO or submission", sum(1 for f in known_losses if f.group in FINISH_GROUPS),
        len(known_losses), known_losses, "no losses with a recorded method before as_of")
    figures["distance_rate"] = _count_figure(
        "share of fights that went to the judges' scorecards",
        sum(1 for f in known if f.group in ("decision", "draw")), len(known), known, _why(n, method_needs))

    timed = [f for f in fights if f.seconds is not None]
    if timed:
        total = sum(f.seconds for f in timed)
        figures["average_fight_time_s"] = _figure(total / len(timed), "seconds", len(timed), total,
                                                  num=total, den=len(timed), digits=2)
    else:
        figures["average_fight_time_s"] = _figure(None, "seconds", reason=_why(n, "a recorded fight time"))

    # striking -----------------------------------------------------------------------
    sig_own = "its own significant strike counts and a fight time"
    sig_opp = "the opponent's significant strike counts and a fight time"
    figures["sig_strikes_landed_per_min"] = _rate(
        fights, lambda f: _num(f.own, "sig_strikes_landed"), per_minutes=1,
        unit="significant strikes landed per minute", needs=sig_own)
    figures["sig_strikes_absorbed_per_min"] = _rate(
        fights, lambda f: _num(f.opp, "sig_strikes_landed"), per_minutes=1,
        unit="significant strikes absorbed per minute", needs=sig_opp)
    figures["sig_strike_accuracy"] = _ratio(
        fights, lambda f: _num(f.own, "sig_strikes_landed"), lambda f: _num(f.own, "sig_strikes_attempted"),
        unit="significant strikes landed / attempted", needs="its own significant strike counts",
        zero_den="no significant strikes attempted in the fights with statistics")
    figures["sig_strike_defence"] = _ratio(
        fights, lambda f: _num(f.opp, "sig_strikes_landed"), lambda f: _num(f.opp, "sig_strikes_attempted"),
        unit="1 - opponent significant strikes landed / attempted", needs="the opponent's significant strike counts",
        zero_den="opponents attempted no significant strikes in the fights with statistics", complement=True)
    figures.update(_share_figures(fights))
    figures["knockdowns_landed_per_15"] = _rate(
        fights, lambda f: _num(f.own, "knock_downs"), per_minutes=15,
        unit="knockdowns scored per 15 minutes", needs="its own knockdown count and a fight time")
    figures["knockdowns_suffered_per_15"] = _rate(
        fights, lambda f: _num(f.opp, "knock_downs"), per_minutes=15,
        unit="knockdowns suffered per 15 minutes", needs="the opponent's knockdown count and a fight time")

    # grappling ----------------------------------------------------------------------
    figures["takedowns_landed_per_15"] = _rate(
        fights, lambda f: _num(f.own, "takedowns_landed"), per_minutes=15,
        unit="takedowns landed per 15 minutes", needs="its own takedown count and a fight time")
    figures["takedown_accuracy"] = _ratio(
        fights, lambda f: _num(f.own, "takedowns_landed"), lambda f: _num(f.own, "takedowns_attempted"),
        unit="takedowns landed / attempted", needs="its own takedown counts",
        zero_den="no takedowns attempted in the fights with statistics")
    figures["takedown_defence"] = _ratio(
        fights, lambda f: _num(f.opp, "takedowns_landed"), lambda f: _num(f.opp, "takedowns_attempted"),
        unit="1 - opponent takedowns landed / attempted", needs="the opponent's takedown counts",
        zero_den="opponents attempted no takedowns in the fights with statistics", complement=True)
    figures["control_time_share"] = _ratio(
        fights, lambda f: _num(f.own, "time_in_control"), lambda f: f.seconds,
        unit="seconds in control / fight seconds", needs="its own control time and a fight time",
        zero_den="no fight time in the fights with control statistics")
    figures["submission_attempts_per_15"] = _rate(
        fights, lambda f: _num(f.own, "submissions"), per_minutes=15,
        unit="submission attempts per 15 minutes", needs="its own submission count and a fight time")

    # schedule, layoff, physical -----------------------------------------------------
    detail, without = _schedule_strength(store, fights)
    rated = [d["opponent_win_rate"] for d in detail if d["opponent_win_rate"] is not None]
    if rated:
        sos = _figure(sum(rated) / len(rated), "mean opponent UFC win rate at the start of each fight",
                      len(rated), sum(f.seconds or 0.0 for f, d in zip(fights, detail) if d["opponent_win_rate"] is not None),
                      num=sum(rated), den=len(rated))
        sos["opponents_without_history"] = without
        figures["strength_of_schedule"] = sos
    else:
        figures["strength_of_schedule"] = _figure(
            None, "mean opponent UFC win rate at the start of each fight",
            reason=_why(0, "") if not n else "no opponent had an earlier UFC fight in the store")
        figures["strength_of_schedule"]["opponents_without_history"] = without

    if fights:
        last = fights[-1]
        figures["days_since_last_fight"] = _static((cutoff - last.start).days, "days")
    else:
        figures["days_since_last_fight"] = _static(None, "days", "no UFC fights in the store before as_of")

    fighter_reason = "the fighter is not in the fighters file"
    age, age_reason = _age((fighter or {}).get("dob"), cutoff) if fighter else (None, fighter_reason)
    figures["age_years"] = _static(age, "years", age_reason)
    for key, label in (("height_in", "height"), ("reach_in", "reach")):
        v = (fighter or {}).get(key)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
        figures[key] = _static(float(v) if ok else None, "inches",
                               None if ok else (f"no {label} on the fighter record" if fighter else fighter_reason))

    # blocks --------------------------------------------------------------------------
    def by_method(group: Sequence[Fight]) -> Dict[str, int]:
        return {g: sum(1 for f in group if f.group == g) for g in WIN_LOSS_GROUPS}

    record = {
        "fights": n, **counts,
        "wins_by_method": by_method(wins), "losses_by_method": by_method(losses),
        "first_fight_utc": iso_utc(fights[0].start) if fights else None,
        "last_fight_utc": iso_utc(fights[-1].start) if fights else None,
    }
    own_ok = {f.bout_id: _has_stats(f.own) for f in fights}
    opp_ok = {f.bout_id: _has_stats(f.opp) for f in fights}
    sample = {
        "fights": n,
        "minutes": round(fight_seconds / 60.0, 2),
        "fights_with_own_stats": sum(own_ok.values()),
        "fights_with_opponent_stats": sum(opp_ok.values()),
        "fights_with_both_stats": sum(1 for f in fights if own_ok[f.bout_id] and opp_ok[f.bout_id]),
        "fights_without_any_stats": [f.bout_id for f in fights if not own_ok[f.bout_id] and not opp_ok[f.bout_id]],
        "skipped": skipped,
    }

    career = _career_record_block(fighter)
    ufccom = _ufccom_block(store, fighter_id)

    missing = [{"figure": name, "reason": fig.get("reason") or "not computed"}
               for name, fig in figures.items() if fig["value"] is None]
    if career is None:
        missing.append({"figure": "career_record_incl_non_ufc",
                        "reason": "no overall record on the fighter record" if fighter else fighter_reason})
    if ufccom is None:
        missing.append({"figure": "ufccom_career", "reason": "no UFC.com profile for this fighter in the store"})

    return {
        "fighter_id": fighter_id,
        "name": (fighter or {}).get("name"),
        "as_of": iso_utc(cutoff),
        "leakage_rule": LEAKAGE_RULE,
        "sample": sample,
        "record": record,
        "figures": figures,
        "streak": _streak(fights),
        "last_three": [fight_line(store, f) for f in reversed(fights[-3:])],
        "physical": {"stance": (fighter or {}).get("stance"), "dob": (fighter or {}).get("dob")},
        "weight_classes": _weight_classes(fights),
        "strength_of_schedule_by_fight": detail,
        "career_record_incl_non_ufc": career,
        "ufccom_career": ufccom,
        "missing": missing,
    }
