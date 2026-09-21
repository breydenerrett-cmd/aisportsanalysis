"""Tests for src.pipeline.live_window.

All tests use fakes, temp directories, and a fake clock that advances per sleep.
"""

import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import live_window

_GIT_AVAILABLE = shutil.which("git") is not None


class FakeClock:
    """Advances on each sleep() call."""

    def __init__(self, start_utc=None):
        self.now = start_utc or datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class TestPregameContext(unittest.TestCase):
    """Tests for pregame_context."""

    def test_pregame_context_mlb_with_fixture_data(self):
        """pregame_context returns game_pk -> pregame dict with favourite."""
        # The shape src.providers.mlb.parse_game actually returns: flat keys,
        # team abbreviations, probable-pitcher ids. This fixture used to carry
        # the raw Stats API payload (teams.home.team.name), which
        # fetch_games never hands to this function, so it was testing a shape
        # production does not produce.
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:40:00Z",
                "home_team": "BOS",
                "away_team": "NYY",
                "home_probable_id": 112211,
                "away_probable_id": 123456,
            }
        ]
        rows = [
            {
                "sport": "mlb",
                "home_team": "Boston Red Sox",
                "away_team": "New York Yankees",
                "commence_time": "2026-09-14T21:40:00Z",
                "book": "DraftKings",
                "home_price": -110,
                "away_price": -110,
                "observed_utc": "2026-09-14T20:00:00Z",
            },
        ]

        context = live_window.pregame_context(
            "mlb", "2026-09-14", rows=rows, games=games
        )

        self.assertIn("747101", context)
        self.assertEqual(context["747101"]["sport"], "mlb")
        self.assertEqual(context["747101"]["home_team"], "BOS")
        self.assertEqual(context["747101"]["away_team"], "NYY")
        self.assertIn(context["747101"]["favorite"], ["home", "away", None])

    def test_pregame_context_nfl_with_data(self):
        """pregame_context works for NFL games."""
        games = [
            {
                "game_id": "2026_02_DET_BUF",
                "start_utc": "2026-09-14T01:20:00Z",
                "home": "Buffalo Bills",
                "away": "Detroit Lions",
            }
        ]

        context = live_window.pregame_context("nfl", "2026-09-14", games=games)

        self.assertIn("2026_02_DET_BUF", context)
        self.assertEqual(context["2026_02_DET_BUF"]["sport"], "nfl")

    def test_pregame_context_empty_games(self):
        """pregame_context returns empty dict when no games."""
        context = live_window.pregame_context("mlb", "2026-09-15", games=[])
        self.assertEqual(context, {})


