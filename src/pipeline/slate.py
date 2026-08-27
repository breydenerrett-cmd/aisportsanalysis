"""Slate assembly: schedule + park + weather + odds into one row per game.

Every field is either populated from a verified source or left blank. There are
no defaults, no interpolation, and no carrying a value forward from a similar
game. A blank column is a signal that downstream code and the coverage report
both act on; a fabricated one is silent corruption that surfaces months later
as a model that backtests well and loses live.

Market probabilities are stored DE-VIGGED. The raw prices are kept alongside
them so nothing is lost, but the probability columns have the bookmaker's
margin removed -- see src/core/odds.py for why comparing against raw implied
probability systematically overstates edge.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.core import odds as odds_math
from src.data import parks
from src.providers import mlb
from src.providers import odds as odds_provider
from src.providers import weather as weather_provider

# Column order for the slate CSV. Explicit rather than derived from a dict so
# the file layout is stable across runs and diffable in version control.
SLATE_COLUMNS = [
    "date", "game_pk", "state", "start_time_utc",
    "away_team", "home_team", "venue",
    "away_probable", "home_probable",
    "park_altitude_m", "park_roof",
    "weather_temp_f", "weather_wind_mph", "weather_wind_from_deg",
    "weather_humidity_pct", "weather_source", "wind_effect", "wind_applicable",
    "ml_book", "ml_away_price", "ml_home_price",
    "ml_away_fair_prob", "ml_home_fair_prob", "ml_margin",
    "rl_book", "rl_away_line", "rl_away_price", "rl_home_line", "rl_home_price",
    "total_book", "total_line", "total_over_price", "total_under_price",
    "away_score", "home_score", "winner", "home_won", "total_runs",
]

# Columns that must be present for a game to be analysable at all. A row
# missing any of these is reported, never silently scored.
REQUIRED_FOR_ANALYSIS = ["ml_away_price", "ml_home_price"]


class SlateError(RuntimeError):
    """Raised when a slate cannot be assembled."""


def build_slate(game_date, include_weather=True, include_odds=True,
                env=None, timeout=20) -> dict:
    """Assemble one date's slate from every available free source.

    Each enrichment step is independent: weather failing does not prevent odds
    from attaching, and missing odds does not discard the schedule. Failures
    are collected into `warnings` so a caller can report exactly what is blank
    and why, rather than presenting an unexplained gap.
    """
    games = mlb.fetch_games(game_date, timeout=timeout)
    rows = [_base_row(game) for game in games]
    warnings = []

    for row, game in zip(rows, games):
        _attach_park(row, warnings)

    if include_weather:
        _attach_weather(rows, warnings, timeout=timeout)

    odds_status = odds_provider.status(env)
    if include_odds and odds_status["configured"]:
        _attach_odds(rows, warnings, env=env, timeout=timeout)
    elif include_odds:
        warnings.append(odds_status["message"])

    return {
        "date": mlb._validate_date(game_date),
        "rows": rows,
        "warnings": warnings,
        "odds_configured": odds_status["configured"],
        "coverage": coverage_report(rows),
    }


def _base_row(game: dict) -> dict:
    row = {column: None for column in SLATE_COLUMNS}
    row.update({
        "date": game["date"],
        "game_pk": game["game_pk"],
        "state": game["state"],
        "start_time_utc": game["start_time_utc"],
        "away_team": game["away_team"],
        "home_team": game["home_team"],
        "venue": game["venue"],
        "away_probable": game["away_probable"],
        "home_probable": game["home_probable"],
        "away_score": game["away_score"],
        "home_score": game["home_score"],
        "winner": game["winner"],
        "home_won": game["home_won"],
        "total_runs": game["total_runs"],
    })
    return row


def _attach_park(row, warnings):
    home = row.get("home_team")
    if not home:
        warnings.append(f"game {row.get('game_pk')}: no home team abbreviation")
        return
    try:
        park = parks.get_park(home)
    except parks.ParkError as exc:
        warnings.append(f"game {row.get('game_pk')}: {exc}")
        return
    row["park_altitude_m"] = park["altitude_m"]
    row["park_roof"] = park["roof"]


def _attach_weather(rows, warnings, timeout=20):
    """Fetch weather for the whole slate in one batched request.

    Fetching park-by-park is 15 requests against a rate-limited endpoint, and
    every retry multiplies the wall-clock. One batched call is both faster and
    far less likely to trip the limiter to begin with.
    """
    targets = []
    for row in rows:
        home, start = row.get("home_team"), row.get("start_time_utc")
        if not home or not start:
            continue
        try:
            targets.append((row, parks.coordinates(home)))
        except parks.ParkError:
            continue  # already reported by _attach_park

    if not targets:
        return

    try:
        payloads = weather_provider.fetch_many(
            [coords for _, coords in targets],
            targets[0][0]["start_time_utc"][:10],
            timeout=timeout,
        )
    except weather_provider.WeatherError as exc:
        warnings.append(f"weather unavailable for the slate: {exc}")
        return

    for (row, _), payload in zip(targets, payloads):
        try:
            reading = weather_provider.extract_hour(
                payload, row["start_time_utc"]
            )
        except weather_provider.WeatherError as exc:
            warnings.append(
                f"weather for {row['away_team']}@{row['home_team']}: {exc}"
            )
            continue

        row["weather_temp_f"] = reading["temp_f"]
        row["weather_wind_mph"] = reading["wind_mph"]
        row["weather_wind_from_deg"] = reading["wind_from_deg"]
        row["weather_humidity_pct"] = reading["humidity_pct"]
        row["weather_source"] = payload.get("_source")

        if reading["wind_from_deg"] is not None:
            effect = parks.wind_effect(row["home_team"], reading["wind_from_deg"],
                                       wind_mph=reading["wind_mph"])
            row["wind_effect"] = effect["direction"]
            row["wind_applicable"] = effect["applicable"]


def _attach_odds(rows, warnings, env=None, timeout=20):
    try:
        payload = odds_provider.fetch_normalized(env=env, timeout=timeout)
    except odds_provider.OddsProviderError as exc:
        warnings.append(f"odds unavailable: {exc}")
        return

    matched = _match_events(rows, payload["events"], warnings)
    for row, event in matched:
        _apply_markets(row, event["markets"])


def _match_events(rows, events, warnings):
    """Pair schedule rows to odds events by team names.

    The odds feed uses full team names; the schedule uses abbreviations. Rather
    than guess at a mapping, match on the abbreviation resolved from the odds
    feed's own team names. Anything unmatched is reported and left blank -- a
    wrong pairing would attach one game's prices to another, which is worse
    than no prices at all.
    """
    pairs = []
    by_key = {}
    for event in events:
        key = _event_key(event)
        if key:
            by_key[key] = event

    for row in rows:
        # Both sides must be canonicalized before comparing. The MLB schedule
        # emits AZ/ATH for Arizona/Athletics; the odds feed's club names
        # resolve to ARI/OAK. Comparing raw abbreviations silently drops every
        # game for those two clubs -- caught live against a real 2026-08-27
        # slate, where Arizona @ San Francisco failed to match despite both
        # teams resolving correctly in isolation.
        key = (parks.canonical_team(row.get("away_team") or ""),
               parks.canonical_team(row.get("home_team") or ""))
        event = by_key.get(key)
        if event is None:
            if row.get("state") != "cancelled":
                warnings.append(
                    f"no odds matched for {row.get('away_team')}@"
                    f"{row.get('home_team')}"
                )
            continue
        pairs.append((row, event))
    return pairs


# Odds feeds emit full club names; the schedule emits abbreviations. This maps
# by the distinctive final word of the club name, which is unique across MLB
# except for the Sox, handled explicitly.
_NAME_TAIL_TO_ABBREV = {
    "orioles": "BAL", "red sox": "BOS", "yankees": "NYY", "rays": "TB",
    "blue jays": "TOR", "white sox": "CWS", "guardians": "CLE",
    "tigers": "DET", "royals": "KC", "twins": "MIN", "astros": "HOU",
    "angels": "LAA", "athletics": "OAK", "mariners": "SEA", "rangers": "TEX",
    "braves": "ATL", "marlins": "MIA", "mets": "NYM", "phillies": "PHI",
    "nationals": "WSH", "cubs": "CHC", "reds": "CIN", "brewers": "MIL",
    "pirates": "PIT", "cardinals": "STL", "diamondbacks": "ARI",
    "rockies": "COL", "dodgers": "LAD", "padres": "SD", "giants": "SF",
}


def team_abbrev_from_name(name):
    """Resolve a full club name to an abbreviation, or None if unrecognized."""
    if not isinstance(name, str) or not name.strip():
        return None
    lowered = name.strip().lower()
    # Longest suffix first so "White Sox" wins over "Sox".
    for tail in sorted(_NAME_TAIL_TO_ABBREV, key=len, reverse=True):
        if lowered.endswith(tail):
            return _NAME_TAIL_TO_ABBREV[tail]
    return None


def _event_key(event):
    away = team_abbrev_from_name(event.get("away_team"))
    home = team_abbrev_from_name(event.get("home_team"))
    return (away, home) if away and home else None


def _apply_markets(row, markets):
    h2h = markets.get("h2h")
    if h2h:
        row["ml_book"] = h2h["book"]
        row["ml_away_price"] = h2h["away_price"]
        row["ml_home_price"] = h2h["home_price"]
        try:
            away_fair, home_fair = odds_math.devig_two_way(
                h2h["away_price"], h2h["home_price"]
            )
            row["ml_away_fair_prob"] = round(away_fair, 6)
            row["ml_home_fair_prob"] = round(home_fair, 6)
            row["ml_margin"] = round(
                odds_math.margin([h2h["away_price"], h2h["home_price"]]), 6
            )
        except odds_math.OddsError:
            # A price the maths rejects leaves the probability blank rather
            # than producing a number nobody can trust.
            pass

    spreads = markets.get("spreads")
    if spreads:
        row["rl_book"] = spreads["book"]
        row["rl_away_line"] = spreads["away_line"]
        row["rl_away_price"] = spreads["away_price"]
        row["rl_home_line"] = spreads["home_line"]
        row["rl_home_price"] = spreads["home_price"]

    totals = markets.get("totals")
    if totals:
        row["total_book"] = totals["book"]
        row["total_line"] = totals["total"]
        row["total_over_price"] = totals["over_price"]
        row["total_under_price"] = totals["under_price"]


# ---------------------------------------------------------------------------
# Coverage and persistence
# ---------------------------------------------------------------------------

def coverage_report(rows) -> dict:
    """Per-column fill rate, plus which games are analysable.

    This is what stops a slate from looking finished when half its columns are
    empty. The report is generated from the data, never asserted.
    """
    total = len(rows)
    filled = {c: sum(1 for r in rows if r.get(c) is not None) for c in SLATE_COLUMNS}
    analysable = sum(
        1 for r in rows
        if all(r.get(c) is not None for c in REQUIRED_FOR_ANALYSIS)
    )
    return {
        "games": total,
        "analysable": analysable,
        "not_analysable": total - analysable,
        "filled": filled,
        "fill_rate": {
            c: (round(n / total, 3) if total else 0.0) for c, n in filled.items()
        },
    }


def write_slate(rows, path) -> str:
    """Write a slate to CSV with a stable column order."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SLATE_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in SLATE_COLUMNS})
    return str(target)


def read_slate(path) -> list:
    """Read a slate CSV back, restoring empty strings to None."""
    target = Path(path)
    if not target.exists():
        raise SlateError(f"slate not found: {target}")
    with target.open(newline="", encoding="utf-8") as handle:
        return [
            {k: (v if v != "" else None) for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]
