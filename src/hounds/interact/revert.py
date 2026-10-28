"""Go back to an earlier version (owner request 2026-10-28: "we need a way for users to undo an upgraded hound and revert").

WHY A NEW VERSION AND NEVER A RESURRECTION. A hound's record belongs to the exact rule that produced it, and an old version is
retired with that record frozen (``user_store.create_version``). Going back therefore does NOT reopen or edit the old row: it makes
version n+1 whose rules are a COPY of the chosen earlier version's rules, through the same ``create_version`` that every Edit, Fine-tune
and Full rebuild uses. The version that was current is retired with its record intact, the copy starts with an empty record (it is a
different run of the rule, on different games), and the page shows the whole lineage, so nothing is hidden and nothing is overwritten.

WHAT IS COPIED. The RULE fields of the chosen version (``user_spec.rule_fields``: rules, sports, markets, bets a day, stake, lock
time, rank, the Gematria settings). The hound keeps its CURRENT name, catchphrase, colour and badge: going back is about the rules,
and it must not quietly rename a hound that was renamed on the way.

THE REFUSALS, each in words and each BEFORE anything is written:
  * not the owner's hound (it reads as not found, like every rite), a buried hound, a hound its owner removed;
  * a version number that is not in this hound's lineage;
  * the version the hound is already on, or one whose rules are exactly the current rules (nothing would change);
  * a chosen version whose rules no longer pass today's checks (``validate_spec``: the menu moved on, a rules file is gone): refused with
    the checker's reason, never repaired;
  * a page that was open on a different version than the hound is on now (someone, or another tab, moved it since the list was drawn).

NOT A TRAINING. It writes no "trained" event and is not held back by the five-settled-bets wait or an open ticket: an Edit has neither,
and an undo that could be refused for a week would not be an undo. Paper only: nothing here places or suggests a bet.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Mapping, Optional, Sequence

from src.hounds import ledgers, user_spec, user_store
from src.hounds.interact import common, rites
from src.hounds.interact.rites import RiteError

logger = logging.getLogger("linehound.hounds.revert")

MODE = "revert"
REASON_PREFIX = "restored from v"
#: what an owner's own words are called on the Versions list, by the reason ``create_version`` stored on the version it retired
_REASON_WORDS = {"fine-tune": "Fine-tuned in training", "full rebuild": "Full rebuild in training", "edited by its owner": "Edited by its owner"}
SUPERSEDED = "superseded by "
HONESTY = ("Going back makes the next version with the rules of the version you chose. The version you leave keeps its record, "
           "and the next version starts with an empty record. Nothing here promises a result. Paper money only.")


# ---------------------------------------------------------------------------
# who may, and which versions there are
# ---------------------------------------------------------------------------

def _lineage_of(dog: Optional[common.Dog], user_id: int, db) -> tuple:
    """``(dog, chain, current)`` for the owner of a member hound (ANY of its versions, old ones included: the owner may be looking at
    version 1's page). Raises ``RiteError``."""
    if dog is None:
        raise RiteError("not_found", "no such hound", 404)
    if dog.kind != common.KIND_USER:
        raise RiteError("not_a_member_dog", "Only a hound a member built has versions to go back to. The house pack stays as it is.", 422)
    if dog.owner_user_id != user_id:
        raise RiteError("not_found", "no such hound", 404)
    chain = user_store.lineage(dog.id, db=db)
    if not chain:
        raise RiteError("not_found", "no such hound", 404)
    newest = chain[-1]
    if newest["status"] == user_store.STATUS_BURIED:
        raise RiteError("already_buried", f"{newest['name']} is buried. Its record is frozen and it cannot go back to an earlier version.", 409)
    live = [h for h in chain if h["status"] not in (user_store.STATUS_RETIRED, user_store.STATUS_BURIED)]
    if not live:
        raise RiteError("not_active", f"{newest['name']} is retired, so there is nothing more to do with it.", 409)
    return dog, chain, live[-1]


def _why(chain: Sequence[Mapping], i: int) -> str:
    """How version ``i`` came about, in words: read off the reason the PREVIOUS version was retired with (``superseded by <id>: <why>``),
    or the origin the version itself carries."""
    if i == 0:
        return "The first version"
    origin = chain[i].get("origin")
    if origin and origin in user_store.ORIGIN_LABELS:
        why = user_store.ORIGIN_LABELS[origin]
    else:
        reason = str(chain[i - 1].get("retire_reason") or "")
        why = reason.split(": ", 1)[1] if reason.startswith(SUPERSEDED) and ": " in reason else "changed"
        why = _REASON_WORDS.get(why, why)
    if origin == user_store.ORIGIN_REVERT:
        reason = str(chain[i - 1].get("retire_reason") or "")
        tail = reason.split(": ", 1)[1] if ": " in reason else ""
        if tail.startswith(REASON_PREFIX):
            why = f"Went back to version {tail[len(REASON_PREFIX):]}"
    return why[:1].upper() + why[1:]


def _record_of(bets: Sequence) -> dict:
    """The forward record of one version: wins, losses, pushes, graded bets, bets still open, and the units at the average price."""
    from src.hounds.interact import training
    rows = [b for b in bets if b.result in rites.SETTLED_RESULTS]
    tally = training._tally([{"result": b.result, "units": training._units_of(b)} for b in rows])       # noqa: SLF001
    return {"wins": tally["wins"], "losses": tally["losses"], "pushes": tally["pushes"], "graded": tally["n"], "units": tally["units"],
            "open": len(bets) - len(rows), "bets": len(bets)}


def versions(dog: Optional[common.Dog], user_id: int, *, rows: Optional[Sequence] = None, ledger_path: Optional[str] = None, db=None) -> dict:
    """The Versions list for the owner: every version oldest first (v1..vN), each with its status, when, why and FORWARD record only (a
    rehearsal is never shown here). ``can_go_back`` is False on the current version and on one whose rules equal the current rules."""
    dog, chain, current = _lineage_of(dog, user_id, db)
    rows = rites.read_rows(ledger_path) if rows is None else rows
    bets, _defs = ledgers.pack_rows(rows)
    by_id: dict = {}
    for b in bets:
        if b.segment == "forward":
            by_id.setdefault(b.hound_id, []).append(b)
    now_hash = user_spec.spec_hash(current["spec"])
    out = []
    for i, h in enumerate(chain):
        is_current = h["id"] == current["id"]
        same = user_spec.spec_hash(h["spec"]) == now_hash
        out.append({"id": h["id"], "version_no": h["version_no"], "status": "current" if is_current else "earlier",
                    "running": is_current and h["status"] == user_store.STATUS_RUNNING, "created_at": h["created_at"],
                    "retired_at": h["retired_at"], "why": _why(chain, i), "origin": h.get("origin"),
                    "record": _record_of(by_id.get(h["id"], [])), "rule_text": user_spec.rule_text(h["spec"]),
                    "can_go_back": not is_current and not same,
                    "cannot_reason": None if (not is_current and not same) else
                    ("This is the version it is on now." if is_current else "Its rules are the same as the version it is on now.")})
    return {"hound_id": dog.id, "name": current["name"], "current": {"id": current["id"], "version_no": current["version_no"]},
            "versions": out, "honesty": HONESTY, "paper_only": True}


# ---------------------------------------------------------------------------
# going back
# ---------------------------------------------------------------------------

def _first_problem(exc: user_spec.SpecError) -> str:
    key, why = next(iter(exc.errors.items()), ("rules", "did not pass"))
    return f"{key} {why}"[:200]


def go_back(dog: Optional[common.Dog], user_id: int, version_no: int, *, current_id: Optional[str] = None, now: Optional[datetime] = None,
            db=None) -> dict:
    """Make the next version with the rules of ``version_no``. Raises ``RiteError`` (nothing written) or returns the card."""
    dog, chain, current = _lineage_of(dog, user_id, db)
    if current_id is not None and str(current_id) != current["id"]:
        raise RiteError("version_stale", f"{current['name']} moved to another version since this list was opened (it is on version "
                                         f"{current['version_no']} now). Nothing was changed. Look at the list again.", 409)
    if isinstance(version_no, bool) or not isinstance(version_no, int):
        raise RiteError("bad_version", "Choose one of the hound's versions by its number.", 422)
    target = next((h for h in chain if h["version_no"] == version_no), None)
    if target is None:
        raise RiteError("no_such_version", f"{current['name']} has no version {version_no}.", 404)
    if target["id"] == current["id"]:
        raise RiteError("already_current", f"{current['name']} is on version {version_no} right now.", 409)
    if user_spec.spec_hash(target["spec"]) == user_spec.spec_hash(current["spec"]):
        raise RiteError("same_rules", f"Version {version_no} has the same rules as the version {current['name']} is on now "
                                      f"(version {current['version_no']}), so going back would change nothing.", 409)
    raw = copy.deepcopy(target["spec"])
    for key in ("name", "tagline", "color", "badge"):         # the rules go back; the hound keeps who it is now
        if key in current["spec"]:
            raw[key] = current["spec"][key]
    try:
        user_spec.validate_spec(raw, taken_names=())
    except user_spec.SpecError as exc:
        raise RiteError("spec_invalid", f"Version {version_no}'s rules no longer pass today's checks ({_first_problem(exc)}), so it cannot "
                                        "be restored. Nothing was changed.", 422, fields=exc.errors) from None
    moment = now or common.now_utc()
    try:
        new = user_store.create_version(current["id"], raw, actor=f"owner:{user_id}", reason=f"{REASON_PREFIX}{version_no}", now=moment, db=db,
                                        origin=user_store.ORIGIN_REVERT)
    except user_spec.SpecError as exc:
        raise RiteError("spec_invalid", f"Version {version_no}'s rules no longer pass today's checks ({_first_problem(exc)}), so it cannot "
                                        "be restored. Nothing was changed.", 422, fields=exc.errors) from None
    except user_store.StoreError as exc:
        if exc.code == "retired":                              # lost a race with another request that made a version first
            raise RiteError("version_stale", f"{current['name']} moved to another version a moment ago. Nothing more was changed. "
                                             "Look at the list again.", 409) from None
        raise RiteError(exc.code, str(exc), {"not_found": 404, "buried": 409}.get(exc.code, 400)) from None
    from src.hounds.english import render
    diff = render.diff_specs(current["spec"], new["spec"])
    logger.info("hound went back hound=%s from_v=%s to_v=%s restored=%s", current["id"], current["version_no"], new["version_no"], version_no)
    return {
        "mode": MODE, "origin": user_store.ORIGIN_REVERT, "label": "Went back", "lineage": user_store.ORIGIN_LABELS[user_store.ORIGIN_REVERT],
        "headline": f"{current['name']} is back on the rules of version {version_no}, as version {new['version_no']}. Its record starts now.",
        "restored_from": version_no, "diff": diff,
        "old": {"id": current["id"], "version_no": current["version_no"], "frozen": True},
        "new": {"id": new["id"], "version_no": new["version_no"], "origin": new.get("origin"), "page_href": f"hound.html?id={new['id']}",
                "record": {"wins": 0, "losses": 0, "pushes": 0, "bets": 0}},
        "undo": undo_offer(current["id"], current["version_no"], new["version_no"]),
        "honesty": HONESTY, "paper_only": True}


def undo_offer(retired_id: str, retired_version_no: int, new_version_no: int) -> dict:
    """What a result card says about undoing the change it just made: going back to the version that was just retired. The card sends
    ``to_version`` (and the id the hound is on now, so a stale card is refused) to ``POST /hounds/{id}/revert``."""
    return {"available": True, "to_version": retired_version_no, "from_version": new_version_no, "retired_id": retired_id,
            "label": f"Undo (go back to version {retired_version_no})"}
