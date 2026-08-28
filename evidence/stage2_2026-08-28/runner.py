"""Stage 2: full 2023-24 discovery rerun on fixed code, all 11 detectors.

Pure computation, no LLM. Dumps JSON artifacts for the report:
  stage2_selections.json, stage2_results.json, stage2_gates.json,
  stage2_robustness.json (battery for every FDR survivor).
"""
import json, statistics, sys, time
from collections import Counter, defaultdict
sys.path.insert(0, '/home/user/aisportsanalysis')
from src.detect import base, detectors
from src.model import discovery, family, selections
from src.pipeline import backfill, bullpen, history, pitchers, rebuilt, lineup_store
from src.pipeline import lineups as lu

OUT = '/tmp/claude-0/-home-user-aisportsanalysis/9c0f9e08-ff18-5c32-af77-0510bde0a7a4/scratchpad/'
base.clear_registry(); detectors.register_defaults()
store = history.read_results(); logs = pitchers.read_logs()
rows_all = list(store.values() if isinstance(store, dict) else store)
posted = lineup_store.read()
hands = lu._read_json(lu.DEFAULT_HANDEDNESS, {})
pen_log = bullpen.read_log()
t0 = time.time()

# Monthly cutoffs: each game reads its month's first-day snapshot (under-informed,
# never over-informed).
cutoffs = [f"{y}-{m:02d}-01" for y in (2023, 2024) for m in range(4, 11)]
snaps = rebuilt.build_snapshots(cutoffs)
print(f"snapshots: {len(snaps)} in {time.time()-t0:.0f}s", flush=True)

def acc_for(date):
    keys = [c for c in cutoffs if c <= date]
    return snaps[keys[-1]] if keys else snaps[cutoffs[0]]

all_sel = []
counts = Counter()
for season in (2023, 2024):
    games = [r for r in rows_all if r["date"].startswith(str(season))]
    pairs = selections.index_price_pairs(backfill.price_pair(season))
    pen_by = {}
    for d in sorted({g["date"] for g in games}):
        for tm in {t for g in games if g["date"] == d
                   for t in (g["away_team"], g["home_team"]) if t}:
            pen_by[(tm, d)] = bullpen.team_workload(pen_log, tm, d)
    out = selections.build(games, store, logs, pairs, bullpen_by_team=pen_by,
                           acc_for_date=acc_for, lineups_by_pk=posted,
                           handedness=hands)
    all_sel += out["selections"]
    for k, v in out["counts"].items():
        counts[k] += v
    print(f"{season}: {len(out['selections'])} selections "
          f"{dict(out['counts'])} ({time.time()-t0:.0f}s)", flush=True)

json.dump(all_sel, open(OUT + 'stage2_selections.json', 'w'))
print("TOTAL:", dict(counts), flush=True)
print("by detector:", dict(Counter(s['detector'] for s in all_sel)), flush=True)

by_det = defaultdict(list)
for s in all_sel:
    by_det[s["detector"]].append(s)
results = [discovery.evaluate(name, by_det[name]) for name in sorted(by_det)]
json.dump(results, open(OUT + 'stage2_results.json', 'w'))

gates = family.apply_gates([{"name": r["detector"], "p": r["p"],
                             "effect": r["effect"] or 0} for r in results])
json.dump(gates, open(OUT + 'stage2_gates.json', 'w'))
print("\nGATES:", gates["summary"], flush=True)
survivors = [e["name"] for e in gates["passed"]]
print("survivors:", survivors, flush=True)

# ---- Stage 3B battery for every survivor, mechanical part -----------------
def eff(sub):
    d = [(1.0 if s["won"] else 0.0) - s["implied"] for s in sub]
    return (len(sub), statistics.mean(d) if d else None)

def ci_p(sub):
    d = [dict(s, _diff=(1.0 if s["won"] else 0.0) - s["implied"]) for s in sub]
    e = statistics.mean([x["_diff"] for x in d])
    ci = discovery.clustered_bootstrap(
        d, lambda smp: statistics.mean([x["_diff"] for x in smp]))
    p = discovery.clustered_two_sided_p(e, d)
    return e, ci, p

battery = {}
for name in survivors:
    rows = by_det[name]
    picked = lambda s: s["home_team"] if s["side"] == "home" else s["away_team"]
    by_team = defaultdict(list)
    for s in rows:
        by_team[picked(s)].append(s)
    contrib = sorted(((eff(sub)[1] * len(sub), t) for t, sub in by_team.items()),
                     reverse=True)
    top5 = {t for _, t in contrib[:5]}
    cuts = {
        "full": rows,
        "no_top5_teams": [s for s in rows if picked(s) not in top5],
        "books_ge_10": [s for s in rows if s["books"] >= 10],
        "no_longshots": [s for s in rows if s["implied"] >= 0.40],
        "favorites": [s for s in rows if s["implied"] > 0.5],
        "underdogs": [s for s in rows if s["implied"] <= 0.5],
        "s2023": [s for s in rows if s["date"].startswith("2023")],
        "s2024": [s for s in rows if s["date"].startswith("2024")],
        "all_cuts": [s for s in rows if picked(s) not in top5
                     and s["books"] >= 10 and s["implied"] >= 0.40],
    }
    entry = {"top5_teams": sorted(top5)}
    for label, sub in cuts.items():
        if len(sub) < 25:
            entry[label] = {"n": len(sub), "note": "too few"}
            continue
        e, ci, p = ci_p(sub)
        entry[label] = {"n": len(sub), "effect": round(e, 5), "p": round(p, 5),
                        "ci": [ci.get("low"), ci.get("high")],
                        "zero_in_ci": (ci.get("low") is not None
                                       and ci["low"] <= 0 <= ci["high"])}
    # dose-response by surprise band
    dose = {}
    for lo, hi in ((0, 1.5), (1.5, 2.5), (2.5, 99)):
        sub = [s for s in rows if s.get("surprise") and lo <= s["surprise"] < hi]
        n, e = eff(sub)
        dose[f"{lo}-{hi}"] = {"n": n, "effect": round(e, 5) if e is not None else None}
    entry["dose_response"] = dose
    battery[name] = entry
    print(f"\nbattery[{name}]:", json.dumps(entry, indent=1)[:600], flush=True)

json.dump(battery, open(OUT + 'stage2_robustness.json', 'w'))
print(f"\nDONE in {time.time()-t0:.0f}s", flush=True)
