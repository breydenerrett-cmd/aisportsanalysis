#!/usr/bin/env python3
"""Find code that is correct, tested, committed -- and that nothing calls.

WHY THIS EXISTS
----------------
2026-09-09/10 produced eight significant findings that looked like eight
different bugs. They were one bug, eight times:

  * the lineup-cadence gate lived in a workflow file cron never reads
  * `engine slip` existed and no script invoked it, so the ranked-picks
    surface was invisible in production while working perfectly in a dry run
  * `gameflow` had NEVER been called by any script or workflow, so the
    play-by-play store did not exist, so every post-game mechanism check
    honestly returned UNDETERMINED -- 0 classifications in 624 reviews of a
    fully-wired, fully-tested, carefully-documented classifier
  * api/billing.py's checkout endpoint was complete and the web view had no
    button, so the subscription revenue path did not exist
  * CLV had never been measured; the falsification battery read NOT_RUN on
    all 85 scorecards

Every one is the same shape: A COMPONENT NOTHING REACHES. And every one was
invisible to the test suite, because a unit test imports the thing it tests.
Tests answer "does this work". Nothing answered "does anything CALL this".

This does. It walks from the entry points that genuinely execute -- the
scheduled workflows, the shell scripts they invoke, the FastAPI app, the
browser router -- and reports every CLI command, HTTP route and view module
that no caller reaches.

WHAT A FINDING MEANS
---------------------
Not automatically a bug. Plenty of commands are legitimately
operator-invoked, and this prints those separately once they are declared.
The finding is: THIS RUNS ONLY IF A HUMAN REMEMBERS. Everything in the list
above was something a human was going to remember.

EXIT CODES: 0 clean, 1 undeclared orphans found.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Commands that legitimately have no automated caller. Each needs a reason,
# and the reason is the point: an entry here is a decision someone made, not
# an accident nobody noticed. Adding one is cheap; adding one you cannot
# justify in a sentence is the smell.
#
# BE STINGY HERE. Declaring a command silences it forever, and "I'll remember
# to run it" is the exact belief that left the play-by-play store empty for
# weeks. Every entry needs a reason that would still convince someone reading
# it cold in six months. If the reason is "it's important, we run it when we
# need to", that is a scheduling bug wearing a declaration.
#
DECLARED_MANUAL = {
    # --- read-only diagnostics: answer a question a human just asked -------
    "brief": "operator asks for a summary; produces no state",
    "budget": "credit-spend readout, read by a person deciding to spend",
    "credits": "same, for the odds-API balance",
    "status": "one-shot health readout",
    "health": "one-shot health readout",
    "timing": "profiling, run when something feels slow",
    "history": "browses ledgers; writes nothing",
    "ledger": "ledger inspection and verification by hand",
    "movement": "line-movement inspection for a specific game",
    "features": "prints the feature registry for a human reading it",
    "cadence": "prints the capture cadence plan",
    "l1": "L1 board inspection",
    "scan": "ad-hoc board scan with a question attached",
    "analyze": "runs one analysis interactively and prints it",

    # --- one-off or recovery: correct BECAUSE they are not automatic -------
    "archive": "operator-run cold-storage move; docs/RESOURCE_POLICY.md",
    "restore": "operator-run recovery path",
    "admin": "operator tooling, human-initiated by definition",
    "backfill": "one-off historical loads, credit-metered",
    "probe": "exploratory research probes, run by hand with a question",
    "boxscores": "historical backfill; the daily path settles from results",
    "ingest": "historical backfill",
    "snapshot": "manual capture outside the cadence",
    "closing-backfill": "one-off repair of historical closing rows",
    "mybets-closing-backfill": "one-off repair, same",
    "calibration-demo": "documentation artefact, not a pipeline step",
    "engine conform": "one-off ledger conformance repair",
    "engine truncation": "one-off ledger truncation repair",
    "engine replay-one": "single-decision replay for debugging",
    "slate": "superseded by `engine slate`, which IS scheduled",
    "grade": "superseded by `engine settle`, which IS scheduled",
    "scan-grade": "superseded by `engine settle`",
    "results": "superseded by `engine settle`",
    "predict": "blocked on `train` below, not independently schedulable",
}

# NOT DECLARED, ON PURPOSE. These stay red because their absence is silent
# and consequential, and each has already cost something measurable:
#
#   train         "fit and evaluate the probability model" -- never called by
#                 anything, which is exactly why p_model_provenance ==
#                 model_derived has ZERO rows across the whole ledger. Win
#                 probability, edge %, confidence meters and variable staking
#                 are all gated on a model nothing has ever trained. The
#                 gate is honest; the reason it never opens is this.
#   postmortem    the learning loop's reporting half -- "why the losses lost,
#                 with a won control". Its input finally exists as of
#                 2026-09-10; nothing reads it.
#   closing-audit CLV integrity checking, in a product whose only measured
#                 leading indicator is CLV.
#

# The files that actually execute on a schedule or in a request. Anything not
# reachable from one of these runs only when a person types it.
ENTRY_SHELL = sorted((REPO / "scripts").glob("*.sh"))
CLI_PATH = REPO / "src" / "cli.py"
API_DIR = REPO / "api"
WEB_JS = REPO / "web" / "js"

# CRON READS THE DEFAULT BRANCH, NOT THIS ONE.
#
# GitHub fires a scheduled workflow from the repository's DEFAULT branch's
# copy of the file. This repo's default branch is an orphan holding five
# files; the working branch is where everything else lives. So a workflow
# edited here changes nothing on a schedule -- which is exactly how the
# lineup-cadence gate came to sit in a committed, tested, reviewed workflow
# that never ran once (tests/test_cadence_is_deployed.py exists for that
# incident).
#
# This audit walked the WORKING tree's .github/workflows, so a command wired
# only in a working-branch workflow looked reachable while cron never touched
# it -- the same blind spot the audit was written to close, inside the audit.
# Found by checking, by hand, whether the gameflow ingest committed a few
# hours earlier would actually fire.
#
# Falls back to the working tree when the default branch cannot be read (a
# shallow clone, no remote, a fresh checkout) and SAYS SO in the output,
# because silently auditing the wrong branch is worse than not auditing.
DEFAULT_BRANCH = "claude/cowork-session-migration-tn3sx2"


def _default_branch_workflows():
    """(sources, note) -- the workflow text cron actually reads."""
    import subprocess
    for ref in (f"origin/{DEFAULT_BRANCH}", DEFAULT_BRANCH):
        try:
            listing = subprocess.run(
                ["git", "ls-tree", "--name-only", "-r", ref, ".github/"],
                cwd=str(REPO), capture_output=True, text=True, timeout=20)
            if listing.returncode != 0:
                continue
            paths = [p for p in listing.stdout.split() if p.endswith(".yml")]
            if not paths:
                continue
            out = []
            for path in paths:
                blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                                      cwd=str(REPO), capture_output=True,
                                      text=True, timeout=20)
                if blob.returncode == 0:
                    out.append(blob.stdout)
            if out:
                return out, f"{len(out)} workflow(s) from {ref} (what cron reads)"
        except Exception:  # noqa: BLE001
            continue
    local = [_read(p) for p in sorted((REPO / ".github" / "workflows").glob("*.yml"))]
    return local, (f"{len(local)} workflow(s) from the WORKING TREE -- could "
                   f"not read {DEFAULT_BRANCH}, so a command wired only here "
                   f"may look reachable while cron never runs it")


ENTRY_WORKFLOW_SOURCES, WORKFLOW_SOURCE_NOTE = _default_branch_workflows()


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _strip_comments_sh(text):
    return "\n".join(l for l in text.splitlines()
                     if not l.lstrip().startswith("#"))


def _strip_comments_py(text):
    """Docstrings and comments discuss commands by name at length. The
    gameflow ingest was described in prose in three documents while nothing
    called it -- matching on prose is how that stays invisible."""
    out, in_doc, delim = [], False, None
    for line in text.splitlines():
        stripped = line.strip()
        if in_doc:
            if delim in stripped:
                in_doc = False
            continue
        if stripped.startswith(('"""', "'''")):
            delim = stripped[:3]
            if not (stripped.endswith(delim) and len(stripped) > 3):
                in_doc = True
            continue
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def cli_commands():
    """Every subcommand src/cli.py registers, as the string a caller types.

    Nesting matters: `engine_sub.add_parser("slate")` is invoked as
    `engine slate`, never as `slate`. A flat scan reports every nested
    command as an orphan, and forty false alarms is how a checker gets
    ignored -- which is the same way the real orphans survived.
    """
    text = _read(CLI_PATH)
    # subparsers-object variable -> the command path that reaches it
    groups = {"sub": ""}
    for var, parent in re.findall(
            r"(\w+)\s*=\s*(\w+)\.add_subparsers\(", text):
        # `engine_cmd = sub.add_parser("engine")` then
        # `engine_sub = engine_cmd.add_subparsers()`
        # \b matters: without it `parser` matches inside `dense_parser` and
        # every top-level command comes back prefixed "dense".
        m = re.search(r"\b" + re.escape(parent)
                      + r'\s*=\s*\w+\.add_parser\(\s*[\'"]'
                      r'([a-z0-9_\-]+)[\'"]', text)
        groups[var] = m.group(1) if m else ""
    out = set()
    for var, name in re.findall(
            r'(\w+)\.add_parser\(\s*[\'"]([a-z0-9_\-]+)[\'"]', text):
        prefix = groups.get(var)
        if prefix is None:
            continue  # not a registered subparsers object
        out.add(f"{prefix} {name}".strip())
    return out


