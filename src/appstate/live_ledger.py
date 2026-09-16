"""Live research candidates ledger. Hash-chained, append-only.

WHY THIS EXISTS
---------------
These are research candidates, never picks. They never appear on the card or
payoff record. A hash-chained ledger records every candidate and every
settlement, so the forward research plan can be audited and verified.

This module is isolated from card_ledger: no imports, no shared code paths.
The profit arithmetic is copied from card_ledger for this live context only.

SECTION 3.1 ROW SHAPE (R16-L6)
-------------------------------
A candidate row carries, on top of `kind`/`recorded_utc`/`date`, the field
groups from `docs/LIVE_BETTING_SYSTEM.md` 3.1: identity (who registered this
rule and what code ran it), game, pre-game proof, trigger, quote and status,
band, and a fixed-false customer surface flag. `record_candidate` REFUSES
(raises `LiveLedgerError`, writes nothing) when any pre-game quote was
observed at or after the game's `commence_time` -- a pre-game favourite read
after the game has started is not pre-game proof of anything (D10's ledger
side: rows must be auditable against their own registration, and a row built
on a leaked in-play price cannot be).

ONE TRIGGER PER RULE PER GAME. The existing dedup on (rule_id, sport,
game_id) already gives this: the first call for a key writes the row --
PRICED or any UNPRICED status -- and every later call for the same key
returns None. A trigger that could not be priced is still recorded (D10) and
still blocks a second trigger later in the same game, so price availability
can never select the sample.

SETTLEMENT FROM AUTHORITATIVE FINALS (R16-L7)
-----------------------------------------------
`settle()` grades unsettled candidates against a caller-supplied
`results_by_game_id` map, exactly as before -- `src/pipeline/live_window.py`
already calls it this way and nothing here changes that call shape. What
changed is what it refuses to do and what it returns:

  * a candidate with no final in `results_by_game_id` stays UNSETTLED, not
    VOID (D11's bug was writing a permanent VOID the first time a final was
    missing);
  * VOID is written only once the candidate's own trigger date is 7 or more
    days old, and every VOID row carries a `reason`;
  * the return value is COUNTS ONLY -- `{date, graded, voids, unsettled}`.
    No `wins`, `losses`, `units` or `by_rule` key, anywhere in this function
    or in `settle_mlb_date`/`settle_recent` below, so nobody who prints this
    dict (a daily loop, a log line) can leak a per-rule win-loss figure
    (Stage 0, 3.1: "nobody on the project computes an interim result").
    Individual settled ROWS in the ledger still carry `result` and
    `profit_units` -- that is the audit record itself, `record()` and
    `history()` still read it for the internal page -- only the printed
    SUMMARY is stripped.

`settle_mlb_date(date)` is the clean call the live window should use instead
of building its own results map from the poller's own state rows (D11):
finals come from `mlb.fetch_results(date)`'s `final` bucket, the Stats API's
own authoritative bucket, never from whatever the window happened to see
live. `settle_recent()` is what the daily loop now calls: yesterday, plus
every date in the last 7 days that still has unsettled MLB candidates.
"""

from __future__ import annotations

import os
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence

from src.ledger.chain import HashChainLedger
from src.paths import evidence_path

LIVE_STORE = os.path.join("evidence", "live_candidates_v1.jsonl")

KIND_CANDIDATE = "live_candidate"
KIND_SETTLED = "live_settled"

RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_PUSH = "PUSH"
RESULT_VOID = "VOID"

# Section 3.1 "Status" group. UNPRICED_NO_FRESH_QUOTE / UNPRICED_NO_MARKET /
# UNPRICED_CREDIT_REFUSED / UNPRICED_FEED_ERROR distinguish WHY a trigger
# could not be priced, so an unpriced share of triggers can be audited by
# cause rather than treated as one undifferentiated bucket.
STATUS_PRICED = "PRICED"
STATUS_UNPRICED_NO_FRESH_QUOTE = "UNPRICED_NO_FRESH_QUOTE"
STATUS_UNPRICED_NO_MARKET = "UNPRICED_NO_MARKET"
STATUS_UNPRICED_CREDIT_REFUSED = "UNPRICED_CREDIT_REFUSED"
STATUS_UNPRICED_FEED_ERROR = "UNPRICED_FEED_ERROR"

