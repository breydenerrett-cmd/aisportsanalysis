"""Automated falsification battery -- every candidate faces the tests that killed M3.

WHY THIS EXISTS
---------------
The most valuable act in this project so far was destroying a false positive.
M3 arrived at +8.49pp, p=0.006, ROI +18% -- and died on dose-response, book
concentration and the season split (docs/RESULTS_V2.md). Those kill-tests were
hand-written for M3 alone, which means the next attractive candidate meets
them only if someone remembers to write them again. This module makes the
battery a machine: one call, every test, no discretion. The system should be
better at destroying false positives than at finding attractive ones, and a
kill-test that has to be remembered is a kill-test that eventually gets skipped
for the candidate everyone wants to keep.

WHAT A ROW IS
-------------
A graded selection: "date" (ISO string), "won" (bool), "implied" (consensus
fair probability of the picked side). The effect is always mean(won - implied)
-- realised minus what the price already said -- so a candidate that merely
restates the favourite scores zero by construction. Optional keys unlock
further checks: "season", "side", "team", "book", "price", and a dose (the
signal magnitude that triggered selection, under the key named by dose_key).
A row missing an optional key is excluded from that check; a check with no
usable rows, or fewer than MIN_N of them, reports {"skipped": reason} and can
never be fatal. The battery never derives season from the date: declaring
where a season starts and ends is the caller's call to make, and a silent
derivation would hide that it was never made.

Every p-value and the baseline interval come from src/model/discovery.py and
cluster by DATE. Selections on one slate share weather, schedule position and
market conditions; anything unclustered here is the anticonservative n that
turns noise into a result.

PRE-REGISTERED FATAL RULES
--------------------------
Written down before any candidate meets them, so no rule can be re-judged
after seeing what it kills. "Judgeable" means n >= MIN_N (30).

1. season_split -- FATAL when two judgeable seasons carry effects of opposite
   sign, each beyond effect_floor in magnitude. A result that points one way
   in 2023 and the other way in 2024 is a year, not an effect.
2. team_concentration -- over the five most-backed teams, FATAL when leaving
   any single team out pushes p above 0.10 AND the remaining effect below
   effect_floor (signed, so a sign flip counts). One club is a story about a
   club, not a market inefficiency.
3. book_concentration -- the same rule by book. This is exactly what killed
   M3: excluding FanDuel gutted it.
4. extreme_removal -- drop the 5% of DATES (ceil, at least one) whose cluster
   contribution to the effect is largest, and FATAL if the remaining effect
   crosses zero. Dates, not rows: outcomes are binary, so the honest notion
   of an outlier is a slate that carried the result, not a single bet whose
   |won - implied| happens to round high. Contribution is measured in the
   direction of the baseline effect, and the rule mirrors for a negative
   baseline -- "crosses zero" always means the sign flips.
5. dose_response -- the M3 signature, encoded exactly. Order the dose bands
   ascending; the SPIKE is the first judgeable band with effect above
   effect_floor. FATAL only when all three hold: (a) the band immediately
   below the spike is judgeable with effect <= 0; (b) at least one judgeable
   band sits above the spike; (c) no judgeable band above the spike shows a
   larger effect than the spike. A real dose should deliver more effect with
   more dose; a spike in one slice with nothing below it and nothing larger
   above it is the shape of noise. Every missing piece -- no spike, spike in
   the bottom band, an unjudgeable neighbour, growth above the spike --
   reports non-fatal, because doubt is not evidence of death either.
   To arm (a) fully, pass the wider graded sample (sub-threshold candidates
   included) with the true selection threshold as one of the dose_bands
   edges, the way M3's 0.015-0.020 band was built; with selected rows only
   and quartile bands the below-spike band usually cannot exist.

Everything else -- baseline, home/away, favourite/underdog, price bands,
threshold sensitivity -- is report-only: slices a person should read, none
sharp enough to kill on automatically.

"SURVIVES" MEANS NOT FALSIFIED, NEVER CONFIRMED
-----------------------------------------------
survives=True says only that no fatal rule fired on this sample. A battery
skipped for sample size survives vacuously; the sample floor and the family
correction upstream are what stop an unmeasured candidate from advancing.
This module destroys; it does not endorse.
"""

from __future__ import annotations

import math

from src.model import discovery

# Below this many rows a slice is reported but never judged, and a whole check
# is skipped. Same floor discovery.evaluate uses: under it, nothing is worth
# reading, and a fatal verdict from ten rows would be noise killing noise.
MIN_N = 30

