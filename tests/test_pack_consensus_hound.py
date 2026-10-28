"""Pack Consensus (docs/PREREG_PACK_HOUND.md): point in time, membership, lineage, agreement, the -200 cap,
the empty-pack wording and forward-only. Synthetic ledger rows; no store and no file is read."""

import json
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds import ai_defs, pack_run
from src.hounds.pack import ai_hounds, base, pack_consensus_hound as pc

CATS = {"professor_paws": "stats", "relief_retriever": "stats", "jetlag_jack": "history", "bargain_bloodhound": "math",
        "steamy_setter": "market", "contrary_corgi": "market", "totals_terrier": "stats", "coin_flip_collie": "random",
        "chalk_chihuahua": "simple", "pack_leader": "mixed", "learner": "learner", "ai_claude": "ai", "ai_other": "ai"}
AI = {"ai_claude": {"id": "ai_claude", "family": "claude"}, "ai_other": {"id": "ai_other", "family": "claude"}}
NOW = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)
START = NOW + timedelta(minutes=30)
DAY = "2026-11-20"


def history(hid, n=30, clv=2.0, segment="forward", graded="2026-11-19T10:00:00Z"):
    """n graded forward bets on n different earlier dates; clv varies a little so the interval is finite."""
    rows = []
    for i in range(n):
        day = (datetime(2026, 10, 1) + timedelta(days=i)).date().isoformat()
        rows.append({"kind": "hound_graded", "hound_id": hid, "segment": segment, "date": day,
                     "clv_pts": clv + (0.3 if i % 2 else -0.3), "graded_utc": graded})
    return rows


def ticket(hid, market="moneyline", side="home", written=None, event="E1", segment="forward", **extra):
    return dict({"kind": "hound_bet", "hound_id": hid, "event_id": event, "market": market, "side": side,
                 "segment": segment, "written_utc": written or "2026-11-20T19:10:00Z"}, **extra)


def board(home=-120, away=110, markets=("moneyline",)):
    sides = {"home": {"price_average": home, "price_best": home, "book": "x", "book_count": 5, "fair": 0.5},
             "away": {"price_average": away, "price_best": away, "book": "x", "book_count": 5, "fair": 0.5}}
    return {"markets": {m: {"line": None if m == "moneyline" else -1.5, "books": 5, "sides": sides} for m in markets}}


def ctx():
    return base.Context(sport="mlb", event_id="E1", date=DAY, start=START, lock=START - timedelta(minutes=60),
                        away_name="Away", home_name="Home", away="AAA", home="HHH")


def hound(rows, now=NOW):
    return pc.PackConsensusHound({"id": "pack_consensus", "sports": ["mlb"], "markets": ["moneyline", "spread", "total"]},
                                 now_fn=lambda: now, categories=CATS, ai_entries=AI, rows=rows)


def proven(*ids):
    rows = []
    for h in ids:
        rows += history(h)
    return rows


FOUR = ("professor_paws", "jetlag_jack", "bargain_bloodhound", "relief_retriever")


class Membership(unittest.TestCase):
    def test_proven_hounds_qualify(self):
        m = hound(proven(*FOUR)).members(DAY, NOW)
        self.assertEqual(sorted(h for v in m.values() for h in v["hounds"]), sorted(FOUR))

    def test_under_n_is_excluded(self):
        rows = proven("professor_paws", "jetlag_jack") + history("bargain_bloodhound", n=pc.MIN_BETS - 1)
        self.assertNotIn("bargain_bloodhound", hound(rows).members(DAY, NOW))

    def test_random_baseline_and_ensembles_are_excluded(self):
        rows = proven("coin_flip_collie", "chalk_chihuahua", "pack_leader", "pack_consensus", "professor_paws")
        cats = dict(CATS, pack_consensus="mixed")
        h = pc.PackConsensusHound({}, now_fn=lambda: NOW, categories=cats, ai_entries=AI, rows=rows)
        self.assertEqual([x for v in h.members(DAY, NOW).values() for x in v["hounds"]], ["professor_paws"])

    def test_mean_above_zero_with_lower_bound_above_zero(self):
        self.assertEqual(hound(history("professor_paws", clv=0.1)).members(DAY, NOW), {})   # lower bound below zero
        self.assertEqual(hound(history("professor_paws", clv=-1.0)).members(DAY, NOW), {})

    def test_replay_rows_and_future_grades_are_ignored(self):
        self.assertEqual(hound(history("professor_paws", segment="replay")).members(DAY, NOW), {})
        late = history("professor_paws", graded="2026-11-20T21:00:00Z")      # graded after the decision instant
        self.assertEqual(hound(late).members(DAY, NOW), {})

    def test_same_day_bets_are_not_history(self):
        rows = history("professor_paws", n=33)
        for r in rows[-3:]:
            r["date"] = DAY
        self.assertEqual(hound(rows).members(DAY, NOW)["run_model"]["n"], 30)

    def test_lineage_families_count_once(self):
        m = hound(proven("steamy_setter", "contrary_corgi", "professor_paws", "totals_terrier",
                         "ai_claude", "ai_other")).members(DAY, NOW)
        self.assertEqual(sorted(m), ["ai:claude", "line_movement", "run_model"])

    def test_learner_is_allowed(self):
        self.assertIn("learner", hound(proven("learner")).members(DAY, NOW))


