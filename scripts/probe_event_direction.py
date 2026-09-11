"""After news lands, does the price move the way we could have called in advance?

Criterion pre-registered in `docs/PREREG_EVENT_DIRECTION.md`, committed before
this file was written. Signs, window, statistic, correction and decision rule
are fixed there and are not restated here as anything other than code.

WHY DIRECTION AND NOT MAGNITUDE
-------------------------------
`scripts/probe_information_edge.py` tried to measure how far a price travels
after news, against a control of quiet moments. The control could not be
built: in the hours before first pitch -- when lineups post and scratches
land -- a comparable moment with no news barely exists. The events ARE the
busy period.

Direction needs no such control. The null is not "no movement", it is 50/50
on which way, and every event supplies its own comparison. It is also the only
form of the question that is bettable: knowing a price will move is worth
nothing, knowing which way is the whole game.

THE POSITIVE CONTROL, AND WHY IT IS HERE
----------------------------------------
Five nulls are on the record in this repo and not one of them can distinguish
"there is no effect" from "the instrument cannot see". A measurement that can
only ever return `no` is not evidence of absence.

So one of the three primary hypotheses is an effect known to be real and
public to every book: warm air is thinner, the ball carries, rising forecast
temperature raises a total. It is NOT a claim of edge. Its job is to license
the reading of the other two -- if the instrument cannot find a known effect,
the nulls beside it are uninformative and this probe says so in those words.

Read-only. Adopts nothing.

Usage:
    python scripts/probe_event_direction.py [--json]
"""

from __future__ import annotations

import argparse
import csv
import json
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
EVENT_MAP = os.path.join("data", "processed", "event_game_map.jsonl")
RESULTS = os.path.join("data", "historical", "mlb_results.csv")

# Same window as the first probe, and fixed in the pre-registration.
HORIZON_MINUTES = 120

# A consensus needs this many books at an instant or it is one shop's opinion.
MIN_BOOKS = 3

# Bonferroni over the three primary hypotheses: 0.05 / 3.
PRIMARY_HYPOTHESES = 3
ALPHA = 0.05 / PRIMARY_HYPOTHESES

# Below this the hit rate is a curiosity, not a finding, however extreme.
MIN_EVENTS = 25

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260911


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def _parse(stamp):
    if not stamp:
        return None
    try:
        out = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _number(value):
    """float(value) or None. The stores round-trip through JSON and CSV, so a
    total arrives as the string "8.5" and a temperature as a float. Coerce,
    never isinstance."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_events(path=EVENTS):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
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
                         "at": when, "payload": row.get("payload") or {}})
    return rows


def _event_to_game_map(path=EVENT_MAP):
    """odds-feed event_id -> MLB game_pk, from the capture's own map."""
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


def _first_pitch(path=RESULTS):
    """{game_pk: first pitch}, from the results store."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            when = _parse(row.get("start_time_utc"))
            if when and row.get("game_pk"):
                out[str(row["game_pk"])] = when
    return out


def _game_sides(path=RESULTS):
    """{game_pk: (home_code, away_code)} so a transaction's team resolves to
    a side of the board. Codes in the results store and in the information
    ledger are the same vocabulary -- ATL, SD, CWS -- checked before use."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pk = row.get("game_pk")
            if pk and row.get("home_team") and row.get("away_team"):
                out[str(pk)] = (row["home_team"], row["away_team"])
    return out


# --------------------------------------------------------------------------
# Board series
# --------------------------------------------------------------------------

def _series_by_event_id(rows_iter, value_of):
    """{event_id: [(instant, consensus)]}, oldest first.

    `value_of` maps one book's row to its number, or None to skip it. A
    consensus is the mean across books at an instant, and exists only when
    `MIN_BOOKS` books quote it.
    """
    quotes = defaultdict(lambda: defaultdict(dict))
    for row in rows_iter:
        at = _parse(row.get("observed_utc"))
        event_id = row.get("event_id")
        if at is None or not event_id:
            continue
        value = value_of(row)
        if value is None:
            continue
        quotes[event_id][at][row.get("book")] = value

    series = {}
    for event_id, by_instant in quotes.items():
        points = []
        for at in sorted(by_instant):
            values = list(by_instant[at].values())
            if len(values) >= MIN_BOOKS:
                points.append((at, statistics.fmean(values)))
        if len(points) >= 3:
            series[event_id] = points
    return series


