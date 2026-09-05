"""Standalone totals evaluation path (R7/A9 of docs/TOTALS_METHODOLOGY.md).

WHY THIS MODULE IS STANDALONE, AND MIRRORS `src.research.f5_eval` EXACTLY
---------------------------------------------------------------------------
"## Revision 2" R7 (superseding sec 4) is explicit: build a totals-parallel
standalone module mirroring `f5_eval.py`, never widen `funnel.py`'s `MARKETS`
tuple -- push handling, line-aware de-vig, and Over/Under settlement are new
logic that would wear an old module's name. This module's only new code is
row construction (`src.research.totals_rows`, moved out of
`scripts/totals_population_audit.py`'s counts-only parsing). Everything else
is reused verbatim:
  - `src.model.discovery` for date-clustered effects, p-values, intervals.
  - `src.research.battery` at frozen `RULES_VERSION 2.0.0`, no bespoke rule.
  - `src.model.family.benjamini_hochberg` for FDR correction.

NO HYPOTHESIS IS DEFINED HERE (mission boundary)
--------------------------------------------------
"## Methodology re-review" leaves the candidate family's exact composition
open (B2/B3 decide `combined_primary_pitch_share` and bullpen-workload, but
those are §1.2 FEATURE hypotheses this module does not build). R6 identifies
the full-population Over/Under bias measurement as the one totals hypothesis
this module's row shape can already grade -- `totals_rows.build_over_rows`
exists for exactly that shape -- but this module registers NO hypothesis:
`freeze_family` below freezes the standalone-path INFRASTRUCTURE (universe
hashes, spec hash, battery rules version) with an empty `members` list, not a
hypothesis record. A future mission that actually registers TOTALS-OVER (or
any other totals member) re-freezes with a real `members` list; this one
proves the infrastructure it would run against is itself frozen and provable.

NO OUTCOME IS READ UNTIL EXPLICITLY ASKED FOR
------------------------------------------------
`dry_run=True` (the only mode this module's mission authorises against real
data) builds both the half-point primary population and the integer stratum
with `won=None`, re-verifies both universe hashes, runs the row-count and
window-adjacent guards, and STOPS before calling `discovery.evaluate` or
`battery.run` -- both of which require `won`. `run_full_evaluation` (real
stats) exists only so the mechanism is present and tested against synthetic
data; the mission that built this module does not authorise running it
against real feature data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import totals_m2_coverage
from src.model import discovery, family
from src.paths import data_path, repo_root
from src.research import battery, totals_rows

EXPECTED_MIN_JOINT_N = 300  # sanity floor -- a manifest below this is data poverty, not a family

# B1/A4/A5 floors and gates, named exactly as F5's for the same reason: a
# candidate must clear these before it can be called a survivor.
EFFECT_FLOOR = 0.010  # one probability point -- src.model.family.MIN_EFFECT
POPULATION_SHIFT_P_FATAL = 0.01
FDR_M = 1  # infrastructure freeze registers zero hypotheses; see module docstring

FROZEN_FAMILY_PATH = data_path("research", "totals", "family_frozen.json")

# R2 (bounded spec hash): the totals spec's own two governing sections,
# bounded by the NEXT top-level heading so a later-appended review note
# cannot silently move what the hash covers.
SPEC_DOC_PATH = repo_root() / "docs" / "TOTALS_METHODOLOGY.md"
_REVISION2_MARKER = "## Revision 2"
_REREVIEW_MARKER = "## Methodology re-review"

# ---------------------------------------------------------------------------
# docs/PREREG_TOTALS_FAMILIES.md "## Methodology review -- 2026-09-05"
# (D1-D7): the CONFIRMATORY TOTALS-M1 family. This is deliberately a SEPARATE
# freeze path from the infrastructure freeze above (`freeze_family`,
# `FROZEN_FAMILY_PATH`, `SPEC_DOC_PATH`) -- that mechanism was built to
# register zero hypotheses (M1's mission boundary at the time), and this
# module never retargets it, so its existing tests and its family record
# shape both stay exactly what they were. `freeze_confirmatory_family` below
# is the NEW mechanism the review's D7 requires: family_id
# `TOTALS_FULLGAME_2026H1`, M1 confirmatory (m=1), M2 recorded inside it as a
# pre-determined exploratory POPULATION_SHIFT_FAIL (D3) -- one family_id,
# per D5 HC7, never two.
CONFIRMATORY_FAMILY_ID = "TOTALS_FULLGAME_2026H1"
CONFIRMATORY_FROZEN_FAMILY_PATH = data_path("research", "totals", "m1_family_frozen.json")

# D2: the family is honestly underpowered below 3.0pp (per-leg MDE ~2.72-
# 2.73pp at the corrected n) -- raised from the draft's withdrawn 1.5pp
# floor. Frozen numerically; may never be lowered after a near-miss.
M1_EFFECT_FLOOR = 0.030

# M-A1 fix (docs/PREREG_TOTALS_FAMILIES.md "## Adversarial pre-registration
# review -- 2026-09-05"): EVERY numeric gate the FINAL SPECIFICATION's
# freeze-record JSON names, as named module constants, so
# `freeze_confirmatory_family` can write them all (not just the three
# hashes + fdr_m the ORIGINAL freeze wrote) and `_verify_confirmatory_family`
# can cross-check ALL of them against this live module at run time -- not
# only `fdr_m`. A record IS the pre-registration only if every gate it
# claims to freeze is both written AND re-checked; writing one without the
# other (the pre-M-A1 state) lets a later commit silently lower a gate with
# every freeze-record guard still passing.
M1_CANNOT_TELL_BAND_PP = (0.0, 3.0)  # D2/O1: open at the top -- 3.0pp exactly is a PASS
POPULATION_SHIFT_LINE_BUCKET_EDGES = totals_rows.LINE_BUCKET_EDGES
POPULATION_SHIFT_BOOK_COUNT_BUCKET_EDGES = totals_rows.BOOK_COUNT_BUCKET_EDGES

PREREG_SPEC_DOC_PATH = repo_root() / "docs" / "PREREG_TOTALS_FAMILIES.md"
# B-A1 fix (docs/PREREG_TOTALS_FAMILIES.md "## Adversarial pre-registration
# review -- 2026-09-05"): the ORIGINAL `_PREREG_START_MARKER = "## Family
# denominator"` hashed from the superseded DRAFT section to end-of-file --
# unbounded at the end (a later-appended review note silently moved the
# hash) AND wrong at the start (it covered withdrawn DRAFT numbers the FINAL
# SPECIFICATION explicitly supersedes). Mirrors `f5_eval._extract_spec_text`
# exactly (same review, same fix, same shape): hash the FINAL SPECIFICATION
# section (up to, not including, the adversarial-review section) plus the
# Post-adversarial amendments section, bounded at the next top-level
# heading so a future review note appended after the amendments cannot move
# what a frozen record was taken against.
_PREREG_FINAL_SPEC_MARKER = "## FINAL SPECIFICATION (post-review, 2026-09-05)"
_PREREG_ADVERSARIAL_MARKER = "## Adversarial pre-registration review"
_PREREG_AMENDMENTS_MARKER = "## Post-adversarial amendments"


class TotalsEvalError(RuntimeError):
    """Raised when the totals evaluation path cannot proceed honestly."""


# ---------------------------------------------------------------------------
# Guards -- run BEFORE any row is trusted
# ---------------------------------------------------------------------------

def verify_universe(*, seasons=totals_rows.SEASONS, archive_root=totals_rows.ARCHIVE_ROOT,
                     results_path=totals_rows.RESULTS_CSV,
                     max_staleness_hours=totals_rows.MAX_STALENESS_HOURS,
                     manifest_path=totals_rows.MANIFEST_PATH) -> dict:
    """Re-verify both hashes against the frozen manifest. Aborts (raises) on
    any mismatch rather than proceeding on a universe that may have moved --
    identical contract to `f5_eval.verify_universe`."""
    if not Path(manifest_path).exists():
        raise TotalsEvalError(
            f"no universe manifest frozen at {manifest_path}. Call "
            "src.research.totals_rows.build_universe/write_manifest before "
            "evaluating -- there is nothing to re-verify against.")
    frozen = totals_rows.read_manifest(manifest_path)
    recomputed = totals_rows.build_universe(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        max_staleness_hours=max_staleness_hours)

    if frozen["content_hash"] != recomputed["content_hash"]:
        raise TotalsEvalError(
            "identity-hash mismatch: the eligible totals universe changed "
            f"since it was frozen (frozen={frozen['content_hash']}, "
            f"recomputed={recomputed['content_hash']}). Aborting -- this "
            "family's denominator cannot be trusted.")

    frozen_price_hash = frozen.get("price_payload_hash")
    if frozen_price_hash is None:
        raise TotalsEvalError(
            "the frozen manifest carries no price_payload_hash -- re-run "
            "src.research.totals_rows.build_universe to add it before "
            "evaluating.")
    if frozen_price_hash != recomputed["price_payload_hash"]:
        raise TotalsEvalError(
            "price-payload-hash mismatch: a book price moved since the "
            f"freeze (frozen={frozen_price_hash}, "
            f"recomputed={recomputed['price_payload_hash']}). Aborting -- a "
            "re-fetch or repair changed prices without moving the identity "
            "hash.")

    return {"content_hash": frozen["content_hash"],
            "price_payload_hash": frozen_price_hash, "verified": True}


def _verify_row_shape(rows: list, *, expected_seasons=totals_rows.SEASONS) -> None:
    """Denominator/hash guard (validation item 3): every row carries a
    season inside the evaluated set, and every row's date is a real ISO
    string. Raises rather than filtering -- a row outside this shape here
    means the universe filter upstream failed."""
    for row in rows:
        if row["season"] not in expected_seasons:
            raise TotalsEvalError(
                f"row for game_pk={row['game_pk']} carries season "
                f"{row['season']!r}, outside the evaluated set "
                f"{expected_seasons} -- aborting rather than silently "
                "dropping it.")
        date = row.get("date")
        if not date or len(str(date)) < 10:
            raise TotalsEvalError(
                f"row for game_pk={row['game_pk']} has no usable date "
                f"({date!r}) -- aborting.")


# ---------------------------------------------------------------------------
# M1 -- standalone freeze mechanism
# ---------------------------------------------------------------------------

def _extract_spec_text(full_text: str) -> str:
    """The exact text `spec_sha256` hashes: "## Revision 2" through the end
    of "## Methodology re-review -- 2026-09-05" (R2's bounded-spec-hash
    rule) -- never a narrative section appended after it. Raises if either
    marker is missing: a family must not be frozen against a document that
    predates the amendments this freeze depends on."""
    if _REVISION2_MARKER not in full_text:
        raise TotalsEvalError(
            f"{_REVISION2_MARKER!r} not found in spec text -- cannot "
            "compute spec_sha256 against a document that lacks it")
    if _REREVIEW_MARKER not in full_text:
        raise TotalsEvalError(
            f"{_REREVIEW_MARKER!r} not found in spec text -- freeze against "
            "a document that has not yet incorporated the re-review's B1-B6 "
            "decisions")
    revision2_onward = full_text.split(_REVISION2_MARKER, 1)[1]
    if _REREVIEW_MARKER not in revision2_onward:
        raise TotalsEvalError("Revision 2 marker found after the re-review "
                              "marker -- document section order is wrong")
    rereview_onward = revision2_onward.split(_REREVIEW_MARKER, 1)[1]
    # Bound to the NEXT top-level heading after the re-review section (R2):
    # a later-appended review note cannot silently move what the hash covers.
    nxt = rereview_onward.find("\n## ")
    if nxt != -1:
        rereview_onward = rereview_onward[:nxt]
    return (_REVISION2_MARKER + revision2_onward[:revision2_onward.index(_REREVIEW_MARKER)]
            + _REREVIEW_MARKER + rereview_onward.rstrip("\n") + "\n")


def spec_sha256(spec_path=SPEC_DOC_PATH) -> str:
    """sha256 over "## Revision 2" + "## Methodology re-review" text only,
    so a frozen record can prove the spec has not moved underneath it since
    registration (M1/R2)."""
    text = Path(spec_path).read_text(encoding="utf-8")
    return hashlib.sha256(_extract_spec_text(text).encode("utf-8")).hexdigest()


def _extract_prereg_spec_text(full_text: str) -> str:
    """The exact text `prereg_spec_sha256` hashes: the FINAL SPECIFICATION
    section (up to, not including, the adversarial-review section) plus the
    Post-adversarial amendments section, mirroring
    `f5_eval._extract_spec_text` exactly (B-A1 fix). Raises if either marker
    is missing -- a family must not be frozen against a document that has
    not yet been amended for the adversarial-review findings this freeze
    depends on."""
    if _PREREG_FINAL_SPEC_MARKER not in full_text:
        raise TotalsEvalError(
            f"{_PREREG_FINAL_SPEC_MARKER!r} not found in spec text -- "
            "cannot compute the confirmatory family's spec_sha256 against "
            "a document that lacks it")
    if _PREREG_AMENDMENTS_MARKER not in full_text:
        raise TotalsEvalError(
            f"{_PREREG_AMENDMENTS_MARKER!r} not found in spec text -- "
            "amend the spec for the adversarial-review findings before "
            "freezing the family")
    spec_section = full_text.split(_PREREG_FINAL_SPEC_MARKER, 1)[1]
    if _PREREG_ADVERSARIAL_MARKER in spec_section:
        spec_section = spec_section.split(_PREREG_ADVERSARIAL_MARKER, 1)[0]
    amendments_section = full_text.split(_PREREG_AMENDMENTS_MARKER, 1)[1]
    # Bound the amendments section to the next top-level heading so that
    # appending later review sections to the document cannot move the hash
    # a frozen record was taken against.
    nxt = amendments_section.find("\n## ")
    if nxt != -1:
        amendments_section = amendments_section[:nxt]
    return (_PREREG_FINAL_SPEC_MARKER + spec_section
            + _PREREG_AMENDMENTS_MARKER + amendments_section.rstrip("\n") + "\n")


def prereg_spec_sha256(spec_path=PREREG_SPEC_DOC_PATH) -> str:
    """sha256 over `docs/PREREG_TOTALS_FAMILIES.md`'s FINAL SPECIFICATION +
    Post-adversarial amendments text only -- the confirmatory TOTALS-M1
    family's own spec hash, kept entirely separate from `spec_sha256`'s
    TOTALS_METHODOLOGY.md hash above (M1). B-A1: bounded at both ends so
    neither superseded DRAFT text nor a later-appended review note can move
    what this hash covers."""
    text = Path(spec_path).read_text(encoding="utf-8")
    return hashlib.sha256(_extract_prereg_spec_text(text).encode("utf-8")).hexdigest()


def freeze_family(path=FROZEN_FAMILY_PATH, *, spec_path=SPEC_DOC_PATH,
                   manifest_path=totals_rows.MANIFEST_PATH, now=None) -> dict:
    """M1: freeze the standalone totals-evaluation-path INFRASTRUCTURE to an
    immutable JSON record -- universe hashes, spec hash, battery rules
    version, staleness bound/anchor -- with `members: []` (no hypothesis
    registered by this mission; see module docstring). Refuses to overwrite
    an existing record. Never called against the real `FROZEN_FAMILY_PATH`
    by anything in this module -- freezing the real family is a deliberate,
    reviewed, separate act."""
    target = Path(path)
    if target.exists():
        raise TotalsEvalError(
            f"a family record is already frozen at {target}. Refusing to "
            "overwrite it -- re-registering the family is a reviewed "
            "commit that deletes the old file first, deliberately.")

    manifest = totals_rows.read_manifest(manifest_path)
    record = {
        "family_id": "TOTALS_STANDALONE_PATH_INFRASTRUCTURE",
        "members": [],  # no hypothesis registered by this mission
        "fdr_q": family.FDR_Q,
        "battery_rules_version": battery.RULES_VERSION,
        "max_staleness_hours": totals_rows.MAX_STALENESS_HOURS,
        "anchor_rule": totals_rows.ANCHOR_RULE,
        "book_floor": totals_rows.BOOK_FLOOR,
        "universe_identity_hash": manifest["content_hash"],
        "universe_price_payload_hash": manifest["price_payload_hash"],
        "universe_counts": manifest["counts"],
        "spec_sha256": spec_sha256(spec_path),
        "frozen_at": (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc).isoformat(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return record


def read_frozen_family(path=FROZEN_FAMILY_PATH) -> dict:
    target = Path(path)
    if not target.exists():
        raise TotalsEvalError(
            f"no family record frozen at {target}. Call freeze_family() to "
            "register the standalone-path infrastructure before running "
            "any evaluation -- a correction and a set of gates computed "
            "against an unregistered path is not a pre-registration.")
    return json.loads(target.read_text(encoding="utf-8"))


def _verify_frozen_family(hashes: dict, *, path=FROZEN_FAMILY_PATH,
                          spec_path=SPEC_DOC_PATH) -> dict:
    """`run_full_evaluation`'s precondition. Raises unless the frozen record
    exists AND its universe hashes and spec_sha256 still match what is true
    right now."""
    record = read_frozen_family(path)
    current_spec_sha = spec_sha256(spec_path)
    if record.get("spec_sha256") != current_spec_sha:
        raise TotalsEvalError(
            "the frozen family's spec_sha256 no longer matches "
            f"{spec_path} -- the specification changed after the family "
            "was frozen. Aborting rather than running against a moved "
            "target.")
    if record.get("universe_identity_hash") != hashes["content_hash"]:
        raise TotalsEvalError(
            "the frozen family's universe_identity_hash does not match the "
            "just-reverified universe -- aborting.")
    if record.get("universe_price_payload_hash") != hashes["price_payload_hash"]:
        raise TotalsEvalError(
            "the frozen family's universe_price_payload_hash does not "
            "match the just-reverified universe -- aborting.")
    if record.get("battery_rules_version") != battery.RULES_VERSION:
        raise TotalsEvalError(
            f"the frozen record's battery_rules_version "
            f"({record.get('battery_rules_version')!r}) disagrees with the "
            f"live battery ({battery.RULES_VERSION!r}) -- aborting.")
    return record


def freeze_confirmatory_family(path=CONFIRMATORY_FROZEN_FAMILY_PATH, *,
                               spec_path=PREREG_SPEC_DOC_PATH,
                               manifest_path=totals_rows.MANIFEST_PATH,
                               now=None) -> dict:
    """D7(7): freeze the CONFIRMATORY `TOTALS_FULLGAME_2026H1` family to an
    immutable JSON record -- TOTALS-M1 confirmatory (m=1), TOTALS-M2
    recorded inside the SAME family_id with `verdict` pre-set to
    `POPULATION_SHIFT_FAIL` (D3) and excluded from the FDR family. Refuses
    to overwrite an existing record, exactly like `freeze_family` and
    `f5_eval.freeze_family` -- once frozen, the record IS the
    pre-registration. Never called against the real
    `CONFIRMATORY_FROZEN_FAMILY_PATH` by anything in this module -- freezing
    the real family is a deliberate, reviewed, separate act, and the mission
    that built this function does not authorise it.
    """
    target = Path(path)
    if target.exists():
        raise TotalsEvalError(
            f"a confirmatory family record is already frozen at {target}. "
            "Refusing to overwrite it -- re-registering the family is a "
            "reviewed commit that deletes the old file first, deliberately.")

    manifest = totals_rows.read_manifest(manifest_path)
    record = {
        "family_id": CONFIRMATORY_FAMILY_ID,
        "members": [
            {
                "id": "TOTALS-M1",
                "name": "Full-population Over/Under closing-line calibration",
                "confirmatory": True,
                "line_stratum": "half_point_primary",
                "devig_primary": "per_line_proportional_ge_3books",
                "devig_sensitivity": ["power", "shin"],
                "devig_sensitivity_gates": True,
                "effect_floor_pp": M1_EFFECT_FLOOR * 100,
                "cannot_tell_band_pp": list(M1_CANNOT_TELL_BAND_PP),  # M-A1/O1
                "direction": "fixed_by_2023_screen_leg_own_sign",  # D5 HC3
                "disclosed_prior_exposure":
                    "V7_2.3_proxy: Under 54.6-56.9pct / Over 40.4-42.5pct -- "
                    "even a SURVIVOR verdict is a disclosed-exposure "
                    "calibration measurement, not a fresh discovery (D5 HC3)",
                "population_shift_kill": {
                    "test": "chi_square", "fatal_p_lt": POPULATION_SHIFT_P_FATAL,
                    "line_bucket_edges": list(POPULATION_SHIFT_LINE_BUCKET_EDGES),
                    "book_count_bucket_edges": list(POPULATION_SHIFT_BOOK_COUNT_BUCKET_EDGES),
                },
            },
            {
                "id": "TOTALS-M2",
                "name": "combined_starter_groundball_share partition",
                "confirmatory": False,
                "verdict": "POPULATION_SHIFT_FAIL",  # D3: pre-determined before freeze
                "excluded_from_fdr": True,
                "devig_sensitivity_gates": False,  # O2: kept explicit, never omitted
                "bucketing": "tercile",
                "bucket_edges_fit_on": "2023_discovery_only",
                "population_shift_kill": {
                    "test": "chi_square_on_own_partition_occupancy",
                    "fatal_p_lt": POPULATION_SHIFT_P_FATAL,
                },
            },
        ],
        "fdr_q": family.FDR_Q,
        "fdr_m": FDR_M,  # D3: m=1, TOTALS-M1 alone -- see class docstring above
        "fdr_does_no_work": True,  # D3: m=1 reduces BH-FDR to p<=fdr_q, strictly weaker than the CI gate
        "clustering": "date",
        "screen_pass_rule": "sign_and_point_estimate_ge_3.0pp_only",
        "replication_pass_rule": (
            "point_estimate_ge_3.0pp_same_sign_AND_two_sided_95pct_CI_"
            "date_clustered_excludes_zero"),
        "battery_rules_version": battery.RULES_VERSION,
        "battery_rules_recorded_skipped": ["rule_3_per_book_sign_replication", "season_split"],
        "max_staleness_hours": totals_rows.MAX_STALENESS_HOURS,
        "anchor_rule": totals_rows.ANCHOR_RULE,
        "book_floor": totals_rows.BOOK_FLOOR,
        "verdict_precedence": list(VERDICTS_PRECEDENCE),  # M-A2: one order, cited by the doc
        "excluded_members_permanent": ["combined_primary_pitch_share (B2)"],
        "deferred_members": ["bullpen_combined_workload (B3)"],
        "requires_independent_forward_leg_before_promotion": True,
        "sealed_period_not_a_forward_leg": ["2026-01-01", "2026-08-27"],
        "universe_identity_hash": manifest["content_hash"],
        "universe_price_payload_hash": manifest["price_payload_hash"],
        "universe_exclusion_ledger": manifest.get("exclusion_ledger"),
        "spec_sha256": prereg_spec_sha256(spec_path),
        "frozen_at": (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc).isoformat(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return record


def read_confirmatory_family(path=CONFIRMATORY_FROZEN_FAMILY_PATH) -> dict:
    target = Path(path)
    if not target.exists():
        raise TotalsEvalError(
            f"no confirmatory family record frozen at {target}. Call "
            "freeze_confirmatory_family() to register TOTALS-M1 before "
            "running any evaluation.")
    return json.loads(target.read_text(encoding="utf-8"))


def _verify_confirmatory_family(hashes: dict, *, path=CONFIRMATORY_FROZEN_FAMILY_PATH,
                                spec_path=PREREG_SPEC_DOC_PATH) -> dict:
    """`run_full_evaluation`'s precondition for the confirmatory family:
    raises unless the frozen record exists, its universe hashes and spec
    hash still match, and EVERY numeric gate the record claims to freeze
    still agrees with this module's live constants -- M-A1 fix. Before
    M-A1 only `fdr_m` was cross-checked (D7(7)), so a later commit could
    silently lower `M1_EFFECT_FLOOR` (or any other gate) and every guard
    here would still pass; "the record IS the pre-registration" is true
    only once every gate the record writes is also re-checked here,
    mirroring `f5_eval._verify_frozen_family`'s B2 guard."""
    record = read_confirmatory_family(path)
    current_spec_sha = prereg_spec_sha256(spec_path)
    if record.get("spec_sha256") != current_spec_sha:
        raise TotalsEvalError(
            "the frozen confirmatory family's spec_sha256 no longer "
            f"matches {spec_path} -- the specification changed after the "
            "family was frozen. Aborting rather than running against a "
            "moved target.")
    if record.get("universe_identity_hash") != hashes["content_hash"]:
        raise TotalsEvalError(
            "the frozen confirmatory family's universe_identity_hash does "
            "not match the just-reverified universe -- aborting.")
    if record.get("universe_price_payload_hash") != hashes["price_payload_hash"]:
        raise TotalsEvalError(
            "the frozen confirmatory family's universe_price_payload_hash "
            "does not match the just-reverified universe -- aborting.")
    if record.get("fdr_m") != FDR_M:
        raise TotalsEvalError(
            f"the frozen record's fdr_m ({record.get('fdr_m')!r}) disagrees "
            f"with this module's FDR_M ({FDR_M!r}) -- D7(7) cross-check "
            "failed; the record and the code must agree before any run.")
    if record.get("fdr_q") != family.FDR_Q:
        raise TotalsEvalError(
            f"the frozen record's fdr_q ({record.get('fdr_q')!r}) disagrees "
            f"with the live family.FDR_Q ({family.FDR_Q!r}) -- aborting.")
    if record.get("clustering") != "date":
        raise TotalsEvalError(
            f"the frozen record's clustering ({record.get('clustering')!r}) "
            "disagrees with the live date-clustered inference this module "
            "runs -- aborting.")
    if record.get("battery_rules_version") != battery.RULES_VERSION:
        raise TotalsEvalError(
            f"the frozen record's battery_rules_version "
            f"({record.get('battery_rules_version')!r}) disagrees with the "
            f"live battery ({battery.RULES_VERSION!r}) -- aborting.")
    m1 = next((m for m in record.get("members", []) if m.get("id") == "TOTALS-M1"), None)
    if m1 is None:
        raise TotalsEvalError(
            "the frozen confirmatory record carries no TOTALS-M1 member -- "
            "aborting.")
    if m1.get("effect_floor_pp") != M1_EFFECT_FLOOR * 100:
        raise TotalsEvalError(
            f"the frozen record's TOTALS-M1 effect_floor_pp "
            f"({m1.get('effect_floor_pp')!r}) disagrees with the live "
            f"M1_EFFECT_FLOOR ({M1_EFFECT_FLOOR * 100!r}) -- M-A1 cross-"
            "check failed; a lowered floor must not silently run.")
    if tuple(m1.get("cannot_tell_band_pp") or []) != M1_CANNOT_TELL_BAND_PP:
        raise TotalsEvalError(
            f"the frozen record's TOTALS-M1 cannot_tell_band_pp "
            f"({m1.get('cannot_tell_band_pp')!r}) disagrees with the live "
            f"M1_CANNOT_TELL_BAND_PP ({M1_CANNOT_TELL_BAND_PP!r}) -- aborting.")
    shift = m1.get("population_shift_kill") or {}
    if shift.get("fatal_p_lt") != POPULATION_SHIFT_P_FATAL:
        raise TotalsEvalError(
            "the frozen record's TOTALS-M1 population_shift_kill.fatal_p_lt "
            f"({shift.get('fatal_p_lt')!r}) disagrees with the live "
            f"POPULATION_SHIFT_P_FATAL ({POPULATION_SHIFT_P_FATAL!r}) -- "
            "aborting.")
    if tuple(shift.get("line_bucket_edges") or []) != POPULATION_SHIFT_LINE_BUCKET_EDGES:
        raise TotalsEvalError(
            "the frozen record's TOTALS-M1 population_shift_kill."
            "line_bucket_edges disagrees with the live "
            f"POPULATION_SHIFT_LINE_BUCKET_EDGES -- aborting.")
    if (tuple(shift.get("book_count_bucket_edges") or [])
       != POPULATION_SHIFT_BOOK_COUNT_BUCKET_EDGES):
        raise TotalsEvalError(
            "the frozen record's TOTALS-M1 population_shift_kill."
            "book_count_bucket_edges disagrees with the live "
            "POPULATION_SHIFT_BOOK_COUNT_BUCKET_EDGES (B-A2) -- aborting.")
    if record.get("max_staleness_hours") != totals_rows.MAX_STALENESS_HOURS:
        raise TotalsEvalError(
            f"the frozen record's max_staleness_hours "
            f"({record.get('max_staleness_hours')!r}) disagrees with the "
            f"live totals_rows.MAX_STALENESS_HOURS "
            f"({totals_rows.MAX_STALENESS_HOURS!r}) -- aborting.")
    if record.get("book_floor") != totals_rows.BOOK_FLOOR:
        raise TotalsEvalError(
            f"the frozen record's book_floor ({record.get('book_floor')!r}) "
            f"disagrees with the live totals_rows.BOOK_FLOOR "
            f"({totals_rows.BOOK_FLOOR!r}) -- aborting.")
    return record


