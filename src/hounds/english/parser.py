"""The free, deterministic English -> spec parser.

HOW IT READS
------------
The text is lower-cased and ASCII-folded, split into rule segments (sentence ends, and "and bet ...",
"also back ..."), and each segment is read by a fixed list of patterns. A pattern that fires CONSUMES
its words, so a later, looser pattern cannot read them again ("hit in 3 straight games" is a streak,
not the hits market). Words left over after every pattern has run are reported as NOT understood,
verbatim, never quietly dropped. Words that carry no rule ("bet", "the", "games", "when") are
ignored.

WHAT IT RETURNS (and what it never does)
----------------------------------------
{spec, draft, understood, not_understood, assumed}. `understood` pairs each phrase with the meaning it
was given; `assumed` lists every default it had to pick (no market named: moneyline) so the person sees
it; `spec` is the draft after the SAME `user_spec.validate_spec` every form post goes through (name left
blank for the person to choose), or None with the reasons in `not_understood`. A condition the menu
refuses (wind direction while no park bearing is on file, a favourite on a player prop) is reported as
not understood WITH the reason, not silently omitted. Nothing is guessed: a stat is never inferred for
a named player, and no number is invented.

"FADE"
------
"Fade X" means back the other side, so every pick-relative thing in the segment is inverted: home <->
away, over <-> under, favourite <-> underdog, "the team" <-> "the opponent", steam toward <-> against.
That keeps "fade teams after 3 straight wins" one honest rule: the opponent has won 3 straight.

MATCHUPS AND TEAM STRENGTH (2026-10-19)
---------------------------------------
A member typed "use statistics, previous head-to-head matchups, previous matchups as in last five games,
use home advantage and away games data matched with offensive and defensive stats" and the parser read one
stray word. Those ideas are conditions now (head-to-head record, home or road record, runs or points per
game, league rank, offense against the other team's defense) and the parser reads them. A phrase that names
the idea but no number ("head-to-head", "home advantage", "last five games") is read with a stated default and
the default is listed under `assumed`, so the person sees it and changes it on the card; a number is never
invented silently. What it still cannot read comes back with `suggestions`: a wording the parser DOES read, for
the common ideas (head-to-head, home advantage, offense vs defense, "best teams"), or the plain fact that the
rules have no such stat yet (starting pitchers, injuries, lineups).

Stdlib only; no network; no clock.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec

MAX_TEXT = 600

_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
              "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}
_PLACE = "§"           # consumed-word marker

# Words that carry no rule. Anything else left over is reported.
_FILLER = frozenset("""
a an the and or but also plus then so only just any all every each of to at for by from per on in with as
is are was were be been being has have had having it its it's they they're theyre their them theirs we i my
me you your he he's his him she her when whenever if while where which that this those these there than
bet bets betting back backing take takes taking play plays playing pick picks make games game team teams
side sides club clubs dog dogs please want like would should will can get gets going lets let's let do does
always never ever really very some more most up out off over under about around when's whats what's
day days night both either one i'd ill i'll go goes pitcher pitchers batter batters hitter hitters player players
use uses using statistics statistic stats data matched matching based consider considering factor factors
""".split()) - {"over", "under", "out", "off", "day", "days", "night", "both", "either", "more", "most", "up"}

_CMP_WORDS = {
    "at least": "gte", "no less than": "gte", "no fewer than": "gte", "or more": "gte", "minimum": "gte",
    "at most": "lte", "no more than": "lte", "up to": "lte", "or fewer": "lte", "or less": "lte", "maximum": "lte",
    "more than": "gt", "greater than": "gt", "over": "gt", "above": "gt", "higher than": "gt", "longer than": "gt",
    "less than": "lt", "fewer than": "lt", "under": "lt", "below": "lt", "lower than": "lt", "shorter than": "lt",
    "warmer than": "gt", "hotter than": "gt", "colder than": "lt", "cooler than": "lt",
}
_CMP_RE = "|".join(sorted((re.escape(k) for k in _CMP_WORDS), key=len, reverse=True))

_SUBJ = (r"(?P<subj>the opponents?|their opponents?|opposing (?:team|teams)|the other team|the home team|"
         r"the away team|the road team|the visitors?|both teams|either team|they|the team|teams?|it)")


def _who(subj: Optional[str], default: str = "pick") -> str:
    s = (subj or "").lower()
    if "opponent" in s or "opposing" in s or "other team" in s:
        return "opponent"
    if "home" in s:
        return "home"
    if "away" in s or "road" in s or "visitor" in s:
        return "away"
    if "both" in s:
        return "both"
    if "either" in s:
        return "either"
    return default


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def normalise(text: str) -> str:
    t = _fold(text).lower()
    t = (t.replace("’", "'").replace("`", "'").replace("−", "-").replace("–", "-")
         .replace("—", "-"))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\b(" + "|".join(_NUM_WORDS) + r")\b", lambda m: _NUM_WORDS[m.group(1)], t)
    return t.strip()


# ---------------------------------------------------------------------------
# teams
# ---------------------------------------------------------------------------

_MLB_CITY = {"ARI": ("arizona",), "ATH": ("oakland", "sacramento"), "ATL": ("atlanta",), "BAL": ("baltimore",),
             "BOS": ("boston",), "CHC": ("chicago",), "CIN": ("cincinnati",), "CLE": ("cleveland",),
             "COL": ("colorado",), "CWS": ("chicago",), "DET": ("detroit",), "HOU": ("houston",),
             "KC": ("kansas city",), "LAA": ("los angeles", "la", "anaheim"), "LAD": ("los angeles", "la"),
             "MIA": ("miami",), "MIL": ("milwaukee",), "MIN": ("minnesota",), "NYM": ("new york", "ny"),
             "NYY": ("new york", "ny"), "PHI": ("philadelphia",), "PIT": ("pittsburgh",), "SD": ("san diego",),
             "SEA": ("seattle",), "SF": ("san francisco",), "STL": ("st louis", "st. louis", "saint louis"),
             "TB": ("tampa bay", "tampa"), "TEX": ("texas",), "TOR": ("toronto",), "WSH": ("washington",)}

_team_cache: dict = {}


def _team_table() -> tuple:
    """(regex alternation of every team phrase, {phrase: [('MLB','NYY'), ...]})."""
    if "t" in _team_cache:
        return _team_cache["t"]
    phrases: dict = {}

    def add(phrase: str, sport: str, code: str) -> None:
        phrase = normalise(phrase)
        phrases.setdefault(phrase, [])
        if (sport, code) not in phrases[phrase]:
            phrases[phrase].append((sport, code))

    for t in R.team_menu():
        sport, code = t["value"].split(":")
        nick = t["label"]
        add(nick, sport, code)
    try:
        from src.sports import nfl_teams
        for code, full, nick in nfl_teams.TEAMS:
            add(full, "NFL", code)
            add(nick, "NFL", code)
    except Exception:  # noqa: BLE001
        pass
    nick_of = {t["value"]: t["label"] for t in R.team_menu()}
    for code, cities in _MLB_CITY.items():
        nick = nick_of.get(f"MLB:{code}")
        if nick:
            for city in cities:
                add(f"{city} {nick}", "MLB", code)
    ordered = sorted(phrases, key=len, reverse=True)
    alternation = "|".join(re.escape(p) for p in ordered)
    _team_cache["t"] = (alternation, phrases)
    return _team_cache["t"]


# ---------------------------------------------------------------------------
# the draft
# ---------------------------------------------------------------------------

class Seg:
    """One rule segment being read."""

    def __init__(self, text: str):
        self.w = text
        self.sports: list = []
        self.markets: list = []
        self.side: Optional[str] = None
        self.price_min: Optional[int] = None
        self.price_max: Optional[int] = None
        self.line_min: Optional[float] = None
        self.line_max: Optional[float] = None
        self.min_books: Optional[int] = None
        self.conds: list = []          # [(clause_text, cond_dict)]
        self.fade = False
        self.days: list = []
        self.players: list = []
        self.teams: list = []          # [(sport, code, opponent: bool)]
        self.team_ambiguous = False
        self.prop_generic = False
        self.stat_for_player = False
        self.venue: list = []          # [(text, ground)] from phrases like "home advantage", merged into one condition

    @property
    def content(self) -> bool:
        return bool(self.sports or self.markets or self.side or self.price_min is not None
                    or self.price_max is not None or self.line_min is not None or self.line_max is not None
                    or self.conds or self.players or self.teams or self.days or self.prop_generic)


class Reader:
    def __init__(self, text: str, players: Optional[Iterable[str]]):
        self.orig = text
        self.understood: list = []
        self.not_understood: list = []
        self.assumed: list = []
        self.globals: dict = {}
        self.players = set(players or ())
        self._player_rx = None

    # -- bookkeeping --------------------------------------------------------------------------
    def ok(self, text: str, meaning: str) -> None:
        text = " ".join(text.split())
        for item in self.understood:
            if item["meaning"] == meaning:           # the same idea said twice reads as one line, both phrases shown
                if text not in item["text"].split(" + "):
                    item["text"] += " + " + text
                return
        self.understood.append({"text": text, "meaning": meaning})

    def no(self, text: str, reason: str) -> None:
        self.not_understood.append({"text": " ".join(text.split()), "reason": reason})

    # -- one pattern pass -----------------------------------------------------------------------
    def take(self, seg_or_text, rx: str, handler, flags=re.I) -> None:
        """Run `handler(match)` on each match of `rx` in the segment's working text and consume the
        matched span (handler returning False leaves the text for later patterns)."""
        is_seg = isinstance(seg_or_text, Seg)
        w = seg_or_text.w if is_seg else seg_or_text[0]
        out, last = [], 0
        for m in re.finditer(rx, w, flags):
            res = handler(m)
            if res is False:
                continue
            out.append(w[last:m.start()])
            out.append(_PLACE * max(1, len(m.group(0)) // 4))
            last = m.end()
        out.append(w[last:])
        new = "".join(out)
        if is_seg:
            seg_or_text.w = new
        else:
            seg_or_text[0] = new


def _price(token: str) -> int:
    return int(token.replace("+", ""))


def _valid_price(p: int) -> bool:
    return abs(p) >= 100 and p <= user_spec.LONGEST_ALLOWED_PRICE


# ---------------------------------------------------------------------------
# global patterns (whole text)
# ---------------------------------------------------------------------------

def read_globals(rd: Reader, box: list) -> None:
    g = rd.globals

    def bets(m):
        n = int(m.group("n"))
        lo, hi = user_spec.MAX_BETS_RANGE
        if lo <= n <= hi:
            g["max_bets_per_day"] = n
            rd.ok(m.group(0), f"at most {n} {'bet' if n == 1 else 'bets'} a day")
        else:
            rd.no(m.group(0), f"a dog may make {lo} to {hi} bets a day")

    rd.take(box, r"\b(?:max(?:imum)?(?:\s+of)?|at most|up to|no more than|limit(?:ed)?(?:\s+to)?|only)\s+"
                 r"(?P<n>\d+)\s+(?:bets?|picks?|plays?|wagers?)\b(?:\s+(?:a|per|each|every)\s+(?:day|night|slate)|\s+daily)?",
            bets)
    rd.take(box, r"\b(?P<n>\d+)\s+(?:bets?|picks?|plays?)\s+(?:a|per|each|every)\s+(?:day|night|slate)\b", bets)
    rd.take(box, r"\b(?:max(?:imum)?(?:\s+of)?|at most|up to|no more than)\s+(?P<n>\d+)\s+(?:a|per|each|every)\s+(?:day|night|slate)\b", bets)

    def stake(m):
        n = float(m.group("n"))
        if n in R.STAKE_CHOICES:
            g["stake_units"] = n
            rd.ok(m.group(0), f"stake {n:g} paper unit{'' if n == 1 else 's'} a bet")
        else:
            rd.no(m.group(0), "a stake is 0.5 to 3 paper units in half-unit steps")

    rd.take(box, r"\b(?:stake|risk|bet|wager|size|for)?\s*(?P<n>\d+(?:\.\d+)?)\s*(?:u|units?)\b", stake)

    def lock(m):
        n = int(m.group("n"))
        mins = n * 60 if m.group("unit").lower().startswith(("h",)) else n
        if mins in user_spec.LOCK_CHOICES:
            g["lock_minutes"] = mins
            rd.ok(m.group(0), f"bets are decided {mins} minutes before the start")
        else:
            rd.no(m.group(0), f"the lock is {', '.join(map(str, user_spec.LOCK_CHOICES))} minutes before the start")

    rd.take(box, r"\b(?P<n>\d+)\s*(?P<unit>hours?|hrs?|h|minutes?|mins?|m)\s+(?:before|prior to|ahead of)"
                 r"(?:\s+(?:the\s+)?(?:first pitch|kickoff|start|game|lock))?", lock)

    def hour_before(m):
        g["lock_minutes"] = 60
        rd.ok(m.group(0), "bets are decided 60 minutes before the start")

    rd.take(box, r"\ban?\s+hour\s+(?:before|prior to)(?:\s+(?:the\s+)?(?:first pitch|kickoff|start|game))?", hour_before)

    ranks = {"longest price": "longest_price", "longest odds": "longest_price", "biggest underdog": "longest_price",
             "biggest underdogs": "longest_price", "biggest dog": "longest_price", "biggest dogs": "longest_price",
             "shortest price": "shortest_price", "shortest odds": "shortest_price", "safest": "shortest_price",
             "most books": "most_books", "most books quoting": "most_books", "biggest steam": "biggest_steam",
             "most steam": "biggest_steam", "most moved": "biggest_steam", "biggest line move": "biggest_steam",
             "earliest game": "earliest_lock", "earliest": "earliest_lock", "first game": "earliest_lock"}
    keys = "|".join(sorted((re.escape(k) for k in ranks), key=len, reverse=True))

    def rank(m):
        choice = ranks[m.group("r").lower()]
        g["rank_by"] = choice
        rd.ok(m.group(0), f"if more qualify than the daily cap, take {R.RANK_LABELS[choice].lower()}")

    rd.take(box, r"\b(?:prioriti[sz]e|prefer|rank(?:ed)?\s+by|favou?r|take|choose|pick)\s+(?:the\s+)?(?P<r>" + keys + r")\b", rank)


# ---------------------------------------------------------------------------
# per-segment patterns
# ---------------------------------------------------------------------------

_DAYS = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu", "friday": "fri",
         "saturday": "sat", "sunday": "sun"}
_HIT_STATS = (("hits", "hits"), ("home_runs", "home runs"))


def read_segment(rd: Reader, seg: Seg) -> None:
    ok, no = rd.ok, rd.no

    def cond(text, c, meaning=None):
        seg.conds.append((text, c))
        kind = "ml_spread"
        try:
            ok(text, "when " + R.condition_text({**R.default_instance(c["id"]), **c}, kind))
        except Exception:  # noqa: BLE001
            ok(text, meaning or c["id"])

    take = lambda rx, h, flags=re.I: rd.take(seg, rx, h, flags)  # noqa: E731

    # --- fade -------------------------------------------------------------------------------------
    def fade(m):
        seg.fade = True
        ok(m.group(0), "back the other side of whatever follows")
    take(r"\b(?:fad(?:e|es|ing)|bet(?:ting)? against(?! the spread)|back(?:ing)? against(?! the spread)|go(?:ing)? against(?! the spread))\b", fade)

    # --- sports -------------------------------------------------------------------------------------
    take(r"\b(?:mlb|baseball)\b", lambda m: (seg.sports.append("MLB"), ok(m.group(0), "MLB")) and None)
    take(r"\b(?:nfl|football)\b", lambda m: (seg.sports.append("NFL"), ok(m.group(0), "NFL")) and None)

    # --- spread size ("spreads under 7") ---------------------------------------------------------------
    def spread_size(m):
        cmp_ = _CMP_WORDS[m.group("cmp").lower()]
        n = float(m.group("n"))
        if n > 30:
            no(m.group(0), "a spread is at most 30 points")
            return
        if "spread" not in seg.markets:
            seg.markets.append("spread")
        cond(m.group(0), {"id": "spread_size", "cmp": cmp_, "value": n})
    take(r"\b(?:point\s+spreads?|spreads?|run\s*lines?)\s+(?:of\s+|is\s+|are\s+)?(?P<cmp>" + _CMP_RE + r")\s+(?P<n>\d+(?:\.\d+)?)\b", spread_size)

    # --- player streaks (before team streaks and the hits market) -------------------------------------------
    verbs = {"hit": "hits", "hits": "hits", "hitting": "hits", "has hit": "hits", "had a hit": "hits",
             "got a hit": "hits", "homered": "home_runs", "homers": "home_runs", "has homered": "home_runs",
             "hit a homer": "home_runs", "driven in a run": "rbis", "had an rbi": "rbis", "scored": "runs",
             "scored a run": "runs"}
    verb_rx = "|".join(sorted((re.escape(v) for v in verbs), key=len, reverse=True))

    def p_streak(m):
        stat = verbs[m.group("v").lower()]
        n = int(m.group("n"))
        if not 1 <= n <= 10:
            no(m.group(0), "a player streak is 1 to 10 games")
            return
        seg.stat_for_player = True
        cond(m.group(0), {"id": "player_streak", "stat": stat, "games": n, "min": 1})
    take(r"\b(?:(?:he|player)(?:'s|\s+has|\s+have|\s+is)?\s+)?(?P<v>" + verb_rx + r")\s+(?:safely\s+)?in\s+(?:each of\s+(?:his\s+)?(?:last|past)\s+)?(?P<n>\d+)\s+"
         r"(?:straight|consecutive|in a row)?\s*(?:games?|starts?|in a row)?(?:\s+in a row)?", p_streak)
    take(r"\b(?:he(?:'s|\s+has)\s+)?(?P<v>" + verb_rx + r")\s+(?:safely\s+)?in\s+(?P<n>\d+)\s+(?:straight|consecutive)\s+games?", p_streak)

    # --- team streaks -----------------------------------------------------------------------------------
    kinds = {"win": "winning", "wins": "winning", "winning": "winning", "w": "winning", "won": "winning",
             "loss": "losing", "losses": "losing", "losing": "losing", "l": "losing", "lost": "losing",
             "defeat": "losing", "defeats": "losing"}

    def t_streak(m):
        k = kinds[(m.group("k") or "").lower()]
        n = int(m.group("n"))
        if not 1 <= n <= 15:
            no(m.group(0), "a streak is 1 to 15 games")
            return
        cond(m.group(0), {"id": "streak", "who": _who(m.groupdict().get("subj")), "kind": k, "value": n})
    take(r"\b(?:after|following|off|coming off|on|with)\s+(?:a\s+)?(?P<n>\d+)[\s-]+(?:game\s+)?(?:straight|in a row|consecutive)\s+(?:game\s+)?(?P<k>wins?|losses|loss|defeats?|w|l)\b", t_streak)
    take(r"\b(?:on|riding|with)\s+(?:a\s+)?(?P<n>\d+)[\s-]*(?:game\s+)?(?P<k>winning|losing)\s+streak\b", t_streak)
    take(r"\b(?:" + _SUBJ + r"\s+)?(?:has|have|had|'ve)?\s*(?P<k>won|lost)\s+(?:their\s+last\s+)?(?P<n>\d+)\s+(?:games?\s+)?(?:straight|in a row|consecutive)(?:\s+games?)?", t_streak)
    take(r"\b(?P<n>\d+)\s+(?:straight|consecutive)\s+(?P<k>wins|losses|defeats)\b", t_streak)

    # --- matchups and team strength -------------------------------------------------------------------------
    _read_matchups(rd, seg, take, cond)

    # --- last N -------------------------------------------------------------------------------------------
    def last_n(m):
        w, n = int(m.group("w")), int(m.group("n"))
        if not (3 <= n <= 20 and 0 <= w <= n):
            no(m.group(0), "last-N form is 3 to 20 games, with wins no more than N")
            return
        cond(m.group(0), {"id": "last_n_wins", "who": _who(m.groupdict().get("subj")), "n": n, "cmp": "gte", "wins": w})
    take(r"\b(?:" + _SUBJ + r"\s+)?(?:has\s+|have\s+)?won\s+(?:at least\s+)?(?P<w>\d+)\s+(?:of|out of)\s+(?:their\s+|its\s+|the\s+)?(?:last|past|previous)\s+(?P<n>\d+)(?:\s+games?)?", last_n)
    take(r"\b(?P<w>\d+)\s*-\s*\d+\s+in\s+(?:their\s+|its\s+)?(?:last|past)\s+(?P<n>\d+)(?:\s+games?)?", last_n)

    # --- rest ------------------------------------------------------------------------------------------------
    def rest_zero(m):
        cond(m.group(0), {"id": "rest_days", "who": _who(m.groupdict().get("subj")), "cmp": "lte", "value": 0})
    take(r"\b(?:" + _SUBJ + r"\s+)?(?:on|with|after|has|have)?\s*(?:no days? (?:of )?rest|back[- ]to[- ]back|(?:0|zero) days? (?:of )?rest|on no rest|no rest)\b", rest_zero)

    def rest(m):
        n = int(m.group("n"))
        if not 0 <= n <= 14:
            no(m.group(0), "rest is 0 to 14 days")
            return
        cmp_ = "lte" if (m.group("sfx") or "").strip() in ("or fewer", "or less") else "gte"
        cond(m.group(0), {"id": "rest_days", "who": _who(m.groupdict().get("subj")), "cmp": cmp_, "value": n})
    take(r"\b(?:" + _SUBJ + r"\s+)?(?:on|with|after|has|have|having|off|at least|coming off)?\s*(?P<n>\d+)\s*\+?\s*(?P<sfx>or more|or fewer|or less)?\s*(?:full\s+)?days?(?:'s)?\s+(?:of\s+)?(?:rest|off)\b", rest)

    # --- travel -------------------------------------------------------------------------------------------------
    def travel(m):
        n = int(m.group("n"))
        if not 0 <= n <= 3000:
            no(m.group(0), "travel is 0 to 3000 miles")
            return
        cond(m.group(0), {"id": "travel_miles", "who": _who(m.groupdict().get("subj")), "cmp": "gte", "miles": n})
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\b(?:" + _SUBJ + r"\s+)?(?:travel(?:l)?ed|flew|flown)\s+(?:more than |over |at least )?(?P<n>\d+)\s*\+?\s*miles?", travel)

    # --- player form / rate -----------------------------------------------------------------------------------
    def p_form(m):
        n = int(m.group("n"))
        rel = "above" if m.group("rel").lower() in ("above", "over") else "below"
        if not 3 <= n <= 15:
            no(m.group(0), "recent form is 3 to 15 games")
            return
        seg.stat_for_player = True
        cond(m.group(0), {"id": "player_form", "n": n, "rel": rel, "margin": 0.0})
    take(r"\b(?:last|past)\s+(?P<n>\d+)\s+games?\s+(?:average|avg|averages)[^,.;§]*?\b(?P<rel>above|over|below|under)\s+the\s+line", p_form)
    take(r"\baverag(?:es|ing|e)\s+(?P<rel>above|over|below|under)\s+the\s+line\s+(?:in|over)\s+(?:his\s+|the\s+)?(?:last|past)\s+(?P<n>\d+)(?:\s+games?)?", p_form)

    def p_rate(m):
        v = float(m.group("v"))
        cmp_ = _CMP_WORDS.get((m.group("cmp") or "at least").lower(), "gte")
        if not 0 <= v <= 10:
            no(m.group(0), "a per-game average is 0 to 10")
            return
        seg.stat_for_player = True
        cond(m.group(0), {"id": "player_rate", "cmp": cmp_, "value": v})
    take(r"\b(?:season\s+)?(?:average|avg|averages|averaging)\s+(?:of\s+)?(?:(?P<cmp>" + _CMP_RE + r")\s+)?(?P<v>\d+(?:\.\d+)?)\s*(?:per game|a game)?", p_rate)

    # --- "last five games" with no win count: recent form ------------------------------------------------------------
    def form(m):
        gd = m.groupdict()
        n = int(gd.get("n") or gd.get("n2") or 5)
        who = _who(gd.get("subj"))
        if not 3 <= n <= 20:
            no(m.group(0), "last-N form is 3 to 20 games")
            return
        wins = n // 2 + 1
        cond(m.group(0), {"id": "last_n_wins", "who": who, "n": n, "cmp": "gte", "wins": wins})
        rd.assumed.append(f"'last {n} games' with no win count is read as at least {wins} wins in the last {n} games")
    take(r"\b(?:" + _POSS + r"\s+)?(?:(?:last|past|previous|recent)\s+(?P<n>\d+)\s+(?:games?|results?|contests?|outings?)"
         r"(?:\s+(?:record|form|results?))?|(?:recent|current|good|strong|winning)\s+form(?:\s+(?:in|over)\s+the\s+(?:last|past)\s+(?P<n2>\d+)\s+games?)?)", form)

    # --- weather -------------------------------------------------------------------------------------------------
    def winddir(m):
        value = m.group("d").lower()
        c = {"id": "wind_direction", "value": value}
        reason = R.BY_ID["wind_direction"].unavailable()
        if reason:
            no(m.group(0), reason)
        else:
            cond(m.group(0), c)
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\bwinds?\s+(?:is\s+|are\s+)?blowing\s+(?P<d>out|in)\b", winddir)
    take(r"\bwind\s+(?P<d>out|in)\b", winddir)

    def wind(m):
        v = float(m.group("n"))
        if not 0 <= v <= 40:
            no(m.group(0), "wind speed is 0 to 40 mph")
            return
        cmp_ = _CMP_WORDS[(m.group("cmp") or "at least").lower()]
        cond(m.group(0), {"id": "wind_speed", "cmp": cmp_, "value": v})
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\bwinds?(?:\s+speed)?(?:\s+is|\s+of)?\s+(?P<cmp>" + _CMP_RE + r")\s+(?P<n>\d+)\s*(?:mph|miles per hour)?", wind)
    take(r"\b(?P<n>\d+)\+?\s*mph\s+winds?\b", lambda m: wind(_Fake(m, cmp="at least")))

    def windy(m):
        cond(m.group(0), {"id": "wind_speed", "cmp": "gte", "value": 12.0})
        rd.assumed.append("'windy' is read as a forecast wind of at least 12 mph")
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\b(?:windy|breezy|gusty)\b", windy)

    def temp(m):
        v = float(m.group("n"))
        if not 20 <= v <= 115:
            no(m.group(0), "temperature is 20 to 115 degrees F")
            return
        cond(m.group(0), {"id": "temperature", "cmp": _CMP_WORDS[m.group("cmp").lower()], "value": v})
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\btemp(?:erature)?(?:\s+is|\s+of)?\s+(?P<cmp>" + _CMP_RE + r")\s+(?P<n>\d{2,3})\s*(?:°|degrees?)?(?:\s*f\b)?", temp)
    take(r"\b(?P<cmp>" + _CMP_RE + r")\s+(?P<n>\d{2,3})\s*(?:°|degrees?)\s*(?:f\b)?", temp)

    def roof(m):
        word = m.group(0).lower()
        v = "closed" if any(k in word for k in ("dome", "indoor", "closed")) else "open"
        cond(m.group(0), {"id": "roof", "value": v})
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\b(?:domes?|domed|indoors?|roof (?:is )?closed)\b", roof)
    take(r"\b(?:open[- ]air|outdoors?|roof (?:is )?open)\b", roof)

    def dry(m):
        cond(m.group(0), {"id": "rain_chance", "cmp": "lte", "value": 10})
        rd.assumed.append("'dry' is read as a forecast chance of rain of 10% or less")
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\b(?:no rain|dry|dry weather)\b", dry)

    def rain(m):
        v = int(m.group("n"))
        if not 0 <= v <= 100:
            no(m.group(0), "rain chance is 0 to 100 percent")
            return
        cond(m.group(0), {"id": "rain_chance", "cmp": _CMP_WORDS[m.group("cmp").lower()], "value": v})
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
    take(r"\b(?:chance of rain|rain chance|rain)\s+(?:is\s+)?(?P<cmp>" + _CMP_RE + r")\s+(?P<n>\d+)\s*%?", rain)

    # --- schedule words -------------------------------------------------------------------------------------------------
    def dow(m):
        word = m.group("d").lower().rstrip("s") if m.group("d").lower() not in ("weekends", "weekdays") else m.group("d").lower()
        if word in ("weekend", "weekends"):
            days = ["sat", "sun"]
        elif word in ("weekday", "weekdays"):
            days = ["mon", "tue", "wed", "thu", "fri"]
        else:
            days = [_DAYS.get(word) or _DAYS.get(word + "s", "")]
        seg.days.extend(d for d in days if d and d not in seg.days)
        ok(m.group(0), "on " + ", ".join(dict(R.WEEKDAYS)[d] for d in days if d))
    take(r"\b(?:on\s+)?(?P<d>mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|weekends?|weekdays?)\b", dow)

    def tod(m):
        word = m.group("v").lower()
        v = "day" if word in ("day", "afternoon", "daytime") else "night"
        cond(m.group(0), {"id": "time_of_day", "value": v})
    take(r"\b(?P<v>day|night|afternoon|evening|daytime)\s+games?\b", tod)

    # --- steam -------------------------------------------------------------------------------------------------------------
    def steam_against(m):
        cond(m.group(0), {"id": "steam", "direction": "against"})
    def steam_toward(m):
        cond(m.group(0), {"id": "steam", "direction": "toward"})
    take(r"\b(?:the\s+)?(?:line|market|money|steam|sharp money|sharps?)\s+(?:has\s+|have\s+)?(?:moved?|moving|moves|shifted|goes|going)?\s*(?:against|away from)\b", steam_against)
    take(r"\b(?:line|market|price)\s+(?:has\s+|have\s+)?(?:moved?|moving|moves|shifted|drifted)\s+(?:toward|towards|to|in favou?r of|behind)\b", steam_toward)
    take(r"\b(?:steam(?:ing|ed)?|sharp money|sharps|steamers?|line moves?|line movement)(?:\s+(?:toward|towards|on|to|behind))?\b", steam_toward)

    # --- for fun ----------------------------------------------------------------------------------------------------------------------
    take(r"\b(?:the\s+)?moon\s+(?:is\s+)?full\b|\bfull moon\b", lambda m: cond(m.group(0), {"id": "moon_phase", "value": "full"}))
    take(r"\b(?:the\s+)?moon\s+(?:is\s+)?new\b|\bnew moon\b", lambda m: cond(m.group(0), {"id": "moon_phase", "value": "new"}))
    take(r"\b(?:coin ?flips?|flip(?:s|ping)? a coin|heads or tails)\b", lambda m: cond(m.group(0), {"id": "coin_flip", "pct": 50}))
    take(r"\b(?:numerology|gematria|lucky numbers?)\b", lambda m: cond(m.group(0), {"id": "numerology", "value": "closer"}))

    def letter(m):
        test = {"starts": "starts_with", "begins": "starts_with", "ends": "ends_with", "contains": "contains",
                "has": "contains", "includes": "contains"}[m.group("t").lower()]
        cond(m.group(0), {"id": "name_letter", "of": "pick", "test": test, "letter": m.group("l").upper()})
    take(r"\b(?:team )?names?\s+(?P<t>starts|begins|ends)\s+with\s+(?:the\s+)?(?:letter\s+)?(?P<l>[a-z])\b", letter)
    take(r"\b(?:team )?names?\s+(?P<t>contains|has|includes)\s+(?:the\s+)?(?:letter\s+)?(?P<l>[a-z])\b", letter)

    # --- books --------------------------------------------------------------------------------------------------------------------------------
    def books(m):
        n = int(m.group("n"))
        lo, hi = user_spec.MIN_BOOKS_RANGE
        if lo <= n <= hi:
            seg.min_books = n
            ok(m.group(0), f"at least {n} {'book' if n == 1 else 'books'} quoting it")
        else:
            no(m.group(0), f"books quoting is {lo} to {hi}")
    take(r"\b(?:at least\s+)?(?P<n>\d+)\+?\s+books?(?:\s+(?:quoting|offering|pricing|on the board|agree))?", books)

    # --- prices (signed, 3-4 digits) ------------------------------------------------------------------------------------------------------------------------
    def price_range(m):
        a, b = _price(m.group("a")), _price(m.group("b"))
        if not (_valid_price(a) and _valid_price(b)):
            no(m.group(0), "prices are American odds such as -150 or +120, up to +1000")
            return
        a, b = sorted((a, b), key=user_spec.price_decimal)
        seg.price_min, seg.price_max = a, b
        ok(m.group(0), f"average price between {_fmt(a)} and {_fmt(b)}")
    take(r"\b(?:between|from|priced at|odds of|at)?\s*(?P<a>[+-]\d{3,4})\s*(?:and|to|through|&|-)\s*(?P<b>[+-]?\d{3,4})\b", price_range)
    take(r"\bbetween\s+(?P<a>\d{3,4})\s+and\s+(?P<b>[+-]?\d{3,4})\b", price_range)

    def price_min(m):
        p = _price(m.group("p"))
        if not _valid_price(p):
            no(m.group(0), "prices are American odds such as -150 or +120")
            return
        seg.price_min = p
        ok(m.group(0), f"average price of {_fmt(p)} or longer")
    take(r"(?P<p>[+-]\d{3,4})\s*(?:or|and)\s*(?:better|longer|higher|more|up|plus)\b", price_min)
    take(r"\b(?:at least|better than|longer than|minimum of|min)\s+(?P<p>[+-]\d{3,4})\b", price_min)

    def price_max(m):
        p = _price(m.group("p"))
        if not _valid_price(p):
            no(m.group(0), "prices are American odds such as -150 or +120")
            return
        seg.price_max = p
        ok(m.group(0), f"average price of {_fmt(p)} or shorter")
    take(r"(?P<p>[+-]\d{3,4})\s*(?:or|and)\s*(?:shorter|worse|lower|less)\b", price_max)
    take(r"\b(?:no longer than|no worse than|up to|at most|shorter than|under|below|maximum of|max)\s+(?P<p>[+-]\d{3,4})\b", price_max)

    def plus_money(m):
        seg.price_min = 100
        ok(m.group(0), "plus-money prices (+100 or longer)")
    take(r"\bplus[- ]money\b", plus_money)

    # --- stats (prop markets) --------------------------------------------------------------------------------------------------------------------------
    def market(name, label):
        def h(m):
            if name not in seg.markets:
                seg.markets.append(name)
            if "MLB" not in seg.sports:
                seg.sports.append("MLB")
            seg.stat_for_player = True
            ok(m.group(0), label)
        return h
    def to_homer(m):
        if "batter_home_runs" not in seg.markets:
            seg.markets.append("batter_home_runs")
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
        seg.stat_for_player = True
        seg.side, seg.line_min, seg.line_max = "over", 0.5, 0.5
        ok(m.group(0), "to hit a home run is the over 0.5 on batter home runs")
    take(r"\b(?:to\s+)?(?:hit(?:s)?|belt(?:s)?|smash(?:es)?)\s+(?:a|an|at least one|1)\s+(?:home\s*run|homer|dinger)\b|\bto\s+(?:homer|go yard)\b", to_homer)

    def to_hit(m):
        if "batter_hits" not in seg.markets:
            seg.markets.append("batter_hits")
        if "MLB" not in seg.sports:
            seg.sports.append("MLB")
        seg.stat_for_player = True
        seg.side, seg.line_min, seg.line_max = "over", 0.5, 0.5
        ok(m.group(0), "to get a hit is the over 0.5 on batter hits")
    take(r"\bto\s+(?:get|record|have|notch)\s+a\s+hit\b|\bto\s+hit\s+safely\b", to_hit)

    take(r"\bhits?\s*\+\s*runs?\s*\+\s*rbis?|\bh\s*\+\s*r\s*\+\s*rbis?\b|\bhits,?\s+runs,?\s+(?:and\s+)?rbis?\b", market("batter_hits_runs_rbis", "batter hits + runs + RBIs"))
    take(r"\btotal\s+bases\b|\btbs?\b", market("batter_total_bases", "batter total bases"))
    take(r"\bhome\s*runs?\b|\bhomers?\b|\bhrs?\b|\bdingers?\b", market("batter_home_runs", "batter home runs"))
    take(r"\bstrike\s*outs?\b|\bks\b|\bk's\b|\bpitcher ks\b", market("pitcher_strikeouts", "pitcher strikeouts"))
    take(r"\bruns\s+scored\b", market("batter_runs_scored", "batter runs scored"))
    take(r"\brbis?\b|\bruns batted in\b", market("batter_rbis", "batter RBIs"))
    take(r"\bhits?\b", market("batter_hits", "batter hits"))

    def props(m):
        seg.prop_generic = True
        ok(m.group(0), "player props")
    take(r"\bplayer\s+props?\b|\bprops?\b", props)

    # --- game markets ------------------------------------------------------------------------------------------------------------------------------------
    def gm(name, label):
        def h(m):
            if name not in seg.markets:
                seg.markets.append(name)
            ok(m.group(0), label)
        return h
    take(r"\bover[/ ]under\b|\bo/u\b|\btotals?\b", gm("total", "game totals"))
    take(r"\bpoint\s+spreads?\b|\brun\s*lines?\b|\bspreads?\b|\bats\b|\bagainst the spread\b", gm("spread", "spread / run line"))
    take(r"\bmoney\s*lines?\b|\bmls?\b|\bstraight[- ]up\b|\boutright\b|\bto win\b|\bwinners?\b", gm("moneyline", "moneyline"))

    # --- over/under with a line ("over 1.5") ------------------------------------------------------------------------------------------------------------------------------
    def side_line(m):
        n = float(m.group("n"))
        if not (user_spec.LINE_RANGE[0] <= n <= user_spec.LINE_RANGE[1]):
            no(m.group(0), "a line is within -30 to 60")
            return
        seg.side = m.group("s").lower()
        seg.line_min = seg.line_max = n
        ok(m.group(0), f"the {seg.side} of {n:g}")
    take(r"\b(?P<s>over|under)\s+(?P<n>\d{1,2}(?:\.\d+)?)\b(?!\s*(?:%|degrees|mph|miles|days|games|books|units))", side_line)

    # --- teams ----------------------------------------------------------------------------------------
    alternation, table = _team_table()
    _read_teams(rd, seg, alternation, table)

    # --- players ----------------------------------------------------------------------------------------------------------------------------------------------------------
    _read_players(rd, seg)

    # --- sides ---------------------------------------------------------------------------------------------------------------------------------------------------------------
    def side(value, label):
        def h(m):
            if seg.side and seg.side != value and seg.side in ("home", "away", "over", "under"):
                return
            seg.side = value
            ok(m.group(0), label)
        return h
    take(r"\b(?:away|road|visiting|visitors?|on the road)\b", side("away", "the away side"))
    take(r"\b(?:at\s+)?home\b", side("home", "the home side"))

    def role(value):
        def h(m):
            seg.conds.append((m.group(0), {"id": "role", "value": value}))
            ok(m.group(0), f"the {value}")
        return h
    take(r"\b(?:favou?rites?|favs?|chalk)\b", role("favourite"))
    take(r"\b(?:underdogs?|dogs?|longshots?)\b", role("underdog"))
    take(r"\bovers?\b", side("over", "the over"))
    take(r"\bunders?\b", side("under", "the under"))


def _fmt(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


# who a team phrase is about ("its offense", "the opponent's defense")
_POSS = (r"(?P<subj>(?:the\s+)?(?:opponents?|opposing\s+team|other\s+team|home\s+team|away\s+team|road\s+team|visitors?|team)'?s?"
         r"|its|their)")
_UNIT_WORD = {"offense": "offense", "offence": "offense", "defense": "defense", "defence": "defense",
              "offensive": "offense", "defensive": "defense"}
_OFF = r"offen[sc]e"
_DEF = r"defen[sc]e"
_MEET = (r"(?:head[- ]to[- ]head(?:\s+(?:meetings?|matchups?|games?|matches))?|h2h|meetings?|matchups?|matches|encounters?"
         r"|games?\s+(?:with|against|vs\.?|versus)\s+(?:the\s+|this\s+|that\s+)?(?:opponent|other team|same team|opposition))")
_VS_OPP = r"(?:\s+(?:with|against|vs\.?|versus)\s+(?:the\s+|this\s+|that\s+)?(?:opponent|other team|same team|opposition|each other))?"
_THIS_SEASON = r"(?:\s+(?:this|the current)\s+(?:season|year))?"
DEFAULT_WINDOW = 10            # games, for the offense / defense phrases that name no window
H2H_DEFAULT_N = 5
VENUE_DEFAULT_PCT = 60.0       # the menu's own default for a home or road win rate


def _read_matchups(rd: "Reader", seg: "Seg", take, cond) -> None:
    """Head-to-head, home or road record, runs or points per game, league rank and offense against the other
    team's defense. Called from `read_segment` BEFORE the last-N and side patterns, so that "won 3 of the
    last 5 meetings" is a head-to-head and "away games data" is a record, not the away side."""
    no = rd.no
    cmps = _CMP_RE

    def window_of(text: str, n: Optional[int]) -> int:
        if n is not None:
            return n
        if re.search(r"\bthis\s+(?:season|year)\b|\bso far\b|\bwhole season\b|\bseason\b", text):
            return 0
        rd.assumed.append(f"no window was named for the scoring figures, so the last {DEFAULT_WINDOW} games are used")
        return DEFAULT_WINDOW

    def sport_hint(text: str) -> None:
        if re.search(r"\bruns?\b", text) and "MLB" not in seg.sports and "NFL" not in seg.sports:
            seg.sports.append("MLB")
        elif re.search(r"\bpoints?\b|\bpts\b", text) and "MLB" not in seg.sports and "NFL" not in seg.sports:
            seg.sports.append("NFL")

    # ---- head to head ------------------------------------------------------------------------------------
    def h2h(m, *, all_wins: bool = False):
        gd = m.groupdict()
        whole = m.group(0)
        n = int(gd["n"]) if gd.get("n") else None
        w = int(gd["w"]) if gd.get("w") else None
        window = "season" if re.search(r"\b(?:this|the current)\s+(?:season|year)\b|\bseason series\b", whole) else "all"
        if n is not None and not 1 <= n <= 10:
            no(whole, "head-to-head looks back 1 to 10 meetings")
            return
        if n is None:
            n = H2H_DEFAULT_N
            rd.assumed.append(f"'head-to-head' with no number of meetings is read as the last {n} meetings")
        if all_wins:
            w = n
        elif w is None:
            w = n // 2 + 1
            rd.assumed.append(f"a 'winning' head-to-head record is read as at least {w} wins in the last {n} meetings")
        if w > n:
            no(whole, "wins cannot be more than the number of meetings counted")
            return
        cond(whole, {"id": "head_to_head", "who": _who(gd.get("subj")), "n": n, "cmp": "gte", "wins": w, "window": window})

    subj = r"(?:" + _SUBJ + r"(?:'s)?\s+)?"
    take(r"\b" + subj + r"(?:has\s+|have\s+|had\s+)?(?:won|beaten|beat|defeated|swept)\s+(?:at least\s+)?(?P<w>\d+)\s+(?:of|out of)\s+"
         r"(?:their\s+|its\s+|the\s+)?(?:last|past|previous|recent)\s+(?P<n>\d+)\s+" + _MEET + _VS_OPP + _THIS_SEASON, h2h)
    take(r"\b" + subj + r"(?:has\s+|have\s+|had\s+)?(?:won|beaten|beat|defeated|swept)\s+(?:all\s+(?:of\s+)?)?(?:the\s+|their\s+|its\s+)?"
         r"(?:last|past|previous|recent)\s+(?P<n>\d+)\s+" + _MEET + _VS_OPP + _THIS_SEASON,
         lambda m: h2h(m, all_wins=True))
    take(r"\b" + subj + r"(?:(?:a|the|their|its|good|strong|winning|better|best|previous|past|prior|recent|historical)\s+)*"
         r"(?:head[- ]to[- ]head|h2h)(?:\s+(?:record|history|results?|stats|statistics|data|numbers|matchups?|meetings?))?" + _VS_OPP +
         r"(?:\s+(?:in|over|across)\s+(?:the\s+)?(?:last|past|previous)\s+(?P<n>\d+)\s+(?:meetings?|matchups?|games?|encounters?))?" + _THIS_SEASON,
         h2h)
    take(r"\b" + subj + r"(?:(?:the|their|its|good|strong|winning)\s+)*(?:previous|past|prior|earlier|historical|recent|last\s+(?P<n>\d+))\s+"
         r"(?:matchups?|meetings?|encounters?|games?\s+(?:with|against|vs\.?|versus)\s+(?:the\s+|this\s+|that\s+)?(?:opponent|other team|same team))"
         + _VS_OPP + _THIS_SEASON, h2h)
    take(r"\bagainst each other\b|\bseason series\b", h2h)

    # ---- offense against the other team's defense --------------------------------------------------------
    def edge(unit: str, m, n: Optional[int] = None):
        who = _who(m.groupdict().get("subj"))
        n = window_of(m.group(0), n if n is not None else (int(m.groupdict()["n"]) if m.groupdict().get("n") else None))
        cond(m.group(0), {"id": "matchup_edge", "who": who, "unit": unit, "gap": 1, "n": n})
        rd.assumed.append("'better' offense or defense is read as ranking at least 1 place better in the league")

    take(r"\b(?:" + _POSS + r"\s+)?(?P<u>" + _OFF + "|" + _DEF + r")\s+(?:is\s+|ranks?\s+|are\s+|rated\s+)?(?:much\s+|far\s+|clearly\s+)?"
         r"(?:better|stronger|higher|ahead of|above|superior)\s+(?:than\s+)?(?:the\s+)?"
         r"(?:opponents?'?s?'?|other\s+team'?s?|opposing(?:\s+team'?s?)?|opposition'?s?|their)\s+(?:" + _OFF + "|" + _DEF + r")"
         r"(?:\s+(?:over|in|across)\s+the\s+(?:last|past)\s+(?P<n>\d+)\s+games?|\s+this\s+(?:season|year))?",
         lambda m: edge(_UNIT_WORD[m.group("u")], m))
    take(r"\b(?P<u>" + _OFF + "|" + _DEF + r")\s+(?:vs\.?|versus|against|facing|matched\s+(?:up\s+)?(?:with|against)|matches\s+up\s+(?:with|against))\s+"
         r"(?:the\s+|an?\s+)?(?:(?:opponents?'?s?'?|opposing|other\s+team'?s?|bad|weak|poor|worse|terrible)\s+)*(?:" + _OFF + "|" + _DEF + r")"
         r"(?:\s+(?:over|in|across)\s+the\s+(?:last|past)\s+(?P<n>\d+)\s+games?|\s+this\s+(?:season|year))?",
         lambda m: edge(_UNIT_WORD[m.group("u")], m))

    def both_edges(m):
        n = window_of(m.group(0), None)
        for unit in ("offense", "defense"):
            cond(m.group(0), {"id": "matchup_edge", "who": "pick", "unit": unit, "gap": 1, "n": n})
        rd.assumed.append("'offensive and defensive' stats are read as: its offense AND its defense each rank at least 1 place "
                          "better in the league than the other team's defense and offense")
    take(r"\boffen[sc](?:e|ive)\s*(?:and|&|/|,)\s*defen[sc](?:e|ive)\s*(?:stats?|statistics|numbers|rankings?|ratings?|matchups?|"
         r"data|metrics|efficiency|comparisons?)?", both_edges)

    def one_edge(m):
        edge(_UNIT_WORD[m.group("u").lower()], m)
    take(r"\b(?P<u>offen[sc]ive|defen[sc]ive)\s+(?:stats?|statistics|numbers?|rankings?|ratings?|matchups?|data|metrics|efficiency|comparisons?)\b",
         one_edge)

    # ---- league rank ("a top 10 offense", "against a bottom 5 defense") --------------------------------------
    def rank(m):
        gd = m.groupdict()
        places = int(gd["p"])
        if not 1 <= places <= 15:
            no(m.group(0), "a league rank is the top or bottom 1 to 15")
            return
        word = gd["u"].lower()
        unit = "defense" if "def" in word else "offense"
        who = "opponent" if gd.get("ag") else _who(gd.get("subj"))
        n = window_of(m.group(0), int(gd["n"]) if gd.get("n") else None)
        cond(m.group(0), {"id": "league_rank", "who": who, "unit": unit, "end": gd["e"].lower(), "places": places, "n": n})
    take(r"\b(?P<ag>(?:against|facing|vs\.?|versus)\s+)?(?:(?:a|an|the)\s+)?(?:" + _POSS + r"\s+(?:has\s+|have\s+|is\s+|with\s+)?(?:a\s+|an\s+)?)?"
         r"(?P<e>top|bottom)[\s-]*(?P<p>\d+)\s+(?P<u>offen[sc]es?|defen[sc]es?|scoring\s+(?:teams?|offen[sc]es?)|offen[sc]ive\s+teams?|defensive\s+teams?)"
         r"(?:\s+in\s+the\s+(?:league|mlb|nfl|majors))?(?:\s+(?:over|in|across)\s+the\s+(?:last|past)\s+(?P<n>\d+)\s+games?|\s+this\s+(?:season|year))?",
         rank)

    # ---- runs or points per game --------------------------------------------------------------------------------
    def per_game(unit: str):
        def h(m):
            gd = m.groupdict()
            value = float(gd["x"])
            if not 0 <= value <= 60:
                no(m.group(0), "runs or points per game is 0 to 60")
                return
            if round(value, 1) != value:
                no(m.group(0), "runs or points per game is in steps of 0.1")
                return
            default_cmp = "at least" if unit == "offense" else "at most"
            cmp_ = _CMP_WORDS[(gd.get("cmp") or default_cmp).lower()]
            n = window_of(m.group(0), int(gd["n"]) if gd.get("n") else None)
            sport_hint(m.group(0))
            cond(m.group(0), {"id": "scoring_rate", "who": _who(gd.get("subj")), "unit": unit, "n": n, "cmp": cmp_, "value": value})
        return h
    tail = (r"(?:\s+(?:per game|a game|each game|every game|/game))?"
            r"(?:\s+(?:over|in|across)\s+(?:the\s+|its\s+|their\s+)?(?:last|past)\s+(?P<n>\d+)\s+games?|\s+this\s+(?:season|year))?")
    take(r"\b" + subj + r"(?:scores?|scored|scoring|averages?|averaging|puts?\s+up|gets?)\s+(?:(?P<cmp>" + cmps + r")\s+)?(?P<x>\d+(?:\.\d+)?)\+?\s*"
         r"(?:runs?|points?|pts)" + tail, per_game("offense"))
    take(r"\b" + subj + r"(?:allows?|allowed|gives?\s+up|conced(?:es|ed)|surrenders?)\s+(?:(?P<cmp>" + cmps + r")\s+)?(?P<x>\d+(?:\.\d+)?)\+?\s*"
         r"(?:runs?|points?|pts)" + tail, per_game("defense"))

    # ---- home or road record ------------------------------------------------------------------------------------
    def venue_numbered(m):
        gd = m.groupdict()
        value = float(gd["v"])
        if not 0 <= value <= 100 or value % 5:
            no(m.group(0), "a win rate is 0 to 100 percent in steps of 5")
            return
        word = (gd.get("g") or gd.get("where") or "").lower()
        ground = "home" if "home" in word and "road" not in word else "road" if any(k in word for k in ("road", "away")) else "today"
        cmp_ = _CMP_WORDS[(gd.get("cmp") or "at least").lower()]
        cond(m.group(0), {"id": "venue_record", "who": _who(gd.get("subj")), "ground": ground, "cmp": cmp_, "pct": value})
    take(r"\b" + subj + r"(?:has\s+|have\s+|with\s+)?(?:a\s+)?(?P<g>home|road|away)\s+(?:win\s+|winning\s+)?(?:record|rate|percentage|pct|form)\s+"
         r"(?:of\s+|is\s+|at\s+)?(?:(?P<cmp>" + cmps + r")\s+)?(?P<v>\d+(?:\.\d+)?)\s*(?:%|percent|pct)", venue_numbered)
    take(r"\b" + subj + r"win(?:ning)?\s+(?:rate|percentage|pct)\s+(?:of\s+|is\s+)?(?:(?P<cmp>" + cmps + r")\s+)?(?P<v>\d+(?:\.\d+)?)\s*(?:%|percent)\s*"
         r"(?P<where>(?:in\s+games\s+)?(?:at home|on the road|on road|away|in home games|in road games|in away games|at the same (?:kind of )?(?:ground|venue)(?:\s+as\s+today'?s?)?))?", venue_numbered)
    take(r"\b" + subj + r"(?:wins?|won)\s+(?:at least\s+)?(?P<v>\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(?:its\s+|their\s+|the\s+)?"
         r"(?P<g>home|road|away)\s+games", venue_numbered)

    def venue_words(ground: str):
        def h(m):
            seg.venue.append((m.group(0), ground))
        return h
    nouns = r"(?:record|records|splits?|form|data|stats|statistics|results|numbers|performance|numbers)"
    take(r"\bhome[- ]?(?:field|court)?\s+advantage\b|\bhome\s*(?:and|&|/)\s*(?:away|road)\s+(?:" + nouns + r"|games(?:\s+" + nouns + r")?)\b"
         r"|\b(?:away|road)\s*(?:and|&|/)\s*home\s+(?:" + nouns + r"|games(?:\s+" + nouns + r")?)\b", venue_words("today"))
    take(r"\bhome\s+(?:" + nouns + r"|games\s+" + nouns + r")\b", venue_words("home"))
    take(r"\b(?:away|road)\s+(?:" + nouns + r"|games\s+" + nouns + r")\b", venue_words("road"))

    # a descriptive phrase has no number: ONE record condition for all of them in the segment
    if seg.venue:
        grounds = {g for _t, g in seg.venue}
        ground = "today" if ("today" in grounds or {"home", "road"} <= grounds) else next(iter(grounds))
        text = " + ".join(t for t, _g in seg.venue)
        cond(text, {"id": "venue_record", "who": "pick", "ground": ground, "cmp": "gte", "pct": VENUE_DEFAULT_PCT})
        rd.assumed.append(f"a home or road record with no percentage is read as a win rate of at least {VENUE_DEFAULT_PCT:g}% "
                          "this season" + (" on today's kind of ground" if ground == "today" else ""))
        seg.venue = []


