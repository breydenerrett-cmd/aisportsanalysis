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


# ---------------------------------------------------------------------------
# B3 -- mechanised verdict (generic; not run against an unregistered member)
# ---------------------------------------------------------------------------

def compute_verdict(*, population_shift_fatal: bool, screen_passes: bool,
                    replication_sign_agrees: bool, replication_ci_excludes_zero: bool,
                    survives_fdr: bool, devig_sign_survives: bool,
                    battery_survives: bool) -> str:
    """Fixed precedence, identical shape to `f5_eval.compute_verdict`:

    1. POPULATION_SHIFT_FAIL -- decided before any outcome (B1), must win
       over every outcome-dependent gate below it.
    2. SCREEN_FAIL -- the screen leg fails sign/floor.
    3. REPLICATION_FAIL -- the replication leg's sign/CI/FDR gate fails.
    4. DEVIG_SIGN_FAIL -- the effect's sign does not survive all three de-vig
       conventions (A4).
    5. BATTERY_FAIL -- the frozen battery flags a fatal rule.
    6. SURVIVOR -- every gate above cleared.
    """
    if population_shift_fatal:
        return "POPULATION_SHIFT_FAIL"
    if not screen_passes:
        return "SCREEN_FAIL"
    if not (replication_sign_agrees and replication_ci_excludes_zero and survives_fdr):
        return "REPLICATION_FAIL"
    if not devig_sign_survives:
        return "DEVIG_SIGN_FAIL"
    if not battery_survives:
        return "BATTERY_FAIL"
    return "SURVIVOR"


def evaluate_screen(rows_screen) -> dict:
    """B1: the screen-leg pass criterion -- sign + point estimate >= floor
    only (no CI, no FDR on this leg, exactly F5's binding amendment)."""
    result = discovery.evaluate("TOTALS-OVER-screen", rows_screen)
    effect = result["effect"]
    passes = effect is not None and effect > 0 and effect >= EFFECT_FLOOR
    return {"effect": effect, "n": result["decided"], "passes_screen": passes}


def _replication_gate(result_replication: dict, expected_sign: int = 1) -> dict:
    effect = result_replication.get("effect")
    ci = result_replication.get("ci")
    sign_agrees = effect is not None and (
        effect > 0 if expected_sign > 0 else effect < 0)
    ci_excludes_zero = bool(
        ci and (ci.get("low", 0) > 0 or ci.get("high", 0) < 0))
    return {"sign_agrees": sign_agrees, "ci_excludes_zero": ci_excludes_zero}


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
    """Battery.run at the frozen rules, verbatim -- no bespoke rule."""
    result = battery.run(rows, effect_floor=effect_floor)
    skipped = {name: check["skipped"] for name, check in result["report"].items()
               if isinstance(check, dict) and "skipped" in check}
    result["skipped_checks"] = skipped
    return result


# ---------------------------------------------------------------------------
# Full evaluation (requires `won` -- NOT run against real data by this
# mission; present so the mechanism exists and is tested against synthetic
# rows, and so `run(dry_run=False)` on synthetic data exercises every gate).
# ---------------------------------------------------------------------------

def run_full_evaluation(*, screen_season="2023", replication_season="2024",
                        seasons=totals_rows.SEASONS,
                        archive_root=totals_rows.ARCHIVE_ROOT,
                        results_path=totals_rows.RESULTS_CSV,
                        max_staleness_hours=totals_rows.MAX_STALENESS_HOURS) -> dict:
    """The complete, outcome-reading evaluation of the R6 full-population
    OVER hypothesis. Refuses to run unless the infrastructure family is
    frozen (`freeze_family`) and its record still matches the live universe
    and spec text."""
    hashes = verify_universe(seasons=seasons, archive_root=archive_root,
                             results_path=results_path,
                             max_staleness_hours=max_staleness_hours)
    _verify_frozen_family(hashes)

    rows = totals_rows.build_over_rows(
        seasons=seasons, archive_root=archive_root, results_path=results_path,
        method=totals_rows.PRIMARY_DEVIG_METHOD, dry_run=False)
    _verify_row_shape(rows, expected_seasons=seasons)

    screen_rows = [r for r in rows if r["season"] == screen_season]
    replication_rows = [r for r in rows if r["season"] == replication_season]

    shift = totals_rows.population_shift_test(screen_rows, replication_rows)

    screen = evaluate_screen(screen_rows)
    replication_result = discovery.evaluate("TOTALS-OVER-replication", replication_rows)
    replication_gate = _replication_gate(replication_result)
    battery_result = run_battery(replication_rows)

    fdr_input = [{"name": "TOTALS-OVER", "p": replication_result["p"]}]
    corrected = family.benjamini_hochberg(fdr_input)
    by_name = {c["name"]: c for c in corrected}

    sensitivity = devig_sensitivity(seasons=seasons, screen_season=screen_season,
                                    replication_season=replication_season,
                                    archive_root=archive_root, results_path=results_path)
    devig_ok = devig_sign_survives_check(
        {label: {"replication": v["replication"]} for label, v in sensitivity.items()},
        "replication")

    verdict = compute_verdict(
        population_shift_fatal=shift["fatal"],
        screen_passes=screen["passes_screen"],
        replication_sign_agrees=replication_gate["sign_agrees"],
        replication_ci_excludes_zero=replication_gate["ci_excludes_zero"],
        survives_fdr=by_name["TOTALS-OVER"]["survives_fdr"],
        devig_sign_survives=devig_ok,
        battery_survives=battery_result["survives"])

    return {
        "population_shift": shift,
        "screen": screen,
        "replication": replication_result,
        "replication_gate": replication_gate,
        "battery": battery_result,
        "devig_sensitivity": sensitivity,
        "devig_sign_survives": devig_ok,
        "survives_fdr": by_name["TOTALS-OVER"]["survives_fdr"],
        "verdict": verdict,
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
