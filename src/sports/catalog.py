"""The sports catalog: Odds API sport keys -> a family code, label, markets and window margins.

WHY THIS EXISTS
---------------
A user-built dog used to bet only MLB and NFL because those two were hard-coded in a tuple. The Odds API
prices dozens of sport keys (every soccer league, every tennis tournament, cricket, rugby, hockey, college
sports, ...). This module is the ONE place that says which key belongs to which family, what to capture for
it, how long after the start a game is still "live", and whether a dog bet on it can be graded.

The data lives in config/sports_catalog.json (stdlib json only: CI runs Python 3.10, which has no TOML reader). Every
function takes an optional ``config`` mapping so tests never read the real file.

CODES AND ROW VALUES
--------------------
A family CODE is upper case (``NBA``, ``SOCCER``): that is what a dog spec and a ledger row carry. The value
written on a multibook ROW's ``sport`` field is the lower-case code (``nba``), because every reader of the
store (``snapshots.iter_multibook``, ``user_engine.iter_rows``) compares the lower-case sport. ``row_sport``
and ``code_of_row_sport`` convert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from src.paths import repo_root

CATALOG_PATH = repo_root() / "config" / "sports_catalog.json"
CATCH_ALL = "OTHER"
ANY = "ANY"                     # the dog-builder option meaning "every family on the menu"

_cache: dict = {}


def load(path=None) -> dict:
    """The whole catalog mapping. Read once per path and remembered; a missing or corrupt file falls back to
    a MLB+NFL-only catalog rather than crashing a caller on a paid or public path."""
    target = Path(path) if path is not None else CATALOG_PATH
    key = str(target)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data.get("families"), dict) or not data["families"]:
            raise ValueError("no families")
    except Exception:  # noqa: BLE001 -- a bad config must never take a page or the engine down
        data = {"capture": {"enabled": False}, "families": {
            "MLB": {"label": "MLB", "prefixes": ["baseball_mlb"], "markets": ["h2h", "spreads", "totals"],
                    "start_word": "first pitch", "since_margin_days": 4, "live_window_hours": 4.5,
                    "capture": "dedicated", "settles": "existing", "dog_menu": True, "draw_possible": False},
            "NFL": {"label": "NFL", "prefixes": ["americanfootball_nfl"], "markets": ["h2h", "spreads", "totals"],
                    "start_word": "kickoff", "since_margin_days": 16, "live_window_hours": 4.5,
                    "capture": "dedicated", "settles": "existing", "dog_menu": True, "draw_possible": False}}}
    _cache[key] = data
    return data


def clear_cache() -> None:
    _cache.clear()


def _families(config: Optional[Mapping] = None) -> Mapping:
    return (config if config is not None else load())["families"]


def capture_config(config: Optional[Mapping] = None) -> dict:
    """The ``capture`` block (caps, cadences, phases). Defaults fill any missing key."""
    base = {
        "enabled": True, "daily_cap_credits": 1500, "inplay_daily_cap_credits": 450,
        "scores_daily_cap_credits": 300, "max_calls_per_run": 60, "regions": ["us"],
        "phases_minutes": {"t24h": 1440, "t6h": 360, "t2h": 120, "t30m": 30},
        "store_horizon_hours": 36, "inplay_cadence_minutes": 30, "inplay_markets": ["h2h"],
        "events_idle_recheck_hours": 6, "events_lookahead_hours": 25, "dark_after_empty_captures": 2,
        "dark_retry_hours": 24, "scores_poll_interval_hours": 8, "scores_days_from": 3,
        "void_after_hours": 72, "skip_key_prefixes": ["politics_", "golf_"],
        "skip_key_suffixes": ["_winner", "_winners", "_outright", "_outrights", "_futures"],
    }
    base.update((config if config is not None else load()).get("capture") or {})
    return base


def daily_cap_credits(config: Optional[Mapping] = None) -> int:
    """The all-sports daily credit cap (config value; the owner's ceiling is 1,500 a day)."""
    return int(capture_config(config)["daily_cap_credits"])


def family_codes(config: Optional[Mapping] = None) -> tuple:
    return tuple(_families(config))


def family(code: str, config: Optional[Mapping] = None) -> Optional[Mapping]:
    return _families(config).get(str(code).upper())


def family_for_key(sport_key: str, config: Optional[Mapping] = None) -> str:
    """The family code for an Odds API sport key: the LONGEST matching prefix wins (``basketball_nba`` is
    NBA, ``basketball_euroleague`` is BASKETBALL); a key nothing claims is OTHER."""
    key = str(sport_key or "").lower()
    best, best_len = CATCH_ALL, -1
    for code, fam in _families(config).items():
        for prefix in fam.get("prefixes") or []:
            if key.startswith(prefix) and len(prefix) > best_len:
                best, best_len = code, len(prefix)
    return best


def label(code: str, config: Optional[Mapping] = None) -> str:
    fam = family(code, config)
    return str(fam["label"]) if fam else str(code)


def markets_for(code: str, config: Optional[Mapping] = None) -> list:
    fam = family(code, config)
    return list(fam["markets"]) if fam else ["h2h"]


def start_word(code: str, config: Optional[Mapping] = None) -> str:
    fam = family(code, config)
    return str((fam or {}).get("start_word") or "start")


def live_window_hours(code: str, config: Optional[Mapping] = None) -> float:
    fam = family(code, config)
    return float((fam or {}).get("live_window_hours") or 4.0)


def draw_possible(code: str, config: Optional[Mapping] = None) -> bool:
    fam = family(code, config)
    return bool((fam or {}).get("draw_possible"))


def is_dedicated(code: str, config: Optional[Mapping] = None) -> bool:
    """True when an existing pipeline already buys this family's keys (MLB, NFL, MMA)."""
    fam = family(code, config)
    return bool(fam) and fam.get("capture") == "dedicated"


def dog_families(config: Optional[Mapping] = None) -> tuple:
    """The family codes a dog builder may choose, in catalog order (MLB and NFL first)."""
    return tuple(c for c, f in _families(config).items() if f.get("dog_menu"))


def row_sport(code: str) -> str:
    """The value a multibook row's ``sport`` field carries for a family code (lower case)."""
    return str(code).lower()


def code_of_row_sport(value: str, config: Optional[Mapping] = None) -> Optional[str]:
    """The family code for a row's ``sport`` value, or None when it names no family (a legacy per-tournament
    string such as ``tennis_atp_...`` belongs to no family row)."""
    code = str(value or "").upper()
    return code if code in _families(config) else None


def since_margin_days(sport: Optional[str], config: Optional[Mapping] = None) -> Optional[int]:
    """The pre-game lead window (days) for a row sport string, or None when the catalog does not know it."""
    code = code_of_row_sport(sport or "", config)
    if code is None:
        return None
    return int(_families(config)[code].get("since_margin_days") or 4)


def is_skipped_key(sport_key: str, entry: Optional[Mapping] = None, config: Optional[Mapping] = None) -> Optional[str]:
    """Why an Odds API sport entry is NOT captured, or None when it is a capturable event sport.

    Outrights and futures have no home and away side, so no moneyline row can be built from them:
    ``has_outrights`` keys, keys that end in a winner/outright suffix, golf and politics."""
    cap = capture_config(config)
    key = str(sport_key or "").lower()
    if entry is not None and entry.get("has_outrights"):
        return "outrights"
    for suffix in cap["skip_key_suffixes"]:
        if key.endswith(suffix):
            return "outrights"
    for prefix in cap["skip_key_prefixes"]:
        if key.startswith(prefix):
            return "not_an_event_sport"
    title = str((entry or {}).get("title") or "").lower()
    if "winner" in title or "outright" in title or "futures" in title:
        return "outrights"
    return None


def public_catalog(config: Optional[Mapping] = None) -> list:
    """GET /sports/catalog body: families with labels, markets and whether a dog may choose them."""
    out = []
    for code, fam in _families(config).items():
        out.append({
            "code": code, "label": fam["label"], "markets": list(fam["markets"]),
            "prefixes": [p for p in fam.get("prefixes") or [] if p],
            "dog_menu": bool(fam.get("dog_menu")), "draw_possible": bool(fam.get("draw_possible")),
            "settles": fam.get("settles"), "note": fam.get("settles_note"),
        })
    return out
