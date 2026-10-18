"""The two answer shapes the desk uses, and their shape checks.

A REPORT (the four analysts, the bull, the bear) and a DECISION (the desk head, every persona).
Both are built from the analyst's own pieces so a reason, an evidence item and a declared
calculation mean exactly what they mean in `src/analyst`:

    reason        {claim, evidence: [{path, value}], derived: [...]}   (analyst MLB schema, prompt v3)
    derivation    {value, unit, op, inputs, note}                       (closed set, analyst.DERIVATION_*)

Football packets use the same shapes: `analyst.is_mlb_packet` is true for any packet with a `game`
block and no `bout`, so the football analyst already runs on the MLB schema, `case_against` and
`derived` included.

SHAPE IS NOT TRUTH
------------------
These functions only say whether an answer has the right keys and types, as the analyst's
`validate_output` does. Whether a path resolves, a number is the packet's, a name is known or a price
is real is the checker's (`src/analyst/critic.py`) and code's (`risk.py`), reported with a reason.
A shape error rejects the whole answer, so it is reserved for an answer that cannot be read.

Pure: no I/O, no clock, no network.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from src.analyst import analyst as analyst_mod

_STR = {"type": "string"}

# One reason with its `derived` list: what the analyst's MLB schema calls a reason.
REASON_SCHEMA: dict = copy.deepcopy(
    analyst_mod.MLB_RESPONSE_SCHEMA["properties"]["calls"]["items"]["properties"]["reasons"]["items"])
DERIVED_SCHEMA: dict = copy.deepcopy(analyst_mod.MLB_RESPONSE_SCHEMA["properties"]["summary_derived"])

FOCUS_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["slot_id", "selection"],
    "properties": {"slot_id": _STR, "selection": _STR},
}

MAX_FINDINGS = 8

REPORT_SCHEMA: dict = {
    "type": "object", "additionalProperties": False,
    "required": ["text", "text_derived", "findings", "focus"],
    "properties": {
        "text": _STR,
        "text_derived": copy.deepcopy(DERIVED_SCHEMA),
        "findings": {"type": "array", "minItems": 1, "maxItems": MAX_FINDINGS,
                     "items": copy.deepcopy(REASON_SCHEMA)},
        "focus": {"type": "array", "items": copy.deepcopy(FOCUS_SCHEMA)},
    },
}

TAKE_KEYS = ("slot_id", "selection", "verdict", "price", "book", "probability", "reasons",
             "case_against", "what_would_change_it")

DECISION_ITEM_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": list(TAKE_KEYS),
    "properties": {
        "slot_id": _STR, "selection": _STR,
        "verdict": {"type": "string", "enum": ["TAKE"]},
        "price": {"type": "integer"}, "book": _STR,
        "probability": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "reasons": {"type": "array", "minItems": 1, "items": copy.deepcopy(REASON_SCHEMA)},
        "case_against": copy.deepcopy(REASON_SCHEMA),
        "what_would_change_it": _STR,
    },
}

DECISION_SCHEMA: dict = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "summary_derived", "decisions"],
    "properties": {
        "summary": _STR,
        "summary_derived": copy.deepcopy(DERIVED_SCHEMA),
        "decisions": {"type": "array", "items": copy.deepcopy(DECISION_ITEM_SCHEMA)},
    },
}


def _words_error(label: str, text: Any, limits: Sequence[int]) -> list:
    if not isinstance(text, str):
        return [f"{label} must be a string"]
    n = analyst_mod.words(text)
    if not limits[0] <= n <= limits[1]:
        return [f"{label} is {n} words; it must be {limits[0]} to {limits[1]}"]
    return []


def _focus_errors(packet: Mapping, focus: Any) -> list:
    if not isinstance(focus, list):
        return ["focus must be a list"]
    errors = []
    markets = packet.get("markets") or {}
    for i, item in enumerate(focus):
        where = f"focus[{i}]"
        if not isinstance(item, Mapping) or set(item) != {"slot_id", "selection"}:
            errors.append(f"{where} needs exactly a slot_id and a selection")
            continue
        sid, sel = item["slot_id"], item["selection"]
        if sid not in markets:
            errors.append(f"{where}: {sid!r} is not a slot in the data")
        elif sel not in [o["selection"] for o in markets[sid]["options"]]:
            errors.append(f"{where}: {sel!r} is not one of {[o['selection'] for o in markets[sid]['options']]}")
    return errors


def report_shape_errors(output: Any, packet: Mapping, words: Sequence[int]) -> list:
    """Every way `output` fails the REPORT shape, as readable strings. Empty means the shape is right."""
    if not isinstance(output, Mapping):
        return ["the answer is not a JSON object"]
    errors: list = []
    extra = set(output) - set(REPORT_SCHEMA["properties"])
    if extra:
        errors.append(f"unexpected top-level keys: {sorted(extra)}")
    absent = [k for k in ("text", "findings", "focus") if k not in output]
    if absent:
        errors.append(f"missing {absent}")
    errors.extend(_words_error("text", output.get("text"), words))
    errors.extend(analyst_mod._derived_shape_errors("text", output.get("text_derived")))
    findings = output.get("findings")
    if not isinstance(findings, list) or not findings:
        errors.append("findings must be a non-empty list")
    else:
        if len(findings) > MAX_FINDINGS:
            errors.append(f"findings has {len(findings)} items; at most {MAX_FINDINGS}")
        for i, f in enumerate(findings):
            errors.extend(analyst_mod._reason_shape_errors(f"findings[{i}]", f, derived=True))
    if "focus" in output:
        errors.extend(_focus_errors(packet, output["focus"]))
    return errors


def decision_shape_errors(output: Any, packet: Mapping, words: Sequence[int]) -> list:
    """Every way `output` fails the DECISION shape. A selection that is not a listed option, a price
    that is not a quote and a TAKE the data cannot support are NOT shape errors: code and the checker
    strike them with a reason."""
    if not isinstance(output, Mapping):
        return ["the answer is not a JSON object"]
    errors: list = []
    extra = set(output) - set(DECISION_SCHEMA["properties"])
    if extra:
        errors.append(f"unexpected top-level keys: {sorted(extra)}")
    if "decisions" not in output:
        errors.append("missing ['decisions'] (an empty list passes the whole game)")
    errors.extend(_words_error("summary", output.get("summary"), words))
    errors.extend(analyst_mod._derived_shape_errors("summary", output.get("summary_derived")))
    decisions = output.get("decisions")
    if not isinstance(decisions, list):
        return errors + ["decisions must be a list"]
    markets = packet.get("markets") or {}
    seen: set = set()
    for i, d in enumerate(decisions):
        where = f"decisions[{i}]"
        if not isinstance(d, Mapping):
            errors.append(f"{where} is not an object")
            continue
        absent = [k for k in TAKE_KEYS if k not in d and k != "case_against"]
        if absent:
            errors.append(f"{where} is missing {absent}")
            continue
        extra = set(d) - set(TAKE_KEYS)
        if extra:
            errors.append(f"{where} has unexpected keys {sorted(extra)}")
        sid = d["slot_id"]
        where = f"decision {sid!r}"
        if sid not in markets:
            errors.append(f"{where}: not a slot in the data")
            continue
        if sid in seen:
            errors.append(f"{where}: more than one decision for this slot")
        seen.add(sid)
        if not isinstance(d["selection"], str):
            errors.append(f"{where}: selection must be a string")
        if d["verdict"] != "TAKE":
            errors.append(f"{where}: verdict must be \"TAKE\" (list only your TAKEs; a slot you do not "
                          "list is a PASS)")
        if isinstance(d["price"], bool) or not isinstance(d["price"], int):
            errors.append(f"{where}: price must be a whole number")
        if not isinstance(d["book"], str):
            errors.append(f"{where}: book must be a string")
        p = d["probability"]
        if not (isinstance(p, (int, float)) and not isinstance(p, bool) and 0.0 < p < 1.0):
            errors.append(f"{where}: probability must be a number between 0 and 1")
        if not isinstance(d["what_would_change_it"], str) or not d["what_would_change_it"].strip():
            errors.append(f"{where}: what_would_change_it must be a sentence")
        reasons = d["reasons"]
        if not isinstance(reasons, list) or not reasons:
            errors.append(f"{where}: reasons must be a non-empty list")
        else:
            for j, r in enumerate(reasons):
                errors.extend(analyst_mod._reason_shape_errors(f"{where}: reasons[{j}]", r, derived=True))
        if d.get("case_against") is None:
            errors.append(f"{where}: case_against is required for a TAKE")
        else:
            errors.extend(analyst_mod._reason_shape_errors(f"{where}: case_against", d["case_against"],
                                                           derived=True))
    return errors
