"""Cold-storage rotation for append-only JSONL forward-capture stores.

THE INCIDENT (2026-09-21, live production)
--------------------------------------------
`data/processed/odds_multibook.jsonl` is a git-tracked, append-only forward
capture (src/pipeline/snapshots.py) that grew to 100.08 MB and GitHub started
rejecting every push from the capture runners:

    remote: error: File data/processed/odds_multibook.jsonl is 100.08 MB;
    this exceeds GitHub's file size limit of 100.00 MB
    ESCALATE: push failed after retries -- commit is local only, needs
    manual push

(scripts/capture_slot.sh's own ESCALATE line, ~line 709.) Growth is ~10
MB/day; every 13-minute capture slot since ~14:30Z that day was captured
locally and then lost when its ephemeral runner was destroyed, because the
commit that held it could never be pushed. `derivative_markets.jsonl` (63
MB), `evidence/decisions_v2.jsonl` (57 MB) and `batter_props.jsonl` (40 MB)
are growing toward the same wall.

THE FIX: A HOT FILE PLUS COLD, IMMUTABLE SEGMENTS
----------------------------------------------------
A store no longer has to be one file. It is a HOT file (small, the tail of
recent history, the only thing a writer ever appends to) plus zero or more
gzip-compressed SEGMENT files under `<store>/archive/<stem>/` holding older
rows in original order. The LOGICAL store is the concatenation of every
segment, oldest first, followed by the hot file -- `iter_lines` below is the
only thing that needs to know both halves exist; every reader that used to
open the store and read every line calls `iter_lines` instead and sees
EXACTLY the same rows in EXACTLY the same order it always did (see this
module's docstring section "WHAT COUNTS AS CORRECT").

Segments are named `NNNN_<first-date>_<last-date>.jsonl.gz`: a zero-padded
four-digit sequence number so that SORTING THE FILENAMES reproduces creation
order, which is also original line order (rotation only ever archives a
PREFIX of the hot file -- see `rotate`). Once written a segment is never
edited, appended to, or reordered; `rotate` only ever adds a new one with the
next sequence number.

WHAT COUNTS AS CORRECT
------------------------
`concat(decompress(segment) for segment in segments) + hot_file_bytes` must
be BYTE-IDENTICAL to what the hot file's bytes were before the store was
ever rotated -- not merely "the same JSON rows", byte-identical, because
some reader somewhere may hash or diff raw lines. `rotate` proves this for
every rotation it performs (decompress the segment it just wrote, concatenate
it with the new hot file, sha256 that against a sha256 of the OLD hot file,
BEFORE either new file is made durable) and refuses -- raising, touching
nothing -- if the proof fails. This is the same "never trust the write,
verify it" discipline `scripts/archive_historical.sh` already uses for the
2023-25 paid odds archive (gzip -n + a decompressed-sha256 sidecar).

WHY THE PREFIX RULE, NOT "everything older than N days"
------------------------------------------------------------
The hot file is one JSON object per line, append-only, and (per
src/pipeline/snapshots.py `append`) is never reordered after being written:
row N's `observed_utc` is never later than row N+1's. So "the maximal
PREFIX of complete lines whose stamp date is older than the cutoff" and
"every row older than the cutoff" describe the same set of lines in the
store as it is actually written -- but the PREFIX version is what makes
rotation safe to implement as one linear scan with no buffering of the
whole file's row set, and it is what makes "stop at the first line that
doesn't qualify" the correct, conservative behaviour rather than a
shortcut: a line this scan cannot confidently classify (unparseable JSON,
missing/malformed stamp field, or the ROW ITSELF still mid-write with no
trailing newline) must never be silently reordered past, so scanning stops
there and everything from that line onward -- even a later line that WOULD
have qualified -- stays in the hot file until the next rotation.

THE GUARD THAT LOOKED LIKE A GUARANTEE, AND ISN'T (2026-09-21 review)
------------------------------------------------------------------------
An earlier draft of this docstring claimed the writer "guards against" an
unparseable line ever reaching the hot file at all. That is backwards.
`snapshots.append`'s own ragged-fragment repair (`_ends_ragged`) does the
opposite on purpose: when a run was killed mid-write, the NEXT append writes
a bare `"\n"` first, turning the torn fragment into a COMPLETE line that is
still not valid JSON. That is the right call for `append` -- it isolates the
damage to the one interrupted row instead of merging two observations into
one unreadable line -- but it means a genuinely unparseable *complete* line
is not a hypothetical here, it is exactly what a killed capture run leaves
behind. Once such a line sits anywhere before the cutoff in the hot file,
this scan halts there on EVERY future rotation (the scan always restarts
from byte 0), and nothing after it is ever archived until that one line is
handled by hand. `_cmd_store_rotate` prints this reason as a WARN, not a
silent no-op, specifically so it does not sit invisible until
`guard_staged_size`'s 95 MiB ESCALATE is the only thing left to catch it.

NO CLOCK INSIDE
-----------------
`rotate`'s `now` is a parameter, never `datetime.now()` read internally --
same discipline as every other forward-capture module in this project
(src/pipeline/snapshots.py, src/capture/cadence.py): a test asserts an exact
cutoff date instead of racing the wall clock, and nothing here can silently
drift onto a different notion of "today" than its caller's. `now` is always
normalised to UTC before its `.date()` is taken (`now.astimezone(timezone.
utc)`) -- stamps are written in UTC (`+00:00`, per every writer in this
project) and the cutoff must be computed in that same calendar, not in
whatever offset happened to be attached to the caller's `now`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator


class StoreArchiveError(RuntimeError):
    """Raised when a rotation's own byte-identity proof fails.

    Always raised BEFORE any durable file is written or replaced -- see the
    module docstring's "WHAT COUNTS AS CORRECT". The caller's hot file and
    archive directory are exactly as they were before `rotate` was called.
    """


# Four-digit sequence prefix (name order == creation order == original line
# order, per the module docstring) then the first and last archived line's
# own stamp date, both YYYY-MM-DD. The date pair is metadata for a human
# skimming the archive directory -- nothing here parses it back out.
_SEGMENT_NAME_RE = re.compile(
    r"^(?P<seq>\d{4})_(?P<first>\d{4}-\d{2}-\d{2})_(?P<last>\d{4}-\d{2}-\d{2})\.jsonl\.gz$"
)


def _coerce_date(value: str | date | None) -> date | None:
    """`since`/`until` accept either a `date` or a YYYY-MM-DD string --
    every caller in this codebase already carries dates as plain ISO
    strings (route params, ledger fields), so requiring a `date` object
    would just push a `date.fromisoformat` onto every call site."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def segment_dir(path: Path | str) -> Path:
    """Where `path`'s archive segments live: `<parent>/archive/<stem>/`.

    `path.stem` strips exactly one suffix (`odds_multibook.jsonl` ->
    `odds_multibook`), which is what keeps this a per-store subdirectory
    rather than one shared archive folder every rotatable store would dump
    into.
    """
    path = Path(path)
    return path.parent / "archive" / path.stem


