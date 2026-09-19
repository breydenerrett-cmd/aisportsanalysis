"""Tests for src.appstate.card_ledger.settle_recent -- the self-healing
settle window (owner directive 2026-09-19).

WHY THIS FILE EXISTS
---------------------
scripts/daily_loop.sh used to call `card settle --date $YESTERDAY` exactly
once, for MLB and NFL alike. A date got exactly one attempt for the rest of
time: a late publish, a feed outage, a transient error, and that date's
picks were orphaned, silently, forever. That is what happened to the only
NFL pick ever published (Bills -225, 2026-09-17): checked directly against
the ledger two days after the game finished, its published row existed and
its settled row did not.

Every test here runs against a temporary ledger path and fully injects
`fetch_results` -- no network, no real clock beyond the `now`/`today` each
test passes in, per this project's HARD RULES.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger


def _card(date="2026-09-17", picks=None, total_picks=None):
    return {
        "date": date,
        "rule": card_ledger.KIND_PUBLISHED,
        "basis": "basis sentence",
        "disclaimer": "disclaimer sentence",
        "model_id": "test_model_v1",
        "calibrated": True,
        "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
        "filled": 0,
        "games_on_slate": 1,
        "picks": picks if picks is not None else [_pick()],
        "total_picks": total_picks or [],
    }


def _pick(rank=1, side="home", price=-225, game_pk=9001, game_id=None,
          sport=None):
    pick = {
        "rank": rank, "label": "STRONG", "bet": "Take the home side",
        "why": ["because"], "market": "moneyline", "line": None, "side": side,
        "team": "HOME", "team_name": "Home Team", "opponent_name": "Away Team",
        "price": price, "book": "draftkings", "books": 8,
        "confidence": 0.74, "market_probability": 0.74,
        "model_probability": 0.64, "game_pk": game_pk, "event_id": "e1",
        "away_team": "AWAY", "home_team": "HOME",
        "first_pitch_utc": "2026-09-17T23:05:00Z",
        "observed_utc": "2026-09-17T18:00:00Z", "model": {},
    }
    if sport:
        pick["sport"] = sport
        pick["game_id"] = game_id or f"{sport}_{game_pk}"
    return pick


class SettleRecentCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")


class YesterdayIsAlwaysChecked(SettleRecentCase):
    def test_no_published_row_for_yesterday_reports_the_honest_reason(self):
        """Offset 1 (yesterday) is always attempted, even with nothing
        published -- a quiet night must still show up in the output as an
        honest miss, not vanish from it the way the old bare "nothing to
        settle" line effectively did."""
        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=lambda d: {}, path=self.path,
            today="2026-09-18")

        self.assertEqual(totals["dates_checked"], 1)
        self.assertEqual(totals["settled"], 0)
        self.assertEqual(len(totals["misses"]), 1)
        self.assertEqual(totals["misses"][0]["date"], "2026-09-17")
        self.assertEqual(totals["misses"][0]["reason"],
                         card_ledger.REASON_NO_PUBLISHED_ROW)


class NoResultsYetStaysRetryable(SettleRecentCase):
    def test_empty_results_map_does_not_void_the_pick(self):
        """PARENT-COMMIT BEHAVIOUR THIS GUARDS AGAINST: calling settle()
        directly with an empty results map VOIDs every pick on the spot
        (grade_pick's honest-VOID-on-no-final-score rule) -- correct once a
        game truly has no result coming, wrong when the feed simply has not
        posted yet. Before the pre-settle gate this test pins, a
        settle_recent() built by naively calling settle() every pass would
        have permanently VOIDed this pick on its very first retry."""
        card_ledger.publish(_card("2026-09-17"), now="2026-09-17T23:00:00Z",
                            path=self.path, sport="nfl")

        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=lambda d: {}, path=self.path,
            today="2026-09-18")

        self.assertEqual(totals["settled"], 0)
        miss = totals["misses"][0]
        self.assertEqual(miss["date"], "2026-09-17")
        self.assertIn("no final score yet", miss["reason"])
        self.assertIsNone(card_ledger.settled_row(
            "2026-09-17", path=self.path, sport="nfl"))


