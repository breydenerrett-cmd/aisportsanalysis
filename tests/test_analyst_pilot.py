"""The supervised-session pilot: prepare, check, publish, and what it must never touch.

Everything is offline and injected: a temp folder stands in for the repo root (every pilot store lives
under it), the loader returns the shared synthetic game, and the clock is a lambda. Nothing here reads
the repo's evidence, calls the API or reaches a network. The "same packet" test is the heart of it: the
packet a session answered is the packet the ledger froze.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.analyst import PILOT_LABEL, LABEL
from src.analyst import analyst as A
from src.analyst import cli, critic, ledger, pilot
from src.analyst import packet as packet_mod
from tests import analyst_fixtures as F

ROOT = Path(__file__).resolve().parent.parent


def item(state="pending", **overrides):
    base = {
        "payload": F.payload(state), "multibook_rows": F.multibook_rows(),
        "team_total_rows": F.team_total_rows(), "batter_prop_rows": F.batter_prop_rows(),
        "pitcher_prop_rows": F.pitcher_prop_rows(), "prop_board": F.prop_board(),
        "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
        "section_as_of": {"teams": "2026-10-02", "starters": "2026-10-02"},
    }
    base.update(overrides)
    return base


class Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.out = []
        self.now = F.NOW

    @property
    def text(self):
        return "\n".join(self.out)

    def prepare(self, *items, scratch=None, game="NYY@TB"):
        return pilot.prepare(F.DATE, game, scratch=scratch, cfg=F.CFG, root=self.root,
                             loader=lambda date: list(items) or [item()],
                             now=lambda: self.now, out=self.out.append)

    @property
    def folder(self):
        return pilot.game_folder(F.DATE, "NYY", "TB", self.root)

    def write_response(self, output, name="answer.json"):
        path = self.root / name
        path.write_text(json.dumps(output), encoding="utf-8")
        return str(path)

    def good_response(self):
        return self.write_response(F.good_output(F.build()))

    def publish(self, response=None, *, now=None, **kw):
        kw.setdefault("model", "claude-sonnet-5-5")
        return pilot.publish(str(self.folder), response or self.good_response(), cfg=F.CFG,
                             root=self.root, now=lambda: now or self.now, out=self.out.append, **kw)

    def files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())

    def store_rows(self):
        return ledger.rows(pilot.store_paths(self.root)["store"])


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

class Prepare(Env):
    def test_it_writes_the_three_files_for_the_game(self):
        self.assertEqual(self.prepare(), 0, self.text)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["packet.json", "prepare.json", "request.json"])
        self.assertEqual(self.folder.name, "2026-10-03_NYY-TB")
        self.assertEqual(self.folder.parent.relative_to(self.root).as_posix(), "evidence/analyst_pilot")

    def test_the_request_is_exactly_what_the_api_call_would_send(self):
        self.prepare()
        packet = F.build()
        self.assertEqual(json.loads((self.folder / "request.json").read_text(encoding="utf-8")),
                         json.loads(json.dumps(A.build_request(packet, F.CFG))))

    def test_prepare_json_names_the_packet_the_prompt_and_the_times(self):
        self.prepare()
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        packet = F.build()
        self.assertEqual(meta["packet_hash"], packet_mod.packet_hash(packet))
        self.assertEqual((meta["prompt_version"], meta["prompt_hash"]),
                         ("analyst_prompt_v2", ledger.prompt_hash()))
        self.assertEqual(meta["built_at"], F.BUILT_AT)
        self.assertEqual(meta["first_pitch_utc"], F.FIRST_PITCH)
        self.assertEqual(meta["model"], F.CFG["model"])
        body = A.build_request(packet, F.CFG)
        self.assertEqual(meta["token_estimate"],
                         A.estimate_tokens(body["system"], body["messages"][0]["content"]))
        self.assertFalse(meta["rehearsal"])

    def test_the_packet_on_disk_hashes_to_the_hash_it_names(self):
        self.prepare()
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        packet = json.loads((self.folder / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(packet_mod.packet_hash(packet), meta["packet_hash"])

    def test_a_started_game_is_refused_with_the_runs_own_words_and_nothing_is_written(self):
        self.assertEqual(self.prepare(item(state="live")), 2)
        self.assertIn("the game is 'live', not pending", self.text)
        self.assertEqual(self.files(), [])
        # the same words the run uses (cli.refusal is ledger.publish_refusal)
        why = ledger.publish_refusal(F.build(state="live"), self.now, 0.0)
        self.assertIn(f"SKIP NYY-TB-2026-10-03-1: {why}", self.text)

    def test_first_pitch_already_passed_is_refused(self):
        self.now = F.NOW + timedelta(hours=6)
        self.assertEqual(self.prepare(), 2)
        self.assertIn("has passed or is inside the", self.text)
        self.assertEqual(self.files(), [])

    def test_an_unpriced_game_is_refused_like_a_run_refuses_it(self):
        bare = item(multibook_rows=[], team_total_rows=[], batter_prop_rows=[], pitcher_prop_rows=[],
                    prop_board=[])
        self.assertEqual(self.prepare(bare), 2)
        self.assertIn("the packet prices no market, so there is nothing to call", self.text)
        self.assertEqual(self.files(), [])

    def test_a_game_that_is_not_on_the_slate_is_an_error(self):
        self.assertEqual(self.prepare(game="BOS@NYM"), 2)
        self.assertIn("no games found", self.text)

    def test_a_malformed_game_argument_is_refused(self):
        self.assertEqual(self.prepare(game="NYY"), 2)
        self.assertIn("AWAY@HOME", self.text)

    def test_scratch_writes_there_instead_and_marks_a_rehearsal(self):
        scratch = self.root / "rehearsal"
        self.assertEqual(self.prepare(scratch=str(scratch)), 0)
        self.assertTrue(json.loads((scratch / "prepare.json").read_text(encoding="utf-8"))["rehearsal"])
        self.assertFalse((self.root / "evidence").exists())
        self.assertIn("REHEARSAL", self.text)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

class Check(Env):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.out.clear()

    def check(self, response, folder=None):
        return pilot.check(str(folder or self.folder), response, out=self.out.append)

    def test_a_good_answer_keeps_every_call_and_prints_totals(self):
        self.assertEqual(self.check(self.good_response()), 0)
        packet = F.build()
        self.assertIn(f"totals: {len(packet['slots'])} calls, {len(packet['slots'])} kept, 0 struck", self.text)
        self.assertIn("moneyline: TAKE_OTHER_SIDE NYY: kept", self.text)
        self.assertIn("summary: ok", self.text)

    def test_check_publishes_nothing(self):
        self.check(self.good_response())
        self.assertFalse((self.root / "evidence" / "analyst_pilot_v1.jsonl").exists())
        self.assertEqual([f for f in self.files() if "analyst_pilot_v1" in f or "usage" in f], [])

    def test_a_planted_wrong_evidence_value_is_struck_and_says_why(self):
        out = F.good_output(F.build())
        out["calls"][0]["reasons"][1]["evidence"][0]["value"] = 4.4402
        self.check(self.write_response(out))
        self.assertIn("moneyline: TAKE_OTHER_SIDE NYY: STRUCK", self.text)
        self.assertIn("holds 3.8602, not 4.4402", self.text)
        self.assertIn(f"{len(F.build()['slots'])} calls, {len(F.build()['slots']) - 1} kept, 1 struck", self.text)

    def test_a_take_at_minus_200_is_struck(self):
        rows = F.multibook_rows(home_ml=(-250, -240, -260), away_ml=(205, 210, 200))
        packet = F.build(multibook_rows=rows)
        self.assertEqual(self.prepare(item(multibook_rows=rows)), 0)
        market = packet["markets"]["moneyline"]
        lean = market["options"][0]
        price, book = lean["best"]["price"], lean["best"]["book"]
        fair = 0.7
        out = F.good_output(packet)
        take = F.pass_call(packet, "moneyline")
        take.update(verdict="TAKE", selection=lean["selection"], price=price, book=book,
                    fair_estimate=fair, confidence="medium",
                    pass_price=int(round(critic.odds_math.probability_to_american(fair))),
                    case_against=F.case_against_for(packet, "moneyline"))
        out["calls"][0] = take
        self.out.clear()
        self.check(self.write_response(out))
        self.assertIn("-200 or worse", self.text)
        self.assertIn("moneyline: TAKE", self.text)
        self.assertIn("STRUCK", self.text)

    def test_a_take_without_a_case_against_is_struck_and_says_so(self):
        out = F.good_output(F.build())
        out["calls"][0]["case_against"] = None
        self.check(self.write_response(out))
        self.assertIn("moneyline: TAKE_OTHER_SIDE NYY: STRUCK", self.text)
        self.assertIn("a TAKE needs a case_against", self.text)

    def test_a_shape_error_is_rejected_with_every_reason(self):
        out = F.good_output(F.build())
        out["summary"] = "too short"
        del out["calls"][1]
        self.assertEqual(self.check(self.write_response(out)), 2)
        self.assertIn("REJECTED", self.text)
        self.assertIn("summary is 2 words", self.text)

    def test_it_works_on_a_rehearsal_folder(self):
        scratch = self.root / "rehearsal"
        self.prepare(scratch=str(scratch))
        self.out.clear()
        self.assertEqual(self.check(self.good_response(), folder=scratch), 0)
        self.assertIn("(rehearsal)", self.text)

    def test_a_response_that_is_not_json_is_an_error_not_a_crash(self):
        bad = self.root / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        self.assertEqual(self.check(str(bad)), 2)
        self.assertIn("not valid JSON", self.text)

    def test_a_markdown_fence_around_the_answer_is_tolerated(self):
        fenced = self.root / "fenced.json"
        fenced.write_text("```json\n" + json.dumps(F.good_output(F.build())) + "\n```", encoding="utf-8")
        self.assertEqual(self.check(str(fenced)), 0)


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

class Publish(Env):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.out.clear()

    def test_the_same_packet_prepare_froze_is_the_packet_the_row_carries(self):
        self.assertEqual(self.publish(), 0, self.text)
        row = self.store_rows()[0]
        prepared = json.loads((self.folder / "packet.json").read_text(encoding="utf-8"))
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        self.assertEqual(row["packet_hash"], meta["packet_hash"])
        self.assertEqual(ledger.read_packet(row), prepared)
        self.assertEqual(row["packet_hash"], packet_mod.packet_hash(F.build()))

    def test_the_row_says_how_it_was_made(self):
        self.publish(tokens_in=10000, tokens_out=5000, seconds=95.5, operator_minutes=12)
        row = self.store_rows()[0]
        self.assertEqual(row["provenance"], "session_assisted")
        self.assertEqual((row["prompt_version"], row["prompt_hash"]), ("analyst_prompt_v2", ledger.prompt_hash()))
        run = row["run"]
        self.assertEqual((run["mode"], run["model"]), ("session_assisted", "claude-sonnet-5-5"))
        self.assertEqual((run["tokens_in"], run["tokens_out"]), (10000, 5000))
        self.assertEqual((run["seconds"], run["operator_minutes"]), (95.5, 12))
        self.assertAlmostEqual(run["cost_usd"], 10000 * 2.0 / 1e6 + 5000 * 10.0 / 1e6, places=4)
        self.assertIn("estimate at list price", run["cost_basis"])
        self.assertIn("not a bill", run["cost_basis"])
        self.assertEqual(row["model"], "claude-sonnet-5-5")

    def test_without_token_counts_there_is_no_dollar_figure_not_a_guess(self):
        self.publish()
        self.assertIsNone(self.store_rows()[0]["run"]["cost_usd"])
        usage = ledger.HashChainLedger(pilot.store_paths(self.root)["usage"]).read()
        self.assertEqual(usage[0]["mode"], "session_assisted")
        self.assertFalse(usage[0]["tokens_reported"])

    def test_only_the_pilot_stores_are_written_and_never_the_main_ones(self):
        self.publish(tokens_in=1, tokens_out=1)
        written = [f for f in self.files() if not f.startswith("evidence/analyst_pilot/")]
        self.assertEqual(len(written), 4, written)   # answer.json, store, usage, one packet
        self.assertIn("evidence/analyst_pilot_v1.jsonl", written)
        self.assertIn("evidence/analyst_pilot_usage_v1.jsonl", written)
        self.assertTrue(any(f.startswith("evidence/analyst_pilot_packets_v1/2026-10-03/") for f in written))
        for main in (ledger.STORE, ledger.USAGE_STORE):
            self.assertFalse((self.root / main).exists(), main)
        self.assertFalse((self.root / ledger.PACKET_DIR).exists())

    def test_pilot_rows_never_reach_the_main_store_or_its_record(self):
        main = str(self.root / "main.jsonl")
        self.publish()
        self.assertFalse(Path(main).exists())
        rec = ledger.record(path=main)
        self.assertEqual((rec["games_published"], rec["families"]["moneyline"]["taken"]), (0, 0))
        self.assertEqual(ledger.record(path=pilot.store_paths(self.root)["store"])["games_published"], 1)

    def test_a_wrong_evidence_value_is_published_struck_not_refused(self):
        out = F.good_output(F.build())
        out["calls"][0]["reasons"][1]["evidence"][0]["value"] = 4.4402
        self.assertEqual(self.publish(self.write_response(out)), 0)
        row = self.store_rows()[0]
        ml = next(c for c in row["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual((ml["verdict"], ml["verification"]["status"]), ("PASS", "could not be verified"))
        self.assertEqual([s["slot_id"] for s in row["struck"]], ["moneyline"])
        self.assertIn("1 struck", self.text)

    def test_a_take_without_a_case_against_is_published_struck(self):
        out = F.good_output(F.build())
        out["calls"][0].pop("case_against")
        self.assertEqual(self.publish(self.write_response(out)), 0)
        row = self.store_rows()[0]
        ml = next(c for c in row["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual(ml["verdict"], "PASS")
        self.assertTrue(any("case_against" in p for p in row["struck"][0]["problems"]))

    def test_a_packet_that_differs_from_the_prepared_one_is_refused(self):
        packet_file = self.folder / "packet.json"
        packet = json.loads(packet_file.read_text(encoding="utf-8"))
        packet["markets"]["moneyline"]["options"][0]["best"]["price"] = -101
        packet_file.write_text(json.dumps(packet), encoding="utf-8")
        self.assertEqual(self.publish(), 2)
        self.assertIn("is not the packet that was prepared", self.text)
        self.assertEqual(self.store_rows() if Path(pilot.store_paths(self.root)["store"]).exists() else [], [])

    def test_a_prepare_json_that_names_another_hash_is_refused(self):
        meta_file = self.folder / "prepare.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["packet_hash"] = "0" * 64
        meta_file.write_text(json.dumps(meta), encoding="utf-8")
        self.assertEqual(self.publish(), 2)
        self.assertIn("is not the packet that was prepared", self.text)

    def test_a_game_that_has_started_is_refused(self):
        self.assertEqual(self.publish(now=F.NOW + timedelta(hours=5)), 2)
        self.assertIn("has passed or is inside the", self.text)
        self.assertFalse(Path(pilot.store_paths(self.root)["store"]).exists())

    def test_a_stale_packet_is_refused_and_the_limit_is_the_configs(self):
        self.assertEqual(F.CFG["pilot"]["max_packet_age_minutes"], 90)
        self.assertEqual(self.publish(now=F.NOW + timedelta(minutes=91)), 2)
        self.assertIn("built 91 minutes ago", self.text)
        self.assertIn("90-minute limit", self.text)
        self.assertFalse(Path(pilot.store_paths(self.root)["store"]).exists())

    def test_a_packet_exactly_at_the_limit_still_publishes(self):
        self.assertEqual(self.publish(now=F.NOW + timedelta(minutes=90)), 0, self.text)

    def test_the_limit_comes_from_config_not_the_code(self):
        cfg = dict(F.CFG, pilot={"max_packet_age_minutes": 10})
        code = pilot.publish(str(self.folder), self.good_response(), model="m", cfg=cfg, root=self.root,
                             now=lambda: F.NOW + timedelta(minutes=11), out=self.out.append)
        self.assertEqual(code, 2)
        self.assertIn("10-minute limit", self.text)

    def test_a_rehearsal_folder_is_refused(self):
        scratch = self.root / "rehearsal"
        self.prepare(scratch=str(scratch))
        self.out.clear()
        code = pilot.publish(str(scratch), self.good_response(), model="m", cfg=F.CFG, root=self.root,
                             now=lambda: self.now, out=self.out.append)
        self.assertEqual(code, 2)
        self.assertIn("is a rehearsal", self.text)
        self.assertFalse(Path(pilot.store_paths(self.root)["store"]).exists())

    def test_a_second_publish_is_refused_without_refresh_and_the_first_row_stands(self):
        self.assertEqual(self.publish(), 0)
        self.out.clear()
        self.assertEqual(self.publish(), 2)
        self.assertIn("already has a pilot row (v1)", self.text)
        self.assertEqual(len([r for r in self.store_rows() if r["kind"] == ledger.KIND_PUBLISHED]), 1)

    def test_refresh_writes_a_new_version_that_supersedes_the_first(self):
        self.publish()
        self.assertEqual(self.publish(refresh=True), 0, self.text)
        rows = [r for r in self.store_rows() if r["kind"] == ledger.KIND_PUBLISHED]
        self.assertEqual([r["version"] for r in rows], [1, 2])
        self.assertEqual(rows[1]["supersedes"], rows[0]["row_hash"])

    def test_a_graded_game_cannot_be_refreshed(self):
        self.publish()
        ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [], now=F.NOW,
                          path=pilot.store_paths(self.root)["store"])
        self.out.clear()
        self.assertEqual(self.publish(refresh=True), 2)
        self.assertIn("already graded", self.text)

    def test_a_prompt_that_changed_since_prepare_is_refused(self):
        with mock.patch.object(A, "PROMPT_VERSION", "analyst_prompt_v3"):
            self.assertEqual(self.publish(), 2)
        self.assertIn("has changed since this game was prepared", self.text)

    def test_a_response_that_fails_the_shape_check_publishes_nothing(self):
        out = F.good_output(F.build())
        out["summary"] = "far too short"
        self.assertEqual(self.publish(self.write_response(out)), 2)
        self.assertIn("fails the shape check", self.text)
        self.assertFalse(Path(pilot.store_paths(self.root)["store"]).exists())

    def test_the_model_is_named_and_counts_are_not_negative(self):
        self.assertEqual(self.publish(model=" "), 2)
        self.assertIn("--model must name the model", self.text)
        self.out.clear()
        self.assertEqual(self.publish(tokens_in=-5), 2)
        self.assertIn("tokens_in must be a number of at least 0", self.text)

    def test_nothing_in_a_publish_touches_the_network(self):
        with mock.patch.object(A, "urllib_post", side_effect=AssertionError("network used")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            self.assertEqual(self.publish(), 0)


# ---------------------------------------------------------------------------
# grade and record cover the pilot, separately
# ---------------------------------------------------------------------------

class GradeAndRecord(Env):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.publish()
        self.out.clear()
        self.pilot_store = pilot.store_paths(self.root)["store"]
        self.main = str(self.root / "main.jsonl")

    def test_grade_grades_pilot_rows_when_the_store_exists(self):
        cli.execute_grade(F.DATE, results=lambda d: ({849835: {"away_score": "5", "home_score": "3"}}, []),
                          now=lambda: F.NOW, out=self.out.append, store_path=self.main,
                          arm_b_store=str(self.root / "b.jsonl"), pilot_store=self.pilot_store)
        self.assertIn("[pilot]: published=1 graded=1", self.text)
        graded = [r for r in ledger.rows(self.pilot_store) if r["kind"] == ledger.KIND_GRADED]
        self.assertEqual(len(graded), 1)
        self.assertFalse(Path(self.main).exists())

    def test_grade_leaves_the_pilot_alone_when_the_main_store_is_injected_and_the_pilot_is_not(self):
        cli.execute_grade(F.DATE, results=lambda d: ({849835: {"away_score": "5", "home_score": "3"}}, []),
                          now=lambda: F.NOW, out=self.out.append, store_path=self.main,
                          arm_b_store=str(self.root / "b.jsonl"))
        self.assertNotIn("[pilot]", self.text)

    def test_grade_with_no_pilot_store_prints_no_pilot_line(self):
        cli.execute_grade(F.DATE, results=lambda d: ({}, []), now=lambda: F.NOW, out=self.out.append,
                          store_path=self.main, arm_b_store=str(self.root / "b.jsonl"),
                          pilot_store=str(self.root / "nowhere.jsonl"))
        self.assertNotIn("[pilot]", self.text)

    def test_record_prints_the_pilot_under_its_own_heading_and_never_in_the_main_counts(self):
        code = cli.execute_record(out=self.out.append, store_path=self.main, usage_path=str(self.root / "u.jsonl"),
                                  cfg=F.CFG, pilot_store=self.pilot_store)
        self.assertEqual(code, 0)
        lines = self.out
        heading = lines.index("SUPERVISED-SESSION BRIEFS (a separate record; never added to the one above)")
        main_part, pilot_part = lines[:heading], lines[heading:]
        self.assertEqual(main_part[0], LABEL)
        self.assertIn("games published 0, settled 0", main_part)
        self.assertEqual(pilot_part[1], PILOT_LABEL)
        self.assertIn("games published 1, settled 0", pilot_part)
        self.assertIn("pilot ledger: OK", "\n".join(pilot_part))

    def test_record_without_a_pilot_store_is_what_it_always_was(self):
        cli.execute_record(out=self.out.append, store_path=self.main, usage_path=str(self.root / "u.jsonl"),
                           cfg=F.CFG, pilot_store=str(self.root / "nowhere.jsonl"))
        self.assertNotIn("SUPERVISED-SESSION", self.text)


# ---------------------------------------------------------------------------
# wiring and shipping
# ---------------------------------------------------------------------------

class TheCommandsAreWired(unittest.TestCase):
    def parse(self, *argv):
        top = argparse.ArgumentParser()
        cli.add_parser(top.add_subparsers(dest="command", required=True))
        return top.parse_args(["analyst", *argv])

    def test_prepare_check_and_publish_parse_with_their_options(self):
        a = self.parse("pilot", "prepare", "--date", "2026-10-03", "--game", "NYY@TB", "--scratch", "x")
        self.assertEqual((a.pilot_command, a.date, a.game, a.scratch), ("prepare", "2026-10-03", "NYY@TB", "x"))
        a = self.parse("pilot", "check", "--dir", "d", "--response", "r.json")
        self.assertEqual((a.pilot_command, a.dir, a.response), ("check", "d", "r.json"))
        a = self.parse("pilot", "publish", "--dir", "d", "--response", "r.json", "--model", "m",
                       "--tokens-in", "10", "--tokens-out", "5", "--seconds", "1.5",
                       "--operator-minutes", "3", "--refresh")
        self.assertEqual((a.model, a.tokens_in, a.tokens_out, a.seconds, a.operator_minutes, a.refresh),
                         ("m", 10, 5, 1.5, 3.0, True))

    def test_main_dispatches_each_to_the_pilot_module(self):
        with mock.patch.object(pilot, "prepare", return_value=0) as prep:
            cli.main(self.parse("pilot", "prepare", "--date", "2026-10-03", "--game", "NYY@TB"))
        prep.assert_called_once_with("2026-10-03", "NYY@TB", scratch=None)
        with mock.patch.object(pilot, "check", return_value=0) as chk:
            cli.main(self.parse("pilot", "check", "--dir", "d", "--response", "r"))
        chk.assert_called_once_with("d", "r")
        with mock.patch.object(pilot, "publish", return_value=0) as pub:
            cli.main(self.parse("pilot", "publish", "--dir", "d", "--response", "r", "--model", "m"))
        self.assertEqual(pub.call_args.kwargs["model"], "m")
        self.assertFalse(pub.call_args.kwargs["refresh"])

    def test_it_is_an_mlb_command_only(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.parse("pilot", "prepare", "--sport", "ufc", "--date", "2026-10-03", "--game", "A@B")


class TheStoresShipInTheImage(unittest.TestCase):
    DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")

    def test_the_pilot_stores_sit_under_evidence_which_the_image_copies(self):
        for path in (pilot.STORE, pilot.USAGE_STORE, pilot.PACKET_DIR, pilot.PILOT_DIR):
            self.assertTrue(path.replace("\\", "/").startswith("evidence/"), path)
        self.assertRegex(self.DOCKERFILE, re.compile(r"^COPY evidence/ evidence/\s*$", re.M))

    def test_the_sample_config_sits_under_config_which_the_image_copies(self):
        self.assertRegex(self.DOCKERFILE, re.compile(r"^COPY config/ config/\s*$", re.M))
        self.assertTrue((ROOT / "config" / "sample_brief.json").is_file())

    def test_the_pilot_paths_are_not_the_main_analysts(self):
        for pair in ((pilot.STORE, ledger.STORE), (pilot.USAGE_STORE, ledger.USAGE_STORE),
                     (pilot.PACKET_DIR, ledger.PACKET_DIR)):
            self.assertNotEqual(*pair)

    def test_the_pilot_never_calls_a_ledger_function_without_an_explicit_path(self):
        text = (ROOT / "src" / "analyst" / "pilot.py").read_text(encoding="utf-8")
        for call in ("ledger.publish(", "ledger.log_usage(", "ledger.rows("):
            for m in re.finditer(re.escape(call), text):
                window = text[m.start():m.start() + 700]
                self.assertRegex(window, r"path=files\[|files\[\"store\"\]", call)

    def test_the_new_config_key_is_in_the_shipped_file_and_validated(self):
        shipped = json.loads((ROOT / "config" / "analyst.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["pilot"], {"max_packet_age_minutes": 90})
        from src.analyst import config
        bad = copy.deepcopy(dict(config.DEFAULTS))
        bad["pilot"] = {"max_packet_age_minutes": 0}
        with self.assertRaises(config.ConfigError):
            config.validate(bad)


if __name__ == "__main__":
    unittest.main()