# Leave-one-out kill line for the concentration checks. 0.10 rather than 0.05
# on purpose: a candidate whose significance cannot survive losing one team or
# one book even at the looser line was never a market-wide effect.
LOO_P_CEILING = 0.10

# Fraction of dates removed by extreme_removal, and how many slices the
# concentration checks leave out (top teams / books by selection count).
EXTREME_DATE_FRACTION = 0.05
CONCENTRATION_TOP = 5

# Implied-probability bands for the report-only price split. Coarse by design:
# finer bands would invite reading noise in the tails.
PRICE_BANDS = ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 1.0))

# Threshold sensitivity re-runs the baseline at these multiples of the implied
# selection threshold (the smallest |dose| observed). 0.8x only differs from
# the baseline when the caller passed rows below the current threshold.
THRESHOLD_SCALES = (0.8, 1.25)

# Checks that carry a pre-registered fatal rule; the rest are report-only.
FATAL_CHECKS = ("season_split", "team_concentration", "book_concentration",
                "extreme_removal", "dose_response")


class BatteryError(RuntimeError):
    """Raised when the battery cannot run honestly (a required key is absent)."""


# ---------------------------------------------------------------------------
# Shared measurement
# ---------------------------------------------------------------------------

def _prepared(rows) -> list:
    """Copies with "_diff" attached; never mutates the caller's rows.

    Required keys raise rather than guess: a row without a date cannot be
    clustered, and a fabricated implied would poison every check at once.
    """
    prepared = []
    for row in rows:
        for key in ("date", "won", "implied"):
            if row.get(key) is None:
                raise BatteryError(f"row missing required key '{key}'")
        prepared.append(dict(
            row, _diff=(1.0 if row["won"] else 0.0) - row["implied"]))
    return prepared


def _measure(diff_rows) -> dict:
    """Effect and clustered p for one slice; refuses to judge under the floor."""
    n = len(diff_rows)
    if n < MIN_N:
        return {"n": n, "effect": None, "p": None,
                "note": f"below the {MIN_N}-row floor; reported, never judged"}
    effect = sum(r["_diff"] for r in diff_rows) / n
    return {"n": n, "effect": round(effect, 5),
            "p": round(discovery.clustered_two_sided_p(effect, diff_rows), 6)}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _baseline(prepared) -> dict:
    if len(prepared) < MIN_N:
        return {"skipped": (f"{len(prepared)} rows is below the {MIN_N}-row "
                            "floor; nothing here is worth reading")}
    result = _measure(prepared)
    result["ci"] = discovery.clustered_bootstrap(
        prepared,
        lambda sample: (sum(r["_diff"] for r in sample) / len(sample))
        if sample else None)
    result["note"] = "mean(won - implied), p and interval clustered by date"
    return result


def _usable(prepared, key):
    return [r for r in prepared if r.get(key) is not None]


def _season_split(prepared, effect_floor) -> dict:
    usable = _usable(prepared, "season")
    if not usable:
        return {"skipped": "no 'season' key present"}
    if len(usable) < MIN_N:
        return {"skipped": f"only {len(usable)} rows carry 'season'"}
    by_season = {}
    for row in usable:
        by_season.setdefault(row["season"], []).append(row)
    seasons = {str(season): _measure(rows) for season, rows
               in sorted(by_season.items(), key=lambda kv: str(kv[0]))}
    judged = [m["effect"] for m in seasons.values() if m["effect"] is not None]
    # Pre-registered rule 1: opposite signs, each beyond the floor, both
    # seasons judgeable. max/min covers every pair without enumerating pairs.
    fatal = (len(judged) >= 2 and max(judged) > effect_floor
             and min(judged) < -effect_floor)
    return {"n": len(usable), "seasons": seasons, "fatal": fatal,
            "note": ("FATAL when two judgeable seasons disagree in sign beyond "
                     "the floor -- a year, not an effect")}


def _side_split(prepared, key, labels, member, note) -> dict:
    usable = _usable(prepared, key) if key else list(prepared)
    if key and not usable:
        return {"skipped": f"no '{key}' key present"}
    if len(usable) < MIN_N:
        return {"skipped": f"only {len(usable)} usable rows"}
    detail = {label: _measure([r for r in usable if member(r, label)])
              for label in labels}
    return {"n": len(usable), "splits": detail, "fatal": False, "note": note}


def _home_away(prepared) -> dict:
    return _side_split(
        prepared, "side", ("home", "away"),
        lambda r, label: r["side"] == label,
        "report only -- an asymmetry here is context, not a verdict")


def _favorite_underdog(prepared) -> dict:
    return _side_split(
        prepared, None, ("favorite", "underdog"),
        lambda r, label: (r["implied"] > 0.5) == (label == "favorite"),
        "report only -- favorite means implied > 0.5")