def cli_callers():
    """Every subcommand any executing file actually invokes."""
    called = set()
    corpus = [_strip_comments_sh(_read(p)) for p in ENTRY_SHELL]
    # Workflow text comes from the DEFAULT branch -- see the comment on
    # _default_branch_workflows for why the working tree's copy is the wrong
    # thing to read.
    corpus += [_strip_comments_sh(src) for src in ENTRY_WORKFLOW_SOURCES]
    # Scripts that shell out to other scripts still count as executing code.
    for blob in corpus:
        for m in re.finditer(r"cli\s+([a-z0-9_\-]+)(?:\s+([a-z0-9_\-]+))?",
                             blob):
            called.add(m.group(1))
            if m.group(2):
                called.add(f"{m.group(1)} {m.group(2)}")
    return called


def http_routes():
    """Every route the API serves, as (method, path)."""
    routes = set()
    for path in sorted(API_DIR.glob("*.py")):
        text = _strip_comments_py(_read(path))
        for m in re.finditer(
                r'@(?:router|app)\.(get|post|put|patch|delete)\(\s*[\'"]'
                r'([^\'"]+)[\'"]', text):
            routes.add((m.group(1).upper(), m.group(2)))
    return routes


def http_callers():
    """Every path any browser module or script requests.

    Template literals count: dayrecap.js asks for `/daily/${date}`, which is
    a real call to GET /daily/{date}. Matching only quoted literals reported
    every parameterised route as an orphan.
    """
    called = set()
    for path in (sorted(WEB_JS.glob("*.js"))
                 + sorted((REPO / "web").glob("*.html"))):
        text = _read(path)
        called.update(re.findall(r'[\'"`](/[a-z0-9_\-/{}.]*)', text))
        # `/daily/${date}` -> the prefix `/daily/` is what matters
        called.update(m + "/" for m in
                      re.findall(r'`(/[a-z0-9_\-/]*?)\$\{', text))
    for path in ENTRY_SHELL:
        called.update(re.findall(r'(/[a-z0-9_\-/]+)',
                                 _strip_comments_sh(_read(path))))
    return called


