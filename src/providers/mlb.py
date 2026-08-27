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
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API_HOST = "https://statsapi.mlb.com/api/v1"
SPORT_ID = 1  # MLB
USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"
DEFAULT_TIMEOUT = 20

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

def _get_json(path: str, params: dict | None = None, timeout: int = DEFAULT_TIMEOUT):
    """Single network seam. Tests patch this and nothing else.

    Raises MLBError on any transport or decode failure rather than letting a
    urllib exception escape, so callers have one exception type to handle.
    """
    query = urllib.parse.urlencode(params or {})
    url = f"{API_HOST}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MLBError(f"MLB API returned HTTP {exc.code} for {path}") from exc
    except urllib.error.URLError as exc:
        raise MLBError(f"could not reach MLB API: {exc.reason}") from exc
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

def fetch_schedule(game_date, timeout: int = DEFAULT_TIMEOUT) -> list:
    """Raw game records for one date, with pitchers and linescore hydrated."""
    day = _validate_date(game_date)
    payload = _get_json(
        "schedule",
        {
            "sportId": SPORT_ID,
            "date": day,
            "hydrate": "probablePitcher,team,linescore",
        },
        timeout=timeout,
    )
    games = []
    for entry in payload.get("dates") or []:
        games.extend(entry.get("games") or [])
    return games


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


def fetch_games(game_date, timeout: int = DEFAULT_TIMEOUT) -> list:
    """Parsed games for one date, in schedule order."""
    return [parse_game(g) for g in fetch_schedule(game_date, timeout=timeout)]


def fetch_results(game_date, timeout: int = DEFAULT_TIMEOUT) -> dict:
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


def fetch_pitcher_game_log(person_id, season, timeout: int = DEFAULT_TIMEOUT) -> list:
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


def backfill_results(start, end, timeout: int = DEFAULT_TIMEOUT,
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
