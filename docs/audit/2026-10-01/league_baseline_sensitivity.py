"""How much does the stale league pitching baseline move a postseason number?

The matchup model turns a starter's raw FIP into runs with a league constant
(`pitchers.league_fip_constant`), computed from every stored pitcher log before
the game. When the store is behind, that constant is behind too, even for a
starter whose own log was fetched fresh. This prices every game that uses
starters three ways:

  A  the stored (stale) league constant, as the page does today
  B  a current constant derived from the official 2026 league pitching totals
     (MLB Stats API team season totals: earned runs, innings, HR, BB, K)
  C  starters left out of the game

Read-only: no store is written. Run from the repo root:
    python docs/audit/2026-10-01/league_baseline_sensitivity.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())

from api import postseason as route                      # noqa: E402
from src.pipeline import history, pitchers               # noqa: E402
from src.pipeline import standings as standings_store    # noqa: E402
from src.providers import mlb                            # noqa: E402
from src.report import postseason_page                   # noqa: E402


def innings(text) -> float:
    whole, _, outs = str(text).partition(".")
    return int(whole) + (int(outs or 0) / 3.0)


def current_constant() -> tuple:
    url = ("https://statsapi.mlb.com/api/v1/teams/stats?season=2026&sportIds=1"
           "&group=pitching&stats=season&gameType=R")
    data = json.load(urllib.request.urlopen(url, timeout=30))
    ip = er = hr = bb = k = 0.0
    teams = 0
    for split in data["stats"][0]["splits"]:
        stat = split["stat"]
        teams += 1
        ip += innings(stat["inningsPitched"])
        er += stat["earnedRuns"]
        hr += stat["homeRuns"]
        bb += stat["baseOnBalls"]
        k += stat["strikeOuts"]
    era = er * 9.0 / ip
    raw = ((13.0 * hr) + (3.0 * bb) - (2.0 * k)) / ip
    return round(era - raw, 4), teams, round(ip, 1), round(era, 3)


def build(now, fetcher):
    store, through = route._topup_results(history.read_results(), history.read_manifest(), now)
    return postseason_page.build(
        now, results_store=store,
        standings=route._topup_standings(standings_store.read(), now),
        probables=postseason_page.upcoming_games(now, mlb.fetch_games, route.SCHEDULE_DAYS_AHEAD),
        results_through=through, fresh_pitcher_logs=fetcher)


def games_with_starters(payload):
    for series in payload.get("series", []):
        for game in series.get("games", []):
            if game.get("starter_input_class") == "CONFIRMED_CURRENT":
                yield series["id"], game


def main() -> int:
    now = datetime.now(timezone.utc)
    stored = pitchers.league_fip_constant(pitchers.read_logs(), now.date().isoformat())
    current, teams, ip, era = current_constant()
    print(f"built {now.strftime('%Y-%m-%d %H:%MZ')}")
    print(f"A  stored league constant : {stored}  (from the stored pitcher logs)")
    print(f"B  current league constant: {current}  ({teams} teams, {ip} IP, league ERA {era}, "
          "official 2026 regular-season totals)")
    print(f"   difference B - A       : {current - stored:+.4f} runs per nine")

    fetcher = route._fresh_fetcher(now)
    a = build(now, fetcher)
    real = pitchers.league_fip_constant
    pitchers.league_fip_constant = lambda logs, cutoff: current
    try:
        b = build(now, fetcher)
    finally:
        pitchers.league_fip_constant = real
    c = build(now, None)          # no fresh logs: every starter stale, none used

    by_b = {(sid, g["number"]): g for sid, g in games_with_starters(b)}
    by_c = {(s["id"], g["number"]): g for s in c.get("series", []) for g in s.get("games", [])}
    rows = 0
    for sid, game in games_with_starters(a):
        key = (sid, game["number"])
        gb, gc = by_b.get(key), by_c.get(key)
        if gb is None or gc is None:
            continue
        rows += 1
        pa, pb, pc = game["home_chance"], gb["home_chance"], gc["home_chance"]
        print(f"\n{sid} game {game['number']}: {game['away']} at {game['home']}")
        print(f"   A stale league constant   home {pa * 100:6.2f}%")
        print(f"   B current league constant home {pb * 100:6.2f}%   B - A = {(pb - pa) * 100:+.2f} points")
        print(f"   C starters left out       home {pc * 100:6.2f}%   A - C = {(pa - pc) * 100:+.2f} points")
    if not rows:
        print("\nno game on the page uses starters right now; nothing to compare")
    sa = {t["team"]: t["wins_world_series"] for t in a.get("teams", [])}
    sb = {t["team"]: t["wins_world_series"] for t in b.get("teams", [])}
    worst = max(sa, key=lambda t: abs(sb.get(t, 0) - sa[t])) if sa else None
    if worst:
        print(f"\nlargest World Series change from A to B: {worst} "
              f"{(sb[worst] - sa[worst]) * 100:+.3f} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
