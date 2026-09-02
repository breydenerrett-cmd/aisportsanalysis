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
from pathlib import Path

import json

from src.paths import processed_path
from src.pipeline import creditlog
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

# F5 close pass: the per-event first-five moneyline, priced once per game at
# the last capture moment before its first pitch.
#
# WHY IT RIDES EVERY CAPTURE MOMENT AND NOT JUST THE LAST ONE
# ------------------------------------------------------------
# It used to hang off the close pass alone, and that made it structurally
# blind. A run that finds any game inside the three-hour window always takes
# all four captures, so `run_end` is pinned to run_start + 45 minutes -- and
# when no game is inside three hours the loop breaks, but then nothing can be
# inside twenty-five minutes either, so the break path can never price
# anything. One instant per hour, therefore, and the T-25 window is a single
# 25-minute slice of each hour. The slate does not oblige: on the real
# 2026-09-01 card twelve of fifteen first pitches fall at :38-:45 past the
# hour, and replaying the true hourly cadence over it reached 3 of 15 games.
# No trigger phase does better than 6 of 15, because 25 minutes of coverage
# per 60 cannot.
#
# Riding every capture moment closes the gap: at each moment the pass prices
# the games that will have started before the NEXT moment, which is the last
# look this run gets at them, and the run's tail keeps the full T-25 reach so
# consecutive hourly runs tile with no hole. Each event is priced at most
# ONCE per run, so the spend is about one credit per game per night -- the
# bottom of the 15-40/day docs/COLLECTION_POLICY.md approved for this layer,
# which specifies exactly this: "piggybacked on dense capture moments".
F5_CLOSE_STORE = processed_path("f5_close.jsonl")
F5_CLOSE_MARKET = "h2h_1st_5_innings"

# Per RUN, not per moment. A doubleheader-heavy hour cannot multiply the
# spend, and a market that errors on every attempt cannot be retried into a
# budget hole -- an attempted event counts whether or not it returned prices.
#
# Raised 6 -> 8 on 2026-08-31 with Brey's explicit approval, because 6 was
# EXACTLY saturated on an ordinary card. MLB clusters its starts: 2026-09-01
# has four games at 22:40 and two at 22:45, all inside one run's span, so the
# 22:15 run spent 6 of 6 with zero headroom. A seventh simultaneous start was
# dropped permanently -- `seen` and `budget` are per-run and the next run
# begins after first pitch, so nothing recovers it, and an F5 close cannot be
# refetched at any price the next morning.
#
# This is a CEILING, not a spend. Measured nightly use is ~1 credit per game
# (15-16 on a 15-game card); the ceiling only binds when starts cluster. The
# theoretical worst case of 32/night stays inside the 15-40/day band that
# docs/COLLECTION_POLICY.md already approves for this layer, which is why the
# raise needed Brey's sign-off but not a new budget.
F5_CLOSE_MAX_EVENTS = 8

