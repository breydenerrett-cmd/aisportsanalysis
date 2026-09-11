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
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = (REPO_ROOT / "web").resolve()

# Extension allowlist: this client ships only these file types (see
# web/README.md's file list). A `.py`, `.env`, or dotfile dropped into
# web/ by mistake must never become servable just by matching a path
# pattern -- an allowlist refuses everything not named here rather than
# trying to blocklist what should never be exposed.
# Extended 2026-09-10 for the installable-app surface. The allowlist is a
# real defence -- it is what stops a traversal or a stray file type being
# served out of web/ -- so this grew by exactly what a web manifest and its
# icons need and nothing else:
#
#   .webmanifest  the manifest itself
#   .png          the icon set (scripts/make_icons.py generates it)
#   .svg, .ico    favicons, which browsers request whether or not we ship
#                 them; serving a real one beats a 404 on every page load
#
# Still refused, deliberately: everything executable or archival, anything
# that could carry a payload a browser would run. If a future asset type
# needs adding, add the ONE suffix, not a wildcard.
_ALLOWED_SUFFIXES = {".html", ".js", ".css", ".json", ".md",
                     ".webmanifest", ".png", ".svg", ".ico"}


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


@router.get("/web", include_in_schema=False)
def get_web_index_no_slash() -> RedirectResponse:
    """`/web` (no slash) REDIRECTS to `/web/` rather than serving the
    shell in place: index.html's css/js are relative paths, and served at
    `/web` they resolve to `/css/...` and 404 -- a blank page with only the
    wordmark (linehound-staging, 2026-09-07). The redirect moves the
    browser's base URL, which is what those paths depend on."""
    return RedirectResponse(url="/web/", status_code=307)


# REVALIDATE EVERY TIME (2026-09-07). Without an explicit policy the browser
# heuristically caches js/css off Last-Modified and served a stale
# web/js/motion.js next to freshly deployed HTML. `no-cache` means "ask
# before reusing", not "never store": FileResponse's ETag/Last-Modified
# make that a cheap 304 on every unchanged asset, and a redeploy is picked
# up on the next load instead of whenever the heuristic expires.
#
# THE SHELL KEEPS THAT RULE. It is one request, it decides the route table,
# and it must never be a version behind.
_SHELL_HEADERS = {"Cache-Control": "no-cache"}

# EVERYTHING ELSE GETS A SHORT WINDOW (2026-09-10), and the reason is
# measured. This app has no build step, so the page loads roughly thirty
# separate ES module files plus its stylesheets. Under `no-cache` the
# browser must revalidate every one of them on every load: thirty
# conditional requests, served one at a time by a single shared CPU, before
# any JavaScript runs at all. On the staging container the first API call
# did not fire until 2.9 SECONDS after navigation, and every one of those
# API calls then returned in about 150ms. The page was not waiting on data.
# It was waiting to be allowed to ask for it.
#
# Thirty seconds is deliberately short. The failure the rule above exists to
# prevent -- fresh shell, stale module -- is now possible only for a reader
# who loads the page during the thirty seconds after a deploy, rather than
# impossible; that is a real and stated cost, taken because a three-second
# blank screen on EVERY load is the larger harm to a reader who is deciding
# whether this product is worth anything.
#
# The right fix is fingerprinted asset URLs, which needs a build step this
# repo has deliberately not taken on. If one ever lands, this becomes
# `immutable` and the window closes entirely.
_ASSET_MAX_AGE_S = 30
_ASSET_HEADERS = {"Cache-Control": f"public, max-age={_ASSET_MAX_AGE_S}"}


@router.get("/web/")
def get_web_index() -> FileResponse:
    """The app shell -- GET /web/ serves web/index.html."""
    return FileResponse(_safe_path("index.html"), headers=_SHELL_HEADERS)


@router.get("/web/{path:path}")
def get_web_asset(path: str) -> FileResponse:
    """Any other file under web/ (web/js/*.js today; web/README.md is
    documentation, not fetched by the page itself, but stays reachable
    here too for a reviewer following a link).

    HTML under web/ is a shell too -- landing.html is a whole page, not an
    asset -- so it takes the shell's revalidate-every-time rule rather than
    the short window the modules get.
    """
    headers = (_SHELL_HEADERS if path.lower().endswith(".html")
               else _ASSET_HEADERS)
    return FileResponse(_safe_path(path), headers=headers)
