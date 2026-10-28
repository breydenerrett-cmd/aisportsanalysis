"""The capture tick end to end, against a scripted world (docs/PREREG_LIVE_TENNIS.md sections 5, 6, 9 and 13).

Every scenario runs a real `Runner` over a fake clock, scripted ESPN scoreboards and scripted Odds API boards, into
temp files, and then reads the ledger back. What is checked is behaviour: what was bought, what was written, what
was refused, and that the rows carry the numbers the pre-registration says they carry.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.core import odds as core_odds
from src.pipeline import creditlog
from src.research.live_tennis import board, config, decision, grade, markov
from src.research.live_tennis.ledger import PaperLedger, SnapshotStore
from src.research.live_tennis.runner import Runner

from tests.live_tennis_fixtures import (AWAY, HOME, KEY, MATCH_ID, World, competition, odds_event, quotes, read_jsonl,
                                        scoreboard)

ON = {config.ENV_SWITCH: "on"}
PRE_QUOTES = [("b1", -150, 130), ("b2", -140, 120), ("b3", -160, 140), ("b4", -150, 130)]
LIVE_QUOTES = [("b1", 100, -105), ("b2", 100, -105), ("b3", 105, -110)]


def pre_doc(world):
    return scoreboard(competition(MATCH_ID, HOME, AWAY, status="STATUS_SCHEDULED", state="pre", sets=[]))


def live_doc(sets, **kw):
    return scoreboard(competition(MATCH_ID, HOME, AWAY, status="STATUS_IN_PROGRESS", state="in", sets=sets, **kw))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.world = World("2026-11-02T09:30:00Z")
        self.world.events = [odds_event()]
        self.world.atp_doc = pre_doc(self.world)
        self.credit_path = self.dir / "credit_live.jsonl"
        self.runner = self.make_runner(self.world)

    def make_runner(self, world, subdir=""):
        base = self.dir / subdir if subdir else self.dir
        base.mkdir(parents=True, exist_ok=True)
        return Runner(ledger=PaperLedger(base / "ledger.jsonl"), snapshots=SnapshotStore(base / "snaps.jsonl"),
                      seams=world.seams(), env=ON, heartbeat_path=base / "heartbeat.jsonl",
                      credit_stores=[base / "credit_live.jsonl"])

    def tick(self, when=None, runner=None, world=None):
        w = world or self.world
        w.end_tick()
        if when:
            w.clock.set(when)
        return (runner or self.runner).tick()

    def set_live(self, when, quotes_spec=LIVE_QUOTES, stamp=None):
        self.world.odds_events = [odds_event(quotes=quotes(stamp or when, quotes_spec))]

    def prematch(self):
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T09:29:00Z", PRE_QUOTES))]
        report = self.tick("2026-11-02T09:30:00Z")
        self.assertEqual([c["purpose"] for c in report["calls"]], ["prematch"])
        return report

    @property
    def ledger(self):
        return self.runner.ledger

    def decisions(self):
        return self.ledger.of_kind("decision")

    def credit_rows(self):
        return creditlog.read(self.dir / "credit_live.jsonl")


class OffAndStopTests(Base):
    def test_off_makes_no_request_spends_nothing_and_writes_nothing(self):
        runner = Runner(ledger=PaperLedger(self.dir / "l.jsonl"), snapshots=SnapshotStore(self.dir / "s.jsonl"),
                        seams=self.world.seams(), env={}, heartbeat_path=self.dir / "h.jsonl",
                        credit_stores=[self.credit_path])
        report = runner.tick()
        self.assertTrue(report["off"])
        self.assertEqual((self.world.espn_calls, self.world.listing_calls, self.world.odds_calls), (0, 0, []))
        self.assertEqual([p.name for p in self.dir.iterdir()], [])

    def test_the_loop_returns_at_once_when_off(self):
        runner = Runner(ledger=PaperLedger(self.dir / "l.jsonl"), snapshots=SnapshotStore(self.dir / "s.jsonl"),
                        seams=self.world.seams(), env={}, heartbeat_path=self.dir / "h.jsonl")
        self.assertEqual(runner.run_loop(max_minutes=5), 1)
        self.assertEqual(self.world.espn_calls, 0)

    def test_past_the_stop_date_nothing_is_requested(self):
        report = self.tick("2027-02-01T10:00:00Z")
        self.assertTrue(report["stopped"])
        self.assertEqual(self.world.odds_calls, [])
        self.assertIn("stop date", " ".join(report["errors"]))

    def test_a_changed_constant_stops_capture(self):
        self.prematch()
        with mock.patch.object(config, "GAP_THRESHOLD_PP", 0.5):
            report = self.tick("2026-11-02T09:40:00Z")
        self.assertTrue(report["stopped"])
        self.assertIn("fingerprint", " ".join(report["errors"]))
        self.assertEqual(len(self.world.odds_calls), 1)


class PrematchTests(Base):
    def test_one_board_before_the_match_seeds_the_model_and_costs_one_credit(self):
        report = self.prematch()
        self.assertEqual(sum(c["credits"] for c in report["calls"]), 1)
        rows = self.credit_rows()
        self.assertEqual([(r["caller"], r["credits_used_last"], r["budget_band"]) for r in rows],
                         [(config.CREDIT_CALLER_PREMATCH, 1, "live_odds")])
        genesis = self.ledger.genesis()
        self.assertEqual(genesis["fingerprint"], config.fingerprint())
        snap = SnapshotStore(self.dir / "snaps.jsonl").recent(board.parse_utc("2026-11-02T00:00:00Z"))[0]
        item = snap["events"]["evt-1"]
        self.assertEqual((item["espn_before"]["state"], item["espn_after"]["state"]), ("pre", "pre"))
        self.assertEqual(item["prematch_p0"]["n_books"], 4)

    def test_a_match_that_is_not_yet_due_is_not_bought_for_and_a_recent_board_is_reused(self):
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T06:00:00Z", PRE_QUOTES))]
        report = self.tick("2026-11-02T06:00:00Z")                          # four hours before: outside the 90 minute lead
        self.assertEqual(report["calls"], [])
        self.prematch()
        again = self.tick("2026-11-02T09:50:00Z")                           # 20 minutes later: still fresh enough
        self.assertEqual(again["calls"], [])
        later = self.tick("2026-11-02T10:16:00Z")                           # 46 minutes after the board and the match 'pre'
        self.assertEqual([c["purpose"] for c in later["calls"]], ["prematch"])

    def test_a_board_taken_after_the_match_started_is_not_a_prematch_price(self):
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T09:29:00Z", PRE_QUOTES))]
        self.world.atp_doc = pre_doc(self.world)
        self.world.after_atp_doc = live_doc([(1, 0)])                        # the second read says the match has started
        self.tick("2026-11-02T09:30:00Z")
        snap = SnapshotStore(self.dir / "snaps.jsonl").recent(board.parse_utc("2026-11-02T00:00:00Z"))[0]
        self.assertIsNone(snap["events"]["evt-1"]["prematch_p0"])


class LifeOfABetTests(Base):
    def reach_set_two(self, live=LIVE_QUOTES):
        self.prematch()
        self.world.atp_doc = live_doc([(6, 3)])
        self.set_live("2026-11-02T11:00:00Z", live)
        return self.tick("2026-11-02T11:00:00Z")

    def test_a_set_start_arms_buys_one_board_and_writes_a_bet(self):
        report = self.reach_set_two()
        self.assertEqual((report["armed"], report["decisions"]), (1, 1))
        self.assertEqual([c["purpose"] for c in report["calls"]], ["decision"])
        armed = self.ledger.of_kind("armed")[0]
        self.assertEqual((armed["dp_id"], armed["set_number"], armed["sets_won_home"], armed["sets_won_away"]),
                         ("evt-1:S2", 2, 1, 0))
        self.assertEqual(armed["orientation"], "straight")
        self.assertEqual(armed["t_c"], "2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["side"], dec["attempt_no"]), (decision.BET, "home", 1))
        self.assertGreater(dec["gap_pp_home"], config.GAP_THRESHOLD_PP)
        self.assertEqual(dec["n_fresh"], 3)
        self.assertEqual(dec["n_stale"], 0)
        # the model numbers on the row are the model's, from the pre-match consensus
        pre = decision.prematch_p0(board.parse_quotes(odds_event(quotes=quotes("2026-11-02T09:29:00Z", PRE_QUOTES))))
        want = markov.model_prices(pre["p0_home"], 0.64, 2, config.SKILL_GAP_BOUND, 1, 0)
        self.assertAlmostEqual(dec["model"]["p_match_home"], want["p_match_home"], places=12)
        self.assertAlmostEqual(dec["model"]["p_set_home"], want["p_set_home"], places=12)
        self.assertAlmostEqual(dec["p0"]["p0_home"], pre["p0_home"], places=12)
        self.assertEqual(dec["entry"]["best_price"], 105.0)
        self.assertEqual(dec["entry"]["best_book"], "b3")

    def test_the_reference_is_bought_after_fifteen_minutes_and_clv_is_computed(self):
        self.reach_set_two()
        quiet = self.tick("2026-11-02T11:11:00Z")                            # 660 s: a reference is due but not yet bought for
        self.assertEqual(quiet["calls"], [])
        self.world.atp_doc = live_doc([(6, 3), (2, 1)])
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T11:15:00Z", [("b1", -130, 110), ("b2", -135, 115), ("b3", -125, 105)]))]
        report = self.tick("2026-11-02T11:15:30Z")
        self.assertEqual([c["purpose"] for c in report["calls"]], ["reference"])
        ref = self.ledger.of_kind("reference")[0]
        dec = self.decisions()[0]
        self.assertEqual(ref["dp_id"], "evt-1:S2")
        self.assertEqual(ref["delay_s"], 930)
        self.assertFalse(ref["shadow"])
        fair_ref = sum(core_odds.devig_two_way(h, a)[0] for h, a in ((-130, 110), (-135, 115), (-125, 105))) / 3
        fair_entry = sum(core_odds.devig_two_way(h, a)[0] for h, a in ((100, -105), (100, -105), (105, -110))) / 3
        avg_entry = sum(core_odds.american_to_probability(h) for h in (100, 100, 105)) / 3
        best_entry = core_odds.american_to_probability(105)
        self.assertAlmostEqual(ref["m1"], 100 * (fair_ref - fair_entry), places=9)
        self.assertAlmostEqual(ref["m2"], 100 * (fair_ref - avg_entry), places=9)
        self.assertAlmostEqual(ref["m2_best"], 100 * (fair_ref - best_entry), places=9)
        self.assertAlmostEqual(ref["m2_best"] - ref["m2"], 100 * (avg_entry - best_entry), places=9)
        self.assertEqual(dec["side"], ref["side"])
        # bought once: nothing is owed after it
        self.assertEqual(self.tick("2026-11-02T11:20:00Z")["calls"], [])

    def test_no_credit_is_spent_on_a_reference_for_a_match_that_is_no_longer_in_progress(self):
        self.reach_set_two()
        self.world.atp_doc = scoreboard(competition(MATCH_ID, HOME, AWAY, status="STATUS_RETIRED", state="post",
                                                    sets=[(6, 3), (2, 1)], winner="a"))
        before = len(self.world.odds_calls)
        report = self.tick("2026-11-02T11:16:00Z")                          # past the 900 s mark, match over
        self.assertEqual((report["calls"], len(self.world.odds_calls)), ([], before))
        late = self.tick("2026-11-02T11:26:00Z")
        self.assertEqual(late["no_reference"], 1)
        self.assertEqual(self.ledger.of_kind("no_reference")[0]["cause"], "NO_SNAPSHOT_IN_WINDOW")

    def test_a_later_board_for_any_purpose_serves_as_the_reference_without_a_dedicated_call(self):
        self.reach_set_two()
        self.world.atp_doc = live_doc([(6, 3), (3, 2)])
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T11:09:00Z", [("b1", -130, 110), ("b2", -135, 115), ("b3", -125, 105)]))]
        # a board bought for another reason in the window: here, a second pre-match style call is not due, so store one directly
        snap = {"snapshot_id": "k@x", "key": KEY, "purpose": "decision", "t_req": "2026-11-02T11:10:00Z",
                "t_resp": "2026-11-02T11:10:00Z", "credits": 1, "usage": None, "events": {"evt-1": {
                    "quotes": board.parse_quotes(self.world.odds_events[0]),
                    "espn_before": {"status": "STATUS_IN_PROGRESS"}, "espn_after": {"status": "STATUS_IN_PROGRESS"}}}}
        self.runner.snapshots.append(snap)
        report = self.tick("2026-11-02T11:11:00Z")
        self.assertEqual(report["calls"], [])
        self.assertEqual(report["references"], 1)
        self.assertEqual(self.ledger.of_kind("reference")[0]["delay_s"], 600)

    def test_no_reference_when_the_window_passes_and_the_cause_is_counted(self):
        self.reach_set_two()
        (self.dir / "credit_live.jsonl").write_text(json.dumps(
            {"utc": "2026-11-02T11:00:30Z", "caller": config.CREDIT_CALLER, "credits_used_last": config.DAILY_CREDIT_CAP,
             "budget_band": "live_odds", "credits_remaining": 49000}) + "\n", encoding="utf-8")
        self.world.atp_doc = live_doc([(6, 3), (5, 4)])
        report = self.tick("2026-11-02T11:20:00Z")                          # a reference is due; the cap refuses it
        self.assertEqual(report["calls"], [])
        self.assertTrue(report["refused"])
        late = self.tick("2026-11-02T11:26:00Z")                            # 1,560 s after the decision
        self.assertEqual(late["no_reference"], 1)
        row = self.ledger.of_kind("no_reference")[0]
        self.assertEqual(row["cause"], "NO_SNAPSHOT_IN_WINDOW")
        self.assertEqual(row["diagnostics"]["in_window"], 0)

    def test_outcome_settles_the_bet_through_the_existing_espn_rule(self):
        self.reach_set_two()
        final = scoreboard(competition(MATCH_ID, HOME, AWAY, status="STATUS_FINAL", state="post",
                                       sets=[(6, 3), (4, 6), (6, 2)], winner="a"))
        out = grade.settle(self.ledger, espn_json=lambda url: final if "/atp/" in url else {"events": []},
                           now=board.parse_utc("2026-11-02T13:00:00Z"))
        self.assertEqual(out["outcomes"], 1)
        outcome = self.ledger.of_kind("outcome")[0]
        dec = self.decisions()[0]
        self.assertEqual((outcome["bet_side"], outcome["bet_result"], outcome["match_winner_home"]), ("home", "WIN", True))
        self.assertFalse(outcome["set_winner_home"])                          # the home player lost set 2 (4-6)
        self.assertAlmostEqual(outcome["profit_avg"], 1.0 / dec["entry"]["avg_implied"] - 1.0, places=12)
        self.assertAlmostEqual(outcome["profit_best"], core_odds.american_to_decimal(105) - 1.0, places=12)
        self.assertEqual(outcome["model_p_match_home"], dec["model"]["p_match_home"])
        # settling twice writes nothing new
        again = grade.settle(self.ledger, espn_json=lambda url: final if "/atp/" in url else {"events": []},
                             now=board.parse_utc("2026-11-02T13:05:00Z"))
        self.assertEqual(again["outcomes"], 0)

    def test_outcome_waits_while_the_match_is_unsettled_and_voids_a_walkover_style_result(self):
        self.reach_set_two()
        live = live_doc([(6, 3), (3, 2)])
        out = grade.settle(self.ledger, espn_json=lambda url: live if "/atp/" in url else {"events": []},
                           now=board.parse_utc("2026-11-02T12:00:00Z"))
        self.assertEqual((out["outcomes"], out["pending"]), (0, 1))
        retired_early = scoreboard(competition(MATCH_ID, HOME, AWAY, status="STATUS_RETIRED", state="post",
                                               sets=[(2, 1)], winner="a"))
        out = grade.settle(self.ledger, espn_json=lambda url: retired_early if "/atp/" in url else {"events": []},
                           now=board.parse_utc("2026-11-02T12:30:00Z"))
        self.assertEqual(out["outcomes"], 1)                                  # retired before a set completed: void, not a win
        outcome = self.ledger.of_kind("outcome")[0]
        self.assertEqual((outcome["bet_result"], outcome["profit_avg"], outcome["match_winner_home"]), ("VOID", 0.0, None))


class ExclusionTests(Base):
    def reach(self, spec=LIVE_QUOTES, stamp=None, doc=None):
        self.prematch()
        self.world.atp_doc = doc or live_doc([(6, 3)])
        self.set_live("2026-11-02T11:00:00Z", spec, stamp)

    def test_no_prematch_price_is_decided_at_once_and_costs_no_credit(self):
        self.world.atp_doc = live_doc([(6, 3)])
        self.set_live("2026-11-02T11:00:00Z")
        report = self.tick("2026-11-02T11:00:00Z")
        self.assertEqual(report["calls"], [])
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "NO_PREMATCH_PRICE"))
        self.assertEqual(self.world.odds_calls, [])
        self.assertEqual(self.credit_rows(), [])

    def test_model_out_of_range_is_decided_at_once(self):
        # a pre-match price of 0.99999 is beyond anything a skill gap of +-0.15 can produce (the ceiling is about 0.99988)
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T09:29:00Z", [("b1", -9999999, 9999999),
                                                                                  ("b2", -9999999, 9999999),
                                                                                  ("b3", -9999999, 9999999)]))]
        self.tick("2026-11-02T09:30:00Z")
        self.world.atp_doc = live_doc([(6, 3)])
        report = self.tick("2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "MODEL_OUT_OF_RANGE"))
        self.assertEqual(len(self.world.odds_calls), 1)                       # only the pre-match board was ever bought
        self.assertEqual(report["calls"], [])

    def test_a_score_that_moved_between_the_two_reads_is_excluded(self):
        self.reach()
        self.world.after_atp_doc = live_doc([(6, 3), (1, 0)])
        report = self.tick("2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "SCORE_MOVED"))
        self.assertEqual(report["calls"][0]["credits"], 1)                    # the call was made and billed, and is recorded

    def test_a_different_set_count_on_the_second_read_is_also_moved(self):
        self.reach()
        self.world.after_atp_doc = live_doc([(6, 3), (2, 6)])                 # set 2 already over
        self.tick("2026-11-02T11:00:00Z")
        self.assertEqual(self.decisions()[0]["reason"], "SCORE_MOVED")

    def test_stale_quotes_never_count_and_a_thin_board_gets_one_more_attempt(self):
        self.prematch()
        self.world.atp_doc = live_doc([(6, 3)])
        spec = [("b1", 100, -105), ("b2", 100, -105), ("b3", 105, -110), ("b4", 100, -105), ("b5", 100, -105)]
        events = quotes("2026-11-02T10:59:59Z", spec[:3]) + quotes("2026-11-02T11:00:00Z", spec[3:])
        self.world.odds_events = [odds_event(quotes=events)]
        first = self.tick("2026-11-02T11:00:00Z")
        self.assertEqual(self.decisions(), [])
        attempt = self.ledger.of_kind("attempt")[0]
        self.assertEqual((attempt["attempt_no"], attempt["result"], attempt["n_fresh"], attempt["n_stale"]), (1, "THIN_BOARD", 2, 3))
        self.assertEqual(self.tick("2026-11-02T11:00:30Z")["calls"], [])      # too soon: attempts are 45 s apart
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T11:00:45Z", spec))]
        second = self.tick("2026-11-02T11:00:46Z")
        self.assertEqual(len(second["calls"]), 1)
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["attempt_no"], dec["n_fresh"]), (decision.BET, 2, 5))
        self.assertEqual(len(self.ledger.of_kind("attempt")), 1)

    def test_a_board_thin_on_the_last_attempt_is_excluded_as_thin(self):
        self.reach(stamp="2026-11-02T10:59:00Z")
        self.tick("2026-11-02T11:00:00Z")
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T10:59:00Z", LIVE_QUOTES))]
        self.tick("2026-11-02T11:00:50Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"], dec["attempt_no"]), (decision.EXCLUDED, "THIN_BOARD", 2))
        self.assertEqual(dec["n_fresh"], 0)

    def test_an_arbitrage_board_is_inconsistent_and_final(self):
        self.reach([("b1", 120, -125), ("b2", -125, 120), ("b3", 110, -115)])
        self.tick("2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "INCONSISTENT_BOARD"))
        self.assertEqual(self.ledger.of_kind("attempt"), [])

    def test_below_threshold_is_a_no_bet_and_is_still_a_row(self):
        # the model rates the home player 0.80 after a set up (from a 0.58 pre-match price); this board agrees with it
        self.reach([("b1", -400, 330), ("b2", -410, 340), ("b3", -390, 320)])
        self.tick("2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual(dec["status"], decision.NO_BET)
        self.assertEqual(dec["reason"], "BELOW_THRESHOLD")
        self.assertEqual(len(dec["fresh_quotes"]), 3)
        self.assertEqual(self.ledger.of_kind("reference"), [])
        self.assertEqual(grade.pending_references(self.ledger), [])

    def test_the_credit_cap_excludes_the_decision_point_and_says_so(self):
        self.reach()
        (self.dir / "credit_live.jsonl").write_text(json.dumps(
            {"utc": "2026-11-02T10:00:00Z", "caller": config.CREDIT_CALLER, "credits_used_last": config.DAILY_CREDIT_CAP,
             "budget_band": "live_odds", "credits_remaining": 49000}) + "\n", encoding="utf-8")
        report = self.tick("2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "CREDIT_REFUSED"))
        self.assertIn("daily cap", dec["detail"]["guard"])
        self.assertEqual(len(self.world.odds_calls), 1)                       # only the earlier pre-match board
        self.assertTrue(report["refused"])

    def test_an_unreadable_balance_refuses_and_a_low_balance_refuses(self):
        self.reach()
        self.world.remaining = config.DAILY_CREDIT_CAP                          # far under the repository floor
        report = self.tick("2026-11-02T11:00:00Z")
        self.assertEqual(self.decisions()[0]["reason"], "CREDIT_REFUSED")
        self.assertIn("floor", report["refused"][0]["reason"])

    def test_a_failed_paid_call_consumes_no_attempt_and_the_window_then_expires(self):
        self.reach()
        self.world.fail_odds = True
        report = self.tick("2026-11-02T11:00:00Z")
        self.assertIn("odds", " ".join(report["errors"]))
        self.assertEqual((self.decisions(), self.ledger.of_kind("attempt")), ([], []))
        self.tick("2026-11-02T11:02:00Z")
        self.assertEqual(self.decisions(), [])
        self.tick("2026-11-02T11:04:10Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "WINDOW_EXPIRED"))

    def test_a_match_that_has_moved_on_is_excluded_not_priced(self):
        self.reach()
        self.world.fail_odds = True
        self.tick("2026-11-02T11:00:00Z")
        self.world.fail_odds = False
        self.world.atp_doc = live_doc([(6, 3), (2, 1)])
        self.tick("2026-11-02T11:01:30Z")
        self.assertEqual(self.decisions()[0]["reason"], "SCORE_MOVED")

    def test_a_format_contradiction_is_recorded_not_guessed(self):
        self.prematch()
        self.world.atp_doc = live_doc([(6, 4), (4, 6), (3, 3), (0, 0)])         # a set listed after one that is unfinished
        self.tick("2026-11-02T11:00:00Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "FORMAT_CONTRADICTION"))

    def test_decided_and_first_set_matches_are_never_armed(self):
        self.prematch()
        for sets in ([(3, 2)], [(0, 0)], [(6, 3), (6, 2)]):
            self.world.atp_doc = live_doc(sets)
            self.tick("2026-11-02T11:00:00Z")
        self.assertEqual(self.ledger.of_kind("armed"), [])

    def test_a_deciding_set_start_arms_set_three(self):
        self.prematch()
        self.world.atp_doc = live_doc([(6, 3), (3, 6)])
        self.set_live("2026-11-02T12:00:00Z")
        self.tick("2026-11-02T12:00:00Z")
        armed = self.ledger.of_kind("armed")[0]
        self.assertEqual((armed["dp_id"], armed["sets_won_home"], armed["sets_won_away"]), ("evt-1:S3", 1, 1))

    def test_an_away_leading_crossed_orientation_is_mapped_to_home_and_away(self):
        self.world.events = [odds_event(home=AWAY, away=HOME)]                  # the book lists the players the other way round
        self.world.odds_events = [odds_event(home=AWAY, away=HOME, quotes=quotes("2026-11-02T09:29:00Z", PRE_QUOTES))]
        self.tick("2026-11-02T09:30:00Z")
        self.world.atp_doc = live_doc([(6, 3)])                                 # ESPN a (HOME in ESPN's list) won set 1
        self.world.odds_events = [odds_event(home=AWAY, away=HOME, quotes=quotes("2026-11-02T11:00:00Z", LIVE_QUOTES))]
        self.tick("2026-11-02T11:00:00Z")
        armed = self.ledger.of_kind("armed")[0]
        self.assertEqual(armed["orientation"], "crossed")
        self.assertEqual((armed["sets_won_home"], armed["sets_won_away"]), (0, 1))     # the book's home player is behind


class StalenessAndShadowTests(Base):
    def test_a_quote_between_the_last_poll_and_our_sight_of_the_set_is_stale_strictly_and_shadow_permissively(self):
        self.prematch()
        self.world.atp_doc = live_doc([(3, 2)])                                   # set 1 still in progress
        self.tick("2026-11-02T10:59:00Z")
        self.world.atp_doc = live_doc([(6, 3)])
        self.set_live("2026-11-02T11:00:00Z", LIVE_QUOTES, stamp="2026-11-02T10:59:30Z")
        self.tick("2026-11-02T11:00:00Z")
        armed = self.ledger.of_kind("armed")[0]
        self.assertEqual(armed["t_prev_poll"], "2026-11-02T10:59:00Z")
        self.assertEqual(self.ledger.of_kind("attempt")[0]["n_fresh"], 0)         # strictly: nothing counts
        self.world.odds_events = [odds_event(quotes=quotes("2026-11-02T10:59:30Z", LIVE_QUOTES))]
        self.tick("2026-11-02T11:00:50Z")
        dec = self.decisions()[0]
        self.assertEqual((dec["status"], dec["reason"]), (decision.EXCLUDED, "THIN_BOARD"))
        self.assertEqual(dec["permissive"]["status"], decision.BET)               # a loose rule WOULD have bet
        self.assertTrue(dec["shadow_bet"])
        self.assertEqual(len(dec["all_quotes"]), 3)
        # a shadow bet never earns a dedicated reference call
        self.world.atp_doc = live_doc([(6, 3), (3, 2)])
        report = self.tick("2026-11-02T11:20:00Z")
        self.assertEqual(report["calls"], [])
        shadow = [p for p in grade.resolve_references(self.ledger, self.runner.snapshots, board.parse_utc("2026-11-02T11:20:00Z"),
                                                      write=False)["pending"]]
        self.assertEqual([p["shadow"] for p in shadow], [True])

    def test_the_previous_poll_survives_a_restart_through_the_heartbeat_file(self):
        self.prematch()
        self.world.atp_doc = live_doc([(3, 2)])
        self.tick("2026-11-02T10:59:00Z")
        fresh_runner = self.make_runner(self.world)                               # a new process: nothing in memory
        self.assertEqual(fresh_runner._last_ok_poll, board.parse_utc("2026-11-02T10:59:00Z"))


class DeterminismAndBookkeepingTests(Base):
    def run_story(self, subdir):
        world = World("2026-11-02T09:30:00Z")
        world.events = [odds_event()]
        world.atp_doc = pre_doc(world)
        runner = self.make_runner(world, subdir)
        world.odds_events = [odds_event(quotes=quotes("2026-11-02T09:29:00Z", PRE_QUOTES))]
        self.tick("2026-11-02T09:30:00Z", runner, world)
        world.atp_doc = live_doc([(6, 3)])
        world.odds_events = [odds_event(quotes=quotes("2026-11-02T11:00:00Z", LIVE_QUOTES))]
        self.tick("2026-11-02T11:00:00Z", runner, world)
        world.atp_doc = live_doc([(6, 3), (2, 1)])
        world.odds_events = [odds_event(quotes=quotes("2026-11-02T11:15:00Z", [("b1", -130, 110), ("b2", -135, 115), ("b3", -125, 105)]))]
        self.tick("2026-11-02T11:15:30Z", runner, world)
        return runner.ledger.rows()

    def test_the_same_world_produces_byte_identical_decisions_and_references(self):
        first, second = self.run_story("one"), self.run_story("two")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual([r["kind"] for r in first], ["genesis", "armed", "decision", "reference"])
        self.assertEqual(first[-1]["row_hash"], second[-1]["row_hash"])            # the chain agrees too

    def test_a_decision_point_is_decided_once_across_restarts(self):
        self.prematch()
        self.world.atp_doc = live_doc([(6, 3)])
        self.set_live("2026-11-02T11:00:00Z")
        self.tick("2026-11-02T11:00:00Z")
        before = self.ledger.rows()
        again = self.make_runner(self.world)
        for when in ("2026-11-02T11:00:10Z", "2026-11-02T11:00:20Z"):
            again.seams.clock.set(when) if hasattr(again.seams.clock, "set") else self.world.clock.set(when)
            self.world.end_tick()
            again.tick()
        self.assertEqual(len(again.ledger.of_kind("decision")), 1)
        self.assertEqual(len(again.ledger.of_kind("armed")), 1)
        self.assertEqual([r["row_hash"] for r in again.ledger.rows()][:len(before)], [r["row_hash"] for r in before])

    def test_a_heartbeat_row_is_written_every_tick_with_the_counts(self):
        self.prematch()
        self.tick("2026-11-02T09:41:00Z")
        beats = read_jsonl(self.dir / "heartbeat.jsonl")
        self.assertEqual(len(beats), 2)
        self.assertEqual(beats[0]["calls"][0]["purpose"], "prematch")
        self.assertTrue(all(b["espn_ok"] for b in beats))

    def test_an_event_ESPN_cannot_pair_is_counted_not_traded(self):
        self.world.events = [odds_event(home="Zed Nobody", away="Yan Unknown")]
        self.world.clock.set("2026-11-02T10:30:00Z")
        report = self.tick("2026-11-02T10:30:00Z")
        self.assertEqual(report["paired"], 0)
        self.assertEqual(report["unmatched_live"], ["evt-1"])                     # it has started and nothing can score it
        self.assertEqual(self.world.odds_calls, [])
        self.assertEqual(read_jsonl(self.dir / "heartbeat.jsonl")[-1]["unmatched_live"], ["evt-1"])

    def test_an_espn_outage_stops_the_tick_and_is_recorded(self):
        def broken(url):
            raise OSError("down")
        seams = self.world.seams()
        seams.espn_json = broken
        runner = Runner(ledger=PaperLedger(self.dir / "o.jsonl"), snapshots=SnapshotStore(self.dir / "os.jsonl"),
                        seams=seams, env=ON, heartbeat_path=self.dir / "oh.jsonl", credit_stores=[self.credit_path])
        self.world.clock.set("2026-11-02T09:30:00Z")
        report = runner.tick()
        self.assertFalse(report["espn_ok"])
        self.assertEqual(self.world.odds_calls, [])
        self.assertEqual(read_jsonl(self.dir / "oh.jsonl")[0]["espn_ok"], False)

    def test_the_loop_ticks_sleeps_and_stops_at_max_minutes(self):
        self.world.clock.set("2026-11-02T04:00:00Z")
        ticks = self.runner.run_loop(max_minutes=20)
        self.assertGreaterEqual(ticks, 3)                                         # idle polling is every five minutes
        self.assertEqual(self.world.odds_calls, [])


if __name__ == "__main__":
    unittest.main()
