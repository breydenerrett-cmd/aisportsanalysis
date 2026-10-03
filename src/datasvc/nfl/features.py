"""Leakage-free NFL features: what a team, a player or a game had behind it as of a moment.

THE ONE PROPERTY THIS MODULE EXISTS TO KEEP
-------------------------------------------
Every figure here uses only games that FINISHED BEFORE the `as_of` instant: a game counts only
if its kickoff plus `FINISH_ALLOWANCE` (6 hours, the source has no finish time) is not after
`as_of`, and it has a final result. A game on the as_of date, at the as_of instant or in the
middle of it, and every later game, never counts, in any figure. `completed_games` is the only
place a game is admitted; the rest of this file, the matchup sheet and the API all go through
it, so the rule is audited in one spot. A feature that saw its own game's outcome would make
every backtest on it look brilliant and every live use of it lose money.

A game's own features default to as of its kickoff, and `as_of` may not be later than the
kickoff (a pre-game sheet "as of" after the game would put the game's result into the form
figures, a quiet leak). Team and player features accept any `as_of`.

Facts the published schedule fixes before the game (the opponent, the stadium, the kickoff
slot, whether it is divisional) are as-of safe. Anything recorded at or after the game is in a
block labelled `"as_of_safe": false` and nothing computed anywhere else reads it: the
quarterback and coach listed for the game (the schedule file carries the projected starter
until the game is final), the observed temperature and wind, and the closing market in the
matchup sheet.

HOW FIGURES ARE BUILT
---------------------
Every window carries its own sample (`games`), and each statistic carries the games that had
the numbers it needs (`games`, `num`, `den`) because a team statistics row can be missing for a
game that has a score. Ratios are sums over sums (yards per play is total net yards over total
plays, not an average of per-game ratios). A figure that cannot be computed has `value` None
and a reason, and is listed in the top-level `missing`. Nothing is filled with an average or
a guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.datasvc.nfl import timeutil, venues
from src.datasvc.nfl.store import POSITION_GROUP_ORDER, NflStore, game_sort_key
from src.datasvc.nfl.timeutil import instant, iso_utc, parse_instant
from src.sports import nfl_teams

LEAKAGE_RULE = ("uses only games that finished before as_of: kickoff + 6 hours is not after as_of and "
                "the game has a final result; a game on the as_of date, at the as_of instant or "
                "during it, and every later game, is excluded")
FINISH_ALLOWANCE = timedelta(hours=6)       # no NFL game, overtime and weather delay included, lasts longer
INJURY_REPORT_LEAD = timedelta(hours=24)    # when an injury row has no timestamp: out this long before kickoff
WINDOWS = (3, 5)
SHORT_WEEK_DAYS = 5                          # rest of this many calendar days or fewer is a short week
BYE_REST_DAYS = 13                           # this many days or more since the last game is a bye or longer
NIGHT_FROM_ET = "19:00"                      # kickoff at or after this Eastern time is primetime
LATE_FROM_ET = "15:00"

__all__ = ["LEAKAGE_RULE", "FINISH_ALLOWANCE", "INJURY_REPORT_LEAD", "WINDOWS", "UnknownGame", "UnknownTeam",
           "UnknownPlayer", "Played", "completed_games", "team_features_as_of", "player_features_as_of",
           "game_features", "head_to_head", "rest_facts", "travel_facts", "injuries_block", "qb_block",
           "schedule_facts", "resolve_team", "instant", "iso_utc", "parse_instant"]

_UTC = timezone.utc


class UnknownGame(LookupError):
    """The game id is not in the store."""


class UnknownTeam(LookupError):
    """The team is not in the store."""


class UnknownPlayer(LookupError):
    """The player id has no row in the store."""


# -- small helpers -------------------------------------------------------------------------

def _clean(x: Optional[float], digits: int = 4):
    if x is None:
        return None
    r = round(x, digits)
    return int(r) if float(r).is_integer() else r


def _per(total: Optional[float], n: int) -> Optional[float]:
    return _clean(total / n) if n and total is not None else None


def _num(value: Any) -> Optional[float]:
    """A real finite number, else None (a bool, a string or NaN is absent, not zero)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def team_name(code: Optional[str]) -> Optional[str]:
    return nfl_teams.full_name(code) if code else None


def resolve_team(store: NflStore, team: str) -> str:
    """A team code from a code, nickname or alias ('LAR' is 'LA'); UnknownTeam when it is not in the store."""
    code = nfl_teams.abbrev(team) or str(team).strip().upper()
    if code not in store.games_by_team():
        raise UnknownTeam(f"no team {team!r} in the store")
    return code


