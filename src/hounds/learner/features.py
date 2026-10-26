"""The features frozen onto every Learner bet at the moment it is placed.

POINT IN TIME, OR IT IS NOT A FEATURE. Everything here is a pure function of three things the runner already hands a hound:
the lock board (``base.lock_board``: quotes observed at or before the lock, strictly before the start), the context
(``base.build_context``: results that finished before the lock, the schedule) and, for the open, the same quote list read
with the same cut-offs (``open_market_board``). The result of the game, the close and anything observed after the lock are
never read, so a feature cannot know how the bet turned out. ``tests/test_learner_hound.py`` pins this: add a post-lock quote
and a result row to the stores and the features must not change.

The dict is written once onto the bet row (``learner_features``) and the learn step reads THAT, never a recomputation: the
record of what the hound knew is the row, and a later change to this module cannot rewrite it. ``FEATURE_VERSION`` goes
on the row so a reader can tell which definition made it.

WHAT IS NOT KNOWN IS NONE. A feature with no honest value (rest days for a sport with no results store, the open price when no
capture an hour before the lock had enough books, a role for a total) is ``None``, never a guess.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Optional, Sequence

from src.hounds.pack import base

FEATURE_VERSION = 1

# The price bands the learn step cuts by. Contiguous over the hound's own range (-199 to +400); -100 never appears (the
# board maps it to +100), so the near-even band is -109..-101. Labels are what a person reads.
BANDS = ((-199, -150, "-199 to -150"), (-149, -110, "-149 to -110"), (-109, -101, "-109 to -101"),
         (100, 180, "+100 to +180"), (181, 400, "+181 to +400"))

FEATURE_NAMES = (
    "sport", "league", "market", "side", "role", "venue", "price", "band", "line", "abs_line",
    "consensus_fair", "break_even", "fair_minus_break_even", "books", "price_best", "best_vs_avg_pts",
    "open_fair", "fair_move_pts", "line_move", "hours_to_start", "day_of_week", "start_hour_et", "month", "is_weekend",
    "rest_days_home", "rest_days_away", "rest_edge", "board_as_of",
)


def band_of(price: Optional[float]) -> Optional[str]:
    if price is None:
        return None
    for lo, hi, label in BANDS:
        if lo <= price <= hi:
            return label
    return None


def role_of(market: str, side: str, price: float) -> Optional[str]:
    """Favourite or underdog by the price's sign, for a side market; None for a total (over/under is not a role)."""
    if market == "total":
        return None
    return "favorite" if price < 0 else "underdog"


def open_market_board(quotes: Iterable[Mapping], market: str, *, lock: datetime, start: datetime, sport: str) -> Optional[dict]:
    """The market's consensus at the earliest capture instant inside the open window that has at least ``MIN_BOOKS`` books,
    if that instant is at least ``OPEN_MIN_LEAD`` before the lock. ``base.open_board`` does this for the moneyline only; this
    is the same rule for any market, with the same cut-offs (nothing after the lock, nothing at or after the start)."""
    lo = start - base.open_window(sport)
    instants: dict = {}
    for q in quotes:
        if q["market"] != market:
            continue
        obs = q["observed"]
        if obs < lo or obs > lock or obs >= start:
            continue
        instants.setdefault(obs, {})[q["book"]] = q
    for obs in sorted(instants):
        if obs > lock - base.OPEN_MIN_LEAD:
            return None
        books = instants[obs]
        if len(books) >= base.MIN_BOOKS:
            mb = base._market_board(list(books.values()), market)
            if mb is not None:
                return mb
    return None


def _rest_days(ctx: base.Context, team: Optional[str]) -> Optional[int]:
    """Whole days off before this game (0 = played the day before), from results that finished before the lock; None when the
    sport has no results store here or the stored days between the last game and this one are not all covered."""
    if not team:
        return None
    if ctx.sport == "mlb":
        games = base.mlb_team_games(ctx, team)
        if not games:
            return None
        last = date.fromisoformat(games[-1]["date"])
        today = date.fromisoformat(ctx.date)
        gap = [(last + timedelta(days=i)).isoformat() for i in range(1, (today - last).days)]
        if any(d not in ctx.mlb_covered for d in gap):
            return None
        return max(0, (today - last).days - 1)
    if ctx.sport == "nfl":
        games = base.nfl_team_games(ctx, team, season=base.nfl_season(ctx))
        kicks = [base.parse_utc(g.get("kickoff")) for g in games]
        kicks = [k for k in kicks if k is not None]
        if not kicks:
            return None
        return max(0, (ctx.start - max(kicks)).days)
    return None


