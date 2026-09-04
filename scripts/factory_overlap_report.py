#!/usr/bin/env python3
"""Report script: unique-vs-total decision counts for the existing sweep output.

See docs/FACTORY_SCALE_DESIGN.md section 7. This script is deliberately
narrow: `sweep.py`'s `SweepReport.to_dict()` does not currently persist the
per-strategy decision sets (`WorldFitness.masks`) that `overlap.py` needs to
compute a real dedup/Jaccard number -- see FACTORY_SCALE_DESIGN.md section 0.
So this script reports what the on-disk sweep artifact(s) actually contain
(counts of strategies and worlds) plus an explicit, honest statement that
decision-level overlap is not yet computable from them, rather than
fabricating a number it cannot support. If no sweep artifact exists at all,
it says so and exits 0 -- this is a reporting script, not a gate, and an
absent input is not a failure.

Deterministic: iterates artifact filenames sorted, writes sorted keys, no
clock reads except a run timestamp on the report itself (which is metadata,
not something any test should hash).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWEEP_GLOB = os.path.join(REPO_ROOT, "data", "research", "evolab", "sweep-*.json")
OUT_PATH = os.path.join(REPO_ROOT, "docs", "FACTORY_OVERLAP_REPORT.md")


def _load_sweep_reports(pattern: str = SWEEP_GLOB) -> list[dict]:
    reports = []
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["_source_path"] = os.path.relpath(path, REPO_ROOT)
        reports.append(payload)
    return reports


def _render(reports: list[dict], generated_at: str) -> str:
    lines = [
        "# Factory overlap report",
        "",
        f"Generated {generated_at}. Counts only -- see "
        "`docs/FACTORY_SCALE_DESIGN.md` for the method and its limits.",
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
    lines += [
        "",
        "## Decision-level overlap: not yet computable",
        "",
        "`src/evolab/sweep.py`'s `SweepReport.to_dict()` stores per-world "
        "aggregate statistics (selection counts, mean movement/ROI) but does "
        "not persist the per-strategy decision sets "
        "(`WorldFitness.masks`) that `src/evolab/overlap.py`'s dedup and "
        "Jaccard clustering need. Unique-wagers-vs-total-decisions and "
        "family clustering (docs/FACTORY_SCALE_DESIGN.md sections 1.4 and 2) "
        "therefore cannot be computed from the artifact(s) above as they "
        "stand today. This is stated here rather than estimated, per this "
        "program's rule that absence is the honest answer over a guess.",
        "",
        "The total strategy count and total selection volume above are real "
        "counts from the sweep artifact(s); they are NOT a substitute for "
        "the unique-wager count and must not be read as effective sample "
        "size (see design section 3).",
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
