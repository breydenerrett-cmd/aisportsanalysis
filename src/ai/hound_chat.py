"""The model half of "talk to your hound" (owner request 2026-10-28): Claude Haiku 5.5 only, through the official ``anthropic`` SDK.

WHERE THIS SITS. ``src/hounds/interact`` is pinned by a test to import no model client, so the Ask tab's computed answers stay
computed. The chat is a SECOND thing next to it: ``src/hounds/chat`` holds everything about the member and the hound (who may talk,
what the hound is allowed to know, the proposal checks, the saved history) and calls THIS module for the one thing that needs a
model, a turn of conversation. This file knows nothing about hounds: it takes a system prompt, some tools, a history and a
member's line, runs the tool loop, and accounts for every cent.

THE CALL. One ``messages.create`` per round, model ``claude-haiku-5-5``, ``thinking: {"type": "adaptive"}`` with ``effort: low`` (a
chat answer is a few sentences; Haiku 5.5 thinks only when it wants to), no ``budget_tokens``, no sampling parameters and no prefill
(each is a 400 on this model). The system prompt goes in as two blocks: the STABLE one (instructions, the rule catalog) carries
``cache_control`` so every hound and every member shares one cached prefix, and the volatile one (this hound, its record) follows
it. Tools are client tools with ``strict: true`` schemas. A turn is the member's line plus at most ``MAX_ROUNDS`` rounds: the answer,
up to two corrections of a refused edit, and the closing words.

THE MONEY. Prices are ``claude-haiku-5-5``'s ($0.10 in / $0.50 out per million tokens, the claude-api price table and
``config/ai_providers.json``); a cache write is 1.25x the input price and a read 0.1x, the router's own factors. Before every round
``Spend.check`` adds the WORST CASE the round could cost to what the month has spent and refuses past the router's shared cap
(``AI_PAID_CAP_USD``), through ``Router.skip_reason`` itself, so the cap, the cooldown after a 429 and the daily call ceiling are the
very ones the AI hounds live under. After every round ``Spend.record`` writes the real cost (the API's own ``usage``, never a guess;
missing usage is charged its worst case) into the router's append-only usage store, so the shared meter sees it.

NO SECRETS. The key is read by NAME and handed to the SDK. It is never logged, returned or put in an error: a failure is reported
by its class name and its status code only.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, List, Mapping, Optional, Sequence

from src.ai import router as router_mod
from src.ai import sdk_client

logger = logging.getLogger("linehound.ai.hound_chat")

MODEL = "claude-haiku-5-5"                  # owner ruling 2026-10-28: Haiku only. There is no second model to fall back to here.
EFFORT = "low"
MAX_TOKENS = 2000                           # thinking plus a few sentences plus a tool call; a backstop, not a target
MAX_ROUNDS = 4                              # the answer, two corrections of a refused edit, and the closing words
TIMEOUT_S = 45.0
KEY_ENV = "ANTHROPIC_API_KEY"
PURPOSE = "hound_chat"
PROVIDER = "anthropic"                      # the router's provider id: spend only counts against the shared cap under it

PRICE_IN_PER_M = 0.10
PRICE_OUT_PER_M = 0.50
LONG_PROMPT_TOKENS = 100_000                # above this the API bills its long-prompt rates
PRICE_IN_LONG_PER_M = 0.50
PRICE_OUT_LONG_PER_M = 2.50
CHARS_PER_TOKEN_WORST = 3.0                 # the estimate over-counts, never under (the router's stance)

REASON_RESTING = "resting"                  # TurnResult.reason values the caller maps to words
REASON_REFUSED = "refusal"
REASON_TOO_LONG = "max_tokens"
REASON_FAILED = "call_failed"
REASON_NO_CLIENT = "no_client"


def api_key(env: Optional[Mapping] = None) -> Optional[str]:
    """The key, or None. Read by NAME; the value is never logged or returned to a page."""
    value = str((env if env is not None else os.environ).get(KEY_ENV) or "").strip()
    return value or None


class Resting(Exception):
    """A round was not made because the shared meter says no (the cap, a cooldown, the daily call ceiling, no key)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# money
# ---------------------------------------------------------------------------

def prices(input_tokens: int) -> tuple:
    return ((PRICE_IN_LONG_PER_M, PRICE_OUT_LONG_PER_M) if input_tokens > LONG_PROMPT_TOKENS
            else (PRICE_IN_PER_M, PRICE_OUT_PER_M))


