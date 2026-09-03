"""Append-only odds snapshot capture. The history IS the data.

WHY THIS EXISTS AND WHY IT CANNOT WAIT
--------------------------------------
Results and stats can be backfilled from decades of archives. Line movement cannot.

There is no free source of "what was this price four hours before first pitch on a Tuesday
last April." Either you were recording at the time or that information is gone permanently.
Every day this job is not running is a day of market data that can never be recovered, which
makes this the one piece of infrastructure whose value depends entirely on starting early.

It also produces the single most important field in the whole project: the CLOSING LINE. Closing
line value -- whether picks were made at better prices than the market settled at -- converges
roughly ten times faster than ROI and is the standard by which this system will eventually be
judged. Every closing price captured now is a graded pick that becomes possible later.

DESIGN: APPEND-ONLY, NEVER MUTATE
---------------------------------
A snapshot is an observation at a moment. Observations are facts and are never edited, merged,
or de-duplicated in place. Storage is JSON Lines: one observation per line, appended, never
rewritten. A corrupt line costs one observation rather than the whole file, and a crashed run
leaves a truncated final line rather than a scrambled dataset.

Prices are never interpolated. If no observation exists for a window, that window is empty and
callers must handle the gap rather than receiving a plausible invention.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core import odds as odds_math
from src.paths import processed_path
from src.providers import odds as odds_provider

DEFAULT_SNAPSHOT_PATH = processed_path("odds_snapshots.jsonl")

# The V3 timing study needs EVERY book's quote at every capture instant, not the
# one preferred book the legacy store keeps. Multi-book rows go to their OWN
# append-only file so nothing that reads odds_snapshots.jsonl sees a new shape.
DEFAULT_MULTIBOOK_PATH = processed_path("odds_multibook.jsonl")

# A snapshot taken after first pitch is not a closing line -- the market has moved on to
# in-play pricing, which is a different product. This margin keeps late-arriving observations
# from being mistaken for the close.
CLOSING_GRACE_SECONDS = 0

# How long a book's own price may sit unchanged before the observation we call
# "the close" is flagged as stale.
#
# WHY THIRTY MINUTES: books repost h2h prices continuously in the hours before
# first pitch, and the feed refreshes them in minutes -- a gap of half an hour
# in the last window before a game is not a quiet market, it is a market this
# book has stopped making (suspended for a lineup scratch, a weather hold, or
# a limit breach). Below roughly this length the gap is indistinguishable from
# ordinary quiet, so a tighter threshold would flag honest closes; much longer
# and a book that went dark before first pitch would still pass as live. The
# flag changes NOTHING about which observation is the close -- the definition
# is frozen -- it only records how much to trust the one we already picked.
CLOSING_STALE_SECONDS = 30 * 60


def _eastern():
    """MLB's official timezone, with a fallback for tzdata-less containers.

    Every regular-season and postseason first pitch falls inside daylight time,
    and the only dates a fixed -04:00 could get wrong are first pitches between
    04:00 and 05:00 UTC -- 11pm Eastern, which baseball does not schedule. So the
    fallback is exact for the games this project sees, and says so rather than
    pretending the zone database is present.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact, not a bug
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


