"""Run the pre-registered opponent-adjusted strikeout comparison for one season.

THE CRITERION IS IN `docs/PREREG_K_OPPONENT.md` AND WAS COMMITTED FIRST.
This script chooses no threshold, constant, population or decision rule; all of
those are fixed in the document and in `src/research/k_opponent.py`.

    python scripts/k_opponent_compare.py --season 2023
    python scripts/k_opponent_compare.py --season 2024
    python scripts/k_opponent_compare.py --verdict      # applies the rule to both artifacts

2025 is tuning-only and 2026-01-01..2026-08-27 is sealed: any other season is a
hard error, and no path is opened until the season passes the guard. The three
inputs mix other years in. They are STREAMED and a line whose raw `date` text is
outside the seasons this run needs (the season and, for the pool and the prior
season's league rate, the one before it, both inside 2023-2024) is discarded
BEFORE IT IS PARSED: never decoded, kept, counted, aggregated or printed. A 2023
run therefore never holds a 2024 row, and no 2025 or 2026 row is ever parsed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.research import k_baseline as kb  # noqa: E402
from src.research import k_opponent as ko  # noqa: E402
from src.research.alpha_registry import git_blob_hash  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PITCHER_LOGS_PATH = os.path.join("data", "historical", "pitcher_logs.jsonl")
BULLPEN_LOG_PATH = os.path.join("data", "historical", "bullpen_log.jsonl")
RESULTS_PATH = os.path.join("data", "historical", "mlb_results.csv")
BASELINE_ARTIFACT_DIR = os.path.join("data", "research", "k_baseline")
OUT_DIR = os.path.join("data", "research", "k_opponent")
RULE_ID = "K_OPPONENT_V1"

_DATE_RE = re.compile(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def seasons_needed(season):
    """The season and, inside the evidence window, the one before it."""
    season = kb.assert_allowed_season(season)
    return tuple(y for y in (season - 1, season) if y in kb.ALLOWED_SEASONS)


def line_year(text):
    """Year of a raw line's `date`, or None. Looks at the date text only."""
    match = _DATE_RE.search(text)
    if not match:
        return None
    head = match.group(1)
    return int(head[:4]) if kb.in_window(head) else None


def stream_jsonl_years(path, years):
    """Yield parsed rows of a mixed-season jsonl whose raw `date` year is in
    `years`. Any other line (2025, 2026, no date) is dropped without being
    parsed."""
    years = set(years)
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for line in fh:
            if line_year(line) in years:
                yield json.loads(line)


def regular_games_for(path, years):
    """{game_pk: date} for `game_type == "R"` games of `years` in
    mlb_results.csv. A line is discarded on its date field before any other
    field is read."""
    import csv
    years = set(years)
    games = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader([fh.readline()]))
        pk_i, date_i, type_i = (header.index("game_pk"), header.index("date"),
                                header.index("game_type"))
        for line in fh:
            fields = line.split(",", date_i + 1)
            if len(fields) <= date_i:
                continue
            head = fields[date_i]
            if not (kb.in_window(head) and int(head[:4]) in years):
                continue
            row = next(csv.reader([line]))
            if row[type_i] == "R":
                games[int(row[pk_i])] = row[date_i][:10]
    return games


def _digest(rows):
    h = hashlib.sha256()
    n = 0
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, separators=(",", ":"),
                            default=str).encode("utf-8"))
        h.update(b"\n")
        n += 1
    return {"rows": n, "sha256": h.hexdigest()}


BASELINE_ROW_KEYS = ("date", "person_id", "k", "bf", "prior_starts", "pool",
                     "e_base", "e_cand") + tuple(
    f"{p}_{kb.line_key(L)}" for L in kb.LINES for p in ("p_base", "p_cand", "p_ctrl"))


def baseline_reconciliation(season, baseline_rows, out_dir=None):
    """Compare the registered baseline rows this run rebuilt with the digest
    stored in the K_BASELINE artifact for the season. Descriptive: it proves the
    baseline is the registered one on this data, and cannot change a number."""
    path = os.path.join(_abs(out_dir or BASELINE_ARTIFACT_DIR),
                        f"k_baseline_{season}.json")
    if not os.path.exists(path):
        return {"checked": False, "reason": "no K_BASELINE artifact for the season"}
    with open(path, "r", encoding="utf-8") as fh:
        stored = json.load(fh).get("row_digest")
    with_ctrl = []
    for r in baseline_rows:
        row = {k: r[k] for k in BASELINE_ROW_KEYS if k in r}
        with_ctrl.append(row)
    mine = _digest(with_ctrl)
    return {"checked": True, "stored": stored, "rebuilt": mine,
            "equal": stored == mine}