def _concentration(prepared, key, effect_floor) -> dict:
    """Leave-one-out over the most-backed teams or books.

    The M3 lesson: a market-wide effect survives losing any one participant.
    Only the top slices by count are left out -- dropping a 4-row team tells
    you nothing, and a leave-out that itself falls under the floor is reported
    but never judged (doubt is not death).
    """
    usable = _usable(prepared, key)
    if not usable:
        return {"skipped": f"no '{key}' key present"}
    if len(usable) < MIN_N:
        return {"skipped": f"only {len(usable)} rows carry '{key}'"}
    counts = {}
    for row in usable:
        counts[row[key]] = counts.get(row[key], 0) + 1
    top = [name for name, _ in sorted(
        counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:CONCENTRATION_TOP]]
    leave_one_out, killed_by = {}, []
    for name in top:
        measured = _measure([r for r in usable if r[key] != name])
        leave_one_out[str(name)] = measured
        # Pre-registered rules 2 and 3: significance AND size both gone once
        # one slice is removed. Signed effect on purpose -- a flip counts.
        if (measured["effect"] is not None
                and measured["p"] > LOO_P_CEILING
                and measured["effect"] < effect_floor):
            killed_by.append(str(name))
    return {"n": len(usable), "leave_one_out": leave_one_out,
            "fatal": bool(killed_by), "killed_by": killed_by,
            "note": (f"FATAL when dropping one {key} leaves p > "
                     f"{LOO_P_CEILING} and effect < the floor")}


def _price_bands(prepared) -> dict:
    bands = []
    for i, (lo, hi) in enumerate(PRICE_BANDS):
        last = i == len(PRICE_BANDS) - 1
        members = [r for r in prepared if lo <= r["implied"]
                   and (r["implied"] <= hi if last else r["implied"] < hi)]
        measured = _measure(members)
        measured["lo"], measured["hi"] = lo, hi
        bands.append(measured)
    return {"n": len(prepared), "bands": bands, "fatal": False,
            "note": "report only -- effect by implied-probability band"}


def _extreme_removal(prepared, baseline_effect) -> dict:
    by_date = {}
    for row in prepared:
        by_date.setdefault(row["date"], []).append(row)
    # Direction of the baseline: dropping the dates that pushed WITH the
    # effect is the test; dropping against it would only inflate the result.
    sign = 1.0 if baseline_effect >= 0 else -1.0
    ranked = sorted(
        by_date.items(),
        key=lambda kv: (-sign * sum(r["_diff"] for r in kv[1]), kv[0]))
    drop = max(1, math.ceil(EXTREME_DATE_FRACTION * len(by_date)))
    dropped = {date for date, _ in ranked[:drop]}
    measured = _measure([r for r in prepared if r["date"] not in dropped])
    # Pre-registered rule 4: fatal only when the sign flips. Shrinkage is
    # expected -- removing the best dates of a real effect shrinks it too.
    fatal = measured["effect"] is not None and sign * measured["effect"] < 0
    measured.update({
        "fatal": fatal, "dropped_dates": sorted(dropped),
        "note": (f"dropped the {drop} date(s) contributing most to the "
                 "effect; FATAL when the remaining effect crosses zero")})
    return measured


def _quartile_edges(values) -> list:
    """Quartile band edges of |dose|, duplicates collapsed so no band is
    degenerate. Index quantiles, not interpolation -- an edge that is a real
    observed value keeps band membership unambiguous."""
    ordered = sorted(values)
    edges = [ordered[0]]
    for fraction in (0.25, 0.5, 0.75):
        edges.append(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))])
    edges.append(ordered[-1])
    collapsed = []
    for edge in edges:
        if not collapsed or edge > collapsed[-1]:
            collapsed.append(edge)
    return collapsed


def _dose_response(prepared, dose_key, dose_bands, effect_floor) -> dict:
    if dose_key is None:
        return {"skipped": "no dose_key configured"}
    usable = _usable(prepared, dose_key)
    if not usable:
        return {"skipped": f"no '{dose_key}' key present"}
    if len(usable) < MIN_N:
        return {"skipped": f"only {len(usable)} rows carry '{dose_key}'"}
    edges = (sorted(dose_bands) if dose_bands
             else _quartile_edges([abs(r[dose_key]) for r in usable]))
    if len(edges) < 2:
        return {"skipped": "dose values have no spread to band"}
    bands = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        last = i == len(edges) - 2
        members = [r for r in usable if lo <= abs(r[dose_key])
                   and (abs(r[dose_key]) <= hi if last else abs(r[dose_key]) < hi)]
        measured = _measure(members)
        measured["lo"], measured["hi"] = lo, hi
        bands.append(measured)
    fatal, why = _m3_signature(bands, effect_floor)
    return {"n": len(usable), "bands": bands, "fatal": fatal, "note": why}


