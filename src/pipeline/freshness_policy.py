"""ONE place that says how old each store may be, and what to tell the owner when it is too old.

WHY THIS EXISTS (2026-10-19)
----------------------------
Three surfaces judged freshness three different ways:

  * the admin Health tab (web/js/admin-views.js) coloured every store by one global rule (green to 24h,
    amber to 72h, red past that) and read "N days behind" as amber for stores whose own tolerance is
    three days;
  * ``src/appstate/alert_feed.py`` (the alerts RSS the owner's Zap emails) knew only odds (3h) and the
    ``core_stale`` list;
  * ``src/pipeline/store_freshness.py`` held the day-count tolerances for the stores the pages read.

So on 2026-10-19 the Health tab showed "Prop listings: Stale, 12 days" while ``/health`` said ok and the
feed stayed empty. The store in question was a finished audit, not a stalled capture (see PROP_LISTING
below), and nothing could say so. Now the thresholds live HERE; ``apphealth.report`` evaluates them once
(``summarize``) and ships the verdicts as ``freshness`` in its payload; the admin page, the alerts feed and
the admin digest all read that one block. A test fails if any of them grows a threshold of its own.

THE VERDICT STATES
------------------
  fresh          inside its limit
  aging          past ``fresh_hours`` but not yet past ``stale_hours`` (amber, never an alert)
  stale          past ``stale_hours`` while the store IS expected to move (red, one alert per UTC day)
  problem        expected, but absent / empty / unreadable (red; unreadable is already a /health reason, so
                 it is shown but not alerted twice)
  not_expected   grey "Not expected now" with the reason: off-season, no game today, the regular season is
                 over, or a bounded audit that has finished. NEVER amber or red, never an alert.

A store with a ``when`` of ``game_day`` is only expected to move on a day MLB plays; ``season`` stores are
expected to move every day of the season. Both are "not expected" outside the season window.

GAME DAY is read from ``data/processed/event_game_map.jsonl`` (MLB only, written by the capture slot: one
row per odds event matched to a schedule game, with its first pitch). It is cheap (a tail read). If that
map is itself stale or missing, the day is UNKNOWN and treated as a game day: an unknown must raise the
question, not silence it.

Stdlib only, no network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional

# ---------------------------------------------------------------------------
# Day-count tolerances for the stores the computed pages read
# (src/pipeline/store_freshness.py imports these; they used to live there).
# ---------------------------------------------------------------------------
# A store is STALE when its coverage ends more than this many days behind yesterday (Eastern).
RESULTS_TOLERANCE_DAYS = 1
DAILY_TOLERANCE_DAYS = 1
PITCHER_TOLERANCE_DAYS = 2
SEASON_AGGREGATE_TOLERANCE_DAYS = 3        # transactions, splits, arsenals: three days
# Once the newest regular-season game is more than this many days old the season is over and the newest
# standings snapshot is the last one there will ever be.
STANDINGS_SEASON_ACTIVE_DAYS = 4

# ---------------------------------------------------------------------------
# Hour-based limits for the forward-capture stores
# ---------------------------------------------------------------------------
# Odds: capture slots are 13 minutes apart in slate hours and 60 minutes apart in quiet hours, so three
# hours is missing at least two quiet-hour slots (the limit scripts/prod_watch.py holds, for the same reason).
ODDS_FRESH_HOURS = 1.5
ODDS_STALE_HOURS = 3.0
# Watches poll every slot and write a marker even when nothing changed.
WATCH_FRESH_HOURS = 3.0
WATCH_STALE_HOURS = 6.0                     # lineups / probables on a game day
TRANSACTIONS_FRESH_HOURS = 24.0
TRANSACTIONS_STALE_HOURS = 72.0             # three days
# Prop prices are captured per game day (pitcher strikeouts T-slots, batter props once a day at ~04:10 UTC).
# 24h is the promise; six hours of slack covers the first slot of a late-starting slate.
PROP_FRESH_HOURS = 24.0
PROP_STALE_HOURS = 30.0
F5_FRESH_HOURS = 24.0
F5_STALE_HOURS = 36.0

# A process older than this has not been redeployed in that long. Production redeploys the working branch
# hourly when CI is green, so three hours is two missed redeploys.
DEPLOY_STALE_HOURS = 3.0

# The MLB window in which a daily-moving store is expected to move at all (month, day), inclusive.
SEASON_START = (3, 15)
SEASON_END = (11, 8)

GAME_MAP_FILE = ("processed", "event_game_map.jsonl")
GAME_MAP_TAIL_BYTES = 256 * 1024
GAME_MAP_CURRENT_HOURS = 36.0

ACTIONS_URL = "https://github.com/breydenerrett-cmd/aisportsanalysis/actions"

STATES = ("fresh", "aging", "stale", "problem", "not_expected")


@dataclass(frozen=True)
class Expectation:
    key: str
    title: str          # card title
    noun: str           # "Prop prices" -> "Prop prices are 12 days old"
    plural: bool        # "are" or "is"
    group: str          # "odds" | "forward" | "pages"
    when: str           # "season" | "game_day"
    fresh_hours: float
    stale_hours: float
    cause: str          # one sentence: what writes this store and how it goes quiet
    fix: str            # one line: what to do


_CAPTURE_FIX = (f"open the latest forward-capture run ({ACTIONS_URL}/workflows/forward-capture.yml) and read the "
                "section named for this store; if the chain died, dispatch forward-capture once.")

EXPECTATIONS: dict = {e.key: e for e in (
    Expectation("odds_multibook", "Odds, multi-book", "Odds", True, "odds", "season",
                ODDS_FRESH_HOURS, ODDS_STALE_HOURS,
                "The capture slot (scripts/capture_slot.sh, dense pass) writes it every 13 to 60 minutes.",
                _CAPTURE_FIX),
    Expectation("odds_snapshots", "Odds snapshots", "Odds snapshots", True, "forward", "season",
                ODDS_FRESH_HOURS, ODDS_STALE_HOURS,
                "The capture slot's dense pass writes it with the multi-book odds.", _CAPTURE_FIX),
    Expectation("f5_close", "First-five closing lines", "First-five closing lines", True, "forward", "game_day",
                F5_FRESH_HOURS, F5_STALE_HOURS,
                "The dense pass records a first-five close near each first pitch.", _CAPTURE_FIX),
    Expectation("prop_prices", "Pitcher prop prices", "Pitcher prop prices", True, "forward", "game_day",
                PROP_FRESH_HOURS, PROP_STALE_HOURS,
                "The capture slot's extras pass (PROP_PRICES=1, src/pipeline/prop_prices.py) writes it in "
                "slots before first pitch; it skips itself on 'credit floor' or 'probe reserve'.",
                _CAPTURE_FIX),
    Expectation("batter_props", "Batter prop prices", "Batter prop prices", True, "forward", "game_day",
                PROP_FRESH_HOURS, PROP_STALE_HOURS,
                "The capture slot's extras pass (BATTER_PROPS=1, src/pipeline/batter_props.py) writes it "
                "once a day for the day's slate; it skips itself on 'credit floor' or an empty slate.",
                _CAPTURE_FIX),
    Expectation("prop_listing", "Prop listing audit", "The prop listing audit", False, "forward", "game_day",
                PROP_FRESH_HOURS, PROP_STALE_HOURS,
                "src/pipeline/prop_listing.py samples three games a day until it spends its credit cap.",
                _CAPTURE_FIX),
    Expectation("probables_watch", "Probable pitchers", "Probable-pitcher polls", True, "forward", "game_day",
                WATCH_FRESH_HOURS, WATCH_STALE_HOURS,
                "The capture slot's watch pass (python -m src.cli watch) polls it every slot.", _CAPTURE_FIX),
    Expectation("lineups_watch", "Lineups", "Lineup polls", True, "forward", "game_day",
                WATCH_FRESH_HOURS, WATCH_STALE_HOURS,
                "The capture slot's watch pass (python -m src.cli watch) polls it every slot.", _CAPTURE_FIX),
    Expectation("transactions_watch", "Transactions", "Transaction polls", True, "forward", "season",
                TRANSACTIONS_FRESH_HOURS, TRANSACTIONS_STALE_HOURS,
                "The capture slot's watch pass (python -m src.cli watch) polls it every slot.", _CAPTURE_FIX),
)}

# Names the admin page and the pages group already use for the day-count stores.
PAGE_STORE_TITLES = {
    "mlb_results": ("Match results", "Match results", True),
    "pitcher_logs": ("Pitcher logs", "Pitcher logs", True),
    "bullpen_log": ("Bullpen log", "The bullpen log", False),
    "standings": ("Standings", "Standings", True),
    "lineups": ("Lineup history", "Lineup history", False),
    "matchup_history": ("Matchup history", "Matchup history", False),
    "pitcher_splits": ("Pitcher splits", "Pitcher splits", True),
    "transactions": ("Transactions (page copy)", "The transactions file", False),
    "arsenal_pitcher": ("Pitcher arsenals", "Pitcher arsenals", True),
    "arsenal_batter": ("Batter arsenals", "Batter arsenals", True),
    "handedness": ("Handedness", "Handedness", False),
}
PAGE_FIX = ("the data behind the pages is refreshed by the daily loop and the image build; open the latest "
            f"daily-loop run ({ACTIONS_URL}/workflows/daily-loop.yml) and the latest tests run, and redeploy "
            "once they are green.")


# ---------------------------------------------------------------------------
# The situation: season, game day, finished audits
# ---------------------------------------------------------------------------

def _utc(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def in_season(now) -> bool:
    moment = _utc(now)
    return SEASON_START <= (moment.month, moment.day) <= SEASON_END


def _parse(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _tail_rows(path: Path, max_bytes: int) -> list:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            chunk = handle.read()
    except OSError:
        return []
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]                       # the first line is cut mid-row
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def game_day(root, now) -> Optional[bool]:
    """True when the MLB schedule has a game on today's Eastern date, False on a confirmed off day, None when
    it cannot be known (the game map is missing or older than ``GAME_MAP_CURRENT_HOURS``)."""
    from src.pipeline import store_freshness
    moment = _utc(now)
    today = store_freshness.baseball_date(moment)
    rows = _tail_rows(Path(root).joinpath(*GAME_MAP_FILE), GAME_MAP_TAIL_BYTES)
    newest_resolved = None
    for row in rows:
        stamp = _parse(row.get("resolved_utc"))
        if stamp and (newest_resolved is None or stamp > newest_resolved):
            newest_resolved = stamp
        start = _parse(row.get("schedule_commence_time")) or _parse(row.get("commence_time"))
        if start and store_freshness.baseball_date(start) == today:
            return True
    if newest_resolved is None or (moment - newest_resolved) > timedelta(hours=GAME_MAP_CURRENT_HOURS):
        return None
    return False


# Cached on the file's own fingerprint, like apphealth's scan: /health is polled every 30 seconds.
_CAP_CACHE: dict = {}


def finished_audits(root) -> dict:
    """{store: {"since": ISO date, "reason": text}} for bounded audits that have spent their cap.

    The prop-listing audit was approved with a hard cap of 400 credits (docs/COLLECTION_POLICY.md,
    src/pipeline/prop_listing.HARD_CAP). It reached it on 2026-10-07 and is DONE BY DESIGN: it stopped on
    purpose, no one switched anything off, and no fix is wanted.
    """
    path = Path(root) / "processed" / "prop_listing.jsonl"
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    hit = _CAP_CACHE.get("prop_listing")
    if hit and hit[0] == key:
        return hit[1]
    out: dict = {}
    try:
        from src.pipeline import prop_listing
        spent, newest = 0, None
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if '"poll"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not row.get("poll"):
                    continue
                billed = row.get("credits_last")
                spent += 1 if billed is None else billed
                stamp = _parse(row.get("observed_utc"))
                if stamp and (newest is None or stamp > newest):
                    newest = stamp
        if spent >= prop_listing.HARD_CAP:
            since = newest.date().isoformat() if newest else "an earlier date"
            out["prop_listing"] = {
                "since": since,
                "reason": (f"Finished on {since}: this audit spent its {prop_listing.HARD_CAP}-credit cap "
                           f"({spent} used) as designed. It is not a stalled capture. Live prop prices are "
                           "in the pitcher and batter prop price stores."),
            }
    except Exception:  # noqa: BLE001 -- a health input must never raise
        out = {}
    _CAP_CACHE["prop_listing"] = (key, out)
    return out


def situation(root, now) -> dict:
    """Everything evaluate() needs to know about today that a store cannot say about itself."""
    moment = _utc(now)
    return {"in_season": in_season(moment), "game_day": game_day(root, moment),
            "finished": finished_audits(root)}


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

_TONE = {"fresh": "ok", "aging": "warn", "stale": "bad", "problem": "bad", "not_expected": "mute"}
_WORD = {"fresh": "Fresh", "aging": "Aging", "stale": "Stale", "problem": "Problem", "not_expected": "Not expected now"}


def human_age(hours: float) -> str:
    """'5 hours', '30 hours' under two days, then '12 days'."""
    if hours < 48:
        n = max(int(hours), 0)
        return f"{n} hour{'' if n == 1 else 's'}"
    n = int(hours // 24)
    return f"{n} days"


def _verdict(exp_key, title, group, state, **extra) -> dict:
    out = {"key": exp_key, "title": title, "group": group, "state": state, "tone": _TONE[state],
           "word": _WORD[state], "age_hours": None, "reason": None, "what": None, "fix": None,
           "noun": None, "plural": True, "alert": False, "since_utc": None, "through": None,
           "headline": None}
    out.update(extra)
    return out


def _not_expected_reason(exp: Expectation, sit: Mapping) -> Optional[str]:
    finished = (sit.get("finished") or {}).get(exp.key)
    if finished:
        return finished["reason"]
    if not sit.get("in_season", True):
        return "The MLB season is over; this store is not expected to move until it starts again."
    if exp.when == "game_day" and sit.get("game_day") is False:
        return "No MLB games today, so nothing is expected to be captured."
    return None


def _store_verdict(exp: Expectation, check: Mapping, sit: Mapping) -> dict:
    base = dict(noun=exp.noun, plural=exp.plural)
    status = check.get("status")
    age_s = check.get("newest_row_age_seconds")
    age_h = age_s / 3600.0 if isinstance(age_s, (int, float)) else None
    reason_off = _not_expected_reason(exp, sit)
    if reason_off:
        return _verdict(exp.key, exp.title, exp.group, "not_expected", reason=reason_off,
                        age_hours=age_h, **base)
    if status == "unreadable":
        return _verdict(exp.key, exp.title, exp.group, "problem", age_hours=age_h,
                        reason=check.get("reason") or "The store could not be read.",
                        headline=f"{exp.noun} cannot be read", what=f"{exp.noun} cannot be read.",
                        fix="read the reason on the Health tab; /health already lists it.", alert=False, **base)
    if status in ("missing", "empty", "archived_only") or check.get("present") is False:
        word = status if status in ("missing", "empty") else "missing"
        return _verdict(exp.key, exp.title, exp.group, "problem", age_hours=age_h,
                        reason=check.get("reason") or f"The store is {word}.",
                        headline=f"The {exp.title.lower()} store is {word}",
                        what=f"The {exp.title.lower()} store is {word}: nothing has been captured, or the volume "
                             "is not mounted. " + exp.cause,
                        fix=exp.fix, alert=True, **base)
    if age_h is None:
        return _verdict(exp.key, exp.title, exp.group, "problem", reason="No row carries a time to age.",
                        headline=f"{exp.noun} have no timestamp to age" if exp.plural else f"{exp.noun} has no timestamp to age",
                        what=f"{exp.noun} {'have' if exp.plural else 'has'} no timestamp to age. " + exp.cause,
                        fix=exp.fix, alert=True, **base)
    newest = check.get("newest_row_utc")
    crossed = _parse(newest)
    since = (crossed + timedelta(hours=exp.stale_hours)).isoformat() if crossed else None
    if age_h > exp.stale_hours:
        verb = "are" if exp.plural else "is"
        cap = datetime.fromisoformat(newest.replace("Z", "+00:00")).strftime("%b %d") if crossed else "an earlier date"
        return _verdict(exp.key, exp.title, exp.group, "stale", age_hours=age_h, since_utc=since,
                        headline=f"{exp.noun} {verb} {human_age(age_h)} old",
                        reason=f"Newest row is {human_age(age_h)} old; the limit is {human_age(exp.stale_hours)}.",
                        what=f"{exp.noun} {verb} {human_age(age_h)} old (last written {cap}, limit "
                             f"{human_age(exp.stale_hours)}). {exp.cause}",
                        fix=exp.fix, alert=True, **base)
    if age_h > exp.fresh_hours:
        return _verdict(exp.key, exp.title, exp.group, "aging", age_hours=age_h, since_utc=since,
                        reason=f"Newest row is {human_age(age_h)} old; stale past {human_age(exp.stale_hours)}.",
                        **base)
    return _verdict(exp.key, exp.title, exp.group, "fresh", age_hours=age_h,
                    reason=f"Newest row is {human_age(age_h)} old.", **base)


def _page_verdict(name: str, entry: Mapping, sit: Mapping) -> dict:
    title, noun, plural = PAGE_STORE_TITLES.get(name, (name.replace("_", " ").title(), name.replace("_", " "), True))
    base = dict(noun=noun, plural=plural, through=entry.get("through"))
    lag = entry.get("lag_days")
    tolerance = entry.get("tolerance_days")
    if entry.get("stale"):
        verb = "are" if plural else "is"
        late = (f"{lag} day{'' if lag == 1 else 's'} behind" if isinstance(lag, int)
                else "missing or unreadable")
        return _verdict(f"fresh_{name}", title, "pages", "stale", lag_days=lag,
                        headline=f"{noun} {verb} {late}",
                        reason=entry.get("reason") or "Past its tolerance.",
                        what=f"{noun} {verb} {late}. {entry.get('reason') or ''}".strip(),
                        fix=PAGE_FIX, alert=True,
                        since_utc=None, **base)
    if entry.get("expected_through") and not entry.get("stale"):
        return _verdict(f"fresh_{name}", title, "pages", "not_expected", lag_days=lag,
                        reason=(f"The regular season is over; the last snapshot ({entry.get('through')}) is the "
                                "last there will be until next season."), **base)
    if name == "handedness" or entry.get("through") is None:
        return _verdict(f"fresh_{name}", title, "pages", "fresh", lag_days=lag,
                        reason=entry.get("reason") or "No dates to age.", **base)
    within = (f"{lag} day{'' if lag == 1 else 's'} behind, within its {tolerance}-day tolerance"
              if isinstance(lag, int) and lag > 0 and tolerance is not None else "Current")
    return _verdict(f"fresh_{name}", title, "pages", "fresh", lag_days=lag, reason=within, **base)


def evaluate(health: Mapping, sit: Optional[Mapping] = None) -> list:
    """One verdict per tracked store, from a ``apphealth.report()`` payload and the situation."""
    sit = dict(sit or {})
    sit.setdefault("in_season", True)
    sit.setdefault("game_day", True)
    sit.setdefault("finished", {})
    out = []
    stores = dict((health.get("odds") or {}))
    stores.update(health.get("forward_captures") or {})
    for key, exp in EXPECTATIONS.items():
        if key in stores:
            out.append(_store_verdict(exp, stores[key], sit))
    pages = health.get("data_freshness") or {}
    if not pages.get("error"):
        for name, entry in (pages.get("stores") or {}).items():
            out.append(_page_verdict(name, entry, sit))
    return out


def summarize(health: Mapping, sit: Optional[Mapping] = None) -> dict:
    """The ``freshness`` block of the health payload: the situation, every verdict, and the ones that need
    the owner (state stale or problem)."""
    sit = dict(sit or {})
    verdicts = evaluate(health, sit)
    return {"situation": {k: sit.get(k) for k in ("in_season", "game_day", "finished")},
            "stores": verdicts,
            "attention": [v for v in verdicts if v["state"] in ("stale", "problem")]}


def thresholds_snapshot() -> dict:
    """Every number this module owns, for the 'no one has a private threshold' test."""
    return {e.key: (e.fresh_hours, e.stale_hours, e.when) for e in EXPECTATIONS.values()}