def _pts(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(100.0 * value, 3)


def build(ctx: base.Context, board: Mapping, market: str, side: str, *, written: datetime,
          open_market: Optional[Mapping] = None) -> Optional[dict]:
    """The frozen feature dict for one candidate bet, or None when the side is not on the board."""
    from src.data.eastern import eastern

    mb = (board.get("markets") or {}).get(market)
    info = mb["sides"].get(side) if mb else None
    if not mb or not info:
        return None
    price, best = info["price_average"], info["price_best"]
    line = mb["line"]
    if market == "spread":
        pick_line = line if side == "home" else -line
    elif market == "total":
        pick_line = line
    else:
        pick_line = None
    be = base.break_even(price)
    start_et = ctx.start.astimezone(eastern())
    # The move since the open. A fair-probability move is only comparable when the line did not change, so it is None when
    # it did; the line's own move is recorded either way, in the pick's direction for a spread (negative = the side got
    # more points to give / fewer to get) and as the raw total for an over/under.
    open_fair = line_move = fair_move = None
    if open_market:
        o_info = open_market["sides"].get(side)
        o_line = open_market["line"]
        if o_info is not None:
            open_fair = o_info["fair"]
        if line is not None and o_line is not None:
            o_pick = (o_line if side == "home" else -o_line) if market == "spread" else o_line
            line_move = round(pick_line - o_pick, 3)
        if o_info is not None and (line is None or o_line == line):
            fair_move = info["fair"] - o_info["fair"]
    home_rest = _rest_days(ctx, ctx.home)
    away_rest = _rest_days(ctx, ctx.away)
    edge = None
    if market != "total" and home_rest is not None and away_rest is not None:
        edge = (home_rest - away_rest) if side == "home" else (away_rest - home_rest)
    return {
        "sport": ctx.sport, "league": ctx.league if ctx.sport not in ("mlb", "nfl") else None,
        "market": market, "side": side, "role": role_of(market, side, price),
        "venue": side if market != "total" else None,
        "price": price, "band": band_of(price), "line": pick_line,
        "abs_line": None if pick_line is None else abs(pick_line),
        "consensus_fair": info["fair"], "break_even": round(be, 6),
        "fair_minus_break_even": _pts(info["fair"] - be),
        "books": info["book_count"], "price_best": best,
        "best_vs_avg_pts": _pts(base.break_even(price) - base.break_even(best)),
        "open_fair": open_fair, "fair_move_pts": _pts(fair_move), "line_move": line_move,
        "hours_to_start": round((ctx.start - written).total_seconds() / 3600.0, 3),
        "day_of_week": start_et.strftime("%a").lower(), "start_hour_et": start_et.hour, "month": start_et.month,
        "is_weekend": start_et.weekday() >= 5,
        "rest_days_home": home_rest, "rest_days_away": away_rest, "rest_edge": edge,
        "board_as_of": board.get("as_of"),
    }


def segment_of(features: Mapping) -> Optional[tuple]:
    """The cell the learn step proposes over: (sport, market, kind, band). ``kind`` is the role for a side market and the side
    for a total, so "NHL favourites at -149 to -110" and "NBA unders at +100 to +180" are each one cell."""
    if not features:
        return None
    kind = features.get("role") if features.get("market") != "total" else features.get("side")
    if not (features.get("sport") and features.get("market") and kind and features.get("band")):
        return None
    return (features["sport"], features["market"], kind, features["band"])


KIND_WORDS = {"favorite": "favourites", "underdog": "plus-money sides", "over": "overs", "under": "unders"}
MARKET_WORDS = {"moneyline": "moneyline", "spread": "spread", "total": "totals"}


def segment_text(segment: Sequence) -> str:
    sport, market, kind, band = segment
    return f"{str(sport).upper()} {MARKET_WORDS.get(market, market)} {KIND_WORDS.get(kind, kind)}, {band}"
