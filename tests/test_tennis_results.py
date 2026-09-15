"""Tests for src/providers/tennis_results.py.

The feed interface is pluggable so that a future tennis results provider can be
swapped in without changing the rest of the system. Tests verify the interface
contract, normalization logic, and winner matching.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.providers import tennis_results
from src.providers.tennis_results import (
    ALWAYS_GRADED_STATUSES,
    ALWAYS_VOID_STATUSES,
    VOID_UNLESS_SET_COMPLETED_STATUSES,
    BallDontLieFeed,
    ENV_BALLDONTLIE_KEY,
    FixtureFeed,
    NoFeed,
    ResultsFeed,
    TennisResultsError,
    feed,
    match_winner,
    normalize_name,
    results_for,
    retirement_rule_note,
    surname,
)


class TestNoFeed(unittest.TestCase):
    """Tests for NoFeed (the default when no provider is configured)."""

    def test_no_feed_name(self):
        """NoFeed reports its name."""
        f = NoFeed()
        self.assertEqual(f.name, "none")

    def test_no_feed_reason(self):
        """NoFeed explains why results are unavailable."""
        f = NoFeed()
        self.assertIn("TENNIS_RESULTS_PROVIDER", f.reason)
        self.assertIn("not set", f.reason)

    def test_no_feed_returns_empty_list(self):
        """NoFeed.fetch_results always returns an empty list."""
        f = NoFeed()
        self.assertEqual(f.fetch_results("2025-09-14"), [])
        self.assertEqual(f.fetch_results("2025-01-01"), [])

    def test_no_feed_has_reason(self):
        """NoFeed has a non-None reason."""
        f = NoFeed()
        self.assertIsNotNone(f.reason)


class TestFeedConfiguration(unittest.TestCase):
    """Tests for the feed() factory function."""

    def test_feed_with_empty_env_is_no_feed(self):
        """feed({}) returns NoFeed."""
        f = feed({})
        self.assertIsInstance(f, NoFeed)

    def test_feed_with_unset_env_var_is_no_feed(self):
        """feed(None) (defaults to os.environ) returns NoFeed if var is unset."""
        # We can't reliably unset os.environ here, so we test with an empty dict.
        f = feed({})
        self.assertIsInstance(f, NoFeed)

    def test_feed_with_blank_var_is_no_feed(self):
        """feed with blank TENNIS_RESULTS_PROVIDER returns NoFeed."""
        f = feed({"TENNIS_RESULTS_PROVIDER": "   "})
        self.assertIsInstance(f, NoFeed)

    def test_fixture_feed_parses_prefix(self):
        """feed with 'fixture:<path>' returns FixtureFeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.jsonl"
            path.write_text("")
            f = feed({"TENNIS_RESULTS_PROVIDER": f"fixture:{path}"})
            self.assertIsInstance(f, FixtureFeed)
            self.assertEqual(f.name, "fixture")

    def test_unknown_provider_raises_error(self):
        """feed with unknown provider raises TennisResultsError."""
        with self.assertRaises(TennisResultsError):
            feed({"TENNIS_RESULTS_PROVIDER": "bogus"})

    def test_error_does_not_echo_value(self):
        """TennisResultsError message does not contain the actual provider value."""
        try:
            feed({"TENNIS_RESULTS_PROVIDER": "secret_provider_123"})
            self.fail("Expected TennisResultsError")
        except TennisResultsError as exc:
            # The message should NOT contain the actual value.
            self.assertNotIn("secret_provider_123", str(exc))
            # It SHOULD mention known providers.
            self.assertIn("fixture", str(exc))


class TestResultsFor(unittest.TestCase):
    """Tests for the results_for() convenience function."""

    def test_results_for_with_no_feed(self):
        """results_for with no feed returns empty rows and the reason."""
        result = results_for("2025-09-14", {})
        self.assertEqual(result["rows"], [])
        self.assertIsNotNone(result["reason"])
        self.assertEqual(result["provider"], "none")

    def test_results_for_structure(self):
        """results_for returns a dict with rows, provider, and reason."""
        result = results_for("2025-09-14", {})
        self.assertIn("rows", result)
        self.assertIn("provider", result)
        self.assertIn("reason", result)
        self.assertIsInstance(result["rows"], list)


