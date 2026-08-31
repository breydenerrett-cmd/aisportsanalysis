"""Slate health monitor: the six days it has to tell apart.

The whole value of this module is discrimination -- a healthy day, a degraded
day, an off day and a day nothing ran must each read differently. So the tests
build real stores on disk (the monitor reads files, not injected objects) and
assert on the ANOMALY SENTENCES, because those are the product; a dict that is
correct but says nothing useful would pass a shape test and fail the user.

The one seam that is injected is MLB's schedule endpoint. Every test passes its
own `schedule_fetch`, so the suite never touches the network and can stage the
case the stores physically cannot produce: a game that exists and that nobody
priced. That case is the reason the slate is asked of MLB rather than inferred
from the odds -- inferred, it deletes itself from both sides of the ratio.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.pipeline import health

DAY = "2026-08-31"
YESTERDAY = "2026-08-30"
NOON = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)  # inside the slate

BOOKS = ["fanduel", "draftkings", "betmgm", "bovada"]

GAMES = [
    ("San Francisco Giants", "Atlanta Braves", "SF", "ATL", 823001),
    ("Chicago Cubs", "Milwaukee Brewers", "CHC", "MIL", 823002),
    ("New York Yankees", "Boston Red Sox", "NYY", "BOS", 823003),
]

START = f"{DAY}T22:05:00Z"

# A West Coast game on tonight's slate: MLB files it under DAY, its first pitch
# carries tomorrow's UTC date, and so does every quote a book posts for it.
LATE_START = f"2026-09-01T01:40:00Z"
LATE_GAME = ("Philadelphia Phillies", "Arizona Diamondbacks", "PHI", "ARI", 823004)


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _record(game, start=START, game_type="R", coded_state="P"):
    """One raw MLB schedule record, shaped like the real endpoint's."""
    away, home, _, _, pk = game
    return {
        "gamePk": pk,
        "gameDate": start,
        "officialDate": DAY,
        "gameType": game_type,
        "status": {"codedGameState": coded_state, "detailedState": "Pre-Game"},
        "teams": {"away": {"team": {"name": away, "abbreviation": game[2]}},
                  "home": {"team": {"name": home, "abbreviation": game[3]}}},
    }


def _schedule(records):
    """A stub schedule endpoint that answers for DAY and nothing else."""
    def fetch(day, **_):
        return list(records) if day == DAY else []
    return fetch


def _unreachable(exc=RuntimeError("MLB API down")):
    def fetch(day, **_):
        raise exc
    return fetch


