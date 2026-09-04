"""Frozen, hashed manifest of the eligible F5-moneyline research universe.

WHY THIS EXISTS
----------------
`docs/RESEARCH_CATALOGUE.md` T8 ("no rescue by threshold change") and T4 (a
whole results set invalidated by a silent join defect) are both failures of
the same shape: a denominator that could move, quietly, after someone had
already seen a result. This module freezes the denominator BEFORE any
hypothesis is evaluated, and gives it a content hash so any later widening
or narrowing -- adding games, dropping games, reclassifying a tie -- is
mechanically detectable rather than something a reviewer has to notice by
eye.

WHAT "ELIGIBLE" MEANS HERE
----------------------------
Every row of `F5_TMINUS2_PRIMARY` (`src.pipeline.f5_tminus2.build_primary_view`,
read from `data/historical/odds_first_five/f5_tminus2_primary.jsonl`) that
survived `src.research.f5_eligibility` -- i.e. the full named universe for
the approved 2023-05-10..2024-10-07 discovery window, INCLUDING the
`PRIMARY_SNAPSHOT_UNAVAILABLE` rows (PREREG_F5_SNAPSHOT_RULE.md section 5:
"the denominator for any later evaluation is the full named universe, not
just the games that happened to price"). Eligibility for the universe is
therefore about the SNAPSHOT (was this game's T-2h price acquisition
in-window and not tuning/sealed), not about whether a price was obtained.

The GRADEABLE subset (what any hypothesis actually evaluates against) is
strictly narrower: `status == "OK"` (a price exists) AND `decided is True`
(the first five innings did not end level). That subset is exactly what
`docs/F5_NORMALIZATION_REPORT.md` and the mission brief call "3,682 decided
games."

NO OUTCOME IS INTERPRETED HERE
--------------------------------
`decided` / `tie` are read directly off `data/historical/first_five_results.jsonl`
(`winner in {"home","away"}` vs `winner is None` on a `complete` record) --
these are settlement FACTS needed to define gradeability, not a computed
win rate, ROI, or any measure of whether a side would have profited. This
module never reads price direction, never compares an implied probability
to an outcome, and never ranks or scores anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.paths import data_path, historical_path
from src.research import f5_eligibility

PRIMARY_VIEW_PATH = historical_path("odds_first_five", "f5_tminus2_primary.jsonl")
SETTLEMENT_PATH = historical_path("first_five_results.jsonl")
RAW_STORE = historical_path("odds_first_five")
MANIFEST_PATH = data_path("research", "f5", "universe_frozen.json")

SNAPSHOT_RULE = "tminus2_v1"


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


def _load_settlement(path=SETTLEMENT_PATH) -> dict:
    return {str(r["game_pk"]): r for r in _read_jsonl(path)}


def content_hash(games: list) -> str:
    """Deterministic sha256 over the sorted eligible game_pk set.

    Sorted numerically (game_pk is a numeric StatsAPI id carried as a
    string) so ordering never depends on read order or dict iteration.
    Hashing only the identity of the set (not status/decided/etc.) means
    this hash answers exactly one question -- "is this the same set of
    games" -- and nothing about how any individual game later gets
    classified. A change in composition (widen or narrow) changes the hash;
    a change in how a game is being interpreted downstream does not, by
    design (that is a different check).
    """
    pks = sorted(int(g["game_pk"]) for g in games)
    payload = json.dumps(pks, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def price_payload_hash(rows: list) -> str:
    """Deterministic sha256 over the PRICED PAYLOAD of the primary view --
    per `game_pk`: `snapshot_at`, and each book's key plus both prices,
    canonically ordered.

    A3 (PREREG_F5_FAMILIES.md): the identity hash (`content_hash`) proves
    which games are in the set, not what price each carries -- a re-fetch or
    repair could rewrite every book price without moving that hash by a bit.
    This hash answers the other half: is this the same set of PRICES. Books
    are sorted by `key` (never trust provider ordering) and only `key` +
    both prices are hashed (never `last_update`, which drifts on a harmless
    re-fetch that changes nothing a hypothesis reads). Rows with no `books`
    (an UNAVAILABLE row) still contribute their `game_pk` and `snapshot_at`
    so the hash also proves the shape of the priced/unpriced split, not just
    the OK rows.
    """
    entries = []
    for row in rows:
        books = []
        for book in row.get("books") or []:
            market = book.get("h2h_1st_5_innings") or {}
            books.append({
                "key": book.get("key"),
                "away_price": market.get("away_price"),
                "home_price": market.get("home_price"),
            })
        books.sort(key=lambda b: (b["key"] is None, b["key"]))
        entries.append({
            "game_pk": str(row.get("game_pk")),
            "snapshot_at": row.get("snapshot_at"),
            "books": books,
        })
    entries.sort(key=lambda e: int(e["game_pk"]))
    payload = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_universe(*, primary_path=PRIMARY_VIEW_PATH, settlement_path=SETTLEMENT_PATH,
                    raw_store=RAW_STORE) -> dict:
    """Recompute the frozen manifest from source data. Deterministic: same
    inputs always produce the same manifest and the same hash.
    """
    primary_rows = _read_jsonl(primary_path)
    settlement = _load_settlement(settlement_path)

    games = []
    joined = 0
    not_joined = []
    for row in primary_rows:
        pk = str(row["game_pk"])
        date = row.get("date")
        season = str(date)[:4] if date else None
        settled = settlement.get(pk)
        decided = None
        tie = None
        complete = None
        if settled is not None:
            joined += 1
            complete = settled.get("complete")
            if complete:
                winner = settled.get("winner")
                if winner in ("home", "away"):
                    decided = True
                    tie = False
                else:
                    decided = False
                    tie = True
            else:
                decided = False
                tie = False
        else:
            not_joined.append(pk)

        games.append({
            "game_pk": pk,
            "date": date,
            "season": season,
            "status": row.get("status"),
            "reason": row.get("reason"),
            "settlement_joined": settled is not None,
            "complete": complete,
            "decided": decided,
            "tie": tie,
        })

    games.sort(key=lambda g: int(g["game_pk"]))

    ok_games = [g for g in games if g["status"] == "OK"]
    unavailable_games = [g for g in games if g["status"] == "PRIMARY_SNAPSHOT_UNAVAILABLE"]
    gradeable = [g for g in ok_games if g["decided"] is True]
    ok_ties = [g for g in ok_games if g["tie"] is True]
    ok_not_complete = [g for g in ok_games
                        if g["settlement_joined"] and g["complete"] is False]

    gradeable_by_season = {}
    for g in gradeable:
        gradeable_by_season[g["season"]] = gradeable_by_season.get(g["season"], 0) + 1

    # Book depth over OK rows, recomputed from the primary view's own
    # `book_count` field (which build_primary_view derives from the
    # unique book keys in `books`, not asserted independently here).
    book_counts = sorted(r.get("book_count") for r in primary_rows
                          if r.get("status") == "OK" and r.get("book_count") is not None)
    n_bc = len(book_counts)
    median_books = (book_counts[n_bc // 2] if n_bc % 2 == 1
                    else (book_counts[n_bc // 2 - 1] + book_counts[n_bc // 2]) / 2) if n_bc else None
    min_books_ge5 = all(c >= 5 for c in book_counts) if book_counts else None

    # Exclusion ledger: every tminus2_v1 raw-history row and why it did or
    # did not enter the eligible universe. This walks F5_RAW_HISTORY
    # directly (not the already-filtered primary view) so the ledger
    # accounts for every attempted game, including the ones the
    # eligibility boundary removed before build_primary_view ever wrote
    # them into f5_tminus2_primary.jsonl.
    raw_rows = []
    for season_file in sorted(Path(raw_store).glob("mlb_*.jsonl")):
        raw_rows.extend(_read_jsonl(season_file))
    tminus2_raw = [r for r in raw_rows if r.get("snapshot_rule") == SNAPSHOT_RULE]

    exclusion_ledger = {
        "tuning_only_2025": 0,
        "sealed_2026": 0,
        "outside_approved_window": 0,
        "date_missing": 0,
    }
    eligible_raw_count = 0
    for r in tminus2_raw:
        verdict = f5_eligibility.eligibility(r.get("date"))
        if verdict["eligible"]:
            eligible_raw_count += 1
        else:
            reason = verdict["reason"]
            exclusion_ledger[reason] = exclusion_ledger.get(reason, 0) + 1

    total_excluded = sum(exclusion_ledger.values())

    manifest = {
        "schema_version": 1,
        "snapshot_rule": SNAPSHOT_RULE,
        "approved_window": {
            "start": f5_eligibility.APPROVED_WINDOW_START,
            "end": f5_eligibility.APPROVED_WINDOW_END,
        },
        "source": {
            "primary_view": str(primary_path),
            "settlement": str(settlement_path),
            "raw_store": str(raw_store),
        },
        "counts": {
            "raw_tminus2_v1_attempts": len(tminus2_raw),
            "eligible_total": len(games),
            "eligible_total_recomputed_matches_raw_minus_excluded":
                len(games) == eligible_raw_count,
            "status_OK": len(ok_games),
            "status_PRIMARY_SNAPSHOT_UNAVAILABLE": len(unavailable_games),
            "settlement_joined": joined,
            "settlement_join_rate": (joined / len(games)) if games else None,
            "not_joined_game_pks": not_joined,
            "OK_book_count_min": book_counts[0] if book_counts else None,
            "OK_book_count_median": median_books,
            "OK_book_count_all_ge_5": min_books_ge5,
            "OK_ties": len(ok_ties),
            "OK_not_complete_void": len(ok_not_complete),
            "gradeable_decided": len(gradeable),
            "gradeable_by_season": gradeable_by_season,
            "eligible_by_season": {
                s: sum(1 for g in games if g["season"] == s)
                for s in sorted({g["season"] for g in games if g["season"]})
            },
        },
        "exclusion_ledger": {
            "rules": exclusion_ledger,
            "total_excluded": total_excluded,
            "raw_attempts_accounted": eligible_raw_count + total_excluded == len(tminus2_raw),
        },
        "games": games,
    }
    manifest["content_hash"] = content_hash(games)
    # A3 amendment: the identity hash proves which games, not what prices --
    # this proves the priced payload too, and is re-verified at run time by
    # src/research/f5_eval.py before any statistic is computed.
    manifest["price_payload_hash"] = price_payload_hash(primary_rows)
    return manifest


def write_manifest(manifest: dict, path=MANIFEST_PATH) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(target)


def read_manifest(path=MANIFEST_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    m = build_universe()
    p = write_manifest(m)
    print(f"wrote {p}")
    print(f"content_hash={m['content_hash']}")
    print(json.dumps(m["counts"], indent=2))
    print(json.dumps(m["exclusion_ledger"], indent=2))
