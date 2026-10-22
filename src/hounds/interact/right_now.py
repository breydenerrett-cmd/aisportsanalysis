"""What this hound would play RIGHT NOW: its own rule over the current board, in its own rank order.

READ ONLY, and nothing new is computed about games. This module takes the answer ``fire.fire`` already gives for a hound
(its rule over the newest stored boards, the engine's own checks, the one-side guard and the -200 cap) and lays it out for
the hound page's headline card:

  candidates   the picks that qualify, games not yet started only (a started game is kept only for a hound whose
               "Also bet games in play" setting is on AND only when the engine itself marked the pick in play), best
               first by the hound's OWN ``rank_by``. ``fire_v2`` stamps ``rank_in_day`` in that order; a classic hound or a
               house hound ranks by the earliest game.
  fit          how strongly a candidate fits ITS rule: its place in that order among the games that fit, as a
               percentage (first of 4 reads 100, last of 4 reads 25). It is NOT a win probability, NOT an edge and
               NOT a value estimate; the page labels it "how sure it is" and says what it measures.
  nothing      when nothing fits: the next game the hound will look at and when its placing window opens.
  voice        a key (underdog, chalk, chaos, nerd, steam, mystic, gematria, degen, grinder or generic) read off the
               hound's persona or its own rule, so the page can talk in its voice. A key, never a claim.

A price of -200 or worse never leaves this module, whatever the engine said. Every candidate says it is a paper pick.
Paper only, not advice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.interact import camp, common, fire

MAX_CANDIDATES = 6
CAP = -200                                   # the public cap: -200 or worse is never shown as a pick

VOICES = ("underdog", "chalk", "chaos", "nerd", "steam", "mystic", "gematria", "degen", "grinder", "generic")
VOICE_LABELS = {"underdog": "Underdog hunter", "chalk": "Chalk eater", "chaos": "Chaos agent", "nerd": "Stats nerd",
                "steam": "Steam chaser", "mystic": "Mystic", "gematria": "Letters and numbers", "degen": "Degen",
                "grinder": "Grinder", "generic": "Hound"}
_VIBE_TO_VOICE = {"nerd": "nerd", "chaos": "chaos", "psychic": "mystic", "degen": "degen", "grinder": "grinder"}
_MYSTIC_CONDITIONS = {"numerology", "moon_phase", "name_letter", "name_length"}
_CHAOS_CONDITIONS = {"coin_flip"}
_NERD_CONDITIONS = {"scoring_rate", "league_rank", "matchup_edge", "head_to_head", "venue_record", "split_pct", "last_n_wins",
                    "player_form", "player_rate", "rest_days", "travel_miles"}
RANK_WORDS = {"earliest_lock": "the earliest game", "longest_price": "the longest price", "shortest_price": "the shortest price",
              "most_books": "the most books quoting", "biggest_steam": "the biggest move toward it"}


def _conditions(node: Any) -> list:
    """Every condition id inside a rule's ``when`` tree."""
    out: list = []
    if isinstance(node, Mapping):
        if "items" in node:
            for item in node.get("items") or []:
                out += _conditions(item)
        elif node.get("id"):
            out.append((node.get("id"), node))
    return out


