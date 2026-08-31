"""The prop-listing feasibility audit: bounded spend, provable absence, no prices.

These tests spend nothing. The provider is a stand-in whose every fetch reports
what it billed, which is also how the real store audits itself.
"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import prop_listing
from src.providers import odds

NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


def _event(identifier, commence, home="Atlanta Braves", away="San Francisco Giants"):
    return {"id": identifier,
            "commence_time": commence.isoformat().replace("+00:00", "Z"),
            "home_team": home, "away_team": away}


def _at(hours):
    """An event whose first pitch is `hours` from NOW."""
    return NOW + dt.timedelta(hours=hours)


def _payload(identifier, books=("draftkings", "fanduel"),
             players=("Bryce Elder", "Anthony Molina")):
    return {
        "id": identifier, "commence_time": "2026-09-02T18:00:00Z",
        "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
        "bookmakers": [{
            "key": book,
            "title": book.title(),
            "markets": [{
                "key": prop_listing.MARKET,
                "last_update": "2026-09-02T11:41:03Z",
                "outcomes": [
                    {"name": side, "description": player,
                     "price": -154, "point": 4.5}
                    for player in players for side in ("Over", "Under")
                ],
            }],
        } for book in books],
    }


class FakeProvider:
    """Enough of src.providers.odds to run the pass without a network or a key."""

    OddsProviderError = odds.OddsProviderError

    def __init__(self, listed, payloads=None, remaining=53000, billed=1,
                 fail=None):
        self.listed = listed
        self.payloads = payloads or {}
        self.remaining = remaining
        self.billed = billed
        self.fail = fail or {}
        self.fetched = []

    def status(self, env=None):
        return {"configured": True}

    def quota(self, env=None):
        return {"remaining": self.remaining}

    def list_events(self, env=None):
        return self.listed

    def fetch_event_odds_with_usage(self, event_id, markets=None, env=None):
        self.fetched.append((event_id, tuple(markets or ())))
        if event_id in self.fail:
            raise self.OddsProviderError(self.fail[event_id])
        payload = self.payloads.get(event_id, _payload(event_id, books=()))
        return payload, {"remaining": self.remaining, "used": 1,
                         "last": self.billed}


class SlotGridTests(unittest.TestCase):
    """The slot a run is in, and the windows it refuses to invent."""

    def test_the_current_slot_is_the_smallest_offset_already_passed(self):
        # At seven hours out the live slot is T-8h; T-12h has gone by and
        # back-filling it under its own label would fake an observation time.
        self.assertEqual(prop_listing._due_slot(_event("a", _at(7)), NOW), "T-8h")

    def test_each_slot_boundary_is_inclusive(self):
        for hours, expected in ((12, "T-12h"), (8, "T-8h"), (6, "T-6h"),
                                (4, "T-4h"), (2, "T-2h"), (0.5, "T-30m")):
            self.assertEqual(
                prop_listing._due_slot(_event("a", _at(hours)), NOW), expected)

    def test_nothing_is_due_before_the_grid_opens(self):
        self.assertIsNone(prop_listing._due_slot(_event("a", _at(13)), NOW))

    def test_nothing_is_due_after_first_pitch(self):
        # A prop fetched in-play answers no question this audit asks and still
        # costs a credit.
        self.assertIsNone(prop_listing._due_slot(_event("a", _at(-0.1)), NOW))

    def test_six_slots_at_three_games_is_the_day_cap(self):
        self.assertEqual(len(prop_listing.SLOTS), 6)
        self.assertEqual(prop_listing.DAILY_CREDIT_CAP, 18)


class SampleSelectionTests(unittest.TestCase):
    """Deterministic selection, frozen once made."""

    def test_earliest_median_latest(self):
        slate = [_event(str(i), _at(i)) for i in range(1, 8)]
        self.assertEqual(prop_listing._choose(slate), ["1", "4", "7"])

    def test_a_short_slate_is_taken_whole(self):
        slate = [_event("a", _at(1)), _event("b", _at(2))]
        self.assertEqual(prop_listing._choose(slate), ["a", "b"])

    def test_ties_are_broken_by_event_id_not_api_order(self):
        same = _at(3)
        forward = [_event(x, same) for x in ("c", "a", "b", "d")]
        self.assertEqual(prop_listing._choose(forward),
                         prop_listing._choose(list(reversed(forward))))

    def test_a_full_slate_records_that_it_was_seen_from_the_top(self):
        slate = [_event(str(i), _at(i)) for i in (2, 6, 11)]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            prop_listing.run(env={}, now=NOW, store=store,
                             provider=FakeProvider(slate))
            sample = [r for r in prop_listing.read(store) if r.get("sample")][0]
        self.assertEqual(sample["selected_at_slot"], "T-12h")

    def test_a_partial_slate_says_so_instead_of_being_corrected(self):
        # Starting mid-slate, /events has already dropped the games that began,
        # so these three are the earliest/median/latest of what is LEFT. The
        # row records that rather than passing the pick off as the day's.
        slate = [_event(str(i), _at(i)) for i in (1, 2, 3)]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            prop_listing.run(env={}, now=NOW, store=store,
                             provider=FakeProvider(slate))
            sample = [r for r in prop_listing.read(store) if r.get("sample")][0]
        self.assertEqual(sample["selected_at_slot"], "T-4h")
        self.assertEqual(sample["slate_size"], 3)

    def test_the_sample_is_frozen_when_the_slate_shrinks(self):
        # /events drops games once they start, so re-choosing every run would
        # move "the earliest game" and scatter the spend over the whole slate.
        slate = [_event(str(i), _at(i)) for i in range(1, 8)]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            first = FakeProvider(slate)
            prop_listing.run(env={}, now=NOW, store=store, provider=first)
            later = NOW + dt.timedelta(hours=3)
            survivors = [e for e in slate
                         if prop_listing._parse_iso(e["commence_time"]) > later]
            second = FakeProvider(survivors)
            prop_listing.run(env={}, now=later, store=store, provider=second)
            samples = prop_listing._samples(prop_listing.read(store))
        self.assertEqual(list(samples.values())[0], ["1", "4", "7"])
        # Everything fetched on the later run is still inside the frozen sample.
        for event_id, _markets in second.fetched:
            self.assertIn(event_id, ["1", "4", "7"])


class RecordingTests(unittest.TestCase):
    """What a row may contain, and what it may never contain."""

    def _run(self, provider, now=NOW, store=None):
        return prop_listing.run(env={}, now=now, store=store, provider=provider)

    def test_a_listed_market_writes_one_row_per_book_per_pitcher(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            report = self._run(provider, store=store)
            rows = prop_listing.read(store)
        listing = [r for r in rows if r.get("listed")]
        self.assertEqual(len(listing), 4)  # two books x two pitchers
        self.assertEqual(report["rows"], 4)
        self.assertEqual({r["book"] for r in listing}, {"draftkings", "fanduel"})
        self.assertEqual({r["player"] for r in listing},
                         {"Bryce Elder", "Anthony Molina"})
        self.assertEqual({r["book_last_update"] for r in listing},
                         {"2026-09-02T11:41:03Z"})

    def test_no_price_and_no_point_is_ever_stored(self):
        # The approval was for a listing audit. A store that quietly accumulated
        # prop prices would be a research collection wearing a feasibility label.
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            self._run(provider, store=store)
            text = Path(store).read_text(encoding="utf-8")
            rows = prop_listing.read(store)
        for row in rows:
            for banned in ("price", "point", "over_price", "under_price"):
                self.assertNotIn(banned, row)
        self.assertNotIn("-154", text)
        self.assertNotIn("4.5", text)

    def test_an_empty_poll_writes_a_marker_that_proves_the_absence(self):
        # "We looked and no book listed it" must never be indistinguishable
        # from "we never looked" -- rosterwatch's rule, rosterwatch's reason.
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1", books=())})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            report = self._run(provider, store=store)
            rows = prop_listing.read(store)
        markers = [r for r in rows if r.get("poll")]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["books_listing"], 0)
        self.assertEqual(markers[0]["slot"], "T-6h")
        self.assertEqual(markers[0]["credits_last"], 1)
        self.assertEqual(report["rows"], 0)
        self.assertEqual(report["markers"], 1)

    def test_a_successful_poll_always_writes_a_marker(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            self._run(provider, store=store)
            rows = prop_listing.read(store)
        markers = [r for r in rows if r.get("poll")]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["books_listing"], 2)

    def test_a_failed_fetch_writes_an_error_row_and_no_marker(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, fail={"g1": "odds API returned HTTP 500"})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            report = self._run(provider, store=store)
            rows = prop_listing.read(store)
        errors = [r for r in rows if r.get("error")]
        self.assertEqual(len(errors), 1)
        self.assertEqual([r for r in rows if r.get("poll")], [])
        self.assertEqual(report["credits_spent"], 0)
        self.assertEqual(len(report["errors"]), 1)

    def test_every_row_carries_the_schedule_version(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            self._run(provider, store=store)
            rows = prop_listing.read(store)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["schedule_version"], prop_listing.SCHEDULE_VERSION)

    def test_only_the_prop_market_is_ever_requested(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            self._run(provider, store=store)
        self.assertEqual(provider.fetched, [("g1", ("pitcher_strikeouts",))])


class ResumabilityTests(unittest.TestCase):
    def test_a_slot_already_recorded_is_never_re_fetched(self):
        listed = [_event("g1", _at(6))]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            first = FakeProvider(listed, {"g1": _payload("g1")})
            prop_listing.run(env={}, now=NOW, store=store, provider=first)
            second = FakeProvider(listed, {"g1": _payload("g1")})
            report = prop_listing.run(env={}, now=NOW + dt.timedelta(minutes=30),
                                      store=store, provider=second)
        self.assertEqual(second.fetched, [])
        self.assertEqual(report["credits_spent"], 0)

    def test_the_next_slot_is_fetched_when_it_comes_due(self):
        listed = [_event("g1", _at(6))]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            first = FakeProvider(listed, {"g1": _payload("g1")})
            prop_listing.run(env={}, now=NOW, store=store, provider=first)
            second = FakeProvider(listed, {"g1": _payload("g1")})
            prop_listing.run(env={}, now=NOW + dt.timedelta(hours=3),
                             store=store, provider=second)
            rows = prop_listing.read(store)
        slots = [r["slot"] for r in rows if r.get("poll")]
        self.assertEqual(slots, ["T-6h", "T-4h"])

    def test_a_failing_slot_is_retried_once_and_then_left_alone(self):
        listed = [_event("g1", _at(6))]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            for minutes in (0, 10, 20, 30):
                provider = FakeProvider(listed, fail={"g1": "boom"})
                prop_listing.run(env={}, now=NOW + dt.timedelta(minutes=minutes),
                                 store=store, provider=provider)
                attempts = prop_listing._attempts(prop_listing.read(store))
            self.assertEqual(attempts[("g1", "T-6h")],
                             prop_listing.MAX_ATTEMPTS_PER_SLOT)

    def test_an_interrupted_append_does_not_corrupt_the_next_row(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            store.write_text('{"observed_utc":"a","poll":true,"credits_last":1}\n'
                             '{"observed_utc":"b","pol', encoding="utf-8")
            prop_listing.append([{"observed_utc": "c", "poll": True,
                                  "credits_last": 1}], store)
            lines = store.read_text(encoding="utf-8").splitlines()
            rows = prop_listing.read(store)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(rows), 2)  # the fragment is skipped, not merged
        self.assertEqual(json.loads(lines[2])["observed_utc"], "c")


class BudgetTests(unittest.TestCase):
    """The floor, the day cap, and the hard cap -- checked before spending."""

    def test_the_credit_floor_stops_everything(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")},
                                remaining=prop_listing.CREDIT_FLOOR)
        with tempfile.TemporaryDirectory() as folder:
            report = prop_listing.run(env={}, now=NOW,
                                      store=Path(folder) / "prop.jsonl",
                                      provider=provider)
        self.assertEqual(report["skipped"], "credit floor")
        self.assertEqual(provider.fetched, [])

    def test_the_audit_yields_above_the_floor_but_below_the_reserve(self):
        # Lowest-priority layer: it skips itself before baseline capture is
        # touched, and that is not the floor being hit.
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")},
                                remaining=prop_listing.PROBE_RESERVE - 1)
        with tempfile.TemporaryDirectory() as folder:
            report = prop_listing.run(env={}, now=NOW,
                                      store=Path(folder) / "prop.jsonl",
                                      provider=provider)
        self.assertEqual(report["skipped"], "probe reserve")
        self.assertEqual(provider.fetched, [])

    def test_the_hard_cap_stops_the_audit_and_escalates(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            prop_listing.append(
                [{"observed_utc": "x", "poll": True, "credits_last": 1,
                  "game_date": "2026-09-01"}] * prop_listing.HARD_CAP, store)
            report = prop_listing.run(env={}, now=NOW, store=store,
                                      provider=provider)
        self.assertEqual(report["skipped"], "hard cap")
        self.assertEqual(provider.fetched, [])
        self.assertTrue(any("ESCALATE" in line for line in report["escalate"]))

    def test_the_day_cap_escalates_instead_of_overspending(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        game_date = prop_listing._slate_date(_at(6))
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            prop_listing.append(
                [{"observed_utc": "x", "poll": True, "credits_last": 1,
                  "game_date": game_date}] * prop_listing.DAILY_CREDIT_CAP, store)
            report = prop_listing.run(env={}, now=NOW, store=store,
                                      provider=provider)
        self.assertEqual(provider.fetched, [])
        self.assertTrue(any("ESCALATE" in line and game_date in line
                            for line in report["escalate"]))

    def test_a_run_never_exceeds_its_fetch_ceiling(self):
        listed = [_event(f"g{i}", _at(6)) for i in range(12)]
        provider = FakeProvider(listed)
        with tempfile.TemporaryDirectory() as folder:
            report = prop_listing.run(env={}, now=NOW,
                                      store=Path(folder) / "prop.jsonl",
                                      provider=provider)
        self.assertLessEqual(report["fetches"], prop_listing.MAX_FETCHES_PER_RUN)

    def test_spend_is_counted_from_markers_not_from_listing_rows(self):
        # One response writes many listing rows; summing their credits_last
        # would multiply the measured spend by the number of books.
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            prop_listing.run(env={}, now=NOW, store=store, provider=provider)
            rows = prop_listing.read(store)
        self.assertEqual(prop_listing.credits_spent(rows), 1)

    def test_a_missing_credit_header_is_charged_as_one_and_stored_as_null(self):
        listed = [_event("g1", _at(6))]
        provider = FakeProvider(listed, {"g1": _payload("g1")}, billed=None)
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "prop.jsonl"
            report = prop_listing.run(env={}, now=NOW, store=store,
                                      provider=provider)
            rows = prop_listing.read(store)
        marker = [r for r in rows if r.get("poll")][0]
        self.assertIsNone(marker["credits_last"])
        self.assertEqual(report["credits_spent"], 1)
        self.assertEqual(prop_listing.credits_spent(rows), 1)

    def test_an_unconfigured_provider_spends_nothing(self):
        provider = FakeProvider([_event("g1", _at(6))])
        provider.status = lambda env=None: {"configured": False}
        with tempfile.TemporaryDirectory() as folder:
            report = prop_listing.run(env={}, now=NOW,
                                      store=Path(folder) / "prop.jsonl",
                                      provider=provider)
        self.assertEqual(report["skipped"], "not configured")


class SwitchTests(unittest.TestCase):
    def test_the_audit_is_off_unless_the_switch_says_on(self):
        self.assertFalse(prop_listing.enabled({}))
        self.assertFalse(prop_listing.enabled({"PROP_LISTING_AUDIT": "off"}))
        for value in ("on", "1", "yes", "TRUE"):
            self.assertTrue(prop_listing.enabled({"PROP_LISTING_AUDIT": value}))


class ProviderSupportTests(unittest.TestCase):
    """The prop key is nameable per event, and nowhere else."""

    def test_the_prop_market_is_nameable_on_the_per_event_endpoint(self):
        self.assertEqual(
            odds._validate_markets(["pitcher_strikeouts"],
                                   allow_event_markets=True),
            ["pitcher_strikeouts"])

    def test_the_featured_endpoint_still_refuses_it_before_spending(self):
        with self.assertRaises(odds.OddsProviderError) as ctx:
            odds._validate_markets(["h2h", "pitcher_strikeouts"])
        self.assertIn("bills per event", str(ctx.exception))

    def test_props_are_not_requested_by_default_anywhere(self):
        for market in odds.PROP_MARKETS:
            self.assertNotIn(market, odds.DEFAULT_MARKETS)
            self.assertNotIn(market, odds.EVENT_MARKETS)

    def test_the_rest_of_the_prop_catalogue_is_still_rejected(self):
        # Support was extended by exactly one key, for exactly one audit.
        for market in ("batter_home_runs", "pitcher_outs", "player_props"):
            with self.assertRaises(odds.OddsProviderError):
                odds._validate_markets([market], allow_event_markets=True)

    def test_a_prop_fetch_costs_one_credit_per_event(self):
        est = odds.estimate_event_credits(3, markets=["pitcher_strikeouts"])
        self.assertEqual(est["credits_per_event"], 1)
        self.assertEqual(est["credits_total"], 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
