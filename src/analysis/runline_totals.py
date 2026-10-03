"""Run line (spreads) and game totals for the Odds payload.

WHY THIS EXISTS
---------------
The capture has requested h2h + spreads + totals on every featured call since
the start (src/providers/odds.py DEFAULT_MARKETS, flat 3 credits a call) and
src/pipeline/snapshots.multibook_rows has stored a row per (event, book,
market) in data/processed/odds_multibook.jsonl since 2026-09-03. The rows were
never SERVED: prices.boards_by_matchup reads moneyline rows only
(snapshots.moneyline_rows) and oddspayload carried h2h only. This module reads
the stored run-line and total rows and shapes them like the h2h section, so the
whole feature costs zero credits to turn on.

THE SWITCH
----------
`RUNLINE_TOTALS=on` (environment). Default OFF. Off, nothing in this module is
called and the odds payload is byte-identical to before. It gates SERVING and
DISPLAY only; the request and the store were already paid for. See
docs/decisions/RUNLINE_TOTALS.md.

WHAT A "BOARD" IS HERE
----------------------
Books do not all quote the same run line or total (one book hangs 7.5 while the
rest hang 8.5). A best price compared across different lines is not a best
price, so each board has a MAIN LINE -- the line the most books quote at the
newest capture instant -- and best price / consensus are computed over the books
quoting that line only. Every other book stays on the board, flagged
`at_main_line: false`, and the other lines are listed with their book counts.
Consensus is the mean de-vigged probability at the main line, refused below the
same 6-book floor the moneyline uses (prices.MIN_BOOKS).

PRE-GAME ONLY, same rule as boards_by_matchup: an in-play board is a different
product (snapshots.is_pregame), so a started game's section is its LAST pre-game
board and says so in `basis`; the page labels it with its capture time.
"""

from __future__ import annotations

import os
import statistics
from typing import Optional

from src.analysis import prices as prices_mod
from src.core import odds as odds_math

ENV_SWITCH = "RUNLINE_TOTALS"
_ON = ("1", "true", "yes", "on")

LINE_MARKETS = ("spreads", "totals")
NO_BOARD_REASON = "no run line / total observations recorded for this game"
BASIS = "last pre-game capture"


def enabled(env=None) -> bool:
    """True only when RUNLINE_TOTALS is explicitly on. Anything else, including
    unset, is OFF -- the owner decision in docs/decisions/RUNLINE_TOTALS.md."""
    source = os.environ if env is None else env
    return (source.get(ENV_SWITCH) or "").strip().lower() in _ON


# ---------------------------------------------------------------------------
# Reading the store
# ---------------------------------------------------------------------------

def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote(market: str, row: dict) -> Optional[dict]:
    """One stored multibook row as a board quote, or None when a field the
    market needs is missing or unparseable (never half-recorded)."""
    base = {"ts": row.get("observed_utc"), "book": row.get("book")}
    if not base["book"]:
        return None
    if market == "spreads":
        home_line, away_line = _float(row.get("home_line")), _float(row.get("away_line"))
        if None in (home_line, away_line):
            return None
        if row.get("home_price") is None or row.get("away_price") is None:
            return None
        base.update(home_line=home_line, away_line=away_line,
                    home_price=row["home_price"], away_price=row["away_price"])
        return base
    total = _float(row.get("total"))
    if total is None or row.get("over_price") is None or row.get("under_price") is None:
        return None
    base.update(total=total, over_price=row["over_price"], under_price=row["under_price"])
    return base


def line_boards_by_matchup(rows=None, sport="mlb", *, date=None) -> dict:
    """{matchup_key: {"spreads": board, "totals": board}} from the multibook store.

    matchup_key is prices.matchup_key's (away, home, official_date), so a game's
    run-line board is found with the key its moneyline board is.

    A board is {"quotes": [...], "observed_utc": ts, "source": prices.SOURCE}: ONE
    capture instant (the newest pre-game one), one quote per book.

    STREAMING AND BOUNDED. The store is tens of megabytes; this keeps, per
    (game, market), only the newest instant's books while it reads, never the
    rows. `date` windows the read like boards_by_matchup does.
    """
    from src.pipeline import slate as slate_mod
    from src.pipeline import snapshots

    if rows is None:
        since = until = None
        if date is not None:
            since, until = snapshots.window_for_date(date, sport=sport)

        def _stream():
            for market in LINE_MARKETS:
                yield from snapshots.iter_multibook(
                    market=market, sport=sport, since=since, until=until,
                    keep=snapshots.is_pregame)
    else:
        def _stream():
            for row in snapshots.pregame_rows(rows):
                if row.get("market") in LINE_MARKETS and snapshots._is_sport(row, sport):
                    yield row

    newest = {}   # (key, market) -> [ts, {book: quote}]
    for row in _stream():
        market = row.get("market")
        quote = _quote(market, row)
        if quote is None or not quote["ts"]:
            continue
        away = slate_mod.team_abbrev_from_name(row.get("away_team") or "")
        home = slate_mod.team_abbrev_from_name(row.get("home_team") or "")
        game_date = snapshots.official_date(row.get("commence_time"))
        if not away or not home or not game_date:
            continue
        slot = newest.setdefault((prices_mod.matchup_key(away, home, game_date), market),
                                 [quote["ts"], {}])
        if quote["ts"] > slot[0]:
            slot[0], slot[1] = quote["ts"], {}
        if quote["ts"] == slot[0]:
            slot[1][quote["book"]] = quote
    boards = {}
    for (key, market), (ts, by_book) in newest.items():
        if by_book:
            boards.setdefault(key, {})[market] = {
                "quotes": list(by_book.values()), "observed_utc": ts,
                "source": prices_mod.SOURCE}
    return boards


