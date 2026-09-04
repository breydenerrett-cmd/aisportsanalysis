"""Tests for src/pipeline/prop_prices.py. Hermetic: the provider is a
stand-in that never touches a network or a key, matching test_prop_listing.py's
pattern -- this layer reuses prop_listing's slot/sampling logic directly."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src.pipeline import prop_prices
from src.providers import odds
from tests import HERMETIC_CREDIT_LOG_STORE

NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


def _event(identifier, commence, home="Atlanta Braves", away="San Francisco Giants"):
    return {"id": identifier,
            "commence_time": commence.isoformat().replace("+00:00", "Z"),
            "home_team": home, "away_team": away}


def _at(hours):
    return NOW + dt.timedelta(hours=hours)


def _payload(identifier, books=("draftkings", "fanduel"),
             players=("Bryce Elder", "Anthony Molina"), point=4.5,
             over_price=-120, under_price=-110):
    return {
        "id": identifier, "commence_time": "2026-09-02T18:00:00Z",
        "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
        "bookmakers": [{
            "key": book,
            "markets": [{
                "key": prop_prices.MARKET,
                "last_update": "2026-09-02T11:41:03Z",
                "outcomes": [
                    outcome
                    for player in players
                    for outcome in (
                        {"name": "Over", "description": player,
                         "price": over_price, "point": point},
                        {"name": "Under", "description": player,
                         "price": under_price, "point": point},
                    )
                ],
            }],
        } for book in books],
    }


class FakeProvider:
    OddsProviderError = odds.OddsProviderError

    def __init__(self, listed, payloads=None, remaining=53000, billed=1, fail=None):
        self.listed = listed
        self.payloads = payloads or {}
        self.remaining = remaining
        self.billed = billed
        self.fail = fail or {}
        self.fetched = []

    def status(self, env=None):
        return {"configured": True}

    def quota(self, env=None):
        return {"remaining": self.remaining, "last": 1}

    def list_events(self, env=None):
        return self.listed

    def fetch_event_odds_with_usage(self, event_id, markets=None, env=None):
        self.fetched.append((event_id, tuple(markets or ())))
        if event_id in self.fail:
            raise self.OddsProviderError(self.fail[event_id])
        payload = self.payloads.get(event_id, _payload(event_id, books=()))
        return payload, {"remaining": self.remaining, "used": 1,
                         "last": self.billed}


class ReusesPropListingDesignTests(unittest.TestCase):
    """The whole point of importing rather than copying: no drift possible."""

    def test_the_slot_grid_is_the_same_object_as_prop_listings(self):
        from src.pipeline import prop_listing
        self.assertIs(prop_prices.SLOTS, prop_listing.SLOTS)
        self.assertIs(prop_prices.GAMES_PER_DAY, prop_listing.GAMES_PER_DAY)

    def test_the_day_cap_is_three_games_times_six_slots(self):
        self.assertEqual(len(prop_prices.SLOTS), 6)
        self.assertEqual(prop_prices.DAILY_CREDIT_CAP, 18)


class SchemaTests(unittest.TestCase):
    """What a price row must carry -- price AND point, unlike prop_listing."""

    def test_a_priced_market_writes_one_row_per_book_per_pitcher(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
            rows = prop_prices.read(store)
        priced = [r for r in rows if r.get("player")]
        self.assertEqual(len(priced), 4)  # two books x two pitchers
        self.assertEqual(report["rows"], 4)
        for row in priced:
            self.assertEqual(row["point"], 4.5)
            self.assertEqual(row["over_price"], -120)
            self.assertEqual(row["under_price"], -110)
            for field in ("observed_utc", "event_id", "game_date",
                          "commence_time", "book", "book_last_update",
                          "player", "credits_last"):
                self.assertIn(field, row)

    def test_a_book_offering_only_one_side_still_gets_a_row(self):
        payload = {
            "id": "g1", "commence_time": "2026-09-02T18:00:00Z",
            "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
            "bookmakers": [{
                "key": "draftkings",
                "markets": [{
                    "key": prop_prices.MARKET,
                    "last_update": "2026-09-02T11:41:03Z",
                    "outcomes": [{"name": "Over", "description": "Bryce Elder",
                                 "price": -120, "point": 4.5}],
                }],
            }],
        }
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": payload})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
            rows = [r for r in prop_prices.read(store) if r.get("player")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["over_price"], -120)
        self.assertIsNone(rows[0]["under_price"])

    def test_a_successful_fetch_always_writes_a_marker(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
            markers = [r for r in prop_prices.read(store) if r.get("poll")]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["books_priced"], 2)
        self.assertEqual(markers[0]["credits_last"], 1)

    def test_a_failed_fetch_writes_an_error_row_and_no_marker(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, fail={"g1": "odds API returned HTTP 500"})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
            rows = prop_prices.read(store)
        self.assertEqual([r for r in rows if r.get("poll")], [])
        self.assertEqual(len([r for r in rows if r.get("error")]), 1)
        self.assertEqual(report["credits_spent"], 0)


class BudgetTests(unittest.TestCase):
    """Enforced from the store's OWN rows, never an in-memory counter."""

    def test_the_credit_floor_stops_everything(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")},
                                remaining=prop_prices.CREDIT_FLOOR)
        with tempfile.TemporaryDirectory() as folder:
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                                     store=Path(folder) / "prices.jsonl",
                                     provider=provider)
        self.assertEqual(report["skipped"], "credit floor")
        self.assertEqual(provider.fetched, [])

    def test_the_layer_yields_above_the_floor_but_below_the_reserve(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")},
                                remaining=prop_prices.PROBE_RESERVE - 1)
        with tempfile.TemporaryDirectory() as folder:
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                                     store=Path(folder) / "prices.jsonl",
                                     provider=provider)
        self.assertEqual(report["skipped"], "probe reserve")
        self.assertEqual(provider.fetched, [])

    def test_the_day_cap_is_read_from_the_stores_own_marker_rows(self):
        # Pre-seed the store with a day's worth of markers written by a
        # PRIOR run (or process) -- the cap must bind from disk, not from
        # anything this call remembers.
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        game_date = "2026-09-02"
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            prop_prices.append(
                [{"observed_utc": "x", "poll": True, "credits_last": 1,
                  "game_date": game_date}] * prop_prices.DAILY_CREDIT_CAP, store)
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
        self.assertEqual(provider.fetched, [])
        self.assertTrue(any("ESCALATE" in line and game_date in line
                            for line in report["escalate"]))

    def test_a_day_under_the_cap_still_spends(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        game_date = "2026-09-02"
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            prop_prices.append(
                [{"observed_utc": "x", "poll": True, "credits_last": 1,
                  "game_date": game_date}] * (prop_prices.DAILY_CREDIT_CAP - 1),
                store)
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
        self.assertEqual(report["fetches"], 1)

    def test_spend_is_counted_from_markers_not_from_price_rows(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=provider)
            rows = prop_prices.read(store)
        self.assertEqual(prop_prices.credits_spent(rows), 1)

    def test_an_unconfigured_provider_spends_nothing(self):
        provider = FakeProvider([_event("g1", _at(6))])
        provider.status = lambda env=None: {"configured": False}
        with tempfile.TemporaryDirectory() as folder:
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                                     store=Path(folder) / "prices.jsonl",
                                     provider=provider)
        self.assertEqual(report["skipped"], "not configured")