class _Fake:
    """A match-like object carrying fixed extra groups (for patterns that reuse another handler)."""

    def __init__(self, m, **extra):
        self._m, self._extra = m, extra

    def group(self, key=0):
        if key in self._extra:
            return self._extra[key]
        return self._m.group(key)

    def groupdict(self):
        return {**self._m.groupdict(), **self._extra}


def _read_teams(rd: Reader, seg: Seg, alternation: str, table) -> None:
    """Team names in the segment -> (sport, code, against) entries."""
    w = seg.w
    out, last = [], 0
    pat = re.compile(r"(?P<ag>(?:against|vs\.?|versus|facing)\s+(?:the\s+)?)?(?<![a-z])(?P<t>" + alternation + r")(?![a-z])")
    for m in pat.finditer(w):
        phrase = m.group("t")
        entries = table.get(phrase)
        if not entries:
            continue
        against = bool(m.group("ag"))
        seg.teams.extend((s, c, against) for s, c in entries)
        if len(entries) > 1:
            seg.team_ambiguous = True
        rd.ok(m.group(0), ("against the " if against else "the ") + phrase)
        out.append(w[last:m.start()])
        out.append(_PLACE * 2)
        last = m.end()
    out.append(w[last:])
    seg.w = "".join(out)


def _read_players(rd: Reader, seg: Seg) -> None:
    if not rd.players:
        return
    if rd._player_rx is None:
        rd._player_rx = re.compile(r"(?<![a-z])(" + "|".join(re.escape(n) for n in sorted(rd.players, key=len, reverse=True)) + r")(?:'s)?(?![a-z])")
    w = seg.w
    out, last = [], 0
    for m in rd._player_rx.finditer(w):
        name = m.group(1)
        display = " ".join(p.capitalize() for p in name.split())
        if display not in seg.players:
            seg.players.append(display)
        rd.ok(m.group(0), f"the player {display}")
        out.append(w[last:m.start()])
        out.append(_PLACE * 2)
        last = m.end()
    out.append(w[last:])
    seg.w = "".join(out)


