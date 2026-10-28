"""LIVE_TENNIS_V1: a forward paper test of a serve-hold Markov model against the live tennis match-winner board.

Pre-registered in `docs/PREREG_LIVE_TENNIS.md` (frozen 2026-10-28) before any of this code existed.
Paper only: no bet-placement code, no customer surface, off unless LIVE_TENNIS_TEST=on.

    config    frozen constants, paths, the switch
    markov    hold -> game -> set -> match probabilities, inversion from the pre-match price
    state     ESPN live score -> sets won, set-start detection
    board     Odds API event -> quotes, freshness, consensus, best and average price
    decision  model price + fresh board -> BET / NO_BET / excluded, deterministic
    clv       M1 and M2 from an entry board and a reference board
    ledger    the hash-chained paper ledger and the snapshot store
    guard     the credit cap guard
    runner    one tick of capture (and the loop)
    grade     references and settlement
    report    counts always; effect statistics only past the floors
    cli       `python -m src.cli research live-tennis capture|grade|report`
"""
