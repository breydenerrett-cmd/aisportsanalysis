"""Slate health: one read-only answer to "is today's collection actually working?"

WHY THIS EXISTS
---------------
Forward capture is the only asset in this program that cannot be rebuilt. A
result can be refetched from an archive for years; the price a book was showing
at 18:40 on a Tuesday is gone the moment the day ends. Every other module here
is written on that premise -- snapshots.py appends and never mutates, dense.py
reports missed windows rather than repairing them, rosterwatch.py refuses to
invent a poll it did not make.

What none of them do is notice when collection quietly stops working. The
failures that cost the most evidence are silent: a book drops off the board and
the store still fills; the poller's credentials lapse and `poll()` logs a
warning nobody reads; a container restart kills the schedule and every command
still exits zero. Nothing raises, nothing is empty, and the loss is only visible
weeks later when a study cannot be run. Until now the only check was reading raw
logs, which is a check nobody performs daily.

So this module answers one question over the stores themselves: for a given
slate date, is what we captured what we should have captured? It reads; it never
writes, fetches, or repairs. A monitor that can change the thing it monitors is
not evidence.

THE HONESTY RULE THAT SHAPES EVERY FIELD
-----------------------------------------
An absent store is NOT a healthy store. The tempting implementation reads a
missing file as an empty list, finds zero problems in zero rows, and prints a
clean bill of health for a day on which nothing ran at all -- the exact failure
this module exists to catch. So every store reports `present` separately from
its contents, an unreadable quantity is None rather than 0, and an absent store
raises an anomaly of its own.

The mirror-image trap is the off day. A date with no baseball has no odds, no
lineups and no captures, and that is not degradation. An empty slate is healthy
-- but only when the schedule is known and says the slate is empty. When we
cannot tell "no games" from "no collection", that ambiguity is itself the
finding, and it is reported as one.

WHERE THE SLATE COMES FROM, AND WHY IT IS NEVER THE ODDS
---------------------------------------------------------
The slate is asked of MLB, whose schedule endpoint is free and keyless -- the
same call dense.py already makes before it spends a credit. Inferring the slate
from the odds stores instead was the single most misleading thing this module
did: a denominator built from priced games can only ever count games a book
priced, so the one failure worth catching -- an entire game nobody quoted --
subtracted itself from both sides of the ratio and vanished. The count came out
smaller and the coverage came out perfect. So the odds stores are now a last
resort used only when MLB cannot be reached, and when they are used the report
says the slate is unestablished rather than quoting a number as if it were one.

The same reasoning governs every ratio here: both sides must be counted in the
same identity space or the ratio is not a coverage number. That is why lineups
are matched to the slate by game_pk and quotes are matched to it by club and
first pitch, and why a count with no comparable denominator is printed as a
bare count instead of being divided by whatever number is nearest. "8 of 7
games have a lineup" is not a coverage figure with a small error in it; it is
two unrelated numbers sharing a sentence.

MLB files a game under its EASTERN date, so a 21:40 ET first pitch is on the
same slate as an 13:10 ET one while carrying the next UTC date. The odds stores
timestamp in UTC. Bucketing quotes by UTC date therefore dropped the whole late
West Coast half of every slate -- which is why matching is by game identity and
a first-pitch tolerance, not by string-equal dates.

WHAT "THE USUAL SET" OF BOOKS MEANS
-----------------------------------
The named books are deliberately not a constant. Books enter and leave the odds
API's coverage for commercial reasons, and a hardcoded roster would either cry
wolf forever or need editing by the person least likely to notice. The baseline
is instead derived from the store's own recent history: a book that showed up on
most of the recent days we collected is expected today, and its absence is worth
a sentence. With no prior days in the store there is no baseline, and the field
says so rather than guessing.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paths import data_path
from src.pipeline import ledger as ledger_mod
from src.pipeline import rosterwatch
from src.pipeline.dense import F5_CLOSE_MAX_EVENTS
from src.pipeline.slate import team_abbrev_from_name
from src.providers import mlb

# A capture older than this during a live slate means prices are moving that we
# are not seeing. dense.py takes four captures an hour while games approach, so
# two hours is already eight missed captures -- far past a transient hiccup.
STALE_SNAPSHOT_HOURS = 2

# rosterwatch.poll is meant to run every 10-15 minutes. Forty-five minutes is
# three consecutive missed polls: past coincidence, and wide enough that a
# lineup could post and be seen only in an unusably loose bracket.
WATCH_STALE_MINUTES = 45

# When the slate counts as live. It opens six hours before the first pitch --
# earlier than dense.py's three-hour window on purpose, because the briefing and
# the first snapshots of the day should already be landing by then -- and closes
# four hours after the last first pitch, which covers a long game plus extras.
SLATE_OPENS_HOURS_BEFORE = 6
SLATE_CLOSES_HOURS_AFTER = 4

# Fewer quotes than this on a game makes the row nearly useless downstream: the
# dispersion and de-vig work needs several independent books before a number
# means anything, and two books cannot disagree informatively.
MIN_BOOKS_PER_GAME = 3

# How far back the "usual set" of books is learned from, and how often a book
# must have appeared in that window to be expected today. Half the collected
# days keeps a book that joined mid-window out of the alarm set while still
# catching one that vanished.
BOOK_BASELINE_DAYS = 14
BOOK_USUAL_DAY_FRACTION = 0.5

MARKETS_EXPECTED = ("h2h", "spreads", "totals")

# How far a book's stated first pitch may sit from MLB's before the quote stops
# being about that game. Wide enough for a rounded or slightly revised start,
# far narrower than the ~20 hours between two meetings of the same clubs in a
# series -- which is the collision this tolerance exists to avoid, since a
# matchup is not a unique key across days.
SCHEDULE_MATCH_HOURS = 8

# The slate this program collects prices for: regular season and postseason.
# Spring training and exhibitions appear on the same endpoint, are barely
# priced, and would otherwise fill February and March with "no book quoted this
# game" findings that are all true and all meaningless.
SLATE_GAME_TYPES = mlb.DECISIVE_GAME_TYPES


class HealthError(RuntimeError):
    """Raised when the monitor is asked for something it cannot honestly answer."""


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(date=None, now=None, data_dir=None, ledger_path=None,
           schedule_fetch=None) -> dict:
    """Assemble the health report for one slate date.

    `date` defaults to today in UTC -- the same clock every store timestamps
    with, so the report never straddles two definitions of "today". `data_dir`
    and `ledger_path` exist so tests can point the monitor at a synthetic tree;
    production passes neither and reads the real stores.

    Exactly one thing here leaves the machine: `schedule_fetch`, MLB's free
    keyless schedule endpoint, which supplies the slate the stores are then
    measured against. It costs no odds credits -- dense.py already leans on the
    same call precisely because asking the market what is on tonight would cost
    as much as the capture itself. Tests pass their own callable; nothing else
    fetches, and nothing writes.

    Every section reports what it found AND whether the store it read was there
    at all.
    """
    moment = _now(now)
    day = _iso_date(date, moment)
    root = Path(data_dir) if data_dir is not None else None

    schedule = _schedule_section(day, root, schedule_fetch)
    odds = _odds_section(day, schedule, root)
    markets = _markets_section(day, schedule, root)
    lineups = _lineups_section(day, schedule, root, moment)
    snaps = _snapshot_section(moment, root)
    settlement = _settlement_section(ledger_path)

    live = _slate_live(schedule, moment)
    out = {
        "date": day,
        "generated_utc": moment.isoformat(),
        "slate_live": live,
        "all_games_started": _all_started(schedule, moment),
        "schedule": schedule,
        "odds": odds,
        "markets": markets,
        "lineups": lineups,
        "snapshots": snaps,
        "settlement": settlement,
    }
    out["anomalies"] = _anomalies(out)
    out["healthy"] = not out["anomalies"]
    return out


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _schedule_section(day, root, fetch=None) -> dict:
    """Which games exist on this date, and how confident we are in that.

    Three sources, in falling order of authority:

    1. The slate CSV, when the operator has already built one. It is MLB's own
       schedule written to disk, so it answers offline and deterministically.
    2. MLB's schedule endpoint. Free, keyless, and the reason this section can
       state a true slate at all: it lists the game no book priced, which is
       the failure most worth catching and the one the odds stores structurally
       cannot show.
    3. The odds stores, only if MLB could not be reached -- and then the section
       declares itself unauthoritative, because a count of priced games is not
       a slate and must not be quoted as one.

    Two kinds of game are named but held out of the count: one that will not be
    played (postponed, cancelled, suspended), which no book will settle and no
    lineup will post, and exhibition play, which is barely priced. Counting
    either would manufacture missing-coverage findings that are all true and
    all worthless. Both are reported so the subtraction is visible.
    """
    path = _slate_path(day, root)
    csv_note = None
    if path.exists():
        try:
            rows = _read_csv(path)
        except OSError as exc:
            csv_note = f"slate csv unreadable ({exc}); asked MLB instead"
        else:
            games = {}
            for row in rows:
                key = _key(row.get("away_team"), row.get("home_team"))
                if key is None:
                    continue
                games[key] = {"start": row.get("start_time_utc"),
                              "game_pk": _int(row.get("game_pk"))}
            return _slate_answer("slate_csv", games, note=None)

    # MLB's own schedule. A monitor may not raise: any failure here -- HTTP,
    # DNS, a timeout, junk JSON -- has to degrade into a stated uncertainty,
    # exactly as dense.py refuses to spend when this call fails.
    try:
        records = (fetch or mlb.fetch_schedule)(day)
    except Exception as exc:  # noqa: BLE001 -- see above
        reason = f"{type(exc).__name__}: {exc}"
        return _odds_derived_schedule(day, root, csv_note, reason)

    games, unplayed, exhibition = {}, [], []
    for record in records or ():
        teams = record.get("teams") or {}
        away = ((teams.get("away") or {}).get("team") or {}).get("name")
        home = ((teams.get("home") or {}).get("team") or {}).get("name")
        key = _key(away, home)
        if key is None:
            continue
        if mlb.is_cancelled(record):
            unplayed.append(key)
        elif record.get("gameType") not in SLATE_GAME_TYPES:
            exhibition.append(key)
        else:
            games[key] = {"start": record.get("gameDate"),
                          "game_pk": _int(record.get("gamePk"))}

    held = []
    if unplayed:
        held.append(f"{len(unplayed)} not being played ({_names(unplayed)})")
    if exhibition:
        held.append(f"{len(exhibition)} exhibition")
    note = "; ".join(filter(None, [csv_note,
                                   ("held out of the count: " + ", ".join(held))
                                   if held else None])) or None
    answer = _slate_answer("mlb_schedule", games, note=note)
    answer["unplayed"] = sorted(unplayed)
    answer["exhibition"] = sorted(exhibition)
    return answer


def _slate_answer(source, games, note) -> dict:
    return {
        "source": source, "present": True, "readable": True,
        "games": len(games), "authoritative": True,
        "keys": sorted(games),
        "starts": {k: v["start"] for k, v in games.items()},
        "game_pks": sorted(v["game_pk"] for v in games.values()
                           if v["game_pk"] is not None),
        "note": note, "unplayed": [], "exhibition": [],
    }


def _odds_derived_schedule(day, root, csv_note, reason) -> dict:
    """Last resort: the games the odds stores happened to see for this date.

    Explicitly not authoritative. This can only ever enumerate games somebody
    priced, so it cannot be a denominator -- the number it produces is reported
    as "what was priced", and every ratio that would have used it is withheld
    rather than computed against the wrong base.
    """
    seen = {}
    for row in (_rows_on_day(_snapshot_path(root), day)
                + _rows_on_day(_multibook_path(root), day)):
        key = _key(row.get("away_team"), row.get("home_team"))
        if key is not None:
            seen.setdefault(key, row.get("commence_time"))
    return {
        "source": "odds_stores", "present": False, "readable": True,
        "games": len(seen) or None, "authoritative": False,
        "keys": sorted(seen), "starts": dict(seen), "game_pks": [],
        "unplayed": [], "exhibition": [],
        "note": (f"MLB's schedule could not be reached ({reason}), so the "
                 f"slate is unestablished; the games listed are only those "
                 f"some book priced, and a game nobody priced is invisible"
                 + (f" [{csv_note}]" if csv_note else "")),
    }


def _odds_section(day, schedule, root) -> dict:
    """Books per game on the multi-book board, and who is missing from it."""
    path = _multibook_path(root)
    rows = _multibook_rows(day, root, schedule)
    by_game = {}
    for row in rows:
        key = _key(row.get("away_team"), row.get("home_team"))
        if key is None or not row.get("book"):
            continue
        by_game.setdefault(key, set()).add(row["book"])

    counts = sorted(len(books) for books in by_game.values())
    seen_books = sorted({b for books in by_game.values() for b in books})
    usual, baseline_days = _usual_books(day, root)

    missing_games = []
    if schedule.get("keys"):
        missing_games = [k for k in schedule["keys"] if k not in by_game]

    return {
        "store_present": path.exists(),
        "games_with_odds": len(by_game) if path.exists() else None,
        "games_without_odds": sorted(missing_games),
        "thin_games": sorted(k for k, b in by_game.items()
                             if len(b) < MIN_BOOKS_PER_GAME),
        "books_seen": seen_books,
        "books_per_game_min": counts[0] if counts else None,
        "books_per_game_median": (round(statistics.median(counts), 1)
                                  if counts else None),
        "usual_books": sorted(usual) if usual is not None else None,
        "books_missing": (sorted(usual - set(seen_books))
                          if usual is not None else None),
        "baseline_days": baseline_days,
        "rows": len(rows) if path.exists() else None,
    }


def _usual_books(day, root):
    """The books a normal day carries, learned from prior days in the store.

    Returns (set|None, days_used). None means no baseline exists yet -- a store
    holding only today cannot say which books are usual, and pretending it can
    would either invent absentees or bless a day on which half the board left.
    """
    path = _multibook_path(root)
    if not path.exists():
        return None, 0
    per_day = {}
    for row in _read_jsonl(path):
        stamp = (row.get("commence_time") or "")[:10]
        if not stamp or stamp >= day or not row.get("book"):
            continue
        per_day.setdefault(stamp, set()).add(row["book"])
    days = sorted(per_day)[-BOOK_BASELINE_DAYS:]
    if not days:
        return None, 0
    needed = max(1, int(len(days) * BOOK_USUAL_DAY_FRACTION))
    tally = {}
    for stamp in days:
        for book in per_day[stamp]:
            tally[book] = tally.get(book, 0) + 1
    return {b for b, n in tally.items() if n >= needed}, len(days)


def _markets_section(day, schedule, root) -> dict:
    """Which markets actually landed: h2h breadth, and the capped F5 close."""
    snap_path = _snapshot_path(root)
    rows = _odds_rows(day, root, schedule)
    per_market = {}
    for row in rows:
        market = row.get("market")
        key = _key(row.get("away_team"), row.get("home_team"))
        if not market or key is None:
            continue
        per_market.setdefault(market, set()).add(key)

    # A fraction is only offered when the denominator is a real slate. Dividing
    # priced games by priced games always returns 1.0, which is the most
    # confident way this monitor could lie.
    expected = schedule.get("games") if schedule.get("authoritative") else None
    coverage = {}
    for market in MARKETS_EXPECTED:
        games = len(per_market.get(market, ()))
        coverage[market] = {
            "games": games if snap_path.exists() else None,
            "of_scheduled": (round(games / expected, 3)
                             if snap_path.exists() and expected else None),
        }

    f5_path = _f5_path(root)
    f5_events = None
    if f5_path.exists():
        f5_events = len({r.get("event_id")
                         for r in _slate_rows(_read_jsonl(f5_path), day, schedule)
                         if r.get("event_id")})
    return {
        "snapshot_store_present": snap_path.exists(),
        "coverage": coverage,
        "unexpected_markets": sorted(set(per_market) - set(MARKETS_EXPECTED)),
        "f5": {
            "store_present": f5_path.exists(),
            "events": f5_events,
            "cap": F5_CLOSE_MAX_EVENTS,
        },
    }


def _lineups_section(day, schedule, root, moment) -> dict:
    """Posted lineups seen, and how long since each watch stream last looked.

    The watch stores carry no game date -- only the fetch time -- so a lineup
    belongs to this slate only when its game_pk is on the slate. That
    intersection is what makes the count a coverage numerator: it is drawn from
    the same set as the denominator, so it cannot exceed it.

    Without game_pks there is no such intersection, and the fetch-date proxy
    counts lineups for games that may not be on this slate at all -- which is
    how this section once reported eight of seven games covered, one number
    from the watch store divided by another from the odds stores. When the two
    cannot be compared, the count is published alone and `of_scheduled` is
    None. A bare count nobody can misread beats a ratio everybody will.
    """
    directory = _watch_dir(root)
    streams = {}
    for name, filename in (("probables", rosterwatch.PROBABLES_FILE),
                           ("lineups", rosterwatch.LINEUPS_FILE),
                           ("transactions", rosterwatch.TRANSACTIONS_FILE)):
        path = directory / filename
        markers = [r.get("fetched_utc") for r in _read_jsonl(path)
                   if r.get("poll") and r.get("fetched_utc")]
        last = max(markers) if markers else None
        parsed = _parse(last)
        streams[name] = {
            "store_present": path.exists(),
            "polls": len(markers) if path.exists() else None,
            "last_poll_utc": last,
            "age_minutes": (round((moment - parsed).total_seconds() / 60.0, 1)
                            if parsed else None),
            "path": str(path),
        }

    lineup_path = directory / rosterwatch.LINEUPS_FILE
    if not lineup_path.exists():
        return {"streams": streams, "games_with_posted_lineups": None,
                "off_slate_lineups": None, "attributed_by": None,
                "of_scheduled": None, "coverage_measurable": False}

    pks = set(schedule.get("game_pks") or ())
    # An authoritative empty slate is measurable too: nothing to cover, nothing
    # covered, 0 of 0. It is only the unknown denominator that blocks a ratio.
    measurable = bool(pks) or (schedule.get("authoritative")
                               and schedule.get("games") == 0)

    posted, today = set(), set()
    for row in _read_jsonl(lineup_path):
        if row.get("poll") or row.get("game_pk") is None:
            continue
        if not (row.get("away_lineup") or row.get("home_lineup")):
            continue
        if (row.get("fetched_utc") or "")[:10] == day:
            today.add(row["game_pk"])
        if row["game_pk"] in pks:
            posted.add(row["game_pk"])

    if measurable:
        return {
            "streams": streams,
            "games_with_posted_lineups": len(posted),
            # Lineups fetched today for games that are not on this slate --
            # tomorrow's early board, mostly. Harmless, but it is the surplus
            # that used to be added to the numerator.
            "off_slate_lineups": len(today - pks),
            "attributed_by": "schedule game_pks",
            "of_scheduled": schedule.get("games"),
            "coverage_measurable": True,
        }
    return {
        "streams": streams,
        "games_with_posted_lineups": len(today),
        "off_slate_lineups": None,
        "attributed_by": "fetch date",
        "of_scheduled": None,
        "coverage_measurable": False,
    }


def _snapshot_section(moment, root) -> dict:
    """Age of the newest multi-book capture, whatever date it was for.

    Deliberately not filtered to the slate date: one capture writes rows for
    every upcoming game, so the freshest row in the store is the honest answer
    to "when did we last successfully see the market", which is the question.
    """
    path = _multibook_path(root)
    if not path.exists():
        return {"store_present": False, "newest_utc": None,
                "age_minutes": None, "observations": None}
    stamps = [r.get("observed_utc") for r in _read_jsonl(path)
              if r.get("observed_utc")]
    newest = max(stamps) if stamps else None
    parsed = _parse(newest)
    age = round((moment - parsed).total_seconds() / 60.0, 1) if parsed else None
    return {"store_present": True, "newest_utc": newest,
            "age_minutes": age, "observations": len(stamps)}


def _settlement_section(ledger_path) -> dict:
    """Settlement gaps, straight from the ledger's own status()."""
    path = Path(ledger_path) if ledger_path is not None else Path(
        ledger_mod.DEFAULT_LEDGER)
    if not path.exists():
        return {"store_present": False, "games_recorded": None, "settled": None,
                "pending": None, "unsettled_past_dates": None}
    status = ledger_mod.status(path)
    return {
        "store_present": True,
        "games_recorded": status["games_recorded"],
        "settled": status["settled"],
        "pending": status["pending"],
        "unsettled_past_dates": status["unsettled_past_dates"],
    }


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------

