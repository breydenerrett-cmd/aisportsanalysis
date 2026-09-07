"""Price-vs-consensus for the markets that are NOT the full-game moneyline:
first-five innings, team totals, alternate lines and pitcher strikeouts.

WHY THIS EXISTS
---------------
The capture side has been buying these markets daily since 2026-09-03 and
the product showed none of them: `src.analysis.opportunities` pinned itself
to `MARKET = "h2h"`, so a first-five under or a strikeout prop could never
appear as an opportunity no matter how good the price was. This module
turns the derivative and prop stores into the same shape the moneyline
ranker already consumes, so every market competes on one measure.

ONE MEASURE, NOT A NEW ONE
--------------------------
Every contract here goes through `prices.snapshot()` -- the same function
the moneyline uses. That is deliberate and it is the whole point: the same
two-way de-vig, the same `prices.MIN_BOOKS` six-book floor, the same
improvement arithmetic. Nothing in this file computes a probability, and
nothing in it invents a market-specific rule. A first-five under is judged
exactly the way a moneyline is judged, or it is not judged at all.

WHAT A CONTRACT IS
------------------
One bettable two-way proposition: an event, a market, a line, and (for team
totals) which team. The line is part of the identity. Over 4.5 and Over 5.0
are DIFFERENT BETS and are never pooled into one consensus -- pooling them
would average two different propositions and call the result a fair price,
which is how a line-shopping tool manufactures an edge that is really just
a different bet.

THIN BOARDS ARE REPORTED, NOT HIDDEN AND NOT RESCUED
----------------------------------------------------
Fewer books quote a first-five total than quote a moneyline, so most of
these contracts fall below the six-book floor. Measured on 2026-09-07: 0 of
6 first-five totals and 0 of 12 first-five spreads cleared it. Two things
this module will not do about that:

  - It will not lower the floor for derivatives. A three-book consensus is
    a handful's opinion whatever market it is quoted in.
  - It will not hide the contract. The row still comes back, carrying its
    books, its prices and a `thin_reason` naming the count and the floor,
    with `verdict` left None. The reader sees that the market exists and
    why we decline to call it.

NEWEST SHARED INSTANT
---------------------
Per contract, only quotes sharing the newest capture timestamp are used --
`prices.snapshot`'s own docstring warns that mixing instants compares a
stale best against a fresh consensus and manufactures improvement out of
latency. That rule is not relaxed here.

Reads two stores and returns plain dicts. stdlib only, no fastapi import
(tests/test_api_boundary.py).
"""

from __future__ import annotations

import json
import os
from typing import Optional

from src.analysis import prices

DERIVATIVE_STORE = os.path.join("data", "processed", "derivative_markets.jsonl")
PROP_STORE = os.path.join("data", "processed", "prop_prices.jsonl")

# Markets this module knows how to phrase and pair. A market absent from
# here is skipped rather than rendered under a guessed label -- the same
# "never a fabricated label" rule the day-recap renderer follows.
TOTALS_MARKETS = ("totals_1st_5_innings", "alternate_totals")
TEAM_TOTAL_MARKETS = ("team_totals",)
MONEYLINE_MARKETS = ("h2h_1st_5_innings",)
SPREAD_MARKETS = ("spreads_1st_5_innings", "alternate_spreads")
PROP_MARKET = "pitcher_strikeouts"

SUPPORTED = (TOTALS_MARKETS + TEAM_TOTAL_MARKETS + MONEYLINE_MARKETS
             + SPREAD_MARKETS + (PROP_MARKET,))

# How each market is said in a sentence. `{line}`, `{team}`, `{player}` and
# `{side}` are filled from the row's own fields; nothing is inferred.
MARKET_NOUN = {
    "totals_1st_5_innings": "First 5 total",
    "h2h_1st_5_innings": "First 5 moneyline",
    "spreads_1st_5_innings": "First 5 spread",
    "team_totals": "team total",
    "alternate_totals": "alternate total",
    "alternate_spreads": "alternate spread",
    PROP_MARKET: "strikeouts",
}


