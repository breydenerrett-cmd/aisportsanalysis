"""Point-in-time results for the Gematria Hound: what our STORES say had happened by the lock, and nothing else.

THE RULE. A number the hound counts ("Seattle's 6th win", "weeks since Atlanta last won at home") is derived only from
finished games in our own stored results whose start was at least ``FINISH_LAG`` before the lock. That is the same
discipline ``pack.base.build_context`` applies to the rule hounds' MLB and NFL history (five and six hours), applied
here to every family. Nothing that happens after the lock can reach a count: ``games_before`` takes the cutoff as an
argument and a test pins that a result after it changes nothing.

WHERE THE RESULTS COME FROM
  MLB / NFL   the Context the pack runner built (``ctx.mlb_games`` / ``ctx.nfl_games``), which is already filtered
              to the lock and, for MLB, never reads the sealed window (2026-01-01..2026-08-27).
  NBA / NHL / college football / EPL   the ESPN store (``data/datasvc/espn/<league>/games_<season>.jsonl``), read lazily
              and cached. The newest stored version of each game is used; only a finished game counts.
  everything else   no stored results. The hound then has no counts for those teams and PASSES (``no_history``);
              it does not invent a record.

WHAT "THE SEASON" IS. The run of regular-season games with no gap over ``SEASON_GAP_DAYS`` ending at the cutoff. That
needs no per-sport calendar and cannot reach back into a previous season, because every sport rests longer than that.

COACHES. Only the NFL store names the coach of each game (nflverse); the count of a coach's wins with a club is
therefore available for the NFL only, labelled "in our store" (2021 onward) because it is not the coach's career.
For other sports the head coach is a NAME in the facts layer and nothing is counted from it.

Stdlib plus the repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.hounds.pack import base
from src.research import gematria

FINISH_LAG = timedelta(hours=6)           # a game that started this long before the lock is over (NFL's own lag; longest game)
SEASON_GAP_DAYS = 100
ESPN_LEAGUES = {"nba": "nba", "nhl": "nhl", "ncaaf": "ncaaf"}      # row sport -> ESPN store folder
EPL_FOLDER = "epl"
EPL_TITLE_MARK = "premier league"


@dataclass(frozen=True)
class Game:
    start: datetime
    date: str                        # Eastern calendar date of the start
    home: str                        # team id (club code for MLB/NFL, normalised ESPN name otherwise)
    away: str
    hs: int
    as_: int
    regular: bool = True
    neutral: bool = False
    home_coach: Optional[str] = None
    away_coach: Optional[str] = None

    def involves(self, tid: str) -> bool:
        return tid in (self.home, self.away)

    def result_for(self, tid: str) -> str:
        mine, theirs = (self.hs, self.as_) if tid == self.home else (self.as_, self.hs)
        return "W" if mine > theirs else ("L" if mine < theirs else "T")

    def venue_of(self, tid: str) -> str:
        return "home" if tid == self.home else "away"

    def opponent(self, tid: str) -> str:
        return self.away if tid == self.home else self.home

    def coach_of(self, tid: str) -> Optional[str]:
        return self.home_coach if tid == self.home else self.away_coach


@dataclass
class Past:
    """What a source knew at the cutoff for one game: the finished games and the two team ids."""
    games: List[Game] = field(default_factory=list)
    home_id: Optional[str] = None
    away_id: Optional[str] = None
    scope: str = ""                  # words for the evidence panel: where the counts come from
    available: bool = False


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

def _mlb_games(ctx: base.Context, cutoff: datetime) -> List[Game]:
    out = []
    for g in ctx.mlb_games:
        hs, as_ = _int(g.get("home_score")), _int(g.get("away_score"))
        start = base.parse_utc(g.get("start_utc"))
        if hs is None or as_ is None or not g.get("home") or not g.get("away"):
            continue
        if start is None:                      # a results row with no start time: placed at noon UTC of its date
            start = datetime.fromisoformat(g["date"] + "T12:00:00+00:00")
        if start >= cutoff:                    # at or after lock - FINISH_LAG: not counted
            continue
        out.append(Game(start=start, date=str(g["date"]), home=g["home"], away=g["away"], hs=hs, as_=as_,
                        regular=(g.get("game_type") in (None, "R"))))
    return sorted(out, key=lambda g: g.start)


def _nfl_games(ctx: base.Context, cutoff: datetime) -> List[Game]:
    out = []
    for r in ctx.nfl_games:
        start = base.parse_utc(r.get("kickoff_utc"))
        hs, as_ = _int(r.get("home_score")), _int(r.get("away_score"))
        if start is None or start >= cutoff or hs is None or as_ is None or r.get("status") != "final":
            continue
        out.append(Game(start=start, date=base.eastern_date(start), home=r["home_team"], away=r["away_team"], hs=hs,
                        as_=as_, regular=(r.get("game_type") == "REG"), neutral=bool(r.get("neutral_site")),
                        home_coach=r.get("home_coach") or None, away_coach=r.get("away_coach") or None))
    return sorted(out, key=lambda g: g.start)


class EspnStore:
    """The ESPN store's games for one league folder, newest version of each game, finished only. Cached by file
    mtimes so a long-lived process sees the capture slot's appends. ``root`` is injectable for tests."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else None
        self._cache: Dict[str, tuple] = {}

    def _root(self) -> Path:
        if self.root is not None:
            return self.root
        from src import paths

        return Path(paths.data_path("datasvc", "espn"))

    def games(self, folder: str) -> List[dict]:
        d = self._root() / folder
        files = sorted(d.glob("games_*.jsonl")) if d.is_dir() else []
        stamp = tuple((f.name, f.stat().st_mtime, f.stat().st_size) for f in files)
        hit = self._cache.get(folder)
        if hit and hit[0] == stamp:
            return hit[1]
        newest: Dict[str, dict] = {}
        for f in files:
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    gid = str(r.get("game_id"))
                    if gid not in newest or str(r.get("observed_utc") or "") >= str(newest[gid].get("observed_utc") or ""):
                        newest[gid] = r
        rows = list(newest.values())
        self._cache[folder] = (stamp, rows)
        return rows


