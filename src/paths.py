"""Repo-root-anchored data paths.

WHY THIS EXISTS
---------------
Every data path in this project used to be a bare relative string --
`data/historical/mlb_results.csv` -- resolved against the current working directory.
Combined with `mkdir(parents=True)` on every writer, that produces a specific and
nasty failure:

    $ cd /tmp && python -m src.cli history
    games stored: 0

No error. No warning. Reading from the wrong directory silently returns an EMPTY
dataset, and writing from the wrong directory silently creates a SECOND one. The
project reports 2,443 games from the repo root and 0 from anywhere else.

That is tolerable while a human runs commands by hand from the project folder. It
stops being tolerable the moment anything is scheduled, because cron's working
directory is not the repo -- so a nightly job would quietly build a parallel, empty
dataset while the real one went stale, and every report would look fine.

Paths are therefore anchored to the repository root, found from this file's own
location rather than from the process's cwd. `AISPORTS_DATA_DIR` overrides the data
root for anyone who wants the store somewhere else, which also makes tests able to
redirect writes without monkeypatching module constants.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "AISPORTS_DATA_DIR"


def repo_root() -> Path:
    """The repository root, derived from this file rather than the cwd.

    src/paths.py -> src/ -> repo root. Deriving it from __file__ is what makes the
    result independent of where the process was started.
    """
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """The data directory. Overridable via AISPORTS_DATA_DIR."""
    override = (os.environ.get(ENV_DATA_DIR) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "data"


def data_path(*parts) -> Path:
    """Build a path under the data root.

    >>> data_path("historical", "mlb_results.csv").is_absolute()
    True
    """
    return data_root().joinpath(*parts)


def raw_path(*parts) -> Path:
    return data_path("raw", *parts)


def processed_path(*parts) -> Path:
    return data_path("processed", *parts)


def historical_path(*parts) -> Path:
    return data_path("historical", *parts)
