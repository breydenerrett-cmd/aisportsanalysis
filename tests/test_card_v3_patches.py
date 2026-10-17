"""Card V3 patches: the behaviour each patch in `docs/decisions/card_v3/` buys.

WHY THIS FILE EXISTS AND WHY MOST OF IT IS `expectedFailure`
-------------------------------------------------------------
`docs/decisions/card_v3/` holds patches against files the V2 registration
fingerprints (`src/analysis/playerprops.py`, `propboard.py`,
`best_bets_card.py`, `card_v2.py`, `card_ledger.py`; PREREG_CARD_V2 11.2 and
section 10). A fingerprint change restarts the counted V2 sample, so the
patches are NOT applied to the committed tree; they are meant for the V3
successor registration (`docs/PREREG_CARD_V3.md`).

Each test below states a behaviour the loss diagnosis
(`docs/research/loss_diagnosis/`) showed is missing from today's code. It
FAILS on today's code, which is the proof it tests the defect, and it PASSES
with the matching patch applied. Until then it is marked `expectedFailure` so
the suite stays green.

TO APPLY A PATCH (V3 only): `git apply docs/decisions/card_v3/<name>.patch`,
then run this file with `CARD_V3_PATCHES_APPLIED=<name>[,<name>...]` (or
`all`) in the environment so the matching tests run as ordinary tests and a
real regression fails the suite; then delete the `pending` decorator on those
tests in the same commit. The patch names are: tb, avg, stale, mlfill,
withdrawn.

A test that passes on today's code AND with the patch (no `pending`) is a
guard on behaviour the patch must not move.
"""

from __future__ import annotations

import os
import unittest

from src.analysis import playerprops


def _applied(name: str) -> bool:
    raw = os.environ.get("CARD_V3_PATCHES_APPLIED", "")
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return "all" in parts or name in parts


def pending(name: str):
    """`expectedFailure` until the named patch is applied (see module doc)."""

    def deco(fn):
        return fn if _applied(name) else unittest.expectedFailure(fn)

    return deco


# ---------------------------------------------------------------------------
# Patch 1: tb_correction.patch
# ---------------------------------------------------------------------------

def _line(pa=4, h=1, doubles=0, triples=0, hr=0, r=0, rbi=0):
    return {"pa": pa, "h": h, "doubles": doubles, "triples": triples,
            "hr": hr, "r": r, "rbi": rbi, "hits_runs_rbi": h + r + rbi}


LEAGUE = {"pa": 100000, "hit": 0.22, "single": 0.15, "double": 0.045,
          "triple": 0.005, "home_run": 0.02, "run": 0.12, "rbi": 0.115}


class TotalBasesOverHalfIsTheHitsEvent(unittest.TestCase):
    """TB >= 1 and H >= 1 are one event. Hits over 0.5 gets the within-game
    correlation (rho) correction; total bases over 0.5 did not, so the card
    priced one event two ways on the same plate appearances. The loss
    diagnosis measured the gap at +2.95 points on 1,163 identical player-games
    (01_estimate_error.md section 3d); `scripts/diagnosis/card_v3_measure.py
    tb` measures the patch on 2024 and on the 2026 forward bets."""

    def setUp(self):
        self.rates = playerprops.batter_rates(
            [_line(pa=4, h=1, doubles=(1 if i % 3 == 0 else 0)) for i in range(100)],
            LEAGUE)

    @pending("tb")
    def test_tb_over_half_equals_hits_over_half_on_identical_inputs(self):
        for pa in (3.2, 4.0, 4.37):
            tb = playerprops.probability_over(
                "batter_total_bases", 0.5, self.rates, pa)
            hits = playerprops.probability_over(
                "batter_hits", 0.5, self.rates, pa)
            self.assertAlmostEqual(tb, hits, places=12,
                                   msg=f"pa={pa}: TB 0.5 {tb:.4f} vs hits 0.5 {hits:.4f}")

    @pending("tb")
    def test_the_equality_holds_through_the_pitcher_factor_and_a_frozen_rho(self):
        """The V2 card passes a frozen rho and a blended pitcher factor; the
        corrected path must honour both, not only the module defaults."""
        for factor, rho in ((1.0, 0.05885), (0.9, 0.05885), (1.12, 0.0)):
            tb = playerprops.probability_over(
                "batter_total_bases", 0.5, self.rates, 4.2, factor, rho=rho)
            hits = playerprops.probability_over(
                "batter_hits", 0.5, self.rates, 4.2, factor, rho=rho)
            self.assertAlmostEqual(tb, hits, places=12)

    @pending("tb")
    def test_price_prop_agrees_end_to_end(self):
        """Through `price_prop`, the entry point the prop board and the card
        use, so a future refactor of `probability_over` cannot hide it."""
        lines = [_line(pa=4, h=1) for _ in range(80)]
        tb = playerprops.price_prop(market="batter_total_bases", line=0.5,
                                    batter_lines=lines, league=LEAGUE,
                                    batting_slot=4)["probability"]
        hits = playerprops.price_prop(market="batter_hits", line=0.5,
                                      batter_lines=lines, league=LEAGUE,
                                      batting_slot=4)["probability"]
        self.assertAlmostEqual(tb, hits, places=12)

    def test_tb_over_1_5_is_not_moved_by_the_patch(self):
        """Guard (passes before AND after): the patch is about the at-least-
        one event only. Over 1.5 stays on the convolution."""
        direct = sum(playerprops.total_bases_distribution(self.rates, 4.2)[2:])
        self.assertAlmostEqual(
            direct,
            playerprops.probability_over("batter_total_bases", 1.5,
                                         self.rates, 4.2),
            places=12)

    def test_hits_over_half_is_not_moved_by_the_patch(self):
        """Guard: the corrected path itself is unchanged. It is the number
        every hits-over-0.5 bet in the V2 ledger was priced with."""
        a = playerprops.probability_over("batter_hits", 0.5, self.rates, 4.2)
        b = playerprops._at_least(self.rates["hit"], 4.2, 1, None)
        self.assertAlmostEqual(a, b, places=12)


