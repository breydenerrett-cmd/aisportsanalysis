"""Tennis research board: matches per tournament with de-vigged consensus.

WHY THIS EXISTS
---------------
Tennis tournaments are grouped by tournament key (e.g., "tennis_atp_china_open").
This module assembles all matches for a date, groups them by tournament, and
computes the de-vigged consensus probability for the likelier side if enough
books quoted the match.

The board is purely informational: no bets, no picks. The notice reads "Research
only. No tennis picks until results grading is connected." to reflect that the
surface is under development.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import prices as prices_mod
from src.pipeline import snapshots, tennis_discovery


def board_for_date(date_str: str, *, rows=None, tournaments=None, now=None) -> dict:
    """Tennis research board: matches grouped by tournament.

    Args:
        date_str: UTC date as YYYY-MM-DD. Matches whose commence_time falls
                 on this UTC date are included.
        rows: Multibook quote rows. Default: reads from snapshots.read_multibook
              filtering for tennis sports.
        tournaments: Tournament metadata from tennis_discovery.latest. Default:
                    lazy-loaded from the discovery store.
        now: Datetime for timestamp. Default: datetime.now(timezone.utc).

    Returns:
        {
            "date": date_str,
            "tournaments": [
                {
                    "key": tournament key,
                    "title": human-readable tournament name,
                    "matches": [
                        {
                            "event_id": event id,
                            "player_a": away_team (player 1),
                            "player_b": home_team (player 2),
                            "commence_time": ISO string,
                            "likelier": "a" or "b" or None,
                            "probability": de-vigged consensus (0.0-1.0) or None,
                            "books": number of books quoted,
                            "observed_utc": newest observation timestamp,
                        },
                        ...
                    ]
                },
                ...
            ],
            "notice": "Research only. No tennis picks until results grading is
                      connected.",
            "generated_utc": ISO string,
        }
    """
    if rows is None:
        # Read multibook rows and filter for tennis sports
        all_rows = snapshots.read_multibook(sport=None)
        rows = [r for r in all_rows if isinstance(r.get("sport"), str)
                and r.get("sport", "").startswith("tennis_")]

    if tournaments is None:
        tournaments = tennis_discovery.latest()

    current_time = now or datetime.now(timezone.utc)
    generated_utc = current_time.isoformat()

    # Build a tournament map by key
    tournament_map = {}
    for t in tournaments:
        key = t.get("key")
        title = t.get("title")
        if key and title:
            tournament_map[key] = title

    # Group rows by (event_id, tournament_key) and select newest per book
    # to build a board per match
    matches_by_event = {}  # {(event_id, tournament_key): [newest quotes per book]}

    for row in rows:
        if not snapshots.is_pregame(row):
            continue

        event_id = row.get("event_id")
        tournament_key = row.get("sport")
        commence_time = row.get("commence_time")

        if not event_id or not tournament_key:
            continue

        key = (event_id, tournament_key)
        if key not in matches_by_event:
            matches_by_event[key] = {
                "event_id": event_id,
                "player_a": row.get("away_team"),
                "player_b": row.get("home_team"),
                "commence_time": commence_time,
                "quotes": {},  # {book: {away_price, home_price, observed_utc}}
                "newest_observed_utc": row.get("observed_utc", ""),
            }

        # Track newest quote per book for this match
        book = row.get("book")
        observed = row.get("observed_utc", "")
        if book:
            existing = matches_by_event[key]["quotes"].get(book, {})
            existing_ts = existing.get("observed_utc", "")
            if observed >= existing_ts:
                matches_by_event[key]["quotes"][book] = {
                    "away_price": row.get("away_price"),
                    "home_price": row.get("home_price"),
                    "observed_utc": observed,
                }
                matches_by_event[key]["newest_observed_utc"] = max(
                    matches_by_event[key]["newest_observed_utc"], observed)

    # Parse commence_time values to filter by date
    target_date = date_str  # YYYY-MM-DD
    matches_by_tournament = {}  # {tournament_key: [match_dicts]}

    for (event_id, tournament_key), match_data in matches_by_event.items():
        commence_time = match_data["commence_time"]
        if not commence_time:
            continue

        try:
            ts = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            match_date = ts.date().isoformat()
        except (ValueError, AttributeError):
            continue

        if match_date != target_date:
            continue

        # Build the quote list for prices.snapshot
        quote_list = []
        for book, quote_data in match_data["quotes"].items():
            if quote_data.get("away_price") is not None and \
                    quote_data.get("home_price") is not None:
                quote_list.append({
                    "book": book,
                    "away_price": quote_data["away_price"],
                    "home_price": quote_data["home_price"],
                })

        # Compute de-vigged consensus
        board_result = prices_mod.snapshot(quote_list) if quote_list else {}
        likelier = None
        probability = None
        books_count = len(quote_list)

        if "skipped" not in board_result and "sides" in board_result:
            sides = board_result["sides"]
            away_side = sides.get("away", {})
            home_side = sides.get("home", {})

            away_prob = away_side.get("consensus_probability")
            home_prob = home_side.get("consensus_probability")

            if away_prob is not None and home_prob is not None:
                if away_prob > home_prob:
                    likelier = "a"
                    probability = away_prob
                else:
                    likelier = "b"
                    probability = home_prob

        # Filter by date and build match record
        if tournament_key not in matches_by_tournament:
            matches_by_tournament[tournament_key] = []

        matches_by_tournament[tournament_key].append({
            "event_id": event_id,
            "player_a": match_data["player_a"],
            "player_b": match_data["player_b"],
            "commence_time": commence_time,
            "likelier": likelier,
            "probability": probability,
            "books": books_count,
            "observed_utc": match_data["newest_observed_utc"],
        })

    # Sort matches within each tournament by commence_time
    for matches in matches_by_tournament.values():
        matches.sort(key=lambda m: m.get("commence_time") or "")

    # Build tournament list, sorted by earliest match
    tournaments_list = []
    for tournament_key in sorted(matches_by_tournament.keys()):
        matches = matches_by_tournament[tournament_key]
        if not matches:
            continue

        # Get title from discovery or prettify the key
        title = tournament_map.get(tournament_key)
        if not title:
            # Prettify: tennis_atp_china_open -> ATP China Open
            parts = tournament_key.replace("tennis_", "").split("_")
            title = " ".join(p.capitalize() for p in parts)

        tournaments_list.append({
            "key": tournament_key,
            "title": title,
            "matches": matches,
        })

    # Sort by earliest match in each tournament
    tournaments_list.sort(
        key=lambda t: min((m.get("commence_time") or "") for m in t["matches"])
        if t["matches"] else "")

    return {
        "date": date_str,
        "tournaments": tournaments_list,
        "notice": "Research only. No tennis picks until results grading is connected.",
        "generated_utc": generated_utc,
    }
