"""Leave-one-book-out (LOBO) value finder, with its constants as arguments.

WHY THIS EXISTS
---------------
`src/analysis/nfl_value.py` (NFL_CARD_V2, registered 2026-09-20) holds the
rule: a price at book B is value when it beats the de-vigged consensus of
every OTHER book quoting the SAME line, under all three de-vig methods. Its
constants are module globals, fixed for the NFL registration, and that module
must not be edited -- a change there changes a registered rule.

The MLB shadow test (docs/PREREG_MLB_VALUE_SHADOW_V1.md) reuses the same rule
on MLB run lines, game totals and batter props, and one of its arms needs a
different minimum book count. So this module is the same arithmetic with every
constant passed in, plus the adapters that turn stored rows into two-way
quotes. `tests/test_lobo_value.py` proves it reproduces
`nfl_value.value_candidates` exactly when handed NFL_CARD_V2's constants, so
the two cannot quietly diverge on the part they share, and an NFL edit can
never silently change an MLB arm (nothing here imports nfl_value).

THE RULE (identical to NFL_CARD_V2 rules 2-5)
---------------------------------------------
  * Each book's LATEST quote per game and market counts.
  * Board freshness: the newest quote on the game-and-market must be no more
    than `fresh_board_seconds` older than the run.
  * Book freshness: a book counts only if its quote is within
    `fresh_seconds` of that newest quote. A quote's time is the book's own
    update time, else the capture time.
  * Fair price for book B's quote = the mean, over every OTHER book quoting
    the same line, of that book's de-vigged probability. B is never in its
    own consensus. At least `min_other_books` other books, or the line is
    not judged.
  * A quote any de-vig method cannot price is excluded everywhere.
  * EV = fair x decimal - 1 per method; a candidate needs EV >= `min_ev`
    under EVERY method, and the lowest is the one reported.
  * A price at `worst_price` or worse is never a candidate (-199 passes,
    -200 does not).

Pure functions: every input arrives as an argument. No I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional, Sequence

from src.core import odds as odds_math

DEVIG_METHODS = ("proportional", "shin", "power")


@dataclass(frozen=True)
class LoboParams:
    """Every constant the rule reads. Frozen: a registered arm's params are
    a value, never mutated in place."""

    min_other_books: int
    min_ev: float
    fresh_seconds: int
    fresh_board_seconds: int
    worst_price: int
    devig_methods: tuple = DEVIG_METHODS

    def as_dict(self) -> dict:
        return {
            "min_other_books": int(self.min_other_books),
            "min_ev": float(self.min_ev),
            "fresh_seconds": int(self.fresh_seconds),
            "fresh_board_seconds": int(self.fresh_board_seconds),
            "worst_price": int(self.worst_price),
            "devig_methods": list(self.devig_methods),
        }


# NFL_CARD_V2's constants, copied as values. tests/test_lobo_value.py fails
# if these ever differ from src/analysis/nfl_value.py's globals, which is
# the only thing the parity test is allowed to lean on.
NFL_CARD_V2_PARAMS = LoboParams(
    min_other_books=5,
    min_ev=0.02,
    fresh_seconds=30 * 60,
    fresh_board_seconds=60 * 60,
    worst_price=-200,
    devig_methods=DEVIG_METHODS,
)


def canonical_sha256(payload: Mapping) -> str:
    """sha256 of `payload`'s canonical JSON (sorted keys, no whitespace,
    ASCII) -- the same serialisation src/ledger/chain.py hashes rows with."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# Small parsers
# ---------------------------------------------------------------------------

def parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        when = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_ok(american, worst_price: int) -> bool:
    """Usable, and strictly better than `worst_price` (-199 passes when the
    floor is -200; -200 does not)."""
    try:
        n = float(american)
    except (TypeError, ValueError):
        return False
    return n > worst_price


def quote_time(row: Mapping) -> Optional[datetime]:
    """When a quote was last current: the book's own update time, else the
    capture time."""
    return parse_utc(row.get("book_last_update")) or parse_utc(row.get("observed_utc"))


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def board_is_fresh(quotes: Sequence[Mapping], *, now: datetime,
                   fresh_board_seconds: int) -> bool:
    """True when the newest quote time on the board is no more than
    `fresh_board_seconds` older than `now`. No datable quote: not fresh."""
    stamps = [q["quote_time"] for q in quotes if q.get("quote_time") is not None]
    if not stamps:
        return False
    return (now - max(stamps)).total_seconds() <= fresh_board_seconds


