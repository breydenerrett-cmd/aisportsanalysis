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

from src.paths import data_path, processed_path, repo_root
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

# The daily cap for in-play odds capture. Owner decision 2026-09-14: a hard
# cap of 300 credits per day for in-play odds across all sports, event-driven,
# with a kill switch that defaults to OFF (see live_odds_enabled below).
LIVE_ODDS_DAILY_CAP = 300

CREDIT_LOG_PATH = creditlog.DEFAULT_STORE
FAMILIES_CONFIG_PATH = repo_root() / "config" / "capture_families.json"

# R16-L4 (D7): the live window writes its own credit rows here, never to
# CREDIT_LOG_PATH, so the two runners (the forward-capture chain and the
# live window) never write the same file at once. `_rows()` below merges
# the two logs by timestamp at READ time -- an application-level merge, not
# a git union-merge driver (explicitly rejected in docs/LIVE_BETTING_SYSTEM.md
# section 6, R16-L4: a union driver can reorder lines and break the delta
# arithmetic `spent_today()` depends on; sorting the two already-chronological
# files by `utc` after reading them cannot reorder either file's own rows
# relative to each other, only interleave the two streams).
LIVE_CREDIT_LOG_PATH = data_path("live", "credit_log_live.jsonl")

# Environment variable to enable/disable live odds capture. The feature is OFF
# by default -- live odds capture is only active when this env var is set to
# one of "1", "true", "yes", or "on" (case-insensitive, whitespace-stripped).
ENV_LIVE_ODDS = "LIVE_ODDS"


def live_odds_enabled(env=None) -> bool:
    """True only when the LIVE_ODDS env var is set to an enabled value.

    env, if given, is a dict to read (used for testing); omit it to read
    os.environ. The value must be "1", "true", "yes", or "on" (lowercased,
    whitespace-stripped) to be considered enabled.
    """
    import os
    if env is None:
        env = os.environ
    value = env.get(ENV_LIVE_ODDS, "").strip().lower()
    return value in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Band separation (2026-09-04 incident, amended same day)
# ---------------------------------------------------------------------------
#
# docs/RESOURCE_POLICY.md defines the LIVE-CAPTURE reserve (the ~900/day
# envelope below) as a band SEPARATE from historical backfill/new-market
# research and ad hoc probes. `spent_today()` used to sum every
# `credits_remaining` delta for the UTC day regardless of who logged it, so
# an owner-approved ~47,000-credit historical purchase logged the same day
# read as LIVE-CAPTURE spend and tripped the envelope on every
# forward-capture fetch for hours -- the growth band starving the one
# stream that cannot be bought back.
#
# THE FIX IS AN EXPLICIT, DURABLE FIELD, NOT INFERENCE. `creditlog.log()`
# takes a `budget_band` kwarg (one of the four `VALID_BANDS` below) that
# every writer sets AT WRITE TIME, describing itself -- not a label this
# module derives after the fact from a caller string, and not a special
# case naming today's runner. Every capture/historical/probe call site this
# repo controls (the five paid-capture `run()`s, `probe_family`, and the
# `scripts/probe_historical_*`/`probe_prop_name_join`/`run_f5_tminus2_
# tranche` scripts) now passes its own band explicitly.
#
# LEGACY ROWS (logged before this field existed, or by any future call site
# that forgets to set it) carry no `budget_band` key at all. Those are
# classified by `_legacy_band()` below from the same `caller` string this
# module has always read -- deterministic (same caller always yields the
# same band) and conservative: only the six known live-capture callers
# classify as `LIVE_CAPTURE`; every other caller, known or not, classifies
# as `HISTORICAL_BACKFILL` so an unrecognized or missing caller can never
# silently count against -- or evade -- the live-capture envelope.
#
# THE LIMIT NEITHER SCHEME CAN COVER: a call that spends credits WITHOUT
# ever calling `creditlog.log()` leaves no row at all -- no caller, no band,
# nothing to classify, because there is no row. Band separation, explicit
# or inferred, can only ever classify spend that was actually logged; it
# cannot recover or attribute spend that left no record. That is a separate,
# real gap (see docs/OVERNIGHT_RUN.md's 2026-09-04 entries) in whichever
# historical code path bypassed `creditlog` entirely, not something either
# scheme here can paper over -- fixing it means making that call site log
# through `creditlog` with its own band, not widening either set below.
LIVE_CAPTURE = "live_capture"
HISTORICAL_BACKFILL = "historical_backfill"
PROBE = "probe"
TEST = "test"
LIVE_ODDS = "live_odds"
VALID_BANDS = frozenset({LIVE_CAPTURE, HISTORICAL_BACKFILL, PROBE, TEST, LIVE_ODDS})

