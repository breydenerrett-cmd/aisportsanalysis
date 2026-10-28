"""Read-only research feed (owner ask 2026-10-28): every hound's bets and every hound version, with no personal data.

Pure helpers, importable without FastAPI; the routes live in api/research_read.py. Reuses ``bet_export.build_rows`` for the rows
and ``common.hound_data`` for the book, so a row here is the same row the spreadsheet export shows. Never writes anything.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Iterator, List, Optional

from src.hounds import bet_export, user_store
from src.hounds.interact import common

TOKEN_ENV = "RESEARCH_READ_TOKEN"


def token_ok(presented: Optional[str], env: Optional[Dict[str, str]] = None) -> bool:
    """True only when the feature is on (env var set and non-empty) and the presented token matches. Compares sha256 digests."""
    expected = (env if env is not None else os.environ).get(TOKEN_ENV, "")
    if not expected or not presented:
        return False
    return hmac.compare_digest(hashlib.sha256(presented.encode("utf-8")).digest(),
                               hashlib.sha256(expected.encode("utf-8")).digest())


def _user_versions() -> List[dict]:
    if not common.user_defs.db_exists():
        return []
    return user_store.list_all()


def hound_records() -> List[Dict[str, Any]]:
    """Every hound version: house/AI/other dogs (one version each) and every member version, retired included."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for h in _user_versions():
        dog = common.resolve(h["id"])
        seen.add(h["id"])
        out.append({"hound_id": h["id"], "name": h["name"], "kind": "member", "root_id": h["root_id"],
                    "version_no": h["version_no"], "version_of": h["version_of"], "status": h["status"],
                    "rule_text": common.rule_text(dog) if dog is not None else "", "spec": h["spec"],
                    "created_at": h["created_at"], "retired_at": h["retired_at"], "retire_reason": h["retire_reason"]})
    from src.hounds import pack as pack_mod
    from src.hounds import stats
    ids = list(pack_mod.BY_ID)
    book = stats.peek_book()
    if book is not None:
        ids += [i for i in book.hounds if i not in pack_mod.BY_ID]
    for hid in ids:
        if hid in seen:
            continue
        seen.add(hid)
        dog = common.resolve(hid)
        if dog is None:
            continue
        out.append({"hound_id": dog.id, "name": dog.name, "kind": dog.kind, "root_id": dog.root_id or dog.id, "version_no": 1,
                    "version_of": None, "status": dog.status, "rule_text": common.rule_text(dog), "spec": None,
                    "created_at": None, "retired_at": None, "retire_reason": None})
    return out


def bet_rows(*, hound_id: Optional[str] = None, since: Optional[str] = None, now: Any = None) -> Iterator[Dict[str, Any]]:
    """One dict per bet across all hounds and versions, tagged with hound_id, root_id, version_no, version_status."""
    for rec in hound_records():
        if hound_id and rec["hound_id"] != hound_id and rec["root_id"] != hound_id:
            continue
        dog = common.resolve(rec["hound_id"])
        data = common.hound_data(dog) if dog is not None else None
        if data is None:
            continue
        for row in bet_export.build_rows(data.view("all"), now=now):
            if since and (row.get("date") or "") < since:
                continue
            row = dict(row)
            row.update(hound_id=rec["hound_id"], root_id=rec["root_id"], version_no=rec["version_no"],
                       version_status=rec["status"])
            yield row
