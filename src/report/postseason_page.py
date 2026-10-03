"""The public MLB postseason page: series state, series chances, game-by-game
forecasts and bracket odds, built from code that already exists.

WHAT THIS FILE IS, AND WHAT IT IS NOT
--------------------------------------
Almost no arithmetic lives here. The series math is
`src.analysis.postseason` (exact first-to-k solver, per-round formats from
`postseason_config`), the per-game price is `src.analysis.matchup_model`
(which runs the unmodified `strength.model_line`), and the state-conditioned
series number is `matchup_model.conditional_series_win_prob`. This module is
the layer that works out WHAT SERIES EXIST RIGHT NOW from the results store,
asks those functions the right question for each one, and lays the answers
out for a reader.

It prices nothing it cannot ground. If the field of 12 cannot be determined
from data on disk, `build` returns `{"available": False, "reason": ...}`
rather than a bracket guessed from a stale snapshot.

HOW THE STATE OF EVERY SERIES IS FOUND
--------------------------------------
* The field (who is seeded where) comes from a FINAL regular-season
  standings snapshot, never an earlier one: the six seeds per league are the
  three division winners by record, then the three best other clubs by the
  feed's own wild-card rank. A tie between division winners is not
  resolvable from this data (the real tiebreak is head-to-head), so it
  returns the honest-absence payload instead of picking one.
* Every series' score comes from postseason rows in the results store
  (`game_type` F / D / L / W). A series is complete the moment one side
  reaches its win count; only completed series advance a team. A game on
  file that fits no series the seeds allow is a CONFLICT and also returns
  the honest-absence payload: a page that quietly dropped it would show a
  score that is not true.
* Nothing dated after `now` is ever read, so no future start can leak in.

WHAT IS KNOWN VS PROJECTED, PER GAME (the owner's rule, 2026-10-01)
-------------------------------------------------------------------
Stale pitcher data may not silently remain a numerical input to a
customer-facing forecast. Every starter slot of every unplayed game is
classified, and the class decides whether the pitcher is in the estimate:

  CONFIRMED_CURRENT     the schedule names him, he has a same-season log and
                        his numbers are current (see `CURRENT_INPUT_DAYS`).
  PROJECTED_CURRENT     the schedule names nobody; the team's rotation (built
                        from a current results store) points to a pitcher whose
                        numbers are current.
  STALE_REFERENCE_ONLY  a pitcher is identified (named or projected) but his
                        numbers are not current.
  UNAVAILABLE           nobody is identified, or the identified pitcher has no
                        same-season log.

A game's primary chance includes the starter component ONLY when both of its
sides are CONFIRMED_CURRENT; otherwise it is priced exactly like an unset
series (team results, park and, when current, bullpens). A projected pitcher
is never shown in the starter slot (a side the schedule has not named is
"TBD") and never feeds a series number: a PROJECTED_CURRENT game carries a
separately labelled `scenarios` entry. Stale pitcher numbers produce neither
a primary number nor a scenario. The bullpen component follows the same
currency rule. Each game and the page carry the list of inputs that are
current and used, so the reader sees what an estimate is made from.

An identified pitcher whose stored numbers are not current is looked up once
through the injected `fresh_pitcher_logs` (the daily job's own game-log fetch
in production), which is how a starter can be CONFIRMED_CURRENT while the
stored logs are old. A pitcher's future start is NEVER treated as known: only
games already final and games the schedule feed has announced count.
Rest/travel and bullpen availability stay CONTEXT ONLY and lineups and
injuries stay UNAVAILABLE, exactly as `matchup_model.FACTOR_DISPOSITIONS`
records.

SERIES THAT DO NOT EXIST YET
-----------------------------
A later-round series whose teams are not decided (a Division Series waiting
on a Wild Card winner) has no starters and no schedule. Its chance is priced
from team strength and park (and bullpens, when their numbers are current)
with a flat home-field adjustment, the same simplification `scripts/postseason_demo.py` labels a scenario input.
Series within one round are treated as independent, as in
`postseason.py`.

NO PREDICTIVE CLAIM. These are model estimates with no series-level track
record. The forecast ledger (`evidence/postseason_forecasts.jsonl`, written
by `scripts/postseason_snapshot.py`) is how that record gets built in
public: once a series ends, the page shows what it said before game 1.
"""

from __future__ import annotations

import itertools
import sys
import threading
from datetime import date as _date_cls
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional, Sequence

from src.analysis import matchup_model as mm
from src.analysis import postseason as ps
from src.analysis import postseason_config as pc
from src.pipeline import pitchers as pitchers_mod

MODEL_ID = "POSTSEASON_PAGE_V1"
MODEL_NAME = "Series chances from team run rates, starters, bullpens and parks"

CAVEAT = ("These are model estimates and can be wrong. They have no track record yet.")

# How many days of schedule `upcoming_games` looks ahead of the baseball date
# for announced starters. A starter the schedule has already named is shown as
# named however far out the game is; 7 covers a whole Division Series.
SCHEDULE_DAYS_AHEAD = 7

# THE ONE CURRENCY RULE. A pitcher's (or the bullpen's) numbers are current
# when the newest row the model would read is no more than this many days
# behind `as_of` (the results-through date), or, for a pitcher, when his log
# was fetched fresh for this build. Anything older is not used in a primary
# number. This replaces the old "caveat but still used" band (3 to 10 days).
CURRENT_INPUT_DAYS = 3

# The four starter classes (see the module docstring), strongest first.
CONFIRMED_CURRENT = "CONFIRMED_CURRENT"
PROJECTED_CURRENT = "PROJECTED_CURRENT"
STALE_REFERENCE_ONLY = "STALE_REFERENCE_ONLY"
INPUT_UNAVAILABLE = "UNAVAILABLE"
STARTER_CLASSES = (CONFIRMED_CURRENT, PROJECTED_CURRENT, STALE_REFERENCE_ONLY,
                   INPUT_UNAVAILABLE)

# The four components every estimate is made of, in the order they are listed.
INPUT_KEYS = ("team_results", "park", "starters", "bullpens")
INPUT_LABELS = {"team_results": "team results", "park": "ballpark",
                "starters": "starting pitchers", "bullpens": "bullpens",
                "league_pitching_baseline": "league pitching baseline"}

# What a reader sees when the page cannot be built, chosen by the builder's
# `missing` code. The internal reason goes in the payload's `detail`, which
# the page does not render.
PUBLIC_REASONS = {
    "final_standings": ("The final regular-season standings are not in yet, so the "
                        "playoff field cannot be set."),
    "results": ("The latest game results have not come in yet, so the series "
                "scores cannot be shown as current."),
    "field": "The playoff bracket could not be set from the information available right now.",
    "pricing": "Series chances could not be worked out from the information available right now.",
}

# A flat home-field adjustment, used ONLY for a series whose teams are not
# decided yet (see the module docstring). A scenario input, not a fitted
# number: the same 0.03 `scripts/postseason_demo.py` uses and labels.
HOME_FIELD_ADJUSTMENT = 0.03

LEAGUE_BY_ID = {103: "AL", 104: "NL"}

ROUND_KEYS = ("WC", "DS", "LCS", "WS")
ROUND_FORMAT = {"WC": pc.WILD_CARD, "DS": pc.DIVISION_SERIES, "LCS": pc.LCS,
                "WS": pc.WORLD_SERIES}
ROUND_LABEL = {"WC": "Wild Card Series", "DS": "Division Series",
               "LCS": "League Championship Series", "WS": "World Series"}
ROUND_CALENDAR_KEY = {"WC": "wild_card", "DS": "division_series", "LCS": "lcs",
                      "WS": "world_series"}
ROUND_BY_GAME_TYPE = {ROUND_FORMAT[k]["game_type"]: k for k in ROUND_KEYS}

# Starter labels, straight from the matchup model's own vocabulary.
MODEL_USED = mm.MODEL_USED
SCENARIO_INPUT = mm.SCENARIO_INPUT
CONTEXT_ONLY = mm.CONTEXT_ONLY
UNAVAILABLE = mm.UNAVAILABLE

# A results store that has not seen yesterday cannot say what the score is
# today. One day of lag is normal (the daily job runs once); more than that,
# while the postseason is on, is a store that stopped advancing.
MAX_RESULTS_LAG_DAYS = 1


class FieldUnknown(Exception):
    """The 12-team field or a series state cannot be pinned from the data."""


