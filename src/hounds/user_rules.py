"""The rule language of a user-built hound: conditions, how they validate, read in English and run.

WHY A REGISTRY AND NOT FREE TEXT
--------------------------------
A hound is a PAPER strategy that races in public, so every sentence it shows has to be exactly what
the engine does. A condition is therefore a row in the `CONDITIONS` table below: an id, typed
parameters with hard bounds, the sentence it renders to, and the one function that decides it. The
web builder, the English parser, the AI translator's output check, the renderer and the engine all
read this one table, so there is no second place for them to drift apart. A model (or a person) can
only ever produce an instance of a row that is already here; anything else is refused by
`validate_condition` with a reason.

CONDITIONS COMBINE IN GROUPS
----------------------------
A rule's `when` is a tree: `{"op": "all"|"any", "items": [condition | group, ...]}`. `all` is AND and
`any` is OR; groups nest to `MAX_DEPTH`. A hound has up to `MAX_RULES` rules and a rule is one
recipe (sports, markets, which side, a price band, a line range, a book minimum and a `when` tree).
Rules are alternatives: a bet is made when ANY rule produces it.

POINT IN TIME, AND NEVER A GUESS
--------------------------------
`evaluate` is a pure function of a `Ctx` that the engine builds from data that existed at the game's
lock. A condition whose input is missing (a team with no recent games, a player with too few box
scores, a park with no verified wind bearing) returns None, which counts as "not met" and is
tallied by name, so a silent gap can never turn into a bet and never hides as a quiet slate.

NOTHING HERE TOUCHES DISK OR THE NETWORK. Facts come in through `ctx.facts` (src/hounds/user_facts.py).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------

MAX_RULES = 4
MAX_DEPTH = 3
MAX_CONDITIONS = 16            # per rule, counting leaves in every nested group
MAX_LIST = 5                   # teams or players named in one condition

GAME_MARKETS = ("moneyline", "spread", "total")
PROP_MARKETS = ("batter_hits", "batter_total_bases", "batter_home_runs", "batter_rbis",
                "batter_runs_scored", "batter_hits_runs_rbis", "pitcher_strikeouts")
ALL_MARKETS = GAME_MARKETS + PROP_MARKETS

MARKET_LABELS = {
    "moneyline": "Moneyline", "spread": "Spread / run line", "total": "Game total",
    "batter_hits": "Batter hits", "batter_total_bases": "Batter total bases",
    "batter_home_runs": "Batter home runs", "batter_rbis": "Batter RBIs",
    "batter_runs_scored": "Batter runs scored", "batter_hits_runs_rbis": "Batter hits + runs + RBIs",
    "pitcher_strikeouts": "Pitcher strikeouts",
}
# What each prop market counts, and where the box score keeps it. The settlement and the player
# conditions read the same table, so "total bases" cannot mean one thing to the grader and another
# to the filter.
PROP_STATS = {
    "batter_hits": ("batter", "h", "hits"),
    "batter_total_bases": ("batter", "total_bases", "total bases"),
    "batter_home_runs": ("batter", "hr", "home runs"),
    "batter_rbis": ("batter", "rbi", "RBIs"),
    "batter_runs_scored": ("batter", "r", "runs"),
    "batter_hits_runs_rbis": ("batter", "hits_runs_rbi", "hits + runs + RBIs"),
    "pitcher_strikeouts": ("pitcher", "k", "strikeouts"),
}
# Short names used in sentences: "over 1.5 total bases".
PROP_NOUN = {m: v[2] for m, v in PROP_STATS.items()}

SIDES = ("either", "home", "away", "over", "under")
SIDE_LABELS = {"either": "Either side (the conditions decide)", "home": "The home side",
               "away": "The away side", "over": "The over", "under": "The under"}


def market_kind(market: str) -> str:
    """'ml_spread' | 'total' | 'prop'."""
    if market in PROP_MARKETS:
        return "prop"
    return "total" if market == "total" else "ml_spread"


def sides_for(kinds: Sequence[str]) -> tuple:
    """The sides a rule over these market kinds may name."""
    if "prop" in kinds or "total" in kinds:
        return ("either", "over", "under")
    return ("either", "home", "away")


RANK_RULES = ("earliest_lock", "longest_price", "shortest_price", "most_books", "biggest_steam")
RANK_LABELS = {
    "earliest_lock": "The earliest game",
    "longest_price": "The longest price (the biggest underdog)",
    "shortest_price": "The shortest price (the safest-looking)",
    "most_books": "The pick the most books are quoting",
    "biggest_steam": "The pick the market moved toward the most",
}

STAKE_CHOICES = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)

COLORS = (("ember", "Ember", "#FF7A45"), ("crimson", "Crimson", "#FF3D57"), ("gold", "Gold", "#F2B84B"),
          ("lime", "Lime", "#8BD450"), ("mint", "Mint", "#3DDBA4"), ("sky", "Sky", "#4FB4FF"),
          ("violet", "Violet", "#A78BFA"), ("rose", "Rose", "#F472B6"))
BADGES = (("bone", "Bone"), ("paw", "Paw print"), ("bolt", "Bolt"), ("flame", "Flame"), ("moon", "Moon"),
          ("star", "Star"), ("crown", "Crown"), ("skull", "Skull"), ("clover", "Clover"), ("anchor", "Anchor"),
          ("diamond", "Diamond"), ("target", "Target"))
COLOR_IDS = tuple(c[0] for c in COLORS)
BADGE_IDS = tuple(b[0] for b in BADGES)

WEEKDAYS = (("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"), ("thu", "Thursday"),
            ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday"))
CMP = (("gte", "at least"), ("lte", "at most"), ("gt", "more than"), ("lt", "less than"))
CMP_TEXT = dict(CMP)
WHO_ALL = (("pick", "the team it backs"), ("opponent", "the opponent"), ("home", "the home team"),
           ("away", "the away team"), ("either", "either team"), ("both", "both teams"))
WHO_TOTAL = tuple(w for w in WHO_ALL if w[0] in ("home", "away", "either", "both"))

_MLB_TEAMS = ("ARI", "ATH", "ATL", "BAL", "BOS", "CHC", "CIN", "CLE", "COL", "CWS", "DET", "HOU", "KC",
              "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "PHI", "PIT", "SD", "SEA", "SF", "STL",
              "TB", "TEX", "TOR", "WSH")


def team_menu() -> list:
    """[{value: 'MLB:NYY', label, sport}] for the team pickers. Built from the program's own
    abbreviation tables so a code the engine cannot resolve is never offered."""
    out = []
    try:
        from src.pipeline.slate import _ABBREV_TO_NICKNAME
        for code in _MLB_TEAMS:
            key = "OAK" if code == "ATH" else code
            nick = _ABBREV_TO_NICKNAME.get(key) or _ABBREV_TO_NICKNAME.get(code) or code
            out.append({"value": f"MLB:{code}", "label": nick, "sport": "MLB"})
    except Exception:  # noqa: BLE001
        out.extend({"value": f"MLB:{c}", "label": c, "sport": "MLB"} for c in _MLB_TEAMS)
    try:
        from src.sports import nfl_teams
        for code, _full, nick in nfl_teams.TEAMS:
            out.append({"value": f"NFL:{code}", "label": nick, "sport": "NFL"})
    except Exception:  # noqa: BLE001
        pass
    return out


def team_values() -> set:
    return {t["value"] for t in team_menu()}


def team_label(value: str) -> str:
    for t in team_menu():
        if t["value"] == value:
            return t["label"]
    return value


# ---------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    name: str
    kind: str                   # choice | int | number | multi | teams | players | letter
    label: str
    choices: tuple = ()         # ((value, label), ...)
    low: float = 0
    high: float = 0
    step: float = 1
    default: Any = None


_PLAYER_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,38}[A-Za-z.]$")


def _fold_name(text: str) -> str:
    import unicodedata
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z]+", ascii_text.lower()))


def fold_player(name: str) -> str:
    """Case, accent and punctuation-blind key for matching a typed name to a prop board's name
    ('Julio Rodriguez' == 'Julio Rodríguez'; 'Jr.' and 'II' suffixes are dropped)."""
    words = [w for w in _fold_name(name).split() if w not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(words)


def _clean_param(p: Param, value: Any, *, known_players: Optional[Callable] = None) -> tuple:
    """(normalised value, error | None)."""
    if p.kind == "choice":
        allowed = [c[0] for c in p.choices]
        if value not in allowed or isinstance(value, bool):
            return None, f"must be one of {', '.join(map(str, allowed))}"
        return value, None
    if p.kind in ("int", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"must be a number from {p.low:g} to {p.high:g}"
        if value != value or not (p.low <= value <= p.high):
            return None, f"must be from {p.low:g} to {p.high:g}"
        if p.kind == "int":
            if int(value) != value:
                return None, "must be a whole number"
            return int(value), None
        steps = round((value - p.low) / p.step)
        snapped = round(p.low + steps * p.step, 4)
        return float(snapped), None
    if p.kind == "multi":
        if not isinstance(value, (list, tuple)) or not value:
            return None, "choose at least one"
        allowed = [c[0] for c in p.choices]
        if any(v not in allowed for v in value) or len(set(value)) != len(value):
            return None, f"choose from {', '.join(allowed)}"
        return [v for v in allowed if v in value], None
    if p.kind == "teams":
        if not isinstance(value, (list, tuple)) or not value or len(value) > MAX_LIST:
            return None, f"name 1 to {MAX_LIST} teams"
        valid = team_values()
        if any(v not in valid for v in value) or len(set(value)) != len(value):
            return None, "names a team that is not on the menu"
        return sorted(value), None
    if p.kind == "players":
        if not isinstance(value, (list, tuple)) or not value or len(value) > MAX_LIST:
            return None, f"name 1 to {MAX_LIST} players"
        names = []
        for v in value:
            if not isinstance(v, str):
                return None, "a player name must be text"
            v = " ".join(v.split())
            if not _PLAYER_RE.match(v):
                return None, "a player name may use only letters, spaces, apostrophes, periods and hyphens"
            names.append(v)
        if len({fold_player(n) for n in names}) != len(names):
            return None, "names the same player twice"
        if known_players is not None:
            unknown = [n for n in names if not known_players(n)]
            if unknown:
                return None, f"{unknown[0]} is not a player in our box scores; spell the name as in the box score"
        return names, None
    if p.kind == "letter":
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]", value):
            return None, "must be a single letter"
        return value.upper(), None
    return None, "unsupported parameter"


# ---------------------------------------------------------------------------
# the evaluation context
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    """One candidate pick at one lock instant, plus the point-in-time facts it may consult."""
    sport: str                              # 'MLB' | 'NFL'
    market: str
    side: str                               # home|away|over|under
    line: Optional[float]                   # the picked side's own line (spread/total/prop line)
    price: int
    n_books: int
    home_code: Optional[str]
    away_code: Optional[str]
    home_name: str = ""
    away_name: str = ""
    pick_code: Optional[str] = None         # the team the bet backs (ml/spread) or the player's team (prop)
    opp_code: Optional[str] = None
    player: Optional[str] = None
    role: Optional[str] = None              # 'favourite' | 'underdog' for ml/spread
    move: Optional[int] = None              # +1 market moved toward the pick, -1 against, 0 none, None unknown
    date: str = ""                          # Eastern slate date
    start: Any = None                       # datetime (UTC)
    lock: Any = None                        # datetime (UTC)
    game_pk: Optional[str] = None
    event_id: str = ""
    seed: str = ""                          # the hound's rule hash, so a coin flip is reproducible
    facts: Any = None                       # FactBook


def _team_for(ctx: Ctx, who: str) -> Optional[str]:
    return {"pick": ctx.pick_code, "opponent": ctx.opp_code, "home": ctx.home_code,
            "away": ctx.away_code}.get(who)


def _over_who(ctx: Ctx, who: str, test: Callable[[str], Optional[bool]]) -> Optional[bool]:
    """Apply a per-team test to 'pick', 'opponent', 'home', 'away', 'either' or 'both'."""
    if who in ("either", "both"):
        results = [test(c) if c else None for c in (ctx.home_code, ctx.away_code)]
        if who == "either":
            if any(r is True for r in results):
                return True
            return None if any(r is None for r in results) else False
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True
    code = _team_for(ctx, who)
    return test(code) if code else None


def _cmp(kind: str, left: float, right: float) -> bool:
    return {"gte": left >= right, "lte": left <= right, "gt": left > right, "lt": left < right}[kind]


# ---------------------------------------------------------------------------
# the conditions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cond:
    id: str
    label: str
    group: str
    kinds: tuple                 # market kinds it can speak about: ml_spread | total | prop
    params: tuple
    template: Callable[[Mapping, str], str]   # (params, kind) -> sentence fragment
    fn: Callable[[Mapping, Ctx], Optional[bool]]
    sports: tuple = ("MLB", "NFL")
    only_markets: tuple = ()     # restrict to these markets (e.g. spread_size -> spread)
    fun: bool = False
    unavailable: Optional[Callable[[], Optional[str]]] = None   # -> reason, or None when available
    note: str = ""               # what data it reads and how much of it exists, shown beside the condition
    check: Optional[Callable[[Mapping], Optional[str]]] = None   # cross-parameter rule -> error text | None


def _who_param(kinds_hint: str = "all") -> Param:
    return Param("who", "choice", "Which team", choices=WHO_ALL, default="pick")


def _cmp_param(default="gte") -> Param:
    return Param("cmp", "choice", "Compare", choices=CMP, default=default)


def _subject(who: str, kind: str) -> str:
    if who == "pick":
        return "the player's team" if kind == "prop" else "the team it backs"
    return dict(WHO_ALL)[who]


def _have(who: str) -> str:
    return "have" if who == "both" else "has"


def _num(v) -> str:
    return f"{v:g}"


# --- sentences ---------------------------------------------------------------------------

def _t_role(p, k): return f"the pick is the {p['value']}"
def _t_team_is(p, k):
    names = _join([team_label(v) for v in p["teams"]])
    if k == "total":
        return f"the game involves the {names}"
    return f"the team is the {names}" if k == "ml_spread" else f"the player plays for the {names}"
def _t_opponent_is(p, k): return f"the opponent is the {_join([team_label(v) for v in p['teams']])}"
def _t_player_is(p, k): return f"the player is {_join(p['players'])}"
def _t_venue(p, k): return "the player's team is playing " + ("at home" if p["value"] == "home" else "on the road")
def _t_steam(p, k):
    return ("the market has moved toward the pick since our first capture" if p["direction"] == "toward"
            else "the market has moved against the pick since our first capture")
def _t_rest(p, k): return f"{_subject(p['who'], k)} {_have(p['who'])} {CMP_TEXT[p['cmp']]} {p['value']} days of rest"
def _t_streak(p, k):
    return (f"{_subject(p['who'], k)} {'have' if p['who'] == 'both' else 'has'} "
            f"{'won' if p['kind'] == 'winning' else 'lost'} {p['value']} or more in a row")
def _t_lastn(p, k):
    return (f"{_subject(p['who'], k)} {_have(p['who'])} won {CMP_TEXT[p['cmp']]} {p['wins']} of "
            f"{'their' if p['who'] in ('both',) else 'its'} last {p['n']} games")
def _t_split(p, k):
    return (f"{_subject(p['who'], k)} {_have(p['who'])} a win rate {CMP_TEXT[p['cmp']]} {p['pct']:g}% "
            f"in games at the same kind of ground as today's (home or away; at least 8 games)")
def _t_travel(p, k):
    return f"{_subject(p['who'], k)} {'have' if p['who'] == 'both' else 'has'} travelled {CMP_TEXT[p['cmp']]} {p['miles']} miles since its last game"
def _t_dow(p, k): return "it is " + _join([dict(WEEKDAYS)[d] for d in p["days"]])
def _t_tod(p, k): return f"it is a {p['value']} game (day = before 5pm Eastern)"
def _t_temp(p, k): return f"the forecast temperature at first pitch is {CMP_TEXT[p['cmp']]} {p['value']:g} degrees F"
def _t_wind(p, k): return f"the forecast wind is {CMP_TEXT[p['cmp']]} {p['value']:g} mph"
def _t_winddir(p, k): return f"the wind is blowing {p['value']} (needs the park's verified orientation)"
def _t_roof(p, k): return {"open": "the park is open-air", "closed": "the roof is a fixed dome or likely closed",
                           "retractable": "the park has a retractable roof"}[p["value"]]
def _t_rain(p, k): return f"the forecast chance of rain is {CMP_TEXT[p['cmp']]} {p['value']}%"
def _t_spread_size(p, k): return f"the spread is {CMP_TEXT[p['cmp']]} {p['value']:g} points"
def _t_numer(p, k):
    return ("the team it backs has a gematria number closer to the date's number than its opponent's"
            if p["value"] == "closer" else
            "the team it backs has a gematria number further from the date's number than its opponent's")
def _t_moon(p, k): return f"the moon is {p['value']} (within 1.5 days of the phase)"
def _t_coin(p, k): return f"a seeded coin flip comes up in its favour {p['pct']}% of the time"
def _t_letter(p, k):
    return f"the {_of(p['of'])} name {dict(_LETTER_TESTS)[p['test']]} the letter {p['letter']}"
def _t_len(p, k): return f"the {_of(p['of'])} name has {CMP_TEXT[p['cmp']]} {p['value']} letters"
def _t_pstreak(p, k):
    one = {"hits": "hit", "home_runs": "home run", "rbis": "RBI", "runs": "run", "total_bases": "total base",
           "strikeouts": "strikeout"}[p["stat"]]
    noun = one if p["min"] == 1 else dict(_STREAK_STATS)[p["stat"]]
    each = "a" if p["min"] == 1 else f"at least {p['min']}"
    return f"the player has {each} {noun} in each of his last {p['games']} games"
def _t_pform(p, k):
    base = "above" if p["rel"] == "above" else "below"
    m = "" if not p["margin"] else f" by at least {p['margin']:g}"
    return f"the player's average over his last {p['n']} games is {base} the line{m}"
def _t_prate(p, k): return f"the player averages {CMP_TEXT[p['cmp']]} {p['value']:g} per game over the box scores on file (at least 5 games)"

def _games_window(n: int) -> str:
    return "so far this season" if not n else f"over the last {n} games"


_UNITS = (("offense", "offense (scored per game)"), ("defense", "defense (allowed per game)"))
_UNIT_NOUN = {"offense": "offense", "defense": "defense"}
_UNIT_OTHER = {"offense": "defense", "defense": "offense"}
_H2H_WINDOWS = (("all", "all meetings on file"), ("season", "this season only"))
_GROUNDS = (("today", "the same kind of ground as today's game"), ("home", "at home"), ("road", "on the road"))
_END = (("top", "in the top"), ("bottom", "in the bottom"))


def _t_h2h(p, k):
    window = "this season only" if p["window"] == "season" else "all meetings on file"
    return (f"{_subject(p['who'], k)} {_have(p['who'])} won {CMP_TEXT[p['cmp']]} {p['wins']} of the last "
            f"{p['n']} meetings between these two clubs ({window})")


def _t_venue_record(p, k):
    ground = {"today": "in games at the same kind of ground as today's (home or away)", "home": "at home",
              "road": "on the road"}[p["ground"]]
    return (f"{_subject(p['who'], k)} {_have(p['who'])} a win rate {CMP_TEXT[p['cmp']]} {p['pct']:g}% {ground} "
            f"this season (at least {MIN_VENUE_GAMES} games)")


def _t_scoring(p, k):
    plural = p["who"] == "both"
    verb = (("score" if plural else "scores") if p["unit"] == "offense" else ("allow" if plural else "allows"))
    return (f"{_subject(p['who'], k)} {verb} {CMP_TEXT[p['cmp']]} {p['value']:g} runs or points per game "
            f"{_games_window(p['n'])}")


def _t_league_rank(p, k):
    which = "best" if p["end"] == "top" else "worst"
    return (f"the {_UNIT_NOUN[p['unit']]} of {_subject(p['who'], k)} ranks in the {p['end']} {p['places']} of the "
            f"league (the {which} {p['places']} clubs for runs or points {'scored' if p['unit'] == 'offense' else 'allowed'} "
            f"per game, {_games_window(p['n'])})")


def _t_edge(p, k):
    return (f"the {_UNIT_NOUN[p['unit']]} of {_subject(p['who'], k)} ranks at least {p['gap']} "
            f"{'place' if p['gap'] == 1 else 'places'} better than the {_UNIT_OTHER[p['unit']]} of the other team in the "
            f"league (runs or points per game, {_games_window(p['n'])})")


_LETTER_TESTS = (("starts_with", "starts with"), ("ends_with", "ends with"), ("contains", "contains"))
_OF = (("pick", "pick's team"), ("opponent", "opponent's team"), ("home", "home team"), ("away", "away team"),
       ("player", "player"))
_STREAK_STATS = (("hits", "hits"), ("home_runs", "home runs"), ("rbis", "RBIs"), ("runs", "runs"),
                 ("total_bases", "total bases"), ("strikeouts", "strikeouts"))


def _of(v: str) -> str:
    return dict(_OF)[v]


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


# --- evaluation ----------------------------------------------------------------------------

def _f_role(p, c): return None if c.role is None else c.role == p["value"]
def _f_team_is(p, c):
    teams = set(p["teams"])
    if c.market == "total":
        return any(f"{c.sport}:{x}" in teams for x in (c.home_code, c.away_code) if x)
    return None if not c.pick_code else f"{c.sport}:{c.pick_code}" in teams
def _f_opponent_is(p, c):
    return None if not c.opp_code else f"{c.sport}:{c.opp_code}" in set(p["teams"])
def _f_player_is(p, c):
    if not c.player:
        return None
    return fold_player(c.player) in {fold_player(n) for n in p["players"]}
def _f_venue(p, c):
    if c.market == "total" or not c.pick_code:
        return None
    return (c.pick_code == c.home_code) == (p["value"] == "home") if c.pick_code in (c.home_code, c.away_code) else None
def _f_steam(p, c):
    if c.move is None:
        return None
    return c.move == (1 if p["direction"] == "toward" else -1)
def _f_rest(p, c):
    return _over_who(c, p["who"], lambda t: _opt(c.facts.rest_days(c.sport, t, c.date, c.lock),
                                                  lambda v: _cmp(p["cmp"], v, p["value"])))
def _f_streak(p, c):
    def test(t):
        s = c.facts.streak(c.sport, t, c.date, c.lock)
        if s is None:
            return None
        return s >= p["value"] if p["kind"] == "winning" else -s >= p["value"]
    return _over_who(c, p["who"], test)
def _f_lastn(p, c):
    return _over_who(c, p["who"], lambda t: _opt(c.facts.last_n_wins(c.sport, t, p["n"], c.date, c.lock),
                                                  lambda v: _cmp(p["cmp"], v, p["wins"])))
def _f_split(p, c):
    def test(t):
        at_home = t == c.home_code
        got = c.facts.split(c.sport, t, at_home, c.date, c.lock)
        if got is None or got[1] < 8:
            return None
        return _cmp(p["cmp"], 100.0 * got[0] / got[1], p["pct"])
    return _over_who(c, p["who"], test)
def _f_travel(p, c):
    return _over_who(c, p["who"], lambda t: _opt(
        c.facts.travel_miles(c.sport, t, c.home_code, c.date, c.lock), lambda v: _cmp(p["cmp"], v, p["miles"])))
_DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
def _f_dow(p, c):
    from datetime import date as _d
    try:
        return _DOW[_d.fromisoformat(c.date).weekday()] in p["days"]
    except ValueError:
        return None
def _f_tod(p, c):
    if c.start is None:
        return None
    from datetime import timezone
    from src.data.eastern import eastern
    hour = c.start.astimezone(eastern()).hour
    return (hour < 17) == (p["value"] == "day")
def _wx(c):
    return c.facts.weather(c.game_pk, c.lock, c.start) if c.sport == "MLB" else None
def _f_temp(p, c):
    w = _wx(c)
    return None if not w or w.get("temp_f") is None else _cmp(p["cmp"], w["temp_f"], p["value"])
def _f_wind(p, c):
    w = _wx(c)
    return None if not w or w.get("wind_mph") is None else _cmp(p["cmp"], w["wind_mph"], p["value"])
def _f_winddir(p, c):
    w = _wx(c)
    if not w:
        return None
    direction = c.facts.wind_direction(c.home_code, w)
    return None if direction is None else direction == p["value"]
def _f_roof(p, c):
    w = _wx(c)
    if not w or not w.get("roof"):
        return None
    roof = w["roof"]
    mapped = {"open": "open", "fixed": "closed", "retractable": "retractable"}.get(roof)
    return None if mapped is None else mapped == p["value"]
def _f_rain(p, c):
    w = _wx(c)
    return None if not w or w.get("precip_probability_pct") is None else _cmp(p["cmp"], w["precip_probability_pct"], p["value"])
def _f_spread_size(p, c):
    return None if c.line is None or c.market != "spread" else _cmp(p["cmp"], abs(c.line), p["value"])
def _f_numer(p, c):
    from src.hounds.pack.numerology_newfie import date_number, digital_root, gematria
    if not (c.pick_code and c.opp_code and c.date):
        return None
    pick_name = c.home_name if c.pick_code == c.home_code else c.away_name
    opp_name = c.away_name if c.pick_code == c.home_code else c.home_name
    d = date_number(c.date)
    dp, do = abs(digital_root(gematria(pick_name)) - d), abs(digital_root(gematria(opp_name)) - d)
    if dp == do:
        return None
    return (dp < do) == (p["value"] == "closer")
def _f_moon(p, c):
    if c.start is None:
        return None
    from src.hounds.pack.lunar_lab import phase
    return phase(c.start) == p["value"]
def _f_coin(p, c):
    digest = hashlib.sha256(f"{c.seed}|{c.event_id}|{c.market}|{c.player or ''}|{c.side}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2 ** 32 < p["pct"] / 100.0
def _name_of(c: Ctx, of: str) -> Optional[str]:
    if of == "player":
        return c.player
    code = {"pick": c.pick_code, "opponent": c.opp_code, "home": c.home_code, "away": c.away_code}.get(of)
    if not code:
        return None
    return c.home_name if code == c.home_code else c.away_name
def _f_letter(p, c):
    name = _name_of(c, p["of"])
    if not name:
        return None
    # A team name is tested on its nickname (the last word): "Boston Red Sox" -> "Sox" would misread two-word
    # clubs, so the full name is used and "starts with" means the city/first word.
    s = _fold_name(name).replace(" ", "")
    ch = p["letter"].lower()
    return {"starts_with": s.startswith(ch), "ends_with": s.endswith(ch), "contains": ch in s}[p["test"]]
def _f_len(p, c):
    name = _name_of(c, p["of"])
    return None if not name else _cmp(p["cmp"], len(_fold_name(name).replace(" ", "")), p["value"])
def _f_pstreak(p, c):
    if not c.player:
        return None
    kind = "pitcher" if p["stat"] == "strikeouts" else "batter"
    key = {"hits": "h", "home_runs": "hr", "rbis": "rbi", "runs": "r", "total_bases": "total_bases",
           "strikeouts": "k"}[p["stat"]]
    series = c.facts.player_series(c.player, kind, key, c.date)
    if series is None or len(series) < p["games"]:
        return None
    return all(v >= p["min"] for v in series[-p["games"]:])
def _f_pform(p, c):
    stat = PROP_STATS.get(c.market)
    if not c.player or not stat or c.line is None:
        return None
    series = c.facts.player_series(c.player, stat[0], stat[1], c.date)
    if series is None or len(series) < p["n"]:
        return None
    avg = sum(series[-p["n"]:]) / p["n"]
    return avg >= c.line + p["margin"] if p["rel"] == "above" else avg <= c.line - p["margin"]
def _f_prate(p, c):
    stat = PROP_STATS.get(c.market)
    if not c.player or not stat:
        return None
    series = c.facts.player_series(c.player, stat[0], stat[1], c.date)
    if series is None or len(series) < 5:
        return None
    return _cmp(p["cmp"], sum(series) / len(series), p["value"])


def _opt(value, fn):
    return None if value is None else fn(value)


MIN_VENUE_GAMES = 5            # a home or road record needs at least this many games on that ground


def _other_club(c: Ctx, team: str) -> Optional[str]:
    """The club on the other side of today's game from `team`."""
    if team == c.home_code:
        return c.away_code
    if team == c.away_code:
        return c.home_code
    return None


