"""Pure projection between the multibook row shape and PriceObservation.

`project_h2h_row` / `unproject_h2h_row` round-trip the CURRENT
data/processed/odds_multibook.jsonl shape (one row per event/book, home_price
+ away_price) with no information loss -- the round-trip test in
tests/test_board_project.py runs this over >=1,000 real captured rows.

`project_line_market_row` covers the shape another lane is adding for
all-books line markets (spreads/totals/etc): one row per event/book/market
with a `point` (or `line`) field and per-side prices. Because that lane's
exact field names were not settled at the time this packet was written, the
projector accepts both `point` and `line` as the line-value key so neither
lane blocks on the other; a follow-up packet can drop whichever name the
other lane did not end up using.

Everything here is pure: no file I/O, no network, no clock (observed_utc is
read from the row, never generated). Capture code decides `observed_utc`;
this module only reshapes what already exists.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.board.ids import selection_id

# The h2h rows in odds_multibook.jsonl predate the multi-sport / multi-market
# board and carry no explicit sport or market_key -- both are constant for
# every row in that file today, so they are filled in here rather than
# invented per row.
_DEFAULT_SPORT = "mlb"
_H2H_MARKET_KEY = "h2h"
_H2H_PROVIDER_MARKET_KEY = "h2h"


def project_h2h_row(
    row: Mapping[str, Any], *, sport: str = _DEFAULT_SPORT
) -> tuple[dict, dict]:
    """One odds_multibook.jsonl row -> two PriceObservation-shaped dicts
    (home side, away side). Returns dicts, not PriceObservation instances, so
    a caller missing a field this project doesn't track (capture_id, region,
    known_at/grade -- not present in the legacy row) can fill it in before
    constructing the frozen dataclass; PriceObservation's own validators are
    the enforcement point, not this function.
    """
    event_id = row["event_id"]
    book = row["book"]
    observed_utc = row["observed_utc"]
    book_last_update = row.get("book_last_update")

    base = {
        "sport": sport,
        "event_id": event_id,
        "game_pk": row.get("game_pk"),
        "market_key": _H2H_MARKET_KEY,
        "line": None,
        "book": book,
        "observed_utc": observed_utc,
        "book_last_update": book_last_update,
        "provider_market_key": _H2H_PROVIDER_MARKET_KEY,
    }

    home = dict(base)
    home.update(
        side="home",
        subject_kind=None,
        subject_id=None,
        price_american=row["home_price"],
        selection_id=selection_id(sport=sport, market_key=_H2H_MARKET_KEY, side="home"),
    )
    away = dict(base)
    away.update(
        side="away",
        subject_kind=None,
        subject_id=None,
        price_american=row["away_price"],
        selection_id=selection_id(sport=sport, market_key=_H2H_MARKET_KEY, side="away"),
    )
    return home, away


def unproject_h2h_row(home: Mapping[str, Any], away: Mapping[str, Any]) -> dict:
    """Reverse of project_h2h_row: two side-dicts (or PriceObservation
    instances, via ._asdict-style access below) -> one odds_multibook.jsonl
    row. Proves the projection loses nothing the legacy store needs by
    reconstructing byte-for-byte the fields the legacy reader depends on.
    """

    def _get(obj: Any, key: str) -> Any:
        return obj[key] if isinstance(obj, Mapping) else getattr(obj, key)

    row = {
        "observed_utc": _get(home, "observed_utc"),
        "event_id": _get(home, "event_id"),
        "book": _get(home, "book"),
        "book_last_update": _get(home, "book_last_update"),
        "home_price": _get(home, "price_american"),
        "away_price": _get(away, "price_american"),
    }
    return row


def _line_value(row: Mapping[str, Any]) -> str | None:
    """Accept either `point` or `line` as the line-value key (see module
    docstring) -- exactly one is expected to be present when has_line=True."""
    if "point" in row and row["point"] is not None:
        value = row["point"]
    elif "line" in row and row["line"] is not None:
        value = row["line"]
    else:
        return None
    return value if isinstance(value, str) else str(value)


def project_line_market_row(
    row: Mapping[str, Any], *, sport: str = _DEFAULT_SPORT
) -> list[dict]:
    """A single all-books line-market row (one event/book/market, both sides
    priced) -> a list of PriceObservation-shaped dicts, one per side present.

    Expected row shape (field names per the other lane's design, both
    `point` and `line` accepted for the line value):
        event_id, market_key, book, observed_utc, book_last_update,
        point | line, <side>_price for each side in the market's
        MARKET_CATALOGUE entry (e.g. over_price/under_price,
        home_price/away_price), optionally subject_kind/subject_id for props.
    """
    market_key = row["market_key"]
    line = _line_value(row)
    subject_kind = row.get("subject_kind")
    subject_id = row.get("subject_id")
    subject = (subject_kind, subject_id) if subject_kind else None

    observations = []
    for side_field, side_name in (
        ("home_price", "home"),
        ("away_price", "away"),
        ("over_price", "over"),
        ("under_price", "under"),
        ("yes_price", "yes"),
        ("no_price", "no"),
    ):
        if side_field not in row or row[side_field] is None:
            continue
        observations.append(
            {
                "sport": sport,
                "event_id": row["event_id"],
                "game_pk": row.get("game_pk"),
                "market_key": market_key,
                "line": line,
                "book": row["book"],
                "observed_utc": row["observed_utc"],
                "book_last_update": row.get("book_last_update"),
                "provider_market_key": row.get("provider_market_key", market_key),
                "side": side_name,
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "price_american": row[side_field],
                "selection_id": selection_id(
                    sport=sport,
                    market_key=market_key,
                    side=side_name,
                    subject=subject,
                    line=line,
                ),
            }
        )
    return observations
