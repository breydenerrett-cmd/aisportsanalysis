"""`ledger` settle: a game that is not final on its own date.

Two real cases kept the daily loop red from 2026-09-23 on. Game 824785
(TOR at BAL) was rained out on 09-22 and played 09-23: the schedule for 09-22
says "Postponed" forever, so a lookup by date never sees the final. Game
823490 (BAL at NYY, 09-27) was cancelled and never played, so nothing will
ever be final. Both sat "not final yet" and `unsettled_past_dates` escalated
every morning.

Nothing here touches the network or the real ledger: the schedule fetches,
the ledger read and the ledger write are all injected.
"""
import argparse
import contextlib
import io
import unittest
from unittest import mock

from src import cli
from src.pipeline import grading, ledger


def _rec(pk, date, away="TOR", home="BAL"):
    return {"kind": "recommendation", "game_pk": pk, "date": date,
            "away_team": away, "home_team": home, "verdict": "no_play",
            "commence_time": f"{date}T22:35:00Z",
            "recorded_at": f"{date}T10:00:00+00:00"}


def _game(pk, date, state, detailed, away_score=None, home_score=None):
    return {"game_pk": pk, "date": date, "state": state,
            "detailed_state": detailed, "away_score": away_score,
            "home_score": home_score,
            "winner": None if away_score is None else ("BAL" if home_score > away_score else "TOR"),
            "home_won": None if away_score is None else int(home_score > away_score),
            "total_runs": None if away_score is None else away_score + home_score,
            "first_five": {"complete": state == "final"}}


class Resolution(unittest.TestCase):
    def test_postponed_then_played_resolves_to_the_final_instance(self):
        row = _rec(824785, "2026-09-22")
        instances = [_game(824785, "2026-09-23", "cancelled", "Postponed"),
                     _game(824785, "2026-09-23", "final", "Final", 2, 4)]
        outcome, found = cli._moved_game_resolution(
            row, instances[0], lambda pk: instances)
        self.assertEqual(outcome, "final")
        self.assertEqual((found["away_score"], found["home_score"]), (2, 4))

    def test_cancelled_everywhere_is_a_void(self):
        row = _rec(823490, "2026-09-27", "BAL", "NYY")
        only = _game(823490, "2026-09-27", "cancelled", "Cancelled")
        outcome, reason = cli._moved_game_resolution(row, only, lambda pk: [only])
        self.assertEqual(outcome, "void")
        self.assertIn("Cancelled", reason)

    def test_postponed_without_a_makeup_yet_stays_pending(self):
        row = _rec(1, "2026-09-22")
        only = _game(1, "2026-09-22", "cancelled", "Postponed")
        self.assertEqual(
            cli._moved_game_resolution(row, only, lambda pk: [only]),
            ("pending", None))

    def test_in_progress_game_makes_no_extra_request(self):
        row = _rec(1, "2026-09-22")
        live = _game(1, "2026-09-22", "pending", "In Progress")

        def boom(pk):
            raise AssertionError("no by-game lookup for a game still being played")

        self.assertEqual(cli._moved_game_resolution(row, live, boom), ("pending", None))

    def test_a_failed_lookup_is_never_a_void(self):
        row = _rec(1, "2026-09-22")

        def down(pk):
            raise OSError("schedule unreachable")

        self.assertEqual(cli._moved_game_resolution(row, None, down), ("pending", None))

    def test_empty_answer_is_never_a_void(self):
        row = _rec(1, "2026-09-22")
        self.assertEqual(cli._moved_game_resolution(row, None, lambda pk: []),
                         ("pending", None))


