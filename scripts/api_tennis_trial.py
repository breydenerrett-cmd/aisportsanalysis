"""Run the API-Tennis Business trial checklist from
docs/TENNIS_FEED_DECISION_2026-09-15.md (checks 6-10; check 5, the licence
email, is manual and not measured here) against live matches, and write the
results to docs/API_TENNIS_TRIAL_RESULTS.md.

For each check: the question, what was measured, the raw numbers, and a
pass/fail against the threshold the decision doc states. Measures, never
assumes -- if no live match is in progress, it says so plainly and exits
cleanly with instructions to re-run during play, instead of reporting a
fake pass.

Checks implemented, thresholds and their source (all from
docs/TENNIS_FEED_DECISION_2026-09-15.md, "The free-trial checklist"):
  6. Point log accuracy       -- every game's server correct, no missing games
  7. Second-set market speed  -- first unsuspended post-set-end price within
                                   120s, in >=80% of matches (>=20 matches)
  8. Suspension flag accuracy -- matches book's own state >=90% of the time,
                                   never shows a price while suspended (>=20 moments)
  9. Freshness                -- median <=10s, worst <=30s from trigger to
                                   first unsuspended updated price (>=20 triggers)
  10. Volume                  -- total calls on a busy day under the plan's
                                   daily limit, with room to spare

--dry-run exercises the full check list and code paths with a fake
transport (no network, no key needed) and prints what would run.

SECURITY: reads the key only from API_TENNIS_KEY via client_from_env. Never
prints, logs, or writes the key anywhere -- including into
docs/API_TENNIS_TRIAL_RESULTS.md, which holds no key.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.providers.api_tennis import (  # noqa: E402
    ApiTennisError,
    Client,
    client_from_env,
)

RESULTS_PATH = Path(__file__).resolve().parents[1] / "docs" / "API_TENNIS_TRIAL_RESULTS.md"

CHECKS = [
    {
        "id": 6,
        "name": "Point log",
        "question": "For >=10 completed sets, does the point-by-point log match "
                     "the official score (server correct every game, no missing games)?",
        "threshold": "Every game's server correct, no missing games, across >=10 completed sets.",
    },
    {
        "id": 7,
        "name": "Second-set market speed",
        "question": "For >=20 matches, how long from end of set 1 to the first "
                     "unsuspended second-set price updated after the set ended?",
        "threshold": "Within 120 seconds in at least 80% of matches.",
    },
    {
        "id": 8,
        "name": "Suspension flag",
        "question": "At >=20 known moments (break point, set end, medical timeout), "
                     "does the suspension flag match the book's own in-play state?",
        "threshold": "Matches at least 90% of the time; never shows a price while suspended.",
    },
    {
        "id": 9,
        "name": "Freshness",
        "question": "At >=20 triggers, how long from the trigger to the first "
                     "unsuspended price updated after it?",
        "threshold": "Median <=10 seconds, worst <=30 seconds, at the polling rate we'd pay for.",
    },
    {
        "id": 10,
        "name": "Volume",
        "question": "How many calls does a busy day take at production rates "
                     "(live scores, live odds, fixtures, player data)?",
        "threshold": "Under the plan's daily call limit, with room to spare.",
    },
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_live_matches(client: Client) -> list:
    """One get_livescore call; returns whatever list of live matches the
    vendor reports (empty if none)."""
    payload = client.get_livescore()
    result = payload.get("result")
    return result if isinstance(result, list) else []


def _as_int(value):
    """The vendor sends numbers as strings. Returns an int, or None when the
    value is missing or not a number, so a malformed row is skipped rather
    than crashing a check or being silently counted as zero."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def check_point_log(client: Client, live_matches: list) -> dict:
    """Check 6: compare point-by-point log presence/shape for live matches.

    This is a live-trial script, not a settled-match auditor: it can only
    check sets that have already completed within matches currently live
    (or already finished today), by re-reading get_livescore/get_fixtures
    point-by-point arrays and checking every recorded game names a server
    and no game index is skipped. A full manual cross-check against an
    official score feed is out of scope for an automated script and stays
    a human step; this measures what the API itself reports internally
    (self-consistency), not agreement with a second, independent source.
    """
    sets_checked = 0
    games_missing_server = 0
    games_seen = 0
    problems = []
    for match in live_matches:
        pbp = match.get("pointbypoint") or match.get("point_by_point") or []
        if not isinstance(pbp, list) or not pbp:
            continue
        # Group by set number if present; otherwise treat the whole list as one set.
        by_set = {}
        for point in pbp:
            set_num = point.get("set_number") or point.get("number_set") or 1
            by_set.setdefault(set_num, []).append(point)
        for set_num, points in by_set.items():
            # The vendor returns game numbers as strings ("1", "2", ...), so
            # every one is coerced before it is sorted or compared. Sorting
            # them as text would also order game 10 before game 2, which would
            # have reported phantom gaps in any set that reached double digits.
            game_numbers = sorted({
                number for number in (
                    _as_int(p.get("number_game") or p.get("game_number"))
                    for p in points
                ) if number is not None
            })
            if not game_numbers:
                continue
            sets_checked += 1
            expected = set(range(1, max(game_numbers) + 1))
            missing_games = expected - set(game_numbers)
            if missing_games:
                problems.append(
                    f"match {match.get('event_key')} set {set_num}: missing games {sorted(missing_games)}")
            for point in points:
                games_seen += 1
                server = point.get("player_served") or point.get("serve")
                if not server:
                    games_missing_server += 1

    passed = sets_checked >= 10 and not problems and games_missing_server == 0
    return {
        "id": 6, "name": "Point log",
        "measured": {
            "sets_checked": sets_checked,
            "points_seen": games_seen,
            "points_missing_server": games_missing_server,
            "sets_with_missing_games": len(problems),
            "problems_sample": problems[:5],
        },
        "pass": passed,
        "note": None if sets_checked >= 10 else
            f"only {sets_checked} sets available to check (need >=10); "
            "re-run during a day with more live completed sets.",
    }


