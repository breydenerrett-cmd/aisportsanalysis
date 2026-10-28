"""References and outcomes: the two things written after a decision (docs/PREREG_LIVE_TENNIS.md sections 5 and 7).

`resolve_references` turns each bet into a `reference` row (the first valid later board and M1 / M2) or a
`no_reference` row (the window passed, with the counted cause). It reads only stored snapshots, spends no credit,
and is run by every capture tick and by `grade`.

`settle` writes one `outcome` row per evaluated decision point (a BET or a NO_BET, never an exclusion) once ESPN
lists its match settled: the match winner, the winner of the set that began at the decision point, and for a bet
its result and flat 1-unit profit at the board-average price and at the best price. This is the ONLY place a
match result is read, and it is read through the repo's existing `espn_tennis_results.settlement` rule (a
retirement after at least one completed set goes to the player who advanced; a walkover, a cancellation and a
retirement before a set completes are void). Nothing here changes a decision or a reference.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from src.core import odds as core_odds
from src.providers import espn_tennis_results as espn
from src.research.live_tennis import board, clv, config, decision as decision_mod
from src.research.live_tennis.ledger import PaperLedger, SnapshotStore


def _bet_view(decision: dict) -> dict:
    """The side, entry board and entry prices a reference is measured for: the real bet, or a SHADOW bet.

    A shadow bet is a decision point where the PERMISSIVE freshness variant (docs/PREREG_LIVE_TENNIS.md section 7,
    descriptive only) would have bet and the strict rule did not. It is referenced from boards that happen to be
    stored, never bought for, and it never enters the decisive test.
    """
    if decision.get("status") == decision_mod.BET:
        return {"side": decision["side"], "board": decision["board"], "entry": decision["entry"], "shadow": False}
    perm = decision.get("permissive") or {}
    return {"side": perm["side"], "board": perm["board"], "entry": perm["entry"], "shadow": True}


def _reference_row(bet: dict, pick: dict, now: datetime) -> dict:
    view = _bet_view(bet)
    metrics = clv.clv(view["side"], view["board"], pick["stats"])
    ref_view = board.side_view(pick["stats"], view["side"])
    snap = pick["snapshot"]
    return {
        "dp_id": bet["dp_id"], "event_id": bet["event_id"], "sport_key": bet["sport_key"], "side": view["side"],
        "shadow": view["shadow"],
        "snapshot_id": snap["snapshot_id"], "t_ref": snap["t_resp"], "delay_s": pick["delay_s"],
        "n_fresh": len(pick["fresh"]), "fresh_quotes": pick["fresh"],
        "ref_consensus": ref_view["consensus"], "ref_board": pick["stats"],
        "entry_consensus": view["entry"]["consensus"], "entry_avg_implied": view["entry"]["avg_implied"],
        "entry_best_implied": view["entry"]["best_implied"], **metrics,
    }


def _cause(diag: dict) -> str:
    if not diag.get("in_window"):
        return "NO_SNAPSHOT_IN_WINDOW"
    if not diag.get("in_progress"):
        return "MATCH_NOT_IN_PROGRESS"
    return "THIN_REFERENCE"


def pending_references(ledger: PaperLedger) -> List[dict]:
    """Decisions that are a bet (or a shadow bet) with neither a reference nor a no_reference row yet."""
    decided = {r["dp_id"] for r in ledger.rows() if r.get("kind") in ("reference", "no_reference")}
    return [d for d in ledger.of_kind("decision")
            if (d.get("status") == decision_mod.BET or d.get("shadow_bet")) and d["dp_id"] not in decided]


def resolve_references(ledger: PaperLedger, snapshots: SnapshotStore, now: datetime, *, write: bool = True) -> dict:
    """Write a reference or no_reference row for every bet that can be resolved. -> counts and the still-pending bets."""
    out = {"references": 0, "no_reference": 0, "pending": []}
    bets = pending_references(ledger)
    if not bets:
        return out
    earliest = min(board.parse_utc(b["t_decision"]) for b in bets)
    stored = snapshots.recent(earliest - timedelta(seconds=1))
    for bet in bets:
        t_dec = board.parse_utc(bet["t_decision"])
        own = [s for s in stored if s.get("key") == bet["sport_key"]]
        pick = clv.pick_reference(t_dec, bet["event_id"], own)
        if pick["found"]:
            if write:
                ledger.append("reference", _reference_row(bet, pick, now), now=now)
            out["references"] += 1
        elif now > t_dec + timedelta(seconds=config.REF_MAX_DELAY_SECONDS):
            if write:
                ledger.append("no_reference", {"dp_id": bet["dp_id"], "event_id": bet["event_id"],
                                               "sport_key": bet["sport_key"], "t_decision": bet["t_decision"],
                                               "shadow": _bet_view(bet)["shadow"],
                                               "cause": _cause(pick["diagnostics"]),
                                               "diagnostics": pick["diagnostics"]}, now=now)
            out["no_reference"] += 1
        else:
            out["pending"].append({"dp_id": bet["dp_id"], "sport_key": bet["sport_key"], "event_id": bet["event_id"],
                                   "t_decision": bet["t_decision"], "shadow": _bet_view(bet)["shadow"],
                                   "due_utc": board.iso_utc(t_dec + timedelta(seconds=config.REF_MIN_DELAY_SECONDS)),
                                   "dedicated_after_utc": board.iso_utc(
                                       t_dec + timedelta(seconds=config.REF_DEDICATED_AFTER_SECONDS)),
                                   "expires_utc": board.iso_utc(
                                       t_dec + timedelta(seconds=config.REF_MAX_DELAY_SECONDS))})
    return out


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------

def _winner_home(winner: str, orientation: str) -> bool:
    return (winner == "a") == (orientation == "straight")


def _set_winner_home(match: "espn.TennisMatch", set_number: int, orientation: str) -> Optional[bool]:
    if set_number < 1 or set_number > len(match.sets):
        return None
    a, b = match.sets[set_number - 1]
    if not espn.set_completed(a, b):
        return None
    return _winner_home("a" if a > b else "b", orientation)


def _profit(result: str, decimal_price: float) -> float:
    if result == "VOID":
        return 0.0
    return (decimal_price - 1.0) if result == "WIN" else -1.0


def _outcome_row(dec: dict, armed: dict, match: "espn.TennisMatch", verdict: dict) -> dict:
    orientation = armed["orientation"]
    graded = verdict["state"] == espn.GRADED
    home_won = _winner_home(verdict["winner"], orientation) if graded else None
    set_home = _set_winner_home(match, armed["set_number"], orientation)
    row = {
        "dp_id": dec["dp_id"], "event_id": dec["event_id"], "sport_key": dec["sport_key"], "status": dec["status"],
        "espn_status": match.status, "settlement_state": verdict["state"], "settlement_reason": verdict["reason"],
        "final_sets": [list(s) for s in match.sets], "match_winner_home": home_won, "set_winner_home": set_home,
        "model_p_match_home": (dec.get("model") or {}).get("p_match_home"),
        "model_p_set_home": (dec.get("model") or {}).get("p_set_home"),
        "consensus_home_at_decision": (dec.get("board") or {}).get("consensus_home"),
        "bet_side": None, "bet_result": None, "profit_avg": None, "profit_best": None,
    }
    if dec["status"] == decision_mod.BET:
        side = dec["side"]
        result = "VOID" if not graded else ("WIN" if (side == "home") == home_won else "LOSS")
        entry = dec["entry"]
        row.update({"bet_side": side, "bet_result": result,
                    "profit_avg": _profit(result, 1.0 / entry["avg_implied"]),
                    "profit_best": _profit(result, core_odds.american_to_decimal(entry["best_price"]))})
    return row


def settle(ledger: PaperLedger, *, espn_json: Callable[[str], dict], now: datetime, write: bool = True) -> dict:
    """Write an outcome row for every evaluated decision point whose ESPN match is settled."""
    decisions = [d for d in ledger.of_kind("decision") if d.get("status") in (decision_mod.BET, decision_mod.NO_BET)]
    done = {r["dp_id"] for r in ledger.of_kind("outcome")}
    armed = ledger.by_dp("armed")
    todo = [d for d in decisions if d["dp_id"] not in done and d["dp_id"] in armed]
    out = {"outcomes": 0, "pending": 0, "unresolved": 0, "not_found": 0, "errors": []}
    docs: Dict[tuple, Optional[list]] = {}

    def matches(tour: str, date_iso: str) -> Optional[list]:
        key = (tour, date_iso)
        if key not in docs:
            try:
                docs[key] = espn.parse_scoreboard(espn_json(espn.scoreboard_url(tour, date_iso)), tour)
            except Exception as exc:  # noqa: BLE001 -- one failed read leaves those rows pending, never guessed
                out["errors"].append(f"{tour} {date_iso}: {type(exc).__name__}")
                docs[key] = None
        return docs[key]

    for dec in sorted(todo, key=lambda d: d["dp_id"]):
        a = armed[dec["dp_id"]]
        t_c = board.parse_utc(a["t_c"])
        found = None
        for date_iso in (t_c.date().isoformat(), now.date().isoformat()):
            listing = matches(a["espn_tour"], date_iso)
            if listing is None:
                continue
            found = next((m for m in listing if m.match_id == str(a["espn_match_id"])), None)
            if found is not None:
                break
        if found is None:
            out["not_found"] += 1
            continue
        verdict = espn.settlement(found)
        if verdict["state"] == espn.PENDING:
            out["pending"] += 1
            continue
        if verdict["state"] == espn.UNRESOLVED:
            out["unresolved"] += 1
            continue
        if write:
            ledger.append("outcome", _outcome_row(dec, a, found, verdict), now=now)
        out["outcomes"] += 1
    return out