VALID_STATUSES = frozenset({
    STATUS_PRICED,
    STATUS_UNPRICED_NO_FRESH_QUOTE,
    STATUS_UNPRICED_NO_MARKET,
    STATUS_UNPRICED_CREDIT_REFUSED,
    STATUS_UNPRICED_FEED_ERROR,
})

# A VOID for "no final yet" is refused before this many days have passed
# since the candidate's own (ET) date -- 3.1: "VOID is written only after 7
# days". A game postponed and never resumed voids sooner, but only with its
# own reason; that path is not exercised by settle() itself and is left to
# whatever caller knows a game was abandoned.
VOID_AFTER_DAYS = 7

SCHEMA_VERSION = "live_candidates_v1.3.1"


class LiveLedgerError(RuntimeError):
    pass


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(path or LIVE_STORE)


def _american_to_decimal(price: float) -> float:
    """Convert American odds to decimal odds.

    Positive price (underdog): decimal = 1.0 + (price / 100.0)
    Negative price (favorite): decimal = 1.0 + (100.0 / abs(price))
    """
    if price > 0:
        return 1.0 + (price / 100.0)
    return 1.0 + (100.0 / abs(price))


def _profit_at_price(price: int, won: bool) -> float:
    """Compute flat one-unit profit at American odds.

    Args:
        price: American odds (int).
        won: True if the bet won, False if lost.

    Returns:
        Profit in units: decimal - 1.0 if won, -1.0 if lost.
    """
    if won:
        try:
            return round(_american_to_decimal(price) - 1.0, 4)
        except (TypeError, ValueError):
            return 0.0
    return -1.0


def _et_date(utc_str: Optional[str]) -> str:
    """ET date (YYYY-MM-DD) from a UTC timestamp string.

    Uses fixed -4:00 offset for baseball season (DST is always in effect).
    """
    if not utc_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert to ET (fixed -4:00 for baseball season, DST always in effect)
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("America/New_York")
        except Exception:
            et = timezone(timedelta(hours=-4))

        et_dt = dt.astimezone(et)
        return et_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _refuse_if_pregame_quote_leaks(candidate: Mapping) -> None:
    """R16-L6: refuse the row when any pre-game quote is at or after the
    game's start.

    `commence_time` and per-book pre-game quotes travel together under
    `pregame_quotes` (each `{"book", "price", "observed_utc"}`) plus the
    summary fields `pregame_newest_observed_utc` / `pregame_books`. A rule
    with no pre-game proof to check (neither field supplied) is allowed
    through unchecked -- this guard exists to catch a leaked in-play quote
    masquerading as pre-game proof, not to require every caller to supply
    proof it does not have yet.
    """
    commence_time = candidate.get("commence_time")
    quotes = candidate.get("pregame_quotes") or ()
    newest = candidate.get("pregame_newest_observed_utc")

    if not commence_time:
        return

    commence_dt = _parse_utc(commence_time)
    if commence_dt is None:
        return

    for quote in quotes:
        observed = _parse_utc((quote or {}).get("observed_utc"))
        if observed is not None and observed >= commence_dt:
            raise LiveLedgerError(
                f"pre-game quote observed at {observed.isoformat()} is at or "
                f"after commence_time {commence_dt.isoformat()} -- refusing "
                "to record a candidate whose pre-game proof may already be "
                "an in-play price"
            )

    newest_dt = _parse_utc(newest)
    if newest_dt is not None and newest_dt >= commence_dt:
        raise LiveLedgerError(
            f"pregame_newest_observed_utc {newest_dt.isoformat()} is at or "
            f"after commence_time {commence_dt.isoformat()} -- refusing to "
            "record a candidate whose pre-game proof may already be an "
            "in-play price"
        )


