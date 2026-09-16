"""Free MLB live game-state poller.

WHY THIS EXISTS
---------------
Live betting markets close as games progress, and a live-odds capture needs
to know the game's state at each observation time. The MLB Stats API's
linescore endpoint is free, keyless, and updates in real time for in-play games.

This module polls for games in "Live" state, fetches their linescore, and appends
one state row per observation. For games that reach "Final", it records exactly
one final row and stops -- settlement needs the official score, and the poller
must never append a second final row.

WHY THIS IS INJECTABLE
----------------------
Every fetch is injectable (fetch_schedule, fetch_linescore) and the clock is
injectable, so tests run without the network and with deterministic time.
Network failures are recorded and do not abort the poll.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.asof import game_pk_key
from src.paths import data_path
from src.providers import mlb

LOG = logging.getLogger(__name__)

DEFAULT_LIVE_DIR = data_path("live", "mlb")

# R16-L5 (docs/LIVE_BETTING_SYSTEM.md 3.2): `fetch_schedule`'s hydrate string
# already includes "linescore", so each game in the schedule payload MAY
# already carry a usable linescore -- if it does, `poll()` uses it directly
# instead of an extra per-game `fetch_linescore` call (15 live games: 16
# calls every 20s drops to about 1). These are exactly the containers
# `_build_row` reads from a linescore; their PRESENCE (not their values --
# `outs`/`pitcher_id`/etc. can legitimately be 0 or None between plays) is
# what "carries every field the rules read" means here.
_SCHEDULE_LINESCORE_REQUIRED_KEYS = (
    "currentInning", "inningHalf", "inningState", "outs",
    "offense", "defense", "teams",
)


def _schedule_linescore_usable(linescore) -> bool:
    """Whether a schedule-hydrated `linescore` dict carries every container
    key `_build_row` reads, so a separate `fetch_linescore` call can be
    skipped for this game this poll."""
    if not isinstance(linescore, dict):
        return False
    return all(key in linescore for key in _SCHEDULE_LINESCORE_REQUIRED_KEYS)


def _eastern():
    """MLB's official timezone; a fixed -04:00 when no zone database is installed."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def poll(game_date=None, *, live_dir=DEFAULT_LIVE_DIR,
         fetch_schedule=mlb.fetch_schedule,
         fetch_linescore=mlb.fetch_linescore,
         clock=None, timeout=20) -> dict:
    """Poll MLB games for live state, appending one row per observation.

    Fetches the schedule for `game_date` (defaults to ET date of clock()),
    and for every game in "Live" state, fetches and records its linescore.
    For a game whose state is "Final" and whose last stored row is not Final,
    appends one final row and stops.

    Never raises on a network error: records it in report["errors"] and continues.

    Returns a summary: {"date", "live_games", "rows_written", "finals_written",
    "errors": [...], "dir"}.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    observed_utc = _utc_iso(clock())
    iso_date = _to_iso_date(game_date, clock)

    directory = Path(live_dir)
    directory.mkdir(parents=True, exist_ok=True)

    report = {
        "date": iso_date,
        "dir": str(directory),
        "live_games": 0,
        "rows_written": 0,
        "finals_written": 0,
        "errors": [],
    }

    # Fetch the schedule.
    try:
        games = fetch_schedule(iso_date, timeout=timeout)
    except Exception as exc:
        LOG.warning("livefeed_mlb: schedule fetch failed: %s", exc)
        report["errors"].append({"source": "schedule", "error": str(exc)})
        return report

    # Index the last stored row per game.
    last_rows = _last_rows(directory / f"{iso_date}.jsonl")

    # Process each game.
    for game in games or []:
        # D3: `game_pk` is canonicalized to the same string form used by
        # `pregame_context`/`gamekey` for every key this module writes below
        # (rows on disk, `report["errors"]`, `_state_id`). A mixed int/string
        # key is exactly what made `tick()` skip every MLB game silently.
        # The raw (numeric) id is kept separately for the linescore fetch --
        # the Stats API URL path, not a dict key -- so a string does not
        # change what gets requested.
        raw_pk = game.get("gamePk")
        game_pk = game_pk_key(raw_pk)
        if game_pk is None:
            continue

        abstract_state = (game.get("status") or {}).get("abstractGameState")
        if abstract_state not in ("Live", "Final"):
            continue

        if abstract_state == "Live":
            report["live_games"] += 1
            # R16-L5: use the schedule's own hydrated linescore when it
            # carries every field _build_row reads -- one schedule call
            # already paid for it (fetch_schedule's hydrate includes
            # "linescore"). Only fall back to a per-game fetch_linescore
            # call when the schedule payload didn't carry a usable one.
            schedule_linescore = game.get("linescore")
            if _schedule_linescore_usable(schedule_linescore):
                linescore = schedule_linescore
            else:
                try:
                    linescore = fetch_linescore(raw_pk, timeout=timeout)
                except Exception as exc:
                    LOG.warning("livefeed_mlb: linescore fetch for game %s failed: %s",
                               game_pk, exc)
                    report["errors"].append({
                        "source": "linescore",
                        "game_pk": game_pk,
                        "error": str(exc),
                    })
                    continue

            # Build the state row.
            row = _build_row(game, linescore, observed_utc)
            if row is not None:
                _append(directory / f"{iso_date}.jsonl", [row])
                report["rows_written"] += 1

        elif abstract_state == "Final":
            # Only write a final row if the last stored row is not already Final.
            last = last_rows.get(game_pk)
            if last is None or last.get("status") != "Final":
                row = _build_final_row(game, observed_utc)
                if row is not None:
                    _append(directory / f"{iso_date}.jsonl", [row])
                    report["finals_written"] += 1

    return report


def _build_row(game: dict, linescore: dict, observed_utc: str) -> dict | None:
    """Build a Live state row from a game and its linescore."""
    game_pk = game_pk_key(game.get("gamePk"))
    if game_pk is None:
        return None

    state_id = _state_id(game_pk, observed_utc)

    teams = game.get("teams") or {}
    away_team = teams.get("away") or {}
    home_team = teams.get("home") or {}

    away_name = (away_team.get("team") or {}).get("name")
    home_name = (home_team.get("team") or {}).get("name")

    away_probable_id = _pitcher_id(away_team)
    home_probable_id = _pitcher_id(home_team)

    linescore_data = linescore or {}
    current_inning = linescore_data.get("currentInning")
    inning_half = linescore_data.get("inningHalf")
    inning_state = linescore_data.get("inningState")
    outs = linescore_data.get("outs")
    balls = linescore_data.get("balls")
    strikes = linescore_data.get("strikes")

    offense = linescore_data.get("offense") or {}
    batter_id = (offense.get("batter") or {}).get("id")

    defense = linescore_data.get("defense") or {}
    pitcher_id = (defense.get("pitcher") or {}).get("id")

    # Runners on base.
    runners = {
        "first": (offense.get("first") or {}).get("id"),
        "second": (offense.get("second") or {}).get("id"),
        "third": (offense.get("third") or {}).get("id"),
    }

    home_stats = (linescore_data.get("teams") or {}).get("home") or {}
    away_stats = (linescore_data.get("teams") or {}).get("away") or {}

    return {
        "observed_utc": observed_utc,
        "state_id": state_id,
        "sport": "mlb",
        "game_pk": game_pk,
        "date": game.get("officialDate") or (game.get("gameDate") or "")[:10] or None,
        "status": "Live",
        "detailed_state": (game.get("status") or {}).get("detailedState"),
        "inning": current_inning,
        "half": inning_half.lower() if inning_half else None,
        "inning_state": inning_state,
        "outs": outs,
        "balls": balls,
        "strikes": strikes,
        "runners": runners,
        "batter_id": batter_id,
        "pitcher_id": pitcher_id,
        "home_team": home_name,
        "away_team": away_name,
        "home_runs": home_stats.get("runs"),
        "away_runs": away_stats.get("runs"),
        "home_hits": home_stats.get("hits"),
        "away_hits": away_stats.get("hits"),
        "home_probable_pitcher_id": home_probable_id,
        "away_probable_pitcher_id": away_probable_id,
    }


def _build_final_row(game: dict, observed_utc: str) -> dict | None:
    """Build a Final state row from a game."""
    game_pk = game_pk_key(game.get("gamePk"))
    if game_pk is None:
        return None

    state_id = _state_id(game_pk, observed_utc)

    teams = game.get("teams") or {}
    away_team = teams.get("away") or {}
    home_team = teams.get("home") or {}

    away_name = (away_team.get("team") or {}).get("name")
    home_name = (home_team.get("team") or {}).get("name")

    away_probable_id = _pitcher_id(away_team)
    home_probable_id = _pitcher_id(home_team)

    return {
        "observed_utc": observed_utc,
        "state_id": state_id,
        "sport": "mlb",
        "game_pk": game_pk,
        "date": game.get("officialDate") or (game.get("gameDate") or "")[:10] or None,
        "status": "Final",
        "detailed_state": (game.get("status") or {}).get("detailedState"),
        "inning": None,
        "half": None,
        "inning_state": None,
        "outs": None,
        "balls": None,
        "strikes": None,
        "runners": {"first": None, "second": None, "third": None},
        "batter_id": None,
        "pitcher_id": None,
        "home_team": home_name,
        "away_team": away_name,
        "home_runs": (home_team.get("score")),
        "away_runs": (away_team.get("score")),
        "home_hits": None,
        "away_hits": None,
        "home_probable_pitcher_id": home_probable_id,
        "away_probable_pitcher_id": away_probable_id,
    }


def _state_id(game_pk, observed_utc: str) -> str:
    """SHA1 hash of game_pk|observed_utc, first 16 hex chars."""
    text = f"{game_pk}|{observed_utc}"
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _pitcher_id(side: dict) -> int | None:
    """Extract pitcher id from a team's probable pitcher."""
    pitcher = side.get("probablePitcher") or {}
    pitcher_id = pitcher.get("id")
    return int(pitcher_id) if pitcher_id is not None else None