class PricingFailure(Exception):
    """A game or matchup could not be priced from the data on disk."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _to_int(value) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_now(now) -> datetime:
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso_plus(day: str, days: int) -> str:
    return (_date_cls.fromisoformat(day) + timedelta(days=days)).isoformat()


# US Eastern, from a fixed rule. `zoneinfo` needs a tz database that Windows
# Pythons usually do not ship, and a clock that is wrong twice a year is worse
# than a rule that is right in the two places it can be wrong. The rule (US,
# since 2007): daylight time (UTC-4) runs from the second Sunday of March at
# 02:00 standard time (07:00Z) to the first Sunday of November at 02:00
# daylight time (06:00Z); standard time (UTC-5) the rest of the year.
def _nth_sunday(year: int, month: int, n: int) -> _date_cls:
    first = _date_cls(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern_utc_offset(now) -> timedelta:
    """-4h while US daylight time is in force, -5h otherwise."""
    moment = _parse_now(now)
    begins = datetime.combine(_nth_sunday(moment.year, 3, 2), datetime.min.time(),
                              tzinfo=timezone.utc) + timedelta(hours=7)
    ends = datetime.combine(_nth_sunday(moment.year, 11, 1), datetime.min.time(),
                            tzinfo=timezone.utc) + timedelta(hours=6)
    return timedelta(hours=-4 if begins <= moment < ends else -5)


def baseball_date(now) -> str:
    """The US Eastern calendar date of `now`, 'YYYY-MM-DD': the date the
    schedule files a game under. From 8 pm Eastern the UTC date is already
    tomorrow, and every evening game starts after 00:00Z."""
    moment = _parse_now(now)
    return (moment + eastern_utc_offset(moment)).date().isoformat()


_MONTH_WORDS = ("Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept",
                "Oct", "Nov", "Dec")


def _short_date(day: str) -> str:
    parsed = _date_cls.fromisoformat(day)
    return f"{_MONTH_WORDS[parsed.month - 1]} {parsed.day}"


def _days_behind(day: Optional[str], as_of: str) -> Optional[int]:
    if not day:
        return None
    return (_date_cls.fromisoformat(as_of) - _date_cls.fromisoformat(day)).days


def is_current(day: Optional[str], as_of: Optional[str]) -> bool:
    """The one currency rule: is a store whose newest row is dated `day`
    current as of `as_of`? No date (nothing on file) is never current."""
    behind = _days_behind(day, as_of) if as_of else None
    return behind is not None and behind <= CURRENT_INPUT_DAYS


def stale_input_caveats(inputs_through: Mapping, as_of: str) -> list:
    """Plain caveats, in the order they should lead the page, for pitcher or
    bullpen numbers that are not current (more than `CURRENT_INPUT_DAYS`
    behind `as_of`). Each says what the old numbers mean for the estimates
    now: they are not in them. A pitcher store with nothing in it is stale;
    an empty bullpen store is left to the method note and the inputs line of
    each game (it has no date to name)."""
    out = []
    pitcher = inputs_through.get("pitcher_logs")
    if pitcher is None:
        out.append("No pitcher numbers are on file, so starting pitchers are not in these "
                   "estimates.")
    elif not is_current(pitcher, as_of):
        out.append(f"Pitcher numbers on file run through {_short_date(pitcher)}. A starting "
                   "pitcher is left out of an estimate unless his numbers are current.")
    bullpen = inputs_through.get("bullpen_log")
    if bullpen is not None and not is_current(bullpen, as_of):
        out.append(f"Bullpen numbers on file run through {_short_date(bullpen)}, so "
                   "bullpens are left out of these estimates.")
    return out


def results_are_current(through: Optional[str], today: str) -> bool:
    """Is the results store current enough to project a rotation from? Within
    `MAX_RESULTS_LAG_DAYS` of the baseball date; no date is not current."""
    behind = _days_behind(through, today)
    return behind is not None and behind <= MAX_RESULTS_LAG_DAYS


def _round6(value):
    return None if value is None else round(float(value), 6)


def unavailable(reason: str, now=None, **extra) -> dict:
    """The honest-absence payload. Never carries a number a reader could
    mistake for a forecast. `reason` is the sentence a reader sees (one of
    `PUBLIC_REASONS`, chosen by the `missing` code); the internal specifics go
    in `detail`, which the page never renders."""
    out = {
        "available": False,
        "reason": reason,
        "model": MODEL_ID,
        "caveats": [CAVEAT],
        "as_of": None,
        "series": [],
        "teams": [],
    }
    if now is not None:
        out["built_at"] = _parse_now(now).isoformat()
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# results: postseason games from the store
# ---------------------------------------------------------------------------

def postseason_games(store: Mapping, season: str, today: str) -> list:
    """Final postseason games of `season` dated on or before `today`, in
    play order. A row with no score, or a tied score, is dropped: a partial
    or impossible result must never become a series win."""
    out = []
    for row in (store or {}).values():
        game_type = row.get("game_type")
        if game_type not in ROUND_BY_GAME_TYPE:
            continue
        day = str(row.get("date") or "")
        if not day.startswith(season) or day > today:
            continue
        away_score, home_score = _to_int(row.get("away_score")), _to_int(row.get("home_score"))
        if away_score is None or home_score is None or away_score == home_score:
            continue
        home, away = row.get("home_team"), row.get("away_team")
        if not home or not away:
            continue
        out.append({
            "pk": str(row.get("game_pk")),
            "date": day,
            "start": str(row.get("start_time_utc") or ""),
            "number": _to_int(row.get("game_number")) or 1,
            "type": game_type,
            "home": home, "away": away,
            "home_score": home_score, "away_score": away_score,
            "winner": home if home_score > away_score else away,
            "venue": row.get("venue"),
            "home_sp_id": _to_int(row.get("home_probable_id")),
            "away_sp_id": _to_int(row.get("away_probable_id")),
        })
    out.sort(key=lambda g: (g["date"], g["start"], g["number"], g["pk"]))
    return out


def _unavailable_for(code: str, detail: str, now, **extra) -> dict:
    return unavailable(PUBLIC_REASONS[code], now, missing=code, detail=detail, **extra)


def newest_result_date(store: Mapping, season: str, today: str) -> Optional[str]:
    dates = [str(r.get("date")) for r in (store or {}).values()
             if str(r.get("date") or "").startswith(season) and str(r.get("date")) <= today]
    return max(dates) if dates else None


def results_through_from_manifest(manifest: Mapping, decisive_scope=None) -> Optional[str]:
    """The date the results ingest has FULLY covered, from the manifest
    `src.pipeline.history` keeps: the last date of an unbroken run.

    THE RULE, from how `history.ingest_date` writes the manifest. Every date
    the ingest asks about gets an entry, off days included (`total` 0), and a
    date it never asked about has none. So inside the postseason window (from
    the first Wild Card date) every date must be on file, not pending, and
    stored under a scope wide enough for `decisive_scope` (a date stored under
    the regular-season-only scope skipped every postseason game on it and was
    still marked done): the run stops at the first one that is not. A later
    date does not paper over an earlier hole. Before the window, as before,
    the newest non-pending date counts and a gap is not a break: the page's
    standings and team numbers only need the regular season to be nearly
    current, and the window's own first date is where the run starts."""
    first_postseason = pc.CALENDAR["wild_card"]["start"]
    entries = {str(day): (entry or {}) for day, entry in (manifest or {}).items()}
    best = None
    for day, entry in entries.items():
        if day < first_postseason and not entry.get("pending"):
            if best is None or day > best:
                best = day
    last = max(entries, default=None)
    day = first_postseason
    while last is not None and day <= last:
        entry = entries.get(day)
        if entry is None or entry.get("pending"):
            break
        if decisive_scope is not None:
            recorded = entry.get("game_types")
            if recorded is None or not frozenset(decisive_scope) <= frozenset(recorded):
                break
        best = day
        day = _iso_plus(day, 1)
    return best


def upcoming_games(now, fetch_games: Callable, days_ahead: int = SCHEDULE_DAYS_AHEAD) -> list:
    """Postseason games not yet final, from the day BEFORE the baseball date
    forward -- where announced probables live -- via an injected
    `fetch_games(date) -> [game]` (`src.providers.mlb.fetch_games` in
    production; this module does no network itself). Covers `days_ahead` days
    after today.

    Why a day back: the schedule files a game under its baseball date, and
    from 8 pm Eastern the UTC date is already tomorrow. Starting at the UTC
    date dropped the game being played from this list, which turned its named
    starters into projections and blanked its date, time and park. A game
    still on the schedule as not final stays in however late it runs; a final
    one is left out (the results store has it). A failed date is skipped: with
    no announcement the builder projects or reports the starter unknown,
    which is the honest fallback."""
    start = _date_cls.fromisoformat(baseball_date(now)) - timedelta(days=1)
    out = []
    for offset in range(days_ahead + 1):
        day = (start + timedelta(days=offset)).isoformat()
        try:
            games = fetch_games(day)
        except Exception:  # noqa: BLE001 -- best effort, see docstring
            continue
        out.extend(g for g in games if g.get("game_type") in ROUND_BY_GAME_TYPE
                   and g.get("state") != "final")
    return out


# ---------------------------------------------------------------------------
# the field: seeds from a FINAL standings snapshot
# ---------------------------------------------------------------------------

def _standings_by_date(standings) -> dict:
    """{date: [row, ...]} from either `standings.read()`'s
    {date: {team: row}} or a flat list of rows."""
    out: dict = {}
    if isinstance(standings, Mapping):
        for day, teams in standings.items():
            rows = list(teams.values()) if isinstance(teams, Mapping) else list(teams or [])
            if rows:
                out[str(day)] = rows
    else:
        for row in standings or []:
            if row.get("date"):
                out.setdefault(str(row["date"]), []).append(row)
    return out


def _final_snapshot(by_date: Mapping, today: str):
    """(date, rows) of the earliest snapshot taken AFTER the regular season
    ended and not after `today`; None if there is none. A snapshot dated the
    last regular-season day counts only if it was captured the next morning
    or later, because one taken that evening can still hold games in
    progress."""
    end = pc.REGULAR_SEASON_ENDS
    candidates = []
    for day in sorted(by_date):
        if day > today or day < end:
            continue
        rows = by_date[day]
        if day == end:
            captured = max(str(r.get("captured_at") or "") for r in rows)
            if captured < _iso_plus(end, 1) + "T06:00":
                continue
        candidates.append(day)
    if not candidates:
        return None
    return candidates[0], by_date[candidates[0]]


def with_final_standings(stored, now, fetch_standings, parse_standings) -> dict:
    """`stored` ({date: {team: row}}), plus the final regular-season table
    from the feed when `stored` holds no snapshot `_final_snapshot` accepts.
    In memory only; `stored` is not modified and nothing is written.

    Why the store alone is not enough: the daily job snapshots a date once,
    in the morning, and never rewrites it. Its row for the last
    regular-season day was therefore captured before that day's games, and
    the feed returns nothing for any later date. So the store never holds a
    final table. Asked now for the last regular-season day, the feed returns
    the finished season; stamped with the time of this call it passes the
    captured-the-next-morning rule honestly.

    Best effort: a failed fetch or anything other than all 30 clubs returns
    `stored` unchanged, and the builder then states the gap.
    """
    now_dt = now if isinstance(now, datetime) else datetime.fromisoformat(str(now))
    today = now_dt.date().isoformat()
    end = pc.REGULAR_SEASON_ENDS
    if today <= end or now_dt.isoformat() < _iso_plus(end, 1) + "T06:00":
        return stored
    if _final_snapshot(_standings_by_date(stored), today) is not None:
        return stored
    try:
        rows = parse_standings(fetch_standings(end[:4], date=end))
    except Exception:  # noqa: BLE001 -- best effort, see docstring
        return stored
    teams = {row["team_abbrev"]: {**row, "date": end, "season": end[:4],
                                  "captured_at": now_dt.isoformat()}
             for row in rows if row.get("team_abbrev")}
    if len(teams) != 30:
        return stored
    out = dict(stored) if isinstance(stored, Mapping) else {}
    if not isinstance(stored, Mapping):
        for day, day_rows in _standings_by_date(stored).items():
            out[day] = {r.get("team_abbrev"): r for r in day_rows}
    out[end] = teams
    return out


def _exact_pct(row) -> float:
    wins, losses = _to_int(row.get("wins")), _to_int(row.get("losses"))
    if wins is not None and losses is not None and wins + losses > 0:
        return wins / (wins + losses)
    pct = row.get("win_pct")
    if pct is None:
        raise FieldUnknown(f"standings row for {row.get('team_abbrev')!r} has no record")
    return float(pct)


