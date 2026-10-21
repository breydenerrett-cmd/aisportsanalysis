"""The provider router: an ordered list of models, a hard dollar cap, strict JSON, and "no answer".

    router = Router()
    answer = router.ask(system, user, schema=DECISION_SCHEMA, validator=check_decision)
    answer.to_dict()  ->  {provider, model, latency_ms, cost_usd, output, ok, reason, attempts}

``output`` is a dict that passed the schema and the validator, or None. There is no third state and no
partial credit: a caller that gets ``ok == False`` passes.

PROVIDERS AND ORDER. ``config/ai_providers.json`` lists providers and the order to try them in. A provider
is usable only when its config flag ``enabled`` is true, its env key is present, an adapter exists for its
``kind``, and (if it is paid) the cap is above zero. Today the one entry is Claude Haiku 5.5. The router
loop is written for more than one (fallback order, per-provider daily caps, cooldowns) because the owner
asked for "a bunch of these models ready to go" and then, on 2026-10-20, to start with Haiku alone; a second
model is a config entry and one adapter class in ``ADAPTER_KINDS``. The free-tier and local adapters were
not written (they would be untested against any live service), and the config does not pretend otherwise.

THE HARD CAP. ``AI_PAID_CAP_USD`` (default 5) bounds the month's spend on paid providers, in UTC calendar
months. Before every paid call the router adds the WORST CASE the call could cost (the prompt's estimated
tokens at the input price plus ``max_tokens`` at the output price) to the month's recorded spend, and
refuses if the sum passes the cap. So the cap holds even for the call that would have crossed it. Spend is
read from the append-only usage store, which survives restarts and deploys; it is computed from the
``usage`` the API returns (a call whose usage is missing is charged its worst case, never zero). Paid calls
are serialised by a lock so two threads cannot both pass the check. The Anthropic console's own spend limit
(``docs/owner/AI_KEYS.md``) is the second wall behind this one.

FAILURES SKIP, NEVER FABRICATE. 429 and 402 put the provider on a cooldown (the response's Retry-After if
given, else ``quota_cooldown_minutes``); the console's "usage limits reached" error cools it for hours; 401
and 403 for ``auth_cooldown_minutes``; a timeout or a server error for ``error_cooldown_minutes``. The
loop then tries the next provider. A reply that is not valid JSON, fails the schema or fails the caller's
validator is retried ONCE on the next provider; a second invalid reply, or running out of providers, is
"no answer". Timeouts are capped at ``MAX_TIMEOUT_S`` (20 s) whatever the config says.

NO PERSON IN A PROMPT. ``check_prompt`` refuses to send a prompt that looks like it holds an email, a phone
number, a government id, a key or any configured secret. Hounds send game and market data and rule text only;
the guard is the net under that promise.

DEGRADING. When no provider is usable (capped, cooling down, down, no key) ``Router.status()`` says
``degraded: true`` and ``RESTING_LINE`` is the sentence a caller shows if it has one to show. The AI hounds
pass; Ask calls no model at all and keeps answering from the dog's own data.

Nothing here touches the network in a test: the Anthropic client comes from an injected factory.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from src.ai import schema as schema_mod
from src.ai.usage import UsageStore

logger = logging.getLogger("linehound.ai.router")

RESTING_LINE = "My AI brain is resting, here's what my rules say."
MAX_TIMEOUT_S = 20.0
DEFAULT_PAID_CAP_USD = 5.0
PAID_CAP_ENV = "AI_PAID_CAP_USD"
CHARS_PER_TOKEN_WORST = 3.0           # a prompt's token count is over-estimated, never under
CHARS_PER_TOKEN_TYPICAL = 4.0         # ...except when asking "is this prefix big enough to cache": there it
                                      # is under-estimated, so a prefix near the line is not cached
CACHE_WRITE_FACTOR = 1.25             # Anthropic prices: a cache write is 1.25x the input price, a read 0.1x
CACHE_READ_FACTOR = 0.10
BATCH_DISCOUNT = 0.5                  # the Message Batches API bills 50% of standard prices
SECRET_ENV_NAMES = ("APP_ADMIN_TOKEN", "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY",
                    "BALLDONTLIE_API_KEY", "ODDS_API_KEY", "THE_ODDS_API_KEY")
MIN_SECRET_LEN = 8

_REDACT_RE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,}|gsk_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})")
_PII_PATTERNS = (
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone number", re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")),
    ("government id", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("api key", _REDACT_RE),
)


def config_path() -> Path:
    from src import paths

    return Path(paths.repo_root()) / "config" / "ai_providers.json"


def load_config(path: Optional[os.PathLike] = None) -> dict:
    """The provider config, or an EMPTY one (no providers) if it cannot be read: a router with no
    config answers nothing, which is the safe failure. ``_error`` says why."""
    target = Path(path) if path else config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("providers"), dict):
            raise ValueError("no providers object")
        return data
    except (OSError, ValueError) as exc:
        logger.error("ai provider config unreadable (%s): %s", target, exc)
        return {"providers": {}, "order": [], "_error": f"{type(exc).__name__}: {exc}"}


def default_usage_path() -> str:
    """AI_USAGE_PATH, else a file BESIDE THE APP DATABASE (the Fly volume in production). Not ``evidence/``:
    that directory is baked into the image and a meter written there would reset at every deploy."""
    override = (os.environ.get("AI_USAGE_PATH") or "").strip()
    if override:
        return override
    from src.appstate import users as users_store

    return str(users_store.db_path().parent / "ai_usage_v1.jsonl")


def paid_cap_usd(env: Optional[Mapping] = None) -> float:
    """The month's hard cap in dollars: AI_PAID_CAP_USD, default 5. A value that is not a finite number
    falls back to the default (the owner's own ceiling); a negative one means 0, which turns paid calls off."""
    source = env if env is not None else os.environ
    raw = str(source.get(PAID_CAP_ENV) or "").strip()
    if not raw:
        return DEFAULT_PAID_CAP_USD
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using %s", PAID_CAP_ENV, raw, DEFAULT_PAID_CAP_USD)
        return DEFAULT_PAID_CAP_USD
    if not math.isfinite(value):
        return DEFAULT_PAID_CAP_USD
    return max(0.0, value)


# ---------------------------------------------------------------------------
# prompt guard
# ---------------------------------------------------------------------------

def secret_values(env: Mapping, specs: Sequence["ProviderSpec"] = ()) -> List[str]:
    names = list(SECRET_ENV_NAMES) + [s.env_key for s in specs if s.env_key]
    out = []
    for name in names:
        value = str(env.get(name) or "").strip()
        if len(value) >= MIN_SECRET_LEN:
            out.append(value)
    return out


def check_prompt(text: str, secrets: Sequence[str] = ()) -> List[str]:
    """Labels (never the matched text) of anything in ``text`` that must not leave the building."""
    found = [label for label, pattern in _PII_PATTERNS if pattern.search(text)]
    if any(s and s in text for s in secrets):
        found.append("configured secret")
    return found


def redact(text: Any, secrets: Sequence[str] = ()) -> str:
    out = str(text)
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    return _REDACT_RE.sub("[redacted]", out)


# ---------------------------------------------------------------------------
# specs and results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    id: str
    kind: str
    enabled: bool
    env_key: str
    model: str
    paid: bool = False
    effort: Optional[str] = None
    max_tokens: int = 400
    price_in_per_m: float = 0.0
    price_out_per_m: float = 0.0
    daily_cap: Optional[int] = None
    timeout_s: float = MAX_TIMEOUT_S
    cache_min_tokens: Optional[int] = None      # None = never mark the system prompt cacheable


def specs_from_config(config: Mapping) -> List[ProviderSpec]:
    defaults = config.get("defaults") or {}
    providers = config.get("providers") or {}
    ordered = [pid for pid in (config.get("order") or []) if pid in providers]
    ordered += [pid for pid in providers if pid not in ordered]
    out = []
    for pid in ordered:
        raw = providers[pid] or {}
        cap = raw.get("daily_cap")
        timeout = min(float(raw.get("timeout_s", defaults.get("timeout_s", MAX_TIMEOUT_S))), MAX_TIMEOUT_S)
        out.append(ProviderSpec(
            id=pid, kind=str(raw.get("kind") or pid), enabled=bool(raw.get("enabled", False)),
            env_key=str(raw.get("env_key") or ""), model=str(raw.get("model") or ""), paid=bool(raw.get("paid", False)),
            effort=raw.get("effort"), max_tokens=int(raw.get("max_tokens", 400)),
            price_in_per_m=float(raw.get("price_in_per_m", 0.0)), price_out_per_m=float(raw.get("price_out_per_m", 0.0)),
            daily_cap=(int(cap) if cap is not None else None), timeout_s=max(1.0, timeout),
            cache_min_tokens=(int(raw["cache_min_tokens"]) if raw.get("cache_min_tokens") else None)))
    return out


@dataclass
class AdapterResult:
    """One reply. ``input_tokens`` are the UNCACHED input tokens; cache writes and reads are priced
    differently (1.25x and 0.1x), so they are carried apart."""
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    refused: bool = False
    stop_reason: Optional[str] = None

    def total_input(self) -> Optional[int]:
        return None if self.input_tokens is None else self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


@dataclass
class BatchItem:
    """One request's outcome inside a finished batch. ``type``: succeeded | errored | canceled | expired."""
    custom_id: str
    type: str
    result: Optional[AdapterResult] = None
    error: str = ""


class AdapterError(Exception):
    """A provider call that did not produce a reply. ``kind``: quota | spend_limit | auth | timeout | error."""

    def __init__(self, kind: str, detail: str = "", retry_after_s: Optional[float] = None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
        self.retry_after_s = retry_after_s


@dataclass
class Attempt:
    provider: str
    model: Optional[str]
    status: str
    latency_ms: Optional[int] = None
    cost_usd: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "status": self.status,
                "latency_ms": self.latency_ms, "cost_usd": self.cost_usd, "detail": self.detail}


@dataclass
class Answer:
    provider: Optional[str]
    model: Optional[str]
    latency_ms: Optional[int]
    cost_usd: float
    output: Optional[dict]
    ok: bool
    reason: str = ""
    attempts: List[Attempt] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "latency_ms": self.latency_ms,
                "cost_usd": self.cost_usd, "output": self.output, "ok": self.ok, "reason": self.reason,
                "attempts": [a.to_dict() for a in self.attempts]}