# ---------------------------------------------------------------------------
# M2 (exploratory) -- pre-determined POPULATION_SHIFT_FAIL (D3/D4)
# ---------------------------------------------------------------------------

def evaluate_m2_exploratory(*, seasons=totals_m2_coverage.SEASONS,
                            matrix_paths=None, archive_root=None,
                            results_path=None) -> dict:
    """D3/D4/D7: TOTALS-M2's real fatal gate, computed counts-only (no
    outcome field is read) by reusing `scripts.totals_m2_coverage`'s
    both-sides-or-None join and 2023-fit tercile edges VERBATIM -- never
    re-derived here, so this module's read of M2's chi-square can never
    silently diverge from the published `docs/TOTALS_M2_COVERAGE.md`
    figures. `verdict` is pre-set to `POPULATION_SHIFT_FAIL` regardless of
    what `fatal` recomputes to -- D3 is explicit that this is a REGISTERED
    pre-determination, not a live gate M2 could still pass; `fatal` is
    reported alongside only so a reader can see the pre-determination is
    honest, not asserted without evidence. Always exploratory, always
    excluded from the confirmatory BH-FDR family (m=1, M1 alone).
    """
    kwargs = {"seasons": seasons}
    if matrix_paths is not None:
        kwargs["matrix_paths"] = matrix_paths
    if archive_root is not None:
        kwargs["archive_root"] = archive_root
    if results_path is not None:
        kwargs["results_path"] = results_path
    coverage = totals_m2_coverage.compute_coverage(**kwargs)
    replication_season = seasons[-1]
    chi = coverage["per_season"][replication_season]["chi_square"]
    p = chi.get("p_value")
    fatal = p is not None and p < POPULATION_SHIFT_P_FATAL
    return {
        "member_id": "TOTALS-M2",
        "name": "combined_starter_groundball_share partition",
        "confirmatory": False,
        "excluded_from_fdr": True,
        "verdict": "POPULATION_SHIFT_FAIL",
        "population_shift": {"chi_square": chi, "p": p, "fatal": fatal},
        "coverage": coverage,
        "note": ("D3: pre-registered POPULATION_SHIFT_FAIL before any "
                 "outcome is read -- excluded from the confirmatory BH-FDR "
                 "family (m=1, TOTALS-M1 alone) and reported exploratory-"
                 "only, non-confirmatory, non-promotable."),
    }