def voice_key(dog: common.Dog, persona: Optional[Mapping] = None) -> str:
    """The hound's voice, read off its persona (a house hound) or its own rule (a builder's hound). Deterministic."""
    vibe = (persona or {}).get("vibe") if isinstance(persona, Mapping) else None
    if vibe in _VIBE_TO_VOICE and dog.kind != common.KIND_USER:
        return _VIBE_TO_VOICE[vibe]
    spec = dog.spec if dog.kind == common.KIND_USER else None
    if not isinstance(spec, Mapping):
        return _VIBE_TO_VOICE.get(vibe, "generic")
    try:
        if user_spec.is_gematria(spec):
            return "gematria"
    except Exception:  # noqa: BLE001 -- a voice never takes the card down
        pass
    rules = spec.get("rules") if isinstance(spec.get("rules"), list) else []
    ids, roles = [], []
    for rule in rules:
        for cid, cond in _conditions(rule.get("when")):
            ids.append(cid)
            if cid == "role":
                roles.append(cond.get("value"))
    rank = spec.get("rank_by")
    side_rule = spec.get("side_rule")                    # a classic (version 1) hound names its side directly
    if side_rule == "underdog":
        roles.append("underdog")
    elif side_rule == "favourite":
        roles.append("favourite")
    elif side_rule in ("market_moved_toward", "market_moved_away"):
        ids.append("steam")
    if _MYSTIC_CONDITIONS & set(ids):
        return "mystic"
    if _CHAOS_CONDITIONS & set(ids):
        return "chaos"
    if rank == "biggest_steam" or "steam" in ids:
        return "steam"
    if rank == "longest_price" or "underdog" in roles:
        return "underdog"
    if rank == "shortest_price" or "favourite" in roles:
        return "chalk"
    if len(_NERD_CONDITIONS & set(ids)) >= 2:
        return "nerd"
    if rules and all(isinstance(r.get("price_min"), (int, float)) and r["price_min"] > 0 for r in rules):
        return "underdog"
    if vibe in _VIBE_TO_VOICE:
        return _VIBE_TO_VOICE[vibe]
    return "generic"


def _persona(dog: common.Dog) -> Optional[dict]:
    try:
        summary = common.summary_json(dog)
    except Exception:  # noqa: BLE001
        return None
    persona = (summary or {}).get("persona")
    return persona if isinstance(persona, dict) else None


def _start(pick: Mapping) -> Optional[datetime]:
    text = str(pick.get("start_utc") or "")
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _price(pick: Mapping) -> Optional[float]:
    value = pick.get("price_average")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def bets_in_play(spec: Optional[Mapping]) -> bool:
    """The hound's "Also bet games in play" setting, read defensively: the field is ``bet_in_play`` (the Unleash fix adds
    it); a build without it, or a hound that never set it, reads as off."""
    return bool(isinstance(spec, Mapping) and spec.get("bet_in_play") is True)


def _lead(rank_by: str, top: Mapping, nxt: Optional[Mapping]) -> str:
    """One plain sentence on why this one is ahead of the next, from the numbers in the two picks. Empty when it is alone."""
    if nxt is None:
        return ""
    fmt = fire._fmt_price
    if rank_by == "longest_price":
        return f"Longest price of the games that fit: {fmt(top['price_average'])} against {fmt(nxt['price_average'])} for the next."
    if rank_by == "shortest_price":
        return f"Shortest price of the games that fit: {fmt(top['price_average'])} against {fmt(nxt['price_average'])} for the next."
    if rank_by == "most_books" and isinstance(top.get("n_books"), int) and isinstance(nxt.get("n_books"), int):
        return f"{top['n_books']} books are quoting it, against {nxt['n_books']} for the next."
    if rank_by == "biggest_steam":
        return "The market has moved toward it more than toward the next one."
    return "It is the earliest game that fits."


def _order(picks: list) -> list:
    """Best first: slate day first, then the hound's own order inside the day, then the start."""
    def key(item):
        index, pick = item
        rank = pick.get("rank_in_day")
        return (str(pick.get("day") or ""), rank if isinstance(rank, int) else 10 ** 6, str(pick.get("start_utc") or ""), index)
    return [p for _i, p in sorted(enumerate(picks), key=key)]


def _next_look(payload: Mapping, spec: Optional[Mapping], now: datetime) -> Optional[dict]:
    """The next game the hound will look at and when its placing window opens (None when it has no upcoming game)."""
    games = [g for g in (payload.get("games") or []) if isinstance(g, Mapping)]
    upcoming = []
    for game in games:
        start = _start(game)
        if start is not None and start > now:
            upcoming.append((start, game))
    if not upcoming:
        return None
    start, game = min(upcoming, key=lambda t: t[0])
    lock = None
    minutes = spec.get("lock_minutes") if isinstance(spec, Mapping) else None
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool):
        lock = start - timedelta(minutes=minutes)
    return {"game": game.get("game"), "event_id": game.get("event_id"), "start_utc": common.iso(start),
            "lock_utc": common.iso(lock) if lock else None,
            "locks_in_minutes": max(0, fire._minutes(lock - now)) if lock else None,
            "starts_in_minutes": fire._minutes(start - now)}


