"""Which sports a rule can run in, and how a rule is fitted to the sports a person picked.

WHY THIS EXISTS
---------------
The quiz used to offer MLB and NFL, and every card was written for those two. It now offers every sport on the dog menu
(`config/sports_catalog.json`, `dog_menu: true`) plus "Any sport". Most conditions work for any sport (the pick is the
underdog, a night game, the line moved, the day of the week, the moon, a seeded coin); a few read MLB or NFL data that
exists for no other sport (rest days, streaks, head-to-head, team stats, weather, player props). The builder's validator
refuses a rule that mixes a sport with a condition that cannot run there, so the quiz must fit each rule to the sports
picked BEFORE it builds the spec. This module is that one fitting step, shared by the composer (what the hound gets) and
the move picker (what question 6 offers), so a move that is offered is a move that composes.

THE FIT, FOR ONE RULE AND A LIST OF SPORTS
------------------------------------------
A rule RUNS IN a sport when all of these hold (`rule_runs_in`):
  * every condition in its `when` tree works for the sport (`user_rules.Cond.any_sport`, else the condition's own `sports`);
  * at least one of its markets is posted for the sport (the catalog's `markets`: tennis has moneylines only, soccer has
    moneylines and totals, ...), and player props are MLB only (the validator's rule);
  * a home or away side is not asked of a sport with no home side (tennis, MMA).
`fit_rule` splits the sports into the ones the rule runs in (the rule is kept, narrowed to them) and the rest. For the
rest, a rule that carries a GENERIC variant (a list of conditions to drop and fields to set) yields a second rule with those
conditions removed; with no variant the rest are simply not covered, and the composer says so.

Nothing here invents a rule: a generic variant is the same rule with conditions taken OUT (and, for a personality, one stated
override such as a higher book minimum), written in the library file. Pure functions: no network, no clock, no randomness.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping, Optional, Sequence

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.sports import catalog as sports_catalog

ANY = user_spec.ANY
MARKET_OF = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}


def all_sports() -> list:
    """Every family on the dog menu, in the validator's canonical order."""
    return list(user_spec.SPORTS)


def resolve_sports(items: Optional[Iterable[str]]) -> list:
    """The explicit, canonically ordered sport list for a library `sports`/`works_in` value. "ANY" (alone or among others)
    means every dog-menu family, resolved NOW so a family added to the catalog later is picked up without editing the file."""
    items = list(items or [])
    if ANY in items:
        return all_sports()
    return [s for s in user_spec.SPORTS if s in items]


def family_markets(sport: str) -> set:
    """The rule markets ('moneyline', 'spread', 'total') posted for a family, from the catalog."""
    return {MARKET_OF[m] for m in sports_catalog.markets_for(sport) if m in MARKET_OF}


def cond_runs_in(cond_id: str, sport: str) -> bool:
    cond = R.BY_ID.get(cond_id)
    if cond is None:
        return False
    return bool(cond.any_sport or sport in cond.sports)


def condition_ids(rule: Mapping) -> list:
    return [c["id"] for c in R.walk(rule.get("when"))]


def rule_runs_in(rule: Mapping, sport: str, no_home_side: Sequence[str] = ()) -> bool:
    markets = list(rule.get("markets") or [])
    if not markets:
        return False
    if R.market_kind(markets[0]) == "prop":
        return sport == "MLB"
    if not any(m in family_markets(sport) for m in markets):
        return False
    if rule.get("side") in ("home", "away") and sport in no_home_side:
        return False
    return all(cond_runs_in(cid, sport) for cid in condition_ids(rule))


def runs_in(rule: Mapping, sports: Iterable[str], no_home_side: Sequence[str] = ()) -> list:
    return [s for s in sports if rule_runs_in(rule, s, no_home_side)]


def _prune(tree: Optional[Mapping], drop: set) -> Optional[dict]:
    if not tree:
        return None
    items: list = []
    for item in tree.get("items") or []:
        if "items" in item:
            sub = _prune(item, drop)
            if sub:
                items.append(sub)
        elif item.get("id") not in drop:
            items.append(copy.deepcopy(dict(item)))
    return {"op": tree.get("op", "all"), "items": items} if items else None


def without_conditions(rule: Mapping, drop: Iterable[str]) -> dict:
    """A copy of the rule with the named conditions taken out of its `when` tree (the tree is None when nothing is left)."""
    out = copy.deepcopy(dict(rule))
    out["when"] = _prune(rule.get("when"), set(drop))
    return out


def fit_rule(rule: Mapping, sports: Sequence[str], *, no_home_side: Sequence[str] = (),
             drop: Any = None, set_fields: Optional[Mapping] = None) -> list:
    """The rule fitted to `sports`: a list of (rule, kind) where kind is 'full' (the rule, narrowed to the sports it runs in)
    or 'generic' (the variant for the sports it does not run in). `drop` is a list of condition ids, or "unsupported" to drop
    every condition the leftover sports cannot run; `set_fields` overrides rule fields on the variant (a book minimum).
    An empty list means the rule runs in none of the sports and has no variant that does."""
    sports = list(sports)
    out: list = []
    covered = runs_in(rule, sports, no_home_side)
    if covered:
        full = copy.deepcopy(dict(rule))
        full["sports"] = covered
        out.append((full, "full"))
    rest = [s for s in sports if s not in covered]
    if rest and (drop or set_fields):
        ids = condition_ids(rule)
        if drop == "unsupported":
            gone = {cid for cid in ids if any(not cond_runs_in(cid, s) for s in rest)}
        else:
            gone = set(drop or ())
        variant = without_conditions(rule, gone)
        variant.update(copy.deepcopy(dict(set_fields or {})))
        reachable = runs_in(variant, rest, no_home_side)
        if reachable and variant != rule:
            variant["sports"] = reachable
            out.append((variant, "generic"))
    return out


def archetype_rules(arch: Mapping, chosen: Sequence[str], no_home_side: Sequence[str] = ()) -> dict:
    """An archetype fitted to the sports picked: {rules, covers, generic, partial}.

    `rules` are the library rules narrowed to `chosen` (plus a generic variant for the picked sports the rule's conditions
    cannot reach, when the archetype declares one); `covers` is the picked sports they run in, in the validator's order;
    `partial` is True when some picked sport is not covered; `generic` is True when any rule is a generic variant. No rules
    means the archetype is not offered for these sports."""
    works = resolve_sports(arch.get("works_in"))
    drop = (arch.get("generic") or {}).get("drop")
    chosen = [s for s in chosen if s in user_spec.SPORTS]
    rules: list = []
    covers: set = set()
    generic = False
    for frag_rule in arch["fragment"]["rules"]:
        base = {**frag_rule, "sports": resolve_sports(frag_rule.get("sports"))}
        own = [s for s in chosen if s in works and s in base["sports"]]
        held: set = set()
        for rule, _kind in fit_rule(base, own, no_home_side=no_home_side):
            rules.append(rule)
            held.update(rule["sports"])
        if drop:
            left = [s for s in chosen if s not in held]
            for rule, kind in fit_rule(base, left, no_home_side=no_home_side, drop=list(drop)):
                if kind == "generic":
                    generic = True
                    rules.append(rule)
                    held.update(rule["sports"])
        covers.update(held)
    order = [s for s in user_spec.SPORTS if s in covers]
    return {"rules": rules, "covers": order, "generic": generic,
            "partial": bool(rules) and any(s not in covers for s in chosen)}
