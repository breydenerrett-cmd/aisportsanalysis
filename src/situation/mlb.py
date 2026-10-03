"""`situation_for_game`: the bigger picture around one MLB game.

WHAT IT READS AND WHAT IT NEVER DOES
------------------------------------
It reads the game itself (who, where, when, the probable starters the schedule names)
and a list of finished games from the results store (`data/historical/mlb_results.csv`,
which starts on 2023-03-30). It reads nothing else: no clock, no disk, no network, no
pitcher log (`pitchers.regular_season_logs` guards model inputs from postseason starts,
and this record needs the postseason starts, so it takes them from the results store's own
probable-starter columns and says so). Everything older than the store is MISSING, never
guessed: a drought "since 2019" is only stated when a store that reaches back to 2019 was
supplied (`extra_games`, the display-only postseason history).

THE CUT-OFF: A GAME ON THE DAY AND LATER NEVER COUNTS
-----------------------------------------------------
The record is drawn as of the game's DATE: only games dated strictly before it are read.
That includes the first half of a doubleheader (the second game says so and leaves the
rest and rhythm facts out, because a day count would be wrong by a day), and the game
itself and anything after it when a finished game is re-analysed later. Every factor's
`as_of` is the date of the newest game it used, and `record.problems` fails a factor
stamped on or after the cut-off.

A STALE STORE IS NOT SILENTLY WRONG
-----------------------------------
"Played yesterday" is only true if yesterday is in the store. If the dates between the
store's newest game and this game are not all confirmed fetched (`covered_dates`, the
ingest manifest), the facts that depend on the last few days (rest and rhythm, form,
the series score, who started) are LEFT OUT and listed as missing with the dates. Without
a manifest the rule is cruder: more than three days between the newest stored game and
this one is stale (a league-wide break that long is rare, and a missing day is worse).
The facts that depend on the long record (pressure history, head to head, the park) are
kept: a day missing from them changes a sample by one game, and they say their sample.

FAMILIES, AS BUILT
------------------
rest_and_rhythm    days since each club's last game, games in the last 7 days, miles from where
                   it last played, and in the postseason whether it had a bye or came through
                   the round before (that series' score, length and how long ago it ended)
form               each club's last 5 and last 10 results with run margin, current streak, runs
                   a game over the last 10 against the regular season
stakes             the series score and game number, whether either club faces elimination, how
                   long since each club won a postseason series (within what the data covers)
pressure_history   each club's postseason game and series record in the data against its
                   regular-season win rate in the same seasons
head_to_head       this season's meetings and the last three
availability       who started each of the club's games in the previous round, and how long since
                   each probable starter last started (this season, postseason included)
venue              the park and its roof

WHAT THE DATA CANNOT SAY (listed in `missing` every time it matters): managers and their
records, injuries, line moves and the public's side, and the playoff race in the regular
season.

Pure: no I/O. Stdlib only.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence

from src.data import parks
from src.pipeline import travel
from src.situation import record as rec
from src.situation import series as ser

SPORT = "mlb"
FAMILIES = ("rest_and_rhythm", "form", "stakes", "pressure_history", "head_to_head",
            "availability", "venue")
SIDES = ("away", "home")

# Form windows, and how many recent games make the "recent runs a game" figure.
FORM_WINDOWS = (5, 10)
RECENT_RUNS_WINDOW = 10
# Days a rhythm count looks back.
RHYTHM_DAYS = 7
# Meetings listed under head to head.
LAST_MEETINGS = 3
# Without an ingest manifest, this many days between the newest stored game and the game
# are taken to be a stale store.
STALE_WITHOUT_MANIFEST_DAYS = 3
# A "starts in the last N days" window for a probable starter.
STARTER_WINDOW_DAYS = 30
# A park this high is worth saying so; below it altitude is not a factor in a sentence.
ALTITUDE_NOTE_M = 1000

COMPARE_ONLY = ("R",) + ser.POSTSEASON_TYPES

_ROOF_WORDS = {
    "open": "an open-air park",
    "retractable": "a park with a retractable roof, so the weather may or may not matter",
    "fixed": "a fixed-roof park, so the weather does not matter",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _canon(team: Any) -> str:
    """One spelling per franchise ("ATH" and "OAK", "AZ" and "ARI"), so a club's history
    does not split across the years the feed spelled it differently."""
    try:
        return parks.canonical_team(team)
    except parks.ParkError:
        return str(team or "").strip().upper()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _days(n: int) -> str:
    return _plural(n, "day")


def _rate(x: float, places: int = 1) -> str:
    return f"{x:.{places}f}"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _round_name(game_type: str) -> str:
    return ser.ROUND_NAMES.get(game_type, "game")


def _normalize(rows: Iterable[Mapping]) -> list:
    """Copies of the rows we can use, clubs under one spelling, in date order. A row with
    no readable date, an unknown game type or no clubs is not usable."""
    seen: dict = {}
    for row in rows:
        d = ser.row_date(row)
        if d is None or row.get("game_type") not in COMPARE_ONLY:
            continue
        away, home = _canon(row.get("away_team")), _canon(row.get("home_team"))
        if not away or not home or away == home:
            continue
        copy = dict(row)
        copy.update(date=d, away_team=away, home_team=home)
        if copy.get("winner"):
            copy["winner"] = _canon(copy["winner"])
        pk = str(row.get("game_pk") or "")
        key = pk or f"{d}|{away}|{home}|{row.get('start_time_utc')}"
        seen[key] = copy
    out = list(seen.values())
    out.sort(key=ser.sort_key)
    return out


def _persp(row: Mapping, team: str) -> Optional[dict]:
    """One finished game from a club's side, or None when it has no usable score."""
    a, h = ser.runs_of(row)
    if a is None or h is None or a == h:
        return None
    if team == row["home_team"]:
        rf, ra, home, opp = h, a, True, row["away_team"]
    elif team == row["away_team"]:
        rf, ra, home, opp = a, h, False, row["home_team"]
    else:
        return None
    return {"date": row["date"], "rf": rf, "ra": ra, "win": rf > ra, "home": home, "opp": opp,
            "type": row.get("game_type"), "row": row}


