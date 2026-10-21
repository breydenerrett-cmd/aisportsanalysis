"""The answer an AI hound asks a model for: its schema, its semantic checks, and the rules it is told.

THE ANSWER
----------
    {"decision": "bet" | "pass", "market": "moneyline" | "spread" | "total" | null,
     "side": "home" | "away" | "over" | "under" | null, "confidence": 1..5, "reason": "<= 25 words"}

``confidence`` is required on a pass too (how sure the model is that nothing here is worth a bet).
The schema checks shapes; ``check_decision`` checks what a shape cannot: a bet needs a market and a side,
and the side has to belong to the market (home or away for a moneyline or spread, over or under for a
total). A model that answers outside this is given no second chance on the same call: the router moves on
to the next provider once, and then there is no answer and the hound passes.

THE RULES TEXT is part of what is pre-registered (``docs/PREREG_AI_HOUNDS.md``) and is versioned:
``PROMPT_VERSION`` is stamped on every decision row, so a later edit to the words is a new version, never
a silent change under an old record.

WHY THE PROMPT SAYS "DO NOT USE WHAT YOU KNOW ABOUT HOW IT TURNED OUT". A language model has read about
games that have already been played. The hounds only ever see games that have not started (they are
forward-only; ``docs/PREREG_AI_HOUNDS.md``), so there is no result for it to remember, but the line costs
nothing and says what the exercise is.
"""

from __future__ import annotations

from typing import List

from src.ai import schema

PROMPT_VERSION = "ai_hound_prompt_v1"
MAX_REASON_WORDS = 25
MARKETS = ("moneyline", "spread", "total")
SIDES = ("home", "away", "over", "under")
SIDES_BY_MARKET = {"moneyline": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under")}

DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "market", "side", "confidence", "reason"],
    "properties": {
        "decision": {"type": "string", "enum": ["bet", "pass"]},
        "market": {"type": ["string", "null"], "enum": list(MARKETS) + [None]},
        "side": {"type": ["string", "null"], "enum": list(SIDES) + [None]},
        "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
        "reason": {"type": "string", "minLength": 1, "maxWords": MAX_REASON_WORDS},
    },
}

SYSTEM_PROMPT = (
    "You are one analyst in a paper-only research exercise: no real money is staked and nothing you write "
    "is advice. You are given the betting board for ONE game as it stood about an hour before it starts, "
    "plus basic team form from stored results.\n"
    "Decide whether to make ONE paper bet on this game or to pass.\n"
    "Rules:\n"
    "- Use only the data in the message. Do not use anything you know about how this game or this season "
    "turned out.\n"
    "- A bet is one market (moneyline, spread or total) and one side of it, chosen from the markets listed "
    "in the data.\n"
    "- Never choose a side whose average price is -200 or worse. Code rejects those and the answer is "
    "wasted.\n"
    "- Passing is a normal answer. Bet only when the data gives you a specific reason you can state; a hunch "
    "is a pass.\n"
    "- The prices already include the books' margin. Do not assume the favourite or the underdog is the "
    "better side.\n"
    "Answer with ONE JSON object and nothing else, with exactly these keys:\n"
    '{"decision": "bet" or "pass", "market": "moneyline" or "spread" or "total" or null, '
    '"side": "home" or "away" or "over" or "under" or null, "confidence": an integer 1 to 5, '
    f'"reason": "at most {MAX_REASON_WORDS} words"}}\n'
    "For a pass, market and side are null. Confidence is 1 (a guess) to 5 (the data is clear)."
)


def check_decision(obj: dict) -> List[str]:
    """Semantic problems with a schema-valid decision (empty = fine)."""
    if obj.get("decision") != "bet":
        return []
    market, side = obj.get("market"), obj.get("side")
    if market is None or side is None:
        return ["a bet needs both a market and a side"]
    if side not in SIDES_BY_MARKET.get(market, ()):
        return [f"side {side!r} does not belong to market {market!r}"]
    return []


def validate_decision(obj: dict) -> List[str]:
    """Schema problems plus semantic problems, in one list."""
    return schema.validate(obj, DECISION_SCHEMA) + (check_decision(obj) if isinstance(obj, dict) else [])