# ---------------------------------------------------------------------------
# the Anthropic adapter
# ---------------------------------------------------------------------------

_SPEND_LIMIT_HINTS = ("usage limit", "credit balance", "spend limit", "billing")


def classify_exception(exc: BaseException) -> AdapterError:
    """Turn whatever the SDK raised into an ``AdapterError``, by status code and class name (so a fake
    exception in a test and the real ``anthropic`` errors take the same path, and the SDK is never imported
    just to be caught)."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    name = type(exc).__name__
    message = str(exc)
    retry_after: Optional[float] = None
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        raw = headers.get("retry-after") if headers is not None else None
        retry_after = float(raw) if raw is not None else None
    except (TypeError, ValueError, AttributeError):
        retry_after = None
    lowered = message.lower()
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timeout" in name.lower():
        return AdapterError("timeout", name)
    if status in (429, 402) or "ratelimit" in name.lower():
        return AdapterError("quota", f"HTTP {status or 429}", retry_after)
    if status == 400 and any(h in lowered for h in _SPEND_LIMIT_HINTS):
        return AdapterError("spend_limit", "the account's own usage limit was reached")
    if status in (401, 403) or "authentication" in name.lower() or "permissiondenied" in name.lower():
        return AdapterError("auth", f"HTTP {status}")
    return AdapterError("error", f"{name}{f' HTTP {status}' if status else ''}")


def _int_or_none(value) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def result_from_message(msg: Any) -> AdapterResult:
    """An ``AdapterResult`` from an SDK message (or a batch result's message)."""
    text = "".join(getattr(b, "text", "") or "" for b in (getattr(msg, "content", None) or ())
                   if getattr(b, "type", None) == "text")
    usage = getattr(msg, "usage", None)
    tokens_in = tokens_out = None
    write = read = 0
    if usage is not None:
        tokens_in = _int_or_none(getattr(usage, "input_tokens", None))
        tokens_out = _int_or_none(getattr(usage, "output_tokens", None))
        write = _int_or_none(getattr(usage, "cache_creation_input_tokens", None)) or 0
        read = _int_or_none(getattr(usage, "cache_read_input_tokens", None)) or 0
    stop = getattr(msg, "stop_reason", None)
    return AdapterResult(text=text, input_tokens=tokens_in, output_tokens=tokens_out, cache_write_tokens=write,
                         cache_read_tokens=read, refused=(stop == "refusal"), stop_reason=stop)


class AnthropicAdapter:
    """Claude through the official ``anthropic`` SDK (imported lazily: the CI image may not have it).

    ``client_factory(api_key, timeout_s)`` returns an object with ``.messages.create`` (and
    ``.messages.batches`` for batches); tests pass a fake, production passes nothing and the SDK's own client
    is built with retries OFF (the router owns retry and cooldown policy, and an SDK retry would double the
    20 s timeout and could double the spend).

    CACHING. When the router says the system prompt is big enough to qualify, the system text goes in as a
    block carrying ``cache_control: ephemeral``, so the stable prefix ends at the breakpoint and the volatile
    user message follows it. (A top-level ``cache_control`` would put the breakpoint on the LAST block, which
    for a stable-system, volatile-user request is the volatile part: it would pay the 1.25x write for text
    that never repeats.)"""

    def __init__(self, client_factory: Optional[Callable[[str, float], Any]] = None):
        self._factory = client_factory
        self._clients: Dict[tuple, Any] = {}

    def _client(self, api_key: str, timeout_s: float) -> Any:
        key = (api_key, timeout_s)
        if key not in self._clients:
            if self._factory is not None:
                self._clients[key] = self._factory(api_key, timeout_s)
            else:
                try:
                    import anthropic          # noqa: PLC0415 -- lazy by design
                except ImportError as exc:
                    raise AdapterError("error", "the anthropic package is not installed") from exc
                self._clients[key] = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        return self._clients[key]

    @staticmethod
    def params(spec: ProviderSpec, model: str, system: str, user: str, max_tokens: int, cache_system: bool) -> dict:
        out: dict = {"model": model, "max_tokens": max_tokens,
                     "system": ([{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                                if cache_system else system),
                     "messages": [{"role": "user", "content": user}]}
        if spec.effort:
            out["output_config"] = {"effort": spec.effort}
        return out

    def complete(self, spec: ProviderSpec, model: str, system: str, user: str, *, api_key: str,
                 timeout_s: float, max_tokens: int, cache_system: bool = False) -> AdapterResult:
        client = self._client(api_key, timeout_s)
        try:
            resp = client.messages.create(**self.params(spec, model, system, user, max_tokens, cache_system))
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 -- classified, never swallowed
            raise classify_exception(exc) from exc
        return result_from_message(resp)

    # -- the Message Batches API (50% of standard prices; not for anything with a deadline) ----------------

    def submit_batch(self, spec: ProviderSpec, model: str, jobs: Sequence[dict], *, api_key: str,
                     timeout_s: float, cache_system: bool = False) -> str:
        """``jobs``: dicts with custom_id, system, user, max_tokens. Returns the batch id."""
        client = self._client(api_key, timeout_s)
        requests = [{"custom_id": j["custom_id"],
                     "params": self.params(spec, model, j["system"], j["user"], j["max_tokens"], cache_system)}
                    for j in jobs]
        try:
            batch = client.messages.batches.create(requests=requests)
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise classify_exception(exc) from exc
        return str(batch.id)

    def batch_status(self, batch_id: str, *, api_key: str, timeout_s: float) -> str:
        """The SDK's ``processing_status``: in_progress | canceling | ended."""
        try:
            return str(self._client(api_key, timeout_s).messages.batches.retrieve(batch_id).processing_status)
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise classify_exception(exc) from exc

    def batch_results(self, batch_id: str, *, api_key: str, timeout_s: float) -> List[BatchItem]:
        """Every result of an ENDED batch, as items that each carry their own ``custom_id``."""
        try:
            entries = list(self._client(api_key, timeout_s).messages.batches.results(batch_id))
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise classify_exception(exc) from exc
        items = []
        for entry in entries:
            outcome = getattr(entry, "result", None)
            kind = str(getattr(outcome, "type", "errored"))
            if kind == "succeeded":
                items.append(BatchItem(str(entry.custom_id), kind, result_from_message(outcome.message)))
            else:
                err = getattr(getattr(outcome, "error", None), "type", "") or kind
                items.append(BatchItem(str(entry.custom_id), kind, None, str(err)))
        return items


# kind -> adapter class. The one place a second provider is plugged in.
ADAPTER_KINDS: Dict[str, Callable[[], Any]] = {"anthropic": AnthropicAdapter}


# ---------------------------------------------------------------------------
# batches (non-urgent jobs at half price)
# ---------------------------------------------------------------------------

_CUSTOM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class BatchJob:
    """One request in a batch. ``custom_id`` is how its result is found again: results come back in ANY
    order, so nothing downstream may ever pair them by position."""
    custom_id: str
    system: str
    user: str
    schema: Optional[dict] = None          # None: the reply's text is kept as {"text": ...}
    validator: Optional[Callable[[dict], List[str]]] = None
    max_tokens: Optional[int] = None


@dataclass
class BatchSubmission:
    ok: bool
    batch_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    reserved_usd: float = 0.0
    n_requests: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class BatchOutcome:
    done: bool                              # False while the provider is still working on the batch
    status: str
    results: Dict[str, Answer] = field(default_factory=dict)       # keyed by custom_id, never by position
    cost_usd: float = 0.0                   # at the batch price (50%)
    already_billed: bool = False            # this batch's cost was recorded by an earlier read
    reason: str = ""


# ---------------------------------------------------------------------------
# the router
# ---------------------------------------------------------------------------

class Router:
    def __init__(self, config: Optional[Mapping] = None, *, env: Optional[Mapping] = None,
                 adapters: Optional[Mapping[str, Any]] = None, usage: Optional[UsageStore] = None,
                 usage_path: Optional[os.PathLike] = None, clock: Optional[Callable[[], datetime]] = None):
        self.config = dict(config) if config is not None else load_config()
        self.env = env if env is not None else os.environ
        self.specs = specs_from_config(self.config)
        self.defaults = self.config.get("defaults") or {}
        self.adapters = dict(adapters) if adapters is not None else {}
        self.usage = usage or UsageStore(usage_path or default_usage_path(), clock=clock)
        self._paid_lock = threading.Lock()

    # -- what is usable -------------------------------------------------------

    def _adapter(self, spec: ProviderSpec) -> Optional[Any]:
        if spec.kind not in self.adapters:
            factory = ADAPTER_KINDS.get(spec.kind)
            if factory is None:
                return None
            self.adapters[spec.kind] = factory()
        return self.adapters[spec.kind]

    def _api_key(self, spec: ProviderSpec) -> str:
        return str(self.env.get(spec.env_key) or "").strip() if spec.env_key else ""

    def disabled_reason(self, spec: ProviderSpec) -> Optional[str]:
        """Why a provider can never be used right now (config or environment), or None if it is enabled."""
        if not spec.enabled:
            return "switched off in config/ai_providers.json"
        if not self._api_key(spec):
            return f"no {spec.env_key} set"
        if self._adapter(spec) is None:
            return f"no adapter for kind {spec.kind!r}"
        if spec.paid and paid_cap_usd(self.env) <= 0:
            return f"{PAID_CAP_ENV} is 0"
        return None

    def enabled_providers(self) -> List[ProviderSpec]:
        return [s for s in self.specs if self.disabled_reason(s) is None]

    def paid_spend(self) -> float:
        """The month's paid spend that counts against the cap: recorded calls (batch calls at their 50%
        price) plus the money reserved for batches submitted and not yet read."""
        return round(sum(self.usage.month_spend(s.id) + self.usage.reserved(s.id) for s in self.specs if s.paid), 8)

    def wants_cache(self, spec: ProviderSpec, system: str) -> bool:
        """Cache the system prompt only when it is large enough to qualify (``cache_min_tokens``, set above the
        model's real minimum), estimated from characters with the generous divisor."""
        return bool(spec.cache_min_tokens) and len(system) / CHARS_PER_TOKEN_TYPICAL >= spec.cache_min_tokens

    def estimate_cost(self, spec: ProviderSpec, system: str, user: str, max_tokens: int, *,
                      cache_system: bool = False, discount: float = 1.0) -> float:
        """The most a call could cost: the prompt's tokens (over-estimated; the system part at the cache-write
        price when it is being cached) plus every output token ``max_tokens`` allows, times the batch discount."""
        user_tokens = math.ceil(len(user) / CHARS_PER_TOKEN_WORST)
        system_tokens = math.ceil(len(system) / CHARS_PER_TOKEN_WORST)
        in_cost = (user_tokens + system_tokens * (CACHE_WRITE_FACTOR if cache_system else 1.0)) * spec.price_in_per_m / 1e6
        return (in_cost + max_tokens * spec.price_out_per_m / 1e6) * discount

    def skip_reason(self, spec: ProviderSpec, est_cost: float = 0.0) -> Optional[str]:
        """Why this provider is not being called right now (a cap, a cooldown), or None if it can be."""
        reason = self.disabled_reason(spec)
        if reason:
            return reason
        cooling = self.usage.cooldown(spec.id)
        if cooling is not None:
            return f"cooling down until {cooling[0].strftime('%H:%M')}Z ({cooling[1]})"
        if spec.daily_cap is not None and self.usage.calls_today(spec.id) >= spec.daily_cap:
            return f"daily cap of {spec.daily_cap} calls reached"
        if spec.paid:
            cap = paid_cap_usd(self.env)
            if self.paid_spend() + est_cost > cap:
                return f"monthly paid cap of ${cap:.2f} reached"
        return None

    def available(self) -> bool:
        """Could a call go out right now? (The cheapest question; used to skip a pass that cannot ask.)"""
        return any(self.skip_reason(s, self.estimate_cost(s, "", "", s.max_tokens)) is None for s in self.specs)

    def degraded(self) -> bool:
        return not self.available()

    def status(self) -> dict:
        """Everything the admin panel shows about the router. No secret appears in it."""
        cap = paid_cap_usd(self.env)
        spend = self.paid_spend()
        providers = []
        for s in self.specs:
            off = self.disabled_reason(s)
            est = self.estimate_cost(s, "", "", s.max_tokens)
            cooling = self.usage.cooldown(s.id)
            skip = self.skip_reason(s, est)
            providers.append({
                "id": s.id, "kind": s.kind, "model": s.model, "paid": s.paid, "enabled": off is None,
                "disabled_reason": off, "usable_now": skip is None, "blocked_reason": skip if off is None else None,
                "calls_today": self.usage.calls_today(s.id), "daily_cap": s.daily_cap,
                "status_today": self.usage.status_today(s.id),
                "cooldown_until": cooling[0].strftime("%Y-%m-%dT%H:%M:%SZ") if cooling else None,
                "month_spend_usd": self.usage.month_spend(s.id), "last_ok": self.usage.last_ok(s.id)})
        return {"providers": providers, "enabled": [p["id"] for p in providers if p["enabled"]],
                "degraded": self.degraded(), "resting_line": RESTING_LINE,
                "batches_open": self.usage.open_batches(),
                "paid": {"cap_usd": cap, "month": self.usage.month(), "spend_usd": spend,
                         "remaining_usd": round(max(0.0, cap - spend), 8), "cap_env": PAID_CAP_ENV,
                         "cap_reached": bool(any(s.paid for s in self.specs) and spend >= cap)},
                "last_errors": self.usage.recent_errors(10), "config_error": self.config.get("_error")}

    # -- asking ---------------------------------------------------------------

    def _cooldown_minutes(self, kind: str, error: AdapterError) -> float:
        d = self.defaults
        if error.retry_after_s:
            return min(max(error.retry_after_s / 60.0, 1.0), 360.0)
        return {"quota": float(d.get("quota_cooldown_minutes", 30)),
                "spend_limit": float(d.get("spend_limit_cooldown_minutes", 360)),
                "auth": float(d.get("auth_cooldown_minutes", 120))}.get(kind, float(d.get("error_cooldown_minutes", 3)))

    def _cost(self, spec: ProviderSpec, result: AdapterResult, est_cost: float, discount: float = 1.0) -> float:
        if result.input_tokens is None or result.output_tokens is None:
            return round(est_cost, 8)                      # usage missing: charge the worst case, never zero
        price_in = spec.price_in_per_m / 1e6
        cost = (result.input_tokens * price_in
                + result.cache_write_tokens * price_in * CACHE_WRITE_FACTOR
                + result.cache_read_tokens * price_in * CACHE_READ_FACTOR
                + result.output_tokens * spec.price_out_per_m / 1e6)
        return round(cost * discount, 8)

    def _no_answer(self, reason: str, attempts: List[Attempt], started: float) -> Answer:
        spent = round(sum(a.cost_usd for a in attempts), 8)
        return Answer(provider=None, model=None, latency_ms=int((time.monotonic() - started) * 1000), cost_usd=spent,
                      output=None, ok=False, reason=reason, attempts=attempts)

    def ask(self, system: str, user: str, *, schema: dict, validator: Optional[Callable[[dict], List[str]]] = None,
            providers: Optional[Sequence[str]] = None, purpose: str = "", max_tokens: Optional[int] = None) -> Answer:
        started = time.monotonic()
        attempts: List[Attempt] = []
        secrets = secret_values(self.env, self.specs)
        leaks = check_prompt(system + "\n" + user, secrets)
        if leaks:
            logger.error("ai prompt refused by the PII guard: %s", ", ".join(leaks))
            return self._no_answer(f"prompt refused: it looks like it contains a {', '.join(leaks)}", attempts, started)
        wanted = list(providers) if providers is not None else None
        candidates = [s for s in self.specs if wanted is None or s.id in wanted]
        if wanted is not None:
            candidates.sort(key=lambda s: wanted.index(s.id))
        max_attempts = int(self.defaults.get("max_attempts", 3))
        invalid = 0
        tried = 0
        for spec in candidates:
            if tried >= max_attempts:
                break
            budget = int(max_tokens or spec.max_tokens)
            cache = self.wants_cache(spec, system)
            est = self.estimate_cost(spec, system, user, budget, cache_system=cache) if spec.paid else 0.0
            if spec.paid:
                self._paid_lock.acquire()
            try:
                skip = self.skip_reason(spec, est)
                if skip:
                    attempts.append(Attempt(spec.id, spec.model or None, "skipped", detail=skip))
                    continue
                tried += 1
                attempt, answer = self._call(spec, system, user, schema, validator, budget, est, purpose, secrets, cache)
            finally:
                if spec.paid:
                    self._paid_lock.release()
            attempts.append(attempt)
            if answer is not None:
                answer.attempts = attempts
                answer.cost_usd = round(sum(a.cost_usd for a in attempts), 8)
                return answer
            if attempt.status == "invalid":
                invalid += 1
                if invalid >= 2:
                    return self._no_answer("two invalid replies in a row", attempts, started)
        reasons = [f"{a.provider}: {a.status}{' - ' + a.detail if a.detail else ''}" for a in attempts]
        why = "; ".join(reasons) if reasons else "no provider is configured"
        return self._no_answer(f"no answer ({why})", attempts, started)

    def _call(self, spec: ProviderSpec, system: str, user: str, schema: dict,
              validator: Optional[Callable[[dict], List[str]]], budget: int, est: float, purpose: str,
              secrets: Sequence[str], cache: bool = False):
        """One provider call, fully accounted. Returns ``(Attempt, Answer or None)``."""
        adapter = self._adapter(spec)
        began = time.monotonic()
        try:
            result = adapter.complete(spec, spec.model, system, user, api_key=self._api_key(spec),
                                      timeout_s=spec.timeout_s, max_tokens=budget, cache_system=cache)
        except AdapterError as err:
            return self._failed(spec, err, began, purpose, secrets), None
        except Exception as exc:  # noqa: BLE001 -- an adapter bug must still be accounted, not raised into a pass
            return self._failed(spec, classify_exception(exc), began, purpose, secrets), None
        latency = int((time.monotonic() - began) * 1000)
        cost = self._cost(spec, result, est)
        if result.refused:
            status, detail, output = "refused", "the model declined to answer", None
        else:
            obj, why = schema_mod.extract_json_object(result.text)
            problems = [why] if why else schema_mod.validate(obj, schema)
            if not problems and validator is not None:
                problems = list(validator(obj))
            status = "ok" if not problems else "invalid"
            detail = "; ".join(problems)[:300]
            output = obj if not problems else None
        self.usage.record_call(provider=spec.id, model=spec.model, status=status, latency_ms=latency, cost_usd=cost,
                               input_tokens=result.total_input(), output_tokens=result.output_tokens,
                               error=(redact(detail, secrets) if status != "ok" else None), purpose=purpose)
        attempt = Attempt(spec.id, spec.model, status, latency, cost, "" if status == "ok" else detail)
        if status != "ok":
            return attempt, None
        return attempt, Answer(provider=spec.id, model=spec.model, latency_ms=latency, cost_usd=cost, output=output,
                               ok=True, reason="")

    def _failed(self, spec: ProviderSpec, err: AdapterError, began: float, purpose: str, secrets: Sequence[str]) -> Attempt:
        latency = int((time.monotonic() - began) * 1000)
        detail = redact(err.detail, secrets)
        status = "quota" if err.kind == "spend_limit" else err.kind
        self.usage.record_call(provider=spec.id, model=spec.model, status=status, latency_ms=latency, cost_usd=0.0,
                               error=detail, purpose=purpose)
        minutes = self._cooldown_minutes(err.kind, err)
        self.usage.record_cooldown(spec.id, self.usage.now() + timedelta(minutes=minutes), f"{err.kind}: {detail}")
        return Attempt(spec.id, spec.model, status, latency, 0.0, detail)


    # -- batches --------------------------------------------------------------

    def _batch_spec(self, provider: str) -> Optional[ProviderSpec]:
        for s in self.specs:
            if s.id == provider:
                return s
        return None

    def submit_batch(self, jobs: Sequence[BatchJob], *, provider: str = "anthropic", purpose: str = "") -> BatchSubmission:
        """Send non-urgent jobs through the Message Batches API at 50% of the standard price.

        For nightly recaps, hype lines and other content; NEVER for a hound's pick before its lock (a batch can
        take up to 24 hours) and never for Ask. The whole batch's worst case, at the batch price, is RESERVED
        against the monthly cap now; a batch that would cross it is refused whole. The daily call cap does not
        apply (it protects free tiers; the dollar cap is the wall here)."""
        spec = self._batch_spec(provider)
        if spec is None:
            return BatchSubmission(False, reason=f"unknown provider {provider!r}")
        if not jobs:
            return BatchSubmission(False, provider=provider, reason="no jobs")
        ids = [j.custom_id for j in jobs]
        if len(set(ids)) != len(ids) or any(not _CUSTOM_ID_RE.match(str(i)) for i in ids):
            return BatchSubmission(False, provider=provider,
                                   reason="custom_ids must be unique, 1-64 characters of letters, digits, - and _")
        adapter = self._adapter(spec)
        if adapter is None or not hasattr(adapter, "submit_batch"):
            return BatchSubmission(False, provider=provider, reason=f"{provider} has no batch support")
        secrets = secret_values(self.env, self.specs)
        for j in jobs:
            leaks = check_prompt(j.system + "\n" + j.user, secrets)
            if leaks:
                return BatchSubmission(False, provider=provider,
                                       reason=f"job {j.custom_id} refused: it looks like it contains a {', '.join(leaks)}")
        cache = any(self.wants_cache(spec, j.system) for j in jobs)
        sized = [{"custom_id": j.custom_id, "system": j.system, "user": j.user,
                  "max_tokens": int(j.max_tokens or spec.max_tokens)} for j in jobs]
        reserve = round(sum(self.estimate_cost(spec, j["system"], j["user"], j["max_tokens"], cache_system=cache,
                                               discount=BATCH_DISCOUNT) for j in sized), 8)
        with self._paid_lock:
            reason = self.disabled_reason(spec)
            cooling = self.usage.cooldown(spec.id)
            if reason is None and cooling is not None:
                reason = f"cooling down until {cooling[0].strftime('%H:%M')}Z ({cooling[1]})"
            if reason is None and spec.paid and self.paid_spend() + reserve > paid_cap_usd(self.env):
                reason = (f"monthly paid cap of ${paid_cap_usd(self.env):.2f} would be crossed "
                          f"(batch worst case ${reserve:.4f})")
            if reason:
                return BatchSubmission(False, provider=provider, model=spec.model, n_requests=len(jobs), reason=reason)
            began = time.monotonic()
            try:
                batch_id = adapter.submit_batch(spec, spec.model, sized, api_key=self._api_key(spec),
                                                timeout_s=spec.timeout_s, cache_system=cache)
            except Exception as exc:  # noqa: BLE001 -- an adapter error and an SDK error are accounted alike
                err = exc if isinstance(exc, AdapterError) else classify_exception(exc)
                self._failed(spec, err, began, f"batch:{purpose}", secrets)
                return BatchSubmission(False, provider=provider, model=spec.model, n_requests=len(jobs),
                                       reason=f"{err.kind}: {redact(err.detail, secrets)}")
            self.usage.record_batch_submit(batch_id=batch_id, provider=spec.id, model=spec.model, reserved_usd=reserve,
                                           n_requests=len(jobs), purpose=purpose)
        return BatchSubmission(True, batch_id=batch_id, provider=provider, model=spec.model, reserved_usd=reserve,
                               n_requests=len(jobs))

    def collect_batch(self, batch_id: str, jobs: Optional[Sequence[BatchJob]] = None, *, provider: str = "anthropic",
                      purpose: str = "") -> BatchOutcome:
        """Poll a batch; when it has ended, return its results KEYED BY custom_id and bill them at 50%.

        ``jobs`` (the same ``BatchJob`` objects, by id) supply each result's schema and validator; without
        them a reply is kept as ``{"text": ...}``. The cost is recorded once, however often this is called:
        a second read returns the results again with ``already_billed`` set and writes nothing."""
        spec = self._batch_spec(provider)
        adapter = self._adapter(spec) if spec is not None else None
        if spec is None or adapter is None or not hasattr(adapter, "batch_results"):
            return BatchOutcome(False, "unknown", reason=f"{provider} has no batch support")
        secrets = secret_values(self.env, self.specs)
        key, timeout = self._api_key(spec), spec.timeout_s
        try:
            status = adapter.batch_status(batch_id, api_key=key, timeout_s=timeout)
            if status != "ended":
                return BatchOutcome(False, status)
            items = adapter.batch_results(batch_id, api_key=key, timeout_s=timeout)
        except Exception as exc:  # noqa: BLE001
            err = exc if isinstance(exc, AdapterError) else classify_exception(exc)
            return BatchOutcome(False, "error", reason=f"{err.kind}: {redact(err.detail, secrets)}")
        by_job = {j.custom_id: j for j in (jobs or ())}
        billed_before = self.usage.batch_done(batch_id)
        results: Dict[str, Answer] = {}
        total = 0.0
        for item in items:
            job = by_job.get(item.custom_id)
            tokens_in = tokens_out = None
            if item.type != "succeeded" or item.result is None:
                results[item.custom_id] = Answer(None, None, None, 0.0, None, False,
                                                 f"batch result {item.type}: {item.error}".strip())
                row_status, cost = ("timeout" if item.type == "expired" else "error"), 0.0
            else:
                res = item.result
                worst = self.estimate_cost(spec, (job.system if job else ""), (job.user if job else ""),
                                           int((job.max_tokens if job else None) or spec.max_tokens),
                                           discount=BATCH_DISCOUNT)
                cost = self._cost(spec, res, worst, discount=BATCH_DISCOUNT)
                tokens_in, tokens_out = res.total_input(), res.output_tokens
                detail, output = "", None
                if res.refused:
                    row_status, detail = "refused", "the model declined to answer"
                elif job is not None and job.schema is not None:
                    obj, why = schema_mod.extract_json_object(res.text)
                    problems = [why] if why else schema_mod.validate(obj, job.schema)
                    if not problems and job.validator is not None:
                        problems = list(job.validator(obj))
                    if problems:
                        row_status, detail = "invalid", "; ".join(problems)[:300]
                    else:
                        row_status, output = "ok", obj
                else:
                    row_status, output = "ok", {"text": res.text}
                results[item.custom_id] = Answer(spec.id, spec.model, None, cost, output, row_status == "ok", detail)
            total += cost
            if not billed_before:
                self.usage.record_call(
                    provider=spec.id, model=spec.model, status=row_status, latency_ms=None, cost_usd=cost,
                    input_tokens=tokens_in, output_tokens=tokens_out,
                    error=(redact(results[item.custom_id].reason, secrets) if row_status != "ok" else None),
                    purpose=f"batch:{batch_id}" + (f":{purpose}" if purpose else ""))
        for job_id in by_job:
            if job_id not in results:
                results[job_id] = Answer(None, None, None, 0.0, None, False, "no result came back for this request")
        if not billed_before:
            self.usage.record_batch_done(batch_id=batch_id, provider=spec.id, status=status, actual_usd=total)
        return BatchOutcome(True, status, results, round(total, 8), already_billed=billed_before)


    def wait_for_batch(self, batch_id: str, jobs: Optional[Sequence[BatchJob]] = None, *, provider: str = "anthropic",
                       purpose: str = "", poll_seconds: float = 30.0, max_wait_seconds: float = 3600.0,
                       sleep: Callable[[float], None] = time.sleep) -> BatchOutcome:
        """Poll ``collect_batch`` until the batch has ended or ``max_wait_seconds`` is up. A batch that is still
        running at the deadline comes back ``done=False`` (read it again later; nothing is lost or billed twice);
        so does one whose status could not be read (``status == "error"``), since a retry is the caller's call."""
        waited = 0.0
        while True:
            outcome = self.collect_batch(batch_id, jobs, provider=provider, purpose=purpose)
            if outcome.done or outcome.status in ("error", "unknown") or waited >= max_wait_seconds:
                return outcome
            sleep(poll_seconds)
            waited += poll_seconds

_default_lock = threading.Lock()
_default: Optional[Router] = None


def default_router() -> Router:
    """The process's one router (its usage store reads one file once and then tails it)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Router()
        return _default


def reset_default_router() -> None:
    global _default
    with _default_lock:
        _default = None
