"""Show how ONE postseason matchup is priced when its starters are confirmed,
projected, and not usable.

    python scripts/postseason_starter_demo.py --away NYY --home TB

WHY THIS EXISTS. The postseason page (`src/report/postseason_page.py`) obeys
one rule: stale pitcher data may not silently remain a numerical input to a
customer-facing forecast. Every starter slot of every unplayed game is
classified CONFIRMED_CURRENT / PROJECTED_CURRENT / STALE_REFERENCE_ONLY /
UNAVAILABLE and the starters enter the game's chance only when both sides are
CONFIRMED_CURRENT. This script runs that one game through the real builder
three times so the behaviour can be read side by side:

  (a) both starters confirmed (named by the schedule) with current numbers,
  (b) starters projected, not announced, with current numbers,
  (c) no usable current starter (named, but the numbers on file are stale).

WHAT IS REAL. The results store and its top-up from the schedule feed, the
standings, the schedule's announced starters, the pitcher logs on disk, the
pitcher game logs fetched live from the MLB feed (the same fetch the page
route makes), and every line of the builder: nothing here prices a game
itself. WHAT IS FORCED. Where a block needs a condition the real world is not
currently providing (an announcement the schedule has not made, or one it
has, or a feed lookup that is withheld), the block's header says so in words
and what was changed. No pitcher number is ever invented: a forced pitcher is
a real one from the team's real rotation pool, priced from his real log.

Read-only: nothing is written; the only requests are GETs to statsapi.mlb.com.
"""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import matchup_model as mm  # noqa: E402
from src.report import postseason_page as page  # noqa: E402


def _name_for(store, pid):
    """A pitcher's name from the results store, or None."""
    for row in store.values():
        for side in ("home", "away"):
            if str(row.get(f"{side}_probable_id")) == str(pid) and row.get(f"{side}_probable"):
                return row[f"{side}_probable"]
    return None


def _target(probables, away, home):
    """The earliest pending postseason game between the two clubs, as the
    schedule lists it (that is the series' next game)."""
    games = [g for g in probables if g.get("away_team") == away and g.get("home_team") == home]
    games.sort(key=lambda g: (str(g.get("date") or ""), str(g.get("start_time_utc") or "")))
    return games[0] if games else None


def _with_game(probables, target, **fields):
    """A copy of the schedule with `fields` set on the one target game."""
    out = []
    for g in probables:
        out.append(dict(g, **fields) if g is target else g)
    return out


def _find_game(payload, away, home, number=None):
    for s in payload.get("series", []):
        if {t["team"] for t in s["teams"]} != {away, home}:
            continue
        for g in s["games"]:
            if g.get("status") in ("next", "future") and g["away"] == away \
                    and g["home"] == home and (number is None or g["number"] == number):
                return s, g
    return None, None


def _top_rotation_pitcher_with_log(store, team, today, fetcher):
    """The pitcher the rotation projection puts first for `team` (then the
    rest of the real rotation pool) who has a real same-season log in the feed,
    or None."""
    pool = mm.build_rotation_pool(store, team, page._iso_plus(today, 1))
    if not pool:
        return None
    first = mm.project_team_rotation(pool, {}, 1)[0][0]
    for pid in [first] + [p for p in pool if p != first]:
        rows = fetcher(pid)
        if rows and any(str(r.get("date") or "").startswith(today[:4]) for r in rows):
            return pid
    return None


def _pct(p):
    return f"{p * 100:.1f}%"


