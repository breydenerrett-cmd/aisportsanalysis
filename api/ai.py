"""GET /admin/ai/status: the AI layer's one status panel, behind the admin token.

    {switch: {env AI_HOUNDS, on}, router: {providers: [{id, model, enabled, disabled_reason, usable_now,
     calls_today, daily_cap, cooldown_until, month_spend_usd...}], paid: {cap_usd, spend_usd, remaining_usd,
     cap_reached}, degraded, last_errors: [...]}, runner: {last pass and its report}, hounds, ledger: {bets,
     graded, decisions_today...}, postmortems: {the hindsight reviews' month wall and queue, and the one-time backfill's progress:
     backfill: {on, cap_usd, spent_usd, reserved_usd, bets: {done, queued, remaining}, lineage_reviews: {...}}}}

Read-only, and it reads files only (the usage meter, the AI ledgers): it never calls a model, so refreshing it
costs nothing. Same gate as every other admin route (``api.auth._require_admin``: 404 when no admin token is
configured, 401 on a wrong one). No key appears in the payload, only whether one is set. The logic is in
``src/hounds/ai_runner.build_status`` (importable without FastAPI, which is where it is tested).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import _require_admin
from src.ai import postmortems
from src.hounds import ai_runner

router = APIRouter()


@router.get("/admin/ai/status")
def get_ai_status(_admin: None = Depends(_require_admin)) -> dict:
    out = ai_runner.build_status()
    out["postmortems"] = postmortems.status_safely()          # never raises, reads files only, calls no model
    return out
