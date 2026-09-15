"""src/analysis/nfl_grade.py -- NFL readiness grade and QB status checks.

Tests verify that:
1. QB status detection: listed/unlisted, out/questionable/OK
2. Board status: book count and freshness
3. Comprehensive grade: ready only when all conditions hold
4. Plain-English reasons for unreadiness
"""

from datetime import datetime, timezone, timedelta
from tests._unittest_bridge import raises

from src.analysis import nfl_grade


# ============================================================================
# Fixtures and helpers
# ============================================================================

def _game(away_code="BUF", home_code="DET", away_qb=None, home_qb=None,
          season=2026, week=1):
    """A minimal normalized NFL game dict."""
    g = {
        "game_id": "2026_01_BUF_DET",
        "season": season,
        "week": week,
        "away_team": away_code,
        "home_team": home_code,
        "start_utc": "2026-09-14T18:00:00Z",
    }
    if away_qb:
        g["away_qb_name"] = away_qb
    if home_qb:
        g["home_qb_name"] = home_qb
    return g


def _injury(team, full_name, position="QB", report_status="", week=1, season=2026):
    """An injury report row."""
    return {
        "season": season,
        "week": week,
        "team": team,
        "gsis_id": f"00-{team}-{full_name[:3]}",
        "full_name": full_name,
        "position": position,
        "report_status": report_status,
        "practice_status": "",
        "date_modified": "",
    }


def _quote(book, observed_utc):
    """A board quote row."""
    return {
        "book": book,
        "observed_utc": observed_utc,
    }


def _now():
    """Current time in UTC."""
    return datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


def _utc(hours_ago):
    """Timestamp N hours before _now()."""
    return (_now() - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


# ============================================================================
# qb_status tests
# ============================================================================

def test_qb_status_listed_and_out():
    """A QB named in the injury report as Out is listed and out."""
    injuries = [
        _injury("BUF", "Josh Allen", report_status="Out"),
    ]
    result = nfl_grade.qb_status("BUF", "Josh Allen", injuries)
    assert result["listed"] is True
    assert result["report_status"] == "Out"
    assert result["out"] is True


def test_qb_status_listed_and_doubtful():
    """Doubtful is also marked as out."""
    injuries = [
        _injury("DET", "Jared Goff", report_status="Doubtful"),
    ]
    result = nfl_grade.qb_status("DET", "Jared Goff", injuries)
    assert result["listed"] is True
    assert result["report_status"] == "Doubtful"
    assert result["out"] is True


def test_qb_status_listed_and_questionable():
    """Questionable is listed but not out."""
    injuries = [
        _injury("BUF", "Josh Allen", report_status="Questionable"),
    ]
    result = nfl_grade.qb_status("BUF", "Josh Allen", injuries)
    assert result["listed"] is True
    assert result["report_status"] == "Questionable"
    assert result["out"] is False


def test_qb_status_unlisted():
    """QB not in injury report is unlisted and not out."""
    injuries = [
        _injury("DET", "Jared Goff", report_status="Questionable"),
    ]
    result = nfl_grade.qb_status("BUF", "Josh Allen", injuries)
    assert result["listed"] is False
    assert result["report_status"] is None
    assert result["out"] is False


def test_qb_status_match_ignores_case():
    """Name matching is case-insensitive."""
    injuries = [
        _injury("BUF", "Josh Allen", report_status="Out"),
    ]
    result = nfl_grade.qb_status("BUF", "JOSH ALLEN", injuries)
    assert result["listed"] is True


def test_qb_status_match_ignores_suffixes():
    """Name matching ignores Jr., Sr., III."""
    injuries = [
        _injury("DET", "Matthew Stafford Jr.", report_status="Doubtful"),
    ]
    result = nfl_grade.qb_status("DET", "Matthew Stafford", injuries)
    assert result["listed"] is True
    assert result["out"] is True


def test_qb_status_by_position_when_name_is_none():
    """When qb_name is None, match the first QB position in that team."""
    injuries = [
        _injury("BUF", "Josh Allen", position="QB", report_status="Out"),
        _injury("BUF", "Someone Else", position="WR", report_status=""),
    ]
    result = nfl_grade.qb_status("BUF", None, injuries)
    assert result["listed"] is True
    assert result["report_status"] == "Out"


def test_qb_status_empty_injuries():
    """Empty injury list means QB is unlisted."""
    result = nfl_grade.qb_status("BUF", "Josh Allen", [])
    assert result["listed"] is False


# ============================================================================
# board_status tests
# ============================================================================

def test_board_status_fresh_with_six_books():
    """Six books, fresh quote = ok and fresh."""
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.board_status(quotes, now=_now())
    assert result["books"] == 6
    assert result["ok"] is True
    assert result["fresh"] is True


def test_board_status_only_five_books():
    """Five books is not ok (need 6+)."""
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(5)]
    result = nfl_grade.board_status(quotes, now=_now())
    assert result["books"] == 5
    assert result["ok"] is False
    assert result["fresh"] is True


