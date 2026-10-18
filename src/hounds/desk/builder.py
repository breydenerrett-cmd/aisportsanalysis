"""Build the request a stage's subagent answers.

A request file has the shape of the analyst pilot's `request.json`, the body the API would have been
sent: `model`, `max_tokens`, `system` (the role's text), `output_config` (the schema) and one user message.
A subagent is handed that one file and nothing else, so what is in it is everything the stage knows.

WHAT A REQUEST CONTAINS, AND NOTHING ELSE
-----------------------------------------
* the role's system text (`roles.py`);
* the frozen data, exactly the analyst packet (`analyst.packet_json`), once;
* for a stage with `needs` only, the upstream stages' CHECKED material: a report's text if the checker
  passed it and the findings the checker did not strike, never a struck claim and never a withheld text;
* the slot ids, so the writer knows what the menu covers;
* for a re-answer only, the checker's rejection lines, word for word, in the analyst's own repair wording.

A first-wave request (the four analysts and every persona) therefore holds the packet and the role text
and nothing else; a test pins that, because "the writer saw only this" is what makes the answer
attributable.

Pure: no I/O, no clock, no network.
"""

from __future__ import annotations

import json
from typing import Mapping, Optional, Sequence

from src.analyst import analyst as analyst_mod
from src.hounds.desk import roles

DATA_HEADER = "THE DATA (JSON). Paths in your evidence start at its top-level keys.\n"
REPORTS_HEADER = ("\n\nCHECKED MATERIAL FROM THE DESK. Each item below was checked against the data; a "
                  "claim the checker struck is not shown, and a text that failed the checker is withheld.\n")

# Estimated size of one upstream item in a later stage's request, used only for the pre-answer token
# estimate (the real size is known once an answer exists). A report is at most 220 words of text and
# 8 findings; at JSON's ~3 characters a token this is a deliberately high figure.
UPSTREAM_CHARS_ESTIMATE = 4500

# Output sizes, in tokens, by stage family. Estimates from the schema's limits, NOT measurements: nothing has
# been answered yet. They exist so `prepare` can say what a game costs before a session is spent on it.
OUTPUT_TOKENS_ESTIMATE = {"report": 1800, "case": 2000, "head": 3000, "persona": 2400}


def _material_block(stage: str, material: Mapping) -> str:
    title = material.get("title") or stage
    body = json.dumps(material, separators=(",", ":"), sort_keys=False)
    return f"\n--- {title} ({stage}) ---\n{body}"


def user_message(packet: Mapping, role: "roles.Role", upstream: Optional[Mapping] = None,
                 repair: Optional[Sequence[str]] = None) -> str:
    """The one user message of a stage's request."""
    slots = [s["slot_id"] for s in packet.get("slots", [])]
    text = DATA_HEADER + analyst_mod.packet_json(packet)
    if role.needs:
        text += REPORTS_HEADER
        for stage in role.needs:
            material = (upstream or {}).get(stage)
            if material is None:
                text += (f"\n--- {roles.ROLES[stage].title} ({stage}) ---\n"
                         "no checked answer was produced for this stage")
            else:
                text += _material_block(stage, material)
    if role.kind == roles.KIND_REPORT:
        task = "Write your report now."
    else:
        task = "Make your decision now. List only your TAKEs; a slot you do not list is a PASS."
    text += "\n\n" + task + " The market slots in the data are: " + ", ".join(slots) + "."
    if repair:
        text += ("\n\nYour previous answer was rejected for these reasons. "
                 "Fix them and answer again:\n- " + "\n- ".join(list(repair)[:12]))
    return text


def build_request(packet: Mapping, role: "roles.Role", cfg: Mapping, upstream: Optional[Mapping] = None,
                  repair: Optional[Sequence[str]] = None) -> dict:
    """The exact JSON body that would be POSTed for this stage. No key, no network."""
    return {
        "model": cfg["model"],
        "max_tokens": int(cfg["max_output_tokens"]),
        "system": role.system,
        "output_config": {"format": {"type": "json_schema", "schema": role.schema()},
                          "effort": cfg["effort"]},
        "messages": [{"role": "user", "content": user_message(packet, role, upstream, repair)}],
    }


def estimate_input_tokens(packet: Mapping, role: "roles.Role") -> int:
    """High estimate of a stage's request tokens before any upstream answer exists: the request with its
    upstream items replaced by `UPSTREAM_CHARS_ESTIMATE` characters each."""
    base = user_message(packet, roles.Role(role.stage, role.kind, role.title, role.system, needs=(),
                                           hound_id=role.hound_id, words=role.words))
    extra = "x" * (UPSTREAM_CHARS_ESTIMATE * len(role.needs))
    return analyst_mod.estimate_tokens(role.system, base, extra, json.dumps(role.schema()))


def output_estimate(role: "roles.Role") -> int:
    if role.stage in roles.ANALYST_STAGES:
        return OUTPUT_TOKENS_ESTIMATE["report"]
    if role.stage in ("bull", "bear"):
        return OUTPUT_TOKENS_ESTIMATE["case"]
    if role.stage == "head":
        return OUTPUT_TOKENS_ESTIMATE["head"]
    return OUTPUT_TOKENS_ESTIMATE["persona"]
