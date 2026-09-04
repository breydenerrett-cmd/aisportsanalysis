#!/usr/bin/env python3
"""Report script: real unique-vs-total decision overlap for the sweep output.

See docs/FACTORY_SCALE_DESIGN.md sections 1.4, 2, 3. `sweep.py`'s
`SweepReport.to_dict()` did not persist per-strategy decision sets when this
script was first written (section 0's named gap); that gap is closed two
ways now: (1) `sweep.py` serializes `decision_masks` on every FUTURE sweep
(`include_masks`, default ON), and (2) `scripts/factory_masks_from_sweep.py`
backfills the masks for the one REAL artifact that already existed before
that flag landed, as `data/research/evolab/masks-<spec_hash16>.bin` + a
`.index.json` sidecar. This script reads either source and reports real
counts and overlap; when NEITHER is available for an artifact, it says so
explicitly rather than fabricating a number (unchanged from before).

WHY POPCOUNTS, NOT `overlap.py`'s STRING-SET API DIRECTLY
------------------------------------------------------------
`overlap.py` (`jaccard`, `pairwise_jaccard`, `cluster_families`) defines the
METHOD -- Jaccard on `{wager_id}` sets, `FAMILY_THRESHOLD = 0.8`,
single-linkage families -- against the smallest sufficient input shape
(`{strategy_id: {wager_id}}`) precisely so it never has to know about a
bitmask. That generality costs O(n^2) SET operations, which is fine at the
scale its own tests run and much too slow at 8,811 strategies with a median
~836 selections apiece (measured: ~38.8M pairs x hashing ~1,000-element
string sets each -- hours, not the ~30-minute budget this slice has). Every
strategy's decision set is already exactly two disjoint bitmasks over the
SAME world (away/home x game index), so this script folds them into one
`2 * n_games`-bit integer per strategy (away bits, then home bits) and uses
Python's native `int.bit_count()` for popcount-based intersection/union --
mathematically the identical Jaccard `overlap.jaccard` computes (both reduce
to "how many wager positions do the two decision sets share"), just computed
over machine words instead of hashed strings. `overlap.FAMILY_THRESHOLD`
and `overlap.effective_n`'s formula are imported and used AS-IS: only the
O(n^2) inner loop's representation changes, never the method or the
threshold.

Deterministic: iterates artifact/index filenames sorted, writes sorted keys,
no clock reads except a run timestamp on the report itself (metadata, not
something any test should hash).
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
OUT_PATH = os.path.join(REPO_ROOT, "docs", "FACTORY_OVERLAP_REPORT.md")

# How many of the largest families to name in the report -- enough to show
# the shape of the redundancy without dumping thousands of one-line rows for
# a population this size.
TOP_FAMILIES_SHOWN = 15


def _load_sweep_reports(pattern: str = SWEEP_GLOB) -> list[dict]:
    reports = []
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["_source_path"] = os.path.relpath(path, REPO_ROOT)
        reports.append(payload)
    return reports


def _masks_paths_for(spec_hash: str) -> tuple[str, str] | None:
    """(index_path, bin_path) for `spec_hash`'s backfilled masks, or None."""
    stem = os.path.join(EVOLAB_DIR, f"masks-{spec_hash[:16]}")
    index_path, bin_path = f"{stem}.index.json", f"{stem}.bin"
    if os.path.exists(index_path) and os.path.exists(bin_path):
        return index_path, bin_path
    return None


def _load_combined_masks(index_path: str, bin_path: str
                         ) -> tuple[dict, list[str], int]:
    """{strategy_id: combined_int}, strategy_order, n_games.

    `combined_int` packs away bits (low `n_games` bits) then home bits (next
    `n_games` bits) -- one integer whose popcount IS the strategy's total
    decision count and whose pairwise AND/OR popcounts ARE Jaccard's
    intersection/union, with no per-pair set construction.
    """
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
    return combined, strategy_order, n_games