class SnapshotError(RuntimeError):
    """Raised when snapshots cannot be captured, read, or interpreted."""


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture(env=None, path=DEFAULT_SNAPSHOT_PATH, timeout: int = 20,
            now=None, multibook_path=None) -> dict:
    """Fetch current odds and append one observation per game per market.

    Returns a summary. Never raises on a missing key -- an unconfigured system reports
    that and writes nothing, so this is safe to put on a schedule before setup is finished.

    Alongside the legacy one-book rows, every capture ALSO persists the full
    multi-book board -- h2h, spreads, totals, and whatever first-five markets
    the payload carries -- to `multibook_path` (default: odds_multibook.jsonl
    next to the snapshot store). Both stores are written from the SAME
    already-fetched API response -- normalize_event keeps every book under
    `all_books` for every market it parses -- so the
    multi-book store costs ZERO extra API credits; no additional request is made.
    """
    status = odds_provider.status(env)
    if not status["configured"]:
        return {
            "captured": 0, "events": 0, "written_to": None,
            "configured": False, "message": status["message"],
        }

    observed = _timestamp(now)
    try:
        payload = odds_provider.fetch_normalized(env=env, timeout=timeout)
    except odds_provider.OddsProviderError as exc:
        return {
            "captured": 0, "events": 0, "written_to": None,
            "configured": True, "error": str(exc),
        }

    rows = []
    for event in payload["events"]:
        for market_key, market in (event.get("markets") or {}).items():
            rows.append({
                "observed_utc": observed,
                "event_id": event.get("event_id"),
                "commence_time": event.get("commence_time"),
                "away_team": event.get("away_team"),
                "home_team": event.get("home_team"),
                "market": market_key,
                "book": market.get("book"),
                "prices": {k: v for k, v in market.items() if k not in ("book", "last_update")},
                "book_last_update": market.get("last_update"),
            })

    written = append(rows, path=path)

    # Multi-book board, from the same payload. The legacy store above is left
    # byte-identical in format for its existing readers.
    mb_target = _resolve_multibook_path(path, multibook_path)
    mb_rows = multibook_rows(observed, payload["events"])
    mb_written = append(mb_rows, path=mb_target)

    return {
        "captured": written, "events": payload["event_count"],
        "written_to": str(path), "configured": True, "observed_utc": observed,
        "multibook": mb_written, "multibook_path": str(mb_target),
    }


def _resolve_multibook_path(snapshot_path, multibook_path):
    """The multi-book store lives next to the snapshot store it shadows.

    Deriving the default from `path` (rather than hardcoding the production
    file) means a caller who redirects the snapshot store -- tests above all --
    redirects the multi-book store with it, and can never leak rows into the
    real data directory.
    """
    if multibook_path is not None:
        return Path(multibook_path)
    snapshot_path = Path(snapshot_path)
    if snapshot_path == Path(DEFAULT_SNAPSHOT_PATH):
        return Path(DEFAULT_MULTIBOOK_PATH)
    return snapshot_path.parent / "odds_multibook.jsonl"


# Market families the multi-book store knows how to shape a row for. h2h and its
# F5 counterpart carry two prices; spreads/totals (and their F5 counterparts)
# also carry a line. Anything else `all_books` might one day contain is skipped,
# never guessed at.
_H2H_SHAPED_MARKETS = ("h2h", "h2h_1st_5_innings")
_LINE_SHAPED_MARKETS = ("spreads", "spreads_1st_5_innings")
_TOTAL_SHAPED_MARKETS = ("totals", "totals_1st_5_innings")


def _decimal_str(value) -> str:
    """A line/point/total as a decimal STRING, never a float.

    Floats round-trip lossily through JSON for values like 1.5 often enough
    that a downstream reader comparing lines with `==` is one bad game away
    from a false mismatch. A string is copied verbatim, forever.
    """
    return value if isinstance(value, str) else str(value)


def multibook_rows(observed, events) -> list:
    """One row per (event, book, market) from a normalized payload.

    Reads the `all_books` section that odds.normalize_event already carries, so
    this consumes data the capture has ALREADY paid for -- zero extra credits.
    A book quoting only half a market is skipped, never half-recorded.

    h2h rows keep the EXACT legacy shape (no `market` key) for byte-identical
    compatibility with every existing reader (grading, snapshots'
    closing_observation, market_closing_observation, oddspayload). Every other
    market's rows are new and additive, carrying a `market` key so a reader
    that wants to stay h2h-only can filter for it; new rows do not replace or
    reshape anything the legacy readers already see.
    """
    rows = []
    for event in events or []:
        all_books = event.get("all_books") or {}
        for market_key, quotes in all_books.items():
            for quote in quotes or []:
                row = _multibook_row(observed, event, market_key, quote)
                if row is not None:
                    rows.append(row)
    return rows


