"""The user-hound engine: turn each running hound's rule into paper bets, before the game starts.

WHAT IT DOES, IN ORDER
----------------------
For one slate date it reads the captured multi-book board (`data/processed/odds_multibook.jsonl`,
through the same `snapshots.iter_multibook` reader the rest of the program uses), and for every
running hound and every game on its menu whose LOCK TIME has arrived and whose start has not:

  1. takes the board as it stood AT LOCK: the newest capture at or before `start - lock_minutes`
     (never a later one), no older than MAX_BOARD_AGE_MINUTES;
  2. applies the hound's side rule to that board, then its price band, the -200 cap and its
     minimum-books rule;
  3. prices the bet at the board AVERAGE across the books (owner grading ruling 2026-09-21: picks,
     not price shopping; the average is taken in decimal odds because a mean of American prices is
     meaningless across even money), and records the best single price beside it;
  4. appends the bet to the hash-chained ledger `evidence/hounds_user_v1.jsonl`, at most
     `max_bets_per_day` per hound per slate date.

WHY "THE BOARD AT LOCK" AND NOT "THE BOARD WHEN THE JOB HAPPENED TO RUN"
-----------------------------------------------------------------------
The capture slot runs on its own cadence (45 to 60 minutes between captures near a start). If a
bet used whatever the latest capture said when the engine ran, the same hound would make different
bets depending on when a cron fired, and a late run would quietly use information from after the
lock. Fixing the board at the lock instant makes the answer a function of (rule, data) only: run it
twice, run it late, run it on another machine, and the same rows come out. The row still records
when it was written (`recorded_utc`) and the engine refuses to write one at or after the start.

IDEMPOTENT AND ORDERED
----------------------
A bet's id is a hash of (hound, event, market), so a rerun adds nothing. Candidates for a hound are
taken in (lock time, event id, market) order and the day's quota counts bets already in the ledger,
so "at most N a day, earliest lock first" holds across several runs.

FIRST CAPTURE, NOT THE TRUE OPEN
--------------------------------
"The side the market moved toward since open" can only mean since OUR first capture of the game
(the feed's real opening line is not stored). The published rule says so. A move is a change of the
consensus line, or, when the line is unchanged, at least MOVE_PROBABILITY of de-vigged win
probability; a smaller change is "no move" and places no bet.

PAPER ONLY
----------
Nothing here talks to a book or suggests a wager. Every row says paper_only.

CLI:  python -m src.hounds.user_engine run --date YYYY-MM-DD|auto [--replay] [--ledger PATH]
      python -m src.hounds.user_engine verify [--ledger PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from src import paths
from src.core import odds as odds_math
from src.hounds import user_spec
from src.ledger.chain import HashChainLedger

LEDGER = os.path.join("evidence", "hounds_user_v1.jsonl")
KIND_BET = "hound_user_bet"
LEDGER_VERSION = 1

# The cadence of the capture slot near a start is 45 to 60 minutes; 75 leaves one missed capture of
# headroom. A lock with no capture this recent is skipped and counted, never guessed.
MAX_BOARD_AGE_MINUTES = 75
# A moneyline (or an unchanged line) must move by this much de-vigged win probability to count.
MOVE_PROBABILITY = 0.005

MARKET_ORDER = {m: i for i, m in enumerate(user_spec.MARKETS)}
_ROW_MARKET = {None: "moneyline", "h2h": "moneyline", "spreads": "spread", "totals": "total"}


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _price(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if abs(value) < 100:
        return None
    return int(value)


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


ENV_LEDGER = "HOUNDS_USER_LEDGER"
LEDGER_NAME = "hounds_user_v1.jsonl"


def ledger_path(path: Optional[str] = None) -> str:
    """Where the user hounds' hash-chained ledger lives.

    An explicit path wins (tests, the CLI's --ledger). Otherwise HOUNDS_USER_LEDGER, otherwise a
    file BESIDE THE APP DATABASE (``data/app/`` locally, the persistent Fly volume in production).

    WHY BESIDE THE DATABASE AND NOT ``evidence/`` (decision 2026-10-18, docs/HOUNDS_USER.md): the
    running hounds live in the app database, so the engine that turns them into bets runs in the
    API process on the machine that owns that database (api/hounds_engine.py). ``evidence/`` is a
    git-tracked directory baked into the image, so a ledger written there on the server would be
    lost at the next deploy and could never reach git. The volume survives deploys. The one place
    both the engine and the public reader (stats.Sources.default) resolve this from is here."""
    if path:
        return path
    override = (os.environ.get(ENV_LEDGER) or "").strip()
    if override:
        return override
    from src.appstate import users as users_store
    return str(users_store.db_path().parent / LEDGER_NAME)


# ---------------------------------------------------------------------------
# the board
# ---------------------------------------------------------------------------

def average_price(prices: Sequence[float]) -> int:
    """The board's AVERAGE price: mean of the decimal odds, converted back, rounded."""
    decimals = [odds_math.american_to_decimal(p) for p in prices]
    return int(round(odds_math.decimal_to_american(sum(decimals) / len(decimals))))


def best_price(book_prices: Sequence[tuple]) -> tuple:
    """(price, book) of the single best quote (highest decimal; ties go to the book sorted first)."""
    ordered = sorted(book_prices, key=lambda bp: (-odds_math.american_to_decimal(bp[1]), bp[0]))
    return ordered[0][1], ordered[0][0]


def _modal(groups: dict) -> Any:
    """The line most books agree on; ties go to the line nearest zero, then the lower value."""
    return sorted(groups, key=lambda k: (-len(groups[k]), abs(k), k))[0]


def build_board(market: str, rows: Sequence[Mapping]) -> Optional[dict]:
    """One capture's rows for one market -> {'market','line','sides':{side:[(book, price)]},'n_books'}.

    One quote per book (the last in file order). For a spread or total, only the books on the
    consensus line count: a half-run difference is a different bet, not a different price."""
    by_book: dict = {}
    for row in rows:
        book = row.get("book")
        if isinstance(book, str) and book:
            by_book[book] = row
    if not by_book:
        return None
    if market == "moneyline":
        sides = {"home": [], "away": []}
        for book, row in sorted(by_book.items()):
            hp, ap = _price(row.get("home_price")), _price(row.get("away_price"))
            if hp is None or ap is None:
                continue
            sides["home"].append((book, hp))
            sides["away"].append((book, ap))
        n = len(sides["home"])
        return {"market": market, "line": None, "sides": sides, "n_books": n} if n else None
    if market == "spread":
        groups: dict = defaultdict(list)
        for book, row in sorted(by_book.items()):
            hl = _number(row.get("home_line"))
            hp, ap = _price(row.get("home_price")), _price(row.get("away_price"))
            if hl is None or hp is None or ap is None:
                continue
            groups[hl].append((book, hp, ap))
        if not groups:
            return None
        line = _modal(groups)
        return {"market": market, "line": line,
                "sides": {"home": [(b, hp) for b, hp, _ in groups[line]],
                          "away": [(b, ap) for b, _, ap in groups[line]]},
                "n_books": len(groups[line])}
    if market == "total":
        groups = defaultdict(list)
        for book, row in sorted(by_book.items()):
            tl = _number(row.get("total"))
            op, up = _price(row.get("over_price")), _price(row.get("under_price"))
            if tl is None or op is None or up is None:
                continue
            groups[tl].append((book, op, up))
        if not groups:
            return None
        line = _modal(groups)
        return {"market": market, "line": line,
                "sides": {"over": [(b, op) for b, op, _ in groups[line]],
                          "under": [(b, up) for b, _, up in groups[line]]},
                "n_books": len(groups[line])}
    return None


def _first_side(board: Mapping) -> str:
    return "over" if board["market"] == "total" else "home"


def _other(side: str) -> str:
    return {"home": "away", "away": "home", "over": "under", "under": "over"}[side]


def _devig_first(board: Mapping) -> float:
    """Mean de-vigged probability of the board's first side (home, or over) across its books."""
    first = _first_side(board)
    second = _other(first)
    probs = []
    for (_, a), (_, b) in zip(board["sides"][first], board["sides"][second]):
        ra, rb = 1.0 / odds_math.american_to_decimal(a), 1.0 / odds_math.american_to_decimal(b)
        probs.append(ra / (ra + rb))
    return sum(probs) / len(probs)


def movement(open_board: Mapping, lock_board: Mapping) -> Optional[str]:
    """The side the market moved TOWARD between two boards of one market, or None for no move."""
    market = lock_board["market"]
    if market in ("spread", "total") and open_board["line"] != lock_board["line"]:
        rose = lock_board["line"] > open_board["line"]
        if market == "total":
            return "over" if rose else "under"
        # A lower (more negative) home line means the market now asks the home side to give more.
        return "away" if rose else "home"
    delta = _devig_first(lock_board) - _devig_first(open_board)
    if abs(delta) < MOVE_PROBABILITY:
        return None
    first = _first_side(lock_board)
    return first if delta > 0 else _other(first)


def side_for_rule(rule: str, market: str, board: Mapping, open_board: Optional[Mapping]) -> Optional[str]:
    """Which side a rule backs on this board, or None when the rule has no answer (tie, no move)."""
    if rule in ("home", "away"):
        return rule if market in ("moneyline", "spread") else None
    if rule in ("over", "under"):
        return rule if market == "total" else None
    if rule in ("favourite", "underdog"):
        if market not in ("moneyline", "spread"):
            return None
        fav = None
        if market == "spread" and board["line"] not in (None, 0):
            fav = "home" if board["line"] < 0 else "away"
        else:
            h = odds_math.american_to_decimal(average_price([p for _, p in board["sides"]["home"]]))
            a = odds_math.american_to_decimal(average_price([p for _, p in board["sides"]["away"]]))
            if abs(h - a) < 1e-9:
                return None
            fav = "home" if h < a else "away"
        return fav if rule == "favourite" else _other(fav)
    if rule in ("market_moved_toward", "market_moved_away"):
        if open_board is None:
            return None
        toward = movement(open_board, board)
        if toward is None:
            return None
        return toward if rule == "market_moved_toward" else _other(toward)
    return None


# ---------------------------------------------------------------------------
# games and captures
# ---------------------------------------------------------------------------

class GameBoards:
    """Every pre-game capture of one event, by market and capture instant."""

    def __init__(self, event_id: str, sport: str):
        self.event_id = event_id
        self.sport = sport
        self.home_team: Optional[str] = None
        self.away_team: Optional[str] = None
        self.commence: Optional[datetime] = None
        self.captures: dict = defaultdict(lambda: defaultdict(list))   # market -> observed -> rows
        self._commence_by_obs: dict = {}

    def add(self, market: str, observed: datetime, row: Mapping) -> None:
        self.captures[market][observed].append(row)
        self.home_team = row.get("home_team") or self.home_team
        self.away_team = row.get("away_team") or self.away_team
        c = _utc(row.get("commence_time"))
        if c is not None:
            self._commence_by_obs[observed] = c

    def commence_at(self, observed: datetime) -> Optional[datetime]:
        """The start time the feed gave at (or nearest before) a capture instant."""
        known = [t for t in self._commence_by_obs if t <= observed]
        if not known:
            return None
        return self._commence_by_obs[max(known)]

    def board_at(self, market: str, as_of: datetime) -> Optional[tuple]:
        """(observed, board) for the newest capture of `market` at or before `as_of`."""
        stamps = [t for t in self.captures.get(market, {}) if t <= as_of]
        for t in sorted(stamps, reverse=True):
            board = build_board(market, self.captures[market][t])
            if board is not None:
                return t, board
        return None

    def first_board(self, market: str, before: datetime) -> Optional[tuple]:
        """The earliest usable capture of `market` strictly before `before`."""
        for t in sorted(self.captures.get(market, {})):
            if t >= before:
                break
            board = build_board(market, self.captures[market][t])
            if board is not None:
                return t, board
        return None


def sport_of_row(row: Mapping) -> str:
    return (row.get("sport") or "mlb").upper()


# The only fields of a board row the engine reads. Kept rows are trimmed to these: a slate's boards
# held whole were most of the engine's memory (the server has 1 GB, and a past incident was
# whole-store reads).
_KEEP_FIELDS = ("book", "home_price", "away_price", "home_line", "away_line", "total",
                "over_price", "under_price", "home_team", "away_team", "commence_time")


def _slim(row: Mapping) -> dict:
    return {k: row[k] for k in _KEEP_FIELDS if k in row}


def build_games(rows: Iterable[Mapping], near_date: Optional[str] = None) -> dict:
    """{event_id: GameBoards} from raw multibook rows, consumed ONE AT A TIME (a generator is
    fine, and is what production passes). Rows observed at or after their own start (in-play) are
    dropped here, once, so nothing downstream can use one.

    ``near_date`` (an Eastern slate date) keeps only rows of games starting within a day of that
    date, so a pass for today does not hold the other weeks' games in memory. The day either side
    is kept because a rescheduled game's earlier rows carry its old start; the exact slate filter
    (the game's latest start) still happens in ``run``."""
    games: dict = {}
    near: dict = {}
    for row in rows:
        market = _ROW_MARKET.get(row.get("market"))
        event_id, observed = row.get("event_id"), _utc(row.get("observed_utc"))
        raw_start = row.get("commence_time")
        start = _utc(raw_start)
        if market is None or not event_id or observed is None or start is None:
            continue
        if observed >= start:
            continue
        if near_date is not None:
            keep = near.get(raw_start)
            if keep is None:
                keep = near[raw_start] = abs(
                    (datetime.fromisoformat(slate_date_of(start)) -
                     datetime.fromisoformat(near_date)).days) <= 1
            if not keep:
                continue
        sport = sport_of_row(row)
        if sport not in user_spec.SPORTS:
            continue
        game = games.get(event_id)
        if game is None:
            game = games[event_id] = GameBoards(event_id, sport)
        game.add(market, observed, _slim(row))
    for game in games.values():
        game.commence = game.commence_at(datetime.max.replace(tzinfo=timezone.utc))
    return games


def slate_date_of(commence: datetime) -> str:
    from src.pipeline import snapshots
    return snapshots.official_date(_iso(commence))


def iter_rows(date: str, sports: Iterable[str], *, multibook_path: Optional[str] = None):
    """The raw rows that can matter for one slate date, STREAMED through the shared windowed
    reader: one row at a time, never a list. This is what the in-process scheduler uses."""
    from src.pipeline import snapshots
    path = multibook_path or snapshots.DEFAULT_MULTIBOOK_PATH
    for sport in sorted({s.lower() for s in sports}):
        since, until = snapshots.window_for_date(date, sport)
        yield from snapshots.iter_multibook(path, sport=sport, since=since, until=until)


def load_rows(date: str, sports: Iterable[str], *, multibook_path: Optional[str] = None) -> list:
    """``iter_rows`` as a list (tests and the CLI; the scheduler streams instead)."""
    return list(iter_rows(date, sports, multibook_path=multibook_path))


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def bet_id_for(hound_id: str, event_id: str, market: str) -> str:
    return "b-" + hashlib.sha256(f"{hound_id}|{event_id}|{market}".encode()).hexdigest()[:20]


def _selection_text(game: GameBoards, market: str, side: str, line: Optional[float]) -> str:
    def signed(x):
        return f"{x:+g}"
    if market == "total":
        return f"{side.title()} {line:g}"
    team = game.home_team if side == "home" else game.away_team
    if market == "spread":
        own = line if side == "home" else -line
        return f"{team} {signed(own)}"
    return f"{team} to win"


def _fmt_price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def contract_fields(row: Mapping, spec: Mapping, mode: str) -> dict:
    """The bet row's fields under the NAMES src/hounds/contract.py and the shared ledger reader
    (src.hounds.ledgers.pack_ledger_rows) use, so the public stats read this ledger without a
    translation layer. Added beside the engine's own names, never instead of them.

    The two prices (owner grading ruling 2026-09-21, and what both halves now mean):
      price_average  the mean decimal price across the books on the board at lock, the price the
                     bet is HEADLINE-graded at (``units_average_price``). Same number as ``price``.
      price_best     the single best quote on that board (``book`` names the book), the price
                     recorded at lock (``units_recorded_price``). Same number as ``best_price``.
    ``segment`` is ``forward`` for a live run and ``replay`` for a backfill (prereg 1a)."""
    side = row["side"]
    if row["market"] == "total":
        what = f"the {side}"
    else:
        what = f"the {side} side"
    reason = (f"Rule: {user_spec.SIDE_LABELS[spec['side_rule']].lower()}. It backed {what} "
              f"({row['selection']}) at the board average of {_fmt_price(row['price'])} across "
              f"{row['n_books']} books; the best single price was {_fmt_price(row['best_price'])} "
              f"at {row['best_book']}.")
    return {
        "date": row["slate_date"], "price_average": row["price"], "price_best": row["best_price"],
        "book": row["best_book"], "book_count": row["n_books"], "start_utc": row["commence_time"],
        "segment": "replay" if mode == "replay" else "forward", "who_decided": "rule",
        "reason": reason,
    }


def evaluate(spec: Mapping, game: GameBoards, market: str, lock_utc: datetime,
             commence: datetime) -> tuple:
    """(candidate_dict | None, reason). The reason is a stable code when there is no candidate."""
    found = game.board_at(market, lock_utc)
    if found is None:
        return None, "no_board_at_lock"
    observed, board = found
    age = (lock_utc - observed).total_seconds() / 60.0
    if age > MAX_BOARD_AGE_MINUTES:
        return None, "board_too_old"
    if board["n_books"] < spec["min_books"]:
        return None, "too_few_books"
    open_board = None
    if spec["side_rule"].startswith("market_moved"):
        first = game.first_board(market, observed)
        open_board = first[1] if first else None
    side = side_for_rule(spec["side_rule"], market, board, open_board)
    if side is None:
        return None, "rule_has_no_side"
    book_prices = board["sides"][side]
    avg = average_price([p for _, p in book_prices])
    if user_spec.beyond_cap(avg):
        return None, "price_cap"
    if not user_spec.in_band(avg, spec["price_min"], spec["price_max"]):
        return None, "outside_price_band"
    best, best_book = best_price(book_prices)
    line = None
    if market == "spread":
        line = board["line"] if side == "home" else -board["line"]
        selection_line = board["line"]
    elif market == "total":
        line = board["line"]
        selection_line = board["line"]
    else:
        selection_line = None
    return {
        "side": side, "line": line, "price": avg, "best_price": best, "best_book": best_book,
        "n_books": board["n_books"], "board_observed_utc": _iso(observed),
        "board_age_minutes": round(age, 1),
        "selection": _selection_text(game, market, side, selection_line),
    }, "ok"


def read_ledger(path: Optional[str] = None) -> list:
    return HashChainLedger(ledger_path(path)).read()


def verify_ledger(path: Optional[str] = None):
    """The chain verdict for the hounds ledger (src.ledger.chain.VerifyResult)."""
    return HashChainLedger(ledger_path(path)).verify()


_verified_cache: dict = {}


def ledger_verified(path: Optional[str] = None) -> bool:
    """verify_ledger().ok, cached on the file's (size, mtime) so a page that shows a 'verified'
    badge does not re-walk the whole chain on every request. A missing file is an empty,
    trivially valid chain."""
    target = ledger_path(path)
    try:
        stat = os.stat(target)
        stamp = (stat.st_size, stat.st_mtime_ns)
    except OSError:
        return True
    hit = _verified_cache.get(target)
    if hit and hit[0] == stamp:
        return hit[1]
    ok = bool(verify_ledger(path).ok)
    _verified_cache[target] = (stamp, ok)
    return ok


def run(date: str, hounds: Sequence[Mapping], rows: Iterable[Mapping], *,
        ledger: Optional[str] = None, now: Optional[datetime] = None, mode: str = "live",
        game_pk_index: Optional[Mapping] = None,
        clock: Optional[Callable[[], datetime]] = None) -> dict:
    """Write the paper bets the running `hounds` make on slate `date`. See the module docstring.

    hounds: [{'id', 'spec', 'created_at'}]. rows: raw multibook rows (any superset of the date).
    mode: 'live' enforces lock <= now < start and ignores games a hound did not yet exist for;
    'replay' backfills a past date at each game's own lock instant, tags rows 'replay', and is meant
    for a scratch ledger. `now`/`clock` are injectable for tests."""
    if mode not in ("live", "replay"):
        raise ValueError("mode must be 'live' or 'replay'")
    clock = clock or (lambda: now if now is not None else datetime.now(timezone.utc))
    store = HashChainLedger(ledger_path(ledger))
    existing = store.read()
    seen_ids = {r["bet_id"] for r in existing if r.get("kind") == KIND_BET}
    per_day: Counter = Counter((r["hound_id"], r["slate_date"]) for r in existing
                               if r.get("kind") == KIND_BET)
    games = {eid: g for eid, g in build_games(rows, near_date=date).items()
             if g.commence is not None and slate_date_of(g.commence) == date}
    skipped: Counter = Counter()
    written_by: Counter = Counter()
    written = 0

    for hound in sorted(hounds, key=lambda h: h["id"]):
        spec = hound["spec"]
        created = _utc(hound.get("created_at"))
        candidates = []
        for event_id, game in games.items():
            if game.sport not in spec["sports"]:
                continue
            commence = game.commence
            lock_utc = commence - timedelta(minutes=spec["lock_minutes"])
            for market in spec["markets"]:
                bet_id = bet_id_for(hound["id"], event_id, market)
                if bet_id in seen_ids:
                    continue
                if mode == "live":
                    t = clock()
                    if t >= commence:
                        skipped["game_started"] += 1
                        continue
                    if t < lock_utc:
                        skipped["not_locked_yet"] += 1
                        continue
                    if created is not None and created > lock_utc:
                        skipped["hound_created_after_lock"] += 1
                        continue
                cand, reason = evaluate(spec, game, market, lock_utc, commence)
                if cand is None:
                    skipped[reason] += 1
                    continue
                candidates.append((lock_utc, event_id, MARKET_ORDER[market], market, game,
                                   commence, cand, bet_id))
        candidates.sort(key=lambda c: (c[0], c[1], c[2]))
        for lock_utc, event_id, _o, market, game, commence, cand, bet_id in candidates:
            if per_day[(hound["id"], date)] >= spec["max_bets_per_day"]:
                skipped["daily_limit"] += 1
                continue
            t = clock()
            if mode == "live" and t >= commence:        # the last guard: never at or after the start
                skipped["game_started"] += 1
                continue
            if user_spec.beyond_cap(cand["price"]):     # belt and braces: the cap is not a setting
                skipped["price_cap"] += 1
                continue
            pk = None
            if game.sport == "MLB" and game_pk_index:
                entry = game_pk_index.get(event_id)
                pk = str(entry.get("game_pk")) if entry and entry.get("game_pk") is not None else None
            row = {
                "kind": KIND_BET, "ledger_version": LEDGER_VERSION, "paper_only": True,
                "bet_id": bet_id, "hound_id": hound["id"],
                "spec_hash": hound.get("spec_hash") or user_spec.spec_hash(spec),
                "sport": game.sport, "event_id": event_id, "game_pk": pk, "slate_date": date,
                "commence_time": _iso(commence), "away_team": game.away_team,
                "home_team": game.home_team, "market": market, "side": cand["side"],
                "line": cand["line"], "selection": cand["selection"], "price": cand["price"],
                "best_price": cand["best_price"], "best_book": cand["best_book"],
                "n_books": cand["n_books"], "lock_minutes": spec["lock_minutes"],
                "lock_utc": _iso(lock_utc), "board_observed_utc": cand["board_observed_utc"],
                "board_age_minutes": cand["board_age_minutes"], "units": 1,
                "recorded_utc": _iso(t), "provenance": mode,
            }
            row.update(contract_fields(row, spec, mode))
            store.append(row)
            seen_ids.add(bet_id)
            per_day[(hound["id"], date)] += 1
            written_by[hound["id"]] += 1
            written += 1
    return {"date": date, "mode": mode, "hounds": len(hounds), "games_seen": len(games),
            "bets_written": written, "by_hound": dict(written_by), "skipped": dict(skipped),
            "paper_only": True}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def auto_dates(now: Optional[datetime] = None) -> list:
    """The slate dates a job running now can still lock bets for: today (Eastern) and tomorrow."""
    from src.pipeline import snapshots
    moment = now or datetime.now(timezone.utc)
    return [snapshots.official_date(_iso(moment)),
            snapshots.official_date(_iso(moment + timedelta(days=1)))]


def _load_game_pk_index() -> dict:
    try:
        from src.board import gamekey
        return gamekey.load_map()
    except Exception:  # noqa: BLE001 -- a missing map only leaves game_pk to be resolved at settle
        return {}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.hounds.user_engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--date", required=True, help="YYYY-MM-DD or 'auto'")
    p_run.add_argument("--replay", action="store_true")
    p_run.add_argument("--ledger")
    p_run.add_argument("--multibook")
    p_run.add_argument("--hounds-file",
                       help="JSON lines of {id, spec, created_at} instead of the app database")
    p_exp = sub.add_parser("export-specs", help="print the running hounds as JSON lines")
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("--ledger")
    args = parser.parse_args(argv)

    if args.cmd == "verify":
        result = verify_ledger(args.ledger)
        print(f"hounds ledger: ok={result.ok} rows={result.rows_checked}"
              + ("" if result.ok else f" broken_at_line={result.broken_at_line} {result.reason}"))
        return 0 if result.ok else 1

    from src.hounds import user_store
    if args.cmd == "export-specs":
        for h in user_store.list_running():
            print(json.dumps({"id": h["id"], "spec": h["spec"], "spec_hash": h["spec_hash"],
                              "created_at": h["created_at"]}, sort_keys=True))
        return 0
    if args.hounds_file:
        hounds = [json.loads(line) for line in Path(args.hounds_file).read_text(
            encoding="utf-8").splitlines() if line.strip()]
    else:
        hounds = user_store.list_running()
    dates = auto_dates() if args.date == "auto" else [args.date]
    sports = {s for h in hounds for s in h["spec"]["sports"]}
    index = _load_game_pk_index()
    for date in dates:
        rows = load_rows(date, sports, multibook_path=args.multibook) if sports else []
        report = run(date, hounds, rows, ledger=args.ledger,
                     mode="replay" if args.replay else "live", game_pk_index=index)
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
