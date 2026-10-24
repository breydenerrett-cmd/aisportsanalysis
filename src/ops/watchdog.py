"""The watchdog: LINEHOUND checks on itself, and on the GitHub machinery that deploys it, and tells the owner.

WHY THIS EXISTS. On 2026-10-03 a production deploy hung while pushing image layers, every later hourly deploy
queued behind it, and the site served seven-hour-old odds until a person happened to look
(docs/audit/2026-10-03/PROD_DEPLOY_HANG.md). Nothing watched between sessions. ``scripts/prod_watch.py`` is the
same idea run by hand; this is the same idea run by the app, every ten minutes, forever, with the answer
delivered to the owner's inbox through the alerts feed his Zap already reads.

WHAT IT CHECKS (each limit is a named constant below, justified where it is set)

  deploy_stuck   a deploy-prod run in progress or queued for more than 25 minutes. The 2026-10-03 failure.
  tests_stuck / capture_run / slate_stuck   the same for the tests (75), forward-capture (130, in progress or
                 queued) and afternoon-slate (60) runs; the limits are ``STUCK_MINUTES_BY_WORKFLOW``.
  ci_tests       the newest finished ``tests`` run on the working branch failed (the alert says when it is the
                 second in a row). Names the failing test when GitHub will give the log, else the failing
                 job and step and the run URL.
  prod_behind    the commit production runs is more than ``BEHIND_MINUTES`` behind the branch while CI is green.
  capture        no successful forward-capture run in ``CAPTURE_STALL_HOURS``. That run also dispatches the
                 hourly production redeploy, so when it stops, odds AND deploys stop.
  health         the app's own freshness verdicts (src/appstate/alert_feed.py, src/pipeline/freshness_policy.py).
                 Reused, not re-judged: the numbers live in the policy and only there.
  grading        a member, manual or AI ticket still open ``GRADING_OVERDUE_HOURS`` after its game's scheduled start
                 (the live settlement loop, src/hounds/live_settle.py, should have graded it within minutes).
  ai_spend       paid AI spend at ``AI_SPEND_WARN`` of its cap: the AI router's monthly meter (AI_PAID_CAP_USD)
                 and the analyst's stores. Skipped while neither exists.
  github_reach   the watchdog itself: it cannot see GitHub for ``BLIND_MINUTES`` and is therefore not watching.

HOW AN ALERT REACHES THE OWNER. Open incidents are written to a small state file on the Fly volume and merged into
``GET /feeds/alerts.rss`` (``alert_feed.collect(extra=...)``). Zapier tells new from seen by ``guid``, so:

  * ONE ITEM PER INCIDENT. The guid is ``watchdog:<kind>:<key>:<opened>`` and never changes while the incident is
    open, so ten polls and three restarts fire one email. The text is the snapshot taken when the incident opened;
    GET /admin/watchdog shows the live text.
  * ONE MORE ITEM WHEN IT CLEARS. ``...:resolved`` with an "All clear" sentence, kept in the feed for
    ``RESOLVED_FEED_HOURS`` so a polling Zap cannot miss it.
  * ``pubDate`` is when the watchdog raised (or cleared) it, a fact in the state file, never "now".

NOT KNOWING IS NOT HEALTHY. A check that cannot get its facts (GitHub unreachable, rate-limited, the commit
production runs is unknown) is ``unknown``: it opens nothing AND closes nothing. An open incident stays open
through a bad GitHub minute; it is never "resolved" by silence. If every GitHub check is blind for
``BLIND_MINUTES`` the watchdog says so, because an empty feed from a blind watchdog reads as good news.

GITHUB BUDGET. The public REST API allows 60 requests an hour per IP without a token. A tick costs 4 requests
(one per check that needs GitHub: 6 ticks an hour is 24, 30 with a restart's refetch), every response is cached
for ``RUNS_TTL_S``, a ``304 Not Modified`` (ETag) costs GitHub nothing, and the client refuses to spend more than
``GITHUB_BUDGET_PER_HOUR`` of its own count or the last ``x-ratelimit-remaining`` GitHub reported. Spent-call
timestamps live in the state file so an hourly redeploy does not reset the count. ``GITHUB_TOKEN``, if set,
raises GitHub's limit and lets the watchdog read test logs; it is sent only to api.github.com, never stored,
logged, put in a status or an alert.

WHICH COMMIT PRODUCTION RUNS. In order: ``GIT_SHA`` env; ``/app/VERSION`` (written at image build from the git
metadata the deploy's checkout leaves behind: see ``write_version`` and deploy/Dockerfile); else inferred from the
deploy-prod run whose window contains this process's start, which is labelled "inferred" everywhere. No workflow
file is touched: the deploy command passes no build arguments, so the build reads the checkout instead.

OFF UNLESS ``WATCHDOG=on`` (production's [env] in deploy/fly.production.toml turns it on; a laptop, a test client
and staging never start one). ``WATCHDOG=off`` (or removing the line) stops the loop and removes the watchdog's
items from the feed. The watchdog runs INSIDE production: if the whole machine is down it cannot tell anyone.

Stdlib only, no FastAPI (Linux CI has none). Nothing here can place a bet or change a deploy: it reads GitHub, reads
the app's own stores, and writes one JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional

from src.hounds import rss

logger = logging.getLogger("linehound.ops.watchdog")

ENV_SWITCH = "WATCHDOG"
ENV_TOKEN = "GITHUB_TOKEN"
ENV_GIT_SHA = "GIT_SHA"
ENV_STATE_PATH = "WATCHDOG_STATE_PATH"
ENV_BUDGET = "WATCHDOG_GITHUB_BUDGET"
ENV_AI_MONTHLY_CAP = "AI_MONTHLY_CAP_USD"

REPO = "breydenerrett-cmd/aisportsanalysis"
BRANCH = "claude/sports-betting-analysis-review-g1o0co"
API = "https://api.github.com"
SITE = f"https://github.com/{REPO}"
ACTIONS = f"{SITE}/actions"
WF_DEPLOY, WF_TESTS, WF_CAPTURE = "deploy-prod.yml", "tests.yml", "forward-capture.yml"
WF_SLATE = "afternoon-slate.yml"

TICK_SECONDS = 600.0                 # the owner asked for ten minutes
WAIT_FOR_WARMUP_SECONDS = 600.0      # like the other loops: never compete with a cold start

# Limits. Each is the owner's number or a number a past incident set.
# How long a run may be in progress OR queued before it is "stuck", per workflow. Measured by the orchestrator
# 2026-10-20 from real runs: a deploy takes 6 to 12 minutes, the tests about 20, a forward-capture run 65 to 75
# (22:05 to 23:12 and 23:05 to 00:17 UTC; a 60 minute limit fired a false alarm), and two capture runs can overlap
# while one waits in its concurrency queue, so a queued capture run is not stuck until the same 130 minutes.
# The 2026-10-03 hang was a hang (six hours), not slowness; these limits sit well past normal and far short of that.
STUCK_MINUTES_BY_WORKFLOW = {WF_DEPLOY: 25, WF_TESTS: 75, WF_CAPTURE: 130, WF_SLATE: 60}   # tests: ~18 min suite + ~17 min no-network rerun = ~37-45 normal (2026-10-21)
STUCK_MINUTES = STUCK_MINUTES_BY_WORKFLOW[WF_DEPLOY]
NORMAL_MINUTES_DEFAULT = {WF_DEPLOY: 6, WF_TESTS: 40, WF_CAPTURE: 70, WF_SLATE: None}   # "normal is N" until runs give a median
BEHIND_MINUTES = 90                  # hourly dispatch + ~6 min build leaves ~66 min of normal lag; 90 is the owner's
CAPTURE_STALL_HOURS = 3              # quiet-hours capture slots are 60 min apart: three hours is two missed slots
GRADING_OVERDUE_HOURS = 4.0          # the owner's line (2026-10-22): a ticket open this long after its game's start is stuck
AI_SPEND_WARN = 0.8                  # alert at 80% of the cap, before the analyst stops itself at 100%
BLIND_MINUTES = 90                   # long enough to ride out a GitHub blip and a rate-limit hour
RESOLVED_FEED_HOURS = 36             # how long an "All clear" item stays in the feed for a polling Zap to see
RESOLVED_KEEP_DAYS = 7               # how long a resolved incident stays in the state file
RESOLVED_KEEP_MAX = 100

# GitHub client
GITHUB_BUDGET_PER_HOUR = 60          # the unauthenticated limit; our own count never exceeds it
GITHUB_BUDGET_WITH_TOKEN = 600       # a token raises GitHub's limit to 5,000; stay far under it
RATE_RESERVE = 5                     # stop when GitHub itself says this few requests remain
RUNS_TTL_S = 240.0                   # a bit under one tick, so every tick refetches but a double-click does not
STALE_MAX_S = 3600.0                 # an answer older than this is no longer served in place of a fresh one: a
                                     # watchdog fed hours-old cache while GitHub is down would never notice it is blind
FOREVER = float("inf")               # a finished run's jobs and logs never change
HTTP_TIMEOUT_S = 15.0
MAX_BODY_BYTES = 8 * 1024 * 1024
BLOCKED_DEFAULT_S = 900.0            # when GitHub says "slow down" without saying for how long

# Check states
OK, ALERT, UNKNOWN, SKIPPED, SUPPRESSED, ERROR = "ok", "alert", "unknown", "skipped", "suppressed", "error"
ACTIVE_RUN_STATES = ("in_progress", "queued", "waiting", "pending", "requested")
RED_CONCLUSIONS = ("failure", "timed_out", "startup_failure")

AI_USAGE_STORES = (                  # written ONLY by `analyst run` with ANTHROPIC_API_KEY (paid API calls)
    "evidence/analyst_usage_v1.jsonl",
    "evidence/analyst_ufc_usage_v1.jsonl",
)                                    # the *_pilot_usage stores are Claude-session estimates, not a bill: excluded
AI_DEFAULT_RUN_CAP_USD = 6.0         # src/analyst/config.py DEFAULTS; the shipped config/analyst.json says the same
AI_RUN_WINDOW_HOURS = 48

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA_ANY = re.compile(r"^[0-9a-f]{7,40}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _compact(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _when(value: Any) -> Optional[datetime]:
    return rss.parse_utc(value)


def _minutes(delta: timedelta) -> int:
    return max(int(delta.total_seconds() // 60), 0)


def span(minutes: float) -> str:
    """'34 min', '2 h 05 min', '3 days': a duration a person reads without doing arithmetic."""
    m = max(int(minutes), 0)
    if m < 120:
        return f"{m} min"
    if m < 48 * 60:
        return f"{m // 60} h {m % 60:02d} min"
    return f"{m // (24 * 60)} days"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", str(text)).strip("_") or "x"


def _sentence(text: str) -> str:
    text = rss.clean(text).rstrip()
    return text if text.endswith((".", "!", "?")) else text + "."


def configured_budget(env: Mapping) -> int:
    """GitHub requests the watchdog may spend an hour: ``WATCHDOG_GITHUB_BUDGET`` if it is a positive number, else
    the unauthenticated limit, or the larger token figure when ``GITHUB_TOKEN`` is set."""
    raw = (env.get(ENV_BUDGET) or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return GITHUB_BUDGET_WITH_TOKEN if (env.get(ENV_TOKEN) or "").strip() else GITHUB_BUDGET_PER_HOUR


def enabled(env: Optional[Mapping] = None) -> bool:
    """On only when ``WATCHDOG=on``. ``off``, unset or anything else is off: the kill switch can never be
    defeated by a typo that happens to read as true."""
    env = os.environ if env is None else env
    return (env.get(ENV_SWITCH) or "").strip().lower() == "on"


def switch_word(env: Optional[Mapping] = None) -> str:
    env = os.environ if env is None else env
    raw = (env.get(ENV_SWITCH) or "").strip().lower()
    return raw if raw in ("on", "off") else "unset"


# ---------------------------------------------------------------------------
# which commit does production run
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _full_sha(text: Optional[str]) -> Optional[str]:
    token = (text or "").split()[0].lower() if (text or "").split() else ""
    return token if _SHA.match(token) else None


def sha_from_gitmeta(directory) -> Optional[str]:
    """The commit a deploy's checkout left behind, from copied git metadata, or None.

    ``directory`` holds whichever of HEAD, FETCH_HEAD, packed-refs and the refs tree the image build could copy
    (deploy/Dockerfile). Both layouts are read: a real ``.git`` (``refs/heads/X``) and the flattened copy the
    Dockerfile makes (``heads/X``, because COPY of a directory copies its CONTENTS). Order: a detached HEAD; the
    branch HEAD names, loose then packed, local then ``origin``; then the first non-merge line of FETCH_HEAD.
    Only a full 40-hex id counts; anything else is "unknown", never a guess."""
    d = Path(directory)
    head = _read_text(d / "HEAD")
    sha = _full_sha(head)
    if sha:
        return sha
    match = re.match(r"ref:\s*(\S+)", head or "")
    if match:
        ref = match.group(1)
        name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        loose = [d / ref, d / ref[len("refs/"):] if ref.startswith("refs/") else d / ref,
                 d / "refs" / "remotes" / "origin" / name, d / "remotes" / "origin" / name]
        for candidate in loose:
            sha = _full_sha(_read_text(candidate))
            if sha:
                return sha
        packed = _read_text(d / "packed-refs") or ""
        wanted = {ref, f"refs/remotes/origin/{name}"}
        for line in packed.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] in wanted and _SHA.match(parts[0].lower()):
                return parts[0].lower()
    for line in (_read_text(d / "FETCH_HEAD") or "").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and "not-for-merge" in fields[1]:
            continue
        sha = _full_sha(fields[0])
        if sha:
            return sha
    return None


def write_version(gitmeta, out) -> Optional[str]:
    """Write ``<sha>\\n`` to ``out`` when the metadata names a commit; return the sha, else None and write
    nothing (a missing VERSION is a stated unknown, never a made-up value). Never raises: this runs in the
    image build, where failing would block a deploy."""
    try:
        sha = sha_from_gitmeta(gitmeta)
        if sha:
            Path(out).write_text(sha + "\n", encoding="utf-8")
        return sha
    except OSError:
        return None


def deployed_version(env: Optional[Mapping] = None, root: Optional[Path] = None) -> Optional[dict]:
    """``{sha, source}`` for the commit this process was built from, or None when the image does not say."""
    env = os.environ if env is None else env
    raw = (env.get(ENV_GIT_SHA) or "").strip().lower()
    if _SHA_ANY.match(raw):
        return {"sha": raw, "source": "GIT_SHA setting"}
    if root is None:
        from src import paths
        root = paths.repo_root()
    sha = _full_sha(_read_text(Path(root) / "VERSION"))
    return {"sha": sha, "source": "VERSION file written when the image was built"} if sha else None


# ---------------------------------------------------------------------------
# GitHub, behind a seam, with a budget and a cache
# ---------------------------------------------------------------------------

class Reply(NamedTuple):
    status: int
    headers: Mapping[str, str]        # lower-case names
    body: str


class GitHubUnavailable(Exception):
    """GitHub could not give an answer right now. The message is safe to show the owner: it names the problem,
    never a header, a URL with credentials or the token."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None            # hand the 302 back: the log download must not receive our Authorization header