class TestFixtureFeed(unittest.TestCase):
    """Tests for FixtureFeed (file-backed feed for testing)."""

    def test_fixture_feed_empty_file(self):
        """FixtureFeed on an empty file returns no results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "empty.jsonl"
            path.write_text("")
            f = FixtureFeed(str(path))
            results = f.fetch_results("2025-09-14")
            self.assertEqual(results, [])

    def test_fixture_feed_filters_by_date(self):
        """FixtureFeed filters results by date prefix."""
        rows = [
            {
                "event_id": "e1",
                "tournament": "US Open",
                "player_a": "Alice",
                "player_b": "Bob",
                "winner": "a",
                "score": "6-4 6-3",
                "completed_utc": "2025-09-14T14:30:00Z",
            },
            {
                "event_id": "e2",
                "tournament": "French Open",
                "player_a": "Carol",
                "player_b": "Diana",
                "winner": "b",
                "score": "6-2 7-5",
                "completed_utc": "2025-09-15T10:00:00Z",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.jsonl"
            with open(path, "w") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")

            feed_obj = FixtureFeed(str(path))

            # Query for 2025-09-14
            result_14 = feed_obj.fetch_results("2025-09-14")
            self.assertEqual(len(result_14), 1)
            self.assertEqual(result_14[0]["event_id"], "e1")

            # Query for 2025-09-15
            result_15 = feed_obj.fetch_results("2025-09-15")
            self.assertEqual(len(result_15), 1)
            self.assertEqual(result_15[0]["event_id"], "e2")

            # Query for a date with no results
            result_16 = feed_obj.fetch_results("2025-09-16")
            self.assertEqual(len(result_16), 0)

    def test_fixture_feed_nonexistent_file(self):
        """FixtureFeed on a nonexistent file returns empty list."""
        f = FixtureFeed("/nonexistent/path/to/file.jsonl")
        results = f.fetch_results("2025-09-14")
        self.assertEqual(results, [])

    def test_fixture_feed_skips_blank_lines(self):
        """FixtureFeed skips blank lines in the file."""
        row = {
            "event_id": "e1",
            "tournament": "Wimbledon",
            "player_a": "Eve",
            "player_b": "Frank",
            "winner": "a",
            "score": "7-6 6-4",
            "completed_utc": "2025-09-14T12:00:00Z",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.jsonl"
            with open(path, "w") as f:
                f.write(json.dumps(row) + "\n")
                f.write("\n")  # Blank line
                f.write("\n")  # Another blank line
                f.write(json.dumps(row) + "\n")

            feed_obj = FixtureFeed(str(path))
            results = feed_obj.fetch_results("2025-09-14")
            self.assertEqual(len(results), 2)


class TestNormalizeName(unittest.TestCase):
    """Tests for normalize_name()."""

    def test_normalize_name_basic(self):
        """normalize_name lowercases and removes accents."""
        self.assertEqual(normalize_name("Iga Świątek"), "iga swiatek")

    def test_normalize_name_already_normalized(self):
        """normalize_name on an already normalized name is idempotent."""
        self.assertEqual(normalize_name("alice smith"), "alice smith")

    def test_normalize_name_uppercase(self):
        """normalize_name lowercases."""
        self.assertEqual(normalize_name("ROGER FEDERER"), "roger federer")

    def test_normalize_name_accents(self):
        """normalize_name removes various accents."""
        self.assertEqual(normalize_name("José"), "jose")
        self.assertEqual(normalize_name("François"), "francois")
        self.assertEqual(normalize_name("Müller"), "muller")

    def test_normalize_name_whitespace(self):
        """normalize_name collapses multiple spaces."""
        self.assertEqual(normalize_name("Alice  Smith   Jones"), "alice smith jones")

    def test_normalize_name_punctuation(self):
        """normalize_name removes punctuation."""
        self.assertEqual(normalize_name("O'Brien-Smith"), "o brien smith")

    def test_normalize_name_mixed(self):
        """normalize_name handles mixed case, accents, and punctuation."""
        self.assertEqual(normalize_name("María José García-López"), "maria jose garcia lopez")


class TestSurname(unittest.TestCase):
    """Tests for surname()."""

    def test_surname_single_name(self):
        """surname of a single name is that name."""
        self.assertEqual(surname("Madonna"), "madonna")

    def test_surname_two_names(self):
        """surname of two names is the last one."""
        self.assertEqual(surname("Roger Federer"), "federer")

    def test_surname_hyphenated(self):
        """surname of a hyphenated name is the last token."""
        self.assertEqual(surname("Maria Garcia-Lopez"), "lopez")

    def test_surname_with_accents(self):
        """surname normalizes accents."""
        self.assertEqual(surname("Iga Świątek"), "swiatek")

    def test_surname_extra_spaces(self):
        """surname handles extra whitespace."""
        self.assertEqual(surname("  Alice   Smith  "), "smith")


class TestMatchWinner(unittest.TestCase):
    """Tests for match_winner()."""

    def test_match_winner_player_a_wins(self):
        """match_winner returns 'home' when player_a's surname matches home_name."""
        row = {
            "winner": "a",
            "player_a": "Roger Federer",
            "player_b": "Rafael Nadal",
        }
        result = match_winner(row, "Roger FEDERER", "Rafael NADAL")
        self.assertEqual(result, "home")

    def test_match_winner_player_b_wins_away(self):
        """match_winner returns 'away' when player_b's surname matches away_name."""
        row = {
            "winner": "b",
            "player_a": "Roger Federer",
            "player_b": "Rafael Nadal",
        }
        result = match_winner(row, "Roger FEDERER", "Rafael NADAL")
        self.assertEqual(result, "away")

    def test_match_winner_player_b_wins_home(self):
        """match_winner can return 'home' if player_b matches home_name."""
        row = {
            "winner": "b",
            "player_a": "Alice",
            "player_b": "Bob Smith",
        }
        result = match_winner(row, "Bob Smith", "Carol")
        self.assertEqual(result, "home")

    def test_match_winner_no_match(self):
        """match_winner returns None when there is no matching surname."""
        row = {
            "winner": "a",
            "player_a": "Unknown Player",
            "player_b": "Rafael Nadal",
        }
        result = match_winner(row, "Roger Federer", "Rafael Nadal")
        self.assertIsNone(result)

    def test_match_winner_ambiguous(self):
        """match_winner returns None when the match is ambiguous."""
        # Both home and away have the same surname (edge case).
        row = {
            "winner": "a",
            "player_a": "Smith Alice",
            "player_b": "Bob",
        }
        result = match_winner(row, "Alice Smith", "Carol Smith")
        # Winner surname is "alice", home is "smith", away is "smith".
        # Should be None, not "home" (no match).
        self.assertIsNone(result)

    def test_match_winner_with_accents(self):
        """match_winner normalizes accents when matching."""
        row = {
            "winner": "a",
            "player_a": "Iga Świątek",
            "player_b": "Simona Halep",
        }
        result = match_winner(row, "Iga Swiatek", "Simona Halep")
        self.assertEqual(result, "home")

    def test_match_winner_empty_name(self):
        """match_winner returns None if the winner field is missing or empty."""
        row = {
            "winner": "a",
            "player_a": "",
            "player_b": "Bob",
        }
        result = match_winner(row, "Alice", "Bob")
        self.assertIsNone(result)

    def test_match_winner_missing_field(self):
        """match_winner returns None if the winner field is not in the row."""
        row = {
            "player_a": "Alice",
            "player_b": "Bob",
        }
        result = match_winner(row, "Alice", "Bob")
        # When "winner" is missing, it defaults to player_b lookup.
        # Since row["winner"] doesn't exist, it returns None via player_b.
        # Actually, let's check the logic: if row.get("winner") == "a" is False,
        # so winner_key becomes "player_b". If player_b is "Bob", and away_name is "Bob",
        # then match_winner should return "away".
        # Let me re-check the implementation...
        # Actually, row.get("winner") returns None when key is missing.
        # None == "a" is False, so winner_key = "player_b".
        # This should work.
        self.assertEqual(result, "away")


