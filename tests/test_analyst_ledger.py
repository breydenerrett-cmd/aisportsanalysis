"""The analyst's ledger: publish before first pitch, chain, tamper, grade, record."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.analyst import critic, grading, ledger, packet as P
from tests import analyst_fixtures as F


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = str(self.dir / "analyst_v1.jsonl")
        self.packets = str(self.dir / "packets")
        self.usage = str(self.dir / "usage.jsonl")
        self.addCleanup(self._tmp.cleanup)

    def publish(self, packet=None, verified=None, now=F.NOW, **kw):
        packet = packet or F.build()
        verified = verified or critic.verify(packet, F.good_output(packet))
        return ledger.publish(packet, verified, now=now, model="claude-sonnet-5-5",
                              path=self.path, packet_dir=self.packets, **kw)

    def lines(self):
        return Path(self.path).read_text(encoding="utf-8").splitlines() if os.path.exists(self.path) else []


def take(packet, slot_id, side, **over):
    """A hand-made TAKE (or TAKE_OTHER_SIDE) on the option with this side."""
    market = packet["markets"][slot_id]
    opt = next(o for o in market["options"] if o["side"] == side)
    call = {"slot_id": slot_id, "market": market["market"], "selection": opt["selection"],
            "verdict": "TAKE" if opt["selection"] == market["lean"] else "TAKE_OTHER_SIDE",
            "price": opt["best"]["price"], "book": opt["best"]["book"], "fair_estimate": 0.6,
            "confidence": "low", "reasons": [{"claim": "x", "evidence": []}], "pass_price": 100,
            "what_would_change_it": "y", "verification": {"status": "verified", "problems": []}}
    call.update(over)
    return call


def verified(calls):
    return critic.Verified(summary="s", summary_status="ok", summary_problems=[], calls=calls,
                           struck=[], model_critic="off")


class Publishing(Base):
    def test_it_writes_a_chained_row_and_a_packet_file_that_verify(self):
        row, created = self.publish()
        self.assertTrue(created)
        self.assertEqual(row["kind"], ledger.KIND_PUBLISHED)
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["packet_hash"], P.packet_hash(F.build()))
        self.assertEqual(len(self.lines()), 1)
        report = ledger.verify(self.path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["rows"], 1)
        self.assertEqual(ledger.read_packet(row)["game"]["game_id"], "NYY-TB-2026-10-03-1")

    def test_every_call_carries_its_grading_spec(self):
        row, _ = self.publish()
        ml = next(c for c in row["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual(ml["grading"]["family"], "moneyline")
        self.assertEqual(ml["grading"]["side"], "away")
        self.assertIsNotNone(ml["grading"]["reference_price"])

    def test_the_struck_audit_trail_is_kept_in_the_row(self):
        packet = F.build()
        out = F.good_output(packet)
        out["calls"][0]["reasons"][1]["claim"] = "He has a 2.17 ERA."
        row, _ = self.publish(packet, critic.verify(packet, out))
        self.assertEqual(row["struck"][0]["slot_id"], "moneyline")
        self.assertIn("2.17", json.dumps(row["struck"][0]["original"]))
        self.assertEqual(next(c for c in row["calls"] if c["slot_id"] == "moneyline")["verdict"], "PASS")

    def test_the_store_is_its_own_file_and_not_a_card_ledger(self):
        self.assertEqual(ledger.STORE, os.path.join("evidence", "analyst_v1.jsonl"))
        from src.appstate import card_ledger
        self.assertNotIn("analyst", card_ledger.CARD_STORE)


class RefusalAfterFirstPitch(Base):
    def test_a_game_that_has_started_is_refused_and_nothing_is_written(self):
        after = datetime(2026, 10, 3, 22, 31, 0, tzinfo=timezone.utc)
        with self.assertRaises(ledger.GameStarted):
            self.publish(now=after)
        self.assertEqual(self.lines(), [])
        self.assertFalse((self.dir / "packets").exists())

    def test_exactly_at_first_pitch_is_refused(self):
        with self.assertRaises(ledger.GameStarted):
            self.publish(now=datetime(2026, 10, 3, 22, 30, 0, tzinfo=timezone.utc))

    def test_one_second_before_first_pitch_is_allowed(self):
        row, created = self.publish(now=datetime(2026, 10, 3, 22, 29, 59, tzinfo=timezone.utc))
        self.assertTrue(created)

    def test_a_game_that_is_not_pending_is_refused_even_before_the_clock(self):
        packet = F.build(state="live")
        with self.assertRaises(ledger.GameStarted) as ctx:
            self.publish(packet)
        self.assertIn("not pending", str(ctx.exception))

    def test_an_unknown_first_pitch_is_refused(self):
        packet = F.build()
        packet["game"]["first_pitch_utc"] = None
        with self.assertRaises(ledger.GameStarted):
            self.publish(packet)

    def test_the_lock_lead_moves_the_deadline_earlier(self):
        with self.assertRaises(ledger.GameStarted):
            self.publish(now=datetime(2026, 10, 3, 22, 10, 0, tzinfo=timezone.utc), lock_lead_minutes=30)

    def test_the_one_rule_the_cli_asks_before_paying_for_the_model(self):
        packet = F.build()
        self.assertIsNone(ledger.publish_refusal(packet, F.NOW))
        self.assertIn("passed", ledger.publish_refusal(
            packet, datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc)))


class FrozenAndVersioned(Base):
    def test_publishing_twice_returns_the_first_row_and_writes_nothing(self):
        first, _ = self.publish()
        again, created = self.publish()
        self.assertFalse(created)
        self.assertEqual(again["row_hash"], first["row_hash"])
        self.assertEqual(len(self.lines()), 1)

    def test_refresh_appends_a_new_version_that_supersedes_the_old(self):
        first, _ = self.publish()
        second, created = self.publish(refresh=True, now=F.NOW + timedelta(hours=1))
        self.assertTrue(created)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["supersedes"], first["row_hash"])
        self.assertEqual(len(self.lines()), 2)
        self.assertEqual(ledger.latest_published(ledger.rows(self.path))["NYY-TB-2026-10-03-1"]["version"], 2)

    def test_refresh_is_refused_once_the_game_is_graded(self):
        self.publish()
        ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [],
                          now=F.NOW, path=self.path)
        with self.assertRaises(ledger.AnalystLedgerError):
            self.publish(refresh=True)

    def test_a_refresh_after_first_pitch_is_still_refused(self):
        self.publish()
        with self.assertRaises(ledger.GameStarted):
            self.publish(refresh=True, now=datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc))


class ChainAndTamper(Base):
    def setUp(self):
        super().setUp()
        self.publish()
        ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [],
                          now=F.NOW, path=self.path)

    def test_a_clean_ledger_verifies(self):
        self.assertTrue(ledger.verify(self.path)["ok"])
        self.assertEqual(len(self.lines()), 2)

    def test_editing_a_published_row_is_detected(self):
        lines = self.lines()
        row = json.loads(lines[0])
        row["calls"][0]["verdict"] = "TAKE"
        lines[0] = json.dumps(row, sort_keys=True)
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = ledger.verify(self.path)
        self.assertFalse(report["ok"])
        self.assertIn("chain broken at line 1", report["problems"][0])

    def test_deleting_a_row_is_detected(self):
        Path(self.path).write_text(self.lines()[1] + "\n", encoding="utf-8")
        report = ledger.verify(self.path)
        self.assertFalse(report["ok"])

    def test_reordering_rows_is_detected(self):
        a, b = self.lines()
        Path(self.path).write_text(b + "\n" + a + "\n", encoding="utf-8")
        self.assertFalse(ledger.verify(self.path)["ok"])

    def test_editing_a_graded_row_breaks_the_chain_from_there(self):
        lines = self.lines()
        row = json.loads(lines[1])
        row["calls"][0]["result"] = "LOSS"          # it was a WIN
        lines[1] = json.dumps(row, sort_keys=True)
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = ledger.verify(self.path)
        self.assertFalse(report["ok"])
        self.assertIn("line 2", report["problems"][0])

    def test_a_replaced_packet_file_is_detected(self):
        files = list((self.dir / "packets").rglob("*.json.gz"))
        self.assertEqual(len(files), 1)
        other = F.build(multibook_rows=F.multibook_rows(home_ml=(-140, -127, -132)))
        with gzip.open(files[0], "wb") as fh:
            fh.write(json.dumps(other, sort_keys=True).encode())
        report = ledger.verify(self.path)
        self.assertFalse(report["ok"])
        self.assertTrue(any("packet file" in p for p in report["problems"]))

    def test_a_missing_packet_file_is_detected(self):
        for f in (self.dir / "packets").rglob("*.json.gz"):
            f.unlink()
        self.assertFalse(ledger.verify(self.path)["ok"])


class GradingEachMarket(Base):
    def setUp(self):
        super().setUp()
        self.packet = F.build()

    def grade_all(self, away, home, box=None):
        calls = [take(self.packet, "moneyline", "away"),
                 take(self.packet, "run_line", "away"),
                 take(self.packet, "total", "under"),
                 take(self.packet, "team_total_away", "over"),
                 take(self.packet, "team_total_home", "under")]
        self.publish(self.packet, verified(calls))
        counts = ledger.grade_date(F.DATE, {849835: {"away_score": str(away), "home_score": str(home)}},
                                   box or [], now=F.NOW, path=self.path)
        graded = [r for r in ledger.rows(self.path) if r["kind"] == ledger.KIND_GRADED][-1]
        return counts, {c["slot_id"]: c for c in graded["calls"]}, graded

    def test_a_road_win_wins_the_moneyline_and_covers_the_run_line(self):
        _, g, graded = self.grade_all(5, 3)
        self.assertEqual(g["moneyline"]["result"], "WIN")
        self.assertAlmostEqual(g["moneyline"]["profit_units"], 1.17)
        self.assertEqual(g["run_line"]["result"], "WIN")
        self.assertEqual(g["total"]["result"], "LOSS")           # Under 7, eight runs
        self.assertEqual(g["team_total_away"]["result"], "WIN")  # five against 3.5
        self.assertEqual(g["team_total_home"]["result"], "WIN")  # TB Under 3.5 with three
        self.assertEqual(graded["final"], {"away_score": 5, "home_score": 3})

    def test_a_one_run_road_loss_still_covers_plus_one_and_a_half(self):
        _, g, _ = self.grade_all(2, 3)
        self.assertEqual(g["moneyline"]["result"], "LOSS")
        self.assertEqual(g["moneyline"]["profit_units"], -1.0)
        self.assertEqual(g["run_line"]["result"], "WIN")

    def test_a_two_run_road_loss_does_not_cover(self):
        _, g, _ = self.grade_all(2, 4)
        self.assertEqual(g["run_line"]["result"], "LOSS")

    def test_an_ungraded_game_is_unresolved_not_a_loss(self):
        calls = [take(self.packet, "moneyline", "away")]
        self.publish(self.packet, verified(calls))
        counts = ledger.grade_date(F.DATE, {}, [], now=F.NOW, path=self.path)
        self.assertEqual(counts["graded"], 0)
        self.assertEqual([r["kind"] for r in ledger.rows(self.path)], [ledger.KIND_PUBLISHED])

    def test_pushes_on_a_whole_number_line(self):
        spec = {"family": "run_line", "side": "away", "line": 1.0}
        c = {"slot_id": "x", "selection": "s", "verdict": "TAKE", "price": -110, "grading": spec}
        out = grading.grade_call(c, 1, {"away_score": "2", "home_score": "3"}, {}, frozenset())
        self.assertEqual((out["result"], out["profit_units"]), ("PUSH", 0.0))
        spec = {"family": "total", "side": "over", "line": 8.0}
        c = dict(c, grading=spec)
        out = grading.grade_call(c, 1, {"away_score": "5", "home_score": "3"}, {}, frozenset())
        self.assertEqual(out["result"], "PUSH")
        spec = {"family": "team_total", "side": "over", "line": 5.0, "team_side": "away"}
        out = grading.grade_call(dict(c, grading=spec), 1, {"away_score": "5", "home_score": "3"},
                                 {}, frozenset())
        self.assertEqual(out["result"], "PUSH")

    def test_a_result_marked_void_voids_the_bet(self):
        spec = {"family": "moneyline", "side": "away", "line": None}
        c = {"slot_id": "x", "selection": "s", "verdict": "TAKE", "price": 110, "grading": spec}
        out = grading.grade_call(c, 1, {"void": True, "reason": "suspended, never resumed"}, {}, frozenset())
        self.assertEqual(out["result"], "VOID")
        self.assertIn("suspended", out["reason"])

    def test_an_unusable_price_voids_instead_of_guessing(self):
        spec = {"family": "total", "side": "over", "line": 6.5}
        c = {"slot_id": "x", "selection": "s", "verdict": "TAKE", "price": 50, "grading": spec}
        out = grading.grade_call(c, 1, {"away_score": "5", "home_score": "3"}, {}, frozenset())
        self.assertEqual(out["result"], "VOID")

    def test_the_card_ledgers_grader_is_the_one_used(self):
        # same answer as card_ledger for the same pick: they can never disagree
        from src.appstate import card_ledger
        spec = {"family": "run_line", "side": "home", "line": -1.5}
        res = {"away_score": "2", "home_score": "5"}
        mine = grading.grade_call({"slot_id": "x", "selection": "s", "verdict": "TAKE", "price": 150,
                                   "grading": spec}, 7, res, {}, frozenset())
        theirs = card_ledger.grade_pick({"game_pk": 7, "market": "run_line", "side": "home",
                                         "line": -1.5, "price": 150}, res)
        self.assertEqual(mine["result"], theirs["result"])
        self.assertEqual(mine["profit_units"], theirs["profit_units"])


class GradingProps(Base):
    def setUp(self):
        super().setUp()
        self.packet = F.build()
        self.slot = {m["context"]["stat"] + ":" + m["context"]["player"]: sid
                     for sid, m in self.packet["markets"].items() if m["market"] == "prop"}

    def box(self):
        return [
            {"type": "batter", "game_pk": 849835, "player_name": "Junior Caminero", "h": 2,
             "total_bases": 3, "hr": 0},
            {"type": "batter", "game_pk": 849835, "player_name": "Ben Rice", "h": 1,
             "total_bases": 1, "hr": 0},
            {"type": "pitcher", "game_pk": 849835, "player_name": "Gerrit Cole", "k": 7},
        ]

    def grade(self, calls, box):
        self.publish(self.packet, verified(calls))
        ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, box,
                          now=F.NOW, path=self.path)
        graded = [r for r in ledger.rows(self.path) if r["kind"] == ledger.KIND_GRADED][-1]
        return {c["slot_id"]: c for c in graded["calls"]}

    def test_batter_and_pitcher_props_are_graded_from_the_box(self):
        cole = self.slot["pitcher_strikeouts:Gerrit Cole"]
        cam = self.slot["batter_hits:Junior Caminero"]
        rice = self.slot["batter_total_bases:Ben Rice"]
        g = self.grade([take(self.packet, cole, "over"), take(self.packet, cam, "over"),
                        take(self.packet, rice, "over")], self.box())
        self.assertEqual(g[cole]["result"], "WIN")      # 7 strikeouts over 6.5
        self.assertEqual(g[cam]["result"], "WIN")       # 2 hits over 0.5
        self.assertEqual(g[rice]["result"], "LOSS")     # 1 total base under 1.5

    def test_a_prop_on_the_line_is_a_push(self):
        spec = {"family": "prop", "stat": "pitcher_strikeouts", "player": "Gerrit Cole",
                "side": "over", "line": 7.0}
        idx = grading.index_box_rows(self.box())
        out = grading.grade_call({"slot_id": "x", "selection": "s", "verdict": "TAKE", "price": -110,
                                  "grading": spec}, 849835, None, *idx)
        self.assertEqual(out["result"], "PUSH")

    def test_a_player_who_never_appeared_in_a_captured_box_is_void(self):
        cam = self.slot["batter_hits:Junior Caminero"]
        box = [r for r in self.box() if r["player_name"] != "Junior Caminero"]
        g = self.grade([take(self.packet, cam, "over")], box)
        self.assertEqual(g[cam]["result"], "VOID")
        self.assertIn("no recorded appearance", g[cam]["reason"])

    def test_no_box_at_all_is_unresolved_not_void(self):
        cam = self.slot["batter_hits:Junior Caminero"]
        self.publish(self.packet, verified([take(self.packet, cam, "over")]))
        counts = ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [],
                                   now=F.NOW, path=self.path)
        # nothing is written for an all-unresolved picture; the record counts it as unresolved
        self.assertEqual(counts["graded"], 0)
        fam = ledger.record(path=self.path)["families"]["prop"]
        self.assertEqual((fam["taken"], fam["unresolved"], fam["losses"], fam["voids"]), (1, 1, 0, 0))

    def test_an_unknown_stat_is_void_not_guessed(self):
        spec = {"family": "prop", "stat": "batter_vibes", "player": "x", "side": "over", "line": 0.5}
        out = grading.grade_call({"slot_id": "x", "selection": "s", "verdict": "TAKE", "price": 100,
                                  "grading": spec}, 1, None, {}, frozenset())
        self.assertEqual(out["result"], "VOID")


class PassesAreNotBets(Base):
    def test_a_pass_reports_what_the_passed_side_would_have_done(self):
        packet = F.build()
        self.publish(packet, verified([F.pass_call(packet, "moneyline")]))   # lean TB at -127
        ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [],
                          now=F.NOW, path=self.path)
        graded = [r for r in ledger.rows(self.path) if r["kind"] == ledger.KIND_GRADED][-1]
        c = graded["calls"][0]
        self.assertEqual(c["result"], "PASS")
        self.assertIsNone(c["profit_units"])
        self.assertEqual(c["would_have"]["result"], "LOSS")   # TB lost
        self.assertTrue(graded["complete"])                  # no bets, a final score

    def test_a_pass_is_never_counted_as_a_win_or_a_loss(self):
        packet = F.build()
        self.publish(packet, verified([F.pass_call(packet, "moneyline")]))
        ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [],
                          now=F.NOW, path=self.path)
        fam = ledger.record(path=self.path)["families"]["moneyline"]
        self.assertEqual((fam["taken"], fam["passes"], fam["graded"], fam["wins"], fam["losses"]),
                         (0, 1, 0, 0, 0))
        self.assertEqual(fam["passes_would_have_lost"], 1)


class GradeDateIsIdempotentAndCorrectionsAppend(Base):
    def setUp(self):
        super().setUp()
        packet = F.build()
        self.publish(packet, verified([take(packet, "moneyline", "away")]))
        self.results = {849835: {"away_score": "5", "home_score": "3"}}

    def test_grading_twice_changes_nothing(self):
        first = ledger.grade_date(F.DATE, self.results, [], now=F.NOW, path=self.path)
        second = ledger.grade_date(F.DATE, self.results, [], now=F.NOW, path=self.path)
        self.assertEqual(first["graded"], 1)
        self.assertEqual(second["graded"], 0)
        self.assertEqual(second["complete"], 1)
        self.assertEqual(len(self.lines()), 2)

    def test_string_and_int_game_pks_both_join(self):
        got = ledger.grade_date(F.DATE, {"849835": self.results[849835]}, [], now=F.NOW, path=self.path)
        self.assertEqual(got["graded"], 1)

    def test_a_correction_appends_and_the_record_uses_it(self):
        ledger.grade_date(F.DATE, self.results, [], now=F.NOW, path=self.path)
        before = self.lines()
        ledger.correct("NYY-TB-2026-10-03-1", "moneyline",
                       {"result": "VOID", "profit_units": 0.0, "reason": "feed error"},
                       "results feed corrected", now=F.NOW, path=self.path)
        after = self.lines()
        self.assertEqual(after[:2], before)          # nothing rewritten
        self.assertEqual(len(after), 3)
        self.assertTrue(ledger.verify(self.path)["ok"])
        fam = ledger.record(path=self.path)["families"]["moneyline"]
        self.assertEqual((fam["wins"], fam["voids"]), (0, 1))
        view = ledger.game_view(F.DATE, "NYY", "TB", path=self.path)
        self.assertEqual(next(c for c in view["calls"] if c["slot_id"] == "moneyline")["result"], "VOID")

    def test_a_correction_needs_a_reason_known_fields_and_a_graded_call(self):
        with self.assertRaises(ledger.AnalystLedgerError):
            ledger.correct("NYY-TB-2026-10-03-1", "moneyline", {"result": "WIN"}, "x", now=F.NOW, path=self.path)
        ledger.grade_date(F.DATE, self.results, [], now=F.NOW, path=self.path)
        with self.assertRaises(ledger.AnalystLedgerError):
            ledger.correct("NYY-TB-2026-10-03-1", "moneyline", {"result": "WIN"}, "  ", now=F.NOW, path=self.path)
        with self.assertRaises(ledger.AnalystLedgerError):
            ledger.correct("NYY-TB-2026-10-03-1", "moneyline", {"price": 100}, "r", now=F.NOW, path=self.path)
        with self.assertRaises(ledger.AnalystLedgerError):
            ledger.correct("NYY-TB-2026-10-03-1", "nope", {"result": "WIN"}, "r", now=F.NOW, path=self.path)

    def test_a_partial_result_is_kept_and_completed_later(self):
        packet = F.build()
        cam = next(sid for sid, m in packet["markets"].items()
                   if m["market"] == "prop" and m["context"]["player"] == "Junior Caminero")
        os.remove(self.path)
        self.publish(packet, verified([take(packet, "moneyline", "away"), take(packet, cam, "over")]))
        ledger.grade_date(F.DATE, self.results, [], now=F.NOW, path=self.path)
        first = [r for r in ledger.rows(self.path) if r["kind"] == ledger.KIND_GRADED][-1]
        self.assertFalse(first["complete"])
        box = [{"type": "batter", "game_pk": 849835, "player_name": "Junior Caminero", "h": 1}]
        ledger.grade_date(F.DATE, self.results, box, now=F.NOW, path=self.path)
        last = [r for r in ledger.rows(self.path) if r["kind"] == ledger.KIND_GRADED][-1]
        self.assertTrue(last["complete"])
        self.assertEqual(len([r for r in ledger.rows(self.path) if r["kind"] == ledger.KIND_GRADED]), 2)


class TheRecord(Base):
    def synthetic_rows(self, n_wins, n_losses, family="moneyline"):
        rows, previous = [], "0" * 64
        for i in range(n_wins + n_losses):
            h = f"{i:064d}"
            rows.append({"kind": ledger.KIND_PUBLISHED, "game_id": f"G{i}", "date": "2026-10-01",
                         "away": "A", "home": "B", "row_hash": h, "version": 1,
                         "first_pitch_utc": "2026-10-01T23:00:00Z",
                         "calls": [{"slot_id": "s", "verdict": "TAKE", "selection": "A", "price": 110,
                                    "grading": {"family": family}}]})
            won = i < n_wins
            rows.append({"kind": ledger.KIND_GRADED, "game_id": f"G{i}", "date": "2026-10-01",
                         "published_row_hash": h, "row_hash": f"g{i:063d}", "complete": True,
                         "calls": [{"slot_id": "s", "result": "WIN" if won else "LOSS",
                                    "profit_units": 1.1 if won else -1.0}]})
        return rows

    def test_under_thirty_graded_calls_no_rate_and_no_return_is_printed(self):
        rec = ledger.record(all_rows=self.synthetic_rows(10, 5), min_graded=30)
        fam = rec["families"]["moneyline"]
        self.assertEqual((fam["graded"], fam["wins"], fam["losses"]), (15, 10, 5))
        self.assertIsNone(fam["win_rate"])
        self.assertIsNone(fam["units"])
        self.assertIn("fewer than 30 graded calls (15 so far)", fam["withheld_reason"])

    def test_twenty_nine_is_still_withheld_and_thirty_is_shown(self):
        self.assertIsNone(ledger.record(all_rows=self.synthetic_rows(20, 9))["families"]["moneyline"]["win_rate"])
        fam = ledger.record(all_rows=self.synthetic_rows(20, 10))["families"]["moneyline"]
        self.assertEqual(fam["win_rate"], round(20 / 30, 4))
        self.assertEqual(fam["units"], round(20 * 1.1 - 10, 2))
        self.assertIsNone(fam["withheld_reason"])

    def test_each_family_is_counted_apart(self):
        rows = self.synthetic_rows(3, 1, "moneyline") + [
            dict(r, game_id="P" + r["game_id"], row_hash="p" + r["row_hash"][1:]) if r["kind"] == ledger.KIND_PUBLISHED
            else dict(r, game_id="P" + r["game_id"], published_row_hash="p" + r["published_row_hash"][1:],
                      row_hash="q" + r["row_hash"][1:])
            for r in self.synthetic_rows(1, 0, "prop")]
        for r in rows:
            if r["kind"] == ledger.KIND_PUBLISHED and r["game_id"].startswith("PG"):
                r["calls"][0]["grading"]["family"] = "prop"
        fams = ledger.record(all_rows=rows)["families"]
        self.assertEqual(fams["moneyline"]["graded"], 4)
        self.assertEqual(fams["prop"]["graded"], 1)
        self.assertEqual(fams["run_line"]["graded"], 0)

    def test_pushes_and_voids_are_counted_but_a_void_is_not_a_graded_call(self):
        rows = self.synthetic_rows(1, 0)
        rows[1]["calls"][0].update(result="PUSH", profit_units=0.0)
        rows += [dict(rows[0], game_id="V", row_hash="v" * 64),
                 dict(rows[1], game_id="V", published_row_hash="v" * 64, row_hash="w" * 64,
                      calls=[{"slot_id": "s", "result": "VOID", "profit_units": 0.0}])]
        fam = ledger.record(all_rows=rows)["families"]["moneyline"]
        self.assertEqual((fam["pushes"], fam["voids"], fam["graded"]), (1, 1, 1))

    def test_only_the_newest_version_of_a_game_counts(self):
        rows = self.synthetic_rows(1, 0)
        newer = dict(rows[0], row_hash="n" * 64, version=2, supersedes=rows[0]["row_hash"])
        rec = ledger.record(all_rows=rows + [newer])
        self.assertEqual(rec["games_published"], 1)
        self.assertEqual(rec["families"]["moneyline"]["graded"], 0)   # v2 is not graded yet
        self.assertEqual(rec["families"]["moneyline"]["unresolved"], 1)

    def test_take_other_side_is_counted_inside_taken(self):
        rows = self.synthetic_rows(1, 0)
        rows[0]["calls"][0]["verdict"] = "TAKE_OTHER_SIDE"
        fam = ledger.record(all_rows=rows)["families"]["moneyline"]
        self.assertEqual((fam["taken"], fam["taken_other_side"]), (1, 1))

    def test_the_recent_list_holds_settled_calls_only_and_the_label_is_present(self):
        rec = ledger.record(all_rows=self.synthetic_rows(2, 1))
        self.assertEqual(len(rec["recent"]), 3)
        self.assertEqual(rec["label"], "Written by an AI model from the data on this page. Unproven. Analysis, not advice.")

    def test_an_empty_ledger_has_a_record_of_zeros(self):
        rec = ledger.record(path=self.path)
        self.assertEqual(rec["games_published"], 0)
        self.assertTrue(all(f["taken"] == 0 for f in rec["families"].values()))


class TheCostLog(Base):
    def test_usage_rows_chain_and_fold_by_day(self):
        for gid, usd in (("A", 0.07), ("B", 0.11)):
            ledger.log_usage(date=F.DATE, game_id=gid, run_id="r1", outcome="published",
                             model="claude-sonnet-5-5",
                             usage={"input_tokens": 10000, "output_tokens": 5000},
                             cost_usd=usd, attempts=1, cfg=F.CFG, now=F.NOW, path=self.usage)
        ledger.log_usage(date=F.DATE, game_id="C", run_id="r1", outcome="rejected_malformed",
                         model="m", usage={"input_tokens": 1, "output_tokens": 2}, cost_usd=0.01,
                         attempts=2, cfg=F.CFG, now=F.NOW, path=self.usage)
        day = ledger.usage_by_day(self.usage)[F.DATE]
        self.assertEqual((day["games"], day["published"]), (3, 2))
        self.assertAlmostEqual(day["cost_usd"], 0.19)
        self.assertEqual(day["input_tokens"], 20001)
        from src.ledger.chain import HashChainLedger
        self.assertTrue(HashChainLedger(self.usage).verify().ok)

    def test_each_row_records_the_price_it_was_computed_with(self):
        row = ledger.log_usage(date=F.DATE, game_id="A", run_id="r", outcome="published", model="m",
                               usage={}, cost_usd=0, attempts=1, cfg=F.CFG, now=F.NOW, path=self.usage)
        self.assertEqual(row["price_per_million_usd"]["output"], 10.0)


class TheGameView(Base):
    def test_no_row_means_none(self):
        self.assertIsNone(ledger.game_view(F.DATE, "NYY", "TB", path=self.path))

    def test_the_view_has_calls_titles_and_no_struck_originals(self):
        packet = F.build()
        out = F.good_output(packet)
        out["calls"][0]["reasons"][1]["claim"] = "He has a 2.17 ERA."
        self.publish(packet, critic.verify(packet, out))
        view = ledger.game_view(F.DATE, "nyy", "tb", path=self.path)
        self.assertEqual(view["game_id"], "NYY-TB-2026-10-03-1")
        self.assertEqual(view["summary_status"], "ok")
        self.assertNotIn("2.17", json.dumps(view))
        self.assertNotIn("struck", view)
        titles = {c["slot_id"]: c["title"] for c in view["calls"]}
        self.assertEqual(titles["moneyline"], "Moneyline")
        self.assertTrue(any("Caminero hits" in t for t in titles.values()))
        self.assertFalse(view["graded"])


if __name__ == "__main__":
    unittest.main()
