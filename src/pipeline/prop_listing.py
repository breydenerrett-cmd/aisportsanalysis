"""Prop LISTING audit: does a book list pitcher strikeouts, and when.

WHAT THIS IS, AND THE LINE IT DOES NOT CROSS
--------------------------------------------
This is a FEASIBILITY MEASUREMENT, approved by Brey on 2026-08-31 and bounded
by `docs/COLLECTION_POLICY.md` ("Feasibility measurement vs research
collection") and designed in `docs/PROBE_PROP_LISTING.md`. It records whether
the `pitcher_strikeouts` market is LISTED, by which books, at which of our own
poll slots, and what each book's `last_update` says. That is the whole product.

It stores NO PRICES and NO POINTS. Not because prices are expensive here --
they arrive in the same response at the same credit -- but because a listing
audit that quietly accumulated a prop price history would be a research
collection wearing a feasibility label, and the approval was explicitly for the
narrow thing. There is no analysis code in this module and none belongs here:
the comparison against lineup-post times is made at read time, elsewhere, from
these rows and `rosterwatch.events()`.

WHY MARKERS ARE WRITTEN ON EVERY SUCCESSFUL FETCH
-------------------------------------------------
Rosterwatch's rule, for rosterwatch's reason. A poll that fetched cleanly and
found no book listing the market writes a marker saying so, so that "we looked
and it was not listed" is distinguishable from "we never looked". Without that,
every listing-time bracket widens to uselessness and the audit's one question
cannot be answered. The marker is written whether or not any book listed the
market -- `books_listing: 0` is the absence proof, and a non-zero count on the
same row is what makes the store's own spend auditable (one marker == one
billed fetch).

A fetch that FAILED writes an error row and no marker. The bracket then widens
honestly instead of claiming a look that did not happen.

WHAT BOUNDS THE SPEND
---------------------
Three limits, checked before any call, in this order: the absolute credit floor
(5,000, never worked around), the per-slate-date cap (18 = 3 games x 6 slots,
so it binds only when something has gone wrong), and the cumulative hard cap
(400). Cumulative spend is read back out of the store's own marker rows rather
than trusted from arithmetic, because the store is the only record that
survives a container.

Resumable by construction: a slot already recorded for an event is never
re-fetched, so a run that dies halfway costs at most the fetches it had already
made, and the next run picks up exactly where it stopped.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paths import processed_path
from src.capture import budget as budget_module
from src.pipeline import creditlog
from src.pipeline import snapshots
from src.providers import odds as odds_provider

LOG = logging.getLogger(__name__)

DEFAULT_STORE = processed_path("prop_listing.jsonl")

MARKET = "pitcher_strikeouts"

# The one adaptation the design permits (shifting the grid one step earlier if
# most games turn out left-censored at S1) becomes version 2. Every row carries
# the version so two regimes can never be silently pooled at read time.
SCHEDULE_VERSION = 1

# Poll slots, anchored to first pitch, minutes before it. Executed at the first
# scheduled run at or after each offset -- the hourly cadence is the grid's
# resolution, and the row's observed_utc is the truth; the label is a schedule
# name, not a claim about the exact moment.
SLOTS = (
    ("T-12h", 720),
    ("T-8h", 480),
    ("T-6h", 360),
    ("T-4h", 240),
    ("T-2h", 120),
    ("T-30m", 30),
)

# Games sampled per slate date, chosen deterministically (earliest, median,
# latest first pitch). Deterministic selection is not a nicety: hand-picking
# "games likely to have props" would manufacture the coverage number this audit
# exists to measure.
GAMES_PER_DAY = 3

# 3 games x 6 slots. Binds only on malfunction, which is the point of it.
DAILY_CREDIT_CAP = GAMES_PER_DAY * len(SLOTS)

# Cumulative ceiling from the design. Reaching it stops the audit and reports
# whatever the store holds, including "underpowered, N = 21".
HARD_CAP = 400

# The absolute floor, identical to dense's. Never worked around.
CREDIT_FLOOR = budget_module.CREDIT_FLOOR

# The design's reserve: the floor plus a round day of headroom. Below this the
# audit skips itself rather than spend the margin that pays for baseline
# capture -- it is the LOWEST priority layer in the policy's order of
# protection, and it yields before any market is dropped or the grid thins.
PROBE_RESERVE = 5200

# A run may not fetch more than this, whatever the arithmetic above concludes.
# Two slate dates can legitimately have events due in one run (tonight's late
# games at T-2h, tomorrow's early games at T-12h), so the honest ceiling is two
# days' worth of sampled games, and anything past it is a bug spending money.
MAX_FETCHES_PER_RUN = 2 * GAMES_PER_DAY

# Attempts (successful or failed) allowed per event per slot. A retry inside the
# same slot band is right after a transient failure; a permanently unreachable
# event id must not re-bill every hour of that band.
MAX_ATTEMPTS_PER_SLOT = 2

ENV_SWITCH = "PROP_LISTING_AUDIT"


class PropListingError(RuntimeError):
    """Raised when the store or the clock is unusable. Never for weather."""


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def run(env=None, now=None, store=DEFAULT_STORE, provider=odds_provider,
        credit_floor=CREDIT_FLOOR, hard_cap=HARD_CAP,
        credit_log_store=None) -> dict:
    """One scheduled pass. Returns a report; never raises for a network fault.

    Everything injectable is injectable so the tests spend nothing: `provider`
    stands in for the odds module, `now` for the clock, `store` for the
    file. `credit_log_store` is a separate seam from `store` -- it is the
    envelope check's own store (see `budget_module.can_spend`'s `store`
    kwarg), not this audit's row file; `None` keeps reading the real
    data/processed/credit_log.jsonl exactly as before this parameter existed.
    """
    clock_now = _now(now)
    report = {"observed_utc": _utc_iso(clock_now), "fetches": 0, "rows": 0,
              "markers": 0, "credits_spent": 0, "errors": [], "escalate": [],
              "events_due": 0, "skipped": None}

    status = provider.status(env)
    if not status.get("configured"):
        report["skipped"] = "not configured"
        return report

    rows_on_disk = read(store)
    cumulative = credits_spent(rows_on_disk)
    report["credits_cumulative_before"] = cumulative
    if cumulative >= hard_cap:
        report["skipped"] = "hard cap"
        report["escalate"].append(
            f"ESCALATE: prop-listing audit reached its {hard_cap}-credit cap "
            f"({cumulative} spent) -- stop it and report what the store holds")
        return report

    # The floor is checked BEFORE spending anything, against the free sports
    # endpoint. Discovering you are broke by going broke is not a floor.
    try:
        quota_now = provider.quota(env)
    except provider.OddsProviderError as exc:
        report["skipped"] = "quota unreadable"
        report["errors"].append(str(exc))
        return report
    remaining = quota_now.get("remaining")
    creditlog.log(remaining, quota_now.get("last"), "prop_listing.run")
    report["credits_remaining"] = remaining
    if remaining is not None and remaining <= credit_floor:
        report["skipped"] = "credit floor"
        return report
    if remaining is not None and remaining < PROBE_RESERVE:
        # Not the floor itself: the audit yields first, before any market is
        # dropped from baseline or the grid thins.
        report["skipped"] = "probe reserve"
        return report

    # Budget guard (docs/planning/attack.md F13/S17): "prop_listing_feasibility"
    # is a measured family (1 credit/event/slot). Passes the `remaining` this
    # call already read rather than re-reading credit_log.jsonl -- see
    # dense.run's identical comment on why. `store=credit_log_store` gives the
    # ENVELOPE half of this same decision the same hermetic seam (see
    # `credit_log_store`'s docstring above); it is None (real disk) unless a
    # caller overrides it.
    decision = budget_module.can_spend("prop_listing_feasibility", 1,
                                        remaining=remaining, store=credit_log_store)
    if not decision.allowed:
        print(f"prop_listing.run: {decision.reason}")
        report["skipped"] = decision.reason
        return report

    try:
        listed = provider.list_events(env)  # free
    except provider.OddsProviderError as exc:
        report["skipped"] = "events unreadable"
        report["errors"].append(str(exc))
        return report

    by_date = _events_by_slate_date(listed)
    samples = _samples(rows_on_disk)
    attempts = _attempts(rows_on_disk)
    per_date_spend = credits_spent_by_date(rows_on_disk)

    # Rows are appended as they are earned, not batched to the end of the run.
    # A batch would mean a run killed after its fetches had already been billed
    # leaves no record of the spend -- credits gone with nothing to show, and a
    # store that can no longer audit itself. One append per event is three file
    # opens on a normal run.
    pending = []
    for game_date in sorted(by_date):
        slate = by_date[game_date]
        due = [e for e in slate if _due_slot(e, clock_now) is not None]
        if not due:
            continue  # nothing on this date is inside the grid yet
        chosen = samples.get(game_date)
        if chosen is None:
            chosen = _choose(slate)
            append([{
                "observed_utc": _utc_iso(clock_now),
                "schedule_version": SCHEDULE_VERSION,
                "sample": True,
                "game_date": game_date,
                "slate_size": len(slate),
                "rule": "earliest, median, latest by commence_time",
                # Which slot the date's earliest listed game was in when the
                # sample was drawn. On a normal day this is T-12h: the grid
                # opens 12h before the first pitch of the day, when the whole
                # slate is listed. Anything later means the sample was drawn
                # from a PARTIAL slate -- /events had already dropped the games
                # that started -- so the three picks are the earliest, median
                # and latest of what was left, not of the day. Recorded rather
                # than corrected, so a reader can exclude such a date instead
                # of inheriting a coverage number skewed toward night games.
                "selected_at_slot": max(
                    (_due_slot(e, clock_now) for e in due),
                    key=dict(SLOTS).get),
                "event_ids": chosen,
            }], store)
            samples[game_date] = chosen
        for event in slate:
            if event.get("id") not in chosen:
                continue
            slot = _due_slot(event, clock_now)
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
                "ESCALATE: prop-listing audit hit its per-run fetch ceiling "
                f"({MAX_FETCHES_PER_RUN}) -- more events came due than the "
                "design expects; check the sampler before the next run")
            break
        spent_today = per_date_spend.get(game_date, 0)
        if spent_today + 1 > DAILY_CREDIT_CAP:
            report["escalate"].append(
                f"ESCALATE: prop-listing audit would exceed its {DAILY_CREDIT_CAP}"
                f"-credit day cap on {game_date} ({spent_today} spent); slot "
                f"{slot} on {event.get('id')} was NOT fetched")
            continue
        if cumulative + 1 > hard_cap:
            report["escalate"].append(
                f"ESCALATE: prop-listing audit reached its {hard_cap}-credit cap "
                f"({cumulative} spent) -- stop it and report what the store holds")
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
        # A missing counter is charged as 1 against the budget and stored as
        # null. Guessing DOWN would let a broken header silently unbound the
        # spend; writing a 1 we did not read would be inventing a measurement.
        charged = 1 if billed is None else billed
        cumulative += charged
        per_date_spend[game_date] = per_date_spend.get(game_date, 0) + charged
        report["fetches"] += 1
        report["credits_spent"] += charged

        listing = _listing_rows(payload, event, slot, observed, billed)
        # The marker goes LAST, after the listing rows it summarises. A crash
        # between them then costs a marker, which widens a bracket honestly;
        # the reverse order would leave a marker claiming books whose rows were
        # never written.
        append(listing + [{
            "observed_utc": observed,
            "schedule_version": SCHEDULE_VERSION,
            "slot": slot,
            "event_id": payload.get("id") or event.get("id"),
            "commence_time": payload.get("commence_time") or event.get("commence_time"),
            "game_date": game_date,
            "poll": True,
            "books_listing": len({r["book"] for r in listing}),
            "credits_last": billed,
        }], store)
        report["markers"] += 1
        report["rows"] += len(listing)

    report["credits_cumulative"] = cumulative
    if cumulative >= hard_cap and not report["escalate"]:
        # Reported on the run that reaches the cap, not on the next one, so the
        # transcript that spent the last credit is the transcript that says so.
        report["escalate"].append(
            f"ESCALATE: prop-listing audit reached its {hard_cap}-credit cap "
            f"({cumulative} spent) -- stop it and report what the store holds")
    return report


def _listing_rows(payload, event, slot, observed, billed) -> list:
    """One row per book per pitcher that IS listed. No prices, no points.

    A book that does not list the market produces no row at all; the marker's
    `books_listing` count is what records the absence. Recording a book as
    "listed: false" would require knowing the full universe of books, which no
    response states -- the response says who listed, not who declined.
    """
    rows = []
    for book in payload.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != MARKET:
                continue
            players = []
            for outcome in market.get("outcomes") or []:
                # The API puts the pitcher in `description` and Over/Under in
                # `name`. Only the pitcher is kept -- the side, the price and
                # the point are exactly the prop-price data this audit is not
                # authorized to collect.
                player = outcome.get("description")
                if player and player not in players:
                    players.append(player)
            if not players:
                players = [None]
            for player in players:
                rows.append({
                    "observed_utc": observed,
                    "schedule_version": SCHEDULE_VERSION,
                    "slot": slot,
                    "event_id": payload.get("id") or event.get("id"),
                    "commence_time": (payload.get("commence_time")
                                      or event.get("commence_time")),
                    "home_team": payload.get("home_team") or event.get("home_team"),
                    "away_team": payload.get("away_team") or event.get("away_team"),
                    "market": MARKET,
                    "book": book.get("key"),
                    "listed": True,
                    "book_last_update": market.get("last_update"),
                    "player": player,
                    "credits_last": billed,
                })
    return rows


# ---------------------------------------------------------------------------
# Sampling and slotting
# ---------------------------------------------------------------------------

def _choose(slate) -> list:
    """Earliest, median, latest first pitch. Ties broken by event id.

    Sorting by (commence_time, id) rather than commence_time alone makes the
    selection reproducible when several games share a first pitch, which is the
    normal case on an MLB slate -- otherwise the sample would depend on the
    order the API happened to return.
    """
    ordered = sorted(slate, key=lambda e: ((e.get("commence_time") or ""),
                                           (e.get("id") or "")))
    if len(ordered) <= GAMES_PER_DAY:
        return [e.get("id") for e in ordered]
    picks = [0, (len(ordered) - 1) // 2, len(ordered) - 1]
    return [ordered[i].get("id") for i in picks]


def _due_slot(event, now):
    """The slot this event is currently in, or None.

    The current slot is the SMALLEST offset whose moment has passed -- at T-7h
    the T-8h slot is the live one, and the T-12h window is gone. A missed window
    is gone; back-filling it under its old label would be a fabricated
    observation time.
    """
    commence = _parse_iso(event.get("commence_time"))
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


def _events_by_slate_date(listed) -> dict:
    out = {}
    for event in listed or []:
        commence = _parse_iso(event.get("commence_time"))
        if commence is None or not event.get("id"):
            continue
        out.setdefault(_slate_date(commence), []).append(event)
    return out


def _eastern():
    """MLB's official timezone; a fixed -04:00 when no zone database exists.

    Same choice, and the same reasoning, as rosterwatch: the slate date this
    store groups by has to be the one the lineup store uses, or the read-time
    join between them lines up two different days.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def _slate_date(moment) -> str:
    return moment.astimezone(_EASTERN).date().isoformat()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def append(rows, path=DEFAULT_STORE) -> int:
    """Append rows as JSON Lines. Never rewrites, never de-duplicates in place.

    A run killed mid-write leaves a final line with no newline; appending onto
    that fragment would corrupt the interrupted row AND the new one. The guard
    is `snapshots._ends_ragged`, the same one the odds stores use, so all three
    forward stores fail the same way and are read by the same rules.
    """
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
    """Every row in the store. A corrupt line is logged and skipped.

    The realistic cause of a bad line is an interrupted append, and a months-long
    unattended audit must not be permanently poisoned by one power cut. The cost
    is bounded: a lost marker widens a bracket, which is honest.
    """
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
            LOG.warning("prop_listing: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


def credits_spent(rows) -> int:
    """Cumulative spend, read from the store's own marker rows.

    One marker == one billed fetch, so markers are the ledger. Listing rows
    carry `credits_last` too, but many of them share a single response and
    summing those would multiply the spend by the number of books.

    A marker with a null `credits_last` (header missing) counts as 1 -- the same
    conservative charge the run applied when it made the call.
    """
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
            commence = _parse_iso(row.get("commence_time"))
            game_date = _slate_date(commence) if commence else "unknown"
        billed = row.get("credits_last")
        out[game_date] = out.get(game_date, 0) + (1 if billed is None else billed)
    return out


def _samples(rows) -> dict:
    """The frozen per-date sample, replayed from the store.

    Re-choosing every run would scatter the spend: the API drops games from
    /events once they start, so "the earliest game on the slate" is a different
    game at T-2h than it was at T-12h. The first choice is written down and
    reused, which is also what makes the sample auditable after the fact.
    """
    out = {}
    for row in rows or []:
        if row.get("sample") and row.get("game_date"):
            out.setdefault(row["game_date"], list(row.get("event_ids") or []))
    return out


def _attempts(rows) -> dict:
    """(event_id, slot) -> attempts already made, successful or failed.

    A successful attempt is counted as the full allowance: a slot that has its
    marker is ANSWERED, and re-fetching it would buy a second reading of the
    same slot at the price of one that has not been read at all. Failures are
    counted one at a time, so a transient error is retried inside its band and a
    permanently unreachable event stops re-billing every hour.
    """
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
        raise PropListingError(
            "the clock must return a timezone-aware datetime; a naive observation "
            "time cannot honestly bracket a listing")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def enabled(env=None) -> bool:
    """The switch. Off unless PROP_LISTING_AUDIT says on.

    Read from the environment so `scripts/forward_capture.sh` holds the single
    obvious line that turns the audit off, and so turning it off never means
    editing a module that is also the evidence writer.
    """
    source = os.environ if env is None else env
    return (source.get(ENV_SWITCH) or "").strip().lower() in {"on", "1", "yes", "true"}


def _load_dotenv(path=None) -> None:
    """Read .env into os.environ. Values already exported win.

    A local copy rather than an import from src.cli: this module is run as a
    module by the capture script, and coupling the evidence writer to a private
    helper in the CLI would break capture the day that helper is renamed.
    """
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
    """Entry point for `python3 -m src.pipeline.prop_listing`.

    Prints one short block for the capture transcript. ESCALATE lines are the
    only ones a model needs to react to, and they are printed verbatim so the
    shell's grep and a human reading the log see the same text.
    """
    _load_dotenv()
    if not enabled():
        print(f"prop listing: off ({ENV_SWITCH} not set)")
        return 0
    report = run()
    if report.get("skipped"):
        print(f"prop listing: skipped: {report['skipped']}")
    else:
        print(f"prop listing: {report['fetches']} fetches, {report['rows']} listing "
              f"rows, {report['markers']} markers, {report['credits_spent']} credits "
              f"(cumulative {report.get('credits_cumulative')})")
    for error in report.get("errors") or []:
        print(f"  error: {error}")
    for line in report.get("escalate") or []:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
