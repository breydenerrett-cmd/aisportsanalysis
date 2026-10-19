"""The bankroll view: the same graded bets as the record, shown as dollars from one shared starting balance.

WHY THIS EXISTS (owner, 2026-10-19). The board showed "up 2 units" next to "ROI 71%": two different
denominators (units won, and profit per bet) on one row, so neither read like money. Every simulated account now
starts with the same $1,000 paper bankroll, one unit is a fixed 1% of that STARTING bankroll ($10), and the
number a bettor reads first is the account balance and the % it moved. Nothing here is a new bet, a new grade or
a new price: it is a presentation of the bets ``src.hounds.stats`` already counts. Definitions and worked
examples: docs/BANKROLL.md. Constants: config/bankroll.json.

THE DEFINITIONS (each one is pinned by tests/test_hounds_bankroll.py)
  * ``unit_usd`` = ``starting_bankroll * unit_pct / 100`` = $10. FLAT: the unit never grows or shrinks with the
    balance (no compounding), so a $ profit is a plain sum over bets and 7d + earlier = season, to the cent.
  * House, baseline and desk dogs stake exactly 1 unit ($10) per bet. A member dog stakes its spec's
    ``stake_units`` (0.5 to 3, ``user_rules.STAKE_CHOICES``), read from its own graded bet. This supersedes the
    "every bet counts as one unit" ruling for the bankroll view ONLY; ``record.units_*`` stays flat, and
    ``bankroll.units_flat`` is the flat figure on the same price basis for comparison.
  * Each bet's profit in units is the one ``summarize`` already uses: at the board-average price when 90% of the
    priced bets have one, else at the recorded price (``basis`` says which). Dollars = units * stake * unit_usd.
  * ``return_pct`` = pnl / starting bankroll * 100. ``yield_pct`` = pnl / dollars staked on bets that were
    actually decided (win or loss; a push or void gets its stake back) * 100: "profit per $ bet", the old ROI.
    Two different denominators are not shown side by side on a board; yield lives on the detail page only.
  * Windows (h24, d7, d30) are by SETTLE time in UTC (when the bet was graded), inside the view being asked
    for (a season view only holds that season's bets). ``season`` is the whole view. A window covers
    ``(now - length, now]``: a bet settled exactly 24 hours ago is OUT of h24; a stamp in the future is treated
    as "just now". The block is recomputed against the clock every time a payload is built (``refreshed``), so a
    cached book never shows yesterday's "24h".
  * Settle time. Pack and member graded rows carry ``graded_utc``; the engine account ledgers carry only the
    slate day. A bet with no stamp is ESTIMATED to have settled ``fallback_settle_hours_after_slate_start`` hours
    after 00:00 UTC of its slate date (30h = 06:00 UTC next morning, after the last west-coast game). ``settle_estimated`` says how many bets used the estimate.
  * ``small_sample`` is true under ``small_sample_min_settled`` (20) settled bets in the view: the UI greys it.
  * ``max_drawdown_*`` is the worst peak-to-trough fall of the account balance, bets taken in settle order,
    starting from the opening balance (so a model that only ever lost has a drawdown from $1,000).

Standard library only (no FastAPI), so it loads where the app does not.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.paths import repo_root

#: the largest paper stake a member dog can choose (``user_rules.STAKE_CHOICES``); a pinned test keeps the two equal
MAX_STAKE_UNITS = 3.0
FLAT_STAKE_UNITS = 1.0

#: what is used if config/bankroll.json is missing or unreadable (the owner's 2026-10-19 decision)
_DEFAULTS = {"currency": "USD", "starting_bankroll": 1000.0, "unit_pct": 1.0,
             "small_sample_min_settled": 20, "fallback_settle_hours_after_slate_start": 30.0}

WINDOWS = (("h24", timedelta(hours=24)), ("d7", timedelta(days=7)), ("d30", timedelta(days=30)))
DECIDED = ("win", "loss")
SETTLED = ("win", "loss", "push")

_CACHE: dict = {"key": None, "params": None}


@dataclass(frozen=True)
class Params:
    currency: str
    start: float
    unit_pct: float
    unit_usd: float
    small_sample_min: int
    fallback_hours: float


def config_path() -> Path:
    return repo_root() / "config" / "bankroll.json"


def _positive(value, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) < 1e9:
        return float(default)
    return float(value)


def params() -> Params:
    """The bankroll constants, re-read when the file's size or mtime changes. A missing or broken file means the
    defaults above, and a nonsense value (zero, negative, text) falls back to its default on its own."""
    path = config_path()
    try:
        st = os.stat(path)
        key = (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        key = (str(path), None, None)
    if _CACHE["key"] == key and _CACHE["params"] is not None:
        return _CACHE["params"]
    raw: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        raw = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        raw = {}
    start = _positive(raw.get("starting_bankroll"), _DEFAULTS["starting_bankroll"])
    pct = _positive(raw.get("unit_pct"), _DEFAULTS["unit_pct"])
    small = raw.get("small_sample_min_settled")
    small = int(small) if isinstance(small, int) and not isinstance(small, bool) and small >= 0 \
        else _DEFAULTS["small_sample_min_settled"]
    out = Params(currency=str(raw.get("currency") or _DEFAULTS["currency"]), start=start, unit_pct=pct,
                 unit_usd=round(start * pct / 100.0, 6), small_sample_min=small,
                 fallback_hours=_positive(raw.get("fallback_settle_hours_after_slate_start"),
                                          _DEFAULTS["fallback_settle_hours_after_slate_start"]))
    _CACHE["key"], _CACHE["params"] = key, out
    return out


def _money(value: float) -> str:
    return f"{value:,.0f}" if abs(value - round(value)) < 1e-9 else f"{value:,.2f}"


def public_block() -> dict:
    """The constants every payload that carries bankroll figures also states, so a page never hard-codes them."""
    p = params()
    return {"currency": p.currency, "start_usd": p.start, "unit_pct": p.unit_pct, "unit_usd": p.unit_usd,
            "flat_stakes": True, "paper": True,
            "label": (f"Every model starts with the same ${_money(p.start)} paper bankroll. "
                      f"1 unit = ${_money(p.unit_usd)}."),
            "note": ("A unit is a fixed share of the STARTING bankroll, not of the current balance, so it does not "
                     "compound. House dogs bet 1 unit; a member dog bets the units its owner chose (0.5 to 3).")}


# ---- one settled bet --------------------------------------------------------------------------

@dataclass
class Event:
    """One graded forward bet as the bankroll sees it. ``units`` is already stake-weighted."""
    settle: Optional[datetime]
    units: float            # profit in units * the stake (the dollars are units * unit_usd)
    flat: float             # the same bet at one unit
    stake: float            # units staked
    result: str
    estimated: bool = False
    order: tuple = ()


def stake_of(bet, kind: Optional[str]) -> float:
    """Units staked on ``bet``: the member dog's own chosen stake, else exactly one unit. A stake that is not a
    sane number (missing, zero, negative, above ``MAX_STAKE_UNITS``) is one unit, the default every v1 member dog
    has always had."""
    if kind != "user":
        return FLAT_STAKE_UNITS
    value = getattr(bet, "stake_units", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) <= MAX_STAKE_UNITS:
        return FLAT_STAKE_UNITS
    return float(value)


def _utc(value) -> Optional[datetime]:
    from src.hounds.contract import _utc as parse
    return parse(value)


def settle_time(bet, p: Optional[Params] = None) -> tuple:
    """``(datetime | None, estimated)``: the bet's own ``graded_utc``, else the estimate described above, else
    (None, True) when the bet has neither a stamp nor a readable slate date."""
    p = p or params()
    stamped = _utc(getattr(bet, "graded_utc", None))
    if stamped is not None:
        return stamped, False
    text = str(getattr(bet, "date", "") or "")[:10]
    try:
        day = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError:
        return None, True
    return day + timedelta(hours=p.fallback_hours), True


def events(graded_bets: Iterable, units_fn: Callable, kind: Optional[str], p: Optional[Params] = None) -> list:
    """The bankroll events for one hound's graded forward bets. ``units_fn(bet)`` is the one-unit profit on the
    hound's price basis (``stats.average_units`` or ``stats.recorded_units``); None counts as 0, as the record does."""
    p = p or params()
    out = []
    for bet in graded_bets:
        flat = units_fn(bet) or 0.0
        stake = stake_of(bet, kind)
        when, estimated = settle_time(bet, p)
        out.append(Event(settle=when, units=flat * stake, flat=flat, stake=stake, result=bet.result,
                         estimated=estimated, order=(str(bet.date or ""), str(bet.bet_id or ""))))
    return out