def _espn_game(r: Mapping, tid_of: Callable[[object], str], cutoff: datetime) -> Optional[Game]:
    if not r.get("completed"):
        return None
    start = base.parse_utc(r.get("date_utc"))
    hs, as_ = _int(r.get("home_score")), _int(r.get("away_score"))
    if start is None or start >= cutoff or hs is None or as_ is None:
        return None
    slug = str(r.get("season_slug") or "")
    regular = slug == "regular-season" or slug.endswith("english-premier-league")
    return Game(start=start, date=base.eastern_date(start), home=tid_of(r.get("home_name")),
                away=tid_of(r.get("away_name")), hs=hs, as_=as_, regular=regular, neutral=bool(r.get("neutral_site")))


class Disk:
    """The default history source: the Context for MLB and NFL, the ESPN store for NBA, NHL, college football and the EPL.

    ``canonical`` maps a feed team name to the name the stored results use (the facts layer's aliases)."""

    def __init__(self, espn: Optional[EspnStore] = None, canonical: Optional[Callable[[str, str], str]] = None):
        self.espn = espn or EspnStore()
        self.canonical = canonical or (lambda sport, name: name)

    def past(self, ctx: base.Context) -> Past:
        cutoff = ctx.lock - FINISH_LAG
        if ctx.sport == "mlb":
            return Past(_mlb_games(ctx, cutoff), ctx.home, ctx.away,
                        "our MLB results store, from 2026-08-28", available=bool(ctx.home and ctx.away))
        if ctx.sport == "nfl":
            return Past(_nfl_games(ctx, cutoff), ctx.home, ctx.away, "our NFL store, 2021 onward",
                        available=bool(ctx.home and ctx.away))
        folder = ESPN_LEAGUES.get(ctx.sport)
        if folder is None and ctx.sport == "soccer" and EPL_TITLE_MARK in str(ctx.league or "").lower():
            folder = EPL_FOLDER
        if folder is None:
            return Past(scope="no results store for this sport")

        def tid_of(name):
            return gematria.normalize(self.canonical(ctx.sport, str(name or "")))

        games = [g for g in (_espn_game(r, tid_of, cutoff) for r in self.espn.games(folder)) if g]
        games.sort(key=lambda g: g.start)
        home_id, away_id = tid_of(ctx.home_name), tid_of(ctx.away_name)
        return Past(games, home_id, away_id, f"the ESPN {folder.upper()} store",
                    available=bool(self.espn.games(folder)) and bool(home_id and away_id))


