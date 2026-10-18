"""The desk hounds' ledger: `evidence/hounds_desk_v1.jsonl`, hash-chained like the analyst's.

ROW KINDS
---------
    hound          a definition (id, name, tagline, category, style, rule_text, prompt version and hash),
                   written once per hound, at registration (the first publish).
    hound_bet      one TAKE a hound published. Forward only: there is no replay segment for a model.
    hound_graded   the result of a bet, written by `grade`, never by a bet's writer.
    desk_game      one row per publish call for a game: which hounds were published, how many TAKEs each,
                   the packet hash and the transcript's path and hash. It carries NO `hound_id`.

WHY `desk_game` HAS NO `hound_id`
---------------------------------
`src/hounds/ledgers.py:pack_ledger_rows` (the reader the leaderboard uses) turns EVERY row that has a
`hound_id` and is not a definition into a bet. A game-level row with a `hound_id` would show up on a
hound's page as a bet with no market. `desk_game` lists its hounds under `hounds` instead, and the reader skips
a row with no `hound_id`.

WHY THE BET AND ITS GRADE SHARE A `bet_id`
------------------------------------------
That reader merges a graded row into its bet by `bet_id`, or failing that by hound + event + market +
selection + line + segment. A graded row without the line would not find a total's bet. Both carry the same
deterministic `bet_id`, so they always merge, and the graded row also carries `units` (the units at the price
taken, the field the reader reads) beside the two figures the pre-registration names.

THE TWO PRICES ON A BET
-----------------------
`price_best` is the price taken: the selection's best quote in the frozen data (a code rule). `price_average`
is the mean decimal price over the books quoting the selection in the same frozen data, as an American price.
`lock_utc` is the instant of the board the hound read (the packet's `built_at`): the price it took was that
board's price. `published_utc` is when the row was written, and `publish` bounds the gap at 90 minutes.

Pure apart from the append-only file: no clock, no network.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from src.hounds.desk import roles, state
from src.ledger.chain import HashChainLedger

LEDGER = os.path.join("evidence", "hounds_desk_v1.jsonl")

KIND_HOUND = "hound"
KIND_BET = "hound_bet"
KIND_GRADED = "hound_graded"
KIND_GAME = "desk_game"


def path(root: Optional[Path] = None) -> Path:
    return state.root_of(root) / LEDGER


def chain(root: Optional[Path] = None) -> HashChainLedger:
    return HashChainLedger(path(root))


def rows(root: Optional[Path] = None) -> list:
    return chain(root).read()


def verify(root: Optional[Path] = None):
    """Walk the chain; a `VerifyResult` naming the FIRST break, if any."""
    return chain(root).verify()


def bet_id(hound_id: str, game_id: str, slot_id: str, selection: str) -> str:
    return f"desk:{hound_id}:{game_id}:{slot_id}:{selection}"


def registered(all_rows: list) -> set:
    return {r["hound_id"] for r in all_rows if r.get("kind") == KIND_HOUND}


def register(root: Optional[Path], now_iso: str, prereg_sha256: Optional[str]) -> list:
    """Append a definition row for every hound that has none. Idempotent. Returns the rows written."""
    ledger = chain(root)
    have = registered(ledger.read())
    written = []
    for h in roles.HOUNDS:
        if h["id"] in have:
            continue
        written.append(ledger.append({
            "kind": KIND_HOUND, "hound_id": h["id"], "name": h["name"], "tagline": h["tagline"],
            "category": h["category"], "style": h["style"], "rule_text": h["rule_text"],
            "sports": list(roles.SPORTS), "markets": list(roles.MARKETS), "who_decided": "model",
            "prompt_version": roles.PROMPT_VERSION, "prompt_hash": roles.hound_prompt_hash(h["id"]),
            "registered_utc": now_iso, "prereg": "docs/PREREG_DESK_HOUNDS.md",
            "prereg_sha256": prereg_sha256, "segment": "forward"}))
    return written


def published_hounds(all_rows: list, game_id: str) -> set:
    """Hounds already published for `game_id` (a hound with no TAKE is still published)."""
    out: set = set()
    for r in all_rows:
        if r.get("kind") == KIND_GAME and r.get("game_id") == game_id:
            out.update((r.get("hounds") or {}).keys())
    return out


def _reason_of(taken, summary_note: Optional[str]) -> str:
    """The one-line reason a bet shows: the stated probability against the market's number, then the first
    claim the checker verified. Short enough for the hounds pages (their reader trims at 420 characters)."""
    first = ""
    for r in taken.decision.get("reasons") or []:
        if isinstance(r, Mapping) and isinstance(r.get("claim"), str) and r["claim"].strip():
            first = r["claim"].strip()
            break
    head = (f"Stated probability {taken.probability:g} against the books' de-vigged {taken.consensus_fair:g}. ")
    text = head + first
    return text if len(text) <= 400 else text[:397].rstrip() + "..."


def bet_row(*, hound_id: str, taken, meta: Mapping, spec: Mapping, published_utc: str,
            packet_hash: str, transcript: str, transcript_sha256: str, stage: str, attempts: int,
            model: str, prompt_hash: str) -> dict:
    game_id = meta["game_id"]
    row = {
        "kind": KIND_BET, "hound_id": hound_id, "bet_id": bet_id(hound_id, game_id, taken.slot_id,
                                                                  taken.selection),
        "date": meta["date"], "sport": meta["sport"], "event_id": meta.get("event_id"),
        "game_id": game_id, "away": meta["away"], "home": meta["home"],
        "start_utc": meta["start_utc"], "lock_utc": meta["built_at"], "published_utc": published_utc,
        "slot_id": taken.slot_id, "market": taken.market, "selection": taken.selection,
        "side": taken.side, "line": taken.line,
        "price_best": taken.price_best, "price_average": taken.price_average, "price": taken.price_best,
        "book": taken.book, "book_count": taken.book_count, "consensus_fair": taken.consensus_fair,
        "probability": taken.probability, "reason": _reason_of(taken, None),
        "who_decided": "model", "segment": "forward",
        "grading": dict(spec), "packet_hash": packet_hash, "transcript": transcript,
        "transcript_sha256": transcript_sha256, "decision_stage": stage, "attempts": attempts,
        "model": model, "prompt_version": roles.PROMPT_VERSION, "prompt_hash": prompt_hash,
    }
    if meta["sport"] == "mlb":
        row["game_pk"] = meta.get("game_ref")
    else:
        row["nfl_game_id"] = meta.get("game_ref")
    return row


def graded_row(bet: Mapping, *, result: str, units_best: Optional[float], units_average: Optional[float],
               graded_utc: str, note: Optional[str] = None) -> dict:
    return {
        "kind": KIND_GRADED, "hound_id": bet["hound_id"], "bet_id": bet["bet_id"],
        "event_id": bet.get("event_id"), "game_id": bet.get("game_id"), "date": bet["date"],
        "market": bet["market"], "selection": bet["selection"], "line": bet.get("line"),
        "segment": "forward", "result": result,
        "units_average_price": units_average, "units_best_price": units_best, "units": units_best,
        "close_price": None, "clv_pts": None,
        "clv_note": "the closing-price comparison is the referee's (src/hounds/stats.py), from the odds store",
        "graded_utc": graded_utc, "note": note,
    }


def graded_ids(all_rows: list) -> set:
    return {r["bet_id"] for r in all_rows if r.get("kind") == KIND_GRADED}
