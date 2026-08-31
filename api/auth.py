"""Bearer-token auth for the api/ layer, built on src.appstate.users.

Same api/<->src/ boundary as api/today.py: this module imports FROM
src.appstate.users, never the reverse, and nothing in src/ knows FastAPI
exists (tests/test_api_boundary.py enforces the stdlib-only import for all
of src/).

No password auth, no session cookies -- invite tokens only (see
src/appstate/users.py's module docstring for why). `get_current_user` is a
FastAPI dependency: attach it to any endpoint that needs an authed user
and a missing/invalid/expired/revoked token becomes a structured 401
before the endpoint body ever runs.

ADMIN INVITE ENDPOINT: gated by APP_ADMIN_TOKEN. Absent env var means the
endpoint is DISABLED (404), not "open with no check" -- an admin surface
that silently accepts every request the moment someone forgets to set an
env var is worse than one that doesn't exist yet.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from src.appstate import users as users_store

ENV_ADMIN_TOKEN = "APP_ADMIN_TOKEN"

router = APIRouter()


def _unauthorized(detail: str) -> HTTPException:
    """One shape for every 401 this module raises -- a caller parses one
    structure, not several ad hoc ones."""
    return HTTPException(status_code=401, detail={"error": "unauthorized", "message": detail})


def get_current_user(authorization: Optional[str] = Header(default=None)) -> users_store.User:
    """FastAPI dependency: resolve `Authorization: Bearer <token>` to a
    User, or raise a structured 401. Never logs the header value -- the
    raw token must not end up anywhere but this one comparison (see
    src/appstate/users.py's hashing rationale).
    """
    if not authorization:
        raise _unauthorized("missing Authorization header")
    scheme, _, raw_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not raw_token:
        raise _unauthorized("expected 'Authorization: Bearer <token>'")
    user = users_store.authenticate(raw_token)
    if user is None:
        raise _unauthorized("invalid, expired, or revoked token")
    if user.status == "suspended":
        raise _unauthorized("account suspended")
    return user


def _require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """Guards the invite-creation endpoint. Absent APP_ADMIN_TOKEN means
    the endpoint is disabled outright (404) -- see module docstring."""
    configured = (os.environ.get(ENV_ADMIN_TOKEN) or "").strip()
    if not configured:
        raise HTTPException(status_code=404, detail="not found")
    if not x_admin_token or x_admin_token != configured:
        raise _unauthorized("invalid admin token")


@router.post("/admin/invites")
def create_invite(email: str, _admin: None = Depends(_require_admin)) -> dict:
    """Create (or reuse) a user by email and issue a fresh invite token.

    Returns the RAW token exactly once, in this response -- it is not
    retrievable again afterward (src/appstate/users.py stores only the
    hash). Losing it means issuing a new one, same as any bearer-token
    invite flow.
    """
    user = users_store.get_user_by_email(email)
    if user is None:
        user = users_store.create_user(email, status="invited", plan="none")
    raw_token = users_store.issue_invite_token(user.id)
    return {"user_id": user.id, "email": user.email, "token": raw_token}
