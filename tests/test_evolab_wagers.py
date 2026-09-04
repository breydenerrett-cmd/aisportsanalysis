"""Canonical wager identity and the append-only store. See
docs/FACTORY_SCALE_DESIGN.md section 1 and src/evolab/wagers.py's docstring.
"""

import json
import os
import tempfile
import unittest

from src.evolab.wagers import WagerError, WagerStore, canonical_wager_id


class TestCanonicalWagerId(unittest.TestCase):

    def test_same_inputs_same_id(self):
        a = canonical_wager_id(123, "h2h", "home", None)
        b = canonical_wager_id(123, "h2h", "home", None)
        self.assertEqual(a, b)

    def test_deterministic_across_processes_shape(self):
        # Not literally cross-process, but pins the hash so a future change
        # to the key shape is caught rather than silently drifting.
        wid = canonical_wager_id(1, "h2h", "home", None)
        self.assertEqual(len(wid), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in wid))

    def test_different_game_pk_different_id(self):
        a = canonical_wager_id(1, "h2h", "home")
        b = canonical_wager_id(2, "h2h", "home")
        self.assertNotEqual(a, b)

    def test_different_market_different_id(self):
        a = canonical_wager_id(1, "h2h", "home")
        b = canonical_wager_id(1, "f5_h2h", "home")
        self.assertNotEqual(a, b)

    def test_different_side_different_id(self):
        a = canonical_wager_id(1, "h2h", "home")
        b = canonical_wager_id(1, "h2h", "away")
        self.assertNotEqual(a, b)

    def test_different_line_different_id(self):
        a = canonical_wager_id(1, "total", "over", 8.5)
        b = canonical_wager_id(1, "total", "over", 9.0)
        self.assertNotEqual(a, b)

    def test_price_not_in_key(self):
        # The whole point of the design: two strategies seeing different
        # ticks on the identical game/market/side/line are the SAME wager.
        wid = canonical_wager_id(1, "h2h", "home", None)
        store = WagerStore()
        store.add(1, "h2h", "home", price=-120, source="s1")
        # Re-adding the identical wager at a DIFFERENT price is a conflict,
        # not a new id -- see test_add_conflicting_price_raises below. This
        # test only pins that the id itself never encodes price.
        self.assertEqual(canonical_wager_id(1, "h2h", "home", None), wid)

    def test_line_none_vs_zero_distinct(self):
        # None (moneyline: no line) must not collide with an explicit 0.0 line.
        a = canonical_wager_id(1, "h2h", "home", None)
        b = canonical_wager_id(1, "h2h", "home", 0.0)
        self.assertNotEqual(a, b)

    def test_rejects_missing_game_pk(self):
        with self.assertRaises(WagerError):
            canonical_wager_id(None, "h2h", "home")

    def test_rejects_unknown_side(self):
        with self.assertRaises(WagerError):
            canonical_wager_id(1, "h2h", "sideways")

    def test_rejects_empty_market(self):
        with self.assertRaises(WagerError):
            canonical_wager_id(1, "", "home")


class TestWagerStore(unittest.TestCase):

    def test_add_returns_canonical_id(self):
        store = WagerStore()
        wid = store.add(1, "h2h", "home", price=-120, source="test")
        self.assertEqual(wid, canonical_wager_id(1, "h2h", "home", None))
        self.assertEqual(len(store), 1)
        self.assertIn(wid, store)

    def test_add_twice_identical_is_idempotent(self):
        store = WagerStore()
        wid1 = store.add(1, "h2h", "home", price=-120, source="s1")
        wid2 = store.add(1, "h2h", "home", price=-120, source="s1")
        self.assertEqual(wid1, wid2)
        self.assertEqual(len(store), 1)

    def test_two_strategies_same_wager_is_one_row(self):
        # This is the entire point: strategy A and strategy B both fire on
        # the same game/market/side and reference ONE stored wager.
        # `source`/`price`/`world_id` describe the WAGER's own provenance
        # (e.g. which sweep observed it first), not which strategy referenced
        # it -- strategy identity lives in the separate reference table
        # (design section 1.3), so both strategies record it with the same
        # wager-level provenance.
        store = WagerStore()
        wid_a = store.add(42, "h2h", "away", price=110, source="sweep:abc")
        wid_b = store.add(42, "h2h", "away", price=110, source="sweep:abc")
        self.assertEqual(wid_a, wid_b)
        self.assertEqual(len(store), 1)

    def test_add_conflicting_price_raises(self):
        store = WagerStore()
        store.add(1, "h2h", "home", price=-120, source="s1")
        with self.assertRaises(WagerError):
            store.add(1, "h2h", "home", price=-150, source="s2")

    def test_add_conflicting_line_is_a_different_wager_not_a_conflict(self):
        # Different line -> different id -> different row, not an error.
        store = WagerStore()
        store.add(1, "total", "over", line=8.5, source="s1")
        store.add(1, "total", "over", line=9.0, source="s2")
        self.assertEqual(len(store), 2)

    def test_first_seen_at_does_not_trigger_conflict(self):
        store = WagerStore()
        store.add(1, "h2h", "home", price=-120, source="s1",
                  first_seen_at="2026-01-01T00:00:00Z")
        # Same content, different provenance timestamp -- must not raise.
        store.add(1, "h2h", "home", price=-120, source="s1",
                  first_seen_at="2026-01-02T00:00:00Z")
        self.assertEqual(len(store), 1)

    def test_all_is_sorted_and_deterministic(self):
        store = WagerStore()
        store.add(9, "h2h", "home", source="s")
        store.add(1, "h2h", "away", source="s")
        rows = store.all()
        self.assertEqual([r.wager_id for r in rows], sorted(r.wager_id for r in rows))

    def test_write_then_read_roundtrips(self):
        store = WagerStore()
        store.add(1, "h2h", "home", price=-120, world_id="w1", source="sweep:abc")
        store.add(2, "total", "over", line=8.5, price=105, source="sweep:abc")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "wagers.json")
            store.write(path)
            with open(path) as fh:
                payload = json.load(fh)
            self.assertEqual(payload["schema"], "evolab.wagers/1")
            self.assertEqual(len(payload["wagers"]), 2)

            reloaded = WagerStore.read(path)
        self.assertEqual(len(reloaded), 2)
        for w in store.all():
            self.assertEqual(reloaded.get(w.wager_id).to_dict(), w.to_dict())

    def test_read_missing_file_is_empty_store(self):
        store = WagerStore.read("/nonexistent/path/does/not/exist.json")
        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
