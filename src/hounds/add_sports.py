"""Add sports to an existing member hound, as a NEW VERSION (``python -m src.cli hounds add-sports``).

WHY A NEW VERSION AND NEVER AN EDIT. A hound's record belongs to the exact rule that produced it (``user_spec.spec_hash``),
so widening its sports is a rule change like any other: ``user_store.create_version`` retires the old version with its
record intact and starts version n+1, the same path Retune and Apply use. Nothing here writes a hound row any other way.

HOW A RULE IS MIRRORED. For each added sport and each existing rule the plan makes the closest honest copy:
  * markets: only the ones the catalog says the sport has (tennis and MMA have a moneyline, soccer a moneyline and a total).
    A prop rule carries only to a sport whose prop markets (``user_rules.PROP_SPORT_MARKETS``) include every prop it names;
    MLB props (batter hits) have no NBA twin, so they are skipped rather than renamed.
  * conditions: kept when the validator accepts them for that sport (the price band, minimum books, favourite/underdog, line
    movement, day of week...). Form, rest and home-cooking conditions read MLB/NFL box scores, so for any other sport they are
    left out and SAID in the notes. A team, opponent or player condition names one league's clubs and never carries over.
    A rule whose whole condition tree falls away is skipped for that sport: it would otherwise bet every game in the band.
  * line bounds are a sport's own scale (a 1.5 run line is not a 7-point spread), so a rule with line bounds carries its
    moneyline only.
Everything else on the hound (bets a day, stake, lock minutes, rank, the price band and so the -200 floor) is kept exactly;
the finished spec goes through ``validate_spec``, the builder's own normalizer, before anything is written.

Sports that cannot be added are reported with the reason: a family off the dog menu (no result source to grade it).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from src.hounds import user_rules as R
from src.hounds import user_spec, user_store
from src.sports import catalog

MARKET_OF_ODDS_KEY = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}
#: conditions that name one league's teams or players: never copied to another sport
TEAM_SPECIFIC = frozenset({"team_is", "opponent_is", "player_is"})
ACTOR = "owner-cli:add-sports"


class AddSportsError(ValueError):
    pass


def gradable_sports() -> List[str]:
    """Every family a member hound can be graded on: on the dog menu (which the catalog gives only to families with a result source)."""
    return list(user_spec.SPORTS)


def not_gradable() -> List[tuple]:
    out = []
    for code in catalog.family_codes():
        if code not in user_spec.SPORTS:
            out.append((code, "no result source to grade it (off the dog menu)"))
    return out


def _game_markets(sport: str) -> List[str]:
    return [MARKET_OF_ODDS_KEY[m] for m in catalog.markets_for(sport) if m in MARKET_OF_ODDS_KEY]


def _carries(cond_id: str, sport: str) -> bool:
    cond = R.BY_ID.get(cond_id)
    if cond is None or cond_id in TEAM_SPECIFIC:
        return False
    return cond.any_sport or sport in cond.sports


def _filter_tree(tree: Optional[Mapping], sport: str, dropped: list) -> Optional[dict]:
    if not tree:
        return None
    items = []
    for item in tree.get("items", []):
        if "items" in item:
            sub = _filter_tree(item, sport, dropped)
            if sub:
                items.append(sub)
        elif _carries(item["id"], sport):
            items.append(copy.deepcopy(item))
        else:
            dropped.append(R.BY_ID[item["id"]].label if item["id"] in R.BY_ID else item["id"])
    return {"op": tree.get("op", "all"), "items": items} if items else None


def _mirror(rule: Mapping, sport: str) -> tuple:
    """(new rule | None, dropped condition labels, why skipped | None)."""
    markets = list(rule["markets"])
    if R.market_kind(markets[0]) == "prop":
        keep = [m for m in markets if m in R.PROP_SPORT_MARKETS.get(sport, ())]
        if not keep:
            return None, [], f"its prop markets ({', '.join(markets)}) have no twin in that sport"
    else:
        keep = [m for m in markets if m in _game_markets(sport)]
        if rule.get("line_min") is not None or rule.get("line_max") is not None:
            keep = [m for m in keep if m == "moneyline"]
        if not keep:
            return None, [], "the sport has none of its markets" + (" (line bounds are a sport's own scale)" if rule.get("line_min") is not None or rule.get("line_max") is not None else "")
    dropped: list = []
    tree = _filter_tree(rule.get("when"), sport, dropped)
    if rule.get("when") and tree is None:
        return None, dropped, "none of its conditions apply to that sport"
    new = {k: copy.deepcopy(rule.get(k)) for k in user_spec.V2_RULE_KEYS}
    new["sports"], new["markets"], new["when"] = [sport], keep, tree
    if keep != markets and rule.get("line_min") is not None:
        new["line_min"] = new["line_max"] = None
    problems: dict = {}
    new = user_spec._validate_rule(new, 0, problems)          # the builder's own rule check, so one bad twin skips itself
    if new is None:
        return None, dropped, "the validator refused it: " + "; ".join(f"{k} {v}" for k, v in list(problems.items())[:2])
    return new, dropped, None


def _raw_spec(spec: Mapping) -> dict:
    if not user_spec.is_v2(spec):
        spec = user_spec.upgrade_v1(spec)
    if user_spec.is_gematria(spec):
        raise AddSportsError("a Gematria hound has a fixed rule set; it cannot be given sports")
    if not spec.get("rules"):
        raise AddSportsError("this hound has no rules to mirror (an Apprentice with no applied proposal)")
    raw = {k: copy.deepcopy(spec[k]) for k in user_spec.V2_TOP_KEYS
           if k in spec and k not in user_spec.V2_DERIVED_KEYS}
    if spec.get("style"):
        raw["style"] = spec["style"]
    return raw


def parse_sports(text: str, have: Iterable[str]) -> tuple:
    """(requested, skipped [(code, why)]). ``all`` means every gradable family; a family already on the hound is skipped."""
    asked = [t.strip().upper() for t in str(text or "").split(",") if t.strip()]
    if not asked:
        raise AddSportsError("name at least one sport (or all)")
    requested, skipped = [], []
    codes = gradable_sports() if "ALL" in asked else asked
    for code in codes:
        if code in have:
            skipped.append((code, "already on the hound"))
        elif code not in user_spec.SPORTS:
            skipped.append((code, "not a sport a hound can be graded on"))
        elif code not in requested:
            requested.append(code)
    if "ALL" in asked:
        skipped.extend(not_gradable())
    return requested, skipped


def plan(hound: Mapping, sports_text: str) -> dict:
    """The new raw spec and the notes, with nothing written. Raises ``AddSportsError`` / ``SpecError``."""
    raw = _raw_spec(hound["spec"])
    have = set(hound["spec"].get("sports") or [])
    requested, skipped = parse_sports(sports_text, have)
    if not requested:
        raise AddSportsError("nothing to add: " + "; ".join(f"{c} {w}" for c, w in skipped))
    rules = raw["rules"]
    original = copy.deepcopy(rules)
    notes, groups = {}, []                       # groups: [key, new rule]
    added = []
    for sport in requested:
        got = False
        for i, rule in enumerate(original):
            new, dropped, why = _mirror(rule, sport)
            label = rule.get("label") or f"rule {i + 1}"
            if new is None:
                notes.setdefault(f"{label} skipped, {why}", []).append(sport)
                continue
            if dropped:
                notes.setdefault(f"{label} without " + ", ".join(sorted(set(dropped))), []).append(sport)
            key = json.dumps({k: v for k, v in new.items() if k != "sports"}, sort_keys=True)
            same = json.dumps({k: v for k, v in rule.items() if k != "sports"}, sort_keys=True)
            if key == same:                      # identical to the original: just widen it
                if sport not in rules[i]["sports"]:
                    rules[i]["sports"].append(sport)
            else:
                for g in groups:
                    if g[0] == key:
                        g[1]["sports"].append(sport)
                        break
                else:
                    groups.append([key, new])
            got = True
        if got:
            added.append(sport)
        else:
            skipped.append((sport, "no rule of this hound carries over"))
    rules.extend(g[1] for g in groups)
    if len(rules) > R.MAX_RULES:
        raise AddSportsError(f"this would make {len(rules)} rules (the most a hound has is {R.MAX_RULES}); add fewer sports at a time")
    spec = user_spec.validate_spec(raw)          # the builder's own normalizer; the name check is the version path's job
    if not added:
        raise AddSportsError("nothing to add: " + "; ".join(f"{c} {w}" for c, w in skipped))
    return {"raw": raw, "spec": spec, "added": added, "skipped": skipped,
            "notes": [f"{', '.join(v)}: {k}" for k, v in notes.items()],
            "sentence": user_spec.rule_text(spec)}


def apply(hound_id: str, sports_text: str, *, dry_run: bool = False, db=None) -> dict:
    hound = user_store.get_hound(hound_id, db=db)
    if hound is None:
        raise AddSportsError(f"no hound {hound_id}")
    out = plan(hound, sports_text)
    out["old_id"], out["new_id"], out["dry_run"] = hound_id, None, dry_run
    if not dry_run:
        new = user_store.create_version(hound_id, out["raw"], actor=ACTOR,
                                        reason="sports added: " + ", ".join(out["added"]), db=db)
        out["new_id"] = new["id"]
    return out
