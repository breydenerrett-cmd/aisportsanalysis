"""Training a member Gematria hound (owner request 2026-10-28: "the Gematria hound cannot be coached ... it is chalk city").

WHY IT WAS REFUSED, AND WHAT CHANGED. A member Gematria hound used to have no rule of its own to change: the engine, ciphers, lead and price
band were the house's (``user_gematria``'s docstring), so Fine-tune said "forward-only" and Full rebuild said "no rule set to rebuild". It now
has a small PARAMETER SPACE of its own (``user_gematria.TUNING_KEYS``: the price band, how clear the lead must be, the ciphers it reads, plus
its sports, bets a day and stake), every knob only NARROWING what the house rules allow. Training changes those knobs and nothing else. It can
never become a different kind of hound: ``vet`` and ``apply_plan`` both refuse a candidate that is not a Gematria spec with the hound's own
stamp, and every candidate goes through ``validate_spec`` (which refuses -200 and worse, an unknown knob, a cipher the rules do not read).

THE SAME REHEARSAL AND EXPLAINER. A candidate is replayed on the captured boards by ``drill.drill_many`` (one pass for the current rule and every
candidate: a hound's signals are computed once per game and shared), judged by the same gate (``training_plans.beats``), and written up by the
same explainer. The Backtest tab still refuses a Gematria hound; only the training screen's rehearsal replays one, labelled hindsight.

ANTI-CHALK. The decision never chooses a side by price: the price only vetoes (``gematria.decision``), and the house band starts at -199, so a
heavy favourite the numbers like passes straight through. ``chalk_report`` reads the hound's own bets; when it mostly backs favourites the
Fine-tune menu puts "stay off heavy favourites" (price floor -150) and "plus money only" (floor +100) FIRST, so they are always among the
candidates rehearsed. They are offered only if they beat the current rule on the rehearsal like any other change. The -200 rule is not a knob.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Mapping, Optional, Sequence

from src.hounds import user_gematria as G
from src.hounds import user_rules, user_spec
from src.hounds.interact import rebuild_ai

# ---------------------------------------------------------------------------
# the chalk read
# ---------------------------------------------------------------------------

CHALK_PRICE = -150               # a favourite this short or shorter is "heavy"
CHALK_MIN_BETS = 8               # fewer priced bets than this cannot show a lean
CHALK_FAVOURITE_SHARE = 0.60     # at least this share of its bets on favourites ...
CHALK_HEAVY_SHARE = 0.30         # ... or at least this share on HEAVY favourites reads as chalk


def _price_of(bet) -> Optional[float]:
    price = bet.price_average if getattr(bet, "price_average", None) is not None else getattr(bet, "price", None)
    return float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) and abs(price) >= 100 else None


def chalk_report(bets: Sequence) -> dict:
    """How the hound's own bets (every forward bet with a price, settled or not) split by price. Facts about the past; ``chalk`` is True when
    it mostly backs favourites. ``text`` says it in numbers, never in a forecast."""
    prices = [p for p in (_price_of(b) for b in bets) if p is not None]
    n = len(prices)
    fav = sum(1 for p in prices if p < 0)
    heavy = sum(1 for p in prices if p <= CHALK_PRICE)
    fav_share = round(fav / n, 3) if n else 0.0
    heavy_share = round(heavy / n, 3) if n else 0.0
    chalk = n >= CHALK_MIN_BETS and (fav_share >= CHALK_FAVOURITE_SHARE or heavy_share >= CHALK_HEAVY_SHARE)
    if not n:
        text = "It has no priced bets yet, so there is no lean to read."
    elif chalk:
        text = f"It leans on favourites: {fav} of its {n} bets were on favourites, {heavy} of them at {CHALK_PRICE} or worse."
    else:
        text = f"It does not mostly back favourites: {fav} of its {n} bets were on favourites, {heavy} of them at {CHALK_PRICE} or worse."
    return {"bets": n, "favourites": fav, "heavy": heavy, "plus_money": n - fav, "favourite_share": fav_share, "heavy_share": heavy_share,
            "chalk": chalk, "heavy_price": CHALK_PRICE, "text": text}


# ---------------------------------------------------------------------------
# the current settings
# ---------------------------------------------------------------------------

def effective_rules(spec: Mapping):
    """The rules the hound's picks are made under: the ACTIVE house rules with the member's knobs over them (narrowing only)."""
    return G.tuned_rules(G.load_rules(), G.tuning_of(spec))


def _p(price: int) -> str:
    return f"+{price}" if price > 0 else str(price)


def band_text(lo: int, hi: int) -> str:
    if lo >= 100:
        return f"{_p(lo)} to {_p(hi)} (plus money only)"
    return f"{_p(lo)} to {_p(hi)}"


def knobs_json(spec: Mapping) -> dict:
    """The settings of a Gematria hound as the designer is shown them: its own knobs, and what they come to under today's house rules."""
    eff = effective_rules(spec)
    d = eff.decision
    return {"sports": list(spec["sports"]), "max_bets_per_day": spec["max_bets_per_day"], "stake_units": spec["stake_units"],
            "tuning": G.tuning_of(spec) or {},
            "in_effect": {"price_band": list(d.price_band), "min_margin": d.min_margin, "min_z": d.min_z, "ciphers": list(eff.ciphers)}}


