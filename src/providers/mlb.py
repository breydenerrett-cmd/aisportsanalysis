"""MLB Stats API provider: schedule, probable pitchers, and final results.

Free, keyless, and documented. This is the spine of the data layer -- it serves
today's slate and, crucially, decades of completed games.

ON BACKFILL
-----------
The instinct when a model needs graded results is to wait for tonight's games
to settle. That path yields one usable slate per day and takes a season to
produce a sample worth analysing.

This API serves historical seasons on the same endpoint. Three past seasons is
roughly 7,000 completed games with final scores, available in an afternoon.
That is the difference between calibrating a model this week and calibrating it
next year. Use `iter_dates` / `fetch_results` over a date range.

ON GAME STATE
-------------
A game is only usable as a graded outcome when it is genuinely final. In-progress
games carry partial scores that look exactly like final ones -- same fields,
same types -- and silently ingesting them corrupts a ledger in a way that is
very hard to detect later. `is_final` is the single gate, and it checks the
coded state rather than the human-readable string, which varies.

All network access funnels through `_get_json` so tests can replace one seam
and never touch the network.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API_HOST = "https://statsapi.mlb.com/api/v1"
SPORT_ID = 1  # MLB
USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"


def _env_float(name: str, fallback: float) -> float:
    """Env override for a timing constant, falling back on a bad or absent value.

    Never raises: an operator typo in the environment should not take the
    provider down, it should just be ignored in favour of the constant that
    already works.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


# TIMEOUT SHAPE (red-team round: a stalled MLB API response used to pin one
# request-handling worker for DEFAULT_TIMEOUT's old value of 20 SECONDS --
# fire enough concurrent requests against a stalled endpoint and every worker
# in the pool is parked waiting on a socket that will never answer. That is a
# DoS knob handed to anyone who can make an HTTP request, private alpha or not.
#
# `urllib.request.urlopen`'s single `timeout` bounds one whole blocking call
# (connect through to a completed read) -- stdlib urllib has no separate
# connect-phase timeout the way `requests`' (host, connect_timeout,
# read_timeout) tuple does, and hand-rolling one via raw sockets is not worth
# the complexity for a stdlib client. MLB_CONNECT_TIMEOUT_S approximates it
# instead: it is always the FIRST attempt's timeout, so a connection that
# will not even open fails fast regardless of what the caller asked for.
# MLB_TOTAL_TIMEOUT_S (or whatever timeout the caller passed) governs the one
# retry, giving a server that is merely slow -- not dead -- a real chance to
# answer. Worst case per _get_json call is therefore MLB_CONNECT_TIMEOUT_S +
# the caller's timeout, not the caller's timeout doubled and never the old
# unbounded-feeling 20s pin.
MLB_CONNECT_TIMEOUT_S = _env_float("MLB_CONNECT_TIMEOUT_S", 3.0)
MLB_TOTAL_TIMEOUT_S = _env_float("MLB_TOTAL_TIMEOUT_S", 8.0)

# What every fetch_* function below defaults `timeout=` to when a caller does
# not specify one -- this is the value the live request-serving path
# (api/today.py, api/games.py, api/betcheck.py all call mlb.fetch_games/
# fetch_schedule with no explicit timeout) actually gets. Batch/research
# callers (src/pipeline/*.py) pass their own literal timeout and are
# unaffected by this constant; verified by grep across src/pipeline before
# this change landed -- none of them reads DEFAULT_TIMEOUT.
DEFAULT_TIMEOUT = MLB_TOTAL_TIMEOUT_S

# Coded game states that mean "this game is over and the result is official".
# Checked against codedGameState, not detailedState -- the latter is a display
# string ("Final", "Game Over", "Completed Early") and varies by situation.
FINAL_STATE_CODES = frozenset({"F", "O"})

# States meaning the game will not be played as scheduled. These are not
# failures; they must be recorded and skipped, never graded.
CANCELLED_STATE_CODES = frozenset({"D", "C", "T", "U"})

# gameType codes. The distinction is not cosmetic: it decides both whether a tie
# is possible and whether a game belongs in a training set at all.
GAME_TYPE_REGULAR = "R"
GAME_TYPE_SPRING = "S"
GAME_TYPE_EXHIBITION = "E"
GAME_TYPE_ALL_STAR = "A"

