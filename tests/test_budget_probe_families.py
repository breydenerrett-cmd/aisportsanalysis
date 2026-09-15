"""Tests for probe_family with new families: scores and tennis_h2h (task 0.9).

Verifies that probe_family can measure the "scores" and "tennis_h2h" families,
using special fetch paths instead of event odds fetches.
"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.capture import budget
from src.pipeline import creditlog

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def _write_families(folder, families):
    """Write a tempfile capture_families.json with the given families dict."""
    path = Path(folder) / "capture_families.json"
    path.write_text(json.dumps({"families": families}), encoding="utf-8")
    return path


class _FakeSportsProvider:
    """Minimal odds_provider stand-in for probe_family with scores/tennis support."""

    class OddsProviderError(RuntimeError):
        pass

    def __init__(self, remaining_before=53000, billed=1, remaining_after=None,
                 scores_payload=None, odds_payload=None, sports=None,
                 fail_fetch=None, configured=True):
        self.remaining_before = remaining_before
        self.billed = billed
        self.remaining_after = (remaining_after if remaining_after is not None
                                else remaining_before - billed)
        self.scores_payload = scores_payload or [
            {"id": "score1", "completed": True, "home_team": "NFL_A", "away_team": "NFL_B"},
            {"id": "score2", "completed": False, "home_team": "NFL_C", "away_team": "NFL_D"},
        ]
        self.odds_payload = odds_payload or {
            "id": "event1",
            "bookmakers": [
                {"key": "book_a", "markets": [{"key": "h2h", "outcomes": [{"name": "x", "price": 100}]}]},
                {"key": "book_b", "markets": [{"key": "h2h", "outcomes": [{"name": "y", "price": 100}]}]},
            ]
        }
        self.sports = sports if sports is not None else [
            {"key": "tennis_wta", "title": "WTA"},
            {"key": "tennis_atp", "title": "ATP"},
        ]
        self.fail_fetch = fail_fetch
        self.configured = configured
        self.calls = []
        self.quota_calls_count = 0  # Track quota calls to return different values

    def status(self, env=None):
        return {"configured": self.configured}

    def quota(self, env=None):
        self.quota_calls_count += 1
        # First call returns remaining_before; subsequent calls return remaining_after
        remaining = self.remaining_before if self.quota_calls_count == 1 else self.remaining_after
        return {"remaining": remaining, "last": self.billed}

    def fetch_scores(self, *, sport=None, env=None, **kwargs):
        self.calls.append(("fetch_scores", {"sport": sport}))
        if self.fail_fetch:
            raise self.OddsProviderError(self.fail_fetch)
        return self.scores_payload

    def fetch_odds(self, markets=None, region=None, env=None, sport=None, **kwargs):
        self.calls.append(("fetch_odds", {"markets": markets, "sport": sport}))
        if self.fail_fetch:
            raise self.OddsProviderError(self.fail_fetch)
        return self.odds_payload

    def fetch_sports(self, *, all_sports=False, env=None, **kwargs):
        self.calls.append(("fetch_sports", {"all_sports": all_sports}))
        return self.sports


class ProbeScoresTests(unittest.TestCase):
    def _families(self, folder, extra=None):
        families = {"scores": {"measured": False, "credits_per_event": None,
                               "measured_utc": None}}
        if extra:
            families.update(extra)
        return _write_families(folder, families)

    def test_probe_scores_measures_and_records_credit_delta(self):
        """Probing 'scores' calls fetch_scores and records the measurement."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            provider = _FakeSportsProvider(remaining_before=53000, billed=1,
                                          remaining_after=52999)
            result = budget.probe_family(
                "scores", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            self.assertEqual(result["credits_per_event"], 1)
            # Verify fetch_scores was called with sport="nfl"
            calls_by_name = {c[0]: c for c in provider.calls}
            self.assertIn("fetch_scores", calls_by_name)
            self.assertEqual(calls_by_name["fetch_scores"][1]["sport"], "nfl")
            # Verify config was updated
            recorded = json.loads(path.read_text(encoding="utf-8"))
            entry = recorded["families"]["scores"]
            self.assertTrue(entry["measured"])
            self.assertEqual(entry["credits_per_event"], 1)
            # Verify credit log has one row
            log_rows = creditlog.read(store)
            self.assertEqual(len(log_rows), 1)
            self.assertEqual(log_rows[0]["credits_remaining"], 52999)
            self.assertEqual(log_rows[0]["credits_used_last"], 1)

    def test_probe_scores_payload_shape_records_event_counts(self):
        """The payload shape for scores records event_count and completed_count."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            payload = [
                {"id": "g1", "completed": True},
                {"id": "g2", "completed": False},
                {"id": "g3", "completed": True},
            ]
            provider = _FakeSportsProvider(scores_payload=payload, billed=1)
            result = budget.probe_family(
                "scores", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            shape = result["payload_shape"]
            self.assertEqual(shape["event_count"], 3)
            self.assertEqual(shape["completed_count"], 2)

    def test_probe_scores_degenerate_when_fewer_than_2_events(self):
        """A scores payload with fewer than 2 events is marked degenerate."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            payload = [{"id": "g1", "completed": True}]
            provider = _FakeSportsProvider(scores_payload=payload, billed=1)
            result = budget.probe_family(
                "scores", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            self.assertTrue(result["degenerate"])
            self.assertEqual(result["payload_shape"]["event_count"], 1)

    def test_probe_scores_non_degenerate_with_2_or_more_events(self):
        """A scores payload with 2+ events is non-degenerate."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            payload = [
                {"id": "g1", "completed": True},
                {"id": "g2", "completed": False},
            ]
            provider = _FakeSportsProvider(scores_payload=payload, billed=1)
            result = budget.probe_family(
                "scores", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            self.assertFalse(result["degenerate"])


class ProbeTennisH2hTests(unittest.TestCase):
    def _families(self, folder, extra=None):
        families = {"tennis_h2h": {"measured": False, "credits_per_event": None,
                                   "measured_utc": None}}
        if extra:
            families.update(extra)
        return _write_families(folder, families)

    def test_probe_tennis_h2h_measures_and_records_credit_delta(self):
        """Probing 'tennis_h2h' fetches sports, finds tennis key, and calls fetch_odds."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            sports = [
                {"key": "mlb", "title": "MLB"},
                {"key": "tennis_wta", "title": "WTA"},
                {"key": "tennis_atp", "title": "ATP"},
            ]
            provider = _FakeSportsProvider(remaining_before=53000, billed=1,
                                          remaining_after=52999, sports=sports)
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            self.assertEqual(result["credits_per_event"], 1)
            # Verify fetch_sports was called to find tennis key
            calls_by_name = {c[0]: c for c in provider.calls}
            self.assertIn("fetch_sports", calls_by_name)
            # Verify fetch_odds was called with the tennis key and markets=["h2h"]
            self.assertIn("fetch_odds", calls_by_name)
            fetch_odds_call = calls_by_name["fetch_odds"]
            self.assertEqual(fetch_odds_call[1]["markets"], ["h2h"])
            self.assertEqual(fetch_odds_call[1]["sport"], "tennis_wta")  # First tennis key
            # Verify result carries the sport_key
            self.assertEqual(result["sport_key"], "tennis_wta")
            # Verify config was updated
            recorded = json.loads(path.read_text(encoding="utf-8"))
            entry = recorded["families"]["tennis_h2h"]
            self.assertTrue(entry["measured"])
            self.assertEqual(entry["credits_per_event"], 1)
            # Verify credit log has one row
            log_rows = creditlog.read(store)
            self.assertEqual(len(log_rows), 1)

    def test_probe_tennis_h2h_finds_first_active_tennis_key(self):
        """When multiple tennis keys are available, the first one is used."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            sports = [
                {"key": "tennis_atp", "title": "ATP"},
                {"key": "tennis_wta", "title": "WTA"},
                {"key": "tennis_itf", "title": "ITF"},
            ]
            provider = _FakeSportsProvider(sports=sports, billed=1)
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            # First tennis key should be tennis_atp
            self.assertEqual(result["sport_key"], "tennis_atp")
            calls_by_name = {c[0]: c for c in provider.calls}
            fetch_odds_call = calls_by_name["fetch_odds"]
            self.assertEqual(fetch_odds_call[1]["sport"], "tennis_atp")

    def test_probe_tennis_h2h_refused_when_no_active_tennis_key(self):
        """When no tennis key is found, probe is refused with a clear error."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            sports = [
                {"key": "mlb", "title": "MLB"},
                {"key": "nfl", "title": "NFL"},
            ]
            provider = _FakeSportsProvider(sports=sports, billed=1)
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path, store=store)
            self.assertFalse(result["probed"])
            self.assertIn("no active tennis market found", result["error"])
            # Verify nothing was recorded in config
            recorded = json.loads(path.read_text(encoding="utf-8"))
            entry = recorded["families"]["tennis_h2h"]
            self.assertFalse(entry["measured"])
            # Verify no credit log rows were created
            log_rows = creditlog.read(store)
            self.assertEqual(len(log_rows), 0)

    def test_probe_tennis_h2h_calculates_billed_from_quota_delta(self):
        """Tennis h2h probe estimates billed credits from quota change."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            sports = [{"key": "tennis_wta", "title": "WTA"}]
            provider = _FakeSportsProvider(remaining_before=50000, remaining_after=49997,
                                          sports=sports, billed=None)  # No explicit billed
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            # Billed should be calculated as 50000 - 49997 = 3
            self.assertEqual(result["credits_per_event"], 3)


class RealConfigFileUnchangedTests(unittest.TestCase):
    def test_real_config_file_unchanged_after_temp_probe(self):
        """The real config/capture_families.json is not modified by temp store probes."""
        with tempfile.TemporaryDirectory() as folder:
            # Use temp config
            path = _write_families(folder, {
                "scores": {"measured": False, "credits_per_event": None,
                          "measured_utc": None}})
            store = Path(folder) / "credit_log.jsonl"
            original_mtime = Path(budget.FAMILIES_CONFIG_PATH).stat().st_mtime
            original_content = Path(budget.FAMILIES_CONFIG_PATH).read_text()

            provider = _FakeSportsProvider(billed=1)
            # Probe with temp config
            result = budget.probe_family(
                "scores", provider=provider, now=NOW,
                families_path=path, store=store)
            self.assertTrue(result["probed"])

            # Verify real config is untouched
            new_mtime = Path(budget.FAMILIES_CONFIG_PATH).stat().st_mtime
            new_content = Path(budget.FAMILIES_CONFIG_PATH).read_text()
            self.assertEqual(original_mtime, new_mtime)
            self.assertEqual(original_content, new_content)
            # Verify temp config was updated
            recorded = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(recorded["families"]["scores"]["measured"])


if __name__ == "__main__":
    unittest.main()
