"""One streaming pass over the captured odds, for every hound bet at once.

For each bet this answers three questions from the multi-book store
(``data/processed/odds_multibook.jsonl`` plus its cold archive), read-only:

  verified   was the price the hound recorded really on the board at its
             decision time? The last capture at or before the decision, for
             that game, market and line, must hold a quote on the same side at
             the same price from the same book (any book when the hound's
             record names none).
  average    the mean decimal price of the books quoting that exact selection
             on that board, when at least ``MIN_AVERAGE_BOOKS`` did: the
             price a bettor who shopped nothing would have seen, used for
             ``units_average_price``.
  CLV        the existing ``src.report.clv.measure_decision`` (unchanged),
             handed a ``pregame_index`` built from the same pass.

WHY A SPECIAL PASS INSTEAD OF ``clv.measure``. The store is ~1,000,000 rows.
``clv.pregame_index()`` materialises all of them (hundreds of MB), which is
exactly the 2026-09-10 and 2026-10-01 memory incidents. Here a row is parsed,
looked at and dropped; what survives is, per (game, market), the last few
pre-game capture instants (the closing board and the few before it, enough for
the second pre-game guard in ``pregame_index``) and, per distinct decision
time, the single latest board at or before it. The kept rows are then handed
to the unchanged ``clv.pregame_index`` so the closing definition is exactly the
project's, not a copy of it.

The pass is the expensive part (a few seconds) and runs once per change of the
inputs (``src.hounds.stats`` caches on file size and mtime).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from src.core import odds as odds_math
from src.report import clv

MIN_AVERAGE_BOOKS = 3          # same floor as src.analysis.prices.MIN_BOOKS (6) is for
                               # a consensus; an average price only needs a board
CLOSING_INSTANTS_KEPT = 4      # last pre-game instants kept per (game, market)

_PRICE_KEYS = ("away_price", "home_price", "away_line", "home_line", "total",
               "over_price", "under_price")


def _book_key(name) -> str:
    return "".join(c for c in str(name or "").lower() if c.isalnum())


def _trim(row: dict) -> dict:
    out = {"observed_utc": row.get("observed_utc"),
           "event_id": row.get("event_id"),
           "commence_time": row.get("commence_time"),
           "market": row.get("market"), "book": row.get("book")}
    for key in _PRICE_KEYS:
        if key in row:
            out[key] = row[key]
    return out


class BoardFacts:
    """What the stored odds say about one bet."""
    __slots__ = ("avg_price", "avg_books", "verified", "checkable")

    def __init__(self):
        self.avg_price = None
        self.avg_books = 0
        self.verified = None
        self.checkable = False


class _Tracker:
    __slots__ = ("moment", "best", "quotes")

    def __init__(self, moment):
        self.moment = moment
        self.best = None
        self.quotes = {}


def store_market(market_key: str):
    """``(captured, store_market_value)`` for a bet's market key."""
    shape = clv.MARKET_SHAPES.get(market_key)
    if shape is None:
        return False, None
    return True, shape.store_market


def _side_price(shape_side, row: dict, line) -> Optional[int]:
    if shape_side.line_field is not None and row.get(shape_side.line_field) != line:
        return None
    price = row.get(shape_side.price_field)
    return int(price) if isinstance(price, (int, float)) else None


def american_mean(prices: list) -> Optional[int]:
    """American price of the mean decimal price of ``prices``."""
    if not prices:
        return None
    mean_dec = sum(odds_math.american_to_decimal(p) for p in prices) / len(prices)
    if mean_dec <= 1.0:
        return None
    return int(round(odds_math.decimal_to_american(mean_dec)))


def scan(bets: list, multibook_path, since: Optional[str] = None):
    """Fill board facts on ``bets`` in place and return the CLV pregame index.

    ``bets`` need: event_id, market_key, side, line, decision_utc, price, book.
    Bets without an event, a captured market, a side or a parseable decision
    time are left unchecked (never guessed). Returns ``(index, teams)`` where
    ``index`` is ``clv.pregame_index``'s dict for the events involved and
    ``teams`` is ``{event_id: (away_team, home_team)}``.
    """
    from src.pipeline import snapshots

    probes = defaultdict(list)              # (event, store_market) -> [bet, ...]
    trackers = {}                           # (event, store_market, moment) -> _Tracker
    wanted_events = set()
    for bet in bets:
        captured, store_mk = store_market(bet.market_key)
        moment = clv._moment(bet.decision_utc)
        if (not captured or not bet.event_id or moment is None
                or bet.side not in (clv.MARKET_SHAPES[bet.market_key].sides)):
            continue
        wanted_events.add(bet.event_id)
        probes[(bet.event_id, store_mk)].append(bet)
        trackers.setdefault((bet.event_id, store_mk, moment), _Tracker(moment))
    by_pair = defaultdict(list)
    for (event, store_mk, moment), tr in trackers.items():
        by_pair[(event, store_mk)].append(tr)

    moments = {}

    def parse(stamp):
        m = moments.get(stamp)
        if m is None:
            m = clv._moment(stamp) or False
            moments[stamp] = m
        return m or None

    closing = defaultdict(dict)             # (event, store_mk) -> {moment: [rows]}
    newest = {}                             # event -> (moment, trimmed row)
    teams = {}

    def keep(row):
        return row.get("event_id") in wanted_events

    for row in snapshots.iter_multibook(path=multibook_path, sport=None, keep=keep,
                                        since=since):
        event = row["event_id"]
        store_mk = row.get("market")
        moment = parse(row.get("observed_utc"))
        if moment is None:
            continue
        teams[event] = (row.get("away_team"), row.get("home_team"))
        top = newest.get(event)
        if top is None or moment > top[0]:
            newest[event] = (moment, _trim(row))
        pair = (event, store_mk)
        if snapshots.is_pregame(row):
            bucket = closing[pair]
            rows = bucket.get(moment)
            if rows is None:
                bucket[moment] = rows = []
                if len(bucket) > CLOSING_INSTANTS_KEPT:
                    del bucket[min(bucket)]
            if moment in bucket:
                rows.append(_trim(row))
        for tr in by_pair.get(pair, ()):
            if moment > tr.moment:
                continue
            if tr.best is None or moment > tr.best:
                tr.best = moment
                tr.quotes = {}
            if moment == tr.best:
                tr.quotes[row.get("book")] = row

    kept = [top[1] for top in newest.values()]
    for bucket in closing.values():
        for rows in bucket.values():
            kept.extend(rows)
    index = clv.pregame_index(kept)

    for (event, store_mk), group in probes.items():
        for bet in group:
            facts = BoardFacts()
            tr = trackers[(event, store_mk, clv._moment(bet.decision_utc))]
            shape_side = clv.MARKET_SHAPES[bet.market_key].sides[bet.side]
            prices = {}
            for book, row in tr.quotes.items():
                p = _side_price(shape_side, row, bet.line)
                if p is not None:
                    prices[book] = p
            if prices:
                facts.checkable = True
                if bet.price is not None:
                    want = _book_key(bet.book)
                    facts.verified = any(
                        p == bet.price and (not want or _book_key(b) == want)
                        for b, p in prices.items())
                if len(prices) >= MIN_AVERAGE_BOOKS:
                    facts.avg_price = american_mean(list(prices.values()))
                    facts.avg_books = len(prices)
            bet.checkable = facts.checkable
            bet.verified = facts.verified
            bet.avg_price = facts.avg_price
            bet.avg_books = facts.avg_books
    return index, teams
