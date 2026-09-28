"""Tests for the slice-3 memory fix: streamed reads that keep exactly the
rows the old full-materialisation code kept, never more, never fewer.

Covers, one class per touched module:
  - src.report.tennis_board: `iter_multibook(sport=None, keep=...)` keeps
    the same rows `read_multibook(sport=None)` + a list filter did.
  - src.report.nfl_card: `_nfl_rows_for_date` keeps this date's rows only,
    newest per (event, book, market, line) -- the Sunday rule.
  - src.analysis.derivative_prices: `_read(path, date=...)` filters while
    reading instead of after.
  - src.report.engine_bridge: the V2-ledger join streams only the rows
    whose event_id is in the requested date's event set.

Every synthetic store lives in a `tempfile.TemporaryDirectory()`; none of
these tests touch the real repo stores.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis import derivative_prices
from src.ledger.chain import HashChainLedger
from src.ledger.records import PROBABILITY_PROVENANCE_NONE, DecisionRecord
from src.pipeline import snapshots
from src.report import engine_bridge, nfl_card, tennis_board


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _mb_row(sport, event_id, book, observed, *, market=None,
           away="Away Team", home="Home Team",
           commence="2026-09-14T18:00:00Z", away_price=-110, home_price=-110,
           home_line=None, away_line=None, total=None,
           over_price=None, under_price=None):
    """One multibook row, shaped exactly like `snapshots._multibook_row`
    writes it -- h2h rows carry no `market` key at all (sport=None default
    matches h2h), a non-None `market` is a spreads/totals/first-five row."""
    row = {
        "observed_utc": observed, "event_id": event_id,
        "commence_time": commence, "home_team": home, "away_team": away,
        "book": book,
    }
    if sport is not None:
        row["sport"] = sport
    if market is not None:
        row["market"] = market
    if market == "spreads":
        row["home_line"] = home_line
        row["away_line"] = away_line
        row["home_price"] = home_price
        row["away_price"] = away_price
    elif market == "totals":
        row["total"] = total
        row["over_price"] = over_price
        row["under_price"] = under_price
    else:  # h2h-shaped (market is None or "h2h_1st_5_innings")
        row["home_price"] = home_price
        row["away_price"] = away_price
    return row


def _write_multibook(rows, tmp) -> Path:
    path = Path(tmp) / "odds_multibook.jsonl"
    snapshots.append(rows, path=path)
    return path


def _decision_row(event_id: str, system_id: str, decision_utc: str,
                  **overrides) -> dict:
    """A minimally-valid DecisionRecord-shaped row (every REQUIRED field of
    `src.ledger.records.DecisionRecord` present, `verdict="no_play"` so
    nothing else is demanded) -- same shape
    `tests/test_decisions_ledger_rotation.py`'s own `_decision_row` uses."""
    row = dict(
        engine_version="v1", system_id=system_id, system_version="1.0.0",
        registry_fingerprint="fp1", frame_fingerprint=None,
        snapshot_fingerprint="snap1", game_pk=12345, event_id=event_id,
        decision_utc=decision_utc, point_class="LATE_BOARD",
        information_time=decision_utc, recorded_utc=decision_utc,
        verdict="no_play", selection_id=None, market_key=None, line=None,
        book=None, price_american=None, consensus_fair=None,
        books_at_decision=None, friction=None, p_model=None,
        p_model_interval=None, edge_bps=None, price_improvement_bps=None,
        rating=None, thesis=None, evidence=[], counterarguments=[],
        supporting_systems=[], refusal_reason=None, assumption_exposure={},
        stake_units=0.0, known_at_grade="A",
        p_model_provenance=PROBABILITY_PROVENANCE_NONE,
    )
    row.update(overrides)
    return row


def _canon(rows) -> list:
    """Rows as a sorted list of canonical JSON strings -- order-independent
    equality that still catches a duplicated or dropped row."""
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


# ---------------------------------------------------------------------------
# tennis_board
# ---------------------------------------------------------------------------