class SettleCommand(unittest.TestCase):
    def _run(self, entries, by_date, by_pk):
        written = []

        def fake_settle(game_pk, result, closing=None, closing_reason=None, **_):
            written.append({"game_pk": game_pk, "result": result,
                            "closing": closing, "closing_reason": closing_reason})

        args = argparse.Namespace(action=None, status=False)
        out = io.StringIO()
        with mock.patch.object(ledger, "read", return_value=entries), \
                mock.patch.object(ledger, "settle", side_effect=fake_settle), \
                mock.patch("src.providers.mlb.fetch_games",
                           side_effect=lambda d: by_date.get(d, [])), \
                mock.patch("src.providers.mlb.fetch_game_instances",
                           side_effect=lambda pk: by_pk.get(pk, [])), \
                mock.patch("src.pipeline.snapshots.read", return_value=[]), \
                contextlib.redirect_stdout(out):
            code = cli.cmd_ledger(args)
        return code, written, out.getvalue()

    def test_both_real_cases_settle_and_a_live_game_does_not(self):
        entries = [_rec(824785, "2026-09-22"),
                   _rec(823490, "2026-09-27", "BAL", "NYY"),
                   _rec(849844, "2026-10-01", "PHI", "ATL")]
        postponed = _game(824785, "2026-09-23", "cancelled", "Postponed")
        made_up = _game(824785, "2026-09-23", "final", "Final", 2, 4)
        cancelled = _game(823490, "2026-09-27", "cancelled", "Cancelled")
        live = _game(849844, "2026-10-01", "pending", "Scheduled")
        code, written, text = self._run(
            entries,
            {"2026-09-22": [postponed], "2026-09-27": [cancelled], "2026-10-01": [live]},
            {824785: [postponed, made_up], 823490: [cancelled]})
        self.assertEqual(code, cli.EXIT_OK)
        by_pk = {w["game_pk"]: w for w in written}
        self.assertEqual(set(by_pk), {824785, 823490})

        played = by_pk[824785]
        self.assertEqual(played["result"]["played_date"], "2026-09-23")
        self.assertEqual((played["result"]["away_score"], played["result"]["home_score"]), (2, 4))
        self.assertEqual(played["result"]["winner"], "BAL")
        self.assertIsNone(played["closing"])
        self.assertIn("postponed from 2026-09-22", played["closing_reason"])

        void = by_pk[823490]
        self.assertIs(void["result"]["void"], True)
        self.assertIsNone(void["result"]["winner"])
        self.assertIsNone(void["result"]["home_won"])
        self.assertIsNone(void["closing"])
        self.assertIn("1 not final yet", text)
        self.assertIn("1 cancelled, recorded as void", text)

    def test_a_game_final_on_its_own_date_is_settled_as_before(self):
        entries = [_rec(7, "2026-09-20")]
        final = _game(7, "2026-09-20", "final", "Final", 1, 3)
        code, written, text = self._run(entries, {"2026-09-20": [final]}, {})
        self.assertEqual(len(written), 1)
        self.assertNotIn("played_date", written[0]["result"])
        self.assertNotIn("void", written[0]["result"])
        self.assertNotIn("postponed", written[0]["closing_reason"] or "")
        self.assertNotIn("void", text)


class NoCloseIsEverDerived(unittest.TestCase):
    """A stale pre-postponement quote must not become a recorded close."""

    def _entries(self, result):
        rec = _rec(5, "2026-09-22")
        settlement = {"kind": "settlement", "game_pk": 5, "result": result,
                      "closing": None, "closing_reason": "x",
                      "settled_at": "2026-09-24T10:00:00+00:00"}
        return rec, [rec, settlement]

    def _snapshots_with_a_price(self, rec):
        from src.pipeline import snapshots
        return [{"away_team": rec["away_team"], "home_team": rec["home_team"],
                 "commence_time": rec["commence_time"], "market": "h2h",
                 "book": "fanduel", "observed_utc": "2026-09-22T20:00:00Z",
                 "book_last_update": "2026-09-22T19:59:00Z",
                 "prices": {"away": 110, "home": -130},
                 "game_key": snapshots.game_key(rec["away_team"], rec["home_team"],
                                                rec["commence_time"])}]

    def test_helper(self):
        self.assertIsNone(grading.settlement_has_no_close({"result": {"winner": "BAL"}}))
        self.assertIn("cancelled", grading.settlement_has_no_close({"result": {"void": True}}))
        self.assertIn("later date", grading.settlement_has_no_close(
            {"result": {"played_date": "2026-09-23"}}))

    def test_control_an_ordinary_settlement_does_derive_a_close(self):
        # Without this the skip test below could pass because the fixture
        # prices nothing at all.
        rec, entries = self._entries({"winner": "BAL"})
        found = grading.find_backfillable_closings(
            entries, self._snapshots_with_a_price(rec))
        self.assertEqual(len(found["derivable"]), 1)

    def test_backfill_skips_void_and_moved_games(self):
        for result in ({"void": True}, {"played_date": "2026-09-23", "winner": "BAL"}):
            rec, entries = self._entries(result)
            found = grading.find_backfillable_closings(
                entries, self._snapshots_with_a_price(rec))
            self.assertEqual(found["to_append"], [], result)
            self.assertEqual(found["derivable"], [], result)
            self.assertEqual(len(found["not_derivable"]), 1, result)


if __name__ == "__main__":
    unittest.main()