class HealthStoreFixture(unittest.TestCase):
    """A synthetic data tree that starts healthy; each test breaks one thing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.ledger = self.root / "forward_ledger.jsonl"
        self.schedule_fetch = _schedule([_record(g) for g in GAMES])
        self.build_slate_csv()
        self.build_odds(observed=NOON - timedelta(minutes=12))
        self.build_baseline_day()
        self.build_watch(last_poll=NOON - timedelta(minutes=5))
        self.build_ledger()

    # -- builders ---------------------------------------------------------

    def build_slate_csv(self, games=GAMES):
        path = self.root / "raw" / f"mlb_{DAY}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["date,game_pk,start_time_utc,away_team,home_team"]
        for _, _, away, home, pk in games:
            lines.append(f"{DAY},{pk},{START},{away},{home}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def build_odds(self, observed, books=BOOKS, games=GAMES, day=DAY):
        stamp = observed.isoformat()
        mb, snap = [], []
        for away, home, _, _, _ in games:
            for book in books:
                mb.append({"observed_utc": stamp, "event_id": f"{away}{home}",
                           "commence_time": f"{day}T22:05:00Z",
                           "home_team": home, "away_team": away, "book": book,
                           "home_price": -120, "away_price": 105})
            for market in ("h2h", "spreads", "totals"):
                snap.append({"observed_utc": stamp, "commence_time": f"{day}T22:05:00Z",
                             "home_team": home, "away_team": away,
                             "market": market, "book": books[0],
                             "prices": {"home_price": -120, "away_price": 105}})
        _write(self.root / "processed" / "odds_multibook.jsonl", mb)
        _write(self.root / "processed" / "odds_snapshots.jsonl", snap)

    def build_baseline_day(self, books=BOOKS):
        """A prior day in the store, which is what makes 'usual books' knowable."""
        self.build_odds(observed=datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc),
                        books=books, day=YESTERDAY)

    def build_watch(self, last_poll, lineup_games=GAMES):
        stamp = last_poll.isoformat()
        watch = self.root / "watch"
        _write(watch / "probables_watch.jsonl", [{"fetched_utc": stamp, "poll": True}])
        _write(watch / "transactions_watch.jsonl", [{"fetched_utc": stamp, "poll": True}])
        rows = [{"fetched_utc": stamp, "poll": True}]
        for _, _, _, _, pk in lineup_games:
            rows.append({"fetched_utc": stamp, "game_pk": pk,
                         "away_lineup": [1, 2, 3], "home_lineup": [4, 5, 6]})
        _write(watch / "lineups_watch.jsonl", rows)

    def build_ledger(self, unsettled_past=False):
        rows = []
        for index, (_, _, away, home, pk) in enumerate(GAMES):
            rows.append({"kind": "recommendation", "game_pk": pk, "date": DAY,
                         "recorded_at": f"{DAY}T09:00:00+00:00",
                         "verdict": "no_play", "away_team": away,
                         "home_team": home, "prices": {"h2h": {}}})
            rows.append({"kind": "settlement", "game_pk": pk,
                         "settled_at": f"{DAY}T23:00:00+00:00",
                         "result": {"home_won": True}, "closing": -120})
        if unsettled_past:
            rows.insert(0, {"kind": "recommendation", "game_pk": 999,
                            "date": YESTERDAY,
                            "recorded_at": f"{YESTERDAY}T09:00:00+00:00",
                            "verdict": "flagged", "prices": {"h2h": {}}})
        _write(self.ledger, rows)

    # -- runner -----------------------------------------------------------

    def run_report(self, now=NOON, date=DAY, fetch=None):
        return health.report(date=date, now=now, data_dir=self.root,
                             ledger_path=self.ledger,
                             schedule_fetch=fetch or self.schedule_fetch)

    def assertMentions(self, data, *fragments):
        blob = " ".join(data["anomalies"]).lower()
        for fragment in fragments:
            self.assertIn(fragment.lower(), blob,
                          msg=f"anomalies were: {data['anomalies']}")


class HealthyDayTests(HealthStoreFixture):

    def test_healthy_day_reports_no_anomalies(self):
        data = self.run_report()
        self.assertEqual(data["anomalies"], [])
        self.assertTrue(data["healthy"])
        self.assertEqual(data["schedule"]["games"], 3)
        self.assertEqual(data["odds"]["games_with_odds"], 3)
        self.assertEqual(data["odds"]["books_per_game_min"], len(BOOKS))
        self.assertEqual(data["odds"]["books_missing"], [])
        self.assertEqual(data["markets"]["coverage"]["h2h"]["games"], 3)
        self.assertEqual(data["lineups"]["games_with_posted_lineups"], 3)
        self.assertTrue(data["slate_live"])

    def test_format_report_is_plain_text_and_names_the_date(self):
        text = health.format_report(self.run_report())
        self.assertIn(DAY, text)
        self.assertIn("ANOMALIES   none", text)
        self.assertIn("books seen", text)

    def test_monitor_writes_nothing(self):
        before = sorted(p.relative_to(self.root).as_posix()
                        for p in self.root.rglob("*"))
        sizes = {p: p.stat().st_size for p in self.root.rglob("*") if p.is_file()}
        self.run_report()
        after = sorted(p.relative_to(self.root).as_posix()
                       for p in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(sizes, {p: p.stat().st_size
                                 for p in self.root.rglob("*") if p.is_file()})


class DegradationTests(HealthStoreFixture):

    def test_missing_book_is_named_against_the_learned_baseline(self):
        """Yesterday had four books; today has three. The absentee is named."""
        self.setUp_missing_book()
        data = self.run_report()
        self.assertEqual(data["odds"]["books_missing"], ["bovada"])
        self.assertMentions(data, "bovada", "1 book")
        self.assertFalse(data["healthy"])

    def setUp_missing_book(self):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(minutes=12),
                        books=[b for b in BOOKS if b != "bovada"])
        self.build_baseline_day()

    def test_stale_snapshot_during_live_slate_is_flagged_with_its_age(self):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(hours=5))
        self.build_baseline_day()
        data = self.run_report()
        self.assertGreater(data["snapshots"]["age_minutes"], 120)
        self.assertMentions(data, "newest multi-book capture", "live slate")

    def test_stale_snapshot_outside_the_slate_is_not_an_alarm(self):
        """Overnight there is nothing to capture; an old capture is expected."""
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(hours=5))
        self.build_baseline_day()
        dawn = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
        self.build_watch(last_poll=dawn - timedelta(minutes=5))
        data = self.run_report(now=dawn)
        self.assertFalse(data["slate_live"])
        self.assertEqual([a for a in data["anomalies"] if "capture" in a], [])

    def test_stale_watch_poll_is_flagged(self):
        (self.root / "watch").rename(self.root / "watch_old")
        self.build_watch(last_poll=NOON - timedelta(hours=3))
        data = self.run_report()
        self.assertMentions(data, "probables watch stream last polled",
                            "lineups watch stream last polled")

    def test_game_with_no_quote_is_named(self):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(minutes=12), games=GAMES[:2])
        self.build_baseline_day()
        data = self.run_report()
        self.assertEqual(data["odds"]["games_without_odds"], [("NYY", "BOS")])
        self.assertMentions(data, "1 of 3 scheduled games have no quote",
                            "NYY @ BOS")

    def test_thin_book_coverage_is_flagged(self):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(minutes=12), books=BOOKS[:2])
        self.build_baseline_day()
        data = self.run_report()
        self.assertMentions(data, f"fewer than {health.MIN_BOOKS_PER_GAME} books")

    def test_settlement_gap_surfaces_the_past_date(self):
        self.ledger.unlink()
        self.build_ledger(unsettled_past=True)
        data = self.run_report()
        self.assertEqual(data["settlement"]["unsettled_past_dates"], [YESTERDAY])
        self.assertMentions(data, "never settled", YESTERDAY)

    def test_no_lineups_during_a_live_slate_is_flagged(self):
        (self.root / "watch").rename(self.root / "watch_old")
        self.build_watch(last_poll=NOON - timedelta(minutes=5), lineup_games=[])
        data = self.run_report()
        self.assertEqual(data["lineups"]["games_with_posted_lineups"], 0)
        self.assertMentions(data, "no posted lineup has been seen")


class EmptySlateTests(HealthStoreFixture):

    def test_empty_slate_with_a_schedule_store_is_healthy(self):
        """An off day has no odds and no captures OF ITS OWN. That is fine.

        The stores themselves still exist and still hold yesterday -- they are
        append-only and cumulative -- so this is the realistic shape of a day
        with no baseball, not a day with no collector.
        """
        for name in ("odds_multibook.jsonl", "odds_snapshots.jsonl"):
            (self.root / "processed" / name).unlink()
        self.build_baseline_day()
        self.build_slate_csv(games=[])
        data = self.run_report()
        self.assertEqual(data["schedule"]["games"], 0)
        self.assertTrue(data["schedule"]["authoritative"])
        self.assertEqual(data["anomalies"], [])
        self.assertTrue(data["healthy"])

    def test_no_games_and_no_schedule_of_any_kind_is_reported_as_ambiguous(self):
        """The one thing the monitor must never do: call this a clean day."""
        (self.root / "raw" / f"mlb_{DAY}.csv").unlink()
        for name in ("odds_multibook.jsonl", "odds_snapshots.jsonl"):
            (self.root / "processed" / name).unlink()
        data = self.run_report(fetch=_unreachable())
        self.assertIsNone(data["schedule"]["games"])
        self.assertFalse(data["schedule"]["authoritative"])
        self.assertFalse(data["healthy"])
        self.assertMentions(data, "empty slate and a failed collection look "
                                  "identical", "MLB API down")

    def test_an_off_day_is_still_healthy_when_mlb_answers_zero(self):
        """No CSV, no odds -- but MLB says there is no baseball. That is fine."""
        (self.root / "raw" / f"mlb_{DAY}.csv").unlink()
        for name in ("odds_multibook.jsonl", "odds_snapshots.jsonl"):
            (self.root / "processed" / name).unlink()
        self.build_baseline_day()
        (self.root / "watch").rename(self.root / "watch_old")
        self.build_watch(last_poll=NOON - timedelta(minutes=5), lineup_games=[])
        data = self.run_report(fetch=_schedule([]))
        self.assertEqual(data["schedule"]["games"], 0)
        self.assertEqual(data["schedule"]["source"], "mlb_schedule")
        self.assertTrue(data["schedule"]["authoritative"])
        self.assertEqual(data["anomalies"], [])


class AbsentStoreTests(HealthStoreFixture):

    def test_absent_stores_read_as_no_data_never_as_zero(self):
        for path in self.root.rglob("*.jsonl"):
            path.unlink()
        data = self.run_report()
        self.assertIsNone(data["odds"]["games_with_odds"])
        self.assertIsNone(data["snapshots"]["age_minutes"])
        self.assertIsNone(data["settlement"]["games_recorded"])
        self.assertIsNone(data["lineups"]["games_with_posted_lineups"])
        self.assertFalse(data["healthy"])
        self.assertMentions(data,
                            "multi-book odds store is absent",
                            "odds snapshot store is absent",
                            "probables watch store is absent",
                            "forward ledger is absent")

    def test_absent_everything_still_formats(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                path.unlink()
        text = health.format_report(self.run_report())
        self.assertIn("no data", text)

    def test_no_baseline_day_is_stated_rather_than_assumed(self):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(minutes=12))  # today only
        data = self.run_report()
        self.assertIsNone(data["odds"]["usual_books"])
        self.assertMentions(data, "no baseline")

    def test_corrupt_line_costs_one_row_not_the_report(self):
        path = self.root / "processed" / "odds_multibook.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"observed_utc": "2026-08-31T19:5\n')
        data = self.run_report()
        self.assertEqual(data["odds"]["games_with_odds"], 3)


class TrueSlateTests(HealthStoreFixture):
    """The slate comes from MLB, so a game nobody priced still exists."""

    def drop_csv(self):
        (self.root / "raw" / f"mlb_{DAY}.csv").unlink()

    def rebuild_odds(self, games=GAMES):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        (self.root / "processed" / "odds_snapshots.jsonl").unlink()
        self.build_odds(observed=NOON - timedelta(minutes=12), games=games)
        self.build_baseline_day()

    def test_a_game_no_book_priced_is_named_not_subtracted(self):
        """The whole point: MLB has three games, the books priced two."""
        self.drop_csv()
        self.rebuild_odds(games=GAMES[:2])
        data = self.run_report()
        self.assertEqual(data["schedule"]["source"], "mlb_schedule")
        self.assertTrue(data["schedule"]["authoritative"])
        self.assertEqual(data["schedule"]["games"], 3)
        self.assertEqual(data["odds"]["games_with_odds"], 2)
        self.assertEqual(data["odds"]["games_without_odds"], [("NYY", "BOS")])
        self.assertMentions(data, "1 of 3 scheduled games have no quote",
                            "NYY @ BOS")

    def test_the_same_missed_game_is_invisible_once_mlb_cannot_be_reached(self):
        """The old behaviour, now stated as uncertainty instead of coverage.

        With only the odds stores to go on, the unpriced game cannot be seen at
        all -- so the monitor must not print a game count as if it were a slate.
        """
        self.drop_csv()
        self.rebuild_odds(games=GAMES[:2])
        data = self.run_report(fetch=_unreachable())
        self.assertFalse(data["schedule"]["authoritative"])
        self.assertEqual(data["schedule"]["games"], 2)
        self.assertEqual(data["odds"]["games_without_odds"], [])
        self.assertIsNone(data["markets"]["coverage"]["h2h"]["of_scheduled"])
        self.assertMentions(data, "could not be established",
                            "coverage against the real slate is unknown")
        self.assertIn("NOT AUTHORITATIVE", health.format_report(data))

    def test_a_west_coast_game_is_matched_across_the_utc_date_boundary(self):
        """MLB files by Eastern date; the books timestamp in UTC.

        Bucketing quotes by UTC date dropped every late game into tomorrow and
        reported it as unpriced. It is on tonight's slate and it is priced.
        """
        self.drop_csv()
        self.schedule_fetch = _schedule(
            [_record(g) for g in GAMES] + [_record(LATE_GAME, start=LATE_START)])
        rows = [{"observed_utc": (NOON - timedelta(minutes=12)).isoformat(),
                 "event_id": "late", "commence_time": LATE_START,
                 "home_team": LATE_GAME[1], "away_team": LATE_GAME[0],
                 "book": book, "home_price": -120, "away_price": 105}
                for book in BOOKS]
        _write(self.root / "processed" / "odds_multibook.jsonl", rows)
        data = self.run_report()
        self.assertEqual(data["schedule"]["games"], 4)
        self.assertEqual(data["odds"]["games_with_odds"], 4)
        self.assertEqual(data["odds"]["games_without_odds"], [])

    def test_yesterdays_rows_for_the_same_matchup_do_not_count_as_todays(self):
        """A series repeats the pairing, so identity alone is not a key."""
        self.drop_csv()
        self.rebuild_odds(games=[])  # today unpriced; yesterday's rows remain
        data = self.run_report()
        self.assertEqual(data["schedule"]["games"], 3)
        self.assertEqual(data["odds"]["games_with_odds"], 0)
        self.assertMentions(data, "holds no rows at all")

    def test_a_postponed_game_is_held_out_of_the_count_and_named(self):
        self.drop_csv()
        self.rebuild_odds(games=GAMES[:2])
        self.schedule_fetch = _schedule(
            [_record(g) for g in GAMES[:2]]
            + [_record(GAMES[2], coded_state="D")])
        data = self.run_report()
        self.assertEqual(data["schedule"]["games"], 2)
        self.assertEqual(data["schedule"]["unplayed"], [("NYY", "BOS")])
        self.assertIn("not being played", data["schedule"]["note"])
        self.assertEqual([a for a in data["anomalies"] if "no quote" in a], [])

    def test_exhibition_play_is_not_counted_as_a_priced_slate(self):
        self.drop_csv()
        self.rebuild_odds(games=GAMES[:2])
        self.schedule_fetch = _schedule(
            [_record(g) for g in GAMES[:2]]
            + [_record(GAMES[2], game_type="S")])
        data = self.run_report()
        self.assertEqual(data["schedule"]["games"], 2)
        self.assertEqual(data["schedule"]["exhibition"], [("NYY", "BOS")])

    def test_the_slate_csv_still_wins_and_nothing_is_fetched(self):
        data = self.run_report(fetch=_unreachable(
            AssertionError("the CSV was on disk; MLB must not be called")))
        self.assertEqual(data["schedule"]["source"], "slate_csv")
        self.assertEqual(data["schedule"]["games"], 3)


class LineupDenominatorTests(HealthStoreFixture):
    """A ratio needs both sides counted in the same space, or it is not one."""

    def test_lineups_for_other_games_never_inflate_slate_coverage(self):
        """The '8 of 7' defect: watch-store count over an odds-store slate."""
        (self.root / "watch").rename(self.root / "watch_old")
        self.build_watch(last_poll=NOON - timedelta(minutes=5))
        _write(self.root / "watch" / "lineups_watch.jsonl",
               [{"fetched_utc": NOON.isoformat(), "game_pk": pk,
                 "away_lineup": [1], "home_lineup": [2]}
                for pk in (901001, 901002)])  # tomorrow's board, already up
        data = self.run_report()
        lineups = data["lineups"]
        self.assertEqual(lineups["games_with_posted_lineups"], 3)
        self.assertEqual(lineups["of_scheduled"], 3)
        self.assertEqual(lineups["off_slate_lineups"], 2)
        self.assertTrue(lineups["coverage_measurable"])
        self.assertLessEqual(lineups["games_with_posted_lineups"],
                             lineups["of_scheduled"])
        text = health.format_report(data)
        self.assertIn("3 of 3 slate games have a posted lineup", text)
        self.assertIn("2 fetched today for games not on this slate", text)

    def test_coverage_is_withheld_when_the_slate_carries_no_game_pks(self):
        """No denominator in the same space, so no ratio -- and it says so."""
        (self.root / "raw" / f"mlb_{DAY}.csv").unlink()
        data = self.run_report(fetch=_unreachable())
        lineups = data["lineups"]
        self.assertFalse(lineups["coverage_measurable"])
        self.assertIsNone(lineups["of_scheduled"])
        self.assertEqual(lineups["games_with_posted_lineups"], 3)
        self.assertEqual(lineups["attributed_by"], "fetch date")
        self.assertMentions(data, "lineup coverage cannot be measured")
        text = health.format_report(data)
        self.assertIn("no comparable slate denominator", text)
        self.assertNotIn("slate games have a posted lineup", text)

    def test_a_true_shortfall_is_still_reported_once_games_have_started(self):
        (self.root / "watch").rename(self.root / "watch_old")
        self.build_watch(last_poll=NOON + timedelta(hours=3),
                         lineup_games=GAMES[:1])
        data = self.run_report(now=NOON + timedelta(hours=3))
        self.assertEqual(data["lineups"]["games_with_posted_lineups"], 1)
        self.assertMentions(data, "only 1 of 3 games ever had a posted lineup")


class EmptyStoreHonestyTests(HealthStoreFixture):
    """Present-but-empty is zero. Absent is unknown. They must not blur."""

    def test_a_present_but_empty_multibook_store_reads_as_zero(self):
        path = self.root / "processed" / "odds_multibook.jsonl"
        path.unlink()
        path.touch()
        data = self.run_report()
        self.assertTrue(data["odds"]["store_present"])
        self.assertEqual(data["odds"]["games_with_odds"], 0)
        self.assertEqual(data["odds"]["rows"], 0)
        self.assertIsNone(data["odds"]["usual_books"])
        self.assertMentions(data, "holds no rows at all")

    def test_an_absent_multibook_store_reads_as_unknown_not_zero(self):
        (self.root / "processed" / "odds_multibook.jsonl").unlink()
        data = self.run_report()
        self.assertFalse(data["odds"]["store_present"])
        self.assertIsNone(data["odds"]["games_with_odds"])
        self.assertIsNone(data["odds"]["rows"])
        self.assertMentions(data, "multi-book odds store is absent")
        self.assertEqual([a for a in data["anomalies"]
                          if "holds no rows at all" in a], [])

    def test_an_absent_lineup_store_publishes_no_coverage_number(self):
        (self.root / "watch" / "lineups_watch.jsonl").unlink()
        data = self.run_report()
        lineups = data["lineups"]
        self.assertIsNone(lineups["games_with_posted_lineups"])
        self.assertIsNone(lineups["of_scheduled"])
        self.assertFalse(lineups["coverage_measurable"])
        self.assertIn("no data posted lineup(s) seen",
                      health.format_report(data))
        self.assertMentions(data, "lineups watch store is absent")


class ContractTests(HealthStoreFixture):

    def test_bad_date_is_refused(self):
        with self.assertRaises(health.HealthError):
            health.report(date="31/08/2026", data_dir=self.root)

    def test_naive_now_is_treated_as_utc(self):
        naive = health.report(date=DAY, now=NOON.replace(tzinfo=None),
                              data_dir=self.root, ledger_path=self.ledger,
                              schedule_fetch=self.schedule_fetch)
        aware = self.run_report()
        self.assertEqual(naive["anomalies"], aware["anomalies"])

    def test_f5_gap_is_only_raised_once_every_game_has_started(self):
        _write(self.root / "processed" / "f5_close.jsonl",
               [{"observed_utc": f"{YESTERDAY}T22:00:00Z", "event_id": "x",
                 "commence_time": f"{YESTERDAY}T22:05:00Z"}])
        during = self.run_report()
        self.assertEqual(during["markets"]["f5"]["events"], 0)
        self.assertEqual([a for a in during["anomalies"] if "first-five" in a], [])

        after = self.run_report(now=NOON + timedelta(hours=3))
        self.assertMentions(after, "first-five close store holds no rows")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