def _f_h2h(p, c):
    def test(t):
        opp = _other_club(c, t)
        got = c.facts.head_to_head(c.sport, t, opp, p["n"], p["window"], c.date, c.lock) if opp else None
        return _opt(got, lambda g: _cmp(p["cmp"], g[0], p["wins"]))
    return _over_who(c, p["who"], test)


def _f_venue_record(p, c):
    def test(t):
        if p["ground"] == "today":
            if t not in (c.home_code, c.away_code):
                return None
            at_home = t == c.home_code
        else:
            at_home = p["ground"] == "home"
        got = c.facts.season_split(c.sport, t, at_home, c.date, c.lock)
        if got is None or got[1] < MIN_VENUE_GAMES:
            return None
        return _cmp(p["cmp"], 100.0 * got[0] / got[1], p["pct"])
    return _over_who(c, p["who"], test)


def _f_scoring(p, c):
    key = "pf" if p["unit"] == "offense" else "pa"
    return _over_who(c, p["who"], lambda t: _opt(c.facts.scoring(c.sport, t, p["n"], c.date, c.lock),
                                                  lambda s: _cmp(p["cmp"], s[key], p["value"])))


def _f_league_rank(p, c):
    def test(t):
        got = c.facts.scoring_rank(c.sport, t, p["unit"], p["n"], c.date, c.lock)
        if got is None:
            return None
        rank, clubs = got
        return rank <= p["places"] if p["end"] == "top" else rank > clubs - p["places"]
    return _over_who(c, p["who"], test)


