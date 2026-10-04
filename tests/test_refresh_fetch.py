"""The fetch layer under the display refresh (2026-10-04): count, reuse, bounded
retry, stop on an authentication denial, and say which kind of "nothing" or
"failure" a call was.

No network and no sleeping: the wire is a scripted function installed at the
same seam the pipelines use (`mlb._get_json`), the layer's `sleep` is a list.
"""

from __future__ import annotations

import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from src.pipeline.refresh_fetch import (CONSECUTIVE_FAILURE_LIMIT, MAX_RETRIES, FetchLayer,
                                        endpoint_class)
from src.providers import mlb, mlb_news, statcast


def http_error(code, retry_after=None, path="schedule"):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    cause = urllib.error.HTTPError("https://example.test", code, "x", headers, io.BytesIO(b""))
    cause.close()
    err = mlb.MLBError(f"MLB API returned HTTP {code} for {path}")
    err.__cause__ = cause
    return err


def final_schedule(pk=7, code="F"):
    return {"dates": [{"games": [{"gamePk": pk, "status": {"codedGameState": code}}]}]}


BOX = {"teams": {"away": {}, "home": {}}}


class Wire:
    """A scripted `mlb._get_json`: `script` is a list of payloads or exceptions
    consumed in order; the last one repeats."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, path, params=None, timeout=None):
        self.calls.append((path, dict(params or {})))
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


class Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "cache"
        self.sleeps = []

    def layer(self, **kw):
        kw.setdefault("sleep", self.sleeps.append)
        kw.setdefault("cache_dir", self.cache)
        return FetchLayer(**kw)

    def run_with(self, wire, layer, fn):
        with mock.patch.object(mlb, "_get_json", wire), layer.install():
            return fn()


class AnAuthenticationDenialStopsAtOnce(Base):

    def test_a_403_is_one_request_no_retry_and_no_sleep(self):
        wire = Wire(http_error(403))
        layer = self.layer()

        def go():
            with self.assertRaises(mlb.MLBError):
                mlb._get_json("schedule", {"date": "2026-10-01"})
        self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertIn("authentication denied (HTTP 403)", layer.halted)
        self.assertEqual(layer.summary()["outcomes"], {"auth_denied": 1})

    def test_every_later_call_fails_instantly_with_no_request(self):
        wire = Wire(http_error(401))
        layer = self.layer()

        def go():
            for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
                with self.assertRaises(mlb.MLBError) as caught:
                    mlb._get_json("schedule", {"date": day})
            return str(caught.exception)
        message = self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), 1, "no retry storm: the second and third made no request")
        self.assertIn("halted", message)
        self.assertEqual(layer.summary()["outcomes"], {"auth_denied": 1, "halted": 2})

    def test_the_news_and_savant_seams_halt_the_run_too(self):
        layer = self.layer()
        news = mock.Mock(side_effect=mlb_news.NewsError("MLB transactions returned HTTP 403"))
        with mock.patch.object(mlb_news, "_get_json", news), layer.install():
            with self.assertRaises(mlb_news.NewsError):
                mlb_news._get_json("transactions", {"startDate": "2026-10-01"})
        self.assertEqual(news.call_count, 1)
        self.assertIn("HTTP 403", layer.halted)
        with mock.patch.object(statcast, "fetch_arsenal", mock.Mock()), layer.install():
            with self.assertRaises(statcast.StatcastError):
                statcast.fetch_arsenal("2026", side="pitcher")
        self.assertEqual(self.sleeps, [])


class RetriesAreBounded(Base):

    def test_429_then_success_retries_twice_with_a_short_backoff(self):
        wire = Wire(http_error(429), http_error(429), final_schedule(code="S"))
        layer = self.layer()
        self.run_with(wire, layer, lambda: mlb._get_json("schedule", {"date": "d"}))
        self.assertEqual(len(wire.calls), 3)
        self.assertEqual(self.sleeps, [1.0, 2.0])
        summary = layer.summary()
        self.assertEqual((summary["network_calls"], summary["retries"], summary["requests_made"]), (1, 2, 3))

    def test_retry_after_is_honoured_up_to_a_cap(self):
        wire = Wire(http_error(429, retry_after=500), final_schedule(code="S"))
        layer = self.layer()
        self.run_with(wire, layer, lambda: mlb._get_json("schedule", {"date": "d"}))
        self.assertEqual(self.sleeps, [30.0])

    def test_a_persistent_503_is_bounded_and_reported_as_a_failure(self):
        wire = Wire(http_error(503))
        layer = self.layer()

        def go():
            with self.assertRaises(mlb.MLBError):
                mlb._get_json("schedule", {"date": "d"})
        self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), 1 + MAX_RETRIES)
        self.assertEqual(len(self.sleeps), MAX_RETRIES)
        self.assertEqual(layer.summary()["outcomes"], {"http_error": 1})
        self.assertEqual(layer.summary()["failed"], 1)

    def test_a_404_and_a_malformed_body_are_not_retried(self):
        wire = Wire(http_error(404, path="people/1/stats"), mlb.MLBError("MLB API returned invalid JSON for x"))
        layer = self.layer()

        def go():
            with self.assertRaises(mlb.MLBError):
                mlb._get_json("people/1/stats", {"stats": "gameLog"})
            with self.assertRaises(mlb.MLBError):
                mlb._get_json("schedule", {"date": "d"})
        self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), 2)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(layer.summary()["outcomes"], {"not_found": 1, "invalid": 1})

    def test_a_transport_failure_is_not_stacked_on_the_providers_own_retry(self):
        wire = Wire(mlb.MLBError("could not reach MLB API for schedule: timed out"))
        layer = self.layer()

        def go():
            with self.assertRaises(mlb.MLBError):
                mlb._get_json("schedule", {"date": "d"})
        self.run_with(wire, layer, go)
        self.assertEqual((len(wire.calls), self.sleeps), (1, []))
        self.assertEqual(layer.summary()["outcomes"], {"transport_error": 1})

    def test_a_run_of_hard_failures_halts_the_run(self):
        wire = Wire(mlb.MLBError("could not reach MLB API for schedule: reset"))
        layer = self.layer()

        def go():
            for n in range(CONSECUTIVE_FAILURE_LIMIT + 3):
                with self.assertRaises(mlb.MLBError):
                    mlb._get_json("schedule", {"date": f"d{n}"})
        self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), CONSECUTIVE_FAILURE_LIMIT, "the rest made no request")
        self.assertIn("consecutive failed requests", layer.halted)

    def test_three_calls_that_stay_429_halt_the_run(self):
        wire = Wire(http_error(429))
        layer = self.layer()

        def go():
            for n in range(6):
                with self.assertRaises(mlb.MLBError):
                    mlb._get_json("schedule", {"date": f"d{n}"})
        self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), 3 * (1 + MAX_RETRIES))
        self.assertIn("rate limited", layer.halted)


class EveryCallIsOneOfTheKindsAReaderMustNotConfuse(Base):

    def test_data_empty_reused_and_failed_are_four_different_outcomes(self):
        empty_log = {"stats": []}
        full = {"stats": [{"splits": [{"date": "2026-10-01"}]}]}
        wire = Wire(full, empty_log, mlb.MLBError("could not reach MLB API for x: reset"))
        layer = self.layer()

        def go():
            mlb._get_json("people/1/stats", {"stats": "gameLog"})          # data
            mlb._get_json("people/2/stats", {"stats": "gameLog"})          # nothing to report
            mlb._get_json("people/1/stats", {"stats": "gameLog"})          # asked before
            with self.assertRaises(mlb.MLBError):
                mlb._get_json("people/3/stats", {"stats": "gameLog"})      # no answer
        self.run_with(wire, layer, go)
        summary = layer.summary()
        self.assertEqual(summary["outcomes"], {"ok": 1, "ok_empty": 1, "cache_memo": 1, "transport_error": 1})
        self.assertEqual((summary["network_calls"], summary["reused"], summary["failed"],
                          summary["missing_source_data"]), (3, 1, 1, 1))

    def test_a_per_step_window_is_the_calls_since_the_mark(self):
        wire = Wire(final_schedule(code="S"))
        layer = self.layer()

        def go():
            mlb._get_json("schedule", {"date": "a"})
            mark = layer.mark()
            mlb._get_json("schedule", {"date": "b"})
            mlb._get_json("schedule", {"date": "b"})
            return layer.summary(mark)
        step = self.run_with(wire, layer, go)
        self.assertEqual((step["calls"], step["network_calls"], step["reused"]), (2, 1, 1))
        self.assertNotIn("wire_attempts", step)

    def test_endpoint_classes(self):
        self.assertEqual(endpoint_class("game/5/boxscore"), "boxscore")
        self.assertEqual(endpoint_class("people/5/stats", {"stats": "gameLog"}), "pitcher_game_log")
        self.assertEqual(endpoint_class("people/5/stats", {"stats": "statSplits"}), "pitcher_splits")
        self.assertEqual(endpoint_class("schedule"), "schedule")


class FetchOnceReuseEverywhere(Base):

    def test_the_same_url_in_one_run_is_asked_once(self):
        wire = Wire(final_schedule(code="S"))
        layer = self.layer()

        def go():
            for _ in range(4):
                mlb._get_json("schedule", {"sportId": 1, "date": "2026-10-04", "hydrate": "x"})
            # parameter order does not make a different URL
            mlb._get_json("schedule", {"hydrate": "x", "date": "2026-10-04", "sportId": 1})
        self.run_with(wire, layer, go)
        self.assertEqual(len(wire.calls), 1)
        self.assertEqual(layer.summary()["reused"], 4)

    def test_a_reused_answer_is_a_copy_not_the_cached_object(self):
        wire = Wire(final_schedule(code="S"))
        layer = self.layer()

        def go():
            first = mlb._get_json("schedule", {"date": "d"})
            first["dates"].clear()
            return mlb._get_json("schedule", {"date": "d"})
        self.assertTrue(self.run_with(wire, layer, go)["dates"])

    def test_a_settled_day_and_its_final_boxscore_survive_a_restart(self):
        wire = Wire(final_schedule(pk=7, code="F"))
        layer = self.layer()

        def first():
            mlb._get_json("schedule", {"date": "2026-10-01"})
            mlb._get_json("game/7/boxscore", {})
        wire.script = [final_schedule(pk=7, code="F"), BOX]
        self.run_with(wire, layer, first)
        self.assertEqual(len(wire.calls), 2)

        again = Wire(AssertionError("a settled answer must not be asked for twice"))
        second = self.layer()           # a new process: new memory, the same disk
        self.run_with(again, second, first)
        self.assertEqual(again.calls, [])
        self.assertEqual(second.summary()["outcomes"], {"cache_disk": 2})

    def test_nothing_that_can_still_change_is_kept_on_disk(self):
        scheduled = {"dates": [{"games": [{"gamePk": 8, "status": {"codedGameState": "S"}}]}]}
        wire = Wire(scheduled, {"stats": [{"splits": [{"date": "2026-10-01"}]}]}, BOX)
        layer = self.layer()

        def go():
            mlb._get_json("schedule", {"date": "2026-10-04"})                    # a game still to play
            mlb._get_json("people/1/stats", {"stats": "gameLog"})                # a log moves with every start
            mlb._get_json("game/8/boxscore", {})                                 # a game not shown final
        self.run_with(wire, layer, go)
        self.assertFalse(list(self.cache.rglob("*.json")) if self.cache.exists() else [])

    def test_a_corrupt_or_foreign_cache_file_is_a_miss_not_an_error(self):
        wire = Wire(final_schedule(pk=7, code="F"))
        layer = self.layer()
        self.run_with(wire, layer, lambda: mlb._get_json("schedule", {"date": "2026-10-01"}))
        for path in self.cache.rglob("*.json"):
            path.write_text("{ not json", encoding="utf-8")
        again = Wire(final_schedule(pk=7, code="F"))
        self.run_with(again, self.layer(), lambda: mlb._get_json("schedule", {"date": "2026-10-01"}))
        self.assertEqual(len(again.calls), 1)

    def test_an_expired_entry_is_asked_for_again(self):
        now = {"t": 1000.0}
        wire = Wire(final_schedule(pk=7, code="F"))
        layer = self.layer(clock=lambda: now["t"], immutable_ttl_s=100.0)
        self.run_with(wire, layer, lambda: mlb._get_json("schedule", {"date": "2026-10-01"}))
        now["t"] = 1200.0
        again = Wire(final_schedule(pk=7, code="F"))
        self.run_with(again, self.layer(clock=lambda: now["t"], immutable_ttl_s=100.0),
                      lambda: mlb._get_json("schedule", {"date": "2026-10-01"}))
        self.assertEqual(len(again.calls), 1)

    def test_an_unwritable_cache_never_breaks_a_fetch(self):
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("a file where the cache directory should be", encoding="utf-8")
        layer = self.layer(cache_dir=blocker / "inside")
        wire = Wire(final_schedule(pk=7, code="F"))
        self.run_with(wire, layer, lambda: mlb._get_json("schedule", {"date": "2026-10-01"}))
        self.assertEqual(layer.summary()["outcomes"], {"ok": 1})

    def test_the_seams_are_restored_whatever_happens(self):
        before = (mlb._get_json, mlb_news._get_json, statcast.fetch_arsenal)
        layer = self.layer()
        with self.assertRaises(RuntimeError):
            with layer.install():
                self.assertIsNot(mlb._get_json, before[0])
                raise RuntimeError("boom")
        self.assertEqual((mlb._get_json, mlb_news._get_json, statcast.fetch_arsenal), before)


if __name__ == "__main__":
    unittest.main()
