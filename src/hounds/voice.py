"""The kennel's voice, in Python: the badges, the Houndmaster's daily line, and nothing else.

NOT RENDERED BY THE SITE (2026-10-19). The professional pass (docs/VOICE.md) removed the badges, the
roasts and the brags from the web pages; the leaderboard and the model page print plain status words
(web/js/hounds-board.js statusOf). This module is kept, with its tests, as voice data for a future Discord
or X post. Presentation only: nothing here touches a rule, the referee, a verdict or a result.
"""

from __future__ import annotations

from typing import Optional

#: verdict label (src.hounds.verdict.LABELS) -> (key, word, emoji, one-line plain explanation)
BADGES: dict = {
    "BEATING THE CLOSE": ("sharp", "SHARP", "\U0001F525",
                          "Its prices keep beating where the market closes. Good shopping, not a promise of wins."),
    "NO DIFFERENT FROM THE MARKET": ("coin_flip", "COIN FLIP", "\U0001FA99",
                                     "Its prices look just like the closing line: no better, no worse. A coin flip, so far."),
    "PAYING THE VIG": ("feeding_the_book", "FEEDING THE BOOK", "\U0001F4B8",
                       "Its prices keep landing worse than the close. Every bet costs it a little extra."),
    "TOO EARLY": ("rookie", "ROOKIE", "\U0001F423",
                  "Too few bets to judge. Wins and losses this early are mostly luck."),
}
UNRATED = ("unrated", "UNRATED", "\U0001F43E", "This one was never graded against the closing line.")

#: a dog down this many units is put down (src.hounds.verdict.RETIRE_UNITS_BELOW)
RETIRE_UNITS = -25.0


def badge_for(label: Optional[str]) -> dict:
    """The badge a verdict label wears: ``{key, word, emoji, text, explain}``."""
    key, word, emoji, explain = BADGES.get(str(label or "").strip().upper(), UNRATED)
    return {"key": key, "word": word, "emoji": emoji, "text": f"{word} {emoji}", "explain": explain}


def fnv1a(text: str) -> int:
    """32-bit FNV-1a over the UTF-16 code units of ``text`` (what JavaScript's charCodeAt sees)."""
    h = 0x811C9DC5
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def pick_line(lines: list, key: str, day: str) -> Optional[str]:
    """One line from ``lines``, chosen by the dog (``key``) and the day: the same dog on the same day
    always gets the same line, on every page and every reload, and tomorrow it can change."""
    if not lines:
        return None
    return lines[fnv1a(f"{key}|{day}") % len(lines)]


def houndmaster_line(hound_id: str, persona: Optional[dict], last_day: Optional[dict],
                     houndmaster: Optional[dict]) -> Optional[dict]:
    """The Houndmaster's line for a dog after its last settled day: a roast after a losing day, a brag
    after a winning one, nothing for a flat day or no day. The dog's own lines first, the boss's generic
    ones when the dog has none (a builder's dog)."""
    if not last_day or last_day.get("result") not in ("win", "loss"):
        return None
    kind = "brag" if last_day["result"] == "win" else "roast"
    field = "brags" if kind == "brag" else "roasts"
    lines = (persona or {}).get(field) or (houndmaster or {}).get(field) or []
    line = pick_line(list(lines), hound_id, str(last_day.get("date") or ""))
    return {"kind": kind, "line": line, "day": last_day.get("date")} if line else None
