"""Which constants were calibrated against a population, and has it moved?

THE FAILURE THIS EXISTS TO PREVENT
-----------------------------------
`docs/INCIDENT_2026-09-10_STRONG_TIER.md`. `EVIDENCE_STRONG` fires at "3+
independent families agree", and `src/engine/slip.py` justifies the 3 by
saying it is the strongest agreement ever measured on the live ledger. That
was true on 2026-09-08, when essentially nothing forward-test played. Two
days later the engine ran 166 decisions from 29 systems, every published
pick was STRONG, and the rarest grade in the product had quietly stopped
distinguishing anything.

Nothing broke. No test failed. A constant that described the old population
kept describing it while the population changed by two orders of magnitude.

**A threshold calibrated against a population is a claim with an expiry
date**, and before this file nothing in the repo recorded which constants
had that property. Every one of them was indistinguishable, in source, from
a published physical constant like `FIP_TO_RA_SCALE`.

WHAT IS AND IS NOT REGISTERED HERE
-----------------------------------
Registered: a constant whose CORRECT VALUE depends on a distribution that
can move -- how many families ever agree, how spread out run scoring is, how
often the market makes a side a heavy favourite.

Not registered, and deliberately: judgment calls and published constants.
`prices.MIN_BOOKS = 6` is a stance about what counts as a market, not a
measurement of one. `HOME_FIELD_RUNS = 0.20` is a published baseball
constant. Neither expires because neither was ever fitted, and registering
them would bury the ones that matter.

The distinction is the point. A constant belongs here if the sentence "this
was measured against X" is true of it.

Read-only. Re-measures each population and reports the gap. Changes nothing.

Usage:
    python scripts/calibration_drift_audit.py [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The re-measurements. Each returns (current_value, detail) or (None, reason).
# ---------------------------------------------------------------------------

def _measure_family_ceiling():
    """The largest family count any published pick currently claims."""
    path = os.path.join(REPO, "evidence", "slips_v1.jsonl")
    if not os.path.exists(path):
        return None, "no slip ledger"
    worst = 0
    seen = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for pick in row.get("picks") or ():
                n = pick.get("n_families")
                if isinstance(n, int):
                    worst = max(worst, n)
                    seen += 1
    if not seen:
        return None, "no published picks yet"
    return worst, f"{seen} published picks"


def _measure_strong_share():
    """What fraction of published picks the STRONG threshold now admits.

    This is the number that matters about a RARE tier, and it is not the
    ceiling -- a tier can be perfectly within its ceiling and still fire on
    every pick, which is exactly what happened.
    """
    from src.engine import slip as slip_mod

    path = os.path.join(REPO, "evidence", "slips_v1.jsonl")
    if not os.path.exists(path):
        return None, "no slip ledger"
    strong = total = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for pick in row.get("picks") or ():
                n = pick.get("n_families")
                if not isinstance(n, int):
                    continue
                total += 1
                if n >= slip_mod.EVIDENCE_STRONG_MIN_FAMILIES:
                    strong += 1
    if not total:
        return None, "no published picks yet"
    return strong / total, f"{strong} of {total} published picks"


def _measure_dispersion():
    """Per-team run variance over mean, conditional on the model's own means."""
    from src.analysis import strength
    from src.pipeline import features as features_mod
    from src.pipeline import history, pitchers as pitcher_store

    store = history.read_results()
    if not store:
        return None, "no results store"
    season = max(str(r.get("date") or "")[:4] for r in store.values())
    logs = pitcher_store.read_logs() or None
    rows = features_mod.build_training_table(
        store, min_date=f"{season}-04-15", max_date=f"{season}-12-31",
        pitcher_logs=logs, require_complete=True)["rows"]
    if len(rows) < 300:
        return None, f"only {len(rows)} games in {season}"
    league = strength.league_runs_per_game(rows)
    residuals = []
    for row in rows:
        actual = store.get(str(row["game_pk"])) or {}
        away, home = _int(actual.get("away_score")), _int(actual.get("home_score"))
        if away is None or home is None:
            continue
        try:
            means = strength.run_means(row, league_rpg=league)
        except strength.StrengthError:
            continue
        for predicted, observed in ((means["away_mean"], away),
                                    (means["home_mean"], home)):
            if predicted > 0:
                residuals.append((observed - predicted) ** 2 / predicted)
    if not residuals:
        return None, "no residuals"
    se = statistics.pstdev(residuals) / math.sqrt(len(residuals))
    return (statistics.fmean(residuals),
            f"{len(residuals)} team-games in {season}, se {se:.4f}")


def _measure_card_band_share():
    """The fraction of recent card picks landing in the top confidence band.

    The card's STRONG band is a cut on the market's own consensus, so it
    moves with how often the market makes a side a heavy favourite -- which
    is a real distribution and can shift with the schedule.
    """
    from src.analysis import daily_card

    path = os.path.join(REPO, "evidence", "cards_v1.jsonl")
    if not os.path.exists(path):
        return None, "no card ledger"
    counts = Counter()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") != "card_published":
                continue
            for pick in row.get("picks") or ():
                counts[pick.get("label")] += 1
    total = sum(counts.values())
    if total < 20:
        return None, f"only {total} published card picks so far"
    return (counts.get(daily_card.LABEL_STRONG, 0) / total,
            f"{counts.get(daily_card.LABEL_STRONG, 0)} of {total} card picks")