def read_states(date, *, live_dir=DEFAULT_LIVE_DIR) -> list[dict]:
    """Read all state rows for one date."""
    path = Path(live_dir) / f"{date}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("livefeed_mlb: %s:%s is not valid JSON; skipped",
                       path, len(rows) + 1)
    return rows


def latest_states(date, *, live_dir=DEFAULT_LIVE_DIR) -> dict:
    """Map game_pk (canonical string, D3) to the newest state row for one date.

    Normalizes every key through `game_pk_key`, not just what this module
    writes going forward: a row written before this fix stores `game_pk` as a
    native JSON int, and without normalizing on read too, a caller joining
    against the string keys `pregame_context` uses would still silently miss
    every pre-fix row.
    """
    states = read_states(date, live_dir=live_dir)
    result = {}
    for row in states:
        game_pk = game_pk_key(row.get("game_pk"))
        if game_pk is not None:
            result[game_pk] = row
    return result


def is_final(row) -> bool:
    """True when a state row represents a final game."""
    return row.get("status") == "Final"


# ---------------------------------------------------------------------------
# Pregame context builder (R16-L2)
# ---------------------------------------------------------------------------
#
# WHY THIS LIVES HERE AND NOT IN live_window.py
# ----------------------------------------------
# `live_window.pregame_context` (D1, D2, D3, D8; docs/LIVE_BETTING_SYSTEM.md
# section 2.3) is broken: it reads `game["teams"]...` and `probablePitcher`
# off a shape `mlb.fetch_games()` never returns (fetch_games returns
# `mlb.parse_game()` records: flat `home_team`/`away_team` abbreviations,
# `home_probable_id`, no `teams` key at all), and it reads
# `consensus.get("home_prob", 0.5)` from `prices.snapshot()`, whose actual
# keys are `sides`, `dispersion`, `label`, `any_positive`, `note` -- there is
# no `home_prob`. Both defects make every favourite/probability read None or
# 0.5, and D3's int/string `game_pk` mismatch means `tick()` then can't even
# find the (broken) context it built.
#
# `live_window.py` is another agent's file for this pass (R16-L3/L4), so the
# fix lives here as a pure function instead, taking every input as an
# argument -- no network, no file reads, nothing global. `live_window.
# pregame_context` becomes correct the moment it delegates to this function;
# see the one-line change named in the R16-L2 report.

