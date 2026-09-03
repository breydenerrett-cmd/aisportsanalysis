"""PriceObservation / InformationEvent validators and JSONL round trip."""

import json
import unittest

from src.board.record import (
    InformationEvent,
    PriceObservation,
    RecordValidationError,
    information_event_from_dict,
    price_observation_from_dict,
    to_jsonl_line,
)


def make_price_observation(**overrides):
    fields = dict(
        sport="mlb", event_id="e1", game_pk=None, market_key="h2h",
        selection_id="abcdef0123456789", side="home", subject_kind=None,
        subject_id=None, line=None, book="fanduel", price_american=-150,
        observed_utc="2026-08-31T10:08:30Z", book_last_update="2026-08-31T10:08:23Z",
        known_at="2026-08-31T10:08:30Z", known_at_grade="A",
        capture_id="cap1", source="odds_api", region="us",
        provider_market_key="h2h",
    )
    fields.update(overrides)
    return PriceObservation(**fields)


class PriceObservationValidationTests(unittest.TestCase):
    def test_valid_observation_constructs(self):
        obs = make_price_observation()
        self.assertEqual(obs.price_american, -150)

    def test_rejects_float_price(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(price_american=-150.0)

    def test_rejects_bool_price(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(price_american=True)

    def test_rejects_price_in_dead_zone(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(price_american=50)

    def test_accepts_boundary_prices(self):
        make_price_observation(price_american=100)
        make_price_observation(price_american=-100)

    def test_rejects_float_line(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(line=8.5)

    def test_accepts_decimal_string_line(self):
        obs = make_price_observation(line="8.5")
        self.assertEqual(obs.line, "8.5")

    def test_rejects_non_matching_line_string(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(line="over 8.5")

    def test_accepts_negative_line(self):
        obs = make_price_observation(line="-1.5")
        self.assertEqual(obs.line, "-1.5")

    def test_rejects_bad_grade(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(known_at_grade="Z")

    def test_rejects_bad_iso_string(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(observed_utc="not-a-date")

    def test_rejects_bad_venue_kind(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(venue_kind="casino")

    def test_defaults(self):
        obs = make_price_observation()
        self.assertEqual(obs.venue_kind, "sportsbook")
        self.assertFalse(obs.is_close)
        self.assertIsNone(obs.limit_observed)
        self.assertTrue(obs.l0_available)

    def test_is_frozen(self):
        obs = make_price_observation()
        with self.assertRaises(Exception):
            obs.price_american = -200

    def test_limit_observed_accepts_int_or_none(self):
        obs = make_price_observation(limit_observed=500)
        self.assertEqual(obs.limit_observed, 500)
        make_price_observation(limit_observed=None)

    def test_limit_observed_rejects_float(self):
        with self.assertRaises(RecordValidationError):
            make_price_observation(limit_observed=500.0)


class InformationEventTests(unittest.TestCase):
    def make(self, **overrides):
        fields = dict(
            sport="mlb", scope="game", scope_id="e1", kind="lineup_posted",
            payload={"lineup": ["p1", "p2"]}, happened_utc="2026-08-31T18:00:00Z",
            known_at="2026-08-31T18:00:00Z", known_at_grade="B",
            observed_utc="2026-08-31T18:00:05Z", source="statsapi",
            capture_id="cap2",
        )
        fields.update(overrides)
        return InformationEvent(**fields)

    def test_valid_event_constructs(self):
        ev = self.make()
        self.assertEqual(ev.kind, "lineup_posted")

    def test_rejects_bad_grade(self):
        with self.assertRaises(RecordValidationError):
            self.make(known_at_grade="F")

    def test_happened_utc_may_be_none(self):
        ev = self.make(happened_utc=None)
        self.assertIsNone(ev.happened_utc)

    def test_is_frozen(self):
        ev = self.make()
        with self.assertRaises(Exception):
            ev.kind = "il_placement"


class JsonlRoundTripTests(unittest.TestCase):
    def test_price_observation_round_trip(self):
        obs = make_price_observation(line="8.5", subject_kind=None)
        line = to_jsonl_line(obs)
        parsed = json.loads(line)
        restored = price_observation_from_dict(parsed)
        self.assertEqual(obs, restored)

    def test_information_event_round_trip(self):
        ev = InformationEvent(
            sport="mlb", scope="game", scope_id="e1", kind="weather_forecast",
            payload={"wind_mph": 12}, happened_utc=None,
            known_at="2026-08-31T12:00:00Z", known_at_grade="C",
            observed_utc="2026-08-31T12:00:01Z", source="noaa",
            capture_id="cap3",
        )
        line = to_jsonl_line(ev)
        parsed = json.loads(line)
        restored = information_event_from_dict(parsed)
        self.assertEqual(ev, restored)

    def test_no_float_in_serialized_price_observation(self):
        obs = make_price_observation(line="8.5")
        serialized = json.loads(to_jsonl_line(obs))
        for key, value in serialized.items():
            self.assertNotIsInstance(
                value, float, msg=f"field {key} serialized as float: {value!r}"
            )


if __name__ == "__main__":
    unittest.main()
