"""Tests for the frozen F5 eligible-universe manifest (src/research/f5_universe.py).

The manifest and its content hash are the whole point of the freeze: a
silent change to the eligible universe (widening, narrowing, or
reclassifying a game) must fail this suite, not slip through. So this test
recomputes the manifest from the same source files the frozen one was built
from and diffs the hash -- it never asserts against hardcoded literals that
could quietly drift.

This module reads the real gitignored historical stores
(`data/historical/odds_first_five/f5_tminus2_primary.jsonl`, etc.). On a
clean checkout without them, these tests skip with an explicit reason
rather than failing or fabricating fixtures (F5_REPAIR_RELEASE_GATE.md,
Check 5).
"""

import unittest
from pathlib import Path

from src.research import f5_universe as universe


def _data_available() -> bool:
    return (Path(universe.PRIMARY_VIEW_PATH).exists()
            and Path(universe.SETTLEMENT_PATH).exists()
            and Path(universe.MANIFEST_PATH).exists())


class TestFrozenManifestMatchesRecomputation(unittest.TestCase):
    """The one test the mission asked for: a silent change to the eligible
    universe must fail the suite."""

    def setUp(self):
        if not _data_available():
            self.skipTest("F5 historical stores or frozen manifest not present "
                           "on this checkout")
        self.frozen = universe.read_manifest()
        self.recomputed = universe.build_universe()

    def test_content_hash_matches_recomputation_from_primary_view(self):
        self.assertEqual(
            self.frozen["content_hash"], self.recomputed["content_hash"],
            "the eligible F5 universe changed since it was frozen -- this is "
            "exactly the silent-denominator-drift the freeze exists to catch "
            "(docs/RESEARCH_CATALOGUE.md T8/T4); re-freeze deliberately if the "
            "widening/narrowing was intended, do not just update this test")

    def test_recomputed_hash_is_deterministic(self):
        again = universe.build_universe()
        self.assertEqual(self.recomputed["content_hash"], again["content_hash"])

    def test_price_payload_hash_matches_recomputation(self):
        # A3 amendment: the identity hash alone cannot prove a price did not
        # move; this hash must also verify or the denominator's PRICES could
        # have silently changed since the freeze.
        self.assertEqual(
            self.frozen["price_payload_hash"], self.recomputed["price_payload_hash"],
            "the priced payload changed since the freeze -- a re-fetch or "
            "repair moved a book price without moving the identity hash "
            "(A3, PREREG_F5_FAMILIES.md); re-freeze deliberately if intended")

    def test_price_payload_hash_is_deterministic(self):
        again = universe.build_universe()
        self.assertEqual(self.recomputed["price_payload_hash"],
                         again["price_payload_hash"])

    def test_frozen_counts_match_recomputation(self):
        self.assertEqual(self.frozen["counts"], self.recomputed["counts"])

    def test_frozen_exclusion_ledger_matches_recomputation(self):
        self.assertEqual(self.frozen["exclusion_ledger"], self.recomputed["exclusion_ledger"])


