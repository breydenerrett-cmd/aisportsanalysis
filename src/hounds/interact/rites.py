"""What the two owner rites share: who may do them, and what the ledger says about a dog's tickets.

THE TWO RITES (owner ruling 2026-10-20: "make those two separate actions, either take it out back or send in for
training, like Pokemon games"): ``outback.bury`` takes a dog out back for good, ``training.train`` sends it to
training and it comes back as a new version. Both are for a MEMBER's dog and its OWNER only, both refuse while the
dog has a ticket that has not settled, and both are written in this package so the CI harness that hides FastAPI can
import them (api/hounds_interact.py is wiring).

WHY AN UNSETTLED TICKET BLOCKS BOTH. A burial freezes the record and a training starts a fresh one. With a ticket
still open, either one would let an owner walk away from a pending loss (the loss would land on a record nobody is
looking at any more). So the rule is the same for both and it reads the LEDGER, not the cached stats book: the book
can be an hour behind, and a ticket written in that hour is exactly the one an owner might be dodging. A ticket more
than 36 hours past its start with no grade still counts as unsettled (it is "ungraded", waiting on the grader, and a
late grade must not land on a frozen record).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from src.hounds import ledgers, user_engine
from src.hounds.contract import TICKET_OPEN, ticket_status
from src.hounds.interact import common

SETTLED_RESULTS = ("win", "loss", "push")


class RiteError(Exception):
    """A refusal the caller can show: ``code`` is stable, ``status`` is the HTTP status the route uses."""

    def __init__(self, code: str, message: str, status: int = 409, **extra):
        self.code = code
        self.status = status
        self.extra = extra
        super().__init__(message)


def guard(dog: Optional[common.Dog], user_id: int) -> common.Dog:
    """The dog, if ``user_id`` may do a rite on it; else a ``RiteError``.

    A house dog (or any dog that is not a member's) is refused in words, because it is a real question ("can I take
    Chalk Chihuahua out back?") with a real answer. A member's dog that belongs to someone else reads exactly like a
    dog that is not there (404): no probing for other people's dog ids."""
    if dog is None:
        raise RiteError("not_found", "no such dog", 404)
    if dog.kind != common.KIND_USER:
        raise RiteError("not_a_member_dog", "Only a dog a member built can be taken out back or sent to training. "
                                            "The house pack stays in the pack.", 422)
    if dog.owner_user_id != user_id:
        raise RiteError("not_found", "no such dog", 404)
    if dog.status == "buried":
        raise RiteError("already_buried", f"{dog.name} is already buried. Its record is frozen.", 409)
    if dog.status == "retired":
        raise RiteError("not_active", f"{dog.name} is retired, so there is nothing more to do with it.", 409)
    return dog


def read_rows(ledger_path: Optional[str] = None) -> list:
    """The user ledger's rows ([] when there is none yet)."""
    return user_engine.read_ledger(ledger_path)


def forward_bets(hound_id: str, rows: Sequence) -> list:
    """The ledger's forward bets for ONE hound version (one id), merged with their grades, as ``ledgers.Bet``."""
    bets, _defs = ledgers.pack_rows(rows)
    return [b for b in bets if b.hound_id == hound_id and b.segment == "forward"]


def split_unsettled(bets: Sequence, now: Optional[datetime] = None) -> tuple:
    """``(open, ungraded)``: forward tickets with no grade, split by the 36-hour rule (``contract.ticket_status``)."""
    now = now or common.now_utc()
    open_n = ungraded_n = 0
    for b in bets:
        if b.graded:
            continue
        if ticket_status(b.result, b.start_utc, b.date, now) == TICKET_OPEN:
            open_n += 1
        else:
            ungraded_n += 1
    return open_n, ungraded_n


def require_all_settled(dog: common.Dog, bets: Sequence, now: Optional[datetime] = None) -> None:
    """Refuse while the dog has a ticket that has not settled. The message says which kind and how many."""
    open_n, ungraded_n = split_unsettled(bets, now)
    if open_n:
        raise RiteError("open_tickets", f"{dog.name} has {open_n} open {'ticket' if open_n == 1 else 'tickets'}. "
                                        "Wait until its open tickets settle.", 409, open_tickets=open_n)
    if ungraded_n:
        raise RiteError("open_tickets", f"{dog.name} has {ungraded_n} {'ticket' if ungraded_n == 1 else 'tickets'} "
                                        "still waiting for a grade. Wait until its tickets settle.", 409,
                        open_tickets=ungraded_n)


def settled_count(bets: Sequence) -> int:
    """Win, loss and push: the bets a record is made of (a void is not a result)."""
    return sum(1 for b in bets if b.result in SETTLED_RESULTS)