class TestTick(unittest.TestCase):
    """Tests for tick -- R16-L5's rule-gated capture design: a capture is
    driven only by a registered trigger, retried at T0+45s/T0+90s, plus one
    non-gating follow-up at T0+5min; never by "any state change"."""

    PREGAME = {
        "pk1": {
            "sport": "mlb",
            "game_id": "pk1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "favorite": "home",
            "favorite_prob": 0.6,
            "starter_ids": {"home": 1, "away": 2},
            "event_id": "evt1",
        }
    }

    TRIGGERING_STATE = {
        "status": "Live", "home_runs": 2, "away_runs": 3,
        "inning": 3, "inning_state": "End",
        "observed_utc": "2026-09-14T20:00:00Z",
    }

    def _quote(self, observed_utc, last_update, n_books=3):
        return {
            "observed_utc": observed_utc,
            "quotes": [
                {"book": f"book{i}", "home_price": -110 - i, "away_price": 100 + i,
                 "last_update": last_update}
                for i in range(n_books)
            ],
        }

    def _make_state(self, prev_states=None):
        return {
            "date": "2026-09-14",
            "prev_states": prev_states or {},
            "pregame": self.PREGAME,
        }

    def _deps(self, capture_fn, registry_status=None):
        return {
            "poll": lambda: {"live_games": 1, "rows_written": 1},
            "capture": capture_fn,
            # Never let a test reach the real ledger (owned by another agent
            # this pass) -- record is always faked here.
            "record": lambda candidate: {**candidate, "recorded_utc": "test"},
            "registry_status": registry_status or {
                "mlb_favorite_trails_after_3": "registered",
                "mlb_starter_pulled_early": "unregistered",
            },
        }

    def test_no_capture_when_no_trigger_fires(self):
        """No registered trigger condition holds: no capture, nothing
        tracked."""
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs)
            return {"captured": 0}

        state = self._make_state()
        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {
                "status": "Live", "home_runs": 0, "away_runs": 0,
                "inning": 1, "observed_utc": "2026-09-14T19:00:00Z",
            }}
            result = live_window.tick("mlb", state=state, deps=self._deps(mock_capture))

        self.assertEqual(result["changed"], 0)
        self.assertEqual(capture_calls, [])
        self.assertEqual(state["trigger_state"], {})

    def test_unregistered_rule_captures_nothing(self):
        """A rule whose registry status is not registered/forward-testing
        fires no trigger and captures nothing, even though its condition
        genuinely holds."""
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs)
            return {"captured": 5}

        state = self._make_state()
        deps = self._deps(mock_capture, registry_status={
            "mlb_favorite_trails_after_3": "unregistered",
            "mlb_starter_pulled_early": "unregistered",
        })

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": self.TRIGGERING_STATE}
            result = live_window.tick("mlb", state=state, deps=deps)

        self.assertEqual(result["changed"], 0)
        self.assertEqual(capture_calls, [])
        self.assertEqual(state["trigger_state"], {})

    def test_registered_trigger_captures_once_prices_and_records(self):
        """A registered rule's trigger fires: exactly one capture is made
        (at T0), it prices with >= 3 fresh books, and exactly one candidate
        is recorded."""
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs.get("reason"))
            return {"captured": 3}

        clock = FakeClock(start_utc=datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc))
        state = self._make_state()

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": self.TRIGGERING_STATE}
            with mock.patch("src.pipeline.live_odds.read_inplay", return_value=[]):
                with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                    m_quote.return_value = self._quote(
                        "2026-09-14T20:00:00Z", "2026-09-14T20:00:00Z")
                    result = live_window.tick(
                        "mlb", state=state, clock=clock, deps=self._deps(mock_capture))

        self.assertEqual(result["changed"], 1)  # one trigger newly registered
        self.assertEqual(len(capture_calls), 1)
        self.assertIn("retry_0", capture_calls[0])
        self.assertEqual(result["candidates_new"], 1)
        key = ("pk1", "mlb_favorite_trails_after_3")
        self.assertIn(key, state["trigger_state"])
        self.assertTrue(state["trigger_state"][key]["priced"])

    def test_second_poll_same_trigger_does_not_recapture_or_reregister(self):
        """A second poll where the underlying condition still holds (or an
        unrelated field changed) must NOT re-register the same
        (game_id, rule_id) trigger or capture again before its next retry is
        due -- one trigger per rule per game (3.1), and no capture "on any
        change"."""
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs.get("reason"))
            return {"captured": 3}

        clock = FakeClock(start_utc=datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc))
        state = self._make_state()
        deps = self._deps(mock_capture)

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": self.TRIGGERING_STATE}
            with mock.patch("src.pipeline.live_odds.read_inplay", return_value=[]):
                with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                    m_quote.return_value = self._quote(
                        "2026-09-14T20:00:00Z", "2026-09-14T20:00:00Z")
                    live_window.tick("mlb", state=state, clock=clock, deps=deps)

                    # An unrelated field changes (e.g. an out is recorded),
                    # 20 seconds later -- well before the T0+45s retry.
                    clock.sleep(20)
                    unrelated_change = dict(self.TRIGGERING_STATE)
                    unrelated_change["outs"] = 1
                    unrelated_change["observed_utc"] = "2026-09-14T20:00:20Z"
                    m_states.return_value = {"pk1": unrelated_change}
                    result = live_window.tick("mlb", state=state, clock=clock, deps=deps)

        self.assertEqual(result["changed"], 0)  # no NEW trigger registered
        self.assertEqual(len(capture_calls), 1)  # still just the T0 capture
        self.assertEqual(len(state["trigger_state"]), 1)

    def test_retries_at_45_and_90_seconds_then_followup_at_5_minutes(self):
        """Full schedule: T0 capture is unpriced (< 3 fresh books), T0+45s
        retry prices it, T0+90s has nothing due, T0+5min takes the one
        descriptive follow-up capture that is never recorded as a
        candidate."""
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs.get("reason"))
            return {"captured": 2}

        clock = FakeClock(start_utc=datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc))
        state = self._make_state()
        deps = self._deps(mock_capture)

        quotes_by_call = [
            self._quote("2026-09-14T20:00:00Z", "2026-09-14T20:00:00Z", n_books=2),   # T0: unpriced
            self._quote("2026-09-14T20:00:45Z", "2026-09-14T20:00:45Z", n_books=3),   # T0+45s: prices
            self._quote("2026-09-14T20:05:00Z", "2026-09-14T20:05:00Z", n_books=3),   # follow-up
        ]

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": self.TRIGGERING_STATE}
            with mock.patch("src.pipeline.live_odds.read_inplay", return_value=[]):
                with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                    m_quote.side_effect = quotes_by_call

                    result_t0 = live_window.tick("mlb", state=state, clock=clock, deps=deps)
                    self.assertEqual(result_t0["candidates_new"], 0)  # unpriced

                    clock.sleep(45)
                    result_45 = live_window.tick("mlb", state=state, clock=clock, deps=deps)
                    self.assertEqual(result_45["candidates_new"], 1)  # now prices

                    clock.sleep(45)  # now at T0 + 90s
                    result_90 = live_window.tick("mlb", state=state, clock=clock, deps=deps)

                    clock.sleep(210)  # now at T0 + 300s (5 minutes)
                    result_followup = live_window.tick("mlb", state=state, clock=clock, deps=deps)

        self.assertEqual(len(capture_calls), 3)
        for call_reason, expected in zip(capture_calls, ("retry_0", "retry_45", "followup_5m")):
            self.assertIn(expected, call_reason)
        self.assertEqual(result_90["captured"], 0)  # nothing due at T0+90s
        self.assertEqual(result_followup["candidates_new"], 0)  # follow-up never gates
        key = ("pk1", "mlb_favorite_trails_after_3")
        self.assertTrue(state["trigger_state"][key]["followup_done"])

    def test_time_based_nfl_trigger_evaluated_every_poll_not_only_on_change(self):
        """D5: the NFL halftime proxy is a TIME-based trigger and must fire
        from check_all_triggers on a poll where nothing in the raw state
        changed at all between polls."""
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs.get("reason"))
            return {"captured": 3}

        commence = datetime(2026, 9, 14, 18, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=90)
        pregame = {
            "nfl1": {
                "sport": "nfl", "game_id": "nfl1", "home_team": "Cowboys",
                "away_team": "Eagles", "favorite": "home", "favorite_prob": 0.65,
                "kickoff_utc": commence.isoformat(),
            }
        }
        nfl_state = {
            "home_score": 10, "away_score": 14, "completed": False,
            "observed_utc": observed.isoformat(),
        }
        state = {"date": "2026-09-14", "prev_states": {"nfl1": nfl_state}, "pregame": pregame}
        deps = {
            "poll": lambda: {"in_play": 1},
            "capture": mock_capture,
            "record": lambda candidate: {**candidate, "recorded_utc": "test"},
            "registry_status": {"nfl_favorite_trails_halftime": "registered"},
        }
        clock = FakeClock(start_utc=observed)

        with mock.patch("src.pipeline.livefeed_nfl.latest_states") as m_states:
            # Identical state to state["prev_states"] -- nothing "changed".
            m_states.return_value = {"nfl1": nfl_state}
            with mock.patch("src.pipeline.live_odds.read_inplay", return_value=[]):
                with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                    m_quote.return_value = self._quote(observed.isoformat(), observed.isoformat())
                    result = live_window.tick("nfl", state=state, clock=clock, deps=deps)

        self.assertEqual(result["changed"], 1)
        self.assertEqual(len(capture_calls), 1)