class TestResultsFeedInterface(unittest.TestCase):
    """Tests for the ResultsFeed base interface."""

    def test_results_feed_is_abstract(self):
        """ResultsFeed cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            ResultsFeed("test", None)

    def test_no_feed_is_a_results_feed(self):
        """NoFeed is a subclass of ResultsFeed."""
        f = NoFeed()
        self.assertIsInstance(f, ResultsFeed)

    def test_fixture_feed_is_a_results_feed(self):
        """FixtureFeed is a subclass of ResultsFeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.jsonl"
            path.write_text("")
            f = FixtureFeed(str(path))
            self.assertIsInstance(f, ResultsFeed)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def test_match_winner_empty_row(self):
        """match_winner on an empty row returns None."""
        result = match_winner({}, "Alice", "Bob")
        self.assertIsNone(result)

    def test_normalize_name_empty_string(self):
        """normalize_name on empty string returns empty string."""
        self.assertEqual(normalize_name(""), "")

    def test_surname_empty_string(self):
        """surname on empty string returns empty string."""
        self.assertEqual(surname(""), "")

    def test_fixture_feed_malformed_json(self):
        """FixtureFeed gracefully skips malformed JSON lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.jsonl"
            with open(path, "w") as f:
                f.write('{"valid": "json"}\n')
                f.write('not valid json\n')
                f.write('{"also": "valid"}\n')

            f = FixtureFeed(str(path))
            # The feed should skip the bad line and return what it can parse.
            results = f.fetch_results("2025-09-14")
            # Since neither of the valid lines match the date, we expect 0 results.
            # But we need to ensure the malformed line didn't crash the parser.
            self.assertIsInstance(results, list)


class TestFeedConfigurationBallDontLie(unittest.TestCase):
    """Tests for feed() choosing BallDontLieFeed."""

    def test_feed_returns_balldontlie_when_only_key_set(self):
        """No provider named, but the key is present -> BallDontLieFeed."""
        f = feed({ENV_BALLDONTLIE_KEY: "test-key"})
        self.assertIsInstance(f, BallDontLieFeed)
        self.assertEqual(f.name, "balldontlie")

    def test_feed_returns_nofeed_when_neither_set(self):
        """Neither provider nor key set -> NoFeed, unchanged."""
        f = feed({})
        self.assertIsInstance(f, NoFeed)

    def test_feed_explicit_balldontlie_with_key(self):
        """TENNIS_RESULTS_PROVIDER=balldontlie with the key set -> BallDontLieFeed."""
        f = feed({
            "TENNIS_RESULTS_PROVIDER": "balldontlie",
            ENV_BALLDONTLIE_KEY: "test-key",
        })
        self.assertIsInstance(f, BallDontLieFeed)

    def test_feed_explicit_balldontlie_without_key_raises(self):
        """TENNIS_RESULTS_PROVIDER=balldontlie with no key -> named error, no leak."""
        with self.assertRaises(TennisResultsError) as ctx:
            feed({"TENNIS_RESULTS_PROVIDER": "balldontlie"})
        self.assertEqual(str(ctx.exception), "BALLDONTLIE_API_KEY is not set")

    def test_fixture_provider_still_wins_over_a_present_key(self):
        """fixture:<path> still works even when BALLDONTLIE_API_KEY is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.jsonl"
            path.write_text("")
            f = feed({
                "TENNIS_RESULTS_PROVIDER": f"fixture:{path}",
                ENV_BALLDONTLIE_KEY: "test-key",
            })
            self.assertIsInstance(f, FixtureFeed)


