"""The Apprentice hound: a hound with no rules that learns only from its owner's real bets.

THE OWNER LOGS A REAL BET (by hand or from a sportsbook screenshot) as a LESSON, in an append-only ledger. Lessons are
real money and real prices; they are NOT the hound's tickets. The hound never bets from them directly: it reads the
settled ones, summarizes the owner's patterns (``learning``), and PROPOSES paper rules the owner may apply through the
existing review-then-apply step. Applied, the hound bets ordinary graded paper tickets in its own ledger, kept apart.

  model      what a lesson is, validation, and the state DERIVED from its append-only events
  calc       parlay and payout arithmetic (a parlay wins only if every leg wins; cash-out math; rounding)
  store      the three append-only tables (triggers refuse UPDATE and DELETE) and the evidence files
  extract    screenshot -> draft via Haiku vision through src/ai/router, validated; the owner confirms
  grading    real bets graded by the same settle path as the hounds' tickets, via a mirror ledger
  analytics  profit, ROI, win rate by cut, CLV, correlated exposure: real numbers only
  learning   the freeze rule, the pattern summary, the proposal and its apply

No bet is ever placed anywhere. Paper picks only for the hound's own picks; the -200 cap holds for them.
"""