class ResultsPresentButUnmatchedIsFlaggedAsAJoinIssue(SettleRecentCase):
    def test_nonempty_results_with_no_matching_game_reports_join_reason(self):
        """The feed came back non-empty -- something is finishing games --
        but none of THIS date's own picks are in it. Per src/joins.py's own
        distinction, a non-empty-vs-non-empty zero-match join is worth
        calling out differently from an honest empty."""
        card_ledger.publish(_card("2026-09-17", picks=[_pick(game_pk=9001)]),
                            now="2026-09-17T23:00:00Z", path=self.path, sport="nfl")

        totals = card_ledger.settle_recent(
            sport="nfl",
            fetch_results=lambda d: {"9999": {"home_score": 10, "away_score": 3}},
            path=self.path, today="2026-09-18")

        self.assertEqual(totals["settled"], 0)
        miss = totals["misses"][0]
        self.assertIn("none matched", miss["reason"])
        self.assertIn("check the join, not the feed", miss["reason"])
        self.assertIsNone(card_ledger.settled_row(
            "2026-09-17", path=self.path, sport="nfl"))


class MatchingResultSettles(SettleRecentCase):
    def test_matching_game_id_settles_and_grades(self):
        card_ledger.publish(
            _card("2026-09-17", picks=[_pick(game_pk=9001, side="home",
                                             price=-225)]),
            now="2026-09-17T23:00:00Z", path=self.path, sport="nfl")

        totals = card_ledger.settle_recent(
            sport="nfl",
            fetch_results=lambda d: {"9001": {"home_score": 27, "away_score": 13}},
            path=self.path, today="2026-09-18")

        self.assertEqual(totals["settled"], 1)
        self.assertEqual(totals["misses"], [])
        row = card_ledger.settled_row("2026-09-17", path=self.path, sport="nfl")
        self.assertIsNotNone(row)
        self.assertEqual(row["wins"], 1)
        self.assertEqual(row["losses"], 0)


class TheLateePublishStory(SettleRecentCase):
    def test_a_date_missed_on_pass_one_settles_on_pass_two(self):
        """The 2026-09-17 story itself, at the card_ledger layer: a card
        published, a first settle_recent pass that cannot yet see a final
        score, and a SECOND pass -- run the next day, as scripts/
        daily_loop.sh does every morning -- that finally can. The old
        single-shot `--date $YESTERDAY` call had no second pass; this
        function's whole purpose is providing one."""
        card_ledger.publish(_card("2026-09-17", picks=[_pick(game_pk=9001)]),
                            now="2026-09-17T23:00:00Z", path=self.path, sport="nfl")

        totals1 = card_ledger.settle_recent(
            sport="nfl", fetch_results=lambda d: {}, path=self.path,
            today="2026-09-18")
        self.assertEqual(totals1["settled"], 0)

        totals2 = card_ledger.settle_recent(
            sport="nfl",
            fetch_results=lambda d: (
                {"9001": {"home_score": 27, "away_score": 13}}
                if d == "2026-09-17" else {}),
            path=self.path, today="2026-09-19")

        self.assertEqual(totals2["settled"], 1)
        self.assertIsNotNone(card_ledger.settled_row(
            "2026-09-17", path=self.path, sport="nfl"))


class OlderDatesAreSkippedWhenNothingIsOutstanding(SettleRecentCase):
    def test_fetch_results_not_called_for_a_date_with_no_published_row(self):
        """Not even yesterday (offset 1, always CHECKED) calls
        fetch_results when nothing is published for it -- `_settle_one_date`
        returns REASON_NO_PUBLISHED_ROW before it ever reaches the results
        source, so a quiet night (the overwhelmingly common case) costs
        zero fetches, not one 'yesterday' fetch plus zero for every older
        date."""
        calls = []

        def fetch(date_str):
            calls.append(date_str)
            return {}

        totals = card_ledger.settle_recent(sport="nfl", fetch_results=fetch,
                                           path=self.path, today="2026-09-25")

        self.assertEqual(calls, [])
        self.assertEqual(totals["misses"],
                         [{"date": "2026-09-24",
                           "reason": card_ledger.REASON_NO_PUBLISHED_ROW}])

    def test_fetch_results_not_called_for_an_already_settled_older_date(self):
        """An older date that is already settled must not be re-fetched
        either -- 'a settled week does not re-run the fetch seven times a
        night for nothing' (matches live_ledger.settle_recent's own
        reasoning)."""
        card_ledger.publish(_card("2026-09-20", picks=[_pick(game_pk=9002)]),
                            now="2026-09-20T23:00:00Z", path=self.path, sport="nfl")
        card_ledger.settle(
            "2026-09-20", {"9002": {"home_score": 1, "away_score": 0}},
            path=self.path, sport="nfl", now="2026-09-21T10:00:00Z")

        calls = []

        def fetch(date_str):
            calls.append(date_str)
            return {}

        card_ledger.settle_recent(sport="nfl", fetch_results=fetch,
                                  path=self.path, today="2026-09-25")

        self.assertNotIn("2026-09-20", calls)

    def test_a_published_unsettled_date_beyond_the_window_is_never_checked(self):
        card_ledger.publish(_card("2026-09-01", picks=[_pick(game_pk=9003)]),
                            now="2026-09-01T23:00:00Z", path=self.path, sport="nfl")

        calls = []

        def fetch(date_str):
            calls.append(date_str)
            return {}

        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=fetch, path=self.path,
            today="2026-09-25", window_days=7)

        self.assertNotIn("2026-09-01", calls)
        self.assertTrue(all(m["date"] != "2026-09-01" for m in totals["misses"]))