def _print_block(letter, title, forced, payload, away, home, number):
    series, game = _find_game(payload, away, home, number)
    print(f"\n({letter}) {title}")
    print(f"    {'(condition forced for the demonstration: ' + forced + ')' if forced else '(no condition forced: this is what the real inputs give)'}")
    if game is None:
        print("    this game is not on the page in this block")
        return
    print(f"    game {game['number']} of {series['id']}: {away} at {home}")
    for side, club in (("away", away), ("home", home)):
        slot = game["starters"][side]
        print(f"    {side:<4} {club:<4} input_class = {slot['input_class']:<20} "
              f"starter slot shows: {slot['display']}"
              + (f"  [{slot['note']}]" if slot.get("note") else ""))
    print(f"    game starter_input_class = {game['starter_input_class']}")
    print(f"    line under the game      = {game['starter_text']}")
    print(f"    primary chance           = {home} {_pct(game['home_chance'])}, "
          f"{away} {_pct(game['away_chance'])}")
    if game["scenarios"]:
        for scn in game["scenarios"]:
            print(f"    scenario (not the estimate) = {scn['label']}: "
                  f"{home} {_pct(scn['home_chance'])}, {away} {_pct(scn['away_chance'])}")
    else:
        print("    scenario                 = none")
    print(f"    inputs                   = {game['inputs_used_text']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--away", required=True, help="away club abbreviation, e.g. NYY")
    parser.add_argument("--home", required=True, help="home club abbreviation, e.g. TB")
    args = parser.parse_args(argv)
    away, home = args.away.upper(), args.home.upper()

    try:
        from api import postseason as route
    except ImportError as exc:  # the route's own top-up and fetcher are reused
        print(f"cannot import the route ({exc}); install the app requirements", file=sys.stderr)
        return 2
    from src.pipeline import history
    from src.pipeline import pitchers as pitchers_store
    from src.pipeline import standings as standings_store
    from src.providers import mlb

    now = datetime.now(timezone.utc)
    store, through = route._topup_results(history.read_results(), history.read_manifest(), now)
    standings = route._topup_standings(standings_store.read(), now)
    probables = page.upcoming_games(now, mlb.fetch_games, route.SCHEDULE_DAYS_AHEAD)
    stored_logs = pitchers_store.read_logs()
    through_stored = page._inputs_through(stored_logs, [])["pitcher_logs"]
    today = page.baseball_date(now)

    target = _target(probables, away, home)
    if target is None:
        print(f"No pending postseason game {away} at {home} is on the schedule feed "
              f"(baseball date {today}); nothing to show.")
        return 1

    def run(probs, fetcher):
        return page.build(now, results_store=store, standings=standings, probables=probs,
                          results_through=through, fresh_pitcher_logs=fetcher,
                          pitcher_logs=copy.deepcopy(stored_logs))

    print(f"POSTSEASON STARTER DEMO  {away} at {home}  ({today}, built {now:%H:%M}Z)")
    print("=" * 78)
    print("REAL in every block: the results store topped up from the feed exactly as the "
          f"route does (through {through}),")
    print("  the standings, the schedule feed, the stored pitcher logs on disk "
          f"(newest row {through_stored}),")
    print("  pitcher game logs fetched live from the MLB feed, and the page builder itself.")
    print("FORCED: only what a block's header says. No number is invented: a forced "
          "pitcher is a real")
    print("  member of the team's real rotation pool, priced from his real log.")
    print(f"What the schedule really says about this game ({target.get('date')}): "
          f"{away} starter = {target.get('away_probable') or 'not announced'}, "
          f"{home} starter = {target.get('home_probable') or 'not announced'}.")

    # The real page first: it fixes which game this is and what is announced.
    baseline = run(probables, route._fresh_fetcher(now))
    if not baseline.get("available"):
        print(f"\nThe page is not available right now: {baseline.get('reason')}")
        return 1
    series, real_game = _find_game(baseline, away, home)
    if real_game is None:
        print(f"\n{away} and {home} are not in a series with games left to play.")
        return 1
    number = real_game["number"]

    # ---- (a) both confirmed ------------------------------------------------
    forced_a, fields = [], {}
    fetcher_a = route._fresh_fetcher(now)
    for side, club in (("away", away), ("home", home)):
        if target.get(f"{side}_probable_id"):
            continue
        chosen = _top_rotation_pitcher_with_log(store, club, today, fetcher_a)
        if chosen is not None:
            name = _name_for(store, chosen) or f"Pitcher {chosen}"
            fields.update({f"{side}_probable_id": chosen, f"{side}_probable": name})
            forced_a.append(f"the schedule has not announced {club}'s starter, so the top of "
                            f"the real {club} rotation pool was named: {name} ({chosen})")
    payload_a = run(_with_game(probables, target, **fields), route._fresh_fetcher(now))
    _print_block("a", "BOTH STARTERS CONFIRMED, CURRENT NUMBERS",
                 "; ".join(forced_a), payload_a, away, home, number)

    # ---- (b) projected, not announced ---------------------------------------
    stripped = _with_game(probables, target, away_probable_id=None, away_probable=None,
                          home_probable_id=None, home_probable=None)
    payload_b = run(stripped, route._fresh_fetcher(now))
    announced = [n for n in (target.get("away_probable"), target.get("home_probable")) if n]
    _print_block("b", "STARTERS PROJECTED, NOT ANNOUNCED, CURRENT NUMBERS",
                 (f"the schedule's real announcement ({', '.join(announced)}) was removed so "
                  "the game has no named starter" if announced else ""),
                 payload_b, away, home, number)

    # ---- (c) no usable current starter ---------------------------------------
    payload_c = run(probables, None)
    _print_block("c", "NO USABLE CURRENT STARTER",
                 "the feed lookup for fresh pitcher logs was withheld, so only the stored "
                 f"pitcher numbers (newest row {through_stored}, {page._days_behind(through_stored, through)} "
                 "days behind the results) exist", payload_c, away, home, number)

    print("\n" + "-" * 78)
    print("The only block whose primary chance carries starting pitchers is (a); (b) and (c) "
          "are priced exactly like a game with no starters named, and (b)'s what-if line "
          "never changes a series number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
