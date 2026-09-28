"""P3 / Lane A behaviour-level regression on REAL published rows, V1 and V2.

OLD = src/appstate/card_ledger.py at 221682eb (before Lane A's bb15ffa3).
NEW = the working tree (bb15ffa3 + 60646612).
Same inputs to both: an exact copy of src/cli.py's nested _results_and_box_rows.

Level 1  per-entry grade, old vs new, every published entry in every store.
Level 2  end-to-end settle on temp copies (V2 stores via settle_v2, V1 via
         settle): W/L/P/units per date must be identical; only VOID->UNRESOLVED
         for genuinely missing data is allowed to differ.
Level 3  re-entry on real rows (NEW only): one game's result withheld on the
         first pass -> UNRESOLVED; second pass with the result -> settles
         exactly once, one linked row added; final tallies equal a one-pass
         settle; readers count it once; a third pass is a no-op; chain verifies.
Nothing is written to any real store: every settle runs on a temp copy.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

ROOT = r"C:\Users\KC\Desktop\aisportsanalysis"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from src.appstate import card_ledger as new  # noqa: E402
from src.pipeline import boxscores as boxscores_mod, history  # noqa: E402
from src.paths import processed_path  # noqa: E402

old_src = subprocess.run(["git", "show", "221682eb:src/appstate/card_ledger.py"],
                         capture_output=True, text=True, cwd=ROOT, encoding="utf-8").stdout
tmpdir = tempfile.mkdtemp()
old_path = os.path.join(tmpdir, "card_ledger_pre.py")
open(old_path, "w", encoding="utf-8").write(old_src)
spec = importlib.util.spec_from_file_location("card_ledger_pre", old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

_STORE = history.read_results()
_BOX = {}


def results_and_box_rows(for_date):
    """Exact copy of src/cli.py's nested helper."""
    if not _STORE:
        return None, []
    by_pk = {}
    for row in _STORE.values():
        if str(row.get("date")) == for_date:
            pk = row.get("game_pk")
            by_pk[pk] = row
            by_pk[str(pk)] = row
            try:
                by_pk[int(pk)] = row
            except (TypeError, ValueError):
                pass
    yr = for_date[:4]
    if yr not in _BOX:
        try:
            _BOX[yr] = boxscores_mod.read(processed_path(f"boxscores_{yr}.jsonl"))
        except boxscores_mod.BoxscoresError:
            _BOX[yr] = []
    return by_pk, _BOX[yr]


V2_STORES = {"v2": new.CARD_STORE_V2, "shadow-a": new.CARD_STORE_V2_SHADOW_A,
             "shadow-c": new.CARD_STORE_V2_SHADOW_C, "shadow-e": new.CARD_STORE_V2_SHADOW_E}
V1_STORE = new.CARD_STORE


