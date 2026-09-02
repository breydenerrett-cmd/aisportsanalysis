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

WHY THIS REUSES prop_listing'S SLOT LOGIC RATHER THAN RE-DERIVING IT
----------------------------------------------------------------------
The two layers are meant to observe the SAME games at the SAME instants
(`SLOTS`, anchored to first pitch) so a later read can compare "was it
listed" against "what did it cost" without reconciling two independent
sampling grids. Reusing `prop_listing._due_slot` / `_choose` /
`_events_by_slate_date` -- rather than copying them -- makes drift between
the two grids impossible by construction, not just unlikely.

BUDGET
------
Same shape as prop_listing: 3 games/day x 6 slots = 18 credits/day, hard
per-slate-date cap enforced from THIS store's own marker rows (never from an
in-memory counter, so a killed run cannot lose track of its own spend), the
absolute 5,000 floor, and the same probe reserve -- this layer yields before
baseline capture is touched, and is skipped first when a day approaches the
overall ~132/day envelope. Off unless PROP_PRICES=1.

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

# Reused, not re-derived -- see module docstring. Importing rather than
# copying the numbers means "3 games/day x 6 slots" can never drift between
# the listing audit and this layer.
SLOTS = prop_listing.SLOTS
GAMES_PER_DAY = prop_listing.GAMES_PER_DAY
MAX_ATTEMPTS_PER_SLOT = prop_listing.MAX_ATTEMPTS_PER_SLOT
MAX_FETCHES_PER_RUN = prop_listing.MAX_FETCHES_PER_RUN
CREDIT_FLOOR = prop_listing.CREDIT_FLOOR
PROBE_RESERVE = prop_listing.PROBE_RESERVE

# 3 games x 6 slots, identical shape to prop_listing's day cap.
DAILY_CREDIT_CAP = GAMES_PER_DAY * len(SLOTS)

ENV_SWITCH = "PROP_PRICES"


class PropPricesError(RuntimeError):
    """Raised when the store or the clock is unusable. Never for a network fault."""


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def run(env=None, now=None, store=DEFAULT_STORE, provider=odds_provider,
        credit_floor=CREDIT_FLOOR, probe_reserve=PROBE_RESERVE,
        daily_cap=DAILY_CREDIT_CAP) -> dict:
    """One scheduled pass. Returns a report; never raises for a network fault.

    Everything injectable is injectable so the tests spend nothing:
    `provider` stands in for the odds module, `now` for the clock, `store`
    for the file -- the same contract prop_listing.run() offers.
    """
    clock_now = _now(now)
    report = {"observed_utc": _utc_iso(clock_now), "fetches": 0, "rows": 0,
              "markers": 0, "credits_spent": 0, "errors": [], "escalate": [],
              "events_due": 0, "skipped": None}

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
    creditlog.log(remaining, quota_now.get("last"), "prop_prices.run")
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
    samples = _samples(rows_on_disk)
    attempts = _attempts(rows_on_disk)
    per_date_spend = credits_spent_by_date(rows_on_disk)

    pending = []
    for game_date in sorted(by_date):
        slate = by_date[game_date]
        due = [e for e in slate if prop_listing._due_slot(e, clock_now) is not None]
        if not due:
            continue
        chosen = samples.get(game_date)
        if chosen is None:
            chosen = prop_listing._choose(slate)
            append([{
                "observed_utc": _utc_iso(clock_now),
                "schedule_version": SCHEDULE_VERSION,
                "sample": True,
                "game_date": game_date,
                "slate_size": len(slate),
                "rule": "earliest, median, latest by commence_time",
                "event_ids": chosen,
            }], store)
            samples[game_date] = chosen
        for event in slate:
            if event.get("id") not in chosen:
                continue
            slot = prop_listing._due_slot(event, clock_now)
            if slot is None:
                continue
            key = (event.get("id"), slot)
            if attempts.get(key, 0) >= MAX_ATTEMPTS_PER_SLOT:
                continue
            pending.append((game_date, event, slot))

    report["events_due"] = len(pending)

    for game_date, event, slot in pending:
        if report["fetches"] >= MAX_FETCHES_PER_RUN:
            report["escalate"].append(
                "ESCALATE: prop-prices capture hit its per-run fetch ceiling "
                f"({MAX_FETCHES_PER_RUN}) -- more events came due than the "
                "design expects; check the sampler before the next run")
            break
        spent_today = per_date_spend.get(game_date, 0)
        if spent_today + 1 > daily_cap:
            report["escalate"].append(
                f"ESCALATE: prop-prices capture would exceed its {daily_cap}"
                f"-credit day cap on {game_date} ({spent_today} spent); slot "
                f"{slot} on {event.get('id')} was NOT fetched")
            continue

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


def _samples(rows) -> dict:
    out = {}
    for row in rows or []:
        if row.get("sample") and row.get("game_date"):
            out.setdefault(row["game_date"], list(row.get("event_ids") or []))
    return out


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
