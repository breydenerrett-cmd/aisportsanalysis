"""Assemble THE CARD for one date from the stores. Read-only.

`src.analysis.daily_card` is the rule and the wording; it takes plain data
and touches nothing. This module is the plumbing that goes and gets that
data: slate entries, the moneyline board, the run-line board, the fitted
calibration, and the model line per game.

Read-only by construction. It fetches nothing from a network -- entries
arrive as an argument from whichever caller already built them (the API
cache, or the CLI) -- and it writes nothing. Publishing the card to the
frozen ledger is `src.appstate.card_ledger`'s job, deliberately kept
separate so that rendering a page can never append evidence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from src.analysis import calibrate, daily_card, gamepayload, grade, strength
from src.analysis import prices as prices_mod
from src.appstate import freshness
from src.core import odds as odds_math
from src.detect import dossier as dossier_mod
from src import joins as joins_mod

# Long enough that a page refresh never re-parses the odds store, short
# enough that a fresh capture reaches the card within one cadence slot
# (capture runs every 15 minutes).
RUNLINE_CACHE_TTL_S = 300

CALIBRATION_STORE = os.path.join("data", "processed", "card_calibration.json")

# HOW LATE THE CARD IS ALLOWED TO FREEZE, and therefore how early it is NOT.
#
# The afternoon pass is scheduled at 21:10Z (5:10pm ET) precisely because
# lineups are posted by then. It is also dispatched on a ~30-minute loop by
# an external scheduler, which means without this gate the FIRST run after
# the UTC date rolls over -- 00:25Z, which is 8:25pm ET the evening BEFORE
# -- would freeze the card. `publish` is idempotent per date, so that first
# run wins the whole day.
#
# A card frozen the night before is built on the thinnest board of the day,
# with no posted lineups and some starters unconfirmed, and then presented
# to a reader for the next twenty hours as "what we committed to before
# first pitch". Technically true. Substantively the worst version of the
# product.
#
# So the freeze waits until the day's earliest open game is within this many
# hours of first pitch. The PAGE is unaffected and shows a live card all day
# -- see `card_for_date` -- clearly marked as not locked in yet.
CARD_FREEZE_LEAD_HOURS = 4.0

# The main run line. Alternates are a different bet and are not considered
# here: the card publishes one standard, quotable number per game, and
# "Padres -1.5" is a bet a reader can find at any book on the list.
RUN_LINE = 1.5

# Run-line rows come from the same multibook store as the moneyline, and the
# same floor applies -- a consensus over fewer books is that handful's
# opinion, not a market's.
MIN_BOOKS = prices_mod.MIN_BOOKS


def load_calibration(path: str = CALIBRATION_STORE) -> Optional[calibrate.Calibration]:
    """The Platt fit written by `scripts/fit_card_calibration.py`, or None.

    None is a real answer and callers must handle it: an uncalibrated model
    says 73% about games that happen 60% of the time, so a card built
    without this file has to say so rather than quietly publish the raw
    number. `card_for_date` sets `calibrated: False` in that case.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, ValueError):
        return None
    try:
        return calibrate.Calibration(
            float(blob["a"]), float(blob["b"]), int(blob["n"]),
            float(blob.get("base_rate", 0.5)))
    except (KeyError, TypeError, ValueError):
        return None


# CACHED, and the caching is not an optimisation -- it is a fix.
#
# `bullpen.read_log()` parses data/historical/bullpen_log.jsonl, which is
# 4.2 MB and 18,365 rows, and `relief_rates_by_team` walks all of it. The
# first version of `relief_rates_for` did both on EVERY /card request, on a
# container sized for a read-only page render. Staging went 503 within an
# hour of that shipping.
#
# Keyed by date because the rates change once a day by construction (they
# are "strictly before this date"), and bounded because an unbounded dict
# keyed by a path parameter is a memory leak a caller controls.
_RELIEF_CACHE: dict = {}
_RELIEF_CACHE_MAX = 8
_RELIEF_LOG: list = []
_RELIEF_LOG_LOADED = False


def _relief_log() -> list:
    """The bullpen log, read at most once per process."""
    global _RELIEF_LOG, _RELIEF_LOG_LOADED
    if _RELIEF_LOG_LOADED:
        return _RELIEF_LOG
    from src.pipeline import bullpen

    try:
        _RELIEF_LOG = bullpen.read_log() or []
    except Exception:  # noqa: BLE001 -- a corrupt log is a gap, not a 500
        _RELIEF_LOG = []
    _RELIEF_LOG_LOADED = True
    return _RELIEF_LOG


def relief_rates_for(date: str) -> dict:
    """`{team: runs allowed per nine in relief}` strictly before `date`.

    The real bullpen, replacing the team's whole-season runs-allowed rate
    that `strength.run_means` used to stand in with -- a rate that includes
    the club's own starters, so the rotation was counted twice and every
    bullpen was dragged toward its own rotation.

    Measured out of sample over 710 games (`scripts/test_bullpen_rate.py`):
    moneyline log-loss improves by 0.00216 nats, in both halves of the
    window. That is nearly twice the model's entire gain over a home-field
    base rate, from removing one stand-in.

    Absent-safe. An unreadable log yields {} and the model falls back to
    exactly what it did before, which is stated on the payload as
    `bullpen_known: false` rather than passed over.
    """
    from src.pipeline import bullpen

    cached = _RELIEF_CACHE.get(date)
    if cached is not None:
        return cached

    log = _relief_log()
    if not log:
        return {}
    try:
        rates = {team: row.get("rate")
                 for team, row in bullpen.relief_rates_by_team(log, date).items()
                 if row.get("rate")}
    except Exception:  # noqa: BLE001
        return {}

    if len(_RELIEF_CACHE) >= _RELIEF_CACHE_MAX:
        # Oldest key out. Insertion order is date order in practice and the
        # cap is small enough that a smarter policy would cost more than it
        # saves.
        _RELIEF_CACHE.pop(next(iter(_RELIEF_CACHE)), None)
    _RELIEF_CACHE[date] = rates
    return rates


