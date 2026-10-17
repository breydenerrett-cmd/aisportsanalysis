"""A game POSTPONED and made up under the same game_pk is pending, then settled once.

2026-10-17. ALCS game 4 (Rays at Guardians, game_pk 849817) was rained out on
2026-10-16 and is made up on Sunday 10-18 under the SAME game_pk. Every paper
wager and card pick dated 10-16 names that pk. The settle step found no final
for it, refused, and the daily loop went red ("ESCALATE: engine settle
failed"); the ledger's settlement-gap check escalated the same date. Nothing had
failed -- the game was not played yet.

The standing policy these tests pin:

  * the schedule says the game was Postponed and the same pk has a later
    instance: the settle step prints "pending makeup on <date>" and exits 0 until
    that game is final -- nothing is written for it, nothing escalates;
  * when the makeup is final and in the results store, the pick-date rows settle
    from that final, exactly once (a rerun is a no-op);
  * a game with no result and NO postponement evidence still refuses, exactly as
    before -- an unanswered or empty schedule lookup is never "pending".

Everything is injected: temp ledgers, a temp manifest, fake schedule lookups. The
network and the repository's real stores are never touched.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import cli
from src.appstate import card_ledger
from src.engine import settle_slate
from src.ledger.chain import HashChainLedger
from src.pipeline import history
from tests.test_engine_settle import (
    SettleTestBase, _wager_row, _write_jsonl, _write_results_csv)

PK = 849817                 # ALCS G4, Rays at Guardians
PICK_DAY = "2026-10-16"     # the day it was rained out
MAKEUP_DAY = "2026-10-18"
OTHER_PK = 849816           # a game played on its own day


def _inst(state, detailed, date, pk=PK):
    return {"game_pk": pk, "date": date, "state": state, "detailed_state": detailed}


# What statsapi returned for gamePk 849817 on 2026-10-17: the Postponed entry
# already carries the NEW officialDate, and the makeup is a second entry.
POSTPONED = _inst("cancelled", "Postponed", MAKEUP_DAY)
MAKEUP_NOT_FINAL = _inst("pending", "Delayed Start", MAKEUP_DAY)
MAKEUP_FINAL_INST = _inst("final", "Final", MAKEUP_DAY)


def _lookup_for(instances):
    return lambda pk, day: history.postponed_makeup(
        pk, day, fetch_instances=lambda _pk: instances)


class PostponedMakeup(unittest.TestCase):
    def test_a_makeup_that_is_not_final_is_pending_with_its_date(self):
        info = history.postponed_makeup(PK, PICK_DAY, fetch_instances=lambda _: [POSTPONED, MAKEUP_NOT_FINAL])
        self.assertEqual(info["status"], history.MAKEUP_PENDING)
        self.assertEqual(info["makeup_date"], MAKEUP_DAY)
        self.assertEqual(info["game_pk"], str(PK))
        self.assertIn("makeup on 2026-10-18", info["detail"])

    def test_a_final_makeup_is_reported_final(self):
        info = history.postponed_makeup(PK, PICK_DAY, fetch_instances=lambda _: [POSTPONED, MAKEUP_FINAL_INST])
        self.assertEqual(info["status"], history.MAKEUP_FINAL)
        self.assertEqual(info["makeup_date"], MAKEUP_DAY)

    def test_only_the_postponement_with_a_new_date_is_pending_on_that_date(self):
        info = history.postponed_makeup(PK, PICK_DAY, fetch_instances=lambda _: [POSTPONED])
        self.assertEqual((info["status"], info["makeup_date"]), (history.MAKEUP_PENDING, MAKEUP_DAY))

    def test_a_postponement_with_no_new_date_yet_is_pending_and_says_so(self):
        info = history.postponed_makeup(
            PK, PICK_DAY, fetch_instances=lambda _: [_inst("cancelled", "Postponed", PICK_DAY)])
        self.assertEqual(info["status"], history.MAKEUP_PENDING)
        self.assertIsNone(info["makeup_date"])
        self.assertIn("not yet set", info["detail"])

    def test_no_positive_evidence_is_never_pending(self):
        def down(_pk):
            raise OSError("schedule unreachable")

        cases = {
            "cancelled for good": [_inst("cancelled", "Cancelled", PICK_DAY)],
            "played on its own day": [_inst("final", "Final", PICK_DAY)],
            "in progress": [_inst("pending", "In Progress", PICK_DAY)],
            "empty answer": [],
        }
        for label, instances in cases.items():
            self.assertIsNone(
                history.postponed_makeup(PK, PICK_DAY, fetch_instances=lambda _, i=instances: i), label)
        self.assertIsNone(history.postponed_makeup(PK, PICK_DAY, fetch_instances=down))
        self.assertIsNone(history.postponed_makeup(PK, "not-a-date", fetch_instances=lambda _: [POSTPONED]))

    def test_a_makeup_on_or_before_the_pick_day_is_not_a_makeup(self):
        earlier = [_inst("cancelled", "Postponed", PICK_DAY), _inst("final", "Final", PICK_DAY)]
        info = history.postponed_makeup(PK, PICK_DAY, fetch_instances=lambda _: earlier)
        self.assertEqual(info["status"], history.MAKEUP_PENDING)   # only the postponement counts
        self.assertIsNone(info["makeup_date"])


class EngineSettleLibrary(SettleTestBase):
    """run_settle: defer a pending-makeup wager, settle it from the same pk once, never twice."""

    def setUp(self):
        super().setUp()
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-pm", PK, 150, date_str=PICK_DAY, selection_id="sel-pm"),
        ])
        _write_results_csv(self.results_path, [])      # nothing ingested for 849817 yet

    def _store_makeup_final(self):
        _write_results_csv(self.results_path, [
            {"game_pk": PK, "date": MAKEUP_DAY, "home_score": 5, "away_score": 2}])

    def test_control_without_a_lookup_the_date_still_refuses(self):
        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle(PICK_DAY)
        self.assertIn("partial slate", str(ctx.exception))

    def test_pending_makeup_defers_and_writes_nothing(self):
        report = self.run_settle(PICK_DAY, makeup_lookup=_lookup_for([POSTPONED, MAKEUP_NOT_FINAL]))
        self.assertEqual(sum(len(s.settled) for s in report.systems), 0)
        self.assertEqual(len(report.pending_makeup), 1)
        pending = report.pending_makeup[0]
        self.assertEqual((pending["game_pk"], pending["makeup_date"], pending["n_wagers"]),
                         (str(PK), MAKEUP_DAY, 1))
        self.assertFalse(self.account_ledger_path_fn("test_system").exists())
        self.assertFalse(self.review_path.exists())

    def test_an_unanswered_lookup_is_still_a_refusal(self):
        for lookup in (lambda pk, day: None, _lookup_for([])):
            with self.assertRaises(settle_slate.SettleError):
                self.run_settle(PICK_DAY, makeup_lookup=lookup)

    def test_a_final_makeup_settles_from_the_same_game_pk_exactly_once(self):
        lookup = _lookup_for([POSTPONED, MAKEUP_FINAL_INST])
        self.run_settle(PICK_DAY, makeup_lookup=_lookup_for([POSTPONED, MAKEUP_NOT_FINAL]))  # the pending day
        self._store_makeup_final()                                                           # Sunday's final lands
        first = self.run_settle(PICK_DAY, makeup_lookup=lookup)
        again = self.run_settle(PICK_DAY, makeup_lookup=lookup)
        self.assertEqual(first.pending_makeup, ())
        settled = first.systems[0].settled
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0].outcome, "win")                    # home won 5-2 in the makeup
        self.assertAlmostEqual(settled[0].profit_units, 1.5)
        self.assertEqual(len(again.systems[0].settled), 0)
        self.assertEqual(again.systems[0].duplicate, 1)
        rows = HashChainLedger(self.account_ledger_path_fn("test_system")).read()
        self.assertEqual(len(rows), 1, "one settlement row, however many runs")

    def test_the_rest_of_the_date_settles_while_the_postponed_game_waits(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-pm", PK, 150, date_str=PICK_DAY, selection_id="sel-pm"),
            _wager_row("bet-ok", OTHER_PK, -120, date_str=PICK_DAY, selection_id="sel-ok"),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": OTHER_PK, "date": PICK_DAY, "home_score": 1, "away_score": 4}])
        report = self.run_settle(PICK_DAY, makeup_lookup=_lookup_for([POSTPONED, MAKEUP_NOT_FINAL]))
        self.assertEqual([s.bet.bet_id for s in report.systems[0].settled], ["bet-ok"])
        self.assertEqual(report.pending_makeup[0]["n_wagers"], 1)
        self._store_makeup_final()
        _write_results_csv(self.results_path, [
            {"game_pk": OTHER_PK, "date": PICK_DAY, "home_score": 1, "away_score": 4},
            {"game_pk": PK, "date": MAKEUP_DAY, "home_score": 5, "away_score": 2}])
        later = self.run_settle(PICK_DAY, makeup_lookup=_lookup_for([POSTPONED, MAKEUP_FINAL_INST]))
        self.assertEqual([s.bet.bet_id for s in later.systems[0].settled], ["bet-pm"])
        self.assertEqual(later.systems[0].duplicate, 1)

    def test_a_missing_result_with_no_postponement_still_refuses_the_whole_date(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-pm", PK, 150, date_str=PICK_DAY, selection_id="sel-pm"),
            _wager_row("bet-lost", 900009, 150, date_str=PICK_DAY, selection_id="sel-lost"),
        ])

        def lookup(pk, day):
            return _lookup_for([POSTPONED, MAKEUP_NOT_FINAL])(pk, day) if str(pk) == str(PK) else None

        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle(PICK_DAY, makeup_lookup=lookup)
        self.assertIn("900009", str(ctx.exception))
        self.assertNotIn(str(PK), str(ctx.exception).split("--", 1)[1].split("Never")[0])


class EngineSettleCommand(SettleTestBase):
    """The CLI: exit 0 and 'pending makeup on <date>' while pending; the carried sweep settles later."""

    def setUp(self):
        super().setUp()
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-pm", PK, 150, date_str=PICK_DAY, selection_id="sel-pm")])
        _write_results_csv(self.results_path, [])
        real_run = settle_slate.run_settle
        real_wagers = settle_slate.wagers_for_date
        real_ids = settle_slate.already_settled_bet_ids
        self.instances = [POSTPONED, MAKEUP_NOT_FINAL]

        def run(date_str, **kw):
            kw.setdefault("game_pk_map_path", self.game_pk_map_path)
            kw.setdefault("sport_source_paths", ())
            kw.setdefault("wagers_path", self.wagers_path)
            kw.setdefault("results_path", self.results_path)
            kw.setdefault("f5_historical_path", self.f5_path)
            kw.setdefault("boxscores_glob", self.boxscores_glob)
            kw.setdefault("information_events_path", self.info_events_path)
            kw.setdefault("decisions_path", self.decisions_path)
            kw.setdefault("review_path", self.review_path)
            kw.setdefault("scorecard_path", self.scorecard_path)
            kw.setdefault("account_ledger_path_fn", self.account_ledger_path_fn)
            return real_run(date_str, **kw)

        self._real_pm = history.postponed_makeup
        patches = (
            mock.patch.object(settle_slate, "run_settle", side_effect=run),
            mock.patch.object(settle_slate, "wagers_for_date",
                              side_effect=lambda d, path=None: real_wagers(
                                  d, path=path or str(self.wagers_path))),
            mock.patch.object(settle_slate, "already_settled_bet_ids",
                              side_effect=lambda s, fn=None: real_ids(
                                  s, fn or self.account_ledger_path_fn)),
            mock.patch.object(history, "postponed_makeup",
                              side_effect=lambda pk, day: self._real_pm(
                                  pk, day, fetch_instances=lambda _: self.instances)),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _settle(self, *argv):
        args = argparse.Namespace(date=argv[0], recent="--recent" in argv)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli._cmd_engine_settle(args)
        return code, out.getvalue(), err.getvalue()

    def _store_makeup_final(self):
        _write_results_csv(self.results_path, [
            {"game_pk": PK, "date": MAKEUP_DAY, "home_score": 5, "away_score": 2}])
        self.instances = [POSTPONED, MAKEUP_FINAL_INST]

    def test_pending_makeup_is_green_and_names_the_date(self):
        code, out, err = self._settle(PICK_DAY)
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("pending makeup on 2026-10-18: game_pk 849817 (1 wager(s))", out)
        self.assertNotIn("ERROR", err)
        self.assertNotIn("ESCALATE", out + err)

    def test_the_wagers_settle_when_the_makeup_is_final_and_not_twice(self):
        self.assertEqual(self._settle(PICK_DAY)[0], cli.EXIT_OK)
        self._store_makeup_final()
        code, out, _ = self._settle(PICK_DAY)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("settled 1 new", out)
        self.assertNotIn("pending makeup", out)
        code, out, _ = self._settle(PICK_DAY)
        self.assertIn("settled 0 new (1 already settled)", out)

    def test_the_carried_sweep_settles_an_earlier_date_once_the_makeup_lands(self):
        # Sunday 10-18 run: yesterday is 10-17; the sweep (from "today" 10-19) reaches 10-16.
        code, out, _ = self._settle("2026-10-18", "--recent")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("pending makeup on 2026-10-18", out)       # 10-16 is 2 days back from 10-18
        self.assertIn("1 earlier date(s) still owed", out)
        self._store_makeup_final()
        code, out, _ = self._settle("2026-10-19", "--recent")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("settled 1 new", out)
        # now nothing is owed: the next sweep opens no ledger and prints no settle
        code, out, _ = self._settle("2026-10-20", "--recent")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("0 earlier date(s) still owed", out)
        rows = HashChainLedger(self.account_ledger_path_fn("test_system")).read()
        self.assertEqual(len(rows), 1)

    def test_a_true_gap_in_the_sweep_still_fails_so_the_loop_escalates(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-lost", 900009, 150, date_str=PICK_DAY, selection_id="sel-lost")])
        self.instances = [_inst("cancelled", "Cancelled", PICK_DAY, pk=900009)]   # never played: not a makeup
        code, _, err = self._settle("2026-10-19", "--recent")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("900009", err)


class MakeupResultsForCards(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.manifest = Path(tmp.name) / "m.json"
        self.write_manifest({"cancelled": 1, "total": 1, "final": 0, "pending": 0})
        self.store = {str(PK): {"game_pk": str(PK), "date": MAKEUP_DAY, "home_score": "5", "away_score": "2"}}
        self.calls = []

    def write_manifest(self, entry):
        self.manifest.write_text(json.dumps({"dates": {PICK_DAY: entry}}), encoding="utf-8")

    def _games(self, day):
        self.calls.append(day)
        return [{"game_pk": PK, "detailed_state": "Postponed", "state": "cancelled", "date": MAKEUP_DAY}]

    def _rows(self, instances, store=None):
        return history.makeup_results_for_date(
            PICK_DAY, self.store if store is None else store, manifest_path=self.manifest,
            fetch_games=self._games, fetch_instances=lambda _: instances)

    def test_a_final_stored_makeup_is_returned_under_its_pk(self):
        self.assertEqual(list(self._rows([POSTPONED, MAKEUP_FINAL_INST])), [str(PK)])

    def test_nothing_comes_back_until_the_makeup_is_final_and_stored(self):
        self.assertEqual(self._rows([POSTPONED, MAKEUP_NOT_FINAL]), {})
        self.assertEqual(self._rows([POSTPONED, MAKEUP_FINAL_INST], store={}), {})

    def test_a_date_with_no_postponement_makes_no_request(self):
        self.write_manifest({"cancelled": 0, "total": 2, "final": 2, "pending": 0})
        self.assertEqual(self._rows([POSTPONED, MAKEUP_FINAL_INST]), {})
        self.assertEqual(self.calls, [])

    def test_a_failing_schedule_adds_nothing(self):
        def down(_day):
            raise OSError("down")

        self.assertEqual(history.makeup_results_for_date(
            PICK_DAY, self.store, manifest_path=self.manifest, fetch_games=down), {})


def _card_pick(game_pk=PK):
    return {
        "rank": 1, "label": "STRONG", "bet": "Take the home side", "why": ["because"],
        "market": "moneyline", "line": None, "side": "home", "team": "CLE",
        "team_name": "Guardians", "opponent_name": "Rays", "price": 150,
        "book": "draftkings", "books": 8, "confidence": 0.5, "market_probability": 0.4,
        "model_probability": 0.5, "game_pk": game_pk, "event_id": "e1", "away_team": "TB",
        "home_team": "CLE", "first_pitch_utc": "2026-10-17T00:08:00Z",
        "observed_utc": "2026-10-16T18:00:00Z", "model": {},
    }


class CardLedgerSettlesFromTheMakeup(unittest.TestCase):
    """card settle --recent: UNRESOLVED (a reported miss, exit 0) until the makeup is final, then graded once."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = os.path.join(tmp.name, "cards_v1.jsonl")
        self.manifest = self.dir / "m.json"
        self.manifest.write_text(json.dumps({"dates": {PICK_DAY: {"cancelled": 1, "total": 1}}}),
                                 encoding="utf-8")
        card = {
            "date": PICK_DAY, "rule": card_ledger.KIND_PUBLISHED, "basis": "b", "disclaimer": "d",
            "model_id": "test_model_v1", "calibrated": True,
            "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
            "filled": 0, "games_on_slate": 1, "picks": [_card_pick()], "total_picks": [],
        }
        card_ledger.publish(card, now="2026-10-16T20:00:00Z", path=self.path)
        self.store = {}
        self.instances = [POSTPONED, MAKEUP_NOT_FINAL]
        for patch in (
                mock.patch.object(history, "DEFAULT_MANIFEST", self.manifest),
                mock.patch.object(history, "read_results", side_effect=lambda *a, **k: dict(self.store)),
                mock.patch("src.providers.mlb.fetch_games",
                           side_effect=lambda d: [{"game_pk": PK, "detailed_state": "Postponed",
                                                   "state": "cancelled", "date": MAKEUP_DAY}]),
                mock.patch("src.providers.mlb.fetch_game_instances",
                           side_effect=lambda pk: self.instances)):
            patch.start()
            self.addCleanup(patch.stop)

    def _recent(self, today):
        fetch = cli._mlb_fetch_results_recent()
        return card_ledger.settle_recent(sport="mlb", fetch_results=fetch, path=self.path, today=today)

    def test_pending_then_settled_once(self):
        # Sat/Sun: the makeup is not played, so nothing is found under 10-16 -- a MISS, not a failure.
        pending = self._recent("2026-10-17")
        self.assertEqual((pending["settled"], len(pending["misses"])), (0, 1))
        self.assertIsNone(card_ledger.settled_row(PICK_DAY, path=self.path))
        note = cli._pending_makeup_note(PICK_DAY)
        self.assertIn("pending makeup", note)
        self.assertIn("849817 on 2026-10-18", note)

        # Sunday's game is final and ingested under 10-18.
        self.store = {str(PK): {"game_pk": str(PK), "date": MAKEUP_DAY,
                                "home_score": "5", "away_score": "2"}}
        self.instances = [POSTPONED, MAKEUP_FINAL_INST]
        done = self._recent("2026-10-19")
        self.assertEqual(done["settled"], 1)
        self.assertNotIn(PICK_DAY, [m["date"] for m in done["misses"]])
        row = card_ledger.settled_row(PICK_DAY, path=self.path)
        self.assertEqual([p["result"] for p in row["picks"]], ["WIN"])

        # Exactly once: the next pass finds the date fully settled and appends nothing.
        again = self._recent("2026-10-20")
        self.assertEqual(again["settled"], 0)
        settled_rows = [r for r in card_ledger._ledger(self.path).read()
                        if r.get("kind") == card_ledger.KIND_SETTLED]
        self.assertEqual(len(settled_rows), 1)


