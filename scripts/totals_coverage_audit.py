"""Deterministic totals-quote coverage audit.

Counts only -- never joins any price to an outcome. Reports quote-row
counts and structural coverage (season, book, line, market_key) across the
three totals data sources named in docs/TOTALS_METHODOLOGY.md section 0.
Writes docs/TOTALS_COVERAGE.md.

Sources:
  - data/historical/odds_history/mlb_20{23,24,25}.jsonl (discovery-window archive)
  - data/processed/odds_multibook.jsonl (forward capture, market-tagged)
  - data/processed/l1_observations.jsonl (forward capture, market_key-tagged;
    2026 rows fall inside the sealed window per CLAUDE.md -- this script
    reports counts/schema shape only, never a date-by-date breakdown that
    would reveal within-window structure, and never touches any outcome
    field).

Run: python3 scripts/totals_coverage_audit.py
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# DATA_ROOT lets this script be pointed at a sibling checkout that holds the
# real (gitignored, large) data/ directory when run from a worktree that
# only carries tracked files -- output always writes into THIS repo's docs/.
DATA_ROOT = Path(os.environ.get("TOTALS_AUDIT_DATA_ROOT", str(REPO)))
OUT = REPO / "docs" / "TOTALS_COVERAGE.md"


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def audit_archive(season: int) -> dict:
    """Each JSONL line is one snapshot: {"events": [...], "snapshot_at": ...}.

    Each event carries `bookmakers` -> `markets` (keyed "h2h"/"totals") ->
    `outcomes` (Over/Under, each with its own `point` and `price`). One
    Over or Under outcome at one book at one snapshot is one "totals
    outcome row" -- matching docs/RESEARCH_V7_TOTALS.md section 1.1's own
    definition (a book-quote row, two per book-quote-pair).
    """
    path = DATA_ROOT / "data" / "historical" / "odds_history" / f"mlb_{season}.jsonl"
    events = set()
    books = set()
    lines = set()
    outcome_rows = 0
    dates = []
    for snapshot in _iter_jsonl(path):
        for event in snapshot.get("events") or []:
            eid = event.get("id")
            d = event.get("commence_time")
            saw_totals_for_event = False
            for book in event.get("bookmakers") or []:
                bk = book.get("key")
                for market in book.get("markets") or []:
                    if market.get("key") != "totals":
                        continue
                    for outcome in market.get("outcomes") or []:
                        outcome_rows += 1
                        saw_totals_for_event = True
                        if bk is not None:
                            books.add(bk)
                        pt = outcome.get("point")
                        if pt is not None:
                            lines.add(pt)
            if saw_totals_for_event:
                if eid is not None:
                    events.add(eid)
                if d:
                    dates.append(str(d)[:10])
    return {
        "season": season,
        "path": str(path.relative_to(DATA_ROOT)),
        "outcome_rows": outcome_rows,
        "events": len(events),
        "books": len(books),
        "distinct_lines": len(lines),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
    }


def audit_odds_multibook() -> dict:
    path = DATA_ROOT / "data" / "processed" / "odds_multibook.jsonl"
    by_market = Counter()
    for row in _iter_jsonl(path):
        by_market[row.get("market") or "untagged"] += 1
    return {"path": str(path.relative_to(DATA_ROOT)), "by_market": dict(by_market)}


def audit_l1_observations() -> dict:
    path = DATA_ROOT / "data" / "processed" / "l1_observations.jsonl"
    by_market = Counter()
    totals_books = set()
    totals_lines_present = 0
    total_rows = 0
    for row in _iter_jsonl(path):
        total_rows += 1
        mk = row.get("market_key") or "untagged"
        by_market[mk] += 1
        if mk == "totals":
            if row.get("book"):
                totals_books.add(row["book"])
            if row.get("line") is not None:
                totals_lines_present += 1
    return {
        "path": str(path.relative_to(DATA_ROOT)),
        "total_rows": total_rows,
        "by_market_key": dict(by_market),
        "totals_distinct_books": len(totals_books),
        "totals_rows_with_line_set": totals_lines_present,
    }


def main() -> None:
    archive = [audit_archive(s) for s in (2023, 2024, 2025)]
    multibook = audit_odds_multibook()
    l1 = audit_l1_observations()

    lines = []
    lines.append("# Totals Coverage Audit")
    lines.append("")
    lines.append(
        "Deterministic, counts-only output of "
        "`scripts/totals_coverage_audit.py`. No outcome is joined to any "
        "price anywhere in this file -- every number below is a row count, "
        "a distinct-value count, or a date range. Generated as an input to "
        "`docs/TOTALS_METHODOLOGY.md`."
    )
    lines.append("")
    lines.append("## Archive: `data/historical/odds_history/mlb_20{23,24,25}.jsonl`")
    lines.append("")
    lines.append(
        "| season | totals outcome rows | events | date range | books | distinct lines |"
    )
    lines.append("|---|---|---|---|---|---|")
    for a in archive:
        rng = f"{a['date_min']} .. {a['date_max']}" if a["date_min"] else "n/a"
        lines.append(
            f"| {a['season']} | {a['outcome_rows']} | {a['events']} | {rng} "
            f"| {a['books']} | {a['distinct_lines']} |"
        )
    lines.append("")
    lines.append(
        f"Source file(s): `{archive[0]['path']}`, `{archive[1]['path']}`, "
        f"`{archive[2]['path']}`."
    )
    lines.append("")
    lines.append("## Forward capture: `data/processed/odds_multibook.jsonl`")
    lines.append("")
    lines.append("| market tag | rows |")
    lines.append("|---|---|")
    for mkt, cnt in sorted(multibook["by_market"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {mkt} | {cnt} |")
    lines.append("")
    lines.append(f"Source: `{multibook['path']}`.")
    lines.append("")
    lines.append(
        "## Forward capture: `data/processed/l1_observations.jsonl` "
        "(counts only -- includes rows inside the sealed 2026 window; "
        "no date breakdown or outcome given, structural counts only)"
    )
    lines.append("")
    lines.append(f"Total rows: {l1['total_rows']}")
    lines.append("")
    lines.append("| market_key | rows |")
    lines.append("|---|---|")
    for mkt, cnt in sorted(l1["by_market_key"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {mkt} | {cnt} |")
    lines.append("")
    lines.append(
        f"`totals` rows with a non-null `line` field: "
        f"{l1['totals_rows_with_line_set']}. Distinct books quoting "
        f"`totals`: {l1['totals_distinct_books']}."
    )
    lines.append("")
    lines.append(f"Source: `{l1['path']}`.")
    lines.append("")
    lines.append(
        "This file establishes forward capture depth only. The "
        "2023-2025 discovery/replication window used by any totals family "
        "is the archive table above -- l1_observations rows dated in the "
        "sealed window (2026-01-01 onward) must never be read for content "
        "beyond this structural count."
    )
    lines.append("")

    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
