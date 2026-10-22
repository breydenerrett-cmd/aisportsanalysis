"""A user-built hound: the fixed menu, strict validation, and the published rule.

WHY A FIXED MENU AND NOT FREE TEXT
----------------------------------
A hound is a PAPER strategy that races in public. Whatever its builder wrote has to be
(a) something the engine can execute exactly, and (b) something a stranger can read and trust
is what ran. Free text fails both, so a spec is a handful of choices from a menu this module
owns (`menu()` is also what the web form is generated from). A later step may let a model fill
the same fields from a sentence; the model would produce a dict that goes through
`validate_spec` like any form post, so nothing it writes can reach the engine unchecked.

THE RULE TEXT IS GENERATED, NEVER WRITTEN
-----------------------------------------
`rule_text(spec)` is a pure function of the validated spec. The published rule is therefore
always exactly what the engine does: there is no second place for the two to drift apart.

THE -200 CAP IS NOT A SETTING
-----------------------------
Owner ruling (2026-09-20, restated 2026-09-22): no selection at -200 or worse, ever, on any
public surface. `MAX_FAVOURITE_PRICE` is the one place that number lives. `validate_spec`
refuses a price band that reaches it, and the engine re-checks every selection against it
anyway (defence in depth: a hand-edited store row still cannot make a -250 bet).

SPECS ARE IMMUTABLE
-------------------
`spec_hash` covers every rule field. A hound's record belongs to the exact rule that produced
it, so changing a rule means a NEW hound version (see user_store.create_version), never an edit.

PAPER ONLY
----------
Nothing here places or suggests a real bet. Every public sentence says so (`NOT_ADVICE`).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.core import odds as odds_math
from src.sports import catalog as sports_catalog

SPEC_VERSION = 1
# The composable rule language (src/hounds/user_rules.py): several rules, each with AND/OR condition
# groups, player props, a stake and a ranking rule. Version-1 specs stay valid and run exactly as
# before; `upgrade_v1` turns one into a version-2 draft when its owner edits it.
SPEC_VERSION_V2 = 2

NOT_ADVICE = ("Paper only. These are simulated picks from a rule, not betting advice and not a "
              "suggestion to place any real bet.")

# Owner ruling 2026-09-20 / 2026-09-22: nothing at -200 or worse, on any public card.
MAX_FAVOURITE_PRICE = -200          # a price at or beyond this is refused
SHORTEST_ALLOWED_PRICE = -199       # the shortest price any band may start from
LONGEST_ALLOWED_PRICE = 1000        # a sanity ceiling, not a recommendation
PRICE_PRESETS_SHORT = (-190, -180, -170, -160, -150, -140, -130, -120, -110, 100, 110, 120, 150)
PRICE_PRESETS_LONG = (-110, 100, 110, 120, 130, 150, 175, 200, 250, 300, 400, 500, 1000)

NAME_MIN, NAME_MAX = 3, 24
TAGLINE_MAX = 80
MIN_BOOKS_RANGE = (1, 10)
MAX_BETS_RANGE = (1, 5)
LOCK_CHOICES = (60, 120, 180)
# Owner decision 2026-10-20: a PAID account runs up to five dogs; a FREE account (access.py, TWO LEVELS,
# "member") keeps one. The free count is every dog that has not been retired or buried (running or benched), so a
# benched dog cannot be used to hold a second slot; taking a dog out back frees its slot. Nothing is ever taken from a free account that
# already has more: see docs/support/FREE_MEMBERS.md (GRANDFATHERING).
MAX_RUNNING_PER_ACCOUNT = 5
FREE_MAX_ACTIVE_PER_ACCOUNT = 1

# The sports a dog may bet. Until 2026-10-19 this was the hard-coded pair ("MLB", "NFL"); it is now the
# catalog's dog-menu families (config/sports_catalog.json): MLB and NFL first, then every other family a
# member dog can be graded on. LEGACY_SPORTS is the old pair, still the DEFAULT wherever a rule is built
# without an explicit choice (the quiz): a dog never starts betting a sport nobody picked for it.
LEGACY_SPORTS = ("MLB", "NFL")
SPORTS = sports_catalog.dog_families()
ANY = sports_catalog.ANY           # "every sport on the menu"; validate_spec writes the explicit list
MARKETS = ("moneyline", "spread", "total")

SIDE_RULES = (
    "favourite", "underdog", "home", "away", "over", "under",
    "market_moved_toward", "market_moved_away",
)

SPORT_LABELS = {code: sports_catalog.label(code) for code in sports_catalog.family_codes()}
MARKET_LABELS = {"moneyline": "Moneyline", "spread": "Spread / run line", "total": "Game total"}
SIDE_LABELS = {
    "favourite": "The favourite",
    "underdog": "The underdog",
    "home": "The home side",
    "away": "The away side",
    "over": "The over",
    "under": "The under",
    "market_moved_toward": "The side the market moved toward since our first capture",
    "market_moved_away": "The side the market moved away from since our first capture",
}
# Which markets each side rule can speak about. over/under only mean something on a total.
SIDE_MARKETS = {
    "favourite": ("moneyline", "spread"),
    "underdog": ("moneyline", "spread"),
    "home": ("moneyline", "spread"),
    "away": ("moneyline", "spread"),
    "over": ("total",),
    "under": ("total",),
    "market_moved_toward": MARKETS,
    "market_moved_away": MARKETS,
}

RULE_FIELDS = ("sports", "markets", "side_rule", "price_min", "price_max", "min_books",
               "max_bets_per_day", "lock_minutes")
SPEC_FIELDS = ("name", "tagline") + RULE_FIELDS


class SpecError(ValueError):
    """A spec the menu refuses. `errors` is {field: message}, every problem at once."""

    def __init__(self, errors: Mapping[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.errors.items()))


# ---------------------------------------------------------------------------
# text filters
# ---------------------------------------------------------------------------

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a",
                       "$": "s", "!": "i"})

# Substrings unambiguous enough to match inside a squashed word without catching ordinary words.
_BLOCK_SUBSTRINGS = (
    "fuck", "shit", "cunt", "nigg", "faggot", "retard", "nazi", "hitler", "whore", "slut",
    "bitch", "rapist", "bastard", "wank", "dickhead", "asshole", "kike", "chink",
    "tranny", "cocksuck", "motherf",
)
# Short words that appear inside innocent ones ("class", "title"): whole-word match only.
_BLOCK_WORDS = frozenset({"ass", "dick", "cock", "fag", "rape", "sex", "porn", "tit", "tits",
                          "piss", "damn", "crap", "coon", "gook", "spic", "paki", "dyke", "homo"})
# Names that would pass as someone else's: books, leagues, the house.
_RESERVED_SUBSTRINGS = (
    "draftkings", "fanduel", "betmgm", "caesars", "espn", "bovada", "pointsbet", "betrivers",
    "fanatics", "prizepicks", "linehound", "bet365", "hardrock", "barstool",
)
_RESERVED_WORDS = frozenset({"mlb", "nfl", "nba", "nhl", "ufc", "official", "admin", "house",
                             "moderator", "support", "staff", "system"})

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-]*[A-Za-z0-9]$")
_TAGLINE_OK_RE = re.compile(r"^[A-Za-z0-9 .,'!?&()/+:%\-]*$")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _fold(text: str) -> str:
    """Lowercase ASCII-ish, leetspeak undone, no separators: 'F u-c k' -> 'fuck'."""
    return re.sub(r"[^a-z]", "", _ascii(text).lower().translate(_LEET))


def _words(text: str) -> list:
    return re.findall(r"[a-z]+", _ascii(text).lower().translate(_LEET))


def _extra_blocklist() -> tuple:
    """Optional owner additions: config/hounds_blocklist.txt, one term per line."""
    try:
        from src import paths
        path = Path(paths.repo_root()) / "config" / "hounds_blocklist.txt"
        if path.exists():
            return tuple(t for t in (ln.strip().lower() for ln in
                                     path.read_text(encoding="utf-8").splitlines())
                         if t and not t.startswith("#"))
    except Exception:  # noqa: BLE001 -- a missing optional file must never break validation
        pass
    return ()


def text_problem(text: str) -> Optional[str]:
    """Why this text may not appear on a public page, or None. Name and tagline both use it."""
    squashed = _fold(text)
    words = _words(text)
    for bad in _BLOCK_SUBSTRINGS + _extra_blocklist():
        if bad in squashed:
            return "contains language that is not allowed"
    if any(w in _BLOCK_WORDS for w in words):
        return "contains language that is not allowed"
    for brand in _RESERVED_SUBSTRINGS:
        if brand in squashed:
            return "uses a protected brand or book name"
    if any(w in _RESERVED_WORDS for w in words):
        return "uses a reserved word"
    return None


# --- real team and player names ---------------------------------------------------------

_known_cache: dict = {}


def _norm_name(text: str) -> str:
    return " ".join(_words(text.replace("-", " ")))


def known_real_names() -> dict:
    """{normalised name: kind} for every team (and, when the box-score store is present, every
    player) this program knows. A hound must not borrow a real club's or athlete's name."""
    if "names" in _known_cache:
        return _known_cache["names"]
    names: dict = {}
    try:
        from src.pipeline import slate as slate_mod
        for tail in slate_mod._NAME_TAIL_TO_ABBREV:
            names[_norm_name(tail)] = "team"
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.sports import nfl_teams
        for _code, full, nick in nfl_teams.TEAMS:
            names[_norm_name(full)] = "team"
            names[_norm_name(nick)] = "team"
    except Exception:  # noqa: BLE001
        pass
    try:
        from src import paths
        box = Path(paths.repo_root()) / "data" / "processed" / "boxscores_2026.jsonl"
        if box.exists():
            with box.open(encoding="utf-8") as fh:
                for line in fh:
                    if '"player_name"' not in line:
                        continue
                    m = re.search(r'"player_name": "([^"]+)"', line)
                    if m:
                        names[_norm_name(m.group(1))] = "player"
    except Exception:  # noqa: BLE001
        pass
    names.pop("", None)
    _known_cache["names"] = names
    return names


def real_name_problem(name: str, extra: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """None when `name` is not (and does not contain) a real team or player name."""
    table = dict(known_real_names())
    if extra:
        table.update({_norm_name(k): v for k, v in extra.items()})
    norm = _norm_name(name)
    if norm in table:
        return f"is a real {table[norm]} name"
    padded = f" {norm} "
    for known, kind in table.items():
        if kind == "team" and f" {known} " in padded:
            return "contains a real team name"
    return None


# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------

def _is_price(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 100


def price_decimal(price: float) -> float:
    return odds_math.american_to_decimal(price)


def in_band(price: float, price_min: int, price_max: int) -> bool:
    """Is an American `price` between the shortest and longest price of a band? Compared in
    decimal odds, because American odds are not ordered across the -100 / +100 gap."""
    d = price_decimal(price)
    return price_decimal(price_min) - 1e-9 <= d <= price_decimal(price_max) + 1e-9


def beyond_cap(price: float) -> bool:
    """True for -200 or worse. The single definition of the cap."""
    return price < 0 and price <= MAX_FAVOURITE_PRICE


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> Optional[list]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _check_name(raw: Mapping, errors: dict, taken_names: Iterable[str],
                extra_real_names: Optional[Mapping[str, str]]) -> Optional[str]:
    name = raw.get("name")
    if not isinstance(name, str):
        errors["name"] = "is required"
        return name
    name = name.strip()
    if not (NAME_MIN <= len(name) <= NAME_MAX):
        errors["name"] = f"must be {NAME_MIN} to {NAME_MAX} characters"
    elif not _NAME_RE.match(name) or "  " in name or not re.search(r"[A-Za-z]", name):
        errors["name"] = "may use only letters, digits, spaces and hyphens, with a letter in it"
    else:
        problem = text_problem(name) or real_name_problem(name, extra_real_names)
        if problem:
            errors["name"] = problem
        elif _fold(name) in {_fold(t) for t in taken_names}:
            errors["name"] = "is already taken"
    return name


def _check_tagline(raw: Mapping, errors: dict, key: str = "tagline", maximum: int = TAGLINE_MAX) -> str:
    tagline = raw.get(key, "")
    if tagline is None:
        tagline = ""
    if not isinstance(tagline, str):
        errors[key] = "must be text"
        return ""
    tagline = " ".join(tagline.split())
    if len(tagline) > maximum:
        errors[key] = f"must be {maximum} characters or fewer"
    elif not _TAGLINE_OK_RE.match(tagline):
        errors[key] = "uses characters that are not allowed"
    else:
        problem = text_problem(tagline)
        if problem:
            errors[key] = problem
    return tagline


def normalize_sports(value: Any) -> Optional[list]:
    """The explicit, canonically ordered sport list for a raw `sports` choice, or None when it is not valid.

    "ANY" (alone or among others) means every sport on the dog menu. It is written out as that explicit list
    at validation, on purpose: a spec is immutable and hashed, and the published rule must be exactly what
    ran, so a dog built as ANY keeps the families that existed when it was built rather than silently
    betting a sport added later."""
    items = _as_list(value)
    if not items or any(not isinstance(s, str) for s in items):
        return None
    if ANY in items:
        return list(SPORTS)
    if any(s not in SPORTS for s in items) or len(set(items)) != len(items):
        return None
    return [s for s in SPORTS if s in items]


def sports_error_text() -> str:
    return f"choose from {', '.join(SPORTS)}, or {ANY} for every sport"


def validate_spec(raw: Mapping, *, taken_names: Iterable[str] = (),
                  extra_real_names: Optional[Mapping[str, str]] = None) -> dict:
    """The strict gate. Returns a NORMALISED spec (canonical order, canonical types) or raises
    SpecError carrying every problem at once. Unknown keys are refused, not ignored: a field the
    engine does not read must never be published as if it were part of the rule."""
    errors: dict = {}
    if not isinstance(raw, Mapping):
        raise SpecError({"spec": "must be an object"})
    if raw.get("version") == SPEC_VERSION_V2 or "rules" in raw or "style" in raw:
        return _validate_v2(raw, taken_names=taken_names, extra_real_names=extra_real_names)
    allowed = set(SPEC_FIELDS) | {"version"}
    for key in raw:
        if key not in allowed:
            errors[str(key)] = "is not a field on the menu"

    name = _check_name(raw, errors, taken_names, extra_real_names)
    tagline = _check_tagline(raw, errors)

    # sports / markets
    sports = normalize_sports(raw.get("sports", raw.get("sport")))
    if sports is None:
        errors["sports"] = sports_error_text()
    markets = _as_list(raw.get("markets", raw.get("market")))
    if not markets or any(m not in MARKETS for m in markets) or len(set(markets)) != len(markets):
        errors["markets"] = f"choose from {', '.join(MARKETS)}"
        markets = None
    else:
        markets = [m for m in MARKETS if m in markets]

    # side rule
    side = raw.get("side_rule")
    if side not in SIDE_RULES:
        errors["side_rule"] = f"choose one of {', '.join(SIDE_RULES)}"
        side = None
    elif markets is not None:
        bad = [m for m in markets if m not in SIDE_MARKETS[side]]
        if bad:
            errors["side_rule"] = (f"'{side}' cannot be applied to {', '.join(bad)}; it works on "
                                   f"{', '.join(SIDE_MARKETS[side])}")

    # price band
    pmin, pmax = raw.get("price_min"), raw.get("price_max")
    for key, value in (("price_min", pmin), ("price_max", pmax)):
        if not _is_price(value):
            errors[key] = "must be an American price such as -150 or +120"
        elif value < 0 and value < SHORTEST_ALLOWED_PRICE:
            errors[key] = (f"cannot be {MAX_FAVOURITE_PRICE} or worse; this program never "
                           f"selects a price that short")
        elif value > LONGEST_ALLOWED_PRICE:
            errors[key] = f"cannot be longer than +{LONGEST_ALLOWED_PRICE}"
    if "price_min" not in errors and "price_max" not in errors:
        if price_decimal(pmin) > price_decimal(pmax):
            errors["price_max"] = "must be the same as or longer than price_min"

    def _bounded(key, low, high):
        v = raw.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not (low <= v <= high):
            errors[key] = f"must be a whole number from {low} to {high}"
            return None
        return v

    min_books = _bounded("min_books", *MIN_BOOKS_RANGE)
    max_bets = _bounded("max_bets_per_day", *MAX_BETS_RANGE)
    lock = raw.get("lock_minutes")
    if isinstance(lock, bool) or lock not in LOCK_CHOICES:
        errors["lock_minutes"] = f"must be one of {', '.join(map(str, LOCK_CHOICES))}"
        lock = None

    if errors:
        raise SpecError(errors)
    return {
        "version": SPEC_VERSION, "name": name, "tagline": tagline, "sports": sports,
        "markets": markets, "side_rule": side, "price_min": pmin, "price_max": pmax,
        "min_books": min_books, "max_bets_per_day": max_bets, "lock_minutes": lock,
    }


RULE_FIELDS_V2 = ("rules", "lock_minutes", "max_bets_per_day", "stake_units", "rank_by")


def is_gematria(spec: Mapping) -> bool:
    """True for a version-2 spec with the member Gematria style (``src/hounds/user_gematria.py``)."""
    return isinstance(spec, Mapping) and spec.get("style") == STYLE_GEMATRIA


def rule_fields(spec: Mapping) -> dict:
    """The fields that make a hound's RULE (everything except its name, tagline, colour and badge)."""
    if spec.get("version") == SPEC_VERSION_V2:
        out = {"v": SPEC_VERSION_V2, **{k: spec[k] for k in RULE_FIELDS_V2}}
        if is_gematria(spec):
            # the style and the rules stamp it was made under are part of the rule; an ordinary hound's hash is unchanged
            out["style"], out["gematria"] = STYLE_GEMATRIA, spec["gematria"]
        return out
    return {k: spec[k] for k in RULE_FIELDS}