def _starter_of(row: Mapping, team: str) -> tuple:
    """(name, id) of the starter the schedule listed for `team` in this game."""
    if team == row["away_team"]:
        return row.get("away_probable"), ser.to_int(row.get("away_probable_id"))
    if team == row["home_team"]:
        return row.get("home_probable"), ser.to_int(row.get("home_probable_id"))
    return None, None


class _Ctx:
    """Everything the factor builders share: the game, the rows before it, the clubs."""

    def __init__(self, game: Mapping, results: Iterable[Mapping], extra: Iterable[Mapping],
                 season_records: Optional[Mapping], covered_dates: Optional[Iterable[str]]):
        d = ser.row_date(game)
        if d is None:
            raise ValueError("the game has no readable date")
        self.game = game
        self.date = d
        self.season = int(d[:4])
        self.gtype = game.get("game_type") or ser.REGULAR
        self.pk = str(game.get("game_pk") or "")
        self.away_label, self.home_label = str(game.get("away_team") or ""), str(game.get("home_team") or "")
        self.away, self.home = _canon(self.away_label), _canon(self.home_label)
        if not self.away or not self.home or self.away == self.home:
            raise ValueError("the game does not name two different clubs")
        self.label = {self.away: self.away_label or self.away, self.home: self.home_label or self.home}
        self.sides = {"away": self.away, "home": self.home}
        self.season_records = dict(season_records or {})

        main = _normalize(results)
        other = _normalize(extra)
        # The main store wins where both hold a game; the cut-off applies to both.
        by_pk = {str(r.get("game_pk")): r for r in other if r.get("game_pk")}
        by_pk.update({str(r.get("game_pk")): r for r in main if r.get("game_pk")})
        no_pk = [r for r in other + main if not r.get("game_pk")]
        merged = sorted(list(by_pk.values()) + no_pk, key=ser.sort_key)
        self.rows = [r for r in merged if r["date"] < self.date and str(r.get("game_pk") or "") != self.pk]
        main_rows = [r for r in main if r["date"] < self.date]
        self.store_starts = main[0]["date"] if main else None
        self.through = main_rows[-1]["date"] if main_rows else None
        self.by_team: dict = {}
        for r in self.rows:
            self.by_team.setdefault(r["away_team"], []).append(r)
            self.by_team.setdefault(r["home_team"], []).append(r)
        self.series = ser.build_series(self.rows)
        self.covered = None if covered_dates is None else set(covered_dates)
        self.stale_reason = self._stale()
        dh = str(game.get("double_header") or "").upper()
        self.second_of_doubleheader = dh in ("Y", "S") and ser.to_int(game.get("game_number")) == 2

    # -- freshness -------------------------------------------------------------------

    def _stale(self) -> Optional[str]:
        if self.through is None:
            return "the results store has no game before this one"
        gap = ser.days_between(self.through, self.date)
        if self.covered is not None:
            start = date.fromisoformat(self.through)
            end = date.fromisoformat(self.date)
            absent = []
            d = start + timedelta(days=1)
            while d < end:
                if d.isoformat() not in self.covered:
                    absent.append(d.isoformat())
                d += timedelta(days=1)
            if absent:
                shown = ", ".join(absent[:3]) + (" and later" if len(absent) > 3 else "")
                return (f"the results store has no confirmed fetch for {shown}, so the last "
                        f"{_days(gap)} before this game may be missing")
            return None
        if gap > STALE_WITHOUT_MANIFEST_DAYS:
            return (f"the results store ends {self.through}, {_days(gap)} before this game, "
                    "and nothing says the days between were off days")
        return None

    # -- lookups ---------------------------------------------------------------------

    def team_rows(self, team: str, *, same_season: bool = False) -> list:
        rows = self.by_team.get(team, [])
        if same_season:
            rows = [r for r in rows if int(r["date"][:4]) == self.season]
        return rows

    def label_of(self, team: str) -> str:
        return self.label.get(team, team)

    def source_games(self, rows: Sequence[Mapping], what: str) -> str:
        if not rows:
            return f"results store: {what}"
        first, last = rows[0]["date"], rows[-1]["date"]
        if first == last:
            return f"results store: {what} ({first})"
        return f"results store: {what} ({first} to {last})"