def catalog_json() -> dict:
    """Every knob and its limits, as the designer is shown them."""
    house = G.load_rules()
    d = house.decision
    from src.hounds.pack import base
    return {"sports": list(user_spec.SPORTS),
            "max_bets_per_day": list(user_spec.MAX_BETS_RANGE), "stake_units": list(user_rules.STAKE_CHOICES),
            "tuning": {"price_min": {"kind": "American price", "from": base.PRICE_MIN, "to": base.PRICE_MAX, "house": d.price_band[0],
                                     "meaning": "the shortest price (heaviest favourite) a bet may be at; raise it to stay off favourites"},
                       "price_max": {"kind": "American price", "from": base.PRICE_MIN, "to": base.PRICE_MAX, "house": d.price_band[1],
                                     "meaning": "the longest price a bet may be at; lower it to stay off long shots"},
                       "min_margin": {"kind": "number", "from": d.min_margin, "to": G.MARGIN_RANGE[1], "house": d.min_margin,
                                      "meaning": "how far ahead the stronger side's count must be; raise it for fewer, clearer cases"},
                       "min_z": {"kind": "number", "from": d.min_z, "to": G.Z_RANGE[1], "house": d.min_z,
                                 "meaning": "the lead in units of the game's own noise; raise it to skip noisy games"},
                       "ciphers": {"kind": "list", "choose_from": list(house.ciphers), "at_least": G.MIN_CIPHERS, "house": list(house.ciphers),
                                   "meaning": "which letter-value ciphers are read; fewer ciphers means fewer matches"}},
            "fixed": ["the market is moneyline", "the engine picks the side with the larger count", "a price of -200 or worse is never taken"]}


# ---------------------------------------------------------------------------
# FINE-TUNE: the menu
# ---------------------------------------------------------------------------

MENU_MAX = 8                    # entries on the menu; Fine-tune rehearses the first ``training_plans.GEMATRIA_MAX_REPLAYS`` of them
PRICE_FLOORS = (-150, -110, 100)
PLUS_MONEY = 100


def _raw(spec: Mapping, *, tuning: Optional[Mapping] = None, **top) -> dict:
    """``spec`` as a raw Gematria spec with ``tuning`` laid over its own (a None value removes that knob) and ``top`` fields replaced. The
    derived rule is dropped so validation derives it again from the new knobs and sports."""
    new = {k: copy.deepcopy(v) for k, v in spec.items() if k not in ("rules", "markets", "side_rule")}
    stamp = dict(new.get("gematria") or {})
    t = dict(stamp.get("tuning") or {})
    for key, value in (tuning or {}).items():
        if value is None:
            t.pop(key, None)
        else:
            t[key] = value
    if t:
        stamp["tuning"] = t
    else:
        stamp.pop("tuning", None)
    new["gematria"] = stamp
    new.update(top)
    return new


