"""Tests for the T-2h F5 snapshot-timing repair (src/pipeline/f5_tminus2.py).

docs/PREREG_F5_SNAPSHOT_RULE.md froze the rule this module implements; these
tests pin the compliance predicate (+/-5min grid tolerance, pregame, >=5
books) and the unavailable path (every named game gets a row, never
silently dropped). No test here touches the real historical stores or the
live provider -- every fetch is injected.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.pipeline import f5_tminus2 as t2


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


SCHEDULED = datetime(2024, 6, 15, 23, 10, tzinfo=timezone.utc)
TARGET = SCHEDULED - timedelta(hours=2)  # 21:10Z


def make_books(n, market=t2.MONEYLINE_MARKET, priced=True):
    books = []
    for i in range(n):
        outcomes = ([{"name": "Away Team", "price": 120},
                    {"name": "Home Team", "price": -140}] if priced else [])
        books.append({
            "key": f"book{i}",
            "last_update": iso(TARGET),
            "markets": [{"key": market, "last_update": iso(TARGET),
                        "outcomes": outcomes}],
        })
    return books


class TestTargetInstant(unittest.TestCase):

    def test_target_is_exactly_two_hours_before_scheduled(self):
        self.assertEqual(t2.target_instant(iso(SCHEDULED)), TARGET)

    def test_never_uses_actual_first_pitch(self):
        # target_instant takes only the value it is given -- there is no
        # second "actual" parameter it could fall back to.
        import inspect
        sig = inspect.signature(t2.target_instant)
        self.assertEqual(list(sig.parameters), ["scheduled_first_pitch"])

    def test_missing_anchor_raises_rather_than_guessing(self):
        with self.assertRaises(t2.TimingRuleError):
            t2.target_instant(None)


class TestDeviation(unittest.TestCase):

    def test_exact_match_is_zero_deviation(self):
        self.assertEqual(t2.deviation_minutes(TARGET, iso(TARGET)), 0.0)

    def test_five_minutes_late_is_five(self):
        snap = TARGET + timedelta(minutes=5)
        self.assertAlmostEqual(t2.deviation_minutes(TARGET, iso(snap)), 5.0)

    def test_five_minutes_early_is_also_five(self):
        snap = TARGET - timedelta(minutes=5)
        self.assertAlmostEqual(t2.deviation_minutes(TARGET, iso(snap)), 5.0)

    def test_missing_snapshot_is_none(self):
        self.assertIsNone(t2.deviation_minutes(TARGET, None))


class TestBookCount(unittest.TestCase):

    def test_counts_books_with_priced_outcomes(self):
        data = {"bookmakers": make_books(6)}
        self.assertEqual(t2.book_count(data), 6)

    def test_a_duplicated_book_key_counts_once(self):
        books = make_books(3)
        books.append(dict(books[0]))  # same key as an existing book
        self.assertEqual(t2.book_count({"bookmakers": books}), 3)

    def test_a_market_key_with_no_outcomes_does_not_count(self):
        data = {"bookmakers": make_books(3, priced=False)}
        self.assertEqual(t2.book_count(data), 0)

    def test_ignores_other_markets(self):
        data = {"bookmakers": make_books(4, market="totals_1st_5_innings")}
        self.assertEqual(t2.book_count(data), 0)

    def test_no_bookmakers_is_zero(self):
        self.assertEqual(t2.book_count({}), 0)


class TestClassify(unittest.TestCase):

    def _classify(self, snapshot_offset_minutes=0, book_n=6, pregame=True):
        snap = TARGET + timedelta(minutes=snapshot_offset_minutes)
        sched = SCHEDULED if pregame else snap - timedelta(minutes=1)
        return t2.classify(scheduled_first_pitch=iso(sched), query_target=TARGET,
                           snapshot_at=iso(snap), valid_book_count=book_n)

    def test_within_tolerance_pregame_enough_books_is_ok(self):
        status, reason = self._classify(snapshot_offset_minutes=3, book_n=5)
        self.assertEqual(status, "OK")
        self.assertIsNone(reason)

    def test_exactly_five_books_is_the_floor_not_the_cutoff(self):
        status, _ = self._classify(book_n=5)
        self.assertEqual(status, "OK")

    def test_four_books_fails(self):
        status, reason = self._classify(book_n=4)
        self.assertEqual(status, "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(reason, "fewer_than_5_books")

    def test_six_minutes_off_grid_fails(self):
        status, reason = self._classify(snapshot_offset_minutes=6)
        self.assertEqual(status, "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(reason, "no_grid_point_within_tolerance")

    def test_exactly_five_minutes_off_is_still_tolerance(self):
        status, _ = self._classify(snapshot_offset_minutes=5)
        self.assertEqual(status, "OK")

    def test_five_minutes_early_is_also_within_tolerance(self):
        status, _ = self._classify(snapshot_offset_minutes=-5)
        self.assertEqual(status, "OK")

    def test_postgame_snapshot_fails_even_if_deviation_and_books_are_fine(self):
        status, reason = self._classify(pregame=False)
        self.assertEqual(status, "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(reason, "not_pregame")

    def test_no_snapshot_at_all_fails_on_grid_not_books(self):
        status, reason = t2.classify(scheduled_first_pitch=iso(SCHEDULED),
                                     query_target=TARGET, snapshot_at=None,
                                     valid_book_count=0)
        self.assertEqual(status, "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(reason, "no_grid_point_within_tolerance")

    def test_never_slides_the_target_to_a_convenient_time(self):
        # A snapshot 3 hours off target is not silently accepted as "the
        # nearest one available" -- it fails on grid tolerance, hard.
        status, reason = self._classify(snapshot_offset_minutes=180)
        self.assertEqual(status, "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(reason, "no_grid_point_within_tolerance")


class TestManifestNeverBuysTwice(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_a_game_already_in_the_manifest_is_skipped_and_costs_nothing(self):
        manifest = t2.read_manifest(self.store)
        manifest["games"]["999"] = {"status": "OK", "reason": None}
        t2.write_manifest(manifest, self.store)

        calls = []

        def events_fetch(instant, timeout=30):
            calls.append(instant)
            return {"data": []}, {"remaining": 100, "last": 1}

        report = t2.run(["999"], schedule={"999": {
            "date": "2024-06-15", "start_time_utc": iso(SCHEDULED),
            "away_team": "SEA", "home_team": "OAK"}},
            store=self.store, events_fetch=events_fetch)

        self.assertEqual(report["skipped_already_attempted"], 1)
        self.assertEqual(report["attempted"], 0)
        self.assertEqual(calls, [])


class TestRunAcquiresAndRecordsMisses(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def schedule_row(self, away="SEA", home="OAK"):
        return {"date": "2024-06-15", "start_time_utc": iso(SCHEDULED),
                "away_team": away, "home_team": home}

    def test_a_game_missing_from_the_schedule_still_gets_a_row(self):
        report = t2.run(["12345"], schedule={}, store=self.store)
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["unavailable"], 1)
        self.assertEqual(report["rows"][0]["status"],
                         "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(report["rows"][0]["reason"],
                         "game_pk_missing_from_schedule")
        # The row landed in F5_RAW_HISTORY even though nothing was bought.
        stored = t2.read_raw_season("unknown", self.store)
        self.assertEqual(len(stored), 1)

    def test_no_matching_event_is_recorded_not_dropped(self):
        def events_fetch(instant, timeout=30):
            return {"data": []}, {"remaining": 999, "last": 1}

        report = t2.run(["1"], schedule={"1": self.schedule_row()},
                        store=self.store, events_fetch=events_fetch)
        self.assertEqual(report["unavailable"], 1)
        self.assertEqual(report["rows"][0]["reason"], "no_matching_event")
        self.assertEqual(report["credits_spent"], 1)

    def test_a_compliant_snapshot_is_tagged_and_stored_ok(self):
        def events_fetch(instant, timeout=30):
            return ({"data": [{"id": "evt1", "away_team": "Seattle Mariners",
                              "home_team": "Oakland Athletics",
                              "commence_time": iso(SCHEDULED)}]},
                    {"remaining": 999, "last": 1})

        def odds_fetch(instant, event_id, timeout=30):
            data = {"id": event_id, "away_team": "Seattle Mariners",
                    "home_team": "Oakland Athletics",
                    "commence_time": iso(SCHEDULED),
                    "bookmakers": make_books(5)}
            return ({"timestamp": iso(TARGET), "data": data},
                    {"remaining": 989, "last": 10})

        report = t2.run(["1"], schedule={"1": self.schedule_row()},
                        store=self.store, events_fetch=events_fetch,
                        odds_fetch=odds_fetch)
        self.assertEqual(report["ok"], 1)
        row = report["rows"][0]
        self.assertEqual(row["status"], "OK")
        self.assertEqual(row["snapshot_rule"], "tminus2_v1")
        self.assertEqual(row["book_count"], 5)
        self.assertEqual(report["credits_spent"], 11)

        stored = t2.read_raw_season(2024, self.store)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["status"], "OK")

    def test_thin_book_snapshot_is_unavailable_with_reason(self):
        def events_fetch(instant, timeout=30):
            return ({"data": [{"id": "evt1", "away_team": "Seattle Mariners",
                              "home_team": "Oakland Athletics",
                              "commence_time": iso(SCHEDULED)}]},
                    {"remaining": 999, "last": 1})

        def odds_fetch(instant, event_id, timeout=30):
            data = {"id": event_id, "away_team": "Seattle Mariners",
                    "home_team": "Oakland Athletics",
                    "commence_time": iso(SCHEDULED),
                    "bookmakers": make_books(2)}
            return ({"timestamp": iso(TARGET), "data": data},
                    {"remaining": 989, "last": 10})

        report = t2.run(["1"], schedule={"1": self.schedule_row()},
                        store=self.store, events_fetch=events_fetch,
                        odds_fetch=odds_fetch)
        self.assertEqual(report["unavailable"], 1)
        self.assertEqual(report["rows"][0]["reason"], "fewer_than_5_books")

    def test_existing_raw_history_files_are_never_truncated(self):
        legacy_path = t2._season_file(self.store, 2024)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            json.dumps({"game_pk": "old", "legacy": True}) + "\n",
            encoding="utf-8")

        t2.run(["12345"], schedule={}, store=self.store)

        legacy_rows = t2.read_raw_season(2024, self.store)
        self.assertEqual(len(legacy_rows), 1)
        self.assertTrue(legacy_rows[0].get("legacy"))
        # The unavailable row for the missed game lands in its own file
        # (no date to key it by) without disturbing the legacy file at all.
        miss_rows = t2.read_raw_season("unknown", self.store)
        self.assertEqual(len(miss_rows), 1)

    def test_markets_unavailable_at_date_is_terminal_and_zero_cost(self):
        # A negative control: a date before the market's own archive begins
        # 422s forever. Confirmed zero-cost live (src/providers/odds.py);
        # this proves the acquisition path records it as an explicit,
        # non-retried miss rather than crashing or looping.
        from src.providers import odds as odds_provider

        calls = {"events": 0}

        def events_fetch(instant, timeout=30):
            calls["events"] += 1
            raise odds_provider.MarketsUnavailableAtDate("dead zone")

        report = t2.run(["1"], schedule={"1": self.schedule_row()},
                        store=self.store, events_fetch=events_fetch)
        self.assertEqual(report["unavailable"], 1)
        self.assertEqual(report["rows"][0]["reason"], "markets_unavailable_at_date")
        self.assertEqual(report["credits_spent"], 0)

        # Never retried on a resumed run -- and never bills the events call
        # again either, because the manifest already marked it attempted.
        t2.run(["1"], schedule={"1": self.schedule_row()},
              store=self.store, events_fetch=events_fetch)
        self.assertEqual(calls["events"], 1)

    def test_never_rebuys_a_target_already_attempted(self):
        calls = {"n": 0}

        def events_fetch(instant, timeout=30):
            calls["n"] += 1
            return {"data": []}, {"remaining": 999, "last": 1}

        row_sched = {"1": self.schedule_row()}
        t2.run(["1"], schedule=row_sched, store=self.store,
              events_fetch=events_fetch)
        t2.run(["1"], schedule=row_sched, store=self.store,
              events_fetch=events_fetch)
        self.assertEqual(calls["n"], 1)


class TestJoinEdgeCases(unittest.TestCase):
    """Zero-cost fixture proofs for two join bugs check 6 of
    docs/F5_REPAIR_RELEASE_GATE.md names by name: the AZ/ARI abbreviation
    split and doubleheader game_pk collisions. Not exercised against the
    live API in the credit-constrained sanity tranche -- these are the
    same injected-fetch pattern the rest of this module's tests use, and
    the ~4,290-game full run will exercise both for real."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_az_spelling_still_matches_the_ari_event(self):
        # mlb_results.csv spells the Diamondbacks "AZ"; the odds feed's full
        # name resolves to "ARI". Without canonicalization this game is
        # permanently unmatched even though the event is right there.
        def events_fetch(instant, timeout=30):
            return ({"data": [{"id": "evt-az", "away_team": "Arizona Diamondbacks",
                              "home_team": "Los Angeles Dodgers",
                              "commence_time": iso(SCHEDULED)}]},
                    {"remaining": 999, "last": 1})

        def odds_fetch(instant, event_id, timeout=30):
            data = {"id": event_id, "away_team": "Arizona Diamondbacks",
                    "home_team": "Los Angeles Dodgers",
                    "commence_time": iso(SCHEDULED), "bookmakers": make_books(5)}
            return {"timestamp": iso(TARGET), "data": data}, {"remaining": 989, "last": 10}

        schedule = {"1": {"date": "2024-06-15", "start_time_utc": iso(SCHEDULED),
                          "away_team": "AZ", "home_team": "LAD"}}
        report = t2.run(["1"], schedule=schedule, store=self.store,
                        events_fetch=events_fetch, odds_fetch=odds_fetch)
        self.assertEqual(report["ok"], 1)
        self.assertEqual(report["rows"][0]["away_team"], "ARI")

    def test_a_doubleheaders_two_legs_never_collide_on_the_manifest(self):
        # Same team pair, same date, different game_pk -- the manifest is
        # keyed by game_pk, so the second leg is neither skipped as already
        # done nor silently merged into the first.
        def events_fetch(instant, timeout=30):
            return ({"data": [{"id": f"evt-{instant}", "away_team": "Philadelphia Phillies",
                              "home_team": "Chicago White Sox",
                              "commence_time": iso(SCHEDULED)}]},
                    {"remaining": 999, "last": 1})

        def odds_fetch(instant, event_id, timeout=30):
            # Echo the requested instant back as the served snapshot -- each
            # leg has its own scheduled start and therefore its own T-2h
            # target, so the fixture must track that rather than assume one
            # fixed TARGET shared by both legs.
            data = {"id": event_id, "away_team": "Philadelphia Phillies",
                    "home_team": "Chicago White Sox",
                    "commence_time": iso(SCHEDULED), "bookmakers": make_books(5)}
            return {"timestamp": instant, "data": data}, {"remaining": 989, "last": 10}

        schedule = {
            "leg1": {"date": "2024-06-15", "start_time_utc": iso(SCHEDULED),
                    "away_team": "PHI", "home_team": "CWS"},
            "leg2": {"date": "2024-06-15",
                    "start_time_utc": iso(SCHEDULED + timedelta(hours=4)),
                    "away_team": "PHI", "home_team": "CWS"},
        }
        report = t2.run(["leg1", "leg2"], schedule=schedule, store=self.store,
                        events_fetch=events_fetch, odds_fetch=odds_fetch)
        self.assertEqual(report["ok"], 2)
        self.assertEqual(report["skipped_already_attempted"], 0)
        manifest = t2.read_manifest(self.store)
        self.assertIn("leg1", manifest["games"])
        self.assertIn("leg2", manifest["games"])


