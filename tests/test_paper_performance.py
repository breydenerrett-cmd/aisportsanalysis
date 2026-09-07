"""Tests for src.report.paper_performance (Task B3).

Hermetic: every ledger this module reads is written to a temp directory by
this test file itself, through the same writer APIs the real pipeline uses
(`src.accounts.paper.PaperAccount` for account ledgers,
`src.ledger.chain.HashChainLedger` directly for the plain wager/review
fixtures, matching their real on-disk row shapes) -- nothing here touches
the real `data/`/`evidence/` trees except the one opt-in real-ledger
reconciliation test, which skips cleanly when `data/paper_accounts` is
absent.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.accounts import paper as paper_mod
from src.accounts.paper import PaperAccount, PaperBet
from src.board.settle import GameResult
from src.ledger.chain import HashChainLedger
from src.ledger.records import compute_thesis_outcome
from src.report import paper_performance as pp

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _bet(bet_id, system_id, side="home", price_american=100, market_key="h2h"):
    return PaperBet(bet_id=bet_id, system_id=system_id, market_key=market_key,
                    selection_id=side, side=side, line=None,
                    price_american=price_american, settlement_rule=market_key)


def _review_row(decision_key, settled, checks=(), review_utc="2026-09-01T00:00:00Z"):
    thesis_outcome = compute_thesis_outcome(tuple(checks), settled)
    return {
        "decision_key": list(decision_key),
        "review_utc": review_utc,
        "settled": settled,
        "thesis_outcome": thesis_outcome,
        "mechanism_checks": list(checks),
        "market_path": {},
        "late_information": [],
        "missed_information": [],
        "lineup_delta": {},
        "bullpen_delta": {},
        "counterargument_realized": [],
        "variance_flag": thesis_outcome == "VARIANCE",
        "system_action": "none",
        "new_hypothesis": None,
    }


class _HermeticBase(unittest.TestCase):
    """Two tiny accounts (one CONTROL prefix, one hex forward-test id),
    settled through the real `PaperAccount` API so their ledgers are
    genuine, verifiable hash chains -- never hand-authored JSONL."""

    CONTROL_SYSTEM = "trivial_test_control"
    FORWARD_SYSTEM = "abc123deadbeef01"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.accounts_dir = Path(self._tmpdir.name) / "paper_accounts"
        self.accounts_dir.mkdir(parents=True)

        patcher = mock.patch.object(
            paper_mod, "default_ledger_path",
            side_effect=lambda sid: self.accounts_dir / f"{sid}.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)

        # CONTROL: two settled bets, one win one loss.
        control = PaperAccount(system_id=self.CONTROL_SYSTEM)
        control.settle_and_record(
            _bet("c-bet-1", self.CONTROL_SYSTEM, price_american=100),
            GameResult(home_runs=5, away_runs=2), day="2026-08-30")
        control.settle_and_record(
            _bet("c-bet-2", self.CONTROL_SYSTEM, price_american=-110),
            GameResult(home_runs=1, away_runs=5), day="2026-08-31")

        # FORWARD_TEST: three settled bets, two wins one loss.
        forward = PaperAccount(system_id=self.FORWARD_SYSTEM)
        forward.settle_and_record(
            _bet("f-bet-1", self.FORWARD_SYSTEM, price_american=120),
            GameResult(home_runs=4, away_runs=1), day="2026-08-30")
        forward.settle_and_record(
            _bet("f-bet-2", self.FORWARD_SYSTEM, price_american=150),
            GameResult(home_runs=4, away_runs=1), day="2026-08-31")
        forward.settle_and_record(
            _bet("f-bet-3", self.FORWARD_SYSTEM, price_american=-130),
            GameResult(home_runs=0, away_runs=6), day="2026-09-01")

        self.wagers_path = Path(self._tmpdir.name) / "paper_wagers_v2.jsonl"
        wl = HashChainLedger(self.wagers_path)
        # Settled wagers (mirror the settled bets above).
        for bet_id, sid, day, event_id, game_pk, side, price in (
            ("c-bet-1", self.CONTROL_SYSTEM, "2026-08-30", "ev-1", 111, "home", 100),
            ("c-bet-2", self.CONTROL_SYSTEM, "2026-08-31", "ev-2", 222, "home", -110),
            ("f-bet-1", self.FORWARD_SYSTEM, "2026-08-30", "ev-1", 111, "home", 120),
            ("f-bet-2", self.FORWARD_SYSTEM, "2026-08-31", "ev-2", 222, "home", 150),
            ("f-bet-3", self.FORWARD_SYSTEM, "2026-09-01", "ev-3", 333, "home", -130),
        ):
            wl.append({
                "bet_id": bet_id, "date": day,
                "decision_utc": f"{day}T12:00:00+00:00",
                "event_id": event_id, "game_pk": game_pk, "label": "PAPER",
                "market_key": "h2h", "line": None, "price_american": price,
                "selection_id": side, "selection_rule": "TEST",
                "settlement_rule": "h2h", "side": side, "stake_units": 1.0,
                "system_id": sid,
            })
        # One pending wager (not settled in either account) on a later date.
        wl.append({
            "bet_id": "f-bet-pending", "date": "2026-09-05",
            "decision_utc": "2026-09-05T12:00:00+00:00",
            "event_id": "ev-4", "game_pk": 444, "label": "PAPER",
            "market_key": "h2h", "line": None, "price_american": -105,
            "selection_id": "home", "selection_rule": "TEST",
            "settlement_rule": "h2h", "side": "home", "stake_units": 1.0,
            "system_id": self.FORWARD_SYSTEM,
        })

        self.event_game_map_path = Path(self._tmpdir.name) / "event_game_map.jsonl"
        with self.event_game_map_path.open("w", encoding="utf-8") as fh:
            import json
            for game_pk, away, home, event_id in (
                (111, "Boston Red Sox", "New York Yankees", "ev-1"),
                (222, "Los Angeles Dodgers", "San Francisco Giants", "ev-2"),
                (333, "Chicago Cubs", "Milwaukee Brewers", "ev-3"),
                # 444 intentionally omitted -- covers the "no map row" path.
            ):
                fh.write(json.dumps({
                    "game_pk": game_pk, "away_team": away, "home_team": home,
                    "event_id": event_id, "resolved": True,
                }) + "\n")

        self.boxscores_path = Path(self._tmpdir.name) / "boxscores.jsonl"
        with self.boxscores_path.open("w", encoding="utf-8") as fh:
            pass  # empty on purpose: 444 stays unresolved by design

        self.review_path = Path(self._tmpdir.name) / "reviews_v2.jsonl"
        rl = HashChainLedger(self.review_path)
        # Joined (5-tuple), UNTESTED, win.
        rl.append(_review_row(
            ("ev-1", self.CONTROL_SYSTEM, "h2h", "home", "2026-08-30T12:00:00+00:00"),
            "win"))
        # Joined (5-tuple), CONFIRMED, win.
        rl.append(_review_row(
            ("ev-1", self.FORWARD_SYSTEM, "h2h", "home", "2026-08-30T12:00:00+00:00"),
            "win", checks=[{"name": "x", "expected": 1, "observed": 1,
                           "verdict": "confirmed"}]))
        # Joined (5-tuple), VARIANCE (confirmed checks, but a loss).
        rl.append(_review_row(
            ("ev-3", self.FORWARD_SYSTEM, "h2h", "home", "2026-09-01T12:00:00+00:00"),
            "loss", checks=[{"name": "x", "expected": 1, "observed": 1,
                            "verdict": "confirmed"}]))
        # Legacy 4-tuple -- can never join under the 5-field scheme.
        rl.append(_review_row(
            ("ev-2", self.CONTROL_SYSTEM, "h2h", "2026-08-31T12:00:00+00:00"),
            "loss"))

        self.scorecard_path = Path(self._tmpdir.name) / "scorecards_v2.jsonl"
        sl = HashChainLedger(self.scorecard_path)
        sl.append({"system_id": self.CONTROL_SYSTEM, "window": "2026-08-31",
                   "account": {"profit_units": 0.0}})
        sl.append({"system_id": self.FORWARD_SYSTEM, "window": "2026-09-01",
                   "account": {"profit_units": 0.0}})

    def _kwargs(self):
        return dict(
            accounts_dir=self.accounts_dir, wagers_path=self.wagers_path,
            event_game_map_path=self.event_game_map_path,
            boxscores_path=self.boxscores_path,
        )

    def _payload_kwargs(self):
        out = dict(self._kwargs())
        out["review_path"] = self.review_path
        out["scorecard_path"] = self.scorecard_path
        return out


class SettledBetsBySystemTests(_HermeticBase):
    def test_returns_a_tuple_per_system(self):
        out = pp.settled_bets_by_system(self.accounts_dir)
        self.assertEqual(set(out), {self.CONTROL_SYSTEM, self.FORWARD_SYSTEM})
        self.assertEqual(len(out[self.CONTROL_SYSTEM]), 2)
        self.assertEqual(len(out[self.FORWARD_SYSTEM]), 3)

    def test_missing_dir_is_empty(self):
        self.assertEqual(pp.settled_bets_by_system(Path("/no/such/dir")), {})


class SystemStandingsTests(_HermeticBase):
    def test_control_standing_shape_and_values(self):
        standings = {s["system_id"]: s for s in pp.system_standings(self.accounts_dir)}
        control = standings[self.CONTROL_SYSTEM]
        expected_keys = {
            "system_id", "system_class", "n_settled", "wins", "losses",
            "pushes", "hit_rate", "units_staked", "units_net",
            "return_on_units", "bankroll", "drawdown_max",
            "avg_odds_decimal", "first_day", "last_day",
        }
        self.assertEqual(set(control), expected_keys)
        self.assertEqual(control["system_class"], pp.CONTROL)
        self.assertEqual(control["n_settled"], 2)
        self.assertEqual(control["wins"], 1)
        self.assertEqual(control["losses"], 1)
        self.assertEqual(control["units_staked"], 2.0)
        self.assertAlmostEqual(control["units_net"], 0.0, places=6)
        self.assertEqual(control["first_day"], "2026-08-30")
        self.assertEqual(control["last_day"], "2026-08-31")

    def test_forward_test_classified_correctly(self):
        standings = {s["system_id"]: s for s in pp.system_standings(self.accounts_dir)}
        forward = standings[self.FORWARD_SYSTEM]
        self.assertEqual(forward["system_class"], pp.FORWARD_TEST)
        self.assertEqual(forward["n_settled"], 3)
        self.assertEqual(forward["wins"], 2)
        self.assertEqual(forward["losses"], 1)

    def test_missing_accounts_dir_is_empty_list(self):
        self.assertEqual(pp.system_standings(Path("/no/such/dir")), [])


class ClassRollupsTests(_HermeticBase):
    def test_rollup_keys_and_totals(self):
        standings = pp.system_standings(self.accounts_dir)
        bets_by_system = pp.settled_bets_by_system(self.accounts_dir)
        rollups = pp.class_rollups(standings, bets_by_system, self.accounts_dir)
        self.assertEqual(set(rollups), {pp.CONTROL, pp.MARKET_REFERENCE,
                                        pp.FORWARD_TEST, pp.ALL_SYSTEMS})
        expected_keys = {
            "n_settled", "wins", "losses", "pushes", "units_staked",
            "units_net", "return_on_units", "hit_rate", "drawdown_max",
        }
        self.assertEqual(set(rollups[pp.CONTROL]), expected_keys)
        self.assertEqual(rollups[pp.CONTROL]["n_settled"], 2)
        self.assertEqual(rollups[pp.FORWARD_TEST]["n_settled"], 3)
        self.assertEqual(rollups[pp.ALL_SYSTEMS]["n_settled"], 5)
        self.assertEqual(rollups[pp.MARKET_REFERENCE]["n_settled"], 0)

    def test_missing_dir_still_returns_all_four_zeroed_buckets(self):
        rollups = pp.class_rollups([], {}, Path("/no/such/dir"))
        self.assertEqual(set(rollups), {pp.CONTROL, pp.MARKET_REFERENCE,
                                        pp.FORWARD_TEST, pp.ALL_SYSTEMS})
        for bucket in rollups.values():
            self.assertEqual(bucket["n_settled"], 0)


class CumulativeSeriesTests(_HermeticBase):
    def test_one_point_per_settled_day(self):
        series = pp.cumulative_series(pp.FORWARD_TEST, self.accounts_dir)
        self.assertEqual([pt["day"] for pt in series],
                         ["2026-08-30", "2026-08-31", "2026-09-01"])
        # Running total must be monotonically accumulated, not reset.
        self.assertNotEqual(series[0]["units_net"], series[-1]["units_net"])


class RecentPicksTests(_HermeticBase):
    def test_newest_first_and_pending_detection(self):
        picks = pp.recent_picks(limit=50, **self._kwargs())
        self.assertEqual(len(picks), 6)
        self.assertEqual(picks[0]["bet_id"], "f-bet-pending")
        self.assertEqual(picks[0]["outcome"], "pending")
        self.assertIsNone(picks[0]["profit_units"])
        # Newest-first ordering by day.
        days = [p["day"] for p in picks]
        self.assertEqual(days, sorted(days, reverse=True))

    def test_settled_picks_carry_real_outcome_and_matchup(self):
        picks = {p["bet_id"]: p for p in pp.recent_picks(limit=50, **self._kwargs())}
        c1 = picks["c-bet-1"]
        self.assertEqual(c1["outcome"], "win")
        self.assertEqual(c1["matchup"], "BOS @ NYY")
        self.assertEqual(c1["system_class"], pp.CONTROL)

    def test_unresolved_matchup_falls_back_honestly(self):
        picks = {p["bet_id"]: p for p in pp.recent_picks(limit=50, **self._kwargs())}
        pending = picks["f-bet-pending"]
        self.assertTrue(pending["matchup"].startswith("event "))
        self.assertIsNone(pending["away_team"])
        self.assertEqual(pp.unresolved_matchup_count(list(picks.values())), 1)

    def test_limit_is_respected(self):
        picks = pp.recent_picks(limit=2, **self._kwargs())
        self.assertEqual(len(picks), 2)

    def test_exact_keys(self):
        picks = pp.recent_picks(limit=50, **self._kwargs())
        expected = {"day", "date", "away_team", "home_team", "matchup",
                   "market_key", "side", "line", "price_american",
                   "system_id", "system_class", "outcome", "profit_units",
                   "bet_id"}
        for p in picks:
            self.assertEqual(set(p), expected)

    def test_missing_wagers_file_is_empty(self):
        self.assertEqual(pp.recent_picks(wagers_path=Path("/no/such.jsonl")), [])


class ReasoningSplitTests(_HermeticBase):
    def test_matrix_and_counts(self):
        split = pp.reasoning_split(review_path=self.review_path)
        self.assertEqual(split["counts"]["UNTESTED"], 2)
        self.assertEqual(split["counts"]["CONFIRMED"], 1)
        self.assertEqual(split["counts"]["VARIANCE"], 1)
        self.assertEqual(split["matrix"]["won_reasoning_confirmed"], 1)
        self.assertEqual(split["matrix"]["lost_reasoning_confirmed"], 1)
        self.assertEqual(split["matrix"]["untested"], 2)
        self.assertEqual(split["joined"], 3)
        self.assertEqual(split["unjoinable_legacy"], 1)
        self.assertIn("UNTESTED", split["note"])

    def test_missing_review_file_is_empty_but_structured(self):
        split = pp.reasoning_split(review_path=Path("/no/such.jsonl"))
        self.assertEqual(split["joined"], 0)
        self.assertEqual(split["unjoinable_legacy"], 0)
        self.assertEqual(sum(split["counts"].values()), 0)


class FreshnessTests(_HermeticBase):
    def test_shape_and_values(self):
        fresh = pp.freshness(
            self.accounts_dir, wagers_path=self.wagers_path,
            scorecard_path=self.scorecard_path)
        self.assertEqual(fresh["settled_through"], "2026-09-01")
        self.assertEqual(fresh["pending_wagers"], 1)
        self.assertEqual(fresh["pending_dates"], ["2026-09-05"])
        self.assertEqual(fresh["wagers_total"], 6)
        self.assertEqual(
            fresh["latest_scorecard_windows"][self.CONTROL_SYSTEM],
            "2026-08-31")

    def test_missing_everything_is_honestly_empty(self):
        fresh = pp.freshness(Path("/no/dir"), wagers_path=Path("/no/w.jsonl"),
                             scorecard_path=Path("/no/s.jsonl"))
        self.assertIsNone(fresh["settled_through"])
        self.assertEqual(fresh["pending_wagers"], 0)
        self.assertEqual(fresh["wagers_total"], 0)


class BuildPerformancePayloadTests(_HermeticBase):
    def test_full_payload_shape(self):
        payload = pp.build_performance_payload(limit=10, **self._payload_kwargs())
        for key in ("label", "generated_at", "disclaimer", "freshness",
                   "classes", "systems", "recent_picks", "reasoning_split",
                   "series", "notes"):
            self.assertIn(key, payload)
        self.assertEqual(payload["label"], "PAPER / RESEARCH PERFORMANCE")
        self.assertIn(pp.FORWARD_TEST, payload["series"])
        self.assertIn(pp.ALL_SYSTEMS, payload["series"])

    def test_systems_sorted_forward_test_first(self):
        payload = pp.build_performance_payload(limit=10, **self._payload_kwargs())
        classes_in_order = [s["system_class"] for s in payload["systems"]]
        self.assertEqual(classes_in_order[0], pp.FORWARD_TEST)

    def test_notes_flag_the_one_unresolved_matchup(self):
        payload = pp.build_performance_payload(limit=10, **self._payload_kwargs())
        self.assertTrue(any("could not be matched" in n for n in payload["notes"]))

    def test_fully_missing_stores_never_raises(self):
        payload = pp.build_performance_payload(
            limit=10, accounts_dir=Path("/no/dir"),
            wagers_path=Path("/no/w.jsonl"),
            event_game_map_path=Path("/no/m.jsonl"),
            boxscores_path=Path("/no/b.jsonl"),
            review_path=Path("/no/r.jsonl"),
            scorecard_path=Path("/no/s.jsonl"))
        self.assertEqual(payload["systems"], [])
        self.assertEqual(payload["recent_picks"], [])


# Every banned-vocabulary rule tests.test_customer_language enforces on
# src/report/*.py applies to this module's own literal strings too --
# checked directly here as a fast, self-contained tripwire (the shared
# scan in tests/test_customer_language.py already covers the file; this
# pins the specific literals this module owns).
class BannedVocabularyTests(unittest.TestCase):
    _BANNED = re.compile(
        r"\b(lock|guaranteed?|sure thing|can'?t lose|win[- ]probabilit\w*)\b"
        r"|\bEV\b|\bCLV\b",
        re.IGNORECASE)

    def test_label_disclaimer_and_note_are_clean(self):
        for text in (pp.LABEL, pp.DISCLAIMER, pp._UNTESTED_NOTE):
            self.assertNotRegex(text, self._BANNED, text)

    def test_edge_never_appears_unnegated(self):
        for text in (pp.LABEL, pp.DISCLAIMER, pp._UNTESTED_NOTE):
            self.assertNotIn("edge", text.lower())


class RealLedgerReconciliationTests(unittest.TestCase):
    """Cross-checks `system_standings().units_net` against the latest
    `scorecards_v2.jsonl` row's `account.profit_units` for every system
    whose latest scorecard window equals its last settled day -- the one
    case where the two are supposed to describe the exact same point in
    time. Skips cleanly when there is no real `data/paper_accounts` to
    check (a fresh checkout that has never run a slate)."""

    def test_units_net_matches_latest_scorecard_profit(self):
        from src.paths import data_path

        accounts_dir = data_path("paper_accounts")
        if not accounts_dir.exists():
            self.skipTest("data/paper_accounts is absent in this checkout")

        standings = {s["system_id"]: s for s in pp.system_standings()}
        latest_windows_rows = {}
        for row in HashChainLedger(
                Path(__file__).resolve().parent.parent
                / "evidence" / "scorecards_v2.jsonl").read():
            sid, window = row.get("system_id"), row.get("window")
            if not sid or window is None:
                continue
            if sid not in latest_windows_rows or str(window) > str(
                    latest_windows_rows[sid]["window"]):
                latest_windows_rows[sid] = row

        mismatches = []
        checked = 0
        for system_id, standing in standings.items():
            row = latest_windows_rows.get(system_id)
            if row is None or row["window"] != standing["last_day"]:
                continue
            checked += 1
            expected = row["account"]["profit_units"]
            actual = standing["units_net"]
            if abs(expected - actual) > 1e-6:
                mismatches.append(
                    f"{system_id}: scorecard.profit_units={expected!r} != "
                    f"standings.units_net={actual!r} (window={row['window']!r})")

        self.assertEqual(
            mismatches, [],
            "units_net disagrees with the latest same-day scorecard for "
            f"{len(mismatches)} system(s):\n" + "\n".join(mismatches))
        if checked == 0:
            self.skipTest(
                "no system's latest scorecard window equals its last "
                "settled day in this checkout -- nothing to reconcile")


if __name__ == "__main__":
    unittest.main()