# Routes the BROWSER navigates to rather than any code fetching: the app
# shell and the static assets under it. Declared, not silently skipped.
BROWSER_NAVIGATED = {"/", "/web", "/web/", "/web/{path:path}"}


def _route_is_called(path, callers):
    """A templated route (/game/{pk}) is never requested literally."""
    if path in BROWSER_NAVIGATED or path in callers:
        return True
    prefix = path.split("{", 1)[0].rstrip("/")
    if not prefix or prefix == "/":
        return False
    return any(c == prefix or c.startswith(prefix + "/")
               or c.rstrip("/") == prefix for c in callers)


def orphan_scripts():
    """Python scripts under scripts/ that nothing executes.

    THE AUDIT'S SECOND BLIND SPOT, found the day after the first.

    scripts/*.sh were treated as ENTRY POINTS -- things that run -- and
    scripts/*.py were never considered at all, in either direction. So a
    Python script nobody calls was invisible to the one tool whose entire
    job is finding code nobody calls.

    It cost something immediately: scripts/prereg_clv_feature_test.py, whose
    own commit message says "a hypothesis nobody automated is one that
    quietly never gets tested," was called by nothing, while this audit
    reported CLEAN.

    `--check`-style helpers invoked from CI count as reached, since ci.sh is
    walked like any other shell entry point.
    """
    called = "\n".join(
        [_strip_comments_sh(_read(p)) for p in ENTRY_SHELL]
        + [_strip_comments_sh(src) for src in ENTRY_WORKFLOW_SOURCES])
    orphans = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        name = path.name
        if name in DECLARED_MANUAL_SCRIPTS:
            continue
        # Matched on the file NAME, so `python3 scripts/x.py`,
        # `python -m scripts.x` and a bare `scripts/x.py` all count.
        if name not in called and path.stem not in called:
            orphans.append(name)
    return orphans


