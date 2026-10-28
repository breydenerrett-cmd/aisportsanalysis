"""One chat turn end to end, and the limits around it (owner request 2026-10-28).

WHO MAY CHAT. The OWNER of a member's hound, signed in, free accounts included. A hound that is not yours reads exactly like a hound that
is not there (404), a house or other hound has no chat at all (a visitor to a public hound page keeps the Ask tab's computed answers,
which cost nothing and call no model), and a hound the owner removed from the kennel is gone. A buried hound can still be talked to (its
record is frozen and public, and "what happened?" is a fair question) but it cannot be edited: it is given no tools. The history is
keyed by the member and the hound's LINEAGE (``root_id``), so it follows the hound across versions.

THE WALLS, cheapest first, all BEFORE a model is asked (a refusal here is never counted against the member):
  1. THE KEY. ``ANTHROPIC_API_KEY`` is read by name; with none the tab says "Chat is unavailable right now".
  2. THE LINE. A message with an email address, a phone number or a key in it is refused (``router.check_prompt``, the same guard the
     AI hounds' prompts pass): nothing about a person goes to a model.
  3. THE DAY. ``FREE_MESSAGES_PER_DAY`` / ``PAID_MESSAGES_PER_DAY`` messages per member per UTC day, counted from the usage table (so
     clearing the chat cannot reset it) and taken inside a transaction; a turn that fails, where the member got no answer, is given back.
  4. THE MONEY. The round's worst case is checked against the router's shared cap (``AI_PAID_CAP_USD``, its cooldowns and its daily call
     ceiling, through ``Router.skip_reason``), against the chat's OWN ceiling for the month (``MONTHLY_CHAT_USD``, under the shared one so
     chat can never use up what the AI hounds live on) and against ``CHAT_CALLS_PER_DAY_ALL`` model calls a day across every member (chat's
     calls are written into the router's daily count, whose per-day cap the AI hounds share).

WHAT IS SAVED. A turn writes nothing until it has an answer: then the member's line and the hound's line (with its proposal card, if it
staged one) are added together. A failed turn leaves the conversation as it was and the page puts the member's words back in the box.

APPLY. The ONLY thing that changes a hound. ``apply_proposal`` re-checks everything from the stored proposal (the same gate the proposal
passed, the hound still being the version the card was drawn for, the hound still being editable), then makes version n+1 through
``user_store.create_version`` with origin ``owner_chat`` and a reason that quotes the member's request. Two taps cannot both apply (the
proposal is claimed in one statement). Cancel changes nothing at all.
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

from src.ai import hound_chat
from src.ai import router as router_mod
from src.hounds import user_spec, user_store
from src.hounds.chat import facts as facts_mod
from src.hounds.chat import proposals, store
from src.hounds.interact import common

logger = logging.getLogger("linehound.hounds.chat")

FREE_MESSAGES_PER_DAY = 20            # owner request 2026-10-28
PAID_MESSAGES_PER_DAY = 100
MESSAGE_MAX_CHARS = 500
HISTORY_WINDOW = 20                   # lines (the member's and the hound's) sent to the model with each message
HISTORY_SHOWN = 200                   # lines the page loads on open
MONTHLY_CHAT_USD = 2.0                # chat's own ceiling for the month, UNDER the router's shared cap (the rebuild's is the same $2)
MONTHLY_CHAT_ENV = "HOUNDS_CHAT_MONTHLY_USD"
CHAT_CALLS_PER_DAY_ALL = 150          # model calls a day across every member; the router's daily cap of 400 is shared with the AI hounds

UNAVAILABLE_TEXT = "Chat is unavailable right now. Try again later."
RESTING_TEXT = "Chat is resting for now. Try again later."
COULD_NOT_ANSWER = "I couldn't answer just now. Your message wasn't sent; try again in a minute."
PRIVATE_TEXT = "Leave emails, phone numbers and keys out of the chat, please."
PROPOSED_FALLBACK = "Here is what I would change. Tap Apply to make it so, or Cancel to leave me as I am."
DOG_WORD = re.compile(r"\bdog(s?)\b", re.IGNORECASE)


class ChatError(Exception):
    """A refusal the page shows in words. ``code`` is stable; ``status`` is the HTTP status the route uses."""

    def __init__(self, code: str, message: str, status: int = 400, **extra):
        self.code, self.status, self.extra = code, status, extra
        super().__init__(message)


def limit_for(paid: bool) -> int:
    return PAID_MESSAGES_PER_DAY if paid else FREE_MESSAGES_PER_DAY


def monthly_cap(env: Optional[Mapping] = None) -> float:
    raw = str((env if env is not None else os.environ).get(MONTHLY_CHAT_ENV) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return MONTHLY_CHAT_USD
    return value if math.isfinite(value) and value >= 0 else MONTHLY_CHAT_USD


def scrub(text: str) -> str:
    """The hound never says the other word for itself (owner copy rule). The prompt says so; this is the net under it."""
    def fix(match: re.Match) -> str:
        word = "hound" + match.group(1)
        return word.capitalize() if match.group(0)[0].isupper() else word
    return DOG_WORD.sub(fix, text).strip()


# ---------------------------------------------------------------------------
# who and what
# ---------------------------------------------------------------------------

def resolve(user_id: int, hound_id: str, *, db: Optional[Path] = None) -> tuple:
    """``(dog, hound row)`` for the CURRENT version of the lineage ``hound_id`` belongs to, if ``user_id`` owns it; else a 404 ``ChatError``.
    An old version's id works (a page that has not yet learned of a newer version still talks to the hound as it is now)."""
    if not common.valid_id(hound_id):
        raise ChatError("not_found", "no such hound", 404)
    given = user_store.get_hound(hound_id, db=db)
    if given is None or given["owner_user_id"] != user_id:
        raise ChatError("not_found", "no such hound", 404)           # not-yours reads exactly like not-there
    versions = user_store.lineage(hound_id, db=db)
    newest = max(versions, key=lambda h: h["version_no"]) if versions else given
    if user_store.removed_by_owner(newest):
        raise ChatError("not_found", "no such hound", 404)
    dog = common.resolve(newest["id"])
    if dog is None or dog.kind != common.KIND_USER:
        raise ChatError("not_found", "no such hound", 404)
    return dog, newest


