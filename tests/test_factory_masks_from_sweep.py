"""scripts/factory_masks_from_sweep.py -- unit tests against synthetic
inputs, never against the real historical stores (those are gitignored
local data, absent in a fresh checkout -- see tests/slow_modules.txt's own
note on this). What IS asserted here: the bin/index writer round-trips
exactly, and the two provable-mismatch guards (`ReplayMismatch`) actually
fire rather than silently accepting a replayed world/genome-space that
disagrees with the artifact it claims to reconstruct.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

from src.evolab import placebo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "factory_masks_from_sweep.py")

_spec = importlib.util.spec_from_file_location("factory_masks_from_sweep", SCRIPT_PATH)
masks_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(masks_mod)


def _tiny_world(n_games=5) -> "placebo.World":
    games = [
        placebo.make_game(
            game_id=f"g{i}", date=f"2024-01-{i + 1:02d}", season=2024,
            home_team="H", away_team="A", home_price=-110, away_price=-110,
            home_won=None, features={})
        for i in range(n_games)
    ]
    return placebo.real_world(games, world_id="TESTWORLD")


class TestWriteBinAndIndexRoundTrips(unittest.TestCase):

    def test_bin_and_index_decode_back_to_the_same_masks(self):
        world = _tiny_world(5)
        masks = {"strat_a": (0b10101, 0b01010), "strat_b": (0b00001, 0b11110)}
        artifact = {"n_strategies_real": 2,
                   "config": {"min_selections": 1}}
        with tempfile.TemporaryDirectory() as tmp:
            orig_out_dir, orig_artifact = masks_mod.OUT_DIR, masks_mod.ARTIFACT_PATH
            masks_mod.OUT_DIR = type(orig_out_dir)(tmp)
            try:
                bin_path, index_path = masks_mod._write_bin_and_index(
                    masks, world, artifact, spec_hash="deadbeef" * 8,
                    decision_digest="abc123", elapsed_s=1.23)
            finally:
                masks_mod.OUT_DIR = orig_out_dir
                masks_mod.ARTIFACT_PATH = orig_artifact

            with open(index_path, encoding="utf-8") as fh:
                index = json.load(fh)
            with open(bin_path, "rb") as fh:
                data = fh.read()

            self.assertEqual(index["n_games"], 5)
            self.assertEqual(index["strategy_order"], ["strat_a", "strat_b"])
            n_bytes = index["bytes_per_mask"]
            rec = index["bytes_per_strategy"]
            self.assertEqual(len(data), rec * len(index["strategy_order"]))
            for i, sid in enumerate(index["strategy_order"]):
                chunk = data[i * rec:(i + 1) * rec]
                away = int.from_bytes(chunk[:n_bytes], "little")
                home = int.from_bytes(chunk[n_bytes:2 * n_bytes], "little")
                self.assertEqual((away, home), masks[sid])

    def test_index_records_that_no_outcome_was_read(self):
        world = _tiny_world(3)
        masks = {"s": (0b1, 0b0)}
        artifact = {"n_strategies_real": 1, "config": {"min_selections": 1}}
        with tempfile.TemporaryDirectory() as tmp:
            orig_out_dir = masks_mod.OUT_DIR
            masks_mod.OUT_DIR = type(orig_out_dir)(tmp)
            try:
                _bin_path, index_path = masks_mod._write_bin_and_index(
                    masks, world, artifact, spec_hash="ab" * 32,
                    decision_digest="digest", elapsed_s=0.1)
            finally:
                masks_mod.OUT_DIR = orig_out_dir
            with open(index_path, encoding="utf-8") as fh:
                index = json.load(fh)
        self.assertIn("no game outcome was read", index["note"])


class TestReplayMismatchGuards(unittest.TestCase):
    """`main()`'s two provable-mismatch checks -- digest and spec_hash --
    each refuse rather than silently accept a replay that disagrees with
    the artifact it is supposed to reconstruct.
    """

    def setUp(self):
        self.world = _tiny_world(4)
        self.artifact = {
            "real_world_id": "REAL",
            "n_strategies_real": 0,
            "enumeration_spec_hash": "expected_spec_hash",
            "replay_manifest": {"decision_digest": "expected_digest"},
            "config": {"eligibility": None, "routings": None,
                      "execution": "CONSENSUS_EXECUTION", "max_signals": 3,
                      "min_selections": 30},
        }

    def _run_main_with(self, *, world_digest, spec_hash, artifact_path):
        with open(artifact_path, "w", encoding="utf-8") as fh:
            json.dump(self.artifact, fh)
        orig_artifact_path = masks_mod.ARTIFACT_PATH
        orig_rebuild_world = masks_mod._rebuild_world
        orig_rebuild_genomes = masks_mod._rebuild_genomes
        masks_mod.ARTIFACT_PATH = type(orig_artifact_path)(artifact_path)
        masks_mod._rebuild_world = lambda artifact: (self.world, world_digest)
        masks_mod._rebuild_genomes = lambda artifact: ([], spec_hash)
        try:
            return masks_mod.main([])
        finally:
            masks_mod.ARTIFACT_PATH = orig_artifact_path
            masks_mod._rebuild_world = orig_rebuild_world
            masks_mod._rebuild_genomes = orig_rebuild_genomes

    def test_digest_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sweep-fake-REAL.json")
            with self.assertRaises(masks_mod.ReplayMismatch):
                self._run_main_with(world_digest="WRONG", spec_hash="x",
                                   artifact_path=path)

    def test_spec_hash_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sweep-fake-REAL.json")
            with self.assertRaises(masks_mod.ReplayMismatch):
                self._run_main_with(world_digest="expected_digest",
                                   spec_hash="WRONG_SPEC",
                                   artifact_path=path)


if __name__ == "__main__":
    unittest.main()