def seeds_from_standings(rows: Sequence[Mapping]) -> dict:
    """{"AL": {1: info, ..., 6: info}, "NL": {...}} where info is
    {"team", "seed", "win_pct", "name"}. Raises FieldUnknown if either league
    does not have exactly three division winners and three wild cards, or if
    two division winners are tied on record (the real tiebreak, head to head,
    is not in this data)."""
    seeds = {}
    for league in pc.LEAGUES:
        mine = [r for r in rows if LEAGUE_BY_ID.get(r.get("league_id")) == league]
        leaders = [r for r in mine if r.get("division_leader")]
        others = [r for r in mine if not r.get("division_leader")
                  and _to_int(r.get("wildcard_rank")) is not None]
        wildcards = sorted(others, key=lambda r: _to_int(r["wildcard_rank"]))[:3]
        if len(leaders) != 3 or len(wildcards) != 3:
            raise FieldUnknown(
                f"{league}: expected 3 division winners and 3 wild cards in the "
                f"standings, found {len(leaders)} and {len(wildcards)}")
        leaders = sorted(leaders, key=lambda r: -_exact_pct(r))
        for first, second in zip(leaders, leaders[1:]):
            if _exact_pct(first) == _exact_pct(second):
                raise FieldUnknown(
                    f"{league}: {first.get('team_abbrev')} and {second.get('team_abbrev')} "
                    "finished with the same record, and the head-to-head tiebreak "
                    "that decides their seeds is not in the data on disk")
        ordered = leaders + wildcards
        seeds[league] = {
            i: {"team": r["team_abbrev"], "seed": i, "win_pct": _exact_pct(r),
                "name": r.get("team_name")}
            for i, r in enumerate(ordered, start=1)}
    return seeds


# ---------------------------------------------------------------------------
# series state
# ---------------------------------------------------------------------------

def _scheduled_holder(pending: Sequence[Mapping], game_type: str, names) -> Optional[str]:
    """The home team of the earliest scheduled (not yet played) game between
    these two clubs: how a World Series with tied records gets its home-field
    holder without this module guessing MLB's tiebreak."""
    games = sorted((g for g in pending
                    if g.get("game_type") == game_type
                    and {g.get("away_team"), g.get("home_team")} == set(names)),
                   key=lambda g: (str(g.get("date") or ""), str(g.get("start_time_utc") or "")))
    return games[0].get("home_team") if games else None


def _make_series(season, league, round_key, slot, slot_label, x, y, games, assigned,
                 pending=()) -> dict:
    """One series from two (possibly undecided) participants and the games on
    file. `x`/`y` are team infos or None. Home field decides which team is
    listed first (`a`)."""
    fmt = ROUND_FORMAT[round_key]
    k = fmt["k"]
    sid = f"{season}-{league or 'MLB'}-{round_key}-{slot}"
    series = {
        "id": sid, "league": league, "round": round_key, "round_label": ROUND_LABEL[round_key],
        "slot": slot, "slot_label": slot_label, "fmt": fmt, "k": k,
        "a": None, "b": None, "known": [t for t in (x, y) if t],
        "games": [], "wins": {}, "winner": None, "loser": None,
        "status": "waiting", "waiting_on": [],
    }
    if x is None or y is None:
        return series

    names = {x["team"], y["team"]}
    observed = [g for g in games
                if g["type"] == fmt["game_type"] and {g["away"], g["home"]} == names]
    seed_rule = fmt["home_field_by"] == pc.HOME_FIELD_BY_SEED

    try:
        rule_side = ps._home_field_holder(x, y, fmt)
    except ps.PostseasonError as exc:
        # A tie on record: the real tiebreak is not in the data. The first
        # game on file, or failing that the schedule's first game, says who
        # hosts; with neither, this series cannot be set.
        scheduled = None if observed else _scheduled_holder(pending, fmt["game_type"], names)
        if not observed and scheduled is None:
            raise FieldUnknown(str(exc)) from exc
        rule_side = None if observed else ("a" if scheduled == x["team"] else "b")
    rule_team = None if rule_side is None else (x if rule_side == "a" else y)

    if observed:
        first_home = observed[0]["home"]
        if seed_rule and rule_team is not None and rule_team["team"] != first_home:
            raise FieldUnknown(
                f"{ROUND_LABEL[round_key]}: {first_home} hosted game 1 but the seeds give "
                f"home field to {rule_team['team']}")
        holder = x if first_home == x["team"] else y
    else:
        holder = rule_team
    other = y if holder is x else x
    series["a"], series["b"] = holder, other

    wins = {holder["team"]: 0, other["team"]: 0}
    for game in observed:
        if max(wins.values()) >= k:
            raise FieldUnknown(
                f"{ROUND_LABEL[round_key]} {holder['team']}-{other['team']}: a game is on "
                "file after the series was already won")
        wins[game["winner"]] += 1
    series["games"] = observed
    series["wins"] = wins
    assigned.update(g["pk"] for g in observed)

    for team in (holder, other):
        if wins[team["team"]] >= k:
            series["winner"], series["loser"] = team, (other if team is holder else holder)
    if series["winner"] is not None:
        series["status"] = "complete"
    elif observed:
        series["status"] = "live"
    else:
        series["status"] = "upcoming"
    return series


def resolve_series(seeds: Mapping, games: Sequence[Mapping], season: str,
                   pending: Sequence[Mapping] = ()) -> dict:
    """Every series of the bracket, keyed by id, with its state. Raises
    FieldUnknown if the games on file contradict the seeds or the format."""
    assigned: set = set()
    series: dict = {}
    wc_by_league: dict = {}
    lcs_by_league: dict = {}

    for league in pc.LEAGUES:
        lg = seeds[league]
        wc = {}
        for key in pc.WILD_CARD_SERIES_KEYS:
            hi, lo = pc.WILD_CARD_PAIRINGS[key]
            s = _make_series(season, league, "WC", key, f"No. {hi} vs No. {lo}",
                             lg[hi], lg[lo], games, assigned)
            wc[key] = s
            series[s["id"]] = s
        wc_by_league[league] = wc

        ds = {}
        for seed in pc.BYE_SEEDS:
            feeder = wc[pc.DS_OPPONENT_SERIES_FOR_SEED[seed]]
            opponent = feeder["winner"]
            if opponent is None:
                if any(g["type"] == pc.DIVISION_SERIES["game_type"]
                       and lg[seed]["team"] in (g["away"], g["home"]) for g in games):
                    raise FieldUnknown(
                        f"{league}: Division Series games are on file for No. {seed} "
                        "but the Wild Card series that feeds it is not complete")
            s = _make_series(season, league, "DS", str(seed), f"No. {seed} vs Wild Card winner",
                             lg[seed], opponent, games, assigned)
            if opponent is None:
                s["waiting_on"] = [feeder["id"]]
            ds[seed] = s
            series[s["id"]] = s

        d1, d2 = ds[1], ds[2]
        w1, w2 = d1["winner"], d2["winner"]
        if (w1 is None or w2 is None) and any(
                g["type"] == pc.LCS["game_type"]
                and {g["away"], g["home"]} & {t["team"] for t in lg.values()} for g in games):
            raise FieldUnknown(
                f"{league}: League Championship Series games are on file but both "
                "Division Series are not complete")
        lcs = _make_series(season, league, "LCS", "1", "Division Series winners",
                           w1, w2, games, assigned)
        lcs["waiting_on"] = [s["id"] for s in (d1, d2) if s["winner"] is None]
        lcs_by_league[league] = lcs
        series[lcs["id"]] = lcs

    al, nl = lcs_by_league["AL"], lcs_by_league["NL"]
    if (al["winner"] is None or nl["winner"] is None) and any(
            g["type"] == pc.WORLD_SERIES["game_type"] for g in games):
        raise FieldUnknown("World Series games are on file but both pennants are not decided")
    ws = _make_series(season, None, "WS", "1", "AL champion vs NL champion",
                      al["winner"], nl["winner"], games, assigned, pending)
    ws["waiting_on"] = [s["id"] for s in (al, nl) if s["winner"] is None]
    series[ws["id"]] = ws

    stray = [g for g in games if g["pk"] not in assigned]
    if stray:
        g = stray[0]
        raise FieldUnknown(
            f"a {ROUND_LABEL[ROUND_BY_GAME_TYPE[g['type']]]} game on {g['date']} "
            f"({g['away']} at {g['home']}) fits no series the seeds allow")
    return series


# ---------------------------------------------------------------------------
# pricing context
# ---------------------------------------------------------------------------