# Same stinginess as DECLARED_MANUAL: a reason that would still convince
# someone reading it cold, or wire the thing up.
DECLARED_MANUAL_SCRIPTS = {
    "__init__.py",            # a package marker, not a script

    # --- one-off migrations and corrections: correct BECAUSE they are not
    #     automatic. Re-running one is at best a no-op and at worst a
    #     duplicate row in an append-only ledger.
    "alpha_registry_migrate.py",
    "append_edge_withdrawal_corrections.py",

    # --- exploratory probes: each was written to answer one question that
    #     had an owner at the time. A probe on a schedule is a probe nobody
    #     is reading.
    "probe_historical_boundaries.py",
    "probe_historical_f5_props.py",
    "probe_historical_leadtime.py",
    "probe_prop_name_join.py",

    # --- credit-metered or long-running research runs, started deliberately
    #     with a budget in mind (docs/RESOURCE_POLICY.md).
    "evolab_sweep.py",
    "run_f5_tminus2_tranche.py",
    "factory_masks_from_sweep.py",
    "factory_lifecycle_dryrun.py",

    # --- freezes: a family is frozen once, on purpose, by a person who has
    #     decided to freeze it.
    "f5_freeze_family.py",
    "totals_freeze_family.py",

    # --- THE CARD'S TWO MEASUREMENTS. Both are read-only, both take
    #     minutes over the full season, and both answer a question a person
    #     is currently asking rather than gating anything. Putting them on
    #     the nightly loop would spend real time producing a number nobody
    #     reads on most days, and the number they produce only moves as the
    #     season adds games.
    #
    #     NOT the same as an unwired gate. What the loop DOES run nightly is
    #     scripts/fit_card_calibration.py, which is the part the product
    #     depends on -- if that ever goes orphan the card silently publishes
    #     raw, overconfident probabilities, and the audit must catch it.
    "backtest_card.py",
    "backtest_card_rule.py",

    # --- PRE-SPECIFIED MODEL TESTS. Each fixes a window and an adoption
    #     criterion in code above the measurement, runs read-only over a
    #     season, and adopts nothing. Running one nightly would spend
    #     minutes reproducing a number that only moves as games accumulate,
    #     and worse, it would invite reading the answer repeatedly until it
    #     said something -- which is the failure these files exist to
    #     prevent. They are run once, deliberately, by a person asking.
    "test_run_dispersion.py",
    "test_bullpen_rate.py",
    "test_park_factor.py",
    "probe_market_consistency.py",
    "probe_run_dispersion.py",
    "probe_first_five.py",
    "probe_model_ablation.py",
    "test_run_dispersion_2025.py",
    "test_calibration_still_helps.py",
    "test_drop_hurting_components.py",
    "backtest_player_props.py",
    "test_tier_ladder.py",

    # --- read-only analyses an operator runs while asking something. They
    #     write no state and gate nothing.
    "derive_mechanism_baselines.py",
    "engine_equivalence.py",
    "f5_tie_audit.py",
    "factory_overlap_report.py",
    "measure_market_derived_calibration.py",
    "time_tests.py",
    "totals_coverage_audit.py",
    "totals_m2_coverage.py",
    "totals_population_audit.py",
    "totals_reschedule_audit.py",
}