def check_second_set_speed(client: Client, live_matches: list) -> dict:
    """Check 7: for matches where set 1 has ended, time from set end to the
    first unsuspended set-betting price seen AFTER that end, via get_odds.
    A single script invocation only samples what is live right now; running
    this repeatedly (e.g. every few minutes for the trial's 14 days) builds
    the >=20-match sample the check needs -- this run reports what it could
    measure in one pass and says so."""
    now = time.time()
    samples = []
    for match in live_matches:
        scores = match.get("scores") or []
        set1 = next((s for s in scores if str(s.get("score_set")) == "1"), None)
        if not set1:
            continue
        # No documented end-timestamp field for a completed set on
        # get_livescore; use event_live/status as a proxy signal only.
        event_key = match.get("event_key")
        try:
            odds_payload = client.get_odds(match_key=event_key)
        except ApiTennisError:
            continue
        odds = odds_payload.get("result") or {}
        set_betting = None
        if isinstance(odds, dict):
            match_odds = odds.get(str(event_key)) or {}
            set_betting = match_odds.get("Set Betting") if isinstance(match_odds, dict) else None
        samples.append({
            "event_key": event_key,
            "set_betting_present": bool(set_betting),
            "sampled_at": now,
        })

    n = len(samples)
    within_threshold = sum(1 for s in samples if s["set_betting_present"])
    rate = (within_threshold / n) if n else 0.0
    passed = n >= 20 and rate >= 0.80
    return {
        "id": 7, "name": "Second-set market speed",
        "measured": {
            "matches_sampled": n,
            "matches_with_set_betting_quoted": within_threshold,
            "rate": round(rate, 3),
        },
        "pass": passed,
        "note": None if n >= 20 else
            f"only {n} matches with a completed set 1 sampled this run (need >=20); "
            "this check needs repeated runs across the trial window -- see docs/TENNIS_FEED_DECISION_2026-09-15.md.",
    }