def urllib_http(url: str, headers: Mapping[str, str], timeout: float = HTTP_TIMEOUT_S) -> Reply:
    """The real HTTP GET. Returns the status instead of raising for 3xx/4xx/5xx; raises OSError only when the
    host did not answer at all. Never follows a redirect (see _NoRedirect) and reads at most MAX_BODY_BYTES."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:     # noqa: S310 -- https URLs built here
            body = response.read(MAX_BODY_BYTES)
            return Reply(response.status, {k.lower(): v for k, v in response.headers.items()},
                         body.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(MAX_BODY_BYTES)
        except OSError:
            pass
        return Reply(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()},
                     body.decode("utf-8", errors="replace"))


@dataclass
class _Cached:
    fetched: float
    etag: Optional[str]
    body: Any


class GitHubClient:
    """GET-only GitHub REST client: cached, ETag-aware and budgeted. ``http`` and ``clock`` are injected, so
    tests never touch the network or the wall clock."""

    def __init__(self, http: Callable[[str, Mapping[str, str]], Reply], clock: Callable[[], float], *,
                 token: Optional[str] = None, budget: Optional[int] = None,
                 calls: Optional[List[float]] = None, blocked_until: float = 0.0):
        self._http = http
        self._clock = clock
        self._token = (token or "").strip() or None
        self.budget = int(budget if budget is not None
                          else (GITHUB_BUDGET_WITH_TOKEN if self._token else GITHUB_BUDGET_PER_HOUR))
        self.calls: List[float] = list(calls or [])
        self.blocked_until = float(blocked_until or 0.0)
        self.remaining: Optional[int] = None
        self.stale_served = 0
        self.last_error: Optional[str] = None
        self._cache: Dict[str, _Cached] = {}

    @property
    def has_token(self) -> bool:
        return self._token is not None

    def calls_last_hour(self) -> int:
        cutoff = self._clock() - 3600.0
        self.calls = [t for t in self.calls if t > cutoff]
        return len(self.calls)

    def _refusal(self) -> Optional[str]:
        now = self._clock()
        if self.blocked_until > now:
            return f"GitHub asked for a pause until {_iso(datetime.fromtimestamp(self.blocked_until, timezone.utc))}"
        if self.calls_last_hour() >= self.budget:
            return f"the watchdog's own GitHub budget ({self.budget} requests an hour) is spent"
        return None

    def _headers(self, accept: str = "application/vnd.github+json") -> Dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "linehound-watchdog", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _note_limits(self, reply: Reply) -> None:
        now = self._clock()
        remaining = reply.headers.get("x-ratelimit-remaining")
        reset = reply.headers.get("x-ratelimit-reset")
        try:
            self.remaining = int(remaining) if remaining is not None else self.remaining
        except ValueError:
            pass
        limited = reply.status in (403, 429)
        if limited or (self.remaining is not None and self.remaining <= RATE_RESERVE):
            until = now + BLOCKED_DEFAULT_S
            try:
                if reset is not None:
                    until = max(float(reset), now + 1.0)
                elif reply.headers.get("retry-after"):
                    until = now + float(reply.headers["retry-after"])
            except ValueError:
                pass
            if limited or reset is not None:
                self.blocked_until = max(self.blocked_until, until)

    def _fail(self, message: str, stale: Optional[_Cached]) -> Any:
        self.last_error = message
        if stale is not None and self._clock() - stale.fetched < STALE_MAX_S:
            self.stale_served += 1
            return stale.body
        raise GitHubUnavailable(message)

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None, *, ttl: float = RUNS_TTL_S) -> Any:
        """The decoded JSON for ``path``. A fresh cache entry costs nothing; when GitHub cannot be asked (budget,
        pause, error) a stale entry is returned rather than nothing, and GitHubUnavailable is raised only when
        there is none."""
        url = API + path + ("?" + urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in params.items()))
                            if params else "")
        entry = self._cache.get(url)
        if entry is not None and self._clock() - entry.fetched < ttl:
            return entry.body
        refusal = self._refusal()
        if refusal:
            return self._fail(refusal, entry)
        headers = self._headers()
        if entry is not None and entry.etag:
            headers["If-None-Match"] = entry.etag
        self.calls.append(self._clock())
        try:
            reply = self._http(url, headers)
        except (OSError, ValueError) as exc:
            return self._fail(f"GitHub did not answer ({type(exc).__name__})", entry)
        self._note_limits(reply)
        if reply.status == 304 and entry is not None:
            entry.fetched = self._clock()
            return entry.body
        if reply.status in (403, 429):
            return self._fail("GitHub is rate-limiting the watchdog" + ("" if self.has_token
                              else " (no GITHUB_TOKEN is set, so the shared anonymous limit applies)"), entry)
        if reply.status != 200:
            return self._fail(f"GitHub answered {reply.status} for {path}", entry)
        try:
            body = json.loads(reply.body)
        except ValueError:
            return self._fail(f"GitHub sent something that is not JSON for {path}", entry)
        self._cache[url] = _Cached(self._clock(), reply.headers.get("etag"), body)
        self.last_error = None
        return body

    def get_log(self, job_id: int) -> Optional[str]:
        """A finished job's log text, or None. Needs a token (GitHub refuses anonymous log reads), follows the
        one redirect by hand so the token is never sent to the storage host, and caches forever."""
        if not self._token:
            return None
        key = f"log:{job_id}"
        entry = self._cache.get(key)
        if entry is not None:
            return entry.body
        if self._refusal():
            return None
        self.calls.append(self._clock())
        try:
            reply = self._http(f"{API}/repos/{REPO}/actions/jobs/{job_id}/logs", self._headers())
            self._note_limits(reply)
            if reply.status in (301, 302, 303, 307, 308):
                location = reply.headers.get("location", "")
                if not location.startswith("https://"):
                    return None
                reply = self._http(location, {"User-Agent": "linehound-watchdog"})
        except (OSError, ValueError):
            return None
        if reply.status != 200:
            return None
        self._cache[key] = _Cached(self._clock(), None, reply.body)
        return reply.body


# ---------------------------------------------------------------------------
# state: one JSON file on the volume
# ---------------------------------------------------------------------------

def default_state_path(env: Optional[Mapping] = None) -> Path:
    """``WATCHDOG_STATE_PATH``, else beside the app database (the Fly volume in production, so incidents survive
    the hourly redeploy; ``data/app/`` on a laptop)."""
    env = os.environ if env is None else env
    explicit = (env.get(ENV_STATE_PATH) or "").strip()
    if explicit:
        return Path(explicit)
    try:
        from src.appstate import users
        return users.db_path().parent / "watchdog_state.json"
    except Exception:  # noqa: BLE001 -- no app database module: fall back to the repo's data/app
        from src import paths
        return paths.repo_root() / "data" / "app" / "watchdog_state.json"


class StateStore:
    """Load tolerant, save atomic. A missing or corrupt file is an empty state: the watchdog starts over, it does
    not crash (and a lost state costs at most one repeated email, because guids carry the opened time)."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", 1)
        data.setdefault("checks", {})
        data.setdefault("incidents", [])
        data.setdefault("github", {})
        return data

    def save(self, state: Mapping) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# what a check reports
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """One thing that needs the owner. ``kind`` is unique among open incidents; ``key`` is the identity of this
    occurrence (a run id, a commit) and only names a NEW incident's guid."""
    kind: str
    key: str
    title: str
    what: str
    fix: str
    url: Optional[str] = None
    feed: bool = True              # False when the existing alerts feed already carries the item (health)