def segments(path: Path | str) -> list[Path]:
    """Every archive segment for `path`, oldest first.

    Sorting by filename is sorting by creation order: the sequence prefix is
    zero-padded to four digits specifically so string sort and numeric sort
    agree (module docstring). A missing archive directory is not an error --
    it means this store has never been rotated -- and returns `[]`, which is
    what makes `iter_lines` on such a path fall through to a plain read of
    the hot file alone.
    """
    directory = segment_dir(path)
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and _SEGMENT_NAME_RE.match(p.name)
    )


def exists(path: Path | str) -> bool:
    """True when there is anything at all to read: a hot file, archive
    segments, or both.

    A store that has been rotated hard enough to leave nothing newer than
    its own keep-window can have an EMPTY or absent hot file while still
    holding real history in `archive/` -- `Path(path).exists()` alone would
    misreport that store as gone. Every reader that used to gate on
    `path.exists()` before deciding a store has "no data" must call this
    instead (see the readers this incident fixed, e.g. src/pipeline/health.py
    `_odds_section`'s `store_present`).
    """
    path = Path(path)
    return path.exists() or bool(segments(path))


def iter_lines(path: Path | str, *, since: str | date | None = None) -> Iterator[str]:
    """Every text line of the LOGICAL store, in original order: every
    archive segment oldest-first, then the (possibly empty, possibly
    absent) hot file.

    `since` (added 2026-09-21, the /odds and /games latency fix): an
    optional YYYY-MM-DD date (str or `date`). A segment is skipped
    ENTIRELY, without ever being opened or decompressed, when its own
    filename says its LAST archived row is dated strictly before `since` --
    the segment name already carries that fact (module docstring: `NNNN_
    <first-date>_<last-date>.jsonl.gz`, and `rotate`'s stamp field is
    `observed_utc`, so this compares against observed dates, not commence
    dates). The hot file is always read in full: it carries no per-segment
    date metadata cheap enough to check without opening it, and it is the
    small tail of the store by construction. `since=None` (the default)
    changes nothing -- every segment is opened exactly as before, which is
    what keeps a caller that never passes `since` reading the identical
    bytes it always did.

    This is a coarse, whole-segment filter, not a row filter: a segment
    that overlaps `since` at all (its `last` date is on or after `since`)
    is still opened and fully yielded, so per-row filtering is still the
    caller's job -- see src.pipeline.snapshots.read's own `since`/`until`.

    Yields str with the line's own trailing newline kept (or omitted for a
    final, unterminated line) exactly as it existed in the file the segment
    was cut from -- callers that `.strip()` before parsing (every JSONL
    reader in this project does) are unaffected either way, and callers that
    care about exact bytes (this module's own verification, tests asserting
    byte-identity) get them.

    Binary mode throughout, decoded per line, deliberately: Python's
    universal-newline text mode can silently rewrite line endings on some
    platforms, and this project's stores are written LF-only by
    `src.pipeline.snapshots.append` (`handle.write(... + "\\n")` in text
    mode on POSIX runners) -- reading them back through the same
    line-splitting rule binary mode uses (split on b"\\n", keep it) is what
    makes "no archive dir -> read exactly like the old plain read" true byte
    for byte, on every platform this ever runs on, Windows dev boxes
    included.

    A store with no archive directory yields exactly what a plain
    `path.open().readlines()`-style read always did -- the segments loop
    below is simply empty, so this is provably a no-op change for every
    store nobody has rotated yet.

    SINGLE-WRITER, QUIESCENT-READER CONTRACT (2026-09-21 review): `segments`
    is listed ONCE, when this generator starts, then the hot file is opened
    after every segment has been fully yielded. A `rotate` that finishes
    WHILE a caller is mid-iteration here can add a segment this call will
    never see (it already passed the `segments()` snapshot) and shrink the
    hot file out from under the `hot.open()` below -- this generator does
    not re-list or re-stat mid-iteration to detect that. This project's
    capture and rotation jobs are safe by construction: every writer to a
    given store's hot file and every `rotate` of it run serially under one
    `GIT_LOCK` / `concurrency: group: forward-capture` (scripts/
    capture_slot.sh), so there is never a concurrent rotation for a reader
    to race in production. A caller running outside that serialisation
    (a long-lived process polling this store while a rotation can happen on
    the same checkout) must not assume the rows it sees mid-iteration are
    the complete, current logical store.
    """
    since_date = _coerce_date(since)
    for segment in segments(path):
        if since_date is not None:
            match = _SEGMENT_NAME_RE.match(segment.name)
            if match and date.fromisoformat(match["last"]) < since_date:
                continue
        with gzip.open(segment, "rb") as handle:
            for raw_line in handle:
                yield raw_line.decode("utf-8")
    hot = Path(path)
    if hot.exists():
        with hot.open("rb") as handle:
            for raw_line in handle:
                yield raw_line.decode("utf-8")