def _flatten(entry) -> dict:
    """One entry's `teams` and `starters` sections as a single feature dict.

    `src.analysis.strength` reads the same key names `src.pipeline.features`
    emits, which is what lets one model serve both the live slate and the
    backtest without a translation layer that could drift between them.
    """
    dossier = entry.get("dossier")
    payload = (dossier.to_dict() if isinstance(dossier, dossier_mod.Dossier)
               else (dossier or {}))
    sections = payload.get("sections") or {}
    flat = {}
    for name in ("teams", "starters"):
        section = sections.get(name)
        if isinstance(section, dict):
            flat.update(section)
    return flat


def _game_identity(entry, *, date: str) -> dict:
    from src.pipeline import slate as slate_mod

    dossier = entry.get("dossier")
    payload = (dossier.to_dict() if isinstance(dossier, dossier_mod.Dossier)
               else (dossier or {}))
    game = payload.get("game") or {}
    away, home = game.get("away_team"), game.get("home_team")
    # DELEGATED, NOT DUPLICATED (fixed 2026-09-16, Stage 18 join-integrity
    # audit). This used to hand-roll `f"{away}-{home}-{date}-{number}"` --
    # raw team names, always appending a marker (defaulting to 1 when
    # `game_number` was absent). `src.analysis.opportunities.build_opportunities`
    # keys its moneyline rows on `gamepayload.game_id(game)`, which slugs the
    # names and appends a marker ONLY when `game_number` or `game_pk` is
    # present. The two constructions happened to agree on every real game
    # checked (every 2026-09-16 slate entry carries `game_number: 1`, so both
    # sides append "-1"), but a game missing BOTH `game_number` and
    # `game_pk` would get no suffix from `gamepayload.game_id` while this
    # function still appended "-1" -- a silent id mismatch that would make
    # `daily_card.build_pick_candidates` find zero moneyline rows for that
    # game and the card would report it as unpriced. Calling the same
    # function both sides call removes the chance of the two drifting
    # again; `game.get("date")` also has to agree with the `date` argument
    # here, which is why it defaults to it below.
    game_for_id = game if game.get("date") else {**game, "date": date}
    return {
        "game_id": gamepayload.game_id(game_for_id),
        "game_pk": game.get("game_pk"),
        "event_id": game.get("event_id"),
        "date": date,
        "away_team": away,
        "home_team": home,
        # Nicknames, not abbreviations: the card's whole job is to say "Take
        # Padres -1.5", and "Take SD -1.5" is a different, worse sentence.
        "away_name": slate_mod.team_nickname(away),
        "home_name": slate_mod.team_nickname(home),
        "away_probable": game.get("away_probable"),
        "home_probable": game.get("home_probable"),
        "first_pitch_utc": game.get("start_time_utc"),
        "venue": game.get("venue"),
        "state": game.get("state"),
        "features": _flatten(entry),
    }


