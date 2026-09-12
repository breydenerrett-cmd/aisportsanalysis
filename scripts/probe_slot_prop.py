"""V7 -- when a batter is posted higher than his own norm, does the market
shorten his hits Over? The reader for docs/PREREG_SLOT_PROP.md.

It refuses to read below the floors: below them it prints PENDING and the
counts, and nothing else. Every threshold is a constant here, mirrored in
the pre-registration, and none is a command-line argument.

Registered 2026-09-12, before a single post-lineup batter-prop quote
existed in this repo (the T-2h capture gate landed after the 09-11 slate's
windows had closed). The registry row is V7:lineup_slot_prop_repricing:
batter_hits.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import propboard  # noqa: E402
from src.pipeline import batter_props, lineup_store  # noqa: E402
from scripts import probe_event_direction as base  # noqa: E402

MARKET = "batter_hits"
SECONDARY_MARKET = "batter_total_bases"
NORM_WINDOW = 10
MIN_PRIOR_LINEUPS = 10
MIN_BASELINE_NIGHTS = 3
UP_AT_LEAST = 2
FLOOR_PER_GROUP = 150
CONTROL_FLOOR_PER_GROUP = 100
LEAD_MINUTES = 120
DRAWS = 2000
SEED = 20260912
ALPHA = 0.05
TOP_SLOTS = (1, 2)
BOTTOM_SLOTS = (8, 9)
REGISTRY_ID = "V7:lineup_slot_prop_repricing:batter_hits"


def family_alpha(declared=ALPHA):
    """The declared alpha divided by the registry's hypothesis count -- the
    family-wise bar. (declared, None) when the registry cannot be read."""
    try:
        from src.research import alpha_registry
        n = alpha_registry.public_research_counts()["hypotheses"]
    except Exception:  # noqa: BLE001 -- an unreadable registry is reported, not hidden
        return declared, None
    if not n:
        return declared, None
    return declared / n, n


def parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Lineups: who batted where, and when the card was posted
# ---------------------------------------------------------------------------

def lineups_by_date(stored):
    """From `lineup_store.read()`: ({date: {player: slot}},
    {(date, game_pk): posted_at}). A card with no `observed_utc` has no
    posting time and its game can never anchor the window."""
    slots = defaultdict(dict)
    posted = {}
    for game_pk, row in (stored or {}).items():
        date = str(row.get("date") or "")[:10]
        if not date:
            continue
        when = parse_iso(row.get("observed_utc"))
        if when is not None:
            posted[(date, str(game_pk))] = when
        for side in ("away", "home"):
            for index, batter in enumerate(row.get(side) or [], start=1):
                if not isinstance(batter, dict) or not batter.get("name"):
                    continue
                try:
                    slot = int(batter.get("order") or index)
                except (TypeError, ValueError):
                    continue
                slots[date][batter["name"]] = slot
    return dict(slots), posted


def slot_history(slots_by_date):
    """{player: [(date, slot), ...]} oldest first."""
    out = defaultdict(list)
    for date in sorted(slots_by_date):
        for player, slot in slots_by_date[date].items():
            out[player].append((date, slot))
    return dict(out)


def norm_slot(prior_slots, window=NORM_WINDOW, min_prior=MIN_PRIOR_LINEUPS):
    """Median of the last `window` prior slots; None below `min_prior`."""
    if len(prior_slots) < min_prior:
        return None
    return statistics.median(prior_slots[-window:])


def delta_slot(norm, tonight):
    """Positive when the batter moved UP the order."""
    return norm - tonight


def group_of(delta):
    if delta >= UP_AT_LEAST:
        return "UP"
    if delta <= -UP_AT_LEAST:
        return "DOWN"
    if delta == 0:
        return "FLAT"
    return None


# ---------------------------------------------------------------------------
# Quotes: post-lineup, inside the window, de-vigged
# ---------------------------------------------------------------------------

def post_lineup_rows(prop_rows, posted_by_event, lead_minutes=LEAD_MINUTES):
    """Quotes observed at or after the game's posting time and within
    `lead_minutes` of first pitch. A quote from before the posting -- the
    pre-gate 04:00Z captures -- is not post-lineup and is dropped."""
    out = []
    for row in prop_rows:
        observed = parse_iso(row.get("observed_utc"))
        commence = parse_iso(row.get("commence_time"))
        posted = posted_by_event.get(row.get("event_id"))
        if observed is None or commence is None or posted is None:
            continue
        if observed < posted:
            continue
        lead = (commence - observed).total_seconds() / 60.0
        if lead <= 0 or lead > lead_minutes:
            continue
        out.append(row)
    return out


def fair_over_by_key(rows):
    """{(date, event, player, market, line): fair Over} for every contract
    with two books quoting both sides at their newest quote."""
    out = {}
    for key, books in propboard._newest_quotes(rows).items():
        market_over, _best = propboard.fair_and_best(books)
        if market_over is not None:
            out[key] = market_over
    return out


def baseline_fair(history, date, min_nights=MIN_BASELINE_NIGHTS):
    """Median fair Over over the batter's prior nights; None below the floor."""
    prior = [fair for d, fair in history if d < date]
    if len(prior) < min_nights:
        return None
    return statistics.median(prior)


