"""The one-line description of a live NHL game or tennis match, for a game card and an open ticket.

    NHL     "2nd · 8:14 · SOG 18-11 · PP WSH"      "1st intermission"      "3rd · 1:12 · SOG 30-22 · empty net NYR"
    TENNIS  "Set 2 · 3-2 · Joint serving · up a break"      "Set 3 · 6-6 · tiebreak · Joint serving"

Numbers are AWAY then HOME, the order a game card lists its two sides (the away side on top) and the order the ticket's own
"Away at Home" game line reads; a power play and an empty net name the TEAM (its abbreviation), so no reader has to know
the order for those. A part whose input is unknown (None) is LEFT OUT, never filled in: a line that says less is a line
that is true. Nothing here implies a bet and nothing in it is a price.

The line is built here, once, and the pages print it verbatim (web/js/live-board.js, web/js/ticket-live.js), so the card,
the strip and the ticket cannot word one game two ways.
"""

from __future__ import annotations

from typing import Mapping, Optional

from src.sports.live_state import names


def nhl_line(state: Mapping) -> Optional[str]:
    """None unless the game is live and its period is known."""
    if state.get("state") != "live":
        return None
    label = state.get("period_label")
    if not label:
        return None
    if state.get("in_intermission"):
        return f"{label} intermission"
    parts = [label]
    if state.get("clock") and state.get("period_type") != "SO":      # a shootout has no running clock to print
        parts.append(state["clock"])
    away, home = state.get("away") or {}, state.get("home") or {}
    if isinstance(away.get("sog"), int) and isinstance(home.get("sog"), int):
        parts.append(f"SOG {away['sog']}-{home['sog']}")
    strength = state.get("strength") or {}
    side = strength.get("pp_side")
    if side in ("home", "away") and (state.get(side) or {}).get("abbrev"):
        parts.append(f"PP {state[side]['abbrev']}")
    empty = strength.get("empty_net")
    if empty in ("home", "away") and (state.get(empty) or {}).get("abbrev"):
        parts.append(f"empty net {state[empty]['abbrev']}")
    return " · ".join(parts)


def _breaks_phrase(state: Mapping) -> Optional[str]:
    """"up a break" when the server leads on breaks, "Rakhimova up a break" when the returner does, "on serve" when level."""
    nb = state.get("net_breaks")
    players = state.get("players") or []
    if not isinstance(nb, Mapping) or len(players) != 2 or not isinstance(nb.get("a"), int):
        return None
    lead = nb["a"]
    if lead == 0:
        return "on serve"
    leader_side = "a" if lead > 0 else "b"
    leader = players[0] if leader_side == "a" else players[1]
    count = abs(lead)
    what = "a break" if count == 1 else f"{count} breaks"
    if state.get("server") == leader_side:
        return f"up {what}"
    return f"{names.last_word_name(leader.get('name'))} up {what}"


def tennis_line(state: Mapping) -> Optional[str]:
    """`state` is an ORIENTED tennis state (``home`` / ``away`` present, see tennis.match)."""
    if state.get("state") != "live" or not isinstance(state.get("set_number"), int):
        return None
    home, away = state.get("home"), state.get("away")
    if not isinstance(home, Mapping) or not isinstance(away, Mapping):
        return None
    parts = [f"Set {state['set_number']}"]
    if isinstance(away.get("games"), int) and isinstance(home.get("games"), int):
        parts.append(f"{away['games']}-{home['games']}")
    if state.get("tiebreak") is True:
        parts.append("tiebreak")
    server = next((p for p in (home, away) if p.get("serving") is True), None)
    if server is not None and server.get("name"):
        parts.append(f"{names.last_word_name(server['name'])} serving")
    phrase = None if state.get("tiebreak") else _breaks_phrase(state)
    if phrase:
        parts.append(phrase)
    sets = (away.get("sets_won"), home.get("sets_won"))
    if all(isinstance(n, int) for n in sets) and (sets[0] or sets[1]):
        parts.append(f"sets {sets[0]}-{sets[1]}")
    return " · ".join(parts)


def line_for(state: Optional[Mapping]) -> Optional[str]:
    if not state:
        return None
    if state.get("sport") == "NHL":
        return nhl_line(state)
    if state.get("sport") == "TENNIS":
        return tennis_line(state)
    return None