def _home_probability(row):
    """One book's two-way de-vigged home probability, or None."""
    away, home = row.get("away_price"), row.get("home_price")
    if away is None or home is None:
        return None
    try:
        booksum = (odds_math.american_to_probability(away)
                   + odds_math.american_to_probability(home))
        if booksum < 0.98:
            return None
        _fair_away, fair_home = odds_math.devig_two_way(away, home)
    except (odds_math.OddsError, TypeError, ValueError, ZeroDivisionError):
        return None
    return fair_home


def _moneyline_series():
    def rows():
        for row in snapshots.iter_multibook():
            if not snapshots.is_full_game_moneyline(row):
                continue
            if not snapshots.is_pregame(row):
                continue
            yield row
    return _series_by_event_id(rows(), _home_probability)


def _total_series():
    """Consensus POSTED TOTAL, not a price.

    The number is what weather moves and what a reader can check. Prices at
    a fixed line move first and finer, but they are only comparable across
    books that posted the same line, and reconciling different lines needs a
    model of the run distribution -- which would put this probe's own
    modelling assumptions inside a measurement about the market.
    """
    def rows():
        for row in snapshots.iter_multibook():
            if row.get("market") != "totals":
                continue
            if not snapshots.is_pregame(row):
                continue
            yield row
    return _series_by_event_id(rows(), lambda r: _number(r.get("total")))


def _by_game(series, mapping):
    out = {}
    for event_id, points in series.items():
        game_pk = mapping.get(event_id)
        if game_pk:
            out[game_pk] = points
    return out


# --------------------------------------------------------------------------
# The statistic
# --------------------------------------------------------------------------

def _net(series, start, end):
    """Signed change in the consensus from `start` to `end`.

    Base is the last quote at or before `start`; final is the last quote in
    `(start, end]`. Net, not peak: picking the extreme of a noisy path is a
    free parameter, and the pre-registration forbids it.
    """
    base = None
    final = None
    for at, value in series:
        if at <= start:
            base = value
        elif at <= end:
            final = value
        else:
            break
    if base is None or final is None:
        return None
    return final - base


def _observations(events, series_by_game, sign_of, window=HORIZON_MINUTES):
    """[{game_pk, after, before, expected}] for events this rule can sign.

    `sign_of(event)` returns +1, -1, or None when the event carries no
    directional claim -- an unsignable event is dropped here rather than
    assigned a direction it does not have.

    The second return value is a census of WHERE EVERY SIGNABLE EVENT WENT.
    An earlier version of this probe counted drops and discarded the count,
    so a hypothesis could print `n=10` off 107 candidates with no indication
    that 90% had fallen out or why. A sample this heavily filtered is a
    statement about the capture, not about the market, and the reader has to
    be able to see that without instrumenting the probe themselves.
    """
    out = []
    census = {"signable": 0, "no board for that game": 0,
              "event precedes the board": 0, "event follows the board": 0,
              "no quote inside the window": 0, "usable": 0}
    span = timedelta(minutes=window)
    for ev in events:
        expected = sign_of(ev)
        if expected is None:
            continue
        census["signable"] += 1
        series = series_by_game.get(ev["game_pk"])
        if not series:
            census["no board for that game"] += 1
            continue
        anchor = ev["at"]
        after = _net(series, anchor, anchor + span)
        if after is None:
            if anchor < series[0][0]:
                census["event precedes the board"] += 1
            elif anchor > series[-1][0]:
                census["event follows the board"] += 1
            else:
                census["no quote inside the window"] += 1
            continue
        census["usable"] += 1
        out.append({"game_pk": ev["game_pk"], "after": after,
                    "before": _net(series, anchor - span, anchor),
                    "expected": expected})
    return out, census


