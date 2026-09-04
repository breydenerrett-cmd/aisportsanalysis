"""Deterministic B6 population audit (counts-only) required by
docs/TOTALS_METHODOLOGY.md "## Methodology re-review -- 2026-09-05" (B6)
before any totals family registration.

NEVER reads, joins, or reports any outcome/score field (`total_runs`,
`won`, settlement of any kind). Every number in the output is a row count,
a distinct-value count, a quantile of timing metadata, or a bucket-occupancy
table. Re-running this script against unchanged input files is byte-
identical.

Reuses the nested snapshot -> events -> bookmakers -> markets -> outcomes
archive shape documented and parsed by scripts/totals_coverage_audit.py.

Definitions applied, per docs/TOTALS_METHODOLOGY.md "Revision 2":

  - Closing snapshot (R5/A7c): for each event, the latest snapshot with
    `snapshot_at` in `[commence_time - 12h, commence_time)`, where
    `commence_time` is read from THAT SAME snapshot's own event record
    (never a later/post-hoc schedule field) -- this is self-referential and
    leak-proof by construction. Events with no snapshot inside that window
    are excluded from every closing-snapshot-based count below; the
    exclusion count is published, never silently dropped.
  - Per-line book floor (R2): at the closing snapshot, a line is "floor-met"
    if >= 3 distinct bookmakers quote a totals outcome at that exact point
    value. A game meets the floor if any line at its closing snapshot is
    floor-met.
  - Closing consensus line (R5, "modal: diagnostic only"): the book-count-
    weighted mode of lines at the closing snapshot; ties broken toward 8.5,
    then toward the line closest to 8.5, then toward the smaller line value
    -- fixed in advance, matching sec 2.2 Decision A's tiebreak.
  - Half-point vs integer (R3): half-point if the consensus line's
    fractional part is exactly 0.5.
  - Rescheduled game: an event id for which more than one distinct
    `commence_time` value is recorded across its own snapshots.

Run: python3 scripts/totals_population_audit.py
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("TOTALS_AUDIT_DATA_ROOT", str(REPO)))
OUT = REPO / "docs" / "TOTALS_POPULATION_AUDIT.md"

MAX_STALENESS_HOURS = 12
SEASONS = (2023, 2024, 2025)  # 2025 reported separately, labelled TUNING_ONLY; no 2026.

LINE_BUCKET_EDGES = [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]  # deterministic, fixed in advance
BOOK_COUNT_BUCKET_EDGES = [1, 2, 3, 4, 5, 6]  # bucket k = "exactly k" for k<6, "6+" for the last


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


def _parse_ts(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _load_event_snapshots(season: int) -> dict:
    """Return {event_id: [(snapshot_at, commence_time, {line: set(book_keys)}), ...]}

    sorted by snapshot_at ascending. Only snapshots carrying at least one
    totals outcome for that event are recorded.
    """
    path = DATA_ROOT / "data" / "historical" / "odds_history" / f"mlb_{season}.jsonl"
    events: dict = defaultdict(list)
    for snapshot in _iter_jsonl(path):
        snap_at_raw = snapshot.get("snapshot_at")
        if not snap_at_raw:
            continue
        snap_at = _parse_ts(snap_at_raw)
        for event in snapshot.get("events") or []:
            eid = event.get("id")
            ct_raw = event.get("commence_time")
            if eid is None or not ct_raw:
                continue
            commence_time = _parse_ts(ct_raw)
            lines: dict = defaultdict(set)
            for book in event.get("bookmakers") or []:
                bk = book.get("key")
                if bk is None:
                    continue
                for market in book.get("markets") or []:
                    if market.get("key") != "totals":
                        continue
                    for outcome in market.get("outcomes") or []:
                        pt = outcome.get("point")
                        if pt is None:
                            continue
                        lines[pt].add(bk)
            if lines:
                events[eid].append((snap_at, commence_time, dict(lines)))
    for eid in events:
        events[eid].sort(key=lambda r: r[0])
    return dict(events)


def _pick_closing(records: list):
    """records sorted ascending by snapshot_at. Returns the chosen record
    (snapshot_at, commence_time, lines) or None if no snapshot falls inside
    [commence_time - 12h, commence_time) using that record's own
    commence_time."""
    for snap_at, commence_time, lines in reversed(records):
        window_start = commence_time - timedelta(hours=MAX_STALENESS_HOURS)
        if window_start <= snap_at < commence_time:
            return (snap_at, commence_time, lines)
    return None


def _modal_line(lines: dict) -> float:
    """Book-count-weighted mode; tie -> toward 8.5, then closest to 8.5,
    then smaller line value. `lines` maps point -> set(book_keys)."""
    counts = {pt: len(books) for pt, books in lines.items()}
    max_count = max(counts.values())
    tied = [pt for pt, c in counts.items() if c == max_count]
    if 8.5 in tied:
        return 8.5
    tied.sort(key=lambda pt: (abs(pt - 8.5), pt))
    return tied[0]


def _line_bucket(line: float) -> str:
    for edge in LINE_BUCKET_EDGES:
        if line < edge:
            return f"<{edge}"
    return f">={LINE_BUCKET_EDGES[-1]}"


def _book_count_bucket(n: int) -> str:
    if n >= BOOK_COUNT_BUCKET_EDGES[-1]:
        return f"{BOOK_COUNT_BUCKET_EDGES[-1]}+"
    return str(n)


def _quantile(sorted_vals: list, q: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def audit_season(season: int) -> dict:
    events = _load_event_snapshots(season)

    games_any_totals = len(events)
    rescheduled = 0
    excluded_no_closing_snapshot = 0

    games_floor_met = 0
    games_half_point = 0
    games_joint = 0

    gap_minutes: list = []
    line_bucket_counts = Counter()
    book_count_bucket_counts = Counter()

    for eid, records in events.items():
        distinct_commence = {ct for _, ct, _ in records}
        if len(distinct_commence) > 1:
            rescheduled += 1

        closing = _pick_closing(records)
        if closing is None:
            excluded_no_closing_snapshot += 1
            continue

        snap_at, commence_time, lines = closing
        gap_minutes.append((commence_time - snap_at).total_seconds() / 60.0)

        book_counts_by_line = {pt: len(books) for pt, books in lines.items()}
        max_books = max(book_counts_by_line.values())
        floor_met = max_books >= 3
        if floor_met:
            games_floor_met += 1

        modal_line = _modal_line(lines)
        is_half_point = (modal_line * 2) % 2 == 1
        if is_half_point:
            games_half_point += 1

        if floor_met and is_half_point:
            games_joint += 1

        line_bucket_counts[_line_bucket(modal_line)] += 1
        book_count_bucket_counts[_book_count_bucket(max_books)] += 1

    gap_minutes.sort()
    p50 = _quantile(gap_minutes, 0.50)
    p90 = _quantile(gap_minutes, 0.90)
    p99 = _quantile(gap_minutes, 0.99)
    gap_max = gap_minutes[-1] if gap_minutes else float("nan")

    # B5 proposed bound: smallest whole-hour bound covering >= 95% of
    # events with a closing snapshot, floored at 6h, capped at 24h.
    # Stated as a quantile derived purely from this timing distribution --
    # no outcome field is read to compute it.
    proposed_bound_hours = None
    if gap_minutes:
        for h in range(6, 25):
            cutoff = h * 60.0
            covered = sum(1 for g in gap_minutes if g <= cutoff) / len(gap_minutes)
            if covered >= 0.95:
                proposed_bound_hours = h
                break
        if proposed_bound_hours is None:
            proposed_bound_hours = 24

    return {
        "season": season,
        "games_any_totals": games_any_totals,
        "games_floor_met": games_floor_met,
        "games_half_point": games_half_point,
        "games_joint": games_joint,
        "excluded_no_closing_snapshot": excluded_no_closing_snapshot,
        "rescheduled": rescheduled,
        "gap_p50": p50,
        "gap_p90": p90,
        "gap_p99": p99,
        "gap_max": gap_max,
        "gap_n": len(gap_minutes),
        "proposed_bound_hours": proposed_bound_hours,
        "line_bucket_counts": dict(line_bucket_counts),
        "book_count_bucket_counts": dict(book_count_bucket_counts),
    }


def _fmt(v) -> str:
    if isinstance(v, float):
        if v != v:  # NaN
            return "n/a"
        return f"{v:.1f}"
    return str(v)


def render(results: dict) -> str:
    lines = []
    lines.append("# Totals Population Audit (B6)")
    lines.append("")
    lines.append(
        "Deterministic, counts-only output of "
        "`scripts/totals_population_audit.py`, produced for "
        "`docs/TOTALS_METHODOLOGY.md` \"## Methodology re-review -- "
        "2026-09-05\" item B6, ahead of any totals family registration. No "
        "outcome (`total_runs`, `won`, or any settlement field) is read, "
        "joined, or reported anywhere in this file. Re-running this script "
        "against unchanged input files reproduces this file byte-for-byte."
    )
    lines.append("")
    lines.append(
        f"Closing-snapshot definition: latest snapshot with `snapshot_at` "
        f"in `[commence_time - {MAX_STALENESS_HOURS}h, commence_time)`, "
        f"using `commence_time` from that same snapshot's own event record "
        f"(never a post-hoc schedule field), per R5/A7c. Per-line floor: "
        f">= 3 distinct books quoting the exact point value, per R2. "
        f"Half-point vs integer determined on the book-count-weighted modal "
        f"line (tiebreak toward 8.5, then closest to 8.5, then smaller "
        f"value), per R3/sec 2.2 Decision A. 2025 is TUNING_ONLY per "
        f"CLAUDE.md and reported separately; 2026 is SEALED and not read."
    )
    lines.append("")

    lines.append("## 1-4. Population counts")
    lines.append("")
    lines.append(
        "| season | (1) any totals quote | (2) floor met (>=3 books, "
        "per-line, at closing) | (3) half-point consensus | (4) joint "
        "(floor AND half-point) -- candidate denominator | excluded: no "
        "closing snapshot in window | (7) rescheduled games |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for season in SEASONS:
        r = results[season]
        label = f"{season}" if season != 2025 else "2025 (TUNING_ONLY)"
        lines.append(
            f"| {label} | {r['games_any_totals']} | {r['games_floor_met']} "
            f"| {r['games_half_point']} | {r['games_joint']} "
            f"| {r['excluded_no_closing_snapshot']} | {r['rescheduled']} |"
        )
    lines.append("")

    lines.append("## 5. Closing-line gap distribution (minutes, snapshot -> commence_time)")
    lines.append("")
    lines.append("| season | n (games with a closing snapshot) | p50 | p90 | p99 | max | proposed max-staleness bound (h) |")
    lines.append("|---|---|---|---|---|---|---|")
    for season in SEASONS:
        r = results[season]
        label = f"{season}" if season != 2025 else "2025 (TUNING_ONLY)"
        lines.append(
            f"| {label} | {r['gap_n']} | {_fmt(r['gap_p50'])} | "
            f"{_fmt(r['gap_p90'])} | {_fmt(r['gap_p99'])} | "
            f"{_fmt(r['gap_max'])} | {r['proposed_bound_hours']} |"
        )
    lines.append("")
    lines.append(
        "Proposed bound per B5: smallest whole-hour bound covering >= 95% "
        "of events with a closing snapshot, floored at 6h and capped at "
        "24h -- derived purely from this timing distribution (no outcome "
        "field read), stated here as a quantile per B5's required order "
        "(measure gap distribution first, freeze bound second, before any "
        "push/split re-measurement)."
    )
    lines.append("")

    lines.append("## 6. Bucket-occupancy tables (population-shift chi-square inputs, R1/B1)")
    lines.append("")
    lines.append(
        "Occupancy of the closing modal line and the per-line max book "
        "count, 2023 vs 2024 (the coverage-asymmetry seasons named in A2); "
        "2025 shown separately as TUNING_ONLY, not part of the 2023-vs-2024 "
        "chi-square. Bucket edges fixed in advance: line buckets "
        f"{LINE_BUCKET_EDGES}; book-count buckets exact 1-5, "
        f"{BOOK_COUNT_BUCKET_EDGES[-1]}+."
    )
    lines.append("")
    lines.append("### Line buckets (by closing modal line)")
    lines.append("")
    all_line_buckets = sorted(
        {b for season in SEASONS for b in results[season]["line_bucket_counts"]},
        key=lambda b: (0, float(b[1:])) if b.startswith("<") else (1, float(b[2:])),
    )
    header = "| bucket | " + " | ".join(
        f"{s}" if s != 2025 else "2025 (TUNING_ONLY)" for s in SEASONS
    ) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(SEASONS) + 1))
    for b in all_line_buckets:
        row = [b] + [str(results[s]["line_bucket_counts"].get(b, 0)) for s in SEASONS]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("### Book-count buckets (by per-line max book count at closing)")
    lines.append("")
    all_bc_buckets = sorted(
        {b for season in SEASONS for b in results[season]["book_count_bucket_counts"]},
        key=lambda b: (1, 0) if b.endswith("+") else (0, int(b)),
    )
    lines.append(header)
    lines.append("|" + "---|" * (len(SEASONS) + 1))
    for b in all_bc_buckets:
        row = [b] + [str(results[s]["book_count_bucket_counts"].get(b, 0)) for s in SEASONS]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append(
        "Source: `data/historical/odds_history/mlb_20{23,24,25}.jsonl`, "
        "parsed via the same nested snapshot -> events -> bookmakers -> "
        "markets -> outcomes structure as `scripts/totals_coverage_audit.py`."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    results = {season: audit_season(season) for season in SEASONS}
    OUT.write_text(render(results))
    print(f"wrote {OUT}")
    for season in SEASONS:
        r = results[season]
        print(
            f"{season}: any_totals={r['games_any_totals']} "
            f"floor_met={r['games_floor_met']} half_point={r['games_half_point']} "
            f"JOINT={r['games_joint']}"
        )


if __name__ == "__main__":
    main()