def _multibook_row(observed, event, market_key, quote):
    base = {
        "observed_utc": observed,
        "event_id": event.get("event_id"),
        "commence_time": event.get("commence_time"),
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
    }

    if market_key in _H2H_SHAPED_MARKETS:
        home_price, away_price = quote.get("home_price"), quote.get("away_price")
        if home_price is None or away_price is None:
            return None
        if market_key != "h2h":
            base["market"] = market_key
        base["book"] = quote.get("book")
        base["book_last_update"] = quote.get("last_update")
        base["home_price"] = home_price
        base["away_price"] = away_price
        return base

    if market_key in _LINE_SHAPED_MARKETS:
        home_line, home_price = quote.get("home_line"), quote.get("home_price")
        away_line, away_price = quote.get("away_line"), quote.get("away_price")
        if None in (home_line, home_price, away_line, away_price):
            return None
        base["market"] = market_key
        base["book"] = quote.get("book")
        base["book_last_update"] = quote.get("last_update")
        base["home_line"] = _decimal_str(home_line)
        base["home_price"] = home_price
        base["away_line"] = _decimal_str(away_line)
        base["away_price"] = away_price
        return base

    if market_key in _TOTAL_SHAPED_MARKETS:
        total = quote.get("total")
        over_price, under_price = quote.get("over_price"), quote.get("under_price")
        if None in (total, over_price, under_price):
            return None
        base["market"] = market_key
        base["book"] = quote.get("book")
        base["book_last_update"] = quote.get("last_update")
        base["total"] = _decimal_str(total)
        base["over_price"] = over_price
        base["under_price"] = under_price
        return base

    return None


def append(rows, path=DEFAULT_SNAPSHOT_PATH) -> int:
    """Append observations as JSON Lines. Never rewrites existing content.

    A run killed mid-write leaves a truncated final line with no newline. Without
    the guard below, the NEXT capture's first row would be appended onto that
    fragment, and `read` would then skip the merged line -- so one crash would
    cost TWO observations, the second of them a perfectly good capture that can
    never be taken again. Terminating the fragment first keeps the damage to the
    one row that was actually interrupted.
    """
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if _ends_ragged(target):
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return len(rows)


def _ends_ragged(target) -> bool:
    """True when the file ends mid-line -- the signature of an interrupted append."""
    target = Path(target)
    if not target.exists() or not target.stat().st_size:
        return False
    with target.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1) != b"\n"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read(path=DEFAULT_SNAPSHOT_PATH, skip_corrupt: bool = True) -> list:
    """Read all observations.

    A truncated final line is the normal signature of a run killed mid-write. With
    `skip_corrupt` that costs one observation instead of the entire history, which is the
    right trade for an append-only log.
    """
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    with target.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                if skip_corrupt:
                    continue
                raise SnapshotError(f"corrupt snapshot on line {number} of {target}")
    return rows


def game_key(away_team, home_team, commence_time) -> tuple:
    """Identity for one scheduled game, stable across observations.

    The day is MLB's OFFICIAL (Eastern) date, not the UTC date of first pitch.
    Keying on the UTC date silently merged two different games: a 20:10 ET
    Saturday night game starts at 00:10 UTC Sunday, so it landed in the same
    bucket as Sunday's 13:35 ET matinee against the same opponent -- and every
    three-game series has that pair. The consequence was not merely a miscount.
    `closing_observation` on the merged series would hand Sunday's settlement
    the last price recorded before Sunday's first pitch, which -- if Sunday
    itself was never snapshotted -- is Saturday's closing price for a different
    game, written onto the evidence row as though it were Sunday's close. This
    module's whole promise is that a missing close stays missing.

    The team fields are canonicalized (see `_canonical_club`) because this
    store and its callers do not agree on team-name SHAPE: `capture` writes
    the odds feed's full club names ('St. Louis Cardinals'), while the
    betting ledger's recommendation rows carry this project's abbreviations
    ('STL'). Comparing those literally never matches, which is why every
    settlement's `closing` field was coming back null even for games with
    thousands of recorded snapshot rows -- the join was failing silently, not
    the data being absent. Canonicalizing both sides here, once, is cheaper
    than teaching every caller to pre-normalize its own team fields.
    """
    return (_canonical_club(away_team), _canonical_club(home_team),
            official_date(commence_time))


