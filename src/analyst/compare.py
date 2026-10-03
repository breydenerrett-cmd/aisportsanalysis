"""`analyst compare`: arm A against arm B, by sport and market family.

WHAT IT ANSWERS
---------------
Does handing the analyst the situation layer (arm B) change how its calls do, compared with the
analyst that reads only the matchup statistics (arm A)? For each sport and each market family it
reports, side by side: how many calls each arm made, how many were bets and how many passes, the
results (W-L-P, voids, unresolved), units at the published prices, and calibration (how close the
probabilities the arm put on its bets were to how often they won). Where the two arms differ in
what they said, it counts that too.

THE SMALL-SAMPLE RULE IS THE RECORD'S, AND IT APPLIES TO EVERY RATE
-------------------------------------------------------------------
A win rate, a return and a calibration figure appear for an arm in a family only at 30 graded
calls (`config min_graded_for_rates`); below that they are null and the reason says how many there
were. Counts are always shown. The difference between the arms is shown only when BOTH arms clear
the bar. A table of twelve calls a side is a story, not a measurement.

ONLY GAMES BOTH ARMS FROZE ARE COMPARED
---------------------------------------
Arm B runs right after arm A on each game, but a game that starts between them is refused by B and
a failed call is skipped, so the two ledgers can hold different games. Comparing A's full set with
B's partial one would compare different slates. So the comparison is over PAIRED games (published
in both ledgers) and says how many were left out and why: only in A, only in B. Prices can differ by
minutes between the arms (each arm's calls are graded at the price it published), and the slots can
differ at the margin (a prop that appeared in between); each arm is read as published.

NOTHING HERE CALLS A MODEL, A NETWORK OR A SCHEDULE. It reads two ledgers (and their cost logs) and
checks that the file given as arm B holds only arm B's rows. It never edits a ledger.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from src import paths
from src.analyst import LABEL
from src.analyst import config as config_mod
from src.analyst import grading, situation_arm, ufc_grading
from src.analyst import ledger as mlb_ledger
from src.analyst import ufc_ledger

VERSION = "analyst_compare_v1"

TAKES = ("TAKE", "TAKE_OTHER_SIDE")
EXIT_OK, EXIT_PROBLEM = 0, 2


@dataclass(frozen=True)
class Sport:
    name: str
    ledger: Any                  # the ledger module (rows, latest_published, latest_graded, ...)
    families: Sequence[str]
    id_key: str                  # the published row's game or bout id
    title: str


SPORTS: Dict[str, Sport] = {
    "mlb": Sport("mlb", mlb_ledger, grading.FAMILIES, "game_id", "MLB games"),
    "ufc": Sport("ufc", ufc_ledger, ufc_grading.FAMILIES, "bout_id", "UFC bouts"),
}


# ---------------------------------------------------------------------------
# one arm
# ---------------------------------------------------------------------------

def _published(sport: Sport, rows: Sequence[Mapping]) -> dict:
    """{id: newest published row}: only the newest version of a game counts."""
    return sport.ledger.latest_published(rows)


def _results(sport: Sport, rows: Sequence[Mapping]) -> dict:
    """{published row_hash: {slot_id: graded call with corrections applied}}."""
    graded = sport.ledger.latest_graded(rows)
    corrections = sport.ledger.corrections_for(rows)
    return {h: sport.ledger.effective_calls(g, corrections) for h, g in graded.items()}


def _blank() -> dict:
    return {"calls": 0, "taken": 0, "taken_other_side": 0, "passes": 0, "graded": 0, "wins": 0,
            "losses": 0, "pushes": 0, "voids": 0, "unresolved": 0, "units": 0.0,
            "passes_would_have_won": 0, "passes_would_have_lost": 0, "passes_would_have_pushed": 0,
            "_cal": []}


def _tally(sport: Sport, pubs: Mapping, results: Mapping, ids: Sequence[str]) -> dict:
    """{family: raw counts and the (estimate, won) pairs for calibration} over `ids`."""
    fams = {f: _blank() for f in sport.families}
    for gid in ids:
        pub = pubs[gid]
        graded = results.get(pub["row_hash"]) or {}
        for call in pub.get("calls") or []:
            fam = (call.get("grading") or {}).get("family")
            if fam not in fams:
                continue
            f = fams[fam]
            f["calls"] += 1
            g = graded.get(call["slot_id"])
            if call["verdict"] == "PASS":
                f["passes"] += 1
                key = {"WIN": "passes_would_have_won", "LOSS": "passes_would_have_lost",
                       "PUSH": "passes_would_have_pushed"}.get(((g or {}).get("would_have") or {}).get("result"))
                if key:
                    f[key] += 1
                continue
            f["taken"] += 1
            if call["verdict"] == "TAKE_OTHER_SIDE":
                f["taken_other_side"] += 1
            res = (g or {}).get("result", grading.UNRESOLVED)
            if res == grading.WIN:
                f["wins"] += 1
            elif res == grading.LOSS:
                f["losses"] += 1
            elif res == grading.PUSH:
                f["pushes"] += 1
            elif res == grading.VOID:
                f["voids"] += 1
            else:
                f["unresolved"] += 1
            if res in (grading.WIN, grading.LOSS, grading.PUSH):
                f["graded"] += 1
                f["units"] += float((g or {}).get("profit_units") or 0.0)
            estimate = call.get("fair_estimate")
            if res in (grading.WIN, grading.LOSS) and isinstance(estimate, (int, float)) \
                    and not isinstance(estimate, bool) and 0.0 < estimate < 1.0:
                f["_cal"].append((float(estimate), 1.0 if res == grading.WIN else 0.0))
    return fams


def _shown(raw: Mapping, min_graded: int) -> dict:
    """The counts always; the rates, the units and the calibration only at `min_graded` graded
    calls (calibration at `min_graded` graded bets that carried an estimate)."""
    out = {k: v for k, v in raw.items() if not k.startswith("_")}
    decided = raw["wins"] + raw["losses"]
    cal = raw["_cal"]
    if raw["graded"] >= min_graded:
        out["win_rate"] = round(raw["wins"] / decided, 4) if decided else None
        out["units"] = round(raw["units"], 2)
        out["units_per_call"] = round(raw["units"] / raw["graded"], 4)
        out["withheld_reason"] = None
    else:
        out["win_rate"] = out["units"] = out["units_per_call"] = None
        out["withheld_reason"] = f"fewer than {min_graded} graded calls ({raw['graded']} so far)"
    if len(cal) >= min_graded:
        mean_p = sum(p for p, _ in cal) / len(cal)
        rate = sum(y for _, y in cal) / len(cal)
        out["calibration"] = {
            "calls": len(cal), "brier": round(sum((p - y) ** 2 for p, y in cal) / len(cal), 4),
            "mean_estimate": round(mean_p, 4), "actual_rate": round(rate, 4),
            "gap": round(mean_p - rate, 4), "withheld_reason": None}
    else:
        out["calibration"] = {"calls": len(cal), "brier": None, "mean_estimate": None, "actual_rate": None,
                              "gap": None,
                              "withheld_reason": f"fewer than {min_graded} graded bets with an estimate "
                                                 f"({len(cal)} so far)"}
    return out


def _difference(a: Mapping, b: Mapping) -> Optional[dict]:
    """B minus A, only when both arms have rates to subtract."""
    if a["win_rate"] is None or b["win_rate"] is None:
        return None
    out = {"win_rate": round(b["win_rate"] - a["win_rate"], 4),
           "units": round(b["units"] - a["units"], 2),
           "units_per_call": round(b["units_per_call"] - a["units_per_call"], 4)}
    ca, cb = a["calibration"], b["calibration"]
    out["brier"] = (round(cb["brier"] - ca["brier"], 4)
                    if ca["brier"] is not None and cb["brier"] is not None else None)
    return out


def _agreement(sport: Sport, pubs_a: Mapping, pubs_b: Mapping, ids: Sequence[str]) -> dict:
    """How often the arms said the same thing on the same slot (counts, never a rate)."""
    out = {f: {"slots_in_both": 0, "same_verdict": 0, "a_take_b_pass": 0, "a_pass_b_take": 0,
               "both_take_different_calls": 0, "slot_only_in_a": 0, "slot_only_in_b": 0}
           for f in sport.families}
    for gid in ids:
        ca = {c["slot_id"]: c for c in pubs_a[gid].get("calls") or []}
        cb = {c["slot_id"]: c for c in pubs_b[gid].get("calls") or []}
        for slot in sorted(set(ca) | set(cb)):
            family = ((ca.get(slot) or cb.get(slot)).get("grading") or {}).get("family")
            if family not in out:
                continue
            f = out[family]
            if slot not in cb:
                f["slot_only_in_a"] += 1
                continue
            if slot not in ca:
                f["slot_only_in_b"] += 1
                continue
            f["slots_in_both"] += 1
            va, vb = ca[slot]["verdict"], cb[slot]["verdict"]
            if va == vb and ca[slot].get("selection") == cb[slot].get("selection"):
                f["same_verdict"] += 1
            elif va in TAKES and vb == "PASS":
                f["a_take_b_pass"] += 1
            elif va == "PASS" and vb in TAKES:
                f["a_pass_b_take"] += 1
            elif va in TAKES and vb in TAKES:
                f["both_take_different_calls"] += 1
            else:
                f["same_verdict"] += 1          # two passes on the same slot
    return out


def _cost(usage_a: Sequence[Mapping], usage_b: Sequence[Mapping], id_key: str, ids: Sequence[str]) -> dict:
    wanted = set(ids)

    def total(rows):
        return round(sum(float(r.get("cost_usd") or 0.0) for r in rows
                         if str(r.get(id_key) or "") in wanted), 4)

    a, b = total(usage_a), total(usage_b)
    return {"arm_a_usd": a, "arm_b_usd": b, "ratio": round(b / a, 3) if a > 0 else None,
            "note": "the cost of the paired games, from the usage each arm's run logged (estimates from the "
                    "usage the API returned)"}


def compare_sport(sport: Sport, rows_a: Sequence[Mapping], rows_b: Sequence[Mapping], *,
                  min_graded: int = 30, usage_a: Sequence[Mapping] = (),
                  usage_b: Sequence[Mapping] = ()) -> dict:
    """The comparison for one sport, from the two ledgers' rows. Pure."""
    problems: List[str] = []
    for row in rows_b:
        if row.get("kind") == sport.ledger.KIND_PUBLISHED and row.get("arm") != situation_arm.ARM_B:
            problems.append(f"{row.get(sport.id_key)}: a published row in the arm B ledger is not marked "
                            "arm B; this file is not arm B's")
            break
    for row in rows_a:
        if row.get("kind") == sport.ledger.KIND_PUBLISHED and row.get("arm") not in (None, situation_arm.ARM_A):
            problems.append(f"{row.get(sport.id_key)}: a published row in the arm A ledger is marked "
                            f"arm {row.get('arm')}; this file is not arm A's")
            break
    pubs_a, pubs_b = _published(sport, rows_a), _published(sport, rows_b)
    paired = sorted(set(pubs_a) & set(pubs_b))
    res_a, res_b = _results(sport, rows_a), _results(sport, rows_b)
    tally_a, tally_b = _tally(sport, pubs_a, res_a, paired), _tally(sport, pubs_b, res_b, paired)
    agreement = _agreement(sport, pubs_a, pubs_b, paired)
    families = {}
    for fam in sport.families:
        a, b = _shown(tally_a[fam], min_graded), _shown(tally_b[fam], min_graded)
        families[fam] = {"A": a, "B": b, "difference_b_minus_a": _difference(a, b),
                         "agreement": agreement[fam]}
    return {
        "sport": sport.name, "title": sport.title,
        "games": {"published_a": len(pubs_a), "published_b": len(pubs_b), "paired": len(paired),
                  "only_a": len(set(pubs_a) - set(pubs_b)), "only_b": len(set(pubs_b) - set(pubs_a))},
        "families": families,
        "cost": _cost(usage_a, usage_b, sport.id_key, paired),
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# the report and its words
# ---------------------------------------------------------------------------

def build_report(sports: Sequence[str], *, loaders: Optional[Mapping] = None, min_graded: int = 30) -> dict:
    """`loaders[sport]` is `() -> (rows_a, rows_b, usage_a, usage_b)`; the default reads the real
    ledgers. A ledger that does not exist reads as empty."""
    out = {"version": VERSION, "label": LABEL, "min_graded": min_graded, "sports": {}}
    for name in sports:
        sport = SPORTS[name]
        load = (loaders or {}).get(name) or (lambda s=sport: _default_load(s))
        rows_a, rows_b, usage_a, usage_b = load()
        out["sports"][name] = compare_sport(sport, rows_a, rows_b, min_graded=min_graded,
                                            usage_a=usage_a, usage_b=usage_b)
    return out


def _default_load(sport: Sport) -> tuple:
    from src.ledger.chain import HashChainLedger

    make = situation_arm.mlb_arm if sport.name == "mlb" else situation_arm.ufc_arm
    a, b = make(situation_arm.ARM_A), make(situation_arm.ARM_B)
    return (sport.ledger.rows(a.abs_store()), sport.ledger.rows(b.abs_store()),
            HashChainLedger(a.abs_usage()).read(), HashChainLedger(b.abs_usage()).read())


def _cell(c: Mapping) -> str:
    rate = "withheld" if c["win_rate"] is None else f"{c['win_rate'] * 100:.1f}%"
    units = "withheld" if c["units"] is None else f"{c['units']:+.2f}"
    cal = c["calibration"]
    brier = "withheld" if cal["brier"] is None else f"{cal['brier']:.4f} (gap {cal['gap']:+.3f})"
    return (f"taken {c['taken']} (other side {c['taken_other_side']}), passes {c['passes']}, graded {c['graded']} "
            f"(W{c['wins']} L{c['losses']} P{c['pushes']} V{c['voids']}), unresolved {c['unresolved']}; "
            f"win rate {rate}, units {units}, calibration {brier}")


def render(report: Mapping) -> List[str]:
    lines = [report["label"],
             f"Arm A reads the matchup statistics. Arm B reads the same plus the situation layer. "
             f"Paired games only; rates withheld under {report['min_graded']} graded calls per family."]
    for name, s in report["sports"].items():
        g = s["games"]
        lines.append("")
        lines.append(f"{s['title']}: A published {g['published_a']}, B published {g['published_b']}, "
                     f"{g['paired']} paired ({g['only_a']} only in A, {g['only_b']} only in B)")
        for problem in s["problems"]:
            lines.append(f"  PROBLEM: {problem}")
        for fam, f in s["families"].items():
            lines.append(f"  {fam}")
            lines.append(f"    A: {_cell(f['A'])}")
            lines.append(f"    B: {_cell(f['B'])}")
            ag = f["agreement"]
            lines.append(f"    the arms: same call on {ag['same_verdict']} of {ag['slots_in_both']} slots; "
                         f"A bet and B passed on {ag['a_take_b_pass']}, A passed and B bet on {ag['a_pass_b_take']}, "
                         f"both bet differently on {ag['both_take_different_calls']}")
            d = f["difference_b_minus_a"]
            lines.append("    B minus A: " + ("withheld until both arms have "
                                              f"{report['min_graded']} graded calls" if d is None else
                                              f"win rate {d['win_rate'] * 100:+.1f} points, units {d['units']:+.2f}"))
        c = s["cost"]
        lines.append(f"  cost of the paired games: A ${c['arm_a_usd']:.2f}, B ${c['arm_b_usd']:.2f}"
                     + ("" if c["ratio"] is None else f" (B is {c['ratio']:.2f} times A)"))
    return lines


def execute_compare(*, sport: str = "all", as_json: bool = False, out: Callable = print,
                    loaders: Optional[Mapping] = None, cfg: Optional[Mapping] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    names = tuple(SPORTS) if sport == "all" else (sport,)
    report = build_report(names, loaders=loaders, min_graded=cfg["min_graded_for_rates"])
    if as_json:
        out(json.dumps(report, indent=2, sort_keys=True))
    else:
        for line in render(report):
            out(line)
    return EXIT_PROBLEM if any(s["problems"] for s in report["sports"].values()) else EXIT_OK
