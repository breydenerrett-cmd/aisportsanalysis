"""src/appstate/reqlog.py: structured log-line formatting and redaction."""

from __future__ import annotations

import unittest

from src.appstate import reqlog


class UserRefTests(unittest.TestCase):

    def test_anonymous_request_has_no_ref(self):
        self.assertIsNone(reqlog.user_ref(None))

    def test_same_user_id_hashes_the_same_way_every_time(self):
        self.assertEqual(reqlog.user_ref(42), reqlog.user_ref(42))

    def test_different_user_ids_hash_differently(self):
        self.assertNotEqual(reqlog.user_ref(1), reqlog.user_ref(2))

    def test_the_raw_id_never_appears_in_its_own_hash(self):
        self.assertNotIn("42", reqlog.user_ref(42))

    def test_hash_length_is_bounded(self):
        self.assertEqual(len(reqlog.user_ref(7)), reqlog.USER_HASH_LENGTH)


class FormatLineTests(unittest.TestCase):

    def test_anonymous_line_shape(self):
        line = reqlog.format_line(method="GET", path_template="/health",
                                  status=200, latency_ms=12.345)
        self.assertIn("method=GET", line)
        self.assertIn("path=/health", line)
        self.assertIn("status=200", line)
        self.assertIn("latency_ms=12.3", line)
        self.assertIn("user=-", line)

    def test_authed_line_carries_a_hash_not_the_raw_id(self):
        line = reqlog.format_line(method="GET", path_template="/my-bets",
                                  status=200, latency_ms=5.0, user_id=99)
        self.assertIn(f"user={reqlog.user_ref(99)}", line)
        self.assertNotIn("user=99", line)

    def test_error_id_rides_along_only_when_given(self):
        no_error = reqlog.format_line(method="GET", path_template="/x",
                                      status=200, latency_ms=1.0)
        self.assertNotIn("error_id", no_error)
        with_error = reqlog.format_line(method="GET", path_template="/x",
                                        status=500, latency_ms=1.0,
                                        error_id="abc123")
        self.assertIn("error_id=abc123", with_error)

    def test_line_has_no_embedded_newline(self):
        line = reqlog.format_line(method="GET", path_template="/game/{date}",
                                  status=200, latency_ms=1.0)
        self.assertNotIn("\n", line)


class RedactionGuardTests(unittest.TestCase):
    """A blunt but honest net: these substrings must never show up in what
    this module produces, and the guard itself must actually catch them."""

    def test_a_clean_line_passes(self):
        line = reqlog.format_line(method="GET", path_template="/health",
                                  status=200, latency_ms=1.0, user_id=5)
        self.assertFalse(reqlog.contains_forbidden_content(line))

    def test_a_bearer_token_is_caught(self):
        self.assertTrue(reqlog.contains_forbidden_content(
            "method=GET path=/x Authorization: Bearer sekrit"))

    def test_an_email_shaped_string_is_caught(self):
        self.assertTrue(reqlog.contains_forbidden_content(
            "user requested as breydenerrett@gmail.com"))

    def test_format_line_itself_never_produces_forbidden_content(self):
        """Regression net: format_line's own output, across the full
        parameter surface, must never trip the guard it is judged by."""
        line = reqlog.format_line(method="POST", path_template="/betcheck",
                                  status=500, latency_ms=999.9, user_id=123,
                                  error_id="deadbeef")
        self.assertFalse(reqlog.contains_forbidden_content(line))


if __name__ == "__main__":
    unittest.main()
