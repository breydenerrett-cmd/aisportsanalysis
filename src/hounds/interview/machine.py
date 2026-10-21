"""The interview state machine: take an answer, take a clarification, say what comes next.

The state is a plain JSON-able dict (see `new_state`) that the service stores. Nothing here touches a database, a
clock the caller did not hand in, or the network; the only outside call is the injected reader (extract.py), and
its result is checked before it is stored.

WHAT AN ANSWER IS
-----------------
  fields       the values the person set with the form controls, checked against the menu
  text_fields  values a reader (the parser, or Haiku) found in what they typed, checked against the same menu AND
               against the text itself: a model's candidate with no support in the person's words is ignored,
               because a hallucinated "NFL" would otherwise start an argument the person never had
  include      the parser's reading of "what has to be true" (and of nothing else)
  exclude      each skip rule, read and turned into its opposite, or refused with the reason
  unsupported  what the person asked for that the rules cannot run; refused: values the menu refused
  slots        the cleaned text exactly as typed (emails and phone numbers already removed)

THE ORDER IS FIXED. `next_step` is the first open clarification, else the first topic that is unanswered or missing a
required field, else the review. A reader may word the question; it cannot change that.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from src.hounds.interview import classify, derive as D
from src.hounds.interview import extract as X
from src.hounds.interview import fields as F
from src.hounds.interview import history as H
from src.hounds.interview import privacy
from src.hounds.interview import readtext as RT
from src.hounds.interview import topics as T

STATE_VERSION = 1
LOG_MAX = 80
TRIGGER_TOPICS = ("side",)        # only here are leftover words reported as "not understood"
STOP_FAILS = 3                    # after this many assistant failures in a row it is not asked again this interview
_NUM = re.compile(r"\d+(?:\.\d+)?")


class InterviewError(ValueError):
    """A refusal the caller can show: `code` is stable, the message is for people."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def new_state() -> dict:
    return {"v": STATE_VERSION, "status": "open", "answers": {}, "acks": [], "phrased": {}, "log": [],
            "assistant": "form", "assistant_note": "", "calls": 0, "fails": 0, "model": None, "cost_usd": 0.0}


# ---------------------------------------------------------------------------------------------------
# evidence: a reader's candidate must be in the person's words
# ---------------------------------------------------------------------------------------------------

# what the person's words must contain for a reader's candidate VALUE to count as said (one pattern per value, so "away"
# is not supported by a sentence that only says "home")
_EVIDENCE = {
    "side": {"home": r"\bhome\b", "away": r"\baway\b|\broad\b|\bvisitors?\b", "over": r"\bover\b", "under": r"\bunder\b",
             "either": r"\beither\b"},
    "role": {"favourite": r"favou?rites?|chalk", "underdog": r"underdogs?|\bdogs?\b", "any": r"\beither\b|\bany\b"},
    "timing": {"pregame": r"pre-?game|before the game|pre-?match|before (?:first pitch|kickoff|tip)", "live": r"\blive\b|in[- ]play",
               "both": r"\bboth\b"},
    "line_timing": {"lock": r"\block\b", "opening": r"\bopen", "closing": r"\bclos"},
    "markets": {"moneyline": r"money ?line|\bml\b", "spread": r"spread|run ?line|puck ?line", "total": r"\btotals?\b|over/under|\bo/u\b",
                "batter_hits": r"\bhits?\b", "batter_total_bases": r"total bases", "batter_home_runs": r"home runs?|homers?",
                "batter_rbis": r"\brbis?\b", "batter_runs_scored": r"runs scored", "batter_hits_runs_rbis": r"hits \+ runs|h\+r\+rbi",
                "pitcher_strikeouts": r"strikeouts?"},
}


