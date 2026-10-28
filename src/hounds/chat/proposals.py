"""The tools the hound may call, and the law every proposed change passes before a member ever sees it.

A TOOL CHANGES NOTHING. The model calls ``propose_price_band``, ``propose_add_sports`` and the rest; each one is applied to a COPY of the hound's rule
(``Workspace.draft``), and the copy goes through ``user_spec.validate_spec``, the builder's own gate, then through ``check_law`` (the
two rules that are never negotiable, re-checked by hand so they hold even if the gate changes: no price at -200 or worse, and at most
``user_rules.MAX_RULES`` rules). A change that passes is STAGED: the member sees a Before to After card with Apply and Cancel, and only
the Apply tap makes a version (``service.apply_proposal``, which runs the same gate again on what was stored). A change that does not pass
goes back to the model as a tool error ONCE so it can fix it; a second refusal in the same turn is final, the model is told to stop and
say plainly that it cannot do that and why. The model is trusted with none of the limits.

WHAT CHAT MAY EDIT. The rule set, the daily bet limit, the stake, the lock time and the rank order (through ``propose_rule_change``) and the price
bands and sports (through their own narrow tools). It may NOT rename a hound or change its look, its catchphrase or its in-play switch:
those are pinned to what the hound has.

STYLES. A Gematria hound follows a method that is not the member's to change: chat may change only its sports, its bets a day and its
stake (the three things its builder lets a member choose), and ``user_spec.validate_spec``'s Gematria branch re-derives its one fixed rule
from the sports, so a ``propose_rule_change`` that slips through still cannot change the method; ``Workspace`` also refuses every other tool by
name and ``changed_outside`` checks the finished copy. An Apprentice hound learns from the bets its owner logs and gets its rules from
the Lessons tab, so chat offers it no edit tools.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from src.hounds import add_sports, user_rules, user_spec, user_store
from src.hounds.english import render

ORIGIN_OWNER_CHAT = "owner_chat"
ORIGIN_LABEL = "edited in chat"

# Registered here, not in user_store, so this file is the whole change: the kennel and the hound page read ``ORIGIN_LABELS`` to say how a
# version came to be, and a version made from the chat should read "edited in chat", not nothing. (user_store.py is another worker's file
# today; the one-line home for this is its ORIGIN_LABELS dict.)
user_store.ORIGIN_LABELS.setdefault(ORIGIN_OWNER_CHAT, ORIGIN_LABEL)

TOOL_SET_BETS = "propose_bets_per_day"
TOOL_SET_STAKE = "propose_stake_units"
TOOL_SET_BAND = "propose_price_band"
TOOL_ADD_SPORTS = "propose_add_sports"
TOOL_REMOVE_SPORTS = "propose_remove_sports"
TOOL_SET_RULES = "propose_rule_change"
GEMATRIA_TOOLS = (TOOL_SET_BETS, TOOL_SET_STAKE, TOOL_ADD_SPORTS, TOOL_REMOVE_SPORTS)    # the three things a member chooses on a Gematria hound

TOP_KEYS_SET_RULES = ("rules", "lock_minutes", "max_bets_per_day", "stake_units", "rank_by")
PINNED_KEYS = ("name", "tagline", "color", "badge", "bet_in_play", "style", "gematria")   # never taken from the model
DERIVED_KEYS = user_spec.V2_DERIVED_KEYS
REASONS_SHOWN = 5


class Refusal(Exception):
    """A change the law does not allow. ``reasons`` are plain sentences the model reads and, if it must, repeats."""

    def __init__(self, reasons: Sequence[str]):
        self.reasons = [str(r) for r in reasons]
        super().__init__("; ".join(self.reasons))


class NoChange(Exception):
    """The hound already is the way the tool would make it. Not a refusal and not a proposal."""


def _tool(name: str, description: str, properties: Mapping) -> dict:
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": dict(properties), "required": list(properties),
                             "additionalProperties": False}}


def _bets_values() -> list:
    return list(range(user_spec.MAX_BETS_RANGE[0], user_spec.MAX_BETS_RANGE[1] + 1))


TOOLS: Dict[str, dict] = {t["name"]: t for t in (
    _tool(TOOL_SET_BETS, "PROPOSE a new daily bet limit (the most bets this hound makes in a day). Stages a proposal; changes nothing until the member taps Apply.",
          {"bets_per_day": {"type": "integer", "enum": _bets_values()}}),
    _tool(TOOL_SET_STAKE, "PROPOSE a new stake, in paper units, for every bet. Stages a proposal; changes nothing until the member taps Apply.",
          {"stake_units": {"type": "number", "enum": [float(s) for s in user_rules.STAKE_CHOICES]}}),
    _tool(TOOL_SET_BAND, "PROPOSE a new price band (American odds, for example -150 or +120) for some rules or all of them. The shortest price allowed is "
                         f"{user_spec.SHORTEST_ALLOWED_PRICE}; the longest is +{user_spec.LONGEST_ALLOWED_PRICE}. price_min is the shortest end, price_max the longer end. "
                         "`rules` lists the rule numbers (1 is the first rule) the band is for; an empty list means every rule. Stages a proposal.",
          {"price_min": {"type": "integer"}, "price_max": {"type": "integer"}, "rules": {"type": "array", "items": {"type": "integer"}}}),
    _tool(TOOL_ADD_SPORTS, "PROPOSE adding sports. Each rule is copied to the new sports where it makes sense (markets and conditions a sport does not have are left "
                           "out and said so). Stages a proposal.",
          {"sports": {"type": "array", "items": {"type": "string", "enum": list(user_spec.SPORTS)}}}),
    _tool(TOOL_REMOVE_SPORTS, "PROPOSE removing sports from every rule. A rule left with no sport is dropped; a hound must keep at least one sport. Stages a proposal.",
          {"sports": {"type": "array", "items": {"type": "string", "enum": list(user_spec.SPORTS)}}}),
    _tool(TOOL_SET_RULES, "PROPOSE a complete replacement rule set, for any change the narrow tools cannot make (a new condition, a new market, a new side, the lock time, "
                          "the rank order, several rules). `rules_json` is ONE JSON string holding the complete rule set in the same shape as the hound's own RULES AS JSON "
                          "(keys: rules, lock_minutes, max_bets_per_day, stake_units, rank_by). Anything you leave out reverts to its default, so copy what is not changing. "
                          "Stages a proposal.",
          {"rules_json": {"type": "string"}}),
)}


def tools_for(spec: Mapping, *, editable: bool = True) -> list:
    """The tools offered for this hound, in a stable order (the tool list is part of the cached prefix)."""
    if not editable or user_spec.is_apprentice(spec):
        return []
    if user_spec.is_gematria(spec):
        return [TOOLS[name] for name in GEMATRIA_TOOLS]
    return list(TOOLS.values())


# ---------------------------------------------------------------------------
# the law
# ---------------------------------------------------------------------------

def _where(path: str) -> str:
    """``rules[0].price_min`` as "rule 1, price_min"."""
    if path.startswith("rules[") and "]" in path:
        head, _, rest = path.partition("]")
        try:
            number = int(head[len("rules["):]) + 1
        except ValueError:
            return path
        return f"rule {number}, {rest.lstrip('.')}" if rest.lstrip(".") else f"rule {number}"
    return path


def reasons_of(errors: Mapping) -> List[str]:
    out = []
    for path, message in list(errors.items())[:REASONS_SHOWN]:
        out.append(f"{_where(str(path))}: {message}")
    return out


def check_law(spec: Mapping) -> None:
    """The two limits that are never negotiable, checked by hand on the finished spec: no price at -200 or worse, at most MAX_RULES rules."""
    rules = spec.get("rules") or []
    if len(rules) > user_rules.MAX_RULES:
        raise Refusal([f"a hound has at most {user_rules.MAX_RULES} rules; this would make {len(rules)}"])
    bad = []
    for i, rule in enumerate(rules, 1):
        for key in ("price_min", "price_max"):
            value = rule.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0 and value <= user_spec.MAX_FAVOURITE_PRICE:
                bad.append(f"rule {i}, {key}: a price of {user_spec.MAX_FAVOURITE_PRICE} or worse is never allowed (the shortest price is {user_spec.SHORTEST_ALLOWED_PRICE})")
    if bad:
        raise Refusal(bad)


def validate(raw: Mapping, taken_names: Sequence[str] = ()) -> dict:
    """``raw`` through the builder's own gate and then the law, or ``Refusal`` carrying every reason."""
    try:
        spec = user_spec.validate_spec(raw, taken_names=taken_names)
    except user_spec.SpecError as exc:
        raise Refusal(reasons_of(exc.errors)) from None
    check_law(spec)
    return spec


