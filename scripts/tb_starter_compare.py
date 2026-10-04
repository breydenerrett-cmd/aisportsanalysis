"""Run the pre-registered starter-aware total-bases comparison for one season.

THE CRITERION IS IN `docs/PREREG_TB_STARTER_AWARE.md` AND WAS COMMITTED FIRST.
This script chooses no threshold, population or decision rule; all of those
are fixed in the document and in `src/research/tb_starter.py`.

    python scripts/tb_starter_compare.py --season 2023
    python scripts/tb_starter_compare.py --season 2024
    python scripts/tb_starter_compare.py --season 2023 --time-slice 1000

`--time-slice N` prices the first N eligible rows, prints the elapsed time and
a projection, and prints NO metric and writes NO artifact.

2025 is tuning-only and 2026-01-01..2026-08-27 is sealed: any other season is
a hard error, the box-score path is built only AFTER the season passes the
guard, and the 2025 box file is never opened. `pitcher_logs.jsonl`,
`lineups.jsonl` and `mlb_results.csv` hold dates outside 2023-2024 too; they are
STREAMED and every row outside 2023-01-01..2024-12-31 is dropped on the spot,
never kept, counted, aggregated or printed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.research import tb_starter as tbs  # noqa: E402
from src.research.alpha_registry import git_blob_hash  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOX_ARCHIVE_DIR = os.path.join("data", "archive", "historical", "boxscores")
BOX_SHA256SUMS = os.path.join("data", "archive", "historical", "SHA256SUMS")
LINEUPS_PATH = os.path.join("data", "historical", "lineups.jsonl")
RESULTS_PATH = os.path.join("data", "historical", "mlb_results.csv")
PITCHER_LOGS_PATH = os.path.join("data", "historical", "pitcher_logs.jsonl")
FROZEN_PARAMS_PATH = os.path.join("data", "processed",
                                  "card_v2_frozen_params.json")
OUT_DIR = os.path.join("data", "research", "tb_starter")
RULE_ID = "TB_STARTER_AWARE_V1"


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def _open_text(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8", newline="")


def stream_jsonl(path):
    with _open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _digest(rows):
    h = hashlib.sha256()
    n = 0
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, separators=(",", ":"),
                            default=str).encode("utf-8"))
        h.update(b"\n")
        n += 1
    return {"rows": n, "sha256": h.hexdigest()}


def _in_window_rows(path):
    """Stream a mixed-season jsonl, keeping ONLY in-window rows.

    A row outside 2023-01-01..2024-12-31 is dropped the moment it is parsed:
    not appended, not tallied, not printed. Rows with no date (bookkeeping
    markers) are kept so their consumer can skip them explicitly.
    """
    kept = []
    for row in stream_jsonl(path):
        date = row.get("date")
        if date is None:
            kept.append(row)
        elif tbs.in_window(str(date)):
            kept.append(row)
    return kept


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _verify_box_archive(season, path):
    """The tracked archive is checksummed in SHA256SUMS; refuse a mismatch."""
    name = f"boxscores/boxscores_{season}.jsonl.gz"
    expected = None
    with open(_abs(BOX_SHA256SUMS), "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2 and parts[1] == name:
                expected = parts[0]
    if expected is None:
        raise tbs.TbStarterError(f"{name} has no entry in {BOX_SHA256SUMS}")
    actual = _sha256_file(path)
    if actual != expected:
        raise tbs.TbStarterError(
            f"{path} sha256 {actual} does not match SHA256SUMS {expected}")
    return actual


def load_results():
    """game_pk -> result row, in-window rows only."""
    out = {}
    with open(_abs(RESULTS_PATH), "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not tbs.in_window(row.get("date")):
                continue
            out[int(row["game_pk"])] = row
    return out


def run(season, *, limit=None, box_path=None):
    """Build the scored rows for one season. Returns (rows, counts, meta)."""
    season = tbs.assert_allowed_season(season)       # BEFORE any path exists
    started = time.time()
    meta = {"rule_id": RULE_ID, "season": season, "inputs": {}}

    if box_path is None:
        box_path = _abs(os.path.join(BOX_ARCHIVE_DIR,
                                     f"boxscores_{season}.jsonl.gz"))
        meta["inputs"]["box_archive_file_sha256"] = _verify_box_archive(
            season, box_path)
    box_rows = list(stream_jsonl(box_path))
    meta["inputs"]["box_path"] = os.path.relpath(box_path, REPO_ROOT)
    meta["inputs"]["box_rows_digest"] = _digest(box_rows)

    results = load_results()
    meta["inputs"]["results_in_window_digest"] = _digest(
        results[k] for k in sorted(results))

    lineups = _in_window_rows(_abs(LINEUPS_PATH))
    meta["inputs"]["lineups_in_window_digest"] = _digest(lineups)
    slot_map, slot_stats = tbs.build_slot_map(lineups)
    meta["lineup_stats"] = slot_stats

    pitchers = _in_window_rows(_abs(PITCHER_LOGS_PATH))
    meta["inputs"]["pitcher_logs_in_window_digest"] = _digest(pitchers)
    starters = tbs.StarterIndex(pitchers)
    meta["pitcher_log_skipped"] = starters.skipped

    with open(_abs(FROZEN_PARAMS_PATH), "r", encoding="utf-8") as fh:
        params = json.load(fh)
    slot_table = tbs.slot_table_from_frozen(params)
    meta["slot_table"] = {str(k): v for k, v in sorted(slot_table.items())}
    meta["slot_table_fit_season"] = params.get("season")
    meta["load_seconds"] = round(time.time() - started, 2)

    priced_started = time.time()
    built = tbs.build_comparison_rows(
        season=season, box_rows=box_rows, results=results, slot_map=slot_map,
        starters=starters, slot_table=slot_table, limit=limit)
    meta["price_seconds"] = round(time.time() - priced_started, 2)
    return built["rows"], built["counts"], meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", required=True)
    ap.add_argument("--time-slice", type=int, default=None, metavar="N",
                    help="price the first N eligible rows, report elapsed "
                         "time only; no metric, no artifact")
    ap.add_argument("--out", default=None,
                    help="artifact path (default data/research/tb_starter/"
                         "tb_starter_<season>.json)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing artifact (tests only)")
    args = ap.parse_args(argv)

    try:
        season = tbs.assert_allowed_season(args.season)
    except tbs.SealedDataError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.time_slice is not None:
        t0 = time.time()
        rows, counts, meta = run(season, limit=args.time_slice)
        elapsed = time.time() - t0
        per_row = meta["price_seconds"] / max(len(rows), 1)
        print(f"time-slice season {season}: {len(rows)} rows priced in "
              f"{meta['price_seconds']}s (load {meta['load_seconds']}s, total "
              f"{elapsed:.1f}s); {per_row * 1000:.2f} ms/row; batter rows in "
              f"file {counts['batter_rows']}; no metric printed, no artifact "
              "written")
        return 0

    out = args.out or os.path.join(OUT_DIR, f"tb_starter_{season}.json")
    out = _abs(out)
    if os.path.exists(out) and not args.force:
        print(f"REFUSED: {out} already exists; one registered run per season, "
              "no silent re-run", file=sys.stderr)
        return 2

    t0 = time.time()
    rows, counts, meta = run(season)
    summary = tbs.summarise_season(rows)
    row_digest = _digest(
        {k: r[k] for k in ("date", "game_pk", "player_id", "tb", "slot",
                           "starter_known", "p2_without", "p2_with",
                           "p1_without", "p1_with")} for r in rows)
    artifact = {
        "rule_id": RULE_ID,
        "prereg_doc": "docs/PREREG_TB_STARTER_AWARE.md",
        "season": season,
        "sign_convention": "d = loss(WITHOUT starter) - loss(WITH starter); "
                           "positive means the starter-aware arm is better",
        "bootstrap": {"resamples": tbs.BOOTSTRAP_RESAMPLES,
                      "seed": tbs.BOOTSTRAP_SEED, "cluster": "date",
                      "interval": "95% percentile"},
        "counts": counts,
        "meta": meta,
        "summary": summary,
        "row_digest": row_digest,
        "code_blob_sha1": {
            "src/research/tb_starter.py": git_blob_hash(
                os.path.join(REPO_ROOT, "src", "research", "tb_starter.py")),
            "scripts/tb_starter_compare.py": git_blob_hash(
                os.path.join(REPO_ROOT, "scripts", "tb_starter_compare.py")),
            "src/analysis/playerprops.py": git_blob_hash(
                os.path.join(REPO_ROOT, "src", "analysis", "playerprops.py")),
        },
        "run_meta": {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "total_seconds": round(time.time() - t0, 2),
        },
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(artifact, fh, indent=1, sort_keys=True)
        fh.write("\n")
    paired = summary["all_rows"]["primary_2plus_tb"].get("paired", {})
    print(f"season {season}: scored {counts['scored']} rows "
          f"({counts['starter_known']} starter-known); wrote {out}")
    print(f"primary mean d = {paired.get('estimate')}  "
          f"95% [{paired.get('low')}, {paired.get('high')}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
