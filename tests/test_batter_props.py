"""Tests for src/pipeline/batter_props.py. Hermetic: the provider is a
stand-in that never touches a network or a key, matching test_prop_prices.py's
pattern."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src.capture import budget
from src.pipeline import batter_props
from src.providers import odds
from tests import HERMETIC_CREDIT_LOG_STORE

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def _event(identifier, commence=NOW, home="Atlanta Braves", away="San Francisco Giants"):
    return {"id": identifier,
            "commence_time": commence.isoformat().replace("+00:00", "Z"),
            "home_team": home, "away_team": away}


def _payload(identifier, books=("draftkings", "fanduel"),
             players=(("p1", "Ronald Acuna Jr."), ("p2", "Matt Olson")),
             point=1.5, over_price=110, under_price=-140,
             last_update="2026-09-03T11:00:00Z"):
    return {
        "id": identifier, "commence_time": "2026-09-03T23:00:00Z",
        "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
        "bookmakers": [{
            "key": book,
            "markets": [{
                "key": market,
                "last_update": last_update,
                "outcomes": [
                    outcome
                    for pid, name in players
                    for outcome in (
                        {"name": "Over", "description": name,
                         "participant_id": pid, "price": over_price, "point": point},
                        {"name": "Under", "description": name,
                         "participant_id": pid, "price": under_price, "point": point},
                    )
                ],
            } for market in batter_props.MARKETS],
        } for book in books],
    }


class FakeProvider:
    OddsProviderError = odds.OddsProviderError
    BATTER_MARKETS = odds.BATTER_MARKETS
    PROP_MARKETS = odds.PROP_MARKETS

    def __init__(self, listed, payloads=None, remaining=53000, billed=6, fail=None):
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
        used = self.remaining - self.billed if self.remaining is not None else None
        self.remaining = used
        return payload, {"remaining": used, "used": 1, "last": self.billed}


def _families(folder, measured=True):
    import json
    path = Path(folder) / "capture_families.json"
    entry = {"measured": measured,
             "credits_per_event": batter_props.CREDITS_PER_EVENT if measured else None,
             "measured_utc": "2026-09-03T00:00:00Z" if measured else None}
    path.write_text(json.dumps({"families": {
        "batter_props_floor": dict(entry),
        "batter_props_extra": dict(entry),
    }}), encoding="utf-8")
    return path


class MarketsTests(unittest.TestCase):
    def test_six_batter_markets_are_named(self):
        self.assertEqual(len(batter_props.MARKETS), 6)
        self.assertEqual(batter_props.CREDITS_PER_EVENT, 6)

    def test_floor_family_is_the_budget_non_droppable_family(self):
        self.assertEqual(batter_props.FLOOR_FAMILY, budget.NON_DROPPABLE_FAMILY)


class SchemaTests(unittest.TestCase):
    def test_a_priced_market_projects_one_row_per_book_per_selection_per_market(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                       processed_store=processed, provider=provider)
            rows = batter_props.read_processed(processed)
        # 6 markets x 2 books x 2 players x 2 sides (over/under selections)
        self.assertEqual(len(rows), 6 * 2 * 2 * 2)
        self.assertEqual(report["rows"], len(rows))
        for row in rows:
            for field in ("event_id", "game_date", "market", "selection",
                          "line", "price", "book", "book_last_update",
                          "observed_utc"):
                self.assertIn(field, row)
        self.assertTrue(any(r["selection"] == "p1:Over" for r in rows))
        self.assertTrue(any(r["selection"] == "p1:Under" for r in rows))

    def test_idempotent_on_a_second_identical_run(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                              processed_store=processed, provider=provider)
            first_count = len(batter_props.read_processed(processed))
            # Second run: same slate, same event already marked done today ->
            # no new fetch, no new rows.
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                              processed_store=processed, provider=provider)
            second_count = len(batter_props.read_processed(processed))
        self.assertEqual(first_count, second_count)

    def test_projected_key_dedupes_identical_rows_even_if_appended_twice(self):
        row = {"event_id": "g1", "market": "batter_hits", "book": "draftkings",
               "selection": "p1:Over", "line": "1.5",
               "book_last_update": "2026-09-03T11:00:00Z", "price": 110}
        with tempfile.TemporaryDirectory() as folder:
            processed = Path(folder) / "processed.jsonl"
            batter_props._append_projected([row], processed)
            written = batter_props._append_projected([row], processed)
            self.assertEqual(written, 0)
            self.assertEqual(len(batter_props.read_processed(processed)), 1)


class FloorAndExtraTests(unittest.TestCase):
    def test_floor_games_are_fetched_even_when_extra_family_is_probe_required(self):
        listed = [_event(f"g{i}") for i in range(1, 6)]
        payloads = {e["id"]: _payload(e["id"], books=("draftkings",),
                                       players=(("p1", "Player One"),))
                    for e in listed}
        provider = FakeProvider(listed, payloads)
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            fam_path = _families(folder, measured=False)
            import src.capture.budget as budget_module
            original = budget_module.FAMILIES_CONFIG_PATH
            budget_module.FAMILIES_CONFIG_PATH = fam_path
            try:
                report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                           processed_store=processed, provider=provider)
            finally:
                budget_module.FAMILIES_CONFIG_PATH = original
        floor_ids = budget.rotated_floor_games(
            sorted(e["id"] for e in listed), "2026-09-03")
        self.assertEqual(len(floor_ids), budget.NON_DROPPABLE_GAMES_PER_NIGHT)
        fetched_ids = {eid for eid, _ in provider.fetched}
        for fid in floor_ids:
            self.assertIn(fid, fetched_ids)

    def test_extra_family_envelope_reads_the_injected_store_not_real_disk(self):
        """Regression pin for the 2026-09-04 break (docs/planning/attack.md
        F13/S17 lineage): `can_spend`'s envelope half falls back to
        `spent_today()` -- a read of `credit_log_store` -- whenever a
        caller doesn't pass `spent` directly. `batter_props.run` passes
        `spent=None` for the non-droppable floor family (exempt from the
        envelope by contract) but, for `batter_props_extra`, must derive it
        from `credit_log_store`, never from whatever
        data/processed/credit_log.jsonl happens to hold today. Two runs
        against the SAME fake provider (`remaining` fixed, so the floor
        check never fires) differing only in the injected store's own
        recorded spend must reach opposite envelope decisions for the extra
        family -- proving the decision tracks the seam, not ambient state.
        """
        listed = [_event(f"g{i}") for i in range(1, 8)]  # more than one night's floor
        payloads = {e["id"]: _payload(e["id"], books=("draftkings",),
                                       players=(("p1", "Player One"),))
                    for e in listed}
        today_utc = dt.datetime.now(dt.timezone.utc)

        def extra_fetch_ids(store):
            provider = FakeProvider(listed, payloads, remaining=53000)
            with tempfile.TemporaryDirectory() as folder:
                raw = Path(folder) / "raw.jsonl"
                processed = Path(folder) / "processed.jsonl"
                batter_props.run(credit_log_store=store, env={}, now=NOW,
                                  store=raw, processed_store=processed,
                                  provider=provider)
            floor_ids = set(budget.rotated_floor_games(
                sorted(e["id"] for e in listed),
                batter_props.prop_listing._slate_date(NOW)))
            return {eid for eid, _ in provider.fetched if eid not in floor_ids}

        with tempfile.TemporaryDirectory() as folder:
            # A store with no rows for today: spent_today() reads 0, so the
            # extra family clears the envelope and gets fetched.
            quiet_store = Path(folder) / "quiet_credit_log.jsonl"
            self.assertTrue(extra_fetch_ids(quiet_store),
                             "extra family should fetch when the injected "
                             "store shows no spend today")

            # A store whose own rows show today's spend already past
            # DAILY_ENVELOPE (the exact shape of 2026-09-04's real log):
            # the SAME provider, SAME `remaining`, must now refuse the
            # extra family on "daily envelope".
            loud_store = Path(folder) / "loud_credit_log.jsonl"
            rows = [
                {"utc": today_utc.replace(microsecond=0).isoformat()
                        .replace("+00:00", "Z"),
                 "credits_remaining": 100000, "credits_used_last": 0,
                 "caller": "test"},
                {"utc": (today_utc + dt.timedelta(minutes=1))
                        .replace(microsecond=0).isoformat()
                        .replace("+00:00", "Z"),
                 "credits_remaining": 100000 - budget.DAILY_ENVELOPE - 1,
                 "credits_used_last": 0, "caller": "test"},
            ]
            loud_store.write_text(
                "\n".join(__import__("json").dumps(r) for r in rows) + "\n",
                encoding="utf-8")
            self.assertEqual(
                extra_fetch_ids(loud_store), set(),
                "extra family must refuse to spend once the injected "
                "store's own rows show the envelope already exceeded")

    def test_credit_floor_skips_the_whole_run(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, remaining=batter_props.CREDIT_FLOOR)
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                       processed_store=processed, provider=provider)
        self.assertEqual(report["skipped"], "credit floor")
        self.assertEqual(provider.fetched, [])

    def test_not_configured_skips_cleanly(self):
        class NotConfigured(FakeProvider):
            def status(self, env=None):
                return {"configured": False}
        provider = NotConfigured([])
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                       processed_store=processed, provider=provider)
        self.assertEqual(report["skipped"], "not configured")

    def test_a_failed_fetch_writes_an_error_row_not_a_marker(self):
        listed = [_event("g1")]
        provider = FakeProvider(listed, fail={"g1": "boom"})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW, store=raw,
                                       processed_store=processed, provider=provider)
            rows = batter_props.read(raw)
        self.assertTrue(any(r.get("error") for r in rows))
        self.assertFalse(any(r.get("poll") for r in rows))
        self.assertEqual(report["errors"], ["g1: boom"])


class EnabledSwitchTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(batter_props.enabled(env={}))

    def test_on_when_set(self):
        self.assertTrue(batter_props.enabled(env={"BATTER_PROPS": "1"}))


if __name__ == "__main__":
    unittest.main()