class _Context:
    """Everything pricing needs, built once per `build` call.

    CURRENCY. `pitcher_store_current` / `bullpen_current` apply the one rule
    (`is_current`) to the stored logs. Pricing with no starters passes NO
    pitcher logs at all, and pricing with a stale bullpen log passes an empty
    one (`mm` then falls back to each team's own run-prevention rate and
    reports `bullpen_known` false): stale numbers are never an input, they
    are only ever described."""

    def __init__(self, store, pitcher_logs, bullpen_log, cutoff, league_rpg, pending,
                 project_starters=True, now=None, *, as_of=None, pitcher_through=None,
                 bullpen_through=None, results_through=None, today=None,
                 fresh_pitcher_logs=None):
        self.store = store
        self.project_starters = project_starters
        self.now = _parse_now(now) if now is not None else None
        self.pitcher_logs = pitcher_logs
        self._logs_copied = False
        self.bullpen_log = bullpen_log
        self.cutoff = cutoff
        self.today = today or _iso_plus(cutoff, -1)
        self.as_of = as_of
        self.results_through = results_through
        self.pitcher_through = pitcher_through
        self.bullpen_through = bullpen_through
        self.pitcher_store_current = is_current(pitcher_through, as_of)
        self.bullpen_current = is_current(bullpen_through, as_of)
        self.pricing_bullpen = bullpen_log if self.bullpen_current else []
        self.league_rpg = league_rpg
        self.pending = pending
        self._fetch = fresh_pitcher_logs
        self._fresh_called: set = set()
        self._fresh_current: set = set()
        self._plan_memo: dict = {}
        self._neutral_memo: dict = {}
        self.real_chance: dict = {}
        self.names: dict = {}
        for row in store.values():
            for side in ("home", "away"):
                pid, name = _to_int(row.get(f"{side}_probable_id")), row.get(f"{side}_probable")
                if pid is not None and name:
                    self.names[pid] = name
        for game in pending:
            for side in ("home", "away"):
                pid, name = _to_int(game.get(f"{side}_probable_id")), game.get(f"{side}_probable")
                if pid is not None and name:
                    self.names[pid] = name

    # -- pitcher numbers ----------------------------------------------------

    def pitcher_rows(self, pid, before: Optional[str] = None) -> list:
        """The same-season rows of one pitcher dated STRICTLY before `before`
        (default: the build's cutoff): the rows the model could read."""
        before = min(before, self.cutoff) if before else self.cutoff
        season = self.cutoff[:4]
        return [r for r in (self.pitcher_logs or {}).get(str(pid), [])
                if r.get("date") and not r.get("empty")
                and str(r["date"])[:4] == season and str(r["date"]) < before]

    def ensure_fresh(self, pid) -> None:
        """Look up an identified pitcher whose stored numbers are not current,
        once per build, through the injected `fresh_pitcher_logs`.

        THE RULE. A list of rows with at least one same-season appearance
        dated on or before today REPLACES that pitcher's stored same-season
        rows for this build and makes his numbers current, whatever the date
        of his newest row: the feed is the source of truth for "nothing newer
        exists", so a pitcher fetched now with no new start since the store's
        date is current. `None`, an exception, or a list with no usable
        same-season row changes nothing, and his stored numbers stay stale
        (or absent). Rows dated after today are dropped here, and rows dated
        on or after a game's own date are dropped again when that game is
        priced (`pitcher_state`, `_logs_for`)."""
        if pid is None or self._fetch is None or pid in self._fresh_called:
            return
        if self.pitcher_store_current and self.pitcher_rows(pid):
            return
        self._fresh_called.add(pid)
        try:
            rows = self._fetch(pid)
        except Exception:  # noqa: BLE001 -- a failed fetch leaves the numbers stale
            return
        if not isinstance(rows, (list, tuple)):
            return
        season = self.cutoff[:4]
        # Regular-season rows only, whatever the fetcher returns: the feed's
        # default answer is the regular season, but a fetcher that asked for
        # the postseason too (tagged rows) must not smuggle October into a
        # model input. Same rule as the stored logs (see `build`).
        clean = [dict(r) for r in rows if isinstance(r, Mapping) and r.get("date")
                 and str(r["date"]) <= self.today and not r.get("empty")
                 and pitchers_mod.is_regular_season(r)]
        if not any(str(r["date"])[:4] == season for r in clean):
            return
        if not self._logs_copied:
            self.pitcher_logs = dict(self.pitcher_logs or {})
            self._logs_copied = True
        kept = [r for r in self.pitcher_logs.get(str(pid), [])
                if str(r.get("date") or "")[:4] != season and r.get("date")]
        merged = kept + [r for r in clean if str(r["date"])[:4] == season]
        merged.sort(key=lambda r: str(r.get("date") or ""))
        self.pitcher_logs[str(pid)] = merged
        self._fresh_current.add(str(pid))

    def pitcher_state(self, pid, game_date: Optional[str] = None) -> dict:
        """{"has_log", "current", "through"} for one pitcher as the model
        would read him for a game on `game_date`."""
        rows = self.pitcher_rows(pid, game_date)
        if not rows:
            return {"has_log": False, "current": False, "through": None}
        through = max(str(r["date"]) for r in rows)
        return {"has_log": True,
                "current": self.pitcher_store_current or str(pid) in self._fresh_current,
                "through": through}

    def _logs_for(self, away_sp, home_sp, game_date):
        """The pitcher logs to hand the model for one game: the build's logs,
        except that a pitcher's rows dated on or after `game_date` are
        removed (a shallow copy; the league-wide FIP constant still reads the
        same rows it always did)."""
        logs = self.pitcher_logs if self.pitcher_logs is not None else {}
        if not game_date or game_date >= self.cutoff:
            return logs
        out = None
        for pid in (away_sp, home_sp):
            rows = logs.get(str(pid), []) if pid is not None else []
            if any(str(r.get("date") or "") >= game_date for r in rows):
                if out is None:
                    out = dict(logs)
                out[str(pid)] = [r for r in rows if str(r.get("date") or "") < game_date]
        return out if out is not None else logs

    # -- prices ---------------------------------------------------------------

    def neutral(self, team_a: str, team_b: str) -> float:
        key = (team_a, team_b)
        if key not in self._neutral_memo:
            try:
                value = mm.neutral_win_prob(
                    self.store, None, self.pricing_bullpen, team_a, team_b, self.cutoff,
                    league_rpg=self.league_rpg, use_richer=True)
            except mm.MatchupModelError as exc:
                raise PricingFailure(str(exc)) from exc
            self._neutral_memo[key] = value
            self._neutral_memo[(team_b, team_a)] = 1.0 - value
        return self._neutral_memo[key]

    def price_game(self, away, home, away_sp, home_sp, game_date=None):
        """One game's home chance. With no starter on either side no pitcher
        log is passed at all; otherwise only rows before `game_date` are."""
        if away_sp is None and home_sp is None:
            logs = {}
        else:
            logs = self._logs_for(away_sp, home_sp, game_date)
        feats = mm.richer_features(
            self.store, logs, self.pricing_bullpen, away, home,
            away_sp, home_sp, self.cutoff, same_season_only=True)
        line, err = mm.model_line_or_none(feats, league_rpg=self.league_rpg)
        if line is None:
            raise PricingFailure(f"cannot price {away} at {home}: {err}")
        return line["p_home"], feats

    def outcomes(self, a_info, b_info, fmt):
        """[(info, chance), (info, chance)] for one series between two
        teams: the real series' own number when this exact matchup exists
        right now, the team-strength price otherwise."""
        key = (fmt["name"], frozenset((a_info["team"], b_info["team"])))
        real = self.real_chance.get(key)
        if real is not None:
            return [(a_info, real[a_info["team"]]), (b_info, real[b_info["team"]])]
        try:
            detail = ps.series_probabilities_for_round(
                a_info, b_info, fmt, self.neutral, home_edge=HOME_FIELD_ADJUSTMENT)
            p_a = detail["p_team_a_wins"]
        except ps.PostseasonError as exc:
            if fmt["home_field_by"] != pc.HOME_FIELD_BY_RECORD:
                raise PricingFailure(str(exc)) from exc
            # A possible World Series between two clubs with identical
            # records. Which would host is decided by a tiebreak that is not
            # in the data, and this matchup may never happen: price it both
            # ways and average, which favours neither.
            ahead = dict(a_info, win_pct=a_info["win_pct"] + 1e-9)
            behind = dict(b_info, win_pct=b_info["win_pct"] - 1e-9)
            first = ps.series_probabilities_for_round(
                ahead, behind, fmt, self.neutral, home_edge=HOME_FIELD_ADJUSTMENT)
            second = ps.series_probabilities_for_round(
                dict(a_info, win_pct=a_info["win_pct"] - 1e-9),
                dict(b_info, win_pct=b_info["win_pct"] + 1e-9),
                fmt, self.neutral, home_edge=HOME_FIELD_ADJUSTMENT)
            p_a = (first["p_team_a_wins"] + second["p_team_a_wins"]) / 2.0
        return [(a_info, p_a), (b_info, 1.0 - p_a)]


def _announced(ctx: _Context, series: Mapping) -> dict:
    """{team: {series_game_index: pitcher_id}} from the pending schedule
    games between this pair, in date order. These are announced starters of
    games that have not been played: the only future starts that count as
    known."""
    a, b = series["a"]["team"], series["b"]["team"]
    game_type = series["fmt"]["game_type"]
    games = [g for g in ctx.pending
             if g.get("game_type") == game_type
             and {g.get("away_team"), g.get("home_team")} == {a, b}]
    games.sort(key=lambda g: (str(g.get("date") or ""), str(g.get("start_time_utc") or "")))
    played = len(series["games"])
    out = {a: {}, b: {}}
    for offset, game in enumerate(games):
        for side in ("home", "away"):
            pid = _to_int(game.get(f"{side}_probable_id"))
            if pid is not None:
                out[game[f"{side}_team"]][played + offset] = pid
    return out


def _rotation_plan(ctx: _Context, team: str, series: Mapping, announced: Mapping, n_games: int) -> dict:
    """{series_game_index: (pitcher_id, source)} for one team, where source
    is "actual" (already played, or announced), "projected", or None."""
    known = {}
    for index, game in enumerate(series["games"]):
        known[index] = game["home_sp_id"] if game["home"] == team else game["away_sp_id"]
    for index, pid in announced.get(team, {}).items():
        known.setdefault(index, pid)
    cutoff = series["games"][0]["date"] if series["games"] else ctx.cutoff
    try:
        if not ctx.project_starters:
            # A results store that is not current cannot say who has pitched
            # lately, so a rotation projected from it names the wrong
            # pitchers: a start that is not announced or played stays
            # unidentified.
            raise mm.MatchupModelError("rotation projection is switched off")
        pool = mm.build_rotation_pool(ctx.store, team, cutoff)
        return mm.project_team_rotation(pool, known, n_games)
    except mm.MatchupModelError:
        plan = {i: (None, None) for i in range(n_games)}
        for index, pid in known.items():
            if pid is not None:
                plan[index] = (pid, "actual")
        return plan


def _has_started(start_utc, now) -> bool:
    if not start_utc or now is None:
        return False
    try:
        return _parse_now(start_utc) <= now
    except ValueError:
        return False


def _game_certain(played: int, wins: Mapping, k: int, number: int) -> bool:
    """Is game `number` (1-based) certain to be played from this state?"""
    lead = max(wins.values()) if wins else 0
    return lead + (number - 1 - played) < k


def _series_plans(ctx: _Context, series: Mapping) -> tuple:
    """({team: {game_index: (pitcher_id, source)}}, n_games) for one series,
    memoised for the build. `source` is "actual" (played, or named by the
    schedule), "projected", or None."""
    memo = ctx._plan_memo.get(series["id"])
    if memo is None:
        n_games = 2 * series["k"] - 1
        announced = _announced(ctx, series)
        plans = {t["team"]: _rotation_plan(ctx, t["team"], series, announced, n_games)
                 for t in (series["a"], series["b"])}
        memo = ctx._plan_memo[series["id"]] = (plans, n_games)
    return memo


def prefetch_fresh_logs(ctx: _Context, series_map: Mapping) -> None:
    """Look up fresh logs for every identified pitcher of every unplayed game,
    schedule-named pitchers first (then earlier games first), so a capped
    fetcher spends its requests where they decide an estimate."""
    if ctx._fetch is None:
        return
    wanted = []
    for order_no, s in enumerate(series_map.values()):
        if s["a"] is None or s["b"] is None or s["status"] == "complete":
            continue
        plans, n_games = _series_plans(ctx, s)
        for plan in plans.values():
            for index in range(len(s["games"]), n_games):
                pid, source = plan[index]
                if pid is not None:
                    wanted.append((source != "actual", index, order_no, pid))
    for _projected, _index, _order, pid in sorted(wanted):
        ctx.ensure_fresh(pid)


def _worst_class(*classes: str) -> str:
    return max(classes, key=STARTER_CLASSES.index)


def _classify_side(ctx: _Context, pid, source, game_date) -> dict:
    """One starter slot of one unplayed game. `named` is true only when the
    schedule named the pitcher; the slot shows nobody else."""
    named = pid is not None and source == "actual"
    state = {"has_log": False, "current": False, "through": None}
    if pid is None:
        cls = INPUT_UNAVAILABLE
    else:
        ctx.ensure_fresh(pid)
        state = ctx.pitcher_state(pid, game_date)
        if not state["has_log"]:
            cls = INPUT_UNAVAILABLE
        elif not state["current"]:
            cls = STALE_REFERENCE_ONLY
        else:
            cls = CONFIRMED_CURRENT if named else PROJECTED_CURRENT
    return {"id": pid, "named": named, "class": cls, "state": state,
            "name": (ctx.names.get(pid) or f"Pitcher {pid}") if pid is not None else None}