# ---------------------------------------------------------------------------
# Patch 2: grade_average_odds.patch
# ---------------------------------------------------------------------------

import tempfile  # noqa: E402

from src.analysis import propboard  # noqa: E402
from src.appstate import card_ledger as cl  # noqa: E402
from src.core import odds as odds_math  # noqa: E402
from tests._card_v2_fixtures import (  # noqa: E402
    game_entry, prop_entry, result_row, select_result)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")


class PropBoardAverage(unittest.TestCase):
    """`propboard.average_decimal`: the mean decimal price over the SAME books
    `fair_and_best` took its best price from."""

    BOOKS = {
        "a": {"Over": -110, "Under": -110},
        "b": {"Over": -125, "Under": 105},
        "c": {"Over": 100, "Under": -120},
        "oneway": {"Over": 150},                      # no Under: not on a two-way board
        "juiceless": {"Over": 150, "Under": 150},    # booksum < 0.98: not a real market
    }

    @pending("avg")
    def test_it_is_the_mean_decimal_of_the_two_way_books_only(self):
        want = sum(odds_math.american_to_decimal(p) for p in (-110, -125, 100)) / 3
        self.assertAlmostEqual(
            want, propboard.average_decimal(self.BOOKS, "Over"), places=9)

    @pending("avg")
    def test_the_best_price_is_the_maximum_of_the_same_set(self):
        _fair, best = propboard.fair_and_best(self.BOOKS)
        avg = propboard.average_decimal(self.BOOKS, "Over")
        self.assertLess(avg, best["Over"][1])
        self.assertEqual(2.0, best["Over"][1], "the +100 book is the best Over")

    @pending("avg")
    def test_a_board_fair_and_best_would_refuse_has_no_average(self):
        thin = {"a": self.BOOKS["a"]}
        self.assertEqual((None, {}), propboard.fair_and_best(thin))
        self.assertIsNone(propboard.average_decimal(thin, "Over"))


