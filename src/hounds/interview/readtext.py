"""Free text into typed pieces, by the deterministic English parser, for triggers and for skip rules.

The parser (src/hounds/english/parser.py) is the only thing that turns words into conditions, whoever supplied
the words: the person directly, or a model's restatement of them. This module wraps it twice.

INCLUDE TEXT ("bet when ...")
  The parser's rule(s) become {fields, items}. Only what the person STATED becomes a field: a sport or market the
  parser filled in as a default ("no market was named, so this is read as a moneyline rule") is not an assertion,
  so it can never contradict what the scope question said. Several separate rules in one answer are not guessed
  between; the machine asks which one the hound follows.

SKIP TEXT ("skip when ...")
  The parser reads the clause as if it said "bet when ...", then each condition is turned into its exact opposite
  (conditions.py). A clause is refused, with the reason and with nothing applied, when any word of it was not
  understood, when it names a side, a price or a sport (those belong to the bet, not to a skip rule), or when a
  condition has no exact opposite. Applying half of a skip rule would quietly loosen it.

AND / OR
  The parser reads "wind under 5 or temperature above 80" as both. Where the words say "or" (or a skip clause names
  two conditions) the connective is not guessed: `needs_connective` is set and the machine asks.
"""

from __future__ import annotations

import re
from typing import List, Optional

from src.hounds import user_rules as R
from src.hounds.english import parser, render
from src.hounds.interview import conditions as C

# "skip when", "pass on games where", "don't bet if" ... removed so the parser sees the condition itself
_SKIP_LEAD = re.compile(
    r"^\s*(?:(?:please\s+)?(?:skip|pass|avoid|ignore)(?:\s+on)?|don'?t\s+bet|do\s+not\s+bet|never\s+bet|no\s+bet|not|"
    r"unless|except(?:\s+when|\s+if)?)\s+"
    r"(?:(?:(?:any|the|all)\s+)?games?\s+)?(?:when|if|where|on|with)?\s*", re.I)
# a clause that is a skip rule even though it was typed in the "what has to be true" box
_IS_SKIP = re.compile(r"^\s*(?:(?:please\s+)?(?:skip|pass|avoid|ignore)\b|don'?t\s+bet\b|do\s+not\s+bet\b|never\s+bet\b|no\s+bet\b|"
                      r"unless\b|except\b)", re.I)
_CLAUSE_SPLIT = re.compile(r"[\n;]+|(?<=[.!?])\s+|,?\s+(?:and\s+|but\s+|also\s+)?(?=(?:skip|pass\s+(?:on|when)|avoid|"
                           r"don'?t\s+bet|do\s+not\s+bet|never\s+bet|unless|except)\b)", re.I)
# "or" between conditions, not the idioms "3 or more", "-150 or shorter"
_OR = re.compile(r"\bor\b(?!\s+(?:more|less|fewer|better|worse|shorter|longer|higher|lower|greater|smaller|over|under|above|below|equal|so|else))", re.I)
_RULE_FIELDS = ("sports", "markets", "side", "price_min", "price_max", "min_books")
_GLOBAL_FIELDS = ("max_bets_per_day", "lock_minutes", "stake_units")


def partition_text(text: str) -> tuple:
    """(include text, [skip clauses]) from one box of prose. "Skip when it rains" typed among the triggers is a skip
    rule, and reading it as a trigger would bet on exactly the games the person meant to avoid."""
    include, skips = [], []
    for part in _CLAUSE_SPLIT.split(str(text or "")):
        part = (part or "").strip(" ,.\t")
        if not part:
            continue
        (skips if _IS_SKIP.match(part) else include).append(part)
    return ". ".join(include), skips


def strip_skip_lead(clause: str) -> str:
    return _SKIP_LEAD.sub("", clause).strip()


def has_or(text: str) -> bool:
    return bool(_OR.search(text or ""))


def _rules_of(result: dict) -> List[dict]:
    spec = result.get("spec")
    if spec and spec.get("rules"):
        return spec["rules"]
    return (result.get("draft") or {}).get("rules") or []


def _assumed(result: dict, needle: str) -> bool:
    return any(needle in a for a in result.get("assumed", []))


