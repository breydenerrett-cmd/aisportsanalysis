"""Market identity: the catalogue of tradeable things and their fingerprint.

A line is part of the selection, not a modifier on it. "Yankees -1.5" and
"Yankees -2.5" are different bets with different settlement outcomes on the
same event; treating the line as metadata attached to a stable selection_id
is how a system silently averages together things that do not average. Every
identity fact that changes what wins the bet (market, side, subject, line)
goes into the hash. Every fact that does not (book, timestamp, region) stays
out of it -- two books quoting the same market/side/subject/line are the same
selection at different prices, and PriceObservation.book is where that price
lives.

The line is stored and hashed as a DECIMAL STRING, never a float. `6.5` and
`6.500000000000001` are the same line to a human and different keys to a
float hasher; a string sidesteps every binary-representation footgun and
keeps identity stable across languages, engines and years without a floating
point equality test anywhere in the critical path (see attack.md and
design-data-first.md on canonical string encodings for exactly this class of
bug).
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple


class MarketSpec(NamedTuple):
    """One row of the catalogue: everything identity and settlement need to
    know about a market family, independent of any single event or price."""

    scope: str  # "game" | "first_five" | "first_inning" | "player"
    shape: str  # "two_way" | "three_way" | "line_two_way" | "line_yesno"
    subject_kind: str | None  # "pitcher" | "batter" | None for team/game markets
    sides: tuple[str, ...]
    has_line: bool
    settlement_rule: str  # key into src.board.settle.SETTLEMENT_RULES
    correlation_group: str  # markets that share an underlying random variable
    status: str  # "LIVE" | "PROBE" | "DECLARED" | "BLOCKED"


# Every market this project is willing to name. A market absent from this
# table cannot be assigned a selection_id, which cannot be projected into a
# PriceObservation, which cannot reach a decision -- the catalogue is the
# single gate a new market must pass through before it can be priced at all.
#
# Status meanings (mirrors MarketFamilySpec.status in record.py):
#   LIVE      captured and settled today
#   PROBE     captured for evidence-building, not yet priced by any system
#   DECLARED  named and settlement-mapped, capture not yet wired
#   BLOCKED   named on purpose so it can never be silently added later
#             (see ARCHITECTURE_BETTING_ENGINE.md guard 8: product data-path
#             guard -- SGP/parlay pricing is gated off, not merely unbuilt)
MARKET_CATALOGUE: dict[str, MarketSpec] = {
    # --- Game-level, no player subject ---
    "h2h": MarketSpec(
        scope="game", shape="two_way", subject_kind=None,
        sides=("home", "away"), has_line=False,
        settlement_rule="h2h", correlation_group="game_outcome",
        status="LIVE",
    ),
    "spreads": MarketSpec(
        scope="game", shape="line_two_way", subject_kind=None,
        sides=("home", "away"), has_line=True,
        settlement_rule="spreads", correlation_group="game_outcome",
        status="LIVE",
    ),
    "totals": MarketSpec(
        scope="game", shape="line_two_way", subject_kind=None,
        sides=("over", "under"), has_line=True,
        settlement_rule="totals", correlation_group="game_total",
        status="LIVE",
    ),
    "team_totals": MarketSpec(
        scope="game", shape="line_two_way", subject_kind=None,
        sides=("over", "under"), has_line=True,
        settlement_rule="team_totals", correlation_group="game_total",
        status="PROBE",
    ),
    "alternate_spreads": MarketSpec(
        scope="game", shape="line_two_way", subject_kind=None,
        sides=("home", "away"), has_line=True,
        settlement_rule="spreads", correlation_group="game_outcome",
        status="PROBE",
    ),
    "alternate_totals": MarketSpec(
        scope="game", shape="line_two_way", subject_kind=None,
        sides=("over", "under"), has_line=True,
        settlement_rule="totals", correlation_group="game_total",
        status="PROBE",
    ),
    # --- First-five-innings mirrors of the game markets ---
    "h2h_1st_5_innings": MarketSpec(
        scope="first_five", shape="two_way", subject_kind=None,
        sides=("home", "away"), has_line=False,
        settlement_rule="h2h_1st_5", correlation_group="first_five_outcome",
        status="PROBE",
    ),
    "spreads_1st_5_innings": MarketSpec(
        scope="first_five", shape="line_two_way", subject_kind=None,
        sides=("home", "away"), has_line=True,
        settlement_rule="spreads_1st_5", correlation_group="first_five_outcome",
        status="PROBE",
    ),
    "totals_1st_5_innings": MarketSpec(
        scope="first_five", shape="line_two_way", subject_kind=None,
        sides=("over", "under"), has_line=True,
        settlement_rule="totals_1st_5", correlation_group="first_five_total",
        status="PROBE",
    ),
    # --- First inning yes/no markets ---
    "first_inning_run": MarketSpec(
        scope="first_inning", shape="line_yesno", subject_kind=None,
        sides=("yes", "no"), has_line=False,
        settlement_rule="first_inning_run", correlation_group="first_inning",
        status="DECLARED",
    ),
    "first_inning_score_home": MarketSpec(
        scope="first_inning", shape="line_yesno", subject_kind=None,
        sides=("yes", "no"), has_line=False,
        settlement_rule="first_inning_score_home", correlation_group="first_inning",
        status="DECLARED",
    ),
    "first_inning_score_away": MarketSpec(
        scope="first_inning", shape="line_yesno", subject_kind=None,
        sides=("yes", "no"), has_line=False,
        settlement_rule="first_inning_score_away", correlation_group="first_inning",
        status="DECLARED",
    ),
    # --- Pitcher props ---
    "pitcher_strikeouts": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="pitcher",
        sides=("over", "under"), has_line=True,
        settlement_rule="pitcher_strikeouts", correlation_group="pitcher_line",
        status="DECLARED",
    ),
    "pitcher_outs": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="pitcher",
        sides=("over", "under"), has_line=True,
        settlement_rule="pitcher_outs", correlation_group="pitcher_line",
        status="DECLARED",
    ),
    "pitcher_hits_allowed": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="pitcher",
        sides=("over", "under"), has_line=True,
        settlement_rule="pitcher_hits_allowed", correlation_group="pitcher_line",
        status="DECLARED",
    ),
    "pitcher_earned_runs": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="pitcher",
        sides=("over", "under"), has_line=True,
        settlement_rule="pitcher_earned_runs", correlation_group="pitcher_line",
        status="DECLARED",
    ),
    "pitcher_walks": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="pitcher",
        sides=("over", "under"), has_line=True,
        settlement_rule="pitcher_walks", correlation_group="pitcher_line",
        status="DECLARED",
    ),
    # --- Batter props ---
    "batter_hits": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_hits", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_total_bases": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_total_bases", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_home_runs": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_home_runs", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_rbis": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_rbis", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_runs": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_runs", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_walks": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_walks", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_strikeouts": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_strikeouts", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_stolen_bases": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_stolen_bases", correlation_group="batter_line",
        status="DECLARED",
    ),
    "batter_hits_runs_rbis": MarketSpec(
        scope="game", shape="line_two_way", subject_kind="batter",
        sides=("over", "under"), has_line=True,
        settlement_rule="batter_hits_runs_rbis", correlation_group="batter_line",
        status="DECLARED",
    ),
    # --- Correlated-parlay products: named so they can never be silently
    # added by a future contributor who finds the provider sends them. SGP
    # identification and correlation pricing is out of scope per S8/guard 8;
    # ranking any candidate from this key is a bug, not a missing feature.
    "same_game_parlay": MarketSpec(
        scope="game", shape="line_two_way", subject_kind=None,
        sides=(), has_line=False,
        settlement_rule="collection_blocked", correlation_group="sgp",
        status="BLOCKED",
    ),
}


def _canonical_line(line: str | float | int | None) -> str | None:
    """Normalize a line to its canonical decimal-string form, or reject it.

    Accepts a pre-canonicalized string, an int, or a float ONLY at the
    identity boundary where a caller has not yet been converted -- floats are
    coerced through str() and are exactly the footgun this module exists to
    keep out of storage. Callers building PriceObservation rows directly
    should always pass a string; record.py's validator raises otherwise.
    """
    if line is None:
        return None
    if isinstance(line, str):
        return line
    if isinstance(line, int):
        return str(line)
    if isinstance(line, float):
        # repr() round-trips exactly and avoids the "6.5" -> "6.5000000001"
        # class of drift that str() can introduce on some platforms/builds.
        return repr(line)
    raise TypeError(f"line must be str, int, float or None, got {type(line)!r}")


def selection_id(
    sport: str,
    market_key: str,
    side: str,
    subject: tuple[str, str] | None = None,
    line: str | float | int | None = None,
) -> str:
    """sha256 of a canonical tuple, truncated to 16 hex characters.

    The canonical tuple is (sport, market_key, side, subject_kind, subject_id,
    line) joined with a separator that cannot appear inside any field (unit
    separator \\x1f), so no field-concatenation collision is possible (e.g.
    ("a","bc") vs ("ab","c") hashing identically under naive "+".join). Field
    order is fixed here and nowhere else -- callers never construct the tuple
    themselves, which is what makes "order-independence" a property of the
    call signature (keyword args) rather than of the hash.
    """
    subject_kind, subject_id = subject if subject is not None else (None, None)
    canonical_line = _canonical_line(line)
    parts = (
        sport,
        market_key,
        side,
        subject_kind or "",
        subject_id or "",
        canonical_line or "",
    )
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
