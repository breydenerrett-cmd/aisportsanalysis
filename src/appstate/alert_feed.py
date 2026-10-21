"""Operator alerts for the owner, as events a Zap can poll (``GET /feeds/alerts.rss``).

THE POINT IS TO COST NOTHING WHEN NOTHING IS WRONG. A Zap that polls this feed spends no task until an
item appears, and the feed is EMPTY (valid RSS, no ``item``) while the site is healthy. When something
is wrong the Zap fires once per incident, not once per poll:

  * one item per (alert kind, UTC date): the ``guid`` is ``alert:<kind>:<YYYY-MM-DD>``, the same on every
    poll that day, so the same incident does not re-fire every fifteen minutes. If it is still broken
    tomorrow it is a NEW item, which is the reminder the owner wants;
  * ``pubDate`` is a fact about the incident (when the odds crossed the limit, when the loop paused),
    else the start of the UTC day. Never "now", so two polls are byte-identical.

WHAT RAISES AN ALERT. THE LIMITS ARE NOT HERE: every store's limit lives in
``src/pipeline/freshness_policy.py`` and ``apphealth.report()["freshness"]`` carries the verdicts; this module
only turns a verdict into an item. (Before 2026-10-19 this file held its own odds limit and the admin page
another; a finished audit read red on one and nothing on the other.)

  health_<what>     a reason in ``apphealth.report()["reasons"]`` (database unreachable, a store that
                    cannot be read, checkout broken). The same words ``GET /health`` already shows.
  odds_stale / odds_missing      the multi-book odds store past its limit, or absent / empty.
  store_stale_<store> / store_missing_<store>     any other forward-capture store the policy EXPECTS to be
                    moving today and finds past its limit (prop prices, lineups, ...). A store that is out of
                    season, has no game today, or is a finished audit is "not expected" and never alerts.
  data_stale_<store>  a store the computed pages read is past its own tolerance. One item per store.
  deploy_stale      the running process is older than ``freshness_policy.DEPLOY_STALE_HOURS`` (3): production
                    redeploys hourly when CI is green, so an old process means redeploys stopped.
  learning_paused   the learning loop paused itself (src/hounds/learning/pause.py): it stopped because
                    it could not show it was helping, and only the owner can resume it.

Every item says what happened AND what to do: its description is "<what>. Fix: <one line>".

NOT HERE, BECAUSE A FEED MUST ANSWER FROM MEMORY: whether CI on the working branch is red, whether a deploy is
stuck, whether capture has stopped. Those are GitHub calls, so the watchdog (src/ops/watchdog.py, every ten minutes,
in its own daemon thread) makes them, keeps its incidents in a small state file, and hands the feed the finished
items through ``collect(extra=...)``. They carry a guid per INCIDENT (not per UTC day) plus a "Resolved" item when
one clears. Without the watchdog a red CI shows up only as ``deploy_stale``; the digest's "not checked" list says
so.

NOT HERE, ON PURPOSE: "the house pack recorded zero bets for today's slate by 21:00 UTC". Whether a day
HAS games is not known without loading the hounds' stores (``pack.base.load_stores``: the whole multi-book
odds file, seconds and hundreds of MB) and a pack hound passing on every game is legitimate, so a cheap
version of the check would page the owner on every quiet day. It needs the schedule, not the ledger.

WHAT NEVER APPEARS: a secret, an email, a token, a row body, a file path. Descriptions say what to look at
(``GET /health``, a named store) and quote only the health check's own reason text, trimmed.

Stdlib only; the report and the pause facts come in as arguments (``api/feeds.py`` gathers them).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional

from src.hounds import rss
from src.hounds.kennel_feed import site_base_url
from src.pipeline import freshness_policy

ODDS_STALE_HOURS = freshness_policy.ODDS_STALE_HOURS      # re-exported; the number lives in the policy
REASON_MAX_CHARS = 200

KIND_ODDS_STALE = "odds_stale"
KIND_ODDS_MISSING = "odds_missing"
KIND_DATA_STALE = "data_stale"
KIND_DEPLOY_STALE = "deploy_stale"
KIND_LEARNING_PAUSED = "learning_paused"
KIND_HEALTH_CHECK_FAILED = "health_check_failed"

ADMIN_HEALTH_URL = "https://linehound.app/admin.html#/health"


# What a health reason may carry that a public feed must not: a file path (it names the host's layout), an email
# address, a long token-like run (an API key or a bearer token that leaked into an exception message).
_PATH = re.compile(r"(?:[A-Za-z]:[\\/][^\s'\"]*|(?<![\w:])/(?:[\w.\-]+/)+[\w.\-]*)")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def scrub(text) -> str:
    """Health-check text made safe for a public feed: paths, emails and token-like runs replaced, then
    trimmed. The check's own words stay; what could identify the host or leak a credential does not."""
    out = _PATH.sub("[path]", rss.clean(text))
    out = _EMAIL.sub("[email]", out)
    out = _TOKEN.sub("[redacted]", out)
    return out[:REASON_MAX_CHARS]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "unknown"