def read_include(text: str) -> dict:
    """The parser's reading of trigger text:
    {text, rules: [{fields, items, sentence}], globals, understood, assumed, not_understood, suggestions,
     needs_connective, connective}. Empty text reads as no rules and nothing unread."""
    out = {"text": text, "rules": [], "globals": {}, "understood": [], "assumed": [], "not_understood": [],
           "suggestions": [], "needs_connective": False, "connective": None}
    if not text or not text.strip():
        return out
    result = parser.parse(text)
    out["understood"] = result.get("understood", [])
    out["assumed"] = result.get("assumed", [])
    out["not_understood"] = result.get("not_understood", [])
    out["suggestions"] = result.get("suggestions", [])
    draft = result.get("draft") or {}
    drafts = draft.get("rules") or []
    rules = _rules_of(result)
    skip_sports = _assumed(result, "no sport was named")
    skip_markets = _assumed(result, "no market was named") or _assumed(result, "no stat named")
    for i, rule in enumerate(rules):
        raw = drafts[i] if i < len(drafts) else rule
        fields = {}
        for key in _RULE_FIELDS:
            if key not in raw or raw[key] is None:
                continue
            if key == "sports" and skip_sports:
                continue
            if key == "markets" and skip_markets:
                continue
            if key == "side" and raw[key] == "either":
                continue
            fields[key] = raw[key]
        when = rule.get("when") or {"op": "all", "items": []}
        try:
            sentence = render.rule_sentence(rule) if result.get("spec") else ""
        except (KeyError, TypeError, IndexError):
            sentence = ""
        out["rules"].append({"fields": fields, "tree": when, "sentence": sentence})
    out["globals"] = {k: draft[k] for k in _GLOBAL_FIELDS if draft.get(k) is not None}
    # parser reads "or" as "and": ask when the words say or and more than one condition came out
    if len(out["rules"]) == 1 and has_or(text) and len(C.leaves(out["rules"][0]["tree"])) > 1:
        out["needs_connective"] = True
    return out


def read_exclude(clause: str) -> dict:
    """One skip clause: {text, status: ok | ambiguous | cant, tree?, either?, both?, reason?, mode}."""
    base = {"text": clause, "status": "cant", "reason": "", "mode": None}
    body = strip_skip_lead(clause)
    if not body:
        base["reason"] = "nothing to skip was named"
        return base
    result = parser.parse(body)
    unread = result.get("not_understood") or []
    drafts = (result.get("draft") or {}).get("rules") or []
    rules = _rules_of(result)
    if unread:
        base["reason"] = "these words could not be read: " + ", ".join(f"\"{u['text']}\"" for u in unread if u.get("text")) \
            if any(u.get("text") for u in unread) else (unread[0].get("reason") or "it could not be read")
        return base
    if len(rules) != 1:
        base["reason"] = "it reads as no rule or as several; give one skip rule per line"
        return base
    raw = drafts[0] if drafts else rules[0]
    tree = rules[0].get("when")
    if not tree or not tree.get("items"):
        base["reason"] = "it names no condition the rules can test (a sport, side or price belongs to the bet itself)"
        return base
    if raw.get("side") not in (None, "either"):
        base["reason"] = "a skip rule can test conditions, not which side is bet"
        return base
    if raw.get("price_min") is not None or raw.get("price_max") is not None:
        base["reason"] = "a skip rule cannot name a price range; set the price band in the odds question"
        return base
    if raw.get("line_min") is not None or raw.get("line_max") is not None:
        base["reason"] = "a skip rule cannot name a line range"
        return base
    flat = C.leaves(tree)
    inverted_leaves = []
    for leaf in flat:
        inv, why = C.invert_leaf(leaf)
        if inv is None:
            base["reason"] = f"\"{_leaf_text(leaf)}\": {why}"
            return base
        inverted_leaves.append(inv)
    explicit_or = has_or(body)
    if tree.get("op") == "any" and len(flat) == len(tree["items"]):
        # the parser only produces "any" for an explicit group; skipping when A or B means: not A and not B
        return {**base, "status": "ok", "tree": {"op": "all", "items": inverted_leaves}, "mode": "either"}
    if len(flat) == 1:
        return {**base, "status": "ok", "tree": {"op": "all", "items": inverted_leaves}, "mode": "single"}
    # two or more conditions in one skip clause: "skip when A and B" is read both ways by people
    return {**base, "status": "ambiguous", "mode": None, "explicit_or": explicit_or,
            "either": {"op": "all", "items": inverted_leaves}, "both": {"op": "any", "items": inverted_leaves}}


def _leaf_text(leaf: dict, kind: str = "ml_spread") -> str:
    try:
        return R.condition_text(leaf, kind)
    except Exception:  # noqa: BLE001 -- wording must never block a refusal
        return str(leaf.get("id"))