def run(season, *, limit=None, logs_path=None, bullpen_path=None,
        results_path=None, baseline_out_dir=None):
    """Build the scored rows for one season. Returns (rows, counts, meta, baseline_rows)."""
    season = kb.assert_allowed_season(season)       # BEFORE any path exists
    years = seasons_needed(season)
    started = time.time()
    logs_path = logs_path or _abs(PITCHER_LOGS_PATH)
    bullpen_path = bullpen_path or _abs(BULLPEN_LOG_PATH)
    results_path = results_path or _abs(RESULTS_PATH)
    meta = {"rule_id": RULE_ID, "season": season, "years_read": list(years),
            "inputs": {}}

    pitchers = list(stream_jsonl_years(logs_path, years))
    extracted = kb.extract_starts(pitchers)
    meta["start_extraction"] = extracted["counts"]
    meta["inputs"]["pitcher_logs_rows_read"] = _digest(pitchers)

    regular = regular_games_for(results_path, years)
    meta["inputs"]["regular_games_in_results"] = len(regular)
    bullpen = list(stream_jsonl_years(bullpen_path, years))
    meta["inputs"]["bullpen_log_rows_read"] = _digest(bullpen)
    games = ko.extract_games(bullpen, regular)
    meta["game_extraction"] = games["counts"]
    attached = ko.attach_opponents(extracted["starts"], games)
    meta["opponent_attachment"] = attached["counts"]
    meta["load_seconds"] = round(time.time() - started, 2)

    built = ko.build_opponent_rows(
        season=season, starts=extracted["starts"], games=games["games"],
        opponents=attached["opponents"], causes=attached["causes"], limit=limit)
    return built["rows"], built["counts"], meta, built["baseline_rows"]


def artifact_path(season, out_dir=None):
    return os.path.join(_abs(out_dir or OUT_DIR), f"k_opponent_{season}.json")


def apply_rule(out_dir=None):
    """Read both season artifacts and apply `decide` literally. Reads only the
    artifacts this script wrote."""
    blocks = {}
    for season in kb.ALLOWED_SEASONS:
        with open(artifact_path(season, out_dir), "r", encoding="utf-8") as fh:
            art = json.load(fh)
        blocks[season] = {key: s["paired"] for key, s in
                          art["summary"]["all_scored"]["lines"].items()}
    return ko.decide(blocks[2023], blocks[2024])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", default=None)
    ap.add_argument("--verdict", action="store_true",
                    help="apply the registered rule to both season artifacts")
    ap.add_argument("--out", default=None,
                    help="artifact path (default data/research/k_opponent/"
                         "k_opponent_<season>.json)")
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
    rows, counts, meta, baseline_rows = run(season)
    summary = ko.summarise_season(rows)
    row_keys = ("date", "person_id", "opponent", "k", "bf", "factor", "e_base",
                "e_cand") + tuple(f"{p}_{kb.line_key(L)}" for L in kb.LINES
                                  for p in ("p_base", "p_cand"))
    artifact = {
        "rule_id": RULE_ID,
        "prereg_doc": "docs/PREREG_K_OPPONENT.md",
        "season": season,
        "sign_convention": "d = loss(BASELINE) - loss(CANDIDATE); positive means "
                           "the opponent-adjusted candidate is better; BASELINE is "
                           "the registered K_BASELINE candidate; d_mae = |K - "
                           "E_baseline| - |K - E_candidate|, same sign",
        "fixed_parameters": {
            "opp_prior_pa": ko.OPP_PRIOR_PA,
            "factor_min": ko.FACTOR_MIN, "factor_max": ko.FACTOR_MAX,
            "baseline_prior_weight_bf": kb.PRIOR_WEIGHT_BF,
            "baseline_prior_weight_starts": kb.PRIOR_WEIGHT_STARTS,
            "min_league_starts": kb.MIN_LEAGUE_STARTS,
            "min_prior_starts": kb.MIN_PRIOR_STARTS,
            "lines": list(kb.LINES), "decisive_lines": list(kb.DECISIVE_LINES),
            "eps": kb.EPS, "distribution": "poisson"},
        "bootstrap": {"resamples": kb.BOOTSTRAP_RESAMPLES,
                      "seed": kb.BOOTSTRAP_SEED, "cluster": "date",
                      "interval": "95% percentile"},
        "counts": counts,
        "meta": meta,
        "baseline_reconciliation": baseline_reconciliation(season, baseline_rows),
        "summary": summary,
        "row_digest": _digest({k: r[k] for k in row_keys} for r in rows),
        "code_blob_sha1": {
            rel: git_blob_hash(os.path.join(REPO_ROOT, *rel.split("/")))
            for rel in ("src/research/k_opponent.py",
                        "scripts/k_opponent_compare.py",
                        "src/research/k_baseline.py")},
        "run_meta": {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "total_seconds": round(time.time() - t0, 2),
        },
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(artifact, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"season {season}: scored {counts['scored']} of "
          f"{counts['baseline_scored']} K_BASELINE-scored starts "
          f"({counts['excluded_no_opponent']} without an opposing team); wrote {out}")
    for key in (kb.line_key(L) for L in kb.DECISIVE_LINES):
        paired = summary["all_scored"]["lines"][key].get("paired", {})
        print(f"line {key}: mean d = {paired.get('estimate')}  "
              f"95% [{paired.get('low')}, {paired.get('high')}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
