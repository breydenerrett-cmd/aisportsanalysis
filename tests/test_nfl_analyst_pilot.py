"""The NFL pilot: prepare, check, publish, grade and record, and what it must never touch.

Everything is offline and injected: a temp folder stands in for the repo root (every NFL pilot store
lives under it), the data store and the odds rows are the synthetic league and rows of
tests/nfl_analyst_fixtures.py, and the clock is a lambda. Nothing here reads the repo's evidence,
calls the API or reaches a network.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.analyst import PILOT_LABEL, cli, ledger, nfl_analyst, nfl_cli, nfl_grading, nfl_pilot, pilot
from src.analyst import analyst as A
from src.analyst import packet as packet_mod
from src.ledger.chain import HashChainLedger
from tests import nfl_analyst_fixtures as F

ROOT = Path(__file__).resolve().parent.parent


class Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.store = F.make_store(self.root / "league")
        self.out = []
        self.now = F.NOW

    @property
    def text(self):
        return "\n".join(self.out)

    def prepare(self, *, game="BUF@KC", rows=None, scratch=None, date=F.DATE):
        return nfl_pilot.prepare(date, game, scratch=scratch, cfg=F.CFG, root=self.root, store=self.store,
                                 rows=F.odds_rows() if rows is None else rows,
                                 now=lambda: self.now, out=self.out.append)

    @property
    def folder(self):
        return nfl_pilot.game_folder(F.DATE, "BUF", "KC", self.root)

    def packet(self):
        return json.loads((self.folder / "packet.json").read_text(encoding="utf-8"))

    def write_response(self, output, name="answer.json"):
        path = self.root / name
        path.write_text(json.dumps(output), encoding="utf-8")
        return str(path)

    def good_response(self):
        return self.write_response(F.good_output(self.packet()))

    def check(self, response, *, now=None):
        return nfl_pilot.check(str(self.folder), response, out=self.out.append, now=lambda: now or self.now)

    def publish(self, response=None, *, now=None, **kw):
        kw.setdefault("model", "claude-sonnet-5-5")
        response = response or self.good_response()
        nfl_pilot.check(str(self.folder), response, out=lambda *_: None, now=lambda: now or self.now)
        return nfl_pilot.publish(str(self.folder), response, cfg=F.CFG, root=self.root,
                                 now=lambda: now or self.now, out=self.out.append, **kw)

    def files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file() and "league" not in p.parts and p.name != "answer.json")

    def store_rows(self):
        return ledger.rows(nfl_pilot.store_paths(self.root)["store"])


class Prepare(Env):
    def test_it_writes_the_three_files_for_the_game_in_the_nfl_folder(self):
        self.assertEqual(self.prepare(), 0, self.text)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["packet.json", "prepare.json", "request.json"])
        self.assertEqual(self.folder.name, "2025-10-26_BUF-KC")
        self.assertEqual(self.folder.parent.relative_to(self.root).as_posix(), "evidence/analyst_pilot_nfl")

    def test_the_request_is_exactly_what_the_api_call_would_send(self):
        self.prepare()
        packet = F.build(self.store)
        self.assertEqual(json.loads((self.folder / "request.json").read_text(encoding="utf-8")),
                         json.loads(json.dumps(nfl_analyst.build_request(packet, F.CFG))))

    def test_prepare_json_names_the_sport_the_packet_the_prompt_and_the_times(self):
        self.prepare()
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        packet = F.build(self.store)
        self.assertEqual(meta["sport"], "nfl")
        self.assertEqual(meta["packet_hash"], packet_mod.packet_hash(packet))
        self.assertEqual((meta["prompt_version"], meta["prompt_hash"]),
                         ("analyst_prompt_nfl_v1", nfl_analyst.prompt_hash()))
        self.assertEqual((meta["built_at"], meta["kickoff_utc"]), (F.BUILT_AT, F.KICKOFF))
        body = nfl_analyst.build_request(packet, F.CFG)
        self.assertEqual(meta["token_estimate"],
                         A.estimate_tokens(body["system"], body["messages"][0]["content"]))
        self.assertEqual((meta["slots"], meta["rehearsal"]), (["moneyline", "spread", "total"], False))

    def test_it_prints_the_token_estimate_and_the_nfl_commands(self):
        self.prepare()
        self.assertRegex(self.text, r"request ~\d+ input tokens \(high estimate\)")
        self.assertIn("pilot check --sport nfl --dir", self.text)
        self.assertIn("pilot publish --sport nfl --dir", self.text)

    def test_the_packet_on_disk_is_the_packet_the_hash_names_and_is_not_key_sorted(self):
        self.prepare()
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        packet = self.packet()
        self.assertEqual(packet_mod.packet_hash(packet), meta["packet_hash"])
        self.assertEqual(list(packet["markets"]), ["moneyline", "spread", "total"])

    def test_a_game_that_has_kicked_off_is_refused_with_the_ledgers_own_words_and_nothing_is_written(self):
        self.now = F.NOW + timedelta(hours=4)
        self.assertEqual(self.prepare(), 2)
        why = ledger.publish_refusal(F.build(self.store, built_at="2025-10-26T21:25:00Z"), self.now, 0.0)
        self.assertIn(f"SKIP {F.GAME_ID}: {why}", self.text)
        self.assertIn("kickoff", why)
        self.assertEqual(self.files(), [])

    def test_a_final_game_is_refused(self):
        self.store.game_by_id()[F.GAME_ID]["status"] = "final"
        self.assertEqual(self.prepare(), 2)
        self.assertIn("not pending", self.text)

    def test_a_game_with_no_prices_is_refused(self):
        self.assertEqual(self.prepare(rows=[]), 2)
        self.assertIn("prices no market", self.text)
        self.assertEqual(self.files(), [])

    def test_a_game_not_in_the_store_a_bad_club_and_a_bad_selector_are_refused_in_words(self):
        self.assertEqual(self.prepare(game="KC@BUF"), 2)
        self.assertIn("no NFL game KC@BUF on 2025-10-26", self.text)
        self.assertEqual(self.prepare(game="XXX@KC"), 2)
        self.assertIn("'XXX' is not an NFL club code", self.text)
        self.assertEqual(self.prepare(game="BUFKC"), 2)
        self.assertIn("--game must be AWAY@HOME", self.text)
        self.assertEqual(self.files(), [])

    def test_a_rehearsal_is_marked_and_can_be_checked_but_never_published(self):
        scratch = self.root / "practice"
        self.assertEqual(self.prepare(scratch=str(scratch)), 0)
        meta = json.loads((scratch / "prepare.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["rehearsal"])
        packet = json.loads((scratch / "packet.json").read_text(encoding="utf-8"))
        response = self.write_response(F.good_output(packet))
        self.assertEqual(nfl_pilot.check(str(scratch), response, out=self.out.append, now=lambda: self.now), 0)
        self.assertEqual(nfl_pilot.publish(str(scratch), response, model="m", cfg=F.CFG, root=self.root,
                                           now=lambda: self.now, out=self.out.append), 2)
        self.assertIn("rehearsal", self.text)
        self.assertEqual(self.store_rows(), [])

    def test_it_writes_only_under_the_nfl_folder_never_beside_the_mlb_pilot(self):
        self.prepare()
        for name in self.files():
            self.assertTrue(name.startswith("evidence/analyst_pilot_nfl/"), name)


class CheckAndPublish(Env):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.prepare(), 0, self.text)
        self.out.clear()

    def test_a_clean_answer_is_published_into_the_nfl_pilot_ledger_and_only_there(self):
        self.assertEqual(self.publish(), 0, self.text)
        self.assertIn("PUBLISHED (NFL pilot) 2025_08_BUF_KC v1", self.text)
        rows = self.store_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["kind"], row["game_id"], row["game_pk"], row["sport"]),
                         ("analyst_published", F.GAME_ID, F.GAME_ID, "nfl"))
        self.assertEqual((row["date"], row["away"], row["home"]), (F.DATE, "BUF", "KC"))
        self.assertEqual((row["first_pitch_utc"], row["kickoff_utc"]), (F.KICKOFF, F.KICKOFF))
        self.assertEqual((row["prompt_version"], row["prompt_hash"]),
                         ("analyst_prompt_nfl_v1", nfl_analyst.prompt_hash()))
        self.assertEqual((row["provenance"], row["mode"], row["attempts"]), ("session_assisted", "session_assisted", 1))
        self.assertEqual(row["packet_hash"], packet_mod.packet_hash(self.packet()))
        self.assertEqual(len(row["calls"]), 3)
        self.assertEqual([c["grading"]["family"] for c in row["calls"]], ["moneyline", "spread", "total"])
        self.assertTrue(ledger.verify(nfl_pilot.store_paths(self.root)["store"])["ok"])
        # the frozen packet file is the packet that was answered
        self.assertEqual(packet_mod.packet_hash(ledger.read_packet(row, root=self.root)), row["packet_hash"])

    def test_no_mlb_store_and_no_main_store_is_ever_created(self):
        self.publish()
        names = " ".join(self.files())
        for forbidden in ("analyst_v1.jsonl", "analyst_pilot_v1.jsonl", "analyst_pilot_usage_v1.jsonl",
                          "analyst_pilot_packets_v1", "analyst_usage_v1.jsonl", "analyst_packets_v1"):
            self.assertNotIn(forbidden, names.replace("analyst_pilot_nfl", ""), forbidden)
        self.assertEqual(sorted({n.split("/")[1] for n in self.files() if n.startswith("evidence/")}),
                         ["analyst_pilot_nfl", "analyst_pilot_nfl_packets_v1", "analyst_pilot_nfl_usage_v1.jsonl",
                          "analyst_pilot_nfl_v1.jsonl"])

    def test_a_usage_row_is_logged_with_the_reported_tokens_priced_at_list(self):
        self.publish(tokens_in=9000, tokens_out=3000, seconds=120, operator_minutes=4)
        usage = HashChainLedger(nfl_pilot.store_paths(self.root)["usage"]).read()
        self.assertEqual(len(usage), 1)
        self.assertEqual((usage[0]["game_id"], usage[0]["sport"], usage[0]["outcome"]), (F.GAME_ID, "nfl", "published"))
        self.assertEqual((usage[0]["input_tokens"], usage[0]["output_tokens"]), (9000, 3000))
        self.assertAlmostEqual(usage[0]["cost_usd"], 0.048, places=4)
        self.assertEqual(self.store_rows()[0]["run"]["cost_basis"], pilot.COST_BASIS)

    def test_a_spread_claim_nobody_quoted_is_published_struck_to_a_pass_with_the_audit_trail(self):
        packet = self.packet()
        out = F.good_output(packet)
        next(c for c in out["calls"] if c["slot_id"] == "spread")["reasons"][0]["claim"] = "BUF +4 is the number."
        response = self.write_response(out)
        self.assertEqual(self.check(response), 0)
        self.assertIn("spread: PASS", self.text)
        self.assertIn("STRUCK, published as a PASS", self.text)
        self.assertIn("names BUF +4", self.text)
        self.assertIn("REJECTED by the checker", self.text)
        self.assertEqual(self.publish(response), 0)
        row = self.store_rows()[0]
        spread = next(c for c in row["calls"] if c["slot_id"] == "spread")
        self.assertEqual(spread["verdict"], "PASS")
        self.assertEqual(spread["verification"]["status"], "could not be verified")
        self.assertEqual([s["slot_id"] for s in row["struck"]], ["spread"])
        self.assertNotIn("BUF +4", json.dumps(spread))

    def test_publishing_after_kickoff_is_refused_and_writes_nothing(self):
        response = self.good_response()
        self.check(response)
        late = F.NOW + timedelta(hours=3, minutes=1)
        code = nfl_pilot.publish(str(self.folder), response, model="m", cfg=F.CFG, root=self.root,
                                 now=lambda: late, out=self.out.append)
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", self.text)
        self.assertIn("kickoff 2025-10-26T20:25:00Z has passed", self.text)
        self.assertEqual(self.store_rows(), [])

    def test_a_packet_older_than_ninety_minutes_is_refused(self):
        response = self.good_response()
        self.check(response)
        code = nfl_pilot.publish(str(self.folder), response, model="m", cfg=F.CFG, root=self.root,
                                 now=lambda: F.NOW + timedelta(minutes=100), out=self.out.append)
        self.assertEqual(code, 2)
        self.assertIn("built 100 minutes ago", self.text)
        self.assertIn("injury reports may have moved", self.text)

    def test_an_answer_that_was_never_checked_is_refused(self):
        code = nfl_pilot.publish(str(self.folder), self.good_response(), model="m", cfg=F.CFG, root=self.root,
                                 now=lambda: self.now, out=self.out.append)
        self.assertEqual(code, 2)
        self.assertIn("never checked", self.text)

    def test_a_published_game_is_frozen_unless_refreshed_and_a_refresh_is_a_new_version(self):
        self.assertEqual(self.publish(), 0)
        self.out.clear()
        self.assertEqual(self.publish(), 2)
        self.assertIn("already has a pilot row (v1); frozen unless --refresh", self.text)
        self.out.clear()
        self.assertEqual(self.publish(refresh=True), 0, self.text)
        self.assertEqual([r["version"] for r in self.store_rows()], [1, 2])

    def test_a_response_that_fails_the_shape_check_is_refused_with_every_reason(self):
        out = F.good_output(self.packet())
        out["calls"].pop()
        response = self.write_response(out)
        self.assertEqual(self.check(response), 2)
        self.assertIn("REJECTED: the response fails the shape check", self.text)
        self.assertEqual(self.publish(response), 2)
        self.assertEqual(self.store_rows(), [])

    def test_the_publication_rule_holds_for_the_nfl_too(self):
        packet = self.packet()
        bad = F.good_output(packet)
        next(c for c in bad["calls"] if c["slot_id"] == "total")["reasons"][0]["claim"] = "Over 48 looks right."
        first = self.write_response(bad, "first.json")
        self.check(first)                                              # attempt 1: rejected
        second = self.write_response(F.good_output(packet), "second.json")
        self.assertEqual(self.check(second), 0)                        # attempt 2: clean, allowed
        self.out.clear()
        reroll = F.good_output(packet)
        reroll["summary"] = reroll["summary"] + " Again."
        third = self.write_response(reroll, "third.json")
        self.check(third)                                              # follows a clean one: a reroll
        self.assertIn("NOT PUBLISHABLE", self.text)
        self.assertEqual(nfl_pilot.publish(str(self.folder), third, model="m", cfg=F.CFG, root=self.root,
                                           now=lambda: self.now, out=self.out.append), 2)
        self.assertEqual(nfl_pilot.publish(str(self.folder), first, model="m", cfg=F.CFG, root=self.root,
                                           now=lambda: self.now, out=self.out.append), 2)
        self.assertEqual(nfl_pilot.publish(str(self.folder), second, model="m", cfg=F.CFG, root=self.root,
                                           now=lambda: self.now, out=self.out.append), 2)  # a later attempt exists
        self.assertEqual(self.store_rows(), [])

    def test_a_prompt_that_changed_since_prepare_is_refused(self):
        meta_path = self.folder / "prepare.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["prompt_hash"] = "0" * 64
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertEqual(self.publish(), 2)
        self.assertIn("prompt or schema has changed", self.text)

    def test_the_ledger_chain_breaks_if_a_row_is_edited(self):
        self.publish()
        path = Path(nfl_pilot.store_paths(self.root)["store"])
        self.assertTrue(ledger.verify(str(path))["ok"])
        path.write_text(path.read_text(encoding="utf-8").replace('"BUF"', '"XXX"', 1), encoding="utf-8")
        self.assertFalse(ledger.verify(str(path))["ok"])

    def test_an_nfl_folder_is_not_publishable_by_the_mlb_pilot_and_an_mlb_folder_not_by_the_nfl_one(self):
        response = self.good_response()
        self.check(response)
        self.assertEqual(pilot.publish(str(self.folder), response, model="m", cfg=F.CFG, root=self.root,
                                       now=lambda: self.now, out=self.out.append), 2)
        self.assertIn("prompt or schema has changed", self.text)
        meta_path = self.folder / "prepare.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("sport")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.out.clear()
        self.assertEqual(nfl_pilot.check(str(self.folder), response, out=self.out.append), 2)
        self.assertIn("prepared for MLB, not NFL", self.text)


class Grading(Env):
    def graded_calls(self, away, home, **call_kw):
        spec_ml = {"family": "moneyline", "side": "away", "line": None, "reference_price": 175}
        result = {"away_score": away, "home_score": home}
        return nfl_grading.grade_call(dict(slot_id="moneyline", selection="BUF", verdict="TAKE_OTHER_SIDE",
                                           price=175, book="draftkings", grading=spec_ml, **call_kw),
                                      F.GAME_ID, result)

    def test_a_moneyline_win_loss_and_tie(self):
        self.assertEqual(self.graded_calls(24, 20)["result"], "WIN")
        self.assertEqual(self.graded_calls(24, 20)["profit_units"], 1.75)
        self.assertEqual(self.graded_calls(20, 24)["result"], "LOSS")
        tie = self.graded_calls(23, 23)
        self.assertEqual((tie["result"], tie["profit_units"]), ("PUSH", 0.0))
        self.assertIn("tie", tie["reason"])

    def test_a_spread_is_graded_by_the_margin_against_the_number(self):
        def spread(selection, side, line, away, home):
            spec = {"family": "spread", "side": side, "line": line, "reference_price": -110}
            return nfl_grading.grade_call(dict(slot_id="spread", selection=selection, verdict="TAKE", price=-110,
                                               book="draftkings", grading=spec), F.GAME_ID,
                                          {"away_score": away, "home_score": home})["result"]
        self.assertEqual(spread("BUF +3.5", "away", 3.5, 20, 23), "WIN")     # lost by 3, got 3.5
        self.assertEqual(spread("BUF +3.5", "away", 3.5, 20, 24), "LOSS")    # lost by 4
        self.assertEqual(spread("KC -3.5", "home", -3.5, 20, 24), "WIN")     # won by 4, laid 3.5
        self.assertEqual(spread("KC -3.5", "home", -3.5, 20, 23), "LOSS")
        self.assertEqual(spread("KC -3", "home", -3.0, 20, 23), "PUSH")      # on the number

    def test_a_total_is_graded_over_under_and_push(self):
        def total(side, line, away, home):
            spec = {"family": "total", "side": side, "line": line, "reference_price": -110}
            return nfl_grading.grade_call(dict(slot_id="total", selection=f"{side} {line}", verdict="TAKE", price=-110,
                                               book="draftkings", grading=spec), F.GAME_ID,
                                          {"away_score": away, "home_score": home})["result"]
        self.assertEqual(total("over", 47.5, 24, 24), "WIN")
        self.assertEqual(total("under", 47.5, 24, 24), "LOSS")
        self.assertEqual(total("over", 48.0, 24, 24), "PUSH")

    def test_no_final_score_is_unresolved_never_a_loss(self):
        spec = {"family": "moneyline", "side": "away", "line": None, "reference_price": 175}
        call = dict(slot_id="moneyline", selection="BUF", verdict="TAKE_OTHER_SIDE", price=175, book="b", grading=spec)
        self.assertEqual(nfl_grading.grade_call(call, F.GAME_ID, None)["result"], "UNRESOLVED")

    def test_a_pass_reports_what_the_passed_side_would_have_done(self):
        spec = {"family": "spread", "side": "away", "line": 3.5, "reference_price": -110}
        call = dict(slot_id="spread", selection="BUF +3.5", verdict="PASS", price=-110, book="b", grading=spec)
        got = nfl_grading.grade_call(call, F.GAME_ID, {"away_score": 20, "home_score": 23})
        self.assertEqual((got["result"], got["would_have"]), ("PASS", {"result": "WIN", "price": -110}))
        self.assertIsNone(nfl_grading.grade_call(call, F.GAME_ID, None)["would_have"])

    def test_results_come_from_final_games_of_the_date_in_the_store(self):
        store = self.store
        store.game_by_id()[F.GAME_ID].update(status="final", away_score=24, home_score=20)
        self.assertEqual(nfl_grading.results_for(store, F.DATE), {F.GAME_ID: {"away_score": 24, "home_score": 20}})
        self.assertEqual(nfl_grading.results_for(store, "2025-10-19"),
                         {"2025_07_SEA_BUF": {"away_score": 16, "home_score": 19}})
        self.assertEqual(nfl_grading.results_for(store, "2025-10-27"), {})
        store.game_by_id()[F.GAME_ID].update(status="scheduled")          # a score without a final status
        self.assertEqual(nfl_grading.results_for(store, F.DATE), {})
        store.game_by_id()[F.GAME_ID].update(status="final")
        store.game_by_id()[F.GAME_ID]["away_score"] = None
        self.assertEqual(nfl_grading.results_for(store, F.DATE), {})

    def test_a_published_brief_is_graded_once_from_the_store_and_counted_in_its_own_record(self):
        self.assertEqual(self.prepare(), 0)
        self.publish()
        path = nfl_pilot.store_paths(self.root)["store"]
        quiet = []
        self.assertEqual(nfl_cli.execute_grade(F.DATE, store=self.store, now=lambda: F.NOW + timedelta(hours=9),
                                               out=quiet.append, store_path=path), 0)
        self.assertIn("published=1 graded=0", quiet[0])               # the game is not final in the store yet
        self.assertIn("no new result yet", "\n".join(quiet))
        self.store.game_by_id()[F.GAME_ID].update(status="final", away_score=17, home_score=27)
        quiet.clear()
        nfl_cli.execute_grade(F.DATE, store=self.store, now=lambda: F.NOW + timedelta(hours=9),
                              out=quiet.append, store_path=path)
        self.assertIn("published=1 graded=1 complete=1", quiet[0])
        quiet.clear()
        nfl_cli.execute_grade(F.DATE, store=self.store, now=lambda: F.NOW + timedelta(hours=10),
                              out=quiet.append, store_path=path)
        self.assertIn("graded=0", quiet[0])                           # idempotent
        view = ledger.game_view(F.DATE, "BUF", "KC", path=path)
        self.assertEqual(view["final"], {"away_score": 17, "home_score": 27})
        ml = next(c for c in view["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual((ml["verdict"], ml["result"]), ("TAKE_OTHER_SIDE", "LOSS"))
        spread = next(c for c in view["calls"] if c["slot_id"] == "spread")
        self.assertEqual(spread["would_have"]["result"] in ("WIN", "LOSS"), True)
        rec = ledger.record(path=path, families=nfl_grading.FAMILIES)
        self.assertEqual(list(rec["families"]), ["moneyline", "spread", "total"])
        self.assertEqual((rec["families"]["moneyline"]["taken"], rec["families"]["moneyline"]["losses"]), (1, 1))
        self.assertEqual(rec["families"]["moneyline"]["win_rate"], None)        # withheld under 30 graded calls
        self.assertEqual(rec["games_settled"], 1)

    def test_the_record_command_prints_the_nfl_families_the_label_and_the_integrity_check(self):
        self.prepare()
        self.publish()
        lines = []
        files = nfl_pilot.store_paths(self.root)
        self.assertEqual(nfl_cli.execute_record(out=lines.append, store_path=files["store"],
                                                usage_path=files["usage"], cfg=F.CFG), 0)
        text = "\n".join(lines)
        self.assertIn(PILOT_LABEL, text)
        for family in ("moneyline", "spread", "total"):
            self.assertIn(family, text)
        for mlb_only in ("run_line", "team_total", "prop "):
            self.assertNotIn(mlb_only, text)
        self.assertIn("nfl pilot ledger: OK (1 rows)", text)
        self.assertIn("games published 1, settled 0", text)
        self.assertIn("1/1 games published", text)



class TheCommandLine(Env):
    def parse(self, *argv):
        root = argparse.ArgumentParser()
        sub = root.add_subparsers(dest="command", required=True)
        cli.add_parser(sub)
        return root.parse_args(["analyst", *argv])

    def run_cli(self, *argv):
        args = self.parse(*argv)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch.object(nfl_pilot, "default_store", return_value=self.store), \
                mock.patch.object(nfl_pilot, "default_rows", return_value=F.odds_rows()), \
                mock.patch.object(cli, "_now", return_value=self.now), \
                mock.patch.object(nfl_pilot.pilot, "_root", return_value=self.root):
            code = cli.main(args)
        return code, buf.getvalue()

    def test_prepare_check_and_publish_route_to_the_nfl_pilot_and_publish_follows_the_folder(self):
        code, text = self.run_cli("pilot", "prepare", "--sport", "nfl", "--date", F.DATE, "--game", "BUF@KC")
        self.assertEqual(code, 0, text)
        self.assertIn("PREPARED 2025_08_BUF_KC", text)
        response = self.write_response(F.good_output(self.packet()))
        # no --sport on check or publish: the folder says which sport it is
        code, text = self.run_cli("pilot", "check", "--dir", str(self.folder), "--response", response)
        self.assertEqual(code, 0, text)
        self.assertIn("CHECK 2025_08_BUF_KC", text)
        self.assertIn("CLEAN", text)
        code, text = self.run_cli("pilot", "publish", "--dir", str(self.folder), "--response", response,
                                  "--model", "claude-sonnet-5-5")
        self.assertEqual(code, 0, text)
        self.assertIn("PUBLISHED (NFL pilot)", text)
        self.assertEqual(len(self.store_rows()), 1)

    def test_an_mlb_selector_on_an_nfl_folder_is_refused(self):
        self.run_cli("pilot", "prepare", "--sport", "nfl", "--date", F.DATE, "--game", "BUF@KC")
        code, text = self.run_cli("pilot", "check", "--sport", "mlb", "--dir", str(self.folder),
                                  "--response", str(self.root / "x.json"))
        self.assertEqual(code, 2)
        self.assertIn("prepared for the NFL", text)

    def test_run_has_no_nfl_and_grade_and_record_do(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse("run", "--sport", "nfl", "--date", F.DATE)
        self.assertEqual(self.parse("grade", "--sport", "nfl", "--date", F.DATE).sport, "nfl")
        self.assertEqual(self.parse("record", "--sport", "nfl").sport, "nfl")

    def test_mlb_prepare_is_still_the_default(self):
        self.assertEqual(self.parse("pilot", "prepare", "--date", F.DATE, "--game", "NYY@TB").sport, "mlb")


class WithoutFastApi(unittest.TestCase):
    """Linux CI has no FastAPI. Every NFL analyst module under src/ must load without it."""

    def test_the_src_modules_import_with_fastapi_hidden(self):
        code = ("import sys\n"
                "sys.modules['fastapi'] = None\n"
                "sys.modules['starlette'] = None\n"
                "import src.analyst.nfl_packet, src.analyst.nfl_analyst, src.analyst.nfl_grading\n"
                "import src.analyst.nfl_pilot, src.analyst.nfl_cli, src.analyst.cli\n"
                "print('ok')\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