# ---------------------------------------------------------------------------
# summaries (pure)
# ---------------------------------------------------------------------------

def current_season(games: Sequence[Game], tid: str) -> List[Game]:
    """The team's regular-season games in the current season: walking back from the newest, stop at a gap over
    ``SEASON_GAP_DAYS``. Oldest first."""
    mine = [g for g in games if g.regular and g.involves(tid)]
    out: List[Game] = []
    for g in reversed(mine):
        if out and (out[-1].start - g.start) > timedelta(days=SEASON_GAP_DAYS):
            break
        out.append(g)
    return list(reversed(out))


@dataclass
class TeamState:
    """A team's season-to-date and its gaps since its last events, as of the cutoff."""
    tid: str
    n: int = 0
    w: int = 0
    l: int = 0
    t: int = 0
    home_w: int = 0
    home_l: int = 0
    road_w: int = 0
    road_l: int = 0
    streak_kind: Optional[str] = None       # "W" | "L" | "T" of the newest game
    streak_len: int = 0
    last_win: Optional[str] = None          # ISO dates (Eastern) of the newest game of each kind
    last_loss: Optional[str] = None
    last_home_win: Optional[str] = None
    last_road_win: Optional[str] = None
    last_home_loss: Optional[str] = None
    last_road_loss: Optional[str] = None
    coach: Optional[str] = None             # the coach of the newest stored game (NFL only)
    coach_w: int = 0                        # that coach's record with this club in our store (NFL only)
    coach_l: int = 0
    coach_n: int = 0


def team_state(games: Sequence[Game], tid: str) -> TeamState:
    st = TeamState(tid=tid)
    season = current_season(games, tid)
    for g in season:
        res, venue = g.result_for(tid), g.venue_of(tid)
        st.n += 1
        if res == "W":
            st.w += 1
            st.last_win = g.date
            if venue == "home":
                st.home_w += 1
                st.last_home_win = g.date
            else:
                st.road_w += 1
                st.last_road_win = g.date
        elif res == "L":
            st.l += 1
            st.last_loss = g.date
            if venue == "home":
                st.home_l += 1
                st.last_home_loss = g.date
            else:
                st.road_l += 1
                st.last_road_loss = g.date
        else:
            st.t += 1
        if res == st.streak_kind:
            st.streak_len += 1
        else:
            st.streak_kind, st.streak_len = res, 1
    # the coach: from the newest stored game that names one (NFL), then that coach's whole record with the club
    stored = [g for g in games if g.involves(tid) and g.coach_of(tid)]
    if stored:
        coach = stored[-1].coach_of(tid)
        st.coach = coach
        for g in stored:
            if g.coach_of(tid) == coach and g.regular:
                st.coach_n += 1
                res = g.result_for(tid)
                st.coach_w += res == "W"
                st.coach_l += res == "L"
    return st


@dataclass
class Series:
    """Head-to-head from the stored games between two teams (any season in the store, regular and post)."""
    a: str
    b: str
    meetings: int = 0
    a_wins: int = 0
    b_wins: int = 0
    last_meeting: Optional[str] = None
    last_a_win: Optional[str] = None
    last_b_win: Optional[str] = None
    a_streak: int = 0                    # consecutive newest meetings won by a (0 when b won the newest)
    b_streak: int = 0


def head_to_head(games: Sequence[Game], a: str, b: str) -> Series:
    s = Series(a, b)
    for g in games:
        if {g.home, g.away} != {a, b}:
            continue
        s.meetings += 1
        s.last_meeting = g.date
        res = g.result_for(a)
        if res == "W":
            s.a_wins += 1
            s.last_a_win = g.date
            s.a_streak, s.b_streak = s.a_streak + 1, 0
        elif res == "L":
            s.b_wins += 1
            s.last_b_win = g.date
            s.b_streak, s.a_streak = s.b_streak + 1, 0
        else:
            s.a_streak = s.b_streak = 0
    return s


def days_between(earlier: Optional[str], later: str) -> Optional[int]:
    if not earlier:
        return None
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
