"""The registered ten-entry ceiling, applied at ADMISSION rather than after.

THE DEFECT THIS ANSWERS
-----------------------
The owner's answer of 2026-09-16 about 00:45Z caps the card at "10 listed
bets in total, picks and fills together", and registration section 16 records
the cost he accepted with it: "an eleventh entry that passed every gate is
refused a slot rather than a published fill being withdrawn."

`best_bets_card.select` honours that within one run. The ledger's own
ceiling does not, because it exempts locked entries:

    # card_ledger.py:2100-2106
    locked_shown = [e for e in merged if e.get("locked")]
    room = max(0, params.ceiling - len(locked_shown))

An entry locks at its own game's first pitch and is then carried forward on
every later publish. Across a day the locked set grows, `room` falls to zero,
there is nothing unlocked left to refuse, and the card keeps growing past the
ceiling. On 2026-09-22 that published 12, 13 and 14 entries against a cap of
10 (`docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md`, E5).

WHY THE FIX BELONGS AT ADMISSION AND NOT AT DISPLAY
---------------------------------------------------
Truncating a published card after the fact would withdraw a bet a reader was
already shown -- exactly what the owner's answer refused. The breach does not
happen when an entry locks; it happens when an eleventh entry is ADMITTED to
a card that already holds ten. An entry never admitted never locks, so the
ceiling holds for the rest of the day without a single published entry being
removed.

NOT WIRED IN. Nothing imports this module in the publish path. It exists so
the correct behaviour can be demonstrated on the real 2026-09-22 sequence
(`scripts/ceiling_reconciliation.py`) and put to the owner as a decision.
Applying it changes what the live publisher emits and is not approved here.
It is also kept deliberately separate from the candidate-enumeration
correction: two different defects, two different modules, two different
tests, so neither one's evidence is read as the other's.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

CEILING_FULL = "ceiling_full_at_admission"


def entry_key(entry: Mapping) -> Any:
    """One contract. Mirrors G11's own key (`best_bets_card._game_key`:
    `player_id or game_id`) so an entry that dedup treats as one bet is one
    bet here too, plus the bet string, because a game can carry a prop and a
    moneyline that dedup already separates by player_id."""
    return (entry.get("player_id") or entry.get("game_id"),
            entry.get("bet") or entry.get("bet_sentence"))


def _rank(entry: Mapping):
    """Picks before fills, then score descending. The same order
    `best_bets_card.rank_key` produces for entries that carry a score;
    an entry with no score sorts last rather than raising."""
    is_fill = 1 if entry.get("entry_class") == "fill" else 0
    score = entry.get("score")
    return (is_fill, -(score if isinstance(score, (int, float)) else -1e9))


def admit(carried: Sequence[Mapping], fresh: Sequence[Mapping], *,
          ceiling: int) -> tuple:
    """`(admitted, refused)` for one publish run.

    `carried` is what the PREVIOUS run admitted, in its published order.
    `fresh` is what this run would list. A carried entry keeps its slot --
    a published bet is never removed to make room for a better one, which
    is the whole point of the owner's answer. Fresh entries fill whatever
    room is left, in rank order; the rest are refused, with a reason, and
    are never silently dropped.
    """
    admitted: list = []
    seen: set = set()

    for entry in carried:
        key = entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        admitted.append(dict(entry))

    room = max(0, ceiling - len(admitted))
    refused: list = []

    for entry in sorted(fresh, key=_rank):
        key = entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        if room <= 0:
            row = dict(entry)
            row["admission_refused_reason"] = CEILING_FULL
            refused.append(row)
            continue
        admitted.append(dict(entry))
        room -= 1

    return admitted, refused


def walk(snapshots: Sequence[Mapping], *, ceiling: int) -> list:
    """Apply `admit` across a day's publishes in order.

    Each element of `snapshots` is `{"published_utc": ..., "entries": [...]}`
    -- one publish run's listed entries, as stored. Returns one row per
    snapshot recording what was actually listed, what admission would have
    listed, and what it would have refused. Nothing is mutated and no
    historical entry is deleted: the refused rows are reported, not erased.
    """
    out: list = []
    carried: list = []
    for snap in snapshots:
        entries = list(snap.get("entries") or ())
        admitted, refused = admit(carried, entries, ceiling=ceiling)
        out.append({
            "published_utc": snap.get("published_utc"),
            "listed_actual": len(entries),
            "listed_under_admission": len(admitted),
            "refused_at_admission": len(refused),
            "over_ceiling_actual": max(0, len(entries) - ceiling),
            "over_ceiling_under_admission": max(0, len(admitted) - ceiling),
            "refused_keys": [entry_key(r) for r in refused],
        })
        carried = admitted
    return out