def _entry(cid: str, label: str, old: str, new: str, why: str, *, tuning: Optional[Mapping] = None, top: Optional[Mapping] = None,
           segment: Optional[Mapping] = None, direction: str = "narrow", entry_id: Optional[str] = None) -> dict:
    eid = entry_id or cid.split(":")[0]

    def build(spec):
        return {"id": eid, "label": label, "old_text": old, "new_text": new, "spec": _raw(spec, tuning=tuning, **(top or {}))}
    return {"cid": cid, "id": eid, "addresses": [cid], "text": f"{label}: {old} to {new}", "segment": segment, "why": why, "build": build,
            "direction": direction}


def _record(seg: Mapping) -> str:
    rec = f"{seg['wins']}-{seg['losses']}" + (f"-{seg['pushes']}" if seg["pushes"] else "")
    return f"{seg['n']} {seg['phrase']} went {rec} ({seg['units']:+.2f}u at the average price)"


def menu(spec: Mapping, analysis: Mapping, bets: Sequence) -> list:
    """The changes Fine-tune may try on a Gematria hound, best-supported first, each a valid spec on its own (``training._apply_entry``
    validates it). Anti-chalk first when the record leans on favourites, then the weak spots the record shows, then a clearer lead, fewer
    ciphers and a plain price floor, and last the ways back toward the house rules. At most ``MENU_MAX``."""
    eff = effective_rules(spec)
    d = eff.decision
    lo, hi = d.price_band
    tuning = G.tuning_of(spec) or {}
    chalk = chalk_report(bets)
    out: list = []
    seen: set = set()

    def add(entry: dict) -> None:
        if entry["cid"] not in seen:
            seen.add(entry["cid"])
            out.append(entry)

    def floor(value: int, why: str, segment: Optional[Mapping] = None) -> None:
        if lo < value <= hi:
            tail = "plus money only" if value >= PLUS_MONEY else f"no favourite shorter than {_p(value)}"
            add(_entry(f"price_floor:{value}", "Price band", band_text(lo, hi), band_text(value, hi), why, tuning={"price_min": value},
                       segment=segment, entry_id="tighten_band" if segment else "price_floor"))
            out[-1]["text"] += f" ({tail})"

    def ceiling(value: int, why: str, segment: Optional[Mapping] = None) -> None:
        if lo <= value < hi:
            add(_entry(f"price_ceiling:{value}", "Price band", band_text(lo, hi), band_text(lo, value), why, tuning={"price_max": value},
                       segment=segment, entry_id="tighten_band" if segment else "price_ceiling"))

    if chalk["chalk"]:
        n, heavy, fav = chalk["bets"], chalk["heavy"], chalk["favourites"]
        floor(-150, f"{fav} of its {n} bets were on favourites, {heavy} of them at {CHALK_PRICE} or worse, so the next version stays off "
                    "heavy favourites.")
        floor(PLUS_MONEY, f"{fav} of its {n} bets were on favourites, so the next version takes plus-money prices only.")
    for seg in analysis.get("weak", ()):
        if seg["dimension"] == "band":
            line = _record(seg) + ", its weakest part, so the next version no longer takes them."
            if seg["key"] == "short_favourites":
                floor(-150, line, seg)
            elif seg["key"] == "favourites":
                floor(-110, line, seg)
            elif seg["key"] == "underdogs":
                ceiling(109, line, seg)
            elif seg["key"] == "long_shots":
                ceiling(199, line, seg)
        elif seg["dimension"] == "sport" and len(spec["sports"]) >= 2 and seg["key"] in spec["sports"]:
            keep = [s for s in spec["sports"] if s != seg["key"]]
            add(_entry(f"drop_sport:{seg['key']}", "Sports", user_spec.sports_phrase(spec["sports"]), user_spec.sports_phrase(keep),
                       _record(seg) + ", its weakest part, so the next version no longer plays it.", top={"sports": keep}, segment=seg))
    if d.min_margin + 1.0 <= G.MARGIN_RANGE[1]:
        add(_entry("lead:margin", "Lead needed", f"at least {d.min_margin:g}", f"at least {d.min_margin + 1.0:g}",
                   "It asks for a clearer lead before it backs a side, so it bets less and only on clearer cases.",
                   tuning={"min_margin": round(d.min_margin + 1.0, 2)}))
    if d.margin_mode == "noise_scaled" and d.min_z + 0.5 <= G.Z_RANGE[1]:
        add(_entry("lead:noise", "Lead against the game's noise", f"{d.min_z:g} times", f"{d.min_z + 0.5:g} times",
                   "It asks for a lead that stands out from the game's own noise, so it skips games with many coincidences.",
                   tuning={"min_z": round(d.min_z + 0.5, 2)}))
    floor(-150, "It tries staying off heavy favourites, the price band the numbers cannot choose between.")
    if len(eff.ciphers) > G.MIN_CIPHERS:
        for cipher in reversed(eff.ciphers):
            keep = [c for c in eff.ciphers if c != cipher]
            add(_entry(f"drop_cipher:{cipher}", "Ciphers read", ", ".join(eff.ciphers), ", ".join(keep),
                       f"It stops reading the {cipher} cipher, so fewer coincidences count as evidence.", tuning={"ciphers": keep}))
    house = G.load_rules()
    hd = house.decision
    for key, label, house_value, text in (("price_min", "Price band", hd.price_band[0], "the house price floor"),
                                          ("price_max", "Price band", hd.price_band[1], "the house price ceiling"),
                                          ("min_margin", "Lead needed", hd.min_margin, "the house lead"),
                                          ("min_z", "Lead against the game's noise", hd.min_z, "the house noise lead"),
                                          ("ciphers", "Ciphers read", None, "all the house ciphers")):
        if key in tuning:
            add(_entry(f"loosen:{key}", label, "its own setting", text, f"It goes back to {text}, a looser setting than it has now.",
                       tuning={key: None}, direction="widen", entry_id="loosen"))
    return out[:MENU_MAX]


