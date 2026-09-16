"""Resumable, rate-limited harvester for BALLDONTLIE's ALL-ACCESS trial.

WHY THIS EXISTS
----------------
The owner bought BALLDONTLIE ALL-ACCESS on a 48-hour free trial starting
~2026-09-15 05:30Z ("run that completely down ... you can use that for all
sports"). ALL-ACCESS raises the per-minute ceiling well above the ALL-STAR
tier src/providers/tennis_results.py was built for (their pricing page:
600 req/min), and unlocks match/game data for every sport the vendor has:
tennis (ATP/WTA), NFL, MLB, NBA, NHL. This script pulls everything the
PLAN below asks for, as compressed JSONL files plus a manifest, so the
trial's value survives long after the trial itself expires. Their terms
allow storing and archiving the data (per the owner's brief).

WHAT THE SPEC CONFIRMS VS. WHAT THIS SCRIPT ASSUMES
------------------------------------------------------
Endpoints, paths, params and response envelopes below are taken from the
published OpenAPI specs (fetched 2026-09-15):
  https://www.balldontlie.io/openapi/atp.yml
  https://www.balldontlie.io/openapi/wta.yml
  https://www.balldontlie.io/openapi/nfl.yml
  https://www.balldontlie.io/openapi/mlb.yml
  https://www.balldontlie.io/openapi/nba.yml
  https://www.balldontlie.io/openapi/nhl.yml
No endpoint below was guessed past what those specs list. Three things the
specs did NOT state, so this script makes an explicit, documented choice
instead of guessing an unlisted endpoint or parameter value:

1. MLB/NBA/NHL "all seasons the API supports" for games/standings/odds --
   the specs give no historical floor year. WIDE_SEASON_RANGE below starts
   at 2000; a season with no data simply comes back with zero rows (one
   cheap request, recorded in the manifest) rather than erroring, so this
   floor costs a little wasted quota rather than missing real history.
2. NBA `/nba/v1/season_averages/{type}` and `/nba/v1/team_season_averages/
   {category}` require a `type`/`category` path or query value whose valid
   enum this script's spec read did not return -- e.g. "base", "advanced",
   "clutch" are guesses, not confirmed values. Rather than guess and risk a
   silent 404 being recorded as "the endpoint doesn't exist", these two are
   left OUT of the plan. Same for NHL's per-team
   `/nhl/v1/teams/{id}/season_stats` and per-player
   `/nhl/v1/players/{id}/season_stats` -- both need an id enumerated from
   another endpoint first, which is a second harvesting phase this pass
   does not build. NHL's bulk `/nhl/v1/box_scores` (player game stats, no
   id enumeration needed) is harvested instead and covers the same
   "player stats" ask without the extra phase.
3. NFL has no separate *team* season-stats endpoint in its spec (only
   `/nfl/v1/season_stats`, which is PLAYER season stats, plus
   `/nfl/v1/standings` for team win/loss). "team season stats" for NFL is
   therefore not a real endpoint here; standings is what's harvested for
   team-level season data.
4. UPDATE 2026-09-15 (DEFECT 2): `.../odds` and `.../odds/opening` on
   MLB/NBA/NHL are NOT filterable by season -- their specs confirm only
   `dates`/`game_ids` (NBA's `/v2/odds` alone spells the former `dates[]`,
   via its own spec's shared `DatesParam` component; every other date filter
   in this file, `.../odds/opening` included, is unbracketed `dates` --
   confirmed by direct inspection of each spec, not assumed uniform). The
   original single unfiltered job per endpoint 400'd for all of them (see
   MANIFEST.json) exactly as the spec's "Either dates or game_ids is
   required" note for MLB/NBA/NHL implies. Odds are now swept one job per
   (season, date) instead -- see `_odds_sweep_jobs`, which prefers real game
   dates already sitting in that sport's harvested games file and falls
   back to a generated calendar window only when that file does not exist
   yet. Tennis's `.../odds/opening` DOES accept a plain `season` filter (its
   spec confirms it), so it sweeps by season instead of date. All four
   sports' `.../odds/opening` specs state coverage is "limited to the most
   recently completed season and ongoing seasons where available" --
   OPENING_ODDS_SEASON_RANGE (this season + last) is sized to that, not to
   WIDE_SEASON_RANGE. NFL's odds jobs (filtered by season+week, unaffected
   by this) were already correct and are unchanged.
5. UPDATE 2026-09-15 (DEFECT 1): NHL's `/nhl/v1/games` was suspected of using
   the wrong key for its season filter (MLB/NBA/NFL all spell theirs
   `seasons[]`). Its OpenAPI spec was re-read directly (raw YAML, not a
   paraphrase) and confirms the parameter really is named `seasons` (array,
   no brackets) -- exactly what this script already sent. The recorded
   http_status:400 for that job is therefore NOT explained by the parameter
   name/shape per the spec, and the key was deliberately left unchanged
   (see `_nhl_jobs`) rather than guessed against clear spec text. What DID
   change: a recorded 400 no longer permanently blocks a job from retrying
   (see `run_plan`'s `permanent` check) -- 400 is a request-shape problem,
   not an entitlement one like 401/403/404, so it should get another try
   rather than being skipped forever by manifest file-path alone.

RESUMABILITY
------------
Each job writes exactly one `data/historical/balldontlie/<sport>/<endpoint
out name>.jsonl.gz` and one manifest entry keyed by that relative path. A
job whose manifest entry has `"complete": true` is skipped outright, and one
that recorded an `"http_status"` (a 403/404/etc that will not resolve by
retrying) is skipped too. A job that stopped mid-page (deadline hit) leaves
a `<file>.cursor` sidecar; the next run reopens the `.jsonl.gz` in append
mode and resumes paging from that cursor. See `run_plan` for the loop and
`_run_paged_job` / `_run_single_job` / `_run_ranking_probe_job` for the
three job kinds.

CLI
---
    python scripts/balldontlie_harvest.py --dry-run
    python scripts/balldontlie_harvest.py --sports tennis,nfl --max-minutes 300
    python scripts/balldontlie_harvest.py --only atp_matches
    python scripts/balldontlie_harvest.py --probe --sports tennis,nfl,mlb,nba,nhl

429 HANDLING AND JOB PRIORITY (2026-09-15 incident)
-----------------------------------------------------
The first real run (35001607006) showed the account rate-limited far below
the ALL-ACCESS ceiling, and the old retry policy gave up inside a single
rate window -- see src/providers/balldontlie.py's "429 POLICY" docstring
for the client-side fix (wait out 429s, bounded by max_429_wait_seconds and
the run's own --max-minutes deadline; a job that gives up for either reason
is recorded "partial" with its cursor saved, not a terminal error). Because
a slow/rate-limited account may not finish the whole PLAN in one trial
window, build_plan() also orders jobs by value instead of sport-then-
alphabetical -- see the block comment above _TIER0_SEASON_FLOOR for the
exact phases. --probe makes one cheap request per sport (no harvesting) so
a run can be started with a fresh read of the account's current rate-limit
headers before committing the full window to it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.paths import repo_root  # noqa: E402
from src.providers.balldontlie import (  # noqa: E402
    BallDontLieDeadlineExceeded,
    BallDontLieError,
    BallDontLieHTTPError,
    BallDontLieRateLimitExhausted,
    Client,
    client_from_env,
)

DEFAULT_OUT_DIR = repo_root() / "data" / "historical" / "balldontlie"
MANIFEST_NAME = "MANIFEST.json"
ALL_SPORTS = ("tennis", "nfl", "mlb", "nba", "nhl")

# "today" for season-range purposes -- overridable so a run months from now
# still reaches forward instead of being stuck at whatever year this file
# was written in. Actual season ceilings are looked at again each run.
_CEILING_YEAR = datetime.now(timezone.utc).year

TENNIS_TOURS = ("atp", "wta")
TENNIS_SEASON_RANGE = range(2010, _CEILING_YEAR + 1)
NFL_SEASON_RANGE = range(2015, _CEILING_YEAR + 1)
NFL_WEEK_RANGE = range(1, 23)  # 18 regular-season weeks + up to 4 postseason
# See module docstring point 1: no stated historical floor for MLB/NBA/NHL.
WIDE_SEASON_RANGE = range(2000, _CEILING_YEAR + 1)
RECENT_SEASON_RANGE = range(_CEILING_YEAR - 4, _CEILING_YEAR + 1)  # "last five seasons"
# `.../odds/opening` on every sport that has it (MLB/NBA/NHL/ATP/WTA) carries
# the identical spec sentence: "Coverage is limited to the most recently
# completed season and ongoing seasons where available." (confirmed on all
# five specs, 2026-09-15) -- sweeping seasons further back than that would
# just be zero-row requests. Two seasons (this one + last) covers "ongoing"
# and "most recently completed" under either interpretation of where in the
# season boundary "today" falls.
OPENING_ODDS_SEASON_RANGE = range(_CEILING_YEAR - 1, _CEILING_YEAR + 1)


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

@dataclass
class JobResult:
    status: str  # "complete" | "partial" | "error"
    rows_written: int = 0
    http_status: Optional[int] = None
    # Only meaningful when status == "partial": "rate_limited" (the job gave
    # up on a single request's 429 wait, i.e. BallDontLieRateLimitExhausted --
    # the ACCOUNT is still rate-limited, not the RUN out of time) or
    # "deadline" (BallDontLieDeadlineExceeded, or run_plan's own pre-job
    # clock check -- the run's --max-minutes budget is what ran out). See
    # run_plan: only "deadline" ends the whole run; "rate_limited" moves on
    # to the next job while run time remains (root cause B, 2026-09-15).
    reason: Optional[str] = None


@dataclass
class RunContext:
    client: Optional[Client]
    out_dir: Path
    manifest: dict
    deadline: Optional[float] = None  # time.monotonic() cutoff, or None
    today: Optional[date] = None      # injectable "today" for the rankings probe
    clock: Callable[[], float] = time.monotonic


@dataclass
class Job:
    sport: str
    endpoint: str        # logical endpoint id -- shared across a season sweep,
                          # what --only matches against
    path: str             # API path, e.g. "/atp/v1/matches"
    description: str
    out_name: str          # output filename stem (no extension)
    est_requests: int       # a HEURISTIC guess, for --dry-run only -- never measured
    run: Callable[[RunContext, "Job"], JobResult]
    params: dict = field(default_factory=dict)
    # Priority-sort-only season, decoupled from `params` (the actual wire
    # request). The odds sweep jobs below (see _dates_for_odds_sweep) filter
    # by date/game_ids, not season -- the vendor spec does not accept a
    # `season` filter on those endpoints, and inventing one would violate
    # this module's "never send an unconfirmed parameter" rule. This field
    # lets _job_season/_job_priority still place a per-date odds job in the
    # right newest-season-first slot without smuggling an extra key onto the
    # wire. None (the default) means "read the season out of params instead"
    # -- unchanged behaviour for every job that predates this field.
    priority_season: Optional[int] = None


def _paged_job(sport, endpoint, path, params, out_name, description, est_requests,
                priority_season=None) -> Job:
    return Job(sport=sport, endpoint=endpoint, path=path, description=description,
               out_name=out_name, est_requests=est_requests, run=_run_paged_job,
               params=dict(params), priority_season=priority_season)


def _single_job(sport, endpoint, path, params, out_name, description, est_requests) -> Job:
    return Job(sport=sport, endpoint=endpoint, path=path, description=description,
               out_name=out_name, est_requests=est_requests, run=_run_single_job,
               params=dict(params))


def _ranking_probe_job(sport, endpoint, tour, out_name, description, est_requests) -> Job:
    return Job(sport=sport, endpoint=endpoint, path=f"/{tour}/v1/rankings",
               description=description, out_name=out_name, est_requests=est_requests,
               run=_run_ranking_probe_job, params={"tour": tour})


# ---------------------------------------------------------------------------
# Odds sweep support (DEFECT 2, 2026-09-15): MLB/NBA/NHL `.../odds` and
# `.../odds/opening` do not accept a `season` filter -- every spec confirms
# only `dates`/`game_ids` (see the per-endpoint key map below). An unfiltered
# call 400s (see the module docstring's former point 4). Rebuilding those as
# one job per date needs to know WHICH dates actually have games; the
# cheapest source of that is the games file this same plan already harvests
# for that sport+season (data/historical/balldontlie/<sport>/<sport>_games_
# <season>.jsonl.gz) -- read real dates from it when it exists, and only
# fall back to a generated calendar range when it does not (a fresh
# checkout, or this season's games job hasn't run yet in THIS plan build --
# build_plan() runs once, up front, so a games job completing later in the
# SAME run cannot feed this pass; the next run's plan rebuild will see it).
# ---------------------------------------------------------------------------

# Field name the vendor uses for a game's calendar date, per sport -- MLB and
# NBA schemas both call it `date`; NHL's schema calls it `game_date` (all
# three confirmed against MLBGame/NBAGame/NHLGame in their OpenAPI specs,
# 2026-09-15). Checked in this order so either key is tolerated.
_GAME_DATE_FIELDS = ("date", "game_date")

# Generous, well-known regular-season-plus-playoffs windows, used ONLY when
# no local games file exists yet to read real dates from (see
# _dates_for_odds_sweep). Deliberately not spec-derived (the specs give no
# season calendar) -- this is common public knowledge about when each league
# plays, not an API behavior guess, and it is only ever a stand-in until the
# real games file supersedes it on a later plan rebuild. Expressed as
# (start_month, start_day, start_year_offset, end_month, end_day,
# end_year_offset) relative to the `season` integer -- NBA/NHL seasons span
# a calendar-year boundary (e.g. season 2024 runs Oct 2024 -> Jun 2025),
# MLB's does not.
_FALLBACK_SEASON_WINDOW = {
    "mlb": (3, 1, 0, 11, 30, 0),
    "nba": (10, 1, 0, 6, 30, 1),
    "nhl": (10, 1, 0, 6, 30, 1),
}

# Literal query key each sport's odds endpoints use for a date filter --
# confirmed against each sport's OpenAPI spec (2026-09-15), NOT assumed
# uniform: MLB/NHL and NBA's own `.../odds/opening` all spell it inline as
# `dates` (no brackets), but NBA's `.../odds` pulls in the shared
# `#/components/parameters/DatesParam`, which nba.yml itself defines as
# `dates[]` (with brackets) -- a genuine inconsistency within the NBA spec
# itself, not a typo introduced here. `game_ids` is unbracketed everywhere
# it appears, so no map is needed for it.
_ODDS_DATE_PARAM_KEY = {
    ("mlb", "odds"): "dates", ("mlb", "odds_opening"): "dates",
    ("nba", "odds"): "dates[]", ("nba", "odds_opening"): "dates",
    ("nhl", "odds"): "dates", ("nhl", "odds_opening"): "dates",
}


def _game_dates_from_file(out_dir: Path, sport: str, season: int) -> list:
    """Distinct, sorted `YYYY-MM-DD` dates found in the local
    `<sport>_games_<season>.jsonl.gz` file this plan already harvests, or []
    if that file does not exist (yet, or at all) on this checkout."""
    path = _out_path(out_dir, sport, f"{sport}_games_{season}")
    if not path.exists():
        return []
    dates = set()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                for field_name in _GAME_DATE_FIELDS:
                    value = row.get(field_name)
                    if value:
                        dates.add(str(value)[:10])  # tolerate a date-time value
                        break
    except OSError:
        return []
    return sorted(dates)


def _fallback_date_range(sport: str, season: int) -> list:
    """Generated `YYYY-MM-DD` dates spanning this sport's well-known season
    window (see _FALLBACK_SEASON_WINDOW) -- used only when no games file
    exists yet for (sport, season)."""
    sm, sd, so, em, ed, eo = _FALLBACK_SEASON_WINDOW[sport]
    start = date(season + so, sm, sd)
    end = date(season + eo, em, ed)
    out = []
    d = start
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _dates_for_odds_sweep(out_dir: Path, sport: str, season: int) -> list:
    """Dates to sweep an odds/odds-opening job over for (sport, season):
    real game dates when the games file is already on disk, else the
    generated fallback window."""
    dates = _game_dates_from_file(out_dir, sport, season)
    return dates if dates else _fallback_date_range(sport, season)


def _odds_sweep_jobs(sport: str, endpoint: str, path: str, out_dir: Path,
                      seasons, description_label: str, est_requests: int) -> list:
    """One paged job per (season, date) for a sport/endpoint whose spec
    confirms only a date/game_ids filter -- see the module-level comment
    above _GAME_DATE_FIELDS for why dates (not game_ids) were chosen, and
    _ODDS_DATE_PARAM_KEY for the exact per-sport/endpoint query key."""
    date_key = _ODDS_DATE_PARAM_KEY[(sport, endpoint)]
    jobs = []
    for season in seasons:
        for d in _dates_for_odds_sweep(out_dir, sport, season):
            jobs.append(_paged_job(
                sport, endpoint, path, {date_key: [d]},
                f"{sport}_{endpoint}_{season}_{d}",
                f"{description_label}, {d} (season {season})", est_requests,
                priority_season=season))
    return jobs


# ---------------------------------------------------------------------------
# PLAN builders -- pure (no network; local disk reads only, to read back
# already-harvested game dates for the odds sweep below), so --dry-run costs
# nothing but a few file existence checks.
# ---------------------------------------------------------------------------

def _tennis_jobs(out_dir: Path) -> list:
    jobs = []
    for tour in TENNIS_TOURS:
        up = tour.upper()
        for season in TENNIS_SEASON_RANGE:
            jobs.append(_paged_job(
                "tennis", f"{tour}_matches", f"/{tour}/v1/matches", {"season": season},
                f"{tour}_matches_{season}", f"{up} matches, season {season}", 5))
        for season in TENNIS_SEASON_RANGE:
            jobs.append(_paged_job(
                "tennis", f"{tour}_tournaments", f"/{tour}/v1/tournaments", {"season": season},
                f"{tour}_tournaments_{season}", f"{up} tournaments, season {season}", 1))
        jobs.append(_paged_job(
            "tennis", f"{tour}_players", f"/{tour}/v1/players", {},
            f"{tour}_players", f"{up} players (all)", 10))
        jobs.append(_ranking_probe_job(
            "tennis", f"{tour}_rankings", tour, f"{tour}_rankings",
            f"{up} rankings, every Monday from the earliest date with data to today", 800))
        # DEFECT 2: /{tour}/v1/odds/opening's own spec says "Coverage is
        # limited to the most recently completed season and ongoing seasons
        # where available" -- an unfiltered call 400s (see MANIFEST.json),
        # and there is no need to sweep further back than that stated
        # coverage window. `season` is a confirmed, valid filter on this
        # endpoint (same spec), so a per-season sweep -- not a date/match_id
        # one -- is both spec-correct and the cheapest sufficient form.
        for season in OPENING_ODDS_SEASON_RANGE:
            jobs.append(_paged_job(
                "tennis", f"{tour}_odds_opening", f"/{tour}/v1/odds/opening",
                {"season": season}, f"{tour}_odds_opening_{season}",
                f"{up} opening odds, season {season} (GOAT tier)", 5,
                priority_season=season))
        jobs.append(_paged_job(
            "tennis", f"{tour}_match_stats", f"/{tour}/v1/match_stats", {},
            f"{tour}_match_stats", f"{up} match stats (all, GOAT tier)", 50))
    return jobs


def _nfl_jobs(out_dir: Path) -> list:  # out_dir unused -- NFL odds already filters by season+week
    jobs = []
    for season in NFL_SEASON_RANGE:
        jobs.append(_paged_job(
            "nfl", "games", "/nfl/v1/games", {"seasons[]": [season]},
            f"nfl_games_{season}", f"NFL games, season {season}", 4))
    for season in NFL_SEASON_RANGE:
        jobs.append(_paged_job(
            "nfl", "season_stats", "/nfl/v1/season_stats", {"season": season},
            f"nfl_season_stats_{season}", f"NFL player season stats, season {season}", 10))
    for season in NFL_SEASON_RANGE:
        jobs.append(_paged_job(
            "nfl", "stats", "/nfl/v1/stats", {"seasons[]": [season]},
            f"nfl_stats_{season}", f"NFL player game stats, season {season}", 40))
    jobs.append(_paged_job(
        "nfl", "player_injuries", "/nfl/v1/player_injuries", {},
        "nfl_player_injuries", "NFL injuries (current snapshot)", 3))
    for season in NFL_SEASON_RANGE:
        jobs.append(_single_job(
            "nfl", "standings", "/nfl/v1/standings", {"season": season},
            f"nfl_standings_{season}", f"NFL standings, season {season}", 1))
    for season in NFL_SEASON_RANGE:
        for week in NFL_WEEK_RANGE:
            jobs.append(_paged_job(
                "nfl", "odds", "/nfl/v1/odds", {"season": season, "week": week},
                f"nfl_odds_{season}_wk{week:02d}",
                f"NFL odds, season {season} week {week}", 1))
            jobs.append(_paged_job(
                "nfl", "odds_opening", "/nfl/v1/odds/opening", {"season": season, "week": week},
                f"nfl_odds_opening_{season}_wk{week:02d}",
                f"NFL opening odds, season {season} week {week} (GOAT tier)", 1))
    return jobs


def _mlb_jobs(out_dir: Path) -> list:
    jobs = []
    for season in WIDE_SEASON_RANGE:
        jobs.append(_paged_job(
            "mlb", "games", "/mlb/v1/games", {"seasons[]": [season]},
            f"mlb_games_{season}", f"MLB games, season {season}", 15))
    for season in WIDE_SEASON_RANGE:
        jobs.append(_single_job(
            "mlb", "standings", "/mlb/v1/standings", {"season": season},
            f"mlb_standings_{season}", f"MLB standings, season {season}", 1))
    # DEFECT 2: /mlb/v1/odds and /odds/opening both confirm "Either dates or
    # game_ids is required" -- the old unfiltered `mlb_odds`/`mlb_odds_opening`
    # jobs always 400'd (see MANIFEST.json) and are superseded by these
    # per-date sweeps; the plan no longer emits the unfiltered form at all.
    jobs.extend(_odds_sweep_jobs(
        "mlb", "odds", "/mlb/v1/odds", out_dir, RECENT_SEASON_RANGE,
        "MLB odds", 2))
    jobs.extend(_odds_sweep_jobs(
        "mlb", "odds_opening", "/mlb/v1/odds/opening", out_dir,
        OPENING_ODDS_SEASON_RANGE, "MLB opening odds (GOAT tier)", 2))
    for season in RECENT_SEASON_RANGE:
        jobs.append(_single_job(
            "mlb", "team_season_stats", "/mlb/v1/teams/season_stats", {"season": season},
            f"mlb_team_season_stats_{season}", f"MLB team season stats, season {season}", 1))
        jobs.append(_paged_job(
            "mlb", "season_stats", "/mlb/v1/season_stats", {"season": season},
            f"mlb_season_stats_{season}", f"MLB player season stats, season {season}", 10))
        jobs.append(_paged_job(
            "mlb", "stats", "/mlb/v1/stats", {"seasons[]": [season]},
            f"mlb_stats_{season}", f"MLB player game stats, season {season}", 80))
    jobs.append(_paged_job(
        "mlb", "player_injuries", "/mlb/v1/player_injuries", {},
        "mlb_player_injuries", "MLB injuries (current snapshot)", 3))
    return jobs


def _nba_jobs(out_dir: Path) -> list:
    jobs = []
    for season in WIDE_SEASON_RANGE:
        jobs.append(_paged_job(
            "nba", "games", "/nba/v1/games", {"seasons[]": [season]},
            f"nba_games_{season}", f"NBA games, season {season}", 15))
    for season in WIDE_SEASON_RANGE:
        jobs.append(_single_job(
            "nba", "standings", "/nba/v1/standings", {"season": season},
            f"nba_standings_{season}", f"NBA standings, season {season}", 1))
    # DEFECT 2: /nba/v2/odds and /odds/opening both confirm "Either dates or
    # game_ids is required" -- the old unfiltered `nba_odds`/`nba_odds_opening`
    # jobs always 400'd (see MANIFEST.json) and are superseded by these
    # per-date sweeps. NOTE the date filter's literal query key differs
    # between the two NBA endpoints themselves (see _ODDS_DATE_PARAM_KEY).
    jobs.extend(_odds_sweep_jobs(
        "nba", "odds", "/nba/v2/odds", out_dir, RECENT_SEASON_RANGE,
        "NBA odds", 2))
    jobs.extend(_odds_sweep_jobs(
        "nba", "odds_opening", "/nba/v2/odds/opening", out_dir,
        OPENING_ODDS_SEASON_RANGE, "NBA opening odds (GOAT tier)", 2))
    for season in RECENT_SEASON_RANGE:
        jobs.append(_paged_job(
            "nba", "stats", "/nba/v1/stats", {"seasons[]": [season]},
            f"nba_stats_{season}", f"NBA player game stats, season {season}", 80))
    jobs.append(_paged_job(
        "nba", "player_injuries", "/nba/v1/player_injuries", {},
        "nba_player_injuries", "NBA injuries (current snapshot)", 3))
    return jobs


def _nhl_jobs(out_dir: Path) -> list:
    jobs = []
    # DEFECT 1: /nhl/v1/games' own OpenAPI spec names this parameter
    # `seasons` (array of integer, no brackets) -- confirmed 2026-09-15 by
    # reading the raw nhl.yml text directly (not a paraphrase), and it is
    # what this line already sends. This does NOT match the hypothesis that
    # NHL needed MLB/NBA/NFL's bracketed `seasons[]` spelling: those three
    # sports' specs explicitly write the name WITH brackets; NHL's spec
    # explicitly writes it WITHOUT them (as does NHL's own `dates` param on
    # this same endpoint, and MLB's `dates` on /mlb/v1/odds -- this vendor is
    # simply inconsistent about brackets from one sport/endpoint to the
    # next, confirmed by direct inspection, not assumed uniform). The
    # http_status:400 recorded in MANIFEST.json for this job is therefore
    # NOT explained by the parameter name/shape per the spec, and this code
    # was left unchanged rather than guess a different key against clear
    # spec text -- see run_plan's `permanent` check below, which no longer
    # treats a recorded 400 as un-retriable, so a corrected or since-fixed
    # request gets a real next attempt instead of being skipped forever.
    for season in WIDE_SEASON_RANGE:
        jobs.append(_paged_job(
            "nhl", "games", "/nhl/v1/games", {"seasons": [season]},
            f"nhl_games_{season}", f"NHL games, season {season}", 15))
    for season in WIDE_SEASON_RANGE:
        jobs.append(_single_job(
            "nhl", "standings", "/nhl/v1/standings", {"season": season},
            f"nhl_standings_{season}", f"NHL standings, season {season}", 1))
    # DEFECT 2: /nhl/v1/odds and /odds/opening both confirm "Either dates or
    # game_ids is required" -- the old unfiltered `nhl_odds`/`nhl_odds_opening`
    # jobs always 400'd (see MANIFEST.json) and are superseded by these
    # per-date sweeps.
    jobs.extend(_odds_sweep_jobs(
        "nhl", "odds", "/nhl/v1/odds", out_dir, RECENT_SEASON_RANGE,
        "NHL odds", 2))
    jobs.extend(_odds_sweep_jobs(
        "nhl", "odds_opening", "/nhl/v1/odds/opening", out_dir,
        OPENING_ODDS_SEASON_RANGE, "NHL opening odds (GOAT tier)", 2))
    for season in RECENT_SEASON_RANGE:
        jobs.append(_paged_job(
            "nhl", "box_scores", "/nhl/v1/box_scores", {"season": season},
            f"nhl_box_scores_{season}", f"NHL box scores (player game stats), season {season}", 80))
    jobs.append(_single_job(
        "nhl", "player_injuries", "/nhl/v1/player_injuries", {},
        "nhl_player_injuries", "NHL injuries (current snapshot, vendor takes no params)", 1))
    return jobs


_SPORT_BUILDERS = {
    "tennis": _tennis_jobs,
    "nfl": _nfl_jobs,
    "mlb": _mlb_jobs,
    "nba": _nba_jobs,
    "nhl": _nhl_jobs,
}


# ---------------------------------------------------------------------------
# Plan priority (2026-09-15 429 incident, see src/providers/balldontlie.py's
# "429 POLICY" docstring): a slow/rate-limited account may not finish the
# whole PLAN, so job ORDER decides what survives if the run stops early.
# Three global phases, cutting across sports (not sport-then-alphabetical):
#
#   phase 0 -- newest-season matches/games/odds for the highest-value
#              window per sport, sport-major within the phase: tennis (ATP
#              then WTA) matches 2026->2019, then NFL games+odds
#              2026->2019, then MLB/NBA/NHL games+odds 2026->2022.
#   phase 1 -- endpoint kinds with no season priority, in this order, across
#              ALL selected sports: players, tournaments, rankings,
#              standings, injuries, stats.
#   phase 2 -- "older seasons": the same matches/games/odds kinds as phase 0,
#              for seasons below that phase's floor.
#
# This only reorders the jobs _tennis_jobs/etc. already build; out_name
# (and therefore the manifest file key and .cursor sidecar path) is
# untouched, so existing manifest entries keep resuming across a reorder.
# ---------------------------------------------------------------------------

_TIER0_SEASON_FLOOR = {"tennis": 2019, "nfl": 2019, "mlb": 2022, "nba": 2022, "nhl": 2022}
_TIER0_ENDPOINT_KINDS = {
    "tennis": {"atp_matches", "wta_matches"},
    "nfl": {"games", "odds", "odds_opening"},
    "mlb": {"games", "odds", "odds_opening"},
    "nba": {"games", "odds", "odds_opening"},
    "nhl": {"games", "odds", "odds_opening"},
}
# Endpoint-kind order within phase 1 -- "players, tournaments, rankings,
# standings, injuries, stats" from the FIX brief. Lower sorts first.
_TIER1_ENDPOINT_RANK = {
    "atp_players": 0, "wta_players": 0,
    "atp_tournaments": 1, "wta_tournaments": 1,
    "atp_rankings": 2, "wta_rankings": 2,
    "standings": 3,
    "player_injuries": 4,
    "atp_match_stats": 5, "wta_match_stats": 5,
    "stats": 5, "season_stats": 5, "team_season_stats": 5, "box_scores": 5,
}
_SPORT_VALUE_ORDER = {sport: i for i, sport in enumerate(ALL_SPORTS)}


def _job_season(job: "Job") -> Optional[int]:
    """The season a job's params carry, under whichever of the three key
    spellings this plan uses (season / seasons[] / seasons), or None for a
    job with no season param at all. Checked first: `job.priority_season`,
    for jobs (the per-date odds sweep) whose actual wire params carry a
    date/game_ids filter instead of a season -- see the Job field's
    docstring."""
    if job.priority_season is not None:
        return job.priority_season
    params = job.params
    if "season" in params:
        return params["season"]
    for key in ("seasons[]", "seasons"):
        value = params.get(key)
        if value:
            return value[0]
    return None


def _job_priority(job: "Job") -> tuple:
    """Sort key implementing the 3-phase priority described above. Lower
    tuples sort first; see the block comment for what each phase means."""
    sport_rank = _SPORT_VALUE_ORDER.get(job.sport, 99)
    season = _job_season(job)
    tier0_kinds = _TIER0_ENDPOINT_KINDS.get(job.sport, ())
    # "matches"/"games" rank ahead of "odds"/"odds_opening" for the same
    # sport+season.
    kind_rank = 1 if "odds" in job.endpoint else 0

    if job.endpoint in tier0_kinds:
        floor = _TIER0_SEASON_FLOOR.get(job.sport, 0)
        # The unfiltered MLB/NBA/NHL odds jobs carry no season param at all
        # -- treat them as "now" (newest) rather than falling out of phase 0.
        effective_season = season if season is not None else 9999
        # Season dominates kind: "2026 back to 2019" means every 2026 job
        # (games AND odds) before any 2025 job, not all games before any odds.
        if effective_season >= floor:
            return (0, sport_rank, -effective_season, kind_rank, job.endpoint, job.out_name)
        return (2, sport_rank, -effective_season, kind_rank, job.endpoint, job.out_name)

    rank = _TIER1_ENDPOINT_RANK.get(job.endpoint, 9)
    return (1, rank, sport_rank, job.endpoint, -(season or 0), job.out_name)


def build_plan(sports=ALL_SPORTS, only: Optional[str] = None,
                out_dir: Path = DEFAULT_OUT_DIR) -> list:
    """Build the priority-ordered job list. No network, safe for --dry-run --
    the odds sweep builders (see _odds_sweep_jobs) do read `out_dir` for
    already-harvested game dates, but that is a handful of local file-
    existence checks, never a request. See the block comment above
    _TIER0_SEASON_FLOOR for the ordering rules; --sports/--only filtering is
    unaffected by it."""
    jobs = []
    for sport in ALL_SPORTS:  # gather in a fixed order; _job_priority resorts
        if sport in sports:
            jobs.extend(_SPORT_BUILDERS[sport](out_dir))
    jobs.sort(key=_job_priority)
    if only:
        jobs = [j for j in jobs if j.endpoint == only]
    return jobs


# ---------------------------------------------------------------------------
# File / manifest helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _out_path(out_dir: Path, sport: str, out_name: str) -> Path:
    return out_dir / sport / f"{out_name}.jsonl.gz"


def _sidecar_path(out_path: Path) -> Path:
    return Path(str(out_path) + ".cursor")


def _manifest_path(out_dir: Path) -> Path:
    return out_dir / MANIFEST_NAME


def load_manifest(out_dir: Path) -> dict:
    path = _manifest_path(out_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_manifest(out_dir: Path, manifest: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _manifest_path(out_dir)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def _finalize_file(path: Path) -> tuple:
    """(sha256_hex, size_bytes, row_count) for a finished .jsonl.gz file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as raw:
        for chunk in iter(lambda: raw.read(1 << 20), b""):
            sha256.update(chunk)
    rows = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows += 1
    return sha256.hexdigest(), path.stat().st_size, rows


