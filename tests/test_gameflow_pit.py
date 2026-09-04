"""The gameflow store is settlement-side evidence and the decision path
cannot reach it -- proved by injection, by import graph, and by cost.

WHY THIS CHECK EXISTS
---------------------
`data/processed/gameflow_*.jsonl` holds play-by-play and win probability:
facts that exist only DURING and AFTER the game they describe. A decision
that could read one row of it would be reading the outcome. That is not a
subtle leak to be caught by calibration later; it is the outcome itself, and
it would make every metric downstream meaningless while looking excellent.

Three independent proofs, in the spirit of tests/test_validation_pit.py:

  1. INJECTION. `src.core.asof.as_of` is the one reader the engine uses to
     ask "what did we know at T". A gameflow store is planted next to the
     stores it does read, stuffed with an EXTREME payload, and the snapshot
     must not move by one byte -- at any T, including a T long after the
     game ended, which is the case a naive "stop at T" filter would let
     through because the rows' observed_utc really is in the past by then.

  2. THE TAMPER DETECTOR MUST FIRE. Byte-identical snapshots prove nothing
     if nothing can move a snapshot. The same payload is therefore also
     written into a store `as_of` DOES read (weather_forecast), and the
     snapshot must change -- only then does silence under the gameflow
     injection mean "refused", not "ignored everything".

  3. IMPORT GRAPH. No module on the decision path imports
     `src.pipeline.gameflow`, so no future call site can smuggle it in
     without this test going red.

  4. ZERO ODDS CREDITS. statsapi.mlb.com is free and keyless. The ingest
     path must not import the odds provider, must not write a credit-log
     row, and must issue its requests against the MLB host -- so no volume
     of post-mortem data collection can ever move the credit floor
     (docs/COLLECTION_POLICY.md).
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.core import asof
from src.pipeline import gameflow
from src.providers import mlb
from tests.test_pipeline_gameflow import (SIMPLE_PLAYS, SIMPLE_WP_PCT,
                                          make_play_by_play,
                                          make_win_probability)

GAME_PK = 824470
T_BEFORE_GAME = "2026-09-02T16:00:00+00:00"
T_LONG_AFTER = "2026-12-31T00:00:00+00:00"

# The planted payload is EXTREME on purpose: a full game's worth of plays
# with the final score in them, observed BEFORE the decision instant, in
# every field name the gameflow store actually uses. If `as_of` admitted this
# store on any code path, the snapshot could not stay identical.
def _tamper_rows(observed_utc: str) -> list:
    return gameflow.build_rows(
        "2026-09-02", GAME_PK, make_play_by_play(SIMPLE_PLAYS),
        make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT), observed_utc,
        game_meta={"home_team": "CIN", "away_team": "SD", "home_score": 0,
                   "away_score": 2})


def _imported_modules(path: Path) -> set:
    """Every module name a file imports, by AST -- never by substring: these
    modules discuss `src.providers.odds` and the credit log in prose, and a
    text search would fire on the documentation that exists to forbid them."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