def thin_reason(books: int) -> str:
    """The one sentence said whenever a board is below the floor. Same
    wording shape as `prices.snapshot`'s own skip reason, so a reader meets
    one explanation across the product rather than two."""
    return (f"{books} book(s) quoted this line at one instant; below the "
            f"{prices.MIN_BOOKS}-book floor a consensus means nothing, so no "
            "value comparison is reported")


def _read(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                # A truncated tail line is skipped, never guessed at.
                continue
    return out


def _line_text(line) -> Optional[str]:
    if line is None or line == "":
        return None
    try:
        value = float(line)
    except (TypeError, ValueError):
        return str(line)
    return str(int(value)) if value == int(value) else str(value)


def _wager_text(market, *, side, line, team=None, player=None) -> Optional[str]:
    """How the bet is said. Returns None when the pieces needed are absent
    -- the caller drops the contract rather than printing half a bet."""
    line_text = _line_text(line)
    if market in TOTALS_MARKETS:
        if not side or line_text is None:
            return None
        return f"First 5: {side} {line_text}" if market.endswith("1st_5_innings") \
            else f"Alternate total: {side} {line_text}"
    if market in TEAM_TOTAL_MARKETS:
        if not side or line_text is None or not team:
            return None
        return f"{team} team total {side} {line_text}"
    if market in MONEYLINE_MARKETS:
        return f"{side} first 5 moneyline" if side else None
    if market in SPREAD_MARKETS:
        if not side or line_text is None:
            return None
        label = "First 5" if market.endswith("1st_5_innings") else "Alternate"
        return f"{label}: {side} {line_text}"
    if market == PROP_MARKET:
        if not player or not side or line_text is None:
            return None
        return f"{player} {side} {line_text} strikeouts"
    return None


def _pair_sides(market, rows):
    """The two sides of this contract, in a stable order, or None.

    A two-way market has exactly two named sides. Anything else -- one side
    only, or three -- is not a contract this module can de-vig, and is
    dropped rather than forced into a pair.
    """
    names = sorted({r.get("side") for r in rows if r.get("side")})
    if len(names) != 2:
        return None
    if market in TOTALS_MARKETS + TEAM_TOTAL_MARKETS:
        if set(names) != {"Over", "Under"}:
            return None
        return ("Over", "Under")
    return (names[0], names[1])


def _derivative_contracts(rows, *, date):
    """Group derivative-store rows into contracts keyed by
    (event_id, market, line, team)."""
    grouped = {}
    for row in rows:
        if row.get("game_date") != date:
            continue
        market = row.get("market")
        if market not in SUPPORTED or not row.get("event_id"):
            continue
        key = (row.get("event_id"), market, str(row.get("line")),
               row.get("team") or "")
        grouped.setdefault(key, []).append(row)

    out = []
    for key, group in grouped.items():
        event_id, market, _line, team = key
        newest = max(r.get("observed_utc") or "" for r in group)
        at_instant = [r for r in group if (r.get("observed_utc") or "") == newest]
        pair = _pair_sides(market, at_instant)
        if not pair:
            continue
        side_a, side_b = pair

        # One row per book carrying BOTH sides. A book quoting only one side
        # of the pair cannot be de-vigged and is left out of the count --
        # counting it would inflate the book depth behind the consensus.
        by_book = {}
        for row in at_instant:
            book = row.get("book")
            if not book:
                continue
            slot = by_book.setdefault(book, {})
            if row.get("side") == side_a:
                slot["away_price"] = row.get("price")
            elif row.get("side") == side_b:
                slot["home_price"] = row.get("price")
        quotes = [{"book": book, "away_price": v.get("away_price"),
                   "home_price": v.get("home_price")}
                  for book, v in sorted(by_book.items())
                  if v.get("away_price") is not None and v.get("home_price") is not None]
        if not quotes:
            continue

        sample = at_instant[0]
        out.append({
            "event_id": event_id,
            "market": market,
            "line": sample.get("line"),
            "team": team or None,
            "player": None,
            "sides": (side_a, side_b),
            "quotes": quotes,
            "observed_utc": newest,
            "commence_time": sample.get("commence_time"),
            "away_team": sample.get("away_team"),
            "home_team": sample.get("home_team"),
        })
    return out


def _prop_contracts(rows, *, date):
    """Pitcher-strikeout rows already carry both prices on one row, so a
    contract is one (event, player, point) and each row is one book."""
    grouped = {}
    for row in rows:
        if row.get("game_date") != date or not row.get("player"):
            continue
        if row.get("market") != PROP_MARKET or not row.get("event_id"):
            continue
        key = (row.get("event_id"), row.get("player"), str(row.get("point")))
        grouped.setdefault(key, []).append(row)

    out = []
    for key, group in grouped.items():
        event_id, player, _point = key
        newest = max(r.get("observed_utc") or "" for r in group)
        at_instant = [r for r in group if (r.get("observed_utc") or "") == newest]
        by_book = {}
        for row in at_instant:
            if row.get("book") and row.get("over_price") is not None \
                    and row.get("under_price") is not None:
                by_book[row["book"]] = row
        quotes = [{"book": book, "away_price": r.get("over_price"),
                   "home_price": r.get("under_price")}
                  for book, r in sorted(by_book.items())]
        if not quotes:
            continue
        sample = at_instant[0]
        out.append({
            "event_id": event_id,
            "market": PROP_MARKET,
            "line": sample.get("point"),
            "team": None,
            "player": player,
            "sides": ("Over", "Under"),
            "quotes": quotes,
            "observed_utc": newest,
            "commence_time": sample.get("commence_time"),
            "away_team": sample.get("away_team"),
            "home_team": sample.get("home_team"),
        })
    return out


def candidates_for_date(date, *, derivative_rows=None, prop_rows=None) -> list:
    """Every derivative/prop contract on `date`, priced the same way a
    moneyline is priced.

    Each returned row carries, per side, either a priced comparison
    (`consensus_probability`, `best_price`, `best_book`) or nothing at all
    plus a `thin_reason`. The caller decides what to render; this function
    never decides that a thin contract should disappear.
    """
    derivative_rows = (_read(DERIVATIVE_STORE) if derivative_rows is None
                       else derivative_rows)
    prop_rows = _read(PROP_STORE) if prop_rows is None else prop_rows

    contracts = (_derivative_contracts(derivative_rows, date=date)
                 + _prop_contracts(prop_rows, date=date))

    out = []
    for contract in contracts:
        quotes = contract["quotes"]
        snap = prices.snapshot(quotes)
        books = len(quotes)
        side_a, side_b = contract["sides"]

        base = {
            "event_id": contract["event_id"],
            "market": contract["market"],
            "market_noun": MARKET_NOUN.get(contract["market"], contract["market"]),
            "line": contract["line"],
            "team": contract["team"],
            "player": contract["player"],
            "away_team": contract["away_team"],
            "home_team": contract["home_team"],
            "commence_time": contract["commence_time"],
            "observed_utc": contract["observed_utc"],
            "books": books,
        }

        if snap.get("skipped"):
            # Below the floor. The contract is still reported, with the
            # count and the floor named, and no verdict of any kind.
            for side in (side_a, side_b):
                row = dict(base)
                row.update({
                    "side": side,
                    "wager_text": _wager_text(
                        contract["market"], side=side, line=contract["line"],
                        team=contract["team"], player=contract["player"]),
                    "best_price": None,
                    "best_book": None,
                    "consensus_probability": None,
                    "thin_reason": thin_reason(books),
                })
                if row["wager_text"]:
                    out.append(row)
            continue

        sides = snap.get("sides") or {}
        for side, snap_key in ((side_a, "away"), (side_b, "home")):
            detail = sides.get(snap_key) or {}
            if detail.get("skipped") or detail.get("best_price") is None:
                continue
            row = dict(base)
            row.update({
                "side": side,
                "wager_text": _wager_text(
                    contract["market"], side=side, line=contract["line"],
                    team=contract["team"], player=contract["player"]),
                "best_price": detail.get("best_price"),
                "best_book": detail.get("best_book"),
                "consensus_probability": detail.get("consensus_probability"),
                "thin_reason": None,
            })
            if row["wager_text"]:
                out.append(row)
    return out
