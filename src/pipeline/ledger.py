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
    """Append one entry per game not already recommended. Returns what happened.

    Re-running a briefing used to append the whole slate again -- one 08-30
    incident left five identical recommendation sets, pure noise in an
    append-only file. The write rule now: a repeat is skipped and counted
    UNLESS it is the one repeat that adds information -- a PRICED entry for
    a game whose only record so far is price-less (a briefing that ran
    before any snapshot existed), which recommendations() prefers as the
    first actionable word. A game with a priced record never gets another
    row; neither does a second price-less run.
    """
    stamp = _iso(recorded_at)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    priced_already, priceless_already = set(), set()
    for existing in read(path):
        if existing.get("kind") != RECOMMENDATION:
            continue
        if existing.get("prices") or {}:
            priced_already.add(existing.get("game_pk"))
        else:
            priceless_already.add(existing.get("game_pk"))

    entries, skipped = [], 0
    for game in slate.get("games", []):
        entry = _entry(game, slate.get("date"), stamp, information_time)
        key = entry.get("game_pk")
        priced = bool(entry.get("prices") or {})
        # A repeat that adds nothing is skipped; the ONE repeat worth
        # keeping is the repair -- a priced entry for a game whose only
        # record so far is price-less (the 04:17-before-any-snapshot case),
        # which recommendations() will then prefer.
        if key in priced_already or (key in priceless_already and not priced):
            skipped += 1
            continue
        entries.append(entry)

    with target.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    verdicts = {}
    for entry in entries:
        verdicts[entry["verdict"]] = verdicts.get(entry["verdict"], 0) + 1
    return {"recorded": len(entries), "skipped_already_recorded": skipped,
            "verdicts": verdicts, "path": str(target), "recorded_at": stamp}


def _entry(game, game_date, stamp, information_time) -> dict:
    dossier = game["dossier"]
    market = dossier.get("market") or {}
    lineups = dossier.get("lineups") or {}

    books = _books(market)
    prices = _prices(market)
    entry = {
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
        "books": books,
        "prices": prices,
        "implied_bullpen_shift": market.get("implied_bullpen_shift"),
        "lineup_status": _lineup_status(lineups, dossier),
        "findings": [_finding(f) for f in game.get("findings", [])],
        "sections_present": sorted(dossier.sections),
        "gaps": dict(dossier.gaps),
    }
    # An entry with no price on any book is a fact worth explaining, not a pair
    # of silent empty dicts: 70 rows went into the ledger that way on one date
    # and nothing recorded why. The dossier already knows the reason when the
    # market section was missing outright.
    if not prices and not any(books.values()):
        entry["price_reason"] = dossier.gaps.get(
            "market", "market section carried no usable prices at information time")
    return entry


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
    """First PRICED recommendation per game; first of any kind as fallback.

    Re-running a briefing later in the day appends again, and the later
    entry carries a price closer to first pitch -- better for reasons that
    have nothing to do with the system. The earliest entry is what it
    actually knew when it first spoke... unless that entry carries no
    prices at all, in which case it is a diary note, not a recommendation:
    an 04:17 run before any snapshot existed left a whole date of price-less
    rows that then permanently defined the "recommendation" for grading. A
    price-less first entry is superseded by the first entry that actually
    has a market attached; a game whose entries NEVER carry a price keeps
    its first row, price_reason and all, so the gap stays visible.
    """
    rows = read(path) if entries is None else entries
    kept = {}
    order = []
    for entry in rows:
        if entry.get("kind") != RECOMMENDATION:
            continue
        key = entry.get("game_pk")
        priced = bool((entry.get("prices") or {}))
        if key not in kept:
            kept[key] = entry
            order.append(key)
        elif priced and not (kept[key].get("prices") or {}):
            kept[key] = entry
    return [kept[key] for key in order]


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
           settled_at=None, closing_reason=None) -> dict:
    """Append a settlement. Never rewrites the recommendation it settles.

    `result` carries the full-game and first-five outcomes; `closing` the price
    at or near close. Both are unknowable at recommendation time, which is the
    whole point -- they go on their own line, so the original entry stays exactly
    as it was written.

    A null closing must never be silent: when `closing` is None the row carries
    `closing_reason` saying WHY there is no close, so "we never captured one"
    stays distinguishable from "someone forgot to pass it".
    """
    entry = {
        "kind": SETTLEMENT,
        "game_pk": game_pk,
        "settled_at": _iso(settled_at),
        "result": result,
        "closing": closing,
    }
    if closing is None:
        entry["closing_reason"] = closing_reason or "no closing price provided"
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
        # Dates whose games should long since be final but carry no
        # settlement: the signature of a daily loop that skipped a day
        # (08-30 did exactly that). Surfaced here so the loop's own output
        # flags the gap instead of it waiting for an audit.
        "unsettled_past_dates": sorted({
            r["date"] for r in recs
            if r.get("date") and r["game_pk"] not in settled
            and r["date"] < (max((x["date"] for x in recs if x.get("date")),
                                 default=""))}),
    }
