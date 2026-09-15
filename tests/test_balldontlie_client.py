"""Tests for src/providers/balldontlie.py.

All network is faked at the Client's single transport seam
(`(path, params, headers) -> (status, body)`); nothing here touches a
socket. Covers: the Authorization header carries the raw key, cursor
pagination (including page_cap), the pacer never exceeds its configured
rate under a fake clock, 429 backs off then succeeds, and no error string
ever contains the key.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from src.providers.balldontlie import (
    BallDontLieError,
    BallDontLieHTTPError,
    Client,
    ClientConfig,
    client_from_env,
)

FAKE_KEY = "sk-test-do-not-use-1234567890"


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSleep:
    """Records every sleep call and advances a FakeClock by that amount."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.calls = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


def _body(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


class RecordingTransport:
    """Fake transport: returns queued (status, payload) responses in order,
    and records every (path, params, headers) call it received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, path, params, headers):
        self.calls.append((path, dict(params), dict(headers)))
        status, payload = self._responses.pop(0)
        return status, _body(payload)


class TestHeaders(unittest.TestCase):
    def test_authorization_header_carries_raw_key(self):
        transport = RecordingTransport([(200, {"data": [], "meta": {}})])
        client = Client(FAKE_KEY, transport=transport,
                         clock=FakeClock(), sleep=lambda s: None)
        client.get("/atp/v1/matches", {"season": 2024})

        self.assertEqual(len(transport.calls), 1)
        _, _, headers = transport.calls[0]
        self.assertEqual(headers["Authorization"], FAKE_KEY)
        # No "Bearer " prefix -- the spec's apiKey scheme documents none.
        self.assertNotIn("Bearer", headers["Authorization"])

    def test_default_transport_puts_key_in_header_not_url(self):
        # Exercises the real (non-injected) transport with urlopen mocked,
        # to confirm the key never ends up in the request URL.
        client = Client(FAKE_KEY)
        captured = {}

        class FakeResponse:
            status = 200

            def read(self):
                return _body({"data": [], "meta": {}})

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["header"] = request.get_header("Authorization")
            return FakeResponse()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            client.get("/atp/v1/matches", {"season": 2024})

        self.assertEqual(captured["header"], FAKE_KEY)
        self.assertNotIn(FAKE_KEY, captured["url"])


class TestPagination(unittest.TestCase):
    def test_follows_next_cursor(self):
        responses = [
            (200, {"data": [{"id": 1}], "meta": {"next_cursor": 10}}),
            (200, {"data": [{"id": 2}], "meta": {"next_cursor": 20}}),
            (200, {"data": [{"id": 3}], "meta": {}}),  # no next_cursor -> stop
        ]
        transport = RecordingTransport(responses)
        client = Client(FAKE_KEY, transport=transport,
                         clock=FakeClock(), sleep=lambda s: None)

        pages = list(client.pages("/atp/v1/matches", {"season": 2024}))

        self.assertEqual(len(pages), 3)
        self.assertEqual(transport.calls[0][1].get("cursor"), None)
        self.assertEqual(transport.calls[1][1]["cursor"], 10)
        self.assertEqual(transport.calls[2][1]["cursor"], 20)

    def test_stops_at_page_cap(self):
        # Every page claims there's a next_cursor -- without page_cap this
        # would loop forever.
        responses = [(200, {"data": [{"id": i}], "meta": {"next_cursor": i + 1}})
                     for i in range(1, 50)]
        transport = RecordingTransport(responses)
        client = Client(FAKE_KEY, transport=transport,
                         clock=FakeClock(), sleep=lambda s: None)

        pages = list(client.pages("/atp/v1/matches", {}, page_cap=3))

        self.assertEqual(len(pages), 3)
        self.assertEqual(len(transport.calls), 3)

    def test_empty_data_stops_pagination(self):
        responses = [(200, {"data": [], "meta": {"next_cursor": 5}})]
        transport = RecordingTransport(responses)
        client = Client(FAKE_KEY, transport=transport,
                         clock=FakeClock(), sleep=lambda s: None)

        pages = list(client.pages("/atp/v1/matches", {}))
        self.assertEqual(len(pages), 1)

    def test_resumes_from_start_cursor(self):
        responses = [(200, {"data": [{"id": 99}], "meta": {}})]
        transport = RecordingTransport(responses)
        client = Client(FAKE_KEY, transport=transport,
                         clock=FakeClock(), sleep=lambda s: None)

        list(client.pages("/atp/v1/matches", {}, start_cursor=777))
        self.assertEqual(transport.calls[0][1]["cursor"], 777)


class TestPacer(unittest.TestCase):
    def test_never_exceeds_configured_rate(self):
        # 60 requests/minute == 1/second, capacity 1 (no burst): every
        # request after the first must be preceded by a >=1s simulated
        # sleep. With a fake clock that never advances on its own, the
        # only way time passes is through the pacer's own sleep calls.
        clock = FakeClock()
        sleep = FakeSleep(clock)
        transport = RecordingTransport([(200, {"data": [], "meta": {}})] * 5)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=60, bucket_capacity=1.0))

        for _ in range(5):
            client.get("/atp/v1/matches", {})

        # First request is free (bucket starts full); the other 4 each
        # forced a wait of ~1 second (60/60).
        self.assertEqual(len(sleep.calls), 4)
        for delay in sleep.calls:
            self.assertAlmostEqual(delay, 1.0, places=6)
        self.assertAlmostEqual(clock.now, 4.0, places=6)

    def test_burst_capacity_allows_immediate_requests_up_to_capacity(self):
        clock = FakeClock()
        sleep = FakeSleep(clock)
        transport = RecordingTransport([(200, {"data": [], "meta": {}})] * 3)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=60, bucket_capacity=3.0))

        for _ in range(3):
            client.get("/atp/v1/matches", {})

        # All three fit inside the initial burst capacity -- no sleeping.
        self.assertEqual(sleep.calls, [])


class TestBackoff(unittest.TestCase):
    def test_429_then_5xx_back_off_then_succeed(self):
        responses = [
            (429, {}),
            (503, {}),
            (200, {"data": [{"id": 1}], "meta": {}}),
        ]
        transport = RecordingTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000,
                                              backoff_base=1.0, backoff_cap=60.0))

        result = client.get("/atp/v1/matches", {})

        self.assertEqual(result["data"], [{"id": 1}])
        self.assertEqual(len(transport.calls), 3)
        # Exponential backoff: 1s, then 2s.
        self.assertEqual(sleep.calls, [1.0, 2.0])

    def test_retries_exhausted_raises_http_error(self):
        responses = [(429, {})] * 10
        transport = RecordingTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000,
                                              max_retries=2, backoff_cap=10.0))

        with self.assertRaises(BallDontLieHTTPError) as ctx:
            client.get("/atp/v1/matches", {})
        self.assertEqual(ctx.exception.status, 429)
        # Backoff is capped -- never exceeds backoff_cap.
        for delay in sleep.calls:
            self.assertLessEqual(delay, 10.0)


class TestErrorsNeverLeakTheKey(unittest.TestCase):
    def test_http_error_message_has_no_key_and_no_query(self):
        transport = RecordingTransport([(403, {})])
        client = Client(FAKE_KEY, transport=transport,
                         clock=FakeClock(), sleep=lambda s: None)

        with self.assertRaises(BallDontLieHTTPError) as ctx:
            client.get("/atp/v1/odds/opening", {"season": 2024, "match_ids": [1, 2, 3]})

        message = str(ctx.exception)
        self.assertNotIn(FAKE_KEY, message)
        self.assertNotIn("season=2024", message)
        self.assertNotIn("match_ids", message)
        self.assertEqual(ctx.exception.status, 403)

    def test_invalid_json_error_has_no_key(self):
        class BadJsonTransport:
            def __call__(self, path, params, headers):
                return 200, b"not json{{{"

        client = Client(FAKE_KEY, transport=BadJsonTransport(),
                         clock=FakeClock(), sleep=lambda s: None)
        with self.assertRaises(BallDontLieError) as ctx:
            client.get("/atp/v1/matches", {})
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_connection_error_message_has_no_key(self):
        def raising_transport(path, params, headers):
            raise BallDontLieError("could not reach balldontlie API: [Errno 111] refused")

        client = Client(FAKE_KEY, transport=raising_transport,
                         clock=FakeClock(), sleep=lambda s: None)
        with self.assertRaises(BallDontLieError) as ctx:
            client.get("/atp/v1/matches", {})
        self.assertNotIn(FAKE_KEY, str(ctx.exception))


class TestClientFromEnv(unittest.TestCase):
    def test_raises_plain_error_naming_variable_when_unset(self):
        with self.assertRaises(BallDontLieError) as ctx:
            client_from_env(env={})
        self.assertIn("BALLDONTLIE_API_KEY", str(ctx.exception))
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_builds_client_when_set(self):
        client = client_from_env(env={"BALLDONTLIE_API_KEY": FAKE_KEY})
        self.assertIsInstance(client, Client)

    def test_strips_whitespace(self):
        client = client_from_env(env={"BALLDONTLIE_API_KEY": f"  {FAKE_KEY}  "})
        self.assertIsInstance(client, Client)


if __name__ == "__main__":
    unittest.main()