def _supported(field: str, value: Any, text: str) -> bool:
    """Is a reader's candidate for `field` actually in `text`? Numbers must appear as digits; words as a keyword for
    that exact value."""
    low = text.lower()
    if field == "sports":
        if not isinstance(value, list):
            return False
        from src.hounds import user_spec
        if re.search(r"any sport|every sport|all sports|all leagues", low):
            return True
        hits = 0
        for code in value:
            label = user_spec.SPORT_LABELS.get(code, code).lower()
            if code.lower() in low or label in low:
                hits += 1
        return hits == len(value) and hits > 0
    if field in _EVIDENCE:
        table = _EVIDENCE[field]
        values = value if isinstance(value, list) else [value]
        return bool(values) and all(v in table and re.search(table[v], text, re.I) for v in values)
    if field in ("price_min", "price_max", "min_books", "max_bets_per_day", "lock_minutes"):
        return str(abs(int(value))) in set(_NUM.findall(text))
    if field == "stake_units":
        wanted = f"{value:g}"
        return wanted in set(_NUM.findall(text)) or (value == 1.0 and bool(re.search(r"\bone\b|\b1\b|\bflat\b", low)))
    return False


# words that say "skip" or "bet" without saying what: a clause that shares only these with the person's text shares nothing
_FILLER = frozenset("skip pass when then that this with from have has are the and not never only bet bets betting game games "
                    "team teams ignore avoid any every all your their they them its for but also".split())


def _content(phrase: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]{3,}", phrase.lower()) if w not in _FILLER]


def _mentioned(phrase: str, text: str) -> bool:
    """Did the person's words contain what a model says they asked for? A model that lists an unsupported idea nobody
    mentioned would put a request on the can't-automate list that was never made, so at least one content word (not
    "skip", "bets", "game"...) from its phrase has to be in what the person typed."""
    low = text.lower()
    return any(w in low for w in _content(phrase))


def _grounded(clause: str, text: str) -> bool:
    """A model's skip clause becomes a RULE, so every content word of it must be in the person's own words. A clause the
    person never said ("Skip day games", from a model, when they typed nothing about the time of day) is never added."""
    words = _content(clause)
    low = text.lower()
    return bool(words) and all(w in low for w in words)


def _numbers(text: str) -> set:
    return set(_NUM.findall(text or ""))


# ---------------------------------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------------------------------

def _lines(text: str, *, each: int, limit: int) -> List[str]:
    out = []
    for raw in str(text or "").split("\n"):
        line = " ".join(raw.split())[:each]
        if line:
            out.append(line)
    return out[:limit]


def _intake(topic: dict, payload: dict, *, today: date) -> dict:
    tid = topic["id"]
    allowed = T.field_names(tid)
    raw_fields = {k: v for k, v in (payload.get("fields") or {}).items() if k in allowed}
    unsupported: List[dict] = []
    if "markets" in raw_fields and isinstance(raw_fields["markets"], (list, tuple)):
        keep = []
        for m in raw_fields["markets"]:
            if isinstance(m, str) and m.startswith("x:"):
                row = T.UNSUPPORTED_MARKET_BY_ID.get(m[2:])
                if row:
                    unsupported.append({"code": row[0], "kind": classify.NO_MARKET, "text": row[1], "reason": row[2], "topic": tid})
            else:
                keep.append(m)
        raw_fields["markets"] = keep or None
    if raw_fields.get("price_any") is False:
        raw_fields.pop("price_any")
    clean, refused = F.check_fields(raw_fields, allowed=allowed)
    for r in refused:
        r["topic"] = tid
    ans: Dict[str, Any] = {"skipped": False, "fields": clean, "text_fields": {}, "slots": {}, "include": None, "exclude": [],
                           "data": [], "examples": None, "history": None, "unsupported": unsupported, "refused": refused,
                           "source": X.SOURCE_FORM}
    for name, role in T.text_slots(tid).items():
        control = next(c for c in T.get(tid)["controls"] if c["name"] == name)
        text = privacy.clean_text((payload.get("texts") or {}).get(name, ""), limit=control["max"])
        if not text:
            continue
        if role == "history":
            rows, rejected = H.parse(text, today=today)
            ans["history"] = {"rows": rows, "rejected": rejected, "summary": H.summary(rows, rejected)}
        elif role == "examples":
            ans["slots"][name] = text
        else:
            ans["slots"][name] = text
    if tid == "examples":
        ans["examples"] = {"trigger": _lines(ans["slots"].get("trigger_text", ""), each=T.EXAMPLE_MAX, limit=T.EXAMPLES_MAX),
                           "skip": _lines(ans["slots"].get("skip_text", ""), each=T.EXAMPLE_MAX, limit=T.EXAMPLES_MAX)}
    if tid == "data":
        wanted = payload.get("data") or []
        ans["data"] = [row[0] for row in T.DATA_CHOICES if row[0] in wanted]
    return ans


