"""Counts-only coverage measurement for TOTALS-M2 (docs/PREREG_TOTALS_FAMILIES.md).

Computes the REAL joint denominator for TOTALS-M2's combined-starter-
groundball-share partition: the intersection of (a) the price-gradeable
totals universe `src.research.totals_rows.build_universe` (in-memory, NEVER
writes the real frozen manifest) and (b) matrix rows where BOTH
`away_starter_groundball_share` and `home_starter_groundball_share` are
present (the both-sides-or-None rule, A1/R4).

NEVER reads any outcome/settlement field beyond what `build_universe` itself
reads to join price-gradeability (game_pk/date/line identity only -- no
`won`/`winner`/`total_runs`). This script does not call any row-grading
function (`build_over_rows` etc.) and does not touch `mlb_results.csv`
directly; it only imports `build_universe`, which already isolates that
join.

Output: docs/TOTALS_M2_COVERAGE.md, plus a returned dict for the unit test.
Deterministic: re-running produces a byte-identical report.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from src.paths import data_path, repo_root
from src.research import totals_rows

MATRIX_PATHS = {
    "2023": data_path("research", "matchup_matrix_2023.jsonl"),
    "2024": data_path("research", "matchup_matrix_2024.jsonl"),
}

SEASONS = ("2023", "2024")
OUT_PATH = repo_root() / "docs" / "TOTALS_M2_COVERAGE.md"

# Real stores (odds archive, settlement CSV, matrix jsonl) are gitignored and
# may not exist inside an isolated worktree checkout. When that happens, fall
# back read-only to the equivalent path under the main checkout (assumed to
# be two levels up from `.claude/worktrees/<name>/`), never writing there.
def _fallback_to_main_checkout(path) -> Path:
    p = Path(path)
    abs_p = p if p.is_absolute() else (repo_root() / p)
    if abs_p.exists():
        return abs_p
    parts = repo_root().parts
    if ".claude" in parts and "worktrees" in parts:
        idx = parts.index(".claude")
        main_root = Path(*parts[:idx])
        rel = abs_p.relative_to(repo_root())
        candidate = main_root / rel
        if candidate.exists():
            return candidate
    return abs_p


ARCHIVE_ROOT = _fallback_to_main_checkout(totals_rows.ARCHIVE_ROOT)
RESULTS_CSV = _fallback_to_main_checkout(totals_rows.RESULTS_CSV)
MATRIX_PATHS = {k: _fallback_to_main_checkout(v) for k, v in MATRIX_PATHS.items()}


def load_matrix_features(path) -> dict:
    """{game_pk (str): (away_gb_share_or_None, home_gb_share_or_None)}."""
    out = {}
    target = Path(path)
    if not target.exists():
        return out
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gp = str(row.get("game_pk"))
            out[gp] = (row.get("away_starter_groundball_share"),
                       row.get("home_starter_groundball_share"))
    return out


def combined_feature(away, home):
    """mean(away, home) if BOTH present, else None (A1/R4 both-sides rule)."""
    if away is None or home is None:
        return None
    return (away + home) / 2.0


def _quantile(sorted_vals, q):
    """State quantile method (linear interpolation on sorted order statistics)."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[int(pos)]
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def fit_tercile_edges(values_2023):
    """Two edges (33.3%, 66.7%) fit on the 2023 feature-side values only."""
    sv = sorted(values_2023)
    return (_quantile(sv, 1.0 / 3.0), _quantile(sv, 2.0 / 3.0))


def assign_tercile(value, edges):
    lo, hi = edges
    if value <= lo:
        return 0
    if value <= hi:
        return 1
    return 2


def mde(n):
    if not n:
        return None
    return 1.96 * math.sqrt(0.25 / n)


def chi_square_uniform(counts):
    """Chi-square goodness-of-fit vs. uniform (equal thirds) occupancy."""
    total = sum(counts)
    if total == 0:
        return None, None
    expected = total / len(counts)
    stat = sum((c - expected) ** 2 / expected for c in counts)
    dof = len(counts) - 1
    return stat, dof


