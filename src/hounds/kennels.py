"""Kennels: every member's public dogs, grouped by owner (GET /hounds/kennels, GET /hounds/kennels/{handle}).

A KENNEL IS A MEMBER'S DOGS. The public handle is the anonymous owner label every user dog already carries
(``user_defs.owner_display``, "Handler 3F2A") written as a slug ("handler-3f2a"), so the same account always
has the same handle and nothing about the account is exposed: no email, no user id, no token, no billing
state. ``resolve_handle`` accepts either spelling.

EVERY PUBLIC DOG IS LISTED, WHETHER OR NOT IT HAS A BET. A dog a member made a minute ago has no settled bet
and no open ticket, and the leaderboard's qualifying round used to hide it (2026-10-19: two members' dogs
could not be found). A kennel reads the app database's dog list, never the ranked table, so a dog with 0 bets
shows with a zero record and a "new" flag. Retired dogs are not public here (they are in the graveyard, with
their record).

The numbers are the leaderboard's own: the same cached stats book (a ledger-only read for a dog the book does
not know yet), the default season's view. Nothing is computed here but the grouping.

Standard library only (no FastAPI), so the module loads where the app does not.
"""

from __future__ import annotations

import re
from typing import Optional

from src.hounds import seasons, stats, user_defs, user_store, user_view
from src.hounds.contract import to_json

PUBLIC_STATUSES = ("running", "benched")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(label: str) -> str:
    """"Handler 3F2A" -> "handler-3f2a" (also the identity of "handler-3f2a")."""
    return _SLUG_RE.sub("-", str(label or "").strip().lower()).strip("-")


def handle_for(owner_user_id: int) -> str:
    return slug(user_defs.owner_display(owner_user_id))


def _public_rows() -> list:
    """The non-retired user dogs, oldest first. No app database means no member dogs."""
    if not user_defs.db_exists():
        return []
    return [h for h in user_store.list_all() if h.get("status") in PUBLIC_STATUSES]


def _looks(rows: list) -> dict:
    try:
        from src.hounds.interact import store
        by_root = store.get_looks({r["root_id"] for r in rows})
    except Exception:  # noqa: BLE001 -- a look is cosmetic; its table never takes a page down
        return {}
    return {r["id"]: by_root[r["root_id"]] for r in rows if r["root_id"] in by_root}


def _result_word(result) -> str:
    text = str(result or "").lower()
    if text in ("win", "won", "w"):
        return "won"
    if text in ("loss", "lost", "l"):
        return "lost"
    if text in ("push", "void"):
        return text
    return "pending"


def _stats_for(row: dict, book, sid: str):
    data = book.hounds.get(row["id"]) if book is not None else None
    if data is None:
        data = user_view.hound_data(row["id"], kick_build=False)
    return data.view(sid) if data is not None else None


def dog_entry(row: dict, view, look: Optional[dict]) -> dict:
    """One dog as a kennel shows it. ``view`` is the stats view for the season (None when the stats cannot be
    read, which shows as a zero record: never a guess)."""
    summary = to_json(view.summary) if view is not None else {}
    rec = summary.get("record") or {}
    wins, losses, pushes = int(rec.get("wins") or 0), int(rec.get("losses") or 0), int(rec.get("pushes") or 0)
    settled = wins + losses + pushes
    open_bets = int(summary.get("open_bets") or 0)
    last = None
    for bet in (to_json(b) for b in (view.bets if view is not None else [])):
        if bet.get("segment", "forward") == "forward" and not bet.get("refused"):
            last = {"date": bet.get("date"), "game": bet.get("game"), "selection": bet.get("selection"),
                    "price": bet.get("price_average"), "result": _result_word(bet.get("result"))}
            break
    return {
        "id": row["id"], "name": row["name"], "tagline": row.get("tagline") or "", "status": row["status"],
        "version_no": row["version_no"], "look": look,
        "sports": [str(s).lower() for s in (row["spec"].get("sports") or [])],
        "record": {"bets": int(rec.get("bets") or 0), "wins": wins, "losses": losses, "pushes": pushes,
                   "units_average_price": rec.get("units_average_price")},
        "settled": settled, "open_bets": open_bets, "new": settled == 0 and open_bets == 0,
        "last_pick": last, "page_href": f"hound.html?id={row['id']}",
    }


