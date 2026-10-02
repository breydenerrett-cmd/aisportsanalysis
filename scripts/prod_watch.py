"""One look at production, and a line only for what is wrong.

WHY THIS EXISTS
---------------
After the 2026-10-01 memory incident production was watched by hand, a
`/health` read every few minutes for hours. That is not a way to run a
business. This reads the same things once, compares them with fixed
thresholds and with what it saw last time, and says OK or names the breach.
It changes nothing anywhere: two GETs to the public site and `gh run list`.

    python scripts/prod_watch.py            # human-readable; exit 1 on a breach
    python scripts/prod_watch.py --quiet    # print only breaches

WHAT IS A BREACH (the thresholds; change them here, in one place)
-----------------------------------------------------------------
- `/health` does not answer 200 with status ok.
- The process restarted since the last look and no `deploy-prod` run finished
  around its start time (a deploy restarts it on purpose; anything else is a
  crash).
- Peak memory above PEAK_RSS_LIMIT_MB, or more than one cache build at once
  (the 2026-10-01 failure).
- The newest odds row on the site is older than ODDS_STALE_HOURS.
- A protected page answers anything but 401 to a visitor with no token.
- Billing is anything but off (until the go-live checklist turns it on, at
  which point set EXPECT_CHECKOUT below).
- The newest finished `tests` run is not green, no capture slot has succeeded
  for CAPTURE_GAP_MINUTES, or the newest daily loop failed.

State is one small JSON file under data/logs/ (git-ignored), so "restarted
since last look" has something to compare with.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://linehound-prod.fly.dev"
REPO = "breydenerrett-cmd/aisportsanalysis"
BRANCH = "claude/sports-betting-analysis-review-g1o0co"
STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "prod_watch_state.json"

PEAK_RSS_LIMIT_MB = 850.0          # the machine has 1,024
ODDS_STALE_HOURS = 3.0
CAPTURE_GAP_MINUTES = 150          # quiet-hours slots are 60 minutes apart
DEPLOY_MATCH_MINUTES = 10
EXPECT_CHECKOUT = "off"


def _get(path, timeout=30):
    """(status, parsed JSON or None). Status None when the host did not answer."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as response:
            body = response.read()
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError):
        return None, None


def _runs(workflow, limit=6):
    """Newest runs of one workflow, newest first; [] when gh cannot answer."""
    try:
        done = subprocess.run(
            ["gh", "run", "list", "--repo", REPO, "--workflow", workflow, "--limit", str(limit),
             "--json", "status,conclusion,createdAt,updatedAt,headBranch"],
            capture_output=True, text=True, timeout=60)
        return json.loads(done.stdout) if done.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def _when(stamp):
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate(health_status, health, card_status, runs, previous, now):
    """Pure: the observations in, (lines, breaches, new_state) out.

    `runs` maps workflow file name -> list of run dicts (newest first)."""
    lines, breaches = [], []

    def check(ok, text):
        lines.append(("OK     " if ok else "BREACH ") + text)
        if not ok:
            breaches.append(text)

    health = health or {}
    check(health_status == 200 and health.get("status") == "ok",
          f"/health: HTTP {health_status}, status {health.get('status')!r}")

    runtime = health.get("runtime") or {}
    started = runtime.get("started_utc")
    state = {"started_utc": started, "restarts_seen": int((previous or {}).get("restarts_seen", 0)),
             "checked_utc": now.isoformat()}
    if started and previous and previous.get("started_utc") and previous["started_utc"] != started:
        started_at = _when(started)
        deploys = [_when(r.get("updatedAt")) for r in runs.get("deploy-prod.yml", [])
                   if r.get("conclusion") == "success"]
        by_deploy = bool(started_at) and any(
            d and abs((d - started_at).total_seconds()) <= DEPLOY_MATCH_MINUTES * 60 for d in deploys)
        if not by_deploy:
            state["restarts_seen"] += 1
        check(by_deploy, f"process restarted at {started} "
                         f"({'by a deploy' if by_deploy else 'NO deploy finished near that time'})")
    else:
        check(True, f"same process since {started} (up {runtime.get('uptime_s')} s)")

    peak = runtime.get("peak_rss_mb")
    check(isinstance(peak, (int, float)) and peak <= PEAK_RSS_LIMIT_MB,
          f"memory: peak {peak} MB, now {runtime.get('rss_mb')} MB (limit {PEAK_RSS_LIMIT_MB:.0f})")
    most = (runtime.get("builds") or {}).get("max_running")
    check(most is not None and most <= 1, f"cache builds at once: {most}")

    age = ((health.get("odds") or {}).get("odds_multibook") or {}).get("newest_row_age_seconds")
    check(isinstance(age, (int, float)) and age <= ODDS_STALE_HOURS * 3600,
          f"newest odds on the site: {age / 3600:.1f} h old" if isinstance(age, (int, float))
          else "newest odds on the site: unknown")

    check(card_status == 401, f"/card with no token: HTTP {card_status} (must be 401)")
    checkout = (health.get("checkout") or {}).get("status")
    check(checkout == EXPECT_CHECKOUT, f"billing: {checkout!r} (expected {EXPECT_CHECKOUT!r})")

    finished = [r for r in runs.get("tests.yml", []) if r.get("status") == "completed"]
    check(bool(finished) and finished[0].get("conclusion") == "success",
          f"CI: newest finished run {finished[0].get('conclusion') if finished else 'not found'}")

    good = [_when(r.get("updatedAt")) for r in runs.get("forward-capture.yml", [])
            if r.get("conclusion") == "success"]
    good = [g for g in good if g]
    gap = (now - max(good)).total_seconds() / 60 if good else None
    check(gap is not None and gap <= CAPTURE_GAP_MINUTES,
          f"capture: last successful slot {gap:.0f} min ago" if gap is not None
          else "capture: no successful slot found")

    daily = [r for r in runs.get("daily-loop.yml", []) if r.get("status") == "completed"]
    check(bool(daily) and daily[0].get("conclusion") == "success",
          f"daily loop: newest finished run {daily[0].get('conclusion') if daily else 'not found'}")

    state["breaches"] = breaches
    return lines, breaches, state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quiet", action="store_true", help="print only breaches")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        previous = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    health_status, health = _get("/health")
    card_status, _ = _get("/card")
    runs = {name: _runs(name) for name in
            ("deploy-prod.yml", "tests.yml", "forward-capture.yml", "daily-loop.yml")}
    lines, breaches, state = evaluate(health_status, health, card_status, runs, previous, now)

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")

    print(f"production watch {now.strftime('%Y-%m-%d %H:%MZ')}: "
          f"{'ALL OK' if not breaches else str(len(breaches)) + ' BREACH(ES)'}; "
          f"unexplained restarts seen so far: {state['restarts_seen']}")
    for line in lines:
        if not args.quiet or line.startswith("BREACH"):
            print("  " + line)
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
