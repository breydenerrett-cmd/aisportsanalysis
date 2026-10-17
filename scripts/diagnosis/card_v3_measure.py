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
from collections import Counter, defaultdict

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
# Patches 2 and 4: the price a graded entry could have been taken at
# ---------------------------------------------------------------------------

def _boards():
    """Per graded V2 entry: the board at the quote (`bl`) and the newest
    board at or before `locked_at` that is newer than the quote (`bp`),
    rebuilt from the capture stores with the diagnosis' own `prices.py`
    machinery (same event matching, same two-sided rules)."""
    import prices as P
    cards = P.load_cards()
    graded = P.graded_entries(cards)
    by_pk, _ = P.event_map()
    pidx, gidx = P.PropIndex(), P.GameIndex()
    out = []
    for e in graded:
        prop = e.get("kind") == "prop"
        side = e.get("side")
        rec = {"entry": e, "bl": None, "bp": None, "absence": None}
        out.append(rec)
        if side not in P.OTHER or e.get("price") is None:
            rec["absence"] = "NO_SIDE_OR_PRICE"
            continue
        ev = P.event_for(e, by_pk)
        if ev is None or ev == P.AMBIGUOUS:
            rec["absence"] = "NO_EVENT" if ev is None else "AMBIGUOUS_EVENT"
            continue
        if prop:
            series = pidx.series((ev, e.get("player"), e.get("market"), float(e.get("line"))))
        else:
            series = list(gidx.series(ev))
        obs = P._t(e.get("observed_utc"))
        hit = P._nearest(series, obs) if (series and obs) else None
        if hit is None:
            rec["absence"] = "QUOTE_INSTANT_NOT_IN_STORE"
            continue
        _d, t_lock, _inst, books_lock = hit
        rec["bl"] = P.board(books_lock, side, prop=prop)
        locked = P._t(e.get("locked_at"))
        if locked is not None:
            prior = [x for x in series if x[0] <= locked]
            if prior and prior[-1][0] > t_lock:
                rec["bp"] = P.board(prior[-1][2], side, prop=prop)
                rec["bp_t"] = prior[-1][0]
    return P, out


def _mean_dec(P, board):
    vals = [P.dec(p) for p in (board.get("prices") or {}).values()]
    vals = [v for v in vals if v]
    return sum(vals) / len(vals) if vals else None


def avg_report(P=None, recs=None):
    """Patch 2: the 178 graded entries re-graded at the board's mean decimal
    price at the quote. HINDSIGHT / retrospective: the ledger never recorded
    the average, so it is rebuilt from the capture stores; entries whose board
    cannot be rebuilt stay at their best price (the patch's own fallback)."""
    if recs is None:
        P, recs = _boards()
    rows = []
    for r in recs:
        e = r["entry"]
        won = e["result"] == "WIN"
        bl = r["bl"]
        min_books = 2 if e.get("kind") == "prop" else 6
        avg = None
        if bl and bl.get("two_sided", 0) >= min_books:
            avg = _mean_dec(P, bl)
        best = e["profit_units"]
        at_avg = ((avg - 1.0) if won else -1.0) if avg else best
        # sensitivity: the diagnosis' other definition, mean implied probability
        alt = None
        if bl and bl.get("two_sided") and bl.get("avg_price") is not None:
            d = P.dec(bl["avg_price"])
            alt = ((d - 1.0) if won else -1.0) if d else None
        rows.append({"kind": e["kind"], "market": e.get("market"), "class": e.get("entry_class"),
                     "withdrawn": bool(e.get("withdrawn")), "won": won, "best": best,
                     "avg": at_avg, "has_avg": avg is not None, "alt": alt,
                     "best_dec": P.dec(e["price"]), "avg_dec": avg})

    def agg(sel):
        s = [x for x in rows if sel(x)]
        built = [x for x in s if x["has_avg"]]
        return {"n": len(s), "n_with_rebuilt_average": len(built),
                "units_at_best": round(sum(x["best"] for x in s), 2),
                "units_at_average": round(sum(x["avg"] for x in s), 2),
                "units_at_best_on_rebuilt_subset": round(sum(x["best"] for x in built), 2),
                "units_at_average_on_rebuilt_subset": round(sum(x["avg"] for x in built), 2),
                "units_at_mean_implied_prob_on_rebuilt_subset": round(
                    sum(x["alt"] for x in built if x["alt"] is not None), 2),
                "mean_best_decimal": round(sum(x["best_dec"] for x in built) / len(built), 4) if built else None,
                "mean_average_decimal": round(sum(x["avg_dec"] for x in built) / len(built), 4) if built else None}

    out = {"all_178": agg(lambda x: True),
           "props": agg(lambda x: x["kind"] == "prop"),
           "moneylines": agg(lambda x: x["kind"] == "game"),
           "picks": agg(lambda x: x["class"] == "pick"),
           "fills": agg(lambda x: x["class"] == "fill"),
           "shown_not_withdrawn": agg(lambda x: not x["withdrawn"]),
           "withdrawn": agg(lambda x: x["withdrawn"]),
           "_note": "HINDSIGHT. Average = mean DECIMAL price over the books on the board at the "
                    "quote instant (the patch's definition). Entries whose board cannot be "
                    "rebuilt keep their best-price grade in the all-entries units."}
    return out


