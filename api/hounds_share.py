"""GET /d/{hound_id} -- the link to share a dog.

A small HTML page whose ``<meta>`` tags (Open Graph and Twitter) name the dog, its record and its
catchphrase, so a link pasted in a chat or a feed unfurls as that dog; a browser is sent straight on to
``/web/hound.html?id=<id>`` (src/hounds/share_page.py holds the page and the reasons).

MOUNT ORDER. api/app.py mounts this router right after /health, before any router that could claim a
``/d/...`` path (nothing does today; the order is pinned by a test so a later catch-all cannot swallow it).

NO REQUEST WAITS FOR A BUILD: the dog comes from the cached stats book if there is one, else the saved
public copy, else the shipped config (a house dog's name and catchphrase), else the page says the kennel
is waking up (503, not cached) rather than call a real dog unknown.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.hounds import share_page

router = APIRouter()

_CACHE = "public, max-age=300"
_NO_STORE = "no-store"


@router.get("/d/{hound_id}", include_in_schema=False)
def shared_dog(hound_id: str) -> HTMLResponse:
    state, info = share_page.lookup(hound_id)
    if state == share_page.STATE_OK and info is not None:
        return HTMLResponse(share_page.render_dog(hound_id, info), headers={"Cache-Control": _CACHE})
    if state == share_page.STATE_WARMING:
        return HTMLResponse(share_page.render_warming(), status_code=503, headers={"Cache-Control": _NO_STORE})
    return HTMLResponse(share_page.render_not_found(hound_id), status_code=404, headers={"Cache-Control": _NO_STORE})
