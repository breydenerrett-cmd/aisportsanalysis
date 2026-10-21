"""What the dog page's kit and the Training camp page read.

``kit`` answers "what can THIS visitor do on THIS dog's page": the page shows only what is real (owner-only
buttons appear for the owner alone; the server checks again on every write). ``mine`` is the Training camp's
"Your dogs in training": each of a signed-in owner's dogs with its season record, its last five tickets, the
feedback it has received and the suggestions waiting for the owner.

Nothing here computes a statistic: the record, form and verdict come from the same cached stats the leaderboard
shows (``common.summary_json``), the tickets from the same ledgers, the counts from the two small tables of
``store``. The suggestions and the notes are text strangers wrote, passed through the text filter on the way
in and shown to the owner without who wrote them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.hounds import user_store
from src.hounds.interact import ask, common, fire, manual, store


def look_of(dog: common.Dog) -> Optional[dict]:
    if dog.kind != common.KIND_USER:
        return None
    try:
        return store.get_look(dog.root_id)
    except Exception:  # noqa: BLE001 -- a look is cosmetic; its table never takes a page down
        return None


def kit(dog: common.Dog, viewer_id: Optional[int], *, now: Optional[datetime] = None) -> dict:
    now = now or common.now_utc()
    owner = dog.kind == common.KIND_USER and viewer_id is not None and dog.owner_user_id == viewer_id
    fb = _counts(dog)
    alive = dog.status in ("running", "benched")
    out = {
        "dog_id": dog.id, "kind": dog.kind, "name": dog.name, "status": dog.status,
        "is_owner": owner, "signed_in": viewer_id is not None,
        # a buried dog has nothing to unleash: it is gone from the pack (a retired one still shows what its rule would pick)
        "can_fire": dog.kind in (common.KIND_USER, common.KIND_HOUSE) and dog.status != "buried",
        # the two rites (src/hounds/interact/outback.py, training.py): the owner of a live member dog. The server
        # checks again on the write and says why when it refuses (an open ticket, too few new bets).
        "can_train": bool(owner and alive), "can_out_back": bool(owner and alive),
        "trained_times": _trained_times(dog), "coached_from": _coached_from(dog),
        "buried": dog.status == "buried",
        "can_record_manual": bool(owner and dog.status == "running"),
        "can_customize": owner, "can_suggest": dog.kind == common.KIND_USER and not owner,
        "look": look_of(dog), "feedback": fb,
        "manual": {"limit_per_day": manual.PER_DAY_LIMIT,
                   "remaining_today": manual.remaining_today(dog.id, now) if dog.kind == common.KIND_USER else 0},
        "builder_href": f"build-a-hound.html?from={dog.id}" if dog.kind == common.KIND_USER else None,
        "paper_only": True,
    }
    if viewer_id is not None:
        try:
            out["my_votes"] = store.my_votes(dog.root_id, viewer_id)
        except Exception:  # noqa: BLE001
            out["my_votes"] = {}
    return out


def _trained_times(dog: common.Dog) -> int:
    """How many times this dog's lineage has been sent to training ("Trained xN"); 0 for a house dog."""
    if dog.kind != common.KIND_USER:
        return 0
    try:
        return user_store.trained_count(dog.root_id)
    except Exception:  # noqa: BLE001 -- a badge never takes the kit down
        return 0


def _coached_from(dog: common.Dog) -> Optional[str]:
    return (dog.hound or {}).get("coached_from") if dog.kind == common.KIND_USER else None


def _counts(dog: common.Dog) -> dict:
    try:
        return store.counts(dog.root_id)
    except Exception:  # noqa: BLE001
        return {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0}


