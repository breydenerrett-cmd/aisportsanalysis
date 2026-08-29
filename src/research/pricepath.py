"""Per-event price paths: every book, every snapshot, joined to the result.

WHY THIS EXISTS
---------------
V1's selection builder answers "what price could a detector have bet, and did
that side win". V2 asks different questions -- how a price MOVED, how far books
disagreed at a moment, whether the T-90 quote forecast better than the T-5 one.
Those need the whole path, not two points from it.

WHAT A PATH IS
--------------
One event. For each book, the ordered sequence of (snapshot_at, away_price,
home_price) strictly before first pitch, plus the realised winner. Prices stay
American and un-de-vigged here on purpose: which de-vig to apply is itself one
of the hypotheses (M5), so baking one in would answer the question before
asking it.

THE POINT-IN-TIME RULE STILL HOLDS
----------------------------------
Every quote is stamped with its own snapshot time and its gap to first pitch,
and quotes at or after first pitch are dropped at read time rather than
filtered downstream. A study that wants only pre-game information gets it by
construction; one that wants a specific window slices on `gap_minutes` and
cannot accidentally reach past zero.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from src.data import parks
from src.pipeline import backfill
from src.pipeline import slate as slate_mod

RESULTS_CSV = Path("data/historical/mlb_results.csv")

# Same reasoning as selections.MAX_EVENT_GAP_SECONDS: a game's own odds event
# agrees with the schedule to within minutes, while the nearest wrong event --
# a doubleheader partner or the next night of the series -- is four-plus hours
# away. Three hours separates the two populations with room on either side.
MAX_EVENT_GAP_SECONDS = 3 * 3600


class PricePathError(RuntimeError):
    """Raised when paths cannot be built honestly."""


def _parse(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def read_results(path=RESULTS_CSV) -> list:
    """Played games with a decided winner, as dicts.

    Games without a final score are dropped rather than defaulted -- an
    undecided game contributes nothing to a calibration study and a zero would
    contribute a lie.
    """
    target = Path(path)
    if not target.exists():
        raise PricePathError(f"results file missing: {target}")
    out = []
    with target.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("home_won") not in ("0", "1"):
                continue
            start = _parse(row.get("start_time_utc"))
            if start is None:
                continue
            out.append({
                "game_pk": row.get("game_pk"),
                "date": row.get("date"),
                "start_time_utc": start,
                "away_team": parks.canonical_team(row.get("away_team")),
                "home_team": parks.canonical_team(row.get("home_team")),
                "home_won": row.get("home_won") == "1",
                "total_runs": _int(row.get("total_runs")),
            })
    return out


def _abbrev(name):
    """Odds-store team name -> canonical abbreviation, or None if unrecognised.

    None rather than a guess: an unmatched name drops the event and shows up in
    the join accounting, where a wrong guess would quietly price one club's
    games off another club's odds.
    """
    if not name:
        return None
    try:
        return parks.canonical_team(slate_mod.team_abbrev_from_name(name))
    except Exception:
        return None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _index_results(results) -> dict:
    """(away, home, date) -> list of games. A list because doubleheaders share a key."""
    index = {}
    for game in results:
        key = (game["away_team"], game["home_team"], game["date"])
        index.setdefault(key, []).append(game)
    return index


def _resolve(candidates, commence_time):
    """The game whose first pitch is closest to this event, if close enough.

    A lone candidate still has to pass the gap check. Skipping it there is how
    V1's price join corrupted itself: a single wrong candidate looks exactly
    like a single right one until you measure.
    """
    if not candidates or commence_time is None:
        return None
    best, best_gap = None, None
    for game in candidates:
        gap = abs((game["start_time_utc"] - commence_time).total_seconds())
        if best_gap is None or gap < best_gap:
            best, best_gap = game, gap
    if best_gap is None or best_gap > MAX_EVENT_GAP_SECONDS:
        return None
    return best


def build(season, store=backfill.DEFAULT_STORE, results=None) -> list:
    """Every event in one season as a price path joined to its outcome.

    Returns a list of dicts:
        event_id, commence_time, away_team, home_team, home_won, total_runs,
        quotes: [{book, snapshot_at, gap_minutes, away_price, home_price}, ...]

    Quotes are sorted by snapshot time. Events that cannot be joined to a
    played game are dropped and counted by `build_report`, never silently
    matched to something nearby.
    """
    return _build(season, store, results)[0]


def build_report(season, store=backfill.DEFAULT_STORE, results=None) -> dict:
    """Same as build(), plus the join accounting.

    The counts matter: a study that quietly loses a third of its games to a
    join failure is measuring a biased subset, and there is no way to notice
    that from the results alone.
    """
    paths, report = _build(season, store, results)
    report["paths"] = paths
    return report


def _build(season, store, results):
    if results is None:
        results = read_results()
    index = _index_results(results)

    events = {}
    unjoined = set()
    snapshots_seen = 0
    quotes_after_start = 0

    for record in backfill.read_season(season, store):
        snapshot_at = _parse(record.get("snapshot_at"))
        if snapshot_at is None:
            continue
        snapshots_seen += 1
        for event in record.get("events") or []:
            start = _parse(event.get("commence_time"))
            if start is None:
                continue
            if snapshot_at >= start:
                quotes_after_start += 1
                continue

            event_id = event.get("id")
            path = events.get(event_id)
            if path is None:
                # The odds store spells teams out ("Seattle Mariners"); the
                # results CSV uses abbreviations. Both ends go through the same
                # two-step so a rename on one side cannot silently unmatch.
                away = _abbrev(event.get("away_team"))
                home = _abbrev(event.get("home_team"))
                if away is None or home is None:
                    unjoined.add(event.get("id"))
                    continue
                game = _resolve(index.get((away, home, start.date().isoformat())),
                                start)
                if game is None:
                    # Odds events are stamped UTC; a night game's local date is
                    # the day before its UTC date, so try that too.
                    previous = (start.date() - dt.timedelta(days=1)).isoformat()
                    game = _resolve(index.get((away, home, previous)), start)
                if game is None:
                    unjoined.add(event_id)
                    continue
                path = events[event_id] = {
                    "event_id": event_id,
                    "commence_time": start,
                    "away_team": away,
                    "home_team": home,
                    "game_pk": game["game_pk"],
                    "date": game["date"],
                    "home_won": game["home_won"],
                    "total_runs": game["total_runs"],
                    "quotes": [],
                }

            gap = (start - snapshot_at).total_seconds() / 60.0
            for book in event.get("bookmakers") or []:
                for market in book.get("markets") or []:
                    if market.get("key") != "h2h":
                        continue
                    prices = {o.get("name"): o.get("price")
                              for o in market.get("outcomes") or []}
                    away_price = prices.get(event.get("away_team"))
                    home_price = prices.get(event.get("home_team"))
                    if away_price is None or home_price is None:
                        continue
                    path["quotes"].append({
                        "book": book.get("key"),
                        "snapshot_at": snapshot_at,
                        "gap_minutes": gap,
                        "away_price": away_price,
                        "home_price": home_price,
                    })

    paths = []
    for path in events.values():
        if not path["quotes"]:
            continue
        path["quotes"].sort(key=lambda q: (q["snapshot_at"], q["book"]))
        paths.append(path)
    paths.sort(key=lambda p: (p["commence_time"], p["event_id"]))

    return paths, {
        "season": season,
        "snapshots_read": snapshots_seen,
        "events_joined": len(paths),
        "events_unjoined": len(unjoined),
        "quotes_dropped_after_start": quotes_after_start,
        "quotes": sum(len(p["quotes"]) for p in paths),
    }


def by_book(path) -> dict:
    """A path's quotes regrouped as book -> chronological quote list."""
    out = {}
    for quote in path["quotes"]:
        out.setdefault(quote["book"], []).append(quote)
    for quotes in out.values():
        quotes.sort(key=lambda q: q["snapshot_at"])
    return out


def snapshots(path) -> list:
    """A path's quotes regrouped as [(snapshot_at, [quote, ...]), ...] in time order.

    This is the cross-sectional view -- every book at one moment -- which is
    what dispersion and consensus questions need.
    """
    grouped = {}
    for quote in path["quotes"]:
        grouped.setdefault(quote["snapshot_at"], []).append(quote)
    return sorted(grouped.items())


def quote_at(path, minimum_gap_minutes):
    """The latest snapshot at least `minimum_gap_minutes` before first pitch.

    Returns (snapshot_at, [quote, ...]) or None. "Latest at least N out" rather
    than "closest to N" because the former is a price the system could have
    acted on at time N, and the latter can be one it could not yet see.
    """
    best = None
    for snapshot_at, quotes in snapshots(path):
        gap = quotes[0]["gap_minutes"]
        if gap < minimum_gap_minutes:
            continue
        if best is None or gap < best[1][0]["gap_minutes"]:
            best = (snapshot_at, quotes)
    return best


def latest_quote(path):
    """The last snapshot before first pitch. Returns (snapshot_at, [quote, ...]) or None."""
    grouped = snapshots(path)
    return grouped[-1] if grouped else None