def test_board_status_stale_board():
    """More than 3 hours old is stale."""
    quotes = [_quote(f"book{i}", _utc(3.1)) for i in range(6)]
    result = nfl_grade.board_status(quotes, now=_now())
    assert result["books"] == 6
    assert result["ok"] is True
    assert result["fresh"] is False


def test_board_status_exactly_fresh_threshold():
    """Exactly 3 hours old is still fresh."""
    quotes = [_quote(f"book{i}", _utc(3)) for i in range(6)]
    result = nfl_grade.board_status(quotes, now=_now())
    assert result["fresh"] is True


def test_board_status_empty_quotes():
    """No quotes means no board."""
    result = nfl_grade.board_status([], now=_now())
    assert result["books"] is None
    assert result["ok"] is False
    assert result["fresh"] is False
    assert result["newest_utc"] is None


def test_board_status_newest_utc_is_latest():
    """newest_utc is the most recent timestamp."""
    oldest = _utc(5)
    middle = _utc(2)
    newest = _utc(0.5)
    quotes = [
        _quote("book1", oldest),
        _quote("book2", newest),
        _quote("book3", middle),
    ]
    result = nfl_grade.board_status(quotes, now=_now())
    assert result["newest_utc"] == newest


def test_board_status_custom_fresh_threshold():
    """Custom fresh_within_minutes overrides default."""
    quotes = [_quote("book1", _utc(2))]
    result = nfl_grade.board_status(quotes, now=_now(), fresh_within_minutes=60)
    assert result["fresh"] is False  # 2 hours > 60 minutes


def test_board_status_duplicate_books_counted_once():
    """Same book appearing multiple times is counted once."""
    quotes = [
        _quote("book1", _utc(1)),
        _quote("book1", _utc(1.5)),
        _quote("book2", _utc(0.5)),
    ]
    result = nfl_grade.board_status(quotes, now=_now())
    assert result["books"] == 2


# ============================================================================
# grade tests
# ============================================================================

