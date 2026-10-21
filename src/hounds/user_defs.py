"""User hounds as the public stats see them: definitions from the app database.

WHY THIS MODULE EXISTS
----------------------
The public numbers (``src.hounds.stats``) are computed from ledgers, and a ledger knows a hound by
its id only. The name, tagline, rule text and owner of a USER hound live in the app database
(``user_store``), so the stats read them through here: one definition dict per hound version, in the
same shape ``src.hounds.house.definitions`` gives the house hounds, so ``stats.summarize`` treats
all hounds alike and a page written against a house hound renders a user hound unchanged.

NOTHING HERE CREATES OR CHANGES A DATABASE. A public read of ``GET /hounds`` must never be what makes
``data/app/app.db`` appear, so a missing file means "no user hounds", not "create an empty one".

``stamp()`` is the cheap fingerprint part: a handful of ints and strings from one aggregate query,
folded into ``Sources.fingerprint`` so a hound created, retired or superseded changes the cache key
even before it has placed a bet.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from src.hounds import user_spec

# One short phrase per side rule, for the "style" chip on a hound's row (the long label is the
# menu's). House hounds describe their approach in a few words; so do builders'.
STYLE = {
    "favourite": "favourites",
    "underdog": "underdogs",
    "home": "home sides",
    "away": "away sides",
    "over": "overs",
    "under": "unders",
    "market_moved_toward": "follows line moves",
    "market_moved_away": "fades line moves",
}


def anonymous_handle(owner_user_id: int) -> str:
    """The anonymous handle: a user's account id is never public, and the same account always gets
    the same handle ("Handler 3F2A")."""
    digest = hashlib.sha256(f"hound-owner:{owner_user_id}".encode()).hexdigest()[:4].upper()
    return f"Handler {digest}"


def owner_display(owner_user_id: int) -> str:
    """What every public page calls a dog's owner: the kennel name the member chose (``member_profile``), else the
    anonymous handle until they set one. Never an email, never the account id."""
    try:
        from src.hounds import member_profile
        name = member_profile.kennel_name_of(owner_user_id)
    except Exception:  # noqa: BLE001 -- a profile table that cannot be read leaves the anonymous handle, never a 500
        name = None
    return name or anonymous_handle(owner_user_id)


def _db_file():
    from src.appstate import users as users_store
    return users_store.db_path()


def db_exists() -> bool:
    try:
        return _db_file().is_file()
    except OSError:
        return False


# The stats cause for a buried dog. It starts with "buried", which is how the kennel news knows to announce a burial
# from the dog's own event (src/hounds/kennel_feed.py) and not a second "put down" from the stats book.
BURIED_CAUSE = "buried by the owner"


def retired_cause(hound: dict) -> str:
    """The graveyard cause for a retired user hound (contract: 'retired by the owner')."""
    reason = (hound.get("retire_reason") or "").strip()
    by = str(hound.get("retired_by") or "")
    if hound.get("status") == "buried":
        return BURIED_CAUSE
    if reason.startswith("superseded by"):
        return reason
    if by.startswith("owner"):
        return "retired by the owner"
    if by == "admin":
        return f"retired by a moderator: {reason}" if reason else "retired by a moderator"
    return f"retired: {reason}" if reason else "retired"


def definition(hound: dict) -> dict:
    """One hound version (a ``user_store`` row dict) as a stats definition."""
    spec = hound["spec"]
    retired = None
    if hound.get("status") in ("retired", "buried"):
        # A buried dog reads as retired to the stats: it leaves the leaderboard's ranking, its record is frozen, and
        # its cause says it was buried. (The headstone itself is outback.py's, from the burial event.)
        retired = {"date": (hound.get("retired_at") or "")[:10] or None,
                   "cause": retired_cause(hound)}
    return {
        "id": hound["id"], "name": hound["name"], "tagline": hound.get("tagline") or "",
        "kind": "user", "category": "numerology" if user_spec.is_gematria(spec) else "mixed",
        "style": ("counts numerical coincidences for each side" if user_spec.is_gematria(spec)
                  else STYLE.get(spec["side_rule"], "")),
        "owner_display": owner_display(hound["owner_user_id"]),
        "sports": [s.lower() for s in spec["sports"]], "markets": list(spec["markets"]),
        "rule_text": user_spec.rule_text(spec), "system_id": None, "card": False,
        "retired": retired, "verdict_sentence": None, "source": "user_store",
        # What the store says the hound is doing. Used only while it has no forward bet yet, so a
        # hound created a minute ago reads "running", not "benched" (the referee's bench rule is
        # about days since the last bet, and there is none).
        "status_hint": hound.get("status"),
        "created_utc": hound.get("created_at"),
    }


def definitions() -> list:
    """Every user hound version, oldest first (retired ones too: they belong in the graveyard)."""
    if not db_exists():
        return []
    from src.hounds import user_store
    return [definition(h) for h in user_store.list_all()]


def get_definition(hound_id: str) -> Optional[dict]:
    if not db_exists():
        return None
    from src.hounds import user_store
    hound = user_store.get_hound(hound_id)
    return definition(hound) if hound else None


def stamp() -> tuple:
    """A cache-key part that changes whenever a hound is created, retired, buried or superseded."""
    if not db_exists():
        return ("user_hounds", None)
    import sqlite3
    from src.hounds import user_store
    try:
        with user_store._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), MAX(created_at), MAX(retired_at), SUM(status = 'retired'), SUM(status = 'buried') "
                "FROM hounds").fetchone()
    except sqlite3.Error:
        return ("user_hounds", "unreadable")
    from src.hounds import member_profile
    # a kennel name shows on every dog's "by <name>", so a rename must change the cache key too
    return ("user_hounds", tuple(row), member_profile.stamp())
