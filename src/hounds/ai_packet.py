"""The packet an AI hound is shown for ONE game, and the two strings that carry it to a model.

WHAT GOES IN (and the lock is the wall)
---------------------------------------
Everything here is point-in-time at the game's LOCK (60 minutes before the start; ``pack.base.LOCK_MINUTES``):

  game       the two clubs' names, the sport, the Eastern date, the start and the lock.
  markets    for each market on the lock board: the main line, how many books quote it, and per side the
             average price, the best price and its book, the book count and the consensus fair probability
             (``base.build_board``: each book's newest quote at or before the lock, none from the start on),
             plus ``by_book``, every book's own two prices on that line.
  movement   the moneyline's consensus fair probability when it first had enough books, against now
             (``base.open_board``), or an honest "no earlier board" when there is none.
  form       the two clubs' recent results from the stores the pack already reads, dated before the game and
             finished at least five (MLB) or six (NFL) hours before the lock, never inside the SEALED window:
             games played, record, runs or points for and against per game, the last five results. This
             exists for MLB and NFL ONLY. Every other family (NBA, NHL, soccer, tennis ...) has no results
             store here, so its packet carries prices and movement alone and says so in ``form.basis``.
  news       whatever the injected ``news_fn`` returns for this game, kept only if its ``observed_utc`` is at
             or before the lock. v1 wires no news source (none of the free ones is point-in-time safe), so
             this is an empty list and the packet says so.

WHAT NEVER GOES IN: a person (an account, an email, a name from the app database), a bet or a record of any
hound, an outcome of this game, any quote observed after the lock. ``render_prompt`` returns the system
text and one compact JSON user message; the router's prompt guard checks both again before anything is sent.

Pure functions of their arguments: no clock, no network, no store reads.
"""

from __future__ import annotations

import json
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.ai.decision import SYSTEM_PROMPT
from src.hounds import ai_defs
from src.hounds.pack import base

# What a game's total is counted in, by catalog family. The wording is the model's only clue to the scale of a
# line, so it is named per sport; a family not listed here is "points".
TOTAL_UNIT = {"MLB": "runs", "BASEBALL": "runs", "CRICKET": "runs", "NHL": "goals", "HOCKEY": "goals",
              "SOCCER": "goals", "TENNIS": "games"}
STATS_FAMILIES = ("mlb", "nfl")        # the families whose recent results our stores hold (see ``form``)
FORM_LAST_N = 5
NEWS_KEEP = 5
NEWS_TEXT_CHARS = 240

NewsFn = Callable[["base.Context"], Sequence[Mapping]]


def _side(info: Mapping) -> dict:
    return {"avg_price": info["price_average"], "best_price": info["price_best"], "best_book": info["book"],
            "books": info["book_count"], "fair_prob": info["fair"]}


def by_book(quotes: Iterable[Mapping], ctx: "base.Context", market: str, line: Optional[float]) -> List[dict]:
    """Every book's newest quote on the board's main line at the lock (same rule as ``board_at_line``)."""
    max_age = base.max_quote_age(ctx.sport)
    newest: Dict[str, Mapping] = {}
    for q in quotes:
        if q["market"] != market or q["line"] != line:
            continue
        obs = q["observed"]
        if obs > ctx.lock or obs >= ctx.start or obs < ctx.lock - max_age:
            continue
        if q["book"] not in newest or obs > newest[q["book"]]["observed"]:
            newest[q["book"]] = q
    a, b = base.SIDES[market]
    usable = dict(newest)
    if market == "moneyline" and any(q.get("draw") is not None for q in newest.values()):
        usable = {k: q for k, q in newest.items() if q.get("draw") is not None}     # the same books the board used
    out = []
    for name, q in sorted(usable.items()):
        row = {"book": name, a: int(round(q["prices"][a])), b: int(round(q["prices"][b]))}
        if q.get("draw") is not None:
            row["draw"] = int(round(q["draw"]))
        out.append(row)
    return out


def movement(ctx: "base.Context", board: Mapping) -> dict:
    """How the moneyline's consensus moved from its first usable board to the lock board."""
    now = (board.get("markets") or {}).get("moneyline")
    first = (ctx.open_board or {}).get("markets", {}).get("moneyline")
    if not now or not first:
        return {"moneyline": None, "note": "no earlier board at least 60 minutes before the lock"}
    return {"moneyline": {
        "first_board_utc": ctx.open_board["as_of"], "home_fair_prob_first": first["sides"]["home"]["fair"],
        "home_fair_prob_now": now["sides"]["home"]["fair"],
        "home_fair_prob_change_pts": round(100.0 * (now["sides"]["home"]["fair"] - first["sides"]["home"]["fair"]), 2),
        "home_avg_price_first": first["sides"]["home"]["price_average"],
        "home_avg_price_now": now["sides"]["home"]["price_average"]}}


def _form_mlb(ctx: "base.Context", team: Optional[str]) -> dict:
    games = base.mlb_team_games(ctx, team) if team else []
    if not games:
        return {"club": team, "games": 0}
    wins = sum(1 for g in games if g["won"])
    n = len(games)
    return {"club": team, "games": n, "wins": wins, "losses": n - wins,
            "runs_for_per_game": round(sum(g["rf"] for g in games) / n, 2),
            "runs_against_per_game": round(sum(g["ra"] for g in games) / n, 2),
            "last5": "".join("W" if g["won"] else "L" for g in games[-FORM_LAST_N:])}


