"""Closing-line value of a paper bet against a later reference board (docs/PREREG_LIVE_TENNIS.md section 7).

    M1 (drift)         100 * (fair_ref - fair_entry) on the bet side                      probability points
    M2 (DECISIVE CLV)  100 * (fair_ref - avg_entry)                                       probability points
    M2 at the best     100 * (fair_ref - best_entry)   "includes price improvement from line shopping" (never edge)

`fair_*` is the consensus (mean of two-way de-vigged book probabilities) of a board of FRESH quotes. `avg_entry`
is the mean RAW implied probability of the bet side over the entry board's fresh books: the break-even of the
board AVERAGE price, the conservative convention. `best_entry` is the implied probability of the best price.
The same three numbers are computed for the side NOT bet, so the selection effect can be read as the difference.

The reference (`pick_reference`) is the first stored snapshot of the key that is at least REF_MIN_DELAY_SECONDS
and at most REF_MAX_DELAY_SECONDS after the decision snapshot, shows at least MIN_FRESH_BOOKS books whose
`last_update` is at or after the decision snapshot's response time (so the reference cannot be the same stale
quote), and was taken with the match in progress on the ESPN poll before and the poll after the paid call.
Nothing in this module reads who won.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional

from src.research.live_tennis import board, config


def clv(side: str, entry: Mapping, ref: Mapping) -> dict:
    """M1, M2, M2-at-best for `side` ('home' or 'away') and the same three for the other side.

    `entry` and `ref` are `board.board_stats` dicts. Every value is in probability points.
    """
    if side not in ("home", "away"):
        raise ValueError("side must be 'home' or 'away'")
    other = "away" if side == "home" else "home"

    def one(s: str) -> dict:
        e, r = board.side_view(entry, s), board.side_view(ref, s)
        return {"m1": 100.0 * (r["consensus"] - e["consensus"]),
                "m2": 100.0 * (r["consensus"] - e["avg_implied"]),
                "m2_best": 100.0 * (r["consensus"] - e["best_implied"])}

    own, opp = one(side), one(other)
    return {**own, "other_m1": opp["m1"], "other_m2": opp["m2"], "other_m2_best": opp["m2_best"]}


def _in_progress(view: Optional[Mapping]) -> bool:
    return bool(view) and view.get("status") == "STATUS_IN_PROGRESS"


def pick_reference(decision_time: datetime, event_id: str, snapshots: Iterable[Mapping]) -> dict:
    """The first valid reference snapshot for a bet, or why none exists (yet).

    `snapshots` are stored snapshot rows of the bet's key: {snapshot_id, t_resp, events: {event_id: {quotes,
    espn_before, espn_after}}}. -> {"found": bool, "snapshot": row|None, "stats": board_stats|None,
    "fresh": [...], "delay_s": float|None, "diagnostics": {...}}. The diagnostics count, for a missing reference,
    how many snapshots fell in the window, how many had the match in progress and the most fresh books seen, so a
    NO_REFERENCE is never an unexplained blank.
    """
    low = decision_time + timedelta(seconds=config.REF_MIN_DELAY_SECONDS)
    high = decision_time + timedelta(seconds=config.REF_MAX_DELAY_SECONDS)
    in_window = in_progress = 0
    most_fresh = 0
    ordered = sorted(snapshots, key=lambda s: str(s.get("t_resp")))
    for snap in ordered:
        t_resp = board.parse_utc(snap.get("t_resp"))
        if t_resp is None or t_resp < low or t_resp > high:
            continue
        item = (snap.get("events") or {}).get(event_id)
        if not item:
            continue
        in_window += 1
        if not (_in_progress(item.get("espn_before")) and _in_progress(item.get("espn_after"))):
            continue
        in_progress += 1
        fresh, _ = board.split_fresh(item.get("quotes") or [], decision_time)
        most_fresh = max(most_fresh, len(fresh))
        if len(fresh) < config.MIN_FRESH_BOOKS:
            continue
        return {"found": True, "snapshot": snap, "stats": board.board_stats(fresh), "fresh": fresh,
                "delay_s": (t_resp - decision_time).total_seconds(),
                "diagnostics": {"in_window": in_window, "in_progress": in_progress, "most_fresh": most_fresh}}
    return {"found": False, "snapshot": None, "stats": None, "fresh": [], "delay_s": None,
            "diagnostics": {"in_window": in_window, "in_progress": in_progress, "most_fresh": most_fresh}}
