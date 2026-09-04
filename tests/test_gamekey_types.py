"""Regression tests for the game_pk type-normalization fix (see
`src.core.asof.game_pk_key`'s docstring for the canonical-type decision).

Before this fix, `src.board.gamekey.resolve_event` wrote `game_pk` as a
native JSON int (whatever `src.providers.mlb.fetch_games` returned) while
`src.engine.glue.GameRef.game_pk` and `data/watch/*.jsonl`'s own rows were
read/compared inconsistently -- a mixed-type comparison could, in
principle, silently match nothing. `game_pk_key` is now the ONE coercion
point every reader goes through, so a store holding one JSON type for
`game_pk` and another store holding the other type for the SAME logical
game must still join correctly.

The real, on-disk regression this bug actually caused was narrower than a
literal comparison failure (every comparison already happened to coerce
with an ad hoc `str(...)`): `src.engine.glue.build_snapshot`'s
`lineup_posted` parameter defaulted to `False` and was never derived from
the `as_of` read it already performs, so `src.evolab.decide`'s
`require_lineup` eligibility gate declined on every live decision
regardless of whether a lineup had actually posted. `TestRealDecisionPath`
below proves that is fixed against the real, captured stores this project
has on disk for a real, close-to-first-pitch 2026 game.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.board import gamekey
from src.core import asof as asof_module
from src.engine import features as features_module
from src.engine import glue

# The exact game the bug report's own reproduction script used: a real,
# captured 2026 game with a posted lineup ~2h50m before first pitch.
REAL_EVENT_ID = "0b0373954f04c35c2aaee9aed8171c17"

# features_module.build_features's live branch needs the handedness cache
# and statcast pitch store (both under the gitignored data/historical/,
# per .gitignore's `data/historical/*` rule -- purchased/rebuilt data, not
# something a fresh checkout carries) to compute *_lineup_platoon_share at
# all; asof_module.as_of reads only the tracked forward-capture stores
# (lineups_watch etc.), so a checkout missing data/historical/ makes the
# two readers disagree for a reason that has nothing to do with the
# game_pk join this test exists to prove -- a missing precondition, not a
# broken assertion. Checked via FeatureSources()'s own defaults so this can
# never drift from the real ones.
_HANDEDNESS_AND_STATCAST_PRESENT = (
    Path(features_module.FeatureSources().handedness_path).exists()
    and Path(features_module.FeatureSources().statcast_store).exists())
_HANDEDNESS_AND_STATCAST_REASON = (
    "requires the gitignored data/historical/{handedness.json,statcast/} "
    "stores that build_features' live branch reads")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class TestGamePkKeyCoercion(unittest.TestCase):
    """`src.core.asof.game_pk_key` itself: every shape a store on disk is
    known to actually produce folds onto the same canonical string."""

    def test_int_and_matching_numeric_string_agree(self):
        self.assertEqual(asof_module.game_pk_key(824717), "824717")
        self.assertEqual(asof_module.game_pk_key("824717"), "824717")
        self.assertEqual(asof_module.game_pk_key(824717),
                         asof_module.game_pk_key("824717"))

    def test_whitespace_and_whole_float_normalize_too(self):
        self.assertEqual(asof_module.game_pk_key(" 824717 "), "824717")
        self.assertEqual(asof_module.game_pk_key(824717.0), "824717")

    def test_none_and_empty_string_are_honestly_none(self):
        self.assertIsNone(asof_module.game_pk_key(None))
        self.assertIsNone(asof_module.game_pk_key(""))
        self.assertIsNone(asof_module.game_pk_key("   "))

    def test_bool_is_rejected_never_silently_a_key(self):
        # bool is an int subclass in Python -- without an explicit guard,
        # `game_pk_key(True)` would silently become "1" and could collide
        # with a real game_pk of 1.
        with self.assertRaises(asof_module.AsOfError):
            asof_module.game_pk_key(True)


class TestMixedTypeJoinAcrossStores(unittest.TestCase):
    """The literal scenario the bug report named: the event_id->game_pk map
    holds one JSON type for `game_pk`, `data/watch/*.jsonl` holds the
    other, for the SAME logical game. The join must still resolve."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_int_valued_map_matches_string_keyed_watch_store(self):
        # The map (src.board.gamekey's own store) holds a native int, as
        # every row written before S1's string normalization still does
        # (the store is append-only -- see game_pk_for_event's docstring).
        game_pk_map = {"evt-mixed": {"game_pk": 555, "resolved": True,
                                     "ambiguous": False}}
        # The watch store holds the SAME game keyed as a string.
        lineups_path = self.tmp / "lineups_watch.jsonl"
        _write_jsonl(lineups_path, [
            {"game_pk": "555", "observed_utc": "2026-06-01T17:00:00Z",
             "home_lineup": [1, 2, 3], "away_lineup": [4, 5, 6]},
        ])
        stores = [asof_module.StoreSpec(
            name="lineups_watch", path=lineups_path,
            game_key_of=lambda r: asof_module.game_pk_key(r.get("game_pk")),
            time_of=lambda r: r.get("observed_utc"),
            fields={"home_lineup": lambda r: r.get("home_lineup") or None,
                    "away_lineup": lambda r: r.get("away_lineup") or None},
        )]

        ref = glue._resolve_ref("evt-mixed", game_pk_map)
        self.assertEqual(ref.game_pk, "555")
        self.assertIsInstance(ref.game_pk, str)

        snapshot = glue.build_snapshot(
            ref, "2026-06-01T18:00:00Z", as_of_stores=stores)
        self.assertTrue(snapshot.lineup_posted)
        self.assertIn("A:home_lineup", snapshot.assumption_exposure)
        self.assertIn("A:away_lineup", snapshot.assumption_exposure)

    def test_string_valued_map_matches_int_keyed_watch_store(self):
        # The reverse mismatch: map already normalized to a string,
        # watch store still a native int (matching the real on-disk
        # convention of data/watch/*.jsonl, which never changed).
        game_pk_map = {"evt-mixed2": {"game_pk": "777", "resolved": True,
                                      "ambiguous": False}}
        lineups_path = self.tmp / "lineups_watch.jsonl"
        _write_jsonl(lineups_path, [
            {"game_pk": 777, "observed_utc": "2026-06-01T17:00:00Z",
             "home_lineup": [1, 2, 3], "away_lineup": [4, 5, 6]},
        ])
        stores = [asof_module.StoreSpec(
            name="lineups_watch", path=lineups_path,
            game_key_of=lambda r: asof_module.game_pk_key(r.get("game_pk")),
            time_of=lambda r: r.get("observed_utc"),
            fields={"home_lineup": lambda r: r.get("home_lineup") or None,
                    "away_lineup": lambda r: r.get("away_lineup") or None},
        )]

        ref = glue._resolve_ref("evt-mixed2", game_pk_map)
        snapshot = glue.build_snapshot(
            ref, "2026-06-01T18:00:00Z", as_of_stores=stores)
        self.assertTrue(snapshot.lineup_posted)

    def test_game_pk_for_event_normalizes_a_legacy_int_row_on_read(self):
        # A row written by resolve_event before the string-normalization
        # fix still holds a native int on disk (append-only store) --
        # game_pk_for_event must still hand back the canonical string.
        index = {"evt-legacy": {"game_pk": 888, "resolved": True}}
        pk = gamekey.game_pk_for_event("evt-legacy", index)
        self.assertEqual(pk, "888")
        self.assertIsInstance(pk, str)