def mine(user_id: int, *, now: Optional[datetime] = None) -> dict:
    """The caller's dogs for the Training camp, running ones first."""
    now = now or common.now_utc()
    rows = [r for r in user_store.list_for_owner(user_id) if r["status"] != user_store.STATUS_BURIED]   # buried dogs are in the graveyard
    order = {"running": 0, "benched": 1, "retired": 2}
    rows.sort(key=lambda h: (order.get(h["status"], 3), h["created_at"]))
    dogs = []
    for row in rows:
        dog = common.resolve(row["id"])
        if dog is None:
            continue
        summary = common.summary_json(dog)
        tickets = common.forward_tickets(dog, limit=5)
        rec = (summary or {}).get("record") or {}
        fb = _counts(dog)
        try:
            suggestions = store.suggestions_for_owner(dog.root_id, limit=5)
            notes = store.notes_for_owner(dog.root_id, limit=5)
        except Exception:  # noqa: BLE001
            suggestions, notes = [], []
        mt = manual.tickets(dog.id, now=now)
        dogs.append({
            "id": dog.id, "name": dog.name, "tagline": dog.tagline, "status": dog.status,
            "version_no": row["version_no"], "trained_times": _trained_times(dog), "look": look_of(dog),
            # the sports this dog bets (lower case, as GET /hounds/kennels/mine says them): Live offers a game only the dogs that bet its sport
            "sports": [str(x).lower() for x in ((row.get("spec") or {}).get("sports") or [])],
            "record": rec, "verdict": (summary or {}).get("verdict"), "open_bets": (summary or {}).get("open_bets"),
            "last_tickets": tickets, "feedback": {k: fb[k] for k in ("good", "bad", "notes", "suggestions")},
            "feedback_notes": notes, "suggestions": suggestions,
            "manual": dict(manual.record_summary(mt), remaining_today=manual.remaining_today(dog.id, now)),
            "page_href": f"hound.html?id={dog.id}", "builder_href": f"build-a-hound.html?from={dog.id}",
            "warming": summary is None,
        })
    return {"dogs": dogs, "count": len(dogs), "paper_only": True}


def decorate_fire(dog: common.Dog, out: dict, viewer_id: Optional[int], *, now: Optional[datetime] = None) -> dict:
    """The fire preview as the page gets it: the internal ledger row dropped, and for each pick what THIS viewer may
    do about it (only the owner of a running builder dog can record a manual pick, and only from a fresh board,
    once per game and market, within the five a day)."""
    now = now or common.now_utc()
    owner = dog.kind == common.KIND_USER and viewer_id is not None and dog.owner_user_id == viewer_id
    already: set = set()
    remaining = 0
    if dog.kind == common.KIND_USER:
        remaining = manual.remaining_today(dog.id, now)
        already = {t["bet_id"] for t in manual.tickets(dog.id, now=now)}
    for pick in out["picks"]:
        pick.pop("row", None)
        blocked = None
        if not owner:
            blocked = "only the owner can record a manual pick" if dog.kind == common.KIND_USER else "house dogs are read only"
        elif dog.status != "running":
            blocked = f"this dog is {dog.status}"
        elif pick["stale"]:
            blocked = f"the newest board is more than {fire.user_engine.MAX_BOARD_AGE_MINUTES} minutes old"
        elif manual.manual_bet_id(dog.id, pick["event_id"], pick["market"]) in already:
            blocked = "already recorded as a manual pick"
        elif remaining <= 0:
            blocked = f"{manual.PER_DAY_LIMIT} manual picks a day is the limit"
        pick["manual"] = {"can_record": blocked is None, "blocked": blocked}
    out["viewer_is_owner"] = owner
    out["manual_remaining_today"] = remaining if owner else None
    return out


def ask_context(dog: common.Dog, viewer_id: Optional[int], *, now: Optional[datetime] = None,
                fire_fn=None, tips: Optional[list] = None, earlier_fn=None, backtest_fn=None) -> ask.AskContext:
    """The facts an answer is built from, gathered once."""
    now = now or common.now_utc()
    summary = common.summary_json(dog)
    trigger = ""
    if dog.kind == common.KIND_HOUSE:
        try:
            from src.hounds import dials
            trigger = dials.TRIGGERS.get(dog.id, "")
        except Exception:  # noqa: BLE001
            trigger = ""
    owner = dog.kind == common.KIND_USER and viewer_id is not None and dog.owner_user_id == viewer_id
    try:
        mt = manual.tickets(dog.id, now=now) if dog.kind == common.KIND_USER else []
    except Exception:  # noqa: BLE001
        mt = []
    return ask.AskContext(
        dog_id=dog.id, name=dog.name, kind=dog.kind, catchphrase=common.catchphrase(dog, summary),
        rule_text=common.rule_text(dog, summary), rule_english=common.rule_english(dog, summary), trigger=trigger,
        spec=dog.spec, summary=summary, tickets=common.forward_tickets(dog, limit=60), manual=mt,
        feedback=_counts(dog), tips=tips or [], is_owner=owner, status=dog.status,
        today=common.eastern_date(now), warming=summary is None, fire_fn=fire_fn,
        earlier_fn=earlier_fn, backtest_fn=backtest_fn, now=now)
