"""Small, hand-built matchup sheets for tests/test_ufc_read.py and the web tests.

A sheet here has only the fields `src/analysis/ufc_read.py` reads, in the shapes
`src/datasvc/ufc/matchup.py` writes (docs/datasvc/UFC_FEATURES.md section 5). The BASELINE
is two identical, solidly sampled fighters, so no rule fires; a test changes one figure and
checks the one rule that should answer. A separate test class runs the read over the full
sheets of the synthetic world the data layer's own tests use, so the hand-built shape cannot
drift from the real one without something failing.
"""

from __future__ import annotations

from typing import Any, Optional

# value, fights, minutes (None for a static figure), and num/den where the figure has them.
BASE_VALUES = {
    "sig_strikes_landed_per_min": 4.0, "sig_strikes_absorbed_per_min": 4.0,
    "sig_strike_accuracy": 0.48, "sig_strike_defence": 0.55,
    "knockdowns_landed_per_15": 0.3, "knockdowns_suffered_per_15": 0.2,
    "takedowns_landed_per_15": 1.0, "takedown_accuracy": 0.4, "takedown_defence": 0.7,
    "control_time_share": 0.15, "submission_attempts_per_15": 0.3,
    "finish_rate": 0.4, "been_finished_rate": 0.2, "distance_rate": 0.5,
    "average_fight_time_s": 700.0, "strength_of_schedule": 0.5, "win_rate": 0.6, "ufc_fights": 8,
}


def figure(value: Any, fights: int = 8, minutes: float = 100.0, **extra) -> dict:
    out = {"value": value, "unit": "unit", "fights": fights, "minutes": minutes}
    out.update(extra)
    return out


def _record(fights: int = 8, wins: int = 5, losses: int = 3) -> dict:
    return {"fights": fights, "wins": wins, "losses": losses, "draws": 0, "no_contests": 0,
            "wins_by_method": {"ko_tko": 2, "submission": 2, "decision": wins - 4, "dq": 0, "other": 0, "unknown": 0},
            "losses_by_method": {"ko_tko": 1, "submission": 0, "decision": losses - 1, "dq": 0, "other": 0, "unknown": 0},
            "first_fight_utc": "2024-02-03T22:00:00Z", "last_fight_utc": "2026-07-04T22:00:00Z"}


def fighter_features(name: str, fid: str) -> dict:
    figs = {k: figure(v) for k, v in BASE_VALUES.items()}
    figs["finish_rate"] = figure(0.4, num=3, den=8)
    figs["been_finished_rate"] = figure(0.2, num=2, den=8)
    figs["takedown_defence"] = figure(0.7, num=14, den=20)
    figs["ufc_fights"] = figure(8, fights=8)
    return {
        "fighter_id": fid, "name": name, "as_of": "2026-10-10T23:00:00Z",
        "sample": {"fights": 8, "minutes": 100.0},
        "record": _record(), "figures": figs,
        "streak": {"type": "win", "length": 1}, "last_three": [],
        "weight_classes": {"current": "Welterweight"},
        "career_record_incl_non_ufc": {"wins": 12, "losses": 4, "draws": 0, "fetched_utc": "2026-10-03T12:00:00Z"},
        "missing": [],
    }


def physical_side(**kw) -> dict:
    out = {"height_in": 72.0, "reach_in": 74.0, "reach_minus_height_in": 2.0, "age_years": 29.0, "stance": "Orthodox"}
    out.update(kw)
    return out


def odds_block(a=-170, b=145, **extra) -> dict:
    def imp(p):
        return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)

    def snap(pa, pb):
        total = imp(pa) + imp(pb)
        return {"a": pa, "b": pb, "implied": {"a": round(imp(pa), 4), "b": round(imp(pb), 4)},
                "margin": round(total - 1.0, 4),
                "without_margin": {"a": round(imp(pa) / total, 4), "b": round(imp(pb) / total, 4)}}

    out = {"provider": "DraftKings", "provider_id": "100", "fetched_utc": "2026-10-03T12:00:00Z", "is_closing": False,
           "as_of_safe": False, "orientation": "verified", "other_providers": [],
           "moneyline": {"open": snap(a + 20, b - 15), "close": None, "current": snap(a, b)},
           "rounds_total": {"line": 4.5, "open": None, "close": None,
                            "current": {"over": -110, "under": -110, "implied": {"over": 0.5238, "under": 0.5238},
                                        "margin": 0.0476, "without_margin": {"over": 0.5, "under": 0.5}}},
           "method": None}
    out.update(extra)
    return out


def make_sheet(a: Optional[dict] = None, b: Optional[dict] = None, *, odds: Any = "default",
               bout: Any = "default", physical: Optional[dict] = None, layoff: Optional[dict] = None,
               previous_meetings: Optional[list] = None, shared: Optional[dict] = None,
               missing: Optional[list] = None, a_name: str = "Alex Archer", b_name: str = "Ben Brawler") -> dict:
    """The baseline sheet. `a` and `b` are {section: replacement} dicts applied to that fighter's features:
    {"figures": {name: figure}} merges into the figures, anything else replaces the section."""
    fa, fb = fighter_features(a_name, "101"), fighter_features(b_name, "102")
    for feats, change in ((fa, a or {}), (fb, b or {})):
        for key, value in change.items():
            if key == "figures":
                feats["figures"].update(value)
            elif key == "record_update":
                feats["record"].update(value)
            else:
                feats[key] = value
    phys = {"a": physical_side(), "b": physical_side(stance="Southpaw"),
            "differences": {}, "stance_matchup": "Orthodox vs Southpaw", "same_stance": False}
    if physical:
        for key, value in physical.items():
            if key in ("a", "b"):
                phys[key] = dict(phys[key], **value)
            else:
                phys[key] = value
    lay = {"measured_to": "2026-10-10T23:00:00Z", "a_days": 90, "b_days": 90,
           "a_last_fight_utc": "2026-07-12T22:00:00Z", "b_last_fight_utc": "2026-07-12T22:00:00Z",
           "difference_days": 0, "longer_layoff": "equal"}
    lay.update(layoff or {})
    sheet = {
        "a": {"fighter_id": "101", "name": a_name}, "b": {"fighter_id": "102", "name": b_name},
        "as_of": "2026-10-10T23:00:00Z", "as_of_source": "scheduled_bout_start",
        "leakage_rule": "rule", "note": "Facts only.",
        "bout": ({"bout_id": "9101", "event_id": "7013", "event_name": "Night", "date_utc": "2026-10-10T23:00Z",
                  "weight_class": "Welterweight", "scheduled_rounds": 3, "card_segment": "main", "match_number": 1,
                  "description": "3 Rnd", "status": "scheduled", "other_scheduled_bout_ids": []}
                 if bout == "default" else bout),
        "odds": odds_block() if odds == "default" else odds,
        "features": {"a": fa, "b": fb},
        "differentials": {}, "styles": {"a": {"applies": []}, "b": {"applies": []}},
        "shared_opponents": shared or {"a_opponents": 5, "b_opponents": 5, "count": 0, "items": []},
        "previous_meetings": previous_meetings or [],
        "physical": phys, "layoff": lay, "missing": missing or [],
    }
    return sheet

