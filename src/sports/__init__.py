"""Sport registry.

WHY THIS EXISTS: the app needs one place that answers "what sport is this
request for, and what are that sport's constants" so card_ledger, the odds
provider, and future UI code don't each hardcode MLB assumptions. Importing
src.sports must not pull in src.providers.mlb or any other provider module
at import time -- card_ledger and providers.odds import src.sports, so a
provider importing src.sports back would be a cycle. Each sport's schedule
and team-abbreviation logic is therefore lazy-imported inside its own
function body (see src/sports/mlb.py), not at module load.

Ordering note: src/sports/spec.py is a real submodule named "spec". The
moment anything below imports it (directly or via mlb.py/nfl.py/tennis.py),
Python's import machinery sets this package's `spec` attribute to that
submodule -- which would silently shadow the `spec()` lookup function if it
were defined first. So MLB/NFL/TENNIS are imported before `def spec` is
declared: the submodule attribute gets bound first, then the function
declaration rebinds the same name to itself, last, for good.
"""

from src.sports.mlb import MLB
from src.sports.nfl import NFL
from src.sports.tennis import TENNIS

DEFAULT_SPORT = "mlb"


class UnknownSport(KeyError):
    """Raised when an unknown sport key is requested."""


SPORTS = {"mlb": MLB, "nfl": NFL, "tennis": TENNIS}


def keys() -> tuple:
    """Return all available sport keys as a tuple."""
    return tuple(SPORTS.keys())


def spec(key=None):
    """Return the SportSpec for a given key, or MLB if key is None or "".

    Raises UnknownSport with a message listing valid keys if key is unknown.
    """
    if key is None or key == "":
        key = DEFAULT_SPORT

    if key not in SPORTS:
        valid_keys = ", ".join(SPORTS.keys())
        raise UnknownSport(f"unknown sport {key!r}; valid keys: {valid_keys}")

    return SPORTS[key]


def is_default(key) -> bool:
    """Return True if key is the default sport (None or "" counts as default)."""
    if key is None or key == "":
        key = DEFAULT_SPORT
    return key == DEFAULT_SPORT


__all__ = ["DEFAULT_SPORT", "UnknownSport", "SPORTS", "keys", "spec", "is_default"]