class SettlementGradesAtAverageOdds(LedgerCase):
    """The owner's 2026-09-21 ruling: picks are graded at AVERAGE odds. The
    best recorded price stays as a second field."""

    FP = "2026-09-20T23:00:00Z"
    LOCKED = "2026-09-20T19:00:00Z"

    def _settle(self, entry, home, away=1, **kw):
        cl.publish_v2(select_result(picks=[entry]), now=self.LOCKED, path=self.path)
        return cl.settle_v2("2026-09-20", {entry["game_pk"]: result_row(away, home)},
                            path=self.path, **kw)["graded"][0]

    def _entry(self, **kw):
        e = game_entry(game_pk=1, price=-110, first_pitch_utc=self.FP,
                       observed_utc=self.LOCKED)
        e.update(kw)
        return e

    @pending("avg")
    def test_a_win_pays_the_average_not_the_best_price(self):
        g = self._settle(self._entry(average_decimal=1.80), home=5)
        self.assertEqual("WIN", g["result"])
        self.assertAlmostEqual(0.80, g["profit_units"], places=4)
        self.assertAlmostEqual(0.9091, g["profit_units_at_best"], places=4)
        self.assertEqual("average", g["graded_price_basis"])

    @pending("avg")
    def test_the_best_price_stays_on_the_entry(self):
        g = self._settle(self._entry(average_decimal=1.80), home=5)
        self.assertEqual(-110, g["price"])
        self.assertEqual(1.80, g["average_decimal"])

    @pending("avg")
    def test_a_loss_is_minus_one_either_way_and_still_labelled(self):
        g = self._settle(self._entry(average_decimal=1.80), home=0)
        self.assertEqual("LOSS", g["result"])
        self.assertEqual(-1.0, g["profit_units"])
        self.assertEqual(-1.0, g["profit_units_at_best"])
        self.assertEqual("average", g["graded_price_basis"])

    @pending("avg")
    def test_no_recorded_average_is_graded_at_best_and_says_so(self):
        """Never a guessed average: an entry frozen without one (all 178 on
        today's ledger) keeps the best-price grade and the label names it."""
        g = self._settle(self._entry(), home=5)
        self.assertAlmostEqual(0.9091, g["profit_units"], places=4)
        self.assertEqual("best_price_no_average_recorded", g["graded_price_basis"])

    @pending("avg")
    def test_an_unusable_average_is_ignored(self):
        for i, bad in enumerate((0.9, 1.0, "x", True)):
            with self.subTest(bad=bad):
                self.path = os.path.join(self._tmp.name, f"cards_v2_{i}.jsonl")
                g = self._settle(self._entry(average_decimal=bad), home=5)
                self.assertEqual("best_price_no_average_recorded", g["graded_price_basis"])

    @pending("avg")
    def test_the_record_reads_the_average_profit(self):
        self._settle(self._entry(average_decimal=1.80), home=5)
        rec = cl.record_v2(path=self.path)
        self.assertAlmostEqual(0.80, rec["main"]["profit_units"], places=4)

    @pending("avg")
    def test_a_prop_is_graded_the_same_way(self):
        p = prop_entry(game_pk=7, price=-115, side="over", line=0.5, market="batter_hits",
                       first_pitch_utc=self.FP, observed_utc=self.LOCKED)
        p["average_decimal"] = 1.82
        cl.publish_v2(select_result(prop_picks=[p]), now=self.LOCKED, path=self.path)
        box = [{"type": "batter", "game_pk": 7, "player_name": "Devers", "h": 2}]
        g = cl.settle_v2("2026-09-20", {}, prop_box_rows=box, path=self.path)["graded"][0]
        self.assertEqual("WIN", g["result"])
        self.assertAlmostEqual(0.82, g["profit_units"], places=4)
        self.assertAlmostEqual(0.8696, g["profit_units_at_best"], places=4)

    def test_a_push_or_void_is_untouched(self):
        """Guard: nothing to re-price on a refunded stake (passes before AND
        after)."""
        e = self._entry(average_decimal=1.80, side="sideways")
        g = self._settle(e, home=5)
        self.assertEqual(0.0, g["profit_units"])
        self.assertNotIn("graded_price_basis", g)


class TheAverageReachesTheCandidate(unittest.TestCase):
    """The ledger can only grade at an average it was handed: the board has to
    compute it and every hop to the V2 candidate has to carry it."""

    @staticmethod
    def _prop_rows(date="2026-09-20"):
        rows = []
        for book, over, under in (("a", -110, -110), ("b", -125, 105), ("c", 100, -120)):
            for side, price in (("Over", over), ("Under", under)):
                rows.append({"game_date": date, "event_id": "e1", "player": "Devers",
                             "market": "batter_hits", "line": 0.5, "side": side,
                             "book": book, "price": price,
                             "observed_utc": date + "T18:00:00Z"})
        return rows

    @pending("avg")
    def test_the_prop_board_contract_carries_the_average(self):
        prior = [dict(_line(pa=4, h=1), date="2026-09-%02d" % d, type="batter",
                      player_name="Devers", team_name="Boston Red Sox")
                 for d in range(1, 19)]
        board = propboard.build(self._prop_rows(), date="2026-09-20",
                                batters_by_name={"Devers": prior}, league=LEAGUE)
        over = [c for c in board["contracts"] if c["side"] == "Over"][0]
        want = sum(odds_math.american_to_decimal(p) for p in (-110, -125, 100)) / 3
        self.assertAlmostEqual(want, over["average_decimal"], places=4)
        self.assertEqual(100, over["price"], "the recorded best price is unchanged")

    @pending("avg")
    def test_the_prop_transport_keeps_the_average(self):
        from src.report import props
        self.assertEqual(1.8, props._public({"average_decimal": 1.8})["average_decimal"])

    @pending("avg")
    def test_the_moneyline_snapshot_carries_the_average(self):
        from src.analysis import prices
        quotes = [{"book": b, "away_price": a, "home_price": h} for b, a, h in (
            ("b1", 120, -140), ("b2", 115, -135), ("b3", 125, -145),
            ("b4", 110, -130), ("b5", 118, -138), ("b6", 122, -142))]
        snap = prices.snapshot(quotes)
        want = sum(odds_math.american_to_decimal(q["home_price"]) for q in quotes) / 6
        self.assertAlmostEqual(want, snap["sides"]["home"]["average_decimal"], places=4)
        self.assertEqual(-130, snap["sides"]["home"]["best_price"])


