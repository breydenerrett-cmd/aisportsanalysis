"""Per-user onboarding-checklist state, derived from analytics events.

WHY THIS MODULE STORES NOTHING OF ITS OWN
--------------------------------------------
The brief for this asks for four steps -- token_redeemed, first_today_view,
first_bet_check, first_saved_bet -- "derived from analytics events where
possible, stored where not". It turns out all four already have an exact,
unambiguous analytics_events row the moment they happen:

    token_redeemed     -> events.INVITE_REDEEMED   (api/auth.py, exactly once
                                                      per token)
    first_today_view   -> events.PAGE_VIEW with properties.route == "/today"
                           (api/today.py's get_today_payload_cached)
    first_bet_check    -> events.BET_CHECK_RUN     (api/betcheck.py, success
                                                      only)
    first_saved_bet    -> events.BET_SAVED         (api/mybets.py, success
                                                      only)

`properties.route` is what makes first_today_view honest rather than a
guess: PAGE_VIEW also fires for /games, /game/{date}/{away}/{home}, and
/changed/{date} (api/games.py's own `_record_page_view`), each tagged with
its own `route` string -- so this module checks that field rather than
treating "any page view happened" as "the user has seen Today", which
would have been true the moment they hit any other view instead.

Because every step already has a real event, this module is a pure read
+ aggregation layer over `events.list_events()` -- it never writes to the
app db itself. If a future onboarding step has no natural analytics event
(the "stored where not" half of the brief), that step earns its own
written column here; none of the current four need one, and inventing a
duplicate written flag for something an event already proves would be the
same "two sources of truth that can drift" problem
src/appstate/events.py's WHY THE USER ID IS HASHED section warns against
in a different shape.

WHY "COMPLETE" MEANS "THE EVENT ACTUALLY EXISTS", NEVER A GUESS
--------------------------------------------------------------------
A step's `completed_at` is the timestamp of the EARLIEST matching event
for that user, or None if no matching event exists yet. There is no
"assume complete because the user is old" or "assume complete because
this is a v1 user seeded before analytics existed" shortcut -- an absent
event means the step reports incomplete, full stop, the same "None over a
guess" rule this program applies everywhere else (src/paths.py's evidence
handling, apphealth.py's honesty rule). A future UI checklist that shows a
step as done because of this module is showing something that is
factually true, not inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from src.appstate import events

TOKEN_REDEEMED = "token_redeemed"
FIRST_TODAY_VIEW = "first_today_view"
FIRST_BET_CHECK = "first_bet_check"
FIRST_SAVED_BET = "first_saved_bet"

# Order matters for a future checklist UI: the natural sequence a new user
# walks through, invite to first saved bet. Not enforced (a user can run a
# bet check before ever loading Today), just the display order.
STEPS = (TOKEN_REDEEMED, FIRST_TODAY_VIEW, FIRST_BET_CHECK, FIRST_SAVED_BET)

# route string api/today.py tags its PAGE_VIEW events with -- see module
# docstring for why this, not "any page_view", is what first_today_view
# checks.
_TODAY_ROUTE = "/today"


@dataclass(frozen=True)
class StepStatus:
    complete: bool
    completed_at: Optional[str]  # ISO-8601 UTC, None iff not complete


@dataclass(frozen=True)
class OnboardingState:
    user_id: int
    steps: Dict[str, StepStatus]

    @property
    def complete(self) -> bool:
        """True once every step in STEPS has a StepStatus.complete -- the
        whole checklist finished, not just the last step reached (a user
        could in principle hit first_bet_check before first_today_view)."""
        return all(self.steps[step].complete for step in STEPS)


def get_onboarding_state(user_id: int, *, db: Optional[Path] = None) -> OnboardingState:
    """This user's onboarding checklist, each step's completion derived
    from the earliest matching analytics event -- see module docstring.

    Scans the whole analytics_events table via `events.list_events()` and
    filters in Python, the same "small table, plain Python beats a second
    SQL dialect" call `events.daily_counts_by_kind` already makes for the
    identical table, for the identical reason (see that function's own
    docstring) -- this is not a hot path (one call per GET /onboarding).
    """
    user_hash = events.hash_user_id(user_id)
    earliest_at: Dict[str, str] = {}
    for event in events.list_events(db=db):
        if event.user_hash != user_hash:
            continue
        step = _step_for_event(event)
        if step is None:
            continue
        # list_events() is oldest-first (see its own docstring), so the
        # first match encountered per step is already the earliest one --
        # a later match for the same step is never kept over it.
        if step not in earliest_at:
            earliest_at[step] = event.at
    steps = {
        step: StepStatus(complete=step in earliest_at,
                         completed_at=earliest_at.get(step))
        for step in STEPS
    }
    return OnboardingState(user_id=user_id, steps=steps)


def _step_for_event(event: events.AnalyticsEvent) -> Optional[str]:
    """Which onboarding step (if any) `event` satisfies. Returns None for
    every event kind/shape that isn't one of the four tracked steps --
    most events in the table (page views of /games, /game, /changed) map
    to nothing here, which is correct: they are real product usage that
    this checklist simply does not track."""
    if event.kind == events.INVITE_REDEEMED:
        return TOKEN_REDEEMED
    if event.kind == events.PAGE_VIEW and event.properties.get("route") == _TODAY_ROUTE:
        return FIRST_TODAY_VIEW
    if event.kind == events.BET_CHECK_RUN:
        return FIRST_BET_CHECK
    if event.kind == events.BET_SAVED:
        return FIRST_SAVED_BET
    return None