def build_rows(fair_by_key, slots_by_date, history, market=MARKET):
    """(scored rows for the primary test, control rows) for one market.

    Control rows are every night's (slot, fair) with no norm or baseline
    needed -- the instrument check compares top-of-order with bottom on
    the same nights."""
    fair_history = defaultdict(list)
    for (date, _event, player, mkt, line), fair in sorted(fair_by_key.items()):
        if mkt == market:
            fair_history[(player, line)].append((date, fair))
    rows, control = [], []
    for (date, _event, player, mkt, line), fair in sorted(fair_by_key.items()):
        if mkt != market:
            continue
        slot = (slots_by_date.get(date) or {}).get(player)
        if slot is None:
            continue
        control.append({"date": date, "player": player, "slot": slot,
                        "fair": fair, "line": line})
        prior = [s for d, s in history.get(player, []) if d < date]
        norm = norm_slot(prior)
        if norm is None:
            continue
        delta = delta_slot(norm, slot)
        group = group_of(delta)
        if group is None:
            continue
        base_fair = baseline_fair(fair_history[(player, line)], date)
        if base_fair is None:
            continue
        rows.append({"date": date, "player": player, "line": line,
                     "slot": slot, "norm": norm, "delta": delta,
                     "group": group, "fair": fair, "baseline": base_fair,
                     "dfair": fair - base_fair})
    return rows, control


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def cluster_bootstrap_difference(a_rows, b_rows, key, alpha, draws=DRAWS,
                                 seed=SEED):
    """(low, high, point) for mean(a) - mean(b), resampling slate DATES with
    replacement -- a night's quotes share a board. None when either side
    is empty or too few draws had both groups."""
    if not a_rows or not b_rows:
        return None
    by_date_a, by_date_b = defaultdict(list), defaultdict(list)
    for r in a_rows:
        by_date_a[r["date"]].append(r[key])
    for r in b_rows:
        by_date_b[r["date"]].append(r[key])
    dates = sorted(set(by_date_a) | set(by_date_b))
    point = (statistics.fmean([r[key] for r in a_rows])
             - statistics.fmean([r[key] for r in b_rows]))
    rng = random.Random(seed)
    diffs = []
    for _ in range(draws):
        picked = [rng.choice(dates) for _ in dates]
        a = [v for d in picked for v in by_date_a.get(d, ())]
        b = [v for d in picked for v in by_date_b.get(d, ())]
        if not a or not b:
            continue
        diffs.append(statistics.fmean(a) - statistics.fmean(b))
    if len(diffs) < draws // 2:
        return None
    diffs.sort()
    low = diffs[int((alpha / 2) * len(diffs))]
    high = diffs[min(len(diffs) - 1, int((1 - alpha / 2) * len(diffs)))]
    return low, high, point


def read_state(n_up, n_flat, n_top, n_bottom, floor=FLOOR_PER_GROUP,
               control_floor=CONTROL_FLOOR_PER_GROUP):
    """"READ" only when every floor is met. The floors do not move."""
    if (n_up >= floor and n_flat >= floor
            and n_top >= control_floor and n_bottom >= control_floor):
        return "READ"
    return "PENDING"


def verdict_from(interval):
    if interval is None:
        return "UNDETERMINED"
    low, _high, _point = interval
    return "CONFIRMED" if low > 0 else "NOT SUPPORTED"


def control_groups(control, top=TOP_SLOTS, bottom=BOTTOM_SLOTS):
    """Top-of-order versus bottom, at the market's most common line so the
    comparison is like with like."""
    lines = [r["line"] for r in control]
    if not lines:
        return [], []
    modal = statistics.mode(lines)
    a = [r for r in control if r["slot"] in top and r["line"] == modal]
    b = [r for r in control if r["slot"] in bottom and r["line"] == modal]
    return a, b