# ---------------------------------------------------------------------------
# Patch 3: stale_board_real.patch
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from src.analysis import best_bets_card  # noqa: E402

NOW = datetime(2026, 10, 5, 5, 15, tzinfo=timezone.utc)


def _cand(i=1, age=60, **over):
    base = dict(game_id=f"G{i}", price=-140, market_probability=0.55,
                our_probability=0.65, books=8,
                observed_utc=None if age is None else NOW - timedelta(seconds=age),
                has_started=False, calibrated=True, bet_sentence="x",
                first_pitch="2026-10-05T23:00:00Z")
    base.update(over)
    return base


class StaleBoardIsComputedFromTheQuoteAgesG3Used(unittest.TestCase):
    """`select()` hard-coded `stale_board: None` (best_bets_card.py ~616), so
    a run on which every candidate failed G3 recorded "no stale board". The
    registration (PREREG_CARD_V2 section 6) defines it: no quote on the
    newest board within the freshness threshold (G3's 3,600 s) of the publish
    instant."""

    def _select(self, cands):
        return best_bets_card.select(cands, now=NOW, params=best_bets_card.V2)

    @pending("stale")
    def test_a_board_where_every_quote_is_older_than_an_hour_is_stale(self):
        out = self._select([_cand(1, age=7200), _cand(2, age=9000)])
        self.assertIsNotNone(out["stale_board"])
        self.assertEqual(7200.0, out["stale_board"]["age_seconds"],
                         "the age read from the board is the NEWEST quote's")
        self.assertEqual(3600, out["stale_board"]["threshold_seconds"])
        self.assertEqual(2, out["stale_board"]["n_quotes"])

    @pending("stale")
    def test_the_threshold_is_g3s_exactly(self):
        """3,600 s passes G3 (it fails above it), so it is a fresh board;
        3,601 s fails G3 on every candidate, so it is a stale one."""
        fresh = self._select([_cand(1, age=3600)])
        self.assertEqual([], fresh["picks"][0]["failed_gates"] if fresh["picks"] else [])
        self.assertIsNone(fresh["stale_board"])
        stale = self._select([_cand(1, age=3601)])
        self.assertIsNotNone(stale["stale_board"])

    @pending("stale")
    def test_stale_board_agrees_with_g3_on_every_candidate(self):
        for ages in ([7200, 8000], [7200, 60], [3601, 3601, 3601], [60, 30]):
            with self.subTest(ages=ages):
                cands = [_cand(i, age=a) for i, a in enumerate(ages)]
                g3_all_fail = all(
                    best_bets_card.G3_STALE in best_bets_card.failed_gates(
                        c, now=NOW, params=best_bets_card.V2) for c in cands)
                out = self._select(cands)
                self.assertEqual(g3_all_fail, out["stale_board"] is not None)

    @pending("stale")
    def test_candidates_with_no_observed_time_make_a_stale_board_with_no_age(self):
        out = self._select([_cand(1, age=None), _cand(2, age=None)])
        self.assertIsNotNone(out["stale_board"])
        self.assertIsNone(out["stale_board"]["age_seconds"])
        self.assertEqual(2, out["stale_board"]["n_unparseable"])

    def test_one_fresh_quote_keeps_the_board_fresh(self):
        """Guard (passes before AND after): the registration's test is "no
        quote within the threshold", not "some quote is old"."""
        out = self._select([_cand(1, age=7200), _cand(2, age=120)])
        self.assertIsNone(out["stale_board"])

    def test_an_empty_pool_is_not_a_stale_board(self):
        """Guard: no board at all is `raw_pool_size == 0`, which the report
        layer words differently; it must not be reported as stale."""
        self.assertIsNone(self._select([])["stale_board"])


if __name__ == "__main__":
    unittest.main()