@dataclass
class Outcome:
    name: str
    state: str
    summary: str
    findings: List[Finding] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)
    github_down: bool = False


def _run_url(run: Mapping) -> str:
    return run.get("html_url") or f"{ACTIONS}/runs/{run.get('id')}"


def _short(sha: Optional[str]) -> str:
    return (sha or "")[:7] or "unknown"


# ---------------------------------------------------------------------------
# the watchdog
# ---------------------------------------------------------------------------

class Watchdog:
    """One instance per process. ``run_once()`` is a tick; it never raises."""

    def __init__(self, *, env: Optional[Mapping] = None,
                 http: Optional[Callable[[str, Mapping[str, str]], Reply]] = None,
                 now: Optional[Callable[[], datetime]] = None,
                 store: Optional[StateStore] = None,
                 version: Optional[Callable[[], Optional[dict]]] = None,
                 started_utc: Optional[Callable[[], Optional[str]]] = None,
                 health: Optional[Callable[[datetime], list]] = None,
                 ai_spend: Optional[Callable[[datetime], Optional[dict]]] = None,
                 grading: Optional[Callable[[datetime], Optional[list]]] = None):
        self.env = os.environ if env is None else env
        self.now = now or _utcnow
        self.store = store or StateStore(default_state_path(self.env))
        self._http = http or urllib_http
        self._version = version or (lambda: deployed_version(self.env))
        self._started = started_utc or (lambda: None)
        self._health = health
        self._ai_spend = ai_spend
        self._grading = grading
        self._lock = threading.Lock()
        self.state = self.store.load()
        gh = self.state.get("github") or {}
        self.client = GitHubClient(self._http, lambda: self.now().timestamp(), token=self.env.get(ENV_TOKEN),
                                   budget=configured_budget(self.env), calls=gh.get("calls") or [],
                                   blocked_until=gh.get("blocked_until") or 0.0)

    # -- the checks ---------------------------------------------------------

    def _runs(self, workflow: str, **params) -> dict:
        return self.client.get(f"/repos/{REPO}/actions/workflows/{workflow}/runs", params)

    def _stuck(self, name: str, kind: str, workflow: str, runs: list, now: datetime, *, noun: str, label: str,
               consequence: str, redo: str) -> Outcome:
        """Is any run of ``workflow`` in progress or queued longer than its limit? The oldest in-progress run is the
        cause; runs queued behind it are counted, not alerted separately."""
        limit = STUCK_MINUTES_BY_WORKFLOW[workflow]
        finished = []
        for r in runs:
            if r.get("status") == "completed" and r.get("conclusion") == "success":
                a, b = _when(r.get("run_started_at") or r.get("created_at")), _when(r.get("updated_at"))
                if a and b and b > a:
                    finished.append((b - a).total_seconds() / 60.0)
        normal = max(int(round(statistics.median(finished))), 1) if finished else NORMAL_MINUTES_DEFAULT[workflow]
        stuck = []
        for r in runs:
            if r.get("status") not in ACTIVE_RUN_STATES:
                continue
            running = r.get("status") == "in_progress"
            began = _when((r.get("run_started_at") if running else None) or r.get("created_at"))
            if began is None:
                continue
            age = _minutes(now - began)
            if age > limit:
                stuck.append((0 if running else 1, began, age, r))
        detail = {"normal_minutes": normal, "limit_minutes": limit, "runs_seen": len(runs)}
        if not stuck:
            last = f"; the last good one took {finished[0]:.0f} min" if finished else ""
            return Outcome(name, OK, f"no {noun} has been running or waiting longer than {limit} min{last}", detail=detail)
        stuck.sort(key=lambda t: (t[0], t[1]))
        _, _, age, run = stuck[0]
        others = sum(1 for r in runs if r.get("status") in ACTIVE_RUN_STATES and r is not run)   # all in line, any age
        url = _run_url(run)
        norm = f" (normal is {normal})" if normal else ""
        if run.get("status") == "in_progress":
            what = f"{label} has been running {span(age)}{norm}"
            title = f"{label} is stuck ({span(age)})"
        else:
            tail = f" (a run normally takes {normal} min from start to finish)" if normal else ""
            what = f"{label} has been waiting to start for {span(age)}{tail}"
            title = f"{label} is stuck waiting ({span(age)})"
        if others:
            what += f", and {others} more run{'s are' if others != 1 else ' is'} queued behind it"
        what += ". " + consequence
        fix = f"open {url} and click Cancel workflow; {redo}"
        detail.update({"run_id": run.get("id"), "age_minutes": age, "queued_behind": others})
        return Outcome(name, ALERT, f"{noun} run {run.get('id')} has been {run.get('status')} for {span(age)}",
                       [Finding(kind, str(run.get("id")), title, what, fix, url)], detail)

    def check_deploy_stuck(self, now: datetime) -> Outcome:
        runs = (self._runs(WF_DEPLOY, per_page=20).get("workflow_runs")) or []
        return self._stuck("deploy_stuck", "deploy_stuck", WF_DEPLOY, runs, now, noun="deploy", label="Deploy to production",
                           consequence="Production keeps serving its last good deploy, so odds and picks go stale",
                           redo="Claude will redeploy")

    def check_tests_stuck(self, now: datetime) -> Outcome:
        runs = (self._runs(WF_TESTS, branch=BRANCH, per_page=20).get("workflow_runs")) or []
        return self._stuck("tests_stuck", "tests_stuck", WF_TESTS, runs, now, noun="tests run", label="The test run",
                           consequence="Production redeploys only after the tests pass, so deploys wait on it",
                           redo="Claude will re-run it")

    def check_capture_stuck(self, now: datetime) -> Outcome:
        runs = (self._runs(WF_CAPTURE, per_page=10).get("workflow_runs")) or []
        return self._stuck("capture_run", "capture_run_stuck", WF_CAPTURE, runs, now, noun="forward-capture run",
                           label="The data-capture run",
                           consequence="Odds and picks stop updating, and the hourly production redeploy it triggers waits too",
                           redo="Claude will restart the chain")

    def check_slate_stuck(self, now: datetime) -> Outcome:
        runs = (self._runs(WF_SLATE, per_page=5).get("workflow_runs")) or []
        return self._stuck("slate_stuck", "slate_stuck", WF_SLATE, runs, now, noun="afternoon-slate run",
                           label="The afternoon slate run",
                           consequence="Today's slate may not be published",
                           redo="Claude will re-run it")

    def _failing_tests(self, run: Mapping) -> Dict[str, Any]:
        """Which job and step failed, and (with a token) which tests. Cached forever per run."""
        out: Dict[str, Any] = {"jobs": [], "tests": []}
        try:
            jobs = self.client.get(f"/repos/{REPO}/actions/runs/{run['id']}/jobs", {"per_page": 30}, ttl=FOREVER)
        except GitHubUnavailable:
            return out
        for job in jobs.get("jobs") or []:
            if job.get("conclusion") not in RED_CONCLUSIONS:
                continue
            steps = [s.get("name") for s in job.get("steps") or [] if s.get("conclusion") in RED_CONCLUSIONS]
            out["jobs"].append({"id": job.get("id"), "name": job.get("name"), "steps": steps})
        for job in out["jobs"][:1]:
            log = self.client.get_log(job["id"]) if job.get("id") else None
            if log:
                out["tests"] = failing_tests_from_log(log)
        return out

    def check_ci(self, now: datetime) -> Outcome:
        data = self._runs(WF_TESTS, branch=BRANCH, per_page=20)      # same request as check_tests_stuck: one call
        runs = [r for r in (data.get("workflow_runs") or []) if r.get("status") == "completed"
                and (r.get("conclusion") == "success" or r.get("conclusion") in RED_CONCLUSIONS)]
        if not runs:
            return Outcome("ci_tests", UNKNOWN, "no finished tests run on the working branch to judge")
        latest = runs[0]
        if latest.get("conclusion") == "success":
            return Outcome("ci_tests", OK, f"the latest tests run on the working branch passed ({_short(latest.get('head_sha'))})",
                           detail={"run_id": latest.get("id"), "sha": latest.get("head_sha")})
        streak = 0
        for r in runs:
            if r.get("conclusion") in RED_CONCLUSIONS:
                streak += 1
            else:
                break
        url = _run_url(latest)
        facts = self._failing_tests(latest)
        message = (latest.get("head_commit") or {}).get("message") or latest.get("display_title") or ""
        commit = rss.clean(message.splitlines()[0] if message else "")[:80]
        what = f"The tests are failing on the working branch: the latest run ({_short(latest.get('head_sha'))}"
        what += f", \"{commit}\")" if commit else ")"
        what += f" failed, {streak} runs in a row" if streak > 1 else " failed"
        if facts["jobs"]:
            job = facts["jobs"][0]
            what += f", in the job \"{job['name']}\"" + (f" at the step \"{job['steps'][0]}\"" if job["steps"] else "")
        if facts["tests"]:
            what += ". Failing: " + "; ".join(facts["tests"][:3])
        what += ". Production only redeploys when the tests are green, so it is staying on its last good version"
        if facts["tests"]:
            fix = f"ask Claude to fix {facts['tests'][0].split(' (')[0]} (run: {url})"
        else:
            fix = f"open {url}, click the red job to see which test failed, and ask Claude to fix it"
        detail = {"run_id": latest.get("id"), "sha": latest.get("head_sha"), "streak": streak, "tests": facts["tests"],
                  "failed_jobs": [j["name"] for j in facts["jobs"]]}
        oldest = runs[streak - 1]
        return Outcome("ci_tests", ALERT, f"tests run {latest.get('id')} failed" + (f" ({streak} in a row)" if streak > 1 else ""),
                       [Finding("ci_red", str(oldest.get("id")), "The tests are failing on the working branch",
                                what, fix, url)], detail)

    def _infer_deployed(self, deploy_runs: list) -> Optional[dict]:
        started = _when(self._started())
        if started is None:
            return None
        slack = timedelta(minutes=3)
        for r in deploy_runs:
            if r.get("status") != "completed" or r.get("conclusion") != "success":
                continue
            a, b = _when(r.get("run_started_at") or r.get("created_at")), _when(r.get("updated_at"))
            if a and b and a <= started <= b + slack and _SHA_ANY.match(str(r.get("head_sha") or "")):
                return {"sha": r["head_sha"], "source": f"inferred from deploy-prod run {r.get('id')} (the image has no VERSION file)"}
        return None

    def check_behind(self, now: datetime, ci: Outcome) -> Outcome:
        deploy_runs = (self._runs(WF_DEPLOY, per_page=20).get("workflow_runs")) or []
        deployed = self._version() or self._infer_deployed(deploy_runs)
        if not deployed:
            return Outcome("prod_behind", UNKNOWN, "the commit production is running is not known: no GIT_SHA, no VERSION file in "
                           "the image and no deploy run matches this process's start")
        commits = self.client.get(f"/repos/{REPO}/commits", {"sha": BRANCH, "per_page": 50})
        if not isinstance(commits, list) or not commits:
            return Outcome("prod_behind", UNKNOWN, "GitHub returned no commits for the working branch")
        sha = str(deployed["sha"]).lower()
        def same(c: Mapping) -> bool:
            theirs = str(c.get("sha") or "").lower()
            return bool(theirs) and (theirs.startswith(sha) or sha.startswith(theirs))

        index = next((i for i, c in enumerate(commits) if same(c)), None)
        head = commits[0]

        def stamp(c: Mapping) -> Optional[datetime]:
            meta = c.get("commit") or {}
            return _when((meta.get("committer") or {}).get("date") or (meta.get("author") or {}).get("date"))

        detail = {"deployed_sha": sha, "deployed_source": deployed["source"], "head_sha": head.get("sha")}
        if index == 0:
            return Outcome("prod_behind", OK, f"production is on the branch's newest commit ({_short(sha)})", detail=detail)
        if index is None:
            missing, oldest, bound = len(commits), commits[-1], True
        else:
            missing, oldest, bound = index, commits[index - 1], False
        since = stamp(oldest)
        if since is None:
            return Outcome("prod_behind", UNKNOWN, "the oldest commit production is missing has no date", detail=detail)
        behind = _minutes(now - since)
        count = f"{missing}{'+' if bound else ''}"
        detail.update({"commits_behind": count, "behind_minutes": behind})
        if behind <= BEHIND_MINUTES:
            return Outcome("prod_behind", OK, f"production is {count} commit{'s' if missing != 1 else ''} behind, the oldest "
                           f"missing change is {span(behind)} old (normal lag; the limit is {BEHIND_MINUTES} min)", detail=detail)
        if ci.state == ALERT:
            return Outcome("prod_behind", SUPPRESSED, f"production is {span(behind)} behind, but the tests are red, so it is "
                           "expected to be (see the failing-tests alert)", detail=detail)
        if ci.state != OK:
            return Outcome("prod_behind", SUPPRESSED, "production looks behind but the tests' state is unknown, so the watchdog "
                           "will not say why yet", detail=detail)
        last_deploy = next((r for r in deploy_runs if r.get("status") == "completed"), None)
        failed = last_deploy is not None and last_deploy.get("conclusion") in RED_CONCLUSIONS + ("cancelled",)
        what = (f"Production is {span(behind)} behind the code: it runs {_short(sha)} while the working branch is at "
                f"{_short(head.get('sha'))}, {count} commit{'s' if missing != 1 else ''} newer, and the tests are green, so it "
                "should have redeployed by now")
        if failed:
            what += f". The last deploy-prod run ended {last_deploy.get('conclusion')}: {_run_url(last_deploy)}"
        fix = (f"open {SITE}/actions/workflows/{WF_DEPLOY}, click Run workflow, then the green Run workflow button "
               "(it deploys the working branch whichever branch is shown); or ask Claude to redeploy")
        return Outcome("prod_behind", ALERT, f"production is {span(behind)} behind the branch",
                       [Finding("prod_behind", _short(sha), f"Production is {span(behind)} behind the code", what, fix,
                                f"{SITE}/actions/workflows/{WF_DEPLOY}")], detail)

    def check_capture(self, now: datetime) -> Outcome:
        data = self._runs(WF_CAPTURE, status="success", per_page=1)
        runs = data.get("workflow_runs") or []
        limit = timedelta(hours=CAPTURE_STALL_HOURS)
        done = _when(runs[0].get("updated_at")) if runs else None
        if done is not None and now - done <= limit:
            return Outcome("capture", OK, f"the last good forward-capture run finished {span(_minutes(now - done))} ago",
                           detail={"last_success_utc": _iso(done), "run_id": runs[0].get("id")})
        newest = None
        try:
            newest = (self._runs(WF_CAPTURE, per_page=10).get("workflow_runs") or [None])[0]   # cached: check_capture_stuck read it
        except GitHubUnavailable:
            pass
        status = ""
        if newest:
            status = f"; the newest run is {newest.get('conclusion') or newest.get('status')}"
        url = f"{SITE}/actions/workflows/{WF_CAPTURE}"
        if done is None:
            what = f"GitHub shows no successful forward-capture run at all{status}"
            title, key = "Data capture has never succeeded on record", "none"
        else:
            what = (f"No forward-capture run has succeeded in {span(_minutes(now - done))} (the last good one finished "
                    f"{done:%b %d %H:%M} UTC){status}")
            title, key = f"Data capture has stopped ({span(_minutes(now - done))} since the last good run)", str(runs[0].get("id"))
        what += ". Odds and picks stop updating, and the hourly production redeploy stops too, because that run triggers it"
        fix = f"open {url}; if the newest run is red read its error and tell Claude, otherwise click Run workflow to restart the chain"
        return Outcome("capture", ALERT, "no forward-capture success in the last "
                       f"{CAPTURE_STALL_HOURS} h", [Finding("capture_stalled", key, title, what, fix, url)],
                       {"last_success_utc": _iso(done)})

    def check_health(self, now: datetime) -> Outcome:
        if self._health is None:
            return Outcome("health", SKIPPED, "no health source wired")
        alerts = self._health(now)
        findings = [Finding(f"health:{a['kind']}", str(a["kind"]), a["title"], a["what"], a["fix"], None, feed=False)
                    for a in alerts]
        if not findings:
            return Outcome("health", OK, "GET /health shows nothing that needs doing")
        return Outcome("health", ALERT, f"{len(findings)} thing{'s' if len(findings) != 1 else ''} in GET /health need doing",
                       findings, {"kinds": [f.kind for f in findings]})

    def check_ai_spend(self, now: datetime) -> Outcome:
        fn = self._ai_spend or (lambda n: ai_spend_status(env=self.env, now=n))
        spend = fn(now)
        if not spend:
            return Outcome("ai_spend", SKIPPED, "no paid-AI usage store exists yet (nothing has run the analyst with an API key)")
        pct = int(spend["fraction"] * 100)
        summary = f"{spend['label']}: ${spend['spent_usd']:.2f} of ${spend['cap_usd']:.2f} ({pct}%)"
        if spend["fraction"] < AI_SPEND_WARN:
            return Outcome("ai_spend", OK, summary, detail=spend)
        what = f"AI spend is at {pct}% of its cap: {summary}"
        if str(spend.get("key", "")).startswith("router:"):
            fix = ("nothing is overspent, the router stops paid calls at 100% and the AI hounds pass; to keep Haiku running, "
                   "raise AI_PAID_CAP_USD with fly secrets set (ask Claude for the line), otherwise let it stop")
        else:
            fix = ("nothing is overspent, the analyst stops itself at 100%; if you want more games analysed, raise "
                   "spend_cap in config/analyst.json (ask Claude), otherwise let it stop")
        return Outcome("ai_spend", ALERT, summary, [Finding("ai_spend", spend.get("key", "x"),
                       f"AI spend is at {pct}% of its cap", what, fix)], spend)

    def check_grading(self, now: datetime) -> Outcome:
        """Open tickets whose game started more than ``GRADING_OVERDUE_HOURS`` ago. The list comes from
        ``live_settle.overdue_tickets``, which counts only what the live loop is responsible for (it leaves out
        postponed and cancelled games, games still in play and families it cannot read), so this fires on a real stall
        and not every night. The house pack is graded by the capture slot and is not counted here."""
        if self._grading is None:
            return Outcome("grading", SKIPPED, "no open-ticket source wired")
        try:
            overdue = self._grading(now)
        except Exception as exc:  # noqa: BLE001 -- not being able to look is unknown, never "all clear"
            return Outcome("grading", UNKNOWN, f"could not read the open tickets ({type(exc).__name__})")
        if overdue is None:
            return Outcome("grading", SKIPPED, "no open-ticket source wired")
        if not overdue:
            return Outcome("grading", OK, f"no ticket has been open more than {GRADING_OVERDUE_HOURS:g} h past its game's start")
        tickets = sum(int(o.get("tickets") or 1) for o in overdue)
        oldest = overdue[0]
        games = ", ".join(f"{o['game']} ({o['sport']}, started {o['start_utc'][11:16]} UTC)" for o in overdue[:4])
        more = f" and {len(overdue) - 4} more" if len(overdue) > 4 else ""
        what = (f"{tickets} ticket{'s' if tickets != 1 else ''} on {len(overdue)} game{'s' if len(overdue) != 1 else ''} "
                f"{'are' if tickets != 1 else 'is'} still open more than {GRADING_OVERDUE_HOURS:g} hours after the scheduled "
                f"start: {games}{more}. The live settlement loop should have graded the ones it can read within minutes of "
                "the final; the rest (no free feed for the sport) grade from the odds vendor's scores. "
                "Records and bankrolls are out of date until they grade")
        fix = ("open GET /hounds/live/status (its 'unsupported' count is open tickets with no free feed) and the app log "
               "(search 'live settle'); the usual causes are the score feed not listing the game under the names the ticket "
               "carries, the feed down, LIVE_SETTLE=off, or a sport with no free feed (EuroLeague, cricket, other hockey), "
               "which grades only from the odds vendor's slower scores. Ask Claude to look")
        detail = {"games": len(overdue), "tickets": tickets, "oldest": oldest["key"],
                  "oldest_hours": oldest["hours_overdue"]}
        return Outcome("grading", ALERT, f"{tickets} ticket{'s' if tickets != 1 else ''} open past {GRADING_OVERDUE_HOURS:g} h",
                       [Finding("grading_overdue", str(oldest["key"]),
                                f"{tickets} ticket{'s' if tickets != 1 else ''} not graded {GRADING_OVERDUE_HOURS:g}+ hours after the game",
                                what, fix)], detail)

    # -- incidents ----------------------------------------------------------

    def _open(self, kind: str) -> Optional[dict]:
        return next((i for i in self.state["incidents"] if i["kind"] == kind and i["status"] == "open"), None)

    def _reconcile(self, outcome: Outcome, now: datetime) -> None:
        """Open what is newly wrong, refresh what still is, close what cleared. Only a decisive result (ok/alert)
        may close anything: unknown, skipped and suppressed leave open incidents exactly as they were."""
        if outcome.state not in (OK, ALERT):
            return
        live = {f.kind: f for f in outcome.findings}
        for inc in self.state["incidents"]:
            if inc["status"] == "open" and inc["check"] == outcome.name and inc["kind"] not in live:
                inc["status"] = "resolved"
                inc["resolved_utc"] = _iso(now)
                inc["resolved_text"] = _sentence(f"All clear: {outcome.summary}") + (
                    f" (This was the alert \"{inc['title']}\", raised {_when(inc['opened_utc']):%H:%M} UTC.)")
        for kind, f in live.items():
            inc = self._open(kind)
            if inc:
                inc["current_what"], inc["last_seen_utc"] = f.what, _iso(now)
                continue
            opened = _compact(now)
            self.state["incidents"].append({
                "id": f"watchdog:{_slug(kind)}:{_slug(f.key)}:{opened}", "kind": kind, "check": outcome.name,
                "key": f.key, "title": f.title, "what": f.what, "current_what": f.what, "fix": f.fix, "url": f.url,
                "feed": f.feed, "status": "open", "opened_utc": _iso(now), "last_seen_utc": _iso(now),
                "resolved_utc": None, "resolved_text": None})

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(days=RESOLVED_KEEP_DAYS)
        keep = [i for i in self.state["incidents"]
                if i["status"] == "open" or (_when(i.get("resolved_utc")) or now) > cutoff]
        open_ = [i for i in keep if i["status"] == "open"]
        done = [i for i in keep if i["status"] != "open"][-RESOLVED_KEEP_MAX:]
        self.state["incidents"] = open_ + done

    # -- one tick -----------------------------------------------------------

    def run_once(self) -> dict:
        with self._lock:
            now = self.now()
            outcomes: Dict[str, Outcome] = {}

            def run(name: str, fn: Callable[[], Outcome]) -> Outcome:
                try:
                    out = fn()
                except GitHubUnavailable as exc:
                    out = Outcome(name, UNKNOWN, str(exc), github_down=True)
                except Exception as exc:  # noqa: BLE001 -- one broken check must not blind the others
                    logger.exception("watchdog check %s crashed", name)
                    out = Outcome(name, ERROR, f"the check crashed ({type(exc).__name__}); see the app log")
                outcomes[name] = out
                return out

            run("deploy_stuck", lambda: self.check_deploy_stuck(now))
            run("tests_stuck", lambda: self.check_tests_stuck(now))
            run("capture_run", lambda: self.check_capture_stuck(now))
            run("slate_stuck", lambda: self.check_slate_stuck(now))
            ci = run("ci_tests", lambda: self.check_ci(now))
            run("prod_behind", lambda: self.check_behind(now, ci))
            run("capture", lambda: self.check_capture(now))
            run("health", lambda: self.check_health(now))
            run("ai_spend", lambda: self.check_ai_spend(now))
            run("grading", lambda: self.check_grading(now))
            outcomes["github_reach"] = self._reach(outcomes, now)
            for out in outcomes.values():
                self._reconcile(out, now)
            self._prune(now)
            self.state["last_check_utc"] = _iso(now)
            self.state["checks"] = {n: {"state": o.state, "summary": o.summary, "checked_utc": _iso(now),
                                        "detail": o.detail} for n, o in outcomes.items()}
            self.state["github"] = dict(self.state.get("github") or {}, calls=self.client.calls[-self.client.budget:],
                                        blocked_until=self.client.blocked_until, last_error=self.client.last_error,
                                        remaining=self.client.remaining)
            try:
                self.store.save(self.state)
            except OSError:
                logger.exception("watchdog could not write its state file")
            return self.state

    def _reach(self, outcomes: Mapping[str, Outcome], now: datetime) -> Outcome:
        """The watchdog watching itself: blind when every check that needs GitHub failed to reach it."""
        needing = [outcomes[n] for n in ("deploy_stuck", "ci_tests", "capture", "capture_run", "tests_stuck", "slate_stuck")]
        gh = self.state.setdefault("github", {})
        if not all(o.github_down for o in needing):
            gh["unreachable_since"] = None
            return Outcome("github_reach", OK, "GitHub is answering")
        since = _when(gh.get("unreachable_since")) or now
        gh["unreachable_since"] = _iso(since)
        blind = _minutes(now - since)
        reason = rss.clean(self.client.last_error or needing[0].summary)
        if blind < BLIND_MINUTES:
            return Outcome("github_reach", UNKNOWN, f"GitHub has not answered for {span(blind)}: {reason}")
        what = (f"The watchdog has not been able to see GitHub for {span(blind)} ({reason}), so it cannot tell if a deploy is "
                "stuck or the tests are red. An empty alert feed does not mean all is well while this lasts")
        fix = ("usually GitHub's shared anonymous limit: add a GITHUB_TOKEN secret to the Fly app (steps in "
               "docs/owner/WATCHDOG.md, 'If the watchdog goes blind'), or ignore it if it clears")
        return Outcome("github_reach", ALERT, f"GitHub unreachable for {span(blind)}: {reason}",
                       [Finding("watchdog_blind", "github", "The watchdog cannot see GitHub", what, fix)])