def _slot_view(side: Mapping, used: bool) -> dict:
    """What the starter slot of one side says. A side the schedule has not
    named is "TBD", whatever the rotation projection thinks; a projected
    pitcher is never shown here."""
    named = side["named"]
    note = None
    if named and side["class"] == STALE_REFERENCE_ONLY:
        note = f"numbers on file end {_short_date(side['state']['through'])}, not used"
    elif named and side["class"] == INPUT_UNAVAILABLE:
        note = "no 2026 pitching numbers on file, not used"
    return {
        "id": side["id"] if named else None,
        "name": side["name"] if named else None,
        "source": "actual" if named else None,
        "display": side["name"] if named else "TBD",
        "input_class": side["class"],
        "numbers_through": side["state"]["through"] if named else None,
        "note": note,
        "in_model": bool(named and used),
    }


def _without_starters_words(ctx: _Context) -> str:
    return ("team results, bullpens and ballpark" if ctx.bullpen_current
            else "team results and ballpark")


def _starter_line(ctx: _Context, game_class: str, sides: Mapping) -> str:
    """The one plain-word line a reader sees under a game."""
    if game_class == CONFIRMED_CURRENT:
        return "Starters confirmed, current numbers used"
    stale = [s for s in sides.values() if s["named"] and s["class"] == STALE_REFERENCE_ONLY]
    if stale:
        oldest = min(s["state"]["through"] for s in stale)
        return f"Announced, but pitcher numbers on file end {_short_date(oldest)}: not used"
    if any(s["named"] and s["class"] == INPUT_UNAVAILABLE for s in sides.values()):
        return "Announced, but no 2026 pitching numbers on file: not used"
    both = not any(s["named"] for s in sides.values())
    return (f"{'Starters' if both else 'Starter'} not announced: estimate uses "
            f"{_without_starters_words(ctx)} only")


def _starter_note(sides: Mapping, game_class: str) -> Optional[str]:
    if game_class == CONFIRMED_CURRENT:
        return None
    if any(s["named"] and s["class"] == INPUT_UNAVAILABLE for s in sides.values()):
        return ("A starter has no 2026 pitching log, so the starters are not in "
                "this estimate.")
    if any(s["named"] and s["class"] == STALE_REFERENCE_ONLY for s in sides.values()):
        return ("A starter's pitching figures are out of date, so the starters are "
                "not in this estimate.")
    return None


def _starter_reason(sides: Mapping) -> str:
    """Why the starters are not used, in the words of the inputs line."""
    parts = []
    if any(not s["named"] for s in sides.values()):
        parts.append("not announced")
    stale = [s for s in sides.values() if s["named"] and s["class"] == STALE_REFERENCE_ONLY]
    if stale:
        parts.append("numbers on file end "
                     + _short_date(min(s["state"]["through"] for s in stale)))
    if any(s["named"] and s["class"] == INPUT_UNAVAILABLE for s in sides.values()):
        parts.append("no 2026 pitching numbers on file")
    return "; ".join(parts) or "not available"


def _inputs_text(inputs: Sequence[Mapping]) -> str:
    """'2 of 4 inputs are current and used: team results through Sept 30,
    ballpark. Not used: starting pitchers (not announced), bullpens (numbers
    on file end Sept 6).' Counts and names only."""
    def named(c, with_through=True):
        return (f"{c['label']} through {_short_date(c['through'])}"
                if with_through and c.get("through") else c["label"])

    current = [c for c in inputs if c["used"] and c["status"] in ("CURRENT", CONFIRMED_CURRENT)]
    stale_used = [c for c in inputs if c["used"] and c not in current]
    unused = [c for c in inputs if not c["used"]]
    head = (f"All {len(inputs)} inputs are current and used"
            if len(current) == len(inputs)
            else f"{len(current)} of {len(inputs)} inputs are current and used")
    text = head + (": " + ", ".join(named(c) for c in current) if current else "") + "."
    if stale_used:
        text += (" Used, but not current: "
                 + ", ".join(named(c) for c in stale_used) + ".")
    if unused:
        text += (" Not used: "
                 + ", ".join(f"{c['label']} ({c['note']})" if c.get("note") else c["label"]
                             for c in unused) + ".")
    return text


def _results_component(ctx: _Context) -> dict:
    current = results_are_current(ctx.results_through, ctx.today)
    through = ctx.results_through
    return {"key": "team_results", "label": INPUT_LABELS["team_results"], "used": True,
            "status": "CURRENT" if current else STALE_REFERENCE_ONLY, "through": through,
            "note": None if current else
            f"results on file end {_short_date(through)}" if through else "no results date"}


def _park_component() -> dict:
    return {"key": "park", "label": INPUT_LABELS["park"], "used": True, "status": "CURRENT",
            "through": None, "note": None}


def _bullpen_component(ctx: _Context) -> dict:
    if ctx.bullpen_current:
        status, note = "CURRENT", None
    elif ctx.bullpen_through is None:
        status, note = INPUT_UNAVAILABLE, "no bullpen numbers on file"
    else:
        status = STALE_REFERENCE_ONLY
        note = f"numbers on file end {_short_date(ctx.bullpen_through)}"
    return {"key": "bullpens", "label": INPUT_LABELS["bullpens"], "used": ctx.bullpen_current,
            "status": status, "through": ctx.bullpen_through, "note": note}


def _game_inputs(ctx: _Context, game_class: str, sides: Mapping) -> list:
    used = game_class == CONFIRMED_CURRENT
    throughs = [s["state"]["through"] for s in sides.values() if s["state"]["through"]]
    starters = {
        "key": "starters", "label": INPUT_LABELS["starters"], "used": used,
        "status": game_class,
        "through": min(throughs) if throughs and (used or game_class == STALE_REFERENCE_ONLY)
        else None,
        "note": None if used else _starter_reason(sides),
    }
    inputs = [_results_component(ctx), _park_component(), starters, _bullpen_component(ctx)]
    if used:
        inputs.append(_league_baseline_component(ctx))
    return inputs


def _league_baseline_component(ctx: _Context) -> dict:
    """The league-wide pitching average a used starter's rate is measured
    against (`pitchers.league_fip_constant`), as an input of its own.

    Owner's rule, 2026-10-01: it must not read as current because the
    starter's own log is. It is computed from every STORED pitcher log, so it
    is as old as the store even when the starter was confirmed from a log
    fetched fresh. Present only on a game whose number carries starters; a
    game priced without them does not use it at all.

    Measured the same day (docs/audit/2026-10-01/league_baseline_sensitivity
    .txt): the stored constant was 3.3107 against 3.2407 from the official
    season totals, which moved the one game using starters by 0.29 points and
    no World Series chance by more than 0.04. So it is surfaced, not repaired."""
    current = ctx.pitcher_store_current
    through = ctx.pitcher_through
    return {"key": "league_pitching_baseline", "label": INPUT_LABELS["league_pitching_baseline"],
            "used": True, "status": "CURRENT" if current else STALE_REFERENCE_ONLY,
            "through": through,
            "note": None if current else
            (f"computed from stored logs that end {_short_date(through)}" if through
             else "computed from stored logs with no date")}


def price_series(ctx: _Context, series: dict) -> dict:
    """Series chance and per-game detail for a series whose teams are known
    and which is not yet complete. Returns {"chance": {team: p}, "games": [...]}.

    Every unplayed game's starter slots are classified (`_classify_side`);
    the game's primary chance carries the starters only when both sides are
    CONFIRMED_CURRENT, and the series chance is built from those primary
    chances alone. A PROJECTED_CURRENT game also carries a separately priced
    `scenarios` entry, which feeds nothing."""
    a, b = series["a"], series["b"]
    fmt, k = series["fmt"], series["k"]
    played = len(series["games"])
    pattern = fmt["home_pattern"]
    plans, n_games = _series_plans(ctx, series)

    scheduled_games = sorted(
        (g for g in ctx.pending
         if g.get("game_type") == fmt["game_type"]
         and {g.get("away_team"), g.get("home_team")} == {a["team"], b["team"]}),
        key=lambda g: (str(g.get("date") or ""), str(g.get("start_time_utc") or "")))

    detail = []
    probs_for_a = []
    for index in range(played, n_games):
        home, away = (a, b) if pattern[index] else (b, a)
        away_sp, away_src = plans[away["team"]][index]
        home_sp, home_src = plans[home["team"]][index]

        slot = index - played
        scheduled = scheduled_games[slot] if slot < len(scheduled_games) else None
        start_utc = scheduled.get("start_time_utc") if scheduled else None
        game_date = scheduled.get("date") if scheduled else None

        sides = {"away": _classify_side(ctx, away_sp, away_src, game_date),
                 "home": _classify_side(ctx, home_sp, home_src, game_date)}
        game_class = _worst_class(sides["away"]["class"], sides["home"]["class"])
        use_starters = game_class == CONFIRMED_CURRENT
        p_home, feats = ctx.price_game(
            away["team"], home["team"],
            away_sp if use_starters else None, home_sp if use_starters else None, game_date)
        if use_starters and not feats.get("both_sp_known"):
            # Cannot happen when the class and the model read the same rows;
            # if it ever does, the starters are not in the number, so say so.
            use_starters, game_class = False, INPUT_UNAVAILABLE
            p_home, feats = ctx.price_game(away["team"], home["team"], None, None, game_date)
        probs_for_a.append(p_home if home is a else 1.0 - p_home)

        scenarios = []
        if game_class == PROJECTED_CURRENT:
            p_scn, _feats = ctx.price_game(
                away["team"], home["team"], away_sp, home_sp, game_date)
            scenarios.append({
                "key": "projected_rotation",
                "label": ("If the projected starters pitch (not announced): "
                          f"{sides['away']['name']} at {sides['home']['name']}"),
                "home_chance": _round6(p_scn), "away_chance": _round6(1.0 - p_scn),
                "starters": {"away": {"id": away_sp, "name": sides["away"]["name"]},
                             "home": {"id": home_sp, "name": sides["home"]["name"]}},
            })

        # The machine labels say what the starters are in THIS number: the
        # model's own vocabulary, kept for the ledger and the tests.
        dispositions = mm.per_game_factor_dispositions(away_src, home_src)
        label = {CONFIRMED_CURRENT: MODEL_USED,
                 PROJECTED_CURRENT: SCENARIO_INPUT}.get(game_class, UNAVAILABLE)
        dispositions["starting_pitcher"] = label
        named_sides = [s for s in sides.values() if s["named"]]
        if game_class == CONFIRMED_CURRENT:
            status = "announced"
        elif game_class == PROJECTED_CURRENT:
            status = "projected"
        elif any(s["class"] == INPUT_UNAVAILABLE for s in named_sides):
            status = "announced_no_log"
        elif any(s["class"] == STALE_REFERENCE_ONLY for s in named_sides):
            status = "announced_stale"
        else:
            status = "not_announced"

        inputs = _game_inputs(ctx, game_class, sides)
        detail.append({
            "number": index + 1,
            "status": "next" if index == played else "future",
            # The game has begun but is not final: its result is not in these
            # numbers, and it is not described as played.
            "started": bool(index == played and _has_started(start_utc, ctx.now)),
            "if_needed": not _game_certain(played, series["wins"], k, index + 1),
            "date": game_date,
            "start_utc": start_utc,
            "venue": scheduled.get("venue") if scheduled else None,
            "home": home["team"], "away": away["team"],
            "home_chance": _round6(p_home),
            "away_chance": _round6(1.0 - p_home),
            "starters": {"home": _slot_view(sides["home"], use_starters),
                         "away": _slot_view(sides["away"], use_starters)},
            "starter_input_class": game_class,
            "starter_label": label,
            "starter_status": status,
            "starter_text": _starter_line(ctx, game_class, sides),
            "starter_note": _starter_note(sides, game_class),
            "scenarios": scenarios,
            "inputs": inputs,
            "inputs_used_text": _inputs_text(inputs),
            "factors": dispositions,
        })

    try:
        chance_a = mm.conditional_series_win_prob(
            probs_for_a, series["wins"][a["team"]], series["wins"][b["team"]], k)
    except (mm.MatchupModelError, ps.PostseasonError) as exc:
        raise PricingFailure(str(exc)) from exc
    return {"chance": {a["team"]: chance_a, b["team"]: 1.0 - chance_a}, "games": detail}


