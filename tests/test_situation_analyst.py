"""The situation layer in the analyst: the switch, arm B, and the proof that arm A did not move.

THE THREE THINGS THIS FILE PINS
-------------------------------
1. ARM A IS UNTOUCHED. The prompts, the packets and the ledger rows arm A writes are byte for byte
   what they were before arm B existed: the hashes below were computed from the BASE commit's own
   source (not from this working tree) and pinned. Nothing here lets the situation reach arm A, not
   even through the written read.
2. ARM B IS A SECOND ANALYST, NOT A DIFFERENT ONE. Same model call, schema, critic and grading; the
   prompt differs by "THE SITUATION" and nothing else; the packet by `sections.situation` and nothing
   else; the ledger is its own file, marked `arm: "B"`.
3. THE SWITCH IS OFF BY DEFAULT and costs nothing off.

Everything is injected or temporary: no model, no network, no repo data.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import cli, config as config_mod
from src.analyst import critic, ledger, packet as packet_mod
from src.analyst import situation_arm, situation_prompt, ufc_analyst as U, ufc_cli, ufc_ledger, ufc_packet
from src.situation import mlb as situation_mlb
from src.situation import record as rec
from src.situation import ufc as situation_ufc
from tests import analyst_fixtures as F
from tests import situation_fixtures as SF
from tests import ufc_analyst_fixtures as UF

KEY = {"ANTHROPIC_API_KEY": "sk-test"}

# Computed from `git show HEAD:...` of the commit before this work, then compared with the working
# tree (tests/ scratch run recorded in docs/SITUATION_LAYER.md). A change to arm A's prompt or packet
# changes these on purpose: update them in the same commit that says why.
# analyst_prompt_v2 (2026-10-03): v1 plus rule 13a, the required case against. v1 never ran, so no row carries its hash.
MLB_PROMPT_SHA256 = "f3d31c9ed1de56c8947fe970ebcfabf2a917498eea57b3acbb2a4052c18bdbe5"
UFC_PROMPT_SHA256 = "fb066b4cad001571d4224507581c092fd1286c4f388cacfc71708346f58d7db3"
MLB_PACKET_SHA256 = "d5f4be75e1dbcfdc486b0128109b2fbe18742debcaeb68c39924fc5ff8206110"
UFC_PACKET_SHA256 = "cf59dcd22ae9bd5f30763575b6acd51112718a170c21abc43ce58b914029a454"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redated(rows, to="2026"):
    """The situation fixtures' 2025 world moved to 2026, so it sits before the analyst fixture's
    game (NYY at TB, a Division Series game on 2026-10-03)."""
    out = []
    for r in rows:
        r = dict(r)
        r["date"] = r["date"].replace("2025", to)
        r["start_time_utc"] = r["start_time_utc"].replace("2025", to)
        out.append(r)
    return out


def mlb_situation(rows=None):
    game = F.payload()["advanced"]["game"]
    return situation_mlb.situation_for_game(game, rows or redated(SF.world()), strict=True)


# ---------------------------------------------------------------------------
# 1. arm A did not move
# ---------------------------------------------------------------------------

class ArmAIsByteForByteWhatItWas(unittest.TestCase):
    def test_the_mlb_prompt_is_the_one_that_shipped(self):
        self.assertEqual(sha(A.SYSTEM_PROMPT), MLB_PROMPT_SHA256)
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v2")

    def test_the_ufc_prompt_is_the_one_that_shipped(self):
        self.assertEqual(sha(U.UFC_SYSTEM_PROMPT), UFC_PROMPT_SHA256)
        self.assertEqual(U.UFC_PROMPT_VERSION, "analyst_ufc_prompt_v1")

    def test_the_mlb_packet_has_no_situation_and_the_same_hash(self):
        p = F.build()
        self.assertNotIn("situation", p["sections"])
        self.assertEqual(p["packet_version"], "analyst_packet_v1")
        self.assertEqual(packet_mod.packet_hash(p), MLB_PACKET_SHA256)

    def test_the_ufc_packet_has_no_situation_and_the_same_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p = UF.packet(UF.make_store(Path(d)))
        self.assertNotIn("situation", p["sections"])
        self.assertEqual(p["packet_version"], "analyst_ufc_packet_v1")
        self.assertEqual(packet_mod.packet_hash(p), UFC_PACKET_SHA256)

    def test_the_request_with_the_switch_off_carries_arm_as_prompt(self):
        body = A.build_request(F.build(), F.CFG)
        self.assertEqual(body["system"], A.SYSTEM_PROMPT)
        self.assertNotIn("situation", body["messages"][0]["content"])
        with tempfile.TemporaryDirectory() as d:
            ubody = U.build_request(UF.packet(UF.make_store(Path(d))), UF.CFG)
        self.assertEqual(ubody["system"], U.UFC_SYSTEM_PROMPT)

    def test_the_written_read_cannot_carry_the_situation_into_arm_a(self):
        base = F.payload()
        with_situation = F.payload()
        with_situation["read"] = {"headline": "x", "situation": {"sentences": ["TB played yesterday."]}}
        without = F.payload()
        without["read"] = {"headline": "x"}
        kw = dict(multibook_rows=F.multibook_rows(), cfg=F.CFG)
        a = packet_mod.build_packet(with_situation, built_at=F.BUILT_AT, **kw)
        b = packet_mod.build_packet(without, built_at=F.BUILT_AT, **kw)
        self.assertEqual(packet_mod.packet_hash(a), packet_mod.packet_hash(b))
        self.assertNotIn("situation", a["sections"]["read"]["values"])
        self.assertNotIn("situation", json.dumps(packet_mod.build_packet(base, built_at=F.BUILT_AT, **kw)))

    def test_the_ledger_row_arm_a_writes_has_no_arm_key_and_its_own_prompt_identity(self):
        with tempfile.TemporaryDirectory() as d:
            env = ArmFiles(Path(d))
            http = F.FakeHttp((200, F.api_response(F.good_output(F.build()))))
            cli.execute_run(F.DATE, env=KEY, http_post=http, loader=lambda date: [item()], now=lambda: F.NOW,
                            out=lambda s: None, cfg=F.CFG, **env.a)
            row = ledger.rows(env.a["store_path"])[0]
        self.assertNotIn("arm", row)
        self.assertNotIn("situation_version", row)
        self.assertEqual(row["prompt_version"], "analyst_prompt_v2")
        self.assertEqual(row["prompt_hash"], ledger.prompt_hash())
        self.assertEqual(row["packet_version"], "analyst_packet_v1")


# ---------------------------------------------------------------------------
# 2. arm B is the same analyst plus one section
# ---------------------------------------------------------------------------

class ThePrompts(unittest.TestCase):
    def test_arm_b_is_arm_a_with_the_situation_section_before_the_closing_line(self):
        for a, b, section in ((A.SYSTEM_PROMPT, A.SITUATION_SYSTEM_PROMPT, situation_prompt.MLB_SITUATION_SECTION),
                              (U.UFC_SYSTEM_PROMPT, U.UFC_SITUATION_SYSTEM_PROMPT, situation_prompt.UFC_SITUATION_SECTION)):
            closing = situation_prompt.CLOSING_LINE
            self.assertTrue(a.endswith(closing) and b.endswith(closing))
            self.assertEqual(b, a[: -len(closing)] + section + "\n\n" + closing)
            # every line of arm A's prompt is in arm B's, in order: nothing was reworded
            self.assertEqual(b.splitlines()[: len(a.splitlines()) - 1], a.splitlines()[:-1])

    def test_the_new_rules_take_the_next_numbers(self):
        mlb = [ln for ln in situation_prompt.MLB_SITUATION_SECTION.splitlines() if ln[:2].isdigit()]
        ufc = [ln for ln in situation_prompt.UFC_SITUATION_SECTION.splitlines() if ln[:2].isdigit()]
        self.assertEqual([int(ln.split(".")[0]) for ln in mlb], [17, 18, 19, 20])
        self.assertEqual([int(ln.split(".")[0]) for ln in ufc], [23, 24, 25, 26])
        # the last rule of each prompt it extends is 16 and 22
        self.assertIn("\n16. ", A.SYSTEM_PROMPT)
        self.assertIn("\n22. ", U.UFC_SYSTEM_PROMPT)

    def test_the_section_asks_for_what_the_plan_asks_for(self):
        for text in (situation_prompt.MLB_SITUATION_SECTION, situation_prompt.UFC_SITUATION_SECTION):
            low = text.lower()
            self.assertIn("sections.situation", text)
            self.assertIn("missing", low)                       # the holes are listed and respected
            self.assertIn("next to the statistics", low)        # weighed with them, not above
            self.assertIn("sample", low)                        # small samples are said to be small
            self.assertIn("cites its path", low)                # every claim still cites the packet
            self.assertIn("price may already include", low)     # the market may price the narrative
            self.assertIn("do no arithmetic", low)
        self.assertIn("postseason", situation_prompt.MLB_SITUATION_SECTION.lower())

    def test_the_section_uses_none_of_the_words_the_critic_bans(self):
        for text in (situation_prompt.MLB_SITUATION_SECTION, situation_prompt.UFC_SITUATION_SECTION):
            self.assertEqual(critic.banned_words(text), [])

    def test_the_prompt_identities_differ_and_are_versioned(self):
        self.assertNotEqual(ledger.prompt_hash(), ledger.prompt_hash(A.SITUATION_SYSTEM_PROMPT))
        self.assertNotEqual(U.prompt_hash(), U.prompt_hash(U.UFC_SITUATION_SYSTEM_PROMPT))
        self.assertEqual(A.SITUATION_PROMPT_VERSION, "analyst_prompt_v2_situation")
        self.assertEqual(U.UFC_SITUATION_PROMPT_VERSION, "analyst_ufc_prompt_v1_situation")

    def test_the_section_refuses_a_prompt_that_does_not_end_on_the_closing_line(self):
        with self.assertRaises(ValueError):
            situation_prompt.with_section("a prompt with another ending", "THE SITUATION")


class TheMlbPacket(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = mlb_situation()
        cls.a = F.build()
        cls.b = F.build(situation=cls.record)

    def test_it_adds_one_section_and_a_version_and_nothing_else(self):
        a, b = json.loads(json.dumps(self.a)), json.loads(json.dumps(self.b))
        self.assertEqual(b["packet_version"], "analyst_packet_v1_situation")
        self.assertIn("situation", b["sections"])
        a["packet_version"] = b["packet_version"] = "x"
        del b["sections"]["situation"]
        self.assertEqual(a, b)                          # markets, slots, missing, limits: all the same

    def test_the_sections_shape_is_the_packets(self):
        s = self.b["sections"]["situation"]
        self.assertEqual(set(s), {"as_of", "as_of_basis", "values"})
        self.assertEqual(s["as_of"], "2026-10-03")
        self.assertEqual(set(s["values"]), {"version", "factors", "missing", "coverage", "how_to_read"})

    def test_a_path_into_it_resolves_to_one_value(self):
        ok, value = packet_mod.resolve_path(
            self.b, "sections.situation.values.factors.rest_and_rhythm.previous_round.home.value")
        self.assertTrue(ok)
        self.assertIn(value, ("played", "bye"))
        ok, value = packet_mod.resolve_path(self.b, "sections.situation.values.factors.form.last_10.away.detail.wins")
        self.assertTrue(ok)
        self.assertIsInstance(value, int)

    def test_the_hash_is_deterministic_and_differs_from_arm_a(self):
        self.assertEqual(packet_mod.packet_hash(self.b), packet_mod.packet_hash(F.build(situation=mlb_situation())))
        self.assertNotEqual(packet_mod.packet_hash(self.a), packet_mod.packet_hash(self.b))

    def test_the_critic_accepts_every_number_and_name_in_every_situation_sentence(self):
        """A model that quotes a situation sentence is not struck: its numbers are packet numbers and
        its names are in the packet's text."""
        pool = critic.NumberPool.base(self.b)
        known = critic.KnownNames.build(self.b)
        checked = 0
        for item in self.record["factors"]:
            self.assertEqual(critic.unsupported_numbers(item["sentence"], pool), [], item["sentence"])
            self.assertEqual(critic.unsupported_names(item["sentence"], known), [], item["sentence"])
            checked += 1
        self.assertGreater(checked, 20)

    def test_a_claim_citing_a_situation_value_verifies_and_a_wrong_value_is_struck(self):
        packet = self.b
        value = packet["sections"]["situation"]["values"]["factors"]["rest_and_rhythm"]["days_since_last_game"]["home"]["value"]
        path = "sections.situation.values.factors.rest_and_rhythm.days_since_last_game.home.value"
        for claimed, expect_problem in ((value, False), (value + 3, True)):
            call = F.pass_call(packet, "moneyline")
            call["reasons"] = [{"claim": "The club has had time off.", "evidence": [{"path": path, "value": claimed}]}]
            problems = critic.check_call(packet, call, critic.NumberPool.base(packet).plus([call])).problems
            self.assertEqual(bool(problems), expect_problem, problems)

    def test_the_sentences_are_in_the_packet_text_the_critic_reads_names_from(self):
        text = packet_mod.canonical_bytes(self.b).decode("utf-8") if hasattr(packet_mod, "canonical_bytes") else ""
        for item in self.record["factors"][:5]:
            self.assertIn(item["sentence"].split(" ")[0], text)


