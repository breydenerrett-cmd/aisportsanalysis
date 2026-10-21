"""Question 6: which moves to show, and in what order.

Question 6 used to put every card in the library on one screen. It now shows FOUR at a time, picked for the person:

  VALID   a move is offered only if it runs in at least one of the sports picked (`fit.archetype_rules`), and what is
          offered is the move already fitted to those sports: its rules, its English and its sport badge all describe
          what the composer will build, because the composer calls the same fit. A move that cannot run (a weather move
          for a tennis fan) is not offered at all; one that needs MLB or NFL data may run on its generic variant.
  RANKED  by relevance to the earlier answers: the sports (a move made for the picked sports first, then the ones that
          cover most of them), the personality (its stance and the move tags it is drawn to), the price comfort (the
          move's price band against the band the person said they are comfortable with) and the markets (moneyline,
          spread, total, props). A move that pulls AGAINST the personality or the price comfort (a favourite move for an
          underdog hunter) goes to the back, not out: the composer still warns if someone picks it.
  PAGED   the list is ordered in pages of four with variety inside each page (no four cards on one idea). The page
          cycles: "Show me 4 others" is the next page, and the last page wraps to the first.

Pure and deterministic: the same answers always give the same list. No network, no clock, no randomness. A move is a
named rule; the line beside it is not a promise that it wins, and nothing here says so.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Optional

from src.hounds import user_spec
from src.hounds.english import render
from src.hounds.quiz import compose as compose_mod
from src.hounds.quiz import fit
from src.hounds.quiz import library as lib_mod

PAGE = lib_mod.MOVES_PER_PAGE
# a card sharing a tag with one already on the page loses this much, so a page is four ideas and not four of one
TAG_REPEAT_PENALTY = 1.25
STANCE_MATCH, STANCE_CLASH = 3.0, -4.0
COMFORT_MATCH, COMFORT_CLASH = 2.0, -2.0
KIND_MATCH, KIND_MISS = 2.5, -1.5
LIKE_EACH, LIKE_CAP = 1.0, 2.0
MADE_FOR_THEM = 1.5          # a move written for every sport picked beats one that runs anywhere
GENERIC_ONLY = -1.0          # a move that runs only on its generic variant is a step down
EXTRA_RULE = -0.75           # each rule past the first uses a slot of the hound's four and is more to read


def _sports_of(ans: Mapping) -> tuple:
    """(the sports the composer will use, whether the person picked some, whether they picked Any sport)."""
    picked = list(ans.get("sports") or [])
    return (picked or list(user_spec.LEGACY_SPORTS)), bool(picked), bool(ans.get("sports_any"))


def _kinds_wanted(ans: Mapping, lib: Mapping) -> set:
    rows = lib_mod.by_id(lib["markets"])
    kinds: set = set()
    for mid in ans.get("markets") or []:
        kind = rows[mid]["kind"]
        kinds.update({"ml", "total"} if kind == "mix" else {kind})
    return kinds


def _band(move_rules: list) -> tuple:
    lo = min(r["price_min"] for r in move_rules)
    hi = max(r["price_max"] for r in move_rules)
    return user_spec.price_decimal(lo), user_spec.price_decimal(hi)


def _comfort_fit(rules: list, comfort: Mapping) -> float:
    lo, hi = _band(rules)
    c_lo, c_hi = user_spec.price_decimal(comfort["price_min"]), user_spec.price_decimal(comfort["price_max"])
    overlap = min(hi, c_hi) - max(lo, c_lo)
    if overlap <= 0:
        return COMFORT_CLASH
    return COMFORT_MATCH * min(1.0, overlap / max(hi - lo, 1e-9))


def _stance_fit(move_stance: str, wanted: Optional[str], match: float, clash: float) -> float:
    if wanted in (None, "neutral") or move_stance == "neutral":
        return 0.0
    return match if move_stance == wanted else clash


def score(arch: Mapping, fitted: Mapping, ctx: Mapping) -> float:
    """How relevant one fitted move is to the answers. Higher is better; ties are broken by library order."""
    eff = ctx["sports"]
    works = set(fit.resolve_sports(arch["works_in"]))
    s = 2.0 * len([c for c in fitted["covers"] if c in eff]) / max(len(eff), 1)
    if ctx["picked"] and set(eff) <= works and not works >= set(user_spec.SPORTS):
        s += MADE_FOR_THEM                   # written for ALL the sports picked (a move for one of three is not "made for them")
    if fitted["generic"] and not works & set(eff):
        s += GENERIC_ONLY
    s += EXTRA_RULE * (len(fitted["rules"]) - 1)
    pers, comfort = ctx["personality"], ctx["comfort"]
    if pers:
        s += _stance_fit(arch["stance"], pers["stance"], STANCE_MATCH, STANCE_CLASH)
        s += min(LIKE_CAP, LIKE_EACH * len(set(pers.get("likes") or []) & set(arch.get("tags") or [])))
    if comfort:
        s += _comfort_fit(fitted["rules"], comfort)
        s += _stance_fit(arch["stance"], comfort["stance"], 1.0, -1.0)
    if ctx["kinds"]:
        s += KIND_MATCH if set(arch["kinds"]) & ctx["kinds"] else KIND_MISS
    return round(s, 6)


def _short_for(arch: Mapping, fitted: Mapping, eff: list) -> str:
    """The card's plain-English line: the move's own, or its generic variant's when that is all that runs."""
    generic = arch.get("generic") or {}
    full = [c for c in fitted["covers"] if c in fit.resolve_sports(arch["works_in"])]
    if fitted["generic"] and not full and generic.get("short"):
        return generic["short"]
    return arch["short"]