def _find(parent: dict, x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict, a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def _overlap_from_combined(combined: dict[str, int]
                           ) -> tuple["overlap.DedupStats", list[list[str]],
                                     "overlap.EffectiveN"]:
    """Dedup stats, families (>= overlap.FAMILY_THRESHOLD), effective N --
    same method `overlap.py` states, computed over popcounts (see module
    docstring)."""
    ids = sorted(combined)
    n_strategies = len(ids)
    total_decisions = sum(v.bit_count() for v in combined.values())

    union_all = 0
    for v in combined.values():
        union_all |= v
    unique_wagers = union_all.bit_count()
    dedup = overlap.DedupStats(n_strategies=n_strategies,
                               total_decisions=total_decisions,
                               unique_wagers=unique_wagers)

    parent = {i: i for i in ids}
    threshold = overlap.FAMILY_THRESHOLD
    for i, a in enumerate(ids):
        ca = combined[a]
        for b in ids[i + 1:]:
            cb = combined[b]
            union_bits = (ca | cb).bit_count()
            if union_bits == 0:
                continue
            inter_bits = (ca & cb).bit_count()
            if inter_bits / union_bits >= threshold:
                _union(parent, a, b)

    groups: dict[str, list[str]] = {}
    for i in ids:
        root = _find(parent, i)
        groups.setdefault(root, []).append(i)
    families = [sorted(members) for members in groups.values()]
    families.sort(key=lambda fam: (-len(fam), fam[0]))

    return dedup, families, overlap.effective_n(families)


def _render(reports: list[dict], generated_at: str) -> str:
    lines = [
        "# Factory overlap report",
        "",
        f"Generated {generated_at}. Counts and overlap only -- no "
        "returns/ROI -- see `docs/FACTORY_SCALE_DESIGN.md` for the method "
        "and its limits.",
        "",
    ]
    if not reports:
        lines += [
            "No sweep output found under `data/research/evolab/sweep-*.json`. "
            "Nothing to report.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        f"Found {len(reports)} sweep artifact(s).",
        "",
        "| artifact | world | n_strategies | n_games | real_champion |",
        "|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.get('_source_path')}` | {r.get('real_world_id')} | "
            f"{r.get('n_strategies_real')} | {r.get('n_games_real')} | "
            f"{r.get('real_champion')} |")
    lines.append("")

    any_computed = False
    for r in reports:
        spec_hash = r.get("enumeration_spec_hash", "")
        masks_paths = _masks_paths_for(spec_hash)
        has_inline_masks = bool(r.get("decision_masks"))
        lines.append(f"## `{r.get('_source_path')}`")
        lines.append("")

        if has_inline_masks:
            from src.evolab.sweep import decode_masks
            decoded = decode_masks(r["decision_masks"])
            n_games = r["decision_masks"]["n_games"]
            combined = {sid: away | (home << n_games)
                       for sid, (away, home) in decoded.items()}
            source_note = "decoded from this artifact's own `decision_masks`"
        elif masks_paths:
            index_path, bin_path = masks_paths
            combined, _order, n_games = _load_combined_masks(index_path, bin_path)
            source_note = (f"backfilled from `{os.path.relpath(index_path, REPO_ROOT)}`"
                           f" + `{os.path.relpath(bin_path, REPO_ROOT)}`"
                           " (see `scripts/factory_masks_from_sweep.py`)")
        else:
            lines += [
                "Decision-level overlap: **not yet computable.** No "
                "`decision_masks` on this artifact and no backfilled "
                f"`masks-{spec_hash[:16]}.{{bin,index.json}}` found under "
                "`data/research/evolab/`. Stated here rather than "
                "estimated, per this program's rule that absence is the "
                "honest answer over a guess.",
                "",
            ]
            continue

        any_computed = True
        dedup, families, eff = _overlap_from_combined(combined)
        lines += [
            f"Decision-level overlap computed ({source_note}).",
            "",
            f"- unique wagers: **{dedup.unique_wagers:,}**",
            f"- total decisions: **{dedup.total_decisions:,}** "
            f"(across {dedup.n_strategies:,} strategies)",
            f"- dedup ratio (unique / total): **{dedup.dedup_ratio:.4f}**",
            f"- families at Jaccard >= {overlap.FAMILY_THRESHOLD} "
            f"(single-linkage, `overlap.FAMILY_THRESHOLD`): "
            f"**{eff.n_families:,}**",
            f"- N_effective_families: **{eff.n_families:,}**",
            f"- N_effective_credit (heuristic, NOT calibrated -- design "
            f"section 3): **{eff.credit:.2f}**",
            "",
            f"Largest {min(TOP_FAMILIES_SHOWN, len(families))} of "
            f"{len(families):,} families (by member count):",
            "",
            "| rank | family size | example strategy_id |",
            "|---|---|---|",
        ]
        for rank, fam in enumerate(families[:TOP_FAMILIES_SHOWN], start=1):
            lines.append(f"| {rank} | {len(fam):,} | `{fam[0]}` |")
        lines.append("")

    if any_computed:
        lines += [
            "N_effective_credit is a diminishing-returns heuristic "
            "(`1 + log2(family_size)` summed over families), not a "
            "calibrated effective-sample-size estimator -- see design "
            "section 3. Family count is the primary, assumption-free "
            "statistic. Neither number is a CSCV/SPA substitute or a "
            "promotion gate.",
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    reports = _load_sweep_reports()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = _render(reports, generated_at)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.write("\n")
    if not reports:
        print(f"no sweep output found; wrote {OUT_PATH} saying so")
    else:
        print(f"wrote {OUT_PATH} covering {len(reports)} sweep artifact(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