def tick_safely(dog: Watchdog) -> None:
    """One tick that can never kill the loop's thread."""
    try:
        dog.run_once()
    except Exception:  # noqa: BLE001
        logger.exception("watchdog tick failed")


# ---------------------------------------------------------------------------
# reading the state: the feed, the digest, the admin view
# ---------------------------------------------------------------------------

def _load(env: Optional[Mapping], store: Optional[StateStore]) -> dict:
    return (store or StateStore(default_state_path(env))).load()


def feed_alerts(now: datetime, *, env: Optional[Mapping] = None, store: Optional[StateStore] = None,
                include_resolved: bool = True) -> list:
    """The watchdog's items for ``GET /feeds/alerts.rss``, as ``alert_feed.collect(extra=...)`` takes them. Reads
    one small file; never the network; ``[]`` when the watchdog is off or the file is unreadable (a feed must
    answer). Open incidents carry their opened-time snapshot, resolved ones their "All clear" for
    ``RESOLVED_FEED_HOURS``. Health incidents are not repeated while open (the feed already carries them) but
    their all-clear is."""
    if not enabled(env):
        return []
    try:
        state = _load(env, store)
    except Exception:  # noqa: BLE001
        return []
    out = []
    cutoff = now - timedelta(hours=RESOLVED_FEED_HOURS)
    for inc in state.get("incidents") or []:
        opened = _when(inc.get("opened_utc"))
        if opened is None:
            continue
        if inc.get("status") == "open":
            if inc.get("feed"):
                out.append({"kind": f"watchdog_{_slug(inc['kind'])}", "title": inc["title"], "what": inc["what"],
                            "fix": inc["fix"], "pub": opened, "guid": inc["id"], "link": inc.get("url"),
                            "description": f"{_sentence(inc['what'])} Fix: {rss.clean(inc['fix']).rstrip('.')}."})
            continue
        done = _when(inc.get("resolved_utc"))
        if include_resolved and done is not None and done > cutoff:
            out.append({"kind": f"watchdog_{_slug(inc['kind'])}_resolved", "title": f"Resolved: {inc['title']}",
                        "what": inc.get("resolved_text") or "All clear.", "fix": "nothing to do", "pub": done,
                        "guid": inc["id"] + ":resolved", "link": inc.get("url"), "resolved": True,
                        "description": inc.get("resolved_text") or "All clear."})
    return out