# Every `caller` string the five paid-capture `run()` entry points log via
# `pipeline.creditlog` (dense.py's own close-capture pass included -- it is
# the same live-capture pass, just its closing window). Used ONLY by
# `_legacy_band()` to classify rows logged before `budget_band` existed;
# every live write site now sets `budget_band=LIVE_CAPTURE` explicitly and
# does not depend on this set at read time.
CAPTURE_CALLERS = frozenset({
    "dense.run", "dense.close_capture",
    "prop_listing.run", "prop_prices.run",
    "batter_props.run", "derivative_markets.run",
})


def _legacy_band(caller) -> str:
    """Best-effort band for a row logged before `budget_band` existed.

    Deterministic (a given caller string always yields the same band) and
    conservative toward the envelope: only `CAPTURE_CALLERS` reads as
    `LIVE_CAPTURE`. A probe-family caller reads as `PROBE`. Every other
    caller -- a recognized historical/backfill script, an unrecognized
    future one, or a missing/empty caller field -- reads as
    `HISTORICAL_BACKFILL`, so nothing outside the six known capture callers
    can ever count against the live-capture envelope by default.
    """
    if caller in CAPTURE_CALLERS:
        return LIVE_CAPTURE
    if isinstance(caller, str) and caller.startswith("budget.probe_family:"):
        return PROBE
    return HISTORICAL_BACKFILL


def row_band(row) -> str:
    """The `budget_band` a credit-log row belongs to: explicit if present
    and valid, else `_legacy_band()`'s deterministic fallback from `caller`.

    Single-row classification only -- it has no delta to weigh, so it
    cannot apply `_delta_band()`'s envelope-ceiling rule below. Used for
    labeling one row in isolation (reporting); `spent_today()` uses
    `_delta_band()` instead, because THAT is where a legacy row's real
    ambiguity (see 2026-09-04's incident) actually lives.
    """
    band = row.get("budget_band")
    if band in VALID_BANDS:
        return band
    return _legacy_band(row.get("caller"))


def _delta_band(cur_row, delta: int) -> str:
    """Band for ONE observed spend delta, ending at `cur_row`.

    An explicit `budget_band` on `cur_row` is authoritative, exactly like
    `row_band()`. For a LEGACY row (no explicit field, logged before this
    field existed), this additionally applies an envelope-ceiling rule
    `row_band()` cannot: `can_spend()` gates every live-capture call BEFORE
    it happens and refuses anything that would push a day's live-capture
    spend over `DAILY_ENVELOPE` -- so under this system's OWN invariant, a
    single delta larger than `DAILY_ENVELOPE` could never have been
    approved as live-capture spend, no matter which of the six capture
    callers happens to be the row that revealed it. This is what actually
    separates the two 2026-09-04 bands on the real log: neither of that
    day's two large historical purchases ever called `creditlog.log()` of
    its own, so the drop each one caused was only ever revealed by the next
    capture-band checkpoint -- a legacy row with no `budget_band` of its
    own. A caller-name-only fallback (`_legacy_band()`, used by `row_band()`
    and by this function for anything at or under the ceiling) cannot tell
    that apart from real capture spend; this can, using a fact the system
    already enforces rather than a guessed threshold.

    A delta at or under the ceiling still runs through the ordinary
    `_legacy_band()` caller classification -- this rule only ever
    RECLASSIFIES a legacy capture-caller row AWAY from live_capture, never
    the reverse, so it can't be used to hide genuine capture overspend: a
    real over-envelope capture bug would show up as `can_spend()` refusing
    the NEXT call, exactly as intended.
    """
    band = cur_row.get("budget_band")
    if band in VALID_BANDS:
        return band
    caller = cur_row.get("caller")
    if delta > DAILY_ENVELOPE and caller in CAPTURE_CALLERS:
        return HISTORICAL_BACKFILL
    return _legacy_band(caller)


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
    """Every credit-log row, chronological.

    An explicit `store` (every test in this repo passes one) reads exactly
    that file, unchanged from before R16-L4. The default (no `store`, used
    by the real CLI and the real budget checks) reads BOTH real logs --
    `CREDIT_LOG_PATH` (the forward-capture chain) and `LIVE_CREDIT_LOG_PATH`
    (the live window, R16-L4) -- and merges them by `utc` so a caller that
    does not pass a store never has to know there are two files. This is a
    read-time merge only; neither file on disk is ever rewritten or
    reordered by it.
    """
    if store is not None:
        return creditlog.read(store)
    merged = creditlog.read(CREDIT_LOG_PATH) + creditlog.read(LIVE_CREDIT_LOG_PATH)
    merged.sort(key=lambda row: row.get("utc") or "")
    return merged


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


