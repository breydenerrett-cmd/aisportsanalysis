"""Quiz answers -> a validated hound spec. Deterministic: the same answers always give the same spec.

THE ANSWERS (every one optional; skip anything and the quiz still composes a hound)
-----------------------------------------------------------------------------------
  sports          ["MLB", "NFL"], one or both
  markets         ids from the library: moneyline, spread, total, props, mix ("a bit of everything")
  personality     underdog_hunter | chalk_eater | chaos_agent | stats_nerd | steam_chaser | mystic
  bets_per_day    1 to 5            stake  0.5 to 3 paper units            price_comfort  short | even | plus | long
  timing          early | late      archetypes  up to 3 library ids      quirks  library ids      letter  "S"
  look            {"coat": "golden", "accessory": "cap"}                   name, tagline  optional text
  english_draft   the parsed rules of the "add anything in your own words" box (from POST /hounds/english), or
  english_text    the raw words, parsed here with the same free parser

HOW THEY BECOME RULES
---------------------
  1. The BASE rules come from the personality (a recipe per kind of market: moneyline/spread, total, prop) over the markets
     chosen (moneyline and spread share one rule; totals and props each get their own).
  2. Each archetype card adds its own rule(s), verbatim from the library.
  3. Quirks are extra AND conditions added to every base and card rule they can apply to (a rule is "every condition must
     hold"). Rules from the English box are the person's own words and are left exactly as parsed.
  4. Anything typed in English is parsed and added as further rules, and a number it names (bets a day, stake, lock time,
     ranking) replaces the quiz's.
  Rules are alternatives: the hound bets when ANY rule says go, and a hound holds at most `MAX_RULES` (4). Rules are kept in
  the order above; extras past the cap are dropped from the end, and the warning says which.

CONFLICTS: THE LATER ANSWER WINS, AND THE QUIZ SAYS SO
------------------------------------------------------
Questions run in this order: sports, markets, personality, risk (bets, stake, price), timing, archetypes, quirks, English.
When two answers disagree the later one wins, and a warning names both: a price comfort that pulls against the personality
(chalk eater, then plus money) takes over the price band and drops the personality's favourite-or-underdog condition; a
quirk replaces a same-kind condition inside an archetype ("new moon" replaces Full Moon Chaos's full moon); an archetype
that needs a sport the person did not pick still runs in its own sport. Opposite stances (a dog card beside a chalk card) are
not an error, only a heads-up that the hound will bet both kinds.

ALWAYS THROUGH THE REAL VALIDATOR. The finished spec goes through `user_spec.validate_spec`. If the validator refuses a
rule (a stale fragment, an English rule off the menu) that rule is dropped and the reason is a warning; a refused global
returns to its default. The -200 cap is the validator's: this module never builds a band that reaches it.

Pure and offline: no network, no clock, no randomness. The only outside read is `taken_names`, which the caller passes in.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Iterable, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import render
from src.hounds.quiz import library as lib_mod

STARTER_PERSONALITY = "underdog_hunter"
STARTER_NOTE = ("You skipped everything, so this is the starter pup: underdog moneylines at plus money. "
                "Change any answer to make it yours.")
ENGLISH_LABEL = "In your words"
# A recipe's stand-in when no personality was picked: no side preference, a comfortable price range.
NEUTRAL = {
    "ml": {"side": "either", "price_min": -150, "price_max": 200, "when": []},
    "total": {"side": "either", "price_min": -199, "price_max": 1000, "when": []},
    "prop": {"side": "either", "price_min": -199, "price_max": 1000, "when": []},
}
ORDER = ("sports", "markets", "personality", "bets_per_day", "stake", "price_comfort", "timing", "archetypes", "quirks",
         "letter", "look", "name", "tagline")
GLOBAL_KEYS = ("max_bets_per_day", "stake_units", "lock_minutes", "rank_by")


def _warn(out: list, code: str, message: str, level: str = "heads_up") -> None:
    out.append({"code": code, "level": level, "message": message})


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# reading the answers
# ---------------------------------------------------------------------------

def clean_answers(raw: Any, lib: Mapping, warnings: list) -> dict:
    """The answers that are usable, nothing else. A bad value is dropped with a warning, never guessed at."""
    a = raw if isinstance(raw, Mapping) else {}
    out: dict = {}
    if raw is not None and not isinstance(raw, Mapping):
        _warn(warnings, "answers_ignored", "The answers were not an object, so every question counts as skipped.")

    def ids_of(key: str, table: str) -> list:
        value = a.get(key)
        if value in (None, "", []):
            return []
        items = [value] if isinstance(value, str) else value
        if not isinstance(items, (list, tuple)):
            _warn(warnings, "answer_ignored", f"'{key}' should be a list; it was skipped.")
            return []
        known = lib_mod.by_id(lib[table])
        good: list = []
        for item in items:
            if isinstance(item, str) and item in known:
                if item not in good:
                    good.append(item)
            else:
                _warn(warnings, "answer_ignored", f"'{str(item)[:30]}' is not a {key} option, so it was left out.")
        return good

    sports = a.get("sports")
    if sports not in (None, "", []):
        items = [sports] if isinstance(sports, str) else sports
        good = [s for s in user_spec.SPORTS if isinstance(items, (list, tuple)) and s in items]
        bad = [i for i in (items if isinstance(items, (list, tuple)) else [items]) if i not in user_spec.SPORTS]
        for item in bad:
            _warn(warnings, "answer_ignored", f"'{str(item)[:20]}' is not a sport this program covers.")
        if good:
            out["sports"] = good
    markets = ids_of("markets", "markets")
    if markets:
        out["markets"] = markets
    pers = a.get("personality")
    if pers not in (None, ""):
        if isinstance(pers, str) and pers in lib_mod.by_id(lib["personalities"]):
            out["personality"] = pers
        else:
            _warn(warnings, "answer_ignored", f"'{str(pers)[:30]}' is not a personality, so it was left out.")
    bets = a.get("bets_per_day")
    if bets not in (None, ""):
        lo, hi = user_spec.MAX_BETS_RANGE
        if _is_int(bets) and lo <= bets <= hi:
            out["bets_per_day"] = bets
        else:
            _warn(warnings, "answer_ignored", f"Bets a day must be a whole number from {lo} to {hi}; it was skipped.")
    stake = a.get("stake")
    if stake not in (None, ""):
        if isinstance(stake, (int, float)) and not isinstance(stake, bool) and float(stake) in R.STAKE_CHOICES:
            out["stake"] = float(stake)
        else:
            _warn(warnings, "answer_ignored", "Stake must be one of " + ", ".join(f"{s:g}" for s in R.STAKE_CHOICES)
                  + " paper units; it was skipped.")
    for key, table in (("price_comfort", "price_comforts"), ("timing", "timings")):
        value = a.get(key)
        if value not in (None, ""):
            if isinstance(value, str) and value in lib_mod.by_id(lib[table]):
                out[key] = value
            else:
                _warn(warnings, "answer_ignored", f"'{str(value)[:30]}' is not a {key.replace('_', ' ')} option.")
    picks = ids_of("archetypes", "archetypes")
    if len(picks) > lib_mod.PICK_LIMIT:
        _warn(warnings, "archetype_limit", f"You can pick up to {lib_mod.PICK_LIMIT} cards; the first "
              f"{lib_mod.PICK_LIMIT} were kept and the rest left out.")
        picks = picks[:lib_mod.PICK_LIMIT]
    if picks:
        out["archetypes"] = picks
    quirks = ids_of("quirks", "quirks")
    if quirks:
        out["quirks"] = quirks
    letter = a.get("letter")
    if letter not in (None, ""):
        if isinstance(letter, str) and len(letter) == 1 and letter.isascii() and letter.isalpha():
            out["letter"] = letter.upper()
        else:
            _warn(warnings, "answer_ignored", "A lucky letter is a single letter A to Z; it was skipped.")
    look = a.get("look")
    if isinstance(look, Mapping):
        coats, accs = lib["looks"]["coats"], lib_mod.by_id(lib["looks"]["accessories"])
        clean = {}
        if look.get("coat") in coats:
            clean["coat"] = look["coat"]
        if look.get("accessory") in accs:
            clean["accessory"] = look["accessory"]
        if clean:
            out["look"] = clean
    for key in ("name", "tagline"):
        value = a.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = " ".join(value.split())
    return out


# ---------------------------------------------------------------------------
# building rules
# ---------------------------------------------------------------------------

def _condition_ids(rule: Mapping) -> list:
    return [c["id"] for c in R.walk(rule.get("when"))]


def _add_condition(rule: dict, cond: Mapping, warnings: list, quirk_name: str) -> None:
    """AND `cond` onto the rule. A same-id condition already there is replaced (the later answer wins) and said so."""
    items = list((rule.get("when") or {"items": []})["items"])
    replaced = [i for i in items if "items" not in i and i["id"] == cond["id"]]
    if replaced:
        items = [i for i in items if i not in replaced]
        _warn(warnings, "quirk_replaced",
              f"'{quirk_name}' replaced the {R.BY_ID[cond['id']].label.lower()} condition already in "
              f"{rule.get('label') or 'a rule'}. Your later answer wins.")
    items.append(copy.deepcopy(dict(cond)))
    rule["when"] = {"op": "all", "items": items}


def _kind_of(rule: Mapping) -> str:
    k = R.market_kind(rule["markets"][0])
    return {"ml_spread": "ml", "total": "total", "prop": "prop"}[k]


def _apply_quirks(rule: dict, quirk_rows: list, letter: Optional[str], warnings: list) -> None:
    for q in quirk_rows:
        kind = _kind_of(rule)
        where = rule.get("label") or "a rule"
        if kind not in q["kinds"]:
            _warn(warnings, "quirk_skipped", f"'{q['name']}' only applies to "
                  f"{'moneylines and spreads' if q['kinds'] == ['ml'] else 'some bets'}, so it was left off {where}.",
                  "note")
            continue
        narrowed = [s for s in rule["sports"] if s in q["sports"]]
        if not narrowed:
            _warn(warnings, "quirk_skipped", f"'{q['name']}' is {'/'.join(q['sports'])} only, so it was left off {where}.")
            continue
        if narrowed != rule["sports"]:
            _warn(warnings, "quirk_narrowed", f"'{q['name']}' is {'/'.join(q['sports'])} only, so {where} now covers "
                  f"{' and '.join(narrowed)} only.")
            rule["sports"] = narrowed
        cond = copy.deepcopy(q["condition"])
        if q["id"] == "lucky_letter" and letter:
            cond["letter"] = letter
        _add_condition(rule, cond, warnings, q["name"])


def _base_rule(kind: str, markets: list, pers: Optional[Mapping], comfort: Optional[Mapping], sports: list,
               warnings: list) -> dict:
    recipe = copy.deepcopy((pers or {}).get("recipes", {}).get(kind) or NEUTRAL[kind])
    when = list(recipe.get("when") or [])
    lo, hi = recipe["price_min"], recipe["price_max"]
    pname = (pers or {}).get("name")
    if comfort:
        if kind == "total" and comfort["stance"] == "dog":
            _warn(warnings, "totals_price", f"Game totals are almost always priced near -110, so '{comfort['name']}' was "
                  "not applied to them; their price band stays open.", "note")
        else:
            if pers and {pers["stance"], comfort["stance"]} == {"dog", "chalk"}:
                _warn(warnings, "price_conflict",
                      f"{pname} and '{comfort['name']}' pull opposite ways. Your later answer wins: the price band is "
                      f"{comfort['name'].lower()} and {pname}'s favourite-or-underdog condition was dropped.")
                when = [c for c in when if c["id"] != "role"]
            lo, hi = comfort["price_min"], comfort["price_max"]
    rule = {"label": pname or ("Your style" if kind == "ml" else "Your style"),
            "sports": list(sports) if kind != "prop" else ["MLB"], "markets": list(markets),
            "side": recipe.get("side", "either"), "price_min": lo, "price_max": hi, "line_min": None, "line_max": None,
            "min_books": recipe.get("min_books", user_spec.DEFAULT_MIN_BOOKS_PROP if kind == "prop"
                                    else user_spec.DEFAULT_MIN_BOOKS_GAME),
            "when": {"op": "all", "items": copy.deepcopy(when)} if when else None}
    return rule


def _archetype_rules(arch: Mapping, chosen_sports: list, warnings: list) -> list:
    rules = copy.deepcopy(arch["fragment"]["rules"])
    for rule in rules:
        rule.setdefault("label", arch["name"])
        if not rule["label"]:
            rule["label"] = arch["name"]
        if chosen_sports:
            keep = [s for s in rule["sports"] if s in chosen_sports]
            if keep:
                rule["sports"] = keep
            else:
                _warn(warnings, "sport_override",
                      f"{arch['name']} is {' and '.join(rule['sports'])} only, but you picked "
                      f"{' and '.join(chosen_sports)}. Your later card pick wins, so this rule still covers "
                      f"{' and '.join(rule['sports'])}.")
    return rules


def _spread_only_markets(markets_chosen: list) -> list:
    return [m for m in ("moneyline", "spread") if m in markets_chosen]


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

def _hash(parts: Any) -> int:
    return int(hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()[:12], 16)


def _name_ok(name: str, taken: Iterable[str]) -> Optional[str]:
    """None when `name` passes the real name checks, else the reason."""
    errors: dict = {}
    user_spec._check_name({"name": name}, errors, taken, None)
    return errors.get("name")


def name_suggestions(lib: Mapping, personality: Optional[str], archetype_ids: list, seed_parts: Any,
                     taken: Iterable[str] = (), count: int = 3) -> list:
    pools = lib["name_pools"]
    pool = list(pools.get(personality or "default") or pools["default"])
    start = _hash(seed_parts) % len(pool)
    ordered = pool[start:] + pool[:start]
    arch = lib_mod.by_id(lib["archetypes"])
    for aid in archetype_ids:
        first = arch[aid]["name"].split()[0].replace("-", " ").title() if aid in arch else ""
        if first:
            ordered.append(f"{first} Pup")
    ordered.extend(pools["default"])
    out: list = []
    taken = list(taken)
    for name in ordered:
        if name not in out and not _name_ok(name, taken):
            out.append(name)
        if len(out) == count:
            break
    return out


# ---------------------------------------------------------------------------
# the look
# ---------------------------------------------------------------------------

def suggest_look(lib: Mapping, answers: Mapping, personality: Optional[Mapping]) -> dict:
    """A whitelisted look for the hound (src/hounds/interact/look.py keys): the person's coat and accessory when they
    picked them, else the personality's own coat and tile, else the plain default. Cosmetic only, and the same table the
    page reads (`coat`, `bg` on each personality), so the preview on the look question is the dog on the reveal."""
    asked = answers.get("look") or {}
    p = personality or {}
    look = {"coat": asked.get("coat") or p.get("coat") or "tan", "eyes": "brown", "bg": p.get("bg") or "navy",
            "head": "none", "face": "none", "neck": "none", "body": "none"}
    if asked.get("accessory"):
        look.update(lib_mod.by_id(lib["looks"]["accessories"])[asked["accessory"]]["look"])
    return look


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------

def _english_parts(english_draft: Any, english_text: Any, warnings: list) -> tuple:
    """(rules, globals) from the English box: a draft already parsed by POST /hounds/english, else the text parsed here."""
    draft = english_draft
    if draft is None and isinstance(english_text, str) and english_text.strip():
        from src.hounds.english import parser
        parsed = parser.parse(english_text)
        draft = parsed.get("draft") or {}
        for chunk in parsed.get("not_understood") or []:
            if chunk.get("text"):
                _warn(warnings, "english_not_understood",
                      f"\"{str(chunk['text'])[:60]}\" was not understood ({chunk.get('reason', 'not on the menu')}).")
    if not isinstance(draft, Mapping):
        return [], {}
    raw_rules = draft.get("rules") if isinstance(draft.get("rules"), list) else []
    rules = [r for r in raw_rules if isinstance(r, Mapping)][:R.MAX_RULES]
    globs = {k: draft[k] for k in GLOBAL_KEYS if k in draft}
    return copy.deepcopy(rules), globs


def compose(answers: Any, *, taken_names: Iterable[str] = (), english_draft: Any = None, english_text: Any = None,
            lib: Optional[Mapping] = None) -> dict:
    """The quiz's answers as {spec, english, warnings, ...}. See the module docstring for the rules."""
    lib = lib if lib is not None else lib_mod.load()
    warnings: list = []
    taken = list(taken_names)
    ans = clean_answers(answers, lib, warnings)
    pers_rows, arch_rows, quirk_rows = (lib_mod.by_id(lib[t]) for t in ("personalities", "archetypes", "quirks"))
    comfort_rows, market_rows = lib_mod.by_id(lib["price_comforts"]), lib_mod.by_id(lib["markets"])
    eng_rules, eng_globals = _english_parts(english_draft, english_text, warnings)

    pers = pers_rows.get(ans.get("personality"))
    comfort = comfort_rows.get(ans.get("price_comfort"))
    chosen_sports = list(ans.get("sports") or [])
    arch_ids = list(ans.get("archetypes") or [])
    quirk_list = [quirk_rows[q] for q in ans.get("quirks") or []]

    # which markets
    market_ids = list(ans.get("markets") or [])
    chosen_markets: list = []
    for mid in market_ids:
        for m in market_rows[mid]["markets"]:
            if m not in chosen_markets:
                chosen_markets.append(m)
    # quirks alone (no card, no words of the person's own) narrow a plain base rule rather than nothing
    wants_base = bool(market_ids or pers or comfort or (quirk_list and not arch_ids and not eng_rules))
    if wants_base and not chosen_markets:
        chosen_markets = ["moneyline"]
        _warn(warnings, "markets_assumed", "No market was picked, so the base rule is on moneylines.", "note")

    built: list = []          # [(rule, source)] in priority order; source = {"kind", "id", "name"}
    sports_for_base = chosen_sports or list(user_spec.SPORTS)
    base_src = {"kind": "personality" if pers else "markets", "id": (pers or {}).get("id"),
                "name": (pers or {}).get("name") or "Your markets"}
    if wants_base:
        ml_markets = _spread_only_markets(chosen_markets)
        if ml_markets:
            built.append((_base_rule("ml", ml_markets, pers, comfort, sports_for_base, warnings), dict(base_src)))
        if "total" in chosen_markets:
            built.append((_base_rule("total", ["total"], pers, comfort, sports_for_base, warnings), dict(base_src)))
        props = [m for m in chosen_markets if R.market_kind(m) == "prop"]
        if props:
            if chosen_sports and "MLB" not in chosen_sports:
                _warn(warnings, "props_mlb_only", "Player props are MLB only, and you picked NFL alone, so props were left out.")
            else:
                built.append((_base_rule("prop", props, pers, comfort, ["MLB"], warnings), dict(base_src)))
    for aid in arch_ids:
        arch = arch_rows[aid]
        for rule in _archetype_rules(arch, chosen_sports, warnings):
            built.append((rule, {"kind": "archetype", "id": aid, "name": arch["name"]}))
    stances = {arch_rows[a]["stance"] for a in arch_ids} | ({pers["stance"]} if pers else set())
    if {"dog", "chalk"} <= stances:
        _warn(warnings, "stance_mix", "A dog card and a chalk card pull opposite ways, so this hound will bet both "
              "underdogs and favourites. Drop one card if you want a single style.")
    for rule, _src in built:
        if quirk_list:
            _apply_quirks(rule, quirk_list, ans.get("letter"), warnings)
    if ans.get("letter"):
        for rule, src in built:
            for cond in R.walk(rule.get("when")):
                if cond["id"] == "name_letter" and src["kind"] == "archetype":
                    cond["letter"] = ans["letter"]
    for rule in eng_rules:
        rule.setdefault("label", "")
        if not rule.get("label"):
            rule["label"] = ENGLISH_LABEL
        built.append((rule, {"kind": "english", "id": None, "name": ENGLISH_LABEL}))

    starter = False
    if not built:
        # nothing asked for, or everything asked for was refused: the starter pup, on the sports picked
        starter, pers = True, pers_rows.get(STARTER_PERSONALITY)
        base_src = {"kind": "personality", "id": STARTER_PERSONALITY, "name": pers["name"]}
        built.append((_base_rule("ml", ["moneyline"], pers, None, sports_for_base, warnings), base_src))
        _warn(warnings, "starter", STARTER_NOTE if not ans else
              "Nothing usable was left from those answers, so this is the starter pup: underdog moneylines at plus money.",
              "note")
    if len(built) > R.MAX_RULES:
        left_out = [src["name"] for _r, src in built[R.MAX_RULES:]]
        _warn(warnings, "rule_cap", f"A hound holds at most {R.MAX_RULES} rules, so {', '.join(left_out)} "
              f"{'was' if len(left_out) == 1 else 'were'} left out. Open Edit rules to swap one in.")
        built = built[:R.MAX_RULES]

    # the whole-hound settings
    settings = {"max_bets_per_day": ans.get("bets_per_day") or (pers or {}).get("bets_hint") or lib["defaults"]["max_bets_per_day"],
                "stake_units": ans.get("stake") or lib["defaults"]["stake_units"],
                "lock_minutes": (lib_mod.by_id(lib["timings"])[ans["timing"]]["lock_minutes"] if ans.get("timing")
                                 else lib["defaults"]["lock_minutes"]),
                "rank_by": (pers or {}).get("rank_by")}
    if not settings["rank_by"]:
        for aid in arch_ids:
            rb = arch_rows[aid]["fragment"].get("rank_by")
            if rb:
                settings["rank_by"] = rb
                break
    settings["rank_by"] = settings["rank_by"] or "earliest_lock"
    if not pers and not ans.get("bets_per_day") and arch_ids:
        bets = arch_rows[arch_ids[0]]["fragment"].get("max_bets_per_day")
        if bets:
            settings["max_bets_per_day"] = bets
    said = {"max_bets_per_day": ans.get("bets_per_day"), "stake_units": ans.get("stake"),
            "lock_minutes": settings["lock_minutes"] if ans.get("timing") else None}
    quiz_settings = dict(settings)            # what a refused global from the English box falls back to
    for key, value in eng_globals.items():
        if key in GLOBAL_KEYS and value is not None and value != settings.get(key):
            if said.get(key) is not None:
                _warn(warnings, "english_override",
                      f"Your own words set {key.replace('_', ' ')} to {value}, replacing the {settings[key]} from your "
                      "quiz answers. Your later answer wins.")
            settings[key] = value

    # colour and badge
    color = (pers or {}).get("color")
    badge = (pers or {}).get("badge")
    if not color:
        seed = _hash([arch_ids[:1], market_ids])
        color = R.COLOR_IDS[seed % len(R.COLOR_IDS)] if arch_ids else lib["defaults"]["color"]
        badge = R.BADGE_IDS[(seed >> 3) % len(R.BADGE_IDS)] if arch_ids else lib["defaults"]["badge"]

    seed_parts = [ans.get("personality"), arch_ids, market_ids, chosen_sports, sorted(ans.get("quirks") or [])]
    suggestions = name_suggestions(lib, (pers or {}).get("id") if not starter else None, arch_ids, seed_parts, taken)
    name = ans.get("name")
    if name:
        problem = _name_ok(name, taken)
        if problem:
            _warn(warnings, "name_rejected", f"'{name[:30]}' {problem}, so a suggested name was used.")
            name = None
    name = name or (suggestions[0] if suggestions else "Starter Pup")
    tagline = ans.get("tagline") or (pers or {}).get("tagline") or (
        ("Runs " + " and ".join(arch_rows[a]["name"] for a in arch_ids[:2]) + ".") if arch_ids else "")
    tagline_errors: dict = {}
    user_spec._check_tagline({"tagline": tagline}, tagline_errors)
    if tagline_errors:
        if ans.get("tagline"):
            _warn(warnings, "tagline_rejected", f"The catchphrase {tagline_errors['tagline']}, so it was left blank.")
        tagline = ""

    raw = {"version": user_spec.SPEC_VERSION_V2, "name": name, "tagline": tagline, "color": color, "badge": badge,
           "lock_minutes": settings["lock_minutes"], "max_bets_per_day": settings["max_bets_per_day"],
           "stake_units": settings["stake_units"], "rank_by": settings["rank_by"],
           "rules": [copy.deepcopy(r) for r, _s in built]}
    sources = [s for _r, s in built]
    spec, sources = _validate_with_repairs(raw, sources, warnings, taken, lib, quiz_settings)
    final_rules = spec["rules"]
    cards = _cards(spec, sources)
    sentences = render.rule_sentences(spec)
    look = suggest_look(lib, ans, pers)
    return {
        "spec": spec, "english": render.rule_text(spec), "sentences": sentences,
        "global_sentences": render.global_sentences(spec), "rule_cards": cards, "warnings": warnings,
        "name_suggestions": suggestions, "look": look, "breed": (pers or {}).get("breed") or "retriever",
        "vibe": (pers or {}).get("vibe") or "", "personality": (pers or {}).get("id"),
        "archetypes": arch_ids, "settings": {k: spec[k] for k in GLOBAL_KEYS},
        "rule_count": len(final_rules), "starter": starter, "answered": [k for k in ORDER if k in ans],
        "paper_only": True, "not_advice": user_spec.NOT_ADVICE, "honesty": lib_mod.HONESTY_LINE,
    }


