"""src/report/effective_record.py -- task B1/B2's reconciled record surface.

Every test builds its own temporary ledger file(s) via `HashChainLedger.
append` directly (the same primitive `card_ledger._ledger(...).append`
itself calls) rather than going through `publish`/`settle`: this module
only READS `record`/`record_v2`/`history`/`history_v2`/`verify`, so a
fixture only has to match the ROW SHAPE those functions read, and building
rows directly keeps these tests independent of publish/settle's own lock-
window and grading rules (including an unrelated, currently in-progress,
uncommitted change to `src/appstate/card_ledger.py`'s grading internals
that this file never exercises). None of these tests touch a real
evidence/*.jsonl file.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from src.appstate import card_ledger
from src.ledger.chain import HashChainLedger
from src.report import effective_record as er


# ---------------------------------------------------------------------------
# fixture builders -- V1-style (MLB-v1, NFL, MMA all share this row shape)
# ---------------------------------------------------------------------------

def _pick(result="WIN", profit_units=0.91, market="moneyline", game_pk=1):
    return {"rank": 1, "bet": "Take it", "label": "STRONG", "market": market,
            "price": -110, "game_pk": game_pk, "result": result,
            "profit_units": profit_units}


def _published_row(date, *, rule, n_picks=1, n_prop_picks=0, n_total_picks=0):
    mk = lambda n, prefix: [{"rank": i + 1, "bet": f"{prefix} {i}",
                             "game_pk": 1000 + i} for i in range(n)]
    return {
        "date": date, "kind": card_ledger.KIND_PUBLISHED, "rule": rule,
        "published_utc": f"{date}T18:00:00Z", "n_filled": 0,
        "picks": mk(n_picks, "game"),
        "prop_picks": mk(n_prop_picks, "prop"),
        "total_picks": mk(n_total_picks, "total"),
    }


def _settled_row(date, *, published_row_hash=None,
                  wins=0, losses=0, pushes=0, voids=0, unresolved=0,
                  profit_units=0.0, picks=None,
                  prop_wins=0, prop_losses=0, prop_pushes=0, prop_voids=0,
                  prop_unresolved=0, prop_profit_units=0.0, prop_picks=None,
                  total_wins=0, total_losses=0, total_pushes=0, total_voids=0,
                  total_unresolved=0, total_profit_units=0.0, total_picks=None):
    n_staked = wins + losses
    n_prop_staked = prop_wins + prop_losses
    n_total_staked = total_wins + total_losses
    return {
        "date": date, "kind": card_ledger.KIND_SETTLED,
        "settled_utc": f"{date}T06:00:00Z",
        "published_row_hash": published_row_hash,
        "wins": wins, "losses": losses, "pushes": pushes, "voids": voids,
        "unresolved": unresolved, "n_staked": n_staked,
        "profit_units": profit_units,
        "picks": picks if picks is not None else [],
        "prop_wins": prop_wins, "prop_losses": prop_losses,
        "prop_pushes": prop_pushes, "prop_voids": prop_voids,
        "prop_unresolved": prop_unresolved, "n_prop_staked": n_prop_staked,
        "prop_profit_units": prop_profit_units,
        "prop_picks": prop_picks if prop_picks is not None else [],
        "total_wins": total_wins, "total_losses": total_losses,
        "total_pushes": total_pushes, "total_voids": total_voids,
        "total_unresolved": total_unresolved, "n_total_staked": n_total_staked,
        "total_profit_units": total_profit_units,
        "total_picks": total_picks if total_picks is not None else [],
    }


def _write_v1_night(path, date, *, rule, wins, losses, profit_units,
                     prop_wins=0, prop_losses=0, prop_profit_units=0.0,
                     voids=0, unresolved=0):
    """One published-and-settled night, correctly joined by
    `published_row_hash` -- the join `record(rule=...)`'s own filter
    depends on."""
    ledger = HashChainLedger(path)
    published = ledger.append(_published_row(date, rule=rule,
                                              n_picks=wins + losses,
                                              n_prop_picks=prop_wins + prop_losses))
    ledger.append(_settled_row(
        date, published_row_hash=published["row_hash"],
        wins=wins, losses=losses, voids=voids, unresolved=unresolved,
        profit_units=profit_units,
        prop_wins=prop_wins, prop_losses=prop_losses,
        prop_profit_units=prop_profit_units))


def _write_v1_pending(path, date, *, rule, n_picks=2):
    """A published-but-never-settled night."""
    HashChainLedger(path).append(_published_row(date, rule=rule, n_picks=n_picks))


class _TempPathCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _path(self, name):
        return os.path.join(self._tmp.name, name)


# ---------------------------------------------------------------------------
# 1. profit-sign reversal renders identically (same shape, sign is just data)
# ---------------------------------------------------------------------------

class ProfitSignReversal(_TempPathCase):
    def _cohort(self, profit_units):
        path = self._path("nfl.jsonl")
        _write_v1_night(path, "2026-09-17", rule="R", wins=1, losses=2,
                        profit_units=profit_units)
        return er._v1_style_cohort(sport="nfl", path=path, rule_id="R",
                                   filter_rule="R", status="current", label="x")

    def test_losing_and_winning_cohorts_share_every_key(self):
        losing = self._cohort(-1.15)
        winning = self._cohort(+1.15)
        self.assertEqual(set(losing.keys()), set(winning.keys()))
        self.assertEqual(losing["market_breakdown"].keys(),
                         winning["market_breakdown"].keys())
        for kind in losing["market_breakdown"]:
            self.assertEqual(set(losing["market_breakdown"][kind].keys()),
                             set(winning["market_breakdown"][kind].keys()))

    def test_only_the_sign_and_derived_figures_differ(self):
        losing = self._cohort(-1.15)
        winning = self._cohort(+1.15)
        self.assertEqual(losing["profit_units"], -1.15)
        self.assertEqual(winning["profit_units"], 1.15)
        # Everything that does not depend on the sign of profit is IDENTICAL.
        for key in ("wins", "losses", "pushes", "voids", "unresolved",
                   "n_staked", "win_rate", "days", "grading_state",
                   "published_count", "settled_count"):
            self.assertEqual(losing[key], winning[key], key)

    def test_roi_pct_flips_sign_with_profit(self):
        losing = self._cohort(-1.15)
        winning = self._cohort(+1.15)
        self.assertLess(losing["roi_pct"], 0)
        self.assertGreater(winning["roi_pct"], 0)
        self.assertAlmostEqual(losing["roi_pct"], -winning["roi_pct"], places=6)


# ---------------------------------------------------------------------------
# 2. current ungraded + previous graded (NFL's real 2026-09-24 shape)
# ---------------------------------------------------------------------------

class CurrentUngradedPreviousGraded(_TempPathCase):
    def test_nfl_snapshot_when_only_the_retired_rule_has_settled(self):
        from src.report import nfl_card as nfl_report
        path = self._path("nfl.jsonl")
        _write_v1_night(path, "2026-09-17", rule=nfl_report.RETIRED_RULE,
                        wins=1, losses=0, profit_units=0.91)
        _write_v1_night(path, "2026-09-20", rule=nfl_report.RETIRED_RULE,
                        wins=0, losses=1, profit_units=-1.0)
        # The live rule has published nothing at all on this ledger.

        snap = er.nfl_snapshot(path=path)
        current, previous = snap["current"], snap["previous"]

        self.assertEqual(current["rule_id"], nfl_report.LIVE_RULE)
        self.assertEqual(current["grading_state"], "no_publications_yet")
        self.assertEqual(current["days"], 0)
        self.assertIsNone(current["date_span"])
        self.assertIsNotNone(current["reason"])

        self.assertEqual(previous["rule_id"], nfl_report.RETIRED_RULE)
        self.assertEqual(previous["grading_state"], "graded")
        self.assertEqual(previous["days"], 2)
        self.assertEqual(previous["wins"], 1)
        self.assertEqual(previous["losses"], 1)
        self.assertEqual(previous["date_span"],
                         {"first": "2026-09-17", "last": "2026-09-20"})

    def test_current_ungraded_cohort_is_never_a_bare_zero_zero(self):
        """B1's honest-absence rule: a cohort with zero settlements must
        name why, not just report 0-0."""
        path = self._path("mma.jsonl")
        _write_v1_pending(path, "2026-09-22", rule="UFC_CARD_V1", n_picks=2)
        snap = er.mma_snapshot(path=path)
        current = snap["current"]
        self.assertEqual(current["wins"], 0)
        self.assertEqual(current["losses"], 0)
        self.assertEqual(current["grading_state"], "published_not_settled")
        self.assertIn("2 picks published", current["reason"])
        self.assertIn("hand", current["reason"])  # the actual UFC reason, not a guess
        self.assertIsNone(snap["previous"])


# ---------------------------------------------------------------------------
# 3. both missing -- a ledger this process cannot read
# ---------------------------------------------------------------------------

class BothMissing(_TempPathCase):
    def test_an_unreadable_ledger_is_unavailable_never_a_guessed_zero(self):
        path = self._path("corrupt.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{this is not valid json\n")

        snap = er.mlb_snapshot(v1_path=path, v2_path=path)
        for cohort in (snap["current"], snap["previous"]):
            self.assertFalse(cohort["available"])
            self.assertEqual(cohort["grading_state"], "unavailable")
            self.assertIsNone(cohort["wins"])
            self.assertIsNone(cohort["losses"])
            self.assertIsNone(cohort["days"])
            self.assertIn("unavailable", cohort["reason"])

    def test_a_file_that_simply_does_not_exist_yet_is_a_real_empty_cohort(self):
        """Distinct from 'unavailable': a path with nothing written yet
        reads as zero rows (HashChainLedger's own contract), which this
        module reports as an honest, explained 'no publications yet' --
        not a read failure."""
        path = self._path("never_written.jsonl")
        snap = er.nfl_snapshot(path=path)
        for cohort in (snap["current"], snap["previous"]):
            self.assertTrue(cohort["available"])
            self.assertEqual(cohort["grading_state"], "no_publications_yet")


# ---------------------------------------------------------------------------
# 4. mixed pending/settled
# ---------------------------------------------------------------------------

class MixedPendingSettled(_TempPathCase):
    def test_pending_and_settled_counts_are_both_explicit(self):
        path = self._path("nfl.jsonl")
        _write_v1_night(path, "2026-09-17", rule="R", wins=1, losses=1,
                        profit_units=-0.09)
        _write_v1_pending(path, "2026-09-24", rule="R", n_picks=3)

        cohort = er._v1_style_cohort(sport="nfl", path=path, rule_id="R",
                                     filter_rule="R", status="current", label="x")
        self.assertEqual(cohort["days"], 1)          # settled nights only
        self.assertEqual(cohort["settled_count"], 2)  # 1 win + 1 loss
        self.assertEqual(cohort["pending_count"], 3)  # the 2026-09-24 night
        self.assertEqual(cohort["published_count"], 5)
        self.assertEqual(cohort["grading_state"], "graded")

    def test_v2_pending_count_excludes_already_settled_dates(self):
        v2_path = self._path("cards_v2.jsonl")
        ledger = HashChainLedger(v2_path)
        ledger.append({"date": "2026-09-22", "kind": card_ledger.KIND_PUBLISHED,
                       "rule": "DAILY_CARD_BEST_BETS_V2",
                       "picks": [{"a": 1}], "prop_picks": []})
        ledger.append({
            "date": "2026-09-22", "kind": card_ledger.KIND_SETTLED,
            "rule": "DAILY_CARD_BEST_BETS_V2", "wins": 1, "losses": 0,
            "pushes": 0, "voids": 0, "n_staked": 1, "profit_units": 0.87,
            "graded": [{"kind": "game", "price_class": "MAIN",
                       "entry_class": "pick", "result": "WIN",
                       "profit_units": 0.87}],
        })
        ledger.append({"date": "2026-09-23", "kind": card_ledger.KIND_PUBLISHED,
                       "rule": "DAILY_CARD_BEST_BETS_V2",
                       "picks": [{"a": 1}, {"a": 2}], "prop_picks": [{"a": 3}]})

        snap = er.mlb_snapshot(v1_path=self._path("v1_empty.jsonl"), v2_path=v2_path)
        current = snap["current"]
        self.assertEqual(current["settled_count"], 1)
        self.assertEqual(current["pending_count"], 3)  # only 2026-09-23's picks
        self.assertEqual(current["days"], 1)


# ---------------------------------------------------------------------------
# 5. per-sport separation
# ---------------------------------------------------------------------------

class PerSportSeparation(_TempPathCase):
    def test_three_sports_read_three_independent_files(self):
        nfl_path = self._path("nfl.jsonl")
        mma_path = self._path("mma.jsonl")
        _write_v1_night(nfl_path, "2026-09-17", rule="NFL_R", wins=3, losses=0,
                        profit_units=2.7)
        _write_v1_pending(mma_path, "2026-09-22", rule="UFC_CARD_V1", n_picks=2)

        nfl_current = er._v1_style_cohort(sport="nfl", path=nfl_path,
                                          rule_id="NFL_R", filter_rule="NFL_R",
                                          status="current", label="x")
        mma_snap = er.mma_snapshot(path=mma_path)

        self.assertEqual(nfl_current["wins"], 3)
        self.assertEqual(nfl_current["sport"], "nfl")
        self.assertEqual(mma_snap["current"]["sport"], "mma")
        # NFL's wins never leak into MMA's cohort, whose file never
        # mentions a settled pick at all.
        self.assertEqual(mma_snap["current"]["wins"], 0)
        self.assertEqual(mma_snap["current"]["settled_count"], 0)

    def test_build_covers_exactly_the_three_public_sports(self):
        out = er.build()
        self.assertEqual(set(out["sports"].keys()), {"mlb", "nfl", "mma"})
        for sport, snap in out["sports"].items():
            self.assertEqual(snap["sport"], sport)


# ---------------------------------------------------------------------------
# 6. all-market vs market-filtered totals (the B1 mismatch, resolved)
# ---------------------------------------------------------------------------

class MarketBreakdownVsHeadline(_TempPathCase):
    def test_headline_is_the_sum_of_every_market_never_game_only(self):
        path = self._path("v1.jsonl")
        _write_v1_night(path, "2026-09-10", rule="R", wins=2, losses=1,
                        profit_units=1.5, prop_wins=3, prop_losses=1,
                        prop_profit_units=0.8)
        cohort = er._v1_style_cohort(sport="mlb", path=path, rule_id="R",
                                     filter_rule="R", status="current", label="x")
        game_only = cohort["market_breakdown"]["game"]
        prop_only = cohort["market_breakdown"]["prop"]
        self.assertEqual(game_only["wins"], 2)
        self.assertEqual(game_only["losses"], 1)
        self.assertEqual(prop_only["wins"], 3)
        self.assertEqual(prop_only["losses"], 1)
        # The headline is neither slice alone -- it is BOTH, pooled, so a
        # game-only V1 number is never compared against an all-markets V2
        # number under the same "wins"/"losses" label again.
        self.assertEqual(cohort["wins"], 5)
        self.assertEqual(cohort["losses"], 2)
        self.assertAlmostEqual(cohort["profit_units"], 2.3, places=6)
        self.assertIn("game", cohort["market_note"])
        self.assertIn("prop", cohort["market_note"])

    def test_v2_headline_matches_its_own_market_breakdown_sum(self):
        """Sanity invariant: record_v2()'s own `combined` figure (this
        module's V2 headline) must never silently disagree with the
        independently-rebuilt per-kind breakdown this module computes from
        the same settled entries."""
        v2_path = self._path("cards_v2.jsonl")
        ledger = HashChainLedger(v2_path)
        ledger.append({
            "date": "2026-09-22", "kind": card_ledger.KIND_SETTLED,
            "rule": "DAILY_CARD_BEST_BETS_V2",
            "wins": 3, "losses": 2, "pushes": 0, "voids": 0, "n_staked": 5,
            "profit_units": 1.05,
            "graded": [
                {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                 "result": "WIN", "profit_units": 0.91},
                {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                 "result": "LOSS", "profit_units": -1.0},
                {"kind": "prop", "price_class": "PLUS_MONEY", "entry_class": "pick",
                 "result": "WIN", "profit_units": 1.20},
                {"kind": "prop", "price_class": "PLUS_MONEY", "entry_class": "pick",
                 "result": "WIN", "profit_units": 1.14},
                {"kind": "prop", "price_class": "MAIN", "entry_class": "pick",
                 "result": "LOSS", "profit_units": -1.0},
                # A fill and a withdrawn pick must never enter EITHER the
                # headline or the breakdown.
                {"kind": "game", "price_class": "MAIN", "entry_class": "fill",
                 "result": "WIN", "profit_units": 5.0},
                {"kind": "prop", "price_class": "MAIN", "entry_class": "pick",
                 "result": "WIN", "profit_units": 9.0, "withdrawn": True},
            ],
        })
        snap = er.mlb_snapshot(v1_path=self._path("v1_empty.jsonl"), v2_path=v2_path)
        current = snap["current"]
        breakdown_sum_wins = sum(fig["wins"] for fig in current["market_breakdown"].values())
        breakdown_sum_losses = sum(fig["losses"] for fig in current["market_breakdown"].values())
        self.assertEqual(current["wins"], 3)
        self.assertEqual(current["losses"], 2)
        self.assertEqual(breakdown_sum_wins, 3)
        self.assertEqual(breakdown_sum_losses, 2)
        self.assertAlmostEqual(current["profit_units"], 1.25, places=6)


# ---------------------------------------------------------------------------
# 7. date boundaries
# ---------------------------------------------------------------------------

class DateBoundaries(_TempPathCase):
    def test_date_span_is_correct_regardless_of_file_order(self):
        path = self._path("nfl.jsonl")
        # Written out of chronological order on purpose.
        _write_v1_night(path, "2026-09-20", rule="R", wins=1, losses=0, profit_units=0.9)
        _write_v1_night(path, "2026-09-10", rule="R", wins=0, losses=1, profit_units=-1.0)
        _write_v1_night(path, "2026-09-17", rule="R", wins=1, losses=0, profit_units=0.9)

        cohort = er._v1_style_cohort(sport="nfl", path=path, rule_id="R",
                                     filter_rule="R", status="current", label="x")
        self.assertEqual(cohort["date_span"], {"first": "2026-09-10", "last": "2026-09-20"})
        self.assertEqual(cohort["days"], 3)
        self.assertEqual(cohort["first_published"], "2026-09-10")


# ---------------------------------------------------------------------------
# 9. trustworthy as-of timestamps
# ---------------------------------------------------------------------------

class AsOfTimestamps(_TempPathCase):
    def test_generated_at_is_the_injected_now(self):
        fixed = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
        out = er.build(now=fixed)
        self.assertEqual(out["generated_at"], fixed.isoformat())

    def test_generated_at_defaults_to_a_real_utc_now(self):
        before = datetime.now(timezone.utc)
        out = er.build()
        parsed = datetime.fromisoformat(out["generated_at"])
        after = datetime.now(timezone.utc)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertLessEqual(before, parsed)
        self.assertLessEqual(parsed, after)

    def test_chain_ok_surfaces_from_verify_for_a_readable_ledger(self):
        path = self._path("nfl.jsonl")
        _write_v1_night(path, "2026-09-17", rule="R", wins=1, losses=0, profit_units=0.9)
        cohort = er._v1_style_cohort(sport="nfl", path=path, rule_id="R",
                                     filter_rule="R", status="current", label="x")
        self.assertIs(cohort["chain_ok"], True)
        self.assertIsInstance(cohort["rows_checked"], int)

    def test_a_tampered_chain_is_reported_not_hidden(self):
        path = self._path("nfl.jsonl")
        _write_v1_night(path, "2026-09-17", rule="R", wins=1, losses=0, profit_units=0.9)
        # Tamper with the file directly, after the fact -- the same attack
        # `card_ledger.verify()` exists to catch.
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import json as _json
        row = _json.loads(lines[-1])
        row["wins"] = 99
        lines[-1] = _json.dumps(row) + "\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)

        cohort = er._v1_style_cohort(sport="nfl", path=path, rule_id="R",
                                     filter_rule="R", status="current", label="x")
        self.assertIs(cohort["chain_ok"], False)


# ---------------------------------------------------------------------------
# stake/ROI denominator consistency (metric contract)
# ---------------------------------------------------------------------------

class ExactGamePlusPropReconciliation(_TempPathCase):
    """Owner review, 2026-09-25: the hero panel and the MLB sport tile
    showed two different numbers for "Our first card rule" on the same
    page -- the hero said 73-40, +7.61u (GAME picks only, from
    `card_ledger.record()`'s bare default); the tile said 151-79, +7.98u
    (this module's V1 cohort, GAME PLUS PROP pooled). Both were real
    numbers; neither was wrong on its own terms. The bug was that ONE
    LABEL ("Our first card rule: 73-40 ... 13 nights") pointed at two
    different populations depending which component of the page rendered
    it -- see api/meta.py's `_card_record` for the fix that makes every
    surface read this module's cohort instead of re-deriving its own
    figure.

    This test is the reconciliation THIS module's own headline promises
    (effective_record.py's own "MARKET-SET MISMATCH, RESOLVED NOT JUST
    LABELLED" docstring section): the cohort's `wins`/`losses`/`pushes`/
    `voids`/`profit_units`/`n_staked` are each EXACTLY the sum of the
    `game` and `prop` slices of its own `market_breakdown` -- not
    approximately, not "close enough", every one of the six figures.

    THE FIXTURE BELOW USES THE REAL NUMBERS FROM THE LIVE LEDGER READ
    DURING THIS REVIEW (2026-09-25, evidence/cards_v1.jsonl, V1's frozen
    13-night record) so this test's own assertions double as the
    reconciliation reported alongside it: game 73-40, +7.6063u, 113
    staked, 0 pushes/voids; prop 78-39, +0.3758u, 117 staked, 0 pushes,
    1 void. 73+78=151, 40+39=79, 0+0=0, 0+1=1, 230 staked,
    7.6063+0.3758=7.9821u -- matching the live headline exactly. This
    file's own convention (module docstring) is that no test here touches
    a real evidence/*.jsonl file, so the real figures are reproduced as
    this test's OWN fixture rather than read from disk; a live
    confirmation that today's actual ledger reconciles the same way lives
    in tests/test_api_meta_card_record_v2.py, which already reads the
    real ledger for other assertions in this same review.
    """

    GAME = {"wins": 73, "losses": 40, "pushes": 0, "voids": 0, "profit_units": 7.6063}
    PROP = {"wins": 78, "losses": 39, "pushes": 0, "voids": 1, "profit_units": 0.3758}

    def _cohort(self):
        path = self._path("v1.jsonl")
        ledger = HashChainLedger(path)
        published = ledger.append(_published_row(
            "2026-09-10", rule="R",
            n_picks=self.GAME["wins"] + self.GAME["losses"],
            n_prop_picks=self.PROP["wins"] + self.PROP["losses"]))
        ledger.append(_settled_row(
            "2026-09-10", published_row_hash=published["row_hash"],
            wins=self.GAME["wins"], losses=self.GAME["losses"],
            pushes=self.GAME["pushes"], voids=self.GAME["voids"],
            profit_units=self.GAME["profit_units"],
            prop_wins=self.PROP["wins"], prop_losses=self.PROP["losses"],
            prop_pushes=self.PROP["pushes"], prop_voids=self.PROP["voids"],
            prop_profit_units=self.PROP["profit_units"]))
        return er._v1_style_cohort(sport="mlb", path=path, rule_id="R",
                                   filter_rule="R", status="previous", label="x")

    def test_game_and_prop_breakdown_matches_the_real_ledger_figures(self):
        """Sanity check on the fixture itself before trusting anything
        built from it: the breakdown this cohort reports for each market
        must be exactly what was written in, unchanged."""
        cohort = self._cohort()
        game, prop = cohort["market_breakdown"]["game"], cohort["market_breakdown"]["prop"]
        self.assertEqual((game["wins"], game["losses"], game["voids"]), (73, 40, 0))
        self.assertAlmostEqual(game["profit_units"], 7.6063, places=4)
        self.assertEqual((prop["wins"], prop["losses"], prop["voids"]), (78, 39, 1))
        self.assertAlmostEqual(prop["profit_units"], 0.3758, places=4)

    def test_headline_wins_losses_pushes_voids_exactly_sum_game_plus_prop(self):
        cohort = self._cohort()
        game, prop = cohort["market_breakdown"]["game"], cohort["market_breakdown"]["prop"]
        self.assertEqual(cohort["wins"], game["wins"] + prop["wins"])
        self.assertEqual(cohort["losses"], game["losses"] + prop["losses"])
        self.assertEqual(cohort["pushes"], game["pushes"] + prop["pushes"])
        self.assertEqual(cohort["voids"], game["voids"] + prop["voids"])
        # The exact real numbers, stated plainly rather than only derived:
        self.assertEqual((cohort["wins"], cohort["losses"]), (151, 79))
        self.assertEqual(cohort["voids"], 1)

    def test_headline_n_staked_exactly_sums_game_plus_prop(self):
        cohort = self._cohort()
        game, prop = cohort["market_breakdown"]["game"], cohort["market_breakdown"]["prop"]
        self.assertEqual(cohort["n_staked"], game["n_staked"] + prop["n_staked"])
        self.assertEqual(cohort["n_staked"], 230)

    def test_headline_profit_units_exactly_sums_game_plus_prop(self):
        cohort = self._cohort()
        game, prop = cohort["market_breakdown"]["game"], cohort["market_breakdown"]["prop"]
        self.assertAlmostEqual(cohort["profit_units"],
                               round(game["profit_units"] + prop["profit_units"], 4),
                               places=4)
        self.assertAlmostEqual(cohort["profit_units"], 7.9821, places=4)

    def test_this_pooled_figure_is_the_one_every_surface_must_show(self):
        """The number this test reconciles (151-79, +7.98u) is NOT a
        second, competing figure alongside the game-only 73-40 -- it is
        the one this module's own docstring says every surface must use
        as "the rule's headline" (see the module docstring's "MARKET-SET
        MISMATCH" section). 73-40 stays real and visible, but only inside
        `market_breakdown["game"]`, never as the top-level `wins`/
        `losses` a reader would read as the rule's whole record."""
        cohort = self._cohort()
        self.assertNotEqual((cohort["wins"], cohort["losses"]),
                            (cohort["market_breakdown"]["game"]["wins"],
                             cohort["market_breakdown"]["game"]["losses"]))


class StakeBasisConsistency(_TempPathCase):
    def test_roi_denominator_is_n_staked_never_published_or_pending(self):
        path = self._path("nfl.jsonl")
        _write_v1_night(path, "2026-09-17", rule="R", wins=1, losses=1,
                        profit_units=-0.09)
        _write_v1_pending(path, "2026-09-24", rule="R", n_picks=10)
        cohort = er._v1_style_cohort(sport="nfl", path=path, rule_id="R",
                                     filter_rule="R", status="current", label="x")
        # n_staked is 2 (the settled night only); 10 pending picks must
        # never dilute or inflate the ROI denominator.
        self.assertEqual(cohort["n_staked"], 2)
        self.assertAlmostEqual(cohort["roi_pct"], -0.09 / 2 * 100.0, places=6)

    def test_stake_basis_is_stated_once_and_reused(self):
        out = er.build()
        self.assertIn("1 unit", out["stake_basis"])
        self.assertIn("profit units", out["stake_basis"].lower())


# ---------------------------------------------------------------------------
# postseason, graded but not counted (owner ruling, registration 11.1;
# docs/PREREG_CARD_V2.md lines 1087-1089 and 3203-3205). The scenario-level
# reconciliation lives in tests/test_postseason_not_counted.py; these test
# the small pure helpers this module's postseason split is built from, in
# isolation, the same way every other helper in this file's "small pure
# helpers" section is tested elsewhere in this suite.
# ---------------------------------------------------------------------------

class PostseasonGamePksHelper(unittest.TestCase):
    def test_only_non_regular_game_types_are_collected(self):
        store = {
            "1": {"game_pk": "1", "game_type": "R"},
            "2": {"game_pk": "2", "game_type": "F"},
            "3": {"game_pk": "3", "game_type": None},
            "4": {"game_pk": "4", "game_type": ""},
        }
        pks = er._postseason_game_pks(store)
        self.assertIn("2", pks)
        self.assertNotIn("1", pks)
        self.assertNotIn("3", pks)
        self.assertNotIn("4", pks)

    def test_both_str_and_int_forms_are_present(self):
        """The exact join `src.cli`'s `_results_and_box_rows` uses for MLB
        -- a caller with either an int or a str game_pk finds it."""
        store = {"717465": {"game_pk": "717465", "game_type": "D"}}
        pks = er._postseason_game_pks(store)
        self.assertIn("717465", pks)
        self.assertIn(717465, pks)

    def test_a_row_with_no_game_pk_is_skipped_not_a_crash(self):
        store = {"1": {"game_pk": None, "game_type": "F"}}
        self.assertEqual(er._postseason_game_pks(store), frozenset())

    def test_an_unreadable_store_is_an_empty_set_not_a_500(self):
        """`results_store=None` reads the real file by default; a
        `history.read_results` that raises must degrade to "nothing known
        to be postseason", never propagate into a record route."""
        with mock.patch("src.pipeline.history.read_results",
                        side_effect=RuntimeError("gone")):
            self.assertEqual(er._postseason_game_pks(None), frozenset())


class IsPostseasonEntryHelper(unittest.TestCase):
    def test_frozen_game_type_wins_even_with_no_pks_set(self):
        self.assertTrue(er._is_postseason_entry({"game_type": "F"}, frozenset()))

    def test_frozen_r_falls_through_to_the_pks_set(self):
        self.assertFalse(er._is_postseason_entry({"game_type": "R"}, frozenset()))
        self.assertTrue(er._is_postseason_entry(
            {"game_type": "R", "game_pk": "9"}, frozenset({"9"})))

    def test_game_id_is_checked_the_same_as_game_pk(self):
        """MLB's game_id is str(game_pk) (src/sports/mlb.py's own
        `_schedule`) -- a V2 entry that only carries `game_id` still
        classifies correctly."""
        self.assertTrue(er._is_postseason_entry(
            {"game_id": "717465"}, frozenset({"717465"})))

    def test_neither_key_present_is_never_postseason(self):
        self.assertFalse(er._is_postseason_entry({}, frozenset({"1", "2"})))


class MlbSnapshotAcceptsAnInjectedResultsStore(_TempPathCase):
    def test_results_store_is_never_read_from_disk_when_injected(self):
        """A caller (this test) supplies its own results store; the real
        data/historical/mlb_results.csv must never be touched."""
        v2_path = self._path("cards_v2.jsonl")
        with mock.patch("src.pipeline.history.read_results",
                        side_effect=AssertionError(
                            "read_results() called despite an injected results_store")):
            snap = er.mlb_snapshot(v1_path=self._path("v1_empty.jsonl"),
                                   v2_path=v2_path, results_store={})
        self.assertTrue(snap["current"]["available"])



class LedgerItselfShowsPostseasonTest(unittest.TestCase):
    """The results store in a deployed image can be weeks behind, so the
    postseason split must not depend on it. Found 2026-10-01: three prop
    fills on a Wild Card game were counted as regular season because a prop
    entry freezes no game_type and the store knew no postseason game."""

    def _hist(self):
        return {"days": [
            {"date": "2026-09-27", "graded": [
                {"kind": "prop", "game_pk": 823400, "entry_class": "fill", "result": "WIN",
                 "price": -120}]},
            {"date": "2026-09-30", "graded": [
                {"kind": "game", "game_pk": 849842, "game_type": "F", "entry_class": "fill",
                 "result": "WIN", "price": -134},
                {"kind": "prop", "game_pk": 849842, "entry_class": "fill", "result": "LOSS",
                 "price": -130},
                # a props-only night: nothing on the card freezes a game_type
                {"kind": "prop", "game_pk": 849999, "result": "WIN", "price": -110}]},
        ]}

    def test_props_on_a_postseason_game_classify_without_the_results_store(self):
        from src.report import effective_record as er
        hist = self._hist()
        pks = er._ledger_postseason_pks(hist)
        self.assertIn(849842, pks)
        self.assertIn("849842", pks)
        self.assertIn(849999, pks)
        self.assertNotIn(823400, pks)
        counted, postseason = er._v2_date_split(hist, pks)
        self.assertEqual(counted, {"2026-09-27"})
        self.assertEqual(postseason, {"2026-09-30"})
        counted_picks, postseason_picks = er._v2_market_breakdown(hist, pks)
        self.assertEqual(counted_picks, {})
        self.assertEqual(sum(f["n_staked"] for f in postseason_picks.values()), 1)

    def test_without_it_the_same_props_are_counted(self):
        # The defect, pinned: an empty store-derived set counts the prop.
        from src.report import effective_record as er
        counted, _ = er._v2_date_split(self._hist(), frozenset())
        self.assertIn("2026-09-30", counted)

    def test_a_date_outside_this_seasons_window_is_not_swept_in(self):
        from src.report import effective_record as er
        hist = {"days": [{"date": "2027-04-10", "graded": [
            {"kind": "prop", "game_pk": 900001, "result": "WIN", "price": -110}]}]}
        self.assertEqual(er._ledger_postseason_pks(hist), frozenset())


if __name__ == "__main__":
    unittest.main()
