#!/usr/bin/env python3
"""Minimal reproduction: `code_fingerprint` depends on the checkout, not
only on the content.

CAUSE. `src.appstate.card_ledger.code_fingerprint` hashes each registered
file's RAW bytes (`Path.read_bytes()`). Line endings are bytes. With
`core.autocrlf=true`, whether a given file sits in the working tree as CRLF
or LF depends on how it entered the index, so two checkouts of the SAME
commit can hash differently. Registration 11.2 treats a fingerprint change
as a model restart that restarts the counted sample, and section 16 records
one value per list -- so this makes the guard fire on a checkout difference
and, in principle, lets a real change hide behind an offsetting one.

This script only reports. It does not reset, recompute or overwrite the
values recorded in section 16, and it changes no file. Fixing the hash
function would itself change a fingerprinted file and restart the sample,
which is the owner's decision, not this script's.

    python scripts/fingerprint_diagnostic.py
    python scripts/fingerprint_diagnostic.py --json

Exit code 1 when a recorded value cannot be reproduced under any convention
tried, 0 otherwise -- matching the other scripts/*_audit.py conventions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.appstate import card_ledger  # noqa: E402

# Section 16, verbatim, at the registration commit 859176ba. PRESERVED, not
# updated: they are the record of what was registered, and this script
# exists to explain why they no longer reproduce, not to make them agree.
RECORDED = {
    "code_fingerprint": (
        "8a641de0ee76091972d482cc316b47924a474e063334d67056333513ee4d2061"),
    "v1_code_fingerprint": (
        "10f5cac7191ff23d0afcebc1f3566c8e747b9e4286a1eacbbfd8be09bf1c92ee"),
}
REGISTRATION_COMMIT = "859176ba"


def _hash(paths, *, convert) -> str:
    """`code_fingerprint`'s exact framing, with the bytes normalised first.

    convert=None  -- the working tree's own bytes (what the live code does)
    convert="lf"  -- every CRLF collapsed to LF
    convert="crlf"-- every LF expanded to CRLF
    """
    hasher = hashlib.sha256()
    for rel in paths:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        try:
            with open(rel, "rb") as fh:
                data = fh.read()
        except OSError:
            hasher.update(b"<absent>")
            hasher.update(b"\0")
            continue
        if convert == "lf":
            data = data.replace(b"\r\n", b"\n")
        elif convert == "crlf":
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest()


def report(name, paths, recorded):
    rows = []
    for rel in paths:
        try:
            with open(rel, "rb") as fh:
                data = fh.read()
        except OSError:
            rows.append({"path": rel, "present": False})
            continue
        crlf = data.count(b"\r\n")
        lf_only = data.count(b"\n") - crlf
        rows.append({
            "path": rel,
            "present": True,
            "bytes": len(data),
            "crlf_lines": crlf,
            "lf_only_lines": lf_only,
            "line_endings": ("CRLF" if crlf and not lf_only
                             else "LF" if lf_only and not crlf
                             else "MIXED" if crlf or lf_only else "NONE"),
            "sha256_worktree": hashlib.sha256(data).hexdigest(),
            "sha256_lf": hashlib.sha256(
                data.replace(b"\r\n", b"\n")).hexdigest(),
        })

    values = {
        "as_checked_out": _hash(paths, convert=None),
        "all_lf": _hash(paths, convert="lf"),
        "all_crlf": _hash(paths, convert="crlf"),
    }
    matches = [k for k, v in values.items() if v == recorded]
    return {
        "name": name,
        "files": rows,
        "fingerprints": values,
        "recorded_in_section_16": recorded,
        "recorded_reproduced_by": matches,
        "live_value_matches_record": values["as_checked_out"] == recorded,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = [
        report("code_fingerprint (V2, registration 11.2)",
               card_ledger.V2_FINGERPRINT_FILES,
               RECORDED["code_fingerprint"]),
        report("v1_code_fingerprint (section 10)",
               card_ledger.V1_FINGERPRINT_FILES,
               RECORDED["v1_code_fingerprint"]),
    ]

    findings = []
    for res in results:
        if res["live_value_matches_record"]:
            continue
        if res["recorded_reproduced_by"]:
            findings.append((
                "ESCALATE",
                f"{res['name']}: this checkout computes "
                f"{res['fingerprints']['as_checked_out'][:16]}..., not the "
                f"recorded {res['recorded_in_section_16'][:16]}..., but the "
                f"recorded value IS reproduced by "
                f"{', '.join(res['recorded_reproduced_by'])} -- the content "
                "is unchanged and the difference is line endings alone"))
        else:
            findings.append((
                "ESCALATE",
                f"{res['name']}: the recorded value is not reproduced by "
                "the working tree under ANY line-ending convention. Either a "
                "registered file's content changed, or the recorded value "
                f"was computed from a state other than {REGISTRATION_COMMIT}. "
                "See docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md E4"))

    if args.json:
        print(json.dumps({"results": results,
                          "findings": [{"severity": s, "message": m}
                                       for s, m in findings]}, indent=2))
    else:
        for res in results:
            print(f"\n{res['name']}")
            print(f"{'file':<46}{'endings':>8}{'bytes':>10}")
            for row in res["files"]:
                if not row["present"]:
                    print(f"{row['path']:<46}{'ABSENT':>8}")
                    continue
                print(f"{row['path']:<46}{row['line_endings']:>8}"
                      f"{row['bytes']:>10}")
            for label, value in res["fingerprints"].items():
                mark = "  == section 16" if value == \
                    res["recorded_in_section_16"] else ""
                print(f"  {label:<16} {value}{mark}")
            print(f"  {'section 16':<16} {res['recorded_in_section_16']}")
        print()
        for severity, message in findings:
            print(f"{severity}: {message}")
        if not findings:
            print("OK: both recorded fingerprints reproduce from this "
                  "checkout as-is.")

    unreproducible = [r for r in results
                      if not r["recorded_reproduced_by"]
                      and not r["live_value_matches_record"]]
    return 1 if unreproducible else 0


if __name__ == "__main__":
    raise SystemExit(main())
