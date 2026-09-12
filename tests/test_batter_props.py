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

# Ninety minutes after NOW, i.e. INSIDE batter_props.CAPTURE_LEAD_MINUTES.
#
# The default used to be NOW itself -- a game whose first pitch is this
# instant. That was fine while the pass captured every game the first time it
# saw one, and stopped being fine on 2026-09-11 when capture was anchored to
# first pitch: a game already starting is correctly worth no credits, so
# every fixture silently fell outside the window and four tests went red.
# They were right to. The fixture now describes a game that is genuinely
# about to be played, which is what these tests were always about.
SOON = NOW + dt.timedelta(minutes=90)


def _event(identifier, commence=SOON, home="Atlanta Braves", away="San Francisco Giants"):
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
        `capture_spent_today()` -- a band-scoped read of `credit_log_store`
        -- whenever a caller doesn't pass `spent` directly. `batter_props.run`
        passes no `spent=` at all for either family, relying on `can_spend`'s
        own default: the non-droppable floor family is exempt from the
        envelope by contract regardless, and `batter_props_extra` must derive
        its spend from `credit_log_store`'s own LIVE_CAPTURE-band rows, never
        from whatever data/processed/credit_log.jsonl happens to hold today
        (nor, per the 2026-09-04 SECOND-round break this pin was updated for,
        from that store's UNBANDED total either -- a same-day
        historical_backfill/probe row in the same store must not count).
        Two runs against the SAME fake provider (`remaining` fixed, so the
        floor check never fires) differing only in the injected store's own
        LIVE_CAPTURE-band spend must reach opposite envelope decisions for
        the extra family -- proving the decision tracks the seam's own band,
        not ambient state and not the store's unbanded total.
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

            # A store whose own rows show today's LIVE_CAPTURE-band spend
            # already at DAILY_ENVELOPE (the exact shape of 2026-09-04's
            # real log, once explicitly banded): the SAME provider, SAME
            # `remaining`, must now refuse the extra family on "daily
            # envelope". `budget_band` is explicit on both rows -- exactly
            # how every live write site logs today, per
            # `creditlog.log`'s `budget_band` contract -- so this cannot be
            # satisfied by the unbanded total; only a LIVE_CAPTURE-scoped
            # read blocks it.
            loud_store = Path(folder) / "loud_credit_log.jsonl"
            rows = [
                {"utc": today_utc.replace(microsecond=0).isoformat()
                        .replace("+00:00", "Z"),
                 "credits_remaining": 100000, "credits_used_last": 0,
                 "caller": "batter_props.run", "budget_band": "live_capture"},
                {"utc": (today_utc + dt.timedelta(minutes=1))
                        .replace(microsecond=0).isoformat()
                        .replace("+00:00", "Z"),
                 "credits_remaining": 100000 - budget.DAILY_ENVELOPE,
                 "credits_used_last": 0, "caller": "batter_props.run",
                 "budget_band": "live_capture"},
            ]
            loud_store.write_text(
                "\n".join(__import__("json").dumps(r) for r in rows) + "\n",
                encoding="utf-8")
            self.assertEqual(
                extra_fetch_ids(loud_store), set(),
                "extra family must refuse to spend once the injected "
                "store's own LIVE_CAPTURE-band rows show the envelope "
                "already exhausted")

            # The 2026-09-04 second-round regression itself: an UNBANDED
            # total at the exact same magnitude, logged under a different
            # band entirely (historical_backfill), must NOT block the
            # extra family -- this is the case a bare, unbanded
            # `spent_today()` read gets wrong.
            historical_store = Path(folder) / "historical_credit_log.jsonl"
            historical_rows = [
                {"utc": today_utc.replace(microsecond=0).isoformat()
                        .replace("+00:00", "Z"),
                 "credits_remaining": 100000, "credits_used_last": 0,
                 "caller": "backfill_script",
                 "budget_band": "historical_backfill"},
                {"utc": (today_utc + dt.timedelta(minutes=1))
                        .replace(microsecond=0).isoformat()
                        .replace("+00:00", "Z"),
                 "credits_remaining": 100000 - budget.DAILY_ENVELOPE - 1,
                 "credits_used_last": 0, "caller": "backfill_script",
                 "budget_band": "historical_backfill"},
            ]
            historical_store.write_text(
                "\n".join(__import__("json").dumps(r)
                          for r in historical_rows) + "\n",
                encoding="utf-8")
            self.assertTrue(
                extra_fetch_ids(historical_store),
                "extra family must still fetch when the injected store's "
                "only over-envelope spend is logged under a different "
                "band (historical_backfill), not live_capture")

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