# ---------------------------------------------------------------------------
# The register itself
# ---------------------------------------------------------------------------
#
# `expected` is what the population read WHEN THE CONSTANT WAS SET, not what
# anyone would like it to read. `tolerance` is how far it may drift before
# the constant stops describing the thing it was measured from.
REGISTER = [
    {
        "constant": "slip.EVIDENCE_STRONG threshold (3 families)",
        "where": "src/engine/slip.py",
        "calibrated_against": "the largest family agreement ever seen on the "
                              "live ledger, which was 3",
        "measured_on": "2026-09-08",
        "measure": _measure_family_ceiling,
        "expected": 3,
        "tolerance": 2,
        "why_it_matters": "STRONG is sold as the rarest grade a pick carries. "
                          "If the ceiling has moved far above the threshold, "
                          "the grade fires on everything and distinguishes "
                          "nothing.",
    },
    {
        "constant": "share of published picks graded STRONG",
        "where": "src/engine/slip.py",
        "calibrated_against": "a rare tier, intended to fire on a small "
                              "minority of picks",
        "measured_on": "2026-09-08",
        "measure": _measure_strong_share,
        "expected": 0.10,
        "tolerance": 0.30,
        "why_it_matters": "The direct measurement of whether a rare tier is "
                          "still rare. The ceiling can look fine while this "
                          "is at 100%, which is what happened on 2026-09-10.",
    },
    {
        "constant": "strength.DISPERSION = 2.3352",
        "where": "src/analysis/strength.py",
        "calibrated_against": "per-team run variance over mean, conditional "
                              "on the model's own per-game means",
        "measured_on": "2026-09-10",
        "measure": _measure_dispersion,
        "expected": 2.3352,
        "tolerance": 0.30,
        "why_it_matters": "Run scoring environments shift between seasons. "
                          "2025 and 2026 agreed to 0.128 standard errors, so "
                          "this is stable -- but it is a measurement, not a "
                          "law, and it is registered because it could move.",
    },
    {
        "constant": "daily_card.BAND_STRONG = 0.62",
        "where": "src/analysis/daily_card.py",
        "calibrated_against": "how often the market makes a side a heavy "
                              "enough favourite to earn the top band",
        "measured_on": "2026-09-10",
        "measure": _measure_card_band_share,
        "expected": 0.30,
        "tolerance": 0.40,
        "why_it_matters": "Same failure shape as the slip's STRONG tier, on "
                          "the surface customers actually read. Registered "
                          "BEFORE it goes wrong rather than after.",
    },
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    findings = []
    rows = []
    for entry in REGISTER:
        try:
            current, detail = entry["measure"]()
        except Exception as exc:  # noqa: BLE001 -- one broken measure must
            # not take the audit down; a silent audit is the failure mode
            # this whole file exists to prevent.
            current, detail = None, f"measurement failed: {exc!r}"

        drift = (abs(current - entry["expected"])
                 if current is not None else None)
        stale = drift is not None and drift > entry["tolerance"]
        rows.append({
            "constant": entry["constant"],
            "where": entry["where"],
            "measured_on": entry["measured_on"],
            "expected": entry["expected"],
            "current": (round(current, 4) if isinstance(current, float)
                        else current),
            "drift": round(drift, 4) if drift is not None else None,
            "tolerance": entry["tolerance"],
            "stale": stale,
            "detail": detail,
        })
        if stale:
            findings.append(
                f"{entry['constant']}: calibrated against "
                f"{entry['calibrated_against']} on {entry['measured_on']}, "
                f"expected {entry['expected']}, now {current} "
                f"({detail}). {entry['why_it_matters']}")

    if args.json:
        print(json.dumps({"rows": rows, "stale": findings}, indent=2))
        return 1 if findings else 0

    print(f"{'constant':<46}{'set':<12}{'was':>9}{'now':>9}{'drift':>9}")
    for row in rows:
        now = "—" if row["current"] is None else f"{row['current']}"
        drift = "—" if row["drift"] is None else f"{row['drift']}"
        flag = "  STALE" if row["stale"] else ""
        print(f"{row['constant'][:45]:<46}{row['measured_on']:<12}"
              f"{row['expected']:>9}{now:>9}{drift:>9}{flag}")
    print()
    for row in rows:
        if row["current"] is None:
            print(f"  not measurable: {row['constant']} -- {row['detail']}")
    if findings:
        print()
        for message in findings:
            print(f"ESCALATE: {message}")
        return 1
    print("  no registered constant has drifted past its tolerance")
    print()
    print("  A constant belongs in this register if the sentence 'this was")
    print("  measured against X' is true of it. Judgment calls and published")
    print("  constants do not expire and are deliberately left out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