def _form_nfl(ctx: "base.Context", team: Optional[str]) -> dict:
    games = base.nfl_team_games(ctx, team, season=base.nfl_season(ctx)) if team else []
    if not games:
        return {"club": team, "games": 0}
    n = len(games)
    wins = sum(1 for g in games if g["won"])
    ties = sum(1 for g in games if g["tied"])
    return {"club": team, "games": n, "wins": wins, "losses": n - wins - ties, "ties": ties,
            "points_for_per_game": round(sum(g["pf"] for g in games) / n, 2),
            "points_against_per_game": round(sum(g["pa"] for g in games) / n, 2),
            "last5": "".join("T" if g["tied"] else ("W" if g["won"] else "L") for g in games[-FORM_LAST_N:])}


def form(ctx: "base.Context") -> dict:
    if ctx.sport == "mlb":
        return {"basis": f"MLB results from {base.SEAL_FLOOR} to the day before this game",
                "away": _form_mlb(ctx, ctx.away), "home": _form_mlb(ctx, ctx.home)}
    if ctx.sport == "nfl":
        return {"basis": "NFL results this season before this game",
                "away": _form_nfl(ctx, ctx.away), "home": _form_nfl(ctx, ctx.home)}
    return {"basis": f"no team results are stored for {_label(ctx.sport)}; only the prices and how they moved are shown",
            "available": False}


def _label(sport: str) -> str:
    from src.sports import catalog

    return catalog.label(str(sport).upper())


def is_three_way(ctx: "base.Context", board: Mapping) -> bool:
    """True when this game's moneyline is a three-way market: the family allows a draw AND the board carries one."""
    from src.sports import catalog

    ml = (board.get("markets") or {}).get("moneyline") or {}
    return "draw" in (ml.get("sides") or {}) and catalog.draw_possible(str(ctx.sport).upper())


def total_unit(ctx: "base.Context") -> str:
    return TOTAL_UNIT.get(str(ctx.sport).upper(), "points")


def rules_note(ctx: "base.Context", board: Mapping, allowed: Sequence[str]) -> str:
    """Plain-English rules for a game outside MLB and NFL: what may be backed and what a draw does. Not added to
    MLB and NFL packets, which stay exactly the pre-registered ones."""
    allowed = list(allowed)
    parts = [f"The markets you may bet here are: {', '.join(allowed) or 'none'}. Choose only from the markets listed in the data."]
    if is_three_way(ctx, board):
        parts.append("The moneyline is THREE-WAY: home win, away win or a draw. A draw loses a moneyline bet on "
                     "either team, so the draw is a real risk. You may back only home or away; the draw cannot be "
                     "backed. fair_prob for home, away and draw sum to 1.")
    elif "moneyline" in allowed and ctx.sport in ("tennis", "mma"):
        parts.append("The moneyline is the match winner (two outcomes, no draw).")
    if allowed == ["moneyline"]:
        parts.append("Only the moneyline is available for this sport.")
    return " ".join(parts)


def news_items(ctx: "base.Context", news_fn: Optional[NewsFn]) -> List[dict]:
    """News the injected source returned, kept only if observed at or before the lock."""
    if news_fn is None:
        return []
    out = []
    for item in news_fn(ctx) or ():
        seen = base.parse_utc(item.get("observed_utc"))
        text = str(item.get("text") or "").strip()
        if seen is None or seen > ctx.lock or not text:
            continue
        out.append({"observed_utc": base.iso(seen), "text": text[:NEWS_TEXT_CHARS]})
    return out[:NEWS_KEEP]


def allowed_markets(ctx: "base.Context", configured: Optional[Sequence[str]] = None) -> List[str]:
    """The markets the model may be shown and may back for this game's family (``ai_defs.markets_for_sport``)."""
    return list(ai_defs.markets_for_sport(ctx.sport, configured or base.MARKETS))


def build_packet(ctx: "base.Context", board: Mapping, quotes: Sequence[Mapping], *,
                 news_fn: Optional[NewsFn] = None, configured_markets: Optional[Sequence[str]] = None) -> dict:
    allowed = allowed_markets(ctx, configured_markets)
    markets = {}
    for market, mb in (board.get("markets") or {}).items():
        if market not in allowed:
            continue
        entry = {"line": mb["line"], "books": mb["books"],
                 "sides": {side: _side(info) for side, info in mb["sides"].items()},
                 "by_book": by_book(quotes, ctx, market, mb["line"])}
        if market == "spread":
            entry["line_note"] = "the HOME team's line; the away side gets the opposite"
        if market == "total":
            entry["line_note"] = "total runs" if ctx.sport == "mlb" else f"total {total_unit(ctx)}"
        if market == "moneyline" and "draw" in mb["sides"]:
            entry["line_note"] = "three-way: home, away or draw; the draw is shown for information and cannot be backed"
        markets[market] = entry
    game = {"sport": ctx.sport.upper(), "away": ctx.away_name, "home": ctx.home_name, "date_et": ctx.date,
            "start_utc": base.iso(ctx.start), "lock_utc": base.iso(ctx.lock), "board_as_of_utc": board.get("as_of")}
    if ctx.sport not in STATS_FAMILIES and ctx.league:
        game["league"] = ctx.league
    packet = {
        "game": game,
        "markets": markets,
        "movement": movement(ctx, board),
        "form": form(ctx),
        "news": news_items(ctx, news_fn),
        "news_note": "no news source is wired in this version" if news_fn is None else None,
        "price_rule": "a side whose average price is -200 or worse is never accepted",
    }
    if ctx.sport not in STATS_FAMILIES:
        packet["rules_note"] = rules_note(ctx, board, allowed)
    return packet


def render_prompt(packet: Mapping) -> Tuple[str, str]:
    """``(system, user)``: the fixed rules, and the packet as one compact JSON message."""
    user = "Game data, all times UTC:\n" + json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return SYSTEM_PROMPT, user


def packet_hash(packet: Mapping) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
