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
#
# v3 (2026-10-04) adds rule 3a and the `derived` field: a calculated number in prose is allowed only when the
# reason declares how it was calculated and the checker (critic.verify_derivations) recomputes it from packet
# values. No row has been published under v2, so the change cost no record. Rule 3 keeps its number and its
# words about quoting the packet; 3a is the exception, so the situation section still starts at 17.
#
# v4 (2026-10-04) adds rule 14a. The first published brief (two rows, both v3) told customers "the
# packet gives nothing beyond the price": "packet" is our internal word and a reader has never heard of
# it. Rule 14a tells the model to say "the data" or "what we have" in every field a reader sees, and the
# checker (critic.INTERNAL_WORDS) strikes the word like any banned one, so a slip is caught, not hoped
# against. Every other rule is byte for byte what it was and 14a takes no number, so the situation
# section still starts at 17. The two v3 rows stay as published: a row is never rewritten.
#
# v5 (2026-10-04) extends rule 14a to a second internal word. The published brief for Braves at Dodgers told
# a customer "the repo model likes the over more than the market does": "repo" is our word for this code
# base and the packet fields are repo_model_probability / repo_market_probability, so the model copied it.
# Rule 14a now also says never write "repo" or "the repo model"; it is LineHound's own model (LineHound's
# baseline model's probability). The checker (critic.INTERNAL_WORDS) strikes the word like "packet". Every
# other rule is byte for byte v4, and 14a keeps its number. The v3 and v4 rows stay as published.
PROMPT_VERSION = "analyst_prompt_v5"
# Arm B of the side-by-side test (docs/SITUATION_LAYER.md): the same (v5) prompt with "THE SITUATION"
# added before its closing line. Used only when the situation arm is switched on; the prompt
# above is untouched and tests pin that it is byte for byte what it was.
SITUATION_PROMPT_VERSION = "analyst_prompt_v5_situation"

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
3a. The one exception to doing arithmetic is a calculation you declare. A number you work out yourself (a difference, a sum, a ratio, a percent change, the days between two dates, the chance a price implies, a count or an average) may appear in a reason, a case against or the summary only if that item lists it in `derived` as {value, unit, op, inputs, note}. `op` is one of difference, sum, ratio, percent_change, days_between, implied_probability, count, mean. `inputs` are packet paths, in order: difference is the first minus the second, ratio is the first over the second, percent_change is the change from the first to the second as a percent of the first, days_between is the calendar days between two dates in UTC (later minus earlier), implied_probability takes one American price, count takes one list. `unit` is what the value is measured in (days, runs, percent, and so on) and `note` says in plain words what it is. The checker recomputes every derived value from the packet, and a wrong one strikes the call. Put the summary's in `summary_derived`. An item with no calculated number has an empty `derived`.
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
14a. Everything a reader sees (the summary, every reason's claim, the case against and what_would_change_it) is read by a customer who has never heard of a packet. In those fields call the data "the data" or "what we have", never "the packet". The checker strikes the word "packet" there. Likewise never write "repo", "repos", "repository" or "the repo model": the probability the packet calls repo_model_probability is LineHound's own model, so say "LineHound's own model" (and "the market" for repo_market_probability). The checker strikes those words too. Evidence paths keep their own form.
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

# THE MLB SCHEMA (prompt v2, v3) AND WHY `RESPONSE_SCHEMA` IS LEFT ALONE
# ---------------------------------------------------------------------
# `RESPONSE_SCHEMA` above is shared: the UFC analyst (ufc_analyst.py, ufc_cli.py) sends and hashes it
# by name, and the UFC prompt never asks for a case against or a derived number. Adding either to it
# would change the UFC request, its prompt hash and what the UFC critic strikes, in a file this change
# does not own. So the MLB schema is a copy with more fields, and `schema_for(packet)` picks by the
# packet (an MLB game packet has a `game` block and no `bout`). Every MLB path (request, shape
# check, critic, ledger hash) goes through it; UFC goes on using `RESPONSE_SCHEMA` untouched.
#
# v2 added the required `case_against`. v3 adds `derived` to every reason and to the case against, and
# `summary_derived` beside the summary: the calculations the item's prose relies on, each recomputed by
# the critic (critic.verify_derivations). The ops, and the units each may be written in, are a CLOSED
# set named here so the prompt, the schema and the checker cannot drift apart (the checker adds the
# arithmetic, and a test pins that the two key sets are the same).
DERIVATION_UNITS: dict = {
    "difference": ("runs", "points", "games", "wins", "innings", "hits", "strikeouts", "degrees",
                   "mph", "units", "percentage points"),
    "sum": ("runs", "points", "games", "wins", "innings", "hits", "strikeouts", "degrees",
            "mph", "units", "percentage points", "percent"),
    "mean": ("runs", "points", "games", "wins", "innings", "hits", "strikeouts", "degrees",
             "mph", "units", "percentage points", "percent"),
    "ratio": ("ratio", "times", "percent"),
    "percent_change": ("percent",),
    "days_between": ("days",),
    "implied_probability": ("percent", "probability"),
    "count": ("items", "games", "players", "books", "quotes", "entries"),
}
DERIVATION_OPS = tuple(DERIVATION_UNITS)
DERIVATION_KEYS = ("value", "unit", "op", "inputs", "note")
MAX_DERIVATIONS = 6          # per item: a reason that needs more than this is doing arithmetic, not citing

_DERIVATION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": list(DERIVATION_KEYS),
    "properties": {
        "value": {"type": "number"},
        "unit": {"type": "string", "enum": sorted({u for us in DERIVATION_UNITS.values() for u in us})},
        "op": {"type": "string", "enum": list(DERIVATION_OPS)},
        "inputs": {"type": "array", "items": _STR},
        "note": _STR,
    },
}
_DERIVED_SCHEMA: dict = {"type": "array", "items": _DERIVATION_SCHEMA}