class TestWindowEvidence(unittest.TestCase):
    """R16 window-evidence artifact: the fix for the 2026-09-16 defect
    (run 35136716193: 511 ticks, `candidates_new: 0`, no record of what was
    evaluated). Proves each failure mode is legible and distinguishable, per
    the task's acceptance criteria -- these tests fail against the
    pre-fix `tick`/`run` (no `state["evidence"]`, no `build_window_evidence`
    at all)."""

    PREGAME = {
        "pk1": {
            "sport": "mlb",
            "game_id": "pk1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "favorite": "home",
            "favorite_prob": 0.6,
            "starter_ids": {"home": 1, "away": 2},
            "event_id": "evt1",
        }
    }

    TRIGGERING_STATE = {
        "status": "Live", "home_runs": 2, "away_runs": 3,
        "inning": 3, "inning_state": "End",
        "observed_utc": "2026-09-14T20:00:00Z",
    }

    def _quote(self, observed_utc, last_update, n_books=3):
        return {
            "observed_utc": observed_utc,
            "quotes": [
                {"book": f"book{i}", "home_price": -110 - i, "away_price": 100 + i,
                 "last_update": last_update}
                for i in range(n_books)
            ],
        }

    def _make_state(self):
        return {"date": "2026-09-14", "prev_states": {}, "pregame": self.PREGAME}

    def _deps(self, capture_fn, registry_status=None):
        return {
            "poll": lambda: {"live_games": 1, "rows_written": 1},
            "capture": capture_fn,
            "record": lambda candidate: {**candidate, "recorded_utc": "test"},
            "registry_status": registry_status or {
                "mlb_favorite_trails_after_3": "registered",
                "mlb_starter_pulled_early": "unregistered",
            },
        }

    def test_state_condition_met_but_price_gate_refused(self):
        """The trigger's state condition holds (favourite trails by 2 after
        the 3rd) but every capture attempt sees fewer than
        `live_rules.MIN_FRESH_BOOKS` fresh books -- the artifact must say
        the price gate refused, distinct from the state never having been
        met, and must name the actual fresh-book count it saw."""
        from src.analysis import live_rules
        from src.pipeline import live_window

        def mock_capture(*args, **kwargs):
            return {"captured": 2}

        clock = FakeClock(start_utc=datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc))
        state = self._make_state()
        deps = self._deps(mock_capture)

        # Never enough fresh books at any retry offset (0, 45, 90).
        quote_2_books = self._quote("2026-09-14T20:00:00Z", "2026-09-14T20:00:00Z", n_books=2)

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": self.TRIGGERING_STATE}
            with mock.patch("src.pipeline.live_odds.read_inplay", return_value=[]):
                with mock.patch("src.pipeline.live_odds.latest_inplay_quote",
                                return_value=quote_2_books):
                    live_window.tick("mlb", state=state, clock=clock, deps=deps)
                    clock.sleep(45)
                    live_window.tick("mlb", state=state, clock=clock, deps=deps)
                    clock.sleep(45)  # T0 + 90s: ladder exhausted after this
                    live_window.tick("mlb", state=state, clock=clock, deps=deps)

        artifact = live_window.build_window_evidence(
            "mlb", date="2026-09-14", ticks=3,
            window_start_utc="2026-09-14T20:00:00Z",
            window_end_utc="2026-09-14T20:01:30Z",
            evidence=state["evidence"], trigger_state=state["trigger_state"],
            stopped_reason="max_minutes (5) elapsed")

        rule_ev = artifact["games"]["pk1"]["rules"]["mlb_favorite_trails_after_3"]
        self.assertEqual(rule_ev["outcome"], "state_condition_met_price_refused")
        self.assertEqual(rule_ev["last_fresh_count"], 2)
        self.assertEqual(rule_ev["min_fresh_books_required"], live_rules.MIN_FRESH_BOOKS)
        self.assertNotIn("closest_miss", rule_ev)  # this is a fired-trigger row, not a miss

    def test_nothing_close_writes_closest_miss_with_actual_values(self):
        """When a rule's condition never comes close to firing, the artifact
        still names the closest the state got, with real observed values --
        never a bare zero and never a placeholder."""
        from src.pipeline import live_window

        far_state = {
            "status": "Live", "home_runs": 0, "away_runs": 0,
            "inning": 1, "inning_state": "Top",
            "observed_utc": "2026-09-14T19:10:00Z",
        }

        def mock_capture(*args, **kwargs):
            return {"captured": 0}

        state = self._make_state()
        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": far_state}
            live_window.tick("mlb", state=state, deps=self._deps(mock_capture))

        artifact = live_window.build_window_evidence(
            "mlb", date="2026-09-14", ticks=1,
            window_start_utc="2026-09-14T19:10:00Z",
            window_end_utc="2026-09-14T19:10:20Z",
            evidence=state["evidence"], trigger_state=state.get("trigger_state", {}),
            stopped_reason="no live games and nothing starts within 30 minutes")

        rule_ev = artifact["games"]["pk1"]["rules"]["mlb_favorite_trails_after_3"]
        self.assertEqual(rule_ev["outcome"], "state_condition_not_met")
        miss = rule_ev["closest_miss"]
        self.assertIsNotNone(miss)
        self.assertFalse(miss["condition_met"])
        self.assertEqual(miss["values"]["inning"], 1)
        self.assertEqual(miss["values"]["margin"], 0)
        self.assertEqual(miss["values"]["observed_utc"], "2026-09-14T19:10:00Z")

    def test_unregistered_rule_distinguished_from_rule_that_did_not_fire(self):
        """Two rules for the same game/tick: one registered whose condition
        never holds, one simply not registered. The artifact must not
        conflate them -- an unregistered rule was never even checked."""
        from src.pipeline import live_window

        def mock_capture(*args, **kwargs):
            return {"captured": 0}

        state = self._make_state()
        deps = self._deps(mock_capture, registry_status={
            "mlb_favorite_trails_after_3": "registered",
            "mlb_starter_pulled_early": "unregistered",
        })

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {
                "status": "Live", "home_runs": 0, "away_runs": 0,
                "inning": 1, "inning_state": "Top",
                "observed_utc": "2026-09-14T19:10:00Z",
            }}
            live_window.tick("mlb", state=state, deps=deps)

        artifact = live_window.build_window_evidence(
            "mlb", date="2026-09-14", ticks=1,
            window_start_utc="2026-09-14T19:10:00Z",
            window_end_utc="2026-09-14T19:10:20Z",
            evidence=state["evidence"], trigger_state=state.get("trigger_state", {}),
            stopped_reason="no live games and nothing starts within 30 minutes")

        rules = artifact["games"]["pk1"]["rules"]
        self.assertEqual(rules["mlb_favorite_trails_after_3"]["outcome"], "state_condition_not_met")
        self.assertEqual(rules["mlb_starter_pulled_early"]["outcome"], "unregistered")
        self.assertNotIn("closest_miss", rules["mlb_starter_pulled_early"])

    def test_record_window_evidence_writes_jsonl(self):
        """record_window_evidence appends one JSON line per call, same
        append-only store convention as record_window_gaps."""
        from src.pipeline import live_window

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_evidence.jsonl"
            artifact = {"kind": "WINDOW_EVIDENCE", "sport": "mlb", "ticks": 5}
            ok1 = live_window.record_window_evidence("mlb", artifact, path=path)
            ok2 = live_window.record_window_evidence("mlb", artifact, path=path)

            self.assertTrue(ok1)
            self.assertTrue(ok2)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["kind"], "WINDOW_EVIDENCE")

    def test_priced_candidate_outcome_distinct_from_price_refused(self):
        """A trigger that DOES price is a third, distinct outcome from
        both the refused-price and never-met cases above."""
        from src.pipeline import live_window

        def mock_capture(*args, **kwargs):
            return {"captured": 3}

        clock = FakeClock(start_utc=datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc))
        state = self._make_state()

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": self.TRIGGERING_STATE}
            with mock.patch("src.pipeline.live_odds.read_inplay", return_value=[]):
                with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                    m_quote.return_value = self._quote(
                        "2026-09-14T20:00:00Z", "2026-09-14T20:00:00Z")
                    live_window.tick("mlb", state=state, clock=clock, deps=self._deps(mock_capture))

        artifact = live_window.build_window_evidence(
            "mlb", date="2026-09-14", ticks=1,
            window_start_utc="2026-09-14T20:00:00Z",
            window_end_utc="2026-09-14T20:00:20Z",
            evidence=state["evidence"], trigger_state=state["trigger_state"],
            stopped_reason="max_minutes (5) elapsed")

        rule_ev = artifact["games"]["pk1"]["rules"]["mlb_favorite_trails_after_3"]
        self.assertEqual(rule_ev["outcome"], "priced_candidate_recorded")


