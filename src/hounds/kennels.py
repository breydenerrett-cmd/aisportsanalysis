"""Kennels: every member's public dogs, grouped by owner (GET /hounds/kennels, GET /hounds/kennels/{handle}).

A KENNEL IS A MEMBER'S DOGS. The public handle is the anonymous owner label every user dog already carries
(``user_defs.owner_display``, "Handler 3F2A") written as a slug ("handler-3f2a"), so the same account always
has the same handle and nothing about the account is exposed: no email, no user id, no token, no billing
state. ``resolve_handle`` accepts either spelling.

KENNEL NAMES (owner ask 2026-10-19). A member can name their kennel (``member_profile``); ``owner_display`` then
returns the name, so the handle (its slug, unique by construction) and every title and "by <name>" follow it. The
old anonymous slug is kept as an ALIAS of the renamed kennel, so a link shared before the rename still lands.

THE PROFILE. ``kennel_detail`` is also the member's public profile: kennel name, member since (month and year),
dog count, the combined paper record and dollars across their public dogs, the best dog and the recent tickets
across all of them. Only fields already public on a dog page are summed; no email, no account id, no stake the
member did not publish.

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

from src.hounds import bankroll, member_profile, seasons, stats, user_defs, user_store, user_view
from src.hounds.contract import to_json

PUBLIC_STATUSES = ("running", "benched")
RECENT_TICKETS = 12

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_APOS_RE = re.compile(r"['’]")      # "Bob's Dogs" -> "bobs-dogs", the same rule as member_profile.slug and kennelHandle


def slug(label: str) -> str:
    """"Handler 3F2A" -> "handler-3f2a" (also the identity of "handler-3f2a")."""
    return _SLUG_RE.sub("-", _APOS_RE.sub("", str(label or "").strip().lower())).strip("-")


def handle_for(owner_user_id: int) -> str:
    return slug(user_defs.owner_display(owner_user_id))


def anonymous_handle_for(owner_user_id: int) -> str:
    """The pre-rename slug ("handler-3f2a"): kept as an alias of the kennel after the member names it."""
    return slug(user_defs.anonymous_handle(owner_user_id))


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
    summary = to_json(bankroll.refreshed(view.summary)) if view is not None else {}
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
        # the dog's paper account (src/hounds/bankroll.py, docs/BANKROLL.md): the shared starting bankroll, what it is
        # now, its return and the 24h / 7d / 30d windows. A member's dog counts the units its owner chose.
        "bankroll": summary.get("bankroll"),
        "settled": settled, "open_bets": open_bets, "new": settled == 0 and open_bets == 0,
        "last_pick": last, "page_href": f"hound.html?id={row['id']}",
    }


def _units(dog: dict) -> float:
    """What a dog is ranked by inside a kennel: the dollars it is up (its bankroll), else its flat units at the
    shared unit for a dog the stats could not give a bankroll for."""
    block = dog.get("bankroll") or {}
    if isinstance(block.get("pnl_usd"), (int, float)):
        return float(block["pnl_usd"])
    value = dog["record"].get("units_average_price")
    return float(value) * bankroll.params().unit_usd if isinstance(value, (int, float)) else float("-inf")


def _best(dogs: list) -> Optional[dict]:
    """The dog with the most paper dollars among those with a settled bet; None when none has settled."""
    played = [d for d in dogs if d["settled"] > 0]
    if not played:
        return None
    top = max(played, key=lambda d: (_units(d), d["settled"]))
    return {"id": top["id"], "name": top["name"], "record": top["record"], "settled": top["settled"],
            "bankroll": top.get("bankroll")}


def _grouped(sid: str) -> dict:
    """{handle: {"display": ..., "dogs": [dog entries]}} for every owner with a public dog."""
    rows = _public_rows()
    book = stats.peek_book()
    looks = _looks(rows)
    out: dict = {}
    for row in rows:
        owner = row["owner_user_id"]
        display = user_defs.owner_display(owner)
        box = out.setdefault(slug(display), {"display": display, "dogs": [], "owner_user_id": owner,
                                              "named": display != user_defs.anonymous_handle(owner),
                                              "aliases": [anonymous_handle_for(owner)], "rows": []})
        box["dogs"].append(dog_entry(row, _stats_for(row, book, sid), looks.get(row["id"])))
        box["rows"].append(row)
    return out


def kennel_list(season: Optional[str] = None) -> dict:
    """Every member with a public dog: handle, label, how many dogs, the best record in the kennel and a few
    faces for the index. Most dogs first, then the better best-record, then the handle."""
    sid = season or seasons.default_id()
    kennels = []
    for handle, box in _grouped(sid).items():
        dogs = box["dogs"]
        kennels.append({
            "handle": handle, "display": box["display"], "named": box["named"], "dog_count": len(dogs),
            "new_dogs": sum(1 for d in dogs if d["new"]), "best": _best(dogs),
            "dogs": [{"id": d["id"], "name": d["name"], "look": d["look"]} for d in dogs[:4]],
            "href": f"kennel.html?u={handle}",
        })
    kennels.sort(key=lambda k: (-k["dog_count"], -_units(k["best"]) if k["best"] else 0, k["handle"]))
    return {"kennels": kennels, "count": len(kennels), "season": seasons.meta(sid)}


def resolve_handle(value: str) -> str:
    return slug(value)


def _find(groups: dict, handle: str) -> Optional[dict]:
    """The kennel a handle means: its current handle, else the anonymous one it had before it was named."""
    key = resolve_handle(handle)
    box = groups.get(key)
    if box is not None:
        return box
    return next((b for b in groups.values() if key in b["aliases"]), None)


def _sum(values) -> Optional[float]:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(sum(nums), 2) if nums else None


def _recent_tickets(box: dict, sid: str, limit: int = RECENT_TICKETS) -> list:
    """The newest forward tickets across the kennel's dogs, each with the dog that made it. The same rows a dog's
    own page lists (no refused pass), newest slate date first."""
    book = stats.peek_book()
    out = []
    for row in box["rows"]:
        view = _stats_for(row, book, sid)
        for bet in (to_json(b) for b in (view.bets if view is not None else [])):
            if bet.get("segment", "forward") != "forward" or bet.get("refused"):
                continue
            out.append({"date": bet.get("date"), "game": bet.get("game"), "selection": bet.get("selection"),
                        "price": bet.get("price_average"), "result": _result_word(bet.get("result")),
                        "dog": {"id": row["id"], "name": row["name"], "href": f"hound.html?id={row['id']}"}})
    out.sort(key=lambda t: (str(t["date"] or ""), str(t["game"] or ""), t["dog"]["name"]), reverse=True)
    return out[:limit]


def _combined(dogs: list) -> dict:
    """The kennel's paper account: the record and dollars of its dogs added up. Each dog starts with its own
    $1,000, so the figure is "dollars up or down across the kennel" and ``return_pct`` is that over the kennel's
    dogs' combined starting bankrolls: an average, never a compounded total."""
    rec = {"bets": 0, "wins": 0, "losses": 0, "pushes": 0}
    for d in dogs:
        for k in rec:
            rec[k] += int(d["record"].get(k) or 0)
    blocks = [d.get("bankroll") for d in dogs if isinstance(d.get("bankroll"), dict)]
    pnl = _sum(b.get("pnl_usd") for b in blocks)
    start = _sum(b.get("start") for b in blocks)
    return {"record": rec, "settled": rec["wins"] + rec["losses"] + rec["pushes"],
            "pnl_usd": pnl, "start_usd": start,
            "return_pct": round(pnl / start * 100.0, 2) if pnl is not None and start else None,
            "open_bets": sum(d["open_bets"] for d in dogs), "currency": bankroll.params().currency,
            "unit_usd": bankroll.params().unit_usd}


