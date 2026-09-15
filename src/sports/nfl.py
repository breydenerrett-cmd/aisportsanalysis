"""NFL sport specification.

WHY THIS EXISTS: the registry holds all per-sport constants so callers don't
hardcode NFL assumptions. Unlike MLB (which has existing provider infrastructure),
NFL's schedule and team-abbreviation functions are wired to the nflverse provider
via lazy imports to avoid import cycles.
"""

from src.sports.spec import SportSpec
from src.sports.nfl_teams import abbrev


def _schedule(date_str):
    """Normalized NFL games for one date (YYYY-MM-DD).

    Adapts `src.providers.nfl.registry_schedule_fn`, which returns that module's
    normalized game records, onto the registry's sport-neutral shape:
    {"game_id", "away", "home", "start_utc"}.

    ON THE TEAM FIELDS: NFL schedule records name teams by nflverse code
    ("BUF", "DET", etc.). These are the provider's own team identifier and are
    returned verbatim rather than a name this module would have to invent a
    second table to produce. `team_abbrev_fn` below is the existing inverse that
    maps full team names (from the odds feed) onto these codes.

    The import is inside the function on purpose to avoid import cycles:
    src.sports is imported by src.appstate.card_ledger and src.providers.odds,
    so importing a provider at module load would break the app at startup.
    """
    from src.providers import nfl

    return nfl.registry_schedule_fn(date_str)


NFL = SportSpec(
    key="nfl",
    display_name="NFL",
    odds_api_key="americanfootball_nfl",
    card_ledger_path="evidence/cards_nfl_v1.jsonl",
    lock_lead_hours=4.0,
    featured_markets=("h2h", "spreads", "totals"),
    game_id_field="game_id",
    start_word="kickoff",
    experimental=True,
    schedule_fn=_schedule,
    team_abbrev_fn=abbrev,
)