def _hit_rate(observations, field="after"):
    """(hits, movers, ties) for one window.

    A net move of exactly zero is not evidence either way. It leaves the
    denominator and is counted, because a market that mostly does not move
    would otherwise masquerade as one that moves correctly.
    """
    hits = movers = ties = 0
    for obs in observations:
        move = obs.get(field)
        if move is None:
            continue
        if move == 0:
            ties += 1
            continue
        movers += 1
        if (move > 0) == (obs["expected"] > 0):
            hits += 1
    return hits, movers, ties


def _clustered_interval(observations, field="after", alpha=ALPHA,
                        resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED):
    """Percentile interval on the hit rate, resampling WHOLE GAMES.

    Two events on one game read the same board minutes apart and are not
    independent draws; resampling events would understate the interval.
    """
    by_game = defaultdict(list)
    for obs in observations:
        move = obs.get(field)
        if move is None or move == 0:
            continue
        by_game[obs["game_pk"]].append((move > 0) == (obs["expected"] > 0))
    games = list(by_game)
    if len(games) < 2:
        return None
    rng = random.Random(seed)
    rates = []
    for _ in range(resamples):
        hits = total = 0
        for _ in games:
            for hit in by_game[games[rng.randrange(len(games))]]:
                total += 1
                hits += 1 if hit else 0
        if total:
            rates.append(hits / total)
    if not rates:
        return None
    rates.sort()
    lo = rates[max(0, int((alpha / 2) * len(rates)) - 1)]
    hi = rates[min(len(rates) - 1, int((1 - alpha / 2) * len(rates)))]
    return [lo, hi]


def _verdict(movers, interval):
    if movers < MIN_EVENTS or interval is None:
        return "UNDETERMINED"
    if interval[0] > 0.50:
        return "CONFIRMED"
    if interval[1] < 0.50:
        return "REFUTED"
    return "UNDETERMINED"


# --------------------------------------------------------------------------
# The hypotheses, signs exactly as pre-registered
# --------------------------------------------------------------------------

def _temperature_sign(ev):
    """Rising forecast temperature -> total rises. Falling -> total falls.

    Only a reading with a recorded `from` is a CHANGE; the rest are first
    observations and carry no direction.
    """
    if ev["kind"] != "weather_forecast_updated":
        return None
    field = (ev["payload"] or {}).get("temp_f")
    if not isinstance(field, dict):
        return None
    frm, to = _number(field.get("from")), _number(field.get("to"))
    if frm is None or to is None or frm == to:
        return None
    return 1 if to > frm else -1


def _precip_sign(ev):
    """Rising rain probability -> total falls. Secondary; a called game is a
    shorter game."""
    if ev["kind"] != "weather_forecast_updated":
        return None
    field = (ev["payload"] or {}).get("precip_probability_pct")
    if not isinstance(field, dict):
        return None
    frm, to = _number(field.get("from")), _number(field.get("to"))
    if frm is None or to is None or frm == to:
        return None
    return -1 if to > frm else 1


def _transaction_sign(category, team_effect, sides):
    """A transaction moves the HOME probability up or down depending on which
    side the transacting team is on.

    `team_effect` is +1 when the named team gets stronger. The board tracks
    the home team's probability, so an away team getting stronger moves that
    number DOWN. Getting this backwards would invert the entire result, which
    is why the mapping is one expression and is covered by its own test.
    """
    def sign_of(ev):
        if ev["kind"] != "transaction_relevant":
            return None
        payload = ev["payload"] or {}
        if payload.get("category") != category:
            return None
        team = payload.get("team")
        pair = sides.get(ev["game_pk"])
        if not team or not pair:
            return None
        home_code, away_code = pair
        if team == home_code:
            return team_effect
        if team == away_code:
            return -team_effect
        return None
    return sign_of