def v2_of(spec: Mapping) -> dict:
    """The hound's rule as a validated version-2 spec (a classic version-1 hound is upgraded the way the builder does it)."""
    raw = copy.deepcopy(dict(spec)) if user_spec.is_v2(spec) else user_spec.upgrade_v1(spec)
    return user_spec.validate_spec(raw, taken_names=())


# fields a Gematria hound's member may change; everything else about the spec must come out identical
_GEMATRIA_FREE = ("sports", "max_bets_per_day", "stake_units", "rules", "markets")


def changed_outside(old: Mapping, new: Mapping) -> List[str]:
    """For a Gematria hound: the fields that changed other than the member's own three choices (the rule is re-derived from the sports, so
    ``rules`` is compared by what the engine reads: it must still be the one canonical rule over the new sports)."""
    out = []
    for key in sorted(set(old) | set(new)):
        if key in _GEMATRIA_FREE:
            continue
        if old.get(key) != new.get(key):
            out.append(key)
    return out


# ---------------------------------------------------------------------------
# the tools
# ---------------------------------------------------------------------------

def _raw(draft: Mapping) -> dict:
    return copy.deepcopy(dict(draft))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sports_arg(args: Mapping) -> list:
    sports = args.get("sports")
    if not isinstance(sports, list) or not sports or any(s not in user_spec.SPORTS for s in sports):
        raise Refusal([f"name at least one sport from: {', '.join(user_spec.SPORTS)}"])
    return [s for s in dict.fromkeys(sports)]