def record_candidate(candidate: Mapping, *, now: Optional[str] = None,
                    path: Optional[str] = None) -> Optional[dict]:
    """Record a live research candidate. Deduplicated per (rule_id, sport,
    game_id) -- ONE TRIGGER PER RULE PER GAME (3.1), priced or not.

    Args:
        candidate: a mapping carrying section 3.1's field groups. Required:
            "rule_id", "sport", "game_id". Recognized (all optional, default
            None/False unless noted):
              Identity: schema_version, family, rule_id, rule_version,
                prereg_doc, prereg_commit, code_commit
              Game: sport, game_id
              Pre-game proof: favourite, favourite_prob, pregame_books,
                pregame_newest_observed_utc, commence_time,
                pregame_quotes (list of {book, price, observed_utc}; used
                only to check the refusal rule, not stored verbatim)
              Trigger: t0_utc, state_id, trigger (dict of the state fields
                that satisfied the rule)
              Quote: capture_observed_utc, price (the logged/median price),
                books (per-book quotes: list of {book, price, last_update}),
                fresh_books, latency_s, max_quote_age_s, retries
              Status: status (one of the STATUS_* constants; default
                STATUS_PRICED)
              Band: in_band, band_version
              Legacy/back-compat display fields also accepted: side, team,
                bet, observed_utc (falls back to t0_utc for the ET date)
        now: Recording timestamp (defaults to now).
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        The full row (payload + chain fields), or None if this (rule_id,
        sport, game_id) already exists in the ledger (deduped, whatever its
        status).

    Raises:
        LiveLedgerError: rule_id/sport/game_id missing, an unrecognized
            status, or a pre-game quote at or after commence_time.
    """
    rule_id = candidate.get("rule_id")
    sport = candidate.get("sport")
    game_id = candidate.get("game_id")
    if not rule_id or not sport or not game_id:
        raise LiveLedgerError(
            "a candidate needs rule_id, sport and game_id to be recorded "
            f"(got rule_id={rule_id!r} sport={sport!r} game_id={game_id!r})"
        )

    status = candidate.get("status") or STATUS_PRICED
    if status not in VALID_STATUSES:
        raise LiveLedgerError(
            f"unrecognized status {status!r}; must be one of {sorted(VALID_STATUSES)}"
        )

    _refuse_if_pregame_quote_leaks(candidate)

    # Check for existing candidate with same (rule_id, sport, game_id) --
    # ONE TRIGGER PER RULE PER GAME, priced or not.
    ledger = _ledger(path)
    for row in ledger.read():
        if (row.get("kind") == KIND_CANDIDATE and
            row.get("rule_id") == rule_id and
            row.get("sport") == sport and
            row.get("game_id") == game_id):
            return None  # Already recorded; this trigger does not get a row.

    observed_utc = candidate.get("observed_utc") or candidate.get("t0_utc")
    row_date = _et_date(observed_utc)

    payload = {
        "kind": KIND_CANDIDATE,
        "recorded_utc": now or datetime.now(timezone.utc).isoformat(),
        "date": row_date,

        # Identity
        "schema_version": candidate.get("schema_version") or SCHEMA_VERSION,
        "family": candidate.get("family"),
        "rule_id": rule_id,
        "rule_version": candidate.get("rule_version"),
        "prereg_doc": candidate.get("prereg_doc"),
        "prereg_commit": candidate.get("prereg_commit"),
        "code_commit": candidate.get("code_commit") or os.environ.get("GITHUB_SHA"),

        # Game
        "sport": sport,
        "game_id": game_id,

        # Pre-game proof
        "favourite": candidate.get("favourite"),
        "favourite_prob": candidate.get("favourite_prob"),
        "pregame_books": candidate.get("pregame_books"),
        "pregame_newest_observed_utc": candidate.get("pregame_newest_observed_utc"),
        "commence_time": candidate.get("commence_time"),

        # Trigger
        "t0_utc": candidate.get("t0_utc") or observed_utc,
        "state_id": candidate.get("state_id"),
        "trigger": candidate.get("trigger"),

        # Quote
        "capture_observed_utc": candidate.get("capture_observed_utc") or observed_utc,
        "price": candidate.get("price"),
        "books": candidate.get("books"),
        "fresh_books": candidate.get("fresh_books"),
        "logged_price": candidate.get("logged_price", candidate.get("price")),
        "latency_s": candidate.get("latency_s"),
        "max_quote_age_s": candidate.get("max_quote_age_s"),
        "retries": candidate.get("retries"),

        # Status
        "status": status,

        # Band
        "in_band": candidate.get("in_band"),
        "band_version": candidate.get("band_version"),

        # Surface -- fixed false until a family passes the full gate (3.1).
        "customer_eligible": False,

        # Display fields carried forward from the pre-3.1 shape; still what
        # renders a row on the internal page.
        "side": candidate.get("side"),
        "team": candidate.get("team"),
        "bet": candidate.get("bet"),
        "observed_utc": observed_utc,
    }

    return ledger.append(payload)