# ---------------------------------------------------------------------------
# bracket odds conditioned on the state
# ---------------------------------------------------------------------------

def _positive(outcomes):
    return [(info, p) for info, p in outcomes if p > 0.0]


def _league_odds(ctx: _Context, seeds: Mapping) -> dict:
    """`league_pennant_probabilities`' walk, conditioned on the real state:
    every completed or in-progress series contributes its own number and
    every undecided one a team-strength price."""
    reaches_ds = {seeds[s]["team"]: 0.0 for s in pc.FIELD_SEEDS}
    reaches_lcs = dict(reaches_ds)
    pennant = dict(reaches_ds)
    for s in pc.BYE_SEEDS:
        reaches_ds[seeds[s]["team"]] = 1.0

    wc_outcomes = {}
    for key in pc.WILD_CARD_SERIES_KEYS:
        hi, lo = pc.WILD_CARD_PAIRINGS[key]
        outcomes = _positive(ctx.outcomes(seeds[hi], seeds[lo], pc.WILD_CARD))
        wc_outcomes[key] = outcomes
        for info, p in outcomes:
            reaches_ds[info["team"]] += p

    ordered = [wc_outcomes[key] for key in pc.WILD_CARD_SERIES_KEYS]
    for choice in itertools.product(*ordered):
        winners = dict(zip(pc.WILD_CARD_SERIES_KEYS, (c[0] for c in choice)))
        wc_prob = 1.0
        for _info, p in choice:
            wc_prob *= p
        matchups = [(seeds[1], winners[pc.DS_OPPONENT_SERIES_FOR_SEED[1]]),
                    (seeds[2], winners[pc.DS_OPPONENT_SERIES_FOR_SEED[2]])]
        ds_outcomes = [_positive(ctx.outcomes(x, y, pc.DIVISION_SERIES)) for x, y in matchups]
        for ds_choice in itertools.product(*ds_outcomes):
            (w1, p1), (w2, p2) = ds_choice
            path = wc_prob * p1 * p2
            reaches_lcs[w1["team"]] += path
            reaches_lcs[w2["team"]] += path
            for info, p in _positive(ctx.outcomes(w1, w2, pc.LCS)):
                pennant[info["team"]] += path * p
    return {"reaches_division_series": reaches_ds, "reaches_lcs": reaches_lcs,
            "wins_pennant": pennant}


def _world_series_odds(ctx: _Context, al: Mapping, nl: Mapping, info_by_team: Mapping) -> dict:
    wins: dict = {}
    for al_team, p_al in al.items():
        if p_al <= 0.0:
            continue
        for nl_team, p_nl in nl.items():
            if p_nl <= 0.0:
                continue
            a_info, b_info = info_by_team[al_team], info_by_team[nl_team]
            outcomes = ctx.outcomes(a_info, b_info, pc.WORLD_SERIES)
            joint = p_al * p_nl
            wins[al_team] = wins.get(al_team, 0.0) + joint * outcomes[0][1]
            wins[nl_team] = wins.get(nl_team, 0.0) + joint * outcomes[1][1]
    return wins


# ---------------------------------------------------------------------------
# the forecast ledger
# ---------------------------------------------------------------------------

def _said_before(rows: Sequence[Mapping], series_id: str, teams: Sequence[str]) -> Optional[dict]:
    """The earliest ledger row for `series_id` written before game 1 (score
    0-0), or None. This is the public grading of the forecasts: a series
    that started before the first snapshot has nothing here and says so."""
    candidates = [r for r in rows
                  if r.get("series_id") == series_id and r.get("games_played") == 0
                  and isinstance(r.get("series_chance"), Mapping)]
    if not candidates:
        return None
    first = min(candidates, key=lambda r: str(r.get("date") or ""))
    chance = {t: first["series_chance"].get(t) for t in teams}
    if any(v is None for v in chance.values()):
        return None
    favourite = max(chance, key=lambda t: chance[t])
    return {"date": first.get("date"), "chance": chance, "favourite": favourite,
            "rated_higher": favourite, "model": first.get("model")}


# ---------------------------------------------------------------------------
# payload assembly
# ---------------------------------------------------------------------------

def _team_line(series: Mapping, info: Mapping, chance: Optional[Mapping]) -> dict:
    team = info["team"]
    return {"team": team, "name": info.get("name"), "seed": info.get("seed"),
            "wins": series["wins"].get(team, 0) if series["wins"] else 0,
            "chance": _round6(chance.get(team)) if chance else None}


def _game_result(game: Mapping, number: int) -> dict:
    return {"number": number, "status": "final", "date": game["date"],
            "home": game["home"], "away": game["away"],
            "home_score": game["home_score"], "away_score": game["away_score"],
            "winner": game["winner"], "venue": game.get("venue")}


def _score_text(series: Mapping) -> Optional[str]:
    if not series["a"] or not series["b"]:
        return None
    a, b = series["a"]["team"], series["b"]["team"]
    wa, wb = series["wins"].get(a, 0), series["wins"].get(b, 0)
    if series["winner"] is not None:
        return f"{series['winner']['team']} won {max(wa, wb)}-{min(wa, wb)}"
    if wa == wb:
        return f"Tied {wa}-{wb}" if wa else "Series not started"
    lead, trail = (a, b) if wa > wb else (b, a)
    return f"{lead} leads {max(wa, wb)}-{min(wa, wb)}"


def _series_payload(ctx: _Context, series: dict, priced: Optional[dict], ledger_rows) -> dict:
    a, b = series["a"], series["b"]
    out = {
        "id": series["id"], "league": series["league"], "round": series["round"],
        "round_label": series["round_label"], "slot": series["slot"],
        "slot_label": series["slot_label"], "best_of": series["fmt"]["best_of"],
        "status": series["status"], "waiting_on": list(series["waiting_on"]),
        "home_field": a["team"] if a else None,
        "teams": [], "score_text": None, "next_game": None, "games": [],
        "winner": None, "final_score": None, "said_before": None,
    }
    if a is None or b is None:
        out["teams"] = [{"team": t["team"], "name": t.get("name"), "seed": t.get("seed"),
                         "wins": 0, "chance": None} for t in series["known"]]
        return out

    if priced:
        chance = priced["chance"]
    elif series["winner"] is not None:
        chance = {series["winner"]["team"]: 1.0, series["loser"]["team"]: 0.0}
    else:
        chance = None
    out["teams"] = [_team_line(series, a, chance), _team_line(series, b, chance)]
    out["score_text"] = _score_text(series)

    games = [_game_result(g, i + 1) for i, g in enumerate(series["games"])]
    if priced:
        games.extend(priced["games"])
        out["next_game"] = priced["games"][0] if priced["games"] else None
    out["games"] = games

    if series["winner"] is not None:
        winner, loser = series["winner"]["team"], series["loser"]["team"]
        out["winner"] = winner
        out["final_score"] = (f"{winner} won {series['wins'][winner]}-{series['wins'][loser]}")
        before = _said_before(ledger_rows, series["id"], [a["team"], b["team"]])
        if before is not None:
            before["favourite_advanced"] = before["favourite"] == winner
            before["rated_higher_advanced"] = before["favourite_advanced"]
        out["said_before"] = before
        out["said_before_note"] = (
            None if before is not None else
            "No forecast was recorded before game 1 of this series.")
    return out


def _team_table(seeds, series_list, odds) -> list:
    eliminated = {}
    for s in series_list:
        if s["status"] == "complete":
            eliminated[s["loser"]["team"]] = f"Eliminated in the {s['round_label']}"
    champion = None
    ws = next((s for s in series_list if s["round"] == "WS" and s["status"] == "complete"), None)
    if ws is not None:
        champion = ws["winner"]["team"]

    rows = []
    for league in pc.LEAGUES:
        for seed in pc.FIELD_SEEDS:
            info = seeds[league][seed]
            team = info["team"]
            if team == champion:
                status, text = "champion", "World Series champion"
            elif team in eliminated:
                status, text = "eliminated", eliminated[team]
            else:
                status, text = "alive", None
            rows.append({
                "team": team, "name": info.get("name"), "league": league, "seed": seed,
                "status": status, "status_text": text,
                "reaches_division_series": _round6(odds["reaches_division_series"].get(team, 0.0)),
                "reaches_lcs": _round6(odds["reaches_lcs"].get(team, 0.0)),
                "wins_pennant": _round6(odds["wins_pennant"].get(team, 0.0)),
                "wins_world_series": _round6(odds["wins_world_series"].get(team, 0.0)),
            })
    rows.sort(key=lambda r: (-(r["wins_world_series"] or 0.0), -(r["wins_pennant"] or 0.0),
                             r["team"]))
    return rows


def _inputs_through(pitcher_logs, bullpen_log, season=None, today=None) -> dict:
    """The newest date in each store, ignoring rows dated after `today` and,
    when `season` is given, rows from other seasons."""
    def keep(day) -> bool:
        day = str(day or "")
        return bool(day) and (today is None or day <= today)             and (season is None or day.startswith(season))

    pitcher_dates = [str(a.get("date")) for appearances in (pitcher_logs or {}).values()
                     for a in appearances if keep(a.get("date"))]
    bullpen_dates = [str(r.get("date")) for r in (bullpen_log or []) if keep(r.get("date"))]
    return {"pitcher_logs": max(pitcher_dates) if pitcher_dates else None,
            "bullpen_log": max(bullpen_dates) if bullpen_dates else None}


def _load_default(name: str):
    if name == "results":
        from src.pipeline import history
        return history.read_results(), history.read_manifest()
    if name == "standings":
        from src.pipeline import standings as standings_mod
        return standings_mod.read()
    if name == "pitchers":
        from src.pipeline import pitchers
        return pitchers.read_logs()
    if name == "bullpen":
        from src.pipeline import bullpen
        return bullpen.read_log()
    if name == "ledger":
        from src.ledger.chain import HashChainLedger
        from src.paths import evidence_path
        return HashChainLedger(evidence_path("postseason_forecasts.jsonl")).read()
    raise KeyError(name)


