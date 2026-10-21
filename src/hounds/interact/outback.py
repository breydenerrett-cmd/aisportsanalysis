"""Take them out back: a member's dog is buried, its record is frozen and public, and a headstone says so.

THE RULING (Brey, 2026-10-20): taking a dog out back means culling it. It always ends the same way: "kill it and
bury it and grave stone and record is frozen and public, and is posted to a public graveyard but is dead and removed".
The preview that used to carry this name is now "Unleash" (``fire.py``); this is the real thing.

WHAT BURIAL DOES, AND WHAT IT NEVER DOES
  * the dog's status becomes ``buried`` (``user_store.bury_hound``): it stops betting (the engine only runs ``running``
    dogs), it leaves the owner's kennel list and the leaderboard's ranking, and it frees a plan slot (a free account
    keeps one dog, a paid one up to five: ``user_store.create_hound`` counts only dogs that are neither retired nor
    buried);
  * ONE row is appended to ``hound_events`` in the same transaction as the status change. The row holds the
    HEADSTONE, frozen at that moment: the final record, the paper bankroll, the best win, the dates and the epitaph.
    The graveyard reads that row, so a headstone never drifts and never depends on the stats cache being warm;
  * no ledger row is written, changed or removed. Every ticket the dog ever made stays on the append-only ledger and
    its page still opens by its address.

REFUSALS (``rites.RiteError``): a house dog, a dog that is not yours (reads as not found), a dog already buried or
retired, and a dog with a ticket that has not settled ("wait until its open tickets settle": nobody walks away from
a pending loss). The check reads the ledger, not the cached book (see ``rites``). The ledger read and the status
change are two steps, so a ticket the engine writes in the milliseconds between them is not caught; the engine only
writes a ticket at a game's lock time and a dog that is no longer ``running`` is skipped from its next pass, so that
window is a few milliseconds wide. Such a ticket would be on the dog's own page (which reads the ledger) but not on the
headstone, which is frozen at the moment of burial.

THE EPITAPH is a pure function of the dog's rule and its final record (``epitaph``): the same stats always write the
same line, in the product's voice (docs/VOICE.md): short, plain, one dry clause and the record, no emoji, no claim
about money. "Chased steam into a wall. 7-12."

Paper only. Nothing here places or suggests a bet.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from src.hounds import bankroll, stats, user_defs, user_spec, user_store, user_view
from src.hounds.contract import to_json
from src.hounds.interact import common, rites, store
from src.hounds.interact.rites import RiteError

HEADSTONE_VERSION = 1
CONFIRM_FIELD = "confirm"        # the request body must say {"confirm": true}: a stray POST buries nothing

# ---------------------------------------------------------------------------
# the epitaph
# ---------------------------------------------------------------------------

# What a rule is known for, in the fewest words. The side rule of a classic dog; for a custom-rules dog the first of
# its rules' conditions that says something (line movement, the pick being the favourite or the underdog), else its
# side, else the markets.
_TRAIT_BY_SIDE_RULE = {
    "market_moved_toward": "Chased steam", "market_moved_away": "Faded the steam", "favourite": "Backed the chalk",
    "underdog": "Took the dogs", "home": "Stayed home", "away": "Hit the road", "over": "Bet the over",
    "under": "Bet the under",
}
_TRAIT_BY_SIDE = {"home": "Stayed home", "away": "Hit the road", "over": "Bet the over", "under": "Bet the under"}
_TRAIT_DEFAULT = "Followed its rules"

# Clauses by how the record read at the end. Each tier has a few; the dog's id picks one, so two dogs with the same
# rule and record can differ while one dog's epitaph never changes.
_LOSING = ("{trait} into a wall.", "{trait} and found the wall.", "{trait} and the books kept the change.")
_LEVEL = ("{trait} and finished level.", "{trait} and went nowhere fast.", "{trait} and broke even on paper.")
_WINNING = ("{trait} and held its ground.", "{trait} and stayed on its feet.", "{trait} and kept pace.")
_SHORT = ("{trait}, then ran out of road.", "{trait} and was gone before it got going.")
_NONE = "Never got a ticket down."

LOSING_WIN_RATE = 0.45           # under this share of decided bets, with units below zero, the record reads as losing
LEVEL_UNITS = 1.0                # within this many units of even (either side) reads as level


def _walk(tree: Any):
    if isinstance(tree, Mapping):
        if "id" in tree:
            yield tree
        for item in tree.get("items") or []:
            yield from _walk(item)


def trait_of(spec: Mapping) -> str:
    """The few words a dog's rule is remembered by."""
    if not user_spec.is_v2(spec):
        return _TRAIT_BY_SIDE_RULE.get(spec.get("side_rule"), _TRAIT_DEFAULT)
    rules = spec.get("rules") or []
    for rule in rules:
        for cond in _walk(rule.get("when")):
            if cond.get("id") == "steam":
                return "Chased steam" if cond.get("direction") == "toward" else "Faded the steam"
    for rule in rules:
        for cond in _walk(rule.get("when")):
            if cond.get("id") == "role":
                return "Backed the chalk" if cond.get("value") == "favourite" else "Took the dogs"
    for rule in rules:
        if any(m.startswith(("batter_", "pitcher_")) for m in rule.get("markets") or []):
            return "Went after props"
    for rule in rules:
        if rule.get("side") in _TRAIT_BY_SIDE:
            return _TRAIT_BY_SIDE[rule["side"]]
    return _TRAIT_DEFAULT


