"""What a FULL REBUILD may cost, and who may ask for one (owner request 2026-10-27).

A full rebuild asks Claude (several parallel Haiku calls, an analyst and an explainer, see ``rebuild_ai``) to re-think a hound from its whole record. That is
real money against the owner's hard AI cap (``AI_PAID_CAP_USD``, default $5 a month, ``src/ai/router.py``), so three walls
stand in front of every call, all checked BEFORE any model is asked:

  1. THE KEY. ``ANTHROPIC_API_KEY`` is read by name from the environment (``src.analyst.config.ENV_KEY`` is the same name). With
     none, the rebuild is "unavailable right now": a plain answer, never a stack trace.
  2. THE MEMBER'S DAY. ``FREE_REBUILDS_PER_DAY`` / ``PAID_REBUILDS_PER_DAY`` full rebuilds per UTC day, counted from the rebuild's
     own ledger. A rebuild that never reached a model (unavailable, over a limit) is not counted.
  3. THE MONTH. The rebuild's worst-case cost (the prompt's estimated tokens plus every output token the calls may write, at
     the model's price) is added to what rebuilds have already spent this month and must stay under ``MONTHLY_REBUILD_USD``;
     it must also fit under what is left of the router's shared monthly cap, so a rebuild can never push the app past
     ``AI_PAID_CAP_USD``. Spend is the API's own ``usage`` times the price, never a guess; a call whose usage is missing is
     charged its worst case.

The ledger is an append-only JSON-lines file next to the router's usage file (it survives deploys). It holds who (a user id and
a hound id), when, how many calls and what they cost. It never holds a prompt, a reply or a key.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

KEY_ENV = "ANTHROPIC_API_KEY"
LEDGER_ENV = "HOUNDS_REBUILD_LEDGER"
FINE_TUNE_STATUS_PREFIX = "fine_tune"

# The member's day. One for a free account (their one hound can still be rebuilt once a day), three for a paid one.
FREE_REBUILDS_PER_DAY = 1
PAID_REBUILDS_PER_DAY = 3

# The rebuilds' own monthly ceiling, UNDER the router's shared cap. A rebuild costs a few cents (see the estimate in the docs),
# so $2 is on the order of a hundred rebuilds; the owner can lower it by environment without a deploy.
MONTHLY_REBUILD_USD = 2.0
MONTHLY_REBUILD_ENV = "HOUNDS_REBUILD_MONTHLY_USD"

# Prices per million tokens as (input, output, input past 100K, output past 100K), from the claude-api skill price table
# (2026-10-06). Haiku 5.5 is every stage's model; Sonnet 5.5 is only used when ``rebuild_ai.USE_SONNET_SYNTHESIS`` is switched on.
HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
PRICES = {HAIKU: (0.10, 0.50, 0.50, 2.50), SONNET: (2.00, 10.00, 2.00, 10.00)}
LONG_PROMPT_TOKENS = 100_000
CHARS_PER_TOKEN_WORST = 3.0           # the estimate over-counts, never under (same stance as the router)


class BudgetError(Exception):
    """A refusal the page shows in words. ``code`` is stable: unavailable | daily_limit | monthly_spend."""

    def __init__(self, code: str, message: str, status: int = 429, **extra):
        self.code = code
        self.status = status
        self.extra = extra
        super().__init__(message)


UNAVAILABLE_TEXT = "The full rebuild is unavailable right now. Fine-tune still works, and you can try the rebuild again later."


def api_key(env: Optional[Mapping] = None) -> Optional[str]:
    """The key, or None. Read by NAME; the value is never logged or returned to a page."""
    value = str((env if env is not None else os.environ).get(KEY_ENV) or "").strip()
    return value or None


def monthly_cap(env: Optional[Mapping] = None) -> float:
    raw = str((env if env is not None else os.environ).get(MONTHLY_REBUILD_ENV) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return MONTHLY_REBUILD_USD
    return value if math.isfinite(value) and value >= 0 else MONTHLY_REBUILD_USD


def limit_for(paid: bool) -> int:
    return PAID_REBUILDS_PER_DAY if paid else FREE_REBUILDS_PER_DAY


def token_estimate(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN_WORST)


def prices(model: str, input_tokens: int) -> tuple:
    p_in, p_out, p_in_long, p_out_long = PRICES.get(model, PRICES[SONNET])      # an unknown model is priced as the dearer one
    return (p_in_long, p_out_long) if input_tokens > LONG_PROMPT_TOKENS else (p_in, p_out)


def worst_case_cost(model: str, input_tokens: int, max_output_tokens: int, calls: int = 1) -> float:
    """The most ``calls`` calls could cost: the whole prompt in, every allowed output token out."""
    p_in, p_out = prices(model, input_tokens)
    return round(calls * (input_tokens * p_in + max_output_tokens * p_out) / 1e6, 6)


def usage_cost(model: str, usage) -> Optional[float]:
    """The cost of one call from the API's own ``usage`` (None when it is missing, so the caller charges the worst case).
    Cache tokens are counted at the plain input price (the rebuild does not cache, so they are zero; counting them is the
    cautious choice)."""
    if usage is None:
        return None
    def n(key):
        value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, 0)
        return int(value or 0)
    tokens_in = n("input_tokens") + n("cache_creation_input_tokens") + n("cache_read_input_tokens")
    p_in, p_out = prices(model, tokens_in)
    return round((tokens_in * p_in + n("output_tokens") * p_out) / 1e6, 8)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_ledger_path() -> Path:
    override = os.environ.get(LEDGER_ENV)
    if override:
        return Path(override)
    from src.ai.router import default_usage_path
    return Path(default_usage_path()).parent / "rebuild_usage.jsonl"


class RebuildLedger:
    """One JSON line per rebuild that reached a model. Small (a handful of rows a day), so it is read whole."""

    def __init__(self, path=None, *, clock: Optional[Callable[[], datetime]] = None):
        self.path = Path(path) if path is not None else None
        self._clock = clock or _utcnow
        self._lock = threading.Lock()
        self._memory: list = []

    def _file(self) -> Path:
        return self.path if self.path is not None else default_ledger_path()

    def now(self) -> datetime:
        return self._clock()

    def rows(self) -> list:
        with self._lock:
            path = self._file()
            out = []
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            continue                   # a torn last line is left alone
            except OSError:
                pass
            return out

    def record(self, *, user_id: int, hound_id: str, status: str, calls: int, cost_usd: float, input_tokens: int,
               output_tokens: int) -> dict:
        moment = self.now().astimezone(timezone.utc)
        row = {"ts": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "day": moment.date().isoformat(), "month": moment.strftime("%Y-%m"),
               "user_id": int(user_id), "hound_id": str(hound_id), "status": status, "calls": int(calls),
               "cost_usd": round(float(cost_usd), 8), "input_tokens": int(input_tokens), "output_tokens": int(output_tokens)}
        with self._lock:
            path = self._file()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        return row

    def used_today(self, user_id: int) -> int:
        """Full rebuilds this member has made today. A fine-tune's one-line write-up is logged here for its few cents of spend but is
        not a rebuild, so it never counts against the member's day."""
        day = self.now().astimezone(timezone.utc).date().isoformat()
        return sum(1 for r in self.rows() if r.get("user_id") == int(user_id) and r.get("day") == day
                   and not str(r.get("status") or "").startswith(FINE_TUNE_STATUS_PREFIX))

    def month_spend(self) -> float:
        month = self.now().astimezone(timezone.utc).strftime("%Y-%m")
        return round(sum(float(r.get("cost_usd") or 0.0) for r in self.rows() if r.get("month") == month), 8)