# Competitive games that must produce a winner. A tie here means the data is
# wrong, not that the game ended level.
DECISIVE_GAME_TYPES = frozenset({
    GAME_TYPE_REGULAR,
    "F",  # Wild Card
    "D",  # Division Series
    "L",  # League Championship Series
    "W",  # World Series
    "P",  # Playoff (legacy tiebreaker)
})

# Exhibition play where a tie is a legitimate final result. Spring training games
# routinely end level once both managers run out of pitchers, and the All-Star
# Game itself famously ended 7-7 in 2002.
TIE_ALLOWED_GAME_TYPES = frozenset({
    GAME_TYPE_SPRING, GAME_TYPE_EXHIBITION, GAME_TYPE_ALL_STAR, "I",
})

# What belongs in a model's training data. Spring training is excluded on
# purpose and it is worth being explicit about why: split squads, minor-league
# rosters, pitchers on artificial pitch counts, and no competitive incentive.
# Those games are real baseball but they are not the process being modeled, and
# including them would teach the model from a different sport wearing the same
# uniforms.
TRAINING_GAME_TYPES = frozenset({GAME_TYPE_REGULAR})


class MLBError(RuntimeError):
    """Raised when the MLB Stats API cannot be reached or returns junk."""


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

# A stall (timeout) or a reset mid-transfer means the request never really
# landed -- retrying is the right instinct. An HTTP error status means the
# provider DID answer, just with a status we don't like; retrying that just
# re-asks a question it already declined to answer, so it is deliberately
# excluded (see the `except urllib.error.HTTPError` branch below, which
# raises immediately and never reaches the retry loop).
_RETRYABLE_REASON_TYPES = (socket.timeout, TimeoutError, ConnectionResetError)


def _is_retryable_transport_error(exc: urllib.error.URLError) -> bool:
    return isinstance(getattr(exc, "reason", None), _RETRYABLE_REASON_TYPES)


