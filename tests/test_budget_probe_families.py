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
        # provider.fetch_odds() (used by the tennis_h2h probe) hits
        # /sports/{sport}/odds, which returns every event for that sport as
        # a LIST -- not the single-event dict fetch_event_odds_with_usage()
        # returns. The default here must match that real shape (2026-09-15:
        # a dict default here hid the 'list' object has no attribute 'get'
        # crash that only showed up against the real API in production).
        self.odds_payload = odds_payload if odds_payload is not None else [
            {
                "id": "event1",
                "bookmakers": [
                    {"key": "book_a", "markets": [{"key": "h2h", "outcomes": [{"name": "x", "price": 100}]}]},
                    {"key": "book_b", "markets": [{"key": "h2h", "outcomes": [{"name": "y", "price": 100}]}]},
                ],
            },
        ]
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


class ProbeMmaH2hTests(unittest.TestCase):
    """2026-09-21: without its own branch, a probe of mma_h2h fell through to
    the default path, which lists MLB events, and measured an MLB game."""

    def test_probe_mma_h2h_fetches_the_mma_sport_key_not_an_mlb_event(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_families(folder, {"mma_h2h": {
                "measured": False, "credits_per_event": None, "measured_utc": None}})
            store = Path(folder) / "credit_log.jsonl"
            provider = _FakeSportsProvider(remaining_before=9000, billed=1,
                                           remaining_after=8999, sports=[])
            result = budget.probe_family(
                "mma_h2h", provider=provider, now=NOW, families_path=path, store=store)
            calls_by_name = {c[0]: c for c in provider.calls}
            self.assertIn("fetch_odds", calls_by_name)
            self.assertEqual(calls_by_name["fetch_odds"][1]["sport"], "mma_mixed_martial_arts")
            self.assertEqual(calls_by_name["fetch_odds"][1]["markets"], ["h2h"])
            self.assertNotIn("list_events", calls_by_name)
            self.assertEqual(result["sport_key"], "mma_mixed_martial_arts")


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

    def test_probe_tennis_h2h_aggregates_shape_across_the_event_list(self):
        """2026-09-15 crash: fetch_odds() returns a LIST of events, each with
        its own bookmakers -- _payload_shape must aggregate across the list
        (max book depth, union of markets, summed outcomes), not assume a
        single-event dict."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            odds_payload = [
                {
                    "id": "event1",
                    "bookmakers": [
                        {"key": "book_a", "markets": [
                            {"key": "h2h", "outcomes": [{"name": "x"}, {"name": "y"}]}]},
                    ],
                },
                {
                    "id": "event2",
                    "bookmakers": [
                        {"key": "book_a", "markets": [
                            {"key": "h2h", "outcomes": [{"name": "x"}, {"name": "y"}]}]},
                        {"key": "book_b", "markets": [
                            {"key": "h2h", "outcomes": [{"name": "x"}, {"name": "y"}]}]},
                    ],
                },
            ]
            provider = _FakeSportsProvider(sports=[{"key": "tennis_wta"}],
                                          odds_payload=odds_payload)
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            shape = result["payload_shape"]
            self.assertEqual(shape["event_count"], 2)
            self.assertEqual(shape["books"], 2)  # deepest single event, not summed
            self.assertEqual(shape["markets_returned"], 1)  # {"h2h"}
            self.assertEqual(shape["outcomes"], 6)  # 2 + 2 + 2 across every book
            self.assertFalse(shape["degenerate"])  # 2 books, 1 market >= min(2, 1)

    def test_probe_tennis_h2h_degenerate_when_the_event_list_is_empty(self):
        """No upcoming tennis events must not crash -- it is a thin, degenerate
        measurement, same treatment as any other empty/thin probe payload."""
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            store = Path(folder) / "credit_log.jsonl"
            provider = _FakeSportsProvider(sports=[{"key": "tennis_wta"}], odds_payload=[])
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path, store=store)
            self.assertTrue(result["probed"])
            self.assertTrue(result["degenerate"])
            self.assertEqual(result["payload_shape"]["event_count"], 0)
            # Still recorded as measured -- the fetch happened and cost a credit.
            recorded = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(recorded["families"]["tennis_h2h"]["measured"])


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


class TennisProbeDeadlock20260916Tests(unittest.TestCase):
    """2026-09-16: the tennis_h2h probe took the first tennis key from the
    FULL sports list -- the out-of-season Australian Open -- got an empty
    payload, and recorded `measured: true, degenerate: true`. can_spend
    treats degenerate as unmeasured (PROBE_REQUIRED), while daily_loop.sh's
    re-probe gate only looked at `measured`, so it never probed again and
    tennis capture stayed refused from then on."""

    def test_probe_skips_a_tennis_key_marked_inactive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_families(folder, {"tennis_h2h": {
                "measured": False, "credits_per_event": None, "measured_utc": None}})
            sports = [
                {"key": "tennis_atp_aus_open_singles", "title": "ATP Australian Open",
                 "active": False},
                {"key": "tennis_wta_singapore_open", "title": "WTA Singapore Open",
                 "active": True},
            ]
            provider = _FakeSportsProvider(sports=sports, billed=1)
            result = budget.probe_family(
                "tennis_h2h", provider=provider, now=NOW, families_path=path,
                store=Path(folder) / "credit_log.jsonl")
            self.assertEqual(result["sport_key"], "tennis_wta_singapore_open")

    def _daily_loop_gate_says_probe(self, entry):
        """Run daily_loop.sh's own re-probe gate (its `python3 -c` line,
        with $family substituted) against a config holding `entry`.
        Exit 0 means "probe it"."""
        import subprocess
        import sys
        repo = Path(__file__).resolve().parents[1]
        text = (repo / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
        block = text[text.index("== probe unmeasured capture families =="):]
        line = next(l for l in block.splitlines()
                    if "python3 -c" in l and "capture_families.json" in l)
        code = line.split('python3 -c "', 1)[1].rsplit('"', 1)[0]
        code = code.replace("$family", "tennis_h2h")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "config").mkdir()
            (Path(folder) / "config" / "capture_families.json").write_text(
                json.dumps({"families": {"tennis_h2h": entry}}), encoding="utf-8")
            done = subprocess.run([sys.executable, "-c", code], cwd=folder,
                                  capture_output=True, text=True, timeout=30)
        return done.returncode == 0

    def test_daily_loop_reprobes_a_degenerate_measurement(self):
        self.assertTrue(self._daily_loop_gate_says_probe(
            {"measured": True, "credits_per_event": 0, "degenerate": True}))

    def test_daily_loop_leaves_a_good_measurement_alone(self):
        self.assertFalse(self._daily_loop_gate_says_probe(
            {"measured": True, "credits_per_event": 1, "degenerate": False}))

    def test_daily_loop_probes_an_unmeasured_family(self):
        self.assertTrue(self._daily_loop_gate_says_probe(
            {"measured": False, "credits_per_event": None}))


if __name__ == "__main__":
    unittest.main()
