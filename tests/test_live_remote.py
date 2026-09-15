"""Tests for src/pipeline/live_remote.py"""

import unittest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

try:
    from src.pipeline import live_remote
    _HAVE_MODULE = True
except Exception:  # noqa: BLE001
    _HAVE_MODULE = False


@unittest.skipUnless(_HAVE_MODULE, "live_remote module not found")
class RemoteTextFetching(unittest.TestCase):
    """fetch_text handles network requests and errors gracefully."""

    def test_fetch_text_returns_content_on_200(self):
        """fetch_text returns response text when status is 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"hello world"
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = live_remote.fetch_text("http://example.com/test")

        self.assertEqual("hello world", result)

    def test_fetch_text_returns_none_on_error(self):
        """fetch_text returns None on any exception."""
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = live_remote.fetch_text("http://example.com/test")

        self.assertIsNone(result)

    def test_fetch_text_returns_none_on_non_200(self):
        """fetch_text returns None on non-200 status (tested by checking implementation)."""
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = live_remote.fetch_text("http://example.com/test")

        # The function checks `if resp.status == 200`, so 404 should return None
        self.assertIsNone(result)


@unittest.skipUnless(_HAVE_MODULE, "live_remote module not found")
class RemoteTextCaching(unittest.TestCase):
    """cached_text caches for ttl and refetches after expiry."""

    def setUp(self):
        """Clear cache before each test."""
        live_remote._CACHE.clear()

    def test_cached_text_returns_cached_value_within_ttl(self):
        """cached_text returns cached value when not expired."""
        call_count = [0]

        def mock_fetch(url):
            call_count[0] += 1
            return f"result_{call_count[0]}"

        now = 1000.0
        result1 = live_remote.cached_text("test_path", ttl_seconds=60, now=now, fetch=mock_fetch)
        result2 = live_remote.cached_text("test_path", ttl_seconds=60, now=now + 30, fetch=mock_fetch)

        self.assertEqual("result_1", result1)
        self.assertEqual("result_1", result2)
        self.assertEqual(1, call_count[0])  # Only called once

    def test_cached_text_refetches_after_ttl_expiry(self):
        """cached_text refetches when TTL expires."""
        call_count = [0]

        def mock_fetch(url):
            call_count[0] += 1
            return f"result_{call_count[0]}"

        now = 1000.0
        result1 = live_remote.cached_text("test_path", ttl_seconds=60, now=now, fetch=mock_fetch)
        result2 = live_remote.cached_text("test_path", ttl_seconds=60, now=now + 61, fetch=mock_fetch)

        self.assertEqual("result_1", result1)
        self.assertEqual("result_2", result2)
        self.assertEqual(2, call_count[0])

    def test_cached_text_caches_failed_fetch_as_none(self):
        """cached_text caches None for failed fetches."""
        call_count = [0]

        def mock_fetch(url):
            call_count[0] += 1
            return None

        now = 1000.0
        result1 = live_remote.cached_text("test_path", ttl_seconds=60, now=now, fetch=mock_fetch)
        result2 = live_remote.cached_text("test_path", ttl_seconds=60, now=now + 30, fetch=mock_fetch)

        self.assertIsNone(result1)
        self.assertIsNone(result2)
        self.assertEqual(1, call_count[0])  # Only called once, none cached

    def test_cached_text_respects_env_off(self):
        """cached_text returns None when LIVE_REMOTE_BASE env is 'off'."""
        with patch.dict("os.environ", {live_remote.REMOTE_BASE_ENV: "off"}):
            result = live_remote.cached_text("test_path", fetch=lambda u: "should_not_call")

        self.assertIsNone(result)


@unittest.skipUnless(_HAVE_MODULE, "live_remote module not found")
class RemoteJsonlParsing(unittest.TestCase):
    """remote_jsonl skips corrupt lines."""

    def setUp(self):
        live_remote._CACHE.clear()

    def test_remote_jsonl_parses_valid_lines(self):
        """remote_jsonl returns parsed JSON objects."""
        jsonl_text = '{"a": 1}\n{"b": 2}\n{"c": 3}\n'

        def mock_fetch(url):
            return jsonl_text

        result = live_remote.remote_jsonl("test.jsonl", fetch=mock_fetch)

        self.assertEqual(3, len(result))
        self.assertEqual({"a": 1}, result[0])
        self.assertEqual({"b": 2}, result[1])
        self.assertEqual({"c": 3}, result[2])

    def test_remote_jsonl_skips_corrupt_lines(self):
        """remote_jsonl skips lines that fail JSON parsing."""
        jsonl_text = '{"a": 1}\ninvalid json\n{"b": 2}\n'

        def mock_fetch(url):
            return jsonl_text

        result = live_remote.remote_jsonl("test.jsonl", fetch=mock_fetch)

        self.assertEqual(2, len(result))
        self.assertEqual({"a": 1}, result[0])
        self.assertEqual({"b": 2}, result[1])

    def test_remote_jsonl_returns_empty_when_fetch_fails(self):
        """remote_jsonl returns empty list when fetch fails."""
        def mock_fetch(url):
            return None

        result = live_remote.remote_jsonl("test.jsonl", fetch=mock_fetch)

        self.assertEqual([], result)


@unittest.skipUnless(_HAVE_MODULE, "live_remote module not found")
class RemoteLiveStateFunctions(unittest.TestCase):
    """live_state_rows and live_candidate_rows work correctly."""

    def setUp(self):
        live_remote._CACHE.clear()

    def test_live_state_rows_returns_mlb_data(self):
        """live_state_rows reads data/live/mlb/{date}.jsonl."""
        jsonl_text = '{"game_pk": "g1", "home_team": "Yankees"}\n'

        def mock_fetch(url):
            self.assertIn("data/live/mlb/2026-09-14.jsonl", url)
            return jsonl_text

        result = live_remote.live_state_rows("mlb", "2026-09-14", fetch=mock_fetch)

        self.assertEqual(1, len(result))
        self.assertEqual("g1", result[0]["game_pk"])

    def test_live_candidate_rows_returns_candidate_data(self):
        """live_candidate_rows reads evidence/live_candidates_v1.jsonl."""
        jsonl_text = '{"rule_id": "rule1", "sport": "mlb"}\n'

        def mock_fetch(url):
            self.assertIn("evidence/live_candidates_v1.jsonl", url)
            return jsonl_text

        result = live_remote.live_candidate_rows(fetch=mock_fetch)

        self.assertEqual(1, len(result))
        self.assertEqual("rule1", result[0]["rule_id"])


@unittest.skipUnless(_HAVE_MODULE, "live_remote module not found")
class RemoteEnabledCheck(unittest.TestCase):
    """enabled() returns False when env is 'off', True otherwise."""

    def test_enabled_returns_true_by_default(self):
        """enabled() returns True when env var is not set."""
        env = {}
        self.assertTrue(live_remote.enabled(env=env))

    def test_enabled_returns_false_when_off(self):
        """enabled() returns False when env value is 'off'."""
        env = {live_remote.REMOTE_BASE_ENV: "off"}
        self.assertFalse(live_remote.enabled(env=env))

    def test_enabled_uses_os_environ_by_default(self):
        """enabled() uses os.environ when env is not passed."""
        with patch.dict("os.environ", {live_remote.REMOTE_BASE_ENV: "off"}):
            self.assertFalse(live_remote.enabled())

        with patch.dict("os.environ", {}, clear=False):
            if live_remote.REMOTE_BASE_ENV in __import__("os").environ:
                del __import__("os").environ[live_remote.REMOTE_BASE_ENV]
            self.assertTrue(live_remote.enabled())


@unittest.skipUnless(_HAVE_MODULE, "live_remote module not found")
class RemoteBaseUrl(unittest.TestCase):
    """Default base URL contains raw.githubusercontent.com and the branch."""

    def test_default_base_contains_github_raw(self):
        """_DEFAULT_BASE includes raw.githubusercontent.com."""
        self.assertIn("raw.githubusercontent.com", live_remote._DEFAULT_BASE)

    def test_default_base_contains_branch(self):
        """_DEFAULT_BASE includes DEFAULT_BRANCH."""
        self.assertIn(live_remote.DEFAULT_BRANCH, live_remote._DEFAULT_BASE)

    def test_owner_repo_derived_correctly(self):
        """_OWNER_REPO is extracted from git remote."""
        # The actual value depends on the git repo
        self.assertIn("/", live_remote._OWNER_REPO)
        self.assertNotIn(".git", live_remote._OWNER_REPO)


if __name__ == "__main__":
    unittest.main()