def _canonical_club(name):
    """One team field, resolved to this project's canonical abbreviation.

    Two DIFFERENT shapes reach this function depending on the caller: the
    odds feed's full club name ('St. Louis Cardinals'), or this project's own
    abbreviation, sometimes in an alternate spelling ('AZ' for Arizona, 'ATH'
    for the Athletics). Resolution is two-step and reuses the same pair of
    resolvers `pipeline.grading` already relies on for this identical join
    (see `grading._find_series`), rather than adding a second team-name
    mapping that could drift out of sync with theirs:

      1. `slate.team_abbrev_from_name` -- the only resolver that recognizes a
         full club name. Returns None for anything else (already an
         abbreviation, or unrecognized).
      2. `parks.canonical_team` -- folds abbreviation spelling variants onto
         one key. Applied to step 1's result when it matched, otherwise to
         the input as given.

    A name neither step recognizes is returned UPPERCASED rather than as
    None: two different unrecognized inputs must stay distinguishable (a
    shared None would silently fold two unrelated, unmatched games into the
    same bucket), and an uppercased garbage string will never equal a real
    team's abbreviation, so it simply never joins to anything. Unknown stays
    unmatched, never mismatched -- this module's whole promise.

    Imports are local: `slate` does not import `snapshots`, so this is not a
    real cycle, but keeping the edge out of the module-level import list
    keeps that true on purpose rather than by accident.
    """
    if not isinstance(name, str) or not name.strip():
        return name
    from src.data.parks import canonical_team
    from src.pipeline import slate

    abbrev = slate.team_abbrev_from_name(name)
    return canonical_team(abbrev) if abbrev else canonical_team(name)


def official_date(commence_time) -> str:
    """MLB's official calendar date for a first pitch, as YYYY-MM-DD.

    The odds feed timestamps in UTC; MLB files a game under its Eastern date,
    which is the date every other source in this project agrees on. An
    unparseable or absent value degrades to the leading ten characters rather
    than inventing a date.
    """
    if commence_time is None:
        return ""
    text = str(commence_time).strip()
    if len(text) == 10:  # already a bare date; nothing to convert
        return text
    try:
        moment = _parse(text)
    except SnapshotError:
        return text[:10]
    return moment.astimezone(_EASTERN).date().isoformat()


def group_by_game(rows, market: str = "h2h") -> dict:
    """Bucket observations for one market by game, sorted oldest first."""
    grouped = {}
    for row in rows:
        if row.get("market") != market:
            continue
        key = game_key(row.get("away_team"), row.get("home_team"),
                       row.get("commence_time"))
        grouped.setdefault(key, []).append(row)
    for series in grouped.values():
        series.sort(key=lambda r: r.get("observed_utc") or "")
    return grouped


def read_multibook(path=DEFAULT_MULTIBOOK_PATH, skip_corrupt: bool = True) -> list:
    """All multi-book observations. Same resilience rules as `read`."""
    return read(path=path, skip_corrupt=skip_corrupt)


def is_pregame(row) -> bool:
    """True when this observation was taken BEFORE its game's first pitch.

    THE STORE IS NOT PRE-GAME ONLY. A capture is one bulk call for the whole
    board, and the feed keeps listing a game after it starts, so every capture
    moment that falls after a first pitch appends in-play rows for that game --
    on 2026-08-31/09-01, 592 of 5,803 rows, up to 2h50m past first pitch, with
    in-play prices as extreme as -10000/+900. Those rows are honest evidence of
    what the feed said and are kept (the store is append-only), but they are a
    DIFFERENT PRODUCT from the pre-game market, and anything that presents a
    board as a price to shop must exclude them.

    The rule is the same one `closing_observation` uses, and deliberately reads
    the same constant, so the "is this a pre-game observation" question can
    never be answered two different ways in this file.

    A row whose stamps are missing or unparseable is NOT pre-game here. It
    cannot be shown to be, and a board is exactly the place where an
    unverifiable row must not be served as a verified one.
    """
    stamp, start = row.get("observed_utc"), row.get("commence_time")
    if not stamp or not start:
        return False
    try:
        return (_parse(start) - _parse(stamp)).total_seconds() > CLOSING_GRACE_SECONDS
    except SnapshotError:
        return False