def _parse_stamp_date(value, stamp_field: str) -> date | None:
    """The calendar date (UTC, as-written) a row's `stamp_field` names, or
    None when the row does not straightforwardly say. Never raises: an
    unparseable stamp is a signal to STOP archiving (module docstring), not
    an error to propagate out of a linear scan."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class _UndatedRow:
    """Sentinel a `stamp_of` callable returns (the default `stamp_field`
    path never produces this -- only `date` or `None`) for a row that is
    legitimately archivable but names no calendar date of its own. The
    motivating case is a hash chain's genesis row (`src.ledger.chain`):
    it must be eligible to move into a segment along with the dated rows
    around it, but it has no `observed_utc`-shaped field to name a segment
    after.

    Deliberately NOT `None` -- `None` already means "stop the archivable
    prefix scan here, this row cannot be confidently classified" (module
    docstring). UNDATED is the opposite: never a reason to stop, only a
    reason not to update the segment's date-range name. A dedicated class
    (one module-level instance, below) rather than a bare `object()` so a
    test failure or debugger repr reads as `UNDATED`, not
    `<object object at 0x...>`.
    """

    def __repr__(self) -> str:
        return "UNDATED"


UNDATED = _UndatedRow()


def _stamp_getter(stamp_field: str, stamp_of):
    """The per-row date function `rotate`'s scan actually calls.

    `stamp_of`, verbatim, when given -- it REPLACES `stamp_field` entirely
    (rotate's own docstring/parameter list). Otherwise a closure over
    `_parse_stamp_date`/`stamp_field` that reproduces the pre-`stamp_of`
    behaviour exactly, which is what keeps every existing caller --
    `odds_multibook`, which never passes `stamp_of` -- byte-for-byte
    unaffected by this parameter's addition.
    """
    if stamp_of is not None:
        return stamp_of

    def _default(row: dict) -> date | None:
        return _parse_stamp_date(row.get(stamp_field), stamp_field)

    return _default


def rotate(path: Path | str, *, keep_days: int, now: datetime,
           threshold_bytes: int, stamp_field: str = "observed_utc",
           stamp_of: Callable[[dict], date | None | UNDATED] | None = None,
           min_hot_rows: int = 0) -> dict:
    """Move the old prefix of `path`'s hot file into a new cold segment.

    `stamp_of` (added for `decisions_v2`, a hash-chained ledger whose
    `recorded_utc` is NOT monotone in file order): when given, REPLACES
    `stamp_field` as the per-row date function -- it receives the parsed
    row dict and returns a `date`, `None` (unparseable/missing -- stop the
    archivable prefix here, same as the default path), or `UNDATED` (this
    module's sentinel: archivable, but names no date of its own -- a hash
    chain's genesis row is the motivating case). Segment filenames are named
    from the MIN and MAX of the DATED rows actually archived, not from the
    first/last row -- identical to "first row's date, last row's date" when
    stamps are monotone (every existing caller, e.g. odds_multibook) but
    correct when they are not. `stamp_of=None` (the default) leaves every
    existing caller's behaviour byte-for-byte unchanged.

    `min_hot_rows` (default 0, unchanged existing behaviour): never archive
    the last `min_hot_rows` COMPLETE lines of the hot file, however far the
    cutoff-date scan would otherwise reach -- a floor under the prefix, on
    top of (not instead of) the existing cutoff-date ceiling. `decisions_v2`
    passes 1 so the hot file always holds at least one row for `append()`'s
    `last_hash()` to chain the next row to without ever touching the
    archive.

    If the capped prefix (after both the cutoff-date ceiling and the
    `min_hot_rows` floor) contains no dated row at all -- e.g. it is a lone
    UNDATED genesis row -- `rotate` is a no-op: a segment filename requires
    at least one dated row to name its range after, so this never invents
    one.

    No-op (returns `{"rotated": False, "reason": ...}`, touches nothing) when
    the hot file is absent, or smaller than `threshold_bytes`, or when no
    leading run of complete, parseable, pre-cutoff lines exists to archive.

    Otherwise: `cutoff = now.date() - keep_days` days. Scans the hot file
    from the start, archiving the MAXIMAL PREFIX of complete lines
    (terminated by `\\n`) whose `stamp_field` date is strictly before
    `cutoff`, stopping at the first line that is incomplete (no trailing
    newline -- an interrupted append, per src.pipeline.snapshots.append's
    own `_ends_ragged` contract), unparseable, or dated on/after `cutoff`.
    Lines are never reordered and the stopping line is never touched.

    The archived prefix is written as one gzip-deterministic segment
    (`mtime=0`, no embedded filename, so re-rotating identical input bytes
    on the SAME zlib build reproduces an identical segment file -- gzip's
    byte layout is not guaranteed across different zlib builds, e.g. a
    zlib-ng vs. stock zlib Python, so this determinism is a within-build
    nicety, not a cross-machine guarantee) to a temp file; before EITHER the
    segment or the hot file is made durable, the temp segment is decompressed
    and concatenated with the new (remaining) hot bytes, sha256'd, and
    compared against a sha256 of the ORIGINAL hot file. Any mismatch raises
    `StoreArchiveError` and leaves both the archive directory and the hot
    file exactly as they were -- see the module docstring's "WHAT COUNTS AS
    CORRECT" -- and that proof is what correctness actually rests on: it is
    over DECOMPRESSED content, so it holds regardless of which zlib build
    wrote the gzip bytes. Only after that proof succeeds does the segment
    get its real name (`os.replace`) and the hot file get rewritten to just
    the remaining suffix (temp file + `os.replace`). If the hot file's own
    replace fails after the segment has already been made durable, the
    segment is unlinked before the error propagates -- a partial rotation
    must never leave the logical store holding the archived prefix twice
    (2026-09-21 review: `os.replace` on Windows raises `PermissionError` when
    another process still has the hot file open, e.g. a `--reload` dev
    server or Defender scanning a just-written file, and ENOSPC/EIO can hit
    a CI runner the same way).

    Refuses (raises before anything is read) if `keep_days` is negative, and
    if the hot file changed size or mtime between when this scan read it and
    when it is about to be replaced -- a concurrent writer landing mid-
    rotation must never have its row silently discarded by the replace.

    `now` is injected (module docstring: no clock inside) and normalised to
    UTC before its `.date()` is taken.
    """
    if keep_days < 0:
        # A negative keep-window has no sane meaning ("keep -5 days") and
        # the arithmetic below does not reject it on its own: it would
        # compute a cutoff AFTER `now` and archive rows that were just
        # written, including today's. Caught here so the CLI's `--keep-days
        # -5` (2026-09-21 review) fails clean instead of silently emptying
        # the hot file.
        raise ValueError(f"keep_days must be >= 0, got {keep_days}")

    path = Path(path)
    report: dict = {
        "path": str(path),
        "rotated": False,
        "segment": None,
        "archived_lines": 0,
        "archived_bytes": 0,
        "hot_size_before": None,
        "hot_size_after": None,
    }

    if not path.exists():
        report["reason"] = "hot file does not exist -- nothing to rotate"
        return report

    # Stat captured HERE, before the read below, and re-checked just before
    # the final hot-file replace (2026-09-21 review): a writer that appends
    # between this read and that replace would otherwise have its row
    # silently discarded -- the replace overwrites the hot file with bytes
    # computed from the OLD content, with no idea a new row landed in
    # between. Re-stat-and-refuse turns a silent data loss into a clean,
    # retryable no-op (the caller's next rotation attempt sees the new row).
    pre_stat = path.stat()
    hot_size = pre_stat.st_size
    report["hot_size_before"] = hot_size
    if hot_size < threshold_bytes:
        report["reason"] = (
            f"hot size {hot_size} bytes < threshold {threshold_bytes} bytes")
        return report

    # UTC, always: stamps are written in UTC (module docstring) and the
    # cutoff must be computed in that same calendar, not whatever offset
    # happened to be attached to the caller's `now` (2026-09-21 review --
    # a non-UTC `now` used to shift the cutoff by up to a day).
    now_utc = now.astimezone(timezone.utc) if now.tzinfo is not None else now
    cutoff_date = now_utc.date() - timedelta(days=keep_days)
    report["cutoff_date"] = cutoff_date.isoformat()

    old_hot = path.read_bytes()
    lines = old_hot.splitlines(keepends=True)

<<<<<<< HEAD
=======
    # DUPLICATE-PREFIX GUARD (2026-09-28 design review of the decisions_v2
    # rotation). `rotate` makes the segment durable first (`os.replace` below)
    # and the shrunk hot file second; a hard kill between the two -- SIGKILL,
    # an OOM kill, a runner's timeout-minutes -- leaves the archived prefix in
    # BOTH places. The chain's verify() catches that state, but a LATER
    # rotation would not: it would archive the same prefix again into the next
    # segment and make the duplication permanent. So before anything else:
    # if the hot file still begins with the exact line the newest segment
    # begins with, refuse loudly and touch nothing. The reason starts with
    # "ESCALATE" so `src.cli`'s `store rotate` fails the run instead of
    # printing a quiet no-op.
    existing = segments(path)
    if existing and lines and lines[0].endswith(b"\n"):
        with gzip.open(existing[-1], "rb") as newest:
            newest_first_line = newest.readline()
        if newest_first_line == lines[0]:
            report["reason"] = (
                f"ESCALATE duplicate prefix: the hot file still begins with the "
                f"first line of {existing[-1].name}; a previous rotation was "
                f"interrupted after its segment was made durable. Nothing "
                f"archived; recover by hand before rotating again")
            return report

>>>>>>> origin/claude/sports-betting-analysis-review-g1o0co
    # `min_hot_rows` caps the prefix from the OTHER end: however many
    # complete lines the cutoff-date scan below would archive, the last
    # `min_hot_rows` of them are kept regardless. The trailing incomplete
    # line, if any, is excluded from `n_complete` FIRST -- it was never a
    # candidate anyway (the scan stops there regardless of this cap, exactly
    # as before) -- so it is never double-counted as one of the rows
    # `min_hot_rows` is keeping.
    n_complete = len(lines)
    if n_complete and not lines[-1].endswith(b"\n"):
        n_complete -= 1
    max_archivable = max(n_complete - min_hot_rows, 0)

    get_stamp = _stamp_getter(stamp_field, stamp_of)

    archive_upto = 0
    first_date: date | None = None
    last_date: date | None = None
    for line in lines[:max_archivable]:
        if not line.endswith(b"\n"):
            break  # incomplete trailing line -- an interrupted append, never touched
        try:
            row = json.loads(line)
        # ValueError, not just json.JSONDecodeError (its subclass): invalid
        # UTF-8 in a line raises UnicodeDecodeError, also a ValueError
        # subclass, out of json.loads's internal decode. Before this fix
        # that propagated out of `rotate` as an uncaught traceback instead
        # of the same "stop the prefix here" this scan already does for
        # malformed JSON (2026-09-21 review).
        except ValueError:
            break  # unparseable -- stop the prefix here, per the module docstring
        if not isinstance(row, dict):
            break
        line_date = get_stamp(row)
        if line_date is None:
            break  # unparseable/missing stamp -- stop the prefix here
        if line_date is UNDATED:
            # Archivable, but names no date of its own -- never a reason to
            # stop, never a contribution to the segment's date range either.
            archive_upto += 1
            continue
        if line_date >= cutoff_date:
            break
        archive_upto += 1
        if first_date is None or line_date < first_date:
            first_date = line_date
        if last_date is None or line_date > last_date:
            last_date = line_date

    if archive_upto == 0:
        if min_hot_rows > 0 and max_archivable == 0:
            report["reason"] = (
                f"min_hot_rows={min_hot_rows} leaves no line eligible to "
                f"archive (hot file has {n_complete} complete line(s))")
        else:
            report["reason"] = (
                f"no complete, parseable line at the start of the hot file is "
                f"dated before cutoff {cutoff_date.isoformat()}")
        return report

    if first_date is None:
        # Every line in the capped, archivable prefix was UNDATED -- a
        # segment filename requires at least one dated row to name its
        # range after (module docstring: `NNNN_<first-date>_<last-date>.
        # jsonl.gz`), so this refuses to invent one. The prefix (e.g. a lone
        # genesis row) stays in the hot file until a later rotation's capped
        # prefix also reaches a dated row.
        report["reason"] = (
            f"the archivable prefix ({archive_upto} line(s)) is entirely "
            f"UNDATED rows -- no dated row to name a segment after; "
            f"nothing archived")
        return report

    archive_bytes = b"".join(lines[:archive_upto])
    new_hot = b"".join(lines[archive_upto:])

    seg_dir = segment_dir(path)
    seg_dir.mkdir(parents=True, exist_ok=True)
    # max(existing seq) + 1, not len(segments) + 1 (2026-09-21 review): a
    # gap in the sequence (e.g. 0001 and 0003 present, 0002 missing --
    # manually removed, or a partial rotation cleaned up by hand) would
    # otherwise compute 0003 again and `os.replace` a SECOND time onto the
    # segment that is already there, silently discarding it -- os.replace
    # does not check whether its target exists.
    existing_seqs = [int(_SEGMENT_NAME_RE.match(p.name)["seq"])
                      for p in segments(path)]
    next_seq = max(existing_seqs, default=0) + 1
    segment_name = f"{next_seq:04d}_{first_date.isoformat()}_{last_date.isoformat()}.jsonl.gz"
    segment_path = seg_dir / segment_name
    if segment_path.exists():
        # Belt and suspenders on top of max()+1 above: refuse rather than
        # silently overwrite an existing segment with `os.replace` below.
        raise StoreArchiveError(
            f"rotate refusing to overwrite existing segment {segment_path} "
            f"-- archive directory left untouched")

    fd, tmp_seg_name = tempfile.mkstemp(dir=str(seg_dir), suffix=".tmp")
    os.close(fd)
    tmp_seg_path = Path(tmp_seg_name)
    try:
        with open(tmp_seg_path, "wb") as raw:
            # filename="" and mtime=0: deterministic gzip bytes, so rotating
            # the same input twice (a test doing exactly that) produces a
            # byte-identical segment rather than one that merely decompresses
            # to the same content.
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                gz.write(archive_bytes)

        # THE PROOF, BEFORE ANYTHING IS DURABLE. Verified against the TEMP
        # segment -- not yet the live one -- so a failed proof leaves no
        # half-finished segment sitting in the archive directory either: a
        # mismatch here must be exactly as if `rotate` was never called at
        # all, not "hot file safe, archive directory now has a corrupt
        # extra file nothing points at".
        with gzip.open(tmp_seg_path, "rb") as check:
            decompressed = check.read()
        rebuilt_hash = hashlib.sha256(decompressed + new_hot).hexdigest()
        original_hash = hashlib.sha256(old_hot).hexdigest()
        if rebuilt_hash != original_hash:
            raise StoreArchiveError(
                f"rotate verification failed for {path}: decompressed "
                f"segment + remaining hot bytes (sha256 {rebuilt_hash}) != "
                f"original hot file (sha256 {original_hash}) -- refusing, "
                f"hot file and archive directory left untouched")

        os.replace(tmp_seg_path, segment_path)
    except Exception:
        if tmp_seg_path.exists():
            tmp_seg_path.unlink()
        raise

    # RE-STAT, RIGHT BEFORE TRUSTING THE READ ABOVE (2026-09-21 review): the
    # segment is now durable and permanent -- from here on, ANY failure must
    # roll it back rather than leave the archived prefix duplicated once a
    # later rotation re-archives it from a hot file that still has it too.
    # A changed size or mtime means some other writer appended (or replaced)
    # the hot file while this scan was running; `old_hot`/`new_hot` were
    # computed from bytes that are no longer what is on disk, so replacing
    # the hot file now would silently discard whatever that writer added.
    try:
        post_stat = path.stat()
    except OSError as exc:
        segment_path.unlink()
        raise StoreArchiveError(
            f"rotate could not re-stat {path} before replacing it: {exc} "
            f"-- rolled back segment {segment_path}, hot file untouched"
        ) from exc
    if (post_stat.st_size, post_stat.st_mtime_ns) != (pre_stat.st_size, pre_stat.st_mtime_ns):
        segment_path.unlink()
        raise StoreArchiveError(
            f"rotate detected a concurrent write to {path} between reading "
            f"it and replacing it (size/mtime changed) -- rolled back "
            f"segment {segment_path}, hot file untouched; retry the "
            f"rotation")

    fd, tmp_hot_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    tmp_hot_path = Path(tmp_hot_name)
    try:
        tmp_hot_path.write_bytes(new_hot)
        os.replace(tmp_hot_path, path)
    except Exception:
        if tmp_hot_path.exists():
            tmp_hot_path.unlink()
        # ROLL BACK THE SEGMENT TOO (2026-09-21 review, the central bug this
        # pass fixes): the segment was already made durable above. Without
        # this, a failure here (ENOSPC, a Windows sharing violation from a
        # `--reload` dev server or Defender holding the hot file open, EIO)
        # left the segment in place while the hot file kept every row that
        # segment just archived -- the logical store then held the archived
        # prefix TWICE, and the next successful rotation would archive it a
        # second time as a new segment, making the duplication permanent.
        # A failure must leave EXACTLY the state a failed byte-identity
        # proof already leaves: no trace at all.
        if segment_path.exists():
            segment_path.unlink()
        raise

    report.update({
        "rotated": True,
        "segment": str(segment_path),
        "archived_lines": archive_upto,
        "archived_bytes": len(archive_bytes),
        "hot_size_after": len(new_hot),
    })
    return report


def snapshot_full(path: Path | str, *, now: datetime) -> dict:
    """Copy the WHOLE current hot file into a new archive segment, unchanged,
    leaving the hot file itself untouched.

    `rotate` (above) assumes its input is an append-only log where row N's
    stamp is never later than row N+1's, so it can archive a linear PREFIX
    and trim the hot file down to the remaining suffix. Not every store this
    project caches looks like that: `src/pipeline/pitchers.py`'s
    `pitcher_logs.jsonl` is grouped by person_id (ascending) and only sorted
    by date WITHIN one person, so there is no whole-file prefix `rotate`
    could archive, and -- unlike odds_multibook -- the whole file is REWRITTEN
    on every `write_logs` call rather than appended to. Added 2026-09-22 for
    exactly that store, so a run that is about to call `write_logs` (and
    therefore fully replace whatever is on disk) has a durable, verified copy
    of what was there immediately before, reusing this module's directory
    layout, gzip determinism, and byte-identity proof rather than inventing a
    second archiving mechanism.

    No-op (`{"snapshotted": False, "reason": ...}`, touches nothing) when the
    hot file is absent or empty -- there is nothing to lose in that case.

    The segment name still follows `_SEGMENT_NAME_RE` (`NNNN_<first>_<last>
    .jsonl.gz`) so it sorts and is recognised the same way a `rotate` segment
    is, but both dates are `now.date()`: this is a POINT-IN-TIME COPY of
    whatever the file held at snapshot time, not an archive of rows dated in
    that range the way a `rotate` segment's name would imply for
    odds_multibook.

    Verified the same way `rotate` verifies its own prefix: the temp segment
    is decompressed and sha256'd against the original hot bytes BEFORE the
    segment is made durable (`os.replace`); a mismatch raises
    `StoreArchiveError` and leaves the archive directory exactly as it was.
    The hot file is never opened for writing here at all, so there is no
    rollback path to speak of -- either the copy is proven byte-identical and
    made durable, or nothing durable exists yet.

    Calling this twice in the same UTC day for the same store produces two
    distinct segments (the sequence number, not the date pair, disambiguates
    them) -- no `label` parameter is offered because the one caller this was
    built for (`pitchers.build_log_store`) runs at most once per invocation,
    and every segment name must stay conformant with `_SEGMENT_NAME_RE` so
    `segments()`'s own next-sequence-number scan keeps seeing it.
    """
    path = Path(path)
    report: dict = {
        "path": str(path), "snapshotted": False, "segment": None,
        "bytes": 0,
    }
    if not path.exists():
        report["reason"] = "hot file does not exist -- nothing to snapshot"
        return report

    original = path.read_bytes()
    if not original:
        report["reason"] = "hot file is empty -- nothing to snapshot"
        return report

    now_utc = now.astimezone(timezone.utc) if now.tzinfo is not None else now
    stamp = now_utc.date().isoformat()

    seg_dir = segment_dir(path)
    seg_dir.mkdir(parents=True, exist_ok=True)
    existing_seqs = [int(_SEGMENT_NAME_RE.match(p.name)["seq"])
                      for p in segments(path)]
    next_seq = max(existing_seqs, default=0) + 1
    segment_name = f"{next_seq:04d}_{stamp}_{stamp}.jsonl.gz"
    segment_path = seg_dir / segment_name
    if segment_path.exists():
        raise StoreArchiveError(
            f"snapshot_full refusing to overwrite existing segment "
            f"{segment_path} -- archive directory left untouched")

    fd, tmp_name = tempfile.mkstemp(dir=str(seg_dir), suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with open(tmp_path, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                gz.write(original)

        with gzip.open(tmp_path, "rb") as check:
            decompressed = check.read()
        if hashlib.sha256(decompressed).hexdigest() != hashlib.sha256(original).hexdigest():
            raise StoreArchiveError(
                f"snapshot_full verification failed for {path}: decompressed "
                f"copy does not match the original bytes -- refusing, hot "
                f"file and archive directory left untouched")

        os.replace(tmp_path, segment_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    report.update({
        "snapshotted": True,
        "segment": str(segment_path),
        "bytes": len(original),
    })
    return report


# ---------------------------------------------------------------------------
# The registry `src.cli`'s `store rotate` command drives. Started with just
# odds_multibook (the store that was actually over GitHub's limit,
# 2026-09-21) -- derivative_markets.jsonl (63 MB) and batter_props.jsonl
# (40 MB) are growing toward the same wall (module docstring) but were not on
# fire that day. `decisions_v2` (the hash-chained decisions ledger,
# src/ledger/chain.py) was added next, once GitHub actually started rejecting
# pushes for it too (104,665,523 bytes against a 104,857,600-byte hard
# limit): it needs `stamp_of` rather than a bare `stamp_field` because its
# `recorded_utc` is NOT monotone in file order (~1,739 decreases, mostly
# within a day) and because its genesis row (no timestamp at all) must still
# be archivable, and it needs `min_hot_rows=1` so the hot file always has a
# row for `HashChainLedger.append()`'s `last_hash()` to chain the next row to
# without ever reading the archive.
# ---------------------------------------------------------------------------

def _odds_multibook_path() -> Path:
    # Local import: this module must not require the rest of src/pipeline to
    # import cleanly (src.paths has no heavy dependencies, but keeping the
    # import inside the registry factory, rather than at module level,
    # mirrors how the rest of this file takes every path as a parameter
    # rather than hardcoding one).
    from src.paths import processed_path

    return processed_path("odds_multibook.jsonl")


def _decisions_v2_path() -> Path:
    # Local import, same reasoning as `_odds_multibook_path` above.
    from src.paths import evidence_path

    return evidence_path("decisions_v2.jsonl")


def _decisions_v2_stamp_of(row: dict):
    """genesis -> UNDATED (archivable, but the genesis row carries no
    timestamp at all); otherwise the first parseable of `recorded_utc`
    (decision rows), `corrected_utc`/`created_utc` (correction rows --
    scripts/append_edge_withdrawal_corrections.py writes one or the other);
    otherwise None, which stops the archivable prefix scan there rather than
    guess. Every non-genesis row in this ledger carries at least one of the
    three (verified fact, not an assumption this function makes)."""
    if row.get("kind") == "genesis":
        return UNDATED
    for field in ("recorded_utc", "corrected_utc", "created_utc"):
        parsed = _parse_stamp_date(row.get(field), field)
        if parsed is not None:
            return parsed
    return None


ROTATABLE_STORES: dict[str, dict] = {
    "odds_multibook": {
        "path": _odds_multibook_path,
        "stamp_field": "observed_utc",
    },
    "decisions_v2": {
        "path": _decisions_v2_path,
        "stamp_of": _decisions_v2_stamp_of,
        "min_hot_rows": 1,
    },
}
