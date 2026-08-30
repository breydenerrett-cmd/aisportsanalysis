"""Roster news, stored append-only and attached to games point-in-time.

WHAT THIS ADDS TO A BRIEFING
-----------------------------
Everything else in the system describes a steady state: how this pitcher has
thrown all season, how this lineup hits that pitch. News is the opposite -- it
is what CHANGED, and change is where a price is most likely to be behind.

"Cincinnati placed 3B Ke'Bryan Hayes on the 10-day injured list. Left groin
strain." That is one line, it is free, it is dated, and it is exactly the kind
of thing a casual bettor misses and a sharp one already knows.

THE CUTOFF IS A ROW FILTER, NOT A PROMISE
------------------------------------------
Every stored item carries the date it took effect. Attaching news to a game is
therefore a comparison between two dates, and a transaction filed after first
pitch cannot reach a game no matter how the caller asks. This is the same
property the rebuilt pitch store has and the same one the stats endpoints
turned out to lack.

WINDOW, AND WHY IT IS SHORT
---------------------------
Ten days. A move from three weeks ago is roster history rather than news, and
listing it under "what changed" trains the reader to skim the section. An
injured-list placement that still matters will usually be reflected in the
lineup by then anyway.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from src.providers import mlb_news

DEFAULT_STORE = Path("data/historical/transactions.jsonl")

# How far back a move stays "news" for a given game.
WINDOW_DAYS = 10

# Most items a game card shows per team before it stops being readable.
MAX_PER_TEAM = 4


class NewsStoreError(RuntimeError):
    """Raised when the news store cannot be read or written."""


def read(store=DEFAULT_STORE) -> list:
    """Every stored transaction, oldest first. Missing file is empty, not an error."""
    target = Path(store)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # One corrupt line costs one transaction, not the whole file. That
            # is the entire reason this is JSON Lines.
            continue
    rows.sort(key=lambda r: (r.get("date") or "", r.get("transaction_id") or 0))
    return rows


def stored_ids(store=DEFAULT_STORE) -> set:
    return {r.get("transaction_id") for r in read(store)}


def ingest(start_date, end_date=None, store=DEFAULT_STORE) -> dict:
    """Fetch a date range and append anything not already stored.

    Deduplicated by MLB's own transaction id, so re-running a range that
    overlaps what is on disk is safe and cheap. The feed genuinely repeats some
    moves across days, and an append-only store with no key would accumulate
    them forever.
    """
    target = Path(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    known = stored_ids(store)

    rows = mlb_news.fetch(start_date, end_date)
    written = 0
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            if row.get("transaction_id") in known:
                continue
            known.add(row.get("transaction_id"))
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            written += 1

    return {"fetched": len(rows), "written": written,
            "skipped_duplicate": len(rows) - written, "store": str(target)}


def _date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def for_team(rows, team, on_date, window_days=WINDOW_DAYS,
             categories=mlb_news.NOTABLE) -> list:
    """Notable moves for one club in the window BEFORE a date.

    Strictly before: a transaction dated the day of the game is included only if
    the caller wants it, and by default it is not, because MLB dates a move by
    the day it took effect rather than the minute it was announced. Treating a
    same-day move as known before first pitch would be a guess dressed as a
    fact, and the whole point of this store is that it does not guess.
    """
    target = _date(on_date)
    if target is None:
        return []
    earliest = target - dt.timedelta(days=window_days)

    out = []
    seen = set()
    for row in rows:
        if row.get("team") != team:
            continue
        if categories is not None and row.get("category") not in categories:
            continue
        when = _date(row.get("date"))
        if when is None or not (earliest <= when < target):
            continue
        # The feed repeats some moves under separate ids. One player, one
        # category, one date is one piece of news to a reader.
        key = (row.get("player_id"), row.get("category"), row.get("date"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)

    out.sort(key=lambda r: r.get("date") or "", reverse=True)
    return out[:MAX_PER_TEAM]


def sentence(row) -> str:
    """One readable line for a move, without MLB's boilerplate.

    MLB's own description is already a decent sentence, so this mostly trims it
    and appends the diagnosis when there is one. Rewriting it wholesale would
    risk saying something the feed did not.
    """
    text = (row.get("description") or "").strip()
    if not text:
        player = row.get("player") or "A player"
        return f"{player}: {row.get('category', 'roster move').replace('_', ' ')}."
    # Strip the retroactive clause, which is administrative detail.
    for marker in (" retroactive to ",):
        index = text.lower().find(marker)
        if index > 0:
            tail = text[index:]
            stop = tail.find(".")
            text = text[:index] + (tail[stop:] if stop >= 0 else "")
    return " ".join(text.split())


def _teams_of(game):
    """(away, home) from either a Dossier-style object or a raw game dict.

    The briefing passes raw MLB game records and the detectors pass dossiers.
    Supporting both here keeps the caller from having to know which it holds.
    """
    teams = getattr(game, "teams", None)
    if teams:
        return teams[0], teams[1]
    if isinstance(game, dict):
        pair = game.get("teams")
        if pair:
            return pair[0], pair[1]
        return game.get("away_team"), game.get("home_team")
    return None, None


def attach(game, rows, on_date, window_days=WINDOW_DAYS) -> dict:
    """News section for one game: {team_abbrev: [row, ...]}, plus a reason when empty."""
    away, home = _teams_of(game)
    section = {}
    for team in (away, home):
        if not team:
            continue
        section[team] = [dict(row, sentence=sentence(row))
                         for row in for_team(rows, team, on_date, window_days)]
    if not any(section.values()):
        return {"teams": section, "reason": (
            f"no injured-list moves, call-ups or trades for either club in the "
            f"last {window_days} days")}
    return {"teams": section, "reason": None}
