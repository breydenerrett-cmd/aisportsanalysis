"""Serves web/ (the structural reference client) as static files.

NOT wired into api/app.py by this module -- that file is another lane's
boundary (see this task's BOUNDARIES). Whoever owns api/app.py adds:

    from api.web import router as web_router
    app.include_router(web_router)

WHY FileResponse INSTEAD OF fastapi.staticfiles.StaticFiles
--------------------------------------------------------------------------
StaticFiles mounts a sub-application at a path prefix, which is a second
way routes get registered in this codebase beyond `APIRouter` +
`include_router` -- every other api/ module uses. A hand-rolled
FileResponse route keeps this file the same shape as every sibling router
(api/games.py, api/odds.py, ...) and keeps the directory-traversal guard
explicit and readable in one place instead of trusting a library default.

WHY NO AUTH DEPENDENCY HERE
--------------------------------------------------------------------------
These are static assets (HTML/JS), not game data -- api/app.py's
`_authed` dependency list gates the game surface itself (docs/API_
CONTRACTS.md's routes), not the reference client that calls it. The
client stores its own invite token in localStorage (web/js/api.js) and
sends it on each API call; serving index.html/js/*.js with no token would
otherwise make it impossible to even reach the token-entry form.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = (REPO_ROOT / "web").resolve()

# Extension allowlist: this client ships only these file types (see
# web/README.md's file list). A `.py`, `.env`, or dotfile dropped into
# web/ by mistake must never become servable just by matching a path
# pattern -- an allowlist refuses everything not named here rather than
# trying to blocklist what should never be exposed.
_ALLOWED_SUFFIXES = {".html", ".js", ".css", ".json", ".md"}


def _safe_path(relative: str) -> Path:
    """Resolve `relative` under WEB_DIR, refusing anything that escapes it
    (`../`, an absolute path, a symlink out) or that is not an allowlisted
    file type. Raises a structured 404 rather than ever touching a path
    outside web/ -- same "name what was searched for" shape as the game
    routes' unknown-game 404s (api/games.py, api/betcheck.py).
    """
    candidate = (WEB_DIR / relative).resolve()
    if WEB_DIR not in candidate.parents and candidate != WEB_DIR:
        raise HTTPException(status_code=404, detail=f"no such asset: {relative!r}")
    if candidate.suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=404, detail=f"no such asset: {relative!r}")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"no such asset: {relative!r}")
    return candidate


@router.get("/web")
@router.get("/web/")
def get_web_index() -> FileResponse:
    """The app shell -- GET /web or /web/ both serve web/index.html, the
    same "no trailing slash matters" convenience a static host gives for
    free."""
    return FileResponse(_safe_path("index.html"))


@router.get("/web/{path:path}")
def get_web_asset(path: str) -> FileResponse:
    """Any other file under web/ (web/js/*.js today; web/README.md is
    documentation, not fetched by the page itself, but stays reachable
    here too for a reviewer following a link)."""
    return FileResponse(_safe_path(path))
