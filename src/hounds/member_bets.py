"""A member's own bet log ("Log a bet"): the ledger, the placing rules, the settle wiring and the record.

Plan: docs/plans/MEMBER_BET_LOG.md. Nothing here is public: a member's bets are read only by that member
(every read below is filtered on ``owner_user_id``), and no stats, leaderboard or alert feed opens this file.

REUSE, NOT A SECOND GRADER
--------------------------
A member's bet row is the hound bet row (``user_engine.KIND_BET``) plus ``owner_user_id``, ``stake_units``,
``live``, ``source: "member"``, ``note`` and ``hound_id: None``. ``user_settle.settle(ledger=<this ledger>,
alert=False)`` therefore grades it with the same code that grades a hound bet (every sport, voids, postponed
games), and writes the graded row (``user_settle.KIND_GRADED``) back to the same ledger. The price a bet is
graded at is the price the MEMBER got (``price``), and ``best_price`` is the same number: a member bet has no
"best of the board" price. The board average at the moment of placing is kept as ``board_price_average``.

APPEND ONLY
-----------
The ledger is a hash chain (``src.ledger.chain``). Nothing edits or deletes a row. A member's void is an
appended graded-kind row (``result: VOID``, ``voided_by_member: true``), which ``settle`` already reads as
"graded", so the bet is never graded afterwards.

NOT ON OUR BOARD
----------------
``place_manual`` writes a row of its own kind (``KIND_MANUAL``, ``status: "unmatched"``). ``settle`` only
reads ``KIND_BET`` rows, so it is never guessed at; it is graded by hand later.

Plain English errors. The words edge, lock, beta, new, paper and promise never appear in member copy.
"""

from __future__ import annotations

import math
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from src.hounds import one_side, user_engine, user_settle, user_spec
from src.ledger.chain import HashChainLedger

ENV_LEDGER = "HOUNDS_MEMBER_BETS_LEDGER"
LEDGER_NAME = "hounds_member_bets_v1.jsonl"

KIND_BET = user_engine.KIND_BET                 # a matched bet is exactly a hound bet row (settle reads it)
KIND_GRADED = user_settle.KIND_GRADED           # a grade, or a member's void, is a graded row
KIND_MANUAL = "member_bet_manual"               # a bet on a game that is not on our board; graded by hand

