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

def grade_pick(pick: Mapping, result: Mapping) -> dict:
    """One frozen pick against one final score.

    `result` is a `src.pipeline.history` row: `away_score`, `home_score`,
    `home_won`. A game with no final score grades VOID, never LOSS -- an
    ungraded pick counted as a loss would make a postponed slate look like a
    bad night, which is the single easiest way for a public record to become
    quietly wrong in the flattering direction's opposite.
    """
    away = result.get("away_score")
    home = result.get("home_score")
    if not isinstance(away, int) or not isinstance(home, int):
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


def verify(*, path: Optional[str] = None):
    """Walk the chain. A published record whose chain is broken is not a
    record, and the page that shows it has to be able to say so."""
    return _ledger(path).verify()