class ResumabilityTests(unittest.TestCase):
    def test_a_slot_already_recorded_is_never_re_fetched(self):
        listed = [_event("g1", _at(6))]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prices.jsonl"
            first = FakeProvider(listed, {"g1": _payload("g1")})
            prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=store, provider=first)
            second = FakeProvider(listed, {"g1": _payload("g1")})
            report = prop_prices.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW + dt.timedelta(minutes=30),
                                     store=store, provider=second)
        self.assertEqual(second.fetched, [])
        self.assertEqual(report["credits_spent"], 0)


class SwitchTests(unittest.TestCase):
    def test_disabled_unless_prop_prices_equals_one(self):
        self.assertFalse(prop_prices.enabled({}))
        self.assertFalse(prop_prices.enabled({"PROP_PRICES": "0"}))
        self.assertFalse(prop_prices.enabled({"PROP_PRICES": "off"}))
        self.assertTrue(prop_prices.enabled({"PROP_PRICES": "1"}))

    def test_main_reports_off_and_spends_nothing_when_disabled(self):
        from unittest import mock
        with mock.patch("builtins.print") as fake_print, \
             mock.patch.object(prop_prices, "_load_dotenv"), \
             mock.patch.dict("os.environ", {"PROP_PRICES": ""}, clear=False):
            code = prop_prices.main()
        self.assertEqual(code, 0)
        self.assertIn("off", fake_print.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
