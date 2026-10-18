"""The system scorecard, the auto-pause, and the lineage that keeps old versions' records.

(a) promotion hit rate, (b) champions against the random controls on the same games, (c) activity and
the false-discovery budget; the pause rule's two triggers and their edges; the pause really closes the
door and only a resume reopens it; old versions keep their own record when a pack hound is promoted.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.hounds import ledgers
from src.hounds.learning import ledger as L, lineage, pause, rules, scorecard as sc
from tests import _learning_fixtures as F

NOW = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()

INFO = {
    "pointer": {"kind": "house", "category": "stats", "status": "running"},
    "professor_paws": {"kind": "house", "category": "stats", "status": "running"},
    "u-abc": {"kind": "user", "category": "mixed", "status": "running"},
    "beagle": {"kind": "baseline", "category": "baseline", "status": "running"},
    "lunar_lab": {"kind": "house", "category": "esoteric", "status": "running"},
    "old_dog": {"kind": "house", "category": "stats", "status": "retired"},
    "professor_paws@v1": {"kind": "house", "category": "stats", "status": "retired"},
    "coin_flip_collie": {"kind": "house", "category": "random", "status": "running"},
    "dartboard_dalmatian": {"kind": "house", "category": "random", "status": "running"},
}


def bets(hid, events, value, day):
    return [(hid, e, "h2h", day, value) for e in events]


class VersusRandom(unittest.TestCase):
    def test_only_the_same_games_are_compared_and_who_counts_as_a_champion(self):
        day = "2026-12-10"
        games = [f"g{i}" for i in range(60)]
        clv = []
        clv += bets("professor_paws", games, 1.0, day)                  # champions on 60 games
        clv += bets("u-abc", games[:30], 3.0, day)                        # a user champion on 30 of them
        clv += bets("coin_flip_collie", games[:40], -2.0, day)            # a control on 40 (30 shared)
        clv += bets("dartboard_dalmatian", games[20:60], -2.0, day)       # the other on 40 (40 shared by pw)
        clv += bets("coin_flip_collie", [f"x{i}" for i in range(80)], -9.0, day)   # games no champion bet
        clv += bets("beagle", games, 50.0, day)                           # a baseline: not a champion
        clv += bets("lunar_lab", games, 50.0, day)                        # for-fun: not a champion
        clv += bets("old_dog", games, 50.0, day)                          # retired: not a champion
        clv += bets("professor_paws@v1", games, 50.0, day)                # an archived version: not either
        out = sc.vs_random(clv, INFO, as_of=TODAY, days=30)
        self.assertEqual(out["games"], 60)                                 # champion AND control on it
        self.assertEqual(out["champion_bets"], 90)                         # 60 + 30
        self.assertEqual(out["control_bets"], 80)                          # 40 + 40; the x* games are not shared
        self.assertAlmostEqual(out["champion_mean"], (60 * 1.0 + 30 * 3.0) / 90, places=3)
        self.assertEqual(out["control_mean"], -2.0)
        self.assertAlmostEqual(out["difference"], out["champion_mean"] + 2.0, places=3)
        self.assertTrue(out["enough"])

    def test_null_below_fifty_bets_on_either_side(self):
        day = "2026-12-10"
        games = [f"g{i}" for i in range(49)]
        clv = bets("professor_paws", games, 1.0, day) + bets("coin_flip_collie", games, -1.0, day)
        out = sc.vs_random(clv, INFO, as_of=TODAY, days=30)
        self.assertFalse(out["enough"])
        self.assertIsNone(out["difference"])
        more = clv + bets("professor_paws", ["g0"], 1.0, day) * 2 + bets("coin_flip_collie", ["g0"], -1.0, day) * 2
        self.assertTrue(sc.vs_random(more, INFO, as_of=TODAY, days=30)["enough"])

    def test_the_30_and_90_day_windows_cut_by_date(self):
        games = [f"g{i}" for i in range(60)]
        old = bets("professor_paws", games, 5.0, "2026-10-15") + bets("coin_flip_collie", games, -5.0, "2026-10-15")
        new = bets("professor_paws", games, 1.0, "2026-12-15") + bets("coin_flip_collie", games, 0.0, "2026-12-15")
        w30 = sc.vs_random(old + new, INFO, as_of=TODAY, days=30)
        w90 = sc.vs_random(old + new, INFO, as_of=TODAY, days=90)
        self.assertEqual(w30["difference"], 1.0)
        self.assertEqual(w90["champion_bets"], 120)
        self.assertAlmostEqual(w90["champion_mean"], 3.0)

    def test_the_window_is_inclusive_of_today_and_not_of_the_day_before_it_starts(self):
        games = [f"g{i}" for i in range(60)]
        edge_in = (TODAY - timedelta(days=29)).isoformat()
        edge_out = (TODAY - timedelta(days=30)).isoformat()
        clv = bets("professor_paws", games, 1.0, edge_in) + bets("coin_flip_collie", games, 0.0, edge_in)
        clv += bets("professor_paws", games, 9.0, edge_out) + bets("coin_flip_collie", games, 9.0, edge_out)
        self.assertEqual(sc.vs_random(clv, INFO, as_of=TODAY, days=30)["champion_bets"], 60)


class HitRate(unittest.TestCase):
    def state_with_promotions(self, n, replaced=1.0):
        st = L.State()
        for i in range(n):
            st.promotions.append({"challenger_id": f"c-{i}", "hound_id": f"h{i}", "to_version": 2, "utc": "2026-11-01T00:00:00Z",
                                  "replaced_mean": replaced, "applied": True})
        return st

    def test_null_until_a_promotion_has_matured(self):
        st = self.state_with_promotions(3)
        out = sc.hit_rate(st, lambda p: (2.0, 99))              # 99 measurable bets: not mature
        self.assertEqual((out["promotions"], out["matured"], out["rate"]), (3, 0, None))
        self.assertIsNone(sc.hit_rate(L.State(), lambda p: None)["rate"])

    def test_a_hit_is_at_or_above_the_replaced_champion(self):
        st = self.state_with_promotions(4)
        means = {"c-0": 1.5, "c-1": 1.0, "c-2": 0.99, "c-3": -3.0}
        out = sc.hit_rate(st, lambda p: (means[p["challenger_id"]], 100))
        self.assertEqual((out["matured"], out["hits"], out["rate"]), (4, 2, 0.5))
        self.assertEqual([d["hit"] for d in out["details"]], [True, True, False, False])

    def test_an_unapplied_promotion_and_a_missing_baseline_do_not_mature(self):
        st = self.state_with_promotions(2)
        st.promotions[0]["applied"] = False
        st.promotions[1]["replaced_mean"] = None
        out = sc.hit_rate(st, lambda p: (5.0, 500))
        self.assertEqual(out["matured"], 0)


class ActivityAndBudget(unittest.TestCase):
    def test_counts_and_the_expected_false_promotion_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = L.Scope.house(Path(tmp))
            for i in range(3):
                F.propose_raw(scope, cid=f"c-{i}", hound_id=f"h{i}")
            log = L.log_for(scope)
            log.append(L.K_DECISION, now=NOW, scope="house", challenger_id="c-0", hound_id="h0",
                       outcome="promoted", reason="boundary_and_bh", bh={"p_adj": 0.02})
            log.append(L.K_PROMOTION, now=NOW, scope="house", hound_id="h0", challenger_id="c-0", from_version=1,
                       to_version=2, params={}, applied=True)
            log.append(L.K_DECISION, now=NOW, scope="house", challenger_id="c-1", hound_id="h1",
                       outcome="retired", reason="harm")
            log.append(L.K_REFUSED, now=NOW, scope="house", hound_id="h2", lineage_key="h2", code="near_duplicate",
                       message="m")
            act = sc.activity(L.read_state(scope), now=NOW)
        self.assertEqual((act["proposals"], act["promotions"], act["retirements"], act["refusals"], act["live"]),
                         (3, 1, 1, 1, 1))
        fd = act["false_discovery_budget"]
        self.assertEqual((fd["q"], fd["monthly_cap"], fd["promotions_this_month"]), (0.10, 3, 1))
        self.assertAlmostEqual(fd["expected_false_promotions_bound"], 0.02)


class AutoPause(unittest.TestCase):
    def hit(self, matured, rate):
        return {"matured": matured, "rate": rate}

    def snaps(self, days, diff, skip=()):
        st = L.State()
        for i in range(days):
            d = (TODAY - timedelta(days=i + 1)).isoformat()
            if d in skip:
                continue
            st.scorecards.append({"date": d, "payload": {"vs_random": {"windows": {"30": {"difference": diff}}}}})
        return st

    def test_hit_rate_below_the_floor_once_ten_have_matured_pauses(self):
        st = L.State()
        self.assertIn("0.30", sc.evaluate_pause(st, self.hit(10, 0.30), TODAY, None))
        self.assertIsNone(sc.evaluate_pause(st, self.hit(9, 0.0), TODAY, None))      # not enough matured
        self.assertIsNone(sc.evaluate_pause(st, self.hit(10, 0.40), TODAY, None))    # at the floor is fine
        self.assertIsNone(sc.evaluate_pause(st, self.hit(12, None), TODAY, None))
        self.assertIsNotNone(sc.evaluate_pause(st, self.hit(30, 0.399), TODAY, None))

    def test_trailing_the_controls_for_sixty_days_pauses(self):
        st = self.snaps(59, -0.5)                         # 59 past days + today = 60
        self.assertEqual(sc.trailing_streak(st, TODAY, -0.1), 60)
        self.assertIn("60", sc.evaluate_pause(st, self.hit(0, None), TODAY, -0.1))

    def test_fifty_nine_days_is_not_enough(self):
        st = self.snaps(58, -0.5)
        self.assertEqual(sc.trailing_streak(st, TODAY, -0.1), 59)
        self.assertIsNone(sc.evaluate_pause(st, self.hit(0, None), TODAY, -0.1))

    def test_a_missing_day_or_a_null_comparison_or_one_good_day_ends_the_streak(self):
        gap = (TODAY - timedelta(days=10)).isoformat()
        st = self.snaps(70, -0.5, skip={gap})
        self.assertEqual(sc.trailing_streak(st, TODAY, -0.1), 10)                     # today + 9 days, then the gap
        self.assertIsNone(sc.evaluate_pause(st, self.hit(0, None), TODAY, -0.1))
        self.assertEqual(sc.trailing_streak(self.snaps(70, -0.5), TODAY, None), 0)    # today is null
        self.assertEqual(sc.trailing_streak(self.snaps(70, None), TODAY, -0.1), 1)
        self.assertEqual(sc.trailing_streak(self.snaps(70, 0.0), TODAY, -0.1), 1)     # zero is not trailing

    def test_the_pause_closes_the_door_and_only_resume_opens_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = L.Scope.house(Path(tmp))
            cfg = Path(tmp) / "hounds_coach.json"
            cfg.write_text(json.dumps({"enabled": True}), encoding="utf-8")
            self.assertFalse(pause.is_paused(scope))
            out = pause.pause(scope, "trailing", now=NOW, config_file=cfg)
            self.assertTrue(out["paused"])
            self.assertTrue(pause.is_paused(scope))
            data = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertIs(data["enabled"], False)                                     # the kill switch flipped itself
            self.assertEqual(data["paused_by"], "learning_loop")
            self.assertEqual(data["reason"], "trailing")
            self.assertTrue(pause.pause(scope, "again", now=NOW, config_file=cfg)["already"])
            self.assertEqual(len([e for e in L.log_for(scope).read() if e["kind"] == L.K_PAUSE]), 1)
            pause.resume(scope, "owner reviewed", now=NOW + timedelta(days=1), config_file=cfg)
            self.assertFalse(pause.is_paused(scope))
            self.assertIs(json.loads(cfg.read_text(encoding="utf-8"))["enabled"], True)

    def test_a_user_scope_pause_writes_a_flag_beside_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = L.Scope.user(Path(tmp))
            pause.pause(scope, "hit rate", now=NOW)
            flag = json.loads((Path(tmp) / L.PAUSE_FILE_USER).read_text(encoding="utf-8"))
            self.assertEqual((flag["paused"], flag["reason"]), (True, "hit rate"))
            self.assertTrue(pause.file_paused(scope.pause_file))
            pause.resume(scope, "ok", now=NOW + timedelta(hours=1))
            self.assertFalse(pause.file_paused(scope.pause_file))

    def test_store_pauses_on_the_day_the_rule_trips_and_only_once_per_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = L.Scope.user(Path(tmp))
            log = L.log_for(scope)
            for i in range(59, 0, -1):
                d = (TODAY - timedelta(days=i)).isoformat()
                log.append(L.K_SCORECARD, now=NOW - timedelta(days=i), scope="user", date=d,
                           payload={"vs_random": {"windows": {"30": {"difference": -0.4}}}})
            payload = {"date": TODAY.isoformat(), "promotion_hit_rate": {"matured": 0, "rate": None},
                       "vs_random": {"windows": {"30": {"difference": -0.4}}}}
            out = sc.store(scope, payload, now=NOW)
            self.assertTrue(out["stored"])
            self.assertIn("60", out["paused"])
            self.assertTrue(pause.is_paused(scope))
            self.assertFalse(sc.store(scope, payload, now=NOW + timedelta(hours=1))["stored"])


class WholeCard(unittest.TestCase):
    def test_compute_stamps_the_chain_status_and_the_basis(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = L.Scope.house(Path(tmp))
            card = sc.compute(scope, now=NOW, clv_bets=[], hound_info=INFO, matured_fn=lambda p: None)
        self.assertEqual(card["date"], "2026-12-20")
        self.assertIsNone(card["promotion_hit_rate"]["rate"])
        self.assertEqual(set(card["vs_random"]["windows"]), {"30", "90"})
        self.assertEqual(card["vs_random"]["controls"], ["coin_flip_collie", "dartboard_dalmatian"])
        self.assertTrue(card["chain"]["ok"])
        self.assertTrue(card["paper_only"])
        self.assertEqual(card["vs_random"]["champions_counted"], 3)       # pointer, professor_paws, u-abc

    def test_merge_sums_counts_and_uses_the_freshest_chance_line(self):
        def card(scope, d, matured, hits, proposals, diff):
            return {"scope": scope, "date": d,
                    "promotion_hit_rate": {"promotions": matured, "matured": matured, "hits": hits},
                    "activity": {"proposals": proposals, "refusals": 1, "held_rounds": 0, "promotions": matured,
                                 "retirements": 0, "undecided": 0, "undos": 0, "live": 1,
                                 "false_discovery_budget": {"promotions_this_month": 1, "expected_false_promotions_bound": 0.1}},
                    "vs_random": {"windows": {"30": {"difference": diff}}},
                    "pause": {"paused": scope == "user", "reason": "r", "since": "s"}}
        merged = sc.merge({"house": card("house", "2026-12-19", 4, 3, 5, 0.1), "user": card("user", "2026-12-20", 6, 1, 7, 0.2)})
        self.assertEqual(merged["promotion_hit_rate"]["matured"], 10)
        self.assertEqual(merged["promotion_hit_rate"]["rate"], 0.4)
        self.assertEqual(merged["activity"]["proposals"], 12)
        self.assertEqual(merged["vs_random"]["windows"]["30"]["difference"], 0.2)
        self.assertTrue(merged["paused"])
        self.assertEqual(merged["pause_reasons"][0]["scope"], "user")
        self.assertEqual(sc.merge({"house": None}), {})


class OldVersionsKeepTheirRecords(unittest.TestCase):
    def setUp(self):
        self.defs = {"professor_paws": {"id": "professor_paws", "name": "Professor Paws", "tagline": "t", "kind": "house",
                                        "category": "stats", "style": "s", "sports": ["mlb"], "markets": ["moneyline"],
                                        "rule_text": "MLB moneyline. Shrink its home win probability 50% toward the "
                                                     "de-vigged consensus. Bet the side whose shrunk probability beats "
                                                     "the consensus by 2.0 points or more.",
                                        "system_id": None, "card": False, "retired": None, "verdict_sentence": None,
                                        "source": "pack_cfg"}}
        v1 = [F.bet("professor_paws", f"e{i}", F.day_n(i), 0, -1.0) for i in range(5)]
        v2 = [F.bet("professor_paws", f"f{i}", F.day_n(10 + i), 0, 0.5, version=2) for i in range(3)]
        self.bets = {"professor_paws": v1 + v2}
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        scope = L.Scope.house(Path(self._tmp.name))
        L.log_for(scope).append(L.K_PROMOTION, now=NOW, scope="house", hound_id="professor_paws", challenger_id="c-1",
                                from_version=1, to_version=2, params={"GAP": 0.03, "SHRINK": 0.5}, applied=True,
                                effective_utc="2026-11-20T00:00:00Z")
        self.events = scope.events

    def test_the_old_version_is_its_own_retired_entry_with_its_own_bets(self):
        made = lineage.split_versions(self.defs, self.bets, [self.events])
        self.assertEqual(made, ["professor_paws@v1"])
        self.assertEqual(len(self.bets["professor_paws"]), 3)                  # the new version: its own record
        self.assertEqual(len(self.bets["professor_paws@v1"]), 5)               # the old one keeps its 5
        old = self.defs["professor_paws@v1"]
        self.assertTrue(old["retired"]["cause"].startswith("superseded by version 2 (promoted challenger c-1"))
        self.assertIn("Professor Paws", old["name"])
        self.assertTrue(all(b.hound_id == "professor_paws@v1" for b in self.bets["professor_paws@v1"]))
        self.assertTrue(all(b.hound_id == "professor_paws" for b in self.bets["professor_paws"]))

    def test_the_new_versions_rule_text_is_generated_and_the_old_ones_is_the_declared_text(self):
        lineage.split_versions(self.defs, self.bets, [self.events])
        self.assertIn("3.0 points or more", self.defs["professor_paws"]["rule_text"])
        self.assertIn("2.0 points or more", self.defs["professor_paws@v1"]["rule_text"])

    def test_no_promotion_and_no_stamped_rows_changes_nothing(self):
        plain = {"professor_paws": [F.bet("professor_paws", "e1", F.day_n(1), 0, -1.0)]}
        before = dict(self.defs)
        self.assertEqual(lineage.split_versions(self.defs, plain, [Path(self._tmp.name) / "none.jsonl"]), [])
        self.assertEqual(self.defs, before)

    def test_rows_stamped_with_a_later_version_are_grouped_even_if_the_registry_is_gone(self):
        made = lineage.split_versions(self.defs, self.bets, [Path(self._tmp.name) / "none.jsonl"])
        self.assertEqual(made, ["professor_paws@v1"])
        self.assertEqual((len(self.bets["professor_paws"]), len(self.bets["professor_paws@v1"])), (3, 5))

    def test_a_fresh_promotion_with_no_new_bets_yet_shows_an_empty_running_champion(self):
        bets = {"professor_paws": [F.bet("professor_paws", f"e{i}", F.day_n(i), 0, -1.0) for i in range(5)]}
        lineage.split_versions(self.defs, bets, [self.events])
        self.assertEqual(bets["professor_paws"], [])
        self.assertEqual(len(bets["professor_paws@v1"]), 5)
        self.assertEqual(self.defs["professor_paws"]["status_hint"], "running")

    def test_the_real_ledger_reader_stamps_the_version(self):
        rows = [{"kind": "hound_bet", "hound_id": "professor_paws", "date": "2026-11-25", "event_id": "e1",
                 "sport": "mlb", "market": "moneyline", "side": "home", "selection": "X ML", "price_average": -110,
                 "price_best": -105, "book_count": 5, "lock_utc": "2026-11-25T22:00:00Z",
                 "start_utc": "2026-11-25T23:00:00Z", "segment": "forward", "hound_version": 2, "row_hash": "h1"},
                {"kind": "hound_graded", "hound_id": "professor_paws", "date": "2026-11-25", "event_id": "e1",
                 "market": "moneyline", "bet_row_hash": "h1", "result": "WIN", "units_best_price": 0.9}]
        bets, _defs = ledgers.pack_rows(rows)
        self.assertEqual([(b.hound_version, b.result) for b in bets], [(2, "win")])
        plain, _ = ledgers.pack_rows([dict(rows[0], row_hash="h2"), ])
        rows0 = dict(rows[0])
        rows0.pop("hound_version")
        self.assertEqual(ledgers.pack_rows([rows0])[0][0].hound_version, 1)


if __name__ == "__main__":
    unittest.main()