def _m3_signature(bands, effect_floor) -> tuple:
    """Pre-registered rule 5, exactly as the module docstring states it.

    Any missing piece answers non-fatal: the rule exists to recognise one
    specific shape of noise, not to punish every non-monotone table.
    """
    spike = None
    for i, band in enumerate(bands):
        if band["effect"] is not None and band["effect"] > effect_floor:
            spike = i
            break
    if spike is None:
        return False, "no judgeable band clears the effect floor"
    if spike == 0:
        return False, ("the first band above the floor is the bottom band; "
                       "no band below it to contradict")
    below = bands[spike - 1]
    if below["effect"] is None:
        return False, ("the band below the spike is under the row floor; "
                       "in doubt, non-fatal")
    if below["effect"] > 0:
        return False, "the band below the spike is positive; no spike signature"
    above = [b["effect"] for b in bands[spike + 1:] if b["effect"] is not None]
    if not above:
        return False, ("no judgeable band above the spike; in doubt, non-fatal")
    if max(above) > bands[spike]["effect"]:
        return False, ("a band above the spike is larger; dose-response is "
                       "not ruled out")
    return True, ("M3 signature: the spike band is positive, the band just "
                  "below it is <= 0, and nothing above it is larger")


def _threshold_sensitivity(prepared, dose_key) -> dict:
    if dose_key is None:
        return {"skipped": "no dose_key configured"}
    usable = _usable(prepared, dose_key)
    if not usable:
        return {"skipped": f"no '{dose_key}' key present"}
    if len(usable) < MIN_N:
        return {"skipped": f"only {len(usable)} rows carry '{dose_key}'"}
    threshold = min(abs(r[dose_key]) for r in usable)
    scaled = {}
    for scale in THRESHOLD_SCALES:
        cut = scale * threshold
        measured = _measure([r for r in usable if abs(r[dose_key]) >= cut])
        measured["threshold"] = round(cut, 6)
        scaled[f"{scale}x"] = measured
    return {"n": len(usable), "threshold": round(threshold, 6),
            "scaled": scaled, "fatal": False,
            "note": ("report only -- a real effect should not hinge on the "
                     "exact threshold; 0.8x differs from baseline only when "
                     "rows below the current threshold were provided")}


# ---------------------------------------------------------------------------
# The battery
# ---------------------------------------------------------------------------

def run(rows, *, effect_floor=0.01, dose_key=None, dose_bands=None) -> dict:
    """Run every falsification check and return the verdict.

    rows: graded selections (see module docstring for keys). dose_key names
    the row key holding the signal magnitude; dose_bands is an ascending list
    of band edges (consecutive pairs form bands, half-open except the last,
    which includes its upper edge -- pass math.inf for an open top), else
    quartiles of |dose|. effect_floor defaults to one probability point, the
    vig line discovery.evaluate already uses for economic meaning.

    Returns {"survives": bool, "fatal": [check names], "report": {checks}}.
    survives means not falsified, never confirmed.
    """
    prepared = _prepared(rows)
    report = {"baseline": _baseline(prepared)}
    if "skipped" in report["baseline"]:
        # Every check reads the same sample; below the floor they all skip
        # for the same reason, and the battery survives only vacuously.
        for name in ("season_split", "home_away", "favorite_underdog",
                     "team_concentration", "book_concentration", "price_bands",
                     "extreme_removal", "dose_response",
                     "threshold_sensitivity"):
            report[name] = {"skipped": report["baseline"]["skipped"]}
        return {"survives": True, "fatal": [], "report": report}

    report["season_split"] = _season_split(prepared, effect_floor)
    report["home_away"] = _home_away(prepared)
    report["favorite_underdog"] = _favorite_underdog(prepared)
    report["team_concentration"] = _concentration(prepared, "team", effect_floor)
    report["book_concentration"] = _concentration(prepared, "book", effect_floor)
    report["price_bands"] = _price_bands(prepared)
    report["extreme_removal"] = _extreme_removal(
        prepared, report["baseline"]["effect"])
    report["dose_response"] = _dose_response(
        prepared, dose_key, dose_bands, effect_floor)
    report["threshold_sensitivity"] = _threshold_sensitivity(prepared, dose_key)

    fatal = [name for name in FATAL_CHECKS if report[name].get("fatal")]
    return {"survives": not fatal, "fatal": fatal, "report": report}