def _et_date(when: datetime) -> date:
    """The US Eastern calendar date of an instant, the date the schedule's `gameday` is on."""
    return (when + timedelta(hours=timeutil.utc_offset_hours("us_eastern", when))).date()


def _day(text: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


# -- the gate -----------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Played:
    """One finished game from one team's side. `eq=False`: it holds dicts, so it hashes by identity."""
    game: dict
    game_id: str
    kickoff: datetime
    team: str
    opponent: str
    site: str                       # home | away | neutral
    points_for: int
    points_against: int
    result: str                     # W | L | T
    row: Optional[dict]             # this team's team_games row
    opp_row: Optional[dict]         # the opponent's row for the same game

    @property
    def margin(self) -> int:
        return self.points_for - self.points_against


def _new_skipped() -> Dict[str, list]:
    return {"no_kickoff_time": [], "in_progress_at_as_of": [], "started_without_result": []}


def completed_games(store: NflStore, team: str, before: Any,
                    skipped: Optional[Dict[str, list]] = None) -> List[Played]:
    """The team's games that finished before `before` and have a final result, oldest first.

    THE LEAKAGE GATE. A game is admitted only when its kickoff is known, kickoff + 6 hours is
    not after `before`, its status is final and both scores are present. `skipped` collects what
    was left out so a reader can see it: games with no kickoff time (they cannot be placed, so
    they are never assumed to be in the past), games that started before `before` but may still
    have been in progress, and games that should have finished with no result recorded.
    """
    cutoff = parse_instant(before)
    rows = store.team_game_by_key()
    out: List[Played] = []
    for game in store.games_by_team().get(team, ()):
        kickoff = instant(game.get("kickoff_utc"))
        if kickoff is None:
            if skipped is not None:
                skipped["no_kickoff_time"].append(game["game_id"])
            continue
        if kickoff + FINISH_ALLOWANCE > cutoff:
            if skipped is not None and kickoff < cutoff:
                skipped["in_progress_at_as_of"].append(game["game_id"])
            continue
        home = game["home_team"] == team
        pf, pa = game.get("home_score" if home else "away_score"), game.get("away_score" if home else "home_score")
        if game.get("status") != "final" or pf is None or pa is None:
            if skipped is not None:
                skipped["started_without_result"].append(
                    {"game_id": game["game_id"], "kickoff_utc": game.get("kickoff_utc"), "status": game.get("status")})
            continue
        opponent = game["away_team"] if home else game["home_team"]
        out.append(Played(
            game=game, game_id=game["game_id"], kickoff=kickoff, team=team, opponent=opponent,
            site="neutral" if game.get("neutral_site") else ("home" if home else "away"),
            points_for=pf, points_against=pa, result="W" if pf > pa else "L" if pf < pa else "T",
            row=rows.get((game["game_id"], team)), opp_row=rows.get((game["game_id"], opponent))))
    out.sort(key=lambda p: (p.kickoff, p.game_id))
    return out


# -- team form ----------------------------------------------------------------------------

YPP_UNIT = "net yards per play: (passing yards - sack yards + rushing yards) / (attempts + sacks + carries)"


def _sum_figure(plays: Sequence[Played], num_of, den_of, *, unit: str, needs: str, ratio: bool = True) -> dict:
    """Sum(num)/Sum(den) over the games that have both; value None with a reason when none do."""
    n = d = 0.0
    used = 0
    for p in plays:
        a, b = num_of(p), den_of(p)
        if a is None or b is None:
            continue
        n += a
        d += b
        used += 1
    if not used:
        return {"value": None, "unit": unit, "games": 0,
                "reason": ("no games in the window" if not plays else f"none of the {len(plays)} game(s) has {needs}")}
    if ratio and d <= 0:
        return {"value": None, "unit": unit, "games": used, "num": _clean(n), "den": _clean(d), "reason": "zero denominator"}
    return {"value": _clean(n / d if ratio else n), "unit": unit, "games": used, "num": _clean(n), "den": _clean(d)}


def _row_num(field: str, opponent: bool = False):
    def get(p: Played) -> Optional[float]:
        row = p.opp_row if opponent else p.row
        return _num(row.get(field)) if row else None
    return get


def _window(plays: Sequence[Played], season: Optional[int]) -> dict:
    """Results and statistics over `plays` (oldest first)."""
    n = len(plays)
    pf = sum(p.points_for for p in plays)
    pa = sum(p.points_against for p in plays)
    wins = sum(1 for p in plays if p.result == "W")
    losses = sum(1 for p in plays if p.result == "L")
    turnovers = [v for v in (_row_num("turnover_margin")(p) for p in plays) if v is not None]
    return {
        "games": n, "wins": wins, "losses": losses, "ties": n - wins - losses,
        "points_for": pf, "points_against": pa,
        "points_for_per_game": _per(pf, n), "points_against_per_game": _per(pa, n),
        "margin_per_game": _per(pf - pa, n),
        "first_game_utc": iso_utc(plays[0].kickoff) if plays else None,
        "last_game_utc": iso_utc(plays[-1].kickoff) if plays else None,
        "seasons": sorted({p.game["season"] for p in plays}),
        "games_in_target_season": sum(1 for p in plays if p.game["season"] == season) if season is not None else None,
        "yards_per_play": _sum_figure(plays, _row_num("net_yards"), _row_num("plays"), unit=YPP_UNIT,
                                      needs="plays and net yards"),
        "yards_per_play_allowed": _sum_figure(plays, _row_num("net_yards", True), _row_num("plays", True),
                                              unit="the opponents' " + YPP_UNIT, needs="the opponent's plays and net yards"),
        "turnover_margin": {"value": _per(sum(turnovers), len(turnovers)) if turnovers else None,
                            "unit": "takeaways - giveaways, per game", "games": len(turnovers),
                            "total": _clean(sum(turnovers)) if turnovers else None,
                            **({} if turnovers else {"reason": "no game in the window has the statistics"})},
    }


def _record(plays: Sequence[Played]) -> dict:
    wins = sum(1 for p in plays if p.result == "W")
    losses = sum(1 for p in plays if p.result == "L")
    return {"games": len(plays), "wins": wins, "losses": losses, "ties": len(plays) - wins - losses}


def _streak(plays: Sequence[Played]) -> dict:
    if not plays:
        return {"type": None, "length": 0}
    kind, length = plays[-1].result, 0
    for p in reversed(plays):
        if p.result != kind:
            break
        length += 1
    return {"type": kind, "length": length}


def _line(p: Played) -> dict:
    return {"game_id": p.game_id, "kickoff_utc": iso_utc(p.kickoff), "season": p.game["season"],
            "week": p.game["week"], "game_type": p.game.get("game_type"), "opponent": p.opponent, "site": p.site,
            "points_for": p.points_for, "points_against": p.points_against, "result": p.result, "margin": p.margin}


def _missing_from_window(prefix: str, window: dict, missing: List[dict]) -> None:
    if window["games"] == 0:
        missing.append({"figure": f"{prefix}", "reason": "no game before as_of in this window"})
        return
    for name in ("yards_per_play", "yards_per_play_allowed", "turnover_margin"):
        if window[name]["value"] is None:
            missing.append({"figure": f"{prefix}.{name}", "reason": window[name].get("reason", "not computed")})


def _team_block(store: NflStore, team: str, cutoff: datetime, season: Optional[int]
                ) -> Tuple[dict, List[Played]]:
    skipped = _new_skipped()
    plays = completed_games(store, team, cutoff, skipped)
    in_season = [p for p in plays if season is not None and p.game["season"] == season]
    missing: List[dict] = []
    form = {"last_3": _window(plays[-3:], season), "last_5": _window(plays[-5:], season),
            "season_to_date": _window(in_season, season)}
    for name, window in form.items():
        _missing_from_window(f"form.{name}", window, missing)
    last = plays[-1] if plays else None
    if last is None:
        missing.append({"figure": "rest", "reason": "no earlier game in the store"})
    block = {
        "team": team, "name": team_name(team), "as_of": iso_utc(cutoff), "leakage_rule": LEAKAGE_RULE,
        "season": season,
        "sample": {"games": len(plays), "first_game_utc": iso_utc(plays[0].kickoff) if plays else None,
                   "last_game_utc": iso_utc(last.kickoff) if last else None, "skipped": skipped},
        "record": {"season": _record(in_season), "store": _record(plays)},
        "streak": _streak(plays),
        "form": form,
        "last_games": [_line(p) for p in reversed(plays[-5:])],
        "missing": missing,
    }
    return block, plays


def team_features_as_of(store: NflStore, team: str, as_of: Any, *, season: Optional[int] = None) -> dict:
    """A team's form as of an instant: results, margins, points, yards per play, turnover margin.

    `season` (default: the NFL season `as_of` falls in) picks the games of `season_to_date`.
    Raises ValueError for an unreadable `as_of` and UnknownTeam for a team not in the store.
    """
    cutoff = parse_instant(as_of)
    code = resolve_team(store, team)
    ref_season = season if season is not None else timeutil.season_of(cutoff)
    block, plays = _team_block(store, code, cutoff, ref_season)
    last = plays[-1] if plays else None
    block["rest"] = {"days_since_last_game": (_et_date(cutoff) - _day(last.game["gameday"])).days if last else None,
                     "last_game_id": last.game_id if last else None,
                     "last_game_utc": iso_utc(last.kickoff) if last else None,
                     "measured_to": iso_utc(cutoff),
                     "unit": "calendar days (US Eastern) from the last game to the as_of date"}
    return block


# -- the game's own context ---------------------------------------------------------------

def schedule_facts(game: dict) -> dict:
    """What the published schedule fixes before the game. As-of safe."""
    et = game.get("kickoff_et")
    window = None
    if et:
        window = "night" if et >= NIGHT_FROM_ET else "late_afternoon" if et >= LATE_FROM_ET else "early"
    return {
        "season": game["season"], "week": game["week"], "game_type": game.get("game_type"),
        "postseason": game.get("game_type") not in (None, "REG"),
        "gameday": game.get("gameday"), "weekday": game.get("weekday"),
        "kickoff_et": et, "kickoff_utc": game.get("kickoff_utc"),
        "time_window": window, "primetime": (et >= NIGHT_FROM_ET) if et else None,
        "divisional": game.get("div_game"), "neutral_site": game.get("neutral_site"),
    }


def previous_scheduled_game(store: NflStore, team: str, game: dict) -> Optional[dict]:
    """The team's game before `game` on the schedule, played or not (a removed game never counts).

    Rest, bye and travel are facts of the schedule: they are known before either game is played,
    so they are measured from the previous SCHEDULED game, not the previous finished one. For a
    game a few weeks ahead the previous finished game can be weeks back; the schedule's is not.
    """
    mine = game_sort_key(game)
    before = [g for g in store.games_by_team().get(team, ())
              if g["game_id"] != game["game_id"] and g.get("status") != "removed" and game_sort_key(g) < mine]
    return before[-1] if before else None


def rest_facts(prev: Optional[dict], game: dict, side: str) -> dict:
    """Rest, bye and short week for one side of a game, from the team's previous scheduled game.

    Days are calendar days between the two `gameday`s (the NFL's own convention: Sunday to
    Thursday is 4). A previous game in an earlier season means this is a season opener: no rest
    figure (the gap is months), `season_opener` true. Where the source gives its own rest days it
    agrees with this on every game of 2023 to 2026 (measured 2026-10-03: 2,126 of 2,126 team games with a
    previous game in those seasons); it differs where it used the nominal schedule (20 team games of 2021,
    the COVID reschedules, and 2 of 2022, week 18 after the cancelled Bills at Bengals game).
    """
    source = game.get(f"{side}_rest_days")
    out = {"days_since_last_game": None, "short_week": None, "coming_off_bye": None, "season_opener": None,
           "week_gap": None, "last_game_id": None, "last_game_utc": None, "source_rest_days": source,
           "rules": f"short week: {SHORT_WEEK_DAYS} or fewer days; bye: two or more weeks since the last game "
                    f"or {BYE_REST_DAYS}+ days"}
    if prev is None:
        out["reason"] = "no earlier game in the store"
        return out
    out["last_game_id"], out["last_game_utc"] = prev["game_id"], prev.get("kickoff_utc")
    if prev["season"] != game["season"]:
        out["season_opener"] = True
        out["reason"] = "season opener: the previous game was last season"
        return out
    out["season_opener"] = False
    today, before = _day(game.get("gameday")), _day(prev.get("gameday"))
    days = (today - before).days if today is not None and before is not None else None
    gap = game["week"] - prev["week"]
    out["days_since_last_game"], out["week_gap"] = days, gap
    if days is not None:
        out["short_week"] = days <= SHORT_WEEK_DAYS
    out["coming_off_bye"] = gap >= 2 or (days is not None and days >= BYE_REST_DAYS)
    return out


def _home_base(store: NflStore, team: str, season: int) -> Optional[str]:
    """The stadium id a team calls home that season, else the nearest earlier season's."""
    table = store.home_stadiums()
    for s in range(season, season - 6, -1):
        if (team, s) in table:
            return table[(team, s)]
    return None


def _venue_of(game: dict) -> Tuple[Optional[str], Optional[str]]:
    """(stadium id, why it cannot be used) for a game."""
    sid = game.get("stadium_id")
    if not sid:
        return None, "the schedule names no stadium"
    check = game.get("venue_check", "ok")
    if check != "ok":
        return None, f"the schedule's venue is unreliable ({check})"
    if venues.venue(sid) is None:
        return None, f"stadium {sid} is not in the venue table"
    return sid, None


def travel_facts(store: NflStore, team: str, game: dict, prev: Optional[dict]) -> dict:
    """Distance and time zones for one team travelling to one game. As-of safe: schedule facts.

    `prev` is the team's previous scheduled game (`previous_scheduled_game`). Miles are
    great-circle from the team's home stadium (and from the venue of its previous game) to this
    game's venue. `time_zones_crossed` is the venue's UTC offset at kickoff minus the
    home stadium's, in hours: negative is westward. `kickoff_home_base_clock` is the kickoff on the
    team's own clock. An unreliable venue gives None figures with the reason.
    """
    venue_id, why = _venue_of(game)
    base = _home_base(store, team, game["season"])
    out = {"base_stadium_id": base, "venue_stadium_id": game.get("stadium_id"), "miles_from_home_base": None,
           "miles_from_last_game": None, "time_zones_crossed": None, "direction": None,
           "kickoff_home_base_clock": None, "reasons": {}}
    if venue_id is None:
        out["reasons"]["venue"] = why
        return out
    if base is None or venues.venue(base) is None:
        out["reasons"]["home_base"] = f"no home stadium for {team} in the store's schedule"
    else:
        here, home = venues.venue(venue_id), venues.venue(base)
        at_home = game["home_team"] == team and not game.get("neutral_site")
        out["miles_from_home_base"] = 0.0 if at_home else venues.miles_between(base, venue_id)
        kickoff = instant(game.get("kickoff_utc"))
        if kickoff is not None:
            delta = timeutil.utc_offset_hours(here.zone, kickoff) - timeutil.utc_offset_hours(home.zone, kickoff)
            out["time_zones_crossed"] = delta
            out["direction"] = "none" if delta == 0 else ("east" if delta > 0 else "west")
            clock = kickoff + timedelta(hours=timeutil.utc_offset_hours(home.zone, kickoff))
            out["kickoff_home_base_clock"] = clock.strftime("%H:%M")
        else:
            out["reasons"]["time_zones"] = "no kickoff time"
    if prev is None:
        out["reasons"]["last_game"] = "no earlier game in the store"
    else:
        prev_id, prev_why = _venue_of(prev)
        if prev_id is None:
            out["reasons"]["last_game"] = f"the previous game's venue is unusable: {prev_why}"
        else:
            out["miles_from_last_game"] = venues.miles_between(prev_id, venue_id)
    return out


def qb_block(store: NflStore, game: dict, side: str, prev: Optional[Played], cutoff: datetime) -> dict:
    """The starting quarterback: the last game's (as-of safe) and this game's (NOT as-of safe).

    The schedule file lists a starter for a game not yet played too, as a projection, and the
    actual starter once it is final. Either way it is recorded at fetch time, not time-stamped,
    so `this_game` carries `as_of_safe: false` and nothing else in the features reads it.
    """
    team = game[f"{side}_team"]
    last_id = last_name = None
    if prev is not None:
        pside = "home" if prev.game["home_team"] == team else "away"
        last_id, last_name = prev.game.get(f"{pside}_qb_id"), prev.game.get(f"{pside}_qb_name")
    this_id, this_name = game.get(f"{side}_qb_id"), game.get(f"{side}_qb_name")
    starts = [s for s in store.qb_starts().get(this_id, ()) if (instant(s[0]) or cutoff) + FINISH_ALLOWANCE <= cutoff] \
        if this_id else []
    return {
        "last_game": {"game_id": prev.game_id if prev else None, "qb_id": last_id, "qb_name": last_name,
                      "as_of_safe": True},
        # everything that depends on the quarterback listed for THIS game is in here, and is not as-of safe
        "this_game": {"qb_id": this_id, "qb_name": this_name, "projected": game.get("status") != "final",
                      "changed_since_last_game": (this_id != last_id) if this_id and last_id else None,
                      "prior_starts_in_store": len(starts) if this_id else None,
                      "prior_starts_with_team": sum(1 for s in starts if s[2] == team) if this_id else None,
                      "as_of_safe": False,
                      "note": "the starter the schedule file lists for this game (projected until it is final); "
                              "recorded when fetched, not time-stamped"},
    }


def coach_block(game: dict, side: str, prev: Optional[Played]) -> dict:
    """The head coach of the last finished game (as-of safe) and of this one (not)."""
    team = game[f"{side}_team"]
    last = None
    if prev is not None:
        last = prev.game.get("home_coach" if prev.game["home_team"] == team else "away_coach")
    this = game.get(f"{side}_coach")
    return {"last_game": {"coach": last, "as_of_safe": True},
            "this_game": {"coach": this, "changed_since_last_game": (this != last) if this and last else None,
                          "as_of_safe": False, "note": "the head coach the schedule file lists for the game"}}


def injuries_block(store: NflStore, team: str, game: dict, cutoff: datetime) -> dict:
    """The team's injury report counts by position, as of the last report out before `cutoff`.

    A row with a `date_modified` is known from that instant. A row without one (the 2025 and
    2026 files) is the week's final report and is taken as out `INJURY_REPORT_LEAD` (24 hours)
    before kickoff: an assumption, stated in the block, not a measurement. Rows not yet known are
    counted in `rows_not_yet_known` and used for nothing.
    """
    season, week = game["season"], game["week"]
    if (season, week) not in store.injury_weeks():
        return {"available": False, "reason": f"the store has no injury report rows for week {week} of season {season}"}
    kickoff = instant(game.get("kickoff_utc"))
    used, unknown = [], 0
    for row in store.injuries_by_game_team().get((game["game_id"], team), ()):
        stamp = instant(row.get("date_modified"))
        known = (stamp <= cutoff) if stamp is not None else (kickoff is not None and cutoff >= kickoff - INJURY_REPORT_LEAD)
        if known:
            used.append(row)
        else:
            unknown += 1
    if not used and unknown:
        return {"available": False, "rows_not_yet_known": unknown,
                "reason": "as_of is before the report is known (a timestamp after as_of, or more than 24 hours before kickoff "
                          "for a row with no timestamp)"}
    groups: Dict[str, Dict[str, int]] = {}
    totals = {"listed": 0, "out": 0, "doubtful": 0, "questionable": 0, "dnp": 0, "limited": 0}
    for row in used:
        for target in (groups.setdefault(row.get("position_group") or "OTHER", dict.fromkeys(totals, 0)), totals):
            target["listed"] += 1
            if row.get("report_status") in ("out", "doubtful", "questionable"):
                target[row["report_status"]] += 1
            if row.get("practice_status") in ("dnp", "limited"):
                target[row["practice_status"]] += 1
    skill = [{"player_id": r["player_id"], "name": r.get("name"), "position": r.get("position"),
              "report_status": r.get("report_status"), "practice_status": r.get("practice_status"),
              "injury": r.get("report_injury") or r.get("practice_injury")}
             for r in used if r.get("position_group") in ("QB", "RB", "WR", "TE")
             and (r.get("report_status") in ("out", "doubtful", "questionable") or r.get("position_group") == "QB")]
    stamps = [r["date_modified"] for r in used if r.get("date_modified")]
    return {"available": True, "report_week": week, "players_listed": len(used),
            "rows_not_yet_known": unknown, "newest_report_utc": max(stamps) if stamps else None,
            "timestamped_rows": len(stamps),
            "by_position_group": {g: groups[g] for g in POSITION_GROUP_ORDER if g in groups},
            "totals": totals,
            "skill_players_listed": sorted(skill, key=lambda s: (s["position"] or "", s["name"] or "")),
            "assumption": "a row without date_modified is the week's final report, taken as published 24 hours before kickoff"}


def head_to_head(store: NflStore, home: str, away: str, cutoff: datetime) -> dict:
    """Games between the two teams in the store before `cutoff`, from `home`'s side, newest first."""
    played = [p for p in completed_games(store, home, cutoff) if p.opponent == away]
    items = []
    for p in reversed(played):
        g = p.game
        items.append({"game_id": p.game_id, "kickoff_utc": iso_utc(p.kickoff), "season": g["season"], "week": g["week"],
                      "game_type": g.get("game_type"), "home_team": g["home_team"], "away_team": g["away_team"],
                      "home_score": g["home_score"], "away_score": g["away_score"],
                      "winner": None if p.result == "T" else (home if p.result == "W" else away),
                      "margin_for_target_home_team": p.margin})
    seasons = store.seasons()
    n = len(played)
    return {
        "meetings": n, "home_team": home, "away_team": away,
        "home_team_wins": sum(1 for p in played if p.result == "W"),
        "away_team_wins": sum(1 for p in played if p.result == "L"),
        "ties": sum(1 for p in played if p.result == "T"),
        "average_margin_for_home_team": _per(sum(p.margin for p in played), n) if n else None,
        "last_meeting": items[0] if items else None, "items": items,
        "store_window": {"seasons": [seasons[0], seasons[-1]] if seasons else None},
        "note": ("every meeting in the store's window, not the teams' full history; home_team and away_team are "
                 "the target game's teams whichever of them hosted the earlier game"),
    }


# -- a game's features ---------------------------------------------------------------------

def game_features(store: NflStore, game_id: str, as_of: Any = None) -> dict:
    """Both teams' features for one game, as of `as_of` (default: the game's kickoff).

    Raises UnknownGame, ValueError for an unreadable `as_of`, or one later than the kickoff, or
    for a game with no kickoff time and no explicit `as_of`.
    """
    game = store.game_by_id().get(game_id)
    if game is None:
        raise UnknownGame(f"no game {game_id!r} in the store")
    kickoff = instant(game.get("kickoff_utc"))
    if as_of is None:
        if kickoff is None:
            raise ValueError(f"game {game_id} has no kickoff time; pass an explicit as_of")
        cutoff, source = kickoff, "kickoff"
    else:
        cutoff, source = parse_instant(as_of), "argument"
        if kickoff is not None and cutoff > kickoff:
            raise ValueError("as_of is after the kickoff: a pre-game sheet as of a later moment would "
                             "count this game's own result in the form figures")
    sides = {}
    missing: List[dict] = []
    for side in ("home", "away"):
        team = game[f"{side}_team"]
        block, plays = _team_block(store, team, cutoff, game["season"])
        prev = plays[-1] if plays else None                     # the last FINISHED game: results, QB, coach
        prev_scheduled = previous_scheduled_game(store, team, game)   # the schedule's previous game: rest, travel
        played = {p.game_id for p in plays}
        gap = [g["game_id"] for g in store.games_by_team().get(team, ())
               if g.get("status") != "removed" and game_sort_key(g) < game_sort_key(game) and g["game_id"] not in played]
        block["sample"]["scheduled_games_without_a_finished_result_before_this_game"] = gap
        if gap:
            block["missing"].append({"figure": "form", "reason": f"{len(gap)} earlier game(s) of this team have no finished "
                                     f"result as of as_of ({', '.join(gap[:3])}): form is as of its last finished game"})
        block["rest"] = rest_facts(prev_scheduled, game, side)
        block["travel"] = travel_facts(store, team, game, prev_scheduled)
        block["injuries"] = injuries_block(store, team, game, cutoff)
        block["qb"] = qb_block(store, game, side, prev, cutoff)
        block["coach"] = coach_block(game, side, prev)
        for name in ("rest", "travel", "injuries"):
            part = block[name]
            if name == "injuries" and not part.get("available"):
                block["missing"].append({"figure": "injuries", "reason": part["reason"]})
            elif name == "rest" and part.get("days_since_last_game") is None and part.get("reason"):
                block["missing"].append({"figure": "rest.days_since_last_game", "reason": part["reason"]})
            elif name == "travel":
                for key, reason in part["reasons"].items():
                    block["missing"].append({"figure": f"travel.{key}", "reason": reason})
        if block["qb"]["this_game"]["qb_id"] is None:
            block["missing"].append({"figure": "qb.this_game", "reason": "the schedule lists no starter for this game yet"})
        if block["coach"]["this_game"]["coach"] is None:
            block["missing"].append({"figure": "coach.this_game", "reason": "the schedule lists no head coach for this game"})
        sides[side] = block
        missing += [dict(m, side=side, team=team) for m in block["missing"]]
    cond = {"temp_f": game.get("temp_f"), "wind_mph": game.get("wind_mph"), "roof": game.get("roof"),
            "surface": game.get("surface"), "as_of_safe": False,
            "note": "observed conditions and the roof's state are recorded at game time; the venue's roof type and surface are fixed"}
    return {
        "game_id": game_id, "as_of": iso_utc(cutoff), "as_of_source": source, "leakage_rule": LEAKAGE_RULE,
        "game": {"game_id": game_id, "status": game.get("status"), "home_team": game["home_team"],
                 "away_team": game["away_team"], "stadium_id": game.get("stadium_id"),
                 "stadium": game.get("stadium"), "venue_check": game.get("venue_check")},
        "schedule": schedule_facts(game),
        "conditions": cond,
        "home": sides["home"], "away": sides["away"],
        "head_to_head": head_to_head(store, game["home_team"], game["away_team"], cutoff),
        "missing": missing,
    }


# -- player features (props) ---------------------------------------------------------------

COUNT_STATS = ("pass_attempts", "completions", "passing_yards", "passing_tds", "interceptions",
               "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds")
SHARE_STATS = ("target_share", "air_yards_share")
PLAYER_NOTE = ("a row means the player has a stat line in the game (offence, defence or special teams); an "
               "offensive player who played and recorded nothing has no row, so `games` counts games with a "
               "stat line and `missed_team_games` the team's games in the window span with none")


def _player_window(rows: Sequence[dict], team_plays: Sequence[Played], all_ids: set) -> dict:
    n = len(rows)
    stats = {}
    for name in COUNT_STATS:
        values = [_num(r.get(name)) for r in rows]
        have = [v for v in values if v is not None]
        stats[name] = {"total": _clean(sum(have)) if have else None, "per_game": _per(sum(have), len(have)) if have else None,
                       "games": len(have)}
    shares = {}
    for name in SHARE_STATS:
        have = [v for v in (_num(r.get(name)) for r in rows) if v is not None]
        shares[name] = {"mean": _clean(sum(have) / len(have)) if have else None, "games": len(have)}
    out = {"games": n, "stats": stats, "shares": shares,
           "first_game_utc": rows[0].get("kickoff_utc") if rows else None,
           "last_game_utc": rows[-1].get("kickoff_utc") if rows else None,
           "game_ids": [r["game_id"] for r in reversed(rows)]}
    if rows:
        team = rows[-1].get("team")
        first = min((instant(r.get("kickoff_utc")) for r in rows if r.get("team") == team and instant(r.get("kickoff_utc"))),
                    default=None)
        window_ids = {r["game_id"] for r in rows}
        span = [p for p in team_plays if first is not None and p.kickoff >= first]
        out["team"] = team
        out["team_games_in_span"] = len(span)
        out["missed_team_games"] = [p.game_id for p in span if p.game_id not in window_ids and p.game_id not in all_ids]
    return out


def player_features_as_of(store: NflStore, player_id: str, as_of: Any, *, windows: Sequence[int] = WINDOWS) -> dict:
    """A player's recent usage and production as of an instant, over his last 3 and 5 games played.

    Only rows of games that pass the leakage gate count. `games` in each window is the number of
    games it really holds (it can be fewer than 3 or 5), and `missed_team_games` lists the team's
    games inside the window's span that the player has no row for. Raises ValueError for an
    unreadable `as_of` and UnknownPlayer for an id with no row in the store.
    """
    cutoff = parse_instant(as_of)
    rows = store.player_games_by_player().get(player_id)
    if not rows:
        raise UnknownPlayer(f"no player {player_id!r} in the store")
    games = store.game_by_id()
    admitted, skipped = [], {"no_kickoff_time": [], "in_progress_at_as_of": [], "not_final": []}
    for row in rows:
        game = games.get(row["game_id"])
        kickoff = instant(game.get("kickoff_utc")) if game else instant(row.get("kickoff_utc"))
        if kickoff is None:
            skipped["no_kickoff_time"].append(row["game_id"])
        elif kickoff + FINISH_ALLOWANCE > cutoff:
            if kickoff < cutoff:
                skipped["in_progress_at_as_of"].append(row["game_id"])
        elif game is not None and game.get("status") != "final":
            skipped["not_final"].append(row["game_id"])
        else:
            admitted.append(row)
    newest = rows[-1]
    out = {"player_id": player_id, "name": newest.get("name"), "position": newest.get("position"),
           "position_group": newest.get("position_group"), "as_of": iso_utc(cutoff), "leakage_rule": LEAKAGE_RULE,
           "team": admitted[-1].get("team") if admitted else None,
           "sample": {"games_in_store_before_as_of": len(admitted),
                      "first_game_utc": admitted[0].get("kickoff_utc") if admitted else None,
                      "last_game_utc": admitted[-1].get("kickoff_utc") if admitted else None,
                      "skipped": skipped, "note": PLAYER_NOTE}}
    missing: List[dict] = []
    all_ids = {r["game_id"] for r in admitted}
    team_plays = completed_games(store, out["team"], cutoff) if out["team"] else []
    for n in windows:
        window = _player_window(admitted[-n:], team_plays, all_ids) if admitted else _player_window([], [], set())
        out[f"last_{n}"] = window
        if window["games"] == 0:
            missing.append({"figure": f"last_{n}", "reason": "the player has no game in the store before as_of"})
    out["recent_games"] = [
        {"game_id": r["game_id"], "kickoff_utc": r.get("kickoff_utc"), "season": r.get("season"), "week": r.get("week"),
         "team": r.get("team"), "opponent": r.get("opponent"), **{k: r.get(k) for k in COUNT_STATS + SHARE_STATS}}
        for r in reversed(admitted[-max(windows):])]
    out["missing"] = missing
    return out
