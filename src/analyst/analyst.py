"""The analyst: one model call per game, strict JSON in and out.

WHAT THIS MODULE DOES AND DOES NOT DO
-------------------------------------
It turns a frozen packet into a request, sends it, parses the answer and checks
its SHAPE (types, enums, word count, one call per slot). It does not decide
whether any claim is TRUE: that is `critic.py`, which runs next and is allowed
to strike what the packet does not support. Shape first, truth second, so a
malformed answer can be retried (it costs a second call) while an untrue one
is published as a PASS and never retried (a retry would just be asking again
until the model says something we like).

HTTP, NOT AN SDK
----------------
`src/` is stdlib-only, so the Messages API is called over HTTPS with `urllib`.
The request shape follows the claude-api reference for claude-sonnet-5-5:
`output_config.format` carries the JSON schema (structured outputs), `effort`
sits beside it, and no `temperature`, `thinking` or prefill is sent (the
current models reject the first two when they are not default and the third
outright). The model id, price per million tokens and effort come from
config/analyst.json. The key comes from ANTHROPIC_API_KEY, at the moment of
the call, and is never stored or printed.

THE SPEND CAP IS HARD
---------------------
`SpendMeter` is checked BEFORE every call against the worst case that call can
cost (estimated input plus the full `max_output_tokens`), and charged AFTER it
from the usage the API returns. A run can therefore never exceed the cap, only
stop short of it, and it says so (`SpendCapReached`). Dollars are estimates:
tokens x the configured price. The configured price is recorded beside each
cost so a price change cannot rewrite history.

Every function that talks to the network takes the HTTP caller as an argument,
so the tests never touch one.
"""

from __future__ import annotations

import copy
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from src.analyst import config as config_mod
from src.analyst import situation_prompt
from src.ledger.chain import canonical_bytes

# v2 (2026-10-03) adds the required `case_against` on every TAKE. v1 never ran against the API (no
# ledger file existed), so the change cost no record. The new rule is numbered 13a so the rules after
# it keep their numbers: the situation section (situation_prompt.py) takes 17 to 20 and must not collide.
PROMPT_VERSION = "analyst_prompt_v2"
# Arm B of the side-by-side test (docs/SITUATION_LAYER.md): the same (v2) prompt with "THE SITUATION"
# added before its closing line. Used only when the situation arm is switched on; the prompt
# above is untouched and tests pin that it is byte for byte what it was.
SITUATION_PROMPT_VERSION = "analyst_prompt_v2_situation"

VERDICTS = ("TAKE", "PASS", "TAKE_OTHER_SIDE")
CONFIDENCES = ("low", "medium", "high")
SUMMARY_WORDS = (120, 200)

# The owner's rulings of 2026-09-20 ("no moneyline at -200 or worse, ever") and
# 2026-09-22 ("no public pick at -200 or worse, on any sport"): no TAKE at a
# price of -200 or worse. The build brief named the moneyline; the second
# ruling is broader, so the floor is applied to EVERY market, heavy-juice props
# included. Narrowing it to the moneyline is the one `if` in critic.check_call.
# Enforced by the critic whatever the model says, and stated in the prompt so
# the model does not spend a call on one.
TAKE_PRICE_FLOOR = -200