def record_text(wins: int, losses: int, pushes: int) -> str:
    return f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")


def _pick(options: Sequence[str], seed: str) -> str:
    return options[int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(options)]


def epitaph(spec: Mapping, wins: int, losses: int, pushes: int, units: Optional[float], seed: str) -> str:
    """One line for the headstone: what the dog did, how it ended, the record. Deterministic: the same rule, record and
    seed (the dog's id) always give the same words. The units are the flat figure at the average price; with none
    (no priced win to read) the win rate alone decides."""
    settled = wins + losses + pushes
    record = record_text(wins, losses, pushes)
    if settled == 0:
        return f"{_NONE} {record}."
    trait = trait_of(spec)
    decided = wins + losses
    rate = wins / decided if decided else 0.5
    if settled < 5:
        template = _pick(_SHORT, seed)
    elif (units is not None and units < 0 and rate < LOSING_WIN_RATE) or (units is None and rate < LOSING_WIN_RATE):
        template = _pick(_LOSING, seed)
    elif units is not None and abs(units) <= LEVEL_UNITS:
        template = _pick(_LEVEL, seed)
    elif units is not None and units > 0:
        template = _pick(_WINNING, seed)
    else:
        template = _pick(_LEVEL, seed)
    return f"{template.format(trait=trait)} {record}."


# ---------------------------------------------------------------------------
# the headstone
# ---------------------------------------------------------------------------

def _best_win(bets: Sequence, raw_by_id: Mapping) -> Optional[dict]:
    """The win that paid the most units at the average price, or None. A ticket at -200 or worse is never featured
    (owner ruling 2026-10-19: no such pick on any public card), the same rule the dog page's best bet follows."""
    wins = [b for b in bets if b.result == "win" and not stats.beyond_cap(b) and stats.average_units(b) is not None]
    if not wins:
        return None
    best = max(wins, key=lambda b: (stats.average_units(b), b.date, b.decision_utc or "", b.bet_id))
    raw = raw_by_id.get(best.bet_id) or {}
    game = f"{raw['away_team']} at {raw['home_team']}" if raw.get("away_team") and raw.get("home_team") else ""
    return {"date": best.date, "game": game, "selection": best.selection_text or raw.get("selection") or "",
            "price": best.price_average if best.price_average is not None else best.price,
            "units": round(stats.average_units(best), 2)}


def build_headstone(hound: Mapping, rows: Sequence, *, died: datetime, look: Optional[dict] = None) -> dict:
    """The frozen headstone for a hound row, from the ledger rows in hand. Pure: no store is written."""
    defn = user_defs.definition(dict(hound, status="running", retired_at=None))      # the numbers as of now, not "retired"
    data = user_view._from_ledger(defn, rows)                                         # noqa: SLF001 -- ledger-only, no board scan
    summary = to_json(bankroll.refreshed(data.summary))
    rec = summary.get("record") or {}
    wins, losses, pushes = int(rec.get("wins") or 0), int(rec.get("losses") or 0), int(rec.get("pushes") or 0)
    units = rec.get("units_average_price")
    spec = hound["spec"]
    bets = rites.forward_bets(hound["id"], rows)
    raw_by_id = {r.get("bet_id"): r for r in rows if r.get("hound_id") == hound["id"] and r.get("bet_id")}
    box = summary.get("bankroll") or {}
    root = user_store.get_hound(hound["root_id"]) or hound
    born = (root.get("created_at") or hound["created_at"])[:10]
    return {
        "headstone_version": HEADSTONE_VERSION,
        "hound_id": hound["id"], "root_id": hound["root_id"], "name": hound["name"],
        "tagline": hound.get("tagline") or "",
        "born": born, "died": common.iso(died)[:10], "died_utc": common.iso(died),
        "version_no": hound["version_no"], "trained_times": user_store.trained_count(hound["root_id"]),
        "sports": [str(s).lower() for s in spec.get("sports") or []],
        "color": spec.get("color", "ember"), "badge": spec.get("badge", "bone"), "look": look,
        "record": {"bets": wins + losses + pushes, "wins": wins, "losses": losses, "pushes": pushes,
                   "units_average_price": units},
        "bankroll": {"start": box.get("start"), "final": box.get("current"), "pnl_usd": box.get("pnl_usd"),
                     "return_pct": box.get("return_pct")},
        "best_win": _best_win(bets, raw_by_id),
        "epitaph": epitaph(spec, wins, losses, pushes, units, hound["id"]),
        "frozen": True,
    }