def _validate_with_repairs(raw: dict, sources: list, warnings: list, taken: list, lib: Mapping,
                           fallbacks: Mapping) -> tuple:
    """validate_spec, repairing what can be repaired and saying so: a refused rule is dropped, a refused global goes
    back to its default, a refused name or tagline is replaced. Returns (spec, the source of each surviving rule), in
    order. Never loops past a dozen tries."""
    sources = list(sources)
    kept = list(range(len(raw["rules"])))
    defaults = {"max_bets_per_day": lib["defaults"]["max_bets_per_day"], "stake_units": lib["defaults"]["stake_units"],
                "lock_minutes": lib["defaults"]["lock_minutes"], "rank_by": "earliest_lock"}
    defaults.update({k: v for k, v in fallbacks.items() if k in defaults})
    for _ in range(12):
        try:
            spec = user_spec.validate_spec(raw, taken_names=taken)
            return spec, [sources[i] for i in kept]
        except user_spec.SpecError as exc:
            errors = exc.errors
            progressed = False
            bad_rules = sorted({int(k.split("]")[0].split("[")[1]) for k in errors if k.startswith("rules[")}, reverse=True)
            for i in bad_rules:
                first = next(v for k, v in errors.items() if k.startswith(f"rules[{i}]"))
                _warn(warnings, "rule_refused", f"{sources[kept[i]]['name']} was left out: the builder refused it ({first}).")
                del raw["rules"][i]
                del kept[i]
                progressed = True
            for key in GLOBAL_KEYS:
                if key in errors:
                    _warn(warnings, "setting_refused", f"{key.replace('_', ' ').title()} {errors[key]}, so it was ignored.")
                    raw[key] = defaults[key]
                    progressed = True
            if "tagline" in errors:
                raw["tagline"] = ""
                progressed = True
            if "name" in errors:
                raw["name"] = "Starter Pup" if raw["name"] != "Starter Pup" else "Quiz Pup Two"
                progressed = True
            if "rules" in errors and not raw["rules"]:
                starter = _starter_rule(lib)
                _warn(warnings, "starter", "Nothing usable was left, so this is the starter pup: underdog moneylines at plus money.", "note")
                raw["rules"] = [starter]
                kept[:] = [0]
                sources = [{"kind": "personality", "id": STARTER_PERSONALITY, "name": "Underdog Hunter"}]
                progressed = True
            if not progressed:
                raise
    raise user_spec.SpecError({"spec": "the quiz could not compose a valid hound"})


def _starter_rule(lib: Mapping) -> dict:
    p = lib_mod.by_id(lib["personalities"])[STARTER_PERSONALITY]
    return _base_rule("ml", ["moneyline"], p, None, list(user_spec.SPORTS), [])


def _cards(spec: Mapping, sources: list) -> list:
    cards = []
    for i, rule in enumerate(spec["rules"]):
        src = sources[i] if i < len(sources) else {"kind": "english", "id": None, "name": ""}
        cards.append({"index": i, "label": rule.get("label") or src["name"], "source": src["kind"], "source_id": src["id"],
                      "source_name": src["name"], "sentence": render.rule_sentence(rule),
                      "body": render.rule_sentence({**rule, "label": ""}), "sports": rule["sports"],
                      "markets": rule["markets"], "side": rule["side"], "price_min": rule["price_min"],
                      "price_max": rule["price_max"], "conditions": len(list(R.walk(rule.get("when"))))})
    return cards
