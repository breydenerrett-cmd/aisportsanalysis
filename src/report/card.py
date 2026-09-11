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

from src.analysis import calibrate, daily_card, strength
from src.analysis import prices as prices_mod
from src.appstate import freshness
from src.core import odds as odds_math
from src.detect import dossier as dossier_mod

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
    number = game.get("game_number") or 1
    return {
        "game_id": f"{away}-{home}-{date}-{number}",
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
    return {
        "picks": list(row.get("picks") or ()),
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
                  prefer_frozen: bool = True) -> dict:
    """The published card for one date.

    Serves the FROZEN card when one exists (see `frozen_card`), and builds
    live otherwise. `prefer_frozen=False` forces a live build, which is what
    `card publish` itself needs -- it is the thing doing the freezing and
    must not read its own output.

    Never raises on a thin slate; an empty schedule produces an empty card
    with `reason` set, which is a different statement from "nothing cleared
    the bar" and is the only empty state this surface has.
    """
    now = now or datetime.now(timezone.utc)

    if prefer_frozen:
        frozen = frozen_card(date)
        if frozen is not None:
            frozen["date"] = date
            frozen["generated_at"] = now.astimezone(timezone.utc).isoformat()
            frozen["model_basis"] = strength.MODEL_BASIS
            return frozen
    cal = calibration if calibration is not None else load_calibration()

    games, model_lines = [], {}
    started = 0
    feature_rows = [_flatten(e) for e in entries or ()]
    league_rpg = strength.league_runs_per_game(feature_rows)
    relief = relief_rates_for(date)

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
        try:
            line = strength.model_line(game["features"], league_rpg=league_rpg,
                                       run_line=RUN_LINE)
        except strength.StrengthError:
            continue
        if cal is not None:
            raw = line["p_home"]
            line["p_home_raw"] = raw
            line["p_home"] = cal.apply(raw)
            line["p_away"] = 1.0 - line["p_home"]
        games.append(game)
        model_lines[game["game_id"]] = line

    candidates = daily_card.build_pick_candidates(
        games,
        model_lines=model_lines,
        moneyline_rows=moneyline_rows(opportunity_rows),
        runline_rows=run_line_rows(date, rows=multibook_rows),
    )
    payload = daily_card.select(candidates)
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
    if not payload["picks"]:
        payload["reason"] = _empty_reason(entries, started, len(games),
                                          len(candidates))
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
