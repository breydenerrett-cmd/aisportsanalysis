"""Email + password login on top of the token sessions, stdlib-only.

WHY THIS EXISTS (owner ask, 2026-10-19)
------------------------------------------
Members had one way in: paste a 43-character bearer token. src/appstate/users.py
explains why that was the right first credential and still is the SESSION
mechanism: this module does not replace tokens. A password only lets a member
EXCHANGE email + password for a fresh token (api/passwords.py POST /auth/login),
issued through the same issuer and ending where their access ends
(src/appstate/access.py). Every authenticated route still sees a token and
nothing else, so none of them changed.

There is no email sender, so there is no reset link and no "forgot password"
mail. Recovery is the admin path in docs/support/FREE_MEMBERS.md: the admin
clears the password, re-issues a token the way support already does, and the
member sets a new password with it.

THE HASH
----------
hashlib.scrypt, n=2**14, r=8, p=1, 32-byte output, a fresh 16-byte random salt
per password. argon2 is not a dependency of this repo and a new native dependency
for one feature is a worse trade than the stdlib's memory-hard KDF. The
parameters are stored with every row (`params`), and verification reads them
from the row, so raising the cost later is a code change that leaves every
existing password verifiable. A stored `params` this module does not recognise
verifies as False, never as an exception.

Verification compares digests with hmac.compare_digest (constant time). The
password is NFKC-normalised first so the same visible string typed on two
keyboards or pasted from a manager is one password.

NO ACCOUNT ENUMERATION
------------------------
`authenticate_password` runs one full scrypt whether or not the email exists or
has a password (it verifies against a throwaway record), and returns None for
every failure. The API layer turns None into one identical response. A person
who has not got the right password learns nothing about whether the address has
an account, and spends the same time learning it.

RATE LIMITS, IN THE DATABASE
------------------------------
10 attempts per 15 minutes and 50 per day, per hashed client address AND per
hashed email. They are rows in `login_attempts`, so a redeploy (this app
redeploys hourly) does not reset them; src/appstate/ratelimit.py's in-process
limiter would have, which is why it is not used here. The check and the insert
are one BEGIN IMMEDIATE transaction, so a burst of parallel requests cannot all
read "9 so far". The email limit applies to ANY string, an address with no
account included, so the limiter itself is not an enumeration oracle.

Honest trade-off: a per-email limit lets a stranger who types someone's address
ten times lock that person's PASSWORD sign-in for fifteen minutes (a day, at
fifty). It cannot lock out the access-code sign-in, which does not pass through
here, and the alternative (no per-email limit) lets a botnet guess one account's
password from a thousand addresses. Rows older than a day are deleted on every
check, so the table cannot grow without bound.

WHAT IS NEVER STORED OR LOGGED
--------------------------------
No raw password, anywhere. No email in `login_attempts` (a sha256 of it). No
exception message in this module carries a password. The password rules below
are the only place a candidate password is inspected.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

from src.appstate import ratelimit
from src.appstate import users as users_store

# ---------------------------------------------------------------------------
# Hash parameters. Changing these is a deliberate, tested act:
# tests/test_passwords.py pins them.
# ---------------------------------------------------------------------------
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16
PARAMS_TAG = f"scrypt:n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P},dklen={SCRYPT_DKLEN}"
_PARAMS_RE = re.compile(r"^scrypt:n=(\d+),r=(\d+),p=(\d+),dklen=(\d+)$")

# ---------------------------------------------------------------------------
# Password rules.
# ---------------------------------------------------------------------------
MIN_PASSWORD_LENGTH = 10
# An upper bound is a courtesy to the hasher, not a security feature: the
# request size is already bounded by the server, and nobody types 200 characters
# by hand. A password manager's longest default is well under this.
MAX_PASSWORD_LENGTH = 200

# A SHORT list on purpose: the 10-character minimum already removes every
# classic short password. These are the 10+ character ones that top the leaked
# lists, plus this product's own name and the obvious sports words. Compared
# lower-cased, and again with trailing digits and punctuation stripped, so
# "Password123!" and "linehound2026" are caught as well as "password123".
COMMON_PASSWORDS = frozenset({
    "password123", "password1234", "passw0rd123", "1234567890", "12345678910",
    "123456789012", "0123456789", "1q2w3e4r5t", "1qaz2wsx3edc", "qwertyuiop",
    "qwertyuiop123", "qwerty12345", "qwerty123456", "asdfghjkl", "asdfghjkl123",
    "zxcvbnm123", "abcdefghij", "abcd123456", "abc1234567", "letmein123",
    "letmein1234", "welcome123", "welcome1234", "iloveyou123", "iloveyou12",
    "admin12345", "administrator", "changeme123", "trustno1234", "monkey1234",
    "dragon1234", "football123", "baseball123", "basketball", "baseball12",
    "sportsbook", "sportsbetting", "bettingodds", "mypassword", "mypassword1",
    "mypassword123", "linehound", "linehound1", "linehound123", "linehound12",
    "linehound2026", "linehoundapp", "samplepassword", "testpassword", "testtest123",
})
_COMMON_BASES = frozenset({
    "password", "passw0rd", "qwertyuiop", "asdfghjkl", "letmein", "welcome",
    "iloveyou", "linehound", "baseball", "football", "basketball", "sportsbook",
    "mypassword", "changeme", "administrator", "trustno1",
})
_TRAILING_NOISE = re.compile(r"[\d\W_]+$")

MAX_EMAIL_LENGTH = 254

# Rate limits: (window in seconds, attempts allowed in that window).
LOGIN_LIMITS: Tuple[Tuple[int, int], ...] = ((15 * 60, 10), (24 * 60 * 60, 50))
_PRUNE_AFTER_S = max(window for window, _ in LOGIN_LIMITS)
SCOPE_IP = "ip"
SCOPE_EMAIL = "email"
SCOPE_PASSWORD_CHANGE = "pwchange"


class PasswordRejected(ValueError):
    """A password the rules refuse. `str(exc)` is the plain sentence the member
    is shown; it never contains the password."""


def _normalise(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def check_password_rules(password, email: str = "") -> str:
    """Return the normalised password if it passes, else raise PasswordRejected
    with a plain message. `email` is the account's address, for the "not your
    email" rule."""
    if not isinstance(password, str) or not password:
        raise PasswordRejected("Choose a password.")
    normalised = _normalise(password)
    if len(normalised) < MIN_PASSWORD_LENGTH:
        raise PasswordRejected(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(normalised) > MAX_PASSWORD_LENGTH:
        raise PasswordRejected(f"Use {MAX_PASSWORD_LENGTH} characters or fewer.")
    lowered = normalised.strip().lower()
    addr = (email or "").strip().lower()
    local = addr.split("@", 1)[0] if addr else ""
    if addr and (lowered == addr or (len(local) >= 3 and lowered == local)):
        raise PasswordRejected("Do not use your email address as your password.")
    if not lowered or len(set(lowered)) <= 2:
        raise PasswordRejected("That password is too simple. Pick something less guessable.")
    base = _TRAILING_NOISE.sub("", lowered)
    if lowered in COMMON_PASSWORDS or base in COMMON_PASSWORDS or base in _COMMON_BASES:
        raise PasswordRejected("That password is too common. Pick something less guessable.")
    return normalised


# ---------------------------------------------------------------------------
# Hashing.
# ---------------------------------------------------------------------------

def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    # maxmem: OpenSSL's default cap is 32 MiB, which n=2**14, r=8 fits, but a
    # stored row with a higher n must still verify, so the cap follows the row.
    maxmem = 128 * r * (n + p + 2) + (1 << 20)
    return hashlib.scrypt(_normalise(password).encode("utf-8"), salt=salt,
                          n=n, r=r, p=p, dklen=dklen, maxmem=maxmem)


@dataclass(frozen=True)
class PasswordRecord:
    """What is stored: hex digest, hex salt, the params tag. repr=False on the
    digest and salt keeps them out of a traceback that prints the object."""
    hash: str
    salt: str
    params: str


def hash_password(password: str) -> PasswordRecord:
    """A fresh salt every call: the same password hashes to a different row for
    every user and every change."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    return PasswordRecord(hash=digest.hex(), salt=salt.hex(), params=PARAMS_TAG)


def verify_password(password: str, record: PasswordRecord) -> bool:
    """Constant-time check of `password` against `record`. Never raises: a
    malformed record is a failed verification."""
    try:
        match = _PARAMS_RE.match(record.params)
        if match is None:
            return False
        n, r, p, dklen = (int(g) for g in match.groups())
        # Refuse absurd stored costs rather than burn memory on a corrupt row.
        if not (2 ** 10 <= n <= 2 ** 20 and 1 <= r <= 32 and 1 <= p <= 16 and 16 <= dklen <= 128):
            return False
        expected = bytes.fromhex(record.hash)
        actual = _scrypt(password, bytes.fromhex(record.salt), n, r, p, len(expected) or dklen)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, MemoryError):
        return False


_dummy_record: Optional[PasswordRecord] = None


def _spend_a_verification(password: str) -> None:
    """Run one full scrypt against a throwaway record, so an unknown email costs
    what a known one costs."""
    global _dummy_record
    if _dummy_record is None:
        # Random bytes, not a hash of anything: building it costs no scrypt (so
        # the FIRST unknown-email request is not slower than the rest) and no
        # password can match it.
        _dummy_record = PasswordRecord(hash=secrets.token_hex(SCRYPT_DKLEN),
                                       salt=secrets.token_hex(SALT_BYTES), params=PARAMS_TAG)
    verify_password(password, _dummy_record)


# ---------------------------------------------------------------------------
# Storage.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """users.py's connection plus this module's two tables, the way testers.py
    does it (one place decides how app.db opens; a test that patches
    `users_store.db_path` redirects this module too)."""
    with users_store._connect(path) as conn:
        _ensure_schema(conn)
        yield conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_passwords (
            user_id INTEGER PRIMARY KEY,
            hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            params TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS login_attempts_lookup "
                 "ON login_attempts (scope, key_hash, at)")


def has_password(user_id: int, *, db: Optional[Path] = None) -> bool:
    with _connect(db) as conn:
        return conn.execute("SELECT 1 FROM user_passwords WHERE user_id = ?",
                            (user_id,)).fetchone() is not None


def _get_record(conn: sqlite3.Connection, user_id: int) -> Optional[PasswordRecord]:
    row = conn.execute("SELECT hash, salt, params FROM user_passwords WHERE user_id = ?",
                       (user_id,)).fetchone()
    return PasswordRecord(hash=row["hash"], salt=row["salt"], params=row["params"]) if row else None


def set_password(user_id: int, new_password: str, *, email: str = "",
                 db: Optional[Path] = None) -> bool:
    """Apply the rules, hash, and store (insert or replace). Returns True if a
    password was REPLACED, False if this is the first one. Raises
    PasswordRejected, with a plain message, before anything is written."""
    normalised = check_password_rules(new_password, email)
    record = hash_password(normalised)
    with _connect(db) as conn:
        existed = conn.execute("SELECT 1 FROM user_passwords WHERE user_id = ?",
                               (user_id,)).fetchone() is not None
        conn.execute(
            "INSERT INTO user_passwords (user_id, hash, salt, params, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
            "hash = excluded.hash, salt = excluded.salt, params = excluded.params, "
            "updated_at = excluded.updated_at",
            (user_id, record.hash, record.salt, record.params, _now_iso()))
    return existed


def clear_password(user_id: int, *,
                   audit: Optional[Callable[[sqlite3.Connection, bool], None]] = None,
                   db: Optional[Path] = None) -> bool:
    """Delete the stored password; True if there was one. `audit(conn, existed)`
    runs on the SAME connection before the commit (the admin route writes its
    audit row there, so the row and the change stand or fall together); an
    exception from it rolls the delete back and propagates."""
    with _connect(db) as conn:
        cur = conn.execute("DELETE FROM user_passwords WHERE user_id = ?", (user_id,))
        existed = cur.rowcount > 0
        if audit is not None:
            audit(conn, existed)
    return existed


def verify_user_password(user_id: int, password: str, *, db: Optional[Path] = None) -> bool:
    """Whether `password` is user_id's current password. Spends a full scrypt
    either way (a user with no password verifies against the throwaway)."""
    with _connect(db) as conn:
        record = _get_record(conn, user_id)
    if record is None:
        _spend_a_verification(password if isinstance(password, str) else "")
        return False
    return verify_password(password if isinstance(password, str) else "", record)


def authenticate_password(email, password, *,
                          db: Optional[Path] = None) -> Optional[users_store.User]:
    """The user whose address and password these are, or None.

    None for EVERY failure: malformed input, unknown email, an account with no
    password, a wrong password. The caller must not distinguish them (see the
    module docstring). One scrypt runs in every case."""
    pw = password if isinstance(password, str) else ""
    addr = email.strip().lower() if isinstance(email, str) else ""
    user = None
    if addr and len(addr) <= MAX_EMAIL_LENGTH and pw and len(pw) <= 4 * MAX_PASSWORD_LENGTH:
        user = users_store.get_user_by_email(addr, db=db)
    if user is None:
        _spend_a_verification(pw[:4 * MAX_PASSWORD_LENGTH])
        return None
    with _connect(db) as conn:
        record = _get_record(conn, user.id)
    if record is None:
        _spend_a_verification(pw)
        return None
    return user if verify_password(pw, record) else None


# ---------------------------------------------------------------------------
# Rate limiting, in the database.
# ---------------------------------------------------------------------------

def _key_hash(scope: str, identity: str) -> str:
    return ratelimit.key_for(f"{scope}:{identity}")


def check_and_record_attempt(keys: List[Tuple[str, str]], *, now: Optional[float] = None,
                             db: Optional[Path] = None) -> Optional[float]:
    """Count one attempt against every (scope, identity) pair in `keys`, atomically.

    Returns None if the attempt is allowed (and has been recorded against every
    key), or the number of seconds until the blocking window frees a slot (and
    NOTHING is recorded: a refused attempt does not lengthen its own lockout).
    `now` is epoch seconds, injectable so tests never sleep.

    Identities are hashed before they touch the table. The whole read-and-insert
    is one BEGIN IMMEDIATE transaction."""
    import time as _time
    when = _time.time() if now is None else float(now)
    hashed = [(scope, _key_hash(scope, identity)) for scope, identity in keys]
    with _connect(db) as conn:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM login_attempts WHERE at < ?", (when - _PRUNE_AFTER_S,))
        worst: Optional[float] = None
        for scope, key in hashed:
            for window, limit in LOGIN_LIMITS:
                rows = conn.execute(
                    "SELECT at FROM login_attempts WHERE scope = ? AND key_hash = ? "
                    "AND at > ? ORDER BY at ASC",
                    (scope, key, when - window)).fetchall()
                if len(rows) >= limit:
                    # The slot that frees first is the (len - limit + 1)th oldest.
                    frees = rows[len(rows) - limit]["at"] + window - when
                    worst = max(worst if worst is not None else 0.0, frees)
        if worst is not None:
            conn.commit()
            return max(worst, 1.0)
        conn.executemany("INSERT INTO login_attempts (scope, key_hash, at) VALUES (?, ?, ?)",
                         [(scope, key, when) for scope, key in hashed])
    return None
