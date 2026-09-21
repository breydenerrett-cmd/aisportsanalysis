"""Bounded UFC/MMA h2h capture -- The Odds API sport key mma_mixed_martial_arts.

WHY THIS EXISTS
---------------
UFC odds live under ONE sport key (unlike tennis's per-tournament keys), and
one call to it returns every active MMA event's moneyline board -- the same
shape as `nfl_capture.py`'s featured call, which is why this module mirrors
that one rather than `tennis_capture.py`'s per-key loop.

BOUNDED ON PURPOSE, TWO WAYS
-----------------------------
1. FIGHT-WEEK GATE: a capture is only even considered when at least one MMA
   event is scheduled within `FIGHT_WEEK_HORIZON_DAYS`. There is no MMA
   capture the other 355 days of the year -- this is what keeps a keyless,
   always-on cadence from quietly spending credits against an empty
   calendar.
2. CADENCE: within a fight week, at most one pull every `GENERAL_INTERVAL_
   MINUTES` (the owner's "at most every 60 minutes" instruction), PLUS one
   extra pull per bout when it enters its own `PREFIGHT_MINUTES` window
   ("within about 2 hours of each bout's commence_time") -- so a Saturday
   card with bouts starting hours apart gets a fresh price close to each
   fight, not just once at the top of the card.

Because one call returns the whole card, a single fetch satisfies BOTH the
general cadence and any bout's pre-fight window at once, exactly like
`nfl_capture.py`'s "a capture is taken once whenever any game reaches a due
phase" design -- see that module's docstring for the shared reasoning.

CREDITS: `FAMILY` starts UNMEASURED in config/capture_families.json on
purpose. `src.capture.budget.can_spend` refuses to spend against an
unmeasured family (PROBE_REQUIRED) until a real `budget --probe mma_h2h`
measurement is recorded -- this module never guesses a cost, and it never
spends a credit before that probe exists, matching the same
never-spend-when-unmeasured rule every other family in this repo already
follows.

DESIGN: APPEND-ONLY DONE-LOG, exactly `tennis_capture.py`'s shape --
(key, event_id, phase) tuples, `key` fixed at SPORT_KEY here since there is
only one. `phase` is "prefight" (one bout's own ~2h window) or "general"
(the card-level 60-minute cadence, marked against the sentinel event id
`_GENERAL_EVENT_ID` since it is not about any one bout).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.capture import budget
from src.paths import processed_path
from src.pipeline import creditlog, snapshots

LOG = logging.getLogger(__name__)

SPORT_KEY = "mma_mixed_martial_arts"
FAMILY = "mma_h2h"
# Estimate only (docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md S5.2:
# "roughly 1-2 credits" per pull regardless of card size). It is passed as
# `est_credits` to `budget.can_spend`, which -- because FAMILY is unmeasured
# -- refuses every spend on PROBE_REQUIRED regardless of this number. Only a
# real `budget --probe mma_h2h` measurement (recorded in
# config/capture_families.json) can turn this family's spending on.
CREDITS_PER_CAPTURE = 2

GENERAL_INTERVAL_MINUTES = 60
PREFIGHT_MINUTES = 120
# UFC cards are frequent (often weekly) -- an 8-day horizon would make the
# hourly cadence fire almost continuously, all year, which is not "during
# fight week" any more, it is "always". 3 days (Thursday through fight
# night for a Saturday card) is the actual "fight week" window the owner's
# instruction describes -- weigh-ins and the final line moves happen in
# this window, and this is what keeps the estimate in
# docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md S5.2 roughly
# honest. Tune here, not in the cadence itself, once mma_h2h is measured
# and a real weekly credit figure is in hand.
FIGHT_WEEK_HORIZON_DAYS = 3

DEFAULT_DONE_PATH = processed_path("mma_capture_done.jsonl")
_GENERAL_EVENT_ID = "__card__"
_GENERAL_PHASE = "general"
_PREFIGHT_PHASE = "prefight"


@dataclass(frozen=True)
class DonePair:
    key: str
    event_id: str
    phase: str
    observed_utc: str


def _read_done(path: str | Path = DEFAULT_DONE_PATH) -> set:
    """(key, event_id, phase) tuples already captured. Never raises; a
    corrupted line costs one row, not the whole log (see tennis_capture's
    identical convention)."""
    done_set = set()
    path = Path(path)
    if not path.exists():
        return done_set
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    key = obj.get("key")
                    event_id = obj.get("event_id")
                    phase = obj.get("phase")
                    if key and event_id and phase:
                        done_set.add((key, event_id, phase))
                except json.JSONDecodeError as e:
                    LOG.warning(f"Skipping corrupted line {line_num} in {path}: {e}")
    except Exception as e:
        LOG.warning(f"Error reading done log {path}: {e}")
    return done_set


def _last_general_capture(path: str | Path = DEFAULT_DONE_PATH) -> Optional[datetime]:
    """The most recent `observed_utc` among rows marked phase="general", or
    None if the general cadence has never fired. Read fresh every call
    (this log is small -- a handful of rows a week) rather than kept in a
    second state file, so there is exactly one append-only source of truth
    for "when did capture last run", the same way `tennis_capture`'s done
    log is the only source of truth for "was this pair captured"."""
    path = Path(path)
    if not path.exists():
        return None
    newest = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("phase") != _GENERAL_PHASE:
                    continue
                when = _parse_iso(obj.get("observed_utc"))
                if when is not None and (newest is None or when > newest):
                    newest = when
    except Exception as e:
        LOG.warning(f"Error scanning done log {path} for last general capture: {e}")
    return newest


def _append_done(pairs: list[DonePair], path: str | Path = DEFAULT_DONE_PATH) -> int:
    if not pairs:
        return 0
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            if path.stat().st_size > 0:
                with path.open("rb") as rb:
                    rb.seek(-1, 2)
                    if rb.read(1) != b"\n":
                        f.write("\n")
            for pair in pairs:
                row = {
                    "key": pair.key,
                    "event_id": pair.event_id,
                    "phase": pair.phase,
                    "observed_utc": pair.observed_utc,
                }
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
        return len(pairs)
    except Exception as e:
        LOG.warning(f"Error appending to done log {path}: {e}")
        return 0


def _now(now: Optional[datetime] = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _timestamp(now: Optional[datetime] = None) -> str:
    return _now(now).isoformat()


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def run(*, now: Optional[datetime] = None,
        list_events: Optional[Callable] = None,
        fetch_normalized: Optional[Callable] = None,
        spend_guard: Optional[Callable] = None,
        snapshot_path: Optional[str] = None,
        multibook_path: Optional[str] = None,
        done_path: str = DEFAULT_DONE_PATH,
        env: Optional[dict] = None, quota: Optional[Callable] = None,
        record_credit: Optional[Callable] = None) -> dict:
    """Run one cycle of UFC/MMA h2h capture.

    Returns a dict with keys: captured (bool), reason (str, when not
    captured), credits, rows, prefight_events (event ids whose ~2h window
    this run covered), general (bool, whether the 60-minute cadence fired).
    """
    current_time = _now(now)
    observed_utc = _timestamp(current_time)

    if list_events is None:
        from src.providers import odds
        list_events = odds.list_events

    if fetch_normalized is None:
        from src.providers import odds
        fetch_normalized = odds.fetch_normalized
        if quota is None:
            quota = odds.quota
        if record_credit is None:
            record_credit = creditlog.log

    if spend_guard is None:
        spend_guard = budget.can_spend

    if snapshot_path is None:
        snapshot_path = snapshots.DEFAULT_SNAPSHOT_PATH
    if multibook_path is None:
        multibook_path = snapshots._resolve_multibook_path(snapshot_path, None)

    try:
        events = list_events(env=env, sport=SPORT_KEY)
    except Exception as e:
        return {"captured": False, "reason": f"list_events error: {e}",
                "credits": 0, "rows": 0}

    upcoming = []
    for event in events or ():
        event_id = event.get("id")
        commence_str = event.get("commence_time")
        if not event_id or not commence_str:
            continue
        commence = _parse_iso(commence_str)
        if commence is None or commence <= current_time:
            continue
        upcoming.append((event_id, commence, event))

    if not upcoming:
        return {"captured": False, "reason": "no upcoming MMA events",
                "credits": 0, "rows": 0}

    horizon = current_time + timedelta(days=FIGHT_WEEK_HORIZON_DAYS)
    in_week = [item for item in upcoming if item[1] <= horizon]
    if not in_week:
        return {"captured": False,
                "reason": (f"no MMA event within the {FIGHT_WEEK_HORIZON_DAYS}-day "
                           "fight-week horizon -- not fight week, nothing to capture"),
                "credits": 0, "rows": 0}

    done = _read_done(done_path)

    prefight_window = current_time + timedelta(minutes=PREFIGHT_MINUTES)
    prefight_due_ids = [event_id for event_id, commence, _event in in_week
                        if commence <= prefight_window
                        and (SPORT_KEY, event_id, _PREFIGHT_PHASE) not in done]

    last_general = _last_general_capture(done_path)
    general_due = (last_general is None or
                  (current_time - last_general) >= timedelta(minutes=GENERAL_INTERVAL_MINUTES))

    if not prefight_due_ids and not general_due:
        return {"captured": False,
                "reason": ("not due: the 60-minute cadence has not elapsed and no "
                           "bout has entered its own pre-fight window"),
                "credits": 0, "rows": 0}

    decision = spend_guard(FAMILY, CREDITS_PER_CAPTURE, now=current_time)
    if not decision.allowed:
        return {"captured": False, "reason": decision.reason, "credits": 0, "rows": 0}

    try:
        payload = fetch_normalized(markets=["h2h"], env=env, sport=SPORT_KEY)
    except Exception as e:
        return {"captured": False, "reason": f"fetch error: {e}",
                "credits": 0, "rows": 0}

    rows = []
    for event in payload.get("events", []):
        event_id = event.get("event_id")
        for market_key, market in (event.get("markets") or {}).items():
            rows.append({
                "observed_utc": observed_utc,
                "event_id": event_id,
                "commence_time": event.get("commence_time"),
                "away_team": event.get("away_team"),
                "home_team": event.get("home_team"),
                "market": market_key,
                "book": market.get("book"),
                "prices": {k: v for k, v in market.items() if k not in ("book", "last_update")},
                "book_last_update": market.get("last_update"),
                "sport": "mma",
            })

    written = snapshots.append(rows, path=snapshot_path)
    mb_rows = snapshots.multibook_rows(observed_utc, payload.get("events", []), sport="mma")
    mb_written = snapshots.append(mb_rows, path=multibook_path)

    done_pairs = [DonePair(SPORT_KEY, event_id, _PREFIGHT_PHASE, observed_utc)
                  for event_id in prefight_due_ids]
    if general_due:
        done_pairs.append(DonePair(SPORT_KEY, _GENERAL_EVENT_ID, _GENERAL_PHASE, observed_utc))
    _append_done(done_pairs, done_path)

    if record_credit is not None:
        try:
            quota_now = quota(env) if quota is not None else {}
            record_credit(quota_now.get("remaining"), quota_now.get("last"),
                          "mma_capture.run", now=current_time,
                          budget_band="live_capture")
        except Exception as exc:  # noqa: BLE001 -- logging never fails a capture
            LOG.warning("mma_capture: credit log failed: %s", exc)

    return {
        "captured": True,
        "credits": CREDITS_PER_CAPTURE,
        "rows": written + mb_written,
        "prefight_events": prefight_due_ids,
        "general": general_due,
    }
