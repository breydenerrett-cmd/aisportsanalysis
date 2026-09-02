"""Tests for L18: extending the append-only closing backfill from h2h to
spreads and totals (`market=` on grading.find_backfillable_closings/
_backfill_row/read_backfills/effective_closing).

WHAT THIS PROVES
-----------------
1. h2h keeps its exact pre-L18 behaviour when `market` is omitted (or
   passed explicitly as "h2h") -- tests/test_closing_backfill.py already
   proves this for the no-argument call; this file adds the explicit-arg
   check.
2. Spreads and totals get their own backfill row per settled game, using
   the SAME derivation `ledger_closing_coverage`/`closing-audit` already
   use (`snapshots.market_closing_observation`), so a spreads/totals
   backfill row can never disagree with what closing-audit called
   derivable.
3. A spreads/totals backfill row records BOTH the line and the price per
   side (whatever the store captured), and NEVER computes a CLV number
   for a line market -- `clv_graded` is always False, with a `clv_reason`
   naming the missing fair-price model. This is a deliberate refusal to
   fabricate, not an oversight.
4. `read_backfills`/`effective_closing` are market-scoped: a spreads
   backfill is invisible to an h2h read and vice versa, and a settlement
   with no per-market `closing` field (true of every settlement for
   spreads/totals) is still handled correctly -- there is no non-null
   original to protect for those two markets.
5. A pre-L18 `closing_backfill` row (no `market` field on disk at all) is
   read as h2h, so the live ledger's L14-era rows keep working under the
   new market-scoped readers with no migration needed.
"""

import unittest
from datetime import datetime, timezone

from src.pipeline import grading, ledger


def snapshot_row(observed, market, prices, away="St. Louis Cardinals",
                 home="Los Angeles Dodgers", commence="2026-08-27T23:10:00Z",
                 book="fanduel"):
    """One odds_snapshots.jsonl row for `market`, shaped exactly like
    `snapshots.capture` writes it -- the odds feed's full club names, prices
    nested under `prices` (see tests/test_closing_backfill.py's identical
    h2h fixture and tests/test_closing_markets.py's spreads/totals ones)."""
    return {
        "observed_utc": observed, "commence_time": commence,
        "away_team": away, "home_team": home, "market": market,
        "book": book, "book_last_update": observed, "prices": prices,
    }


def recommendation(game_pk, away="STL", home="LAD", date="2026-08-27",
                   commence="2026-08-27T23:10:00Z", side="home", market=None,
                   home_price=-150, away_price=130):
    """One ledger recommendation row -- identical shape to
    tests/test_closing_backfill.py's fixture of the same name. This
    project has never flagged an actual spread/total recommendation, so
    `prices` here only ever carries an `h2h` quote, matching production."""
    return {
        "kind": ledger.RECOMMENDATION,
        "game_pk": game_pk, "away_team": away, "home_team": home,
        "date": date, "commence_time": commence, "side": side,
        "market": market, "verdict": "flagged" if market else "no_play",
        "prices": {"h2h": {"home_price": home_price, "away_price": away_price}},
    }


def settlement(game_pk, closing=None):
    """One ledger settlement row. `closing` is h2h-only in production --
    there has never been a per-market field for spreads/totals."""
    entry = {"kind": ledger.SETTLEMENT, "game_pk": game_pk,
             "settled_at": "2026-08-28T04:00:00+00:00",
             "result": {"home_won": 1}, "closing": closing}
    if closing is None:
        entry["closing_reason"] = "no closing price provided"
    return entry


class TestH2HDefaultAndExplicitMarketAgree(unittest.TestCase):
    def test_omitting_market_and_passing_h2h_explicitly_are_identical(self):
        entries = [recommendation(1), settlement(1, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "h2h",
                             {"home_price": -150, "away_price": 130})]

        fixed_now = datetime(2026, 9, 2, tzinfo=timezone.utc)
        implicit = grading.find_backfillable_closings(entries, rows, now=fixed_now)
        explicit = grading.find_backfillable_closings(entries, rows, market="h2h",
                                                       now=fixed_now)

        self.assertEqual(implicit["to_append"], explicit["to_append"])
        self.assertEqual(len(implicit["to_append"]), 1)
        self.assertEqual(implicit["to_append"][0]["market"], "h2h")