# ---------------------------------------------------------------------------
# B3 -- mechanised verdict (generic; not run against an unregistered member)
# ---------------------------------------------------------------------------

# M-A2 fix (docs/PREREG_TOTALS_FAMILIES.md "## Adversarial pre-registration
# review -- 2026-09-05", decided at open item O1): the ONE precedence order,
# cited by the FINAL SPECIFICATION's amended "Verdict codes and precedence"
# section and implemented ONLY here -- `VERDICTS`, `compute_verdict`, and the
# doc must never again state three different orders. A pre-outcome kill
# (POPULATION_SHIFT_FAIL), a fatal battery flag (BATTERY_FAIL), and a de-vig
# sign failure (DEVIG_SIGN_FAIL) are all statements about the DESIGN and
# outrank CANNOT_TELL, a statement about POWER; CANNOT_TELL in turn outranks
# SCREEN_FAIL/REPLICATION_FAIL, which are statements about the observed
# read. Before this fix CANNOT_TELL was checked second (right after
# POPULATION_SHIFT_FAIL), so an in-band result the frozen battery flagged as
# FATAL was reported CANNOT_TELL -- not a rescue (CANNOT_TELL is not a
# pass), but it hid a battery failure from the published record, which the
# family's own "publish the losers" principle forbids.
VERDICTS_PRECEDENCE = ("POPULATION_SHIFT_FAIL", "BATTERY_FAIL", "DEVIG_SIGN_FAIL",
                      "CANNOT_TELL", "SCREEN_FAIL", "REPLICATION_FAIL", "SURVIVOR")