SYSTEM_PROMPT = """\
You are a baseball betting analyst. You write the analysis of one MLB game and make a call on every market the packet prices. You are an AI model and the reader knows it. Your work is published before the game, graded afterward, and shown next to its record whatever that record turns out to be. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

THE PACKET IS YOUR ONLY SOURCE
1. Reason only from the packet. Use no outside knowledge of any team, player, injury, weather, standing or result, even if you are sure of it. If something matters and is not in the packet, say it is missing.
2. A claim without a packet path is forbidden. Every reason has evidence: a list of {path, value}. A path names one value in the packet and starts at the packet's own top-level key. The value is copied exactly. Examples of real paths: markets.moneyline.options[0].best.price and sections.starters.values.home_sp_era. Never start a path with data. or packet.
3. Every number you write in prose must appear in the packet, or be a price or probability you are yourself giving in a call. Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers. Do not write clock times.
4. `missing` lists what is absent, stale or thin. Weigh it. A call that rests on something listed there is a PASS.

THE CALLS
5. Make exactly one call for every entry in `slots`, in the same order, using its slot_id and its market. `selection` must be one of that slot's selections, written exactly as listed. The first selection is the lean: the side the books favour.
6. Verdicts. TAKE: bet the lean (the first selection) at the price you name. TAKE_OTHER_SIDE: bet the other selection, the side the books do not favour. PASS: bet nothing in this market.
7. PASS is the default. When the evidence is thin, or the packet gives you nothing about this market beyond its own price, PASS. Say plainly when the market is probably right, and what makes you think so.
8. Never TAKE any bet at a price of -200 or worse, in any market (-200, -250, -325 and so on). PASS it, or if the other side is the one you like, take that.
9. price and book: the quote you would take, copied from the selection's quotes in the packet. For a PASS you may give the best quote or null.
10. fair_estimate: your own probability that the selection wins, between 0.01 and 0.99. The books' own de-vigged number is in the packet as fair_probability, and for props the repo model's number is in context. If you depart from the books by more than a few points, the reasons must show what the packet knows that the price does not. For a PASS you may give null.
11. pass_price: the American price at which the selection stops being worth taking, which is the break-even price of your fair_estimate. On a PASS, the price at which you would start to take it, or null if no price would do.
12. confidence: low, medium or high. High only when several independent packet facts agree and nothing relevant is in `missing`.
13. what_would_change_it: one sentence naming a specific new fact that would flip the call, such as a lineup change or a scratch. If it names a price, that price is your pass_price.
13a. case_against: for a TAKE or a TAKE_OTHER_SIDE, the strongest reason from the packet that this bet loses, written as {claim, evidence} and built like a reason. It must name a specific weakness in this bet, such as a number in the packet that points the other way, not general risk: "anything can happen in baseball" is not a case against. Cite at least one packet path, and quote only numbers that are in the packet. Argue it as hard as you would argue the other side. For a PASS it is null.

THE WORDS
14. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have, or certainty. No exclamation marks.
15. Do not recommend a stake size and do not describe anything as a bet you or we placed.

THE SUMMARY
16. `summary` is the argument in 120 to 200 words of plain prose, one or two paragraphs, no lists, no markdown. Say where you lean and why, where you pass, what the market probably has right, and which missing inputs matter. A voice like: "Even though TB is -127, I like it: the starter has the better numbers over his last starts and the price is close to a coin flip." Only with facts that are actually in the packet.

Reply with one JSON object that matches the schema and nothing else."""

SITUATION_SYSTEM_PROMPT = situation_prompt.with_section(SYSTEM_PROMPT, situation_prompt.MLB_SITUATION_SECTION)

_STR = {"type": "string"}
_NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_INT_OR_NULL = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_STR_OR_NULL = {"anyOf": [{"type": "string"}, {"type": "null"}]}

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "calls"],
    "properties": {
        "summary": _STR,
        "calls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["slot_id", "market", "selection", "verdict", "price",
                             "book", "fair_estimate", "confidence", "reasons",
                             "pass_price", "what_would_change_it"],
                "properties": {
                    "slot_id": _STR,
                    "market": _STR,
                    "selection": _STR,
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "price": _INT_OR_NULL,
                    "book": _STR_OR_NULL,
                    "fair_estimate": _NUM_OR_NULL,
                    "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                    "reasons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["claim", "evidence"],
                            "properties": {
                                "claim": _STR,
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["path", "value"],
                                        "properties": {
                                            "path": _STR,
                                            "value": {"anyOf": [
                                                {"type": "string"}, {"type": "number"},
                                                {"type": "boolean"}, {"type": "null"}]},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "pass_price": _INT_OR_NULL,
                    "what_would_change_it": _STR,
                },
            },
        },
    },
}

