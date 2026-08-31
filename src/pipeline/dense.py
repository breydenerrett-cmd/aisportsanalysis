"""Dense snapshot capture inside the window where prices actually move.

WHY
---
Research Family V2 lost two hypotheses to sampling resolution rather than to
evidence. M1 asked whether prices overreact and give some back; M2 asked
whether the price at first pitch is really sharper than the price ninety
minutes earlier. Both are answerable questions in the literature and neither
could be asked here, because our history holds four or five snapshots per game
spread across a whole day. Only 197 games in two seasons carried both a
90-240 minute quote and a sub-hour one, and three of those were the weekend
afternoons M2 is specifically about.

The fix is not cleverness, it is sampling. A quote every fifteen minutes across
the hours before first pitch makes both questions answerable within a season,
and line movement is the one thing that cannot be bought retroactively at any
price.

WHY IT IS NOT SIMPLY "SNAPSHOT MORE OFTEN"
-------------------------------------------
Credits are finite and most of the day has no game about to start. This module
captures only when at least one game begins inside the active window, so an
overnight hour costs nothing. The scheduler can therefore fire every hour
without thinking, and the spend follows the schedule of actual baseball.

COST, STATED PLAINLY
--------------------
Three markets in one region is 3 credits per capture. Four captures an hour
across an eleven-hour slate is 132 credits a day. That is the number this was
approved on and `estimate_daily_credits` recomputes it from the live
configuration rather than trusting this comment.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from src.pipeline import snapshots
from src.providers import mlb
from src.providers import odds as odds_provider

# How long before first pitch the dense window opens. Three hours covers the
# span M1 and M2 both need, and starts after lineups are typically posted.
WINDOW_MINUTES = 180

# Spacing between captures within one scheduled run.
INTERVAL_MINUTES = 15

# Captures per scheduled run. Four at fifteen minutes covers one hour, so an
# hourly schedule tiles the day with no gaps and no overlap.
CAPTURES_PER_RUN = 4

# Refuse to start a run that would take the balance below this. A dense
# schedule is worth stopping before it eats the reserve that pays for
# everything else.
CREDIT_FLOOR = 5000

# The close-capture pass: if a game starts within this many minutes when the
# 4x15 loop has finished, one more capture is taken. The observation nearest
# first pitch is the closing line, the single most valuable row in the store,
# and a loop whose cadence happened to straddle first pitch was silently
# skipping it.
CLOSE_WINDOW_MINUTES = 25

# A game that reaches first pitch with no capture anywhere in this many final
# minutes has no defensible closing observation, and the run reports it as a
# missed window rather than letting the gap pass silently.
MISSED_WINDOW_MINUTES = 30


class DenseCaptureError(RuntimeError):
    """Raised when a dense run cannot proceed safely."""


def estimate_daily_credits(env=None, hours_of_baseball=11) -> dict:
    """What a full day of dense capture costs, from the live configuration."""
    per_call = odds_provider.estimate_credits(env=env)["credits_per_call"]
    per_hour = per_call * CAPTURES_PER_RUN
    return {
        "credits_per_call": per_call,
        "captures_per_hour": CAPTURES_PER_RUN,
        "credits_per_hour": per_hour,
        "hours_of_baseball": hours_of_baseball,
        "credits_per_day": per_hour * hours_of_baseball,
        "credits_per_month": per_hour * hours_of_baseball * 30,
    }


def games_in_window(rows, now=None, window_minutes=WINDOW_MINUTES) -> int:
    """How many games start inside the dense window right now.

    Counts games whose first pitch is still ahead but no further off than the
    window. A game already under way is excluded: its price is in-play, which
    is a different product and not what any of this measures.
    """
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=window_minutes)
    count = 0
    for row in rows or []:
        start = _parse(row.get("commence_time"))
        if start is None:
            continue
        if now < start <= horizon:
            count += 1
    return count


def _parse(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _upcoming(now=None, timeout=20):
    """Today's and tomorrow's first pitches, from the FREE schedule endpoint.

    Deliberately not the odds API. Asking the market "is a game coming up" costs
    the same three credits as the snapshot itself, which would silently double
    the price of every capture -- the gate would cost as much as the thing it
    was gating. MLB publishes the schedule for nothing, and start times are
    exactly what the window needs.

    Two dates because a late-evening slate runs past midnight UTC, so today's
    games and tomorrow's calendar date overlap.
    """
    now = now or datetime.now(timezone.utc)
    rows = []
    for offset in (0, 1):
        day = (now + timedelta(days=offset)).date().isoformat()
        try:
            for game in mlb.fetch_schedule(day, timeout=timeout):
                rows.append({"commence_time": _start_of(game)})
        except Exception:  # noqa: BLE001 -- a schedule outage must not spend credits
            return None
    return rows


def _start_of(game):
    return (game.get("gameDate") or (game.get("gameData") or {})
            .get("datetime", {}).get("dateTime"))


def run(env=None, captures=CAPTURES_PER_RUN, interval_minutes=INTERVAL_MINUTES,
        window_minutes=WINDOW_MINUTES, credit_floor=CREDIT_FLOOR,
        now=None, sleep=time.sleep, poll_hook=None) -> dict:
    """Take a spaced series of captures, but only while a game is approaching.

    The window is re-checked before every capture rather than once at the top.
    A run that starts with a game forty minutes out will stop on its own once
    that game begins, instead of spending the rest of its budget on in-play
    prices nobody asked for.
    """
    status = odds_provider.status(env)
    if not status.get("configured"):
        return {"captures": 0, "skipped": "not configured",
                "message": status.get("message")}

    # The floor is checked BEFORE spending anything. The sports endpoint is not
    # metered, so this costs nothing -- which is the only ordering under which a
    # floor actually holds. Reading the balance from a metered response would
    # mean discovering you are broke by going broke.
    try:
        remaining = odds_provider.quota(env).get("remaining")
    except odds_provider.OddsProviderError as exc:
        return {"captures": 0, "skipped": "quota unreadable", "message": str(exc)}
    if remaining is not None and remaining <= credit_floor:
        return {"captures": 0, "skipped": "credit floor",
                "credits_remaining": remaining, "floor": credit_floor}

    clock = _clock(now)
    run_start = clock()
    capture_moments = []

    results = []
    reason = None
    for index in range(captures):
        moment = clock()
        events = _upcoming(moment)
        if events is None:
            reason = "schedule unreachable"
            break
        approaching = games_in_window(events, moment, window_minutes)
        if approaching == 0:
            reason = "no game inside the window"
            break

        captured = snapshots.capture(env=env)
        capture_moments.append(moment)
        # Piggyback the caller's poll hook (cmd_dense passes
        # rosterwatch.poll) on every capture moment: the free MLB endpoints
        # cost nothing, and polling here tightens the V3 event brackets to
        # the dense spacing exactly when games are approaching -- which is
        # when lineups post and scratches happen. A poll failure never
        # blocks the capture that pays for this run.
        if poll_hook is not None:
            try:
                poll_hook()
            except Exception:  # noqa: BLE001 -- capture outlives the poll
                pass
        results.append({
            "at": moment.isoformat().replace("+00:00", "Z"),
            "games_in_window": approaching,
            "captured": captured.get("captured", 0),
            "events": captured.get("events", 0),
            "error": captured.get("error"),
        })
        if index < captures - 1 and sleep:
            sleep(interval_minutes * 60)

    # Close-capture pass: one more spend when a game is inside its final
    # minutes, even though the spaced loop is done. The floor is re-checked
    # first -- the check is free, so "before every spend" stays literally true.
    close_capture = None
    run_end = clock()
    events_now = _upcoming(run_end)
    if events_now is not None and games_in_window(
            events_now, run_end, CLOSE_WINDOW_MINUTES) > 0:
        try:
            remaining_now = odds_provider.quota(env).get("remaining")
        except odds_provider.OddsProviderError as exc:
            close_capture = {"skipped": "quota unreadable", "message": str(exc)}
            remaining_now = None
        else:
            if remaining_now is not None and remaining_now <= credit_floor:
                close_capture = {"skipped": "credit floor",
                                 "credits_remaining": remaining_now}
            else:
                captured = snapshots.capture(env=env)
                capture_moments.append(run_end)
                close_capture = {
                    "at": run_end.isoformat().replace("+00:00", "Z"),
                    "captured": captured.get("captured", 0),
                    "events": captured.get("events", 0),
                    "error": captured.get("error"),
                }
                results.append(dict(close_capture, close_pass=True,
                                    games_in_window=games_in_window(
                                        events_now, run_end,
                                        CLOSE_WINDOW_MINUTES)))

    missed = _missed_windows(events_now, run_start, run_end, capture_moments)

    return {
        "captures": len(results),
        "observations": sum(r["captured"] for r in results),
        "credits_remaining_before": remaining,
        "stopped_early": reason if reason else None,
        "close_capture": close_capture,
        "missed_windows": missed,
        "detail": results,
    }


def _clock(now):
    """Wall clock by default; a fixed instant or a callable for tests."""
    if callable(now):
        return now
    if now is not None:
        return lambda: now
    return lambda: datetime.now(timezone.utc)


def _missed_windows(events, run_start, run_end, capture_moments):
    """Games that reached first pitch during this run with no capture in
    their final MISSED_WINDOW_MINUTES. Reported, never repaired -- the price
    is gone and the honest output is the gap itself.

    A capture from an EARLIER run can legitimately cover the window, so the
    snapshot store's own timestamps count alongside this run's captures.
    """
    if not events or run_end <= run_start:
        return []
    started = []
    for row in events:
        start = _parse(row.get("commence_time"))
        if start is not None and run_start < start <= run_end:
            started.append(start)
    if not started:
        return []

    stamps = list(capture_moments)
    for row in snapshots.read():
        parsed = _parse(row.get("observed_utc"))
        if parsed is not None:
            stamps.append(parsed)

    missed = []
    for start in sorted(started):
        window_open = start - timedelta(minutes=MISSED_WINDOW_MINUTES)
        if not any(window_open <= stamp <= start for stamp in stamps):
            missed.append({
                "commence_time": start.isoformat().replace("+00:00", "Z"),
                "reason": (f"reached first pitch with no capture in its "
                           f"last {MISSED_WINDOW_MINUTES} minutes"),
            })
    return missed