class TestD12StarterObservedOverwrite(unittest.TestCase):
    """docs/LIVE_BETTING_SYSTEM.md D12: `live_rules._mlb_starter_pulled_early`
    must compare against the pitcher actually observed on defence, not the
    pregame probable, once a real one has been seen. Fails against the
    pre-fix `tick`, which never performed this overwrite (the docstring's
    own words: 'live_window.tick never does that')."""

    def _deps(self, capture_fn):
        return {
            "poll": lambda: {"live_games": 1, "rows_written": 1},
            "capture": capture_fn,
            "record": lambda candidate: {**candidate, "recorded_utc": "test"},
            "registry_status": {
                "mlb_favorite_trails_after_3": "unregistered",
                "mlb_starter_pulled_early": "registered",
            },
        }

    def test_first_observed_defensive_pitcher_overwrites_probable(self):
        """An opener (observed pitcher != probable) on the very first
        defensive row must NOT be mistaken for a mid-game pull -- the
        probable is overwritten with the observed id before evaluation, so
        the rule compares against reality, not the pregame guess."""
        from src.pipeline import live_window

        pregame = {
            "pk1": {
                "sport": "mlb", "game_id": "pk1",
                "home_team": "BOS", "away_team": "NYY",
                "favorite": "home", "favorite_prob": 0.6,
                # Probable pitcher (id 111) turns out NOT to be who actually
                # takes the mound (an opener, id 999) -- D12's exact scenario.
                "starter_ids": {"home": 111, "away": 2},
                "event_id": "evt1",
            }
        }
        state = {"date": "2026-09-14", "prev_states": {}, "pregame": pregame}
        capture_calls = []

        def mock_capture(*args, **kwargs):
            capture_calls.append(kwargs.get("reason"))
            return {"captured": 0}

        # Home favourite on defence = top half. The opener (999) is the
        # first pitcher ever observed there -- must become the "starter"
        # for D12 purposes, not trigger a false "starter pulled".
        opener_row = {
            "status": "Live", "half": "top", "inning": 1,
            "pitcher_id": 999, "home_runs": 0, "away_runs": 0,
            "observed_utc": "2026-09-14T19:05:00Z",
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": opener_row}
            live_window.tick("mlb", state=state, deps=self._deps(mock_capture))

        self.assertEqual(pregame["pk1"]["starter_ids"]["home"], 999)
        self.assertEqual(capture_calls, [])  # no false "starter pulled" trigger

        # A REAL pull two innings later, still <= 4, favourite still ahead:
        # now it must fire, compared against the OBSERVED starter (999).
        pulled_row = {
            "status": "Live", "half": "top", "inning": 3,
            "pitcher_id": 777, "home_runs": 2, "away_runs": 0,
            "observed_utc": "2026-09-14T19:35:00Z",
        }
        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": pulled_row}
            result = live_window.tick("mlb", state=state, deps=self._deps(mock_capture))

        self.assertEqual(result["changed"], 1)  # trigger now registered
        self.assertEqual(pregame["pk1"]["starter_ids"]["home"], 999)  # unchanged


class TestShouldDispatch(unittest.TestCase):
    """Tests for should_dispatch."""

    def test_should_dispatch_live_game_mlb(self):
        """should_dispatch returns True when a game's start has passed and
        game_state() is neither final nor cancelled (D8).

        Fixture shape is `mlb.parse_game()`'s own output (flat `state` field
        of "final"/"cancelled"/"pending" -- `game_state()` has no "live"
        value, see D8/`_mlb_live_or_soon`), never a hand-shaped raw-API dict.
        """
        now = datetime(2026, 9, 14, 21, 30, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "state": "pending",
            }
        ]

        def mock_schedule(date):
            return games

        # `running` is injected because the default reads the real `gh run
        # list`: without it these three tests pass or fail according to
        # whatever this account's Actions queue looks like at the moment they
        # run, which is how they came to fail on a machine with a live window
        # queued (2026-09-16).
        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertTrue(can_run)
        self.assertIn("live", reason)

    def test_should_dispatch_game_starts_soon(self):
        """should_dispatch returns True when a FUTURE start is within 30 minutes."""
        now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T20:20:00Z",
                "state": "pending",
            }
        ]

        def mock_schedule(date):
            return games

        # `running` is injected because the default reads the real `gh run
        # list`: without it these three tests pass or fail according to
        # whatever this account's Actions queue looks like at the moment they
        # run, which is how they came to fail on a machine with a live window
        # queued (2026-09-16).
        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertTrue(can_run)
        self.assertIn("within 30 minutes", reason)

    def test_should_dispatch_nothing_happening(self):
        """should_dispatch returns False when no games are live/starting soon."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "state": "pending",
            }
        ]

        def mock_schedule(date):
            return games

        # `running` is injected because the default reads the real `gh run
        # list`: without it these three tests pass or fail according to
        # whatever this account's Actions queue looks like at the moment they
        # run, which is how they came to fail on a machine with a live window
        # queued (2026-09-16).
        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertFalse(can_run)
        self.assertIn("nothing starts", reason)

    def test_should_dispatch_mlb_final_game_past_start_is_not_live(self):
        """D8 regression: a game whose start has passed but is already
        `final` must NOT be reported as live or dispatched on its account --
        the old code treated ANY past start time as "starting within 30
        minutes" and never asked whether the game was over."""
        now = datetime(2026, 9, 14, 23, 59, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T18:00:00Z",
                "state": "final",
            }
        ]

        def mock_schedule(date):
            return games

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertFalse(can_run)
        self.assertIn("nothing starts", reason)

    def test_should_dispatch_mlb_cancelled_game_past_start_is_not_live(self):
        """D8: same as above for a cancelled game."""
        now = datetime(2026, 9, 14, 23, 59, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T18:00:00Z",
                "state": "cancelled",
            }
        ]

        def mock_schedule(date):
            return games

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertFalse(can_run)

    def test_should_dispatch_nfl_outside_window(self):
        """should_dispatch returns False for NFL outside broadcast windows."""
        # Tuesday 10 AM ET
        now = datetime(2026, 9, 15, 14, 0, 0, tzinfo=timezone.utc)

        can_run, reason = live_window.should_dispatch("nfl", now=now)

        self.assertFalse(can_run)
        self.assertIn("outside", reason)

    def test_should_dispatch_already_running(self):
        """should_dispatch returns False when window is already running."""
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)

        def mock_running():
            return True

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, running=mock_running
        )

        self.assertFalse(can_run)
        self.assertIn("already running", reason)

    def test_should_dispatch_default_running_checks_gh_across_runners(self):
        """Default (no `running` override) consults gh, not just the local marker.

        Regression test for the bug where should_dispatch's default check
        only ever looked at a marker file local to the calling runner, so a
        different job (like forward-capture's chain) could never see a real
        window active elsewhere and redispatched every cycle.
        """
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "status": {"abstractGameState": "Live"},
            }
        ]

        with mock.patch.object(live_window, "_local_window_marker_active", return_value=False), \
             mock.patch.object(live_window, "_gh_run_active", return_value=True) as m_gh:
            can_run, reason = live_window.should_dispatch(
                "mlb", now=now, schedule=lambda date: games
            )

        m_gh.assert_called_once_with("mlb")
        self.assertFalse(can_run)
        self.assertIn("already running", reason)


