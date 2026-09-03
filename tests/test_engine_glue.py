import json
import tempfile
import unittest
from pathlib import Path

from src.core import asof as asof_module
from src.engine import glue
from src.engine.truncation import truncation_differential

GAME_A = "aaaa1111aaaa1111aaaa1111aaaa1111"
GAME_B = "bbbb2222bbbb2222bbbb2222bbbb2222"


def _l1_row(event_id, market_key, selection_id, side, price, book,
            observed_utc, game_pk=None):
    return {
        "sport": "mlb", "event_id": event_id, "game_pk": game_pk,
        "market_key": market_key, "selection_id": selection_id, "side": side,
        "subject_kind": None, "subject_id": None, "line": None, "book": book,
        "price_american": price, "observed_utc": observed_utc,
        "book_last_update": None, "known_at": observed_utc,
        "known_at_grade": "A", "capture_id": f"c-{observed_utc}",
        "source": "odds_api", "region": "us", "provider_market_key": market_key,
        "venue_kind": "sportsbook", "is_close": False, "limit_observed": None,
        "l0_available": False,
    }


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class GlueTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.l1_path = Path(self._tmp.name) / "l1_observations.jsonl"


class TestBuildBoard(GlueTestBase):
    def test_stop_at_t_excludes_future_rows(self):
        _write_jsonl(self.l1_path, [
            _l1_row(GAME_A, "h2h", "home_sel", "home", -150, "a",
                    "2026-09-02T18:00:00Z"),
            _l1_row(GAME_A, "h2h", "home_sel", "home", -140, "a",
                    "2026-09-02T20:00:00Z"),
        ])
        board = glue.build_board(GAME_A, "2026-09-02T19:00:00Z", path=self.l1_path)
        prices = [q.price_american for q in board.quotes]
        self.assertEqual(prices, [-150])

    def test_selects_only_the_requested_game(self):
        _write_jsonl(self.l1_path, [
            _l1_row(GAME_A, "h2h", "home_sel", "home", -150, "a",
                    "2026-09-02T18:00:00Z"),
            _l1_row(GAME_B, "h2h", "home_sel", "home", -200, "a",
                    "2026-09-02T18:00:00Z"),
        ])
        board = glue.build_board(GAME_A, "2026-09-02T20:00:00Z", path=self.l1_path)
        self.assertEqual(len(board.quotes), 1)
        self.assertEqual(board.quotes[0].event_id, GAME_A)
        self.assertEqual(board.game_pk, GAME_A)

    def test_board_facts_counts_distinct_books_per_market(self):
        _write_jsonl(self.l1_path, [
            _l1_row(GAME_A, "h2h", "home_sel", "home", -150, "a",
                    "2026-09-02T18:00:00Z"),
            _l1_row(GAME_A, "h2h", "home_sel", "home", -140, "b",
                    "2026-09-02T18:05:00Z"),
            _l1_row(GAME_A, "totals", "over_sel", "over", -110, "a",
                    "2026-09-02T18:00:00Z"),
        ])
        board = glue.build_board(GAME_A, "2026-09-02T20:00:00Z", path=self.l1_path)
        markets, books_by_market = glue.board_facts(board)
        self.assertEqual(markets, ("h2h", "totals"))
        self.assertEqual(books_by_market, {"h2h": 2, "totals": 1})


class TestBuildSnapshot(GlueTestBase):
    def test_uses_as_of_when_game_pk_present(self):
        watch_path = Path(self._tmp.name) / "umpires_watch.jsonl"
        _write_jsonl(watch_path, [
            {"game_pk": 999, "observed_utc": "2026-09-02T18:00:00Z",
             "home_plate_umpire": "Jane Doe"},
        ])
        stores = [asof_module.StoreSpec(
            name="umpires_watch", path=watch_path,
            game_key_of=lambda r: str(r.get("game_pk")) if r.get("game_pk") is not None else None,
            time_of=lambda r: r.get("observed_utc"),
            fields={"home_plate_umpire": lambda r: r.get("home_plate_umpire")},
        )]
        # 2026+ is inside the live-capture era, so this field grades A.
        ref = glue.GameRef(event_id=GAME_A, game_pk="999")
        snapshot = glue.build_snapshot(
            ref, "2026-09-02T20:00:00Z", as_of_stores=stores)
        self.assertIn("A:home_plate_umpire", snapshot.assumption_exposure)
        self.assertEqual(snapshot.game_pk, GAME_A)  # board_key wins on the field

    def test_skips_as_of_without_a_game_pk(self):
        ref = glue.GameRef(event_id=GAME_A)
        snapshot = glue.build_snapshot(ref, "2026-09-02T20:00:00Z")
        self.assertEqual(snapshot.assumption_exposure, {})

    def test_stop_at_t_on_as_of_fields(self):
        watch_path = Path(self._tmp.name) / "umpires_watch.jsonl"
        _write_jsonl(watch_path, [
            {"game_pk": 999, "observed_utc": "2026-09-02T21:00:00Z",
             "home_plate_umpire": "Jane Doe"},
        ])
        stores = [asof_module.StoreSpec(
            name="umpires_watch", path=watch_path,
            game_key_of=lambda r: str(r.get("game_pk")) if r.get("game_pk") is not None else None,
            time_of=lambda r: r.get("observed_utc"),
            fields={"home_plate_umpire": lambda r: r.get("home_plate_umpire")},
        )]
        ref = glue.GameRef(event_id=GAME_A, game_pk="999")
        # t is BEFORE the umpire observation -- it must not appear.
        snapshot = glue.build_snapshot(
            ref, "2026-09-02T20:00:00Z", as_of_stores=stores)
        self.assertEqual(snapshot.assumption_exposure, {})

    def test_available_markets_come_from_the_board(self):
        _write_jsonl(self.l1_path, [
            _l1_row(GAME_A, "h2h", "home_sel", "home", -150, "a",
                    "2026-09-02T18:00:00Z"),
        ])
        board = glue.build_board(GAME_A, "2026-09-02T20:00:00Z", path=self.l1_path)
        snapshot = glue.build_snapshot(GAME_A, "2026-09-02T20:00:00Z", board=board)
        self.assertEqual(snapshot.available_markets, ("h2h",))
        self.assertEqual(snapshot.books_by_market, {"h2h": 1})