# ---------------------------------------------------------------------------
# turning a segment into a rule
# ---------------------------------------------------------------------------

_INVERT_SIDE = {"home": "away", "away": "home", "over": "under", "under": "over"}
_INVERT_ROLE = {"favourite": "underdog", "underdog": "favourite"}
_INVERT_WHO = {"pick": "opponent", "opponent": "pick", "home": "away", "away": "home"}
_INVERT_STEAM = {"toward": "against", "against": "toward"}


def _apply_fade(seg: Seg) -> None:
    if seg.side in _INVERT_SIDE:
        seg.side = _INVERT_SIDE[seg.side]
    new_conds = []
    for text, c in seg.conds:
        c = dict(c)
        if c["id"] == "role":
            c["value"] = _INVERT_ROLE[c["value"]]
        elif c["id"] == "steam":
            c["direction"] = _INVERT_STEAM[c["direction"]]
        elif "who" in c:
            c["who"] = _INVERT_WHO.get(c["who"], c["who"])
        new_conds.append((text, c))
    seg.conds = new_conds
    seg.teams = [(s, code, not against) for s, code, against in seg.teams]


def _leftovers(rd: Reader, seg: Seg) -> None:
    for chunk in seg.w.split(_PLACE):
        tokens = re.findall(r"[a-z0-9'+\-.%/]+", chunk)
        words = [t for t in tokens if t.strip("'.-") and t not in _FILLER and not re.fullmatch(r"[.,;:!?'-]+", t)]
        if words:
            rd.no(" ".join(words), "not something the dog language can read yet")


