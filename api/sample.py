"""The public sample brief: ONE designated game's supervised-session analysis, free to read.

    GET /sample/brief    PUBLIC, rate-limited like /analyst/record

WHY IT EXISTS
-------------
Outreach needs one real brief a stranger can read without an account: the same analysis, the same
reasons, the same case against and the same grade the paid pages show, for one game, labelled as
what it is (written in a supervised session, unproven). The analyst's own routes are gated and the
record route never serves an unsettled game's calls, so this is the single, narrow exception.

WHAT IT SERVES, AND ONLY THAT
-----------------------------
`config/sample_brief.json` names the game: `{"date": "2026-10-03", "away": "NYY", "home": "TB"}`, or
`null` for no sample. The route serves that game's row from the PILOT ledger and nothing else: no
query parameter picks a game, no other game can be reached, and the main (API) ledger is never read.
When the file says null, names a game with no pilot row, or is malformed, the answer is
`available: false` with a plain reason, never an error and never a different game. The owner changes
the sample by editing one small file that ships in the image (`config/` is copied by
deploy/Dockerfile); the pilot's rows ship the same way (`evidence/`).

THE ANALYSIS IS THE FROZEN ROW. The route never calls a model, computes no price and re-derives
nothing; a page view cannot spend a cent or change what was published.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends

from api import analyst as analyst_api
from src.analyst import PILOT_LABEL
from src.appstate import ratelimit
from src.paths import repo_root

public_router = APIRouter()

CONFIG_PATH = "config/sample_brief.json"
PUBLIC_RATE_LIMIT_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=PUBLIC_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit = ratelimit.limiter_dependency(_limiter)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TEAM = re.compile(r"^[A-Za-z]{2,4}$")

NONE_YET = "There is no sample brief to show right now."


def designated() -> Optional[dict]:
    """The game `config/sample_brief.json` names, or None (no file, null, or anything malformed)."""
    try:
        with open(repo_root() / CONFIG_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    date, away, home = raw.get("date"), raw.get("away"), raw.get("home")
    if not (isinstance(date, str) and _ISO_DATE.match(date) and isinstance(away, str)
            and isinstance(home, str) and _TEAM.match(away) and _TEAM.match(home)):
        return None
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None
    return {"date": date, "away": away.upper(), "home": home.upper()}


def _unavailable() -> dict:
    return {"available": False, "label": PILOT_LABEL, "analysis": None, "reason": NONE_YET,
            "first_pitch_utc": None, "published_utc": None}


@public_router.get("/sample/brief", dependencies=[Depends(_rate_limit)])
def get_sample_brief() -> dict:
    """The designated game's pilot analysis, with its grade once graded, or `available: false`."""
    game = designated()
    if game is None:
        return _unavailable()
    view = analyst_api.pilot_view(game["date"], game["away"], game["home"])
    if view is None:
        return _unavailable()
    return {"available": True, "label": PILOT_LABEL, "analysis": view, "reason": None,
            "first_pitch_utc": view["first_pitch_utc"], "published_utc": view["published_utc"]}
