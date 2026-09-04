"""docs/PREREG_CALIBRATED_PROBABILITY.md §4/§5: measure the market_derived
(de-vigged consensus) probability's calibration on 2024, the permitted
evaluation season -- log-loss, Brier, ECE, max-CE, both bin schemes, and
the three named baselines -- and cross-check the primary (distinct-close)
result against Phase 2A's frozen M0 numbers
(docs/EVOLAB_PHASE2A_BASELINE.md §9.2: log-loss 0.67275, Brier 0.23999).

This does NOT read `evidence/decisions_v2.jsonl` -- there is no ledger
history yet with 2,234 settled market_derived decisions. It measures the
SAME identity map (the board's own de-vigged consensus, via
`src.core.calibration`) directly against `src.evolab.baseline.build_rows`'s
2024 rows, which is the sealed non-evidential sandbox Phase 2A itself used
-- an independent re-derivation through a completely different code path
(this project's real `scorecard.build_calibration_report`/
`src.core.calibration`, never Phase 2A's own scoring functions), which is
exactly what makes reproducing 0.67275/0.23999 to the last digit a real
cross-check rather than a tautology.

Run: `python3 scripts/measure_market_derived_calibration.py`
Writes: data/research/evolab/market_derived_calibration_2024.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core import calibration as cal
from src.evolab import baseline
from src.paths import repo_root

OUT_PATH = repo_root() / "data" / "research" / "evolab" / \
    "market_derived_calibration_2024.json"


def measure(season: int = 2024) -> dict:
    built = baseline.build_rows(season)
    rows = built["rows"]
    distinct_rows = [r for r in rows if r["distinct"]]

    def _score(subset, label):
        preds = [r["market_home"] for r in subset]
        outs = [r["home_won"] for r in subset]
        scores = cal.score_all(preds, outs, bins=10)
        fixed = cal.reliability_curve(preds, outs, bins=10)
        equal = cal.reliability_curve_equal_count(preds, outs, bins=10)
        base = cal.baseline_base_rate(outs)
        return {
            "label": label, "n": len(subset), **scores,
            "baseline_base_rate": base,
            "reliability_fixed_width": fixed,
            "reliability_equal_count": equal,
        }

    primary = _score(distinct_rows, "primary_distinct_close")
    sensitivity = _score(rows, "sensitivity_no_distinctness_filter")

    phase2a_reference = {"log_loss": 0.67275, "brier": 0.23999}
    cross_check = {
        "log_loss_matches_to_5dp": (
            round(primary["log_loss"], 5) == phase2a_reference["log_loss"]),
        "brier_matches_to_5dp": (
            round(primary["brier"], 5) == phase2a_reference["brier"]),
    }

    return {
        "season": season, "excluded": built["excluded"],
        "phase2a_reference_2024": phase2a_reference,
        "cross_check": cross_check,
        "primary": primary, "sensitivity": sensitivity,
    }


def main() -> int:
    result = measure()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    p = result["primary"]
    print(f"n={p['n']} log_loss={p['log_loss']:.5f} brier={p['brier']:.5f} "
          f"ece={p['ece']:.5f} max_ce={p['max_ce']:.5f}")
    print(f"Phase 2A cross-check: {result['cross_check']}")
    print(f"Written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
