"""Candidate fields, checked against the user_spec menu one at a time and never repaired.

A candidate comes from a form control, from the deterministic parser or from a model. Whatever its source,
`check_fields` is the only door into the interview's state, and it applies the menu's own bounds
(src/hounds/user_spec.py, src/hounds/user_rules.py). A value the menu refuses is not clamped to the nearest
legal one: a model's idea of a better number is not the person's rule. It comes back in `refused` with the
menu's reason, and the caller lists it under "can't automate yet" so the person sees what was asked and why
it did not fit.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from src.hounds import user_rules as R
from src.hounds import user_spec

TIMINGS = ("pregame", "live", "both")
LINE_TIMINGS = ("lock", "opening", "closing")
ATTRIBUTIONS = ("anonymous", "kennel", "named")
ROLES = ("any", "favourite", "underdog")

# every field the interview understands; anything else is refused by name
KNOWN = ("sports", "markets", "timing", "side", "role", "price_any", "price_min", "price_max", "min_books",
         "line_timing", "max_bets_per_day", "lock_minutes", "stake_units", "publish_ok", "attribution",
         "attribution_name")
# fields a text-reader (the parser or a model) may propose; the rest only come from a form control
TEXT_FIELDS = ("sports", "markets", "timing", "side", "role", "price_min", "price_max", "min_books",
               "line_timing", "max_bets_per_day", "lock_minutes", "stake_units")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _price(value: Any) -> Tuple[Any, str]:
    if not _is_int(value) or abs(value) < 100:
        return None, "must be an American price such as -150 or +120"
    if value < 0 and value < user_spec.SHORTEST_ALLOWED_PRICE:
        return None, f"cannot be {user_spec.MAX_FAVOURITE_PRICE} or worse; this program never selects a price that short"
    if value > user_spec.LONGEST_ALLOWED_PRICE:
        return None, f"cannot be longer than +{user_spec.LONGEST_ALLOWED_PRICE}"
    return value, ""


def _bounded(value: Any, low: int, high: int, noun: str) -> Tuple[Any, str]:
    if not _is_int(value) or not (low <= value <= high):
        return None, f"{noun} must be a whole number from {low} to {high}"
    return value, ""


def check_one(name: str, value: Any) -> Tuple[Any, str]:
    """(clean value, "") or (None, the menu's reason)."""
    if name == "sports":
        clean = user_spec.normalize_sports(value)
        return (clean, "") if clean else (None, user_spec.sports_error_text())
    if name == "markets":
        items = [value] if isinstance(value, str) else value
        if (not isinstance(items, (list, tuple)) or not items or len(set(items)) != len(items)
                or any(m not in R.ALL_MARKETS for m in items)):
            return None, f"choose from {', '.join(R.ALL_MARKETS)}"
        return [m for m in R.ALL_MARKETS if m in items], ""
    if name == "timing":
        return (value, "") if value in TIMINGS else (None, f"choose one of {', '.join(TIMINGS)}")
    if name == "side":
        return (value, "") if value in R.SIDES else (None, f"choose one of {', '.join(R.SIDES)}")
    if name == "role":
        return (value, "") if value in ROLES else (None, f"choose one of {', '.join(ROLES)}")
    if name in ("price_min", "price_max"):
        return _price(value)
    if name == "price_any":
        return (True, "") if value is True else (None, "must be true or left out")
    if name == "min_books":
        return _bounded(value, *user_spec.MIN_BOOKS_RANGE, "books")
    if name == "line_timing":
        return (value, "") if value in LINE_TIMINGS else (None, f"choose one of {', '.join(LINE_TIMINGS)}")
    if name == "max_bets_per_day":
        return _bounded(value, *user_spec.MAX_BETS_RANGE, "bets a day")
    if name == "lock_minutes":
        if isinstance(value, bool) or value not in user_spec.LOCK_CHOICES:
            return None, f"must be one of {', '.join(map(str, user_spec.LOCK_CHOICES))} minutes before the start"
        return int(value), ""
    if name == "stake_units":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) not in R.STAKE_CHOICES:
            return None, f"must be one of {', '.join(f'{s:g}' for s in R.STAKE_CHOICES)} paper units"
        return float(value), ""
    if name == "publish_ok":
        return (value, "") if isinstance(value, bool) else (None, "must be yes or no")
    if name == "attribution":
        return (value, "") if value in ATTRIBUTIONS else (None, f"choose one of {', '.join(ATTRIBUTIONS)}")
    if name == "attribution_name":
        text = " ".join(str(value or "").split())
        if not (2 <= len(text) <= 40):
            return None, "must be 2 to 40 characters"
        problem = user_spec.text_problem(text)
        return (None, problem) if problem else (text, "")
    return None, "is not a field on the menu"


def check_fields(raw: Any, *, allowed: Tuple[str, ...] = KNOWN) -> Tuple[dict, list]:
    """(clean, refused). `clean` holds only menu-legal values in a canonical key order; `refused` is
    [{field, value, reason}] for everything else, including keys that are not fields."""
    clean: dict = {}
    refused: list = []
    if not isinstance(raw, Mapping):
        return clean, refused
    for name in sorted(raw, key=str):
        value = raw[name]
        if value is None:
            continue
        if name not in allowed:
            refused.append({"field": str(name)[:30], "value": _show(value), "reason": "is not something this question takes"})
            continue
        good, why = check_one(name, value)
        if why:
            refused.append({"field": name, "value": _show(value), "reason": why})
        else:
            clean[name] = good
    return clean, refused


def _show(value: Any) -> str:
    return str(value)[:60]