# ---------------------------------------------------------------------------
# FULL REBUILD: the profile
# ---------------------------------------------------------------------------

GEMATRIA_MIN_POINTS = 4           # a rebuild must differ from the current settings by at least this many points ...
GEMATRIA_MIN_AREAS = 2            # ... and in at least this many of: price band, lead, ciphers, sports, volume
ALLOWED_KEYS = frozenset({"sports", "max_bets_per_day", "stake_units", "tuning", "style", "version", "name", "tagline", "color", "badge",
                          "gematria", "rules", "markets", "side_rule", "lock_minutes", "rank_by", "bet_in_play"})

GEM_ANGLES = (
    ("price", "Price band and favourites",
     "Re-think the PRICE BAND (price_min and price_max). Read the chalk lines and the price breakdown: where along the odds the wins "
     "came from and where the units were lost. If it leans on favourites, move price_min up (for example to -150, -110 or +100) or cap long "
     "shots with price_max. Choose the band the record supports, not a notch."),
    ("lead", "How clear the lead must be",
     "Re-think HOW CLEAR the lead must be (min_margin and min_z): fewer, clearer cases or more volume? Use the rehearsal's bet counts and "
     "the record's losers to decide, and combine it with at least one other change."),
    ("ciphers", "Which ciphers it reads",
     "Re-think WHICH CIPHERS are read (at least two). Fewer ciphers means fewer coincidences count as evidence. Combine it with a price or "
     "lead change so the rebuild is a real departure."),
    ("sports", "Which sports it plays",
     "Re-think WHICH SPORTS it plays: cut the sports where the record is weak, add sports the catalog offers where the numbers can read "
     "names and dates, and move the price band to suit what remains."),
    ("volume", "Bet volume and stake",
     "Re-think HOW MUCH it bets (max_bets_per_day and stake_units) together with how selective it is, so it bets fewer, better-supported "
     "games. Pair it with a price or lead change."),
    ("restart", "Start over from the record",
     "Ignore the current settings completely. Read the record as if you had never seen them and choose every setting you would use from "
     "this record alone: sports, price band, lead, ciphers, bets a day and stake."),
)

