"""When we learn something, does the market move after us -- and by how long?

THE QUESTION, AND WHY IT IS NOT THE ONE THIS REPO KEEPS ASKING
---------------------------------------------------------------
Every measurement here so far has compared OUR NUMBER to THE MARKET'S NUMBER
-- the prop head-to-head, the disagreement scans, the card's own filter --
and all of them came back at or below the market
(`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`).

That is a question about modelling. It is not the only way a price is beaten,
and the owner named the other one:

    "being a master of knowledge... knowing if someone posted online that
     they saw Connor McGregor walking to a medical clinic a week or two
     before the fight... but the video didn't come out viral until after,
     like there's real value there."

That is an INFORMATION edge: not a better estimate of the same facts, but
the same estimate made earlier, before the price reflects a fact that
already exists. A null result on the first question says nothing about the
second, and this repo has never tested the second.

It can. `data/processed/information_events.jsonl` records 1,221 events --
lineups posted and changed, probable pitchers changed, roster transactions,
weather shifts, umpire assignments -- each stamped with `observed_utc`, the
instant WE saw it, and every one graded "A" for timing precision. The
multi-book store carries prices with their own timestamps. So the two halves
needed to answer it are already on disk.

WHAT IS MEASURED
----------------
For every event attached to a game whose board we were capturing:

  1. The de-vigged home probability at the last quote BEFORE we saw it.
  2. The same at each quote after, out to `HORIZON_MINUTES`.
  3. How far the price travelled, and when.

And the only thing that makes those numbers mean anything:

  THE CONTROL, AND IT HAD TO BE BUILT TWICE.

  Prices drift all day; a board that moves two points after a lineup posts
  has told you nothing if it also moves two points after nothing at all. So
  the comparison is event-anchored movement against baseline drift over an
  identical horizon.

  The first version drew control anchors at random instants on the same
  games, keeping clear of real events. It produced +0.62 points with an
  interval nowhere near zero, and it was wrong:

      hours before first pitch     event anchors  median  2.9h
                                   control anchors median 22.2h

  Events cluster near first pitch -- lineups post two to four hours out,
  scratches land late -- and the clearance rule pushed the control into the
  dead hours the day before. That measured busy-time against quiet-time and
  called it news against no-news.

  The control is now MATCHED ON LEAD TIME: for an event N hours before its
  game, control anchors are drawn from other games at the same N (within
  `LEAD_MATCH_TOLERANCE_HOURS`), still clear of any event. Same part of the
  day, same market conditions, one has news and one does not.

WHAT IT CANNOT SAY
------------------
Whether the move is in a direction we could have predicted. Knowing the
price will MOVE is not knowing WHICH WAY -- and only the second is bettable.
This probe measures whether a window exists at all; a direction test is a
separate and harder question, and is not attempted here.

Read-only. Adopts nothing.

Usage:
    python scripts/probe_information_edge.py [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import odds as odds_math  # noqa: E402
from src.pipeline import snapshots  # noqa: E402

EVENTS = os.path.join("data", "processed", "information_events.jsonl")

# How far past an event to follow the price. Long enough that a book that
# reacts slowly is still counted, short enough that the whole day's drift is
# not attributed to one event.
HORIZON_MINUTES = 120

# A board needs this many two-way books at an instant before its consensus is
# a market rather than one shop's opinion. Same floor and same reason as
# scripts/_propboard.py's MIN_BOOKS.
MIN_BOOKS = 3

# Control anchors must sit this far from any real event, or the "baseline"
# is quietly measuring the events again.
CONTROL_CLEARANCE_MINUTES = 180

# How close in TIME-TO-FIRST-PITCH a control anchor must sit to the event it
# stands in for. A board three hours from first pitch behaves nothing like
# the same board twenty-two hours out, and the first version of this probe
# compared exactly those two things -- see the module docstring.
LEAD_MATCH_TOLERANCE_HOURS = 1.0

BOOTSTRAP_SEED = 20260911


def _parse(stamp):
    if not stamp:
        return None
    try:
        out = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _read_events():
    rows = []
    if not os.path.exists(EVENTS):
        return rows
    with open(EVENTS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            when = _parse(row.get("observed_utc"))
            game = row.get("game_pk")
            if when is None or not game:
                continue
            rows.append({"kind": row.get("event_kind"), "game_pk": str(game),
                         "at": when})
    return rows


def _boards_by_game():
    """{game_pk-ish key: [(instant, fair_home_probability)]}, oldest first.

    Keyed by EVENT ID from the odds feed, then mapped to game_pk through the
    event map, because the two stores name games differently -- the odds feed
    has its own event ids and the information ledger carries MLB game_pks.
    """
    quotes = defaultdict(lambda: defaultdict(dict))
    for row in snapshots.iter_multibook():
        if not snapshots.is_full_game_moneyline(row):
            continue
        if not snapshots.is_pregame(row):
            continue
        at = _parse(row.get("observed_utc"))
        event_id = row.get("event_id")
        if at is None or not event_id:
            continue
        quotes[event_id][at][row.get("book")] = (row.get("away_price"),
                                                 row.get("home_price"))

    boards = {}
    for event_id, by_instant in quotes.items():
        series = []
        for at in sorted(by_instant):
            fair = []
            for away, home in by_instant[at].values():
                if away is None or home is None:
                    continue
                try:
                    total = (odds_math.american_to_probability(away)
                             + odds_math.american_to_probability(home))
                    if total < 0.98:
                        continue
                    _fa, fh = odds_math.devig_two_way(away, home)
                except (odds_math.OddsError, TypeError, ValueError,
                        ZeroDivisionError):
                    continue
                fair.append(fh)
            if len(fair) >= MIN_BOOKS:
                series.append((at, statistics.fmean(fair)))
        if len(series) >= 3:
            boards[event_id] = series
    return boards


def _event_to_game_map():
    """odds-feed event_id -> MLB game_pk, from the capture's own map."""
    path = os.path.join("data", "processed", "event_game_map.jsonl")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            event_id, game_pk = row.get("event_id"), row.get("game_pk")
            if event_id and game_pk:
                out[event_id] = str(game_pk)
    return out


