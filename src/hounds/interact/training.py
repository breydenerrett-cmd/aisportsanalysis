"""Send to training: a member's dog studies its own settled tickets and comes back as a new version.

THE RULING (Brey, 2026-10-20): the other path is a dog "coached and transformed into a new updated version that
fixes itself with learned behavior and seeks AI guidance for making better choices after analysis", like
evolving in a Pokemon game. This module is that path; ``outback.py`` is the other one.

WHAT HAPPENS, IN ORDER
  1. ``rites.guard``: a member's dog, its owner, still alive. Refused while a ticket is unsettled (``rites``).
  2. THE LIMITS. A dog that has never been trained may train at once; if it has fewer than ``MIN_NEW_SETTLED`` settled
     bets the first training is a LIGHT ADJUSTMENT and says so. Once a lineage has trained, the version it is on must
     have ``MIN_NEW_SETTLED`` NEW settled bets of its own before it can train again (a record that has not had time to
     say anything is not something to coach on).
  3. ``analyse``: the dog's own settled bets cut by sport, market, price band, home or away (over or under), favourite
     or underdog, and the rule that made them. A segment is a weak spot only when it clears THE EVIDENCE BAR: at least
     ``MIN_SEGMENT_BETS`` bets, units below zero, and a sample-size level of ``MIN_SEGMENT_LEVEL`` or better from the same
     ``diagnosis.level_of`` the coach's table uses (a cut can be big and still sit inside what luck does). Worst first.
     A hound's CORE (``identity.py``: the sports and markets it is for, read from its name, its words or its spec) is never a
     weak spot, so it is never proposed for removal. 2026-10-29: HOCKEYCHIEF's card cut NHL, its whole point, off 5 bets that
     went 2-3 while the coach's own read said the run turns up in 78% of random orders. When no segment clears the bar the
     default proposal is "Keep going: no change" (mode ``keep``): nothing is changed, nothing is written, and the card says
     so in numbers (``keep_message``). A first training under ``MIN_NEW_SETTLED`` bets is still the labelled light adjustment.
  3b. THE COACH (owner request 2026-10-21, "matrix-level"): before anything is proposed the coach reads a wider table than step
     3's, ``diagnosis.diagnose`` (price band, side, sport, market, day of the week, slate time, rest, line movement, books
     quoting, betting days, the daily limit, rules, losing runs, pairs that went wrong together, each with its own sample-size
     level), and Claude Haiku ranks the most likely reasons from it (``coach_ai``; the rules engine reads when the model is capped
     or down). The page runs this as two read-only steps first (``read_step``: ``/train/diagnose``, ``/train/assess``), cached by
     ``coach``, and the training takes the cached read. The model can only reorder the menu (``menu``): a pick that is not on it is
     ignored, and every pick is re-validated below. The spend is written to the ``trained`` event and the log.
  4. ``propose``: one to ``MAX_CHANGES`` concrete changes to the spec, each aimed at a weak spot, each one that only
     NARROWS what the dog does (a sport or market dropped, a price band tightened, one side dropped, a favourite or
     underdog condition added, more books required, fewer bets a day). That is the same rule the Houndmaster coach
     lives by (``user_coach.narrowing_problems``): a change may make a dog more careful, never more exposed, so the
     -200 cap is untouched by construction, and every change is run through ``user_spec.validate_spec`` anyway. A
     change that does not validate is dropped, never repaired. The choice is deterministic: the same bets and the same
     rule always give the same changes.
  5. ``user_store.create_version``: the old version is retired with its record frozen, a NEW version starts with an empty
     record, stamped ``coached_from`` the old one, and one ``trained`` event is written in the same transaction.

PROPOSAL, REVIEW, APPLY (owner ruling 2026-10-22: "players should have a choice to veto the upgrade or tell it to tweak the
changes and why"). Steps 3 to 4 no longer write anything on their own. ``review`` builds the proposal card (the changes, a reason
for each, what today's board would have said), ``veto`` says no (nothing changes and it does not count against the limit), a
``tweak`` maps the owner's words to the same closed menu through Claude Haiku or the rules engine (at most three rounds), and only
``train`` with the owner's confirm and the ids they left ticked (``picks``) performs step 5. The menu also holds LOOSENING changes
(``retune.py``) for the paths where the owner asked: a Retune from the Ask chat, a tweak, and the default for a hound that has not
placed a settled bet, which is never narrowed (production 2026-10-22: a Gematria hound with no bets was sent from 3 bets a day to
2). The new version of a retune is marked ``owner retune (from chat)`` in its lineage (``user_store`` ``origin``).

WHAT IT NEVER SAYS. Nothing here claims the new version is better, will win, or fixes anything. A weak spot is a fact
about the past ("its 6 away-side tickets went 1-5"); a change is "no longer takes them"; the card ends with "its new
record starts now". The hindsight line is labelled hindsight: it counts what the change would have left out of the
bets already settled, which the coach could see, so it is a rehearsal and not evidence (the same stance as
``coach_grade``'s hindsight grade).

WHAT IT REUSES. ``coach_card.change_sentence`` writes the one-line change list the report card uses;
``breeding.cross``'s grid helpers step the numeric knobs (books, bets a day) one grid step and ``cross.rng_for`` is the
deterministic tie-break for the light adjustment; ``english.render.diff_specs`` is the plain-English before/after;
``learning.coach_brief`` supplies the data notice and the size cap for the optional AI brief. ``coach_grade`` itself
grades house-pack shadow runs over the pack ledger, which a member's dog does not have, so its hindsight idea is
reused here as a count over the dog's own settled bets rather than as a replay.

THE AI PARAGRAPH IS OPTIONAL AND NEVER BLOCKS. The shown guidance is always written by code from the analysis. When the
owner's Zapier hook is configured (``english.translate.hook_url``) the brief is also POSTed to it from a background
thread with a short timeout, so the owner's Zap can have a model take a second look; the request returns without waiting
and a hook that is down or slow changes nothing. The reply, if any, is not read back (there is no callback for it).

Paper only. Nothing here places or suggests a bet.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import coach_card, stats, user_rules, user_spec, user_store
from src.hounds.breeding import cross
from src.hounds.interact import common, identity, loss_why, revert, rites, store
from src.hounds.interact.rites import RiteError

logger = logging.getLogger("linehound.hounds.training")

MIN_NEW_SETTLED = 5          # settled bets a version needs before it can train again (and for a non-light first training)
# THE EVIDENCE BAR (2026-10-29). Three bets was the old floor and a 2-3 record on five was enough to cut a sport. Ten is the least
# a cut can hold before units per bet mean anything; and ten bets can still be a coin flip, so the slice must also reach the
# sample-size level the coach's own table calls "some signal" (``diagnosis.level_of``: at least 10 bets and its units per bet
# a full standard error below the rest of the hound's bets; "weak signal" and under is within what luck does).
MIN_SEGMENT_BETS = 10
MIN_SEGMENT_LEVEL = "medium"
_LEVEL_RANK = {"too_few": 0, "low": 1, "medium": 2, "high": 3}
MAX_CHANGES = 3
HOOK_TIMEOUT_S = 4           # the optional AI brief never holds a training for longer than this (it is a background post)

CONFIRM_FIELD = "confirm"

# The price bands the analysis cuts by, shortest price first (decimal-odds order, not the American number line: -110 is
# shorter than +100). Contiguous and covering the whole menu range, so every priced bet lands in exactly one.
PRICE_BANDS = (
    ("short_favourites", "short favourites", "-199 to -151", -199, -151),
    ("favourites", "favourites", "-150 to -111", -150, -111),
    ("near_even", "near even", "-110 to +109", -110, 109),
    ("underdogs", "underdogs", "+110 to +199", 110, 199),
    ("long_shots", "long shots", "+200 and up", 200, user_spec.LONGEST_ALLOWED_PRICE),
)
_BAND_BY_KEY = {b[0]: i for i, b in enumerate(PRICE_BANDS)}

VENUE_LABELS = {"home": "home-side", "away": "away-side", "over": "over", "under": "under"}
_OPPOSITE_VENUE = {"home": "away", "away": "home", "over": "under", "under": "over"}
ROLE_LABELS = {"favourite": "favourite", "underdog": "underdog"}
_OPPOSITE_ROLE = {"favourite": "underdog", "underdog": "favourite"}

# The numeric knobs a careful nudge moves, as the grid helpers in breeding.cross expect them (lo, hi, step, kind).
class _Knob:
    def __init__(self, lo, hi, step, kind="int"):
        self.lo, self.hi, self.step, self.kind = lo, hi, step, kind


BOOKS_KNOB = _Knob(user_spec.MIN_BOOKS_RANGE[0], user_spec.MIN_BOOKS_RANGE[1], 1)
BETS_KNOB = _Knob(user_spec.MAX_BETS_RANGE[0], user_spec.MAX_BETS_RANGE[1], 1)

DIMENSIONS = ("sport", "market", "band", "venue", "role", "rule")
DIMENSION_NOUN = {"sport": "sport", "market": "market", "band": "price band", "venue": "side", "role": "kind of pick",
                  "rule": "rule"}


# ---------------------------------------------------------------------------
# the bets, cut up
# ---------------------------------------------------------------------------

def band_of(price) -> Optional[str]:
    """The key of the price band an American price falls in, or None for no usable price. A price worse than the first
    band (an old -200 ticket) reads as that band; one past the last reads as the last."""
    if not isinstance(price, (int, float)) or isinstance(price, bool) or abs(price) < 100:
        return None
    d = user_spec.price_decimal(price)
    for key, _name, _range, _lo, hi in PRICE_BANDS:
        if d <= user_spec.price_decimal(hi) + 1e-9:
            return key
    return PRICE_BANDS[-1][0]


# The ledger reader names the three game markets by the odds feed's words; the menu (and so a spec) uses these.
MARKET_OF_KEY = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}


def market_of(bet) -> Optional[str]:
    """The spec's name for the market a bet was on ("moneyline", "spread", "total", or a prop market's own name)."""
    key = bet.market_key
    return MARKET_OF_KEY.get(key, key) or None


def role_of(bet) -> Optional[str]:
    """Favourite or underdog for a moneyline (by its price) or a spread (by the sign of the pick's own line). A total or
    a prop has none."""
    market = market_of(bet)
    if market == "moneyline":
        price = bet.price_average if bet.price_average is not None else bet.price
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            return "favourite" if price < 0 else "underdog"
    elif market == "spread":
        try:
            line = float(bet.line)
        except (TypeError, ValueError):
            return None
        return "favourite" if line < 0 else "underdog" if line > 0 else None
    return None


def _units_of(bet) -> float:
    units = stats.average_units(bet)
    if units is None:
        units = stats.recorded_units(bet)
    return float(units) if units is not None else 0.0


def facts(bets: Sequence, spec: Mapping, rule_index: Optional[Mapping] = None) -> list:
    """One flat dict per SETTLED forward bet (win, loss, push): what the analysis cuts by."""
    out = []
    for b in bets:
        if b.result not in rites.SETTLED_RESULTS:
            continue
        price = b.price_average if b.price_average is not None else b.price
        side = b.side if b.side in VENUE_LABELS else None
        out.append({"result": b.result, "units": _units_of(b), "sport": str(b.sport or "").upper() or None,
                    "market": market_of(b), "band": band_of(price), "venue": side, "role": role_of(b),
                    "rule": (rule_index or {}).get(b.bet_id) if user_spec.is_v2(spec) else None})
    return out


def _label(spec: Mapping, dimension: str, key) -> tuple:
    """``(label, phrase)``: the segment's short name, and how a sentence says its bets ("9 MLB bets")."""
    if dimension == "sport":
        name = user_spec.SPORT_LABELS.get(key, str(key))
        return name, f"{name} bets"
    if dimension == "market":
        name = user_rules.MARKET_LABELS.get(key, str(key)).lower()
        return name, f"{name} bets"
    if dimension == "band":
        _k, name, rng, _lo, _hi = PRICE_BANDS[_BAND_BY_KEY[key]]
        return f"{name} ({rng})", f"bets priced {rng}"
    if dimension == "venue":
        return VENUE_LABELS[key], f"{VENUE_LABELS[key]} bets"
    if dimension == "role":
        return ROLE_LABELS[key], f"{ROLE_LABELS[key]} picks"
    rules = spec.get("rules") or []
    if isinstance(key, int) and 0 <= key < len(rules):
        name = (rules[key].get("label") or "").strip()
        label = f"rule {key + 1}" + (f" ({name})" if name else "")
    else:
        label = f"rule {key}"
    return label, f"{label} bets"


def _tally(rows: Sequence) -> dict:
    wins = sum(1 for r in rows if r["result"] == "win")
    losses = sum(1 for r in rows if r["result"] == "loss")
    pushes = sum(1 for r in rows if r["result"] == "push")
    return {"n": len(rows), "wins": wins, "losses": losses, "pushes": pushes,
            "units": round(sum(r["units"] for r in rows), 2)}


def _clears_the_bar(group: Sequence[Mapping], rows: Sequence[Mapping]) -> bool:
    """True when a segment is big enough AND its units per bet sit far enough below the rest of the hound's bets to be a signal
    (``MIN_SEGMENT_BETS`` and ``MIN_SEGMENT_LEVEL``, by the coach table's own ``diagnosis.level_of`` and z). A segment that is
    only losing because the rest is losing more (z at or above zero) is not a weak spot of its own."""
    n = len(group)
    if n < MIN_SEGMENT_BETS:
        return False
    from src.hounds.interact import diagnosis        # at call time: diagnosis imports this module
    ids = {id(r) for r in group}
    z = diagnosis._z([r["units"] for r in group], [r["units"] for r in rows if id(r) not in ids])      # noqa: SLF001
    if z is None or z >= 0:
        return False
    return _LEVEL_RANK[diagnosis.level_of(n, z)] >= _LEVEL_RANK[MIN_SEGMENT_LEVEL]


def analyse(bets: Sequence, spec: Mapping, rule_index: Optional[Mapping] = None, *, core: Optional[Mapping] = None) -> dict:
    """The dog's settled bets cut every way, and the weak spots.

    ``{"settled", "overall", "segments": {dimension: [segment]}, "weak": [segment], "held": [segment], "core"}`` where a
    segment is ``{dimension, key, label, n, wins, losses, pushes, units}``. ``weak`` holds the segments that clear the evidence
    bar (``_clears_the_bar``) and lost units, from a dimension that splits the bets at least two ways (a dimension with one value
    cannot be narrowed), worst units first, then the larger sample, then the dimension order and the key, so the order never
    depends on how the bets were read.

    ``core`` (``identity.identity_of``: the sports and markets the hound is for) is never weak: a core segment that did clear the bar
    is held back, not cut. ``held`` is every losing segment that is NOT weak, worst units first, each with the ``reason`` it was
    left alone (``thin``: under ``MIN_SEGMENT_BETS`` bets; ``noise``: enough bets but inside what luck does; ``core``: it cleared the
    bar but the hound is for it). It is what the "keep going" message quotes."""
    rows = facts(bets, spec, rule_index)
    segments: dict = {}
    weak: list = []
    held: list = []
    for dim in DIMENSIONS:
        groups: dict = {}
        for r in rows:
            if r[dim] is not None:
                groups.setdefault(r[dim], []).append(r)
        entries = []
        for key in sorted(groups, key=lambda k: (str(type(k)), k)):
            label, phrase = _label(spec, dim, key)
            seg = {"dimension": dim, "key": key, "label": label, "phrase": phrase, **_tally(groups[key])}
            entries.append(seg)
        segments[dim] = entries
        if len(entries) < 2:
            continue
        for seg in entries:
            if seg["units"] >= 0:
                continue
            clears = _clears_the_bar(groups[seg["key"]], rows)
            if clears and not identity.blocks(core, dim, seg["key"]):
                weak.append(seg)
            else:
                held.append(dict(seg, reason="core" if clears else "thin" if seg["n"] < MIN_SEGMENT_BETS else "noise"))
    order = lambda s: (s["units"], -s["n"], DIMENSIONS.index(s["dimension"]), str(s["key"]))     # noqa: E731
    weak.sort(key=order)
    held.sort(key=order)
    return {"settled": len(rows), "overall": _tally(rows), "segments": segments, "weak": weak, "held": held,
            "core": dict(core) if core else None}


# ---------------------------------------------------------------------------
# the changes (each one narrows; none widens)
# ---------------------------------------------------------------------------

def _rule_likes(spec: dict) -> list:
    """The dicts that carry sports, markets, a price band and min_books: a classic dog's spec itself, or each rule of a
    custom-rules dog."""
    return spec["rules"] if user_spec.is_v2(spec) else [spec]


def _price_text(price: int) -> str:
    return user_spec._fmt_price(price)       # noqa: SLF001 -- the menu's own price formatter


def _sports_text(sports: Sequence[str]) -> str:
    return user_spec.sports_phrase(sports)


def _drop_from_list(spec: dict, field: str, value) -> Optional[tuple]:
    """Remove ``value`` from every rule's ``field`` list. A rule left empty is dropped when the dog has another rule;
    a dog that would be left with nothing is not changed (None). Returns ``(new spec, old text, new text)``."""
    new = copy.deepcopy(spec)
    before = _join_all(spec, field)
    touched = False
    if user_spec.is_v2(new):
        kept = []
        for rule in new["rules"]:
            if value in rule[field]:
                rest = [v for v in rule[field] if v != value]
                touched = True
                if rest:
                    rule[field] = rest
                    kept.append(rule)
                # a rule with nothing left is dropped
            else:
                kept.append(rule)
        if not kept or not touched:
            return None
        new["rules"] = kept
    else:
        if value not in new[field]:
            return None
        rest = [v for v in new[field] if v != value]
        if not rest:
            return None
        new[field] = rest
        touched = True
    return new, before, _join_all(new, field)


def _join_all(spec: Mapping, field: str) -> str:
    seen: list = []
    for rl in (spec["rules"] if user_spec.is_v2(spec) else [spec]):
        for v in rl[field]:
            if v not in seen:
                seen.append(v)
    if field == "sports":
        return _sports_text(seen)
    return ", ".join(user_rules.MARKET_LABELS.get(v, v).lower() for v in seen)


def change_drop_sport(spec: dict, sport: str) -> Optional[dict]:
    out = _drop_from_list(spec, "sports", sport)
    return None if out is None else {"spec": out[0], "id": "drop_sport", "field": "sports", "label": "Sports",
                                     "old_text": out[1], "new_text": out[2]}


def change_drop_market(spec: dict, market: str) -> Optional[dict]:
    out = _drop_from_list(spec, "markets", market)
    return None if out is None else {"spec": out[0], "id": "drop_market", "field": "markets", "label": "Markets",
                                     "old_text": out[1], "new_text": out[2]}


def change_focus_sports(spec: dict, keep: Sequence[str]) -> Optional[dict]:
    """Narrow every rule to the sports in ``keep`` (the hound's core). A custom rule left with none of them is dropped, and a
    hound that would be left with no rule at all is not changed (None). Only ever narrows; the same gate as every change."""
    keep = list(keep)
    new = copy.deepcopy(spec)
    before = _join_all(spec, "sports")
    if user_spec.is_v2(new):
        kept = []
        for rule in new["rules"]:
            rest = [s for s in rule["sports"] if s in keep]
            if rest:
                rule["sports"] = rest
                kept.append(rule)
        if not kept:
            return None
        new["rules"] = kept
    else:
        rest = [s for s in new["sports"] if s in keep]
        if not rest:
            return None
        new["sports"] = rest
    after = _join_all(new, "sports")
    if after == before:
        return None
    return {"spec": new, "id": "focus_sports", "field": "sports", "label": "Sports", "old_text": before, "new_text": after}


def change_tighten_band(spec: dict, band_key: str) -> Optional[dict]:
    """Cut the worst price band off the end of every price range it sits on the edge of. A band in the middle of a range
    cannot be cut out (a range has no hole), and a range that lies wholly inside the band is left alone."""
    index = _BAND_BY_KEY[band_key]
    _k, _name, _range, blo, bhi = PRICE_BANDS[index]
    dlo, dhi = user_spec.price_decimal(blo), user_spec.price_decimal(bhi)
    new = copy.deepcopy(spec)
    moves = []
    for rl in _rule_likes(new):
        pmin, pmax = rl["price_min"], rl["price_max"]
        low_in = dlo - 1e-9 <= user_spec.price_decimal(pmin) <= dhi + 1e-9
        high_in = dlo - 1e-9 <= user_spec.price_decimal(pmax) <= dhi + 1e-9
        if low_in and not high_in and index + 1 < len(PRICE_BANDS):
            rl["price_min"] = PRICE_BANDS[index + 1][3]
            moves.append((pmin, pmax, rl["price_min"], pmax))
        elif high_in and not low_in and index > 0:
            rl["price_max"] = PRICE_BANDS[index - 1][4]
            moves.append((pmin, pmax, pmin, rl["price_max"]))
    if not moves:
        return None
    a, b, c, d = moves[0]
    old_text, new_text = f"{_price_text(a)} to {_price_text(b)}", f"{_price_text(c)} to {_price_text(d)}"
    if len(moves) > 1:
        old_text, new_text = old_text + " (first rule)", new_text + " (first rule)"
    return {"spec": new, "id": "tighten_band", "field": "price_band", "label": "Price range",
            "old_text": old_text, "new_text": new_text}


def change_drop_venue(spec: dict, venue: str) -> Optional[dict]:
    """A custom-rules rule that takes either side learns to take only the other one. (A classic dog's side is its rule,
    which training never rewrites.)"""
    if not user_spec.is_v2(spec):
        return None
    keep = _OPPOSITE_VENUE[venue]
    new = copy.deepcopy(spec)
    changed = 0
    for rule in new["rules"]:
        kinds = {user_rules.market_kind(m) for m in rule["markets"]}
        if rule.get("side") == "either" and keep in user_rules.sides_for(sorted(kinds)):
            rule["side"] = keep
            changed += 1
    if not changed:
        return None
    return {"spec": new, "id": "drop_venue", "field": "side", "label": "Side",
            "old_text": "either side", "new_text": f"{VENUE_LABELS[keep]} only"}


def change_require_role(spec: dict, role: str) -> Optional[dict]:
    """Add "the pick is the <role>" to the rules that can carry it and do not already say favourite or underdog."""
    if not user_spec.is_v2(spec):
        return None
    keep = _OPPOSITE_ROLE[role]
    new = copy.deepcopy(spec)
    changed = 0
    for rule in new["rules"]:
        if {user_rules.market_kind(m) for m in rule["markets"]} != {"ml_spread"}:
            continue
        if any(c.get("id") == "role" for c in _conds(rule.get("when"))):
            continue
        cond = {"id": "role", "value": keep}
        rule["when"] = {"op": "all", "items": [cond]} if not rule.get("when") else {"op": "all", "items": [rule["when"], cond]}
        changed += 1
    if not changed:
        return None
    return {"spec": new, "id": "require_role", "field": "pick", "label": "Which side of the price",
            "old_text": "favourite or underdog", "new_text": f"the {ROLE_LABELS[keep]} only"}


def _conds(tree) -> list:
    out = []
    if isinstance(tree, Mapping):
        if "id" in tree:
            out.append(tree)
        for item in tree.get("items") or []:
            out.extend(_conds(item))
    return out


def change_more_books(spec: dict, rule: Optional[int] = None) -> Optional[dict]:
    """One more book must be quoting a price (one grid step), on one rule or on all of them."""
    new = copy.deepcopy(spec)
    targets = _rule_likes(new) if rule is None else [new["rules"][rule]] if user_spec.is_v2(new) and rule < len(new["rules"]) else []
    changed = []
    for rl in targets:
        stepped = _step(BOOKS_KNOB, rl["min_books"], +1)
        if stepped != rl["min_books"]:
            changed.append((rl["min_books"], stepped))
            rl["min_books"] = stepped
    if not changed:
        return None
    return {"spec": new, "id": "more_books", "field": "min_books", "label": "Books quoting at least",
            "old_text": f"{changed[0][0]} books", "new_text": f"{changed[0][1]} books"}


def change_fewer_bets(spec: dict) -> Optional[dict]:
    """One bet fewer a day (one grid step)."""
    stepped = _step(BETS_KNOB, spec["max_bets_per_day"], -1)
    if stepped == spec["max_bets_per_day"]:
        return None
    new = copy.deepcopy(spec)
    new["max_bets_per_day"] = stepped
    return {"spec": new, "id": "fewer_bets", "field": "max_bets_per_day", "label": "Most bets a day",
            "old_text": str(spec["max_bets_per_day"]), "new_text": str(stepped)}


def _step(knob, value, direction: int):
    """One grid step from ``value`` (``breeding.cross``'s helpers), held inside the knob's bounds."""
    top = cross.grid_index(knob, knob.hi)
    return cross.on_grid_value(knob, max(0, min(top, cross.grid_index(knob, value) + direction)))


def _candidate_for(spec: dict, seg: Mapping) -> Optional[dict]:
    dim, key = seg["dimension"], seg["key"]
    if dim == "sport":
        return change_drop_sport(spec, key)
    if dim == "market":
        return change_drop_market(spec, key)
    if dim == "band":
        return change_tighten_band(spec, key)
    if dim == "venue":
        return change_drop_venue(spec, key)
    if dim == "role":
        return change_require_role(spec, key)
    if dim == "rule":
        return change_more_books(spec, key)
    return None


def _hash(spec: Mapping) -> str:
    return user_spec.spec_hash(spec)


def _validated(raw: Mapping) -> Optional[dict]:
    """The spec through the menu's own gate, or None when the menu refuses it (a change that does not validate is
    dropped, never repaired)."""
    try:
        return user_spec.validate_spec(raw, taken_names=())
    except user_spec.SpecError:
        return None


def _why(seg: Mapping, change_id: str) -> str:
    record = f"{seg['wins']}-{seg['losses']}" + (f"-{seg['pushes']}" if seg["pushes"] else "")
    spot = f"{seg['n']} {seg['phrase']} went {record} ({seg['units']:+.2f}u at the average price)"
    if change_id == "more_books":
        return f"{spot}, its weakest part, so this rule now waits for one more book to quote the price."
    if change_id == "require_role":
        return f"{spot}, its weakest part, so the new version only takes the other kind of pick."
    return f"{spot}, its weakest part, so the new version no longer takes them."


def cid_of(change_id: str, seg: Optional[Mapping]) -> str:
    """The stable id of a candidate change on the menu: ``drop_sport:MLB``, ``tighten_band:underdogs``, ``more_books:rule1``."""
    if seg is None:
        return change_id
    if seg["dimension"] == "rule":
        return f"{change_id}:rule{seg['key']}"
    return f"{change_id}:{seg['key']}"


def _segment_view(seg: Mapping) -> dict:
    return {k: seg[k] for k in ("dimension", "key", "label", "phrase", "n", "wins", "losses", "pushes", "units")}


def _entry_for_segment(spec: Mapping, seg: Mapping) -> Optional[dict]:
    """A menu entry for one weak segment, or None when its change does not stand on its own against ``spec``."""
    cand = _candidate_for(copy.deepcopy(dict(spec)), seg)
    if cand is None:
        return None
    valid = _validated(cand["spec"])
    if valid is None or _hash(valid) == _hash(spec):
        return None
    return {"cid": cid_of(cand["id"], seg), "id": cand["id"], "addresses": [f"{seg['dimension']}:{seg['key']}"],
            "text": f"{cand['label']}: {cand['old_text']} to {cand['new_text']}", "segment": seg, "why": None,
            "build": lambda s, _seg=seg: _candidate_for(s, _seg)}


def menu(spec: Mapping, analysis: Mapping, diagnosis: Optional[Mapping] = None) -> list:
    """Every narrowing change the coach could make to ``spec`` right now, each valid on its own: the deterministic order
    (``analysis['weak']``, worst first), then, when a diagnosis is given, a change aimed at the two other cuts the menu can
    narrow (books quoting, the daily limit). This is the WHOLE set a model may choose from: it can reorder and pick, it cannot
    add a change that is not here, and every pick is run through ``user_spec.validate_spec`` again when it is applied."""
    out: list = []
    seen: set = set()
    core = analysis.get("core")
    for seg in analysis.get("weak", ()):
        if identity.blocks(core, seg["dimension"], seg["key"]):         # belt and braces: ``analyse`` already holds a core segment back
            continue
        entry = _entry_for_segment(spec, seg)
        if entry and entry["cid"] not in seen:
            seen.add(entry["cid"])
            out.append(entry)
    for f in (diagnosis or {}).get("rows", ()):
        if f.get("kind") != "segment" or f.get("direction") != "against" or f.get("n", 0) < MIN_SEGMENT_BETS:
            continue
        if _LEVEL_RANK.get(f.get("level"), 0) < _LEVEL_RANK[MIN_SEGMENT_LEVEL]:        # the same evidence bar as a weak spot
            continue
        rec = f"{f['wins']}-{f['losses']}" + (f"-{f['pushes']}" if f["pushes"] else "")
        if f["id"] in ("books:few", "books:mid") and "more_books:all" not in seen:
            cand = change_more_books(copy.deepcopy(dict(spec)))
            valid = _validated(cand["spec"]) if cand else None
            if valid is not None and _hash(valid) != _hash(spec):
                seen.add("more_books:all")
                out.append({"cid": "more_books:all", "id": "more_books", "addresses": [f["id"]],
                            "text": f"{cand['label']}: {cand['old_text']} to {cand['new_text']}", "segment": None,
                            "why": (f"{f['label']} went {rec} over {f['n']} ({f['units']:+.2f}u at the average price), "
                                    "so every rule now waits for one more book to quote the price."),
                            "build": lambda s: change_more_books(s)})
        if f["id"] == "cap:at_limit" and "fewer_bets" not in seen:
            cand = change_fewer_bets(copy.deepcopy(dict(spec)))
            valid = _validated(cand["spec"]) if cand else None
            if valid is not None and _hash(valid) != _hash(spec):
                seen.add("fewer_bets")
                out.append({"cid": "fewer_bets", "id": "fewer_bets", "addresses": [f["id"]],
                            "text": f"{cand['label']}: {cand['old_text']} to {cand['new_text']}", "segment": None,
                            "why": (f"On the days it hit its daily limit its {f['n']} bets went {rec} ({f['units']:+.2f}u at "
                                    "the average price), so the new version takes one bet fewer a day."),
                            "build": lambda s: change_fewer_bets(s)})
    return out


def _apply_entry(current: dict, entry: Mapping, pick: str) -> Optional[tuple]:
    """``(new spec, change)`` for a menu entry applied to ``current``, or None when it no longer validates or changes nothing."""
    cand = entry["build"](copy.deepcopy(current))
    if cand is None:
        return None
    valid = _validated(cand["spec"])
    if valid is None or _hash(valid) == _hash(current):
        return None
    seg = entry.get("segment")
    change = {k: v for k, v in cand.items() if k != "spec"}
    change.update(why=entry.get("why") or _why(seg, cand["id"]), segment=_segment_view(seg) if seg else None,
                  hindsight={k: seg[k] for k in ("n", "wins", "losses", "pushes", "units")}
                  if seg and cand["id"] in ("drop_sport", "drop_market", "tighten_band", "drop_venue") else None,
                  cid=entry["cid"], factors=list(entry["addresses"]), pick=pick, direction=entry.get("direction", "narrow"))
    return valid, change


def propose(spec: Mapping, analysis: Mapping, *, seed_key: str, hound_id: str, light: bool,
            preferred: Sequence[str] = (), entries: Sequence[Mapping] = ()) -> tuple:
    """``(new spec, [change], mode, note)`` or ``(None, [], mode, note)`` when no valid change exists.

    ``mode`` is ``analysed`` (changes aimed at weak spots), ``light`` (a small careful nudge: the dog has fewer than
    ``MIN_NEW_SETTLED`` settled bets) or ``keep`` (a dog with enough bets in which nothing cleared the evidence bar: no change).
    Deterministic: no clock, no unseeded draw."""
    current = copy.deepcopy(dict(spec))
    changes: list = []
    if not light:
        # A model's picks (``preferred``, menu ids in its order) go first, and only ones that are ON the menu: an id that is not
        # there is ignored, and each pick is re-validated against the spec as it stands. With no valid pick the deterministic
        # order below runs exactly as it always has.
        if preferred and entries:
            by_cid = {e["cid"]: e for e in entries}
            for cid in preferred:
                if len(changes) >= MAX_CHANGES:
                    break
                entry = by_cid.get(cid)
                if entry is None or any(c["cid"] == cid for c in changes):
                    continue
                applied = _apply_entry(current, entry, "coach")
                if applied is None:
                    continue
                current, change = applied
                changes.append(change)
            if changes:
                return current, changes, "analysed", ""
        for seg in analysis.get("weak", []):
            if len(changes) >= MAX_CHANGES:
                break
            if identity.blocks(analysis.get("core"), seg["dimension"], seg["key"]):
                continue
            cand = _candidate_for(current, seg)
            if cand is None:
                continue
            valid = _validated(cand["spec"])
            if valid is None or _hash(valid) == _hash(current):
                continue
            current = valid
            change = {k: v for k, v in cand.items() if k != "spec"}
            change.update(why=_why(seg, cand["id"]), segment=_segment_view(seg),
                          hindsight={k: seg[k] for k in ("n", "wins", "losses", "pushes", "units")}
                          if cand["id"] in ("drop_sport", "drop_market", "tighten_band", "drop_venue") else None,
                          cid=cid_of(cand["id"], seg), factors=[f"{seg['dimension']}:{seg['key']}"], pick="rules", direction="narrow")
            changes.append(change)
        if changes:
            return current, changes, "analysed", ""
        # Nothing cleared the evidence bar, or nothing the menu allows addresses what did: the honest proposal is no change.
        # (A first training under MIN_NEW_SETTLED bets is the labelled light adjustment below.)
        return None, [], "keep", "no_change_fits" if analysis.get("weak") else "no_weak_spot"
    # a light adjustment: one careful nudge, the knob chosen by the seeded stream (so two dogs do not all nudge the same one)
    rng = cross.rng_for(seed_key, hound_id)
    options = [lambda s: change_more_books(s), lambda s: change_fewer_bets(s)]
    order = list(range(len(options)))
    rng.shuffle(order)
    for i in order:
        cand = options[i](current)
        if cand is None:
            continue
        valid = _validated(cand["spec"])
        if valid is None or _hash(valid) == _hash(current):
            continue
        change = {k: v for k, v in cand.items() if k != "spec"}
        why = ("A small careful adjustment: one more book must quote the price before it bets." if cand["id"] == "more_books"
               else "A small careful adjustment: one bet fewer a day.")
        change.update(why=why, segment=None, hindsight=None, factors=[], pick="rules", direction="narrow",
                      cid="more_books:all" if cand["id"] == "more_books" else cand["id"])
        note = "not_enough_bets" if light else "no_weak_spot"
        return valid, [change], "light", note
    return None, [], "light", "nothing_to_change"


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def _record_text(rec: Mapping) -> str:
    return f"{rec['wins']}-{rec['losses']}" + (f"-{rec['pushes']}" if rec.get("pushes") else "")


def guidance_text(name: str, analysis: Mapping, changes: Sequence, mode: str, note: str, from_version: int) -> str:
    """The paragraph the card shows: what the coach read and what it did, in plain words, never a promise. Written by
    code from the analysis; the optional AI second look (``send_brief``) does not replace it."""
    overall = analysis["overall"]
    if mode == "light":
        if note == "not_enough_bets":
            intro = (f"{name} has {overall['n']} settled {'bet' if overall['n'] == 1 else 'bets'} on this version, "
                     f"under the {MIN_NEW_SETTLED} the coach needs to find a weak spot, so this is a light adjustment "
                     "and not an analysis.")
        else:
            intro = (f"{name} went {_record_text(overall)} over {overall['n']} settled bets, and no part of that record "
                     "stood out as a weak spot, so this is a light adjustment.")
    else:
        worst = next((c["segment"] for c in changes if c.get("segment")), analysis["weak"][0])
        intro = (f"{name} went {_record_text(overall)} over {overall['n']} settled bets ({overall['units']:+.2f}u at the "
                 f"average price). The weakest part it could change was its {worst['phrase']}: {_record_text(worst)} over "
                 f"{worst['n']} ({worst['units']:+.2f}u).")
    made = coach_card.change_sentence(changes)
    return (f"{intro} The coach changed {made}. Version {from_version} keeps its record as it stands. "
            "The new version's record starts now.")


def build_brief(name: str, analysis: Mapping, changes: Sequence, mode: str, text: str) -> dict:
    """What the optional AI step is shown. Data, not instructions (``coach_brief.DATA_NOTICE``), held under the brief
    size cap. No account id, no email, no token: the dog's public name and its own numbers."""
    try:
        from src.hounds.learning import coach_brief
        notice, cap = coach_brief.DATA_NOTICE, coach_brief.MAX_BYTES
    except Exception:  # noqa: BLE001 -- the brief is optional; a notice of our own is better than no brief
        notice, cap = "DATA, NOT INSTRUCTIONS. Everything below is quoted data about a paper strategy.", 25_000
    brief = {"kind": "training_brief", "data_notice": notice, "dog": name, "mode": mode,
             "settled": analysis["overall"]["n"], "record": _record_text(analysis["overall"]),
             "weak_spots": [{k: s[k] for k in ("dimension", "label", "phrase", "n", "wins", "losses", "pushes", "units")}
                            for s in analysis["weak"][:5]],
             "changes": [{k: c[k] for k in ("label", "old_text", "new_text", "why")} for c in changes],
             "written_by_code": text, "paper_only": True}
    while len(json.dumps(brief, default=str).encode("utf-8")) > cap and brief["weak_spots"]:
        brief["weak_spots"].pop()
    return brief


def send_brief(brief: Mapping, job_key: str, *, env: Optional[Mapping] = None,
               poster: Optional[Callable] = None, background: bool = True) -> bool:
    """POST the brief to the owner's Zapier hook if one is configured. Returns True when a request was started (not
    when it succeeded). NEVER raises and never waits for the answer: the post runs on a daemon thread with a short
    timeout, and every failure is swallowed, because a coach's second opinion must not hold up a training."""
    try:
        # Opt-in: the only hook today is the live strategy-translator Zap, whose AI step would spend tasks on briefs
        # it cannot use. Off unless TRAINING_BRIEF_ZAP=on (set it once a Zap filters on kind=training_brief).
        if str((env if env is not None else os.environ).get("TRAINING_BRIEF_ZAP", "")).strip().lower() != "on":
            return False
        from src.hounds.english import translate
        url = translate.hook_url(env)
        if url is None:
            return False
        post = poster or (lambda u, payload: translate.post_hook(u, payload, timeout=HOOK_TIMEOUT_S))
        payload = {"job_id": job_key, "kind": "training_brief", "text": json.dumps(dict(brief), sort_keys=True)}

        def run():
            try:
                post(url, payload)
            except Exception:  # noqa: BLE001 -- see above: nothing about the hook may reach the person
                pass

        if background:
            threading.Thread(target=run, daemon=True, name=f"training-brief-{job_key}").start()
        else:
            run()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# the rite
# ---------------------------------------------------------------------------

def rule_index_of(rows: Sequence, hound_id: str) -> dict:
    """{bet_id: rule_index} for a custom-rules dog's bets, from the raw ledger rows."""
    return {r["bet_id"]: r["rule_index"] for r in rows
            if r.get("hound_id") == hound_id and r.get("bet_id") and isinstance(r.get("rule_index"), int)}


def eligibility(dog: common.Dog, hound: Mapping, bets: Sequence) -> dict:
    """Whether this dog may train now, from its bets alone: ``{allowed, light, settled, trained_times, needs}``."""
    settled = rites.settled_count(bets)
    trained = user_store.trained_count(hound["root_id"])
    if trained and settled < MIN_NEW_SETTLED:
        return {"allowed": False, "light": False, "settled": settled, "trained_times": trained, "needs": MIN_NEW_SETTLED - settled,
                "message": (f"{dog.name} needs {MIN_NEW_SETTLED} new settled bets on version {hound['version_no']} before "
                            f"it can train again. It has {settled}.")}
    return {"allowed": True, "light": settled < MIN_NEW_SETTLED, "settled": settled, "trained_times": trained, "needs": 0,
            "message": ""}


def _ready(dog, user_id: int, *, confirmed_required: bool, confirmed: bool, now, rows, ledger_path, db) -> tuple:
    """The checks every step of a training shares: the owner's live member hound, nothing unsettled, and a version that may train.
    Returns ``(dog, moment, rows, bets, hound, gate)`` or raises ``RiteError``."""
    dog = rites.guard(dog, user_id)
    if confirmed_required and not confirmed:
        raise RiteError("confirm_required", f"Say it again to send {dog.name} to training: send confirm true.", 400)
    moment = now or common.now_utc()
    rows = rites.read_rows(ledger_path) if rows is None else rows
    bets = rites.forward_bets(dog.id, rows)
    rites.require_all_settled(dog, bets, moment)
    hound = user_store.get_hound(dog.id, db=db)
    if hound is None:
        raise RiteError("not_found", "no such dog", 404)
    gate = eligibility(dog, hound, bets)
    if not gate["allowed"]:
        raise RiteError("training_too_soon", gate["message"], 409, settled=gate["settled"], needs=gate["needs"])
    return dog, moment, rows, bets, hound, gate


def _coach_input(dog, hound, bets, rows, analysis, spec) -> dict:
    return {"hound_id": dog.id, "bets": bets, "spec": spec, "rows": rows, "rule_index": rule_index_of(rows, dog.id),
            "analysis": analysis}


def coach_view(read: Mapping, applied: Sequence[str] = ()) -> dict:
    """What a page receives of the coach's read: who read it, the ranked reasons with the table lines they cite, and which of the
    read's picks became changes. No cost, no router reason, no model refusal text: those stay in the log and the event."""
    ai = read["source"] == "ai"
    # why the rules engine read it, in a word the page can say: resting (capped, down or no key), too_few (too few settled bets for a
    # model to read) or dropped (the model answered but none of its reasons held up against the table)
    why = None if ai else {"skipped": "too_few", "dropped_all": "dropped"}.get(read.get("status"), "resting")
    return {"source": read["source"], "label": read["label"], "resting": not ai, "why": why, "model_label": "Claude Haiku" if ai else None,
            "summary": read.get("summary"), "picks_applied": list(applied),
            "reasons": [{"rank": i + 1, "factors": r["factors"], "text": r["text"], "confidence": r["confidence"],
                         "thin": bool(r.get("thin")), "cited": r["cited"]} for i, r in enumerate(read["reasons"])]}


def read_step(dog: Optional[common.Dog], user_id: int, coach, *, stage: str, now: Optional[datetime] = None,
              rows: Optional[Sequence] = None, ledger_path: Optional[str] = None, db=None) -> dict:
    """The first two steps of Send to training, which write nothing: ``stage`` ``diagnose`` (the table) or ``assess`` (the table and
    the read of it). The same checks as the training itself, minus the confirm. Raises ``RiteError`` like ``train`` does."""
    from src.hounds.interact import coach as coach_mod
    dog, _moment, rows, bets, hound, gate = _ready(dog, user_id, confirmed_required=False, confirmed=False, now=now, rows=rows,
                                                    ledger_path=ledger_path, db=db)
    spec = hound["spec"]
    analysis = analyse(bets, spec, rule_index_of(rows, dog.id), core=identity.identity_of(hound))
    inp = _coach_input(dog, hound, bets, rows, analysis, spec)
    table = coach.diagnosis(inp)
    out = {"stage": stage, "light": gate["light"], "version_no": hound["version_no"], "diagnosis": coach_mod.public_view(table),
           "paper_only": True}
    if stage == "assess":
        out["coach"] = coach_view(coach.read(inp, menu(spec, analysis, table), table))
    return out


# ---------------------------------------------------------------------------
# proposal -> review -> apply (owner ruling 2026-10-22: "players should have a choice to veto the upgrade or tell it to tweak
# the changes and why")
# ---------------------------------------------------------------------------
#
# EVERY training now goes in steps, and only the last one writes anything:
#   ``review``  builds the proposal card (each change old -> new with its one-line reason, what today's board would have said,
#               and the coach's read when there is one). It reads the ledger and the board and writes NOTHING.
#   ``review`` again, with a ``tweak`` (up to ``retune.TWEAK_ROUNDS`` times): the owner says why or what instead, the words are
#               mapped to the same closed menu (``retune.full_menu``) by Claude Haiku or the rules engine, within the same caps,
#               and a revised card comes back. Still nothing written.
#   ``veto``    says no. Nothing is written, no version is made and the training limit does not move.
#   ``train``   with the owner's confirm and the cids they left ticked (``picks``) is Apply: the one place a version is created.
# The picks are cids on the menu and nothing else: ``train`` rebuilds each change from the menu against the spec as it stands,
# runs it through ``user_spec.validate_spec``, and refuses a cid that is not on the menu.

TWEAK_REGISTRY_MAX = 512
_tweaks: dict = {}
_tweaks_lock = threading.Lock()
NOT_BETTING_SETTLED = 0          # a hound with this many settled bets or fewer has nothing to be coached on: it is not betting
LOOSEN_DEFAULT_MAX = 2           # the default proposal for a hound that is not betting widens at most this many things


def _tweak_key(hound_id: str, spec: Mapping) -> tuple:
    return (hound_id, user_spec.spec_hash(spec))


def tweaks_used(hound_id: str, spec: Mapping) -> int:
    with _tweaks_lock:
        return _tweaks.get(_tweak_key(hound_id, spec), 0)


def _tweak_bump(hound_id: str, spec: Mapping, at_least: int = 0) -> int:
    """Count one more tweak round for this hound on this rule and return the new count. Held in this process (like the coach's
    cache); the page also reports the round it is on and the larger of the two counts is used, so a restart cannot hand out more."""
    key = _tweak_key(hound_id, spec)
    with _tweaks_lock:
        used = max(_tweaks.get(key, 0), at_least) + 1
        _tweaks[key] = used
        while len(_tweaks) > TWEAK_REGISTRY_MAX:
            _tweaks.pop(next(iter(_tweaks)))
        return used


def _tweaks_clear(hound_id: str) -> None:
    with _tweaks_lock:
        for key in [k for k in _tweaks if k[0] == hound_id]:
            del _tweaks[key]


def _propose_loosening(spec: Mapping, board_fn: Optional[Callable], *, pin_sports: bool = False) -> tuple:
    """``(new spec or None, [change], "loosen", note)``: the default for a hound that is not betting. It never narrows. With
    today's board it offers only changes that would add a candidate there (most added first, one per kind of change); without a
    board it offers the first of each kind in the menu's own order. A change to the daily limit is never offered: a hound that
    places nothing is not stopped by its limit. ``pin_sports`` (the owner said "keep the sports as they are") leaves out the
    sports family too."""
    from src.hounds.interact import retune
    pool = [e for e in retune.loosening_menu(spec) if e["family"] != retune.BETS_FAMILY
            and not (pin_sports and e["family"] == retune.SPORT_FAMILY)]
    counted = retune.whatif(spec, pool, board_fn)
    if counted["base"] is not None:
        scored = []
        for e in pool:
            c = counted["by_cid"].get(e["cid"])
            if c is not None and c["after"] > c["before"]:
                scored.append((c["after"] - c["before"], e))
        scored.sort(key=lambda t: (-t[0], retune.FAMILY_ORDER.index(t[1]["family"])))
        ordered, note = [e for _g, e in scored], "not_betting"
    else:
        ordered, note = pool, "not_betting_no_board"
    current, changes, used = copy.deepcopy(dict(spec)), [], set()
    for e in ordered:
        if len(changes) >= LOOSEN_DEFAULT_MAX:
            break
        if e["family"] in used:
            continue
        applied = _apply_entry(current, e, "rules")
        if applied is None:
            continue
        used.add(e["family"])
        current, change = applied
        changes.append(change)
    if not changes:
        return None, [], "loosen", "nothing_sensible"
    return current, changes, "loosen", note


def _pin_sports(analysis: Mapping) -> dict:
    """The analysis as the coach reads it when the owner has said to keep the sports as they are: no weak spot is a sport."""
    return dict(analysis, weak=[s for s in analysis["weak"] if s["dimension"] != "sport"])


def _default_plan(dog, hound, bets, rows, analysis, gate, coach, board_fn, *, pin_sports: bool = False) -> dict:
    """The proposal Send to training makes by itself: the coach's read and the narrowing menu as always, EXCEPT for a hound that
    is not betting (no settled bet on this version), which is offered loosening instead, never narrowing. ``analysis`` already
    holds the hound's core back (``analyse(core=...)``), so the default plan never cuts what the hound is for; ``pin_sports`` is the
    owner's own "keep the sports as they are" and takes every sport out of it."""
    from src.hounds.interact import coach as coach_mod, retune
    spec = hound["spec"]
    if pin_sports:
        analysis = _pin_sports(analysis)
    the_coach = coach or coach_mod.Coach(rules_only=True)
    inp = _coach_input(dog, hound, bets, rows, analysis, spec)
    table = the_coach.diagnosis(inp)
    entries = menu(spec, analysis, table)
    read = the_coach.read(inp, entries, table)
    # The same today's-board read the owner's card shows ("On today's board: N candidates"). A spec with zero candidates today
    # is not held back by a narrow rule the board never reached, so narrowing it would only make things worse: it gets the
    # loosening menu instead, which offers nothing when no loosening adds a candidate. An unreadable board (None) changes nothing.
    today = retune.whatif(spec, [], board_fn)["base"]
    idle_today = today is not None and today["candidates"] == 0
    if analysis["settled"] <= NOT_BETTING_SETTLED or idle_today:
        new_spec, changes, mode, note = _propose_loosening(spec, board_fn, pin_sports=pin_sports)
    else:
        new_spec, changes, mode, note = propose(spec, analysis, seed_key=f"train-v{hound['version_no']}", hound_id=dog.id,
                                                light=gate["light"], preferred=read["picks"] if read["source"] == "ai" else (),
                                                entries=entries)
    return {"spec": new_spec, "changes": changes, "mode": mode, "note": note, "read": read, "table": table}


def _menu_for(spec, analysis, table, origin, *, core=None, lines=(), enforce=True) -> list:
    """The closed set a pick or a tweak may use. The diagnosis table feeds it only for the training path (the chat path has none).
    ``core`` is the hound's identity: with ``enforce`` (the proposal) the set leaves out any change that removes a core sport or
    market unless one of the owner's ``lines`` asks for that one; Apply passes ``enforce=False`` because the owner has read the card."""
    from src.hounds.interact import retune
    return retune.full_menu(spec, analysis, table if origin is None else None, core=core, lines=lines, enforce=enforce)


def _apply_items(spec: Mapping, items: Sequence[Mapping], entries: Sequence[Mapping]) -> tuple:
    """``(new spec, [change])`` for mapped items (cid, line, quote, text) applied in order, each re-validated; a change that no
    longer applies is skipped. A change made for an item that cites a chat line carries that line."""
    by_cid = {e["cid"]: e for e in entries}
    current, changes = copy.deepcopy(dict(spec)), []
    for item in items:
        if len(changes) >= MAX_CHANGES:
            break
        entry = by_cid.get(item["cid"])
        if entry is None:
            continue
        applied = _apply_entry(current, entry, "owner")
        if applied is None:
            continue
        current, change = applied
        if item.get("line") is not None:
            change["cite"] = {"line": item["line"], "text": item["text"], "quote": item.get("quote") or ""}
        changes.append(change)
    return current, changes


def _picked_plan(spec: Mapping, picks: Sequence[str], entries: Sequence[Mapping]) -> tuple:
    """The changes for the cids the owner left ticked. A cid that is not on the menu refuses the whole request (422), more than
    ``MAX_CHANGES`` refuses it (422), and none left refuses it (400): a stray POST can never smuggle in a change."""
    ids = [c for c in dict.fromkeys(picks) if isinstance(c, str)]
    if not ids:
        raise RiteError("no_changes_selected", "Pick at least one change to apply, or say no to the proposal.", 400)
    if len(ids) > MAX_CHANGES:
        raise RiteError("too_many_changes", f"A training makes at most {MAX_CHANGES} changes.", 422)
    on_menu = {e["cid"] for e in entries}
    unknown = [c for c in ids if c not in on_menu]
    if unknown:
        raise RiteError("unknown_change", "That change is not one the hound is allowed to make.", 422, unknown=unknown[:3])
    return _apply_items(spec, [{"cid": c, "line": None, "text": "", "quote": ""} for c in ids], entries)


def _mode_of(changes: Sequence[Mapping], gate: Mapping, origin: Optional[str], settled: int) -> tuple:
    """``(mode, note)`` for changes the owner chose: a retune from chat; an analysis when a change is aimed at a weak spot;
    loosening for changes that only widen; otherwise the light adjustment or a plain owner-chosen training."""
    if origin:
        return "retune", ""
    if any(c.get("segment") for c in changes):
        return "analysed", ""
    if changes and all(c.get("direction") == "loosen" for c in changes):
        return "loosen", "not_betting"
    if gate["light"]:
        return "light", "not_enough_bets" if settled < MIN_NEW_SETTLED else "no_weak_spot"
    return "owner", ""


def guidance_owner(name: str, analysis: Mapping, changes: Sequence, mode: str, from_version: int) -> str:
    """The paragraph for a training the owner shaped (a retune, a hound that was not betting, a tweak): what was changed, in plain
    words, never a promise."""
    n = analysis["overall"]["n"]
    if mode == "retune":
        intro = f"{name} changed itself because its owner asked in the chat."
    elif mode == "loosen":
        intro = (f"{name} had {'not placed a settled bet' if n == 0 else 'few settled bets'} on this version, so there was no "
                 "record to coach on. The changes widen what it looks at, so it considers more games.")
    else:
        intro = f"{name} has {n} settled {'bet' if n == 1 else 'bets'} on this version. The changes below were chosen with its owner."
    made = coach_card.change_sentence(changes)
    return (f"{intro} The changes: {made}. This changes how many and which games it looks at; it makes no promise about results. "
            f"Version {from_version} keeps its record as it stands. The new version's record starts now.")


def _today_block(spec: Mapping, new_spec: Optional[Mapping], changes: list, entries: Sequence[Mapping],
                 board_fn: Optional[Callable]) -> Optional[dict]:
    """What the proposal would have meant on today's board, and the same for each change on its own. Counts of candidates, from
    boards only (``retune.board_counts``). None when there is no board function or the board cannot be read. Each change gets
    its own ``today`` ({before, after}) when it could be counted."""
    from src.hounds.interact import retune
    if board_fn is None:
        return None
    base = board_fn(spec)
    if base is None:
        return None
    by_cid = {e["cid"]: e for e in entries}
    for change in changes:
        entry = by_cid.get(change["cid"])
        applied = _apply_entry(copy.deepcopy(dict(spec)), entry, "owner") if entry else None
        counts = board_fn(applied[0]) if applied else None
        change["today"] = None if counts is None else {"before": base["candidates"], "after": counts["candidates"]}
    after = base if new_spec is None else board_fn(new_spec)
    if after is None:
        return None
    return {"games": base["games"], "before": base["candidates"], "after": after["candidates"],
            "text": retune.today_text(base["candidates"], after["candidates"]), "note": retune.TODAY_NOTE}


def _clean_origin(origin) -> Optional[str]:
    from src.hounds.interact import retune
    if origin in (None, "", "training"):
        return None
    if origin in ("chat", retune.ORIGIN_CHAT):
        return retune.ORIGIN_CHAT
    raise RiteError("bad_origin", "That is not a kind of training this hound knows.", 422)


STALE_PROPOSAL = "proposal_stale"
REVIEW_REQUIRED = "review_required"


def proposal_basis(hound_id: str, spec: Mapping) -> str:
    """What a proposal was made against: the hound version's id and its rule's hash. The review card carries it and Apply sends it
    back, so a card that was drawn for a rule that has since changed (an edit in another tab, a second Apply, a training that
    finished elsewhere) is refused in words instead of applying cids to a rule the owner never saw them against. A version's spec
    never changes in place (``user_store.create_version`` makes a new id), so the id alone would do today; the hash keeps the check
    true if that ever stops being so."""
    return f"{hound_id}:{user_spec.spec_hash(spec)[:16]}"


def _stale(name: str, *, applied_elsewhere: bool = False) -> RiteError:
    how = ("was changed by another request a moment ago (a second tab, or Apply tapped twice)" if applied_elsewhere
           else "has changed since the proposal was made")
    return RiteError(STALE_PROPOSAL, f"This proposal is out of date: {name} {how}. Nothing more was changed. Open its newest "
                                     "version and look at a fresh proposal.", 409)


def _clip(text, limit: int) -> str:
    """One line of the owner's words, control characters gone, spacing collapsed, at most ``limit`` characters. The raw text is
    cut BEFORE any pattern runs over it, so a megabyte pasted into the box costs what a few hundred characters cost."""
    raw = str(text if text is not None else "")[: limit * 4]
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", raw).split())[:limit]


def keep_message(name: str, analysis: Mapping, *, pinned: bool = False) -> str:
    """"Keep going: no change", in numbers: the weakest part of the record that was left alone and why, and that the hound keeps
    its rule. Never a promise and never a forecast. ``pinned`` adds that the owner asked to keep the sports as they are."""
    held = analysis.get("held") or []
    overall = analysis["overall"]
    if held:
        seg = held[0]
        spot = f"{_record_text(seg)} on {seg['n']} {seg['phrase']}"
        if seg.get("reason") == "core":
            body = (f"{spot} is its weakest part, but {seg['label']} is what {name} is for, so the coach does not cut it. "
                    f"Nothing else stood out, so {name} keeps its rule.")
        elif seg.get("reason") == "noise":
            body = (f"{spot} is inside what luck does at these prices. Nothing here is a pattern, so {name} keeps its rule.")
        else:
            body = (f"{spot} is too few to tell from luck at these prices. Nothing here is a pattern yet, so {name} keeps its rule.")
    elif overall["n"]:
        body = (f"{name} went {_record_text(overall)} over {overall['n']} settled bets, and no part of that record stood out, "
                f"so it keeps its rule.")
    else:
        body = f"{name} has no settled bets on this version yet, so there is nothing to read and it keeps its rule."
    if pinned:
        body += " You asked to keep the sports as they are, so no sport change is proposed."
    return body


def _nothing_message(dog, mode: str, analysis: Optional[Mapping] = None, *, pinned: bool = False) -> str:
    if mode == "keep" and analysis is not None:
        return keep_message(dog.name, analysis, pinned=pinned)
    if mode == "loosen":
        return (f"{dog.name} has not bet yet, and none of the changes it is allowed to make would add a game to today's board, "
                "so there is nothing sensible to change. Tell it what you would like instead, or say no.")
    return f"{dog.name} is already as careful as its rule can be, so there is nothing left to train."


def _losses_block(bets: Sequence, rows: Sequence, hound_id: str, hindsight_fn: Optional[Callable]) -> Optional[dict]:
    """The "Why it lost" block of the card (``loss_why.loss_breakdown``), or None if it could not be built: a card is better
    without the block than not drawn at all. ``hindsight_fn(hound_id, bets)`` -> ``{bet_id: review}`` is the caller's way to hand
    in the hindsight reviews (a file read, never a model); with none, the breakdown runs on closing price and score alone."""
    try:
        reviews = hindsight_fn(hound_id, bets) if hindsight_fn is not None else None
        return loss_why.loss_breakdown(loss_why.settled_rows(bets, rows), reviews)
    except Exception as exc:  # noqa: BLE001
        logger.warning("training review: the loss breakdown failed (%s)", type(exc).__name__)
        return None


def review(dog: Optional[common.Dog], user_id: int, coach=None, *, origin=None, chat: Sequence = (), tweak: Optional[str] = None,
           round_no: int = 0, board_fn: Optional[Callable] = None, router=None, env: Optional[Mapping] = None,
           now: Optional[datetime] = None, rows: Optional[Sequence] = None, ledger_path: Optional[str] = None, db=None,
           hindsight_fn: Optional[Callable] = None) -> dict:
    """The proposal card for a training: what the hound would change, each change with its reason, what today's board would have
    said, and the owner's choices. WRITES NOTHING. Same refusals as ``train`` minus the confirm (an open ticket, too soon).

    ``origin`` ``"chat"`` is a Retune from the Ask chat (``chat`` holds the owner's lines): the proposal is mapped from those
    lines. A ``tweak`` (the owner's reason or what they want instead) re-maps the proposal from the chat lines plus that line,
    at most ``retune.TWEAK_ROUNDS`` times per hound and rule.

    The card also carries ``core`` (the sports and markets the hound is for, which the coach never proposes to cut: ``identity.py``)
    and ``losses`` (why it lost: ``loss_why.py``). When nothing clears the evidence bar the default proposal is "Keep going: no
    change" (``mode`` ``keep``, ``nothing`` true). A tweak that says to keep the sports as they are (``retune.KEEP_CID``) takes every
    sport change out of the proposal (``kept_sports``): the default proposal is then rebuilt without them."""
    from src.hounds.interact import coach as coach_mod, retune
    origin = _clean_origin(origin)
    dog, _moment, rows, bets, hound, gate = _ready(dog, user_id, confirmed_required=False, confirmed=False, now=now, rows=rows,
                                                    ledger_path=ledger_path, db=db)
    spec = hound["spec"]
    core = identity.identity_of(hound)
    analysis = analyse(bets, spec, rule_index_of(rows, dog.id), core=core)
    the_coach = coach or coach_mod.Coach(rules_only=True)
    lines = retune.clean_lines(chat)
    used = tweaks_used(dog.id, spec)
    mapper, read, table, message, pinned = None, None, None, "", False
    if tweak is not None:
        line = _clip(tweak, retune.LINE_MAX)
        if not line:
            raise RiteError("tweak_empty", "Say what you want changed, or why, and the hound will look again.", 422)
        used = max(used, min(max(int(round_no or 0), 0), retune.TWEAK_ROUNDS))
        if used >= retune.TWEAK_ROUNDS:
            raise RiteError("tweak_limit", f"That is {retune.TWEAK_ROUNDS} tweaks. Apply the proposal, or say no and start again.",
                            409, tweak={"used": used, "left": 0, "max": retune.TWEAK_ROUNDS})
        lines = (lines + [line])[-retune.MAX_CHAT_LINES:]
    if tweak is None and origin is None:
        plan = _default_plan(dog, hound, bets, rows, analysis, gate, coach, board_fn)
        new_spec, changes, mode, note, read, table = plan["spec"], plan["changes"], plan["mode"], plan["note"], plan["read"], plan["table"]
        entries = _menu_for(spec, analysis, table, origin, core=core, lines=lines)
        if not changes:
            message = _nothing_message(dog, mode, analysis)
    else:
        table = the_coach.diagnosis(_coach_input(dog, hound, bets, rows, analysis, spec)) if origin is None else None
        entries = _menu_for(spec, analysis, table, origin, core=core, lines=lines)
        counted = retune.whatif(spec, entries, board_fn)
        mapper = retune.map_chat(lines, entries, counted, router=router, env=env)
        # "keep the sports as they are" is a directive, not a change: it takes every sport change out of what the owner's other
        # words mapped to, and leaves the rest of the training to the default proposal (built without the sports)
        by_cid = {e["cid"]: e for e in entries}
        pinned = any(i["cid"] == retune.KEEP_CID for i in mapper["items"])
        items = [i for i in mapper["items"] if i["cid"] != retune.KEEP_CID
                 and not (pinned and by_cid[i["cid"]]["id"] in retune.SPORT_CHANGE_IDS)]
        new_spec, changes = _apply_items(spec, items, entries)
        if tweak is not None:
            used = _tweak_bump(dog.id, spec, at_least=used)
        mode, note = ("retune" if origin else "owner"), ""
        if pinned and not changes and origin is None:
            plan = _default_plan(dog, hound, bets, rows, analysis, gate, coach, board_fn, pin_sports=True)
            new_spec, changes, mode, note, read, table = plan["spec"], plan["changes"], plan["mode"], plan["note"], plan["read"], plan["table"]
        if not changes:
            new_spec = None
            if pinned:
                mode = "keep"
                message = _nothing_message(dog, "keep", analysis, pinned=True)
            else:
                message = ("I could not turn that into a change I am allowed to make. Say it another way." if tweak is not None else
                           "I could not turn what you said into a change I am allowed to make, so I would leave my rule as it is.")
    framing = f"{dog.name} has not bet yet. Want it to look at more games?" if analysis["settled"] <= NOT_BETTING_SETTLED else None
    today = _today_block(spec, new_spec, changes, entries, board_fn)
    return {
        "origin": origin or "training", "mode": mode, "note": note, "light": gate["light"], "settled": analysis["settled"],
        "version_no": hound["version_no"], "name": dog.name, "framing": framing, "message": message,
        "core": identity.core_view(core), "losses": _losses_block(bets, rows, dog.id, hindsight_fn), "kept_sports": pinned,
        "kept_note": "Sports kept as they are, as you asked." if pinned else None,
        "basis": proposal_basis(dog.id, spec),
        "changes": [dict(c) for c in changes], "picks": [c["cid"] for c in changes], "nothing": not changes,
        "today": today, "owner_feedback": owner_feedback(dog, user_id, db=db),
        "mapper": None if mapper is None else {k: mapper[k] for k in ("source", "label", "status")},
        "coach": coach_view(read) if read is not None and origin is None else None,
        "tweak": {"used": used, "left": max(0, retune.TWEAK_ROUNDS - used), "max": retune.TWEAK_ROUNDS},
        "limit_note": "Applying counts as a training and makes a new version. Saying no changes nothing and does not count.",
        "honesty": retune.HONESTY, "paper_only": True,
    }


def owner_feedback(dog: common.Dog, user_id: int, *, db=None) -> Optional[dict]:
    """The owner's own Good / Bad calls on this hound's picks and answers, as a LABELLED INPUT to the review ("3 Bad calls: 2 bad
    price"). It is shown beside the proposal and weighed by the owner; it is not an input to the coach's cache key, the menu or
    the mapper, so it never changes what is proposed and nothing here applies without their Apply. None when they have not voted
    (or the table cannot be read: a feedback problem must not stop a training review)."""
    try:
        got = store.owner_evidence(dog.root_id, user_id, db=db)
    except Exception:  # noqa: BLE001
        return None
    if not (got["good"] or got["bad"]):
        return None
    return {"label": "Your own Good call / Bad call votes on this hound", "good": got["good"], "bad": got["bad"],
            "chips": got["chips"], "text": got["text"], "notes": got["notes"],
            "note": "Shown for you to weigh. It changes nothing by itself; only Apply does."}


def veto(dog: Optional[common.Dog], user_id: int) -> dict:
    """The owner says no to a proposal. Nothing is written: no version, no event, no frozen record, and the training limit is
    untouched (a limit counts versions made by training, and none is made). The tweak rounds for this hound are cleared."""
    dog = rites.guard(dog, user_id)
    _tweaks_clear(dog.id)
    return {"vetoed": True, "changed": False, "counts_toward_limit": False, "version_no": (dog.hound or {}).get("version_no"),
            "headline": f"{dog.name} stays as it is. Nothing was changed, and this does not count as a training.", "paper_only": True}


def gate_for(dog: Optional[common.Dog], user_id: int, *, now: Optional[datetime] = None, rows: Optional[Sequence] = None,
             ledger_path: Optional[str] = None, db=None) -> tuple:
    """``(allowed, message)``: whether this hound could be trained now, as a sentence. Reads only. Ask uses it to decide whether
    its Retune button works; the real refusal still comes from ``review`` and ``train``."""
    try:
        _ready(dog, user_id, confirmed_required=False, confirmed=False, now=now, rows=rows, ledger_path=ledger_path, db=db)
    except RiteError as exc:
        return False, str(exc)
    return True, ""


def train(dog: Optional[common.Dog], user_id: int, *, confirmed: bool = False, now: Optional[datetime] = None,
          rows: Optional[Sequence] = None, ledger_path: Optional[str] = None, db=None,
          env: Optional[Mapping] = None, poster: Optional[Callable] = None, background: bool = True,
          coach=None, picks: Optional[Sequence[str]] = None, origin=None, board_fn: Optional[Callable] = None,
          basis: Optional[str] = None, require_review: bool = False) -> dict:
    """APPLY a training for ``user_id``. Returns the "what changed and why" card or raises ``RiteError``.

    ``require_review`` (the HTTP route always sets it): an Apply must carry the ``picks`` of a review card. A bare
    ``{"confirm": true}`` (the old one-tap Send to training, e.g. a page cached from before the review existed) is refused as
    ``review_required`` (409) and writes nothing, so no training is ever made without the owner seeing the proposal first.

    ``coach`` is the ``coach.Coach`` that reads the diagnosis (the live routes pass ``coach.live()``, whose read the page already
    waited for and which is cached, so it is not paid for twice). With none, the rules engine reads it: no router, no disk.

    ``picks`` are the menu cids the owner left ticked on the review card; with them the changes are exactly those (rebuilt from
    the menu and re-validated). With none, the default proposal is applied (the caller said yes without choosing). ``origin``
    ``"chat"`` marks the new version "owner retune (from chat)" in its lineage. ``board_fn`` is only used to choose the default
    changes for a hound that is not betting.

    ``basis`` is the review card's ``proposal_basis``. An Apply of a reviewed proposal (``picks`` or ``basis`` given) on a version that
    is no longer the live one, or whose rule is not the one the card was drawn for, is refused as ``proposal_stale`` (409) with a
    sentence that says so, never applied to whatever the rule has become; the same refusal answers the second of two Applies that
    race (the store's own transaction lets exactly one of them retire the old version)."""
    from src.hounds.interact import coach as coach_mod, retune
    origin = _clean_origin(origin)
    reviewed = picks is not None or basis is not None
    try:
        dog = rites.guard(dog, user_id)
    except RiteError as exc:
        if reviewed and exc.code == "not_active":
            raise _stale(dog.name) from None
        raise
    if reviewed:
        # checked BEFORE the training gate: a double-tapped Apply is "out of date", not "too soon to train again"
        live = user_store.get_hound(dog.id, db=db)
        if live is not None and (live["status"] == user_store.STATUS_RETIRED
                                 or (basis is not None and str(basis) != proposal_basis(dog.id, live["spec"]))):
            raise _stale(dog.name)
    dog, moment, rows, bets, hound, gate = _ready(dog, user_id, confirmed_required=True, confirmed=confirmed, now=now, rows=rows,
                                                    ledger_path=ledger_path, db=db)
    if require_review and picks is None:
        raise RiteError(REVIEW_REQUIRED, f"Look at {dog.name}'s proposal first: open Send to training again, check the changes, "
                                         "then tap Apply. Nothing was changed.", 409)
    spec = hound["spec"]
    core = identity.identity_of(hound)
    analysis = analyse(bets, spec, rule_index_of(rows, dog.id), core=core)
    the_coach = coach or coach_mod.Coach(rules_only=True)
    inp = _coach_input(dog, hound, bets, rows, analysis, spec)
    if picks is not None:
        table = the_coach.diagnosis(inp) if origin is None else None
        # Apply re-checks a card the owner has read and ticked, so the lock is not applied again here: a core sport can only be on
        # that card because the owner's own words asked for it (``review`` enforced the lock when the card was drawn)
        entries = _menu_for(spec, analysis, table, origin, core=core, enforce=False)
        new_spec, changes = _picked_plan(spec, picks, entries)
        read = the_coach.read(inp, menu(spec, analysis, table), table) if origin is None else None
        mode, note = _mode_of(changes, gate, origin, analysis["settled"])
        if not changes:
            new_spec = None
    else:
        plan = _default_plan(dog, hound, bets, rows, analysis, gate, the_coach, board_fn)
        new_spec, changes, mode, note, read, table = plan["spec"], plan["changes"], plan["mode"], plan["note"], plan["read"], plan["table"]
        if origin and changes:
            mode = "retune"
    if new_spec is None:
        raise RiteError("nothing_to_change", _nothing_message(dog, mode, analysis), 409)
    if mode in ("retune", "loosen", "owner"):
        text = guidance_owner(dog.name, analysis, changes, mode, hound["version_no"])
    else:
        text = guidance_text(dog.name, analysis, changes, mode, note, hound["version_no"])
    frozen = dict(analysis["overall"])
    applied = [c["cid"] for c in changes if c.get("pick") == "coach"]
    if read is not None:
        coach_event = {"source": read["source"], "status": read["status"], "model": read.get("model"),
                       "cost_usd": read.get("cost_usd") or 0.0,
                       "reasons": [{"factors": r["factors"], "confidence": r["confidence"]} for r in read["reasons"]],
                       "picks": list(read.get("picks") or []), "picks_applied": applied,
                       "cuts_examined": table["meta"]["cuts_examined"] if table else None}
    else:
        coach_event = {"source": "none", "status": "not_asked", "model": None, "cost_usd": 0.0, "reasons": [], "picks": [],
                       "picks_applied": [], "cuts_examined": None}
    event = {"kind": user_store.EVENT_TRAINED,
             "payload": {"name": hound["name"], "from_hound_id": dog.id, "from_version": hound["version_no"],
                         "to_version": hound["version_no"] + 1, "mode": mode, "settled": analysis["settled"],
                         "origin": origin or "training", "owner_chosen": picks is not None,
                         "record": {k: frozen[k] for k in ("wins", "losses", "pushes")},
                         "changes": [{k: c[k] for k in ("id", "label", "old_text", "new_text")} for c in changes],
                         "coach": coach_event}}
    try:
        new = user_store.create_version(dog.id, new_spec, actor=f"owner:{user_id}",
                                        reason=retune.LINEAGE_LABEL if origin else "sent to training", now=moment,
                                        db=db, coached_from=dog.id, event=event, origin=origin)
    except user_spec.SpecError as exc:
        raise RiteError("spec_invalid", "The trained rule did not pass the menu's checks, so nothing was changed.", 422,
                        fields=exc.errors)
    except user_store.StoreError as exc:
        if exc.code == "retired":
            raise _stale(dog.name, applied_elsewhere=True) from None    # two Applies raced and the other one made the version
        status = {"not_found": 404, "buried": 409}.get(exc.code, 400)
        raise RiteError(exc.code, str(exc), status)
    _tweaks_clear(dog.id)
    logger.info(
        "training done hound=%s from_v=%s to_v=%s mode=%s origin=%s coach=%s status=%s cost_usd=%.6f picks_applied=%d", dog.id,
        hound["version_no"], new["version_no"], mode, origin or "training", coach_event["source"], coach_event["status"],
        coach_event["cost_usd"], len(applied))
    from src.hounds.english import render
    brief = build_brief(dog.name, analysis, changes, mode if mode in ("analysed", "light") else "light", text)
    asked = send_brief(brief, f"training-{new['id']}", env=env, poster=poster, background=background)
    trained_times = user_store.trained_count(new["root_id"], db=db)
    light = mode in ("light", "loosen")
    return {
        "mode": mode, "light_adjustment": light, "origin": origin or "training",
        "label": "Retuned" if mode == "retune" else "Light adjustment" if light else "Trained",
        "lineage": retune.LINEAGE_LABEL if origin else None,
        "headline": (f"{dog.name} is back as version {new['version_no']}. Its new record starts now."),
        "light_note": ("A light adjustment: the hound does not have enough settled bets yet for the coach to find a weak "
                       "spot." if mode == "light" and note == "not_enough_bets" else
                       "A light adjustment: nothing in its record stood out." if mode == "light" else
                       "A light adjustment: the hound had not bet yet, so the changes widen what it looks at."
                       if mode == "loosen" else None),
        "changes": [{k: v for k, v in c.items() if k != "today"} for c in changes],
        "change_sentence": coach_card.change_sentence(changes),
        "diff": render.diff_specs(spec, new["spec"]),
        "analysis": {"settled": analysis["settled"], "overall": analysis["overall"],
                     "weak": analysis["weak"][:3]},
        "coach": coach_view(read, applied) if read is not None else None,
        "diagnosis": ({"settled": table["settled"], "checks": sum(1 for f in table["rows"] if f["kind"] != "unavailable"),
                       "cuts_examined": table["meta"]["cuts_examined"], "ranked": table["ranked"][:5]} if table else None),
        "guidance": {"text": text, "source": "code", "ai_requested": asked},
        "old": {"id": dog.id, "version_no": hound["version_no"], "record": frozen, "frozen": True},
        "new": {"id": new["id"], "version_no": new["version_no"], "coached_from": new["coached_from"], "origin": new.get("origin"),
                "trained_times": trained_times, "page_href": f"hound.html?id={new['id']}",
                "record": {"wins": 0, "losses": 0, "pushes": 0, "bets": 0}},
        "next_training": f"It can train again after {MIN_NEW_SETTLED} new settled bets on version {new['version_no']}.",
        "undo": revert.undo_offer(dog.id, hound["version_no"], new["version_no"]),       # "Undo" on the card: back to the version just retired
        "honesty": retune.HONESTY, "paper_only": True,
    }
