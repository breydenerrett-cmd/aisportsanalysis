"""Tests for the intraday posted-lineup cadence (P0, 2026-09-08).

WHAT WENT WRONG, AND WHAT THESE TESTS ARE HERE TO STOP HAPPENING AGAIN
----------------------------------------------------------------------
`lineup_store.build` was called from exactly one place -- the 10:00Z daily loop
-- and it skipped any date already present in the store. For a closed
historical date that is right and cheap. For a date still in progress it is a
silent data-loss bug: the 10:00Z pass stored whatever had posted by 10:00Z,
marked the date covered, and every later pass skipped it, so a lineup that
posted at 21:00Z was never collected at all. Measured on the real store on
2026-09-08: 10 of the day's 15 games, and the missing 5 unreachable by any
later `build` call, that evening or any morning after.

The suite that existed passed throughout. It could not have caught this,
because every one of its fixtures was a CLOSED date -- a date whose games were
all posted before the first fetch -- so "skip a covered date" and "skip a
complete date" were indistinguishable in every test. That is the shape of
fixture this module deliberately breaks: every fixture here changes between the
first pass and the second, which is what a live date does.

The second half tests `slate_due`, the gate that decides whether the refreshed
store is worth another slate pass. It exists because refreshing a store nothing
re-reads changes nothing: the measured defect was that FORWARD_TEST decisions
froze a median 8.9 minutes before first pitch while their lineups had been
visible a median 160 minutes before it. Nothing was waiting on data; nothing
was running.

The last three tests are the WIRING tests the fix is worthless without: they
assert the refresh reaches more than the once-daily path. A store that is
correct and called once a day is the bug we started from.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.paths import repo_root
from src.pipeline import lineup_store


def _slot(order, person_id):
    return {"order": order, "person_id": person_id,
            "name": f"Player {person_id}", "position": "1B"}


def _card(game_pk, away=(), home=(), posted_at=None):
    """One game's fetched record, in `lineups.fetch_lineups`'s own shape."""
    record = {"game_pk": game_pk,
              "away": [_slot(i, pid) for i, pid in enumerate(away, 1)],
              "home": [_slot(i, pid) for i, pid in enumerate(home, 1)]}
    if posted_at:
        record["posted_at"] = posted_at
    return record


class FakeFetch:
    """Serves a different day per call, which is what a live date does.

    The existing store suite's fake returns the same canned answer forever, so
    a date fetched twice looks identical to a date fetched once -- exactly the
    uniformity that let the freeze-at-first-touch bug pass. `pages` is a list:
    call n gets pages[n], and the last page repeats once the list runs out.
    """

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, iso, timeout=20):
        self.calls.append(iso)
        index = min(len(self.calls) - 1, len(self.pages) - 1)
        page = self.pages[index]
        return dict(page.get(iso) or {})


class LineupStoreTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "lineups.jsonl"

    def _build(self, dates, fetch, **kwargs):
        return lineup_store.build(
            dates, path=self.path, fetch=fetch,
            fetch_handedness=lambda ids, timeout=20: None,
            sleep=lambda seconds: None, **kwargs)

    def _lines(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestIntradayTopUp(LineupStoreTestCase):
    """A date still in progress gains games between passes. It must collect
    them; the historical backfill must keep skipping closed dates."""

    def test_a_refreshed_date_collects_games_that_posted_after_the_first_pass(self):
        # 10:00Z: one card up. 21:00Z: the other two have posted.
        morning = {"2026-09-08": {101: _card(101, [1, 2], [3, 4])}}
        evening = {"2026-09-08": {101: _card(101, [1, 2], [3, 4]),
                                  102: _card(102, [5, 6], [7, 8]),
                                  103: _card(103, [9, 10], [11, 12])}}
        fetch = FakeFetch([morning, evening])

        self._build(["2026-09-08"], fetch)
        self.assertEqual(set(lineup_store.read(self.path)), {"101"})

        report = self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])

        self.assertEqual(set(lineup_store.read(self.path)), {"101", "102", "103"},
                         "a refreshed date must collect the games that posted "
                         "after the first pass -- this is the whole defect")
        self.assertEqual(report["games"], 2)
        self.assertEqual(report["refreshed"], 1)
        self.assertEqual(report["skipped"], 0)

    def test_a_date_not_named_for_refresh_is_still_skipped(self):
        # The historical backfill's contract, unchanged: ~370 closed dates must
        # not be refetched just because the refresh path now exists.
        morning = {"2023-06-01": {101: _card(101, [1], [2])}}
        evening = {"2023-06-01": {101: _card(101, [1], [2]),
                                  102: _card(102, [3], [4])}}
        fetch = FakeFetch([morning, evening])

        self._build(["2023-06-01"], fetch)
        report = self._build(["2023-06-01"], fetch)

        self.assertEqual(fetch.calls, ["2023-06-01"],
                         "a covered date not named for refresh must not hit "
                         "the network again")
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(set(lineup_store.read(self.path)), {"101"})

    def test_a_refresh_that_finds_nothing_new_writes_nothing(self):
        # The cadence runs every capture slot. If an unchanged slate appended a
        # duplicate row per game per slot, a 15-game day would add ~1,400 rows
        # of nothing and read() would be resolving duplicates all season.
        page = {"2026-09-08": {101: _card(101, [1, 2], [3, 4])}}
        fetch = FakeFetch([page])

        self._build(["2026-09-08"], fetch)
        before = self._lines()
        report = self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])

        self.assertEqual(self._lines(), before,
                         "an unchanged refresh must append nothing at all")
        self.assertEqual(report["games"], 0)
        self.assertEqual(report["topped_up"], 0)

    def test_a_half_posted_card_is_completed_by_a_later_pass(self):
        # The real 2026-09-08 shape: at 18:52Z three games had one side up and
        # the other still blank. A per-game "have I seen this game_pk" check
        # calls that done forever and stores half a lineup.
        half = {"2026-09-08": {101: _card(101, away=[1, 2, 3])}}
        full = {"2026-09-08": {101: _card(101, away=[1, 2, 3], home=[4, 5, 6])}}
        fetch = FakeFetch([half, full])

        self._build(["2026-09-08"], fetch)
        self.assertEqual(lineup_store.read(self.path)["101"]["home"], [])

        report = self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])

        card = lineup_store.read(self.path)["101"]
        self.assertEqual([slot["person_id"] for slot in card["home"]], [4, 5, 6],
                         "a card seen mid-posting must be completed, not "
                         "treated as done because its game_pk was stored")
        self.assertEqual([slot["person_id"] for slot in card["away"]], [1, 2, 3])
        self.assertEqual(report["topped_up"], 1)

    def test_a_same_size_change_does_not_rewrite_a_stored_card(self):
        # A late scratch is a real fact and it belongs to lineups_watch, which
        # brackets every edit with the poll that saw it. Rewriting it here would
        # change the input an already-published research row was computed from.
        first = {"2026-09-08": {101: _card(101, [1, 2], [3, 4])}}
        scratched = {"2026-09-08": {101: _card(101, [1, 99], [3, 4])}}
        fetch = FakeFetch([first, scratched])

        self._build(["2026-09-08"], fetch)
        report = self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])

        card = lineup_store.read(self.path)["101"]
        self.assertEqual([slot["person_id"] for slot in card["away"]], [1, 2],
                         "a same-size change must not overwrite a stored card")
        self.assertEqual(report["games"], 0)

    def test_the_empty_marker_is_written_once_however_often_a_date_refreshes(self):
        # The marker answers "was this date ever attempted". One per attempt
        # would answer "how often did the cadence run", which the run log
        # already answers, and would bloat the store by ~96 rows a day.
        empty = {"2026-09-08": {}}
        fetch = FakeFetch([empty])

        self._build(["2026-09-08"], fetch)
        self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])
        self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])

        self.assertEqual(self._lines(), [{"date": "2026-09-08", "empty": True}])
        self.assertIn("2026-09-08", lineup_store.covered_dates(self.path))

    def test_a_date_that_was_empty_and_then_posts_is_still_collected(self):
        # An off-day marker and a slate that had simply not posted yet look
        # identical at 10:00Z. Refusing to look again would turn "nothing had
        # posted at breakfast" into "this date has no lineups", permanently.
        empty = {"2026-09-08": {}}
        posted = {"2026-09-08": {101: _card(101, [1], [2])}}
        fetch = FakeFetch([empty, posted])

        self._build(["2026-09-08"], fetch)
        self.assertEqual(lineup_store.read(self.path), {})

        self._build(["2026-09-08"], fetch, refresh=["2026-09-08"])

        self.assertEqual(set(lineup_store.read(self.path)), {"101"})

    def test_observed_utc_is_recorded_when_reported_and_never_invented(self):
        # Before this field existed, a store frozen at 10:00Z and one refreshed
        # all afternoon were byte-for-byte identical, so "did the cadence run"
        # was unanswerable from the store itself. It is recorded ONLY when the
        # fetcher reports it: a locally stamped clock on a path that did not
        # observe the fetch would be a fabricated observation time.
        with_time = {"2026-09-08": {101: _card(101, [1], [2],
                                               posted_at="2026-09-08T19:40:43+00:00")}}
        without = {"2026-09-09": {102: _card(102, [3], [4])}}
        fetch = FakeFetch([with_time, without])

        self._build(["2026-09-08"], fetch)
        self._build(["2026-09-09"], fetch)

        rows = {str(row["game_pk"]): row for row in self._lines()
                if row.get("game_pk")}
        self.assertEqual(rows["101"]["observed_utc"], "2026-09-08T19:40:43+00:00")
        self.assertNotIn("observed_utc", rows["102"],
                         "an unreported observation time must be ABSENT, never "
                         "a locally invented one")


class TestSlateDue(unittest.TestCase):
    """The gate. A refreshed store changes nothing on its own -- something has
    to decide again once the lineup lands."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.watch = root / "lineups_watch.jsonl"
        self.decisions = root / "decisions_v2.jsonl"

    def _write(self, path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows),
                        encoding="utf-8")

    def _due(self):
        return lineup_store.slate_due(watch_path=self.watch,
                                      decisions_path=self.decisions)

    def test_due_when_a_complete_lineup_landed_after_the_last_frozen_set(self):
        self._write(self.watch, [
            {"fetched_utc": "2026-09-08T19:40:43+00:00", "game_pk": 824792,
             "home_lineup": [1, 2], "away_lineup": [3, 4]}])
        self._write(self.decisions, [
            {"recorded_utc": "2026-09-08T15:22:17+00:00"}])

        gate = self._due()

        self.assertTrue(gate["due"])
        self.assertEqual(gate["newest_lineup_utc"], "2026-09-08T19:40:43+00:00")
        self.assertIn("19:40:43", gate["reason"])

    def test_not_due_when_the_last_frozen_set_is_newer_than_every_lineup(self):
        self._write(self.watch, [
            {"fetched_utc": "2026-09-08T19:40:43+00:00", "game_pk": 824792,
             "home_lineup": [1, 2], "away_lineup": [3, 4]}])
        self._write(self.decisions, [
            {"recorded_utc": "2026-09-08T20:23:39+00:00"}])

        gate = self._due()

        self.assertFalse(gate["due"])
        self.assertIn("20:23:39", gate["reason"])

    def test_a_half_posted_card_does_not_make_a_pass_due(self):
        # `build_snapshot` derives lineup_posted from BOTH sides being present,
        # so a pass fired on a home-only card cannot decide anything and would
        # append a decision set carrying no new information.
        self._write(self.watch, [
            {"fetched_utc": "2026-09-08T18:52:26+00:00", "game_pk": 824792,
             "home_lineup": [1, 2], "away_lineup": []}])
        self._write(self.decisions, [
            {"recorded_utc": "2026-09-08T13:58:00+00:00"}])

        gate = self._due()

        self.assertFalse(gate["due"])
        self.assertIsNone(gate["newest_lineup_utc"])

    def test_a_store_of_nothing_but_poll_markers_is_not_due(self):
        # Every poll appends a marker whether or not it saw anything, so for
        # most of the day the watch store's NEWEST row is a marker and nothing
        # else. A gate that took the freshest row of any kind would therefore
        # fire on every single capture slot -- precisely what it exists to
        # prevent -- and would look correct in any fixture where a lineup
        # happened to be the last thing written.
        self._write(self.watch, [
            {"fetched_utc": "2026-09-08T13:10:49+00:00", "poll": True,
             "game_date": "2026-09-08"},
            {"fetched_utc": "2026-09-08T19:40:45+00:00", "poll": True,
             "game_date": "2026-09-08"}])
        self._write(self.decisions, [
            {"recorded_utc": "2026-09-08T13:58:00+00:00"}])

        gate = self._due()

        self.assertFalse(gate["due"])
        self.assertIsNone(gate["newest_lineup_utc"])
        self.assertIn("no game has a complete posted lineup", gate["reason"])

    def test_the_gate_reads_the_write_instant_not_the_decision_instant(self):
        # decision_utc is the instant a decision was made AS OF -- the latest
        # capture before first pitch, which can sit hours before the pass that
        # wrote it. Comparing against it would keep re-firing passes for a set
        # already frozen.
        self._write(self.watch, [
            {"fetched_utc": "2026-09-08T19:40:43+00:00", "game_pk": 824792,
             "home_lineup": [1, 2], "away_lineup": [3, 4]}])
        self._write(self.decisions, [
            {"decision_utc": "2026-09-08T10:11:00+00:00",
             "recorded_utc": "2026-09-08T20:23:39+00:00"}])

        self.assertFalse(self._due()["due"])

    def test_an_absent_store_answers_not_due_with_a_reason_and_never_raises(self):
        # This runs inside a capture pass. It must never be the reason a
        # capture fails, and "I could not tell" must not read as "yes".
        gate = self._due()

        self.assertFalse(gate["due"])
        self.assertIsNone(gate["newest_lineup_utc"])
        self.assertTrue(gate["reason"])

    def test_a_torn_line_does_not_take_the_gate_down(self):
        # Both stores are appended to by live passes; a truncated last line is
        # a normal transient, not a reason to stop deciding.
        self.watch.write_text(
            json.dumps({"fetched_utc": "2026-09-08T19:40:43+00:00",
                        "game_pk": 824792, "home_lineup": [1],
                        "away_lineup": [2]}) + "\n{\"fetched_ut",
            encoding="utf-8")
        self._write(self.decisions, [
            {"recorded_utc": "2026-09-08T13:58:00+00:00"}])

        self.assertTrue(self._due()["due"])