def status(*, env: Optional[Mapping] = None, store: Optional[StateStore] = None,
           now: Optional[datetime] = None, started_utc: Optional[str] = None) -> dict:
    """What ``GET /admin/watchdog`` shows: the last check, each check's state, open incidents (live text), the
    recent resolved ones, the commit production runs, and the GitHub budget. No token, header or log in it."""
    env = os.environ if env is None else env
    now = now or _utcnow()
    state = _load(env, store)
    incidents = state.get("incidents") or []
    gh = state.get("github") or {}
    cutoff = now - timedelta(hours=1)
    calls = [t for t in (gh.get("calls") or []) if isinstance(t, (int, float)) and t > cutoff.timestamp()]
    deployed = deployed_version(env)
    open_ = [{"id": i["id"], "kind": i["kind"], "check": i["check"], "title": i["title"], "what": i.get("current_what") or i["what"],
              "fix": i["fix"], "url": i.get("url"), "opened_utc": i["opened_utc"], "last_seen_utc": i.get("last_seen_utc"),
              "in_alerts_feed": bool(i.get("feed"))} for i in incidents if i.get("status") == "open"]
    resolved = [{"id": i["id"], "kind": i["kind"], "title": i["title"], "opened_utc": i["opened_utc"],
                 "resolved_utc": i.get("resolved_utc"), "text": i.get("resolved_text")}
                for i in incidents if i.get("status") != "open"][-10:]
    return {
        "enabled": enabled(env), "switch": switch_word(env),
        "note": None if enabled(env) else "Off: set WATCHDOG=on (deploy/fly.production.toml does for production).",
        "interval_seconds": TICK_SECONDS, "last_check_utc": state.get("last_check_utc"),
        "checks": {n: {k: v.get(k) for k in ("state", "summary", "checked_utc")}
                   for n, v in (state.get("checks") or {}).items()},
        "open_incidents": open_, "recently_resolved": resolved,
        "production_commit": ({"sha": deployed["sha"], "source": deployed["source"]} if deployed
                              else {"sha": None, "source": "not in the image (no GIT_SHA, no VERSION file); inferred from the deploy run when possible"}),
        "process_started_utc": started_utc,
        "github": {"token_present": bool((env.get(ENV_TOKEN) or "").strip()), "calls_last_hour": len(calls),
                   "budget_per_hour": configured_budget(env),
                   "blocked_until": _iso(datetime.fromtimestamp(gh["blocked_until"], timezone.utc))
                   if gh.get("blocked_until") and gh["blocked_until"] > now.timestamp() else None,
                   "last_error": gh.get("last_error"), "ratelimit_remaining": gh.get("remaining")},
        "limits": {"stuck_minutes": dict(STUCK_MINUTES_BY_WORKFLOW), "prod_behind_minutes": BEHIND_MINUTES,
                   "capture_stalled_hours": CAPTURE_STALL_HOURS, "ai_spend_warn": AI_SPEND_WARN,
                   "blind_minutes": BLIND_MINUTES},
    }


