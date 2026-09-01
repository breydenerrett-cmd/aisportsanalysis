"""JSON payload builders for the Odds tab: GET /odds/{date} and
GET /odds/{date}/{away}/{home}.

WHY THIS IS SEPARATE FROM src/analysis/prices.py
--------------------------------------------------
prices.py answers "how much better is the best price than the consensus"
(Engine 1 / price improvement) for one game at a time. The Odds tab wants a
different, wider thing: the WHOLE board (every book, every price) laid out
per game across a slate, plus a couple of slate-level summary numbers a
reader would otherwise have to compute by scanning every card by eye. This
module builds that shape from the same multi-book store prices.py already
reads (`prices.boards_by_matchup`) and prices.py's own de-vigging
(`prices.snapshot`) -- it does not re-derive the consensus or re-implement
de-vigging, it only reshapes and adds board-wide bookkeeping prices.py has
no reason to know about (spread across books, favorite disagreement).

MARKET STRUCTURE
-----------------
Only h2h (moneyline) exists today -- it is the only market the multi-book
store captures (src/pipeline/snapshots.py's `multibook_rows`). Every game's
payload nests its market(s) under a `markets` dict keyed by market name
(`"h2h"`) rather than putting h2h fields at the top level, so a future
market (spreads, totals) is an additional key, not a reshape of every
existing consumer.

EVIDENCE RULES, RESTATED AT THE WIRE (same as src/analysis/gamepayload.py)
---------------------------------------------------------------------------
- the de-vigged number is `market_implied_consensus` -- a probability implied
  by the board at one instant, never "the market's true read" and never a
  prediction.
- price improvement / best price is a better EXECUTION price (line-shopping
  value), never EV or edge.
- no win-probability field is emitted anywhere in this module.
- a market with no board, or a board below the book floor, says so with an
  explicit reason -- it never fabricates a placeholder price or consensus.

SPREAD-IN-CENTS -- WHAT IT IS AND IS NOT
------------------------------------------
`spread_cents` is the plain arithmetic gap between the best and worst quoted
American price on one side of the board (e.g. -105 best vs -120 worst is a
15-cent spread). It is a literal reading of the board, not a de-vigged or
probability-weighted figure, and it is not comparable across the -100/+100
sign boundary in a currency-consistent way (a -105-to-+100 gap and a
+100-to-+105 gap are not the same amount of "value" despite both reading 5).
It answers one question honestly -- "how far apart are the books quoting
this side" -- and no more than that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import gamepayload
from src.analysis import prices as prices_mod
from src.core import odds as odds_math

MARKETS = ("h2h",)  # the only market the multi-book store captures today

NO_BOARD_REASON = "no multi-book observations recorded for this game"


# ---------------------------------------------------------------------------
# Staleness -- same rule as api/today.py / src/analysis/gamepayload.py, kept
# as its own copy for the same reason those two keep separate copies: this
# module must stay importable without pulling in a sibling module's private
# helper just to compute one subtraction.
# ---------------------------------------------------------------------------

def _age_seconds(observed_utc: Optional[str], *, now: datetime) -> Optional[float]:
    """Seconds between an observed quote and `now`. None if there is nothing
    to age -- absence over a fabricated age of zero."""
    if not observed_utc:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max((now.astimezone(timezone.utc) - observed).total_seconds(), 0.0)


def _staleness(observed_utc: Optional[str], *, now: datetime, has_board: bool) -> dict:
    return {
        "observed_utc": observed_utc,
        "age_seconds": _age_seconds(observed_utc, now=now),
        "has_board": has_board,
    }


# ---------------------------------------------------------------------------
# Board -- the raw per-book quotes, unfiltered
# ---------------------------------------------------------------------------

def _board_rows(board_quotes: list) -> list:
    """The full book board, one row per book: book, away/home price, and
    when it was captured. `board_quotes` is the list `prices.latest_instant`
    already produced (via `prices.boards_by_matchup`) -- one row per book,
    all sharing the newest capture instant for this game.
    """
    return [{
        "book": row.get("book"),
        "away_price": row.get("away_price"),
        "home_price": row.get("home_price"),
        "captured_at": row.get("ts"),
    } for row in board_quotes or []]


# ---------------------------------------------------------------------------
# Best price per side -- every book quoting it, not just the first found
# ---------------------------------------------------------------------------

def _decimal_or_none(price):
    try:
        return odds_math.american_to_decimal(price)
    except odds_math.OddsError:
        return None


def _best_price_side(board_quotes: list, price_key: str) -> Optional[dict]:
    """The best (highest-payout) American price on one side, and EVERY book
    quoting it -- a tie is common (two books at the market-leading number)
    and naming only one would hide the other's identical price.
    """
    best_decimal = None
    best_price = None
    for row in board_quotes or []:
        price = row.get(price_key)
        decimal = _decimal_or_none(price)
        if decimal is None:
            continue
        if best_decimal is None or decimal > best_decimal:
            best_decimal, best_price = decimal, price
    if best_decimal is None:
        return None
    books = sorted({row.get("book") for row in board_quotes
                    if row.get(price_key) == best_price and row.get("book")})
    return {"price": best_price, "books": books}


def _spread_cents_side(board_quotes: list, price_key: str) -> Optional[float]:
    """See the module docstring's SPREAD-IN-CENTS note. None below two
    priced quotes -- a spread needs two numbers to be apart from each other."""
    prices = [row.get(price_key) for row in board_quotes or []
              if row.get(price_key) is not None]
    if len(prices) < 2:
        return None
    return max(prices) - min(prices)


# ---------------------------------------------------------------------------
# Consensus -- probability AND its price restatement
# ---------------------------------------------------------------------------

def _consensus_section(snapshot: dict) -> Optional[dict]:
    """Market-implied consensus, per side, as both a probability and the
    American price that probability implies -- never a prediction, never
    "true". `snapshot` is whatever `prices.snapshot` already computed; this
    function only reshapes it, it does not re-devig anything.
    """
    if "skipped" in snapshot:
        return None
    sides = snapshot.get("sides") or {}
    out = {}
    for side, detail in sides.items():
        if "skipped" in detail:
            out[side] = {"skipped": detail["skipped"]}
            continue
        probability = detail.get("consensus_probability")
        out[side] = {
            "implied_probability": probability,
            "implied_price": (round(odds_math.probability_to_american(probability))
                              if probability is not None else None),
        }
    out["books"] = (snapshot.get("dispersion") or {}).get("books")
    return out


# ---------------------------------------------------------------------------
# Per-game, per-market payload
# ---------------------------------------------------------------------------

def build_market_h2h(board: Optional[dict], *, now: datetime) -> dict:
    """The h2h market section for one game: board, best price, consensus,
    spread, staleness -- or an explicit unavailable state at each level a
    board can fall short at (no board at all; a board thinner than the
    book floor `prices.MIN_BOOKS` still shows raw prices, just no consensus).
    """
    quotes = (board or {}).get("quotes") or []
    observed_utc = (board or {}).get("observed_utc")
    has_board = bool(quotes)
    if not has_board:
        return {
            "board_available": False,
            "reason": NO_BOARD_REASON,
            "board": [],
            "best": None,
            "consensus": None,
            "spread_cents": {"away": None, "home": None},
            "staleness": _staleness(None, now=now, has_board=False),
        }
    snapshot = prices_mod.snapshot(quotes)
    consensus = _consensus_section(snapshot)
    return {
        "board_available": True,
        "reason": None,
        "board": _board_rows(quotes),
        "best": {
            "away": _best_price_side(quotes, "away_price"),
            "home": _best_price_side(quotes, "home_price"),
        },
        "consensus": consensus,
        "consensus_unavailable_reason": (
            None if consensus is not None else snapshot.get("skipped")),
        "spread_cents": {
            "away": _spread_cents_side(quotes, "away_price"),
            "home": _spread_cents_side(quotes, "home_price"),
        },
        "staleness": _staleness(observed_utc, now=now, has_board=True),
    }


MARKET_BUILDERS = {"h2h": build_market_h2h}


def build_game_markets(board: Optional[dict], *, now: datetime) -> dict:
    """Every market this module knows how to build for one game. h2h is the
    only entry today; a future market is an additional key here, and every
    caller that iterates `markets` picks it up with no reshape."""
    return {name: builder(board, now=now) for name, builder in MARKET_BUILDERS.items()}


def _favorite_side(row: dict) -> Optional[str]:
    """Which side one book's raw (not de-vigged) quote favors -- the side
    with the lower American price / higher raw implied probability. Used
    only for the slate-level "books disagree on favorite" count, which is a
    board-shape observation, not a probability claim, so raw prices (not the
    de-vigged consensus) are the right input: two books can each be internally
    consistent and still call a different side the favorite.
    """
    away, home = row.get("away_price"), row.get("home_price")
    away_p = _decimal_or_none(away)
    home_p = _decimal_or_none(home)
    if away_p is None or home_p is None:
        return None
    if away_p == home_p:
        return None
    return "home" if home_p < away_p else "away"


def _books_disagree_on_favorite(quotes: list) -> Optional[bool]:
    """True when this game's books do not unanimously agree which side is
    favored. None when there is not enough priced data to judge (fewer than
    two books with a determinable favorite) -- absence over a guessed False.
    """
    favorites = {f for f in (_favorite_side(row) for row in quotes or [])
                if f is not None}
    if len(favorites) == 0:
        return None
    return len(favorites) > 1


# ---------------------------------------------------------------------------
# One game's full odds payload
# ---------------------------------------------------------------------------

def build_game_odds(game: dict, board: Optional[dict], *, now: datetime) -> dict:
    """The Odds-tab payload for one game: identity plus every market."""
    return {
        "game_id": gamepayload.game_id(game),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "date": game.get("date"),
        "first_pitch_utc": game.get("start_time_utc"),
        "venue": game.get("venue"),
        "markets": build_game_markets(board, now=now),
    }


# ---------------------------------------------------------------------------
# Slate-level summary
# ---------------------------------------------------------------------------

def _widest_spread_game(game_odds: list) -> Optional[dict]:
    """The game (and side) with the largest h2h spread_cents on the slate.
    None when nothing on the slate has a priceable spread at all."""
    best = None
    for entry in game_odds:
        spreads = entry["markets"].get("h2h", {}).get("spread_cents") or {}
        for side, value in spreads.items():
            if value is None:
                continue
            if best is None or value > best["spread_cents"]:
                best = {"game_id": entry["game_id"], "side": side,
                        "spread_cents": value}
    return best


def build_slate_summary(game_odds: list, boards_by_id: dict) -> dict:
    """Slate-level Odds-tab summary: games count, the single widest h2h
    spread on the board, and how many games' books do not unanimously agree
    on the favorite.
    """
    disagree_count = 0
    for entry in game_odds:
        quotes = (boards_by_id.get(entry["game_id"]) or {}).get("quotes") or []
        if _books_disagree_on_favorite(quotes):
            disagree_count += 1
    return {
        "games_count": len(game_odds),
        "widest_spread_game": _widest_spread_game(game_odds),
        "books_disagree_on_favorite_count": disagree_count,
    }


def build_odds_payload(games: list, boards: dict, *, date: Optional[str] = None,
                       now: Optional[datetime] = None) -> dict:
    """The full GET /odds/{date} payload.

    `games` is the date's schedule (src.providers.mlb.fetch_games shape);
    `boards` is keyed the way `prices.matchup_key` keys it -- the caller
    looks each game's board up with that key so this function never has to
    know how the multi-book store files its rows.
    """
    now = now or datetime.now(timezone.utc)
    game_odds = []
    boards_by_id = {}
    for game in games:
        key = prices_mod.matchup_key(game.get("away_team"), game.get("home_team"),
                                     game.get("date"))
        board = boards.get(key)
        entry = build_game_odds(game, board, now=now)
        game_odds.append(entry)
        boards_by_id[entry["game_id"]] = board
    return {
        "date": date,
        "generated_at": now.isoformat(),
        "games": game_odds,
        "summary": build_slate_summary(game_odds, boards_by_id),
    }
