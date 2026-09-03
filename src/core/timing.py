"""Wall-clock and CPU instrumentation for the research pipeline.

WHY THIS EXISTS
----------------
`docs/planning/map-compute-scale.md` section 1: the sweep's headline
throughput claim ("11,088 genomes in 51 ms", `docs/EVOLAB_DESIGN.md:384`) was
never measured -- it is a design-time estimate that nothing in `sweep.py`,
`replay.py` or `registry.py` records. The Phase 2B artifact that shipped the
project's most important published verdict carries no timing field at all.
"Compute is never the bottleneck" is an empirical claim; without a number
attached to every run, it is an opinion wearing a number's clothes.

This module is the one place that measures. It does not decide what counts as
slow, and it never touches research content -- adding `stage()` around a
computation must not change one byte of what that computation returns. The
determinism tests in `tests/test_timing.py` and `tests/test_evolab_sweep.py`
pin exactly that: an artifact built with instrumentation and one built
without must be byte-identical outside the `timings` key.

WHAT GETS MEASURED, AND WHY THESE FOUR NUMBERS
-----------------------------------------------
- `wall_s` (time.perf_counter): what a human waiting on the run experiences.
  The only number of the four that captures I/O wait (disk reads of the
  JSONL stores) as well as CPU-bound work.
- `cpu_s` (time.process_time): process CPU time only. The gap between
  `wall_s` and `cpu_s` is time spent NOT computing -- I/O, GC pauses, or (on
  a busy box) time preempted by other processes. A stage whose wall time
  dwarfs its CPU time is I/O-bound (matrix.py's JSONL re-parse, per
  map-compute-scale.md section 2b), not CPU-bound (the bitset arithmetic,
  section 2a) -- conflating the two would send optimization effort at the
  wrong target.
- `peak_rss_mb` (resource.getrusage(RUSAGE_SELF).ru_maxrss): peak resident
  set size for the whole process at the time this stage ends. `ru_maxrss` is
  cumulative-since-process-start on Linux (it is a running maximum, not a
  per-call delta), so a later stage's `peak_rss_mb` can never be smaller than
  an earlier one's within the same process -- this is documented rather than
  worked around because a delta would require sampling before AND after
  every stage, which is exactly the kind of overhead this module promises not
  to add to the hot path.
- `decisions` / `decisions_per_s`: the caller-supplied count of genome
  x world (or game) evaluations this stage represents, divided by `wall_s`.
  None when the caller has no meaningful count for a stage (e.g. `write`) --
  a 0 or a fabricated count would be worse than an honest absence.

STDLIB ONLY
-----------
`resource` is POSIX-only (no `psutil`, no third-party dependency) --
`bitsets.py:8`'s "no numpy" environment constraint extends here: this module
must run in the exact same environment the sweep already runs in, unmodified.
`resource.getrusage` is unavailable on Windows; this codebase runs on Linux
containers only (map-compute-scale.md section 3), so that limitation is
accepted rather than papered over with a cross-platform shim nobody asked for.
"""

from __future__ import annotations

import resource
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Sequence


class TimingError(RuntimeError):
    """Raised when an artifact is written without required timing evidence."""


@dataclass(frozen=True)
class StageTiming:
    """One stage's measured cost. Immutable -- a stage is measured once."""

    stage: str
    wall_s: float
    cpu_s: float
    rows: int | None
    decisions: int | None
    decisions_per_s: float | None
    peak_rss_mb: float

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "wall_s": self.wall_s,
            "cpu_s": self.cpu_s,
            "rows": self.rows,
            "decisions": self.decisions,
            "decisions_per_s": self.decisions_per_s,
            "peak_rss_mb": self.peak_rss_mb,
        }


@dataclass
class TimingCollector:
    """An ordered list of `StageTiming` records for one run.

    Passed by callers into `stage()` (or built implicitly by `stage()` when
    no collector is given, for one-off measurement). Callers that want a
    run's stages persisted into an artifact hold one of these across the
    whole run and call `.to_list()` when building the artifact dict.
    """

    records: list = field(default_factory=list)

    def add(self, timing: StageTiming) -> None:
        self.records.append(timing)

    def to_list(self) -> list:
        return [t.to_dict() for t in self.records]


def _peak_rss_mb() -> float:
    """Peak RSS in MB. `ru_maxrss` is KiB on Linux, bytes on macOS (BSD) --
    this codebase's containers are Linux (map-compute-scale.md section 3), so
    KiB is what is measured, and only ever adjusted if that stops being true.
    """
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


@contextmanager
def stage(name: str, *, collector: TimingCollector | None = None,
         rows: int | None = None, decisions: int | None = None
         ) -> Iterator[TimingCollector]:
    """Time one named stage of a run.

    Usage::

        timings = TimingCollector()
        with stage("load", collector=timings, rows=n_games):
            ...

    `decisions_per_s` is computed from `decisions` and the measured wall time
    only when both `decisions` and a positive `wall_s` are available -- never
    from `cpu_s`, so I/O-bound stages (a JSONL re-parse) do not get an
    inflated decisions-per-second figure by dividing by the smaller number.
    Yields the `TimingCollector` the record was appended to -- the one passed
    in, or a fresh one when the caller only wants the single measurement.
    """
    own = collector if collector is not None else TimingCollector()
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    try:
        yield own
    finally:
        wall_s = time.perf_counter() - wall_start
        cpu_s = time.process_time() - cpu_start
        decisions_per_s = (decisions / wall_s
                           if decisions is not None and wall_s > 0 else None)
        own.add(StageTiming(
            stage=name, wall_s=wall_s, cpu_s=cpu_s, rows=rows,
            decisions=decisions, decisions_per_s=decisions_per_s,
            peak_rss_mb=_peak_rss_mb()))


_REQUIRED_KEYS = frozenset({"stage", "wall_s", "cpu_s", "peak_rss_mb"})


def require_timings(artifact: dict, *, min_stages: int = 1) -> None:
    """Fail loudly if `artifact` is missing timing evidence.

    Called by every artifact writer in this package before the bytes hit
    disk (design intent: an artifact without timings should never exist,
    the same discipline `SweepReport.write` already applies to namespace
    isolation). Checks structure, not values -- a stage legitimately can
    have `wall_s == 0.0` on a fast machine; what it cannot have is a missing
    key or a `timings` list that is empty or absent.
    """
    if "timings" not in artifact:
        raise TimingError(
            "artifact has no 'timings' key -- every artifact this package "
            "writes must carry per-stage timing (docs/planning/"
            "map-compute-scale.md section 1: the alternative is an "
            "unmeasured throughput claim shipping again)")
    timings = artifact["timings"]
    if not isinstance(timings, Sequence) or isinstance(timings, (str, bytes)):
        raise TimingError(
            f"artifact['timings'] must be a list of stage records, got "
            f"{type(timings).__name__}")
    if len(timings) < min_stages:
        raise TimingError(
            f"artifact['timings'] has {len(timings)} stage(s), need at "
            f"least {min_stages}")
    for i, record in enumerate(timings):
        if not isinstance(record, dict):
            raise TimingError(f"timings[{i}] is not a dict: {record!r}")
        missing = _REQUIRED_KEYS - record.keys()
        if missing:
            raise TimingError(
                f"timings[{i}] ({record.get('stage', '?')!r}) is missing "
                f"required key(s) {sorted(missing)}")
        if not isinstance(record["stage"], str) or not record["stage"]:
            raise TimingError(f"timings[{i}] has an empty/non-string stage "
                              f"name: {record.get('stage')!r}")
