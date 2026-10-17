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


# ---------------------------------------------------------------------------
# Patch 4: ml_fill_lock_price.patch
# ---------------------------------------------------------------------------

class MoneylineFillsLockOnTheBoardAtLock(LedgerCase):
    """Registration L3 locked an entry "as last published", and a fill may be
    added on a stale quote, so a fill added on the 04:00Z baseline locked at
    that morning price. 11 of the 20 graded moneylines with a newer capture
    before `locked_at` were graded at a price no longer on any book (loss
    diagnosis 03 section 4; a Dodgers fill graded -147 with -212 the best at
    lock)."""

    FP = "2026-09-20T23:00:00Z"
    SHOWN = "2026-09-20T10:00:00Z"      # provisional publish, outside the window
    LOCK_RUN = "2026-09-20T19:30:00Z"   # first run inside T-4h

    def _fill(self, price, observed, **kw):
        e = game_entry(game_pk=1, price=price, entry_class="fill",
                       failed_gates=["G7_VALUE"], first_pitch_utc=self.FP,
                       observed_utc=observed)
        e.update(kw)
        return e

    def _publish_shown(self, price=-128):
        cl.publish_v2(select_result(fills=[self._fill(price, self.SHOWN)]),
                      now=self.SHOWN, path=self.path)

    def _lock_run(self, fresh_fills):
        return cl.publish_v2(select_result(fills=fresh_fills), now=self.LOCK_RUN,
                             path=self.path)

    @pending("mlfill")
    def test_the_fill_locks_on_the_price_that_was_on_the_board_at_lock(self):
        self._publish_shown(-128)
        row = self._lock_run([self._fill(-135, "2026-09-20T19:25:00Z",
                                         average_decimal=1.72)])
        fill = row["fills"][0]
        self.assertTrue(fill["locked"])
        self.assertEqual(-135, fill["price"])
        self.assertEqual("2026-09-20T19:25:00Z", fill["observed_utc"])
        self.assertEqual(-128, fill["price_when_shown"])
        self.assertEqual("board_at_lock", fill["lock_price_basis"])

    @pending("mlfill")
    @pending("avg")
    def test_the_average_price_moves_with_the_best_price(self):
        """Needs patch 2 too (the field is frozen there): a fill locked on the
        lock-time board must carry that board's average, not the morning's."""
        self._publish_shown(-128)
        row = self._lock_run([self._fill(-135, "2026-09-20T19:25:00Z",
                                         average_decimal=1.72)])
        self.assertEqual(1.72, row["fills"][0]["average_decimal"])

    @pending("mlfill")
    def test_it_is_graded_at_the_lock_price(self):
        self._publish_shown(-128)
        self._lock_run([self._fill(-135, "2026-09-20T19:25:00Z")])
        g = cl.settle_v2("2026-09-20", {1: result_row(1, 5)}, path=self.path)["graded"][0]
        self.assertEqual("WIN", g["result"])
        self.assertAlmostEqual(0.7407, g["profit_units"], places=4)   # -135, not -128

    @pending("mlfill")
    def test_no_read_at_the_locking_run_locks_as_published_and_says_so(self):
        """The ledger cannot know why the candidate is absent, so it keeps the
        shown price and labels it unverified rather than guessing."""
        self._publish_shown(-128)
        row = self._lock_run([])
        fill = row["fills"][0]
        self.assertTrue(fill["locked"])
        self.assertEqual(-128, fill["price"])
        self.assertEqual("last_published_no_read_at_lock", fill["lock_price_basis"])

    @pending("mlfill")
    def test_a_read_that_fails_a_hard_gate_withdraws_the_fill(self):
        """The registered band is -160..+250; a lock-time board at -212 has no
        in-band price, so the fill is withdrawn, not locked at a price nobody
        can take. It is still graded, labelled withdrawn, at its shown price."""
        self._publish_shown(-128)
        row = self._lock_run([self._fill(-212, "2026-09-20T19:25:00Z",
                                         failed_gates=["G4_BAND"])])
        self.assertEqual([], row["fills"])
        self.assertEqual(1, len(row["withdrawn"]))
        self.assertEqual(-128, row["withdrawn"][0]["price"])
        g = cl.settle_v2("2026-09-20", {1: result_row(5, 1)}, path=self.path)["graded"]
        self.assertTrue(g[0]["withdrawn"])

    def test_a_pick_still_locks_as_last_published(self):
        """Guard (passes before AND after): the patch is about fills. A
        provisional PICK keeps registration L3, even against a failing read
        (tests/test_card_v2_lock_and_withdraw.py pins the same)."""
        pick = game_entry(game_pk=1, price=-128, first_pitch_utc=self.FP,
                          observed_utc=self.SHOWN)
        cl.publish_v2(select_result(picks=[pick]), now=self.SHOWN, path=self.path)
        fresh = game_entry(game_pk=1, price=-135, first_pitch_utc=self.FP,
                           observed_utc="2026-09-20T19:25:00Z")
        row = cl.publish_v2(select_result(picks=[fresh]), now=self.LOCK_RUN, path=self.path)
        self.assertEqual(-128, row["picks"][0]["price"])
        self.assertTrue(row["picks"][0]["locked"])

    def test_a_prop_fill_is_untouched(self):
        """Guard: the capture store cannot say what a prop's board looked like
        at lock (no capture between the quote and the lock), so props are out
        of scope."""
        fill = prop_entry(game_pk=9, price=-120, entry_class="fill",
                          first_pitch_utc=self.FP, observed_utc=self.SHOWN)
        cl.publish_v2(select_result(fills=[fill]), now=self.SHOWN, path=self.path)
        fresh = dict(fill, price=-130, observed_utc="2026-09-20T19:25:00Z")
        row = cl.publish_v2(select_result(fills=[fresh]), now=self.LOCK_RUN, path=self.path)
        self.assertEqual(-120, row["fills"][0]["price"])
        self.assertNotIn("lock_price_basis", row["fills"][0])


