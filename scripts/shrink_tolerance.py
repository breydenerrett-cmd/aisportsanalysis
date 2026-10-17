"""Decide whether a staged JSON store that got a few bytes smaller is a real
shrink or only a re-serialisation. Called by scripts/lib_shrink_guard.sh.

WHY THIS EXISTS (2026-10-16)
----------------------------
Every daily-loop run since 2026-10-07 ended
`ESCALATE: data/historical/arsenals/<file>.json would shrink N -> N-k bytes,
refusing` with k between 1 and 4, then exit 1. The guard
(guard_staged_no_shrink) compares a non-jsonl store by BYTE SIZE against HEAD,
which is exactly right for what it was built for (a stale CI cache restore
unpacking an old copy over a fresh one: 4,993 rows became 119). But the
arsenals files are rewritten by the loop's own refresh, and a rewrite that
spells a float differently (0.30 against 0.3), or drops a trailing newline,
changes the byte count by a handful with every record intact. The guard read
that as a shrink, restored the file, and made the whole run red every day for
nine days, so a real alarm would have been indistinguishable from the noise.

THE RULE
--------
A byte shrink is TOLERATED only when BOTH hold:
  * the staged file is smaller by LESS THAN 0.1% of the HEAD file
    (MAX_SHRINK_FRACTION), and
  * the number of records is UNCHANGED, counted the same way on both sides.
Anything else (one record fewer, 0.1% or more fewer bytes, a file that does not
parse, a file whose records cannot be counted) is a real shrink or an unknown
one and the guard refuses exactly as before. "Cannot tell" refuses: the guard's
whole job is to fail toward keeping data.

RECORDS are counted without knowing the store's schema: a top-level JSON list
is its length; a top-level object is the total length of its list-valued
fields (the arsenals files are `{"as_of", "min_pitches", "rows": [...],
"season", "side"}`, so that is `rows`). An object with no list at all has no
countable records and is never tolerated.

USAGE
-----
    python3 scripts/shrink_tolerance.py HEAD_BLOB STAGED_BLOB

Both arguments are git blob ids, read with `git cat-file blob` in the current
repository. Prints ONE line saying both byte counts and both record counts and
exits 0 when the shrink is tolerated, 1 when it is not (or cannot be judged).
Stdlib only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Optional, Sequence

# 0.1% of the HEAD file. The observed re-serialisation shrinks were 1 to 4
# bytes on files of tens of kilobytes (about 0.01% or less); a lost record on a
# store this size is far over this, and records are also required to match, so
# this bound only has to be tight enough that "unchanged count" cannot hide a
# truncated value.
MAX_SHRINK_FRACTION = 0.001


def count_records(obj) -> Optional[int]:
    """How many records a parsed JSON store holds, or None if it cannot be
    said. See the module docstring for the definition."""
    if isinstance(obj, list):
        return len(obj)
    if isinstance(obj, dict):
        lists = [v for v in obj.values() if isinstance(v, list)]
        if not lists:
            return None
        return sum(len(v) for v in lists)
    return None


def judge(head_bytes: bytes, staged_bytes: bytes) -> tuple:
    """(tolerated, one_line_message). Pure: takes the two files' bytes."""
    head_n, staged_n = len(head_bytes), len(staged_bytes)
    try:
        head_records = count_records(json.loads(head_bytes.decode("utf-8-sig")))
        staged_records = count_records(json.loads(staged_bytes.decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError):
        head_records = staged_records = None
    pct = ((head_n - staged_n) / head_n * 100.0) if head_n else 0.0
    facts = (f"bytes {head_n} -> {staged_n} ({-pct:+.4f}%), "
             f"records {head_records} -> {staged_records}")
    if staged_n >= head_n:
        return True, f"not smaller: {facts}"
    if head_records is None or staged_records is None:
        return False, f"records cannot be counted: {facts}"
    if staged_records != head_records:
        return False, f"records changed: {facts}"
    if (head_n - staged_n) >= head_n * MAX_SHRINK_FRACTION:
        return False, f"shrink is 0.1% or more of the file: {facts}"
    return True, f"re-serialisation only, same record count: {facts}"


def _blob(blob_id: str) -> bytes:
    done = subprocess.run(["git", "cat-file", "blob", blob_id],
                          capture_output=True, check=True)
    return done.stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: shrink_tolerance.py HEAD_BLOB STAGED_BLOB")
        return 1
    try:
        head_bytes, staged_bytes = _blob(args[0]), _blob(args[1])
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"cannot read the blobs: {type(exc).__name__}")
        return 1
    tolerated, message = judge(head_bytes, staged_bytes)
    print(message)
    return 0 if tolerated else 1


if __name__ == "__main__":
    raise SystemExit(main())