ASK = "Write a complete set of settings that is a major departure from the current one."


def angles(count: Optional[int] = None) -> tuple:
    n = rebuild_ai.ANGLE_COUNT if count is None else count
    return GEM_ANGLES[:max(1, min(int(n), len(GEM_ANGLES), rebuild_ai.MAX_PARALLEL))]


def _limits_text() -> str:
    house = G.load_rules()
    d = house.decision
    return (f"- sports: any of {', '.join(user_spec.SPORTS)} (at least one).\n"
            f"- max_bets_per_day: a whole number from {user_spec.MAX_BETS_RANGE[0]} to {user_spec.MAX_BETS_RANGE[1]}. "
            f"stake_units: one of {list(user_rules.STAKE_CHOICES)}.\n"
            f"- tuning.price_min / price_max: American prices from -199 to +400; they can only NARROW the house band "
            f"({d.price_band[0]} to {d.price_band[1]}). A price of -200 or worse is never allowed.\n"
            f"- tuning.min_margin: {d.min_margin:g} to {G.MARGIN_RANGE[1]:g} (the house value is the least). "
            f"tuning.min_z: {d.min_z:g} to {G.Z_RANGE[1]:g} (the house value is the least).\n"
            f"- tuning.ciphers: at least {G.MIN_CIPHERS} of {', '.join(house.ciphers)}.\n")


def system_text() -> str:
    return (
        "You are a settings designer for a paper-betting app. A member's \"Gematria hound\" picks paper bets (pretend money, never real): for "
        "each game it counts numerical coincidences in the names, dates and stored results of the two teams (the same engine as the house "
        "Gematria Hound), backs the side with the larger count only if the lead is clear enough, and only if that side's average price is "
        "inside a band. The engine chooses the side; the price only vetoes.\n\n"
        "You get everything: the hound's current settings (JSON and in plain English), its FORWARD record (every graded paper bet it made "
        "live, which counts toward its public record), a CHALK read (how often it backed favourites), its REHEARSAL record (the current "
        "settings replayed over recently captured boards: hindsight, never counted, shown only so you can see how it behaves), breakdowns by "
        "sport and price band, the biggest losers, and the limits.\n\n"
        "YOUR JOB: design settings that are a MAJOR departure from the current ones, aimed at the weaknesses the record shows and keeping what it "
        "supports. A cosmetic nudge (one number by a notch) is a failed answer: change at least two different areas (price band, lead, "
        "ciphers, sports, volume). Your brief names the angle to attack; stay on it but write COMPLETE settings.\n\n"
        "Be honest about the evidence. A segment with a handful of bets is noise, not a finding; say so in your summary rather than building on "
        "it. Never claim the new settings will win or make money: you are proposing different settings to be rehearsed, nothing more.\n\n"
        "THE ONLY THINGS YOU MAY CHANGE (a program checks every one; anything that breaks a limit is thrown away whole, never repaired). "
        "You cannot change what kind of hound this is, its market (always moneyline), or how it picks a side; an answer that names a rule list, "
        "another style or a market is refused.\n" + _limits_text() + "\n"
        f"Answer ONLY in the requested JSON: \"summary\" (what you changed and why, in plain words, tied to numbers in the record, at most "
        f"{rebuild_ai.SUMMARY_MAX} characters) and \"spec_json\" (one JSON string holding an object with sports, max_bets_per_day, "
        "stake_units and tuning).")


