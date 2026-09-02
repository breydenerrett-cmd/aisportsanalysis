#!/usr/bin/env python3
"""Migrate the four family registration files (+ the Phase 2B sweep, the Elo
audit, and every verdict already read) into `data/research/alpha_registry.jsonl`.

Every literal number below is transcribed by hand from a specific source
document, cited in a comment on the line it came from. Nothing here is
estimated, interpolated, or "reasonably assumed" without saying so in a
comment AND in `docs/ALPHA_REGISTRY_MIGRATION_REPORT.md`, which is the
authority for every disagreement and every null field this migration
produced. Read that report before trusting a number pulled from here.

USAGE
-----
    python3 scripts/alpha_registry_migrate.py migrate [--path FILE]
    python3 scripts/alpha_registry_migrate.py report  [--path FILE] [--market M] [--data-window W]

`migrate` is idempotent: it reads whatever ids already exist at `--path`
first and only appends rows for ids that are not there yet. Running it twice
in a row appends nothing the second time (this is asserted in
tests/test_alpha_registry.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.research import alpha_registry as reg  # noqa: E402

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SPORT = "mlb"
Q_010 = 0.10
SEALED = True  # every family this migration seeds keeps 2026-01-01..08-27 sealed

# battery 2.0.0 fingerprint, verbatim from data/research/family_v4_exploratory.json
# and data/research/family_v5_stuff.json's "note" fields.
BATTERY_FINGERPRINT_V4_V5 = "ac74c7a7f715f9ec"

# evidence/stage2_2026-08-28/code_commit.txt, verbatim.
V1_CODE_HASH = "4af6656a79e9fa5e15e67a32e7b7bb8a6e07dddb"

# EVOLAB_PHASE2B_RESULTS.md section 5 "Provenance" table, verbatim.
PHASE2B_CODE_HASH = "3ca8a008af43a5d27023738d98af12ad07eff6f1"


def _row(kind, id_, family, market, registered_utc, data_window, source_doc,
         alpha_declared, spec_id=None, direction=None, feature_expr_hash=None,
         code_hash=None, registered_via_amendment=None, candidates_evaluated=None,
         migrated_utc=None):
    row = {
        "kind": kind, "id": id_, "family": family, "spec_id": spec_id,
        "market": market, "sport": SPORT, "registered_utc": registered_utc,
        "data_window": data_window, "direction": direction,
        "feature_expr_hash": feature_expr_hash, "alpha_declared": alpha_declared,
        "status": "registered", "source_doc": source_doc, "code_hash": code_hash,
        "migrated_utc": migrated_utc,
    }
    if registered_via_amendment is not None:
        row["registered_via_amendment"] = registered_via_amendment
    if candidates_evaluated is not None:
        row["candidates_evaluated"] = candidates_evaluated
    return row


def _verdict(id_, read_utc, result, p=None, effect=None, ci=None,
             battery_version=None, within_sweep=None,
             forward_window=None, migrated_utc=None):
    row = {
        "kind": "verdict", "id": id_, "read_utc": read_utc, "result": result,
        "p": p, "effect": effect, "ci": ci, "battery_version": battery_version,
        "forward_window": forward_window or {"start": None, "n": None, "pending": False},
        "migrated_utc": migrated_utc,
    }
    if within_sweep is not None:
        row["within_sweep"] = within_sweep
    return row


# ---------------------------------------------------------------------------
# V1 -- evidence/hypothesis_family.json (count: 21, registered_at
# 2026-08-28T08:39:49.622381+00:00) x docs/RESULTS_STAGE2.md
# ---------------------------------------------------------------------------

V1_REGISTERED_UTC = "2026-08-28T08:39:49.622381+00:00"
V1_SOURCE = "evidence/hypothesis_family.json"
V1_DATA_WINDOW = {"discovery": "2023-2024", "replication": None, "sealed_untouched": SEALED}

# (detector, [markets]) -- copied verbatim, in file order, from
# evidence/hypothesis_family.json's "hypotheses" list.
V1_DETECTOR_MARKETS = [
    ("bullpen_exposure", ["h2h", "h2h_1st_5_innings"]),
    ("bullpen_workload", ["h2h"]),
    ("implied_bullpen_disagreement", ["h2h", "h2h_1st_5_innings"]),
    ("lineup_vs_starter", ["h2h", "h2h_1st_5_innings"]),
    ("park_and_weather", ["totals", "totals_1st_5_innings"]),
    ("pitch_mix_mismatch", ["h2h", "h2h_1st_5_innings", "totals_1st_5_innings"]),
    ("platoon_mismatch", ["h2h", "h2h_1st_5_innings", "totals_1st_5_innings"]),
    ("stale_book", ["h2h"]),
    ("starter_mismatch", ["h2h", "h2h_1st_5_innings"]),
    ("thin_matchup_history", ["h2h"]),
    ("travel_load", ["h2h", "totals"]),
]
assert sum(len(m) for _, m in V1_DETECTOR_MARKETS) == 21

# docs/RESULTS_STAGE2.md's table: n, effect (pp), clustered p, 95% CI (pp).
# Detectors not in this table produced no side (context/debunk/totals) or
# fell below the 30-selection floor (lineup_vs_starter, n=26) -- see the
# migration report for the full list of nulls this implies.
V1_STATS = {
    "bullpen_exposure": dict(n=1508, effect=1.65, p=0.18, ci=(-0.70, 4.04)),
    "bullpen_workload": dict(n=2499, effect=0.79, p=0.32, ci=(-0.81, 2.34)),
    "pitch_mix_mismatch": dict(n=3339, effect=0.60, p=0.40, ci=(-0.74, 2.07)),
    "platoon_mismatch": dict(n=104, effect=3.84, p=0.44, ci=(-5.79, 13.37)),
    "starter_mismatch": dict(n=2295, effect=-0.75, p=0.48, ci=(-2.74, 1.27)),
    "travel_load": dict(n=604, effect=0.38, p=0.85, ci=(-3.40, 4.24)),
    "stale_book": dict(n=2949, effect=0.03, p=0.97, ci=(-1.35, 1.48)),
}
# evidence/stage2_2026-08-28/ (directory name) is the only place a run date
# for this table is recorded -- RESULTS_STAGE2.md's own text carries no
# explicit run-date sentence. Flagged in the migration report as inferred.
V1_READ_UTC = "2026-08-28"


def v1_rows():
    hyps, verdicts = [], []
    for detector, markets in V1_DETECTOR_MARKETS:
        for market in markets:
            id_ = f"V1:{detector}:{market}"
            # No direction field exists anywhere in the frozen registration
            # file; not reverse-engineered from later results docs (that
            # would leak post-hoc knowledge into a "pre-registered" field).
            atom_hash = reg.semantic_hash_v0([(detector, "flag_present", market, None)])
            hyps.append(_row(
                "hypothesis", id_, "V1", market, V1_REGISTERED_UTC, V1_DATA_WINDOW,
                V1_SOURCE, Q_010, spec_id=detector, direction=None,
                feature_expr_hash=atom_hash, code_hash=V1_CODE_HASH,
            ))
            stats = V1_STATS.get(detector)
            if stats:
                verdicts.append(_verdict(
                    id_, V1_READ_UTC, "null", p=stats["p"], effect=stats["effect"],
                    ci=list(stats["ci"]),
                ))
            else:
                # implied_bullpen_disagreement / park_and_weather / thin_matchup_history
                # (side-less by design) and lineup_vs_starter (26 selections,
                # below the 30-selection floor -- RESULTS_STAGE2.md line 21).
                # No p/effect/ci was ever computed for these; None over guess.
                verdicts.append(_verdict(id_, V1_READ_UTC, "null"))
    return hyps, verdicts


# ---------------------------------------------------------------------------
# V2 -- docs/RESEARCH_V2.md (prose pre-registration, no structured file) x
# docs/RESULTS_V2.md (Run date: 2026-08-29)
# ---------------------------------------------------------------------------

V2_REGISTERED_UTC = "2026-08-29"  # RESEARCH_V2.md: "Opened: 2026-08-29" (date only)
V2_READ_UTC = "2026-08-29"        # RESULTS_V2.md: "Run date: 2026-08-29"
V2_SOURCE = "docs/RESEARCH_V2.md"
V2_DATA_WINDOW = {"discovery": "2023-2024", "replication": None, "sealed_untouched": SEALED}

# Each entry: (id_suffix, market, atom, verdict-kwargs). "atom" fields
# (feature/operator/direction) are THIS MIGRATION'S OWN PARAPHRASE of
# RESEARCH_V2.md's prose -- no machine-readable spec exists for V2, unlike
# V1/V4/V5/V3. Flagged prominently in the migration report: a future
# re-registration of the identical M-test will only collide with these
# hashes if it happens to reproduce the same paraphrase, which is unlikely.
# market: pricepath.py (src/research/pricepath.py) hardcodes market key
# "h2h" for the price-path reconstruction M1/M2/M3/M5 all read from, so all
# four ran on h2h in practice even though RESEARCH_V2.md's M3 write-up says
# it would "evaluate on totals as well as moneyline" -- that never happened
# per the code, and is flagged as a pre-registration/execution mismatch.
V2_SPECS = {
    "M1": dict(
        market="h2h",
        atom=("consecutive_price_change_lag1",
              "autocorrelation_sign_negative_hypothesized", "h2h", "fade_last_move"),
        direction="fade_last_move",
    ),
    "M2": dict(
        market="h2h",
        atom=("price_T_minus_90_vs_pregame",
              "forecast_calibration_superior_on_weekend_day", "h2h",
              "early_price_more_accurate_weekend_day"),
        direction="early_price_more_accurate_weekend_day",
    ),
    "M3": dict(
        market="h2h",
        atom=("cross_book_deviation_from_consensus", "outlier_price_is_correct_bet",
              "h2h", "bet_against_outlier_book"),
        direction="bet_against_outlier_book",
    ),
    "M4": dict(
        # This is the one V2 hypothesis about the F5 market specifically --
        # the object under test is whether the F5 price is internally
        # consistent with the full-game price, so the market charged is the
        # F5 market whose mispricing is the claim.
        market="h2h_1st_5_innings",
        atom=("implied_full_minus_f5_bullpen_gap", "systematic_bias_test",
              "h2h_1st_5_innings", None),
        direction=None,  # two-sided bias test, no a-priori sign (RESEARCH_V2.md)
    ),
    "M5": dict(
        market="h2h",
        atom=("devig_method_choice", "calibration_comparison", "h2h", None),
        direction=None,  # methodological comparison, not a directional bet
    ),
}

# docs/RESULTS_V2.md verbatim numbers.
V2_VERDICTS = {
    "M5": dict(result="null", p=None, effect=None, ci=None),  # log-loss/Brier
        # table doesn't map onto p/effect/ci at all -- see report.
    "M2": dict(result="null", p=None, effect=None, ci=None),  # INCONCLUSIVE:
        # the strict (pre-registered) test had only 3 qualifying games and
        # was never scored; the loose-test cell numbers are explicitly
        # "not the paper's test" per the doc and are not copied here.
    "M1": dict(result="null", p=0.13, effect=0.013, ci=None),  # lag-1
        # autocorrelation +0.013, clustered p=0.13 -- wrong sign, no CI given.
    "M3": dict(result="false_positive", p=0.0063, effect=8.49, ci=[2.34, 14.28]),
    "M4": dict(result="null", p=0.665, effect=1.25, ci=[-4.31, 6.80]),  # CORRECTED
        # numbers per RESULTS_V2.md's own 2026-08-31 correction note, which
        # states it is "the authority" over the original [-4.56, 7.12] figure.
}


def v2_rows():
    hyps, verdicts = [], []
    for code, spec in V2_SPECS.items():
        id_ = f"V2:{code}"
        atom_hash = reg.semantic_hash_v0([spec["atom"]])
        hyps.append(_row(
            "hypothesis", id_, "V2", spec["market"], V2_REGISTERED_UTC, V2_DATA_WINDOW,
            V2_SOURCE, Q_010, spec_id=code, direction=spec["direction"],
            feature_expr_hash=atom_hash, code_hash=None,  # no code hash recorded anywhere for V2
        ))
        v = V2_VERDICTS[code]
        verdicts.append(_verdict(id_, V2_READ_UTC, v["result"], p=v["p"],
                                  effect=v["effect"], ci=v["ci"]))
    return hyps, verdicts


# ---------------------------------------------------------------------------
# V4 -- data/research/family_v4_exploratory.json (count: 6, registered_at
# 2026-08-31T02:16:27.934270+00:00) x data/research/results_v4_run.json
# ---------------------------------------------------------------------------

V4_REGISTERED_UTC = "2026-08-31T02:16:27.934270+00:00"
V4_READ_UTC = V4_REGISTERED_UTC  # results_v4_run.json carries no separate
    # "run_at"/read timestamp; RESEARCH_CATALOGUE.md's "Run 2026-08-31 02:16
    # UTC" matches the registration instant to the minute, so no distinct
    # read time exists to copy.
V4_SOURCE = "data/research/family_v4_exploratory.json"
V4_DATA_WINDOW = {"discovery": "2023", "replication": "2024", "sealed_untouched": SEALED}

# Verbatim from data/research/family_v4_exploratory.json's "specs" list:
# (name, feature, market, direction, threshold).
V4_SPECS = [
    ("pitch_lean_vulnerability", "primary_pitch_share*lineup_vs_primary_pitch", "h2h", "positive", 0.06),
    ("stacked_top_platoon", "top_minus_bottom*lineup_platoon_share", "h2h", "positive", 0.0234),
    ("platoon_pressure", "lineup_platoon_share*starter_platoon_gap", "h2h", "positive", 0.0478),
    ("stacked_top_vs_pitch", "top_minus_bottom*lineup_vs_primary_pitch", "h2h", "positive", 0.0117),
    ("handed_lineup_vs_pitch", "lineup_platoon_share*lineup_vs_primary_pitch", "h2h", "positive", 0.1134),
    ("stacked_top_weak_starter", "top_minus_bottom*starter_platoon_gap", "h2h", "positive", 0.0028),
]
assert len(V4_SPECS) == 6

# data/research/results_v4_run.json, verbatim, with the DECISIVE stage's
# number picked per the row's own terminal "status"/"level_reached": the
# stage a row actually reached is the one whose number is copied, never a
# stage it never got past. See the migration report for why a "no_replication"
# row's p is null (the decision at that stage is made on effect
# magnitude/sign, not on a freshly computed p-value).
V4_VERDICTS = {
    "pitch_lean_vulnerability": dict(result="false_positive", p=0.453575, effect=0.01057, ci=None),
    "stacked_top_platoon": dict(result="null", p=0.499681, effect=-0.00982, ci=None),
    "platoon_pressure": dict(result="null", p=0.818606, effect=-0.00753, ci=None),
    "stacked_top_vs_pitch": dict(result="null", p=0.650834, effect=-0.00847, ci=None),
    "handed_lineup_vs_pitch": dict(result="null", p=None, effect=-0.03547, ci=None),
    "stacked_top_weak_starter": dict(result="null", p=None, effect=-0.00444, ci=None),
}


def v4_rows():
    hyps, verdicts = [], []
    for name, feature, market, direction, threshold in V4_SPECS:
        id_ = f"V4:{name}"
        # grid = identity: the threshold is already a single frozen p70
        # scalar per family, so bucketing it against itself is a no-op.
        atom_hash = reg.semantic_hash_v0(
            [(feature, "gte_threshold_back_advantaged", market, direction, threshold)],
            grid=[threshold],
        )
        hyps.append(_row(
            "hypothesis", id_, "V4", market, V4_REGISTERED_UTC, V4_DATA_WINDOW,
            V4_SOURCE, Q_010, spec_id=name, direction=direction,
            feature_expr_hash=atom_hash, code_hash=BATTERY_FINGERPRINT_V4_V5,
        ))
        v = V4_VERDICTS[name]
        verdicts.append(_verdict(id_, V4_READ_UTC, v["result"], p=v["p"],
                                  effect=v["effect"], ci=v["ci"],
                                  battery_version="2.0.0"))
    return hyps, verdicts


# ---------------------------------------------------------------------------
# V5 -- data/research/family_v5_stuff.json (count: 3, registered_at
# 2026-08-31T07:54:53.674306+00:00) x data/research/results_v5_run.json
# ---------------------------------------------------------------------------

V5_REGISTERED_UTC = "2026-08-31T07:54:53.674306+00:00"
V5_READ_UTC = V5_REGISTERED_UTC  # same reasoning as V4: no distinct read
    # timestamp exists; RESEARCH_CATALOGUE.md's "Run 2026-08-31 07:54 UTC"
    # matches the registration instant.
V5_SOURCE = "data/research/family_v5_stuff.json"
V5_DATA_WINDOW = {"discovery": "2023", "replication": "2024", "sealed_untouched": SEALED}

V5_SPECS = [
    ("facing_soft_stuff", "starter_velocity_gap", "h2h", "negative", 3.0167),
    ("stacked_top_vs_groundballer", "top_minus_bottom*starter_groundball_share", "h2h", "negative", 0.0137),
    ("fastball_leaning_decliner", "primary_pitch_share*starter_velocity_gap", "h2h", "negative", 1.238),
]
assert len(V5_SPECS) == 3

V5_VERDICTS = {
    "facing_soft_stuff": dict(result="null", p=None, effect=0.00455, ci=None),
    "stacked_top_vs_groundballer": dict(result="null", p=None, effect=-0.03392, ci=None),
    "fastball_leaning_decliner": dict(result="null", p=None, effect=-0.00332, ci=None),
}


def v5_rows():
    hyps, verdicts = [], []
    for name, feature, market, direction, threshold in V5_SPECS:
        id_ = f"V5:{name}"
        atom_hash = reg.semantic_hash_v0(
            [(feature, "gte_threshold_back_advantaged", market, direction, threshold)],
            grid=[threshold],
        )
        hyps.append(_row(
            "hypothesis", id_, "V5", market, V5_REGISTERED_UTC, V5_DATA_WINDOW,
            V5_SOURCE, Q_010, spec_id=name, direction=direction,
            feature_expr_hash=atom_hash, code_hash=BATTERY_FINGERPRINT_V4_V5,
        ))
        v = V5_VERDICTS[name]
        verdicts.append(_verdict(id_, V5_READ_UTC, v["result"], p=v["p"],
                                  effect=v["effect"], ci=v["ci"],
                                  battery_version="2.0.0"))
    return hyps, verdicts


# ---------------------------------------------------------------------------
# V3 -- docs/RESEARCH_V3_TIMING.md (frozen 2026-08-31, 4 classes) +
# docs/RESEARCH_V3_UMPIRE_CLASS.md (amendment, 2026-09-02, 5th class).
#
# THE DESIGN NOTE PREDATES THIS AMENDMENT: docs/ALPHA_REGISTRY_DESIGN.md
# says "V3's admitted classes ... 4 rows" and "two are below floor -> status
# registered, no verdict" -- both wrong against the source docs read here.
# The umpire amendment (same date as the design note) makes the family FIVE
# classes, and the ADDENDUM in RESEARCH_V3_TIMING.md shows only ONE of the
# original four classes has actually crossed its read floor (56/30
# measurable for transaction_first_seen; lineup_posted 29/30, hitter_scratch
# 3/30, starter_scratch 0/30 -- all three still below floor, not two). This
# migration follows the source documents, not the design note's stale count,
# per this task's own instruction to record the disagreement rather than
# silently reconcile it. See docs/ALPHA_REGISTRY_MIGRATION_REPORT.md.
# ---------------------------------------------------------------------------

V3_DATA_WINDOW = {"discovery": "forward", "replication": None, "sealed_untouched": SEALED}
V3_FROZEN_UTC = "2026-08-31"     # RESEARCH_V3_TIMING.md: "Frozen 2026-08-31"
V3_AMENDMENT_UTC = "2026-09-02"  # RESEARCH_V3_UMPIRE_CLASS.md: "pre-registered
                                   # 2026-09-02, BEFORE any event has been read"
V3_TIMING_SOURCE = "docs/RESEARCH_V3_TIMING.md"
V3_UMPIRE_SOURCE = "docs/RESEARCH_V3_UMPIRE_CLASS.md"

# class name (using the ADDENDUM's own preferred name for the renamed
# class), registered_utc, source doc, amendment flag.
V3_CLASSES = [
    ("lineup_posted", V3_FROZEN_UTC, V3_TIMING_SOURCE, None),
    ("starter_scratch", V3_FROZEN_UTC, V3_TIMING_SOURCE, None),
    ("hitter_scratch", V3_FROZEN_UTC, V3_TIMING_SOURCE, None),
    # freeze record names this "il_roster_move"; the capture code and the
    # ADDENDUM both call it "transaction_first_seen" -- same class, kept
    # under its addendum name with the alias recorded in spec_id.
    ("transaction_first_seen", V3_FROZEN_UTC, V3_TIMING_SOURCE, None),
    ("umpire_crew_revealed", V3_AMENDMENT_UTC, V3_UMPIRE_SOURCE,
     "docs/RESEARCH_V3_UMPIRE_CLASS.md"),
]
assert len(V3_CLASSES) == 5

# ADDENDUM 2026-09-02 in docs/RESEARCH_V3_TIMING.md: only
# transaction_first_seen has crossed its 30-event floor and been read.
V3_READ_UTC = "2026-09-02"
V3_VERDICT_ID = "V3:transaction_first_seen"


def v3_rows():
    hyps = []
    for class_name, registered_utc, source_doc, amendment in V3_CLASSES:
        id_ = f"V3:{class_name}"
        # market intentionally None: neither RESEARCH_V3_TIMING.md nor the
        # umpire amendment names a specific betting market (h2h/totals) for
        # the price-reaction measurement -- they speak generically of
        # "books", "quotes" and "de-vigged implied probability". Guessing
        # h2h by analogy to other modules' hardcoded market key would not
        # be verbatim from either V3 doc, so it is left null. See the report.
        atom = (class_name, "median_reaction_exceeds_floor", None, "positive")
        atom_hash = reg.semantic_hash_v0([atom])
        hyps.append(_row(
            "hypothesis", id_, "V3", None, registered_utc, V3_DATA_WINDOW,
            source_doc, Q_010, spec_id=class_name, direction="positive",
            feature_expr_hash=atom_hash, code_hash=None,
            registered_via_amendment=amendment,
        ))
    # Only one verdict exists across all five classes at migration time.
    verdicts = [_verdict(
        V3_VERDICT_ID, V3_READ_UTC, "candidate",
        # S_hat(0), the frozen pre-registered test statistic (not the
        # descriptive median-minutes figures, which the family's own rules
        # keep separate from "the" primary-hypothesis result).
        p=0.000, effect=1.0, ci=[1.0, 1.0],
        battery_version=None,  # bespoke bootstrap (timingtest.py), not the
                                # shared RULES_VERSION 2.0.0 falsification battery
        forward_window={"start": None, "n": 56, "pending": False},
    )]
    return hyps, verdicts


# ---------------------------------------------------------------------------
# Evolab Phase 2B -- ONE sweep row (D1), not 8,811 hypothesis rows.
# docs/EVOLAB_PHASE2B_RESULTS.md
# ---------------------------------------------------------------------------

PHASE2B_ID = "EVOLAB:phase2b"
PHASE2B_REGISTERED_UTC = "2026-08-31"  # docs/EVOLAB_DESIGN.md section 14b,
    # "Stated prior before Phase 2B runs (2026-08-31)"; design doc itself
    # "Approved by Brey 2026-08-31"
PHASE2B_READ_UTC = "2026-08-31"        # seed 20260831; results doc dated to the same run
PHASE2B_SOURCE = "docs/EVOLAB_PHASE2B_RESULTS.md"
# Scope footnote (added 2026-09-02): the genome schema names h2h and
# h2h_1st_5_innings, but src/evolab/feed.py sources full-game h2h prices
# only -- "the 8,811-strategy headline is therefore an h2h-only search."
PHASE2B_MARKET = "h2h"
PHASE2B_DATA_WINDOW = {"discovery": "2023-2024", "replication": None, "sealed_untouched": SEALED}
PHASE2B_CANDIDATES = 8811
# threshold_pct = 95.0 is a placebo-CEILING percentile, not a BH-FDR q --
# a different unit from every hypothesis row's alpha_declared=0.10. Flagged
# in the report since "alpha_declared" otherwise means the same thing everywhere.
PHASE2B_ALPHA_DECLARED = 95.0


def phase2b_rows():
    atom_hash = reg.semantic_hash_v0(
        [("evolab_phase2b_movement_ceiling_sweep", "sweep", PHASE2B_MARKET, None)]
    )
    hyp = _row(
        "sweep", PHASE2B_ID, "EVOLAB_PHASE2B", PHASE2B_MARKET, PHASE2B_REGISTERED_UTC,
        PHASE2B_DATA_WINDOW, PHASE2B_SOURCE, PHASE2B_ALPHA_DECLARED,
        spec_id=None, direction=None, feature_expr_hash=atom_hash,
        code_hash=PHASE2B_CODE_HASH, candidates_evaluated=PHASE2B_CANDIDATES,
    )
    verdict = _verdict(
        PHASE2B_ID, PHASE2B_READ_UTC, "null",
        # The pooled placebo-exceedance p (the ceiling's own decisive
        # statistic, per the doc's explicit adjudication of the SPA-vs-
        # ceiling disagreement: "the placebo ceiling embodies the correct
        # null and SPA does not"), NOT SPA's p=0.002997 (recorded instead
        # under within_sweep.spa_p, exactly as D2's schema asks for it).
        p=0.871, effect=0.004882213449032019, ci=None,
        battery_version="2.0.0",
        within_sweep={"spa_p": 0.002997, "pbo": 0.6111, "placebo_pct": 13.3},
    )
    return [hyp], [verdict]


# ---------------------------------------------------------------------------
# Elo benchmark -- ONE audit row (kind: "audit", never a hypothesis, D1/D2).
# docs/BENCHMARK_ELO.md
# ---------------------------------------------------------------------------

ELO_ID = "AUDIT:elo_benchmark"
# BENCHMARK_ELO.md is "frozen before any score is computed" but states no
# separate freeze timestamp; it co-locates its freeze with "Run 2026-08-31".
# Flagged in the report as inferred, not a distinct stated date.
ELO_REGISTERED_UTC = "2026-08-31"
ELO_READ_UTC = "2026-08-31"  # "Result: Run 2026-08-31 on 2,234 scored ... games"
ELO_SOURCE = "docs/BENCHMARK_ELO.md"
# "h2h" is not a literal field in this doc; inferred with high confidence
# because an Elo win-probability model is a moneyline forecast by
# construction (there is no F5/totals Elo here) -- a different, more
# confident basis than V3's market=None call. Flagged in the report anyway.
ELO_MARKET = "h2h"
ELO_DATA_WINDOW = {"discovery": "2024", "replication": None, "sealed_untouched": SEALED}


def elo_rows():
    atom_hash = reg.semantic_hash_v0(
        [("elo_vs_close_logloss_benchmark", "audit", ELO_MARKET, "positive")]
    )
    hyp = _row(
        "audit", ELO_ID, "ELO_BENCHMARK", ELO_MARKET, ELO_REGISTERED_UTC,
        ELO_DATA_WINDOW, ELO_SOURCE, None,  # an audit has no FDR q to declare
        spec_id=None, direction="positive", feature_expr_hash=atom_hash,
        code_hash=None,
    )
    verdict = _verdict(
        ELO_ID, ELO_READ_UTC, "audit", p=0.0003, effect=0.00801, ci=None,
        battery_version=None,
    )
    return [hyp], [verdict]


# ---------------------------------------------------------------------------
# Migration driver
# ---------------------------------------------------------------------------

def all_rows():
    """Every hypothesis/sweep/audit row and every verdict row this migration
    knows how to produce, in family order. Returns (hypotheses, verdicts)."""
    hyps, verdicts = [], []
    for builder in (v1_rows, v2_rows, v4_rows, v5_rows, v3_rows, phase2b_rows, elo_rows):
        h, v = builder()
        hyps.extend(h)
        verdicts.extend(v)
    return hyps, verdicts


def migrate(path=None) -> dict:
    """Idempotent: only appends rows for ids not already present at `path`."""
    registry = reg.AlphaRegistry(path)
    existing_hyp_ids = registry._registered_ids()  # noqa: SLF001 (intentional, in-package use)
    existing_verdict_ids = registry._verdict_ids()  # noqa: SLF001
    now = reg.utcnow_iso()

    hyps, verdicts = all_rows()
    appended_hyps = appended_verdicts = skipped_hyps = skipped_verdicts = 0

    for row in hyps:
        if row["id"] in existing_hyp_ids:
            skipped_hyps += 1
            continue
        row["migrated_utc"] = now
        registry.register(row)
        appended_hyps += 1

    for row in verdicts:
        if row["id"] in existing_verdict_ids:
            skipped_verdicts += 1
            continue
        row["migrated_utc"] = now
        registry.record_verdict(row)
        appended_verdicts += 1

    return {
        "path": str(registry.path),
        "appended_hypotheses_sweeps_audits": appended_hyps,
        "skipped_hypotheses_sweeps_audits": skipped_hyps,
        "appended_verdicts": appended_verdicts,
        "skipped_verdicts": skipped_verdicts,
    }


def _counts_for_exact_market(registry: "reg.AlphaRegistry", market) -> dict:
    """Like `total_searched(market=...)` but treats `market=None` as "rows
    whose market field IS None" rather than "no filter" -- `total_searched`'s
    own `market=None` means "don't filter on market" (its documented,
    correct contract for the public API), which is the wrong question for a
    per-market breakdown that wants to show the null-market bucket (V3)
    on its own line rather than folding it into "everything"."""
    counts = {"hypotheses": 0, "sweeps": 0, "sweep_candidates": 0, "audits": 0}
    for row in registry.read_all():
        if row.get("kind") not in reg.REGISTRATION_KINDS:
            continue
        if row.get("market") != market:
            continue
        kind = row["kind"]
        if kind == "hypothesis":
            counts["hypotheses"] += 1
        elif kind == "sweep":
            counts["sweeps"] += 1
            candidates = row.get("candidates_evaluated")
            if isinstance(candidates, (int, float)):
                counts["sweep_candidates"] += candidates
        elif kind == "audit":
            counts["audits"] += 1
    return counts


def _known_markets(registry: "reg.AlphaRegistry") -> list:
    """Every distinct market value actually on the ledger (None included),
    in a stable, readable order -- never a hardcoded guess at what markets
    exist, so a new family's new market shows up here automatically."""
    seen = []
    for row in registry.read_all():
        if row.get("kind") not in reg.REGISTRATION_KINDS:
            continue
        m = row.get("market")
        if m not in seen:
            seen.append(m)
    return sorted(seen, key=lambda m: (m is None, m))