def _method_note(inputs_through: Mapping) -> str:
    return (
        "Each game is priced from both teams' season run rates and the park. Each "
        "bullpen's season record and the starting pitchers are added only when "
        f"their numbers are current, meaning no more than {CURRENT_INPUT_DAYS} days "
        "older than the latest results. A starter counts only when the schedule has "
        "named him, he has a 2026 pitching log and that log is current. A starter "
        "the schedule has not named is shown as TBD and is never filled in with a "
        "guess. A game whose starters are not confirmed is priced without starting "
        "pitchers. When the schedule names nobody but the team's rotation points to "
        "a pitcher, a separate what-if line shows that game with the projected "
        "starters; it is labelled, and it never changes a series, pennant or World "
        "Series chance. A series chance is the exact chance of reaching the needed "
        "wins from the current score, game by game, with home games where the "
        "schedule puts them. A series whose teams are not set yet is priced from "
        "team strength and park (and bullpens when current) with a flat home-field "
        "adjustment, and series in the same round are worked out separately, as "
        "if one did not affect another. Pennant and World Series chances add up "
        "every way the bracket can still play out. The stored pitcher numbers run "
        f"through {inputs_through.get('pitcher_logs') or 'an unknown date'} and the "
        f"stored bullpen numbers through {inputs_through.get('bullpen_log') or 'an unknown date'}.")


def _input_summary(ctx: _Context, priced: Mapping) -> dict:
    """The four inputs judged across the page, and one plain sentence. Counts
    and names only; no share of any forecast."""
    games = [g for p in priced.values() for g in p["games"]]
    counts = {c: 0 for c in STARTER_CLASSES}
    for g in games:
        counts[g["starter_input_class"]] += 1
    total = len(games)
    confirmed = counts[CONFIRMED_CURRENT]
    pitcher_through = ctx.pitcher_through
    present = [c for c in STARTER_CLASSES if counts[c]]
    # The weakest class present, as for a single game; `used` says whether
    # any game's number has starters in it at all.
    starter_status = _worst_class(*present) if present else INPUT_UNAVAILABLE
    starter_used = confirmed > 0
    if not total:
        note = "no games with set matchups are left to estimate"
    elif confirmed:
        note = f"{confirmed} of {total} games still to play have confirmed starters"
    else:
        note = f"none of the {total} games still to play has a confirmed starter"
    starters = {"key": "starters", "label": INPUT_LABELS["starters"], "used": starter_used,
                "status": starter_status, "through": pitcher_through, "note": note,
                "counts": dict(counts)}
    bullpens = _bullpen_component(ctx)
    components = [_results_component(ctx), _park_component(), starters, bullpens]

    if not total:
        first = "No game with a set matchup is left to estimate"
    elif confirmed:
        first = (f"Starting pitchers are in {confirmed} of {total} games still to play, "
                 "the ones with a confirmed starter and current numbers; the rest are "
                 "estimated without them")
    else:
        first = (f"None of the {total} games still to play has a confirmed starter with "
                 "current numbers, so starting pitchers are left out of every estimate")
    if ctx.bullpen_current:
        second = "bullpens are included"
    elif ctx.bullpen_through is None:
        second = "bullpens are left out because no bullpen numbers are on file"
    else:
        second = ("bullpens are left out because their numbers on file end "
                  + _short_date(ctx.bullpen_through))
    text = f"{first}; {second}."
    # One number behind a used starter is NOT his own: the league-wide
    # baseline his rate is measured against (the model's FIP constant) is
    # computed from every stored pitcher log. When that store is behind, the
    # baseline is behind too. It is a league average over a whole season and
    # barely moves in a few weeks, but it is a stale pitcher-derived number in
    # the estimate, so the page says so wherever a starter is used.
    if confirmed and not ctx.pitcher_store_current and pitcher_through:
        text += (" Where a starter is used his own numbers are current; the league-wide "
                 "pitching average they are compared with is computed from the stored "
                 "logs, which end " + _short_date(pitcher_through) + ".")
    return {"components": components, "starter_counts": dict(counts), "unplayed_games": total,
            "text": text}