def analyst_text() -> str:
    return (
        "You are the analyst in a paper-betting app's Gematria hound rebuild. Several designers each proposed different complete settings for "
        "the same hound, and a program has already enforced the hard limits and replayed each one on the same captured boards (a rehearsal: "
        "hindsight, never counted, not evidence of future results).\n\n"
        "You get the hound's current settings and record, every surviving candidate with its settings in plain English and its rehearsal "
        "numbers (graded bets, wins, losses, units, units per bet), and the limits. Compare them honestly. Pick the strongest, or MERGE the best "
        "parts of two or three into one complete set of settings. Prefer a candidate whose rehearsal numbers and sample size support it; say "
        "plainly when a sample is small. Your merge must still be a MAJOR change from the current settings.\n\n"
        "Flag weak spots: thin samples, a setting that only works because of one sport or price band. Tie every reason to a figure you were "
        "given; never invent a figure.\n\n"
        "The same hard limits apply to your merged settings as to the candidates:\n" + _limits_text() +
        "A program re-checks and re-replays whatever you return. Answer ONLY in the requested JSON.")


def build_context(*, name: str, version_no: int, spec: Mapping, plain_rule: str, bets: Sequence[Mapping], analysis: Mapping,
                  baseline: Optional[Mapping], chalk: Mapping) -> str:
    """Everything the designer is shown: the current settings, the whole forward record and its cuts, the chalk read, the rehearsal and
    the knob catalog. The same for every angle (only the brief that follows differs)."""
    shown = list(bets)[-rebuild_ai.MAX_BETS_IN_PROMPT:]
    losers = sorted((b for b in bets if b.get("result") == "loss"), key=lambda b: b.get("units") or 0.0)[:rebuild_ai.LOSERS_SHOWN]
    overall = analysis.get("overall") or {}
    parts = [rebuild_ai.DATA_NOTICE, "",
             f"HOUND: {name}, version {version_no}. A Gematria hound.",
             "CURRENT SETTINGS IN PLAIN ENGLISH:", plain_rule, "",
             "CURRENT SETTINGS (JSON):", json.dumps(knobs_json(spec), separators=(",", ":"), sort_keys=True), "",
             "CHALK READ (facts about its own bets):", "  " + chalk["text"], "",
             "FORWARD RECORD (live graded paper bets; THIS COUNTS toward the hound's public record):",
             f"  settled {analysis.get('settled')}: {overall.get('wins')}-{overall.get('losses')}-{overall.get('pushes')}, "
             f"{overall.get('units')}u at the average price",
             "BREAKDOWNS of the forward record (n bets, wins-losses-pushes, units):", *rebuild_ai._seg_lines(analysis), "",      # noqa: SLF001
             f"BIGGEST FORWARD LOSERS ({len(losers)} shown):", *(("  " + rebuild_ai._bet_line(b)) for b in losers), "",           # noqa: SLF001
             f"EVERY FORWARD BET ({len(shown)} of {len(bets)} shown, oldest first):", *(("  " + rebuild_ai._bet_line(b)) for b in shown), "",  # noqa: SLF001
             "REHEARSAL OF THE CURRENT SETTINGS (replay on captured boards: hindsight, NEVER counted, not evidence):",
             *rebuild_ai._replay_lines(baseline), "",                                                                          # noqa: SLF001
             "THE KNOBS AND THEIR LIMITS (JSON):", json.dumps(catalog_json(), separators=(",", ":"))]
    return "\n".join(parts)


def _first_error(exc: user_spec.SpecError) -> str:
    key, why = next(iter(exc.errors.items()), ("settings", "did not validate"))
    return f"{key} {why}"[:200]