class TheUfcPacket(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = UF.make_store(Path(cls._tmp.name))
        cls.record = situation_ufc.situation_for_bout(cls.store, UF.BOUT, strict=True)
        cls.a = UF.packet(cls.store)
        cls.b = UF.packet(cls.store, situation=cls.record)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_it_adds_one_section_and_a_version_and_nothing_else(self):
        a, b = json.loads(json.dumps(self.a)), json.loads(json.dumps(self.b))
        self.assertEqual(b["packet_version"], "analyst_ufc_packet_v1_situation")
        a["packet_version"] = b["packet_version"] = "x"
        self.assertEqual(set(b["sections"]) - set(a["sections"]), {"situation"})
        del b["sections"]["situation"]
        self.assertEqual(a, b)

    def test_fighter_paths_resolve_and_the_critic_accepts_the_sentences(self):
        ok, value = packet_mod.resolve_path(
            self.b, "sections.situation.values.factors.rest_and_rhythm.days_since_last_fight.a.value")
        self.assertTrue(ok)
        self.assertEqual(value, 119)
        pool, known = critic.NumberPool.base(self.b), U.known_names(self.b)
        for item in self.record["factors"]:
            self.assertEqual(critic.unsupported_numbers(item["sentence"], pool), [], item["sentence"])
            self.assertEqual(critic.unsupported_names(item["sentence"], known), [], item["sentence"])


# ---------------------------------------------------------------------------
# 3. the CLI: arms, files, the switch
# ---------------------------------------------------------------------------

def item():
    payload = F.payload()
    return {
        "payload": payload, "multibook_rows": F.multibook_rows(), "team_total_rows": F.team_total_rows(),
        "batter_prop_rows": F.batter_prop_rows(), "pitcher_prop_rows": F.pitcher_prop_rows(),
        "prop_board": F.prop_board(),
        "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
        "section_as_of": {"teams": "2026-10-02"},
    }


class ArmFiles:
    """Every file either arm may write, in a temporary directory."""

    def __init__(self, root: Path):
        self.root = root
        self.a = dict(store_path=str(root / "a.jsonl"), usage_path=str(root / "a_usage.jsonl"),
                      packet_dir=str(root / "a_packets"))
        self.b = dict(store=str(root / "b.jsonl"), usage=str(root / "b_usage.jsonl"),
                      packet_dir=str(root / "b_packets"))

    def listing(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())


class TheMlbRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.files = ArmFiles(Path(self._tmp.name))
        self.out = []
        self.record = mlb_situation()

    def http(self, usage=None):
        return F.FakeHttp((200, F.api_response(F.good_output(F.build()), usage)))

    def run_cli(self, *, cfg=None, http=None, items=None, **kw):
        kw.setdefault("situation_for", lambda it: self.record)
        return cli.execute_run(F.DATE, env=kw.pop("env", KEY), http_post=http or self.http(),
                               loader=lambda date: list(items or [item()]), now=kw.pop("now", lambda: F.NOW),
                               out=self.out.append, cfg=cfg or F.CFG, arm_b_paths=self.files.b,
                               **self.files.a, **kw)

    @property
    def text(self):
        return "\n".join(self.out)

    def a_rows(self):
        return ledger.rows(self.files.a["store_path"])

    def b_rows(self):
        return ledger.rows(self.files.b["store"])

    # -- the switch ----------------------------------------------------------------

    def test_the_switch_is_off_in_the_shipped_config_and_the_defaults(self):
        self.assertIs(config_mod.DEFAULTS["situation_arm"]["enabled"], False)
        shipped = json.loads((Path(config_mod.__file__).resolve().parents[2] / "config" / "analyst.json")
                             .read_text(encoding="utf-8"))
        self.assertIs(shipped["situation_arm"]["enabled"], False)
        self.assertIs(config_mod.load()["situation_arm"]["enabled"], False)

    def test_a_malformed_switch_is_an_error_not_a_default(self):
        for bad in ({}, {"enabled": "yes"}, None, 1):
            with self.assertRaises(config_mod.ConfigError):
                config_mod.validate(dict(config_mod.DEFAULTS, situation_arm=bad))

    def test_selected_arms(self):
        off, on = {"situation_arm": {"enabled": False}}, {"situation_arm": {"enabled": True}}
        self.assertEqual(situation_arm.selected_arms(None, off), ("A",))
        self.assertEqual(situation_arm.selected_arms(None, on), ("A", "B"))
        self.assertEqual(situation_arm.selected_arms("A", on), ("A",))
        self.assertEqual(situation_arm.selected_arms("B", off), ("B",))
        self.assertEqual(situation_arm.selected_arms("both", off), ("A", "B"))
        with self.assertRaises(ValueError):
            situation_arm.selected_arms("C", off)

    def test_with_the_switch_off_one_run_writes_arm_a_only_and_calls_the_model_once(self):
        http = self.http()
        self.assertEqual(self.run_cli(http=http), 0)
        self.assertEqual(http.calls, 1)
        self.assertEqual(len(self.a_rows()), 1)
        self.assertFalse(Path(self.files.b["store"]).exists())
        self.assertNotIn("[arm B]", self.text)
        self.assertEqual(http.requests[0]["body"]["system"], A.SYSTEM_PROMPT)

    def test_the_config_switch_runs_both_arms_without_the_flag(self):
        on = dict(F.CFG, situation_arm={"enabled": True})
        http = self.http()
        self.assertEqual(self.run_cli(cfg=on, http=http), 0)
        self.assertEqual(http.calls, 2)
        self.assertEqual(len(self.a_rows()), 1)
        self.assertEqual(len(self.b_rows()), 1)

    def test_the_flag_overrides_the_switch_either_way(self):
        on = dict(F.CFG, situation_arm={"enabled": True})
        http = self.http()
        self.run_cli(cfg=on, http=http, arm="A")
        self.assertEqual((http.calls, Path(self.files.b["store"]).exists()), (1, False))
        http = self.http()
        self.run_cli(cfg=F.CFG, http=http, arm="B")
        self.assertEqual(http.calls, 1)
        self.assertEqual(http.requests[0]["body"]["system"], A.SITUATION_SYSTEM_PROMPT)

    def test_an_unknown_arm_is_an_error_before_anything_is_built(self):
        self.assertEqual(self.run_cli(arm="C"), cli.EXIT_ERROR)
        self.assertEqual(self.files.listing(), [])

    # -- arm B's request, rows and files -------------------------------------------

    def test_the_two_arms_send_the_two_prompts_and_only_b_sends_the_situation(self):
        http = self.http()
        self.run_cli(http=http, arm="both")
        a, b = (r["body"] for r in http.requests)
        self.assertEqual(a["system"], A.SYSTEM_PROMPT)
        self.assertEqual(b["system"], A.SITUATION_SYSTEM_PROMPT)
        self.assertNotIn('"situation"', a["messages"][0]["content"])
        self.assertIn('"situation"', b["messages"][0]["content"])
        self.assertEqual(a["model"], b["model"])
        self.assertEqual(a["output_config"], b["output_config"])     # same schema, same effort

    def test_each_arm_writes_its_own_ledger_packets_and_cost_log(self):
        self.run_cli(arm="both")
        listing = self.files.listing()
        for name in ("a.jsonl", "a_usage.jsonl", "b.jsonl", "b_usage.jsonl"):
            self.assertIn(name, listing)
        self.assertTrue(any(p.startswith("a_packets") for p in listing))
        self.assertTrue(any(p.startswith("b_packets") for p in listing))
        a, b = self.a_rows()[0], self.b_rows()[0]
        self.assertNotIn("arm", a)
        self.assertEqual((b["arm"], b["situation_version"]), ("B", "situation_v1"))
        self.assertEqual((a["prompt_version"], b["prompt_version"]),
                         ("analyst_prompt_v2", "analyst_prompt_v2_situation"))
        self.assertEqual((a["prompt_hash"], b["prompt_hash"]),
                         (ledger.prompt_hash(), ledger.prompt_hash(A.SITUATION_SYSTEM_PROMPT)))
        self.assertEqual((a["packet_version"], b["packet_version"]),
                         ("analyst_packet_v1", "analyst_packet_v1_situation"))
        self.assertNotEqual(a["packet_hash"], b["packet_hash"])
        self.assertEqual(a["game_id"], b["game_id"])

    def test_arm_bs_frozen_packet_holds_the_situation_and_verifies(self):
        self.run_cli(arm="both")
        row = self.b_rows()[0]
        frozen = ledger.read_packet(row)
        self.assertIn("situation", frozen["sections"])
        self.assertTrue(ledger.verify(self.files.b["store"])["ok"])
        self.assertTrue(ledger.verify(self.files.a["store_path"])["ok"])

    def test_arm_bs_cost_log_says_which_arm_it_is(self):
        from src.ledger.chain import HashChainLedger
        self.run_cli(arm="both")
        a = HashChainLedger(self.files.a["usage_path"]).read()[0]
        b = HashChainLedger(self.files.b["usage"]).read()[0]
        self.assertNotIn("arm", a)
        self.assertEqual(b["arm"], "B")

    def test_lines_for_arm_b_are_tagged_and_arm_as_are_not(self):
        self.run_cli(arm="both")
        published = [ln for ln in self.out if "PUBLISHED" in ln]
        self.assertEqual(len(published), 2)
        self.assertTrue(published[0].startswith("PUBLISHED "))
        self.assertTrue(published[1].startswith("[arm B] PUBLISHED "))
        self.assertIn("arm A: 1 published", self.text)
        self.assertIn("arm B: 1 published", self.text)

    def test_a_second_run_finds_both_arms_frozen_and_pays_for_nothing(self):
        self.run_cli(arm="both")
        http = self.http()
        self.out.clear()
        self.run_cli(http=http, arm="both")
        self.assertEqual(http.calls, 0)
        self.assertEqual(sum("already published" in ln for ln in self.out), 2)

    def test_both_arms_share_one_spend_meter(self):
        # one call's worst case is about $0.19 and A's real cost is $0.07, so a $0.23 cap lets A through
        # and stops B before it is made: the two arms draw on one meter, not one each
        tight = dict(F.CFG, spend_cap={"max_usd_per_run": 0.23, "max_tokens_per_run": 600000})
        http = self.http({"input_tokens": 10000, "output_tokens": 5000})
        code = self.run_cli(cfg=tight, http=http, arm="both")
        self.assertEqual(code, cli.EXIT_CAP)
        self.assertEqual(http.calls, 1)
        self.assertEqual(len(self.a_rows()), 1)
        self.assertFalse(Path(self.files.b["store"]).exists())

    def test_a_situation_that_cannot_be_built_skips_arm_b_and_never_arm_a(self):
        def broken(_item):
            raise RuntimeError("no results store")
        http = self.http()
        self.assertEqual(self.run_cli(http=http, arm="both", situation_for=broken), 0)
        self.assertEqual(http.calls, 1)
        self.assertEqual(len(self.a_rows()), 1)
        self.assertIn("[arm B] SKIP NYY-TB-2026-10-03-1: the situation could not be built (RuntimeError", self.text)

    def test_a_game_that_starts_between_the_arms_is_refused_by_b_and_the_pair_is_dropped(self):
        started = {"yes": False}
        original_out = self.out.append

        def out(line):
            original_out(line)
            if line.startswith("PUBLISHED "):
                started["yes"] = True

        from datetime import datetime, timezone
        after = datetime(2026, 10, 3, 23, 0, 0, tzinfo=timezone.utc)       # first pitch was 22:30Z
        self.out = type("O", (), {"append": staticmethod(out)})()
        code = cli.execute_run(F.DATE, env=KEY, http_post=self.http(), loader=lambda date: [item()],
                               now=lambda: after if started["yes"] else F.NOW, out=out, cfg=F.CFG,
                               arm="both", situation_for=lambda it: self.record, arm_b_paths=self.files.b,
                               **self.files.a)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.a_rows()), 1)
        self.assertFalse(Path(self.files.b["store"]).exists())

    def test_a_dry_run_builds_both_requests_and_writes_nothing(self):
        http = self.http()
        self.assertEqual(self.run_cli(env={}, http=http, arm="both", dry_run=True), 0)
        self.assertEqual((http.calls, self.files.listing()), (0, []))
        lines = [ln for ln in self.out if "DRY RUN" in ln]
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("[arm B] DRY RUN"))
        self.assertIn("situation:", self.text)

    def test_arm_bs_dry_run_request_is_larger_by_about_the_situation(self):
        self.run_cli(env={}, arm="both", dry_run=True)
        a, b = [int(ln.split("request ~")[1].split(" ")[0]) for ln in self.out if "DRY RUN" in ln]
        self.assertGreater(b, a)
        self.assertLess(b - a, 6000)         # a few thousand tokens, not a second packet

    def test_without_a_key_neither_arm_is_built_or_written(self):
        http = self.http()
        self.assertEqual(self.run_cli(env={}, http=http, arm="both"), cli.EXIT_BLOCKED)
        self.assertEqual((http.calls, self.files.listing()), (0, []))

    # -- grading and the record ----------------------------------------------------

    def test_grading_a_date_grades_both_arms_when_arm_bs_ledger_exists(self):
        self.run_cli(arm="both")
        rows = {"849835": {"game_pk": "849835", "date": F.DATE, "away_team": "NYY", "home_team": "TB",
                           "away_score": "3", "home_score": "5", "winner": "TB", "game_type": "D"}}
        out = []
        cli.execute_grade(F.DATE, results=lambda d: (rows, []), now=lambda: F.NOW, out=out.append,
                          store_path=self.files.a["store_path"], arm_b_store=self.files.b["store"])
        self.assertTrue(any(ln.startswith("analyst grade") and "[arm B]" in ln for ln in out), out)
        for rows_ in (self.a_rows(), self.b_rows()):
            self.assertTrue(any(r["kind"] == ledger.KIND_GRADED for r in rows_))

    def test_grading_leaves_arm_b_alone_when_it_never_ran(self):
        self.run_cli(arm="A")
        out = []
        cli.execute_grade(F.DATE, results=lambda d: ({}, []), now=lambda: F.NOW, out=out.append,
                          store_path=self.files.a["store_path"], arm_b_store=self.files.b["store"])
        self.assertFalse(any("[arm B]" in ln for ln in out))
        self.assertFalse(Path(self.files.b["store"]).exists())

    def test_the_record_prints_arm_bs_ledger_on_request(self):
        self.run_cli(arm="both")
        out = []
        cli.execute_record(out=out.append, store_path=self.files.b["store"], usage_path=self.files.b["usage"],
                           cfg=F.CFG, arm="B")
        self.assertTrue(any("ARM B" in ln for ln in out))
        self.assertTrue(any("ledger: OK" in ln for ln in out))


class TheUfcRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = UF.make_store(self.dir / "world")
        self.files = ArmFiles(self.dir / "out")
        self.out = []

    def http(self):
        return UF.FakeHttp((200, UF.api_response(UF.good_output(UF.packet(self.store)))))

    def run_cli(self, *, http=None, **kw):
        return ufc_cli.execute_run(
            UF.DATE, env=kw.pop("env", KEY), http_post=http or self.http(),
            loader=lambda date, event=None: [UF.item(self.store)], now=lambda: UF.NOW, out=self.out.append,
            cfg=kw.pop("cfg", UF.CFG), arm_b_paths=self.files.b, **self.files.a, **kw)

    def test_with_the_switch_off_only_arm_a_runs_and_nothing_of_arm_b_is_written(self):
        http = self.http()
        self.assertEqual(self.run_cli(http=http), 0)
        self.assertEqual(http.calls, 1)
        self.assertFalse(Path(self.files.b["store"]).exists())
        self.assertEqual(http.requests[0]["body"]["system"], U.UFC_SYSTEM_PROMPT)

    def test_both_arms_write_their_own_ledgers_with_the_real_builder(self):
        http = self.http()
        self.assertEqual(self.run_cli(http=http, arm="both"), 0)
        self.assertEqual(http.calls, 2)
        a, b = ufc_ledger.rows(self.files.a["store_path"])[0], ufc_ledger.rows(self.files.b["store"])[0]
        self.assertNotIn("arm", a)
        self.assertEqual((b["arm"], b["prompt_version"], b["packet_version"]),
                         ("B", "analyst_ufc_prompt_v1_situation", "analyst_ufc_packet_v1_situation"))
        self.assertEqual((a["prompt_version"], a["packet_version"]), ("analyst_ufc_prompt_v1", "analyst_ufc_packet_v1"))
        self.assertEqual(a["bout_id"], b["bout_id"])
        self.assertIn("situation", ufc_ledger.read_packet(b)["sections"])
        self.assertNotIn("situation", ufc_ledger.read_packet(a)["sections"])
        self.assertEqual(http.requests[1]["body"]["system"], U.UFC_SITUATION_SYSTEM_PROMPT)
        self.assertIn('"situation"', http.requests[1]["body"]["messages"][0]["content"])
        self.assertNotIn('"situation"', http.requests[0]["body"]["messages"][0]["content"])

    def test_the_config_switch_runs_both(self):
        http = self.http()
        self.run_cli(http=http, cfg=dict(UF.CFG, situation_arm={"enabled": True}))
        self.assertEqual(http.calls, 2)

    def test_a_situation_that_cannot_be_built_skips_arm_b_only(self):
        def broken(_item):
            raise LookupError("no such bout")
        http = self.http()
        self.assertEqual(self.run_cli(http=http, arm="both", situation_for=broken), 0)
        self.assertEqual(http.calls, 1)
        self.assertIn("[arm B] SKIP 9101: the situation could not be built (LookupError", "\n".join(self.out))

    def test_grading_both_arms(self):
        self.run_cli(arm="both")
        UF.finish_the_bout(self.store)
        out = []
        ufc_cli.execute_grade(UF.DATE, results=lambda d: self.store.bout_by_id(), now=lambda: UF.NOW,
                              out=out.append, store_path=self.files.a["store_path"],
                              arm_b_store=self.files.b["store"])
        self.assertTrue(any("[arm B]" in ln for ln in out), out)
        for path in (self.files.a["store_path"], self.files.b["store"]):
            self.assertTrue(any(r["kind"] == ufc_ledger.KIND_GRADED for r in ufc_ledger.rows(path)))

    def test_a_dry_run_names_both_arms(self):
        self.run_cli(env={}, arm="both", dry_run=True)
        text = "\n".join(self.out)
        self.assertEqual(sum("DRY RUN" in ln for ln in self.out), 2)
        self.assertIn("[arm B] DRY RUN", text)
        self.assertEqual(self.files.listing(), [])


