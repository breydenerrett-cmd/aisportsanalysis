"""The member "Gematria" base style: a member's hound that picks by the SAME engine and the SAME active rules as the house
Gematria Hound (``src/hounds/gematria``), on the member's own sports, bets a day, stake and name.

WHAT THE MEMBER CHOOSES AND WHAT THEY DO NOT
--------------------------------------------
The member chooses the name, tagline, colour, badge, sports, most bets a day and stake, like any hound. What decides a pick is
the house's: the margin, the thresholds, the ciphers, the weights and the price band come from ``config/gematria/active.json``'s
rules file, read at pick time by the same ``GematriaRuntime`` the house hound runs. The ONE thing a member may lay over it is a
small set of knobs that only NARROW those rules (``TUNING_KEYS``: price band, how clear the lead must be, which ciphers are read;
owner request 2026-10-28, so a Gematria hound can be fine-tuned and rebuilt like any other: ``interact/gematria_training.py``).
There is no second copy of the logic here, so the two can never drift: this module only (1) rebuilds the house runner's inputs for a
member's game (a point-in-time ``Context`` and the lock board, through ``pack.base``'s own functions), (2) asks the runtime to
weigh the game, and (3) turns a "bet" verdict into the candidate the user engine writes.

THE SPEC (a version-2 spec with ``style: "gematria"``)
------------------------------------------------------
``validate_spec`` hands a raw spec with that style to ``normalize`` below, which returns the spec's fixed parts:

  sports           the member's, from the dog menu
  rules            ONE canonical rule, derived (never typed): moneyline, either side, the stamped rules' price band, 3 books,
                   no conditions. It exists so every reader that walks ``spec["rules"]`` (the kennel feed, the stats, the
                   sports gate) keeps working; the engine never evaluates it as a rule, ``hound_candidates`` of the generic
                   engine returns nothing for this style (user_engine_v2), and the published sentence says what really runs.
  lock_minutes     the rules' own (60), nothing else is accepted
  gematria         ``{rules_version, rules_hash}`` stamped at creation: which rules the hound was made under. It is part of
                   the spec hash. It must name a rules file this program holds, so a made-up stamp is refused.

WHICH RULES A BET USES. The engine weighs under the ACTIVE rules, exactly as the house hound does, and every bet row carries the
``rules_version`` / ``rules_hash`` it was actually made under (and the evidence block, with both sides' matches). When the
house moves to ``rules_v2`` a member hound made under v1 follows it, and its bet rows say so from that day. The creation
stamp stays in the spec as the record of what the member saw when they made it.

PASSES. The engine's own reasons are kept as counts on the engine report (``gematria_no_history``, ``gematria_small_margin``
...). A sport with no facts or no stored results passes with those reasons; nothing is guessed, and a game is never invented.

FORWARD ONLY, PAPER ONLY. A replay is refused (the house hound refuses one too: ``ai_defs.GEMATRIA_FORWARD_ONLY_MESSAGE``). The
preview (``preview``) is a read-only look at today's board and writes nothing. The kill switch ``GEMATRIA_HOUND=off`` stops
member Gematria hounds exactly as it stops the house hound. Nothing here places or suggests a real bet, and a price of -200 or
worse is vetoed by the decision itself and again by the user engine.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

STYLE = "gematria"
STYLE_LABEL = "Gematria"
HOUSE_HOUND_ID = "gematria"
HOUSE_HOUND_NAME = "Gematria Hound"
HOUSE_HOUND_HREF = "hound.html?id=gematria"
CATEGORY = "numerology"
CANONICAL_LABEL = "Gematria"
MARKET = "moneyline"

PASS_PREFIX = "gematria_"
FORWARD_ONLY_CODE = "gematria_forward_only"
OFF_CODE = "gematria_switched_off"

#: Plain, claim-free copy. The one-paragraph explanation the builder shows, and the short line the quiz card carries.
EXPLAINER = (
    "Gematria reads the numbers in a game. For each team it works out what the numbers in names, cities, mascots, the date "
    "and our stored results would say if that team won: letter values, win and loss counts, streaks, days since the last "
    "win. Every time two of those numbers match, that is one piece of evidence. Your hound backs the side with clearly more "
    "matches, on moneylines only, an hour before the start, and passes when the sides are too close or the price is -200 or "
    "worse. Where our stored results are thin it reads the names and the date alone. It uses the same rules as the house "
    "Gematria Hound, so the two never drift apart. It is a "
    "for-fun style: nothing here claims that numbers predict games, and every pick is paper and graded in public.")
QUIZ_LINE = "Reads the numbers in names, dates and streaks. Bets when they line up."

_STAMP_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,24}$")
_STAMP_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def is_gematria(spec: Mapping) -> bool:
    return isinstance(spec, Mapping) and spec.get("style") == STYLE


def enabled(env: Optional[Mapping] = None) -> bool:
    """The kill switch, shared with the house hound: ``GEMATRIA_HOUND=off`` (also 0, false, no) stops both."""
    from src.hounds.gematria import runtime as gem_rt

    return gem_rt.enabled(env)


# ---------------------------------------------------------------------------
# the rules a hound is stamped with
# ---------------------------------------------------------------------------

_rules_cache: dict = {}


def _rules_file(name: Optional[str] = None):
    from src.hounds.gematria import rules as rules_mod

    fname = name or rules_mod.active_file()
    return fname, rules_mod.config_dir() / fname


def load_rules(name: Optional[str] = None):
    """The parsed rules of one file (the active one by default), cached by file modification time."""
    from src.hounds.gematria import rules as rules_mod

    fname, path = _rules_file(name)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return rules_mod.load(fname)           # raises RulesError with the reason
    hit = _rules_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    rules = rules_mod.load(fname)
    _rules_cache[str(path)] = (key, rules)
    return rules


def active_stamp() -> dict:
    """``{rules_version, rules_hash}`` of the rules the house hound runs under today."""
    rules = load_rules()
    return {"rules_version": rules.version, "rules_hash": rules.rules_hash}


def known_rules() -> dict:
    """{(version, hash): Rules} for every rules file on disk (a spec's stamp must be one of them)."""
    from src.hounds.gematria import rules as rules_mod

    out: dict = {}
    folder = rules_mod.config_dir()
    try:
        names = sorted(p.name for p in folder.glob("rules_*.json"))
    except OSError:
        names = []
    for name in names:
        try:
            r = load_rules(name)
        except Exception:  # noqa: BLE001 -- a bad rules file is simply not a known stamp
            continue
        out[(r.version, r.rules_hash)] = r
    return out


def rules_for(stamp: Optional[Mapping]):
    """The Rules a stamp names (the stamped file), or the active ones when the stamp is missing or unknown."""
    if isinstance(stamp, Mapping):
        hit = known_rules().get((stamp.get("rules_version"), stamp.get("rules_hash")))
        if hit is not None:
            return hit
    return load_rules()


# ---------------------------------------------------------------------------
# the member's own knobs (owner request 2026-10-28: "the Gematria hound cannot be coached")
# ---------------------------------------------------------------------------
#
# WHY KNOBS AT ALL. Until 2026-10-28 a member Gematria hound had NO rule of its own: the engine, the ciphers, the margin and the price
# band were all the house's, so there was nothing for Fine-tune or Full rebuild to change, and the one thing members saw (it kept
# backing heavy favourites, "chalk city") could not be fixed. The decision never CHOOSES a side by price, the price only vetoes
# (``gematria.decision``), so a price band that starts at -199 lets every favourite the numbers happen to like straight through.
#
# THE KNOBS (``spec["gematria"]["tuning"]``, every key optional, absent = the house rules exactly):
#   price_min, price_max   the price band the backed side's average price must sit in. It can only NARROW the active rules' band
#                          (-199 to +400 today), never widen it, and never reach -200.
#   min_margin, min_z      how clearly one side must lead (the floor, and in units of the game's own noise). Only raised
#                          above the house value; the house value is also the least it can be.
#   ciphers                which of the four ciphers are read (at least two). A subset of the active rules' ciphers.
# Sports, most bets a day and stake are the spec's own fields, as for any hound. The MARKET (moneyline) and the SIDE (the engine
# picks the side with the larger total) are not knobs: a hound that chose its side or market would be a different style.
#
# WHERE IT LIVES. Inside the existing ``gematria`` stamp, so it is part of the spec hash (a tuned hound is a different rule, with its
# own record) and an untuned hound's hash is byte-for-byte what it was. Applied at pick time over the ACTIVE rules (``tuned_rules``);
# the rules FILE is never edited, and a bet row carries the tuning it was made under.

TUNING_KEY = "tuning"
TUNING_KEYS = ("ciphers", "min_margin", "min_z", "price_max", "price_min")
MIN_CIPHERS = 2
MARGIN_RANGE = (0.5, 10.0)
Z_RANGE = (0.0, 4.0)


def tuning_of(spec: Optional[Mapping]) -> Optional[dict]:
    """The member's tuning on a Gematria spec, or None (none given, or not a Gematria spec)."""
    stamp = spec.get("gematria") if isinstance(spec, Mapping) else None
    tuning = stamp.get(TUNING_KEY) if isinstance(stamp, Mapping) else None
    return dict(tuning) if isinstance(tuning, Mapping) and tuning else None


def tuning_key(tuning: Optional[Mapping]) -> tuple:
    """A hashable form of a tuning (the weigher memoises on it)."""
    if not tuning:
        return ()
    return tuple(sorted((k, tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in tuning.items()))


def tuned_rules(rules, tuning: Optional[Mapping]):
    """``rules`` with the member's knobs laid over them. NARROWING ONLY, whatever the tuning says: the band is clamped inside the
    rules' own band, the margin and z never go under the rules' values, and the ciphers are the rules' own that the member kept (the
    rules' full set when none of them match). The rules object itself is frozen and is never changed; a copy is returned."""
    if not tuning:
        return rules
    d = rules.decision
    lo, hi = d.price_band
    if tuning.get("price_min") is not None:
        lo = max(lo, int(tuning["price_min"]))
    if tuning.get("price_max") is not None:
        hi = min(hi, int(tuning["price_max"]))
    fields = {"price_band": (lo, hi)}
    if tuning.get("min_margin") is not None:
        fields["min_margin"] = max(d.min_margin, float(tuning["min_margin"]))
    if tuning.get("min_z") is not None:
        fields["min_z"] = max(d.min_z, float(tuning["min_z"]))
    out = {"decision": dataclasses.replace(d, **fields)}
    kept = tuple(c for c in rules.ciphers if c in (tuning.get("ciphers") or ()))
    if kept and kept != tuple(rules.ciphers):
        out["ciphers"] = kept
        out["cipher_weights"] = {c: rules.cipher_weights[c] for c in kept}
    return dataclasses.replace(rules, **out)


def _number(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return round(float(value), 2) if lo <= float(value) <= hi else None


def normalize_tuning(raw: Any, rules, errors: dict) -> Optional[dict]:
    """The canonical tuning (only the keys given, typed, ciphers in cipher order), or None when there is none. Reasons go in
    ``errors['gematria']``. ``rules`` are the stamped rules: a band no price can sit in, or a cipher those rules do not read, is refused."""
    from src.hounds import user_spec
    from src.hounds.pack import base
    from src.research import gematria as cipher_book

    if raw in (None, {}):
        return None
    if not isinstance(raw, Mapping):
        errors["gematria"] = "tuning must be an object"
        return None
    unknown = sorted(str(k)[:30] for k in raw if k not in TUNING_KEYS)
    if unknown:
        errors["gematria"] = f"tuning has no knob called {', '.join(unknown)}; the knobs are {', '.join(TUNING_KEYS)}"
        return None
    out: dict = {}
    for key in ("price_min", "price_max"):
        if key not in raw:
            continue
        v = raw[key]
        if not user_spec._is_price(v) or not (base.PRICE_MIN <= v <= base.PRICE_MAX):      # noqa: SLF001 -- the menu's own price check
            errors["gematria"] = f"{key} must be an American price from {base.PRICE_MIN} to {base.PRICE_MAX} (never -200 or worse)"
            return None
        out[key] = int(v)
    if "min_margin" in raw:
        v = _number(raw["min_margin"], *MARGIN_RANGE)
        if v is None:
            errors["gematria"] = f"min_margin must be a number from {MARGIN_RANGE[0]:g} to {MARGIN_RANGE[1]:g}"
            return None
        out["min_margin"] = v
    if "min_z" in raw:
        v = _number(raw["min_z"], *Z_RANGE)
        if v is None:
            errors["gematria"] = f"min_z must be a number from {Z_RANGE[0]:g} to {Z_RANGE[1]:g}"
            return None
        out["min_z"] = v
    if "ciphers" in raw:
        given = raw["ciphers"]
        ok = isinstance(given, (list, tuple)) and all(isinstance(c, str) for c in given)
        wanted = {c for c in given} if ok else set()
        if not ok or not wanted <= set(cipher_book.CIPHERS) or not wanted <= set(rules.ciphers) or len(wanted) < MIN_CIPHERS:
            errors["gematria"] = (f"ciphers must name at least {MIN_CIPHERS} of {', '.join(rules.ciphers)}")
            return None
        out["ciphers"] = [c for c in cipher_book.CIPHERS if c in wanted]
    if not out:
        return None
    lo, hi = tuned_rules(rules, out).decision.price_band
    if lo > hi:
        errors["gematria"] = "that price band leaves no price a bet could be at"
        return None
    return {k: out[k] for k in sorted(out)}


# ---------------------------------------------------------------------------
# validation (called by user_spec._validate_v2)
# ---------------------------------------------------------------------------

def canonical_rule(sports: list, rules, tuning: Optional[Mapping] = None) -> dict:
    """The one rule a Gematria spec carries. Derived from the stamped rules (and the member's own price band, see ``tuned_rules``),
    never typed."""
    from src.hounds.pack import base

    lo, hi = tuned_rules(rules, tuning).decision.price_band
    return {"label": CANONICAL_LABEL, "sports": list(sports), "markets": [MARKET], "side": "either",
            "price_min": int(max(base.PRICE_MIN, lo)), "price_max": int(min(base.PRICE_MAX, hi)),
            "line_min": None, "line_max": None, "min_books": int(base.MIN_BOOKS), "when": None}


def normalize(raw: Mapping, errors: dict) -> Optional[dict]:
    """The fixed parts of a Gematria spec, or None with the reasons in ``errors``.

    Returns ``{sports, stamp, rules, rule, lock_minutes}``. ``raw["rules"]`` is accepted on input (so a spec can be POSTed back
    as read) but only to be REPLACED by the canonical rule; a rule carrying conditions or a market other than the
    moneyline is refused, because the engine would not read them and a published rule must be what ran."""
    from src.hounds import user_spec

    stamp_raw = raw.get("gematria")
    stamp = None
    tuning_raw = None
    if stamp_raw is None:
        stamp = active_stamp()
    elif (isinstance(stamp_raw, Mapping) and {"rules_version", "rules_hash"} <= set(stamp_raw) <= {"rules_version", "rules_hash", TUNING_KEY}
          and isinstance(stamp_raw["rules_version"], str) and _STAMP_VERSION_RE.match(stamp_raw["rules_version"])
          and isinstance(stamp_raw["rules_hash"], str) and _STAMP_HASH_RE.match(stamp_raw["rules_hash"])
          and (stamp_raw["rules_version"], stamp_raw["rules_hash"]) in known_rules()):
        stamp = {"rules_version": stamp_raw["rules_version"], "rules_hash": stamp_raw["rules_hash"]}
        tuning_raw = stamp_raw.get(TUNING_KEY)
    else:
        errors["gematria"] = "must name a Gematria rules version this program holds"
    rules_raw = raw.get("rules")
    given_sports: list = []
    if rules_raw not in (None, []):
        if not isinstance(rules_raw, (list, tuple)) or len(rules_raw) != 1 or not isinstance(rules_raw[0], Mapping):
            errors["rules"] = "the Gematria style has one fixed rule; leave it as it is"
        else:
            one = rules_raw[0]
            if one.get("when"):
                errors["rules"] = "the Gematria style takes no extra conditions; its rule is fixed"
            elif any(m != MARKET for m in (one.get("markets") or [MARKET])):
                errors["rules"] = "the Gematria style bets moneylines only"
            else:
                given_sports = one.get("sports") or []
    sports = user_spec.normalize_sports(raw["sports"] if raw.get("sports") is not None else given_sports)
    if sports is None:
        errors["sports"] = user_spec.sports_error_text()
    elif raw.get("sports") is not None and given_sports and user_spec.normalize_sports(given_sports) != sports:
        errors["sports"] = "the Gematria rule covers the hound's sports; change the sports, not the rule"
    markets = raw.get("markets")
    if markets is not None and list(markets if isinstance(markets, (list, tuple)) else [markets]) != [MARKET]:
        errors["markets"] = "the Gematria style bets moneylines only"
    rank = raw.get("rank_by")
    if rank is not None and rank != "earliest_lock":
        errors["rank_by"] = "the Gematria style takes the earliest games first"
    if errors.get("gematria") or errors.get("rules") or sports is None or stamp is None:
        return None
    rules = rules_for(stamp)
    tuning = normalize_tuning(tuning_raw, rules, errors)
    if errors.get("gematria"):
        return None
    if tuning:
        stamp[TUNING_KEY] = tuning
    lock = int(rules.decision.lock_minutes)
    given_lock = raw.get("lock_minutes")
    if given_lock is not None and given_lock != lock:
        errors["lock_minutes"] = f"the Gematria style weighs each game {lock} minutes before the start"
        return None
    rule = canonical_rule(sports, rules, tuning)
    return {"sports": sports, "stamp": stamp, "rules": [rule], "rule": rule, "lock_minutes": lock}


# ---------------------------------------------------------------------------
# the published rule
# ---------------------------------------------------------------------------

def _price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def rule_sentence(spec: Mapping) -> str:
    """The Gematria style's rule in plain English, from the stamped rules and the spec's sports. Pure."""
    from src.hounds import user_spec

    house = rules_for(spec.get("gematria"))
    tuning = tuning_of(spec)
    rules = tuned_rules(house, tuning)
    d = rules.decision
    lo, hi = spec["rules"][0]["price_min"], spec["rules"][0]["price_max"]
    sports = user_spec.sports_phrase(spec["rules"][0]["sports"])
    if rules.static_fallback:
        # rules v2: thin counts are read statically, and the lead is judged against the game's own noise
        lead = (f"It backs the side with the larger total only if it leads by at least {d.min_margin:g} and by clearly more than the "
                "game's own noise (a game with many coincidences needs a bigger lead), and the side's average price is between "
                f"{_price(lo)} and {_price(hi)} (never -200 or worse); otherwise it passes. Where our stored results are thin, or a "
                "sport has none, it reads the names, the date and founding dates alone.")
    else:
        lead = (f"It backs the side with the larger total only if it leads by at least {d.min_margin:g}, both sides had enough "
                f"stored results to count, and the side's average price is between {_price(lo)} and {_price(hi)} "
                "(never -200 or worse); otherwise it passes.")
    return (
        f"{CANONICAL_LABEL}: {sports} moneylines. For each team it works out what the numbers would say if that team won "
        "(the cipher values of names, cities and mascots, the number of the date, how far the game is from a founding "
        "date, and counts from our stored results such as records, streaks and days since a win); each time two of those "
        f"numbers match is one piece of evidence. {lead} {tuning_sentence(house, tuning)}"
        "makes no claim that numbers predict games.")


def tuning_sentence(house, tuning: Optional[Mapping]) -> str:
    """The closing clause of the published rule: the house rules it runs, and, when the member tuned it, exactly which settings are
    its own. Ends with a space so the caller can continue the sentence."""
    if not tuning:
        return f"It runs the house Gematria Hound's rules ({house.version}) and "
    own = []
    d = house.decision
    if "min_margin" in tuning or "min_z" in tuning:
        own.append("how clearly one side must lead")
    if "price_min" in tuning or "price_max" in tuning:
        own.append("the price band")
    if "ciphers" in tuning:
        own.append("the ciphers it reads (" + ", ".join(tuning["ciphers"]) + ")")
    return (f"It runs the house Gematria Hound's rules ({house.version}) with its own settings for " + _and_list(own) + ", "
            f"which only narrow what the house rules allow (the house rules lead by {d.min_margin:g}), and ")


def _and_list(items: list) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def knob_lines(spec: Mapping) -> dict:
    """The knobs of a Gematria spec as the plain words a card and a diff show: ``{"Sports": ..., "Price band": ..., ...}``. Pure."""
    house = rules_for(spec.get("gematria"))
    rules = tuned_rules(house, tuning_of(spec))
    d = rules.decision
    rule = spec["rules"][0]
    lo, hi = rule["price_min"], rule["price_max"]
    from src.hounds import user_spec
    return {"Sports": user_spec.sports_phrase(rule["sports"]),
            "Price band": f"{_price(lo)} to {_price(hi)} (never -200 or worse)",
            "Lead needed": f"at least {d.min_margin:g}" + (f" and {d.min_z:g} times the game's noise" if d.margin_mode == "noise_scaled" and d.min_z else ""),
            "Ciphers read": ", ".join(rules.ciphers)}


def knob_diff(old: Mapping, new: Mapping) -> list:
    """``[{what, before, after}]`` for the knobs that differ between two Gematria specs (``english.render.diff_specs`` uses it)."""
    a, b = knob_lines(old), knob_lines(new)
    return [{"what": k, "before": a[k], "after": b[k]} for k in a if a[k] != b[k]]


def fixed_text(fixed: Mapping) -> str:
    """The builder's one line of what the style fixes (the page shows it as is): lock, market, price band, rules version."""
    parts = []
    if fixed.get("lock_minutes"):
        parts.append(f"it weighs each game {fixed['lock_minutes']} minutes before the start")
    parts.append("on moneylines only")
    band = fixed.get("price_band")
    if band:
        parts.append(f"at an average price between {_price(band[0])} and {_price(band[1])} (never -200 or worse)")
    if fixed.get("rules_version"):
        parts.append(f"under the house hound's rules {fixed['rules_version']}")
    tail = ". It passes when the data is thin." if fixed.get("rules_version") in (None, "", "v1") else ". Where stored results are thin it reads names and dates alone."
    return "Fixed by the style: " + ", ".join(parts) + tail


def global_sentences(spec: Mapping) -> list:
    bets, stake = spec["max_bets_per_day"], spec["stake_units"]
    return [
        f"{spec['lock_minutes']} minutes before the start it weighs each game once, from the board as it stood then and "
        "the results stored by then (nothing newer). Unleash weighs the day's open games at once, on the board standing then.",
        f"At most {bets} {'bet' if bets == 1 else 'bets'} a day: the strongest cases when you Unleash, the earliest games first after that.",
        f"Each bet is {stake:g} paper unit{'' if stake == 1 else 's'}, graded at the average price.",
    ]


# ---------------------------------------------------------------------------
# weighing a member's games with the house runtime
# ---------------------------------------------------------------------------

def _row_for(row: Mapping, observed: datetime) -> dict:
    return {**row, "market": "h2h", "observed_utc": observed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def make_runtime():
    """The house runtime, ledger-less: the same rules, facts and history source the house hound runs, and no decision log (a
    member's bet row carries the evidence). Tests replace this to run on synthetic facts and results."""
    from src.hounds.gematria import runtime as gem_rt

    return gem_rt.GematriaRuntime(ledger=None)


class Weigher:
    """One engine pass's view of the games: the house runner's inputs for each game, built once, weighed once.

    The boards the user engine holds (``GameBoards``) are turned back into the quotes ``pack.base`` reads, so the
    ``Context`` and the lock board come from ``pack.base.build_context`` / ``lock_board`` themselves: the same functions, on
    the same captured rows, as the house runner. ``runtime`` is injectable for tests; production builds the house
    ``GematriaRuntime`` with no ledger (a member's pass writes no decision log, the bet row carries the evidence)."""

    def __init__(self, games: Mapping, *, runtime=None, root: Optional[str] = None,
                 load_results: Optional[Callable] = None):
        self.games = games
        self._runtime = runtime
        self._root = root
        self._load_results = load_results
        self._stores = None
        self._loaded: set = set()
        self._memo: dict = {}
        self._tuned: dict = {}
        self._prepared: dict = {}

    @property
    def runtime(self):
        if self._runtime is None:
            self._runtime = make_runtime()
        return self._runtime

    def runtime_for(self, tuning: Optional[Mapping] = None):
        """The runtime to weigh with: the house's, or, for a member who tuned their hound, a shallow copy whose rules carry the member's
        knobs (``tuned_rules``: narrowing only). The copy shares the facts, the history source and the (absent) ledger, so it costs
        nothing, and the house runtime itself is never touched."""
        if not tuning:
            return self.runtime
        key = tuning_key(tuning)
        got = self._tuned.get(key)
        if got is None:
            got = copy.copy(self.runtime)
            got.rules = tuned_rules(self.runtime.rules, tuning)
            got.tuning = dict(tuning)                  # ``_candidate`` stamps it on the bet row
            self._tuned[key] = got
        return got

    def stores(self):
        from src.hounds.pack import base

        if self._stores is None:
            st = base.Stores(sports=tuple(sorted({g.sport.lower() for g in self.games.values()})) or base.DEFAULT_SPORTS)
            for eid, g in self.games.items():
                quotes = []
                for observed, rows in (g.captures.get("moneyline") or {}).items():
                    for row in rows:
                        q = base.quote_from_row(_row_for(row, observed))
                        if q is not None:
                            quotes.append(q)
                if not quotes:
                    continue
                st.quotes_by_event[eid] = quotes
                st.events[eid] = {"sport": g.sport.lower(), "away_name": g.away_team, "home_name": g.home_team,
                                  "commence": sorted(g._commence_by_obs.items()),
                                  **({"league_title": g.league_title} if g.league_title else {})}
            self._stores = st
        return self._stores

    def _ensure_results(self, sport: str) -> None:
        from src.hounds.pack import base

        if sport not in ("mlb", "nfl") or sport in self._loaded:
            return
        self._loaded.add(sport)
        loader = self._load_results or (lambda st, s: base.load_result_stores(st, root=self._root, mlb=(s == "mlb"),
                                                                              nfl=(s == "nfl")))
        loader(self.stores(), sport)

    def context(self, event_id: str):
        from src.hounds.pack import base

        game = self.games.get(event_id)
        if game is None:
            return None
        self._ensure_results(game.sport.lower())
        return base.build_context(self.stores(), event_id)

    def weigh(self, event_id: str, *, as_of: Optional[datetime] = None, tuning: Optional[Mapping] = None):
        """``(ctx, board, Weighed)`` for a game, or None when it has no usable board or start. ``as_of`` is only the
        preview's: a game not yet at its lock is read on the board as it stands (the lock board does not exist yet). ``tuning`` is the
        member's knobs (``tuning_of(spec)``): one pass weighs different members' hounds, each under its own."""
        from src.hounds.pack import base

        runtime = self.runtime_for(tuning)
        key = (event_id, as_of, tuning_key(tuning))
        if as_of is None and key in self._memo:          # a preview's moving clock is never memoised (it would only grow)
            return self._memo[key]
        ctx = self.context(event_id)
        out = None
        if ctx is not None:
            if as_of is None or as_of >= ctx.lock:
                board = base.lock_board(self.stores(), ctx)
            else:
                board = base.build_board(self.stores().quotes_by_event.get(event_id) or [], at=as_of, start=ctx.start,
                                         sport=ctx.sport)
            ahead = as_of is not None and as_of < ctx.lock
            # an ahead read is cut at its own instant for the history too (``GematriaRuntime.inputs``), not only for the board
            prepared = None
            if as_of is None and hasattr(runtime, "prepare"):
                # the expensive half is shared by every tuning that reads the same ciphers (a rehearsal weighs one game under many variants)
                pkey = (event_id, tuple(runtime.rules.ciphers))
                prepared = self._prepared.get(pkey)
                if prepared is None:
                    prepared = self._prepared[pkey] = runtime.prepare(ctx)
            if prepared is not None:
                out = (ctx, board, runtime.weigh(ctx, board, prepared=prepared))
            else:
                out = (ctx, board, runtime.weigh(ctx, board, known_at=as_of) if ahead else runtime.weigh(ctx, board))
        if as_of is None:
            self._memo[key] = out
        return out


def _candidate(game, ctx, board, weighed, runtime) -> Optional[dict]:
    """The engine candidate for a "bet" verdict, with the evidence stamped for the bet row."""
    from src.hounds import user_engine as E
    from src.hounds.pack import base

    v = weighed.verdict
    info = base.side_info(board, MARKET, v.side)
    if info is None:
        return None
    price, best = int(info["price_average"]), int(info["price_best"])
    found = game.board_at(MARKET, ctx.lock)
    observed = found[0] if found else ctx.lock
    selection = E._selection_text(game, MARKET, v.side, None)
    n_books = int(info["book_count"])
    rules = runtime.rules
    reason = (f"Gematria: {v.reason}. It backed {selection} at the board average of {E._fmt_price(price)} across {n_books} "
              f"books; the best single price was {E._fmt_price(best)} at {info['book']}. Rules {rules.version}.")
    extra = {"gematria": weighed.block, "rules_version": rules.version, "rules_hash": rules.rules_hash,
             "confidence": v.confidence, "forward_only": True, "style": STYLE, "reason": reason}
    tuning = getattr(runtime, "tuning", None)
    if tuning:
        extra["tuning"] = dict(tuning)             # the member's own settings the bet was made under: the record can tell tuned from house
    return {"side": v.side, "line": None, "price": price, "best_price": best, "best_book": info["book"],
            "n_books": n_books, "board_observed_utc": E._iso(observed),
            "board_age_minutes": round((ctx.lock - observed).total_seconds() / 60.0, 1), "selection": selection,
            "player": None, "rule_index": 0, "row_extra": extra}


def hound_candidates(hound: Mapping, spec: Mapping, games: Mapping, date: str, *, mode: str,
                     clock: Callable[[], datetime], seen_ids: set, skipped, considered: dict,
                     weigher: Weigher, env: Optional[Mapping] = None, ahead: bool = False) -> list:
    """The candidates of one member Gematria hound on one slate date, in the shape ``user_engine.run`` ranks and writes:
    ``[(sortkey, lock_utc, event_id, market, game, commence, cand, bet_id)]``.

    ``ahead`` is Unleash (``user_engine.run(place_ahead=True)``). Until 2026-10-22 this function ignored it: every game still
    more than ``lock_minutes`` from its start was skipped as ``not_locked_yet``, so a member who tapped Unleash at noon had
    the whole evening slate unevaluated and read "Checked 60 games ... rule not met". With ``ahead`` a game not yet at its lock is
    weighed NOW, on the newest board at or before now and on results stored by now (``Weigher.weigh(as_of=now)``: nothing later
    exists), exactly as the preview reads it, and the bet says it was placed ahead. Under rules v2 the day's candidates are
    ranked by their z (the margin in units of the game's own noise), best first, so the daily limit keeps the strongest cases
    rather than the earliest games; the lock-time runner (one game at a time) cannot rank, and still goes earliest first."""
    from src.hounds import user_engine as E

    if not enabled(env):
        skipped[OFF_CODE] += 1
        return []
    # The house hound is forward only; so is a member's, with ONE exception: the training screen's REHEARSAL (owner request 2026-10-28),
    # which the drill marks on the hound row it hands the engine (``rehearsal``). A rehearsal is hindsight, written to a throwaway
    # ledger and never counted; every game is weighed once, at its own lock, on the board and the results stored by then, exactly as a
    # live pass would have, so it is as point-in-time as the engine itself. The public Backtest still refuses a Gematria hound.
    rehearsal = mode == "replay" and hound.get("rehearsal") is True
    if mode != "live" and not rehearsal:
        skipped[FORWARD_ONLY_CODE] += 1
        return []
    tuning = tuning_of(spec)
    runtime = weigher.runtime_for(tuning) if tuning else weigher.runtime
    tuned = {"tuning": tuning} if tuning else {}          # an untuned pass calls the weigher exactly as it always has
    created = E._utc(hound.get("created_at"))
    out = []
    for event_id, game in sorted(games.items()):
        if game.sport not in spec["sports"] or game.commence is None:
            continue
        bet_id = E.bet_id_for(hound["id"], event_id, MARKET)
        if bet_id in seen_ids:
            continue
        if rehearsal:
            got = weigher.weigh(event_id, **tuned)
            if got is None:
                skipped[PASS_PREFIX + "no_context"] += 1
                continue
            ctx, board, weighed = got
            cand = _candidate(game, ctx, board, weighed, runtime) if weighed.verdict.is_bet else None
            if cand is None:
                skipped[PASS_PREFIX + (weighed.verdict.code if not weighed.verdict.is_bet else "no_board")] += 1
                continue
            out.append(((ctx.lock, event_id, 0), ctx.lock, event_id, MARKET, game, ctx.start, cand, bet_id))
            continue
        now = clock()
        lock_pre = game.commence - timedelta(minutes=spec["lock_minutes"])
        if now >= game.commence:
            skipped["game_started"] += 1
            continue
        if now < lock_pre and not ahead:
            skipped["not_locked_yet"] += 1
            continue
        if created is not None and created > lock_pre and not ahead:
            skipped["hound_created_after_lock"] += 1
            continue
        considered.setdefault(hound["id"], set()).add(event_id)
        # ahead: a game not at its lock yet, or one whose lock passed before this hound existed, is read on the board standing now
        as_of = now if (ahead and (now < lock_pre or (created is not None and created > lock_pre))) else None
        got = weigher.weigh(event_id, as_of=as_of, **tuned)
        if got is None:
            skipped[PASS_PREFIX + "no_context"] += 1
            continue
        ctx, board, weighed = got
        if now >= ctx.start:
            skipped["game_started"] += 1
            continue
        if now < ctx.lock and not ahead:
            skipped["not_locked_yet"] += 1
            continue
        if not weighed.verdict.is_bet:
            skipped[PASS_PREFIX + weighed.verdict.code] += 1
            continue
        cand = _candidate(game, ctx, board, weighed, runtime)
        if cand is None:
            skipped[PASS_PREFIX + "no_board"] += 1
            continue
        if as_of is not None:
            cand["row_extra"]["placed_ahead"] = True        # weighed before its lock (or after a lock the hound missed): said on the row
        ranked = runtime.rules.static_fallback and ahead
        key = (-weighed.verdict.z, ctx.lock, event_id, 0) if ranked else (ctx.lock, event_id, 0)
        # Which ORDER chose this bet under the daily limit, on the row (red team 2026-10-22). The order is code, not the rules file, so
        # the rules_hash alone cannot say it: on 2026-10-20 and 10-22 an Unleash's top 5 by z shared only 2 and 3 games with the 5 the
        # lock-time runner takes earliest first. Same rules, a different selection: the record must be able to tell them apart.
        # Only a ranked bet carries it (absent = earliest first), so a lock-time row is byte-for-byte what it was.
        if ranked:
            cand["row_extra"]["day_order"] = "z"
        out.append((key, ctx.lock, event_id, MARKET, game, ctx.start, cand, bet_id))
    return out


def preview(spec: Mapping, games: Mapping, date: str, now: datetime, *, weigher: Optional[Weigher] = None) -> dict:
    """What this member Gematria spec would bet on this slate, from the boards as they stand at ``now``. Writes nothing.
    Same result shape as ``user_engine_v2.preview`` so the builder's preview panel draws it unchanged."""
    from src.hounds import user_engine as E

    weigher = weigher or Weigher(games)
    tuning = tuning_of(spec)
    runtime = weigher.runtime_for(tuning) if tuning else weigher.runtime
    tuned = {"tuning": tuning} if tuning else {}
    skipped: Counter = Counter()
    considered: set = set()
    picks = []
    for event_id, game in sorted(games.items()):
        if game.sport not in spec["sports"] or game.commence is None:
            continue
        if not enabled():
            skipped[OFF_CODE] += 1
            continue
        considered.add(event_id)
        got = weigher.weigh(event_id, as_of=now, **tuned)
        if got is None:
            skipped[PASS_PREFIX + "no_context"] += 1
            continue
        ctx, board, weighed = got
        if weighed.verdict.is_bet:
            cand = _candidate(game, ctx, board, weighed, runtime)
            if cand is not None:
                picks.append((ctx.lock, event_id, game, ctx, cand, weighed.verdict.z))
                continue
        skipped[PASS_PREFIX + weighed.verdict.code] += 1
    if runtime.rules.static_fallback:
        picks.sort(key=lambda p: (-p[5], p[0], p[1]))
    else:
        picks.sort(key=lambda p: (p[0], p[1]))
    out = []
    for position, (lock, event_id, game, ctx, cand, _z) in enumerate(picks):
        out.append({
            "event_id": event_id, "sport": game.sport, "market": MARKET, "away_team": game.away_team,
            "home_team": game.home_team, "start_utc": E._iso(ctx.start), "lock_utc": E._iso(lock), "locked": now >= lock,
            "selection": cand["selection"], "side": cand["side"], "line": None, "player": None, "price": cand["price"],
            "best_price": cand["best_price"], "n_books": cand["n_books"], "rule_index": 0,
            "would_bet": position < spec["max_bets_per_day"], "rank": position + 1})
    return {"date": date, "games_considered": len(considered), "games_fit": len(out), "qualifying": len(out),
            "would_bet": min(len(out), spec["max_bets_per_day"]), "max_bets_per_day": spec["max_bets_per_day"],
            "picks": out, "skipped": dict(skipped)}


# ---------------------------------------------------------------------------
# the Evidence fold for a member's hound
# ---------------------------------------------------------------------------

MAX_PICKS = 40


def picks_for(hound_id: str, *, ledger: Optional[str] = None, limit: int = MAX_PICKS) -> dict:
    """The same payload as ``gematria.view.picks_for`` (what ``web/js/hounds-gematria.js`` reads), from the member ledger.

    Streams the ledger and parses only lines naming this hound, so a big shared ledger is never held whole."""
    from src.hounds import NOT_ADVICE, PAPER_ONLY, user_engine, user_settle
    from src.hounds.gematria import EXPERIMENTAL_LINE

    path = Path(user_engine.ledger_path(ledger))
    needle = f'"{hound_id}"'
    bets, grades = [], {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if needle not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict) or r.get("hound_id") != hound_id:
                    continue
                if r.get("kind") == user_engine.KIND_BET and isinstance(r.get("gematria"), dict):
                    bets.append(r)
                elif r.get("kind") == user_settle.KIND_GRADED:
                    grades[r.get("bet_id")] = r
    bets.sort(key=lambda r: (str(r.get("commence_time") or ""), str(r.get("event_id") or "")), reverse=True)
    picks = []
    for r in bets[:limit]:
        g = r["gematria"]
        graded = grades.get(r.get("bet_id"))
        picks.append({
            "event_id": r.get("event_id"), "date": r.get("slate_date"), "sport": r.get("sport"),
            "start_utc": r.get("commence_time"), "away": r.get("away_team"), "home": r.get("home_team"),
            "selection": r.get("selection"), "side": r.get("side"), "price": r.get("price_average", r.get("price")),
            "result": graded.get("result") if graded else None,
            "rules_version": g.get("rules_version") or r.get("rules_version"),
            "hound_version": g.get("hound_version"),
            "scores": g.get("scores"), "margin": g.get("margin"), "threshold": g.get("threshold"),
            "comparisons": g.get("comparisons"), "search_space": g.get("search_space"), "matches": g.get("matches"),
            "history": g.get("history"), "evidence": g.get("evidence"),
        })
    return {"hound_id": hound_id, "started": bool(bets), "picks": picks, "copy": EXPERIMENTAL_LINE,
            "paper_only": PAPER_ONLY, "not_advice": NOT_ADVICE}


def is_member_gematria_hound(hound_id: str) -> bool:
    """True for a stored member hound (any version) whose spec has the Gematria style. A missing database answers False."""
    if not isinstance(hound_id, str) or not hound_id:
        return False
    try:
        from src.hounds import user_defs, user_store

        if not user_defs.db_exists():
            return False
        hound = user_store.get_hound(hound_id)
    except Exception:  # noqa: BLE001 -- an unreadable store is "not a member hound", never a 500 on a public route
        return False
    return bool(hound) and is_gematria(hound.get("spec") or {})