def ml_lock_report(P=None, recs=None):
    """Patch 4: moneyline entries re-priced at the board that was on the
    screen at `locked_at` (the newest capture at or before the lock that is
    newer than the quote). HINDSIGHT; rebuilt from the capture stores."""
    if recs is None:
        P, recs = _boards()
    ml = [r for r in recs if r["entry"].get("kind") == "game"]
    rows = []
    for r in ml:
        e, bp = r["entry"], r["bp"]
        won = e["result"] == "WIN"
        row = {"class": e.get("entry_class"), "won": won, "price": e["price"],
               "best": e["profit_units"], "has_lock_board": False}
        if bp and bp.get("two_sided", 0) >= 6:
            prices = list((bp.get("prices") or {}).values())
            lock_best = bp["best_price"]
            row.update({
                "has_lock_board": True,
                "lock_best": lock_best,
                "graded_price_on_board": any(P.dec(p) >= P.dec(e["price"]) for p in prices),
                "cents_vs_graded": P.cents(lock_best) - P.cents(e["price"]),
                "in_band_at_lock": -160 <= lock_best <= 250,
                "at_lock": ((P.dec(lock_best) - 1.0) if won else -1.0),
            })
        rows.append(row)

    def agg(sel):
        s = [x for x in rows if sel(x)]
        L = [x for x in s if x["has_lock_board"]]
        kept = [x for x in L if x["in_band_at_lock"]]
        gone = [x for x in L if not x["in_band_at_lock"]]
        return {
            "n": len(s), "n_with_newer_board_before_lock": len(L),
            "graded_price_still_on_board": sum(1 for x in L if x["graded_price_on_board"]),
            "graded_price_not_on_board": sum(1 for x in L if not x["graded_price_on_board"]),
            "units_graded_on_those": round(sum(x["best"] for x in L), 2),
            "units_at_lock_best_on_those": round(sum(x["at_lock"] for x in L), 2),
            "mean_cents_lock_best_minus_graded": (round(sum(x["cents_vs_graded"] for x in L) / len(L), 1) if L else None),
            "out_of_band_at_lock_would_be_withdrawn": len(gone),
            "out_of_band_units_graded": round(sum(x["best"] for x in gone), 2),
            "out_of_band_wl": f"{sum(1 for x in gone if x['won'])}-{sum(1 for x in gone if not x['won'])}",
            "units_graded_on_kept": round(sum(x["best"] for x in kept), 2),
            "units_at_lock_best_on_kept": round(sum(x["at_lock"] for x in kept), 2),
        }

    return {"moneyline_fills": agg(lambda x: x["class"] == "fill"),
            "moneyline_picks": agg(lambda x: x["class"] == "pick"),
            "moneyline_all": agg(lambda x: True),
            "_note": "HINDSIGHT. Lock board = newest multibook capture at or before locked_at that "
                     "is newer than the quote. 'Would be withdrawn' = the lock-time best price "
                     "is outside the registered band -160..+250 (G4), so the patch would "
                     "withdraw the fill instead of locking it at an unavailable price."}


