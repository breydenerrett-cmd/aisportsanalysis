"""Closing-line measurement for V2 picks (build plan T4).

Every index here is a plain hand-built dict shaped like
`clv.pregame_index()`'s own return -- `{event_id: {"rows": [...],
"commence_time": iso}}` -- and this file never opens
`data/processed/odds_multibook.jsonl`: `measure_pick`/`measure_ledger` never
read a store themselves, only the `index` they are handed.

The worked arithmetic (price -112, needs 0.5283, p_close 0.53 -> clv_pct
+0.32%, clv_bps +17; p_lock 0.5126 -> consensus drift +3.39%) is registration
11.3's own example. American odds are integers, so the fixture board below
uses the closest integer price pair whose de-vigged home consensus lands
within 0.0001 of 0.5300 (103/-125 -> 0.530026...) rather than exactly 0.53,
and the assertions tolerate that same margin.
"""

from __future__ import annotations

import unittest

from src.report import card_clv


def _books(n, *, away_price=103, home_price=-125, observed_utc="2026-09-20T22:30:00Z",
           market=None, **line_fields):
    rows = []
    for i in range(n):
        row = {"observed_utc": observed_utc, "book": f"book{i}",
               "away_price": away_price, "home_price": home_price}
        if market is not None:
            row["market"] = market
        row.update(line_fields)
        rows.append(row)
    return rows


def _index(event_id, rows, commence_time="2026-09-20T23:05:00Z"):
    return {event_id: {"rows": rows, "commence_time": commence_time}}


def _pick(event_id="evt-1", market="moneyline", side="home", price=-112,
          observed_utc="2026-09-20T18:00:00Z", market_probability=0.5126,
          kind="game", line=None, entry_class="pick", price_class="MAIN"):
    return {
        "kind": kind, "event_id": event_id, "market": market, "side": side,
        "price": price, "observed_utc": observed_utc,
        "market_probability": market_probability, "line": line,
        "entry_class": entry_class, "price_class": price_class,
    }


class WorkedArithmetic(unittest.TestCase):
    def test_needs_clv_pct_clv_bps_and_consensus_drift_match_the_registration_example(self):
        index = _index("evt-1", _books(6))
        pick = _pick(price=-112, market_probability=0.5126)
        result = card_clv.measure_pick(pick, index)

        self.assertNotIn("absence", result)
        self.assertAlmostEqual(0.5283, result["needs"], places=4)
        self.assertAlmostEqual(0.0032, result["clv_pct"], delta=0.0002)
        self.assertAlmostEqual(17, result["clv_bps"], delta=1.0)
        self.assertTrue(result["beats_close"])
        self.assertAlmostEqual(0.0339, result["consensus_drift_pct"], delta=0.0005)

    def test_entry_class_and_price_class_are_carried_through_unchanged(self):
        index = _index("evt-1", _books(6))
        pick = _pick(entry_class="fill", price_class="PLUS_MONEY")
        result = card_clv.measure_pick(pick, index)
        self.assertEqual("fill", result["entry_class"])
        self.assertEqual("PLUS_MONEY", result["price_class"])


class ClosingBoardThin(unittest.TestCase):
    def test_a_newer_five_book_capture_yields_closing_board_thin_never_an_older_six_book_one(self):
        old_six = _books(6, observed_utc="2026-09-20T20:00:00Z")
        new_five = _books(5, observed_utc="2026-09-20T22:30:00Z")
        index = _index("evt-1", old_six + new_five)
        result = card_clv.measure_pick(_pick(), index)
        self.assertEqual("CLOSING_BOARD_THIN", result["absence"])