def _f_edge(p, c):
    def test(t):
        other = _other_club(c, t)
        if not other:
            return None
        mine = c.facts.scoring_rank(c.sport, t, p["unit"], p["n"], c.date, c.lock)
        theirs = c.facts.scoring_rank(c.sport, other, _UNIT_OTHER[p["unit"]], p["n"], c.date, c.lock)
        if mine is None or theirs is None:
            return None
        return theirs[0] - mine[0] >= p["gap"]
    return _over_who(c, p["who"], test)


def _check_h2h(item: Mapping) -> Optional[str]:
    if item["wins"] > item["n"]:
        return "wins cannot be more than the number of meetings counted"
    return None


def _wind_direction_unavailable() -> Optional[str]:
    try:
        from src.data import parks
        if parks.parks_missing_orientation():
            return ("wind direction needs each ballpark's verified compass bearing, which is not on file "
                    "yet (src/data/parks.py leaves it empty rather than guess). Use wind speed instead.")
    except Exception:  # noqa: BLE001
        return "wind direction is not available"
    return None


_WHO = Param("who", "choice", "Which team", choices=WHO_ALL, default="pick")
_C = lambda: _cmp_param()  # noqa: E731


def _P(name, kind, label, **kw):
    return Param(name, kind, label, **kw)