def kennel_detail(handle: str, season: Optional[str] = None) -> Optional[dict]:
    """One member's public profile and dogs, or None when no member has that handle (or has no public dog)."""
    sid = season or seasons.default_id()
    box = _find(_grouped(sid), handle)
    if box is None:
        return None
    dogs = box["dogs"]
    return {"handle": slug(box["display"]), "display": box["display"], "title": box["display"],
            "named": box["named"], "dog_count": len(dogs),
            "member_since": member_profile.member_since(box["owner_user_id"]),
            "combined": _combined(dogs), "best": _best(dogs), "recent_tickets": _recent_tickets(box, sid),
            "dogs": dogs, "season": seasons.meta(sid), "bankroll": bankroll.public_block()}


def my_kennel(owner_user_id: int, season: Optional[str] = None) -> dict:
    """The signed-in member's own dogs for the "My kennel" page: every dog they have, retired ones last and flagged,
    with the same numbers a public kennel shows, plus their own handle so the page can link to the public view."""
    sid = season or seasons.default_id()
    rows = list(user_store.list_for_owner(owner_user_id)) if user_defs.db_exists() else []
    # A dog the owner removed ("Remove from my kennel") is gone from this page, with every earlier version of it. Its
    # record is not: it stays on the ledger and its address still opens, saying "Retired by the owner".
    gone = user_store.removed_roots(rows)
    removed = sum(1 for r in rows if r["root_id"] in gone and r["version_of"] is None)
    rows = [r for r in rows if r["root_id"] not in gone]
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
    profile = member_profile.get(owner_user_id) if user_defs.db_exists() else {
        "kennel_name": None, "needs_name_prompt": False, "limits": member_profile.limits()}
    return {"handle": handle_for(owner_user_id), "display": user_defs.owner_display(owner_user_id),
            "kennel_name": profile["kennel_name"], "needs_name_prompt": profile["needs_name_prompt"],
            "name_limits": profile["limits"],
            "dog_count": sum(1 for d in dogs if not d["retired"]), "dogs": dogs, "removed_count": removed,
            "season": seasons.meta(sid)}
