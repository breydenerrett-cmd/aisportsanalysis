"""GET /d/{hound_id} -- the link to share a dog.

A small HTML page whose ``<meta>`` tags (Open Graph and Twitter) name the dog, its record and its
catchphrase, so a link pasted in a chat or a feed unfurls as that dog; a browser is sent straight on to
``/web/hound.html?id=<id>`` (src/hounds/share_page.py holds the page and the reasons).

MOUNT ORDER. api/app.py mounts this router right after /health, before any router that could claim a
``/d/...`` path (nothing does today; the order is pinned by a test so a later catch-all cannot swallow it).

NO REQUEST WAITS FOR A BUILD: the dog comes from the cached stats book if there is one, else the saved
public copy, else the shipped config (a house dog's name and catchphrase), else the page says the kennel
is waking up (503, not cached) rather than call a real dog unknown.

GET /d/{hound_id}/card.png is the picture those tags point at (src/hounds/share_card.py decides what it says,
share_render.py draws it): 1200x630, public dogs only. A retired, unknown or not-yet-loaded dog gets the GENERIC card
(the brand, no numbers), never a 404, so a pasted link never unfurls as a broken image. The picture is cached by the
hash of what it says: that hash is the ETag, a matching ``If-None-Match`` is a 304, and the page links
``card.png?v=<hash>`` so a changed record is a new URL. A matching ``?v=`` is cached for a day, anything else for
five minutes (a dog can retire; its old URL should not outlive that by a year). Pillow missing: 503, not a broken image.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from src.hounds import share_card, share_page

router = APIRouter()

_CACHE = "public, max-age=300"
_NO_STORE = "no-store"
_CARD_MATCHED = "public, max-age=86400"       # ?v= equals the current hash: the bytes cannot change under that URL
_CARD_UNMATCHED = "public, max-age=300"
_CARD_WARMING = "public, max-age=30"


@router.get("/d/{hound_id}", include_in_schema=False)
def shared_dog(hound_id: str) -> HTMLResponse:
    state, info = share_page.lookup(hound_id)
    if state == share_page.STATE_OK and info is not None:
        return HTMLResponse(share_page.render_dog(hound_id, info), headers={"Cache-Control": _CACHE})
    if state == share_page.STATE_WARMING:
        return HTMLResponse(share_page.render_warming(), status_code=503, headers={"Cache-Control": _NO_STORE})
    return HTMLResponse(share_page.render_not_found(hound_id), status_code=404, headers={"Cache-Control": _NO_STORE})


@router.get("/d/{hound_id}/card.png", include_in_schema=False)
def shared_dog_card(hound_id: str, request: Request, v: Optional[str] = None) -> Response:
    spec = share_card.spec_for(hound_id)
    digest = spec.digest()
    etag = f'"{digest}"'
    if spec.reason == share_card.REASON_WARMING:
        control = _CARD_WARMING
    else:
        control = _CARD_MATCHED if v == digest else _CARD_UNMATCHED
    headers = {"ETag": etag, "Cache-Control": control}
    if etag in [t.strip() for t in (request.headers.get("if-none-match") or "").split(",")]:
        return Response(status_code=304, headers=headers)
    try:
        png = share_card.png_for(spec)
    except share_card.RenderUnavailable:
        return Response("picture unavailable", status_code=503, media_type="text/plain", headers={"Cache-Control": _NO_STORE})
    return Response(png, media_type="image/png", headers=headers)
