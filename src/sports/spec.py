"""The per-sport constant record.

WHY THIS EXISTS: every MLB assumption in this app -- the odds API's sport key,
which field carries a game's id, how many hours before the start a published
pick locks, even the word a customer reads ("first pitch") -- is currently a
literal sitting in whichever module needed it first. Adding a second sport by
editing those literals in place would break MLB. A SportSpec is the one record
that holds them, so a caller asks the registry for a sport and reads its
constants instead of hardcoding one sport's answer.

Frozen on purpose: these are constants, and a spec that could be mutated at
runtime would let one request's edit leak into the next request's behaviour.
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class SportSpec:
    """Frozen sport definition carrying all per-sport constants."""
    key: str                          # "mlb" | "nfl" | "tennis"
    display_name: str                 # "MLB" | "NFL" | "Tennis"
    odds_api_key: Optional[str]       # "baseball_mlb" | "americanfootball_nfl" | None
    card_ledger_path: str             # repo-relative path to the jsonl card store
    lock_lead_hours: float            # hours before start when a published pick locks
    featured_markets: tuple           # ("h2h","spreads","totals") or ("h2h",)
    game_id_field: str                # "game_pk" | "game_id" | "event_id"
    start_word: str                   # "first pitch" | "kickoff" | "first serve"
    experimental: bool                # False for mlb; True for nfl and tennis
    schedule_fn: Optional[Callable]   # date_str "YYYY-MM-DD" -> list of dicts with keys
                                      # {"game_id", "away", "home", "start_utc"}
    team_abbrev_fn: Optional[Callable]  # full team name -> abbreviation or None
