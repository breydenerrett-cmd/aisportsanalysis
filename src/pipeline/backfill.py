"""Historical odds backfill: buy each price once, keep it forever.

WHY A LOCAL STORE RATHER THAN REPEATED CALLS
--------------------------------------------
Historical prices do not change. A price from 15 July 2025 is the same price today and
next year, so paying for it twice is pure waste -- and the credits that pay for it come
from a subscription that is meant to be cancelled after one month.

So this fetches once, writes to disk, and records what it fetched. Everything
downstream reads the local files. After the backfill the subscription can lapse and the
research continues unaffected.

RESUMABLE, BECAUSE IT WILL BE INTERRUPTED
-----------------------------------------
Several thousand sequential requests over a metered budget will be interrupted -- by a
timeout, a rate limit, a container going away. A restart that re-fetches everything
would spend the budget twice and might not have twice to spend.

A manifest records every snapshot already stored, keyed by its exact timestamp. Re-running
skips those, so an interrupted backfill resumes rather than restarts.

THE BUDGET IS ENFORCED, NOT ESTIMATED
-------------------------------------
Every response carries the credits remaining on the account. That number is read and
respected on every call, and the run stops when the configured budget is exhausted --
before the request, not after. An estimate that turns out low is a plan; a budget that
is not checked is an overdraft.

WHY CLOSING PRICES ARE APPROXIMATED, AND SAID TO BE
---------------------------------------------------
The cheap historical endpoint answers "what were all the prices at this instant", one
request for the whole slate. It cannot answer "what was each game's price just before
its own first pitch", because games start hours apart.

Getting a true per-game close means the per-event endpoint, billed per game, which costs
more than the whole rest of the backfill. So instead several snapshots a day are taken,
and each game is later matched to the LATEST snapshot strictly before its own start.
That is a good approximation and it is labelled an approximation -- `closing_gap_minutes`
records how stale each matched price is, so a game whose nearest snapshot was two hours
early is visibly different from one caught ten minutes out.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paths import historical_path
from src.providers import odds as odds_provider

DEFAULT_STORE = historical_path("odds_history")

# Historical requests cost ten times a live one, per market per region.
HISTORICAL_MULTIPLIER = 10

# Snapshot times, UTC, chosen against the shape of an MLB day rather than spaced evenly.
# Afternoon games start around 17:00-20:00 UTC, the eastern evening block around
# 23:00, and the west coast around 02:00 the next day. Each time sits just before a
# cluster so the latest-snapshot-before-first-pitch match lands close to the real close.
DEFAULT_SNAPSHOT_TIMES = ("16:50", "22:50", "01:50")

# MLB regular season, roughly. Deliberately wide -- a date with no games costs a request
# and returns an empty slate, which is cheap and simpler than encoding the schedule.
SEASON_START = (3, 20)
SEASON_END = (10, 5)


class BackfillError(RuntimeError):
    """Raised when the backfill cannot run or its store is unreadable."""


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def season_timestamps(season, snapshot_times=DEFAULT_SNAPSHOT_TIMES) -> list:
    """Every UTC instant to sample for one season.

    A 01:50 snapshot belongs to the previous day's slate -- west coast games starting
    at 22:10 local are still in progress. The date arithmetic handles that by simply
    emitting the timestamp on its own calendar day; matching games to snapshots happens
    later and by comparing instants, so nothing depends on which day a snapshot is
    filed under.
    """
    start = datetime(season, *SEASON_START, tzinfo=timezone.utc)
    end = datetime(season, *SEASON_END, tzinfo=timezone.utc)
    stamps = []
    day = start
    while day <= end:
        for clock in snapshot_times:
            hour, minute = (int(part) for part in clock.split(":"))
            stamps.append(day.replace(hour=hour, minute=minute, second=0, microsecond=0))
        day += timedelta(days=1)
    return stamps


def plan(seasons, markets, snapshot_times=DEFAULT_SNAPSHOT_TIMES, regions=1) -> dict:
    """What a backfill would cost, before a credit is spent."""
    per_call = HISTORICAL_MULTIPLIER * len(markets) * regions
    stamps = sum(len(season_timestamps(s, snapshot_times)) for s in seasons)
    return {
        "seasons": list(seasons),
        "markets": list(markets),
        "snapshot_times": list(snapshot_times),
        "snapshots": stamps,
        "credits_per_snapshot": per_call,
        "credits_total": stamps * per_call,
    }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _season_file(store, season) -> Path:
    return Path(store) / f"mlb_{season}.jsonl"


def _manifest_file(store) -> Path:
    return Path(store) / "manifest.json"


def read_manifest(store=DEFAULT_STORE) -> dict:
    target = _manifest_file(store)
    if not target.exists():
        return {"snapshots": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackfillError(f"manifest at {target} is not valid JSON") from exc
    if "snapshots" not in data:
        raise BackfillError(f"manifest at {target} is malformed")
    return data


def write_manifest(manifest, store=DEFAULT_STORE) -> str:
    target = _manifest_file(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return str(target)


def snapshot_key(stamp, markets) -> str:
    """Identity of a stored snapshot.

    Keyed on the markets as well as the instant: a snapshot fetched for h2h alone is
    not the same observation as one fetched for h2h and totals, and treating them as
    interchangeable would make a later run skip work it never did.
    """
    when = stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return f"{when}:{','.join(sorted(markets))}"


def read_season(season, store=DEFAULT_STORE) -> list:
    """Every snapshot stored for one season. Missing file is empty, not an error."""
    target = _season_file(store, season)
    if not target.exists():
        return []
    out = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BackfillError(f"{target}:{number} is not valid JSON") from exc
    return out


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(seasons, markets, snapshot_times=DEFAULT_SNAPSHOT_TIMES,
        budget=None, store=DEFAULT_STORE, on_snapshot=None,
        fetch=None, timeout=30) -> dict:
    """Fetch and store every missing snapshot, inside a credit budget.

    `budget` is a hard ceiling on credits this run may spend. It is checked BEFORE
    each request using the cost of that request, so the ceiling cannot be crossed --
    unlike a check afterwards, which discovers the overspend once it has happened.

    Returns a report. Partial progress is always kept: the manifest and the season
    files are flushed as it goes, so an interruption costs one snapshot at most.
    """
    fetcher = fetch or odds_provider.fetch_historical_odds
    manifest = read_manifest(store)
    per_call = HISTORICAL_MULTIPLIER * len(markets)
    observed_cost = 0

    report = {
        "requested": 0, "fetched": 0, "skipped_cached": 0, "failed": 0,
        "credits_spent": 0, "credits_remaining": None, "stopped_early": None,
        "empty_snapshots": 0, "store": str(store),
    }

    for season in seasons:
        target = _season_file(store, season)
        target.parent.mkdir(parents=True, exist_ok=True)

        for stamp in season_timestamps(season, snapshot_times):
            key = snapshot_key(stamp, markets)
            report["requested"] += 1

            if key in manifest["snapshots"]:
                report["skipped_cached"] += 1
                continue

            # Cost the next request at the most expensive one seen so far, not at the
            # local estimate. The API is the authority on billing, and if it charges
            # more than expected, an estimate-based check keeps approving requests and
            # overruns the budget by exactly the amount it was wrong by.
            next_cost = max(per_call, observed_cost)
            if budget is not None and report["credits_spent"] + next_cost > budget:
                report["stopped_early"] = (
                    f"budget of {budget} credits would be exceeded by the next "
                    f"request ({next_cost} credits); {report['fetched']} snapshots "
                    "stored so far and the run is resumable")
                return report

            try:
                payload, usage = fetcher(stamp, markets=markets, timeout=timeout)
            except odds_provider.OddsProviderError as exc:
                report["failed"] += 1
                # Not recorded in the manifest, so a later run retries it. Recording
                # a failure as done would silently leave a permanent hole.
                if on_snapshot:
                    on_snapshot({"stamp": stamp, "error": str(exc)})
                continue

            events = payload.get("data") or []
            record = {
                # The requested instant, not the key -- splitting the key on ":"
                # truncated it at the hour because the timestamp contains colons.
                "requested_at": stamp.astimezone(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%MZ"),
                "snapshot_at": payload.get("timestamp"),
                "markets": sorted(markets),
                "events": events,
            }
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

            manifest["snapshots"][key] = {
                "season": season,
                "snapshot_at": payload.get("timestamp"),
                "events": len(events),
            }
            write_manifest(manifest, store)

            report["fetched"] += 1
            charged = usage.get("last") or per_call
            observed_cost = max(observed_cost, charged)
            report["credits_spent"] += charged
            if usage.get("remaining") is not None:
                report["credits_remaining"] = usage["remaining"]
            if not events:
                # An off-day. Recorded rather than skipped, so a later run can tell a
                # genuine empty slate from a date that was never fetched.
                report["empty_snapshots"] += 1
            if on_snapshot:
                on_snapshot({"stamp": stamp, "events": len(events),
                             "remaining": usage.get("remaining")})

    return report


# ---------------------------------------------------------------------------
# Closing-price matching
# ---------------------------------------------------------------------------

def closing_prices(season, store=DEFAULT_STORE) -> dict:
    """For each game, the latest stored price strictly before its own first pitch.

    This is the approximation the module docstring warns about, made explicit. Each
    match carries `closing_gap_minutes` -- how stale the price was at first pitch --
    so a game caught ten minutes out is distinguishable from one caught two hours out,
    and an analysis can drop the stale ones rather than averaging them in unknowingly.
    """
    best = {}
    for record in read_season(season, store):
        snapshot_at = _parse(record.get("snapshot_at"))
        if snapshot_at is None:
            continue
        for event in record.get("events") or []:
            start = _parse(event.get("commence_time"))
            if start is None or snapshot_at >= start:
                continue
            event_id = event.get("id")
            gap = (start - snapshot_at).total_seconds() / 60.0
            current = best.get(event_id)
            if current is None or gap < current["closing_gap_minutes"]:
                best[event_id] = {
                    "event_id": event_id,
                    "commence_time": event.get("commence_time"),
                    "home_team": event.get("home_team"),
                    "away_team": event.get("away_team"),
                    "snapshot_at": record.get("snapshot_at"),
                    "closing_gap_minutes": round(gap, 1),
                    "bookmakers": event.get("bookmakers") or [],
                }
    return best


def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# First-five backfill, for named games only
# ---------------------------------------------------------------------------

FIRST_FIVE_MARKETS = ("h2h_1st_5_innings", "totals_1st_5_innings")
FIRST_FIVE_STORE = historical_path("odds_first_five")


def first_five_plan(games, markets=FIRST_FIVE_MARKETS, regions=1) -> dict:
    """What a first-five backfill costs. Billed PER GAME, unlike the featured feed.

    The whole reason this is affordable is that it runs on named games. Three
    seasons of every game would be 145,800 credits; three seasons of the ~10%
    that clear the scanner's talent bar is under 15,000. A scanner that stays
    quiet is what makes its own evidence purchasable.
    """
    # One events lookup per date, at 1 credit, plus the odds per game.
    dates = len({g.get("date") for g in games})
    per_game = HISTORICAL_MULTIPLIER * len(markets) * regions
    return {
        "games": len(games), "dates": dates,
        "credits_per_game": per_game,
        "credits_events": dates,
        "credits_total": len(games) * per_game + dates,
    }


def run_first_five(games, markets=FIRST_FIVE_MARKETS, budget=None,
                   store=FIRST_FIVE_STORE, on_game=None, fetch_events=None,
                   fetch_odds=None, timeout=30) -> dict:
    """Fetch first-five prices for a named list of games.

    Games are matched to Odds API events by team pair on their own date, because
    the two feeds do not share ids. An unmatched game is REPORTED rather than
    skipped -- an unmatched pair is nearly always a team-code mismatch, which has
    silently cost this project data twice before.
    """
    from src.pipeline import slate as slate_mod

    events_for = fetch_events or _historical_events
    odds_for = fetch_odds or _historical_event_odds

    manifest = read_manifest(store)
    target = Path(store)
    target.mkdir(parents=True, exist_ok=True)
    per_game = HISTORICAL_MULTIPLIER * len(markets)

    report = {"requested": len(games), "fetched": 0, "skipped_cached": 0,
              "unmatched": 0, "failed": 0, "unavailable_at_date": 0,
              "credits_spent": 0, "credits_remaining": None,
              "stopped_early": None, "store": str(store)}

    by_date = {}
    for game in games:
        by_date.setdefault(game.get("date"), []).append(game)

    for game_date in sorted(by_date):
        wanted = [g for g in by_date[game_date]
                  if f"{game_date}:{g['away_team']}@{g['home_team']}"
                  not in manifest["snapshots"]]
        report["skipped_cached"] += len(by_date[game_date]) - len(wanted)
        if not wanted:
            continue

        if budget is not None and report["credits_spent"] + 1 > budget:
            report["stopped_early"] = "budget exhausted before the events lookup"
            return report

        try:
            payload, usage = events_for(game_date, timeout=timeout)
            events = payload.get("data") if isinstance(payload, dict) else payload
        except odds_provider.OddsProviderError as exc:
            report["failed"] += len(wanted)
            if on_game:
                on_game({"date": game_date, "error": str(exc)})
            continue
        report["credits_spent"] += usage.get("last") or 1
        if usage.get("remaining") is not None:
            report["credits_remaining"] = usage["remaining"]

        index = {}
        for event in events:
            away = slate_mod.team_abbrev_from_name(event.get("away_team"))
            home = slate_mod.team_abbrev_from_name(event.get("home_team"))
            if away and home:
                index[(away, home)] = event

        for game in wanted:
            key = (game["away_team"], game["home_team"])
            event = index.get(key)
            if not event:
                report["unmatched"] += 1
                if on_game:
                    on_game({"date": game_date, "game": key,
                             "error": "no matching event in the odds feed"})
                continue

            if budget is not None and report["credits_spent"] + per_game > budget:
                report["stopped_early"] = (
                    f"budget of {budget} would be exceeded by the next game "
                    f"({per_game} credits); the run is resumable")
                return report

            try:
                payload, usage = odds_for(game_date, event["id"], markets,
                                          timeout=timeout)
            except odds_provider.MarketsUnavailableAtDate:
                # Not a failure and never retried: first-five history begins in
                # mid-May 2023, so every earlier date answers 422 forever. It is
                # recorded in the manifest so a resumed run does not re-ask, and
                # it costs zero credits either way.
                report["unavailable_at_date"] += 1
                manifest["snapshots"][f"{game_date}:{key[0]}@{key[1]}"] = {
                    "unavailable_at_date": True}
                write_manifest(manifest, store)
                if on_game:
                    on_game({"date": game_date, "game": key,
                             "unavailable": True})
                continue
            except odds_provider.OddsProviderError as exc:
                report["failed"] += 1
                if on_game:
                    on_game({"date": game_date, "game": key, "error": str(exc)})
                continue

            record = {"date": game_date, "away_team": key[0], "home_team": key[1],
                      "game_pk": game.get("game_pk"), "event_id": event["id"],
                      "commence_time": event.get("commence_time"),
                      "snapshot_at": payload.get("timestamp"),
                      "markets": sorted(markets),
                      "data": payload.get("data")}
            path = target / f"mlb_{game_date[:4]}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

            manifest["snapshots"][f"{game_date}:{key[0]}@{key[1]}"] = {
                "event_id": event["id"], "snapshot_at": payload.get("timestamp")}
            write_manifest(manifest, store)

            report["fetched"] += 1
            report["credits_spent"] += usage.get("last") or per_game
            if usage.get("remaining") is not None:
                report["credits_remaining"] = usage["remaining"]
            if on_game:
                on_game({"date": game_date, "game": key,
                         "remaining": usage.get("remaining")})

    return report


def _snapshot_instant(game_date) -> str:
    """The instant to ask about: late evening UTC on the game's own date.

    Games start across a nine-hour spread, so no single instant is every game's
    close. This is deliberately the same approximation the featured backfill
    makes, and `closing_gap_minutes` on the stored record is what lets an
    analysis see how good it was for any given game.
    """
    return f"{game_date}T22:50:00Z"


def _historical_events(game_date, timeout=30):
    return odds_provider._get_json_with_usage(
        f"historical/sports/{odds_provider.SPORT}/events",
        {"apiKey": odds_provider.api_key(), "date": _snapshot_instant(game_date)},
        timeout=timeout)


def _historical_event_odds(game_date, event_id, markets, timeout=30):
    return odds_provider._get_json_with_usage(
        f"historical/sports/{odds_provider.SPORT}/events/{event_id}/odds",
        {"apiKey": odds_provider.api_key(), "regions": odds_provider.DEFAULT_REGION,
         "markets": ",".join(markets), "oddsFormat": odds_provider.ODDS_FORMAT,
         "date": _snapshot_instant(game_date)},
        timeout=timeout)