CONDITIONS: tuple = (
    # --- the pick ---------------------------------------------------------------------------
    Cond("role", "Favourite or underdog", "The pick", ("ml_spread",),
         (_P("value", "choice", "The pick is", choices=(("favourite", "the favourite"), ("underdog", "the underdog")), default="underdog"),),
         _t_role, _f_role),
    Cond("team_is", "A specific team", "The pick", ("ml_spread", "total", "prop"),
         (_P("teams", "teams", "Teams", default=[]),), _t_team_is, _f_team_is),
    Cond("opponent_is", "Against a specific team", "The pick", ("ml_spread", "prop"),
         (_P("teams", "teams", "Teams", default=[]),), _t_opponent_is, _f_opponent_is),
    Cond("steam", "Line movement since open", "The pick", ("ml_spread", "total", "prop"),
         (_P("direction", "choice", "The market has moved", choices=(("toward", "toward the pick"), ("against", "against the pick")), default="toward"),),
         _t_steam, _f_steam),
    Cond("spread_size", "Size of the spread", "The pick", ("ml_spread",),
         (_cmp_param("lte"), _P("value", "number", "Points", low=0, high=30, step=0.5, default=7)),
         _t_spread_size, _f_spread_size, only_markets=("spread",)),
    # --- form and schedule --------------------------------------------------------------------
    Cond("rest_days", "Days of rest", "Form and schedule", ("ml_spread", "total", "prop"),
         (_WHO, _cmp_param(), _P("value", "int", "Days (MLB: days off since the last game; NFL: days between games)", low=0, high=14, default=2)),
         _t_rest, _f_rest),
    Cond("streak", "Winning or losing streak", "Form and schedule", ("ml_spread", "total", "prop"),
         (_WHO, _P("kind", "choice", "Streak", choices=(("winning", "winning"), ("losing", "losing")), default="winning"),
          _P("value", "int", "Games in a row (at least)", low=1, high=15, default=3)),
         _t_streak, _f_streak),
    Cond("last_n_wins", "Wins in the last N games", "Form and schedule", ("ml_spread", "total", "prop"),
         (_WHO, _P("n", "int", "Last N games", low=3, high=20, default=10), _cmp_param(),
          _P("wins", "int", "Wins", low=0, high=20, default=7)),
         _t_lastn, _f_lastn),
    Cond("split_pct", "Home or road win rate", "Form and schedule", ("ml_spread", "total", "prop"),
         (_WHO, _cmp_param(), _P("pct", "number", "Win rate (%)", low=0, high=100, step=5, default=60)),
         _t_split, _f_split),
    Cond("travel_miles", "Miles travelled since the last game", "Form and schedule", ("ml_spread", "total", "prop"),
         (_WHO, _cmp_param(), _P("miles", "int", "Miles", low=0, high=3000, default=1000)),
         _t_travel, _f_travel, sports=("MLB",)),
    Cond("day_of_week", "Day of the week", "Form and schedule", ("ml_spread", "total", "prop"),
         (_P("days", "multi", "Days", choices=WEEKDAYS, default=["sat", "sun"]),), _t_dow, _f_dow),
    Cond("time_of_day", "Day or night game", "Form and schedule", ("ml_spread", "total", "prop"),
         (_P("value", "choice", "It is a", choices=(("day", "day game"), ("night", "night game")), default="night"),),
         _t_tod, _f_tod),
    # --- matchups and team strength ------------------------------------------------------------------
    Cond("head_to_head", "Head-to-head record", "Matchups and team strength", ("ml_spread", "total", "prop"),
         (_WHO, _P("n", "int", "Last N meetings with this opponent", low=1, high=10, default=5), _cmp_param(),
          _P("wins", "int", "Wins", low=0, high=10, default=3),
          _P("window", "choice", "Meetings counted", choices=_H2H_WINDOWS, default="all")),
         _t_h2h, _f_h2h, check=_check_h2h,
         note=("The last N meetings between the two clubs on file; it needs N meetings or it does not apply. NFL: games "
               "since 2021. MLB: 2023 to 2025 and games since August 28, 2026 (January to August 2026 results are held "
               "back, so a recent meeting from that stretch is not seen). 'This season only' is shorter still.")),
    Cond("venue_record", "Home or road record this season", "Matchups and team strength", ("ml_spread", "total", "prop"),
         (_WHO, _P("ground", "choice", "Record", choices=_GROUNDS, default="today"), _cmp_param(),
          _P("pct", "number", "Win rate (%)", low=0, high=100, step=5, default=60)),
         _t_venue_record, _f_venue_record,
         note=(f"This season's win rate at home or on the road; it needs {MIN_VENUE_GAMES} games on that ground. "
               "MLB games on file start August 28, 2026.")),
    Cond("scoring_rate", "Runs or points per game", "Matchups and team strength", ("ml_spread", "total", "prop"),
         (_WHO, _P("unit", "choice", "Which side of the ball", choices=_UNITS, default="offense"),
          _P("n", "int", "Last N games (0 = the whole season so far)", low=0, high=20, default=10), _cmp_param(),
          _P("value", "number", "Runs (MLB) or points (NFL) per game", low=0, high=60, step=0.1, default=4.5)),
         _t_scoring, _f_scoring,
         note=("Runs (MLB) or points (NFL) per game from final scores on file; it needs N games, or "
               "5 games for the whole season. MLB games on file start August 28, 2026.")),
    Cond("league_rank", "League rank in scoring or defence", "Matchups and team strength", ("ml_spread", "total", "prop"),
         (_WHO, _P("unit", "choice", "Which side of the ball", choices=_UNITS, default="offense"),
          _P("end", "choice", "Ranks", choices=_END, default="top"),
          _P("places", "int", "Places in the league", low=1, high=15, default=10),
          _P("n", "int", "Last N games (0 = the whole season so far)", low=0, high=20, default=10)),
         _t_league_rank, _f_league_rank,
         note=("Ranks every club with enough games on file by runs or points scored (offense) or allowed (defense) per "
               "game; clubs level on the figure share a rank. MLB games on file start August 28, 2026.")),
    Cond("matchup_edge", "Offense against the other team's defense", "Matchups and team strength",
         ("ml_spread", "total", "prop"),
         (_WHO, _P("unit", "choice", "Compare its", choices=(("offense", "offense against the other team's defense"),
                                                             ("defense", "defense against the other team's offense")),
                   default="offense"),
          _P("gap", "int", "Ranks at least this many places better", low=1, high=15, default=1),
          _P("n", "int", "Last N games (0 = the whole season so far)", low=0, high=20, default=10)),
         _t_edge, _f_edge,
         note=("Compares league ranks: one club's offense (most runs or points scored) against the other club's defense "
               "(fewest allowed), or the reverse. MLB games on file start August 28, 2026.")),
    # --- weather ------------------------------------------------------------------------------------
    Cond("temperature", "Temperature", "Weather", ("ml_spread", "total", "prop"),
         (_cmp_param(), _P("value", "number", "Degrees F", low=20, high=115, step=1, default=80)),
         _t_temp, _f_temp, sports=("MLB",)),
    Cond("wind_speed", "Wind speed", "Weather", ("ml_spread", "total", "prop"),
         (_cmp_param(), _P("value", "number", "Miles per hour", low=0, high=40, step=1, default=10)),
         _t_wind, _f_wind, sports=("MLB",)),
    Cond("wind_direction", "Wind blowing out or in", "Weather", ("ml_spread", "total", "prop"),
         (_P("value", "choice", "Blowing", choices=(("out", "out toward center field"), ("in", "in from center field")), default="out"),),
         _t_winddir, _f_winddir, sports=("MLB",), unavailable=_wind_direction_unavailable),
    Cond("roof", "Roof", "Weather", ("ml_spread", "total", "prop"),
         (_P("value", "choice", "The park", choices=(("open", "is open-air"), ("closed", "has a fixed roof"), ("retractable", "has a retractable roof")), default="open"),),
         _t_roof, _f_roof, sports=("MLB",)),
    Cond("rain_chance", "Chance of rain", "Weather", ("ml_spread", "total", "prop"),
         (_cmp_param("lte"), _P("value", "int", "Percent", low=0, high=100, default=20)),
         _t_rain, _f_rain, sports=("MLB",)),
    # --- players (props) ----------------------------------------------------------------------
    Cond("player_is", "A specific player", "Player props", ("prop",),
         (_P("players", "players", "Players", default=[]),), _t_player_is, _f_player_is, sports=("MLB",)),
    Cond("venue", "Player's team at home or away", "Player props", ("prop",),
         (_P("value", "choice", "The player's team is", choices=(("home", "at home"), ("away", "on the road")), default="home"),),
         _t_venue, _f_venue, sports=("MLB",)),
    Cond("player_streak", "Player streak", "Player props", ("prop",),
         (_P("stat", "choice", "Stat", choices=_STREAK_STATS, default="hits"),
          _P("games", "int", "In each of his last N games", low=1, high=10, default=3),
          _P("min", "int", "At least this many each game", low=1, high=4, default=1)),
         _t_pstreak, _f_pstreak, sports=("MLB",)),
    Cond("player_form", "Recent average against the line", "Player props", ("prop",),
         (_P("n", "int", "Last N games", low=3, high=15, default=7),
          _P("rel", "choice", "The average is", choices=(("above", "above the line"), ("below", "below the line")), default="above"),
          _P("margin", "number", "By at least", low=0, high=3, step=0.05, default=0.0)),
         _t_pform, _f_pform, sports=("MLB",)),
    Cond("player_rate", "Average per game (box scores on file)", "Player props", ("prop",),
         (_cmp_param(), _P("value", "number", "Per game", low=0, high=10, step=0.05, default=1.0)),
         _t_prate, _f_prate, sports=("MLB",)),
    # --- for fun -----------------------------------------------------------------------------------
    Cond("numerology", "Numerology", "For fun", ("ml_spread",),
         (_P("value", "choice", "The team it backs is", choices=(("closer", "closer to the date's number"), ("further", "further from the date's number")), default="closer"),),
         _t_numer, _f_numer, fun=True),
    Cond("moon_phase", "Moon phase", "For fun", ("ml_spread", "total", "prop"),
         (_P("value", "choice", "The moon is", choices=(("full", "full"), ("new", "new"), ("other", "neither")), default="full"),),
         _t_moon, _f_moon, fun=True),
    Cond("coin_flip", "Coin flip", "For fun", ("ml_spread", "total", "prop"),
         (_P("pct", "int", "Chance it comes up (%)", low=5, high=95, default=50),), _t_coin, _f_coin, fun=True),
    Cond("name_letter", "Letters in a name", "For fun", ("ml_spread", "total", "prop"),
         (_P("of", "choice", "Whose name", choices=_OF, default="pick"),
          _P("test", "choice", "The name", choices=_LETTER_TESTS, default="starts_with"),
          _P("letter", "letter", "Letter", default="S")), _t_letter, _f_letter, fun=True),
    Cond("name_length", "Length of a name", "For fun", ("ml_spread", "total", "prop"),
         (_P("of", "choice", "Whose name", choices=_OF, default="pick"), _cmp_param(),
          _P("value", "int", "Letters", low=3, high=30, default=10)), _t_len, _f_len, fun=True),
)
BY_ID = {c.id: c for c in CONDITIONS}


