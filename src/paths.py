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


def evidence_path(*parts) -> Path:
    """Records that are UNBACKFILLABLE, and therefore committed rather than ignored.

    Everything under data/ is gitignored on the correct grounds that it is
    reproducible: results, slates and pitcher logs can all be re-fetched from the
    providers, so committing them would bloat history for nothing.

    Forward-looking records are the exact opposite. A prediction is evidence only
    because it was written down BEFORE the game, and a mismatch flag is evidence only
    because it carries the price that was available at the moment it was raised. Once
    the game is played, neither can be reconstructed by anyone, at any cost.

    Left under data/, they were gitignored -- which in a container that gets reclaimed
    means the forward evidence the entire validation plan rests on quietly evaporates,
    with the code still running perfectly and the log starting again from zero.

    So they live here, tracked, next to docs/test_split_seal.json for the same reason
    that file does. Deliberately NOT under AISPORTS_DATA_DIR: redirecting the data root
    must not silently redirect the evidence too.
    """
    return repo_root().joinpath("evidence", *parts)
