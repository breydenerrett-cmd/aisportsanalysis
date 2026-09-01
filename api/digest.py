"""GET /digest: the authed user's daily digest -- their saved bets'
settlement outcomes since their last digest, tonight's slate summary, the
notable subset of tonight's What Changed band, and one price-improvement
observation if the board has one.

Same wiring split as api/today.py and api/games.py: the real domain path
(mlb.fetch_games -> history.read_results -> briefing.build_slate) runs
here, and src.analysis.digest.build_user_digest -- pure, stdlib, testable
without FastAPI or a network -- turns the result plus this user's own state
into the digest shape. This file only fetches inputs and glues them
together; nothing here re-derives a number the domain layer or
src.analysis.digest already computed.

WHY NO CACHE, UNLIKE /games AND /today
-----------------------------------------
api/games.py and api/today.py cache the slate build because many different
users hit the SAME (date) key inside the same short window -- caching there
absorbs a shared traffic burst. /digest is a personal, roughly-once-a-day
read scoped to one user; there is no shared key for a cache to help with,
so this route rebuilds the slate on every call rather than growing a cache
for a read this infrequent. (A future version could share api/games.py's
`_entries_cache` if /digest traffic ever justified it -- not needed today.)

WHY "SINCE LAST DIGEST" IS READ BEFORE THE NEW EVENT IS RECORDED
--------------------------------------------------------------------
`events.latest_event` is called BEFORE `events.record_event_safe` writes
this request's own DIGEST_VIEWED row -- reversing that order would make
every digest see itself as its own most-recent previous digest, collapsing
`since_last_digest` to "now" and reporting zero settled bets forever. See
src/analysis/digest.py's module docstring for what `since_last_digest`
means to the digest itself.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from src.analysis import digest as digest_mod
from src.appstate import events, savedbets
from src.appstate.users import User
from src.pipeline import briefing, history
from src.providers import mlb

from api.auth import get_current_user

router = APIRouter()


def _build_tonight(date: str) -> tuple:
    """(entries, notes) for `date`, through the real domain path -- the
    same fetch-then-build-slate pair api/today.py's `_build` closure and
    api/games.py's `_rebuild` closure each perform for their own routes.
    Raises HTTPException(502) on an unreachable schedule provider, the same
    structured-error shape every other route in this package already uses.
    """
    try:
        games = mlb.fetch_games(date)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502,
                            detail=f"schedule unavailable for {date}: {exc}")
    store = history.read_results()
    slate = briefing.build_slate(games, store)
    return slate["games"], slate.get("notes", [])


@router.get("/digest")
def get_digest(current_user: User = Depends(get_current_user)) -> dict:
    """Today's digest for the authed user. Always today's date -- a digest
    is inherently "as of now", the same way GET /today is; there is no
    historical-digest replay endpoint."""
    today = date_cls.today().isoformat()
    now = datetime.now(timezone.utc)
    entries, notes = _build_tonight(today)

    saved_bets = savedbets.list_bets(current_user.id)
    user_hash = events.hash_user_id(current_user.id)
    previous = events.latest_event(user_hash, events.DIGEST_VIEWED)
    since_last_digest = previous.at if previous is not None else None

    payload = digest_mod.build_user_digest(
        current_user.id, today, entries=entries, saved_bets=saved_bets,
        notes=notes, since_last_digest=since_last_digest, now=now)

    # Recorded AFTER the read above, and after the payload is built (so a
    # broken events db costs one missing data point, never this response --
    # events.record_event_safe's own "never raise" contract) -- see the
    # module docstring's ordering note.
    events.record_event_safe(current_user.id, events.DIGEST_VIEWED,
                             {"date": today}, at=now.isoformat())
    return payload