def fresh_quotes(quotes: Sequence[Mapping], *, fresh_seconds: int) -> list:
    """Quotes whose time is within `fresh_seconds` of the board's newest."""
    stamped = [q for q in quotes if q.get("quote_time") is not None]
    if not stamped:
        return []
    newest = max(q["quote_time"] for q in stamped)
    floor = newest - timedelta(seconds=fresh_seconds)
    return [q for q in stamped if q["quote_time"] >= floor]


def newest_quote_time(quotes: Sequence[Mapping]) -> Optional[datetime]:
    stamps = [q["quote_time"] for q in quotes if q.get("quote_time") is not None]
    return max(stamps) if stamps else None


# ---------------------------------------------------------------------------
# De-vig and judge
# ---------------------------------------------------------------------------

def devig_pair(pair: Sequence[tuple], methods: Sequence[str]) -> Optional[dict]:
    """{method: {side: fair probability}} for one book's two prices, or None
    when ANY method cannot price it (such a quote is neither judged nor part
    of anyone's consensus)."""
    (side_a, _, price_a), (side_b, _, price_b) = pair
    out = {}
    for method in methods:
        try:
            fair_a, fair_b = odds_math.devig_two_way(price_a, price_b, method=method)
        except (odds_math.OddsError, TypeError, ValueError):
            return None
        out[method] = {side_a: fair_a, side_b: fair_b}
    return out


def judge_board(quotes: Sequence[Mapping], *, now: datetime,
                params: LoboParams) -> dict:
    """Judge one game-and-market board.

    `quotes` is every book's latest quote on the board: dicts with `book`,
    `line_key` (quotes are compared only within one line_key), `pair`
    (((side, line, price), (side, line, price)), or None when the book is not
    two-way here), `quote_time` (datetime or None) and `meta` (passed through
    to each candidate untouched).

    Returns {"fresh": bool, "lines_judged": int, "candidates": [...]}. A
    book-line is "judged" when it has at least `min_other_books` others on its
    line -- counted so an empty result can say whether anything was looked at.
    """
    result = {"fresh": False, "lines_judged": 0, "candidates": []}
    if not board_is_fresh(quotes, now=now, fresh_board_seconds=params.fresh_board_seconds):
        return result
    result["fresh"] = True
    methods = tuple(params.devig_methods)

    # {line_key: [(book, quote, {method: {side: fair}})]}
    by_line: dict = defaultdict(list)
    for q in fresh_quotes(quotes, fresh_seconds=params.fresh_seconds):
        pair = q.get("pair")
        if pair is None:
            continue
        fair = devig_pair(pair, methods)
        if fair is None:
            continue
        by_line[q.get("line_key")].append((q.get("book"), q, fair))

    for _line_key, entries in by_line.items():
        # One quote per book per line. A book that appears twice on one line
        # is ambiguous (two players normalising to one name, a duplicated
        # row); it is dropped from that line entirely rather than guessed at.
        per_book: dict = defaultdict(int)
        for book, _q, _f in entries:
            per_book[book] += 1
        entries = [e for e in entries if per_book[e[0]] == 1]

        for book, q, _own in entries:
            others = [(b, f) for b, _q2, f in entries if b != book]
            if len(others) < params.min_other_books:
                continue
            result["lines_judged"] += 1
            for side, line, price in q["pair"]:
                if not price_ok(price, params.worst_price):
                    continue
                try:
                    decimal = odds_math.american_to_decimal(price)
                except (odds_math.OddsError, TypeError, ValueError):
                    continue
                # The price is the same under every method, so the lowest EV
                # is also the lowest fair probability: clearing min_ev there
                # IS clearing it under all of them.
                by_method = {}
                for method in methods:
                    fair_m = sum(f[method][side] for _b, f in others) / len(others)
                    by_method[method] = (fair_m * decimal - 1.0, fair_m)
                binding = min(methods, key=lambda m: by_method[m][0])
                ev, fair_p = by_method[binding]
                if ev < params.min_ev:
                    continue
                result["candidates"].append({
                    "line_key": q.get("line_key"),
                    "side": side,
                    "line": line,
                    "price": price,
                    "book": book,
                    "fair_probability": fair_p,
                    "ev": ev,
                    "devig_method": binding,
                    "ev_by_method": {m: by_method[m][0] for m in methods},
                    "fair_by_method": {m: by_method[m][1] for m in methods},
                    "n_other_books": len(others),
                    "other_books": sorted(str(b) for b, _f in others),
                    "quote_time": q.get("quote_time"),
                    "meta": q.get("meta") or {},
                })
    return result