def published(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return [r for r in rows if r.get("kind") == new.KIND_PUBLISHED and r.get("date")]


def temp_store(rows, name):
    p = os.path.join(tmpdir, name)
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


def grade_one(mod, entry, by_pk, box_index):
    if entry.get("kind") == "prop":
        return mod.grade_prop_pick(entry, box_index)
    lk = entry.get("game_id") if entry.get("sport") else entry.get("game_pk")
    res = by_pk.get(lk) or by_pk.get(str(lk)) or {}
    if entry.get("market") == "total":
        return mod.grade_total_pick(entry, res)
    return mod.grade_pick(entry, res)


def tally(row, keys=("wins", "losses", "pushes", "profit_units")):
    return tuple(round(row.get(k) or 0, 6) if isinstance(row.get(k), float) else row.get(k) for k in keys)



def tail_chain_ok(path, n_appended):
    """The temp copy holds published rows only (settled rows stripped), so its
    chain is broken by construction before any settle runs. What this check
    can prove is that the rows the settle passes APPENDED chain correctly:
    each appended row's prev_hash is the row_hash of the row physically before
    it, and each row_hash recomputes from its own payload."""
    from src.ledger.chain import row_hash, ROW_HASH_FIELD, PREV_HASH_FIELD
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    tail = rows[-(n_appended + 1):]
    for prev, cur in zip(tail, tail[1:]):
        if cur.get(PREV_HASH_FIELD) != prev.get(ROW_HASH_FIELD):
            return False
        payload = {k: v for k, v in cur.items() if k not in (ROW_HASH_FIELD, PREV_HASH_FIELD)}
        if row_hash(payload, cur[PREV_HASH_FIELD]) != cur[ROW_HASH_FIELD]:
            return False
    return True

fails = []
print("=== LEVEL 1: per-entry grade, old vs new ===")
grand = Counter()
for name, path in list(V2_STORES.items()) + [("v1", V1_STORE)]:
    c = Counter()
    for r in published(path):
        by_pk, box = results_and_box_rows(r["date"])
        if by_pk is None:
            c["no_inputs"] += 1
            continue
        bo, bn = old._index_prop_box_rows(box), new._index_prop_box_rows(box)
        if name == "v1":
            entries = (r.get("picks") or []) + (r.get("prop_picks") or []) + (r.get("total_picks") or [])
        else:
            entries = (r.get("all_bets") or []) + (r.get("withdrawn") or [])
        for e in entries:
            go, gn = grade_one(old, e, by_pk, bo), grade_one(new, e, by_pk, bn)
            ko = (go.get("result"), go.get("profit_units"))
            kn = (gn.get("result"), gn.get("profit_units"))
            if ko == kn:
                c["identical"] += 1
            else:
                c[f"{ko[0]}/{ko[1]} -> {kn[0]}/{kn[1]}"] += 1
    print(f"  {name:<9} {dict(c)}")
    grand.update(c)
allowed = {"identical", "no_inputs", "VOID/0.0 -> UNRESOLVED/0.0"}
unexpected = {k: v for k, v in grand.items() if k not in allowed}
print("  ALL:", dict(grand))
print("  unexpected transitions:", unexpected or "none")
if unexpected:
    fails.append(f"level1 unexpected {unexpected}")

print("\n=== LEVEL 2: end-to-end settle, old vs new, temp copies ===")
for name, path in list(V2_STORES.items()) + [("v1", V1_STORE)]:
    pub = published(path)
    dates = sorted({r["date"] for r in pub})
    diffs = []
    same = 0
    for mod_name, mod in (("old", old), ("new", new)):
        tp = temp_store(pub, f"{name}_{mod_name}_l2.jsonl")
        outs = {}
        for d in dates:
            by_pk, box = results_and_box_rows(d)
            fn = mod.settle_v2 if name != "v1" else mod.settle
            row = fn(d, by_pk or {}, prop_box_rows=box, path=tp)
            outs[d] = row
        if mod_name == "old":
            old_out = outs
        else:
            new_out = outs
    for d in dates:
        o, n = old_out[d], new_out[d]
        if o is None and n is None:
            same += 1
            continue
        if (o is None) != (n is None):
            diffs.append((d, "one side None", o and tally(o), n and tally(n)))
            continue
        if name == "v1":
            keys = ("wins", "losses", "pushes", "profit_units", "prop_wins", "prop_losses", "total_wins", "total_losses")
        else:
            keys = ("wins", "losses", "pushes", "profit_units")
        if tally(o, keys) == tally(n, keys):
            same += 1
        else:
            diffs.append((d, tally(o, keys), tally(n, keys)))
    print(f"  {name:<9} dates {len(dates)}: W/L/P/units identical on {same}; differing {len(diffs)} {diffs[:3]}")
    if diffs:
        fails.append(f"level2 {name} {diffs[:3]}")

print("\n=== LEVEL 3: re-entry on real rows (NEW only) ===")
for name, path in list(V2_STORES.items()) + [("v1", V1_STORE)]:
    pub = published(path)
    # the date with the most gradable game entries whose result exists
    best = None
    for r in pub:
        by_pk, box = results_and_box_rows(r["date"])
        if not by_pk:
            continue
        ents = ((r.get("all_bets") or []) if name != "v1" else (r.get("picks") or []))
        gpks = [e.get("game_pk") for e in ents if e.get("kind") != "prop" and e.get("game_pk") in by_pk]
        if gpks and (best is None or len(gpks) > len(best[1])):
            best = (r["date"], gpks)
    if best is None:
        print(f"  {name:<9} no date with a gradable game entry -- skipped")
        continue
    d, gpks = best
    by_pk, box = results_and_box_rows(d)
    withheld = gpks[0]
    partial = {k: v for k, v in by_pk.items() if k not in (withheld, str(withheld))}
    try:
        partial.pop(int(withheld), None)
    except (TypeError, ValueError):
        pass
    settle = new.settle_v2 if name != "v1" else new.settle
    one = temp_store(pub, f"{name}_onepass.jsonl")
    two = temp_store(pub, f"{name}_twopass.jsonl")
    r_one = settle(d, by_pk, prop_box_rows=box, path=one)
    r1 = settle(d, partial, prop_box_rows=box, path=two)
    r2 = settle(d, by_pk, prop_box_rows=box, path=two)
    r3 = settle(d, by_pk, prop_box_rows=box, path=two)
    settled_rows = [x for x in new._ledger(two).read() if x.get("kind") == new.KIND_SETTLED and x.get("date") == d]
    if name != "v1":
        rec_two = new.record_v2(path=two)["combined"]
        rec_one = new.record_v2(path=one)["combined"]
        unresolved_1 = r1.get("unresolved") if r1 else None
    else:
        rec_two = new.record(path=two)
        rec_one = new.record(path=one)
        unresolved_1 = sum(1 for p in (r1.get("picks") or []) if p.get("result") == new.RESULT_UNRESOLVED) if r1 else None
    k = ("wins", "losses", "pushes", "n_staked", "profit_units")
    ok = (r1 is not None and (unresolved_1 or 0) >= 1 and r2 is not None and r3 is None
          and len(settled_rows) == 2 and settled_rows[1].get("supersedes_row_hash") == settled_rows[0].get("row_hash")
          and tally(r2) == tally(r_one)
          and tuple(rec_two.get(x) for x in k) == tuple(rec_one.get(x) for x in k)
          and tail_chain_ok(two, n_appended=2))
    print(f"  {name:<9} date {d}, withheld game {withheld}: pass1 unresolved={unresolved_1}, "
          f"pass2 {tally(r2) if r2 else None} vs one-pass {tally(r_one) if r_one else None}, pass3 {'no-op' if r3 is None else 'APPENDED'}, "
          f"settled rows {len(settled_rows)}, linked={settled_rows[1].get('supersedes_row_hash') == settled_rows[0].get('row_hash') if len(settled_rows) == 2 else None}, "
          f"reader twopass {tuple(rec_two.get(x) for x in k)} == onepass {tuple(rec_one.get(x) for x in k)}: "
          f"{tuple(rec_two.get(x) for x in k) == tuple(rec_one.get(x) for x in k)} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        fails.append(f"level3 {name}")

shutil.rmtree(tmpdir, ignore_errors=True)
print("\nRESULT:", "PASS" if not fails else f"FAIL {fails}")