class TestRealDecisionPath(unittest.TestCase):
    """Against the REAL, on-disk stores (no fixtures): the exact game and
    instant the bug report's own reproduction script used."""

    def _ref_and_t(self):
        ref = glue._resolve_ref(REAL_EVENT_ID, None)
        commence = glue.commence_time_for(ref)
        if commence is None:
            self.skipTest(
                f"commence_time unknown for {REAL_EVENT_ID!r} in this "
                "worktree's data -- cannot run the real-store assertion")
        t = (dt.datetime.fromisoformat(commence.replace("Z", "+00:00"))
             - dt.timedelta(minutes=30))
        return ref, t.isoformat()

    def test_as_of_returns_non_empty_fields_for_a_real_recent_game(self):
        ref, t = self._ref_and_t()
        if ref.asof_key is None:
            self.skipTest(f"{REAL_EVENT_ID!r} has no resolved game_pk in "
                          "this worktree's event_game_map.jsonl")
        snapshot = asof_module.as_of(ref.asof_key, t)
        self.assertTrue(snapshot.fields,
                        "as_of found nothing for a game with real captures "
                        "on disk -- the game_pk join is silently failing")
        self.assertIsNotNone(snapshot.get("home_lineup"))
        self.assertIsNotNone(snapshot.get("away_lineup"))

    def test_lineup_posted_is_true_before_first_pitch_with_a_real_lineup(self):
        ref, t = self._ref_and_t()
        snap = glue.build_snapshot(ref, t)
        self.assertTrue(
            snap.lineup_posted,
            "a real lineup is on disk well before first pitch for this "
            "game, but build_snapshot reported lineup_posted=False")

    @unittest.skipUnless(_HANDEDNESS_AND_STATCAST_PRESENT,
                        _HANDEDNESS_AND_STATCAST_REASON)
    def test_build_features_and_as_of_agree_on_lineup_presence(self):
        """Two independent readers of the SAME forward stores for the SAME
        game at the SAME instant must never disagree on whether a lineup
        was known -- exactly the divergence a game_pk join bug would cause
        (one reader's key matching, the other's silently not)."""
        ref, t = self._ref_and_t()
        if ref.asof_key is None:
            self.skipTest(f"{REAL_EVENT_ID!r} has no resolved game_pk in "
                          "this worktree's event_game_map.jsonl")
        snapshot = asof_module.as_of(ref.asof_key, t)
        as_of_knows_lineup = (snapshot.get("home_lineup") is not None
                              and snapshot.get("away_lineup") is not None)

        features = features_module.build_features(ref, t)
        features_know_lineup = any(
            name.endswith("_lineup_platoon_share") for name in features)

        self.assertEqual(
            as_of_knows_lineup, features_know_lineup,
            f"as_of lineup-known={as_of_knows_lineup} but "
            f"build_features lineup-known={features_know_lineup} for the "
            "same game/instant -- the two readers disagree")


if __name__ == "__main__":
    unittest.main()