def pregame_rows(rows) -> list:
    """`rows` keeping only the observations taken before first pitch.

    Filtering, never rewriting: the store keeps every row it was written, and
    consumers that mean "the pre-game market" say so here.
    """
    return [row for row in rows or [] if is_pregame(row)]


def multibook_quotes(event_id=None, away_team=None, home_team=None, date=None,
                     path=DEFAULT_MULTIBOOK_PATH, rows=None,
                     pregame_only: bool = False) -> list:
    """Quotes for one event, shaped for src/research/eventstudy.measure.

    Filters by event_id when given, otherwise by team names and/or the
    commence date (YYYY-MM-DD). Returns [{ts, book, away_price, home_price}]
    sorted oldest first, where ts is OUR observed_utc -- the eventstudy module
    measures market latency against when WE saw the price, and the book's own
    last_update stays in the store for anyone who needs it.

    `pregame_only` drops in-play observations (see `is_pregame`). It defaults
    to False because this is the raw accessor and eventstudy caps post-start
    quotes itself with the game's start time; every caller that presents a
    BOARD passes True.
    """
    if event_id is None and away_team is None and home_team is None and date is None:
        raise SnapshotError("multibook_quotes needs an event_id, team, or date filter")
    source = read_multibook(path) if rows is None else rows
    if pregame_only:
        source = pregame_rows(source)
    quotes = []
    for row in source:
        if event_id is not None and row.get("event_id") != event_id:
            continue
        if away_team is not None and row.get("away_team") != away_team:
            continue
        if home_team is not None and row.get("home_team") != home_team:
            continue
        if date is not None and (row.get("commence_time") or "")[:10] != date:
            continue
        quotes.append({
            "ts": row.get("observed_utc"),
            "book": row.get("book"),
            "away_price": row.get("away_price"),
            "home_price": row.get("home_price"),
        })
    quotes.sort(key=lambda q: q.get("ts") or "")
    return quotes


# ---------------------------------------------------------------------------
# Derived signals
# ---------------------------------------------------------------------------

def closing_observation(series, commence_time=None):
    """The last observation strictly BEFORE first pitch, with its staleness recorded.

    Returns None when nothing was recorded before the game started. That is a real and common
    outcome -- a job that started mid-season has no closing line for earlier games -- and it
    must stay distinguishable from a captured close, because silently substituting the nearest
    available price would corrupt every CLV number computed from it.

    The returned dict is a COPY of the chosen row with two added fields:

      * `book_stale_seconds` -- how long the book's own price had already been
        standing when we observed it (observed_utc minus book_last_update), or
        None when the row carries no book_last_update. None is not zero: a row
        from before the feed reported last_update simply does not know, and
        inventing a fresh-looking 0 would be a fabricated fact.
      * `book_stale` -- True when that age exceeds CLOSING_STALE_SECONDS, i.e.
        the "closing line" came from a book that had likely stopped quoting.

    WHICH observation is the close does not change -- that definition is frozen,
    and every CLV number already computed stays reproducible. A suspended book
    used to supply a close indistinguishable from a live one; now the row says
    so, and callers can weight or exclude it with the evidence in hand.
    """
    if not series:
        return None
    start = commence_time or series[0].get("commence_time")
    if not start:
        return None
    try:
        cutoff = _parse(start)
    except SnapshotError:
        return None

    before = []
    for row in series:
        stamp = row.get("observed_utc")
        if not stamp:
            continue
        try:
            moment = _parse(stamp)
        except SnapshotError:
            continue
        if (cutoff - moment).total_seconds() > CLOSING_GRACE_SECONDS:
            before.append((moment, row))
    if not before:
        return None
    before.sort(key=lambda pair: pair[0])
    return _with_staleness(before[-1][1])