class TennisBoardStreamingTests(unittest.TestCase):

    def test_streamed_keep_matches_full_read_then_filter(self):
        """The exact property the fix depends on: `iter_multibook(sport=
        None, keep=_is_tennis_row)` keeps precisely the rows the old
        `read_multibook(sport=None)` + list-filter kept -- across mixed
        sports, mixed markets (h2h and a spreads row, which the old filter
        never excluded either), and rows with no `sport` key at all (MLB,
        which the tennis filter must reject)."""
        rows = [
            _mb_row(None, "mlb1", "fanduel", "2026-09-14T10:00:00Z"),  # MLB (no sport key)
            _mb_row("nfl", "nfl1", "draftkings", "2026-09-14T10:00:00Z"),
            _mb_row("tennis_atp_china_open", "t1", "bovada",
                   "2026-09-14T09:00:00Z"),
            _mb_row("tennis_wta_beijing", "t2", "fanduel",
                   "2026-09-14T09:05:00Z", market="spreads",
                   home_line="-3.5", away_line="3.5"),
            _mb_row("mma", "mma1", "betmgm", "2026-09-14T10:00:00Z"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_multibook(rows, tmp)

            streamed = list(snapshots.iter_multibook(
                path=path, sport=None, keep=tennis_board._is_tennis_row))
            naive = [r for r in snapshots.read_multibook(path=path, sport=None)
                    if isinstance(r.get("sport"), str)
                    and r.get("sport", "").startswith("tennis_")]

        self.assertEqual(_canon(streamed), _canon(naive))
        self.assertEqual(len(streamed), 2)
        self.assertEqual({r["event_id"] for r in streamed}, {"t1", "t2"})

    def test_board_for_date_streams_end_to_end(self):
        """`board_for_date(date_str)` with no injected `rows` -- the
        production default -- reaches the same board a caller who injects
        the pre-filtered tennis rows by hand gets. `snapshots.iter_multibook`
        is redirected to the synthetic store (its `path` default is bound
        at import time, so a module-level path constant cannot be
        monkeypatched after the fact); everything else is the real,
        unmocked streaming code."""
        rows = [
            _mb_row("tennis_atp_china_open", "t1", "bovada",
                   "2026-09-14T09:00:00Z", commence="2026-09-14T15:00:00Z"),
            _mb_row("tennis_atp_china_open", "t1", "fanduel",
                   "2026-09-14T09:01:00Z", commence="2026-09-14T15:00:00Z"),
            _mb_row("mlb", "mlb1", "fanduel", "2026-09-14T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_multibook(rows, tmp)
            real_iter = snapshots.iter_multibook

            def _redirected(*args, **kwargs):
                kwargs["path"] = path
                return real_iter(*args, **kwargs)

            with mock.patch.object(snapshots, "iter_multibook",
                                   side_effect=_redirected):
                streamed_board = tennis_board.board_for_date(
                    "2026-09-14", tournaments=[])

            injected_rows = [r for r in rows
                             if r["sport"].startswith("tennis_")]
            injected_board = tennis_board.board_for_date(
                "2026-09-14", rows=injected_rows, tournaments=[])

        # generated_utc is a build-time stamp; everything else must match.
        streamed_board.pop("generated_utc")
        injected_board.pop("generated_utc")
        self.assertEqual(streamed_board, injected_board)
        self.assertTrue(streamed_board["captured_any"])


# ---------------------------------------------------------------------------
# nfl_card
# ---------------------------------------------------------------------------

def _patched_nfl_iter(path):
    """Context manager redirecting `snapshots.iter_multibook` (as seen by
    `nfl_card._nfl_rows_for_date`) to a synthetic store, same technique as
    `TennisBoardStreamingTests.test_board_for_date_streams_end_to_end`."""
    real_iter = snapshots.iter_multibook

    def _redirected(*args, **kwargs):
        kwargs["path"] = path
        return real_iter(*args, **kwargs)

    return mock.patch.object(snapshots, "iter_multibook",
                             side_effect=_redirected)


def _naive_nfl_rows_for_date(path, date_str):
    """Reference implementation: read every NFL row (the old, unstreamed
    way), keep this date's, keep the newest per (event, book, market,
    line). This is the property `_nfl_rows_for_date` must match -- not
    reimplementing the streaming, just the OLD full-read-then-filter
    behaviour it replaces."""
    all_rows = snapshots.read_multibook(path=path, sport="nfl")
    by_date = [r for r in all_rows
              if snapshots.official_date(r.get("commence_time")) == date_str]
    latest = {}
    for row in by_date:
        key = (row.get("event_id"), row.get("book"), row.get("market"),
              nfl_card._nfl_line_key(row))
        seen = latest.get(key)
        if seen is None or (str(row.get("observed_utc") or "")
                            >= str(seen.get("observed_utc") or "")):
            latest[key] = row
    return list(latest.values())


class NflCardStreamingTests(unittest.TestCase):

    def test_only_this_dates_rows_are_kept(self):
        rows = [
            _mb_row("nfl", "e1", "fanduel", "2026-09-14T10:00:00Z",
                   commence="2026-09-14T17:00:00Z"),
            _mb_row("nfl", "e2", "fanduel", "2026-09-15T10:00:00Z",
                   commence="2026-09-15T17:00:00Z"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_multibook(rows, tmp)
            with _patched_nfl_iter(path):
                kept = nfl_card._nfl_rows_for_date("2026-09-14")
        self.assertEqual([r["event_id"] for r in kept], ["e1"])

    def test_sunday_newest_per_key_rule(self):
        """The SAME book quotes the SAME line three times across a busy
        capture day (a "Sunday"); only the newest of the three survives."""
        rows = [
            _mb_row("nfl", "e1", "fanduel", "2026-09-14T09:00:00Z",
                   commence="2026-09-14T17:00:00Z", home_price=-110),
            _mb_row("nfl", "e1", "fanduel", "2026-09-14T12:00:00Z",
                   commence="2026-09-14T17:00:00Z", home_price=-115),
            _mb_row("nfl", "e1", "fanduel", "2026-09-14T15:00:00Z",
                   commence="2026-09-14T17:00:00Z", home_price=-120),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_multibook(rows, tmp)
            with _patched_nfl_iter(path):
                kept = nfl_card._nfl_rows_for_date("2026-09-14")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["observed_utc"], "2026-09-14T15:00:00Z")
        self.assertEqual(kept[0]["home_price"], -120)

    def test_different_lines_are_not_collapsed(self):
        """Two DIFFERENT spread lines from the same book are two different
        bets, not duplicate observations -- both must survive the dedup,
        even though they share (event, book, market)."""
        rows = [
            _mb_row("nfl", "e1", "fanduel", "2026-09-14T09:00:00Z",
                   commence="2026-09-14T17:00:00Z", market="spreads",
                   home_line="-3.0", away_line="3.0"),
            _mb_row("nfl", "e1", "fanduel", "2026-09-14T12:00:00Z",
                   commence="2026-09-14T17:00:00Z", market="spreads",
                   home_line="-3.5", away_line="3.5"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_multibook(rows, tmp)
            with _patched_nfl_iter(path):
                kept = nfl_card._nfl_rows_for_date("2026-09-14")
        self.assertEqual(len(kept), 2)
        self.assertEqual({r["home_line"] for r in kept}, {"-3.0", "-3.5"})

    def test_equivalent_to_the_naive_full_read_reference(self):
        """A busier synthetic slate -- two games, several books, h2h and
        spreads, repeated observations -- streamed result equals the naive
        full-read-then-filter-then-dedup reference, as sets of rows."""
        rows = []
        for minute, price in ((0, -105), (10, -108), (20, -112)):
            rows.append(_mb_row(
                "nfl", "e1", "fanduel", f"2026-09-14T09:{minute:02d}:00Z",
                commence="2026-09-14T17:00:00Z", home_price=price))
        rows.append(_mb_row("nfl", "e1", "draftkings",
                            "2026-09-14T09:05:00Z",
                            commence="2026-09-14T17:00:00Z", home_price=-107))
        rows.append(_mb_row("nfl", "e1", "fanduel", "2026-09-14T09:00:00Z",
                            commence="2026-09-14T17:00:00Z", market="spreads",
                            home_line="-2.5", away_line="2.5"))
        rows.append(_mb_row("nfl", "e2", "betmgm", "2026-09-14T09:00:00Z",
                            commence="2026-09-14T20:00:00Z", home_price=-130))
        # a different date's row for the same book -- must not leak in
        rows.append(_mb_row("nfl", "e3", "fanduel", "2026-09-15T09:00:00Z",
                            commence="2026-09-15T17:00:00Z", home_price=100))

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_multibook(rows, tmp)
            with _patched_nfl_iter(path):
                streamed = nfl_card._nfl_rows_for_date("2026-09-14")
            reference = _naive_nfl_rows_for_date(path, "2026-09-14")

        self.assertEqual(_canon(streamed), _canon(reference))
        self.assertEqual({r["event_id"] for r in streamed}, {"e1", "e2"})


# ---------------------------------------------------------------------------
# derivative_prices
# ---------------------------------------------------------------------------

class DerivativePricesReadStreamingTests(unittest.TestCase):

    def _write(self, tmp, rows):
        path = Path(tmp) / "derivative_markets.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        return path

    def test_date_filter_while_reading_matches_full_read_then_filter(self):
        rows = [
            {"game_date": "2026-09-14", "market": "totals_1st_5_innings",
            "n": 1},
            {"game_date": "2026-09-15", "market": "totals_1st_5_innings",
            "n": 2},
            {"game_date": "2026-09-14", "market": "team_totals", "n": 3},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, rows)
            filtered = derivative_prices._read(path, date="2026-09-14")
            reference = [r for r in derivative_prices._read(path)
                        if r.get("game_date") == "2026-09-14"]
        self.assertEqual(_canon(filtered), _canon(reference))
        self.assertEqual({r["n"] for r in filtered}, {1, 3})

    def test_no_date_is_unchanged_full_read(self):
        """`date=None` (the default) is byte-for-byte the old behaviour --
        no existing caller that omits it sees any change."""
        rows = [{"game_date": "2026-09-14", "n": 1},
               {"game_date": "2026-09-15", "n": 2}]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, rows)
            self.assertEqual(len(derivative_prices._read(path)), 2)

    def test_a_truncated_tail_line_is_still_skipped_not_guessed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "derivative_markets.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"game_date": "2026-09-14", "n": 1}) + "\n")
                fh.write('{"game_date": "2026-09-14", "n": 2')  # truncated
            rows = derivative_prices._read(path, date="2026-09-14")
        self.assertEqual(len(rows), 1)


# ---------------------------------------------------------------------------
# engine_bridge
# ---------------------------------------------------------------------------

class EngineBridgeStreamingTests(unittest.TestCase):

    def _build_ledger(self, tmp):
        path = Path(tmp) / "decisions_v2.jsonl"
        ledger = HashChainLedger(path)
        ledger.append({"kind": "genesis"})
        ledger.append(_decision_row("e1", "sys_a", "2026-09-14T09:00:00Z"))
        ledger.append(_decision_row("e2", "sys_b", "2026-09-14T09:05:00Z"))
        ledger.append(_decision_row("e1", "sys_c", "2026-09-14T09:10:00Z"))
        # a row with no decision_utc at all (a correction row) must be
        # skipped exactly like load_decisions() skips it.
        ledger.append({"kind": "correction", "event_id": "e1"})
        return path

    def test_stream_matches_load_decisions_filtered_to_the_event_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._build_ledger(tmp)
            streamed = list(engine_bridge._stream_decisions_for_event_ids(
                {"e1"}, path=path))

            raw_rows = HashChainLedger(path).read()
            reference = [
                DecisionRecord.from_row(row) for row in raw_rows
                if row.get("event_id") in {"e1"}
                and row.get("kind") != "genesis" and "decision_utc" in row
            ]

        self.assertEqual(len(streamed), 2)
        self.assertEqual(
            sorted(r.system_id for r in streamed),
            sorted(r.system_id for r in reference))
        self.assertEqual({r.event_id for r in streamed}, {"e1"})

    def test_event_ids_not_in_the_set_are_never_parsed_into_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._build_ledger(tmp)
            streamed = list(engine_bridge._stream_decisions_for_event_ids(
                set(), path=path))
        self.assertEqual(streamed, [])

    def test_decisions_for_date_returns_only_the_dates_rows(self):
        """End to end: `decisions_for_date` (default, unstreamed-by-caller
        path) streams the ledger and returns summaries ONLY for the
        requested date's games -- e2's decision (2026-09-08, via the fixture
        index) never appears in the 2026-09-07 result."""
        index = {
            "e1": {"away_abbrev": "BOS", "home_abbrev": "NYY",
                  "date": "2026-09-07"},
            "e2": {"away_abbrev": "LAD", "home_abbrev": "SF",
                  "date": "2026-09-08"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._build_ledger(tmp)
            with mock.patch.object(engine_bridge, "V2_LEDGER_PATH", str(path)), \
                mock.patch.object(engine_bridge, "event_index",
                                  return_value=index):
                result = engine_bridge.decisions_for_date(
                    "2026-09-07", wagers=())

        self.assertEqual(list(result.keys()), [("BOS", "NYY", "2026-09-07")])
        summaries = result[("BOS", "NYY", "2026-09-07")]
        self.assertEqual(len(summaries), 2)  # sys_a and sys_c, both on e1
        self.assertEqual({s["system_id"] for s in summaries},
                         {"sys_a", "sys_c"})


if __name__ == "__main__":
    unittest.main()