def _card(arch: Mapping, fitted: Mapping, sentences: list, ctx: Mapping, lib: Mapping) -> dict:
    return {"id": arch["id"], "name": arch["name"], "short": _short_for(arch, fitted, ctx["sports"]), "icon": arch["icon"],
            "stance": arch["stance"], "tags": list(arch.get("tags") or []), "kinds": list(arch["kinds"]),
            "sports": list(fitted["covers"]),
            "sport_badge": lib_mod.sport_badge_text(fitted["covers"], lib, any_picked=ctx["any_picked"]),
            "partial": bool(fitted["partial"] and ctx["picked"]), "generic": bool(fitted["generic"]),
            "rule_count": len(fitted["rules"]), "english": " ".join(sentences), "sentences": sentences}


def valid_moves(answers: Any, lib: Optional[Mapping] = None) -> tuple:
    """(the valid moves in library order as [(archetype, fitted rules, sentences)], the ids the validator refused). The
    refused list is empty unless the library itself is broken; a test holds it empty for every sport combination."""
    lib = lib if lib is not None else lib_mod.load()
    ans = compose_mod.clean_answers(answers, lib, [])
    eff, _picked, _any = _sports_of(ans)
    no_home = lib_mod.no_home_side(lib)
    out: list = []
    refused: list = []
    for arch in lib["archetypes"]:
        fitted = fit.archetype_rules(arch, eff, no_home)
        if not fitted["rules"]:
            continue
        rules = copy.deepcopy(fitted["rules"])
        for rule in rules:
            if not rule.get("label"):
                rule["label"] = arch["name"]
        try:
            spec = user_spec.validate_spec({"version": user_spec.SPEC_VERSION_V2, "name": lib_mod.PLACEHOLDER_NAME,
                                            "tagline": "", "rules": rules})
        except user_spec.SpecError:
            refused.append(arch["id"])
            continue
        out.append((arch, fitted, render.rule_sentences(spec)))
    return out, refused