def candidates(*, date: Optional[str] = None,
              path: Optional[str] = None) -> list[dict]:
    """List all recorded candidates, optionally filtered by ET date.

    Args:
        date: ET date filter (YYYY-MM-DD), or None for all.
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        List of candidate rows (kind == KIND_CANDIDATE).
    """
    ledger = _ledger(path)
    result = []
    for row in ledger.read():
        if row.get("kind") != KIND_CANDIDATE:
            continue
        if date is not None and row.get("date") != date:
            continue
        result.append(row)
    return result


def unsettled(*, date: Optional[str] = None,
             path: Optional[str] = None) -> list[dict]:
    """List unsettled candidates for a date.

    Args:
        date: ET date (YYYY-MM-DD).
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        List of candidates with no corresponding settlement row.
    """
    if not date:
        return []

    ledger = _ledger(path)
    settled_keys = set()
    for row in ledger.read():
        if row.get("kind") == KIND_SETTLED and row.get("date") == date:
            key = (row.get("rule_id"), row.get("sport"), row.get("game_id"))
            settled_keys.add(key)

    result = []
    for row in ledger.read():
        if row.get("kind") != KIND_CANDIDATE or row.get("date") != date:
            continue
        key = (row.get("rule_id"), row.get("sport"), row.get("game_id"))
        if key not in settled_keys:
            result.append(row)
    return result


def _days_since(row_date: str, moment: datetime) -> Optional[int]:
    try:
        d = date_cls.fromisoformat(row_date)
    except (TypeError, ValueError):
        return None
    return (moment.date() - d).days


def settle(date: str, results_by_game_id: Mapping, *,
          now: Optional[str] = None, path: Optional[str] = None) -> Optional[dict]:
    """Settle candidates for a date against AUTHORITATIVE finals (R16-L7).

    A candidate with no final in `results_by_game_id` stays UNSETTLED and is
    retried on a later call -- it is never VOIDed just because this call
    could not find a final. VOID is written only once the candidate's own
    date is `VOID_AFTER_DAYS` (7) or more days old, and that row always
    carries a `reason`.

    Args:
        date: ET date (YYYY-MM-DD) of the candidates to settle.
        results_by_game_id: {game_id or str(game_id): {"home_score",
            "away_score"}} from an authoritative source (see
            `settle_mlb_date` for MLB). A game_id absent from this map is
            treated as "no final yet", not a loss or a void.
        now: Settlement timestamp (defaults to now).
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        {"date", "graded", "voids", "unsettled"} -- COUNTS ONLY. Deliberately
        no "wins", "losses", "units" or per-rule breakdown: this is the value
        a daily loop or log prints, and Stage 0 (3.1) forbids an interim
        win-loss figure leaking anywhere. Individual settled ROWS in the
        ledger still carry `result` and `profit_units` for later audit.
        Returns None if there was nothing unsettled for this date.
    """
    unsettled_list = unsettled(date=date, path=path)
    if not unsettled_list:
        return None

    ledger = _ledger(path)
    moment = _parse_utc(now) or datetime.now(timezone.utc)
    settled_utc = now or moment.isoformat()

    graded = 0
    voids = 0
    still_unsettled = 0

    for candidate in unsettled_list:
        game_id = candidate.get("game_id")
        result = (results_by_game_id.get(game_id) or
                 results_by_game_id.get(str(game_id)))

        home = away = None
        if result:
            try:
                home_score = result.get("home_score")
                away_score = result.get("away_score")
                home = int(home_score) if home_score is not None else None
                away = int(away_score) if away_score is not None else None
            except (TypeError, ValueError):
                home = away = None

        if home is None or away is None:
            # No final yet. Only VOID once this candidate's own date is old
            # enough (D11: a window that stopped early, or a missing feed,
            # must not permanently void a real candidate the first time it
            # is checked).
            age_days = _days_since(candidate.get("date") or date, moment)
            if age_days is not None and age_days >= VOID_AFTER_DAYS:
                reason = (
                    f"no final score after {age_days} days "
                    f"(checked {moment.date().isoformat()})"
                )
                ledger.append({
                    "kind": KIND_SETTLED,
                    "settled_utc": settled_utc,
                    "date": date,
                    "rule_id": candidate.get("rule_id"),
                    "sport": candidate.get("sport"),
                    "game_id": game_id,
                    "side": candidate.get("side"),
                    "price": candidate.get("price"),
                    "result": RESULT_VOID,
                    "profit_units": 0.0,
                    "reason": reason,
                })
                voids += 1
            else:
                still_unsettled += 1
            continue

        side = candidate.get("side")
        price = candidate.get("price")

        if home == away:
            result_code, profit, reason = RESULT_PUSH, 0.0, None
        elif side == "home":
            won = home > away
            result_code = RESULT_WIN if won else RESULT_LOSS
            profit, reason = _profit_at_price(price, won), None
        elif side == "away":
            won = away > home
            result_code = RESULT_WIN if won else RESULT_LOSS
            profit, reason = _profit_at_price(price, won), None
        else:
            result_code, profit = RESULT_VOID, 0.0
            reason = f"unknown side {side!r}"

        row = {
            "kind": KIND_SETTLED,
            "settled_utc": settled_utc,
            "date": date,
            "rule_id": candidate.get("rule_id"),
            "sport": candidate.get("sport"),
            "game_id": game_id,
            "side": side,
            "price": price,
            "result": result_code,
            "profit_units": profit,
        }
        if reason is not None:
            row["reason"] = reason
        ledger.append(row)

        if result_code == RESULT_VOID:
            voids += 1
        else:
            graded += 1

    return {
        "date": date,
        "graded": graded,
        "voids": voids,
        "unsettled": still_unsettled,
    }