class TestPrimaryViewIsDerivedNotAcquired(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_only_tminus2_rows_enter_the_primary_view(self):
        legacy_path = t2._season_file(self.store, 2024)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        with legacy_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"game_pk": "old", "date": "2024-06-01"}) + "\n")

        ok_row = {"game_pk": "1", "date": "2024-06-15",
                 "away_team": "SEA", "home_team": "OAK",
                 "scheduled_first_pitch": iso(SCHEDULED),
                 "actual_first_pitch": None, "query_instant": iso(TARGET),
                 "snapshot_at": iso(TARGET), "lead_time_hours": 2.0,
                 "book_count": 5,
                 "data": {"away_team": "Seattle Mariners",
                          "home_team": "Oakland Athletics",
                          "bookmakers": make_books(5)},
                 "status": "OK", "reason": None, "snapshot_rule": "tminus2_v1",
                 "markets": ["h2h_1st_5_innings"]}
        t2.append_raw_row(ok_row, self.store)

        unavailable_row = dict(ok_row)
        unavailable_row.update({"game_pk": "2", "status":
                                "PRIMARY_SNAPSHOT_UNAVAILABLE",
                                "reason": "fewer_than_5_books", "data": None})
        t2.append_raw_row(unavailable_row, self.store)

        rows = t2.build_primary_view([2024], self.store)
        pks = {r["game_pk"] for r in rows}
        self.assertEqual(pks, {"1", "2"})
        self.assertNotIn("old", pks)

        ok_view = next(r for r in rows if r["game_pk"] == "1")
        self.assertEqual(len(ok_view["books"]), 5)
        unavailable_view = next(r for r in rows if r["game_pk"] == "2")
        self.assertEqual(unavailable_view["books"], [])
        self.assertEqual(unavailable_view["status"], "PRIMARY_SNAPSHOT_UNAVAILABLE")

    def test_denominator_includes_unavailable_games_not_just_priced_ones(self):
        # A PRIMARY_SNAPSHOT_UNAVAILABLE game must still be counted -- silent
        # survivorship in the denominator is the failure mode this view
        # exists to prevent.
        row = {"game_pk": "3", "date": "2024-06-15", "away_team": "SEA",
              "home_team": "OAK", "scheduled_first_pitch": iso(SCHEDULED),
              "actual_first_pitch": None, "query_instant": iso(TARGET),
              "snapshot_at": None, "lead_time_hours": None, "book_count": 0,
              "data": None, "status": "PRIMARY_SNAPSHOT_UNAVAILABLE",
              "reason": "no_matching_event", "snapshot_rule": "tminus2_v1",
              "markets": ["h2h_1st_5_innings"]}
        t2.append_raw_row(row, self.store)
        rows = t2.build_primary_view([2024], self.store)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "PRIMARY_SNAPSHOT_UNAVAILABLE")