VERDICTS = VERDICTS_PRECEDENCE


def compute_verdict(*, population_shift_fatal: bool, screen_passes: bool,
                    replication_sign_agrees: bool, replication_ci_excludes_zero: bool,
                    survives_fdr: bool, devig_sign_survives: bool,
                    battery_survives: bool, screen_cannot_tell: bool = False,
                    replication_cannot_tell: bool = False,
                    replication_floor_ok: bool = True) -> str:
    """Fixed precedence (M-A2/O1) -- extends `f5_eval.compute_verdict`'s
    shape with D2's CANNOT_TELL verdict (item 6), in `VERDICTS_PRECEDENCE`
    order:

    1. POPULATION_SHIFT_FAIL -- decided before any outcome (B1/D1), must win
       over every outcome-dependent gate below it.
    2. BATTERY_FAIL -- the frozen battery flags a fatal rule: a statement
       about the DESIGN, and must never be absorbed by CANNOT_TELL below it.
    3. DEVIG_SIGN_FAIL -- the effect's sign does not survive all three
       de-vig conventions (A4): also a DESIGN statement, outranks CANNOT_TELL.
    4. CANNOT_TELL -- D2: a true effect of 0-3.0pp is inside the noise band
       either leg's own MDE cannot distinguish from zero. Set by the caller
       when the screen or replication point estimate is non-zero but below
       `M1_EFFECT_FLOOR` WITH the pre-registered sign -- never a PASS, never
       a FAIL of the market's calibration, and it must win over SCREEN_FAIL/
       REPLICATION_FAIL (an underpowered read is not the same claim as "no
       effect exists" or "the effect disagrees").
    5. SCREEN_FAIL -- the screen leg shows no detectable signal at all
       (effect is exactly zero or unreadable) -- distinct from CANNOT_TELL.
    6. REPLICATION_FAIL -- the replication leg's sign/floor/CI/FDR gate
       fails (D2: the 3.0pp floor binds on BOTH legs, not just the screen).
    7. SURVIVOR -- every gate above cleared.
    """
    if population_shift_fatal:
        return "POPULATION_SHIFT_FAIL"
    if not battery_survives:
        return "BATTERY_FAIL"
    if not devig_sign_survives:
        return "DEVIG_SIGN_FAIL"
    if screen_cannot_tell or replication_cannot_tell:
        return "CANNOT_TELL"
    if not screen_passes:
        return "SCREEN_FAIL"
    if not (replication_sign_agrees and replication_ci_excludes_zero
           and survives_fdr and replication_floor_ok):
        return "REPLICATION_FAIL"
    return "SURVIVOR"