# THE MLB SCHEMA (prompt v2) AND WHY `RESPONSE_SCHEMA` IS LEFT ALONE
# ------------------------------------------------------------------
# `RESPONSE_SCHEMA` above is shared: the UFC analyst (ufc_analyst.py, ufc_cli.py) sends and hashes it
# by name, and the UFC prompt never asks for a case against. Adding the field to it would change the
# UFC request, its prompt hash and what the UFC critic strikes, in a file this change does not own.
# So the MLB schema is a copy with one more required call field, and `schema_for(packet)` picks by
# the packet (an MLB game packet has a `game` block and no `bout`). Every MLB path (request, shape
# check, critic, ledger hash) goes through it; UFC goes on using `RESPONSE_SCHEMA` untouched.
_REASON_SCHEMA = RESPONSE_SCHEMA["properties"]["calls"]["items"]["properties"]["reasons"]["items"]
CASE_AGAINST_SCHEMA: dict = {"anyOf": [_REASON_SCHEMA, {"type": "null"}]}


def _mlb_schema() -> dict:
    schema = copy.deepcopy(RESPONSE_SCHEMA)
    item = schema["properties"]["calls"]["items"]
    item["required"] = list(item["required"]) + ["case_against"]
    item["properties"]["case_against"] = copy.deepcopy(CASE_AGAINST_SCHEMA)
    return schema


MLB_RESPONSE_SCHEMA: dict = _mlb_schema()


def is_mlb_packet(packet: Any) -> bool:
    return isinstance(packet, Mapping) and isinstance(packet.get("game"), Mapping) and "bout" not in packet


def schema_for(packet: Any) -> dict:
    """The response schema for this packet's sport: MLB's (with `case_against`) or the shared one."""
    return MLB_RESPONSE_SCHEMA if is_mlb_packet(packet) else RESPONSE_SCHEMA


CRITIC_SYSTEM_PROMPT = """\
You check one analyst's published calls against the fact packet it was written from. You add no facts and make no calls of your own. For each call decide whether every reason's claim is actually supported by the evidence values it cites, and whether the verdict follows from the reasons. A claim that goes beyond its evidence, reads a number the wrong way, or draws a conclusion the cited facts do not support is not supported. Do the same for the summary. Be strict: when in doubt, it is not supported. Reply with one JSON object that matches the schema and nothing else."""

CRITIC_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["checks", "summary_supported", "summary_problem"],
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["slot_id", "supported", "problem"],
                "properties": {"slot_id": _STR, "supported": {"type": "boolean"},
                               "problem": _STR},
            },
        },
        "summary_supported": {"type": "boolean"},
        "summary_problem": _STR,
    },
}


class AnalystError(RuntimeError):
    """The analyst could not produce an answer. Nothing is published."""


class Blocked(AnalystError):
    """A precondition (the key) is missing. Nothing was sent."""


class SpendCapReached(AnalystError):
    """The next call could exceed the run's spend cap, so it was not made."""


class ModelRefused(AnalystError):
    """The API answered with a refusal or an unusable stop reason.

    The call completed, so it was billed: `usage` and `cost_usd` carry what it
    cost (set by `analyze`) so the run can log it like any other spend.
    """
    usage: dict = {}
    cost_usd: float = 0.0


class MalformedOutput(AnalystError):
    def __init__(self, errors: Sequence[str], usage: Optional[Mapping] = None):
        super().__init__("; ".join(errors[:6]))
        self.errors = list(errors)
        self.usage = dict(usage or {})


class HttpFailure(AnalystError):
    pass


# ---------------------------------------------------------------------------
# spend
# ---------------------------------------------------------------------------

