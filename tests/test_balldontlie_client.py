"""Tests for src/providers/balldontlie.py.

All network is faked at the Client's single transport seam -- either the
old `(path, params, headers) -> (status, body)` 2-tuple shape or the new
`(status, body, response_headers)` 3-tuple shape; nothing here touches a
socket. Covers: the Authorization header carries the raw key, cursor
pagination (including page_cap), the pacer never exceeds its configured
rate under a fake clock, 5xx backs off then succeeds, the 429 wait policy
(Retry-After / x-ratelimit-reset / 61s default, the max_429_wait_seconds
cap, and the caller deadline), the pacer adapting after a 429, the header
whitelist, and no error string or rate_state() ever contains the key or an
unlisted header.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from src.providers.balldontlie import (
    BallDontLieDeadlineExceeded,
    BallDontLieError,
    BallDontLieHTTPError,
    BallDontLieRateLimitExhausted,
    Client,
    ClientConfig,
    DEFAULT_MAX_429_ATTEMPTS,
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
    """Fake transport: returns queued (status, payload) 2-tuple responses in
    order (the pre-headers shape), and records every (path, params, headers)
    call it received. Used to prove the 2-tuple shape still works."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, path, params, headers):
        self.calls.append((path, dict(params), dict(headers)))
        status, payload = self._responses.pop(0)
        return status, _body(payload)


