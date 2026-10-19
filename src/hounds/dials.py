"""A dog's rulebook in plain words: what it bets on, and the dials it can be turned on.

WHY THIS EXISTS. The dog page used to hide its rule behind the receipts and never said which numbers in the
rule are dials the referee can turn. "Transparent" means a stranger can read, in one screen, what the dog
does, which thresholds it uses right now, and when they last changed. This module builds that payload for
``GET /hounds/{id}/rulebook`` (api/hounds_tips.py) and the "Coach this dog" panel reads the same dials.

NOTHING HERE MEASURES OR DECIDES ANYTHING. The knobs, bounds and steps are ``tunables.py``'s (read from
``config/house_pack.json``), the current values and the last change are the learning ledger's champion
state. This file only WORDS them. The plain wording lives here, not in the config, for two reasons: the
config's ``label`` is a long methods-style sentence (it feeds the coach brief) and the registered pack's
config is not ours to edit. A test holds this table to the config: every knob of every tunable hound has
an entry, so a new knob cannot ship without plain words.

THE SHAPE OF A DIAL (JSON): ``name, label, kind, min, max, step, default, current, scale, unit, text``.
``text`` is the current value in the dog's words ("3 points"); ``scale`` and ``unit`` let the page word any
other value on the same grid (the coach panel's slider) with ``dialText`` in web/js/hounds-rulebook.js.
A test runs both formatters over every grid point and demands identical strings.
"""

from __future__ import annotations

from typing import Mapping, Optional

from src.hounds.learning import rules, tunables

# (hound id, knob name) -> (what the dial is called, scale applied to the stored value, unit word)
# ``scale`` turns the stored probability into points (x100) so the page reads "3 points", never "0.03".
# A unit of "%" is glued to the number ("50%"); any other unit is a word after it ("3 points").
# AVOID the words the public pages ban (edge, lock, profit): tests/test_hounds_voice.py scans the page text.
DIAL_WORDS = {
    ("professor_paws", "GAP"): ("Gap over the market needed", 100.0, "points"),
    ("professor_paws", "SHRINK"): ("Pull toward the market", 100.0, "%"),
    ("totals_terrier", "GAP"): ("Gap from the market total needed", 100.0, "points"),
    ("relief_retriever", "GAP"): ("Bullpen gap needed", 1.0, "pitches"),
    ("gridiron_greyhound", "BAR"): ("Margin against the spread needed", 1.0, "points"),
    ("jetlag_jack", "NFL_REST_GAP"): ("Extra rest needed (NFL)", 1.0, "days"),
    ("steamy_setter", "MOVE"): ("Steam needed", 100.0, "points"),
    ("stale_bread_beagle", "EDGE"): ("Price gap needed at the best book", 100.0, "points"),
    ("stale_bread_beagle", "MIN_BOOKS"): ("Books quoting before it trusts a price", 1.0, "books"),
    ("bargain_bloodhound", "MARGIN"): ("Discount to fair needed", 100.0, "points"),
    ("hot_streak_husky", "MLB_HOT"): ("Wins in the last 10 to count as hot (MLB)", 1.0, "wins"),
    ("grudge_bulldog", "NFL_MARGIN"): ("Losing margin that starts a grudge (NFL)", 1.0, "points"),
    ("grudge_bulldog", "MLB_MARGIN"): ("Losing margin that starts a grudge (MLB)", 1.0, "runs"),
    ("pack_leader", "MIN_VOTES"): ("Votes needed from the pack", 1.0, "votes"),
}

