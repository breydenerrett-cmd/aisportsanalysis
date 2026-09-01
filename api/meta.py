"""GET /meta -- app version, the beta disclaimer, and the product one-liner.

No auth: this is the one route a staging preview's landing page, a support
ticket, or Brey checking "what's actually deployed right now" needs to hit
with no bearer token -- same reasoning as api/health.py's no-auth line, just
for "what version/what disclaimer" instead of "is it up".

WHY THE VERSION IS READ ONCE AT IMPORT, NOT PER-REQUEST
--------------------------------------------------------
`git describe` shells out to `git`, which is not guaranteed to exist (or to
find a `.git` dir) inside a built container -- the whole point of
deploy/Dockerfile copying source instead of a git checkout. Running that
subprocess on every request would mean paying its cost (and its failure
mode) per call, for a value that cannot change during the process's
lifetime. Reading it once at import time, with "dev" as the fallback, means
GET /meta is exactly as cheap and exactly as safe as GET /health.

WHY "dev", NOT AN EXCEPTION OR None
-------------------------------------
A version string that cannot be produced (no git, no .git dir, git not on
PATH) is not a failure of the endpoint -- the app still runs, still serves
real answers. "dev" says plainly "not a tagged/traceable build" without
turning an ops nicety into a reason GET /meta would 500.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter

from src.analysis.disclaimers import get_disclaimer

router = APIRouter()

# Kept out of the tout-vocabulary scan's SCAN_DIRS (src/analysis,
# src/report) on purpose -- this is app.py-adjacent wiring, not domain
# code -- but it is still written to the same rule: no EV/edge/guarantee
# language, because it is customer-facing the moment a staging URL exists.
PRODUCT_ONE_LINER = (
    "Sports-betting information and research -- price comparisons and "
    "context to inform your own wagering decisions, not picks or "
    "guarantees."
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_FALLBACK_VERSION = "dev"


def _read_version() -> str:
    """`git describe --tags --always --dirty`, or "dev" if that is not
    possible (no git binary, no .git dir -- exactly the built-container
    case deploy/Dockerfile produces, since it COPYs source, not a clone).
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
            check=False)
    except (OSError, subprocess.SubprocessError):
        return _FALLBACK_VERSION
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        return _FALLBACK_VERSION
    return version


# Read once at import time -- see module docstring.
APP_VERSION = _read_version()


@router.get("/meta")
def get_meta() -> dict:
    return {
        "version": APP_VERSION,
        "product": PRODUCT_ONE_LINER,
        "disclaimer": get_disclaimer(),
    }