# ---------------------------------------------------------------------------
# failing-test names from a job log
# ---------------------------------------------------------------------------

_LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
_UNITTEST = re.compile(r"^(?:FAIL|ERROR): (\S+ \([\w.]+\))")
_PYTEST = re.compile(r"^FAILED (\S+?::\S+)")


def failing_tests_from_log(log: str, limit: int = 5) -> List[str]:
    """Up to ``limit`` distinct failing test names from a unittest or pytest log, in order of appearance.
    unittest prints ``FAIL: test_name (tests.test_mod.Class.test_name)`` lines in its summary; pytest prints
    ``FAILED path::Class::test``. Both are matched after GitHub's per-line timestamp is stripped."""
    seen: List[str] = []
    for raw in log.splitlines():
        line = _LOG_STAMP.sub("", raw.strip())
        match = _UNITTEST.match(line) or _PYTEST.match(line)
        if match and match.group(1) not in seen:
            seen.append(match.group(1))
            if len(seen) >= limit:
                break
    return seen


# ---------------------------------------------------------------------------
# the paid AI analyst's spend
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def router_spend_status(*, env: Optional[Mapping] = None, now: Optional[datetime] = None,
                        usage_path: Optional[os.PathLike] = None) -> Optional[dict]:
    """This month's paid spend in the AI router's meter (src/ai: the AI hounds, the Claude Hound) against
    ``AI_PAID_CAP_USD``, or None when that meter has no file yet. The meter lives beside the app database
    (the Fly volume), so this reads the live number in production, not an image copy."""
    env = os.environ if env is None else env
    now = now or _utcnow()
    from src.ai import router as ai_router
    from src.ai.usage import UsageStore

    path = Path(usage_path) if usage_path is not None else Path(ai_router.default_usage_path())
    if not path.is_file():
        return None
    cap = ai_router.paid_cap_usd(env)
    month = now.strftime("%Y-%m")
    spent = UsageStore(path, clock=lambda: now).total_month_spend(month)
    frac = (spent / cap) if cap > 0 else (1.0 if spent > 0 else 0.0)
    return {"fraction": frac, "spent_usd": spent, "cap_usd": cap, "key": f"router:{month}",
            "label": f"the AI hounds this month ({month}) against AI_PAID_CAP_USD"}