# "This dog bets when ..." for every house dog: the one-line trigger, no thresholds (the dials carry those).
TRIGGERS = {
    "professor_paws": "the house run model likes a side more than the market does",
    "totals_terrier": "the house run model's total is well off the market's total",
    "relief_retriever": "one bullpen is way more worn out than the other",
    "gridiron_greyhound": "an NFL club's expected margin clears the spread by enough",
    "elimination_basset": "a home club is one loss from going home in the playoffs",
    "jetlag_jack": "a rested club faces a team that flew in overnight",
    "steamy_setter": "the market moves toward one side between the open and bet time",
    "contrary_corgi": "the market steams one way (then it takes the other side)",
    "stale_bread_beagle": "one book's price is stale next to everybody else's",
    "bargain_bloodhound": "a book is selling a side below fair price",
    "kelly_kelpie": "a book is selling a side below fair price (it sizes the bet small)",
    "hot_streak_husky": "a hot club meets a cold one",
    "grudge_bulldog": "a club is out for revenge after a bad loss to the same opponent",
    "numerology_newfie": "the numbers line up (for fun)",
    "lunar_lab": "the moon is full or new (for fun)",
    "coin_flip_collie": "a game is on the board (the coin bets every one; it's the control)",
    "dartboard_dalmatian": "the dart lands on a market that's on the board (a control)",
    "pack_leader": "two or more other dogs agree and nobody disagrees",
    "scrappy_schnauzer": "another dog likes an underdog priced +100 to +250",
    "chalk_chihuahua": "a favourite is priced between -101 and -199",
    "home_dog_hank": "the home club is a +100 to +400 underdog",
}
GENERIC_TRIGGER = "its rule fires on a game"

LAST_CHANGED_BY = "the referee"


def number_text(value: float) -> str:
    """12.0 -> "12", 2.5 -> "2.5", 0.3 -> "0.3": the shortest honest form, one decimal at most."""
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"


def dial_text(scale: float, unit: str, value: float) -> str:
    """A knob value in the dog's words: ``dial_text(100, "points", 0.03)`` -> "3 points"."""
    num = number_text(float(value) * float(scale))
    if unit == "%":
        return f"{num}%"
    if num == "1" and unit.endswith("s"):
        unit = unit[:-1]
    return f"{num} {unit}"


def words_for(hound_id: str, knob: tunables.Knob) -> tuple:
    """``(label, scale, unit)`` for a knob; an undeclared one falls back to the config's own label and
    the raw value (a test keeps that from happening for the shipped pack)."""
    return DIAL_WORDS.get((hound_id, knob.name)) or (knob.label, 1.0, "")


def trigger_for(hound_id: str, tagline: str = "") -> str:
    return TRIGGERS.get(hound_id) or GENERIC_TRIGGER


def champion_state(hound_id: str, *, scope_map: Optional[Mapping] = None) -> tuple:
    """``(version, params, last_promotion_or_None)`` for a pack hound from the learning ledger. An
    unreadable ledger reads as "never changed" (the declared defaults), the same way the lineage view
    treats it."""
    from src.hounds.learning import views
    scope_map = scope_map if scope_map is not None else views.scopes()
    state = views._safe_state(scope_map[rules.SCOPE_HOUSE])
    promos = sorted(state.promotions_for(hound_id), key=lambda p: int(p["to_version"]))
    last = promos[-1] if promos else None
    return state.champion_version(hound_id), state.champion_params(hound_id), last


def rulebook(hound_id: str, *, rule_text: str = "", tagline: str = "", tun_cfg: Optional[Mapping] = None,
             scope_map: Optional[Mapping] = None) -> dict:
    """The rulebook payload for one hound (house or not): the rule, the plain trigger, and for a tunable
    pack hound its dials with their current values and when the referee last changed them."""
    cfg = tun_cfg if tun_cfg is not None else tunables.load()
    tun = cfg.get(hound_id)
    out = {"hound_id": hound_id, "rule_text": rule_text or (tun.rule_text if tun else ""),
           "trigger": trigger_for(hound_id, tagline), "tunable": bool(tun), "dials": [],
           "champion_version": 1, "last_changed": None,
           "only_the_referee": "Only the referee can change a dog. Fans can send tips; tips never change it.",
           "paper_only": True}
    if not tun:
        return out
    version, params, last = champion_state(hound_id, scope_map=scope_map)
    values = tunables.full_values(tun, params)
    for name, knob in tun.knobs.items():
        label, scale, unit = words_for(hound_id, knob)
        out["dials"].append({
            "name": name, "label": label, "kind": knob.kind, "min": knob.lo, "max": knob.hi, "step": knob.step,
            "default": knob.default, "current": values[name], "scale": scale, "unit": unit,
            "text": dial_text(scale, unit, values[name])})
    out["champion_version"] = version
    if last:
        out["last_changed"] = {"version": int(last["to_version"]), "utc": last.get("effective_utc") or last.get("utc"),
                               "by": LAST_CHANGED_BY}
    return out