def _reader_slots(topic: dict, ans: dict) -> Dict[str, str]:
    roles = T.text_slots(topic["id"])
    return {n: t for n, t in ans["slots"].items() if roles.get(n) in ("include", "exclude", "notes")}


def _dedupe_unsupported(items: List[dict]) -> List[dict]:
    out: List[dict] = []
    for it in items:
        low = it["text"].lower()
        if any(low in o["text"].lower() or o["text"].lower() in low for o in out):
            continue
        out.append(it)
    return out


def _apply_reading(topic: dict, ans: dict, reading: X.Reading) -> None:
    tid = topic["id"]
    roles = T.text_slots(tid)
    include_raw = "\n".join(t for n, t in ans["slots"].items() if roles.get(n) == "include")
    include_text, prose_skips = RT.partition_text(include_raw)
    clauses: List[str] = []
    for n, t in ans["slots"].items():
        if roles.get(n) == "exclude":
            clauses.extend(X.split_clauses(t))
    clauses.extend(prose_skips)

    all_text = "\n".join(t for n, t in ans["slots"].items() if roles.get(n) in ("include", "exclude", "notes"))
    reading_fields = reading.fields if reading.source == X.SOURCE_AI else {}

    # the include reading: the person's own words first; a model's restatement only when it reads cleanly and keeps every number
    include = RT.read_include(include_text) if include_text else None
    used = "raw"
    if include is not None and reading.source == X.SOURCE_AI and reading.include_text and include["not_understood"]:
        restated = RT.read_include(reading.include_text)
        raw_n = len([x for r in include["rules"] for x in r["tree"].get("items", [])])
        new_n = len([x for r in restated["rules"] for x in r["tree"].get("items", [])])
        if (not restated["not_understood"] and restated["rules"] and _numbers(reading.include_text) == _numbers(include_text)
                and new_n >= raw_n):
            include, used = restated, "restated"
    if include is not None:
        include["used"] = used
        include["chosen"] = None
        ans["include"] = include

    # the skip rules: the person's lines, plus a model's clauses only when it invented no number
    seen = set()
    all_clauses = []
    for c in clauses:
        key = " ".join(c.lower().split())
        if key not in seen:
            seen.add(key)
            all_clauses.append(c)
    if reading.source == X.SOURCE_AI:
        known = _numbers(all_text)
        for c in reading.exclude_clauses:
            key = " ".join(c.lower().split())
            if key not in seen and _numbers(c) <= known and _grounded(c, all_text):
                seen.add(key)
                all_clauses.append(c)
    for c in all_clauses[:8]:
        ex = RT.read_exclude(c)
        ans["exclude"].append(ex)

    # a reader's candidate fields: menu-checked, and present in the person's words
    candidates = {k: v for k, v in reading_fields.items() if k in F.TEXT_FIELDS and v is not None}
    clean, refused = F.check_fields(candidates, allowed=F.TEXT_FIELDS)
    ans["text_fields"] = {k: v for k, v in clean.items() if _supported(k, v, all_text) and ans["fields"].get(k) != v}
    for r in refused:
        if _supported(r["field"], _raw_of(candidates, r["field"]), all_text):
            r["topic"] = tid
            ans["refused"].append(r)

    # what the language cannot run: the rule table is the floor, the model's list is added to it
    found = classify.find_unsupported(all_text, topic=tid)
    for u in reading.unsupported:
        if _mentioned(u["text"], all_text):
            found.append({"code": "", "kind": "", "text": u["text"], "reason": u["reason"], "topic": tid})
    ans["unsupported"] = _dedupe_unsupported(ans["unsupported"] + found)
    ans["source"] = reading.source
    if tid in TRIGGER_TOPICS or not ans.get("include"):
        return
    ans["include"]["not_understood_shown"] = ans["include"].get("not_understood", [])
    ans["include"]["not_understood"] = []