def _first_pitch_by_game():
    """{game_pk: first pitch}, from the results store."""
    import csv
    path = os.path.join("data", "historical", "mlb_results.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            when = _parse(row.get("start_time_utc"))
            if when and row.get("game_pk"):
                out[str(row["game_pk"])] = when
    return out


def _travel(series, anchor, horizon_minutes=HORIZON_MINUTES):
    """How far the consensus moved after `anchor`, and how long it took.

    Returns (points_moved, minutes_to_peak) or None when the anchor has no
    price on both sides of it.
    """
    before = [(at, p) for at, p in series if at <= anchor]
    after = [(at, p) for at, p in series
             if anchor < at <= anchor + timedelta(minutes=horizon_minutes)]
    if not before or not after:
        return None
    base = before[-1][1]
    peak_at, peak_move = None, 0.0
    for at, p in after:
        move = abs(p - base)
        if move > peak_move:
            peak_move, peak_at = move, at
    if peak_at is None:
        return (0.0, None)
    return (peak_move * 100, (peak_at - anchor).total_seconds() / 60)


def _summary(values):
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    var = statistics.fmean((v - mean) ** 2 for v in values)
    se = math.sqrt(var / len(values))
    return {"n": len(values), "mean": mean, "se": se,
            "median": statistics.median(values),
            "ci95": [mean - 1.96 * se, mean + 1.96 * se]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    events = _read_events()
    if not events:
        print("no information events stored", file=sys.stderr)
        return 1
    boards = _boards_by_game()
    mapping = _event_to_game_map()
    by_game = defaultdict(list)
    for event_id, series in boards.items():
        game_pk = mapping.get(event_id)
        if game_pk:
            by_game[game_pk] = series

    matched = defaultdict(list)
    unmatched = 0
    event_times = defaultdict(list)
    for ev in events:
        series = by_game.get(ev["game_pk"])
        if not series:
            unmatched += 1
            continue
        event_times[ev["game_pk"]].append(ev["at"])
        got = _travel(series, ev["at"])
        if got is not None:
            matched[ev["kind"]].append(got)

    # THE CONTROL, MATCHED ON LEAD TIME. See the module docstring for what
    # the unmatched version measured instead.
    first_pitch = _first_pitch_by_game()
    rng = random.Random(BOOTSTRAP_SEED)

    # Every usable control anchor, tagged with how far it sits from its own
    # first pitch, so an event can be matched against a like-for-like moment
    # on a different game.
    pool = []
    for game_pk, series in by_game.items():
        fp = first_pitch.get(game_pk)
        if fp is None:
            continue
        reals = event_times.get(game_pk) or []
        for at, _p in series:
            if any(abs((at - r).total_seconds()) / 60
                   <= CONTROL_CLEARANCE_MINUTES for r in reals):
                continue
            pool.append((game_pk, at, (fp - at).total_seconds() / 3600))
    rng.shuffle(pool)

    control = []
    control_leads = []
    event_leads = []
    used = set()
    for ev in events:
        series = by_game.get(ev["game_pk"])
        fp = first_pitch.get(ev["game_pk"])
        if not series or fp is None or _travel(series, ev["at"]) is None:
            continue
        lead = (fp - ev["at"]).total_seconds() / 3600
        event_leads.append(lead)
        for i, (game_pk, at, cand_lead) in enumerate(pool):
            if i in used or game_pk == ev["game_pk"]:
                continue
            if abs(cand_lead - lead) > LEAD_MATCH_TOLERANCE_HOURS:
                continue
            got = _travel(by_game[game_pk], at)
            if got is None:
                continue
            used.add(i)
            control.append(got)
            control_leads.append(cand_lead)
            break

    all_events = [v for rows in matched.values() for v in rows]
    report = {
        "events_stored": len(events),
        "events_matched_to_a_board": sum(len(v) for v in matched.values()),
        "events_with_no_board": unmatched,
        "games_with_a_board": len(by_game),
        "horizon_minutes": HORIZON_MINUTES,
        "event_move_points": _summary([m for m, _t in all_events]),
        "control_move_points": _summary([m for m, _t in control]),
        "minutes_to_peak": _summary([t for _m, t in all_events
                                     if t is not None]),
        "by_kind": {k: _summary([m for m, _t in v])
                    for k, v in sorted(matched.items())},
        # THE CHECK THAT CAUGHT THE FIRST VERSION. Printed every run so a
        # reader can see for themselves that the two arms are being measured
        # at the same distance from first pitch.
        "lead_hours_event": _summary(event_leads),
        "lead_hours_control": _summary(control_leads),
    }

    if args.json:
        print(json.dumps(report, indent=2, default=float))
        return 0

    print("DOES THE MARKET MOVE AFTER WE LEARN SOMETHING?")
    print()
    print(f"  {report['events_stored']} information events stored")
    print(f"  {report['events_matched_to_a_board']} landed on a game whose "
          f"board we were capturing")
    print(f"  {report['events_with_no_board']} had no board to measure against")
    print(f"  horizon: {HORIZON_MINUTES} minutes after the event")
    print()
    ev, ct = report["event_move_points"], report["control_move_points"]
    if not ev or not ct:
        print("  not enough matched events or control anchors to compare.")
        print("  That is the finding: the two stores do not overlap enough")
        print("  yet to answer this, and saying so beats a number built on")
        print("  a handful of rows.")
        return 0
    le, lc = report["lead_hours_event"], report["lead_hours_control"]
    if le and lc:
        print("  ARE THE TWO ARMS COMPARABLE? Hours before first pitch --")
        print("  the check that caught this probe's first version, where the")
        print("  control sat 19 hours further from the game than the events.")
        print(f"    events  median {le['median']:.1f}h      "
              f"control median {lc['median']:.1f}h")
        if abs(le["median"] - lc["median"]) > LEAD_MATCH_TOLERANCE_HOURS:
            print("    -> STILL NOT MATCHED. Read nothing below this line.")
        else:
            print("    -> matched; both arms sit at the same point in the day.")
        print()
    print("  HOW FAR THE CONSENSUS TRAVELLED, in points of win probability")
    print(f"    after an event    n={ev['n']:<5} mean {ev['mean']:.2f}   "
          f"median {ev['median']:.2f}   95% [{ev['ci95'][0]:.2f}, "
          f"{ev['ci95'][1]:.2f}]")
    print(f"    after nothing     n={ct['n']:<5} mean {ct['mean']:.2f}   "
          f"median {ct['median']:.2f}   95% [{ct['ci95'][0]:.2f}, "
          f"{ct['ci95'][1]:.2f}]")
    print()
    gap = ev["mean"] - ct["mean"]
    se = math.sqrt(ev["se"] ** 2 + ct["se"] ** 2)
    print(f"    difference {gap:+.2f} points   95% [{gap - 1.96 * se:+.2f}, "
          f"{gap + 1.96 * se:+.2f}]")
    print()
    if gap - 1.96 * se > 0:
        print("    The interval excludes zero: boards move further after we")
        print("    learn something than they do at a random moment. That is a")
        print("    WINDOW, not an edge -- see below.")
    else:
        print("    The interval spans zero. On this data, a board does not")
        print("    move measurably further after an event than after nothing.")
    print()
    peak = report["minutes_to_peak"]
    if peak:
        print(f"  HOW LONG UNTIL IT MOVES   median {peak['median']:.0f} min, "
              f"mean {peak['mean']:.0f} min (n={peak['n']})")
        print("    This is the size of the window a reader would have had.")
    print()
    print("  BY EVENT KIND")
    for kind, s in report["by_kind"].items():
        if s:
            print(f"    {str(kind):<26} n={s['n']:<5} mean {s['mean']:.2f} pts")
    print()
    print("  WHAT THIS CANNOT SAY: which WAY the price moved. Knowing a board")
    print("  will move is not knowing its direction, and only the second is")
    print("  bettable. This measures whether a window exists at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
