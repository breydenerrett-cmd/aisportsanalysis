"""GET /health -- process + store liveness, no auth, no secrets.

Same api/<->src/ split as every other router here: src/appstate/apphealth.py
owns the actual checks (db reachability, store freshness) as plain stdlib
logic; this file only mounts it as a route and lets an unexpected exception
in the check itself still come back as a *response* rather than a crashed
process -- the one endpoint a host's uptime checker hits is also the one
endpoint that must never itself 500 the way a normal route is allowed to
(see api/app.py's structured-500 handler for every other route).

No auth: an uptime checker, a load balancer, or Brey debugging a deploy from
a phone must be able to hit this with no bearer token. That is also why
src/appstate/apphealth.report() is built to never put a token, email, or
row body in its output -- see that module's docstring.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from src.appstate import apphealth

router = APIRouter()


@router.get("/health")
def get_health(response: Response) -> dict:
    """Structured health payload; HTTP status mirrors the payload's own
    `status` field (200 when ok, 503 when degraded) so a plain uptime
    checker that only looks at the status code still gets the right
    answer without parsing JSON.
    """
    try:
        data = apphealth.report()
    except Exception as exc:  # noqa: BLE001 -- see module docstring
        response.status_code = 503
        return {"status": "degraded", "reasons": [f"health check itself failed: {exc}"]}
    if data["status"] != "ok":
        response.status_code = 503
    return data
