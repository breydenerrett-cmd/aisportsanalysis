"""The forward ledger: what the system knew, at the moment it knew it.

WHY THIS IS THE ONLY EVIDENCE THAT WILL EVER COUNT
--------------------------------------------------
Every historical evaluation in this project rests on discipline that can fail --
a season-to-date split slipped into a past date, a threshold nudged after a
disappointing number, a split looked at twice. Games that have not been played
cannot be peeked at by anyone, including by accident.

So the ledger records a recommendation BEFORE first pitch, with the information
that produced it, and settles it afterwards against a closing price and a result
that were unknowable at the time. Nothing else in this repository has that
property.

APPEND-ONLY, AND THE SETTLEMENT NEVER TOUCHES THE RECOMMENDATION
----------------------------------------------------------------
Entries are appended and never modified. Settlement is written as separate
fields on a separate line keyed to the same entry, so a recommendation that aged
badly stays on the record exactly as it was made. A file that can be edited
after the fact is a draft, not evidence.

WHAT "WHAT IT KNEW" ACTUALLY MEANS
----------------------------------
Not just the verdict. A verdict alone cannot be audited later: if the ledger
says "no play" it must be possible to ask WHY, and to tell "the price was
already blown out" from "there was no price" from "the lineup had not posted".
So each entry carries the detector outputs, the lineup status, every book and
price on the board, and the information time -- and `information_time` is the
moment the inputs were gathered, not the moment the file was written, because a
run that takes four minutes must not claim four minutes of hindsight.

WHY EVERY GAME IS RECORDED, NOT JUST THE PICKS
-----------------------------------------------
A ledger of only the recommendations cannot answer "how often did it decline",
and a strategy whose whole point is skipping most days is not describable
without the days it skipped. No-play and market-unavailable are entries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.paths import evidence_path

DEFAULT_LEDGER = evidence_path("forward_ledger.jsonl")

RECOMMENDATION = "recommendation"
SETTLEMENT = "settlement"


class LedgerError(RuntimeError):
    """Raised when the ledger cannot be written or read."""


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_slate(slate, path=DEFAULT_LEDGER, recorded_at=None,
                 information_time=None) -> dict:
    """Append one entry per game. Returns what was written."""
    stamp = _iso(recorded_at)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    for game in slate.get("games", []):
        entries.append(_entry(game, slate.get("date"), stamp, information_time))

    with target.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    verdicts = {}
    for entry in entries:
        verdicts[entry["verdict"]] = verdicts.get(entry["verdict"], 0) + 1
    return {"recorded": len(entries), "verdicts": verdicts, "path": str(target),
            "recorded_at": stamp}


def _entry(game, game_date, stamp, information_time) -> dict:
    dossier = game["dossier"]
    market = dossier.get("market") or {}
    lineups = dossier.get("lineups") or {}

    return {
        "kind": RECOMMENDATION,
        "recorded_at": stamp,
        # The moment the INPUTS were gathered. A run takes minutes, and claiming
        # the write time would quietly grant the ledger those minutes of
        # hindsight on every entry.
        "information_time": (information_time
                             or dossier.information_time.isoformat()),
        "date": game_date,
        "game_pk": dossier.game.get("game_pk"),
        "away_team": dossier.game.get("away_team"),
        "home_team": dossier.game.get("home_team"),
        "commence_time": dossier.game.get("start_time_utc"),
        "verdict": game.get("verdict"),
        "side": game.get("side"),
        "market": game.get("market"),
        "summary": game.get("summary"),
        # Every book on the board, not the chosen one. Which price was available
        # is part of what the system knew, and a single quote cannot answer
        # "could we actually have got that number".
        "books": _books(market),
        "prices": _prices(market),
        "implied_bullpen_shift": market.get("implied_bullpen_shift"),
        "lineup_status": _lineup_status(lineups, dossier),
        "findings": [_finding(f) for f in game.get("findings", [])],
        "sections_present": sorted(dossier.sections),
        "gaps": dict(dossier.gaps),
    }


def _books(market) -> dict:
    out = {}
    for name, quotes in (market.get("all_books") or {}).items():
        out[name] = [{"book": q.get("book"), "away_price": q.get("away_price"),
                      "home_price": q.get("home_price"), "total": q.get("total"),
                      "over_price": q.get("over_price"),
                      "under_price": q.get("under_price"),
                      "last_update": q.get("last_update")} for q in quotes]
    return out


def _prices(market) -> dict:
    out = {}
    for name, quote in (market.get("markets") or {}).items():
        out[name] = {k: quote.get(k) for k in
                     ("book", "away_price", "home_price", "away_fair",
                      "home_fair", "total", "over_price", "under_price",
                      "over_fair", "under_fair", "hold_pct", "last_update")}
    return out


def _lineup_status(lineups, dossier) -> dict:
    """Posted or not, and if not, why. Both are facts about the recommendation.

    A pick made before lineups post is a different pick from one made after, and
    a ledger that cannot tell them apart cannot support the timing question at
    all.
    """
    if not lineups:
        return {"posted": False,
                "reason": dossier.gaps.get("lineups", "not fetched")}
    return {
        "posted": True,
        "away": [b.get("person_id") for b in (lineups.get("away") or {}).get("batters") or []],
        "home": [b.get("person_id") for b in (lineups.get("home") or {}).get("batters") or []],
        "away_handedness": (lineups.get("away") or {}).get("handedness"),
        "home_handedness": (lineups.get("home") or {}).get("handedness"),
    }


def _finding(finding) -> dict:
    return {"detector": finding.detector, "kind": finding.kind,
            "claim": finding.claim, "value": finding.value,
            "baseline": finding.baseline, "sample": finding.sample,
            "surprise": finding.surprise, "side": finding.side,
            "evidence": finding.evidence}


def _iso(value=None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(
        timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Reading and settlement
# ---------------------------------------------------------------------------

def read(path=DEFAULT_LEDGER) -> list:
    """Every line ever appended, in order. Missing file is empty, not an error."""
    target = Path(path)
    if not target.exists():
        return []
    entries = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LedgerError(f"{target}:{number} is not valid JSON") from exc
    return entries


def recommendations(entries=None, path=DEFAULT_LEDGER) -> list:
    """First recommendation per game.

    Re-running a briefing later in the day appends again, and the later entry
    carries a price closer to first pitch -- better for reasons that have
    nothing to do with the system. The earliest entry is what it actually knew
    when it first spoke.
    """
    rows = read(path) if entries is None else entries
    seen, kept = set(), []
    for entry in rows:
        if entry.get("kind") != RECOMMENDATION:
            continue
        key = entry.get("game_pk")
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)
    return kept


def settlements(entries=None, path=DEFAULT_LEDGER) -> dict:
    """Settlement rows keyed by game_pk. Last write wins, since a settlement can
    legitimately be corrected when a later fetch fills a missing closing price."""
    rows = read(path) if entries is None else entries
    out = {}
    for entry in rows:
        if entry.get("kind") == SETTLEMENT:
            out[entry.get("game_pk")] = entry
    return out


def settle(game_pk, result, closing=None, path=DEFAULT_LEDGER,
           settled_at=None) -> dict:
    """Append a settlement. Never rewrites the recommendation it settles.

    `result` carries the full-game and first-five outcomes; `closing` the price
    at or near close. Both are unknowable at recommendation time, which is the
    whole point -- they go on their own line, so the original entry stays exactly
    as it was written.
    """
    entry = {
        "kind": SETTLEMENT,
        "game_pk": game_pk,
        "settled_at": _iso(settled_at),
        "result": result,
        "closing": closing,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def status(path=DEFAULT_LEDGER) -> dict:
    """What the ledger holds, and how much of it has resolved."""
    entries = read(path)
    recs = recommendations(entries)
    settled = settlements(entries)
    verdicts = {}
    for rec in recs:
        verdicts[rec["verdict"]] = verdicts.get(rec["verdict"], 0) + 1

    actionable = [r for r in recs if r["verdict"] == "flagged"]
    return {
        "games_recorded": len(recs),
        "settled": sum(1 for r in recs if r["game_pk"] in settled),
        "pending": sum(1 for r in recs if r["game_pk"] not in settled),
        "verdicts": verdicts,
        "actionable": len(actionable),
        "first_recorded": min((r["recorded_at"] for r in recs), default=None),
        "last_recorded": max((r["recorded_at"] for r in recs), default=None),
        "dates": sorted({r["date"] for r in recs if r.get("date")}),
    }