def _of_choices(kind: str) -> tuple:
    if kind == "prop":
        return tuple(o for o in _OF if o[0] in ("pick", "opponent", "home", "away", "player"))
    if kind == "total":
        return tuple(o for o in _OF if o[0] in ("home", "away"))
    return tuple(o for o in _OF if o[0] != "player")


def default_instance(cond_id: str) -> dict:
    cond = BY_ID[cond_id]
    out = {"id": cond_id}
    for p in cond.params:
        out[p.name] = list(p.default) if isinstance(p.default, list) else p.default
    return out


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate_condition(raw: Any, *, kinds: Sequence[str], markets: Sequence[str], sports: Sequence[str],
                       path: str, errors: dict, known_players: Optional[Callable] = None) -> Optional[dict]:
    """A normalised condition dict, or None with the reasons added to `errors` under `path`.
    Unknown parameters are refused, not dropped: a field the engine does not read must not be
    published as if it were part of the rule."""
    if not isinstance(raw, Mapping):
        errors[path] = "a condition must be an object"
        return None
    cid = raw.get("id")
    cond = BY_ID.get(cid) if isinstance(cid, str) else None
    if cond is None:
        errors[path] = f"unknown condition {str(cid)[:40]!r}; it is not on the menu"
        return None
    where = f"{path}.{cid}"
    ok = True
    extra = set(raw) - {"id"} - {p.name for p in cond.params}
    for key in sorted(extra, key=str):
        errors[f"{where}.{str(key)[:30]}"] = "is not a parameter of this condition"
        ok = False
    bad_kind = [k for k in kinds if k not in cond.kinds]
    if bad_kind:
        errors[where] = f"{cond.label} cannot be used with {', '.join(MARKET_LABELS[m] for m in markets if market_kind(m) in bad_kind)}"
        return None
    if cond.only_markets and any(m not in cond.only_markets for m in markets):
        errors[where] = f"{cond.label} only applies to {', '.join(cond.only_markets)} rules"
        return None
    if not any(s in cond.sports for s in sports):
        errors[where] = f"{cond.label} is not available for {' / '.join(sports)}"
        return None
    if any(s not in cond.sports for s in sports):
        errors[where] = f"{cond.label} works for {' / '.join(cond.sports)} only; give the other sport its own rule"
        return None
    if cond.unavailable is not None:
        reason = cond.unavailable()
        if reason:
            errors[where] = reason
            return None
    out = {"id": cid}
    for p in cond.params:
        if p.name not in raw:
            if p.default is None or (isinstance(p.default, list) and not p.default):
                errors[f"{where}.{p.name}"] = "is required"
                ok = False
                continue
            value = list(p.default) if isinstance(p.default, list) else p.default
        else:
            value = raw[p.name]
        # 'who' and 'of' offer different choices on a total
        param = p
        if p.name == "who":
            param = Param(p.name, "choice", p.label, choices=WHO_TOTAL if "total" in kinds else WHO_ALL)
        elif p.name == "of":
            param = Param(p.name, "choice", p.label,
                          choices=_of_choices("total" if "total" in kinds else kinds[0]))
        clean, err = _clean_param(param, value, known_players=known_players)
        if err:
            errors[f"{where}.{p.name}"] = err
            ok = False
        else:
            out[p.name] = clean
    if ok and cond.check is not None:
        problem = cond.check(out)
        if problem:
            errors[where] = problem
            ok = False
    return out if ok else None


