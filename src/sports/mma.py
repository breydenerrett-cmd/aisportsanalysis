"""MMA/UFC sport specification.

WHY THIS EXISTS: same registry role as tennis.py -- MMA breaks the same
"one team, one game_pk" assumption tennis does, for a related reason. A UFC
card is a single long session, not several independent kickoffs, so a pick
locks against ITS OWN bout's commence_time (90 minutes out, per the owner's
UFC_CARD_V1 registration), not a whole-card cutoff. There is one Odds API
sport key for the whole sport (no per-tournament keys the way tennis needs),
so `odds_api_key` is set, unlike tennis's `None`.

Constants-only stub: `schedule_fn` and `team_abbrev_fn` stay None -- bouts
are discovered from the Odds API's own `/events` listing (see
`src.pipeline.mma_capture`), not from a separate schedule provider, and
fighters are matched by name as quoted, not abbreviated.
"""

from src.sports.spec import SportSpec


MMA = SportSpec(
    key="mma",
    display_name="UFC",
    odds_api_key="mma_mixed_martial_arts",
    card_ledger_path="evidence/cards_mma_v1.jsonl",
    # 90 minutes: locked per bout, per UFC_CARD_V1's pre-registered rule
    # (docs/PREREG_UFC_CARD_V1.md) -- a long fight card cannot lock all at
    # once the way MLB/NFL lock a whole slate near its earliest start.
    lock_lead_hours=1.5,
    featured_markets=("h2h",),
    game_id_field="event_id",
    start_word="first bell",
    experimental=True,
    schedule_fn=None,
    team_abbrev_fn=None,
)