def build_pregame_context(games, odds_rows, gamekey_map, now=None) -> dict:
    """The pre-game context `live_window.pregame_context` should return.

    Pure: every input is injected, nothing is fetched or read from disk.

    Args:
        games: `mlb.parse_game()`-shaped records (i.e. `mlb.fetch_games()`'s
            return value) for the slate -- flat `game_pk`, `home_team`/
            `away_team` (club abbreviations), `start_time_utc`,
            `home_probable_id`/`away_probable_id`.
        odds_rows: pre-game multibook quote rows (`odds_multibook.jsonl`
            shape: `event_id`, `home_team`/`away_team` (full club names),
            `commence_time`, `observed_utc`, `book`, `home_price`,
            `away_price`). May include in-play rows for the same event --
            this function filters to strictly pre-game itself (see below) so
            a caller does not have to pre-filter by `commence_time`.
        gamekey_map: `gamekey.load_map()`'s output, `{event_id: resolution
            row}`, each row carrying a `game_pk` in canonical string form
            (`src.core.asof.game_pk_key`). This is the ONLY path from a
            `game_pk` to an `event_id` -- odds rows are never matched to a
            schedule game by team name here (that join belongs to
            `gamekey.resolve_event`, done once, ahead of time).
        now: injected clock (datetime), stamped on every row as
            `context_built_utc` for audit; never used to decide usability.

    Returns:
        `{game_pk (str) -> context}`, one entry per game in `games` that has
        a `game_pk`. Each context is:
            {"sport": "mlb", "game_id": game_pk (str), "event_id": str|None,
             "home_team": str|None, "away_team": str|None,
             "favorite": "home"|"away"|None, "favorite_prob": float|None,
             "book_count": int, "newest_quote_utc": str|None,
             "starter_ids": {"home": id|None, "away": id|None},
             "kickoff_utc": str|None, "context_built_utc": str|None,
             "usable": bool, "reason": str|None}

        `favorite`/`favorite_prob` come straight from
        `prices.snapshot(...)["sides"]["home"]["consensus_probability"]` and
        its away counterpart (D2) -- never re-derived from a field that does
        not exist. `usable=False` always carries a `reason`; nothing here
        pretends a game has a workable context when it does not.

        `starter_ids` is the PREGAME PROBABLE pitcher (the only pitcher
        identity knowable before first pitch) -- see `live_rules.
        _mlb_starter_pulled_early`'s docstring for the contract this feeds
        (D12): a caller wiring this into a live tick loop must overwrite
        `starter_ids` with the pitcher actually observed on defence in the
        first live state row for that side, not leave the probable in place
        once the game has started.
    """
    from src.analysis import prices as prices_mod

    now_utc = _utc_iso(now) if isinstance(now, datetime) else None

    # Invert the gamekey map once: game_pk (canonical string) -> event_id.
    # First mapped event_id wins -- a genuine collision (two events resolved
    # to the same game_pk) is a gamekey-store problem, not this function's to
    # silently arbitrate.
    pk_to_event: dict[str, str] = {}
    for event_id, row in (gamekey_map or {}).items():
        pk = game_pk_key((row or {}).get("game_pk"))
        if pk is not None and pk not in pk_to_event:
            pk_to_event[pk] = str(event_id)

    # Group odds rows by event_id once, rather than re-scanning the whole
    # list per game.
    rows_by_event: dict[str, list] = {}
    for row in odds_rows or []:
        event_id = row.get("event_id")
        if event_id is None:
            continue
        rows_by_event.setdefault(str(event_id), []).append(row)

    context: dict[str, dict] = {}
    for game in games or []:
        game_pk = game_pk_key(game.get("game_pk"))
        if game_pk is None:
            continue

        home_team = game.get("home_team")
        away_team = game.get("away_team")
        kickoff_utc = game.get("start_time_utc")
        starter_ids = {
            "home": game.get("home_probable_id"),
            "away": game.get("away_probable_id"),
        }

        base = {
            "sport": "mlb",
            "game_id": game_pk,
            "home_team": home_team,
            "away_team": away_team,
            "favorite": None,
            "favorite_prob": None,
            "book_count": 0,
            "newest_quote_utc": None,
            "starter_ids": starter_ids,
            "kickoff_utc": kickoff_utc,
            "context_built_utc": now_utc,
        }

        event_id = pk_to_event.get(game_pk)
        if event_id is None:
            context[game_pk] = {
                **base, "event_id": None, "usable": False,
                "reason": "no event_id mapped for this game_pk in the gamekey map",
            }
            continue

        rows = rows_by_event.get(event_id, [])
        if not rows:
            context[game_pk] = {
                **base, "event_id": event_id, "usable": False,
                "reason": "no odds rows found for this event_id",
            }
            continue

        commence_dt = _parse_iso(kickoff_utc) or _parse_iso(
            rows[0].get("commence_time"))
        if commence_dt is None:
            context[game_pk] = {
                **base, "event_id": event_id, "usable": False,
                "reason": "commence_time could not be parsed",
            }
            continue

        # Each book's NEWEST quote observed STRICTLY BEFORE commence_time.
        # Strict: a quote observed exactly at (or after) first pitch is an
        # in-play price, not a pre-game one, and D2 documents what happens
        # when in-play rows leak into a consensus (a point-in-time leak).
        newest_by_book: dict[str, dict] = {}
        for row in rows:
            observed_dt = _parse_iso(row.get("observed_utc"))
            if observed_dt is None or observed_dt >= commence_dt:
                continue
            book = row.get("book")
            if not book:
                continue
            current = newest_by_book.get(book)
            if current is None or (row.get("observed_utc") or "") > (
                    current.get("observed_utc") or ""):
                newest_by_book[book] = row

        pregame_quotes = list(newest_by_book.values())
        if not pregame_quotes:
            context[game_pk] = {
                **base, "event_id": event_id, "usable": False,
                "reason": "no quotes observed strictly before commence_time",
            }
            continue

        newest_quote_utc = max(
            (q.get("observed_utc") or "") for q in pregame_quotes) or None

        consensus = prices_mod.snapshot(pregame_quotes)
        if "skipped" in consensus:
            context[game_pk] = {
                **base, "event_id": event_id,
                "book_count": len(pregame_quotes),
                "newest_quote_utc": newest_quote_utc,
                "usable": False, "reason": consensus["skipped"],
            }
            continue

        sides = consensus.get("sides") or {}
        home_side = sides.get("home") or {}
        away_side = sides.get("away") or {}
        home_prob = home_side.get("consensus_probability")
        away_prob = away_side.get("consensus_probability")

        if home_prob is None and away_prob is None:
            context[game_pk] = {
                **base, "event_id": event_id,
                "book_count": consensus.get("dispersion", {}).get(
                    "books", len(pregame_quotes)),
                "newest_quote_utc": newest_quote_utc,
                "usable": False,
                "reason": "neither side of the board could be priced",
            }
            continue

        # D2: the favourite and its probability are read straight off
        # `sides.home.consensus_probability` / `sides.away.consensus_probability`
        # -- never re-derived (e.g. `max(p, 1 - p)` against a re-devigged
        # number) from a field this dict does not carry.
        if home_prob is not None and (away_prob is None or home_prob >= away_prob):
            favorite, favorite_prob = "home", home_prob
        else:
            favorite, favorite_prob = "away", away_prob

        context[game_pk] = {
            **base, "event_id": event_id, "favorite": favorite,
            "favorite_prob": favorite_prob,
            "book_count": consensus.get("dispersion", {}).get(
                "books", len(pregame_quotes)),
            "newest_quote_utc": newest_quote_utc,
            "usable": True, "reason": None,
        }

    return context


