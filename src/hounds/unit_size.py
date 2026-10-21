"""How a viewer reads the money: a unit size, or a percent of bankroll. A LENS on the record, never the record.

WHY THIS EXISTS (owner, 2026-10-21, relaying Jacob). At a fixed $10 unit a 1-unit bet and a 3-unit bet were $10 and
$30: too small a spread to feel like money. A member wants to choose what a unit is worth, or to size bets as a
share of a bankroll that grows and shrinks. UNITS STAY THE TRUTH: every stored bet, grade, rank and the leaderboard
order is in units and does not move with this setting. The setting only decides the DOLLARS a page prints beside
the units, and it is read per viewer: a signed-in member's choice lives on the account (``member_unit_size``), a
visitor's in the browser (web/js/unitsize.js). The dollar math has ONE definition, here; web/js/unitsize.js is its
port, and tests/test_unit_size.py runs both over the same bets and demands the same dollars.

THE TWO MODES (each is pinned by tests/test_unit_size.py; worked example: docs/BANKROLL.md)
  * ``fixed``  one unit = ``unit_usd`` whole dollars ($1 to $1,000; chips $10 / $25 / $50 / $100; default $25).
    The starting bankroll is 100 units (``unit_usd * 100``), so the account of any unit size is the same account at a
    different scale: dollars are ``units * unit_usd`` to the cent, and return % and every rank are IDENTICAL for
    every unit size.
  * ``percent``  one unit = ``pct`` percent of the balance at the time the bet is placed (0.5 to 5 in steps of 0.5,
    default 1), on a starting bankroll the viewer sets ($100 to $100,000, default $2,500). A bet of ``s`` units risks
    ``s * pct%`` of that balance, so it COMPOUNDS: dollars are not ``units * constant`` here and the return % is the
    compounded figure at that sizing (the pages label it "at your sizing"). The unit-based ranks do not move.

WHAT "THE BALANCE AT THE TIME THE BET IS PLACED" MEANS. Bets are taken slate day by slate day, in date order. Every
bet of one slate day is open at once, so all of them are sized off the SAME balance: the one after every earlier
slate day has settled, before any bet of this day settles ("concurrent open bets are sized off the balance before
any of them settle"). Two bets of one day therefore never size off each other. The balance path (peak, drawdown) and
the 24h / 7d / 30d windows then use each bet's settle time, exactly as the fixed view does.

Standard library only (no FastAPI), so it loads where the app does not.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

from src.appstate import users as users_store

# ---- the choices (web/js/unitsize.js mirrors these; tests/test_unit_size.py pins the pair) ----------------------
FIXED_MIN, FIXED_MAX = 1, 1000
#: quick chips for the fixed mode; any whole dollar from FIXED_MIN to FIXED_MAX is also valid
FIXED_CHIPS = (10, 25, 50, 100)
DEFAULT_FIXED_USD = 25
#: the fixed starting bankroll is this many units, at every unit size (so return % does not depend on the size)
UNITS_IN_START = 100
PCT_CHOICES = tuple(i / 2 for i in range(1, 11))          # 0.5, 1.0 ... 5.0
DEFAULT_PCT = 1.0
START_MIN, START_MAX = 100, 100000
DEFAULT_START_USD = 2500
MODES = ("fixed", "percent")


class SizingError(ValueError):
    """A refusal the caller can show: ``code`` is stable, the message is for people."""

    def __init__(self, code: str, message: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class Sizing:
    mode: str
    unit_usd: Optional[float]      # fixed mode: dollars per unit; None in percent mode
    pct: Optional[float]           # percent mode: percent of the balance per unit; None in fixed mode
    start_usd: float               # the opening balance (fixed: 100 units; percent: the viewer's own)

    def as_dict(self) -> dict:
        return {"mode": self.mode, "unit_usd": self.unit_usd, "pct": self.pct, "start_usd": self.start_usd}


def fixed(unit_usd: float) -> Sizing:
    """A fixed-dollar sizing WITHOUT validation (the server's own reference unit, which may be a cents value)."""
    return Sizing("fixed", float(unit_usd), None, float(unit_usd) * UNITS_IN_START)


def default_sizing() -> Sizing:
    return fixed(DEFAULT_FIXED_USD)


def _whole(value, lo: float, hi: float, code: str, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise SizingError(code, f"{what} must be a whole number of dollars")
    if float(value) != int(value):
        raise SizingError(code, f"{what} must be a whole number of dollars")
    n = int(value)
    if not lo <= n <= hi:
        raise SizingError(code, f"{what} must be between ${int(lo):,} and ${int(hi):,}")
    return n


def validate(raw) -> Sizing:
    """A viewer's sizing from untrusted input, or ``SizingError``. Nothing is coerced from text and nothing is
    guessed: a string, a fractional dollar or a percent off the half-point steps is refused (a field the chosen mode
    does not use is ignored), so what is stored is always exactly what the page will read back."""
    if not isinstance(raw, dict):
        raise SizingError("sizing_shape", "send a sizing object")
    mode = raw.get("mode")
    if mode not in MODES:
        raise SizingError("sizing_mode", "mode must be 'fixed' or 'percent'")
    if mode == "fixed":
        unit = _whole(raw.get("unit_usd"), FIXED_MIN, FIXED_MAX, "unit_usd", "a unit")
        return fixed(unit)
    pct = raw.get("pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or float(pct) not in PCT_CHOICES:
        raise SizingError("pct", "the percent must be 0.5 to 5 in steps of 0.5")
    start = _whole(raw.get("start_usd"), START_MIN, START_MAX, "start_usd", "the starting bankroll")
    return Sizing("percent", None, float(pct), float(start))


# ---- the dollars -------------------------------------------------------------------------------

def priced(evts: list, sizing: Sizing) -> list:
    """``[(profit_usd, staked_usd)]`` aligned with ``evts`` (``bankroll.Event``), the one definition of the module
    docstring. ``Event.units`` is the stake-weighted profit and ``Event.stake`` the units risked."""
    if sizing.mode == "fixed":
        unit = float(sizing.unit_usd)
        return [(e.units * unit, e.stake * unit) for e in evts]
    share = float(sizing.pct) / 100.0
    out = [(0.0, 0.0)] * len(evts)
    by_day: dict = {}
    for i, e in enumerate(evts):
        by_day.setdefault(str(e.order[0]) if e.order else "", []).append(i)
    balance = float(sizing.start_usd)
    for day in sorted(by_day):
        base = balance                                     # every bet of the day is sized off this one balance
        total = 0.0
        for i in by_day[day]:
            e = evts[i]
            out[i] = (e.units * share * base, e.stake * share * base)
            total += out[i][0]
        balance += total
    return out


#: the compact result: w(in), l(oss), p(ush); an open or void bet is "" (neither decided nor settled)
RESULT_LETTER = {"win": "w", "loss": "l", "push": "p"}


# ---- the web client's wire form ---------------------------------------------------------------

def wire_events(evts: Iterable) -> list:
    """The compact ``events`` list a payload's bankroll block carries so the browser can price the same bets at the
    viewer's sizing: ``[slate_date, settle_epoch_seconds | null, profit_units, stake_units, result_letter]``. Units only;
    no dollar crosses the wire from here, and the ranks never read it."""
    out = []
    for e in evts:
        settle = e.settle.astimezone(timezone.utc) if isinstance(e.settle, datetime) else None
        out.append([str(e.order[0]) if e.order else "", int(settle.timestamp()) if settle else None,
                    round(e.units + 0.0, 4), round(e.stake + 0.0, 4), RESULT_LETTER.get(e.result, "")])
    return out


def from_wire(events: Iterable) -> list:
    """``bankroll.Event`` objects back from a payload's ``events`` list (the inverse of ``wire_events``), for a caller
    that holds only the wire form (the dog's chat answers price a replay at the asker's sizing from it)."""
    from src.hounds import bankroll
    word = {"w": "win", "l": "loss", "p": "push"}
    out = []
    for i, e in enumerate(events or []):
        if not isinstance(e, (list, tuple)) or len(e) < 5:
            continue
        settle = datetime.fromtimestamp(e[1], tz=timezone.utc) if isinstance(e[1], (int, float)) else None
        out.append(bankroll.Event(settle=settle, units=float(e[2]), flat=float(e[2]), stake=float(e[3]),
                                  result=word.get(e[4], "void"), order=(str(e[0]), f"{i:06d}")))
    return out


# ---- a member's saved choice -------------------------------------------------------------------

_lock = threading.Lock()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS member_unit_size (
            user_id INTEGER PRIMARY KEY,
            mode TEXT NOT NULL,
            unit_usd INTEGER,
            pct REAL,
            start_usd INTEGER,
            updated_at TEXT
        )
    """)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Its own table in the app database, PRIVATE to the account: it is never joined into a public payload (the
    kennel name lives apart in ``member_profiles`` for the opposite reason)."""
    with users_store._connect() as conn:
        _ensure_schema(conn)
        yield conn


def get(user_id: int) -> Sizing:
    """The member's saved sizing, else the default. A broken row is the default too."""
    try:
        if not users_store.db_path().is_file():
            return default_sizing()
        with _connect() as conn:
            row = conn.execute("SELECT mode, unit_usd, pct, start_usd FROM member_unit_size WHERE user_id = ?",
                               (int(user_id),)).fetchone()
    except (sqlite3.Error, OSError):
        return default_sizing()
    if row is None:
        return default_sizing()
    try:
        return validate({"mode": row["mode"], "unit_usd": row["unit_usd"], "pct": row["pct"],
                         "start_usd": row["start_usd"]})
    except SizingError:
        return default_sizing()


def save(user_id: int, raw, *, now: Optional[datetime] = None) -> Sizing:
    """Validate and store the member's sizing; returns what was stored."""
    sizing = validate(raw)
    if users_store.get_user(int(user_id)) is None:
        raise SizingError("not_found", "no such member", 404)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    unit = int(sizing.unit_usd) if sizing.unit_usd is not None else None
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO member_unit_size (user_id, mode, unit_usd, pct, start_usd, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET mode = excluded.mode, "
            "unit_usd = excluded.unit_usd, pct = excluded.pct, start_usd = excluded.start_usd, "
            "updated_at = excluded.updated_at",
            (int(user_id), sizing.mode, unit, sizing.pct, int(sizing.start_usd), stamp))
    return sizing


def choices() -> dict:
    """The legal values, for the endpoint and for a page that wants to draw its pickers from the server."""
    return {"modes": list(MODES), "fixed": {"min": FIXED_MIN, "max": FIXED_MAX, "chips": list(FIXED_CHIPS),
                                            "default": DEFAULT_FIXED_USD, "units_in_start": UNITS_IN_START},
            "percent": {"choices": list(PCT_CHOICES), "default": DEFAULT_PCT, "start_min": START_MIN,
                        "start_max": START_MAX, "start_default": DEFAULT_START_USD},
            "default": default_sizing().as_dict()}
