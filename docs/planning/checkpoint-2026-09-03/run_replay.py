import json
from src.evolab import replay
from src.evolab.decide import decide_with_reason
from src.evolab.registry import DEFAULT_REGISTRY
from src.evolab import genome as genome_mod
from src.core import asof as asof_module

u = replay.load_universe(seasons=(2023,))
g = u.get("718781")
print("GAME", g.game_pk, g.away_team, "@", g.home_team, g.official_date, g.commence_time)
print("PARK", g.park)
print("instants (T values):")
for inst in g.instants:
    print(" ", inst.observed, "books=", inst.books)

# pick the last instant strictly before commence as decision time
T = g.instants[-1].observed
print("chosen T =", T)

view = replay.world_view(g, T)
print("WorldView.point_class:", view.point_class)
print("WorldView.available:", view.available)
print("WorldView.lineup_posted:", view.lineup_posted)
print("WorldView.features (non-null):")
for k,v in sorted(view.features.items()):
    if v is not None:
        print(f"   {k} = {v}")

board = replay.board_at(g, T)
print("board keys (markets):", list(board.keys()) if isinstance(board, dict) else board)

# a simple real genome: fires on starter_velocity_gap
genome = genome_mod.validate({
    "eligibility": {"markets": ["h2h"], "min_books": 3, "require_lineup": False},
    "signals": [{"feature": "lineup_platoon_share", "threshold_index": 0, "weight": 1.0}],
    "combination": {"rule": "weighted_sum"},
    "entry": {"min_score": 1.0, "min_confirmations": 1},
    "routing": {"market_preference": ["h2h"], "f5_condition": "never"},
    "execution": genome_mod.DEFAULT_EXECUTION,
}, DEFAULT_REGISTRY)

decision, reason = decide_with_reason(genome, view, registry=DEFAULT_REGISTRY)
print("DECISION:", decision)
print("REASON:", reason)

if decision:
    quote = replay.execution_quote(view, decision.market, decision.side, decision.execution_mode)
    print("EXECUTION QUOTE:", quote)

# asof-based information grade check for this game_pk (2023 -> should be DEGRADED)
snap = asof_module.as_of(g.game_pk, T)
label, reasons = asof_module.information_grade(snap)
print("INFO GRADE:", label, reasons)

# settlement
import csv
with open("data/historical/mlb_results.csv") as f:
    r = csv.DictReader(f)
    for row in r:
        if row.get("game_pk") == g.game_pk:
            print("SETTLEMENT ROW:", row)
            break
