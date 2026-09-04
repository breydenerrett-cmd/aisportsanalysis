"""A1 feature-side audit: is every book's F5 moneyline genuinely two-way?

WHY THIS EXISTS
----------------
PREREG_F5_FAMILIES.md flaw A1: the gradeable set drops ties and compares
outcomes against a TWO-WAY de-vigged `p_home`. That is only valid if every
book's F5 moneyline is a genuine two-way, void-on-tie market. If any book in
the >=5-book consensus quotes a THREE-WAY line (home / away / draw), its
two-outcome de-vig silently renormalises away a real draw price, inflating
both sides' implied probabilities -- a measurement artefact of the de-vig,
not of the market.

This script enumerates the distinct outcome-name SETS actually quoted under
`h2h_1st_5_innings`, per book, across every OK game in the frozen primary
view, and reports any book that ever quoted three (or more) outcomes on a
graded game.

WHY THIS READS THE RAW STORE, NOT THE PRIMARY VIEW
----------------------------------------------------
`f5_tminus2_primary.jsonl` (built by `build_primary_view` /
`_books_projection`) already reduces every book's market to
`{away_price, home_price}` by matching each outcome's `name` against the
game's own away/home team names -- a genuine third outcome (e.g. "Draw")
would already have been silently dropped there, which is exactly the
failure mode A1 warns about. The raw outcome-NAME list survives only in
`F5_RAW_HISTORY` (`data/historical/odds_first_five/mlb_*.jsonl`), the same
source `build_primary_view` reads from, so this audit reads the raw store
directly, restricted to the same `snapshot_rule: "tminus2_v1"` rows and the
same `game_pk` set the primary view already carries as `status == "OK"`.
This is feature-side only: no settlement/outcome data is read.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paths import historical_path, repo_root

PRIMARY_VIEW_PATH = historical_path("odds_first_five", "f5_tminus2_primary.jsonl")
RAW_STORE = historical_path("odds_first_five")
SNAPSHOT_RULE = "tminus2_v1"
MARKET = "h2h_1st_5_innings"
MIN_BOOKS = 5
REPORT_PATH = repo_root() / "docs" / "F5_TIE_AUDIT.md"


def _read_jsonl(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _ok_game_pks(primary_path=PRIMARY_VIEW_PATH) -> set:
    return {str(r["game_pk"]) for r in _read_jsonl(primary_path)
            if r.get("status") == "OK"}


def audit(*, primary_path=PRIMARY_VIEW_PATH, raw_store=RAW_STORE) -> dict:
    """Per-book outcome-set-size counts, and any three-way (or wider) book.

    Returns a dict with:
      book_setsize_counts: {book_key: {set_size: game_count}}
      three_way_books: {book_key: sorted [game_pk, ...]} (games where that
        book quoted >= 3 distinct outcome names)
      ok_games: number of OK games in the primary view (the audited scope)
      gate_before: whether every OK-row book count was already >= MIN_BOOKS
        (read straight off the frozen manifest counts, not recomputed here)
    """
    ok_pks = _ok_game_pks(primary_path)
    book_setsize_counts = defaultdict(lambda: defaultdict(int))
    three_way_games = defaultdict(set)

    for season_file in sorted(Path(raw_store).glob("mlb_*.jsonl")):
        for row in _read_jsonl(season_file):
            if row.get("snapshot_rule") != SNAPSHOT_RULE:
                continue
            if row.get("status") != "OK":
                continue
            pk = str(row.get("game_pk"))
            if pk not in ok_pks:
                continue
            data = row.get("data") or {}
            for book in data.get("bookmakers") or []:
                key = book.get("key")
                for market_row in book.get("markets") or []:
                    if market_row.get("key") != MARKET:
                        continue
                    names = tuple(sorted(
                        o.get("name") for o in (market_row.get("outcomes") or [])))
                    book_setsize_counts[key][len(names)] += 1
                    if len(names) >= 3:
                        three_way_games[key].add(pk)

    return {
        "ok_games": len(ok_pks),
        "book_setsize_counts": {
            k: dict(v) for k, v in sorted(book_setsize_counts.items())},
        "three_way_books": {
            k: sorted(v, key=int) for k, v in sorted(three_way_games.items())},
    }


def gate_after_exclusion(*, primary_path=PRIMARY_VIEW_PATH,
                          three_way_books=None) -> dict:
    """Re-check the >=5-book gate after excluding any three-way book.

    Reads `book_count` and (when a three-way book was found) the per-book
    keys off the raw store, drops the excluded book key(s) from each game's
    count, and reports whether every OK game still clears MIN_BOOKS. When no
    three-way book exists this is a no-op restating the existing gate.
    """
    three_way_books = three_way_books or {}
    if not three_way_books:
        rows = [r for r in _read_jsonl(primary_path) if r.get("status") == "OK"]
        counts = [r.get("book_count") for r in rows if r.get("book_count") is not None]
        return {
            "excluded_books": [],
            "n_games": len(counts),
            "min_book_count_after_exclusion": min(counts) if counts else None,
            "all_ge_5_after_exclusion": all(c >= MIN_BOOKS for c in counts) if counts else None,
        }

    ok_pks = _ok_game_pks(primary_path)
    excluded_keys = set(three_way_books)
    counts_by_pk = {}
    for season_file in sorted(Path(RAW_STORE).glob("mlb_*.jsonl")):
        for row in _read_jsonl(season_file):
            if row.get("snapshot_rule") != SNAPSHOT_RULE or row.get("status") != "OK":
                continue
            pk = str(row.get("game_pk"))
            if pk not in ok_pks:
                continue
            data = row.get("data") or {}
            keys = set()
            for book in data.get("bookmakers") or []:
                for market_row in book.get("markets") or []:
                    if market_row.get("key") == MARKET and (market_row.get("outcomes") or []):
                        keys.add(book.get("key"))
                        break
            counts_by_pk[pk] = len(keys - excluded_keys)

    counts = list(counts_by_pk.values())
    return {
        "excluded_books": sorted(excluded_keys),
        "n_games": len(counts),
        "min_book_count_after_exclusion": min(counts) if counts else None,
        "all_ge_5_after_exclusion": all(c >= MIN_BOOKS for c in counts) if counts else None,
    }


def render_report(result: dict, gate: dict) -> str:
    lines = [
        "# F5 tie-settlement / three-way audit (A1)",
        "",
        "Feature-side only -- no settlement or outcome data read. Generated by "
        "`scripts/f5_tie_audit.py`.",
        "",
        f"OK games audited: **{result['ok_games']}**",
        "",
        "## Outcome-name set sizes per book (count of OK games)",
        "",
        "| book | set sizes seen (size: game count) |",
        "|---|---|",
    ]
    for book, sizes in result["book_setsize_counts"].items():
        sizes_str = ", ".join(f"{k}: {v}" for k, v in sorted(sizes.items()))
        lines.append(f"| {book} | {sizes_str} |")

    lines += ["", "## Three-way (or wider) books found", ""]
    if result["three_way_books"]:
        lines.append("| book | game_pks with >=3 outcomes |")
        lines.append("|---|---|")
        for book, pks in result["three_way_books"].items():
            lines.append(f"| {book} | {', '.join(pks)} |")
        lines.append("")
        lines.append(
            "**Any three-way book above is excluded from the consensus in "
            "`src/research/f5_eval.py`, per A1.**")
    else:
        lines.append(
            "**None.** Every book quoted exactly a two-outcome "
            "`h2h_1st_5_innings` market on every audited game. The two-way "
            "de-vig convention is valid as-is; no exclusion required.")

    lines += ["", "## >=5-book gate, re-checked after exclusion", ""]
    if gate["excluded_books"]:
        lines.append(f"Excluded book(s): {', '.join(gate['excluded_books'])}")
    else:
        lines.append("No book excluded (none was three-way).")
    lines.append(f"- games checked: {gate['n_games']}")
    lines.append(f"- minimum book count after exclusion: "
                 f"{gate['min_book_count_after_exclusion']}")
    lines.append(f"- all games still >= {MIN_BOOKS} books: "
                 f"{gate['all_ge_5_after_exclusion']}")
    lines.append("")
    return "\n".join(lines)


def main():
    result = audit()
    gate = gate_after_exclusion(three_way_books=result["three_way_books"])
    report = render_report(result, gate)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(f"three_way_books: {result['three_way_books'] or 'none'}")
    print(f"gate_after_exclusion: {gate}")


if __name__ == "__main__":
    main()