def text_chars(system: Any, tools: Sequence, messages: Sequence) -> int:
    """How many characters a request carries (a content list counts every text and tool block, a thinking block counts as nothing:
    the API drops it from the count of later turns)."""
    def size(value: Any) -> int:
        if isinstance(value, str):
            return len(value)
        if isinstance(value, Mapping):
            return sum(size(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return sum(size(v) for v in value)
        text = getattr(value, "text", None)
        if isinstance(text, str):
            return len(text)
        data = getattr(value, "input", None)
        return size(data) if isinstance(data, (Mapping, list)) else 0
    return size(system) + size(list(tools)) + sum(size(m.get("content")) for m in messages)


def worst_case_cost(chars: int, max_tokens: int = MAX_TOKENS, carried_rounds: int = 0) -> float:
    """The most one round could cost: every input character as a token-and-a-third at the cache-WRITE price, every output token the
    round may write, and (for a later round of a tool loop) every thinking token the earlier rounds may have written, which the
    request carries back in but whose text the API hides from the character count."""
    tokens_in = math.ceil(chars / CHARS_PER_TOKEN_WORST) + carried_rounds * max_tokens
    p_in, p_out = prices(tokens_in)
    return round((tokens_in * p_in * router_mod.CACHE_WRITE_FACTOR + max_tokens * p_out) / 1e6, 8)


@dataclass
class Usage:
    """Tokens a turn used, summed over its rounds. ``input_tokens`` are the UNCACHED ones (the API reports cache traffic apart)."""
    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0

    def total_input(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


def _count(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def message_cost(message: Any, worst: float) -> tuple:
    """``(cost, input_tokens, cache_write, cache_read, output_tokens)`` of one reply from its own ``usage``. Without usage the
    round is charged its worst case, never zero."""
    usage = getattr(message, "usage", None)
    tin = _count(getattr(usage, "input_tokens", None)) if usage is not None else None
    tout = _count(getattr(usage, "output_tokens", None)) if usage is not None else None
    if tin is None or tout is None:
        return worst, 0, 0, 0, 0
    write = _count(getattr(usage, "cache_creation_input_tokens", None)) or 0
    read = _count(getattr(usage, "cache_read_input_tokens", None)) or 0
    p_in, p_out = prices(tin + write + read)
    cost = (tin * p_in + write * p_in * router_mod.CACHE_WRITE_FACTOR + read * p_in * router_mod.CACHE_READ_FACTOR + tout * p_out) / 1e6
    return round(cost, 8), tin, write, read, tout


class Spend:
    """The shared meter for chat rounds. One per turn; ``router`` is injectable (tests), production uses the process's own."""

    def __init__(self, router: Any = None, extra_check: Optional[Callable[[float], Optional[str]]] = None):
        self._router = router
        self._extra = extra_check          # the chat's own monthly ceiling, owned by src/hounds/chat

    @property
    def router(self):
        if self._router is None:
            self._router = router_mod.default_router()
        return self._router

    def _spec(self):
        for spec in self.router.specs:
            if spec.kind == "anthropic" and spec.paid:
                return spec
        return None

    def check(self, worst: float) -> None:
        """Raise ``Resting`` when this round may not be made: the router's own verdict (no key, switched off, cap, cooldown, daily
        calls) first, then the chat's extra ceiling."""
        spec = self._spec()
        if spec is None:
            raise Resting("the AI provider is not configured")
        why = self.router.skip_reason(spec, worst)
        if why:
            raise Resting(why)
        if self._extra is not None:
            why = self._extra(worst)
            if why:
                raise Resting(why)

    def record(self, status: str, cost: float, tokens_in: int, tokens_out: int, latency_ms: int, error: Optional[str] = None) -> None:
        try:
            self.router.usage.record_call(provider=PROVIDER, model=MODEL, status=status, latency_ms=latency_ms, cost_usd=cost,
                                          input_tokens=tokens_in, output_tokens=tokens_out, error=error, purpose=PURPOSE)
        except Exception:  # noqa: BLE001 -- the meter failing must not lose the member's answer
            logger.warning("hound chat could not write its usage row")

    def cool_down(self, error: "router_mod.AdapterError") -> None:
        """A 429, a 401 or a timeout cools the provider for everyone, exactly as the router does for its own calls."""
        try:
            minutes = self.router._cooldown_minutes(error.kind, error)          # noqa: SLF001 -- same package, one policy
            self.router.usage.record_cooldown(PROVIDER, self.router.usage.now() + timedelta(minutes=minutes), f"{error.kind}: hound chat")
        except Exception:  # noqa: BLE001
            logger.warning("hound chat could not write its cooldown")


# ---------------------------------------------------------------------------
# the turn
# ---------------------------------------------------------------------------

@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False


@dataclass
class TurnResult:
    ok: bool
    text: str = ""
    reason: str = ""
    usage: Usage = field(default_factory=Usage)
    stop_reason: Optional[str] = None
    rounds: int = 0


OnTool = Callable[[str, Mapping], ToolOutcome]


def _blocks(message: Any) -> list:
    return list(getattr(message, "content", None) or ())


def reply_text(message: Any) -> str:
    return "".join(getattr(b, "text", "") or "" for b in _blocks(message) if getattr(b, "type", None) == "text").strip()


def default_client(key: str):
    """The SDK client, built outside ``src/hounds/interact`` (``src/ai/sdk_client.py``). Raises ``ImportError`` when the package is not
    installed; the caller reads that as "unavailable"."""
    return sdk_client.build_client(key, TIMEOUT_S)


def run_turn(client: Any, *, system: Sequence[Mapping], tools: Sequence[Mapping], history: Sequence[Mapping], user_text: str,
             on_tool: OnTool, spend: Spend, max_rounds: int = MAX_ROUNDS) -> TurnResult:
    """One conversational turn. ``history`` is ``[{"role", "content"}]`` ending on the hound's last line (or empty); ``on_tool`` answers
    each tool call the model makes. Never raises: a refusal of the meter, a failed call or a reply that cannot be used is a
    ``TurnResult`` with ``ok`` False and a ``reason``."""
    messages: List[dict] = [dict(m) for m in history] + [{"role": "user", "content": user_text}]
    usage = Usage()
    last_text = ""
    for round_no in range(max(1, max_rounds)):
        worst = worst_case_cost(text_chars(system, tools, messages), carried_rounds=round_no)
        try:
            spend.check(worst)
        except Resting as exc:
            return TurnResult(False, reason=REASON_RESTING + ": " + exc.reason, usage=usage, rounds=round_no)
        params: dict = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": list(system), "messages": list(messages),
                        "thinking": {"type": "adaptive"}, "output_config": {"effort": EFFORT}}
        if tools:
            params["tools"] = list(tools)
        began = time.monotonic()
        try:
            message = client.messages.create(**params)
        except Exception as exc:  # noqa: BLE001 -- classified; reported by class name and status only, never the message
            err = router_mod.classify_exception(exc)
            spend.record(err.kind if err.kind != "spend_limit" else "quota", 0.0, 0, 0, int((time.monotonic() - began) * 1000), error=err.detail)
            if err.kind in ("quota", "spend_limit", "auth", "timeout"):
                spend.cool_down(err)
            logger.warning("hound chat call failed kind=%s error=%s", err.kind, type(exc).__name__)
            return TurnResult(False, reason=REASON_FAILED + ": " + err.kind, usage=usage, rounds=round_no)
        cost, tin, write, read, tout = message_cost(message, worst)
        usage.input_tokens += tin
        usage.cache_write_tokens += write
        usage.cache_read_tokens += read
        usage.output_tokens += tout
        usage.calls += 1
        usage.cost_usd = round(usage.cost_usd + cost, 8)
        stop = getattr(message, "stop_reason", None)
        spend.record("refused" if stop == "refusal" else "ok", cost, tin + write + read, tout, int((time.monotonic() - began) * 1000))
        logger.info("hound chat round=%d in=%d out=%d cost_usd=%.6f stop=%s", round_no, tin + write + read, tout, cost, stop)
        if stop == "refusal":
            return TurnResult(False, reason=REASON_REFUSED, usage=usage, stop_reason=stop, rounds=round_no + 1)
        calls = [b for b in _blocks(message) if getattr(b, "type", None) == "tool_use"]
        text = reply_text(message)
        if text:
            last_text = text
        if stop == "max_tokens" and not calls:
            return TurnResult(False, reason=REASON_TOO_LONG, usage=usage, stop_reason=stop, rounds=round_no + 1)
        if not calls:
            return TurnResult(True, text=text or last_text, usage=usage, stop_reason=stop, rounds=round_no + 1)
        results = []
        for block in calls:
            args = getattr(block, "input", None)
            try:
                outcome = on_tool(str(getattr(block, "name", "")), args if isinstance(args, Mapping) else {})
            except Exception:  # noqa: BLE001 -- a bug in a tool must not strand the member: it is told the tool failed
                logger.exception("hound chat tool failed")
                outcome = ToolOutcome("That tool failed. Do not use it again; answer the member without it.", True)
            row = {"type": "tool_result", "tool_use_id": getattr(block, "id", ""), "content": outcome.content}
            if outcome.is_error:
                row["is_error"] = True
            results.append(row)
        # the assistant turn goes back whole, thinking blocks included (a tool loop needs them), then the results
        messages.append({"role": "assistant", "content": _blocks(message)})
        messages.append({"role": "user", "content": results})
    return TurnResult(True, text=last_text, usage=usage, stop_reason="max_rounds", rounds=max(1, max_rounds))