def _write_rows(gz, rows, harvested_utc: str) -> int:
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        line = json.dumps({**row, "_harvested_utc": harvested_utc}, sort_keys=True)
        gz.write((line + "\n").encode("utf-8"))
        count += 1
    return count


def _flush_to_disk(gz) -> None:
    """Flush the gzip stream's buffered output and fsync the underlying file
    BEFORE a cursor/state sidecar is persisted (root cause D): otherwise a
    hard kill can leave a sidecar claiming progress whose rows were never
    actually written to the .jsonl.gz, silently dropping them on resume.
    fsync is best-effort -- flush() already gets the bytes to the OS, and
    some sandboxed filesystems reject fsync outright."""
    gz.flush()
    try:
        os.fsync(gz.fileno())
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def _run_paged_job(ctx: RunContext, job: Job) -> JobResult:
    out_path = _out_path(ctx.out_dir, job.sport, job.out_name)
    cursor_path = _sidecar_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    resuming = cursor_path.exists() and out_path.exists()
    if cursor_path.exists() and not out_path.exists():
        # Inconsistent leftover state (e.g. the .jsonl.gz was removed by
        # hand) -- never trust a cursor with no matching data, start clean.
        try:
            cursor_path.unlink()
        except OSError:
            pass

    start_cursor = None
    if resuming:
        try:
            saved = json.loads(cursor_path.read_text(encoding="utf-8"))
            start_cursor = saved.get("cursor")
        except (json.JSONDecodeError, OSError):
            resuming = False

    mode = "ab" if resuming else "wb"
    rows_written = 0
    harvested_utc = _utc_now_iso()
    try:
        with gzip.open(out_path, mode) as gz:
            for payload in ctx.client.pages(job.path, job.params, start_cursor=start_cursor,
                                             deadline=ctx.deadline):
                data = payload.get("data")
                rows = data if isinstance(data, list) else ([data] if data else [])
                rows_written += _write_rows(gz, rows, harvested_utc)

                meta = payload.get("meta") or {}
                next_cursor = meta.get("next_cursor")
                if next_cursor is None:
                    # This was the last page -- NOT a resumable stopping
                    # point (root cause D): a stale cursor from an earlier
                    # page left on disk here would duplicate this final page
                    # on the next run. Drop it and let the pager's own
                    # generator termination end the loop below.
                    if cursor_path.exists():
                        cursor_path.unlink()
                    continue

                _flush_to_disk(gz)  # rows must be on disk before the cursor claims them
                cursor_path.write_text(json.dumps({"cursor": next_cursor}), encoding="utf-8")

                if ctx.deadline is not None and ctx.clock() >= ctx.deadline:
                    return JobResult(status="partial", rows_written=rows_written)
    except BallDontLieRateLimitExhausted:
        # Still rate-limited, not permanently disallowed -- the cursor
        # sidecar from the last successful page (if any) is already on disk,
        # so this resumes on the next run instead of erroring out. Tagged
        # "rate_limited" (not "deadline") so run_plan moves on to the next
        # job instead of ending the whole run (root cause B).
        return JobResult(status="partial", rows_written=rows_written, reason="rate_limited")
    except BallDontLieDeadlineExceeded:
        return JobResult(status="partial", rows_written=rows_written, reason="deadline")
    except BallDontLieHTTPError as exc:
        return JobResult(status="error", http_status=exc.status, rows_written=rows_written)

    if cursor_path.exists():
        cursor_path.unlink()
    return JobResult(status="complete", rows_written=rows_written)


