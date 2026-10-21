"""The facts layer: what the Gematria Hound is allowed to know about a team, read from ``config/gematria/team_facts.json``.

ABSENT IS ABSENT. Every fact in the file carries the URL it was read from (``scripts/build_gematria_facts.py``), and a
fact that could not be read is simply missing. This module never fills a gap: ``Team.name_texts`` yields only the
text fields that exist, ``Team.anchors`` only the dates that exist, and the signal generator turns no fact into no
quantity. A team the file has never heard of is a ``Team`` with nothing in it, which the decision then passes on.

POINT-IN-TIME. The facts here are standing facts (a founding date, a mascot, the state a club plays in) and the
CURRENT head coach. A coach can change; ``head_coach`` records the season it was read for, and the signal
generator only uses it for a game in that season. Anything that depends on results (a record entering the game, a
head-to-head history, a coach's wins with the club) is NOT here: it comes from our stored results, as of the lock
(``history.py``).

THE STATE TABLE below is the order of statehood (``STATE_ADMITTED``), written out once and held by a test, because the
posts lean on it ("Georgia is the 4th state"). Source: https://en.wikipedia.org/wiki/List_of_U.S._states_by_date_of_admission_to_the_Union
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.research import gematria

STATE_TABLE_SOURCE = "https://en.wikipedia.org/wiki/List_of_U.S._states_by_date_of_admission_to_the_Union"

# (name, postal code, admission date) in the order of statehood; the 1-based index is the "Nth state".
_STATES = (
    ("Delaware", "DE", "1787-12-07"), ("Pennsylvania", "PA", "1787-12-12"), ("New Jersey", "NJ", "1787-12-18"),
    ("Georgia", "GA", "1788-01-02"), ("Connecticut", "CT", "1788-01-09"), ("Massachusetts", "MA", "1788-02-06"),
    ("Maryland", "MD", "1788-04-28"), ("South Carolina", "SC", "1788-05-23"), ("New Hampshire", "NH", "1788-06-21"),
    ("Virginia", "VA", "1788-06-25"), ("New York", "NY", "1788-07-26"), ("North Carolina", "NC", "1789-11-21"),
    ("Rhode Island", "RI", "1790-05-29"), ("Vermont", "VT", "1791-03-04"), ("Kentucky", "KY", "1792-06-01"),
    ("Tennessee", "TN", "1796-06-01"), ("Ohio", "OH", "1803-03-01"), ("Louisiana", "LA", "1812-04-30"),
    ("Indiana", "IN", "1816-12-11"), ("Mississippi", "MS", "1817-12-10"), ("Illinois", "IL", "1818-12-03"),
    ("Alabama", "AL", "1819-12-14"), ("Maine", "ME", "1820-03-15"), ("Missouri", "MO", "1821-08-10"),
    ("Arkansas", "AR", "1836-06-15"), ("Michigan", "MI", "1837-01-26"), ("Florida", "FL", "1845-03-03"),
    ("Texas", "TX", "1845-12-29"), ("Iowa", "IA", "1846-12-28"), ("Wisconsin", "WI", "1848-05-29"),
    ("California", "CA", "1850-09-09"), ("Minnesota", "MN", "1858-05-11"), ("Oregon", "OR", "1859-02-14"),
    ("Kansas", "KS", "1861-01-29"), ("West Virginia", "WV", "1863-06-20"), ("Nevada", "NV", "1864-10-31"),
    ("Nebraska", "NE", "1867-03-01"), ("Colorado", "CO", "1876-08-01"), ("North Dakota", "ND", "1889-11-02"),
    ("South Dakota", "SD", "1889-11-02"), ("Montana", "MT", "1889-11-08"), ("Washington", "WA", "1889-11-11"),
    ("Idaho", "ID", "1890-07-03"), ("Wyoming", "WY", "1890-07-10"), ("Utah", "UT", "1896-01-04"),
    ("Oklahoma", "OK", "1907-11-16"), ("New Mexico", "NM", "1912-01-06"), ("Arizona", "AZ", "1912-02-14"),
    ("Alaska", "AK", "1959-01-03"), ("Hawaii", "HI", "1959-08-21"),
)
#: {state name: (order of statehood, admission date)}
STATE_ADMITTED: Dict[str, Tuple[int, str]] = {name: (i + 1, when) for i, (name, _code, when) in enumerate(_STATES)}
_STATE_BY_CODE = {code: name for name, code, _ in _STATES}
_STATE_BY_KEY = {gematria.normalize(name): name for name, _c, _w in _STATES}

CONFIG_DIR = "gematria"
FACTS_NAME = "team_facts.json"

#: the text fields a team contributes to the name pool, in a fixed order (the order is part of determinism)
NAME_FIELDS = ("name", "city", "mascot", "state", "university", "abbr", "head_coach")


def state_name(value: object) -> Optional[str]:
    """The full state name for a postal code or a name ("MA", "Massachusetts", "massachusetts"), else None."""
    text = str(value or "").strip()
    if not text:
        return None
    return _STATE_BY_CODE.get(text.upper()) or _STATE_BY_KEY.get(gematria.normalize(text))


def team_key(sport: str, name: object) -> str:
    """The one key a team goes by in the facts file and in every lookup: ``sport:lettersonly``."""
    return f"{str(sport or '').lower()}:{gematria.normalize(name)}"


@dataclass
class Anchor:
    """A dated fact a span can be counted from."""
    what: str                    # "team founded", "university founded", "state admitted"
    date: str                    # ISO date (day precision) or "YYYY" (year precision)
    precision: str               # "day" | "year"
    source: str = ""

    @property
    def year(self) -> int:
        return int(self.date[:4])


@dataclass
class Team:
    """Everything known about one team, all of it optional."""
    key: str = ""
    sport: str = ""
    name: str = ""
    texts: Dict[str, str] = field(default_factory=dict)         # field -> text, only the ones that exist
    state_order: Optional[int] = None
    coach_season: Optional[int] = None
    anchors: List[Anchor] = field(default_factory=list)
    numbers: List[Tuple[str, int]] = field(default_factory=list)      # (label, value): jersey numbers, area codes ... when the facts hold them
    known: bool = False

    def name_texts(self) -> List[Tuple[str, str]]:
        """[(field, text)] in ``NAME_FIELDS`` order, existing fields only."""
        return [(f, self.texts[f]) for f in NAME_FIELDS if self.texts.get(f)]


def _anchor(what: str, node: Optional[dict]) -> Optional[Anchor]:
    if not isinstance(node, dict) or not node.get("date") or node.get("precision") not in ("day", "year"):
        return None
    return Anchor(what, str(node["date"]), node["precision"], str(node.get("source") or ""))


def build_team(sport: str, entry: Optional[dict], fallback_name: str = "") -> Team:
    if not isinstance(entry, dict):
        return Team(key=team_key(sport, fallback_name), sport=sport, name=fallback_name)
    team = Team(key=team_key(sport, entry.get("name") or fallback_name), sport=sport,
                name=str(entry.get("name") or fallback_name), known=True)
    team.texts["name"] = team.name

    def value(field_name: str) -> Optional[str]:
        node = entry.get(field_name)
        v = node.get("value") if isinstance(node, dict) else None
        return str(v) if v else None

    for fname in ("city", "mascot", "university", "abbr"):
        v = value(fname)
        if v:
            team.texts[fname] = v
    v = value("state")
    if v and state_name(v):
        team.texts["state"] = state_name(v)
        order = STATE_ADMITTED[state_name(v)]
        team.state_order = order[0]
        team.anchors.append(Anchor("state admitted", order[1], "day", STATE_TABLE_SOURCE))
    coach = entry.get("head_coach")
    if isinstance(coach, dict) and coach.get("value"):
        team.texts["head_coach"] = str(coach["value"])
        if isinstance(coach.get("season"), int):
            team.coach_season = coach["season"]
    for n in entry.get("numbers") or ():
        if isinstance(n, dict) and isinstance(n.get("value"), int) and n.get("label"):
            team.numbers.append((str(n["label"]), n["value"]))
    for what, f in (("team founded", "founded"), ("university founded", "university_founded")):
        a = _anchor(what, entry.get(f))
        if a:
            team.anchors.append(a)
    return team


class FactsBook:
    """The loaded file, indexed by team key and by alias key."""

    def __init__(self, data: Optional[dict] = None):
        self.data = data or {}
        teams = self.data.get("teams") or {}
        self._index: Dict[str, dict] = {}
        for key, entry in teams.items():
            self._index[key] = entry
            sport = str(entry.get("sport") or key.split(":", 1)[0])
            for alias in entry.get("aliases") or ():
                self._index.setdefault(team_key(sport, alias), entry)

    def __len__(self) -> int:
        return len({id(e) for e in self._index.values()})

    def team(self, sport: str, name: object) -> Team:
        """The team for a feed name; an unknown team is an empty ``Team`` (``known`` False), never an error."""
        text = str(name or "")
        return build_team(sport, self._index.get(team_key(sport, text)), text)

    def canonical_name(self, sport: str, name: object) -> str:
        """The name the stored results use for a feed name ("Los Angeles Clippers" -> "LA Clippers"); the name itself
        when the team is unknown."""
        entry = self._index.get(team_key(sport, name))
        return str(entry.get("name")) if entry and entry.get("name") else str(name or "")

    def sports(self) -> List[str]:
        return sorted({str(e.get("sport")) for e in self._index.values()})


def facts_path(root: Optional[Path] = None) -> Path:
    from src import paths

    return (Path(root) if root else Path(paths.repo_root())) / "config" / CONFIG_DIR / FACTS_NAME


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> FactsBook:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return FactsBook(data if isinstance(data, dict) else {})


def load(path: Optional[Path] = None) -> FactsBook:
    """The facts book, cached on (path, mtime) so an edited file is re-read. A missing or unreadable file is an
    EMPTY book (every team unknown), which makes the hound pass everything, not crash."""
    p = Path(path) if path else facts_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return FactsBook({})
    return _load_cached(str(p), mtime)