def _chi2_sf_df2(stat):
    """Survival function for chi-square with 2 dof: exp(-stat/2). Exact,
    closed form -- no scipy dependency needed for df=2 (our only case, 3
    terciles)."""
    return math.exp(-stat / 2.0)


def compute_coverage(*, seasons=SEASONS, matrix_paths=MATRIX_PATHS,
                      archive_root=ARCHIVE_ROOT,
                      results_path=RESULTS_CSV,
                      max_staleness_hours=totals_rows.MAX_STALENESS_HOURS) -> dict:
    """Counts-only. Calls `build_universe` in-memory (never writes the real
    manifest path) to get the price-gradeable joint denominator, then joins
    against the matrix rows' both-sides-or-None feature by game_pk.
    """
    universe = totals_rows.build_universe(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        max_staleness_hours=max_staleness_hours)

    gradeable_by_season = {s: [] for s in seasons}
    for e in universe["events"]:
        gradeable_by_season.setdefault(e["season"], []).append(e["game_pk"])

    per_season = {}
    feature_by_game_2023 = {}
    for season in seasons:
        matrix = load_matrix_features(matrix_paths[season])
        game_pks = gradeable_by_season.get(season, [])
        joint_n = len(game_pks)

        both_present = 0
        dropped_both_sides_rule = 0
        fail_no_matrix_row = 0
        fail_missing_away_only = 0
        fail_missing_home_only = 0
        fail_missing_both = 0
        feature_values = {}

        for gp in game_pks:
            if gp not in matrix:
                fail_no_matrix_row += 1
                continue
            away, home = matrix[gp]
            feat = combined_feature(away, home)
            if feat is None:
                dropped_both_sides_rule += 1
                if away is None and home is None:
                    fail_missing_both += 1
                elif away is None:
                    fail_missing_away_only += 1
                else:
                    fail_missing_home_only += 1
                continue
            both_present += 1
            feature_values[gp] = feat

        per_season[season] = {
            "joint_denominator_n": joint_n,
            "rows_with_both_starters_feature_present": both_present,
            "dropped_both_sides_or_none_rule": dropped_both_sides_rule,
            "join_failures": {
                "no_matrix_row_for_game_pk": fail_no_matrix_row,
                "feature_missing_away_only": fail_missing_away_only,
                "feature_missing_home_only": fail_missing_home_only,
                "feature_missing_both_sides": fail_missing_both,
            },
            "join_rate_both_sides_present_pct": (
                round(100.0 * both_present / joint_n, 1) if joint_n else None),
            "feature_values": feature_values,
        }
        if season == "2023":
            feature_by_game_2023 = feature_values

    edges = fit_tercile_edges(list(feature_by_game_2023.values()))

    for season in seasons:
        rec = per_season[season]
        vals = rec.pop("feature_values")
        counts = [0, 0, 0]
        for v in vals.values():
            counts[assign_tercile(v, edges)] += 1
        rec["tercile_occupancy"] = {"t0_low": counts[0], "t1_mid": counts[1], "t2_high": counts[2]}
        stat, dof = chi_square_uniform(counts) if sum(counts) else (None, None)
        rec["chi_square"] = {
            "statistic": round(stat, 4) if stat is not None else None,
            "dof": dof,
            "p_value": round(_chi2_sf_df2(stat), 4) if (stat is not None and dof == 2) else None,
        }
        rec["per_tercile_mde"] = {
            k: (round(mde(c), 4) if c else None) for k, c in
            zip(("t0_low", "t1_mid", "t2_high"), counts)
        }

    join_2023 = per_season["2023"]["join_rate_both_sides_present_pct"]
    join_2024 = per_season["2024"]["join_rate_both_sides_present_pct"]
    shift_note = None
    if join_2023 is not None and join_2024 is not None:
        diff = abs(join_2023 - join_2024)
        if diff >= 10.0:
            shift_note = (
                f"Coverage shift: 2023 join rate {join_2023}% vs 2024 join rate "
                f"{join_2024}% (|Δ|={round(diff,1)}pp) -- material difference, "
                "flagged per task instructions."
            )
        else:
            shift_note = (
                f"No material coverage shift: 2023 join rate {join_2023}% vs "
                f"2024 join rate {join_2024}% (|Δ|={round(diff,1)}pp)."
            )

    return {
        "tercile_edges_fit_on_2023": {"low_edge": edges[0], "high_edge": edges[1]},
        "per_season": per_season,
        "coverage_shift_note": shift_note,
    }


