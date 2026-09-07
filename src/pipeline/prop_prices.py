"""Pitcher-strikeout PROP PRICES: bounded spend, switched off by default.

WHAT THIS IS AND HOW IT DIFFERS FROM prop_listing.py
-----------------------------------------------------
`prop_listing.py` is a feasibility measurement: does a book list
`pitcher_strikeouts`, by which books, when -- no prices, no points, approved
narrowly on 2026-08-31 (docs/COLLECTION_POLICY.md, docs/PROBE_PROP_LISTING.md).

This module is the RESEARCH COLLECTION layer that measurement was explicitly
kept separate from: it stores the price AND the point per book per pitcher.
It is switched on under the owner-approved capture-now principle (CAPTURE
NOW, RESEARCH LATER -- docs/MASTER_PLAN.md Sec.1 claim 3, Appendix C.1 item
6: timestamped forward data cannot be bought retroactively) and bounded
exactly as docs/COLLECTION_POLICY.md's dated amendment states -- see that
file for the full accounting. It does NOT authorize a historical prop
purchase, which stays a hard approval gate.

TWO SLOTS PER GAME, FULL SLATE (not the 3-game sample the design started with)
--------------------------------------------------------------------------------
Originally this layer imported prop_listing's whole grid verbatim: 3 games
picked deterministically per day (`_choose`), each polled at 6 slots
(T-12h..T-30m). That undersampled exactly the way derivative_markets.py did
for the same reason -- see `src/pipeline/derivative_markets.py`'s own "TWO
SLOTS PER GAME" section for the shared design. This layer now polls EVERY
game on the slate (no sampling) at the SAME two instants derivative_markets
uses: T-3h (matches `dense.WINDOW_MINUTES = 180`) and T-30m (the deepest
board). `SLOTS` below is this module's own copy of that two-entry grid --
duplicated, not imported from derivative_markets, so neither module takes an
import dependency on the other; both were built from the same design at the
same time and are meant to be read together, never silently diverge.

`_due_slot` is likewise this module's own function rather than
`prop_listing._due_slot`, because that function reads its own six-slot
`SLOTS` directly as a module global, not as a parameter -- it cannot be
pointed at a different grid without editing prop_listing.py, which is out of
this module's scope. `_events_by_slate_date` and `_parse_iso` stay imported
from prop_listing: both are generic (no dependency on which slot grid is in
use), so reusing them still makes drift in THOSE mechanics impossible by
construction.

BUDGET
------
Every game, both slots: for a normal MLB slate (up to 15 games, real max
since only 30 teams play at once) that is at most 15 x 2 x 1 credit/event =
30 credits/day (pitcher_props is 1 credit/event per
config/capture_families.json). The per-slate-date cap is computed from the
day's actual slate size (`len(slate) * len(SLOTS)`) rather than a fixed
constant, so it scales with the real slate instead of silently truncating a
15-game day sized for the old 3-game sample. Enforced from THIS store's own
marker rows (never from an in-memory counter, so a killed run cannot lose
track of its own spend), gated per-event through `budget.can_spend` exactly
like derivative_markets.py, plus the absolute 5,000 floor and the same probe
reserve -- this layer yields before baseline capture is touched, and is
skipped first when a day approaches the overall ~900/day envelope
(`budget.DAILY_ENVELOPE`). Off unless PROP_PRICES=1.

WHY A MARKER ROW EXISTS HERE TOO
----------------------------------
Copied from prop_listing's self-auditing pattern: one marker per billed
fetch, carrying `credits_last` as the API's own account of what that fetch
cost. Price rows can outnumber fetches many times over (one per book per
pitcher), so summing THEIR `credits_last` would multiply the measured spend
by the number of rows a single response happened to produce. The marker is
the ledger; the price rows are the product.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from src.paths import processed_path
from src.capture import budget as budget_module
from src.pipeline import creditlog
from src.pipeline import prop_listing
from src.pipeline import snapshots
from src.providers import odds as odds_provider

LOG = logging.getLogger(__name__)

DEFAULT_STORE = processed_path("prop_prices.jsonl")

MARKET = prop_listing.MARKET  # "pitcher_strikeouts"

# Carried so two regimes can never be silently pooled at read time, same
# reasoning as prop_listing.SCHEDULE_VERSION.
SCHEDULE_VERSION = 1

# Two capture instants per game, anchored to first pitch, minutes before it.
# This module's OWN copy of the same two-entry grid
# src/pipeline/derivative_markets.py uses (see that module's "TWO SLOTS PER
# GAME" docstring section) -- duplicated, not imported, so neither module
# takes a dependency on the other; see this module's own docstring for why
# prop_listing.SLOTS (six slots, three sampled games) is no longer reused.
SLOTS = (
    ("T-3h", 180),
    ("T-30m", 30),
)

# Generic constants with no dependency on which slot grid is in use --
# still safe, and still correct by construction, to reuse from prop_listing.
MAX_ATTEMPTS_PER_SLOT = prop_listing.MAX_ATTEMPTS_PER_SLOT
CREDIT_FLOOR = prop_listing.CREDIT_FLOOR
PROBE_RESERVE = prop_listing.PROBE_RESERVE

# Credits budgeted per game per day: one fetch per slot, and pitcher_props
# costs 1 credit/event (config/capture_families.json). The per-date cap
# used at runtime is this times THAT DAY's own slate size, not a fixed
# sample size -- see `run()`.
CREDITS_PER_GAME_PER_DAY = len(SLOTS)

# A run may not fetch more than this, whatever the arithmetic concludes --
# a runaway guard, not a coverage limit (see module docstring). Sized above
# the real max of 15 concurrent MLB games (30 teams), with headroom for a
# doubleheader and for two slate dates legitimately having events due in one
# run (tonight's late games at T-30m, tomorrow's early games at T-3h).
MAX_EVENTS_PER_SLATE = 20
MAX_FETCHES_PER_RUN = 2 * MAX_EVENTS_PER_SLATE

ENV_SWITCH = "PROP_PRICES"


class PropPricesError(RuntimeError):
    """Raised when the store or the clock is unusable. Never for a network fault."""


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def run(env=None, now=None, store=DEFAULT_STORE, provider=odds_provider,
        credit_floor=CREDIT_FLOOR, probe_reserve=PROBE_RESERVE,
        credit_log_store=None) -> dict:
    """One scheduled pass. Returns a report; never raises for a network fault.

    Everything injectable is injectable so the tests spend nothing:
    `provider` stands in for the odds module, `now` for the clock, `store`
    for the file -- the same contract prop_listing.run() offers.
    `credit_log_store` is the same envelope-check seam prop_listing.run and
    dense.run carry: None (default) reads the real credit_log.jsonl.
    """
    clock_now = _now(now)
    report = {"observed_utc": _utc_iso(clock_now), "fetches": 0, "rows": 0,
              "markers": 0, "credits_spent": 0, "errors": [], "escalate": [],
              "events_due": 0, "skipped": None, "budget_reasons": {}}

    status = provider.status(env)
    if not status.get("configured"):
        report["skipped"] = "not configured"
        return report

    # The floor is checked BEFORE spending anything, against the free sports
    # endpoint -- same ordering prop_listing and dense both rely on.
    try:
        quota_now = provider.quota(env)
    except provider.OddsProviderError as exc:
        report["skipped"] = "quota unreadable"
        report["errors"].append(str(exc))
        return report
    remaining = quota_now.get("remaining")
    creditlog.log(remaining, quota_now.get("last"), "prop_prices.run",
                  budget_band=budget_module.LIVE_CAPTURE)
    report["credits_remaining"] = remaining
    if remaining is not None and remaining <= credit_floor:
        report["skipped"] = "credit floor"
        return report
    if remaining is not None and remaining < probe_reserve:
        # Lowest-priority research layer: it yields before baseline capture
        # or the listing audit gives up anything.
        report["skipped"] = "probe reserve"
        return report

    try:
        listed = provider.list_events(env)  # free
    except provider.OddsProviderError as exc:
        report["skipped"] = "events unreadable"
        report["errors"].append(str(exc))
        return report

    rows_on_disk = read(store)
    by_date = prop_listing._events_by_slate_date(listed)
    attempts = _attempts(rows_on_disk)
    per_date_spend = credits_spent_by_date(rows_on_disk)

    # Full slate, not a 3-game sample: every event on each date's slate that
    # is currently due gets a slot. cap_for_date scales with that day's OWN
    # slate size (CREDITS_PER_GAME_PER_DAY per game), so a 15-game day is
    # never truncated by a cap sized for the old 3-game design.
    pending = []
    for game_date in sorted(by_date):
        slate = by_date[game_date]
        cap_for_date = len(slate) * CREDITS_PER_GAME_PER_DAY
        for event in slate:
            slot = _due_slot(event, clock_now)
            if slot is None:
                continue
            key = (event.get("id"), slot)
            if attempts.get(key, 0) >= MAX_ATTEMPTS_PER_SLOT:
                continue
            pending.append((game_date, event, slot, cap_for_date))

    report["events_due"] = len(pending)

    # Budget guard (docs/planning/attack.md F13/S17), checked per event
    # about to be fetched -- the same shape derivative_markets.py uses,
    # rather than one upfront estimate for the whole day. "pitcher_props"
    # IS a measured family (config/capture_families.json: 1 credit/event),
    # so a real PROBE_REQUIRED here would mean that measurement was
    # invalidated; it is surfaced (printed, recorded) and stops this run's
    # remaining fetches without retrying each one, since every other event
    # is equally unmeasured. A floor or envelope refusal, unlike
    # PROBE_REQUIRED, is absolute and also stops the run.
    probe_required = False
    for game_date, event, slot, cap_for_date in pending:
        if probe_required:
            break
        if report["fetches"] >= MAX_FETCHES_PER_RUN:
            report["escalate"].append(
                "ESCALATE: prop-prices capture hit its per-run fetch ceiling "
                f"({MAX_FETCHES_PER_RUN}) -- more events came due than the "
                "design expects; check the plan before the next run")
            break
        spent_today = per_date_spend.get(game_date, 0)
        if spent_today + 1 > cap_for_date:
            report["escalate"].append(
                f"ESCALATE: prop-prices capture would exceed its {cap_for_date}"
                f"-credit day cap on {game_date} ({spent_today} spent); slot "
                f"{slot} on {event.get('id')} was NOT fetched")
            continue

        decision = budget_module.can_spend(
            "pitcher_props", 1, remaining=remaining, store=credit_log_store)
        report["budget_reasons"][event.get("id")] = decision.reason
        if not decision.allowed:
            print(f"prop_prices.run: {event.get('id')} {slot}: {decision.reason}")
            report["budget_reason"] = decision.reason
            if decision.reason.startswith("PROBE_REQUIRED"):
                probe_required = True
                continue
            report["escalate"].append(f"prop_prices: stopped -- {decision.reason}")
            break

        observed = _utc_iso(_now(now))
        try:
            payload, usage = provider.fetch_event_odds_with_usage(
                event.get("id"), markets=(MARKET,), env=env)
        except provider.OddsProviderError as exc:
            append([{
                "observed_utc": observed,
                "schedule_version": SCHEDULE_VERSION,
                "slot": slot,
                "event_id": event.get("id"),
                "game_date": game_date,
                "error": str(exc),
            }], store)
            report["errors"].append(f"{event.get('id')} {slot}: {exc}")
            continue

        billed = (usage or {}).get("last")
        charged = 1 if billed is None else billed
        per_date_spend[game_date] = per_date_spend.get(game_date, 0) + charged
        remaining = None if remaining is None else remaining - charged
        report["fetches"] += 1
        report["credits_spent"] += charged

        prices = _price_rows(payload, event, slot, observed, billed, game_date)
        append(prices + [{
            "observed_utc": observed,
            "schedule_version": SCHEDULE_VERSION,
            "slot": slot,
            "event_id": payload.get("id") or event.get("id"),
            "commence_time": payload.get("commence_time") or event.get("commence_time"),
            "game_date": game_date,
            "poll": True,
            "books_priced": len({r["book"] for r in prices}),
            "credits_last": billed,
        }], store)
        report["markers"] += 1
        report["rows"] += len(prices)

    report["credits_cumulative"] = credits_spent(read(store))
    return report


def _price_rows(payload, event, slot, observed, billed, game_date) -> list:
    """One row per book per pitcher, carrying the price AND the point.

    Over/Under outcomes for the same pitcher share one point (the line);
    a response missing one side still yields a row with that side None
    rather than being dropped, since a book quoting only Over is itself a
    fact worth recording, not an error to discard.
    """
    rows = []
    for book in payload.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != MARKET:
                continue
            by_player = {}
            for outcome in market.get("outcomes") or []:
                player = outcome.get("description")
                if not player:
                    continue
                entry = by_player.setdefault(
                    player, {"point": None, "over_price": None, "under_price": None})
                if outcome.get("point") is not None:
                    entry["point"] = outcome.get("point")
                side = outcome.get("name")
                if side == "Over":
                    entry["over_price"] = outcome.get("price")
                elif side == "Under":
                    entry["under_price"] = outcome.get("price")
            for player, prices in by_player.items():
                rows.append({
                    "observed_utc": observed,
                    "schedule_version": SCHEDULE_VERSION,
                    "slot": slot,
                    "event_id": payload.get("id") or event.get("id"),
                    "game_date": game_date,
                    "commence_time": (payload.get("commence_time")
                                      or event.get("commence_time")),
                    "home_team": payload.get("home_team") or event.get("home_team"),
                    "away_team": payload.get("away_team") or event.get("away_team"),
                    "market": MARKET,
                    "book": book.get("key"),
                    "book_last_update": market.get("last_update"),
                    "player": player,
                    "point": prices["point"],
                    "over_price": prices["over_price"],
                    "under_price": prices["under_price"],
                    "credits_last": billed,
                })
    return rows


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def append(rows, path=DEFAULT_STORE) -> int:
    """Append rows as JSON Lines. Never rewrites, never de-duplicates in place."""
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if snapshots._ends_ragged(target):
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def read(path=DEFAULT_STORE) -> list:
    """Every row in the store. A corrupt line is logged and skipped."""
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("prop_prices: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


def credits_spent(rows) -> int:
    """Cumulative spend, read from the store's own marker rows. See module docstring."""
    total = 0
    for row in rows or []:
        if not row.get("poll"):
            continue
        billed = row.get("credits_last")
        total += 1 if billed is None else billed
    return total