def evaluate_screen(rows_screen, *, effect_floor=M1_EFFECT_FLOOR) -> dict:
    """B1/D5 HC3: the screen-leg pass criterion -- point estimate >= floor
    IN MAGNITUDE only (no CI, no FDR on this leg, exactly F5's binding
    amendment). D5 HC3: M1's tested sign is not pre-committed to a
    direction -- it is FIXED BY the 2023 screen leg's own point estimate,
    so `expected_sign` is an OUTPUT of this function, not an input to it;
    the 2024 replication leg must then agree with whatever sign the screen
    leg itself showed. D2: an effect that is real but smaller than the
    3.0pp floor is CANNOT_TELL, never a screen failure -- a screen failure
    is reserved for a genuinely null/unreadable read (effect exactly 0.0 or
    the leg has no decided rows at all).
    """
    result = discovery.evaluate("TOTALS-M1-screen", rows_screen)
    effect = result["effect"]
    if effect is None:
        return {"effect": None, "n": result["decided"], "passes_screen": False,
                "cannot_tell": False, "expected_sign": 0}
    expected_sign = 1 if effect > 0 else (-1 if effect < 0 else 0)
    passes = abs(effect) >= effect_floor
    cannot_tell = (not passes) and expected_sign != 0
    return {"effect": effect, "n": result["decided"], "passes_screen": passes,
            "cannot_tell": cannot_tell, "expected_sign": expected_sign}


