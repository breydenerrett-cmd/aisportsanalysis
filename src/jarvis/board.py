"""As-of price boards: what the stored odds said at an instant, the no-vig consensus, and open versus current.

WHY THIS FILE EXISTS INSTEAD OF REUSING ``src.report.card``'S BOARD. The card builds its board from live provider
fetches and "newest row wins"; Jarvis must answer "what could the owner have seen at ``as_of``" from the stores
alone. Every reader here takes ``as_of`` and drops any row observed after it, so a better price that was captured
later can never leak into an earlier briefing (tests/test_jarvis.py pins that).

A BOARD is the newest capture instant at or before T, per (game, market, [player], book). One capture lists a
book's whole menu, so taking the newest INSTANT (not the newest row per line) means a line a book has since moved
off cannot linger as a phantom quote. The OPEN board is the same read at each book's EARLIEST instant.

CONSENSUS IS LEAVE-ONE-OUT. The fair probability behind a pick's expected value is the mean of the other books'
no-vig prices, EXCLUDING the book that offers the best price. Otherwise the very quote being judged would raise
the consensus it is judged against. It needs ``MIN_OTHER_BOOKS`` other books; a thinner market gets no number.

THE -200 BAN lives here too (``price_allowed``): a selection whose best OR average price is -200 or worse is never
offered, whatever its value says.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

from src.core import odds as odds_math
from src.hounds import boards as hound_boards
from src.paths import processed_path
from src.pipeline import snapshots

MIN_OTHER_BOOKS = 3            # books besides the best-price book that must quote the pair for a consensus
MIN_BOOKS = MIN_OTHER_BOOKS + 1
QUOTE_MAX_AGE_S = 3 * 3600     # a quote whose book last updated it more than this before the board instant is not takeable
BAN_PRICE = -200               # owner rulings 2026-09-20 / 2026-09-22: never -200 or worse, anywhere
DEVIG_METHOD = "power"         # the favourite-longshot-aware method the shadow arms use as primary

MARKET_NAMES = {None: "moneyline", "h2h": "moneyline", "spreads": "spread", "totals": "total"}
SIDES = {"moneyline": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under")}
PROP_SIDES = ("over", "under")


def parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_price(value: Any) -> Optional[int]:
    """An American price as an int, or None (a bool, a non-number, or inside (-100, 100) is not a price)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return int(value) if abs(value) >= 100 else None


def price_allowed(*prices: Optional[int]) -> bool:
    """False when any given price is -200 or worse (the owner's standing ban)."""
    return all(p is None or p > BAN_PRICE for p in prices)


def decimal_of(price: int) -> float:
    return odds_math.american_to_decimal(price)


def american_text(price: Optional[int]) -> str:
    return "no price" if price is None else (f"+{price}" if price > 0 else str(price))