def estimate_tokens(*texts: str) -> int:
    """A deliberately high token estimate (JSON of numbers runs near 3
    characters a token), used only for the worst-case pre-call check. Real
    spend is charged from the API's own usage numbers."""
    return int(sum(len(t) for t in texts) / 3.0) + 64


def cost_usd(usage: Mapping, cfg: Mapping) -> float:
    price = cfg["price_per_million_usd"]
    cache_read = float(price.get("cache_read", price["input"]))
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    read = int(usage.get("cache_read_input_tokens") or 0)
    wrote = int(usage.get("cache_creation_input_tokens") or 0)
    return (inp * price["input"] + wrote * price["input"] * 1.25
            + read * cache_read + out * price["output"]) / 1_000_000.0


@dataclass
class SpendMeter:
    """Running spend for one `analyst run`, with a hard stop."""
    max_usd: float
    max_tokens: int
    spent_usd: float = 0.0
    tokens: int = 0
    calls: int = 0

    @classmethod
    def from_config(cls, cfg: Mapping) -> "SpendMeter":
        cap = cfg["spend_cap"]
        return cls(max_usd=float(cap["max_usd_per_run"]),
                   max_tokens=int(cap["max_tokens_per_run"]))

    def check_before(self, est_input_tokens: int, max_output_tokens: int,
                     cfg: Mapping) -> None:
        price = cfg["price_per_million_usd"]
        worst_usd = (est_input_tokens * price["input"]
                     + max_output_tokens * price["output"]) / 1_000_000.0
        worst_tokens = est_input_tokens + max_output_tokens
        if self.spent_usd + worst_usd > self.max_usd:
            raise SpendCapReached(
                f"spend cap reached: ${self.spent_usd:.2f} spent of "
                f"${self.max_usd:.2f}; the next call could cost up to "
                f"${worst_usd:.2f}")
        if self.tokens + worst_tokens > self.max_tokens:
            raise SpendCapReached(
                f"token cap reached: {self.tokens} used of {self.max_tokens}; "
                f"the next call could use up to {worst_tokens}")

    def charge(self, usage: Mapping, cfg: Mapping) -> float:
        usd = cost_usd(usage, cfg)
        self.spent_usd += usd
        self.tokens += int(usage.get("input_tokens") or 0) \
            + int(usage.get("output_tokens") or 0) \
            + int(usage.get("cache_read_input_tokens") or 0) \
            + int(usage.get("cache_creation_input_tokens") or 0)
        self.calls += 1
        return usd


def _add_usage(total: dict, usage: Mapping) -> None:
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens"):
        total[key] = int(total.get(key) or 0) + int(usage.get(key) or 0)


# ---------------------------------------------------------------------------
# the request
# ---------------------------------------------------------------------------

def packet_json(packet: Mapping) -> str:
    return canonical_bytes(packet).decode("utf-8")


def user_message(packet: Mapping, repair: Optional[Sequence[str]] = None) -> str:
    slots = [s["slot_id"] for s in packet.get("slots", [])]
    text = ("PACKET (JSON). Paths in your evidence start at its top-level keys.\n"
            + packet_json(packet)
            + "\n\nMake one call for each of these slot ids, in this order: "
            + ", ".join(slots) + ".")
    if repair:
        text += ("\n\nYour previous answer was rejected for these reasons. "
                 "Fix them and answer again:\n- " + "\n- ".join(repair[:12]))
    return text


def build_request(packet: Mapping, cfg: Mapping, *,
                  repair: Optional[Sequence[str]] = None,
                  system_prompt: str = SYSTEM_PROMPT) -> dict:
    """The exact JSON body that would be POSTed. No key, no network.

    `system_prompt` is the one thing a sport changes (`ufc_analyst.py` passes its
    own); the schema, the effort and the request shape are shared on purpose.
    """
    return {
        "model": cfg["model"],
        "max_tokens": int(cfg["max_output_tokens"]),
        "system": system_prompt,
        "output_config": {
            "format": {"type": "json_schema", "schema": schema_for(packet)},
            "effort": cfg["effort"],
        },
        "messages": [{"role": "user", "content": user_message(packet, repair)}],
    }


