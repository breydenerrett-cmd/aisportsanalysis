"""Batter-prop CAPTURE: owner decision 3 (2026-09-03) -- capture batter props
now, within the ~900/day envelope, with hard guards.

WHAT THIS IS
------------
Two families, both gated through `src.capture.budget.can_spend`:

- `batter_props_floor` (`budget.NON_DROPPABLE_FAMILY`): a deterministically
  rotated slice of `budget.NON_DROPPABLE_GAMES_PER_NIGHT` games per slate
  date, never dropped under a squeeze (see budget.py's module docstring,
  S17). Bypasses the floor/envelope check by design -- `can_spend` treats
  this family specially -- but still requires a measured cost before it
  spends (PROBE_REQUIRED otherwise).
- `batter_props_extra`: every other game on the slate, fully gated by the
  floor and the ~900/day envelope, and the family this project's DROP_ORDER
  sheds first among the batter surfaces (rank 7, just above featured).

Markets: `src.providers.odds.BATTER_MARKETS` (6 keys), fetched together in
one per-event call -- 6 credits/event/region at the default single region.

L0/L1 SHAPE
-----------
The raw provider payload is written by `odds_provider.fetch_event_odds_with_usage`
itself (`_write_raw_capture`, one JSON blob per call) -- this module never
duplicates that write. What this module owns is the L1 marker (one per
billed fetch, mirroring prop_prices.py's self-auditing convention) and the
L2 projection into `data/processed/batter_props.jsonl`: one row per
(event, market, book, selection, line, last_update).

IDEMPOTENCY
------------
Projected rows are keyed by (event_id, market, book, selection, line,
last_update) -- the same instant re-observed by a second run (or a retried
call after a partial write) produces the identical key and is skipped, not
duplicated. `selection` is the player id (falling back to the player name
when the provider does not carry one) plus the over/under side, matching
this project's SELECTION identity convention (src/board/ids.py).

Off unless BATTER_PROPS=1 (see scripts/capture_extras.sh).
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

RAW_STORE = processed_path("batter_props_raw.jsonl")
PROCESSED_STORE = processed_path("batter_props.jsonl")

MARKETS = odds_provider.BATTER_MARKETS
CREDITS_PER_EVENT = len(MARKETS)  # 6 markets x 1 default region = 6 credits/event

FLOOR_FAMILY = budget_module.NON_DROPPABLE_FAMILY  # "batter_props_floor"
EXTRA_FAMILY = "batter_props_extra"

# Extra (droppable) games captured per slate date, on top of the
# non-droppable floor's NON_DROPPABLE_GAMES_PER_NIGHT. Kept small and
# explicit -- this is the family DROP_ORDER sheds first among the batter
# surfaces, and a run that fetched an unbounded "rest of the slate" would
# make that drop meaningless.
EXTRA_GAMES_PER_NIGHT = 4

# A run may not fetch more than this many events, whatever the arithmetic
# above concludes -- the same per-run ceiling shape as prop_listing/prop_prices.
MAX_FETCHES_PER_RUN = budget_module.NON_DROPPABLE_GAMES_PER_NIGHT + EXTRA_GAMES_PER_NIGHT

CREDIT_FLOOR = prop_listing.CREDIT_FLOOR

ENV_SWITCH = "BATTER_PROPS"


class BatterPropsError(RuntimeError):
    """Raised when the store or the clock is unusable. Never for a network fault."""


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def run(env=None, now=None, store=RAW_STORE, processed_store=PROCESSED_STORE,
        provider=odds_provider, credit_floor=CREDIT_FLOOR) -> dict:
    """One scheduled pass. Returns a report; never raises for a network fault.

    Everything injectable is injectable so the tests spend nothing:
    `provider` stands in for the odds module, `now` for the clock, `store`/
    `processed_store` for the files -- the same contract prop_prices.run() offers.
    """
    clock_now = _now(now)
    report = {"observed_utc": _utc_iso(clock_now), "fetches": 0, "rows": 0,
              "markers": 0, "credits_spent": 0, "errors": [], "escalate": [],
              "games_due": 0, "skipped": None, "budget_reasons": {}}

    status = provider.status(env)
    if not status.get("configured"):
        report["skipped"] = "not configured"
        return report

    try:
        quota_now = provider.quota(env)
    except provider.OddsProviderError as exc:
        report["skipped"] = "quota unreadable"
        report["errors"].append(str(exc))
        return report
    remaining = quota_now.get("remaining")
    creditlog.log(remaining, quota_now.get("last"), "batter_props.run")
    report["credits_remaining"] = remaining
    if remaining is not None and remaining <= credit_floor:
        report["skipped"] = "credit floor"
        return report

    try:
        listed = provider.list_events(env)  # free
    except provider.OddsProviderError as exc:
        report["skipped"] = "events unreadable"
        report["errors"].append(str(exc))
        return report

    by_date = prop_listing._events_by_slate_date(listed)
    today = prop_listing._slate_date(clock_now)
    slate = by_date.get(today, [])
    if not slate:
        report["skipped"] = "no games on today's slate"
        return report

    rows_on_disk = read(store)
    done_today = _done_today(rows_on_disk, today)

    all_ids = sorted(e.get("id") for e in slate if e.get("id"))
    floor_ids = set(budget_module.rotated_floor_games(all_ids, today))
    by_id = {e.get("id"): e for e in slate if e.get("id")}

    # Floor games first, always -- the non-droppable surface must never be
    # starved by an "extra" game that happened to sort earlier.
    plan = []
    for event_id in sorted(floor_ids):
        if (event_id, today) in done_today:
            continue
        plan.append((FLOOR_FAMILY, by_id[event_id]))

    remaining_slots = EXTRA_GAMES_PER_NIGHT
    for event_id in all_ids:
        if remaining_slots <= 0:
            break
        if event_id in floor_ids:
            continue
        if (event_id, today) in done_today:
            continue
        plan.append((EXTRA_FAMILY, by_id[event_id]))
        remaining_slots -= 1

    report["games_due"] = len(plan)

    spent_this_run = 0
    for family, event in plan:
        if report["fetches"] >= MAX_FETCHES_PER_RUN:
            report["escalate"].append(
                "ESCALATE: batter-props capture hit its per-run fetch "
                f"ceiling ({MAX_FETCHES_PER_RUN}) -- more games came due "
                "than the design expects; check the plan before the next run")
            break

        decision = budget_module.can_spend(
            family, CREDITS_PER_EVENT, remaining=remaining,
            spent=budget_module.spent_today() if family != FLOOR_FAMILY else None)
        report["budget_reasons"][event.get("id")] = decision.reason
        if not decision.allowed:
            print(f"batter_props.run: {family} {event.get('id')}: {decision.reason}")
            if not decision.reason.startswith("PROBE_REQUIRED"):
                if family == FLOOR_FAMILY:
                    # The floor is non-droppable; a refusal here (only ever
                    # PROBE_REQUIRED per can_spend's own contract, since the
                    # floor bypasses the floor/envelope checks) is surfaced,
                    # never treated as a reason to stop the whole run.
                    continue
                # A droppable family hitting the floor or the envelope stops
                # this family for the rest of the run -- the whole point of
                # DROP_ORDER is that batter_props_extra yields first.
                report["escalate"].append(
                    f"batter_props: {family} stopped -- {decision.reason}")
                break
            # PROBE_REQUIRED: printed and recorded, never a hard stop --
            # same convention as prop_prices.run's own PROBE_REQUIRED path.

        observed = _utc_iso(_now(now))
        try:
            payload, usage = provider.fetch_event_odds_with_usage(
                event.get("id"), markets=MARKETS, env=env)
        except provider.OddsProviderError as exc:
            append([{
                "observed_utc": observed,
                "family": family,
                "event_id": event.get("id"),
                "game_date": today,
                "error": str(exc),
            }], store)
            report["errors"].append(f"{event.get('id')}: {exc}")
            continue

        billed = (usage or {}).get("last")
        charged = CREDITS_PER_EVENT if billed is None else billed
        remaining = None if remaining is None else remaining - charged
        spent_this_run += charged
        report["fetches"] += 1
        report["credits_spent"] += charged

        projected = _project(payload, event, observed, today)
        written = _append_projected(projected, processed_store)

        append([{
            "observed_utc": observed,
            "family": family,
            "event_id": payload.get("id") or event.get("id"),
            "commence_time": payload.get("commence_time") or event.get("commence_time"),
            "game_date": today,
            "poll": True,
            "rows_projected": written,
            "credits_last": billed,
        }], store)
        report["markers"] += 1
        report["rows"] += written

    report["credits_cumulative"] = credits_spent(read(store))
    return report


def _project(payload, event, observed, game_date) -> list:
    """One row per (market, book, selection, line): MARKET/SELECTION/LINE/
    PRICE/BOOK/TIMESTAMPS plus the provider's own `last_update`.

    SELECTION is the player id when the provider supplies one (`description_
    id`/`participant_id`, whichever the payload carries), falling back to the
    player name -- plus the over/under side, matching src/board/ids.py's
    "the line is part of the selection" convention: a different side is a
    different selection, not a modifier on one.
    """
    rows = []
    event_id = payload.get("id") or event.get("id")
    commence_time = payload.get("commence_time") or event.get("commence_time")
    home_team = payload.get("home_team") or event.get("home_team")
    away_team = payload.get("away_team") or event.get("away_team")
    for book in payload.get("bookmakers") or []:
        book_key = book.get("key")
        for market in book.get("markets") or []:
            market_key = market.get("key")
            if market_key not in MARKETS:
                continue
            last_update = market.get("last_update")
            for outcome in market.get("outcomes") or []:
                player = outcome.get("description")
                if not player:
                    continue
                side = outcome.get("name")  # "Over" / "Under"
                player_id = (outcome.get("participant_id")
                             or outcome.get("description_id")
                             or player)
                selection = f"{player_id}:{side}"
                line = outcome.get("point")
                rows.append({
                    "event_id": event_id,
                    "game_date": game_date,
                    "commence_time": commence_time,
                    "home_team": home_team,
                    "away_team": away_team,
                    "market": market_key,
                    "selection": selection,
                    "player": player,
                    "side": side,
                    "line": None if line is None else str(line),
                    "price": outcome.get("price"),
                    "book": book_key,
                    "book_last_update": last_update,
                    "observed_utc": observed,
                })
    return rows


# ---------------------------------------------------------------------------
# Store (raw/marker)
# ---------------------------------------------------------------------------

def append(rows, path=RAW_STORE) -> int:
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


def read(path=RAW_STORE) -> list:
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
            LOG.warning("batter_props: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


def credits_spent(rows) -> int:
    total = 0
    for row in rows or []:
        if not row.get("poll"):
            continue
        billed = row.get("credits_last")
        total += CREDITS_PER_EVENT if billed is None else billed
    return total


def _done_today(rows, game_date) -> set:
    out = set()
    for row in rows or []:
        if row.get("poll") and row.get("game_date") == game_date:
            out.add((row.get("event_id"), game_date))
    return out


# ---------------------------------------------------------------------------
# Store (projected L2)
# ---------------------------------------------------------------------------

def _projected_key(row) -> tuple:
    return (row.get("event_id"), row.get("market"), row.get("book"),
            row.get("selection"), row.get("line"), row.get("book_last_update"))


def _append_projected(rows, path=PROCESSED_STORE) -> int:
    """Append only rows whose idempotency key is not already on disk."""
    if not rows:
        return 0
    existing = {_projected_key(r) for r in read_processed(path)}
    fresh = [r for r in rows if _projected_key(r) not in existing]
    if not fresh:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if snapshots._ends_ragged(target):
            handle.write("\n")
        for row in fresh:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(fresh)


def read_processed(path=PROCESSED_STORE) -> list:
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
            LOG.warning("batter_props: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise BatterPropsError(
            "the clock must return a timezone-aware datetime; a naive "
            "observation time cannot honestly bracket a price")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def enabled(env=None) -> bool:
    """The switch. Off unless BATTER_PROPS says on."""
    source = os.environ if env is None else env
    return (source.get(ENV_SWITCH) or "").strip().lower() in {"on", "1", "yes", "true"}


def _load_dotenv(path=None) -> None:
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
    """Entry point for `python3 -m src.pipeline.batter_props`.

    Prints one short block for the capture transcript. A PROBE_REQUIRED
    condition on either family prints a single status line and never fails
    the capture -- ESCALATE lines are the only ones a model needs to react to.
    """
    _load_dotenv()
    if not enabled():
        print(f"batter props: off ({ENV_SWITCH} not set)")
        return 0
    report = run()
    if report.get("skipped"):
        print(f"batter props: skipped: {report['skipped']}")
    else:
        print(f"batter props: {report['fetches']} fetches, {report['rows']} rows, "
              f"{report['markers']} markers, {report['credits_spent']} credits "
              f"(cumulative {report.get('credits_cumulative')})")
    probe_required = {eid: reason for eid, reason in
                       (report.get("budget_reasons") or {}).items()
                       if reason.startswith("PROBE_REQUIRED")}
    if probe_required:
        print(f"batter props: PROBE_REQUIRED for "
              f"{len(probe_required)} game(s) -- run `python3 -m src.cli "
              f"budget --probe batter_props_floor` / `--probe batter_props_extra`; "
              f"capture continued anyway (never fails on PROBE_REQUIRED)")
    for error in report.get("errors") or []:
        print(f"  error: {error}")
    for line in report.get("escalate") or []:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