class TheArmDefinitions(unittest.TestCase):
    def test_arm_bs_files_are_the_two_the_plan_names_and_arm_as_are_unchanged(self):
        self.assertEqual(situation_arm.MLB_B_STORE.replace("\\", "/"), "evidence/analyst_v1_situation.jsonl")
        self.assertEqual(situation_arm.UFC_B_STORE.replace("\\", "/"), "evidence/analyst_ufc_v1_situation.jsonl")
        self.assertEqual(situation_arm.mlb_arm("A").store.replace("\\", "/"), "evidence/analyst_v1.jsonl")
        self.assertEqual(situation_arm.ufc_arm("A").store.replace("\\", "/"), "evidence/analyst_ufc_v1.jsonl")

    def test_an_arm_names_its_log_lines_and_a_arm_does_not(self):
        self.assertEqual(situation_arm.mlb_arm("A").tag, "")
        self.assertEqual(situation_arm.ufc_arm("B").tag, "[arm B] ")

    def test_the_two_arms_never_share_a_file(self):
        for make in (situation_arm.mlb_arm, situation_arm.ufc_arm):
            a, b = make("A"), make("B")
            self.assertEqual(len({a.store, a.usage, a.packet_dir, b.store, b.usage, b.packet_dir}), 6)


if __name__ == "__main__":
    unittest.main()