def _raw_of(candidates: dict, field: str) -> Any:
    return candidates.get(field)


# ---------------------------------------------------------------------------------------------------
# applying an answer
# ---------------------------------------------------------------------------------------------------

def _first_open(derived: dict) -> Optional[dict]:
    for t in derived["topics"]:
        if t["state"] in ("open", "missing"):
            return T.get(t["id"])
    return None


def describe_answer(topic: dict, ans: dict) -> str:
    """A short plain line for the chat: what the controls said, then what was typed."""
    if ans.get("skipped"):
        return "Skipped."
    parts: List[str] = []
    merged = {**ans.get("fields", {})}
    for control in topic["controls"]:
        name = control["name"]
        if name in merged:
            parts.append(f"{control['label']}: {D.show_value(name, merged[name])}")
    if ans.get("data"):
        names = [T.DATA_BY_ID[i][1] for i in ans["data"]]
        parts.append("Information used: " + "; ".join(names))
    for name, text in ans.get("slots", {}).items():
        parts.append(text.replace("\n", " / "))
    if ans.get("history"):
        s = ans["history"]["summary"]
        parts.append(f"{s['rows']} dated rows kept as {H.LABEL}")
    return ". ".join(parts) if parts else "Nothing added."


def _log(state: dict, role: str, text: str, **extra: Any) -> None:
    state["log"].append({"role": role, "text": text, **extra})
    del state["log"][:-LOG_MAX]


def apply_answer(state: dict, topic_id: str, payload: dict, *, reader=None, today: date) -> dict:
    """Store one answer (re-answering a topic replaces it) and return {"reading": Reading | None}."""
    try:
        topic = T.get(topic_id)
    except KeyError:
        raise InterviewError("unknown_topic", "That question is not part of the interview.")
    if state.get("status") != "open":
        raise InterviewError("closed", "This interview is finished.")
    state["acks"] = [a for a in state.get("acks", []) if not (topic_id == "scope" and a == "live_only")]
    state["phrased"].pop(topic_id, None)
    if payload.get("skip"):
        if not topic["skippable"]:
            raise InterviewError("not_skippable", f"{topic['title']} cannot be skipped.")
        state["answers"][topic_id] = {"skipped": True, "fields": {}, "text_fields": {}, "slots": {}, "include": None,
                                      "exclude": [], "data": [], "unsupported": [], "refused": [], "source": X.SOURCE_FORM}
        _log(state, "person", "Skipped.", topic=topic_id)
        return {"reading": None}
    ans = _intake(topic, payload, today=today)
    state["answers"][topic_id] = ans
    provisional = D.derive(state)
    nxt = _first_open(provisional)
    reading = None
    slots = _reader_slots(topic, ans)
    use_reader = reader is not None and state.get("fails", 0) < STOP_FAILS
    if use_reader:
        stored = {k: v for k, v in ans["fields"].items()}
        reading = reader.read(topic, slots, stored=stored, next_topic=nxt)
    else:
        reading = X.FormReader().read(topic, slots, stored={}, next_topic=nxt)
        if reader is not None:
            reading.fell_back, reading.why = True, "the assistant is not being asked again this interview"
    if reading.source == X.SOURCE_AI:
        state["calls"] = state.get("calls", 0) + 1
        state["fails"] = 0
        state["model"] = reading.model or state.get("model")
    elif reading.fell_back and use_reader:
        state["calls"] = state.get("calls", 0) + (1 if "budget" not in reading.why else 0)
        state["fails"] = state.get("fails", 0) + 1
    state["cost_usd"] = round(state.get("cost_usd", 0.0) + reading.cost_usd, 8)
    state["assistant"] = reading.source if not reading.fell_back else X.SOURCE_FORM
    state["assistant_note"] = ("The assistant is resting, so these are plain form questions. The rules and the result are the same."
                               if reading.fell_back and reader is not None else "")
    _apply_reading(topic, ans, reading)
    after = D.derive(state)
    _log(state, "person", describe_answer(topic, ans), topic=topic_id)
    if reading.follow_up and not after["clarifications"]:
        after_next = _first_open(after)
        if after_next is not None and nxt is not None and after_next["id"] == nxt["id"]:
            state["phrased"][after_next["id"]] = reading.follow_up
    log_next(state)
    return {"reading": reading}