class TestTuningOnlyRowsAreExcludedFromThePrimaryView(unittest.TestCase):
    """The regression test the owner asked for: a 2025 (or 2026, or
    pre-window) raw observation can EXIST in F5_RAW_HISTORY, fully readable,
    while being IMPOSSIBLE to enter the eligible research universe that
    build_primary_view assembles. Both halves are asserted below -- see
    test_present_in_raw_history_but_absent_from_primary_view.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def _row(self, game_pk, date):
        return {"game_pk": game_pk, "date": date,
                "away_team": "SEA", "home_team": "OAK",
                "scheduled_first_pitch": iso(SCHEDULED),
                "actual_first_pitch": None, "query_instant": iso(TARGET),
                "snapshot_at": iso(TARGET), "lead_time_hours": 2.0,
                "book_count": 5,
                "data": {"away_team": "Seattle Mariners",
                         "home_team": "Oakland Athletics",
                         "bookmakers": make_books(5)},
                "status": "OK", "reason": None, "snapshot_rule": "tminus2_v1",
                "markets": ["h2h_1st_5_innings"]}

    def test_present_in_raw_history_but_absent_from_primary_view(self):
        tuning_only_2025 = self._row("pk2025", "2025-08-13")
        t2.append_raw_row(tuning_only_2025, self.store)

        # HALF ONE: the row is present and fully readable in raw history --
        # nothing about eligibility deleted or hid it there.
        raw_2025 = t2.read_raw_season(2025, self.store)
        self.assertEqual(len(raw_2025), 1)
        self.assertEqual(raw_2025[0]["game_pk"], "pk2025")
        self.assertEqual(raw_2025[0]["status"], "OK")  # untouched, not rewritten

        # HALF TWO: it is nonetheless absent from every eligible-universe
        # path -- here, the one and only function that assembles
        # F5_TMINUS2_PRIMARY.
        primary_2025 = t2.build_primary_view([2025], self.store)
        self.assertEqual(primary_2025, [])

    def test_2026_is_excluded_too(self):
        t2.append_raw_row(self._row("pk2026", "2026-05-01"), self.store)
        self.assertEqual(len(t2.read_raw_season(2026, self.store)), 1)
        self.assertEqual(t2.build_primary_view([2026], self.store), [])

    def test_pre_window_2023_rows_are_excluded_by_the_same_window_rule(self):
        # 2023-03-30 and 2023-05-06 in the real sanity tranche: legitimate
        # paid raw data, dated before the approved 2023-05-10 discovery
        # window opens.
        t2.append_raw_row(self._row("pk_pre1", "2023-03-30"), self.store)
        t2.append_raw_row(self._row("pk_pre2", "2023-05-06"), self.store)
        self.assertEqual(len(t2.read_raw_season(2023, self.store)), 2)
        self.assertEqual(t2.build_primary_view([2023], self.store), [])

    def test_in_window_2023_and_2024_rows_still_enter_the_view(self):
        # The boundary must exclude only what it is supposed to -- it must
        # not quietly swallow legitimate in-window rows too.
        t2.append_raw_row(self._row("pk_in1", "2023-05-10"), self.store)  # start, inclusive
        t2.append_raw_row(self._row("pk_in2", "2024-10-07"), self.store)  # end, inclusive
        pks_2023 = {r["game_pk"] for r in t2.build_primary_view([2023], self.store)}
        pks_2024 = {r["game_pk"] for r in t2.build_primary_view([2024], self.store)}
        self.assertEqual(pks_2023, {"pk_in1"})
        self.assertEqual(pks_2024, {"pk_in2"})

    def test_a_mixed_season_file_only_yields_its_eligible_rows(self):
        # 2025 contains both real tuning-only games and (hypothetically) an
        # in-window make-up date would not occur since the year itself is
        # tuning-only-forever -- assert every 2025 row is excluded even when
        # several share the season file with an unrelated status.
        t2.append_raw_row(self._row("a", "2025-04-28"), self.store)
        t2.append_raw_row(self._row("b", "2025-09-22"), self.store)
        self.assertEqual(len(t2.read_raw_season(2025, self.store)), 2)
        self.assertEqual(t2.build_primary_view([2025], self.store), [])


if __name__ == "__main__":
    unittest.main()
