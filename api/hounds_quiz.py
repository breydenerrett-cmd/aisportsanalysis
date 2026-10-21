"""The hound quiz's two public doors (web/quiz.html, web/js/hound-quiz.js).

    GET  /hounds/quiz/library   every archetype with its exact spec fragment and its GENERATED English, plus the answer
                                tables (personalities, markets, price comforts, quirks, timings, looks) the quiz is drawn from
    POST /hounds/quiz/compose   {answers, english_draft?, english_text?} -> {spec, english, rule_cards, warnings, ...}
    POST /hounds/quiz/moves     {answers, page?} -> the four move cards on that page for the sports and answers so far
                                (name, one short line, sport badge, the full rule behind it); page + 1 is "Show me 4 others"
    POST /hounds/quiz/pick      {answers} -> the one move "Pick for me" takes

Both are public reads of a config file and pure functions: nothing is saved, no bet is placed, no hound is created. The spec
that comes back has already been through the real validator (`user_spec.validate_spec`); the page still sends it through
the usual save door (`POST /hounds`), which validates it again, so nothing here can reach the engine unchecked.

MOUNT ORDER. ``/hounds/quiz/...`` sits next to ``/hounds/{id}/...``; this router is mounted BEFORE api.hounds (api/app.py
does, and tests/test_hounds_quiz_api.py pins it).

Thin wiring: the logic is src/hounds/quiz (library, compose); this module adds rate limits and the paper-only wrapper.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.appstate import ratelimit
from src.hounds import user_spec, user_store
from src.hounds.english import parser as english_parser
from src.hounds.quiz import compose as quiz_compose
from src.hounds.quiz import library as quiz_library
from src.hounds.quiz import moves as quiz_moves

router = APIRouter()

PAPER = {"paper_only": True, "not_advice": user_spec.NOT_ADVICE}

# A visitor answering a quiz posts a handful of times; composing is cheap but still an open door.
_library_limiter = ratelimit.FixedWindowLimiter(limit=60, window_s=60.0)
_rl_library = ratelimit.limiter_dependency(_library_limiter)
_compose_limiter = ratelimit.FixedWindowLimiter(limit=45, window_s=60.0)
_rl_compose = ratelimit.limiter_dependency(_compose_limiter)
_moves_limiter = ratelimit.FixedWindowLimiter(limit=60, window_s=60.0)
_rl_moves = ratelimit.limiter_dependency(_moves_limiter)


class MovesRequest(BaseModel):
    answers: Dict[str, Any] = {}
    page: int = 0


class ComposeRequest(BaseModel):
    answers: Dict[str, Any] = {}
    english_draft: Optional[Dict[str, Any]] = None
    english_text: Optional[str] = None


def _taken_names() -> list:
    """Names already used by a hound, so a suggestion is never one that would be refused. A store that cannot be
    read means no filter, not a failed quiz: the save door still refuses a taken name."""
    try:
        return list(user_store.taken_names())
    except Exception:  # noqa: BLE001
        return []


@router.get("/hounds/quiz/library")
def quiz_library_read(response: Response, _rl: None = Depends(_rl_library)) -> dict:
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        out = quiz_library.public_library()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail={"error": "library_unavailable", "message": type(exc).__name__})
    out.update(PAPER)
    return out


@router.post("/hounds/quiz/compose")
def quiz_compose_answers(body: ComposeRequest, response: Response, _rl: None = Depends(_rl_compose)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    text = body.english_text
    if text is not None and len(text) > english_parser.MAX_TEXT:
        raise HTTPException(status_code=422, detail={"error": "text_too_long", "max": english_parser.MAX_TEXT})
    try:
        out = quiz_compose.compose(body.answers, taken_names=_taken_names(), english_draft=body.english_draft,
                                   english_text=text)
    except user_spec.SpecError as exc:
        raise HTTPException(status_code=422, detail={"error": "spec_invalid", "message": "the quiz could not compose a "
                                                     "valid hound from that", "fields": exc.errors})
    out.update(PAPER)
    return out


@router.post("/hounds/quiz/moves")
def quiz_moves_page(body: MovesRequest, response: Response, _rl: None = Depends(_rl_moves)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    out = quiz_moves.suggest(body.answers, page=max(0, min(body.page, 1000)))
    out.update(PAPER)
    return out


@router.post("/hounds/quiz/pick")
def quiz_pick_for_me(body: MovesRequest, response: Response, _rl: None = Depends(_rl_moves)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    out = quiz_moves.pick_for_me(body.answers)
    out.update(PAPER)
    return out
