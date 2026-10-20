"""LINEHOUND's email sender: a Resend client, an append-only send log, and nothing else.

WHY THIS FILE IS SMALL ON PURPOSE
---------------------------------
Until 2026-10-20 no code in this repo could send an email (docs/RETENTION_EMAILS.md). The growth playbook's
backlog item 2 (docs/marketing/GROWTH_PLAYBOOK.md, R6/R7/R9) needs three emails: the Keep confirmation, the
nightly result and the Sunday pack. This module is the transport they share. What each email SAYS is in
``email_render.py``; WHO gets one and WHEN is in ``email_jobs.py``; the unsubscribe flag and its signed link are
in ``email_prefs.py``.

STDLIB ONLY. One POST to ``https://api.resend.com/emails`` with ``urllib``; no new dependency, and nothing here
imports FastAPI, so it loads on the Linux CI image that has none.

OFF UNLESS THE KEY IS SET. ``RESEND_API_KEY`` is a secret the owner sets on the Fly app
(docs/owner/RESEND_ATTACH.md). With it unset every send is a no-op that returns ``{"status": "disabled"}``,
logs "email disabled" ONCE per process, writes nothing to the send log, and never raises: a laptop, a test
client and staging all behave this way. ``EMAIL_FROM`` overrides the sender (default ``DEFAULT_FROM``).

NEVER LOGGED: the key, a full address, a message body. Addresses are masked (``b***@g***.com``) everywhere they
could reach a log line or the send log, and provider error text is scrubbed of both before it is kept.

AT MOST ONCE PER (user, kind, date)
-----------------------------------
The send log (``email_send_log.jsonl``, beside the app database on the persistent volume) is append-only and
holds no message bodies. A send writes a ``sending`` row BEFORE the request and a ``sent`` or ``failed`` row
after it, so a crash between the two can never cause a second email: ``sending`` with no later row counts as
sent (at most once beats at least once for a message nobody can recall). A ``failed`` row does not block a
retry on the next job tick, up to ``MAX_ATTEMPTS`` failures per key. Resend is also given an ``Idempotency-Key``
header (its dedupe window is 24 hours), so the one in-request retry cannot double-send either.

RETRIES: one retry, after ``RETRY_DELAY_S``, on a 429, a 5xx or a network error. Every request has a
``TIMEOUT_S`` timeout. A 4xx other than 429 is a refusal (an unverified domain, a bad address) and is not
retried.

SINGLE WRITER. Production runs one machine on sqlite. The log is guarded by a process lock and is read and
written by that one process; nothing here is safe for two writers on one file, and nothing needs to be.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger("linehound.notify.email")

ENV_KEY = "RESEND_API_KEY"
ENV_FROM = "EMAIL_FROM"
DEFAULT_FROM = "LINEHOUND <hounds@linehound.app>"
API_URL = "https://api.resend.com/emails"

TIMEOUT_S = 10.0
RETRY_DELAY_S = 2.0
RETRY_STATUSES = (429,)               # plus every 5xx and a network error (status 0)
MAX_ATTEMPTS = 3                      # failed rows per (user, kind, date) before the job stops trying
USER_AGENT = "linehound-email/1.0"    # Cloudflare in front of some APIs refuses urllib's default agent

KIND_KEEP = "keep"
KIND_NIGHTLY = "nightly"
KIND_SUNDAY = "sunday"
KIND_TEST = "test"

LOG_NAME = "email_send_log.jsonl"
ROW_RUN = "run"                       # a job-run summary row (not a message), for /admin/email/status

STATUS_SENT = "sent"
STATUS_SENDING = "sending"
STATUS_FAILED = "failed"

# Result statuses a caller sees.
R_SENT = "sent"
R_DISABLED = "disabled"
R_DUPLICATE = "duplicate"
R_FAILED = "failed"
R_GAVE_UP = "gave_up"

# (url, headers, body, timeout) -> (status, response body). Status 0 means the request never got an answer
# (timeout, DNS, refused).
Sender = Callable[[str, Mapping[str, str], bytes, float], "tuple[int, bytes]"]

_EMAIL_IN_TEXT = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")

_DISABLED_LOCK = threading.Lock()
_DISABLED_LOGGED = False


# ---------------------------------------------------------------------------
# environment, masking
# ---------------------------------------------------------------------------

def api_key(env: Optional[Mapping] = None) -> Optional[str]:
    source = env if env is not None else os.environ
    value = str(source.get(ENV_KEY) or "").strip()
    return value or None


def enabled(env: Optional[Mapping] = None) -> bool:
    return api_key(env) is not None


def sender_address(env: Optional[Mapping] = None) -> str:
    source = env if env is not None else os.environ
    return str(source.get(ENV_FROM) or "").strip() or DEFAULT_FROM


def mask_email(address: Any) -> str:
    """``b***@g***.com``: enough to tell two addresses apart in a log, not enough to contact anyone."""
    text = str(address or "").strip()
    local, at, domain = text.partition("@")
    if not at or not local or not domain:
        return "***"
    head, dot, tld = domain.rpartition(".")
    if not dot:
        return f"{local[0]}***@{domain[0]}***"
    return f"{local[0]}***@{(head or tld)[0]}***.{tld}"


def scrub(text: Any, *, key: Optional[str] = None, limit: int = 200) -> str:
    """Provider error text made safe to keep: addresses masked, the key removed, length capped."""
    out = str(text or "")
    if key:
        out = out.replace(key, "[key]")
    out = _EMAIL_IN_TEXT.sub(lambda m: mask_email(m.group(0)), out)
    return " ".join(out.split())[:limit]


# ---------------------------------------------------------------------------
# the send log
# ---------------------------------------------------------------------------

def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SendLog:
    """The append-only send log and the index the idempotency checks read.

    The index is rebuilt only when the file's size is not the one this object last saw (a first read, or a
    file someone else appended to), so a job that checks a thousand users reads the file once."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._size: Optional[int] = None
        self._seen = False
        # (user_id, kind, date) -> {"sent": bool, "failed": int, "refs": set}. "sent" is True from the
        # ``sending`` row on (a crash after the request must not allow a second email) until a ``failed`` row
        # for the same attempt says the provider refused it.
        self._keys: dict = {}
        self._dates: dict = {}         # (user_id, kind) -> {date, ...}
        self._rows: list = []

    # -- reading ----------------------------------------------------------
    def _reload_if_changed(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = None
        if self._seen and size == self._size:
            return
        self._keys, self._dates, self._rows = {}, {}, []
        self._size, self._seen = size, True
        if size is None:
            return
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        self._ingest(row)
        except OSError:
            logger.warning("email send log unreadable at %s", self.path)

    def _ingest(self, row: dict) -> None:
        self._rows.append(row)
        if row.get("type") == ROW_RUN:
            return
        key = (row.get("user_id"), row.get("kind"), row.get("date"))
        state = self._keys.setdefault(key, {"sent": False, "failed": 0, "refs": set()})
        self._dates.setdefault(key[:2], set()).add(key[2])
        status = row.get("status")
        if status in (STATUS_SENT, STATUS_SENDING):
            state["sent"] = True
            state["refs"].update(row.get("refs") or [])
        elif status == STATUS_FAILED:
            state["sent"] = False
            state["refs"] = set()
            state["failed"] += 1

    def rows(self) -> list:
        with self._lock:
            self._reload_if_changed()
            return list(self._rows)

    def already_sent(self, user_id, kind: str, date: str) -> bool:
        with self._lock:
            self._reload_if_changed()
            return bool(self._keys.get((user_id, kind, date), {}).get("sent"))

    def failures(self, user_id, kind: str, date: str) -> int:
        with self._lock:
            self._reload_if_changed()
            return int(self._keys.get((user_id, kind, date), {}).get("failed", 0))

    def ever_sent(self, user_id, kind: str) -> bool:
        with self._lock:
            self._reload_if_changed()
            return any(self._keys[(user_id, kind, d)]["sent"] for d in self._dates.get((user_id, kind), ()))

    def refs_sent(self, user_id, kind: str) -> set:
        """Everything already reported to this user in a message of this kind (bet ids, for the nightly)."""
        with self._lock:
            self._reload_if_changed()
            out: set = set()
            for d in self._dates.get((user_id, kind), ()):
                out |= self._keys[(user_id, kind, d)]["refs"]
            return out

    # -- writing ----------------------------------------------------------
    def append(self, row: dict) -> None:
        with self._lock:
            self._reload_if_changed()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(row, sort_keys=True) + "\n"
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
            self._ingest(row)
            try:
                self._size = self.path.stat().st_size
            except OSError:
                self._size = None

    def reserve(self, user_id, kind: str, date: str, *, to: str, refs, now: datetime) -> Optional[str]:
        """Take the key under the lock. Returns None when it is yours, else why not: ``duplicate`` or
        ``gave_up``. Writes the ``sending`` row before returning, so two threads cannot both be told yes."""
        with self._lock:
            self._reload_if_changed()
            state = self._keys.get((user_id, kind, date), {"sent": False, "failed": 0})
            if state["sent"]:
                return R_DUPLICATE
            if state["failed"] >= MAX_ATTEMPTS:
                return R_GAVE_UP
            self.append({"ts": _iso(now), "user_id": user_id, "kind": kind, "date": date,
                         "status": STATUS_SENDING, "to": to, "refs": sorted(refs or ())})
            return None


_LOGS: dict = {}
_LOGS_LOCK = threading.Lock()


def log_path() -> Path:
    """Beside the app database (the Fly volume in production), resolved at call time so a test that points
    APP_DB_PATH at a temp file redirects it."""
    from src.appstate import users as users_store
    return users_store.db_path().parent / LOG_NAME


def default_log() -> SendLog:
    path = log_path()
    with _LOGS_LOCK:
        log = _LOGS.get(str(path))
        if log is None:
            log = _LOGS[str(path)] = SendLog(path)
        return log


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def urllib_sender(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> "tuple[int, bytes]":
    """The real transport. An HTTP error status is returned, not raised; a network failure is status 0."""
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:     # noqa: S310 -- fixed https URL
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), exc.read()
        except Exception:  # noqa: BLE001
            return int(exc.code), b""
    except Exception:  # noqa: BLE001 -- timeout, DNS, refused: all "no answer"
        return 0, b""


def _retryable(status: int) -> bool:
    return status == 0 or status in RETRY_STATUSES or status >= 500


def note_disabled() -> None:
    """Log \"email disabled\" the first time anything asks to send while the key is unset, then never again."""
    global _DISABLED_LOGGED
    with _DISABLED_LOCK:
        if _DISABLED_LOGGED:
            return
        _DISABLED_LOGGED = True
    logger.info("email disabled: %s is not set", ENV_KEY)


def reset_disabled_notice() -> None:
    """Tests only: let the once-per-process 'email disabled' line be logged again."""
    global _DISABLED_LOGGED
    with _DISABLED_LOCK:
        _DISABLED_LOGGED = False


def _request_body(message: Mapping, sender: str) -> bytes:
    payload = {"from": sender, "to": [message["to"]], "subject": message["subject"],
               "html": message["html"], "text": message["text"]}
    if message.get("headers"):
        payload["headers"] = dict(message["headers"])
    return json.dumps(payload).encode("utf-8")


def send(message: Mapping, *, user_id, kind: str, date: str, refs=(), http: Optional[Sender] = None,
         log: Optional[SendLog] = None, env: Optional[Mapping] = None,
         sleep: Callable[[float], None] = time.sleep, now: Optional[datetime] = None) -> dict:
    """Send ``message`` ({to, subject, html, text, headers?}) at most once for (user_id, kind, date).

    Never raises. Returns ``{"status": sent | disabled | duplicate | failed | gave_up, "http": int | None,
    "id": provider id | None, "to": masked address}``. ``http`` is the injected transport (tests: never the
    real network)."""
    masked = mask_email(message.get("to"))
    key = api_key(env)
    if key is None:
        note_disabled()
        return {"status": R_DISABLED, "http": None, "id": None, "to": masked}
    try:
        return _send(message, key, masked, user_id=user_id, kind=kind, date=date, refs=refs,
                     http=http or urllib_sender, log=log or default_log(), env=env, sleep=sleep,
                     now=now or datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 -- the send path must never take a job or a request down
        logger.error("email send crashed for %s kind=%s: %s", masked, kind, scrub(repr(exc), key=key))
        return {"status": R_FAILED, "http": None, "id": None, "to": masked}


def _send(message, key, masked, *, user_id, kind, date, refs, http, log, env, sleep, now) -> dict:
    refused = log.reserve(user_id, kind, date, to=masked, refs=refs, now=now)
    if refused is not None:
        return {"status": refused, "http": None, "id": None, "to": masked}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "User-Agent": USER_AGENT, "Idempotency-Key": f"linehound-{kind}-{user_id}-{date}"}
    body = _request_body(message, sender_address(env))
    status, answer = http(API_URL, headers, body, TIMEOUT_S)
    if _retryable(status):
        sleep(RETRY_DELAY_S)
        status, answer = http(API_URL, headers, body, TIMEOUT_S)
    parsed: dict = {}
    try:
        loaded = json.loads(answer.decode("utf-8")) if answer else {}
        parsed = loaded if isinstance(loaded, dict) else {}
    except ValueError:
        parsed = {}
    if 200 <= status < 300:
        provider_id = str(parsed.get("id") or "") or None
        log.append({"ts": _iso(now), "user_id": user_id, "kind": kind, "date": date,
                    "status": STATUS_SENT, "to": masked, "http": status, "provider_id": provider_id,
                    "refs": sorted(refs or ())})
        return {"status": R_SENT, "http": status, "id": provider_id, "to": masked}
    reason = scrub(parsed.get("message") or parsed.get("name") or "", key=key)
    log.append({"ts": _iso(now), "user_id": user_id, "kind": kind, "date": date,
                "status": STATUS_FAILED, "to": masked, "http": status, "error": reason})
    logger.warning("email to %s kind=%s failed: http %s %s", masked, kind, status, reason)
    return {"status": R_FAILED, "http": status, "id": None, "to": masked}


def record_run(log: SendLog, *, job: str, date: str, counts: Mapping, now: datetime) -> None:
    """One summary row per job run, for the admin status page. Counts only: no address, no body."""
    log.append({"type": ROW_RUN, "ts": _iso(now), "job": job, "date": date, "counts": dict(counts)})


# ---------------------------------------------------------------------------
# the one-line hook the keep flow calls
# ---------------------------------------------------------------------------

def send_keep_confirmation(user, dog, **kwargs) -> dict:
    """THE HOOK. Call this once a free account has saved its first dog::

        from src.notify.email import send_keep_confirmation
        send_keep_confirmation(user, dog)          # user: users.User (id, email); dog: the hounds row (id, name)

    Safe to call from a request: it never raises, it is a no-op while ``RESEND_API_KEY`` is unset, and it
    sends at most one Keep email per user, ever. It makes one HTTP request, so a route that must not wait on
    it calls ``email_jobs.send_keep_confirmation_async`` instead. See ``email_jobs.send_keep_confirmation``."""
    from src.notify import email_jobs
    return email_jobs.send_keep_confirmation(user, dog, **kwargs)
