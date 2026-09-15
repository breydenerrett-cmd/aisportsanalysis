"""What we actually KNOW about an NFL game before we publish a pick.

WHY THIS EXISTS
---------------
Unlike baseball, NFL games can proceed without full injury reports, but starting
QB status is mission-critical. The grade reports five facts that determine whether
we know enough to call a pick:

1. Has the weekly injury report been published for both teams?
2. What is the status of each starting QB (listed/out/questionable/OK)?
3. Is there a live board, with enough books (6+) and fresh data (< 3 hours)?

A pick made when either starting QB is listed as Out is a different risk than
one made with all information in hand. The grade says so in plain language.

PURE FUNCTIONS: No I/O, no clock of its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence


def _normalize_name(name: str) -> str:
    """Normalize a player name for matching: lowercase, remove suffixes and punctuation.

    Handles Jr., Sr., III, etc. Case-insensitive matching.
    """
    if not name:
        return ""
    normalized = name.lower().strip()
    # Remove common suffixes
    for suffix in (" jr.", " sr.", " iii", " ii", " iv"):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    # Remove punctuation
    normalized = normalized.replace(".", "").replace(",", "")
    return normalized.strip()


def qb_status(team_code: str, qb_name: Optional[str], injuries: Sequence[dict]) -> dict:
    """Check QB status from the injury report.

    Args:
        team_code: NFL team code (e.g., "BUF", "DET").
        qb_name: Starting QB name, or None to match any QB position.
        injuries: List of injury rows from src/providers/nfl.py fetch_injuries().
                 Each row has: season, week, team, gsis_id, full_name, position,
                 report_status, practice_status, date_modified.

    Returns:
        Dict with keys:
            - listed (bool): True if this QB appears in the injury report.
            - report_status (str or None): The reported status ("Out", "Doubtful",
              "Questionable", etc.), or None if not listed.
            - out (bool): True if report_status is "Out" or "Doubtful".
    """
    target_normalized = _normalize_name(qb_name) if qb_name else None

    for row in injuries or []:
        # Match team first
        if row.get("team") != team_code:
            continue

        # If qb_name is given, match by normalized name
        if target_normalized:
            row_normalized = _normalize_name(row.get("full_name", ""))
            if row_normalized != target_normalized:
                continue
        else:
            # Match by position QB if qb_name is None
            if row.get("position") != "QB":
                continue

        # Found a match
        report_status = row.get("report_status") or None
        is_out = report_status in ("Out", "Doubtful")
        return {
            "listed": True,
            "report_status": report_status,
            "out": is_out,
        }

    # Not found in injury report
    return {
        "listed": False,
        "report_status": None,
        "out": False,
    }


def board_status(quotes: Sequence[dict], *, now: datetime,
                 fresh_within_minutes: int = 180) -> dict:
    """Check board depth and freshness.

    Args:
        quotes: List of quote rows, each with at minimum "book" and "observed_utc".
        now: Current time (datetime with UTC timezone).
        fresh_within_minutes: Board is fresh if newest observation is within this
                             many minutes of now. Default 180 (3 hours).

    Returns:
        Dict with keys:
            - books (int or None): Distinct book count in quotes, or None if empty.
            - ok (bool): True if books >= 6.
            - fresh (bool): True if newest observed_utc is within fresh_within_minutes.
            - newest_utc (str or None): The most recent observed_utc timestamp.
    """
    if not quotes:
        return {
            "books": None,
            "ok": False,
            "fresh": False,
            "newest_utc": None,
        }

    # Extract distinct books and find newest timestamp
    books_set = set()
    newest_utc = None
    newest_dt = None

    for quote in quotes:
        book = quote.get("book")
        if book:
            books_set.add(book)

        observed = quote.get("observed_utc")
        if observed:
            try:
                # Parse ISO UTC timestamp
                dt = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
                if newest_dt is None or dt > newest_dt:
                    newest_dt = dt
                    newest_utc = observed
            except (ValueError, AttributeError):
                # Skip unparseable timestamps
                pass

    book_count = len(books_set) if books_set else None
    ok = book_count is not None and book_count >= 6

    # Check freshness
    fresh = False
    if newest_dt is not None:
        # Ensure now is timezone-aware
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        time_diff = (now_utc - newest_dt).total_seconds()
        fresh = time_diff <= (fresh_within_minutes * 60)

    return {
        "books": book_count,
        "ok": ok,
        "fresh": fresh,
        "newest_utc": newest_utc,
    }


def grade(game: dict, *, injuries: Sequence[dict], quotes: Sequence[dict],
          now: datetime, week: int) -> dict:
    """Comprehensive readiness grade for an NFL game.

    Args:
        game: Normalized game dict from src/providers/nfl.py with keys:
              game_id, season, week, away_team, home_team, start_utc, etc.
              Optionally: home_qb_name, away_qb_name.
        injuries: Injury rows for this week.
        quotes: Board quotes (observed_utc, book, etc.).
        now: Current datetime (timezone-aware).
        week: The NFL week number (for injury report published check).

    Returns:
        Dict with keys:
            - injury_report_published (bool): Any injury row for either team
              in this week exists.
            - home_qb (dict): Result of qb_status(...) for home QB.
            - away_qb (dict): Result of qb_status(...) for away QB.
            - starting_qb_out (bool): True if either QB is marked out.
            - board (dict): Result of board_status(...).
            - ready (bool): True if board.ok and board.fresh and
              injury_report_published and not starting_qb_out.
            - reasons (list[str]): Plain-English sentences explaining what
              is not ready. Empty if ready=True.
    """
    # Filter injuries for this week
    week_injuries = [inj for inj in (injuries or [])
                     if inj.get("week") == week]

    # Check injury report published
    teams_with_reports = set()
    for inj in week_injuries:
        team = inj.get("team")
        if team:
            teams_with_reports.add(team)

    away_code = game.get("away_team")
    home_code = game.get("home_team")

    injury_report_published = (away_code in teams_with_reports and
                               home_code in teams_with_reports)

    # Check QB statuses
    away_qb_name = game.get("away_qb_name")
    home_qb_name = game.get("home_qb_name")

    away_qb = qb_status(away_code, away_qb_name, week_injuries)
    home_qb = qb_status(home_code, home_qb_name, week_injuries)

    starting_qb_out = away_qb["out"] or home_qb["out"]

    # Check board
    board = board_status(quotes, now=now)

    # Ready check
    ready = (board["ok"] and board["fresh"] and
             injury_report_published and not starting_qb_out)

    # Build reasons (why it's not ready)
    reasons = []

    if not injury_report_published:
        reasons.append("The injury report for this game has not been published yet.")

    if not board["ok"]:
        if board["books"] is None:
            reasons.append("No books are pricing this game yet.")
        else:
            reasons.append(f"Fewer than six books are pricing this game ({board['books']} found).")
    elif not board["fresh"]:
        # Only report staleness if board exists but is not fresh
        reasons.append("The board is older than three hours.")

    if starting_qb_out:
        reasons.append("A starting quarterback is listed as out.")

    return {
        "injury_report_published": injury_report_published,
        "home_qb": home_qb,
        "away_qb": away_qb,
        "starting_qb_out": starting_qb_out,
        "board": board,
        "ready": ready,
        "reasons": reasons,
    }
