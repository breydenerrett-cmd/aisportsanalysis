"""When a depleted lineup posts, does the price move against that team?

Criterion pre-registered in `docs/PREREG_LINEUP_DIRECTION.md`, committed
before this file was written. The sign, the tie-breaks, the minimum history,
the window, the statistic and the decision rule are fixed there.

WHY THIS EVENT
--------------
`scripts/probe_event_direction.py` ran three direction tests and none could
answer. Two failed on TIMING: weather news arrives before any book has priced
the game, and IL placements are filed against games already played.

`lineup_posted` has neither problem. It lands a median 2.9 hours before first
pitch -- inside the window where a market exists, is liquid, and is about to
be bet -- and it is the largest event class on disk.

THE TRAP, AND THE WHOLE REASON THE BASELINE IS WHAT IT IS
---------------------------------------------------------
A posted lineup differs from the club's previous one by a mean of 2.22
batters out of nine. Almost all of that is rest days and platoon splits:
routine, scheduled, and already in the price. A signer that treats "different
from last night" as news would spend its sample measuring the weekly bench
rotation, and would look directionally sensible while doing it.

So the baseline is not last night's lineup. It is the EXPECTED lineup -- the
nine players with the highest appearance rate over that club's prior posted
lineups -- and the surprise is the summed appearance rate of expected
regulars who are absent tonight. A man who starts nine nights in ten and is
out is news. A man who starts five in ten and is out is Tuesday.

WHY AVAILABILITY AND NOT QUALITY
--------------------------------
A richer signer would score lineup quality. Three routes were checked and all
three were worse (the pre-registration records the measurements):

  * src/analysis/strength.py says outright, line 81: "Lineups are ignored
    entirely." No function in it takes a player or a batting order.
  * The wOBA route reads data/historical/statcast/, which does not exist,
    and its only caches cover 2023 and 2024 against a 2026 test window.
  * Composing playerprops.batter_rates nine-wide refuses any batter under 40
    plate appearances, which only 53% of posted lineups survive -- and the
    batters who refuse are the call-ups and platoon players whose appearance
    IS the news. That route selects against the lineups worth measuring.

Availability needs no batter model, no plate-appearance floor, and nothing
beyond the lineups themselves.

Read-only. Adopts nothing.

Usage:
    python scripts/probe_lineup_direction.py [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import probe_event_direction as base  # noqa: E402

# A club needs this many prior posted lineups before an appearance rate is
# anything but noise.
MIN_PRIOR_LINEUPS = 3

# Fixed in the pre-registration; the same floor the transaction tests used.
MIN_EVENTS = 25

# THE PRE-REGISTERED ALPHA, and why it is not the one that decides.
#
# docs/PREREG_LINEUP_DIRECTION.md declared 0.05 on the grounds that this is
# one primary hypothesis. Adversarial review, 2026-09-11, pointed out that
# the grounds are wrong: this programme keeps `data/research/alpha_registry.jsonl`
# precisely to count how many hypotheses it has tested against this market,
# and the answer is 40 before this one. The parent probe
# (scripts/probe_event_direction.py) already divides by its own sibling count.
#
# A result that clears 0.05 as though it were the first thing ever tried is
# not clearing the bar this programme set for itself. So both are computed
# and THE STRICTER ONE DECIDES. Reporting only the pre-registered figure
# would be true and misleading at the same time.
ALPHA = 0.05


def family_alpha(declared=ALPHA):
    """`declared` spread over every hypothesis this programme has registered.

    Falls back to the declared alpha when the registry cannot be read -- a
    missing ledger must not silently make the bar easier.
    """
    try:
        from src.research import alpha_registry
        counts = alpha_registry.public_research_counts()
        n = max(1, int(counts.get("hypotheses") or 1))
    except Exception:  # noqa: BLE001 -- see docstring
        return declared, None
    return declared / n, n


# FORWARD REPLICATION, as registered (data/research/alpha_registry.jsonl,
# V6:lineup_surprise_direction:h2h): postings collected strictly after the
# registration instant, read once at a floor of 150 usable observations,
# at the family-wise alpha only. Neither number moves.
from datetime import datetime as _dt, timezone as _tz
REGISTERED_AT = _dt(2026, 9, 11, 20, 38, 15, tzinfo=_tz.utc)
FORWARD_FLOOR = 150


def _lineup_rows(events, sides, first_pitch):
    """[{team, date, lineup, side, game_pk, at}] for every usable posting.

    An event is dropped when its game cannot be resolved to two sides, when
    the posting is not a full nine, or when the game has no first pitch --
    never guessed into place.
    """
    rows = []
    dropped = Counter()
    for ev in events:
        if ev["kind"] != "lineup_posted":
            continue
        payload = ev["payload"] or {}
        side = payload.get("side")
        lineup = payload.get("lineup") or []
        pair = sides.get(ev["game_pk"])
        when = first_pitch.get(ev["game_pk"])
        if not pair:
            dropped["game not resolvable to two sides"] += 1
            continue
        if side not in ("home", "away"):
            dropped["no side on the posting"] += 1
            continue
        if len(lineup) != 9:
            dropped["not a full nine"] += 1
            continue
        if when is None:
            dropped["no first pitch"] += 1
            continue
        home_code, away_code = pair
        rows.append({
            "team": home_code if side == "home" else away_code,
            "date": when.date(), "lineup": list(lineup), "side": side,
            "game_pk": ev["game_pk"], "at": ev["at"],
        })
    rows.sort(key=lambda r: (r["team"], r["date"], r["at"]))
    return rows, dropped


def _expected_lineup(prior_lineups):
    """The nine players most likely to start, and their appearance rates.

    `prior_lineups` is that club's postings STRICTLY BEFORE the game being
    scored, oldest first. Ties are broken by most recent appearance first,
    then lowest player_id -- a deterministic rule fixed in the
    pre-registration so it cannot be chosen afterwards to suit an answer.
    """
    appearances = Counter()
    last_seen = {}
    for index, lineup in enumerate(prior_lineups):
        for player in lineup:
            appearances[player] += 1
            last_seen[player] = index
    total = len(prior_lineups)
    rate = {player: count / total for player, count in appearances.items()}
    ordered = sorted(rate, key=lambda p: (-rate[p], -last_seen[p], p))
    return ordered[:9], rate


def _surprise(expected, rate, tonight):
    """Summed appearance rate of expected regulars who are NOT playing.

    Zero when the expected nine all start. Grows with both how many regulars
    are missing and how reliable they were -- which is the distinction the
    whole test rests on, because two of nine changing is the norm.
    """
    playing = set(tonight)
    return sum(rate[player] for player in expected if player not in playing)


def score_lineups(rows, min_prior=MIN_PRIOR_LINEUPS):
    """Attach surprise to each posting that has enough history behind it."""
    by_team = defaultdict(list)
    for row in rows:
        by_team[row["team"]].append(row)

    scored = []
    skipped_thin = 0
    for _team, games in by_team.items():
        for index, game in enumerate(games):
            prior = games[:index]
            if len(prior) < min_prior:
                skipped_thin += 1
                continue
            expected, rate = _expected_lineup([g["lineup"] for g in prior])
            surprise = _surprise(expected, rate, game["lineup"])
            novel = len([p for p in game["lineup"] if p not in rate])
            scored.append({**game, "surprise": surprise, "novel": novel,
                           "n_prior": len(prior),
                           "missing": len([p for p in expected
                                           if p not in set(game["lineup"])])})
    return scored, skipped_thin


def sign_of(row):
    """Which way the HOME number should move after this posting.

    The board tracks the home team's probability. A depleted HOME lineup
    should push it down; a depleted AWAY lineup should push it up. Inverting
    this would flip the whole result while still printing a plausible number,
    which is why it is one expression with its own test.

    None when the posting carries no directional claim -- the expected nine
    all started.
    """
    if row.get("surprise", 0) <= 0:
        return None
    return -1 if row["side"] == "home" else +1


def _observations(scored, boards, window=base.HORIZON_MINUTES):
    from datetime import timedelta
    out = []
    census = Counter()
    span = timedelta(minutes=window)
    for row in scored:
        expected = sign_of(row)
        census["scorable"] += 1
        if expected is None:
            census["expected nine all started"] += 1
            continue
        series = boards.get(row["game_pk"])
        if not series:
            census["no board for that game"] += 1
            continue
        anchor = row["at"]
        after = base._net(series, anchor, anchor + span)
        if after is None:
            if anchor < series[0][0]:
                census["event precedes the board"] += 1
            elif anchor > series[-1][0]:
                census["event follows the board"] += 1
            else:
                census["no quote inside the window"] += 1
            continue
        census["usable"] += 1
        out.append({"game_pk": row["game_pk"], "after": after,
                    "before": base._net(series, anchor - span, anchor),
                    "expected": expected, "surprise": row["surprise"],
                    "team": row["team"], "side": row["side"],
                    "novel": row["novel"], "missing": row["missing"],
                    # When the posting landed, so a forward read can keep to
                    # postings collected after the registration instant.
                    "at": anchor})
    return out, census


def forward_only(observations, cutoff=None):
    """The observations whose posting landed AFTER the registration instant
    -- the out-of-sample set V6's forward replication is allowed to read.

    Strictly after: a posting at the registration second itself was in the
    discovery data. A naive timestamp is read as UTC, which is what every
    store in this repo writes."""
    from datetime import timezone
    cutoff = cutoff or REGISTERED_AT
    out = []
    for o in observations:
        at = o.get("at")
        if at is None:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at > cutoff:
            out.append(o)
    return out


def forward_state(n, floor=FORWARD_FLOOR):
    """"PENDING" until the pre-registered floor, "READ" at or past it. The
    floor is not lowered by a run that happens to be close."""
    return "READ" if n >= floor else "PENDING"


def _dose_response(observations):
    """THE SENSITIVITY CONTROL. Magnitude, not direction.

    Split at the median surprise and compare how far the price moves,
    ignoring which way. If a big surprise moves it no further than a small
    one, this instrument cannot see lineup news at all -- and then a null on
    direction is not evidence of absence, it is evidence of a blind
    instrument. Last round's control failed and made every null beside it
    uninterpretable; this one exists so that cannot happen silently again.
    """
    if len(observations) < 4:
        return None
    surprises = sorted(o["surprise"] for o in observations)
    cut = statistics.median(surprises)
    low = [abs(o["after"]) * 100 for o in observations if o["surprise"] <= cut]
    high = [abs(o["after"]) * 100 for o in observations if o["surprise"] > cut]
    if len(low) < 2 or len(high) < 2:
        return None
    return {
        "cut": cut,
        "low_n": len(low), "high_n": len(high),
        "low_mean": statistics.fmean(low), "high_mean": statistics.fmean(high),
        "low_median": statistics.median(low),
        "high_median": statistics.median(high),
        "ratio": (statistics.fmean(high) / statistics.fmean(low)
                  if statistics.fmean(low) else None),
    }


def _posting_gaps(scored, observations):
    """{game_pk: minutes between that game's two postings}, None if only one.

    The gap is a property of WHEN the lineups were published. It is known
    without looking at a single price, which is what makes splitting on it
    legitimate where splitting on the outcome would not be.
    """
    anchor = {(row["game_pk"], row["side"]): row["at"] for row in scored}
    by_game = defaultdict(list)
    for obs in observations:
        stamp = anchor.get((obs["game_pk"], obs["side"]))
        if stamp is not None:
            by_game[obs["game_pk"]].append(stamp)
    out = {}
    for game_pk, stamps in by_game.items():
        out[game_pk] = ((max(stamps) - min(stamps)).total_seconds() / 60
                        if len(stamps) >= 2 else None)
    return out


def _structural_split(observations, gaps, shared_minutes=45):
    """Which observations could actually have falsified the hypothesis.

    THE PROBLEM THIS EXISTS TO SURFACE, found only after the first run.

    Both clubs post a lineup for the same game, usually within the hour, and
    a depleted HOME lineup and a depleted AWAY lineup predict OPPOSITE moves
    in the same number. When the two postings share a window, the price can
    only go one way, so exactly one of the pair is a hit whatever the market
    does. Those games are pinned to 0.500 by arithmetic, contribute two
    observations each to `n`, and cannot test anything.

    Reporting a pooled hit rate without saying this invites the reader to
    treat the headline `n` as the sample size. It is not.
    """
    free, forced = [], []
    for obs in observations:
        gap = gaps.get(obs["game_pk"])
        (forced if gap is not None and gap < shared_minutes else free
         ).append(obs)
    return free, forced


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--forward", action="store_true",
                    help="the registered forward replication: postings after "
                         f"{REGISTERED_AT.isoformat()} only, PENDING below "
                         f"{FORWARD_FLOOR}, family-wise alpha only")
    args = ap.parse_args(argv)

    events = base._read_events()
    if not events:
        print("no information events stored", file=sys.stderr)
        return 1
    sides = base._game_sides()
    first_pitch = base._first_pitch()
    mapping = base._event_to_game_map()
    boards = base._by_game(base._moneyline_series(), mapping)

    rows, dropped = _lineup_rows(events, sides, first_pitch)
    scored, skipped_thin = score_lineups(rows)
    observations, census = _observations(scored, boards)

    if args.forward:
        # The priors behind each posting's "expected nine" may reach back
        # into the discovery window -- that is history, not a read. Only the
        # POSTINGS being scored are held to the cutoff.
        forward = forward_only(observations)
        state = forward_state(len(forward))
        print("=" * 78)
        print("LINEUP DIRECTION -- FORWARD REPLICATION (V6, registered "
              f"{REGISTERED_AT.isoformat()})")
        print("=" * 78)
        print(f"  {len(forward)} usable postings after the registration "
              f"instant; floor {FORWARD_FLOOR}")
        if state == "PENDING":
            print(f"\nVERDICT: PENDING -- {FORWARD_FLOOR - len(forward)} more "
                  "usable postings needed. The floor does not get lowered, "
                  "and nothing below is read early.")
            return 0
        strict_alpha, family_size = family_alpha()
        hits, movers, ties = base._hit_rate(forward, "after")
        strict = base._clustered_interval(forward, "after", alpha=strict_alpha)
        verdict = base._verdict(movers, strict) if strict else "UNDETERMINED"
        ci = f"[{strict[0]:.3f}, {strict[1]:.3f}]" if strict else "[too few]"
        print(f"    n={movers}   hit {hits / movers:.3f}   "
              f"family of {family_size}   alpha {strict_alpha:.5f}   {ci}")
        print(f"\nVERDICT: {verdict}")
        return 0

    print("=" * 78)
    print("LINEUP DIRECTION -- does a depleted lineup push its own price down?")
    print("=" * 78)
    print(f"  {len(rows)} usable postings, {len(scored)} with "
          f">= {MIN_PRIOR_LINEUPS} prior lineups behind them")
    print(f"  Criterion: docs/PREREG_LINEUP_DIRECTION.md, committed before "
          f"this ran.")
    print()

    hits, movers, ties = base._hit_rate(observations, "after")
    interval = base._clustered_interval(observations, "after", alpha=ALPHA)
    b_hits, b_movers, _bt = base._hit_rate(observations, "before")
    verdict = base._verdict(movers, interval) if movers >= MIN_EVENTS else (
        "UNDETERMINED")
    if interval is None:
        verdict = "UNDETERMINED"

    print("PRIMARY")
    rate = f"{hits / movers:.3f}" if movers else "  --  "
    ci = f"[{interval[0]:.3f}, {interval[1]:.3f}]" if interval else "[too few]"
    before = f"{b_hits / b_movers:.3f}" if b_movers else "  --  "
    print(f"  depleted lineup -> its own number falls")
    print(f"    n={movers}   hit {rate}   before {before}")
    if ties:
        print(f"    ({ties} did not move at all, excluded)")
    print()
    print(f"    as pre-registered   alpha {ALPHA:.5f}   95%   "
          f"{ci}   {verdict}")

    # And the same interval at the bar this programme actually set itself.
    strict_alpha, family_size = family_alpha()
    strict = base._clustered_interval(observations, "after",
                                      alpha=strict_alpha)
    strict_verdict = (base._verdict(movers, strict)
                      if movers >= MIN_EVENTS else "UNDETERMINED")
    strict_ci = (f"[{strict[0]:.3f}, {strict[1]:.3f}]" if strict
                 else "[too few]")
    label = (f"family of {family_size}" if family_size
             else "registry unreadable")
    print(f"    {label:<19} alpha {strict_alpha:.5f}   "
          f"{100 * (1 - strict_alpha):.2f}% {strict_ci}   {strict_verdict}")
    print()
    if verdict == "CONFIRMED" and strict_verdict != "CONFIRMED":
        print("  *** THE STRICTER READING DECIDES, AND IT IS NOT CONFIRMED. ***")
        print("  This clears the alpha its own pre-registration declared, and")
        print("  does not clear the one implied by the 40 hypotheses this")
        print("  programme had already tested against this same market")
        print("  (data/research/alpha_registry.jsonl). The first 'yes' after")
        print("  forty 'no's is exactly the result that needs the harsher")
        print("  bar, not the kinder one. NOT PROMOTED -- held for forward")
        print("  replication on data collected after 2026-09-11.")
        verdict = strict_verdict

    print()
    print("SENSITIVITY CONTROL -- can this instrument see lineup news at all?")
    dose = _dose_response(observations)
    if dose is None:
        print("  too few events to split")
        sensitive = False
    else:
        print(f"  split at surprise {dose['cut']:.2f}")
        print(f"    small surprises  n={dose['low_n']:<4} "
              f"mean move {dose['low_mean']:.2f} pts   "
              f"median {dose['low_median']:.2f}")
        print(f"    big surprises    n={dose['high_n']:<4} "
              f"mean move {dose['high_mean']:.2f} pts   "
              f"median {dose['high_median']:.2f}")
        ratio = dose["ratio"]
        sensitive = bool(ratio and ratio > 1.0)
        print(f"    big/small ratio  {ratio:.2f}" if ratio else "")
    print()
    if sensitive:
        print("  The price moves further after a bigger lineup surprise, so")
        print("  the instrument is at least responsive to lineup news, and a")
        print("  null on direction can be read as a null.")
    else:
        print("  *** BIG SURPRISES DO NOT MOVE THE PRICE MORE THAN SMALL ***")
        print("  This instrument has not been shown able to see lineup news.")
        print("  NO NULL ABOVE IS EVIDENCE OF ABSENCE. Read nothing into it.")

    print()
    print("HOW MUCH OF THAT n COULD HAVE FALSIFIED ANYTHING?")
    print("  Both clubs post for the same game. A depleted home lineup and a")
    print("  depleted away lineup predict OPPOSITE moves in the same number,")
    print("  so when the two postings share a window exactly one of the pair")
    print("  is a hit whatever the market does. Those games are pinned to")
    print("  0.500 by arithmetic and cannot test the hypothesis.")
    print()
    gaps = _posting_gaps(scored, observations)
    free, forced = _structural_split(observations, gaps)
    for name, chunk in (("could falsify it", free),
                        ("structurally pinned", forced)):
        h, m, _t = base._hit_rate(chunk, "after")
        band = base._clustered_interval(chunk, "after", alpha=ALPHA)
        band_s = f"[{band[0]:.3f}, {band[1]:.3f}]" if band else "[too few]"
        bh, bm, _bt = base._hit_rate(chunk, "before")
        print(f"  {name:<22} n={m:<4} hit "
              f"{(h / m if m else 0):.3f}  {band_s:<18} "
              f"before {(bh / bm if bm else 0):.3f}")
    print()
    print("  The pinned stratum sitting near 0.500 is the mechanism working,")
    print("  not evidence against the hypothesis. The split is post-hoc --")
    print("  the 45-minute threshold was chosen after the first run -- so")
    print("  these are DESCRIPTIVE, not estimates. What they establish is")
    print("  that the pre-registered pooled figure is DILUTED rather than")
    print("  inflated, and that the honest sample size is the first row.")

    print()
    print("WHERE THE SAMPLE WENT")
    if skipped_thin:
        print(f"  {skipped_thin}  fewer than {MIN_PRIOR_LINEUPS} prior "
              f"lineups for that club")
    for key, count in dropped.most_common():
        print(f"  {count}  {key}")
    for key in ("expected nine all started", "no board for that game",
                "event precedes the board", "event follows the board",
                "no quote inside the window", "usable"):
        if census.get(key):
            print(f"  {census[key]}  {key}")

    print()
    print("SECONDARY -- descriptive, decides nothing")
    if observations:
        ordered = sorted(observations, key=lambda o: o["surprise"])
        third = max(1, len(ordered) // 3)
        for name, chunk in (("low surprise", ordered[:third]),
                            ("mid surprise", ordered[third:2 * third]),
                            ("high surprise", ordered[2 * third:])):
            h, m, _t = base._hit_rate(chunk, "after")
            span = (f"{chunk[0]['surprise']:.2f}-{chunk[-1]['surprise']:.2f}"
                    if chunk else "-")
            print(f"  {name:<16} {span:<12} n={m:<4} "
                  f"hit {(h / m if m else 0):.3f}")
        novel = Counter(o["novel"] for o in observations)
        print(f"  novel starters per lineup: {dict(sorted(novel.items()))}")

    if args.json:
        print()
        print(json.dumps({
            "n": movers, "hits": hits, "ties": ties,
            "rate": (hits / movers) if movers else None,
            "ci": interval, "verdict": verdict, "dose_response": dose,
            "census": dict(census), "dropped": dict(dropped),
        }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