def _join_words(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _grading_note(payloads: Sequence[Mapping], ledger_rows: Sequence[Mapping]) -> str:
    """The sentence under HOW WE GRADE THIS, written from what the forecast
    ledger holds, never from a promise. A series is "recorded" when the ledger
    has a row for it from before game 1 (`_said_before`). The ledger did not
    exist for the Wild Card round, so a page built from a ledger with no Wild
    Card rows says so; the forward-looking sentence appears only for rounds
    whose series already have their rows."""
    order = {k: i for i, k in enumerate(ROUND_KEYS)}
    known = [p for p in payloads if len(p["teams"]) == 2]

    def recorded(p) -> bool:
        return _said_before(ledger_rows or [], p["id"], [t["team"] for t in p["teams"]]) is not None

    missed = [p for p in known if p["status"] in ("live", "complete") and not recorded(p)]
    parts = []
    for key in ROUND_KEYS:
        gone = [p for p in missed if p["round"] == key]
        if not gone:
            continue
        label = ROUND_LABEL[key]
        if len(gone) == sum(1 for p in known if p["round"] == key):
            parts.append(f"The {label} started before its estimates were written down, "
                         "so it cannot be graded.")
        else:
            parts.append(f"Some {label} series started before their estimates were "
                         "written down, so those cannot be graded.")

    if known and all(recorded(p) for p in known):
        parts.append("Each series estimate is written down before its first game and kept.")
    elif missed:
        last_missed = max(order[p["round"]] for p in missed)
        for key in ROUND_KEYS[last_missed + 1:]:
            later = [p for p in known if order[p["round"]] >= order[key]]
            if later and any(p["round"] == key for p in later) and all(recorded(p) for p in later):
                parts.append(f"Starting with the {ROUND_LABEL[key]}, each series estimate is "
                             "written down before its first game and kept.")
                break

    if any(recorded(p) for p in known):
        parts.append("When a series ends, the page shows what was written down next to "
                     "what happened.")
    else:
        parts.append("Once a series with a recorded estimate ends, the page will show what "
                     "was written down next to what happened.")
    return " ".join(parts)


def capped_pitcher_fetcher(fetch: Callable[[int], Optional[list]], *, cap: int,
                           memo: Optional[dict] = None, day: Optional[str] = None,
                           lock=None) -> Callable[[int], Optional[list]]:
    """A `fresh_pitcher_logs` for `build`, wrapped around an injected
    `fetch(pitcher_id) -> rows` (`mlb.fetch_pitcher_game_log` bound to the
    season in production; this module does no network itself).

      * at most `cap` NEW requests per fetcher (one fetcher per build); a
        pitcher past the cap is skipped, which leaves his numbers stale, and
        `report()` says how many were skipped;
      * with a `memo` dict and a `day`, a successful answer is remembered under
        (pitcher_id, day) and a later fetcher for the same day reuses it
        without a request; an answer is never remembered across days, and a
        failed request is never remembered, so the next build tries again;
      * any exception from `fetch` is swallowed and returns None: a failed
        lookup leaves the pitcher stale and never fails the build.

    The returned callable has `.requests` and `.skipped` counters and a
    `.report(stream)` that writes the skipped count when the cap bit."""
    guard = lock if lock is not None else threading.Lock()
    state = {"requests": 0, "skipped": 0}

    def fetcher(pid):
        key = (pid, day)
        if memo is not None:
            with guard:
                if key in memo:
                    return memo[key]
        with guard:
            if state["requests"] >= cap:
                state["skipped"] += 1
                return None
            state["requests"] += 1
        try:
            rows = fetch(pid)
        except Exception:  # noqa: BLE001 -- a failed lookup leaves the pitcher stale
            return None
        if memo is not None and isinstance(rows, (list, tuple)):
            with guard:
                for stale in [k for k in memo if k[1] != day]:
                    del memo[stale]
                memo[key] = list(rows)
        return rows

    def report(stream=None):
        if state["skipped"]:
            print(f"postseason: pitcher log lookups capped at {cap}; "
                  f"{state['skipped']} pitcher(s) skipped and left with stored numbers",
                  file=stream or sys.stderr, flush=True)

    fetcher.report = report
    fetcher.counts = state
    return fetcher


def build(now, results_store=None, standings=None, probables=None, *,
          pitcher_logs=None, bullpen_log=None, ledger_rows=None,
          results_through=None,
          fresh_pitcher_logs: Optional[Callable[[int], Optional[list]]] = None) -> dict:
    """The public postseason page, as a JSON-ready dict.

    `now` -- an aware datetime or ISO string; nothing dated after it is read.
    `results_store` -- `history.read_results()` shape ({game_pk: row}); read
        from disk when None.
    `standings` -- `standings.read()` shape ({date: {team: row}}) or a flat
        row list; read from disk when None.
    `probables` -- upcoming schedule games (`mlb.parse_game` shape, with
        `*_probable_id`); None means none are known and every future starter
        is projected or unavailable.
    `pitcher_logs` / `bullpen_log` -- injected for tests, read from disk when
        None. `ledger_rows` -- the forecast ledger's rows, for the "what we
        said before game 1" lines. `results_through` -- the newest date the
        results ingest fully covered; defaults to the newest date in the
        store.
    `fresh_pitcher_logs` -- optional `fn(pitcher_id) -> rows | None`, called at
        most once per identified pitcher whose stored numbers are not current,
        returning rows in the shape `pitchers.read_logs()` yields (the shape
        `mlb.fetch_pitcher_game_log` returns, which is what the daily job
        stores). See `_Context.ensure_fresh` for the rule; None (the default)
        keeps the builder pure, and a fetcher that raises or returns None
        leaves that pitcher's numbers stale.

    Returns `{"available": False, "reason": ...}` when the field or a series
    state cannot be determined from the data.
    """
    now_dt = _parse_now(now)
    # The baseball (US Eastern) date, not the UTC one: results, the schedule
    # and the lag guard are all filed under it, and from 8 pm Eastern the UTC
    # date is already tomorrow.
    today = baseball_date(now_dt)
    season = pc.REGULAR_SEASON_ENDS[:4]

    try:
        manifest = None
        if results_store is None:
            results_store, manifest = _load_default("results")
        if standings is None:
            standings = _load_default("standings")
        if results_through is None and manifest is not None:
            from src.providers import mlb
            results_through = results_through_from_manifest(manifest, mlb.DECISIVE_GAME_TYPES)

        # Point in time: nothing after `now` is ever read. Only this season is
        # kept: every feature the model reads is same-season by construction,
        # so older rows could not change a number and only slow every price.
        store = {k: r for k, r in results_store.items()
                 if str(r.get("date") or "").startswith(season)
                 and str(r.get("date") or "") <= today}

        by_date = _standings_by_date(standings)
        snapshot = _final_snapshot(by_date, today)
        if snapshot is None:
            latest = max(by_date) if by_date else None
            return _unavailable_for(
                "final_standings",
                "The final regular-season standings are not available yet, so the "
                "12-team field cannot be set. "
                + (f"The newest standings on file are from {latest}; the regular season "
                   f"ended {pc.REGULAR_SEASON_ENDS}." if latest else "No standings are on file."),
                now_dt)
        standings_date, standings_rows = snapshot
        seeds = seeds_from_standings(standings_rows)

        seeded = {info["team"] for lg in seeds.values() for info in lg.values()}
        in_store = {t for r in store.values() if str(r.get("date") or "").startswith(season)
                    for t in (r.get("home_team"), r.get("away_team"))}
        missing_teams = sorted(seeded - in_store)
        if missing_teams:
            raise FieldUnknown(
                "these seeded clubs have no 2026 games in the results store: "
                + ", ".join(missing_teams))

        games = postseason_games(store, season, today)
        pending = [g for g in (probables or [])
                   if str(g.get("state") or "") not in ("final", "cancelled")
                   and g.get("game_type") in ROUND_BY_GAME_TYPE]
        series = resolve_series(seeds, games, season, pending)

        store_through = newest_result_date(store, season, today)
        through = results_through or store_through
        champion_known = series[f"{season}-MLB-WS-1"]["status"] == "complete"
        if (not champion_known and today >= pc.CALENDAR["wild_card"]["start"]
                and (through is None or
                     (_date_cls.fromisoformat(today) - _date_cls.fromisoformat(through)).days
                     > MAX_RESULTS_LAG_DAYS)):
            return _unavailable_for(
                "results",
                "The postseason is under way but the results on file only run through "
                f"{through or 'an unknown date'}, so the series scores cannot be "
                "shown as current.", now_dt, results_through=through)

        if pitcher_logs is None:
            pitcher_logs = _load_default("pitchers")
        # REGULAR SEASON ONLY, for every number this build prices and every
        # date it prints. The stored log also holds postseason starts, tagged
        # with their `game_type`, so the page can see October; a starter's
        # season-to-date numbers are a model input and a postseason start is a
        # different, selected population. Filtering here (a copy, at the
        # consumer; `pitchers.read_logs` stays whole because the store is
        # rewritten from it) makes every figure below what it was before any
        # postseason row was stored, including the "run through" date and the
        # currency rule that decides whether a starter counts at all.
        pitcher_logs = pitchers_mod.regular_season_logs(pitcher_logs)
        if bullpen_log is None:
            bullpen_log = _load_default("bullpen")
        bullpen_all = bullpen_log
        bullpen_log = [r for r in bullpen_log if str(r.get("date") or "").startswith(season)]
        if ledger_rows is None:
            try:
                ledger_rows = _load_default("ledger")
            except Exception:  # noqa: BLE001 -- a missing ledger only removes the grading line
                ledger_rows = []

        cutoff = _iso_plus(today, 1)
        league_rpg = mm.league_rpg_from_store(store, cutoff)
        if not league_rpg:
            raise PricingFailure("no league run rate is available from the results store")
        as_of = max(d for d in (store_through, standings_date) if d)
        inputs_through = _inputs_through(pitcher_logs, bullpen_all, season, today)
        pitcher_season = _inputs_through(pitcher_logs, [], season, today)["pitcher_logs"]
        bullpen_season = _inputs_through({}, bullpen_all, season, today)["bullpen_log"]
        ctx = _Context(store, pitcher_logs, bullpen_log, cutoff, league_rpg, pending,
                       project_starters=results_are_current(through, today), now=now_dt,
                       as_of=as_of, pitcher_through=pitcher_season,
                       bullpen_through=bullpen_season, results_through=through,
                       today=today, fresh_pitcher_logs=fresh_pitcher_logs)
        prefetch_fresh_logs(ctx, series)

        # 1. real series first: their numbers feed the bracket walk.
        priced: dict = {}
        for sid, s in series.items():
            if s["a"] is None or s["b"] is None:
                continue
            if s["status"] == "complete":
                chance = {s["winner"]["team"]: 1.0, s["loser"]["team"]: 0.0}
            else:
                priced[sid] = price_series(ctx, s)
                chance = priced[sid]["chance"]
            ctx.real_chance[(s["fmt"]["name"], frozenset(chance))] = chance

        # 2. the bracket walk, conditioned on those.
        per_league = {lg: _league_odds(ctx, seeds[lg]) for lg in pc.LEAGUES}
        info_by_team = {info["team"]: info for lg in seeds.values() for info in lg.values()}
        ws_wins = _world_series_odds(
            ctx, per_league["AL"]["wins_pennant"], per_league["NL"]["wins_pennant"], info_by_team)
        odds = {
            "reaches_division_series": {**per_league["AL"]["reaches_division_series"],
                                        **per_league["NL"]["reaches_division_series"]},
            "reaches_lcs": {**per_league["AL"]["reaches_lcs"], **per_league["NL"]["reaches_lcs"]},
            "wins_pennant": {**per_league["AL"]["wins_pennant"], **per_league["NL"]["wins_pennant"]},
            "wins_world_series": ws_wins,
        }
    except FieldUnknown as exc:
        return _unavailable_for(
            "field", f"The postseason field or a series state cannot be set from the data on file: {exc}",
            now_dt)
    except PricingFailure as exc:
        return _unavailable_for(
            "pricing", f"A series could not be priced from the data on file: {exc}", now_dt)

    order = {k: i for i, k in enumerate(ROUND_KEYS)}
    ordered = sorted(series.values(), key=lambda s: (
        order[s["round"]], {"AL": 0, "NL": 1}.get(s["league"], 2), s["slot"]))
    payloads = [_series_payload(ctx, s, priced.get(s["id"]), ledger_rows or []) for s in ordered]

    live_round = next((s["round"] for s in ordered if s["status"] in ("live", "upcoming")), None)
    completed = [p for p in payloads if p["status"] == "complete"]
    graded = [p for p in completed if p["said_before"] is not None]
    ws_payload = next(p for p in payloads if p["round"] == "WS")
    lead = stale_input_caveats(inputs_through, as_of)
    caveats = [*lead, CAVEAT]
    caveats.append(
        "A starting pitcher counts only when the schedule has named him and his numbers "
        "are current. Otherwise the game is estimated without starting pitchers, and a "
        "starter the schedule has not named stays TBD: a projected starter is a guess "
        "and appears only as a separate, labelled what-if line.")
    summary = _input_summary(ctx, priced)
    caveats.append("Series scores run through the date shown; a game played since then is not "
                   "in these numbers.")

    return {
        "available": True,
        "season": int(season),
        "as_of": as_of,
        "results_through": through,
        "standings_date": standings_date,
        "built_at": now_dt.isoformat(),
        "model": MODEL_ID,
        "model_name": MODEL_NAME,
        "method": _method_note(inputs_through),
        "caveats": caveats,
        # How many of `caveats` the page leads with: any stale-data caveats
        # and the one that says these are estimates.
        "lead_caveat_count": len(lead) + 1,
        "grading_note": _grading_note(payloads, ledger_rows or []),
        "inputs_through": inputs_through,
        "current_input_days": CURRENT_INPUT_DAYS,
        "input_summary": summary,
        "live_round": live_round,
        "live_round_label": ROUND_LABEL.get(live_round),
        "champion": ws_payload["winner"],
        "calendar": {ROUND_LABEL[k]: pc.CALENDAR[ROUND_CALENDAR_KEY[k]] for k in ROUND_KEYS},
        "seeds": {lg: [{"seed": i, "team": seeds[lg][i]["team"], "name": seeds[lg][i].get("name")}
                       for i in pc.FIELD_SEEDS] for lg in pc.LEAGUES},
        "series": payloads,
        "teams": _team_table(seeds, ordered, odds),
        "scorecard": {
            "completed_series": len(completed),
            "graded_before_game_one": len(graded),
            "favourite_advanced": sum(1 for p in graded if p["said_before"]["favourite_advanced"]),
        },
        # The same tally in the words the page shows (the page never renders
        # the scorecard's keys).
        "grading": {
            "completed_series": len(completed),
            "recorded_and_finished": len(graded),
            "rated_higher_advanced": sum(
                1 for p in graded if p["said_before"]["rated_higher_advanced"]),
        },
        "factor_labels": {"announced_starters": MODEL_USED, "projected_starters": SCENARIO_INPUT,
                          "no_starter": UNAVAILABLE},
    }


# ---------------------------------------------------------------------------
# ledger rows (pure; the script owns the file)
# ---------------------------------------------------------------------------

def _component_used(game: Mapping, key: str) -> Optional[bool]:
    """Whether the named input is in this game's primary chance; None for a
    game that carries no inputs list (a payload from before it existed)."""
    for item in game.get("inputs") or []:
        if item.get("key") == key:
            return bool(item.get("used"))
    return None


def snapshot_rows(payload: Mapping, day: str) -> list:
    """One forecast row per live or upcoming series with both teams known.
    Empty when the page is unavailable."""
    if not payload.get("available"):
        return []
    rows = []
    for s in payload["series"]:
        if s["status"] not in ("live", "upcoming") or len(s["teams"]) != 2:
            continue
        chance = {t["team"]: t["chance"] for t in s["teams"]}
        if any(v is None for v in chance.values()):
            continue
        wins = {t["team"]: t["wins"] for t in s["teams"]}
        nxt = s.get("next_game")
        rows.append({
            "kind": "postseason_series_forecast",
            "model": payload["model"],
            "date": day,
            "season": payload["season"],
            "series_id": s["id"],
            "round": s["round_label"],
            "league": s["league"],
            "teams": [t["team"] for t in s["teams"]],
            "home_field": s["home_field"],
            "wins": wins,
            "games_played": sum(wins.values()),
            "series_chance": chance,
            "next_game": None if not nxt else {
                "number": nxt["number"], "date": nxt["date"], "home": nxt["home"],
                "away": nxt["away"], "home_chance": nxt["home_chance"],
                "starter_label": nxt["starter_label"],
                "starter_input_class": nxt.get("starter_input_class"),
                "starters_used": _component_used(nxt, "starters"),
                "bullpens_used": _component_used(nxt, "bullpens")},
            "inputs": {
                "as_of": payload["as_of"],
                "results_through": payload["results_through"],
                "standings_date": payload["standings_date"],
                "inputs_through": payload["inputs_through"],
                "starter_labels": [g["starter_label"] for g in s["games"]
                                   if g.get("status") in ("next", "future")],
                # What each recorded game estimate was made from, so a later
                # grader can tell a starter-based number from one made
                # without starters or bullpens.
                "games": [{"number": g["number"],
                           "starter_input_class": g.get("starter_input_class"),
                           "starters_used": _component_used(g, "starters"),
                           "bullpens_used": _component_used(g, "bullpens")}
                          for g in s["games"] if g.get("status") in ("next", "future")],
            },
        })
    return rows