def test_grade_ready_when_everything_is_ok():
    """All conditions met: ready=True, no reasons."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status=""),
        _injury("DET", "Jared Goff", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is True
    assert result["reasons"] == []


def test_grade_not_ready_injury_report_not_published():
    """If injury report missing for one team, not ready."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        # Only BUF injury, missing DET
        _injury("BUF", "Josh Allen", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is False
    assert result["injury_report_published"] is False
    assert "injury report for this game has not been published yet" in result["reasons"][0]


def test_grade_not_ready_board_not_ok():
    """Board with < 6 books makes game not ready."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status=""),
        _injury("DET", "Jared Goff", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(5)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is False
    assert result["board"]["ok"] is False
    assert "Fewer than six books" in result["reasons"][0]


def test_grade_not_ready_board_stale():
    """Stale board (> 3 hours) makes game not ready."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status=""),
        _injury("DET", "Jared Goff", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(3.1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is False
    assert result["board"]["fresh"] is False
    assert "The board is older than three hours" in result["reasons"][0]


def test_grade_not_ready_starting_qb_out():
    """Starting QB listed as Out makes game not ready."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status="Out"),
        _injury("DET", "Jared Goff", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is False
    assert result["away_qb"]["out"] is True
    assert result["starting_qb_out"] is True
    assert "A starting quarterback is listed as out" in result["reasons"][0]


def test_grade_not_ready_home_qb_doubtful():
    """Home QB marked Doubtful is also out."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status=""),
        _injury("DET", "Jared Goff", report_status="Doubtful"),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is False
    assert result["home_qb"]["out"] is True
    assert result["starting_qb_out"] is True


def test_grade_qb_questionable_does_not_block():
    """QB listed as Questionable doesn't block ready."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status="Questionable"),
        _injury("DET", "Jared Goff", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is True
    assert result["away_qb"]["listed"] is True
    assert result["away_qb"]["out"] is False


def test_grade_multiple_unready_reasons():
    """When multiple things are wrong, all reasons are listed."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status="Out"),
        # Missing DET injury
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(4)]  # Only 4 books
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is False
    assert len(result["reasons"]) >= 2
    # Check that we have reasons for injury report, board, and QB
    reason_text = "\n".join(result["reasons"])
    assert "injury report" in reason_text
    assert "books" in reason_text
    assert "quarterback" in reason_text


def test_grade_week_filtering():
    """Grade only considers injuries from the specified week."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=2)
    injuries = [
        # Week 1 injuries (ignored)
        _injury("BUF", "Josh Allen", report_status="Out", week=1),
        _injury("DET", "Jared Goff", report_status="", week=1),
        # Week 2 injuries (used)
        _injury("BUF", "Josh Allen", report_status="", week=2),
        _injury("DET", "Jared Goff", report_status="", week=2),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=2)
    # Josh Allen's week 1 "Out" should not matter for week 2 game
    assert result["ready"] is True
    assert result["away_qb"]["out"] is False


def test_grade_no_board_no_quotes():
    """No board at all is a clear not-ready."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", report_status=""),
        _injury("DET", "Jared Goff", report_status=""),
    ]
    result = nfl_grade.grade(game, injuries=injuries, quotes=[],
                             now=_now(), week=1)
    assert result["ready"] is False
    assert result["board"]["ok"] is False
    assert "No books" in result["reasons"][0]
    # Should NOT say "board is older than three hours" when there's no board
    assert "older than three hours" not in " ".join(result["reasons"])


def test_grade_reason_exact_sentences():
    """Verify that reason sentences match expected plain language."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = []  # No injury report
    quotes = [_quote(f"book{i}", _utc(4)) for i in range(6)]  # Stale but >= 6 books
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)

    # Should have two reasons: injury report and stale board
    assert len(result["reasons"]) == 2
    assert "The injury report for this game has not been published yet." in result["reasons"]
    assert "The board is older than three hours." in result["reasons"]


# ============================================================================
# Edge cases and integration
# ============================================================================

def test_grade_missing_qb_names_in_game():
    """Game without qb_name fields works (matches by position)."""
    game = _game("BUF", "DET", week=1)  # No qb names given
    injuries = [
        _injury("BUF", "Josh Allen", position="QB", report_status=""),
        _injury("DET", "Jared Goff", position="QB", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    assert result["ready"] is True


def test_grade_non_qb_injuries_ignored():
    """Only QB position matters for starting_qb_out check."""
    game = _game("BUF", "DET", away_qb="Josh Allen", home_qb="Jared Goff", week=1)
    injuries = [
        _injury("BUF", "Josh Allen", position="QB", report_status=""),
        _injury("BUF", "Stefon Diggs", position="WR", report_status="Out"),  # Not QB
        _injury("DET", "Jared Goff", position="QB", report_status=""),
    ]
    quotes = [_quote(f"book{i}", _utc(1)) for i in range(6)]
    result = nfl_grade.grade(game, injuries=injuries, quotes=quotes,
                             now=_now(), week=1)
    # WR out should not affect ready
    assert result["ready"] is True


# CI runs `python -m unittest discover` on a stdlib-only interpreter
from tests._unittest_bridge import as_test_case  # noqa: E402

FunctionTests = as_test_case(globals())
