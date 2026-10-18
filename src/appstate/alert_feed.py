"""Operator alerts for the owner, as events a Zap can poll (``GET /feeds/alerts.rss``).

THE POINT IS TO COST NOTHING WHEN NOTHING IS WRONG. A Zap that polls this feed spends no task until an
item appears, and the feed is EMPTY (valid RSS, no ``item``) while the site is healthy. When something
is wrong the Zap fires once per incident, not once per poll:

  * one item per (alert kind, UTC date): the ``guid`` is ``alert:<kind>:<YYYY-MM-DD>``, the same on every
    poll that day, so the same incident does not re-fire every fifteen minutes. If it is still broken
    tomorrow it is a NEW item, which is the reminder the owner wants;
  * ``pubDate`` is a fact about the incident (when the odds crossed the limit, when the loop paused),
    else the start of the UTC day. Never "now", so two polls are byte-identical.

WHAT RAISES AN ALERT (thresholds named here, in one place)

  health_<what>     a reason in ``apphealth.report()["reasons"]`` (database unreachable, a store that
                    cannot be read, checkout broken). The same words ``GET /health`` already shows.
  odds_stale        the newest odds row is older than ``ODDS_STALE_HOURS`` (3.0; the same limit
                    ``scripts/prod_watch.py`` holds, for the same reason: quiet-hours capture slots
                    are 60 minutes apart, so three hours is missing at least two).
  odds_missing      the odds store is absent or has no rows. An absent store is not a healthy store.
  data_stale        a core store the computed pages read is past its own tolerance
                    (``data_freshness.core_stale``, src/pipeline/store_freshness.py).
  learning_paused   the learning loop paused itself (src/hounds/learning/pause.py): it stopped because
                    it could not show it was helping, and only the owner can resume it.

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

ODDS_STALE_HOURS = 3.0
REASON_MAX_CHARS = 200

KIND_ODDS_STALE = "odds_stale"
KIND_ODDS_MISSING = "odds_missing"
KIND_DATA_STALE = "data_stale"
KIND_LEARNING_PAUSED = "learning_paused"
KIND_HEALTH_CHECK_FAILED = "health_check_failed"


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


def _alert(kind: str, title: str, description: str, pub: datetime) -> dict:
    return {"kind": kind, "title": title, "description": rss.clean(description), "pub": pub}


def _health_reason_alert(reason: str, day_start: datetime) -> dict:
    text = scrub(reason)
    head = text.split(":", 1)[0]
    head_slug = _slug(head)
    if head_slug.startswith("app_db"):
        title = "The app database is unreachable"
    elif head_slug == "checkout":
        title = "Checkout is broken"
    else:
        title = f"A data store cannot be read: {head}"
    return _alert(f"health_{head_slug}", title,
                  f"Look at GET /health, field 'reasons'. It says: {text}", day_start)


def _odds_alerts(health: Mapping, day_start: datetime) -> list:
    store = ((health.get("odds") or {}).get("odds_multibook")) or {}
    status = store.get("status")
    if status == "unreadable":
        return []                                   # already a health_ reason; one alert per problem
    if status in ("missing", "empty") or store.get("present") is False:
        return [_alert(KIND_ODDS_MISSING, f"Odds store is {status or 'missing'}",
                       "Look at GET /health, odds.odds_multibook, and at the last forward-capture run.",
                       day_start)]
    age = store.get("newest_row_age_seconds")
    if not isinstance(age, (int, float)) or age <= ODDS_STALE_HOURS * 3600:
        return []
    hours = int(age // 3600)
    crossed = rss.parse_utc(store.get("newest_row_utc"))
    pub = (crossed + timedelta(hours=ODDS_STALE_HOURS)) if crossed else day_start
    return [_alert(KIND_ODDS_STALE, f"Odds are {hours} hours old",
                   "Look at the latest forward-capture run (Actions) and at GET /health, "
                   "odds.odds_multibook.newest_row_age_seconds.", pub)]


def _freshness_alerts(health: Mapping, day_start: datetime) -> list:
    data = health.get("data_freshness") or {}
    if data.get("error"):
        return [_alert(KIND_DATA_STALE, "Data freshness could not be checked",
                       "Look at GET /health, data_freshness.error.", day_start)]
    core = [str(n) for n in (data.get("core_stale") or [])]
    if not core:
        return []
    return [_alert(KIND_DATA_STALE, f"Core data is behind: {', '.join(core)}",
                   "These stores are past their tolerance. Look at GET /health, data_freshness.stores, "
                   "and at the daily loop run.", day_start)]


def _pause_alerts(pauses: Iterable[Mapping], day_start: datetime) -> list:
    out = []
    for p in pauses:
        scope = rss.clean(p.get("scope") or "house")
        since = rss.parse_utc(p.get("since")) or day_start
        reason = scrub(p.get("reason") or "")
        out.append(_alert(f"{KIND_LEARNING_PAUSED}_{_slug(scope)}",
                          f"The learning loop paused itself ({scope})",
                          "It stopped because it could not show it was helping; only the owner resumes it "
                          "(python -m src.hounds.learning resume --reason ...). "
                          + (f"Its reason: {reason}" if reason else "Look at GET /hounds/learning."), since))
    return out


def collect(health: Optional[Mapping], pauses: Iterable[Mapping], *, now: datetime,
            health_error: Optional[str] = None) -> list:
    """Every alert standing right now, as ``{kind, guid, title, description, pub}``, newest first."""
    now = now.astimezone(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    alerts: list = []
    if health is None:
        alerts.append(_alert(KIND_HEALTH_CHECK_FAILED, "The health check itself failed",
                             "Look at GET /health and the app logs. "
                             + (f"It said: {scrub(health_error)}" if health_error else ""),
                             day_start))
    else:
        for reason in health.get("reasons") or []:
            alerts.append(_health_reason_alert(str(reason), day_start))
        alerts += _odds_alerts(health, day_start)
        alerts += _freshness_alerts(health, day_start)
    alerts += _pause_alerts(pauses, day_start)

    seen, unique = set(), []
    for a in alerts:
        a["guid"] = f"alert:{a['kind']}:{day}"
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
    items = [{"title": a["title"], "link": f"{base}/health", "guid": a["guid"], "pub": a["pub"],
              "description": a["description"]} for a in alerts]
    return rss.render(title="LINEHOUND operator alerts", link=f"{base}/health",
                      description="Empty while the site is healthy. One item per problem per UTC day.",
                      items=items, self_url=self_url)


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
