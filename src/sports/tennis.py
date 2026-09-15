"""Tennis sport specification.

WHY THIS EXISTS: tennis is the sport that proves the registry is not just an
MLB/NFL toggle -- it breaks three assumptions the rest of the app quietly makes.
There is no single odds API key (the feed is per tournament, e.g.
"tennis_atp_china_open"), so `odds_api_key` is None and a caller must resolve a
tournament rather than read a constant. There are no spreads or totals worth
featuring, only the match winner. And a match locks one hour out, not four,
because the card in front of it is a single match, not an evening slate.

Constants-only stub: the provider lands later, so the two adapters are None and
`experimental=True` keeps it out of anything customer-facing.
"""

from src.sports.spec import SportSpec


TENNIS = SportSpec(
    key="tennis",
    display_name="Tennis",
    odds_api_key=None,
    card_ledger_path="evidence/cards_tennis_v1.jsonl",
    lock_lead_hours=1.0,
    featured_markets=("h2h",),
    game_id_field="event_id",
    start_word="first serve",
    experimental=True,
    schedule_fn=None,
    team_abbrev_fn=None,
)