def _run_single_job(ctx: RunContext, job: Job) -> JobResult:
    out_path = _out_path(ctx.out_dir, job.sport, job.out_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    harvested_utc = _utc_now_iso()
    try:
        payload = ctx.client.get(job.path, job.params, deadline=ctx.deadline)
    except BallDontLieRateLimitExhausted:
        return JobResult(status="partial", rows_written=0, reason="rate_limited")
    except BallDontLieDeadlineExceeded:
        return JobResult(status="partial", rows_written=0, reason="deadline")
    except BallDontLieHTTPError as exc:
        return JobResult(status="error", http_status=exc.status)

    data = payload.get("data")
    rows = data if isinstance(data, list) else ([data] if data else [])
    with gzip.open(out_path, "wb") as gz:
        rows_written = _write_rows(gz, rows, harvested_utc)
    return JobResult(status="complete", rows_written=rows_written)


def _most_recent_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


_RANKING_PROBE_STEP_DAYS = 28
_RANKING_PROBE_FLOOR = date(2000, 1, 3)
_RANKING_PROBE_ITERATION_CAP = 5000  # safety net against a corrupted sidecar


def _run_ranking_probe_job(ctx: RunContext, job: Job) -> JobResult:
    """Rankings: probe backward in 4-week steps to find the earliest Monday
    with data, then fetch every Monday from there to today.

    Progress (which phase, and where in it) is a small JSON object in the
    `.cursor` sidecar, not a raw vendor cursor -- see the module docstring's
    "RESUMABILITY" section. Every step of both phases persists state before
    the next network call, so a deadline hit or a crash loses at most one
    step of work.
    """
    tour = job.params["tour"]
    path = job.path
    out_path = _out_path(ctx.out_dir, job.sport, job.out_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    state_path = _sidecar_path(out_path)

    if state_path.exists() and not out_path.exists():
        # Orphan state (root cause E): exactly the chained-run case, since
        # data/historical/* is not committed -- a state sidecar can survive
        # while the .jsonl.gz it describes does not. Without this guard the
        # job would resume mid-fill onto a FRESH file and later mark
        # complete=True over silently truncated data, mirroring
        # _run_paged_job's identical guard above.
        try:
            state_path.unlink()
        except OSError:
            pass

    today = ctx.today or datetime.now(timezone.utc).date()
    this_monday = _most_recent_monday(today)

    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = None
    if state is None:
        state = {"phase": "probe", "probe_date": this_monday.isoformat(),
                  "known_good": None}

    harvested_utc = _utc_now_iso()
    rows_written = 0
    mode = "ab" if out_path.exists() else "wb"
    gz = gzip.open(out_path, mode)
    try:
        for _ in range(_RANKING_PROBE_ITERATION_CAP):
            if ctx.deadline is not None and ctx.clock() >= ctx.deadline:
                state_path.write_text(json.dumps(state), encoding="utf-8")
                return JobResult(status="partial", rows_written=rows_written)

            if state["phase"] == "probe":
                probe_date = date.fromisoformat(state["probe_date"])
                payload = ctx.client.get(path, {"date": probe_date.isoformat(), "per_page": 1},
                                          deadline=ctx.deadline)
                found = bool(payload.get("data"))
                if found:
                    state["known_good"] = probe_date.isoformat()
                    next_probe = probe_date - timedelta(days=_RANKING_PROBE_STEP_DAYS)
                    if next_probe < _RANKING_PROBE_FLOOR:
                        state = {"phase": "fill", "next_date": _RANKING_PROBE_FLOOR.isoformat(),
                                 "until": this_monday.isoformat()}
                    else:
                        state["probe_date"] = next_probe.isoformat()
                elif state.get("known_good") is not None:
                    # The boundary is somewhere inside the last 4-week probe
                    # step. Start the weekly fill AT the failed probe date
                    # (not at known_good, which is much closer to today) so
                    # every week in that gap -- including ones the 4-week
                    # jump skipped over -- gets a real fetch. A week here
                    # that turns out to have no data just writes zero rows.
                    state = {"phase": "fill", "next_date": probe_date.isoformat(),
                             "until": this_monday.isoformat()}
                else:
                    # No known_good yet (root cause E): an empty probe here
                    # -- including the very FIRST one, at today -- does not
                    # mean there is no data anywhere. It can just mean this
                    # week's rankings have not posted yet. Keep stepping
                    # backward instead of collapsing to a single-week fill
                    # and silently losing all ranking history; only give up
                    # once the floor is reached with nothing found.
                    next_probe = probe_date - timedelta(days=_RANKING_PROBE_STEP_DAYS)
                    if next_probe < _RANKING_PROBE_FLOOR:
                        state = {"phase": "done_empty"}
                    else:
                        state["probe_date"] = next_probe.isoformat()
                state_path.write_text(json.dumps(state), encoding="utf-8")
                continue

            if state["phase"] == "done_empty":
                # Probed all the way back to the floor and never found a
                # single Monday with data -- genuinely nothing to fill, not
                # a bug. rows_written stays 0; run_plan flags a 0-row
                # "complete" manifest entry as zero_rows so this reads as
                # "confirmed empty", not silently indistinguishable from a
                # normal successful pull (root cause E).
                break

            # phase == "fill": walk forward weekly, fetching every Monday.
            next_date = date.fromisoformat(state["next_date"])
            until = date.fromisoformat(state["until"])
            if next_date > until:
                break
            for fill_payload in ctx.client.pages(path, {"date": next_date.isoformat()},
                                                  deadline=ctx.deadline):
                rows = fill_payload.get("data") or []
                rows_written += _write_rows(gz, rows, harvested_utc)
            state["next_date"] = (next_date + timedelta(days=7)).isoformat()
            _flush_to_disk(gz)  # rows must be on disk before the state claims them (root cause D)
            state_path.write_text(json.dumps(state), encoding="utf-8")
        else:
            raise BallDontLieError(
                "rankings probe exceeded its iteration safety cap -- corrupted .cursor state?")
    except BallDontLieRateLimitExhausted:
        # `state` already reflects the last persisted step (see the
        # state_path.write_text calls above) -- nothing further to save.
        return JobResult(status="partial", rows_written=rows_written, reason="rate_limited")
    except BallDontLieDeadlineExceeded:
        return JobResult(status="partial", rows_written=rows_written, reason="deadline")
    except BallDontLieHTTPError as exc:
        return JobResult(status="error", http_status=exc.status, rows_written=rows_written)
    finally:
        gz.close()

    if state_path.exists():
        state_path.unlink()
    return JobResult(status="complete", rows_written=rows_written)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _rel_file(out_dir: Path, job: Job) -> str:
    return _out_path(out_dir, job.sport, job.out_name).relative_to(out_dir).as_posix()


# How many CONSECUTIVE rate-limited partials end the run early instead of
# moving on to the next job (root cause B guard). Each one has already
# waited up to max_429_wait_seconds (900s default) before giving up, so 3 in
# a row is ~45 minutes of real evidence the account is hard-blocked right
# now -- long enough not to bail on a single transient blip, short enough
# that it doesn't burn a meaningful slice of a 330-minute run sleeping
# through a block that isn't going to lift.
_RATE_LIMIT_HARD_BLOCK_THRESHOLD = 3


def run_plan(jobs: list, ctx: RunContext) -> dict:
    """Run jobs in order, skipping completed/permanently-errored ones.

    Never raises out of the loop: every provider error (HTTP or otherwise)
    is caught here as a final backstop even though the job functions already
    handle the HTTP case themselves, so a job kind that forgets to catch
    something still cannot take the whole harvest down.

    A "partial" result ends the run only when it means the run's own
    deadline is out (JobResult.reason == "deadline", or this loop's own
    pre-job clock check). A "rate_limited" partial means the ACCOUNT gave up
    waiting out one request's 429s, not that run time is gone -- the loop
    moves on to the next job, tracking consecutive rate-limited partials so
    a genuinely hard-blocked account still stops instead of sleeping
    max_429_wait_seconds per job for the rest of the run (root cause B, see
    _RATE_LIMIT_HARD_BLOCK_THRESHOLD).
    """
    completed = skipped = errored = partial = 0
    partial_rate_limited = partial_deadline = 0
    consecutive_rate_limited = 0
    for job in jobs:
        rel = _rel_file(ctx.out_dir, job)
        entry = ctx.manifest.get(rel)
        recorded_status = entry.get("http_status") if entry else None
        # A recorded status only skips the job if it is PERMANENT (4xx other
        # than 429 or 400). 429 and 5xx are transient -- e.g. the 2026-09-15
        # incident poisoned MANIFEST.json with http_status:429 on every
        # tennis season, and without this check those jobs would be skipped
        # forever. 400 (Bad Request) joined this list 2026-09-15 (DEFECT 1/2
        # fix): unlike 401/403/404 (genuinely not entitled/not found, no
        # request would ever succeed), a 400 means THIS request was malformed
        # -- exactly what the old unfiltered NHL-games and MLB/NBA/NHL/tennis
        # odds jobs recorded before this fix corrected their params/shape.
        # Treating 400 as permanent would keep skipping the very jobs this
        # fix exists to unblock, forever, since the skip check is keyed on
        # the manifest FILE PATH, not on whether the params changed. This is
        # deliberately a property of the recorded status, not a one-time
        # manifest edit, so a concurrently-running job rewriting the
        # manifest can never un-fix it.
        permanent = (recorded_status is not None and recorded_status != 429
                     and recorded_status != 400 and not (500 <= recorded_status < 600))
        if entry and (entry.get("complete") or permanent):
            skipped += 1
            continue

        if ctx.deadline is not None and ctx.clock() >= ctx.deadline:
            break

        try:
            result = job.run(ctx, job)
        except BallDontLieError:
            result = JobResult(status="error", http_status=None)
        except Exception:  # noqa: BLE001 -- see docstring: never take the loop down
            result = JobResult(status="error", http_status=None)

        out_path = _out_path(ctx.out_dir, job.sport, job.out_name)
        base_entry = {
            "file": rel, "sport": job.sport, "endpoint": job.endpoint,
            "params": job.params, "harvested_utc": _utc_now_iso(),
        }
        if result.status == "complete":
            if out_path.exists():
                sha256, size, rows = _finalize_file(out_path)
            else:
                sha256, size, rows = None, 0, 0
            ctx.manifest[rel] = {**base_entry, "rows": rows, "sha256": sha256,
                                  "bytes": size, "complete": True}
            if rows == 0:
                # Visibly distinguish a genuinely-empty complete job (e.g.
                # the rankings probe hitting its floor with no data at all,
                # root cause E) from an ordinary successful pull, rather
                # than letting it look identical to "complete": True with a
                # plausible row count.
                ctx.manifest[rel]["zero_rows"] = True
            completed += 1
        elif result.status == "error":
            ctx.manifest[rel] = {**base_entry, "rows": result.rows_written, "sha256": None,
                                  "bytes": out_path.stat().st_size if out_path.exists() else 0,
                                  "complete": False, "http_status": result.http_status}
            errored += 1
        else:  # partial
            ctx.manifest[rel] = {**base_entry, "rows": result.rows_written, "sha256": None,
                                  "bytes": out_path.stat().st_size if out_path.exists() else 0,
                                  "complete": False}
            partial += 1
            if result.reason == "rate_limited":
                partial_rate_limited += 1
            else:
                partial_deadline += 1

        save_manifest(ctx.out_dir, ctx.manifest)
        if result.status == "partial":
            if result.reason == "rate_limited":
                # Root cause B: a rate-limit exhaustion means the ACCOUNT is
                # still rate-limited, not that the RUN is out of time -- with
                # run time left, move on to the next job rather than ending
                # the whole run. Guard against the pathological case (the
                # account is hard-blocked for the rest of the run) below.
                consecutive_rate_limited += 1
                if consecutive_rate_limited >= _RATE_LIMIT_HARD_BLOCK_THRESHOLD:
                    break
            else:
                break  # genuine deadline hit inside the job -- stop cleanly, state is saved
        else:
            consecutive_rate_limited = 0

    return {"completed": completed, "skipped": skipped, "errored": errored, "partial": partial,
            "partial_rate_limited": partial_rate_limited, "partial_deadline": partial_deadline}


# One cheap, per_page=1 endpoint per sport for --probe. Paths are ones this
# plan already uses (tennis' /atp/v1/players -- see _tennis_jobs) or ones
# confirmed against the OpenAPI specs cited in this module's docstring
# (nfl/mlb/nba/nhl .../v1/teams).
_PROBE_ENDPOINTS = {
    "tennis": "/atp/v1/players",
    "nfl": "/nfl/v1/teams",
    "mlb": "/mlb/v1/teams",
    "nba": "/nba/v1/teams",
    "nhl": "/nhl/v1/teams",
}


def run_probe(client: Client, sports: list) -> None:
    """--probe: exactly one per_page=1 request per selected sport, to see
    the account's current rate-limit state without spending real quota.
    Prints ONLY the sport, HTTP status, and the whitelisted rate-limit
    headers -- no response body, no API key, no URL/query string (see
    src/providers/balldontlie.py's Client.probe and _whitelist_headers)."""
    for sport in sports:
        path = _PROBE_ENDPOINTS.get(sport)
        if path is None:
            continue
        try:
            status, headers = client.probe(path, {"per_page": 1})
        except BallDontLieError as exc:
            print(f"{sport}: error ({exc})")
            continue
        print(f"{sport}: status={status} headers={headers}")


def _print_plan(jobs: list) -> None:
    by_sport: dict = {}
    for job in jobs:
        by_sport.setdefault(job.sport, []).append(job)
    total = 0
    for sport in ALL_SPORTS:
        sport_jobs = by_sport.get(sport)
        if not sport_jobs:
            continue
        sport_total = sum(j.est_requests for j in sport_jobs)
        total += sport_total
        print(f"== {sport}: {len(sport_jobs)} jobs, ~{sport_total} requests (heuristic estimate) ==")
        for job in sport_jobs:
            print(f"  {job.sport}/{job.out_name}.jsonl.gz  {job.path}  "
                  f"params={job.params}  ~{job.est_requests} req  -- {job.description}")
    print(f"TOTAL: {len(jobs)} jobs, ~{total} requests (heuristic estimate)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sports", default=",".join(ALL_SPORTS),
                     help="comma-separated sports to harvest (default: all)")
    ap.add_argument("--only", default=None, help="restrict to one logical endpoint id")
    ap.add_argument("--max-minutes", type=float, default=None,
                     help="stop cleanly after this many minutes, leaving resumable state")
    ap.add_argument("--dry-run", action="store_true",
                     help="print the plan and a request estimate; touches no network")
    ap.add_argument("--probe", action="store_true",
                     help="one cheap per_page=1 request per selected sport; prints status + "
                          "rate-limit headers only, then exits (no harvesting)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                     help="output directory (default: data/historical/balldontlie)")
    args = ap.parse_args(argv)

    sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    unknown = [s for s in sports if s not in ALL_SPORTS]
    if unknown:
        print(f"unknown sport(s): {', '.join(unknown)} -- known: {', '.join(ALL_SPORTS)}",
              file=sys.stderr)
        return 2

    # Computed before build_plan (which reads it, read-only, to enumerate
    # already-harvested game dates for the odds sweep -- see
    # _odds_sweep_jobs) rather than after, as it used to be.
    out_dir = Path(args.out_dir)
    jobs = build_plan(sports, only=args.only, out_dir=out_dir)

    if args.dry_run:
        _print_plan(jobs)
        return 0

    try:
        client = client_from_env()
    except BallDontLieError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.probe:
        run_probe(client, sports)
        return 0

    manifest = load_manifest(out_dir)
    deadline = (time.monotonic() + args.max_minutes * 60) if args.max_minutes is not None else None
    ctx = RunContext(client=client, out_dir=out_dir, manifest=manifest, deadline=deadline)

    summary = run_plan(jobs, ctx)
    print(f"jobs: {summary['completed']} completed, {summary['skipped']} skipped, "
          f"{summary['partial']} partial "
          f"({summary['partial_rate_limited']} rate-limited, {summary['partial_deadline']} deadline), "
          f"{summary['errored']} errored")
    print(f"rate_state: {client.rate_state()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
