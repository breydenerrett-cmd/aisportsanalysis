"""Cadence SLO: grade is computed from measured poll gaps, never asserted.

WHY THIS EXISTS
----------------
docs/planning/attack.md F10: every grade-A/B claim in the corpus is
downstream of a scheduler whose observed unattended success rate was zero.
The synthesis had made `known_at_grade` an ASSERTION tied to a schedule
("Tier A fires every 15 minutes, so it's grade B"); F10's fix is that the
grade must be COMPUTED from the actual measured gap between polls, because a
six-hour hole in an allegedly-15-minute schedule makes every fact bracketed
across that hole a grade-C fact wearing a grade-B label.

WHAT THIS READS
-----------------
Only timestamps already written by other modules -- this module fetches
nothing and spends nothing:

- `data/processed/odds_multibook.jsonl` -- one `observed_utc` per capture
  instant (src/pipeline/snapshots.py).
- rosterwatch's lineup-watch marker rows -- one `fetched_utc` per poll,
  `poll: true` (src/pipeline/rosterwatch.py).
- umpirewatch's marker rows -- one `observed_utc` per poll, `poll: true`
  (src/pipeline/umpirewatch.py).
- `data/processed/weather_forecast.jsonl` -- one `observed_utc` per tick
  (src/pipeline/weather_capture.py).

WHAT IT WRITES
---------------
One row per (date, source) to `data/processed/cadence_slo.jsonl`, appended
like every other forward store here -- never rewritten. Each row: attempted
(rows seen that day), longest_gap_seconds, p95_gap_seconds, grade
(`grade_from_gap` on the longest gap -- the SLO is only as good as its worst
gap), computed_utc.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.paths import data_path, processed_path

LOG = logging.getLogger(__name__)

# rosterwatch/umpirewatch both write to data/watch/ (src.paths.data_path
# ("watch"), NOT processed_path) -- data/watch/ is sacred forward-capture
# territory (see this program's hard rules); this module only ever reads it.
DEFAULT_WATCH_DIR = data_path("watch")

DEFAULT_MULTIBOOK_PATH = processed_path("odds_multibook.jsonl")
DEFAULT_LINEUPS_WATCH_PATH = DEFAULT_WATCH_DIR / "lineups_watch.jsonl"
DEFAULT_UMPIRES_WATCH_PATH = DEFAULT_WATCH_DIR / "umpires_watch.jsonl"
DEFAULT_WEATHER_PATH = processed_path("weather_forecast.jsonl")
DEFAULT_SLO_STORE = processed_path("cadence_slo.jsonl")

# grade_from_gap thresholds, in seconds. F10's fix, verbatim:
# "gap <= 20min => B, <= 2h => C, else D".
GRADE_B_MAX_SECONDS = 20 * 60
GRADE_C_MAX_SECONDS = 2 * 60 * 60


def grade_from_gap(seconds) -> str:
    """B if the gap bracketing a fact is <=20min, C if <=2h, else D.

    `seconds` is a measured gap between the poll that did NOT yet see a fact
    and the first poll that did -- never asserted from a schedule. None or a
    negative gap is refused (a caller passing an unmeasured or nonsensical
    interval is a bug, not a D grade).
    """
    if seconds is None or seconds < 0:
        raise ValueError(f"grade_from_gap requires a measured, non-negative "
                          f"gap in seconds; got {seconds!r}")
    if seconds <= GRADE_B_MAX_SECONDS:
        return "B"
    if seconds <= GRADE_C_MAX_SECONDS:
        return "C"
    return "D"


def _read_jsonl(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _timestamps_for_date(rows, date_str, field, poll_only=False) -> list:
    out = []
    for row in rows:
        if poll_only and not row.get("poll"):
            continue
        stamp = row.get(field)
        if not stamp or not stamp.startswith(date_str):
            continue
        out.append(stamp)
    return sorted(set(out))


def _parse_iso(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _gaps_seconds(timestamps: list) -> list:
    moments = [_parse_iso(t) for t in timestamps]
    return [(b - a).total_seconds() for a, b in zip(moments, moments[1:])]


def _percentile(values: list, pct: float) -> float:
    """Nearest-rank percentile, no numpy dependency for one small list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = pct / 100.0 * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def source_cadence(date_str: str, timestamps: list) -> dict:
    """attempted/succeeded/longest_gap/p95_gap/grade for one source's day.

    `succeeded` == `attempted` here by construction: every timestamp this
    module reads comes from a store that only records a SUCCESSFUL poll
    (each module's own marker/row convention -- a failed fetch does not
    write one). A day with fewer rows than expected shows up as a longer
    gap, not as a distinct failure count; that gap is the honest signal.
    """
    attempted = len(timestamps)
    gaps = _gaps_seconds(timestamps)
    longest = max(gaps) if gaps else None
    p95 = _percentile(gaps, 95) if gaps else None
    grade = grade_from_gap(longest) if longest is not None else None
    return {
        "date": date_str,
        "attempted": attempted,
        "succeeded": attempted,
        "longest_gap_seconds": longest,
        "p95_gap_seconds": p95,
        "grade": grade,
    }