# ---------------------------------------------------------------------------
# Building the payload sections
# ---------------------------------------------------------------------------

def _modal_line(values: list):
    """The line most books quote. Ties go to the line nearest the median of all
    quoted lines, then the lower number -- deterministic, never arbitrary."""
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    top = max(counts.values())
    tied = [v for v, c in counts.items() if c == top]
    median = statistics.median(values)
    return min(tied, key=lambda v: (abs(v - median), v))


def _best(quotes: list, price_key: str, extra: dict) -> Optional[dict]:
    """Best (highest-payout) price on one side and EVERY book quoting it."""
    best_price, best_decimal = None, None
    for q in quotes:
        try:
            decimal = odds_math.american_to_decimal(q[price_key])
        except (odds_math.OddsError, TypeError, KeyError):
            continue
        if best_decimal is None or decimal > best_decimal:
            best_price, best_decimal = q[price_key], decimal
    if best_decimal is None:
        return None
    books = sorted({q["book"] for q in quotes if q.get(price_key) == best_price})
    out = {"price": best_price, "books": books}
    out.update(extra)
    return out


def _consensus(quotes: list, key_a: str, key_b: str, side_a: str, side_b: str):
    """(consensus section or None, reason or None) over quotes at the main line."""
    fairs = []
    for q in quotes:
        try:
            fairs.append(odds_math.devig_two_way(q[key_a], q[key_b]))
        except (odds_math.OddsError, TypeError, KeyError):
            continue
    if len(fairs) < prices_mod.MIN_BOOKS:
        return None, (f"{len(fairs)} books quoted the main line; below the "
                      f"{prices_mod.MIN_BOOKS}-book floor a consensus means nothing")
    out = {"books": len(fairs)}
    for index, side in enumerate((side_a, side_b)):
        probability = sum(f[index] for f in fairs) / len(fairs)
        out[side] = {"implied_probability": round(probability, 5),
                     "implied_price": round(odds_math.probability_to_american(probability))}
    return out, None


def _unavailable(now_staleness) -> dict:
    return {"board_available": False, "reason": NO_BOARD_REASON, "basis": BASIS,
            "main_line": None, "books_at_main_line": 0, "board": [], "best": None,
            "consensus": None, "other_lines": [], "staleness": now_staleness(None, False)}


def build_market_spreads(board: Optional[dict], *, staleness) -> dict:
    """Run line section for one game. `staleness(observed_utc, has_board)` is
    oddspayload's own helper, passed in so this module needs no import cycle."""
    quotes = (board or {}).get("quotes") or []
    if not quotes:
        return _unavailable(staleness)
    main_home = _modal_line([q["home_line"] for q in quotes])
    at_main = [q for q in quotes if q["home_line"] == main_home]
    main_away = at_main[0]["away_line"]
    consensus, reason = _consensus(at_main, "away_price", "home_price", "away", "home")
    other = {}
    for q in quotes:
        if q["home_line"] != main_home:
            other[q["home_line"]] = other.get(q["home_line"], 0) + 1
    return {
        "board_available": True, "reason": None, "basis": BASIS,
        "main_line": {"home": main_home, "away": main_away},
        "books_at_main_line": len(at_main),
        "board": [{"book": q["book"], "home_line": q["home_line"], "home_price": q["home_price"],
                   "away_line": q["away_line"], "away_price": q["away_price"],
                   "at_main_line": q["home_line"] == main_home, "captured_at": q["ts"]}
                  for q in quotes],
        "best": {"away": _best(at_main, "away_price", {"line": main_away}),
                 "home": _best(at_main, "home_price", {"line": main_home})},
        "consensus": consensus, "consensus_unavailable_reason": reason,
        "other_lines": [{"home_line": line, "books": n} for line, n in sorted(other.items())],
        "staleness": staleness(board.get("observed_utc"), True),
    }


def build_market_totals(board: Optional[dict], *, staleness) -> dict:
    """Game total section for one game (see build_market_spreads)."""
    quotes = (board or {}).get("quotes") or []
    if not quotes:
        return _unavailable(staleness)
    main = _modal_line([q["total"] for q in quotes])
    at_main = [q for q in quotes if q["total"] == main]
    consensus, reason = _consensus(at_main, "over_price", "under_price", "over", "under")
    other = {}
    for q in quotes:
        if q["total"] != main:
            other[q["total"]] = other.get(q["total"], 0) + 1
    return {
        "board_available": True, "reason": None, "basis": BASIS,
        "main_line": {"total": main},
        "books_at_main_line": len(at_main),
        "board": [{"book": q["book"], "total": q["total"], "over_price": q["over_price"],
                   "under_price": q["under_price"], "at_main_line": q["total"] == main,
                   "captured_at": q["ts"]} for q in quotes],
        "best": {"over": _best(at_main, "over_price", {"total": main}),
                 "under": _best(at_main, "under_price", {"total": main})},
        "consensus": consensus, "consensus_unavailable_reason": reason,
        "other_lines": [{"total": line, "books": n} for line, n in sorted(other.items())],
        "staleness": staleness(board.get("observed_utc"), True),
    }


def build_game_line_markets(line_boards_for_game: Optional[dict], *, staleness) -> dict:
    """{"spreads": section, "totals": section} for one game; an absent board is
    an explicit unavailable section, never a placeholder price."""
    boards = line_boards_for_game or {}
    return {"spreads": build_market_spreads(boards.get("spreads"), staleness=staleness),
            "totals": build_market_totals(boards.get("totals"), staleness=staleness)}
