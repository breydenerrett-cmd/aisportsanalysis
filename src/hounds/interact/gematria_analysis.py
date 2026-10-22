"""The Gematria hound's visible analysis: the REAL work it did on today's games, as lines a page can play.

THE STORY (owner, 2026-10-22). A member's Gematria hound answered Unleash in about 30 seconds of the person waiting and nothing
else. "A real gematria hound should take longer to think and analyze games ... the analysis should feel deep and real." The
engine already does that work on every game (``src/hounds/gematria``): it computes four cipher values for every name, builds the
numbers of the date, searches thousands of coincidences per game and scores both sides. It just never showed any of it. This module
returns that work, game by game, so the page can stream it the way the training diagnosis screen streams its checks
(web/js/dog-diagnose.js, web/js/dog-gematria-stream.js).

NOTHING HERE IS INVENTED. Every line is formatted from a value the engine computed in this call: ``gematria.values`` for the ciphers,
``Signals`` for the matches, scores, margin and noise, the ``Verdict`` for the pick or the pass and its reason. A game the engine could
not weigh (no board, started) is simply absent; a game with no match on a side says "no match found" because that is what was computed.
The page may pace the lines (that is staging, not work) but adds none.

WHICH GAMES. All of the hound's games that have not started, weighed NOW on the newest board and on results stored by now, exactly as
Unleash weighs them (``user_gematria.Weigher.weigh``, ``as_of`` now). The payload is CAPPED at ``MAX_GAMES``: the engine's picks
first (strongest case first), then the passes that came closest, so it stays small however long the day is. ``weighed`` says how many
games were weighed in all.

Read only. Writes nothing, places nothing, claims nothing: the copy the page prints under it says the hound is experimental numerology.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable, List, Mapping, Optional

from src.hounds import ai_defs, user_gematria
from src.hounds.gematria import EXPERIMENTAL_LINE
from src.hounds.gematria import signals as sig_mod
from src.hounds.interact import common, fire
from src.research import gematria

MAX_GAMES = 12                  # the most games a payload carries
MAX_NAME_TEXTS = 3              # the most name fields (team, city, mascot ...) whose ciphers are printed per side
MAX_MATCHES = 3                 # the most matches printed per side (the full list is on the hound's page for a pick)
TTL_S = 45.0                    # a repeat of the same call inside this is served from memory

_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 8


class NotGematria(ValueError):
    pass


def is_gematria_dog(dog: Optional[common.Dog]) -> bool:
    """A member hound with the Gematria style, or the house Gematria Hound (config family ``gematria``)."""
    if dog is None:
        return False
    if dog.kind == common.KIND_USER:
        return bool(dog.spec) and user_gematria.is_gematria(dog.spec)
    entry = ai_defs.entry_for(dog.id) if isinstance(dog.id, str) else None
    return bool(entry) and entry.get("family") == "gematria"


def _sports_of(dog: common.Dog) -> tuple:
    if dog.kind == common.KIND_USER:
        return tuple(dog.spec["sports"])
    return tuple(s.upper() for s in ai_defs.resolve_sports(ai_defs.entry_for(dog.id) or {}))     # the boards name sports in capitals


def _lock_minutes(dog: common.Dog, runtime) -> int:
    return int(dog.spec["lock_minutes"]) if dog.kind == common.KIND_USER else int(runtime.rules.decision.lock_minutes)


def _price(p) -> str:
    return f"{p:+d}" if isinstance(p, int) else str(p)


def match_text(e: sig_mod.Evidence) -> str:
    """One match as a line: the number they share, the two things that equal it and the weight the rules give the match."""
    parts = [e.a.label] + ([e.b.label] if e.b is not None else [])
    if e.note:
        parts.append(e.note)
    return f"{e.value}: " + " · ".join(parts) + f" (+{e.weight:g})"


def cipher_lines(g: sig_mod.GameInputs, runtime, side: str, team_name: str) -> List[dict]:
    """The cipher values of this side's names, computed now, one line per name field (team, city, mascot ...)."""
    out = []
    for field, text in g.team(side).team.name_texts()[:MAX_NAME_TEXTS]:
        vals = gematria.values(text, runtime.rules.ciphers)
        out.append({"kind": "cipher", "side": side, "field": field, "text": f"{text}: " + " · ".join(f"{c} {vals[c]}" for c in runtime.rules.ciphers),
                    "values": {c: vals[c] for c in runtime.rules.ciphers}})
    return out


