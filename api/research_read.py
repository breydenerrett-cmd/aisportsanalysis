"""Read-only research feed for the owner's local tooling (owner ask 2026-10-28).

    GET /research/bets.jsonl    every bet of every hound and version, one JSON object per line (?hound_id=, ?since=YYYY-MM-DD)
    GET /research/hounds.json   every hound version: id, name, version_no, status, rule text, created/retired times

AUTH. Header ``X-Research-Token`` against the ``RESEARCH_READ_TOKEN`` env var (sha256 digests, constant-time compare). Env var
unset or empty = feature off. Off, missing token and wrong token all answer the same bare 404, so nothing reveals the route.
No owner emails or user ids leave here. Read-only; the header is never logged.
"""

from __future__ import annotations

import json
import re
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from src.appstate import ratelimit
from src.hounds import research_read as core

router = APIRouter()

READ_PER_MIN = 30
_limiter = ratelimit.FixedWindowLimiter(limit=READ_PER_MIN, window_s=60.0)
_rl = ratelimit.limiter_dependency(_limiter)
_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _gate(token: Optional[str]) -> None:
    if not core.token_ok(token):
        raise HTTPException(status_code=404, detail="Not Found")


def _lines(hound_id: Optional[str], since: Optional[str]) -> Iterator[bytes]:
    for row in core.bet_rows(hound_id=hound_id, since=since):
        yield (json.dumps(row, default=str, ensure_ascii=False) + "\n").encode("utf-8")


@router.get("/research/bets.jsonl")
def research_bets(hound_id: Optional[str] = Query(None, max_length=80), since: Optional[str] = Query(None),
                  x_research_token: Optional[str] = Header(default=None), _r: None = Depends(_rl)):
    _gate(x_research_token)
    if since is not None and not _DATE.match(since):
        raise HTTPException(status_code=422, detail="since must be YYYY-MM-DD")
    return StreamingResponse(_lines(hound_id, since), media_type="application/x-ndjson", headers=_HEADERS)


@router.get("/research/hounds.json")
def research_hounds(x_research_token: Optional[str] = Header(default=None), _r: None = Depends(_rl)):
    _gate(x_research_token)
    return JSONResponse({"hounds": core.hound_records()}, headers=_HEADERS)
