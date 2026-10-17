#!/usr/bin/env python3
"""Perform, record and verify the tier ladder's pre-registered read.

WHY THIS EXISTS
----------------
`docs/PREREG_TIER_LADDER.md` fixed a rule on 2026-09-10 and
`scripts/test_tier_ladder.py` implements it. That script REFUSED while the
ledger held under twenty usable dates, and the daily loop reported the wait
quietly. Once the ledger crossed twenty dates the script began answering
"DO NOT ADOPT" every night, and the loop began printing

    ESCALATE: the tier ladder pre-registration is now answerable and did not
    adopt ...

every night -- for a read that nobody ever performed or wrote down. A line
that fires nightly about something already understood trains everyone to
ignore the night it means something new; a line that goes quiet because
someone deleted the check hides a real miscalibration. Neither is acceptable.
The legitimate way for that line to stop is the one this file provides: the
read is performed ONCE, by the registered script, on a stated cut of the
ledger; the result is written to an artifact that carries its own freeze
check; the registry gets a verdict row that names the artifact's hash; and the
loop, finding all of that intact, prints a RECORDED line instead.

WHAT THIS DOES NOT DO
----------------------
It never edits the registered script, never changes a threshold, and never
touches `src/engine/slip.py`. It does not decide what happens to
EVIDENCE_STRONG when the read fails -- the registration is silent on that and
`docs/decisions/evidence_strong_tier.md` puts the choice to the owner.

THE FOUR WAYS A RECORDED READ STOPS COUNTING
---------------------------------------------
`verify_recorded` returns not-ok, and the loop goes back to ESCALATE, when:

1. the artifact is missing, unparseable, or carries an unanswered verdict;
2. the registration's rule text (everything above its "## Status" heading,
   LF-normalised) no longer hashes to the value frozen in the artifact -- the
   rule was edited after it was read;
3. the registered script's constants no longer equal the ones the read used --
   the instrument was changed after it was read;
4. the alpha registry has no verdict row carrying this artifact's sha256 --
   the read is not on the one ledger of what this project has searched.

Usage:
    python3 scripts/tier_ladder_read.py read --through 2026-10-16 \
        [--write] [--register]
    python3 scripts/tier_ladder_read.py --check-recorded
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import random
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

RULE_ID = "TIER_LADDER_V1"
REGISTRY_ID = "TIER_LADDER:permutation_null_family_agreement:evidence_tier"
PREREG_PATH = os.path.join(REPO, "docs", "PREREG_TIER_LADDER.md")
ARTIFACT_PATH = os.path.join(REPO, "data", "research", "tier_ladder",
                             "tier_ladder_result.json")
LADDER_SCRIPT = os.path.join(REPO, "scripts", "test_tier_ladder.py")
DECISION_NOTE = "docs/decisions/evidence_strong_tier.md"
RESULT_DOC = "docs/research/TIER_LADDER_RESULT.md"

# The commit that froze the rule text, and the instant it was made
# (2026-09-10T12:32:47-07:00). Written down here so a reader does not have to
# go and find them; the freeze check itself is the hash below, not this id.
PREREG_COMMIT = "266ef6552bc7dede1fad148979d176bcce1485b7"
PREREG_COMMIT_UTC = "2026-09-10T19:32:47+00:00"

# Verdicts a recorded read may carry. NOT_ANSWERABLE is deliberately not
# recordable: a read that could not be performed is a wait, not a result, and
# the loop must keep reporting the wait.
RECORDABLE_VERDICTS = ("ADOPT", "NOT_ADOPT")

REGISTERED_CONSTANTS = (
    "STRONG_PERCENTILE", "BUILDING_PERCENTILE", "THIN_PERCENTILE",
    "PERMUTATIONS", "SEED", "MIN_WAGERS_PER_DATE", "MIN_SYSTEMS_PER_DATE",
    "MIN_DATES", "MAX_SPLIT_HALF_DISAGREEMENT",
)


# ---------------------------------------------------------------------------
# Pieces shared by the read and the verifier
# ---------------------------------------------------------------------------

def load_ladder_module():
    """The registered script, imported unmodified under its own name."""
    spec = importlib.util.spec_from_file_location(
        "test_tier_ladder", LADDER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registered_constants(module=None):
    module = module or load_ladder_module()
    return {name: getattr(module, name) for name in REGISTERED_CONSTANTS}


def prereg_rule_sha256(path=PREREG_PATH):
    """sha256 of the registration's rule text.

    Everything above the `## Status` heading, LF-normalised. The Status
    section is a log that is MEANT to be appended to; the rule above it is
    what was frozen, and an edit there after a read voids the read.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    cut = text.find("\n## Status")
    if cut < 0:
        raise ValueError(f"{path} has no '## Status' heading to freeze above")
    return hashlib.sha256(text[:cut + 1].encode("utf-8")).hexdigest()