class TestSpreadsAndTotalsBackfill(unittest.TestCase):
    def test_spreads_close_is_derivable_and_recorded_with_line_and_price(self):
        entries = [recommendation(2), settlement(2, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "spreads",
                             {"home_line": -1.5, "home_price": 120,
                              "away_line": 1.5, "away_price": -140})]

        result = grading.find_backfillable_closings(entries, rows, market="spreads")

        self.assertEqual(len(result["to_append"]), 1)
        row = result["to_append"][0]
        self.assertEqual(row["kind"], "closing_backfill")
        self.assertEqual(row["ref"], 2)
        self.assertEqual(row["market"], "spreads")
        prices = row["closing_price"]["prices"]
        self.assertEqual(prices["home_line"], -1.5)
        self.assertEqual(prices["home_price"], 120)
        self.assertEqual(prices["away_line"], 1.5)
        self.assertEqual(prices["away_price"], -140)
        self.assertEqual(row["closing_source"], "odds_snapshots")
        self.assertEqual(row["reason"],
                         "market close not recorded at settlement (h2h-only writer)")

    def test_totals_close_is_derivable_and_recorded_with_line_and_price(self):
        entries = [recommendation(3), settlement(3, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "totals",
                             {"total": 8.5, "over_price": -110, "under_price": -110})]

        result = grading.find_backfillable_closings(entries, rows, market="totals")

        row = result["to_append"][0]
        self.assertEqual(row["market"], "totals")
        prices = row["closing_price"]["prices"]
        self.assertEqual(prices["total"], 8.5)
        self.assertEqual(prices["over_price"], -110)
        self.assertEqual(prices["under_price"], -110)

    def test_clv_is_never_computed_for_a_line_market_even_with_a_priced_side(self):
        # Even though a pick price CAN be read off the recommendation's h2h
        # quote, a spreads/totals close must never be diffed against it --
        # that would compare two different markets' prices as if they
        # quoted the same bet.
        entries = [recommendation(4, side="home", home_price=-150),
                  settlement(4, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "spreads",
                             {"home_line": -1.5, "home_price": -150,
                              "away_line": 1.5, "away_price": 130})]

        row = grading.find_backfillable_closings(entries, rows, market="spreads")["to_append"][0]

        self.assertFalse(row["clv"]["clv_graded"])
        self.assertEqual(row["clv"]["clv_reason"],
                         "line-market CLV needs a fair-price model this system does not have")
        self.assertIsNotNone(row["closing_price"])  # the close is still recorded

    def test_agrees_with_market_closing_observation_reason_strings(self):
        # not_captured / "no snapshot observed before first pitch" --
        # the same vocabulary closing-audit already uses, so the two
        # tools can never describe the same gap two different ways.
        entries = [recommendation(5), settlement(5, closing=None)]

        not_captured = grading.find_backfillable_closings(entries, [], market="totals")
        self.assertEqual(not_captured["not_derivable"][0]["reason"], "not_captured")

        late_row = [snapshot_row("2026-08-28T01:00:00+00:00", "totals",
                                 {"total": 8.5, "over_price": -110, "under_price": -110})]
        too_late = grading.find_backfillable_closings(entries, late_row, market="totals")
        self.assertEqual(too_late["not_derivable"][0]["reason"],
                         "no snapshot observed before first pitch")

    def test_a_settled_game_with_no_recommendation_is_reported_not_skipped(self):
        entries = [settlement(6, closing=None)]  # no recommendation row

        result = grading.find_backfillable_closings(entries, [], market="spreads")

        self.assertEqual(result["no_recommendation"], [6])
        self.assertEqual(result["to_append"], [])

    def test_a_second_run_for_the_same_market_appends_zero(self):
        entries = [recommendation(7), settlement(7, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "totals",
                             {"total": 8.5, "over_price": -110, "under_price": -110})]

        first = grading.find_backfillable_closings(entries, rows, market="totals")
        entries_after = entries + first["to_append"]

        second = grading.find_backfillable_closings(entries_after, rows, market="totals")
        self.assertEqual(second["to_append"], [])
        self.assertEqual(second["already_backfilled"], [7])

    def test_backfilling_one_market_does_not_satisfy_another(self):
        # Backfilling spreads for a game must leave totals (and h2h)
        # exactly as derivable as before -- markets are independent ledgers
        # of coverage, not one shared flag.
        entries = [recommendation(8), settlement(8, closing=None)]
        rows = [
            snapshot_row("2026-08-27T20:00:00+00:00", "spreads",
                        {"home_line": -1.5, "home_price": 120,
                         "away_line": 1.5, "away_price": -140}),
            snapshot_row("2026-08-27T20:00:00+00:00", "totals",
                        {"total": 8.5, "over_price": -110, "under_price": -110}),
        ]
        spreads_result = grading.find_backfillable_closings(entries, rows, market="spreads")
        entries_after_spreads = entries + spreads_result["to_append"]

        totals_result = grading.find_backfillable_closings(
            entries_after_spreads, rows, market="totals")
        self.assertEqual(len(totals_result["to_append"]), 1)
        self.assertEqual(totals_result["already_backfilled"], [])