def _units(dog: dict) -> float:
    value = dog["record"].get("units_average_price")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _best(dogs: list) -> Optional[dict]:
    """The dog with the most units among those with a settled bet; None when none has settled."""
    played = [d for d in dogs if d["settled"] > 0]
    if not played:
        return None
    top = max(played, key=lambda d: (_units(d), d["settled"]))
    return {"id": top["id"], "name": top["name"], "record": top["record"], "settled": top["settled"]}


def _grouped(sid: str) -> dict:
    """{handle: {"display": ..., "dogs": [dog entries]}} for every owner with a public dog."""
    rows = _public_rows()
    book = stats.peek_book()
    looks = _looks(rows)
    out: dict = {}
    for row in rows:
        display = user_defs.owner_display(row["owner_user_id"])
        box = out.setdefault(slug(display), {"display": display, "dogs": []})
        box["dogs"].append(dog_entry(row, _stats_for(row, book, sid), looks.get(row["id"])))
    return out


def kennel_list(season: Optional[str] = None) -> dict:
    """Every member with a public dog: handle, label, how many dogs, the best record in the kennel and a few
    faces for the index. Most dogs first, then the better best-record, then the handle."""
    sid = season or seasons.default_id()
    kennels = []
    for handle, box in _grouped(sid).items():
        dogs = box["dogs"]
        kennels.append({
            "handle": handle, "display": box["display"], "dog_count": len(dogs),
            "new_dogs": sum(1 for d in dogs if d["new"]), "best": _best(dogs),
            "dogs": [{"id": d["id"], "name": d["name"], "look": d["look"]} for d in dogs[:4]],
            "href": f"kennel.html?u={handle}",
        })
    kennels.sort(key=lambda k: (-k["dog_count"], -(k["best"]["record"].get("units_average_price") or 0) if k["best"] else 0,
                                k["handle"]))
    return {"kennels": kennels, "count": len(kennels), "season": seasons.meta(sid)}


def resolve_handle(value: str) -> str:
    return slug(value)


def kennel_detail(handle: str, season: Optional[str] = None) -> Optional[dict]:
    """One member's public dogs, or None when no member has that handle (or has no public dog)."""
    sid = season or seasons.default_id()
    box = _grouped(sid).get(resolve_handle(handle))
    if box is None:
        return None
    dogs = box["dogs"]
    return {"handle": resolve_handle(handle), "display": box["display"], "dog_count": len(dogs),
            "best": _best(dogs), "dogs": dogs, "season": seasons.meta(sid)}


def my_kennel(owner_user_id: int, season: Optional[str] = None) -> dict:
    """The signed-in member's own dogs for the "My kennel" page: every dog they have, retired ones last and flagged,
    with the same numbers a public kennel shows, plus their own handle so the page can link to the public view."""
    sid = season or seasons.default_id()
    rows = list(user_store.list_for_owner(owner_user_id)) if user_defs.db_exists() else []
    order = {"running": 0, "benched": 1, "retired": 2}
    rows.sort(key=lambda h: (order.get(h["status"], 3), h["created_at"]))
    book = stats.peek_book()
    looks = _looks(rows)
    dogs = []
    for row in rows:
        entry = dog_entry(row, _stats_for(row, book, sid), looks.get(row["id"]))
        entry["retired"] = row["status"] == "retired"
        entry["builder_href"] = f"build-a-hound.html?from={row['id']}"
        dogs.append(entry)
    return {"handle": handle_for(owner_user_id), "display": user_defs.owner_display(owner_user_id),
            "dog_count": sum(1 for d in dogs if not d["retired"]), "dogs": dogs, "season": seasons.meta(sid)}
