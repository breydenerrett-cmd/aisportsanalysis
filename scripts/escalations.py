#!/usr/bin/env python3
"""Classify a daily-loop run's `ESCALATE:` lines against the acknowledged
escalations ledger (`docs/ESCALATIONS.md`), so the scheduled job fails only
on an escalation nobody has seen before.

THE PROBLEM THIS EXISTS TO FIX
-------------------------------
`.github/workflows/daily-loop.yml`'s final step used to be a bare
`grep -q "^ESCALATE:" /tmp/daily_run.out`: any ESCALATE line at all failed
the job. Two of this repo's audits (`scripts/calibration_drift_audit.py`,
`scripts/research_readiness.py`) escalate on every single run right now, for
reasons that are known, acknowledged, and not fixable today (see
`docs/ESCALATIONS.md` for both). A job that is red every morning for the
same two known reasons carries no information -- a genuinely NEW escalation
is exactly as invisible in that stream as the two standing ones.

Nothing here weakens a check: every audit keeps printing its `ESCALATE:`
line exactly as before, every run it is still true. Only the job's verdict
changes -- and only for a line that matches an entry someone already
acknowledged in the ledger.

USAGE
-----
    python3 scripts/escalations.py --check /tmp/daily_run.out
        Reads the ledger, reads every `ESCALATE:` line out of the given
        file, prints each one labelled KNOWN or NEW, then a one-line
        `known=N new=M` summary. Exits 1 only if new > 0.

    python3 scripts/escalations.py --list
        Prints the ledger's rows (id, status, first_seen, pattern) for a
        human to sanity-check what's currently acknowledged.

No network access, stdlib only. Tolerant of a missing ledger: with no
`docs/ESCALATIONS.md` to read, `--check` classifies every ESCALATE line NEW
-- the same behaviour the old bare grep had, so deleting the ledger (or not
having created it yet) cannot silently swallow an escalation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO / "docs" / "ESCALATIONS.md"

# Rows in either state still page nobody -- both are acknowledgements that a
# human has already seen this exact line. `fixed`/`retired` rows are
# deliberately excluded: once a fix lands, the line should stop appearing at
# all, and if it ever recurs it is reported NEW rather than re-absorbed
# forever by a row nobody is watching anymore.
ACTIVE_STATUSES = {"open", "fix in progress"}

_SEPARATOR_CELL = re.compile(r":?-{3,}:?")


class LedgerEntry:
    __slots__ = ("id", "first_seen", "pattern", "acknowledged_by",
                 "acknowledged_on", "status", "why_open")

    def __init__(self, id, first_seen, pattern, acknowledged_by,
                 acknowledged_on, status, why_open):
        self.id = id
        self.first_seen = first_seen
        self.pattern = pattern
        self.acknowledged_by = acknowledged_by
        self.acknowledged_on = acknowledged_on
        self.status = status
        self.why_open = why_open


def parse_ledger(path: Path) -> list[LedgerEntry]:
    """Parse the pipe-delimited markdown table in docs/ESCALATIONS.md.

    Tolerant of a missing file (returns []) and of any prose around the
    table (only lines starting with `|` are considered). The first pipe row
    is the header, the next is the `|---|---|...` separator, everything
    after is data -- rows with fewer than 7 cells or an empty pattern are
    skipped rather than raising, so a hand-edited ledger with a stray line
    degrades to "that row is ignored", not "the whole check crashes".
    """
    if not path.is_file():
        return []

    entries: list[LedgerEntry] = []
    header_seen = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not header_seen:
            header_seen = True
            continue
        if all(_SEPARATOR_CELL.fullmatch(c) for c in cells):
            continue  # the |---|---|...| separator row
        if len(cells) < 7:
            continue
        id_, first_seen, pattern, ack_by, ack_on, status, why_open = cells[:7]
        if not pattern:
            continue
        entries.append(LedgerEntry(id_, first_seen, pattern, ack_by, ack_on,
                                    status.strip().lower(), why_open))
    return entries


def extract_escalate_lines(text: str) -> list[str]:
    """Every line starting `ESCALATE:` -- matches the same anchor the old
    `grep -q "^ESCALATE:"` used, so nothing that used to fail the job is
    now invisible to this one."""
    return [line for line in text.splitlines() if line.startswith("ESCALATE:")]


def classify(lines: list[str],
             ledger: list[LedgerEntry]) -> list[tuple[str, str]]:
    """Returns [(line, "KNOWN"|"NEW"), ...] in input order. A line is KNOWN
    if it contains the `pattern` substring of at least one active
    (open / fix in progress) ledger row; otherwise NEW."""
    active_patterns = [e.pattern for e in ledger
                        if e.status in ACTIVE_STATUSES and e.pattern]
    results = []
    for line in lines:
        is_known = any(pattern in line for pattern in active_patterns)
        results.append((line, "KNOWN" if is_known else "NEW"))
    return results


def cmd_check(run_output_file: str, ledger_path: Path) -> int:
    out_path = Path(run_output_file)
    if not out_path.is_file():
        print(f"escalations: no such run output file: {run_output_file}")
        return 1

    ledger = parse_ledger(ledger_path)
    text = out_path.read_text(encoding="utf-8", errors="replace")
    lines = extract_escalate_lines(text)
    results = classify(lines, ledger)

    if not results:
        print("no ESCALATE lines -- clean run")
        print("known=0 new=0")
        return 0

    for line, label in results:
        print(f"{label}: {line}")

    known = sum(1 for _, label in results if label == "KNOWN")
    new = sum(1 for _, label in results if label == "NEW")
    print(f"known={known} new={new}")
    return 1 if new else 0


def cmd_list(ledger_path: Path) -> int:
    ledger = parse_ledger(ledger_path)
    if not ledger:
        print(f"escalations: no ledger entries found at {ledger_path}")
        return 0
    for entry in ledger:
        print(f"{entry.id}\t{entry.status}\t{entry.first_seen}\t{entry.pattern}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify daily-loop ESCALATE lines against "
                     "docs/ESCALATIONS.md")
    parser.add_argument(
        "--check", metavar="RUN_OUTPUT_FILE",
        help="classify every ESCALATE: line in this file; exit 1 iff any "
             "is NEW")
    parser.add_argument(
        "--list", action="store_true",
        help="print the ledger's acknowledged entries and exit 0")
    parser.add_argument(
        "--ledger", default=str(DEFAULT_LEDGER),
        help="path to the ledger (default: docs/ESCALATIONS.md)")
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    if args.list:
        return cmd_list(ledger_path)
    if args.check:
        return cmd_check(args.check, ledger_path)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