def credits_spent_by_date(rows) -> dict:
    out = {}
    for row in rows or []:
        if not row.get("poll"):
            continue
        game_date = row.get("game_date")
        if game_date is None:
            commence = prop_listing._parse_iso(row.get("commence_time"))
            game_date = prop_listing._slate_date(commence) if commence else "unknown"
        billed = row.get("credits_last")
        out[game_date] = out.get(game_date, 0) + (1 if billed is None else billed)
    return out


def _due_slot(event, now):
    """The slot this event is currently in, or None.

    The current slot is the SMALLEST offset whose moment has passed -- at
    T-2h the T-3h slot is the live one; past T-30m, or past first pitch,
    nothing is due. Identical rule to `prop_listing._due_slot`, duplicated
    (not imported) because that function reads its own module-level
    six-slot `SLOTS` directly rather than taking one as a parameter -- see
    module docstring. A missed window is gone: this never back-fills a slot
    whose moment has already passed under a different label.
    """
    commence = prop_listing._parse_iso(event.get("commence_time"))
    if commence is None:
        return None
    minutes = (commence - now).total_seconds() / 60.0
    if minutes <= 0:
        return None  # first pitch has passed; nothing here is worth a credit
    current = None
    for name, offset in SLOTS:
        if minutes <= offset:
            current = name
    return current