def _get_json(path: str, params: dict | None = None, timeout: float | None = None):
    """Single network seam. Tests patch this and nothing else.

    `timeout=None` (the default) uses the two-attempt shape described above
    `MLB_CONNECT_TIMEOUT_S`: quick first attempt, more patient retry, and
    only on a timeout/reset. Passing an explicit `timeout` (as every
    src/pipeline/*.py batch caller does) keeps that value on both the first
    attempt and the one retry -- the retry is new behaviour for those
    callers, the timeout duration itself is not.

    Raises MLBError on any transport or decode failure rather than letting a
    urllib exception escape, so callers have one exception type to handle.
    """
    query = urllib.parse.urlencode(params or {})
    url = f"{API_HOST}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    retry_timeout = MLB_TOTAL_TIMEOUT_S if timeout is None else timeout
    attempt_timeouts = (MLB_CONNECT_TIMEOUT_S, retry_timeout)

    for attempt, attempt_timeout in enumerate(attempt_timeouts):
        try:
            with urllib.request.urlopen(request, timeout=attempt_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise MLBError(f"MLB API returned HTTP {exc.code} for {path}") from exc
        except urllib.error.URLError as exc:
            is_last_attempt = attempt == len(attempt_timeouts) - 1
            if is_last_attempt or not _is_retryable_transport_error(exc):
                raise MLBError(f"could not reach MLB API: {exc.reason}") from exc
            continue  # one quick retry on a timeout/reset only
        except json.JSONDecodeError as exc:
            raise MLBError(f"MLB API returned invalid JSON for {path}") from exc


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

def is_final(game: dict) -> bool:
    """True only when the game is over and the score is official.

    Deliberately strict. An in-progress game carries a partial score in the
    same field a final game uses, so a loose check silently ingests garbage.
    Requires the coded state to be final AND both scores present.
    """
    status = (game.get("status") or {})
    if status.get("codedGameState") not in FINAL_STATE_CODES:
        return False
    teams = game.get("teams") or {}
    for side in ("away", "home"):
        if (teams.get(side) or {}).get("score") is None:
            return False
    return True


def is_cancelled(game: dict) -> bool:
    """True when the game was postponed, cancelled, or suspended."""
    status = (game.get("status") or {})
    return status.get("codedGameState") in CANCELLED_STATE_CODES


def game_state(game: dict) -> str:
    """Coarse classification: 'final', 'cancelled', or 'pending'."""
    if is_final(game):
        return "final"
    if is_cancelled(game):
        return "cancelled"
    return "pending"


# ---------------------------------------------------------------------------
# Schedule and results
# ---------------------------------------------------------------------------

def fetch_schedule(game_date, timeout: float = DEFAULT_TIMEOUT,
                    hydrate_officials: bool = False) -> list:
    """Raw game records for one date, with pitchers and linescore hydrated.

    `hydrate_officials=True` additionally asks the API for the umpire crew
    (`hydrate=officials`) -- see `fetch_officials`/`parse_officials` below.
    It defaults False and every caller that does not pass it gets the exact
    same `hydrate` string, and therefore the exact same payload, as before
    this flag existed: additive and opt-in, on purpose, because
    api/today.py, api/games.py and api/betcheck.py all call this with no
    `hydrate` argument of their own and must never see their response shape
    change under them.
    """
    day = _validate_date(game_date)
    hydrate = "probablePitcher,team,linescore"
    if hydrate_officials:
        hydrate = f"{hydrate},officials"
    payload = _get_json(
        "schedule",
        {
            "sportId": SPORT_ID,
            "date": day,
            "hydrate": hydrate,
        },
        timeout=timeout,
    )
    games = []
    for entry in payload.get("dates") or []:
        games.extend(entry.get("games") or [])
    return games


# ---------------------------------------------------------------------------
# Umpire crews (officials)
# ---------------------------------------------------------------------------

# The officialType MLB uses for the umpire who calls balls and strikes -- the
# one crew slot every downstream user of this data actually wants named
# explicitly, rather than everyone re-deriving it from the raw list.
HOME_PLATE_OFFICIAL_TYPE = "Home Plate"


def parse_officials(game: dict) -> dict:
    """Flatten one API game record's umpire crew.

    ON THE REVEAL WINDOW (verified live against this same host, 2026-09-02)
    -------------------------------------------------------------------
    The `officials` hydrate is EMPTY while a game's `detailedState` is
    'Scheduled', and becomes a populated 4-person crew by 'Pre-Game' or
    'Warmup' -- observed 3.6-4.6 hours before first pitch on that date's
    slate. `officials: []` for a still-`Scheduled` game is therefore the
    honest, expected answer, not a fetch failure and not a reason to retry:
    it says the API was asked and it has not revealed the crew yet. Historical
    availability back to 2015 is asserted by the same audit but not exercised
    here -- this function is forward-only, called from `fetch_officials`.

    Nothing is invented: a missing crew stays an empty list, never padded or
    guessed at.
    """
    officials = []
    for entry in game.get("officials") or []:
        official = entry.get("official") or {}
        officials.append({
            "id": official.get("id"),
            "name": official.get("fullName"),
            "officialType": entry.get("officialType"),
        })
    return {
        "game_pk": game.get("gamePk"),
        "officials": officials,
        "game_state": (game.get("status") or {}).get("detailedState"),
        "first_pitch_utc": game.get("gameDate"),
    }


def home_plate_umpire(officials: list):
    """The Home Plate crew member's name from a `parse_officials` list, or None."""
    for official in officials or []:
        if official.get("officialType") == HOME_PLATE_OFFICIAL_TYPE:
            return official.get("name")
    return None


def fetch_officials(game_date, timeout: float = DEFAULT_TIMEOUT) -> list:
    """Umpire crews for one date's slate, one record per game.

    Additive and opt-in: this is the only caller in this module that passes
    `hydrate_officials=True`, so every other `fetch_schedule` caller is
    completely unaffected by this function's existence. Returns
    `parse_officials` records; a game that has not reached 'Pre-Game' yet
    comes back with `officials: []`, which `src.pipeline.umpirewatch` uses to
    bracket the reveal between the last empty poll and the first non-empty one.
    """
    games = fetch_schedule(game_date, timeout=timeout, hydrate_officials=True)
    return [parse_officials(game) for game in games]


def parse_game(game: dict) -> dict:
    """Flatten one API game record into the fields this project uses.

    Scores are returned as-is, including for unfinished games -- callers must
    check `state` before treating them as results. Nothing is invented: a
    missing probable pitcher stays None rather than becoming a placeholder.
    """
    teams = game.get("teams") or {}
    away, home = (teams.get("away") or {}), (teams.get("home") or {})
    state = game_state(game)

    record = {
        "game_pk": game.get("gamePk"),
        "date": (game.get("officialDate") or (game.get("gameDate") or "")[:10]) or None,
        "start_time_utc": game.get("gameDate"),
        "state": state,
        "game_type": game.get("gameType"),
        "detailed_state": (game.get("status") or {}).get("detailedState"),
        "venue": (game.get("venue") or {}).get("name"),
        "away_team": _team_abbrev(away),
        "home_team": _team_abbrev(home),
        "away_team_id": (away.get("team") or {}).get("id"),
        "home_team_id": (home.get("team") or {}).get("id"),
        "away_score": away.get("score"),
        "home_score": home.get("score"),
        "away_probable": _pitcher_name(away),
        "home_probable": _pitcher_name(home),
        "away_probable_id": _pitcher_id(away),
        "home_probable_id": _pitcher_id(home),
        "double_header": game.get("doubleHeader"),
        "game_number": game.get("gameNumber"),
        "first_five": first_five(game),
    }

    # A winner is only meaningful for a genuinely final game -- and whether a tie
    # is even possible depends on the game type.
    #
    # In a competitive game a tied "final" means the data is wrong, so raising is
    # correct: silently picking a side would put a fabricated winner into the
    # training set. But spring training and exhibition games legitimately end
    # level once both managers run out of pitchers, and treating that as
    # corruption caused four real spring dates to fail ingestion entirely.
    if state == "final":
        away_score, home_score = record["away_score"], record["home_score"]
        game_type = record["game_type"]

        if away_score == home_score:
            if game_type in DECISIVE_GAME_TYPES:
                raise MLBError(
                    f"game {record['game_pk']} (type {game_type!r}) reports final "
                    f"with a tied score {away_score}-{home_score}; a competitive "
                    "game must have a winner, so this is bad data"
                )
            if game_type not in TIE_ALLOWED_GAME_TYPES:
                raise MLBError(
                    f"game {record['game_pk']} has unknown gameType {game_type!r} "
                    f"and a tied score {away_score}-{home_score}; refusing to "
                    "guess whether a tie is legal for this game type"
                )
            # A legitimate exhibition tie. There is no winner, and saying so is
            # the honest answer rather than picking one.
            record["winner"] = None
            record["home_won"] = None
        else:
            record["winner"] = (
                record["home_team"] if home_score > away_score else record["away_team"]
            )
            record["home_won"] = 1 if home_score > away_score else 0

        record["total_runs"] = away_score + home_score
        record["run_differential"] = abs(home_score - away_score)
    else:
        record["winner"] = None
        record["home_won"] = None
        record["total_runs"] = None
        record["run_differential"] = None

    return record


# The first five innings are a market in their own right, and grading it needs the
# half-inning line rather than the final score. Five is not a slice of the final
# score and cannot be derived from it.
FIRST_FIVE_INNINGS = 5


def first_five(game: dict) -> dict:
    """Runs through five complete innings, or an explicit statement of why not.

    WHY THIS IS STRICTER THAN IT LOOKS
    ----------------------------------
    A first-five bet is void unless five full innings are played, and "five full
    innings" is not the same as "the game was official". A game called after the top
    of the fifth with the home team ahead is an official, final game -- and its first
    five never finished, because the home side never batted in the fifth.

    That case is rare, which is exactly what makes it dangerous: a scanner graded
    across a season would meet it a handful of times, and scoring those as results
    rather than voids would quietly corrupt the record with games whose outcome was
    decided by weather.

    So both halves of all five innings must carry an explicit run total. A missing
    half is void, never zero. `complete` is False and `runs` is None rather than a
    number that looks usable.
    """
    linescore = game.get("linescore") or {}
    innings = linescore.get("innings") or []
    result = {"complete": False, "away_runs": None, "home_runs": None,
              "total_runs": None, "winner": None, "reason": None,
              "innings_available": len(innings)}

    if len(innings) < FIRST_FIVE_INNINGS:
        result["reason"] = (
            f"only {len(innings)} inning(s) in the line; a first-five market needs "
            f"{FIRST_FIVE_INNINGS} and is void otherwise")
        return result

    away_total = home_total = 0
    for inning in innings[:FIRST_FIVE_INNINGS]:
        for half, running in (("away", "away"), ("home", "home")):
            runs = (inning.get(half) or {}).get("runs")
            if runs is None:
                # A half-inning with no run total was not played. Treating it as a
                # zero would silently turn a void into a result.
                result["reason"] = (
                    f"the {half} half of inning {inning.get('num')} has no run total, "
                    "so five full innings were not played")
                return result
            if half == "away":
                away_total += runs
            else:
                home_total += runs

    result.update({
        "complete": True,
        "away_runs": away_total,
        "home_runs": home_total,
        "total_runs": away_total + home_total,
        # A first-five moneyline can genuinely tie, unlike a full game. None is the
        # honest answer, not a coin flip.
        "winner": (None if away_total == home_total
                   else ("home" if home_total > away_total else "away")),
    })
    return result


def fetch_games(game_date, timeout: float = DEFAULT_TIMEOUT) -> list:
    """Parsed games for one date, in schedule order."""
    return [parse_game(g) for g in fetch_schedule(game_date, timeout=timeout)]


def fetch_results(game_date, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Games for one date, split by state, with counts.

    Returns a dict with `final`, `pending`, `cancelled`, and a `summary`. The
    split is the point: a caller appending to a ledger takes `final` only, and
    the counts make it obvious when a date has nothing usable yet.
    """
    games = fetch_games(game_date, timeout=timeout)
    buckets = {"final": [], "pending": [], "cancelled": []}
    for game in games:
        buckets[game["state"]].append(game)
    return {
        **buckets,
        "date": _validate_date(game_date),
        "summary": {
            "total": len(games),
            "final": len(buckets["final"]),
            "pending": len(buckets["pending"]),
            "cancelled": len(buckets["cancelled"]),
        },
    }


def fetch_pitcher_game_log(person_id, season, timeout: float = DEFAULT_TIMEOUT) -> list:
    """Every pitching appearance for one player in one season, oldest first.

    This is the raw material for point-in-time pitcher stats. Season-to-date figures
    from the API include the whole season and would leak the future into past games;
    a game log can be accumulated forward to whatever date is needed.

    Returns one record per appearance with the date attached. An empty list is a
    legitimate answer -- a pitcher who missed the season through injury has no
    appearances, and that is different from a failed request.
    """
    payload = _get_json(
        f"people/{person_id}/stats",
        {"stats": "gameLog", "group": "pitching", "season": season},
        timeout=timeout,
    )
    stats = payload.get("stats") or []
    if not stats:
        return []

    appearances = []
    for split in stats[0].get("splits") or []:
        stat = split.get("stat") or {}
        appearances.append({
            "person_id": int(person_id),
            "date": split.get("date"),
            "season": str(season),
            "is_home": split.get("isHome"),
            "games_started": _as_int(stat.get("gamesStarted")),
            "innings_pitched": _innings_to_float(stat.get("inningsPitched")),
            "earned_runs": _as_int(stat.get("earnedRuns")),
            "runs": _as_int(stat.get("runs")),
            "hits": _as_int(stat.get("hits")),
            "walks": _as_int(stat.get("baseOnBalls")),
            "strikeouts": _as_int(stat.get("strikeOuts")),
            "home_runs": _as_int(stat.get("homeRuns")),
            "batters_faced": _as_int(stat.get("battersFaced")),
            "pitches": _as_int(stat.get("numberOfPitches")),
        })
    appearances.sort(key=lambda a: a.get("date") or "")
    return appearances


# ---------------------------------------------------------------------------
# Boxscores and linescores (per-game, per-player lines)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS: no batter prop and no pitcher prop beyond strikeouts can
# ever be settled, backtested, or self-reviewed without per-game, per-player
# box lines -- a moneyline/spread grade needs only the final score, but "did
# this batter get 2+ hits" needs the batter's own line. The MLB Stats API
# serves it free and keyless, backfillable to 2023, on the same host and the
# same `_get_json` seam as everything else in this module.
#
# `fetch_boxscore` and `fetch_linescore` return the RAW API payload, parsed
# by `parse_boxscore`/`parse_linescore` below -- kept separate the same way
# `fetch_officials`/`parse_officials` are, so a caller that wants the raw
# shape (or a test with a raw fixture) is not forced through the flattener.

def fetch_boxscore(game_pk, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Raw boxscore payload for one game: full batting/pitching lines by team."""
    return _get_json(f"game/{game_pk}/boxscore", timeout=timeout)


def fetch_linescore(game_pk, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Raw linescore payload for one game: runs/hits/errors by inning."""
    return _get_json(f"game/{game_pk}/linescore", timeout=timeout)


def parse_boxscore(game_pk, boxscore: dict) -> dict:
    """Flatten one game's boxscore into pitcher rows and batter rows.

    Only players with a non-empty `stats.batting` or `stats.pitching` block
    are included -- the API lists the whole active roster (bench, bullpen
    arms who never entered) with empty stat blocks, and those never-played
    players are not a game line, they are a roster note. A player can appear
    in both lists (a position player who pitched, or a pitcher who batted in
    an NL park); that is not a bug, it is two real lines for one game.

    Computed fields (`total_bases`, `hits_runs_rbi`) are derived here, once,
    from the same box, so every downstream reader (grading, features) agrees
    on the arithmetic instead of re-deriving it slightly differently each time.
    """
    pitchers, batters = [], []
    teams = boxscore.get("teams") or {}
    for side in ("away", "home"):
        team = teams.get(side) or {}
        team_info = team.get("team") or {}
        team_id = team_info.get("id")
        team_name = team_info.get("name")
        for player in (team.get("players") or {}).values():
            person = player.get("person") or {}
            player_id = person.get("id")
            player_name = person.get("fullName")
            stats = player.get("stats") or {}
            batting = stats.get("batting") or {}
            pitching = stats.get("pitching") or {}
            if pitching:
                pitchers.append({
                    "game_pk": _as_int(game_pk),
                    "side": side,
                    "team_id": team_id,
                    "team_name": team_name,
                    "player_id": player_id,
                    "player_name": player_name,
                    "outs": _as_int(pitching.get("outs")),
                    "ip": _innings_to_float(pitching.get("inningsPitched")),
                    "h": _as_int(pitching.get("hits")),
                    "er": _as_int(pitching.get("earnedRuns")),
                    "r": _as_int(pitching.get("runs")),
                    "bb": _as_int(pitching.get("baseOnBalls")),
                    "k": _as_int(pitching.get("strikeOuts")),
                    "pitches": _as_int(pitching.get("numberOfPitches")),
                    "batters_faced": _as_int(pitching.get("battersFaced")),
                })
            if batting:
                hits = _as_int(batting.get("hits")) or 0
                doubles = _as_int(batting.get("doubles")) or 0
                triples = _as_int(batting.get("triples")) or 0
                home_runs = _as_int(batting.get("homeRuns")) or 0
                runs = _as_int(batting.get("runs")) or 0
                rbi = _as_int(batting.get("rbi")) or 0
                singles = hits - doubles - triples - home_runs
                total_bases = (singles + 2 * doubles + 3 * triples
                               + 4 * home_runs)
                batters.append({
                    "game_pk": _as_int(game_pk),
                    "side": side,
                    "team_id": team_id,
                    "team_name": team_name,
                    "player_id": player_id,
                    "player_name": player_name,
                    "pa": _as_int(batting.get("plateAppearances")),
                    "ab": _as_int(batting.get("atBats")),
                    "h": hits,
                    "doubles": doubles,
                    "triples": triples,
                    "hr": home_runs,
                    "r": runs,
                    "rbi": rbi,
                    "bb": _as_int(batting.get("baseOnBalls")),
                    "k": _as_int(batting.get("strikeOuts")),
                    "sb": _as_int(batting.get("stolenBases")),
                    "total_bases": total_bases,
                    "hits_runs_rbi": hits + runs + rbi,
                })
    return {"game_pk": _as_int(game_pk), "pitchers": pitchers, "batters": batters}


def parse_linescore(game_pk, linescore: dict) -> dict:
    """Flatten one game's linescore: runs by inning plus first-scoring facts.

    `first_team_to_score` walks innings in order (away bats the top half,
    home the bottom) and returns the side of the first half-inning with any
    runs -- `None` for a game that never scored, which is a real, recordable
    outcome, not a miss. First-inning scoring is broken out explicitly
    because it is its own settleable prop family ("first inning: yes/no").
    """
    innings = []
    first_scoring_side = None
    for inning in linescore.get("innings") or []:
        away_runs = _as_int((inning.get("away") or {}).get("runs")) or 0
        home_runs = _as_int((inning.get("home") or {}).get("runs")) or 0
        innings.append({
            "num": inning.get("num"),
            "away_runs": away_runs,
            "home_runs": home_runs,
        })
        if first_scoring_side is None:
            if away_runs > 0:
                first_scoring_side = "away"
            elif home_runs > 0:
                first_scoring_side = "home"

    first = innings[0] if innings else {"away_runs": 0, "home_runs": 0}
    first_inning_away_runs = first["away_runs"]
    first_inning_home_runs = first["home_runs"]
    return {
        "game_pk": _as_int(game_pk),
        "innings": innings,
        "first_inning_away_runs": first_inning_away_runs,
        "first_inning_home_runs": first_inning_home_runs,
        "first_inning_scored": bool(first_inning_away_runs
                                     or first_inning_home_runs),
        "first_team_to_score": first_scoring_side,
    }


def _innings_to_float(value):
    """Convert baseball's innings notation to a real number.

    Innings pitched are written in thirds: "5.1" means five and ONE THIRD innings,
    not five and one tenth. Treating that string as a float understates every rate
    statistic computed from it -- ERA, WHIP, K/9 -- by a few percent, consistently
    and invisibly. It is one of the classic silent errors in baseball data work.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "." not in text:
        try:
            return float(text)
        except ValueError:
            return None
    whole, _, fraction = text.partition(".")
    try:
        innings = float(whole)
    except ValueError:
        return None
    if fraction == "1":
        return innings + 1.0 / 3.0
    if fraction == "2":
        return innings + 2.0 / 3.0
    if fraction == "0":
        return innings
    # An unexpected fraction means the notation is not what we think it is.
    raise MLBError(
        f"innings pitched {value!r} has an unexpected fraction; baseball uses "
        "thirds (.0, .1, .2) and misreading it silently skews every rate stat"
    )


def _as_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iter_dates(start, end):
    """Yield ISO dates from start to end inclusive. The backfill driver."""
    first, last = _to_date(start), _to_date(end)
    if first > last:
        raise MLBError(f"start date {first} is after end date {last}")
    current = first
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def backfill_results(start, end, timeout: float = DEFAULT_TIMEOUT,
                     on_date=None) -> dict:
    """Collect every FINAL game across a date range.

    This is the function that turns "wait a season" into "wait an afternoon".

    `on_date` is an optional callback receiving each date's result dict, so a
    long run can report progress without this function knowing about printing.

    Dates that fail are recorded in `errors` and do not abort the run -- a
    single bad day should not discard hours of collection.
    """
    collected, errors = [], []
    dates_seen = 0
    for day in iter_dates(start, end):
        dates_seen += 1
        try:
            result = fetch_results(day, timeout=timeout)
        except MLBError as exc:
            errors.append({"date": day, "error": str(exc)})
            continue
        collected.extend(result["final"])
        if on_date is not None:
            on_date(result)
    return {
        "games": collected,
        "errors": errors,
        "dates_requested": dates_seen,
        "dates_failed": len(errors),
        "final_games": len(collected),
    }


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _team_abbrev(side: dict):
    team = side.get("team") or {}
    abbrev = team.get("abbreviation")
    return abbrev.strip().upper() if isinstance(abbrev, str) and abbrev else None


def _pitcher_name(side: dict):
    pitcher = side.get("probablePitcher") or {}
    name = pitcher.get("fullName")
    return name if isinstance(name, str) and name.strip() else None


def _pitcher_id(side: dict):
    return (side.get("probablePitcher") or {}).get("id")


def _validate_date(value) -> str:
    return _to_date(value).isoformat()


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise MLBError(f"date must be a string or date, got {value!r}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise MLBError(f"date must be ISO format YYYY-MM-DD, got {value!r}") from exc
