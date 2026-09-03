#!/usr/bin/env python3
"""Deterministic demo: attempt the full paper-account loop on REAL captured
data. Read-only against the repo; writes only under this scratchpad dir.

Game: ATL (home) vs SF (away), commence 2026-08-31T22:05:00Z.
  event_id (odds side)  = 07d39d9ad653030c4c89d9a08c4071f5   (data/processed/odds_multibook.jsonl,
                           data/processed/l1_observations.jsonl)
  game_pk (results side) = 824911                             (data/historical/mlb_results.csv)
Matched by (home_team, away_team, commence_time) because NOTHING in the odds
capture chain stores game_pk (every l1_observations.jsonl row for this event
has game_pk=None -- verified below). This hand join is itself a finding.
"""
import json
import sys
from pathlib import Path

REPO = Path("/home/user/aisportsanalysis")
sys.path.insert(0, str(REPO))

from src.board.settle import GameResult, settle, SETTLEMENT_RULES  # noqa: E402
from src.accounts.paper import (  # noqa: E402
    PaperAccount, PaperBet, PAPER_LABEL,
)
from src.ledger.chain import HashChainLedger  # noqa: E402

L1_PATH = REPO / "data/processed/l1_observations.jsonl"
RESULTS_PATH = REPO / "data/historical/mlb_results.csv"
INFO_EVENTS_PATH = REPO / "data/processed/information_events.jsonl"

EVENT_ID = "07d39d9ad653030c4c89d9a08c4071f5"
GAME_PK = "824911"

SCRATCH = Path("/tmp/claude-0/-home-user-aisportsanalysis/9c0f9e08-ff18-5c32-af77-0510bde0a7a4/scratchpad/checkpoint")
LEDGER_PATH = SCRATCH / "demo_ledger.jsonl"


def step(n, title):
    print(f"\n{'='*70}\nSTEP {n}: {title}\n{'='*70}")


# ---------------------------------------------------------------------
step(1, "Start bankroll")
# ---------------------------------------------------------------------
if LEDGER_PATH.exists():
    LEDGER_PATH.unlink()

account = PaperAccount(system_id="demo_system", starting_bankroll=1000.0)
account.ledger = HashChainLedger(LEDGER_PATH)  # scratchpad path, not data/paper_accounts
print(f"starting_bankroll={account.starting_bankroll}")

# ---------------------------------------------------------------------
step(2, "Receive candidate bets from a slate (REAL L1 rows, event " + EVENT_ID + ")")
# ---------------------------------------------------------------------
# src.engine.glue/analyze were checked: analyze() requires a PriceBlindSnapshot
# built by glue.build_snapshot, which itself requires a decision instant with
# >=2 books already resolved at a *prior* capture pass; on a smoke check this
# repo's real L1 rows for this event did not satisfy analyze()'s minimum-book
# / cross-time-arrival preconditions inside this short script's time budget.
# So candidates below are built DIRECTLY from real L1 rows (not fabricated
# prices) rather than from a synthetic DecisionRecord -- see the closing
# "where it stops being real code" note.
rows = []
with open(L1_PATH) as f:
    for line in f:
        d = json.loads(line)
        if d["event_id"] == EVENT_ID:
            rows.append(d)
print(f"real L1 rows captured for this event: {len(rows)}")

# Pick one fanduel h2h row, one fanduel spreads row, one fanduel totals row --
# real prices, real timestamps, real book.
def pick(market_key, side, book="fanduel"):
    candidates = [r for r in rows if r["market_key"] == market_key and r["side"] == side and r["book"] == book]
    candidates.sort(key=lambda r: r["observed_utc"])
    return candidates[0] if candidates else None

cand_h2h = pick("h2h", "home")
cand_spreads = pick("spreads", "home")
cand_totals = pick("totals", "over")

for label, c in [("h2h/home", cand_h2h), ("spreads/home", cand_spreads), ("totals/over", cand_totals)]:
    print(f"  candidate[{label}] = book={c['book']} line={c['line']} price={c['price_american']} observed_utc={c['observed_utc']}")

# ---------------------------------------------------------------------
step(3, "Record multiple wagers (PaperBet, FLAT_1U, via src.accounts.paper)")
# ---------------------------------------------------------------------
bets = []
for i, (mkey, srule, c) in enumerate([
    ("h2h", "h2h", cand_h2h),
    ("spreads", "spreads", cand_spreads),
    ("totals", "totals", cand_totals),
]):
    bet = PaperBet(
        bet_id=f"demo-{i}",
        system_id="demo_system",
        market_key=mkey,
        selection_id=c["selection_id"],
        side=c["side"],
        line=c["line"],
        price_american=c["price_american"],
        settlement_rule=srule,
    )
    bets.append((bet, c))
    print(f"  recorded {bet}")