# ---------------------------------------------------------------------------
# rest and rhythm
# ---------------------------------------------------------------------------

STALE_LEFT_OUT = "left out: the results store is not current (see results_store_current)"


def _rest(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "rest_and_rhythm"
    if ctx.second_of_doubleheader:
        gaps.append(rec.gap(fam, "earlier_game_today",
                            "this is game 2 of a doubleheader: today's first game is not read, so rest "
                            "and rhythm are left out and form runs through yesterday"))
        return
    if ctx.stale_reason:
        gaps.append(rec.gap(fam, "days_since_last_game", STALE_LEFT_OUT))
        return
    for side in SIDES:
        team = ctx.sides[side]
        label = ctx.label_of(team)
        games = ctx.team_rows(team, same_season=True)
        if not games:
            gaps.append(rec.gap(fam, "days_since_last_game",
                                f"{label} has no earlier game this season in the store (the opener)", side=side))
            continue
        last = games[-1]
        n = ser.days_between(last["date"], ctx.date)
        if n == 1:
            sentence = f"{label} played yesterday ({last['date']})."
        elif n == 2:
            sentence = f"{label} had a day off: it last played on {last['date']}, 2 days earlier."
        else:
            sentence = (f"{label} last played {n} days earlier ({last['date']}), "
                        f"{n - 1} days off.")
        out.append(rec.factor(fam, "days_since_last_game", n, "days", sample={"games": 1},
                              as_of=last["date"], side=side,
                              source=ctx.source_games([last], "the club's last game before this one"),
                              sentence=sentence, detail={"days_off": n - 1, "last_game_date": last["date"]}))
        recent = [g for g in games if ser.days_between(g["date"], ctx.date) <= RHYTHM_DAYS]
        k = len(recent)
        out.append(rec.factor(
            fam, "games_last_7_days", k, "games", sample={"days": RHYTHM_DAYS}, as_of=last["date"], side=side,
            source=ctx.source_games(recent or [last], f"{label}'s games in the {RHYTHM_DAYS} days before this one"),
            sentence=(f"{label} played no games in the last {RHYTHM_DAYS} days." if k == 0 else
                      f"{label} played {_plural(k, 'game')} in the last {RHYTHM_DAYS} days.")))
        # Miles from the park it last played in. The park is the home club's.
        try:
            where_from = parks.coordinates(last["home_team"])
            where_to = parks.coordinates(ctx.home)
        except parks.ParkError:
            gaps.append(rec.gap(fam, "travel_miles", f"a park for {label}'s last game or this one is not on file",
                                side=side))
            continue
        miles = int(round(travel.great_circle_miles(where_from, where_to)))
        venue = last.get("venue") or ctx.label_of(last["home_team"])
        out.append(rec.factor(
            fam, "travel_miles", miles, "miles", sample={"games": 1}, as_of=last["date"], side=side,
            source=ctx.source_games([last], "the park of the club's last game, against this game's park"),
            sentence=(f"{label} did not travel: it last played at {venue}, the same park." if miles == 0 else
                      f"{label} travels about {miles} miles from where it last played ({venue})."),
            detail={"from_park": venue}))


def _previous_round(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "rest_and_rhythm"
    if ctx.gtype not in ("D", "L", "W"):
        return
    if ctx.stale_reason:
        gaps.append(rec.gap(fam, "previous_round", STALE_LEFT_OUT))
        return
    prev = ser.previous_round(ctx.gtype)
    for side in SIDES:
        team = ctx.sides[side]
        label = ctx.label_of(team)
        status, series = ser.bye_or_played(ctx.series, team, ctx.season, ctx.gtype)
        if status == "bye":
            games = ctx.team_rows(team, same_season=True)
            last = games[-1]["date"] if games else ctx.through
            out.append(rec.factor(
                fam, "previous_round", "bye", "text", sample={"seasons": 1}, as_of=last or ctx.through, side=side,
                source=f"results store: no {_round_name(prev)} game for the club in {ctx.season}, with that round complete",
                sentence=f"{label} had a bye: it did not play in the {_round_name(prev)}.",
                detail={"round": _round_name(prev)}))
        elif status == "played":
            opp = next(t for t in series.teams if t != team)
            wins = series.wins
            mine, theirs = wins[team], wins[opp]
            ended = series.last_date
            since = ser.days_between(ended, ctx.date)
            verb = "won" if series.winner == team else "lost" if series.winner == opp else "played"
            how = (f"{mine}-{theirs}" if series.length > 1 else "in a single game")
            sentence = (f"{label} {verb} the {series.name} {how} over {ctx.label_of(opp)}"
                        if verb != "played" else f"{label} played the {series.name} against {ctx.label_of(opp)}")
            if series.length > 1:
                sentence += f" ({_plural(series.length, 'game')}), which ended {ended}, {_plural(since, 'day')} earlier."
            else:
                sentence += f", which ended {ended}, {_plural(since, 'day')} earlier."
            out.append(rec.factor(
                fam, "previous_round", "played", "text", sample={"games": series.length}, as_of=ended, side=side,
                source=ctx.source_games(list(series.games), f"the club's {series.name}"),
                sentence=sentence,
                detail={"round": series.name, "opponent": ctx.label_of(opp), "wins": mine, "losses": theirs,
                        "games": series.length, "ended": ended, "days_since_ended": since,
                        "won": series.winner == team}))
        else:
            gaps.append(rec.gap(fam, "previous_round",
                                f"the store does not show whether {label} had a bye or played the "
                                f"{_round_name(prev)} (that round is not fully in the data)", side=side))


# ---------------------------------------------------------------------------
# form
# ---------------------------------------------------------------------------

def _form(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "form"
    if ctx.stale_reason:
        gaps.append(rec.gap(fam, "last_10", STALE_LEFT_OUT))
        return
    for side in SIDES:
        team = ctx.sides[side]
        label = ctx.label_of(team)
        games = [p for p in (_persp(r, team) for r in ctx.team_rows(team, same_season=True)) if p]
        if not games:
            gaps.append(rec.gap(fam, "last_10", f"{label} has no earlier game this season in the store", side=side))
            continue
        newest = games[-1]["date"]
        for window in FORM_WINDOWS:
            recent = games[-window:]
            n = len(recent)
            wins = sum(1 for g in recent if g["win"])
            margin = sum(g["rf"] - g["ra"] for g in recent)
            per = margin / n
            if margin > 0:
                runs = f"outscoring opponents by {margin} runs in total ({_rate(per)} a game)"
            elif margin < 0:
                runs = f"being outscored by {-margin} runs in total ({_rate(-per)} a game)"
            else:
                runs = "even on runs"
            span = f"its last {n} games" if n == window else f"its only {_plural(n, 'game')} this season"
            out.append(rec.factor(
                fam, f"last_{window}", wins, "wins", sample={"games": n, "window": window}, as_of=newest, side=side,
                source=ctx.source_games([g["row"] for g in recent], f"{label}'s last {n} games"),
                sentence=f"{label} is {wins}-{n - wins} over {span}, {runs}.",
                detail={"games": n, "wins": wins, "losses": n - wins, "run_margin": margin,
                        "run_margin_per_game": round(per, 4),
                        "runs_for": sum(g["rf"] for g in recent), "runs_against": sum(g["ra"] for g in recent)}))
        kind = games[-1]["win"]
        length = 0
        for g in reversed(games):
            if g["win"] != kind:
                break
            length += 1
        word = "won" if kind else "lost"
        out.append(rec.factor(
            fam, "streak", length, "games", sample={"games": len(games)}, as_of=newest, side=side,
            source=ctx.source_games([g["row"] for g in games[-length:]], f"{label}'s current streak"),
            sentence=(f"{label} {word} its last game." if length == 1 else f"{label} has {word} {length} straight."),
            detail={"type": "win" if kind else "loss"}))
        regular = [g for g in games if g["type"] == ser.REGULAR]
        recent = games[-RECENT_RUNS_WINDOW:]
        # Comparable only when the baseline holds games the recent window does not: early in the
        # season, or after the regular season is over, the two are the same games or nothing.
        recent_all_regular = all(g["type"] == ser.REGULAR for g in recent)
        if regular and not (recent_all_regular and len(regular) <= len(recent)):
            season_rpg = sum(g["rf"] for g in regular) / len(regular)
            recent_rpg = sum(g["rf"] for g in recent) / len(recent)
            out.append(rec.factor(
                fam, "runs_per_game_recent_vs_season", round(recent_rpg, 2), "runs per game",
                sample={"recent_games": len(recent), "season_games": len(regular)}, as_of=newest, side=side,
                source=ctx.source_games([g["row"] for g in recent], f"{label}'s runs scored, last {len(recent)} games "
                                        f"against its {len(regular)} regular-season games"),
                sentence=(f"{label} scored {_rate(recent_rpg)} runs a game over its last {len(recent)}, "
                          f"against {_rate(season_rpg)} over its {len(regular)} regular-season games."),
                detail={"season_runs_per_game": round(season_rpg, 4), "season_games": len(regular),
                        "recent_games": len(recent)}))
        else:
            gaps.append(rec.gap(fam, "runs_per_game_recent_vs_season",
                                f"{label}'s recent games are all of its regular season so far, so there is "
                                "nothing to compare them with", side=side))


# ---------------------------------------------------------------------------
# stakes
# ---------------------------------------------------------------------------

def _series_state(ctx: _Ctx):
    """(series so far or None, game number, wins by club) for a postseason game."""
    pair = tuple(sorted((ctx.away, ctx.home)))
    mine = [s for s in ctx.series if s.season == ctx.season and s.game_type == ctx.gtype and s.teams == pair]
    if not mine:
        return None, 1, {ctx.away: 0, ctx.home: 0}
    s = mine[0]
    return s, s.length + 1, s.wins


def _stakes(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "stakes"
    if ctx.gtype not in ser.POSTSEASON_TYPES:
        gaps.append(rec.gap(fam, "playoff_race",
                            "the standings and the playoff race are not part of this record, so what a regular-season "
                            "game is worth to either club is not stated"))
        return
    needed = ser.wins_needed(ctx.season, ctx.gtype)
    best_of = 2 * needed - 1
    if ctx.stale_reason:
        gaps.append(rec.gap(fam, "series_state", STALE_LEFT_OUT))
    else:
        s, number, wins = _series_state(ctx)
        if s is not None and s.complete:
            gaps.append(rec.gap(fam, "series_state",
                                f"the data already shows this {_round_name(ctx.gtype)} decided before this game"))
        else:
            aw, hw = wins[ctx.away], wins[ctx.home]
            fmt = ("a single game" if best_of == 1 else f"best of {best_of}")
            if best_of == 1:
                sentence = f"The {_round_name(ctx.gtype)} is a single game, so this one decides it."
            elif aw == hw == 0:
                sentence = f"Game 1 of the {_round_name(ctx.gtype)} ({fmt})."
            elif aw == hw:
                sentence = f"Game {number} of the {_round_name(ctx.gtype)} ({fmt}): the series is tied {aw}-{hw}."
            else:
                lead, lw, tw = ((ctx.away_label, aw, hw) if aw > hw else (ctx.home_label, hw, aw))
                sentence = f"Game {number} of the {_round_name(ctx.gtype)} ({fmt}): {lead} lead {lw}-{tw}."
            games = list(s.games) if s else []
            out.append(rec.factor(
                fam, "series_state", number, "game number",
                sample={"games_played": number - 1}, as_of=(games[-1]["date"] if games else ctx.through),
                source=(ctx.source_games(games, f"the {_round_name(ctx.gtype)} so far") if games else
                        f"results store: no earlier game of this {_round_name(ctx.gtype)} between the two clubs"),
                sentence=sentence,
                detail={"round": _round_name(ctx.gtype), "best_of": best_of, "wins_needed": needed,
                        "away_wins": aw, "home_wins": hw}))
            for side, team in ctx.sides.items():
                other = ctx.home if team == ctx.away else ctx.away
                label = ctx.label_of(team)
                faces = wins[other] == needed - 1
                out.append(rec.factor(
                    fam, "elimination", faces, "bool", sample={"games_played": number - 1},
                    as_of=(games[-1]["date"] if games else ctx.through), side=side,
                    source=f"results store: the series score going into this game ({wins[team]}-{wins[other]})",
                    sentence=(f"{label} faces elimination: {ctx.label_of(other)} need one more win." if faces else
                              f"{label} is not facing elimination."),
                    detail={"own_wins": wins[team], "opponent_wins": wins[other], "wins_needed": needed}))
    # How long since each club won a postseason series, within what the data covers.
    first_season = int(min(r["date"] for r in ctx.rows)[:4]) if ctx.rows else None
    last_season_in_data = ctx.season
    for side, team in ctx.sides.items():
        label = ctx.label_of(team)
        if first_season is None:
            gaps.append(rec.gap(fam, "series_wins_in_data", "no earlier games are in the data", side=side))
            continue
        won = [s for s in ctx.series if s.winner == team]
        if won:
            last = max(won, key=lambda s: s.last_date)
            sentence = (f"{label} has won {len(won)} postseason series in our data ({first_season} on), "
                        f"most recently in {last.season}.")
            detail = {"first_season_in_data": first_season, "last_series_win_season": last.season,
                      "last_series_win_round": last.name}
            as_of = last.last_date
        else:
            sentence = (f"{label} has not won a postseason series in our data, which starts in "
                        f"{first_season}.")
            detail = {"first_season_in_data": first_season}
            as_of = ctx.rows[-1]["date"]
        out.append(rec.factor(
            fam, "series_wins_in_data", len(won), "series", sample={"seasons_in_data": last_season_in_data - first_season + 1},
            as_of=as_of, side=side,
            source=(f"results store: every postseason series the club played since {first_season}"),
            sentence=sentence, detail=detail))


# ---------------------------------------------------------------------------
# pressure history
# ---------------------------------------------------------------------------

def _regular_record(ctx: _Ctx, team: str, season: int) -> Optional[tuple]:
    """(wins, losses) of a club's regular season: the supplied season record (the standings, which
    count every game, including the two opening series abroad the results store starts after) when
    there is one, else the club's regular-season games in the rows, else None."""
    held = ctx.season_records.get((season, team))
    if held and held.get("wins") is not None and held.get("losses") is not None:
        return int(held["wins"]), int(held["losses"])
    games = [p for p in (_persp(r, team) for r in ctx.by_team.get(team, ())
                         if r.get("game_type") == ser.REGULAR and int(r["date"][:4]) == season) if p]
    if ctx.store_starts and season >= int(ctx.store_starts[:4]) and games:
        wins = sum(1 for g in games if g["win"])
        return wins, len(games) - wins
    return None


def _pressure(ctx: _Ctx, out: list, gaps: list) -> None:
    """How each club has fared in the postseason against its regular season. It is a fact
    about October, so it is written for postseason games only: in April it would be a line of
    "no postseason games" the analyst would have to read past."""
    fam = "pressure_history"
    if ctx.gtype not in ser.POSTSEASON_TYPES:
        return
    first_season = int(min(r["date"] for r in ctx.rows)[:4]) if ctx.rows else None
    for side, team in ctx.sides.items():
        label = ctx.label_of(team)
        post = [p for p in (_persp(r, team) for r in ctx.team_rows(team)
                            if r.get("game_type") in ser.POSTSEASON_TYPES) if p]
        if first_season is None:
            gaps.append(rec.gap(fam, "postseason_record", "no earlier games are in the data", side=side))
            continue
        if not post:
            out.append(rec.factor(
                fam, "postseason_record", 0, "games", sample={"games": 0}, as_of=ctx.rows[-1]["date"], side=side,
                source=f"results store: every postseason game since {first_season}",
                sentence=f"{label} has no postseason games in our data, which starts in {first_season}.",
                detail={"first_season_in_data": first_season}))
            continue
        wins = sum(1 for p in post if p["win"])
        n = len(post)
        mine = [s for s in ctx.series if team in s.teams and s.complete]
        sw = sum(1 for s in mine if s.winner == team)
        sl = len(mine) - sw
        seasons = sorted({int(p["date"][:4]) for p in post})
        reg_w = reg_l = 0
        missing_seasons = []
        for season in seasons:
            held = _regular_record(ctx, team, season)
            if held is None:
                missing_seasons.append(season)
            else:
                reg_w += held[0]
                reg_l += held[1]
        win_pct = wins / n
        detail = {"wins": wins, "losses": n - wins, "series_won": sw, "series_lost": sl,
                  "win_pct": round(win_pct, 4), "seasons": seasons, "first_season_in_data": first_season}
        sentence = (f"{label} is {wins}-{n - wins} in {n} postseason games in our data ({first_season} on), "
                    f"{sw}-{sl} in series, a {_pct(win_pct)} win rate")
        if reg_w + reg_l:
            reg_pct = reg_w / (reg_w + reg_l)
            detail.update(regular_season_win_pct=round(reg_pct, 4), regular_season_games=reg_w + reg_l,
                          win_pct_difference=round(win_pct - reg_pct, 4))
            sentence += (f", against {_pct(reg_pct)} in the regular seasons it reached the postseason "
                         f"({reg_w + reg_l} games).")
        else:
            sentence += "."
        if missing_seasons:
            gaps.append(rec.gap(fam, "regular_season_win_rate",
                                f"no regular-season record for {', '.join(str(s) for s in missing_seasons)}, so those "
                                f"seasons are left out of {label}'s comparison", side=side))
        out.append(rec.factor(
            fam, "postseason_record", n, "games", sample={"games": n, "series": len(mine)},
            as_of=post[-1]["date"], side=side,
            source=ctx.source_games([p["row"] for p in post], f"{label}'s postseason games"),
            sentence=sentence, detail=detail))
    gaps.append(rec.gap(fam, "manager_record",
                        "managers and their postseason records are not in the results store"))


# ---------------------------------------------------------------------------
# head to head
# ---------------------------------------------------------------------------

def _head_to_head(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "head_to_head"
    meetings = [r for r in ctx.team_rows(ctx.away)
                if {r["away_team"], r["home_team"]} == {ctx.away, ctx.home}]
    this_season = [r for r in meetings if int(r["date"][:4]) == ctx.season]
    first_season = int(min(r["date"] for r in ctx.rows)[:4]) if ctx.rows else None
    if first_season is None:
        gaps.append(rec.gap(fam, "season_series", "no earlier games are in the data"))
        return
    a_wins = sum(1 for r in this_season if ser.winner_of(r) == ctx.away)
    n = len(this_season)
    h_wins = n - a_wins
    if n:
        sentence = (f"This season {ctx.away_label} is {a_wins}-{h_wins} against {ctx.home_label} "
                    f"in {_plural(n, 'game')}.")
    else:
        sentence = f"{ctx.away_label} and {ctx.home_label} have not played each other yet this season."
    out.append(rec.factor(
        fam, "season_series", n, "games", sample={"games": n}, as_of=(this_season[-1]["date"] if this_season
                                                                       else ctx.rows[-1]["date"]),
        source=(ctx.source_games(this_season, f"{ctx.away_label} against {ctx.home_label} this season") if this_season
                else f"results store: no game between the two clubs in {ctx.season} before this one"),
        sentence=sentence, detail={"away_wins": a_wins, "home_wins": h_wins}))
    scored = [r for r in meetings if None not in ser.runs_of(r) and ser.winner_of(r)]
    last = scored[-LAST_MEETINGS:]
    if last:
        listed = []
        for r in reversed(last):
            a, h = ser.runs_of(r)
            winner = ser.winner_of(r)
            listed.append({"date": r["date"], "away": ctx.label_of(r["away_team"]), "home": ctx.label_of(r["home_team"]),
                           "away_score": a, "home_score": h, "winner": ctx.label_of(winner) if winner else None,
                           "round": _round_name(r.get("game_type")) if r.get("game_type") in ser.POSTSEASON_TYPES
                           else "regular season"})
        bits = []
        for m in listed:
            hi, lo = max(m["away_score"], m["home_score"]), min(m["away_score"], m["home_score"])
            bits.append(f"{m['winner']} won {hi}-{lo} on {m['date']}")
        sentence = (f"The last {'meeting' if len(listed) == 1 else str(len(listed)) + ' meetings'} in our data: "
                    + "; ".join(bits) + ".")
        out.append(rec.factor(
            fam, "last_meetings", len(listed), "games", sample={"meetings_in_data": len(meetings)},
            as_of=last[-1]["date"], source=ctx.source_games(last, f"the last {len(last)} meetings"),
            sentence=sentence, detail={"meetings": listed, "data_starts_season": first_season}))
    else:
        out.append(rec.factor(
            fam, "last_meetings", 0, "games", sample={"meetings_in_data": 0}, as_of=ctx.rows[-1]["date"],
            source=f"results store: no game between the two clubs since {first_season}",
            sentence=f"The two clubs have not met since our data begins in {first_season}.",
            detail={"data_starts_season": first_season}))


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------

def _availability(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "availability"
    if ctx.stale_reason:
        gaps.append(rec.gap(fam, "probable_rest", STALE_LEFT_OUT))
        return
    for side, team in ctx.sides.items():
        label = ctx.label_of(team)
        name = ctx.game.get(f"{side}_probable")
        pid = ser.to_int(ctx.game.get(f"{side}_probable_id"))
        if not name:
            gaps.append(rec.gap(fam, "probable_rest", f"no probable starter is listed for {label} yet", side=side))
        else:
            starts = []
            for r in ctx.team_rows(team, same_season=True):
                n2, i2 = _starter_of(r, team)
                same = (pid is not None and i2 == pid) or (pid is None and n2 == name)
                if same:
                    starts.append(r)
            if not starts:
                gaps.append(rec.gap(fam, "probable_rest",
                                    f"{name} has no earlier start this season in the store (a first start, "
                                    "or a return from the injured list)", side=side))
            else:
                last = starts[-1]
                since = ser.days_between(last["date"], ctx.date)
                recent = [r for r in starts if ser.days_between(r["date"], ctx.date) <= STARTER_WINDOW_DAYS]
                postseason = last.get("game_type") in ser.POSTSEASON_TYPES
                where = f" in the {_round_name(last['game_type'])}" if postseason else ""
                out.append(rec.factor(
                    fam, "probable_rest", since, "days", sample={"starts_this_season": len(starts)},
                    as_of=last["date"], side=side,
                    source=ctx.source_games([last], f"{name}'s last start as the listed starter"),
                    sentence=(f"{name} last started {_days(since)} earlier ({last['date']}){where}, "
                              f"{_plural(since - 1, 'day')} of rest."),
                    detail={"starter": name, "last_start": last["date"], "days_of_rest": since - 1,
                            "starts_last_30_days": len(recent), "last_start_postseason": postseason}))
        if ctx.gtype in ("D", "L", "W"):
            status, series = ser.bye_or_played(ctx.series, team, ctx.season, ctx.gtype)
            if status != "played":
                continue
            listed = []
            for i, g in enumerate(series.games, 1):
                who, _ = _starter_of(g, team)
                listed.append({"game": i, "date": g["date"], "starter": who})
            named = [x for x in listed if x["starter"]]
            if not named:
                gaps.append(rec.gap(fam, "starters_previous_round",
                                    f"the store names no starter for {label}'s {series.name} games", side=side))
                continue
            distinct = list(dict.fromkeys(x["starter"] for x in named))
            parts = ", ".join(f"game {x['game']} {x['starter']}" for x in named)
            out.append(rec.factor(
                fam, "starters_previous_round", len(distinct), "starters",
                sample={"games": series.length, "named": len(named)}, as_of=series.last_date, side=side,
                source=ctx.source_games(list(series.games), f"the starters the schedule listed in {label}'s {series.name}"),
                sentence=f"{label}'s listed starters in the {series.name}: {parts}.",
                detail={"round": series.name, "starters": listed}))
    # What the data does not hold about availability, once per game.
    gaps.append(rec.gap(fam, "injuries_and_pitch_counts",
                        "injuries, pitch counts and bullpen use are not in the results store (the packet's bullpen "
                        "section covers recent relievers)"))


# ---------------------------------------------------------------------------
# venue
# ---------------------------------------------------------------------------

def _venue(ctx: _Ctx, out: list, gaps: list) -> None:
    fam = "venue"
    try:
        park = parks.get_park(ctx.home)
    except parks.ParkError:
        gaps.append(rec.gap(fam, "park", f"no park is on file for {ctx.home_label}"))
        return
    name = ctx.game.get("venue") or park["name"]
    as_of = (date.fromisoformat(ctx.date) - timedelta(days=1)).isoformat()   # static facts: known the day before
    altitude = park.get("altitude_m")
    sentence = f"{ctx.home_label} host at {name}."
    if isinstance(altitude, (int, float)) and altitude >= ALTITUDE_NOTE_M:
        sentence = f"{ctx.home_label} host at {name}, {int(altitude)} meters above sea level."
    out.append(rec.factor(
        fam, "park", name, "text", sample={}, as_of=as_of,
        source=f"the schedule's venue, with the park table for {ctx.home_label}", sentence=sentence,
        detail={"home_team": ctx.home_label, "altitude_m": altitude}))
    roof = park.get("roof")
    if roof in _ROOF_WORDS:
        out.append(rec.factor(
            fam, "roof", roof, "text", sample={}, as_of=as_of,
            source=f"the park table for {ctx.home_label}",
            sentence=f"{name} is {_ROOF_WORDS[roof]}."))


# ---------------------------------------------------------------------------
# the public function
# ---------------------------------------------------------------------------

def _display(ctx: _Ctx, factors: Sequence[Mapping]) -> list:
    """What the page's short Situation block says, in order (the page shows up to six).

    "Not facing elimination" is true of nearly every game and tells a reader nothing, so
    elimination is shown only when it is the news."""
    triples = []
    if ctx.gtype in ser.POSTSEASON_TYPES:
        triples.append(("stakes", "series_state", "game"))
        for f in factors:
            if f["name"] == "elimination" and f["value"] is True:
                triples.append(("stakes", "elimination", f["side"]))
        triples += [("rest_and_rhythm", "previous_round", s) for s in SIDES]
    else:
        triples += [("rest_and_rhythm", "days_since_last_game", s) for s in SIDES]
    triples += [("form", "last_10", s) for s in SIDES]
    triples.append(("head_to_head", "season_series", "game"))
    triples += [("availability", "starters_previous_round", s) for s in SIDES]
    return triples


def situation_for_game(game: Mapping, results: Iterable[Mapping], *,
                       extra_games: Iterable[Mapping] = (),
                       season_records: Optional[Mapping] = None,
                       covered_dates: Optional[Iterable[str]] = None,
                       strict: bool = False) -> dict:
    """The situation around one MLB game, drawn as of the game's date.

    `game` is a schedule row (`date`, `away_team`, `home_team`, and optionally `game_pk`,
    `game_type`, `venue`, `start_time_utc`, `away_probable`/`home_probable` with `_id`,
    `double_header`, `game_number`). `results` is the results store's finished games.
    `extra_games` are more finished games from an older, display-only history (earlier
    postseasons) and `season_records` the regular-season records `{(season, club):
    {"wins", "losses"}}` for the seasons the results store does not hold: both only extend the
    long-memory facts. `covered_dates` is the set of dates the ingest manifest confirms.
    Raises `ValueError` for a game with no readable date or no two clubs. A factor that fails
    is left out and listed as missing; `strict=True` re-raises instead (the tests use it).
    """
    ctx = _Ctx(game, results, extra_games, season_records, covered_dates)
    factors: List[dict] = []
    gaps: List[dict] = []
    steps: Sequence[tuple] = (
        ("rest_and_rhythm", _rest), ("rest_and_rhythm", _previous_round), ("form", _form),
        ("stakes", _stakes), ("pressure_history", _pressure), ("head_to_head", _head_to_head),
        ("availability", _availability), ("venue", _venue))
    for family, step in steps:
        try:
            step(ctx, factors, gaps)
        except Exception as exc:  # noqa: BLE001 -- one family never takes the record down
            if strict:
                raise
            gaps.append(rec.gap(family, getattr(step, "__name__", family).lstrip("_"),
                                f"this part could not be worked out from the data ({type(exc).__name__})"))
    if ctx.stale_reason:
        gaps.append(rec.gap("rest_and_rhythm", "results_store_current", ctx.stale_reason))
    basis = (f"games dated before {ctx.date} in the results store"
             + (f", which starts {ctx.store_starts}" if ctx.store_starts else ""))
    return rec.build(
        sport=SPORT,
        subject={"game_pk": ctx.game.get("game_pk"), "date": ctx.date, "away": ctx.away_label,
                 "home": ctx.home_label, "game_type": ctx.gtype,
                 "first_pitch_utc": ctx.game.get("start_time_utc")},
        as_of=ctx.date, as_of_basis=basis, families=FAMILIES, sides=SIDES,
        factors=factors, missing=gaps,
        coverage={"results_store_starts": ctx.store_starts, "results_store_through": ctx.through,
                  "results_current": ctx.stale_reason is None,
                  "earlier_postseasons_from": (min(r["date"] for r in ctx.rows)[:4] if ctx.rows else None)},
        display=_display(ctx, factors))