def vet(raw: Any, current: Mapping) -> tuple:
    """``(spec, None)`` for settings that pass every check, else ``(None, reason)``. ``raw`` is the designer's ``spec_json`` (text or object) or
    a stored, already validated Gematria spec (Apply checks the saved plan again with this). The candidate is built FROM THE CURRENT SPEC, so
    the name, look, stamp, market, lock time and side logic cannot change; only sports, bets a day, stake and the knobs are read from ``raw``.
    A different style, or a rule list that is not the Gematria hound's own, is refused whole."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None, "the settings were not valid JSON"
    if not isinstance(raw, Mapping):
        return None, "the settings were not an object"
    if not user_spec.is_gematria(current):
        return None, "this is not a Gematria hound"
    if raw.get("style") not in (None, user_spec.STYLE_GEMATRIA):
        return None, "a Gematria hound stays a Gematria hound; its style cannot change"
    if raw.get("style") is None and ("rules" in raw or "gematria" in raw and not isinstance(raw.get("gematria"), Mapping)):
        return None, "a rule list is not a Gematria hound's; it stays a Gematria hound"
    unknown = sorted(str(k)[:30] for k in raw if k not in ALLOWED_KEYS)
    if unknown:
        return None, f"it named settings a Gematria hound does not have: {', '.join(unknown)}"
    stamp = raw.get("gematria")
    if "tuning" in raw:
        tuning = raw["tuning"]
    elif isinstance(stamp, Mapping) and "tuning" in stamp:
        tuning = stamp["tuning"]
    else:
        tuning = G.tuning_of(current)                      # not named: unchanged
    cand = _raw(current)
    cand["gematria"] = {k: v for k, v in cand["gematria"].items() if k != "tuning"}
    if tuning:
        cand["gematria"]["tuning"] = tuning
    for key in ("sports", "max_bets_per_day", "stake_units"):
        if raw.get(key) is not None:
            cand[key] = raw[key]
    try:
        spec = user_spec.validate_spec(cand, taken_names=())
    except user_spec.SpecError as exc:
        return None, _first_error(exc)
    base = {k: v for k, v in (current.get("gematria") or {}).items() if k != "tuning"}
    if not user_spec.is_gematria(spec) or {k: v for k, v in spec["gematria"].items() if k != "tuning"} != base:
        return None, "a Gematria hound stays a Gematria hound with its own rules stamp"
    return spec, None


def distance(old: Mapping, new: Mapping) -> dict:
    """How far apart two Gematria hounds' settings are, in what they come to under today's rules (so an explicit knob equal to the house value
    counts as no change). Points: a price edge that moved 2, a lead knob that moved 1 (2 for a big move), a cipher added or dropped 2, a sport
    added or dropped 1, bets a day or the stake 1. ``areas`` is how many of price / lead / ciphers / sports / volume changed at all."""
    a, b = effective_rules(old), effective_rules(new)
    da, db = a.decision, b.decision
    price = (2 if da.price_band[0] != db.price_band[0] else 0) + (2 if da.price_band[1] != db.price_band[1] else 0)
    lead = ((1 if da.min_margin != db.min_margin else 0) + (1 if abs(da.min_margin - db.min_margin) >= 1.0 else 0)
            + (1 if da.min_z != db.min_z else 0) + (1 if abs(da.min_z - db.min_z) >= 0.5 else 0))
    ciphers = 2 * len(set(a.ciphers) ^ set(b.ciphers))
    sports = len(set(old["sports"]) ^ set(new["sports"]))
    volume = (1 if old["max_bets_per_day"] != new["max_bets_per_day"] else 0) + (1 if old["stake_units"] != new["stake_units"] else 0)
    detail = {"prices": price, "lead": lead, "ciphers": ciphers, "sports": sports, "volume": volume}
    return {"points": sum(detail.values()), "areas": sum(1 for v in detail.values() if v), "rules_changed": 0, "detail": detail}


def too_similar(dist: Mapping) -> bool:
    return dist["points"] < GEMATRIA_MIN_POINTS or dist["areas"] < GEMATRIA_MIN_AREAS


def similar_text(dist: Mapping) -> str:
    return (f"it differed from the current settings by only {dist['points']} points in {dist['areas']} area(s); a rebuild must differ by at "
            f"least {GEMATRIA_MIN_POINTS} points and change at least {GEMATRIA_MIN_AREAS} different areas (price band, lead, ciphers, sports, volume).")


def profile() -> rebuild_ai.Profile:
    return rebuild_ai.Profile(system=system_text, analyst_system=analyst_text, angles_fn=angles, vet=vet, distance=distance,
                              too_similar=too_similar, ask=ASK, similar_text=similar_text)