def _t_bets(draft: Mapping, args: Mapping) -> dict:
    value = args.get("bets_per_day")
    if not _is_int(value):
        raise Refusal([f"bets_per_day must be a whole number from {user_spec.MAX_BETS_RANGE[0]} to {user_spec.MAX_BETS_RANGE[1]}"])
    if draft.get("max_bets_per_day") == value:
        raise NoChange(f"it already makes at most {value} bet{'s' if value != 1 else ''} a day")
    raw = _raw(draft)
    raw["max_bets_per_day"] = value
    return raw


def _t_stake(draft: Mapping, args: Mapping) -> dict:
    value = args.get("stake_units")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal(["stake_units must be a number of paper units"])
    if float(draft.get("stake_units", 1.0)) == float(value):
        raise NoChange(f"the stake is already {value:g} paper unit{'s' if float(value) != 1 else ''}")
    raw = _raw(draft)
    raw["stake_units"] = float(value)
    return raw


def _t_band(draft: Mapping, args: Mapping) -> dict:
    lo, hi = args.get("price_min"), args.get("price_max")
    if not (_is_int(lo) and _is_int(hi)):
        raise Refusal(["price_min and price_max must be whole American prices such as -150 or +120"])
    raw = _raw(draft)
    rules = raw.get("rules") or []
    if not rules:
        raise Refusal(["this hound has no rules to put a price band on"])
    wanted = args.get("rules")
    if wanted in (None, []):
        picks = list(range(len(rules)))
    elif isinstance(wanted, list) and all(_is_int(n) for n in wanted):
        missing = [n for n in wanted if not 1 <= n <= len(rules)]
        if missing:
            raise Refusal([f"there is no rule {missing[0]}; this hound has {len(rules)} rule{'s' if len(rules) != 1 else ''}"])
        picks = sorted({n - 1 for n in wanted})
    else:
        raise Refusal(["`rules` must be a list of rule numbers, or empty for every rule"])
    changed = False
    for i in picks:
        if rules[i].get("price_min") != lo or rules[i].get("price_max") != hi:
            changed = True
        rules[i]["price_min"], rules[i]["price_max"] = lo, hi
    if not changed:
        raise NoChange("the price band is already that")
    return raw