class CaptureWindowTests(unittest.TestCase):
    """Capture is anchored to first pitch, not to whenever a run first looks.

    Until 2026-09-11 each game was captured the first time any run saw it.
    Since `_done_today` then blocks every later run that day, and
    forward_capture.sh runs every fifteen minutes, the whole slate was priced
    the moment the Eastern date rolled over: all 9,672 quotes in the store
    landed between 04:00 and 09:10 UTC, a median 17.3 hours before first
    pitch, and not one of 77 games had a quote on both sides of its own
    lineup posting -- the moment that actually sets a batter's plate
    appearances.
    """

    def test_a_game_inside_the_window_is_due(self):
        event = _event("g1", commence=NOW + dt.timedelta(minutes=90))
        self.assertTrue(batter_props._in_capture_window(event, NOW))

    def test_a_game_still_hours_away_is_not_due_yet(self):
        """The defect, stated as a test: 17 hours out is not the moment."""
        event = _event("g1", commence=NOW + dt.timedelta(hours=17))
        self.assertFalse(batter_props._in_capture_window(event, NOW))

    def test_a_game_already_started_is_never_due(self):
        """A price after first pitch is not a pregame price."""
        event = _event("g1", commence=NOW - dt.timedelta(minutes=1))
        self.assertFalse(batter_props._in_capture_window(event, NOW))

    def test_the_boundary_is_inclusive_at_the_lead_and_open_at_zero(self):
        lead = batter_props.CAPTURE_LEAD_MINUTES
        at_lead = _event("g1", commence=NOW + dt.timedelta(minutes=lead))
        past_lead = _event("g2", commence=NOW + dt.timedelta(minutes=lead + 1))
        at_zero = _event("g3", commence=NOW)
        self.assertTrue(batter_props._in_capture_window(at_lead, NOW))
        self.assertFalse(batter_props._in_capture_window(past_lead, NOW))
        self.assertFalse(batter_props._in_capture_window(at_zero, NOW))

    def test_an_unreadable_commence_time_does_not_block_capture(self):
        """Fail toward capturing, not toward a silent coverage hole.

        A clock bug that made every game look 'not yet due' would stop the
        surface entirely and report a clean run while doing it -- the exact
        shape of failure this repo keeps finding.
        """
        self.assertTrue(batter_props._in_capture_window(
            {"commence_time": "not a timestamp"}, NOW))
        self.assertTrue(batter_props._in_capture_window({}, NOW))

    def test_the_window_lands_after_lineups_post(self):
        """Lineups post a median 2.92h before first pitch (p10 1.84h).

        The window has to open later than that or it reprices the board
        before the information it exists to catch has arrived.
        """
        self.assertLessEqual(batter_props.CAPTURE_LEAD_MINUTES, 120)

    def test_a_run_before_the_window_fetches_nothing_and_says_why(self):
        # Eleven hours, not seventeen: NOW is 08:00 Eastern, so a game
        # seventeen hours out belongs to TOMORROW's slate and would be
        # skipped for an entirely different reason ("no games on today's
        # slate"), making this test pass without exercising the window at
        # all. Eleven hours is a 7pm Eastern game seen at breakfast -- the
        # real case this gate exists for.
        listed = [_event(f"g{i}", commence=NOW + dt.timedelta(hours=11))
                  for i in range(1, 8)]
        provider = FakeProvider(listed, {})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(
                credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                store=raw, processed_store=processed, provider=provider)
        self.assertEqual(provider.fetched, [])
        self.assertIsNone(report.get("skipped"),
                          "skipped for some other reason, so the window was "
                          "never exercised")
        self.assertGreater(report.get("games_outside_window", 0), 0)