def _replication_gate(result_replication: dict, expected_sign: int = 1,
                      *, effect_floor=M1_EFFECT_FLOOR) -> dict:
    """D2: the 2024 replication leg's sign-agreement, CI-excludes-zero, and
    (new, D2) floor-in-magnitude checks. `cannot_tell` fires only when the
    sign AGREES with the screen's (`expected_sign`) but the magnitude sits
    inside the 0-3.0pp band -- a sign DISAGREEMENT is a real fail, never
    merely underpowered."""
    effect = result_replication.get("effect")
    ci = result_replication.get("ci")
    sign_agrees = effect is not None and (
        effect > 0 if expected_sign > 0 else effect < 0)
    ci_excludes_zero = bool(
        ci and (ci.get("low", 0) > 0 or ci.get("high", 0) < 0))
    floor_ok = effect is not None and abs(effect) >= effect_floor
    cannot_tell = sign_agrees and not floor_ok
    return {"sign_agrees": sign_agrees, "ci_excludes_zero": ci_excludes_zero,
            "floor_ok": floor_ok, "cannot_tell": cannot_tell}


def devig_sign_survives_check(sensitivity: dict, key: str, expected_sign: int = 1) -> bool:
    """A4: the effect must keep `expected_sign` under all three de-vig
    conventions. A convention with too few rows to produce an effect fails
    this check -- a missing sign cannot be said to have survived."""
    for label in totals_rows.DEVIG_METHODS:
        effect = sensitivity[label][key]["effect"]
        if effect is None:
            return False
        if expected_sign > 0 and not (effect > 0):
            return False
        if expected_sign < 0 and not (effect < 0):
            return False
    return True


