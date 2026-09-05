#!/usr/bin/env python3
"""Dry-run lifecycle classification of the existing overlap-report families.

See docs/FACTORY_LIFECYCLE.md "Dry-run classification of the 1,062 existing
families" for the full argument; this script is that argument's
implementation only.

WHAT THIS DOES AND DOES NOT DO
-------------------------------
It reads the ALREADY-PERSISTED `data/research/evolab/sweep-*.json` artifacts
(the same ones `scripts/factory_overlap_report.py` reads), recomputes the
same Jaccard families `overlap.py`/that script already define (no new
threshold, no new method), and classifies each family as CANDIDATE or
RETIRED using ONLY fields already written into the artifact:
`ceiling.generators_cleared`, `spa_cross_check.status`, `cscv.pbo`. It never
calls `run_sweep`, never touches CSCV/SPA/ceiling code, never reads an
outcome/price/ledger row -- "no evaluation, no outcome reads" per the task.

THE RULE, STATED ONCE
----------------------
`ceiling.generators_cleared` is the set of placebo generators the REAL
maximum (the single best strategy across the WHOLE population) beat -- an
upper bound on every family's best member, since no family member can beat
what the population champion could not. If it is empty, or if
`spa_cross_check.status == "DISAGREE"` (the artifact's own words: "Find the
bug before quoting either number" -- a disagreement is not evidence a
result should be trusted), or if `cscv.pbo > 0.5` (worse than a coin flip),
the whole artifact's population-level battery verdict is FAIL, and every
family drawn from it is classified RETIRED for want of ANY surviving
passing evidence -- there is no per-family fresh CSCV/SPA retest on record
for any of them, so none can honestly be called CANDIDATE (which requires a
non-empty PreRegistration and an admission decision this script has no
authority to make on the owner's behalf -- it only reports what the
evidence already on disk permits).

If a future artifact's battery verdict is a PASS by this same rule, this
script still does not call `lifecycle.admit()` for it -- admission is a
human/pipeline decision requiring a `PreRegistration` this script cannot
manufacture. It reports such families as CANDIDATE-ELIGIBLE instead of
RETIRED, so the distinction between "the data does not support keeping this
out" and "this has actually been admitted" is never blurred.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.evolab import overlap  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVOLAB_DIR = os.path.join(REPO_ROOT, "data", "research", "evolab")
SWEEP_GLOB = os.path.join(EVOLAB_DIR, "sweep-*.json")
OUT_PATH = os.path.join(REPO_ROOT, "docs", "FACTORY_LIFECYCLE_DRYRUN.md")


def _load_sweep_reports(pattern: str = SWEEP_GLOB) -> list[dict]:
    reports = []
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["_source_path"] = os.path.relpath(path, REPO_ROOT)
        reports.append(payload)
    return reports


def _masks_paths_for(spec_hash: str):
    stem = os.path.join(EVOLAB_DIR, f"masks-{spec_hash[:16]}")
    index_path, bin_path = f"{stem}.index.json", f"{stem}.bin"
    if os.path.exists(index_path) and os.path.exists(bin_path):
        return index_path, bin_path
    return None


def _load_combined_masks(index_path: str, bin_path: str):
    """Same packing as scripts/factory_overlap_report.py -- see that
    module's docstring for why popcounts, not string sets, at this scale."""
    with open(index_path, "r", encoding="utf-8") as fh:
        index = json.load(fh)
    n_games = index["n_games"]
    n_bytes = index["bytes_per_mask"]
    rec = index["bytes_per_strategy"]
    strategy_order = index["strategy_order"]
    with open(bin_path, "rb") as fh:
        data = fh.read()
    combined = {}
    for i, sid in enumerate(strategy_order):
        chunk = data[i * rec:(i + 1) * rec]
        away = int.from_bytes(chunk[:n_bytes], "little")
        home = int.from_bytes(chunk[n_bytes:2 * n_bytes], "little")
        combined[sid] = away | (home << n_games)
    return combined, n_games


def _find(parent, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent, a, b):
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def _families_from_combined(combined: dict) -> list:
    """Jaccard>=overlap.FAMILY_THRESHOLD single-linkage families, popcount
    method -- identical to factory_overlap_report.py's `_overlap_from_combined`,
    families only (this script does not need dedup/effective-N, already
    reported in FACTORY_OVERLAP_REPORT.md)."""
    ids = sorted(combined)
    parent = {i: i for i in ids}
    threshold = overlap.FAMILY_THRESHOLD
    for i, a in enumerate(ids):
        ca = combined[a]
        for b in ids[i + 1:]:
            cb = combined[b]
            union_bits = (ca | cb).bit_count()
            if union_bits == 0:
                continue
            if (ca & cb).bit_count() / union_bits >= threshold:
                _union(parent, a, b)
    groups: dict = {}
    for i in ids:
        groups.setdefault(_find(parent, i), []).append(i)
    families = [sorted(members) for members in groups.values()]
    families.sort(key=lambda fam: (-len(fam), fam[0]))
    return families