def _has_started(first_pitch_utc, now: datetime) -> bool:
    """True when first pitch is at or before `now`.

    A game that has started is not a pick, and this is the check that the
    2026-09-09 slip was missing when it published 21 in-progress games as
    live recommendations. Unknown first-pitch time counts as STARTED, not as
    pregame: a partial schedule must fail closed.
    """
    if not first_pitch_utc:
        return True
    try:
        when = datetime.fromisoformat(str(first_pitch_utc).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= now.astimezone(timezone.utc)


# THE OTHER THING THAT WAS READ ON EVERY REQUEST, and the bigger one.
#
# `run_line_rows` called `snapshots.read_multibook()` with no caching, and
# that parses data/processed/odds_multibook.jsonl -- 38 MB and 119,000 rows
# -- into Python dicts. On a 512 MB staging container serving a read-only
# page, one request could allocate several hundred megabytes of short-lived
# objects; two at once could not. Staging went 503 within an hour of this
# shipping and the deploy's own health check had passed on the way in,
# because nothing had requested a card yet.
#
# Cached per date behind the same single-flight TTL cache api/games.py uses
# for its slate builds, so a burst of requests for one date shares one parse
# instead of each paying for it.
_RUNLINE_CACHE = freshness.SingleFlightTTLCache(ttl_s=RUNLINE_CACHE_TTL_S)


def run_line_rows(date: str, *, rows=None, run_line: float = RUN_LINE) -> dict:
    """Cached wrapper. `rows` given explicitly bypasses the cache, because a
    caller injecting its own rows is a test and must not see another test's
    result."""
    if rows is not None:
        return _run_line_rows_uncached(date, rows=rows, run_line=run_line)
    try:
        value, _meta = _RUNLINE_CACHE.get(
            ("run_lines", date, run_line),
            lambda: _run_line_rows_uncached(date, rows=None, run_line=run_line))
        return value
    except Exception:  # noqa: BLE001 -- an unreadable store is a gap, and a
        # card with no alternatives is a real state; a 500 is not.
        return {}


def _run_line_rows_uncached(date: str, *, rows=None,
                            run_line: float = RUN_LINE) -> dict:
    """{game_id: {"away": {...}, "home": {...}}} for the standard run line.

    Built from the same multibook store and the same `prices.snapshot` the
    moneyline uses -- one de-vig, one book floor, one definition of best
    price. Nothing market-specific is invented here.

    The store carries BOTH sides of a spread on one row (`home_line`/
    `home_price`, `away_line`/`away_price`), so none of the 2026-09-09
    pairing problem applies: there is no pairing decision to get wrong. Rows
    at any line other than the standard one are skipped rather than pooled
    into it -- Padres -1.5 and Padres -2.5 are different bets and averaging
    them would produce a fair price for neither.
    """
    from src.pipeline import slate as slate_mod
    from src.pipeline import snapshots

    # FILTERED WHILE READING, never materialised. The store is 38 MB and
    # 119,000 rows and this needs a few hundred of them -- see
    # `snapshots.iter_multibook` for what building the whole list did to a
    # 512 MB container. `rows` given explicitly is a test injecting its own
    # data and is filtered in memory as before.
    if rows is None:
        source = (r for r in snapshots.iter_multibook(market="spreads")
                  if snapshots.official_date(r.get("commence_time")) == date
                  and snapshots.is_pregame(r))
    else:
        source = (r for r in snapshots.pregame_rows(rows)
                  if r.get("market") == "spreads"
                  and snapshots.official_date(r.get("commence_time")) == date)

    grouped = {}
    for row in source:
        try:
            home_line = float(str(row.get("home_line")))
            away_line = float(str(row.get("away_line")))
        except (TypeError, ValueError):
            continue
        if abs(abs(home_line) - run_line) > 1e-9 or abs(home_line + away_line) > 1e-9:
            continue
        away = slate_mod.team_abbrev_from_name(row.get("away_team") or "")
        home = slate_mod.team_abbrev_from_name(row.get("home_team") or "")
        if not away or not home:
            continue
        key = (away, home, date, home_line)
        grouped.setdefault(key, []).append(row)

    out = {}
    for (away, home, day, home_line), group in grouped.items():
        quotes = prices_mod.latest_instant([
            {"ts": r.get("observed_utc"), "book": r.get("book"),
             "away_price": r.get("away_price"), "home_price": r.get("home_price")}
            for r in group])
        if not quotes:
            continue
        snap = prices_mod.snapshot(quotes)
        if snap.get("skipped"):
            continue
        sides = snap.get("sides") or {}
        detail = {}
        for side in ("away", "home"):
            info = sides.get(side) or {}
            if info.get("skipped") or info.get("best_price") is None:
                continue
            detail[side] = {
                "best_price": info.get("best_price"),
                "best_book": info.get("best_book"),
                "consensus_probability": info.get("consensus_probability"),
                "books": (snap.get("dispersion") or {}).get("books"),
                "line": home_line if side == "home" else -home_line,
                "observed_utc": quotes[0].get("ts"),
            }
        if detail:
            # Doubleheaders share a matchup key here; game 1 is the only one
            # the standard board covers on this store, so the key is the
            # single-game shape the entries produce.
            out[f"{away}-{home}-{day}-1"] = detail
    return out


# TOTALS ROWS ARE CACHED THE SAME WAY THE RUN-LINE ROWS ARE, and for the
# same reason: the multi-book store is large and this reads it once per date
# per TTL window rather than once per request. `rows` given explicitly (a
# test's own injected store) bypasses the cache for the same reason
# `run_line_rows` bypasses it -- a caller supplying its own rows must not see
# another test's cached result.
_TOTALS_CACHE = freshness.SingleFlightTTLCache(ttl_s=RUNLINE_CACHE_TTL_S)


def total_rows(date: str, *, rows=None) -> dict:
    """Cached wrapper around `_total_rows_uncached`. See `run_line_rows`."""
    if rows is not None:
        return _total_rows_uncached(date, rows=rows)
    try:
        value, _meta = _TOTALS_CACHE.get(
            ("totals", date), lambda: _total_rows_uncached(date, rows=None))
        return value
    except Exception:  # noqa: BLE001 -- an unreadable store is a gap, and a
        # card with no total picks is a real state; a 500 is not.
        return {}


def _total_rows_uncached(date: str, *, rows=None) -> dict:
    """{game_id: {"line", "over": {...}, "under": {...}, "books",
    "observed_utc"}} -- one entry per game, at that game's own CONSENSUS
    line.

    Unlike the run line (`_run_line_rows_uncached`), a total has no fixed
    standard to filter to: 8.5 in Coors Field is a different bet from 8.5 at
    Petco, and the number itself is what the board is pricing. So rather
    than skip every line but one, this groups each book's NEWEST quote by
    the line IT is currently posting, and takes the line the MOST books
    currently agree on -- ties broken toward the lower number, arbitrarily
    but deterministically, since a tie is rare and nothing downstream should
    depend on dict iteration order deciding it. Books quoting a different
    line are simply not part of this de-vig -- exactly the same choice
    `_run_line_rows_uncached` makes by skipping non-standard lines, applied
    to a number that has to be discovered per game instead of declared once.
    """
    from src.pipeline import slate as slate_mod
    from src.pipeline import snapshots

    if rows is None:
        source = (r for r in snapshots.iter_multibook(market="totals")
                  if snapshots.official_date(r.get("commence_time")) == date
                  and snapshots.is_pregame(r))
    else:
        source = (r for r in snapshots.pregame_rows(rows)
                  if r.get("market") == "totals"
                  and snapshots.official_date(r.get("commence_time")) == date)

    grouped: dict = {}
    for row in source:
        away = slate_mod.team_abbrev_from_name(row.get("away_team") or "")
        home = slate_mod.team_abbrev_from_name(row.get("home_team") or "")
        if not away or not home:
            continue
        try:
            line = float(str(row.get("total")))
        except (TypeError, ValueError):
            continue
        grouped.setdefault((away, home, date), []).append((line, row))

    out = {}
    for (away, home, day), entries in grouped.items():
        # Each book's newest quote, at the line IT posted it at.
        by_book: dict = {}
        for line, row in entries:
            book = row.get("book")
            if not book:
                continue
            ts = row.get("observed_utc") or ""
            held = by_book.get(book)
            if held is None or ts > held[0]:
                by_book[book] = (ts, line, row)

        by_line: dict = {}
        for _ts, line, row in by_book.values():
            by_line.setdefault(line, []).append(row)
        if not by_line:
            continue
        # Most books, ties toward the lower number -- see the docstring.
        consensus_line = max(by_line, key=lambda l: (len(by_line[l]), -l))
        group = by_line[consensus_line]

        quotes = prices_mod.latest_instant([
            {"ts": r.get("observed_utc"), "book": r.get("book"),
             "away_price": r.get("over_price"), "home_price": r.get("under_price")}
            for r in group])
        if not quotes:
            continue
        snap = prices_mod.snapshot(quotes)
        if snap.get("skipped"):
            continue
        sides = snap.get("sides") or {}
        over_info, under_info = sides.get("away") or {}, sides.get("home") or {}
        if (over_info.get("skipped") or under_info.get("skipped")
                or over_info.get("best_price") is None
                or under_info.get("best_price") is None):
            continue

        out[f"{away}-{home}-{day}-1"] = {
            "line": consensus_line,
            "over": {
                "best_price": over_info.get("best_price"),
                "best_book": over_info.get("best_book"),
                "consensus_probability": over_info.get("consensus_probability"),
            },
            "under": {
                "best_price": under_info.get("best_price"),
                "best_book": under_info.get("best_book"),
                "consensus_probability": under_info.get("consensus_probability"),
            },
            "books": (snap.get("dispersion") or {}).get("books"),
            "observed_utc": quotes[0].get("ts"),
        }
    return out


def moneyline_rows(opportunity_rows: Sequence) -> dict:
    """{game_id: {"away": row, "home": row}} from opportunities rows."""
    out = {}
    for row in opportunity_rows or ():
        gid, side = row.get("game_id"), row.get("side")
        if not gid or side not in ("away", "home"):
            continue
        if row.get("market") != "h2h":
            continue
        out.setdefault(gid, {})[side] = row
    return out


def freeze_window(card: dict, *, now: Optional[datetime] = None,
                  lead_hours: float = CARD_FREEZE_LEAD_HOURS) -> dict:
    """Is it late enough in the day to freeze this card?

    Returns `{"ready": bool, "reason": str, "earliest_first_pitch": str|None,
    "opens_at": str|None}`. The reason is written for a run log, because
    this gate declining is the NORMAL outcome for most of the day and a bare
    "skipped" would read as a failure every half hour.

    MEASURED AGAINST THE DAY'S EARLIEST STILL-OPEN GAME, and what that means
    changed on 2026-09-11.

    It used to mean the card was fixed for the whole day at that moment: the
    ledger was idempotent per date, so the first publish won and a 7:40pm
    pick was locked at 8:15am to protect a 12:15pm matinee. A scratch at 6pm
    could not touch it.

    It no longer means that. `card_ledger.publish` locks each pick against
    ITS OWN first pitch and carries locked picks forward untouched, so
    publishing repeatedly through the day is safe and is the intended
    cadence. This gate now answers a narrower question: is it late enough
    that the EARLIEST game's pick is worth writing down at all? Everything
    later on the slate keeps improving until its own window closes.
    """
    now = now or datetime.now(timezone.utc)
    picks = card.get("picks") or []
    if not picks:
        return {"ready": False, "reason": "no picks to freeze",
                "earliest_first_pitch": None, "opens_at": None}

    stamps = []
    for pick in picks:
        parsed = _parse_first_pitch(pick.get("first_pitch_utc"))
        if parsed is not None:
            stamps.append(parsed)
    if not stamps:
        # Fail OPEN here, deliberately: a card whose first-pitch times are
        # all unreadable is already refused upstream by `_has_started`, so
        # reaching this branch means something stranger, and blocking the
        # freeze forever would silently stop the record.
        return {"ready": True,
                "reason": "no readable first-pitch times; freezing rather "
                          "than blocking the record indefinitely",
                "earliest_first_pitch": None, "opens_at": None}

    earliest = min(stamps)
    opens_at = earliest - timedelta(hours=lead_hours)
    if now < opens_at:
        return {
            "ready": False,
            "reason": (f"too early: the first game starts "
                       f"{earliest.isoformat()} and the card freezes from "
                       f"{opens_at.isoformat()} ({lead_hours:g}h before)"),
            "earliest_first_pitch": earliest.isoformat(),
            "opens_at": opens_at.isoformat(),
        }
    return {
        "ready": True,
        "reason": (f"within {lead_hours:g}h of the first game "
                   f"({earliest.isoformat()})"),
        "earliest_first_pitch": earliest.isoformat(),
        "opens_at": opens_at.isoformat(),
    }


def _parse_first_pitch(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# THE TWO REASON SENTENCES FOR "NOTHING SELECTED", chosen deliberately to
# avoid the retired "nothing clears the bar" register (checker problem 5,
# 2026-09-12). `tests/test_no_nothing_clears_the_bar.py`'s own docstring
# says the ban is on the MEANING, not the spelling -- "No player prop
# clears our bar tonight." was a paraphrase of exactly that sentence. Both
# strings below state a fact about tonight's props (posted lineup, cleared
# its price) rather than a verdict about our confidence.
_PROP_NONE_SELECTED_LIVE = (
    "No player prop posted with a lineup behind it clears its price tonight.")
_PROP_NONE_SELECTED_FROZEN = (
    "No player prop posted with a lineup behind it cleared its price when "
    "this card was frozen.")
# The THIRD reason -- and a different fact from the two above. An old row
# published before 2026-09-12 never considered props at all; saying a prop
# "didn't clear its price" on that row is a claim about history that isn't
# true (checker problem 4). See `frozen_card`.
_PROP_NOT_PART_OF_CARD = "Player props were not part of this card when it was frozen."

# THE SAME THREE-WAY SPLIT, FOR TOTALS. ADDED 2026-09-14, same reasoning as
# the prop reasons just above: "nothing cleared" is a verdict on our own
# confidence and this surface never states one; each string here states a
# fact about tonight's totals board instead (or, for a row frozen before
# this feature existed, the fact that totals were never asked about at all).
# TOTALS ARE BUILT, GRADED AND RENDERED -- AND PAUSED ON THE LIVE CARD
# (orchestrator, 2026-09-14). The instrument is the suspect: on today's slate
# the run model's expected total sat ABOVE the market's line in 8 of 9 games
# (LAD@CIN 9.27 vs 7.5, NYY@MIN 9.78 vs 8.0) and BELOW it only at Coors
# (SD@COL 9.57 vs 11.0) -- the shape of a missing park factor -- and every
# total it would have published cleared its price on our run model alone, at
# a market of 50-52%, a coin flip. A graded public ledger is not the place to
# find out whether that is bias. Flip this to True once the run model's
# totals have been measured against settled games (owner decision). Frozen
# rows that already hold total picks are served either way.
TOTALS_ON_CARD = False
_TOTALS_PAUSED = (
    "Game totals are not on the card yet: our run numbers read high on "
    "totals, and we are measuring that against finished games first.")

_TOTAL_NONE_SELECTED_LIVE = (
    "No game total on the board both agrees with our own numbers and "
    "clears its price tonight.")
_TOTAL_NONE_SELECTED_FROZEN = (
    "No game total on the board both agreed with our own numbers and "
    "cleared its price when this card was frozen.")
_TOTAL_NOT_PART_OF_CARD = "Game totals were not part of this card when it was frozen."
_TOTALS_PAUSED_FROZEN = (
    "Game totals were paused when this card was frozen, so none were "
    "checked for it.")


def _prop_identity_by_game_pk(entries: Sequence, *, date: str) -> dict:
    """{str(game_pk): game identity} for every game on today's schedule,
    whether or not it produced a game-pick candidate.

    KEYED BY game_pk, NOT event_id -- fixed 2026-09-12 (checker BLOCKER,
    problem 1). A real slate entry's `game` dict never carries an
    `event_id`: `src.providers.mlb.parse_game` emits no such field, and
    nothing in `briefing.build_slate` adds one, so the old event_id-keyed
    version of this function was always `{}` in production and every prop
    pick was silently dropped at the join below -- verified against all 19
    published card rows in evidence/cards_v1.jsonl (every one carries
    `"event_id": null`) and against the real 2026-09-12 board (15 eligible
    contracts, 0 joined). `game_pk` is the identifier `_game_identity`
    actually gets off the schedule, so this is keyed on that instead; see
    `_build_prop_picks` for the other half of the join (event_id ->
    game_pk, via `src.board.gamekey`).
    """
    from src.core.asof import game_pk_key

    out = {}
    for entry in entries or ():
        game = _game_identity(entry, date=date)
        pk = game_pk_key(game.get("game_pk"))
        if pk is not None:
            out[pk] = game
    return out


def _build_prop_picks(entries: Sequence, *, date: str, now: datetime,
                      prop_board=None, event_map=None) -> tuple:
    """`(prop_picks, prop_reason)` for a LIVE card build.

    `prop_board` is the injectable seam: a callable `date -> board dict`,
    defaulting to `src.report.props.board_for_date` called for every
    eligible contract on the board (see the `limit` note below). Injected
    so a test never has to let this read `data/processed/batter_props.jsonl`
    and `boxscores_2026.jsonl` off the real disk to exercise it -- see
    `docs/` on "a test that reads the disk" for the defect this guards.

    `event_map` is the second injectable seam, shaped like
    `src.board.gamekey.load_map()`'s return ({event_id: {"game_pk": ...}}):
    a prop contract carries the odds feed's `event_id`, a slate entry
    carries the schedule's `game_pk` and no `event_id` at all, and
    `data/processed/event_game_map.jsonl` (`src.board.gamekey`) is the one
    store on disk that already resolves one id space to the other. Defaults
    to the real map; a test passes its own dict so this never touches disk.

    THE BOARD IS ASKED FOR EVERY CONTRACT, not its default page. Checker
    problem 2: `board_fn(date)` used to call `props_mod.board_for_date`
    with no `limit`, so the candidate pool was silently capped at
    `DEFAULT_LIMIT` (40) -- most likely first, so this only ever bites when
    fewer than `MAX_PROP_PICKS` of the top 40 survive `select_props`'s
    filters while an eligible contract sits below the cut, but the
    truncation was silent and slate-size dependent either way. Only the
    REAL default is widened to `MAX_LIMIT` (200) here, by wrapping it
    rather than adding a `limit` kwarg to this function's own call of
    `board_fn` -- an injected test double is a plain `callable(date)` and
    must not be required to accept one.

    The board can raise (a corrupt store) or come back with no contracts (no
    props posted yet, or nothing on it clears `propboard.LIKELY_FLOOR`).
    Either way `prop_picks` is `[]` and `prop_reason` names why in the
    reader's own words -- the same contract `_empty_reason` keeps for the
    moneyline picks beside it. A broken prop board must never take the
    moneyline card down with it: the moneyline picks are the product this
    surface has always sold, and props are additive to it.
    """
    from src.report import props as props_mod

    board_fn = prop_board or (
        lambda d: props_mod.board_for_date(d, limit=props_mod.MAX_LIMIT))
    try:
        board = board_fn(date)
    except Exception:  # noqa: BLE001 -- see the docstring above
        return [], "Player props aren't available for today's games right now."

    contracts = (board or {}).get("contracts") or []
    if not contracts:
        reason = ((board or {}).get("reason")
                  or "No player props are posted for today's games yet.")
        return [], reason

    from src.board import gamekey
    from src.pipeline import slate as slate_mod

    if event_map is None:
        try:
            event_map = gamekey.load_map()
        except Exception:  # noqa: BLE001 -- an unreadable map is a gap,
            # not a reason to take the moneyline card down with it.
            event_map = {}

    identity = _prop_identity_by_game_pk(entries, date=date)
    enriched = []
    for contract in contracts:
        pk = gamekey.game_pk_for_event(contract.get("event_id"), event_map)
        game = identity.get(pk) if pk is not None else None
        if game is None:
            # A prop quote whose game is not on today's read schedule -- a
            # feed mismatch, an unresolved event_id, or a doubleheader game
            # the schedule pass did not carry. Not a pick without knowing
            # which game it is or when it starts.
            continue
        team = (slate_mod.team_abbrev_from_name(contract["team_name"])
               if contract.get("team_name") else None)
        enriched.append({
            **contract,
            "game_pk": game.get("game_pk"),
            "away_team": game.get("away_team"),
            "home_team": game.get("home_team"),
            "first_pitch_utc": game.get("first_pitch_utc"),
            "team": team,
        })

    # `require_lineup=False`: the owner's ask is analysis run pre-emptively,
    # before any lineup posts (see `daily_card.select_props`'s own docstring
    # for the full reasoning and the replacement mechanism).
    picks = daily_card.select_props(enriched, now=now, require_lineup=False)
    if not picks:
        return [], _PROP_NONE_SELECTED_LIVE
    return picks, None


def _served_prop_order(picks) -> list:
    """The frozen prop picks in probability order, each numbered by
    `position` -- the prop-pick counterpart to `_served_order` below.

    Ranked by probability rather than by `daily_card._rank_key` (which reads
    `confidence`/`market_probability`, fields a prop pick does not carry):
    a prop pick's own rule ranks by probability and only by probability, and
    the served order has to agree with the rule that selected it.
    """
    ordered = sorted(
        (dict(p) for p in picks),
        key=lambda p: (-(p.get("probability") or 0.0), str(p.get("player") or "")))
    for i, pick in enumerate(ordered, start=1):
        pick["position"] = i
    return ordered


def _served_total_order(picks) -> list:
    """The frozen total picks in market-probability order, each numbered by
    `position` -- the total-pick counterpart to `_served_prop_order` above.
    A total pick's own rule ranks by market probability (see
    `daily_card.select_totals`), so the served order reads the same field.
    """
    ordered = sorted((dict(p) for p in picks),
                     key=lambda p: -(p.get("market_probability") or 0.0))
    for i, pick in enumerate(ordered, start=1):
        pick["position"] = i
    return ordered


def _served_order(picks) -> list:
    """The frozen picks in the order the card says it uses -- "ranked by how
    confident the market is" -- each numbered by `position`.

    A pick's `rank` is the slot it was frozen in and is a frozen field
    (card_ledger.FROZEN_FIELDS), so it is never rewritten. But a card is
    assembled through the day: each pick locks against its own first pitch
    and is carried forward with the rank it held in THAT freeze. The row
    served for 2026-09-11 carried nine picks with ranks [3,2,3,1,2,4,5,5,4],
    in lock order, and the page printed "3 OF 9" twice. `position` is where
    the pick sits on the card actually being served; `rank` stays as the
    receipt of where it sat when it froze.
    """
    ordered = sorted((dict(p) for p in picks), key=daily_card._rank_key)
    for i, pick in enumerate(ordered, start=1):
        pick["position"] = i
    return ordered


def frozen_card(date: str) -> Optional[dict]:
    """The card as it was FROZEN for `date`, in payload shape, or None.

    THIS IS WHY THE RECEIPTS MEAN ANYTHING. `card_for_date` rebuilds from
    live prices, so a page that always rebuilt would show a card that drifts
    away from the one in the ledger as books move -- and a record whose
    receipts do not match the page they are receipts for is not a record.

    Once a date is published, the page serves the frozen row. The prices on
    it are quoted from that instant and are named as such
    (`frozen_at`), and scripts/publication_audit.py warns when they get old.
    That is the promise, stated plainly: this is what we said, before the
    games started, and it has not been touched since.

    Returns None before the afternoon pass publishes, and the page then
    builds live and says so.
    """
    from src.appstate import card_ledger

    row = card_ledger.published_row(date)
    if row is None:
        return None
    # EVERY KEY THE LIVE BRANCH EMITS, so a consumer never has to ask which
    # branch it got. The counts a frozen row cannot know are None rather
    # than absent -- and None rather than 0, because "we did not record this"
    # and "this was zero" are different facts and a renderer that treats them
    # the same prints "0 games on the slate" for a card that has three picks.
    # `"prop_picks" in row` (not `.get(...) or ()` truthiness alone) is
    # what tells a card published before this feature from a card that
    # considered props and found none -- see `_PROP_NOT_PART_OF_CARD`'s
    # comment above and checker problem 4.
    prop_picks_considered = "prop_picks" in row
    prop_picks = row.get("prop_picks") or ()
    # TOTAL PICKS, the same "key present vs. key missing" distinction as
    # `prop_picks_considered` just above -- see that comment and
    # `_TOTAL_NOT_PART_OF_CARD`.
    total_picks_considered = "total_picks" in row
    total_picks = row.get("total_picks") or ()
    # PAUSED, NOT EVALUATED (2026-09-14, owner-approved wording fix). Totals
    # have been switched off on the live card since the day the key first
    # appeared on a ledger row (`TOTALS_ON_CARD = False` shipped in the same
    # commit as `total_picks`), so a row that carries `total_picks` but no
    # `totals_paused` flag was built while paused. Rows written after this
    # fix carry the flag explicitly.
    totals_paused = bool(row.get("totals_paused",
                                 total_picks_considered and not total_picks))

    served_picks = _served_order(row.get("picks") or ())
    served_totals = _served_total_order(total_picks)
    served_props = _served_prop_order(prop_picks)
    return {
        "picks": served_picks,
        "filled": row.get("n_filled") or 0,
        "considered": None,
        "agreed": None,
        "split": None,
        "games_started": None,
        "games_open": None,
        "rule": row.get("rule"),
        "basis": row.get("basis"),
        "disclaimer": row.get("disclaimer"),
        "min_picks": daily_card.MIN_PICKS,
        "max_picks": daily_card.MAX_PICKS,
        # PROP PICKS, FROZEN LIKE THE GAME PICKS BESIDE THEM. An old row
        # published before 2026-09-12 has no `prop_picks` key at all, and
        # `.get(...) or ()` reads that exactly like an empty list for
        # `prop_picks` itself -- the whole point of the "every reader
        # treats a missing key as an empty list" rule this feature was
        # built under. `prop_reason` is the one exception: a MISSING key
        # and an EMPTY list are different facts (props never considered vs.
        # considered and none selected) and read differently below.
        "prop_picks": served_props,
        "prop_reason": (
            None if prop_picks
            else _PROP_NONE_SELECTED_FROZEN if prop_picks_considered
            else _PROP_NOT_PART_OF_CARD),
        # TOTAL PICKS, same three-way distinction as props (2026-09-14).
        "total_picks": served_totals,
        "total_reason": (
            None if total_picks
            else _TOTALS_PAUSED_FROZEN if totals_paused
            else _TOTAL_NONE_SELECTED_FROZEN if total_picks_considered
            else _TOTAL_NOT_PART_OF_CARD),
        "totals_paused": totals_paused,
        # THE MERGED LIST, built from these same three served arrays -- see
        # `card_for_date`'s live branch for why it is always rebuilt rather
        # than frozen as its own field: it is a view over the three, never
        # an independent claim.
        "all_bets": daily_card.merge_all_bets(
            served_picks, served_totals, served_props),
        "frozen": True,
        "frozen_at": row.get("published_utc"),
        "row_hash": row.get("row_hash"),
        "calibrated": row.get("calibrated"),
        "calibration": row.get("calibration"),
        "model_id": row.get("model_id"),
        "games_on_slate": row.get("games_on_slate"),
    }


def card_for_date(entries: Sequence, opportunity_rows: Sequence, *, date: str,
                  now: Optional[datetime] = None,
                  calibration=None, multibook_rows=None,
                  prefer_frozen: bool = True, prop_board=None,
                  event_map=None) -> dict:
    """The published card for one date.

    Serves the FROZEN card when one exists (see `frozen_card`), and builds
    live otherwise. `prefer_frozen=False` forces a live build, which is what
    `card publish` itself needs -- it is the thing doing the freezing and
    must not read its own output.

    Never raises on a thin slate; an empty schedule produces an empty card
    with `reason` set, which is a different statement from "nothing cleared
    the bar" and is the only empty state this surface has.

    `prop_board` and `event_map` are the player-props seams: `prop_board` a
    callable `date -> board dict`, defaulting to `src.report.props.
    board_for_date`; `event_map` an `{event_id: {"game_pk": ...}}` dict,
    defaulting to `src.board.gamekey.load_map()`. See `_build_prop_picks`
    for what each is for and why both are injectable.
    """
    now = now or datetime.now(timezone.utc)

    if prefer_frozen:
        frozen = frozen_card(date)
        if frozen is not None:
            frozen["date"] = date
            frozen["knowledge_legend"] = list(grade.legend())
            frozen["generated_at"] = now.astimezone(timezone.utc).isoformat()
            frozen["model_basis"] = strength.MODEL_BASIS
            return frozen
    cal = calibration if calibration is not None else load_calibration()

    games, model_lines = [], {}
    started = 0
    feature_rows = [_flatten(e) for e in entries or ()]
    league_rpg = strength.league_runs_per_game(feature_rows)
    relief = relief_rates_for(date)
    # READ BEFORE THE LOOP, because the loop needs each game's own line to
    # ask the model about THAT line -- see the `totals=` call below.
    total_lines = total_rows(date, rows=multibook_rows)

    for entry in entries or ():
        game = _game_identity(entry, date=date)
        if _has_started(game["first_pitch_utc"], now):
            started += 1
            continue
        if not league_rpg:
            continue
        # The real relief rate for each club, when the log has one. Absent
        # keys leave `run_means` on its old fallback and it says so.
        game["features"]["away_bullpen_rate"] = relief.get(game["away_team"])
        game["features"]["home_bullpen_rate"] = relief.get(game["home_team"])
        # THE GAME'S OWN TOTAL LINE, PASSED IN. Scouted 2026-09-14: this call
        # never passed `totals=`, so `strength.market_probabilities`' own
        # `p_over` dict was always empty and no total pick could ever agree
        # with anything -- there was nothing to read `p_over` at. The total
        # board has no fixed standard the way the run line does, so the line
        # itself has to be read off `total_lines` per game before the model
        # is asked about it.
        game_total = total_lines.get(game["game_id"])
        total_line = (game_total or {}).get("line")
        totals_arg = None
        if isinstance(total_line, (int, float)):
            totals_arg = [total_line]
            # WHOLE-NUMBER LINES CAN PUSH. ADDED 2026-09-14 (Opus checker
            # problem 1). `daily_card.build_total_candidates` needs the
            # model's probability at `total_line - 0.5` too, to measure how
            # much mass sits exactly on the push and read both sides
            # ignoring it -- see that function's own comment for the full
            # reasoning and the live number it was measured against. A
            # half-point line cannot push, so nothing extra is asked of the
            # model for one.
            if float(total_line).is_integer():
                totals_arg.append(float(total_line) - 0.5)
        try:
            line = strength.model_line(game["features"], league_rpg=league_rpg,
                                       run_line=RUN_LINE, totals=totals_arg)
        except strength.StrengthError:
            continue
        if cal is not None:
            raw = line["p_home"]
            line["p_home_raw"] = raw
            line["p_home"] = cal.apply(raw)
            line["p_away"] = 1.0 - line["p_home"]
        games.append(game)
        model_lines[game["game_id"]] = line

    ml_rows = moneyline_rows(opportunity_rows)
    # LOUD ZERO, NOT A SILENT ONE (Stage 18 join-integrity audit, 2026-09-16).
    # `games` is keyed by `_game_identity`'s `game_id`; `ml_rows` is keyed by
    # `gamepayload.game_id()` via `opportunities.build_opportunities`. Both
    # now delegate to the same function (see `_game_identity`), but this is
    # exactly the shape the NFL outage had -- two id constructions that can
    # drift apart with nothing raising when they do. If today's slate and
    # today's priced board are both non-empty but not one game_id lines up
    # between them, that is a code failure (an id-construction mismatch),
    # not the honest "books haven't posted yet" this function reports
    # below when `ml_rows` itself is empty.
    joins_mod.report_join_result(
        name="card-slate-to-moneyline-board",
        left=games, right=ml_rows,
        matched=[g for g in games if g.get("game_id") in ml_rows])
    candidates = daily_card.build_pick_candidates(
        games,
        model_lines=model_lines,
        moneyline_rows=ml_rows,
        runline_rows=run_line_rows(date, rows=multibook_rows),
    )
    payload = daily_card.select(candidates)

    if TOTALS_ON_CARD:
        total_candidates = daily_card.build_total_candidates(
            games, model_lines=model_lines, total_rows=total_lines)
        total_payload = daily_card.select_totals(total_candidates)
        payload["total_picks"] = total_payload["picks"]
        payload["total_reason"] = (
            None if total_payload["picks"] else _TOTAL_NONE_SELECTED_LIVE)
        payload["totals_paused"] = False
    else:
        payload["total_picks"] = []
        payload["total_reason"] = _TOTALS_PAUSED
        payload["totals_paused"] = True
    payload.update({
        "date": date,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "games_on_slate": len(entries or ()),
        "games_started": started,
        "games_open": len(games),
        "calibrated": cal is not None and cal.n >= calibrate.MIN_FIT_GAMES,
        "calibration": cal.to_dict() if cal is not None else None,
        "model_id": strength.MODEL_ID,
        "model_basis": strength.MODEL_BASIS,
        # NOT YET FROZEN. The page says so, because "these are the prices
        # right now and this card can still change" and "this is what we
        # committed to before first pitch" are different promises and only
        # one of them is the product.
        "frozen": False,
        "frozen_at": None,
    })
    attach_knowledge(payload, entries, now=now)

    prop_picks, prop_reason = _build_prop_picks(
        entries, date=date, now=now, prop_board=prop_board, event_map=event_map)
    payload["prop_picks"] = prop_picks
    payload["prop_reason"] = prop_reason

    # THE MERGED LIST -- every kind the card can carry today, one ranking.
    # Built fresh from the three arrays just assigned above, so it can never
    # disagree with them (see `daily_card.merge_all_bets`).
    payload["all_bets"] = daily_card.merge_all_bets(
        payload["picks"], payload["total_picks"], payload["prop_picks"])

    if not payload["picks"]:
        payload["reason"] = _empty_reason(entries, started, len(games),
                                          len(candidates))
    return payload


def attach_knowledge(payload: dict, entries: Sequence, *, now: datetime) -> dict:
    """Put a knowledge grade on every pick, and the legend on the card.

    The grade comes from the same dossier census the slate list shows
    (src/analysis/gamepayload.py), joined on game_pk -- the one identifier
    both the card and the slate carry unchanged. A pick whose game has no
    dossier here gets no grade rather than a guessed one.

    The "+" is decided here and nowhere else, because this is the only
    place a pick and its price exist together: an A becomes A+ when the
    pick's own model number clears the break-even its stated price demands.
    Moneyline picks only -- on a run-line pick `model_probability` is a
    cover probability and `price` is the run-line price, and comparing them
    is a different question than the one the plus asks.
    """
    grades = {}
    for entry in entries or ():
        dossier = entry.get("dossier") if isinstance(entry, dict) else None
        if not isinstance(dossier, dossier_mod.Dossier):
            continue
        game = dossier.game or {}
        key = game.get("game_pk")
        if key is None:
            continue
        grades[str(key)] = grade.knowledge_grade(
            game=game,
            data_quality=gamepayload._data_quality(dossier),
            board_summary=gamepayload._board_summary(dossier, now=now),
            lineups=dossier.get("lineups"),
            gaps=dossier.gaps)

    for pick in payload.get("picks") or ():
        base = grades.get(str(pick.get("game_pk")))
        if base is None:
            pick["knowledge"] = None
            continue
        breakeven = None
        if pick.get("market") == "moneyline" and pick.get("price") is not None:
            try:
                breakeven = odds_math.american_to_probability(pick["price"])
            except (odds_math.OddsError, TypeError, ValueError, ZeroDivisionError):
                breakeven = None
        pick["knowledge"] = grade.with_plus(
            base,
            model_probability=(pick.get("model_probability")
                               if pick.get("market") == "moneyline" else None),
            breakeven=breakeven)

    payload["knowledge_legend"] = list(grade.legend())
    return payload


def _empty_reason(entries, started, open_games, candidates) -> str:
    """Why there is no card, in the reader's terms.

    Every branch names a fact about the WORLD -- no games, all started, no
    prices -- and never a fact about our own confidence. "Nothing cleared the
    bar" is not among them and cannot be: this surface has no bar to clear.
    """
    if not entries:
        return "There are no major-league games scheduled today."
    if open_games == 0 and started:
        return (f"All {started} of today's games have already started. "
                f"Tomorrow's card goes up when the lines open.")
    if candidates == 0:
        return ("The books have not posted prices for today's games yet. "
                "The card goes up as soon as they do.")
    return "Today's card is not available."


def american_from_probability(p) -> Optional[int]:
    """A model probability as a price, for the "our number" line."""
    try:
        return int(round(odds_math.probability_to_american(p)))
    except (odds_math.OddsError, TypeError, ValueError):
        return None
