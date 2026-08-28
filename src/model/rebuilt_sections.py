"""Dossier sections for past games, built from the rebuilt pitch-level store.

WHY THIS MODULE EXISTS
----------------------
Four detectors -- platoon_mismatch, pitch_mix_mismatch, thin_matchup_history,
lineup_vs_starter -- were excluded from every historical evaluation because
their live sources (statSplits, the Savant leaderboards, vsPlayer) answer only
"season to date" and leak the future into any earlier game. The rebuilt
accumulations answer "as of a cutoff" honestly, but they arrive shaped as raw
tuple-keyed counters. This module reshapes them into the EXACT sections those
detectors already read, so the detectors themselves run unchanged on 2023-24
games and a historical finding is produced by the same code as a live one.

THE SHAPES ARE THE LIVE SHAPES, THE NUMBERS ARE POINT-IN-TIME
-------------------------------------------------------------
Section layouts mirror briefing._lineup_section / _arsenal_section and the
live splits/matchup sections field for field, with one declared difference:
the rebuilt platoon split is wOBA-scale rather than OPS-scale, and says so via
a "metric" field so the detector can gate on the right threshold. Sample gates
are shared with the live twins by importing their constants -- a rebuilt
feature that gated differently would make historical and forward results
incomparable.

SIDES CROSS OVER, ONCE, HERE
----------------------------
A lineup's platoon composition, pitch-type read and matchup history are only
meaningful against the OPPOSING starter, so the away lineup is paired with
home_probable_id and vice versa -- the same crossing briefing.py performs live.
Getting this wrong produces a confident, precisely wrong number on every game,
which is why it happens in exactly one place per path.
"""

from __future__ import annotations

from src.pipeline import lineups as lineup_mod
from src.pipeline import rebuilt


def sections_for_game(acc, game, posted_lineup, handedness) -> tuple:
    """The four rebuilt dossier sections for one past game.

    Returns (sections, reasons): `sections` maps section name to data in the
    live shape, `reasons` names each section that could NOT be built and why,
    so a historical dossier can record the gap rather than silently omit it.
    """
    handedness = handedness or {}
    sections, reasons = {}, {}

    # -- splits and arsenals: each side's OWN starter -----------------------
    splits, arsenals = {}, {}
    for side, key in (("away", "away_probable_id"), ("home", "home_probable_id")):
        pitcher_id = game.get(key)
        if not pitcher_id:
            continue
        split = rebuilt.platoon_split(acc, pitcher_id)
        # Declared so the detector applies the wOBA-scale gap threshold, not
        # the OPS one -- the numbers live on different scales.
        split["metric"] = "woba"
        splits[side] = {"platoon": split}
        rows = _arsenal_rows(acc, pitcher_id)
        if rows:
            arsenals[side] = rows

    if splits:
        sections["splits"] = splits
    else:
        reasons["splits"] = "no probable starter on either side"
    if arsenals:
        sections["arsenals"] = arsenals
    else:
        reasons["arsenals"] = ("no probable starter with enough pitches "
                               "before the cutoff")

    # -- lineups and matchup history: each lineup vs the OPPOSING starter ---
    lineups_section, matchup_section = {}, {}
    for side, opposing_key in (("away", "home_probable_id"),
                               ("home", "away_probable_id")):
        slots = (posted_lineup or {}).get(side) or []
        if not slots:
            continue
        pitcher_id = game.get(opposing_key)
        throws = (handedness.get(str(pitcher_id)) or {}).get("throws")
        lineups_section[side] = {
            "batters": slots,
            "handedness": lineup_mod.lineup_handedness(slots, handedness),
            "platoon_advantage": lineup_mod.platoon_advantage_share(
                slots, handedness, throws),
            "faces_starter_throwing": throws,
            "vs_pitch": _vs_pitch(acc, slots, pitcher_id),
        }
        matchup_section[side] = _lineup_vs_pitcher(acc, slots, pitcher_id)

    if lineups_section:
        sections["lineups"] = lineups_section
    else:
        reasons["lineups"] = "no posted lineup stored for this game"
    if matchup_section:
        sections["matchup_history"] = matchup_section
    else:
        reasons["matchup_history"] = "no posted lineup stored for this game"

    return sections, reasons


def _arsenal_rows(acc, pitcher_id) -> list:
    """The starter's arsenal in the live leaderboard row shape, usage first.

    pitch_mix already applies the shared 50-pitch floor and sorts by usage.
    The per-pitch feed carries no display name, so pitch_name falls back to
    the type code rather than inventing one.
    """
    slots = acc["arsenal"].get(str(pitcher_id)) or {}
    return [{"pitch_type": row["pitch_type"],
             "pitch_name": row["pitch_type"],
             "pitch_usage": row["usage_pct"],
             "woba": row["woba"],
             "pa": (slots.get(row["pitch_type"]) or {}).get("denom", 0)}
            for row in rebuilt.pitch_mix(acc, pitcher_id)]


def _vs_pitch(acc, slots, pitcher_id) -> dict:
    """Each posted hitter's line against each pitch the opposing starter throws.

    Grouped by pitch type, matching briefing._lineup_vs_pitch. A hitter with
    zero plate appearances against a pitch has no line and gets no row, so the
    detector's minimum-hitters gate counts hitters with evidence, not slots.
    """
    grouped = {}
    if not pitcher_id:
        return grouped
    for row in rebuilt.pitch_mix(acc, str(pitcher_id)):
        pitch_type = row["pitch_type"]
        for slot in slots:
            line = rebuilt.batter_vs_pitch_type(
                acc, slot.get("person_id"), pitch_type)
            if not line["pa"]:
                continue
            grouped.setdefault(pitch_type, []).append(
                {"batter": slot.get("name"), "pitch_type": pitch_type,
                 "woba": line["woba"], "pa": line["pa"]})
    return grouped


def _lineup_vs_pitcher(acc, slots, pitcher_id) -> dict:
    """Every posted hitter against the opposing starter, plus the aggregate.

    Same shape and same usable gate as lineups.lineup_vs_pitcher -- the shared
    MIN_LINEUP_AT_BATS constant, imported rather than restated, so the rebuilt
    section can never drift from its live twin.
    """
    if not pitcher_id:
        return {"batters": [], "total_at_bats": 0, "total_hits": 0,
                "total_strikeouts": 0, "aggregate_avg": None, "usable": False,
                "reason": "the opposing probable starter is unknown"}

    entries, total_ab, total_hits, total_k = [], 0, 0, 0
    for slot in slots:
        person_id = slot.get("person_id")
        if not person_id:
            continue
        line = rebuilt.batter_vs_pitcher(acc, person_id, pitcher_id)
        entries.append({"name": slot.get("name"), "order": slot.get("order"),
                        "person_id": person_id, **line})
        total_ab += line["at_bats"]
        total_hits += line["hits"]
        total_k += line["strikeouts"]

    usable = total_ab >= lineup_mod.MIN_LINEUP_AT_BATS
    return {
        "batters": entries,
        "total_at_bats": total_ab,
        "total_hits": total_hits,
        "total_strikeouts": total_k,
        "aggregate_avg": round(total_hits / total_ab, 3) if total_ab else None,
        "usable": usable,
        "reason": None if usable else (
            f"the whole lineup has only {total_ab} career at-bats against him "
            f"before the cutoff; a read needs at least "
            f"{lineup_mod.MIN_LINEUP_AT_BATS}"),
    }