def validate_tree(raw: Any, *, kinds: Sequence[str], markets: Sequence[str], sports: Sequence[str],
                  path: str, errors: dict, depth: int = 1, counter: Optional[list] = None,
                  known_players: Optional[Callable] = None) -> Optional[dict]:
    """Normalise a `when` tree. A bare condition is wrapped as an `all` group. Returns None for no
    tree (and for a tree with errors, which are in `errors`)."""
    counter = counter if counter is not None else [0]
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        errors[path] = "must be a group like {\"op\": \"all\", \"items\": [...]}"
        return None
    if "id" in raw:                              # a lone condition
        raw = {"op": "all", "items": [raw]}
    extra = set(raw) - {"op", "items"}
    if extra:
        errors[path] = f"unknown keys {sorted(map(str, extra))[:3]}"
        return None
    op = raw.get("op", "all")
    items = raw.get("items", [])
    if op not in ("all", "any"):
        errors[f"{path}.op"] = "must be 'all' (AND) or 'any' (OR)"
        return None
    if not isinstance(items, (list, tuple)):
        errors[f"{path}.items"] = "must be a list"
        return None
    if depth > MAX_DEPTH:
        errors[path] = f"groups nest at most {MAX_DEPTH} deep"
        return None
    out_items = []
    for i, item in enumerate(items):
        sub = f"{path}[{i}]"
        if isinstance(item, Mapping) and "id" not in item and ("items" in item or "op" in item):
            node = validate_tree(item, kinds=kinds, markets=markets, sports=sports, path=sub, errors=errors,
                                 depth=depth + 1, counter=counter, known_players=known_players)
            if node is not None and node["items"]:
                out_items.append(node)
        else:
            counter[0] += 1
            if counter[0] > MAX_CONDITIONS:
                errors[path] = f"a rule may have at most {MAX_CONDITIONS} conditions"
                return None
            node = validate_condition(item, kinds=kinds, markets=markets, sports=sports, path=sub,
                                      errors=errors, known_players=known_players)
            if node is not None:
                out_items.append(node)
    return {"op": op, "items": out_items} if out_items else None