def report(path=None, market=None, data_window=None) -> str:
    registry = reg.AlphaRegistry(path)
    lines = []
    overall = registry.total_searched(market=market, data_window=data_window)
    lines.append("Alpha registry -- searched so far"
                  + (f" (market={market!r})" if market else "")
                  + (f" (data_window={data_window!r})" if data_window else ""))
    lines.append(
        f"  TOTAL: {overall['hypotheses']} hypotheses, {overall['sweeps']} sweeps "
        f"({overall['sweep_candidates']} sweep candidates), {overall['audits']} audits"
    )
    lines.append("  by family:")
    for family in sorted(overall["by_family"]):
        b = overall["by_family"][family]
        lines.append(f"    {family:16s} hypotheses={b['hypotheses']:<3d} "
                      f"sweeps={b['sweeps']:<2d} audits={b['audits']:<2d}")

    if market is None and data_window is None:
        lines.append("")
        lines.append("  per market:")
        for m in _known_markets(registry):
            counts = _counts_for_exact_market(registry, m)
            label = m if m is not None else "(null -- market not recorded, e.g. V3)"
            lines.append(
                f"    {label:45s} hypotheses={counts['hypotheses']:<3d} "
                f"sweeps={counts['sweeps']:<2d} audits={counts['audits']:<2d}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    migrate_cmd = sub.add_parser("migrate", help="idempotently seed the ledger")
    migrate_cmd.add_argument("--path", default=None,
                              help="ledger path (default: data/research/alpha_registry.jsonl)")

    report_cmd = sub.add_parser("report", help="print per-market searched-so-far")
    report_cmd.add_argument("--path", default=None)
    report_cmd.add_argument("--market", default=None)
    report_cmd.add_argument("--data-window", default=None)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "migrate":
        result = migrate(path=args.path)
        print(f"migrated -> {result['path']}")
        print(f"  appended: {result['appended_hypotheses_sweeps_audits']} "
              f"hypotheses/sweeps/audits, {result['appended_verdicts']} verdicts")
        print(f"  skipped (already present): "
              f"{result['skipped_hypotheses_sweeps_audits']} hypotheses/sweeps/audits, "
              f"{result['skipped_verdicts']} verdicts")
    elif args.action == "report":
        print(report(path=args.path, market=args.market, data_window=args.data_window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
