"""Credit budget governance: a reset-aware daily envelope, per-family measured
costs, and a versioned drop order -- docs/planning/attack.md F13 and S17.

WHY THIS EXISTS
----------------
F13: the ~900/day envelope in the synthesis was priced on unmeasured
per-event costs, and on top of a balance whose semantics were misread. The
odds provider's `remaining` is a MONTHLY QUOTA on a flow that resets every
billing cycle (`PRICING_TIERS`, src/providers/odds.py:237-243 -- the "100K"
tier is $59/mo for 100,000 credits), not a bank balance that only ever goes
down. Treating ~99,600 remaining as "70% headroom forever" is the exact
mistake this module exists to prevent: it is 70% headroom UNTIL THE NEXT
RESET, after which it is 100% again, and a plan that assumes otherwise breaks
the first time it crosses a reset mid-run.

S17: the old coded drop order dropped batter props first -- the largest
surface with zero history and no retroactive purchase path. Under a squeeze
that destroys the most perishable data first, which is backwards. This module
reorders by irrecoverability x marginal information (DROP_ORDER below) and
carves out a non-droppable thin batter-prop floor so the surface is never
zero for a whole month.

WHAT THIS DOES NOT DO
----------------------
It never calls the odds API. `spent_today()` / `remaining_today()` are pure
reads of data/processed/credit_log.jsonl -- the append-only record every
paid-capture module already writes via `pipeline.creditlog` before spending
anything. This module adds no new spending path; it only decides, from
numbers already on disk, whether a caller that is ABOUT to spend may.

THE ONE EXCEPTION: `--probe <family>`, which is a real 1-credit API call,
gated so hard it is not runnable as a side effect of anything else -- see
`probe_family()` and `src/cli.py`'s `budget --probe` subcommand. It is
implemented here and NOT executed by this change (zero live credits).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.paths import processed_path, repo_root
from src.pipeline import creditlog

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier fact and envelope arithmetic
# ---------------------------------------------------------------------------

# The account's paid tier. This is a FACT about the provider's pricing table,
# cited rather than duplicated: src/providers/odds.py:237-243,
# `PRICING_TIERS = (..., ("100K", 59, 100_000), ...)` -- $59/mo for 100,000
# credits. Read it, never invented: if the account tier ever changes this
# constant must change with it, by hand, because there is no live way to ask
# the provider "which tier am I on" (the provider's `quota()` endpoint returns
# only `remaining`/`last`, not the tier itself).
MONTHLY_ALLOTMENT = 100_000

# How long one allotment cycle is assumed to run. The Odds API bills
# monthly; the exact anchor day of the account's billing cycle is NOT known
# from anything this repo can read (`quota()` returns a remaining count, not
# a reset date), so this uses a 30-day cycle anchored to the UTC calendar
# month as the best available approximation. THIS IS AN ASSUMPTION, not a
# measured fact -- flagged here rather than silently baked into the
# arithmetic, and callers that need the real anchor should get it from the
# account's own billing page.
RESET_CYCLE_DAYS = 30

# Fraction of one monthly allotment this program's forward-capture envelope
# is approved to plan against, leaving the remainder as headroom for
# backfills, ad hoc probes, and the reserve the floor protects. Owner
# decision 2 (packet W7): the ~900/day envelope is approved "provided it
# stays inside the existing paid monthly allotment and has hard spend
# guards" -- this fraction is chosen so the derived envelope lands there.
UTILIZATION_TARGET = 0.27

# The approved daily envelope, derived rather than hand-typed so the
# arithmetic is checkable in one place:
#   100,000 allotment x 0.27 target / 30-day cycle = 900/day.
DAILY_ENVELOPE = round(MONTHLY_ALLOTMENT * UTILIZATION_TARGET / RESET_CYCLE_DAYS)

# The absolute floor. This module is the canonical owner of the 5,000
# figure; prop_listing.py re-exports it (it imports this module, so the
# import must not run the other way -- that was a circular import).
# Odds.py itself does not define a floor constant -- the floor is a program
# policy, not a provider fact.
CREDIT_FLOOR = 5000

CREDIT_LOG_PATH = creditlog.DEFAULT_STORE
FAMILIES_CONFIG_PATH = repo_root() / "config" / "capture_families.json"


def quota_reset_utc(now=None) -> datetime:
    """The next assumed reset instant: the first of the next UTC calendar month.

    This is the RESET_CYCLE_DAYS assumption made concrete as a timestamp.
    It is a planning aid ("how many days until the flow resets"), not a
    verified billing date -- see the RESET_CYCLE_DAYS docstring above.
    """
    moment = _now(now)
    if moment.month == 12:
        return datetime(moment.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(moment.year, moment.month + 1, 1, tzinfo=timezone.utc)


def days_until_reset(now=None) -> int:
    """Whole days remaining until `quota_reset_utc`, minimum 0."""
    moment = _now(now)
    delta = quota_reset_utc(moment) - moment
    return max(0, delta.days)


# ---------------------------------------------------------------------------
# Reading the credit log (read-only; this module writes nothing to it)
# ---------------------------------------------------------------------------

def _rows(store=None) -> list:
    return creditlog.read(store if store is not None else CREDIT_LOG_PATH)


def _row_date(row) -> Optional[str]:
    utc = row.get("utc")
    if not utc:
        return None
    try:
        return utc[:10]  # "YYYY-MM-DD" prefix of an ISO-8601 UTC timestamp
    except (TypeError, IndexError):
        return None


def remaining_today(now=None, store=None) -> Optional[int]:
    """The most recently logged `credits_remaining` reading for today (UTC).

    None if the log has no row for today yet -- callers must treat that as
    "unknown", never as "unlimited" or "zero".
    """
    today = _row_date({"utc": _utc_iso(_now(now))})
    rows = [r for r in _rows(store) if _row_date(r) == today]
    if not rows:
        return None
    return rows[-1].get("credits_remaining")


def spent_today(now=None, store=None) -> int:
    """Credits spent so far today (UTC), from consecutive `remaining` deltas.

    Sums `max(prev - cur, 0)` across consecutive log rows within today's UTC
    calendar date. A rise in `remaining` between two consecutive rows means a
    reset happened between them (the flow refilled) -- that increment
    contributes 0 spend rather than a negative number, and the boundary is
    not otherwise smoothed over: spend accounting restarts cleanly, exactly
    as a reset should read.

    Rows with `credits_remaining: None` (a quota-unreadable event) are
    skipped when computing a delta but do not themselves count as spend --
    an unreadable quota is not evidence of a purchase.
    """
    today = _row_date({"utc": _utc_iso(_now(now))})
    todays_rows = [r for r in _rows(store) if _row_date(r) == today]
    known = [r.get("credits_remaining") for r in todays_rows
             if r.get("credits_remaining") is not None]
    total = 0
    for prev, cur in zip(known, known[1:]):
        if cur < prev:
            total += prev - cur
        # cur >= prev: a reset (or a free, unmetered read) between the two
        # readings. Contributes nothing to today's spend either way.
    return total


def remaining_after(est_credits: int, now=None, store=None) -> Optional[int]:
    """`remaining_today() - est_credits`, or None if remaining is unknown."""
    remaining = remaining_today(now=now, store=store)
    if remaining is None:
        return None
    return remaining - est_credits


# ---------------------------------------------------------------------------
# Per-family measured cost table
# ---------------------------------------------------------------------------

def load_families(path=None) -> dict:
    """The `families` mapping from config/capture_families.json.

    Never raises: a missing or corrupt config means every family reads as
    unmeasured (PROBE_REQUIRED) rather than crashing a caller on the paid
    critical path.
    """
    target = Path(path if path is not None else FAMILIES_CONFIG_PATH)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data.get("families", {})
    except Exception as exc:  # noqa: BLE001 -- config read must never break a caller
        LOG.debug("budget: failed to read %s (%s: %s)", target, type(exc).__name__, exc)
        return {}


def family_cost(family: str, path=None) -> Optional[int]:
    """Measured `credits_per_event` for `family`, or None if unmeasured/unknown."""
    entry = load_families(path).get(family)
    if not entry or not entry.get("measured"):
        return None
    return entry.get("credits_per_event")


# ---------------------------------------------------------------------------
# The drop order (S17): irrecoverability x marginal-information ranking
# ---------------------------------------------------------------------------
#
# Versioned so a later reorder is an explicit, reviewable diff rather than a
# silent behavior change. Index 0 drops FIRST under a squeeze; the last
# entry drops LAST, "always" (F13/S17: Tier A featured is never the thing
# that breaks a budget -- it is flat 3 credits/event and the cheapest
# possible baseline). `batter_props_floor` never appears in this list: it is
# enforced separately as non-droppable (see `NON_DROPPABLE_FAMILY` and
# `can_spend`) precisely because S17's fix requires a thin batter-prop
# surface that survives every squeeze, not merely one that drops last.

DROP_ORDER_VERSION = 1

DROP_ORDER = (
    {"rank": 1, "family": "parlay_sgp",
     "reason": "Endpoint existence unconfirmed; zero committed information to lose."},
    {"rank": 2, "family": "prop_listing_feasibility",
     "reason": "Feasibility-only, no prices; already the lowest-priority layer "
               "per docs/COLLECTION_POLICY.md, and the coverage question it "
               "answers can be re-asked next month at the same 1 credit/slot."},
    {"rank": 3, "family": "team_totals",
     "reason": "Unmeasured, moderate information; a missed day is one of many "
               "and the market persists tomorrow at the same price shape."},
    {"rank": 4, "family": "alternates",
     "reason": "High info-per-credit (130-160 outcome rows/event) but the "
               "least unique: the same book relists the same ladder tomorrow, "
               "so a missed day is recoverable in kind, not in fact."},
    {"rank": 5, "family": "pitcher_props",
     "reason": "Keyed by starter; a missed start is gone, but the pitcher "
               "himself starts again within a week, so the surface is only "
               "partially irrecoverable."},
    {"rank": 6, "family": "f5_trio",
     "reason": "Closer to the game than alternates/team totals; first-five "
               "prices move with the same information the full-game market "
               "does, so losing a day here loses more than losing alternates."},
    {"rank": 7, "family": "batter_props_extra",
     "reason": "Batter props beyond the non-droppable floor. Droppable, but "
               "ranked near-last on purpose (S17): zero history exists "
               "elsewhere and there is no retroactive purchase path at any "
               "price, so this is dropped only after every layer above it."},
    {"rank": 8, "family": "featured",
     "reason": "Tier A: flat 3 credits/event, the response variable itself. "
               "Last resort, always -- if this drops, the day has already "
               "failed by every other measure."},
)

# Never appears in DROP_ORDER and is never returned by any allocator this
# module offers: full batter props on a small, deterministically rotated
# slice of the night's card, kept alive through every squeeze so the surface
# is never zero for a whole month (S17's stated fix).
NON_DROPPABLE_FAMILY = "batter_props_floor"
NON_DROPPABLE_GAMES_PER_NIGHT = 2


def rotated_floor_games(all_game_ids: list, game_date: str) -> list:
    """Deterministically pick `NON_DROPPABLE_GAMES_PER_NIGHT` games for the
    non-droppable batter-prop floor on `game_date`.

    Deterministic and stateless: the same (`all_game_ids`, `game_date`)
    always picks the same games, so a killed-and-restarted run reselects
    identically rather than skipping a night or double-counting one. Rotates
    by hashing the date so the same two games are not picked every single
    night regardless of slate size.
    """
    ids = sorted(str(g) for g in all_game_ids)
    if not ids:
        return []
    offset = int(hashlib.sha256(game_date.encode("utf-8")).hexdigest(), 16) % len(ids)
    rotated = ids[offset:] + ids[:offset]
    return rotated[:NON_DROPPABLE_GAMES_PER_NIGHT]


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def can_spend(family: str, est_credits: int, now=None, store=None,
              families_path=None, remaining=None, spent=None) -> Decision:
    """May `family` spend `est_credits` right now?

    Checked in this order, matching the existing per-module convention
    (floor before envelope before anything else):

    1. The non-droppable floor family is never gated by the floor or the
       envelope -- it is, by definition, the thing that survives a squeeze.
       (It can still be refused for being unmeasured; see 4.)
    2. Absolute floor: spending would take the balance to or below
       `CREDIT_FLOOR`. Unreadable remaining fails closed (refused), matching
       dense.py/prop_listing.py/prop_prices.py's own "quota unreadable"
       handling -- this module never assumes a spend is safe from missing data.
    3. Daily envelope: today's spend plus this request would exceed
       `DAILY_ENVELOPE`.
    4. Measured cost: `family` must have a measured `credits_per_event` in
       config/capture_families.json, or the decision is PROBE_REQUIRED --
       a family with no measured cost cannot be budgeted (F13's fix).

    `remaining`/`spent` let a caller that has ALREADY read the live quota
    this pass (dense.py/prop_listing.py/prop_prices.py all call
    `odds_provider.quota()` before this) pass that number straight through
    instead of re-deriving it from credit_log.jsonl -- the log write for
    THIS pass may not have landed yet (or, under a test's forward-store
    guard, may never land), and re-reading a file whose freshest row a
    caller is holding in hand already would be strictly worse than using
    what the caller has. Omit either to fall back to the read-only log scan.
    """
    # A zero-credit request (weather_capture: free, keyless endpoints) can
    # never deplete the floor or the envelope, so it is never gated by
    # either -- gating a free call on the paid balance would make a network
    # outage on the credit-log side able to block a capture that costs
    # nothing, which is exactly the kind of failure this module exists to
    # prevent, not cause.
    if family != NON_DROPPABLE_FAMILY and est_credits > 0:
        if remaining is None:
            remaining = remaining_today(now=now, store=store)
        if remaining is None:
            return Decision(False, "skipped: quota unreadable (no credit_log row for today)")
        if remaining - est_credits <= CREDIT_FLOOR:
            return Decision(False, f"skipped: credit floor (remaining={remaining}, "
                                    f"floor={CREDIT_FLOOR}, requested={est_credits})")

        if spent is None:
            spent = spent_today(now=now, store=store)
        if spent + est_credits > DAILY_ENVELOPE:
            return Decision(False, f"skipped: daily envelope (spent={spent}, "
                                    f"requested={est_credits}, envelope={DAILY_ENVELOPE})")

    cost = family_cost(family, path=families_path)
    if cost is None:
        return Decision(False, f"PROBE_REQUIRED: {family} has no measured "
                                f"credits_per_event -- run `python3 -m src.cli "
                                f"budget --probe {family}` before this family "
                                f"can enter the envelope")

    return Decision(True, f"ok: {family} measured at {cost} credit(s)/event")


def status(now=None, store=None, families_path=None) -> dict:
    """Everything `python3 -m src.cli budget` prints, as a dict."""
    remaining = remaining_today(now=now, store=store)
    spent = spent_today(now=now, store=store)
    families = load_families(families_path)
    per_family = {}
    for name, entry in families.items():
        per_family[name] = {
            "measured": bool(entry.get("measured")),
            "credits_per_event": entry.get("credits_per_event"),
            "measured_utc": entry.get("measured_utc"),
        }
    return {
        "monthly_allotment": MONTHLY_ALLOTMENT,
        "reset_cycle_days": RESET_CYCLE_DAYS,
        "quota_reset_utc": _utc_iso(quota_reset_utc(now)),
        "days_until_reset": days_until_reset(now),
        "daily_envelope": DAILY_ENVELOPE,
        "credit_floor": CREDIT_FLOOR,
        "remaining_today": remaining,
        "spent_today": spent,
        "envelope_remaining_today": (DAILY_ENVELOPE - spent) if spent is not None else None,
        "drop_order_version": DROP_ORDER_VERSION,
        "drop_order": [d["family"] for d in DROP_ORDER],
        "non_droppable_family": NON_DROPPABLE_FAMILY,
        "families": per_family,
    }


# ---------------------------------------------------------------------------
# The probe (implemented, never invoked by this change)
# ---------------------------------------------------------------------------

# Which markets a probe of `family` fetches, and where those keys live.
# Only families with a real per-event, per-market odds_provider entry point
# are probeable this way -- a family with no market list (parlay_sgp,
# team_totals, f5_trio) is not wired here and returns an explicit error
# rather than guessing a market to call.
def _probe_markets(family: str, provider) -> Optional[tuple]:
    if family in ("batter_props_floor", "batter_props_extra", "batter_props"):
        return provider.BATTER_MARKETS
    if family == "pitcher_props":
        return provider.PROP_MARKETS
    return None


def probe_family(family: str, env=None, provider=None, now=None,
                  families_path=None) -> dict:
    """Spend exactly ONE bounded fetch measuring `family`'s real per-event cost.

    A real API call: one event, one region, `family`'s market list, via
    `odds_provider.fetch_event_odds_with_usage`. The credit delta is read
    from the provider's own usage headers (never guessed), recorded into
    `config/capture_families.json` as `measured: true`, and printed.

    Refuses to run twice per family per day (a stored `measured_utc` whose
    UTC date matches today's is a repeat request, not a re-measurement --
    re-probing daily would spend real credits on a number that does not
    change run to run) and respects `CREDIT_FLOOR` (checked before spending,
    against the free quota read, same ordering every other paid-capture
    module in this repo uses).
    """
    if provider is None:
        from src.providers import odds as provider  # local import: keep this
        # module importable (and its arithmetic testable) with no network
        # dependency unless a probe is actually requested.

    entry = load_families(families_path).get(family)
    if entry is None:
        return {"family": family, "probed": False,
                "error": f"unknown family {family!r}; add it to "
                         f"config/capture_families.json first"}

    moment = _now(now)
    today = moment.date().isoformat()
    already_measured_utc = entry.get("measured_utc")
    if entry.get("measured") and already_measured_utc \
            and str(already_measured_utc)[:10] == today:
        return {"family": family, "probed": False,
                "error": f"already probed today ({already_measured_utc}); "
                         f"refusing to run a second probe for {family!r} "
                         f"on the same UTC day",
                "credits_per_event": entry.get("credits_per_event")}

    markets = _probe_markets(family, provider)
    if markets is None:
        return {"family": family, "probed": False,
                "error": f"probe fetch not wired for family {family!r} -- "
                         f"no known odds_provider market list for it"}

    status_now = provider.status(env)
    if not status_now.get("configured"):
        return {"family": family, "probed": False,
                "error": "not configured", "message": status_now.get("message")}

    try:
        quota_before = provider.quota(env)
    except provider.OddsProviderError as exc:
        return {"family": family, "probed": False,
                "error": "quota unreadable", "message": str(exc)}
    remaining_before = quota_before.get("remaining")
    if remaining_before is not None and remaining_before <= CREDIT_FLOOR:
        return {"family": family, "probed": False,
                "error": "credit floor", "credits_remaining": remaining_before}

    try:
        listed = provider.list_events(env)  # free
    except provider.OddsProviderError as exc:
        return {"family": family, "probed": False,
                "error": "events unreadable", "message": str(exc)}
    if not listed:
        return {"family": family, "probed": False,
                "error": "no events available to probe against"}
    event = sorted(listed, key=lambda e: (e.get("commence_time") or "",
                                          e.get("id") or ""))[0]
    event_id = event.get("id")

    measured_utc = _utc_iso(moment)
    result = {"family": family, "probed": False, "measured_utc": measured_utc,
              "event_id": event_id, "markets": list(markets),
              "credits_remaining_before": remaining_before}

    try:
        payload, usage = provider.fetch_event_odds_with_usage(
            event_id, markets=markets, env=env)
    except provider.OddsProviderError as exc:
        result["error"] = f"probe fetch failed: {exc}"
        return result

    billed = (usage or {}).get("last")
    remaining_after_call = (usage or {}).get("remaining")
    if billed is not None:
        credits_per_event = billed
    elif remaining_before is not None and remaining_after_call is not None:
        credits_per_event = max(remaining_before - remaining_after_call, 0)
    else:
        credits_per_event = len(markets)  # last-resort, conservative estimate

    creditlog.log(remaining_after_call, billed, f"budget.probe_family:{family}")

    recorded = _record_measurement(
        family, credits_per_event,
        source=f"budget.probe_family: live {family} probe against event "
               f"{event_id} ({len(markets)} market(s), 1 region); "
               f"billed={billed!r}, remaining_before={remaining_before!r}, "
               f"remaining_after={remaining_after_call!r}",
        measured_utc=measured_utc, families_path=families_path)

    result["probed"] = True
    result["credits_per_event"] = credits_per_event
    result["credits_remaining_after"] = remaining_after_call
    result["recorded"] = recorded
    return result


def _record_measurement(family: str, credits_per_event: int, source: str,
                          measured_utc: str, families_path=None) -> bool:
    """Persist a real measurement into config/capture_families.json.

    Never called by anything except a completed `probe_family` fetch --
    this is the only path that may set `measured: true`.
    """
    target = Path(families_path if families_path is not None else FAMILIES_CONFIG_PATH)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        families = data.setdefault("families", {})
        families[family] = {
            "measured": True,
            "credits_per_event": credits_per_event,
            "measured_utc": measured_utc,
            "source": source,
        }
        target.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n",
                           encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        LOG.debug("budget: failed to record measurement for %s (%s: %s)",
                  family, type(exc).__name__, exc)
        return False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("budget now() must return a timezone-aware datetime")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