class AlreadySettledYesterdayIsReportedHonestly(SettleRecentCase):
    def test_yesterday_already_settled_is_not_double_counted(self):
        card_ledger.publish(_card("2026-09-17", picks=[_pick(game_pk=9004)]),
                            now="2026-09-17T23:00:00Z", path=self.path, sport="nfl")
        card_ledger.settle(
            "2026-09-17", {"9004": {"home_score": 3, "away_score": 1}},
            path=self.path, sport="nfl", now="2026-09-18T10:00:00Z")

        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=lambda d: {}, path=self.path,
            today="2026-09-18")

        self.assertEqual(totals["settled"], 0)
        self.assertEqual(totals["misses"][0]["reason"],
                         card_ledger.REASON_ALREADY_SETTLED)


class FeedErrorsAreCaughtNotRaised(SettleRecentCase):
    def test_a_raising_fetch_results_is_a_legible_miss(self):
        """A results source that raises (feed down, not configured,
        network error) must not crash the whole settle_recent pass, and
        must not be treated as an honest empty result -- it gets its own
        reason so a bad feed is distinguishable from a quiet one."""
        card_ledger.publish(_card("2026-09-17", picks=[_pick(game_pk=9005)]),
                            now="2026-09-17T23:00:00Z", path=self.path, sport="nfl")

        def raises(date_str):
            raise RuntimeError("feed unreachable")

        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=raises, path=self.path,
            today="2026-09-18")

        self.assertEqual(totals["settled"], 0)
        self.assertIn("feed unreachable", totals["misses"][0]["reason"])
        self.assertIsNone(card_ledger.settled_row(
            "2026-09-17", path=self.path, sport="nfl"))


class OutputShapeIsStable(SettleRecentCase):
    def test_output_has_exactly_the_documented_keys(self):
        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=lambda d: {}, path=self.path,
            today="2026-09-18")
        self.assertEqual(set(totals.keys()),
                         {"dates_checked", "settled", "misses"})


class TotalPicksAreGatedTheSameWayGamePicksAre(SettleRecentCase):
    def test_total_pick_keys_also_require_a_matching_result(self):
        card = _card("2026-09-17", picks=[],
                     total_picks=[{
                         "rank": 1, "label": "STRONG", "bet": "Over 8.5",
                         "why": ["x"], "line": 8.5, "side": "over",
                         "price": -110, "book": "dk", "books": 8,
                         "game_pk": 9006, "event_id": "e1",
                         "away_team": "AWAY", "home_team": "HOME",
                         "first_pitch_utc": "2026-09-17T23:05:00Z",
                         "observed_utc": "2026-09-17T18:00:00Z",
                     }])
        # Publish requires at least one game pick OR total pick to be
        # non-empty overall; card_ledger.publish refuses only when BOTH
        # picks and total_picks are empty at once is not the rule -- it
        # refuses when `picks` (game picks) is empty. So exercise this
        # through settle() directly instead of publish(), which is the
        # documented behaviour (`publish`'s own docstring: an empty
        # `picks` refuses regardless of total_picks).
        card["picks"] = [_pick(game_pk=1, side="home")]
        card["total_picks"][0]["game_pk"] = 9006
        card_ledger.publish(card, now="2026-09-17T23:00:00Z",
                            path=self.path, sport="nfl")

        totals = card_ledger.settle_recent(
            sport="nfl", fetch_results=lambda d: {"9006": {"home_score": 6,
                                                            "away_score": 5}},
            path=self.path, today="2026-09-18")

        # game pick 1 has no matching result (feed only carries 9006) --
        # but the TOTAL pick's key (9006) does match, so at least one key
        # matched overall and settle() runs; the game pick grades VOID on
        # its own (existing settle() behaviour, unchanged by this feature)
        # while the total pick grades normally.
        self.assertEqual(totals["settled"], 1)
        row = card_ledger.settled_row("2026-09-17", path=self.path, sport="nfl")
        self.assertEqual(row["voids"], 1)
        self.assertEqual(row["total_picks"][0]["result"], "WIN")


if __name__ == "__main__":
    unittest.main()
