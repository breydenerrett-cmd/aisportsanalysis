"""Tests for src/pipeline/derivative_markets.py. Hermetic: the provider is a
stand-in that never touches a network or a key, matching test_batter_props.py's
pattern."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.capture import budget
from src.pipeline import derivative_markets
from src.providers import odds
from tests import HERMETIC_CREDIT_LOG_STORE

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)

# Default fixture commence time sits exactly at the T-3h boundary (180
# minutes out) so a plain _event("g1") is due for a fetch under the new
# slot-gated plan without every test having to reason about timing.
T3H = NOW + dt.timedelta(hours=3)
T30M = NOW + dt.timedelta(minutes=30)


def _event(identifier, commence=T3H, home="Atlanta Braves", away="San Francisco Giants"):
    return {"id": identifier,
            "commence_time": commence.isoformat().replace("+00:00", "Z"),
            "home_team": home, "away_team": away}


def _team_totals_payload(identifier, books=("draftkings", "fanduel"),
                          last_update="2026-09-03T11:00:00Z"):
    """team_totals: outcomes are Over/Under, scoped to a team via `description`."""
    return {
        "id": identifier, "commence_time": "2026-09-03T23:00:00Z",
        "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
        "bookmakers": [{
            "key": book,
            "markets": [{
                "key": "team_totals",
                "last_update": last_update,
                "outcomes": [
                    {"name": "Over", "description": "Atlanta Braves",
                     "price": -110, "point": 4.5},
                    {"name": "Under", "description": "Atlanta Braves",
                     "price": -110, "point": 4.5},
                    {"name": "Over", "description": "San Francisco Giants",
                     "price": -115, "point": 3.5},
                    {"name": "Under", "description": "San Francisco Giants",
                     "price": -105, "point": 3.5},
                ],
            }],
        } for book in books],
    }


def _alternates_payload(identifier, books=("draftkings",),
                         last_update="2026-09-03T11:00:00Z"):
    """alternates: alternate_spreads outcomes are team-named; alternate_totals
    outcomes are Over/Under with no team -- two markets, different outcome
    shapes, in the same payload."""
    return {
        "id": identifier, "commence_time": "2026-09-03T23:00:00Z",
        "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
        "bookmakers": [{
            "key": book,
            "markets": [
                {"key": "alternate_spreads", "last_update": last_update,
                 "outcomes": [
                     {"name": "Atlanta Braves", "price": -110, "point": -1.5},
                     {"name": "San Francisco Giants", "price": -110, "point": 1.5},
                     {"name": "Atlanta Braves", "price": 150, "point": -2.5},
                     {"name": "San Francisco Giants", "price": -180, "point": 2.5},
                 ]},
                {"key": "alternate_totals", "last_update": last_update,
                 "outcomes": [
                     {"name": "Over", "price": -110, "point": 8.5},
                     {"name": "Under", "price": -110, "point": 8.5},
                 ]},
            ],
        } for book in books],
    }


def _f5_trio_payload(identifier, books=("draftkings",),
                      last_update="2026-09-03T11:00:00Z"):
    return {
        "id": identifier, "commence_time": "2026-09-03T23:00:00Z",
        "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
        "bookmakers": [{
            "key": book,
            "markets": [
                {"key": "h2h_1st_5_innings", "last_update": last_update,
                 "outcomes": [{"name": "Atlanta Braves", "price": -130},
                              {"name": "San Francisco Giants", "price": 110}]},
                {"key": "spreads_1st_5_innings", "last_update": last_update,
                 "outcomes": [{"name": "Atlanta Braves", "price": -110, "point": -0.5},
                              {"name": "San Francisco Giants", "price": -110, "point": 0.5}]},
                {"key": "totals_1st_5_innings", "last_update": last_update,
                 "outcomes": [{"name": "Over", "price": -110, "point": 4.5},
                              {"name": "Under", "price": -110, "point": 4.5}]},
            ],
        } for book in books],
    }


PAYLOAD_BY_FAMILY = {
    "team_totals": _team_totals_payload,
    "alternates": _alternates_payload,
    "f5_trio": _f5_trio_payload,
}


class FakeProvider:
    OddsProviderError = odds.OddsProviderError
    TEAM_TOTALS_MARKETS = odds.TEAM_TOTALS_MARKETS
    ALTERNATE_MARKETS = odds.ALTERNATE_MARKETS
    EVENT_MARKETS = odds.EVENT_MARKETS

    def __init__(self, listed, payloads=None, remaining=53000, billed=None, fail=None):
        self.listed = listed
        self.payloads = payloads or {}  # {(family, event_id): payload}
        self.remaining = remaining
        self.billed = billed
        self.fail = fail or {}  # {(family, event_id): message}
        self.fetched = []

    def status(self, env=None):
        return {"configured": True}

    def quota(self, env=None):
        return {"remaining": self.remaining, "last": 1}

    def list_events(self, env=None):
        return self.listed

    def fetch_event_odds_with_usage(self, event_id, markets=None, env=None):
        markets = tuple(markets or ())
        family = _family_for_markets(markets)
        self.fetched.append((family, event_id, markets))
        if (family, event_id) in self.fail:
            raise self.OddsProviderError(self.fail[(family, event_id)])
        billed = self.billed if self.billed is not None else len(markets)
        payload = self.payloads.get(
            (family, event_id),
            PAYLOAD_BY_FAMILY[family](event_id, books=()))
        used = self.remaining - billed if self.remaining is not None else None
        self.remaining = used
        return payload, {"remaining": used, "used": 1, "last": billed}


def _family_for_markets(markets) -> str:
    markets = set(markets)
    for family, expected in derivative_markets.FAMILY_MARKETS.items():
        if markets == set(expected):
            return family
    raise AssertionError(f"unrecognized market list: {markets}")


def _families(folder, measured=True):
    path = Path(folder) / "capture_families.json"
    families = {}
    for family, markets in derivative_markets.FAMILY_MARKETS.items():
        families[family] = {
            "measured": measured,
            "credits_per_event": len(markets) if measured else None,
            "measured_utc": "2026-09-03T00:00:00Z" if measured else None,
        }
    path.write_text(json.dumps({"families": families}), encoding="utf-8")
    return path


class _WithFamiliesPath:
    """Context manager: point budget.FAMILIES_CONFIG_PATH at a tempfile config
    for the duration of the block, restoring it after -- can_spend()/
    family_cost() read the module-level default path with no injection point
    of their own, same workaround test_batter_props.py uses."""

    def __init__(self, path):
        self.path = path
        self.original = None

    def __enter__(self):
        import src.capture.budget as budget_module
        self.original = budget_module.FAMILIES_CONFIG_PATH
        budget_module.FAMILIES_CONFIG_PATH = self.path
        return self

    def __exit__(self, *exc):
        import src.capture.budget as budget_module
        budget_module.FAMILIES_CONFIG_PATH = self.original


class MarketsTests(unittest.TestCase):
    def test_three_families_are_named_with_the_right_market_lists(self):
        self.assertEqual(set(derivative_markets.FAMILY_MARKETS),
                          {"team_totals", "alternates", "f5_trio"})
        self.assertEqual(derivative_markets.FAMILY_MARKETS["team_totals"],
                          odds.TEAM_TOTALS_MARKETS)
        self.assertEqual(derivative_markets.FAMILY_MARKETS["alternates"],
                          odds.ALTERNATE_MARKETS)
        self.assertEqual(derivative_markets.FAMILY_MARKETS["f5_trio"],
                          odds.EVENT_MARKETS)

    def test_none_of_the_three_is_the_non_droppable_floor(self):
        for family in derivative_markets.FAMILIES:
            self.assertNotEqual(family, budget.NON_DROPPABLE_FAMILY)
            self.assertIn(family, [d["family"] for d in budget.DROP_ORDER])


class SchemaTests(unittest.TestCase):
    def test_team_totals_selection_folds_in_the_team(self):
        listed = [_event("g1")]
        payloads = {("team_totals", "g1"): _team_totals_payload("g1", books=("draftkings",))}
        provider = FakeProvider(listed, payloads)
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                                  processed_store=processed,
                                                  provider=provider)
            rows = derivative_markets.read_processed(processed)
        team_totals_rows = [r for r in rows if r["family"] == "team_totals"]
        self.assertEqual(len(team_totals_rows), 4)  # 1 book x 2 teams x 2 sides
        for field in ("event_id", "game_date", "market", "selection", "line",
                      "price", "book", "book_last_update", "observed_utc"):
            self.assertIn(field, team_totals_rows[0])
        self.assertTrue(any(r["selection"] == "Atlanta Braves:Over" for r in team_totals_rows))
        self.assertTrue(any(r["selection"] == "Atlanta Braves:Under" for r in team_totals_rows))
        self.assertTrue(any(r["selection"] == "San Francisco Giants:Over"
                             for r in team_totals_rows))

    def test_alternates_projects_both_markets_with_distinct_selection_shapes(self):
        listed = [_event("g1")]
        payloads = {("alternates", "g1"): _alternates_payload("g1")}
        provider = FakeProvider(listed, payloads)
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                        processed_store=processed, provider=provider)
            rows = derivative_markets.read_processed(processed)
        alt_rows = [r for r in rows if r["family"] == "alternates"]
        spread_rows = [r for r in alt_rows if r["market"] == "alternate_spreads"]
        total_rows = [r for r in alt_rows if r["market"] == "alternate_totals"]
        self.assertEqual(len(spread_rows), 4)  # team-named, no team-folding needed
        self.assertEqual(len(total_rows), 2)  # Over/Under, no team
        self.assertTrue(any(r["selection"] == "Atlanta Braves" for r in spread_rows))
        self.assertTrue(any(r["selection"] == "Over" for r in total_rows))
        # Two different lines on the same side must be two rows, not one.
        lines = {r["line"] for r in spread_rows if r["selection"] == "Atlanta Braves"}
        self.assertEqual(lines, {"-1.5", "-2.5"})

    def test_f5_trio_projects_all_three_markets(self):
        listed = [_event("g1")]
        payloads = {("f5_trio", "g1"): _f5_trio_payload("g1")}
        provider = FakeProvider(listed, payloads)
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                        processed_store=processed, provider=provider)
            rows = derivative_markets.read_processed(processed)
        f5_rows = [r for r in rows if r["family"] == "f5_trio"]
        self.assertEqual({r["market"] for r in f5_rows},
                          {"h2h_1st_5_innings", "spreads_1st_5_innings",
                           "totals_1st_5_innings"})

    def test_idempotent_on_a_second_identical_run(self):
        listed = [_event("g1")]
        payloads = {("team_totals", "g1"): _team_totals_payload("g1", books=("draftkings",))}
        provider = FakeProvider(listed, payloads)
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                        processed_store=processed, provider=provider)
                first_count = len(derivative_markets.read_processed(processed))
                derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                        processed_store=processed, provider=provider)
                second_count = len(derivative_markets.read_processed(processed))
        self.assertEqual(first_count, second_count)

    def test_projected_key_dedupes_identical_rows_even_if_appended_twice(self):
        row = {"event_id": "g1", "family": "team_totals", "market": "team_totals",
               "book": "draftkings", "selection": "Atlanta Braves:Over",
               "line": "4.5", "book_last_update": "2026-09-03T11:00:00Z",
               "price": -110}
        with tempfile.TemporaryDirectory() as folder:
            processed = Path(folder) / "processed.jsonl"
            derivative_markets._append_projected([row], processed)
            written = derivative_markets._append_projected([row], processed)
            self.assertEqual(written, 0)
            self.assertEqual(len(derivative_markets.read_processed(processed)), 1)


class SlotTests(unittest.TestCase):
    """T-3h and T-30m are two independent fetches per (family, event); a
    slot already captured is never re-fetched, and a slot not yet due is
    never fetched early."""

    def test_not_due_between_slots_is_not_fetched(self):
        # 90 minutes out: past neither boundary from below -- still inside
        # the open T-3h band, so nothing NEW is due (it was already due,
        # and stays due, from T-3h all the way down to T-30m; a run at this
        # instant with nothing yet captured still owes the T-3h fetch).
        # This test instead checks the genuinely-too-early case: 4 hours out.
        listed = [_event("g1", commence=NOW + dt.timedelta(hours=4))]
        provider = FakeProvider(listed, {
            ("team_totals", "g1"): _team_totals_payload("g1"),
        })
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                    store=raw, processed_store=processed, provider=provider)
        self.assertEqual(provider.fetched, [])
        self.assertEqual(report["games_due"], 0)

    def test_past_first_pitch_is_not_fetched(self):
        listed = [_event("g1", commence=NOW - dt.timedelta(minutes=1))]
        provider = FakeProvider(listed, {
            ("team_totals", "g1"): _team_totals_payload("g1"),
        })
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                    store=raw, processed_store=processed, provider=provider)
        self.assertEqual(provider.fetched, [])
        self.assertEqual(report["games_due"], 0)

    def test_a_contract_is_captured_once_in_each_of_the_three_slots(self):
        listed = [_event("g1", commence=T3H)]
        provider = FakeProvider(listed, {
            ("team_totals", "g1"): _team_totals_payload("g1", books=("draftkings",)),
        })
        with tempfile.TemporaryDirectory() as folder:
            # Only team_totals is measured, so alternates/f5_trio stay
            # PROBE_REQUIRED and never fetch -- keeps this test's fetch
            # count to exactly the one family under test.
            fam_path = _families(folder, measured=False)
            data = json.loads(fam_path.read_text(encoding="utf-8"))
            data["families"]["team_totals"] = {
                "measured": True,
                "credits_per_event": len(odds.TEAM_TOTALS_MARKETS),
                "measured_utc": "2026-08-31T00:00:00Z",
            }
            fam_path.write_text(json.dumps(data), encoding="utf-8")
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                # T-3h: first fetch.
                r1 = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                    store=raw, processed_store=processed, provider=provider)
                # Still within the T-3h band (2h remaining): already captured,
                # must NOT re-fetch. Note this is 2h, not 1h -- with the
                # T-90m slot in place, 1h before first pitch is a DIFFERENT
                # band and is supposed to fetch.
                r2 = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                    now=T3H - dt.timedelta(hours=2),
                    store=raw, processed_store=processed, provider=provider)
                # T-90m (75 minutes out): a distinct slot, added 2026-09-07.
                # This is the band where first-five and prop boards fill out.
                r3 = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                    now=T3H - dt.timedelta(minutes=75),
                    store=raw, processed_store=processed, provider=provider)
                # T-30m (25 minutes to first pitch): third, distinct fetch.
                r4 = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                    now=T3H - dt.timedelta(minutes=25),
                    store=raw, processed_store=processed, provider=provider)
                # Still within the T-30m band (10 minutes to first pitch):
                # already captured, must NOT re-fetch again.
                r5 = derivative_markets.run(
                    credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                    now=T3H - dt.timedelta(minutes=10),
                    store=raw, processed_store=processed, provider=provider)
            markers = [r for r in derivative_markets.read(raw)
                       if r.get("poll") and r.get("family") == "team_totals"
                       and r.get("event_id") == "g1"]
        self.assertEqual(r1["fetches"], 1, "T-3h")
        self.assertEqual(r2["fetches"], 0, "still T-3h")
        self.assertEqual(r3["fetches"], 1, "T-90m")
        self.assertEqual(r4["fetches"], 1, "T-30m")
        self.assertEqual(r5["fetches"], 0, "still T-30m")
        self.assertEqual(len(markers), 3)
        self.assertEqual({m["slot"] for m in markers},
                         {"T-3h", "T-90m", "T-30m"})
        fetched_families_and_slots = [(f, e) for f, e, m in provider.fetched]
        self.assertEqual(fetched_families_and_slots,
                          [("team_totals", "g1")] * 3)


class BudgetGuardTests(unittest.TestCase):
    def test_unmeasured_families_are_probe_required_and_never_fetched(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, {
            ("team_totals", "g1"): _team_totals_payload("g1"),
            ("alternates", "g1"): _alternates_payload("g1"),
            ("f5_trio", "g1"): _f5_trio_payload("g1"),
        })
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder, measured=False)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                                  processed_store=processed,
                                                  provider=provider)
        self.assertEqual(provider.fetched, [])
        self.assertEqual(report["fetches"], 0)
        for family in derivative_markets.FAMILIES:
            self.assertTrue(
                report["budget_reasons"][family]["g1"].startswith("PROBE_REQUIRED"))
        # PROBE_REQUIRED must never appear as an ESCALATE line.
        self.assertEqual(report["escalate"], [])

    def test_measured_alternates_still_fetches_even_though_others_are_probe_required(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, {
            ("alternates", "g1"): _alternates_payload("g1"),
        })
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder, measured=False)
            # Only alternates is measured -- team_totals and f5_trio stay unmeasured.
            data = json.loads(fam_path.read_text(encoding="utf-8"))
            data["families"]["alternates"] = {
                "measured": True,
                "credits_per_event": len(odds.ALTERNATE_MARKETS),
                "measured_utc": "2026-08-31T00:00:00Z",
            }
            fam_path.write_text(json.dumps(data), encoding="utf-8")
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                                  processed_store=processed,
                                                  provider=provider)
        fetched_families = {family for family, _, _ in provider.fetched}
        self.assertEqual(fetched_families, {"alternates"})
        self.assertEqual(report["fetches"], 1)
        self.assertTrue(
            report["budget_reasons"]["team_totals"]["g1"].startswith("PROBE_REQUIRED"))
        self.assertTrue(
            report["budget_reasons"]["f5_trio"]["g1"].startswith("PROBE_REQUIRED"))

    def test_credit_floor_skips_the_whole_run(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, remaining=derivative_markets.CREDIT_FLOOR)
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                                  processed_store=processed,
                                                  provider=provider)
        self.assertEqual(report["skipped"], "credit floor")
        self.assertEqual(provider.fetched, [])

    def test_not_configured_skips_cleanly(self):
        class NotConfigured(FakeProvider):
            def status(self, env=None):
                return {"configured": False}
        provider = NotConfigured([])
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                                  processed_store=processed,
                                                  provider=provider)
        self.assertEqual(report["skipped"], "not configured")

    def test_a_failed_fetch_writes_an_error_row_not_a_marker(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, fail={("team_totals", "g1"): "boom"})
        with tempfile.TemporaryDirectory() as folder:
            fam_path = _families(folder)
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            with _WithFamiliesPath(fam_path):
                report = derivative_markets.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                                  processed_store=processed,
                                                  provider=provider)
            rows = derivative_markets.read(raw)
        self.assertTrue(any(r.get("error") for r in rows))
        self.assertFalse(any(r.get("poll") for r in rows if r.get("family") == "team_totals"
                              and r.get("event_id") == "g1"))
        self.assertTrue(any("team_totals g1: boom" in e for e in report["errors"]))


class EnabledSwitchTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(derivative_markets.enabled(env={}))

    def test_on_when_set(self):
        self.assertTrue(derivative_markets.enabled(env={"DERIVATIVES": "1"}))


if __name__ == "__main__":
    unittest.main()