# ---------------------------------------------------------------------------------------------------
# effects: how an option edits the stored answers
# ---------------------------------------------------------------------------------------------------

def _each_answer(state: dict):
    for ans in state["answers"].values():
        if not ans.get("skipped"):
            yield ans


def _set_everywhere(state: dict, field: str, value: Any) -> None:
    for ans in _each_answer(state):
        for bag in (ans["fields"], ans["text_fields"]):
            if field in bag:
                bag[field] = value
        inc = ans.get("include")
        if inc:
            if field in (inc.get("globals") or {}):
                inc["globals"][field] = value
            for rule in inc["rules"]:
                if field in rule["fields"]:
                    rule["fields"][field] = value


def _clear_everywhere(state: dict, field: str) -> None:
    for ans in _each_answer(state):
        for bag in (ans["fields"], ans["text_fields"]):
            bag.pop(field, None)
        inc = ans.get("include")
        if inc:
            (inc.get("globals") or {}).pop(field, None)
            for rule in inc["rules"]:
                rule["fields"].pop(field, None)
                if field == "role":
                    rule["tree"] = _without(rule["tree"], lambda leaf: leaf.get("id") == "role")


def _without(tree: dict, pred) -> dict:
    items = []
    for child in tree.get("items", []):
        if "items" in child:
            sub = _without(child, pred)
            if sub["items"]:
                items.append(sub)
        elif not pred(child):
            items.append(child)
    return {**tree, "items": items}


def apply_effects(state: dict, effects: List[dict]) -> None:
    for e in effects:
        op = e["op"]
        if op == "set_field":
            _set_everywhere(state, e["field"], e["value"])
        elif op == "clear_field":
            _clear_everywhere(state, e["field"])
        elif op == "clear_fields":
            for f in e["fields"]:
                _clear_everywhere(state, f)
        elif op == "unanswer":
            for t in e["topics"]:
                state["answers"].pop(t, None)
                state["phrased"].pop(t, None)
        elif op == "ack":
            if e["key"] not in state["acks"]:
                state["acks"].append(e["key"])
        elif op == "choose_rule":
            state["answers"][e["topic"]]["include"]["chosen"] = e["index"]
        elif op == "set_connective":
            state["answers"][e["topic"]]["include"]["connective"] = e["value"]
        elif op == "set_exclude_mode":
            state["answers"][e["topic"]]["exclude"][e["index"]]["mode"] = e["mode"]
        elif op == "drop_exclude":
            state["answers"][e["topic"]]["exclude"][e["index"]]["status"] = "dropped"
        elif op == "drop_include_item":
            inc = state["answers"][e["topic"]]["include"]
            for rule in inc["rules"]:
                rule["tree"] = _without(rule["tree"], lambda leaf, c=e["canon"]: D.canon(leaf) == c)
        else:
            raise InterviewError("bad_effect", "That choice cannot be applied.")


def apply_resolution(state: dict, clarification_id: str, option_id: str) -> None:
    if state.get("status") != "open":
        raise InterviewError("closed", "This interview is finished.")
    derived = D.derive(state)
    clar = next((c for c in derived["clarifications"] if c["id"] == clarification_id), None)
    if clar is None:
        raise InterviewError("not_open", "That question is not open any more.")
    option = next((o for o in clar["options"] if o["id"] == option_id), None)
    if option is None:
        raise InterviewError("bad_option", "That is not one of the choices.")
    apply_effects(state, option["effects"])
    _log(state, "person", option["label"], clarification=clarification_id)
    log_next(state)


