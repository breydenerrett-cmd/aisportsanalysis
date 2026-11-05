"""The quiz's impact meter: what the answers so far would have done over the last 1, 3 and 7 days of stored boards.

``measure(answers, previous_answers)`` composes the spec the answers make (the same ``compose`` the reveal uses), replays it over
the stored boards through ``drill.impact_windows`` (ONE 7-day pass; the 1 and 3 day windows are slices of it, and the spec before
this answer rides in the same pass), and returns one plain line per window plus the difference this answer made over 7 days.

Read-only and hindsight: nothing is saved, no bet is placed, nothing is counted. A Gematria hound is forward-only, so it gets no
lines and a one-sentence reason. Copy rules: no profit claim, none of the banned words; "paper" is fine.
No FastAPI here: the route is api/hounds_quiz.py.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.interact import drill
from src.hounds.quiz import compose as quiz_compose

WINDOW_LABELS = {1: "Last day", 3: "Last 3 days", 7: "Last 7 days"}
# Replay cost is one scan of the stored boards per sport (about a second each); past this many the meter replays the busiest
# few and says so, so a 7-day answer stays a few seconds (measured 2026-11-05: 17 sports = 18 s, 4 sports = about 4 s).
MAX_SPORTS = 4
SPORT_PRIORITY = ("MLB", "NBA", "NHL", "NFL", "NCAAF", "NCAAB", "WNBA", "SOCCER", "TENNIS", "MMA")
GEMATRIA_NOTE = "A Gematria hound weighs each game once, at the start, so a past day cannot be replayed."


def _signed(value: float, digits: int = 1) -> str:
    text = f"{abs(value):.{digits}f}"
    if float(text) == 0:
        return f"{0:.{digits}f}"
    return ("+" if value > 0 else "-") + text


def window_line(label: str, w: Mapping) -> str:
    bets = int(w.get("bets") or 0)
    if bets == 0:
        return f"{label}: would not have bet"
    wins, losses, pushes = int(w.get("wins") or 0), int(w.get("losses") or 0), int(w.get("pushes") or 0)
    record = f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")
    graded = wins + losses + pushes
    if graded == 0:
        return f"{label}: {bets} {'bet' if bets == 1 else 'bets'}, not settled yet"
    return f"{label}: {bets} {'bet' if bets == 1 else 'bets'}, {record}, {_signed(float(w.get('units') or 0.0))}u"


def delta_of(current: Mapping, previous: Optional[Mapping]) -> Optional[dict]:
    """The 7-day difference between two replays, as numbers and a sentence. None when there is nothing to compare."""
    if previous is None:
        return None
    db = int(current["bets"]) - int(previous["bets"])
    du = round(float(current["units"]) - float(previous["units"]), 2)
    if db == 0 and du == 0:
        line = "this choice: no change over 7 days"
    else:
        line = f"this choice: {db:+d} {'bet' if abs(db) == 1 else 'bets'}, {_signed(du)}u over 7 days"
    return {"bets": db, "units": du, "line": line}


def capped(spec: dict) -> tuple:
    """(spec to replay, note or None): more than MAX_SPORTS sports replays the busiest MAX_SPORTS of them."""
    sports = list(spec.get("sports") or [])
    if len(sports) <= MAX_SPORTS:
        return spec, None
    rank = {s: i for i, s in enumerate(SPORT_PRIORITY)}
    keep = sorted(sports, key=lambda s: (rank.get(s, 99), s))[:MAX_SPORTS]
    keep = [s for s in sports if s in keep]
    rules = []
    for rule in spec.get("rules") or []:
        mine = [s for s in (rule.get("sports") or keep) if s in keep]
        if mine:                                   # a rule's own sports list is what the validator unions back into the spec's
            rules.append({**rule, "sports": mine})
    return {**spec, "sports": keep, "rules": rules or spec.get("rules")}, f"Replayed on {', '.join(keep)} only, to keep this quick."


def _compose_spec(answers: Any, english_draft: Any = None) -> Optional[dict]:
    try:
        return quiz_compose.compose(answers, taken_names=(), english_draft=english_draft).get("spec")
    except user_spec.SpecError:
        return None


def measure(answers: Any, previous_answers: Any = None, *, english_draft: Any = None, now=None, **inject) -> dict:
    """The meter for ``answers``. ``previous_answers`` (the answers before this one) adds the delta line when it composes to a
    different spec. Raises ``drill.DrillError`` (busy, invalid) for the route to word."""
    spec = _compose_spec(answers, english_draft)
    if spec is None:
        return {"available": False, "windows": [], "delta": None, "note": "Those answers do not make a hound yet."}
    if user_spec.is_gematria(spec):
        return {"available": False, "windows": [], "delta": None, "spec_hash": user_spec.spec_hash(spec), "note": GEMATRIA_NOTE}
    spec, cap_note = capped(spec)
    if any(R.market_kind(m) == "prop" for r in spec.get("rules") or [] for m in r.get("markets") or []):
        cap_note = ((cap_note + " ") if cap_note else "") + "Player props are not replayed, so these lines cover game bets only."
    specs = [spec]
    prev_spec = _compose_spec(previous_answers, english_draft) if previous_answers is not None else None
    if prev_spec is not None:
        prev_spec = capped(prev_spec)[0]
    if prev_spec is not None and not user_spec.is_gematria(prev_spec) and user_spec.spec_hash(prev_spec) != user_spec.spec_hash(spec):
        specs.append(prev_spec)
    got = drill.impact_windows(specs, now=now, **inject)
    cur = got[0]
    rows = [{"days": n, **cur[n], "line": window_line(WINDOW_LABELS[n], cur[n])} for n in drill.IMPACT_WINDOWS]
    delta = delta_of(cur[7], got[1][7]) if len(got) > 1 and got[1] else None
    return {"available": True, "spec_hash": user_spec.spec_hash(spec), "windows": rows, "delta": delta,
            "note": (cap_note + " " if cap_note else "") + "Hindsight on stored boards. Paper only, never counted."}
