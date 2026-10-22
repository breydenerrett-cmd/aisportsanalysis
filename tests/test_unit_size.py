"""The unit-size lens (src/hounds/unit_size.py, web/js/unitsize.js, api/hounds_kennels.py GET/PUT /me/unit-size).

Owner ask 2026-10-21 (relaying Jacob): "the unit size difference between one unit and three units is only a couple
dollars." A viewer now chooses what a unit is worth (fixed dollars, default $25) or sizes bets as a percent of a
bankroll that compounds. What this file holds the feature to:
  * UNITS STAY THE TRUTH. Returning the same bets at any fixed unit size scales every dollar linearly and leaves the
    return %, the units and the settled counts alone, so a rank can never move with the setting;
  * the legal choices are validated (a whole dollar from $1 to $1,000, or 0.5 to 5 percent in halves on a $100 to
    $100,000 start) and the default is a $25 unit;
  * percent mode COMPOUNDS and is hand-computed below (a five-bet fixture whose every dollar is written out);
  * the browser's port gives the same dollars as Python over the same bets;
  * a signed-in member's choice round-trips through the account, and a visitor whose storage throws gets $25.

The logic tests need no FastAPI (Linux CI has none); the route tests are skipped without it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import bankroll as bk
from src.hounds import unit_size as us
from tests.hounds_web_runner import HAS_NODE, run_js as _run_js


def run_js(source):
    """These tests choose their own viewer (or none): never the pinned reference viewer the page tests run as."""
    return _run_js(source, viewer=None)

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parent.parent


def ev(date, flat, stake, result, hours_ago, bet="x"):
    """One bankroll event: ``flat`` is the one-unit profit, ``units`` the stake-weighted profit."""
    return bk.Event(settle=NOW - timedelta(hours=hours_ago), units=flat * stake, flat=flat, stake=stake,
                    result=result, order=(date, bet))


#: five bets on three slate days (every number below is hand-computed from this list)
FIVE = [
    ev("2026-10-01", 0.9, 1.0, "win", 70, "a"),
    ev("2026-10-01", -1.0, 2.0, "loss", 69, "b"),
    ev("2026-10-02", 1.5, 1.0, "win", 46, "c"),
    ev("2026-10-03", 0.5, 3.0, "win", 20, "d"),
    ev("2026-10-03", 0.0, 1.0, "push", 19, "e"),
]


class TheChoices(unittest.TestCase):
    def test_the_default_is_a_25_dollar_unit_and_a_100_unit_start(self):
        d = us.default_sizing()
        self.assertEqual((d.mode, d.unit_usd, d.start_usd), ("fixed", 25.0, 2500.0))

    def test_every_chip_and_every_whole_dollar_in_range_is_legal(self):
        for dollars in (*us.FIXED_CHIPS, 1, 37, 1000):
            s = us.validate({"mode": "fixed", "unit_usd": dollars})
            self.assertEqual((s.unit_usd, s.start_usd), (float(dollars), dollars * 100.0))

    def test_fixed_refuses_everything_else(self):
        for bad in (0, -5, 1001, 12.5, "25", None, True, float("nan"), [25]):
            with self.subTest(unit=bad), self.assertRaises(us.SizingError) as ctx:
                us.validate({"mode": "fixed", "unit_usd": bad})
            self.assertEqual(ctx.exception.code, "unit_usd")

    def test_percent_takes_half_point_steps_on_a_100_to_100000_start(self):
        for pct in (0.5, 1, 2, 5):
            s = us.validate({"mode": "percent", "pct": pct, "start_usd": 5000})
            self.assertEqual((s.pct, s.start_usd, s.unit_usd), (float(pct), 5000.0, None))
        for start in (100, 100000):
            us.validate({"mode": "percent", "pct": 1, "start_usd": start})
        for bad in (0, 0.25, 0.75, 5.5, 6, "2", None, True):
            with self.subTest(pct=bad), self.assertRaises(us.SizingError) as ctx:
                us.validate({"mode": "percent", "pct": bad, "start_usd": 5000})
            self.assertEqual(ctx.exception.code, "pct")
        for bad in (99, 100001, 2500.5, "5000", None, False):
            with self.subTest(start=bad), self.assertRaises(us.SizingError) as ctx:
                us.validate({"mode": "percent", "pct": 1, "start_usd": bad})
            self.assertEqual(ctx.exception.code, "start_usd")

    def test_infinity_and_numbers_too_big_for_a_float_are_refused_not_a_500(self):
        """A JSON ``1e999`` is +Infinity and ``1`` followed by 400 zeros is an int no float can hold: both once raised
        OverflowError out of the validator (an HTTP 500 on PUT /me/unit-size). They are refusals like any other bad number."""
        huge = 10 ** 400
        for field, extra in (("unit_usd", {"mode": "fixed"}), ("start_usd", {"mode": "percent", "pct": 2}),
                             ("pct", {"mode": "percent", "start_usd": 5000})):
            for bad in (float("inf"), float("-inf"), huge, -huge):
                with self.subTest(field=field, value=bad), self.assertRaises(us.SizingError) as ctx:
                    us.validate({**extra, field: bad})
                self.assertEqual(ctx.exception.code, field)

    def test_a_bad_mode_or_shape_is_refused(self):
        for bad in (None, "fixed", [], {"mode": "kelly"}, {}):
            with self.subTest(raw=bad), self.assertRaises(us.SizingError):
                us.validate(bad)


class FixedIsALinearLens(unittest.TestCase):
    def block(self, unit):
        return bk.block(FIVE, NOW, sizing=us.validate({"mode": "fixed", "unit_usd": unit}))

    def test_dollars_scale_linearly_with_the_unit_and_nothing_else_moves(self):
        base = self.block(10)
        for unit in (25, 50, 100, 7):
            other = self.block(unit)
            k = unit / 10
            self.assertEqual(other["start"], unit * 100.0)
            for key in ("pnl_usd", "wagered_usd", "max_drawdown_usd"):
                self.assertAlmostEqual(other[key], base[key] * k, delta=0.011, msg=key)
            for name, w in base["windows"].items():
                self.assertAlmostEqual(other["windows"][name]["pnl_usd"], w["pnl_usd"] * k, delta=0.011)
                self.assertEqual(other["windows"][name]["return_pct"], w["return_pct"], name)
                self.assertEqual((other["windows"][name]["units"], other["windows"][name]["bets"]),
                                 (w["units"], w["bets"]))
            for key in ("return_pct", "yield_pct", "max_drawdown_pct", "units_total", "units_flat", "settled"):
                self.assertEqual(other[key], base[key], key)

    def test_the_reference_block_is_the_config_unit_and_carries_the_units_only_events(self):
        ref = bk.block(FIVE, NOW)
        self.assertEqual(ref["unit_usd"], bk.params().unit_usd)
        self.assertEqual(len(ref["events"]), 5)
        self.assertEqual(ref["events"][0], ["2026-10-01", int((NOW - timedelta(hours=70)).timestamp()), 0.9, 1.0, "w"])
        self.assertEqual(ref["events"][4][4], "p")
        self.assertNotIn("events", self.block(25))                       # a lens block is the answer, not the input
        self.assertEqual(self.block(25)["sizing"]["unit_usd"], 25.0)

    def test_the_reference_account_is_unchanged_by_the_lens_code(self):
        ref = bk.block(FIVE, NOW)
        self.assertEqual(ref["pnl_usd"], round(sum(e.units for e in FIVE) * bk.params().unit_usd, 2))


class PercentCompounds(unittest.TestCase):
    """The hand-computed fixture. 2% of a $5,000 bankroll, bets of one slate day all sized off the balance before
    any of that day's bets settle:

      day 1, balance 5,000, 1u = $100.00
        a  1u staked, +0.9 flat    -> +0.9u  = +$90.00
        b  2u staked, -1.0 flat    -> -2.0u  = -$200.00      (staked $200.00)   day ends 4,890.00
      day 2, balance 4,890, 1u = $97.80
        c  1u staked, +1.5 flat    -> +1.5u  = +$146.70                          day ends 5,036.70
      day 3, balance 5,036.70, 1u = $100.734
        d  3u staked, +0.5 flat    -> +1.5u  = +$151.101     (staked $302.202)
        e  1u staked, push         ->  0u    =  $0.00                            day ends 5,187.801
      P&L +$187.80 (3.76% of 5,000). Wagered on decided bets: a $100 + b $200 + c $97.80 + d $302.202 = $700.00
      (the push is not money at risk); yield 187.801 / 700.002 = 26.83%.
      Balance in settle order 5,000 -> 5,090 -> 4,890 -> 5,036.70 -> 5,187.801: the worst fall is b's, $200 off
      the 5,090 peak (3.93%); the final balance is the new high, 5,187.80."""

    SIZING = {"mode": "percent", "pct": 2, "start_usd": 5000}

    def setUp(self):
        self.b = bk.block(FIVE, NOW, sizing=us.validate(self.SIZING))

    def test_each_bet_is_its_own_dollars_off_its_days_balance(self):
        got = us.priced(FIVE, us.validate(self.SIZING))
        want = [(90.0, 100.0), (-200.0, 200.0), (146.7, 97.8), (151.101, 302.202), (0.0, 100.734)]
        for (gp, gs), (wp, ws) in zip(got, want):
            self.assertAlmostEqual(gp, wp, places=6)
            self.assertAlmostEqual(gs, ws, places=6)

    def test_the_account(self):
        b = self.b
        self.assertEqual((b["start"], b["pnl_usd"], b["current"], b["return_pct"]), (5000.0, 187.8, 5187.8, 3.76))
        self.assertEqual((b["wagered_usd"], b["yield_pct"]), (700.0, 26.83))
        self.assertEqual((b["peak"], b["max_drawdown_usd"], b["max_drawdown_pct"]), (5187.8, 200.0, 3.93))

    def test_pnl_is_not_units_times_a_constant_here(self):
        # 1.5u won on day 2 is $146.70 and 1.5u won on day 3 is $151.10: the unit grew with the balance
        priced = us.priced(FIVE, us.validate(self.SIZING))
        self.assertNotAlmostEqual(priced[2][0], priced[3][0], places=2)
        self.assertEqual(FIVE[2].units, FIVE[3].units)

    def test_windows_use_settle_time_and_the_same_per_bet_dollars(self):
        w = self.b["windows"]
        self.assertEqual((w["h24"]["bets"], w["h24"]["pnl_usd"]), (2, 151.1))          # d and e settled 20h and 19h ago
        self.assertEqual((w["d7"]["bets"], w["d7"]["pnl_usd"]), (5, 187.8))
        self.assertEqual(w["season"]["settled"], 5)
        self.assertEqual(w["h24"]["units"], 1.5)

    def test_units_and_the_record_are_the_servers_whatever_the_sizing(self):
        ref = bk.block(FIVE, NOW)
        for key in ("units_total", "units_flat", "settled", "bets"):
            self.assertEqual(self.b[key], ref[key], key)
        self.assertEqual(self.b["sizing"]["mode"], "percent")


class OneSource(unittest.TestCase):
    def test_the_stake_ceiling_is_the_specs_ceiling_and_the_picker_goes_to_five(self):
        from src.hounds import user_rules
        self.assertEqual(bk.MAX_STAKE_UNITS, max(user_rules.STAKE_CHOICES))
        self.assertEqual(max(user_rules.STAKE_CHOICES), 5.0)
        for units in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0):
            self.assertIn(units, user_rules.STAKE_CHOICES)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBrowserPortAgreesWithPython(unittest.TestCase):
    """web/js/unitsize.js is the port; the dollars must match to the cent (rounded the same way)."""

    def lens(self, sizing, now=NOW):
        ref = bk.block(FIVE, now)
        snippet = ('import * as U from "./unitsize.js";\n'
                   f"const b = {json.dumps(ref)};\n"
                   f"console.log(JSON.stringify(U.lensBlock(b, {json.dumps(sizing)}, {int(now.timestamp())})));")
        return run_js(snippet)

    def check(self, sizing):
        sizing = us.validate(sizing).as_dict()                 # the page always holds a parsed sizing, with its start
        want = bk.block(FIVE, NOW, sizing=us.validate(sizing))
        got = self.lens(sizing)
        for key in ("start", "current", "pnl_usd", "return_pct", "wagered_usd", "yield_pct", "peak",
                    "max_drawdown_usd", "max_drawdown_pct", "units_total", "settled"):
            self.assertAlmostEqual(got[key], want[key], delta=0.011, msg=f"{sizing} {key}")
        for name in ("h24", "d7", "d30", "season"):
            for key in ("pnl_usd", "return_pct", "units", "bets", "settled"):
                self.assertAlmostEqual(got["windows"][name][key], want["windows"][name][key], delta=0.011,
                                       msg=f"{sizing} {name}.{key}")

    def test_fixed_sizes(self):
        for unit in (10, 25, 50, 100, 3):
            self.check({"mode": "fixed", "unit_usd": unit})

    def test_a_six_bet_fixture_with_a_push_a_void_and_two_bets_on_one_day_is_exact_in_both_ports(self):
        """Hand-computed (2% of $2,500; sized off the pre-day balance): day 1 balance 2500 -> A +90.00 (2u win at +0.9) and B -50.00
        -> 2540; day 2 base 2540 -> push 0, D +228.60 (3u at +1.5) -> 2768.60; day 3 base 2768.60 -> void 0, F -110.744 -> 2657.856.
        Wagered is the decided bets only (100 + 50 + 152.40 + 110.744). Drawdown 110.744 off the 2768.60 peak is exactly 4%."""
        def e(day, flat, stake, result, hours):
            return bk.Event(settle=NOW - timedelta(hours=hours), units=flat * stake, flat=flat, stake=stake, result=result,
                            order=(day, f"b{hours}"))
        bets = [e("2026-10-01", 0.9, 2, "win", 100), e("2026-10-01", -1, 1, "loss", 99), e("2026-10-02", 0, 1, "push", 75),
                e("2026-10-02", 1.5, 3, "win", 74), e("2026-10-03", 0, 1, "void", 50), e("2026-10-03", -1, 2, "loss", 49)]
        sizing = us.validate({"mode": "percent", "pct": 2, "start_usd": 2500})
        hand = {"start": 2500.0, "current": 2657.86, "pnl_usd": 157.86, "return_pct": 6.31, "wagered_usd": 413.14, "yield_pct": 38.21,
                "peak": 2768.6, "max_drawdown_usd": 110.74, "max_drawdown_pct": 4.0, "bets": 6, "settled": 5}
        py = bk.block(bets, NOW, sizing=sizing)
        self.assertEqual({k: py[k] for k in hand}, hand)
        got = run_js('import * as U from "./unitsize.js";\n'
                     f"const b = {json.dumps({**bk.block(bets, NOW), 'bets': 6, 'settled': 5})};\n"
                     f"console.log(JSON.stringify(U.lensBlock(b, {json.dumps(sizing.as_dict())}, {int(NOW.timestamp())})));")
        self.assertEqual({k: got[k] for k in hand}, hand)

    def test_units_that_never_terminate_still_price_to_the_cent(self):
        """-110 style prices give units like 0.909090...; the wire keeps six places so 40 such bets at $1,000 a unit match Python."""
        bets = [bk.Event(settle=NOW - timedelta(hours=i + 1), units=(100 / 110) * 1.5 if i % 3 else -1.5, flat=(100 / 110),
                         stake=1.5, result="win" if i % 3 else "loss", order=(f"2026-09-{i // 2 + 1:02d}", f"b{i:03d}")) for i in range(40)]
        sizing = us.validate({"mode": "fixed", "unit_usd": 1000})
        want = bk.block(bets, NOW, sizing=sizing)
        got = run_js('import * as U from "./unitsize.js";\n'
                     f"const b = {json.dumps({**bk.block(bets, NOW), 'bets': 40, 'settled': 40})};\n"
                     f"console.log(JSON.stringify(U.lensBlock(b, {json.dumps({**sizing.as_dict(), 'unit_usd': 1000})}, {int(NOW.timestamp())})));")
        for key in ("current", "pnl_usd", "wagered_usd", "peak", "max_drawdown_usd"):
            self.assertAlmostEqual(got[key], want[key], delta=0.0051, msg=key)

    def test_percent_sizes(self):
        self.check({"mode": "percent", "pct": 2, "start_usd": 5000})
        self.check({"mode": "percent", "pct": 0.5, "start_usd": 100})
        self.check({"mode": "percent", "pct": 5, "start_usd": 100000})

    def test_the_series_is_the_balance_after_each_slate_day(self):
        ref = bk.block(FIVE, NOW)
        pts = [{"date": d} for d in ("2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03")]
        out = run_js('import * as U from "./unitsize.js";\n'
                     f"const b = {json.dumps(ref)};\nconst pts = {json.dumps(pts)};\n"
                     'console.log(JSON.stringify(U.lensSeriesUsd(pts, b, {mode: "percent", unit_usd: null, pct: 2, start_usd: 5000})));')
        self.assertEqual(out, [5000.0, 4890.0, 5036.7, 5187.8])

    def test_the_constants_are_pythons(self):
        out = run_js('import * as U from "./unitsize.js";\n'
                     "console.log(JSON.stringify([U.FIXED_MIN, U.FIXED_MAX, U.FIXED_CHIPS, U.DEFAULT_FIXED_USD, U.UNITS_IN_START, "
                     "U.PCT_CHOICES, U.DEFAULT_PCT, U.START_MIN, U.START_MAX, U.DEFAULT_START_USD]));")
        self.assertEqual(out, [us.FIXED_MIN, us.FIXED_MAX, list(us.FIXED_CHIPS), us.DEFAULT_FIXED_USD, us.UNITS_IN_START,
                               list(us.PCT_CHOICES), us.DEFAULT_PCT, us.START_MIN, us.START_MAX, us.DEFAULT_START_USD])

    def test_the_validators_agree(self):
        cases = [{"mode": "fixed", "unit_usd": v} for v in (0, 1, 12.5, 1000, 1001, "25")] + \
                [{"mode": "percent", "pct": p, "start_usd": s} for p, s in ((0.5, 100), (0.25, 100), (5, 100000), (5, 100001), (2, 99))]
        want = []
        for raw in cases:
            try:
                us.validate(raw)
                want.append(True)
            except us.SizingError:
                want.append(False)
        got = run_js('import * as U from "./unitsize.js";\n'
                     f"console.log(JSON.stringify({json.dumps(cases)}.map((c) => U.parseSizing(c) !== null)));")
        self.assertEqual(got, want)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheVisitorsChoice(unittest.TestCase):
    """A visitor's choice is in localStorage; storage may be missing or throw, and the answer is then $25."""

    def read(self, setup):
        out = run_js('import * as U from "./unitsize.js";\n' + setup + "\nconsole.log(JSON.stringify(U.getSizing()));")
        return out

    def test_no_window_at_all_is_the_default(self):
        self.assertEqual(self.read(""), us.default_sizing().as_dict())

    def test_storage_that_throws_on_every_call_is_the_default(self):
        out = self.read('globalThis.window = {localStorage: {getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }}};')
        self.assertEqual(out["unit_usd"], 25)

    def test_storage_whose_accessor_throws_is_the_default(self):
        out = self.read('globalThis.window = {}; Object.defineProperty(globalThis.window, "localStorage", {get() { throw new Error("denied"); }});')
        self.assertEqual(out["unit_usd"], 25)

    def test_a_stored_choice_is_read_back(self):
        out = self.read('globalThis.window = {localStorage: {getItem: () => JSON.stringify({mode: "percent", unit_usd: null, pct: 2, start_usd: 5000}), setItem() {}}};')
        self.assertEqual(out, {"mode": "percent", "unit_usd": None, "pct": 2, "start_usd": 5000})

    def test_junk_in_storage_is_the_default(self):
        for junk in ("not json", '{"mode":"fixed","unit_usd":0}', '{"mode":"percent","pct":9,"start_usd":5000}', "null"):
            with self.subTest(junk=junk):
                out = self.read(f"globalThis.window = {{localStorage: {{getItem: () => {json.dumps(junk)}, setItem() {{}}}}}};")
                self.assertEqual(out["unit_usd"], 25, junk)

    def test_choosing_with_storage_throwing_still_applies_for_the_page_and_does_not_throw(self):
        out = run_js('import * as U from "./unitsize.js";\n'
                     'globalThis.window = {localStorage: {getItem() { throw new Error("x"); }, setItem() { throw new Error("x"); }}, dispatchEvent() {}};\n'
                     'U.onSizingChange(() => {});\n'
                     'const r = await U.chooseSizing({mode: "fixed", unit_usd: 50});\n'
                     "console.log(JSON.stringify([r, U.getSizing().unit_usd]));")
        self.assertEqual(out[1], 50)
        self.assertEqual(out[0]["unit_usd"], 50)

    def test_a_refused_choice_changes_nothing(self):
        out = run_js('import * as U from "./unitsize.js";\n'
                     'globalThis.window = {localStorage: {getItem: () => null, setItem() {}}, dispatchEvent() {}};\n'
                     'const r = await U.chooseSizing({mode: "fixed", unit_usd: 5000});\n'
                     "console.log(JSON.stringify([r, U.getSizing().unit_usd]));")
        self.assertEqual(out, [None, 25])