def _attempts(rows) -> dict:
    out = {}
    for row in rows or []:
        if row.get("poll"):
            weight = MAX_ATTEMPTS_PER_SLOT
        elif row.get("error"):
            weight = 1
        else:
            continue
        key = (row.get("event_id"), row.get("slot"))
        out[key] = out.get(key, 0) + weight
    return out


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise PropPricesError(
            "the clock must return a timezone-aware datetime; a naive "
            "observation time cannot honestly bracket a price")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def enabled(env=None) -> bool:
    """The switch. Off unless PROP_PRICES=1 (or another truthy spelling)."""
    source = os.environ if env is None else env
    return (source.get(ENV_SWITCH) or "").strip().lower() in {"on", "1", "yes", "true"}


def _load_dotenv(path=None) -> None:
    """Read .env into os.environ. Values already exported win."""
    env_file = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv=None) -> int:
    """Entry point for `python3 -m src.pipeline.prop_prices`."""
    _load_dotenv()
    if not enabled():
        print(f"prop prices: off ({ENV_SWITCH} not set)")
        return 0
    report = run()
    if report.get("skipped"):
        print(f"prop prices: skipped: {report['skipped']}")
    else:
        print(f"prop prices: {report['fetches']} fetches, {report['rows']} price "
              f"rows, {report['markers']} markers, {report['credits_spent']} credits "
              f"(cumulative {report.get('credits_cumulative')})")
    for error in report.get("errors") or []:
        print(f"  error: {error}")
    for line in report.get("escalate") or []:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