# ---------------------------------------------------------------------------------------------------
# what to show
# ---------------------------------------------------------------------------------------------------

REVIEW_LINE = "That is everything. Check the summary below, then confirm to create your hound."


def log_next(state: dict) -> None:
    """Write the question that comes next into the chat log, so a reloaded interview reads as the conversation it was."""
    step = next_step(state)
    if step["kind"] == "topic":
        text, extra = step["assistant_prompt"] or step["prompt"], {"topic": step["topic"]}
    elif step["kind"] == "clarify":
        text, extra = step["clarification"]["question"], {"clarification": step["clarification"]["id"]}
    elif step["kind"] == "review":
        text, extra = REVIEW_LINE, {}
    else:
        return
    last = next((e for e in reversed(state["log"]) if e["role"] == "assistant"), None)
    if last is not None and last["text"] == text and state["log"][-1] is last:
        return
    cid = extra.get("clarification")
    if cid:
        # an open clarification is asked once in the chat, not again after every answer given while it waits
        asked = max((i for i, e in enumerate(state["log"]) if e["role"] == "assistant" and e.get("clarification") == cid), default=-1)
        settled = max((i for i, e in enumerate(state["log"]) if e["role"] == "person" and e.get("clarification") == cid), default=-1)
        if asked > settled:
            return
    _log(state, "assistant", text, **extra)


def public_clarification(clar: dict) -> dict:
    return {"id": clar["id"], "kind": clar["kind"], "question": clar["question"], "topics": clar["topics"],
            "options": [{"id": o["id"], "label": o["label"]} for o in clar["options"]]}


def _prefill(topic: dict, ans: Optional[dict]) -> dict:
    if not ans or ans.get("skipped"):
        return {"fields": {}, "texts": {}, "data": []}
    return {"fields": dict(ans.get("fields", {})), "texts": dict(ans.get("slots", {})), "data": list(ans.get("data", []))}


def topic_step(state: dict, topic_id: str, derived: dict) -> dict:
    topic = T.get(topic_id)
    ans = state["answers"].get(topic_id)
    status = next(s for s in derived["topics"] if s["id"] == topic_id)
    ids = [t["id"] for t in T.build_topics()]
    return {"kind": "topic", "topic": topic_id, "title": topic["title"], "prompt": topic["prompt"],
            "assistant_prompt": state["phrased"].get(topic_id), "controls": topic["controls"],
            "skippable": topic["skippable"], "required": list(topic["required"]), "needs": status["needs"],
            "index": ids.index(topic_id) + 1, "of": len(ids), "prefill": _prefill(topic, ans)}


def next_step(state: dict, derived: Optional[dict] = None) -> dict:
    derived = derived or D.derive(state)
    if state.get("status") != "open":
        return {"kind": "done"}
    if derived["clarifications"]:
        return {"kind": "clarify", "clarification": public_clarification(derived["clarifications"][0]),
                "remaining": len(derived["clarifications"])}
    open_topic = _first_open(derived)
    if open_topic is not None:
        return topic_step(state, open_topic["id"], derived)
    return {"kind": "review"}


def view(state: dict, edit: Optional[str] = None) -> dict:
    """What the page draws. `edit` names an answered topic to open again (its form, prefilled); the interview's own
    next step is unchanged and comes back as soon as that answer is saved."""
    derived = D.derive(state)
    done = sum(1 for t in derived["topics"] if t["state"] in ("done", "skipped"))
    step = next_step(state, derived)
    if edit and state.get("status") == "open":
        try:
            T.get(edit)
        except KeyError:
            raise InterviewError("unknown_topic", "That question is not part of the interview.")
        step = topic_step(state, edit, derived)
    return {"assistant": state.get("assistant", "form"), "assistant_note": state.get("assistant_note", ""),
            "progress": {"done": done, "total": len(derived["topics"]), "topics": derived["topics"]},
            "step": step, "cant_automate": derived["cant_automate"],
            "log": list(state.get("log", [])), "status": state.get("status", "open")}
