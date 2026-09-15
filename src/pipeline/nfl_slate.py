"""Build an NFL slate from schedule, odds, ratings, and injuries.

WHY THIS EXISTS
---------------
The slate is the unified view of one date's games: schedule, market consensus,
team strength, and readiness. It is the input to nfl_card.select(), which
filters to picks. Building it is pure functions with lazy defaults, so every
seam (schedule, snapshots, team stats, injuries) can be tested by injection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import nfl_grade, nfl_strength
from src.analysis.prices import boards_by_matchup
from src.pipeline import snapshots
from src.providers import nfl, odds
from src.sports import nfl_teams


def entries_for_date(date_str: str, *, now: Optional[datetime] = None,
                     games=None, rows=None, team_stats=None,
                     injuries=None, season=None) -> list[dict]:
    """Entries for one date, in the shape nfl_card.select() expects.

    A list of dicts, one per schedulable game (not started), each carrying
    schedule, quotes, model, and grade.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        games: Schedule rows (default: lazy fetch_schedule_for_date).
        rows: Snapshot rows pre-game only (default: lazy read_multibook sport="nfl").
        team_stats: Team statistics rows (default: lazy fetch_team_stats).
        injuries: Injury report rows (default: lazy fetch_injuries).
        season: NFL season (default: lazy from now).

    Returns:
        List of entry dicts, sorted by kickoff_utc. Each entry carries:
        game_id, week, home_team, away_team, home_code, away_code, kickoff_utc,
        neutral_site, h2h_quotes, spread_quotes, model, grade.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if season is None:
        season = nfl.current_season(now)

    if games is None:
        games = nfl.schedule_for_date(date_str)

    if rows is None:
        # Get ALL multibook rows, then filter to pre-game for this sport
        rows = snapshots.read_multibook(sport="nfl")

    if team_stats is None:
        team_stats = nfl.fetch_team_stats(season)

    if injuries is None:
        injuries = nfl.fetch_injuries(season)

    # Build the board lookup: {(away_code, home_code, date_str): board}
    boards = boards_by_matchup(rows, sport="nfl")

    # Filter team_stats to this week for ratings
    games_by_week = {}
    for game in games:
        week = game.get("week")
        if week is not None:
            games_by_week.setdefault(week, []).append(game)

    # Build entries
    entries = []
    for game in games:
        week = game.get("week")
        kickoff_utc = game.get("start_utc")

        # Use the game's week if available
        if week is None:
            continue

        # Get team codes from the normalized game
        away_code = game.get("away_team")
        home_code = game.get("home_team")

        if not away_code or not home_code:
            continue

        # Get full team names from codes
        away_team = nfl_teams.full_name(away_code)
        home_team = nfl_teams.full_name(home_code)

        if not away_team or not home_team:
            continue

        # Look up the board for this matchup
        board = boards.get((away_code, home_code, date_str))

        # Extract h2h and spread quotes from the board
        h2h_quotes = []
        spread_quotes = []
        if board:
            quotes = board.get("quotes") or []
            for quote in quotes:
                h2h_quote = {
                    "book": quote.get("book"),
                    "home_price": quote.get("home_price"),
                    "away_price": quote.get("away_price"),
                    "observed_utc": board.get("observed_utc"),
                }
                h2h_quotes.append(h2h_quote)

                # Extract spread quotes if available
                home_line = quote.get("home_line")
                away_line = quote.get("away_line")
                if home_line is not None and away_line is not None:
                    # Both sides: home_line is a signed line (e.g., -3.0 means home is favored)
                    spread_quotes.append({
                        "home": {
                            "line": home_line,
                            "price": quote.get("home_spread_price"),
                            "book": quote.get("book"),
                        },
                        "away": {
                            "line": away_line,
                            "price": quote.get("away_spread_price"),
                            "book": quote.get("book"),
                        },
                    })

        # Get team ratings through this week
        ratings = nfl_strength.team_ratings(team_stats, season=season,
                                            through_week=week)

        # Get model probability
        neutral_site = game.get("neutral_site", False)
        model = None
        if away_code in ratings and home_code in ratings:
            model = nfl_strength.game_probability(
                home_code, away_code, ratings, neutral_site=neutral_site)

        # Get game readiness grade
        grade = nfl_grade.grade(
            game, injuries=injuries, quotes=h2h_quotes,
            now=now, week=week)

        entry = {
            "game_id": game.get("game_id"),
            "week": week,
            "home_team": home_team,
            "away_team": away_team,
            "home_code": home_code,
            "away_code": away_code,
            "kickoff_utc": kickoff_utc,
            "neutral_site": neutral_site,
            "h2h_quotes": h2h_quotes,
            "spread_quotes": spread_quotes,
            "model": model,
            "grade": grade,
        }
        entries.append(entry)

    # Sort by kickoff
    entries.sort(key=lambda e: e.get("kickoff_utc") or "")
    return entries


def results_for_date(date_str: str, *, games=None,
                     scores=None) -> dict:
    """Final scores for all games on date, keyed by game_id.

    Returns {game_id: {home_score, away_score, completed}, ...}.
    Only includes games with final scores (completed=True).

    Args:
        date_str: ISO date string ("2026-09-14").
        games: Schedule rows (default: lazy fetch_schedule_for_date).
        scores: Normalized score rows (default: lazy fetch_scores).

    Returns:
        Dict of game_id -> {home_score, away_score, completed}.
    """
    if games is None:
        games = nfl.schedule_for_date(date_str)

    if scores is None:
        # Fetch scores normalized by the odds provider
        scores_raw = odds.fetch_scores(sport="nfl", days_from=3)
        scores = [odds.normalize_score(s) for s in scores_raw]

    # Index games by (away_code, home_code) for matching
    games_by_teams = {}
    for game in games:
        away_code = game.get("away_team")
        home_code = game.get("home_team")
        if away_code and home_code:
            games_by_teams[(away_code, home_code)] = game

    # Index scores by (away_code, home_code) for matching
    scores_by_teams = {}
    for score in scores:
        if not score.get("completed"):
            continue
        away_name = score.get("away_team")
        home_name = score.get("home_team")
        if not away_name or not home_name:
            continue

        # Resolve full names to codes
        away_code = nfl_teams.abbrev(away_name)
        home_code = nfl_teams.abbrev(home_name)

        if away_code and home_code:
            scores_by_teams[(away_code, home_code)] = score

    # Join games to their scores
    results = {}
    for (away_code, home_code), game in games_by_teams.items():
        score = scores_by_teams.get((away_code, home_code))
        if score and score.get("completed"):
            game_id = game.get("game_id")
            if game_id:
                results[game_id] = {
                    "home_score": score.get("home_score"),
                    "away_score": score.get("away_score"),
                    "completed": True,
                }

    return results