def _parse_iso(value):
    """Parse an ISO-8601 UTC timestamp string to an aware datetime, or None.

    Never raises: a malformed or missing timestamp is an honest "cannot use
    this row", not a crash mid-build.
    """
    if not value or not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _last_rows(path: Path) -> dict:
    """Map game_pk (canonical string, D3) to the last row for each game."""
    last = {}
    for line in _read_lines(path):
        try:
            row = json.loads(line)
            game_pk = game_pk_key(row.get("game_pk"))
            if game_pk is not None:
                last[game_pk] = row
        except json.JSONDecodeError:
            pass
    return last


def _read_lines(path: Path) -> list:
    """Every line in the file that exists."""
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _append(path: Path, rows: list) -> None:
    """Append rows, first newline-terminating any ragged end."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    ragged = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            ragged = handle.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as handle:
        if ragged:
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _utc_iso(moment: datetime) -> str:
    """ISO format UTC timestamp."""
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(
            "the clock must return a timezone-aware datetime")
    return moment.astimezone(timezone.utc).isoformat()


def _to_iso_date(value, clock=None) -> str:
    """Get the date in YYYY-MM-DD format, using ET as the official date."""
    if value is None:
        moment = clock() if clock is not None else datetime.now(timezone.utc)
        if not isinstance(moment, datetime) or moment.tzinfo is None:
            raise ValueError(
                "the clock must return a timezone-aware datetime")
        return moment.astimezone(_EASTERN).date().isoformat()
    if isinstance(value, str):
        return value
    return str(value)
