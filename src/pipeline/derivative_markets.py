"""Derivative-markets CAPTURE: team totals, alternate lines, and the
first-five trio -- docs/SGP_PARLAY_CAPTURE.md's "proposed next families",
each gated through `src.capture.budget.can_spend` exactly like every other
paid-capture module in this repo.

WHAT THIS IS
------------
Three families, each with its own per-event odds_provider market list (also
the list `budget.probe_family` uses to measure each family's real cost --
see `src.capture.budget._probe_markets`):

- `team_totals`   -- `odds_provider.TEAM_TOTALS_MARKETS` (1 key)
- `alternates`    -- `odds_provider.ALTERNATE_MARKETS` (2 keys)
- `f5_trio`       -- `odds_provider.EVENT_MARKETS` (3 keys: the full
                     h2h+spreads+totals first-five bundle, distinct from the
                     already-measured f5-h2h-only figure dense.py piggybacks)

None of these is the non-droppable floor: all three sit in
`budget.DROP_ORDER` (ranks 3, 4 and 6) and are gated by the ordinary
floor/envelope/measured-cost checks `can_spend` already enforces -- this
module adds no new spending path, it only decides, per family per event,
whether a fetch about to happen may.

WHY ONE MODULE FOR THREE FAMILIES
----------------------------------
Same billing shape (markets x regions PER EVENT, per-event endpoint only --
`odds_provider.EVENT_ONLY_MARKETS`), same guard order, same store shape.
Three near-identical modules would just be this one copy-pasted three times
with the market list and the family name swapped -- exactly the kind of
duplication that drifts the moment one guard changes and the other two
copies are not updated to match.

BOUNDED, NOT A FULL-SLATE SWEEP
--------------------------------
Each family fetches at most `MAX_EVENTS_PER_FAMILY_PER_RUN` events per run,
mirroring prop_listing.py/batter_props.py's own per-run ceiling shape. A
family whose cost is still unmeasured (team_totals and f5_trio, as of this
writing -- see config/capture_families.json) never actually spends: every
event for that family comes back PROBE_REQUIRED from `can_spend`, which is
printed as a single status line and never treated as a capture failure (see
`main()`) until an operator runs
`python3 -m src.cli budget --probe team_totals` / `--probe f5_trio`.

L0/L1/L2 SHAPE
--------------
The raw provider payload is written by
`odds_provider.fetch_event_odds_with_usage` itself (`_write_raw_capture`,
one JSON blob per call) -- this module never duplicates that write, same as
batter_props.py. This module owns the L1 marker (one per billed fetch) in
`data/processed/derivative_markets_raw.jsonl` and the L2 projection into
`data/processed/derivative_markets.jsonl`: one row per (event, family,
market, book, selection, line, book_last_update) carrying
MARKET/SELECTION/LINE/PRICE/BOOK/TIMESTAMPS.

SELECTION
---------
`{team}:{side}` when the outcome carries a team (`description`) -- team
totals need the team folded in because "Over"/"Under" alone collides across
a game's two teams; a team-scoped spread/first-five side already carries the
team as `name` and needs nothing appended. `side` alone (`outcome.get("name")`,
"Over"/"Under" or a team name) otherwise. Matches this project's "the line is
part of the selection" convention (src/board/ids.py): LINE is a separate
column, never folded into SELECTION, so two different alternate lines on the
same side are two rows, not one row overwritten.

IDEMPOTENCY
-----------
Projected rows are keyed by (event_id, family, market, book, selection,
line, book_last_update) -- the same instant re-observed by a second run (or
a retried call after a partial write) produces the identical key and is
skipped, not duplicated.

Off unless DERIVATIVES=1 (see scripts/capture_extras.sh).
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

RAW_STORE = processed_path("derivative_markets_raw.jsonl")
PROCESSED_STORE = processed_path("derivative_markets.jsonl")

# Family name -> its odds_provider market list. Also the source of truth
# `budget._probe_markets` reads from for these three families, so a market
# added/removed here and there cannot silently drift apart.
FAMILY_MARKETS = {
    "team_totals": odds_provider.TEAM_TOTALS_MARKETS,
    "alternates": odds_provider.ALTERNATE_MARKETS,
    "f5_trio": odds_provider.EVENT_MARKETS,
}

# Plan order: cheapest/lowest-information family first is not the rule here
# (that is DROP_ORDER's job under a squeeze) -- this is simply a stable,
# reviewable iteration order so a transcript reads the same way every run.
FAMILIES = ("team_totals", "alternates", "f5_trio")

# A run may not fetch more than this many events per family, whatever the
# slate size -- the same per-run ceiling shape as prop_listing/batter_props.
MAX_EVENTS_PER_FAMILY_PER_RUN = 4

CREDIT_FLOOR = prop_listing.CREDIT_FLOOR

ENV_SWITCH = "DERIVATIVES"


class DerivativeMarketsError(RuntimeError):
    """Raised when the store or the clock is unusable. Never for a network fault."""


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def run(env=None, now=None, store=RAW_STORE, processed_store=PROCESSED_STORE,
        provider=odds_provider, credit_floor=CREDIT_FLOOR,
        credit_log_store=None) -> dict:
    """One scheduled pass. Returns a report; never raises for a network fault.

    Everything injectable is injectable so the tests spend nothing:
    `provider` stands in for the odds module, `now` for the clock, `store`/
    `processed_store` for the files -- the same contract batter_props.run()
    offers. `credit_log_store` is the envelope-check seam every other
    paid-capture `run()` in this package now carries: None (default) reads
    the real credit_log.jsonl via `can_spend`'s own default, which is
    `capture_spent_today()` -- the LIVE_CAPTURE-band total, never the
    unbanded `spent_today()`.
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
    creditlog.log(remaining, quota_now.get("last"), "derivative_markets.run",
                  budget_band=budget_module.LIVE_CAPTURE)
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
    by_id = {e.get("id"): e for e in slate if e.get("id")}

    plan = []
    for family in FAMILIES:
        slots = MAX_EVENTS_PER_FAMILY_PER_RUN
        for event_id in all_ids:
            if slots <= 0:
                break
            if (family, event_id, today) in done_today:
                continue
            plan.append((family, by_id[event_id]))
            slots -= 1

    report["games_due"] = len(plan)

    stopped_families = set()
    for family, event in plan:
        if family in stopped_families:
            continue
        event_id = event.get("id")
        markets = FAMILY_MARKETS[family]
        credits_per_event = len(markets)

        if report["fetches"] >= MAX_EVENTS_PER_FAMILY_PER_RUN * len(FAMILIES):
            report["escalate"].append(
                "ESCALATE: derivative-markets capture hit its per-run fetch "
                f"ceiling ({MAX_EVENTS_PER_FAMILY_PER_RUN * len(FAMILIES)}) -- "
                "more games came due than the design expects; check the plan "
                "before the next run")
            break

        decision = budget_module.can_spend(
            family, credits_per_event, remaining=remaining,
            store=credit_log_store)
        report["budget_reasons"].setdefault(family, {})[event_id] = decision.reason
        if not decision.allowed:
            print(f"derivative_markets.run: {family} {event_id}: {decision.reason}")
            if decision.reason.startswith("PROBE_REQUIRED"):
                # PROBE_REQUIRED is printed and recorded, never a hard stop --
                # same convention as batter_props.run's own PROBE_REQUIRED
                # path. Other events for this same family are equally
                # unmeasured, so there is no point retrying them this run.
                stopped_families.add(family)
                continue
            # A droppable family hitting the floor or the envelope stops
            # THIS family for the rest of the run; other families may still
            # have room (a real floor/envelope hit reported by `can_spend`
            # reflects the live balance, so once true it is true for every
            # family, but stopping per-family keeps the loop's behavior
            # obviously correct even if that ever changes).
            report["escalate"].append(
                f"derivative_markets: {family} stopped -- {decision.reason}")
            stopped_families.add(family)
            continue

        observed = _utc_iso(_now(now))
        try:
            payload, usage = provider.fetch_event_odds_with_usage(
                event_id, markets=markets, env=env)
        except provider.OddsProviderError as exc:
            append([{
                "observed_utc": observed,
                "family": family,
                "event_id": event_id,
                "game_date": today,
                "error": str(exc),
            }], store)
            report["errors"].append(f"{family} {event_id}: {exc}")
            continue

        billed = (usage or {}).get("last")
        charged = credits_per_event if billed is None else billed
        remaining = None if remaining is None else remaining - charged
        report["fetches"] += 1
        report["credits_spent"] += charged

        projected = _project(payload, event, family, markets, observed, today)
        written = _append_projected(projected, processed_store)

        append([{
            "observed_utc": observed,
            "family": family,
            "event_id": payload.get("id") or event_id,
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


def _project(payload, event, family, markets, observed, game_date) -> list:
    """One row per (market, book, selection, line): MARKET/SELECTION/LINE/
    PRICE/BOOK/TIMESTAMPS plus the provider's own `last_update`.

    SELECTION is `{team}:{side}` when the outcome carries a team
    (`description` -- team totals, where "Over"/"Under" alone collides
    across the game's two teams) and `side` alone otherwise (a team-scoped
    spread's own `name` already IS the team; a game total's own `name`
    already IS "Over"/"Under"). LINE stays a separate column, never folded
    into SELECTION -- src/board/ids.py's "the line is part of the identity,
    not a modifier on it" convention, applied to the store row rather than a
    hashed selection_id.
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
            if market_key not in markets:
                continue
            last_update = market.get("last_update")
            for outcome in market.get("outcomes") or []:
                side = outcome.get("name")
                if not side:
                    continue
                team = outcome.get("description")
                selection = f"{team}:{side}" if team else side
                line = outcome.get("point")
                rows.append({
                    "event_id": event_id,
                    "game_date": game_date,
                    "commence_time": commence_time,
                    "home_team": home_team,
                    "away_team": away_team,
                    "family": family,
                    "market": market_key,
                    "selection": selection,
                    "side": side,
                    "team": team,
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
            LOG.warning("derivative_markets: %s:%s is not valid JSON (likely "
                        "an interrupted append); skipped", target, number)
    return rows


def credits_spent(rows) -> int:
    total = 0
    for row in rows or []:
        if not row.get("poll"):
            continue
        billed = row.get("credits_last")
        family = row.get("family")
        markets = FAMILY_MARKETS.get(family)
        default = len(markets) if markets else 0
        total += default if billed is None else billed
    return total


def _done_today(rows, game_date) -> set:
    out = set()
    for row in rows or []:
        if row.get("poll") and row.get("game_date") == game_date:
            out.add((row.get("family"), row.get("event_id"), game_date))
    return out


# ---------------------------------------------------------------------------
# Store (projected L2)
# ---------------------------------------------------------------------------

def _projected_key(row) -> tuple:
    return (row.get("event_id"), row.get("family"), row.get("market"),
            row.get("book"), row.get("selection"), row.get("line"),
            row.get("book_last_update"))


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
            LOG.warning("derivative_markets: %s:%s is not valid JSON (likely "
                        "an interrupted append); skipped", target, number)
    return rows


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise DerivativeMarketsError(
            "the clock must return a timezone-aware datetime; a naive "
            "observation time cannot honestly bracket a price")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def enabled(env=None) -> bool:
    """The switch. Off unless DERIVATIVES says on."""
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
    """Entry point for `python3 -m src.pipeline.derivative_markets`.

    Prints one short block for the capture transcript. A PROBE_REQUIRED
    condition on any family prints a single status line and never fails the
    capture -- ESCALATE lines are the only ones a model needs to react to.
    """
    _load_dotenv()
    if not enabled():
        print(f"derivative markets: off ({ENV_SWITCH} not set)")
        return 0
    report = run()
    if report.get("skipped"):
        print(f"derivative markets: skipped: {report['skipped']}")
    else:
        print(f"derivative markets: {report['fetches']} fetches, {report['rows']} rows, "
              f"{report['markers']} markers, {report['credits_spent']} credits "
              f"(cumulative {report.get('credits_cumulative')})")
    probe_required = []
    for family, by_event in (report.get("budget_reasons") or {}).items():
        for event_id, reason in by_event.items():
            if reason.startswith("PROBE_REQUIRED"):
                probe_required.append(family)
                break
    if probe_required:
        families_list = ", ".join(sorted(set(probe_required)))
        print(f"derivative markets: PROBE_REQUIRED for {families_list} -- run "
              f"`python3 -m src.cli budget --probe <family>` for each; "
              f"capture continued anyway (never fails on PROBE_REQUIRED)")
    for error in report.get("errors") or []:
        print(f"  error: {error}")
    for line in report.get("escalate") or []:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