class BaselineWindowTests(unittest.TestCase):
    """Unit tests for `_in_baseline_window`/`_capture_phase` in isolation --
    owner decision 2026-09-12, docs/DECISION_PROP_CAPTURE_SPEND.md."""

    def test_a_game_six_hours_out_is_in_the_baseline_window(self):
        event = _event("g1", commence=NOW + dt.timedelta(hours=6))
        self.assertTrue(batter_props._in_baseline_window(event, NOW))
        self.assertEqual(batter_props._capture_phase(event, NOW), "baseline")

    def test_the_baseline_boundary_is_inclusive_at_both_ends(self):
        at_min = _event("g1", commence=NOW + dt.timedelta(
            minutes=batter_props.BASELINE_LEAD_MIN_MINUTES))
        at_max = _event("g2", commence=NOW + dt.timedelta(
            minutes=batter_props.BASELINE_LEAD_MAX_MINUTES))
        just_under = _event("g3", commence=NOW + dt.timedelta(
            minutes=batter_props.BASELINE_LEAD_MIN_MINUTES - 1))
        just_over = _event("g4", commence=NOW + dt.timedelta(
            minutes=batter_props.BASELINE_LEAD_MAX_MINUTES + 1))
        self.assertTrue(batter_props._in_baseline_window(at_min, NOW))
        self.assertTrue(batter_props._in_baseline_window(at_max, NOW))
        self.assertFalse(batter_props._in_baseline_window(just_under, NOW))
        self.assertFalse(batter_props._in_baseline_window(just_over, NOW))

    def test_the_two_windows_never_overlap(self):
        """A defect here would let the same instant bill under both phase
        labels -- see BASELINE_LEAD_MIN_MINUTES's own module docstring."""
        self.assertGreater(batter_props.BASELINE_LEAD_MIN_MINUTES,
                            batter_props.CAPTURE_LEAD_MINUTES)

    def test_capture_phase_is_gate_inside_the_gate_window(self):
        event = _event("g1", commence=NOW + dt.timedelta(minutes=90))
        self.assertEqual(batter_props._capture_phase(event, NOW), "gate")

    def test_capture_phase_is_none_in_the_dead_zone_between_windows(self):
        event = _event("g1", commence=NOW + dt.timedelta(minutes=200))
        self.assertIsNone(batter_props._capture_phase(event, NOW))

    def test_capture_phase_is_none_once_first_pitch_has_passed(self):
        event = _event("g1", commence=NOW - dt.timedelta(minutes=1))
        self.assertIsNone(batter_props._capture_phase(event, NOW))

    def test_an_unreadable_commence_time_fails_open_to_gate_not_baseline(self):
        junk = {"commence_time": "not a timestamp"}
        self.assertFalse(batter_props._in_baseline_window(junk, NOW))
        self.assertEqual(batter_props._capture_phase(junk, NOW), "gate")