def _anomalies(out) -> list:
    """Plain-English findings, each carrying the number it rests on.

    Ordered store-first: an absent store explains every downstream silence, and
    a reader who sees "the multi-book store is absent" should not then have to
    read eight derived complaints about the day it never captured.
    """
    schedule, odds = out["schedule"], out["odds"]
    markets, lineups = out["markets"], out["lineups"]
    snaps, settle = out["snapshots"], out["settlement"]
    day = out["date"]
    found = []

    # --- stores that are simply not there -------------------------------
    if not odds["store_present"]:
        found.append("The multi-book odds store is absent, so no book coverage "
                     "for this slate can be checked at all.")
    if not markets["snapshot_store_present"]:
        found.append("The odds snapshot store is absent, so market coverage "
                     "(h2h, spreads, totals) is unknown, not zero.")
    for name, stream in lineups["streams"].items():
        if not stream["store_present"]:
            found.append(f"The {name} watch store is absent: no poll history "
                         f"exists to prove we ever looked.")
    if not settle["store_present"]:
        found.append("The forward ledger is absent, so settlement completeness "
                     "cannot be checked.")

    # --- the off-day / dead-collector distinction -----------------------
    if schedule["games"] in (0, None):
        if schedule["authoritative"] and schedule["games"] == 0:
            return found  # A real off day. Everything below would be noise.
        found.append(
            f"No games could be established for {day}: {schedule['note']} -- "
            f"an empty slate and a failed collection look identical from here.")
        return found

    games = schedule["games"]

    # --- can this slate be trusted as a denominator? --------------------
    if not schedule["authoritative"]:
        # Everything downstream still runs -- a thin book count is worth
        # knowing either way -- but no coverage ratio is offered against this
        # number, and the reader is told why before reading any of them.
        found.append(
            f"The slate for {day} could not be established: {schedule['note']}. "
            f"The {games} game(s) below are the ones some book priced, so "
            f"coverage against the real slate is unknown, not complete.")

    # --- odds breadth ---------------------------------------------------
    if odds["store_present"]:
        missing = odds["games_without_odds"]
        if odds["games_with_odds"] == 0 and games:
            # Naming fourteen games individually adds nothing when the answer is
            # "none of them"; the one sentence is the whole finding.
            found.append(f"The multi-book store holds no rows at all for {day}, "
                         f"a slate of {games} games.")
        elif missing:
            found.append(
                f"{len(missing)} of {games} {_slate_noun(schedule)} have no "
                f"quote from any book: {_names(missing)}.")
        if odds["books_missing"]:
            found.append(
                f"{len(odds['books_missing'])} book(s) usually on the board are "
                f"absent today ({', '.join(odds['books_missing'])}), measured "
                f"against {odds['baseline_days']} earlier collected day(s).")
        elif odds["usual_books"] is None and odds["games_with_odds"]:
            found.append(
                "No earlier day exists in the multi-book store, so there is no "
                "baseline to tell a missing book from a normal one.")
        if odds["thin_games"]:
            found.append(
                f"{len(odds['thin_games'])} game(s) carry fewer than "
                f"{MIN_BOOKS_PER_GAME} books: {_names(odds['thin_games'])}.")

    # --- markets --------------------------------------------------------
    h2h = markets["coverage"]["h2h"]["games"]
    if h2h is not None and h2h < games:
        found.append(f"h2h prices cover {h2h} of {games} "
                     f"{_slate_noun(schedule)} ({games - h2h} uncovered).")
    if out["all_games_started"] and markets["f5"]["store_present"] \
            and markets["f5"]["events"] == 0 and games:
        found.append(f"The first-five close store holds no rows for {day} "
                     f"despite {games} games having started (cap is "
                     f"{F5_CLOSE_MAX_EVENTS} events per close pass).")

    # --- lineups and polling --------------------------------------------
    for name, stream in lineups["streams"].items():
        if not stream["store_present"]:
            continue
        age = stream["age_minutes"]
        if age is None:
            found.append(f"The {name} watch store holds no successful poll "
                         f"marker at all.")
        elif age > WATCH_STALE_MINUTES:
            found.append(
                f"The {name} watch stream last polled successfully "
                f"{_hours(age)} ago, past the {WATCH_STALE_MINUTES}-minute "
                f"limit of three missed polls.")

    posted = lineups["games_with_posted_lineups"]
    if posted is not None and not lineups["coverage_measurable"]:
        # Said once, plainly, instead of publishing a shortfall computed from
        # two different populations.
        found.append(
            f"Lineup coverage cannot be measured for {day}: lineups are "
            f"identified by game_pk and this slate carries none, so the "
            f"{posted} posted lineup(s) seen cannot be matched to its games.")
    elif posted is not None and games:
        # Lineups post a few hours out and stagger across a slate, so a partial
        # count mid-afternoon is normal. Zero during a live slate is not, and
        # neither is a shortfall once every game has begun.
        if out["slate_live"] and posted == 0:
            found.append(f"No posted lineup has been seen for any of the "
                         f"{games} games while the slate is live.")
        elif out["all_games_started"] and posted < games:
            found.append(f"Only {posted} of {games} games ever had a posted "
                         f"lineup recorded, though all have started.")

    # --- snapshot staleness ---------------------------------------------
    if snaps["store_present"]:
        age = snaps["age_minutes"]
        if age is None:
            found.append("The multi-book store exists but holds no timestamped "
                         "observation, so capture freshness is unknown.")
        elif out["slate_live"] and age > STALE_SNAPSHOT_HOURS * 60:
            found.append(
                f"The newest multi-book capture is {_hours(age)} old during a "
                f"live slate, past the {STALE_SNAPSHOT_HOURS}-hour limit.")

    # --- settlement ------------------------------------------------------
    if settle["store_present"] and settle["unsettled_past_dates"]:
        dates = settle["unsettled_past_dates"]
        found.append(
            f"{len(dates)} past date(s) in the ledger carry recommendations "
            f"that were never settled: {', '.join(dates)}.")

    return found


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_report(data) -> str:
    """Render the report as plain text. No color, no emoji, one screen."""
    lines = [f"SLATE HEALTH  {data['date']}",
             f"generated {data['generated_utc']}",
             ""]

    schedule = data["schedule"]
    live = {True: "live", False: "not live", None: "unknown"}[data["slate_live"]]
    lines.append(f"schedule    {_num(schedule['games'])} games "
                 f"(source: {schedule['source']}"
                 f"{'' if schedule['authoritative'] else ', NOT AUTHORITATIVE'}"
                 f", slate {live})")
    if schedule["note"]:
        lines.append(f"            note: {schedule['note']}")

    odds = data["odds"]
    lines.append(f"odds        {_num(odds['games_with_odds'])} games with quotes, "
                 f"books/game min {_num(odds['books_per_game_min'])} / median "
                 f"{_num(odds['books_per_game_median'])}")
    lines.append(f"            books seen: "
                 f"{', '.join(odds['books_seen']) or 'none'}")
    if odds["books_missing"]:
        lines.append(f"            missing vs usual: "
                     f"{', '.join(odds['books_missing'])}")

    cov = data["markets"]["coverage"]
    lines.append("markets     " + ", ".join(
        f"{m} {_num(cov[m]['games'])}" for m in MARKETS_EXPECTED))
    f5 = data["markets"]["f5"]
    lines.append("            F5 close "
                 + (f"{f5['events']} events (cap {f5['cap']})"
                    if f5["store_present"]
                    else f"store absent, events unknown (cap {f5['cap']})"))

    lineups = data["lineups"]
    if lineups["coverage_measurable"]:
        lines.append(f"lineups     {lineups['games_with_posted_lineups']} of "
                     f"{lineups['of_scheduled']} slate games have a posted "
                     f"lineup (matched by {lineups['attributed_by']})")
        if lineups["off_slate_lineups"]:
            lines.append(f"            plus {lineups['off_slate_lineups']} "
                         f"fetched today for games not on this slate")
    else:
        lines.append(f"lineups     "
                     f"{_num(lineups['games_with_posted_lineups'])} posted "
                     f"lineup(s) seen, no comparable slate denominator "
                     f"(attributed by {_num(lineups['attributed_by'])})")
    for name, stream in lineups["streams"].items():
        age = ("no poll recorded" if stream["age_minutes"] is None
               else f"{_hours(stream['age_minutes'])} ago")
        lines.append(f"            {name:<13} last poll {age}")

    snaps = data["snapshots"]
    lines.append(f"snapshots   newest capture "
                 + ("no data" if snaps["age_minutes"] is None
                    else f"{_hours(snaps['age_minutes'])} ago")
                 + f" ({_num(snaps['observations'])} rows)")

    settle = data["settlement"]
    lines.append(f"settlement  {_num(settle['settled'])} settled, "
                 f"{_num(settle['pending'])} pending of "
                 f"{_num(settle['games_recorded'])} recorded")

    lines.append("")
    if not data["anomalies"]:
        lines.append("ANOMALIES   none")
    else:
        lines.append(f"ANOMALIES   {len(data['anomalies'])}")
        for item in data["anomalies"]:
            lines.append(f"  - {item}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _slate_live(schedule, moment):
    """True while the slate is running, None when start times are unknown.

    None matters: the staleness alarm is only meaningful during a live slate,
    and firing it on a day whose start times we never learned would be an
    accusation made without evidence.
    """
    starts = [s for s in (schedule.get("starts") or {}).values() if s]
    parsed = [p for p in (_parse(s) for s in starts) if p is not None]
    if not parsed:
        return None if schedule.get("games") else False
    return (min(parsed) - timedelta(hours=SLATE_OPENS_HOURS_BEFORE) <= moment
            <= max(parsed) + timedelta(hours=SLATE_CLOSES_HOURS_AFTER))


def _all_started(schedule, moment):
    """True once every scheduled first pitch has passed; None when unknown.

    Several checks only make sense afterwards -- an empty first-five close store
    at noon is a store waiting for the close pass, not a failure -- so they ask
    this rather than inferring "over" from "not live", which is also true all
    morning.
    """
    starts = [p for p in (_parse(s) for s in
                          (schedule.get("starts") or {}).values()) if p]
    if not starts:
        return None
    return moment > max(starts)


def _key(away, home):
    """Game identity across stores: abbreviations when resolvable, else names.

    The slate CSV stores abbreviations and the odds stores store full club
    names, so one of them has to be translated or nothing ever matches. An
    unresolvable name keeps its raw form rather than being dropped -- it still
    matches itself within its own store, and a silently discarded game would
    understate coverage.
    """
    if not away or not home:
        return None
    return (team_abbrev_from_name(away) or str(away),
            team_abbrev_from_name(home) or str(home))


def _names(keys) -> str:
    return ", ".join(f"{a} @ {h}" for a, h in keys)


def _hours(minutes) -> str:
    if minutes is None:
        return "unknown"
    if minutes < 90:
        return f"{minutes:.0f} min"
    return f"{minutes / 60:.1f} h"


def _num(value):
    return "no data" if value is None else value


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        raise HealthError("now must be a datetime")
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _iso_date(date, moment) -> str:
    if date is None:
        return moment.date().isoformat()
    if isinstance(date, datetime):
        return date.date().isoformat()
    text = str(date).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise HealthError(f"date must be YYYY-MM-DD, got {date!r}") from exc
    return text


def _parse(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_jsonl(path) -> list:
    """Rows of a JSONL store; a corrupt line costs one row, never the file.

    Same tolerance the writers assume -- an interrupted append is the normal
    signature of a killed run, and a monitor that raises on it would go blind
    exactly when something has gone wrong.
    """
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _read_csv(path) -> list:
    import csv
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [{k: (v if v != "" else None) for k, v in row.items()}
                for row in csv.DictReader(handle)]


def _base(root) -> Path:
    return Path(root) if root is not None else data_path()


def _slate_path(day, root) -> Path:
    return _base(root) / "raw" / f"mlb_{day}.csv"


def _snapshot_path(root) -> Path:
    return _base(root) / "processed" / "odds_snapshots.jsonl"


def _multibook_path(root) -> Path:
    return _base(root) / "processed" / "odds_multibook.jsonl"


def _f5_path(root) -> Path:
    return _base(root) / "processed" / "f5_close.jsonl"


def _watch_dir(root) -> Path:
    return _base(root) / "watch"


def _odds_rows(day, root, schedule=None) -> list:
    return _slate_rows(_read_jsonl(_snapshot_path(root)), day, schedule)


def _multibook_rows(day, root, schedule=None) -> list:
    return _slate_rows(_read_jsonl(_multibook_path(root)), day, schedule)


def _rows_on_day(path, day) -> list:
    """Rows whose first pitch falls on this UTC date. A blunt instrument.

    Only for the odds-derived fallback, which has no slate to match against.
    Everywhere else `_slate_rows` is used instead, because MLB files a game
    under its Eastern date: bucketing by UTC date silently drops the late West
    Coast half of every slate into the following day.
    """
    return [r for r in _read_jsonl(path)
            if (r.get("commence_time") or "")[:10] == day]


def _slate_rows(rows, day, schedule) -> list:
    """The rows that belong to this slate's games, matched by identity.

    A club pairing repeats through a series, so the pairing alone is not a key
    across days; it is paired with the scheduled first pitch and a tolerance
    wide enough for a book's rounding but far narrower than the gap between two
    meetings. A row whose time will not parse falls back to the UTC date, which
    is at least no worse than the old behaviour.

    With no authoritative slate there is nothing to match against, so this
    degrades to the UTC-date bucket and the caller has already been told the
    slate is unestablished.
    """
    if not schedule or not schedule.get("authoritative"):
        return [r for r in rows if (r.get("commence_time") or "")[:10] == day]
    starts = {key: _parse(value)
              for key, value in (schedule.get("starts") or {}).items()}
    selected = []
    for row in rows:
        key = _key(row.get("away_team"), row.get("home_team"))
        if key not in starts:
            continue
        wanted, seen = starts[key], _parse(row.get("commence_time"))
        if wanted is None or seen is None:
            if (row.get("commence_time") or "")[:10] == day:
                selected.append(row)
        elif abs((seen - wanted).total_seconds()) <= SCHEDULE_MATCH_HOURS * 3600:
            selected.append(row)
    return selected


def _slate_noun(schedule) -> str:
    return ("scheduled games" if schedule.get("authoritative")
            else "games seen priced")