def _pages(entries: list, scores: dict) -> list:
    """Order the moves in pages of PAGE: best first, with variety inside each page, then the next best, and so on."""
    index = {e[0]["id"]: i for i, e in enumerate(entries)}
    remaining = sorted(entries, key=lambda e: (-scores[e[0]["id"]], index[e[0]["id"]]))
    ordered: list = []
    while remaining:
        page: list = []
        tags: list = []
        while remaining and len(page) < PAGE:
            def net(e):
                shared = len(set(e[0].get("tags") or []) & set(tags))
                return scores[e[0]["id"]] - TAG_REPEAT_PENALTY * shared
            best = max(remaining, key=lambda e: (net(e), -index[e[0]["id"]]))
            remaining.remove(best)
            page.append(best)
            tags.extend(best[0].get("tags") or [])
        ordered.extend(page)
    return ordered


def _window(cards: list, page: int) -> tuple:
    """(the cards on `page`, the page number actually used, how many pages). Every page holds PAGE cards: the last one is
    filled from the front of the list, so the cycle never shows a short page. A page number past the end wraps."""
    pages = max(1, -(-len(cards) // PAGE))
    used = (page if isinstance(page, int) and not isinstance(page, bool) else 0) % pages
    start = used * PAGE
    return [cards[(start + i) % len(cards)] for i in range(min(PAGE, len(cards)))], used, pages


def _ranked(answers: Any, lib: Mapping) -> tuple:
    """(the cleaned answers, the cards best first, the context): shared by `suggest` and `pick_for_me`."""
    warnings: list = []
    ans = compose_mod.clean_answers(answers, lib, warnings)
    eff, picked, any_picked = _sports_of(ans)
    entries, _refused = valid_moves(answers, lib)
    ctx = {"sports": eff, "picked": picked, "any_picked": any_picked,
           "personality": lib_mod.by_id(lib["personalities"]).get(ans.get("personality")),
           "comfort": lib_mod.by_id(lib["price_comforts"]).get(ans.get("price_comfort")),
           "kinds": _kinds_wanted(ans, lib)}
    scores = {arch["id"]: score(arch, fitted, ctx) for arch, fitted, _s in entries}
    cards = [_card(arch, fitted, sentences, ctx, lib) for arch, fitted, sentences in _pages(entries, scores)]
    return ans, cards, ctx


def suggest(answers: Any, lib: Optional[Mapping] = None, page: int = 0) -> dict:
    """POST /hounds/quiz/moves: the four moves on `page` (0 is the first four), most relevant first, as cards.

    "Show me 4 others" asks for page + 1; the last page is filled from the front and the one after it wraps to the first, so
    the cycle never runs dry. `recommended` is the one move Pick for me would take. `order` is every valid move's id, best
    first. `dropped` lists moves the person had already picked that no longer run in the sports they now have, so the page
    can take them off the pick list."""
    lib = lib if lib is not None else lib_mod.load()
    ans, cards, ctx = _ranked(answers, lib)
    shown, used, pages = _window(cards, page)
    offered = {c["id"] for c in cards}
    return {"moves": shown, "page": used, "pages": pages, "next_page": (used + 1) % pages, "page_size": PAGE,
            "total": len(cards), "order": [c["id"] for c in cards], "recommended": cards[0]["id"] if cards else None,
            "recommended_card": cards[0] if cards else None, "pick_limit": lib_mod.PICK_LIMIT,
            "dropped": [a for a in ans.get("archetypes") or [] if a not in offered],
            "markets_available": markets_available(ctx["sports"], lib),
            "sports": ctx["sports"], "sports_picked": ctx["picked"], "sports_any": ctx["any_picked"],
            "paper_only": True, "not_advice": user_spec.NOT_ADVICE}


def pick_for_me(answers: Any, lib: Optional[Mapping] = None) -> dict:
    """The single move that suits the earlier answers best: {id, card} (None when no move runs). Deterministic: the same
    answers always pick the same move. It is the top of the same list question 6 pages through."""
    lib = lib if lib is not None else lib_mod.load()
    _ans, cards, _ctx = _ranked(answers, lib)
    return {"id": cards[0]["id"] if cards else None, "card": cards[0] if cards else None}


def markets_available(sports: list, lib: Optional[Mapping] = None) -> list:
    """See library.markets_available: the market options the sports picked post."""
    return lib_mod.markets_available(sports, lib)
