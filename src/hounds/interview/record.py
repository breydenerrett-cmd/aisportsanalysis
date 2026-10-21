"""The strategy record, its freeze hash and the confirmation summary.

WHAT THE HASH COVERS (AND WHY NOT MORE)
---------------------------------------
`freeze_hash` is the sha256 of the canonical JSON (sorted keys, no spaces) of `freeze_body`: the strategy as it will
run. It covers the rule fields of the spec (`user_spec.rule_fields`: rules, lock, daily cap, stake, ranking), the
conditions in and out, the can't-automate list, the missing-data policy, the examples and the stated disproof. It
leaves out what is not the strategy: the hound's name and tagline, the record's id, its status, the dates, the
author and consent, and the claimed history. So

  * the same confirmed answers give the same JSON and the same hash, whenever and by whoever they are confirmed,
    whatever words a model used to ask for them, and whatever order the conditions were said in;
  * renaming a hound does not change what it is;
  * adding claimed history later does not change the frozen rule.

`user_spec.spec_hash` already identifies a rule inside the hounds store; this hash additionally freezes the
statements around the rule that the person confirmed.

STATUS. A record is `draft` while it is being reviewed and `shadow` once the hound exists: a paper hound that bets
forward only, with `effective_date` the first day its picks count. Nothing before that day is ever back-filled.

MISSING OR STALE DATA IS A PASS, NOT A GUESS. These are the engine's own reasons (src/hounds/user_engine_v2.py
tallies them by name) in the words a person reads. The record carries them so the promise is frozen with the rule.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Dict, List, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds import user_engine as E
from src.hounds.english import render
from src.hounds.interview import conditions as C
from src.hounds.interview import derive as D
from src.hounds.interview import history as H
from src.hounds.interview import topics as T

RECORD_VERSION = 1
STATUS_DRAFT = "draft"
STATUS_SHADOW = "shadow"
PRICE_SOURCE = "the average price across every book quoting it, read at the lock"
SETTLEMENT = ("Win, loss or push at the average price recorded at the lock, one flat paper stake per bet. "
              "A game that is postponed or voided is a push. Nothing is graded at a better price than was recorded.")

# the engine's PASS reasons (src/hounds/user_engine_v2.py `skipped` keys), in plain words
PASS_REASONS = (
    ("no_board_at_lock", "No price board existed at the lock, so it passes."),
    ("board_too_old", f"The newest price board was too old at the lock (game bets: over {E.MAX_BOARD_AGE_MINUTES} minutes; "
                      f"player props: over {user_spec.MAX_PROP_BOARD_AGE_MINUTES} minutes), so it passes."),
    ("too_few_books", "Fewer books were quoting the price than the minimum, so it passes."),
    ("outside_price_band", "The average price was outside the price range, so it passes."),
    ("price_cap", f"The price was {user_spec.MAX_FAVOURITE_PRICE} or worse, which no hound ever bets, so it passes."),
    ("game_started", "The game had already started, so it passes."),
    ("hound_created_after_lock", "The hound was created after that game's lock, so it passes."),
)


def missing_data_handling(spec: Mapping) -> dict:
    used = sorted({leaf["id"] for rule in spec["rules"] for leaf in _leaves_of(rule.get("when"))})
    reasons = [{"code": code, "text": text} for code, text in PASS_REASONS]
    for cid in used:
        cond = R.BY_ID[cid]
        reasons.append({"code": f"unknown_{cid}", "text": f"The fact \"{cond.label}\" was missing for that game, so it passes."})
    return {"policy": "pass",
            "summary": ("If any fact a rule needs is missing or stale at the lock, the hound passes on that game and records "
                        "the reason. It never guesses a fact and never bets to fill a quota."),
            "reasons": reasons, "conditions_used": used}


def required_data_freshness() -> dict:
    return {"game_board_max_age_minutes": E.MAX_BOARD_AGE_MINUTES,
            "prop_board_max_age_minutes": user_spec.MAX_PROP_BOARD_AGE_MINUTES,
            "as_of": "the lock; nothing newer is ever used"}


def _leaves_of(tree: Optional[Mapping]) -> List[dict]:
    return C.leaves(tree) if tree else []


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _inclusion(spec: Mapping, derived: Mapping) -> List[dict]:
    kind = R.market_kind(spec["rules"][0]["markets"][0])
    out = []
    for entry in derived["items"]:
        if entry["source"][0] == "exclude":
            continue
        cond = entry["condition"]
        text = R.tree_text(cond, kind) if "items" in cond else R.condition_text(cond, kind)
        out.append({"text": text, "condition": cond})
    return sorted(out, key=lambda x: canonical(x["condition"]))


def _exclusion(spec: Mapping, derived: Mapping, state: Mapping) -> List[dict]:
    kind = R.market_kind(spec["rules"][0]["markets"][0])
    out = []
    for entry in derived["items"]:
        src = entry["source"]
        if src[0] != "exclude":
            continue
        ex = state["answers"][src[1]]["exclude"][src[2]]
        cond = entry["condition"]
        meaning = R.tree_text(cond, kind) if "items" in cond else R.condition_text(cond, kind)
        out.append({"text": ex["text"], "rule": cond, "plain": f"Bets only when {meaning}"})
    return sorted(out, key=lambda x: canonical(x["rule"]))


def _cant(derived: Mapping) -> List[dict]:
    return [{"topic": c["topic"], "text": c["text"], "reason": c["reason"]} for c in derived["cant_automate"]]


def _examples(state: Mapping) -> dict:
    ex = (state["answers"].get("examples") or {}).get("examples") or {"trigger": [], "skip": []}
    return {"would_bet": list(ex["trigger"]), "would_not_bet": list(ex["skip"])}


def _disproof(state: Mapping) -> Optional[str]:
    ans = state["answers"].get("disprove") or {}
    return (ans.get("slots") or {}).get("text") or None


def _publish(state: Mapping, fields: Mapping) -> dict:
    return {"permitted": bool(fields.get("publish_ok", False)), "attribution": fields.get("attribution", "anonymous"),
            "attribution_name": fields.get("attribution_name") if fields.get("attribution") == "named" else None}


def _provenance(state: Mapping, interview_id: str) -> dict:
    ai_used = state.get("calls", 0) > 0 and state.get("model")
    mode = "form" if not state.get("model") else ("ai" if state.get("assistant") == "ai" else "mixed")
    return {"source": "member_interview", "interview_id": interview_id, "ai_assisted": bool(ai_used),
            "ai_model": state.get("model") if ai_used else None, "mode": mode,
            "history_claimed": bool((state["answers"].get("history") or {}).get("history"))}


def build_record(state: Mapping, derived: Mapping, spec: Mapping, *, record_id: str, interview_id: str,
                 owner_display: str, status: str, effective_date: Optional[date]) -> dict:
    fields = derived["fields"]
    publish = _publish(state, fields)
    if publish["attribution"] == "named" and publish["attribution_name"]:
        author = publish["attribution_name"]
    elif publish["attribution"] == "kennel":
        author = owner_display
    else:
        author = "Anonymous"
    record = {
        "record_version": RECORD_VERSION, "id": record_id, "version": 1,
        "author": {"display": author, "attribution": publish["attribution"]},
        "provenance": _provenance(state, interview_id), "status": status,
        "sports": list(spec["sports"]), "markets": list(spec["markets"]), "pregame_or_live": "pregame",
        "spec": dict(spec),
        "inclusion_conditions": _inclusion(spec, derived), "exclusion_conditions": _exclusion(spec, derived, state),
        "cant_automate": _cant(derived),
        "price_source": PRICE_SOURCE,
        "timing": {"lock_minutes": spec["lock_minutes"], "line_timing": "lock"},
        "max_picks_per_day": spec["max_bets_per_day"], "unit_size": spec["stake_units"],
        "required_data_freshness": required_data_freshness(),
        "handling_missing_data": missing_data_handling(spec),
        "settlement_rules": SETTLEMENT,
        "examples": _examples(state), "disproof": _disproof(state),
        "publish": publish,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "paper_only": True, "not_advice": user_spec.NOT_ADVICE,
    }
    record["freeze_hash"] = freeze_hash(record)
    return record


def freeze_body(record: Mapping) -> dict:
    return {
        "record_version": record["record_version"],
        "spec": user_spec.rule_fields(record["spec"]),
        "sports": record["sports"], "markets": record["markets"], "pregame_or_live": record["pregame_or_live"],
        "inclusion_conditions": record["inclusion_conditions"], "exclusion_conditions": record["exclusion_conditions"],
        "cant_automate": record["cant_automate"], "price_source": record["price_source"], "timing": record["timing"],
        "max_picks_per_day": record["max_picks_per_day"], "unit_size": record["unit_size"],
        "required_data_freshness": record["required_data_freshness"],
        "handling_missing_data": record["handling_missing_data"], "settlement_rules": record["settlement_rules"],
        "examples": record["examples"], "disproof": record["disproof"],
    }


def freeze_hash(record: Mapping) -> str:
    return hashlib.sha256(canonical(freeze_body(record)).encode("utf-8")).hexdigest()


def summary_lines(record: Mapping) -> List[str]:
    """The plain-English summary a person reads before confirming. Every sentence comes from the validated spec or
    from the person's own statements; none of it says the strategy wins."""
    spec = record["spec"]
    lines = list(render.rule_sentences(spec)) + list(render.global_sentences(spec))
    for ex in record["exclusion_conditions"]:
        lines.append(f"Your pass rule, \"{ex['text']}\", is part of the conditions above.")
    lines.append(record["handling_missing_data"]["summary"])
    lines.append("It bets forward only, on paper, from the day you confirm. Nothing earlier is counted.")
    return lines


def review(state: Mapping, derived: Mapping, spec: Mapping, *, record_id: str, interview_id: str, owner_display: str,
           today: date) -> dict:
    record = build_record(state, derived, spec, record_id=record_id, interview_id=interview_id, owner_display=owner_display,
                          status=STATUS_DRAFT, effective_date=today)
    hist = (state["answers"].get("history") or {}).get("history")
    return {"record": record, "freeze_hash": record["freeze_hash"], "summary": summary_lines(record),
            "cant_automate": record["cant_automate"], "skips": [e["text"] for e in record["exclusion_conditions"]],
            "claimed_history": hist["summary"] if hist else None, "name": spec["name"], "tagline": spec["tagline"],
            "effective_date": record["effective_date"], "paper_only": True, "not_advice": user_spec.NOT_ADVICE}
