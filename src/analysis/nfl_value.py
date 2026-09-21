"""NFL_CARD_V2 -- value lines, not favourites.

WHY THIS REPLACES NFL_CARD_V1
-----------------------------
V1 took whichever side the market made more likely, in every game, ranked by
how likely -- a favourites list by construction. On 2026-09-20 it published
San Francisco -950, Tampa Bay -420, Baltimore -380 and Kansas City -278. The
owner's ruling that day: a moneyline at -200 or worse is never a bet, and the
value in the NFL is on the point spread and the game total, not on picking
winners.

THE RULE, PRE-REGISTERED 2026-09-20 (before any V2 pick exists or is graded)
---------------------------------------------------------------------------
Every constant below is fixed here, in code, before a single V2 card has been
published, so none of it can be chosen in view of results. Registration:
docs/PREREG_NFL_CARD_V2.md.

  1. MARKETS: the point spread, the game total, and the moneyline.
  2. HARD PRICE RULE: no selection priced at -200 or worse is ever a
     candidate, in any market (owner ruling, 2026-09-20).
  3. FRESH QUOTES ONLY: each book's LATEST quote per game and market, and
     only if that book updated within `FRESH_SECONDS` of the newest update
     any book posted for the same game and market. A stale quote is the
     single most common source of fake value -- a book that has not moved
     yet looks "generous" until it does. AND the newest quote for that game
     and market must itself be no more than `FRESH_BOARD_SECONDS` older
     than the run: a board every book stopped updating on together is
     stale as a whole, and the book-vs-book test cannot see it.
  4. LEAVE-ONE-BOOK-OUT FAIR PRICE: a price at book B is judged against the
     de-vigged consensus of every OTHER book quoting the SAME line (same
     spread number, same total number). Book B is never part of the
     consensus it is measured against. At least `MIN_OTHER_BOOKS` other
     books must quote that exact line, or the line is not judged at all.
  5. VALUE: expected value = fair probability x decimal price - 1, at book
     B's price, computed once per de-vig method in `DEVIG_METHODS`. A
     selection is a candidate only if it is at least `MIN_EV` under EVERY
     one of them, and the fair probability and EV the card shows are the
     lowest of the three.
  6. One pick per game (its highest-value candidate). Rank by value.
     Publish at most `MAX_PICKS`.

Rules 3 (board age) and 5 (all three methods) were corrected 2026-09-21,
after review and before the registration commit -- no V2 pick had been
published. docs/PREREG_NFL_CARD_V2.md records both and why.

WHAT THIS DOES AND DOES NOT CLAIM
---------------------------------
It finds prices that are better than the rest of the market is offering for
the same bet. That is a statement about the PRICE, not a prediction that the
bet wins: the fair probability comes from the market itself, so a pick here
is "this book is paying more than the other books think this is worth", not
"we know something the market does not". Whether prices like these win over
time is exactly what the forward record exists to find out.

Pure functions: every input arrives as an argument.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional, Sequence

from src.core import odds as odds_math

RULE_ID = "NFL_CARD_V2"
MODEL_ID = "nfl_value_lines_v2"

# Owner ruling 2026-09-20: -200 or worse is never a bet. Applied to every
# market, not just the moneyline -- a spread or total at that juice is the
# same bad price by a different name.
WORST_PRICE = -200
MIN_OTHER_BOOKS = 5
MIN_EV = 0.02
FRESH_SECONDS = 30 * 60
# Review, 2026-09-21: `FRESH_SECONDS` only compares books with each other.
# On 2026-09-20 NFL capture stopped at 04:01Z and the card still ran from
# 14:37Z to 20:29Z; every book on that board was equally 10-16 hours old, so
# all of them passed, and V2 would have published and locked IND@KC Over
# 46.5 +110 -- a price no book was still offering. While NFL capture is
# running its snapshots land about 9-20 minutes apart (94 of the 99 gaps in
# the store to 2026-09-21 03:51Z; the other 5 are capture stopping for about
# 20 to 27.5 hours -- the pre-2026-09-21 capture-commit loss, which threw
# away every daytime snapshot), so a board whose newest quote is over an
# hour old means capture stopped, not that the market is quiet.
FRESH_BOARD_SECONDS = 60 * 60
# Review, 2026-09-21: proportional de-vig alone leaves too much probability
# on the long shot (src/core/odds.py says so, and says an edge that survives
# only one method is fragile). Replayed over the store's 100 NFL capture
# instants to 2026-09-21 03:51Z, proportional alone gave 17 candidates, 16 of
# them plus-money moneyline dogs; under all three, 1 (a total) and no dog.
# The same all-methods rule as src/pipeline/predict.py's
# `disagreement_is_robust` and the F5/totals evals'
# `devig_sign_survives_check`.
DEVIG_METHODS = ("proportional", "shin", "power")
MAX_PICKS = 5
# At or above both: STRONG. Otherwise LEAN. Labels only -- ranking is by EV.
STRONG_EV = 0.04
STRONG_BOOKS = 8

LABEL_STRONG = "STRONG"
LABEL_LEAN = "LEAN"

CARD_BASIS = (
    "Each pick is a price that is better than the rest of the market is "
    "offering for the exact same bet -- same spread, same total. The fair "
    "price comes from every other sportsbook quoting that line, with the "
    "vig removed, and the book offering the pick is never part of the "
    "average it is judged against. The vig is removed three standard ways; "
    "a pick has to clear under all three, and the figure shown is the "
    "lowest. A game is judged only when its newest price is under an hour "
    "old, and each book's price is compared only if it is within half an "
    "hour of that newest one. Moneylines at -200 or worse are never picked."
)
CARD_DISCLAIMER = (
    "This is analysis, not advice, and not a guarantee. Value here means the "
    "price beats the market's own consensus; it does not mean the bet will "
    "win, and the fair price comes from the market itself, not from a model "
    "of the game. Every pick is published before kickoff and graded win or "
    "lose. NFL_CARD_V2 is a new test -- bet at your own risk."
)


def _fmt_price(american) -> str:
    if american is None:
        return "—"
    n = int(round(float(american)))
    return f"+{n}" if n > 0 else str(n)


def _fmt_line(line: float) -> str:
    return f"{line:+g}"


def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_ok(american) -> bool:
    """Usable, and better than WORST_PRICE (so -199 passes, -200 does not)."""
    try:
        n = float(american)
    except (TypeError, ValueError):
        return False
    return n > WORST_PRICE


def latest_quotes(rows: Iterable[Mapping]) -> dict:
    """{(event_id, market, book): newest row}. `market` None means h2h."""
    latest: dict = {}
    for row in rows:
        key = (row.get("event_id"), row.get("market") or "h2h", row.get("book"))
        seen = latest.get(key)
        if seen is None or str(row.get("observed_utc") or "") >= str(seen.get("observed_utc") or ""):
            latest[key] = row
    return latest


def _quote_time(row: Mapping) -> Optional[datetime]:
    """When a quote was last current: the book's own update time, else the
    capture time."""
    return _parse_utc(row.get("book_last_update")) or _parse_utc(row.get("observed_utc"))


def _fresh(rows: Sequence[Mapping]) -> list:
    """Drop quotes whose book last updated more than FRESH_SECONDS before the
    newest update on the same game and market."""
    stamps = [(_quote_time(r), r) for r in rows]
    stamps = [(t, r) for t, r in stamps if t is not None]
    if not stamps:
        return []
    newest = max(t for t, _ in stamps)
    floor = newest - timedelta(seconds=FRESH_SECONDS)
    return [r for t, r in stamps if t >= floor]


def board_is_fresh(rows: Sequence[Mapping], *, now: datetime) -> bool:
    """True when the newest quote in `rows` (one game and market) is no more
    than FRESH_BOARD_SECONDS older than `now`. A board with no datable quote
    is not fresh."""
    stamps = [t for t in (_quote_time(r) for r in rows) if t is not None]
    if not stamps:
        return False
    return (now - max(stamps)).total_seconds() <= FRESH_BOARD_SECONDS


def _upcoming_boards(rows: Iterable[Mapping], *, now: datetime) -> dict:
    """{(event_id, market): [each book's latest row]} for games not yet
    kicked off, in the three markets V2 judges."""
    boards: dict = defaultdict(list)
    for (event_id, market, _book), row in latest_quotes(rows).items():
        if market not in ("spreads", "totals", "h2h"):
            continue
        kickoff = _parse_utc(row.get("commence_time"))
        if kickoff is None or kickoff <= now:
            continue
        boards[(event_id, market)].append(row)
    return boards


def has_fresh_board(rows: Iterable[Mapping], *, now: datetime) -> bool:
    """Whether any upcoming game and market in `rows` passes the
    FRESH_BOARD_SECONDS gate -- so an empty card can say "the prices are too
    old to judge" instead of "we judged them and declined"."""
    return any(board_is_fresh(board, now=now)
               for board in _upcoming_boards(rows, now=now).values())


def _two_way(row: Mapping, market: str) -> Optional[tuple]:
    """(line_key, [(side, line, price), (side, line, price)]) for one quote.

    spreads: line_key is the HOME line; sides are home/away with their own
    signed lines. totals: line_key is the total; sides are over/under.
    h2h: line_key is None; sides are home/away.
    """
    if market == "spreads":
        home_line, away_line = _float(row.get("home_line")), _float(row.get("away_line"))
        if home_line is None or away_line is None:
            return None
        return (home_line, [("home", home_line, row.get("home_price")),
                            ("away", away_line, row.get("away_price"))])
    if market == "totals":
        total = _float(row.get("total"))
        if total is None:
            return None
        return (total, [("over", total, row.get("over_price")),
                        ("under", total, row.get("under_price"))])
    if market == "h2h":
        return (None, [("home", None, row.get("home_price")),
                       ("away", None, row.get("away_price"))])
    return None


def _devig(pair: Sequence[tuple]) -> Optional[dict]:
    """{method: {side: fair probability}} from one book's two prices, one
    entry per method in DEVIG_METHODS -- or None if any method cannot price
    it. A quote one method cannot de-vig cannot be said to clear under that
    method, so it is neither judged nor part of anyone's consensus."""
    (side_a, _, price_a), (side_b, _, price_b) = pair
    out = {}
    for method in DEVIG_METHODS:
        try:
            fair_a, fair_b = odds_math.devig_two_way(price_a, price_b, method=method)
        except (odds_math.OddsError, TypeError, ValueError):
            return None
        out[method] = {side_a: fair_a, side_b: fair_b}
    return out


def value_candidates(rows: Iterable[Mapping], *, now: datetime) -> list:
    """Every (game, market, line, side, book) whose price clears MIN_EV
    against the leave-one-book-out consensus under every de-vig method. One
    dict per candidate; not yet de-duplicated to one per game."""
    out = []
    for (event_id, market), rows_here in _upcoming_boards(rows, now=now).items():
        if not board_is_fresh(rows_here, now=now):
            continue
        fresh = _fresh(rows_here)
        # {line_key: [(book, row, {method: {side: fair}}, pair)]}
        by_line: dict = defaultdict(list)
        for row in fresh:
            parsed = _two_way(row, market)
            if parsed is None:
                continue
            line_key, pair = parsed
            fair = _devig(pair)
            if fair is None:
                continue
            by_line[line_key].append((row.get("book"), row, fair, pair))

        for line_key, quotes in by_line.items():
            for book, row, _own_fair, pair in quotes:
                others = [f for b, _r, f, _p in quotes if b != book]
                if len(others) < MIN_OTHER_BOOKS:
                    continue
                for side, line, price in pair:
                    if not _price_ok(price):
                        continue
                    try:
                        decimal = odds_math.american_to_decimal(price)
                    except (odds_math.OddsError, TypeError, ValueError):
                        continue
                    # {method: (ev, fair)}. The price is the same under every
                    # method, so the lowest EV is also the lowest fair
                    # probability: clearing MIN_EV there IS clearing it under
                    # all three, and it is the figure the card shows.
                    by_method = {}
                    for method in DEVIG_METHODS:
                        fair_m = sum(f[method][side] for f in others) / len(others)
                        by_method[method] = (fair_m * decimal - 1.0, fair_m)
                    binding = min(DEVIG_METHODS, key=lambda m: by_method[m][0])
                    ev, fair_p = by_method[binding]
                    if ev < MIN_EV:
                        continue
                    out.append({
                        "event_id": event_id, "market": market, "line": line,
                        "side": side, "price": price, "book": book,
                        "fair_probability": fair_p, "ev": ev,
                        "devig_method": binding,
                        "ev_by_method": {m: by_method[m][0] for m in DEVIG_METHODS},
                        "n_other_books": len(others),
                        "home_team": row.get("home_team"),
                        "away_team": row.get("away_team"),
                        "commence_time": row.get("commence_time"),
                    })
    return out


def _bet_text(cand: Mapping) -> str:
    price = _fmt_price(cand["price"])
    if cand["market"] == "totals":
        word = "Over" if cand["side"] == "over" else "Under"
        return (f"{word} {cand['line']:g} points -- {cand['away_team']} at "
                f"{cand['home_team']} -- at {price}")
    team = cand["home_team"] if cand["side"] == "home" else cand["away_team"]
    if cand["market"] == "spreads":
        return f"Take {team} {_fmt_line(cand['line'])} at {price}"
    return f"Take {team} to win at {price}"


def _why(cand: Mapping) -> list:
    fair_pct = cand["fair_probability"] * 100.0
    ev_pct = cand["ev"] * 100.0
    # Both figures are the most cautious of the three de-vig methods (rule 5).
    return [
        f"{cand['n_other_books']} other sportsbooks quoting this exact line put "
        f"its fair chance at {fair_pct:.1f}% once their margin is removed -- "
        "the lowest of three standard ways of removing it.",
        f"At {_fmt_price(cand['price'])} with {cand['book']}, that works out to "
        f"about {ev_pct:.1f}% more than the bet is worth on the market's own "
        "numbers -- a better price, not a prediction.",
    ]


def select(rows: Iterable[Mapping], *, now: datetime,
           game_ids: Optional[Mapping] = None,
           max_picks: int = MAX_PICKS) -> list:
    """The published V2 picks: one per game, ranked by value, capped.

    `game_ids` maps (home_team, away_team) full names to the schedule's
    game_id, which settlement keys results on. A game with no schedule id
    is skipped -- a pick nobody can grade is not a pick.
    """
    best_per_game: dict = {}
    for cand in value_candidates(rows, now=now):
        key = cand["event_id"]
        if key not in best_per_game or cand["ev"] > best_per_game[key]["ev"]:
            best_per_game[key] = cand

    ranked = sorted(best_per_game.values(), key=lambda c: -c["ev"])
    picks = []
    for cand in ranked:
        if len(picks) >= max_picks:
            break
        game_id = (game_ids or {}).get((cand["home_team"], cand["away_team"]))
        if game_id is None:
            continue
        market = {"spreads": "spread", "totals": "total", "h2h": "moneyline"}[cand["market"]]
        strong = cand["ev"] >= STRONG_EV and cand["n_other_books"] >= STRONG_BOOKS
        picks.append({
            "game_id": game_id,
            "rank": len(picks) + 1,
            "sport": "nfl",
            "home_team": cand["home_team"],
            "away_team": cand["away_team"],
            "side": cand["side"],
            "team": (cand["home_team"] if cand["side"] == "home"
                     else cand["away_team"] if cand["side"] == "away" else None),
            "market": market,
            "line": cand["line"],
            "price": cand["price"],
            "book": cand["book"],
            "market_probability": round(cand["fair_probability"], 4),
            "model_probability": None,
            "value_pct": round(cand["ev"] * 100.0, 2),
            "n_other_books": cand["n_other_books"],
            "label": LABEL_STRONG if strong else LABEL_LEAN,
            "bet": _bet_text(cand),
            "why": _why(cand),
            "kickoff_utc": cand["commence_time"],
            "first_pitch_utc": cand["commence_time"],
            "experimental": True,
        })
    return picks