class TestGhRunActive(unittest.TestCase):
    """Tests for _gh_run_active (the cross-runner 'already dispatched' check)."""

    def test_matching_sport_in_progress_is_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "in_progress", "displayTitle": "live-window-mlb"},
            ])

        self.assertTrue(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_no_matching_runs_is_not_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "completed", "displayTitle": "live-window-mlb"},
            ])

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_wrong_sport_prefix_is_not_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "in_progress", "displayTitle": "live-window-nfl"},
            ])

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_cancelled_run_is_not_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "completed", "displayTitle": "live-window-mlb", "conclusion": "cancelled"},
            ])

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_queued_run_is_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "queued", "displayTitle": "live-window-nfl"},
            ])

        self.assertTrue(live_window._gh_run_active("nfl", run_cli=fake_cli))

    def test_gh_error_fails_open_to_not_active(self):
        def fake_cli(workflow):
            raise RuntimeError("gh not found")

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_malformed_json_fails_open_to_not_active(self):
        def fake_cli(workflow):
            return "not json"

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))


class TestLocalWindowMarkerActive(unittest.TestCase):
    """Tests for _local_window_marker_active (the same-runner marker check)."""

    def test_no_marker_file_is_not_active(self):
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        with mock.patch.object(
            live_window, "data_path", return_value="/nonexistent/path/window.lock"
        ):
            self.assertFalse(live_window._local_window_marker_active("mlb", now))

    def test_unexpired_marker_is_active(self):
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "window.lock"
            marker.write_text((now + timedelta(minutes=10)).isoformat(), encoding="utf-8")
            with mock.patch.object(live_window, "data_path", return_value=str(marker)):
                self.assertTrue(live_window._local_window_marker_active("mlb", now))

    def test_expired_marker_is_not_active(self):
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "window.lock"
            marker.write_text((now - timedelta(minutes=10)).isoformat(), encoding="utf-8")
            with mock.patch.object(live_window, "data_path", return_value=str(marker)):
                self.assertFalse(live_window._local_window_marker_active("mlb", now))