def _unsigned(kind, category=None):
    """Secondary buckets with no declared sign. Scored against +1 purely so
    the printed rate reads as "fraction that RAISED the home number"; nothing
    is decided from it and the pre-registration says so."""
    def sign_of(ev):
        if ev["kind"] != kind:
            return None
        if category is not None and (ev["payload"] or {}).get("category") != category:
            return None
        return 1
    return sign_of


# --------------------------------------------------------------------------

def _report(name, observations, census, gated=True):
    hits, movers, ties = _hit_rate(observations, "after")
    interval = _clustered_interval(observations, "after")
    b_hits, b_movers, _b_ties = _hit_rate(observations, "before")
    row = {
        "name": name, "n_signable": len(observations), "movers": movers,
        "ties": ties, "hits": hits,
        "rate": (hits / movers) if movers else None,
        "ci": interval,
        "before_rate": (b_hits / b_movers) if b_movers else None,
        "before_movers": b_movers,
        "verdict": _verdict(movers, interval) if gated else "DESCRIPTIVE",
        "census": census,
    }
    return row


def _print_census(row):
    """Where every signable event went. See `_observations`."""
    census = row.get("census") or {}
    signable = census.get("signable", 0)
    if not signable:
        return
    print(f"  {row['name']}")
    print(f"    {signable} events carry a direction")
    for key in ("no board for that game", "event precedes the board",
                "event follows the board", "no quote inside the window",
                "usable"):
        count = census.get(key, 0)
        if count:
            print(f"      {count:>4}  {key}")


def _print_row(row):
    rate = row["rate"]
    rate_s = f"{rate:.3f}" if rate is not None else "  --  "
    ci = row["ci"]
    ci_s = f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "[ too few games ]"
    before = row["before_rate"]
    before_s = f"{before:.3f}" if before is not None else "  --  "
    print(f"  {row['name']:<34} n={row['movers']:<4} hit {rate_s}  "
          f"{ci_s:<18} before {before_s}  {row['verdict']}")
    if row["ties"]:
        print(f"  {'':<34} ({row['ties']} did not move at all, excluded)")


def _lead_hours(stamp, game_pk, first_pitch):
    """Hours between `stamp` and first pitch. Negative means afterwards."""
    when = first_pitch.get(game_pk)
    if when is None:
        return None
    return (when - stamp).total_seconds() / 3600