# ---------------------------------------------------------------------------
# the call
# ---------------------------------------------------------------------------

HttpPost = Callable[[str, Mapping, bytes, float], tuple]


def urllib_post(url: str, headers: Mapping, body: bytes, timeout: float) -> tuple:
    """`(status, bytes)` over HTTPS. HTTP error statuses come back as values;
    only a failure to reach the server raises."""
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- fixed https url from config
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpFailure(f"could not reach the API: {type(exc).__name__}") from exc


def _headers(api_key: str, cfg: Mapping) -> dict:
    return {"content-type": "application/json", "x-api-key": api_key,
            "anthropic-version": cfg["anthropic_version"]}


RETRYABLE = (408, 429, 500, 502, 503, 504, 529)


def post_message(body: Mapping, cfg: Mapping, *, api_key: str,
                 http_post: HttpPost = urllib_post,
                 sleep: Callable[[float], None] = time.sleep,
                 http_retries: int = 2) -> dict:
    """POST one Messages request; the parsed response, or `AnalystError`.

    Retries only transport-level trouble (rate limit, overload, 5xx). Those
    retries are not charged: the API bills a completed response. The error
    text carries the status and the API's own message and never the key.
    """
    raw = json.dumps(body).encode("utf-8")
    for attempt in range(http_retries + 1):
        status, payload = http_post(cfg["api_url"], _headers(api_key, cfg), raw,
                                    float(cfg["request_timeout_s"]))
        if status == 200:
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise HttpFailure("the API sent a response that is not JSON") from exc
        if status in RETRYABLE and attempt < http_retries:
            sleep(2.0 * (attempt + 1))
            continue
        try:
            message = json.loads(payload).get("error", {}).get("message", "")
        except (json.JSONDecodeError, AttributeError):
            message = ""
        raise HttpFailure(f"the API returned HTTP {status}: {str(message)[:300]}")
    raise HttpFailure("the API did not answer")  # pragma: no cover