# ---------------------------------------------------------------------------
# Adapter: multi-book game-line rows (odds_multibook.jsonl shape)
# ---------------------------------------------------------------------------

def multibook_two_way(row: Mapping, market: str) -> Optional[tuple]:
    """(line_key, pair) for one stored game-line quote.

    spreads: line_key is the HOME line; sides are home/away with their own
    signed lines. totals: line_key is the total; sides over/under. h2h:
    line_key None; sides home/away.
    """
    if market == "spreads":
        home_line, away_line = to_float(row.get("home_line")), to_float(row.get("away_line"))
        if home_line is None or away_line is None:
            return None
        return (home_line, (("home", home_line, row.get("home_price")),
                            ("away", away_line, row.get("away_price"))))
    if market == "totals":
        total = to_float(row.get("total"))
        if total is None:
            return None
        return (total, (("over", total, row.get("over_price")),
                        ("under", total, row.get("under_price"))))
    if market == "h2h":
        return (None, (("home", None, row.get("home_price")),
                       ("away", None, row.get("away_price"))))
    return None


def latest_multibook_rows(rows: Iterable[Mapping]) -> dict:
    """{(event_id, market, book): newest row}. A row with no `market` is h2h.
    Ties on observed_utc go to the later row in file order."""
    latest: dict = {}
    for row in rows:
        key = (row.get("event_id"), row.get("market") or "h2h", row.get("book"))
        seen = latest.get(key)
        if seen is None or str(row.get("observed_utc") or "") >= str(seen.get("observed_utc") or ""):
            latest[key] = row
    return latest


def multibook_boards(rows: Iterable[Mapping], *, now: datetime,
                     markets: Sequence[str]) -> dict:
    """{(event_id, market): [quote]} for games not yet started. Every book's
    latest row is a quote -- including one whose prices cannot be parsed
    (pair None), because its time still counts toward the board's freshness,
    exactly as in nfl_value."""
    boards: dict = defaultdict(list)
    for (event_id, market, book), row in latest_multibook_rows(rows).items():
        if market not in markets:
            continue
        kickoff = parse_utc(row.get("commence_time"))
        if kickoff is None or kickoff <= now:
            continue
        parsed = multibook_two_way(row, market)
        line_key, pair = parsed if parsed is not None else (None, None)
        boards[(event_id, market)].append({
            "book": book,
            "line_key": line_key,
            "pair": pair,
            "quote_time": quote_time(row),
            "meta": {
                "event_id": event_id,
                "market": market,
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "commence_time": row.get("commence_time"),
                "observed_utc": row.get("observed_utc"),
                "book_last_update": row.get("book_last_update"),
            },
        })
    return boards


def value_candidates_multibook(rows: Iterable[Mapping], *, now: datetime,
                               params: LoboParams,
                               markets: Sequence[str] = ("spreads", "totals", "h2h")) -> list:
    """Candidates in nfl_value.value_candidates' own shape (the parity
    surface), plus the extra evidence fields judge_board adds."""
    out = []
    for (_event_id, _market), quotes in multibook_boards(rows, now=now, markets=markets).items():
        judged = judge_board(quotes, now=now, params=params)
        for cand in judged["candidates"]:
            meta = cand["meta"]
            out.append({
                "event_id": meta["event_id"], "market": meta["market"],
                "line": cand["line"], "side": cand["side"],
                "price": cand["price"], "book": cand["book"],
                "fair_probability": cand["fair_probability"], "ev": cand["ev"],
                "devig_method": cand["devig_method"],
                "ev_by_method": cand["ev_by_method"],
                "n_other_books": cand["n_other_books"],
                "home_team": meta["home_team"], "away_team": meta["away_team"],
                "commence_time": meta["commence_time"],
            })
    return out
