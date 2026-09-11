"""THE RECEIPTS. Every published card, frozen before first pitch and graded.

WHY THIS IS THE PRODUCT
-----------------------
The card itself is an opinion, and opinions are cheap -- every handicapping
site on the internet has three of them a day. What almost none of them have
is a public, immutable list of every pick they ever made, including the ones
that lost, with the price and the book they quoted at the time.

That is what this file writes. A card published tonight is hashed into an
append-only chain and cannot be edited afterwards, which means the record
page cannot flatter itself and neither can we.

TWO RULES, BOTH LOAD-BEARING
----------------------------
1. FROZEN ON FIRST PUBLICATION. `publish` writes a date's card once. Calling
   it again for the same date is a no-op that returns the existing row
   rather than an updated one, because a card that could be rewritten at
   20:00 for a game that started at 19:05 is not a record of anything. The
   engine's slip has followed this rule since it existed; the card follows
   the same one for the same reason.

2. GRADED, NEVER RE-SCORED. `settle` appends a SEPARATE row carrying the
   outcome. The published row is never touched. So the file reads as a
   history of what was claimed and then what happened, in that order, and
   nothing in it can be quietly improved after the fact.

WHAT A GRADE MEANS HERE
-----------------------
A moneyline pick wins if the club wins. A run-line pick wins if the club
covers -- wins by more than the line as a favourite, or loses by less than
it (or wins) as an underdog. Both are decided from the final score in
`src.pipeline.history`, which is the same store the paper ledger settles
from, so a card and a paper wager on the same game can never disagree about
who won.

Return is at FLAT ONE-UNIT STAKES at the price that was published, which is
the only stake plan this project uses anywhere. It is not a claim that
anyone bet that amount.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.core import odds as odds_math
from src.ledger.chain import HashChainLedger

CARD_STORE = os.path.join("evidence", "cards_v1.jsonl")

KIND_PUBLISHED = "card_published"
KIND_SETTLED = "card_settled"

RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_PUSH = "PUSH"
RESULT_VOID = "VOID"

# The fields of a pick that are frozen. Deliberately a fixed list rather than
# "whatever the card happened to carry": a ledger whose columns drift with
# the renderer stops being comparable across dates, and the first thing
# anyone will do with this file is compare across dates.
FROZEN_FIELDS = (
    "rank", "label", "bet", "why", "market", "line", "side",
    "team", "team_name", "opponent_name", "price", "book", "books",
    "confidence", "market_probability", "model_probability",
    "model_probability_moneyline", "game_id", "game_pk", "event_id",
    "away_team", "home_team", "first_pitch_utc", "observed_utc", "model",
    # The run line offered alongside the pick. Frozen with it because it was
    # shown to the reader, and anything shown is part of what was claimed --
    # but NEVER graded: `settle` scores `market`/`line`/`price`, which are
    # the pick's own, and an alternative nobody was told to take is not a
    # bet this record gets credit or blame for.
    "alternative",
)


class CardLedgerError(RuntimeError):
    pass


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(path or CARD_STORE)


def _frozen_pick(pick: Mapping) -> dict:
    return {key: pick.get(key) for key in FROZEN_FIELDS}


def published_row(date: str, *, path: Optional[str] = None) -> Optional[dict]:
    """The published card for `date`, or None. Reads the whole chain, which
    is cheap at one row a day and stays correct if rows are ever backfilled
    out of order."""
    for row in _ledger(path).read():
        if row.get("kind") == KIND_PUBLISHED and row.get("date") == date:
            return row
    return None


def settled_row(date: str, *, path: Optional[str] = None) -> Optional[dict]:
    for row in _ledger(path).read():
        if row.get("kind") == KIND_SETTLED and row.get("date") == date:
            return row
    return None


def publish(card: Mapping, *, now: Optional[str] = None,
            path: Optional[str] = None) -> dict:
    """Freeze one date's card. Idempotent per date.

    Returns the row -- the existing one when this date is already published,
    so a caller that runs twice a day never doubles a date and never silently
    replaces one. `already_published` on the returned dict says which
    happened, and it is not part of the hashed payload.
    """
    date = card.get("date")
    if not date:
        raise CardLedgerError("a card with no date cannot be published")
    picks = card.get("picks") or []
    if not picks:
        raise CardLedgerError(
            f"the card for {date} has no picks; there is nothing to freeze. "
            "An empty card is a real state -- see src/report/card.py's "
            "_empty_reason -- but it is not evidence and is not recorded.")

    existing = published_row(date, path=path)
    if existing is not None:
        out = dict(existing)
        out["already_published"] = True
        return out

    payload = {
        "kind": KIND_PUBLISHED,
        "date": date,
        "published_utc": now or datetime.now(timezone.utc).isoformat(),
        "rule": card.get("rule"),
        "basis": card.get("basis"),
        "disclaimer": card.get("disclaimer"),
        "model_id": card.get("model_id"),
        "calibrated": card.get("calibrated"),
        "calibration": card.get("calibration"),
        "n_picks": len(picks),
        "n_filled": card.get("filled"),
        "games_on_slate": card.get("games_on_slate"),
        "picks": [_frozen_pick(p) for p in picks],
    }
    row = _ledger(path).append(payload)
    out = dict(row)
    out["already_published"] = False
    return out


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def _score(value) -> Optional[int]:
    """A final score as an int, or None. NEVER an isinstance check.

    THE RESULTS STORE KEEPS SCORES AS STRINGS. `history.read_results()`
    round-trips through CSV, so a 7-9 game arrives as `("7", "9")`. An
    `isinstance(value, int)` guard here rejected all 2,153 stored games and
    would have graded every pick on every card VOID -- and a card settling
    0-0 with three voids does not read as a bug, it reads as a postponed
    slate. The public record would simply have stopped recording, quietly,
    forever.

    Found 2026-09-10 by a research probe that used the same isinstance guard
    and reported "only 0 finished games". The same trap, twice, in one day:
    see also the int/str game_pk join in src/cli.py's `card settle`.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def grade_pick(pick: Mapping, result: Mapping) -> dict:
    """One frozen pick against one final score.

    `result` is a `src.pipeline.history` row: `away_score`, `home_score`,
    `home_won`. A game with no final score grades VOID, never LOSS -- an
    ungraded pick counted as a loss would make a postponed slate look like a
    bad night, which is the single easiest way for a public record to become
    quietly wrong in the flattering direction's opposite.
    """
    away = _score(result.get("away_score"))
    home = _score(result.get("home_score"))
    if away is None or home is None:
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": "no final score stored for this game"}

    side = pick.get("side")
    if side not in ("away", "home"):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unknown side {side!r} on a frozen pick"}

    margin = home - away  # home minus away, everywhere in this repo
    market = pick.get("market")

    if market == "run_line":
        line = pick.get("line")
        if not isinstance(line, (int, float)):
            return {"result": RESULT_VOID, "profit_units": 0.0,
                    "reason": "run-line pick carries no line"}
        # `line` is signed from the PICKED side's point of view: +1.5 means
        # this side is getting the runs, -1.5 means giving them.
        own_margin = margin if side == "home" else -margin
        adjusted = own_margin + float(line)
        if abs(adjusted) < 1e-9:
            return {"result": RESULT_PUSH, "profit_units": 0.0,
                    "reason": "the run line landed exactly on the margin"}
        won = adjusted > 0
    else:
        won = (margin > 0) if side == "home" else (margin < 0)

    price = pick.get("price")
    try:
        profit = (odds_math.american_to_decimal(price) - 1.0) if won else -1.0
    except (odds_math.OddsError, TypeError, ValueError):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unusable published price {price!r}"}

    return {
        "result": RESULT_WIN if won else RESULT_LOSS,
        "profit_units": round(profit, 4),
        "away_score": away,
        "home_score": home,
        "margin": margin,
    }