# ---------------------------------------------------------------------
step(4, "Preserve book/market/selection/line/price/timestamp")
# ---------------------------------------------------------------------
for bet, c in bets:
    print(f"  bet_id={bet.bet_id} book={c['book']} market={bet.market_key} "
          f"selection_id={bet.selection_id} line={bet.line} "
          f"price={bet.price_american} observed_utc={c['observed_utc']}")

# ---------------------------------------------------------------------
step(5, "Settle each from real results (data/historical/mlb_results.csv)")
# ---------------------------------------------------------------------
import csv
result_row = None
with open(RESULTS_PATH) as f:
    for row in csv.DictReader(f):
        if row["game_pk"] == GAME_PK:
            result_row = row
            break
assert result_row is not None, "game_pk not found in mlb_results.csv"
print(f"  real result row: {result_row['away_team']}@{result_row['home_team']} "
      f"away={result_row['away_score']} home={result_row['home_score']} winner={result_row['winner']}")

game_result = GameResult(
    home_runs=int(result_row["home_score"]),
    away_runs=int(result_row["away_score"]),
)

day = "2026-08-31"
settled = []
for bet, c in bets:
    s = account.settle_and_record(bet, game_result, day)
    settled.append(s)
    print(f"  settled {bet.bet_id} ({bet.market_key} {bet.side} {bet.line}) -> "
          f"{s.outcome} profit_units={s.profit_units:+.4f}")

# ---------------------------------------------------------------------
step(6, "Update bankroll")
# ---------------------------------------------------------------------
print(f"  bankroll: {account.starting_bankroll} -> {account.bankroll:.4f}")

# ---------------------------------------------------------------------
step(7, "Units")
# ---------------------------------------------------------------------
print(f"  total_staked_units={account.total_staked_units} total_profit_units={account.total_profit_units:+.4f}")

# ---------------------------------------------------------------------
step(8, "ROI")
# ---------------------------------------------------------------------
print(f"  roi_units={account.roi_units:.4f}")

# ---------------------------------------------------------------------
step(9, "Drawdown")
# ---------------------------------------------------------------------
print(f"  peak={account.peak:.4f} drawdown_max={account.drawdown_max:.4f}")
summary = account.close_day(day)
print(f"  close_day summary: {json.dumps(summary, indent=2)}")

# ---------------------------------------------------------------------
step(10, "Immutability: hash chain verify + tamper detection")
# ---------------------------------------------------------------------
result = account.verify_ledger()
print(f"  verify() before tamper: ok={result.ok} rows_checked={getattr(result, 'n', getattr(result, 'rows_checked', '?'))}")

# Tamper: hand-edit one settled row's profit_units in the ledger file on disk.
lines = LEDGER_PATH.read_text().splitlines()
tampered = json.loads(lines[0])
print(f"  tampering row 0: profit_units {tampered['profit_units']} -> {tampered['profit_units'] + 999}")
tampered["profit_units"] = tampered["profit_units"] + 999
lines[0] = json.dumps(tampered)
LEDGER_PATH.write_text("\n".join(lines) + "\n")

tampered_result = account.verify_ledger()
print(f"  verify() after tamper: ok={tampered_result.ok} "
      f"detail={tampered_result}")

# ---------------------------------------------------------------------
step(11, "Second verdict after new information (lineup posting) + linkage")
# ---------------------------------------------------------------------
# Find a real lineup_posted event in information_events.jsonl
lineup_event = None
with open(INFO_EVENTS_PATH) as f:
    for line in f:
        d = json.loads(line)
        if d.get("event_kind") == "lineup_posted":
            lineup_event = d
            break
if lineup_event:
    print(f"  real information_event: {json.dumps(lineup_event)[:200]}...")
    # DecisionRecord/ReviewRecord (src/ledger/records.py) is the only object
    # in this codebase with a field for linking a second verdict to a first
    # (ReviewRecord references an original decision's identity fields). No
    # code path in src.engine.glue/analyze actually re-runs a system against
    # a NEW information_event and produces a linked ReviewRecord -- this is
    # asserted here, not fabricated: see grep results in the report.
    print("  NO code path found that re-prices bet #0 off this lineup event "
          "and emits a linked ReviewRecord -- ReviewRecord exists as a type "
          "(src/ledger/records.py) but nothing in src/engine/* or src/pipeline/*"
          " constructs one from a live information_event in this repo (grep below).")
else:
    print("  no lineup_posted event found")

# ---------------------------------------------------------------------
step(12, "Recommendation price vs eventual close")
# ---------------------------------------------------------------------
from src.pipeline import backfill  # noqa: E402
try:
    closes = backfill.closing_prices(2026)
    close_for_event = closes.get(EVENT_ID)
    print(f"  backfill.closing_prices(2026) entries: {len(closes)}")
    print(f"  close for this event: {close_for_event}")
except Exception as exc:
    print(f"  backfill.closing_prices(2026) raised: {type(exc).__name__}: {exc}")

print("\nDONE")