class TheReplayAndTheHeadstoneCarryTheBetList(unittest.TestCase):
    """The two payloads that are not a live bankroll block still let a page price their bets at the viewer's sizing."""

    PICKS = [{"date": "2026-10-01", "game": "A @ B", "market": "h2h", "selection": "A", "result": "WIN", "units_average_price": 1.2,
              "units_best_price": 1.3, "stake_units": 2.0, "price_average": 120},
             {"date": "2026-10-02", "game": "C @ D", "market": "h2h", "selection": "C", "result": "LOSS", "units_average_price": -1.0,
              "units_best_price": -1.0, "price_average": -110},
             {"date": "2026-10-03", "game": "E @ F", "market": "h2h", "selection": "E", "result": None, "units_average_price": None,
              "units_best_price": None, "price_average": 100}]

    def test_a_backtest_result_carries_events_and_each_graded_pick_knows_its_place_in_them(self):
        from src.hounds.interact import drill
        out = drill._summary([dict(p) for p in self.PICKS])
        self.assertEqual(out["bankroll"]["events"], [["2026-10-01", None, 2.4, 2.0, "w"], ["2026-10-02", None, -1.0, 1.0, "l"]])
        self.assertEqual([p.get("ev") for p in out["picks"]], [None, 1, 0])          # newest first; the pending pick has none
        self.assertEqual(out["best"][0]["ev"], 0)

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_backtest_page_prices_a_pick_at_the_viewers_sizing(self):
        from src.hounds.interact import drill
        out = drill._summary([dict(p) for p in self.PICKS])
        ref = out["bankroll"]
        got = run_js('import * as B from "./dog-backtest.js";\nimport * as U from "./unitsize.js";\n'
                     'globalThis.window = {localStorage: {getItem: () => JSON.stringify({mode: "percent", unit_usd: null, pct: 2, start_usd: 5000}), setItem() {}}};\n'
                     f"const ref = {json.dumps(ref)};\nconst picks = {json.dumps(out['picks'])};\n"
                     "console.log(JSON.stringify(picks.map((p) => B.pickUsd(p, ref))));")
        # 2% of $5,000 = $100 a unit on day 1 (2.4u won = +$240); day 2's balance is $5,240, so a lost unit is $104.80
        self.assertEqual(got, [None, -104.8, 240.0])

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_a_headstone_is_shown_at_the_viewers_unit_size_and_an_old_one_has_no_percent_dollars(self):
        events = [["2026-10-01", None, 1.0, 1.0, "w"], ["2026-10-02", None, 1.0, 1.0, "w"]]
        stone = {"start": 1000.0, "final": 1020.0, "pnl_usd": 20.0, "return_pct": 2.0, "unit_usd": 10.0, "events": events}
        old = {"start": 1000.0, "final": 1020.0, "pnl_usd": 20.0, "return_pct": 2.0}

        def text(box, viewer):
            return run_js('import * as H from "./dog-headstone.js";\n'
                          f"globalThis.window = {{localStorage: {{getItem: () => {json.dumps(json.dumps(viewer))}, setItem() {{}}}}}};\n"
                          f"console.log(JSON.stringify(H.finalBankrollText({json.dumps(box)})));")
        self.assertEqual(text(stone, {"mode": "fixed", "unit_usd": 50, "pct": None, "start_usd": 5000}), "$5,100 (+2.0%)")
        self.assertEqual(text(old, {"mode": "fixed", "unit_usd": 50, "pct": None, "start_usd": 5000}), "$5,100 (+2.0%)")
        self.assertEqual(text(old, {"mode": "percent", "unit_usd": None, "pct": 2, "start_usd": 5000}), "n/a")
        self.assertEqual(text(stone, {"mode": "percent", "unit_usd": None, "pct": 2, "start_usd": 5000}), "$5,202 (+4.0%)")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheAccountEndpoint(unittest.TestCase):
    def setUp(self):
        from api import hounds_kennels as api
        self.api = api
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        p = mock.patch.object(users_store, "db_path", lambda: self.db)
        p.start()
        self.addCleanup(p.stop)
        self.jacob = users_store.create_user("jacob.private@example.com", status="active", db=self.db)
        self.sam = users_store.create_user("sam.private@example.com", status="active", db=self.db)

    def get(self, user):
        return self.api.my_unit_size(Response(), current_user=user, _rl=None)

    def put(self, user, **body):
        return self.api.put_my_unit_size(self.api.UnitSizeRequest(**body), Response(), current_user=user, _rl=None)

    def refused(self, user, **body):
        with self.assertRaises(HTTPException) as ctx:
            self.put(user, **body)
        return ctx.exception

    def test_a_new_member_reads_the_25_dollar_default(self):
        out = self.get(self.jacob)
        self.assertEqual(out["sizing"], us.default_sizing().as_dict())
        self.assertIn("chips", out["choices"]["fixed"])
        self.assertTrue(out["paper_only"])

    def test_fixed_round_trip(self):
        out = self.put(self.jacob, mode="fixed", unit_usd=50)
        self.assertEqual((out["sizing"]["mode"], out["sizing"]["unit_usd"], out["sizing"]["start_usd"]), ("fixed", 50.0, 5000.0))
        self.assertEqual(self.get(self.jacob)["sizing"], out["sizing"])

    def test_percent_round_trip_and_a_later_write_replaces_it(self):
        self.put(self.jacob, mode="percent", pct=2, start_usd=5000)
        self.assertEqual(self.get(self.jacob)["sizing"], {"mode": "percent", "unit_usd": None, "pct": 2.0, "start_usd": 5000.0})
        self.put(self.jacob, mode="fixed", unit_usd=100)
        self.assertEqual(self.get(self.jacob)["sizing"]["unit_usd"], 100.0)

    def test_one_member_never_sees_anothers_choice(self):
        self.put(self.jacob, mode="fixed", unit_usd=100)
        self.assertEqual(self.get(self.sam)["sizing"]["unit_usd"], 25.0)

    def test_refusals_carry_a_code_and_store_nothing(self):
        for body, code in (({"mode": "fixed", "unit_usd": 0}, "unit_usd"), ({"mode": "fixed", "unit_usd": 1001}, "unit_usd"),
                           ({"mode": "fixed", "unit_usd": 12.5}, "unit_usd"), ({"mode": "fixed", "unit_usd": "25"}, "unit_usd"),
                           ({"mode": "percent", "pct": 7, "start_usd": 5000}, "pct"),
                           ({"mode": "percent", "pct": 2, "start_usd": 50}, "start_usd"),
                           ({"mode": "nonsense"}, "sizing_mode"), ({}, "sizing_mode")):
            with self.subTest(body=body):
                exc = self.refused(self.jacob, **body)
                self.assertEqual((exc.status_code, exc.detail["error"]), (422, code))
        self.assertEqual(self.get(self.jacob)["sizing"]["unit_usd"], 25.0)

    def test_the_routes_need_a_signed_in_member(self):
        deps = {}
        for route in self.api.router.routes:
            if getattr(route, "path", "") == "/me/unit-size":
                deps[tuple(sorted(route.methods))] = [(getattr(d, "call", None) or d.dependency).__name__
                                                      for d in route.dependant.dependencies]
        self.assertIn("get_current_user", deps[("GET",)])
        self.assertIn("get_current_user", deps[("PUT",)])

    def test_the_choice_is_private_not_in_any_public_profile_table(self):
        self.put(self.jacob, mode="fixed", unit_usd=100)
        from src.hounds import member_profile
        self.assertNotIn("100", json.dumps(member_profile.get(self.jacob.id)))


if __name__ == "__main__":
    unittest.main()