MARKETS = ("moneyline", "spread", "total")
STAKE_MIN, STAKE_MAX = 0.25, 10.0
NOTE_MAX = 140
GAME_TEXT_MAX, SIDE_TEXT_MAX = 120, 60
MIN_PRICE_MAGNITUDE, MAX_PRICE_MAGNITUDE = 100, 100000      # mirrors api/betcheck.MIN/MAX_PLAUSIBLE_PRICE_MAGNITUDE
# The newest board the price may be read from. Same as the Live page's "live" window.
BOARD_FRESH_MINUTES = 90
# A bet on a game that is not on the board has no start time we know, so it can be removed for a short while only.
MANUAL_VOID_MINUTES = 60
SIDES = {"moneyline": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under")}

_write_lock = threading.Lock()


class BetError(ValueError):
    """A refusal with a plain sentence for the member. ``status`` is the HTTP code the API answers with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# where the ledger lives
# ---------------------------------------------------------------------------

def ledger_path(path: Optional[str] = None) -> str:
    """An explicit path wins; then HOUNDS_MEMBER_BETS_LEDGER; otherwise beside the app database (the Fly
    volume in production), next to ``hounds_user_v1.jsonl``. Never the git-tracked ``evidence/`` directory."""
    if path:
        return path
    override = (os.environ.get(ENV_LEDGER) or "").strip()
    if override:
        return override
    from src.appstate import users as users_store
    return str(users_store.db_path().parent / LEDGER_NAME)


def ledger_beside(rule_ledger: Optional[str]) -> str:
    """The member ledger that goes with a hound ledger path: the default one when none is given, otherwise the
    file beside the one given (so a test or shadow ledger gets its own, empty, member ledger)."""
    if not rule_ledger:
        return ledger_path()
    return str(Path(rule_ledger).with_name(LEDGER_NAME))


def _store(ledger: Optional[str]) -> HashChainLedger:
    return HashChainLedger(ledger_path(ledger))


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def check_price(price) -> Optional[int]:
    """None stays None. Otherwise a finite whole American price whose size passes the Bet Check bound."""
    if price is None:
        return None
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) \
            or price != int(price):
        raise BetError("That price does not look right. Type it the way a sportsbook shows it, like -110 or +150.")
    value = int(price)
    if not (MIN_PRICE_MAGNITUDE <= abs(value) <= MAX_PRICE_MAGNITUDE):
        raise BetError("That price does not look right. Type it the way a sportsbook shows it, like -110 or +150.")
    return value


def check_stake(stake) -> float:
    if isinstance(stake, bool) or not isinstance(stake, (int, float)) or not math.isfinite(stake) \
            or not (STAKE_MIN <= stake <= STAKE_MAX):
        raise BetError(f"The stake has to be between {STAKE_MIN:g} and {STAKE_MAX:g} units.")
    return float(stake)


def check_note(note) -> Optional[str]:
    if note is None:
        return None
    text = str(note).strip()
    if len(text) > NOTE_MAX:
        raise BetError(f"Keep the note to {NOTE_MAX} characters or fewer.")
    return text or None


def _line(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BetError("That line does not look right.")
    return float(value)


# ---------------------------------------------------------------------------
# the board read
# ---------------------------------------------------------------------------

def find_game(event_id: str, now: datetime, rows_for: Optional[Callable] = None):
    """The event's boards (before AND after the start), or None when no stored row names it.
    ``rows_for(date, sports)`` is the injection point; the default streams the repository store."""
    found = None
    today = datetime.fromisoformat(user_engine.slate_date_of(now))
    for delta in (-1, 0, 1):
        date = (today + timedelta(days=delta)).date().isoformat()
        source = rows_for(date, user_spec.SPORTS) if rows_for else user_engine.iter_rows(date, user_spec.SPORTS)
        found = user_engine.build_event_game(source, event_id)
        if found is not None:
            return found
    return None


def board_quote(game, market: str, side: str, now: datetime) -> Optional[dict]:
    """The current board for one side: {price, best_price, best_book, n_books, line (the side's own line),
    observed_utc}, or None when there is no board no older than BOARD_FRESH_MINUTES."""
    found = game.board_at(market, now)
    if found is None:
        return None
    observed, board = found
    if (now - observed).total_seconds() / 60.0 > BOARD_FRESH_MINUTES:
        return None
    quotes = board["sides"].get(side)
    if not quotes:
        return None
    best, best_book = user_engine.best_price(quotes)
    line = None
    if market == "spread":
        line = board["line"] if side == "home" else -board["line"]
    elif market == "total":
        line = board["line"]
    return {"price": user_engine.average_price([p for _, p in quotes]), "best_price": best, "best_book": best_book,
            "n_books": board["n_books"], "line": line, "observed_utc": user_engine._iso(observed)}


def current_price(event_id: str, market: str, side: str, *, now: Optional[datetime] = None,
                  rows_for: Optional[Callable] = None) -> dict:
    """What the Log a bet form pre-fills: {price, line, n_books} or {price: None} when the board has none."""
    now = _now(now)
    game = find_game(event_id, now, rows_for)
    quote = board_quote(game, market, side, now) if game is not None and market in MARKETS else None
    if quote is None:
        return {"price": None, "line": None, "n_books": 0}
    return {"price": quote["price"], "line": quote["line"], "n_books": quote["n_books"]}


def _selection(game, market: str, side: str, line: Optional[float]) -> str:
    if market == "total":
        return f"{side.title()} {line:g}" if line is not None else side.title()
    team = game.home_team if side == "home" else game.away_team
    if market == "spread" and line is not None:
        return f"{team} {line:+g}"
    return f"{team} to win"


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def _rows(ledger: Optional[str]) -> list:
    return _store(ledger).read()


def _owned(rows: Iterable[Mapping], owner_id) -> list:
    return [r for r in rows if r.get("owner_user_id") == owner_id]


def _graded_by_id(rows: Iterable[Mapping]) -> dict:
    return {r["bet_id"]: r for r in rows if r.get("kind") == KIND_GRADED and r.get("bet_id")}


def _is_member_row(row: Mapping) -> bool:
    return row.get("source") == "member" and row.get("kind") in (KIND_BET, KIND_MANUAL)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return "mb-" + uuid.uuid4().hex[:20]


def place_bet(owner_id, *, event_id: str, market: str, side: str, line=None, price=None, stake_units,
              note=None, now: Optional[datetime] = None, ledger: Optional[str] = None,
              rows_for: Optional[Callable] = None) -> dict:
    """Record a bet on a game on our board. Returns the ledger row. Raises BetError with a plain sentence."""
    now = _now(now)
    if market not in MARKETS:
        raise BetError("Pick moneyline, spread or total.")
    if side not in SIDES[market]:
        raise BetError("Pick a side: " + " or ".join(SIDES[market]) + ".")
    stake = check_stake(stake_units)
    typed = check_price(price)
    typed_line = _line(line)
    note = check_note(note)
    if not event_id or not isinstance(event_id, str):
        raise BetError("Pick a game first.")

    game = find_game(event_id, now, rows_for)
    if game is None or game.commence is None:
        raise BetError("We can't find that game on our board. Use Log a bet by hand instead.", status=404)
    from src.sports import catalog
    code = catalog.code_of_row_sport((game.sport or "").lower())
    commence = game.commence
    if now >= commence + timedelta(hours=catalog.live_window_hours(code) if code else 4.5):
        raise BetError("That game is already over.")
    live = now >= commence

    quote = board_quote(game, market, side, now)
    use_line = typed_line if typed_line is not None else (quote["line"] if quote else None)
    if market in ("spread", "total") and use_line is None:
        raise BetError("Add the line you bet.")
    if market == "moneyline":
        use_line = None
    # The board's price applies only when the board is on the line the member bet.
    on_board_line = quote is not None and (market == "moneyline" or typed_line is None
                                           or abs(quote["line"] - typed_line) < 1e-9)
    if typed is None:
        if not on_board_line:
            raise BetError("There is no current price on the board for that game. Type the price you got.")
        got = quote["price"]
    else:
        got = typed
    row_extra = {}
    if game.league:
        row_extra = {"league": game.league, "league_title": game.league_title}

    with _write_lock:
        store = _store(ledger)
        existing = store.read()
        mine = _owned(existing, owner_id)
        graded = _graded_by_id(existing)
        # One side per game per member (the hounds' own rule). A bet the member removed no longer counts.
        book = one_side.Book()
        hid = f"m-{owner_id}"
        for r in mine:
            if r.get("kind") != KIND_BET or (graded.get(r["bet_id"]) or {}).get("voided_by_member"):
                continue
            book.take({**r, "hound_id": hid})
        refused = book.refusal(hid, event_id, market, side, None, use_line, game={
            "sport": game.sport, "home_team": game.home_team, "away_team": game.away_team,
            "commence_time": user_engine._iso(commence), "game_pk": None})
        if refused is not None:
            raise BetError("You can only back one side of a game: " + one_side.reason_text(refused) + ".",
                           status=409)
        row = {
            "kind": KIND_BET, "ledger_version": user_engine.LEDGER_VERSION, "source": "member",
            "bet_id": _new_id(), "hound_id": None, "owner_user_id": owner_id,
            "sport": game.sport, "event_id": event_id, "game_pk": None,
            "slate_date": user_engine.slate_date_of(commence), "commence_time": user_engine._iso(commence),
            "away_team": game.away_team, "home_team": game.home_team, "market": market, "side": side,
            "line": use_line, "selection": _selection(game, market, side, use_line),
            "price": got, "best_price": got, "price_average": got, "price_best": got,
            "board_price_average": quote["price"] if on_board_line else None,
            "n_books": quote["n_books"] if on_board_line else 0,
            "board_observed_utc": quote["observed_utc"] if on_board_line else None,
            "price_source": "typed" if typed is not None and (not on_board_line or typed != quote["price"]) else "board",
            "stake_units": stake, "units": stake, "live": live, "note": note,
            "segment": "forward", "provenance": "member",
            "placed_utc": user_engine._iso(now), "recorded_utc": user_engine._iso(now),
        }
        row.update(row_extra)
        store.append(row)
    return row


def place_manual(owner_id, *, sport: str, game_text: str, side_text: str, price=None, stake_units, note=None,
                 now: Optional[datetime] = None, ledger: Optional[str] = None) -> dict:
    """Record a bet on a game that is not on our board. Never graded automatically: status "unmatched"."""
    now = _now(now)
    code = str(sport or "").strip().upper()
    if code not in user_spec.SPORTS:
        raise BetError("Pick a sport from the list.")
    game_text = str(game_text or "").strip()
    side_text = str(side_text or "").strip()
    if not game_text or len(game_text) > GAME_TEXT_MAX:
        raise BetError(f"Describe the game in {GAME_TEXT_MAX} characters or fewer.")
    if not side_text or len(side_text) > SIDE_TEXT_MAX:
        raise BetError(f"Describe your side in {SIDE_TEXT_MAX} characters or fewer.")
    row = {
        "kind": KIND_MANUAL, "ledger_version": user_engine.LEDGER_VERSION, "source": "member",
        "bet_id": _new_id(), "hound_id": None, "owner_user_id": owner_id, "sport": code, "event_id": None,
        "game_text": game_text, "side_text": side_text, "price": check_price(price),
        "stake_units": check_stake(stake_units), "note": check_note(note), "status": "unmatched",
        "live": False, "placed_utc": user_engine._iso(now), "recorded_utc": user_engine._iso(now),
    }
    with _write_lock:
        _store(ledger).append(row)
    return row


def void_bet(owner_id, bet_id: str, *, now: Optional[datetime] = None, ledger: Optional[str] = None) -> dict:
    """Remove a bet before its game starts by APPENDING a void row. After the start it stays on the record."""
    now = _now(now)
    with _write_lock:
        store = _store(ledger)
        rows = store.read()
        bet = next((r for r in _owned(rows, owner_id) if r.get("bet_id") == bet_id and _is_member_row(r)), None)
        if bet is None:
            raise BetError("We can't find that bet.", status=404)
        if bet_id in _graded_by_id(rows):
            raise BetError("That bet is already settled, so it stays on your record.", status=409)
        if bet["kind"] == KIND_MANUAL:
            placed = user_engine._utc(bet["placed_utc"])
            if placed is None or now - placed > timedelta(minutes=MANUAL_VOID_MINUTES):
                raise BetError("That bet can only be removed in the first hour after you log it.", status=409)
        else:
            start = user_engine._utc(bet.get("commence_time"))
            if start is None or now >= start:
                raise BetError("That game has started, so the bet stays on your record.", status=409)
        row = {
            "kind": KIND_GRADED, "ledger_version": user_engine.LEDGER_VERSION, "bet_id": bet_id,
            "hound_id": None, "owner_user_id": owner_id, "source": "member", "result": "VOID",
            "voided_by_member": True, "reason": "removed by the member before the game started"
            if bet["kind"] == KIND_BET else "removed by the member",
            "profit_units": 0.0, "profit_units_best": 0.0, "units": 0.0, "close_price": None, "clv_pts": None,
            "date": bet.get("slate_date"), "slate_date": bet.get("slate_date"),
            "graded_utc": user_engine._iso(now),
        }
        store.append(row)
    return row


# ---------------------------------------------------------------------------
# settling (called from the 15-minute pass)
# ---------------------------------------------------------------------------

def settle(*, ledger: Optional[str] = None, now: Optional[datetime] = None, **kwargs) -> dict:
    """Grade the member ledger with the hounds' own grader. ``alert`` is always off: a member knows what they
    bet. Reads nothing when the ledger does not exist yet."""
    path = ledger_path(ledger)
    if not os.path.exists(path):
        return {"considered": 0, "graded": 0, "pending": 0}
    kwargs.pop("alert", None)
    return user_settle.settle(ledger=path, now=now, alert=False, **kwargs)


# ---------------------------------------------------------------------------
# the member's view and record
# ---------------------------------------------------------------------------

def _game_text(row: Mapping) -> str:
    if row.get("kind") == KIND_MANUAL:
        return row.get("game_text") or ""
    return f"{row.get('away_team') or '?'} at {row.get('home_team') or '?'}"


def view_of(bet: Mapping, grade: Optional[Mapping], now: datetime) -> dict:
    """One bet as the member sees it. Only fields meant for the member: no ledger internals."""
    manual = bet.get("kind") == KIND_MANUAL
    stake = float(bet.get("stake_units") or 1.0)
    voided = bool(grade and grade.get("voided_by_member"))
    if grade is None:
        status = "unmatched" if manual else "open"
    else:
        status = "removed" if voided else "settled"
    result = grade.get("result") if grade else None
    profit = None
    if grade and result and grade.get("profit_units") is not None:
        profit = round(float(grade["profit_units"]) * stake, 4)
    start = user_engine._utc(bet.get("commence_time"))
    if grade is not None:
        can_void = False
    elif manual:
        placed = user_engine._utc(bet.get("placed_utc"))
        can_void = placed is not None and now - placed <= timedelta(minutes=MANUAL_VOID_MINUTES)
    else:
        can_void = start is not None and now < start
    return {
        "id": bet["bet_id"], "kind": "manual" if manual else "board", "status": status,
        "sport": bet.get("sport"), "game": _game_text(bet), "event_id": bet.get("event_id"),
        "market": bet.get("market"), "side": bet.get("side_text") if manual else bet.get("side"),
        "selection": bet.get("side_text") if manual else bet.get("selection"), "line": bet.get("line"),
        "price": bet.get("price"), "stake_units": stake, "live": bool(bet.get("live")),
        "in_play": bool(bet.get("live")), "note": bet.get("note"),
        "placed_utc": bet.get("placed_utc"), "start_utc": bet.get("commence_time"),
        "result": result, "units": profit, "close_price": grade.get("close_price") if grade else None,
        "clv_pts": grade.get("clv_pts") if grade else None, "reason": grade.get("reason") if grade else None,
        "score": ({"home": grade.get("home_score"), "away": grade.get("away_score")}
                  if grade and grade.get("home_score") is not None else None),
        "can_void": can_void,
    }


def record_of(views: Iterable[Mapping]) -> dict:
    """{w, l, p, void, units, stake_units, clv_mean, n_clv} over the settled bets (a void adds nothing)."""
    out = {"w": 0, "l": 0, "p": 0, "void": 0, "units": 0.0, "stake_units": 0.0, "clv_mean": None, "n_clv": 0}
    clv: list = []
    for v in views:
        if v["status"] not in ("settled", "removed"):
            continue
        key = {"WIN": "w", "LOSS": "l", "PUSH": "p", "VOID": "void"}.get(v["result"])
        if key is None:
            continue
        out[key] += 1
        if key != "void":
            out["units"] += v["units"] or 0.0
            out["stake_units"] += v["stake_units"]
        if v["clv_pts"] is not None:
            clv.append(v["clv_pts"])
    out["units"] = round(out["units"], 4)
    out["stake_units"] = round(out["stake_units"], 4)
    out["n_clv"] = len(clv)
    out["clv_mean"] = round(sum(clv) / len(clv), 3) if clv else None
    return out


def member_view(owner_id, *, now: Optional[datetime] = None, ledger: Optional[str] = None) -> dict:
    """{bets: [newest first], record, open}. Reads only this member's rows."""
    now = _now(now)
    rows = _rows(ledger)
    # settle writes its grades without an owner, so they are looked up by this member's own bet ids.
    graded = _graded_by_id(rows)
    mine = [r for r in _owned(rows, owner_id) if _is_member_row(r)]
    views = [view_of(r, graded.get(r["bet_id"]), now) for r in mine]
    views.sort(key=lambda v: (v["placed_utc"] or "", v["id"]), reverse=True)
    return {"bets": views, "record": record_of(views),
            "open": sum(1 for v in views if v["status"] in ("open", "unmatched"))}