class TestRun(unittest.TestCase):
    """Tests for run."""

    def test_run_stops_early_when_no_games_nearby(self):
        """run exits early when nothing is live and nothing starts within 30 min."""
        clock = FakeClock()

        def mock_poll():
            return {"live_games": 0, "rows_written": 0}

        def mock_schedule(date):
            return []

        deps = {
            "poll": mock_poll,
            # Never let a run() test reach the real data/live/ store --
            # every run() call now writes a window-evidence artifact.
            "record_window_evidence": lambda sport, artifact: True,
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = []
                result = live_window.run(
                    "mlb", max_minutes=330, clock=clock, sleep=clock.sleep, deps=deps
                )

        self.assertLessEqual(result["ticks"], 2)
        self.assertIn("nothing starts", result["stopped_reason"])

    def test_run_commits_at_interval(self):
        """run calls commit at the specified interval."""
        clock = FakeClock()
        commits = []

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_commit():
            commits.append(clock())

        deps = {"poll": mock_poll, "record_window_evidence": lambda sport, artifact: True}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live"}}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = [
                    {
                        "game_pk": "pk1",
                        "start_time_utc": "2026-09-14T21:00:00Z",
                        "status": {"abstractGameState": "Live"},
                    }
                ]
                result = live_window.run(
                    "mlb",
                    max_minutes=10,
                    clock=clock,
                    sleep=clock.sleep,
                    deps=deps,
                    commit=mock_commit,
                    commit_every_minutes=5,
                )

        # Should have at least one commit
        self.assertGreater(len(commits), 0)

    def test_run_respects_max_minutes(self):
        """run stops when max_minutes elapsed."""
        clock = FakeClock()

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        deps = {"poll": mock_poll, "record_window_evidence": lambda sport, artifact: True}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live"}}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = [
                    {
                        "game_pk": "pk1",
                        "start_time_utc": "2026-09-14T21:00:00Z",
                        "status": {"abstractGameState": "Live"},
                    }
                ]
                result = live_window.run(
                    "mlb",
                    max_minutes=5,
                    clock=clock,
                    sleep=clock.sleep,
                    deps=deps,
                )

        self.assertIn("max_minutes", result["stopped_reason"])


class TestWindowGaps(unittest.TestCase):
    """R16-L5 (3.2 "Window handoffs"): a live minute no window covers is
    recorded as a WINDOW_GAP, never silently skipped."""

    def test_gap_recorded_when_handoff_exceeds_tolerance(self):
        previous_last = {"pk1": "2026-09-14T20:00:00Z"}
        current_first = {"pk1": "2026-09-14T20:31:00Z"}  # ~31 min later
        gaps = live_window.compute_window_gaps(
            previous_last, current_first, poll_interval_s=20)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["kind"], "WINDOW_GAP")
        self.assertEqual(gaps[0]["game_id"], "pk1")
        self.assertEqual(gaps[0]["start_utc"], "2026-09-14T20:00:00Z")
        self.assertEqual(gaps[0]["end_utc"], "2026-09-14T20:31:00Z")
        self.assertAlmostEqual(gaps[0]["gap_seconds"], 1860, delta=1)

    def test_no_gap_within_tolerance(self):
        previous_last = {"pk1": "2026-09-14T20:00:00Z"}
        current_first = {"pk1": "2026-09-14T20:00:25Z"}  # 25s, under 1.5x20s=30s
        gaps = live_window.compute_window_gaps(
            previous_last, current_first, poll_interval_s=20)
        self.assertEqual(gaps, [])

    def test_no_gap_for_a_game_not_seen_before(self):
        """A game with no prior row (new to the slate) is never treated as
        a gap -- nothing was missed, it just started."""
        gaps = live_window.compute_window_gaps(
            {}, {"pk1": "2026-09-14T20:00:00Z"}, poll_interval_s=20)
        self.assertEqual(gaps, [])

    def test_record_window_gaps_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gaps.jsonl"
            gaps = [{"kind": "WINDOW_GAP", "game_id": "pk1",
                    "start_utc": "a", "end_utc": "b", "gap_seconds": 100,
                    "reason": "no live window covered this span"}]
            count = live_window.record_window_gaps("mlb", gaps, path=path)
            self.assertEqual(count, 1)
            lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["game_id"], "pk1")

    def test_record_window_gaps_no_gaps_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gaps.jsonl"
            count = live_window.record_window_gaps("mlb", [], path=path)
            self.assertEqual(count, 0)
            self.assertFalse(path.exists())

    def test_run_records_a_gap_left_by_a_prior_window(self):
        """End-to-end through run(): state already on disk from an earlier
        window (last row 40 minutes ago), this window's own first poll picks
        the game up now -- the gap between them must be recorded via the
        injected record_window_gaps, not silently dropped."""
        clock = FakeClock(start_utc=datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc))
        recorded = []

        def fake_record_window_gaps(sport, gaps):
            recorded.extend(gaps)
            return len(gaps)

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        deps = {"poll": mock_poll, "record_window_gaps": fake_record_window_gaps,
                "record_window_evidence": lambda sport, artifact: True}

        prior_row = {"pk1": {"status": "Live", "observed_utc": "2026-09-14T20:20:00Z"}}
        current_row = {"pk1": {"status": "Live", "observed_utc": "2026-09-14T21:00:00Z"}}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            # First call (before the loop) returns the PRIOR window's last
            # row; every call once the loop starts returns the current one.
            m_states.side_effect = [prior_row] + [current_row] * 10
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = []
                # A sub-poll-interval max_minutes so the loop runs exactly
                # one tick (one 20s sleep already exceeds it) -- deterministic,
                # no risk of an exact-equality hang at the max_minutes boundary.
                live_window.run(
                    "mlb", max_minutes=0.3, clock=clock, sleep=clock.sleep, deps=deps)

        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["game_id"], "pk1")
        self.assertEqual(recorded[0]["start_utc"], "2026-09-14T20:20:00Z")