def _default_mlb_fetch_results(game_date: str) -> dict:
    from src.providers import mlb
    return mlb.fetch_results(game_date)


def settle_mlb_date(date: str, *, path: Optional[str] = None,
                    now: Optional[str] = None,
                    fetch_results=None) -> Optional[dict]:
    """Settle one date's MLB candidates from `mlb.fetch_results` -- the
    Stats API's own authoritative final bucket, never the live poller's own
    rows (R16-L7 fixes D11's `live_window.settle()` path, which built finals
    from whatever the poller itself had seen).

    THE SIGNATURE THE WINDOW SHOULD CALL:

        settle_mlb_date(date: str, *, path: Optional[str] = None,
                        now: Optional[str] = None) -> Optional[dict]

    Wiring `src/pipeline/live_window.py`'s `settle()` to call this instead of
    building its own MLB `results` dict from `livefeed_mlb.read_states` is a
    one-line change once that file is free to edit.

    Args:
        date: ET date (YYYY-MM-DD).
        path: Ledger path (defaults to LIVE_STORE).
        now: Settlement timestamp (defaults to now).
        fetch_results: Injectable for tests; defaults to
            `mlb.fetch_results`.

    Returns:
        Same shape as `settle()`: {"date", "graded", "voids", "unsettled"},
        or None if there was nothing unsettled for this date.
    """
    fetch = fetch_results or _default_mlb_fetch_results
    payload = fetch(date) or {}
    results_by_game_id = {}
    for game in payload.get("final") or ():
        game_pk = game.get("game_pk")
        if game_pk is None:
            continue
        results_by_game_id[str(game_pk)] = {
            "home_score": game.get("home_score"),
            "away_score": game.get("away_score"),
        }
    return settle(date, results_by_game_id, now=now, path=path)


def settle_recent(*, path: Optional[str] = None, now: Optional[str] = None,
                  today: Optional[str] = None,
                  fetch_results=None) -> dict:
    """What the daily loop runs (R16-L7): settle yesterday, plus every date
    in the last 7 days that still has unsettled MLB candidates.

    Args:
        path: Ledger path (defaults to LIVE_STORE).
        now: Settlement timestamp for every date checked (defaults to now).
        today: ISO date to treat as "today" (defaults to the real UTC date;
            exposed for tests).
        fetch_results: Injectable for tests; passed through to
            `settle_mlb_date`.

    Returns:
        {"graded", "voids", "unsettled", "dates_checked"} -- counts summed
        across every date checked. Still no wins/losses/units.
    """
    moment = _parse_utc(now) or datetime.now(timezone.utc)
    if today:
        anchor = date_cls.fromisoformat(today)
    else:
        anchor = moment.date()

    totals = {"graded": 0, "voids": 0, "unsettled": 0, "dates_checked": 0}
    for offset in range(1, VOID_AFTER_DAYS + 1):
        d = (anchor - timedelta(days=offset)).isoformat()
        # Yesterday is always checked; older dates only if something is
        # still outstanding for them, so a settled week does not re-run
        # `mlb.fetch_results` seven times a night for nothing.
        if offset != 1 and not unsettled(date=d, path=path):
            continue
        result = settle_mlb_date(d, path=path, now=now, fetch_results=fetch_results)
        totals["dates_checked"] += 1
        if result:
            totals["graded"] += result["graded"]
            totals["voids"] += result["voids"]
            totals["unsettled"] += result["unsettled"]
    return totals