def _alert(kind: str, title: str, what: str, fix: str, pub: datetime) -> dict:
    what = rss.clean(what).rstrip()
    fix = rss.clean(fix).strip().rstrip(".")
    sentence = what if what.endswith((".", "!", "?")) else what + "."
    return {"kind": kind, "title": title, "what": what, "fix": fix, "pub": pub,
            "description": f"{sentence} Fix: {fix}."}


def _health_reason_alert(reason: str, day_start: datetime) -> dict:
    text = scrub(reason)
    head = text.split(":", 1)[0]
    head_slug = _slug(head)
    if head_slug.startswith("app_db"):
        title = "The app database is unreachable"
        fix = "check the volume and the machine on Fly, then redeploy; GET /health shows the reason"
    elif head_slug == "checkout":
        title = "Checkout is broken"
        fix = "set the billing setting named in the reason on Fly (PUBLIC_BASE_URL or a Stripe key) and redeploy"
    else:
        title = f"A data store cannot be read: {head}"
        fix = f"open {ADMIN_HEALTH_URL} to see which file, restore it from git and redeploy"
    return _alert(f"health_{head_slug}", title, f"GET /health says: {text}", fix, day_start)


_STORE_KIND = {"odds_multibook": (KIND_ODDS_STALE, KIND_ODDS_MISSING)}


def _freshness_alerts(health: Mapping, day_start: datetime, now: datetime) -> list:
    data = health.get("data_freshness") or {}
    out = []
    if data.get("error"):
        out.append(_alert(KIND_DATA_STALE, "Data freshness could not be checked",
                          f"GET /health could not evaluate the stores behind the pages: {scrub(data['error'])}",
                          "open GET /health, data_freshness.error, and read the app log for the traceback",
                          day_start))
    fresh = health.get("freshness")
    if not isinstance(fresh, Mapping) or "stores" not in fresh:
        # A health payload that carries no verdicts (an older caller): judge it by the same policy.
        fresh = freshness_policy.summarize(health)
    for verdict in fresh.get("stores") or []:
        if verdict.get("state") not in ("stale", "problem") or not verdict.get("alert"):
            continue
        key = verdict["key"]
        stale_kind, missing_kind = _STORE_KIND.get(key, (f"store_stale_{key}", f"store_missing_{key}"))
        if key.startswith("fresh_"):
            kind = f"{KIND_DATA_STALE}_{key[len('fresh_'):]}"
        else:
            kind = stale_kind if verdict["state"] == "stale" else missing_kind
        pub = rss.parse_utc(verdict.get("since_utc")) or day_start
        out.append(_alert(kind, verdict["headline"], verdict["what"], verdict["fix"], min(pub, now)))
    return out


def _deploy_alerts(started_utc, now: datetime) -> list:
    started = rss.parse_utc(started_utc) if started_utc else None
    if started is None:
        return []                      # the app cannot tell when it was deployed: say nothing, invent nothing
    hours = (now - started).total_seconds() / 3600.0
    if hours <= freshness_policy.DEPLOY_STALE_HOURS:
        return []
    return [_alert(KIND_DEPLOY_STALE, f"Production has not redeployed in {freshness_policy.human_age(hours)}",
                   f"The running app started {started.strftime('%b %d %H:%M')} UTC. Production redeploys the "
                   "working branch about hourly when the tests are green, so redeploys have stopped",
                   f"open {freshness_policy.ACTIONS_URL}/workflows/tests.yml; if the latest run is red fix or "
                   f"re-run it, then run deploy-prod ({freshness_policy.ACTIONS_URL}/workflows/deploy-prod.yml)",
                   started + timedelta(hours=freshness_policy.DEPLOY_STALE_HOURS))]


def _pause_alerts(pauses: Iterable[Mapping], day_start: datetime) -> list:
    out = []
    for p in pauses:
        scope = rss.clean(p.get("scope") or "house")
        since = rss.parse_utc(p.get("since")) or day_start
        reason = scrub(p.get("reason") or "")
        out.append(_alert(f"{KIND_LEARNING_PAUSED}_{_slug(scope)}",
                          f"The learning loop paused itself ({scope})",
                          "It stopped because it could not show it was helping; only the owner resumes it. "
                          + (f"Its reason: {reason}" if reason else "GET /hounds/learning has the detail"),
                          "read the reason, then run python -m src.hounds.learning resume --reason ... "
                          "if you accept it", since))
    return out


