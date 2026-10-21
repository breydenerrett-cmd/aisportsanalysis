"""One side per game: a hound never holds two positions that can lose together on the same game.

THE BUG THIS CLOSES (2026-10-21, a member's hound)
--------------------------------------------------
A member hound took the 76ers moneyline at +140 AND the Knicks -4.5 at even money on one game. Those are
opposite sides: a Knicks win by 1 to 4 loses both tickets. Nothing was broken in the arithmetic; the engine
simply had no idea two of its own tickets could contradict. ``user_engine_v2.hound_candidates`` de-duplicated
per bet id (hound, event, market key), so one hound with a moneyline rule and a spread rule could take both,
and the hash-chained ledger accepted whatever the engine handed it.

THE RULE (owner-facing: "A hound takes one side per game.")
-----------------------------------------------------------
Per hound, per game:

  * at most ONE side position. Moneyline and spread (the run line and the puck line are spreads) are both
    "side" markets, so a moneyline and a spread on the same team count as one (the second is redundant),
    and a moneyline on one team with a spread on the other is the contradiction itself;
  * at most ONE totals position (never the over and the under);
  * a side and a total on one game are not contradictory. The hound only ever holds both when its own rules
    ask for both markets, because the engine only evaluates markets a rule names;
  * a player prop is its own slot per (player, stat): never the over and the under of one stat for one player.

THE DEAD ZONE (owner clarification, 2026-10-21)
-----------------------------------------------
76ers ML + Knicks -4.5 is the worst pair there is: the two tickets can never both win, and a Knicks win by 1
to 4 loses both. (76ers ML + Knicks +4.5 would at least be a hedge with a middle, where both win.) The rule
still blocks every second side; ``dead_zone`` names the worst kind so the refusal can say so in plain words:
"these two bets could both lose and can never both win". It is a pure function of the two positions.

WHICH ONE SURVIVES
------------------
When several candidates collide, the one that ranks first under the hound's OWN ``rank_by`` is kept
(``keep_first`` is handed the list already in that order). Never the better price after the fact: that
would turn "one side per game" into price shopping, which the picks-not-prices ruling forbids.

TWO LAYERS, ON PURPOSE
----------------------
  1. ``keep_first`` runs inside each engine's selection, so the candidates that reach the writer are already
     consistent and the preview shows what the engine will really do.
  2. ``Book`` is the guard at the point a row is appended. It is built from the rows ALREADY IN THE LEDGER
     for that hound and game, so a second run, a different engine path, or a manual send from Live cannot
     add the opposite side later. The first layer cannot know about yesterday's run; this one can.

WHICH GAME
----------
A game is its event id, its MLB game_pk, or its sport + both teams + exact start instant (``game_aliases``), so
a re-issued event id (the odds feed did it for the 2026-10-15 Guardians at Rays game) cannot start a second,
independent slate of positions. The engine's guard also reads the owner's manual tickets beside the rule
ledger, so a tap on one side stops the engine adding the other, as the engine's ticket stops the tap.

The ledger is append-only. Nothing here edits or deletes a row, so a pair written before this rule existed
stays exactly as it was; the rule holds going forward.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from src.hounds import user_rules

logger = logging.getLogger("linehound.hounds.one_side")

# The moneyline, the point spread, the run line and the puck line all back one team to come out ahead, so
# they share a single slot. The aliases cover the names a feed or an older row may carry.
SIDE_MARKETS = frozenset({"moneyline", "spread", "h2h", "spreads", "run_line", "runline", "puck_line",
                          "puckline", "run line", "puck line"})
TOTAL_MARKETS = frozenset({"total", "totals"})

# Stable codes (the engine counts them in its ``skipped`` tally) and the plain sentences the owner reads.
CODE_OTHER = "one_side_other"
CODE_SAME = "one_side_same"
CODE_DEAD = "one_side_dead_zone"
REASON_OTHER = "already on the other side of this game"
REASON_SAME = "already backing this side of this game"
REASON_DEAD = "these two bets could both lose and can never both win"
REASONS = {CODE_OTHER: REASON_OTHER, CODE_SAME: REASON_SAME, CODE_DEAD: REASON_DEAD}


def slot_of(market: Any, side: Any, player: Any = None) -> Optional[tuple]:
    """(slot, value) a position occupies, or None when the market is not one this rule governs.

    A side position's value is the TEAM (home/away), a total's and a prop's is over/under. Two positions
    in the same slot with the same value are redundant; with different values they contradict."""
    name = str(market or "").strip().lower()
    side_text = str(side or "").strip().lower()
    if not side_text:
        return None
    if name in SIDE_MARKETS:
        return ("side",), side_text
    if name in TOTAL_MARKETS:
        return ("total",), side_text
    if name in user_rules.PROP_MARKETS:
        who = user_rules.fold_player(str(player or "")) if player else ""
        return ("prop", name, who), side_text
    return None


MARGIN_RANGE = 200      # final margins (home minus away) tried by ``dead_zone``; no game goes beyond it


def _margin_rule(market: Any, side: Any, line: Any) -> Optional[tuple]:
    """(sign, threshold) so a side position wins at home-minus-away margin ``x`` when ``sign*(x-threshold) > 0``,
    pushes at 0 and loses below. A spread's ``line`` is the picked team's OWN line (Knicks -4.5 is -4.5), the
    shape every ledger row carries. A moneyline has no line (threshold 0). None when it is not a side bet."""
    name = str(market or "").strip().lower()
    side_text = str(side or "").strip().lower()
    if name not in SIDE_MARKETS or side_text not in ("home", "away"):
        return None
    own = 0.0
    if name not in ("moneyline", "h2h"):
        try:
            own = float(line)
        except (TypeError, ValueError):
            return None
    # home covers when x + own > 0, i.e. x > -own; away covers when -x + own > 0, i.e. x < own
    return (1, -own) if side_text == "home" else (-1, own)


def dead_zone(a: Mapping, b: Mapping) -> bool:
    """True when two side positions on ONE game can never both win AND some final margin loses both.

    ``a`` and ``b`` carry ``market``, ``side`` (home/away) and, for a spread, ``line`` (the picked team's own
    line, as the ledger stores it). Pushes are neither wins nor losses. A pair that overlaps (both win on some
    margin: a middle) is not a dead zone, nor is one team's moneyline plus its own spread; a pair that is not
    two side bets is not judged (False). Pure: no ledger, no clock."""
    left = _margin_rule(a.get("market"), a.get("side"), a.get("line"))
    right = _margin_rule(b.get("market"), b.get("side"), b.get("line"))
    if left is None or right is None:
        return False
    both_lose = False
    for x in range(-MARGIN_RANGE, MARGIN_RANGE + 1):
        d_left = left[0] * (x - left[1])
        d_right = right[0] * (x - right[1])
        if d_left > 0 and d_right > 0:
            return False                      # a middle: they can both win
        if d_left < 0 and d_right < 0:
            both_lose = True
    return both_lose


def check(held: Mapping, market: Any, side: Any, player: Any = None, line: Any = None) -> Optional[str]:
    """The stable refusal code for a candidate against the positions ``held`` ({slot: (value, market, line)}),
    or None. A pair of side bets that is a dead zone gets its own code (and sentence)."""
    placed = slot_of(market, side, player)
    if placed is None:
        return None
    slot, value = placed
    have = held.get(slot)
    if have is None:
        return None
    if slot == ("side",) and dead_zone({"market": have[1], "side": have[0], "line": have[2]},
                                       {"market": market, "side": value, "line": line}):
        return CODE_DEAD
    return CODE_SAME if have[0] == value else CODE_OTHER


def keep_first(ranked: Iterable, describe: Callable[[Any], tuple], *, skipped: Any = None,
               hound_id: str = "", event_of: Optional[Callable[[Any], str]] = None,
               dropped: Optional[list] = None) -> list:
    """The items of ``ranked`` (already in the hound's own rank order) that do not collide.

    ``describe(item)`` -> (event_id, market, side, player[, line]). Per event the first item to claim a slot
    keeps it; a later one in the same slot is dropped and counted in ``skipped`` under its code. Order is
    preserved, so the caller's own daily cap still sees the survivors in rank order. ``dropped`` (a list, when
    given) receives ``(item, code)`` for each one refused, so a caller can say WHY a pick it was asked about is
    not there (the manual pick's "one side per game" reason)."""
    held: dict = {}
    kept: list = []
    for item in ranked:
        event_id, market, side, player, *rest = describe(item)
        line = rest[0] if rest else None
        slots = held.setdefault(event_id, {})
        code = check(slots, market, side, player, line)
        if code is not None:
            if skipped is not None:
                skipped[code] += 1
            if dropped is not None:
                dropped.append((item, code))
            logger.info("hound %s refused %s %s on %s: %s", hound_id or "?", market, side, event_id,
                        REASONS[code])
            continue
        placed = slot_of(market, side, player)
        if placed is not None:
            slots[placed[0]] = (placed[1], market, line)
        kept.append(item)
    return kept


def _team_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _start_text(value: Any) -> str:
    """The start instant as one UTC minute string, or "" when unreadable (so two spellings of one instant agree)."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def game_aliases(event_id: Any, game: Optional[Mapping] = None) -> list:
    """Every name one game can go by, so a re-issued event id does not make it two games.

    ``game`` carries ``sport``, ``home_team``, ``away_team``, ``commence_time`` and ``game_pk`` (a ledger row
    has all five). Three keys, each safe on its own:
      * the event id the odds feed gave it;
      * the MLB ``game_pk`` (a doubleheader's two games have two);
      * the sport, both teams and the exact start instant. Two real games of one pair never start at the same
        instant, so equal teams and start under two ids is one game. The odds feed has re-issued an id for a
        game whose start moved (2026-10-15 Guardians at Rays) and a provider could spell the id another way."""
    keys: list = []
    if event_id:
        keys.append(("event", str(event_id)))
    if game:
        sport = _team_text(game.get("sport"))
        pk = game.get("game_pk")
        if sport == "mlb" and pk not in (None, ""):
            keys.append(("pk", str(pk)))
        home, away = _team_text(game.get("home_team")), _team_text(game.get("away_team"))
        start = _start_text(game.get("commence_time"))
        if sport and home and away and start:
            keys.append(("teams", sport, home, away, start))
    return keys


class Book:
    """The positions every hound already holds, by (hound, game), read from ledger rows.

    Build it once from the ledger the writer is about to append to (``Book.from_rows``), ask ``refusal``
    before each append and ``take`` after it. Rows that are not bets, or that name no event, are ignored.
    A graded or voided bet still counts: the rule is about what the hound put on the game, not about how
    it ended. A game is known by every alias in ``game_aliases``: two event ids that name one game (same
    game_pk, or same teams and start) share one set of positions."""

    BET_KINDS = ("hound_user_bet",)

    def __init__(self) -> None:
        self._group: dict = {}     # (hound, alias) -> group id
        self._slots: dict = {}     # group id -> {slot: (value, market, line)}
        self._next = 0

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping], kinds: Optional[Sequence[str]] = None) -> "Book":
        book = cls()
        wanted = tuple(kinds) if kinds else cls.BET_KINDS
        for row in rows:
            if row.get("kind") in wanted:
                book.take(row)
        return book

    def _groups(self, hound_id: Any, aliases: Sequence) -> list:
        found: list = []
        for alias in aliases:
            gid = self._group.get((hound_id, alias))
            if gid is not None and gid not in found:
                found.append(gid)
        return found

    def take(self, row: Mapping) -> None:
        hound_id, event_id = row.get("hound_id"), row.get("event_id")
        if hound_id is None or event_id is None:
            return
        placed = slot_of(row.get("market"), row.get("side"), row.get("player"))
        if placed is None:
            return
        aliases = game_aliases(event_id, row)
        found = self._groups(hound_id, aliases)
        if found:
            gid = found[0]
            for other in found[1:]:                       # two names for one game: join what each held
                for slot, have in self._slots.pop(other, {}).items():
                    self._slots[gid].setdefault(slot, have)
                for key, owner in list(self._group.items()):
                    if owner == other:
                        self._group[key] = gid
        else:
            gid = self._next
            self._next += 1
            self._slots[gid] = {}
        for alias in aliases:
            self._group[(hound_id, alias)] = gid
        self._slots[gid].setdefault(placed[0], (placed[1], row.get("market"), row.get("line")))

    def held(self, hound_id: str, event_id: str, game: Optional[Mapping] = None) -> dict:
        merged: dict = {}
        for gid in self._groups(hound_id, game_aliases(event_id, game)):
            for slot, have in self._slots[gid].items():
                merged.setdefault(slot, have)
        return merged

    def refusal(self, hound_id: str, event_id: str, market: Any, side: Any, player: Any = None,
                line: Any = None, game: Optional[Mapping] = None) -> Optional[str]:
        """The stable code to refuse with, or None when the position is free to take. ``game`` (sport, teams,
        start, game_pk) lets a second event id of the same game find the positions held under the first."""
        return check(self.held(hound_id, event_id, game), market, side, player, line)

    def refusal_for_row(self, row: Mapping) -> Optional[str]:
        return self.refusal(row.get("hound_id"), row.get("event_id"), row.get("market"), row.get("side"),
                            row.get("player"), row.get("line"), game=row)


def reason_text(code: str) -> str:
    return REASONS.get(code, REASON_OTHER)