def build_rule(rd: Reader, seg: Seg) -> Optional[dict]:
    """The rule dict a segment describes, or None when the segment said nothing about a bet."""
    if not seg.content:
        _leftovers(rd, seg)
        return None
    if seg.fade:
        _apply_fade(seg)
    _leftovers(rd, seg)

    markets = list(seg.markets)
    # player props
    prop_markets = [m for m in markets if R.market_kind(m) == "prop"]
    if seg.prop_generic and not prop_markets:
        prop_markets = list(R.PROP_MARKETS)
        rd.assumed.append("'props' with no stat named is read as every prop market; narrow it to the stats you want")
    if prop_markets:
        markets = prop_markets
    if seg.players and not prop_markets and not seg.stat_for_player:
        rd.no(", ".join(seg.players), "a player needs a stat to bet on (hits, total bases, home runs, RBIs, strikeouts)")
    if not markets:
        if seg.side in ("over", "under") and not seg.teams:
            markets = ["total"]
            rd.assumed.append(f"'{seg.side}' with no stat named is read as a game total")
        else:
            markets = ["moneyline"]
            rd.assumed.append("no market was named, so this is read as a moneyline rule")
    kinds = {R.market_kind(m) for m in markets}
    if len(kinds) > 1:
        # one rule per kind would be a different rule set; keep the first kind and report the rest
        keep = sorted(kinds)[0]
        dropped = [m for m in markets if R.market_kind(m) != keep]
        markets = [m for m in markets if R.market_kind(m) == keep]
        rd.no(", ".join(dropped), "a rule is about game bets, totals or player props, not a mix; say it as a second rule")
        kinds = {keep}
    kind = next(iter(kinds))

    sports = list(dict.fromkeys(seg.sports))
    if kind == "prop":
        sports = ["MLB"]
    if not sports:
        both_ok = all(set(R.BY_ID[c["id"]].sports) >= {"MLB", "NFL"} for _t, c in seg.conds if c["id"] in R.BY_ID)
        sports = ["MLB", "NFL"] if both_ok and not seg.teams else (_team_sports(seg) or ["MLB"])
        rd.assumed.append("no sport was named, so this rule covers " + " and ".join(sports))

    side = seg.side
    conds = list(seg.conds)
    if kind == "prop" and side in ("home", "away"):
        conds.append((side, {"id": "venue", "value": side}))
        side = None
    if kind == "total" and side in ("home", "away"):
        side = None
    if seg.days:
        conds.append((", ".join(seg.days), {"id": "day_of_week", "days": [d for d, _l in R.WEEKDAYS if d in seg.days]}))
    if seg.players:
        conds.append((", ".join(seg.players), {"id": "player_is", "players": seg.players[:R.MAX_LIST]}))
    ours = [(s, c) for s, c, against in seg.teams if not against]
    theirs = [(s, c) for s, c, against in seg.teams if against]
    for group, cid in ((ours, "team_is"), (theirs, "opponent_is")):
        group = [(s, c) for s, c in group if not sports or s in sports]
        if group:
            conds.append((", ".join(c for _s, c in group), {"id": cid, "teams": sorted({f"{s}:{c}" for s, c in group})[:R.MAX_LIST]}))

    items = []
    seen_conds: list = []
    for text, c in conds:
        if c in seen_conds:                  # the same idea said twice ("head-to-head ... previous matchups")
            continue
        seen_conds.append(c)
        errors: dict = {}
        norm = R.validate_condition(c, kinds=[kind], markets=markets, sports=sports, path="c", errors=errors,
                                    known_players=user_spec._known_player_fn())
        if norm is None:
            rd.no(text if isinstance(text, str) else c["id"], "; ".join(errors.values()) or "not valid here")
            continue
        items.append(norm)
    rule: dict = {"label": "", "sports": sports, "markets": markets, "side": side or "either"}
    if side not in (None, "either") and side not in R.sides_for([kind]):
        rd.no(side, f"'{side}' does not apply to {', '.join(markets)}")
        rule["side"] = "either"
    for key in ("price_min", "price_max", "line_min", "line_max", "min_books"):
        value = getattr(seg, key)
        if value is not None:
            rule[key] = value
    if items:
        rule["when"] = {"op": "all", "items": items}
    return rule


