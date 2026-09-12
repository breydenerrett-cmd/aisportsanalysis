"""Batter-prop CAPTURE: owner decision 3 (2026-09-03) -- capture batter props
now, within the ~900/day envelope, with hard guards. Extended 2026-09-12
(docs/DECISION_PROP_CAPTURE_SPEND.md, owner approved) to capture each game
TWICE per slate date -- see "TWO PHASES PER GAME" below.

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
  sheds first among the batter surfaces (rank 7, just above featured). The
  cap is sized to the FULL slate (EXTRA_GAMES_PER_NIGHT), not a sample of
  it -- see that constant's own comment.

Markets: `src.providers.odds.BATTER_MARKETS` (6 keys), fetched together in
one per-event call -- 6 credits/event/region at the default single region.

TWO PHASES PER GAME
--------------------
Each game on today's slate may be captured up to TWICE per slate date: once
in the BASELINE window (5-7h before first pitch, pre-lineup) and once in the
GATE window (0-2h before first pitch, post-lineup for ~85% of games). See
BASELINE_LEAD_MIN_MINUTES/BASELINE_LEAD_MAX_MINUTES and `_capture_phase`
below for the full rationale and credit arithmetic. Every written row (the
L1 marker AND the L2 projected rows) carries `"capture_phase": "baseline"`
or `"gate"` recording which pass produced it.

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
this project's SELECTION identity convention (src/board/ids.py). Whether a
GAME is due for another fetch at all is a separate question, tracked by
`_done_today` per (event_id, game_date, capture_phase) -- so a game already
captured baseline is still due for gate, and the reverse, but never a third
capture within either phase.

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
# non-droppable floor's NON_DROPPABLE_GAMES_PER_NIGHT. This is the family
# DROP_ORDER sheds first among the batter surfaces, but the cap itself is
# sized to the FULL SLATE, not to a token sample of it -- owner decision
# 2026-09-12 (docs/DECISION_PROP_CAPTURE_SPEND.md): "full slate (~15/night)"
# was the approved option, and the store already shows the existing gate
# pass fetching 9-16 events on a normal night, so a cap here below that
# range would silently reintroduce a partial-slate ceiling the owner did not
# ask for. 18 covers the observed range with room for a heavy doubleheader
# night; it is a ceiling, not a target -- a thin slate still spends less.
EXTRA_GAMES_PER_NIGHT = 18

# A run may not fetch more than this many events, whatever the arithmetic
# above concludes -- the same per-run ceiling shape as prop_listing/prop_prices.
# Still one ceiling for BOTH phases combined: the baseline and gate windows
# never overlap for the same game (see BASELINE_LEAD_MIN/MAX_MINUTES below),
# so at most one phase per game can be due in any single run, and the sum
# across all games due this run is still bounded by slate size.
MAX_FETCHES_PER_RUN = budget_module.NON_DROPPABLE_GAMES_PER_NIGHT + EXTRA_GAMES_PER_NIGHT

CREDIT_FLOOR = prop_listing.CREDIT_FLOOR

# WHEN a game is captured, which until 2026-09-11 was "the first time a run
# saw it" and is now anchored to its own first pitch.
#
# THE DEFECT THIS FIXES. Each game is captured once per slate date
# (`_done_today`), and forward_capture.sh calls this pass every fifteen
# minutes. So the first run after the Eastern date rolled over captured the
# whole plan and every later run that day found nothing due. Measured over
# the store on 2026-09-11: all 9,672 batter-prop quotes landed between 04:00
# and 09:10 UTC -- midnight to 5am Eastern -- a median 17.3 HOURS before
# first pitch.
#
# WHY THAT IS THE WRONG HOUR. A posted lineup sets each batter's SLOT, and
# slot sets plate appearances (playerprops.SLOT_PLATE_APPEARANCES: leadoff
# 4.467, nine-hole 3.461). A hitter moving up the order gains roughly 29%
# more chances, which is enormous against a hits or total-bases line.
# Lineups post a median 2.9 hours before first pitch. Capturing at 17 hours
# meant that of 77 games where we held both a lineup event and prop quotes,
# ZERO had a quote on both sides of the posting. The single most informative
# moment for a player total was one we had never once priced.
#
# T-2h matches the `T-2h` band prop_listing's SLOTS grid already uses, and by
# then roughly 85% of lineups are out (lead-time p10 1.84h, median 2.92h).
#
# THIS DOES NOT CHANGE SPEND. Same games, same once-per-slate-date rule, same
# floor and extra families, same caps -- only the hour. A game sits inside
# this window for two hours and the pass runs every fifteen minutes, so it
# gets about eight chances to catch each one.
CAPTURE_LEAD_MINUTES = 120

# ---------------------------------------------------------------------------
# THE BASELINE PASS (2026-09-12, docs/DECISION_PROP_CAPTURE_SPEND.md, owner
# approved)
# ---------------------------------------------------------------------------
#
# THE GATE WINDOW ABOVE ONLY EVER CATCHES ONE SIDE OF EACH GAME: POST-LINEUP.
# By design -- T-120m is chosen because ~85% of lineups are out by then. But
# a single capture per game per slate date means we only ever get ONE side,
# never both on the same game -- and, corrected 2026-09-12 (a checker caught
# this block asserting the opposite of the measured fact, contradicting
# docs/DECISION_PROP_CAPTURE_SPEND.md, docs/LINEUP_DIRECTION_RESULT.md and
# this file's own CAPTURE_LEAD_MINUTES history two screens up), the side
# we've actually been getting is PRE-lineup, not post. Measured on the store
# as it stood 2026-09-11: of 17,149 batter-prop rows, lead time ran min
# 3.38h / median 16.42h / max 22.08h -- 14,470 rows (84%) at 5h or more, ZERO
# inside 2h. Every held row is pre-lineup (lineups post a median 2.92h out);
# ZERO are post-lineup. That is the CAPTURE_LEAD_MINUTES fix's own starting
# point restated: before 2026-09-11 this module captured once, ~17.3h before
# first pitch, hours ahead of any lineup. The 2026-09-11 fix moves the ONE
# capture this module makes to T-120m -- post-lineup for ~85% of games --
# which corrects the historical blind spot going forward but trades it for
# the opposite one: a game now relying solely on the gate window holds the
# post-lineup side and never the pre-lineup side to compare it against. So a
# hitter moving up the order (SLOT_PLATE_APPEARANCES: leadoff 4.467 PA vs
# nine-hole 3.461, ~29% more chances) has still never once been priced on
# both sides of the move that mattered -- not for lack of a pre-lineup
# quote, but because a single per-game capture only ever banks one side.
#
# So a SECOND pass, anchored to the SAME first-pitch clock as the gate,
# fires 5-7 hours out -- clear of the LATEST-posting lineups (lead-time p10
# 1.84h = 110min, well under BASELINE_LEAD_MIN_MINUTES=300) and a full two
# hours ahead of the median post (2.92h = 175min). This is NOT "before ANY
# lineup posts": p10 is the SHORT-lead tail -- the latest-posting lineups --
# and says nothing about the EARLIEST-posting tail (p90/max), which is not
# measured here or in docs/PLAYER_PROPS_NEXT.md. An unusually early lineup
# could still land before T-5h; the baseline pass is a second look, not a
# guarantee of pre-lineup timing for every game (see "additional
# information... never a precondition" below). It closes a full 3 hours
# before the gate window opens (BASELINE_LEAD_MIN_MINUTES=300 >
# CAPTURE_LEAD_MINUTES=120), so the two windows never overlap and a single
# instant is never billed twice under two different phase labels.
#
# EACH GAME ON THE SLATE MAY THEREFORE BE CAPTURED TWICE PER SLATE DATE, NOT
# ONCE: once when it is baseline-due, once when it is gate-due. `_done_today`
# tracks this per (event_id, game_date, capture_phase) rather than per
# (event_id, game_date) -- the same game clearing the gate window no longer
# blocks the baseline window it already cleared, or the reverse, but neither
# phase is ever billed a second time for the same game/date. A game first
# observed already inside the gate window (baseline's own window necessarily
# already elapsed) gets the gate capture only -- there is no mechanism here
# that retroactively "catches up" a missed baseline, by design: baseline is
# additional information when available, never a precondition for gate.
#
# CREDIT ARITHMETIC (measured 2026-09-03, docs/DECISION_PROP_CAPTURE_SPEND.md).
# Batter-prop capture bills 5-6 credits/event (5 is the measured figure;
# 6 = CREDITS_PER_EVENT is the worst case, 1 credit/market x 6 markets, and
# what the budget guards actually charge against). A full slate is ~15
# events; two passes/night is ~30 event-captures/night, so 150-180 credits/
# night worst case against the 900/day LIVE_CAPTURE envelope
# (budget.DAILY_ENVELOPE) -- 17-20% of one night's envelope -- and against
# the 22,699 credits remaining this billing cycle (measured 2026-09-12) it
# rounds to nothing. THIS DOES NOT WEAKEN ANY GUARD: can_spend's floor,
# envelope and per-family measured-cost check all run exactly as before,
# once per fetch, for every baseline fetch exactly as for every gate fetch --
# only the number of times a given game passes through them grows from at
# most one to at most two.
BASELINE_LEAD_MAX_MINUTES = 420  # T-7h: the far edge of the baseline window.
BASELINE_LEAD_MIN_MINUTES = 300  # T-5h: the near edge -- 3h clear of the gate.

ENV_SWITCH = "BATTER_PROPS"

# STOLEN BASES (2026-09-12, docs/DECISION_PROP_CAPTURE_SPEND.md). Off by
# default -- setting this to "1" adds `batter_stolen_bases`
# (odds_provider.STOLEN_BASE_MARKETS) to the markets this module fetches for
# EVERY captured event, on top of the six measured BATTER_MARKETS keys. It
# stays off by default because the owner-approved path here is
# PROBE-then-capture: `scripts/probe_stolen_bases.py` answers, cheaply,
# whether any book even offers this market before a single live credit is
# spent capturing it on a schedule. Flip this only after that probe has run
# and come back positive -- flipping it blind spends a credit/event on a
# market that may not exist, and (unlike the six measured markets) its real
# per-event cost is not yet in config/capture_families.json, so the budget
# estimate below is a plain market count, not a measured figure.
STOLEN_BASES_ENV_SWITCH = "STOLEN_BASES"


def _stolen_bases_enabled(env=None) -> bool:
    source = os.environ if env is None else env
    return (source.get(STOLEN_BASES_ENV_SWITCH) or "").strip().lower() in {
        "on", "1", "yes", "true"}


def _capture_markets(env=None) -> tuple:
    """Markets this run requests: MARKETS, plus `batter_stolen_bases` when
    `_stolen_bases_enabled`. See STOLEN_BASES_ENV_SWITCH's comment above for
    why this defaults off and what turning it on costs."""
    if _stolen_bases_enabled(env):
        return MARKETS + odds_provider.STOLEN_BASE_MARKETS
    return MARKETS


class BatterPropsError(RuntimeError):
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
    `processed_store` for the files -- the same contract prop_prices.run()
    offers. `credit_log_store` is the EXTRA_FAMILY envelope check's own seam
    (the floor family bypasses the envelope by contract -- `can_spend` never
    gates `NON_DROPPABLE_FAMILY` on the floor or the envelope -- so it never
    needs this): None (default) reads the real credit_log.jsonl via
    `can_spend`'s own default, which is `capture_spent_today()` -- the
    LIVE_CAPTURE-band total, never the unbanded `spent_today()`.
    """
    clock_now = _now(now)
    report = {"observed_utc": _utc_iso(clock_now), "fetches": 0, "rows": 0,
              "markers": 0, "credits_spent": 0, "errors": [], "escalate": [],
              "games_due": 0, "skipped": None, "budget_reasons": {},
              "fetches_by_phase": {}}

    # MARKETS unless STOLEN_BASES=1 (off by default -- see that switch's own
    # docstring). `credits_per_event` tracks whichever set is actually being
    # requested this run, rather than the fixed CREDITS_PER_EVENT constant,
    # so the budget guard below is never asked to approve a request smaller
    # than the one about to be made.
    markets = _capture_markets(env)
    credits_per_event = len(markets)

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
    creditlog.log(remaining, quota_now.get("last"), "batter_props.run",
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
    floor_ids = set(budget_module.rotated_floor_games(all_ids, today))
    by_id = {e.get("id"): e for e in slate if e.get("id")}

    # Floor games first, always -- the non-droppable surface must never be
    # starved by an "extra" game that happened to sort earlier. Each entry
    # now carries its capture PHASE ("baseline" or "gate") alongside the
    # family: `_capture_phase` returns whichever of the two windows `now`
    # currently falls inside for that game (never both -- see
    # BASELINE_LEAD_MIN_MINUTES's docstring), and the done-check is keyed by
    # phase so a game already captured baseline is still due for gate, and
    # the reverse, but neither phase twice.
    plan = []
    not_yet = 0
    for event_id in sorted(floor_ids):
        phase = _capture_phase(by_id[event_id], clock_now)
        if phase is None:
            not_yet += 1
            continue
        if (event_id, today, phase) in done_today:
            continue
        plan.append((FLOOR_FAMILY, by_id[event_id], phase))

    remaining_slots = EXTRA_GAMES_PER_NIGHT
    for event_id in all_ids:
        if remaining_slots <= 0:
            break
        if event_id in floor_ids:
            continue
        phase = _capture_phase(by_id[event_id], clock_now)
        if phase is None:
            not_yet += 1
            continue
        if (event_id, today, phase) in done_today:
            continue
        plan.append((EXTRA_FAMILY, by_id[event_id], phase))
        remaining_slots -= 1

    # Not a skip reason in the budget sense -- these games are still coming,
    # and a later run the same day will take them. Reported so a reader of
    # the transcript can tell "waiting for the window" from "dropped".
    report["games_outside_window"] = not_yet

    report["games_due"] = len(plan)

    spent_this_run = 0
    for family, event, phase in plan:
        if report["fetches"] >= MAX_FETCHES_PER_RUN:
            report["escalate"].append(
                "ESCALATE: batter-props capture hit its per-run fetch "
                f"ceiling ({MAX_FETCHES_PER_RUN}) -- more games came due "
                "than the design expects; check the plan before the next run")
            break

        decision = budget_module.can_spend(
            family, credits_per_event, remaining=remaining,
            store=credit_log_store)
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
                event.get("id"), markets=markets, env=env)
        except provider.OddsProviderError as exc:
            append([{
                "observed_utc": observed,
                "family": family,
                "event_id": event.get("id"),
                "game_date": today,
                "capture_phase": phase,
                "error": str(exc),
            }], store)
            report["errors"].append(f"{event.get('id')}: {exc}")
            continue

        billed = (usage or {}).get("last")
        charged = credits_per_event if billed is None else billed
        remaining = None if remaining is None else remaining - charged
        spent_this_run += charged
        report["fetches"] += 1
        report["credits_spent"] += charged
        report["fetches_by_phase"][phase] = report["fetches_by_phase"].get(phase, 0) + 1

        projected = _project(payload, event, observed, today, phase, markets)
        written = _append_projected(projected, processed_store)

        append([{
            "observed_utc": observed,
            "family": family,
            "event_id": payload.get("id") or event.get("id"),
            "commence_time": payload.get("commence_time") or event.get("commence_time"),
            "game_date": today,
            "capture_phase": phase,
            "poll": True,
            "rows_projected": written,
            "credits_last": billed,
        }], store)
        report["markers"] += 1
        report["rows"] += written

    report["credits_cumulative"] = credits_spent(read(store))
    return report