class TestTheRefreshIsWiredIntoMoreThanTheOnceDailyPath(unittest.TestCase):
    """The regression the fix is worthless without.

    `lineup_store.build` being correct is not the fix; being CALLED on the
    cadence lineups post at is. Before this change it was called from exactly
    one place, the once-daily loop, and the store's own suite was fully green
    the whole time. These tests read the operational entry points as text --
    the only place that wiring is expressed -- so deleting the intraday caller
    fails a test instead of silently restoring the defect."""

    # A COMMENT IS NOT WIRING. Every assertion below runs against the file
    # with its comment lines removed, because the first draft of these tests
    # did not: replacing the workflow's real `slate_due()` call with a stub
    # left them green, satisfied entirely by the explanatory comment sitting
    # above the call. A wiring test that a paragraph of prose can satisfy is
    # the same failure mode as the suite that missed the original bug.
    CALL = "lineup_store.build("
    # How far past a `build(` call site to look for its own `refresh=`. Both
    # call sites name it on the very next line; 240 characters is comfortably
    # inside the following statement, so a `refresh=` belonging to some OTHER
    # call cannot be mistaken for this one's.
    CALL_SITE_CHARS = 240

    @staticmethod
    def _code(text):
        return "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith("#"))

    @classmethod
    def _entry_points(cls):
        root = repo_root()
        paths = sorted((root / "scripts").glob("*.sh"))
        paths += sorted((root / ".github" / "workflows").glob("*.yml"))
        return {p.name: cls._code(p.read_text(encoding="utf-8")) for p in paths}

    @classmethod
    def _refreshing_callers(cls):
        out = {}
        for name, code in cls._entry_points().items():
            index = code.find(cls.CALL)
            while index != -1:
                site = code[index:index + cls.CALL_SITE_CHARS]
                if "refresh=" in site:
                    out[name] = site
                    break
                index = code.find(cls.CALL, index + 1)
        return out

    def test_at_least_two_entry_points_refresh_the_store(self):
        callers = self._refreshing_callers()
        self.assertGreaterEqual(
            len(callers), 2,
            "the posted-lineup store must be refreshed from more than one "
            "operational entry point; found: %s" % sorted(callers))

    def test_at_least_one_caller_is_not_the_once_daily_loop(self):
        intraday = sorted(name for name in self._refreshing_callers()
                          if name != "daily_loop.sh")
        self.assertTrue(
            intraday,
            "daily_loop.sh runs once a day, hours before lineups post -- a "
            "refresh wired only there is the defect, not the fix")

    def test_every_caller_that_builds_the_store_names_refresh(self):
        # A single build() left on a plain resume is enough to re-freeze a live
        # date at whatever had posted when it ran, whatever the other callers
        # do -- so this is per call site, not a count over the repo.
        callers = self._refreshing_callers()
        for name, code in self._entry_points().items():
            if self.CALL in code:
                self.assertIn(name, callers,
                              "%s builds the posted-lineup store without "
                              "naming refresh= for the dates still filling "
                              "in" % name)

    def test_the_intraday_capture_path_refreshes_the_store(self):
        # Named explicitly: the capture path is the ONLY one that runs on the
        # cadence lineups actually post at. A rename should force a look here.
        self.assertIn("forward_capture.sh", self._refreshing_callers())

    def test_the_once_daily_loop_still_refreshes_rather_than_resuming(self):
        # It is the backstop that closes any game the intraday cadence missed.
        # A plain resume there re-freezes yesterday at whatever had posted by
        # 10:00Z the previous morning.
        self.assertIn("daily_loop.sh", self._refreshing_callers())

    def test_the_capture_cadence_gates_a_slate_pass_on_the_refresh(self):
        # Refreshing a store nothing re-reads moves no number. The measured
        # defect was decisions frozen 137 minutes after their own inputs
        # existed, and only a slate pass closes that.
        code = self._entry_points()["forward-capture.yml"]
        self.assertIn("lineup_store.slate_due()", code)
        self.assertIn("afternoon_slate.sh", code)


if __name__ == "__main__":
    unittest.main()