def _with_staleness(row) -> dict:
    """Copy of `row` carrying `book_stale_seconds` and `book_stale`.

    A copy, not the row itself: the series belongs to the append-only store's
    reader and must keep reading back exactly what was written.

    A book_last_update that is AHEAD of our observation (clock skew between the
    book and us) yields a negative age, which is recorded as-is rather than
    clamped -- skew is evidence about the feed, and hiding it behind a zero
    would make an unexplained reading look like a perfect one.
    """
    closing = dict(row)
    age = None
    stamped = row.get("book_last_update")
    observed = row.get("observed_utc")
    if stamped and observed:
        try:
            age = (_parse(observed) - _parse(stamped)).total_seconds()
        except SnapshotError:
            age = None  # unparseable: unknown, never guessed
    closing["book_stale_seconds"] = age
    closing["book_stale"] = age is not None and age > CLOSING_STALE_SECONDS
    return closing


# ---------------------------------------------------------------------------
# Market-aware close identification
# ---------------------------------------------------------------------------
#
# WHY THIS EXTENDS closing_observation RATHER THAN CHANGING IT
# --------------------------------------------------------------
# closing_observation and group_by_game were ALREADY market-agnostic: neither
# function reads anything but observed_utc, commence_time, and (for
# staleness) book_last_update, and group_by_game's `market` parameter already
# filters on whatever literal string a row's own `market` field carries. So
# spreads and totals -- both captured into odds_snapshots.jsonl alongside
# h2h by the exact same `capture()` call, same shape, same timing -- already
# worked here with zero changes (see tests/test_pipeline_snapshots.py's
# TestGrouping.test_filters_to_the_requested_market, unmodified by this
# lane). What was missing was a name for "the market a caller means" versus
# the literal key the store or the odds feed happens to use for it, and a
# place to look up first-five closes at all: those live in an entirely
# different store (f5_close.jsonl, see pipeline.dense._f5_close_pass) with a
# different row shape (home_price/away_price are top-level fields, not
# nested under `prices` -- see `_with_staleness`'s note that it never reads
# `prices` at all, which is exactly why closing_observation already works on
# either shape unmodified) and the ODDS FEED's own key for the market
# (h2h_1st_5_innings) rather than this project's name for it (first_five,
# matching pipeline.mismatch.MARKET_F5).
#
# closing_observation's and group_by_game's signatures and behaviour are
# UNCHANGED by this section -- see tests/test_closing_markets.py's explicit
# regression test -- so every existing caller (grading._closing_line_value,
# grading._ledger_closing, cli._settlement_closing, cli._settlement_closing's
# regression suite in tests/test_settlement_closing_join.py) keeps working
# exactly as before, byte for byte.

# data/processed/f5_close.jsonl's own path, duplicated from (rather than
# imported from) pipeline.dense.F5_CLOSE_STORE: dense.py imports THIS module
# for `_ends_ragged`, so importing back would be a real cycle, not just an
# inconvenient one. Both name the same literal path; nothing here writes to
# either store, only reads.
DEFAULT_F5_CLOSE_PATH = processed_path("f5_close.jsonl")

# This project's own market names -> the literal string each row's `market`
# field carries in the store that captures it. h2h/spreads/totals all live
# in odds_snapshots.jsonl under their own name already; first_five (this
# project's name for it, matching pipeline.mismatch.MARKET_F5) lives in
# f5_close.jsonl under the odds feed's own key for the same market.
MARKET_STORE_KEY = {
    "h2h": "h2h",
    "spreads": "spreads",
    "totals": "totals",
    "first_five": "h2h_1st_5_innings",
}


def market_series_index(rows, market: str = "h2h") -> dict:
    """`group_by_game`, keyed by this project's market name instead of
    whatever literal string the store or the odds feed uses for it.

    Raises on an unrecognized market rather than silently returning an
    empty index -- an empty index looks identical to "this store holds
    nothing for this market", and a caller's typo must not read as a real
    coverage gap.
    """
    if market not in MARKET_STORE_KEY:
        raise SnapshotError(
            f"unknown market {market!r}; expected one of {sorted(MARKET_STORE_KEY)}")
    return group_by_game(rows, market=MARKET_STORE_KEY[market])


