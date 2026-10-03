"""The UFC analyst's ledger: frozen before the bout, graded after, apart from every other record.

Every ledger, packet directory and usage log is a path the test owns in a temporary
directory. A test proves the default paths are not the MLB analyst's and that none of them is
created by a publish to a temp path.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import paths
from src.analyst import ledger as mlb_ledger
from src.analyst import packet as base
from src.analyst import ufc_analyst as U
from src.analyst import ufc_ledger as L
from tests import ufc_analyst_fixtures as F

SECOND = "9102"           # the prelim, 104 v 105, starts 21:00Z, two hours before the main event


class Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = str(self.dir / "ufc.jsonl")
        self.packets = str(self.dir / "packets")
        self.usage = str(self.dir / "usage.jsonl")
        self.store = F.make_store(self.dir / "world", rows=[F.odds(), F.odds(bout_id=SECOND)])

    def published(self, bout_id=F.BOUT, now=F.NOW, **kw):
        packet = F.packet(self.store, bout_id=bout_id)
        verified = U.verify(packet, F.good_output(packet))
        row, created = L.publish(packet, verified, now=now, model="claude-test", path=self.path,
                                 packet_dir=self.packets, **kw)
        return packet, verified, row, created

    def finish(self, bout_id=F.BOUT, **result):
        defaults = dict(winner_id="102", result_method="KO_TKO", end_round=2, end_time_s=77.0, fight_time_s=377.0)
        defaults.update(result)
        F.finish_the_bout(self.store, bout_id, **defaults)
        return self.store.bout_by_id()

    def grade(self, date=F.DATE, now=None, bouts=None):
        return L.grade_date(date, bouts if bouts is not None else self.store.bout_by_id(),
                            now=now or F.NOW + timedelta(hours=10), path=self.path)

    def rows(self):
        return L.rows(self.path)


class Publishing(Env):
    def test_a_publish_writes_one_chained_row_with_everything_needed_to_grade_it(self):
        packet, verified, row, created = self.published()
        self.assertTrue(created)
        self.assertEqual([r["kind"] for r in self.rows()], ["analyst_ufc_published"])
        self.assertRegex(row["row_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual((row["bout_id"], row["event_id"], row["date"], row["start_utc"]),
                         (F.BOUT, F.EVENT, F.DATE, F.START_ISO))
        self.assertEqual(row["fighters"], {"a": {"id": "101", "name": F.A}, "b": {"id": "102", "name": F.B}})
        self.assertEqual((row["weight_class"], row["scheduled_rounds"], row["match_number"]), ("Welterweight", 5, 1))
        self.assertEqual(row["published_utc"], "2026-10-10T16:00:00Z")
        self.assertEqual((row["version"], row["supersedes"]), (1, None))
        self.assertEqual([c["slot_id"] for c in row["calls"]], [s["slot_id"] for s in packet["slots"]])
        for call in row["calls"]:
            self.assertEqual(call["grading"]["family"], packet["markets"][call["slot_id"]]["market"])
        self.assertEqual(row["summary_status"], "ok")
        self.assertEqual(row["struck"], [])

    def test_the_row_carries_the_ufc_prompt_identity_and_the_packet_hash(self):
        packet, _v, row, _c = self.published()
        self.assertEqual((row["prompt_version"], row["prompt_hash"]), (U.UFC_PROMPT_VERSION, U.prompt_hash()))
        self.assertNotEqual(row["prompt_hash"], mlb_ledger.prompt_hash())
        self.assertEqual((row["packet_hash"], row["packet_version"]), (base.packet_hash(packet), "analyst_ufc_packet_v1"))
        self.assertEqual(row["model"], "claude-test")

    def test_the_packet_is_a_file_named_by_its_hash_and_it_round_trips(self):
        packet, _v, row, _c = self.published()
        target = Path(row["packet_path"])
        self.assertTrue(target.is_file())
        self.assertEqual(target.name, f"{F.BOUT}_{row['packet_hash'][:12]}.json.gz")
        self.assertEqual(target.parent.name, F.DATE)
        self.assertEqual(L.read_packet(row), packet)
        with gzip.open(target) as fh:
            self.assertEqual(json.loads(fh.read()), packet)

    def test_a_published_bout_is_frozen(self):
        _p, _v, first, created = self.published()
        _p, _v, again, created_again = self.published()
        self.assertEqual((created, created_again), (True, False))
        self.assertEqual(again["row_hash"], first["row_hash"])
        self.assertEqual(len(self.rows()), 1)

    def test_a_refresh_writes_a_new_version_and_only_the_newest_counts(self):
        _p, _v, first, _c = self.published()
        _p, _v, second, created = self.published(now=F.NOW + timedelta(minutes=10), refresh=True)
        self.assertTrue(created)
        self.assertEqual((second["version"], second["supersedes"]), (2, first["row_hash"]))
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(L.latest_published(self.rows())[F.BOUT]["row_hash"], second["row_hash"])

    def test_a_graded_bout_cannot_be_published_again(self):
        """Reached only if a bout is graded while the store still says it is scheduled (the
        store here is not told): the 'already graded' guard is separate from the start rule."""
        self.published()
        finished = dict(self.store.bout_by_id()[F.BOUT], status="final", winner_id="102",
                        result_method="KO_TKO", end_round=2, end_time_s=77.0, fight_time_s=377.0)
        self.assertEqual(self.grade(bouts={F.BOUT: finished})["graded"], 1)
        with self.assertRaises(L.UfcLedgerError) as ctx:
            self.published(now=F.NOW + timedelta(minutes=5), refresh=True)
        self.assertNotIsInstance(ctx.exception, L.BoutStarted)
        self.assertIn("already graded", str(ctx.exception))

    def test_the_struck_originals_are_kept_for_the_audit_and_not_in_the_calls(self):
        packet = F.packet(self.store)
        out = F.deep(F.good_output(packet))
        out["calls"][0]["reasons"][0]["claim"] = "He lands 71.93 strikes."
        verified = U.verify(packet, out)
        row, _c = L.publish(packet, verified, now=F.NOW, model="m", path=self.path, packet_dir=self.packets)
        self.assertEqual([s["slot_id"] for s in row["struck"]], ["moneyline"])
        self.assertIn("71.93", json.dumps(row["struck"]))
        self.assertNotIn("71.93", json.dumps(row["calls"]))
        self.assertEqual(row["calls"][0]["verdict"], "PASS")


class RefusesAfterTheStart(Env):
    """The ledger never holds a call made after the bout began, or one that cannot be shown
    to have been made before it."""

    def refuses(self, packet, now, **kw):
        verified = U.verify(packet, F.good_output(packet))
        with self.assertRaises(L.BoutStarted):
            L.publish(packet, verified, now=now, model="m", path=self.path, packet_dir=self.packets, **kw)
        self.assertEqual(self.rows(), [])
        self.assertFalse(Path(self.packets).exists())          # nothing written at all

    def test_after_the_scheduled_start(self):
        self.refuses(F.packet(self.store), datetime(2026, 10, 10, 23, 0, 1, tzinfo=timezone.utc))

    def test_at_the_scheduled_start(self):
        self.refuses(F.packet(self.store), datetime(2026, 10, 10, 23, 0, 0, tzinfo=timezone.utc))

    def test_one_second_before_it_is_allowed(self):
        packet = F.packet(self.store)
        row, created = L.publish(packet, U.verify(packet, F.good_output(packet)),
                                 now=datetime(2026, 10, 10, 22, 59, 59, tzinfo=timezone.utc), model="m",
                                 path=self.path, packet_dir=self.packets)
        self.assertTrue(created)

    def test_inside_the_lock_lead(self):
        self.refuses(F.packet(self.store), datetime(2026, 10, 10, 22, 40, tzinfo=timezone.utc),
                     lock_lead_minutes=30)

    def test_a_bout_with_no_scheduled_start(self):
        bout = dict(self.store.bout_by_id()[F.BOUT], date_utc=None)
        self.store.upsert("bouts", [bout])
        packet = F.packet(self.store)
        self.assertIn("unknown", L.publish_refusal(packet, F.NOW))
        self.refuses(packet, F.NOW)

    def test_a_bout_that_is_not_scheduled(self):
        F.finish_the_bout(self.store)
        packet = F.packet(self.store)
        why = L.publish_refusal(packet, F.NOW)
        self.assertIn("'final'", why)
        self.refuses(packet, F.NOW)

    def test_the_refusal_helper_says_none_for_a_bout_that_can_be_published(self):
        self.assertIsNone(L.publish_refusal(F.packet(self.store), F.NOW))

    def test_the_start_it_refuses_at_is_the_scheduled_segment_start(self):
        """ESPN gives every bout of a card segment that segment's start, so the real bout begins
        later: refusing at the scheduled start is conservative by construction."""
        self.assertEqual(F.packet(self.store)["bout"]["start_utc"], F.START_ISO)


class Grading(Env):
    def test_nothing_is_graded_while_the_bout_has_not_been_fought(self):
        self.published()
        counts = self.grade(now=F.NOW + timedelta(hours=1))
        self.assertEqual((counts["published"], counts["graded"], counts["unchanged"]), (1, 0, 1))
        self.assertEqual(len(self.rows()), 1)

    def test_a_finished_bout_is_graded_by_the_data_layers_result(self):
        self.published()
        self.finish(winner_id="102", result_method="KO_TKO", end_round=2, end_time_s=77.0)
        counts = self.grade()
        self.assertEqual((counts["graded"], counts["complete"]), (1, 1))
        graded = L.latest_graded(self.rows())
        row = next(iter(graded.values()))
        self.assertEqual(row["kind"], "analyst_ufc_graded")
        self.assertTrue(row["complete"])
        self.assertEqual(row["final"]["outcome"], "decided")
        by_slot = {c["slot_id"]: c for c in row["calls"]}
        self.assertEqual((by_slot["moneyline"]["verdict"], by_slot["moneyline"]["result"]),
                         ("TAKE_OTHER_SIDE", "WIN"))                      # Brawler won
        self.assertEqual(by_slot["moneyline"]["profit_units"], 1.45)
        self.assertEqual(by_slot["rounds_total"]["result"], "PASS")
        self.assertEqual(by_slot["rounds_total"]["would_have"]["result"], "LOSS")   # over 4.5 lost to a round-2 KO
        self.assertEqual(by_slot["method_b_ko"]["would_have"]["result"], "WIN")     # the passed KO price won

    def test_grading_twice_changes_nothing(self):
        self.published()
        self.finish()
        self.grade()
        again = self.grade()
        self.assertEqual((again["graded"], again["complete"]), (0, 1))
        self.assertEqual(len([r for r in self.rows() if r["kind"] == "analyst_ufc_graded"]), 1)

    def test_a_later_grade_replaces_an_earlier_one_only_when_it_adds_a_result(self):
        """Graded while the winner is recorded but the time is not: the total stays unresolved,
        and the later grade that adds the time is the one that counts."""
        packet = F.packet(self.store)
        out = F.deep(F.good_output(packet))
        under = packet["markets"]["rounds_total"]["options"][1]
        out["calls"][1] = {
            "slot_id": "rounds_total", "market": "rounds_total", "selection": under["selection"],
            "verdict": "TAKE_OTHER_SIDE", "price": -110, "book": "DraftKings", "fair_estimate": 0.58,
            "confidence": "low", "reasons": [{"claim": "The price is fair for a short fight.",
                                              "evidence": [{"path": "markets.rounds_total.options[1].best.price",
                                                            "value": -110}]}],
            "pass_price": -138, "what_would_change_it": "A late price move."}
        L.publish(packet, U.verify(packet, out), now=F.NOW, model="m", path=self.path, packet_dir=self.packets)
        self.finish(end_round=None, end_time_s=None, fight_time_s=None)
        first = self.grade()
        self.assertEqual((first["graded"], first["complete"]), (1, 0))      # the moneyline settled, the total did not
        self.finish(end_round=2, end_time_s=77.0, fight_time_s=377.0)
        second = self.grade()
        self.assertEqual((second["graded"], second["complete"]), (1, 1))
        newest = next(iter(L.latest_graded(self.rows()).values()))
        self.assertEqual({c["slot_id"]: c["result"] for c in newest["calls"]}["rounds_total"], "WIN")
        self.assertEqual(len([r for r in self.rows() if r["kind"] == "analyst_ufc_graded"]), 2)

    def test_a_canceled_bout_is_graded_void_and_complete(self):
        self.published()
        F.finish_the_bout(self.store, status="canceled", winner_id=None, result_method=None, end_round=None,
                          end_time_s=None, fight_time_s=None)
        counts = self.grade()
        self.assertEqual((counts["graded"], counts["complete"]), (1, 1))
        row = next(iter(L.latest_graded(self.rows()).values()))
        self.assertEqual(row["final"], {"outcome": "canceled"})
        self.assertEqual({c["result"] for c in row["calls"] if c["verdict"] != "PASS"}, {"VOID"})

    def test_a_draw_is_void(self):
        self.published()
        self.finish(winner_id=None, result_method="DRAW", end_round=5, end_time_s=300.0, fight_time_s=1500.0)
        self.grade()
        row = next(iter(L.latest_graded(self.rows()).values()))
        self.assertEqual(row["final"]["outcome"], "draw")
        self.assertEqual({c["result"] for c in row["calls"] if c["verdict"] != "PASS"}, {"VOID"})

    def test_only_the_dates_published_bouts_are_graded(self):
        self.published()
        counts = self.grade(date="2026-10-11")
        self.assertEqual(counts["published"], 0)

    def test_a_published_bout_the_store_no_longer_has_stays_unresolved(self):
        self.published()
        counts = self.grade(bouts={})
        self.assertEqual((counts["graded"], counts["unchanged"]), (0, 1))


class Corrections(Env):
    def setUp(self):
        super().setUp()
        self.published()
        self.finish()
        self.grade()

    def test_a_correction_appends_and_the_graded_row_is_untouched(self):
        before = [dict(r) for r in self.rows()]
        L.correct(F.BOUT, "moneyline", {"result": "LOSS", "profit_units": -1.0}, "ESPN corrected the winner",
                  now=F.NOW, path=self.path)
        rows = self.rows()
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(rows[-1]["kind"], "analyst_ufc_correction")
        rec = L.record(path=self.path)
        ml = rec["families"]["moneyline"]
        self.assertEqual((ml["wins"], ml["losses"]), (0, 1))

    def test_a_correction_needs_a_reason_a_known_field_and_a_graded_call(self):
        with self.assertRaises(L.UfcLedgerError):
            L.correct(F.BOUT, "moneyline", {"result": "LOSS"}, "  ", now=F.NOW, path=self.path)
        with self.assertRaises(L.UfcLedgerError):
            L.correct(F.BOUT, "moneyline", {"verdict": "PASS"}, "why", now=F.NOW, path=self.path)
        with self.assertRaises(L.UfcLedgerError):
            L.correct(F.BOUT, "nope", {"result": "LOSS"}, "why", now=F.NOW, path=self.path)
        with self.assertRaises(L.UfcLedgerError):
            L.correct("nope", "moneyline", {"result": "LOSS"}, "why", now=F.NOW, path=self.path)

    def test_a_corrected_call_is_marked_in_the_view(self):
        L.correct(F.BOUT, "moneyline", {"result": "LOSS"}, "fix", now=F.NOW, path=self.path)
        view = L.event_view(F.EVENT, path=self.path)
        ml = next(c for c in view["bouts"][0]["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual(ml["result"], "LOSS")


class TheEventView(Env):
    def test_every_published_bout_of_the_event_in_card_order_with_its_grade(self):
        self.published(SECOND)
        self.published(F.BOUT)
        view = L.event_view(F.EVENT, path=self.path)
        self.assertEqual((view["event_id"], view["event_name"], view["date"]),
                         (F.EVENT, "Synthetic Championship Night", F.DATE))
        self.assertEqual([b["bout_id"] for b in view["bouts"]], [F.BOUT, SECOND])      # main event first
        main = view["bouts"][0]
        self.assertEqual((main["fighter_a"], main["fighter_b"], main["weight_class"]), (F.A, F.B, "Welterweight"))
        self.assertEqual((main["summary_status"], main["graded"], main["final"], main["result_text"]),
                         ("ok", False, None, None))
        ml = next(c for c in main["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual((ml["family"], ml["title"], ml["verdict"]), ("moneyline", "Moneyline", "TAKE_OTHER_SIDE"))
        titles = {c["slot_id"]: c["title"] for c in main["calls"]}
        self.assertEqual(titles["rounds_total"], "Rounds total")
        self.assertEqual(titles["method_a_ko"], "Method of victory")

    def test_a_graded_bout_shows_its_result_in_words_and_each_calls_result(self):
        self.published()
        self.finish()
        self.grade()
        main = L.event_view(F.EVENT, path=self.path)["bouts"][0]
        self.assertTrue(main["graded"])
        self.assertEqual(main["result_text"], "Ben Brawler won by KO/TKO in round 2.")
        ml = next(c for c in main["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual(ml["result"], "WIN")
        rt = next(c for c in main["calls"] if c["slot_id"] == "rounds_total")
        self.assertEqual(rt["would_have"]["result"], "LOSS")

    def test_an_event_with_nothing_published_is_none(self):
        self.published()
        self.assertIsNone(L.event_view("nope", path=self.path))
        self.assertIsNone(L.event_view(F.EVENT, all_rows=[]))

    def test_the_view_only_ever_reads_the_ledger(self):
        self.published()
        rows = self.rows()
        Path(self.path).unlink()
        self.assertEqual(L.event_view(F.EVENT, all_rows=rows)["bouts"][0]["bout_id"], F.BOUT)


def published_row(i, calls, date="2026-10-10"):
    return {"kind": L.KIND_PUBLISHED, "bout_id": f"b{i}", "event_id": "e1", "row_hash": f"p{i}", "date": date,
            "fighters": {"a": {"id": "1", "name": "A"}, "b": {"id": "2", "name": "B"}}, "version": 1,
            "published_utc": "x", "calls": calls}


def call(slot, family, verdict="TAKE", price=100, selection="x"):
    return {"slot_id": slot, "selection": selection, "verdict": verdict, "price": price,
            "grading": {"family": family}}


def graded_row(i, results, complete=True):
    return {"kind": L.KIND_GRADED, "published_row_hash": f"p{i}", "row_hash": f"g{i}", "complete": complete,
            "calls": [{"slot_id": s, "result": r, "profit_units": u, "would_have": w}
                      for s, r, u, w in results]}


class TheRecord(Env):
    def thirty(self, wins, family="moneyline", slot="moneyline"):
        rows = []
        for i in range(30):
            rows.append(published_row(i, [call(slot, family)]))
            win = i < wins
            rows.append(graded_row(i, [(slot, "WIN" if win else "LOSS", 1.0 if win else -1.0, None)]))
        return rows

    def test_the_families_are_moneyline_method_and_rounds_total_and_nothing_else(self):
        rec = L.record(all_rows=[])
        self.assertEqual(list(rec["families"]), ["moneyline", "method", "rounds_total"])
        self.assertIn("Unproven", rec["label"])
        self.assertEqual((rec["bouts_published"], rec["bouts_settled"]), (0, 0))

    def test_below_thirty_graded_calls_the_rate_and_units_are_withheld(self):
        rows = [published_row(i, [call("moneyline", "moneyline")]) for i in range(5)]
        rows += [graded_row(i, [("moneyline", "WIN", 1.0, None)]) for i in range(5)]
        f = L.record(all_rows=rows)["families"]["moneyline"]
        self.assertEqual((f["taken"], f["graded"], f["wins"]), (5, 5, 5))
        self.assertIsNone(f["win_rate"])
        self.assertIsNone(f["units"])
        self.assertEqual(f["withheld_reason"], "fewer than 30 graded calls (5 so far)")

    def test_at_thirty_the_rate_and_units_appear_for_that_family_only(self):
        rec = L.record(all_rows=self.thirty(18))
        ml, method, total = (rec["families"][k] for k in ("moneyline", "method", "rounds_total"))
        self.assertEqual((ml["graded"], ml["win_rate"], ml["units"], ml["withheld_reason"]), (30, 0.6, 6.0, None))
        self.assertIsNone(method["win_rate"])             # a good run in one family cannot lift another
        self.assertIsNone(total["win_rate"])

    def test_twenty_nine_is_still_withheld(self):
        rows = self.thirty(18)[:-2]                                      # drop the last bout's two rows
        f = L.record(all_rows=rows)["families"]["moneyline"]
        self.assertEqual(f["graded"], 29)
        self.assertIsNone(f["win_rate"])

    def test_pushes_count_as_graded_and_voids_do_not(self):
        rows = [published_row(i, [call("rounds_total", "rounds_total")]) for i in range(3)]
        rows += [graded_row(0, [("rounds_total", "PUSH", 0.0, None)]),
                 graded_row(1, [("rounds_total", "VOID", 0.0, None)]),
                 graded_row(2, [("rounds_total", "WIN", 0.9, None)])]
        f = L.record(all_rows=rows)["families"]["rounds_total"]
        self.assertEqual((f["graded"], f["pushes"], f["voids"], f["wins"]), (2, 1, 1, 1))

    def test_a_pass_is_counted_apart_with_what_it_would_have_done(self):
        rows = [published_row(0, [call("moneyline", "moneyline", verdict="PASS"),
                                  call("method_a_ko", "method", verdict="PASS")])]
        rows.append(graded_row(0, [("moneyline", "PASS", None, {"result": "WIN", "price": -170}),
                                   ("method_a_ko", "PASS", None, {"result": "LOSS", "price": 280})]))
        fams = L.record(all_rows=rows)["families"]
        self.assertEqual((fams["moneyline"]["passes"], fams["moneyline"]["taken"], fams["moneyline"]["graded"]), (1, 0, 0))
        self.assertEqual(fams["moneyline"]["passes_would_have_won"], 1)
        self.assertEqual(fams["method"]["passes_would_have_lost"], 1)

    def test_an_unresolved_take_is_counted_as_unresolved_never_a_loss(self):
        rows = [published_row(0, [call("moneyline", "moneyline")])]
        f = L.record(all_rows=rows)["families"]["moneyline"]
        self.assertEqual((f["taken"], f["unresolved"], f["losses"], f["graded"]), (1, 1, 0, 0))

    def test_take_other_side_is_counted_inside_taken(self):
        rows = [published_row(0, [call("moneyline", "moneyline", verdict="TAKE_OTHER_SIDE")])]
        f = L.record(all_rows=rows)["families"]["moneyline"]
        self.assertEqual((f["taken"], f["taken_other_side"]), (1, 1))

    def test_only_the_newest_version_of_a_bout_counts(self):
        old = published_row(0, [call("moneyline", "moneyline")])
        new = dict(published_row(0, [call("moneyline", "moneyline", verdict="PASS")]), row_hash="p0b", version=2)
        f = L.record(all_rows=[old, new])["families"]["moneyline"]
        self.assertEqual((f["taken"], f["passes"]), (0, 1))

    def test_recent_lists_settled_calls_only_and_never_an_unsettled_one(self):
        rows = [published_row(0, [call("moneyline", "moneyline", selection="Alex Archer")]),
                published_row(1, [call("moneyline", "moneyline", selection="Unsettled Man")]),
                graded_row(0, [("moneyline", "WIN", 1.0, None)])]
        rec = L.record(all_rows=rows)
        self.assertEqual([r["selection"] for r in rec["recent"]], ["Alex Archer"])
        self.assertNotIn("Unsettled Man", json.dumps(rec))
        self.assertEqual(set(rec["recent"][0]), {"date", "fighter_a", "fighter_b", "family", "selection",
                                                  "verdict", "price", "result", "reason"})

    def test_it_is_not_the_mlb_record(self):
        from src.analyst import grading
        self.assertNotEqual(tuple(L.record(all_rows=[])["families"]), grading.FAMILIES)
        self.assertNotEqual(L.STORE, mlb_ledger.STORE)
        self.assertNotEqual(L.USAGE_STORE, mlb_ledger.USAGE_STORE)
        self.assertNotEqual(L.PACKET_DIR, mlb_ledger.PACKET_DIR)
        self.assertNotEqual(L.KIND_PUBLISHED, mlb_ledger.KIND_PUBLISHED)


class Integrity(Env):
    def test_a_clean_ledger_verifies(self):
        self.published()
        self.published(SECOND)
        result = L.verify(self.path)
        self.assertEqual((result["ok"], result["rows"], result["problems"]), (True, 2, []))

    def test_an_edited_row_breaks_the_chain(self):
        self.published()
        text = Path(self.path).read_text(encoding="utf-8").replace("TAKE_OTHER_SIDE", "TAKE")
        Path(self.path).write_text(text, encoding="utf-8")
        result = L.verify(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("chain broken", result["problems"][0])

    def test_a_missing_or_swapped_packet_file_is_a_problem(self):
        _p, _v, row, _c = self.published()
        Path(row["packet_path"]).unlink()
        self.assertFalse(L.verify(self.path)["ok"])
        packet = F.packet(self.store)
        packet["bout"]["weight_class"] = "Heavyweight"
        with gzip.GzipFile(row["packet_path"], "wb") as fh:
            fh.write(json.dumps(packet).encode())
        result = L.verify(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("packet file", result["problems"][0])


class ItsOwnFiles(Env):
    def test_the_default_paths_are_the_ufc_ones(self):
        self.assertEqual(L.STORE.replace("\\", "/"), "evidence/analyst_ufc_v1.jsonl")
        self.assertEqual(L.USAGE_STORE.replace("\\", "/"), "evidence/analyst_ufc_usage_v1.jsonl")
        self.assertEqual(L.PACKET_DIR.replace("\\", "/"), "evidence/analyst_ufc_packets_v1")

    def test_publishing_to_a_temp_path_touches_nothing_at_the_default_paths(self):
        def state():
            out = []
            for rel in (L.STORE, L.USAGE_STORE, L.PACKET_DIR):
                target = paths.repo_root() / rel
                out.append(target.stat().st_mtime_ns if target.exists() else None)
            return out
        before = state()
        self.published()
        self.assertEqual(state(), before)

    def test_the_usage_log_is_its_own_file_with_the_bout_in_it(self):
        L.log_usage(date=F.DATE, bout_id=F.BOUT, run_id="r1", outcome="published", model="m",
                    usage={"input_tokens": 9000, "output_tokens": 4000}, cost_usd=0.058, attempts=1, cfg=F.CFG,
                    now=F.NOW, extra={"calls": 8, "struck": 0}, path=self.usage)
        row = json.loads(Path(self.usage).read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual((row["kind"], row["bout_id"], row["sport"], row["game_id"]),
                         ("analyst_usage", F.BOUT, "ufc", F.BOUT))
        day = L.usage_by_day(self.usage)[F.DATE]
        self.assertEqual((day["games"], day["published"], day["cost_usd"]), (1, 1, 0.058))


if __name__ == "__main__":
    unittest.main()