def _look_of(root_id: str) -> Optional[dict]:
    try:
        return store.get_look(root_id)
    except Exception:  # noqa: BLE001 -- a look is cosmetic; its table never stops a burial
        return None


# ---------------------------------------------------------------------------
# the rite
# ---------------------------------------------------------------------------

def bury(dog: Optional[common.Dog], user_id: int, *, confirmed: bool = False, now: Optional[datetime] = None,
         rows: Optional[Sequence] = None, ledger_path: Optional[str] = None, db=None) -> dict:
    """Take ``dog`` out back for ``user_id``. Returns ``{"headstone", "freed_slot", ...}`` or raises ``RiteError``.

    ``confirmed`` is the second tap's word: the page asks twice, and the server will not bury without hearing it
    (a script that POSTs to the route without ``{"confirm": true}`` gets a 400 and the dog is untouched)."""
    dog = rites.guard(dog, user_id)
    if not confirmed:
        raise RiteError("confirm_required", f"Say it again to bury {dog.name}: send confirm true. This cannot be undone.", 400)
    moment = now or common.now_utc()
    rows = rites.read_rows(ledger_path) if rows is None else rows
    rites.require_all_settled(dog, rites.forward_bets(dog.id, rows), moment)
    hound = user_store.get_hound(dog.id, db=db)
    if hound is None:
        raise RiteError("not_found", "no such dog", 404)
    stone = build_headstone(hound, rows, died=moment, look=_look_of(dog.root_id))
    try:
        user_store.bury_hound(dog.id, owner_user_id=user_id, payload=stone, now=moment, db=db)
    except user_store.StoreError as exc:
        status = {"not_found": 404, "already_buried": 409, "retired": 409}.get(exc.code, 400)
        raise RiteError(exc.code, str(exc), status)
    return {"headstone": public_headstone({"hound_id": dog.id, "owner_user_id": user_id, "created_at": common.iso(moment),
                                           "payload": stone}),
            "freed_slot": True,
            "slot_note": "Its slot is free: you can build another dog.",
            "paper_only": True}


# ---------------------------------------------------------------------------
# reading headstones (public)
# ---------------------------------------------------------------------------

def public_headstone(event: Mapping) -> dict:
    """A burial event as the graveyard shows it: the frozen stone plus the kennel it came from. The owner's account id
    is never in it; the kennel is the public label every dog already carries."""
    stone = dict(event.get("payload") or {})
    owner = event.get("owner_user_id")
    kennel = None
    if owner is not None:
        try:
            from src.hounds import kennels
            display = user_defs.owner_display(owner)
            kennel = {"display": display, "handle": kennels.slug(display), "href": f"kennel.html?u={kennels.slug(display)}"}
        except Exception:  # noqa: BLE001 -- a kennel label that cannot be read leaves the stone without one
            kennel = None
    stone.update({"kennel": kennel, "page_href": f"hound.html?id={stone.get('hound_id') or event.get('hound_id')}",
                  "buried_utc": event.get("created_at") or stone.get("died_utc"), "paper_only": True})
    return stone


def headstones(*, owner_user_id: Optional[int] = None, db=None) -> list:
    """Every headstone, newest burial first. ``owner_user_id`` narrows to one kennel's. [] when there is no app
    database: a public read never creates one."""
    if not user_defs.db_exists():
        return []
    events = user_store.list_events(user_store.EVENT_BURIED, owner_user_id=owner_user_id, db=db)
    return [public_headstone(e) for e in events]


def headstone_for(hound_id: str, *, db=None) -> Optional[dict]:
    """The headstone of one buried dog, or None when it is not buried (or not known)."""
    if not user_defs.db_exists():
        return None
    hound = user_store.get_hound(hound_id, db=db)
    if hound is None or hound["status"] != user_store.STATUS_BURIED:
        return None
    for event in user_store.list_events(user_store.EVENT_BURIED, root_id=hound["root_id"], db=db):
        if event["hound_id"] == hound_id:
            return public_headstone(event)
    return None
