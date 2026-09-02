"""Tests for the forward-ledger closing-price backfill (commit 65f499a
fixed the join; these rows repair the settlements written before the fix
without touching them -- see src/pipeline/grading.py's "Forward-ledger
closing-price backfill" section for the full rationale).

Every test here builds ledger `entries` and snapshot `rows` in memory --
never a real file -- except the append/idempotence/no-mutation tests,
which round-trip through a temp file the way `closing-backfill` actually
runs.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import grading, ledger, snapshots


def snapshot_row(observed, away="St. Louis Cardinals", home="Los Angeles Dodgers",
                 commence="2026-08-27T23:10:00Z", home_price=-150, away_price=130,
                 book="fanduel"):
    """One h2h snapshot row, shaped exactly like `snapshots.capture` writes
    it: the odds feed's full club names, not this project's abbreviations
    -- see tests/test_settlement_closing_join.py's identical fixture."""
    return {
        "observed_utc": observed, "commence_time": commence,
        "away_team": away, "home_team": home, "market": "h2h",
        "book": book, "book_last_update": observed,
        "prices": {"home_price": home_price, "away_price": away_price},
    }


def recommendation(game_pk, away="STL", home="LAD", date="2026-08-27",
                   commence="2026-08-27T23:10:00Z", side="home", market=None,
                   home_price=-150, away_price=130):
    """One ledger recommendation row, shaped the way `ledger.record_slate`
    writes it: this project's team abbreviations, plus a `prices["h2h"]`
    quote (the board as it stood at recommendation time)."""
    return {
        "kind": ledger.RECOMMENDATION,
        "game_pk": game_pk, "away_team": away, "home_team": home,
        "date": date, "commence_time": commence, "side": side,
        "market": market, "verdict": "flagged" if market else "no_play",
        "prices": {"h2h": {"home_price": home_price, "away_price": away_price}},
    }


def settlement(game_pk, closing=None, closing_reason=None):
    """One ledger settlement row, shaped the way `ledger.settle` writes
    it -- `closing=None` is the null this backfill exists to explain."""
    entry = {"kind": ledger.SETTLEMENT, "game_pk": game_pk,
             "settled_at": "2026-08-28T04:00:00+00:00",
             "result": {"home_won": 1}, "closing": closing}
    if closing is None:
        entry["closing_reason"] = closing_reason or "no closing price provided"
    return entry