def _number(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# ---------------------------------------------------------------------------
# reading the stores
# ---------------------------------------------------------------------------

def default_multibook_path() -> Path:
    return processed_path("odds_multibook.jsonl")


def read_game_rows(date: str, as_of: datetime, sport: str = "mlb", path: Optional[Path] = None) -> list:
    """Pre-game multi-book rows for the games whose official (Eastern) date is ``date``, observed at or before ``as_of``.

    Rows of in-play captures, rows with no readable stamps, and rows of a game that had started by ``as_of`` are
    dropped. Returns normalised rows (``market`` in moneyline/spread/total, ``observed`` and ``updated`` datetimes).
    """
    since, until = snapshots.window_for_date(date, sport)
    out: list = []
    for row in snapshots.iter_multibook(path or default_multibook_path(), sport=sport, since=since, until=until):
        market = MARKET_NAMES.get(row.get("market"))
        if market is None or row.get("in_play"):
            continue
        observed, start = parse_time(row.get("observed_utc")), parse_time(row.get("commence_time"))
        if observed is None or start is None or observed > as_of or observed >= start or start <= as_of:
            continue
        if snapshots.official_date(row.get("commence_time")) != date:
            continue
        updated = parse_time(row.get("book_last_update")) or observed
        if updated > as_of:
            continue
        if market == "moneyline":
            prices = {"home": valid_price(row.get("home_price")), "away": valid_price(row.get("away_price"))}
            line = None
        elif market == "spread":
            prices = {"home": valid_price(row.get("home_price")), "away": valid_price(row.get("away_price"))}
            line = _number(row.get("home_line"))
            if line is None:
                continue
        else:
            prices = {"over": valid_price(row.get("over_price")), "under": valid_price(row.get("under_price"))}
            line = _number(row.get("total"))
            if line is None:
                continue
        if any(p is None for p in prices.values()):
            continue
        out.append({"event_id": row.get("event_id"), "away_team": row.get("away_team"), "home_team": row.get("home_team"),
                    "commence_time": row.get("commence_time"), "market": market, "player": None, "book": row.get("book"),
                    "line": line, "prices": prices, "observed": observed, "updated": updated})
    return out


def _prop_store_paths(sport: str) -> list:
    if sport == "mlb":
        return [("batter", processed_path("batter_props.jsonl")), ("pitcher", processed_path("prop_prices.jsonl"))]
    return [("allsports", processed_path("allsports_props.jsonl"))]


def _prop_rows_from(kind: str, path: Path, event_ids: set) -> Iterator[dict]:
    """Per-side prop rows ``{event_id, market, player, book, line, side, price, observed, updated}`` for these events.

    The text prefilter only ever over-matches (an event id appearing anywhere in the line); the parsed row is
    checked exactly. batter_props and allsports_props carry one side per row; prop_prices carries both."""
    if not path.exists() or not event_ids:
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not any(eid in line for eid in event_ids):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_id") not in event_ids or row.get("poll") or not row.get("player"):
                continue
            observed = parse_time(row.get("observed_utc"))
            if observed is None:
                continue
            updated = parse_time(row.get("book_last_update")) or observed
            base = {"event_id": row["event_id"], "market": row.get("market"), "player": row.get("player"),
                    "book": row.get("book"), "observed": observed, "updated": updated}
            if kind == "pitcher":
                point = _number(row.get("point"))
                for side, key in (("over", "over_price"), ("under", "under_price")):
                    if point is not None:
                        yield {**base, "line": point, "side": side, "price": valid_price(row.get(key))}
            else:
                side = str(row.get("side") or "").lower()
                line_value = _number(row.get("line"))
                if side in PROP_SIDES and line_value is not None:
                    yield {**base, "line": line_value, "side": side, "price": valid_price(row.get("price"))}


def read_prop_rows(events: Mapping[str, Mapping], as_of: datetime, sport: str = "mlb") -> list:
    """Pre-game prop quotes for these events (``{event_id: {commence_time...}}``) observed at or before ``as_of``,
    grouped into pair rows (one per book, player, market and line) carrying both sides' prices."""
    ids = set(events)
    pairs: dict = {}
    for kind, path in _prop_store_paths(sport):
        for r in _prop_rows_from(kind, path, ids):
            start = parse_time(events[r["event_id"]].get("commence_time"))
            if r["price"] is None or start is None or r["observed"] > as_of or r["observed"] >= start or r["updated"] > as_of:
                continue
            key = (r["event_id"], r["market"], r["player"], r["book"], r["line"], r["observed"])
            row = pairs.setdefault(key, {"event_id": r["event_id"], "market": r["market"], "player": r["player"],
                                         "book": r["book"], "line": r["line"], "observed": r["observed"],
                                         "updated": r["updated"], "prices": {},
                                         "away_team": events[r["event_id"]].get("away_team"),
                                         "home_team": events[r["event_id"]].get("home_team"),
                                         "commence_time": events[r["event_id"]].get("commence_time")})
            row["prices"][r["side"]] = r["price"]
    return [r for r in pairs.values() if set(r["prices"]) == set(PROP_SIDES)]


# ---------------------------------------------------------------------------
# boards, groups, consensus
# ---------------------------------------------------------------------------

def board_at(rows: Iterable[Mapping], t: datetime, *, which: str = "latest") -> list:
    """The board at ``t``: per (event, market, player, book) only the rows of that book's newest (``which="latest"``)
    or earliest (``"first"``) capture instant at or before ``t``, minus quotes older than ``QUOTE_MAX_AGE_S``."""
    instants: dict = {}
    for r in rows:
        if r["observed"] > t:
            continue
        key = (r["event_id"], r["market"], r["player"], r["book"])
        have = instants.get(key)
        if have is None or (r["observed"] > have if which == "latest" else r["observed"] < have):
            instants[key] = r["observed"]
    out = []
    for r in rows:
        key = (r["event_id"], r["market"], r["player"], r["book"])
        if instants.get(key) != r["observed"] or r["observed"] > t:
            continue
        if (r["observed"] - r["updated"]).total_seconds() > QUOTE_MAX_AGE_S:
            continue
        out.append(r)
    return out


def groups_of(board: Iterable[Mapping]) -> dict:
    """``{(event, market, player, line): {book: row}}``; one row per book per line."""
    groups: dict = defaultdict(dict)
    for r in board:
        groups[(r["event_id"], r["market"], r["player"], r["line"])][r["book"]] = r
    return groups


def american_mean(prices: list) -> Optional[int]:
    return hound_boards.american_mean(prices)


def _fair_for(books_rows: Mapping[str, Mapping], side_a: str, side_b: str) -> list:
    """Per-book no-vig probabilities of ``side_a`` (falls back to proportional when a method refuses a lopsided pair)."""
    fairs = []
    for row in books_rows.values():
        a, b = row["prices"].get(side_a), row["prices"].get(side_b)
        if a is None or b is None:
            continue
        for method in (DEVIG_METHOD, "proportional"):
            try:
                fairs.append(odds_math.devig([a, b], method)[0])
                break
            except odds_math.OddsError:
                continue
    return fairs


def selections(group_key: tuple, books_rows: Mapping[str, Mapping]) -> list:
    """Both sides of one (event, market, player, line) group as price facts, each with its leave-one-out consensus.

    A side's ``fair`` is None when fewer than ``MIN_OTHER_BOOKS`` other books quote the pair. The spread's ``line``
    is the picked team's OWN line (home line for home, its negative for away), the shape the ledger stores."""
    event_id, market, player, line = group_key
    sides = PROP_SIDES if market not in SIDES else SIDES[market]
    any_row = next(iter(books_rows.values()))
    out = []
    for i, side in enumerate(sides):
        other = sides[1 - i]
        quoted = {b: r for b, r in books_rows.items() if r["prices"].get(side) is not None}
        if not quoted:
            continue
        best_book = min(quoted, key=lambda b: (-decimal_of(quoted[b]["prices"][side]), b))
        best = quoted[best_book]["prices"][side]
        prices = [r["prices"][side] for r in quoted.values()]
        others = {b: r for b, r in books_rows.items() if b != best_book}
        fairs = _fair_for(others, side, other)
        fair = sum(fairs) / len(fairs) if len(fairs) >= MIN_OTHER_BOOKS else None
        spread = (max(fairs) - min(fairs)) if len(fairs) >= 2 else None
        all_fairs = _fair_for(books_rows, side, other)
        own_line = line
        if market == "spread" and side == "away":
            own_line = -line
        out.append({
            "event_id": event_id, "market": market, "player": player, "side": side, "line": own_line,
            "group_line": line, "best_price": best, "best_book": best_book, "average_price": american_mean(prices),
            "books": len(quoted), "other_books": len(fairs), "fair": fair, "fair_spread": spread,
            "fair_all": (sum(all_fairs) / len(all_fairs)) if len(all_fairs) >= 2 else None,
            "observed": max(r["observed"] for r in quoted.values()),
            "away_team": any_row.get("away_team"), "home_team": any_row.get("home_team"),
            "commence_time": any_row.get("commence_time")})
    return out


def all_selections(board: Iterable[Mapping]) -> list:
    out: list = []
    for key, rows in sorted(groups_of(board).items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        out.extend(selections(key, rows))
    return out


def expected_value(probability: float, price: int) -> float:
    """Expected return per unit staked at ``price`` if ``probability`` is right (an estimate, never a promise)."""
    return probability * (decimal_of(price) - 1.0) - (1.0 - probability)


def max_price(probability: float, min_ev: float) -> Optional[int]:
    """The worst American price still leaving ``min_ev`` at ``probability``, never -200 or worse.

    Rounded toward the better price so the stated price itself clears ``min_ev``. A very short price the maths
    allows is clamped to -199 (the ban); None when the probability is not usable."""
    if not (0.0 < probability < 1.0):
        return None
    needed = (1.0 + min_ev) / probability
    if needed <= 1.0:
        return BAN_PRICE + 1
    if needed >= 2.0:
        return max(100, int(math.ceil((needed - 1.0) * 100.0 - 1e-9)))
    cap = int(math.floor(100.0 / (needed - 1.0) + 1e-9))
    return -min(cap, abs(BAN_PRICE) - 1)


def window_start(rows: Iterable[Mapping]) -> Optional[datetime]:
    return min((r["observed"] for r in rows), default=None)


def newest(rows: Iterable[Mapping]) -> Optional[datetime]:
    return max((r["observed"] for r in rows), default=None)


def age_minutes(moment: datetime, as_of: datetime) -> float:
    return (as_of - moment) / timedelta(minutes=1)