def settle(date: str, results_by_game_pk: Mapping, *,
           now: Optional[str] = None, path: Optional[str] = None) -> Optional[dict]:
    """Grade one published card and append the outcome as a NEW row.

    Returns None when there is nothing to do -- no card for that date, or it
    is already settled. Never edits the published row.
    """
    published = published_row(date, path=path)
    if published is None:
        return None
    if settled_row(date, path=path) is not None:
        return None

    graded, staked, profit = [], 0, 0.0
    for pick in published.get("picks") or ():
        pk = pick.get("game_pk")
        result = (results_by_game_pk.get(pk)
                  or results_by_game_pk.get(str(pk))
                  or {})
        grade = grade_pick(pick, result)
        graded.append({"rank": pick.get("rank"), "bet": pick.get("bet"),
                       "label": pick.get("label"), "market": pick.get("market"),
                       "price": pick.get("price"), "game_pk": pk, **grade})
        if grade["result"] in (RESULT_WIN, RESULT_LOSS):
            staked += 1
            profit += grade["profit_units"]

    wins = sum(1 for g in graded if g["result"] == RESULT_WIN)
    losses = sum(1 for g in graded if g["result"] == RESULT_LOSS)
    payload = {
        "kind": KIND_SETTLED,
        "date": date,
        "settled_utc": now or datetime.now(timezone.utc).isoformat(),
        "published_row_hash": published.get("row_hash"),
        "n_picks": len(graded),
        "n_staked": staked,
        "wins": wins,
        "losses": losses,
        "pushes": sum(1 for g in graded if g["result"] == RESULT_PUSH),
        "voids": sum(1 for g in graded if g["result"] == RESULT_VOID),
        "profit_units": round(profit, 4),
        "roi_pct": round(profit / staked * 100.0, 3) if staked else None,
        "picks": graded,
    }
    return _ledger(path).append(payload)


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

