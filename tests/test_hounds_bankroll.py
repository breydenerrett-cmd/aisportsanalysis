"""The bankroll view (src/hounds/bankroll.py, docs/BANKROLL.md): a $1,000 paper account, 1 unit = $10.

The owner's complaint (2026-10-19): "up 2 units" beside "ROI 71%" does not read like money. These tests pin the
definitions that replaced it: dollars from one shared start, a flat unit, stake-weighted member dogs, windows by
settle time, and a yield that is kept for the detail page only. The arithmetic is worked by hand in the comments.

Runs without FastAPI (Linux CI has none); the route checks skip there.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import bankroll as bk, contract, ledgers, stats, user_rules
from src.hounds.ledgers import Sources
from tests import _hounds_fixtures as F

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds import router

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


def ev(units, hours_ago=None, result=None, stake=1.0, settle=None, order=("2026-10-01", "x")):
    """One bankroll event; ``units`` is the stake-weighted profit in units."""
    when = settle if settle is not None else (NOW - timedelta(hours=hours_ago) if hours_ago is not None else None)
    result = result or ("win" if units > 0 else "loss" if units < 0 else "push")
    return bk.Event(settle=when, units=units, flat=units / stake, stake=stake, result=result, order=order)


class Constants(unittest.TestCase):
    def test_the_owner_numbers(self):
        p = bk.params()
        self.assertEqual((p.start, p.unit_pct, p.unit_usd, p.currency), (1000.0, 1.0, 10.0, "USD"))
        self.assertEqual(p.small_sample_min, 20)

    def test_the_public_label_says_every_model_starts_the_same(self):
        pub = bk.public_block()
        self.assertEqual(pub["label"], "Every model starts with the same $1,000 paper bankroll. 1 unit = $10.")
        self.assertIs(pub["flat_stakes"], True)
        self.assertIn("does not compound", pub["note"])

    def test_a_missing_or_broken_config_means_the_owner_numbers(self):
        for text in (None, "{not json", "[]", '{"starting_bankroll": -5, "unit_pct": "x", "small_sample_min_settled": true}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "bankroll.json"
                if text is not None:
                    path.write_text(text, encoding="utf-8")
                with mock.patch.object(bk, "config_path", lambda: path):
                    p = bk.params()
                    self.assertEqual((p.start, p.unit_usd, p.small_sample_min), (1000.0, 10.0, 20))

    def test_a_changed_unit_size_moves_the_dollars_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bankroll.json"
            path.write_text(json.dumps({"starting_bankroll": 2000, "unit_pct": 0.5}), encoding="utf-8")
            with mock.patch.object(bk, "config_path", lambda: path):
                b = bk.block([ev(2.0, 1)], NOW)
        self.assertEqual((b["start"], b["unit_usd"], b["pnl_usd"], b["current"]), (2000.0, 10.0, 20.0, 2020.0))
        self.assertEqual(b["return_pct"], 1.0)

    def test_the_stake_ceiling_is_the_specs_ceiling(self):
        self.assertEqual(bk.MAX_STAKE_UNITS, max(user_rules.STAKE_CHOICES))

    def test_the_config_is_in_the_cache_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            self.assertTrue(any("bankroll.json" in entry[0] for entry in src.fingerprint()
                                if isinstance(entry, tuple) and entry and isinstance(entry[0], str)))


class Windows(unittest.TestCase):
    def test_a_bet_settled_exactly_24_hours_ago_is_outside_the_24h_window(self):
        out_, in_ = ev(1.0, 24), ev(1.0, 24 - 1 / 3600)
        self.assertEqual(bk.block([out_], NOW)["windows"]["h24"]["bets"], 0)
        self.assertEqual(bk.block([in_], NOW)["windows"]["h24"]["bets"], 1)

    def test_a_bet_settled_this_second_and_one_stamped_in_the_future_are_inside(self):
        b = bk.block([ev(1.0, 0), ev(1.0, -3)], NOW)
        self.assertEqual(b["windows"]["h24"]["bets"], 2)

    def test_7_and_30_day_edges(self):
        evts = [ev(1.0, 24 * 7), ev(1.0, 24 * 7 - 1), ev(1.0, 24 * 30), ev(1.0, 24 * 30 - 1), ev(1.0, 24 * 40)]
        w = bk.block(evts, NOW)["windows"]
        self.assertEqual((w["h24"]["bets"], w["d7"]["bets"], w["d30"]["bets"], w["season"]["bets"]), (0, 1, 3, 5))

    def test_window_dollars_percent_and_units(self):
        # 24h: +1.5u and -0.5u => +1.0u = +$10 = +1.00% of the $1,000 start. Older: +3u (not in 24h).
        w = bk.block([ev(1.5, 2), ev(-0.5, 5), ev(3.0, 100)], NOW)["windows"]
        self.assertEqual((w["h24"]["units"], w["h24"]["pnl_usd"], w["h24"]["return_pct"]), (1.0, 10.0, 1.0))
        self.assertEqual((w["d7"]["units"], w["d7"]["pnl_usd"], w["d7"]["return_pct"]), (4.0, 40.0, 4.0))
        self.assertEqual((w["h24"]["bets"], w["h24"]["settled"]), (2, 2))

    def test_season_window_is_the_whole_view_and_matches_the_top_level(self):
        b = bk.block([ev(1.0, 1), ev(-2.0, 500), ev(0.5, 900)], NOW)
        self.assertEqual({k: b["windows"]["season"][k] for k in ("pnl_usd", "return_pct", "units", "bets")},
                         {"pnl_usd": b["pnl_usd"], "return_pct": b["return_pct"], "units": b["units_total"],
                          "bets": b["bets"]})

    def test_windows_add_up_to_the_season_to_the_cent(self):
        # flat, non-compounding units: the part settled in the last week plus the part before it is the whole.
        evts = [ev(0.91, 3), ev(-1.0, 60), ev(1.33, 300), ev(-1.0, 600)]
        b = bk.block(evts, NOW)
        older = bk.block([e for e in evts if e.settle <= NOW - timedelta(days=7)], NOW)
        self.assertAlmostEqual(b["windows"]["d7"]["pnl_usd"] + older["pnl_usd"], b["pnl_usd"], places=2)

    def test_a_bet_with_no_readable_settle_time_counts_in_the_season_only(self):
        b = bk.block([ev(1.0, None), ev(1.0, 1)], NOW)
        self.assertEqual((b["windows"]["h24"]["bets"], b["windows"]["season"]["bets"]), (1, 2))

    def test_voids_are_bets_but_not_settled(self):
        w = bk.block([ev(0.0, 1, result="void"), ev(0.0, 1, result="push"), ev(1.0, 1)], NOW)["windows"]["h24"]
        self.assertEqual((w["bets"], w["settled"]), (3, 2))

    def test_refreshed_moves_the_windows_with_the_clock(self):
        s = contract.HoundSummary(id="x", name="X")
        bk.attach(s, [ev(2.0, 1)], "average_price", NOW)
        self.assertEqual(s.bankroll["windows"]["h24"]["pnl_usd"], 20.0)
        later = bk.refreshed(s, NOW + timedelta(days=2))
        self.assertEqual(later.bankroll["windows"]["h24"]["pnl_usd"], 0.0)
        self.assertEqual(later.bankroll["windows"]["d7"]["pnl_usd"], 20.0)
        self.assertEqual(s.bankroll["windows"]["h24"]["pnl_usd"], 20.0)        # the cached one is not mutated
        self.assertIs(bk.refreshed(contract.HoundSummary(id="y", name="Y")).bankroll, None)


class Account(unittest.TestCase):
    def test_return_is_pnl_over_the_start_never_per_bet(self):
        # +1.2u, +1.2u, -1u = +1.4u => +$14 => $1,014.00 => +1.40% (a per-bet yield would have said 46.7%).
        b = bk.block([ev(1.2, 30), ev(1.2, 20), ev(-1.0, 10)], NOW)
        self.assertEqual((b["current"], b["pnl_usd"], b["return_pct"], b["units_total"]), (1014.0, 14.0, 1.4, 1.4))
        self.assertEqual(b["return_pct"], round(b["pnl_usd"] / 1000.0 * 100, 2))

    def test_yield_is_profit_per_dollar_bet_and_a_push_is_not_money_at_risk(self):
        # decided stakes: 2u + 1u = 3u = $30 at risk; push 5u and void 5u are refunded. pnl +1.2u = $12.
        evts = [ev(2.4, 5, stake=2.0), ev(-1.0, 4), ev(0.0, 3, result="push", stake=5.0),
                ev(0.0, 2, result="void", stake=5.0)]
        b = bk.block(evts, NOW)
        self.assertEqual((b["wagered_usd"], b["pnl_usd"], b["yield_pct"]), (30.0, 14.0, round(14 / 30 * 100, 2)))

    def test_an_account_with_nothing_settled_is_the_opening_balance(self):
        b = bk.block([], NOW)
        self.assertEqual((b["current"], b["pnl_usd"], b["return_pct"], b["units_total"], b["bets"]),
                         (1000.0, 0.0, 0.0, 0.0, 0))
        self.assertIsNone(b["yield_pct"])
        self.assertTrue(b["small_sample"])
        self.assertEqual((b["peak"], b["max_drawdown_usd"]), (1000.0, 0.0))

    def test_small_sample_below_twenty_settled_bets(self):
        self.assertTrue(bk.block([ev(1.0, 1)] * 19, NOW)["small_sample"])
        self.assertFalse(bk.block([ev(1.0, 1)] * 20, NOW)["small_sample"])
        # a push settles; a void does not
        self.assertFalse(bk.block([ev(1.0, 1)] * 19 + [ev(0.0, 1, result="push")], NOW)["small_sample"])
        self.assertTrue(bk.block([ev(1.0, 1)] * 19 + [ev(0.0, 1, result="void")], NOW)["small_sample"])

    def test_max_drawdown_is_the_worst_peak_to_trough_in_settle_order(self):
        # balance: 1000 +30 =1030, +20 =1050 (peak), -40 =1010, -30 =980 (trough, $70 below the peak),
        # +100 =1080 (new peak, no new drawdown), -10 =1070.
        order = [ev(3.0, 60), ev(2.0, 50), ev(-4.0, 40), ev(-3.0, 30), ev(10.0, 20), ev(-1.0, 10)]
        b = bk.block(list(reversed(order)), NOW)               # fed out of order on purpose
        self.assertEqual((b["peak"], b["max_drawdown_usd"], b["current"]), (1080.0, 70.0, 1070.0))
        self.assertEqual(b["max_drawdown_pct"], round(70 / 1050 * 100, 2))

    def test_a_model_that_only_lost_has_its_drawdown_from_the_opening_balance(self):
        b = bk.block([ev(-1.0, 3), ev(-1.0, 2)], NOW)
        self.assertEqual((b["peak"], b["max_drawdown_usd"], b["max_drawdown_pct"]), (1000.0, 20.0, 2.0))

    def test_a_model_that_only_won_has_no_drawdown(self):
        self.assertEqual(bk.block([ev(1.0, 3), ev(1.0, 2)], NOW)["max_drawdown_usd"], 0.0)

    def test_stake_summary_for_the_builder_line(self):
        b = bk.block([ev(3.0, 5, stake=3.0), ev(-3.0, 4, stake=3.0)], NOW)
        self.assertEqual((b["stake_units"], b["avg_stake_units"]), (3.0, 3.0))


class StakeAndSettleTime(unittest.TestCase):
    def test_only_a_member_dog_stakes_its_own_units(self):
        mine = ledgers.Bet(hound_id="u", stake_units=2.5)
        self.assertEqual(bk.stake_of(mine, "user"), 2.5)
        for kind in ("house", "baseline", None):
            self.assertEqual(bk.stake_of(mine, kind), 1.0)

    def test_a_missing_or_nonsense_stake_is_one_unit(self):
        for bad in (None, 0, -1, 3.01, 40, "3", True, float("nan")):
            with self.subTest(stake=bad):
                self.assertEqual(bk.stake_of(ledgers.Bet(hound_id="u", stake_units=bad), "user"), 1.0)

    def test_graded_utc_is_the_settle_time_and_a_missing_one_is_estimated_from_the_slate_day(self):
        stamped = ledgers.Bet(hound_id="u", date="2026-10-01", graded_utc="2026-10-02T08:30:00Z")
        when, estimated = bk.settle_time(stamped)
        self.assertEqual((when, estimated), (datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), False))
        when, estimated = bk.settle_time(ledgers.Bet(hound_id="u", date="2026-10-01"))
        self.assertEqual((when, estimated), (datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc), True))
        self.assertEqual(bk.settle_time(ledgers.Bet(hound_id="u", date="")), (None, True))

    def test_the_ledger_reader_carries_stake_and_graded_stamp_but_not_the_house_stake(self):
        rows = [
            {"hound_id": "u-9", "kind": "hound"},
            {"hound_id": "u-9", "bet_id": "a", "date": "2026-10-02", "market": "moneyline", "selection": "home",
             "stake_units": 2.0, "event_id": "G1"},
            {"hound_id": "u-9", "bet_id": "a", "result": "win", "graded_utc": "2026-10-03T07:00:00Z", "units": 1.0},
            {"hound_id": "h-9", "bet_id": "b", "date": "2026-10-02", "market": "moneyline", "selection": "home",
             "stake": 0.3, "event_id": "G2", "result": "loss", "units": -1.0},
        ]
        bets, _ = ledgers.pack_rows(rows)
        by_id = {b.bet_id: b for b in bets}
        self.assertEqual((by_id["a"].stake_units, by_id["a"].graded_utc), (2.0, "2026-10-03T07:00:00Z"))
        self.assertIsNone(by_id["b"].stake_units)          # the house pack's own ``stake`` is not read
        self.assertIsNone(by_id["b"].graded_utc)


def _member_world(root: Path) -> Sources:
    """The standard fixture world plus two member dogs: ``u-2`` stakes 0.5 to 3 units, ``u-3`` is a v1 dog."""
    src = F.make_world(root)
    # u-2 (average price on every bet, so the average-price basis applies):
    #   m1 win  at avg +110, stake 3.0 -> +1.10 * 3.0 = +3.30u   graded 2026-10-02T12:00Z
    #   m2 loss             , stake 0.5 -> -1.00 * 0.5 = -0.50u   graded 2026-10-02T18:00Z
    #   m3 loss             , stake 2.0 -> -1.00 * 2.0 = -2.00u   graded 2026-10-03T09:00Z
    #   total +0.80u = +$8.00 (flat view: 1.10 - 1 - 1 = -0.90u)
    def row(hid, bet_id, event, date, result, stake, graded, best=120, avg=110):
        out = {"hound_id": hid, "bet_id": bet_id, "date": date, "event_id": event, "sport": "mlb",
               "market": "moneyline", "selection": "away", "price_best": best, "price_average": avg,
               "lock_utc": f"{date}T15:00:00+00:00", "start_utc": f"{date}T23:00:00Z", "segment": "forward",
               "who_decided": "rule", "result": result, "units": 1.2 if result == "win" else -1.0,
               "graded_utc": graded}
        if stake is not None:
            out["stake_units"] = stake
        return out
    rows = [
        {"kind": "hound", "hound_id": "u-1", "name": "Rover", "owner_display": "pat", "rule_text": "Pat's rule.",
         "category": "mixed", "style": "mine"},
        {"hound_id": "u-1", "date": "2026-10-01", "event_id": "E1", "sport": "mlb", "market": "moneyline",
         "selection": "away", "price_best": 115, "price_average": 108, "lock_utc": F.DECIDE, "start_utc": F.START,
         "segment": "forward", "bet_id": "q1", "who_decided": "rule", "result": "loss", "units": -1.0},
        {"kind": "hound", "hound_id": "u-2", "name": "Heavy", "owner_display": "sam", "rule_text": "Sam's rule.",
         "category": "mixed", "style": "mine"},
        row("u-2", "m1", "G1", "2026-10-02", "win", 3.0, "2026-10-02T12:00:00Z"),
        row("u-2", "m2", "G2", "2026-10-02", "loss", 0.5, "2026-10-02T18:00:00Z"),
        row("u-2", "m3", "G3", "2026-10-03", "loss", 2.0, "2026-10-03T09:00:00Z"),
        {"kind": "hound", "hound_id": "u-3", "name": "Plain", "owner_display": "lee", "rule_text": "Lee's rule.",
         "category": "mixed", "style": "mine"},
        row("u-3", "n1", "G4", "2026-10-02", "win", None, "2026-10-02T12:00:00Z"),
    ]
    F.write_jsonl(root / "evidence/hounds_user_v1.jsonl", rows)
    return src


class OverTheWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.src = _member_world(Path(cls._tmp.name))
        stats.clear_cache()
        cls.book = stats.build(cls.src)

    @classmethod
    def tearDownClass(cls):
        stats.clear_cache()
        cls._tmp.cleanup()

    def bank(self, hid, season="all"):
        return self.book.hounds[hid].view(season).summary.bankroll

    def test_every_hound_in_every_view_has_a_bankroll_block(self):
        for data in self.book.hounds.values():
            for season in ("all", "s1", "s2"):
                b = data.view(season).summary.bankroll
                self.assertIsNotNone(b, (data.summary.id, season))
                self.assertEqual((b["start"], b["unit_usd"]), (1000.0, 10.0))
                self.assertEqual(set(b["windows"]), {"h24", "d7", "d30", "season"})

    def test_house_and_baseline_dogs_bet_one_unit_of_ten_dollars(self):
        # alpha's forward bets: win/loss/push; average-price basis (see test_hounds_stats): +0.8130 - 1 + 0.
        a = self.book.hounds["alpha"].summary
        b = a.bankroll
        self.assertEqual(b["basis"], "average_price")
        self.assertAlmostEqual(b["pnl_usd"], a.record.units_average_price * 10.0, places=1)
        self.assertEqual(b["units_total"], b["units_flat"])
        self.assertEqual(b["stake_units"], 1.0)
        self.assertEqual(b["current"], round(1000.0 + b["pnl_usd"], 2))
        # bravo (a baseline dog): one void is a bet and no money
        v = self.bank("bravo")
        self.assertEqual((v["bets"], v["settled"], v["pnl_usd"], v["current"]), (1, 0, 0.0, 1000.0))

    def test_the_house_pack_stake_is_ignored_house_dogs_always_bet_one_unit(self):
        # charlie's forward win paid 1.12u at the recorded price, 1 unit staked: +$11.20 at the recorded price.
        c = self.bank("charlie")
        self.assertEqual(c["stake_units"], 1.0)
        self.assertEqual(c["avg_stake_units"], 1.0)

    def test_a_member_dog_is_stake_weighted_and_the_flat_figure_stays_available(self):
        b = self.bank("u-2")
        self.assertEqual(b["basis"], "average_price")
        self.assertAlmostEqual(b["units_total"], 0.8, places=2)
        self.assertAlmostEqual(b["units_flat"], -0.9, places=2)
        self.assertAlmostEqual(b["pnl_usd"], 8.0, places=2)
        self.assertEqual(b["current"], 1008.0)
        self.assertAlmostEqual(b["return_pct"], 0.8, places=2)
        # one in 2.5 units wagered on decided bets... 3.0 + 0.5 + 2.0 = 5.5u = $55 at risk: yield 8/55
        self.assertAlmostEqual(b["yield_pct"], 8.0 / 55.0 * 100, places=2)
        self.assertEqual(b["stake_units"], 2.0)             # the latest bet's stake
        self.assertAlmostEqual(b["avg_stake_units"], 5.5 / 3, places=3)

    def test_the_public_record_is_still_flat_one_unit_per_bet(self):
        # The bankroll supersedes the "every bet is one unit" ruling for the bankroll view ONLY.
        r = self.book.hounds["u-2"].summary.record
        self.assertAlmostEqual(r.units_average_price, -0.9, places=3)
        self.assertEqual(r.bets, 3)

    def test_a_v1_member_dog_with_no_stake_bets_one_unit(self):
        b = self.bank("u-3")
        self.assertEqual((b["stake_units"], b["units_total"], b["units_total"] == b["units_flat"]), (1.0, 1.1, True))
        self.assertEqual(b["pnl_usd"], 11.0)

    def test_member_windows_follow_graded_utc(self):
        # now = 2026-10-03T12:00Z: m3 (09:00 today) and m2 (18:00 yesterday) are inside 24h; m1 (12:00
        # yesterday, exactly 24h ago) is not. m2 + m3 = -0.5 - 2.0 = -2.5u = -$25 = -2.50%.
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        b = bk.block(self.book.hounds["u-2"].summary._bankroll_events, now)
        h = b["windows"]["h24"]
        self.assertEqual((h["bets"], h["units"], h["pnl_usd"], h["return_pct"]), (2, -2.5, -25.0, -2.5))
        self.assertEqual(b["windows"]["d7"]["bets"], 3)
        self.assertEqual(b["settle_estimated"], 0)

    def test_engine_dogs_have_estimated_settle_times_and_say_so(self):
        b = self.bank("alpha")
        self.assertEqual(b["settle_estimated"], b["bets"])

    def test_a_season_view_is_its_own_account_from_the_opening_balance(self):
        # every fixture bet is in October 1-3, inside season 1 (to 2026-10-17): season 2 has nothing.
        s2 = self.bank("u-2", "s2")
        self.assertEqual((s2["bets"], s2["current"], s2["pnl_usd"]), (0, 1000.0, 0.0))
        self.assertEqual(self.bank("u-2", "s1")["current"], self.bank("u-2", "all")["current"])

    def test_the_series_is_in_dollars_and_ends_on_the_account_balance(self):
        for hid in ("alpha", "u-2", "u-3", "charlie"):
            series = self.book.hounds[hid].series
            self.assertTrue(series)
            self.assertEqual(series[0].bankroll_usd, 1000.0, hid)           # the zero point is the opening balance
            self.assertEqual(series[-1].bankroll_usd, self.bank(hid)["current"], hid)
        # u-2: day 1 (Oct 2) is +3.30 - 0.50 = +2.80u = $1,028.00; day 2 (Oct 3) is -2.00u => $1,008.00
        got = [p.bankroll_usd for p in self.book.hounds["u-2"].series]
        self.assertEqual(got, [1000.0, 1028.0, 1008.0])

    def test_old_fields_are_all_still_there_and_the_block_is_additive(self):
        s = contract.to_json(self.book.hounds["alpha"].summary)
        old = {"id", "name", "tagline", "kind", "category", "style", "owner_display", "sports", "markets",
               "rule_text", "status", "retired", "record", "clv", "verdict", "first_bet_utc", "last_bet_utc",
               "verified", "verified_share", "checkable_share", "replay", "spark", "spark_basis", "source",
               "persona", "form", "open_bets", "ungraded_bets", "settled", "ranked"}
        self.assertEqual(set(s) - old, {"bankroll"})
        self.assertEqual(set(s["record"]), {"bets", "wins", "losses", "pushes", "voids",
                                            "units_recorded_price", "units_average_price"})
        json.dumps(s, allow_nan=False)

    def test_payloads_carry_the_rules_and_fresh_windows(self):
        board = contract.leaderboard_payload(stats.leaderboard(self.book, "all"), self.book.as_of)
        self.assertEqual(board["bankroll_rules"]["label"],
                         "Every model starts with the same $1,000 paper bankroll. 1 unit = $10.")
        self.assertTrue(all("bankroll" in h for h in board["hounds"]))
        detail = contract.hound_payload(self.book.hounds["u-2"].summary, self.book.hounds["u-2"].series,
                                        contract.paginate(self.book.hounds["u-2"].bets, 1), self.book.as_of)
        self.assertEqual(detail["bankroll"]["current"], 1008.0)
        self.assertEqual(detail["bankroll_rules"]["unit_usd"], 10.0)
        # the windows in a payload are about NOW, not about the day the book was built: nothing here is recent
        self.assertEqual(detail["bankroll"]["windows"]["h24"]["bets"], 0)
        series = contract.series_payload({"u-2": self.book.hounds["u-2"].series}, self.book.as_of)
        self.assertEqual(series["series"]["u-2"][-1]["bankroll_usd"], 1008.0)
        self.assertEqual(series["bankroll_rules"]["start_usd"], 1000.0)

    def test_the_saved_copy_carries_the_blocks(self):
        snap = stats.build_snapshot(self.book)
        row = next(h for h in snap["views"]["all"]["leaderboard"]["hounds"] if h["id"] == "u-2")
        self.assertEqual(row["bankroll"]["current"], 1008.0)
        json.dumps(snap, allow_nan=False)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        src = _member_world(Path(cls._tmp.name))
        cls._patch = mock.patch.object(Sources, "default", staticmethod(lambda: src))
        cls._patch.start()
        stats.clear_cache()
        stats.get_book(src)
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        stats.clear_cache()
        cls._tmp.cleanup()

    def get(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_leaderboard_route_has_bankroll_and_every_old_field(self):
        body = self.get("/hounds?season=all")
        self.assertIn("bankroll_rules", body)
        for h in body["hounds"]:
            self.assertIn("bankroll", h)
            for old in ("record", "clv", "verdict", "spark", "form", "settled", "ranked"):
                self.assertIn(old, h)
        mine = next(h for h in body["hounds"] if h["id"] == "u-2")
        self.assertEqual((mine["bankroll"]["current"], mine["bankroll"]["return_pct"]), (1008.0, 0.8))

    def test_detail_and_series_routes(self):
        d = self.get("/hounds/u-2?season=all")
        # balance 1033.00 (peak) -> 1028.00 -> 1008.00: the worst fall is $25
        self.assertEqual((d["bankroll"]["peak"], d["bankroll"]["max_drawdown_usd"]), (1033.0, 25.0))
        self.assertEqual(d["bankroll_rules"]["start_usd"], 1000.0)
        s = self.get("/hounds/series?ids=u-2,alpha&season=all")
        self.assertEqual([p["bankroll_usd"] for p in s["series"]["u-2"]], [1000.0, 1028.0, 1008.0])
        self.assertIn("cum_units_average_price", s["series"]["u-2"][0])


if __name__ == "__main__":
    unittest.main()
