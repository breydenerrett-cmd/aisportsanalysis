"""Where the hounds disagree: one table per game, saved for the page.

The seven hounds read the same frozen data under different instructions, so the interesting thing on a
game page is not what each did but where they split. For every market slot the table says what each hound
decided (a TAKE with its price, or PASS), whether code struck a TAKE the hound proposed, and one status:

    split     takers on opposite sides of the same market
    agree     two or more hounds took the same side and nobody took the other
    lone      exactly one hound took it
    none      nobody took it

The personas are one model under seven sets of instructions, so "agree" is not confirmation; the page says
so. A hound that has not been published for the game (its stage was never answered) appears as `unanswered`
and is left out of the status, never counted as a PASS.

Pure: no I/O, no clock, no network.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.hounds.desk import roles

PASS = "PASS"
UNANSWERED = "unanswered"

STATUS_ORDER = ("split", "agree", "lone", "none")


def slot_status(takes: Sequence[Mapping]) -> str:
    """`takes` is [{"hound_id", "selection"}] for one slot."""
    if not takes:
        return "none"
    sides = {t["selection"] for t in takes}
    if len(sides) > 1:
        return "split"
    return "agree" if len(takes) >= 2 else "lone"


def build(packet: Mapping, per_hound: Mapping) -> dict:
    """`per_hound` is {hound_id: None | {"takes": [{slot_id, selection, price, book, probability}],
    "struck": [{slot_id, selection, rule, reason}]}}. None = no decision to show (unanswered)."""
    table = []
    for slot in packet.get("slots") or []:
        sid = slot["slot_id"]
        cells, takes = {}, []
        for hid in (h["id"] for h in roles.HOUNDS):
            result = per_hound.get(hid)
            if result is None:
                cells[hid] = {"decision": UNANSWERED}
                continue
            mine = [t for t in result.get("takes") or [] if t["slot_id"] == sid]
            struck = [s for s in result.get("struck") or [] if s["slot_id"] == sid]
            if mine:
                t = mine[0]
                cells[hid] = {"decision": "TAKE", "selection": t["selection"], "price": t.get("price"),
                              "book": t.get("book"), "probability": t.get("probability")}
                takes.append({"hound_id": hid, "selection": t["selection"]})
            else:
                cells[hid] = {"decision": PASS}
            if struck:
                cells[hid]["struck"] = [{"selection": s.get("selection"), "rule": s["rule"],
                                         "reason": s["reason"]} for s in struck]
        table.append({"slot_id": sid, "label": slot.get("label"), "market": slot.get("market"),
                      "status": slot_status(takes), "takers": len(takes), "hounds": cells})
    counts = {k: sum(1 for r in table if r["status"] == k) for k in STATUS_ORDER}
    return {"slots": table, "counts": counts,
            "note": ("The Desk and the six personas are one model reading the same data under different "
                     "instructions. Agreement among them is not confirmation, and a split is not a "
                     "signal. Paper only.")}