def _team_sports(seg: Seg) -> list:
    sports = []
    for s, _c, _a in seg.teams:
        if s not in sports:
            sports.append(s)
    return sports


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

_SPLIT = re.compile(r"\.(?=\s|$)|[;\n]+|\b(?:and|also|plus|,)\s+(?:then\s+)?(?:also\s+)?(?=(?:bet|back|take|play|fade)\b(?!-))|\balso\b")


def _known_players() -> set:
    """Folded names of players in the box scores (the parser's list of 'who is a player')."""
    try:
        from src.hounds.user_facts import known_player_keys
        return set(known_player_keys())
    except Exception:  # noqa: BLE001
        return set()


# What to say instead. Each row: (words that signal the idea, a wording the parser reads | None, why / what is
# not on the menu). Matched against the words that were NOT understood, never against what was.
_SUGGEST = (
    (r"head[- ]to[- ]head|\bh2h\b|matchups?|meetings?|encounters?|history (?:against|with|vs)|\bseries\b",
     "won at least 3 of the last 5 meetings",
     "Head-to-head is on the menu: say how many of the last meetings (1 to 10) it must have won."),
    (r"home[- ]?(?:field|court)? advantage|home form|home record|home games|away games|away record|road record|road form|road games|\bsplits?\b",
     "win rate at least 60% in games at the same kind of ground as today's",
     "A home or road record is on the menu as a win rate this season; say the percentage."),
    (r"offen[sc]|defen[sc]|scoring|runs allowed|points allowed|runs scored|points scored|\bpitching\b",
     "its offense ranks better than the opponent's defense",
     "Offense and defense are on the menu as league ranks and as runs or points per game, for example 'a top 10 defense' or "
     "'scores at least 4.5 runs per game'."),
    (r"\bbest\b|good teams?|strong teams?|top teams?|hot teams?|momentum|\btrends?\b|\bform\b",
     "won at least 4 of the last 5 games",
     "'Best' needs a measure the rules have: recent wins, a win streak, or a league rank in offense or defense."),
    (r"injur|lineups?|starters?|starting pitchers?|bullpens?|\bera\b|\bwhip\b|\bpitcher",
     None,
     "Starting pitchers, bullpens, lineups and injuries are not available to the rules yet, so they cannot be used."),
    (r"\bvalue\b|\bedge\b|expected value|\bev\b|kelly|\bmodel\b",
     None,
     "A dog does not compute value or edge. Describe the bet with a price range and conditions instead."),
)