def report(rows, control, alpha, family_size):
    up = [r for r in rows if r["group"] == "UP"]
    flat = [r for r in rows if r["group"] == "FLAT"]
    down = [r for r in rows if r["group"] == "DOWN"]
    top, bottom = control_groups(control)
    state = read_state(len(up), len(flat), len(top), len(bottom))
    out = {"state": state, "n_up": len(up), "n_flat": len(flat),
           "n_down": len(down), "n_top": len(top), "n_bottom": len(bottom),
           "alpha": alpha, "family_size": family_size,
           "floors": {"group": FLOOR_PER_GROUP, "control": CONTROL_FLOOR_PER_GROUP}}
    if state == "PENDING":
        return out
    ctrl = cluster_bootstrap_difference(top, bottom, "fair", alpha)
    out["control"] = {"interval": ctrl, "verdict": verdict_from(ctrl)}
    primary = cluster_bootstrap_difference(up, flat, "dfair", alpha)
    out["primary"] = {"interval": primary, "verdict": verdict_from(primary)}
    # FLAT minus DOWN above zero is DOWN below FLAT: the declared mirror.
    mirror = cluster_bootstrap_difference(flat, down, "dfair", alpha)
    out["mirror"] = {"interval": mirror, "verdict": verdict_from(mirror)}
    if out["control"]["verdict"] != "CONFIRMED":
        out["primary"]["verdict"] = "UNDETERMINED"
        out["mirror"]["verdict"] = "UNDETERMINED"
        out["note"] = ("the positive control did not confirm: this instrument "
                       "has not been shown able to see plate-appearance "
                       "effects, so no null here is evidence of absence")
    return out


def _fmt(interval):
    if interval is None:
        return "[too few]"
    low, high, point = interval
    return f"{point:+.4f}  [{low:+.4f}, {high:+.4f}]"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    stored = lineup_store.read()
    slots_by_date, posted = lineups_by_date(stored)
    posted_by_pk = {str(pk): when for (_date, pk), when in posted.items()}
    posted_by_event = {}
    for event_id, game_pk in base._event_to_game_map().items():
        when = posted_by_pk.get(str(game_pk))
        if when is not None:
            posted_by_event[event_id] = when

    all_rows = batter_props.read_processed()
    rows = post_lineup_rows(all_rows, posted_by_event)
    fair = fair_over_by_key(rows)
    history = slot_history(slots_by_date)
    alpha, family = family_alpha()

    results = {}
    for market in (MARKET, SECONDARY_MARKET):
        scored, control = build_rows(fair, slots_by_date, history, market=market)
        results[market] = report(scored, control, alpha, family)

    if args.json:
        print(json.dumps({"registry_id": REGISTRY_ID, "quotes_all": len(all_rows),
                          "quotes_post_lineup": len(rows),
                          "contracts_with_fair": len(fair),
                          "results": results}, indent=2, default=str))
        return 0

    print("=" * 78)
    print("SLOT -> PROP REPRICING -- does the market shorten a batter's Over")
    print("when he is posted above his norm?  (V7, docs/PREREG_SLOT_PROP.md)")
    print("=" * 78)
    print(f"  {len(all_rows)} batter-prop quotes on disk, {len(rows)} post-lineup "
          f"inside {LEAD_MINUTES} min, {len(fair)} contracts with a fair Over")
    label = f"family of {family}" if family else "registry unreadable"
    print(f"  alpha {alpha:.5f} ({label})")
    for market, res in results.items():
        tag = "PRIMARY" if market == MARKET else "SECONDARY (decides nothing)"
        print()
        print(f"{tag} -- {market}")
        print(f"  UP n={res['n_up']}  FLAT n={res['n_flat']}  DOWN n={res['n_down']}"
              f"   control top n={res['n_top']}  bottom n={res['n_bottom']}")
        if res["state"] == "PENDING":
            need_up = max(0, FLOOR_PER_GROUP - res["n_up"])
            need_flat = max(0, FLOOR_PER_GROUP - res["n_flat"])
            print(f"  VERDICT: PENDING -- floors {FLOOR_PER_GROUP}/{FLOOR_PER_GROUP} "
                  f"(need {need_up} more UP, {need_flat} more FLAT), control "
                  f"{CONTROL_FLOOR_PER_GROUP} each. Nothing is read early.")
            continue
        print(f"  control  top - bottom fair Over   {_fmt(res['control']['interval'])}"
              f"   {res['control']['verdict']}")
        print(f"  H1       UP - FLAT dfair          {_fmt(res['primary']['interval'])}"
              f"   {res['primary']['verdict']}")
        print(f"  mirror   FLAT - DOWN dfair        {_fmt(res['mirror']['interval'])}"
              f"   {res['mirror']['verdict']}")
        if res.get("note"):
            print(f"  *** {res['note']} ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