def response_text(resp: Mapping) -> str:
    """The text of a response, or `ModelRefused` when it has none to use."""
    stop = resp.get("stop_reason")
    if stop == "refusal":
        raise ModelRefused("the model declined to answer (stop_reason refusal)")
    if stop == "max_tokens":
        raise ModelRefused("the answer was cut off at max_tokens; nothing usable")
    parts = [b.get("text", "") for b in resp.get("content") or []
             if isinstance(b, Mapping) and b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise ModelRefused("the response held no text")
    return text


# ---------------------------------------------------------------------------
# shape validation
# ---------------------------------------------------------------------------

def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def words(text: str) -> int:
    return len(str(text).split())


def _reason_shape_errors(where: str, reason: Any) -> list:
    """Shape errors of one {claim, evidence: [{path, value}]}: a reason or a case against."""
    if not isinstance(reason, Mapping) or not isinstance(reason.get("claim"), str) \
            or not isinstance(reason.get("evidence"), list):
        return [f"{where} needs a claim and an evidence list"]
    return [f"{where}.evidence[{k}] needs a path and a value"
            for k, ev in enumerate(reason["evidence"])
            if not isinstance(ev, Mapping) or not isinstance(ev.get("path"), str) or "value" not in ev]


def validate_output(output: Any, packet: Mapping) -> list:
    """Every way `output` fails the schema, as readable strings. Empty list
    means the SHAPE is right; it says nothing about whether it is true."""
    errors: list = []
    if not isinstance(output, Mapping):
        return ["the answer is not a JSON object"]
    extra = set(output) - {"summary", "calls"}
    if extra:
        errors.append(f"unexpected top-level keys: {sorted(extra)}")
    summary = output.get("summary")
    if not isinstance(summary, str):
        errors.append("summary must be a string")
    else:
        n = words(summary)
        if not SUMMARY_WORDS[0] <= n <= SUMMARY_WORDS[1]:
            errors.append(f"summary is {n} words; it must be {SUMMARY_WORDS[0]} to "
                          f"{SUMMARY_WORDS[1]}")
    calls = output.get("calls")
    if not isinstance(calls, list):
        return errors + ["calls must be a list"]
    schema = schema_for(packet)
    markets = packet.get("markets") or {}
    seen: dict = {}
    for i, call in enumerate(calls):
        where = f"calls[{i}]"
        if not isinstance(call, Mapping):
            errors.append(f"{where} is not an object")
            continue
        item_schema = schema["properties"]["calls"]["items"]
        # An absent case_against is read as null: the critic strikes a TAKE without one and says
        # why, which is a better answer to a forgotten key than rejecting the whole analysis.
        missing = [k for k in item_schema["required"] if k not in call and k != "case_against"]
        if missing:
            errors.append(f"{where} is missing {missing}")
            continue
        extra = set(call) - set(item_schema["properties"])
        if extra:
            errors.append(f"{where} has unexpected keys {sorted(extra)}")
        sid = call["slot_id"]
        where = f"call {sid!r}"
        if sid not in markets:
            errors.append(f"{where}: not a slot in the packet")
            continue
        if sid in seen:
            errors.append(f"{where}: more than one call for this slot")
        seen[sid] = call
        if call["market"] != markets[sid]["market"]:
            errors.append(f"{where}: market must be {markets[sid]['market']!r}")
        if not isinstance(call["selection"], str):
            errors.append(f"{where}: selection must be a string")
        if call["verdict"] not in VERDICTS:
            errors.append(f"{where}: verdict must be one of {list(VERDICTS)}")
        if call["confidence"] not in CONFIDENCES:
            errors.append(f"{where}: confidence must be one of {list(CONFIDENCES)}")
        for key in ("price", "pass_price"):
            v = call[key]
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                errors.append(f"{where}: {key} must be a whole number or null")
        if call["book"] is not None and not isinstance(call["book"], str):
            errors.append(f"{where}: book must be a string or null")
        fe = call["fair_estimate"]
        if fe is not None and not (_is_num(fe) and 0.0 < fe < 1.0):
            errors.append(f"{where}: fair_estimate must be a probability between 0 and 1, or null")
        if not isinstance(call["what_would_change_it"], str) or not call["what_would_change_it"].strip():
            errors.append(f"{where}: what_would_change_it must be a sentence")
        if "case_against" in item_schema["properties"] and call.get("case_against") is not None:
            errors.extend(_reason_shape_errors(f"{where}: case_against", call["case_against"]))
        reasons = call["reasons"]
        if not isinstance(reasons, list) or not reasons:
            errors.append(f"{where}: reasons must be a non-empty list")
            continue
        for j, reason in enumerate(reasons):
            errors.extend(_reason_shape_errors(f"{where}: reasons[{j}]", reason))
    for sid in markets:
        if sid not in seen:
            errors.append(f"call {sid!r}: missing; every slot needs one call")
    order = [c.get("slot_id") for c in calls if isinstance(c, Mapping)]
    wanted = [s for s in markets if s in order]
    if not errors and [s for s in order if s in markets] != wanted:
        errors.append("calls are not in the same order as the slots")
    return errors


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    output: dict
    usage: dict
    cost_usd: float
    attempts: int
    model: str
    request_ids: list = field(default_factory=list)


def analyze(packet: Mapping, cfg: Mapping, *, api_key: Optional[str],
            http_post: HttpPost = urllib_post, meter: Optional[SpendMeter] = None,
            sleep: Callable[[float], None] = time.sleep,
            system_prompt: str = SYSTEM_PROMPT) -> AnalysisResult:
    """Ask the model for the game's analysis. Raises, never returns junk.

    `Blocked` without a key (nothing sent). Up to `max_attempts` calls: only a
    SHAPE failure earns a retry, with the reasons appended to the request.
    `system_prompt` defaults to the MLB prompt; another sport passes its own.
    """
    if not api_key:
        raise Blocked(f"{config_mod.ENV_KEY} is not set; the analyst cannot run")
    meter = meter or SpendMeter.from_config(cfg)
    usage_total: dict = {}
    total_cost = 0.0
    errors: list = []
    request_ids: list = []
    for attempt in range(1, int(cfg["max_attempts"]) + 1):
        body = build_request(packet, cfg, repair=errors or None, system_prompt=system_prompt)
        meter.check_before(estimate_tokens(body["system"],
                                           body["messages"][0]["content"]),
                           int(cfg["max_output_tokens"]), cfg)
        resp = post_message(body, cfg, api_key=api_key, http_post=http_post, sleep=sleep)
        usage = resp.get("usage") or {}
        total_cost += meter.charge(usage, cfg)
        _add_usage(usage_total, usage)
        if resp.get("id"):
            request_ids.append(resp["id"])
        try:
            text = response_text(resp)
        except ModelRefused as exc:
            exc.usage, exc.cost_usd = dict(usage_total), total_cost
            raise
        try:
            output = json.loads(text)
        except json.JSONDecodeError:
            errors = ["the answer was not valid JSON"]
            continue
        errors = validate_output(output, packet)
        if not errors:
            return AnalysisResult(output=output, usage=usage_total, cost_usd=total_cost,
                                  attempts=attempt, model=resp.get("model") or cfg["model"],
                                  request_ids=request_ids)
    raise MalformedOutput(errors, usage_total)


# ---------------------------------------------------------------------------
# the optional model critic's request
# ---------------------------------------------------------------------------

def build_critic_request(packet: Mapping, output: Mapping, cfg: Mapping) -> dict:
    mc = cfg["model_critic"]
    text = ("PACKET (JSON):\n" + packet_json(packet)
            + "\n\nPUBLISHED ANALYSIS (JSON):\n" + canonical_bytes(output).decode("utf-8")
            + "\n\nCheck every call and the summary.")
    return {
        "model": mc["model"],
        "max_tokens": int(mc["max_output_tokens"]),
        "system": CRITIC_SYSTEM_PROMPT,
        "output_config": {"format": {"type": "json_schema", "schema": CRITIC_SCHEMA},
                          "effort": cfg["effort"]},
        "messages": [{"role": "user", "content": text}],
    }


def run_model_critic(packet: Mapping, output: Mapping, cfg: Mapping, *,
                     api_key: Optional[str], http_post: HttpPost = urllib_post,
                     meter: Optional[SpendMeter] = None,
                     sleep: Callable[[float], None] = time.sleep) -> tuple:
    """`(verdict dict, usage, cost)`; `AnalystError` on any trouble. The
    caller treats a failure as "the critic did not run", never as "all clear"."""
    if not api_key:
        raise Blocked(f"{config_mod.ENV_KEY} is not set")
    meter = meter or SpendMeter.from_config(cfg)
    body = build_critic_request(packet, output, cfg)
    meter.check_before(estimate_tokens(body["system"], body["messages"][0]["content"]),
                       int(cfg["model_critic"]["max_output_tokens"]), cfg)
    resp = post_message(body, cfg, api_key=api_key, http_post=http_post, sleep=sleep)
    usage = resp.get("usage") or {}
    cost = meter.charge(usage, cfg)
    try:
        verdict = json.loads(response_text(resp))
    except json.JSONDecodeError as exc:
        raise MalformedOutput(["the critic's answer was not valid JSON"], usage) from exc
    if not isinstance(verdict, Mapping) or not isinstance(verdict.get("checks"), list):
        raise MalformedOutput(["the critic's answer has the wrong shape"], usage)
    return verdict, dict(usage), cost
