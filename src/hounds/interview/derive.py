"""Answers in, everything the interview knows out: a pure function of the stored answers.

NOTHING HERE CALLS A MODEL, READS A CLOCK OR TOUCHES A DATABASE. The state machine stores what each answer said
(already checked against the menu); `derive` merges those answers into one picture and reports, deterministically:

  fields         the merged scalar fields (sports, markets, side, price band, limits, stake ...)
  items          the conditions that must hold, each with where it came from, in a canonical order
  cant_automate  everything asked for that the rules cannot run, with the reason; nothing is dropped
  clarifications questions that MUST be answered before the interview can finish (see below)
  missing        the topics still to ask
  spec           the user_spec version-2 spec, validated, or None; problems carries the menu's refusals

That is what makes "the same confirmed answers give the same spec JSON and hash" true: the model's wording and the
order the person phrased things in never reach this function, only the checked values do, and conditions are
sorted into a canonical order before the rule is built.

CLARIFICATIONS, NOT PRIORITY
----------------------------
Two answers that disagree are never settled by "the later one wins". Each kind below becomes a question with
options, and the interview cannot finish while one is open:

  conflict:<field>      two answers gave different values for the same field
  live_only             the whole strategy is live betting, which a hound cannot do
  side_markets          a side that cannot apply to the markets chosen (the over on a moneyline)
  role_price            "underdogs" with a price band that only holds favourites, or the reverse
  price_order           a price range written backwards
  price_any_band        "any price" and a price range at once
  two_rules:<topic>     the text describes more than one separate strategy
  connective:<topic>    "or" between conditions: any one, or all of them?
  exclude:<topic>:<i>   a skip rule with several conditions: skip on either, or only on both?
  impossible            two required conditions that can never both be true (rest at least 3 and less than 2)
  refused:<hash>        the menu itself refused the combination; the question says which answer to change

Each option carries `effects`, small edits the machine applies to the stored answers (machine.apply_effects).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import render
from src.hounds.interview import conditions as C
from src.hounds.interview import fields as F
from src.hounds.interview import topics as T

PLACEHOLDER_NAME = "Interview hound"
# "no opinion" values: they never contradict a stated one
WEAK = {"side": "either", "role": "any"}
LIVE_REASON = ("Live and in-game bets are not available. A hound locks 60 to 180 minutes before the start and "
               "uses only what was known by then.")
LINE_TIMING_REASON = ("A hound is priced at its lock time, as the average across books. It cannot take the opening "
                      "or the closing line.")
KIND_NOUN = {"ml_spread": "the game bet", "total": "the game total", "prop": "the player prop"}


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def short_id(*parts: Any) -> str:
    return hashlib.sha256("|".join(canon(p) for p in parts).encode("utf-8")).hexdigest()[:8]


def show_value(field: str, value: Any) -> str:
    """A field value as the person reads it."""
    if field in ("price_min", "price_max"):
        return render.fmt_price(int(value))
    if field in ("sports",):
        return user_spec.sports_phrase(value)
    if field == "markets":
        return ", ".join(R.MARKET_LABELS.get(m, m) for m in value)
    if field == "stake_units":
        return f"{value:g} paper unit" + ("" if value == 1 else "s")
    if field == "lock_minutes":
        return f"{value} minutes before the start"
    if field == "max_bets_per_day":
        return f"{value} a day"
    if field == "min_books":
        return f"{value} book" + ("" if value == 1 else "s")
    if field == "side":
        return R.SIDE_LABELS.get(value, str(value))
    if field == "timing":
        return {"pregame": "before the game", "live": "live", "both": "before the game and live"}.get(value, str(value))
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


FIELD_LABELS = {"sports": "Sports", "markets": "Bets", "timing": "When it bets", "side": "Side", "role": "Favourite or underdog",
                "price_min": "Shortest price", "price_max": "Longest price", "min_books": "Books quoting it",
                "max_bets_per_day": "Bets a day", "lock_minutes": "Lock time", "stake_units": "Stake"}


# ---------------------------------------------------------------------------------------------------
# collecting
# ---------------------------------------------------------------------------------------------------

def _include_choice(inc: Optional[dict]) -> Optional[int]:
    """Which parsed rule of an include reading the hound follows: the only one, the chosen one, or None."""
    if not inc or not inc.get("rules"):
        return None
    if len(inc["rules"]) == 1:
        return 0
    chosen = inc.get("chosen")
    return chosen if isinstance(chosen, int) and 0 <= chosen < len(inc["rules"]) else None


def _assertions(answers: Dict[str, dict]) -> Dict[str, List[Tuple[str, Any]]]:
    out: Dict[str, List[Tuple[str, Any]]] = {}

    def add(field: str, value: Any, topic: str) -> None:
        out.setdefault(field, []).append((topic, value))

    for tid in T.topic_ids():
        ans = answers.get(tid)
        if not ans or ans.get("skipped"):
            continue
        for f, v in (ans.get("fields") or {}).items():
            add(f, v, tid)
        for f, v in (ans.get("text_fields") or {}).items():
            add(f, v, tid)
        inc = ans.get("include")
        if inc:
            for f, v in (inc.get("globals") or {}).items():
                add(f, v, tid)
            idx = _include_choice(inc)
            if idx is not None:
                for f, v in inc["rules"][idx]["fields"].items():
                    add(f, v, tid)
    return out


def _distinct(field: str, pairs: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    """The distinct values asserted for a field (first topic that said each), weak values dropped when a strong one exists."""
    seen: Dict[str, Tuple[str, Any]] = {}
    for topic, value in pairs:
        key = canon(sorted(value)) if isinstance(value, list) else canon(value)
        seen.setdefault(key, (topic, value))
    values = list(seen.values())
    weak = WEAK.get(field)
    strong = [tv for tv in values if tv[1] != weak]
    return strong if strong else values


def _items(answers: Dict[str, dict], role: Optional[str]) -> List[Tuple[dict, tuple]]:
    """Every condition the hound requires, with its source: ("role",), ("include", topic) or ("exclude", topic, index)."""
    found: List[Tuple[dict, tuple]] = []
    if role in ("favourite", "underdog"):
        found.append(({"id": "role", "value": role}, ("role",)))
    for tid in T.topic_ids():
        ans = answers.get(tid)
        if not ans or ans.get("skipped"):
            continue
        inc = ans.get("include")
        idx = _include_choice(inc)
        if idx is not None:
            top = list(inc["rules"][idx]["tree"].get("items") or [])
            if inc.get("needs_connective") and inc.get("connective") == "any" and len(top) > 1:
                found.append(({"op": "any", "items": top}, ("include", tid)))
            else:
                found.extend((it, ("include", tid)) for it in top)
        for i, ex in enumerate(ans.get("exclude") or []):
            tree = None
            if ex.get("status") == "ok":
                tree = ex["tree"]
            elif ex.get("status") == "ambiguous" and ex.get("mode") in ("either", "both"):
                tree = ex[ex["mode"]]
            if tree is None:
                continue
            if tree["op"] == "all":
                found.extend((it, ("exclude", tid, i)) for it in tree["items"])
            else:
                found.append((tree, ("exclude", tid, i)))
    # the same condition said twice (a form choice and a sentence) is one condition; the first source keeps it
    seen: set = set()
    unique: List[Tuple[dict, tuple]] = []
    for item, src in found:
        key = canon(item)
        if key not in seen:
            seen.add(key)
            unique.append((item, src))
    return unique


def _cant_items(answers: Dict[str, dict], merged: Dict[str, Any], acks: set) -> List[dict]:
    out: List[dict] = []

    def add(topic: str, text: str, reason: str, code: str = "") -> None:
        out.append({"id": short_id(topic, text.lower(), code), "topic": topic, "text": text, "reason": reason, "code": code})

    for tid in T.topic_ids():
        ans = answers.get(tid)
        if not ans or ans.get("skipped"):
            continue
        for u in ans.get("unsupported") or []:
            add(tid, u["text"], u["reason"], u.get("code", ""))
        for r in ans.get("refused") or []:
            add(tid, f"{FIELD_LABELS.get(r['field'], r['field'])}: {r['value']}", f"the menu does not allow it: {r['reason']}", "refused")
        inc = ans.get("include")
        if inc:
            for nu in inc.get("not_understood") or []:
                if nu.get("text"):
                    add(tid, nu["text"], nu.get("reason") or "not something the rules can read yet", "not_understood")
            idx = _include_choice(inc)
            if len(inc.get("rules") or []) > 1 and idx is not None:
                for j, rule in enumerate(inc["rules"]):
                    if j != idx:
                        add(tid, rule["sentence"] or "a second strategy",
                            "It was described as a separate strategy. Build it as its own hound.", "second_strategy")
        for ex in ans.get("exclude") or []:
            if ex.get("status") == "cant":
                add(tid, ex["text"], "this skip rule could not be turned into a rule: " + (ex.get("reason") or "not on the menu"),
                    "skip_rule")
        for did in ans.get("data") or []:
            row = T.DATA_BY_ID.get(did)
            if row and not row[2]:
                add(tid, row[1], row[3], "data_" + did)
    if merged.get("timing") in ("live", "both"):
        add("scope", "Live betting", LIVE_REASON, "live")
    if merged.get("line_timing") in ("opening", "closing"):
        add("price", f"The {merged['line_timing']} line", LINE_TIMING_REASON, "line_timing")
    seen, unique = set(), []
    for item in out:
        key = (item["code"] if item["code"] in ("live", "line_timing") else item["id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    order = {t: i for i, t in enumerate(T.topic_ids())}
    unique.sort(key=lambda x: (order.get(x["topic"], 99), x["text"].lower(), x["id"]))
    return unique


# ---------------------------------------------------------------------------------------------------
# clarifications
# ---------------------------------------------------------------------------------------------------

def _opt(oid: str, label: str, *effects: dict) -> dict:
    return {"id": oid, "label": label, "effects": list(effects)}


def _clar(cid: str, kind: str, question: str, options: List[dict], topics: List[str]) -> dict:
    return {"id": cid, "kind": kind, "question": question, "options": options, "topics": topics}


def _kind_of_markets(markets: List[str]) -> List[str]:
    return sorted({R.market_kind(m) for m in markets})


def _item_label(item: dict, src: tuple, answers: Dict[str, dict], kind: str) -> str:
    if src[0] == "exclude":
        ex = (answers.get(src[1]) or {}).get("exclude", [])[src[2]]
        return f"Skip: {ex['text']}"
    if src[0] == "role":
        return f"Only {item['value']}s"
    try:
        text = R.tree_text({"op": "all", "items": [item]}, kind) if "items" not in item else R.tree_text(item, kind)
    except Exception:  # noqa: BLE001
        text = str(item.get("id"))
    return f"Bet only when {text}"


def _drop_effect(item: dict, src: tuple) -> dict:
    if src[0] == "role":
        return {"op": "clear_field", "field": "role"}
    if src[0] == "exclude":
        return {"op": "drop_exclude", "topic": src[1], "index": src[2]}
    return {"op": "drop_include_item", "topic": src[1], "canon": canon(item)}


def _clarifications(answers: Dict[str, dict], merged: Dict[str, Any], conflicts: Dict[str, List[Tuple[str, Any]]],
                    items: List[Tuple[dict, tuple]], acks: set) -> List[dict]:
    out: List[dict] = []
    # conflicting answers
    for field in sorted(conflicts, key=lambda f: (F.KNOWN.index(f) if f in F.KNOWN else 99, f)):
        values = conflicts[field]
        label = FIELD_LABELS.get(field, field)
        opts = [_opt(f"v{i}", f"{show_value(field, v)}", {"op": "set_field", "field": field, "value": v})
                for i, (_t, v) in enumerate(values)]
        said = "; ".join(f"{T.get(t)['title']}: {show_value(field, v)}" for t, v in values)
        out.append(_clar(f"conflict:{field}", "conflict",
                         f"Two of your answers disagree about {label.lower()} ({said}). Which one do you mean?", opts,
                         sorted({t for t, _ in values})))
    # live only
    if merged.get("timing") == "live" and "live_only" not in acks:
        out.append(_clar("live_only", "live_only",
                         "A hound only bets before the game starts. It locks 60 to 180 minutes ahead and uses only what was known by then. "
                         "Do you want the before-the-game version of this strategy? The live part stays on the can't-automate list.",
                         [_opt("pregame", "Yes, build the before-the-game version", {"op": "ack", "key": "live_only"}),
                          _opt("redo", "No, I'll change my answers", {"op": "unanswer", "topics": ["scope"]})], ["scope"]))
    # side vs markets
    side, markets = merged.get("side"), merged.get("markets")
    if side and markets:
        bad = [m for m in markets if side not in R.sides_for([R.market_kind(m)])]
        if bad:
            good = [m for m in markets if m not in bad]
            opts = []
            if good:
                opts.append(_opt("markets", f"Keep {show_value('side', side).lower()} and bet only {show_value('markets', good)}",
                                 {"op": "set_field", "field": "markets", "value": good}))
            opts.append(_opt("either", "Let the conditions decide the side", {"op": "set_field", "field": "side", "value": "either"}))
            opts.append(_opt("redo", "Change the side", {"op": "unanswer", "topics": ["side"]}))
            out.append(_clar("side_markets", "side_markets",
                             f"{R.SIDE_LABELS[side]} does not apply to {show_value('markets', bad)}. What should change?",
                             opts, ["scope", "side"]))
    # role vs price band (moneyline only: a spread price is near -110 for either side)
    role = merged.get("role")
    pmin, pmax = merged.get("price_min"), merged.get("price_max")
    if role in ("favourite", "underdog") and markets and "moneyline" in markets and not merged.get("price_any"):
        clash = (role == "underdog" and pmax is not None and pmax <= -130) or (role == "favourite" and pmin is not None and pmin >= 105)
        if clash:
            word = "underdogs" if role == "underdog" else "favourites"
            out.append(_clar("role_price", "role_price",
                             f"You asked for {word}, but the price range {show_value('price_min', pmin) if pmin is not None else 'any'} to "
                             f"{show_value('price_max', pmax) if pmax is not None else 'any'} only holds the other kind on a moneyline. What should change?",
                             [_opt("keep_role", f"Keep {word}; I'll set the prices again",
                                   {"op": "clear_fields", "fields": ["price_min", "price_max", "price_any"]}, {"op": "unanswer", "topics": ["price"]}),
                              _opt("keep_prices", "Keep the price range; drop the favourite/underdog condition", {"op": "clear_field", "field": "role"})],
                             ["side", "price"]))
    # price order
    if pmin is not None and pmax is not None and user_spec.price_decimal(pmin) > user_spec.price_decimal(pmax):
        out.append(_clar("price_order", "price_order",
                         f"The shortest price ({render.fmt_price(pmin)}) is longer than the longest ({render.fmt_price(pmax)}). Which way round do you mean?",
                         [_opt("swap", f"{render.fmt_price(pmax)} to {render.fmt_price(pmin)}",
                               {"op": "set_field", "field": "price_min", "value": pmax}, {"op": "set_field", "field": "price_max", "value": pmin}),
                          _opt("redo", "Let me enter them again", {"op": "clear_fields", "fields": ["price_min", "price_max"]},
                               {"op": "unanswer", "topics": ["price"]})], ["price"]))
    # any price and a range
    if merged.get("price_any") and (pmin is not None or pmax is not None):
        out.append(_clar("price_any_band", "price_any_band", "You chose any price and also gave a price range. Which do you mean?",
                         [_opt("range", "Only the range", {"op": "clear_field", "field": "price_any"}),
                          _opt("any", "Any price", {"op": "clear_fields", "fields": ["price_min", "price_max"]})], ["price"]))
    # per-answer ambiguities
    for tid in T.topic_ids():
        ans = answers.get(tid)
        if not ans or ans.get("skipped"):
            continue
        inc = ans.get("include")
        if inc and len(inc.get("rules") or []) > 1 and _include_choice(inc) is None:
            opts = [_opt(f"r{i}", rule["sentence"] or "This rule", {"op": "choose_rule", "topic": tid, "index": i})
                    for i, rule in enumerate(inc["rules"])]
            out.append(_clar(f"two_rules:{tid}", "two_rules",
                             "That reads as more than one separate strategy. A hound follows one. Which one should this hound follow? "
                             "The others are kept on the can't-automate list so you can build them as their own hounds.", opts, [tid]))
        if inc and inc.get("needs_connective") and inc.get("connective") is None and _include_choice(inc) is not None:
            out.append(_clar(f"connective:{tid}", "connective",
                             "You used \"or\" between conditions. Must all of them be true to bet, or is any one enough?",
                             [_opt("all", "All of them must be true", {"op": "set_connective", "topic": tid, "value": "all"}),
                              _opt("any", "Any one is enough", {"op": "set_connective", "topic": tid, "value": "any"})], [tid]))
        for i, ex in enumerate(ans.get("exclude") or []):
            if ex.get("status") == "ambiguous" and ex.get("mode") is None:
                out.append(_clar(f"exclude:{tid}:{i}", "exclude",
                                 f"\"{ex['text']}\" names several conditions. Skip when any one of them is true, or only when all of them are true at once?",
                                 [_opt("either", "Skip when any one is true", {"op": "set_exclude_mode", "topic": tid, "index": i, "mode": "either"}),
                                  _opt("both", "Skip only when all are true together", {"op": "set_exclude_mode", "topic": tid, "index": i, "mode": "both"})],
                                 [tid]))
    # impossible together
    kinds = _kind_of_markets(markets or []) or ["ml_spread"]
    leafy = [(it, src) for it, src in items if "items" not in it]
    reported = set()
    for a in range(len(leafy)):
        for b in range(a + 1, len(leafy)):
            (x, sx), (y, sy) = leafy[a], leafy[b]
            if x.get("id") != y.get("id"):
                continue
            bad = C.empty_together(x, y)
            if x["id"] in C.TWO_VALUED and x.get("value") != y.get("value"):
                bad = True
            if x["id"] == "day_of_week" and not (set(x.get("days", [])) & set(y.get("days", []))):
                bad = True
            if not bad:
                continue
            cid = "impossible:" + short_id(sorted([canon(x), canon(y)]))
            if cid in reported:
                continue
            reported.add(cid)
            kind = kinds[0]
            out.append(_clar(cid, "impossible",
                             "Two of the conditions can never be true together, so the hound would never bet. Which one do you keep?",
                             [_opt("keep_first", _item_label(x, sx, answers, kind), _drop_effect(y, sy)),
                              _opt("keep_second", _item_label(y, sy, answers, kind), _drop_effect(x, sx))],
                             sorted({s[1] for s in (sx, sy) if len(s) > 1} or {"side"})))
    return out


# ---------------------------------------------------------------------------------------------------
# the spec
# ---------------------------------------------------------------------------------------------------

def _tree(items: List[dict]) -> Optional[dict]:
    if not items:
        return None
    uniq: Dict[str, dict] = {}
    for it in items:
        uniq.setdefault(canon(it), it)
    return {"op": "all", "items": [uniq[k] for k in sorted(uniq)]}


def build_rules(merged: Dict[str, Any], items: List[dict]) -> List[dict]:
    """One rule per kind of market (a rule is about game bets, totals or props, never a mix)."""
    kinds: Dict[str, List[str]] = {}
    for m in merged["markets"]:
        kinds.setdefault(R.market_kind(m), []).append(m)
    when = _tree(items)
    rules = []
    for kind in ("ml_spread", "total", "prop"):
        if kind not in kinds:
            continue
        side = merged.get("side") or "either"
        if side not in R.sides_for([kind]):
            continue
        rule: Dict[str, Any] = {"label": "", "sports": list(merged["sports"]), "markets": kinds[kind], "side": side}
        if not merged.get("price_any"):
            if merged.get("price_min") is not None:
                rule["price_min"] = merged["price_min"]
            if merged.get("price_max") is not None:
                rule["price_max"] = merged["price_max"]
        if merged.get("min_books") is not None:
            rule["min_books"] = merged["min_books"]
        if when is not None:
            rule["when"] = when
        rules.append(rule)
    return rules


def build_spec_input(merged: Dict[str, Any], items: List[dict], *, name: str, tagline: str = "") -> dict:
    return {"version": user_spec.SPEC_VERSION_V2, "name": name, "tagline": tagline, "color": "ember", "badge": "bone",
            "lock_minutes": merged["lock_minutes"], "max_bets_per_day": merged["max_bets_per_day"],
            "stake_units": merged["stake_units"], "rank_by": "earliest_lock", "rules": build_rules(merged, items)}


REQUIRED_FOR_SPEC = ("sports", "markets", "side", "max_bets_per_day", "lock_minutes", "stake_units")

# which topic to send the person back to for each menu refusal
def _topic_for_error(key: str) -> str:
    if "when" in key:
        return "side"
    if "sports" in key or "markets" in key:
        return "scope"
    if "side" in key:
        return "side"
    if "price" in key or "min_books" in key or "line" in key:
        return "price"
    if "lock_minutes" in key or "max_bets" in key:
        return "limits"
    if "stake" in key:
        return "stake"
    return "side"


def topic_status(answers: Dict[str, dict], merged: Dict[str, Any]) -> List[dict]:
    """[{id, title, state: done | skipped | missing | open, needs}] in topic order."""
    out = []
    for t in T.build_topics():
        ans = answers.get(t["id"])
        needs = [f for f in t["required"] if merged.get(f) is None]
        if ans is None:
            state = "open"
        elif ans.get("skipped"):
            state = "skipped" if t["skippable"] else "open"
        elif needs:
            state = "missing"
        else:
            state = "done"
        out.append({"id": t["id"], "title": t["title"], "state": state, "needs": needs})
    return out


def derive(state: dict) -> dict:
    answers: Dict[str, dict] = state.get("answers") or {}
    acks = set(state.get("acks") or [])
    asserted = _assertions(answers)
    merged: Dict[str, Any] = {}
    conflicts: Dict[str, List[Tuple[str, Any]]] = {}
    for field, pairs in asserted.items():
        distinct = _distinct(field, pairs)
        if len(distinct) > 1:
            conflicts[field] = distinct
        else:
            merged[field] = distinct[0][1]
    items_src = _items(answers, merged.get("role") if "role" not in conflicts else None)
    clarifications = _clarifications(answers, merged, conflicts, items_src, acks)
    status = topic_status(answers, merged)
    missing = [s["id"] for s in status if s["state"] in ("open", "missing")]
    cant = _cant_items(answers, merged, acks)
    out: Dict[str, Any] = {"fields": merged, "items": [{"condition": it, "source": list(src)} for it, src in items_src],
                           "cant_automate": cant, "clarifications": clarifications, "missing": missing,
                           "topics": status, "spec": None, "problems": {}, "complete": False}
    if missing or clarifications or conflicts or any(f not in merged for f in REQUIRED_FOR_SPEC):
        return out
    spec_items = [it for it, _ in items_src]
    raw = build_spec_input(merged, spec_items, name=PLACEHOLDER_NAME)
    try:
        out["spec"] = user_spec.validate_spec(raw)
    except user_spec.SpecError as exc:
        out["problems"] = dict(exc.errors)
        topics = sorted({_topic_for_error(k) for k in exc.errors if k != "name"} or {"side"})
        msg = "; ".join(f"{k}: {v}" for k, v in exc.errors.items() if k != "name")
        out["clarifications"] = [_clar("refused:" + short_id(sorted(exc.errors)), "refused",
                                       f"The menu does not allow this combination ({msg}). Which answer should change?",
                                       [_opt(f"redo_{t}", f"Change: {T.get(t)['title']}", {"op": "unanswer", "topics": [t]}) for t in topics],
                                       topics)]
        return out
    out["complete"] = True
    return out
