"""The live score of a tennis match, read from the free ESPN scoreboard, and the set-start rule.

ESPN lists, per match, the games of every set played so far INCLUDING the one in progress (`linescores`),
a status (`STATUS_IN_PROGRESS` ...) and a `pre` / `in` / `post` state. From that this module derives, with no
guessing:

    completed sets, sets won by each player, the in-progress set's games (None when ESPN has not listed it
    yet), whether the match is decided, and whether the data contradict the format (a player with more sets
    than the format allows, a completed set listed after an unfinished one ...).

A match is at a SET START (a decision point, docs/PREREG_LIVE_TENNIS.md section 6) when it is in progress, at
least one set is completed, nobody has won the match, and the current set is at 0-0 or not yet listed.

ESPN's player order (`a`, `b`) is its own; `orient` maps a pair onto (home, away) as The Odds API names them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

from src.providers import espn_tennis_results as espn

IN_PROGRESS = "STATUS_IN_PROGRESS"


@dataclass(frozen=True)
class LiveState:
    status: str
    state: str                              # ESPN's pre / in / post
    in_progress: bool
    sets: Tuple[Tuple[int, int], ...]       # games (a, b) per set as listed, in order
    completed: int                          # completed sets, counted from the first
    sets_won: Tuple[int, int]               # (a, b), ESPN's order
    current: Optional[Tuple[int, int]]      # games in the set in progress, None when not listed
    sets_to_win: int
    decided: bool
    contradiction: Optional[str]            # None, or why the data cannot be a match of this format

    @property
    def set_number(self) -> int:
        """The set in progress (or about to start): completed sets + 1."""
        return self.completed + 1


def live_state(match: "espn.TennisMatch", sets_to_win: int) -> LiveState:
    sets = tuple((int(a), int(b)) for a, b in match.sets)
    completed, won_a, won_b = 0, 0, 0
    index = 0
    while index < len(sets) and espn.set_completed(*sets[index]):
        a, b = sets[index]
        if a > b:
            won_a += 1
        else:
            won_b += 1
        completed += 1
        index += 1
    rest = sets[index:]
    contradiction = None
    current = rest[0] if len(rest) == 1 else None
    if len(rest) > 1:
        contradiction = "a set is listed after one that is not finished"
    if won_a > sets_to_win or won_b > sets_to_win or (won_a >= sets_to_win and won_b >= sets_to_win):
        contradiction = "more sets won than the format allows"
    if completed > 2 * sets_to_win - 1:
        contradiction = "more sets than the format allows"
    decided = won_a >= sets_to_win or won_b >= sets_to_win
    return LiveState(
        status=match.status, state=match.state, in_progress=(match.status == IN_PROGRESS),
        sets=sets, completed=completed, sets_won=(won_a, won_b), current=current,
        sets_to_win=sets_to_win, decided=decided, contradiction=contradiction)


def is_set_start(state: LiveState, min_set: int = 2) -> bool:
    """In progress, set `min_set` or later is about to be played (the previous one just completed), the new set at 0-0."""
    if not state.in_progress or state.contradiction or state.decided:
        return False
    if state.set_number < min_set:
        return False
    return state.current is None or state.current == (0, 0)


def same_set_start(first: Optional[LiveState], second: Optional[LiveState]) -> bool:
    """True when two reads are the SAME set start: both set starts, the same sets-won score, the same set number."""
    if first is None or second is None:
        return False
    return (is_set_start(first) and is_set_start(second)
            and first.sets_won == second.sets_won and first.set_number == second.set_number)


def orient(pair: Sequence, orientation: str) -> tuple:
    """Map an ESPN (a, b) pair onto (home, away). 'straight': ESPN a is the odds home player; 'crossed': ESPN a is away."""
    a, b = pair
    if orientation == "straight":
        return (a, b)
    if orientation == "crossed":
        return (b, a)
    raise ValueError(f"orientation must be 'straight' or 'crossed', got {orientation!r}")


def to_dict(state: LiveState) -> dict:
    """A JSON-safe copy of a LiveState (stored with every snapshot so the score bracket can be re-checked later)."""
    return {"status": state.status, "state": state.state, "in_progress": state.in_progress,
            "sets": [list(s) for s in state.sets], "completed": state.completed,
            "sets_won": list(state.sets_won), "current": list(state.current) if state.current is not None else None,
            "sets_to_win": state.sets_to_win, "decided": state.decided, "contradiction": state.contradiction}


def from_dict(data: Optional[Mapping]) -> Optional[LiveState]:
    if not data:
        return None
    return LiveState(
        status=data.get("status") or "", state=data.get("state") or "", in_progress=bool(data.get("in_progress")),
        sets=tuple((int(a), int(b)) for a, b in data.get("sets") or []), completed=int(data.get("completed") or 0),
        sets_won=tuple(int(x) for x in (data.get("sets_won") or (0, 0))),
        current=tuple(int(x) for x in data["current"]) if data.get("current") is not None else None,
        sets_to_win=int(data.get("sets_to_win") or 2), decided=bool(data.get("decided")),
        contradiction=data.get("contradiction"))


def possession_map(doc) -> Dict[str, str]:
    """{ESPN match id: 'a' | 'b'} for the competitor ESPN flags `possession` (the server, as best ESPN says).

    Recorded in the ledger and NEVER used by the rule (docs/PREREG_LIVE_TENNIS.md section 4.5): the model
    averages the two possible first servers.
    """
    out: Dict[str, str] = {}
    if not isinstance(doc, Mapping):
        return out
    for event in doc.get("events") or []:
        for group in (event or {}).get("groupings") or []:
            for comp in (group or {}).get("competitions") or []:
                if not isinstance(comp, Mapping):
                    continue
                flagged = [c for c in comp.get("competitors") or [] if isinstance(c, Mapping) and c.get("possession") is True]
                if len(flagged) == 1 and str(comp.get("id") or ""):
                    order = flagged[0].get("order")
                    if order in (1, 2):
                        out[str(comp["id"])] = "a" if order == 1 else "b"
    return out
