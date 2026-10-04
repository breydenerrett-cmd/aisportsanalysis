"""Run the pre-registered strikeout baseline comparison for one season.

THE CRITERION IS IN `docs/PREREG_K_BASELINE.md` AND WAS COMMITTED FIRST.
This script chooses no threshold, population or decision rule; all of those
are fixed in the document and in `src/research/k_baseline.py`.

    python scripts/k_baseline_compare.py --season 2023
    python scripts/k_baseline_compare.py --season 2024
    python scripts/k_baseline_compare.py --verdict      # applies the rule to both artifacts

2025 is tuning-only and 2026-01-01..2026-08-27 is sealed: any other season is
a hard error and the pitcher-log path is opened only AFTER the season passes the
guard. `pitcher_logs.jsonl` holds dates outside 2023-2024 too; it is STREAMED
and every row outside 2023-01-01..2024-12-31 is dropped on the spot, never
kept, counted, aggregated or printed. A 2023 run never reads 2024 rows into any
prediction, and a 2024 run reads 2023 only as the registered prior-season pool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.research import k_baseline as kb  # noqa: E402
from src.research.alpha_registry import git_blob_hash  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PITCHER_LOGS_PATH = os.path.join("data", "historical", "pitcher_logs.jsonl")
OUT_DIR = os.path.join("data", "research", "k_baseline")
RULE_ID = "K_BASELINE_V1"


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def stream_jsonl(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
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


def in_window_rows(path):
    """Stream a mixed-season jsonl keeping ONLY in-window rows. A row outside
    2023-01-01..2024-12-31 is dropped the moment it is parsed: not appended,
    not tallied, not printed."""
    kept = []
    for row in stream_jsonl(path):
        if kb.in_window(row.get("date")):
            kept.append(row)
    return kept


def run(season, *, limit=None, logs_path=None):
    """Build the scored rows for one season. Returns (rows, counts, meta)."""
    season = kb.assert_allowed_season(season)       # BEFORE any path exists
    started = time.time()
    meta = {"rule_id": RULE_ID, "season": season, "inputs": {}}
    path = logs_path or _abs(PITCHER_LOGS_PATH)
    pitchers = in_window_rows(path)
    meta["inputs"]["pitcher_logs_path"] = os.path.relpath(path, REPO_ROOT) \
        if os.path.isabs(path) and path.startswith(REPO_ROOT) else str(path)
    meta["inputs"]["pitcher_logs_in_window_digest"] = _digest(pitchers)
    extracted = kb.extract_starts(pitchers)
    meta["start_extraction"] = extracted["counts"]
    meta["load_seconds"] = round(time.time() - started, 2)
    priced_started = time.time()
    built = kb.build_comparison_rows(
        season=season, starts=extracted["starts"], limit=limit)
    meta["price_seconds"] = round(time.time() - priced_started, 2)
    return built["rows"], built["counts"], meta


def artifact_path(season, out_dir=None):
    return os.path.join(_abs(out_dir or OUT_DIR), f"k_baseline_{season}.json")


def apply_rule(out_dir=None):
    """Read both season artifacts and apply `decide` literally. Reads only
    the artifacts this script wrote."""
    blocks = {}
    for season in kb.ALLOWED_SEASONS:
        with open(artifact_path(season, out_dir), "r", encoding="utf-8") as fh:
            art = json.load(fh)
        blocks[season] = {key: s["paired"] for key, s in
                          art["summary"]["all_scored"]["lines"].items()}
    return kb.decide(blocks[2023], blocks[2024])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", default=None)
    ap.add_argument("--verdict", action="store_true",
                    help="apply the registered rule to both season artifacts")
    ap.add_argument("--out", default=None,
                    help="artifact path (default data/research/k_baseline/"
                         "k_baseline_<season>.json)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing artifact (tests only)")
    args = ap.parse_args(argv)

    if args.verdict:
        print(json.dumps(apply_rule(), indent=1))
        return 0
    if args.season is None:
        print("REFUSED: --season is required", file=sys.stderr)
        return 2
    try:
        season = kb.assert_allowed_season(args.season)
    except kb.SealedDataError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    out = _abs(args.out) if args.out else artifact_path(season)
    if os.path.exists(out) and not args.force:
        print(f"REFUSED: {out} already exists; one registered run per season, "
              "no silent re-run", file=sys.stderr)
        return 2

    t0 = time.time()
    rows, counts, meta = run(season)
    summary = kb.summarise_season(rows)
    row_keys = ("date", "person_id", "k", "bf", "prior_starts", "pool",
                "e_base", "e_cand") + tuple(
        f"{p}_{kb.line_key(L)}" for L in kb.LINES
        for p in ("p_base", "p_cand", "p_ctrl"))
    row_digest = _digest({k: r[k] for k in row_keys} for r in rows)
    artifact = {
        "rule_id": RULE_ID,
        "prereg_doc": "docs/PREREG_K_BASELINE.md",
        "season": season,
        "sign_convention": "d = loss(BASELINE) - loss(CANDIDATE); positive "
                           "means the pitcher-specific candidate is better; "
                           "d_mae = |K - E_baseline| - |K - E_candidate|, same sign",
        "fixed_parameters": {
            "prior_weight_bf": kb.PRIOR_WEIGHT_BF,
            "prior_weight_starts": kb.PRIOR_WEIGHT_STARTS,
            "min_league_starts": kb.MIN_LEAGUE_STARTS,
            "min_prior_starts": kb.MIN_PRIOR_STARTS,
            "lines": list(kb.LINES), "decisive_lines": list(kb.DECISIVE_LINES),
            "eps": kb.EPS, "candidate_distribution": "poisson"},
        "bootstrap": {"resamples": kb.BOOTSTRAP_RESAMPLES,
                      "seed": kb.BOOTSTRAP_SEED, "cluster": "date",
                      "interval": "95% percentile"},
        "counts": counts,
        "meta": meta,
        "summary": summary,
        "row_digest": row_digest,
        "code_blob_sha1": {
            "src/research/k_baseline.py": git_blob_hash(
                os.path.join(REPO_ROOT, "src", "research", "k_baseline.py")),
            "scripts/k_baseline_compare.py": git_blob_hash(
                os.path.join(REPO_ROOT, "scripts", "k_baseline_compare.py")),
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
    print(f"season {season}: scored {counts['scored']} starts "
          f"(excluded: {counts['excluded_no_league_pool']} no league pool, "
          f"{counts['excluded_no_prior_start']} no prior start); wrote {out}")
    for key in (kb.line_key(L) for L in kb.DECISIVE_LINES):
        paired = summary["all_scored"]["lines"][key].get("paired", {})
        print(f"line {key}: mean d = {paired.get('estimate')}  "
              f"95% [{paired.get('low')}, {paired.get('high')}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