class Empty(unittest.TestCase):
    def test_empty_pack_says_so_and_bets_nothing(self):
        h = hound(proven("professor_paws", "jetlag_jack") + [ticket("professor_paws"), ticket("jetlag_jack")])
        self.assertEqual(h.pick(board(), ctx()), [])
        st = h.status(DAY)
        self.assertFalse(st["formed"])
        self.assertTrue(st["sentence"].startswith("Not enough proven hounds yet to form a pack."))
        self.assertNotIn("cleared the bar", st["sentence"].lower())

    def test_no_history_at_all(self):
        self.assertEqual(hound([]).pick(board(), ctx()), [])


class Bets(unittest.TestCase):
    def pick(self, tickets, bd=None, rows=None, now=NOW):
        return hound((rows if rows is not None else proven(*FOUR)) + tickets, now).pick(bd or board(), ctx())

    def test_two_families_agreeing_bet(self):
        sel = self.pick([ticket("professor_paws"), ticket("jetlag_jack")])
        self.assertEqual(len(sel), 1)
        self.assertEqual((sel[0].market, sel[0].side, sel[0].stake), ("moneyline", "home", 1.0))
        self.assertEqual(sel[0].row_extra["pack_voters"], ["jetlag_jack", "professor_paws"])
        self.assertIn("jetlag_jack", sel[0].reason)

    def test_one_vote_is_not_enough(self):
        self.assertEqual(self.pick([ticket("professor_paws")]), [])

    def test_a_ticket_recorded_after_the_decision_is_ignored(self):
        late = "2026-11-20T20:05:00Z"
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack", written=late)]), [])

    def test_a_ticket_written_at_or_after_the_start_is_ignored(self):
        after = START.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack", written=after)],
                                   now=START + timedelta(minutes=5)), [])

    def test_non_voters_do_not_vote(self):
        rows = proven(*FOUR) + history("chalk_chihuahua")
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("chalk_chihuahua"), ticket("coin_flip_collie")],
                                   rows=rows), [])

    def test_a_family_votes_once(self):
        rows = proven(*FOUR, "steamy_setter", "contrary_corgi")
        self.assertEqual(self.pick([ticket("steamy_setter"), ticket("contrary_corgi")], rows=rows), [])
        sel = self.pick([ticket("steamy_setter"), ticket("contrary_corgi"), ticket("jetlag_jack")], rows=rows)
        self.assertEqual(sel[0].score, 2.0)

    def test_a_split_family_casts_no_vote(self):
        rows = proven(*FOUR, "steamy_setter", "contrary_corgi")
        self.assertEqual(self.pick([ticket("steamy_setter"), ticket("contrary_corgi", side="away"),
                                    ticket("jetlag_jack")], rows=rows), [])

    def test_opposition_blocks_the_bet(self):
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack"),
                                    ticket("bargain_bloodhound", side="away")]), [])

    def test_other_club_in_another_market_blocks_the_bet(self):
        bd = board(markets=("moneyline", "spread"))
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack"),
                                    ticket("bargain_bloodhound", market="spread", side="away")], bd), [])

    def test_other_games_tickets_are_ignored(self):
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack", event="E2")]), [])

    def test_replay_tickets_are_ignored(self):
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack", segment="replay")]), [])

    def test_challenger_rows_are_ignored(self):
        self.assertEqual(self.pick([ticket("professor_paws"), ticket("jetlag_jack", role="challenger")]), [])

    def test_more_votes_win_across_markets_and_ties_go_to_moneyline(self):
        bd = board(markets=("moneyline", "spread"))
        t = [ticket("professor_paws"), ticket("jetlag_jack"),
             ticket("professor_paws", market="spread"), ticket("jetlag_jack", market="spread"),
             ticket("bargain_bloodhound", market="spread")]
        self.assertEqual(self.pick(t, bd)[0].market, "spread")
        self.assertEqual(self.pick(t[:4], bd)[0].market, "moneyline")

    def test_the_minus_200_cap_holds_through_the_runner_choice(self):
        h = hound(proven(*FOUR) + [ticket("professor_paws"), ticket("jetlag_jack")])
        self.assertIsNotNone(pack_run.choose(h, board(home=-199), ctx()))
        self.assertIsNone(pack_run.choose(h, board(home=-200), ctx()))
        self.assertIsNone(pack_run.choose(h, board(home=-260), ctx()))