# ---- the block --------------------------------------------------------------------------------

def _r(x: Optional[float], nd: int = 2) -> Optional[float]:
    return None if x is None else round(x + 0.0, nd)


def _window(rows: list, p: Params) -> dict:
    units = sum(e.units for e in rows)
    pnl = units * p.unit_usd
    return {"pnl_usd": _r(pnl), "return_pct": _r(pnl / p.start * 100.0), "units": _r(units),
            "bets": len(rows), "settled": sum(1 for e in rows if e.result in SETTLED)}


def _sort_key(e: Event):
    return (e.settle is not None, e.settle or datetime.min.replace(tzinfo=timezone.utc), e.order)


def block(evts: list, now: Optional[datetime] = None, basis: Optional[str] = None,
          p: Optional[Params] = None) -> dict:
    """The ``bankroll`` block of a summary for these events as of ``now`` (UTC; default the clock)."""
    p = p or params()
    now = now or datetime.now(timezone.utc)
    ordered = sorted(evts, key=_sort_key)
    balance = peak = p.start
    worst = worst_pct = 0.0
    for e in ordered:
        balance += e.units * p.unit_usd
        peak = max(peak, balance)
        drop = peak - balance
        if drop > worst + 1e-9:
            worst, worst_pct = drop, drop / peak * 100.0
    units = sum(e.units for e in ordered)
    pnl = units * p.unit_usd
    decided = [e for e in ordered if e.result in DECIDED]
    wagered = sum(e.stake for e in decided) * p.unit_usd
    settled = sum(1 for e in ordered if e.result in SETTLED)
    windows = {}
    for name, length in WINDOWS:
        cutoff = now - length
        windows[name] = _window([e for e in ordered if e.settle is not None and e.settle > cutoff], p)
    windows["season"] = _window(ordered, p)
    return {
        "start": p.start, "current": _r(p.start + pnl), "pnl_usd": _r(pnl), "return_pct": _r(pnl / p.start * 100.0),
        "units_total": _r(units), "units_flat": _r(sum(e.flat for e in ordered)),
        "unit_usd": p.unit_usd, "unit_pct": p.unit_pct,
        "bets": len(ordered), "settled": settled, "small_sample": settled < p.small_sample_min,
        "small_sample_min": p.small_sample_min,
        "wagered_usd": _r(wagered), "yield_pct": _r(pnl / wagered * 100.0) if wagered > 0 else None,
        "peak": _r(peak), "max_drawdown_usd": _r(worst), "max_drawdown_pct": _r(worst_pct),
        "stake_units": _r(ordered[-1].stake, 3) if ordered else None,
        "avg_stake_units": _r(sum(e.stake for e in ordered) / len(ordered), 3) if ordered else None,
        "windows": windows, "settle_estimated": sum(1 for e in ordered if e.estimated),
        "basis": basis, "currency": p.currency,
    }


def attach(summary, evts: list, basis: Optional[str], now: Optional[datetime] = None) -> None:
    """Put the block on ``summary`` and keep the events (a plain attribute, not a dataclass field, so it is
    never serialised) for ``refreshed``."""
    summary.bankroll = block(evts, now, basis)
    summary._bankroll_events = evts


def refreshed(summary, now: Optional[datetime] = None):
    """``summary`` with its bankroll windows recomputed against ``now``. A cached book can be hours old, and a
    "last 24 hours" figure must be about the 24 hours before THIS request. A summary built without events (a
    test double, a copy that lost the attribute) is returned as it is."""
    evts = getattr(summary, "_bankroll_events", None)
    if evts is None:
        return summary
    out = copy.copy(summary)
    out.bankroll = block(evts, now, (summary.bankroll or {}).get("basis"))
    return out


def refreshed_all(summaries: list, now: Optional[datetime] = None) -> list:
    now = now or datetime.now(timezone.utc)
    return [refreshed(s, now) for s in summaries]