class TestFindsExactlyWhatIsDerivable(unittest.TestCase):
    """The dry-run computation: derivable / not-derivable / untouched."""

    def test_null_closing_now_derivable_is_found(self):
        entries = [recommendation(1), settlement(1, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]

        result = grading.find_backfillable_closings(entries, rows)

        self.assertEqual(len(result["derivable"]), 1)
        self.assertEqual(result["derivable"][0]["game_pk"], 1)
        self.assertEqual(result["not_derivable"], [])
        self.assertEqual(len(result["to_append"]), 1)

    def test_null_closing_with_no_snapshots_stays_not_derivable(self):
        entries = [recommendation(2), settlement(2, closing=None)]

        result = grading.find_backfillable_closings(entries, snapshot_rows=[])

        self.assertEqual(result["derivable"], [])
        self.assertEqual(len(result["not_derivable"]), 1)
        self.assertEqual(result["not_derivable"][0]["reason"],
                         "no snapshots recorded for this game")
        self.assertEqual(result["to_append"], [])

    def test_snapshots_only_after_first_pitch_stay_not_derivable(self):
        entries = [recommendation(3), settlement(3, closing=None)]
        # observed AFTER commence_time -- not a pregame observation.
        rows = [snapshot_row("2026-08-28T01:00:00+00:00")]

        result = grading.find_backfillable_closings(entries, rows)

        self.assertEqual(result["derivable"], [])
        self.assertEqual(result["not_derivable"][0]["reason"],
                         "no snapshot observed before first pitch")

    def test_a_non_null_original_is_never_examined_or_touched(self):
        real_closing = {"market": "h2h", "prices": {"home_price": -150, "away_price": 130}}
        entries = [recommendation(4), settlement(4, closing=real_closing)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]

        result = grading.find_backfillable_closings(entries, rows)

        self.assertEqual(result["derivable"], [])
        self.assertEqual(result["not_derivable"], [])
        self.assertEqual(result["to_append"], [])

    def test_no_matching_recommendation_is_reported_not_silently_skipped(self):
        entries = [settlement(5, closing=None)]  # no recommendation row at all

        result = grading.find_backfillable_closings(entries, snapshot_rows=[])

        self.assertEqual(result["no_recommendation"], [5])
        self.assertEqual(result["derivable"], [])
        self.assertEqual(result["not_derivable"], [])

    def test_abbreviation_vs_full_name_join_works_through_the_backfill(self):
        # The exact bug fixed by 65f499a, exercised through the full
        # backfill path rather than the join function alone.
        entries = [recommendation(6, away="AZ", home="SF"), settlement(6, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00",
                             away="Arizona Diamondbacks",
                             home="San Francisco Giants")]

        result = grading.find_backfillable_closings(entries, rows)

        self.assertEqual(len(result["derivable"]), 1)


class TestBackfillRowShape(unittest.TestCase):
    """The row appended carries exactly the specified fields."""

    def test_row_has_every_required_field(self):
        entries = [recommendation(7), settlement(7, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]

        result = grading.find_backfillable_closings(entries, rows, now=None)
        row = result["to_append"][0]

        self.assertEqual(row["kind"], "closing_backfill")
        self.assertEqual(row["ref"], 7)
        self.assertIsNotNone(row["closing_price"])
        self.assertEqual(row["closing_observed_utc"], "2026-08-27T20:00:00+00:00")
        self.assertEqual(row["closing_source"], "odds_snapshots")
        self.assertIn("derived_utc", row)
        self.assertIn("clv", row)
        self.assertEqual(row["reason"], "abbreviation join bug 65f499a")

    def test_clv_is_computed_when_side_and_prices_are_known(self):
        # side=home, pick price -150 (recommendation time), close -150 too
        # (same book, unmoved) -- a real, checkable CLV.
        entries = [recommendation(8, side="home", home_price=-150, away_price=130),
                  settlement(8, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00",
                             home_price=-160, away_price=140)]

        row = grading.find_backfillable_closings(entries, rows)["to_append"][0]

        self.assertTrue(row["clv"]["clv_graded"])
        self.assertEqual(row["clv"]["clv_side"], "home")
        self.assertEqual(row["clv"]["pick_price"], -150)
        self.assertEqual(row["clv"]["closing_price"], -160)

    def test_clv_is_ungraded_with_a_reason_when_there_is_no_side(self):
        entries = [recommendation(9, side=None), settlement(9, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]

        row = grading.find_backfillable_closings(entries, rows)["to_append"][0]

        self.assertFalse(row["clv"]["clv_graded"])
        self.assertEqual(row["clv"]["clv_reason"],
                         "no side recorded on the recommendation")

    def test_clv_is_never_computed_off_a_non_h2h_market_price(self):
        # A first_five pick's own market price must never be compared to
        # the h2h close -- that would silently mix markets. With no h2h
        # price recorded on the recommendation, clv stays ungraded.
        entries = [{
            "kind": ledger.RECOMMENDATION, "game_pk": 10, "away_team": "CIN",
            "home_team": "CHC", "date": "2026-08-27",
            "commence_time": "2026-08-27T23:10:00Z", "side": "home",
            "market": "first_five", "verdict": "flagged",
            "prices": {"h2h_1st_5_innings": {"home_price": -188, "away_price": 148}},
        }, settlement(10, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00",
                             away="Cincinnati Reds", home="Chicago Cubs",
                             commence="2026-08-27T23:10:00Z")]

        row = grading.find_backfillable_closings(entries, rows)["to_append"][0]

        self.assertIsNotNone(row["closing_price"])  # the close is still recorded
        self.assertFalse(row["clv"]["clv_graded"])
        self.assertEqual(row["clv"]["clv_reason"],
                         "no h2h price recorded on the recommendation")


class TestReaderPreference(unittest.TestCase):
    """Readers must prefer a valid backfill when the original is null, and
    must never let a backfill override a non-null original."""

    def test_a_valid_backfill_is_preferred_when_original_is_null(self):
        entries = [recommendation(11), settlement(11, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]
        entries = entries + grading.find_backfillable_closings(entries, rows)["to_append"]

        backfills = grading.read_backfills(entries)
        effective = grading.effective_closing(settlement(11, closing=None), backfills)

        self.assertIsNotNone(effective)
        self.assertEqual(effective["prices"]["home_price"], -150)

    def test_a_non_null_original_is_never_overridden(self):
        real_closing = {"market": "h2h", "prices": {"home_price": -999, "away_price": 999}}
        original = settlement(12, closing=real_closing)
        # A backfill row someone appended anyway (tampered, or a stale
        # tool run before the original was known to be non-null).
        rogue = {"kind": "closing_backfill", "ref": 12,
                 "closing_price": {"prices": {"home_price": -111, "away_price": 111}},
                 "closing_observed_utc": "x", "closing_source": "odds_snapshots",
                 "derived_utc": "y", "clv": None, "reason": "tampered"}
        entries = [recommendation(12), original, rogue]

        backfills = grading.read_backfills(entries)
        self.assertNotIn(12, backfills)

        effective = grading.effective_closing(original, backfills)
        self.assertEqual(effective, real_closing)

    def test_no_backfill_and_null_original_reads_as_none(self):
        original = settlement(13, closing=None)
        effective = grading.effective_closing(original, backfills={})
        self.assertIsNone(effective)


class TestTamperedAndDuplicateRowsAreIgnoredDeterministically(unittest.TestCase):

    def test_a_second_backfill_for_the_same_ref_is_ignored_first_wins(self):
        first = {"kind": "closing_backfill", "ref": 14,
                 "closing_price": {"prices": {"home_price": -150, "away_price": 130}},
                 "closing_observed_utc": "a", "closing_source": "odds_snapshots",
                 "derived_utc": "t1", "clv": None, "reason": "abbreviation join bug 65f499a"}
        duplicate = {"kind": "closing_backfill", "ref": 14,
                     "closing_price": {"prices": {"home_price": -777, "away_price": 777}},
                     "closing_observed_utc": "b", "closing_source": "odds_snapshots",
                     "derived_utc": "t2", "clv": None, "reason": "abbreviation join bug 65f499a"}
        entries = [recommendation(14), settlement(14, closing=None), first, duplicate]

        backfills = grading.read_backfills(entries)

        self.assertEqual(backfills[14]["closing_price"]["prices"]["home_price"], -150)

    def test_order_is_what_decides_it_not_the_content(self):
        # Same two rows, appended in the opposite order -- the one now
        # first wins, proving the rule is positional (append order),
        # not a hidden "biggest/smallest wins" comparison.
        a = {"kind": "closing_backfill", "ref": 15,
             "closing_price": {"prices": {"home_price": -150, "away_price": 130}},
             "closing_observed_utc": "a", "closing_source": "odds_snapshots",
             "derived_utc": "t1", "clv": None, "reason": "x"}
        b = {"kind": "closing_backfill", "ref": 15,
             "closing_price": {"prices": {"home_price": -777, "away_price": 777}},
             "closing_observed_utc": "b", "closing_source": "odds_snapshots",
             "derived_utc": "t2", "clv": None, "reason": "x"}
        base = [recommendation(15), settlement(15, closing=None)]

        first_a = grading.read_backfills(base + [a, b])[15]
        first_b = grading.read_backfills(base + [b, a])[15]

        self.assertEqual(first_a["closing_observed_utc"], "a")
        self.assertEqual(first_b["closing_observed_utc"], "b")

    def test_a_backfill_targeting_an_already_closed_settlement_is_excluded(self):
        real_closing = {"market": "h2h", "prices": {"home_price": -150, "away_price": 130}}
        rogue = {"kind": "closing_backfill", "ref": 16,
                 "closing_price": {"prices": {"home_price": -999, "away_price": 999}},
                 "closing_observed_utc": "a", "closing_source": "odds_snapshots",
                 "derived_utc": "t1", "clv": None, "reason": "tampered"}
        entries = [recommendation(16), settlement(16, closing=real_closing), rogue]

        self.assertEqual(grading.read_backfills(entries), {})

    def test_a_backfill_for_a_ref_with_no_settlement_at_all_is_excluded(self):
        orphan = {"kind": "closing_backfill", "ref": 17,
                  "closing_price": {"prices": {"home_price": -150, "away_price": 130}},
                  "closing_observed_utc": "a", "closing_source": "odds_snapshots",
                  "derived_utc": "t1", "clv": None, "reason": "x"}
        self.assertEqual(grading.read_backfills([orphan]), {})

    def test_a_backfill_with_a_null_closing_price_is_excluded(self):
        bad = {"kind": "closing_backfill", "ref": 18, "closing_price": None,
               "closing_observed_utc": None, "closing_source": "odds_snapshots",
               "derived_utc": "t1", "clv": None, "reason": "x"}
        entries = [recommendation(18), settlement(18, closing=None), bad]
        self.assertEqual(grading.read_backfills(entries), {})


class TestIdempotenceAndNoMutation(unittest.TestCase):
    """A second run appends nothing; an existing row is never rewritten."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "forward_ledger.jsonl"

    def test_a_second_run_appends_zero_rows(self):
        entries = [recommendation(19), settlement(19, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]
        grading.append_ledger_rows(entries, self.path)  # writes the base rows

        first = grading.find_backfillable_closings(ledger.read(self.path), rows)
        grading.append_ledger_rows(first["to_append"], self.path)
        self.assertEqual(len(first["to_append"]), 1)

        second = grading.find_backfillable_closings(ledger.read(self.path), rows)
        self.assertEqual(second["to_append"], [])
        self.assertEqual(second["already_backfilled"], [19])

    def test_existing_lines_are_byte_identical_after_a_backfill_run(self):
        entries = [recommendation(20), settlement(20, closing=None)]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]
        grading.append_ledger_rows(entries, self.path)
        before = self.path.read_text(encoding="utf-8")

        result = grading.find_backfillable_closings(ledger.read(self.path), rows)
        grading.append_ledger_rows(result["to_append"], self.path)
        after = self.path.read_text(encoding="utf-8")

        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))

    def test_a_ragged_final_line_is_still_appended_to_safely(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(recommendation(21)))  # no trailing newline
        grading.append_ledger_rows([settlement(21, closing=None)], self.path)

        rows = ledger.read(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["game_pk"], 21)

    def test_appending_nothing_does_not_create_a_file(self):
        grading.append_ledger_rows([], self.path)
        self.assertFalse(self.path.exists())


class TestMarketCoverage(unittest.TestCase):
    """Coverage is reported honestly, per market, never blended into one
    number that would hide an uncovered market behind a covered one.

    L17 re-shaped this from "grouped by whatever the recommendation
    happened to flag" (mostly None, since this system has so far only ever
    flagged full-game or first-five bets) to the four markets a settlement
    structurally supports grading against -- h2h, spreads, totals,
    first_five -- each checked against every settled game regardless of
    what was actually recommended for it. See grading.ledger_closing_coverage's
    module note for why."""

    def test_h2h_counts_original_and_backfill_as_recorded(self):
        real_closing = {"market": "h2h", "prices": {"home_price": -150, "away_price": 130}}
        entries = [
            recommendation(30, market=None), settlement(30, closing=real_closing),
            recommendation(31, market=None), settlement(31, closing=None),
        ]
        rows = [snapshot_row("2026-08-27T20:00:00+00:00")]
        backfilled = entries + grading.find_backfillable_closings(entries, rows)["to_append"]

        coverage = grading.ledger_closing_coverage(backfilled, snapshot_rows=rows, f5_rows=[])

        h2h = coverage["h2h"]
        self.assertEqual(h2h["settled"], 2)
        self.assertEqual(h2h["with_closing"], 2)
        self.assertEqual(h2h["from_original"], 1)
        self.assertEqual(h2h["from_backfill"], 1)
        self.assertEqual(h2h["derivable_not_recorded"], 0)
        self.assertEqual(h2h["source"], "odds_snapshots")

    def test_spreads_and_totals_are_derivable_but_never_recorded(self):
        # Same store, same timing as h2h -- but nothing has ever written a
        # spreads or totals close to the ledger, so recorded stays 0 even
        # though the close is right there in the store.
        entries = [recommendation(33, market=None), settlement(33, closing=None)]
        spreads_row = snapshot_row("2026-08-27T20:00:00+00:00")
        spreads_row["market"] = "spreads"
        spreads_row["prices"] = {"home_line": -1.5, "home_price": 120,
                                 "away_line": 1.5, "away_price": -140}
        totals_row = snapshot_row("2026-08-27T20:00:00+00:00")
        totals_row["market"] = "totals"
        totals_row["prices"] = {"total": 8.5, "over_price": -110, "under_price": -110}
        rows = [snapshot_row("2026-08-27T20:00:00+00:00"), spreads_row, totals_row]

        coverage = grading.ledger_closing_coverage(entries, snapshot_rows=rows, f5_rows=[])

        for market in ("spreads", "totals"):
            bucket = coverage[market]
            self.assertEqual(bucket["settled"], 1)
            self.assertEqual(bucket["with_closing"], 0)
            self.assertEqual(bucket["from_original"], 0)
            self.assertEqual(bucket["from_backfill"], 0)
            self.assertEqual(bucket["derivable_not_recorded"], 1)
            self.assertEqual(bucket["not_derivable"], {})
            self.assertEqual(bucket["source"], "odds_snapshots")

    def test_first_five_is_never_recorded_and_uses_the_f5_store(self):
        entries = [recommendation(34, market="first_five"), settlement(34, closing=None)]
        f5_row = {
            "observed_utc": "2026-08-27T22:50:00Z", "commence_time": "2026-08-27T23:10:00Z",
            "away_team": recommendation(34)["away_team"], "home_team": recommendation(34)["home_team"],
            "market": "h2h_1st_5_innings", "book": "fanduel",
            "book_last_update": "2026-08-27T22:49:00Z",
            "home_price": -140, "away_price": 120,
        }

        coverage = grading.ledger_closing_coverage(entries, snapshot_rows=[], f5_rows=[f5_row])

        f5 = coverage["first_five"]
        self.assertEqual(f5["settled"], 1)
        self.assertEqual(f5["with_closing"], 0)
        self.assertEqual(f5["derivable_not_recorded"], 1)
        self.assertEqual(f5["source"], "f5_close")

    def test_not_captured_is_its_own_reason_bucket(self):
        # No snapshot rows anywhere: every market for this settled game is
        # genuinely uncaptured, not merely "captured too late".
        entries = [recommendation(35, market=None), settlement(35, closing=None)]

        coverage = grading.ledger_closing_coverage(entries, snapshot_rows=[], f5_rows=[])

        for market in ("h2h", "spreads", "totals", "first_five"):
            bucket = coverage[market]
            self.assertEqual(bucket["derivable_not_recorded"], 0)
            self.assertEqual(bucket["not_derivable"], {"not_captured": 1})


if __name__ == "__main__":
    unittest.main()