# ---------------------------------------------------------------------------
# Patch 5: withdrawn_label.patch
# ---------------------------------------------------------------------------

class WithdrawnPicksAreReportedAndLabelled(LedgerCase):
    """A withdrawn pick was shown to readers and is graded. `settle_v2` sums
    it into the per-day totals (97-81 on the 178 entries) while `record_v2`
    leaves it out of every figure (86-75) and reported only a COUNT (19), so
    one ledger said two records with no label (loss diagnosis 02 section 0)."""

    def _day_with_one_kept_and_one_withdrawn(self):
        fp = "2026-09-20T23:00:00Z"
        kept = game_entry(game_pk=1, price=-140, first_pitch_utc=fp,
                          observed_utc="2026-09-20T10:00:00Z")
        gone = game_entry(game_pk=2, price=-140, first_pitch_utc=fp,
                          observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[kept, gone]), now="2026-09-20T10:00:00Z",
                      path=self.path)
        # the 11:00Z read still passes game 1 and now fails game 2: withdrawn
        k2 = game_entry(game_pk=1, price=-140, first_pitch_utc=fp,
                        observed_utc="2026-09-20T11:00:00Z")
        g2 = game_entry(game_pk=2, price=-140, first_pitch_utc=fp,
                        observed_utc="2026-09-20T11:00:00Z", failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=[k2, g2]), now="2026-09-20T11:00:00Z",
                            path=self.path)
        self.assertEqual(1, len(row["withdrawn"]))
        # game 1 LOSES (home 0), the withdrawn game 2 WINS (home 5)
        cl.settle_v2("2026-09-20", {1: result_row(1, 0), 2: result_row(1, 5)},
                     path=self.path)

    @pending("withdrawn")
    def test_record_v2_reports_how_the_withdrawn_picks_graded(self):
        self._day_with_one_kept_and_one_withdrawn()
        rec = cl.record_v2(path=self.path)
        wg = rec["withdrawn_graded"]
        self.assertEqual((1, 0, 1), (wg["wins"], wg["losses"], wg["n_staked"]))
        self.assertAlmostEqual(0.7143, wg["profit_units"], places=4)

    def test_the_withdrawn_pick_is_in_none_of_the_headline_figures(self):
        """Guard (passes before AND after): the patch ADDS the withdrawn
        figure; it must not move the headline ones."""
        self._day_with_one_kept_and_one_withdrawn()
        rec = cl.record_v2(path=self.path)
        self.assertEqual((0, 1), (rec["main"]["wins"], rec["main"]["losses"]))
        self.assertEqual((0, 1), (rec["combined"]["wins"], rec["combined"]["losses"]))

    @pending("withdrawn")
    def test_history_v2_days_say_their_totals_include_the_withdrawn(self):
        self._day_with_one_kept_and_one_withdrawn()
        day = cl.history_v2(path=self.path)["days"][0]
        self.assertTrue(day["totals_include_withdrawn"])
        self.assertEqual((1, 1), (day["wins"], day["losses"]))          # the old, pooled figure
        self.assertEqual((0, 1), (day["shown"]["wins"], day["shown"]["losses"]))
        self.assertEqual((1, 0), (day["withdrawn_graded"]["wins"], day["withdrawn_graded"]["losses"]))

    @pending("withdrawn")
    def test_shown_plus_withdrawn_is_the_pooled_total(self):
        self._day_with_one_kept_and_one_withdrawn()
        day = cl.history_v2(path=self.path)["days"][0]
        self.assertAlmostEqual(
            day["profit_units"],
            day["shown"]["profit_units"] + day["withdrawn_graded"]["profit_units"], places=4)

    def test_the_withdrawn_count_is_still_a_bare_int(self):
        """Guard (passes before AND after): `record_v2()["withdrawn"]` is read
        as a count by `effective_record`; the patch adds a key beside it."""
        self._day_with_one_kept_and_one_withdrawn()
        self.assertEqual(1, cl.record_v2(path=self.path)["withdrawn"])

    def test_the_stored_settled_row_is_not_rewritten(self):
        """Guard: the ledger is hash-chained; the label is added by the
        readers, so the written row keeps its original keys."""
        self._day_with_one_kept_and_one_withdrawn()
        row = cl.settled_row("2026-09-20", path=self.path)
        self.assertNotIn("totals_include_withdrawn", row)
        self.assertEqual(1, row["wins"])


if __name__ == "__main__":
    unittest.main()