def game_entry(ctx, w, runtime) -> dict:
    """One game's analysis from the engine's own ``Weighed``."""
    v, sig, g = w.verdict, w.signals, w.inputs
    names = {"home": ctx.home_name, "away": ctx.away_name}
    lines: List[dict] = []
    if g is not None and sig is not None:
        for side in ("away", "home"):
            lines.extend(cipher_lines(g, runtime, side, names[side]))
        basis_text = ("season counts and static numbers" if sig.basis == "season"
                      else "static numbers only (names, date, founding spans); this sport has no stored counts yet")
        lines.append({"kind": "basis", "side": None, "text": f"Reading {basis_text}", "basis": sig.basis})
        for side in ("away", "home"):
            ev = sig.side(side).evidence
            if not ev:
                lines.append({"kind": "match", "side": side, "text": f"{names[side]}: no match found in {sig.side(side).comparisons} comparisons",
                              "none": True})
            for e in ev[:MAX_MATCHES]:
                lines.append({"kind": "match", "side": side, "text": f"{names[side]}: {match_text(e)}", "value": e.value,
                              "weight": round(e.weight, 3), "evidence_kind": e.kind})
        lines.append({"kind": "score", "side": None,
                      "text": (f"{names['away']} {sig.away.score:g} against {names['home']} {sig.home.score:g}; margin {abs(sig.margin):g}, "
                               f"{sig.z:.2f} times the noise ({sig.noise_sd:g}); searched {sig.away.comparisons} and {sig.home.comparisons} comparisons"),
                      "scores": {"home": sig.home.score, "away": sig.away.score}, "margin": sig.margin, "z": sig.z})
    if v.is_bet:
        pick_name = names[v.side]
        led = (f" {pick_name} leads the count {sig.side(v.side).score:g} to {sig.side(sig_mod.other(v.side)).score:g} (margin {abs(v.margin):g})."
               if sig is not None else "")
        lines.append({"kind": "decision", "side": v.side, "status": "bet", "text": f"Pick: {pick_name} to win at {_price(v.price)}.{led}"})
    else:
        lines.append({"kind": "decision", "side": None, "status": "pass", "code": v.code, "text": f"Pass: {v.reason}"})
    return {
        "event_id": ctx.event_id, "sport": ctx.sport, "game": f"{ctx.away_name} @ {ctx.home_name}",
        "start_utc": common.iso(ctx.start), "start_et": fire.clock_et(ctx.start),
        "basis": sig.basis if sig is not None else None, "status": "bet" if v.is_bet else "pass", "code": v.code,
        "side": v.side, "price": v.price, "z": v.z, "margin": v.margin,
        "scores": ({"home": sig.home.score, "away": sig.away.score} if sig is not None else None),
        "comparisons": ({"home": sig.home.comparisons, "away": sig.away.comparisons} if sig is not None else None),
        "lines": lines,
    }


def _rank_key(item: tuple):
    """Picks first (the strongest case first), then the passes that came closest; ties by start then id so a repeat is identical."""
    entry = item[1]
    return (0 if entry["status"] == "bet" else 1, -float(entry["z"] or 0.0), entry["start_utc"], entry["event_id"])


def build(dog: common.Dog, *, now: Optional[datetime] = None, games: Optional[Mapping] = None, runtime=None,
          limit: int = MAX_GAMES, use_cache: bool = True) -> dict:
    """The analysis payload for a Gematria hound, now.

    ``games`` ({event_id: GameBoards}) and ``runtime`` are the injection points; production reads the cached boards of the hound's sports
    (``fire.cached_games``) and the house ``GematriaRuntime`` with no ledger."""
    if not is_gematria_dog(dog):
        raise NotGematria("this hound is not a Gematria hound")
    now = now or common.now_utc()
    inject = games is not None or runtime is not None
    key = (dog.id, int(now.timestamp() // TTL_S))
    if use_cache and not inject:
        with _cache_lock:
            hit = _cache.get(key)
        if hit is not None:
            return hit
    sports = _sports_of(dog)
    if games is None:
        games = fire.cached_games(sports, now)
    runtime = runtime or user_gematria.make_runtime()
    weigher = user_gematria.Weigher(games, runtime=runtime)
    lock_minutes = _lock_minutes(dog, runtime)
    weighed: List[tuple] = []
    with fire._heavy():                  # the same process-wide gate Unleash weighs under (result stores are read for MLB / NFL)
        for event_id, game in sorted(games.items()):
            if game.sport not in sports or game.commence is None or game.commence <= now:
                continue
            lock = game.commence - timedelta(minutes=lock_minutes)
            got = weigher.weigh(event_id, as_of=now if now < lock else None)
            if got is None:
                continue
            ctx, _board, w = got
            if w.signals is None and not w.verdict.is_bet and w.verdict.code in ("no_history", "no_facts"):
                continue                 # nothing was computed for it (rules v1 on a sport with no stored results): nothing to show
            weighed.append((ctx, game_entry(ctx, w, runtime), w))
    ordered = sorted(((c, e) for c, e, _w in weighed), key=_rank_key)
    shown = [e for _c, e in ordered[:max(0, limit)]]
    rules = runtime.rules
    out = {
        "dog_id": dog.id, "as_of": common.iso(now), "weighed": len(weighed), "shown": len(shown), "capped": len(weighed) > len(shown),
        "picks": sum(1 for e in shown if e["status"] == "bet"), "picks_total": sum(1 for _c, e, _w in weighed if e["status"] == "bet"),
        "games": shown,
        "rules": {"version": rules.version, "hound_version": rules.hound_version, "rules_hash": rules.rules_hash},
        "date_numbers": _date_line(now),
        "copy": EXPERIMENTAL_LINE, "paper_only": True,
    }
    if use_cache and not inject:
        with _cache_lock:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[key] = out
    return out


def _date_line(now: datetime) -> dict:
    """The numbers of the Eastern calendar date the games are read against (printed once, before the first game)."""
    date = common.eastern_date(now)
    nums = gematria.date_numbers(date)
    text = f"Date {date}: " + " · ".join(f"{k} {nums[k]}" for k in ("md_yy", "md_20yy", "digits", "doy", "doy_left", "root"))
    return {"date": date, "text": text, "values": {k: nums[k] for k in ("md_yy", "md_20yy", "digits", "doy", "doy_left", "root")}}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
