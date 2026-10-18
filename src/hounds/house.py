"""The house hounds: definitions, and the plain-English rule of a signal system.

TWO CONFIG FILES, BOTH EDITABLE WITHOUT CODE
--------------------------------------------
  config/house_hounds.json  the hounds backed by systems the engine already
                            paper-trades every day (the baselines, the
                            pre-registered signal systems) and the paused
                            public card ("the Old Dog"). Owned here.
  config/house_pack.json    the strategy pack's own definitions (owned by the
                            pack worker); read here, never written.

Each entry: ``id, name, tagline, kind ("house" | "baseline"), category, style,
sports, markets, rule_text``, plus for an engine hound ``system_id`` (the id in
the paper ledgers) and, for a retired static hound, ``retired {date, cause}``
and ``verdict_sentence`` (what the referee says when it cannot measure it).

RULE TEXT MUST BE TRUE. ``genome_rule_text`` generates the plain-English rule
of an evolab signal system directly from its genome and the frozen signal
registry, so the words in the config cannot drift from the thing that actually
decides; ``tests/test_hounds_house.py`` regenerates it and compares. The
baselines' and the Old Dog's text is checked against the code and the paused
decision memo (``docs/decisions/MLB_VALUE_PICKS_PAUSED.md``) by the same test
file's fixtures and by reading ``src.engine.adapters.evolab_system``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.hounds.contract import CATEGORIES, KIND_BASELINE, KIND_HOUSE, KIND_USER

# What each registered signal measures, in the words a person would use. The
# signs are the registry's (frozen before any search): +1 means the side
# holding MORE of the thing is favoured, -1 means the side holding more is
# the one that is hurt.
SIGNAL_WORDS = {
    "lineup_platoon_share": (
        "how much of a posted lineup holds the platoon advantage over the "
        "starter it faces (the side with more of it is favoured)"),
    "lineup_vs_primary_pitch": (
        "how well a lineup has hit the single pitch the opposing starter "
        "throws most (the better-hitting side is favoured)"),
    "primary_pitch_share": (
        "how heavily a starter leans on his one favourite pitch (the side "
        "facing the more predictable starter is favoured)"),
    "top_minus_bottom": (
        "how top-heavy a batting order is (the more top-heavy side is "
        "favoured)"),
    "starter_velocity_gap": (
        "how far a starter's fastball sits above league pace (the side "
        "facing the harder thrower is hurt)"),
    "starter_groundball_share": (
        "how ground-ball-heavy a starter is (the side facing the bigger "
        "ground-ball pitcher is hurt)"),
}
RUNG_WORDS = {0: "a median-sized gap", 1: "a 75th-percentile gap",
              2: "a 90th-percentile gap"}


def genome_rule_text(genome) -> str:
    """The plain-English rule of an evolab ``Genome``, built from the genome.

    Says only what ``src.evolab.decide.decide_with_reason`` does: eligibility
    (markets, minimum books, lineup posted), each signal with its rung and
    weight, the combination rule, the entry gate, and how two disagreeing
    sides are resolved. No claim about results or edge.
    """
    el = genome.eligibility
    market_words = " and ".join(
        {"h2h": "the full-game moneyline",
         "h2h_1st_5_innings": "the first-five-innings moneyline"}.get(m, m)
        for m in genome.routing.market_preference)
    parts = [
        f"Bets {market_words}, one unit, at most one bet a game"
        + (", only once the lineups are posted" if el.require_lineup else "")
        + f", and only when at least {el.min_books} books are quoting it. "
        "It takes the best price on the board."]
    sig_bits = []
    for s in genome.signals:
        words = SIGNAL_WORDS.get(s.feature, s.feature.replace("_", " "))
        weight = ("" if s.weight == 1.0 else
                  (", counted double" if s.weight == 2.0 else f", counted {s.weight:g} times"))
        sig_bits.append(f"{words}, firing at {RUNG_WORDS.get(s.threshold_index, 'a set gap')} "
                        f"between the two teams{weight}")
    n = len(genome.signals)
    parts.append(
        f"It watches {n} pre-registered signal{'s' if n != 1 else ''}, each "
        "with its direction fixed before any results were known: "
        + "; ".join(f"({i}) {b}" for i, b in enumerate(sig_bits, 1)) + ".")
    if genome.combination.rule == "k_of_n":
        gate = (f"It bets a side when at least {genome.combination.k} signals "
                "point at it")
    else:
        gate = (f"Each signal that fires adds its weight to the side it points "
                f"at; it bets a side once that total reaches "
                f"{genome.entry.min_score:g}")
    k = genome.entry.min_confirmations
    gate += (f" and at least {k} signal{'s' if k != 1 else ''} "
             f"{'agree' if k != 1 else 'agrees'}. If both sides qualify the "
             "heavier side is bet, and a tie is no bet.")
    parts.append(gate)
    parts.append("It never uses the price to choose a side.")
    return " ".join(parts)


def load_json(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, (dict, list)) else {}


def _entries(data) -> list:
    if isinstance(data, dict):
        data = data.get("hounds", [])
    if isinstance(data, dict):
        data = [dict(v, id=k) for k, v in data.items()]
    return [e for e in data if isinstance(e, dict) and e.get("id")]


def _norm_category(value, kind) -> str:
    value = str(value or "").lower()
    if value in CATEGORIES:
        return value
    return "baseline" if kind == KIND_BASELINE else "mixed"


def definitions(house_cfg_path, pack_cfg_path, desk_cfg_path=None) -> list:
    """Hound definitions from the config files, in file order.

    A later entry with an id already seen is ignored (the house file wins), so
    the pack file can never silently shadow a house hound. The desk's file
    (config/desk_hounds.json) is the third; its hounds are forward-only (a
    model has no replay), so one with no bet at all reads "not started" with
    its rule text, rather than "benched".
    """
    out, seen = [], set()
    sources = [("house_cfg", house_cfg_path), ("pack_cfg", pack_cfg_path)]
    if desk_cfg_path is not None:
        sources.append(("desk_cfg", desk_cfg_path))
    for source, path in sources:
        for entry in _entries(load_json(path)):
            hid = str(entry["id"])
            if hid in seen:
                continue
            seen.add(hid)
            kind = entry.get("kind") or KIND_HOUSE
            if kind not in (KIND_HOUSE, KIND_USER, KIND_BASELINE):
                kind = KIND_HOUSE
            out.append({
                "id": hid,
                "name": entry.get("name") or hid,
                "tagline": entry.get("tagline") or "",
                "kind": kind,
                "category": _norm_category(entry.get("category"), kind),
                "style": entry.get("style") or "",
                "owner_display": entry.get("owner_display"),
                "sports": list(entry.get("sports") or ["mlb"]),
                "markets": list(entry.get("markets") or []),
                "rule_text": entry.get("rule_text") or "",
                "system_id": entry.get("system_id"),
                "card": bool(entry.get("card")),
                "retired": entry.get("retired"),
                "verdict_sentence": entry.get("verdict_sentence"),
                "source": source,
                "not_started_when_empty": source == "desk_cfg",
            })
    return out


def engine_system_map(defs: list) -> dict:
    """``{system_id: hound_id}`` for the engine-backed definitions."""
    return {d["system_id"]: d["id"] for d in defs
            if d.get("system_id") and not d.get("card")}


def card_hound_id(defs: list) -> Optional[str]:
    for d in defs:
        if d.get("card"):
            return d["id"]
    return None