class OtherAbsenceReasons(unittest.TestCase):
    def test_no_event_when_the_index_has_no_capture_for_this_event(self):
        result = card_clv.measure_pick(_pick(event_id="evt-missing"), _index("evt-1", _books(6)))
        self.assertEqual("NO_EVENT", result["absence"])

    def test_no_market_for_an_undeclared_market_key(self):
        pick = _pick(market="totals")
        result = card_clv.measure_pick(pick, _index("evt-1", _books(6)))
        self.assertEqual("NO_MARKET", result["absence"])

    def test_close_stale_when_the_capture_is_far_before_first_pitch(self):
        # lead = commence - observed; make it > 5400s (90 minutes).
        rows = _books(6, observed_utc="2026-09-20T18:00:00Z")
        index = _index("evt-1", rows, commence_time="2026-09-20T23:05:00Z")
        result = card_clv.measure_pick(_pick(observed_utc="2026-09-20T10:00:00Z"), index)
        self.assertEqual("CLOSE_STALE", result["absence"])

    def test_closing_board_is_decision_board_when_the_pick_read_the_same_instant(self):
        same_instant = "2026-09-20T22:30:00Z"
        rows = _books(6, observed_utc=same_instant)
        index = _index("evt-1", rows)
        result = card_clv.measure_pick(_pick(observed_utc=same_instant), index)
        self.assertEqual("CLOSING_BOARD_IS_DECISION_BOARD", result["absence"])

    def test_close_precedes_decision_when_the_capture_is_older_than_the_pick(self):
        # lead must stay under CLOSE_STALE's 5400s so that check is not
        # the one that fires first.
        rows = _books(6, observed_utc="2026-09-20T21:50:00Z")
        index = _index("evt-1", rows, commence_time="2026-09-20T23:05:00Z")
        # The pick's own quote is NEWER than the closing capture.
        result = card_clv.measure_pick(_pick(observed_utc="2026-09-20T22:30:00Z"), index)
        self.assertEqual("CLOSE_PRECEDES_DECISION", result["absence"])


class RunLineMatchedOnSignAndLineExactly(unittest.TestCase):
    def test_a_run_line_reads_the_boards_own_line_field_at_the_signed_line(self):
        rows = _books(6, market="spreads", away_line=1.5, home_line=-1.5,
                     away_price=103, home_price=-125)
        index = _index("evt-1", rows)
        pick = _pick(market="run_line", side="home", line=-1.5)
        result = card_clv.measure_pick(pick, index)
        self.assertNotIn("absence", result)

    def test_a_run_line_at_a_different_number_finds_no_matching_quotes(self):
        rows = _books(6, market="spreads", away_line=1.5, home_line=-1.5)
        index = _index("evt-1", rows)
        pick = _pick(market="run_line", side="home", line=-2.5)
        result = card_clv.measure_pick(pick, index)
        self.assertEqual("CLOSING_BOARD_THIN", result["absence"])


class PropsNeverMeasured(unittest.TestCase):
    def test_a_prop_always_returns_prop_not_measured_even_with_six_books(self):
        rows = _books(6)
        index = _index("evt-2", rows)
        pick = _pick(event_id="evt-2", kind="prop")
        result = card_clv.measure_pick(pick, index)
        self.assertEqual("PROP_NOT_MEASURED", result["absence"])


class MeasureLedgerReadsAV2SettledRow(unittest.TestCase):
    def test_measure_ledger_covers_graded_and_withdrawn_entries(self):
        import os
        import tempfile
        from src.appstate import card_ledger as cl
        from tests._card_v2_fixtures import game_entry, select_result, result_row

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "cards_v2.jsonl")

        pick = game_entry(game_pk=1, price=-112, market_probability=0.5126,
                          observed_utc="2026-09-20T18:00:00Z", event_id="evt-1")
        cl.publish_v2(select_result(date="2026-09-20", picks=[pick]),
                     now="2026-09-20T18:00:00Z", path=path)
        cl.settle_v2("2026-09-20", {1: result_row(1, 5)}, path=path)

        index = _index("evt-1", _books(6))
        measurements = card_clv.measure_ledger(path, index)
        self.assertEqual(1, len(measurements))
        self.assertEqual("2026-09-20", measurements[0]["date"])
        self.assertFalse(measurements[0]["withdrawn"])
        self.assertIn("clv_bps", measurements[0])


if __name__ == "__main__":
    unittest.main()