def count_conditions(tree: Optional[Mapping]) -> int:
    if not tree:
        return 0
    return sum(count_conditions(i) if "items" in i else 1 for i in tree["items"])


def walk(tree: Optional[Mapping]):
    """Every leaf condition in the tree."""
    if not tree:
        return
    for item in tree["items"]:
        if "items" in item:
            yield from walk(item)
        else:
            yield item


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

def evaluate_tree(tree: Optional[Mapping], ctx: Ctx, unknown: Optional[list] = None) -> bool:
    """True when the tree holds. None (unknown input) counts as not met, and the condition id goes
    into `unknown` so the engine can report it. An empty tree always holds."""
    if not tree:
        return True
    results = []
    for item in tree["items"]:
        if "items" in item:
            results.append(evaluate_tree(item, ctx, unknown))
            continue
        cond = BY_ID[item["id"]]
        try:
            value = cond.fn(item, ctx)
        except Exception:  # noqa: BLE001 -- a broken fact source must not turn into a bet
            value = None
        if value is None and unknown is not None:
            unknown.append(item["id"])
        results.append(bool(value))
    return all(results) if tree["op"] == "all" else any(results)


# ---------------------------------------------------------------------------
# English
# ---------------------------------------------------------------------------

def condition_text(item: Mapping, kind: str) -> str:
    cond = BY_ID[item["id"]]
    return cond.template(item, kind)