_REASON_SCHEMA = RESPONSE_SCHEMA["properties"]["calls"]["items"]["properties"]["reasons"]["items"]
CASE_AGAINST_SCHEMA: dict = {"anyOf": [_REASON_SCHEMA, {"type": "null"}]}


def _mlb_schema() -> dict:
    schema = copy.deepcopy(RESPONSE_SCHEMA)
    schema["required"] = list(schema["required"]) + ["summary_derived"]
    schema["properties"]["summary_derived"] = copy.deepcopy(_DERIVED_SCHEMA)
    item = schema["properties"]["calls"]["items"]
    reason = item["properties"]["reasons"]["items"]
    reason["required"] = list(reason["required"]) + ["derived"]
    reason["properties"]["derived"] = copy.deepcopy(_DERIVED_SCHEMA)
    item["required"] = list(item["required"]) + ["case_against"]
    item["properties"]["case_against"] = {"anyOf": [copy.deepcopy(reason), {"type": "null"}]}
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


def _derived_shape_errors(where: str, derived: Any) -> list:
    """Shape errors of a `derived` list. Only the SHAPE: an unknown op, a unit the op does not allow or
    a value that does not recompute is the critic's to strike (with the reason), not a reason to ask
    the model again. An absent `derived` is an empty one, as an absent case_against is null."""
    if derived is None:
        return []
    if not isinstance(derived, list):
        return [f"{where}.derived must be a list"]
    errors = []
    for k, d in enumerate(derived):
        at = f"{where}.derived[{k}]"
        if not isinstance(d, Mapping):
            errors.append(f"{at} is not an object")
            continue
        extra = set(d) - set(DERIVATION_KEYS)
        if extra:
            errors.append(f"{at} has unexpected keys {sorted(extra)}")
        absent = [key for key in DERIVATION_KEYS if key not in d]
        if absent:
            errors.append(f"{at} is missing {absent}")
            continue
        if not _is_num(d["value"]):
            errors.append(f"{at}.value must be a number")
        if not isinstance(d["op"], str) or not isinstance(d["unit"], str) or not isinstance(d["note"], str):
            errors.append(f"{at} needs op, unit and note as strings")
        if not isinstance(d["inputs"], list) or not all(isinstance(i, str) for i in d["inputs"]):
            errors.append(f"{at}.inputs must be a list of packet paths")
    return errors


def _reason_shape_errors(where: str, reason: Any, *, derived: bool = False) -> list:
    """Shape errors of one {claim, evidence: [{path, value}]}: a reason or a case against.
    `derived` (an MLB packet, prompt v3) also checks the shape of its `derived` list."""
    if not isinstance(reason, Mapping) or not isinstance(reason.get("claim"), str) \
            or not isinstance(reason.get("evidence"), list):
        return [f"{where} needs a claim and an evidence list"]
    errors = [f"{where}.evidence[{k}] needs a path and a value"
              for k, ev in enumerate(reason["evidence"])
              if not isinstance(ev, Mapping) or not isinstance(ev.get("path"), str) or "value" not in ev]
    if derived:
        errors.extend(_derived_shape_errors(where, reason.get("derived")))
    return errors


def validate_output(output: Any, packet: Mapping) -> list:
    """Every way `output` fails the schema, as readable strings. Empty list
    means the SHAPE is right; it says nothing about whether it is true."""
    errors: list = []
    if not isinstance(output, Mapping):
        return ["the answer is not a JSON object"]
    schema = schema_for(packet)
    mlb = is_mlb_packet(packet)
    extra = set(output) - set(schema["properties"])
    if extra:
        errors.append(f"unexpected top-level keys: {sorted(extra)}")
    if mlb:
        errors.extend(_derived_shape_errors("summary", output.get("summary_derived")))
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
            errors.extend(_reason_shape_errors(f"{where}: case_against", call["case_against"],
                                               derived=mlb))
        reasons = call["reasons"]
        if not isinstance(reasons, list) or not reasons:
            errors.append(f"{where}: reasons must be a non-empty list")
            continue
        for j, reason in enumerate(reasons):
            errors.extend(_reason_shape_errors(f"{where}: reasons[{j}]", reason, derived=mlb))
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