def editable(hound: Mapping) -> tuple:
    """``(True, "")`` when the hound's rule may be changed from chat, else ``(False, why)``."""
    status = hound.get("status")
    if status == user_store.STATUS_BURIED:
        return False, "it is buried and its record is frozen"
    if status == user_store.STATUS_RETIRED:
        return False, "it was retired"
    return True, ""


def _public_message(row: Mapping) -> dict:
    return {"id": row["id"], "role": row["role"], "text": row["text"], "created_at": row["created_at"], "version_no": row["version_no"],
            "proposal": proposals.public_card(row.get("proposal"))}


def _hound_block(hound: Mapping) -> dict:
    ok, why = editable(hound)
    spec = hound["spec"]
    return {"id": hound["id"], "root_id": hound["root_id"], "name": hound["name"], "version_no": hound["version_no"], "status": hound["status"],
            "style": spec.get("style") or "rules", "can_edit": ok and not user_spec.is_apprentice(spec), "edit_note": why}


def limits(user_id: int, paid: bool, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    limit = limit_for(paid)
    used = store.used_today(user_id, now=now, db=db)
    return {"limit_per_day": limit, "used_today": used, "left_today": max(0, limit - used), "paid": bool(paid), "message_max_chars": MESSAGE_MAX_CHARS}


def availability(*, env: Optional[Mapping] = None, router: Any = None) -> tuple:
    """``(True, "")`` when a message could be answered right now (a key, the shared meter), else ``(False, words for the page)``."""
    if hound_chat.api_key(env) is None:
        return False, UNAVAILABLE_TEXT
    try:
        spend = hound_chat.Spend(router)
        spend.check(hound_chat.worst_case_cost(0))
    except hound_chat.Resting:
        return False, RESTING_TEXT
    except Exception:  # noqa: BLE001 -- a meter that cannot be read must not break the tab
        return True, ""
    return True, ""


def open_chat(user_id: int, paid: bool, hound_id: str, *, now: Optional[datetime] = None, db: Optional[Path] = None,
              env: Optional[Mapping] = None, router: Any = None) -> dict:
    """What the tab needs on open: the hound, whether chat can answer right now, the saved conversation and today's allowance."""
    dog, hound = resolve(user_id, hound_id, db=db)
    ok, reason = availability(env=env, router=router)
    rows = store.history(user_id, hound["root_id"], limit=HISTORY_SHOWN, db=db)
    return {"hound": _hound_block(hound), "available": ok, "reason": None if ok else reason,
            "messages": [_public_message(r) for r in rows], "limits": limits(user_id, paid, now=now, db=db),
            "window": HISTORY_WINDOW, "paper_only": True}


# ---------------------------------------------------------------------------
# a turn
# ---------------------------------------------------------------------------

def model_window(rows: List[Mapping], window: int = HISTORY_WINDOW) -> List[dict]:
    """The last ``window`` lines as the API wants them. A hound line that carried a proposal says what became of it, so the model knows
    what is pending, applied or cancelled. A window that would start on the hound's line starts one line later (a conversation opens
    on the member)."""
    lines = [r for r in rows if r["role"] in (store.ROLE_MEMBER, store.ROLE_HOUND)][-window:]
    out = []
    for r in lines:
        text = r["text"]
        card = r.get("proposal")
        if card:
            what = "; ".join(f"{c.get('what')}: {c.get('before')} -> {c.get('after')}" for c in (card.get("changes") or [])[:6])
            text += f"\n[PROPOSAL STATUS: {card.get('status')}. {what}]"
        out.append({"role": "user" if r["role"] == store.ROLE_MEMBER else "assistant", "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _guard(*, env: Optional[Mapping], now: Optional[datetime], db: Optional[Path]) -> Callable[[float], Optional[str]]:
    cap = monthly_cap(env)

    def check(worst: float) -> Optional[str]:
        if store.month_spend(now=now, db=db) + worst > cap:
            return f"this month's chat spending limit of ${cap:.2f} is reached"
        if store.calls_today_all(now=now, db=db) >= CHAT_CALLS_PER_DAY_ALL:
            return f"chat has made its {CHAT_CALLS_PER_DAY_ALL} model calls for today"
        return None
    return check


def send(user_id: int, paid: bool, hound_id: str, text: str, *, now: Optional[datetime] = None, db: Optional[Path] = None,
         env: Optional[Mapping] = None, router: Any = None, client: Any = None, client_factory: Optional[Callable] = None,
         facts_fn: Optional[Callable] = None, catalog: Optional[str] = None) -> dict:
    """One member message, answered. Returns ``{"messages": [member line, hound line], "hound", "limits"}`` or raises ``ChatError``."""
    dog, hound = resolve(user_id, hound_id, db=db)
    message = " ".join(str(text or "").split())
    if not message:
        raise ChatError("message_required", "Say something first.", 422)
    if len(message) > MESSAGE_MAX_CHARS:
        raise ChatError("message_too_long", f"Keep it under {MESSAGE_MAX_CHARS} characters.", 422)
    key = hound_chat.api_key(env)
    if key is None:
        raise ChatError("unavailable", UNAVAILABLE_TEXT, 503)
    secrets = router_mod.secret_values(env if env is not None else os.environ) + [key]
    if router_mod.check_prompt(message, secrets):
        raise ChatError("private_info", PRIVATE_TEXT, 422)
    limit = limit_for(paid)
    used = store.used_today(user_id, now=now, db=db)
    if used >= limit:
        raise ChatError("daily_limit", f"You have used today's {limit} messages. They come back tomorrow.", 429, used=used, limit=limit)

    root = hound["root_id"]
    can_edit, why_not = editable(hound)
    facts = facts_fn(dog, hound) if facts_fn else facts_mod.collect(dog, hound, now=now, db=db)
    facts["edit_note"] = "" if (can_edit and not user_spec.is_apprentice(hound["spec"])) else (
        f"rule changes are not available right now ({why_not or 'an Apprentice learns from the bets its owner logs; its rules change in the Lessons tab'}); "
        "you have no tools, so say so if asked")
    rows = store.history(user_id, root, limit=HISTORY_WINDOW * 2 + 10, db=db)          # notices take slots the model never sees
    window = model_window(rows)
    taken = [n for n in user_store.taken_names(db=db) if user_spec._fold(n) != user_spec._fold(hound["name"])]      # noqa: SLF001
    workspace = proposals.Workspace(hound, taken_names=taken, editable=can_edit, why_not=why_not)
    tools = proposals.tools_for(workspace.current, editable=can_edit)
    system = facts_mod.system_blocks(facts, catalog=catalog)
    spend = hound_chat.Spend(router, extra_check=_guard(env=env, now=now, db=db))
    try:                                                   # the money wall, before the member's day is touched
        spend.check(hound_chat.worst_case_cost(hound_chat.text_chars(system, tools, window) + len(message)))
    except hound_chat.Resting as exc:
        logger.info("hound chat resting: %s", exc.reason)
        raise ChatError("resting", RESTING_TEXT, 503) from None
    try:
        usage_id = store.begin_turn(user_id, root, hound["id"], limit, now=now, db=db)
    except store.CapReached as exc:
        raise ChatError("daily_limit", f"You have used today's {exc.limit} messages. They come back tomorrow.", 429, used=exc.used, limit=exc.limit) from None
    result = None
    try:
        if client is None:
            client = (client_factory or hound_chat.default_client)(key)
        result = hound_chat.run_turn(client, system=system, tools=tools, history=window, user_text=message,
                                     on_tool=lambda name, args: hound_chat.ToolOutcome(*workspace.handle(name, args)), spend=spend)
    except ImportError:
        store.finish_turn(usage_id, store.STATE_FAILED, db=db)
        raise ChatError("unavailable", UNAVAILABLE_TEXT, 503) from None
    except Exception:  # noqa: BLE001 -- never a stack trace to the page, never a key in a log
        logger.exception("hound chat turn crashed")
        store.finish_turn(usage_id, store.STATE_FAILED, db=db)
        raise ChatError("model_failed", COULD_NOT_ANSWER, 502) from None
    use = result.usage
    if not result.ok:
        store.finish_turn(usage_id, store.STATE_FAILED, calls=use.calls, input_tokens=use.total_input(), output_tokens=use.output_tokens,
                          cost_usd=use.cost_usd, db=db)
        if result.reason.startswith(hound_chat.REASON_RESTING):
            raise ChatError("resting", RESTING_TEXT, 503)
        raise ChatError("model_failed", COULD_NOT_ANSWER, 502)

    reply = scrub(result.text)
    card = workspace.card(message, hound)
    if not reply:
        reply = (PROPOSED_FALLBACK if card else (f"I can't do that: {workspace.refused_for_good}" if workspace.refused_for_good
                                                  else "I don't have an answer to that just now."))
    if card:
        store.replace_pending(user_id, root, db=db)
    member_row = store.add_message(user_id, root, hound["id"], hound["version_no"], store.ROLE_MEMBER, message, now=now, db=db)
    hound_row = store.add_message(user_id, root, hound["id"], hound["version_no"], store.ROLE_HOUND, reply, proposal=card, now=now, db=db)
    store.finish_turn(usage_id, store.STATE_OK, calls=use.calls, input_tokens=use.total_input(), output_tokens=use.output_tokens,
                      cost_usd=use.cost_usd, db=db)
    return {"messages": [_public_message(member_row), _public_message(hound_row)], "hound": _hound_block(hound),
            "limits": limits(user_id, paid, now=now, db=db), "cost_usd": use.cost_usd}


# ---------------------------------------------------------------------------
# apply and cancel
# ---------------------------------------------------------------------------

def _stored_proposal(user_id: int, hound: Mapping, message_id: int, db) -> tuple:
    row = store.get_message(message_id, user_id, hound["root_id"], db=db)
    if row is None or not row.get("proposal"):
        raise ChatError("not_found", "no such proposal", 404)
    return row, row["proposal"]


def _gone(status: str) -> ChatError:
    words = {"applied": "That change was already applied.", "cancelled": "That change was cancelled.",
             "replaced": "That change was replaced by a later one.", "stale": "That change was made for an earlier version.",
             "applying": "That change is being applied.", "failed": "That change could not be applied."}
    return ChatError(f"proposal_{status}", words.get(status, "That change is not waiting for a tap."), 409, state=status)


def apply_proposal(user_id: int, hound_id: str, message_id: int, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """Make the version a proposal describes. The stored proposal, not the page, holds the rule set, and it is checked again here."""
    dog, hound = resolve(user_id, hound_id, db=db)
    row, proposal = _stored_proposal(user_id, hound, message_id, db)
    if proposal.get("status") != "pending":
        raise _gone(str(proposal.get("status")))
    ok, why = editable(hound)
    if not ok or user_spec.is_apprentice(hound["spec"]):
        raise ChatError("not_editable", f"{hound['name']} cannot be changed: {why or 'an Apprentice changes through its Lessons'}.", 409)
    if proposal.get("base_hound_id") != hound["id"] or proposal.get("base_hash") != user_spec.spec_hash(hound["spec"]):
        store.claim_proposal(message_id, user_id, hound["root_id"], "stale", db=db)
        raise ChatError("proposal_stale", "That change was made for an earlier version. Ask again.", 409, state="stale")
    taken = [n for n in user_store.taken_names(db=db) if user_spec._fold(n) != user_spec._fold(hound["name"])]          # noqa: SLF001
    try:
        spec = proposals.validate(proposal.get("spec") or {}, taken)
        if user_spec.is_gematria(hound["spec"]):
            outside = proposals.changed_outside(proposals.v2_of(hound["spec"]), spec)
            if outside:
                raise proposals.Refusal([f"a Gematria hound follows a fixed method; {', '.join(outside)} cannot change"])
    except proposals.Refusal as exc:
        store.claim_proposal(message_id, user_id, hound["root_id"], "failed", db=db)
        raise ChatError("proposal_invalid", "That change no longer passes the checks: " + "; ".join(exc.reasons), 422) from None
    if store.claim_proposal(message_id, user_id, hound["root_id"], "applying", db=db) is None:
        raise _gone("applying")
    request = proposal.get("request") or "a change from chat"
    reason = f'chat: "{request}"'[:120]
    try:
        new = user_store.create_version(hound["id"], spec, actor=f"owner:{user_id}", reason=reason, now=now, db=db,
                                        origin=proposals.ORIGIN_OWNER_CHAT)
    except user_store.StoreError as exc:
        store.claim_proposal(message_id, user_id, hound["root_id"], "failed", expect="applying", db=db)
        raise ChatError(f"store_{exc.code}", str(exc), 409) from None
    except user_spec.SpecError as exc:
        store.claim_proposal(message_id, user_id, hound["root_id"], "failed", expect="applying", db=db)
        raise ChatError("proposal_invalid", "That change no longer passes the checks: " + "; ".join(proposals.reasons_of(exc.errors)), 422) from None
    done = dict(proposal, status="applied", applied={"hound_id": new["id"], "version_no": new["version_no"]})
    store.set_proposal(message_id, done, db=db)
    notice = store.add_message(user_id, new["root_id"], new["id"], new["version_no"], store.ROLE_NOTICE,
                               f"Applied. {new['name']} is now on version {new['version_no']}. The earlier version keeps its record.", now=now, db=db)
    row = dict(row, proposal=done)
    return {"messages": [_public_message(row), _public_message(notice)], "hound": _hound_block(new), "previous_id": hound["id"]}


def cancel_proposal(user_id: int, hound_id: str, message_id: int, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """Leave the hound exactly as it is. Nothing is written to the hound; the card is marked cancelled."""
    dog, hound = resolve(user_id, hound_id, db=db)
    row, proposal = _stored_proposal(user_id, hound, message_id, db)
    claimed = store.claim_proposal(message_id, user_id, hound["root_id"], "cancelled", db=db)
    if claimed is None:
        raise _gone(str(proposal.get("status")))
    notice = store.add_message(user_id, hound["root_id"], hound["id"], hound["version_no"], store.ROLE_NOTICE,
                               "Cancelled. No change was made.", now=now, db=db)
    return {"messages": [_public_message(claimed), _public_message(notice)], "hound": _hound_block(hound)}


def clear_chat(user_id: int, hound_id: str, *, db: Optional[Path] = None) -> dict:
    dog, hound = resolve(user_id, hound_id, db=db)
    removed = store.clear(user_id, hound["root_id"], db=db)
    return {"cleared": removed, "hound": _hound_block(hound)}
