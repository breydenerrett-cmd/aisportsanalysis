"""Resolving a dog id, and reading its public numbers without ever waiting for a build.

A dog is one of three things for this package:

  user   a hound someone built (``user_store``): a spec the engine executes, an owner, a version chain.
  house  a pack hound (``src.hounds.pack``): a rule written in code; read-only here.
  other  anything else the leaderboard lists (the AI desk's models, the baselines): it has tickets and a
         record, so it can be asked about, but it cannot be fired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from src.hounds import stats, user_defs, user_spec, user_store, user_view
from src.hounds.contract import to_json

KIND_USER = "user"
KIND_HOUSE = "house"
KIND_OTHER = "other"

_ID_RE = re.compile(r"^[A-Za-z0-9_.@\-]{1,80}$")


@dataclass
class Dog:
    id: str
    kind: str
    name: str
    tagline: str = ""
    hound: Optional[dict] = None          # the user_store row (user dogs)
    house: Any = None                     # the pack Hound object (house dogs)
    owner_user_id: Optional[int] = None
    status: str = "running"
    root_id: str = ""

    @property
    def spec(self) -> Optional[dict]:
        return self.hound["spec"] if self.hound else None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_id(hound_id: Any) -> bool:
    return isinstance(hound_id, str) and bool(_ID_RE.match(hound_id))


def resolve(hound_id: str) -> Optional[Dog]:
    """The dog behind an id, or None when nothing public knows it."""
    if not valid_id(hound_id):
        return None
    if user_defs.db_exists():
        row = user_store.get_hound(hound_id)
        if row is not None:
            return Dog(id=row["id"], kind=KIND_USER, name=row["name"], tagline=row.get("tagline") or "",
                       hound=row, owner_user_id=row["owner_user_id"], status=row["status"],
                       root_id=row["root_id"])
    from src.hounds import pack as pack_mod
    house = pack_mod.BY_ID.get(hound_id)
    if house is not None:
        return Dog(id=house.id, kind=KIND_HOUSE, name=house.name, tagline=house.tagline, house=house,
                   root_id=house.id)
    # a listed dog of another kind (desk model, baseline): known by the cached book only
    book = stats.peek_book()
    data = book.hounds.get(hound_id) if book is not None else None
    if data is not None:
        s = data.summary
        return Dog(id=s.id, kind=KIND_OTHER, name=s.name, tagline=s.tagline or "", status=s.status or "running",
                   root_id=s.id)
    return None


def hound_data(dog: Dog) -> Optional[stats.HoundData]:
    """The public stats for a dog (record, form, tickets), or None while the book is still warming.
    Never builds: a cached book if there is one, else a ledger-only read for a user dog."""
    if dog.kind == KIND_USER:
        return user_view.hound_data(dog.id, kick_build=False)
    book = stats.peek_book()
    if book is None:
        book, _state = stats.get_book_nowait()
    return book.hounds.get(dog.id) if book is not None else None


def summary_json(dog: Dog) -> Optional[dict]:
    data = hound_data(dog)
    return to_json(data.summary) if data is not None else None


def forward_tickets(dog: Dog, limit: Optional[int] = None) -> list:
    """The dog's forward tickets as JSON dicts, newest first (the rehearsal tickets are not in these)."""
    data = hound_data(dog)
    if data is None:
        return []
    rows = [to_json(b) for b in data.bets if getattr(b, "segment", "forward") == "forward"]
    return rows[:limit] if limit else rows


def catchphrase(dog: Dog, summary: Optional[dict] = None) -> str:
    """One line in the dog's own voice: a house dog's catchphrase, a builder's tagline."""
    if dog.kind == KIND_USER:
        return (dog.tagline or "").strip()
    persona = (summary or {}).get("persona") if summary else None
    line = persona.get("catchphrase") if isinstance(persona, dict) else ""
    return (line or dog.tagline or "").strip()


def rule_text(dog: Dog, summary: Optional[dict] = None) -> str:
    if dog.kind == KIND_USER:
        return user_spec.rule_text(dog.spec)
    if dog.kind == KIND_HOUSE and getattr(dog.house, "RULE", ""):
        return dog.house.RULE
    return ((summary or {}).get("rule_text") or "").strip()


def rule_english(dog: Dog, summary: Optional[dict] = None) -> str:
    """The rule in plain English: the spec-to-English renderer when the builder has shipped one, else the
    rule text. Tried defensively (the module and function names are another worker's); never raises."""
    if dog.kind == KIND_USER and dog.spec is not None:
        try:
            import importlib
            mod = importlib.import_module("src.hounds.english")
            for name in ("spec_to_english", "render_spec", "render", "to_english", "explain_spec", "explain"):
                fn = getattr(mod, name, None)
                if callable(fn):
                    out = fn(dog.spec)
                    if isinstance(out, str) and out.strip():
                        return out.strip()
                    if isinstance(out, dict):
                        for key in ("english", "text", "sentence", "rule"):
                            if isinstance(out.get(key), str) and out[key].strip():
                                return out[key].strip()
        except Exception:  # noqa: BLE001 -- the renderer is optional; the rule text always exists
            pass
    return rule_text(dog, summary)


def eastern_date(moment: datetime) -> str:
    try:
        from src.pipeline import snapshots
        return snapshots.official_date(iso(moment))
    except Exception:  # noqa: BLE001
        return iso(moment)[:10]