def market_closing_observation(series_index, away_team, home_team, commence_time):
    """(observation, reason) for one game against an index `market_series_index`
    already built. Same PIT rule `closing_observation` always uses -- the
    last observation strictly before the scheduled first pitch -- applied to
    whichever market that index was built for.

    `reason` is set only when `observation` is None, and distinguishes two
    different kinds of gap that a single null would otherwise collapse
    together: `"not_captured"` means this market's store holds not one
    observation of this game (the game was never on a board this store
    watched -- often because the store was not yet running for its date, as
    with f5_close.jsonl's first few weeks); `"no snapshot observed before
    first pitch"` means it holds observations, but every one of them arrived
    at or after the scheduled start, same as `closing_observation` reports
    for h2h. A missed window stays missing either way -- this never
    substitutes a nearby price for either kind of gap.
    """
    key = game_key(away_team, home_team, commence_time)
    series = series_index.get(key)
    if not series:
        return None, "not_captured"
    observation = closing_observation(series, commence_time)
    if observation is None:
        return None, "no snapshot observed before first pitch"
    return observation, None


def movement(series, side: str = "home_price") -> dict:
    """Opening price, closing price, and the drift between them for one side.

    `observations` counts how many times the market was actually sampled. A large move measured
    across two observations twelve hours apart is not the same evidence as the same move seen
    across twenty, and reporting the count keeps that distinction visible.
    """
    prices = []
    for row in series:
        value = (row.get("prices") or {}).get(side)
        if value is not None:
            prices.append((row.get("observed_utc"), value))
    if not prices:
        return {"observations": 0, "opening": None, "closing": None,
                "moved": None, "direction": None}

    opening_time, opening = prices[0]
    closing_time, closing = prices[-1]

    try:
        opening_prob = odds_math.american_to_probability(opening)
        closing_prob = odds_math.american_to_probability(closing)
        prob_shift = closing_prob - opening_prob
    except odds_math.OddsError:
        prob_shift = None

    return {
        "observations": len(prices),
        "opening": opening, "opening_utc": opening_time,
        "closing": closing, "closing_utc": closing_time,
        "moved": closing - opening,
        "implied_prob_shift": round(prob_shift, 6) if prob_shift is not None else None,
        "direction": "toward" if closing < opening else ("away" if closing > opening else "flat"),
    }


def closing_line_value(pick_price, closing_price) -> dict:
    """How much better the taken price was than where the market closed.

    Positive CLV means the bet was placed at a better number than the market settled on. This
    is the metric that judges the system long before ROI says anything reliable, because it
    measures whether real inefficiency was found rather than whether the coin landed right.

    Expressed two ways: in cents of American odds, and as the difference in implied probability,
    which is the comparable figure across favorites and underdogs.
    """
    pick_prob = odds_math.american_to_probability(pick_price)
    close_prob = odds_math.american_to_probability(closing_price)
    return {
        "pick_price": pick_price,
        "closing_price": closing_price,
        "cents": closing_price - pick_price,
        "prob_edge": round(close_prob - pick_prob, 6),
        "beat_close": close_prob > pick_prob,
    }


def coverage(rows) -> dict:
    """How complete the snapshot history is. Surfaces gaps rather than hiding them."""
    if not rows:
        return {"observations": 0, "games": 0, "with_closing": 0,
                "closing_rate": 0.0, "first_utc": None, "last_utc": None}

    grouped = group_by_game(rows)
    with_closing = sum(
        1 for series in grouped.values() if closing_observation(series) is not None
    )
    stamps = sorted(r["observed_utc"] for r in rows if r.get("observed_utc"))
    return {
        "observations": len(rows),
        "games": len(grouped),
        "with_closing": with_closing,
        "closing_rate": round(with_closing / len(grouped), 3) if grouped else 0.0,
        "first_utc": stamps[0] if stamps else None,
        "last_utc": stamps[-1] if stamps else None,
    }


def _timestamp(now=None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _parse(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise SnapshotError(f"timestamp must be a string, got {value!r}")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SnapshotError(f"could not parse timestamp {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