def _t_add(draft: Mapping, args: Mapping) -> dict:
    sports = _sports_arg(args)
    have = set(draft.get("sports") or [])
    if all(s in have for s in sports):
        raise NoChange(f"it already covers {', '.join(sports)}")
    try:
        out = add_sports.plan({"spec": dict(draft)}, ",".join(sports))
    except add_sports.AddSportsError as exc:
        raise Refusal([str(exc)]) from None
    except user_spec.SpecError as exc:
        raise Refusal(reasons_of(exc.errors)) from None
    return out["raw"]


def _t_remove(draft: Mapping, args: Mapping) -> dict:
    sports = _sports_arg(args)
    have = list(draft.get("sports") or [])
    gone = [s for s in sports if s in have]
    if not gone:
        raise NoChange(f"it does not cover {', '.join(sports)}")
    if not [s for s in have if s not in gone]:
        raise Refusal(["a hound must keep at least one sport"])
    raw = _raw(draft)
    kept = []
    for rule in raw.get("rules") or []:
        rule["sports"] = [s for s in rule.get("sports") or [] if s not in gone]
        if rule["sports"]:
            kept.append(rule)
    if not kept:
        raise Refusal(["that would leave no rule with a sport; a hound must keep at least one"])
    raw["rules"] = kept
    return raw


def _t_rules(draft: Mapping, args: Mapping) -> dict:
    text = args.get("rules_json")
    try:
        body = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise Refusal(["rules_json must be one JSON object holding the complete rule set"])
    stray = [k for k in body if k not in TOP_KEYS_SET_RULES + PINNED_KEYS + DERIVED_KEYS + ("version",)]
    if stray:
        raise Refusal([f"{k}: is not a field on the menu" for k in stray[:REASONS_SHOWN]])
    raw = {k: copy.deepcopy(v) for k, v in body.items() if k in TOP_KEYS_SET_RULES}
    rules = raw.get("rules")
    if isinstance(rules, list) and len(rules) > user_rules.MAX_RULES:
        raise Refusal([f"a hound has at most {user_rules.MAX_RULES} rules; this has {len(rules)}"])
    for key in ("name", "tagline", "color", "badge", user_spec.IN_PLAY_FIELD):          # pinned to what the hound has, never the model's
        if key in draft:
            raw[key] = copy.deepcopy(draft[key])
    raw["version"] = user_spec.SPEC_VERSION_V2
    return raw


_HANDLERS: Dict[str, Callable[[Mapping, Mapping], dict]] = {
    TOOL_SET_BETS: _t_bets, TOOL_SET_STAKE: _t_stake, TOOL_SET_BAND: _t_band, TOOL_ADD_SPORTS: _t_add,
    TOOL_REMOVE_SPORTS: _t_remove, TOOL_SET_RULES: _t_rules}


def _strip_gematria(raw: Mapping) -> dict:
    return {k: copy.deepcopy(v) for k, v in raw.items() if k not in ("rules", "markets", "side_rule")}


def _gematria_raw(draft: Mapping, name: str, args: Mapping) -> dict:
    """A Gematria hound's edit, done on the three fields its builder lets a member choose. The one fixed rule is NOT sent: validation
    re-derives it from the stamp and the sports."""
    if name == TOOL_SET_BETS:
        return _strip_gematria(_t_bets(draft, args))
    if name == TOOL_SET_STAKE:
        return _strip_gematria(_t_stake(draft, args))
    raw = _strip_gematria(draft)
    sports = _sports_arg(args)
    have = list(draft.get("sports") or [])
    if name == TOOL_ADD_SPORTS:
        if all(s in have for s in sports):
            raise NoChange(f"it already covers {', '.join(sports)}")
        raw["sports"] = [s for s in user_spec.SPORTS if s in have or s in sports]
    else:
        gone = [s for s in sports if s in have]
        if not gone:
            raise NoChange(f"it does not cover {', '.join(sports)}")
        left = [s for s in have if s not in gone]
        if not left:
            raise Refusal(["a hound must keep at least one sport"])
        raw["sports"] = left
    return raw


# ---------------------------------------------------------------------------
# one turn's working copy
# ---------------------------------------------------------------------------

STAGED = ("Staged for the member's approval. NOTHING has changed yet: the member now sees a card with Apply and Cancel. "
          "Say in one or two short sentences what you propose, in your own voice, and tell them to tap Apply to make it so. "
          "What would change: ")