def spec_hash(spec: Mapping) -> str:
    """sha256 of the RULE fields only: two hounds with the same rule share a hash whatever they
    are called, which is how a copy that changed nothing is recognised."""
    body = json.dumps(rule_fields(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# the published rule
# ---------------------------------------------------------------------------

def _fmt_price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def _market_words(spec: Mapping) -> str:
    sports = spec["sports"]
    names = []
    for m in spec["markets"]:
        if m == "moneyline":
            names.append("moneylines")
        elif m == "spread":
            names.append("run lines" if sports == ["MLB"] else
                         "point spreads" if sports == ["NFL"] else
                         "run lines and point spreads" if set(sports) <= set(LEGACY_SPORTS) else "spreads")
        else:
            names.append("game totals")
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


_SIDE_PHRASE = {
    "favourite": "the favourite",
    "underdog": "the underdog",
    "home": "the home side",
    "away": "the away side",
    "over": "the over",
    "under": "the under",
    "market_moved_toward": "the side the market has moved toward since our first capture of the game (a line change, or half a point of win probability)",
    "market_moved_away": "the side the market has moved away from since our first capture of the game (a line change, or half a point of win probability)",
}


# How a sport reads inside a sentence. The catalog keys (GRIDIRON, BASKETBALL, NCAAF ...) are internal and never user copy; this is the
# short label a reader sees (the hound pages' web/js/hounds-board.js SPORT_LABELS says the same words). MLB, NFL, NBA, WNBA, NHL, MMA and
# AFL are what people call them, so they pass through.
SPORT_PHRASE_LABELS = {
    "NCAAF": "college football", "GRIDIRON": "CFL and UFL", "NCAAB": "college basketball", "BASKETBALL": "other basketball",
    "HOCKEY": "other hockey", "BASEBALL": "other baseball", "SOCCER": "soccer", "TENNIS": "tennis", "CRICKET": "cricket",
    "RUGBY": "rugby", "AFL": "Aussie rules",
}


def sport_words(code: str) -> str:
    """One sport as a reader sees it: the label, never the internal key ("GRIDIRON" reads "CFL and UFL")."""
    key = str(code or "").strip()
    return SPORT_PHRASE_LABELS.get(key.upper()) or (key.upper() if key.upper() in SPORTS else key)


def sports_phrase(sports: Iterable[str]) -> str:
    """'MLB and NFL', 'NBA', 'any sport' (every dog-menu family), or 'MLB, NFL, NBA and 4 more sports'. Every sport reads by its
    label (``sport_words``), never by its internal key."""
    sports = list(sports)
    if set(sports) >= set(SPORTS) and len(SPORTS) > 2:
        return "any sport"
    words = [sport_words(x) for x in sports]
    if len(words) <= 3:
        text = " and ".join(words) if len(words) <= 2 else ", ".join(words[:-1]) + " and " + words[-1]
    else:
        text = ", ".join(words[:3]) + f" and {len(words) - 3} more sport{'' if len(words) == 4 else 's'}"
    return text[:1].upper() + text[1:]            # a phrase opens a clause


def rule_text(spec: Mapping) -> str:
    """The plain-English rule, generated from the validated spec and nothing else."""
    if spec.get("version") == SPEC_VERSION_V2:
        from src.hounds.english import render
        return render.rule_text(spec)
    sports = spec["sports"]
    sport_words = sports_phrase(sports)
    words = {sports_catalog.start_word(c) for c in sports}
    starts = words.pop() if len(words) == 1 else ("first pitch or kickoff" if set(sports) == set(LEGACY_SPORTS)
                                                   else "the start")
    books = spec["min_books"]
    bets = spec["max_bets_per_day"]
    return (
        f"{sport_words} {_market_words(spec)}. "
        f"{spec['lock_minutes']} minutes before {starts}, it backs {_SIDE_PHRASE[spec['side_rule']]} "
        f"when the average price across the books is between {_fmt_price(spec['price_min'])} and "
        f"{_fmt_price(spec['price_max'])} (never {MAX_FAVOURITE_PRICE} or worse) and at least "
        f"{books} {'book is' if books == 1 else 'books are'} quoting it. "
        f"At most {bets} {'bet' if bets == 1 else 'bets'} a day, earliest placing time first. "
        f"Each bet is one paper unit, graded at the average price. {NOT_ADVICE}"
    )


def sports_menu() -> list:
    """The sport choices for the builder: every dog-menu family, then ANY (every family at once)."""
    return ([{"value": s, "label": SPORT_LABELS[s]} for s in SPORTS]
            + [{"value": ANY, "label": "Any sport", "any": True}])


def menu() -> dict:
    """The fixed menu, with labels, for the web form. Nothing outside it validates."""
    return {
        "paper_only": True,
        "not_advice": NOT_ADVICE,
        "name": {"min": NAME_MIN, "max": NAME_MAX, "pattern": "letters, digits, spaces, hyphens"},
        "tagline": {"max": TAGLINE_MAX},
        "sports": sports_menu(),
        "markets": [{"value": m, "label": MARKET_LABELS[m], "sports": list(SPORTS)} for m in MARKETS],
        "side_rules": [{"value": s, "label": SIDE_LABELS[s], "markets": list(SIDE_MARKETS[s])}
                       for s in SIDE_RULES],
        "price_min": {"label": "Shortest price", "presets": list(PRICE_PRESETS_SHORT),
                      "lowest": SHORTEST_ALLOWED_PRICE},
        "price_max": {"label": "Longest price", "presets": list(PRICE_PRESETS_LONG),
                      "highest": LONGEST_ALLOWED_PRICE},
        "price_cap_note": f"No selection at {MAX_FAVOURITE_PRICE} or worse, ever.",
        "min_books": {"label": "Books quoting at least", "min": MIN_BOOKS_RANGE[0],
                      "max": MIN_BOOKS_RANGE[1]},
        "max_bets_per_day": {"label": "Most bets a day", "min": MAX_BETS_RANGE[0],
                             "max": MAX_BETS_RANGE[1]},
        "lock_minutes": {"label": "Lock this long before the start",
                         "choices": list(LOCK_CHOICES)},
        "max_running_per_account": MAX_RUNNING_PER_ACCOUNT,
    }


# ---------------------------------------------------------------------------
# version 2: the composable rule set (conditions live in src/hounds/user_rules.py)
# ---------------------------------------------------------------------------

V2_RULE_KEYS = ("label", "sports", "markets", "side", "price_min", "price_max", "line_min", "line_max",
                "min_books", "when")
# Keys a version-2 spec carries for readers that predate it (the public definition, the kennel feed):
# derived from the rules on every validation, accepted on input so a spec can be POSTed back as read,
# and never part of the rule hash.
V2_DERIVED_KEYS = ("sports", "markets", "side_rule")
V2_TOP_KEYS = ("version", "name", "tagline", "color", "badge", "lock_minutes", "max_bets_per_day",
               "stake_units", "rank_by", "rules") + V2_DERIVED_KEYS
# The base style (src/hounds/user_gematria.py): "rules" is every ordinary hound (the key is simply absent), "gematria" is the
# member Gematria style, whose pick logic is the house Gematria Hound's. `gematria` is its creation stamp (rules version + hash).
STYLE_RULES, STYLE_GEMATRIA = "rules", "gematria"
STYLES = (STYLE_RULES, STYLE_GEMATRIA)
V2_STYLE_KEYS = ("style", "gematria")
RULE_LABEL_MAX = 40
DEFAULT_MIN_BOOKS_GAME, DEFAULT_MIN_BOOKS_PROP = 3, 1
LINE_RANGE = (-30.0, 60.0)
# Prop boards are captured twice a game (a baseline 5-24 hours out, a gate capture 0-2 hours out), so a
# 120 or 180 minute lock often has only the baseline board. Point-in-time either way; this bounds how
# stale a price may be.
MAX_PROP_BOARD_AGE_MINUTES = 720


def _known_player_fn():
    """A predicate for 'is this a player in our box scores', or None when no box-score store is
    present at all (then names cannot be checked and are accepted if well formed)."""
    from src.hounds.user_facts import known_player_keys
    from src.hounds.user_rules import fold_player
    names = known_player_keys()
    return (lambda n: fold_player(n) in names) if names else None


def _price_errors(raw: Mapping, errors: dict, prefix: str) -> tuple:
    pmin, pmax = raw.get("price_min", SHORTEST_ALLOWED_PRICE), raw.get("price_max", LONGEST_ALLOWED_PRICE)
    for key, value in (("price_min", pmin), ("price_max", pmax)):
        if not _is_price(value):
            errors[f"{prefix}{key}"] = "must be an American price such as -150 or +120"
        elif value < 0 and value < SHORTEST_ALLOWED_PRICE:
            errors[f"{prefix}{key}"] = (f"cannot be {MAX_FAVOURITE_PRICE} or worse; this program never "
                                        f"selects a price that short")
        elif value > LONGEST_ALLOWED_PRICE:
            errors[f"{prefix}{key}"] = f"cannot be longer than +{LONGEST_ALLOWED_PRICE}"
    if f"{prefix}price_min" not in errors and f"{prefix}price_max" not in errors:
        if price_decimal(pmin) > price_decimal(pmax):
            errors[f"{prefix}price_max"] = "must be the same as or longer than price_min"
    return pmin, pmax


def _line_value(raw: Mapping, key: str, errors: dict, prefix: str) -> Optional[float]:
    v = raw.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not (LINE_RANGE[0] <= v <= LINE_RANGE[1]):
        errors[f"{prefix}{key}"] = f"must be a number from {LINE_RANGE[0]:g} to {LINE_RANGE[1]:g}"
        return None
    return float(v)


def _validate_rule(raw: Any, index: int, errors: dict) -> Optional[dict]:
    from src.hounds import user_rules as R
    prefix = f"rules[{index}]."
    if not isinstance(raw, Mapping):
        errors[f"rules[{index}]"] = "a rule must be an object"
        return None
    for key in raw:
        if key not in V2_RULE_KEYS:
            errors[f"{prefix}{str(key)[:30]}"] = "is not a field on the menu"
    start_errors = len(errors)

    label = raw.get("label", "")
    if label is None:
        label = ""
    if not isinstance(label, str):
        errors[f"{prefix}label"] = "must be text"
        label = ""
    else:
        label = _check_tagline({f"{prefix}label": label}, errors, key=f"{prefix}label", maximum=RULE_LABEL_MAX)

    sports = normalize_sports(raw.get("sports", raw.get("sport")))
    if sports is None:
        errors[f"{prefix}sports"] = sports_error_text()
    markets = _as_list(raw.get("markets", raw.get("market")))
    if not markets or any(m not in R.ALL_MARKETS for m in markets) or len(set(markets)) != len(markets):
        errors[f"{prefix}markets"] = f"choose from {', '.join(R.ALL_MARKETS)}"
        markets = None
    else:
        markets = [m for m in R.ALL_MARKETS if m in markets]
    kinds: list = []
    if markets:
        kinds = sorted({R.market_kind(m) for m in markets})
        if len(kinds) > 1:
            errors[f"{prefix}markets"] = ("a rule is about game bets (moneyline, spread), game totals, or "
                                          "player props; put each in its own rule")
            markets = None
        elif "prop" in kinds and sports and sports != ["MLB"]:
            errors[f"{prefix}sports"] = "player props are MLB only: there are no prop prices on file for any other sport"
            sports = None

    side = raw.get("side", "either")
    if side not in R.SIDES:
        errors[f"{prefix}side"] = f"choose one of {', '.join(R.SIDES)}"
        side = None
    elif markets and side not in R.sides_for(kinds):
        errors[f"{prefix}side"] = (f"'{side}' cannot be applied to {', '.join(markets)}; it works on "
                                   f"{', '.join(R.sides_for(kinds))}")

    pmin, pmax = _price_errors(raw, errors, prefix)
    lmin, lmax = _line_value(raw, "line_min", errors, prefix), _line_value(raw, "line_max", errors, prefix)
    if lmin is not None and lmax is not None and lmin > lmax:
        errors[f"{prefix}line_max"] = "must be the same as or higher than line_min"
    if (lmin is not None or lmax is not None) and markets and markets == ["moneyline"]:
        errors[f"{prefix}line_min"] = "a moneyline has no line; use the price range instead"

    default_books = DEFAULT_MIN_BOOKS_PROP if "prop" in kinds else DEFAULT_MIN_BOOKS_GAME
    mb = raw.get("min_books", default_books)
    if isinstance(mb, bool) or not isinstance(mb, int) or not (MIN_BOOKS_RANGE[0] <= mb <= MIN_BOOKS_RANGE[1]):
        errors[f"{prefix}min_books"] = f"must be a whole number from {MIN_BOOKS_RANGE[0]} to {MIN_BOOKS_RANGE[1]}"
        mb = None

    when = None
    if raw.get("when") is not None and sports and markets:
        when = R.validate_tree(raw["when"], kinds=kinds, markets=markets, sports=sports,
                               path=f"{prefix}when", errors=errors, known_players=_known_player_fn())
    if len(errors) > start_errors:
        return None
    return {"label": label, "sports": sports, "markets": markets, "side": side, "price_min": pmin,
            "price_max": pmax, "line_min": lmin, "line_max": lmax, "min_books": mb, "when": when}


def _validate_v2(raw: Mapping, *, taken_names: Iterable[str], extra_real_names) -> dict:
    from src.hounds import user_rules as R
    errors: dict = {}
    for key in raw:
        if key not in V2_TOP_KEYS and key not in V2_STYLE_KEYS:
            errors[str(key)[:30]] = "is not a field on the menu"
    style = raw.get("style", STYLE_RULES)
    if style not in STYLES:
        errors["style"] = f"choose one of {', '.join(STYLES)}"
        style = STYLE_RULES
    if style == STYLE_RULES and raw.get("gematria") is not None:
        errors["gematria"] = "belongs to the Gematria style only"
    if raw.get("version", SPEC_VERSION_V2) != SPEC_VERSION_V2:
        errors["version"] = f"must be {SPEC_VERSION_V2}"
    name = _check_name(raw, errors, taken_names, extra_real_names)
    tagline = _check_tagline(raw, errors)

    color = raw.get("color", "ember")
    if color not in R.COLOR_IDS:
        errors["color"] = f"choose one of {', '.join(R.COLOR_IDS)}"
    badge = raw.get("badge", "bone")
    if badge not in R.BADGE_IDS:
        errors["badge"] = f"choose one of {', '.join(R.BADGE_IDS)}"

    fixed = None
    if style == STYLE_GEMATRIA:
        from src.hounds import user_gematria
        fixed = user_gematria.normalize(raw, errors)
    lock = raw.get("lock_minutes", LOCK_CHOICES[1]) if fixed is None else fixed["lock_minutes"]
    if isinstance(lock, bool) or lock not in LOCK_CHOICES:
        errors["lock_minutes"] = f"must be one of {', '.join(map(str, LOCK_CHOICES))}"
        lock = None
    bets = raw.get("max_bets_per_day", 2)
    if isinstance(bets, bool) or not isinstance(bets, int) or not (MAX_BETS_RANGE[0] <= bets <= MAX_BETS_RANGE[1]):
        errors["max_bets_per_day"] = f"must be a whole number from {MAX_BETS_RANGE[0]} to {MAX_BETS_RANGE[1]}"
        bets = None
    stake = raw.get("stake_units", 1.0)
    if isinstance(stake, bool) or not isinstance(stake, (int, float)) or float(stake) not in R.STAKE_CHOICES:
        errors["stake_units"] = f"must be one of {', '.join(f'{s:g}' for s in R.STAKE_CHOICES)} paper units"
        stake = None
    rank = raw.get("rank_by", "earliest_lock")
    if rank not in R.RANK_RULES:
        errors["rank_by"] = f"choose one of {', '.join(R.RANK_RULES)}"

    rules_raw = raw.get("rules") if fixed is None else fixed["rules"]
    rules: list = []
    if style == STYLE_GEMATRIA and fixed is None:
        pass                                    # `normalize` already said what is wrong
    elif not isinstance(rules_raw, (list, tuple)) or not rules_raw:
        errors["rules"] = "add at least one rule"
    elif len(rules_raw) > R.MAX_RULES:
        errors["rules"] = f"a dog has at most {R.MAX_RULES} rules"
    else:
        for i, item in enumerate(rules_raw):
            norm = _validate_rule(item, i, errors)
            if norm is not None:
                rules.append(norm)
    if errors:
        raise SpecError(errors)
    sports = [s for s in SPORTS if any(s in r["sports"] for r in rules)]
    markets = [m for m in R.ALL_MARKETS if any(m in r["markets"] for r in rules)]
    out = {
        "version": SPEC_VERSION_V2, "name": name, "tagline": tagline, "color": color, "badge": badge,
        "sports": sports, "markets": markets, "side_rule": "custom", "lock_minutes": lock,
        "max_bets_per_day": bets, "stake_units": float(stake), "rank_by": rank, "rules": rules,
    }
    if fixed is not None:
        out["style"], out["gematria"] = STYLE_GEMATRIA, fixed["stamp"]
    return out


def is_v2(spec: Mapping) -> bool:
    return spec.get("version") == SPEC_VERSION_V2


def upgrade_v1(spec: Mapping) -> dict:
    """A version-1 spec as the equivalent version-2 DRAFT (not validated against names): what the
    builder opens when its owner edits a classic dog. The new version is a different spec (it hashes
    differently), so the old record and every bet on it stay exactly as they were."""
    side_rule = spec["side_rule"]
    base = {"sports": list(spec["sports"]), "price_min": spec["price_min"], "price_max": spec["price_max"],
            "line_min": None, "line_max": None, "min_books": spec["min_books"]}
    when_items: list = []
    side = "either"
    if side_rule in ("home", "away", "over", "under"):
        side = side_rule
    elif side_rule in ("favourite", "underdog"):
        when_items.append({"id": "role", "value": side_rule})
    elif side_rule in ("market_moved_toward", "market_moved_away"):
        when_items.append({"id": "steam", "direction": "toward" if side_rule.endswith("toward") else "against"})
    rules = []
    for markets in ([m for m in spec["markets"] if m != "total"], [m for m in spec["markets"] if m == "total"]):
        if not markets:
            continue
        if markets == ["total"] and side in ("home", "away"):
            continue
        if markets != ["total"] and side in ("over", "under"):
            continue
        rules.append({**base, "label": "", "markets": markets, "side": side,
                      "when": {"op": "all", "items": list(when_items)} if when_items else None})
        if markets == ["total"] and when_items and when_items[0]["id"] == "role":
            rules.pop()                      # a favourite/underdog rule never applied to totals
    return {"version": SPEC_VERSION_V2, "name": spec["name"], "tagline": spec.get("tagline", ""),
            "color": "ember", "badge": "bone", "lock_minutes": spec["lock_minutes"],
            "max_bets_per_day": spec["max_bets_per_day"], "stake_units": 1.0, "rank_by": "earliest_lock",
            "rules": rules}


def builder_menu() -> dict:
    """GET /hounds/builder/menu: everything a client may put in a version-2 spec, with bounds. The
    English parser, the AI translator's output check and the web builder are all generated from, and
    validated against, this one document."""
    from src.hounds import bankroll, user_rules as R
    return {
        "spec_version": SPEC_VERSION_V2,
        "paper_only": True, "not_advice": NOT_ADVICE,
        "price_cap_note": f"No selection at {MAX_FAVOURITE_PRICE} or worse, ever.",
        "limits": {"max_rules": R.MAX_RULES, "max_depth": R.MAX_DEPTH, "max_conditions_per_rule": R.MAX_CONDITIONS,
                   "max_running_per_account": MAX_RUNNING_PER_ACCOUNT, "max_list": R.MAX_LIST},
        "name": {"min": NAME_MIN, "max": NAME_MAX}, "tagline": {"max": TAGLINE_MAX},
        "rule_label": {"max": RULE_LABEL_MAX},
        "sports": sports_menu(),
        "markets": [{"value": m, "label": R.MARKET_LABELS[m], "kind": R.market_kind(m), "has_line": m != "moneyline",
                     "sports": ["MLB"] if R.market_kind(m) == "prop" else list(SPORTS)} for m in R.ALL_MARKETS],
        "sides": [{"value": s, "label": R.SIDE_LABELS[s]} for s in R.SIDES],
        "side_by_kind": {"ml_spread": list(R.sides_for(["ml_spread"])), "total": list(R.sides_for(["total"])),
                         "prop": list(R.sides_for(["prop"]))},
        "price": {"lowest": SHORTEST_ALLOWED_PRICE, "highest": LONGEST_ALLOWED_PRICE,
                  "presets_short": list(PRICE_PRESETS_SHORT), "presets_long": list(PRICE_PRESETS_LONG),
                  "cap": MAX_FAVOURITE_PRICE},
        "line": {"min": LINE_RANGE[0], "max": LINE_RANGE[1]},
        "min_books": {"min": MIN_BOOKS_RANGE[0], "max": MIN_BOOKS_RANGE[1],
                      "default_game": DEFAULT_MIN_BOOKS_GAME, "default_prop": DEFAULT_MIN_BOOKS_PROP},
        "max_bets_per_day": {"min": MAX_BETS_RANGE[0], "max": MAX_BETS_RANGE[1], "default": 2},
        "stake_units": {"choices": list(R.STAKE_CHOICES), "default": 1.0},
        "lock_minutes": {"choices": list(LOCK_CHOICES), "default": LOCK_CHOICES[1]},
        "rank_by": [{"value": r, "label": R.RANK_LABELS[r]} for r in R.RANK_RULES],
        "colors": [{"value": c[0], "label": c[1], "hex": c[2]} for c in R.COLORS],
        "badges": [{"value": b[0], "label": b[1]} for b in R.BADGES],
        "teams": R.team_menu(),
        "conditions": R.menu_conditions(),
        "prop_board_note": ("Prop boards are captured twice a game, so a prop is priced from the newest "
                            "capture at or before your lock, up to "
                            f"{MAX_PROP_BOARD_AGE_MINUTES // 60} hours old."),
        "ranking_note": ("When more picks qualify than your daily cap, they are ranked by your rule. A pick "
                         "is made at its own decision time, so the ranking decides among the picks that qualify "
                         "in the same engine pass; a bet already made is never taken back."),
        "stake_note": ("Your dog's bankroll, return and units use this stake; its win-loss record counts every "
                       "bet once."),
        "bankroll": bankroll.public_block(),
        "styles": base_styles(),
    }


def base_styles() -> list:
    """The builder's base-style choices. "rules" is the ordinary builder (the rest of the menu applies); "gematria" is the
    member style whose picks come from the house Gematria Hound's engine and active rules, so it carries only what a member
    may choose (sports, most bets a day, stake, name) and the fixed facts the page states beside it."""
    from src.hounds import user_gematria as G
    fixed = {"markets": [G.MARKET], "lock_minutes": None, "price_band": None, "rules_version": None}
    try:
        rules = G.load_rules()
        fixed.update({"lock_minutes": int(rules.decision.lock_minutes), "rules_version": rules.version,
                      "price_band": list(rules.decision.price_band)})
    except Exception:  # noqa: BLE001 -- a menu that cannot read the rules still lists the style, with the facts it has
        pass
    fixed["text"] = G.fixed_text(fixed)
    return [
        {"value": STYLE_RULES, "label": "Your own rules",
         "summary": "Describe the bets in plain English or build them from rules: sports, markets, prices and conditions."},
        {"value": STYLE_GEMATRIA, "label": G.STYLE_LABEL, "summary": G.EXPLAINER, "quiz_line": G.QUIZ_LINE,
         "house_hound": {"id": G.HOUSE_HOUND_ID, "name": G.HOUSE_HOUND_NAME, "href": G.HOUSE_HOUND_HREF},
         "chooses": ["sports", "max_bets_per_day", "stake_units"], "fixed": fixed},
    ]