def price_reports():
    P, recs = _boards()
    out = {"avg": avg_report(P, recs), "ml_lock": ml_lock_report(P, recs)}
    os.makedirs(OUT_DIR, exist_ok=True)
    for key, name in (("avg", "measured_grade_average_odds.json"),
                      ("ml_lock", "measured_ml_fill_lock_price.json")):
        with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as fh:
            json.dump(out[key], fh, indent=1, default=float, sort_keys=True)
    return out


def stale_report():
    """Patch 3: how many publish runs the real `stale_board` would have
    flagged, from the loss diagnosis' replay of the prop candidate pool at
    each publish instant (`data/research/loss_diagnosis/prop_replay_pool.
    jsonl.gz`, built by `scripts/diagnosis/selection.py replay`: 164 of the
    175 published runs).

    PROP POOL ONLY: the replay has no game candidates, and the patch's
    definition counts a fresh game quote as a fresh board. So a run flagged
    here could be called fresh by the patch if a game quote was within the
    hour (the hourly full-slate capture prices games and props together, so
    the two agree most of the time, but this is an estimate, not the
    patch's exact output). The ledger's own `stale_board` field was `None` on
    every published row.
    """
    rows = [r for r in C.iter_jsonl(C.p("data", "research", "loss_diagnosis",
                                       "prop_replay_pool.jsonl.gz"))
            if r.get("source") == "run"]
    runs = defaultdict(list)
    for r in rows:
        C.guard(r["date"])
        runs[(r["date"], r["run"])].append(r)
    flags = {}
    for key, pool in runs.items():
        now = C.parse_utc(pool[0]["now"])
        ages = [(now - C.parse_utc(r["observed_utc"])).total_seconds()
                for r in pool if C.parse_utc(r.get("observed_utc")) is not None]
        flags[key] = (min(ages) if ages else None)
    stale = {k: v for k, v in flags.items() if v is None or v > 3600}
    by_date = defaultdict(list)
    for (date, _run), v in flags.items():
        by_date[date].append(v is None or v > 3600)
    published = [r for r in C.iter_jsonl(C.p("evidence", "cards_v2.jsonl"))
                 if r.get("kind") == "card_published"]
    out = {
        "published_rows_in_ledger": len(published),
        "recorded_stale_board_flags_in_ledger": sum(1 for r in published if r.get("stale_board")),
        "runs_replayed": len(flags),
        "runs_stale_by_registration_definition_prop_pool": len(stale),
        "share_of_replayed_runs": round(len(stale) / len(flags), 3) if flags else None,
        "dates": len(by_date),
        "dates_with_at_least_one_stale_run": sum(1 for v in by_date.values() if any(v)),
        "dates_with_every_replayed_run_stale": sum(1 for v in by_date.values() if all(v)),
        "stale_runs_by_utc_hour": dict(sorted(Counter(
            (sorted(runs[k], key=lambda r: r["now"])[0]["now"][11:13]) for k in stale).items())),
        "_note": "ESTIMATE from the prop pool only; the ledger recorded None on every row.",
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "measured_stale_board_real.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float, sort_keys=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=("tb", "avg", "ml", "stale"))
    args = ap.parse_args(argv)
    if args.part == "stale":
        print(json.dumps(stale_report(), indent=1, default=float, sort_keys=True))
    elif args.part == "tb":
        print(json.dumps(tb_report(), indent=1, default=float, sort_keys=True))
    else:
        out = price_reports()
        print(json.dumps(out["avg" if args.part == "avg" else "ml_lock"], indent=1,
                         default=float, sort_keys=True))


if __name__ == "__main__":
    main()
