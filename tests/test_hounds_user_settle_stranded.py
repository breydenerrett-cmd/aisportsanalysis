"""A dog's (or a manual) paper bet is never stranded by the settle window or a cancelled game.

THE AUDIT FINDING (2026-10-19). `user_settle.settle` looked back 14 days and had no cancelled-game
void, so a bet on a game cancelled, or made up, later than the window sat pending forever and later
read UNGRADED. The engine had the same bug (BAL at NYY 2026-09-27, game_pk 823490, Cancelled outright:
108 wagers ungraded for three weeks); it was fixed in `settle_slate` / `cli` by voiding a
schedule-Cancelled game with a named reason and sweeping every owed date. These tests pin the same
policy for the dogs' ledger and the manual ledger:

  * a 20-day-old pending bet is graded (no 14-day window);
  * a game the schedule shows Cancelled is voided once, with the engine's named reason;
  * a Postponed game stays pending, then grades once after the makeup is played;
  * a rerun writes nothing; an unanswered or failed lookup is never a void.

Everything is injected; nothing touches the network or the repository stores.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.engine import settle_slate
from src.hounds import user_engine as eng
from src.hounds import user_settle as st
from src.hounds.interact import manual
from src.pipeline import history
from tests._hounds_user_fixtures import DATE, EVENT, hound, result_row, standard_rows, utc
from tests.test_hounds_interact_fire import dog_of, rows_for

AT_LOCK = utc("2026-10-20T21:10:00Z")
OLD_NOW = utc("2026-11-09T12:00:00Z")        # 20 days after the slate: outside the old 14-day window
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}
CANCELLED = {"game_pk": PK, "status": history.CANCELLED_NEVER_PLAYED, "detail": "cancelled, never played"}
POSTPONED = {"status": "pending_makeup", "makeup_date": "2026-11-12"}


def _not_cancelled(pk, day):
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")
        eng.run(DATE, [hound(price_min=100, price_max=250)], standard_rows(), ledger=self.ledger,
                now=AT_LOCK, game_pk_index=INDEX)

    def settle(self, results, now=OLD_NOW, **kw):
        kw.setdefault("close_fn", lambda bet: None)
        kw.setdefault("game_pk_index", INDEX)
        return st.settle(ledger=self.ledger, now=now, mlb_results=results, **kw)

    def graded(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == st.KIND_GRADED]


class EveryOwedDate(Base):
    def test_a_twenty_day_old_pending_bet_is_graded_and_a_rerun_writes_nothing(self):
        results = {PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}
        report = self.settle(results)
        self.assertEqual((report["considered"], report["graded"]), (1, 1))
        self.assertEqual(self.graded()[0]["result"], "WIN")
        again = self.settle(results)
        self.assertEqual((again["considered"], again["graded"]), (0, 0))
        self.assertEqual(len(self.graded()), 1)

    def test_an_explicit_lookback_still_narrows_the_sweep(self):
        results = {PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}
        self.assertEqual(self.settle(results, lookback_days=14)["considered"], 0)
        self.assertEqual(self.graded(), [])


class Cancelled(Base):
    def test_a_cancelled_game_is_voided_once_with_the_named_reason(self):
        calls = []

        def lookup(pk, day):
            calls.append((pk, day))
            return CANCELLED
        report = self.settle({}, cancelled_lookup=lookup)
        self.assertEqual((report["graded"], report["pending"], report["by_result"]), (1, 0, {"VOID": 1}))
        self.assertEqual(report["voided_cancelled"][0]["game_pk"], PK)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"], g["profit_units_best"], g["clv_pts"]),
                         ("VOID", 0.0, 0.0, None))
        self.assertEqual(g["reason"], settle_slate.CANCELLED_VOID_REASON)
        self.assertEqual(calls, [(PK, DATE)])
        # idempotent: the bet is graded, so nothing is asked and nothing is written
        again = self.settle({}, cancelled_lookup=lookup)
        self.assertEqual((again["considered"], again["graded"]), (0, 0))
        self.assertEqual((len(self.graded()), len(calls)), (1, 1))
        rec = st.records_by_hound(eng.read_ledger(self.ledger))["u-test1"]["record"]
        self.assertEqual((rec["voids"], rec["units_average_price"]), (1, 0.0))

    def test_no_lookup_a_failed_lookup_or_an_empty_answer_never_voids(self):
        def boom(pk, day):
            raise RuntimeError("schedule down")
        for kw in ({}, {"cancelled_lookup": boom}, {"cancelled_lookup": _not_cancelled}):
            report = self.settle({}, **kw)
            self.assertEqual((report["graded"], report["pending"]), (0, 1))
        self.assertEqual(self.graded(), [])

    def test_a_game_still_being_played_is_not_asked_about(self):
        asked = []
        report = self.settle({}, now=utc("2026-10-20T23:30:00Z"),
                             cancelled_lookup=lambda pk, d: asked.append(pk) or CANCELLED)
        self.assertEqual((report["graded"], asked), (0, []))

    def test_a_result_in_the_store_wins_over_the_schedule(self):
        report = self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)},
                             cancelled_lookup=lambda pk, d: CANCELLED)
        self.assertEqual(self.graded()[0]["result"], "WIN")
        self.assertEqual(report["voided_cancelled"], [])

    def test_the_real_helper_voids_only_on_an_all_cancelled_schedule(self):
        def entries(*states):
            return lambda pk: [{"detailed_state": s, "date": DATE, "state": "x"} for s in states]

        def via(*states):
            return lambda pk, day: history.cancelled_game(pk, day, fetch_instances=entries(*states))
        self.assertEqual(self.settle({}, cancelled_lookup=via("Postponed"))["graded"], 0)
        self.assertEqual(self.settle({}, cancelled_lookup=via("Cancelled"))["graded"], 1)


class Postponed(Base):
    def test_a_postponed_game_stays_pending_then_grades_once_after_the_makeup(self):
        report = self.settle({}, postponed_lookup=lambda pk, d: POSTPONED, cancelled_lookup=_not_cancelled)
        self.assertEqual((report["graded"], report["pending"]), (0, 1))
        self.assertEqual(report["pending_makeup"][0]["makeup_date"], "2026-11-12")
        self.assertEqual(self.graded(), [])
        later = {PK: result_row(PK, "2026-11-12", "BOS", "SEA", 5, 3)}
        self.assertEqual(self.settle(later, postponed_lookup=lambda pk, d: POSTPONED,
                                     cancelled_lookup=_not_cancelled)["graded"], 1)
        self.assertEqual(self.settle(later)["graded"], 0)
        self.assertEqual([g["result"] for g in self.graded()], ["WIN"])

    def test_the_real_cancelled_helper_leaves_a_postponed_game_pending(self):
        entries = [{"detailed_state": "Postponed", "date": "2026-11-12", "state": "x"}]
        report = self.settle({}, cancelled_lookup=lambda pk, d: history.cancelled_game(
            pk, d, fetch_instances=lambda p: entries))
        self.assertEqual((report["graded"], report["pending"]), (0, 1))


class ManualTickets(unittest.TestCase):
    """The manual ledger is graded by the same function, so it inherits the sweep and the void."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        self.manual_ledger = os.path.join(self._tmp.name, "hounds_manual_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)
        manual.record(dog_of(), 7, EVENT, "moneyline", now=utc("2026-10-20T21:30:00Z"),
                      ledger=self.manual_ledger, rule_ledger=self.ledger,
                      rows_for=rows_for(standard_rows()))

    def settle(self, results, **kw):
        return manual.settle_manual(now=OLD_NOW, ledger=self.manual_ledger, mlb_results=results,
                                    game_pk_index=INDEX, close_fn=lambda b: None, **kw)

    def test_a_twenty_day_old_manual_ticket_grades(self):
        report = self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)})
        self.assertEqual(report["graded"], 1)
        self.assertEqual(manual.tickets("u-test1", path=self.manual_ledger, now=OLD_NOW)[0]["result"], "WIN")

    def test_a_manual_ticket_on_a_cancelled_game_voids_and_does_not_show_ungraded(self):
        self.assertEqual(self.settle({}, cancelled_lookup=lambda pk, d: CANCELLED)["graded"], 1)
        item = manual.tickets("u-test1", path=self.manual_ledger, now=OLD_NOW)[0]
        self.assertEqual(item["result"], "VOID")
        self.assertEqual(self.settle({}, cancelled_lookup=lambda pk, d: CANCELLED)["graded"], 0)


class RunnerWiring(unittest.TestCase):
    def test_the_pass_hands_both_schedule_lookups_to_the_settler_and_sets_no_window(self):
        from src.hounds import user_runner
        seen = {}

        def fake_settle(**kw):
            seen.update(kw)
            return {"considered": 0, "graded": 0, "pending": 0}
        hounds = [{"spec": {"sports": ["MLB"]}}]
        with mock.patch.object(eng, "iter_rows", lambda *a, **k: iter(())), \
             mock.patch.object(eng, "run", lambda *a, **k: {"date": "d", "games_seen": 0,
                                                            "bets_written": 0, "skipped": {}}), \
             mock.patch.object(eng, "_load_game_pk_index", lambda: {}), \
             mock.patch.object(st, "settle", fake_settle):
            user_runner.run_pass(now=utc("2026-10-20T15:00:00Z"), hounds=hounds,
                                 refresh_stats=lambda: None)
        self.assertTrue(callable(seen.get("cancelled_lookup")))
        self.assertTrue(callable(seen.get("postponed_lookup")))
        self.assertNotIn("lookback_days", seen)


if __name__ == "__main__":
    unittest.main()