class HeaderedTransport:
    """Fake transport returning the new 3-tuple (status, payload,
    response_headers) shape, for exercising 429 / rate-limit-header
    handling. `responses` is a list of (status, payload_dict, headers_dict)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, path, params, headers):
        self.calls.append((path, dict(params), dict(headers)))
        status, payload, resp_headers = self._responses.pop(0)
        return status, _body(payload), dict(resp_headers)


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
            headers = {}  # real urlopen responses expose .headers.items()

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
    """5xx retries: unchanged bounded exponential backoff. 429 has its own
    policy -- see TestRateLimitWait / TestRateLimitPacerAdaptation /
    TestRateLimitCapsAndDeadline below."""

    def test_5xx_backs_off_then_succeeds(self):
        responses = [
            (503, {}),
            (502, {}),
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

    def test_5xx_retries_exhausted_raises_http_error(self):
        responses = [(503, {})] * 10
        transport = RecordingTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000,
                                              max_retries=2, backoff_cap=10.0))

        with self.assertRaises(BallDontLieHTTPError) as ctx:
            client.get("/atp/v1/matches", {})
        self.assertEqual(ctx.exception.status, 503)
        # Backoff is capped -- never exceeds backoff_cap.
        for delay in sleep.calls:
            self.assertLessEqual(delay, 10.0)


class TestRateLimitWait(unittest.TestCase):
    """429 handling waits instead of giving up -- see
    src/providers/balldontlie.py's "429 POLICY" docstring. Every case here
    uses a fast pacer (rate_per_minute=6000, bucket_capacity=6000) so the
    pacer itself never sleeps -- every recorded sleep call is the 429 wait."""

    def _fast_client(self, transport, clock, sleep, **config_kwargs):
        return Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                      config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000,
                                           **config_kwargs))

    def test_retry_after_waits_that_long_then_succeeds(self):
        responses = [
            (429, {}, {"Retry-After": "5"}),
            (200, {"data": [{"id": 1}], "meta": {}}, {}),
        ]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = self._fast_client(transport, clock, sleep)

        result = client.get("/nfl/v1/games", {})

        self.assertEqual(result["data"], [{"id": 1}])
        self.assertEqual(sleep.calls, [5.0])

    def test_ratelimit_reset_epoch_waits_until_reset(self):
        # A value above 10**9 is epoch seconds, not seconds-until-reset --
        # the wait is (reset_epoch - now), using the injectable wall clock.
        clock = FakeClock(start=2_000_000_000.0)
        sleep = FakeSleep(clock)
        reset_epoch = clock.now + 45.0
        responses = [
            (429, {}, {"X-RateLimit-Reset": str(reset_epoch)}),
            (200, {"data": [], "meta": {}}, {}),
        ]
        transport = HeaderedTransport(responses)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep, now=clock,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000))

        client.get("/nfl/v1/games", {})

        self.assertEqual(sleep.calls, [45.0])

    def test_ratelimit_reset_seconds_until_reset_waits_that_long(self):
        # A value at or below 10**9 is seconds-until-reset, used as-is.
        responses = [
            (429, {}, {"ratelimit-reset": "12"}),
            (200, {"data": [], "meta": {}}, {}),
        ]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = self._fast_client(transport, clock, sleep)

        client.get("/nfl/v1/games", {})

        self.assertEqual(sleep.calls, [12.0])

    def test_no_headers_waits_61_seconds(self):
        responses = [(429, {}, {}), (200, {"data": [], "meta": {}}, {})]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = self._fast_client(transport, clock, sleep)

        client.get("/nfl/v1/games", {})

        self.assertEqual(sleep.calls, [61.0])

    def test_2_tuple_transport_still_works_for_429(self):
        # Backward compat: a transport that still returns the old 2-tuple
        # shape is treated as having no headers, so it gets the 61s default.
        responses = [(429, {}), (200, {"data": [], "meta": {}})]
        transport = RecordingTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = self._fast_client(transport, clock, sleep)

        result = client.get("/nfl/v1/games", {})

        self.assertEqual(result["data"], [])
        self.assertEqual(sleep.calls, [61.0])


class TestRateLimitPacerAdaptation(unittest.TestCase):
    def test_adapts_to_95_percent_of_ratelimit_limit(self):
        responses = [
            (429, {}, {"X-RateLimit-Limit": "10"}),
            (200, {"data": [], "meta": {}}, {}),
        ]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000))

        client.get("/nfl/v1/games", {})

        state = client.rate_state()
        self.assertAlmostEqual(state["rate_per_minute"], 9.5, places=6)
        self.assertEqual(state["limit"], 10.0)

    def test_halves_with_floor_when_no_limit_header(self):
        responses = [(429, {}, {}), (200, {"data": [], "meta": {}}, {})]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6, bucket_capacity=6000))

        client.get("/nfl/v1/games", {})

        # 6/2 = 3, below the 4/min floor -- floor wins.
        self.assertAlmostEqual(client.rate_state()["rate_per_minute"], 4.0, places=6)

    def test_halves_without_hitting_floor(self):
        responses = [(429, {}, {}), (200, {"data": [], "meta": {}}, {})]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=20, bucket_capacity=6000))

        client.get("/nfl/v1/games", {})

        self.assertAlmostEqual(client.rate_state()["rate_per_minute"], 10.0, places=6)


class TestRateLimitCapsAndDeadline(unittest.TestCase):
    def test_wait_never_passes_the_deadline_and_raises(self):
        responses = [(429, {}, {})] * 3
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000))

        # Default wait (no headers) is 61s; a 10s-away deadline must cap the
        # sleep to 10s and then raise, never sleeping the full 61.
        with self.assertRaises(BallDontLieDeadlineExceeded):
            client.get("/nfl/v1/games", {}, deadline=10.0)

        self.assertEqual(sleep.calls, [10.0])

    def test_exhausting_max_429_wait_seconds_raises(self):
        responses = [(429, {}, {})] * 5
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000,
                                              max_429_wait_seconds=100.0))

        with self.assertRaises(BallDontLieRateLimitExhausted) as ctx:
            client.get("/nfl/v1/games", {})

        self.assertLessEqual(sum(sleep.calls), 100.0)
        self.assertEqual(ctx.exception.path, "/nfl/v1/games")

    def test_default_max_429_wait_seconds_is_900(self):
        self.assertEqual(ClientConfig().max_429_wait_seconds, 900.0)


class TestRateLimitAttemptBound(unittest.TestCase):
    """Root cause F (2026-09-15 incident): a computed 429 wait of 0 (e.g. a
    malformed/zero Retry-After, or an x-ratelimit-reset already in the past)
    must not let get() retry with no bound at all -- max_429_wait_seconds
    alone never fires in that case because rate_limit_wait_total never
    grows. Measured at 188,101 requests / zero progress in one real run
    before this existed."""

    def test_zero_computed_wait_does_not_retry_unboundedly(self):
        # A huge max_429_wait_seconds proves the SECONDS-based cap is not
        # what stops this -- only the attempt counter can.
        responses = [(429, {}, {"Retry-After": "0"})] * (DEFAULT_MAX_429_ATTEMPTS + 20)
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000,
                                              max_429_wait_seconds=10 ** 9))

        with self.assertRaises(BallDontLieRateLimitExhausted):
            client.get("/nfl/v1/games", {})

        self.assertLessEqual(len(transport.calls), DEFAULT_MAX_429_ATTEMPTS + 1)

    def test_zero_retry_after_wait_is_floored_to_a_minimum(self):
        # Belt-and-braces alongside the attempt bound: a computed 0 must
        # not look like "no wait needed" for even a single attempt.
        responses = [(429, {}, {"Retry-After": "0"}), (200, {"data": [], "meta": {}}, {})]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000))

        client.get("/nfl/v1/games", {})

        self.assertEqual(sleep.calls, [1.0])


class TestRateLimitHeaderWhitelist(unittest.TestCase):
    def test_only_whitelisted_headers_survive_into_rate_state(self):
        responses = [
            (429, {}, {
                "Retry-After": "1",
                "X-RateLimit-Limit": "10",
                "Set-Cookie": "session=abc123",
                "Authorization": FAKE_KEY,
            }),
            (200, {"data": [], "meta": {}}, {}),
        ]
        transport = HeaderedTransport(responses)
        clock = FakeClock()
        sleep = FakeSleep(clock)
        client = Client(FAKE_KEY, transport=transport, clock=clock, sleep=sleep,
                         config=ClientConfig(rate_per_minute=6000, bucket_capacity=6000))

        client.get("/nfl/v1/games", {})

        state = client.rate_state()
        self.assertNotIn("set-cookie", state)
        self.assertNotIn(FAKE_KEY, repr(state))
        self.assertNotIn("session=abc123", repr(state))
        # The whitelisted one made it through.
        self.assertEqual(state["limit"], 10.0)

    def test_probe_only_returns_whitelisted_headers(self):
        transport = HeaderedTransport([
            (200, {"data": []}, {
                "X-RateLimit-Remaining": "42",
                "Set-Cookie": "x=y",
                "Authorization": FAKE_KEY,
            }),
        ])
        client = Client(FAKE_KEY, transport=transport, clock=FakeClock(), sleep=lambda s: None)

        status, headers = client.probe("/nfl/v1/teams", {"per_page": 1})

        self.assertEqual(status, 200)
        self.assertEqual(headers, {"x-ratelimit-remaining": "42"})
        self.assertEqual(len(transport.calls), 1)


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