def render_report(result: dict) -> str:
    lines = []
    lines.append("# TOTALS-M2 real coverage (counts-only)")
    lines.append("")
    lines.append(
        "Deterministic, counts-only measurement of the TRUE joint denominator "
        "for TOTALS-M2 (docs/PREREG_TOTALS_FAMILIES.md M2 section): the "
        "intersection of the price-gradeable totals universe "
        "(`src.research.totals_rows.build_universe`, called in-memory here, "
        "never written to the real frozen manifest) with matrix rows where "
        "BOTH `away_starter_groundball_share` and `home_starter_groundball_share` "
        "are present (A1/R4 both-sides-or-None rule). No outcome/score field "
        "(`total_runs`, `won`, `winner`) is read by this script."
    )
    lines.append("")
    lines.append("Generated by `scripts/totals_m2_coverage.py`. Re-running is byte-identical.")
    lines.append("")
    lines.append("## Tercile edges (fit on 2023 feature values only)")
    lines.append("")
    edges = result["tercile_edges_fit_on_2023"]
    lines.append(f"- Low/mid edge: {edges['low_edge']}")
    lines.append(f"- Mid/high edge: {edges['high_edge']}")
    lines.append("")
    for season in SEASONS:
        rec = result["per_season"][season]
        lines.append(f"## {season}")
        lines.append("")
        lines.append(f"- Joint denominator n (price-gradeable universe): {rec['joint_denominator_n']}")
        lines.append(f"- Rows with both starters' feature present: {rec['rows_with_both_starters_feature_present']}")
        lines.append(f"- Dropped by both-sides-or-None rule: {rec['dropped_both_sides_or_none_rule']}")
        lines.append(f"- Join rate (both-sides present / joint denominator): {rec['join_rate_both_sides_present_pct']}%")
        lines.append("- Join failures by cause:")
        jf = rec["join_failures"]
        lines.append(f"  - No matrix row for game_pk: {jf['no_matrix_row_for_game_pk']}")
        lines.append(f"  - Feature missing (away only): {jf['feature_missing_away_only']}")
        lines.append(f"  - Feature missing (home only): {jf['feature_missing_home_only']}")
        lines.append(f"  - Feature missing (both sides): {jf['feature_missing_both_sides']}")
        occ = rec["tercile_occupancy"]
        lines.append(f"- Tercile occupancy (2023-fit edges applied): low={occ['t0_low']}, mid={occ['t1_mid']}, high={occ['t2_high']}")
        cs = rec["chi_square"]
        lines.append(f"- Chi-square vs. uniform occupancy: statistic={cs['statistic']}, dof={cs['dof']}, p={cs['p_value']}")
        mdes = rec["per_tercile_mde"]
        lines.append(f"- Per-tercile MDE (two-sided 95%, p≈0.5): low={mdes['t0_low']}, mid={mdes['t1_mid']}, high={mdes['t2_high']}")
        lines.append("")
    lines.append("## Coverage-shift note")
    lines.append("")
    lines.append(result["coverage_shift_note"] or "n/a")
    lines.append("")
    return "\n".join(lines)


def main():
    result = compute_coverage()
    report = render_report(result)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    for season in SEASONS:
        rec = result["per_season"][season]
        print(f"{season}: joint_n={rec['joint_denominator_n']} both_present={rec['rows_with_both_starters_feature_present']}")


if __name__ == "__main__":
    main()