def collect(health: Optional[Mapping], pauses: Iterable[Mapping], *, now: datetime,
            health_error: Optional[str] = None, started_utc=None, extra: Optional[Iterable[Mapping]] = None) -> list:
    """Every alert standing right now, as ``{kind, guid, title, what, fix, description, pub}``, newest first.

    ``started_utc`` is when the running process started (a deploy or restart); None skips the deploy check.
    ``extra`` are finished alerts from the watchdog (src/ops/watchdog.py: stuck deploy, red tests, ...), each with
    its own ``guid`` (one per incident, not one per UTC day), ``description`` and optional ``link``; they are merged
    and de-duplicated by guid like every other item."""
    now = now.astimezone(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    alerts: list = []
    if health is None:
        alerts.append(_alert(KIND_HEALTH_CHECK_FAILED, "The health check itself failed",
                             "The app could not evaluate its own health"
                             + (f" and said: {scrub(health_error)}" if health_error else ""),
                             "open GET /health and the app logs on Fly to see the exception", day_start))
    else:
        for reason in health.get("reasons") or []:
            alerts.append(_health_reason_alert(str(reason), day_start))
        alerts += _freshness_alerts(health, day_start, now)
    alerts += _deploy_alerts(started_utc, now)
    alerts += _pause_alerts(pauses, day_start)
    alerts += [dict(a) for a in extra or ()]

    seen, unique = set(), []
    for a in alerts:
        a.setdefault("guid", f"alert:{a['kind']}:{day}")
        if a["guid"] in seen:
            continue
        seen.add(a["guid"])
        unique.append(a)
    unique.sort(key=lambda a: a["guid"])
    unique.sort(key=lambda a: a["pub"], reverse=True)
    return unique


def render_feed(alerts: Iterable[Mapping], *, base_url: Optional[str] = None,
                self_url: Optional[str] = None) -> str:
    base = (base_url or site_base_url()).rstrip("/")
    items = [{"title": a["title"], "link": a.get("link") or f"{base}/health", "guid": a["guid"], "pub": a["pub"],
              "description": a["description"]} for a in alerts]
    return rss.render(title="LINEHOUND operator alerts", link=f"{base}/health",
                      description="Empty while the site is healthy. One item per problem per UTC day.",
                      items=items, self_url=self_url)


# What the server cannot check, said out loud so an empty digest is not read as "CI is green".
NOT_CHECKED = ("CI on the working branch from this page (the watchdog, src/ops/watchdog.py, checks it and the deploys "
               "every 10 minutes when WATCHDOG=on and raises its own alerts; without it a red build shows up here only as "
               "'Production has not redeployed')",
               "Whether the house pack placed bets today (needs the schedule and the ledger, not a health check)")


def digest(health: Optional[Mapping], pauses: Iterable[Mapping], *, now: datetime,
           health_error: Optional[str] = None, started_utc=None, extra: Optional[Iterable[Mapping]] = None) -> dict:
    """The owner's "what needs doing today": the same alerts the feed raises, as plain sentences, plus what is
    only worth watching and what is deliberately quiet. The admin Overview reads this.

    ``items`` are the alerts (title, what happened, the one-line fix, since when); ``watch`` are stores past
    their fresh limit but not yet stale; ``not_expected`` are the grey ones with their reasons."""
    now = now.astimezone(timezone.utc)
    alerts = collect(health, pauses, now=now, health_error=health_error, started_utc=started_utc, extra=extra)
    fresh = (health or {}).get("freshness")
    if health is not None and (not isinstance(fresh, Mapping) or "stores" not in fresh):
        fresh = freshness_policy.summarize(health)
    verdicts = (fresh or {}).get("stores") or []
    n = len(alerts)
    return {
        "generated_at": now.isoformat(),
        "all_clear": n == 0,
        "headline": ("Nothing needs doing today." if n == 0
                     else f"{n} thing{'' if n == 1 else 's'} need{'s' if n == 1 else ''} doing today."),
        "items": [{"kind": a["kind"], "title": a["title"], "what": a["what"], "fix": a["fix"],
                   "since": a["pub"].isoformat(), "line": f"{a['title']}. Fix: {a['fix']}."} for a in alerts],
        "watch": [{"key": v["key"], "title": v["title"], "reason": v["reason"]}
                  for v in verdicts if v.get("state") == "aging"],
        "not_expected": [{"key": v["key"], "title": v["title"], "reason": v["reason"]}
                         for v in verdicts if v.get("state") == "not_expected"],
        "not_checked": list(NOT_CHECKED),
    }


def gather(now: datetime):
    """``(health, health_error, pauses, started_utc)`` for the feed and the digest, so both judge the same facts.
    Never raises: a failing health check becomes ``health=None`` plus the exception type."""
    from src.appstate import apphealth
    health, error = None, None
    try:
        health = apphealth.report(now=now)
    except Exception as exc:  # noqa: BLE001 -- the alert feed must say the check failed, not 500
        error = f"{type(exc).__name__}"
    return health, error, pause_facts()


def pause_facts() -> list:
    """``[{scope, reason, since}]`` for each learning scope the loop has paused (an empty list when it
    is running, or when the ledgers cannot be read: a pause check must not be the thing that 500s)."""
    out = []
    try:
        from src.hounds.learning import ledger as L, pause, views
        for name, scope in L.default_scopes().items():
            if not pause.is_paused(scope):
                continue
            last = views._safe_state(scope).last_pause() or {}
            out.append({"scope": name, "reason": last.get("reason"), "since": last.get("utc")})
    except Exception:  # noqa: BLE001
        return out
    return out