SOURCES = {
    "odds_multibook": {
        "path": DEFAULT_MULTIBOOK_PATH, "field": "observed_utc", "poll_only": False,
    },
    "rosterwatch_lineups": {
        "path": DEFAULT_LINEUPS_WATCH_PATH, "field": "fetched_utc", "poll_only": True,
    },
    "umpirewatch": {
        "path": DEFAULT_UMPIRES_WATCH_PATH, "field": "observed_utc", "poll_only": True,
    },
    "weather_forecast": {
        "path": DEFAULT_WEATHER_PATH, "field": "observed_utc", "poll_only": False,
    },
}


def compute(date_str: str, sources=None, now=None) -> dict:
    """Compute (never write) the SLO for every source on `date_str`.

    `sources` overrides the default store paths -- tests pass fixtures here
    rather than touching data/processed/.
    """
    sources = sources if sources is not None else SOURCES
    computed_utc = _utc_iso(_now(now))
    per_source = {}
    for name, cfg in sources.items():
        rows = _read_jsonl(cfg["path"])
        timestamps = _timestamps_for_date(
            rows, date_str, cfg["field"], poll_only=cfg.get("poll_only", False))
        per_source[name] = source_cadence(date_str, timestamps)
    return {"date": date_str, "computed_utc": computed_utc, "sources": per_source}


def write(date_str: str, sources=None, now=None, store=None) -> dict:
    """Compute the SLO for `date_str` and append one row per source.

    Append-only, like every other forward store: never rewrites an existing
    date's row, even if called twice for the same date (the reader is
    expected to take the latest row per (date, source) if it cares).
    """
    result = compute(date_str, sources=sources, now=now)
    target = Path(store if store is not None else DEFAULT_SLO_STORE)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with target.open("a", encoding="utf-8") as handle:
            if _ends_ragged(target):
                handle.write("\n")
            for name, slo in result["sources"].items():
                row = dict(slo)
                row["source"] = name
                row["computed_utc"] = result["computed_utc"]
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                written += 1
    except Exception as exc:  # noqa: BLE001 -- match creditlog's fail-silent contract
        LOG.debug("cadence: failed to append (%s: %s)", type(exc).__name__, exc)
        result["written"] = 0
        result["write_error"] = str(exc)
        return result
    result["written"] = written
    return result


def read(store=None) -> list:
    return _read_jsonl(store if store is not None else DEFAULT_SLO_STORE)


def _ends_ragged(target) -> bool:
    target = Path(target)
    if not target.exists() or not target.stat().st_size:
        return False
    with target.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1) != b"\n"


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("cadence now() must return a timezone-aware datetime")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv=None) -> int:
    """`python3 -m src.cli cadence --date YYYY-MM-DD` wires here."""
    import sys
    args = argv if argv is not None else sys.argv[1:]
    date_str = None
    it = iter(args)
    for arg in it:
        if arg == "--date":
            date_str = next(it, None)
    if not date_str:
        date_str = datetime.now(timezone.utc).date().isoformat()
    result = write(date_str)
    print(f"cadence SLO for {date_str} ({result['written']} rows written to "
          f"{DEFAULT_SLO_STORE}):")
    for name, slo in result["sources"].items():
        print(f"  {name:22s} attempted={slo['attempted']:3d}  "
              f"longest_gap={slo['longest_gap_seconds']}  "
              f"p95_gap={slo['p95_gap_seconds']}  grade={slo['grade']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