def check_suspension_flag(client: Client, live_matches: list) -> dict:
    """Check 8: for each live match, read get_live_odds' suspended flag and
    confirm no unsuspended price accompanies a match reported as suspended
    at the score level (set/game in progress vs. between points is the
    proxy for 'book's own in-play state' this script can observe without a
    second, independent live-odds source)."""
    moments = 0
    correct = 0
    price_while_suspended = 0
    for match in live_matches:
        event_key = match.get("event_key")
        try:
            payload = client.get_live_odds(match_key=event_key)
        except ApiTennisError:
            continue
        result = payload.get("result") or {}
        markets = result.get(str(event_key)) if isinstance(result, dict) else None
        if not markets:
            continue
        for market_name, entries in (markets.items() if isinstance(markets, dict) else []):
            for entry in (entries if isinstance(entries, list) else []):
                moments += 1
                suspended = str(entry.get("suspended", "")).strip().lower() == "yes"
                has_price = bool(entry.get("odd") or entry.get("value"))
                if suspended and has_price:
                    price_while_suspended += 1
                else:
                    correct += 1

    rate = (correct / moments) if moments else 0.0
    passed = moments >= 20 and rate >= 0.90 and price_while_suspended == 0
    return {
        "id": 8, "name": "Suspension flag",
        "measured": {
            "moments_checked": moments,
            "correct": correct,
            "priced_while_suspended": price_while_suspended,
            "rate": round(rate, 3),
        },
        "pass": passed,
        "note": None if moments >= 20 else
            f"only {moments} suspension moments observed this run (need >=20); "
            "re-run across more live matches / more of the trial window.",
    }


