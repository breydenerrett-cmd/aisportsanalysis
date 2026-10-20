"""A member's public profile settings: the kennel name (and whether the one-time "Name your kennel" prompt is done).

WHY THIS IS ITS OWN TABLE. ``users`` belongs to ``src/appstate/users.py`` and holds the login (email, status, plan);
none of it is public, and a column added there would sit one careless ``SELECT *`` from a public payload. The
kennel name IS public, so it lives apart in ``member_profiles`` (same app database, ``CREATE TABLE IF NOT EXISTS``,
additive like ``user_store``), keyed by the account id, and the only way out of this module is a name or a flag:
never an email, never the id.

THE NAME (owner ask 2026-10-19). Until a member sets one, their kennel is the anonymous handle every member dog
already carries ("Handler 21E8", ``user_defs.anonymous_handle``). A name is 2 to 30 characters: letters, digits,
spaces, hyphens and apostrophes, starting and ending with a letter or digit. It runs through the same text filter as
a dog's name (``user_spec.text_problem``: profanity, protected book and league names, reserved words) plus a short
list of claims no kennel may make about itself ("guaranteed", "can't lose"), and it may not look like an anonymous
handle ("Handler 21E8"), which would let one member pass as another.

UNIQUE, CASE-INSENSITIVELY. The identity of a name is its URL slug (``kennels.slug``: "Bob's Dogs", "bobs dogs" and
"BOBS-DOGS" are the SAME kennel; an apostrophe is dropped, not turned into a space), kept in ``kennel_key`` under a unique index, so two members can never share
a public address. The slug is also the kennel's handle in ``kennel.html?u=``; the old anonymous handle keeps
resolving to the renamed kennel (``kennels.resolve_handle``) so a shared link does not break.

EVERY NAME SHOWN COMES FROM HERE. ``user_defs.owner_display`` asks this module, so the kennels index, the kennel
page, the leaderboard's "by <name>", the dog page's "Built by <name>" and the share cards all change with one write.
``stamp()`` goes into the stats cache fingerprint, so a rename rebuilds the cached book.

THE ADMIN CAN SET OR CLEAR IT FOR ANY MEMBER (``POST /admin/users/kennel-name``): a name that slipped past the
filter, or a member who asked support to change it. The same checks apply; clearing returns the member to the
anonymous handle.

Standard library only (no FastAPI).
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

from src.appstate import users as users_store

NAME_MIN, NAME_MAX = 2, 30
_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 '\-]*[A-Za-z0-9])?$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_APOS_RE = re.compile(r"['’]")          # "Bob's Dogs" and "Bobs Dogs" are one kennel: an apostrophe is not a separator
_ANON_SLUG_RE = re.compile(r"^handler-[0-9a-f]{4}$")
#: slugs that are routes or roles, not kennels ("mine" is /hounds/kennels/mine)
_RESERVED_SLUGS = frozenset({"mine", "me", "new", "all", "index"})
#: a kennel may not claim a result for itself (the same line a dog's tagline holds)
_CLAIMS = ("guarantee", "guaranteed", "sure thing", "surething", "risk free", "riskfree", "free money",
           "cant lose", "never lose", "no losing", "lock of the", "fixed games", "insider")

#: read-through cache: owner_display is called once per dog row, so a page of 80 dogs must not be 80 queries
CACHE_TTL_S = 5.0
_cache: dict = {}
_cache_lock = threading.Lock()


class ProfileError(ValueError):
    """A refusal the caller can show: ``code`` is stable, the message is for people."""

    def __init__(self, code: str, message: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(message)


def slug(text: str) -> str:
    """The identity of a kennel name (the same rule as ``kennels.slug`` and the page's ``kennelHandle``)."""
    return _SLUG_RE.sub("-", _APOS_RE.sub("", str(text or "").strip().lower())).strip("-")


def _iso(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS member_profiles (
            user_id INTEGER PRIMARY KEY,
            kennel_name TEXT,
            kennel_key TEXT,
            kennel_set_by TEXT,
            kennel_set_at TEXT,
            kennel_set_reason TEXT,
            prompt_dismissed_at TEXT
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS member_profiles_kennel_key "
                 "ON member_profiles(kennel_key) WHERE kennel_key IS NOT NULL")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


def _db_exists() -> bool:
    try:
        return users_store.db_path().is_file()
    except OSError:
        return False


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def kennel_names() -> Dict[int, str]:
    """{user_id: kennel_name} for every member who has named their kennel. Empty when there is no app database
    (a public read never creates one)."""
    if not _db_exists():
        return {}
    key = str(users_store.db_path())
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT user_id, kennel_name FROM member_profiles "
                                "WHERE kennel_name IS NOT NULL").fetchall()
        names = {int(r["user_id"]): str(r["kennel_name"]) for r in rows}
    except sqlite3.Error:
        names = {}
    with _cache_lock:
        _cache[key] = (time.monotonic(), names)
    return names


def kennel_name_of(user_id: int) -> Optional[str]:
    return kennel_names().get(int(user_id))


def get(user_id: int) -> dict:
    """What the member's own pages need: the name (or None), whether the prompt is still to show. No id, no email."""
    row = None
    if _db_exists():
        try:
            with _connect() as conn:
                row = conn.execute("SELECT kennel_name, prompt_dismissed_at FROM member_profiles WHERE user_id = ?",
                                   (int(user_id),)).fetchone()
        except sqlite3.Error:
            row = None
    name = row["kennel_name"] if row else None
    return {"kennel_name": name, "prompt_dismissed": bool(row and row["prompt_dismissed_at"]),
            "needs_name_prompt": name is None and not (row and row["prompt_dismissed_at"]),
            "limits": limits()}


def limits() -> dict:
    return {"min": NAME_MIN, "max": NAME_MAX, "pattern": "letters, numbers, spaces, hyphens and apostrophes"}


def stamp() -> tuple:
    """A cache-key part that changes whenever a kennel name is set, changed or cleared."""
    if not _db_exists():
        return ("member_profiles", None)
    try:
        with _connect() as conn:
            row = conn.execute("SELECT COUNT(kennel_name), MAX(kennel_set_at), SUM(LENGTH(kennel_key)) "
                               "FROM member_profiles").fetchone()
        return ("member_profiles", tuple(row))
    except sqlite3.Error:
        return ("member_profiles", "unreadable")


def member_since(user_id: int) -> Optional[str]:
    """"October 2026": the month the account was made, and nothing finer (the day is not public)."""
    user = users_store.get_user(int(user_id)) if _db_exists() else None
    try:
        when = datetime.fromisoformat((user.created_at or "").replace("Z", "+00:00")) if user else None
    except ValueError:
        when = None
    return when.strftime("%B %Y") if when else None


# ---------------------------------------------------------------------------
# the name
# ---------------------------------------------------------------------------

def clean(raw) -> str:
    """Whitespace squeezed to single spaces, ends trimmed."""
    return " ".join(str(raw if raw is not None else "").split())


def validate_name(raw, *, user_id: Optional[int] = None) -> tuple:
    """(name, key) for a name the menu accepts, else ProfileError. ``user_id`` is the member asking, so keeping
    their own name (or changing only its capitals) is not a clash with themselves."""
    from src.hounds import user_spec
    name = clean(raw)
    if not (NAME_MIN <= len(name) <= NAME_MAX):
        raise ProfileError("kennel_name_length", f"a kennel name is {NAME_MIN} to {NAME_MAX} characters")
    if not _NAME_RE.match(name) or not re.search(r"[A-Za-z]", name):
        raise ProfileError("kennel_name_characters",
                           "use letters, numbers, spaces, hyphens and apostrophes, with at least one letter")
    problem = user_spec.text_problem(name)
    if problem:
        raise ProfileError("kennel_name_not_allowed", f"that name {problem}")
    squashed = re.sub(r"[^a-z]", "", name.lower())
    if any(c.replace(" ", "") in squashed for c in _CLAIMS):
        raise ProfileError("kennel_name_claim", "a kennel name cannot promise or claim a result")
    key = slug(name)
    if _ANON_SLUG_RE.match(key) or key in _RESERVED_SLUGS:
        raise ProfileError("kennel_name_reserved", "that name is reserved")
    with _connect() as conn:
        clash = conn.execute("SELECT user_id FROM member_profiles WHERE kennel_key = ?", (key,)).fetchone()
    if clash and (user_id is None or int(clash["user_id"]) != int(user_id)):
        raise ProfileError("kennel_name_taken", "another kennel already has that name", 409)
    return name, key


def set_kennel_name(user_id: int, raw, *, actor: str = "owner", reason: Optional[str] = None,
                    now: Optional[datetime] = None) -> dict:
    """Name a member's kennel. ``actor`` is "owner" or "admin" and an admin's ``reason`` is kept beside the name
    (never public). An EMPTY name is a clear and is the admin's only: a member cannot un-name themselves."""
    if users_store.get_user(int(user_id)) is None:
        raise ProfileError("not_found", "no such member", 404)
    stamp_at = _iso(now)
    if clean(raw) == "":
        if actor != "admin":
            raise ProfileError("kennel_name_length", f"a kennel name is {NAME_MIN} to {NAME_MAX} characters")
        with _connect() as conn:
            conn.execute("UPDATE member_profiles SET kennel_name = NULL, kennel_key = NULL, kennel_set_by = ?, "
                         "kennel_set_at = ?, kennel_set_reason = ? WHERE user_id = ?", (actor, stamp_at, reason, int(user_id)))
        clear_cache()
        return get(user_id)
    name, key = validate_name(raw, user_id=user_id)
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            clash = conn.execute("SELECT user_id FROM member_profiles WHERE kennel_key = ? AND user_id != ?",
                                 (key, int(user_id))).fetchone()
            if clash:
                conn.rollback()
                raise ProfileError("kennel_name_taken", "another kennel already has that name", 409)
            conn.execute("INSERT INTO member_profiles (user_id, kennel_name, kennel_key, kennel_set_by, kennel_set_at, "
                         "kennel_set_reason) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                         "kennel_name = excluded.kennel_name, kennel_key = excluded.kennel_key, "
                         "kennel_set_by = excluded.kennel_set_by, kennel_set_at = excluded.kennel_set_at, "
                         "kennel_set_reason = excluded.kennel_set_reason",
                         (int(user_id), name, key, actor, stamp_at, reason))
    except sqlite3.IntegrityError:
        raise ProfileError("kennel_name_taken", "another kennel already has that name", 409)
    clear_cache()
    return get(user_id)


def dismiss_prompt(user_id: int, *, now: Optional[datetime] = None) -> dict:
    """"Not now" on the one-time prompt: it is never shown again (the name can still be set from My kennel)."""
    if users_store.get_user(int(user_id)) is None:
        raise ProfileError("not_found", "no such member", 404)
    with _connect() as conn:
        conn.execute("INSERT INTO member_profiles (user_id, prompt_dismissed_at) VALUES (?, ?) "
                     "ON CONFLICT(user_id) DO UPDATE SET prompt_dismissed_at = excluded.prompt_dismissed_at",
                     (int(user_id), _iso(now)))
    clear_cache()
    return get(user_id)