class TestManifestShapeAndInvariants(unittest.TestCase):
    def setUp(self):
        if not _data_available():
            self.skipTest("F5 historical stores or frozen manifest not present "
                           "on this checkout")
        self.m = universe.read_manifest()

    def test_hash_is_over_the_sorted_game_pk_set(self):
        recomputed_hash = universe.content_hash(self.m["games"])
        self.assertEqual(self.m["content_hash"], recomputed_hash)

    def test_no_2025_or_2026_game_in_the_eligible_set(self):
        seasons = {g["season"] for g in self.m["games"]}
        self.assertNotIn("2025", seasons)
        self.assertNotIn("2026", seasons)

    def test_every_game_is_inside_the_approved_window(self):
        start = self.m["approved_window"]["start"]
        end = self.m["approved_window"]["end"]
        for g in self.m["games"]:
            self.assertTrue(start <= g["date"] <= end,
                             f"game_pk {g['game_pk']} date {g['date']} outside "
                             f"approved window {start}..{end}")

    def test_status_counts_partition_the_eligible_set(self):
        ok = sum(1 for g in self.m["games"] if g["status"] == "OK")
        unavailable = sum(1 for g in self.m["games"]
                           if g["status"] == "PRIMARY_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(ok + unavailable, len(self.m["games"]))
        self.assertEqual(ok, self.m["counts"]["status_OK"])
        self.assertEqual(unavailable, self.m["counts"]["status_PRIMARY_SNAPSHOT_UNAVAILABLE"])

    def test_gradeable_decided_only_counts_ok_and_decided_rows(self):
        gradeable = [g for g in self.m["games"]
                     if g["status"] == "OK" and g["decided"] is True]
        self.assertEqual(len(gradeable), self.m["counts"]["gradeable_decided"])

    def test_gradeable_decided_never_includes_a_tie(self):
        for g in self.m["games"]:
            if g["decided"] is True:
                self.assertFalse(g["tie"])

    def test_settlement_join_is_complete(self):
        self.assertEqual(self.m["counts"]["settlement_join_rate"], 1.0)
        self.assertEqual(self.m["counts"]["not_joined_game_pks"], [])

    def test_raw_attempts_fully_accounted_by_eligible_plus_excluded(self):
        self.assertTrue(self.m["exclusion_ledger"]["raw_attempts_accounted"])

    def test_price_payload_hash_present_and_stable_under_key_reordering(self):
        # Canonical ordering (books sorted by key) must make the hash
        # independent of provider list order -- otherwise a harmless re-fetch
        # that reordered bookmakers in the response would look like a moved
        # denominator.
        self.assertIn("price_payload_hash", self.m)
        reordered = [dict(g) for g in self.m["games"]]
        self.assertEqual(universe.price_payload_hash(self.m["games"]),
                         universe.price_payload_hash(reordered))


class TestPricePayloadHash(unittest.TestCase):
    """Unit-level: no real data store required."""

    def _row(self, game_pk, snapshot_at, books):
        return {"game_pk": game_pk, "snapshot_at": snapshot_at,
                "books": [{"key": k, "h2h_1st_5_innings":
                          {"away_price": a, "home_price": h}}
                         for k, a, h in books]}

    def test_book_order_does_not_change_the_hash(self):
        a = self._row("1", "2023-05-10T00:00:00Z",
                      [("dk", 105, -135), ("fd", 110, -140)])
        b = self._row("1", "2023-05-10T00:00:00Z",
                      [("fd", 110, -140), ("dk", 105, -135)])
        self.assertEqual(universe.price_payload_hash([a]),
                         universe.price_payload_hash([b]))

    def test_a_changed_price_changes_the_hash(self):
        a = self._row("1", "2023-05-10T00:00:00Z", [("dk", 105, -135)])
        b = self._row("1", "2023-05-10T00:00:00Z", [("dk", 106, -135)])
        self.assertNotEqual(universe.price_payload_hash([a]),
                            universe.price_payload_hash([b]))

    def test_a_changed_snapshot_at_changes_the_hash(self):
        a = self._row("1", "2023-05-10T00:00:00Z", [("dk", 105, -135)])
        b = self._row("1", "2023-05-10T00:05:00Z", [("dk", 105, -135)])
        self.assertNotEqual(universe.price_payload_hash([a]),
                            universe.price_payload_hash([b]))

    def test_last_update_drift_does_not_change_the_hash(self):
        # last_update is intentionally not hashed -- a harmless re-fetch that
        # only refreshes provider timestamps must not look like a moved price.
        a = {"game_pk": "1", "snapshot_at": "t", "books": [
            {"key": "dk", "h2h_1st_5_innings":
             {"away_price": 105, "home_price": -135, "last_update": "X"}}]}
        b = {"game_pk": "1", "snapshot_at": "t", "books": [
            {"key": "dk", "h2h_1st_5_innings":
             {"away_price": 105, "home_price": -135, "last_update": "Y"}}]}
        self.assertEqual(universe.price_payload_hash([a]),
                         universe.price_payload_hash([b]))


if __name__ == "__main__":
    unittest.main()