class ForwardOnlyAndWiring(unittest.TestCase):
    def test_a_replay_is_refused(self):
        h = hound(proven(*FOUR))
        self.assertTrue(h.forward_only)
        with self.assertRaises(ai_defs.ForwardOnlyError):
            pack_run.run(base.Stores(), [DAY], replay=True, now=NOW, path="unused", hounds=[h])

    def test_registered_in_config_and_not_built_as_a_model_hound(self):
        e = ai_defs.entry_for("pack_consensus")
        self.assertEqual((e["family"], e["providers"], e["max_per_day"], e["stake_units"], e["forward_only"]),
                         ("pack_consensus", [], 3, 1.0, True))
        self.assertIn("pack_consensus", ai_defs.ids())
        built = ai_hounds.build_hounds(mock.Mock())
        self.assertNotIn("pack_consensus", [x.id for x in built])

    def test_config_copy_rules(self):
        text = json.dumps(ai_defs.entry_for("pack_consensus")).lower().replace("dog_menu", "")
        for word in (" dog", "beta", "nothing cleared the bar", "profit"):
            self.assertNotIn(word, text)
        self.assertIn("not enough proven hounds yet to form a pack", text)

    def test_prereg_is_frozen_with_the_constants_the_code_uses(self):
        doc = (Path(__file__).resolve().parents[1] / "docs" / "PREREG_PACK_HOUND.md").read_text(encoding="utf-8")
        self.assertIn("FROZEN 2026-10-28", doc)
        self.assertIn(f"N = {pc.MIN_BETS}", doc)
        self.assertIn("proven hounds yet to form a pack", doc)


class RunnerReport(unittest.TestCase):
    def test_a_pass_reports_the_empty_pack_in_plain_words_and_writes_no_pack_bet(self):
        import os
        import tempfile
        from src.hounds import ai_runner
        from tests.test_learner_hound import LOCKED, basic_stores
        with tempfile.TemporaryDirectory() as d:
            empty = os.path.join(d, "house.jsonl")           # an injected, empty house ledger: no machine state read
            env = {"GEMATRIA_HOUND": "off", "LEARNER_HOUND": "off"}
            with mock.patch.dict(os.environ, env), mock.patch.object(pack_run, "ledger_path", return_value=empty):
                report = ai_runner.run_pass(now=LOCKED, router=mock.Mock(enabled_providers=lambda: []), stores=basic_stores(),
                                            ledger=os.path.join(d, "ai.jsonl"), decisions=os.path.join(d, "d.jsonl"),
                                            refresh_stats=lambda: None)
        self.assertFalse(report["pack_consensus"]["formed"])
        self.assertTrue(report["pack_consensus"]["sentence"].startswith("Not enough proven hounds yet to form a pack."))
        self.assertEqual(report["run"]["written"], 0)


if __name__ == "__main__":
    unittest.main()