def _spread(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return {"n": len(values), "median": statistics.median(values),
            "p10": values[int(0.10 * len(values))],
            "p90": values[int(0.90 * len(values))]}


def _print_timing(events, moneyline, totals, first_pitch):
    """Does a priceable market even EXIST when each kind of news arrives?

    This is the question that decides whether a thin sample is a spending
    problem or a structural one. A book that has not opened a game cannot
    react to news about it, and no amount of polling invents a price.
    """
    print("IS THERE A MARKET TO MOVE, WHEN THE NEWS LANDS?")
    print("  hours before first pitch; negative means after the game started")

    def show(label, values):
        got = _spread(values)
        if not got:
            print(f"    {label:<34} none")
            return
        print(f"    {label:<34} n={got['n']:<4} "
              f"median {got['median']:6.1f}h   "
              f"p10 {got['p10']:6.1f}h  p90 {got['p90']:6.1f}h")

    for name, boards in (("moneyline", moneyline), ("totals", totals)):
        show(f"{name} board opens",
             [_lead_hours(s[0][0], g, first_pitch) for g, s in boards.items()])
        show(f"{name} board closes",
             [_lead_hours(s[-1][0], g, first_pitch) for g, s in boards.items()])

    kinds = (
        ("temperature change (control)",
         lambda e: _temperature_sign(e) is not None),
        ("il_placement (H1)",
         lambda e: e["kind"] == "transaction_relevant"
         and (e["payload"] or {}).get("category") == "il_placement"),
        ("il_activation (H2)",
         lambda e: e["kind"] == "transaction_relevant"
         and (e["payload"] or {}).get("category") == "il_activation"),
        ("lineup_posted", lambda e: e["kind"] == "lineup_posted"),
    )
    for label, matches in kinds:
        show(label, [_lead_hours(e["at"], e["game_pk"], first_pitch)
                     for e in events if matches(e)])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    events = _read_events()
    if not events:
        print("no information events stored", file=sys.stderr)
        return 1

    mapping = _event_to_game_map()
    sides = _game_sides()
    first_pitch = _first_pitch()
    moneyline = _by_game(_moneyline_series(), mapping)
    totals = _by_game(_total_series(), mapping)

    print("=" * 78)
    print("EVENT DIRECTION -- does the price move the way we could have called?")
    print("=" * 78)
    print(f"  {len(events)} information events")
    print(f"  {len(moneyline)} games with a moneyline board, "
          f"{len(totals)} with a totals board")
    print(f"  window {HORIZON_MINUTES} min   "
          f"Bonferroni {PRIMARY_HYPOTHESES} tests -> "
          f"{100 * (1 - ALPHA):.2f}% intervals")
    print()
    print("  Criterion: docs/PREREG_EVENT_DIRECTION.md, committed before this ran.")
    print()

    primary = []

    obs, census = _observations(events, totals, _temperature_sign)
    control = _report("CONTROL temp -> total", obs, census)
    primary.append(control)

    obs, census = _observations(events, moneyline,
                               _transaction_sign("il_placement", -1, sides))
    primary.append(_report("H1 IL placement -> team down", obs, census))

    obs, census = _observations(events, moneyline,
                               _transaction_sign("il_activation", +1, sides))
    primary.append(_report("H2 IL activation -> team up", obs, census))

    print("PRIMARY  (hit = moved the way the sign said it would)")
    for row in primary:
        _print_row(row)

    print()
    print("WHERE THE SAMPLE WENT")
    for row in primary:
        _print_census(row)

    print()
    _print_timing(events, moneyline, totals, first_pitch)

    print()
    print("THE CONTROL DECIDES HOW TO READ THE REST")
    if control["verdict"] == "CONFIRMED":
        print("  The instrument sees a known public effect. A null beside it")
        print("  is a real null and can be believed.")
    else:
        print("  *** THE POSITIVE CONTROL DID NOT CONFIRM. ***")
        print("  A known, public, well-documented effect was not detected.")
        print("  That means this instrument has not been shown to be able to")
        print("  detect anything, and NO NULL BELOW OR ABOVE IS EVIDENCE OF")
        print("  ABSENCE. Read nothing into the other rows.")

    print()
    print("SECONDARY  (no declared sign; decides nothing -- rate is "
          "'fraction that raised the home number')")
    secondary = []
    obs, census = _observations(events, totals, _precip_sign)
    secondary.append(_report("rain up -> total down", obs, census, gated=False))
    for category in ("recalled", "optioned", "designated", "rehab"):
        obs, census = _observations(
            events, moneyline, _unsigned("transaction_relevant", category))
        secondary.append(_report(f"{category} (unsigned)", obs, census,
                                 gated=False))
    obs, census = _observations(events, moneyline, _unsigned("lineup_posted"))
    secondary.append(_report("lineup_posted (unsigned)", obs, census,
                             gated=False))
    obs, census = _observations(events, moneyline, _unsigned("lineup_changed"))
    secondary.append(_report("lineup_changed (unsigned)", obs, census,
                             gated=False))
    for row in secondary:
        _print_row(row)

    print()
    print("BEFORE vs AFTER -- did the price move before we saw it?")
    print("  'before' above is the same statistic over the 120 min BEFORE the")
    print("  event. A before-rate as high as the after-rate means the market")
    print("  had already moved and we are reading news it has finished")
    print("  absorbing. Descriptive: it decides nothing, because reporting")
    print("  that never reaches our ledger would look the same.")

    if args.json:
        print()
        print(json.dumps({"primary": primary, "secondary": secondary},
                         indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
