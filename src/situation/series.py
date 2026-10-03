"""Postseason series, rebuilt from game results.

WHY THIS EXISTS
---------------
The results store holds games, not series: a row says who played whom on a date and
who won, with the round in `game_type` (F Wild Card, D Division Series, L League
Championship Series, W World Series). Everything a postseason situation needs (what
the series stands at, whether this is an elimination game, who had a bye, how long and
how recently the previous round ended) is a statement about a series, so it is rebuilt
here, once, and shared by the game-level builder (`mlb.py`) and the historical test
(`rest_vs_rhythm.py`). Two clubs meet at most once in a round of a season, so a series
is `(season, round, the two clubs)` and needs no id the store does not carry.

THE CUT-OFF IS APPLIED HERE
---------------------------
`build_series(rows, before=D)` reads only rows dated strictly before D, so the state it
returns is the state going into a game on D. A series that has games on or after D is
simply shorter, and may be incomplete: the same function that rebuilds a finished
series for the historical test gives the series state the day of any game in it.

FORMATS CHANGE, SO THE LENGTH IS A FACT ABOUT A SEASON
-------------------------------------------------------
Division Series are best of five (three wins), League Championship Series and World
Series best of seven (four), in every season this code reads. The Wild Card round is
the one that moved: a single game from 2012 to 2019 and in 2021, a best-of-three in 2020
(all sixteen clubs played it, no byes) and from 2022 (six clubs a league, the top two
seeds rest). `wins_needed` and `wild_card_series_expected` carry that, with the season
named, so no season is read with another's format. A row that carries `games_in_series`
(the display store does) overrides the table for that series.

A BYE IS NOT A FACT THE STORE STATES
------------------------------------
A club that played no Wild Card game had a bye only if the Wild Card round is fully in
the data. With the round missing or partly missing (an ingest that stopped, a store that
starts too late) a club absent from it is UNKNOWN, not rested, and `bye_or_played` says
so instead of guessing.

Pure: rows in, series out. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

REGULAR = "R"
POSTSEASON_TYPES = ("F", "D", "L", "W")          # in the order the rounds are played
ROUND_NAMES = {"F": "Wild Card Series", "D": "Division Series",
               "L": "League Championship Series", "W": "World Series"}
SHORT_ROUND = {"F": "wild card", "D": "division series", "L": "league championship series",
               "W": "world series"}

# Seasons whose Wild Card round was a single game: 2012 (the format's first year) to 2019,
# and 2021. 2020 was a best-of-three among sixteen clubs with no byes; 2022 on is the
# six-club format with a best-of-three and byes for the top two seeds.
SINGLE_GAME_WILD_CARD_SEASONS = frozenset(set(range(2012, 2020)) | {2021})

_WINS_NEEDED = {"D": 3, "L": 4, "W": 4}


# ---------------------------------------------------------------------------
# row helpers (rows are the results store's: strings from a CSV are fine)
# ---------------------------------------------------------------------------

def to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def row_date(row: Mapping) -> Optional[str]:
    """The row's date as an ISO date string, or None when it is missing or unreadable."""
    text = str(row.get("date") or "").strip()[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def season_of(row: Mapping) -> Optional[int]:
    d = row_date(row)
    return int(d[:4]) if d else None


def days_between(earlier: str, later: str) -> int:
    """Whole days from one ISO date to another (later minus earlier)."""
    return (date.fromisoformat(later[:10]) - date.fromisoformat(earlier[:10])).days


def runs_of(row: Mapping) -> tuple:
    """(away runs, home runs), each None when the store has no usable score."""
    return to_int(row.get("away_score")), to_int(row.get("home_score"))


def winner_of(row: Mapping) -> Optional[str]:
    """The winning club's abbreviation. A tie, an unscored game or a stored winner
    that is neither club has none: such a game is never counted as a win for anyone."""
    away, home = row.get("away_team"), row.get("home_team")
    a, h = runs_of(row)
    if a is not None and h is not None and a != h:
        return away if a > h else home
    stored = row.get("winner")
    if stored in (away, home) and (a is None or h is None):
        return stored
    return None


def sort_key(row: Mapping) -> tuple:
    return (row_date(row) or "", str(row.get("start_time_utc") or ""), to_int(row.get("game_pk")) or 0)


def played_by(row: Mapping, team: str) -> bool:
    return team in (row.get("away_team"), row.get("home_team"))


def opponent_in(row: Mapping, team: str) -> Optional[str]:
    if row.get("away_team") == team:
        return row.get("home_team")
    if row.get("home_team") == team:
        return row.get("away_team")
    return None


# ---------------------------------------------------------------------------
# formats
# ---------------------------------------------------------------------------

def wins_needed(season: int, game_type: str, games_in_series: Optional[int] = None) -> int:
    """Wins that end a series of this round in this season."""
    if games_in_series:
        return games_in_series // 2 + 1
    if game_type == "F":
        return 1 if season in SINGLE_GAME_WILD_CARD_SEASONS else 2
    return _WINS_NEEDED[game_type]


def series_length_words(season: int, game_type: str, games_in_series: Optional[int] = None) -> str:
    """"single game", "best of 3", "best of 5", "best of 7" for display."""
    needed = wins_needed(season, game_type, games_in_series)
    return "a single game" if needed == 1 else f"best of {2 * needed - 1}"


def wild_card_series_expected(season: int) -> int:
    """How many Wild Card series (or games) a season's bracket holds."""
    if season in SINGLE_GAME_WILD_CARD_SEASONS:
        return 2
    if season == 2020:
        return 8
    return 4


def previous_round(game_type: str) -> Optional[str]:
    i = POSTSEASON_TYPES.index(game_type) if game_type in POSTSEASON_TYPES else -1
    return POSTSEASON_TYPES[i - 1] if i > 0 else None


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Series:
    """One round's meeting of two clubs in one season, from the games `build_series` was given."""
    season: int
    game_type: str
    teams: tuple                 # the two abbreviations, sorted
    games: tuple                 # result rows, chronological, each with a winner
    needed: int                  # wins that end it

    @property
    def wins(self) -> dict:
        out = {t: 0 for t in self.teams}
        for g in self.games:
            w = winner_of(g)
            if w in out:
                out[w] += 1
        return out

    @property
    def winner(self) -> Optional[str]:
        wins = self.wins
        top = max(wins.values())
        leaders = [t for t, n in wins.items() if n == top]
        return leaders[0] if top >= self.needed and len(leaders) == 1 else None

    @property
    def loser(self) -> Optional[str]:
        w = self.winner
        return None if w is None else next(t for t in self.teams if t != w)

    @property
    def complete(self) -> bool:
        return self.winner is not None

    @property
    def length(self) -> int:
        return len(self.games)

    @property
    def first_date(self) -> str:
        return row_date(self.games[0])

    @property
    def last_date(self) -> str:
        return row_date(self.games[-1])

    @property
    def name(self) -> str:
        return ROUND_NAMES[self.game_type]


def build_series(rows: Iterable[Mapping], *, before: Optional[str] = None) -> list:
    """Every postseason series the rows hold, oldest first.

    `before` (an ISO date) keeps only games dated strictly before it. A row without a
    readable date, a decided winner or both clubs is skipped: it cannot be placed in a
    series or counted for anyone.
    """
    groups: dict = {}
    for row in rows:
        gt = row.get("game_type")
        d = row_date(row)
        if gt not in POSTSEASON_TYPES or d is None:
            continue
        if before is not None and not d < before[:10]:
            continue
        away, home = row.get("away_team"), row.get("home_team")
        if not away or not home or away == home or winner_of(row) is None:
            continue
        season = int(d[:4])
        groups.setdefault((season, gt, tuple(sorted((away, home)))), {})[str(row.get("game_pk") or id(row))] = row
    out = []
    for (season, gt, teams), games in groups.items():
        ordered = tuple(sorted(games.values(), key=sort_key))
        length = to_int(ordered[-1].get("games_in_series")) or None
        out.append(Series(season=season, game_type=gt, teams=teams, games=ordered,
                          needed=wins_needed(season, gt, length)))
    out.sort(key=lambda s: (s.first_date, POSTSEASON_TYPES.index(s.game_type), s.teams))
    return out


def series_of_team(all_series: Sequence[Series], team: str, *, season: Optional[int] = None,
                   game_type: Optional[str] = None) -> list:
    return [s for s in all_series if team in s.teams
            and (season is None or s.season == season)
            and (game_type is None or s.game_type == game_type)]


def wild_card_round_complete(all_series: Sequence[Series], season: int) -> bool:
    """Is a season's whole Wild Card round in the data, every series decided?"""
    wc = [s for s in all_series if s.season == season and s.game_type == "F"]
    return len(wc) >= wild_card_series_expected(season) and all(s.complete for s in wc)


def bye_or_played(all_series: Sequence[Series], team: str, season: int, game_type: str) -> tuple:
    """`(status, series)` for a club going into a round: "played" with the series it
    came through, "bye" (Division Series only, and only when the Wild Card round is fully
    in the data), "none" for a round with no round before it (Wild Card), or "unknown"
    when the data cannot say."""
    prev = previous_round(game_type)
    if prev is None:
        return "none", None
    mine = [s for s in series_of_team(all_series, team, season=season, game_type=prev)]
    if mine:
        return "played", sorted(mine, key=lambda s: s.last_date)[-1]
    if game_type == "D" and wild_card_round_complete(all_series, season):
        return "bye", None
    return "unknown", None