class BaselinePassTests(unittest.TestCase):
    """Integration tests for the two-phase capture (owner decision
    2026-09-12): a game may be captured once baseline (pre-lineup, 5-7h out)
    and once gate (post-lineup, 0-2h out) per slate date -- never a third
    time in either phase."""

    def test_a_game_six_hours_out_is_captured_in_the_baseline_window(self):
        event = _event("g1", commence=NOW + dt.timedelta(hours=6))
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                       now=NOW, store=raw, processed_store=processed,
                                       provider=provider)
            rows = batter_props.read_processed(processed)
        self.assertEqual(provider.fetched, [("g1", tuple(batter_props.MARKETS))])
        self.assertEqual(report["fetches_by_phase"], {"baseline": 1})
        self.assertTrue(rows)
        self.assertTrue(all(r["capture_phase"] == "baseline" for r in rows))

    def test_not_captured_twice_within_the_same_baseline_window(self):
        """The mission's own "not again until inside 2h" case, pinned for
        real (2026-09-12, checker finding): the dead-zone test below only
        exercises WINDOW logic -- `_capture_phase` returns None between the
        two windows regardless of done-ness, so it stayed green even under
        a mutation that broke `_done_today`'s "baseline" bucket entirely.
        This test instead runs TWICE while `now` stays inside the SAME
        baseline window (still `_capture_phase`=="baseline" both times), so
        only `_done_today` can be the thing stopping the second fetch. The
        baseline window is 120 minutes wide and forward_capture.yml polls
        every 15 minutes -- a broken baseline done-check would refetch on
        most of those polls, roughly 8x/game/night (~15 games x 8 x 6 =
        ~720 credits against the 900/day envelope) while every other test
        in this file stayed green.
        """
        commence = NOW + dt.timedelta(hours=6)  # 360 minutes out at NOW
        event = _event("g1", commence=commence)
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            first = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                      now=NOW, store=raw, processed_store=processed,
                                      provider=provider)
            # 20 minutes later: 340 minutes out, still inside the baseline
            # window (300-420) -- `_capture_phase` returns "baseline" again,
            # exactly as it did for the first run.
            second_now = NOW + dt.timedelta(minutes=20)
            self.assertEqual(batter_props._capture_phase(event, second_now), "baseline")
            second = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                       now=second_now, store=raw,
                                       processed_store=processed, provider=provider)
        self.assertEqual(first["fetches_by_phase"], {"baseline": 1})
        self.assertEqual(len(provider.fetched), 1,
                          "second run inside the same baseline window must not refetch")
        self.assertEqual(second.get("fetches_by_phase"), {},
                          "baseline done-ness must block the second run, not just the window")

    def test_not_captured_again_in_the_dead_zone_between_windows(self):
        commence = NOW + dt.timedelta(hours=6)
        event = _event("g1", commence=commence)
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                              store=raw, processed_store=processed, provider=provider)
            # 200 minutes before first pitch: past the gate window's 120m
            # edge, short of the baseline window's 300m edge -- the dead
            # zone between the two passes.
            dead_zone_now = commence - dt.timedelta(minutes=200)
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                       now=dead_zone_now, store=raw,
                                       processed_store=processed, provider=provider)
        self.assertEqual(len(provider.fetched), 1, "no second fetch in the dead zone")
        self.assertEqual(report.get("fetches_by_phase"), {})

    def test_after_baseline_a_gate_run_captures_once_more(self):
        """The book's price moves between the two passes (it is 6 hours
        later and the lineup has posted), so `last_update` differs and both
        captures land as distinct L2 rows -- not merely distinct markers."""
        commence = NOW + dt.timedelta(hours=6)
        event = _event("g1", commence=commence)

        class _MovingPriceProvider(FakeProvider):
            def fetch_event_odds_with_usage(self, event_id, markets=None, env=None):
                self.fetched.append((event_id, tuple(markets or ())))
                last_update = ("2026-09-03T11:00:00Z" if len(self.fetched) == 1
                                else "2026-09-03T17:00:00Z")
                payload = _payload(event_id, last_update=last_update)
                used = self.remaining - self.billed if self.remaining is not None else None
                self.remaining = used
                return payload, {"remaining": used, "used": 1, "last": self.billed}

        provider = _MovingPriceProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            first = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                      now=NOW, store=raw, processed_store=processed,
                                      provider=provider)
            gate_now = commence - dt.timedelta(minutes=90)  # inside the gate window
            second = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                       now=gate_now, store=raw,
                                       processed_store=processed, provider=provider)
            rows = batter_props.read_processed(processed)
        self.assertEqual(first["fetches_by_phase"], {"baseline": 1})
        self.assertEqual(second["fetches_by_phase"], {"gate": 1})
        self.assertEqual(len(provider.fetched), 2)
        self.assertEqual({r["capture_phase"] for r in rows}, {"baseline", "gate"})

    def test_never_a_third_capture_for_the_same_game_same_date(self):
        commence = NOW + dt.timedelta(hours=6)
        event = _event("g1", commence=commence)
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                              store=raw, processed_store=processed, provider=provider)
            gate_now = commence - dt.timedelta(minutes=90)
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                              now=gate_now, store=raw, processed_store=processed,
                              provider=provider)
            # Still inside the gate window, on the same slate date, after
            # the gate phase was already captured once.
            third_now = commence - dt.timedelta(minutes=30)
            third = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                      now=third_now, store=raw,
                                      processed_store=processed, provider=provider)
        self.assertEqual(len(provider.fetched), 2, "no third fetch for the same game/date")
        self.assertEqual(third.get("fetches_by_phase"), {})

    def test_a_game_first_seen_inside_the_gate_window_gets_only_gate(self):
        """No baseline is fabricated after the fact for a game only ever
        observed close to first pitch -- baseline is a bonus second look,
        never a precondition for the gate capture."""
        commence = NOW + dt.timedelta(minutes=90)
        event = _event("g1", commence=commence)
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                       now=NOW, store=raw, processed_store=processed,
                                       provider=provider)
            rows = batter_props.read_processed(processed)
        self.assertEqual(report["fetches_by_phase"], {"gate": 1})
        self.assertTrue(rows)
        self.assertTrue(all(r["capture_phase"] == "gate" for r in rows))
        self.assertEqual(len(provider.fetched), 1)

    def test_rows_carry_capture_phase_on_marker_and_projection_alike(self):
        event = _event("g1", commence=NOW + dt.timedelta(hours=6))
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                              store=raw, processed_store=processed, provider=provider)
            markers = [r for r in batter_props.read(raw) if r.get("poll")]
            rows = batter_props.read_processed(processed)
        self.assertTrue(markers)
        self.assertTrue(all(m.get("capture_phase") == "baseline" for m in markers))
        self.assertTrue(rows)
        self.assertTrue(all(r.get("capture_phase") == "baseline" for r in rows))

    def test_the_report_counts_both_phases_in_a_single_run(self):
        """A mixed slate -- one game baseline-due, another gate-due -- in
        the SAME run must show up under both phase keys, not just whichever
        the loop happened to process last."""
        baseline_event = _event("g1", commence=NOW + dt.timedelta(hours=6))
        gate_event = _event("g2", commence=NOW + dt.timedelta(minutes=90))
        listed = [baseline_event, gate_event]
        payloads = {
            "g1": _payload("g1", books=("draftkings",),
                           players=(("p1", "Player One"),)),
            "g2": _payload("g2", books=("draftkings",),
                           players=(("p2", "Player Two"),)),
        }
        provider = FakeProvider(listed, payloads)
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            report = batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={},
                                       now=NOW, store=raw, processed_store=processed,
                                       provider=provider)
        self.assertEqual(report["fetches_by_phase"], {"baseline": 1, "gate": 1})


class EnabledSwitchTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(batter_props.enabled(env={}))

    def test_on_when_set(self):
        self.assertTrue(batter_props.enabled(env={"BATTER_PROPS": "1"}))


class StolenBasesFlagTests(unittest.TestCase):
    """STOLEN_BASES=1 (docs/DECISION_PROP_CAPTURE_SPEND.md, 2026-09-12):
    off by default, and the flag is what the probe-then-capture rule
    depends on -- scripts/probe_stolen_bases.py is the "probe", this flag
    is the "then-capture"."""

    def test_off_by_default(self):
        self.assertFalse(batter_props._stolen_bases_enabled(env={}))

    def test_on_when_set(self):
        self.assertTrue(batter_props._stolen_bases_enabled(env={"STOLEN_BASES": "1"}))

    def test_capture_markets_excludes_stolen_bases_by_default(self):
        self.assertEqual(batter_props._capture_markets(env={}), batter_props.MARKETS)

    def test_capture_markets_includes_stolen_bases_when_enabled(self):
        markets = batter_props._capture_markets(env={"STOLEN_BASES": "1"})
        self.assertIn("batter_stolen_bases", markets)
        self.assertEqual(len(markets), len(batter_props.MARKETS) + 1)

    def test_run_requests_only_the_six_markets_by_default(self):
        event = _event("g1")
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                              store=raw, processed_store=processed, provider=provider)
        self.assertEqual(provider.fetched[0][1], tuple(batter_props.MARKETS))

    def test_run_requests_seven_markets_when_stolen_bases_enabled(self):
        event = _event("g1")
        provider = FakeProvider([event], {"g1": _payload("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE,
                              env={"STOLEN_BASES": "1"}, now=NOW, store=raw,
                              processed_store=processed, provider=provider)
        self.assertEqual(provider.fetched[0][1],
                          tuple(batter_props.MARKETS) + ("batter_stolen_bases",))

    def test_stolen_bases_rows_are_projected_only_when_the_flag_is_on(self):
        """A payload that happens to echo a stolen-bases outcome is kept
        only when the flag turned the request on -- the market filter inside
        `_project` is what actually gates the L2 write, not merely the shape
        of the request."""
        def payload_with_steals(event_id):
            base = _payload(event_id, books=("draftkings",),
                             players=(("p1", "Player One"),))
            base["bookmakers"][0]["markets"].append({
                "key": "batter_stolen_bases",
                "last_update": "2026-09-03T11:00:00Z",
                "outcomes": [
                    {"name": "Over", "description": "Player One",
                     "participant_id": "p1", "price": 120, "point": 0.5},
                    {"name": "Under", "description": "Player One",
                     "participant_id": "p1", "price": -150, "point": 0.5},
                ],
            })
            return base

        event = _event("g1")
        provider_off = FakeProvider([event], {"g1": payload_with_steals("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, env={}, now=NOW,
                              store=raw, processed_store=processed, provider=provider_off)
            off_rows = batter_props.read_processed(processed)
        self.assertFalse(any(r["market"] == "batter_stolen_bases" for r in off_rows))

        provider_on = FakeProvider([event], {"g1": payload_with_steals("g1")})
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / "raw.jsonl"
            processed = Path(folder) / "processed.jsonl"
            batter_props.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE,
                              env={"STOLEN_BASES": "1"}, now=NOW, store=raw,
                              processed_store=processed, provider=provider_on)
            on_rows = batter_props.read_processed(processed)
        self.assertTrue(any(r["market"] == "batter_stolen_bases" for r in on_rows))
        self.assertTrue(all(r.get("capture_phase") for r in on_rows))


if __name__ == "__main__":
    unittest.main()
