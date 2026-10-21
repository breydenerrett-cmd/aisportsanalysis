"""The exact opposite of a condition, or an honest refusal.

WHY THIS EXISTS
---------------
The rule language has "all of" and "any of" groups but no NOT. A person who says "skip games when the wind is over
15 mph" is describing a condition that must be FALSE, and the only way to say that to the engine is to state the
complement as a condition that must be TRUE ("the wind is 15 mph or less"). That is exact for a comparison
(`gt` <-> `lte`, `lt` <-> `gte`), for two-valued choices (favourite <-> underdog, day <-> night) and for a set of
weekdays. It is NOT exact when the complement is a third state: "the market did not move toward the pick" is not
"the market moved against it", and "not these five teams" is not a list this menu can write. Those are refused
with a reason and listed under "can't automate yet", never approximated.

Missing data stays safe in both directions. A condition whose input is missing evaluates to "unknown", which counts
as not met (src/hounds/user_rules.py). Its complement is also unknown, so a game with a missing fact passes
whichever way the rule was written; that is the documented PASS behaviour (record.MISSING_DATA).

`who` flips with De Morgan: the opposite of "either team has at least 2 days of rest" is "both teams have less than 2".
"""

from __future__ import annotations

import copy
from typing import Mapping, Optional, Tuple

from src.hounds import user_rules as R

CMP_INVERSE = {"gte": "lt", "gt": "lte", "lte": "gt", "lt": "gte"}
WHO_INVERSE = {"either": "both", "both": "either"}
# the conditions whose parameters are a comparison (`cmp`) against a number, with optional `who`
CMP_IDS = frozenset({"spread_size", "rest_days", "split_pct", "travel_miles", "last_n_wins", "head_to_head",
                     "venue_record", "scoring_rate", "temperature", "wind_speed", "rain_chance", "player_rate",
                     "name_length"})
# the number each comparison reads
NUMBER_KEY = {"spread_size": "value", "rest_days": "value", "split_pct": "pct", "travel_miles": "miles",
              "last_n_wins": "wins", "head_to_head": "wins", "venue_record": "pct", "scoring_rate": "value",
              "temperature": "value", "wind_speed": "value", "rain_chance": "value", "player_rate": "value",
              "name_length": "value"}
TWO_VALUED = {"role": ("favourite", "underdog"), "venue": ("home", "away"), "time_of_day": ("day", "night")}

NOT_EXACT = ("the opposite of this condition is not on the menu, so it cannot be written as a skip rule "
             "without changing what you meant")


def invert_leaf(item: Mapping) -> Tuple[Optional[dict], str]:
    """(the opposite condition, "") or (None, why there is none)."""
    cid = item.get("id")
    out = copy.deepcopy(dict(item))
    if cid in CMP_IDS:
        out["cmp"] = CMP_INVERSE[item["cmp"]]
        if item.get("who") in WHO_INVERSE:
            out["who"] = WHO_INVERSE[item["who"]]
        return out, ""
    if cid in TWO_VALUED:
        a, b = TWO_VALUED[cid]
        value = item.get("value")
        if value not in (a, b):
            return None, NOT_EXACT
        out["value"] = b if value == a else a
        return out, ""
    if cid == "day_of_week":
        days = [d for d, _ in R.WEEKDAYS if d not in item.get("days", [])]
        if not days or len(days) == len(R.WEEKDAYS):
            return None, NOT_EXACT
        out["days"] = days
        return out, ""
    return None, NOT_EXACT


def invert_tree(node: Mapping) -> Tuple[Optional[dict], str]:
    """The opposite of a condition or a group (De Morgan), or (None, why not)."""
    if "items" not in node:
        return invert_leaf(node)
    items = []
    for child in node["items"]:
        inverted, why = invert_tree(child)
        if inverted is None:
            return None, why
        items.append(inverted)
    return {"op": "any" if node.get("op") == "all" else "all", "items": items}, ""


def leaves(node: Mapping) -> list:
    """Every condition in a tree, in order."""
    if "items" not in node:
        return [dict(node)]
    out: list = []
    for child in node["items"]:
        out.extend(leaves(child))
    return out


def canon(node) -> str:
    import json
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def interval(item: Mapping) -> Optional[Tuple[float, float, bool, bool]]:
    """(low, high, low_open, high_open) for a comparison condition, else None."""
    cid = item.get("id")
    if cid not in CMP_IDS:
        return None
    value = item.get(NUMBER_KEY[cid])
    if not isinstance(value, (int, float)):
        return None
    inf = float("inf")
    return {"gte": (value, inf, False, True), "gt": (value, inf, True, True),
            "lte": (-inf, value, True, False), "lt": (-inf, value, True, True)}[item["cmp"]]


def signature(item: Mapping) -> str:
    """Everything about a comparison except its direction and number: two conditions with the same signature
    talk about the same quantity of the same team."""
    rest = {k: v for k, v in item.items() if k not in ("cmp", NUMBER_KEY.get(item.get("id"), "value"))}
    return canon(rest)


def empty_together(a: Mapping, b: Mapping) -> bool:
    """True when no value can satisfy both comparisons (same quantity, ranges that do not meet)."""
    if a.get("id") != b.get("id") or signature(a) != signature(b):
        return False
    ia, ib = interval(a), interval(b)
    if ia is None or ib is None:
        return False
    low = max(ia[0], ib[0])
    high = min(ia[1], ib[1])
    if low < high:
        return False
    if low > high:
        return True
    # equal ends meet only when both ends are closed
    low_open = (ia[2] if ia[0] == low else False) or (ib[2] if ib[0] == low else False)
    high_open = (ia[3] if ia[1] == high else False) or (ib[3] if ib[1] == high else False)
    return low_open or high_open
