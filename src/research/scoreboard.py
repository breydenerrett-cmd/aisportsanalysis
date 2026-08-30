"""Run scoreboard: did the autonomous run reduce uncertainty, or just emit code?

WHY THIS EXISTS
---------------
A long unattended run can produce thousands of lines and settle nothing. The
number that matters at the end is epistemic: how many hypotheses were screened,
how many were killed, how many replicated, how many survive -- and what the
odds-credit budget bought. This module records exactly that, one JSON line per
run, so runs are comparable across weeks and a run that "did a lot" but killed
nothing is visible as such.

WHY NO TIMESTAMPS ARE INVENTED HERE
-----------------------------------
`started` and `finished` come from the caller, or stay empty. The run knows
when it started; this module does not, and stamping append-time as start-time
would quietly turn a bookkeeping field into a fabrication -- the same
never-guess rule the rest of the codebase applies to data. Missing counts
default to 0 and missing text to "", so every line carries the full schema and
downstream readers never need per-key existence checks.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.paths import data_path

DEFAULT_STORE = data_path("research", "scoreboard.jsonl")

# Every line carries all of these. Counts default to 0, text to "" -- a run
# that reports nothing for a field reports zero of it, explicitly.
COUNT_KEYS = ("hypotheses_screened", "hypotheses_killed",
              "hypotheses_replicated", "survivors", "credits_spent")
TEXT_KEYS = ("started", "finished", "notes")


class ScoreboardError(RuntimeError):
    """Raised when the scoreboard cannot be written or read honestly."""


def record(run_summary, path=DEFAULT_STORE) -> dict:
    """Append one run's summary as a JSON line; returns the row as written.

    Unknown keys the caller included are kept -- a run that chose to write
    something down should not have it silently dropped by the bookkeeper --
    but the schema keys are always present so the file stays uniform.
    """
    if not isinstance(run_summary, dict):
        raise ScoreboardError(f"run_summary must be a dict, got {type(run_summary).__name__}")
    row = dict(run_summary)
    for key in COUNT_KEYS:
        row.setdefault(key, 0)
    for key in TEXT_KEYS:
        row.setdefault(key, "")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read(path=DEFAULT_STORE) -> list:
    """All recorded runs, oldest first. Missing file is empty, not an error.

    A line that does not parse raises: this file is written only by record(),
    so corruption means something went wrong that skipping would hide.
    """
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ScoreboardError(f"{target}:{number} is not valid JSON") from exc
    return rows


def format_latest(path=DEFAULT_STORE) -> str:
    """The most recent run, one short line for a human or a debrief."""
    rows = read(path)
    if not rows:
        return "no runs recorded"
    row = rows[-1]
    span = f"{row.get('started') or '?'} -> {row.get('finished') or '?'}"
    line = (f"{span}: screened {row.get('hypotheses_screened', 0)}, "
            f"killed {row.get('hypotheses_killed', 0)}, "
            f"replicated {row.get('hypotheses_replicated', 0)}, "
            f"survivors {row.get('survivors', 0)}, "
            f"credits {row.get('credits_spent', 0)}")
    notes = row.get("notes") or ""
    return f"{line} -- {notes}" if notes else line
