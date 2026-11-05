"""The quiz's "Help me choose" and "Skip": what each question's answer becomes when the member does not pick one.

HELP ME CHOOSE applies what the house pack would use, for the sports already chosen, and the page labels the answer "chosen for you":

  sports        the sport the house pack plays most (config/house_hounds.json: MLB)
  personality   the style that reads the data the chosen sports have: each style is composed on those sports and the one with the fewest
                heads-ups wins (ties keep the library order, so it is deterministic); a sport none of them fit falls back to the first
  risk          the middle risk level (the quiz's own starting point)
  aggression    the same middle level (Describe-it-first's version of risk: bets a day and stake only)
  stats         Hits (the first of the prop stats the quiz offers)
  finish        nothing to pick: the quiz suggests a name and a look

SKIP leaves the question at its default, and the page says what that default is (``skip_label``): sports -> the sports a hound with none
chosen bets (MLB and NFL), personality -> the plain starter, risk -> Balanced.

Pure and offline, like compose: no model, no clock, no randomness. No FastAPI here: the route is api/hounds_quiz.py.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Optional

from src import paths
from src.hounds import user_spec
from src.hounds.quiz import compose as quiz_compose
from src.hounds.quiz import describe as quiz_describe
from src.hounds.quiz import library as lib_mod

STEPS = ("sports", "personality", "risk", "aggression", "stats", "finish")
DEFAULT_RISK = "balanced"
FALLBACK_SPORT = "MLB"
STARTER_LABEL = "a plain starter: underdog moneylines at plus money"


def house_sport() -> str:
    """The sport the most house hounds play (the pack is built on it). Read from the house config; MLB if it cannot be read."""
    try:
        rows = json.loads((Path(paths.repo_root()) / "config" / "house_hounds.json").read_text(encoding="utf-8")).get("hounds") or []
        counts = Counter(str(s).upper() for r in rows for s in (r.get("sports") or []))
        valid = [(n, s) for s, n in counts.items() if s in user_spec.SPORTS]
        if valid:
            return sorted(valid, key=lambda x: (-x[0], x[1]))[0][1]
    except (OSError, ValueError):
        pass
    return FALLBACK_SPORT


def _sports_of(answers: Mapping) -> list:
    raw = answers.get("sports") if isinstance(answers, Mapping) else None
    got = [s for s in (raw or []) if isinstance(s, str)]
    return got or [house_sport()]


def _style_fit(lib: Mapping, personality_id: str, sports: list) -> int:
    """How many heads-ups composing this style on these sports raises (fewer is a better fit)."""
    try:
        out = quiz_compose.compose({"sports": sports, "personality": personality_id, "markets": ["moneyline"]}, taken_names=())
    except user_spec.SpecError:
        return 99
    return sum(1 for w in out.get("warnings") or [] if w.get("level") != "note") + sum(
        1 for w in out.get("warnings") or [] if w.get("code") in ("base_generic", "base_narrowed", "market_unavailable"))


def best_personality(lib: Mapping, sports: list) -> Optional[dict]:
    rows = [p for p in lib.get("personalities") or [] if p.get("style") != "gematria"]
    if not rows:
        return None
    scored = [(_style_fit(lib, p["id"], sports), i, p) for i, p in enumerate(rows)]
    return min(scored, key=lambda x: (x[0], x[1]))[2]


def choose(step: str, answers: Any = None, lib: Optional[Mapping] = None) -> dict:
    """{step, value, label, skip_label}: the value the page applies for "Help me choose" and the words for both buttons."""
    lib = lib or lib_mod.load()
    ans = answers if isinstance(answers, Mapping) else {}
    if step not in STEPS:
        raise ValueError(f"unknown step: {step}")
    if step == "sports":
        sport = house_sport()
        return {"step": step, "value": [sport], "label": lib_mod.sport_label(sport, lib),
                "why": "the sport the house pack plays", "skip_label": "MLB and NFL"}
    if step == "personality":
        sports = _sports_of(ans)
        pick = best_personality(lib, sports)
        name = pick["name"] if pick else ""
        return {"step": step, "value": pick["id"] if pick else None, "label": name,
                "why": f"it reads data {lib_mod.sports_text(sports)} carries", "skip_label": STARTER_LABEL}
    if step in ("risk", "aggression"):
        level = next((r for r in lib.get("risk_levels") or [] if r["id"] == DEFAULT_RISK), None) or (lib.get("risk_levels") or [{}])[0]
        return {"step": step, "value": level.get("id"), "label": level.get("name", ""), "why": "the middle setting",
                "skip_label": level.get("name", "")}
    if step == "stats":
        first = quiz_describe.PROP_STATS[0]
        return {"step": step, "value": [first[0]], "label": first[1], "why": "the stat most players ask for", "skip_label": "no stat picked"}
    return {"step": step, "value": None, "label": "a suggested name and look", "why": "", "skip_label": "a suggested name and look"}
