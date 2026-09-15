"""MLB sport specification.

WHY THIS EXISTS: MLB is the sport this product already ships, so its spec is
the reference every other sport is measured against -- its constants are read
off the modules that own them today (the odds provider's sport key, the card
ledger's store path and lock lead) rather than retyped, so a change there can
never silently disagree with the registry. The schedule and team-abbreviation
adapters live here as thin wrappers with LAZY imports: src.sports is imported
by src.appstate.card_ledger and src.providers.odds, so importing a provider at
module load would close an import cycle and break the app at startup.
"""

from src.sports.spec import SportSpec


def _schedule(date_str):
    """Normalized MLB games for one date (YYYY-MM-DD).

    Adapts `src.providers.mlb.fetch_games`, which returns that module's own
    parsed game records, onto the registry's sport-neutral shape:
    {"game_id", "away", "home", "start_utc"}.

    ON THE TEAM FIELDS: a parsed MLB record names its clubs by ABBREVIATION
    ("BOS", "NYY") -- that is the identifier the MLB schedule endpoint serves
    and the one this repo joins on. The full club names live on the odds feed,
    and `team_abbrev_fn` below is the existing inverse that maps those onto
    these. So "away"/"home" carry the provider's own club identifier verbatim
    rather than a name this module would have to invent a second table to
    produce.

    The import is inside the function on purpose -- see the module docstring.
    """
    from src.providers import mlb

    normalized = []
    for game in mlb.fetch_games(date_str):
        game_pk = game.get("game_pk")
        normalized.append({
            # Stringified because the registry's game_id is a string for every
            # sport (tennis event ids are not integers), and a caller that
            # compares ids across sports must not have to remember which.
            "game_id": None if game_pk is None else str(game_pk),
            "away": game.get("away_team"),
            "home": game.get("home_team"),
            "start_utc": game.get("start_time_utc"),
        })
    return normalized


def _abbrev(name):
    """Full club name -> abbreviation, or None when unrecognised.

    Delegates to the single existing table in src.pipeline.slate; a second
    name-to-abbreviation map in this package would drift from that one.
    Lazy-imported for the same cycle reason as `_schedule`.
    """
    from src.pipeline.slate import team_abbrev_from_name
    return team_abbrev_from_name(name)


MLB = SportSpec(
    key="mlb",
    display_name="MLB",
    odds_api_key="baseball_mlb",
    card_ledger_path="evidence/cards_v1.jsonl",
    lock_lead_hours=4.0,
    featured_markets=("h2h", "spreads", "totals"),
    game_id_field="game_pk",
    start_word="first pitch",
    experimental=False,
    schedule_fn=_schedule,
    team_abbrev_fn=_abbrev,
)