NO_CHANGE = "Nothing to change: "
FIX_ONCE = "That change is not allowed: {why}. You may fix it ONCE and call a tool again, or stop and explain."
FINAL_REFUSAL = ("Still not allowed: {why}. Do NOT call a tool again. Tell the member plainly that you cannot do this and why, "
                 "in these words, and offer what you can do instead.")
NOT_EDITABLE = "Rule changes are not available for this hound right now ({why}). Do not call a tool; tell the member."


class Workspace:
    """The tool calls of ONE turn, applied in order to a copy of the hound's rule. ``handle`` is the ``on_tool`` the model loop calls."""

    def __init__(self, hound: Mapping, *, taken_names: Sequence[str] = (), editable: bool = True, why_not: str = ""):
        self.spec = hound["spec"]
        self.current = v2_of(self.spec)
        self.draft = copy.deepcopy(self.current)
        self.taken = list(taken_names)
        self.editable = editable
        self.why_not = why_not
        self.gematria = user_spec.is_gematria(self.current)
        self.apprentice = user_spec.is_apprentice(self.current)
        self.refusals = 0
        self.last_refusal = ""
        self.summaries: List[str] = []

    @property
    def allowed(self) -> tuple:
        return tuple(t["name"] for t in tools_for(self.current, editable=self.editable))

    def handle(self, name: str, args: Mapping):
        """``(content, is_error)`` for one tool call."""
        if not self.editable or self.apprentice:
            return NOT_EDITABLE.format(why=self.why_not or "an Apprentice learns from the bets its owner logs"), True
        if self.refusals >= 2:
            return FINAL_REFUSAL.format(why=self.last_refusal), True
        handler = _HANDLERS.get(name)
        if handler is None or name not in self.allowed:
            return self._refuse([f"{name} is not something this hound can do"
                                 + (" (a Gematria hound follows a fixed method; only its sports, bets a day and stake can change)" if self.gematria else "")])
        try:
            raw = _gematria_raw(self.draft, name, args) if self.gematria else handler(self.draft, args)
            spec = validate(raw, self.taken)
            if spec == self.draft:
                raise NoChange("it already reads that way")
            if self.gematria:
                outside = changed_outside(self.current, spec)
                if outside:
                    raise Refusal([f"a Gematria hound follows a fixed method; {', '.join(outside)} cannot change"])
        except NoChange as exc:
            return NO_CHANGE + str(exc) + ". Tell the member; no proposal was staged for this.", False
        except Refusal as exc:
            return self._refuse(exc.reasons)
        before = self.draft
        self.draft = spec
        lines = [f"{d['what']}: {d['before']} -> {d['after']}" for d in render.diff_specs(before, spec)]
        self.summaries.append(name)
        return STAGED + ("; ".join(lines) if lines else "the rule reads the same") + ".", False

    def _refuse(self, reasons: Sequence[str]):
        self.refusals += 1
        self.last_refusal = "; ".join(reasons)[:600]
        template = FIX_ONCE if self.refusals == 1 else FINAL_REFUSAL
        return template.format(why=self.last_refusal), True

    @property
    def changed(self) -> bool:
        return self.draft != self.current

    @property
    def refused_for_good(self) -> Optional[str]:
        """The reason the hound has to give when the turn ended on a second refusal (and nothing was staged to fall back on)."""
        return self.last_refusal if self.refusals >= 2 else None

    def card(self, request: str, hound: Mapping) -> Optional[dict]:
        """The proposal card for what this turn staged, or None when nothing changed."""
        if not self.changed:
            return None
        changes = render.diff_specs(self.current, self.draft)
        return {"status": "pending", "request": " ".join(str(request or "").split())[:200], "changes": changes,
                "rule_after": user_spec.rule_text(self.draft), "spec": self.draft, "base_hound_id": hound["id"],
                "base_hash": user_spec.spec_hash(hound["spec"]), "tools": list(self.summaries)}


def public_card(proposal: Optional[Mapping]) -> Optional[dict]:
    """What the page may see of a proposal: its state and the plain-English difference, never the stored spec or its hashes."""
    if not proposal:
        return None
    out = {k: proposal.get(k) for k in ("status", "changes", "rule_after", "request")}
    if proposal.get("applied"):
        out["applied"] = dict(proposal["applied"])
    return out