class TestGamesCapturedOnAndRefusal(GlueTestBase):
    def test_games_captured_on_filters_by_date_and_sorts(self):
        _write_jsonl(self.l1_path, [
            _l1_row(GAME_B, "h2h", "home_sel", "home", -150, "a",
                    "2026-09-02T18:00:00Z"),
            _l1_row(GAME_A, "h2h", "home_sel", "home", -140, "a",
                    "2026-09-02T18:05:00Z"),
            _l1_row(GAME_A, "h2h", "home_sel", "home", -140, "a",
                    "2026-09-01T18:05:00Z"),  # wrong date
        ])
        games = glue.games_captured_on("2026-09-02", path=self.l1_path)
        self.assertEqual(games, (GAME_A, GAME_B))

    def test_sample_truncation_inputs_refuses_on_empty_date(self):
        _write_jsonl(self.l1_path, [
            _l1_row(GAME_A, "h2h", "home_sel", "home", -150, "a",
                    "2026-09-01T18:00:00Z"),
        ])
        with self.assertRaises(glue.GlueError):
            glue.sample_truncation_inputs("2026-09-02", 5, path=self.l1_path)

    def test_sample_truncation_inputs_refuses_on_missing_store(self):
        missing = Path(self._tmp.name) / "does_not_exist.jsonl"
        with self.assertRaises(glue.GlueError):
            glue.sample_truncation_inputs("2026-09-02", 5, path=missing)


class TestSampleTruncationInputsAndGate(GlueTestBase):
    def _seed(self):
        rows = []
        for game in (GAME_A, GAME_B):
            rows.append(_l1_row(game, "h2h", f"{game}_home", "home", -150,
                                 "a", "2026-09-02T18:00:00Z"))
            rows.append(_l1_row(game, "h2h", f"{game}_away", "away", 130,
                                 "a", "2026-09-02T18:00:00Z"))
            # a price move inside the (t-2h, t] window
            rows.append(_l1_row(game, "h2h", f"{game}_home", "home", -160,
                                 "a", "2026-09-02T19:30:00Z"))
            rows.append(_l1_row(game, "h2h", f"{game}_away", "away", 140,
                                 "a", "2026-09-02T19:30:00Z"))
        _write_jsonl(self.l1_path, rows)

    def test_sample_size_and_stop_at_t_are_respected(self):
        self._seed()
        samples = glue.sample_truncation_inputs(
            "2026-09-02", 1, t_offset_minutes=120, path=self.l1_path)
        self.assertEqual(len(samples), 1)
        sample = samples[0]
        self.assertTrue(sample.t2h < sample.t)
        # t2h board must not see the 19:30 price move.
        t2h_prices = {q.price_american for q in sample.board_t2h.quotes}
        t_prices = {q.price_american for q in sample.board_t.quotes}
        self.assertNotIn(-160, t2h_prices)
        self.assertIn(-160, t_prices)

    def test_gate_record_schema_from_a_real_differential(self):
        self._seed()
        samples = glue.sample_truncation_inputs(
            "2026-09-02", 2, t_offset_minutes=120, path=self.l1_path)
        report = truncation_differential(
            samples, systems=(glue.TrivialAlwaysHomeSystem(),))
        gr = report.gate_result
        self.assertEqual(gr.gate, "G4")
        self.assertIsInstance(gr.passed, bool)
        self.assertTrue(gr.reasons)
        self.assertIsInstance(gr.inputs_hash, str)
        self.assertEqual(bool(gr), gr.passed)
        # The price move is explained by a books_by_market arrival -> PASS.
        self.assertTrue(gr.passed, gr.reasons)
        self.assertEqual(report.leakage_failures, ())

    def test_price_arrivals_explain_the_move_leakage_free(self):
        self._seed()
        sample = glue.build_truncation_sample(
            GAME_A, "2026-09-02T17:30:00Z", "2026-09-02T19:30:00Z",
            path=self.l1_path)
        self.assertTrue(any(a.field == "books_by_market:h2h"
                             for a in sample.arrivals))


if __name__ == "__main__":
    unittest.main()
