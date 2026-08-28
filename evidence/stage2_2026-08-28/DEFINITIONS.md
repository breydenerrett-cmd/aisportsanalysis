Recommendation price: consensus proportional de-vig across all books at the
latest snapshot >= 360 min before first pitch; best book kept separately; ROI
uses best book. Comparison price ("late_move", NOT CLV): same construction at
the latest snapshot before first pitch (median 84 min out). Games matched to
odds events by canonicalized team pair + commence-time within 3h of the MLB
start (_resolve_pair). Features: monthly first-day rebuilt snapshots (under-
informed, never over-informed); posted lineups from lineup_store; live leaky
endpoints untouched. p-values cluster-robust by date; CIs date-clustered
bootstrap (2000). FDR: BH q=0.10 + 1pp effect floor over the pre-registered
family (evidence/hypothesis_family.json, unchanged since registration).
Timestamp: 2026-08-28T23:0x UTC. Runner: runner.py (reproduces end to end).