def record(*, path: Optional[str] = None, since: Optional[str] = None) -> dict:
    """The running record: every settled card, pooled.

    Pooled is CORRECT here and is not the pooling mistake this repo warns
    about elsewhere. The card is one system with one rule, so its picks are
    one population; the warning applies to pooling DIFFERENT systems, where
    a control and a forward test get averaged into a number describing
    neither.

    VOIDS ARE COUNTED AND REPORTED, never dropped. A record that silently
    omits postponed games is a record with a hole in it that nobody can see.
    """
    days, wins, losses, pushes, voids, staked = 0, 0, 0, 0, 0, 0
    profit = 0.0
    by_label = {}
    for row in _ledger(path).read():
        if row.get("kind") != KIND_SETTLED:
            continue
        if since and (row.get("date") or "") < since:
            continue
        days += 1
        wins += row.get("wins") or 0
        losses += row.get("losses") or 0
        pushes += row.get("pushes") or 0
        voids += row.get("voids") or 0
        staked += row.get("n_staked") or 0
        profit += row.get("profit_units") or 0.0
        for pick in row.get("picks") or ():
            label = pick.get("label") or "UNLABELLED"
            slot = by_label.setdefault(
                label, {"wins": 0, "losses": 0, "staked": 0, "profit_units": 0.0})
            if pick.get("result") == RESULT_WIN:
                slot["wins"] += 1
            elif pick.get("result") == RESULT_LOSS:
                slot["losses"] += 1
            if pick.get("result") in (RESULT_WIN, RESULT_LOSS):
                slot["staked"] += 1
                slot["profit_units"] += pick.get("profit_units") or 0.0

    for slot in by_label.values():
        slot["profit_units"] = round(slot["profit_units"], 4)
        slot["win_rate"] = (round(slot["wins"] / slot["staked"], 4)
                            if slot["staked"] else None)

    return {
        "days": days,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "n_staked": staked,
        "win_rate": round(wins / staked, 4) if staked else None,
        "profit_units": round(profit, 4),
        "roi_pct": round(profit / staked * 100.0, 3) if staked else None,
        "by_label": by_label,
        "since": since,
    }


