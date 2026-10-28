"""The credit cap guard for LIVE_TENNIS_V1 (docs/PREREG_LIVE_TENNIS.md section 9).

`can_spend` is checked BEFORE every paid call and fails CLOSED. In order:

    1  the switch: LIVE_TENNIS_TEST must be 'on', else refuse (the default). No request is made while OFF.
    2  a non-positive request is allowed (free calls)
    3  after the stop date: refuse
    4  the balance must be readable: an unreadable quota refuses
    5  the repository's credit floor (`budget.CREDIT_FLOOR`, 5,000): refuse if the balance would reach it
    6  the test's own daily cap (DAILY_CREDIT_CAP, 200), summed from this test's own credit rows
    7  the pre-match sub-cap (PREMATCH_DAILY_SUBCAP, 60) for a pre-match-only purpose
    8  the test's own monthly cap (MONTHLY_CREDIT_CAP, 4,000)
    9  the owner's shared in-play cap (`budget.LIVE_ODDS_DAILY_CAP`, 300 a day across every sport): the live_odds
       band's direct-sum total for the day plus this call must stay within it

Every paid call is logged by `log_call` to the live credit log under the existing direct-sum band `live_odds`,
from the call's OWN `x-requests-last` (one when the vendor sent none, never zero), so spend is billed to the live
band and never inferred from a later balance delta. Nothing here widens a cap: a refusal is a recorded outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, List, Mapping, Optional, Sequence

from src.capture import budget
from src.pipeline import creditlog
from src.research.live_tennis import config

PURPOSE_PREMATCH = "prematch"
PURPOSES = (PURPOSE_PREMATCH, "decision", "reference")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def default_stores() -> list:
    return [budget.LIVE_CREDIT_LOG_PATH, budget.CREDIT_LOG_PATH]


def read_rows(stores: Optional[Sequence] = None) -> List[dict]:
    rows: List[dict] = []
    for store in (stores if stores is not None else default_stores()):
        rows.extend(creditlog.read(store))
    rows.sort(key=lambda r: r.get("utc") or "")
    return rows


def _utc(now: Optional[datetime]) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def spent(rows: Iterable[Mapping], *, day: Optional[str] = None, month: Optional[str] = None,
          caller_prefix: Optional[str] = None, band: Optional[str] = None) -> int:
    """Sum of `credits_used_last` over rows on a UTC day / month, optionally for one caller prefix or band."""
    total = 0
    for row in rows:
        utc = str(row.get("utc") or "")
        if day is not None and utc[:10] != day:
            continue
        if month is not None and utc[:7] != month:
            continue
        if caller_prefix is not None and not str(row.get("caller") or "").startswith(caller_prefix):
            continue
        if band is not None and budget.row_band(row) != band:
            continue
        total += int(row.get("credits_used_last") or 0)
    return total


def can_spend(est: int, *, purpose: str = "decision", now: Optional[datetime] = None, env: Optional[Mapping] = None,
              remaining: Optional[int] = None, stores: Optional[Sequence] = None,
              rows: Optional[Sequence[Mapping]] = None) -> Decision:
    if not config.switch_on(env):
        return Decision(False, f"refused: live tennis test is OFF ({config.ENV_SWITCH} is not on)")
    if est <= 0:
        return Decision(True, "ok: non-positive request")
    if purpose not in PURPOSES:
        return Decision(False, f"refused: unknown purpose {purpose!r}")
    moment = _utc(now)
    if moment.date() > date.fromisoformat(config.STOP_DATE):
        return Decision(False, f"refused: past the stop date {config.STOP_DATE}")
    if remaining is None:
        return Decision(False, "skipped: quota unreadable (fails closed)")
    if remaining - est <= budget.CREDIT_FLOOR:
        return Decision(False, f"skipped: credit floor (remaining={remaining}, floor={budget.CREDIT_FLOOR}, requested={est})")
    data = list(rows) if rows is not None else read_rows(stores)
    day, month = moment.strftime("%Y-%m-%d"), moment.strftime("%Y-%m")
    own_day = spent(data, day=day, caller_prefix=config.CREDIT_CALLER)
    if own_day + est > config.DAILY_CREDIT_CAP:
        return Decision(False, f"refused: daily cap ({own_day} of {config.DAILY_CREDIT_CAP} spent today, +{est} would exceed it)")
    if purpose == PURPOSE_PREMATCH:
        own_pre = spent(data, day=day, caller_prefix=config.CREDIT_CALLER_PREMATCH)
        if own_pre + est > config.PREMATCH_DAILY_SUBCAP:
            return Decision(False, f"refused: pre-match sub-cap ({own_pre} of {config.PREMATCH_DAILY_SUBCAP} spent today)")
    own_month = spent(data, month=month, caller_prefix=config.CREDIT_CALLER)
    if own_month + est > config.MONTHLY_CREDIT_CAP:
        return Decision(False, f"refused: monthly cap ({own_month} of {config.MONTHLY_CREDIT_CAP} spent this month)")
    shared = spent(data, day=day, band=budget.LIVE_ODDS)
    if shared + est > budget.LIVE_ODDS_DAILY_CAP:
        return Decision(False, f"refused: shared live-odds cap ({shared} of {budget.LIVE_ODDS_DAILY_CAP} spent today)")
    return Decision(True, f"ok: {own_day}+{est} of {config.DAILY_CREDIT_CAP} today, {own_month}+{est} of {config.MONTHLY_CREDIT_CAP} this month")


def caller_for(purpose: str) -> str:
    return config.CREDIT_CALLER_PREMATCH if purpose == PURPOSE_PREMATCH else config.CREDIT_CALLER


def log_call(*, purpose: str, usage: Optional[Mapping], now: Optional[datetime] = None,
             store=None, record=None) -> int:
    """Append this call's own cost to the live credit log; return the credits billed (>= 1: never undercount)."""
    usage = usage or {}
    last = usage.get("last")
    billed = int(last) if isinstance(last, (int, float)) and not isinstance(last, bool) and last > 0 else 1
    writer = record or creditlog.log
    kwargs = {"budget_band": config.CREDIT_BAND}
    if store is not None:
        kwargs["store"] = store
    else:
        kwargs["store"] = budget.LIVE_CREDIT_LOG_PATH
    writer(usage.get("remaining"), billed, caller_for(purpose), now=_utc(now) if now else None, **kwargs)
    return billed
