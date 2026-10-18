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

SPEC_VERSION = 1

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
MAX_RUNNING_PER_ACCOUNT = 3

SPORTS = ("MLB", "NFL")
MARKETS = ("moneyline", "spread", "total")

SIDE_RULES = (
    "favourite", "underdog", "home", "away", "over", "under",
    "market_moved_toward", "market_moved_away",
)

SPORT_LABELS = {"MLB": "MLB", "NFL": "NFL"}
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


def validate_spec(raw: Mapping, *, taken_names: Iterable[str] = (),
                  extra_real_names: Optional[Mapping[str, str]] = None) -> dict:
    """The strict gate. Returns a NORMALISED spec (canonical order, canonical types) or raises
    SpecError carrying every problem at once. Unknown keys are refused, not ignored: a field the
    engine does not read must never be published as if it were part of the rule."""
    errors: dict = {}
    if not isinstance(raw, Mapping):
        raise SpecError({"spec": "must be an object"})
    allowed = set(SPEC_FIELDS) | {"version"}
    for key in raw:
        if key not in allowed:
            errors[str(key)] = "is not a field on the menu"

    # name
    name = raw.get("name")
    if not isinstance(name, str):
        errors["name"] = "is required"
    else:
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

    # tagline
    tagline = raw.get("tagline", "")
    if tagline is None:
        tagline = ""
    if not isinstance(tagline, str):
        errors["tagline"] = "must be text"
    else:
        tagline = " ".join(tagline.split())
        if len(tagline) > TAGLINE_MAX:
            errors["tagline"] = f"must be {TAGLINE_MAX} characters or fewer"
        elif not _TAGLINE_OK_RE.match(tagline):
            errors["tagline"] = "uses characters that are not allowed"
        else:
            problem = text_problem(tagline)
            if problem:
                errors["tagline"] = problem

    # sports / markets
    sports = _as_list(raw.get("sports", raw.get("sport")))
    if not sports or any(s not in SPORTS for s in sports) or len(set(sports)) != len(sports):
        errors["sports"] = f"choose one or both of {', '.join(SPORTS)}"
        sports = None
    else:
        sports = [s for s in SPORTS if s in sports]
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


def rule_fields(spec: Mapping) -> dict:
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
                         "point spreads" if sports == ["NFL"] else "run lines and point spreads")
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


def rule_text(spec: Mapping) -> str:
    """The plain-English rule, generated from the validated spec and nothing else."""
    sports = spec["sports"]
    sport_words = " and ".join(sports)
    start_word = {"MLB": "first pitch", "NFL": "kickoff"}
    starts = start_word[sports[0]] if len(sports) == 1 else "first pitch or kickoff"
    books = spec["min_books"]
    bets = spec["max_bets_per_day"]
    return (
        f"{sport_words} {_market_words(spec)}. "
        f"{spec['lock_minutes']} minutes before {starts}, it backs {_SIDE_PHRASE[spec['side_rule']]} "
        f"when the average price across the books is between {_fmt_price(spec['price_min'])} and "
        f"{_fmt_price(spec['price_max'])} (never {MAX_FAVOURITE_PRICE} or worse) and at least "
        f"{books} {'book is' if books == 1 else 'books are'} quoting it. "
        f"At most {bets} {'bet' if bets == 1 else 'bets'} a day, earliest lock first. "
        f"Each bet is one paper unit, graded at the average price. {NOT_ADVICE}"
    )


def menu() -> dict:
    """The fixed menu, with labels, for the web form. Nothing outside it validates."""
    return {
        "paper_only": True,
        "not_advice": NOT_ADVICE,
        "name": {"min": NAME_MIN, "max": NAME_MAX, "pattern": "letters, digits, spaces, hyphens"},
        "tagline": {"max": TAGLINE_MAX},
        "sports": [{"value": s, "label": SPORT_LABELS[s]} for s in SPORTS],
        "markets": [{"value": m, "label": MARKET_LABELS[m]} for m in MARKETS],
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