def record(*, path: Optional[str] = None) -> dict:
    """Full record: all candidates, all settlements, summary stats.

    NOT printed by the daily loop or any log -- this is the internal
    performance-page aggregate (`api/performance.py`), a different surface
    from `settle()`'s return value, which is what gets logged.

    Returns:
        {"candidates", "settled", "wins", "losses", "pushes", "voids",
         "units", "by_rule": {rule_id: {...counts...}}}.
    """
    ledger = _ledger(path)

    candidates_list = []
    settled_list = []

    for row in ledger.read():
        if row.get("kind") == KIND_CANDIDATE:
            candidates_list.append(row)
        elif row.get("kind") == KIND_SETTLED:
            settled_list.append(row)

    wins = losses = pushes = voids = 0
    units = 0.0
    by_rule = {}

    for row in settled_list:
        result = row.get("result")
        profit = row.get("profit_units", 0.0)
        rule_id = row.get("rule_id")

        if result == RESULT_WIN:
            wins += 1
            units += profit
        elif result == RESULT_LOSS:
            losses += 1
            units += profit
        elif result == RESULT_PUSH:
            pushes += 1
        elif result == RESULT_VOID:
            voids += 1

        if rule_id not in by_rule:
            by_rule[rule_id] = {"wins": 0, "losses": 0, "pushes": 0, "voids": 0, "units": 0.0}
        slot = by_rule[rule_id]
        if result == RESULT_WIN:
            slot["wins"] += 1
            slot["units"] += profit
        elif result == RESULT_LOSS:
            slot["losses"] += 1
            slot["units"] += profit
        elif result == RESULT_PUSH:
            slot["pushes"] += 1
        elif result == RESULT_VOID:
            slot["voids"] += 1

    for slot in by_rule.values():
        slot["units"] = round(slot["units"], 4)

    return {
        "candidates": len(candidates_list),
        "settled": len(settled_list),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "units": round(units, 4),
        "by_rule": by_rule,
    }


def history(*, path: Optional[str] = None, limit: int = 50) -> list[dict]:
    """All candidates, newest first, with settlement if available.

    Args:
        path: Ledger path (defaults to LIVE_STORE).
        limit: Maximum results (default 50).

    Returns:
        List of candidates with 'settlement' field (dict or None), newest first.
    """
    ledger = _ledger(path)

    settled_by_key = {}
    for row in ledger.read():
        if row.get("kind") == KIND_SETTLED:
            key = (row.get("rule_id"), row.get("sport"), row.get("game_id"))
            settled_by_key[key] = row

    candidates_list = []
    for row in ledger.read():
        if row.get("kind") == KIND_CANDIDATE:
            candidates_list.append(row)

    # Sort newest first
    candidates_list.sort(key=lambda r: r.get("observed_utc") or "", reverse=True)

    result = []
    for candidate in candidates_list[:limit]:
        key = (candidate.get("rule_id"), candidate.get("sport"), candidate.get("game_id"))
        settlement = settled_by_key.get(key)
        result.append({
            **candidate,
            "settlement": settlement,
        })

    return result


def verify(*, path: Optional[str] = None):
    """Verify the chain integrity.

    Returns:
        VerifyResult from HashChainLedger.verify().
    """
    return _ledger(path).verify()


def _main(argv=None):
    """CLI entry point: `python -m src.appstate.live_ledger settle`.

    Prints ONLY the counts line -- never wins/losses/units -- so this is
    what `scripts/daily_loop.sh` shells out to for R16-L7's nightly
    settlement pass.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="live_ledger")
    sub = parser.add_subparsers(dest="cmd", required=True)
    settle_p = sub.add_parser(
        "settle", help="Settle yesterday and any unsettled date in the last 7 days")
    settle_p.add_argument("--sport", default="mlb", choices=["mlb"],
                          help="Only mlb is wired to an authoritative final source today")

    args = parser.parse_args(argv)

    if args.cmd == "settle":
        totals = settle_recent()
        print(
            f"graded={totals['graded']} voids={totals['voids']} "
            f"unsettled={totals['unsettled']} dates_checked={totals['dates_checked']}"
        )
        return 0

    return 1


if __name__ == "__main__":
    import sys
    sys.exit(_main())
