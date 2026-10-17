"""Card V3 patch measurements: what each proposed patch would have changed.

Research only. Reads stores, prices through the card's own functions, and
writes small markdown/JSON files under `docs/decisions/card_v3/`. Edits no
model file, store, card, threshold or fingerprint. Reuses the loss diagnosis'
loaders and estimators (`scripts/diagnosis/estimate_error.py`, `_ee_common.py`)
so a number here and the number in `docs/research/loss_diagnosis/` come from
the same code.

Run (from the repo root, on a tree WITH `tb_correction.patch` applied for
`tb`; the other parts need no patch):

    python3 scripts/diagnosis/card_v3_measure.py tb
    python3 scripts/diagnosis/card_v3_measure.py avg
    python3 scripts/diagnosis/card_v3_measure.py ml

Evidence rules honoured here (same as the diagnosis):
* 2026-01-01..2026-08-27 is sealed. Every loader drops a sealed row on its
  date column before any other field is read (`_ee_common.guard`); nothing
  here opens a sealed outcome.
* 2025 is not used.
* Every "what the record would have been" figure is HINDSIGHT on the same
  published bets and licenses nothing beyond a forward test.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ee_common as C  # noqa: E402

sys.path.insert(0, C.ROOT)
os.chdir(C.ROOT)

import estimate_error as EE  # noqa: E402
from src.analysis import best_bets_card, playerprops  # noqa: E402

OUT_DIR = C.p("docs", "decisions", "card_v3")


# ---------------------------------------------------------------------------
# Patch 1: total bases over 0.5
# ---------------------------------------------------------------------------

def _legacy_tb05_wrapper(current):
    """`probability_over` as it was before `tb_correction.patch`: total bases
    over 0.5 through the uncorrected convolution. Everything else is the
    current function, unchanged, so the only difference between the two arms
    is the one branch the patch edits."""

    def legacy(market, line, rates, expected_pa, pitcher_factor=1.0, rho=None):
        if market == "batter_total_bases" and int(math.floor(line)) + 1 == 1:
            adjusted = dict(rates)
            for key in ("single", "double", "triple", "home_run"):
                adjusted[key] = rates[key] * pitcher_factor
            dist = playerprops.total_bases_distribution(adjusted, expected_pa)
            return sum(dist[1:])
        return current(market, line, rates, expected_pa, pitcher_factor, rho)

    return legacy


@contextlib.contextmanager
def _arm(name):
    """`before` swaps in the legacy TB 0.5 branch; `after` is the tree as is."""
    current = playerprops.probability_over
    if name == "before":
        playerprops.probability_over = _legacy_tb05_wrapper(current)
    try:
        yield
    finally:
        playerprops.probability_over = current


def _quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **kw)


def tb_hist_2024():
    """2024 out of sample (no 2024 outcome was used to fit anything here):
    the card's model on listed starters, regular season, two history regimes.
    Pairs the legacy and patched price on identical player-games."""
    box23 = C.load_box_archive(2023)
    lu23 = [r for r in C.load_lineups() if str(r["date"])[:4] == "2023"]
    pa23 = EE.pa_dists_from_lineups(lu23, box23)
    runs = {}
    for arm in ("before", "after"):
        with _arm(arm):
            runs[arm] = _quiet(EE.run_hist, 2024, pa23)
    out = {}
    for regime in ("full", "short"):
        b = [r for r in runs["before"][regime] if r["market"] == "batter_total_bases" and r["line"] == 0.5]
        a = [r for r in runs["after"][regime] if r["market"] == "batter_total_bases" and r["line"] == 0.5]
        if len(a) != len(b):
            raise SystemExit(f"arms disagree on the 2024 {regime} row set: {len(b)} vs {len(a)}")
        pair = []
        for rb, ra in zip(b, a):
            if (rb["date"], rb["y"], rb["pa"], rb["slot"]) != (ra["date"], ra["y"], ra["pa"], ra["slot"]):
                raise SystemExit("arms are not row-aligned")
            pair.append({"date": rb["date"], "y": rb["y"], "p_before": rb["p_card"], "p_after": ra["p_card"]})
        d_ll = C.clustered_boot(pair, lambda r: C.ll(r["p_before"], r["y"]) - C.ll(r["p_after"], r["y"]))
        bias_b = C.clustered_boot(pair, lambda r: r["p_before"] - r["y"])
        bias_a = C.clustered_boot(pair, lambda r: r["p_after"] - r["y"])
        shift = C.clustered_boot(pair, lambda r: r["p_after"] - r["p_before"])
        out[regime] = {
            "n": len(pair),
            "mean_p_before": C.mean(r["p_before"] for r in pair),
            "mean_p_after": C.mean(r["p_after"] for r in pair),
            "hit_rate": C.mean(r["y"] for r in pair),
            "shift_pts": [100 * x for x in shift],
            "bias_before_pts": [100 * x for x in bias_b],
            "bias_after_pts": [100 * x for x in bias_a],
            "ll_before": C.mean(C.ll(r["p_before"], r["y"]) for r in pair),
            "ll_after": C.mean(C.ll(r["p_after"], r["y"]) for r in pair),
            "ll_gain": list(d_ll),
        }
    return out


def tb_published_2026():
    """The graded published TB 0.5 bets, re-priced through the patched path.

    The shift is measured on the REPLAYED number (the diagnosis' own method,
    `estimate_error.run_published` + the pool replay's inputs) and applied to
    the ledger's published `our_probability`. The gates are then re-run on
    the shifted number to see which entries the card would still have shown.
    """
    ctx = EE.Ctx2026()
    pub = _quiet(EE.run_published, ctx)
    by_date_rows, _ = EE.pregame_rows_by_date()
    results = []
    league_cache = {}
    for e in pub:
        if e["market"] != "batter_total_bases" or float(e["line"]) != 0.5:
            continue
        date = e["date"]
        C.guard(date)
        lg = league_cache.setdefault(date, ctx.league(date))
        prior = EE.propboard._prior_lines(ctx.by_name.get(e["player"]) or [], date)
        slot = None
        if e["src"] == "batting_slot":
            slot = ctx.slots_by_date_name.get(date, {}).get(e["player"])
        base = dict(market="batter_total_bases", line=0.5, batter_lines=prior, league=lg)
        with _arm("before"):
            p_old = playerprops.price_prop(**base, batting_slot=slot)["probability"]
        p_new = playerprops.price_prop(**base, batting_slot=slot)["probability"]
        p_hits = playerprops.price_prop(**dict(base, market="batter_hits"), batting_slot=slot)["probability"]
        results.append(dict(e, p_old_replay=p_old, p_new_replay=p_new, p_hits_path=p_hits,
                            slot_used=slot))
    return pub, results


def _gate_recheck(e, new_our):
    """Fails of the V2 gates for this entry with `new_our` as our number.
    Quote age is set to zero because the question is about our number, not
    about the quote; G1 is not applicable (the bet was unstarted when shown)."""
    from datetime import datetime, timezone
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cand = {"kind": "prop", "price": e["price"], "market_probability": e["mkt"],
            "our_probability": new_our, "books": 99, "observed_utc": now,
            "has_started": False, "season_games": 99}
    return best_bets_card.failed_gates(cand, now=now, params=best_bets_card.V2)


def tb_report():
    hist = tb_hist_2024()
    pub, tb = tb_published_2026()
    n = len(tb)
    over = [r for r in tb if r["side"] == "Over"]
    for r in tb:
        sgn = 1 if r["side"] == "Over" else -1
        r["shift_side"] = sgn * (r["p_new_replay"] - r["p_old_replay"])
        r["our_new"] = r["our"] + (r["p_new_replay"] - r["p_old_replay"]) if r["side"] == "Over" \
            else r["our"] - (r["p_new_replay"] - r["p_old_replay"])
        fails = _gate_recheck(r, r["our_new"])
        r["new_fails"] = fails
        hard = set(fails) - {"G3_STALE", "G7_VALUE"}
        r["new_status"] = "pick" if not fails else ("fill-eligible" if not hard else "dropped")
    dropped = [r for r in tb if r["new_status"] == "dropped"]
    demoted = [r for r in tb if r["new_status"] == "fill-eligible" and r["entry_class"] == "pick"]
    kept = [r for r in tb if r["new_status"] in ("pick",) or (r["new_status"] == "fill-eligible" and r["entry_class"] == "fill")]

    def wl(rows):
        w = sum(1 for r in rows if r["y"])
        return f"{w}-{len(rows) - w}", round(sum(r["profit"] for r in rows), 2)

    all_pub = len(pub)
    mean_shift_all = sum(r["shift_side"] for r in tb) / all_pub if all_pub else None
    out = {
        "hist_2024": hist,
        "published_2026": {
            "n_published_graded_props": all_pub,
            "n_tb05": n,
            "n_tb05_over": len(over),
            "mean_shift_side_pts_per_tb05_bet": 100 * sum(r["shift_side"] for r in tb) / n,
            "mean_shift_side_pts_averaged_over_all_props": 100 * mean_shift_all,
            "equals_hits_path_max_abs_diff": max(abs(r["p_new_replay"] - r["p_hits_path"]) for r in tb),
            "status_counts": {k: sum(1 for r in tb if r["new_status"] == k) for k in ("pick", "fill-eligible", "dropped")},
            "was_pick": sum(1 for r in tb if r["entry_class"] == "pick"),
            "was_fill": sum(1 for r in tb if r["entry_class"] == "fill"),
            "dropped_wl_units_HINDSIGHT": wl(dropped),
            "demoted_pick_to_fill_wl_units_HINDSIGHT": wl(demoted),
            "all_tb05_wl_units": wl(tb),
            "remaining_if_dropped_removed_wl_units_HINDSIGHT": wl([r for r in tb if r["new_status"] != "dropped"]),
            "mean_our_old": 100 * sum(r["our"] for r in tb) / n,
            "mean_our_new": 100 * sum(r["our_new"] for r in tb) / n,
            "mean_market": 100 * sum(r["mkt"] for r in tb) / n,
            "hit_rate": sum(r["y"] for r in tb) / n,
        },
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "measured_tb_correction.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float, sort_keys=True)
    return out


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=("tb",))
    args = ap.parse_args(argv)
    if args.part == "tb":
        print(json.dumps(tb_report(), indent=1, default=float, sort_keys=True))


if __name__ == "__main__":
    main()