def suggest(not_understood: Iterable[Mapping]) -> list:
    """[{phrase, try, why}] for the words the parser could not read: a wording it does read (or None, with the
    plain reason the idea is not on the menu), one entry per idea."""
    words = " ".join(str(item.get("text") or "") for item in not_understood).lower()
    out = []
    for rx, wording, why in _SUGGEST:
        m = re.search(rx, words)
        if m:
            out.append({"phrase": m.group(0), "try": wording, "why": why})
    return out


def parse(text: Any, *, players: Optional[Iterable[str]] = None) -> dict:
    """Read `text` into a version-2 spec draft. See the module docstring for the result."""
    if not isinstance(text, str) or not text.strip():
        return _result(None, {}, [], [{"text": "", "reason": "type a strategy to start"}], [], [])
    if len(text) > MAX_TEXT:
        out = _result(None, {}, [], [{"text": text[:40] + "...", "reason": f"keep it to {MAX_TEXT} characters or fewer"}], [], [])
        out["too_long"] = True
        return out
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    names = {R.fold_player(p) for p in players} if players is not None else _known_players()
    names = {n for n in names if len(n.split()) >= 2}
    rd = Reader(text, names)
    norm = normalise(text)

    box = [norm]
    read_globals(rd, box)
    whole = box[0]

    segments = [s for s in (p.strip(" ,") for p in _SPLIT.split(whole) if p) if s.strip(_PLACE + " ,")]
    rules = []
    for chunk in segments:
        seg = Seg(chunk)
        read_segment(rd, seg)
        rule = build_rule(rd, seg)
        if rule is not None:
            rules.append(rule)
    if len(rules) > R.MAX_RULES:
        rd.no("", f"a dog has at most {R.MAX_RULES} rules; the rest were left out")
        rules = rules[:R.MAX_RULES]

    draft: dict = {"version": user_spec.SPEC_VERSION_V2, "rules": rules}
    draft.update(rd.globals)
    spec = None
    if rules:
        try:
            spec = user_spec.validate_spec({**draft, "name": "Draft Dog"})
            spec["name"] = ""
        except user_spec.SpecError as exc:
            for field, msg in exc.errors.items():
                if field == "name":
                    continue
                rd.no(field, msg)
    return _result(spec, draft, rd.understood, rd.not_understood, rd.assumed, rules)


def _result(spec, draft, understood, not_understood, assumed, rules) -> dict:
    out = {"spec": spec, "draft": draft, "understood": understood, "not_understood": not_understood,
           "assumed": list(dict.fromkeys(assumed)), "complete": bool(spec) and not not_understood,
           "suggestions": suggest(not_understood), "max_text": MAX_TEXT}
    if spec:
        from src.hounds.english import render
        out["sentences"] = render.rule_sentences(spec) + render.global_sentences(spec)
    return out
