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

import os
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
    "Linehound -- sports-betting information and research -- price "
    "comparisons and context to inform your own wagering decisions, not "
    "picks or guarantees."
)

# Working brand only -- per Brey's 2026-09-01 decision: "Use LINEHOUND
# anywhere a temporary customer-facing brand is required ... Do not
# buy/register the final domain or make irreversible legal branding
# decisions until trademark/domain clearance is completed." `temporary`
# stays True until that clearance lands and a final name is chosen; do not
# flip it without Brey saying so.
BRAND = {"name": "Linehound", "temporary": True}

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


def _public_demo() -> bool:
    """Mirrors api/app.py's APP_PUBLIC_DEMO parse (read here directly rather
    than imported, so this module never imports the app it is mounted on).
    Read per request, not at import: the client uses it to decide whether
    to show the sign-in wall, and a test may flip the variable."""
    return (os.environ.get("APP_PUBLIC_DEMO") or "").strip().lower() in (
        "1", "true", "yes")


def _research_counts() -> dict:
    """Registry counts, or an explicit absence -- never a guessed number.

    /meta is hit on every page load and must not 500 because a research
    file moved. An unreadable registry reports nulls, and the client
    renders the sentence without figures rather than inventing them; that
    is the same honest-absence rule every other surface here follows.
    """
    try:
        from src.research import alpha_registry
        return alpha_registry.public_research_counts()
    except Exception:  # noqa: BLE001
        return {"hypotheses": None, "surviving": None}


@router.get("/meta")
def get_meta() -> dict:
    return {
        "version": APP_VERSION,
        "product": PRODUCT_ONE_LINER,
        "disclaimer": get_disclaimer(),
        "brand": BRAND,
        # True only when the deployment serves the read-only game surface
        # without a token (hosted demo). The client hides the sign-in wall
        # and the BETS destination when this is set; see api/app.py.
        "public_demo": _public_demo(),
        # The two research numbers the product states to customers, read
        # from data/research/alpha_registry.jsonl rather than typed into a
        # view. They used to be hardcoded in four places at three different
        # values -- the app said 27, Bet Check said "twenty-seven", the
        # landing page said 25, and the registry said 40 -- so a prospect
        # read one number on the page that sold them the subscription and a
        # different one the first time they opened the app. See
        # src/research/alpha_registry.public_research_counts.
        "research": _research_counts(),
    }
