"""The unsubscribe flag, the signed link that flips it, and the places a link points.

ONE FLAG PER USER. ``email_prefs`` is a table in the app database (same file, same
``CREATE TABLE IF NOT EXISTS`` pattern as ``customers.py`` and ``user_store.py``; no existing table is altered).
A row exists only for a user who unsubscribed. The nightly result and the Sunday pack respect it; the Keep
confirmation is the one transactional message a person asked for by keeping a dog, so it is sent once
regardless, and it carries the same link.

THE LINK IS SIGNED, NOT A LOGIN. ``token(user_id)`` is ``<user_id>.<hmac>``: an HMAC-SHA256 of the user id under
a server secret, truncated to 32 hex characters and compared in constant time. It can do exactly one thing,
turn that user's emails off, so it needs no expiry (an old email's link must keep working) and it can never
sign anyone in (the survival dashboard lists a link-carries-a-token sign-in defect; this is not that). The secret
is ``EMAIL_SIGNING_SECRET`` if set, else a random one created once beside the app database
(``email_signing.key``, mode 0600, on the persistent volume) so the owner has nothing to configure.

Standard library only (no FastAPI).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import quote

from src.appstate import users as users_store

logger = logging.getLogger("linehound.notify.prefs")

ENV_SECRET = "EMAIL_SIGNING_SECRET"
ENV_BASE_URL = "PUBLIC_BASE_URL"          # the variable src/appstate/billing.py already reads
DEFAULT_BASE_URL = "https://linehound.app"
SECRET_FILE = "email_signing.key"
MAC_HEX = 32


# ---------------------------------------------------------------------------
# the flag
# ---------------------------------------------------------------------------

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS email_prefs ("
                 "user_id INTEGER PRIMARY KEY, unsubscribed_at TEXT NOT NULL)")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


def is_unsubscribed(user_id: int, *, db: Optional[Path] = None) -> bool:
    with _connect(db) as conn:
        return conn.execute("SELECT 1 FROM email_prefs WHERE user_id = ?", (user_id,)).fetchone() is not None


def unsubscribed_ids(*, db: Optional[Path] = None) -> set:
    with _connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT user_id FROM email_prefs").fetchall()}


def set_unsubscribed(user_id: int, value: bool = True, *, db: Optional[Path] = None,
                     now: Optional[datetime] = None) -> bool:
    """Flip the flag. Idempotent; True when the user is unsubscribed afterwards."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect(db) as conn:
        if value:
            conn.execute("INSERT OR IGNORE INTO email_prefs (user_id, unsubscribed_at) VALUES (?, ?)",
                         (user_id, stamp))
        else:
            conn.execute("DELETE FROM email_prefs WHERE user_id = ?", (user_id,))
    return value


# ---------------------------------------------------------------------------
# the signed link
# ---------------------------------------------------------------------------

def _secret_path() -> Path:
    return users_store.db_path().parent / SECRET_FILE


def signing_secret(env: Optional[dict] = None, *, path: Optional[Path] = None) -> bytes:
    source = env if env is not None else os.environ
    configured = str(source.get(ENV_SECRET) or "").strip()
    if configured:
        return configured.encode("utf-8")
    target = path or _secret_path()
    try:
        return target.read_text(encoding="utf-8").strip().encode("utf-8")
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL: if two processes race to create it, one wins and the other reads the winner's.
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
    except FileExistsError:
        return target.read_text(encoding="utf-8").strip().encode("utf-8")
    except OSError:
        logger.warning("could not persist the email signing secret; links signed now will not survive a restart")
    return value.encode("utf-8")


def _mac(user_id: int, secret: bytes) -> str:
    return hmac.new(secret, f"unsubscribe:{int(user_id)}".encode("utf-8"), hashlib.sha256).hexdigest()[:MAC_HEX]


def token(user_id: int, *, secret: Optional[bytes] = None) -> str:
    return f"{int(user_id)}.{_mac(user_id, secret or signing_secret())}"


def verify(candidate, *, secret: Optional[bytes] = None) -> Optional[int]:
    """The user id a token is for, or None for anything that is not a token this server signed."""
    if not isinstance(candidate, str) or len(candidate) > 80:
        return None
    head, dot, mac = candidate.partition(".")
    if not dot or not head.isdigit() or len(head) > 12:
        return None
    expected = _mac(int(head), secret or signing_secret())
    if not hmac.compare_digest(mac.encode("utf-8"), expected.encode("utf-8")):
        return None
    return int(head)


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------

def base_url(env: Optional[dict] = None) -> str:
    source = env if env is not None else os.environ
    return (str(source.get(ENV_BASE_URL) or "").strip().rstrip("/")) or DEFAULT_BASE_URL


def unsubscribe_url(user_id: int, *, env: Optional[dict] = None, secret: Optional[bytes] = None) -> str:
    return f"{base_url(env)}/email/unsubscribe?t={quote(token(user_id, secret=secret), safe='')}"


def dog_url(hound_id: str, campaign: str, *, env: Optional[dict] = None) -> str:
    return (f"{base_url(env)}/web/hound.html?id={quote(str(hound_id), safe='')}"
            f"&utm_source=email&utm_medium=email&utm_campaign={quote(campaign, safe='')}")


def leaderboard_url(campaign: str, *, env: Optional[dict] = None) -> str:
    return f"{base_url(env)}/web/hounds.html?utm_source=email&utm_medium=email&utm_campaign={quote(campaign, safe='')}"


def kennel_url(campaign: str, *, env: Optional[dict] = None) -> str:
    return f"{base_url(env)}/web/kennel.html?utm_source=email&utm_medium=email&utm_campaign={quote(campaign, safe='')}"


# ---------------------------------------------------------------------------
# the postal address (CAN-SPAM) from config/business.json, if the owner has put one there
# ---------------------------------------------------------------------------

POSTAL_KEY = "postal_address"


def postal_address(config_path: Optional[Path] = None) -> Optional[str]:
    """The owner's mailing address as one line, or None. NEVER invented: with no ``postal_address`` in
    config/business.json the footer simply has none, and docs/owner/RESEND_ATTACH.md lists it as an open
    owner item. The value may be a string or an object with street/city/region/postal_code lines."""
    from src.paths import repo_root
    path = config_path or (repo_root() / "config" / "business.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get(POSTAL_KEY)
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(raw, str):
        text = " ".join(raw.split())
        return text or None
    if isinstance(raw, dict):
        parts = [str(raw.get(k) or "").strip() for k in ("name", "street", "city", "region", "postal_code", "country")]
        text = ", ".join(p for p in parts if p)
        return text or None
    return None
