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

# When this process started, as near as this module can know it (it is
# imported while the app is being built). A restart shows as a new value.
_PROCESS_STARTED = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)


def _memory_mb() -> dict:
    """Resident memory now and its high-water mark, in MB, from
    /proc/self/status (Linux). None on a platform without it. Reading one
    small pseudo-file keeps /health cheap."""
    out = {"rss_mb": None, "peak_rss_mb": None}
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = round(int(line.split()[1]) / 1024.0, 1)
                elif line.startswith("VmHWM:"):
                    out["peak_rss_mb"] = round(int(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    return out


def runtime() -> dict:
    """Uptime, memory and how many cache builds have run at once.

    Added 2026-10-01 after production was found restarting for lack of memory
    every eleven minutes with nothing on /health to show it: the deploy check
    saw a healthy process each time because it was always a NEW process.
    `started_utc` changing between two reads is a restart; `peak_rss_mb` is the
    number to hold against the machine size; `builds.max_running` must be 1."""
    from datetime import datetime, timezone
    from src.appstate import freshness
    now = datetime.now(timezone.utc)
    return {"started_utc": _PROCESS_STARTED.isoformat(),
            "uptime_s": int((now - _PROCESS_STARTED).total_seconds()),
            **_memory_mb(),
            "builds": freshness.build_stats()}


def _only_checkout_is_broken(data: dict) -> bool:
    """True when the report is degraded for one reason only: billing is
    switched on and cannot sell.

    That state stays "degraded" in the payload, where the operator and the
    deploy workflow read it. It must not become a 503, because the 503 is
    what Fly's health check routes on: a 503 here takes the WHOLE site out
    of rotation, record page and existing subscribers included, over a
    missing billing setting. Checkout already refuses on its own in that
    state (src.appstate.billing.checkout_not_ready_reason), so nothing is
    sold; the rest of the site has no reason to go dark with it."""
    reasons = data.get("reasons") or []
    return bool(reasons) and all(str(r).startswith("checkout:") for r in reasons)


@router.get("/health")
def get_health(response: Response) -> dict:
    """Structured health payload; HTTP status mirrors the payload's own
    `status` field (200 when ok, 503 when degraded) so a plain uptime
    checker that only looks at the status code still gets the right
    answer without parsing JSON. One exception: see
    `_only_checkout_is_broken`.
    """
    try:
        data = apphealth.report()
    except Exception as exc:  # noqa: BLE001 -- see module docstring
        response.status_code = 503
        return {"status": "degraded", "reasons": [f"health check itself failed: {exc}"]}
    if data["status"] != "ok" and not _only_checkout_is_broken(data):
        response.status_code = 503
    # Warm-up progress (api/warmup.py). Informational only: it never changes
    # `status`, because a cold cache is slow, not unhealthy. Deploy checks
    # read `passes_completed` to wait before exercising pages.
    from api import warmup
    data["warmup"] = warmup.status()
    try:
        data["runtime"] = runtime()
    except Exception:  # noqa: BLE001 -- informational; never the reason /health fails
        data["runtime"] = None
    return data