def ai_spend_status(*, env: Optional[Mapping] = None, now: Optional[datetime] = None,
                    root: Optional[Path] = None, router_usage_path: Optional[os.PathLike] = None) -> Optional[dict]:
    """The highest cap fraction across the AI router's monthly meter (``router_spend_status``) and the paid
    analyst's stores (``analyst_spend_status``), or None when neither has a file."""
    try:
        routed = router_spend_status(env=env, now=now, usage_path=router_usage_path)
    except Exception:  # noqa: BLE001 - a broken meter must not take the watchdog down; the analyst check still runs
        logger.exception("watchdog: AI router meter unreadable")
        routed = None
    analyst = analyst_spend_status(env=env, now=now, root=root)
    found = [r for r in (routed, analyst) if r]
    return max(found, key=lambda r: r["fraction"]) if found else None


def analyst_spend_status(*, env: Optional[Mapping] = None, now: Optional[datetime] = None,
                         root: Optional[Path] = None) -> Optional[dict]:
    """The highest cap fraction among the paid analyst's recent runs (and this month, when ``AI_MONTHLY_CAP_USD``
    is set), or None when no usage store exists. A run is the rows sharing a ``run_id`` in one store; its cap is
    ``spend_cap`` in config/analyst.json (dollars and tokens, whichever is closer). Estimates from the API's own
    usage numbers, the same ones the analyst's meter charges."""
    env = os.environ if env is None else env
    now = now or _utcnow()
    if root is None:
        from src import paths
        root = paths.repo_root()
    root = Path(root)
    stores = [root / rel for rel in AI_USAGE_STORES if (root / rel).is_file()]
    if not stores:
        return None
    cap_usd, cap_tokens = AI_DEFAULT_RUN_CAP_USD, None
    try:
        cfg = json.loads((root / "config" / "analyst.json").read_text(encoding="utf-8"))
        cap = cfg.get("spend_cap") or {}
        cap_usd = float(cap.get("max_usd_per_run") or cap_usd)
        cap_tokens = float(cap["max_tokens_per_run"]) if cap.get("max_tokens_per_run") else None
    except (OSError, ValueError, TypeError):
        pass
    window = now - timedelta(hours=AI_RUN_WINDOW_HOURS)
    runs: Dict[tuple, dict] = {}
    month_usd, month = 0.0, now.strftime("%Y-%m")
    for path in stores:
        for row in _read_jsonl(path):
            usd = float(row.get("cost_usd") or 0.0)
            if str(row.get("date") or "").startswith(month):
                month_usd += usd
            at = _when(row.get("logged_utc") or row.get("date"))
            if at is None or at < window:
                continue
            slot = runs.setdefault((path.name, row.get("run_id") or row.get("date")), {"usd": 0.0, "tokens": 0.0, "date": row.get("date")})
            slot["usd"] += usd
            slot["tokens"] += sum(float(row.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"))
    best: Optional[dict] = None
    for (store, run), slot in runs.items():
        frac = max(slot["usd"] / cap_usd if cap_usd else 0.0, slot["tokens"] / cap_tokens if cap_tokens else 0.0)
        if best is None or frac > best["fraction"]:
            best = {"fraction": frac, "spent_usd": slot["usd"], "cap_usd": cap_usd, "key": f"{store}:{run}",
                    "label": f"the analyst's run for {slot['date']} against its per-run cap"}
    monthly_cap = None
    raw = (env.get(ENV_AI_MONTHLY_CAP) or "").strip()
    try:
        monthly_cap = float(raw) if raw else None
    except ValueError:
        monthly_cap = None
    if monthly_cap and monthly_cap > 0 and (best is None or month_usd / monthly_cap > best["fraction"]):
        best = {"fraction": month_usd / monthly_cap, "spent_usd": month_usd, "cap_usd": monthly_cap,
                "key": f"month:{month}", "label": f"this month ({month}) against AI_MONTHLY_CAP_USD"}
    if best is None:
        best = {"fraction": 0.0, "spent_usd": 0.0, "cap_usd": cap_usd, "key": "none",
                "label": "no analyst run in the last 48 hours against its per-run cap"}
    return best


# ---------------------------------------------------------------------------
# production wiring
# ---------------------------------------------------------------------------

def health_alerts_source(started_utc: Optional[Callable[[], Optional[str]]] = None) -> Callable[[datetime], list]:
    """The app's own verdicts as alerts, from the SAME code the alerts feed runs. Called WITHOUT the watchdog's
    own items, so it cannot feed on itself."""
    def source(now: datetime) -> list:
        from src.appstate import alert_feed
        health, error, pauses = alert_feed.gather(now)
        return alert_feed.collect(health, pauses, now=now, health_error=error,
                                  started_utc=started_utc() if started_utc else None)
    return source


def grading_source(now: datetime) -> list:
    """The open tickets past the grading line, from the live settlement loop's own reader (the app's ledgers and cache)."""
    from src.hounds import live_settle
    return live_settle.overdue_tickets(now, hours=GRADING_OVERDUE_HOURS)


def build(*, env: Optional[Mapping] = None, started_utc: Optional[Callable[[], Optional[str]]] = None) -> Watchdog:
    return Watchdog(env=env, started_utc=started_utc, health=health_alerts_source(started_utc),
                    grading=grading_source)


def start_loop(*, ready: Optional[Callable[[], bool]] = None, stop_event: Optional[threading.Event] = None,
               env: Optional[Mapping] = None, tick_s: float = TICK_SECONDS,
               started_utc: Optional[Callable[[], Optional[str]]] = None,
               do_tick: Optional[Callable[[], object]] = None) -> Optional[threading.Thread]:
    """Start the ONE daemon thread, or return None (starting nothing) unless ``WATCHDOG=on``. Waits for
    ``ready()`` (the first cache warm-up pass) like every other loop, then ticks every ``tick_s``."""
    if not enabled(env):
        return None
    event = stop_event if stop_event is not None else threading.Event()
    if do_tick is None:
        dog = build(env=env, started_utc=started_utc)
        do_tick = lambda: tick_safely(dog)       # noqa: E731

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            do_tick()
            if event.wait(tick_s):
                return

    thread = threading.Thread(target=loop, daemon=True, name="watchdog")
    thread.start()
    logger.info("watchdog loop started, tick=%ss", tick_s)
    return thread


def main(argv: Optional[List[str]] = None) -> int:
    """``write-version --gitmeta DIR --out FILE`` (the image build; always exits 0) and ``run`` (one real tick
    from a shell, printing the status; reads GitHub, writes the state file)."""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.ops.watchdog")
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write-version")
    w.add_argument("--gitmeta", required=True)
    w.add_argument("--out", required=True)
    sub.add_parser("run")
    args = parser.parse_args(argv)
    if args.cmd == "write-version":
        sha = write_version(args.gitmeta, args.out)
        print(f"VERSION: {sha}" if sha else "VERSION: not written (the git metadata did not name a commit)")
        return 0
    dog = build()
    dog.run_once()
    print(json.dumps(status(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