def router_headroom(router_spend: Optional[Callable[[], tuple]] = None) -> Optional[float]:
    """Dollars left under the router's shared monthly cap, or None when it cannot be read (then the rebuild's own ceiling
    stands alone). ``router_spend`` returns ``(spent, cap)``; the default reads the process's router."""
    try:
        if router_spend is None:
            from src.ai import router as router_mod
            r = router_mod.default_router()
            spent, cap = r.paid_spend(), router_mod.paid_cap_usd()
        else:
            spent, cap = router_spend()
        return max(0.0, float(cap) - float(spent))
    except Exception:  # noqa: BLE001 -- a meter that cannot be read must not break the page; the rebuild ceiling still applies
        return None


def check(user_id: int, *, paid: bool, worst_cost: float, ledger: RebuildLedger, env: Optional[Mapping] = None,
          router_spend: Optional[Callable[[], tuple]] = None) -> dict:
    """Raise ``BudgetError`` when this rebuild may not be made; else the numbers the page shows."""
    if api_key(env) is None:
        raise BudgetError("unavailable", UNAVAILABLE_TEXT, 503)
    limit = limit_for(paid)
    used = ledger.used_today(user_id)
    if used >= limit:
        raise BudgetError("daily_limit", f"You have used today's {limit} full rebuild{'s' if limit != 1 else ''}. "
                                         "Fine-tune is still open, and the rebuild resets tomorrow (UTC).", 429,
                          used=used, limit=limit)
    spent = ledger.month_spend()
    cap = monthly_cap(env)
    headroom = router_headroom(router_spend)
    if spent + worst_cost > cap or (headroom is not None and worst_cost > headroom):
        raise BudgetError("monthly_spend", "Full rebuilds have reached this month's spending limit. "
                                           "Fine-tune still works, and the rebuild is back next month.", 429)
    return {"used_today": used, "limit_per_day": limit, "left_today": limit - used}


def log_usage_to_router(cost_usd: float, input_tokens: int, output_tokens: int, model: str, status: str) -> None:
    """Also write the call into the router's usage store so the SHARED monthly cap sees the spend. Best effort."""
    try:
        from src.ai import router as router_mod
        router_mod.default_router().usage.record_call(provider="anthropic", model=model, status=status, cost_usd=cost_usd,
                                                      input_tokens=input_tokens, output_tokens=output_tokens,
                                                      purpose="hound_full_rebuild")
    except Exception:  # noqa: BLE001
        pass