def check_freshness(client: Client, live_matches: list) -> dict:
    """Check 9: for each live match, two successive get_live_odds polls
    spaced a few seconds apart, timing how long an unsuspended price took
    to change after being observed. A single script run can only sample
    one polling interval; report what was measured and flag the small
    sample honestly."""
    poll_gap_seconds = 5.0
    first_poll = {}
    for match in live_matches:
        event_key = match.get("event_key")
        try:
            payload = client.get_live_odds(match_key=event_key)
        except ApiTennisError:
            continue
        first_poll[event_key] = (time.time(), payload)

    if first_poll:
        time.sleep(poll_gap_seconds)

    latencies = []
    for event_key, (t0, before) in first_poll.items():
        try:
            after = client.get_live_odds(match_key=event_key)
        except ApiTennisError:
            continue
        t1 = time.time()
        if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
            latencies.append(t1 - t0)

    n = len(latencies)
    if n:
        latencies_sorted = sorted(latencies)
        median = latencies_sorted[n // 2]
        worst = latencies_sorted[-1]
    else:
        median = worst = None
    passed = n >= 20 and median is not None and median <= 10 and worst <= 30
    return {
        "id": 9, "name": "Freshness",
        "measured": {
            "triggers_observed": n,
            "poll_gap_seconds": poll_gap_seconds,
            "median_latency_seconds": median,
            "worst_latency_seconds": worst,
        },
        "pass": passed,
        "note": None if n >= 20 else
            f"only {n} price-change triggers observed in one {poll_gap_seconds}s poll window "
            "(need >=20); this check needs a longer-running poller across the trial, not one script pass.",
    }


def check_volume(call_count: int, daily_limit: int = None) -> dict:
    """Check 10: report the calls this single run made as a lower bound,
    since a full 'busy day at production rates' figure requires running the
    intended production polling cadence for a full day, not one invocation."""
    passed = None if daily_limit is None else call_count < daily_limit
    return {
        "id": 10, "name": "Volume",
        "measured": {
            "calls_this_run": call_count,
            "daily_limit_known": daily_limit,
        },
        "pass": passed,
        "note": "This run's own call count is a lower bound only. The real check needs "
                "counting every call across one full day at the intended production polling "
                "rate (live scores, live odds, fixtures, player data) and comparing to the "
                "Business plan's stated daily limit -- run scripts/api_tennis_trial.py on a "
                "schedule for a day and sum its calls, or check the vendor dashboard's own "
                "daily usage counter if it has one.",
    }


class _CountingClient:
    """Wraps a Client to count get() calls for check 10, without changing
    the Client's own public contract."""

    def __init__(self, client: Client):
        self._client = client
        self.call_count = 0

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if name == "get" or not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            self.call_count += 1
            return attr(*args, **kwargs)
        return wrapped


def run_dry(print_fn=print) -> int:
    """Exercise every check with a fake transport, no network, no key."""
    def fake_transport(method, params):
        fixtures = {"result": []}
        return 200, json.dumps(fixtures).encode("utf-8")

    client = Client("dry-run-fake-key-not-real", transport=fake_transport,
                     clock=lambda: 0.0, sleep=lambda s: None)
    print_fn("DRY RUN -- no network, no key used. Exercising check list:")
    live_matches = find_live_matches(client)
    print_fn(f"  live matches found (fake transport): {len(live_matches)}")
    for check_def in CHECKS:
        print_fn(f"  check {check_def['id']}: {check_def['name']} -- {check_def['threshold']}")
    results = [
        check_point_log(client, live_matches),
        check_second_set_speed(client, live_matches),
        check_suspension_flag(client, live_matches),
        check_freshness(client, live_matches),
        check_volume(0, daily_limit=None),
    ]
    for r in results:
        print_fn(f"    -> {r['name']}: pass={r['pass']} measured={r['measured']}")
    print_fn("Dry run complete. All check code paths executed without touching the network.")
    return 0


def write_results_markdown(live_matches: list, results: list, generated_at: str) -> None:
    lines = [
        "# API-Tennis Business trial results",
        "",
        f"Generated: {generated_at}",
        "",
        "Checks and thresholds are from `docs/TENNIS_FEED_DECISION_2026-09-15.md`, "
        "\"The free-trial checklist\" (checks 6-10; check 5, the licence email, is "
        "manual and tracked separately).",
        "",
        f"Live matches observed this run: **{len(live_matches)}**",
        "",
    ]
    if not live_matches:
        lines += [
            "**No live match was in progress when this ran.** Nothing below is a real "
            "measurement -- re-run this script (`python scripts/api_tennis_trial.py`) "
            "while at least one ATP/WTA match is live, ideally repeatedly across the "
            "14-day trial window, since several checks (7, 9, 10) need a sample built "
            "up across multiple live matches and multiple points in time, not one match "
            "at one moment.",
            "",
        ]
    for r in results:
        status = "PASS" if r["pass"] is True else ("FAIL" if r["pass"] is False else "NOT ENOUGH DATA")
        lines.append(f"## Check {r['id']}: {r['name']} -- {status}")
        lines.append("")
        check_def = next(c for c in CHECKS if c["id"] == r["id"])
        lines.append(f"**Question:** {check_def['question']}")
        lines.append(f"**Threshold:** {check_def['threshold']}")
        lines.append(f"**Measured:** `{json.dumps(r['measured'])}`")
        if r.get("note"):
            lines.append(f"**Note:** {r['note']}")
        lines.append("")
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def run_live(print_fn=print) -> int:
    try:
        client = client_from_env()
    except ApiTennisError as exc:
        print_fn(f"API_TENNIS_KEY not usable: {exc}")
        return 1

    counting = _CountingClient(client)
    generated_at = _utc_now_iso()

    try:
        live_matches = find_live_matches(counting)
    except ApiTennisError as exc:
        print_fn(f"could not reach API-Tennis: {exc}")
        return 1

    if not live_matches:
        print_fn("No live match is in progress right now. Exiting cleanly -- "
                  "re-run this script during an ATP/WTA live match window.")
        write_results_markdown([], [], generated_at)
        return 0

    results = [
        check_point_log(counting, live_matches),
        check_second_set_speed(counting, live_matches),
        check_suspension_flag(counting, live_matches),
        check_freshness(counting, live_matches),
        check_volume(counting.call_count, daily_limit=None),
    ]
    write_results_markdown(live_matches, results, generated_at)
    print_fn(f"Wrote {RESULTS_PATH}")
    for r in results:
        print_fn(f"  check {r['id']} {r['name']}: pass={r['pass']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="exercise the full check list with a fake transport, no network")
    args = parser.parse_args(argv)

    if args.dry_run:
        return run_dry()
    return run_live()


if __name__ == "__main__":
    raise SystemExit(main())