class TestReaderPreferenceIsMarketScoped(unittest.TestCase):
    def test_a_spreads_backfill_is_invisible_to_an_h2h_read(self):
        entries = [recommendation(9), settlement(9, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "spreads",
                             {"home_line": -1.5, "home_price": 120,
                              "away_line": 1.5, "away_price": -140})]
        spreads_backfill = grading.find_backfillable_closings(
            entries, rows, market="spreads")["to_append"]
        entries_after = entries + spreads_backfill

        h2h_backfills = grading.read_backfills(entries_after, market="h2h")
        self.assertNotIn(9, h2h_backfills)

        spreads_backfills = grading.read_backfills(entries_after, market="spreads")
        self.assertIn(9, spreads_backfills)

    def test_effective_closing_for_a_line_market_reads_straight_from_backfill(self):
        # Spreads/totals settlements never carry a per-market `closing`
        # field of their own -- the backfill IS the only place either is
        # ever recorded, so there is no "original" to prefer over it.
        entries = [recommendation(10), settlement(10, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00", "totals",
                             {"total": 8.5, "over_price": -110, "under_price": -110})]
        totals_backfill = grading.find_backfillable_closings(
            entries, rows, market="totals")["to_append"]
        entries_after = entries + totals_backfill

        backfills = grading.read_backfills(entries_after, market="totals")
        effective = grading.effective_closing(
            settlement(10, closing=None), backfills, market="totals")

        self.assertIsNotNone(effective)
        self.assertEqual(effective["prices"]["total"], 8.5)

    def test_pre_l18_backfill_rows_with_no_market_field_read_as_h2h(self):
        # Every closing_backfill row written before L18 has no `market`
        # key at all. The market-scoped reader must still find it under
        # "h2h" without any migration of rows already on disk.
        legacy_row = {
            "kind": "closing_backfill", "ref": 11,
            "closing_price": {"prices": {"home_price": -150, "away_price": 130}},
            "closing_observed_utc": "a", "closing_source": "odds_snapshots",
            "derived_utc": "t1", "clv": None,
            "reason": "abbreviation join bug 65f499a",
        }
        entries = [recommendation(11), settlement(11, closing=None), legacy_row]

        h2h_backfills = grading.read_backfills(entries, market="h2h")
        self.assertIn(11, h2h_backfills)

        spreads_backfills = grading.read_backfills(entries, market="spreads")
        self.assertNotIn(11, spreads_backfills)


if __name__ == "__main__":
    unittest.main()
