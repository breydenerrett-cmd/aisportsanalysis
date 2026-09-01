"""api/onboarding.py: GET /onboarding -- the authed caller's onboarding
checklist, so a future UI can render "3 of 4 done" without touching
analytics_events itself.

Thin wiring over src.appstate.onboarding -- see that module's docstring
for why every step here is derived from an existing analytics event
rather than a separately-written flag.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.appstate import onboarding
from src.appstate.users import User

from api.auth import get_current_user

router = APIRouter()


@router.get("/onboarding")
def get_onboarding(current_user: User = Depends(get_current_user)) -> dict:
    state = onboarding.get_onboarding_state(current_user.id)
    return {
        "steps": {
            step: {"complete": status.complete, "completed_at": status.completed_at}
            for step, status in state.steps.items()
        },
        "complete": state.complete,
    }