def tree_text(tree: Optional[Mapping], kind: str, *, top: bool = True) -> str:
    """'a and b', 'a or b', with nested groups bracketed in words ('both ... and ...' / 'either ...
    or ...') so the sentence cannot be misread."""
    if not tree or not tree["items"]:
        return ""
    parts = []
    for item in tree["items"]:
        if "items" in item:
            parts.append(("(" + tree_text(item, kind, top=False) + ")"))
        else:
            parts.append(condition_text(item, kind))
    if len(parts) == 1:
        return parts[0]
    word = " and " if tree["op"] == "all" else " or "
    if len(parts) == 2:
        return word.join(parts)
    return ", ".join(parts[:-1]) + "," + word + parts[-1]


# ---------------------------------------------------------------------------
# the menu
# ---------------------------------------------------------------------------

def menu_conditions() -> list:
    out = []
    for cond in CONDITIONS:
        reason = cond.unavailable() if cond.unavailable else None
        params = []
        for p in cond.params:
            item = {"name": p.name, "kind": p.kind, "label": p.label}
            if p.kind == "choice" or p.kind == "multi":
                item["choices"] = [{"value": v, "label": l} for v, l in p.choices]
            if p.kind in ("int", "number"):
                item.update({"min": p.low, "max": p.high, "step": p.step})
            if p.kind == "teams":
                item["max"] = MAX_LIST
            if p.kind == "players":
                item["max"] = MAX_LIST
            item["default"] = list(p.default) if isinstance(p.default, list) else p.default
            params.append(item)
        out.append({"id": cond.id, "label": cond.label, "group": cond.group, "kinds": list(cond.kinds),
                    "sports": list(cond.sports), "only_markets": list(cond.only_markets), "fun": cond.fun,
                    "params": params, "available": reason is None, "unavailable_reason": reason,
                    "note": cond.note})
    return out