def history(*, path: Optional[str] = None, limit: Optional[int] = 60) -> dict:
    """Every settled day, newest first, each joined back to its own
    PUBLISHED row for the book and team names a settled row does not carry.

    WHY THE JOIN. `settle` deliberately appends a SEPARATE row (rule 2 in
    this module's docstring) carrying only what grading needs: rank, bet,
    label, market, price, game_pk, the result and the score. The book, the
    books-compared count and the team names are FROZEN_FIELDS on the
    PUBLISHED row alone -- they describe what a reader was shown at
    publish time, not what grading needed -- so a page that wants "took
    -140 at DraftKings, best of 11 books" beside a graded pick has to read
    both rows for the date and match them up. Matched by `rank`, which is
    unique within one date's picks (1..daily_card.MAX_PICKS) and is carried
    unchanged on both the frozen pick and its graded counterpart.

    `limit` caps how many days come back, newest first -- the ledger only
    grows, and the public record page has no reason to pull every day that
    ever settled just to show the last couple of months. Capped, never
    silently truncated: `total_days` and `truncated` say exactly what
    happened, so a caller can render "60 of 214 days" instead of a number
    that just looks complete. `limit=None` returns every settled day; the
    API route never does this (see api/card.py) but a script reading the
    whole history should not have to pass an arbitrarily large number.
    """
    ledger = _ledger(path)
    published_by_date: dict = {}
    settled: list = []
    for row in ledger.read():
        kind = row.get("kind")
        if kind == KIND_PUBLISHED:
            published_by_date[row.get("date")] = row
        elif kind == KIND_SETTLED:
            settled.append(row)

    # Lexicographic order on YYYY-MM-DD is chronological order.
    settled.sort(key=lambda r: r.get("date") or "", reverse=True)
    total_days = len(settled)
    capped = settled if limit is None else settled[:max(limit, 0)]

    days = []
    for row in capped:
        published = published_by_date.get(row.get("date")) or {}
        frozen_by_rank = {p.get("rank"): p for p in (published.get("picks") or ())}
        picks = []
        for graded in row.get("picks") or ():
            frozen = frozen_by_rank.get(graded.get("rank")) or {}
            picks.append({
                "rank": graded.get("rank"),
                "bet": graded.get("bet"),
                "label": graded.get("label"),
                "market": graded.get("market"),
                "price": graded.get("price"),
                "book": frozen.get("book"),
                "books": frozen.get("books"),
                "away_team": frozen.get("away_team"),
                "home_team": frozen.get("home_team"),
                "team_name": frozen.get("team_name"),
                "opponent_name": frozen.get("opponent_name"),
                "result": graded.get("result"),
                "profit_units": graded.get("profit_units"),
                "away_score": graded.get("away_score"),
                "home_score": graded.get("home_score"),
                # Populated only for a VOID pick (see grade_pick) -- the
                # plain-English reason nothing here could be graded.
                "reason": graded.get("reason"),
            })
        days.append({
            "date": row.get("date"),
            "settled_utc": row.get("settled_utc"),
            "wins": row.get("wins") or 0,
            "losses": row.get("losses") or 0,
            "pushes": row.get("pushes") or 0,
            "voids": row.get("voids") or 0,
            "n_staked": row.get("n_staked") or 0,
            "profit_units": row.get("profit_units"),
            "roi_pct": row.get("roi_pct"),
            # This settled row's own hash, and the PUBLISHED row's hash it
            # was graded against -- two different receipts. The published
            # hash is the one a reader wants: "this is what was claimed,
            # before the game, and here is the exact entry that proves it."
            "row_hash": row.get("row_hash"),
            "published_row_hash": row.get("published_row_hash"),
            "picks": picks,
        })

    # PUBLISHED BUT NOT YET GRADED, carried separately.
    #
    # `days` above is settled days only, and that is right for the record: an
    # ungraded day has no result to put in a tally. But it is wrong for a
    # CALENDAR, which is the question "what did you say, and when" before it
    # is the question "how did it go". A calendar built from `days` alone
    # shows nothing at all on the day a card is published and only fills in
    # the morning after -- so on the first day of the product, and on every
    # day before that night's settle, it reads as if nothing was published.
    #
    # Kept as its own key rather than mixed into `days` so no existing
    # consumer of `days` starts seeing rows with no result in them. A caller
    # that wants both merges them and knows which is which.
    pending = []
    settled_dates = {row.get("date") for row in settled}
    for date, row in published_by_date.items():
        if date in settled_dates:
            continue
        pending.append({
            "date": date,
            "published_utc": row.get("published_utc"),
            "n_filled": row.get("n_filled") or 0,
            "row_hash": row.get("row_hash"),
            "picks": [{
                "rank": p.get("rank"),
                "bet": p.get("bet"),
                "label": p.get("label"),
                "market": p.get("market"),
                "price": p.get("price"),
                "book": p.get("book"),
                "books": p.get("books"),
                "away_team": p.get("away_team"),
                "home_team": p.get("home_team"),
                "team_name": p.get("team_name"),
                "opponent_name": p.get("opponent_name"),
            } for p in (row.get("picks") or ())],
        })
    pending.sort(key=lambda r: r.get("date") or "", reverse=True)

    return {
        "days": days,
        "pending_days": pending,
        "limit": limit,
        "total_days": total_days,
        "truncated": total_days > len(days),
    }


def verify(*, path: Optional[str] = None):
    """Walk the chain. A published record whose chain is broken is not a
    record, and the page that shows it has to be able to say so."""
    return _ledger(path).verify()