class _RedirectedDataDir:
    """A temp data root, with the one real store `as_of` reads seeded."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._previous = os.environ.get(asof.data_path.__module__ and
                                        "AISPORTS_DATA_DIR")
        os.environ["AISPORTS_DATA_DIR"] = str(self.root)
        # One honest, pre-T observation so the baseline snapshot is non-empty
        # -- a snapshot that is empty in every case could not detect anything.
        _write_jsonl(self.root / "processed" / "weather_forecast.jsonl", [{
            "game_pk": GAME_PK, "observed_utc": "2026-09-02T15:00:00+00:00",
            "temp_f": 71, "wind_mph": 4, "roof": "open",
        }])
        return self

    def __exit__(self, *exc):
        if self._previous is None:
            os.environ.pop("AISPORTS_DATA_DIR", None)
        else:
            os.environ["AISPORTS_DATA_DIR"] = self._previous
        self._tmp.cleanup()
        return False


def _snapshot_bytes(t: str) -> bytes:
    return json.dumps(asof.as_of(GAME_PK, t).to_dict(),
                      sort_keys=True).encode("utf-8")


class TestGameflowIsUnreachableFromAsOf(unittest.TestCase):

    def test_no_default_store_points_at_the_gameflow_store(self):
        paths = [str(spec.path) for spec in asof._default_stores()]
        self.assertFalse([p for p in paths if "gameflow" in p],
                          f"as_of registers a gameflow store: {paths}")

    def test_injection_does_not_move_the_snapshot_at_any_t(self):
        with _RedirectedDataDir() as data:
            for t in (T_BEFORE_GAME, T_LONG_AFTER):
                with self.subTest(t=t):
                    clean = _snapshot_bytes(t)
                    # Determinism first: the byte comparison presumes it.
                    self.assertEqual(clean, _snapshot_bytes(t))

                    store = data.root / "processed" / f"gameflow_2026.jsonl"
                    _write_jsonl(store, _tamper_rows(
                        "2026-09-02T14:00:00+00:00"))
                    self.assertTrue(store.exists())
                    self.assertEqual(
                        clean, _snapshot_bytes(t),
                        "as_of surfaced gameflow data -- the decision path "
                        "can see the outcome of the game it is deciding")
                    store.unlink()

    def test_the_same_payload_DOES_move_a_snapshot_through_a_read_store(self):
        """The tamper detector proving it can fire (test_validation_pit.py's
        own argument): identical bytes only mean 'refused' if this passes."""
        with _RedirectedDataDir() as data:
            clean = _snapshot_bytes(T_LONG_AFTER)
            _write_jsonl(data.root / "processed" / "weather_forecast.jsonl", [{
                "game_pk": GAME_PK,
                "observed_utc": "2026-09-02T15:30:00+00:00",
                "temp_f": 999, "wind_mph": 999, "roof": "closed",
            }])
            self.assertNotEqual(clean, _snapshot_bytes(T_LONG_AFTER))

    def test_gameflow_filename_is_not_swept_up_by_the_boxscore_glob(self):
        from src.engine import settle_slate
        pattern = Path(settle_slate.BOXSCORES_GLOB).name
        self.assertTrue(pattern.startswith("boxscores_"))
        self.assertFalse(Path("gameflow_2026.jsonl").match(pattern))


class TestDecisionPathDoesNotImportGameflow(unittest.TestCase):
    """No module the engine decides through may import the gameflow store."""

    DECISION_PATH = (
        "src/engine/analyze.py", "src/engine/slate.py", "src/engine/glue.py",
        "src/engine/features.py", "src/engine/adversaries.py",
        "src/core/asof.py", "src/board/record.py", "src/board/project.py",
        "src/model/dataset.py", "src/model/pointintime.py",
        "src/research/matrix.py",
        # The mechanism-check lane's two decision-path additions. These are
        # the modules that WRITE the post-game predicates, at decision time,
        # and they are the likeliest place for someone to reach for the
        # answer while authoring the question: a predicate that consulted the
        # game it predicts would be the most complete leak available.
        "src/engine/mechanism_predicates.py",
        "src/engine/adapters/evolab_system.py",
    )

    def test_no_decision_path_module_imports_gameflow(self):
        root = Path(__file__).resolve().parent.parent
        for relative in self.DECISION_PATH:
            path = root / relative
            if not path.exists():
                continue
            with self.subTest(module=relative):
                imported = _imported_modules(path)
                self.assertFalse(
                    [n for n in imported if "gameflow" in n],
                    f"{relative} imports the post-game gameflow store")

    def test_the_settlement_side_evaluator_is_not_on_the_decision_path(self):
        """`src/review/mechanism_eval.py` reads play-by-play and therefore
        belongs to settlement alone. Nothing the engine decides through may
        import it -- the predicates it evaluates are the decision path's
        half, and that module (mechanism_predicates) must not import it back.
        """
        root = Path(__file__).resolve().parent.parent
        for relative in self.DECISION_PATH:
            path = root / relative
            if not path.exists():
                continue
            with self.subTest(module=relative):
                imported = _imported_modules(path)
                self.assertFalse(
                    [n for n in imported if "mechanism_eval" in n],
                    f"{relative} imports the settlement-side evaluator")

    def test_the_predicate_author_reads_no_result_store_of_any_kind(self):
        """Belt and braces on the same boundary: the module that freezes a
        prediction must not import gameflow, the boxscore pipeline, the
        results history, or the settlement runner."""
        root = Path(__file__).resolve().parent.parent
        imported = _imported_modules(
            root / "src/engine/mechanism_predicates.py")
        forbidden = [n for n in imported
                     if any(bad in n for bad in
                            ("gameflow", "boxscore", "settle", "history",
                             "mechanism_eval", "postmortem"))]
        self.assertFalse(forbidden,
                          f"the predicate author imports {forbidden}")

    def test_gameflow_itself_does_not_import_the_decision_path(self):
        root = Path(__file__).resolve().parent.parent
        imported = _imported_modules(root / "src/pipeline/gameflow.py")
        self.assertFalse([n for n in imported if "engine" in n])


class TestGameflowCostsZeroOddsCredits(unittest.TestCase):

    def test_the_module_never_imports_the_odds_provider_or_credit_log(self):
        """By IMPORT, not by substring -- both modules discuss the odds
        provider and the credit log in prose, which is the point."""
        root = Path(__file__).resolve().parent.parent
        for relative in ("src/pipeline/gameflow.py", "src/review/postmortem.py"):
            with self.subTest(module=relative):
                imported = _imported_modules(root / relative)
                offenders = [n for n in imported
                             if "providers.odds" in n or "creditlog" in n]
                self.assertFalse(offenders,
                                  f"{relative} imports {offenders} -- a "
                                  "post-game path must never reach a paid one")

    def test_the_endpoints_are_on_the_free_keyless_mlb_host(self):
        self.assertTrue(mlb.API_HOST.startswith("https://statsapi.mlb.com"))
        captured = []

        def fake_get_json(path, params=None, timeout=None):
            captured.append(path)
            return {"allPlays": []} if "playByPlay" in path else []

        original = mlb._get_json
        mlb._get_json = fake_get_json
        try:
            mlb.fetch_play_by_play(GAME_PK)
            mlb.fetch_win_probability(GAME_PK)
        finally:
            mlb._get_json = original
        self.assertEqual(captured, [f"game/{GAME_PK}/playByPlay",
                                     f"game/{GAME_PK}/winProbability"])

    def test_a_full_ingest_writes_no_credit_log_row(self):
        from src.pipeline import creditlog
        with _RedirectedDataDir() as data:
            credit_log = data.root / "processed" / "credit_log.jsonl"
            store = data.root / "processed" / "gameflow_2026.jsonl"
            report = gameflow.ingest_date(
                "2026-09-02", path=store,
                fetch_results=lambda day, timeout=20: {
                    "final": [{"game_pk": GAME_PK}]},
                fetch_play_by_play=lambda pk, timeout=20: make_play_by_play(
                    SIMPLE_PLAYS),
                fetch_win_probability=lambda pk, timeout=20:
                    make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT),
                sleep=lambda _s: None)
            self.assertEqual(report["games_written"], 1)
            self.assertFalse(credit_log.exists(),
                              "gameflow ingest wrote a credit-log row -- it "
                              "must never touch the odds quota")
            self.assertEqual(creditlog.read(credit_log), [])


if __name__ == "__main__":
    unittest.main()
