"""Synthetic pack ledgers, challengers and a temp world for the breeding tests. Nothing reads a live store:
every ledger, the kill switch and the coach switch live in a temp directory."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.hounds.breeding import cycle, rules
from src.hounds.learning import ledger as L
from src.hounds.learning import tunables
from src.ledger.chain import HashChainLedger

UTC = timezone.utc
FIRST = date(2026, 10, 1)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def write_bets(path: Path, hound_id: str, n: int, *, clv: Optional[float] = 0.5, units: float = 0.1,
               segment: str = "forward", result: str = "WIN", version: Optional[int] = None,
               start_day: date = FIRST, tag: str = "", graded: bool = True) -> None:
    """``n`` bet rows (one game a day per hound) each followed by its graded row."""
    chain = HashChainLedger(path)
    for i in range(n):
        day = (start_day + timedelta(days=i % 20)).isoformat()
        eid = f"{tag}{hound_id}-{segment}-{i}"
        bet = {"kind": "hound_bet", "hound_id": hound_id, "date": day, "event_id": eid, "market": "moneyline",
               "selection": "Home ML", "side": "home", "segment": segment, "price_average": -110,
               "price_best": -105, "sport": "mlb", "lock_utc": f"{day}T22:00:00Z",
               "start_utc": f"{day}T23:00:00Z", "written_utc": f"{day}T22:00:00Z"}
        if version is not None:
            bet["hound_version"] = version
        row = chain.append(bet)
        if not graded:
            continue
        chain.append({"kind": "hound_graded", "hound_id": hound_id, "date": day, "event_id": eid,
                      "market": "moneyline", "selection": "Home ML", "side": "home", "segment": segment,
                      "bet_row_hash": row["row_hash"], "result": result, "units_average_price": units,
                      "units_best_price": units, "clv_pts": clv})


def propose_live(scope: L.Scope, cid: str, hound_id: str, values: dict, *, created: str = "2026-09-01T00:00:00Z",
                 proposed_by: str = "coach", parent_version: int = 1) -> None:
    tun = tunables.load()[hound_id]
    full = tunables.full_values(tun, values)
    L.log_for(scope).append(
        L.K_PROPOSAL, now=utc(created), scope=scope.name, challenger_id=cid, hound_kind="pack",
        hound_id=hound_id, lineage_key=hound_id, category=tun.category, parent_version=parent_version,
        parent_ref=None, spec={"values": full, "rule_text": "x"}, spec_hash=f"hash-{cid}",
        spec_diff=tunables.diff(tun.defaults(), full), hypothesis="A hypothesis that is long enough.",
        evidence=["scorecard.record"], proposed_by=proposed_by)


def decide(scope: L.Scope, cid: str, outcome: str, reason: str, when: str) -> None:
    L.log_for(scope).append(L.K_DECISION, now=utc(when), scope=scope.name, challenger_id=cid,
                            hound_id="x", outcome=outcome, reason=reason, detail="", look_no=None, bh=None)


def world(root: Path, *, enabled: bool = True) -> cycle.World:
    root.mkdir(parents=True, exist_ok=True)
    cfg = root / "breeding.json"
    cfg.write_text('{"enabled": %s}' % ("true" if enabled else "false"), encoding="utf-8")
    return cycle.World(scope=L.Scope.house(root / "learning"), champion_ledger=root / "pack.jsonl",
                       breed_ledger=root / rules.LEDGER_FILE, config=cfg)


def breed_rows(w: cycle.World) -> list:
    p = Path(w.breed_ledger)
    return HashChainLedger(p).read() if p.exists() else []