def devig_sensitivity(*, seasons=totals_rows.SEASONS, screen_season, replication_season,
                      archive_root=totals_rows.ARCHIVE_ROOT,
                      results_path=totals_rows.RESULTS_CSV) -> dict:
    """A2/R2: the full-population OVER effect under all three de-vig
    conventions, screen and replication legs separately."""
    out = {}
    for label, method in totals_rows.DEVIG_METHODS.items():
        rows = totals_rows.build_over_rows(
            seasons=seasons, archive_root=archive_root, results_path=results_path,
            method=method, dry_run=False)
        screen_rows = [r for r in rows if r["season"] == screen_season]
        replication_rows = [r for r in rows if r["season"] == replication_season]
        out[label] = {
            "screen": discovery.evaluate(f"TOTALS-OVER-{label}-screen", screen_rows),
            "replication": discovery.evaluate(f"TOTALS-OVER-{label}-replication", replication_rows),
        }
    return out


def run_battery(rows, *, effect_floor=EFFECT_FLOOR) -> dict:
    """Battery.run at the frozen rules, verbatim -- no bespoke rule. Records
    every check the battery itself reported as skipped, and why (item 5),
    plus two skips the battery cannot detect on its own because it never
    sees WHY a rule was structurally unable to fire on this row shape:

    - `season_split`: FATAL_CHECK, but this module's replication leg is
      single-season by construction (the 2024 leg alone, per B1/D2's
      binding "never pooled" rule) -- leave-one-season-out has nothing to
      leave out. Mirrors `f5_eval.run_battery`'s identical R1 fix.
    - `book_concentration`: these rows carry one CONSENSUS row per game
      (`totals_rows.consensus_fair_for_line`'s cross-book mean), never a
      per-row `book` field, so a per-book concentration check is inert on
      this shape the same way F5's per-book rule is on its consensus rows.
    """
    result = battery.run(rows, effect_floor=effect_floor)
    skipped = {name: check["skipped"] for name, check in result["report"].items()
               if isinstance(check, dict) and "skipped" in check}

    seasons_present = {str(r.get("season") or str(r.get("date", ""))[:4]) for r in rows}
    if len(seasons_present) <= 1 and "season_split" not in skipped:
        reason = ("single-season leg (%s): season_split cannot fire; "
                  "leave-one-season-out is not evaluable on the replication "
                  "leg by design (B1/D2)" % (",".join(sorted(seasons_present)) or "none"))
        skipped["season_split"] = reason
        rep = result["report"].get("season_split")
        if isinstance(rep, dict):
            rep["skipped"] = reason

    has_per_row_book = any(r.get("book") is not None for r in rows)
    if not has_per_row_book and "book_concentration" not in skipped:
        reason = ("rows carry one cross-book CONSENSUS price per game, "
                  "never a per-row book -- book_concentration is inert on "
                  "this shape (item 5)")
        skipped["book_concentration"] = reason
        rep = result["report"].get("book_concentration")
        if isinstance(rep, dict):
            rep["skipped"] = reason

    result["skipped_checks"] = skipped
    return result


# ---------------------------------------------------------------------------
# Full evaluation (requires `won` -- NOT run against real data by this
# mission; present so the mechanism exists and is tested against synthetic
# rows, and so `run(dry_run=False)` on synthetic data exercises every gate).
# ---------------------------------------------------------------------------

def integer_stratum_report(*, seasons=totals_rows.SEASONS,
                           archive_root=totals_rows.ARCHIVE_ROOT,
                           results_path=totals_rows.RESULTS_CSV,
                           method=totals_rows.PRIMARY_DEVIG_METHOD) -> dict:
    """Item 9: the integer-line stratum, report-only, FOREVER (D6 lever i --
    it can never substitute for, rescue, or be promoted over the half-point
    primary). Estimand is P(over | no push) -- pushes are already excluded
    from both numerator and denominator by `totals_rows.build_integer_
    stratum_rows`. This function computes no gate, no verdict, no CI: just
    the raw over-rate per season, so a reader sees the number without
    mistaking it for a confirmatory result."""
    rows = totals_rows.build_integer_stratum_rows(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        method=method, dry_run=False)
    by_season = {}
    for season in seasons:
        season_rows = [r for r in rows if r["season"] == season]
        n = len(season_rows)
        overs = sum(1 for r in season_rows if r["won"] is True)
        by_season[season] = {
            "n_no_push": n,
            "overs": overs,
            "p_over_given_no_push": round(overs / n, 4) if n else None,
        }
    return {
        "report_only": True,
        "promotable": False,
        "by_season": by_season,
        "note": ("D6 lever (i): P(over | no push) on the integer-line "
                 "stratum is a second look at the same question on an "
                 "adjacent population and is report-only forever -- it can "
                 "never substitute for, rescue, or be promoted over the "
                 "half-point primary (item 9)."),
    }


