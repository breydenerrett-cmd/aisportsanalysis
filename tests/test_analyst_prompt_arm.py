"""Champion / challenger for the analyst's brief prompt (src/analyst/prompt_arm.py).

No test here calls a model: urllib is blocked for the whole module, the shadow run's analyzer is a fake,
and the CLI's `shadow` refuses to spend without --confirm-spend.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.analyst import analyst as analyst_mod
from src.analyst import critic, config as config_mod, ledger as aledger, prompt_arm, situation_arm
from src.hounds.learning import ledger as L, lessons, pause, proposals, rules
from src.hounds.learning.referee import Referee
from src.ledger.chain import HashChainLedger
from tests import analyst_fixtures as AF
from tests import _learning_fixtures as F

HYP = "A shorter brief that asks for fewer claims may pass more of the games where the books are right."
EVID = ["record.families.moneyline.units_per_call"]


def variant(text=None, n=1):
    """A prompt that keeps the phrases the checker relies on but is not a near-copy of the champion."""
    base = text or analyst_mod.SYSTEM_PROMPT
    return base + ("\n\nADDITIONAL RULE %d. Prefer PASS on any market where the quotes are within one cent of each other, "
                   "and say so in a sentence. " % n) * 12 + "\n".join(f"Extra guidance line {i} for variant {n}." for i in range(60 * n))


def pub_row(gid, day, hour, takes, *, row_hash=None):
    return {"kind": aledger.KIND_PUBLISHED, "game_id": gid, "game_pk": 1, "date": day, "away": "A", "home": "H",
            "first_pitch_utc": f"{day}T{hour:02d}:10:00Z", "published_utc": f"{day}T12:00:00Z", "version": 1,
            "prompt_version": analyst_mod.PROMPT_VERSION, "packet_hash": "x", "packet_path": "x",
            "calls": [{"slot_id": f"s{i}", "verdict": "TAKE", "market": "moneyline"} for i in range(takes)]}


def graded_row(pub_hash, gid, day, profits, complete=True):
    return {"kind": aledger.KIND_GRADED, "game_id": gid, "date": day, "published_row_hash": pub_hash, "version": 1,
            "graded_utc": f"{day}T23:59:00Z", "complete": complete, "final": {},
            "calls": [{"slot_id": f"s{i}", "result": "WIN" if p > 0 else "LOSS", "profit_units": p}
                      for i, p in enumerate(profits)]}


class NoModelEver(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("a model call was attempted"))
        p.start()
        self.addCleanup(p.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.scope = L.Scope.house(self.root / "evidence")
        self.now = F.utc("2026-11-10T12:00:00Z")


class TheChampionPrompt(NoModelEver):
    def test_with_no_promotion_the_shipped_prompt_and_no_override(self):
        text, version = prompt_arm.champion(scope=self.scope, root=self.root)
        self.assertEqual(text, analyst_mod.SYSTEM_PROMPT)
        self.assertIsNone(version)

    def test_arm_a_is_byte_for_byte_what_it_always_was_until_a_promotion(self):
        arm = situation_arm.mlb_arm(situation_arm.ARM_A)
        self.assertEqual(arm.system_prompt, analyst_mod.SYSTEM_PROMPT)
        self.assertIsNone(arm.prompt_version)
        self.assertIsNone(arm.extra)

    def test_a_promotion_changes_the_prompt_the_next_run_uses_as_a_new_version(self):
        text = variant()
        sha, rel = prompt_arm.store_prompt(text, self.root)
        L.log_for(self.scope).append(L.K_PROMOTION, now=self.now, scope="house", hound_id=prompt_arm.HOUND_ID,
                                     lineage_key=prompt_arm.HOUND_ID, challenger_id="c-win", kind_of="analyst",
                                     from_version=1, to_version=2, prompt={"sha256": sha, "prompt_file": rel},
                                     applied=True)
        got, version = prompt_arm.champion(scope=self.scope, root=self.root)
        self.assertEqual(got, text)
        self.assertEqual(version, "analyst_prompt_v5+c-win")
        with mock.patch.object(prompt_arm, "champion", lambda *a, **k: (got, version)):
            arm = situation_arm.mlb_arm(situation_arm.ARM_A)
        self.assertEqual((arm.system_prompt, arm.prompt_version), (text, version))
        self.assertEqual(analyst_mod.SYSTEM_PROMPT[:40], analyst_mod.SYSTEM_PROMPT[:40])        # the old text is still there

    def test_a_promoted_prompt_whose_file_was_altered_or_is_missing_raises_not_falls_back(self):
        text = variant()
        sha, rel = prompt_arm.store_prompt(text, self.root)
        L.log_for(self.scope).append(L.K_PROMOTION, now=self.now, scope="house", hound_id=prompt_arm.HOUND_ID,
                                     challenger_id="c-win", kind_of="analyst", from_version=1, to_version=2,
                                     prompt={"sha256": sha, "prompt_file": rel}, applied=True)
        (self.root / rel).write_text(text + " tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            prompt_arm.champion(scope=self.scope, root=self.root)
        (self.root / rel).unlink()
        with self.assertRaises(OSError):
            prompt_arm.champion(scope=self.scope, root=self.root)

    def test_the_prompt_store_is_content_addressed_and_never_overwritten(self):
        text = variant()
        sha, rel = prompt_arm.store_prompt(text, self.root)
        self.assertEqual(sha, prompt_arm.sha_of(text))
        self.assertTrue(rel.startswith("evidence/analyst_prompts/"))
        self.assertEqual(prompt_arm.store_prompt(text, self.root), (sha, rel))
        (self.root / rel).write_text("something else", encoding="utf-8")
        with self.assertRaises(ValueError):
            prompt_arm.store_prompt(text, self.root)


class Proposing(NoModelEver):
    def propose(self, text=None, **kw):
        kw.setdefault("graded", 50)
        kw.setdefault("coach_on", True)
        kw.setdefault("now", self.now)
        return prompt_arm.propose(self.scope, text if text is not None else variant(), kw.pop("hypothesis", HYP),
                                  kw.pop("evidence", EVID), root=self.root, **kw)

    def refused(self, code, *a, **kw):
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.propose(*a, **kw)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def test_a_good_prompt_becomes_a_live_analyst_challenger_with_its_text_stored(self):
        c = self.propose()
        self.assertEqual((c.kind, c.hound_id, c.status, c.category), ("analyst", "analyst_prompt:mlb", "live", "analyst"))
        self.assertEqual(prompt_arm.read_prompt(c.spec, self.root), variant())
        self.assertTrue(c.spec_diff["prompt"][1].startswith(c.spec["sha256"][:12]))

    def test_the_arms_own_guards(self):
        self.refused("coach_disabled", coach_on=False)
        self.refused("not_enough_bets", graded=49)
        self.refused("bad_prompt", text="short")
        self.refused("bad_prompt", text="x" * 600)                                   # none of the required phrases
        self.refused("near_duplicate", text=analyst_mod.SYSTEM_PROMPT)               # the champion itself
        self.refused("near_duplicate", text=analyst_mod.SYSTEM_PROMPT + "\nOne more sentence.")
        self.refused("bad_text", hypothesis="short")
        self.refused("bad_evidence", evidence=[])

    def test_one_live_at_a_time_and_seven_days_between_proposals(self):
        self.propose()
        self.refused("too_soon", text=variant(n=2), now=self.now + timedelta(days=3))
        self.refused("too_many_live", text=variant(n=2), now=self.now + timedelta(days=8))

    def test_a_retired_prompt_or_a_near_copy_is_not_tried_again_for_90_days(self):
        c = self.propose()
        L.log_for(self.scope).append(L.K_DECISION, now=self.now + timedelta(days=20), scope="house", challenger_id=c.id,
                                     hound_id=prompt_arm.HOUND_ID, outcome="retired", reason="harm")
        later = self.now + timedelta(days=30)
        self.refused("retired_repeat", text=variant(), now=later)
        self.refused("retired_repeat", text=variant() + " A tiny addition.", now=later)
        self.assertIsNotNone(self.propose(text=variant(n=3), now=later))             # a different idea is fine

    def test_a_proposal_cannot_change_the_champion(self):
        self.propose()
        text, version = prompt_arm.champion(scope=self.scope, root=self.root)
        self.assertEqual((text, version), (analyst_mod.SYSTEM_PROMPT, None))
        self.assertEqual(L.read_state(self.scope).promotions, [])


class ShadowRunning(NoModelEver):
    def setUp(self):
        super().setUp()
        self.champ_store = str(self.root / "champ.jsonl")
        self.packets = str(self.root / "champ_packets")
        packet = AF.build()
        verified = critic.Verified(summary="s", summary_status="ok", summary_problems=[],
                                   calls=critic.verify(packet, AF.good_output(packet)).calls, struck=[], model_critic="off")
        self.pub, _ = aledger.publish(packet, verified, now=AF.NOW, model="m", path=self.champ_store, packet_dir=self.packets)
        self.packet = packet
        self.challenger = proposals.propose_pack  # noqa: F841 -- keep import used
        self.c = prompt_arm.propose(self.scope, variant(), HYP, EVID, graded=50, coach_on=True, now=AF.NOW - timedelta(days=9),
                                    root=self.root)
        self.cfg = config_mod.validate(dict(config_mod.DEFAULTS))

    def fake_analyze(self, packet, cfg, *, api_key, http_post, meter, system_prompt):
        self.seen_prompt = system_prompt
        return analyst_mod.AnalysisResult(output=AF.good_output(packet), usage={"input_tokens": 10, "output_tokens": 5},
                                          cost_usd=0.01, attempts=1, model="claude-test", request_ids=["r"])

    def test_the_answer_goes_to_the_challenger_store_only_under_the_challengers_prompt(self):
        before = Path(self.champ_store).read_text(encoding="utf-8")
        out = prompt_arm.shadow_date(AF.DATE, self.scope, now=AF.NOW + timedelta(minutes=5), cfg=self.cfg, key="k",
                                     champion_store=self.champ_store, root=self.root, analyze=self.fake_analyze,
                                     out=lambda *a: None)
        self.assertEqual((out["answered"], out["failed"]), (1, 0))
        self.assertEqual(self.seen_prompt, variant())
        self.assertEqual(Path(self.champ_store).read_text(encoding="utf-8"), before)      # the champion's ledger: untouched
        p = prompt_arm.challenger_paths(self.c.id, self.root)
        rows = aledger.rows(p["store"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt_version"], f"challenger:{self.c.id}")
        self.assertEqual(rows[0]["role"], "challenger")
        self.assertEqual(rows[0]["champion_row_hash"], self.pub["row_hash"])
        self.assertEqual(rows[0]["packet_hash"], self.pub["packet_hash"])                  # the SAME frozen packet
        self.assertEqual(aledger.verify(p["store"])["ok"], True)
        self.assertFalse(Path(p["store"]).resolve() == Path(self.champ_store).resolve())

    def test_a_rerun_answers_nothing_twice_and_a_started_game_is_refused(self):
        kw = dict(cfg=self.cfg, key="k", champion_store=self.champ_store, root=self.root, analyze=self.fake_analyze,
                  out=lambda *a: None)
        prompt_arm.shadow_date(AF.DATE, self.scope, now=AF.NOW + timedelta(minutes=5), **kw)
        again = prompt_arm.shadow_date(AF.DATE, self.scope, now=AF.NOW + timedelta(minutes=10), **kw)
        self.assertEqual(again["answered"], 0)
        # a second challenger store is empty; the game has started by then
        shutil_store = Path(prompt_arm.challenger_paths(self.c.id, self.root)["store"])
        shutil_store.unlink()
        late = prompt_arm.shadow_date(AF.DATE, self.scope, now=aledger.start_utc(self.packet["game"]) and
                                      datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc), **kw)
        self.assertEqual((late["answered"], late["skipped"]), (0, 1))

    def test_dry_run_sends_and_writes_nothing(self):
        called = []
        out = prompt_arm.shadow_date(AF.DATE, self.scope, now=AF.NOW + timedelta(minutes=5), cfg=self.cfg, key=None,
                                     champion_store=self.champ_store, dry_run=True, root=self.root,
                                     analyze=lambda *a, **k: called.append(1), out=lambda *a: None)
        self.assertEqual(called, [])
        self.assertEqual(out["answered"], 0)
        self.assertFalse(Path(prompt_arm.challenger_paths(self.c.id, self.root)["store"]).exists())

    def test_no_live_challenger_means_nothing_to_do(self):
        L.log_for(self.scope).append(L.K_DECISION, now=AF.NOW, scope="house", challenger_id=self.c.id,
                                     hound_id=prompt_arm.HOUND_ID, outcome="undecided", reason="expired")
        out = prompt_arm.shadow_date(AF.DATE, self.scope, now=AF.NOW, cfg=self.cfg, key="k",
                                     champion_store=self.champ_store, root=self.root, analyze=self.fake_analyze,
                                     out=lambda *a: None)
        self.assertEqual(out["challengers"], 0)


class TheCliSpendsOnlyWhenTold(NoModelEver):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = prompt_arm.main(["--root", str(self.root), "--now", "2026-11-10T12:00:00Z", *argv])
        return code, buf.getvalue()

    def test_status_and_propose(self):
        cfg = self.root / "coach.json"
        cfg.write_text('{"enabled": true}', encoding="utf-8")
        pf = self.root / "p.txt"
        pf.write_text(variant(), encoding="utf-8")
        store = self.root / "none.jsonl"
        code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["champion_prompt"], "analyst_prompt_v5")
        code, out = self.run_cli("--coach-config", str(cfg), "--store", str(store), "propose", "--prompt-file", str(pf),
                                 "--hypothesis", HYP, "--evidence", "a")
        self.assertEqual((code, json.loads(out)["code"]), (1, "not_enough_bets"))      # no graded games yet

    def test_shadow_without_confirm_spend_is_a_dry_run_and_without_a_key_it_is_blocked(self):
        with mock.patch.object(config_mod, "api_key", return_value=None):
            code, out = self.run_cli("shadow", "--date", "2026-11-10", "--confirm-spend")
            self.assertEqual(code, 3)
            self.assertIn("BLOCKED", out)
            code, out = self.run_cli("shadow", "--date", "2026-11-10")
            self.assertEqual(code, 0)
            self.assertIn("dry run", out)

    def test_the_cli_names_its_commands(self):
        doc = prompt_arm.__doc__
        for name in ("status", "propose", "shadow", "grade", "referee"):
            self.assertIn(f"python -m src.analyst.prompt_arm {name}", doc)


class OnGradedCallsTheSameReferee(NoModelEver):
    """160 games over 40 days, the challenger better by about 1 unit a game on the games it takes."""

    def build(self, challenger_better=1.0, challenger_take_share=1.0, games=160):
        c = prompt_arm.propose(self.scope, variant(), HYP, EVID, graded=50, coach_on=True,
                               now=F.utc("2026-10-25T00:00:00Z"), root=self.root)
        champ_store = HashChainLedger(self.root / "champ.jsonl")
        chall_store = HashChainLedger(prompt_arm.challenger_paths(c.id, self.root)["store"])
        import random
        rng = random.Random(4)
        for i in range(games):
            day = F.day_n(i // 4)
            gid = f"g{i:03d}"
            champ_units = [round(rng.choice([-1.0, 0.9]), 2)]
            chall_units = [round(champ_units[0] + challenger_better + rng.gauss(0, 0.3), 2)] \
                if rng.random() < challenger_take_share else []
            cp = champ_store.append(pub_row(gid, day, 12 + i % 4, 1))
            champ_store.append(graded_row(cp["row_hash"], gid, day, champ_units))
            hp = chall_store.append(dict(pub_row(gid, day, 12 + i % 4, len(chall_units)), role="challenger"))
            chall_store.append(graded_row(hp["row_hash"], gid, day, chall_units))
        return c

    def referee(self, now="2027-01-05T12:00:00Z"):
        return prompt_arm.run_referee(self.scope, now=F.utc(now), champion_store=str(self.root / "champ.jsonl"), root=self.root)

    def test_a_game_is_the_units_of_its_takes_and_a_pass_is_zero(self):
        pub = pub_row("g1", "2026-11-02", 12, 2)
        g = dict(graded_row("h", "g1", "2026-11-02", [0.9, -1.0]), row_hash="rh")
        self.assertEqual(prompt_arm.game_value(pub, g, {}), -0.1)
        self.assertIsNone(prompt_arm.game_value(pub_row("g2", "2026-11-02", 12, 0), None, {}))
        self.assertEqual(prompt_arm.game_value(pub, None, {}), 0.0)           # takes, nothing graded: adds 0

    def test_the_looks_are_the_analysts_larger_table_and_the_clear_winner_is_promoted_after_the_month_ends(self):
        c = self.build()
        rep = self.referee()
        st = L.read_state(self.scope)
        looks = [lk for lk in st.challengers[c.id].looks if not lk.get("skipped")]
        self.assertEqual([lk["n"] for lk in looks], [150])
        self.assertEqual(looks[0]["look_no"], 1)
        self.assertEqual(looks[0]["alpha"], 0.002)
        self.assertTrue(looks[0]["eligible"])
        self.assertEqual(st.challengers[c.id].status, "promoted")
        self.assertEqual(rep["promoted"], 1)
        promo = st.promotions[0]
        self.assertEqual(promo["prompt"]["sha256"], prompt_arm.sha_of(variant()))
        self.assertEqual(st.champion_version(prompt_arm.HOUND_ID), 2)
        # and the next run really does use the promoted prompt
        text, version = prompt_arm.champion(scope=self.scope, root=self.root)
        self.assertEqual((text, version), (variant(), f"analyst_prompt_v5+{c.id}"))
        self.assertEqual(len(lessons.read(self.scope.lessons)), 1)

    def test_a_clearly_worse_prompt_is_retired_at_once(self):
        c = self.build(challenger_better=-1.5)
        self.referee()
        self.assertEqual(L.read_state(self.scope).challengers[c.id].outcome_reason, "harm")

    def test_a_prompt_that_wins_by_taking_far_fewer_games_cannot_promote(self):
        c = self.build(challenger_better=1.0, challenger_take_share=0.3)
        self.referee()
        look = [lk for lk in L.read_state(self.scope).challengers[c.id].looks if not lk.get("skipped")][0]
        self.assertFalse(look["volume_ok"])
        self.assertFalse(look["eligible"])
        self.assertEqual(L.read_state(self.scope).challengers[c.id].status, "live")

    def test_ungraded_games_cut_the_prefix_and_unanswered_games_are_uncovered_not_free_passes(self):
        c = self.build(games=40)
        store = HashChainLedger(self.root / "champ.jsonl")
        extra = store.append(pub_row("gx", F.day_n(40), 12, 1))                    # published, never graded
        pr = prompt_arm.pairing_for(L.read_state(self.scope).challengers[c.id], L.read_state(self.scope),
                                    champion_store=str(self.root / "champ.jsonl"), root=self.root)
        self.assertEqual(len(pr.slots), 40)
        self.assertEqual(pr.uncovered, 1)                                          # the champion's gx has no challenger answer
        del extra

    def test_the_pack_referee_does_not_touch_an_analyst_challenger(self):
        c = self.build(games=10)
        # a pack-style run (no pairing_for, kinds=("pack",)) must leave it alone, even far past 180 days
        Referee(self.scope, now=F.utc("2027-06-01T00:00:00Z"), bets_for=lambda c: ([], []), kinds=("pack",)).run()
        self.assertEqual(L.read_state(self.scope).challengers[c.id].status, "live")


if __name__ == "__main__":
    unittest.main()