class TestSettle(unittest.TestCase):
    """Tests for settle."""

    def test_settle_mlb_candidate_from_final(self):
        """settle grades an MLB candidate against a final state row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create live candidates ledger
            ledger_path = Path(tmpdir) / "live_candidates_v1.jsonl"
            candidate = {
                "kind": "live_candidate",
                "recorded_utc": "2026-09-14T20:00:00Z",
                "date": "2026-09-14",
                "rule_id": "mlb_favorite_trails_after_3",
                "sport": "mlb",
                "game_id": "747101",
                "side": "home",
                "team": "Boston Red Sox",
                "bet": "Boston Red Sox moneyline",
                "price": -110,
                "books": 5,
                "state_id": "abc123",
                "observed_utc": "2026-09-14T20:00:00Z",
                "trigger": {"inning": 3},
            }

            # Write candidate with chain fields
            row = candidate.copy()
            row["hash"] = "hash0"
            row["prior_hash"] = ""
            ledger_path.write_text(json.dumps(row) + "\n")

            # Settlement
            results = {
                "747101": {"home_score": 5, "away_score": 3}
            }

            with mock.patch("src.appstate.live_ledger.LIVE_STORE", str(ledger_path)):
                result = live_window.settle("2026-09-14", results=results)

            self.assertIsNotNone(result)
            self.assertGreater(result["graded"], 0)


class TestMain(unittest.TestCase):
    """Tests for main."""

    def test_main_should_dispatch_flag(self):
        """main with --should-dispatch prints DISPATCH or HOLD."""
        with mock.patch("src.pipeline.live_window.should_dispatch") as m_dispatch:
            m_dispatch.return_value = (True, "live game")
            with mock.patch("builtins.print") as m_print:
                live_window.main(["live_window.py", "--sport", "mlb", "--should-dispatch"])
                m_print.assert_called_once()
                call_arg = m_print.call_args[0][0]
                self.assertIn("DISPATCH", call_arg)

    def test_main_should_dispatch_false(self):
        """main prints HOLD when should_dispatch returns False."""
        with mock.patch("src.pipeline.live_window.should_dispatch") as m_dispatch:
            m_dispatch.return_value = (False, "outside window")
            with mock.patch("builtins.print") as m_print:
                live_window.main(["live_window.py", "--sport", "mlb", "--should-dispatch"])
                call_arg = m_print.call_args[0][0]
                self.assertIn("HOLD", call_arg)

    def test_main_settle_needs_no_sport(self):
        """The exact command scripts/daily_loop.sh runs: --settle --date, no --sport.

        It used to exit with an argparse error, so the live candidates would
        never have been graded.
        """
        with mock.patch("src.pipeline.live_window.settle", return_value=None) as m_settle:
            with mock.patch("builtins.print"):
                code = live_window.main(["live_window.py", "--settle", "--date", "2026-09-14"])
        self.assertEqual(code, 0)
        m_settle.assert_called_once_with("2026-09-14")

    def test_main_run_still_requires_sport(self):
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                live_window.main(["live_window.py", "--max-minutes", "5"])

    def test_daily_loop_calls_settle_the_way_main_accepts(self):
        """Tie the script to a settle entry point that actually accepts it.

        R16-L7 moved nightly settlement off this module: the loop now grades
        from AUTHORITATIVE finals via `src.appstate.live_ledger settle`, which
        walks yesterday plus any unsettled date in the last 7 days, so a
        missed night self-heals instead of leaving a permanent hole. This test
        keeps its original job -- the script and the code that serves it must
        not drift -- by pinning the invocation AND proving the module's own
        parser accepts that exact argv. `live_window --settle` above stays a
        working entry point; it is simply no longer what the loop runs.
        """
        from pathlib import Path

        from src.appstate import live_ledger

        script = (Path(__file__).resolve().parents[1] / "scripts" / "daily_loop.sh").read_text(
            encoding="utf-8")
        self.assertIn("python3 -m src.appstate.live_ledger settle", script)
        self.assertNotIn("src.pipeline.live_window --settle", script)

        with mock.patch.object(live_ledger, "settle_recent",
                               return_value={"graded": 0, "voids": 0,
                                             "unsettled": 0, "dates_checked": 1}):
            with mock.patch("builtins.print"):
                self.assertEqual(live_ledger._main(["settle"]), 0)


class TestCommitStagesOnlyLiveAndLedger(unittest.TestCase):
    """R16-L4/D7: the window's own commit must never touch
    data/processed/credit_log.jsonl -- that is the forward-capture chain's
    file, committed and pushed on its own ~13-minute cadence, and staging it
    here is the two-writer race D7 describes."""

    def test_commit_git_add_excludes_processed_credit_log(self):
        # The staged paths are the existence-filtered tuple (2026-09-19: a
        # literal two-path add refused everything whenever the candidates
        # ledger did not exist yet).
        source = Path(live_window.__file__).read_text(encoding="utf-8")
        self.assertIn('("data/live", "evidence/live_candidates_v1.jsonl")', source)
        self.assertIn('_git("add", *stage)', source)
        self.assertNotIn('"data/processed/credit_log.jsonl"', source)


@unittest.skipUnless(_GIT_AVAILABLE, "git is not available on this machine")
class TestPushPathNoCreditLogConflict(unittest.TestCase):
    """R16-L4/D7 acceptance: two runners, each appending to their OWN store
    (data/live/credit_log_live.jsonl for the window, data/processed/
    credit_log.jsonl for the forward-capture chain -- never the same file),
    pushing concurrently within one minute, both land with no rebase
    failure. Everything here runs against throwaway local (file://) git
    repos under a temp directory -- no network, so it runs in CI. It does
    not import live_window._commit (which is nested inside main() and reads
    real argv/os.environ) but replicates its exact git sequence: add,
    commit, `pull --rebase --autostash origin <branch>` with up to 3
    attempts, then push -- so a change to that sequence that reintroduces
    the D7 race would show up here too.
    """

    def _git(self, cwd, *argv, check=True):
        result = subprocess.run(
            ["git", *argv], cwd=str(cwd), capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError(
                f"git {' '.join(argv)} in {cwd} failed: {result.stderr}")
        return result

    def _push_with_rebase_retry(self, clone_dir, branch, errors):
        """Mirrors live_window.py main()._commit's own retry loop exactly."""
        for attempt in range(3):
            pulled = subprocess.run(
                ["git", "pull", "-q", "--rebase", "--autostash", "origin", branch],
                cwd=str(clone_dir), capture_output=True, text=True)
            if pulled.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], cwd=str(clone_dir),
                               capture_output=True, text=True)
                errors.append(f"rebase failed (attempt {attempt + 1}): "
                              f"{pulled.stderr.strip()}")
                continue
            pushed = subprocess.run(
                ["git", "push", "-q", "origin", branch],
                cwd=str(clone_dir), capture_output=True, text=True)
            if pushed.returncode == 0:
                return True
            errors.append(f"push failed (attempt {attempt + 1}): "
                          f"{pushed.stderr.strip()}")
        return False

    def test_two_clones_push_concurrently_within_one_minute_no_rebase_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            origin = tmp / "origin.git"
            clone_a = tmp / "clone_a"
            clone_b = tmp / "clone_b"

            self._git(tmp, "init", "--bare", "-b", "main", str(origin))

            # Seed origin with one commit so both clones start from the
            # same history (an empty bare repo has no branch to clone).
            seed = tmp / "seed"
            self._git(tmp, "clone", "-q", str(origin), str(seed))
            self._git(seed, "config", "user.email", "test@example.com")
            self._git(seed, "config", "user.name", "test")
            (seed / "data").mkdir()
            (seed / "data" / "live").mkdir()
            (seed / "data" / "live" / ".gitkeep").write_text("", encoding="utf-8")
            self._git(seed, "add", "-A")
            self._git(seed, "commit", "-q", "-m", "seed")
            self._git(seed, "push", "-q", "origin", "main")

            for name, clone_dir in (("a", clone_a), ("b", clone_b)):
                self._git(tmp, "clone", "-q", str(origin), str(clone_dir))
                self._git(clone_dir, "config", "user.email", "test@example.com")
                self._git(clone_dir, "config", "user.name", "test")

            # Each runner writes to its OWN file -- data/live/credit_log_live.jsonl
            # for the window (clone_a) and data/processed/credit_log.jsonl for the
            # forward-capture chain (clone_b) -- exactly the D7 fix: never the
            # same path, so a genuine three-way merge (both sides adding at the
            # end of the SAME file) can never happen here even under a race.
            (clone_a / "data" / "live").mkdir(parents=True, exist_ok=True)
            (clone_a / "data" / "live" / "credit_log_live.jsonl").write_text(
                json.dumps({"utc": "2026-09-16T00:00:00Z", "caller": "window"}) + "\n",
                encoding="utf-8")
            self._git(clone_a, "add", "data/live/credit_log_live.jsonl")
            self._git(clone_a, "commit", "-q", "-m", "Live window mlb 00:00Z (external)")

            (clone_b / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (clone_b / "data" / "processed" / "credit_log.jsonl").write_text(
                json.dumps({"utc": "2026-09-16T00:00:05Z", "caller": "chain"}) + "\n",
                encoding="utf-8")
            self._git(clone_b, "add", "data/processed/credit_log.jsonl")
            self._git(clone_b, "commit", "-q", "-m", "forward-capture chain")

            errors_a, errors_b = [], []
            start = time.monotonic()
            thread_a = threading.Thread(
                target=self._push_with_rebase_retry,
                args=(clone_a, "main", errors_a))
            thread_b = threading.Thread(
                target=self._push_with_rebase_retry,
                args=(clone_b, "main", errors_b))
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=60)
            thread_b.join(timeout=60)
            elapsed = time.monotonic() - start

            self.assertLess(elapsed, 60,
                            "both pushes must land within one minute")
            self.assertFalse(thread_a.is_alive(), "clone_a push did not finish")
            self.assertFalse(thread_b.is_alive(), "clone_b push did not finish")
            rebase_failures = [e for e in errors_a + errors_b if "rebase failed" in e]
            self.assertEqual(rebase_failures, [],
                             f"a rebase failed under the race: {rebase_failures}")

            # Both commits landed on the remote.
            log = self._git(origin, "log", "--oneline", "main").stdout
            self.assertIn("Live window mlb 00:00Z (external)", log)
            self.assertIn("forward-capture chain", log)
            check = self._git(seed, "fetch", "-q", "origin", "main")
            checkout = self._git(seed, "checkout", "-q", "origin/main", "--",
                                 "data/live/credit_log_live.jsonl",
                                 "data/processed/credit_log.jsonl")
            self.assertTrue((seed / "data" / "live" / "credit_log_live.jsonl").exists())
            self.assertTrue((seed / "data" / "processed" / "credit_log.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