def build(dog: common.Dog, viewer_id: Optional[int] = None, *, now: Optional[datetime] = None,
          payload: Optional[dict] = None) -> dict:
    """The "what I'd play right now" answer for one hound. ``payload`` is the Fire-now answer (injected by tests);
    otherwise it is ``fire.fire(dog)`` decorated for this viewer. Raises ``fire.NotFirable`` for a hound that has no rule to run."""
    now = now or common.now_utc()
    if payload is None:
        payload = camp.decorate_fire(dog, fire.fire(dog, now=now), viewer_id, now=now)
    spec = dog.spec if dog.kind == common.KIND_USER else None
    in_play_on = bets_in_play(spec)
    rank_by = (spec or {}).get("rank_by") if isinstance(spec, Mapping) else None
    rank_by = rank_by if rank_by in RANK_WORDS else "earliest_lock"
    stake = spec.get("stake_units") if isinstance(spec, Mapping) else None
    stake = float(stake) if isinstance(stake, (int, float)) and not isinstance(stake, bool) and stake > 0 else 1.0
    kept = []
    for pick in payload.get("picks") or []:
        price = _price(pick)
        start = _start(pick)
        if price is None or price <= CAP or start is None:
            continue                                            # no price, or -200 or worse: never a "right now" pick
        if start <= now and not (in_play_on and pick.get("in_play") is True):
            continue                                            # a game that has started is not a "not yet started" pick
        kept.append(pick)
    ordered = _order(kept)[:MAX_CANDIDATES]
    total = len(ordered)
    candidates = []
    for index, pick in enumerate(ordered):
        nxt = ordered[index + 1] if index + 1 < total else None
        fit = round(100 * (total - index) / total)
        manual = pick.get("manual") if isinstance(pick.get("manual"), dict) else {"can_record": False, "blocked": None}
        candidates.append({
            "event_id": pick.get("event_id"), "market": pick.get("market"), "market_label": pick.get("market_label"),
            "player": pick.get("player"), "game": pick.get("game"), "sport": pick.get("sport"), "side": pick.get("side"),
            "selection": pick.get("selection"), "line": pick.get("line"), "price_average": pick.get("price_average"),
            "price_best": pick.get("price_best"), "best_book": pick.get("best_book"), "n_books": pick.get("n_books"),
            "start_utc": pick.get("start_utc"), "minutes_to_start": pick.get("minutes_to_start"),
            "day_label": pick.get("day_label"), "stale": bool(pick.get("stale")), "board_age_minutes": pick.get("board_age_minutes"),
            "in_play": bool(pick.get("in_play")), "over_daily_limit": bool(pick.get("over_daily_limit")),
            "stake_units": stake, "rank": index + 1, "of": total, "fit": fit,
            "fit_text": "The top of the board" if index == 0 else f"Number {index + 1} of {total} on its board",
            "lead": _lead(rank_by, pick, nxt) if index == 0 else "", "reason": pick.get("reason") or "",
            "manual": {"can_record": bool(manual.get("can_record")), "blocked": manual.get("blocked")},
        })
    persona = _persona(dog)
    key = voice_key(dog, persona)
    out = {
        "dog_id": dog.id, "dog_name": dog.name, "kind": dog.kind, "as_of": common.iso(now),
        "voice": key, "voice_label": VOICE_LABELS[key],
        "rank_by": rank_by, "rank_words": RANK_WORDS[rank_by],
        "fit_definition": ("How strongly the game fits this hound's own rule, by its place among the games that fit tonight, "
                           f"ranked by {RANK_WORDS[rank_by]}. It is not a chance of winning."),
        "candidates": candidates, "nothing": not candidates, "games_considered": payload.get("games_considered", 0),
        "bets_in_play": in_play_on, "viewer_is_owner": bool(payload.get("viewer_is_owner")),
        "manual_remaining_today": payload.get("manual_remaining_today"),
        "next_look": None if candidates else _next_look(payload, spec, now),
        "next_game": None if candidates else payload.get("next_game"),
        "live_elsewhere": None if candidates else payload.get("live_elsewhere"),
        "paper_only": True,
        "not_advice": "Paper pick, not advice. 21+.",
    }
    return out