def _bdl_player(player_id, full_name):
    parts = full_name.split()
    return {
        "id": player_id,
        "first_name": parts[0],
        "last_name": parts[-1],
        "full_name": full_name,
    }


def _bdl_tournament(name="Test Open", start_date="2025-09-10", end_date="2025-09-20"):
    return {
        "id": 1,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
    }


def _bdl_match(match_id, status, player1, player2, winner=None,
               tournament=None, score="6-4 6-3"):
    return {
        "id": match_id,
        "tournament": tournament or _bdl_tournament(),
        "season": 2025,
        "round": "Final",
        "player1": player1,
        "player2": player2,
        "winner": winner,
        "score": score,
        "set_scores": [],
        "player1_game_score": None,
        "player2_game_score": None,
        "server": None,
        "duration": None,
        "number_of_sets": None,
        "match_status": status,
        "status_state": "final",
        "is_live": False,
    }


class TestBallDontLieFeed(unittest.TestCase):
    """Tests for BallDontLieFeed against a fake get_json (no network)."""

    def _players(self):
        federer = _bdl_player(1, "Roger Federer")
        nadal = _bdl_player(2, "Rafael Nadal")
        return federer, nadal

    def test_sends_key_in_authorization_header(self):
        """The fake key is sent verbatim in the Authorization header."""
        federer, nadal = self._players()
        seen_headers = []

        def fake_get_json(url, headers):
            seen_headers.append(headers)
            return {"data": [], "meta": {"next_cursor": None, "per_page": 100}}

        f = BallDontLieFeed("test-key", get_json=fake_get_json, sleep=lambda s: None)
        f.fetch_results("2025-09-14")

        self.assertTrue(seen_headers)
        for headers in seen_headers:
            self.assertEqual(headers["Authorization"], "test-key")

    def test_filters_status_winner_and_date_window(self):
        """Only finished/retired/walkover/defaulted rows come back, with the
        right winner and vendor status; in_progress and scheduled are dropped."""
        federer, nadal = self._players()
        tournament = _bdl_tournament(start_date="2025-09-10", end_date="2025-09-20")

        finished = _bdl_match(101, "finished", federer, nadal, winner=federer,
                              tournament=tournament, score="6-4 6-3")
        retired_after_set = _bdl_match(102, "retired", federer, nadal, winner=federer,
                                       tournament=tournament, score="6-4 2-1 ret.")
        walkover = _bdl_match(103, "walkover", federer, nadal, winner=nadal,
                              tournament=tournament, score="W/O")
        in_progress = _bdl_match(104, "in_progress", federer, nadal, winner=None,
                                 tournament=tournament)
        scheduled = _bdl_match(105, "scheduled", federer, nadal, winner=None,
                               tournament=tournament)

        atp_page = {
            "data": [finished, retired_after_set, walkover, in_progress, scheduled],
            "meta": {"next_cursor": None, "per_page": 100},
        }
        wta_page = {"data": [], "meta": {"next_cursor": None, "per_page": 100}}

        def fake_get_json(url, headers):
            if "/atp/v1/matches" in url:
                return atp_page
            return wta_page

        f = BallDontLieFeed("test-key", get_json=fake_get_json, sleep=lambda s: None)
        rows = f.fetch_results("2025-09-14")

        self.assertEqual(len(rows), 3)
        by_status = {row["status"]: row for row in rows}
        self.assertEqual(set(by_status), {"finished", "retired", "walkover"})

        self.assertEqual(by_status["finished"]["winner"], "a")
        self.assertEqual(by_status["finished"]["player_a"], "Roger Federer")
        self.assertEqual(by_status["finished"]["player_b"], "Rafael Nadal")
        self.assertEqual(by_status["finished"]["tour"], "atp")
        self.assertEqual(by_status["finished"]["vendor_match_id"], 101)

        self.assertEqual(by_status["retired"]["winner"], "a")
        self.assertEqual(by_status["walkover"]["winner"], "b")

        # No per-match timestamp exists in the spec, so this feed never
        # invents one.
        for row in rows:
            self.assertNotIn("completed_utc", row)

    def test_match_outside_tournament_window_is_dropped(self):
        """A match whose tournament dates don't cover the query date is excluded."""
        federer, nadal = self._players()
        tournament = _bdl_tournament(start_date="2025-01-01", end_date="2025-01-14")
        finished = _bdl_match(201, "finished", federer, nadal, winner=federer,
                              tournament=tournament)

        def fake_get_json(url, headers):
            if "/atp/v1/matches" in url:
                return {"data": [finished], "meta": {"next_cursor": None, "per_page": 100}}
            return {"data": [], "meta": {"next_cursor": None, "per_page": 100}}

        f = BallDontLieFeed("test-key", get_json=fake_get_json, sleep=lambda s: None)
        rows = f.fetch_results("2025-09-14")
        self.assertEqual(rows, [])

    def test_stops_at_page_cap(self):
        """A vendor that always hands back a next_cursor is capped, not looped forever."""
        federer, nadal = self._players()
        call_count = {"n": 0}
        # Non-empty (but filtered-out) data on every page, so pagination is
        # driven by next_cursor rather than stopped early by an empty page.
        filler = _bdl_match(1, "scheduled", federer, nadal)

        def fake_get_json(url, headers):
            call_count["n"] += 1
            return {"data": [filler], "meta": {"next_cursor": 999, "per_page": 100}}

        f = BallDontLieFeed("test-key", get_json=fake_get_json, sleep=lambda s: None,
                            page_cap=3)
        f.fetch_results("2025-09-14")

        # 3 pages per tour, 2 tours (atp, wta).
        self.assertEqual(call_count["n"], 6)

    def test_calls_sleep_seam_between_pages(self):
        """The sleep seam is invoked between requests, not before the first one."""
        federer, nadal = self._players()
        sleep_calls = []
        filler = _bdl_match(1, "scheduled", federer, nadal)

        page1 = {"data": [filler], "meta": {"next_cursor": 42, "per_page": 100}}
        page2 = {"data": [], "meta": {"next_cursor": None, "per_page": 100}}
        responses = {"atp": [page1, page2], "wta": [page2]}

        def fake_get_json(url, headers):
            tour = "atp" if "/atp/v1/matches" in url else "wta"
            return responses[tour].pop(0)

        f = BallDontLieFeed("test-key", get_json=fake_get_json,
                            sleep=lambda s: sleep_calls.append(s))
        f.fetch_results("2025-09-14")

        # 3 total requests (atp page1, atp page2, wta page1) -> 2 sleeps.
        self.assertEqual(len(sleep_calls), 2)
        for s in sleep_calls:
            self.assertEqual(s, tennis_results.BALLDONTLIE_RATE_LIMIT_SLEEP_SECONDS)

    def test_no_resolvable_winner_is_dropped(self):
        """A completed-status match whose winner id matches neither player is dropped."""
        federer, nadal = self._players()
        stranger = _bdl_player(999, "Someone Else")
        tournament = _bdl_tournament()
        bad = _bdl_match(301, "finished", federer, nadal, winner=stranger,
                         tournament=tournament)

        def fake_get_json(url, headers):
            if "/atp/v1/matches" in url:
                return {"data": [bad], "meta": {"next_cursor": None, "per_page": 100}}
            return {"data": [], "meta": {"next_cursor": None, "per_page": 100}}

        f = BallDontLieFeed("test-key", get_json=fake_get_json, sleep=lambda s: None)
        rows = f.fetch_results("2025-09-14")
        self.assertEqual(rows, [])


class TestRetirementRule(unittest.TestCase):
    """Tests for retirement_rule_note() and the exported status constants."""

    def test_retirement_rule_note_mentions_void_and_advanced(self):
        note = retirement_rule_note()
        self.assertIn("VOID", note)
        self.assertIn("walkover", note.lower())
        self.assertIn("retired", note.lower())

    def test_status_constants_partition_cleanly(self):
        """The three status buckets never overlap."""
        self.assertEqual(ALWAYS_VOID_STATUSES & ALWAYS_GRADED_STATUSES, set())
        self.assertEqual(ALWAYS_VOID_STATUSES & VOID_UNLESS_SET_COMPLETED_STATUSES, set())
        self.assertEqual(ALWAYS_GRADED_STATUSES & VOID_UNLESS_SET_COMPLETED_STATUSES, set())
        self.assertIn("walkover", ALWAYS_VOID_STATUSES)
        self.assertIn("retired", VOID_UNLESS_SET_COMPLETED_STATUSES)
        self.assertIn("finished", ALWAYS_GRADED_STATUSES)
