"""Remote live game state and research candidate reads via GitHub raw content.

WHY THIS EXISTS
---------------
The live runner (src/pipeline/live_window.py) writes game-state rows to
data/live/<sport>/<YYYY-MM-DD>.jsonl and research candidates to
evidence/live_candidates_v1.jsonl and pushes them to the branch every five
minutes from a GitHub Actions job. The staging container is built at deploy
time and never sees those pushes (its image does not copy data/live), so
GET /live would answer "idle" through every game. The repository is public,
so the pushed files are readable without a token; this module reads them
with a 60-second in-process cache, and a failed read is cached too so an
outage never turns into a request storm. LIVE_REMOTE_BASE=off disables it.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Optional, Callable

REMOTE_BASE_ENV = "LIVE_REMOTE_BASE"
DEFAULT_BRANCH = "claude/sports-betting-analysis-review-g1o0co"


# A constant, not a `git remote` call at import: the container has no git
# and no checkout, and an import that shells out is a surprise in a web app.
_OWNER_REPO = "breydenerrett-cmd/aisportsanalysis"
_DEFAULT_BASE = f"https://raw.githubusercontent.com/{_OWNER_REPO}/{DEFAULT_BRANCH}/"

# Simple in-process cache: path -> (fetched_epoch, text)
_CACHE: dict[str, tuple[float, Optional[str]]] = {}


def fetch_text(url: str, timeout: int = 5) -> Optional[str]:
    """Fetch text from a URL. Returns None on any error or non-200.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        The response text, or None on any error.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "linehound-live-remote"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8")
    except Exception:
        pass
    return None


def cached_text(
    path: str,
    *,
    ttl_seconds: int = 60,
    now: Optional[float] = None,
    fetch: Optional[Callable[[str], Optional[str]]] = None,
) -> Optional[str]:
    """Fetch and cache text for a path. Returns None on error.

    A failed fetch is cached as None for the TTL, so an outage does not
    hammer the remote repeatedly.

    Args:
        path: Cache key and relative path.
        ttl_seconds: Time-to-live in seconds.
        now: Current time (defaults to time.time()).
        fetch: Fetch function (defaults to fetch_text).

    Returns:
        Cached or fetched text, or None.
    """
    fetch = fetch or fetch_text
    now = now or time.time()

    # Check cache
    if path in _CACHE:
        fetched_epoch, cached_val = _CACHE[path]
        if now - fetched_epoch < ttl_seconds:
            return cached_val

    # Fetch new value
    base = os.environ.get(REMOTE_BASE_ENV) or _DEFAULT_BASE
    if base == "off":
        return None

    url = f"{base}{path}"
    result = fetch(url)

    # Cache result (including None for failures)
    _CACHE[path] = (now, result)
    return result


def remote_jsonl(path: str, **kw) -> list[dict]:
    """Read and parse a remote JSONL file, skipping bad lines.

    Args:
        path: Relative path to the file.
        **kw: Passed to cached_text.

    Returns:
        List of parsed JSON objects, skipping lines that fail to parse.
    """
    text = cached_text(path, **kw)
    if not text:
        return []

    result = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            pass  # Skip bad lines

    return result


def live_state_rows(sport: str, date: str, **kw) -> list[dict]:
    """Read remote game state rows for a sport and date.

    Args:
        sport: "mlb" or "nfl".
        date: YYYY-MM-DD string.
        **kw: Passed to remote_jsonl.

    Returns:
        List of state row dicts.
    """
    return remote_jsonl(f"data/live/{sport}/{date}.jsonl", **kw)


def live_candidate_rows(**kw) -> list[dict]:
    """Read remote research candidate rows.

    Args:
        **kw: Passed to remote_jsonl.

    Returns:
        List of candidate row dicts.
    """
    return remote_jsonl("evidence/live_candidates_v1.jsonl", **kw)


def enabled(env: Optional[dict[str, str]] = None) -> bool:
    """Check if remote reads are enabled.

    Args:
        env: Environment dict (defaults to os.environ).

    Returns:
        False if env[REMOTE_BASE_ENV] == "off", True otherwise.
    """
    env = env or os.environ
    return env.get(REMOTE_BASE_ENV) != "off"