def spent_today(now=None, store=None, band=None) -> int:
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

    `band`, when given (one of `VALID_BANDS`, e.g. `LIVE_CAPTURE`),
    restricts what counts to deltas whose LATER row (the one that observed
    the drop) resolves to that band via `row_band()` -- explicit
    `budget_band` field if the row has one, else `_delta_band()`'s
    deterministic fallback (caller name, plus the envelope-ceiling rule for
    a legacy capture-caller row -- see `_delta_band`'s docstring). This is
    NOT "filter the rows to this band, then diff the filtered sequence" --
    that would silently keep counting a same-day historical purchase
    against capture, because the balance it drained is still what the NEXT
    live-capture row reads, gap or no gap. Diffing the FULL chronological
    sequence first and then bucketing each individual delta by the band of
    the row that revealed it correctly excludes a historical/probe purchase
    whether or not it logged its own checkpoint in between (see
    `test_a_large_same_day_historical_spend_does_not_block_capture` and
    `test_an_unlogged_historical_spend_is_still_excluded_via_the_envelope_ceiling`).
    `None` (the default) keeps the old whole-day-regardless-of-band total,
    which `status()` still reports so historical/probe spend stays visible.

    R16-L3 (D6): `LIVE_ODDS` is the one exception to all of the above. Two
    runners (the forward-capture chain and the live window) can each spend
    credits between one moment and the next, so a balance-delta attributed
    to "whichever row observed the drop" bills a live_odds capture's real
    cost to the pre-game envelope (or vice versa) whenever the chain's own
    checkpoint happens to be the next row logged. `live_odds.capture_inplay`
    now logs each call's OWN cost, read from that call's own response
    headers (`x-requests-last`), on `credits_used_last` -- so the live_odds
    total below is a direct sum of what each call actually billed, never a
    balance delta, and a `band=LIVE_ODDS` request returns it immediately.

    For every OTHER band, a delta that spans one or more live_odds rows (the
    two runners interleaved in the merged log) has those calls' own logged
    cost subtracted before the remainder is classified -- so the same
    in-play spend is never ALSO counted against `LIVE_CAPTURE`'s envelope
    just because a live_odds row happened to land between two pre-game
    checkpoints.
    """
    today = _row_date({"utc": _utc_iso(_now(now))})
    todays_rows = [r for r in _rows(store) if _row_date(r) == today]

    live_odds_total = sum(
        (r.get("credits_used_last") or 0)
        for r in todays_rows if row_band(r) == LIVE_ODDS
    )
    if band == LIVE_ODDS:
        return live_odds_total

    known = [r for r in todays_rows if r.get("credits_remaining") is not None]
    other_total = 0
    for prev, cur in zip(known, known[1:]):
        prev_remaining, cur_remaining = prev["credits_remaining"], cur["credits_remaining"]
        if cur_remaining >= prev_remaining:
            # A reset (or a free, unmetered read) between the two readings.
            # Contributes nothing to today's spend either way.
            continue
        delta = prev_remaining - cur_remaining
        cur_band = _delta_band(cur, delta)
        if cur_band == LIVE_ODDS:
            # This delta IS a live_odds checkpoint's own drop -- already
            # counted once in live_odds_total above via its own
            # credits_used_last; counting it again here would double it.
            continue
        prev_utc, cur_utc = prev.get("utc") or "", cur.get("utc") or ""
        live_odds_inside = sum(
            (r.get("credits_used_last") or 0)
            for r in todays_rows
            if row_band(r) == LIVE_ODDS
            and prev_utc < (r.get("utc") or "") < cur_utc
        )
        delta = max(delta - live_odds_inside, 0)
        if band is None or cur_band == band:
            other_total += delta
    if band is None:
        return other_total + live_odds_total
    return other_total


def capture_spent_today(now=None, store=None) -> int:
    """`spent_today()` restricted to the LIVE-CAPTURE band.

    This is what `can_spend()`'s DAILY_ENVELOPE check reads: the envelope
    exists to bound live capture's own spend, not whatever a same-day
    historical backfill or probe -- a different band entirely per
    docs/RESOURCE_POLICY.md -- happened to spend and log under its own
    band. See the band-separation docstring above `VALID_BANDS` for what
    this can and cannot separate.
    """
    return spent_today(now=now, store=store, band=LIVE_CAPTURE)


# ---------------------------------------------------------------------------
# Checkpoint observability (2026-09-19 incident)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. `can_spend()` gates every live-capture call BEFORE it
# spends, against `capture_spent_today()`'s running total read off
# credit_log.jsonl -- so the whole envelope design depends on a checkpoint
# landing in that file roughly as often as capture runs. 2026-09-19T04:00Z-
# 15:36Z, capture_slot.sh's forward-capture.yml `capture` job ran on its
# normal ~13-minute cadence the entire time (`gh run list --workflow=
# forward-capture`, ~51 completed/success runs in the window) and each run's
# own step output showed real work -- dense captures, the non-droppable
# batter-props floor family (exempt from both the floor and the envelope by
# `can_spend`'s own contract, see NON_DROPPABLE_FAMILY below), nfl_capture --
# yet not one of those runs' own git-commit step found anything to commit
# ("== no data changes ==" every single time; confirmed against `git log
# --since ... --until ... -- data/processed/credit_log.jsonl` on the real
# branch, which shows only the unrelated Daily-loop/Afternoon-slate commits
# landing in that window, zero "Forward capture slot" commits). The credit
# log went completely silent for 11.6 hours while real spend kept
# happening -- confirmed by the SAME run's own in-process envelope math
# advancing checkpoint to checkpoint (e.g. one 06:18Z run read spent=927 at
# its dense.run() call and spent=938 eleven credits later at its
# nfl_capture call, the exact size of that run's own batter-props floor
# spend) even though the file those numbers came from never left that one
# ephemeral runner. When a checkpoint finally committed again, the entire
# gap's real spend landed as one outsized delta.
#
# `can_spend()` cannot protect against this on its own: it can only ever
# refuse a call it gets to see, and every call in the gap read a stale,
# low `spent_today()` because no checkpoint before it had landed either.
# These two functions do not change any spend decision -- they make the
# checkpoint stream's own health machine-checkable, so a human or
# `src.capture.health.assess()` finds out inside one cadence, not 11.6
# hours and an eyeballed timestamp diff later.

def checkpoint_age_minutes(now=None, store=None) -> Optional[float]:
    """Minutes since the most recently logged credit-log row (merged
    stores, chronological -- see `_rows()`), or None if the log has no
    rows at all.

    A live-capture cadence that is actually running writes a checkpoint
    roughly every capture pass (dense.run/prop_listing.run/batter_props.run
    etc. each call `creditlog.log()` before deciding whether to spend, win
    or lose). This number going unusually large while capture keeps
    reporting success -- rather than the log simply having no rows for a
    quiet overnight stretch -- is exactly the 2026-09-19 signature: real
    calls, no checkpoints. Read from a FRESH checkout (this file, unlike
    the raw artifacts `health.py` also watches, is git-tracked and not
    reproducible/redirected per-runner), this is the plain number a human
    manually reconstructed from timestamps during that incident, made
    machine-checkable.
    """
    moment = _now(now)
    rows = _rows(store)
    if not rows:
        return None
    latest_utc = rows[-1].get("utc")
    if not latest_utc:
        return None
    try:
        latest = datetime.fromisoformat(str(latest_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - latest).total_seconds() / 60.0)


def oversized_checkpoint_deltas(now=None, store=None, band=LIVE_CAPTURE,
                                 threshold=None) -> list:
    """Every consecutive same-day delta in `band` bigger than `threshold`
    (default `DAILY_ENVELOPE`), as a list of
    `{"from_utc", "to_utc", "delta", "from_caller", "to_caller"}` dicts.

    `can_spend()` refuses BEFORE spending whenever `capture_spent_today()`
    plus the request would exceed `DAILY_ENVELOPE` -- so under this
    system's own invariant, genuine live-capture spend should never show
    up as one checkpoint-to-checkpoint delta bigger than a full day's
    envelope; it should show up as many deltas, each individually held
    under it. A single delta this large means the checkpoints in between
    never landed (see the module-level comment above this section for the
    2026-09-19 incident this documents) -- `can_spend()` was reading a
    stale, low "spent so far" number for the whole gap and never got the
    chance to refuse anything.

    THIS DOES NOT RECLASSIFY THE DELTA THE WAY `_delta_band()`'S
    LEGACY-ONLY CEILING RULE DOES. `_delta_band()` only ever reclassifies a
    LEGACY row (no explicit `budget_band`) away from LIVE_CAPTURE, on the
    theory that a real live-capture overspend this size "could never have
    been approved" -- see that function's own docstring, and note it is
    guarded to rows with NO explicit band: today's 2026-09-19 spike row
    carries `"budget_band": "live_capture"` explicitly, so that rule never
    runs on it at all, legacy or not. That is correct, not a hole to
    patch: this row IS genuine live-capture spend that was never approved
    one checkpoint at a time, because no checkpoint got the chance to run
    the approval -- reclassifying it as historical/backfill would hide the
    exact overspend this function exists to surface, precisely the
    failure `_delta_band()`'s own docstring warns against. This function
    uses `row_band()` (explicit band if present, else the plain
    caller-name fallback, WITHOUT the ceiling special case) and never
    changes what band a delta reports as -- it only flags the size.
    """
    threshold = DAILY_ENVELOPE if threshold is None else threshold
    today = _row_date({"utc": _utc_iso(_now(now))})
    todays_rows = [r for r in _rows(store) if _row_date(r) == today]
    known = [r for r in todays_rows if r.get("credits_remaining") is not None]
    anomalies = []
    for prev, cur in zip(known, known[1:]):
        prev_remaining, cur_remaining = prev["credits_remaining"], cur["credits_remaining"]
        if cur_remaining >= prev_remaining:
            continue
        delta = prev_remaining - cur_remaining
        if row_band(cur) != band:
            continue
        if delta > threshold:
            anomalies.append({
                "from_utc": prev.get("utc"),
                "to_utc": cur.get("utc"),
                "delta": delta,
                "from_caller": prev.get("caller"),
                "to_caller": cur.get("caller"),
            })
    return anomalies


def can_spend_live_odds(est_credits: int, now=None, store=None, env=None,
                        remaining=None) -> Decision:
    """May we spend `est_credits` on in-play odds right now?

    Checked in order:
    1. Feature enabled: if live_odds_enabled(env) is False, refuse with
       "disabled" in the reason.
    2. Non-positive request: est_credits <= 0 is allowed (no spend).
    3. Remaining quota: if not provided, read from credit log; if still None,
       refuse as quota unreadable.
    4. Credit floor: if remaining - est_credits <= CREDIT_FLOOR, refuse with
       "floor" wording.
    5. Live odds cap: if spent_today(band=LIVE_ODDS) + est_credits would exceed
       LIVE_ODDS_DAILY_CAP, refuse with "cap" in the reason.

    Unlike can_spend(), this NEVER checks DAILY_ENVELOPE: the live odds band
    is separate and has its own cap (LIVE_ODDS_DAILY_CAP).
    """
    if not live_odds_enabled(env):
        return Decision(False, "refused: live odds disabled (LIVE_ODDS is not set)")

    if est_credits <= 0:
        return Decision(True, "ok: live odds non-positive request")

    if remaining is None:
        remaining = remaining_today(now=now, store=store)

    if remaining is None:
        return Decision(False,
                       "skipped: quota unreadable (no credit_log row for today)")

    if remaining - est_credits <= CREDIT_FLOOR:
        return Decision(False, f"skipped: credit floor (remaining={remaining}, "
                               f"floor={CREDIT_FLOOR}, requested={est_credits})")

    spent = spent_today(now=now, store=store, band=LIVE_ODDS)
    if spent + est_credits > LIVE_ODDS_DAILY_CAP:
        return Decision(False, f"refused: live odds cap ({spent} of "
                               f"{LIVE_ODDS_DAILY_CAP} spent today, +{est_credits} "
                               f"would exceed it)")

    return Decision(True, f"ok: live odds {spent}+{est_credits} of "
                          f"{LIVE_ODDS_DAILY_CAP} today")


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
    """Measured `credits_per_event` for `family`, or None if unmeasured/unknown.

    A row recorded from a degenerate probe (see `_payload_shape`) does not
    count as a measurement: it was priced off a payload too thin to trust
    (fewer than 2 books, or fewer than 2 of the requested markets actually
    returned), so `family` stays PROBE_REQUIRED until a real probe replaces
    it.
    """
    entry = load_families(path).get(family)
    if not entry or not entry.get("measured") or entry.get("degenerate"):
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
            spent = capture_spent_today(now=now, store=store)
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
    capture_spent = capture_spent_today(now=now, store=store)
    families = load_families(families_path)
    per_family = {}
    for name, entry in families.items():
        degenerate = bool(entry.get("degenerate"))
        measured = bool(entry.get("measured")) and not degenerate
        per_family[name] = {
            "measured": measured,
            "credits_per_event": entry.get("credits_per_event"),
            "measured_utc": entry.get("measured_utc"),
            "degenerate": degenerate,
            "state": ("provisional (degenerate probe)" if degenerate
                      else ("measured" if measured else "PROBE_REQUIRED")),
        }
    live_odds_spent = spent_today(now=now, store=store, band=LIVE_ODDS)
    live_odds_remaining = (LIVE_ODDS_DAILY_CAP - live_odds_spent
                           if live_odds_spent is not None else None)
    return {
        "monthly_allotment": MONTHLY_ALLOTMENT,
        "reset_cycle_days": RESET_CYCLE_DAYS,
        "quota_reset_utc": _utc_iso(quota_reset_utc(now)),
        "days_until_reset": days_until_reset(now),
        "daily_envelope": DAILY_ENVELOPE,
        "credit_floor": CREDIT_FLOOR,
        "remaining_today": remaining,
        "spent_today": spent,
        "capture_spent_today": capture_spent,
        "envelope_remaining_today": (
            (DAILY_ENVELOPE - capture_spent) if capture_spent is not None else None),
        # 2026-09-19 incident (see the section above capture_spent_today):
        # the checkpoint stream's own health, surfaced instead of assumed.
        "checkpoint_age_minutes": checkpoint_age_minutes(now=now, store=store),
        "checkpoint_anomalies": oversized_checkpoint_deltas(now=now, store=store),
        "live_odds": {
            "enabled": live_odds_enabled(),
            "spent_today": live_odds_spent,
            "cap": LIVE_ODDS_DAILY_CAP,
            "remaining_in_cap": live_odds_remaining,
        },
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
# are probeable this way -- a family with no market list at all (parlay_sgp:
# no endpoint exists, confirmed 2026-09-03 against the vendor's own markets
# page -- see docs/SGP_PARLAY_CAPTURE.md) is not wired here and returns an
# explicit error rather than guessing a market to call.
#
# SPECIAL CASES: "scores" and "tennis_h2h" do not use market lists like odds
# calls -- they use different endpoints (fetch_scores, fetch_odds with sport).
# Return a sentinel marker to indicate these need special handling in probe_family.
def _probe_markets(family: str, provider) -> Optional[tuple]:
    if family in ("batter_props_floor", "batter_props_extra", "batter_props"):
        return provider.BATTER_MARKETS
    if family == "pitcher_props":
        return provider.PROP_MARKETS
    if family == "team_totals":
        return provider.TEAM_TOTALS_MARKETS
    if family == "alternates":
        return provider.ALTERNATE_MARKETS
    if family == "f5_trio":
        return provider.EVENT_MARKETS
    if family == "scores":
        return ("SPECIAL:fetch_scores",)  # Sentinel for special handling
    if family == "tennis_h2h":
        return ("SPECIAL:fetch_odds_tennis_h2h",)  # Sentinel for special handling
    return None


# Minimum lead time an event must have over "now" to be probe-eligible. A
# probe against an event whose commence_time has already passed (or is about
# to) returns a payload thinned by books/markets pulling their lines as the
# game starts -- exactly the bug this constant fixes: a 03:26Z probe against
# an event that had gone final at 23:41Z the day before measured 1
# credit/event off a 1-book, 1-outcome payload. 45 minutes is a conservative
# floor, not a measured fact; configurable per call for a caller that needs
# a different margin.
PROBE_MIN_LEAD_MINUTES = 45


def _payload_shape(payload, requested_markets, commence_time=None, is_scores=False,
                    is_multi_event=False) -> dict:
    """Books/markets/outcomes actually returned by a probe fetch, plus the
    `degenerate` verdict (S17 bugfix): fewer than 2 books, or fewer than 2 of
    the requested markets actually present, means the payload is too thin to
    trust as a per-event cost measurement -- most likely an event whose
    market had already closed or thinned near/after commence_time.

    For scores payloads (is_scores=True), the payload is a list of events
    (not a dict with bookmakers). We record event count and completed count.

    For multi-event payloads (is_multi_event=True -- provider.fetch_odds()
    returns every event for a sport in one list, not the single-event dict
    fetch_event_odds_with_usage() returns), books/markets/outcomes are
    aggregated across every event in the list: books as the deepest single
    event seen (a representative depth, not a sum that would double-count
    the same books across events), markets/outcomes as totals across every
    event (2026-09-15: the tennis_h2h probe crashed here with
    `'list' object has no attribute 'get'` because this branch did not
    exist -- payload.get("bookmakers") assumed the single-event shape).
    """
    if is_scores:
        # Scores payload is a list of events; no bookmakers, no markets.
        # Record event count and how many are completed.
        events = payload if isinstance(payload, list) else []
        event_count = len(events)
        completed_count = sum(1 for e in events if e.get("completed"))
        # Scores payloads with fewer than 2 events are considered degenerate
        # (thin payload, not enough data to trust the per-event cost).
        degenerate = event_count < 2
        return {
            "event_count": event_count,
            "completed_count": completed_count,
            "degenerate": degenerate,
        }

    if is_multi_event:
        events = payload if isinstance(payload, list) else []
        requested = set(requested_markets or ())
        markets_seen = set()
        books = 0
        outcomes = 0
        for event in events:
            bookmakers = event.get("bookmakers") or []
            books = max(books, len(bookmakers))
            for book in bookmakers:
                for market in (book.get("markets") or []):
                    key = market.get("key")
                    if key is not None:
                        markets_seen.add(key)
                    outcomes += len(market.get("outcomes") or [])
        markets_returned = len(markets_seen & requested) if requested else len(markets_seen)
        needed = min(2, len(requested)) if requested else 2
        degenerate = not events or books < 2 or markets_returned < needed
        return {
            "event_count": len(events),
            "books": books,
            "markets_returned": markets_returned,
            "outcomes": outcomes,
            "degenerate": degenerate,
        }

    # Standard odds payload with bookmakers
    bookmakers = payload.get("bookmakers") or []
    books = len(bookmakers)
    requested = set(requested_markets or ())
    markets_seen = set()
    outcomes = 0
    for book in bookmakers:
        for market in (book.get("markets") or []):
            key = market.get("key")
            if key is not None:
                markets_seen.add(key)
            outcomes += len(market.get("outcomes") or [])
    markets_returned = len(markets_seen & requested) if requested else len(markets_seen)
    # A single-market family (team_totals) can never return two markets, so
    # the market leg is "fewer than min(2, requested)" -- otherwise a real
    # 36-outcome payload would be marked thin forever (found on the first
    # live team_totals probe, 2026-09-03 05:07Z).
    needed = min(2, len(requested)) if requested else 2
    degenerate = books < 2 or markets_returned < needed
    return {
        "books": books,
        "markets_returned": markets_returned,
        "outcomes": outcomes,
        "commence_time": commence_time or payload.get("commence_time"),
        "degenerate": degenerate,
    }


def probe_family(family: str, env=None, provider=None, now=None,
                  families_path=None, store=None, min_lead_minutes=PROBE_MIN_LEAD_MINUTES) -> dict:
    """Spend exactly ONE bounded fetch measuring `family`'s real per-event cost.

    A real API call: one event, one region, `family`'s market list, via
    `odds_provider.fetch_event_odds_with_usage`. The credit delta is read
    from the provider's own usage headers (never guessed), recorded into
    `config/capture_families.json` as `measured: true`, and printed.

    The event probed is the EARLIEST listed event with `commence_time >= now
    + min_lead_minutes` -- never an event that has already started or is
    about to, whose book/outcome count is thinning as lines pull. If no such
    event exists, this refuses and spends nothing (`list_events` is free;
    the paid fetch is never reached).

    The payload's shape (books, markets actually returned, outcome count) is
    recorded on the measured row alongside the cost. A payload with fewer
    than 2 books or fewer than 2 of the requested markets is `degenerate`:
    it is recorded for visibility but does NOT satisfy PROBE_REQUIRED (see
    `family_cost`) and does NOT block a same-day re-probe -- only a
    non-degenerate measurement does.

    Refuses to run twice per family per day (a stored `measured_utc` whose
    UTC date matches today's, from a NON-degenerate measurement, is a
    repeat request, not a re-measurement -- re-probing daily would spend
    real credits on a number that does not change run to run) and respects
    `CREDIT_FLOOR` (checked before spending, against the free quota read,
    same ordering every other paid-capture module in this repo uses).
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
    if entry.get("measured") and not entry.get("degenerate") and already_measured_utc \
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

    measured_utc = _utc_iso(moment)
    result = {"family": family, "probed": False, "measured_utc": measured_utc,
              "credits_remaining_before": remaining_before}

    # Initialize variables that will be set by the fetch paths.
    payload = None
    usage = None
    event_id = None
    event_commence = None
    fetch_markets = list(markets)  # Markets used for fetch/display
    is_scores_fetch = False
    remaining_after_call = None

    # SPECIAL HANDLING FOR SCORES AND TENNIS_H2H
    # These do not use the standard event odds fetch path.
    if family == "scores":
        # Fetch scores directly (no event selection needed)
        try:
            payload = provider.fetch_scores(sport="nfl", env=env)
        except provider.OddsProviderError as exc:
            result["error"] = f"probe fetch failed: {exc}"
            return result
        # For scores, there's no usage header like fetch_event_odds_with_usage,
        # so we estimate based on quota change.
        try:
            remaining_after_call = provider.quota(env).get("remaining")
        except provider.OddsProviderError:
            remaining_after_call = None
        fetch_markets = ["scores"]
        is_scores_fetch = True
    elif family == "tennis_h2h":
        # First, find an active tennis key
        try:
            sports = provider.fetch_sports(all_sports=True, env=env)
        except provider.OddsProviderError as exc:
            result["error"] = f"could not fetch sports list: {exc}"
            return result
        # Find the first ACTIVE tennis sport key. `all_sports=True` also
        # lists out-of-season tournaments (`"active": false`); the 2026-09-16
        # probe took the first tennis key regardless, landed on the
        # Australian Open in September, got an empty payload, and recorded a
        # degenerate measurement that left tennis capture PROBE_REQUIRED from
        # then on. A key with no `active` field at all is treated as active.
        tennis_key = None
        for sport in sports:
            key = sport.get("key", "")
            if "tennis" in key.lower() and sport.get("active", True) is not False:
                tennis_key = key
                break
        if tennis_key is None:
            result["error"] = "no active tennis market found in provider.fetch_sports()"
            return result
        # Now fetch odds for tennis h2h
        try:
            payload = provider.fetch_odds(markets=["h2h"], env=env, sport=tennis_key)
        except provider.OddsProviderError as exc:
            result["error"] = f"probe fetch failed: {exc}"
            return result
        # Read quota after to get billed amount
        try:
            remaining_after_call = provider.quota(env).get("remaining")
        except provider.OddsProviderError:
            remaining_after_call = None
        result["sport_key"] = tennis_key
        fetch_markets = ["h2h"]
    else:
        # STANDARD EVENT ODDS FETCH PATH
        try:
            listed = provider.list_events(env)  # free
        except provider.OddsProviderError as exc:
            return {"family": family, "probed": False,
                    "error": "events unreadable", "message": str(exc)}
        if not listed:
            return {"family": family, "probed": False,
                    "error": "no events available to probe against"}

        earliest_start = moment + timedelta(minutes=min_lead_minutes)
        eligible = []
        for e in listed:
            commence = e.get("commence_time")
            if not commence:
                continue
            try:
                when = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= earliest_start:
                eligible.append((when, e))
        if not eligible:
            return {"family": family, "probed": False,
                    "error": f"no event with commence_time at least "
                             f"{min_lead_minutes} minute(s) in the future "
                             f"({len(listed)} event(s) listed, all too close to "
                             f"or past commence -- refusing to probe against a "
                             f"stale/live event); spent nothing"}
        eligible.sort(key=lambda pair: (pair[0], pair[1].get("id") or ""))
        event = eligible[0][1]
        event_id = event.get("id")
        event_commence = event.get("commence_time")

        try:
            payload, usage = provider.fetch_event_odds_with_usage(
                event_id, markets=markets, env=env)
        except provider.OddsProviderError as exc:
            result["error"] = f"probe fetch failed: {exc}"
            return result

    result["event_id"] = event_id
    result["markets"] = fetch_markets

    # For standard fetch, get billed and remaining from usage; for special cases,
    # these are already set. Calculate billed from usage first.
    if usage is not None:
        billed = usage.get("last")
        if remaining_after_call is None:
            remaining_after_call = usage.get("remaining")
    else:
        billed = None

    # Determine billed amount: prefer explicit value, else quota delta, else default estimate
    if billed is not None:
        credits_per_event = billed
    elif remaining_before is not None and remaining_after_call is not None:
        credits_per_event = max(remaining_before - remaining_after_call, 0)
    else:
        credits_per_event = len(fetch_markets) if fetch_markets else 1

    # For creditlog, use the calculated credits_per_event if billed was not explicit
    billed_for_log = billed if billed is not None else credits_per_event
    creditlog.log(remaining_after_call, billed_for_log, f"budget.probe_family:{family}",
                  store=store if store is not None else CREDIT_LOG_PATH, budget_band=PROBE)

    # Calculate payload shape; special handling for scores/tennis_h2h vs standard odds
    if is_scores_fetch:
        shape = _payload_shape(payload, None, is_scores=True)
    elif family == "tennis_h2h":
        shape = _payload_shape(payload, fetch_markets, is_multi_event=True)
    else:
        shape = _payload_shape(payload, fetch_markets, commence_time=event_commence)
    degenerate = shape.get("degenerate", False)

    # Build source string: different format for special vs standard
    if family == "scores":
        source_str = (f"budget.probe_family: {family} probe fetching NFL scores; "
                      f"billed={billed!r}, remaining_before={remaining_before!r}, "
                      f"remaining_after={remaining_after_call!r}")
    elif family == "tennis_h2h":
        source_str = (f"budget.probe_family: {family} probe fetching h2h odds for "
                      f"{result.get('sport_key')}; "
                      f"billed={billed!r}, remaining_before={remaining_before!r}, "
                      f"remaining_after={remaining_after_call!r}")
    else:
        source_str = (f"budget.probe_family: live {family} probe against event "
                      f"{event_id} ({len(fetch_markets)} market(s), 1 region); "
                      f"billed={billed!r}, remaining_before={remaining_before!r}, "
                      f"remaining_after={remaining_after_call!r}")

    # Append degenerate payload details if applicable
    if degenerate:
        if is_scores_fetch:
            source_str += (f"; DEGENERATE PAYLOAD (event_count={shape.get('event_count')}, "
                          f"completed_count={shape.get('completed_count')}, does not satisfy "
                          f"PROBE_REQUIRED, does not block a same-day re-probe)")
        else:
            source_str += (f"; DEGENERATE PAYLOAD (books={shape.get('books')}, "
                          f"markets_returned={shape.get('markets_returned')}, "
                          f"outcomes={shape.get('outcomes')}, does not satisfy "
                          f"PROBE_REQUIRED, does not block a same-day re-probe)")

    recorded = _record_measurement(
        family, credits_per_event, source=source_str,
        measured_utc=measured_utc, families_path=families_path,
        payload_shape=shape, degenerate=degenerate)

    result["probed"] = True
    result["credits_per_event"] = credits_per_event
    result["credits_remaining_after"] = remaining_after_call
    result["payload_shape"] = shape
    result["degenerate"] = degenerate
    result["recorded"] = recorded
    return result


def _record_measurement(family: str, credits_per_event: int, source: str,
                          measured_utc: str, families_path=None,
                          payload_shape: Optional[dict] = None,
                          degenerate: bool = False) -> bool:
    """Persist a real measurement into config/capture_families.json.

    Never called by anything except a completed `probe_family` fetch --
    this is the only path that may set `measured: true`. `measured` is set
    True regardless of `degenerate` (the fetch DID happen and DID cost a
    credit -- that fact is real); `degenerate` is a separate flag that
    `family_cost`/`can_spend` check to decide whether this row may satisfy
    PROBE_REQUIRED.
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
            "degenerate": degenerate,
            "payload_shape": payload_shape,
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