def run_full_evaluation(*, screen_season="2023", replication_season="2024",
                        seasons=totals_rows.SEASONS,
                        archive_root=totals_rows.ARCHIVE_ROOT,
                        results_path=totals_rows.RESULTS_CSV,
                        max_staleness_hours=totals_rows.MAX_STALENESS_HOURS,
                        manifest_path=totals_rows.MANIFEST_PATH,
                        confirmatory_family_path=CONFIRMATORY_FROZEN_FAMILY_PATH,
                        spec_path=PREREG_SPEC_DOC_PATH,
                        m2_matrix_paths=None) -> dict:
    """D7: the complete, outcome-reading evaluation of the CONFIRMATORY
    `TOTALS_FULLGAME_2026H1` family -- TOTALS-M1 (confirmatory, m=1) plus
    TOTALS-M2 (exploratory, pre-determined POPULATION_SHIFT_FAIL, D3).
    Refuses to run unless the confirmatory family is frozen
    (`freeze_confirmatory_family`) and its record still matches the live
    universe, spec text, and every numeric gate (M-A1).

    M-A3 fix: `manifest_path`/`confirmatory_family_path`/`spec_path` were
    previously hardcoded to the real default paths with no way to point
    this function at a synthetic fixture, which is WHY no test ever
    exercised this happy path end to end (the one call site that reached
    this far raised inside `verify_universe` against the real manifest, not
    inside the gate it claimed to test). Defaults are unchanged, so no real
    call site's behaviour changes.
    """
    hashes = verify_universe(seasons=seasons, archive_root=archive_root,
                             results_path=results_path,
                             max_staleness_hours=max_staleness_hours,
                             manifest_path=manifest_path)
    _verify_confirmatory_family(hashes, path=confirmatory_family_path, spec_path=spec_path)

    rows = totals_rows.build_over_rows(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        method=totals_rows.PRIMARY_DEVIG_METHOD, dry_run=False)
    _verify_row_shape(rows, expected_seasons=seasons)

    screen_rows = [r for r in rows if r["season"] == screen_season]
    replication_rows = [r for r in rows if r["season"] == replication_season]

    shift = totals_rows.population_shift_test(screen_rows, replication_rows)

    # D5 HC3: the tested sign is FIXED by the screen leg's own point
    # estimate -- never imported from a proxy, never chosen after the fact.
    screen = evaluate_screen(screen_rows)
    expected_sign = screen["expected_sign"] or 1  # 1 is inert when screen itself is null/CANNOT_TELL

    replication_result = discovery.evaluate("TOTALS-M1-replication", replication_rows)
    replication_gate = _replication_gate(replication_result, expected_sign=expected_sign)
    battery_result = run_battery(replication_rows, effect_floor=M1_EFFECT_FLOOR)

    # D3: m=1 -- TOTALS-M1 alone. M2 is excluded from this list entirely
    # (never merely down-weighted): "the FDR step does no work in this
    # family and no multiplicity credit may be claimed from it" (D3).
    fdr_input = [{"name": "TOTALS-M1", "p": replication_result["p"]}]
    if len(fdr_input) != FDR_M:
        raise TotalsEvalError(
            f"FDR family size drifted: expected FDR_M={FDR_M}, built "
            f"{len(fdr_input)} p-values -- D7(7) regression.")
    corrected = family.benjamini_hochberg(fdr_input)
    by_name = {c["name"]: c for c in corrected}

    sensitivity = devig_sensitivity(seasons=seasons, screen_season=screen_season,
                                    replication_season=replication_season,
                                    archive_root=archive_root, results_path=results_path)
    devig_ok = devig_sign_survives_check(
        {label: {"replication": v["replication"]} for label, v in sensitivity.items()},
        "replication", expected_sign=expected_sign)

    m1_verdict = compute_verdict(
        population_shift_fatal=shift["fatal"],
        screen_passes=screen["passes_screen"],
        screen_cannot_tell=screen["cannot_tell"],
        replication_sign_agrees=replication_gate["sign_agrees"],
        replication_ci_excludes_zero=replication_gate["ci_excludes_zero"],
        replication_floor_ok=replication_gate["floor_ok"],
        replication_cannot_tell=replication_gate["cannot_tell"],
        survives_fdr=by_name["TOTALS-M1"]["survives_fdr"],
        devig_sign_survives=devig_ok,
        battery_survives=battery_result["survives"])

    m2 = evaluate_m2_exploratory(seasons=seasons, matrix_paths=m2_matrix_paths,
                                 archive_root=archive_root, results_path=results_path)

    integer_stratum = integer_stratum_report(
        seasons=seasons, archive_root=archive_root, results_path=results_path)

    return {
        "family_id": CONFIRMATORY_FAMILY_ID,
        "m1": {
            "population_shift": shift,
            "screen": screen,
            "expected_sign": expected_sign,
            "replication": replication_result,
            "replication_gate": replication_gate,
            "battery": battery_result,
            "devig_sensitivity": sensitivity,
            "devig_sign_survives": devig_ok,
            "survives_fdr": by_name["TOTALS-M1"]["survives_fdr"],
            "verdict": m1_verdict,
            "disclosed_prior_exposure_note": (
                "even a SURVIVOR verdict here is reported as a calibration "
                "MEASUREMENT with disclosed prior exposure (V7 2.3), not a "
                "fresh confirmatory discovery, and may not promote to any "
                "trading decision without an independent forward "
                "out-of-sample leg (D5 HC3)."),
        },
        "m2": m2,
        "integer_stratum_report_only": integer_stratum,
        "fdr_m1_only": corrected,
    }


# ---------------------------------------------------------------------------
# Entry point -- dry_run is the only mode this module's own mission
# authorises against real feature data.
# ---------------------------------------------------------------------------

def run(*, dry_run=True, seasons=totals_rows.SEASONS,
        archive_root=totals_rows.ARCHIVE_ROOT,
        results_path=totals_rows.RESULTS_CSV,
        max_staleness_hours=totals_rows.MAX_STALENESS_HOURS,
        screen_season="2023", replication_season="2024") -> dict:
    """`dry_run=True`: exercises row construction for both the half-point
    primary population and the integer stratum, both hash guards, and the
    row-shape guard -- all feature-side against real data, with `won`
    replaced by `None` everywhere and no `discovery.evaluate`/`battery.run`
    call made. `dry_run=False` calls `run_full_evaluation`, which reads
    `won` -- not authorised against real data by this module's mission.
    """
    hashes = verify_universe(seasons=seasons, archive_root=archive_root,
                             results_path=results_path,
                             max_staleness_hours=max_staleness_hours)

    if not dry_run:
        result = run_full_evaluation(
            screen_season=screen_season, replication_season=replication_season,
            seasons=seasons, archive_root=archive_root, results_path=results_path,
            max_staleness_hours=max_staleness_hours)
        result["hashes"] = hashes
        result["dry_run"] = False
        return result

    over_rows = totals_rows.build_over_rows(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        dry_run=True)
    assert all(r["won"] is None for r in over_rows), (
        "dry_run must never expose an outcome")
    _verify_row_shape(over_rows, expected_seasons=seasons)

    integer_rows = totals_rows.build_integer_stratum_rows(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        dry_run=True)
    assert all(r["won"] is None for r in integer_rows), (
        "dry_run must never expose an outcome")

    by_season_over = {s: sum(1 for r in over_rows if r["season"] == s) for s in seasons}
    by_season_int = {s: sum(1 for r in integer_rows if r["season"] == s) for s in seasons}

    return {
        "dry_run": True,
        "hashes": hashes,
        "row_counts": {"half_point_primary": len(over_rows), "integer_stratum": len(integer_rows)},
        "season_split": {"half_point_primary": by_season_over, "integer_stratum": by_season_int},
        "note": ("no statistic computed -- won was never read; this is the "
                 "only mode authorised against real data until a totals "
                 "family is registered per docs/TOTALS_METHODOLOGY.md."),
    }