def file_sha256(path):
    """sha256 of a text file, LF-normalised (same convention as the
    freeze checks recorded for K_OPPONENT)."""
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_blob_id(path):
    from src.research import alpha_registry
    return alpha_registry.git_blob_hash(path)


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def _registered_report(module, through, permutations):
    """Run the registered script's own `main(--json)` on the ledger cut at
    `through`, by narrowing what its loader returns. Its logic is not
    reimplemented here: the report is what it printed."""
    original = module._load_plays

    def cut():
        full = original()
        return {d: w for d, w in full.items() if d <= through}

    module._load_plays = cut
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            argv = ["--json"]
            if permutations is not None:
                argv += ["--permutations", str(permutations)]
            exit_code = module.main(argv)
        return json.loads(buffer.getvalue()), exit_code
    finally:
        module._load_plays = original


def _counts(module, through, family_of, permutations):
    """Real and null family counts per wager, in the registered script's own
    draw order, so they reproduce its report exactly (asserted by the caller)."""
    plays = {d: w for d, w in module._load_plays().items() if d <= through}
    usable = {d: w for d, w in plays.items()
              if len(w) >= module.MIN_WAGERS_PER_DATE
              and len({s for b in w.values() for s in b})
              >= module.MIN_SYSTEMS_PER_DATE}
    rng = random.Random(module.SEED)
    per_date = max(1, permutations // len(usable))
    real, null = [], []
    for date in sorted(usable):
        wagers = usable[date]
        for backers in wagers.values():
            real.append(module._family_count(backers, family_of)[0])
        null.extend(module._null_for_date(wagers, family_of, rng, per_date))
    return plays, usable, real, null


def _share(values, threshold):
    return round(sum(1 for v in values if v >= threshold) / len(values), 4)


def _published_pick_shares(through):
    """STRONG share of picks on the published slips, under the live
    threshold, over slips dated up to `through`. Reported twice: over every
    pick on every slip (the drift audit's own denominator, which counts a
    wager again on each hourly slip that carries it) and over distinct
    wagers."""
    from src.engine import slip as slip_mod

    path = os.path.join(REPO, "evidence", "slips_v1.jsonl")
    if not os.path.exists(path):
        return None
    picks = strong = 0
    wagers = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if (row.get("date") or "") > through:
                continue
            for pick in row.get("picks") or ():
                n = pick.get("n_families")
                if not isinstance(n, int):
                    continue
                picks += 1
                is_strong = n >= slip_mod.EVIDENCE_STRONG_MIN_FAMILIES
                strong += is_strong
                wagers[pick.get("wager_id")] = max(
                    wagers.get(pick.get("wager_id"), 0), n)
    distinct_strong = sum(
        1 for n in wagers.values()
        if n >= slip_mod.EVIDENCE_STRONG_MIN_FAMILIES)
    return {
        "threshold_families": slip_mod.EVIDENCE_STRONG_MIN_FAMILIES,
        "picks_over_all_slips": picks,
        "strong_over_all_slips": strong,
        "share_over_all_slips": round(strong / picks, 4) if picks else None,
        "distinct_wagers": len(wagers),
        "distinct_wagers_ever_strong": distinct_strong,
        "share_over_distinct_wagers": (round(distinct_strong / len(wagers), 4)
                                       if wagers else None),
        "largest_n_families": max(wagers.values()) if wagers else None,
    }


def _structural_only_variant(module, through, permutations):
    """EXPLORATORY, POST HOC, NOT REGISTERED. The same null with the family
    map built from genome structure alone (no behavioural relation), to ask
    whether the finding is only the clustering being fitted on the same
    decisions it is then used to count. Cannot change the verdict. Systems
    the structural map does not cover are counted individually, and how many
    plays that affected is reported."""
    from src.analysis import families as families_mod
    from src.engine import slip as slip_mod
    from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS

    systems = [s for s in REGISTERED_SYSTEMS if slip_mod.is_forward_test(s.id)]
    genomes = {s.id: getattr(s, "genome", None) for s in systems}
    clustering = families_mod.families({}, genomes=genomes)
    family_of = dict(getattr(clustering, "family_id_of", None) or {})
    if not family_of:
        return {"available": False}
    plays, usable, real, null = _counts(module, through, family_of,
                                        permutations)
    unknown = 0
    for wagers in usable.values():
        for backers in wagers.values():
            unknown += module._family_count(backers, family_of)[1]
    return {
        "available": True,
        "status": "exploratory, post hoc, not registered, cannot change the "
                  "verdict",
        "systems_mapped": len(family_of),
        "families": len(set(family_of.values())),
        "plays_with_no_known_family": unknown,
        "real_mean_families": round(statistics.fmean(real), 3),
        "null_mean_families": round(statistics.fmean(null), 3),
    }


def perform_read(through, *, permutations=None):
    """The whole read, as data. Raises if the instrument disagrees with
    itself; never returns a verdict it could not reproduce."""
    module = load_ladder_module()
    permutations = permutations or module.PERMUTATIONS

    report, exit_code = _registered_report(module, through, permutations)
    if "usable_dates" not in report:
        raise RuntimeError(
            f"the registered script did not answer on the cut through "
            f"{through}: {report!r}")

    family_of = module._family_map()
    if not family_of:
        raise RuntimeError("no family map; refusing to read")
    plays, usable, real, null = _counts(module, through, family_of,
                                        permutations)

    # SELF-CHECK. The shares below are computed by this file; the report is
    # computed by the registered script. If they ever disagree, this file's
    # numbers are the suspect and nothing is recorded.
    if (round(statistics.fmean(real), 3) != report["real_mean_families"]
            or round(statistics.fmean(null), 3) != report["null_mean_families"]
            or len(real) != report["wagers_measured"]):
        raise RuntimeError(
            "this file's reproduction of the registered script's counts "
            "does not match its report; refusing to record a read built on "
            "a disagreeing instrument")

    ladder = report["ladder_from_the_null"]
    checks = report["checks"]
    verdict = "ADOPT" if report["ADOPT"] else "NOT_ADOPT"
    failed = sorted(name for name, ok in checks.items() if not ok)

    thresholds = {
        "null_STRONG_cutoff": ladder["STRONG"],
        "null_BUILDING_cutoff": ladder["BUILDING"],
        "null_THIN_cutoff": ladder["THIN"],
        "live_STRONG_threshold": 3,
    }
    share_table = {}
    for name, threshold in thresholds.items():
        share_table[name] = {
            "families_at_least": threshold,
            "real_share_of_wagers": _share(real, threshold),
            "null_share_of_wagers": _share(null, threshold),
        }

    date_list = sorted(usable)
    ledger_dates = sorted(plays)
    return {
        "rule_id": RULE_ID,
        "registry_id": REGISTRY_ID,
        "registration": {
            "doc": "docs/PREREG_TIER_LADDER.md",
            "commit": PREREG_COMMIT,
            "committed_utc": PREREG_COMMIT_UTC,
            "rule_sha256": prereg_rule_sha256(),
        },
        "instrument": {
            "script": "scripts/test_tier_ladder.py",
            "script_blob_id": git_blob_id(LADDER_SCRIPT),
            "constants": registered_constants(module),
            "note": "rule constants and the null/percentile code are "
                    "unchanged since the freeze commit; the script's family "
                    "map source (a glue.family_map fallback that never "
                    "existed, replaced the same day by the live slip's own "
                    "clustering) and its archive-aware reads were revised "
                    "afterwards, before any twenty-date read",
        },
        "read": {
            "through_date": through,
            "ledger_decision_dates": [ledger_dates[0], ledger_dates[-1]],
            "n_ledger_dates": len(ledger_dates),
            "usable_dates": date_list,
            "n_usable_dates": len(date_list),
            "n_wagers_measured": len(real),
            "permutations_total": permutations,
            "permutations_per_date": report["permutations_per_date"],
            "family_map_systems": len(family_of),
            "family_map_families": len(set(family_of.values())),
            "family_map_note": "the live clustering at read time, built "
                               "from the whole forward history exactly as "
                               "the slip builds it (the registered script's "
                               "own map); it is not cut at through_date",
            "family_map_sha256": hashlib.sha256(
                json.dumps(sorted(family_of.items())).encode("utf-8")
            ).hexdigest(),
            "outcomes_read": False,
        },
        "registered_report": report,
        "registered_exit_code": exit_code,
        "failed_checks": failed,
        "verdict": verdict,
        "ladder_the_null_produces": ladder,
        "share_table": share_table,
        "published_picks_under_live_threshold": _published_pick_shares(through),
        "exploratory_structural_only_map": _structural_only_variant(
            module, through, permutations),
        "consequence": {
            "live_threshold_changed": False,
            "EVIDENCE_STRONG_MIN_FAMILIES": 3,
            "what_the_registration_says_to_do":
                "no threshold changes; the current threshold stays with the "
                "debt still recorded (PREREG_TIER_LADDER.md, 'What would "
                "make this fail'). It does not say whether to keep, label, "
                "retire or recalibrate under a successor.",
            "decision_note": DECISION_NOTE,
        },
    }


# ---------------------------------------------------------------------------
# Writing, registering
# ---------------------------------------------------------------------------

def write_artifact(result, path=ARTIFACT_PATH):
    if os.path.exists(path):
        raise FileExistsError(
            f"{path} already exists. A read is performed once; a second "
            f"read on a later cut is a different document, not an overwrite.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def register_read(result, artifact_path=ARTIFACT_PATH, registry_path=None,
                  read_utc=None):
    """Append the audit registration and its verdict to the alpha registry.

    kind='audit' on purpose, as for SR1's amendment: `public_research_counts`
    counts only kind=='hypothesis', and this is a calibration read about a
    label, not a search for a betting edge, so the product's "N ideas
    registered" does not move. It does move `total_searched()` audits by one
    and `read` by one; subtract it when citing those.
    """
    from src.research import alpha_registry

    read_utc = read_utc or alpha_registry.utcnow_iso()
    registration = alpha_registry.register({
        "kind": "audit",
        "id": REGISTRY_ID,
        "family": "TIER_LADDER",
        "market": "forward_slip",
        "sport": "mlb",
        "registered_utc": PREREG_COMMIT_UTC,
        "data_window": {"discovery": "2026-forward", "replication": None,
                        "sealed_untouched": True},
        "alpha_declared": None,
        "direction": "family agreement on a played wager exceeds what the "
                     "same systems would produce by chance, so the evidence "
                     "tier thresholds can be the 95th/75th/50th percentiles "
                     "of a permutation null",
        "feature_expr_hash": None,
        "spec_id": RULE_ID,
        "code_hash": git_blob_id(LADDER_SCRIPT),
        "source_doc": "docs/PREREG_TIER_LADDER.md",
        "note": "Registry row added " + read_utc[:10] + ", at the time of "
                "the read, not at the time of the registration. The "
                "registration itself dates from commit " + PREREG_COMMIT + " (" + PREREG_COMMIT_UTC
                + "), which froze the rule text whose sha256 is "
                + result["registration"]["rule_sha256"] + " (everything "
                "above the Status heading, LF-normalised). The registry did "
                "not know this registration until now; the registration did "
                "not wait for it. kind='audit' so public_research_counts() "
                "keeps counting only hypotheses: this calibrates a label and "
                "searches for no betting edge.",
        "migrated_utc": None,
    }, path=registry_path)

    read = result["read"]
    report = result["registered_report"]
    verdict = alpha_registry.record_verdict({
        "kind": "verdict",
        "id": REGISTRY_ID,
        "read_utc": read_utc,
        "result": "audit",
        "p": None,
        "effect": None,
        "ci": None,
        "battery_version": None,
        "forward_window": {"start": read["usable_dates"][0],
                           "n": read["n_wagers_measured"],
                           "pending": False},
        "note": "RULE VERDICT: " + result["verdict"] + " by the registered "
                "rule. Failed checks: " + ", ".join(result["failed_checks"])
                + ". Read through " + read["through_date"] + ": "
                + str(read["n_usable_dates"]) + " usable dates ("
                + read["usable_dates"][0] + " to " + read["usable_dates"][-1]
                + "), " + str(read["n_wagers_measured"]) + " wagers, real "
                "mean " + str(report["real_mean_families"]) + " families vs "
                "null mean " + str(report["null_mean_families"])
                + "; null ladder STRONG>=" + str(result["ladder_the_null_produces"]["STRONG"])
                + " BUILDING>=" + str(result["ladder_the_null_produces"]["BUILDING"])
                + " THIN>=" + str(result["ladder_the_null_produces"]["THIN"])
                + "; split halves disagree by "
                + str(report["split_half_disagreement"]) + " families "
                "(rule allows 1). result='audit' because this is not a "
                "search result. No threshold changed: "
                "slip.EVIDENCE_STRONG_MIN_FAMILIES stays 3, and the owner "
                "choice about what STRONG should now mean is in "
                + DECISION_NOTE + ". Artifact "
                + os.path.relpath(artifact_path, REPO).replace(os.sep, "/")
                + " sha256 " + file_sha256(artifact_path) + ". Result "
                "document: " + RESULT_DOC + ".",
        "migrated_utc": None,
    }, path=registry_path)
    return registration, verdict


# ---------------------------------------------------------------------------
# The verifier the daily loop calls
# ---------------------------------------------------------------------------

def verify_recorded(artifact_path=ARTIFACT_PATH, registry_path=None,
                    prereg_path=PREREG_PATH, ladder_module=None):
    """`(ok, message, result_or_None)`. ok is True only when every one of
    the four conditions in the module docstring holds."""
    from src.research import alpha_registry

    if not os.path.exists(artifact_path):
        return False, "no recorded read: " + os.path.relpath(
            artifact_path, REPO) + " does not exist", None
    try:
        with open(artifact_path, encoding="utf-8") as fh:
            result = json.load(fh)
    except (OSError, ValueError) as exc:
        return False, f"recorded read unreadable: {exc!r}", None

    if result.get("rule_id") != RULE_ID:
        return False, "recorded read is not for rule " + RULE_ID, result
    if result.get("verdict") not in RECORDABLE_VERDICTS:
        return False, (f"recorded read carries verdict "
                       f"{result.get('verdict')!r}, which is not a recordable "
                       f"answer"), result
    if result["verdict"] == "ADOPT":
        # A recorded ADOPT is never an all-clear: the thresholds still have
        # to be changed by a deliberate edit, so the loop keeps saying so.
        return False, ("the recorded read ADOPTS; src/engine/slip.py has "
                       "not been changed to match it"), result

    try:
        live_rule = prereg_rule_sha256(prereg_path)
    except (OSError, ValueError) as exc:
        return False, f"cannot recompute the registration freeze: {exc!r}", result
    frozen_rule = (result.get("registration") or {}).get("rule_sha256")
    if live_rule != frozen_rule:
        return False, ("the registration's rule text no longer hashes to the "
                       "value the read froze; it was edited after it was "
                       "read, which voids the read"), result

    try:
        live_constants = registered_constants(ladder_module)
    except Exception as exc:  # noqa: BLE001 -- surface, never swallow
        return False, f"cannot load the registered script: {exc!r}", result
    read_constants = (result.get("instrument") or {}).get("constants")
    if live_constants != read_constants:
        return False, ("the registered script's constants differ from the "
                       "ones the read used; the instrument changed after "
                       "the read"), result

    registry = alpha_registry.AlphaRegistry(registry_path)
    digest = file_sha256(artifact_path)
    verdict_rows = [r for r in registry.read_all()
                    if r.get("kind") == "verdict"
                    and r.get("id") == REGISTRY_ID]
    if not any(digest in (r.get("note") or "") for r in verdict_rows):
        return False, ("the alpha registry has no verdict row for "
                       + REGISTRY_ID + " that names this artifact's sha256"), result

    return True, "ok", result


def recorded_line(result):
    read = result["read"]
    report = result["registered_report"]
    return (
        f"RECORDED: tier ladder pre-registration read {result['verdict']} "
        f"through {read['through_date']} ({read['n_usable_dates']} usable "
        f"dates, {read['n_wagers_measured']} wagers; real mean "
        f"{report['real_mean_families']} families vs null mean "
        f"{report['null_mean_families']}; failed: "
        f"{', '.join(result['failed_checks']) or 'none'}). "
        f"EVIDENCE_STRONG is unchanged at "
        f"{result['consequence']['EVIDENCE_STRONG_MIN_FAMILIES']} families; "
        f"what STRONG should now mean is the owner's choice in "
        f"{result['consequence']['decision_note']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-recorded", action="store_true",
                    help="verify the recorded read; print RECORDED and exit "
                         "0, or print why not and exit 1")
    sub = ap.add_subparsers(dest="cmd")
    rd = sub.add_parser("read", help="perform the read")
    rd.add_argument("--through", required=True,
                    help="last decision date (UTC, YYYY-MM-DD) to include")
    rd.add_argument("--permutations", type=int, default=None)
    rd.add_argument("--write", action="store_true",
                    help="write the artifact (refuses to overwrite)")
    rd.add_argument("--register", action="store_true",
                    help="append the registry rows (needs --write first)")
    args = ap.parse_args(argv)

    if args.check_recorded:
        ok, message, result = verify_recorded()
        if ok:
            print(recorded_line(result))
            return 0
        print("not recorded: " + message)
        return 1

    if args.cmd == "read":
        result = perform_read(args.through, permutations=args.permutations)
        if args.write:
            path = write_artifact(result)
            print("wrote " + os.path.relpath(path, REPO))
            if args.register:
                register_read(result, path)
                print("registered " + REGISTRY_ID)
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