def view_modules():
    """Browser modules whose renderers NOTHING imports.

    Checked against every other module, not just main.js: a component is
    reachable if any routed view composes it (games.js mounts
    renderFeaturedBet, today.js mounts renderRecordStrip). Only main.js would
    flag every legitimate sub-component, and again, false alarms are how a
    checker stops being read.
    """
    others = {p.stem: _read(p) for p in sorted(WEB_JS.glob("*.js"))}
    orphans = []
    for name, text in others.items():
        renderers = [e for e in
                     re.findall(r"export\s+(?:async\s+)?function\s+(\w+)",
                                text)
                     if e.startswith("render")]
        if not renderers:
            continue
        # A call, not a mention: `import { renderX }` alone is not a use, and
        # a docstring naming it certainly is not.
        reachable = False
        for other, blob in others.items():
            if other == name:
                continue
            code = "\n".join(l for l in blob.splitlines()
                             if not l.lstrip().startswith(("*", "//", "/*")))
            if any(re.search(r"\b" + r + r"\s*\(", code) for r in renderers):
                reachable = True
                break
        if not reachable:
            orphans.append((name, renderers))
    return orphans


def main():
    findings = []

    commands = cli_commands()
    called = cli_callers()
    orphan_cmds = sorted(
        c for c in commands
        if c not in called
        and not any(c == d or c.startswith(d) for d in DECLARED_MANUAL))
    if orphan_cmds:
        findings.append(
            f"{len(orphan_cmds)} CLI command(s) that no script or workflow "
            f"ever invokes -- they run only if a person remembers:\n    "
            + "\n    ".join(orphan_cmds))

    routes = http_routes()
    http_called = http_callers()
    orphan_routes = sorted(
        f"{m} {p}" for m, p in routes if not _route_is_called(p, http_called))
    if orphan_routes:
        findings.append(
            f"{len(orphan_routes)} HTTP route(s) no client calls -- built "
            f"server-side capability with no way to reach it (this is what "
            f"POST /billing/checkout was):\n    "
            + "\n    ".join(orphan_routes))

    stray_scripts = orphan_scripts()
    if stray_scripts:
        findings.append(
            f"{len(stray_scripts)} script(s) under scripts/ that no shell "
            f"script or workflow executes -- this is what hid "
            f"prereg_clv_feature_test.py:\n    "
            + "\n    ".join(stray_scripts))

    orphan_views = view_modules()
    if orphan_views:
        findings.append(
            f"{len(orphan_views)} view module(s) main.js never routes to:\n    "
            + "\n    ".join(f"{n}: {', '.join(r)}" for n, r in orphan_views))

    print(f"entry points walked: {len(ENTRY_SHELL)} shell scripts, "
          f"{len(routes)} HTTP routes, {len(commands)} CLI commands")
    print(f"  workflows: {WORKFLOW_SOURCE_NOTE}")
    if not findings:
        print("\nreachability audit: clean -- everything is reachable from "
              "something that runs")
        return 0
    for f in findings:
        print(f"\nORPHAN: {f}")
    print(f"\n{len(findings)} orphan class(es). Each is code that works and "
          f"that nothing calls. Declare it in DECLARED_MANUAL with a reason, "
          f"or wire it to something that runs.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