def population_battery_verdict(report: dict) -> tuple:
    """(passed: bool, reasons: list[str]) -- the ONE population-level
    verdict this script reads off already-persisted fields, per the module
    docstring's rule. `passed=False` if ANY of the three checks fail; every
    failing check is named, never a bare False."""
    reasons = []
    ceiling = report.get("ceiling") or {}
    cleared = ceiling.get("generators_cleared")
    if not cleared:
        reasons.append(
            "ceiling.generators_cleared is empty -- the population's real "
            "maximum cleared no placebo generator's threshold")
    cross = report.get("spa_cross_check") or {}
    status = cross.get("status")
    if status == "DISAGREE":
        reasons.append(
            "spa_cross_check.status is DISAGREE -- the artifact's own "
            "verdict says neither number should be quoted as a pass")
    cscv = report.get("cscv") or {}
    pbo = cscv.get("pbo")
    if isinstance(pbo, (int, float)) and pbo > 0.5:
        reasons.append(
            f"cscv.pbo is {pbo:.4f} > 0.5 -- probability of backtest "
            "overfitting worse than a coin flip")
    return (not reasons, reasons)


def classify_families(report: dict) -> tuple:
    """(families: list[list[str]], state_by_family_index: list[str],
    verdict_reasons: list[str]) for one sweep artifact."""
    spec_hash = report.get("enumeration_spec_hash", "")
    if report.get("decision_masks"):
        from src.evolab.sweep import decode_masks
        decoded = decode_masks(report["decision_masks"])
        n_games = report["decision_masks"]["n_games"]
        combined = {sid: away | (home << n_games)
                   for sid, (away, home) in decoded.items()}
    else:
        masks_paths = _masks_paths_for(spec_hash)
        if not masks_paths:
            return [], [], [
                "no decision_masks on this artifact and no backfilled "
                f"masks-{spec_hash[:16]}.{{bin,index.json}} found -- "
                "families cannot be recomputed, nothing classified"]
        combined, _n_games = _load_combined_masks(*masks_paths)

    families = _families_from_combined(combined)
    passed, reasons = population_battery_verdict(report)
    # Every family gets the SAME state: the verdict this rule reads is
    # population-level (there is no per-family retest on record), so a
    # per-family loop would just repeat the identical reasons |families|
    # times -- states are still returned per-family so a future artifact
    # with per-family verdicts is a drop-in extension, not a rewrite.
    state = "CANDIDATE-ELIGIBLE" if passed else "RETIRED"
    states = [state] * len(families)
    return families, states, reasons


def _render(reports: list, generated_at: str) -> str:
    lines = [
        "# Factory lifecycle dry-run",
        "",
        f"Generated {generated_at}. Classifies the families already "
        "computed in `docs/FACTORY_OVERLAP_REPORT.md` into "
        "CANDIDATE-ELIGIBLE/RETIRED using only fields already persisted in "
        "the sweep artifact -- no evaluation, no outcome read. See "
        "`docs/FACTORY_LIFECYCLE.md` for the exact rule.",
        "",
    ]
    if not reports:
        lines += ["No sweep artifacts found under "
                 "`data/research/evolab/sweep-*.json`. Nothing to classify.",
                 ""]
        return "\n".join(lines)

    for r in reports:
        lines.append(f"## `{r.get('_source_path')}`")
        lines.append("")
        families, states, reasons = classify_families(r)
        if not families:
            lines += [f"Not classified: {reasons[0]}", ""]
            continue
        n_retired = states.count("RETIRED")
        n_candidate = states.count("CANDIDATE-ELIGIBLE")
        lines += [
            f"Population battery verdict: **"
            f"{'PASS' if n_retired == 0 else 'FAIL'}**.",
            "",
        ]
        if reasons:
            lines.append("Reasons (already-persisted fields read):")
            for reason in reasons:
                lines.append(f"- {reason}")
            lines.append("")
        lines += [
            f"- families found: **{len(families):,}**",
            f"- RETIRED: **{n_retired:,}**",
            f"- CANDIDATE-ELIGIBLE (data does not rule them out -- NOT the "
            "same as admitted; admission needs a PreRegistration this "
            f"script has no authority to write): **{n_candidate:,}**",
            "",
            "This is a read of one already-existing population-level "
            "verdict applied uniformly to every family drawn from it -- "
            "there is no per-family fresh CSCV/SPA retest on record for "
            "any of them yet. See docs/FACTORY_LIFECYCLE.md for why this "
            "is the honest, conservative reading rather than a new "
            "judgement.",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    reports = _load_sweep_reports()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = _render(reports, generated_at)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(text + ("\n" if not text.endswith("\n") else ""))
    print(f"wrote {os.path.relpath(OUT_PATH, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