class V2FamilyRecentWindow(unittest.TestCase):
    """`card settle --rule v2 --recent`: the V2 family retries the week, with the makeup's result."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manifest = Path(tmp.name) / "m.json"
        manifest.write_text(json.dumps({"dates": {PICK_DAY: {"cancelled": 1, "total": 1}}}), encoding="utf-8")
        self.graded = []
        self.published = {PICK_DAY}
        self.settled = {}
        store = {str(PK): {"game_pk": str(PK), "date": MAKEUP_DAY, "home_score": "5", "away_score": "2"}}

        def settle_v2(day, by_pk, prop_box_rows=None, path=None):
            self.graded.append((day, sorted(map(str, by_pk))))
            self.settled[day] = True
            return {"wins": 1, "losses": 0}

        for patch in (
                mock.patch.object(history, "DEFAULT_MANIFEST", manifest),
                mock.patch.object(history, "read_results", return_value=store),
                mock.patch("src.providers.mlb.fetch_games",
                           return_value=[{"game_pk": PK, "detailed_state": "Postponed",
                                          "state": "cancelled", "date": MAKEUP_DAY}]),
                mock.patch("src.providers.mlb.fetch_game_instances",
                           return_value=[POSTPONED, MAKEUP_FINAL_INST]),
                mock.patch("src.pipeline.boxscores.read", return_value=[]),
                mock.patch.object(card_ledger, "published_row",
                                  side_effect=lambda d, path=None: {"date": d} if d in self.published else None),
                mock.patch.object(card_ledger, "settled_row",
                                  side_effect=lambda d, path=None: {"date": d} if d in self.settled else None),
                mock.patch.object(card_ledger, "_v2_has_unresolved", return_value=False),
                mock.patch.object(card_ledger, "settle_v2", side_effect=settle_v2)):
            patch.start()
            self.addCleanup(patch.stop)

    def _run(self, rule="v2"):
        args = argparse.Namespace(card_command="settle", sport="mlb", rule=rule, date="2026-10-19", recent=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.cmd_card(args)
        return code, out.getvalue()

    def test_the_postponed_day_is_graded_with_the_makeup_result_and_other_days_are_skipped(self):
        code, out = self._run()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual([d for d, _ in self.graded], [PICK_DAY])
        self.assertIn(str(PK), self.graded[0][1])
        self.assertIn("v2: settled 2026-10-16: 1-0", out)

    def test_a_fully_settled_day_is_not_opened_again(self):
        self._run()
        self.graded.clear()
        code, out = self._run()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(self.graded, [])
        self.assertIn("dates_settled=0", out)


class SettlementGapSplit(unittest.TestCase):
    RECS = [{"date": PICK_DAY, "game_pk": PK}, {"date": "2026-10-14", "game_pk": 5}]

    def test_a_date_whose_only_unsettled_game_is_pending_makeup_is_not_a_gap(self):
        gap, pending = history.split_pending_makeup_dates(
            [PICK_DAY], self.RECS, {}, lookup=_lookup_for([POSTPONED, MAKEUP_NOT_FINAL]))
        self.assertEqual((gap, pending), ([], {PICK_DAY: {str(PK): MAKEUP_DAY}}))

    def test_a_true_gap_stays_a_gap(self):
        gap, pending = history.split_pending_makeup_dates(
            ["2026-10-14"], self.RECS, {}, lookup=lambda pk, day: None)
        self.assertEqual((gap, pending), (["2026-10-14"], {}))

    def test_a_final_makeup_that_is_still_unsettled_is_a_gap(self):
        gap, _ = history.split_pending_makeup_dates(
            [PICK_DAY], self.RECS, {}, lookup=_lookup_for([POSTPONED, MAKEUP_FINAL_INST]))
        self.assertEqual(gap, [PICK_DAY])

    def test_one_non_pending_game_on_the_date_keeps_the_whole_date_a_gap(self):
        recs = self.RECS + [{"date": PICK_DAY, "game_pk": 77}]
        gap, pending = history.split_pending_makeup_dates(
            [PICK_DAY], recs, {}, lookup=lambda pk, day: (
                _lookup_for([POSTPONED, MAKEUP_NOT_FINAL])(pk, day) if pk == PK else None))
        self.assertEqual((gap, pending), ([PICK_DAY], {}))

    def test_a_date_with_no_unsettled_game_found_stays_a_gap(self):
        # The caller says the date is unsettled; if none of its games can be
        # shown pending, the disagreement is surfaced, never hidden.
        gap, pending = history.split_pending_makeup_dates(
            [PICK_DAY], self.RECS, {PK: object()}, lookup=lambda pk, day: None)
        self.assertEqual((gap, pending), ([PICK_DAY], {}))

    def test_a_settled_game_is_not_asked_about(self):
        asked = []
        recs = self.RECS + [{"date": PICK_DAY, "game_pk": 77}]
        history.split_pending_makeup_dates(
            [PICK_DAY], recs, {PK: object()},
            lookup=lambda pk, day: asked.append(pk))
        self.assertEqual(asked, [77])


class TheLoopReadsTheRightLines(unittest.TestCase):
    SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")

    def test_the_gap_escalate_still_reads_only_unsettled_past_dates(self):
        self.assertIn('grep -q "unsettled_past_dates: \\[.\\+\\]"', self.SCRIPT)
        self.assertIn("pending_makeup_dates:", self.SCRIPT)
        self.assertIn("history.split_pending_makeup_dates", self.SCRIPT)

    def test_the_carried_engine_sweep_and_v2_window_are_wired(self):
        self.assertIn('engine settle --date "$TODAY" --recent', self.SCRIPT)
        self.assertIn("card settle --rule all --recent", self.SCRIPT)
        self.assertIn("ESCALATE: engine settle failed for $YESTERDAY", self.SCRIPT)   # unchanged for a true failure


if __name__ == "__main__":
    unittest.main()
