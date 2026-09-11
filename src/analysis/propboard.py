"""Tonight's player props, priced: what is likely, and what the price needs.

WHY THIS EXISTS
---------------
The published card can only ever emit two things -- `moneyline` and
`run_line` (src/analysis/daily_card.py). Every night it therefore shows the
same shape of bet: the market's biggest favourites. The owner, 2026-09-11,
looking at a card of five moneylines between -155 and -205:

    "where are all the player props including player hits player total
     bases player stolen base player home run, there's just so many
     different bets that are not being incorporated here"

The data was already there -- 17,149 prop quotes across six markets -- and
nothing in the product read it.

THE ORDER THINGS ARE ASKED IN, AND IT IS HIS
--------------------------------------------
    "none of that price matters until we know it's a MORE THAN LIKELY BET,
     once we have the almost guaranteed bets, then we find the best sports
     picks of those with the best value, not the other way around."

So every contract carries two numbers and they are asked in that order:

    1. `probability`  -- our model's chance this happens. Point-in-time,
                         from the batter's own prior box scores, no price
                         read. This is the "is it likely" question.
    2. `breakeven`    -- what the best available price REQUIRES to be worth
                         taking. This is the "is it worth it" question, and
                         it is only asked of contracts that already passed
                         the first.

`edge = probability - breakeven`. Positive means our number says the price
is too generous.

WHAT THIS IS NOT, AND THE REASON IS MEASURED
--------------------------------------------
**This is a BOARD, not a pick list, and it must not be ranked by `edge`.**

`scripts/probe_prop_value.py` measured exactly that strategy: contracts where
our probability cleared the best available price returned **-13.4%**, against
**-9.1%** for every assessable over. Selecting on our own edge did WORSE than
not selecting at all, because departure from the price is selected on the
model's own error (docs/PREREG_MARKET_VS_MODEL.md).

The model is calibrated -- `batter_hits` at +0.0133 nats over the base rate,
3.3x what the team model manages -- and calibrated overall is not the same as
calibrated conditional on disagreeing with the market. So the honest surface
shows both numbers and lets a reader see the gap; it does not rank by the gap
and call the top of that ranking a bet.

WHICH MARKETS SURVIVE, AND WHY THE MISSING ONES ARE MISSING
-----------------------------------------------------------
Measured against the store on 2026-09-11:

    batter_hits           4,722 quotes at 0.5, 317 at 1.5, both sides   OK
    batter_total_bases    1,189 at 0.5, 4,201 at 1.5, both sides        OK
    batter_runs_scored      576 at 0.5, both sides                      OK
    batter_home_runs      3,351 quotes and ZERO unders                  no fair price
    batter_rbis             885 quotes                                  model not good enough
    batter_hits_runs_rbis 1,908 quotes                                  model not good enough
    stolen bases          not captured at all

**Home runs are the one worth explaining.** No book quotes the under, so
there is no two-way pair to de-vig, and any "edge" computed there is measured
against a raw price that still contains the book's whole margin -- which is
the book's, not ours. A home-run prop is also almost never a *likely* bet:
these sit around 5-15%, so under the owner's own first filter they are
lottery tickets, not the almost-guaranteed bets he is asking for.

The other two are refused by `playerprops.publishable`, which is a statement
about our model and not about the market.

Pure analysis. No I/O, no network, no api/ import.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from src.analysis import playerprops
from src.core import odds as odds_math

# Two books quoting BOTH sides before a contract has a fair price at all.
# Same floor and the same reason as scripts/_propboard.py.
MIN_BOOKS = 2

# A two-way pair whose raw probabilities sum below this is not a real market
# -- a book that has taken its margin off is usually one that has stopped
# offering the bet.
MIN_TWO_WAY_BOOKSUM = 0.98

# Below this our model is not claiming the outcome is likely, and the
# contract does not belong on a "most likely" board at all.
LIKELY_FLOOR = 0.50


class PropBoardError(ValueError):
    """Raised when the inputs cannot describe a board. Never for one bad row."""


def assessable(market: Optional[str]) -> bool:
    """Both gates, and they ask different questions.

    `publishable` asks whether the MODEL is any good on this market.
    `deviggable` asks whether a fair price EXISTS to measure against. Home
    runs pass the first and fail the second; see the module docstring.
    """
    return (playerprops.publishable(market or "")
            and playerprops.deviggable(market or ""))


def _newest_quotes(rows: Iterable[Mapping]) -> dict:
    """{(date, event, player, market, line): {book: {side: price}}}.

    Only each book's NEWEST quote for a contract survives: a book that moved
    its line during the day should be read where it ended, not averaged over
    everywhere it passed through.
    """
    newest: dict = {}
    for row in rows:
        if not assessable(row.get("market")):
            continue
        key = (row.get("game_date"), row.get("event_id"), row.get("player"),
               row.get("market"), str(row.get("line")))
        stamp = row.get("observed_utc") or ""
        if stamp > newest.get(key, ""):
            newest[key] = stamp

    out: dict = {}
    for row in rows:
        if not assessable(row.get("market")):
            continue
        key = (row.get("game_date"), row.get("event_id"), row.get("player"),
               row.get("market"), str(row.get("line")))
        if (row.get("observed_utc") or "") != newest.get(key):
            continue
        side, book = row.get("side"), row.get("book")
        if side in ("Over", "Under") and book:
            out.setdefault(key, {}).setdefault(book, {})[side] = row.get("price")
    return out


def fair_and_best(books: Mapping) -> tuple:
    """(mean de-vigged over probability, {side: (american, decimal, book)}).

    A gap measured against a RAW price partly IS the book's margin, which is
    not value and does not belong to us -- so every fair probability here has
    had its own book's margin removed first. Returns (None, {}) when no book
    quotes both sides.
    """
    fair_overs, best = [], {}
    for book, sides in (books or {}).items():
        over, under = sides.get("Over"), sides.get("Under")
        if over is None or under is None:
            continue
        try:
            raw = (odds_math.american_to_probability(over)
                   + odds_math.american_to_probability(under))
            if raw < MIN_TWO_WAY_BOOKSUM:
                continue
            fair_over, _fair_under = odds_math.devig_two_way(over, under)
            decimals = {"Over": odds_math.american_to_decimal(over),
                        "Under": odds_math.american_to_decimal(under)}
        except (odds_math.OddsError, TypeError, ValueError,
                ZeroDivisionError):
            continue
        fair_overs.append(fair_over)
        for side, american in (("Over", over), ("Under", under)):
            held = best.get(side)
            if held is None or decimals[side] > held[1]:
                best[side] = (american, decimals[side], book)
    if len(fair_overs) < MIN_BOOKS:
        return None, {}
    return sum(fair_overs) / len(fair_overs), best


def _prior_lines(batter_rows: Sequence[Mapping], date: str) -> list:
    """That batter's box scores STRICTLY BEFORE `date`.

    Strictly: a batter's own performance tonight may not inform tonight's
    estimate, and `<` rather than `<=` is the whole of that guarantee.
    """
    return [row for row in batter_rows or []
            if str(row.get("date") or "")[:10] < date]


def build(prop_rows: Iterable[Mapping], *, date: str,
          batters_by_name: Mapping, league: Mapping,
          slots_by_player: Optional[Mapping] = None) -> dict:
    """Every priceable prop contract for one slate date.

    `slots_by_player` is tonight's batting order where it is known. Slot is
    the single most valuable input here and the reason it matters is
    measured, not assumed: `playerprops.SLOT_PLATE_APPEARANCES` runs from
    4.467 plate appearances leading off to 3.461 batting ninth, so a hitter
    moving up the order gains about 29% more chances. Absent, the model falls
    back to the batter's own season average and says which it used.

    Returns {"date", "contracts", "refused"} -- `refused` a census of what
    could not be priced and why, because a board that silently drops most of
    its input looks identical to a thin slate.
    """
    if not date:
        raise PropBoardError("a slate date is required")

    quotes = _newest_quotes(
        [row for row in prop_rows if row.get("game_date") == date])

    contracts, refused = [], {}

    def refuse(reason: str) -> None:
        refused[reason] = refused.get(reason, 0) + 1

    for key, books in quotes.items():
        _date, event_id, player, market, line_text = key
        try:
            line = float(line_text)
        except (TypeError, ValueError):
            refuse("line is not a number")
            continue

        prior = _prior_lines(batters_by_name.get(player) or [], date)
        if not prior:
            refuse("no prior box score for this batter")
            continue

        market_over, best = fair_and_best(books)
        if market_over is None:
            refuse("fewer than two books quoting both sides")
            continue

        try:
            priced = playerprops.price_prop(
                market=market, line=line, batter_lines=prior, league=league,
                batting_slot=(slots_by_player or {}).get(player))
        except playerprops.PropError as exc:
            refuse(str(exc))
            continue

        over_p = priced["probability"]
        for side, model_p in (("Over", over_p), ("Under", 1.0 - over_p)):
            quote = best.get(side)
            if not quote:
                continue
            american, decimal, book = quote
            breakeven = 1.0 / decimal
            contracts.append({
                "player": player, "market": market, "line": line,
                "side": side, "event_id": event_id,
                "probability": model_p,
                "market_probability": (market_over if side == "Over"
                                       else 1.0 - market_over),
                "breakeven": breakeven,
                "gap_vs_breakeven": model_p - breakeven,
                "price": american, "book": book,
                "expected_pa": priced.get("expected_pa"),
                "expected_pa_source": priced.get("expected_pa_source"),
                "batting_slot": priced.get("batting_slot"),
            })

    return {"date": date, "contracts": contracts, "refused": refused}


def most_likely(contracts: Sequence[Mapping], *, floor: float = LIKELY_FLOOR,
                limit: Optional[int] = None) -> list:
    """His first filter: what is MORE THAN LIKELY to happen, likeliest first.

    Ranked by our probability and NEVER by edge -- see the module docstring
    for the measurement that forbids it. The price is carried along so a
    reader can see what it would cost, which is a different question and is
    asked second.
    """
    kept = [c for c in contracts if (c.get("probability") or 0.0) > floor]
    kept.sort(key=lambda c: (-(c.get("probability") or 0.0),
                             str(c.get("player") or ""),
                             str(c.get("market") or "")))
    return kept[:limit] if limit else kept


def clears_its_price(contracts: Sequence[Mapping]) -> list:
    """His second filter, applied to survivors of the first.

    Keeps contracts our number says are likelier than the price requires.
    **Still not a recommendation**: this is the exact subset measured at
    -13.4% against a -9.1% control. It is surfaced so the gap is visible and
    labelled, not so it can be bet.
    """
    return [c for c in contracts if (c.get("gap_vs_breakeven") or 0.0) > 0.0]


def summarise(board: Mapping) -> dict:
    """Counts a reader needs to judge how thin the board is."""
    contracts = board.get("contracts") or []
    likely = most_likely(contracts)
    return {
        "date": board.get("date"),
        "contracts": len(contracts),
        "markets": sorted({c.get("market") for c in contracts
                           if c.get("market")}),
        "likely": len(likely),
        "likely_and_clears_price": len(clears_its_price(likely)),
        "refused": dict(board.get("refused") or {}),
    }