# The free MLB schedule and the odds feed disagree about first pitch by about
# a minute (MLB 22:40 against the odds feed's 22:41, every game, measured
# 2026-08-31). The schedule is only a free pre-filter here; the odds feed's
# own commence_time decides what actually gets priced. The slack stops a
# one-minute skew from closing the gate on a game the pass would have taken,
# and it is the same tolerance used to match a stored close back to a
# scheduled game.
F5_SCHEDULE_SLACK_MINUTES = 2

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

    Three dates, and YESTERDAY is the one that matters. MLB files a game under
    its Eastern date, so a 22:10 ET first pitch on the 30th is filed under the
    30th and starts at 02:10 UTC on the 31st. Asking only for the UTC date and
    the day after meant that from 00:00 UTC -- 8pm Eastern -- the entire
    still-to-start West Coast slate vanished from this function's view. The
    loop then stopped with "no game inside the window", the close pass never
    fired, and `_missed_windows` could not even report the gap, because the
    games it would have reported were not in `events` either. Every West Coast
    closing line, every night, silently. The schedule endpoint is free, so the
    extra call costs nothing but a request.
    """
    now = now or datetime.now(timezone.utc)
    rows = []
    for offset in (-1, 0, 1):
        day = (now + timedelta(days=offset)).date().isoformat()
        try:
            for game in mlb.fetch_schedule(day, timeout=timeout):
                rows.append(dict(_identity_of(game),
                                 commence_time=_start_of(game)))
        except Exception:  # noqa: BLE001 -- a schedule outage must not spend credits
            return None
    return rows


def any_game_scheduled(now=None, timeout=20):
    """Is MLB playing anywhere in the yesterday/today/tomorrow window?

    A FREE-schedule question, for callers that spend a paid credit only when
    a game is actually on the board (the daily snapshot). Reuses `_upcoming`
    so the same West-Coast/Eastern-date correctness lives in one place.

    Three-valued on purpose:
      True  -- the schedule was reachable and lists at least one game.
      False -- the schedule was reachable and lists ZERO games (the off-season
               / a true dead day). This is the only signal that justifies
               skipping a paid capture.
      None  -- the free schedule endpoint was unreachable. The caller must NOT
               skip on this: a schedule outage is not evidence the season is
               over, and line movement missed on a live day cannot be
               recovered. Unknown means spend, the safe direction.
    """
    events = _upcoming(now=now, timeout=timeout)
    if events is None:
        return None
    return len(events) > 0


def _start_of(game):
    return (game.get("gameDate") or (game.get("gameData") or {})
            .get("datetime", {}).get("dateTime"))


def _identity_of(game):
    """Who is playing, plus MLB's own game id, from a raw schedule record.

    WHY THE SCHEDULE ROWS CARRY IDENTITY AT ALL
    -------------------------------------------
    `_missed_f5_closes` used to decide whether a scheduled game had a stored
    close by comparing first-pitch times alone. On a normal MLB card that is
    not a key: the real 2026-09-01 slate has four games at 22:40 and two at
    22:45, so ONE stored row marked every game sharing its start time as
    covered and up to three genuinely lost closes were reported as none. The
    detector was blind to exactly the failure it exists to catch.

    `game_pk` is MLB's identifier and is carried for the operator's benefit;
    it is not the odds feed's event id, so it cannot join the two feeds. The
    team pair can: MLB's full club names and the odds feed's are the same
    strings ("New York Yankees"), and a pair of clubs is unique on a slate
    even when a doubleheader repeats a start time. If the two feeds ever
    disagree on a club's name the pair stops matching and the game is
    reported missed -- a false alarm, which is the safe direction for a
    detector whose whole purpose is to make silence impossible.
    """
    teams = game.get("teams") or {}
    def name(side):
        return ((teams.get(side) or {}).get("team") or {}).get("name")
    return {"game_pk": game.get("gamePk"),
            "home_team": name("home"), "away_team": name("away")}


def _team_key(home, away):
    """Case- and whitespace-insensitive identity for a scheduled matchup.

    None when either club is missing, which is the signal to fall back to
    first-pitch matching rather than to guess.
    """
    if not home or not away:
        return None
    return (str(home).strip().casefold(), str(away).strip().casefold())


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
        quota_now = odds_provider.quota(env)
    except odds_provider.OddsProviderError as exc:
        return {"captures": 0, "skipped": "quota unreadable", "message": str(exc)}
    remaining = quota_now.get("remaining")
    creditlog.log(remaining, quota_now.get("last"), "dense.run")
    if remaining is not None and remaining <= credit_floor:
        return {"captures": 0, "skipped": "credit floor",
                "credits_remaining": remaining, "floor": credit_floor}

    clock = _clock(now)
    run_start = clock()
    capture_moments = []

    # One F5 budget and one seen-set for the whole run, so the cap bounds the
    # run rather than each moment inside it.
    f5_state = {"seen": set(), "budget": F5_CLOSE_MAX_EVENTS,
                "events": 0, "rows": 0, "errors": [], "dropped": [],
                "budget_exhausted": False}

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
        row = {
            "at": moment.isoformat().replace("+00:00", "Z"),
            "games_in_window": approaching,
            "captured": captured.get("captured", 0),
            "events": captured.get("events", 0),
            "error": captured.get("error"),
        }
        # The last look this run gets at any game starting before the next
        # capture. On the final pass through the loop there is no next
        # capture, so the tail below widens the reach to the full T-25.
        f5 = _f5_moment(env, moment, interval_minutes, events, f5_state)
        if f5 is not None:
            row["f5"] = f5
        results.append(row)
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
            quota_close = odds_provider.quota(env)
        except odds_provider.OddsProviderError as exc:
            close_capture = {"skipped": "quota unreadable", "message": str(exc)}
            remaining_now = None
        else:
            remaining_now = quota_close.get("remaining")
            creditlog.log(remaining_now, quota_close.get("last"), "dense.close_capture")
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
                close_capture["f5"] = _f5_moment(
                    env, run_end, CLOSE_WINDOW_MINUTES, events_now,
                    f5_state) or {"events": 0, "rows": 0, "errors": [],
                                  "dropped": []}
                results.append(dict(close_capture, close_pass=True,
                                    games_in_window=games_in_window(
                                        events_now, run_end,
                                        CLOSE_WINDOW_MINUTES)))

    # Two gaps, reported separately because they are two different losses.
    # `missed_windows` is the h2h close; `missed_f5_closes` is the first-five
    # one, which is the entire evidence base of the market-depth lane and had
    # no reporting at all -- the pass could no-op every night and the run
    # still looked healthy.
    missed = _missed_windows(events_now, run_start, run_end, capture_moments)
    missed_f5 = _missed_f5_closes(events_now, run_start, run_end)

    return {
        "captures": len(results),
        "observations": sum(r["captured"] for r in results),
        "credits_remaining_before": remaining,
        "stopped_early": reason if reason else None,
        "close_capture": close_capture,
        "f5_closes": {"events": f5_state["events"], "rows": f5_state["rows"],
                      "errors": f5_state["errors"],
                      "dropped": f5_state["dropped"],
                      "budget": F5_CLOSE_MAX_EVENTS,
                      "budget_exhausted": f5_state["budget_exhausted"]},
        "missed_windows": missed,
        "missed_f5_closes": missed_f5,
        "detail": results,
    }


def _f5_moment(env, moment, lookahead_minutes, events, state):
    """Price the F5 close for games this run will not get another look at.

    Returns None when there is nothing to do, so a quiet moment adds no noise
    to the report and costs no request. The gate reads the FREE schedule
    already in hand; only games it flags reach the odds feed at all.
    """
    if state["budget"] <= 0:
        # Exhausted earlier in this run. Which games this costs is not known
        # here without another listing, but nothing is being priced from now
        # on, and `_missed_f5_closes` names every unpriced game at the end.
        state["budget_exhausted"] = True
        return None
    # Slack on BOTH edges. The far edge is obvious; the near edge is the one
    # that cost two games a night in the replay -- the schedule says 22:45 at
    # the moment the clock reads 22:45, so the game is not "ahead" by the free
    # feed's reckoning, while the odds feed still lists it at 22:46 with a
    # price to give.
    slack = timedelta(minutes=F5_SCHEDULE_SLACK_MINUTES)
    if events is not None and games_in_window(
            events, moment - slack,
            lookahead_minutes + 2 * F5_SCHEDULE_SLACK_MINUTES) == 0:
        return None
    report = _f5_close_pass(env, moment, lookahead_minutes=lookahead_minutes,
                            seen=state["seen"], budget=state["budget"])
    state["budget"] -= report["events"]
    state["events"] += report["events"]
    state["rows"] += report["rows"]
    state["errors"].extend(report["errors"])
    state["dropped"].extend(report.get("dropped") or [])
    if report.get("dropped"):
        state["budget_exhausted"] = True
    return report


def _f5_close_pass(env, moment, store=None, lookahead_minutes=None,
                   seen=None, budget=None) -> dict:
    """First-five moneyline for games inside the close window, per event.

    The events index is unmetered; each odds fetch bills one credit for the
    one market x one region it asks for, and the pass is capped so a
    doubleheader-heavy slate cannot silently multiply the spend. Every
    per-event failure is reported, never fatal -- the h2h close already in
    the store is the run's primary product.

    `lookahead_minutes` is how far ahead this moment is responsible for: the
    gap to the next capture inside the loop, the full T-25 at the run's tail.
    `seen` and `budget` are the run's shared state, so an event is paid for
    once per run and the cap bounds the run rather than each moment in it.
    """
    target = Path(store) if store else Path(F5_CLOSE_STORE)
    lookahead = (CLOSE_WINDOW_MINUTES if lookahead_minutes is None
                 else lookahead_minutes)
    cap = F5_CLOSE_MAX_EVENTS if budget is None else budget
    if cap <= 0:
        return {"events": 0, "rows": 0, "errors": [], "dropped": []}
    try:
        listed = odds_provider.list_events(env)
    except odds_provider.OddsProviderError as exc:
        return {"events": 0, "rows": 0, "errors": [str(exc)], "dropped": []}

    observed = moment.isoformat().replace("+00:00", "Z")
    horizon = moment + timedelta(minutes=lookahead)
    targets = []
    for event in listed or []:
        commence = _parse_iso(event.get("commence_time"))
        if commence is None or not (moment < commence <= horizon):
            continue
        if seen is not None and event.get("id") in seen:
            continue
        targets.append(event)
    # The cap binds SILENTLY unless the overflow is carried out. `seen` and
    # `budget` are per-run and the next run begins after first pitch, so a
    # game dropped here is never priced by anything -- the loss is permanent
    # and must be named, not truncated away. Measured spend on the real
    # 2026-09-01 card is 6, 5, 1, 3 per run, and the 22:15 run spends 6 of 6
    # with zero headroom, so a seventh start in one span is routine.
    targets.sort(key=lambda event: _parse_iso(event.get("commence_time"))
                 or horizon)
    dropped = [{"event_id": event.get("id"),
                "commence_time": event.get("commence_time"),
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "reason": (f"F5 close budget of {cap} bound at this capture "
                           f"moment; no later moment can reach this game")}
               for event in targets[cap:]]
    targets = targets[:cap]
    if seen is not None:
        # Marked on ATTEMPT, not on success. A market that is not listed
        # errors identically at every moment, and retrying it three more
        # times inside one run would spend the cap on a game that has no
        # first-five price to give.
        seen.update(event.get("id") for event in targets)

    rows, errors = [], []
    for event in targets:
        try:
            payload = odds_provider.fetch_event_odds(
                event.get("id"), markets=(F5_CLOSE_MARKET,), env=env)
        except odds_provider.OddsProviderError as exc:
            errors.append(f"{event.get('id')}: {exc}")
            continue
        for book in payload.get("bookmakers") or []:
            for market in book.get("markets") or []:
                if market.get("key") != F5_CLOSE_MARKET:
                    continue
                prices = {o.get("name"): o.get("price")
                          for o in market.get("outcomes") or []}
                home = prices.get(payload.get("home_team"))
                away = prices.get(payload.get("away_team"))
                if home is None or away is None:
                    continue
                rows.append({
                    "observed_utc": observed,
                    "event_id": payload.get("id"),
                    "commence_time": payload.get("commence_time"),
                    "home_team": payload.get("home_team"),
                    "away_team": payload.get("away_team"),
                    "market": F5_CLOSE_MARKET,
                    "book": book.get("key"),
                    "book_last_update": market.get("last_update"),
                    "home_price": home,
                    "away_price": away,
                })
    if rows:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            # A run killed mid-write leaves a fragment with no newline; without
            # this the next close pass would weld its first row onto that
            # fragment and lose a good capture along with the bad one.
            if snapshots._ends_ragged(target):
                handle.write("\n")
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {"events": len(targets), "rows": len(rows), "errors": errors,
            "dropped": dropped}


def _missed_f5_closes(events, run_start, run_end, store=None):
    """Games this run was the last look at, with no first-five close stored.

    The same contract as `_missed_windows` and for the same reason: reported,
    never repaired. This one exists because the F5 layer's failure mode is
    silence -- the pass no-ops, the run looks healthy, and the absence is only
    noticed when someone goes looking for a store that was never written. A
    night that produced no close now says so on the run that produced none.

    A close taken by an EARLIER run legitimately covers the window, so the
    store's own rows are what is checked, not just this run's spend. Rows are
    Rows are matched to scheduled games BY IDENTITY -- the pair of clubs,
    which both feeds name identically -- because first pitch is not a key on a
    real card. Four games start at 22:40 on 2026-09-01 and two at 22:45; under
    time-only matching one stored row silenced every game sharing its start,
    so three lost closes reported as zero. First pitch within
    F5_SCHEDULE_SLACK_MINUTES stays as the fallback for rows that genuinely
    carry no identity -- an older store written before the clubs were recorded,
    or a caller passing bare schedule times -- because the two feeds disagree
    about first pitch by about a minute.

    The span is every game this run was responsible for: from run_start out to
    the tail pass's own horizon, since a game inside that horizon has had its
    last look from this run. A later run can still reach the far end of it, so
    a line here can occasionally be answered by the next run rather than being
    permanent -- which is the right way round. A first-five close that goes
    missing quietly is how this store spent its first night empty while the
    lane believed it was accumulating.
    """
    if not events or run_end <= run_start:
        return []
    horizon = run_end + timedelta(minutes=CLOSE_WINDOW_MINUTES)
    started = []
    for row in events:
        start = _parse(row.get("commence_time"))
        if start is not None and run_start < start <= horizon:
            started.append((start, row))
    if not started:
        return []

    priced = _f5_priced(store)
    slack = timedelta(minutes=F5_SCHEDULE_SLACK_MINUTES)
    missed = []
    for start, row in sorted(started, key=lambda pair: pair[0]):
        window_open = start - timedelta(minutes=CLOSE_WINDOW_MINUTES)
        key = _team_key(row.get("home_team"), row.get("away_team"))
        covered = False
        for commence, observed, priced_key in priced:
            if not (window_open <= observed <= start):
                continue
            if key is not None and priced_key is not None:
                # Both sides know who is playing: identity decides, and a
                # shared start time proves nothing.
                if key == priced_key:
                    covered = True
                    break
                continue
            if abs(commence - start) <= slack:
                covered = True
                break
        if covered:
            continue
        entry = {
            "commence_time": start.isoformat().replace("+00:00", "Z"),
            "reason": (f"this run was its last look and no "
                       f"{F5_CLOSE_MARKET} price is stored inside its "
                       f"final {CLOSE_WINDOW_MINUTES} minutes"),
        }
        # Named when known, because on a card with four simultaneous starts a
        # bare timestamp does not tell the operator WHICH game was lost.
        for field in ("game_pk", "home_team", "away_team"):
            if row.get(field) is not None:
                entry[field] = row[field]
        missed.append(entry)
    return missed


def _f5_priced(store=None):
    """(first pitch, observation time, team key) per row in the F5 store.

    The team key is None for a row that does not name both clubs; callers fall
    back to first-pitch matching for those rather than treating an unknown
    matchup as a match.

    A store that does not exist yet is not an error -- it is the state this
    lane spent its first night in, and reading it must say "nothing priced"
    rather than raise on the run that would have priced something.
    """
    target = Path(store) if store else Path(F5_CLOSE_STORE)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return []
    priced = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:  # a fragment from a killed run, not evidence
            continue
        commence = _parse(row.get("commence_time"))
        observed = _parse(row.get("observed_utc"))
        if commence is not None and observed is not None:
            priced.append((commence, observed,
                           _team_key(row.get("home_team"),
                                     row.get("away_team"))))
    return priced


def _parse_iso(stamp):
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


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