def _project(payload, event, observed, game_date, phase, markets=MARKETS) -> list:
    """One row per (market, book, selection, line): MARKET/SELECTION/LINE/
    PRICE/BOOK/TIMESTAMPS plus the provider's own `last_update`.

    `markets` is the set actually REQUESTED this fetch (default MARKETS,
    the six measured keys) -- rows are kept only for a market in that set,
    so a payload that happens to echo back a market nobody asked for is
    never silently projected. This is also how STOLEN_BASES=1 reaches the
    L2 store: `run()` passes its own `_capture_markets(env)` result through
    here, and `batter_stolen_bases` rows are only ever kept when that wider
    set is what was actually billed for.

    SELECTION is the player id when the provider supplies one (`description_
    id`/`participant_id`, whichever the payload carries), falling back to the
    player name -- plus the over/under side, matching src/board/ids.py's
    "the line is part of the selection" convention: a different side is a
    different selection, not a modifier on one.

    `phase` ("baseline" or "gate") is stamped onto every row as
    `capture_phase` so a reader can tell which of the two passes produced a
    given quote without rejoining against the raw store's marker rows --
    the whole point of the baseline pass is a before/after comparison, and
    that comparison needs the phase on the row it is comparing, not just on
    the marker. NOT part of `_projected_key`'s idempotency tuple on purpose:
    a book whose `last_update` genuinely has not moved between the two
    passes is the same observed price twice, correctly deduplicated at the
    L2 layer exactly as a same-phase re-poll already is -- the raw store's
    marker (billed, phase-stamped) is still the record that both fetches
    happened.
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
                    "capture_phase": phase,
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


def _in_capture_window(event, now, lead_minutes=CAPTURE_LEAD_MINUTES) -> bool:
    """Is this game close enough to first pitch to be worth a GATE credit yet?

    True inside `(0, lead_minutes]` before first pitch. False once first
    pitch has passed -- a price after the game started is not a pregame
    price and is worth nothing here.

    An event with no readable commence_time returns True: an unparseable
    timestamp must not silently stop a game being captured at all, which
    would turn a clock bug into a permanent coverage hole. That is the same
    direction prop_listing's own guards fail in. This is deliberately the
    FAIL-OPEN phase -- `_capture_phase` checks this one first for exactly
    that reason -- rather than the baseline window below, which has no
    equivalent obligation: the gate is the backstop every game must clear at
    least once, baseline is a bonus second look this contract never promised.
    """
    commence = prop_listing._parse_iso(event.get("commence_time"))
    if commence is None:
        return True
    minutes = (commence - now).total_seconds() / 60.0
    return 0 < minutes <= lead_minutes


def _in_baseline_window(event, now, lead_min=BASELINE_LEAD_MIN_MINUTES,
                         lead_max=BASELINE_LEAD_MAX_MINUTES) -> bool:
    """Is this game far enough out to be worth a BASELINE (pre-lineup) credit?

    True inside `[lead_min, lead_max]` minutes before first pitch -- see
    BASELINE_LEAD_MIN_MINUTES's module-level docstring for why that band sits
    where it does relative to lineup-posting and to the gate window.

    An event with no readable commence_time returns False, the opposite of
    `_in_capture_window`'s fail-open: baseline is the SECOND of two chances
    at a game, never the only one, so an unparseable timestamp here simply
    forfeits the earlier look rather than needing its own escape hatch --
    the gate window's unconditional fail-open still guarantees the game is
    captured at least once.
    """
    commence = prop_listing._parse_iso(event.get("commence_time"))
    if commence is None:
        return False
    minutes = (commence - now).total_seconds() / 60.0
    return lead_min <= minutes <= lead_max


def _capture_phase(event, now):
    """Which capture phase, if any, `event` is due for right now.

    Returns "gate" if inside the gate window (checked first: it is the
    backstop every game must clear, and the fail-open destination when
    first pitch is unparseable), else "baseline" if inside the baseline
    window, else None if due for neither -- too far out, in the dead zone
    between the two windows, or already started. The two windows never
    overlap (BASELINE_LEAD_MIN_MINUTES=300 > CAPTURE_LEAD_MINUTES=120), so
    this ordering never actually has to break a tie; it exists for the
    unparseable-commence_time case, where only the gate check can fire.
    """
    if _in_capture_window(event, now):
        return "gate"
    if _in_baseline_window(event, now):
        return "baseline"
    return None


def _done_today(rows, game_date) -> set:
    """(event_id, game_date, capture_phase) already captured today.

    Phase is part of the key (2026-09-12, the baseline-pass change): a game
    captured in the baseline window is still due for the gate window later
    the same day, and the reverse, but neither phase is ever billed twice.
    A legacy row written before `capture_phase` existed reads as phase
    `None` here, which never matches either live phase string -- it cannot
    silently satisfy a "baseline" or "gate" check it was never billed under.
    """
    out = set()
    for row in rows or []:
        if row.get("poll") and row.get("game_date") == game_date:
            out.add((row.get("event_id"), game_date, row.get("capture_phase")))
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
        by_phase = report.get("fetches_by_phase") or {}
        print(f"batter props: {report['fetches']} fetches "
              f"(baseline={by_phase.get('baseline', 0)}, gate={by_phase.get('gate', 0)}), "
              f"{report['rows']} rows, {report['markers']} markers, "
              f"{report['credits_spent']} credits "
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
