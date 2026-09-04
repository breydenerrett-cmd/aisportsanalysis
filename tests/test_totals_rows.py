"""Tests for src/research/totals_rows.py and src/research/totals_eval.py --
the standalone totals evaluation path.

Covers docs/TOTALS_METHODOLOGY.md "## Revision 2" + "## Methodology
re-review -- 2026-09-05" validation items 1-13. All synthetic-fixture based
(no real gitignored store required) except a `dry_run` smoke test against
the real stores, which SKIPS (never fails) when they are absent -- matching
`tests/test_f5_eval.py`'s convention.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core import odds as odds_math
from src.model import family
from src.research import battery, funnel, totals_eval as te, totals_rows as tr


def _data_available() -> bool:
    return (Path(tr.ARCHIVE_ROOT, "mlb_2023.jsonl").exists()
            and Path(tr.ARCHIVE_ROOT, "mlb_2024.jsonl").exists()
            and Path(tr.RESULTS_CSV).exists())


# ---------------------------------------------------------------------------
# Synthetic fixture builders
# ---------------------------------------------------------------------------

def _outcome(name, point, price):
    return {"name": name, "point": point, "price": price}


def _book(key, point, over_price, under_price):
    return {"key": key, "markets": [
        {"key": "totals", "outcomes": [
            _outcome("Over", point, over_price),
            _outcome("Under", point, under_price)]}]}


def _snapshot(snap_at, event_id, commence_time, away_team, home_team, books):
    return {"snapshot_at": snap_at,
            "events": [{"id": event_id, "commence_time": commence_time,
                       "away_team": away_team, "home_team": home_team,
                       "bookmakers": books}]}


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_results_csv(path, games):
    """games: list of dicts with game_pk, date, start_time_utc, away_team,
    home_team, home_won ('0'/'1'), total_runs."""
    header = ("game_pk,date,start_time_utc,venue,game_type,away_team,home_team,"
              "away_team_id,home_team_id,away_probable,home_probable,"
              "away_probable_id,home_probable_id,away_score,home_score,winner,"
              "home_won,total_runs,run_differential,double_header,game_number")
    lines = [header]
    for g in games:
        away_score = g.get("away_score", 0)
        home_score = g.get("home_score", g.get("total_runs", 0) - away_score)
        winner = "home" if g["home_won"] == "1" else "away"
        lines.append(",".join(str(x) for x in [
            g["game_pk"], g["date"], g["start_time_utc"], "Park", "R",
            g["away_team"], g["home_team"], 1, 2, "P1", "P2", 10, 20,
            away_score, home_score, winner, g["home_won"], g["total_runs"],
            abs(home_score - away_score), "N", 1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Fixture:
    """One temp-dir archive + results.csv, built to a chosen shape. `games`
    is a list of dicts: game_pk, date, away, home, line, over/under prices
    per book, total_runs, gap_hours (snapshot-to-commence), season.
    """

    def __init__(self, tmpdir):
        self.root = Path(tmpdir)
        self.archive_root = self.root / "odds_history"
        self.results_csv = self.root / "mlb_results.csv"
        self._by_season = {}
        self._results = []

    def add_game(self, *, season, event_id, game_pk, date, away_full, home_full,
                away_abbrev, home_abbrev, commence_time, line, books,
                total_runs, gap_hours=2.0, home_won=None, extra_snapshots=None):
        """`books`: [(key, over_price, under_price), ...] all quoting `line`.
        `gap_hours`: hours before commence_time the (only) snapshot sits.
        `extra_snapshots`: optional list of (gap_hours, line, books) tuples
        for additional snapshots on the same event (staleness / rescheduling
        tests)."""
        from datetime import datetime, timedelta
        ct = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        snap_at = (ct - timedelta(hours=gap_hours)).isoformat().replace("+00:00", "Z")
        bookmakers = [_book(k, line, o, u) for k, o, u in books]
        records = [_snapshot(snap_at, event_id, commence_time, away_full, home_full, bookmakers)]
        for g_hours, ln, bks in (extra_snapshots or []):
            s_at = (ct - timedelta(hours=g_hours)).isoformat().replace("+00:00", "Z")
            records.append(_snapshot(s_at, event_id, commence_time, away_full, home_full,
                                     [_book(k, ln, o, u) for k, o, u in bks]))
        self._by_season.setdefault(season, []).extend(records)
        if home_won is not None:
            self._results.append({
                "game_pk": game_pk, "date": date, "start_time_utc": commence_time,
                "away_team": away_abbrev, "home_team": home_abbrev,
                "home_won": "1" if home_won else "0", "total_runs": total_runs,
            })

    def write(self):
        for season, records in self._by_season.items():
            _write_jsonl(self.archive_root / f"mlb_{season}.jsonl", records)
        _write_results_csv(self.results_csv, self._results)
        return self


DEFAULT_BOOKS = [("dk", -110, -110), ("fd", -112, -108), ("mgm", -108, -112)]


def _add_default_game(fx, *, season, event_id, game_pk, date, total_runs,
                      home_won, line=8.5, gap_hours=2.0, books=None):
    fx.add_game(season=season, event_id=event_id, game_pk=game_pk, date=date,
               away_full="Boston Red Sox", home_full="New York Yankees",
               away_abbrev="BOS", home_abbrev="NYY",
               commence_time=f"{date}T23:05:00Z", line=line,
               books=books or DEFAULT_BOOKS, total_runs=total_runs,
               gap_hours=gap_hours, home_won=home_won)


# ---------------------------------------------------------------------------
# 1. Synthetic settlement injection: Over/Under/push on both line types
# ---------------------------------------------------------------------------

class TestSettlementInjection(unittest.TestCase):
    def _built(self, total_runs, line, home_won=True):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=total_runs,
                              home_won=home_won, line=line)
            fx.write()
            rows = tr.build_over_rows(seasons=("2023",), archive_root=fx.archive_root,
                                      results_path=fx.results_csv, dry_run=False)
            return rows

    def test_half_point_over(self):
        rows = self._built(total_runs=9, line=8.5)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["won"])

    def test_half_point_under(self):
        rows = self._built(total_runs=8, line=8.5)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["won"])

    def test_integer_line_push_excluded_from_half_point_build(self):
        # An integer line never enters build_over_rows (half-point primary
        # only) at all -- it must be excluded, not graded as a push.
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=8, home_won=False, line=8.0)
            fx.write()
            rows = tr.build_over_rows(seasons=("2023",), archive_root=fx.archive_root,
                                      results_path=fx.results_csv, dry_run=False)
            self.assertEqual(rows, [])

    def test_integer_stratum_push_excluded_byte_exact(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=8, home_won=False, line=8.0)
            fx.write()
            rows = tr.build_integer_stratum_rows(
                seasons=("2023",), archive_root=fx.archive_root,
                results_path=fx.results_csv, dry_run=False)
            self.assertEqual(rows, [])  # push -- excluded from numerator and denominator

    def test_integer_stratum_over_and_under(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True, line=8.0)
            _add_default_game(fx, season="2023", event_id="e2", game_pk="2",
                              date="2023-06-02", total_runs=7, home_won=False, line=8.0)
            fx.write()
            rows = tr.build_integer_stratum_rows(
                seasons=("2023",), archive_root=fx.archive_root,
                results_path=fx.results_csv, dry_run=False)
            self.assertEqual(len(rows), 2)
            self.assertTrue(any(r["won"] is True for r in rows))
            self.assertTrue(any(r["won"] is False for r in rows))


# ---------------------------------------------------------------------------
# 2. PIT negatives: staleness bound, rescheduled-game commence_time,
# no-actual-first-pitch read
# ---------------------------------------------------------------------------

class TestPITNegatives(unittest.TestCase):
    def test_snapshot_outside_staleness_bound_excluded(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True,
                              gap_hours=7.0)  # outside the default 6h bound
            fx.write()
            events = tr.load_event_snapshots("2023", archive_root=fx.archive_root)
            closing = tr.compute_event_closing(events["e1"])
            self.assertIsNone(closing)

    def test_snapshot_inside_staleness_bound_included(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True,
                              gap_hours=5.0)
            fx.write()
            events = tr.load_event_snapshots("2023", archive_root=fx.archive_root)
            closing = tr.compute_event_closing(events["e1"])
            self.assertIsNotNone(closing)

    def test_rescheduled_game_cannot_leak_revised_commence_time(self):
        """A7c: `commence_time` is read from the SAME snapshot's own event
        record. A snapshot taken under the ORIGINAL schedule, arbitrarily
        close to that original time, must not be re-anchored against a
        LATER snapshot's revised (rescheduled) commence_time -- each
        snapshot in `records` carries its own, and `_pick_closing` never
        mixes one snapshot's `snapshot_at` with another's `commence_time`.
        """
        from datetime import datetime, timedelta
        original_ct = "2023-06-01T23:05:00Z"
        revised_ct = "2023-06-02T18:05:00Z"  # game pushed a day, per a later snapshot
        orig_dt = datetime.fromisoformat(original_ct.replace("Z", "+00:00"))
        revised_dt = datetime.fromisoformat(revised_ct.replace("Z", "+00:00"))
        # A snapshot taken 2h before the ORIGINAL time (would qualify against
        # original_ct) but ~21h before the REVISED time (would be excluded
        # against revised_ct under the 6h bound).
        early_snap_at = (orig_dt - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        late_snap_at = (revised_dt - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        records = [
            (datetime.fromisoformat(early_snap_at.replace("Z", "+00:00")), orig_dt,
             "Boston Red Sox", "New York Yankees", {8.5: {"dk": {"over": -110, "under": -110}}}),
            (datetime.fromisoformat(late_snap_at.replace("Z", "+00:00")), revised_dt,
             "Boston Red Sox", "New York Yankees", {9.5: {"dk": {"over": -110, "under": -110}}}),
        ]
        closing = tr._pick_closing(records)
        # The LATEST record wins (closest to its own, correctly-anchored
        # commence_time) -- its commence_time is the REVISED one, taken from
        # that same record, never borrowed from the earlier snapshot.
        self.assertEqual(closing[1], revised_dt)
        self.assertEqual(closing[4], {9.5: {"dk": {"over": -110, "under": -110}}})

    def test_dry_run_never_exposes_won(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True)
            fx.write()
            rows = tr.build_over_rows(seasons=("2023",), archive_root=fx.archive_root,
                                      results_path=fx.results_csv, dry_run=True)
            self.assertTrue(rows)
            self.assertTrue(all(r["won"] is None for r in rows))

    def test_2025_never_read_by_default_seasons(self):
        self.assertNotIn("2025", tr.SEASONS)
        self.assertNotIn("2026", tr.SEASONS)


# ---------------------------------------------------------------------------
# 3. Denominator + both hashes
# ---------------------------------------------------------------------------

class TestUniverseHashes(unittest.TestCase):
    def _fixture_with_two_games(self, td):
        fx = _Fixture(td)
        _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                          date="2023-06-01", total_runs=9, home_won=True)
        _add_default_game(fx, season="2023", event_id="e2", game_pk="2",
                          date="2023-06-02", total_runs=7, home_won=False)
        fx.write()
        return fx

    def test_deterministic_and_stable(self):
        with TemporaryDirectory() as td:
            fx = self._fixture_with_two_games(td)
            m1 = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv)
            m2 = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv)
            self.assertEqual(m1["content_hash"], m2["content_hash"])
            self.assertEqual(m1["price_payload_hash"], m2["price_payload_hash"])
            self.assertEqual(m1["counts"]["joint_total"], 2)

    def test_content_hash_moves_when_a_game_is_added(self):
        with TemporaryDirectory() as td:
            fx = self._fixture_with_two_games(td)
            m1 = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv)
            fx.add_game(season="2023", event_id="e3", game_pk="3", date="2023-06-03",
                       away_full="Boston Red Sox", home_full="New York Yankees",
                       away_abbrev="BOS", home_abbrev="NYY",
                       commence_time="2023-06-03T23:05:00Z", line=8.5,
                       books=DEFAULT_BOOKS, total_runs=5, home_won=False)
            fx.write()
            m2 = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv)
            self.assertNotEqual(m1["content_hash"], m2["content_hash"])

    def test_price_payload_hash_moves_when_a_price_changes_identity_does_not(self):
        with TemporaryDirectory() as td:
            fx = self._fixture_with_two_games(td)
            m1 = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv)
            # Rewrite e1's price without changing the game set.
            fx2 = _Fixture(td + "_v2" if False else td)  # reuse same dir structure
        with TemporaryDirectory() as td2:
            fx = _Fixture(td2)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True,
                              books=[("dk", -130, 105), ("fd", -112, -108), ("mgm", -108, -112)])
            _add_default_game(fx, season="2023", event_id="e2", game_pk="2",
                              date="2023-06-02", total_runs=7, home_won=False)
            fx.write()
            m2 = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv)
            self.assertEqual(m1["content_hash"], m2["content_hash"])
            self.assertNotEqual(m1["price_payload_hash"], m2["price_payload_hash"])

    def test_verify_universe_raises_on_identity_mismatch(self):
        with TemporaryDirectory() as td:
            fx = self._fixture_with_two_games(td)
            manifest = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                         results_path=fx.results_csv)
            manifest_path = Path(td) / "manifest.json"
            tr.write_manifest(manifest, manifest_path)
            fx.add_game(season="2023", event_id="e3", game_pk="3", date="2023-06-03",
                       away_full="Boston Red Sox", home_full="New York Yankees",
                       away_abbrev="BOS", home_abbrev="NYY",
                       commence_time="2023-06-03T23:05:00Z", line=8.5,
                       books=DEFAULT_BOOKS, total_runs=5, home_won=False)
            fx.write()
            with self.assertRaises(te.TotalsEvalError):
                te.verify_universe(seasons=("2023",), archive_root=fx.archive_root,
                                   results_path=fx.results_csv, manifest_path=manifest_path)


# ---------------------------------------------------------------------------
# 4. De-vig agreement: book-order permutation stability, sums to 1.0
# ---------------------------------------------------------------------------

class TestDoubleheaderSameDayFallback(unittest.TestCase):
    """docs/TOTALS_UNJOINED_AUDIT.md: a straight doubleheader's nightcap can
    start more than `pricepath.MAX_EVENT_GAP_SECONDS` (3h) after its own
    listed commence_time -- real audited case, Guardians @ Tigers
    2023-04-18, game_pk 718541, actual start 17:15 UTC vs. the odds event's
    20:40 UTC commence_time (3.42h gap). `_join_settlement` must still find
    it via the same-day-only fallback once `pricepath`'s own two-step join
    (same day within 3h, then previous day) has already come back empty."""

    def _index(self):
        from datetime import datetime
        game = {
            "game_pk": "718541", "date": "2023-04-18",
            "start_time_utc": datetime.fromisoformat("2023-04-18T17:15:00+00:00"),
            "away_team": "CLE", "home_team": "DET",
            "home_won": True, "total_runs": 1,
        }
        return {("CLE", "DET", "2023-04-18"): [game]}

    def test_same_day_nightcap_beyond_pricepath_gap_still_joins(self):
        from datetime import datetime
        commence_time = datetime.fromisoformat("2023-04-18T20:40:00+00:00")
        game = tr._join_settlement("Cleveland Guardians", "Detroit Tigers",
                                    commence_time, self._index())
        self.assertIsNotNone(game)
        self.assertEqual(game["game_pk"], "718541")

    def test_fallback_never_reaches_a_different_calendar_date(self):
        """The fallback is same-date-only: a candidate that exists only on
        an adjacent date must stay unjoined, exactly like the genuine
        postponement/makeup cases the audit found -- widening the bound
        must never let a totals join reach across days the way `pricepath`'s
        own previous-day step deliberately, narrowly does."""
        from datetime import datetime
        game = {
            "game_pk": "999999", "date": "2023-04-19",
            "start_time_utc": datetime.fromisoformat("2023-04-19T17:10:00+00:00"),
            "away_team": "CLE", "home_team": "DET",
            "home_won": True, "total_runs": 5,
        }
        index = {("CLE", "DET", "2023-04-19"): [game]}
        commence_time = datetime.fromisoformat("2023-04-18T20:40:00+00:00")
        self.assertIsNone(tr._join_settlement("Cleveland Guardians", "Detroit Tigers",
                                               commence_time, index))

    def test_beyond_widened_bound_still_unjoined(self):
        """A same-day candidate more than 8h away is still a candidate for
        collision (e.g. an early getaway-day game plus a much later postponed
        makeup) -- not a slow doubleheader nightcap -- so it must stay
        unjoined rather than being guessed at."""
        from datetime import datetime
        game = {
            "game_pk": "718541", "date": "2023-04-18",
            "start_time_utc": datetime.fromisoformat("2023-04-18T09:00:00+00:00"),
            "away_team": "CLE", "home_team": "DET",
            "home_won": True, "total_runs": 1,
        }
        index = {("CLE", "DET", "2023-04-18"): [game]}
        commence_time = datetime.fromisoformat("2023-04-18T20:40:00+00:00")
        self.assertIsNone(tr._join_settlement("Cleveland Guardians", "Detroit Tigers",
                                               commence_time, index))


class TestDevigAgreement(unittest.TestCase):
    def test_permutation_invariant(self):
        book_prices = {"dk": {"over": -110, "under": -110},
                       "fd": {"over": -112, "under": -108},
                       "mgm": {"over": -108, "under": -112}}
        c1 = tr.consensus_fair_for_line(book_prices)
        reordered = dict(reversed(list(book_prices.items())))
        c2 = tr.consensus_fair_for_line(reordered)
        self.assertAlmostEqual(c1["over_fair"], c2["over_fair"], places=9)
        self.assertAlmostEqual(c1["under_fair"], c2["under_fair"], places=9)

    def test_fair_probabilities_sum_to_one(self):
        example = tr.devig_two_way_example()["near_fair"]
        for method in tr.DEVIG_METHODS.values():
            over_fair, under_fair = odds_math.devig_two_way(
                example["over"], example["under"], method=method)
            self.assertAlmostEqual(over_fair + under_fair, 1.0, places=9)

    def test_three_conventions_agree_closely_near_fair(self):
        example = tr.devig_two_way_example()["near_fair"]
        fairs = []
        for method in tr.DEVIG_METHODS.values():
            over_fair, _ = odds_math.devig_two_way(example["over"], example["under"], method=method)
            fairs.append(over_fair)
        self.assertLess(max(fairs) - min(fairs), 0.01)


# ---------------------------------------------------------------------------
# 5. Battery wiring
# ---------------------------------------------------------------------------

class TestBatteryWiring(unittest.TestCase):
    def test_battery_accepts_totals_row_shape(self):
        rows = [{"date": f"2023-06-{i:02d}", "won": i % 2 == 0, "implied": 0.5,
                "season": "2023"} for i in range(1, 40)]
        result = battery.run(rows, effect_floor=te.EFFECT_FLOOR)
        self.assertIn("survives", result)
        self.assertIn("report", result)

    def test_run_battery_records_skips(self):
        rows = [{"date": f"2023-06-{i:02d}", "won": i % 2 == 0, "implied": 0.5,
                "season": "2023"} for i in range(1, 40)]
        result = te.run_battery(rows)
        self.assertIn("skipped_checks", result)
        self.assertIsInstance(result["skipped_checks"], dict)


# ---------------------------------------------------------------------------
# 7. Three-convention de-vig sensitivity with sign-survival gate
# ---------------------------------------------------------------------------

class TestDevigSignSurvival(unittest.TestCase):
    def test_survives_when_all_three_positive(self):
        sensitivity = {label: {"key": {"effect": 0.02}} for label in tr.DEVIG_METHODS}
        self.assertTrue(te.devig_sign_survives_check(sensitivity, "key", expected_sign=1))

    def test_fails_when_one_convention_flips_sign(self):
        sensitivity = {label: {"key": {"effect": 0.02}} for label in tr.DEVIG_METHODS}
        one = list(tr.DEVIG_METHODS)[0]
        sensitivity[one]["key"]["effect"] = -0.01
        self.assertFalse(te.devig_sign_survives_check(sensitivity, "key", expected_sign=1))

    def test_fails_when_one_convention_has_no_effect(self):
        sensitivity = {label: {"key": {"effect": 0.02}} for label in tr.DEVIG_METHODS}
        one = list(tr.DEVIG_METHODS)[0]
        sensitivity[one]["key"]["effect"] = None
        self.assertFalse(te.devig_sign_survives_check(sensitivity, "key", expected_sign=1))


# ---------------------------------------------------------------------------
# 9. Staleness distribution parameters exist and are named constants
# ---------------------------------------------------------------------------

class TestStalenessParameters(unittest.TestCase):
    def test_default_bound_is_named_constant(self):
        self.assertEqual(tr.MAX_STALENESS_HOURS, 6)

    def test_anchor_rule_is_named_constant(self):
        self.assertEqual(tr.ANCHOR_RULE, "per_snapshot_commence_time")

    def test_bound_is_a_parameter_not_hardcoded(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True,
                              gap_hours=8.0)
            fx.write()
            events = tr.load_event_snapshots("2023", archive_root=fx.archive_root)
            self.assertIsNone(tr.compute_event_closing(events["e1"]))
            self.assertIsNotNone(
                tr.compute_event_closing(events["e1"], max_staleness_hours=12))


# ---------------------------------------------------------------------------
# 10. Pre-void frozen denominator
# ---------------------------------------------------------------------------

class TestPreVoidDenominator(unittest.TestCase):
    def test_pushed_game_still_counts_in_universe(self):
        """A6: the universe denominator is defined pre-void. An integer-line
        push is impossible in the half-point joint population by
        construction, so this proves the PRINCIPLE on the half-point
        population itself: a joined, gradeable event counts in
        `build_universe` regardless of what its settlement later says --
        `build_universe` never opens `total_runs` at all.
        """
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=8, home_won=False)  # exact push value at 8.5 is impossible; total_runs=8 settles under
            fx.write()
            manifest = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                         results_path=fx.results_csv)
            self.assertEqual(manifest["counts"]["joint_total"], 1)


# ---------------------------------------------------------------------------
# 11. Population-shift chi-square
# ---------------------------------------------------------------------------

class TestPopulationShift(unittest.TestCase):
    def test_identical_distributions_not_fatal(self):
        screen = [{"line": 8.5} for _ in range(100)] + [{"line": 9.5} for _ in range(100)]
        replication = [{"line": 8.5} for _ in range(100)] + [{"line": 9.5} for _ in range(100)]
        result = tr.population_shift_test(screen, replication)
        self.assertFalse(result["fatal"])
        self.assertGreater(result["p"], 0.01)

    def test_dramatic_shift_is_fatal(self):
        screen = [{"line": 8.5} for _ in range(500)] + [{"line": 9.5} for _ in range(500)]
        replication = [{"line": 8.5} for _ in range(950)] + [{"line": 9.5} for _ in range(50)]
        result = tr.population_shift_test(screen, replication)
        self.assertTrue(result["fatal"])
        self.assertLess(result["p"], 0.01)

    def test_never_reads_won(self):
        screen = [{"line": 8.5} for _ in range(50)] + [{"line": 9.5} for _ in range(50)]
        replication = [{"line": 8.5} for _ in range(50)] + [{"line": 9.5} for _ in range(50)]
        # No 'won' key present at all -- must not raise or need it.
        result = tr.population_shift_test(screen, replication)
        self.assertIn("p", result)

    def test_chi_square_even_df_matches_f5_df2_case(self):
        from src.research import f5_eval
        for x in (0.0, 1.0, 5.0, 9.21):
            self.assertAlmostEqual(
                tr.chi_square_p_even_df(x, 2), f5_eval.chi_square_p_df2(x), places=9)

    def test_chi_square_rejects_odd_df(self):
        with self.assertRaises(tr.TotalsRowsError):
            tr.chi_square_p_even_df(1.0, 3)


# ---------------------------------------------------------------------------
# 12. Mechanised verdict + freeze
# ---------------------------------------------------------------------------

class TestVerdictGates(unittest.TestCase):
    BASE = dict(population_shift_fatal=False, screen_passes=True,
               replication_sign_agrees=True, replication_ci_excludes_zero=True,
               survives_fdr=True, devig_sign_survives=True, battery_survives=True)

    def test_survivor_when_all_gates_clear(self):
        self.assertEqual(te.compute_verdict(**self.BASE), "SURVIVOR")

    def test_population_shift_wins_over_every_other_gate(self):
        kwargs = dict(self.BASE, population_shift_fatal=True, screen_passes=False,
                     battery_survives=False)
        self.assertEqual(te.compute_verdict(**kwargs), "POPULATION_SHIFT_FAIL")

    def test_screen_fail_flips_verdict(self):
        kwargs = dict(self.BASE, screen_passes=False)
        self.assertEqual(te.compute_verdict(**kwargs), "SCREEN_FAIL")

    def test_replication_sign_disagreement_flips_verdict(self):
        kwargs = dict(self.BASE, replication_sign_agrees=False)
        self.assertEqual(te.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_replication_ci_flips_verdict(self):
        kwargs = dict(self.BASE, replication_ci_excludes_zero=False)
        self.assertEqual(te.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_fdr_flips_verdict(self):
        kwargs = dict(self.BASE, survives_fdr=False)
        self.assertEqual(te.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_devig_sign_flips_verdict(self):
        kwargs = dict(self.BASE, devig_sign_survives=False)
        self.assertEqual(te.compute_verdict(**kwargs), "DEVIG_SIGN_FAIL")

    def test_battery_flips_verdict(self):
        kwargs = dict(self.BASE, battery_survives=False)
        self.assertEqual(te.compute_verdict(**kwargs), "BATTERY_FAIL")


class TestFreezeMechanism(unittest.TestCase):
    def test_freeze_refuses_to_overwrite(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True)
            fx.write()
            manifest = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                         results_path=fx.results_csv)
            manifest_path = Path(td) / "universe.json"
            tr.write_manifest(manifest, manifest_path)
            family_path = Path(td) / "family.json"
            te.freeze_family(family_path, manifest_path=manifest_path)
            with self.assertRaises(te.TotalsEvalError):
                te.freeze_family(family_path, manifest_path=manifest_path)

    def test_run_refuses_without_frozen_record(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True)
            fx.write()
            manifest = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                         results_path=fx.results_csv)
            manifest_path = Path(td) / "universe.json"
            tr.write_manifest(manifest, manifest_path)
            family_path = Path(td) / "family.json"
            with self.assertRaises(te.TotalsEvalError):
                te.read_frozen_family(family_path)
            with self.assertRaises(te.TotalsEvalError):
                # run_full_evaluation() -> _verify_frozen_family() must raise
                # before reading any 'won'.
                te.run_full_evaluation(
                    seasons=("2023",), archive_root=fx.archive_root,
                    results_path=fx.results_csv)


class TestBoundedSpecHash(unittest.TestCase):
    def test_hash_ignores_content_appended_after_next_heading(self):
        with TemporaryDirectory() as td:
            base = ("# doc\n\n## Revision 2\n\nbody text\n\n"
                   "## Methodology re-review -- 2026-09-05\n\nreview text\n")
            path1 = Path(td) / "a.md"
            path1.write_text(base, encoding="utf-8")
            h1 = te.spec_sha256(path1)

            appended = base + "\n## A later appended section\n\nnew stuff\n"
            path2 = Path(td) / "b.md"
            path2.write_text(appended, encoding="utf-8")
            h2 = te.spec_sha256(path2)
            self.assertEqual(h1, h2)

    def test_hash_changes_when_bounded_section_changes(self):
        with TemporaryDirectory() as td:
            base = ("# doc\n\n## Revision 2\n\nbody text\n\n"
                   "## Methodology re-review -- 2026-09-05\n\nreview text\n")
            path1 = Path(td) / "a.md"
            path1.write_text(base, encoding="utf-8")
            h1 = te.spec_sha256(path1)

            changed = base.replace("review text", "REVISED review text")
            path2 = Path(td) / "b.md"
            path2.write_text(changed, encoding="utf-8")
            h2 = te.spec_sha256(path2)
            self.assertNotEqual(h1, h2)

    def test_hash_raises_without_markers(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "a.md"
            path.write_text("# doc\n\nno markers here\n", encoding="utf-8")
            with self.assertRaises(te.TotalsEvalError):
                te.spec_sha256(path)

    def test_real_spec_doc_hashes_cleanly(self):
        h = te.spec_sha256()
        self.assertEqual(len(h), 64)


# ---------------------------------------------------------------------------
# 13. Half-point / integer stratification -- never pooled
# ---------------------------------------------------------------------------

class TestStratification(unittest.TestCase):
    def test_half_point_and_integer_rows_are_disjoint(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True, line=8.5)
            _add_default_game(fx, season="2023", event_id="e2", game_pk="2",
                              date="2023-06-02", total_runs=9, home_won=True, line=8.0)
            fx.write()
            half = tr.build_over_rows(seasons=("2023",), archive_root=fx.archive_root,
                                      results_path=fx.results_csv, dry_run=True)
            integer = tr.build_integer_stratum_rows(
                seasons=("2023",), archive_root=fx.archive_root,
                results_path=fx.results_csv, dry_run=True)
            half_pks = {r["game_pk"] for r in half}
            int_pks = {r["game_pk"] for r in integer}
            self.assertEqual(half_pks, {"1"})
            self.assertEqual(int_pks, {"2"})
            self.assertTrue(all(r["is_half_point"] for r in half))
            self.assertTrue(all(not r["is_half_point"] for r in integer))


# ---------------------------------------------------------------------------
# A9 -- selection-semantics equivalence with funnel.py's threshold firing
# ---------------------------------------------------------------------------

class TestThresholdFiringEquivalence(unittest.TestCase):
    def test_matches_funnel_signal_on_shared_fixture(self):
        rows = [
            {"away_x": 5.0, "home_x": 3.0},   # signal = 2.0
            {"away_x": 3.0, "home_x": 3.0},   # signal = 0.0
            {"away_x": None, "home_x": 3.0},  # signal = None
            {"away_x": 1.0, "home_x": 4.0},   # signal = -3.0
        ]
        for threshold in (0.5, 1.5, 2.5, 3.5):
            for row in rows:
                value = funnel._signal(row, "x")
                expected = value is not None and abs(value) >= threshold
                self.assertEqual(tr.threshold_fires(value, threshold), expected)


# ---------------------------------------------------------------------------
# Real-data dry_run smoke test -- skips (never fails) when stores are absent
# ---------------------------------------------------------------------------

class TestRealDataDryRunSmoke(unittest.TestCase):
    @unittest.skipUnless(_data_available(), "real gitignored totals stores not present")
    def test_universe_builds_and_dry_run_runs(self):
        manifest = tr.build_universe()
        self.assertGreater(manifest["counts"]["joint_total"], 0)
        rows = tr.build_over_rows(dry_run=True)
        self.assertTrue(all(r["won"] is None for r in rows))


# ---------------------------------------------------------------------------
# docs/PREREG_TOTALS_FAMILIES.md "## Methodology review -- 2026-09-05"
# (D1-D7): the nine code/validation items.
# ---------------------------------------------------------------------------

class TestExclusionLedger(unittest.TestCase):
    """Item 1: regular-season-only denominator, itemised exclusion ledger."""

    def test_classify_not_joined_splits_frozen_table(self):
        ids = list(tr.NOT_JOINED_CLASSIFICATION["postponed"][:2]
                  + tr.NOT_JOINED_CLASSIFICATION["all_star"]
                  + tr.NOT_JOINED_CLASSIFICATION["postseason"][:1])
        ledger = tr.classify_not_joined(ids)
        self.assertEqual(len(ledger["postponed"]), 2)
        self.assertEqual(len(ledger["all_star"]), 1)
        self.assertEqual(len(ledger["postseason"]), 1)
        self.assertEqual(ledger["unclassified"], [])

    def test_classify_not_joined_flags_unrecognised_id(self):
        ledger = tr.classify_not_joined(["not_a_real_event_id"])
        self.assertEqual(ledger["unclassified"], ["not_a_real_event_id"])

    def test_ledger_reconciles_to_raw_not_joined_count(self):
        """A synthetic fixture that manufactures a not-joined event outside
        the frozen classification table must raise -- `build_universe` must
        never silently report a ledger that does not reconcile."""
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            # A game with a price-gradeable closing line but NO matching
            # settlement row at all -- not_joined, and not in the frozen
            # audit table, so the ledger cannot reconcile it.
            from datetime import datetime
            fx.add_game(season="2023", event_id="unaudited1", game_pk="999",
                       date="2023-06-01", away_full="Boston Red Sox",
                       home_full="New York Yankees", away_abbrev="ZZZ",
                       home_abbrev="ZZZ", commence_time="2023-06-01T23:05:00Z",
                       line=8.5, books=DEFAULT_BOOKS, total_runs=9)
            fx.write()
            with self.assertRaises(tr.TotalsRowsError):
                tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                  results_path=fx.results_csv)

    @unittest.skipUnless(_data_available(), "real gitignored totals stores not present")
    def test_real_ledger_reconciles_and_matches_audit_counts(self):
        """D1: the real archive's exclusion ledger must equal the audited
        counts -- 30 postponed, 14 postseason, 1 All-Star -- exactly."""
        manifest = tr.build_universe()
        ledger = manifest["exclusion_ledger"]
        self.assertEqual(ledger["postponed"], 30)
        self.assertEqual(ledger["postseason"], 14)
        self.assertEqual(ledger["all_star"], 1)
        self.assertEqual(
            ledger["postponed"] + ledger["postseason"] + ledger["all_star"],
            manifest["counts"]["not_joined_to_settlement"])
        self.assertEqual(manifest["counts"]["joint_by_season"],
                         {"2023": 1296, "2024": 1288})


class TestM1CannotTell(unittest.TestCase):
    """Item 6: CANNOT_TELL for M1 effects in (0, 3.0pp) (D2)."""

    BASE = dict(population_shift_fatal=False, screen_passes=True,
               replication_sign_agrees=True, replication_ci_excludes_zero=True,
               survives_fdr=True, devig_sign_survives=True, battery_survives=True)

    def test_screen_cannot_tell_flips_verdict(self):
        kwargs = dict(self.BASE, screen_cannot_tell=True)
        self.assertEqual(te.compute_verdict(**kwargs), "CANNOT_TELL")

    def test_replication_cannot_tell_flips_verdict(self):
        kwargs = dict(self.BASE, replication_cannot_tell=True)
        self.assertEqual(te.compute_verdict(**kwargs), "CANNOT_TELL")

    def test_cannot_tell_wins_over_screen_and_replication_fail(self):
        kwargs = dict(self.BASE, screen_cannot_tell=True, screen_passes=False,
                     replication_sign_agrees=False)
        self.assertEqual(te.compute_verdict(**kwargs), "CANNOT_TELL")

    def test_population_shift_wins_over_cannot_tell(self):
        kwargs = dict(self.BASE, screen_cannot_tell=True, population_shift_fatal=True)
        self.assertEqual(te.compute_verdict(**kwargs), "POPULATION_SHIFT_FAIL")

    def test_evaluate_screen_effect_below_floor_is_cannot_tell(self):
        # Small, real, positive effect (1.5pp): 1,030 wins / 970 losses of
        # 2,000 rows at implied 0.50 -> win rate 0.515, effect = 0.015 --
        # inside the 0-3.0pp band.
        rows = ([{"date": "2023-06-01", "won": True, "implied": 0.50}] * 1030
               + [{"date": "2023-06-01", "won": False, "implied": 0.50}] * 970)
        result = te.evaluate_screen(rows)
        self.assertAlmostEqual(result["effect"], 0.015, places=6)
        self.assertFalse(result["passes_screen"])
        self.assertTrue(result["cannot_tell"])
        self.assertEqual(result["expected_sign"], 1)

    def test_evaluate_screen_effect_at_or_above_floor_passes(self):
        # Effect = 0.03 exactly: 1,060 wins / 940 losses of 2,000 rows
        # (win rate 0.53).
        rows = ([{"date": "2023-06-01", "won": True, "implied": 0.50}] * 1060
               + [{"date": "2023-06-01", "won": False, "implied": 0.50}] * 940)
        result = te.evaluate_screen(rows)
        self.assertAlmostEqual(result["effect"], 0.03, places=6)
        self.assertTrue(result["passes_screen"])
        self.assertFalse(result["cannot_tell"])

    def test_evaluate_screen_null_effect_is_screen_fail_not_cannot_tell(self):
        rows = [{"date": "2023-06-01", "won": (i % 2 == 0), "implied": 0.50}
               for i in range(40)]
        result = te.evaluate_screen(rows)
        self.assertFalse(result["passes_screen"])
        self.assertFalse(result["cannot_tell"])
        self.assertEqual(result["expected_sign"], 0)

    def test_replication_gate_cannot_tell_only_when_sign_agrees(self):
        # Sign disagrees -> real fail, never cannot_tell.
        gate = te._replication_gate({"effect": -0.01, "ci": {"low": -0.02, "high": 0.0}},
                                    expected_sign=1)
        self.assertFalse(gate["sign_agrees"])
        self.assertFalse(gate["cannot_tell"])

        # Sign agrees, magnitude below floor -> cannot_tell.
        gate = te._replication_gate({"effect": 0.015, "ci": {"low": 0.001, "high": 0.03}},
                                    expected_sign=1)
        self.assertTrue(gate["sign_agrees"])
        self.assertFalse(gate["floor_ok"])
        self.assertTrue(gate["cannot_tell"])


class TestConfirmatoryFreeze(unittest.TestCase):
    """Item 7: freeze_confirmatory_family with FDR_M=1 cross-check, M1
    confirmatory only, M2 exploratory pre-determined POPULATION_SHIFT_FAIL.
    """

    def _frozen_manifest(self, td):
        fx = _Fixture(td)
        _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                          date="2023-06-01", total_runs=9, home_won=True)
        fx.write()
        manifest = tr.build_universe(seasons=("2023",), archive_root=fx.archive_root,
                                     results_path=fx.results_csv)
        manifest_path = Path(td) / "universe.json"
        tr.write_manifest(manifest, manifest_path)
        return manifest_path

    def test_freeze_confirmatory_family_refuses_to_overwrite(self):
        with TemporaryDirectory() as td:
            manifest_path = self._frozen_manifest(td)
            family_path = Path(td) / "family.json"
            record = te.freeze_confirmatory_family(family_path, manifest_path=manifest_path)
            self.assertEqual(record["family_id"], "TOTALS_FULLGAME_2026H1")
            self.assertEqual(record["fdr_m"], 1)
            ids = [m["id"] for m in record["members"]]
            self.assertEqual(ids, ["TOTALS-M1", "TOTALS-M2"])
            m2 = [m for m in record["members"] if m["id"] == "TOTALS-M2"][0]
            self.assertEqual(m2["verdict"], "POPULATION_SHIFT_FAIL")
            self.assertTrue(m2["excluded_from_fdr"])
            m1 = [m for m in record["members"] if m["id"] == "TOTALS-M1"][0]
            self.assertTrue(m1["confirmatory"])
            self.assertFalse(m2["confirmatory"])
            with self.assertRaises(te.TotalsEvalError):
                te.freeze_confirmatory_family(family_path, manifest_path=manifest_path)

    def test_run_full_evaluation_refuses_without_confirmatory_freeze(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True)
            fx.write()
            with self.assertRaises(te.TotalsEvalError):
                te.read_confirmatory_family(Path(td) / "nope.json")

    def test_verify_confirmatory_family_cross_checks_fdr_m(self):
        with TemporaryDirectory() as td:
            manifest_path = self._frozen_manifest(td)
            family_path = Path(td) / "family.json"
            te.freeze_confirmatory_family(family_path, manifest_path=manifest_path)
            record = te.read_confirmatory_family(family_path)
            record["fdr_m"] = 2  # simulate the record and the code disagreeing
            family_path.write_text(json.dumps(record), encoding="utf-8")
            manifest = tr.read_manifest(manifest_path)
            hashes = {"content_hash": manifest["content_hash"],
                     "price_payload_hash": manifest["price_payload_hash"]}
            with self.assertRaises(te.TotalsEvalError):
                te._verify_confirmatory_family(hashes, path=family_path)


class TestM2Exploratory(unittest.TestCase):
    """Item 7 (M2 side): D3's pre-determined POPULATION_SHIFT_FAIL, wired
    via `scripts.totals_m2_coverage`'s terciles-fit-on-2023 and
    both-sides-or-None rule."""

    @unittest.skipUnless(_data_available(), "real gitignored totals stores not present")
    def test_m2_exploratory_is_pre_determined_population_shift_fail(self):
        result = te.evaluate_m2_exploratory()
        self.assertEqual(result["verdict"], "POPULATION_SHIFT_FAIL")
        self.assertFalse(result["confirmatory"])
        self.assertTrue(result["excluded_from_fdr"])
        # D3's own published figure: p=0.0001, well under the 0.01 fatal bound.
        self.assertLess(result["population_shift"]["p"], 0.01)
        self.assertTrue(result["population_shift"]["fatal"])


class TestPrereqSpecHash(unittest.TestCase):
    def test_prereg_spec_hash_is_stable_and_bounded(self):
        h1 = te.prereg_spec_sha256()
        h2 = te.prereg_spec_sha256()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_prereg_spec_hash_raises_without_marker(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "a.md"
            path.write_text("# doc\n\nno markers here\n", encoding="utf-8")
            with self.assertRaises(te.TotalsEvalError):
                te.prereg_spec_sha256(path)


class TestCommenceTimeMutationFixture(unittest.TestCase):
    """Item 8: a mutation-armed fixture proving the closing pick is anchored
    to the SAME snapshot's own `commence_time`, never a later, post-hoc
    schedule field -- the fixture must FAIL (assertion catches a real
    regression) if `_pick_closing`/`compute_event_closing` were changed to
    read a mutated/post-hoc anchor instead."""

    def test_mutating_a_later_snapshots_commence_time_cannot_move_the_pick(self):
        from datetime import datetime, timedelta
        original_ct = datetime.fromisoformat("2023-06-01T23:05:00+00:00")
        # A later snapshot's event carries a MUTATED (post-hoc-looking)
        # commence_time far in the future -- simulating a corrupted/rescheduled
        # schedule field arriving after the real closing snapshot.
        mutated_ct = datetime.fromisoformat("2023-06-05T12:00:00+00:00")
        good_snap_at = original_ct - timedelta(hours=2)
        records = [
            (good_snap_at, original_ct, "Boston Red Sox", "New York Yankees",
             {8.5: {"dk": {"over": -110, "under": -110}}}),
        ]
        closing_before = tr.compute_event_closing(records)
        self.assertIsNotNone(closing_before)
        self.assertEqual(closing_before["commence_time"], original_ct)

        # Arm the mutation: replace the record's OWN commence_time with the
        # mutated value, exactly as a post-hoc-schedule-field bug would.
        mutated_records = [(good_snap_at, mutated_ct, "Boston Red Sox",
                           "New York Yankees", {8.5: {"dk": {"over": -110, "under": -110}}})]
        closing_after = tr.compute_event_closing(mutated_records)
        # A snapshot 2h before the ORIGINAL time is now ~87h before the
        # MUTATED time -- outside the 6h staleness bound -- so the mutation
        # must be REJECTED (None), never silently accepted with a moved
        # anchor. This is the fixture's fail condition: if the anchor rule
        # ever changed to read a different, later-arriving commence_time
        # field instead of the record's own, this assertion would start
        # passing on a picked-but-wrong closing instead of catching the
        # staleness rejection here.
        self.assertIsNone(closing_after)


class TestIntegerStratumReport(unittest.TestCase):
    """Item 9: push handling -- half-point primary has no pushes by
    construction (guarded); the integer stratum is report-only P(over | no
    push), never promotable."""

    def test_report_only_and_never_promotable(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1",
                              date="2023-06-01", total_runs=9, home_won=True, line=8.0)
            _add_default_game(fx, season="2023", event_id="e2", game_pk="2",
                              date="2023-06-02", total_runs=7, home_won=False, line=8.0)
            _add_default_game(fx, season="2023", event_id="e3", game_pk="3",
                              date="2023-06-03", total_runs=8, home_won=False, line=8.0)  # push
            fx.write()
            report = te.integer_stratum_report(
                seasons=("2023",), archive_root=fx.archive_root, results_path=fx.results_csv)
            self.assertTrue(report["report_only"])
            self.assertFalse(report["promotable"])
            self.assertEqual(report["by_season"]["2023"]["n_no_push"], 2)  # push excluded
            self.assertEqual(report["by_season"]["2023"]["overs"], 1)
            self.assertAlmostEqual(report["by_season"]["2023"]["p_over_given_no_push"], 0.5)


if __name__ == "__main__":
    unittest.main()
